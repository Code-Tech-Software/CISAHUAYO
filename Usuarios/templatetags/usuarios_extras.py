"""Filtros de plantilla de usuarios y roles."""
from django import template

from ..seguridad import iniciales_de, nombre_de

register = template.Library()


@register.filter
def nombre_visible(usuario):
    """«Nombre Apellido»; sin nombre, el usuario."""
    return nombre_de(usuario)


@register.filter
def iniciales(usuario):
    return iniciales_de(usuario)


@register.filter
def modulos_sin_acceso(matriz):
    """Nombres de los módulos del resumen de permisos en los que no se concede nada."""
    return [modulo['modulo'].nombre for modulo in matriz if not modulo['concedidos']]


@register.filter
def tono_de_usuario(usuario):
    """Número 1-6 estable por cuenta, para variar el color de su avatar."""
    try:
        return int(usuario.pk) % 6 + 1
    except (TypeError, ValueError):
        return 1
