"""Quién ve qué eventos de la agenda (se aplica en el servidor, en cada consulta).

- El administrador (permiso Agenda.gestionar, reservado) ve y gestiona todos.
- El personal consulta los eventos de todo el colegio y los de sus niveles: los que ya tiene por sus relaciones en el
  sistema (docente, dirección de nivel, coordinación de bitácoras, niveles para comunicados y para retiros, alcance de
  prefectura; Comunicados/alcance.py · niveles_asignados). Sin niveles, solo los de todo el colegio.
- Un tutor, los de los niveles en que tiene hijos inscritos en el ciclo actual (vínculo activo).
- Un estudiante, los de su nivel (su inscripción del ciclo actual).
Los de todo el colegio se guardan una sola vez: quien tiene varios niveles los ve una sola vez.
"""
from dataclasses import dataclass, field

from django.db import DatabaseError

from Alumnos.models import ORDEN_NIVELES, Inscripcion

from .models import COLEGIO, NOMBRE_DE_ALCANCE, EventoAgenda

GESTIONAR = 'Agenda.gestionar'
SOLO_COLEGIO = 'COLEGIO'


@dataclass(frozen=True)
class Vista:
    todos: bool = False
    niveles: frozenset = field(default_factory=frozenset)
    gestiona: bool = False

    @property
    def niveles_en_orden(self):
        return [n for n in ORDEN_NIVELES if self.todos or n in self.niveles]

    def eventos(self):
        """Los eventos que puede consultar (los de todo el colegio, una vez)."""
        consulta = EventoAgenda.objects.all()
        if self.todos:
            return consulta
        return consulta.filter(alcance__in=[*self.niveles, COLEGIO])

    def puede_ver(self, evento):
        return self.todos or evento.alcance == COLEGIO or evento.alcance in self.niveles

    def filtrar(self, consulta, filtro):
        """«Todos los niveles» (''), un nivel (sus eventos y los de todo el colegio) o solo los de todo el colegio.
        Un nivel que no le corresponde se ignora (no amplía lo que puede ver)."""
        if filtro == SOLO_COLEGIO:
            return consulta.filter(alcance=COLEGIO)
        if filtro in self.niveles_en_orden:
            return consulta.filter(alcance__in=[filtro, COLEGIO])
        return consulta

    def opciones(self):
        """Las opciones de la lista de niveles: todos, cada nivel que le corresponde y solo los de todo el colegio."""
        return [('', 'Todos los niveles'), *[(n, NOMBRE_DE_ALCANCE[n]) for n in self.niveles_en_orden], (SOLO_COLEGIO, 'Solo eventos de todo el colegio')]


def _niveles_validos(niveles):
    return frozenset(n for n in niveles or () if n in ORDEN_NIVELES)


def de_usuario(usuario):
    """La vista de una cuenta del sistema."""
    if usuario.has_perm(GESTIONAR):
        return Vista(todos=True, gestiona=True)
    from Comunicados.alcance import niveles_asignados
    from Usuarios.models import PerfilUsuario
    niveles = set(niveles_asignados(usuario))
    try:
        niveles |= set(PerfilUsuario.objects.filter(usuario=usuario).values_list('niveles_retiros', flat=True).first() or [])
    except DatabaseError:
        pass
    return Vista(niveles=_niveles_validos(niveles))


def _niveles_vigentes(inscripciones):
    return _niveles_validos(inscripciones.filter(activa=True, ciclo__activo=True).values_list('grado__nivel', flat=True))


def de_tutor(tutor):
    """Los niveles en que tiene hijos inscritos (vínculo activo, estudiante activo, ciclo actual)."""
    return Vista(niveles=_niveles_vigentes(Inscripcion.objects.filter(
        alumno__tutores_relacionados__tutor=tutor, alumno__tutores_relacionados__activo=True, alumno__estatus='ACTIVO')))


def de_estudiante(alumno):
    return Vista(niveles=_niveles_vigentes(Inscripcion.objects.filter(alumno=alumno)))
