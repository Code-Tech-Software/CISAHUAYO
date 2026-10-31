"""Qué horarios consulta cada cuenta (pedido del 2026-10-30). Se aplica en el servidor: ocultar un botón no basta.

- **Perfil Docente** (un rol marcado para docentes, `Usuarios.Rol.es_docente`): solo sus clases, las asignaciones en que su
  ficha de profesor imparte esa materia en ese grupo, reunidas en «Mi horario» (views_docente.py). No ve el horario
  completo de un grupo o un grado ni los bloques de otros docentes, y no crea, edita ni quita horarios. Quién es sale de
  la sesión: ningún parámetro del navegador lo cambia.
- **Los demás roles** (administración, dirección, coordinación…) siguen con lo que les dan sus permisos, aunque su cuenta
  también tenga ficha de profesor.

Lo que queda fuera responde 404. Las pantallas de otros módulos que listan materias con su horario (grupo, grado, materia,
tablero de asignaciones, perfil de un profesor) pasan por `sin_horarios_ajenos`.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied
from django.db.models import F, Q

from Alumnos.asistencia_docente import asignaciones_del_profesor
from Alumnos.clases import EN_EFECTO
from Alumnos.models import CicloEscolar, MateriaGrado, orden_de_nivel
from Usuarios.docentes import profesor_de
from Usuarios.seguridad import rol_de


def solo_sus_clases(usuario):
    """Si la cuenta es del perfil Docente: un rol para docentes o, sin rol, una ficha de profesor (se calcula una vez por
    petición)."""
    if usuario is None or not getattr(usuario, 'is_authenticated', False) or usuario.is_superuser:
        return False
    guardado = getattr(usuario, '_solo_sus_clases', None)
    if guardado is None:
        rol = rol_de(usuario)
        guardado = rol.es_docente and not rol.acceso_total if rol is not None else profesor_de(usuario) is not None
        usuario._solo_sus_clases = guardado
    return guardado


def no_docentes(vista):
    """Para el perfil Docente los horarios son de consulta: aunque su rol tuviera el permiso, no crea, edita ni quita. Va
    debajo de `requiere_permisos`."""
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        if solo_sus_clases(request.user):
            raise PermissionDenied
        return vista(request, *args, **kwargs)
    return envoltura


def asignaciones_del_docente(usuario, ciclo):
    """Sus asignaciones explícitas del ciclo, en orden escolar: sin las de grados ocultos (salvo en un ciclo cerrado) y sin
    los grupos de clase de un bloque que sigue en preparación. Un grupo de clase cuenta solo si la cuenta es su docente."""
    profesor = profesor_de(usuario)
    if profesor is None or ciclo is None:
        return MateriaGrado.objects.none()
    return (
        asignaciones_del_profesor(profesor, ciclo).filter(Q(clase__isnull=True) | Q(clase__bloque__estado__in=EN_EFECTO))
        .order_by(orden_de_nivel('grado__nivel'), 'grado__numero', F('grupo__nombre__orden').asc(nulls_last=True), 'grupo__nombre_de_clase', 'materia__nombre')
    )


def ciclos_del_docente(usuario):
    """Los ciclos que puede consultar: aquellos en que tiene clases, y el actual."""
    profesor = profesor_de(usuario)
    con_clases = MateriaGrado.objects.filter(profesor=profesor, activa=True).values('ciclo') if profesor else []
    return list(CicloEscolar.objects.filter(Q(pk__in=con_clases) | Q(activo=True)))


def sin_horarios_ajenos(asignaciones, usuario):
    """Para las pantallas que listan materias de varios docentes: a una cuenta del perfil Docente se le quita el horario de
    las asignaciones que no son suyas (`horario_ajeno`). Las asignaciones deben traer ya su resumen de horario."""
    if not solo_sus_clases(usuario):
        return asignaciones
    profesor = profesor_de(usuario)
    for asignacion in asignaciones:
        if profesor is None or asignacion.profesor_id != profesor.pk:
            asignacion.lineas, asignacion.bloques, asignacion.minutos, asignacion.duracion = [], 0, 0, ''
            asignacion.horario_ajeno = True
    return asignaciones
