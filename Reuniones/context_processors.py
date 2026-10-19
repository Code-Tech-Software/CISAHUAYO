"""Las notificaciones de reuniones con familias en todas las páginas: la sección «Reuniones» de la campana (contador y
lista) para el personal del módulo y para los tutores en su portal. Se calcula solo si la plantilla lo usa.

Los recordatorios y los avisos de acuerdos que le toquen a la persona no se generan al dibujar cada página (no le suman
consultas): los genera, a lo más cada pocos minutos, la petición aparte de la campana (vistas `resumen`, que
static/js/reuniones-avisos.js hace al cargar la página) o el comando avisos_de_reuniones."""
from django.core.cache import cache
from django.db import DatabaseError
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.functional import SimpleLazyObject

from CISAHUAYO import portales

from . import notificaciones
from .alcance import usa_reuniones
from .tiempo_real import datos_de

WS = '/ws/mensajes/'   # el canal de avisos es el mismo de la mensajería (Mensajes/routing.py)
EN_LA_CAMPANA = 5
CADA = 300             # segundos entre una generación de recordatorios y la siguiente, por persona


def _hora(momento):
    momento = timezone.localtime(momento)
    return momento.strftime('%H:%M') if momento.date() == timezone.localdate() else momento.strftime('%d/%m')


def cuenta_de(request):
    """(usuario, tutor, espacio de rutas) de quien navega si recibe notificaciones de reuniones; si no, (None, None, None)."""
    usuario = getattr(request, 'user', None)
    if usuario is not None and usuario.is_authenticated:
        return (usuario, None, 'reuniones') if usa_reuniones(usuario) else (None, None, None)
    if getattr(request, 'cuenta_portal_tipo', None) == portales.TUTOR:
        return None, request.cuenta_portal, 'portal_tutores:reuniones'
    return None, None, None


def generar_si_toca(usuario=None, tutor=None):
    llave = f'reuniones-avisos:{"u" if usuario is not None else "t"}:{(usuario or tutor).pk}'
    if cache.add(llave, 1, CADA):
        notificaciones.generar_para(usuario=usuario, tutor=tutor)


def datos_de_avisos(usuario=None, tutor=None):
    pendientes = notificaciones.pendientes_de(usuario=usuario, tutor=tutor)
    avisos = [{**datos_de(n), 'hora': _hora(n.creada)} for n in pendientes.order_by('-creada', '-pk')[:EN_LA_CAMPANA]]
    return {'pendientes': pendientes.count(), 'avisos': avisos}


def reuniones(request):
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

    return {'avisos_reuniones': SimpleLazyObject(calcular)}
