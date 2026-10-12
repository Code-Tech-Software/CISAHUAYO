"""Asistencia para docentes: la matriz de una materia (estudiantes × días del periodo abierto) y los cambios que el
docente puede hacer en ella.

Usa los mismos registros que el pase de lista (`AsistenciaMateria`: por estudiante, por materia del grupo y por día):
lo que el docente cambia aquí se ve en el pase de lista y en los reportes, y al revés. Se guarda con
`guardar_pase_de_lista`, así que marcar presente o retardo también deja constancia de que el estudiante estuvo en el
colegio (como al pasar lista).

Reglas acordadas con el usuario (2026-10-12):
- Solo materias asignadas al docente (`MateriaGrado.profesor`), del ciclo actual; cada grupo es una materia aparte.
- Columnas: los días de lunes a viernes del periodo de evaluación abierto del nivel de la materia; por omisión solo
  el mes en curso, o el rango que se elija (siempre dentro del periodo). Una fila de meses y líneas entre meses y
  semanas ayudan a ubicarse (pedido del 2026-10-12).
- El docente pone Presente, Falta o Retardo; una falta o un retardo lleva su observación (por qué), que se guarda
  en las observaciones del mismo registro (se ven también en el pase de lista). Poner presente la borra. No justifica: la falta justificada (J) se ve y queda bloqueada (se maneja
  desde Justificaciones), igual que cualquier celda que cubra una justificación vigente.
- Suspensión (S, días sin clases) bloqueada para todos; fechas futuras y días en que la materia no tiene clase según
  su horario, bloqueados. Una celda sin registro muestra «—» (no es falta) y el docente puede hacer la primera captura.
- Cada cambio se valida en el servidor y se rechaza si alguien más cambió esa celda mientras tanto (versión).
"""
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .academico import ciclo_actual
from .asistencias import asistencia_editable, guardar_pase_de_lista, porcentaje
from .models import AsistenciaMateria, DiaNoLectivo, HorarioMateria, Inscripcion, Justificacion, MateriaGrado
from .periodos import periodo_abierto

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

    @property
    def clase(self):
        return CLASES.get(self.letra, 'vacia' if self.letra == '—' else 'nada')


# ---------------------------------------------------------------------------
# Qué materias, qué periodo y qué días
# ---------------------------------------------------------------------------
def asignaciones_del_profesor(profesor, ciclo=None):
    """Las materias (una por grupo) que el profesor imparte en el ciclo (el actual si no se indica)."""
    ciclo = ciclo or ciclo_actual()
    if profesor is None or ciclo is None:
        return MateriaGrado.objects.none()
    return (
        MateriaGrado.objects.filter(profesor=profesor, ciclo=ciclo, activa=True, materia__activa=True)
        .select_related('materia', 'ciclo', 'grado', 'grupo__nombre', 'grupo__grado')
        .order_by('materia__nombre', 'grupo__grado__numero', 'grupo__nombre__orden', 'grupo__nombre__nombre')
    )


def periodo_de(asignacion):
    """El periodo de evaluación abierto hoy del nivel de la materia, en su ciclo (o None)."""
    return periodo_abierto(asignacion.grado.nivel, ciclo=asignacion.ciclo)


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
    """{(id de inscripción, fecha)} cubiertos por una justificación vigente de esa materia (o de todas)."""
    return set(
        Justificacion.objects.filter(activa=True, inscripcion__in=inscripciones, fecha__range=(desde, hasta))
        .filter(Q(todas_materias=True) | Q(materias=asignacion))
        .values_list('inscripcion_id', 'fecha')
    )


def _celda(registro, fecha, hoy, inscripcion, suspension, con_clase, justificada, materia, puede_editar):
    """La celda de un estudiante en un día, con lo que se ve, si el docente la puede cambiar (y si no, por qué) y la
    observación del registro (también en el globo de ayuda)."""
    celda = _celda_sin_observacion(registro, fecha, hoy, inscripcion, suspension, con_clase, justificada, materia, puede_editar)
    if registro is not None and registro.observaciones and celda.letra not in ('S', ''):
        celda.observaciones = registro.observaciones
        celda.nombre = f'{celda.nombre}. Observación: {registro.observaciones}'
    return celda


def _celda_sin_observacion(registro, fecha, hoy, inscripcion, suspension, con_clase, justificada, materia, puede_editar):
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
    return Celda(letra or '—', NOMBRES[letra] if letra else 'Sin registro: elige el estado', True, version)


def _contexto_editable(asignacion, usuario):
    """Si el docente puede cambiar celdas de esta materia (permiso, materia vigente y ciclo actual)."""
    return (
        usuario is not None and usuario.has_perm('Alumnos.change_asistenciamateria')
        and asignacion.activa and asignacion.ciclo.activo
    )


# ---------------------------------------------------------------------------
# Qué días se ven: por omisión el mes en curso; o el rango que se elija, siempre dentro del periodo
# ---------------------------------------------------------------------------
def limites_del_periodo(periodo, ciclo):
    """(primer día, último día) que se pueden ver: el periodo dentro de las fechas del ciclo; None si no se cruzan."""
    desde, hasta = max(periodo.fecha_inicio, ciclo.fecha_inicio), min(periodo.fecha_fin, ciclo.fecha_fin)
    return (desde, hasta) if desde <= hasta else None


def ajustar(fecha, limites):
    """La fecha llevada dentro de los límites."""
    return min(max(fecha, limites[0]), limites[1])


def _fin_de_mes(fecha):
    return (fecha.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def rango_del_mes(limites, hoy):
    """El mes en curso dentro del periodo (si hoy queda fuera del periodo, su mes más cercano)."""
    ancla = ajustar(hoy, limites)
    return max(ancla.replace(day=1), limites[0]), min(_fin_de_mes(ancla), limites[1])


def rango_de_la_semana(limites, hoy):
    """La semana en curso (lunes a viernes) dentro del periodo."""
    ancla = ajustar(hoy, limites)
    lunes = ancla - timedelta(days=ancla.weekday())
    return max(lunes, limites[0]), min(lunes + timedelta(days=4), limites[1])


def atajos(limites, hoy):
    """[(nombre, desde, hasta)] de los rangos de un clic."""
    return [
        ('Esta semana', *rango_de_la_semana(limites, hoy)),
        ('Este mes', *rango_del_mes(limites, hoy)),
        ('Todo el periodo', *limites),
    ]


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
def matriz(asignacion, usuario=None, hoy=None, desde=None, hasta=None):
    """Lo que se dibuja de la materia entre `desde` y `hasta` (el mes en curso si no se indican; siempre dentro del
    periodo abierto).

    Devuelve {'periodo', 'limites', 'desde', 'hasta', 'completo', 'columnas', 'meses', 'filas', 'sin_horario'};
    `periodo` es None si no hay uno abierto. Cada columna: {'fecha', 'hoy', 'bloqueada', 'suspension', 'sin_clase',
    'inicial', 'dia', 'titulo', 'inicio_mes', 'inicio_semana', 'mes_par'}; `meses`: [{'nombre', 'columnas', 'par'}]
    para la fila de meses; cada fila: {'inscripcion', 'alumno', 'celdas'} con una `Celda` por columna.
    """
    hoy = hoy or timezone.localdate()
    periodo = periodo_de(asignacion)
    vacia = {'periodo': periodo, 'limites': None, 'desde': None, 'hasta': None, 'completo': True,
             'columnas': [], 'meses': [], 'filas': [], 'sin_horario': False}
    if periodo is None:
        return vacia
    limites = limites_del_periodo(periodo, asignacion.ciclo)
    if limites is None:
        return vacia
    if desde is None or hasta is None:
        desde, hasta = rango_del_mes(limites, hoy)
    desde, hasta = ajustar(desde, limites), ajustar(hasta, limites)
    fechas = dias_habiles(desde, hasta)

    suspensiones = dict(DiaNoLectivo.objects.filter(fecha__range=(desde, hasta)).values_list('fecha', 'motivo'))
    dias_con_clase = set(HorarioMateria.objects.filter(materia_grado=asignacion).values_list('dia_semana', flat=True))
    inscripciones = list(inscripciones_de(asignacion))
    registros = {
        (registro.inscripcion_id, registro.fecha): registro
        for registro in AsistenciaMateria.objects.filter(materia_grado=asignacion, inscripcion__in=inscripciones, fecha__range=(desde, hasta))
    }
    justificadas = _justificaciones(asignacion, inscripciones, desde, hasta) if inscripciones else set()
    puede_editar = _contexto_editable(asignacion, usuario)

    columnas, meses = [], []
    for fecha in fechas:
        anterior = columnas[-1]['fecha'] if columnas else None
        inicio_mes = anterior is None or anterior.month != fecha.month
        if inicio_mes:
            meses.append({'nombre': f'{MESES_LARGOS[fecha.month - 1]} {fecha.year}', 'columnas': 0, 'par': len(meses) % 2 == 1})
        meses[-1]['columnas'] += 1
        suspension = suspensiones.get(fecha)
        sin_clase = fecha.weekday() not in dias_con_clase
        columnas.append({
            'fecha': fecha, 'hoy': fecha == hoy, 'suspension': suspension, 'sin_clase': sin_clase,
            'bloqueada': suspension is not None or fecha > hoy or sin_clase,
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
                columna['suspension'], not columna['sin_clase'], (inscripcion.pk, columna['fecha']) in justificadas,
                asignacion.materia, puede_editar,
            )
            celda.hoy, celda.apagada = columna['hoy'], columna['bloqueada']
            celda.inicio_mes, celda.inicio_semana = columna['inicio_mes'], columna['inicio_semana']
            celdas.append(celda)
        filas.append({'inscripcion': inscripcion, 'alumno': inscripcion.alumno, 'celdas': celdas})
    return {
        'periodo': periodo, 'limites': limites, 'desde': desde, 'hasta': hasta, 'completo': (desde, hasta) == limites,
        'columnas': columnas, 'meses': meses, 'filas': filas, 'sin_horario': not dias_con_clase,
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
def celda_de(asignacion, inscripcion, fecha, usuario=None, hoy=None):
    """La celda de un estudiante en un día con las mismas reglas de la matriz (para validar un cambio)."""
    hoy = hoy or timezone.localdate()
    registro = AsistenciaMateria.objects.filter(materia_grado=asignacion, inscripcion=inscripcion, fecha=fecha).first()
    suspension = DiaNoLectivo.objects.filter(fecha=fecha).values_list('motivo', flat=True).first()
    con_clase = HorarioMateria.objects.filter(materia_grado=asignacion, dia_semana=fecha.weekday()).exists()
    justificada = bool(_justificaciones(asignacion, [inscripcion], fecha, fecha))
    return _celda(registro, fecha, hoy, inscripcion, suspension, con_clase, justificada, asignacion.materia,
                  _contexto_editable(asignacion, usuario))


def limpiar_observacion(texto):
    """Sin espacios de más (como el pase de lista)."""
    return ' '.join((texto or '').split())


def guardar_cambio(asignacion, inscripcion, fecha, estado, version, usuario, hoy=None, observaciones=''):
    """Pone ese estado al estudiante en esa materia y día, si se permite. Devuelve la celda ya guardada.

    `version` es la que tenía la celda en pantalla: si el registro cambió desde entonces no se sobrescribe (409).
    Una falta o un retardo exigen `observaciones` (por qué); presente las borra. Con el mismo estado y otra
    observación, solo se actualiza la observación.
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
    periodo = periodo_de(asignacion)
    if periodo is None or not (periodo.fecha_inicio <= fecha <= periodo.fecha_fin):
        raise CambioRechazado('Esa fecha no está en el periodo de evaluación abierto.')
    if not asistencia_editable(fecha) and fecha <= hoy:
        raise CambioRechazado('Esa fecha es de un ciclo que ya no se modifica.')

    with transaction.atomic():
        actual = celda_de(asignacion, inscripcion, fecha, usuario, hoy)
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
    return celda_de(asignacion, inscripcion, fecha, usuario, hoy)
