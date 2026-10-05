from django.apps import AppConfig
from django.db.models.signals import post_migrate


class UsuariosConfig(AppConfig):
    name = 'Usuarios'

    def ready(self):
        from django.contrib.auth.signals import user_logged_in

        from . import signals

        user_logged_in.connect(signals.recordar_cambio_de_contrasena, dispatch_uid='usuarios.cambio_de_contrasena')
        # Se crean los roles iniciales después de migrar, cuando ya existen todos los permisos de los modelos
        post_migrate.connect(signals.crear_roles_iniciales, sender=self, dispatch_uid='usuarios.roles_iniciales')
