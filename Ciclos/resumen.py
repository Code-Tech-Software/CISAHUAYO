"""Lo que muestra el detalle de un ciclo escolar (2026-10-26): estudiantes por grado y por grupo, días de clase por
nivel, comparación con el ciclo anterior y la lista de preparación del ciclo."""
from collections import defaultdict
from dataclasses import dataclass

from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from Alumnos.asistencias import NOMBRES_DE_NIVEL, dias_de_clases
from Alumnos.models import (
    ORDEN_NIVELES, CicloEscolar, DiaNoLectivo, Grado, Grupo, HorarioMateria, Inscripcion, MateriaGrado, Periodo, Recreo,
)


def _grados_activos():
    return list(Grado.objects.filter(activo=True).academicos())


def _grupos_activos(grados):
    return list(
        Grupo.objects.filter(grado__in=grados, activo=True).select_related('grado', 'nombre')
        .order_by('nombre__orden', 'nombre__nombre')
    )


# ---------------------------------------------------------------------------
# Estudiantes por grado y por grupo
# ---------------------------------------------------------------------------
def por_grado_y_grupo(ciclo):
    """Estudiantes inscritos en cada grado del ciclo, con el desglose por grupo, en orden escolar."""
    conteos = defaultdict(lambda: {'activas': 0, 'bajas': 0})
    for fila in (
        Inscripcion.objects.filter(ciclo=ciclo).values('grado_id', 'grupo_id')
        .annotate(activas=Count('pk', filter=Q(activa=True)), bajas=Count('pk', filter=Q(activa=False)))
    ):
        for clave in ((fila['grado_id'], None), (fila['grado_id'], fila['grupo_id'])):
            conteos[clave]['activas'] += fila['activas']
            conteos[clave]['bajas'] += fila['bajas']

    con_inscripciones = {grado_id for grado_id, grupo_id in conteos if grupo_id is None}
    grados = Grado.objects.filter(Q(activo=True) | Q(pk__in=con_inscripciones)).academicos()
    grupos_inscritos = {grupo_id for _, grupo_id in conteos if grupo_id}
    grupos = defaultdict(list)
    for grupo in (
        Grupo.objects.filter(Q(activo=True) | Q(pk__in=grupos_inscritos), grado__in=grados)
        .select_related('grado', 'nombre').order_by('nombre__orden', 'nombre__nombre')
    ):
        grupos[grupo.grado_id].append({'grupo': grupo, **conteos[(grupo.grado_id, grupo.pk)]})

    filas = [{'grado': grado, 'grupos': grupos[grado.pk], **conteos[(grado.pk, None)]} for grado in grados]
    maximo = max((fila['activas'] for fila in filas), default=0)
    for fila in filas:
        fila['porcentaje'] = round(fila['activas'] * 100 / maximo) if maximo else 0
    return filas


# ---------------------------------------------------------------------------
# Días de clase
# ---------------------------------------------------------------------------
def dias_de_clase_por_nivel(ciclo, hoy=None):
    """Por nivel con grados activos: los días de clase del ciclo (sin días sin clases de ese nivel ni fines de semana
    sin horario) y cuántos van hasta hoy."""
    hoy = hoy or timezone.localdate()
    niveles = set(Grado.objects.filter(activo=True).values_list('nivel', flat=True))
    filas = []
    for nivel in ORDEN_NIVELES:
        if nivel not in niveles:
            continue
        total = dias_de_clases(ciclo.fecha_inicio, ciclo.fecha_fin, ciclo, nivel)
        van = sum(1 for fecha in total if fecha <= hoy)
        filas.append({
            'nivel': NOMBRES_DE_NIVEL[nivel], 'total': len(total), 'van': van,
            'porcentaje': round(van * 100 / len(total)) if total else 0,
        })
    return filas


# ---------------------------------------------------------------------------
# Comparación con el ciclo anterior
# ---------------------------------------------------------------------------
def comparacion_con_anterior(ciclo):
    """Inscritos contra el ciclo anterior, cuántos de ese ciclo se reinscribieron en este y cuántas bajas hubo en cada
    uno. None si no hay ciclo anterior con inscripciones."""
    anterior = (
        CicloEscolar.objects.filter(fecha_inicio__lt=ciclo.fecha_inicio, inscripciones__isnull=False)
        .distinct().order_by('-fecha_inicio').first()
    )
    if anterior is None:
        return None

    def conteos(c):
        return Inscripcion.objects.filter(ciclo=c).aggregate(
            inscritos=Count('pk', filter=Q(activa=True)), bajas=Count('pk', filter=Q(activa=False)),
        )

    este, previo = conteos(ciclo), conteos(anterior)
    del_anterior = Inscripcion.objects.filter(ciclo=anterior, activa=True).values('alumno_id')
    reinscritos = Inscripcion.objects.filter(ciclo=ciclo, activa=True, alumno_id__in=del_anterior).count()
    return {
        'anterior': anterior,
        'inscritos': este['inscritos'], 'inscritos_antes': previo['inscritos'],
        'diferencia': este['inscritos'] - previo['inscritos'],
        'reinscritos': reinscritos,
        'porcentaje_reinscritos': round(reinscritos * 100 / previo['inscritos']) if previo['inscritos'] else 0,
        'nuevos': este['inscritos'] - reinscritos,
        'bajas': este['bajas'], 'bajas_antes': previo['bajas'],
    }


# ---------------------------------------------------------------------------
# Preparación del ciclo
# ---------------------------------------------------------------------------
@dataclass
class Paso:
    titulo: str
    listo: bool
    detalle: str
    url: str = ''
    enlace: str = ''


def _plural(cantidad, singular, plural=None):
    return f'{cantidad} {singular if cantidad == 1 else (plural or singular + "s")}'


def preparacion(ciclo, usuario, origen_plan=None):
    """Lo que un ciclo necesita antes de empezar, cada cosa con su estado (listo o pendiente) y su acceso si la cuenta
    puede entrar ahí: grupos, plan de materias, horarios, profesores, periodos por nivel, configuración de
    calificaciones, recesos y días sin clases."""
    from Calificaciones.models import ConfiguracionEvaluacion
    from Calificaciones.reglas import VER_CONFIG

    grados = _grados_activos()
    grupos = _grupos_activos(grados)
    plan = MateriaGrado.objects.filter(ciclo=ciclo, activa=True, grupo__in=grupos)
    pasos = []

    def paso(titulo, listo, detalle, url='', permiso=True, enlace='Revisar'):
        pasos.append(Paso(titulo, listo, detalle, url if permiso else '', enlace))

    sin_grupo = [grado for grado in grados if not any(g.grado_id == grado.pk for g in grupos)]
    paso('Grupos', bool(grupos) and not sin_grupo,
         f'Faltan grupos en {", ".join(str(g) for g in sin_grupo[:3])}{"…" if len(sin_grupo) > 3 else ""}.' if sin_grupo
         else (f'{_plural(len(grupos), "grupo")} en {_plural(len(grados), "grado")}.' if grupos else 'Todavía no hay grados.'),
         reverse('grupos:lista'), usuario.has_perm('Alumnos.view_grupo'))

    con_plan = set(plan.values_list('grupo_id', flat=True))
    sin_plan = [grupo for grupo in grupos if grupo.pk not in con_plan]
    if origen_plan is not None and not con_plan:
        url_plan, permiso_plan, enlace = (f"{reverse('materias:copiar')}?origen={origen_plan.pk}&destino={ciclo.pk}",
                                          usuario.has_perm('Alumnos.add_materiagrado'), f'Copiar de {origen_plan}')
    else:
        url_plan, permiso_plan, enlace = reverse('materias:lista'), usuario.has_perm('Alumnos.view_materia'), 'Revisar'
    paso('Plan de materias', bool(grupos) and not sin_plan,
         f'{_plural(len(sin_plan), "grupo")} sin materias.' if sin_plan
         else f'{_plural(plan.count(), "materia asignada", "materias asignadas")} a los grupos.',
         url_plan, permiso_plan, enlace)

    horarios = f"{reverse('horarios:lista')}?ciclo={ciclo.pk}"
    sin_horario = plan.exclude(pk__in=HorarioMateria.objects.values('materia_grado_id')).count()
    total_plan = plan.count()
    paso('Horarios', total_plan > 0 and not sin_horario,
         f'{_plural(sin_horario, "materia")} sin horario.' if sin_horario
         else ('Todas las materias tienen horario.' if total_plan else 'Primero arma el plan de materias.'),
         horarios, usuario.has_perm('Alumnos.view_horariomateria'))

    sin_profesor = plan.filter(profesor__isnull=True).count()
    paso('Profesores asignados', total_plan > 0 and not sin_profesor,
         f'{_plural(sin_profesor, "materia")} sin profesor.' if sin_profesor
         else ('Todas las materias tienen profesor.' if total_plan else 'Primero arma el plan de materias.'),
         f"{reverse('asignaciones:tablero')}?ciclo={ciclo.pk}", usuario.has_perm('Alumnos.view_materiagrado'))

    niveles = [nivel for nivel in ORDEN_NIVELES if any(g.nivel == nivel for g in grados)]
    con_periodos = set(Periodo.objects.filter(ciclo=ciclo).values_list('nivel', flat=True))
    sin_periodos = [NOMBRES_DE_NIVEL[nivel] for nivel in niveles if nivel not in con_periodos]
    paso('Periodos de evaluación', bool(niveles) and not sin_periodos,
         f'Sin periodos: {", ".join(sin_periodos)}.' if sin_periodos else 'Cada nivel tiene sus periodos.',
         f"{reverse('periodos:lista')}?ciclo={ciclo.pk}", usuario.has_perm('Alumnos.view_periodo'))

    materias = set(plan.values_list('materia_id', flat=True))
    configuradas = set(
        ConfiguracionEvaluacion.objects.filter(ciclo=ciclo, materia_id__in=materias, estado=ConfiguracionEvaluacion.ACTIVA)
        .values_list('materia_id', flat=True)
    )
    sin_configurar = len(materias - configuradas)
    paso('Configuración de calificaciones', bool(materias) and not sin_configurar,
         f'{_plural(sin_configurar, "materia")} sin configuración activa.' if sin_configurar
         else ('Todas las materias están configuradas.' if materias else 'Primero arma el plan de materias.'),
         f"{reverse('calificaciones:configuracion')}?ciclo={ciclo.pk}", usuario.has_perm(VER_CONFIG))

    con_receso = set(Recreo.objects.filter(ciclo=ciclo).values_list('grupo_id', flat=True))
    sin_receso = [grupo for grupo in grupos if grupo.pk in con_plan and grupo.pk not in con_receso]
    paso('Recesos', bool(con_plan) and not sin_receso,
         f'{_plural(len(sin_receso), "grupo")} sin receso.' if sin_receso
         else ('Todos los grupos tienen receso.' if con_plan else 'Primero arma el plan de materias.'),
         horarios, usuario.has_perm('Alumnos.view_horariomateria'))

    dias = DiaNoLectivo.objects.filter(fecha__range=(ciclo.fecha_inicio, ciclo.fecha_fin)).values('fecha').distinct().count()
    paso('Días sin clases', dias > 0,
         f'{_plural(dias, "día registrado", "días registrados")}.' if dias else 'Todavía no se carga el calendario del ciclo.',
         '#dias-sin-clases', usuario.has_perm('Alumnos.view_cicloescolar'), 'Ver')
    return pasos
