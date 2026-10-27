"""Reglas del control de asistencia: entrada del alumno, asistencia por materia, cierre del día y justificaciones.

Cómo funciona (cada grupo tiene su horario):
- Al llegar, el alumno registra su entrada con su credencial (UID) o su número de referencia. Eso crea su asistencia
  general del día y, de una vez, la de cada materia que su grupo tiene ese día, para que el profesor ya la encuentre
  al empezar la clase y solo corrija lo que haga falta.
- Quien llega cuando una clase ya empezó o terminó queda con retardo o falta en esa materia.
- Quien entra después de la hora límite de su nivel (o, sin límite, de la hora de entrada más la tolerancia) queda con
  retardo en la entrada general, y su primera clase del día le cuenta como falta (pedido del 2026-10-14).
- Un estudiante con una suspensión autorizada no recibe faltas al cerrar el día: está suspendido, no faltó. Tampoco
  puede registrar su entrada esos días (la pantalla lo rechaza).
- Al cerrar el día se generan las faltas de quien nunca registró entrada.
- Una falta está «justificada» cuando hay una justificación vigente que la cubre (se calcula al consultar: no se
  guarda en la asistencia, así que anular o cambiar una justificación se refleja sola).
- No hay clases en fin de semana (pedido del 2026-10-27), aunque algún horario tenga bloques en sábado o domingo.
- Cada captura o corrección de una persona queda en la bitácora (`CambioAsistencia`) con lo que había antes.
- Al cerrar un día se avisa en el portal a los tutores de las faltas sin justificar y de los retardos de sus hijos.
"""
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import time, timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, connections, transaction
from django.db.models import Count, Exists, Min, OuterRef, Q
from django.utils import timezone
from django.utils.formats import date_format

from .models import (
    Alumno,
    AsistenciaGeneral,
    AsistenciaMateria,
    CambioAsistencia,
    CicloEscolar,
    CierreDia,
    ConfiguracionAsistencia,
    DiaNoLectivo,
    Grado,
    Inscripcion,
    Justificacion,
    LimiteEntradaNivel,
    NotificacionAsistencia,
    TutorAlumno,
    UmbralAsistenciaNivel,
)

logger = logging.getLogger(__name__)

ESTADOS = ('PRESENTE', 'RETARDO', 'FALTA')
ETIQUETAS = dict(AsistenciaGeneral.ESTADO_CHOICES)
# Máximo de días que se revisan hacia atrás al cerrar días pendientes (evita un cierre enorme por error)
LIMITE_DIAS_PENDIENTES = 45
# Al cerrar un día de hace más de estos días ya no se avisa a los tutores (sería un aviso viejo)
DIAS_PARA_AVISAR = 3
NIVELES = tuple(clave for clave, _ in Grado.NIVEL_CHOICES)
NOMBRES_DE_NIVEL = dict(Grado.NIVEL_CHOICES)


class EntradaRechazada(Exception):
    """La entrada no se puede registrar; `codigo` identifica el motivo y `mensaje` es para mostrar al alumno."""

    def __init__(self, codigo, mensaje):
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje


@dataclass(frozen=True)
class Clase:
    """Una materia de un grado en un día: de la hora en que empieza su primer bloque a la que termina el último.

    `bloques` son los (inicio, fin) de cada bloque del día, solo para mostrarlos; las reglas usan `inicio` y `fin`.
    """

    asignacion: object
    inicio: time
    fin: time
    bloques: tuple = ()

    @property
    def pk(self):
        return self.asignacion.pk


@dataclass
class ResultadoEntrada:
    asistencia: object
    creada: bool
    materias: int = 0


# ---------------------------------------------------------------------------
# Calendario
# ---------------------------------------------------------------------------
def ciclo_de_fecha(fecha):
    """El ciclo cuyas fechas incluyen el día (si por error hubiera dos, el actual)."""
    return (
        CicloEscolar.objects.filter(fecha_inicio__lte=fecha, fecha_fin__gte=fecha)
        .order_by('-activo', '-fecha_inicio').first()
    )


def texto_de_niveles(niveles):
    """«todos los niveles» o sus nombres en orden escolar («preescolar y primaria»)."""
    niveles = [nivel for nivel in NIVELES if nivel in set(niveles)]
    if len(niveles) == len(NIVELES):
        return 'todos los niveles'
    nombres = [NOMBRES_DE_NIVEL[nivel].lower() for nivel in niveles]
    return ' y '.join(nombres) if len(nombres) < 3 else f'{", ".join(nombres[:-1])} y {nombres[-1]}'


def niveles_sin_clases(fecha):
    """{nivel: motivo} de los niveles que tienen ese día registrado como día sin clases."""
    return dict(DiaNoLectivo.objects.filter(fecha=fecha).values_list('nivel', 'motivo'))


def _niveles_del_colegio():
    """Los niveles con grados activos (sin ninguno, los cuatro): un día es sin clases para todo el colegio cuando lo es
    para todos ellos."""
    return set(Grado.objects.filter(activo=True).values_list('nivel', flat=True)) or set(NIVELES)


def _de_todo_el_colegio(niveles):
    return bool(niveles) and _niveles_del_colegio() <= set(niveles)


def fechas_sin_clases(desde, hasta, nivel=None):
    """Las fechas entre esas dos (inclusive) sin clases para ese nivel o, sin nivel, para todo el colegio."""
    dias = DiaNoLectivo.objects.filter(fecha__range=(desde, hasta))
    if nivel:
        return set(dias.filter(nivel=nivel).values_list('fecha', flat=True))
    por_fecha = defaultdict(set)
    for fecha, nivel_del_dia in dias.values_list('fecha', 'nivel'):
        por_fecha[fecha].add(nivel_del_dia)
    return {fecha for fecha, niveles in por_fecha.items() if _de_todo_el_colegio(niveles)}


def aviso_de_niveles_sin_clases(fecha):
    """Si ese día solo algunos niveles no tienen clases, el aviso para las pantallas del día (sus estudiantes no se
    esperan ni se cuentan); si no, None."""
    sin_clases = niveles_sin_clases(fecha)
    if not sin_clases or _de_todo_el_colegio(sin_clases):
        return None
    por_motivo = defaultdict(list)
    for nivel in NIVELES:
        if nivel in sin_clases:
            por_motivo[sin_clases[nivel]].append(nivel)
    partes = '; '.join(f'{texto_de_niveles(niveles)} ({motivo})' for motivo, niveles in por_motivo.items())
    return f'Sin clases en {partes}: sus estudiantes no registran entrada ni se les generan faltas.'


@dataclass
class DiaSinClases:
    """Un día sin clases tal como se registró: una fecha y un motivo con sus niveles."""
    pk: int             # uno de sus registros (para quitarlo)
    fecha: object
    motivo: str
    niveles: list

    @property
    def todos(self):
        return set(NIVELES) <= set(self.niveles)

    @property
    def nombres(self):
        return [NOMBRES_DE_NIVEL[nivel] for nivel in NIVELES if nivel in self.niveles]


def dias_sin_clases_registrados(limite=120, ciclo=None):
    """Los días sin clases (los de las fechas del ciclo, si se indica), del más reciente al más antiguo, uno por fecha
    y motivo con sus niveles."""
    dias = {}
    registros = DiaNoLectivo.objects.all()
    if ciclo is not None:
        registros = registros.filter(fecha__range=(ciclo.fecha_inicio, ciclo.fecha_fin))
    for registro in registros.order_by('-fecha', 'motivo', 'pk')[:limite * len(NIVELES)]:
        dia = dias.setdefault((registro.fecha, registro.motivo), DiaSinClases(registro.pk, registro.fecha, registro.motivo, []))
        dia.niveles.append(registro.nivel)
    return list(dias.values())[:limite]


def motivo_sin_clases(fecha, ciclo=None, exigir_actual=False, nivel=None):
    """Por qué ese día no se registra asistencia (texto), o None si es día de clases.

    Con `nivel`, para los estudiantes de ese nivel; sin él, para todo el colegio. Un día sin clases solo de algunos
    niveles sigue siendo día de clases: sus estudiantes no se esperan (`inscripciones_del_dia`).
    `exigir_actual` pide además que el ciclo del día sea el ciclo actual (se usa para registrar entradas y para
    capturar: los ciclos cerrados y los próximos no se modifican).
    """
    ciclo = ciclo or ciclo_de_fecha(fecha)
    if ciclo is None:
        return 'Ese día queda fuera de las fechas de cualquier ciclo escolar.'
    if exigir_actual and not ciclo.activo:
        return f'El ciclo {ciclo} no es el ciclo actual.'
    sin_clases = niveles_sin_clases(fecha)
    if nivel:
        motivo = sin_clases.get(nivel)
    else:
        motivo = ', '.join(dict.fromkeys(sin_clases[n] for n in NIVELES if n in sin_clases)) if _de_todo_el_colegio(sin_clases) else None
    if motivo:
        return f'Día sin clases: {motivo}.'
    if fecha.weekday() >= 5:
        return 'No hay clases en fin de semana.'
    return None


def dias_de_clases(desde, hasta, ciclo, nivel=None):
    """Los días de clases entre dos fechas (inclusive), dentro del ciclo: de lunes a viernes y sin días sin clases (de
    ese nivel o, sin nivel, de todo el colegio)."""
    desde, hasta = max(desde, ciclo.fecha_inicio), min(hasta, ciclo.fecha_fin)
    if desde > hasta:
        return []
    sin_clases = fechas_sin_clases(desde, hasta, nivel)
    fechas = []
    for indice in range((hasta - desde).days + 1):
        fecha = desde + timedelta(days=indice)
        if fecha not in sin_clases and fecha.weekday() < 5:
            fechas.append(fecha)
    return fechas


def quitar_faltas_del_cierre(dias):
    """Al registrar días sin clases que ya se habían cerrado (por ejemplo, una suspensión por emergencia): quita las
    faltas que el cierre generó esos días a los estudiantes de esos niveles, generales y por materia, y los avisos de
    falta a sus tutores. `dias` es [(fecha, nivel), …].

    Solo se quitan las faltas que generó el cierre: lo que registró la pantalla de entrada o una persona se queda (también
    una falta del cierre que alguien ya corrigió a presente), igual que una falta por materia que ya tiene su
    justificación con comprobante. Devuelve cuántas faltas generales se quitaron.
    """
    hoy = timezone.localdate()
    por_nivel = defaultdict(set)
    for fecha, nivel in dias:
        if fecha <= hoy:
            por_nivel[nivel].add(fecha)
    quitadas = 0
    with transaction.atomic():
        for nivel, fechas in por_nivel.items():
            del_nivel = {'fecha__in': fechas, 'inscripcion__grado__nivel': nivel}
            faltas_del_cierre = {**del_nivel, 'origen': 'CIERRE', 'estado': 'FALTA'}
            quitadas += AsistenciaGeneral.objects.filter(**faltas_del_cierre).delete()[0]
            AsistenciaMateria.objects.filter(**faltas_del_cierre).filter(justificaciones__isnull=True).delete()
            NotificacionAsistencia.objects.filter(tipo=NotificacionAsistencia.FALTA, **del_nivel).delete()
    return quitadas


def reabrir_dias(fechas):
    """Al quitar un día sin clases: sus fechas ya pasadas vuelven a quedar pendientes de cierre (el siguiente cierre
    genera las faltas de quien no entró). Devuelve las fechas que se reabrieron."""
    pasadas = [fecha for fecha in fechas if fecha < timezone.localdate()]
    reabiertas = list(CierreDia.objects.filter(fecha__in=pasadas).values_list('fecha', flat=True))
    CierreDia.objects.filter(fecha__in=reabiertas).delete()
    return sorted(reabiertas)


def asistencia_editable(fecha):
    """Se captura y corrige asistencia en el ciclo actual, de los días que ya empezaron (nunca del futuro)."""
    if fecha > timezone.localdate():
        return False
    ciclo = ciclo_de_fecha(fecha)
    return ciclo is not None and ciclo.activo


# ---------------------------------------------------------------------------
# Quiénes asisten y a qué clases
# ---------------------------------------------------------------------------
def inscripciones_del_dia(fecha, ciclo=None, grado=None, grupo=None):
    """Inscripciones vigentes que deben asistir ese día: alumnos activos, ya inscritos, en el ciclo del día, de los
    niveles que tienen clases ese día (de un grado o de un grupo, si se indica)."""
    ciclo = ciclo or ciclo_de_fecha(fecha)
    if ciclo is None:
        return Inscripcion.objects.none()
    inscripciones = Inscripcion.objects.filter(
        ciclo=ciclo, activa=True, alumno__estatus='ACTIVO', fecha_inscripcion__lte=fecha,
    )
    sin_clases = niveles_sin_clases(fecha)
    if sin_clases:
        inscripciones = inscripciones.exclude(grado__nivel__in=list(sin_clases))
    if grado is not None:
        inscripciones = inscripciones.filter(grado=grado)
    if grupo is not None:
        inscripciones = inscripciones.filter(grupo=grupo)
    return inscripciones


def _bloques_de_fecha(fecha, ciclo, **filtros):
    """Los bloques de ese día: los de su semana (A o B) en los niveles alternados y la versión del horario de entonces
    (Alumnos/semanas.py, el criterio de todo el sistema)."""
    from .semanas import bloques_de_fecha
    return bloques_de_fecha(fecha, ciclo, **filtros)


def _bloques_del_dia(ciclo, fecha, **filtros):
    return (
        _bloques_de_fecha(fecha, ciclo, materia_grado__materia__activa=True, **filtros)
        .select_related('materia_grado__materia', 'materia_grado__profesor', 'materia_grado__grado', 'materia_grado__grupo__nombre', 'materia_grado__grupo__grado')
        .order_by('hora_inicio')
    )


def clases_por_grupo(ciclo, fecha, **filtros):
    """{id de grupo: [Clase, …]} de las materias que se imparten ese día, en orden de hora (cada grupo tiene su
    horario)."""
    horas = {}
    for bloque in _bloques_del_dia(ciclo, fecha, **filtros):
        horas.setdefault(bloque.materia_grado.pk, (bloque.materia_grado, set()))[1].add((bloque.hora_inicio, bloque.hora_fin))
    clases = defaultdict(list)
    for asignacion, bloques in horas.values():
        bloques = tuple(sorted(bloques))
        clases[asignacion.grupo_id].append(Clase(asignacion, bloques[0][0], max(fin for _, fin in bloques), bloques))
    for lista in clases.values():
        lista.sort(key=lambda clase: (clase.inicio, clase.asignacion.materia.nombre))
    return clases


def clases_del_dia(grupo, ciclo, fecha):
    """Las clases del grupo ese día, en orden de hora."""
    return clases_por_grupo(ciclo, fecha, materia_grado__grupo=grupo).get(grupo.pk, [])


# ---------------------------------------------------------------------------
# Estados según la hora de llegada
# ---------------------------------------------------------------------------
def _minuto(hora):
    """La hora sin segundos: se compara como se muestra (08:10:40 cuenta como 08:10)."""
    return hora.replace(second=0, microsecond=0)


def _mas_minutos(hora, minutos):
    total = min(hora.hour * 60 + hora.minute + minutos, 23 * 60 + 59)
    return time(total // 60, total % 60)


def limite_de_entrada(nivel, configuracion):
    """La hora límite de entrada del nivel; sin una propia, la hora de entrada general más la tolerancia."""
    propia = LimiteEntradaNivel.objects.filter(nivel=nivel).values_list('hora_limite', flat=True).first() if nivel else None
    return propia or _mas_minutos(configuracion.hora_entrada, configuracion.tolerancia_minutos)


def estado_de_entrada(hora, configuracion, nivel=None):
    """PRESENTE si llegó a tiempo (a más tardar en la hora límite de su nivel); RETARDO si después."""
    return 'PRESENTE' if _minuto(hora) <= limite_de_entrada(nivel, configuracion) else 'RETARDO'


def estado_en_clase(hora, clase, tolerancia):
    """Cómo queda en una materia quien llega a esa hora: FALTA si la clase ya terminó, RETARDO si ya empezó."""
    hora = _minuto(hora)
    if hora >= clase.fin:
        return 'FALTA'
    return 'RETARDO' if hora > _mas_minutos(clase.inicio, tolerancia) else 'PRESENTE'


def _nota_de_llegada(estado, hora):
    if estado == 'FALTA':
        return f'Llegó a las {hora:%H:%M}, cuando la clase ya había terminado.'
    if estado == 'RETARDO':
        return f'Llegó a las {hora:%H:%M}, con la clase iniciada.'
    return ''


def _materias_por_crear(inscripcion, fecha, hora, tolerancia, clases, existentes, origen, usuario, estado_fijo=None, nota='',
                        retardo_de_entrada=False):
    """Objetos AsistenciaMateria (sin guardar) de las materias que `existentes` todavía no tiene.

    `estado_fijo` (por ejemplo FALTA) manda sobre el que saldría de la hora de llegada. Con `retardo_de_entrada` (llegó
    después de la hora límite de su nivel), la primera clase del día queda con falta.
    """
    primera = min(clases, key=lambda clase: clase.inicio) if clases and retardo_de_entrada and not estado_fijo else None
    nuevas = []
    for clase in clases:
        if clase.pk in existentes:
            continue
        if clase is primera:
            estado = 'FALTA'
            observacion = f'Llegó a las {hora:%H:%M}, después de la hora límite de entrada: la primera hora cuenta como falta.' if hora else (
                'Llegó después de la hora límite de entrada: la primera hora cuenta como falta.')
        else:
            estado = estado_fijo or (estado_en_clase(hora, clase, tolerancia) if hora else 'PRESENTE')
            observacion = nota or (_nota_de_llegada(estado, hora) if hora else '')
        nuevas.append(AsistenciaMateria(
            inscripcion=inscripcion, materia_grado=clase.asignacion, fecha=fecha, estado=estado, origen=origen,
            registrado_por=usuario, observaciones=observacion,
        ))
    return nuevas


def crear_asistencias_de_materias(inscripcion, fecha, hora, tolerancia, clases=None, origen='ENTRADA', usuario=None, retardo_de_entrada=False):
    """Crea la asistencia de cada materia del día que todavía no la tiene, según la hora de llegada.

    Con `hora=None` (no se sabe a qué hora llegó) todas quedan presentes, salvo la primera si llegó con retardo a la
    entrada (`retardo_de_entrada`). Nunca toca las que ya existen. Devuelve cuántas creó.
    """
    clases = clases if clases is not None else clases_del_dia(inscripcion.grupo, inscripcion.ciclo, fecha)
    existentes = set(
        AsistenciaMateria.objects.filter(inscripcion=inscripcion, fecha=fecha).values_list('materia_grado_id', flat=True)
    )
    nuevas = _materias_por_crear(inscripcion, fecha, hora, tolerancia, clases, existentes, origen, usuario, retardo_de_entrada=retardo_de_entrada)
    AsistenciaMateria.objects.bulk_create(nuevas, ignore_conflicts=True)
    return len(nuevas)


# ---------------------------------------------------------------------------
# Entrada del alumno (pantalla de la entrada)
# ---------------------------------------------------------------------------
_MENSAJES_ESTATUS = {
    'SUSPENDIDO': 'Tu registro está suspendido. Acude a dirección.',
    'BAJA': 'Tu registro no está activo. Acude a control escolar.',
    'EGRESADO': 'Tu registro no está activo. Acude a control escolar.',
}


def buscar_alumno(codigo, modo='uid', con_referencia=True):
    """El alumno de un código escaneado (UID de la credencial) o escrito (número de referencia).

    Se busca primero según `modo`, pero si no aparece se prueba el otro: así un UID escaneado con el cursor en el campo
    de la referencia (o al revés) también funciona. Sin `con_referencia` (la entrada con número de referencia se apagó
    en los ajustes) solo vale la credencial. Devuelve (alumno, origen) con origen UID o REFERENCIA.
    """
    codigo = ''.join(caracter for caracter in (codigo or '') if caracter.isprintable()).strip()
    if not codigo:
        raise EntradaRechazada('VACIO', 'Acerca tu credencial o escribe tu número de referencia.' if con_referencia else 'Acerca tu credencial al lector.')
    campos = (('UID', 'uid'), ('REFERENCIA', 'referencia'))
    if not con_referencia:
        campos = campos[:1]
    for origen, campo in (campos if modo != 'referencia' else campos[::-1]):
        alumno = Alumno.objects.filter(**{f'{campo}__iexact': codigo}).first()
        if alumno:
            return alumno, origen
    if not con_referencia:
        raise EntradaRechazada('NO_ENCONTRADO', 'No encontramos esa credencial. Intenta de nuevo o acude a control escolar: la entrada con número de referencia no está disponible.')
    raise EntradaRechazada('NO_ENCONTRADO', 'No encontramos esa credencial o ese número de referencia. Intenta de nuevo o acude a control escolar.')


def registrar_entrada(alumno, origen, usuario=None, momento=None):
    """Registra la entrada del alumno y crea la asistencia de sus materias del día.

    Si ya había registrado entrada ese día no cambia nada (`creada=False`). Lanza `EntradaRechazada` si no procede:
    alumno sin estatus activo, día sin clases o sin inscripción en el ciclo.
    """
    momento = momento or timezone.localtime()
    fecha, hora = momento.date(), _minuto(momento.time())

    if alumno.estatus != 'ACTIVO':
        raise EntradaRechazada(alumno.estatus, _MENSAJES_ESTATUS.get(alumno.estatus, 'Tu registro no está activo.'))
    suspension = suspension_vigente(alumno, fecha)
    if suspension is not None:
        raise EntradaRechazada('SUSPENSION', f'Tienes una suspensión hasta el {suspension.fecha_fin:%d/%m/%Y}: hoy no puedes ingresar. Acude a prefectura.')
    motivo = motivo_sin_clases(fecha, exigir_actual=True)
    if motivo:
        raise EntradaRechazada('SIN_CLASES', motivo)
    ciclo = ciclo_de_fecha(fecha)
    inscripcion = Inscripcion.objects.filter(alumno=alumno, ciclo=ciclo, activa=True).select_related('grado', 'ciclo').first()
    if inscripcion is None:
        raise EntradaRechazada('SIN_INSCRIPCION', 'No tienes una inscripción vigente en el ciclo actual. Acude a control escolar.')
    sin_clases = DiaNoLectivo.objects.filter(fecha=fecha, nivel=inscripcion.grado.nivel).values_list('motivo', flat=True).first()
    if sin_clases:
        raise EntradaRechazada('SIN_CLASES', f'Hoy no hay clases en {inscripcion.grado.get_nivel_display().lower()}: {sin_clases}.')

    configuracion = ConfiguracionAsistencia.cargar()
    try:
        with transaction.atomic():
            existente = AsistenciaGeneral.objects.filter(inscripcion=inscripcion, fecha=fecha).first()
            if existente:
                return ResultadoEntrada(existente, creada=False)
            estado = estado_de_entrada(hora, configuracion, inscripcion.grado.nivel)
            asistencia = AsistenciaGeneral.objects.create(
                inscripcion=inscripcion, fecha=fecha, estado=estado, hora_entrada=hora, origen=origen, registrado_por=usuario,
            )
            materias = crear_asistencias_de_materias(
                inscripcion, fecha, hora, configuracion.tolerancia_minutos, usuario=usuario, retardo_de_entrada=estado == 'RETARDO',
            )
    except IntegrityError:  # dos lecturas casi simultáneas de la misma credencial: ganó la otra
        return ResultadoEntrada(AsistenciaGeneral.objects.get(inscripcion=inscripcion, fecha=fecha), creada=False)
    return ResultadoEntrada(asistencia, creada=True, materias=materias)


# ---------------------------------------------------------------------------
# Capturas de quien administra y de los profesores
# ---------------------------------------------------------------------------
def _materias_del_dia(inscripcion, fecha):
    """{id de materia: (estado, observaciones)} de la asistencia por materia del estudiante ese día."""
    return {
        materia: (estado, observaciones)
        for materia, estado, observaciones in AsistenciaMateria.objects.filter(inscripcion=inscripcion, fecha=fecha)
        .values_list('materia_grado_id', 'estado', 'observaciones')
    }


def _cambios_de_materias(inscripcion, fecha, antes, despues, via, usuario):
    """Las anotaciones de la bitácora de las materias que cambiaron (o que se registraron) entre dos fotos del día."""
    return [
        CambioAsistencia(
            inscripcion=inscripcion, fecha=fecha, materia_grado_id=materia, estado_anterior=antes.get(materia, ('', ''))[0],
            estado_nuevo=estado, observacion_anterior=antes.get(materia, ('', ''))[1], observacion_nueva=observaciones,
            via=via[:120], usuario=usuario,
        )
        for materia, (estado, observaciones) in despues.items()
        if antes.get(materia) != (estado, observaciones)
    ]


def fijar_asistencia_general(inscripcion, fecha, estado, hora=None, observaciones='', usuario=None, propagar=True,
                             via='Asistencia del día'):
    """Crea o corrige la asistencia general de un alumno ese día (captura manual de quien administra).

    Con `propagar`, las materias del día siguen a la general: una falta general es falta en todas; una presencia
    crea las materias que faltan y recalcula las que genera el sistema (las que el profesor ya capturó no se tocan).
    Sin hora, todas sus materias quedan presentes (salvo la primera si quedó con retardo). Lo que cambió queda en la
    bitácora con `via` (desde dónde). En `asistencia.pase_sobrescrito` quedan las materias en que el profesor lo había
    marcado presente o con retardo y que la falta general cambió a falta.
    """
    configuracion = ConfiguracionAsistencia.cargar()
    hora = _minuto(hora) if hora else None
    with transaction.atomic():
        asistencia = AsistenciaGeneral.objects.filter(inscripcion=inscripcion, fecha=fecha).first()
        antes = (asistencia.estado, asistencia.hora_entrada, asistencia.observaciones) if asistencia else ('', None, '')
        if asistencia is None:
            asistencia = AsistenciaGeneral(inscripcion=inscripcion, fecha=fecha, origen='MANUAL')
        asistencia.estado = estado
        asistencia.hora_entrada = None if estado == 'FALTA' else hora
        asistencia.observaciones = observaciones
        asistencia.registrado_por = usuario
        asistencia.save()
        cambios = []
        if antes != (asistencia.estado, asistencia.hora_entrada, asistencia.observaciones):
            cambios.append(CambioAsistencia(
                inscripcion=inscripcion, fecha=fecha, estado_anterior=antes[0], estado_nuevo=estado, hora_anterior=antes[1],
                hora_nueva=asistencia.hora_entrada, observacion_anterior=antes[2], observacion_nueva=observaciones, via=via[:120],
                usuario=usuario,
            ))
        asistencia.pase_sobrescrito = []
        if propagar:
            previas = _materias_del_dia(inscripcion, fecha)
            asistencia.pase_sobrescrito = _propagar_a_materias(asistencia, configuracion, usuario)
            cambios += _cambios_de_materias(inscripcion, fecha, previas, _materias_del_dia(inscripcion, fecha), via, usuario)
        CambioAsistencia.objects.bulk_create(cambios)
    return asistencia


def pase_que_contradice_una_falta(inscripciones, fecha):
    """{id de inscripción: [materias]} de las materias en que el profesor marcó presente o retardo ese día: si se pone
    falta general, esas materias también quedan con falta (se avisa antes de guardar)."""
    resultado = defaultdict(list)
    for registro in (AsistenciaMateria.objects.filter(inscripcion__in=inscripciones, fecha=fecha, origen='PASE', estado__in=('PRESENTE', 'RETARDO'))
                     .select_related('materia_grado__materia').order_by('materia_grado__materia__nombre')):
        resultado[registro.inscripcion_id].append(str(registro.materia_grado.materia))
    return dict(resultado)


def _propagar_a_materias(asistencia, configuracion, usuario):
    """Las materias del día siguen a la general. Devuelve las materias del pase de lista del profesor (presente o
    retardo) que una falta general cambió a falta."""
    inscripcion, fecha = asistencia.inscripcion, asistencia.fecha
    clases = clases_del_dia(inscripcion.grupo, inscripcion.ciclo, fecha)
    registros = AsistenciaMateria.objects.filter(inscripcion=inscripcion, fecha=fecha)
    ahora = timezone.now()

    if asistencia.estado == 'FALTA':
        sobrescritas = pase_que_contradice_una_falta([inscripcion.pk], fecha).get(inscripcion.pk, [])
        registros.update(estado='FALTA', origen='MANUAL', registrado_por=usuario, observaciones='No asistió al colegio.', modificado=ahora)
        nuevas = [
            AsistenciaMateria(
                inscripcion=inscripcion, materia_grado=clase.asignacion, fecha=fecha, estado='FALTA', origen='MANUAL',
                registrado_por=usuario, observaciones='No asistió al colegio.',
            )
            for clase in clases
        ]
        AsistenciaMateria.objects.bulk_create(nuevas, ignore_conflicts=True)
        return sobrescritas

    # Presente o con retardo: lo que generó el sistema se recalcula con la hora; el pase de lista del profesor se respeta
    registros.exclude(origen='PASE').delete()
    crear_asistencias_de_materias(
        inscripcion, fecha, asistencia.hora_entrada, configuracion.tolerancia_minutos, clases=clases, origen='MANUAL', usuario=usuario,
        retardo_de_entrada=asistencia.estado == 'RETARDO',
    )
    return []


def guardar_pase_de_lista(asignacion, fecha, filas, usuario=None, via=None):
    """Guarda el pase de lista de una materia: `filas` es [(inscripcion, estado, observaciones), …].

    Quien aparece presente o con retardo en una clase estuvo en el colegio: si no tenía asistencia general ese día
    (o tenía falta) se le registra presente. Lo que cambió queda en la bitácora. Devuelve cuántos alumnos se guardaron.
    """
    if not filas:
        return 0
    via = (via or f'Pase de lista de {asignacion.materia}')[:120]
    ids = [inscripcion.pk for inscripcion, _, _ in filas]
    ahora = timezone.now()
    with transaction.atomic():
        previas = {
            registro.inscripcion_id: registro
            for registro in AsistenciaMateria.objects.filter(materia_grado=asignacion, fecha=fecha, inscripcion__in=ids)
        }
        generales = {
            registro.inscripcion_id: registro
            for registro in AsistenciaGeneral.objects.filter(fecha=fecha, inscripcion__in=ids)
        }
        nuevas, cambiadas, generales_nuevas, generales_corregidas, bitacora = [], [], [], [], []
        for inscripcion, estado, observaciones in filas:
            registro = previas.get(inscripcion.pk)
            antes = (registro.estado, registro.observaciones) if registro is not None else ('', '')
            if antes != (estado, observaciones):
                bitacora.append(CambioAsistencia(
                    inscripcion=inscripcion, fecha=fecha, materia_grado=asignacion, estado_anterior=antes[0], estado_nuevo=estado,
                    observacion_anterior=antes[1], observacion_nueva=observaciones, via=via, usuario=usuario,
                ))
            if registro is None:
                nuevas.append(AsistenciaMateria(
                    inscripcion=inscripcion, materia_grado=asignacion, fecha=fecha, estado=estado, origen='PASE',
                    registrado_por=usuario, observaciones=observaciones,
                ))
            else:
                registro.estado, registro.observaciones = estado, observaciones
                registro.origen, registro.registrado_por, registro.modificado = 'PASE', usuario, ahora
                cambiadas.append(registro)

            if estado != 'FALTA':
                general = generales.get(inscripcion.pk)
                nota = f'Registrada en el pase de lista de {asignacion.materia}.'
                if general is None or general.estado == 'FALTA':
                    bitacora.append(CambioAsistencia(
                        inscripcion=inscripcion, fecha=fecha, estado_anterior=general.estado if general else '', estado_nuevo='PRESENTE',
                        hora_anterior=general.hora_entrada if general else None, observacion_anterior=general.observaciones if general else '',
                        observacion_nueva=nota, via=via, usuario=usuario,
                    ))
                if general is None:
                    generales_nuevas.append(AsistenciaGeneral(
                        inscripcion=inscripcion, fecha=fecha, estado='PRESENTE', origen='MANUAL', registrado_por=usuario, observaciones=nota,
                    ))
                elif general.estado == 'FALTA':
                    general.estado, general.observaciones, general.registrado_por, general.modificado = 'PRESENTE', nota, usuario, ahora
                    generales_corregidas.append(general)

        AsistenciaMateria.objects.bulk_create(nuevas, ignore_conflicts=True)
        AsistenciaMateria.objects.bulk_update(cambiadas, ['estado', 'observaciones', 'origen', 'registrado_por', 'modificado'])
        AsistenciaGeneral.objects.bulk_create(generales_nuevas, ignore_conflicts=True)
        AsistenciaGeneral.objects.bulk_update(generales_corregidas, ['estado', 'observaciones', 'registrado_por', 'modificado'])
        CambioAsistencia.objects.bulk_create(bitacora)
    return len(filas)


# ---------------------------------------------------------------------------
# Cierre del día
# ---------------------------------------------------------------------------
def cerrar_dia(fecha, usuario=None, automatico=False):
    """Genera las faltas del día: a quien no registró entrada, general y de cada una de sus materias.

    También completa las materias que le faltan a quien sí asistió (presentes, o según la hora a la que llegó).
    Se puede repetir sin problema. Devuelve cuántos alumnos quedaron con falta general, o None si ese día no se cierra
    (día sin clases de todo el colegio, futuro o fuera de un ciclo). Los niveles sin clases ese día no se tocan.
    """
    if fecha > timezone.localdate() or motivo_sin_clases(fecha):
        return None
    ciclo = ciclo_de_fecha(fecha)
    configuracion = ConfiguracionAsistencia.cargar()
    inscripciones = list(inscripciones_del_dia(fecha, ciclo).select_related('grado'))
    generales = {a.inscripcion_id: a for a in AsistenciaGeneral.objects.filter(fecha=fecha, inscripcion__ciclo=ciclo)}
    clases = clases_por_grupo(ciclo, fecha)
    registradas = defaultdict(set)  # id de inscripción -> materias que ya tienen asistencia ese día
    for inscripcion_id, asignacion_id in AsistenciaMateria.objects.filter(fecha=fecha, inscripcion__ciclo=ciclo).values_list('inscripcion_id', 'materia_grado_id'):
        registradas[inscripcion_id].add(asignacion_id)

    suspendidos = alumnos_suspendidos(fecha)   # con suspensión autorizada ese día: no faltaron
    with transaction.atomic():
        nuevas_generales, nuevas_materias = [], []
        for inscripcion in inscripciones:
            general = generales.get(inscripcion.pk)
            clases_del_grado = clases.get(inscripcion.grupo_id, [])
            if inscripcion.alumno_id in suspendidos and (general is None or general.estado == 'FALTA'):
                continue
            if general is None or general.estado == 'FALTA':
                if general is None:
                    nuevas_generales.append(AsistenciaGeneral(
                        inscripcion=inscripcion, fecha=fecha, estado='FALTA', origen='CIERRE', registrado_por=usuario,
                        observaciones='No registró entrada.',
                    ))
                nuevas_materias += _materias_por_crear(
                    inscripcion, fecha, None, 0, clases_del_grado, registradas[inscripcion.pk], 'CIERRE', usuario,
                    estado_fijo='FALTA', nota='No asistió al colegio.',
                )
            else:
                nuevas_materias += _materias_por_crear(
                    inscripcion, fecha, general.hora_entrada, configuracion.tolerancia_minutos, clases_del_grado,
                    registradas[inscripcion.pk], 'CIERRE', usuario, retardo_de_entrada=general.estado == 'RETARDO',
                )
        AsistenciaGeneral.objects.bulk_create(nuevas_generales, ignore_conflicts=True)
        AsistenciaMateria.objects.bulk_create(nuevas_materias, ignore_conflicts=True)
        faltas = len(nuevas_generales)

        CierreDia.objects.update_or_create(fecha=fecha, defaults={
            'cerrado_en': timezone.now(), 'cerrado_por': usuario, 'automatico': automatico, 'faltas': faltas,
        })
    if configuracion.avisar_a_tutores and fecha >= timezone.localdate() - timedelta(days=DIAS_PARA_AVISAR):
        try:
            avisar_a_tutores(fecha, ciclo)
        except Exception:   # un fallo al avisar nunca deshace el cierre
            logger.exception('No se pudo avisar a los tutores de la asistencia del %s', fecha)
    return faltas


def _texto_del_aviso(registro, fecha):
    alumno = registro.inscripcion.alumno
    dia = date_format(fecha, 'l j \\d\\e F').lower()
    if registro.estado == 'FALTA':
        return f'Falta de {alumno.nombre}', f'{alumno} no asistió al colegio el {dia}.'
    hora = f' a las {registro.hora_entrada:%H:%M}' if registro.hora_entrada else ''
    return f'Retardo de {alumno.nombre}', f'{alumno} llegó con retardo{hora} el {dia}.'


def avisar_a_tutores(fecha, ciclo=None):
    """Avisa en la campana del portal a los tutores de las faltas sin justificar y de los retardos de entrada de ese día
    de sus hijos: tutores activos, con acceso al portal y con un vínculo activo que recibe notificaciones. Los días con
    suspensión autorizada no se avisan y un aviso no se repite (uno por tutor, estudiante y día). Devuelve cuántos
    avisos nuevos propuso."""
    ciclo = ciclo or ciclo_de_fecha(fecha)
    if ciclo is None:
        return 0
    registros = (
        con_justificada_general(sin_dias_suspendidos(AsistenciaGeneral.objects.filter(
            fecha=fecha, inscripcion__ciclo=ciclo, inscripcion__activa=True, inscripcion__alumno__estatus='ACTIVO',
            estado__in=('FALTA', 'RETARDO'),
        )))
        .filter(justificada=False).select_related('inscripcion__alumno')
    )
    por_alumno = {registro.inscripcion.alumno_id: registro for registro in registros}
    if not por_alumno:
        return 0
    vinculos = TutorAlumno.objects.filter(
        alumno__in=por_alumno, activo=True, recibe_notificaciones=True, tutor__estatus='ACTIVO', tutor__acceso_portal=True,
    ).values_list('tutor_id', 'alumno_id')
    avisos = []
    for tutor_id, alumno_id in vinculos:
        registro = por_alumno[alumno_id]
        titulo, texto = _texto_del_aviso(registro, fecha)
        avisos.append(NotificacionAsistencia(
            tutor_id=tutor_id, inscripcion=registro.inscripcion, fecha=fecha, tipo=registro.estado, titulo=titulo[:160], texto=texto[:300],
        ))
    NotificacionAsistencia.objects.bulk_create(avisos, ignore_conflicts=True)
    return len(avisos)


def suspension_vigente(alumno, fecha):
    """La suspensión autorizada (de un registro de conducta no anulado) que incluye ese día, o None."""
    from Conducta.models import APROBADA, Suspension
    return (
        Suspension.objects.filter(aprobacion=APROBADA, registro__anulado=False, registro__alumno=alumno,
                                  fecha_inicio__lte=fecha, fecha_fin__gte=fecha)
        .order_by('-fecha_fin').first()
    )


def suspensiones_del_dia(fecha, alumnos):
    """{id de estudiante: suspensión} de esos estudiantes con una suspensión autorizada o pendiente de autorizar (de un
    registro no anulado) que incluye ese día; si tiene las dos, la autorizada."""
    from Conducta.models import APROBADA, PENDIENTE, Suspension
    por_alumno = {}
    for suspension in (Suspension.objects.filter(aprobacion__in=(APROBADA, PENDIENTE), registro__anulado=False, registro__alumno__in=alumnos,
                                                 fecha_inicio__lte=fecha, fecha_fin__gte=fecha).select_related('registro')):
        actual = por_alumno.get(suspension.registro.alumno_id)
        if actual is None or (suspension.aprobada and not actual.aprobada):
            por_alumno[suspension.registro.alumno_id] = suspension
    return por_alumno


def alumnos_suspendidos(fecha):
    """Ids de los estudiantes con una suspensión autorizada (de un registro de conducta no anulado) que incluye ese día."""
    from Conducta.models import APROBADA, Suspension
    return set(
        Suspension.objects.filter(aprobacion=APROBADA, registro__anulado=False, fecha_inicio__lte=fecha, fecha_fin__gte=fecha)
        .values_list('registro__alumno_id', flat=True)
    )


def sin_dias_suspendidos(asistencias, campo='inscripcion__alumno'):
    """Los registros de asistencia sin los de días en que el estudiante tenía una suspensión autorizada: esos días no
    cuentan como faltas ni como asistencia (estaba suspendido)."""
    from Conducta.models import APROBADA, Suspension
    suspendido = Suspension.objects.filter(
        aprobacion=APROBADA, registro__anulado=False, registro__alumno=OuterRef(campo),
        fecha_inicio__lte=OuterRef('fecha'), fecha_fin__gte=OuterRef('fecha'),
    )
    return asistencias.exclude(Exists(suspendido))


def dias_pendientes_de_cierre(hoy=None):
    """Días de clases anteriores a hoy, del ciclo actual, con entradas registradas y que todavía no se cierran."""
    hoy = hoy or timezone.localdate()
    ciclo = CicloEscolar.objects.filter(activo=True).order_by('-fecha_inicio').first()
    if ciclo is None:
        return []
    desde = max(ciclo.fecha_inicio, hoy - timedelta(days=LIMITE_DIAS_PENDIENTES))
    fechas = set(
        AsistenciaGeneral.objects.filter(inscripcion__ciclo=ciclo, fecha__gte=desde, fecha__lt=hoy).values_list('fecha', flat=True).distinct()
    )
    if not fechas:
        return []
    cerradas = set(CierreDia.objects.filter(fecha__in=fechas).values_list('fecha', flat=True))
    sin_clases = fechas_sin_clases(min(fechas), max(fechas))   # de todo el colegio: los de algunos niveles sí se cierran
    return sorted(fechas - cerradas - sin_clases)


def dias_sin_registros(hoy=None):
    """Días de clases anteriores a hoy, del ciclo actual, en que se esperaba a estudiantes y no hay ni un registro de
    entrada ni un cierre (por ejemplo, si la pantalla de entrada falló toda la mañana). No se cierran solos: cerrarlos
    pondría falta a todos. Solo se buscan desde el primer día con registros del ciclo (antes el sistema no se usaba)."""
    hoy = hoy or timezone.localdate()
    ciclo = CicloEscolar.objects.filter(activo=True).order_by('-fecha_inicio').first()
    if ciclo is None:
        return []
    primero = AsistenciaGeneral.objects.filter(inscripcion__ciclo=ciclo).aggregate(primero=Min('fecha'))['primero']
    if primero is None:
        return []
    desde = max(ciclo.fecha_inicio, hoy - timedelta(days=LIMITE_DIAS_PENDIENTES), primero)
    candidatos = dias_de_clases(desde, hoy - timedelta(days=1), ciclo)
    if not candidatos:
        return []
    con_registros = set(
        AsistenciaGeneral.objects.filter(inscripcion__ciclo=ciclo, fecha__in=candidatos).values_list('fecha', flat=True).distinct()
    )
    cerradas = set(CierreDia.objects.filter(fecha__in=candidatos).values_list('fecha', flat=True))
    return [fecha for fecha in candidatos if fecha not in con_registros and fecha not in cerradas and inscripciones_del_dia(fecha, ciclo).exists()]


def cerrar_dias_pendientes(usuario=None, automatico=False, hoy=None):
    """Cierra todos los días pendientes. Devuelve [(fecha, faltas), …]."""
    cerrados = []
    for fecha in dias_pendientes_de_cierre(hoy):
        faltas = cerrar_dia(fecha, usuario=usuario, automatico=automatico)
        if faltas is not None:
            cerrados.append((fecha, faltas))
    return cerrados


def cierre_automatico_del_dia(hoy=None):
    """Cierra los días anteriores una sola vez por día (la primera entrada de la mañana lo dispara), si está activado.
    Si falla, la siguiente entrada lo vuelve a intentar."""
    hoy = hoy or timezone.localdate()
    clave = f'asistencias:cierre-automatico:{hoy}'
    if not cache.add(clave, True, 12 * 3600):   # `add` no pisa la marca: dos entradas simultáneas no cierran dos veces
        return []
    try:
        return cerrar_dias_pendientes(automatico=True, hoy=hoy) if ConfiguracionAsistencia.cargar().cierre_automatico else []
    except Exception:
        cache.delete(clave)
        raise


def en_segundo_plano(tarea, descripcion):
    """Corre `tarea` en un hilo aparte (así quien espera la respuesta no espera la tarea) y registra su error si falla.
    Con ASISTENCIA_CIERRE_EN_SEGUNDO_PLANO apagado (en las pruebas) corre aquí mismo."""
    def correr():
        try:
            tarea()
        except Exception:
            logger.exception(descripcion)

    if not getattr(settings, 'ASISTENCIA_CIERRE_EN_SEGUNDO_PLANO', True):
        correr()
        return

    def en_su_hilo():
        try:
            correr()
        finally:
            connections.close_all()   # el hilo abrió sus propias conexiones a la base de datos

    threading.Thread(target=en_su_hilo, name='asistencias-segundo-plano', daemon=True).start()


def umbral_de(nivel=None, configuracion=None):
    """El umbral de asistencia (%) del nivel; sin uno propio, el general. Por debajo, los reportes marcan al estudiante."""
    propio = UmbralAsistenciaNivel.objects.filter(nivel=nivel).values_list('umbral', flat=True).first() if nivel else None
    return propio or (configuracion or ConfiguracionAsistencia.cargar()).umbral_asistencia


# ---------------------------------------------------------------------------
# Resúmenes
# ---------------------------------------------------------------------------
def resumen_del_dia(fecha, ciclo=None, grupo=None):
    """La asistencia general del día, grado por grado (en orden escolar) y en total (de un solo grupo, si se indica).

    Cada fila: grado, inscritos, presentes, retardos, faltas, justificadas (faltas con justificación), suspendidos (con
    suspensión autorizada ese día: no cuentan como faltas), sin_registro (todavía sin entrada ni falta) y entraron
    (presentes más retardos). El total trae las mismas claves.
    """
    ciclo = ciclo or ciclo_de_fecha(fecha)
    inscripciones = inscripciones_del_dia(fecha, ciclo, grupo=grupo)
    inscritos = dict(inscripciones.order_by().values_list('grado_id').annotate(total=Count('pk')))
    suspendidos = dict(
        inscripciones.filter(alumno__in=alumnos_suspendidos(fecha)).order_by().values_list('grado_id').annotate(total=Count('pk'))
    )
    registros = (
        con_justificada_general(sin_dias_suspendidos(AsistenciaGeneral.objects.filter(fecha=fecha, inscripcion__in=inscripciones)))
        .order_by().values('inscripcion__grado_id')
        .annotate(
            presentes=Count('pk', filter=Q(estado='PRESENTE')),
            retardos=Count('pk', filter=Q(estado='RETARDO')),
            faltas=Count('pk', filter=Q(estado='FALTA')),
            justificadas=Count('pk', filter=Q(estado='FALTA', justificada=True)),
        )
    )
    por_grado = {fila['inscripcion__grado_id']: fila for fila in registros}

    filas, total = [], dict.fromkeys(('inscritos', 'presentes', 'retardos', 'faltas', 'justificadas', 'suspendidos', 'sin_registro', 'entraron'), 0)
    for grado in Grado.objects.filter(pk__in=inscritos).academicos():
        datos = por_grado.get(grado.pk, {})
        fila = {
            'grado': grado, 'inscritos': inscritos[grado.pk],
            'presentes': datos.get('presentes', 0), 'retardos': datos.get('retardos', 0),
            'faltas': datos.get('faltas', 0), 'justificadas': datos.get('justificadas', 0), 'suspendidos': suspendidos.get(grado.pk, 0),
        }
        fila['entraron'] = fila['presentes'] + fila['retardos']
        fila['sin_registro'] = fila['inscritos'] - fila['entraron'] - fila['faltas'] - fila['suspendidos']
        for clave in total:
            total[clave] += fila[clave]
        filas.append(fila)
    return {'grados': filas, 'total': total}


# ---------------------------------------------------------------------------
# Justificaciones
# ---------------------------------------------------------------------------
def con_justificada_general(asistencias):
    """Agrega `justificada` (bool) a asistencias generales: hay una justificación vigente de ese día que la cubre."""
    cubre = Justificacion.objects.filter(
        activa=True, justifica_general=True, inscripcion=OuterRef('inscripcion'), fecha=OuterRef('fecha'),
    )
    return asistencias.annotate(justificada=Exists(cubre))


def con_justificada_materia(asistencias):
    """Agrega `justificada` (bool) a asistencias por materia: la justificación cubre todas las materias o esa."""
    cubre = Justificacion.objects.filter(
        activa=True, inscripcion=OuterRef('inscripcion'), fecha=OuterRef('fecha'),
    ).filter(Q(todas_materias=True) | Q(materias=OuterRef('materia_grado')))
    return asistencias.annotate(justificada=Exists(cubre))


def conteos(asistencias):
    """Totales de un queryset anotado con `justificada` (ver arriba): presentes, retardos, faltas, justificadas, registros."""
    total = asistencias.aggregate(
        registros=Count('pk'),
        presentes=Count('pk', filter=Q(estado='PRESENTE')),
        retardos=Count('pk', filter=Q(estado='RETARDO')),
        faltas=Count('pk', filter=Q(estado='FALTA')),
        justificadas=Count('pk', filter=Q(estado='FALTA', justificada=True)),
    )
    return total


def porcentaje(presentes, retardos, registros):
    """Asistencia = presentes y retardos entre los días con registro (redondeado), o None si no hay registros."""
    return round(100 * (presentes + retardos) / registros) if registros else None
