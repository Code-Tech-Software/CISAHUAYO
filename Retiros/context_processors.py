"""Las notificaciones de retiros en todas las páginas: la sección «Retiros» de la campana (contador y lista) para el
personal que atiende retiros y para los tutores en su portal. Se calcula solo si la plantilla lo usa. Los mismos datos,
en JSON: vistas `resumen` (Retiros/views.py y Retiros/views_portal.py)."""
from django.db import DatabaseError
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.functional import SimpleLazyObject

from CISAHUAYO import portales

from . import notificaciones
from .alcance import usa_retiros
from .tiempo_real import datos_de

WS = '/ws/mensajes/'   # el canal de avisos es el mismo de la mensajería (Mensajes/routing.py)
EN_LA_CAMPANA = 5


def _hora(momento):
    momento = timezone.localtime(momento)
    return momento.strftime('%H:%M') if momento.date() == timezone.localdate() else momento.strftime('%d/%m')


def cuenta_de(request):
    """(usuario, tutor, espacio de rutas) de quien navega si recibe notificaciones de retiros; si no, (None, None, None)."""
    usuario = getattr(request, 'user', None)
    if usuario is not None and usuario.is_authenticated:
        return (usuario, None, 'retiros') if usa_retiros(usuario) else (None, None, None)
    if getattr(request, 'cuenta_portal_tipo', None) == portales.TUTOR:   # lo pone portales.portal_requerido
        return None, request.cuenta_portal, 'portal_tutores:retiros'
    return None, None, None


def datos_de_avisos(usuario=None, tutor=None):
    pendientes = notificaciones.pendientes_de(usuario=usuario, tutor=tutor)
    avisos = [{**datos_de(n), 'hora': _hora(n.creada)} for n in pendientes.order_by('-creada', '-pk')[:EN_LA_CAMPANA]]
    return {'pendientes': pendientes.count(), 'avisos': avisos}


def retiros(request):
    def calcular():
        try:
            usuario, tutor, espacio = cuenta_de(request)
            if espacio is None:
                return {'activa': False}
            datos = datos_de_avisos(usuario=usuario, tutor=tutor)
            datos.update(activa=True, ws=WS, url=reverse(f'{espacio}:lista'), url_resumen=reverse(f'{espacio}:resumen'))
        except (DatabaseError, NoReverseMatch):   # sin la migración o sin las rutas: el resto sigue funcionando
            return {'activa': False}
        return datos

    return {'avisos_retiros': SimpleLazyObject(calcular)}
