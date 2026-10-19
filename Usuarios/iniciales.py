"""Roles con los que arranca el sistema.

Se crean una sola vez, la primera vez que se migra (si ya existe un rol de acceso total, no se vuelve a tocar nada).
Solo «Administrador» es un rol del sistema; los demás son un punto de partida razonable que se puede editar, copiar o
desactivar desde «Roles y permisos». Los permisos son los de Usuarios/catalogo.py.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction

from .catalogo import con_requisitos, permisos_de_modulos, reservados_para
from .models import PerfilUsuario, Rol
from .seguridad import objetos_de_permisos

ESCOLARES = ('alumnos', 'tutores', 'profesores', 'inscripciones', 'ciclos', 'grados', 'grupos', 'materias', 'horarios', 'periodos', 'asistencias',
             'calificaciones', 'bitacoras', 'conducta', 'mensajes', 'comunicados', 'retiros', 'reuniones')
# Reuniones con familias: quienes gestionan y acompañan las de sus niveles (dirección, coordinación y prefectura)
REUNIONES_DIRECTIVAS = {'Reuniones.participar', 'Reuniones.gestionar', 'Reuniones.acompanar', 'Reuniones.confidencial'}


def _direccion():
    return permisos_de_modulos(*ESCOLARES) | {'auth.view_user', 'Usuarios.view_rol'}


def _control_escolar():
    return (
        permisos_de_modulos('alumnos', 'tutores', 'inscripciones')
        | permisos_de_modulos('profesores', 'ciclos', 'grados', 'grupos', 'materias', 'horarios', 'periodos', solo=('ver',))
        | {'Alumnos.view_asistenciageneral', 'Alumnos.view_asistenciamateria', 'Alumnos.view_justificacion'}
        | {'Conducta.view_registroconducta', 'Conducta.add_registroconducta', 'Conducta.change_registroconducta'}
        | permisos_de_modulos('calificaciones', solo=('ver',))
        | {'Mensajes.usar', 'Mensajes.contactar_familias'}
        | {'Reuniones.registrar'}
    )


def _docente():
    return (
        permisos_de_modulos('alumnos', 'tutores', 'grados', 'grupos', 'materias', 'horarios', 'periodos', solo=('ver',))
        | {'Alumnos.view_asistenciamateria', 'Alumnos.change_asistenciamateria', 'Alumnos.view_justificacion'}
        | {'Calificaciones.capturar', 'Calificaciones.cerrar'}
        | {'Bitacoras.registrar'}
        | {'Mensajes.usar'}
        | {'Comunicados.recibir'}
        | {'Reuniones.participar'}
    )


def _coordinacion():
    # Sus niveles se eligen en su ficha de usuario («Niveles que coordina»)
    return (
        permisos_de_modulos('alumnos', 'grados', 'grupos', 'materias', 'horarios', 'periodos', solo=('ver',))
        | {'Bitacoras.consultar_todas', 'Bitacoras.registrar_todas'}
        | {'Mensajes.usar'}
        | {'Comunicados.recibir', 'Comunicados.enviar'}   # a los niveles que coordina
        | REUNIONES_DIRECTIVAS
    )


def _recepcion():
    return {
        'Alumnos.view_alumno', 'Alumnos.add_asistenciageneral', 'Alumnos.view_asistenciageneral',
        'Alumnos.view_justificacion', 'Mensajes.usar', 'Reuniones.registrar',
    }


def _prefectura():
    # Corregir lo de otros y los casos cerrados (Prefectura.corregir_otros) lo concede el administrador si quiere
    return ((permisos_de_modulos('prefectura') - {'Prefectura.corregir_otros'}) | {'Bitacoras.consultar_todas', 'Bitacoras.registrar_todas'}
            | {'Mensajes.usar', 'Mensajes.contactar_familias'}
            | {'Retiros.consultar', 'Retiros.confirmar'}   # retiros de su alcance
            | REUNIONES_DIRECTIVAS)


# nombre, descripción, color, permisos
PREDETERMINADOS = (
    ('Dirección', 'Todos los módulos escolares. Consulta usuarios y roles, pero no los administra.', 1, _direccion),
    ('Control escolar', 'Altas y cambios de estudiantes, tutores e inscripciones; consulta del resto.', 2, _control_escolar),
    ('Docente', 'Consulta estudiantes, grados, materias y horarios; pasa lista, captura las calificaciones y lleva la bitácora de sus clases.', 4, _docente),
    ('Coordinación académica', 'Bitácoras por grupo de los niveles que coordina (se eligen en su ficha); consulta estudiantes, grupos, materias y horarios.', 1, _coordinacion),
    ('Recepción', 'Pantalla de entrada y asistencia del día; consulta las justificaciones.', 5, _recepcion),
    ('Prefectura', 'Estudiantes, asistencia, conducta y seguimiento de los niveles o grupos que se le asignen.', 6, _prefectura),
)

# Roles cuyas cuentas son de profesores (al crearlas se registra o vincula su ficha de profesor)
ROLES_DOCENTES = {'Docente'}
# Roles de prefectura (sus cuentas solo ven los niveles o grupos que se les asignen)
ROLES_PREFECTURA = {'Prefectura'}


def _crear_rol(nombre, descripcion, tono, permisos=(), **extra):
    grupo, _ = Group.objects.get_or_create(name=nombre)
    rol, _ = Rol.objects.get_or_create(grupo=grupo, defaults={'descripcion': descripcion, 'tono': tono, **extra})
    if permisos:
        # Justificar faltas: solo el administrador (lo tiene por ser de acceso total) y prefectura
        permisos = con_requisitos(permisos) - reservados_para(extra.get('es_prefectura', False))
        grupo.permissions.set(objetos_de_permisos(permisos))
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
        _crear_rol(nombre, descripcion, tono, permisos(), es_docente=nombre in ROLES_DOCENTES, es_prefectura=nombre in ROLES_PREFECTURA)

    # Quien ya era superusuario pasa a tener el rol de administrador
    for usuario in get_user_model().objects.filter(is_superuser=True):
        usuario.groups.add(administrador.grupo)
        PerfilUsuario.de(usuario)
    return True
