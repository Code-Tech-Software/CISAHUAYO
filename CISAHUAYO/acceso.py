"""Inicio de sesión del sistema.

Antes se usaba el del admin de Django, que solo deja entrar a personal «staff» y manda siempre a su propio panel. Las
cuentas del sistema (módulo Usuarios) no son de staff: su acceso lo define el rol. Aquí la pantalla es la misma de
siempre (misma ruta, /admin/login/, que los demás módulos usan como `LOGIN_URL`), pero entra cualquier cuenta activa y
se llega a la página que se pidió o, si no hubo ninguna, al inicio del sistema.
"""
from django.conf import settings
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect


class VistaDeAcceso(LoginView):
    template_name = 'registration/login.html'

    def dispatch(self, request, *args, **kwargs):
        # Quien ya tiene sesión y abre esta pantalla pasa directo, salvo que pida el panel de Django sin ser de staff
        # (el admin lo manda aquí: si lo dejáramos pasar, daría vueltas sin fin).
        if request.user.is_authenticated and request.method == 'GET':
            destino = self.get_redirect_url()
            if not destino:
                return redirect(settings.LOGIN_REDIRECT_URL)
            if destino != request.path and not (destino.startswith('/admin/') and not request.user.is_staff):
                return redirect(destino)
        return super().dispatch(request, *args, **kwargs)


acceso = VistaDeAcceso.as_view()
salir = LogoutView.as_view()
