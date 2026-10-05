"""Señales de la app de usuarios."""
from django.db import DatabaseError

from .models import PerfilUsuario

SESION_CAMBIO_DE_CONTRASENA = 'debe_cambiar_contrasena'


def recordar_cambio_de_contrasena(sender, request, user, **kwargs):
    """Al iniciar sesión, anota en la sesión si debe elegir una contraseña propia (así el middleware no consulta la base)."""
    if request is None:
        return
    try:
        debe = PerfilUsuario.objects.filter(usuario=user, debe_cambiar_contrasena=True).exists()
    except DatabaseError:   # la tabla aún no existe (migración en curso)
        debe = False
    request.session[SESION_CAMBIO_DE_CONTRASENA] = debe


def crear_roles_iniciales(sender, **kwargs):
    """Después de migrar: crea los roles de arranque (una sola vez; ver Usuarios/iniciales.py)."""
    from django.db import connections

    from .iniciales import crear_roles_iniciales as crear
    from .models import Rol

    using = kwargs.get('using', 'default')
    if using != 'default':
        return
    # Una migración parcial (p. ej. `migrate Alumnos`) puede dejar esta app sin sus tablas
    if Rol._meta.db_table not in connections[using].introspection.table_names():
        return
    crear()
