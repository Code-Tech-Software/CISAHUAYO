from django import template
from django.utils.formats import date_format

from .. import notificaciones
from ..disponibilidad import nombre_de_persona, nombre_de_usuario
from ..reglas import ICONO_DE_ESTADO, TONO_DE_ACUERDO, TONO_DE_ESTADO

register = template.Library()


@register.filter
def tono_estado(estado):
    return TONO_DE_ESTADO.get(estado, '')


@register.filter
def icono_estado(estado):
    return ICONO_DE_ESTADO.get(estado, 'info')


@register.filter
def tono_acuerdo(estado):
    return TONO_DE_ACUERDO.get(estado, '')


@register.filter
def persona(objeto):
    """«Ana Campos Vega» de un tutor o un estudiante."""
    return nombre_de_persona(objeto) if objeto else ''


@register.filter
def cuenta(usuario):
    """El nombre de una cuenta del personal."""
    return nombre_de_usuario(usuario) if usuario else '—'


@register.filter
def cuando(reunion):
    """«Lunes 20 de octubre, 10:00 a 10:30 · Sala de juntas» o «Por programar»."""
    return notificaciones.cuando(reunion)


@register.filter
def grupo_corto(inscripcion):
    """«Secundaria · 7° A» de una inscripción (el grupo con la equivalencia del grado)."""
    if not inscripcion:
        return 'Sin inscripción en el ciclo actual'
    grado = inscripcion.grado
    grupo = inscripcion.grupo.corto if inscripcion.grupo_id else str(grado)
    return f'{grado.get_nivel_display()} · {grupo}'


@register.filter
def fecha_larga(fecha):
    return date_format(fecha, 'l j \d\e F \d\e Y').capitalize() if fecha else ''


@register.filter
def get(diccionario, clave):
    """El valor de una clave de un diccionario (en las plantillas)."""
    return (diccionario or {}).get(clave)
