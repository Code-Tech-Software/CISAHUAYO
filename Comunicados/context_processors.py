"""Los comunicados en todas las páginas: cuántos tiene sin leer quien navega (el contador del menú y de la campana).

`avisos_comunicados.activa` solo si la cuenta recibe comunicados: un profesor con permiso en el sistema, o la cuenta
de un portal. Se calcula solo si la plantilla lo usa."""
from django.db import DatabaseError
from django.urls import NoReverseMatch, reverse
from django.utils.functional import SimpleLazyObject

from . import reglas


def comunicados(request):
    def calcular():
        try:
            usuario = getattr(request, 'user', None)
            if usuario is not None and usuario.is_authenticated:
                lector = reglas.lector_de_usuario(usuario)
                url = f"{reverse('comunicados:inicio')}?vista=recibidos"
            else:
                cuenta = getattr(request, 'cuenta_portal', None)   # la pone portales.portal_requerido
                if cuenta is None:
                    return {'activa': False}
                tipo = request.cuenta_portal_tipo
                lector = reglas.lector_de_portal(tipo, cuenta)
                from .views import ESPACIO_DE_PORTAL
                url = reverse(f'{ESPACIO_DE_PORTAL[tipo]}:inicio')
            if lector is None:
                return {'activa': False}
            pendientes, urgentes = lector.pendientes()
        except (DatabaseError, NoReverseMatch):   # sin la migración o sin las rutas: el resto sigue funcionando
            return {'activa': False}
        return {'activa': True, 'pendientes': pendientes, 'urgentes': urgentes, 'url': url}

    return {'avisos_comunicados': SimpleLazyObject(calcular)}
