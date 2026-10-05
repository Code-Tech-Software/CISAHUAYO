"""Contraseña temporal: quien entra con una debe elegir la suya antes de usar el sistema."""
from django.shortcuts import redirect
from django.urls import reverse

from .signals import SESION_CAMBIO_DE_CONTRASENA


class CambioDeContrasenaObligatorio:
    """Mientras la sesión lleve la marca «debe cambiar su contraseña», todo redirige a la pantalla para hacerlo.

    La marca la pone el inicio de sesión (Usuarios/signals.py) según el perfil, así que aquí no se consulta la base de
    datos. Se permite lo imprescindible: la propia pantalla de cambio, cerrar sesión y los archivos estáticos.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def _permitidas(self):
        return (reverse('cuenta:contrasena'), reverse('logout'), reverse('admin:logout'))

    def __call__(self, request):
        if (
            request.session.get(SESION_CAMBIO_DE_CONTRASENA)
            and request.user.is_authenticated
            and request.path not in self._permitidas()
            and not request.path.startswith(('/static/', '/media/'))
        ):
            return redirect('cuenta:contrasena')
        return self.get_response(request)
