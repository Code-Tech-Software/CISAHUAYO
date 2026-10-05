"""Roles con los que arranca el sistema.

Se crean una sola vez, la primera vez que se migra (si ya existe un rol de acceso total, no se vuelve a tocar nada).
Solo «Administrador» es un rol del sistema; los demás son un punto de partida razonable que se puede editar, copiar o
desactivar desde «Roles y permisos». Los permisos son los de Usuarios/catalogo.py.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction

from .catalogo import con_requisitos, permisos_de_modulos
from .models import PerfilUsuario, Rol
from .seguridad import objetos_de_permisos

ESCOLARES = ('alumnos', 'tutores', 'profesores', 'inscripciones', 'ciclos', 'grados', 'materias', 'horarios', 'asistencias')


def _direccion():
    return permisos_de_modulos(*ESCOLARES) | {'auth.view_user', 'Usuarios.view_rol'}


def _control_escolar():
    return (
        permisos_de_modulos('alumnos', 'tutores', 'inscripciones')
        | permisos_de_modulos('profesores', 'ciclos', 'grados', 'materias', 'horarios', solo=('ver',))
        | {'Alumnos.view_asistenciageneral', 'Alumnos.view_asistenciamateria', 'Alumnos.view_justificacion',
           'Alumnos.add_justificacion', 'Alumnos.change_justificacion', 'Alumnos.delete_justificacion'}
    )


def _docente():
    return (
        permisos_de_modulos('alumnos', 'tutores', 'grados', 'materias', 'horarios', solo=('ver',))
        | {'Alumnos.view_asistenciamateria', 'Alumnos.change_asistenciamateria', 'Alumnos.view_justificacion'}
    )


def _recepcion():
    return {
        'Alumnos.view_alumno', 'Alumnos.add_asistenciageneral', 'Alumnos.view_asistenciageneral',
        'Alumnos.view_justificacion', 'Alumnos.add_justificacion',
    }


# nombre, descripción, color, permisos
PREDETERMINADOS = (
    ('Dirección', 'Todos los módulos escolares. Consulta usuarios y roles, pero no los administra.', 1, _direccion),
    ('Control escolar', 'Altas y cambios de alumnos, tutores e inscripciones; consulta del resto y justificaciones.', 2, _control_escolar),
    ('Docente', 'Consulta alumnos, grados, materias y horarios, y pasa lista en sus clases.', 4, _docente),
    ('Recepción', 'Pantalla de entrada, asistencia del día y justificaciones.', 5, _recepcion),
)


def _crear_rol(nombre, descripcion, tono, permisos=(), **extra):
    grupo, _ = Group.objects.get_or_create(name=nombre)
    rol, _ = Rol.objects.get_or_create(grupo=grupo, defaults={'descripcion': descripcion, 'tono': tono, **extra})
    if permisos:
        grupo.permissions.set(objetos_de_permisos(con_requisitos(permisos)))
    return rol


@transaction.atomic
def crear_roles_iniciales():
    """Crea «Administrador» y los roles de arranque. Devuelve True si hizo algo."""
    if Rol.objects.filter(acceso_total=True).exists():
        return False

    administrador = _crear_rol(
        'Administrador', 'Acceso completo al sistema, incluidos usuarios y roles. No se puede modificar.', 3,
        es_sistema=True, acceso_total=True,
    )
    for nombre, descripcion, tono, permisos in PREDETERMINADOS:
        _crear_rol(nombre, descripcion, tono, permisos())

    # Quien ya era superusuario pasa a tener el rol de administrador
    for usuario in get_user_model().objects.filter(is_superuser=True):
        usuario.groups.add(administrador.grupo)
        PerfilUsuario.de(usuario)
    return True
