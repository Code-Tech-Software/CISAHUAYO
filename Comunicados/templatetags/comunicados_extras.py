"""Filtros de plantilla de los comunicados."""
from django import template
from django.utils import timezone

register = template.Library()


def _plural(numero, singular, plural):
    return f'{numero} {singular if numero == 1 else plural}'


@register.filter
def tiempo_relativo(momento):
    """«Hace un momento», «Hace 5 minutos», «Hace 3 horas», «Ayer», «Hace 2 días», «Hace 3 semanas», «Hace 2 meses»…
    (en la zona horaria del colegio)."""
    if not momento:
        return ''
    ahora = timezone.now()
    segundos = (ahora - momento).total_seconds()
    if segundos < 60:
        return 'Hace un momento'
    if segundos < 3600:
        return f'Hace {_plural(int(segundos // 60), "minuto", "minutos")}'
    dias = (timezone.localdate(ahora) - timezone.localtime(momento).date()).days
    if dias == 0:
        return f'Hace {_plural(int(segundos // 3600), "hora", "horas")}'
    if dias == 1:
        return 'Ayer'
    if dias < 7:
        return f'Hace {dias} días'
    if dias < 30:
        return f'Hace {_plural(dias // 7, "semana", "semanas")}'
    if dias < 365:
        return f'Hace {_plural(dias // 30, "mes", "meses")}'
    return f'Hace {_plural(dias // 365, "año", "años")}'


@register.filter
def iniciales_de(texto):
    partes = (texto or '').split()
    return ''.join(parte[0] for parte in partes[:2]).upper() or '?'


@register.filter
def tono_de(numero):
    """Un número 1-6 estable (para el color del avatar)."""
    try:
        return int(numero) % 6 + 1
    except (TypeError, ValueError):
        return 1


@register.filter
def tamano_legible(bytes_):
    try:
        bytes_ = int(bytes_)
    except (TypeError, ValueError):
        return ''
    if bytes_ < 1024:
        return f'{bytes_} B'
    if bytes_ < 1024 * 1024:
        return f'{round(bytes_ / 1024)} KB'
    return f'{bytes_ / (1024 * 1024):.1f} MB'.replace('.', ',')
