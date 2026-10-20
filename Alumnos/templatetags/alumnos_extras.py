"""Filtros de plantilla de la sección de alumnos."""
from django import template

from ..models import ORDEN_NIVELES, Grado
from ..utils import normalizar_telefono

register = template.Library()

TONOS_ESTATUS = {
    'ACTIVO': 'success',
    'SUSPENDIDO': 'warning',
    'BAJA': 'danger',
    'EGRESADO': 'info',
    'INACTIVO': 'neutral',
    # estados de una asistencia
    'PRESENTE': 'success',
    'RETARDO': 'warning',
    'FALTA': 'danger',
    # estados de un ciclo escolar
    'ACTUAL': 'success',
    'PROXIMO': 'info',
    'CERRADO': 'neutral',
}


@register.filter
def telefono(valor):
    """353 533 0557 (si no son 10 dígitos, devuelve el texto tal cual)."""
    digitos = normalizar_telefono(valor)
    if len(digitos) != 10:
        return valor
    return f'{digitos[:3]} {digitos[3:6]} {digitos[6:]}'


@register.filter
def tono(pk):
    """Número 1-6 estable por registro, para variar el color de los avatares."""
    try:
        return int(pk) % 6 + 1
    except (TypeError, ValueError):
        return 1


@register.filter
def nivel_tono(nivel):
    """Número 1-4 según el nivel escolar, para dar a cada nivel su propio color."""
    return ORDEN_NIVELES.index(nivel) + 1 if nivel in ORDEN_NIVELES else 1


@register.filter
def nombre_de_nivel(nivel):
    """'PRIMARIA' -> 'Primaria'."""
    return dict(Grado.NIVEL_CHOICES).get(nivel, nivel)


@register.filter
def tono_estatus(estatus):
    """Variante de color (.tag--*) de un estatus."""
    return TONOS_ESTATUS.get(estatus, 'neutral')


@register.filter
def grado_equivalente(inscripcion):
    """«7° A» o «K2 B»: la equivalencia del grado en la continuidad escolar (la guardada en Grados o, si no tiene, la
    habitual de su nivel) con su grupo. Sin una equivalencia posible, el grado de siempre («1° A Secundaria»)."""
    if not inscripcion:
        return ''
    from ..academico import equivalencia_sugerida
    grado = inscripcion.grado
    codigo = grado.equivalencia or equivalencia_sugerida(grado.nivel, grado.numero)
    if not codigo:
        return str(inscripcion.grupo or grado)
    texto = f'{codigo}°' if str(codigo).isdigit() else str(codigo)
    return f'{texto} {inscripcion.grupo.nombre}' if inscripcion.grupo_id else texto
