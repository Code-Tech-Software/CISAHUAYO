"""Quién ve y qué puede hacer cada cuenta con las reuniones con familias (se aplica en el servidor, en cada consulta).

- **Administrador** (`Reuniones.todo`, exclusivo del rol de acceso total): todas las reuniones del colegio.
- **Registrar** (`Reuniones.registrar`, p. ej. recepción): atiende las llamadas de cualquier nivel: registra
  solicitudes, consulta la agenda y la disponibilidad, programa, anota las confirmaciones y los avisos de la familia.
  Ve todas las reuniones, pero no las notas confidenciales (salvo que también tenga `Reuniones.confidencial`).
- **Gestionar** (`Reuniones.gestionar`: Dirección, Coordinación académica y Prefectura): las reuniones de los
  estudiantes de los niveles que tiene asignados: «Niveles que dirige» y «Niveles que coordina» de su ficha de usuario
  y, en una cuenta de prefectura, su alcance de prefectura (niveles, grupos o todo el colegio). Las reprograma, cancela,
  inicia, registra la minuta, los acuerdos y las inasistencias.
- **Participar** (`Reuniones.participar`, p. ej. docentes): solo las reuniones en que participa; confirma su
  disponibilidad. Sin las observaciones internas ni las notas confidenciales.
- **Acompañar** (`Reuniones.acompanar`): puede ser el acompañante directivo de una reunión con docentes, en los niveles
  de su alcance directivo.
- **Confidencial** (`Reuniones.confidencial`): ve y escribe las notas internas de la minuta de las reuniones que gestiona o
  en que participa (nunca por atender las llamadas de todo el colegio).
Los tutores (portal) solo ven las reuniones a las que están invitados (Reuniones/views_portal.py).

Lo que queda fuera responde 404: ocultar un botón no basta.
"""
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.db.models import Exists, OuterRef, Q

from Prefectura.alcance import NINGUNO, NOMBRE_DE_NIVEL, TOTAL, Alcance

from .models import EstudianteEnReunion, ParticipanteReunion, Reunion

PARTICIPAR = 'Reuniones.participar'
REGISTRAR = 'Reuniones.registrar'
GESTIONAR = 'Reuniones.gestionar'
ACOMPANAR = 'Reuniones.acompanar'
CONFIDENCIAL = 'Reuniones.confidencial'
TODO = 'Reuniones.todo'
CONFIGURAR = 'Reuniones.configurar'
DEL_MODULO = (PARTICIPAR, REGISTRAR, GESTIONAR, TODO)
QUE_ATIENDEN = (REGISTRAR, GESTIONAR, TODO)

SIN_NIVELES = ('No tienes niveles educativos asignados para gestionar reuniones. Pide al administrador que te asigne tus '
               '«Niveles que dirige» o «Niveles que coordina» en tu ficha de usuario (o tu alcance de prefectura).')


def usa_reuniones(usuario):
    """Si la cuenta entra al módulo (cualquiera de sus permisos)."""
    return bool(usuario and usuario.is_authenticated and usuario.is_active and any(usuario.has_perm(p) for p in DEL_MODULO))


def atiende_reuniones(usuario):
    """Si la cuenta registra o gestiona reuniones (el panel y la agenda del módulo)."""
    return bool(usuario and usuario.is_authenticated and usuario.is_active and any(usuario.has_perm(p) for p in QUE_ATIENDEN))


# ---------------------------------------------------------------------------
# Alcance directivo (gestionar y acompañar)
# ---------------------------------------------------------------------------
def _niveles_de_ficha(usuario):
    from Usuarios.models import PerfilUsuario
    try:
        fila = PerfilUsuario.objects.filter(usuario=usuario).values('niveles_direccion', 'niveles_bitacora').first() or {}
    except DatabaseError:   # aún no se aplica la migración de Usuarios
        fila = {}
    niveles = set(fila.get('niveles_direccion') or []) | set(fila.get('niveles_bitacora') or [])
    return {n for n in niveles if n in NOMBRE_DE_NIVEL}


def alcance_directivo(usuario):
    """Los niveles (y grupos) cuyas reuniones gestiona o acompaña la cuenta (se calcula una vez por petición)."""
    if not (usuario and usuario.is_authenticated and usuario.is_active):
        return NINGUNO
    guardado = getattr(usuario, '_alcance_reuniones', None)
    if guardado is not None:
        return guardado
    if usuario.has_perm(TODO):
        alcance = TOTAL
    else:
        niveles, grupos, todo = _niveles_de_ficha(usuario), set(), False
        from Prefectura.alcance import alcance_de as alcance_de_prefectura
        from Prefectura.alcance import es_cuenta_de_prefectura
        if es_cuenta_de_prefectura(usuario):
            prefectura = alcance_de_prefectura(usuario)
            todo = prefectura.todo
            niveles |= set(prefectura.niveles)
            grupos |= set(prefectura.grupos)
        alcance = Alcance(restringido=True, todo=todo, niveles=frozenset(niveles), grupos=frozenset(grupos))
    usuario._alcance_reuniones = alcance
    return alcance


def cubre(alcance, inscripcion):
    """Si el alcance incluye al estudiante de esa inscripción (su nivel o su grupo)."""
    if alcance.total:
        return True
    if inscripcion is None:
        return False
    return inscripcion.grado.nivel in alcance.niveles or (inscripcion.grupo_id is not None and inscripcion.grupo_id in alcance.grupos)


def condicion_de_estudiantes(alcance):
    """La condición sobre `Reunion`: alguno de sus estudiantes está en el alcance."""
    if alcance.total:
        return Q()
    if alcance.vacio:
        return Q(pk__in=[])
    dentro = EstudianteEnReunion.objects.filter(reunion=OuterRef('pk')).filter(
        alcance.condicion(nivel='inscripcion__grado__nivel', grupo='inscripcion__grupo'))
    return Q(Exists(dentro))


def inscripciones_de(reunion):
    return [e.inscripcion for e in reunion.estudiantes.select_related('inscripcion__grado').all() if e.inscripcion_id]


def puede_acompanar(usuario, inscripciones):
    """Si la cuenta puede ser el acompañante directivo de una reunión con esos estudiantes: tiene el permiso, está
    activa y su alcance directivo incluye a alguno de ellos."""
    if not (usuario and usuario.is_active and usuario.has_perm(ACOMPANAR)):
        return False
    alcance = alcance_directivo(usuario)
    return alcance.total or any(cubre(alcance, i) for i in inscripciones)


def cuentas_con_permiso(permiso):
    """Las cuentas activas con un permiso de reuniones (por su rol, por permiso suelto o por ser superusuario)."""
    codigo = permiso.split('.')[1]
    return get_user_model().objects.filter(
        Q(is_superuser=True)
        | Q(groups__permissions__codename=codigo, groups__permissions__content_type__app_label='Reuniones')
        | Q(user_permissions__codename=codigo, user_permissions__content_type__app_label='Reuniones'),
        is_active=True,
    ).distinct().order_by('first_name', 'last_name', 'username')


def candidatos_a_acompanar(inscripciones, excluir=()):
    """Las cuentas que pueden acompañar una reunión con esos estudiantes."""
    excluir = {getattr(u, 'pk', u) for u in excluir}
    return [u for u in cuentas_con_permiso(ACOMPANAR) if u.pk not in excluir and puede_acompanar(u, inscripciones)]


# ---------------------------------------------------------------------------
# Qué ve y qué hace cada cuenta
# ---------------------------------------------------------------------------
@dataclass
class Acceso:
    usuario: object

    def __post_init__(self):
        u = self.usuario
        activo = bool(u and u.is_authenticated and u.is_active)
        self.todo = activo and u.has_perm(TODO)
        self.registra = activo and u.has_perm(REGISTRAR)
        self.gestiona = activo and u.has_perm(GESTIONAR)
        self.participa = activo and u.has_perm(PARTICIPAR)
        self.confidencial = activo and u.has_perm(CONFIDENCIAL)
        self.alcance = alcance_directivo(u) if (self.todo or self.gestiona) else NINGUNO

    @property
    def ve_todo(self):
        """Quien ve todas las reuniones: el administrador y quien atiende las llamadas."""
        return self.todo or self.registra

    @property
    def sin_niveles(self):
        return self.gestiona and not self.ve_todo and self.alcance.vacio

    def reuniones(self):
        """Las reuniones que puede consultar."""
        consulta = Reunion.objects.all()
        if self.ve_todo:
            return consulta
        condicion = Q(Exists(ParticipanteReunion.objects.filter(reunion=OuterRef('pk'), usuario=self.usuario, activo=True)))
        if self.gestiona:
            condicion |= condicion_de_estudiantes(self.alcance)
        return consulta.filter(condicion)

    def puede_ver(self, reunion):
        return self.reuniones().filter(pk=reunion.pk).exists()

    def participacion(self, reunion):
        return reunion.participantes.filter(usuario=self.usuario, activo=True).first()

    def gestiona_reunion(self, reunion):
        """Reprogramar, cancelar, iniciar, minuta, acuerdos e inasistencias."""
        if self.todo:
            return True
        if not self.gestiona or self.alcance.vacio:
            return False
        return Reunion.objects.filter(pk=reunion.pk).filter(condicion_de_estudiantes(self.alcance)).exists()

    def atiende_reunion(self, reunion):
        """Programar, participantes, confirmación del tutor y avisos a la familia (quien registra o gestiona)."""
        return self.registra or self.gestiona_reunion(reunion)

    def ve_observaciones(self, reunion):
        """Las observaciones internas de la solicitud: el personal que la atiende, no un docente participante."""
        return self.atiende_reunion(reunion)

    def ve_confidencial(self, reunion):
        """Las notas internas confidenciales de la minuta: solo con el permiso y solo de las reuniones que gestiona (las de
        sus niveles) o en que participa. Atender las llamadas de todo el colegio no da acceso a ellas."""
        if not self.confidencial:
            return False
        return self.gestiona_reunion(reunion) or self.participacion(reunion) is not None
