from django.apps import AppConfig


class MensajesConfig(AppConfig):
    name = 'Mensajes'
    verbose_name = 'Mensajes'

    def ready(self):
        from django.contrib.auth.signals import user_logged_out

        from .push import olvidar_navegador

        # Al cerrar sesión en el sistema, ese navegador deja de recibir las notificaciones push de esa persona (en los
        # portales: CISAHUAYO/portales.cerrar_sesion)
        user_logged_out.connect(lambda sender, request, **kwargs: olvidar_navegador(request), weak=False,
                                dispatch_uid='mensajes.push.cerrar_sesion')
