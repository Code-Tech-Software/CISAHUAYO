"""Asistencia para docentes: la matriz de una materia (estudiantes × días del ciclo) y los cambios que el docente puede
hacer en ella.

Usa los registros de asistencia por materia (`AsistenciaMateria`: por estudiante, por materia del grupo y por día) que
también crean la entrada al colegio y el cierre del día: lo que el docente cambia aquí se ve en la asistencia por
materia de la administración y en los reportes, y al revés. Se guarda con `guardar_pase_de_lista`, así que marcar
presente o retardo también deja constancia de que el estudiante estuvo en el colegio.

Reglas acordadas con el usuario (2026-10-12):
- Solo materias asignadas al docente (`MateriaGrado.profesor`), del ciclo actual; cada grupo es una materia aparte.
- Columnas: los días de lunes a viernes del ciclo; por omisión solo el mes en curso, o el rango que se elija (siempre
  dentro del ciclo). Una fila de meses y líneas entre meses y semanas ayudan a ubicarse (pedido del 2026-10-12).
- La asistencia no depende del periodo de evaluación (pedido del 2026-10-27): entre un periodo y otro, sin periodos o
  con el periodo cerrado a mano para las calificaciones, se sigue pasando lista. El docente captura y corrige solo los
  últimos días (`ConfiguracionAsistencia.dias_para_corregir`, la `ventana`); lo anterior lo corrige la administración,
  que no tiene ese plazo. El periodo abierto solo se muestra como referencia y como rango rápido.
- El docente pone Presente, Falta o Retardo; una falta o un retardo lleva su observación (por qué), que se guarda
  en las observaciones del mismo registro. Poner presente la borra. No justifica: la falta justificada (J) se ve y queda
  bloqueada (la justifica la administración), igual que cualquier celda que cubra una justificación vigente.
- Suspensión (S, días sin clases) bloqueada para todos; fechas futuras y días en que la materia no tiene clase según
  su horario, bloqueados. Una celda sin registro muestra «—» (no es falta) y el docente puede hacer la primera captura.
- Suspensión de un estudiante (pedido del 2026-10-14): sus días se marcan con una S en un círculo blanco. Autorizada
  (borde continuo), la celda queda bloqueada y no cuenta como falta ni asistencia; pendiente de autorizar (borde
  punteado), solo avisa: si el estudiante asistió se puede capturar su asistencia.
- Cada cambio se valida en el servidor y se rechaza si alguien más cambió esa celda mientras tanto (versión).

La administración usa la misma matriz con todas las materias del ciclo (Asistencias/views_materias.py, pedido del
2026-10-13) y, además, justifica una falta registrada con la foto de su comprobante (`justificar_falta`): se guarda
como una `Justificacion` de esa materia vinculada al registro de la falta, así que la J aparece igual aquí, en la
vista del docente, en los reportes y en Justificaciones. La falta sigue siendo falta (no se vuelve asistencia).
"""
import logging
from dataclasses import dataclass
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from .academico import ciclo_actual
from .asistencias import asistencia_editable, guardar_pase_de_lista, porcentaje
from .models import (
    AsistenciaMateria,
    DiaNoLectivo,
    HorarioMateria,
    Inscripcion,
    Justificacion,
    MateriaGrado,
    orden_de_nivel,
)
from .periodos import periodo_abierto

logger = logging.getLogger(__name__)

# Lo que el docente puede poner, con su letra
ESTADOS_DEL_DOCENTE = {'PRESENTE': 'P', 'FALTA': 'F', 'RETARDO': 'R'}
# Una falta o un retardo se explican (pedido del 2026-10-12); el texto cabe en AsistenciaMateria.observaciones
CON_OBSERVACION = ('FALTA', 'RETARDO')
OBSERVACION_MINIMA, OBSERVACION_MAXIMA = 3, 250
LETRA_DE_ESTADO = ESTADOS_DEL_DOCENTE
NOMBRES = {
    'P': 'Presente', 'F': 'Falta', 'J': 'Falta justificada', 'S': 'Suspensión de clases', 'R': 'Retardo',
}
# Clase CSS de cada indicador (static/css/asistencias.css, «Asistencia para docentes»)
CLASES = {'P': 'presente', 'F': 'falta', 'J': 'justificada', 'S': 'suspension', 'R': 'retardo'}
# La suspensión de un estudiante: autorizada o pendiente de autorizar (una S en un círculo blanco)
SUSPENDIDO, SOLICITADO = 'suspendido', 'solicitado'
LEYENDA = [
    ('P', NOMBRES['P'], 'presente'), ('F', NOMBRES['F'], 'falta'), ('R', NOMBRES['R'], 'retardo'),
    ('J', NOMBRES['J'], 'justificada'), ('S', NOMBRES['S'], 'suspension'),
    ('S', 'Estudiante suspendido (suspensión autorizada)', SUSPENDIDO), ('S', 'Suspensión pendiente de autorizar', SOLICITADO),
]
DIAS = ('lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo')
INICIALES = ('L', 'M', 'M', 'J', 'V', 'S', 'D')
MESES_LARGOS = (
    'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
)


class CambioRechazado(Exception):
    """El cambio no se guardó: `mensaje` para la persona y `codigo` HTTP (400, 403 o 409)."""

    def __init__(self, mensaje, codigo=400):
        super().__init__(mensaje)
        self.mensaje, self.codigo = mensaje, codigo


@dataclass
class Celda:
    letra: str          # 'P', 'F', 'R', 'J', 'S', '—' (sin registro, editable) o '' (bloqueada sin registro)
    nombre: str         # lo que dice el globo de ayuda
    editable: bool
    version: str = ''   # marca de la última modificación del registro ('' si no hay registro)
    hoy: bool = False   # la columna de hoy (se resalta)
    apagada: bool = False   # su columna está bloqueada (suspensión, futuro o sin clase): fondo gris
    inicio_mes: bool = False      # primera columna de un mes (línea fuerte a la izquierda)
    inicio_semana: bool = False   # primera columna de una semana (línea fina)
    observaciones: str = ''       # por qué la falta o el retardo (lo que escribió el docente)
    justificable: bool = False    # una falta registrada que quien administra puede justificar (nunca en la del docente)
    justificacion: object = None  # en una J, la justificación que la cubre (su comprobante, quién y cuándo)
    estilo: str = ''              # suspensión del estudiante: SUSPENDIDO o SOLICITADO (manda sobre la clase de la letra)

    @property
    def clase(self):
        return self.estilo or CLASES.get(self.letra, 'vacia' if self.letra == '—' else 'nada')


# ---------------------------------------------------------------------------
# Qué materias, qué periodo y qué días
# ---------------------------------------------------------------------------
def _sin_grados_ocultos(asignaciones, ciclo):
    """En el ciclo actual o en uno próximo, sin las materias de los grados ocultos (2026-10-28: no se ofrecen para pasar
    lista ni capturar mientras lo estén); en uno cerrado (historial), todas."""
    return asignaciones if ciclo.estado == 'CERRADO' else asignaciones.filter(grado__visible=True)


def asignaciones_del_profesor(profesor, ciclo=None):
    """Las materias (una por grupo) que el profesor imparte en el ciclo (el actual si no se indica)."""
    ciclo = ciclo or ciclo_actual()
    if profesor is None or ciclo is None:
        return MateriaGrado.objects.none()
    return (
        _sin_grados_ocultos(MateriaGrado.objects.filter(profesor=profesor, ciclo=ciclo, activa=True, materia__activa=True), ciclo)
        .select_related('materia', 'ciclo', 'grado', 'grupo__nombre', 'grupo__grado')
        .order_by('materia__nombre', 'grupo__grado__numero', 'grupo__nombre__orden', 'grupo__nombre__nombre')
    )


def asignaciones_del_ciclo(ciclo=None):
    """Todas las materias (una por grupo) del ciclo (el actual si no se indica), en orden escolar: lo que consulta la
    administración."""
    ciclo = ciclo or ciclo_actual()
    if ciclo is None:
        return MateriaGrado.objects.none()
    return (
        _sin_grados_ocultos(MateriaGrado.objects.filter(ciclo=ciclo, activa=True, materia__activa=True), ciclo)
        .select_related('materia', 'ciclo', 'grado', 'grupo__nombre', 'grupo__grado', 'profesor')
        .order_by(orden_de_nivel('grado__nivel'), 'grado__numero', 'grupo__nombre__orden', 'grupo__nombre__nombre', 'materia__nombre')
    )


def periodo_de(asignacion):
    """El periodo de evaluación abierto hoy del nivel de la materia, en su ciclo (o None). Solo de referencia: la
    asistencia no depende de él."""
    return periodo_abierto(asignacion.grado.nivel, ciclo=asignacion.ciclo)


def limites_de(asignacion):
    """(primer día, último día) que se pueden ver de la materia: las fechas de su ciclo."""
    return asignacion.ciclo.fecha_inicio, asignacion.ciclo.fecha_fin


def ventana_del_docente():
    """Cuántos días hacia atrás (además de hoy) captura y corrige un docente su asistencia."""
    from .models import ConfiguracionAsistencia
    return ConfiguracionAsistencia.cargar().dias_para_corregir


def fuera_de_la_ventana(fecha, hoy, ventana):
    """Si la fecha ya pasó del plazo del docente (`ventana` días antes de hoy); sin ventana (la administración), nunca."""
    return ventana is not None and fecha < hoy - timedelta(days=ventana)


def inscripciones_de(asignacion):
    """Los estudiantes de la materia: inscritos (activos) en su grupo y ciclo, con estatus activo."""
    return (
        Inscripcion.objects.filter(grupo=asignacion.grupo, ciclo=asignacion.ciclo, activa=True, alumno__estatus='ACTIVO')
        .select_related('alumno')
        .order_by('alumno__apellido_paterno', 'alumno__apellido_materno', 'alumno__nombre')
    )


def version_de(registro):
    """Marca de la última modificación de un registro ('' si no hay): el mismo instante da el mismo texto, sin
    importar la zona horaria con que se haya leído."""
    return f'{registro.modificado.timestamp():.6f}' if registro is not None else ''


def _justificaciones(asignacion, inscripciones, desde, hasta):
    """{(id de inscripción, fecha): justificación} de las vigentes que cubren esa materia (o todas). Si un día lo cubren
    varias, la que se hizo desde esa falta (con su comprobante)."""
    cubiertas = {}
    vigentes = (
        Justificacion.objects.filter(activa=True, inscripcion__in=inscripciones, fecha__range=(desde, hasta))
        .filter(Q(todas_materias=True) | Q(materias=asignacion))
        .select_related('registrada_por', 'inscripcion__alumno', 'inscripcion__ciclo').distinct().order_by('creado')
    )
    for justificacion in vigentes:
        clave = (justificacion.inscripcion_id, justificacion.fecha)
        if clave not in cubiertas or justificacion.asistencia_id:
            cubiertas[clave] = justificacion
    return cubiertas


def _suspensiones_de(inscripciones, desde, hasta):
    """{(id de inscripción, fecha): suspensión} de los estudiantes con una suspensión autorizada o pendiente de autorizar
    (de un registro de conducta no anulado) en esas fechas; si un día tiene las dos, manda la autorizada."""
    from Conducta.models import APROBADA, PENDIENTE, Suspension

    por_alumno = {inscripcion.alumno_id: inscripcion.pk for inscripcion in inscripciones}
    if not por_alumno:
        return {}
    dias = {}
    suspensiones = Suspension.objects.filter(
        registro__alumno__in=por_alumno, registro__anulado=False, aprobacion__in=(APROBADA, PENDIENTE),
        fecha_inicio__lte=hasta, fecha_fin__gte=desde,
    ).select_related('registro')
    for suspension in suspensiones:
        fecha = max(suspension.fecha_inicio, desde)
        while fecha <= min(suspension.fecha_fin, hasta):
            clave = (por_alumno[suspension.registro.alumno_id], fecha)
            if clave not in dias or suspension.aprobada:
                dias[clave] = suspension
            fecha += timedelta(days=1)
    return dias


def _con_suspension(celda, suspension_del_alumno):
    """La celda de un día con suspensión del estudiante: autorizada, una S bloqueada (no es falta ni asistencia);
    pendiente, una S que solo avisa (si hay registro, se ve el registro con el aviso)."""
    s = suspension_del_alumno
    texto = f'del {s.fecha_inicio:%d/%m} al {s.fecha_fin:%d/%m}: {s.motivo_nombre}'
    if s.aprobada:
        return Celda('S', f'Suspendido: suspensión autorizada {texto}', False, celda.version, estilo=SUSPENDIDO)
    if celda.letra in ('—', ''):
        celda.letra, celda.estilo = 'S', SOLICITADO
        celda.nombre = f'Suspensión pendiente de autorizar {texto}' + ('. Si asistió, puedes capturar su asistencia.' if celda.editable else '')
    else:
        celda.nombre = f'{celda.nombre} · suspensión pendiente de autorizar {texto}'
    return celda


def _celda(registro, fecha, hoy, inscripcion, suspension, con_clase, justificacion, materia, puede_editar, puede_justificar=False,
           suspension_del_alumno=None, ventana=None):
    """La celda de un estudiante en un día, con lo que se ve, si el docente la puede cambiar (y si no, por qué) y la
    observación del registro (también en el globo de ayuda). Para quien administra (`puede_justificar`), además, si es
    una falta que se puede justificar; en una J va la justificación que la cubre. Un día con suspensión del estudiante
    (`suspension_del_alumno`) se marca con su S. Con `ventana` (la del docente), lo que ya pasó del plazo se bloquea."""
    celda = _celda_sin_observacion(
        registro, fecha, hoy, inscripcion, suspension, con_clase, justificacion is not None, materia, puede_editar, ventana,
    )
    if registro is not None and registro.observaciones and celda.letra not in ('S', ''):
        celda.observaciones = registro.observaciones
        celda.nombre = f'{celda.nombre}. Observación: {registro.observaciones}'
    if celda.letra == 'J':
        celda.justificacion = justificacion
    celda.justificable = puede_justificar and celda.letra == 'F' and fecha >= inscripcion.fecha_inscripcion
    if suspension_del_alumno is not None and suspension is None and fecha >= inscripcion.fecha_inscripcion:
        celda = _con_suspension(celda, suspension_del_alumno)
    return celda


def _celda_sin_observacion(registro, fecha, hoy, inscripcion, suspension, con_clase, justificada, materia, puede_editar, ventana=None):
    letra = LETRA_DE_ESTADO.get(registro.estado) if registro is not None else None
    version = version_de(registro)
    if suspension is not None:
        return Celda('S', f'Suspensión de clases: {suspension}' if suspension else NOMBRES['S'], False, version)
    if fecha < inscripcion.fecha_inscripcion:
        return Celda(letra or '', f'{NOMBRES[letra]} · aún no estaba inscrito' if letra else 'Aún no estaba inscrito', False, version)
    if justificada:
        if letra in (None, 'F'):
            return Celda('J', 'Falta justificada: se cambia desde Justificaciones', False, version)
        return Celda(letra, f'{NOMBRES[letra]} · tiene una justificación: se cambia desde Justificaciones', False, version)
    if fecha > hoy:
        return Celda(letra or '', 'Fecha futura: todavía no se captura', False, version)
    if not con_clase:
        nombre = f'{materia} no tiene clase los {DIAS[fecha.weekday()]}'
        return Celda(letra or '', f'{NOMBRES[letra]} · {nombre}' if letra else nombre, False, version)
    if not puede_editar:
        return Celda(letra or '—', NOMBRES[letra] if letra else 'Sin registro', False, version)
    if fuera_de_la_ventana(fecha, hoy, ventana):
        plazo = f'pasaron más de {ventana} día{"s" if ventana != 1 else ""}: la corrige la administración'
        return Celda(letra or '—', f'{NOMBRES[letra]} · {plazo}' if letra else f'Sin registro · {plazo}', False, version)
    return Celda(letra or '—', NOMBRES[letra] if letra else 'Sin registro: elige el estado', True, version)


def _contexto_editable(asignacion, usuario):
    """Si el docente puede cambiar celdas de esta materia (permiso, materia vigente y ciclo actual)."""
    return (
        usuario is not None and usuario.has_perm('Alumnos.change_asistenciamateria')
        and asignacion.activa and asignacion.ciclo.activo
    )


# ---------------------------------------------------------------------------
# Qué días se ven: por omisión el mes en curso; o el rango que se elija, siempre dentro del ciclo
# ---------------------------------------------------------------------------
def limites_del_periodo(periodo, ciclo):
    """(primer día, último día) del periodo dentro de las fechas del ciclo; None si no se cruzan."""
    desde, hasta = max(periodo.fecha_inicio, ciclo.fecha_inicio), min(periodo.fecha_fin, ciclo.fecha_fin)
    return (desde, hasta) if desde <= hasta else None


def ajustar(fecha, limites):
    """La fecha llevada dentro de los límites."""
    return min(max(fecha, limites[0]), limites[1])


def _fin_de_mes(fecha):
    return (fecha.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def rango_del_mes(limites, hoy):
    """El mes en curso dentro de los límites (si hoy queda fuera, su mes más cercano)."""
    ancla = ajustar(hoy, limites)
    return max(ancla.replace(day=1), limites[0]), min(_fin_de_mes(ancla), limites[1])


def rango_de_la_semana(limites, hoy):
    """La semana en curso (lunes a viernes) dentro de los límites."""
    ancla = ajustar(hoy, limites)
    lunes = ancla - timedelta(days=ancla.weekday())
    return max(lunes, limites[0]), min(lunes + timedelta(days=4), limites[1])


def atajos(limites, hoy, periodo=None):
    """[(nombre, desde, hasta)] de los rangos de un clic: la semana, el mes, el periodo abierto (si hay) y el ciclo."""
    rangos = [
        ('Esta semana', *rango_de_la_semana(limites, hoy)),
        ('Este mes', *rango_del_mes(limites, hoy)),
    ]
    if periodo is not None:
        desde, hasta = max(periodo.fecha_inicio, limites[0]), min(periodo.fecha_fin, limites[1])
        if desde <= hasta:
            rangos.append((f'Periodo «{periodo.nombre}»', desde, hasta))
    rangos.append(('Todo el ciclo', *limites))
    return rangos


def dias_habiles(desde, hasta):
    """Los días de lunes a viernes entre dos fechas (inclusive)."""
    dias = []
    while desde <= hasta:
        if desde.weekday() < 5:
            dias.append(desde)
        desde += timedelta(days=1)
    return dias


def dias_del_periodo(periodo, ciclo):
    """Los días de lunes a viernes del periodo, dentro de las fechas del ciclo."""
    limites = limites_del_periodo(periodo, ciclo)
    return dias_habiles(*limites) if limites else []


# ---------------------------------------------------------------------------
# La matriz
# ---------------------------------------------------------------------------
def matriz(asignacion, usuario=None, hoy=None, desde=None, hasta=None, puede_justificar=False, ventana=None):
    """Lo que se dibuja de la materia entre `desde` y `hasta` (el mes en curso si no se indican; siempre dentro del
    ciclo). Con `puede_justificar` (solo la vista de la administración) las faltas se marcan justificables; con
    `ventana` (la del docente), lo que ya pasó de su plazo no se puede cambiar.

    Devuelve {'periodo', 'limites', 'desde', 'hasta', 'completo', 'columnas', 'meses', 'filas', 'sin_horario',
    'ventana'}; `periodo` es el periodo abierto (de referencia) o None. Cada columna: {'fecha', 'hoy', 'bloqueada',
    'suspension', 'sin_clase', 'fuera_de_plazo', 'inicial', 'dia', 'titulo', 'inicio_mes', 'inicio_semana', 'mes_par'};
    `meses`: [{'nombre', 'columnas', 'par'}] para la fila de meses; cada fila: {'inscripcion', 'alumno', 'celdas'} con
    una `Celda` por columna.
    """
    hoy = hoy or timezone.localdate()
    periodo = periodo_de(asignacion)
    limites = limites_de(asignacion)
    if desde is None or hasta is None:
        desde, hasta = rango_del_mes(limites, hoy)
    desde, hasta = ajustar(desde, limites), ajustar(hasta, limites)
    fechas = dias_habiles(desde, hasta)

    suspensiones = dict(DiaNoLectivo.objects.filter(fecha__range=(desde, hasta), nivel=asignacion.grado.nivel).values_list('fecha', 'motivo'))
    from .semanas import fechas_con_clase
    con_clase = fechas_con_clase(asignacion, fechas)   # su semana A/B y la versión del horario de cada fecha
    inscripciones = list(inscripciones_de(asignacion))
    registros = {
        (registro.inscripcion_id, registro.fecha): registro
        for registro in AsistenciaMateria.objects.filter(materia_grado=asignacion, inscripcion__in=inscripciones, fecha__range=(desde, hasta))
    }
    justificadas = _justificaciones(asignacion, inscripciones, desde, hasta) if inscripciones else {}
    suspendidos = _suspensiones_de(inscripciones, desde, hasta)
    puede_editar = _contexto_editable(asignacion, usuario)

    columnas, meses = [], []
    for fecha in fechas:
        anterior = columnas[-1]['fecha'] if columnas else None
        inicio_mes = anterior is None or anterior.month != fecha.month
        if inicio_mes:
            meses.append({'nombre': f'{MESES_LARGOS[fecha.month - 1]} {fecha.year}', 'columnas': 0, 'par': len(meses) % 2 == 1})
        meses[-1]['columnas'] += 1
        suspension = suspensiones.get(fecha)
        sin_clase = fecha not in con_clase
        fuera_de_plazo = puede_editar and fuera_de_la_ventana(fecha, hoy, ventana)
        columnas.append({
            'fecha': fecha, 'hoy': fecha == hoy, 'suspension': suspension, 'sin_clase': sin_clase, 'fuera_de_plazo': fuera_de_plazo,
            'bloqueada': suspension is not None or fecha > hoy or sin_clase or fuera_de_plazo,
            'inicial': INICIALES[fecha.weekday()], 'dia': DIAS[fecha.weekday()],
            'titulo': f'{DIAS[fecha.weekday()]} {fecha.day} de {MESES_LARGOS[fecha.month - 1]}',
            'inicio_mes': inicio_mes and anterior is not None,
            'inicio_semana': anterior is not None and not inicio_mes and fecha.weekday() < anterior.weekday(),
            'mes_par': meses[-1]['par'],
        })

    filas = []
    for inscripcion in inscripciones:
        celdas = []
        for columna in columnas:
            celda = _celda(
                registros.get((inscripcion.pk, columna['fecha'])), columna['fecha'], hoy, inscripcion,
                columna['suspension'], not columna['sin_clase'], justificadas.get((inscripcion.pk, columna['fecha'])),
                asignacion.materia, puede_editar, puede_justificar, suspendidos.get((inscripcion.pk, columna['fecha'])), ventana,
            )
            celda.hoy, celda.apagada = columna['hoy'], columna['bloqueada']
            celda.inicio_mes, celda.inicio_semana = columna['inicio_mes'], columna['inicio_semana']
            celdas.append(celda)
        filas.append({'inscripcion': inscripcion, 'alumno': inscripcion.alumno, 'celdas': celdas})
    return {
        'periodo': periodo, 'limites': limites, 'desde': desde, 'hasta': hasta, 'completo': (desde, hasta) == limites,
        'columnas': columnas, 'meses': meses, 'filas': filas, 'ventana': ventana if puede_editar else None,
        'sin_horario': not HorarioMateria.historial.filter(materia_grado=asignacion).exists(),
    }


# ---------------------------------------------------------------------------
# El reporte: lo mismo que la matriz, con totales, una tabla por mes y las observaciones
# ---------------------------------------------------------------------------
def resumen_de(celdas):
    """Totales de una fila: presentes, retardos, faltas, justificadas, sin registro y el porcentaje de asistencia
    (presentes y retardos entre los días con registro, como en los reportes de asistencia). Las suspensiones y los días
    bloqueados no cuentan."""
    cuenta = {letra: 0 for letra in 'PRFJ'}
    sin_registro = 0
    for celda in celdas:
        if celda.letra in cuenta:
            cuenta[celda.letra] += 1
        elif celda.letra == '—':
            sin_registro += 1
    registros = sum(cuenta.values())
    return {
        'presentes': cuenta['P'], 'retardos': cuenta['R'], 'faltas': cuenta['F'], 'justificadas': cuenta['J'],
        'sin_registro': sin_registro, 'registros': registros, 'porcentaje': porcentaje(cuenta['P'], cuenta['R'], registros),
    }


def reporte(datos):
    """Lo que lleva el reporte de una matriz (`matriz(...)`): {'filas', 'totales', 'meses', 'observaciones'}.

    `filas` son las de la matriz con su `resumen`; `meses`, una tabla por mes (así cabe en una hoja horizontal);
    `observaciones`, las de las celdas que tienen, en orden de fecha y de lista."""
    filas = [{**fila, 'resumen': resumen_de(fila['celdas'])} for fila in datos['filas']]
    totales = {clave: sum(fila['resumen'][clave] for fila in filas)
               for clave in ('presentes', 'retardos', 'faltas', 'justificadas', 'sin_registro', 'registros')}
    totales['porcentaje'] = porcentaje(totales['presentes'], totales['retardos'], totales['registros'])

    meses, inicio = [], 0
    for mes in datos['meses']:
        fin = inicio + mes['columnas']
        meses.append({
            'nombre': mes['nombre'],
            'columnas': datos['columnas'][inicio:fin],
            'filas': [{'alumno': fila['alumno'], 'celdas': fila['celdas'][inicio:fin]} for fila in filas],
        })
        inicio = fin

    observaciones = [
        {'fecha': columna['fecha'], 'alumno': fila['alumno'], 'estado': NOMBRES.get(fila['celdas'][indice].letra, ''),
         'observacion': fila['celdas'][indice].observaciones}
        for indice, columna in enumerate(datos['columnas'])
        for fila in filas
        if fila['celdas'][indice].observaciones
    ]
    return {'filas': filas, 'totales': totales, 'meses': meses, 'observaciones': observaciones}


# ---------------------------------------------------------------------------
# Un cambio
# ---------------------------------------------------------------------------
def celda_de(asignacion, inscripcion, fecha, usuario=None, hoy=None, puede_justificar=False, ventana=None):
    """La celda de un estudiante en un día con las mismas reglas de la matriz (para validar un cambio)."""
    hoy = hoy or timezone.localdate()
    registro = AsistenciaMateria.objects.filter(materia_grado=asignacion, inscripcion=inscripcion, fecha=fecha).first()
    suspension = DiaNoLectivo.objects.filter(fecha=fecha, nivel=asignacion.grado.nivel).values_list('motivo', flat=True).first()
    from .semanas import fechas_con_clase
    con_clase = fecha in fechas_con_clase(asignacion, [fecha])
    justificacion = _justificaciones(asignacion, [inscripcion], fecha, fecha).get((inscripcion.pk, fecha))
    suspendido = _suspensiones_de([inscripcion], fecha, fecha).get((inscripcion.pk, fecha))
    return _celda(registro, fecha, hoy, inscripcion, suspension, con_clase, justificacion, asignacion.materia,
                  _contexto_editable(asignacion, usuario), puede_justificar, suspendido, ventana)


def limpiar_observacion(texto):
    """Sin espacios de más (como el pase de lista)."""
    return ' '.join((texto or '').split())


def guardar_cambio(asignacion, inscripcion, fecha, estado, version, usuario, hoy=None, observaciones='', puede_justificar=False,
                   ventana=None):
    """Pone ese estado al estudiante en esa materia y día, si se permite. Devuelve la celda ya guardada (con
    `puede_justificar`, como la ve quien administra).

    `version` es la que tenía la celda en pantalla: si el registro cambió desde entonces no se sobrescribe (409).
    Una falta o un retardo exigen `observaciones` (por qué); presente las borra. Con el mismo estado y otra
    observación, solo se actualiza la observación. Con `ventana` (la del docente), lo que ya pasó de su plazo se rechaza.
    """
    hoy = hoy or timezone.localdate()
    if estado not in ESTADOS_DEL_DOCENTE:
        raise CambioRechazado('Elige presente, falta o retardo: la falta justificada se registra en Justificaciones.')
    observaciones = limpiar_observacion(observaciones) if estado in CON_OBSERVACION else ''
    if estado in CON_OBSERVACION:
        que = 'la falta' if estado == 'FALTA' else 'el retardo'
        if len(observaciones) < OBSERVACION_MINIMA:
            raise CambioRechazado(f'Escribe en las observaciones por qué {que}.')
        if len(observaciones) > OBSERVACION_MAXIMA:
            raise CambioRechazado(f'La observación es muy larga: hasta {OBSERVACION_MAXIMA} caracteres.')
    if inscripcion.grupo_id != asignacion.grupo_id or inscripcion.ciclo_id != asignacion.ciclo_id or not inscripcion.activa:
        raise CambioRechazado('Ese estudiante no está inscrito en esta materia.')
    if fecha.weekday() >= 5:
        raise CambioRechazado('Solo se captura de lunes a viernes.')
    if not (asignacion.ciclo.fecha_inicio <= fecha <= asignacion.ciclo.fecha_fin):
        raise CambioRechazado(f'Esa fecha queda fuera del ciclo {asignacion.ciclo}.')
    if not asistencia_editable(fecha) and fecha <= hoy:
        raise CambioRechazado('Esa fecha es de un ciclo que ya no se modifica.')

    with transaction.atomic():
        actual = celda_de(asignacion, inscripcion, fecha, usuario, hoy, ventana=ventana)
        if not actual.editable:
            raise CambioRechazado(f'No se puede cambiar: {actual.nombre[0].lower()}{actual.nombre[1:]}.')
        registro = (
            AsistenciaMateria.objects.select_for_update()
            .filter(materia_grado=asignacion, inscripcion=inscripcion, fecha=fecha).first()
        )
        if version_de(registro) != (version or ''):
            raise CambioRechazado('Alguien más cambió esta asistencia mientras la veías: ya se muestra lo guardado.', 409)
        if registro is None or registro.estado != estado or registro.observaciones != observaciones:
            guardar_pase_de_lista(asignacion, fecha, [(inscripcion, estado, observaciones)], usuario=usuario)
    return celda_de(asignacion, inscripcion, fecha, usuario, hoy, puede_justificar, ventana)


# ---------------------------------------------------------------------------
# Justificar una falta (solo la administración)
# ---------------------------------------------------------------------------
def puede_justificar(usuario, asignacion):
    """Si la persona puede justificar faltas de esta materia: el permiso de justificaciones y el ciclo actual (las
    justificaciones de otros ciclos ya no se modifican). La vista del docente nunca lo ofrece."""
    return bool(usuario and usuario.has_perm('Alumnos.add_justificacion') and asignacion.ciclo.activo)


def justificar_falta(asignacion, inscripcion, fecha, version, motivo, comprobante, usuario, hoy=None):
    """Justifica la falta registrada del estudiante en esa materia y día con la foto de su comprobante. Devuelve la
    celda ya guardada (una J).

    Se guarda como una `Justificacion` de esa sola materia vinculada al registro de la falta (`asistencia`), con el
    comprobante, quién la registró y cuándo (`creado`). El registro sigue siendo una falta. Si la falta cambió mientras
    se llenaba el formulario (otra versión), si ya está justificada o si ya no es falta, no se guarda (409); si el
    comprobante no se puede guardar, tampoco se guarda nada.
    """
    hoy = hoy or timezone.localdate()
    if not asignacion.ciclo.activo:
        raise CambioRechazado('Esa falta es de un ciclo que ya no se modifica.')
    if inscripcion.grupo_id != asignacion.grupo_id or inscripcion.ciclo_id != asignacion.ciclo_id or not inscripcion.activa:
        raise CambioRechazado('Ese estudiante no está inscrito en esta materia.')

    with transaction.atomic():
        registro = (
            AsistenciaMateria.objects.select_for_update()
            .filter(materia_grado=asignacion, inscripcion=inscripcion, fecha=fecha).first()
        )
        if version_de(registro) != (version or ''):
            raise CambioRechazado('Alguien más cambió esta asistencia mientras la veías: ya se muestra lo guardado.', 409)
        actual = celda_de(asignacion, inscripcion, fecha, usuario, hoy, puede_justificar=True)
        if actual.letra == 'J':
            raise CambioRechazado('Esa falta ya está justificada.', 409)
        if not actual.justificable:
            raise CambioRechazado('Solo se justifica una falta registrada.')
        justificacion = Justificacion(
            inscripcion=inscripcion, fecha=fecha, motivo=motivo, asistencia=registro, documento=comprobante,
            registrada_por=usuario,
        )
        try:
            with transaction.atomic():
                justificacion.save()   # sube el comprobante y luego guarda el registro
        except IntegrityError:
            raise CambioRechazado('Esa falta ya está justificada.', 409) from None
        except Exception:   # el almacenamiento de archivos (Cloudinary o el disco) no respondió
            logger.exception('No se pudo guardar el comprobante de la falta %s', registro.pk)
            raise CambioRechazado('No se pudo guardar el comprobante. Inténtalo de nuevo: la falta sigue sin justificar.', 503) from None
        justificacion.materias.set([asignacion])
    return celda_de(asignacion, inscripcion, fecha, usuario, hoy, puede_justificar=True)
