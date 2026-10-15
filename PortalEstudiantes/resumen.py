"""Lo que ve un estudiante de sí mismo en su portal (y su tutor, en el suyo).

Todo es del ciclo actual y de la inscripción vigente: el horario del grupo con sus recesos, las clases de hoy, la
asistencia general (sin los días de una suspensión autorizada; las faltas justificadas se cuentan aparte) y las
calificaciones de los periodos ya cerrados. Solo se muestran las actas cerradas: mientras un periodo está en captura
sus calificaciones pueden cambiar.
"""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from Alumnos.asistencias import con_justificada_general, conteos, motivo_sin_clases, porcentaje, sin_dias_suspendidos
from Alumnos.horarios import cuadricula, recreos_del_grupo
from Alumnos.models import AsistenciaGeneral, HorarioMateria, MateriaGrado, Periodo

INCIDENCIAS_RECIENTES = 6


def inscripcion_actual(alumno):
    """La inscripción activa del estudiante en el ciclo actual, o None."""
    return (
        alumno.inscripciones.filter(activa=True, ciclo__activo=True)
        .select_related('ciclo', 'grado', 'grupo__nombre', 'grupo__grado')
        .order_by('-ciclo__fecha_inicio').first()
    )


def _promedio(valores):
    valores = [v for v in valores if v is not None]
    if not valores:
        return None
    return (sum(valores) / len(valores)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Horario y clases de hoy
# ---------------------------------------------------------------------------
@dataclass
class ClaseDeHoy:
    nombre: str
    detalle: str
    inicio: object
    fin: object
    es_receso: bool
    momento: str   # 'pasada', 'ahora' o 'proxima'


def _horario(inscripcion):
    bloques = list(
        HorarioMateria.objects.filter(
            materia_grado__grupo=inscripcion.grupo, materia_grado__ciclo=inscripcion.ciclo, materia_grado__activa=True,
        ).select_related('materia_grado__materia', 'materia_grado__profesor')
    )
    return bloques + list(recreos_del_grupo(inscripcion.grupo, inscripcion.ciclo))


def _clases_de_hoy(inscripcion, bloques, ahora):
    """(lista de ClaseDeHoy, motivo por el que hoy no hay clases o '')."""
    hoy, ciclo = ahora.date(), inscripcion.ciclo
    if not ciclo.fecha_inicio <= hoy <= ciclo.fecha_fin:
        return [], 'Hoy está fuera de las fechas del ciclo escolar.'
    motivo = motivo_sin_clases(hoy, ciclo, nivel=inscripcion.grado.nivel)
    if motivo:
        return [], motivo
    hora, clases = ahora.time(), []
    for bloque in sorted((b for b in bloques if b.dia_semana == hoy.weekday()), key=lambda b: (b.hora_inicio, b.hora_fin)):
        momento = 'pasada' if bloque.hora_fin <= hora else ('ahora' if bloque.hora_inicio <= hora else 'proxima')
        if getattr(bloque, 'es_recreo', False):
            clases.append(ClaseDeHoy(bloque.nombre, 'Receso de todo el grupo', bloque.hora_inicio, bloque.hora_fin, True, momento))
        else:
            asignacion = bloque.materia_grado
            profesor = asignacion.profesor.nombre_completo if asignacion.profesor_id else 'Profesor por asignar'
            clases.append(ClaseDeHoy(asignacion.materia.nombre, profesor, bloque.hora_inicio, bloque.hora_fin, False, momento))
    return clases, ''


# ---------------------------------------------------------------------------
# Asistencia
# ---------------------------------------------------------------------------
def _asistencia(inscripcion, hoy):
    registros = sin_dias_suspendidos(con_justificada_general(AsistenciaGeneral.objects.filter(inscripcion=inscripcion)))
    totales = conteos(registros)
    return {
        **totales,
        'porcentaje': porcentaje(totales['presentes'], totales['retardos'], totales['registros']),
        'sin_justificar': totales['faltas'] - totales['justificadas'],
        'hoy': registros.filter(fecha=hoy).first(),
        'incidencias': list(registros.exclude(estado='PRESENTE').order_by('-fecha')[:INCIDENCIAS_RECIENTES]),
    }


# ---------------------------------------------------------------------------
# Calificaciones de los periodos cerrados
# ---------------------------------------------------------------------------
@dataclass
class FilaDeCalificaciones:
    materia: str
    profesor: str
    valores: list            # una calificación (Decimal) o None por periodo, en el orden de las columnas
    promedio: Decimal = None


@dataclass
class Calificaciones:
    periodos: list = field(default_factory=list)
    filas: list = field(default_factory=list)
    promedios_por_periodo: list = field(default_factory=list)
    promedio_general: Decimal = None
    cerrados: int = 0        # periodos con al menos una materia cerrada


def _calificaciones(inscripcion):
    from Calificaciones.models import ActaCalificaciones

    periodos = list(Periodo.objects.filter(ciclo=inscripcion.ciclo, nivel=inscripcion.grado.nivel).order_by('fecha_inicio', 'nombre'))
    asignaciones = list(
        MateriaGrado.objects.filter(grupo=inscripcion.grupo, ciclo=inscripcion.ciclo, activa=True)
        .select_related('materia', 'profesor').order_by('materia__nombre')
    )
    finales = {}
    actas = ActaCalificaciones.objects.filter(
        asignacion__in=asignaciones, periodo__in=periodos, estado=ActaCalificaciones.CERRADA,
    ).only('asignacion_id', 'periodo_id', 'resultados_cerrados')
    for acta in actas:
        fila = next((r for r in acta.resultados_cerrados if r.get('inscripcion') == inscripcion.pk), None)
        if fila and fila.get('final') not in (None, ''):
            finales[(acta.asignacion_id, acta.periodo_id)] = Decimal(fila['final'])

    filas = []
    for asignacion in asignaciones:
        valores = [finales.get((asignacion.pk, periodo.pk)) for periodo in periodos]
        profesor = asignacion.profesor.nombre_completo if asignacion.profesor_id else ''
        filas.append(FilaDeCalificaciones(asignacion.materia.nombre, profesor, valores, _promedio(valores)))
    por_periodo = [_promedio([fila.valores[indice] for fila in filas]) for indice in range(len(periodos))]
    return Calificaciones(
        periodos=periodos, filas=filas, promedios_por_periodo=por_periodo,
        promedio_general=_promedio([fila.promedio for fila in filas]),
        cerrados=sum(1 for valor in por_periodo if valor is not None),
    )


# ---------------------------------------------------------------------------
# Todo junto
# ---------------------------------------------------------------------------
def resumen(alumno, completo=True):
    """Lo que muestra el portal de un estudiante. Con completo=False (las tarjetas del portal de tutores) no arma el
    horario ni la tabla de calificaciones, solo los totales."""
    ahora = timezone.localtime()
    inscripcion = inscripcion_actual(alumno)
    datos = {'alumno': alumno, 'inscripcion': inscripcion, 'hoy': ahora.date()}
    if inscripcion is None:
        return datos
    bloques = _horario(inscripcion)
    clases_hoy, sin_clases_hoy = _clases_de_hoy(inscripcion, bloques, ahora)
    calificaciones = _calificaciones(inscripcion)
    datos.update({
        'ciclo': inscripcion.ciclo,
        'asistencia': _asistencia(inscripcion, ahora.date()),
        'clases_hoy': clases_hoy,
        'sin_clases_hoy': sin_clases_hoy,
        'calificaciones': calificaciones,
    })
    if completo:
        datos.update({
            'cuadricula': cuadricula(bloques),
            'etiqueta_horario': f'Horario semanal de {inscripcion.grupo} en el ciclo {inscripcion.ciclo}',
        })
    return datos
