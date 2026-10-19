"""Aviso en tiempo real de las notificaciones de reuniones, por el mismo canal de la mensajería (Django Channels).

Cada pestaña abierta del personal del módulo (o de un tutor en su portal) se une también al grupo de reuniones de su
persona («reuniones.usuario.3», «reuniones.tutor.12»: Mensajes/consumers.py). Al guardar una notificación se manda un
evento a su grupo; static/js/reuniones-avisos.js pide el resumen y actualiza la campana.

Si Redis no está disponible nadie pierde nada: la notificación ya está guardada (al recargar se ve).
"""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.urls import reverse

from .alcance import usa_reuniones
from .models import NotificacionReunion

registro = logging.getLogger(__name__)


def grupo_de_usuario(usuario):
    return f'reuniones.usuario.{usuario.pk}' if usa_reuniones(usuario) else None


def grupo_de_tutor(tutor):
    return f'reuniones.tutor.{tutor.pk}'


def url_de(notificacion):
    if notificacion.usuario_id:
        return reverse('reuniones:detalle', args=[notificacion.reunion_id])
    return reverse('portal_tutores:reuniones:detalle', args=[notificacion.reunion_id])


def datos_de(notificacion):
    return {'id': notificacion.pk, 'reunion': notificacion.reunion_id, 'titulo': notificacion.titulo,
            'texto': notificacion.texto, 'url': url_de(notificacion)}


def avisar(ids):
    capa = get_channel_layer()
    if capa is None or not ids:
        return
    enviar = async_to_sync(capa.group_send)
    for notificacion in NotificacionReunion.objects.filter(pk__in=ids):
        grupo = f'reuniones.usuario.{notificacion.usuario_id}' if notificacion.usuario_id else f'reuniones.tutor.{notificacion.tutor_id}'
        try:
            enviar(grupo, {'type': 'reunion.aviso', 'datos': datos_de(notificacion)})
        except Exception:   # Redis caído o inalcanzable: la notificación ya se guardó
            registro.exception('No se pudo avisar en tiempo real de la notificación de reunión %s', notificacion.pk)
            return
