"""Cuentas de los profesores: una sola cuenta de usuario por profesor y un solo profesor por cuenta.

La **cuenta** (`auth.User` + `PerfilUsuario`) guarda lo del acceso: usuario, contraseña, correo de la cuenta, rol y
permisos. La **ficha del profesor** (`Alumnos.Profesor`) guarda lo del docente. Se unen con `Profesor.usuario`
(OneToOne). Da igual desde dónde se cree la relación (al registrar o editar un profesor con «Dar acceso al sistema», o
al crear un usuario docente): las dos rutas usan estas funciones y terminan igual.

El nombre de la cuenta sale de la ficha del profesor: al vincularlas y cada vez que se edita la ficha, el nombre y los
apellidos de la cuenta se copian de ahí (una sola fuente, para que nunca digan cosas distintas).
"""
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction

from .models import PerfilUsuario, Rol
from .seguridad import asignar_rol, contrasena_temporal, puede_gestionar

Usuario = get_user_model()


def roles_docentes():
    return Rol.objects.filter(es_docente=True, activo=True).select_related('grupo')


def rol_docente_predeterminado(asignables=None):
    """El primer rol para docentes (de los que se pueden asignar, si se indican)."""
    for rol in roles_docentes():
        if asignables is None or rol in asignables:
            return rol
    return None


def profesor_de(usuario):
    """La ficha de profesor de la cuenta, o None (sin consultar dos veces si ya se cargó)."""
    if usuario is None or not getattr(usuario, 'pk', None):
        return None
    try:
        return usuario.profesor
    except ObjectDoesNotExist:
        return None


def cuentas_sin_profesor(actor):
    """Cuentas activas que todavía no son de ningún profesor y que `actor` puede administrar (para vincularlas)."""
    cuentas = Usuario.objects.filter(is_active=True, profesor__isnull=True).order_by('first_name', 'last_name', 'username')
    return [cuenta for cuenta in cuentas if puede_gestionar(actor, cuenta)]


def profesores_sin_cuenta():
    from Alumnos.models import Profesor
    return Profesor.objects.filter(estatus='ACTIVO', usuario__isnull=True)


def sincronizar_nombre(profesor):
    """Copia el nombre y los apellidos de la ficha del profesor a su cuenta (si tiene y si cambiaron)."""
    usuario = profesor.usuario if profesor.usuario_id else None
    if usuario is None:
        return
    nombre, apellidos = profesor.nombre[:150], profesor.apellidos[:150]
    if (usuario.first_name, usuario.last_name) != (nombre, apellidos):
        usuario.first_name, usuario.last_name = nombre, apellidos
        usuario.save(update_fields=['first_name', 'last_name'])


@transaction.atomic
def vincular(profesor, usuario):
    """Une la ficha del profesor con la cuenta. Ninguna de las dos puede estar ya unida a otra."""
    if profesor.usuario_id and profesor.usuario_id != usuario.pk:
        raise ValidationError(f'{profesor} ya tiene una cuenta de acceso.')
    otro = profesor_de(usuario)
    if otro is not None and otro.pk != profesor.pk:
        raise ValidationError(f'La cuenta «{usuario.username}» ya es de {otro}.')
    profesor.usuario = usuario
    profesor.save(update_fields=['usuario', 'modificado'])
    sincronizar_nombre(profesor)
    perfil = PerfilUsuario.de(usuario)
    if not perfil.cargo:
        perfil.cargo = 'Docente'
        perfil.save(update_fields=['cargo', 'modificado'])
    return profesor


def puede_desactivar_su_cuenta(actor, profesor):
    """¿`actor` puede desactivar la cuenta del profesor al darlo de baja? (permiso, rango y que no sea la suya)."""
    from .seguridad import es_ultimo_administrador

    cuenta = profesor.usuario if profesor.usuario_id else None
    return (
        cuenta is not None and cuenta.is_active and cuenta.pk != actor.pk
        and actor.has_perm('auth.delete_user') and puede_gestionar(actor, cuenta) and not es_ultimo_administrador(cuenta)
    )


@transaction.atomic
def desvincular(profesor):
    """Separa la ficha de su cuenta. No borra ni desactiva nada: cada una sigue existiendo por su lado."""
    usuario = profesor.usuario if profesor.usuario_id else None
    profesor.usuario = None
    profesor.save(update_fields=['usuario', 'modificado'])
    return usuario


@transaction.atomic
def crear_cuenta(profesor, *, username, email, rol, contrasena=''):
    """Crea la cuenta del profesor, le da el rol y la vincula. Devuelve (cuenta, contraseña en claro).

    Sin contraseña se genera una temporal. En ambos casos la persona deberá elegir una propia al entrar por primera vez.
    """
    contrasena_en_claro = contrasena or contrasena_temporal()
    usuario = Usuario(username=username, email=email or '', is_active=True)
    usuario.set_password(contrasena_en_claro)
    usuario.save()
    perfil = PerfilUsuario.de(usuario)
    perfil.telefono = (profesor.telefono or '')[:10]
    perfil.cargo = 'Docente'
    perfil.debe_cambiar_contrasena = True
    perfil.save()
    asignar_rol(usuario, rol)
    vincular(profesor, usuario)
    return usuario, contrasena_en_claro
