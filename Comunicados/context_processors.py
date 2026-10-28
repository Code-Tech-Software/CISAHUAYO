"""Los comunicados en todas las páginas: los que tiene sin leer quien navega (el contador del menú y la campana de
notificaciones, que los suma a los mensajes y los lista uno por uno).

`avisos_comunicados.activa` solo si la cuenta recibe comunicados: un profesor o alguien del personal con permiso en el
sistema, o la cuenta de un portal. Se calcula solo si la plantilla lo usa. Los mismos datos, en JSON: vista `resumen` (Comunicados/views.py)."""
from django.db import DatabaseError
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.functional import SimpleLazyObject

from . import reglas

# El canal de avisos es el mismo de la mensajería (Mensajes/routing.py)
WS = '/ws/mensajes/'


def _hora(momento):
    momento = timezone.localtime(momento)
    return momento.strftime('%H:%M') if momento.date() == timezone.localdate() else momento.strftime('%d/%m')


def cuenta_que_recibe(request):
    """(lector, espacio de rutas) de quien navega, o (None, None) si no recibe comunicados."""
    usuario = getattr(request, 'user', None)
    if usuario is not None and usuario.is_authenticated:
        lector = reglas.lector_de_usuario(usuario)
        return (lector, 'comunicados') if lector is not None else (None, None)
    cuenta = getattr(request, 'cuenta_portal', None)   # la pone portales.portal_requerido
    if cuenta is None:
        return None, None
    from .views import ESPACIO_DE_PORTAL
    tipo = request.cuenta_portal_tipo
    return reglas.lector_de_portal(tipo, cuenta), ESPACIO_DE_PORTAL[tipo]


def datos_de_avisos(lector, espacio):
    """{'pendientes', 'urgentes', 'avisos'}: cuántos no ha leído y los más recientes (urgentes primero) para la campana."""
    pendientes, urgentes = lector.pendientes()
    avisos = [{
        'id': copia.comunicado_id,
        'titulo': copia.comunicado.titulo,
        'autor': reglas.nombre_de_usuario(copia.comunicado.autor),
        'urgente': copia.comunicado.urgente,
        'hora': _hora(copia.comunicado.publicado_en),
        'url': reverse(f'{espacio}:recibido', args=[copia.comunicado_id]),
    } for copia in reglas.avisos(lector)]
    return {'pendientes': pendientes, 'urgentes': urgentes, 'avisos': avisos}


def comunicados(request):
    def calcular():
        try:
            lector, espacio = cuenta_que_recibe(request)
            if lector is None:
                return {'activa': False}
            datos = datos_de_avisos(lector, espacio)
            url = reverse(f'{espacio}:inicio') + ('?vista=recibidos' if espacio == 'comunicados' else '')
            datos.update(activa=True, ws=WS, url=url, url_resumen=reverse(f'{espacio}:resumen'))
        except (DatabaseError, NoReverseMatch):   # sin la migración o sin las rutas: el resto sigue funcionando
            return {'activa': False}
        return datos

    return {'avisos_comunicados': SimpleLazyObject(calcular)}
