from django import template

from ..reglas import nombre_de

register = template.Library()


@register.filter
def nombre_corto(persona):
    """«Ana Campos» (nombre y primer apellido) de un tutor o un estudiante."""
    if not persona:
        return ''
    return f'{persona.nombre} {persona.apellido_paterno}'.strip()


@register.filter
def nombre_completo(persona):
    return nombre_de(persona) if persona else ''
