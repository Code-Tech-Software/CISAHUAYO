"""Periodos de evaluación (parciales, bimestres, trimestres…) de cada nivel.

Un periodo abierto es la ventana en la que los profesores de ese nivel pueden capturar calificaciones: la captura debe
preguntar aquí (`periodos_abiertos` o `periodo_abierto`) y no calcularlo por su cuenta, porque un periodo puede estar
abierto o cerrado a mano además de por sus fechas.
"""
from datetime import timedelta

from django.utils import timezone
from django.utils.formats import date_format

from .models import ORDEN_NIVELES, Grado, Periodo


def periodos_abiertos(nivel, ciclo=None, fecha=None):
    """Los periodos del nivel abiertos en esa fecha (hoy si no se indica), del ciclo indicado o de cualquiera."""
    periodos = Periodo.objects.abiertos(fecha).filter(nivel=nivel)
    if ciclo is not None:
        periodos = periodos.filter(ciclo=ciclo)
    return periodos.order_by('fecha_inicio')


def periodo_abierto(nivel, ciclo=None, fecha=None):
    """El periodo del nivel abierto en esa fecha (el más antiguo, si hubiera varios), o None si no hay ninguno."""
    return periodos_abiertos(nivel, ciclo, fecha).first()


def _en_dias(dias):
    if dias == 0:
        return 'hoy'
    if dias == 1:
        return 'mañana'
    return f'en {dias} días'


def describir(periodo, hoy=None):
    """Una línea que explica su estado: «Se cierra en 5 días», «Se abre mañana», «Se cerró el 31 de octubre»…"""
    hoy = hoy or timezone.localdate()
    if periodo.apertura == Periodo.ABIERTO:
        return 'Se puede capturar hasta que lo cierres.'
    if periodo.apertura == Periodo.CERRADO:
        return 'No se puede capturar hasta que lo abras.'
    estado = periodo.estado_en(hoy)
    if estado == Periodo.PROXIMO:
        return f'Se abre {_en_dias((periodo.fecha_inicio - hoy).days)}.'
    if estado == Periodo.ABIERTO:
        return f'Se cierra {_en_dias((periodo.fecha_fin - hoy).days)}.' if periodo.fecha_fin > hoy else 'Se cierra al terminar el día de hoy.'
    return f'Se cerró el {date_format(periodo.fecha_fin, "j \\d\\e F").lower()}.'


def periodos_por_nivel(ciclo, hoy=None):
    """Los cuatro niveles en orden escolar, cada uno con sus periodos del ciclo (en orden, numerados y descritos)."""
    hoy = hoy or timezone.localdate()
    por_nivel = {nivel: [] for nivel in ORDEN_NIVELES}
    if ciclo is not None:
        for periodo in Periodo.objects.filter(ciclo=ciclo).order_by('fecha_inicio', 'nombre'):
            por_nivel.setdefault(periodo.nivel, []).append(periodo)
    nombres = dict(Grado.NIVEL_CHOICES)
    niveles = []
    for nivel in ORDEN_NIVELES:
        periodos = por_nivel[nivel]
        for numero, periodo in enumerate(periodos, start=1):
            periodo.numero = numero
            periodo.estado_actual = periodo.estado_en(hoy)
            periodo.descripcion = describir(periodo, hoy)
        niveles.append({
            'codigo': nivel,
            'nombre': nombres[nivel],
            'periodos': periodos,
            'abiertos': [periodo for periodo in periodos if periodo.estado_actual == Periodo.ABIERTO],
        })
    return niveles


def fechas_sugeridas(ciclo, nivel):
    """Para un periodo nuevo del nivel: empieza el día siguiente al último que ya tiene (o al iniciar el ciclo)."""
    if ciclo is None:
        return {}
    ultimo = Periodo.objects.filter(ciclo=ciclo, nivel=nivel).order_by('-fecha_fin').first()
    inicio = ultimo.fecha_fin + timedelta(days=1) if ultimo else ciclo.fecha_inicio
    return {'fecha_inicio': inicio} if inicio <= ciclo.fecha_fin else {}
