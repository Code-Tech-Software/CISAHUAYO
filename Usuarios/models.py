"""Roles y perfil de los usuarios del sistema.

Un **rol** es un grupo de permisos de Django (`auth.Group`) con nombre, descripción y color. Es el grupo quien guarda los
permisos, así que cualquier cambio en un rol llega al instante a todos los usuarios que lo tienen, sin tocar a ninguno
(Django calcula los permisos de cada usuario a partir de sus grupos en cada petición). Cada usuario tiene un solo rol.

El **perfil** guarda lo que el modelo de usuario de Django no tiene (teléfono, cargo), la marca de «debe cambiar su
contraseña» que se activa al crear la cuenta o al restablecerla y cómo quiere ver el sistema (tema de color y menú
lateral, en Ajustes).
"""
from django.conf import settings
from django.contrib.auth.models import Group
from django.db import models
from django.urls import reverse

from CISAHUAYO import temas


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
    es_docente = models.BooleanField(
        'rol para docentes', default=False,
        help_text='Las cuentas con este rol son de profesores: al crearlas se registra o se vincula su ficha de profesor.',
    )
    es_prefectura = models.BooleanField(
        'rol de prefectura', default=False,
        help_text='Las cuentas con este rol solo ven a los estudiantes de los niveles o grupos que se les asignen (o de todo '
                  'el colegio, si se concede expresamente). Sin alcance asignado no ven a ningún estudiante.',
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
        help_text='Si está activo, en su siguiente acceso deberá elegir una contraseña propia. Es opcional: se pide al '
                  'crear la cuenta o al restablecer su contraseña.',
    )
    # Contraseña consultable (pedido del 2026-10-15, como en estudiantes y tutores): la que asigna o restablece quien
    # administra, legible solo para un administrador. Nunca la que elige la propia persona: si la contraseña cambia por
    # otro camino, se borra sola (Usuarios/contrasenas.py).
    contrasena_visible = models.CharField('contraseña consultable', max_length=128, blank=True, editable=False)
    tema =models.CharField('tema de color', max_length=20, choices=temas.opciones, default=temas.PREDETERMINADO)
    menu_lateral = models.CharField('menú lateral', max_length=10, choices=temas.MENUS, default=temas.MENU_CLARO)
    # Dirección de nivel (pedido del 2026-10-14): quien puede aprobar suspensiones y medidas solo resuelve las de los
    # niveles que dirige (el administrador, todas)
    niveles_direccion = models.JSONField(
        'niveles que dirige', default=list, blank=True,
        help_text='Autoriza las suspensiones y medidas de estos niveles (si su rol tiene el permiso de aprobar).',
    )
    # Coordinación (Bitácoras por grupo, 2026-10-14): quien consulta o registra en las bitácoras de todos los grupos
    # solo llega a los de estos niveles; sin niveles, a todo el colegio. Prefectura usa su propio alcance.
    niveles_bitacora = models.JSONField(
        'niveles que coordina', default=list, blank=True,
        help_text='Limita las bitácoras de todos los grupos a estos niveles (vacío: todo el colegio).',
    )
    # Comunicados (2026-10-16): niveles a los que puede enviar, además de los que ya tiene por ser docente, dirigir o
    # coordinar un nivel, o por su alcance de prefectura (Comunicados/alcance.py). Sin ninguno, no envía.
    niveles_comunicados = models.JSONField(
        'niveles para comunicados', default=list, blank=True,
        help_text='Puede enviar comunicados a los tutores, estudiantes y profesores de estos niveles (si su rol tiene el permiso).',
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
