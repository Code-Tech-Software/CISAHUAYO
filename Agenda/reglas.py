"""Las operaciones de la agenda (2026-10-27): reunir lo que ve cada persona, los eventos que se repiten, el historial de
cambios, los próximos eventos del inicio, la búsqueda y los archivos de calendario (un evento o la suscripción).

Eventos que se repiten: al registrarlo con «Repetir» se crean de una vez todos los de la serie (cada uno es un evento
normal: se ve, se busca, se recuerda y se exporta igual), hasta la fecha elegida (como máximo un año y 120 eventos).
Cada semana, cada dos semanas, cada mes el mismo día, el mismo día de la semana (el primer lunes) o el último (el último
viernes). Se pueden saltar los días sin clases. Al corregir o eliminar uno se elige si aplica a ese o a ese y los
siguientes de la serie.
"""
import calendar
import uuid
from datetime import date, time, timedelta

from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.safestring import mark_safe

from Mensajes import enriquecido

from . import fuentes
from .models import AvisoAgenda, EventoAgenda

SEMANAL, QUINCENAL, MENSUAL_DIA, MENSUAL_ORDINAL, MENSUAL_ULTIMO = 'SEMANAL', 'QUINCENAL', 'MENSUAL_DIA', 'MENSUAL_ORDINAL', 'MENSUAL_ULTIMO'
REPETICIONES = [
    (SEMANAL, 'Cada semana'),
    (QUINCENAL, 'Cada dos semanas'),
    (MENSUAL_DIA, 'Cada mes, el mismo día'),
    (MENSUAL_ORDINAL, 'Cada mes, el mismo día de la semana (p. ej. el primer lunes)'),
    (MENSUAL_ULTIMO, 'Cada mes, el último día de esa semana (p. ej. el último viernes)'),
]
MAXIMO_DE_LA_SERIE = 120
HASTA_UN_ANIO = 366
DIAS = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
ORDINALES = {1: 'primer', 2: 'segundo', 3: 'tercer', 4: 'cuarto'}


# ---------------------------------------------------------------------------
# Lo que ve cada persona
# ---------------------------------------------------------------------------
def eventos_de(persona, desde, hasta, filtro='', tipo=''):
    """Los eventos de la agenda (de sus niveles, con el filtro de nivel) y lo de otros módulos que ve esa persona entre
    esas fechas, con el filtro de tipo."""
    vista = persona.vista
    propios = vista.filtrar(vista.eventos(), filtro).filter(fecha_inicio__lte=hasta, fecha_fin__gte=desde)
    if tipo:
        propios = propios.filter(tipo=tipo)
    externos = fuentes.externos(persona, desde, hasta, filtro)
    if tipo:
        externos = [evento for evento in externos if evento.tipo == tipo]
    return list(propios) + externos


def descripcion_html(evento):
    """La descripción en párrafos, con sus direcciones como enlaces (escapada)."""
    return mark_safe(enriquecido.texto_con_enlaces(evento.descripcion)) if evento.descripcion else ''


# ---------------------------------------------------------------------------
# Eventos que se repiten
# ---------------------------------------------------------------------------
def _mismo_dia_de_la_semana(anio, mes, dia_semana, ordinal):
    """El `ordinal`-ésimo `dia_semana` (0 = lunes) del mes; ordinal -1: el último. None si ese mes no lo tiene."""
    dias = [d for d in range(1, calendar.monthrange(anio, mes)[1] + 1) if date(anio, mes, d).weekday() == dia_semana]
    if ordinal == -1:
        return date(anio, mes, dias[-1])
    return date(anio, mes, dias[ordinal - 1]) if ordinal <= len(dias) else None


def _siguiente_mes(anio, mes):
    return (anio + 1, 1) if mes == 12 else (anio, mes + 1)


def fechas_de_la_serie(inicio, repetir, hasta, saltar=()):
    """Las fechas de inicio de cada evento de la serie (la primera es `inicio`), hasta `hasta` inclusive, sin las de
    `saltar` (como máximo MAXIMO_DE_LA_SERIE)."""
    fechas = []
    if repetir in (SEMANAL, QUINCENAL):
        paso = timedelta(days=7 if repetir == SEMANAL else 14)
        fecha = inicio
        while fecha <= hasta:
            fechas.append(fecha)
            fecha += paso
    else:
        ordinal = -1 if repetir == MENSUAL_ULTIMO else (inicio.day - 1) // 7 + 1
        anio, mes = inicio.year, inicio.month
        while True:
            if repetir == MENSUAL_DIA:
                fecha = date(anio, mes, inicio.day) if inicio.day <= calendar.monthrange(anio, mes)[1] else None
            else:
                fecha = _mismo_dia_de_la_semana(anio, mes, inicio.weekday(), ordinal)
            if fecha is not None and fecha > hasta:
                break
            if fecha is not None and fecha >= inicio:
                fechas.append(fecha)
            anio, mes = _siguiente_mes(anio, mes)
            if date(anio, mes, 1) > hasta:
                break
    saltar = set(saltar)
    return [fecha for fecha in fechas if fecha == inicio or fecha not in saltar][:MAXIMO_DE_LA_SERIE]


def texto_de_repeticion(inicio, repetir, hasta):
    """«Cada lunes hasta el 30 de junio de 2027», «Cada mes, el último viernes…»."""
    dia = DIAS[inicio.weekday()]
    texto = {
        SEMANAL: f'Cada {dia}',
        QUINCENAL: f'Cada dos semanas, en {dia}',
        MENSUAL_DIA: f'Cada mes, el día {inicio.day}',
        MENSUAL_ORDINAL: f'Cada mes, el {ORDINALES.get(min((inicio.day - 1) // 7 + 1, 4))} {dia}',
        MENSUAL_ULTIMO: f'Cada mes, el último {dia}',
    }[repetir]
    return f'{texto} hasta el {date_format(hasta, "j \\d\\e F \\d\\e Y").lower()}'


def dias_a_saltar(alcance, desde, hasta):
    """Los días sin clases de ese alcance (de todo el colegio, o de ese nivel) entre esas fechas."""
    from Alumnos.asistencias import fechas_sin_clases
    from .models import COLEGIO
    return fechas_sin_clases(desde, hasta, None if alcance == COLEGIO else alcance)


@transaction.atomic
def crear(evento, usuario, repetir='', hasta=None, saltar_sin_clases=False):
    """Guarda un evento nuevo (con `repetir`, toda su serie). Devuelve los eventos creados."""
    evento.creado_por = evento.modificado_por = usuario
    if not repetir:
        evento.save()
        registrar(usuario, evento, 'alta', f'Registró el evento ({evento.texto_de_fechas}).')
        _recordar_si_es_pronto([evento])
        return [evento]
    saltar = dias_a_saltar(evento.alcance, evento.fecha_inicio, hasta) if saltar_sin_clases else ()
    duracion = evento.fecha_fin - evento.fecha_inicio
    serie, texto = uuid.uuid4(), texto_de_repeticion(evento.fecha_inicio, repetir, hasta)
    creados = []
    for fecha in fechas_de_la_serie(evento.fecha_inicio, repetir, hasta, saltar):
        copia = EventoAgenda(
            titulo=evento.titulo, descripcion=evento.descripcion, alcance=evento.alcance, tipo=evento.tipo, fecha_inicio=fecha,
            fecha_fin=fecha + duracion, todo_el_dia=evento.todo_el_dia, hora_inicio=evento.hora_inicio, hora_fin=evento.hora_fin,
            lugar=evento.lugar, importante=evento.importante, serie=serie, repeticion=texto, creado_por=usuario, modificado_por=usuario,
        )
        copia.save()
        creados.append(copia)
    registrar(usuario, creados[0], 'alta', f'Registró el evento con {len(creados)} fechas ({texto}).')
    _recordar_si_es_pronto(creados[:1])
    return creados


def _recordar_si_es_pronto(eventos):
    """Un evento importante que se registra (o se mueve) para hoy o mañana se recuerda en ese momento, sin esperar a la
    siguiente revisión (Agenda/recordatorios.py)."""
    hoy = timezone.localdate()
    if any(e.importante and e.recordatorio_en is None and e.fecha_inicio <= hoy + timedelta(days=1) and e.fecha_fin >= hoy for e in eventos):
        from . import recordatorios
        transaction.on_commit(recordatorios.generar_sin_fallar)


def siguientes_de_la_serie(evento):
    """Ese evento y los de su serie que empiezan el mismo día o después."""
    if not evento.serie:
        return EventoAgenda.objects.filter(pk=evento.pk)
    return EventoAgenda.objects.filter(serie=evento.serie, fecha_inicio__gte=evento.fecha_inicio)


CAMPOS_DE_LA_SERIE = ('titulo', 'descripcion', 'alcance', 'tipo', 'todo_el_dia', 'hora_inicio', 'hora_fin', 'lugar', 'importante')


@transaction.atomic
def guardar_cambios(evento, usuario, toda_la_serie=False):
    """Guarda lo corregido; con `toda_la_serie`, también en los siguientes de la serie (sus fechas no cambian)."""
    evento.modificado_por = usuario
    anterior = EventoAgenda.objects.filter(pk=evento.pk).values_list('fecha_inicio', flat=True).first()
    if anterior is not None and anterior != evento.fecha_inicio:
        # Cambió de fecha: se vuelve a recordar para la nueva (los avisos de la fecha anterior ya no sirven)
        evento.recordatorio_en = None
        AvisoAgenda.objects.filter(evento=evento).delete()
    evento.save()
    _recordar_si_es_pronto([evento])
    otros = 0
    if toda_la_serie and evento.serie:
        cambios = {campo: getattr(evento, campo) for campo in CAMPOS_DE_LA_SERIE}
        otros = siguientes_de_la_serie(evento).exclude(pk=evento.pk).update(modificado_por=usuario, **cambios)
    registrar(usuario, evento, 'cambio', 'Corrigió el evento' + (f' y {otros} siguiente{"s" if otros != 1 else ""} de su serie.' if otros else '.'))
    return otros


@transaction.atomic
def eliminar(evento, usuario, y_siguientes=False):
    """Elimina el evento (con `y_siguientes`, también los siguientes de su serie). Devuelve cuántos."""
    consulta = siguientes_de_la_serie(evento) if y_siguientes else EventoAgenda.objects.filter(pk=evento.pk)
    total = consulta.count()
    registrar(usuario, evento, 'baja', 'Eliminó el evento' + (f' y {total - 1} siguiente{"s" if total - 1 != 1 else ""} de su serie.' if total > 1 else '.')
              + f' Era del {evento.texto_de_fechas.lower()}, para {evento.nombre_alcance}.')
    consulta.delete()
    return total


def valores_para_duplicar(evento):
    """Lo que el formulario de «Nuevo evento» trae ya escrito al duplicarlo."""
    return {
        'titulo': evento.titulo, 'descripcion': evento.descripcion, 'alcance': evento.alcance, 'tipo': evento.tipo,
        'fecha_inicio': evento.fecha_inicio, 'fecha_fin': evento.fecha_fin, 'todo_el_dia': evento.todo_el_dia,
        'hora_inicio': evento.hora_inicio, 'hora_fin': evento.hora_fin, 'lugar': evento.lugar, 'importante': evento.importante,
    }


# ---------------------------------------------------------------------------
# Historial de cambios (la Bitácora de cambios del sistema)
# ---------------------------------------------------------------------------
def registrar(usuario, evento, accion, mensaje):
    from Usuarios.seguridad import ACCION_ALTA, ACCION_BAJA, ACCION_CAMBIO
    from Usuarios.seguridad import registrar as anotar
    anotar(usuario, evento, {'alta': ACCION_ALTA, 'cambio': ACCION_CAMBIO, 'baja': ACCION_BAJA}[accion], mensaje)


# ---------------------------------------------------------------------------
# Próximos eventos (el inicio del sistema y de los portales) y búsqueda
# ---------------------------------------------------------------------------
def _orden(evento):
    return (evento.fecha_inicio, not evento.todo_el_dia, evento.hora_inicio or time.min, evento.titulo, str(evento.pk))


def proximos(persona, dias=14, limite=6):
    """Los próximos eventos de quien mira (de hoy a `dias` después; los que ya empezaron y siguen, también), en orden."""
    hoy = timezone.localdate()
    eventos = sorted(eventos_de(persona, hoy, hoy + timedelta(days=dias)), key=lambda e: (max(e.fecha_inicio, hoy), *_orden(e)[1:]))
    base = persona.url('calendario')

    def url(evento):
        if getattr(evento, 'es_externo', False):
            return evento.url_propia or f'{base}?mes={evento.fecha_inicio:%Y-%m}'
        return f'{base}?evento={evento.pk}'

    return [{'evento': evento, 'fecha': max(evento.fecha_inicio, hoy), 'dia': texto_del_dia(max(evento.fecha_inicio, hoy), hoy),
             'url': url(evento)} for evento in eventos[:limite]]


def para_el_inicio(persona):
    """{'proximos', 'url_agenda'} para el recuadro «Próximos eventos» del inicio (templates/agenda/_proximos.html). Si algo
    falla, el inicio se muestra igual, sin el recuadro. De paso, revisa si hay recordatorios por mandar."""
    import logging
    from . import recordatorios
    recordatorios.generar_si_toca()
    try:
        return {'proximos': proximos(persona), 'url_agenda': persona.url('calendario'), 'con_agenda': True}
    except Exception:
        logging.getLogger(__name__).exception('No se pudieron preparar los próximos eventos')
        return {'con_agenda': False}


def texto_del_dia(fecha, hoy):
    if fecha == hoy:
        return 'Hoy'
    if fecha == hoy + timedelta(days=1):
        return 'Mañana'
    if fecha - hoy < timedelta(days=7):
        return date_format(fecha, 'l').capitalize()
    return date_format(fecha, 'D j b').capitalize()


def buscar(persona, texto, filtro='', tipo=''):
    """Los eventos que coinciden con cada palabra (título, descripción o lugar) en el año anterior y el siguiente, del
    más cercano a hoy hacia adelante y luego los pasados."""
    hoy = timezone.localdate()
    desde, hasta = hoy - timedelta(days=365), hoy + timedelta(days=365)
    palabras = [p for p in (texto or '').split() if p]
    vista = persona.vista
    propios = vista.filtrar(vista.eventos(), filtro).filter(fecha_inicio__lte=hasta, fecha_fin__gte=desde)
    if tipo:
        propios = propios.filter(tipo=tipo)
    for palabra in palabras:
        propios = propios.filter(Q(titulo__icontains=palabra) | Q(descripcion__icontains=palabra) | Q(lugar__icontains=palabra))
    from CISAHUAYO.sin_acentos import quitar_acentos
    claves = [quitar_acentos(p).lower() for p in palabras]
    externos = [e for e in fuentes.externos(persona, desde, hasta, filtro) if (not tipo or e.tipo == tipo)
                and all(c in quitar_acentos(f'{e.titulo} {e.descripcion} {e.lugar}').lower() for c in claves)]
    eventos = list(propios) + externos
    futuros = sorted([e for e in eventos if e.fecha_fin >= hoy], key=_orden)
    pasados = sorted([e for e in eventos if e.fecha_fin < hoy], key=_orden, reverse=True)
    return futuros, pasados


def por_dia(eventos, desde, hasta):
    """[(fecha, [eventos])] de los días entre esas fechas que tienen algo (un evento de varios días, en cada uno)."""
    dias = {}
    for evento in sorted(eventos, key=_orden):
        fecha = max(evento.fecha_inicio, desde)
        while fecha <= min(evento.fecha_fin, hasta):
            dias.setdefault(fecha, []).append(evento)
            fecha += timedelta(days=1)
    return sorted(dias.items())


# ---------------------------------------------------------------------------
# Archivos de calendario
# ---------------------------------------------------------------------------
def _ics(evento, url):
    from CISAHUAYO.ics import EventoIcs
    prefijo = 'agenda' if not getattr(evento, 'es_externo', False) else evento.fuente
    return EventoIcs(
        uid=f'{prefijo}-{evento.pk}@cisahuayo', titulo=evento.titulo, fecha_inicio=evento.fecha_inicio, fecha_fin=evento.fecha_fin,
        hora_inicio=None if evento.todo_el_dia else evento.hora_inicio, hora_fin=None if evento.todo_el_dia else evento.hora_fin,
        descripcion=evento.descripcion, lugar=evento.lugar, url=url,
    )


def ics_de_evento(evento, url=''):
    from CISAHUAYO.ics import calendario
    return calendario([_ics(evento, url)])


def ics_de_suscripcion(persona, absoluta):
    """El calendario completo de esa persona: de un mes atrás a un año adelante. `absoluta(ruta)`: la dirección completa."""
    from CISAHUAYO.ics import calendario
    hoy = timezone.localdate()
    eventos = sorted(eventos_de(persona, hoy - timedelta(days=31), hoy + timedelta(days=365)), key=_orden)
    archivos = []
    for evento in eventos:
        if getattr(evento, 'es_externo', False):
            url = absoluta(evento.url_propia) if evento.url_propia else ''
        else:
            url = absoluta(f'{reverse(f"{persona.espacio}:calendario")}?evento={evento.pk}')
        archivos.append(_ics(evento, url))
    return calendario(archivos, nombre='CISAHUAYO · Agenda', refrescar_horas=6)
