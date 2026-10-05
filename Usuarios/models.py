"""Roles y perfil de los usuarios del sistema.

Un **rol** es un grupo de permisos de Django (`auth.Group`) con nombre, descripción y color. Es el grupo quien guarda los
permisos, así que cualquier cambio en un rol llega al instante a todos los usuarios que lo tienen, sin tocar a ninguno
(Django calcula los permisos de cada usuario a partir de sus grupos en cada petición). Cada usuario tiene un solo rol.

El **perfil** guarda lo que el modelo de usuario de Django no tiene (teléfono, cargo) y la marca de «debe cambiar su
contraseña» que se activa al crear la cuenta o al restablecerla.
"""
from django.conf import settings
from django.contrib.auth.models import Group
from django.db import models
from django.urls import reverse


class Rol(models.Model):
    TONOS = [(1, 'Turquesa'), (2, 'Amarillo'), (3, 'Guinda'), (4, 'Azul'), (5, 'Verde'), (6, 'Gris')]

    grupo = models.OneToOneField(Group, on_delete=models.CASCADE, related_name='rol', verbose_name='grupo de permisos')
    descripcion = models.CharField('descripción', max_length=200, blank=True)
    tono = models.PositiveSmallIntegerField('color', choices=TONOS, default=1)
    activo = models.BooleanField(
        default=True,
        help_text='Un rol desactivado no se puede asignar a usuarios nuevos. No se borra: conserva su historial.',
    )
    es_sistema = models.BooleanField(
        'rol del sistema', default=False,
        help_text='Los roles del sistema no se pueden editar ni desactivar.',
    )
    acceso_total = models.BooleanField(
        default=False,
        help_text='Quien tiene este rol puede hacer todo en el sistema (y entrar a la administración de Django).',
    )
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'rol'
        verbose_name_plural = 'roles'
        ordering = ['-acceso_total', 'grupo__name']

    def __str__(self):
        return self.nombre

    @property
    def nombre(self):
        return self.grupo.name

    def get_absolute_url(self):
        return reverse('roles:detalle', args=[self.pk])


class PerfilUsuario(models.Model):
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='perfil')
    telefono = models.CharField('teléfono', max_length=10, blank=True)
    cargo = models.CharField(max_length=80, blank=True, help_text='Puesto o función en el colegio.')
    debe_cambiar_contrasena = models.BooleanField(
        'debe cambiar su contraseña', default=False,
        help_text='Se activa al crear la cuenta o restablecer la contraseña: en su siguiente acceso deberá elegir una propia.',
    )
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'perfil de usuario'
        verbose_name_plural = 'perfiles de usuario'
        default_permissions = ()   # los permisos de las cuentas son los de auth.User

    def __str__(self):
        return f'Perfil de {self.usuario}'

    @classmethod
    def de(cls, usuario):
        """El perfil del usuario; se crea vacío si aún no tiene (cuentas hechas con createsuperuser o en el admin)."""
        perfil, _ = cls.objects.get_or_create(usuario=usuario)
        return perfil
