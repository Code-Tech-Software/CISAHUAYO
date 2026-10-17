"""Aviso en tiempo real de un comunicado nuevo, por el mismo canal de la mensajería (Django Channels y Redis).

Cada pestaña abierta se une, además de a su grupo de mensajes, al grupo de comunicados de su persona
(«comunicados.tutor.3», «comunicados.estudiante.12», «comunicados.profesor.4»: Mensajes/consumers.py). Al enviar se
manda un evento a cada destinatario; static/js/comunicados-avisos.js lo muestra y actualiza los contadores.

El aviso es solo eso: no confirma que la persona lo haya visto. El comunicado ya está guardado cuando se avisa; si
Redis no está disponible nadie pierde nada (al recargar lo ve y el contador lo cuenta) y solo se registra el error.
"""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.urls import reverse

from .models import Comunicado, Destinatario

registro = logging.getLogger(__name__)
VISTA_PREVIA = 140


def grupo(tipo, pk):
    return f'comunicados.{tipo.lower()}.{pk}'


def grupo_de_usuario(usuario):
    """El grupo de comunicados de una cuenta del sistema (solo los profesores que pueden consultarlos), o None."""
    from .reglas import lector_de_usuario
    lector = lector_de_usuario(usuario)
    return grupo(lector.tipo, lector.persona.pk) if lector else None


def grupo_de_portal(tipo, cuenta):
    from .reglas import lector_de_portal
    lector = lector_de_portal(tipo, cuenta)
    return grupo(lector.tipo, lector.persona.pk)


def url_para(tipo, comunicado_id):
    espacio = {Destinatario.PROFESOR: 'comunicados', Destinatario.ESTUDIANTE: 'portal_estudiantes:comunicados',
               Destinatario.TUTOR: 'portal_tutores:comunicados'}[tipo]
    return reverse(f'{espacio}:recibido', args=[comunicado_id])


def _vista_previa(texto):
    texto = ' '.join(texto.split())
    return texto if len(texto) <= VISTA_PREVIA else texto[:VISTA_PREVIA - 1].rstrip() + '…'


def avisar_comunicado(comunicado_id):
    capa = get_channel_layer()
    if capa is None:
        return
    comunicado = Comunicado.objects.select_related('autor').filter(pk=comunicado_id, eliminado=False).first()
    if comunicado is None:
        return
    from .reglas import nombre_de_usuario
    base = {
        'id': comunicado.pk, 'titulo': comunicado.titulo, 'urgente': comunicado.urgente,
        'autor': nombre_de_usuario(comunicado.autor), 'vista_previa': _vista_previa(comunicado.descripcion),
    }
    urls = {tipo: url_para(tipo, comunicado.pk) for tipo, _ in Destinatario.TIPOS}
    campos = {Destinatario.ESTUDIANTE: 'alumno_id', Destinatario.TUTOR: 'tutor_id', Destinatario.PROFESOR: 'profesor_id'}
    enviar = async_to_sync(capa.group_send)
    for destinatario in comunicado.destinatarios.values('tipo', 'alumno_id', 'tutor_id', 'profesor_id'):
        tipo = destinatario['tipo']
        try:
            enviar(grupo(tipo, destinatario[campos[tipo]]), {'type': 'comunicado.nuevo', 'datos': {**base, 'url': urls[tipo]}})
        except Exception:   # Redis caído o inalcanzable: el comunicado ya se guardó
            registro.exception('No se pudo avisar en tiempo real del comunicado %s', comunicado.pk)
            return
