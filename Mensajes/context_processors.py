"""La mensajería en todas las páginas: el total sin leer y los avisos de la campana de notificaciones (y del menú)."""
from django.db import DatabaseError
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.functional import SimpleLazyObject

from . import reglas
from .models import Participante

ESPACIO_DE_PORTAL = {'estudiante': Participante.ESTUDIANTE, 'tutor': Participante.TUTOR}


def _hora(momento):
    momento = timezone.localtime(momento)
    return momento.strftime('%H:%M') if momento.date() == timezone.localdate() else momento.strftime('%d/%m')


def datos_de_avisos(participante, espacio, como_json=False):
    """{'no_leidos', 'avisos'}: las conversaciones con mensajes sin leer, con quién escribió y una vista previa."""
    avisos = []
    for conversacion in (reglas.avisos(participante) if participante else []):
        avisos.append({
            'conversacion': conversacion.pk,
            'url': reverse(f'{espacio}:conversacion', args=[conversacion.pk]),
            'nombre': conversacion.otro.nombre,
            'iniciales': conversacion.otro.iniciales,
            'vista_previa': reglas.vista_previa(conversacion.ultimo_mensaje.texto),
            'no_leidos': conversacion.no_leidos,
            'hora': _hora(conversacion.actualizada),
        })
    return {'no_leidos': reglas.no_leidos(participante) if participante else 0, 'avisos': avisos}


def mensajeria(request):
    """`mensajeria.activa` (si la cuenta usa la mensajería), `no_leidos`, `avisos` y las direcciones que usa
    static/js/avisos.js. Se calcula solo si la plantilla lo usa."""
    def calcular():
        try:
            usuario = getattr(request, 'user', None)
            if usuario is not None and usuario.is_authenticated:
                if not reglas.usa_mensajeria(usuario):
                    return {'activa': False}
                espacio, participante = reglas.ESPACIO[Participante.SISTEMA], reglas.de_usuario(usuario, crear=False)
            else:
                cuenta = getattr(request, 'cuenta_portal', None)   # la pone portales.portal_requerido
                if cuenta is None:
                    return {'activa': False}
                tipo = request.cuenta_portal_tipo
                espacio, participante = reglas.ESPACIO[ESPACIO_DE_PORTAL[tipo]], reglas.de_portal(tipo, cuenta, crear=False)
            datos = datos_de_avisos(participante, espacio)
            datos.update(activa=True, ws='/ws/mensajes/', url_bandeja=reverse(f'{espacio}:inicio'), url_resumen=reverse(f'{espacio}:resumen'))
        except (DatabaseError, NoReverseMatch):   # sin la migración o sin las rutas de Mensajes: el resto sigue funcionando
            return {'activa': False}
        return datos

    return {'mensajeria': SimpleLazyObject(calcular)}
