"""Ayudantes compartidos por las pruebas de las secciones académicas (ciclos, grados e inscripciones)."""
import itertools
from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from Alumnos.models import (
    Alumno,
    CicloEscolar,
    ConfiguracionAsistencia,
    Grado,
    HorarioMateria,
    Inscripcion,
    Materia,
    MateriaGrado,
    Profesor,
    Tutor,
    TutorAlumno,
)

# Las pruebas corren con DEBUG=False: almacenamiento simple (sin manifiesto ni Cloudinary) y un hasher rápido.
PRUEBAS = override_settings(
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
)

_contador = itertools.count(1)


def hoy():
    return timezone.localdate()


def crear_alumno(**cambios):
    n = next(_contador)
    datos = {
        'referencia': f'R{n:04d}', 'nombre': 'Luis', 'apellido_paterno': 'Pérez', 'apellido_materno': 'Mora',
        'curp': f'CURP{n:014d}', 'sexo': 'M', 'fecha_nacimiento': date(2015, 5, 5), 'grupo_sanguineo': 'A+',
        'domicilio': 'Av. Juárez 45', 'colonia': 'Centro', 'ciudad': 'Sahuayo', 'estado': 'Michoacán',
        'cp': '59000', 'contrasena': 'hash',
    }
    datos.update(cambios)
    return Alumno.objects.create(**datos)


def crear_tutor(**cambios):
    datos = {'nombre': 'Rosa', 'apellido_paterno': 'Mora', 'telefono': '3531112233'}
    datos.update(cambios)
    return Tutor.objects.create(**datos)


def crear_profesor(**cambios):
    datos = {'nombre': 'Marta', 'apellido_paterno': 'Rangel', 'apellido_materno': 'Soto', 'telefono': '3534445566'}
    datos.update(cambios)
    return Profesor.objects.create(**datos)


def vincular(tutor, alumno, **cambios):
    datos = {'parentesco': 'MADRE', 'activo': True}
    datos.update(cambios)
    return TutorAlumno.objects.create(tutor=tutor, alumno=alumno, **datos)


def crear_ciclo(nombre, desde, hasta, activo=False):
    """`desde` y `hasta` son días respecto a hoy (negativos = pasado)."""
    return CicloEscolar.objects.create(
        nombre=nombre, fecha_inicio=hoy() + timedelta(days=desde), fecha_fin=hoy() + timedelta(days=hasta), activo=activo,
    )


def ciclo_actual_de_prueba(nombre='2026-2027'):
    return crear_ciclo(nombre, -60, 300, activo=True)


def ciclo_proximo_de_prueba(nombre='2027-2028'):
    return crear_ciclo(nombre, 330, 660)


def ciclo_cerrado_de_prueba(nombre='2025-2026'):
    return crear_ciclo(nombre, -430, -70)


def crear_grado(nivel='PRIMARIA', numero=1, **cambios):
    return Grado.objects.create(nivel=nivel, numero=numero, **cambios)


def inscribir(alumno, ciclo, grado, **cambios):
    return Inscripcion.objects.create(alumno=alumno, ciclo=ciclo, grado=grado, **cambios)


class BaseTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser('admin', 'admin@example.com', 'x')
        cls.sin_permisos = User.objects.create_user('visitante', password='x')

    def setUp(self):
        self.client.force_login(self.admin)

    def con_permisos(self, *codigos):
        """Inicia sesión con un usuario nuevo que solo tiene los permisos indicados (codename)."""
        self.usuarios = getattr(self, 'usuarios', 0) + 1
        usuario = get_user_model().objects.create_user(f'usuario{self.usuarios}', password='x')
        usuario.user_permissions.add(*Permission.objects.filter(codename__in=codigos))
        self.client.force_login(usuario)
        return usuario


# ---------------------------------------------------------------------------
# Asistencias
# ---------------------------------------------------------------------------
def lunes():
    """El lunes más reciente (hoy, si es lunes): un día de clases que cae dentro del ciclo actual de prueba."""
    return hoy() - timedelta(days=hoy().weekday())


def momento(hora, minuto=0, fecha=None):
    """Una hora de ese día (por omisión el lunes de prueba), con zona horaria."""
    return timezone.make_aware(datetime.combine(fecha or lunes(), time(hora, minuto)))


def materia_en_grado(clave, grado, ciclo, dia=0, inicio=(8, 0), fin=(9, 0), **cambios):
    """Asigna la materia al grado en el ciclo, con un bloque de horario (sin horario si `inicio` es None)."""
    materia, _ = Materia.objects.get_or_create(clave=clave, defaults={'nombre': clave.title()})
    asignacion = MateriaGrado.objects.create(materia=materia, grado=grado, ciclo=ciclo, **cambios)
    if inicio:
        HorarioMateria.objects.create(materia_grado=asignacion, dia_semana=dia, hora_inicio=time(*inicio), hora_fin=time(*fin))
    return asignacion


def inscribir_antes(alumno, ciclo, grado, **cambios):
    """Inscribe desde el inicio del ciclo: así el alumno ya debía asistir a los días pasados que se prueban."""
    cambios.setdefault('fecha_inscripcion', ciclo.fecha_inicio)
    return inscribir(alumno, ciclo, grado, **cambios)


class BaseAsistenciaTestCase(BaseTestCase):
    """Un grado con tres materias el lunes (8:00–9:00, 9:00–10:00 y 11:00–12:00), una escuela que abre a las 8:00 con
    10 minutos de tolerancia y un alumno con credencial inscrito en él.

    Con `hora = (h, m)` el reloj queda fijo en el lunes de prueba a esa hora (las vistas usan «hoy» y «ahora»).
    """

    hora = None

    def setUp(self):
        super().setUp()
        cache.clear()
        ConfiguracionAsistencia.cargar()
        self.ciclo = ciclo_actual_de_prueba()
        self.grado = crear_grado('PRIMARIA', 4)
        self.mat = materia_en_grado('MAT', self.grado, self.ciclo, inicio=(8, 0), fin=(9, 0))
        self.esp = materia_en_grado('ESP', self.grado, self.ciclo, inicio=(9, 0), fin=(10, 0))
        self.cie = materia_en_grado('CIE', self.grado, self.ciclo, inicio=(11, 0), fin=(12, 0))
        self.alumno = crear_alumno(uid='AB12CD34')
        self.inscripcion = inscribir_antes(self.alumno, self.ciclo, self.grado)
        self._reloj = None
        if self.hora:
            self.fijar_ahora(*self.hora)

    def fijar_ahora(self, hora, minuto=0, fecha=None):
        """Detiene el reloj en esa hora del lunes de prueba (o de la fecha dada)."""
        if self._reloj:
            self._reloj.stop()
        self._reloj = patch('django.utils.timezone.now', return_value=momento(hora, minuto, fecha))
        self._reloj.start()
        self.addCleanup(self._reloj.stop)

    def estados_de_materias(self, inscripcion=None, fecha=None):
        from Alumnos.models import AsistenciaMateria

        registros = AsistenciaMateria.objects.filter(inscripcion=inscripcion or self.inscripcion, fecha=fecha or lunes())
        return {r.materia_grado.materia.clave: r.estado for r in registros}


# ---------------------------------------------------------------------------
# Usuarios y roles
# ---------------------------------------------------------------------------
def crear_rol(nombre, permisos=(), **extra):
    """Un rol nuevo con esos permisos («app.codename»; se añade lo que cada uno necesita, como al guardarlo desde la matriz)."""
    from Usuarios.iniciales import _crear_rol
    return _crear_rol(nombre, extra.pop('descripcion', ''), extra.pop('tono', 1), set(permisos), **extra)


def crear_usuario(username, rol=None, contrasena='x', **cambios):
    """Una cuenta con ese rol (sin ser de staff), lista para iniciar sesión."""
    from Usuarios.models import PerfilUsuario
    from Usuarios.seguridad import asignar_rol
    cambios.setdefault('first_name', username.capitalize())
    cambios.setdefault('last_name', 'Prueba')
    usuario = get_user_model().objects.create_user(username, password=contrasena, **cambios)
    PerfilUsuario.de(usuario)
    if rol is not None:
        asignar_rol(usuario, rol)
    return usuario
