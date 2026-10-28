"""Aviso en tiempo real de un comunicado nuevo, por el mismo canal de la mensajería (Django Channels y Redis).

Cada pestaña abierta se une, además de a su grupo de mensajes, al grupo de comunicados de su persona
(«comunicados.tutor.3», «comunicados.estudiante.12», «comunicados.profesor.4», «comunicados.personal.9»:
Mensajes/consumers.py). Al publicarse se manda un evento a cada destinatario (y otra vez, marcado como recordatorio, a los
pendientes cuando quien lo envió lo pide); static/js/comunicados-avisos.js lo muestra y actualiza los contadores. Lo
manda Comunicados/avisos.py, en segundo plano.

El aviso es solo eso: no confirma que la persona lo haya visto. El comunicado ya está guardado cuando se avisa; si
Redis no está disponible nadie pierde nada (al recargar lo ve y el contador lo cuenta) y solo se registra el error.
"""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.urls import reverse

from .models import Destinatario

registro = logging.getLogger(__name__)
VISTA_PREVIA = 140
CAMPOS = {Destinatario.ESTUDIANTE: 'alumno_id', Destinatario.TUTOR: 'tutor_id', Destinatario.PROFESOR: 'profesor_id',
          Destinatario.PERSONAL: 'usuario_id'}


def grupo(tipo, pk):
    return f'comunicados.{tipo.lower()}.{pk}'


def grupo_de_usuario(usuario):
    """El grupo de comunicados de una cuenta del sistema (un profesor o el personal que puede consultarlos), o None."""
    from .reglas import lector_de_usuario
    lector = lector_de_usuario(usuario)
    return grupo(lector.tipo, lector.persona.pk) if lector else None


def grupo_de_portal(tipo, cuenta):
    from .reglas import lector_de_portal
    lector = lector_de_portal(tipo, cuenta)
    return grupo(lector.tipo, lector.persona.pk)


def url_para(tipo, comunicado_id):
    espacio = {Destinatario.PROFESOR: 'comunicados', Destinatario.PERSONAL: 'comunicados',
               Destinatario.ESTUDIANTE: 'portal_estudiantes:comunicados', Destinatario.TUTOR: 'portal_tutores:comunicados'}[tipo]
    return reverse(f'{espacio}:recibido', args=[comunicado_id])


def vista_previa(texto):
    texto = ' '.join(texto.split())
    return texto if len(texto) <= VISTA_PREVIA else texto[:VISTA_PREVIA - 1].rstrip() + '…'


def enviar_eventos(comunicado, destinatarios, recordatorio=False):
    """Un evento a cada destinatario ({tipo, alumno_id, tutor_id, profesor_id, usuario_id}) en su grupo."""
    capa = get_channel_layer()
    if capa is None:
        return
    from .reglas import nombre_de_usuario
    base = {
        'id': comunicado.pk, 'titulo': comunicado.titulo, 'urgente': comunicado.urgente, 'recordatorio': recordatorio,
        'autor': nombre_de_usuario(comunicado.autor), 'vista_previa': vista_previa(comunicado.descripcion),
    }
    urls = {tipo: url_para(tipo, comunicado.pk) for tipo, _ in Destinatario.TIPOS}
    enviar = async_to_sync(capa.group_send)
    for destinatario in destinatarios:
        tipo = destinatario['tipo']
        try:
            enviar(grupo(tipo, destinatario[CAMPOS[tipo]]), {'type': 'comunicado.nuevo', 'datos': {**base, 'url': urls[tipo]}})
        except Exception:   # Redis caído o inalcanzable: el comunicado ya se guardó
            registro.exception('No se pudo avisar en tiempo real del comunicado %s', comunicado.pk)
            return


def avisar_comunicado(comunicado_id):
    """A todos sus destinatarios, ahora mismo (en este hilo). Lo normal es Comunicados/avisos.avisar, en segundo plano."""
    from .avisos import _avisar
    _avisar(comunicado_id)
