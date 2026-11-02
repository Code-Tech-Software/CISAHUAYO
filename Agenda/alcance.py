"""Quién ve qué eventos de la agenda y quién los gestiona (se aplica en el servidor, en cada consulta).

- El administrador (permiso Agenda.gestionar, reservado) ve y gestiona todos.
- El personal consulta los eventos de todo el colegio y los de sus niveles: los que ya tiene por sus relaciones en el
  sistema (docente, dirección de nivel, coordinación de bitácoras, niveles para comunicados y para retiros, alcance de
  prefectura; Comunicados/alcance.py · niveles_asignados). Sin niveles, solo los de todo el colegio. Con el permiso
  Agenda.gestionar_nivel (se concede desde Roles), también registra, corrige, cancela y elimina los eventos que son
  solo de sus niveles (nunca los de todo el colegio).
- Un tutor, los de los niveles en que tiene hijos inscritos en el ciclo actual (vínculo activo) que sean para las
  familias; si el evento es solo de algunos grados o grupos, solo si alguno de sus hijos está en ellos.
- Un estudiante, igual con su propia inscripción, en los eventos que sean para los estudiantes.
Los de todo el colegio se guardan una sola vez: quien tiene varios niveles los ve una sola vez.
"""
from dataclasses import dataclass, field

from django.db import DatabaseError
from django.db.models import Q

from Alumnos.models import ORDEN_NIVELES, Grado, Inscripcion

from .models import COLEGIO, NOMBRE_DE_ALCANCE, VARIOS, EventoAgenda, NivelEvento

GESTIONAR = 'Agenda.gestionar'
GESTIONAR_NIVEL = 'Agenda.gestionar_nivel'
SOLO_COLEGIO = 'COLEGIO'
FAMILIAS, ESTUDIANTES = 'familias', 'estudiantes'


@dataclass(frozen=True)
class Vista:
    todos: bool = False
    niveles: frozenset = field(default_factory=frozenset)
    gestiona_todo: bool = False
    gestiona_niveles: frozenset = field(default_factory=frozenset)
    publico: str = ''                                       # '' (personal), FAMILIAS o ESTUDIANTES
    grados: frozenset = field(default_factory=frozenset)    # en un portal: los grados y grupos de sus estudiantes
    grupos: frozenset = field(default_factory=frozenset)

    @property
    def gestiona(self):
        return self.gestiona_todo or bool(self.gestiona_niveles)

    @property
    def niveles_en_orden(self):
        return [n for n in ORDEN_NIVELES if self.todos or n in self.niveles]

    @property
    def niveles_que_gestiona(self):
        return [n for n in ORDEN_NIVELES if self.gestiona_todo or n in self.gestiona_niveles]

    def eventos(self):
        """Los eventos que puede consultar (los de todo el colegio, una vez)."""
        consulta = EventoAgenda.objects.all()
        if self.todos:
            return consulta
        consulta = consulta.filter(_de_niveles(self.niveles))
        if self.publico == FAMILIAS:
            consulta = consulta.filter(para_familias=True)
        elif self.publico == ESTUDIANTES:
            consulta = consulta.filter(para_estudiantes=True)
        if self.publico:
            consulta = consulta.filter(_de_cursos(self.grados, self.grupos))
        return consulta

    def puede_ver(self, evento):
        return self.todos or self.eventos().filter(pk=evento.pk).exists()

    def puede_gestionar(self, evento):
        """Corregir, cancelar o eliminar ese evento: el administrador, cualquiera; con la gestión de sus niveles, uno que
        sea solo de esos niveles."""
        if self.gestiona_todo:
            return True
        return bool(self.gestiona_niveles) and evento.alcance != COLEGIO and set(evento.niveles_del_evento) <= self.gestiona_niveles

    def filtrar(self, consulta, filtro):
        """«Todos los niveles» (''), un nivel (sus eventos y los de todo el colegio) o solo los de todo el colegio.
        Un nivel que no le corresponde se ignora (no amplía lo que puede ver)."""
        if filtro == SOLO_COLEGIO:
            return consulta.filter(alcance=COLEGIO)
        if filtro in self.niveles_en_orden:
            return consulta.filter(_de_niveles({filtro}))
        return consulta

    def opciones(self):
        """Las opciones de la lista de niveles: todos, cada nivel que le corresponde y solo los de todo el colegio."""
        return [('', 'Todos los niveles'), *[(n, NOMBRE_DE_ALCANCE[n]) for n in self.niveles_en_orden], (SOLO_COLEGIO, 'Solo eventos de todo el colegio')]

    def cursos(self):
        """[(nivel, [(clave, nombre)])] de la lista «Grado o grupo»: «g12» es un grado completo y «r34», un grupo. En un
        portal, los de sus estudiantes; el personal, los de sus niveles."""
        from Alumnos.models import Grupo
        if self.publico:
            grados = Grado.objects.filter(pk__in=self.grados)
            grupos = Grupo.objects.filter(pk__in=self.grupos)
        else:
            grados = Grado.objects.disponibles().filter(nivel__in=self.niveles_en_orden)
            grupos = Grupo.objects.filter(grado__in=grados, activo=True)
        por_grado = {}
        for grupo in grupos.select_related('grado', 'nombre'):
            por_grado.setdefault(grupo.grado_id, []).append(grupo)
        resultado = {}
        for grado in sorted(grados, key=lambda g: (ORDEN_NIVELES.index(g.nivel), g.numero)):
            opciones = resultado.setdefault(grado.nivel, [])
            propios = sorted(por_grado.get(grado.pk, []), key=lambda g: str(g))
            if len(propios) != 1 or not self.publico:
                opciones.append((f'g{grado.pk}', f'{grado} (todo el grado)' if len(propios) > 1 else str(grado)))
            if len(propios) > 1 or self.publico:
                opciones += [(f'r{grupo.pk}', str(grupo)) for grupo in propios]
        return [(NOMBRE_DE_ALCANCE[nivel], opciones) for nivel, opciones in resultado.items() if opciones]

    def curso_pedido(self, clave):
        """(grado, grupo) de la clave «g12» o «r34» si está entre sus opciones; si no, (None, None)."""
        from Alumnos.models import Grupo
        clave = str(clave or '')
        if not any(clave == valor for _, opciones in self.cursos() for valor, _ in opciones):
            return None, None
        if clave.startswith('g'):
            return Grado.objects.filter(pk=clave[1:]).first(), None
        grupo = Grupo.objects.select_related('grado').filter(pk=clave[1:]).first()
        return (grupo.grado, grupo) if grupo else (None, None)


def _de_niveles(niveles):
    """Los de todo el colegio y los que incluyen alguno de esos niveles (de uno solo o de varios)."""
    niveles = sorted(niveles)
    return (Q(alcance=COLEGIO) | Q(alcance__in=niveles)
            | Q(alcance=VARIOS, pk__in=NivelEvento.objects.filter(nivel__in=niveles).values('evento')))


def _de_cursos(grados, grupos):
    """Los que no son solo de algunos grados o grupos, y los de esos grados o grupos."""
    return (Q(por_grupos=False)
            | Q(pk__in=EventoAgenda.grados.through.objects.filter(grado_id__in=grados).values('eventoagenda_id'))
            | Q(pk__in=EventoAgenda.grupos.through.objects.filter(grupo_id__in=grupos).values('eventoagenda_id')))


def filtrar_por_curso(consulta, grado, grupo=None):
    """Lo que ve ese grado (o ese grupo): lo de su nivel y de todo el colegio que no es solo de otros grados o grupos."""
    grupos = [grupo.pk] if grupo is not None else list(grado.grupos.values_list('pk', flat=True))
    return consulta.filter(_de_niveles({grado.nivel})).filter(_de_cursos([grado.pk], grupos))


def _niveles_validos(niveles):
    return frozenset(n for n in niveles or () if n in ORDEN_NIVELES)


def niveles_del_personal(usuario):
    from Comunicados.alcance import niveles_asignados
    from Usuarios.models import PerfilUsuario
    niveles = set(niveles_asignados(usuario))
    try:
        niveles |= set(PerfilUsuario.objects.filter(usuario=usuario).values_list('niveles_retiros', flat=True).first() or [])
    except DatabaseError:
        pass
    return _niveles_validos(niveles)


def de_usuario(usuario):
    """La vista de una cuenta del sistema."""
    if usuario.has_perm(GESTIONAR):
        return Vista(todos=True, gestiona_todo=True)
    niveles = niveles_del_personal(usuario)
    return Vista(niveles=niveles, gestiona_niveles=niveles if usuario.has_perm(GESTIONAR_NIVEL) else frozenset())


def _vigentes(inscripciones):
    return inscripciones.filter(activa=True, ciclo__activo=True)


def _vista_de_portal(inscripciones, publico):
    filas = list(_vigentes(inscripciones).values_list('grado__nivel', 'grado_id', 'grupo_id'))
    return Vista(niveles=_niveles_validos(nivel for nivel, _, _ in filas), publico=publico,
                 grados=frozenset(g for _, g, _ in filas), grupos=frozenset(r for _, _, r in filas if r))


def de_tutor(tutor):
    """Los niveles, grados y grupos en que tiene hijos inscritos (vínculo activo, estudiante activo, ciclo actual)."""
    return _vista_de_portal(Inscripcion.objects.filter(
        alumno__tutores_relacionados__tutor=tutor, alumno__tutores_relacionados__activo=True, alumno__estatus='ACTIVO'), FAMILIAS)


def de_estudiante(alumno):
    return _vista_de_portal(Inscripcion.objects.filter(alumno=alumno), ESTUDIANTES)
