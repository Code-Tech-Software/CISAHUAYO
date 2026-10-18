"""Aviso en tiempo real de las notificaciones de retiros, por el mismo canal de la mensajería (Django Channels y Redis).

Cada pestaña abierta de quien atiende retiros (o de un tutor en su portal) se une, además de a sus otros grupos, al
grupo de retiros de su persona («retiros.usuario.3», «retiros.tutor.12»: Mensajes/consumers.py). Al guardar una
notificación se manda un evento a su grupo; static/js/retiros-avisos.js la muestra y actualiza los contadores.

Si Redis no está disponible nadie pierde nada: la notificación ya está guardada (al recargar se ve) y solo se registra
el error.
"""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.urls import reverse

from .alcance import usa_retiros
from .models import Notificacion

registro = logging.getLogger(__name__)


def grupo_de_usuario(usuario):
    """El grupo de retiros de una cuenta del sistema (si atiende retiros), o None."""
    return f'retiros.usuario.{usuario.pk}' if usa_retiros(usuario) else None


def grupo_de_tutor(tutor):
    return f'retiros.tutor.{tutor.pk}'


def url_de(notificacion):
    if notificacion.usuario_id:
        return reverse('retiros:detalle', args=[notificacion.aviso_id])
    return reverse('portal_tutores:retiros:detalle', args=[notificacion.aviso_id])


def datos_de(notificacion):
    return {'id': notificacion.pk, 'aviso': notificacion.aviso_id, 'titulo': notificacion.titulo,
            'texto': notificacion.texto, 'url': url_de(notificacion)}


def avisar(ids):
    capa = get_channel_layer()
    if capa is None or not ids:
        return
    enviar = async_to_sync(capa.group_send)
    for notificacion in Notificacion.objects.filter(pk__in=ids):
        grupo = f'retiros.usuario.{notificacion.usuario_id}' if notificacion.usuario_id else f'retiros.tutor.{notificacion.tutor_id}'
        try:
            enviar(grupo, {'type': 'retiro.aviso', 'datos': datos_de(notificacion)})
        except Exception:   # Redis caído o inalcanzable: la notificación ya se guardó
            registro.exception('No se pudo avisar en tiempo real de la notificación de retiro %s', notificacion.pk)
            return
