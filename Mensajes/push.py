"""Notificaciones push de la mensajería (pedido del 2026-10-27): el aviso de un mensaje nuevo llega a la computadora o
al celular aunque la página del sistema o del portal esté cerrada.

Cómo funciona (Web Push):
- Al activar los avisos del navegador (la campana: static/js/avisos.js), el navegador registra el service worker
  (/sw.js, templates/mensajes/sw.js) y se suscribe con la clave pública del colegio; la suscripción (una dirección del
  servicio de push de ese navegador y sus claves) se guarda aquí, de esa persona (`SuscripcionPush`).
- Al enviar un mensaje, a cada navegador suscrito de la otra persona se le manda el aviso (quién escribió y una vista
  previa), cifrado: el servicio de push (Google, Apple, Mozilla) no puede leerlo. El service worker lo muestra, salvo
  que el sistema esté a la vista en ese equipo (ahí ya lo avisa la página).
- Si el servicio dice que la suscripción ya no existe, se borra. Al cerrar sesión, la de ese navegador también (en
  una computadora compartida, la siguiente persona no recibe los avisos de la anterior).

Las claves (VAPID) se generan una vez con `python manage.py generar_claves_push` y van en las variables de entorno:
sin ellas, no se ofrecen. En iPhone y iPad solo funcionan con el sistema agregado a la pantalla de inicio.
"""
import json
import logging
import threading

from django.conf import settings
from django.db import connections
from django.db.models import Q

from .models import Miembro, SuscripcionPush

registro = logging.getLogger(__name__)
CLAVE_DE_SESION = 'mensajes_push'   # la suscripción de este navegador, para olvidarla al cerrar sesión
VIGENCIA = 24 * 60 * 60             # si el equipo está apagado, el servicio de push guarda el aviso hasta un día


def activas():
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


class SuscripcionInvalida(ValueError):
    pass


def guardar(participante, datos, request=None):
    """Guarda (o pasa a esta persona) la suscripción que mandó el navegador: {endpoint, keys: {p256dh, auth}}."""
    endpoint = str((datos or {}).get('endpoint') or '')
    claves = (datos or {}).get('keys') or {}
    p256dh, auth = str(claves.get('p256dh') or ''), str(claves.get('auth') or '')
    if not endpoint.startswith('https://') or len(endpoint) > 1000 or not (0 < len(p256dh) <= 200) or not (0 < len(auth) <= 100):
        raise SuscripcionInvalida('La suscripción del navegador no es válida.')
    suscripcion, _ = SuscripcionPush.objects.update_or_create(
        endpoint=endpoint, defaults={'participante': participante, 'p256dh': p256dh, 'auth': auth})
    if request is not None:
        request.session[CLAVE_DE_SESION] = endpoint
    return suscripcion


def olvidar_navegador(request):
    """Al cerrar sesión: este navegador deja de recibir los avisos de esa persona."""
    try:
        endpoint = request.session.get(CLAVE_DE_SESION)
        if endpoint:
            SuscripcionPush.objects.filter(endpoint=endpoint).delete()
    except Exception:   # cerrar sesión nunca debe fallar por esto
        registro.exception('No se pudo quitar la suscripción push al cerrar sesión')


def _enviar(suscripcion, carga, urgente=False):
    from pywebpush import WebPushException, webpush
    try:
        webpush(
            subscription_info={'endpoint': suscripcion.endpoint, 'keys': {'p256dh': suscripcion.p256dh, 'auth': suscripcion.auth}},
            data=json.dumps(carga), vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={'sub': settings.VAPID_CONTACTO}, ttl=VIGENCIA, timeout=10,
            headers={'Urgency': 'high' if urgente else 'normal'},   # un aviso urgente despierta al teléfono de inmediato
        )
    except WebPushException as error:
        estado = getattr(getattr(error, 'response', None), 'status_code', None)
        if estado in (404, 410):   # el navegador quitó el permiso o la suscripción venció
            suscripcion.delete()
        else:
            registro.warning('No se pudo enviar la notificación push (%s): %s', estado, error)
    except Exception:
        registro.exception('No se pudo enviar la notificación push')


def _en_segundo_plano(envios):
    def tarea():
        try:
            for suscripcion, carga in envios:
                _enviar(suscripcion, carga)
        finally:
            if settings.PUSH_EN_SEGUNDO_PLANO:
                connections.close_all()

    if settings.PUSH_EN_SEGUNDO_PLANO:
        threading.Thread(target=tarea, name='mensajes-push', daemon=True).start()
    else:
        tarea()


def suscripciones_de(tutores=(), alumnos=(), usuarios=()):
    """Los navegadores suscritos de esas cuentas (ids de tutores, estudiantes y usuarios del sistema), en una sola
    consulta: {('tutor' | 'alumno' | 'usuario', id): [suscripciones]}. Lo usan los comunicados (Comunicados/avisos.py)."""
    if not (tutores or alumnos or usuarios):
        return {}
    condicion = Q(participante__tutor_id__in=list(tutores)) | Q(participante__alumno_id__in=list(alumnos)) | Q(participante__usuario_id__in=list(usuarios))
    resultado = {}
    for suscripcion in SuscripcionPush.objects.filter(condicion).select_related('participante'):
        participante = suscripcion.participante
        clave = ('tutor', participante.tutor_id) if participante.tutor_id else (
            ('alumno', participante.alumno_id) if participante.alumno_id else ('usuario', participante.usuario_id))
        resultado.setdefault(clave, []).append(suscripcion)
    return resultado


def enviar_ahora(envios, urgente=False):
    """Manda [(suscripción, carga)] en este hilo (quien llama ya decidió si va en segundo plano)."""
    for suscripcion, carga in envios:
        _enviar(suscripcion, carga, urgente)


def avisar_mensaje(mensaje):
    """A los navegadores suscritos de la otra persona de la conversación (no a quien lo escribió). El aviso lleva quién
    escribió, una vista previa y la dirección de la conversación en su espacio (el sistema o su portal)."""
    if not activas():
        return
    from .reglas import vista_previa
    from .tiempo_real import url_de_conversacion
    envios = []
    destinatarios = Miembro.objects.filter(conversacion=mensaje.conversacion_id).exclude(participante=mensaje.autor_id).select_related(
        'participante__usuario', 'participante__alumno', 'participante__tutor')
    for miembro in destinatarios:
        suscripciones = list(SuscripcionPush.objects.filter(participante=miembro.participante_id))
        if not suscripciones:
            continue
        carga = {
            'titulo': mensaje.autor.nombre,
            'texto': vista_previa(mensaje.texto),
            'url': url_de_conversacion(miembro.participante, mensaje.conversacion_id),
            'etiqueta': f'conversacion-{mensaje.conversacion_id}',
        }
        envios.extend((suscripcion, carga) for suscripcion in suscripciones)
    if envios:
        _en_segundo_plano(envios)
