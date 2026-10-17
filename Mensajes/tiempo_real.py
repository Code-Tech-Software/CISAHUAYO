"""Avisos en tiempo real (Django Channels; en producción, Redis reparte los eventos entre los procesos).

Cada participante tiene su grupo («mensajes.<id>»): ahí se conectan todas sus pestañas abiertas (Mensajes/consumers.py)
y ahí llegan los avisos de sus conversaciones. Los mensajes ya están guardados en la base de datos cuando se avisa: si
Redis no está disponible, nadie pierde nada (al recargar, todo está ahí); solo se registra el error.
"""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from .models import Miembro

registro = logging.getLogger(__name__)


def grupo(participante_id):
    return f'mensajes.{participante_id}'


def _enviar(participante_id, evento):
    capa = get_channel_layer()
    if capa is None:
        return
    try:
        async_to_sync(capa.group_send)(grupo(participante_id), evento)
    except Exception:   # Redis caído o inalcanzable: el mensaje ya se guardó
        registro.exception('No se pudo enviar el aviso en tiempo real al participante %s', participante_id)


def url_de_conversacion(participante, conversacion_id):
    from .reglas import ESPACIO
    return reverse(f'{ESPACIO[participante.tipo]}:conversacion', args=[conversacion_id])


def datos_de_mensaje(mensaje, para):
    """Lo que necesita la pantalla de `para` para mostrar el mensaje y su aviso. El texto va tal cual (el navegador lo
    pone como texto, nunca como HTML); el formato, en `html`, ya limpio en el servidor (Mensajes/enriquecido.py)."""
    from .reglas import html_visible, no_leidos, vista_previa
    creado = timezone.localtime(mensaje.creado)
    return {
        'conversacion': mensaje.conversacion_id,
        'id': mensaje.pk,
        'mio': mensaje.autor_id == para.pk,
        'autor': mensaje.autor.nombre,
        'iniciales': mensaje.autor.iniciales,
        'texto': mensaje.texto,
        'html': html_visible(mensaje, para),   # limpio en el servidor; '' si no tiene formato
        'vista_previa': mensaje.texto if len(mensaje.texto) <= 120 else vista_previa(mensaje.texto),
        'hora': creado.strftime('%H:%M'),
        'fecha': creado.date().isoformat(),
        'fecha_texto': date_format(creado, 'j \\d\\e F'),
        'url': url_de_conversacion(para, mensaje.conversacion_id),
        'no_leidos': no_leidos(para),
    }


def avisar_mensaje(mensaje):
    """A cada miembro de la conversación (también a quien lo envió: sus otras pestañas)."""
    miembros = Miembro.objects.filter(conversacion=mensaje.conversacion_id).select_related(
        'participante__usuario', 'participante__alumno', 'participante__tutor')
    for miembro in miembros:
        _enviar(miembro.participante_id, {'type': 'mensaje.nuevo', 'datos': datos_de_mensaje(mensaje, miembro.participante)})


def avisar_lectura(conversacion, lector, hasta):
    """A la otra persona: hasta dónde se leyó (sus mensajes pasan a «Leído»). A quien leyó: su nuevo total sin leer."""
    from .reglas import no_leidos
    for miembro in Miembro.objects.filter(conversacion=conversacion).exclude(participante=lector):
        _enviar(miembro.participante_id, {'type': 'mensaje.leido', 'datos': {'conversacion': conversacion.pk, 'hasta': hasta}})
    _enviar(lector.pk, {'type': 'mensajes.resumen', 'datos': {'conversacion': conversacion.pk, 'no_leidos': no_leidos(lector)}})
