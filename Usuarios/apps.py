from django.apps import AppConfig
from django.conf import settings
from django.db.models.signals import post_migrate, pre_save


class UsuariosConfig(AppConfig):
    name = 'Usuarios'

    def ready(self):
        from django.contrib.auth.signals import user_logged_in

        from . import contrasenas, signals

        user_logged_in.connect(signals.recordar_cambio_de_contrasena, dispatch_uid='usuarios.cambio_de_contrasena')
        # Si la contraseña de una cuenta cambia por otro camino, su copia consultable se borra (Usuarios/contrasenas.py)
        pre_save.connect(contrasenas.olvidar_si_cambia, sender=settings.AUTH_USER_MODEL, dispatch_uid='usuarios.contrasena_visible')
        # Se crean los roles iniciales después de migrar, cuando ya existen todos los permisos de los modelos
        post_migrate.connect(signals.crear_roles_iniciales, sender=self, dispatch_uid='usuarios.roles_iniciales')
