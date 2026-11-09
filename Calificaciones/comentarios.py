"""Comentarios por periodo y boleta de comentarios (pedido del 2026-11-09).

- Cada docente escribe un comentario por estudiante en cada materia que le imparte, en cada periodo. La lista es la real
  de la clase en el periodo (Alumnos/clases.py): en un grupo de clase de un bloque simultáneo, sus integrantes aunque
  vengan de varios grupos base.
- Uno solo por estudiante, materia cursada y periodo (restricción en la base). La materia es la del plan del estudiante
  (en una clase que mezcla grados, su equivalencia), así que si en el periodo cambia de docente o de grupo se sigue
  escribiendo en el mismo registro y se conserva su autoría. Solo cuenta como capturado si tiene texto.
- Se captura cuando se capturan calificaciones: la persona puede capturar en la materia (Calificaciones/reglas.py), el
  ciclo es el actual, el periodo está abierto y su semestre o su bloque no lo impiden. Además, la boleta de
  comentarios del estudiante no debe estar publicada.
- La boleta de comentarios es aparte de la de calificaciones: se publica por estudiante cuando todas sus materias del
  periodo tienen comentario, y guarda lo publicado, que es lo que ven el estudiante y sus tutores en su portal. Para
  corregir un comentario publicado se reabre con motivo (permiso de reabrir calificaciones). Todo queda en la bitácora
  (`CambioComentario`) y la publicación y la reapertura también en la Bitácora de cambios.
"""
from dataclasses import dataclass, field

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from Alumnos.asistencia_docente import inscripciones_de
from Alumnos.clases import lista_de, materias_cursadas, sustituidos_todo_el_rango, tramos_de_asignacion
from Alumnos.models import EquivalenciaClase, Grado, Inscripcion, Periodo
from Alumnos.periodos import periodos_para_grado
from Usuarios.docentes import profesor_de
from Usuarios.seguridad import ACCION_CAMBIO, registrar

from . import reglas, semestres
from .models import BoletaComentarios, CambioComentario, ComentarioPeriodo, DatosOficialesNivel

PUBLICAR = 'Calificaciones.publicar_comentarios'
LIMITE = 2000   # caracteres de un comentario: cabe completo en la boleta impresa


class ComentarioRechazado(Exception):
    def __init__(self, mensaje):
        super().__init__(mensaje)
        self.mensaje = mensaje


def rango(periodo):
    """(primer día, último día) del periodo dentro de su ciclo."""
    ciclo = periodo.ciclo
    return max(periodo.fecha_inicio, ciclo.fecha_inicio), min(periodo.fecha_fin, ciclo.fecha_fin)


def limpiar(texto):
    """El comentario como se guarda: saltos de línea normales y sin espacios sobrantes al principio y al final."""
    return (texto or '').replace('\r\n', '\n').replace('\r', '\n').strip()


def version_de(comentario):
    """La versión del comentario con que se cargó la página ('' si todavía no existe)."""
    return str(comentario.version) if comentario is not None and comentario.pk else ''


def nombre_de_docente(usuario):
    """Como sale el autor en la boleta: el nombre de su ficha de profesor o, si no tiene, el de su cuenta."""
    profesor = profesor_de(usuario)
    if profesor is not None:
        return profesor.nombre_completo
    return usuario.get_full_name() or usuario.get_username()


# ---------------------------------------------------------------------------
# Quién cursa qué en el periodo
# ---------------------------------------------------------------------------
class Clases:
    """Quién está en cada clase durante un periodo, con una consulta por clase (se reutiliza entre estudiantes)."""

    def __init__(self, periodo):
        self.periodo = periodo
        self.desde, self.hasta = rango(periodo)
        self._clases = {}

    def _de(self, asignacion):
        if asignacion.pk not in self._clases:
            aplica = any(p.pk == self.periodo.pk for p in reglas.periodos_de(asignacion))
            if not aplica:
                datos = (False, set())
            elif asignacion.es_de_clase:
                datos = (True, set(tramos_de_asignacion(asignacion, self.desde, self.hasta)))
            else:
                datos = (True, set(sustituidos_todo_el_rango(asignacion, self.desde, self.hasta)))
            self._clases[asignacion.pk] = datos
        return self._clases[asignacion.pk]

    def cursa(self, inscripcion, asignacion):
        """Si el estudiante tomó esa clase en algún día del periodo (en su grupo base, si un bloque no se la sustituyó
        todo el periodo)."""
        if inscripcion.ciclo_id != asignacion.ciclo_id:
            return False
        aplica, inscripciones = self._de(asignacion)
        if not aplica:
            return False
        if asignacion.es_de_clase:
            return inscripcion.pk in inscripciones
        return inscripcion.grupo_id == asignacion.grupo_id and inscripcion.pk not in inscripciones


def equivalencias_de(asignacion):
    """{id de grado: materia del plan} de una clase que mezcla grados ({} si no es de clase)."""
    if not asignacion.es_de_clase:
        return {}
    return {e.grado_id: e.materia for e in EquivalenciaClase.objects.filter(clase=asignacion.clase).select_related('materia')}


def materia_para(asignacion, inscripcion, equivalencias):
    """La materia con que cuenta la clase para el estudiante: la de su plan."""
    return equivalencias.get(inscripcion.grado_id) or asignacion.materia


@dataclass
class MateriaDelPeriodo:
    """Una materia que el estudiante cursó en el periodo, con las clases en que la tomó y su comentario."""
    materia: object
    asignaciones: list
    comentario: object = None

    @property
    def actual(self):
        return self.asignaciones[-1]

    @property
    def capturada(self):
        return self.comentario is not None and self.comentario.capturado

    @property
    def docente_asignado(self):
        return self.actual.profesor.nombre_completo if self.actual.profesor_id else ''

    @property
    def docente(self):
        """El docente autor del comentario; sin comentario, el que tiene asignada la materia."""
        if self.capturada and self.comentario.docente:
            return self.comentario.docente
        return self.docente_asignado


def materias_del_periodo(inscripcion, periodo, clases=None):
    """Las materias del estudiante en el periodo, cada una una sola vez y con su comentario (orden alfabético)."""
    if inscripcion.ciclo_id != periodo.ciclo_id:
        return []
    clases = clases or Clases(periodo)
    materias = []
    for cursada in materias_cursadas(inscripcion):
        en_el_periodo = [a for a in cursada.asignaciones if clases.cursa(inscripcion, a)]
        if en_el_periodo:
            materias.append(MateriaDelPeriodo(cursada.materia, en_el_periodo))
    comentarios = {c.materia_id: c for c in ComentarioPeriodo.objects.filter(inscripcion=inscripcion, periodo=periodo)}
    for materia in materias:
        materia.comentario = comentarios.get(materia.materia.pk)
    return materias


def periodos_del_grado(grado, ciclo):
    """Los periodos de evaluación del grado en el ciclo: los de su nivel (en preparatoria por semestres, los de su
    semestre)."""
    periodos = list(periodos_para_grado(ciclo, grado))
    semestre = semestres.semestre_de_grado_en(grado, ciclo)
    if semestre is not None:
        periodos = [p for p in periodos if p.semestre_id == semestre.pk]
    return periodos


def periodos_de_inscripcion(inscripcion):
    return periodos_del_grado(inscripcion.grado, inscripcion.ciclo)


def inscripcion_del_periodo(alumno, periodo):
    """La inscripción del estudiante con la que cursó el periodo (None si no estuvo inscrito en ese nivel y ciclo)."""
    candidatas = list(Inscripcion.objects.filter(alumno=alumno, ciclo=periodo.ciclo_id, grado__nivel=periodo.nivel)
                      .select_related('ciclo', 'grado', 'grupo__nombre', 'grupo__grado').order_by('-activa', '-fecha_inscripcion', '-pk'))
    if periodo.semestre_id:
        candidatas = [i for i in candidatas if i.grado.semestre == periodo.semestre.clave]
    return candidatas[0] if candidatas else None


def periodos_del_alumno(alumno):
    """[(periodo, inscripción)] de todas sus inscripciones, del más reciente al más antiguo."""
    pares = []
    for inscripcion in Inscripcion.objects.filter(alumno=alumno).select_related('ciclo', 'grado', 'grupo__nombre', 'grupo__grado'):
        pares.extend((periodo, inscripcion) for periodo in periodos_de_inscripcion(inscripcion))
    return sorted(pares, key=lambda par: (par[0].ciclo.fecha_inicio, par[0].fecha_inicio, par[0].pk), reverse=True)


# ---------------------------------------------------------------------------
# La captura del docente
# ---------------------------------------------------------------------------
def motivo_de_solo_lectura(asignacion, periodo, usuario, hoy=None):
    """Por qué no se escriben comentarios en esa materia y periodo (texto) o '' si se puede."""
    hoy = hoy or timezone.localdate()
    if not reglas.puede_capturar(usuario, asignacion):
        return 'Solo consulta: no escribes los comentarios de esta materia.'
    bloqueo = semestres.bloqueo_de_captura(periodo) or reglas.bloqueo_de_clase(asignacion)
    if bloqueo:
        return bloqueo.replace('sus calificaciones', 'sus comentarios')
    if not asignacion.ciclo.activo:
        return f'El ciclo {asignacion.ciclo} no es el ciclo actual: sus comentarios son de solo lectura.'
    estado = periodo.estado_en(hoy)
    if estado == Periodo.CERRADO:
        return f'{periodo.nombre} está cerrado: ya no se escriben comentarios (dirección puede abrirlo unos días más desde Periodos).'
    if estado == Periodo.PROXIMO:
        return f'{periodo.nombre} todavía no empieza (se abre el {periodo.fecha_inicio:%d/%m/%Y}).'
    return ''


@dataclass
class FilaDeComentario:
    inscripcion: object
    numero: int
    materia: object                 # la del plan del estudiante
    comentario: object = None
    publicada: bool = False         # su boleta de comentarios del periodo ya se publicó
    salio: object = None            # el último día que estuvo, si dejó el grupo de clase en el periodo

    @property
    def nombre(self):
        alumno = self.inscripcion.alumno
        return ' '.join(p for p in (alumno.apellido_paterno, alumno.apellido_materno, alumno.nombre) if p)

    @property
    def texto(self):
        return self.comentario.texto if self.comentario is not None else ''

    @property
    def capturado(self):
        return self.comentario is not None and self.comentario.capturado

    @property
    def version(self):
        return version_de(self.comentario)


@dataclass
class Captura:
    asignacion: object
    periodo: object
    filas: list = field(default_factory=list)

    @property
    def capturados(self):
        return sum(1 for f in self.filas if f.capturado)

    @property
    def pendientes(self):
        return len(self.filas) - self.capturados

    @property
    def porcentaje(self):
        return round(100 * self.capturados / len(self.filas)) if self.filas else 0


def captura(asignacion, periodo):
    """Los estudiantes de la clase en el periodo (la lista real, con los que ya pasaron al semestre siguiente) con su
    comentario de la materia."""
    desde, hasta = rango(periodo)
    inscripciones = list(inscripciones_de(asignacion, con_concluidas=True, desde=desde, hasta=hasta)
                         .select_related('alumno', 'grado', 'grupo'))
    lista = lista_de(asignacion, desde, hasta)
    equivalencias = equivalencias_de(asignacion)
    comentarios = {(c.inscripcion_id, c.materia_id): c for c in ComentarioPeriodo.objects.filter(periodo=periodo, inscripcion__in=inscripciones)
                   .select_related('autor', 'actualizado_por')}
    publicadas = set(BoletaComentarios.objects.filter(periodo=periodo, inscripcion__in=inscripciones, publicada=True)
                     .values_list('inscripcion_id', flat=True))
    filas = []
    for numero, inscripcion in enumerate(inscripciones, 1):
        materia = materia_para(asignacion, inscripcion, equivalencias)
        filas.append(FilaDeComentario(
            inscripcion=inscripcion, numero=numero, materia=materia, comentario=comentarios.get((inscripcion.pk, materia.pk)),
            publicada=inscripcion.pk in publicadas, salio=lista.salida(inscripcion.pk, hasta) if lista.tramos else None,
        ))
    return Captura(asignacion=asignacion, periodo=periodo, filas=filas)


def _boleta_bloqueada(inscripcion, periodo):
    """El registro de la boleta del estudiante en el periodo, bloqueado mientras dura la transacción (se crea si no
    existe: así una publicación y un guardado simultáneos no se cruzan)."""
    try:
        with transaction.atomic():
            BoletaComentarios.objects.get_or_create(inscripcion=inscripcion, periodo=periodo)
    except IntegrityError:   # otra petición la creó al mismo tiempo
        pass
    return BoletaComentarios.objects.select_for_update().get(inscripcion=inscripcion, periodo=periodo)


def _guardar_uno(asignacion, periodo, fila, texto, version, usuario):
    """Guarda un comentario. Devuelve True si cambió, False si ya tenía ese texto."""
    boleta = _boleta_bloqueada(fila.inscripcion, periodo)
    if boleta.publicada:
        raise ComentarioRechazado('Su boleta de comentarios ya se publicó: para corregirlo, dirección la reabre con motivo.')
    comentario = (ComentarioPeriodo.objects.select_for_update()
                  .filter(inscripcion=fila.inscripcion, materia=fila.materia, periodo=periodo).first())
    anterior = comentario.texto if comentario is not None else ''
    if texto == anterior:
        return False
    if version != version_de(comentario):
        raise ComentarioRechazado('Alguien más cambió este comentario mientras escribías. Tu texto sigue aquí: revisa el actual y vuelve a guardar.')
    if comentario is None:
        comentario = ComentarioPeriodo(inscripcion=fila.inscripcion, materia=fila.materia, periodo=periodo)
    ahora = timezone.now()
    if texto and comentario.capturado_en is None:   # la autoría es de quien lo escribe primero y se conserva
        comentario.autor, comentario.docente, comentario.capturado_en = usuario, nombre_de_docente(usuario), ahora
    comentario.texto, comentario.asignacion = texto, asignacion
    comentario.actualizado_por, comentario.actualizado_en = usuario, ahora
    comentario.version += 1
    comentario.save()
    CambioComentario.objects.create(inscripcion=fila.inscripcion, periodo=periodo, materia=fila.materia, accion=CambioComentario.CAPTURA,
                                    anterior=anterior, nuevo=texto, usuario=usuario, datos={'asignacion': asignacion.pk})
    return True


def guardar(asignacion, periodo, usuario, capturas):
    """Guarda los comentarios enviados: {id de inscripción: (texto, versión con que se cargó)}. Cada uno se valida y se
    guarda por separado (un error no detiene a los demás). Devuelve (guardados, {id de inscripción: error})."""
    motivo = motivo_de_solo_lectura(asignacion, periodo, usuario)
    if motivo:
        raise ComentarioRechazado(motivo)
    filas = {f.inscripcion.pk: f for f in captura(asignacion, periodo).filas}
    guardados, errores = 0, {}
    for pk, (texto, version) in capturas.items():
        fila = filas.get(pk)
        if fila is None:
            errores[pk] = 'El estudiante no está en la lista de esta materia en el periodo.'
            continue
        texto = limpiar(texto)
        if len(texto) > LIMITE:
            errores[pk] = f'El comentario tiene {len(texto)} caracteres: el máximo es {LIMITE}.'
            continue
        try:
            with transaction.atomic():
                guardados += _guardar_uno(asignacion, periodo, fila, texto, version, usuario)
        except ComentarioRechazado as error:
            errores[pk] = error.mensaje
    return guardados, errores


def asignaciones_del_periodo(asignaciones, periodo):
    """De las materias, las que tienen ese periodo."""
    return [a for a in asignaciones if any(p.pk == periodo.pk for p in reglas.periodos_de(a))]


# ---------------------------------------------------------------------------
# La boleta de comentarios
# ---------------------------------------------------------------------------
@dataclass
class BoletaDeComentarios:
    inscripcion: object
    periodo: object
    materias: list
    registro: object = None          # BoletaComentarios (o None si nunca se ha guardado nada)

    @property
    def alumno(self):
        return self.inscripcion.alumno

    @property
    def pendientes(self):
        return [m for m in self.materias if not m.capturada]

    @property
    def capturadas(self):
        return len(self.materias) - len(self.pendientes)

    @property
    def completa(self):
        return bool(self.materias) and not self.pendientes

    @property
    def publicada(self):
        return self.registro is not None and self.registro.publicada

    @property
    def contenido(self):
        """Lo que muestra la hoja: lo publicado, si ya se publicó; si no, el borrador con los comentarios de hoy."""
        return self.registro.contenido if self.publicada else contenido_de(self)

    @property
    def estado(self):
        if self.publicada:
            return 'publicada'
        return 'lista' if self.completa else 'pendiente'


def boleta_de(inscripcion, periodo, clases=None):
    return BoletaDeComentarios(
        inscripcion=inscripcion, periodo=periodo, materias=materias_del_periodo(inscripcion, periodo, clases),
        registro=BoletaComentarios.objects.filter(inscripcion=inscripcion, periodo=periodo).select_related('publicada_por').first(),
    )


def contenido_de(boleta):
    """Los datos de la hoja (lo que se guarda al publicar): estudiante, escuela y una fila por materia."""
    inscripcion, periodo = boleta.inscripcion, boleta.periodo
    datos = DatosOficialesNivel.objects.filter(nivel=inscripcion.grado.nivel).first()
    alumno = inscripcion.alumno
    return {
        'alumno': ' '.join(p for p in (alumno.nombre, alumno.apellido_paterno, alumno.apellido_materno) if p),
        'matricula': alumno.referencia,
        'nivel': dict(Grado.NIVEL_CHOICES).get(inscripcion.grado.nivel, inscripcion.grado.nivel),
        'grado': f'{inscripcion.grado.numero}.º',
        'grupo': str(inscripcion.grupo),
        'ciclo': str(inscripcion.ciclo),
        'periodo': periodo.nombre,
        'semestre': periodo.semestre.nombre if periodo.semestre_id else '',
        'cct': datos.cct if datos else '',
        'director': datos.director if datos else '',
        'cargo': datos.cargo_o_predeterminado if datos else 'Dirección',
        'materias': [{'materia': m.materia.nombre, 'docente': m.docente, 'comentario': m.comentario.texto if m.capturada else '',
                      'pendiente': not m.capturada} for m in boleta.materias],
    }


def problemas_para_publicar(boleta):
    if boleta.publicada:
        return ['Ya está publicada.']
    if not boleta.materias:
        return [f'No cursa materias en {boleta.periodo.nombre}.']
    if boleta.pendientes:
        return ['Faltan comentarios de ' + ', '.join(m.materia.nombre for m in boleta.pendientes) + '.']
    return []


@transaction.atomic
def publicar(inscripcion, periodo, usuario):
    registro = _boleta_bloqueada(inscripcion, periodo)
    boleta = boleta_de(inscripcion, periodo)
    boleta.registro = registro
    problemas = problemas_para_publicar(boleta)
    if problemas:
        raise ComentarioRechazado(' '.join(problemas))
    registro.contenido = contenido_de(boleta)
    registro.publicada, registro.publicada_por, registro.publicada_en = True, usuario, timezone.now()
    registro.save()
    CambioComentario.objects.create(inscripcion=inscripcion, periodo=periodo, accion=CambioComentario.PUBLICACION, nuevo='Publicada',
                                    usuario=usuario, datos={'materias': len(boleta.materias)})
    registrar(usuario, registro, ACCION_CAMBIO, f'Publicó la boleta de comentarios de {registro.contenido["alumno"]} ({periodo.nombre}, ciclo {periodo.ciclo}).')
    return registro


def bloqueo_de_reapertura(periodo):
    """Por qué no se reabre (su semestre de bachillerato está cerrado) o ''."""
    if semestres.bloqueo_de_periodo(periodo):
        return (f'{periodo.nombre} es del {periodo.semestre.en_frase}, que está cerrado: para corregir un comentario, primero se reabre '
                'el semestre (Ciclos escolares, con motivo).')
    return ''


@transaction.atomic
def reabrir(inscripcion, periodo, motivo, usuario):
    registro = BoletaComentarios.objects.select_for_update().filter(inscripcion=inscripcion, periodo=periodo).first()
    if registro is None or not registro.publicada:
        raise ComentarioRechazado('No está publicada.')
    bloqueo = bloqueo_de_reapertura(periodo)
    if bloqueo:
        raise ComentarioRechazado(bloqueo)
    CambioComentario.objects.create(
        inscripcion=inscripcion, periodo=periodo, accion=CambioComentario.REAPERTURA, anterior='Publicada', nuevo='En captura', motivo=motivo,
        usuario=usuario, datos={'publicada_en': registro.publicada_en.isoformat() if registro.publicada_en else '', 'contenido': registro.contenido},
    )
    alumno = registro.contenido.get('alumno') or str(inscripcion.alumno)
    registro.publicada, registro.publicada_por, registro.publicada_en, registro.contenido = False, None, None, {}
    registro.save()
    registrar(usuario, registro, ACCION_CAMBIO, f'Reabrió la boleta de comentarios de {alumno} ({periodo.nombre}, ciclo {periodo.ciclo}). Motivo: {motivo}')
    return registro


def historial(inscripcion, periodo, limite=100):
    return list(CambioComentario.objects.filter(inscripcion=inscripcion, periodo=periodo).select_related('usuario', 'materia')[:limite])


# ---------------------------------------------------------------------------
# Un grupo y los portales
# ---------------------------------------------------------------------------
def inscripciones_del_grupo(grupo, periodo):
    """Los estudiantes del grupo base en el ciclo del periodo (también los que ya pasaron al semestre siguiente), en el
    orden de la lista."""
    return list(Inscripcion.objects.filter(Q(activa=True) | Q(concluida=True), grupo=grupo, ciclo=periodo.ciclo_id)
                .select_related('alumno', 'ciclo', 'grado', 'grupo__nombre', 'grupo__grado')
                .order_by('alumno__apellido_paterno', 'alumno__apellido_materno', 'alumno__nombre'))


def boletas_del_grupo(grupo, periodo):
    clases = Clases(periodo)
    return [boleta_de(i, periodo, clases) for i in inscripciones_del_grupo(grupo, periodo)]


def publicadas_de(alumno):
    """Sus boletas de comentarios publicadas, de la más reciente."""
    return list(BoletaComentarios.objects.filter(inscripcion__alumno=alumno, publicada=True).select_related('periodo__ciclo')
                .order_by('-periodo__ciclo__fecha_inicio', '-periodo__fecha_inicio', '-pk'))
