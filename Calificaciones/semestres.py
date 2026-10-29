"""Reglas del bachillerato por semestres (pedido del 2026-10-28). Los números los calcula
Calificaciones/calculo_semestral.py; aquí se juntan los datos, se decide quién captura qué y cuándo, y se cierra.

- Cada ciclo puede tener un semestre A y uno B (`Alumnos.Semestre`), con sus fechas, sus periodos y su estado. En
  preparatoria cada grado es un semestre (1.º, 3.º y 5.º en el A; 2.º, 4.º y 6.º en el B: `Alumnos.models.semestre_de_grado`).
- Las calificaciones de periodo que cuentan son las de las actas cerradas (las mismas que ven el portal y la Vista
  360): mientras un acta está en captura, ese periodo está pendiente.
- Semestre pendiente: no se captura nada de él. Abierto: se capturan sus periodos (cuando el periodo lo permite) y sus
  exámenes finales, extraordinarios y regularizaciones. Cerrado: la evaluación ordinaria queda bloqueada (periodos,
  rubros, porcentajes, actas y exámenes finales); solo se capturan los extraordinarios y las regularizaciones que
  sigan pendientes, aunque el semestre B ya esté abierto o el ciclo se haya cerrado.
- Para cerrarlo, todas sus materias deben tener la evaluación ordinaria completa (actas cerradas y exámenes finales
  capturados). Cerrar guarda los resultados en la bitácora; reabrir pide motivo y guarda lo que estaba cerrado. Al
  volver a cerrarlo se registran las calificaciones definitivas que cambiaron.
- De cada examen solo se corrige el último que se capturó (el final mientras no haya extraordinario, etc.): los
  anteriores quedan como historia.
- Abrir, cerrar y configurar un semestre: quien edita los ciclos escolares (Alumnos.change_cicloescolar). Reabrirlo,
  además, necesita el permiso de reabrir calificaciones (Calificaciones.reabrir). Los exámenes los captura quien captura
  las calificaciones de la materia (su docente o quien gestiona todas).
"""
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from Alumnos.models import NIVEL_POR_SEMESTRES, Inscripcion, MateriaGrado, Periodo, Semestre

from . import calculo_semestral as cs
from .models import ActaCalificaciones, CambioSemestre, ExamenSemestral

GESTIONAR = 'Alumnos.change_cicloescolar'
REABRIR = 'Calificaciones.reabrir'
TIPOS = dict(ExamenSemestral.TIPOS)
NOMBRES_DE_EXAMEN = {ExamenSemestral.FINAL: 'Examen final', ExamenSemestral.EXTRAORDINARIO: 'Extraordinario',
                     ExamenSemestral.REGULARIZACION: 'Regularización'}


def puede_gestionar(usuario):
    return usuario.has_perm(GESTIONAR)


def puede_reabrir(usuario):
    return usuario.has_perm(GESTIONAR) and usuario.has_perm(REABRIR)


# ---------------------------------------------------------------------------
# Qué semestre
# ---------------------------------------------------------------------------
def semestres_del_ciclo(ciclo):
    """{'A': Semestre, 'B': Semestre} (los que existan)."""
    return {s.clave: s for s in Semestre.objects.filter(ciclo=ciclo)} if ciclo is not None else {}


def semestre_de_grado_en(grado, ciclo):
    """El semestre del ciclo en que se cursa el grado (None si no es de preparatoria o el ciclo no tiene semestres)."""
    clave = grado.semestre if grado is not None else None
    if not clave or ciclo is None:
        return None
    return Semestre.objects.filter(ciclo=ciclo, clave=clave).first()


def semestre_de_asignacion(asignacion):
    return semestre_de_grado_en(asignacion.grado, asignacion.ciclo)


def semestre_de_materia(materia, ciclo):
    """El de la materia en el ciclo: por su grado o, si no lo tiene registrado, por el de los grupos que la llevan."""
    grado = materia.grado if materia.grado_id else None
    if grado is None:
        asignacion = MateriaGrado.objects.filter(materia=materia, ciclo=ciclo).select_related('grado').first()
        grado = asignacion.grado if asignacion else None
    return semestre_de_grado_en(grado, ciclo)


def periodos_del_semestre(semestre):
    return list(semestre.periodos.order_by('fecha_inicio', 'nombre')) if semestre else []


def asignaciones_del_semestre(semestre):
    """Las materias (una por grupo) que se cursan en el semestre: las de los grados de preparatoria de ese semestre."""
    asignaciones = (MateriaGrado.objects.filter(ciclo=semestre.ciclo, activa=True, grado__nivel=NIVEL_POR_SEMESTRES)
                    .select_related('materia', 'grado', 'grupo__nombre', 'grupo__grado', 'profesor')
                    .order_by('grado__numero', 'grupo__nombre__orden', 'grupo__nombre__nombre', 'materia__nombre'))
    return [a for a in asignaciones if a.grado.semestre == semestre.clave]


def grados_de_semestres_cerrados(ciclo):
    """Los grados de preparatoria cuyo semestre ya se cerró en el ciclo: aunque se oculten, Calificaciones los sigue
    mostrando (sus actas son registros y sus extraordinarios se siguen capturando)."""
    cerrados = {s.clave for s in Semestre.objects.filter(ciclo=ciclo, estado=Semestre.CERRADO)} if ciclo else set()
    if not cerrados:
        return []
    from Alumnos.models import Grado
    return [g.pk for g in Grado.objects.filter(nivel=NIVEL_POR_SEMESTRES) if g.semestre in cerrados]


# ---------------------------------------------------------------------------
# Bloqueos de la evaluación ordinaria
# ---------------------------------------------------------------------------
def bloqueo_de_captura(periodo):
    """Por qué no se capturan calificaciones del periodo por su semestre ('' si el semestre no lo impide)."""
    semestre = periodo.semestre if periodo.semestre_id else None
    if semestre is None:
        return ''
    if semestre.cerrado:
        return f'El {semestre.en_frase} está cerrado: sus calificaciones de periodo ya no se editan.'
    if semestre.estado == Semestre.PENDIENTE:
        return f'El {semestre.en_frase} todavía no se abre: se abre desde Ciclos escolares.'
    return ''


def bloqueo_de_periodo(periodo):
    """Por qué no se edita el periodo (fechas, apertura, borrarlo): su semestre está cerrado. '' si se puede."""
    semestre = periodo.semestre if periodo.semestre_id else None
    if semestre is not None and semestre.cerrado:
        return f'{periodo.nombre} es del {semestre.en_frase}, que está cerrado: reábrelo para cambiar el periodo.'
    return ''


def bloqueo_de_configuracion(materia, ciclo):
    """Por qué no se cambian los rubros, porcentajes o reglas de la materia: su semestre está cerrado. '' si se puede."""
    semestre = semestre_de_materia(materia, ciclo)
    if semestre is not None and semestre.cerrado:
        return f'{materia} es del {semestre.en_frase} del ciclo {ciclo}, que está cerrado: su configuración ya no se cambia.'
    return ''


def ventana(semestre):
    """Los exámenes que el estado del semestre permite capturar."""
    if semestre is None:
        return set()
    if semestre.abierto:
        return {cs.FINAL, cs.EXTRAORDINARIO, cs.REGULARIZACION}
    if semestre.cerrado:
        return {cs.EXTRAORDINARIO, cs.REGULARIZACION}
    return set()


# ---------------------------------------------------------------------------
# La hoja del semestre: periodos, exámenes y resultado de cada estudiante
# ---------------------------------------------------------------------------
@dataclass
class FilaSemestral:
    inscripcion: object
    numero: int
    nombre: str
    resultado: object                                  # calculo_semestral.ResultadoSemestral
    examenes: dict = field(default_factory=dict)       # tipo -> ExamenSemestral


@dataclass
class HojaSemestral:
    asignacion: object
    semestre: object
    periodos: list
    filas: list
    actas: dict                                        # id de periodo -> ActaCalificaciones (las que existen)

    @property
    def periodos_sin_cerrar(self):
        return [p for p in self.periodos if not (self.actas.get(p.pk) and self.actas[p.pk].cerrada)]

    def contar(self, condicion):
        return sum(1 for f in self.filas if condicion(f.resultado))


def estudiantes_de(asignacion):
    """Los estudiantes de la materia, también los que ya pasaron al semestre siguiente (inscripción concluida)."""
    from Alumnos.asistencia_docente import inscripciones_de
    return list(inscripciones_de(asignacion, con_concluidas=True))


def hojas(asignaciones, semestre):
    """{id de asignación: HojaSemestral} de varias materias del mismo semestre, con pocas consultas."""
    asignaciones = list(asignaciones)
    periodos = periodos_del_semestre(semestre)
    if not asignaciones:
        return {}
    ids = [a.pk for a in asignaciones]
    por_grupo = {}
    for inscripcion in (Inscripcion.objects.filter(grupo__in={a.grupo_id for a in asignaciones}, ciclo=semestre.ciclo, alumno__estatus='ACTIVO')
                        .filter(Q(activa=True) | Q(concluida=True)).select_related('alumno')
                        .order_by('alumno__apellido_paterno', 'alumno__apellido_materno', 'alumno__nombre')):
        por_grupo.setdefault(inscripcion.grupo_id, []).append(inscripcion)
    actas, finales = {}, {}
    for acta in ActaCalificaciones.objects.filter(asignacion__in=ids, periodo__in=periodos):
        actas.setdefault(acta.asignacion_id, {})[acta.periodo_id] = acta
        if acta.cerrada:
            for r in acta.resultados_cerrados or []:
                if r.get('final') not in (None, ''):
                    finales[(acta.asignacion_id, acta.periodo_id, r.get('inscripcion'))] = Decimal(r['final'])
    examenes = {}
    for examen in ExamenSemestral.objects.filter(asignacion__in=ids):
        examenes.setdefault((examen.asignacion_id, examen.inscripcion_id), {})[examen.tipo] = examen

    resultado = {}
    for asignacion in asignaciones:
        filas = []
        for numero, inscripcion in enumerate(por_grupo.get(asignacion.grupo_id, []), start=1):
            suyos = examenes.get((asignacion.pk, inscripcion.pk), {})
            valor = lambda tipo: suyos[tipo].valor if tipo in suyos else None   # noqa: E731
            calculado = cs.calcular([finales.get((asignacion.pk, p.pk, inscripcion.pk)) for p in periodos],
                                    final=valor(cs.FINAL), extraordinario=valor(cs.EXTRAORDINARIO), regularizacion=valor(cs.REGULARIZACION))
            filas.append(FilaSemestral(inscripcion=inscripcion, numero=numero, nombre=str(inscripcion.alumno), resultado=calculado, examenes=suyos))
        resultado[asignacion.pk] = HojaSemestral(asignacion=asignacion, semestre=semestre, periodos=periodos, filas=filas,
                                                 actas=actas.get(asignacion.pk, {}))
    return resultado


def hoja(asignacion, semestre=None):
    semestre = semestre or semestre_de_asignacion(asignacion)
    return hojas([asignacion], semestre)[asignacion.pk]


def resultado_de(inscripcion, asignacion, semestre=None):
    """El resultado semestral de un estudiante en una materia (None si la materia no es de un semestre)."""
    semestre = semestre or semestre_de_asignacion(asignacion)
    if semestre is None:
        return None
    fila = next((f for f in hoja(asignacion, semestre).filas if f.inscripcion.pk == inscripcion.pk), None)
    return fila.resultado if fila else None


def foto(fila, asignacion):
    """Un resultado como datos (para la bitácora del cierre y la comparación al volver a cerrar)."""
    r = fila.resultado
    return {
        'asignacion': asignacion.pk, 'materia': str(asignacion.materia), 'grupo': str(asignacion.grupo),
        'inscripcion': fila.inscripcion.pk, 'nombre': fila.nombre,
        'periodos': [cs.texto(p) for p in r.periodos], 'promedio': cs.texto(r.promedio), 'situacion': r.situacion,
        'examen_final': cs.texto(r.examen_final), 'por_exencion': r.final_por_exencion, 'ordinaria': cs.texto(r.ordinaria),
        'extraordinario': cs.texto(r.extraordinario), 'regularizacion': cs.texto(r.regularizacion),
        'definitiva': cs.texto(r.definitiva), 'estado': r.estado,
    }


# ---------------------------------------------------------------------------
# Resumen del semestre (antes de cerrarlo y en su página)
# ---------------------------------------------------------------------------
@dataclass
class MateriaDelResumen:
    asignacion: object
    estudiantes: int
    completas: int          # con calificación definitiva (aprobada o reprobada)
    pendientes: int         # sin resultado ordinario (periodos o examen final)
    procesos: int           # extraordinario o regularización abiertos
    aprobadas: int
    reprobadas: int
    actas_sin_cerrar: list  # periodos cuyo acta sigue en captura (o sin abrir)
    examenes_finales: int   # exámenes finales por capturar


@dataclass
class Resumen:
    semestre: object
    periodos: list
    materias: list
    hojas: dict
    estudiantes_pendientes: list = field(default_factory=list)   # (materia, fila) de lo ordinario pendiente
    estudiantes_en_proceso: list = field(default_factory=list)   # (materia, fila) con extraordinario o regularización abiertos

    def total(self, campo):
        return sum(getattr(m, campo) for m in self.materias)

    @property
    def procesos_abiertos(self):
        return self.total('procesos')

    @property
    def pendientes(self):
        return self.total('pendientes')

    @property
    def total_completas(self):
        return self.total('completas')


def resumen(semestre):
    periodos = periodos_del_semestre(semestre)
    asignaciones = asignaciones_del_semestre(semestre)
    calculadas = hojas(asignaciones, semestre)
    datos = Resumen(semestre=semestre, periodos=periodos, materias=[], hojas=calculadas)
    for asignacion in asignaciones:
        h = calculadas[asignacion.pk]
        datos.materias.append(MateriaDelResumen(
            asignacion=asignacion, estudiantes=len(h.filas),
            completas=h.contar(lambda r: r.concluida), pendientes=h.contar(lambda r: r.pendiente_ordinario),
            procesos=h.contar(lambda r: r.proceso_abierto), aprobadas=h.contar(lambda r: r.aprobada),
            reprobadas=h.contar(lambda r: r.reprobada), actas_sin_cerrar=h.periodos_sin_cerrar if h.filas else [],
            examenes_finales=h.contar(lambda r: r.estado == cs.PENDIENTE_FINAL),
        ))
        for fila in h.filas:
            if fila.resultado.pendiente_ordinario:
                datos.estudiantes_pendientes.append((asignacion, fila))
            elif fila.resultado.proceso_abierto:
                datos.estudiantes_en_proceso.append((asignacion, fila))
    return datos


def problemas_para_cerrar(semestre, datos=None):
    """Lo que impide cerrar la evaluación ordinaria del semestre (lista vacía si se puede)."""
    if not semestre.abierto:
        return [f'El {semestre.en_frase} no está abierto.']
    datos = datos or resumen(semestre)
    problemas = []
    if not datos.periodos:
        problemas.append(f'El {semestre.en_frase} no tiene periodos de evaluación (asígnalos en Periodos de evaluación).')
    if not datos.materias:
        problemas.append(f'No hay materias de grados del {semestre.en_frase} en el ciclo.')
    actas = sum(len(m.actas_sin_cerrar) for m in datos.materias)
    if actas:
        problemas.append(f'{actas} acta{"s" if actas != 1 else ""} de periodo sin cerrar.')
    sin_periodos = sum(1 for _, f in datos.estudiantes_pendientes if f.resultado.estado == cs.PENDIENTE_PERIODOS)
    if sin_periodos and not actas:
        problemas.append(f'{sin_periodos} estudiante{"s" if sin_periodos != 1 else ""} sin calificación en algún periodo '
                         '(no estaba en la lista cuando se cerró el acta: reábrela para calificarlo).')
    finales = datos.total('examenes_finales')
    if finales:
        problemas.append(f'{finales} examen{"es" if finales != 1 else ""} final{"es" if finales != 1 else ""} por capturar.')
    return problemas


# ---------------------------------------------------------------------------
# Abrir, cerrar y reabrir
# ---------------------------------------------------------------------------
class SemestreRechazado(Exception):
    def __init__(self, mensaje):
        super().__init__(mensaje)
        self.mensaje = mensaje


def _bloquear(semestre):
    return Semestre.objects.select_for_update().select_related('ciclo').get(pk=semestre.pk)


@transaction.atomic
def abrir(semestre, usuario):
    semestre = _bloquear(semestre)
    if semestre.estado != Semestre.PENDIENTE:
        raise SemestreRechazado(f'El {semestre.en_frase} ya {"está abierto" if semestre.abierto else "se abrió y se cerró: usa «Reabrir»"}.')
    if semestre.ciclo.estado == 'CERRADO':
        raise SemestreRechazado(f'El ciclo {semestre.ciclo} está cerrado.')
    semestre.estado, semestre.abierto_en, semestre.abierto_por = Semestre.ABIERTO, timezone.now(), usuario
    semestre.save()
    CambioSemestre.objects.create(semestre=semestre, accion=CambioSemestre.APERTURA, que=f'Apertura del {semestre.en_frase}',
                                  anterior='Pendiente', nuevo='Abierto', usuario=usuario)
    return semestre


def _ultimo_cierre(semestre):
    return semestre.cambios.filter(accion=CambioSemestre.CIERRE).order_by('-fecha', '-pk').first()


@transaction.atomic
def cerrar(semestre, usuario):
    """Cierra la evaluación ordinaria: guarda los resultados en la bitácora y, si ya se había cerrado antes, qué
    calificaciones definitivas cambiaron desde entonces."""
    semestre = _bloquear(semestre)
    datos = resumen(semestre)
    problemas = problemas_para_cerrar(semestre, datos)
    if problemas:
        raise SemestreRechazado(' '.join(problemas))
    resultados = [foto(f, h.asignacion) for h in datos.hojas.values() for f in h.filas]
    cambios = []
    anterior = _ultimo_cierre(semestre)
    if anterior is not None:
        antes = {(r['asignacion'], r['inscripcion']): r for r in anterior.datos.get('resultados', [])}
        for r in resultados:
            previo = antes.get((r['asignacion'], r['inscripcion']))
            if previo is None or (previo['definitiva'], previo['estado']) != (r['definitiva'], r['estado']):
                cambios.append({'materia': r['materia'], 'grupo': r['grupo'], 'nombre': r['nombre'],
                                'antes': previo['definitiva'] if previo else '', 'despues': r['definitiva'],
                                'estado_antes': cs.ESTADOS.get(previo['estado'], '') if previo else '', 'estado': cs.ESTADOS[r['estado']]})
    semestre.estado, semestre.cerrado_en, semestre.cerrado_por = Semestre.CERRADO, timezone.now(), usuario
    semestre.save()
    CambioSemestre.objects.create(
        semestre=semestre, accion=CambioSemestre.CIERRE, que=f'Cierre del {semestre.en_frase}', anterior='Abierto', nuevo='Cerrado',
        usuario=usuario, datos={'resultados': resultados, 'cambios': cambios, 'recierre': anterior is not None,
                                'procesos_abiertos': datos.procesos_abiertos},
    )
    return semestre


@transaction.atomic
def reabrir(semestre, motivo, usuario):
    semestre = _bloquear(semestre)
    if not semestre.cerrado:
        raise SemestreRechazado(f'El {semestre.en_frase} no está cerrado.')
    if semestre.ciclo.estado == 'CERRADO':
        raise SemestreRechazado(f'El ciclo {semestre.ciclo} está cerrado: márcalo como actual antes de reabrir uno de sus semestres.')
    CambioSemestre.objects.create(
        semestre=semestre, accion=CambioSemestre.REAPERTURA, que=f'Reapertura del {semestre.en_frase}', anterior='Cerrado',
        nuevo='Abierto', motivo=motivo, usuario=usuario,
        datos={'cerrado_en': semestre.cerrado_en.isoformat() if semestre.cerrado_en else '',
               'cerrado_por': (semestre.cerrado_por.get_full_name() or semestre.cerrado_por.get_username()) if semestre.cerrado_por else ''},
    )
    semestre.estado, semestre.cerrado_en, semestre.cerrado_por = Semestre.ABIERTO, None, None
    semestre.save()
    return semestre


def cambios_desde_reapertura(semestre):
    """Las calificaciones definitivas que cambiaron al volver a cerrar (del último cierre), o [] si no hay."""
    ultimo = _ultimo_cierre(semestre)
    return ultimo.datos.get('cambios', []) if ultimo else []


# ---------------------------------------------------------------------------
# Captura de exámenes (celda por celda, con bitácora)
# ---------------------------------------------------------------------------
def motivo_de_solo_lectura(asignacion, usuario, semestre):
    """Por qué no se captura ningún examen en la hoja ('' si algo se puede capturar, según cada estudiante)."""
    from .reglas import puede_capturar
    if semestre is None:
        return 'La materia no es de un semestre de bachillerato.'
    if not puede_capturar(usuario, asignacion):
        return 'Solo consulta: no capturas las calificaciones de esta materia.'
    if semestre.estado == Semestre.PENDIENTE:
        return f'El {semestre.en_frase} todavía no se abre.'
    return ''   # abierto, o cerrado con extraordinarios o regularizaciones pendientes: se decide por estudiante


def editables(fila, semestre, usuario_puede):
    """Los exámenes de la fila que se pueden capturar o corregir ahora."""
    if not usuario_puede:
        return set()
    return fila.resultado.capturable & ventana(semestre)


def _guardar_examen(asignacion, semestre, fila, cambio, usuario):
    from .reglas import CapturaRechazada, leer_calificacion, numero
    tipo = cambio.get('id')
    if tipo not in TIPOS:
        raise CapturaRechazada('Examen no válido.')
    nuevo = leer_calificacion(cambio.get('valor', ''))
    registro = ExamenSemestral.objects.select_for_update().filter(asignacion=asignacion, inscripcion=fila.inscripcion, tipo=tipo).first()
    actual = registro.valor if registro else None
    if actual == nuevo:
        return numero(nuevo)   # ya estaba así (un reintento)
    if 'anterior' in cambio:
        try:
            esperado = leer_calificacion(cambio.get('anterior'))
        except CapturaRechazada:
            esperado = object()
        if esperado != actual:
            raise CapturaRechazada(f'Alguien más lo cambió mientras tanto (ahora es «{numero(actual) or "vacío"}»). Recarga para ver lo actual.')
    if tipo not in editables(fila, semestre, True):
        if tipo == cs.FINAL and semestre.cerrado:
            raise CapturaRechazada(f'El {semestre.en_frase} está cerrado: el examen final ya no se cambia.')
        if tipo == cs.FINAL and fila.resultado.situacion == cs.EXENTO:
            raise CapturaRechazada('Está exento: su examen final se asigna con el promedio de periodos.')
        if tipo == cs.FINAL and fila.resultado.situacion == cs.SIN_DERECHO:
            raise CapturaRechazada('Con promedio menor que 6.0 no tiene derecho a examen final: pasa a extraordinario.')
        if fila.resultado.estado == cs.PENDIENTE_PERIODOS:
            raise CapturaRechazada('Todavía falta la calificación de algún periodo (con su acta cerrada).')
        raise CapturaRechazada(f'No corresponde capturar {NOMBRES_DE_EXAMEN[tipo].lower()}: solo se corrige el último examen capturado.')
    if nuevo is None:
        registro.delete()
    elif registro:
        registro.valor, registro.modificado_por = nuevo, usuario
        registro.save(update_fields=['valor', 'modificado_por', 'modificado'])
    else:
        ExamenSemestral.objects.create(asignacion=asignacion, inscripcion=fila.inscripcion, tipo=tipo, valor=nuevo, modificado_por=usuario)
    CambioSemestre.objects.create(semestre=semestre, accion=CambioSemestre.EXAMEN, asignacion=asignacion, inscripcion=fila.inscripcion,
                                  que=f'{NOMBRES_DE_EXAMEN[tipo]} · {asignacion.materia}', anterior=numero(actual), nuevo=numero(nuevo), usuario=usuario)
    return numero(nuevo)


def guardar_examenes(asignacion, usuario, cambios):
    """Guarda una lista de cambios [{'clave', 'tipo': 'examen', 'id': tipo de examen, 'inscripcion', 'valor',
    'anterior'}]; cada uno se valida por separado. Devuelve ([{'clave', 'ok', 'valor' o 'error'}], hoja recalculada)."""
    from .reglas import CapturaRechazada
    semestre = semestre_de_asignacion(asignacion)
    motivo = motivo_de_solo_lectura(asignacion, usuario, semestre)
    if motivo:
        raise CapturaRechazada(motivo)
    resultados = []
    for cambio in cambios[:500]:
        clave = cambio.get('clave', '')
        try:
            with transaction.atomic():
                semestre = _bloquear(semestre)   # nadie lo cierra a la mitad del guardado
                fila = next((f for f in hoja(asignacion, semestre).filas if str(f.inscripcion.pk) == str(cambio.get('inscripcion'))), None)
                if fila is None:
                    raise CapturaRechazada('Ese estudiante no está en este grupo.')
                if cambio.get('tipo') != 'examen':
                    raise CapturaRechazada('Cambio no válido.')
                valor = _guardar_examen(asignacion, semestre, fila, cambio, usuario)
            resultados.append({'clave': clave, 'ok': True, 'valor': valor})
        except CapturaRechazada as error:
            resultados.append({'clave': clave, 'ok': False, 'error': error.mensaje})
    return resultados, hoja(asignacion, semestre)


def movimientos(asignacion, limite=100):
    """Los exámenes capturados o corregidos de la materia (bitácora del semestre), del más reciente."""
    return list(CambioSemestre.objects.filter(asignacion=asignacion, accion=CambioSemestre.EXAMEN)
                .select_related('usuario', 'inscripcion__alumno')[:limite])


# ---------------------------------------------------------------------------
# Fechas de los semestres y periodos
# ---------------------------------------------------------------------------
@transaction.atomic
def guardar_fechas(ciclo, fechas, usuario):
    """Crea o actualiza los semestres del ciclo: `fechas` = {'A': (inicio, fin), 'B': (inicio, fin)} (ya validadas
    por el formulario). Los periodos de preparatoria sin semestre que empiezan dentro de uno se le asignan."""
    guardados = []
    for clave, (inicio, fin) in fechas.items():
        semestre = Semestre.objects.filter(ciclo=ciclo, clave=clave).first()
        if semestre is None:
            semestre = Semestre.objects.create(ciclo=ciclo, clave=clave, fecha_inicio=inicio, fecha_fin=fin)
            CambioSemestre.objects.create(semestre=semestre, accion=CambioSemestre.FECHAS, que=f'Alta del {semestre.en_frase}',
                                          nuevo=f'{inicio:%d/%m/%Y} al {fin:%d/%m/%Y}', usuario=usuario)
        elif (semestre.fecha_inicio, semestre.fecha_fin) != (inicio, fin):
            antes = f'{semestre.fecha_inicio:%d/%m/%Y} al {semestre.fecha_fin:%d/%m/%Y}'
            semestre.fecha_inicio, semestre.fecha_fin = inicio, fin
            semestre.save()
            CambioSemestre.objects.create(semestre=semestre, accion=CambioSemestre.FECHAS, que=f'Fechas del {semestre.en_frase}',
                                          anterior=antes, nuevo=f'{inicio:%d/%m/%Y} al {fin:%d/%m/%Y}', usuario=usuario)
        guardados.append(semestre)
    for semestre in guardados:
        (Periodo.objects.filter(ciclo=ciclo, nivel=NIVEL_POR_SEMESTRES, semestre__isnull=True,
                                fecha_inicio__range=(semestre.fecha_inicio, semestre.fecha_fin)).update(semestre=semestre))
    return guardados


def periodos_sin_semestre(ciclo):
    """Los periodos de preparatoria del ciclo que no tienen semestre (si el ciclo tiene semestres)."""
    if ciclo is None or not Semestre.objects.filter(ciclo=ciclo).exists():
        return []
    return list(Periodo.objects.filter(ciclo=ciclo, nivel=NIVEL_POR_SEMESTRES, semestre__isnull=True).order_by('fecha_inicio'))


# ---------------------------------------------------------------------------
# Cierre del ciclo
# ---------------------------------------------------------------------------
def impide_cerrar_ciclo(ciclo):
    """Lo que impide cerrar el ciclo por sus semestres: alguno sin cerrar (textos; vacío si no hay semestres o todos
    están cerrados)."""
    return [f'El {s.en_frase} de bachillerato está {s.get_estado_display().lower()}: ciérralo antes de cerrar el ciclo.'
            for s in Semestre.objects.filter(ciclo=ciclo).order_by('clave') if not s.cerrado]


def procesos_abiertos_del_ciclo(ciclo):
    """{semestre: cuántos extraordinarios o regularizaciones siguen pendientes} de los semestres cerrados del ciclo."""
    abiertos = {}
    for semestre in Semestre.objects.filter(ciclo=ciclo, estado=Semestre.CERRADO).order_by('clave'):
        cantidad = sum(h.contar(lambda r: r.proceso_abierto) for h in hojas(asignaciones_del_semestre(semestre), semestre).values())
        if cantidad:
            abiertos[semestre] = cantidad
    return abiertos
