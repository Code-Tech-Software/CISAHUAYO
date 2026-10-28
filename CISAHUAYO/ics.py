"""Archivos de calendario (.ics, iCalendar) sin dependencias: un evento suelto («Agregar a mi calendario» de un comunicado
o de un evento de la agenda) o un calendario completo (la suscripción a la agenda, que el teléfono vuelve a leer solo).
iPhone, Android, Google Calendar y Outlook los abren.

    calendario([EventoIcs(uid='agenda-7@cisahuayo', titulo='Junta', fecha_inicio=date(…))], nombre='Agenda')  -> str
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone

from django.utils import timezone


@dataclass
class EventoIcs:
    uid: str
    titulo: str
    fecha_inicio: date
    fecha_fin: date = None          # vacía: el mismo día
    hora_inicio: time = None        # vacía: todo el día
    hora_fin: time = None
    descripcion: str = ''
    lugar: str = ''
    url: str = ''


def texto(valor):
    """Un valor de texto como lo pide iCalendar (sin comas, puntos y coma ni saltos sin escapar)."""
    return (valor or '').replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\r\n', '\n').replace('\n', '\\n')


def plegar(linea):
    """Los renglones de un .ics no pasan de 75 bytes: los largos siguen en el siguiente, empezando con un espacio."""
    if len(linea.encode('utf-8')) <= 75:
        return linea
    partes, actual = [], ''
    for caracter in linea:
        if len((actual + caracter).encode('utf-8')) > (75 if not partes else 74):
            partes.append(actual)
            actual = caracter
        else:
            actual += caracter
    partes.append(actual)
    return '\r\n '.join(partes)


def utc(momento):
    return momento.astimezone(dt_timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def _lineas(evento, ahora):
    fin = evento.fecha_fin or evento.fecha_inicio
    lineas = ['BEGIN:VEVENT', f'UID:{evento.uid}', f'DTSTAMP:{utc(ahora)}']
    if evento.hora_inicio:
        inicio = timezone.make_aware(datetime.combine(evento.fecha_inicio, evento.hora_inicio))
        termina = (timezone.make_aware(datetime.combine(fin, evento.hora_fin)) if evento.hora_fin
                   else inicio + timedelta(hours=1))
        if termina <= inicio:
            termina = inicio + timedelta(hours=1)
        lineas += [f'DTSTART:{utc(inicio)}', f'DTEND:{utc(termina)}']
    else:
        lineas += [f'DTSTART;VALUE=DATE:{evento.fecha_inicio:%Y%m%d}', f'DTEND;VALUE=DATE:{fin + timedelta(days=1):%Y%m%d}']
    lineas.append(f'SUMMARY:{texto(evento.titulo)}')
    descripcion = (evento.descripcion or '')[:1000] + (f'\n\n{evento.url}' if evento.url else '')
    if descripcion.strip():
        lineas.append(f'DESCRIPTION:{texto(descripcion.strip())}')
    if evento.lugar:
        lineas.append(f'LOCATION:{texto(evento.lugar)}')
    if evento.url:
        lineas.append(f'URL:{evento.url}')
    lineas.append('END:VEVENT')
    return lineas


def calendario(eventos, nombre='', refrescar_horas=None):
    """El texto del .ics con esos eventos. `nombre`: cómo se llama el calendario en el teléfono; `refrescar_horas`: cada
    cuánto debe volver a leerlo (en una suscripción)."""
    ahora = timezone.now()
    lineas = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//CISAHUAYO//Agenda//ES', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH']
    if nombre:
        lineas.append(f'X-WR-CALNAME:{texto(nombre)}')
    if refrescar_horas:
        lineas += [f'REFRESH-INTERVAL;VALUE=DURATION:PT{refrescar_horas}H', f'X-PUBLISHED-TTL:PT{refrescar_horas}H']
    for evento in eventos:
        lineas += _lineas(evento, ahora)
    lineas.append('END:VCALENDAR')
    return '\r\n'.join(plegar(linea) for linea in lineas) + '\r\n'
