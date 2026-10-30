"""Reglas de los bloques simultáneos (pedido del 2026-10-30): armar un bloque y sus opciones, delimitar quién participa,
distribuir a los estudiantes, revisar los conflictos, activar y desactivar. Quién está en qué clase en cada fecha se
consulta en Alumnos/clases.py. Todo se valida aquí, en el servidor, sea cual sea la pantalla.

- Cada opción (`GrupoClase`) es una asignación (`MateriaGrado`) de un grupo técnico: el horario, la asistencia, las actas
  y las bitácoras son los de siempre y no se duplican materias.
- En preparación, la distribución es un borrador: no afecta nada y se puede mover libremente. Al activar (sin
  pendientes ni conflictos) sus clases entran al horario. Después, cada cambio lleva fecha efectiva: se cierra el registro
  anterior y se abre otro, sin tocar lo capturado.
- Un conflicto es real solo si dos obligaciones coinciden de verdad: mismo día, horas traslapadas, fechas de vigencia
  (también el semestre de cada materia) y semanas A/B. Compartir grupos base no es un conflicto.
- Las operaciones masivas son todo o nada: si un estudiante no se puede asignar, no se guarda ninguno.
- La bitácora es la del sistema (`LogEntry`): del bloque y, por cada estudiante, en su expediente.
"""
from dataclasses import dataclass
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from Alumnos import historial
from Alumnos.clases import EN_EFECTO, hay_bloques, tramo_de
from Alumnos.horarios import DIAS_CORTOS, se_empalman
from Alumnos.models import (
    BloqueSimultaneo, EquivalenciaClase, Grupo, GrupoClase, HorarioBloque, HorarioMateria, Inscripcion, IntegranteClase, MateriaGrado,
    ParticipanteBloque, Semestre,
)
from Alumnos.semanas import Calendario, coinciden
from Usuarios.seguridad import ACCION_ALTA, ACCION_BAJA, ACCION_CAMBIO, registrar

VER, CREAR, GESTIONAR = 'Alumnos.view_bloquesimultaneo', 'Alumnos.add_bloquesimultaneo', 'Alumnos.change_bloquesimultaneo'


class BloqueRechazado(Exception):
    """No se pudo hacer lo pedido: `mensaje` para la persona."""

    def __init__(self, mensaje):
        super().__init__(mensaje)
        self.mensaje = mensaje


def _plural(cantidad, singular, plural=None):
    return f'{cantidad} {singular if cantidad == 1 else (plural or singular + "s")}'


def bloqueo(bloque):
    """Por qué no se modifica el bloque ('' si se puede): su ciclo o su semestre ya se cerraron."""
    if bloque.ciclo.estado == 'CERRADO':
        return f'El ciclo {bloque.ciclo} está cerrado: el bloque se conserva tal como quedó.'
    if bloque.semestre_id and bloque.semestre.cerrado:
        return f'El {bloque.semestre.en_frase} está cerrado: el bloque ya no se modifica.'
    return ''


def _exigir_editable(bloque):
    motivo = bloqueo(bloque)
    if motivo:
        raise BloqueRechazado(motivo)


def _bloquear(bloque):
    return BloqueSimultaneo.objects.select_for_update().select_related('ciclo', 'semestre').get(pk=bloque.pk)


def _quien(usuario):
    return (usuario.get_full_name() or usuario.get_username()) if usuario else ''


# ---------------------------------------------------------------------------
# El bloque y sus opciones
# ---------------------------------------------------------------------------
def grados_de(bloque):
    return {grupo.grado_id: grupo.grado for grupo in bloque.grupos_origen.select_related('grado')}


@transaction.atomic
def guardar_horarios(bloque, filas):
    """Deja los días y horarios del bloque: `filas` = [(día, inicio, fin, semana)]. Solo mientras no está activo."""
    if bloque.activo:
        raise BloqueRechazado('Desactiva el bloque para cambiar sus horarios.')
    bloque.horarios.all().delete()
    HorarioBloque.objects.bulk_create([
        HorarioBloque(bloque=bloque, dia_semana=dia, hora_inicio=inicio, hora_fin=fin, semana=semana)
        for dia, inicio, fin, semana in sorted(set(filas))
    ])


def _validar_materia(bloque, materia, equivalencias):
    """La materia debe ser del nivel: de uno de los grados del bloque (o sin grado) y, si la clase mezcla grados, cada
    grado debe tener su materia del plan."""
    grados = grados_de(bloque)
    if not materia.activa:
        raise BloqueRechazado(f'{materia} no está activa en el catálogo.')
    if materia.grado_id and materia.grado_id not in grados:
        raise BloqueRechazado(f'{materia} es de {materia.grado}: no es de los grados de origen del bloque.')
    for grado, materia_del_plan in equivalencias.items():
        if grado.pk not in grados:
            raise BloqueRechazado(f'{grado} no es uno de los grados de origen del bloque.')
        if materia_del_plan.grado_id and materia_del_plan.grado_id != grado.pk:
            raise BloqueRechazado(f'{materia_del_plan} no es del plan de {grado}.')


def _guardar_equivalencias(clase, equivalencias):
    clase.equivalencias.all().delete()
    EquivalenciaClase.objects.bulk_create([EquivalenciaClase(clase=clase, grado=grado, materia=materia) for grado, materia in equivalencias.items()])


def _exigir_profesor_del_nivel(bloque, profesor):
    if profesor is not None and not profesor.niveles.filter(nivel=bloque.nivel).exists():
        raise BloqueRechazado(f'{profesor} no da clases en {bloque.get_nivel_display()}.')


@transaction.atomic
def crear_opcion(bloque, datos, usuario):
    """Una opción nueva: `datos` = {'nombre', 'materia', 'profesor', 'aula', 'equivalencias': {grado: materia}}."""
    bloque = _bloquear(bloque)
    _exigir_editable(bloque)
    if bloque.activo:
        raise BloqueRechazado('Desactiva el bloque para agregar opciones.')
    materia, equivalencias = datos['materia'], datos.get('equivalencias') or {}
    _validar_materia(bloque, materia, equivalencias)
    _exigir_profesor_del_nivel(bloque, datos.get('profesor'))
    if bloque.opciones.filter(nombre__iexact=datos['nombre']).exists():
        raise BloqueRechazado(f'El bloque ya tiene una opción llamada «{datos["nombre"]}».')
    grados = grados_de(bloque)
    grado = grados.get(materia.grado_id) or next(iter(grados.values()), None)
    if grado is None:
        raise BloqueRechazado('Elige primero los grupos de origen del bloque.')
    grupo = Grupo.con_clases.create(grado=grado, nombre=None, nombre_de_clase=datos['nombre'])
    asignacion = MateriaGrado.objects.create(ciclo=bloque.ciclo, grado=grado, grupo=grupo, materia=materia, profesor=datos.get('profesor'))
    clase = GrupoClase.objects.create(bloque=bloque, asignacion=asignacion, nombre=datos['nombre'], aula=datos.get('aula', ''))
    _guardar_equivalencias(clase, equivalencias)
    registrar(usuario, bloque, ACCION_ALTA, f'Agregó la opción {clase.nombre}: {materia}, {datos.get("profesor") or "sin docente"}.')
    return clase


def tiene_registros(clase):
    """Si ya hay asistencia o calificaciones en la clase (entonces su materia ya no cambia)."""
    asignacion = clase.asignacion
    return asignacion.asistencias.exists() or asignacion.actas_calificaciones.exists() or asignacion.bitacoras.exists()


@transaction.atomic
def editar_opcion(clase, datos, usuario):
    bloque = _bloquear(clase.bloque)
    _exigir_editable(bloque)
    asignacion, cambios = clase.asignacion, []
    materia, profesor, equivalencias = datos['materia'], datos.get('profesor'), datos.get('equivalencias') or {}
    if materia.pk != asignacion.materia_id:
        if tiene_registros(clase):
            raise BloqueRechazado(f'{clase.nombre} ya tiene asistencia o calificaciones de {asignacion.materia}: su materia ya no cambia. Crea otra opción.')
        _validar_materia(bloque, materia, equivalencias)
        cambios.append(f'materia: {asignacion.materia} → {materia}')
        asignacion.materia = materia
    if (profesor.pk if profesor else None) != asignacion.profesor_id:
        _exigir_profesor_del_nivel(bloque, profesor)
        cambios.append(f'docente: {asignacion.profesor or "sin docente"} → {profesor or "sin docente"}')
        asignacion.profesor = profesor
    asignacion.save()
    if datos['nombre'] != clase.nombre:
        if bloque.opciones.exclude(pk=clase.pk).filter(nombre__iexact=datos['nombre']).exists():
            raise BloqueRechazado(f'El bloque ya tiene una opción llamada «{datos["nombre"]}».')
        cambios.append(f'nombre: {clase.nombre} → {datos["nombre"]}')
        clase.nombre = datos['nombre']
        Grupo.con_clases.filter(pk=asignacion.grupo_id).update(nombre_de_clase=datos['nombre'])
    if datos.get('aula', '') != clase.aula:
        cambios.append(f'aula: {clase.aula or "sin aula"} → {datos.get("aula") or "sin aula"}')
        clase.aula = datos.get('aula', '')
    clase.save()
    _guardar_equivalencias(clase, equivalencias)
    if bloque.activo:
        problemas = _conflictos_de_docente_y_aula(bloque)
        if problemas:
            raise BloqueRechazado(' '.join(c.texto for c in problemas[:3]))
    if cambios:
        registrar(usuario, bloque, ACCION_CAMBIO, f'{clase.nombre}: {"; ".join(cambios)}.')
    return clase


def _cerrar_horario_de(clase, fecha):
    HorarioMateria.objects.filter(materia_grado=clase.asignacion).update(vigente_hasta=fecha - timedelta(days=1))


@transaction.atomic
def desactivar_opcion(clase, fecha, usuario):
    """La opción deja de impartirse desde esa fecha: sus estudiantes quedan pendientes y lo capturado se conserva."""
    bloque = _bloquear(clase.bloque)
    _exigir_editable(bloque)
    if not clase.activa:
        return clase
    if bloque.activo:
        for integrante in clase.integrantes.filter(_q_desde(fecha)):
            _cerrar(integrante, fecha)
        _cerrar_horario_de(clase, fecha)
    clase.activa = False
    clase.save(update_fields=['activa', 'modificado'])
    registrar(usuario, bloque, ACCION_BAJA, f'Desactivó la opción {clase.nombre} desde el {fecha:%d/%m/%Y}.')
    return clase


@transaction.atomic
def reactivar_opcion(clase, fecha, usuario):
    bloque = _bloquear(clase.bloque)
    _exigir_editable(bloque)
    if clase.activa:
        return clase
    clase.activa = True
    clase.save(update_fields=['activa', 'modificado'])
    if bloque.activo:
        _abrir_horario_de(clase, bloque, fecha)
    registrar(usuario, bloque, ACCION_CAMBIO, f'Reactivó la opción {clase.nombre}.')
    return clase


# ---------------------------------------------------------------------------
# Quién participa y cómo se distribuye
# ---------------------------------------------------------------------------
ORDEN_DE_LISTA = ('alumno__apellido_paterno', 'alumno__apellido_materno', 'alumno__nombre')


def poblacion(bloque):
    """Los estudiantes que deben quedar en una opción: los de los grupos de origen o, si se delimitó, los elegidos."""
    inscripciones = Inscripcion.objects.filter(ciclo=bloque.ciclo, activa=True, alumno__estatus='ACTIVO')
    if bloque.poblacion_delimitada:
        inscripciones = inscripciones.filter(bloques_en_que_participa__bloque=bloque)
    else:
        inscripciones = inscripciones.filter(grupo__in=bloque.grupos_origen.all())
    return inscripciones.select_related('alumno', 'grado', 'grupo__nombre', 'grupo__grado').order_by(*ORDEN_DE_LISTA)


def candidatos(bloque):
    """De quiénes se elige la población delimitada: los estudiantes de los grupos de origen."""
    return (Inscripcion.objects.filter(ciclo=bloque.ciclo, activa=True, alumno__estatus='ACTIVO', grupo__in=bloque.grupos_origen.all())
            .select_related('alumno', 'grado', 'grupo__nombre', 'grupo__grado').order_by(*ORDEN_DE_LISTA))


@transaction.atomic
def delimitar(bloque, inscripciones, participan, usuario):
    """Marca a esos estudiantes como participantes (o los quita, con su lugar en las opciones si es un borrador)."""
    bloque = _bloquear(bloque)
    _exigir_editable(bloque)
    if bloque.activo:
        raise BloqueRechazado('Desactiva el bloque para cambiar a quiénes participan.')
    permitidos = set(candidatos(bloque).values_list('pk', flat=True))
    inscripciones = list(inscripciones)
    ajenos = [i for i in inscripciones if i.pk not in permitidos]
    if ajenos:
        raise BloqueRechazado(f'{ajenos[0].alumno} no es de los grupos de origen del bloque.')
    if participan:
        ParticipanteBloque.objects.bulk_create([ParticipanteBloque(bloque=bloque, inscripcion=i) for i in inscripciones], ignore_conflicts=True)
    else:
        bloque.participantes.filter(inscripcion__in=inscripciones).delete()
        if bloque.en_preparacion:
            IntegranteClase.objects.filter(clase__bloque=bloque, inscripcion__in=inscripciones).delete()
    registrar(usuario, bloque, ACCION_CAMBIO, f'{"Agregó a" if participan else "Quitó de"} la población {_plural(len(inscripciones), "estudiante")}.')


def fecha_de_trabajo(bloque, pedida=None):
    """La fecha con que se consulta o se cambia la distribución: en preparación, el inicio del bloque (es un borrador); si
    no, la pedida o hoy, dentro de la vigencia."""
    if bloque.en_preparacion:
        return bloque.vigente_desde
    fecha = pedida or timezone.localdate()
    return min(max(fecha, bloque.vigente_desde), bloque.vigente_hasta)


def _q_desde(fecha):
    return Q(hasta__isnull=True) | Q(hasta__gte=fecha)


def integrantes_en(bloque, fecha):
    """{id de inscripción: IntegranteClase} de la distribución del bloque en esa fecha."""
    filas = IntegranteClase.objects.filter(clase__bloque=bloque, desde__lte=fecha).filter(_q_desde(fecha)).select_related('clase')
    return {fila.inscripcion_id: fila for fila in filas}


@dataclass
class Distribucion:
    fecha: object
    filas: list            # [{'inscripcion', 'integrante'}] de la población, en orden de lista
    opciones: list         # [{'clase', 'total', 'por_grupo'}]
    pendientes: list       # inscripciones de la población sin opción

    @property
    def total(self):
        return len(self.filas)


def distribucion(bloque, fecha=None):
    fecha = fecha_de_trabajo(bloque, fecha)
    actuales = integrantes_en(bloque, fecha)
    filas = [{'inscripcion': i, 'integrante': actuales.get(i.pk)} for i in poblacion(bloque)]
    opciones = []
    for clase in bloque.opciones.select_related('asignacion__materia', 'asignacion__profesor').order_by('nombre'):
        suyos = [f for f in filas if f['integrante'] is not None and f['integrante'].clase_id == clase.pk]
        por_grupo = {}
        for fila in suyos:
            por_grupo[str(fila['inscripcion'].grupo)] = por_grupo.get(str(fila['inscripcion'].grupo), 0) + 1
        opciones.append({'clase': clase, 'total': len(suyos), 'por_grupo': sorted(por_grupo.items())})
    return Distribucion(fecha, filas, opciones, [f['inscripcion'] for f in filas if f['integrante'] is None])


def materia_del_plan(clase, inscripcion):
    """La materia con que cuenta la clase para ese estudiante, o None si no corresponde a su plan de estudios."""
    materia = clase.asignacion.materia
    equivalencia = clase.equivalencias.filter(grado=inscripcion.grado_id).select_related('materia').first()
    if equivalencia is not None:
        return equivalencia.materia
    return materia if materia.grado_id in (None, inscripcion.grado_id) else None


def _problemas_de_asignar(bloque, clase, inscripcion, participantes):
    """Por qué ese estudiante no puede entrar a la opción (texto) o ''."""
    alumno = inscripcion.alumno
    if inscripcion.grado.nivel != bloque.nivel:
        return f'{alumno} es de {inscripcion.grado.get_nivel_display()}: el bloque es de {bloque.get_nivel_display()}.'
    if inscripcion.ciclo_id != bloque.ciclo_id:
        return f'{alumno} no está inscrito en el ciclo {bloque.ciclo}.'
    if inscripcion.pk not in participantes:
        return f'{alumno} no participa en este bloque.'
    if materia_del_plan(clase, inscripcion) is None:
        return (f'{clase.asignacion.materia} no es del plan de {inscripcion.grado}: indica en la opción qué materia del plan '
                f'cursan ahí los estudiantes de {inscripcion.grado}.')
    return ''


def _cerrar(integrante, fecha):
    """Termina la pertenencia el día anterior a `fecha`. Si nunca llegó a tener efecto, no deja rastro en la lista."""
    if integrante.desde >= fecha:
        integrante.delete()
    else:
        integrante.hasta = fecha - timedelta(days=1)
        integrante.save(update_fields=['hasta', 'modificado'])


@transaction.atomic
def asignar(bloque, clase, inscripciones, fecha, usuario):
    """Pone a esos estudiantes en la opción desde `fecha` (en preparación, desde el inicio del bloque). Quien ya estaba en
    otra opción del bloque cambia a esta: lo anterior se conserva. Si alguno no se puede, no se guarda ninguno."""
    bloque = _bloquear(bloque)
    _exigir_editable(bloque)
    if bloque.estado == BloqueSimultaneo.INACTIVO:
        raise BloqueRechazado('El bloque está inactivo: reactívalo para cambiar la distribución.')
    if clase.bloque_id != bloque.pk:
        raise BloqueRechazado('Esa opción no es de este bloque.')
    if not clase.activa:
        raise BloqueRechazado(f'{clase.nombre} está desactivada.')
    if bloque.activo and fecha is not None and not bloque.vigente_desde <= fecha <= bloque.vigente_hasta:
        raise BloqueRechazado(f'La fecha efectiva debe estar en la vigencia del bloque ({bloque.vigente_desde:%d/%m/%Y} al {bloque.vigente_hasta:%d/%m/%Y}).')
    fecha = fecha_de_trabajo(bloque, fecha)
    inscripciones = list(inscripciones)
    participantes = set(poblacion(bloque).values_list('pk', flat=True))
    problemas = [p for p in (_problemas_de_asignar(bloque, clase, i, participantes) for i in inscripciones) if p]
    problemas += _choques_con_otras_clases(bloque, inscripciones, fecha)
    if problemas:
        extra = f' Y {len(problemas) - 4} más.' if len(problemas) > 4 else ''
        raise BloqueRechazado('No se asignó a nadie. ' + ' '.join(problemas[:4]) + extra)

    actuales = integrantes_en(bloque, fecha)
    movidos, mensajes = 0, {}
    for inscripcion in inscripciones:
        actual = actuales.get(inscripcion.pk)
        if actual is not None and actual.clase_id == clase.pk:
            continue
        if actual is not None:
            _cerrar(actual, fecha)
        # Las pertenencias posteriores a esta fecha (un cambio ya programado) quedan reemplazadas por esta
        for posterior in IntegranteClase.objects.filter(clase__bloque=bloque, inscripcion=inscripcion, desde__gt=fecha):
            posterior.delete()
        IntegranteClase.objects.create(clase=clase, inscripcion=inscripcion, desde=fecha, asignado_por=usuario)
        movidos += 1
        origen = f'de {actual.clase.nombre} a' if actual is not None else 'a'
        mensajes[inscripcion.alumno_id] = f'Lo cambió {origen} {clase.nombre} ({bloque.nombre}) desde el {fecha:%d/%m/%Y}.' if actual else (
            f'Lo asignó a {clase.nombre} ({bloque.nombre}) desde el {fecha:%d/%m/%Y}.')
    if movidos:
        if not bloque.en_preparacion:
            historial.anotar_varios(usuario, mensajes)
        registrar(usuario, bloque, ACCION_CAMBIO, f'Asignó {_plural(movidos, "estudiante")} a {clase.nombre} desde el {fecha:%d/%m/%Y}.')
    return movidos


@transaction.atomic
def quitar(bloque, inscripciones, fecha, usuario):
    """Saca a esos estudiantes de su opción desde `fecha`: quedan pendientes de asignación."""
    bloque = _bloquear(bloque)
    _exigir_editable(bloque)
    fecha = fecha_de_trabajo(bloque, fecha)
    actuales = integrantes_en(bloque, fecha)
    quitados = 0
    for inscripcion in inscripciones:
        actual = actuales.get(inscripcion.pk)
        if actual is not None:
            _cerrar(actual, fecha)
            quitados += 1
    if quitados:
        registrar(usuario, bloque, ACCION_CAMBIO, f'Quitó a {_plural(quitados, "estudiante")} de su opción desde el {fecha:%d/%m/%Y}.')
    return quitados


# ---------------------------------------------------------------------------
# Conflictos
# ---------------------------------------------------------------------------
ESTUDIANTE, DOCENTE, AULA = 'ESTUDIANTE', 'DOCENTE', 'AULA'


@dataclass(frozen=True)
class Conflicto:
    tipo: str
    texto: str


def _texto_de_hora(horario):
    semana = f' sem. {horario.semana}' if horario.semana else ''
    return f'{DIAS_CORTOS[horario.dia_semana]} {horario.hora_inicio:%H:%M}–{horario.hora_fin:%H:%M}{semana}'


def _clave(horario):
    return (horario.dia_semana, horario.hora_inicio, horario.hora_fin)


def _traslapan(a, b):
    return a[0] <= b[1] and b[0] <= a[1]


class _Fechas:
    """Las fechas reales de un bloque de horario: su vigencia y, en preparatoria, el semestre de su materia."""

    def __init__(self, ciclo):
        self.ciclo = ciclo
        self.calendario = Calendario(ciclo)
        self.semestres = {s.clave: s for s in Semestre.objects.filter(ciclo=ciclo)}

    def de(self, horario):
        asignacion = horario.materia_grado
        inicio, fin = horario.vigente_desde or self.ciclo.fecha_inicio, self.ciclo.fecha_fin
        for limite in (horario.vigente_hasta, horario.fin_programado):
            if limite is not None:
                fin = min(fin, limite)
        semestre = self.semestres.get(asignacion.grado.semestre)
        if semestre is not None:
            inicio, fin = max(inicio, semestre.fecha_inicio), min(fin, semestre.fecha_fin)
        return inicio, fin

    def coinciden(self, nivel_a, horario_a, rango_a, nivel_b, horario_b, rango_b):
        """Si dos bloques de horario caen de verdad en una misma fecha."""
        if not se_empalman(_clave(horario_a), _clave(horario_b)) or not _traslapan(rango_a, rango_b):
            return False
        return coinciden(nivel_a, horario_a.semana, nivel_b, horario_b.semana, self.ciclo, desde=max(rango_a[0], rango_b[0]), calendario=self.calendario)


def _rango(bloque):
    return bloque.vigente_desde, bloque.vigente_hasta


def _normal(aula):
    return ' '.join((aula or '').split()).casefold()


def _conflictos_de_docente_y_aula(bloque):
    fechas, conflictos = _Fechas(bloque.ciclo), []
    horarios = list(bloque.horarios.all())
    opciones = list(bloque.opciones.filter(activa=True).select_related('asignacion__profesor', 'asignacion__materia'))
    rango = _rango(bloque)

    # Dentro del bloque las opciones son simultáneas: no pueden compartir docente ni aula
    for indice, opcion in enumerate(opciones):
        for otra in opciones[indice + 1:]:
            if opcion.asignacion.profesor_id and opcion.asignacion.profesor_id == otra.asignacion.profesor_id:
                conflictos.append(Conflicto(DOCENTE, f'{opcion.asignacion.profesor} está en {opcion.nombre} y en {otra.nombre}, que son a la misma hora.'))
            if _normal(opcion.aula) and _normal(opcion.aula) == _normal(otra.aula):
                conflictos.append(Conflicto(AULA, f'{opcion.nombre} y {otra.nombre} usan el aula {opcion.aula} a la misma hora.'))

    profesores = {o.asignacion.profesor_id: o for o in opciones if o.asignacion.profesor_id}
    propias = [o.asignacion_id for o in opciones]
    externos = (HorarioMateria.historial.filter(materia_grado__profesor__in=list(profesores), materia_grado__ciclo=bloque.ciclo, materia_grado__activa=True)
                .exclude(materia_grado__in=propias).select_related('materia_grado__materia', 'materia_grado__grado', 'materia_grado__grupo__grado', 'materia_grado__grupo__nombre', 'materia_grado__profesor'))
    vistos = set()
    for externo in externos:
        rango_externo = fechas.de(externo)
        for horario in horarios:
            if fechas.coinciden(bloque.nivel, horario, rango, externo.materia_grado.grado.nivel, externo, rango_externo):
                asignacion = externo.materia_grado
                clave = (asignacion.pk, _clave(horario))
                if clave not in vistos:
                    vistos.add(clave)
                    conflictos.append(Conflicto(DOCENTE, f'{asignacion.profesor} ya da {asignacion.materia} con {asignacion.grupo} ({_texto_de_hora(externo)}).'))

    con_aula = {_normal(o.aula): o for o in opciones if _normal(o.aula)}
    if con_aula:
        otras = (GrupoClase.objects.filter(bloque__ciclo=bloque.ciclo, bloque__estado=BloqueSimultaneo.ACTIVO, activa=True).exclude(bloque=bloque)
                 .select_related('bloque').prefetch_related('bloque__horarios'))
        for otra in otras:
            propia = con_aula.get(_normal(otra.aula))
            if propia is None:
                continue
            for suyo in otra.bloque.horarios.all():
                if any(fechas.coinciden(bloque.nivel, h, rango, otra.bloque.nivel, suyo, _rango(otra.bloque)) for h in horarios):
                    conflictos.append(Conflicto(AULA, f'El aula {propia.aula} ya la usa {otra.nombre} de {otra.bloque.nombre} ({_texto_de_hora(suyo)}).'))
                    break
    return conflictos


def _otros_pasos(bloque, inscripciones):
    """Las pertenencias de esos estudiantes a clases de otros bloques en efecto."""
    return (IntegranteClase.objects.filter(inscripcion__in=inscripciones, clase__bloque__estado__in=EN_EFECTO, clase__bloque__ciclo=bloque.ciclo)
            .exclude(clase__bloque=bloque).select_related('clase__bloque', 'inscripcion__alumno').prefetch_related('clase__bloque__horarios'))


def _choques_con_otras_clases(bloque, inscripciones, desde=None):
    """Textos de los estudiantes que ya tienen otra clase a esa hora, en otro bloque, en las fechas que coinciden."""
    if not hay_bloques(bloque.ciclo):
        return []
    fechas, horarios, textos = _Fechas(bloque.ciclo), list(bloque.horarios.all()), []
    rango = (desde or bloque.vigente_desde, bloque.vigente_hasta)
    for paso in _otros_pasos(bloque, inscripciones):
        otro = paso.clase.bloque
        tramo = tramo_de(paso)
        for suyo in otro.horarios.all():
            if any(fechas.coinciden(bloque.nivel, h, rango, otro.nivel, suyo, tramo) for h in horarios):
                textos.append(f'{paso.inscripcion.alumno} ya tiene {paso.clase.nombre} de {otro.nombre} a esa hora ({_texto_de_hora(suyo)}).')
                break
    return textos


def conflictos(bloque):
    """Los conflictos reales del bloque con lo que ya hay en el horario, sobre sus estudiantes, docentes y aulas."""
    fechas, resultado = _Fechas(bloque.ciclo), _conflictos_de_docente_y_aula(bloque)
    horarios, rango = list(bloque.horarios.all()), _rango(bloque)
    participantes = list(poblacion(bloque))

    # El horario de sus grupos base, salvo lo que el bloque sustituye
    sustituidas = set(bloque.sustituye.values_list('pk', flat=True))
    por_grupo = {}
    for inscripcion in participantes:
        por_grupo.setdefault(inscripcion.grupo_id, []).append(inscripcion)
    base = (HorarioMateria.historial.filter(materia_grado__grupo__in=list(por_grupo), materia_grado__ciclo=bloque.ciclo, materia_grado__activa=True)
            .exclude(materia_grado__in=sustituidas).select_related('materia_grado__materia', 'materia_grado__grado', 'materia_grado__grupo__grado', 'materia_grado__grupo__nombre'))
    vistos = set()
    for horario_base in base:
        asignacion = horario_base.materia_grado
        rango_base = fechas.de(horario_base)
        if asignacion.pk in vistos:
            continue
        if any(fechas.coinciden(bloque.nivel, h, rango, asignacion.grado.nivel, horario_base, rango_base) for h in horarios):
            vistos.add(asignacion.pk)
            cuantos = len(por_grupo[asignacion.grupo_id])
            resultado.append(Conflicto(ESTUDIANTE, f'{_plural(cuantos, "estudiante")} de {asignacion.grupo} tiene{"n" if cuantos != 1 else ""} {asignacion.materia} '
                                                   f'a esa hora ({_texto_de_hora(horario_base)}): agrégala a las clases que el bloque sustituye o cambia el horario.'))

    # Otros bloques en efecto
    resultado += [Conflicto(ESTUDIANTE, texto) for texto in _choques_con_otras_clases(bloque, participantes)[:20]]
    return resultado


# ---------------------------------------------------------------------------
# Activar y desactivar
# ---------------------------------------------------------------------------
def problemas_para_activar(bloque):
    """Lo que impide activar el bloque (textos; vacío si se puede)."""
    motivo = bloqueo(bloque)
    if motivo:
        return [motivo]
    problemas = []
    opciones = list(bloque.opciones.filter(activa=True).select_related('asignacion__profesor'))
    if not bloque.horarios.exists():
        problemas.append('Faltan los días y horarios del bloque.')
    if not opciones:
        problemas.append('El bloque no tiene opciones activas.')
    sin_docente = [o.nombre for o in opciones if o.asignacion.profesor_id is None]
    if sin_docente:
        problemas.append(f'Sin docente: {", ".join(sin_docente)}.')
    if bloque.vigente_hasta < timezone.localdate():
        problemas.append('Su vigencia ya terminó.')
    datos = distribucion(bloque, bloque.vigente_desde if bloque.en_preparacion else None)
    if not datos.filas:
        problemas.append('No tiene estudiantes participantes.')
    if datos.pendientes:
        problemas.append(f'{_plural(len(datos.pendientes), "estudiante")} sin opción asignada. Si solo participa una parte de los grupos, delimita la población.')
    problemas += [c.texto for c in conflictos(bloque)]
    return problemas


def _abrir_horario_de(clase, bloque, desde):
    existentes = set(HorarioMateria.objects.filter(materia_grado=clase.asignacion).values_list('semana', 'dia_semana', 'hora_inicio', 'hora_fin'))
    HorarioMateria.objects.bulk_create([
        HorarioMateria(materia_grado=clase.asignacion, dia_semana=h.dia_semana, hora_inicio=h.hora_inicio, hora_fin=h.hora_fin, semana=h.semana,
                       vigente_desde=desde, fin_programado=bloque.vigente_hasta)
        for h in bloque.horarios.all() if (h.semana, h.dia_semana, h.hora_inicio, h.hora_fin) not in existentes
    ])


@transaction.atomic
def activar(bloque, usuario):
    """Pone el bloque en efecto: sus clases entran al horario. Al reactivar uno desactivado, sus estudiantes siguen en la
    opción que tenían, desde hoy: los días que estuvo inactivo no cuentan."""
    bloque = _bloquear(bloque)
    if bloque.activo:
        return bloque
    problemas = problemas_para_activar(bloque)
    if problemas:
        raise BloqueRechazado(' '.join(problemas[:6]))
    hoy = timezone.localdate()
    reactivado = bloque.estado == BloqueSimultaneo.INACTIVO
    desde = max(hoy, bloque.vigente_desde) if reactivado else bloque.vigente_desde
    if reactivado and bloque.desactivado_en is not None and desde > bloque.desactivado_en:
        for integrante in IntegranteClase.objects.filter(clase__bloque=bloque, clase__activa=True).filter(_q_desde(bloque.desactivado_en)):
            original_hasta = integrante.hasta
            _cerrar(integrante, bloque.desactivado_en)
            if original_hasta is None or original_hasta >= desde:
                try:
                    with transaction.atomic():
                        IntegranteClase.objects.create(clase=integrante.clase, inscripcion=integrante.inscripcion, desde=desde, hasta=original_hasta,
                                                       asignado_por=usuario)
                except IntegrityError:   # ya estaba desde esa fecha
                    pass
    bloque.estado, bloque.activado_en, bloque.activado_por = BloqueSimultaneo.ACTIVO, timezone.now(), usuario
    bloque.desactivado_en, bloque.desactivado_por = None, None
    bloque.save()
    for clase in bloque.opciones.filter(activa=True).select_related('asignacion'):
        _abrir_horario_de(clase, bloque, desde)
    registrar(usuario, bloque, ACCION_CAMBIO, f'{"Reactivó" if reactivado else "Activó"} el bloque desde el {desde:%d/%m/%Y}.')
    return bloque


@transaction.atomic
def desactivar(bloque, fecha, usuario):
    """El bloque deja de impartirse desde esa fecha: no hay operaciones nuevas y lo registrado se sigue consultando."""
    bloque = _bloquear(bloque)
    _exigir_editable(bloque)
    if not bloque.activo:
        raise BloqueRechazado('El bloque no está activo.')
    bloque.estado, bloque.desactivado_en, bloque.desactivado_por = BloqueSimultaneo.INACTIVO, fecha, usuario
    bloque.save()
    HorarioMateria.objects.filter(materia_grado__clase__bloque=bloque).update(vigente_hasta=fecha - timedelta(days=1))
    registrar(usuario, bloque, ACCION_BAJA, f'Desactivó el bloque desde el {fecha:%d/%m/%Y}.')
    return bloque


def actualizar_fin(bloque):
    """Tras cambiar la vigencia de un bloque activo: sus clases terminan con la fecha nueva."""
    HorarioMateria.objects.filter(materia_grado__clase__bloque=bloque).update(fin_programado=bloque.vigente_hasta)


def historial_del_bloque(bloque, limite=60):
    from Usuarios.seguridad import historial as bitacora
    return bitacora(bloque, limite)
