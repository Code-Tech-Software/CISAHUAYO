"""Limpieza de los archivos que se subieron a una conversación y nunca se enviaron (pedido del 2026-10-20).

Una imagen o un documento subidos sin enviar el mensaje solo los ve quien los subió; pasado un día se borran (registro
y archivo). Corre sola una vez al día, cuando alguien abre la mensajería (`limpiar_si_toca`), y también con el comando
`python manage.py limpiar_mensajes` (para programarlo, si se quiere, en el servidor).
"""
import logging
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from .models import ImagenMensaje

VIGENCIA = timedelta(days=1)
CADA = 24 * 60 * 60   # segundos entre una limpieza automática y la siguiente
LLAVE = 'mensajes-limpieza'

registro = logging.getLogger(__name__)


def limpiar_pendientes(**filtros):
    """Borra los archivos sin enviar de hace más de un día (con `filtros`, solo esos: p. ej. de una persona en una
    conversación). Devuelve cuántos borró."""
    viejos = list(ImagenMensaje.objects.filter(mensaje__isnull=True, creada__lt=timezone.now() - VIGENCIA, **filtros))
    for archivo in viejos:
        try:
            archivo.archivo.delete(save=False)
        except Exception:   # sin el registro nadie lo puede pedir: el archivo, si quedó, es inaccesible
            registro.exception('No se pudo borrar un archivo sin enviar de la mensajería')
        archivo.delete()
    return len(viejos)


def limpiar_si_toca():
    """La limpieza automática: una vez al día por proceso, la primera vez que alguien abre la mensajería."""
    if cache.add(LLAVE, 1, CADA):
        try:
            limpiar_pendientes()
        except Exception:   # la limpieza nunca debe impedir que se abra la mensajería
            registro.exception('No se pudo limpiar los archivos sin enviar de la mensajería')
