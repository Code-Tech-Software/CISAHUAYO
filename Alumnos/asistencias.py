"""Reglas del control de asistencia: entrada del alumno, asistencia por materia, cierre del día y justificaciones.

Cómo funciona (el colegio tiene un solo grupo por grado):
- Al llegar, el alumno registra su entrada con su credencial (UID) o su número de referencia. Eso crea su asistencia
  general del día y, de una vez, la de cada materia que su grado tiene ese día, para que el profesor ya la encuentre
  al empezar la clase y solo corrija lo que haga falta.
- Quien llega cuando una clase ya empezó o terminó queda con retardo o falta en esa materia.
- Al cerrar el día se generan las faltas de quien nunca registró entrada.
- Una falta está «justificada» cuando hay una justificación vigente que la cubre (se calcula al consultar: no se
  guarda en la asistencia, así que anular o cambiar una justificación se refleja sola).
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import time, timedelta

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone

from .models import (
    Alumno,
    AsistenciaGeneral,
    AsistenciaMateria,
    CicloEscolar,
    CierreDia,
    ConfiguracionAsistencia,
    DiaNoLectivo,
    Grado,
    HorarioMateria,
    Inscripcion,
    Justificacion,
)

ESTADOS = ('PRESENTE', 'RETARDO', 'FALTA')
ETIQUETAS = dict(AsistenciaGeneral.ESTADO_CHOICES)
# Máximo de días que se revisan hacia atrás al cerrar días pendientes (evita un cierre enorme por error)
LIMITE_DIAS_PENDIENTES = 45


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


def motivo_sin_clases(fecha, ciclo=None, exigir_actual=False):
    """Por qué ese día no se registra asistencia (texto), o None si es día de clases.

    `exigir_actual` pide además que el ciclo del día sea el ciclo actual (se usa para registrar entradas y para
    capturar: los ciclos cerrados y los próximos no se modifican).
    """
    ciclo = ciclo or ciclo_de_fecha(fecha)
    if ciclo is None:
        return 'Ese día queda fuera de las fechas de cualquier ciclo escolar.'
    if exigir_actual and not ciclo.activo:
        return f'El ciclo {ciclo} no es el ciclo actual.'
    sin_clases = DiaNoLectivo.objects.filter(fecha=fecha).values_list('motivo', flat=True).first()
    if sin_clases:
        return f'Día sin clases: {sin_clases}.'
    if fecha.weekday() >= 5 and not HorarioMateria.objects.filter(
        materia_grado__ciclo=ciclo, materia_grado__activa=True, dia_semana=fecha.weekday(),
    ).exists():
        return 'No hay clases en fin de semana.'
    return None


def dias_de_clases(desde, hasta, ciclo):
    """Los días de clases entre dos fechas (inclusive), dentro del ciclo: sin días sin clases y sin fines de semana sin horario."""
    desde, hasta = max(desde, ciclo.fecha_inicio), min(hasta, ciclo.fecha_fin)
    if desde > hasta:
        return []
    sin_clases = set(DiaNoLectivo.objects.filter(fecha__range=(desde, hasta)).values_list('fecha', flat=True))
    dias_con_horario = set(
        HorarioMateria.objects.filter(materia_grado__ciclo=ciclo, materia_grado__activa=True).values_list('dia_semana', flat=True).distinct()
    )
    fechas = []
    for indice in range((hasta - desde).days + 1):
        fecha = desde + timedelta(days=indice)
        if fecha not in sin_clases and (fecha.weekday() < 5 or fecha.weekday() in dias_con_horario):
            fechas.append(fecha)
    return fechas


def asistencia_editable(fecha):
    """Se captura y corrige asistencia en el ciclo actual, de los días que ya empezaron (nunca del futuro)."""
    if fecha > timezone.localdate():
        return False
    ciclo = ciclo_de_fecha(fecha)
    return ciclo is not None and ciclo.activo


# ---------------------------------------------------------------------------
# Quiénes asisten y a qué clases
# ---------------------------------------------------------------------------
def inscripciones_del_dia(fecha, ciclo=None, grado=None):
    """Inscripciones vigentes que deben asistir ese día: alumnos activos, ya inscritos, en el ciclo del día."""
    ciclo = ciclo or ciclo_de_fecha(fecha)
    if ciclo is None:
        return Inscripcion.objects.none()
    inscripciones = Inscripcion.objects.filter(
        ciclo=ciclo, activa=True, alumno__estatus='ACTIVO', fecha_inscripcion__lte=fecha,
    )
    if grado is not None:
        inscripciones = inscripciones.filter(grado=grado)
    return inscripciones


def _bloques_del_dia(ciclo, fecha, **filtros):
    return (
        HorarioMateria.objects.filter(
            materia_grado__ciclo=ciclo, materia_grado__activa=True, materia_grado__materia__activa=True,
            dia_semana=fecha.weekday(), **filtros,
        )
        .select_related('materia_grado__materia', 'materia_grado__profesor', 'materia_grado__grado')
        .order_by('hora_inicio')
    )


def clases_por_grado(ciclo, fecha, **filtros):
    """{id de grado: [Clase, …]} de las materias que se imparten ese día, en orden de hora."""
    horas = {}
    for bloque in _bloques_del_dia(ciclo, fecha, **filtros):
        horas.setdefault(bloque.materia_grado.pk, (bloque.materia_grado, set()))[1].add((bloque.hora_inicio, bloque.hora_fin))
    clases = defaultdict(list)
    for asignacion, bloques in horas.values():
        bloques = tuple(sorted(bloques))
        clases[asignacion.grado_id].append(Clase(asignacion, bloques[0][0], max(fin for _, fin in bloques), bloques))
    for lista in clases.values():
        lista.sort(key=lambda clase: (clase.inicio, clase.asignacion.materia.nombre))
    return clases


def clases_del_dia(grado, ciclo, fecha):
    return clases_por_grado(ciclo, fecha, materia_grado__grado=grado).get(grado.pk, [])


# ---------------------------------------------------------------------------
# Estados según la hora de llegada
# ---------------------------------------------------------------------------
def _minuto(hora):
    """La hora sin segundos: se compara como se muestra (08:10:40 cuenta como 08:10)."""
    return hora.replace(second=0, microsecond=0)


def _mas_minutos(hora, minutos):
    total = min(hora.hour * 60 + hora.minute + minutos, 23 * 60 + 59)
    return time(total // 60, total % 60)


def estado_de_entrada(hora, configuracion):
    """PRESENTE si llegó a tiempo (hora de entrada más la tolerancia); RETARDO si después."""
    limite = _mas_minutos(configuracion.hora_entrada, configuracion.tolerancia_minutos)
    return 'PRESENTE' if _minuto(hora) <= limite else 'RETARDO'


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


def _materias_por_crear(inscripcion, fecha, hora, tolerancia, clases, existentes, origen, usuario, estado_fijo=None, nota=''):
    """Objetos AsistenciaMateria (sin guardar) de las materias que `existentes` todavía no tiene.

    `estado_fijo` (por ejemplo FALTA) manda sobre el que saldría de la hora de llegada.
    """
    nuevas = []
    for clase in clases:
        if clase.pk in existentes:
            continue
        estado = estado_fijo or (estado_en_clase(hora, clase, tolerancia) if hora else 'PRESENTE')
        nuevas.append(AsistenciaMateria(
            inscripcion=inscripcion, materia_grado=clase.asignacion, fecha=fecha, estado=estado, origen=origen,
            registrado_por=usuario, observaciones=nota or (_nota_de_llegada(estado, hora) if hora else ''),
        ))
    return nuevas


def crear_asistencias_de_materias(inscripcion, fecha, hora, tolerancia, clases=None, origen='ENTRADA', usuario=None):
    """Crea la asistencia de cada materia del día que todavía no la tiene, según la hora de llegada.

    Con `hora=None` (no se sabe a qué hora llegó) todas quedan presentes. Nunca toca las que ya existen.
    Devuelve cuántas creó.
    """
    clases = clases if clases is not None else clases_del_dia(inscripcion.grado, inscripcion.ciclo, fecha)
    existentes = set(
        AsistenciaMateria.objects.filter(inscripcion=inscripcion, fecha=fecha).values_list('materia_grado_id', flat=True)
    )
    nuevas = _materias_por_crear(inscripcion, fecha, hora, tolerancia, clases, existentes, origen, usuario)
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


def buscar_alumno(codigo, modo='uid'):
    """El alumno de un código escaneado (UID de la credencial) o escrito (número de referencia).

    Se busca primero según `modo`, pero si no aparece se prueba el otro: así un UID escaneado con el cursor en el campo
    de la referencia (o al revés) también funciona. Devuelve (alumno, origen) con origen UID o REFERENCIA.
    """
    codigo = ''.join(caracter for caracter in (codigo or '') if caracter.isprintable()).strip()
    if not codigo:
        raise EntradaRechazada('VACIO', 'Acerca tu credencial o escribe tu número de referencia.')
    campos = (('UID', 'uid'), ('REFERENCIA', 'referencia'))
    for origen, campo in (campos if modo != 'referencia' else campos[::-1]):
        alumno = Alumno.objects.filter(**{f'{campo}__iexact': codigo}).first()
        if alumno:
            return alumno, origen
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
    motivo = motivo_sin_clases(fecha, exigir_actual=True)
    if motivo:
        raise EntradaRechazada('SIN_CLASES', motivo)
    ciclo = ciclo_de_fecha(fecha)
    inscripcion = Inscripcion.objects.filter(alumno=alumno, ciclo=ciclo, activa=True).select_related('grado', 'ciclo').first()
    if inscripcion is None:
        raise EntradaRechazada('SIN_INSCRIPCION', 'No tienes una inscripción vigente en el ciclo actual. Acude a control escolar.')

    configuracion = ConfiguracionAsistencia.cargar()
    try:
        with transaction.atomic():
            existente = AsistenciaGeneral.objects.filter(inscripcion=inscripcion, fecha=fecha).first()
            if existente:
                return ResultadoEntrada(existente, creada=False)
            asistencia = AsistenciaGeneral.objects.create(
                inscripcion=inscripcion, fecha=fecha, estado=estado_de_entrada(hora, configuracion),
                hora_entrada=hora, origen=origen, registrado_por=usuario,
            )
            materias = crear_asistencias_de_materias(inscripcion, fecha, hora, configuracion.tolerancia_minutos, usuario=usuario)
    except IntegrityError:  # dos lecturas casi simultáneas de la misma credencial: ganó la otra
        return ResultadoEntrada(AsistenciaGeneral.objects.get(inscripcion=inscripcion, fecha=fecha), creada=False)
    return ResultadoEntrada(asistencia, creada=True, materias=materias)


# ---------------------------------------------------------------------------
# Capturas de quien administra y de los profesores
# ---------------------------------------------------------------------------
def fijar_asistencia_general(inscripcion, fecha, estado, hora=None, observaciones='', usuario=None, propagar=True):
    """Crea o corrige la asistencia general de un alumno ese día (captura manual de quien administra).

    Con `propagar`, las materias del día siguen a la general: una falta general es falta en todas; una presencia
    crea las materias que faltan y recalcula las que genera el sistema (las que el profesor ya capturó no se tocan).
    """
    configuracion = ConfiguracionAsistencia.cargar()
    hora = _minuto(hora) if hora else None
    with transaction.atomic():
        asistencia = AsistenciaGeneral.objects.filter(inscripcion=inscripcion, fecha=fecha).first()
        if asistencia is None:
            asistencia = AsistenciaGeneral(inscripcion=inscripcion, fecha=fecha, origen='MANUAL')
        asistencia.estado = estado
        asistencia.hora_entrada = None if estado == 'FALTA' else hora
        asistencia.observaciones = observaciones
        asistencia.registrado_por = usuario
        asistencia.save()
        if propagar:
            _propagar_a_materias(asistencia, configuracion, usuario)
    return asistencia


def _propagar_a_materias(asistencia, configuracion, usuario):
    inscripcion, fecha = asistencia.inscripcion, asistencia.fecha
    clases = clases_del_dia(inscripcion.grado, inscripcion.ciclo, fecha)
    registros = AsistenciaMateria.objects.filter(inscripcion=inscripcion, fecha=fecha)
    ahora = timezone.now()

    if asistencia.estado == 'FALTA':
        registros.update(estado='FALTA', origen='MANUAL', registrado_por=usuario, observaciones='No asistió al colegio.', modificado=ahora)
        nuevas = [
            AsistenciaMateria(
                inscripcion=inscripcion, materia_grado=clase.asignacion, fecha=fecha, estado='FALTA', origen='MANUAL',
                registrado_por=usuario, observaciones='No asistió al colegio.',
            )
            for clase in clases
        ]
        AsistenciaMateria.objects.bulk_create(nuevas, ignore_conflicts=True)
        return

    # Presente o con retardo: lo que generó el sistema se recalcula con la hora; el pase de lista del profesor se respeta
    registros.exclude(origen='PASE').delete()
    crear_asistencias_de_materias(
        inscripcion, fecha, asistencia.hora_entrada, configuracion.tolerancia_minutos, clases=clases, origen='MANUAL', usuario=usuario,
    )


def guardar_pase_de_lista(asignacion, fecha, filas, usuario=None):
    """Guarda el pase de lista de una materia: `filas` es [(inscripcion, estado, observaciones), …].

    Quien aparece presente o con retardo en una clase estuvo en el colegio: si no tenía asistencia general ese día
    (o tenía falta) se le registra presente. Devuelve cuántos alumnos se guardaron.
    """
    if not filas:
        return 0
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
        nuevas, cambiadas, generales_nuevas, generales_corregidas = [], [], [], []
        for inscripcion, estado, observaciones in filas:
            registro = previas.get(inscripcion.pk)
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
    return len(filas)


# ---------------------------------------------------------------------------
# Cierre del día
# ---------------------------------------------------------------------------
def cerrar_dia(fecha, usuario=None, automatico=False):
    """Genera las faltas del día: a quien no registró entrada, general y de cada una de sus materias.

    También completa las materias que le faltan a quien sí asistió (presentes, o según la hora a la que llegó).
    Se puede repetir sin problema. Devuelve cuántos alumnos quedaron con falta general, o None si ese día no se cierra
    (día sin clases, futuro o fuera de un ciclo).
    """
    if fecha > timezone.localdate() or motivo_sin_clases(fecha):
        return None
    ciclo = ciclo_de_fecha(fecha)
    configuracion = ConfiguracionAsistencia.cargar()
    inscripciones = list(inscripciones_del_dia(fecha, ciclo).select_related('grado'))
    generales = {a.inscripcion_id: a for a in AsistenciaGeneral.objects.filter(fecha=fecha, inscripcion__ciclo=ciclo)}
    clases = clases_por_grado(ciclo, fecha)
    registradas = defaultdict(set)  # id de inscripción -> materias que ya tienen asistencia ese día
    for inscripcion_id, asignacion_id in AsistenciaMateria.objects.filter(fecha=fecha, inscripcion__ciclo=ciclo).values_list('inscripcion_id', 'materia_grado_id'):
        registradas[inscripcion_id].add(asignacion_id)

    with transaction.atomic():
        nuevas_generales, nuevas_materias = [], []
        for inscripcion in inscripciones:
            general = generales.get(inscripcion.pk)
            clases_del_grado = clases.get(inscripcion.grado_id, [])
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
                    registradas[inscripcion.pk], 'CIERRE', usuario,
                )
        AsistenciaGeneral.objects.bulk_create(nuevas_generales, ignore_conflicts=True)
        AsistenciaMateria.objects.bulk_create(nuevas_materias, ignore_conflicts=True)
        faltas = len(nuevas_generales)

        CierreDia.objects.update_or_create(fecha=fecha, defaults={
            'cerrado_en': timezone.now(), 'cerrado_por': usuario, 'automatico': automatico, 'faltas': faltas,
        })
    return faltas


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
    sin_clases = set(DiaNoLectivo.objects.filter(fecha__in=fechas).values_list('fecha', flat=True))
    return sorted(fechas - cerradas - sin_clases)


def cerrar_dias_pendientes(usuario=None, automatico=False, hoy=None):
    """Cierra todos los días pendientes. Devuelve [(fecha, faltas), …]."""
    cerrados = []
    for fecha in dias_pendientes_de_cierre(hoy):
        faltas = cerrar_dia(fecha, usuario=usuario, automatico=automatico)
        if faltas is not None:
            cerrados.append((fecha, faltas))
    return cerrados


def cierre_automatico_del_dia(hoy=None):
    """Cierra los días anteriores una sola vez por día (la primera entrada de la mañana lo dispara), si está activado."""
    hoy = hoy or timezone.localdate()
    clave = f'asistencias:cierre-automatico:{hoy}'
    if cache.get(clave):
        return []
    cerrados = cerrar_dias_pendientes(automatico=True, hoy=hoy) if ConfiguracionAsistencia.cargar().cierre_automatico else []
    cache.set(clave, True, 12 * 3600)
    return cerrados


# ---------------------------------------------------------------------------
# Resúmenes
# ---------------------------------------------------------------------------
def resumen_del_dia(fecha, ciclo=None):
    """La asistencia general del día, grado por grado (en orden escolar) y en total.

    Cada fila: grado, inscritos, presentes, retardos, faltas, justificadas (faltas con justificación), sin_registro
    (todavía sin entrada ni falta) y entraron (presentes más retardos). El total trae las mismas claves.
    """
    ciclo = ciclo or ciclo_de_fecha(fecha)
    inscripciones = inscripciones_del_dia(fecha, ciclo)
    inscritos = dict(inscripciones.order_by().values_list('grado_id').annotate(total=Count('pk')))
    registros = (
        con_justificada_general(AsistenciaGeneral.objects.filter(fecha=fecha, inscripcion__in=inscripciones))
        .order_by().values('inscripcion__grado_id')
        .annotate(
            presentes=Count('pk', filter=Q(estado='PRESENTE')),
            retardos=Count('pk', filter=Q(estado='RETARDO')),
            faltas=Count('pk', filter=Q(estado='FALTA')),
            justificadas=Count('pk', filter=Q(estado='FALTA', justificada=True)),
        )
    )
    por_grado = {fila['inscripcion__grado_id']: fila for fila in registros}

    filas, total = [], dict.fromkeys(('inscritos', 'presentes', 'retardos', 'faltas', 'justificadas', 'sin_registro', 'entraron'), 0)
    for grado in Grado.objects.filter(pk__in=inscritos).academicos():
        datos = por_grado.get(grado.pk, {})
        fila = {
            'grado': grado, 'inscritos': inscritos[grado.pk],
            'presentes': datos.get('presentes', 0), 'retardos': datos.get('retardos', 0),
            'faltas': datos.get('faltas', 0), 'justificadas': datos.get('justificadas', 0),
        }
        fila['entraron'] = fila['presentes'] + fila['retardos']
        fila['sin_registro'] = fila['inscritos'] - fila['entraron'] - fila['faltas']
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
