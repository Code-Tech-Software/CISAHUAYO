"""Reglas de seguridad de usuarios y roles: permisos efectivos, asignación de rol y quién puede gestionar a quién.

Principios:
- Los permisos viven en el rol (un grupo de Django); el usuario solo apunta a su rol. Cambiar un rol cambia a todos.
- Nadie puede conceder lo que no tiene: un usuario solo asigna roles cuyos permisos él también posee (y solo un
  superusuario asigna el rol de acceso total), y solo gestiona a quien no tenga más poder que él.
- Siempre debe quedar al menos un administrador activo, y nadie se quita a sí mismo el acceso.
"""
from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Q

from Alumnos.utils import generar_contrasena

from .catalogo import TODOS
from .models import PerfilUsuario, Rol

Usuario = get_user_model()
ACCION_ALTA, ACCION_CAMBIO, ACCION_BAJA = ADDITION, CHANGE, DELETION


# ---------------------------------------------------------------------------
# Permisos
# ---------------------------------------------------------------------------
def codigos(permisos):
    """Los permisos de Django como cadenas «app.codename». Usa el caché de tipos de contenido: no hace una consulta por permiso."""
    return {f'{ContentType.objects.get_for_id(p.content_type_id).app_label}.{p.codename}' for p in permisos}


def permisos_de_rol(rol):
    """Los permisos que concede un rol (todos los del catálogo si es de acceso total)."""
    if rol is None:
        return set()
    if rol.acceso_total:
        return set(TODOS)
    return codigos(rol.grupo.permissions.select_related('content_type'))


def permisos_efectivos(usuario):
    """Todo lo que el usuario puede hacer (un superusuario, todo el catálogo)."""
    if not usuario.is_active:
        return set()
    if usuario.is_superuser:
        return set(TODOS)
    return set(usuario.get_all_permissions())


def permisos_de_cuenta(usuario):
    """Los permisos de la cuenta aunque esté desactivada (Django los oculta en cuentas inactivas): sirve para saber
    cuánto poder tendría al reactivarla."""
    if usuario.is_superuser:
        return set(TODOS)
    # Con los grupos y permisos ya cargados (prefetch_related) no consulta nada
    permisos = codigos(usuario.user_permissions.all())
    for grupo in usuario.groups.all():
        permisos |= codigos(grupo.permissions.all())
    return permisos


def objetos_de_permisos(codigos_pedidos):
    """Los `Permission` de Django que corresponden a esas cadenas «app.codename» (los que existan)."""
    if not codigos_pedidos:
        return Permission.objects.none()
    condicion = Q()
    for codigo in codigos_pedidos:
        app, _, codename = codigo.partition('.')
        condicion |= Q(content_type__app_label=app, codename=codename)
    return Permission.objects.filter(condicion).select_related('content_type')


# ---------------------------------------------------------------------------
# Rol de un usuario
# ---------------------------------------------------------------------------
def rol_de(usuario):
    """El rol del usuario: el de su grupo; un superusuario sin rol cuenta como administrador."""
    if usuario is None or not getattr(usuario, 'pk', None):
        return None
    for grupo in usuario.groups.all():
        rol = getattr(grupo, 'rol', None)
        if rol is not None:
            rol.grupo = grupo   # ya lo tenemos: evita una consulta más al pedir el nombre
            return rol
    if usuario.is_superuser:
        return Rol.objects.filter(acceso_total=True).select_related('grupo').first()
    return None


@transaction.atomic
def asignar_rol(usuario, rol):
    """Deja al usuario con ese único rol. El acceso total activa también `is_superuser` e `is_staff` (admin de Django)."""
    otros = Group.objects.filter(user=usuario, rol__isnull=False).exclude(pk=rol.grupo_id)
    if otros:
        usuario.groups.remove(*otros)
    usuario.groups.add(rol.grupo)
    usuario.is_superuser = usuario.is_staff = rol.acceso_total
    usuario.save(update_fields=['is_superuser', 'is_staff'])


def puede_asignar(actor, rol):
    """¿`actor` puede dar este rol? Solo roles activos cuyos permisos él ya tiene; el de acceso total, solo un superusuario."""
    if not rol.activo:
        return False
    if actor.is_superuser:
        return True
    return not rol.acceso_total and permisos_de_rol(rol) <= permisos_efectivos(actor)


def roles_asignables(actor):
    return [rol for rol in Rol.objects.select_related('grupo') if puede_asignar(actor, rol)]


def puede_gestionar(actor, objetivo, permisos_del_actor=None):
    """¿`actor` puede editar, desactivar o restablecer a `objetivo`? No si tiene más poder que él.

    En un listado se calcula una vez `permisos_efectivos(actor)` y se pasa aquí para no repetirlo por fila."""
    if actor.is_superuser:
        return True
    if objetivo.is_superuser:
        return False
    if permisos_del_actor is None:
        permisos_del_actor = permisos_efectivos(actor)
    return permisos_de_cuenta(objetivo) <= permisos_del_actor


def es_ultimo_administrador(usuario):
    """¿Es el único administrador activo? Si lo es, no se le puede quitar el acceso ni desactivarlo."""
    return (
        usuario.is_superuser and usuario.is_active
        and not Usuario.objects.filter(is_superuser=True, is_active=True).exclude(pk=usuario.pk).exists()
    )


def contrasena_temporal():
    return generar_contrasena(10)


def nombre_de(usuario):
    """«Nombre Apellido»; sin nombre registrado, el usuario."""
    return usuario.get_full_name().strip() or usuario.get_username()


def iniciales_de(usuario):
    partes = (usuario.get_full_name() or usuario.get_username()).split()
    return ''.join(parte[0] for parte in partes[:2]).upper() or '?'


# ---------------------------------------------------------------------------
# Bitácora (el historial de cambios del admin de Django)
# ---------------------------------------------------------------------------
def registrar(actor, objeto, accion, mensaje):
    """Anota quién hizo qué sobre un usuario o un rol; se muestra en su perfil y en el historial del admin."""
    LogEntry.objects.create(
        user_id=actor.pk,
        content_type=ContentType.objects.get_for_model(objeto),
        object_id=str(objeto.pk),
        object_repr=str(objeto)[:200],
        action_flag=accion,
        change_message=mensaje,
    )


def historial(objeto, limite=12):
    return list(
        LogEntry.objects.filter(content_type=ContentType.objects.get_for_model(objeto), object_id=str(objeto.pk))
        .select_related('user').order_by('-action_time', '-pk')[:limite]
    )


def perfil_de(usuario):
    return PerfilUsuario.de(usuario)
