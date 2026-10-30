"""Lo que ve un estudiante de sí mismo en su portal (y su tutor, en el suyo).

Todo es del ciclo actual y de la inscripción vigente: el horario del grupo con sus recesos, las clases de hoy, la
asistencia general (sin los días de una suspensión autorizada; las faltas justificadas se cuentan aparte) y las
calificaciones de los periodos ya cerrados. Solo se muestran las actas cerradas: mientras un periodo está en captura
sus calificaciones pueden cambiar. En bachillerato por semestres (2026-10-28), además, el resultado de cada semestre
cerrado del ciclo (examen final, extraordinario, regularización y definitiva), con los mismos números que la hoja
semestral de Calificaciones.
"""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q
from django.utils import timezone

from Alumnos.asistencias import con_justificada_general, conteos, motivo_sin_clases, porcentaje, sin_dias_suspendidos
from Alumnos.clases import bloques_del_estudiante, materias_cursadas
from Alumnos.horarios import cuadricula, recreos_del_grupo
from Alumnos.models import NIVEL_POR_SEMESTRES, AsistenciaGeneral
from Alumnos.periodos import periodos_para_grado
from Alumnos.semanas import Calendario

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


def _horario(inscripcion, fecha, calendario):
    """El horario del grupo en la semana de esa fecha: con semanas A y B, el de la que le toca; y la versión del
    horario en vigor cada día (Alumnos/semanas.py)."""
    bloques = list(
        bloques_del_estudiante(inscripcion, fecha, calendario)   # con sus grupos de clase: solo la opción que cursa
        .select_related('materia_grado__materia', 'materia_grado__profesor', 'materia_grado__grupo')
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
    asignacion: object = None   # la materia del grupo (la Vista 360 del expediente revisa con ella quién puede verla)


@dataclass
class Calificaciones:
    periodos: list = field(default_factory=list)
    filas: list = field(default_factory=list)
    promedios_por_periodo: list = field(default_factory=list)
    promedio_general: Decimal = None
    cerrados: int = 0        # periodos con al menos una materia cerrada


def _calificaciones(inscripcion):
    from Calificaciones.models import ActaCalificaciones

    periodos = list(periodos_para_grado(inscripcion.ciclo, inscripcion.grado))
    cursadas = materias_cursadas(inscripcion)   # con sus grupos de clase; una materia, una sola fila
    finales = {}
    actas = ActaCalificaciones.objects.filter(
        asignacion__in=[a for c in cursadas for a in c.asignaciones], periodo__in=periodos, estado=ActaCalificaciones.CERRADA,
    ).only('asignacion_id', 'periodo_id', 'resultados_cerrados')
    for acta in actas:
        fila = next((r for r in acta.resultados_cerrados if r.get('inscripcion') == inscripcion.pk), None)
        if fila and fila.get('final') not in (None, ''):
            finales[(acta.asignacion_id, acta.periodo_id)] = Decimal(fila['final'])

    filas = []
    for cursada in cursadas:
        # De la asignación más reciente en que tenga calificación de ese periodo
        valores = [next((finales[(a.pk, periodo.pk)] for a in reversed(cursada.asignaciones) if (a.pk, periodo.pk) in finales), None)
                   for periodo in periodos]
        if cursada.sustituida and not any(v is not None for v in valores):
            continue   # un bloque se la sustituyó antes de calificarla
        asignacion = cursada.actual
        profesor = asignacion.profesor.nombre_completo if asignacion.profesor_id else ''
        filas.append(FilaDeCalificaciones(cursada.materia.nombre, profesor, valores, _promedio(valores), asignacion))
    por_periodo = [_promedio([fila.valores[indice] for fila in filas]) for indice in range(len(periodos))]
    return Calificaciones(
        periodos=periodos, filas=filas, promedios_por_periodo=por_periodo,
        promedio_general=_promedio([fila.promedio for fila in filas]),
        cerrados=sum(1 for valor in por_periodo if valor is not None),
    )


# ---------------------------------------------------------------------------
# Bachillerato por semestres: los semestres cerrados del ciclo
# ---------------------------------------------------------------------------
@dataclass
class SemestreDelPortal:
    semestre: object
    grupo: object
    filas: list = field(default_factory=list)


def semestrales(alumno, ciclo):
    """Por cada semestre del ciclo que ya se cerró y en el que estuvo inscrito: sus materias con el promedio de
    periodos, el examen final (o la exención), la final ordinaria, el extraordinario, la regularización, la definitiva
    y el estado. Mientras un semestre está abierto no se muestra: sus resultados todavía pueden cambiar."""
    from Calificaciones import calculo_semestral as cs
    from Calificaciones import semestres as reglas_semestres
    lista = []
    inscripciones = (alumno.inscripciones.filter(Q(activa=True) | Q(concluida=True), ciclo=ciclo, grado__nivel=NIVEL_POR_SEMESTRES)
                     .select_related('grado', 'ciclo', 'grupo__nombre', 'grupo__grado'))
    for inscripcion in inscripciones:
        semestre = reglas_semestres.semestre_de_grado_en(inscripcion.grado, ciclo)
        if semestre is None or not semestre.cerrado:
            continue
        asignaciones = [c.actual for c in materias_cursadas(inscripcion)]
        hojas = reglas_semestres.hojas(asignaciones, semestre)
        datos = SemestreDelPortal(semestre=semestre, grupo=inscripcion.grupo)
        for asignacion in asignaciones:
            fila = next((f for f in hojas[asignacion.pk].filas if f.inscripcion.pk == inscripcion.pk), None)
            if fila is None:
                continue
            r = fila.resultado
            datos.filas.append({
                'materia': asignacion.materia.nombre, 'profesor': asignacion.profesor.nombre_completo if asignacion.profesor_id else '',
                'promedio': cs.texto(r.promedio), 'exento': r.final_por_exencion, 'final': cs.texto(r.examen_final),
                'ordinaria': cs.texto(r.ordinaria), 'extraordinario': cs.texto(r.extraordinario), 'regularizacion': cs.texto(r.regularizacion),
                'definitiva': cs.texto(r.definitiva), 'estado': r.estado_texto,
                'estilo': 'aprobada' if r.aprobada else ('reprobada' if r.reprobada else 'pendiente'),
            })
        lista.append(datos)
    return sorted(lista, key=lambda s: s.semestre.clave)


def calificaciones_de(inscripcion):
    """Las calificaciones de las actas cerradas de la inscripción (también las usa la Vista 360 del expediente)."""
    return _calificaciones(inscripcion)


def promedio(valores):
    """El promedio que usa el sistema para juntar calificaciones (sin las pendientes), a dos decimales."""
    return _promedio(valores)


# ---------------------------------------------------------------------------
# Todo junto
# ---------------------------------------------------------------------------
def resumen(alumno, completo=True, semana=None):
    """Lo que muestra el portal de un estudiante. Con completo=False (las tarjetas del portal de tutores) no arma el
    horario ni la tabla de calificaciones, solo los totales. `semana`: una fecha de la semana cuyo horario se muestra
    (por omisión, la de hoy)."""
    ahora = timezone.localtime()
    inscripcion = inscripcion_actual(alumno)
    datos = {'alumno': alumno, 'inscripcion': inscripcion, 'hoy': ahora.date()}
    if inscripcion is None:
        return datos
    calendario = Calendario(inscripcion.ciclo)
    bloques = _horario(inscripcion, ahora.date(), calendario)
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
        ciclo, nivel = inscripcion.ciclo, inscripcion.grado.nivel
        fecha = min(max(semana or ahora.date(), ciclo.fecha_inicio), ciclo.fecha_fin)
        info = calendario.info(fecha, nivel)
        de_la_semana = bloques if info.lunes == calendario.info(ahora.date(), nivel).lunes else _horario(inscripcion, fecha, calendario)
        datos.update({
            'semestrales': semestrales(alumno, ciclo) if nivel == NIVEL_POR_SEMESTRES else [],
            'cuadricula': cuadricula(de_la_semana),
            'etiqueta_horario': (f'Horario de {inscripcion.grupo}, {info.nombre.lower()}, del {info.rango}' if info.alternada
                                 else f'Horario semanal de {inscripcion.grupo} en el ciclo {ciclo}'),
            # Semanas A y B: la que se muestra, con sus fechas, y las de al lado para navegar
            'semana': info if info.alternada else None,
            'es_esta_semana': info.lunes == calendario.info(ahora.date(), nivel).lunes,
            'puede_anterior': info.lunes > ciclo.fecha_inicio,
            'puede_siguiente': info.siguiente <= ciclo.fecha_fin,
        })
    return datos
