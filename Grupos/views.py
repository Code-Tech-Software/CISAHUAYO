from itertools import groupby

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from Alumnos.academico import ciclo_actual, ciclo_editable, elegir_ciclo
from Alumnos.docentes import con_habilitados
from Alumnos.horarios import con_resumen_de_horario, formatear_duracion
from Alumnos.models import CicloEscolar, Grado, Grupo, Inscripcion, MateriaGrado, NombreGrupo, Profesor
from Alumnos.vinculos import prefetch_vinculos_activos
from CISAHUAYO.permisos import requiere_permisos
from Usuarios.seguridad import ACCION_ALTA, ACCION_BAJA, ACCION_CAMBIO, registrar

from .forms import NombreGrupoForm


def _conteo_por_grupo(consulta):
    return dict(consulta.order_by().values_list('grupo_id').annotate(total=Count('pk')))


# ---------------------------------------------------------------------------
# Los grupos de cada nivel, en tarjetas, y el catálogo de nombres de grupo
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.view_grupo')
def grupo_lista(request):
    ciclo = ciclo_actual()
    inscritos = materias = sin_profesor = {}
    if ciclo:
        inscritos = _conteo_por_grupo(Inscripcion.objects.filter(ciclo=ciclo, activa=True))
        plan = MateriaGrado.objects.filter(ciclo=ciclo, activa=True, materia__activa=True)
        materias = _conteo_por_grupo(plan)
        sin_profesor = _conteo_por_grupo(plan.filter(profesor__isnull=True))

    grupos = Grupo.objects.filter(activo=True, grado__activo=True).select_related('grado', 'nombre').academicos()
    niveles = []
    for nivel, del_nivel in groupby(grupos, key=lambda grupo: grupo.grado.nivel):
        filas = [
            {
                'grupo': grupo, 'inscritos': inscritos.get(grupo.pk, 0),
                'materias': materias.get(grupo.pk, 0), 'sin_profesor': sin_profesor.get(grupo.pk, 0),
            }
            for grupo in del_nivel
        ]
        niveles.append({
            'nombre': dict(Grado.NIVEL_CHOICES)[nivel],
            'filas': filas,
            'inscritos': sum(fila['inscritos'] for fila in filas),
        })

    catalogo = NombreGrupo.objects.annotate(
        en_uso=Count('grupos', filter=Q(grupos__activo=True, grupos__grado__activo=True)),
    ).order_by('-activo', 'orden', 'nombre')
    return render(request, 'grupos/lista.html', {
        'ciclo': ciclo,
        'niveles': niveles,
        'total_grupos': sum(len(nivel['filas']) for nivel in niveles),
        'total_inscritos': sum(nivel['inscritos'] for nivel in niveles),
        'catalogo': list(catalogo),
    })


# ---------------------------------------------------------------------------
# Perfil de un grupo: sus estudiantes, sus materias con su profesor y su horario
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.view_grupo')
def grupo_detalle(request, pk):
    grupo = get_object_or_404(Grupo.objects.select_related('grado', 'nombre'), pk=pk)
    ciclos = list(CicloEscolar.objects.all())
    ciclo = elegir_ciclo(request.GET.get('ciclo', ''), ciclos)
    editable = ciclo_editable(ciclo) and grupo.activo and grupo.grado.activo

    inscripciones = []
    materias = []
    if ciclo:
        inscripciones = list(
            Inscripcion.objects.filter(grupo=grupo, ciclo=ciclo, activa=True).select_related('alumno')
            .prefetch_related(prefetch_vinculos_activos('alumno__'))
            .order_by('alumno__apellido_paterno', 'alumno__apellido_materno', 'alumno__nombre')
        )
        materias = con_habilitados(con_resumen_de_horario(
            MateriaGrado.objects.filter(grupo=grupo, ciclo=ciclo, activa=True).select_related('materia', 'profesor')
            .prefetch_related('horarios').order_by('materia__nombre')
        ))
    minutos = sum(asignacion.minutos for asignacion in materias)

    return render(request, 'grupos/detalle.html', {
        'grupo': grupo,
        'grado': grupo.grado,
        'grupos_del_grado': list(
            grupo.grado.grupos.filter(Q(activo=True) | Q(pk=grupo.pk)).select_related('grado', 'nombre').order_by('nombre__orden', 'nombre__nombre')
        ),
        'ciclos': ciclos,
        'ciclo': ciclo,
        'editable': editable,
        'inscripciones': inscripciones,
        'materias': materias,
        'sin_profesor': sum(1 for asignacion in materias if not asignacion.profesor_id),
        'horas_semanales': formatear_duracion(minutos) if minutos else '',
        'profesores_activos': list(Profesor.objects.filter(estatus='ACTIVO')) if editable else [],
    })


# ---------------------------------------------------------------------------
# Catálogo de nombres de grupo
# ---------------------------------------------------------------------------
def _al_catalogo():
    return redirect(f"{reverse('grupos:lista')}#catalogo")


def _formulario(request, form, nombre=None):
    return render(request, 'grupos/nombre_form.html', {'form': form, 'nombre': nombre, 'es_edicion': nombre is not None})


@requiere_permisos('Alumnos.add_nombregrupo')
def nombre_crear(request):
    form = NombreGrupoForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        if form.is_valid():
            nombre = form.save()
            registrar(request.user, nombre, ACCION_ALTA, f'Nombre de grupo «{nombre}».')
            messages.success(request, f'Se agregó el grupo «{nombre}» al catálogo. Ya puedes usarlo en los grados.')
            return _al_catalogo()
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return _formulario(request, form)


@requiere_permisos('Alumnos.change_nombregrupo')
def nombre_editar(request, pk):
    nombre = get_object_or_404(NombreGrupo, pk=pk)
    anterior = nombre.nombre
    form = NombreGrupoForm(request.POST if request.method == 'POST' else None, instance=nombre)
    if request.method == 'POST':
        if form.is_valid():
            nombre = form.save()
            if nombre.nombre != anterior:
                registrar(request.user, nombre, ACCION_CAMBIO, f'Renombrado: «{anterior}» → «{nombre}».')
            messages.success(request, f'Se actualizó el grupo «{nombre}».')
            return _al_catalogo()
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return _formulario(request, form, nombre)


@require_POST
@requiere_permisos('Alumnos.delete_nombregrupo')
def nombre_baja(request, pk):
    """Baja lógica: el nombre ya no se ofrece al crear grupos; los grupos que ya lo usan lo conservan."""
    nombre = get_object_or_404(NombreGrupo, pk=pk)
    if nombre.activo:
        nombre.activo = False
        nombre.save(update_fields=['activo'])
        registrar(request.user, nombre, ACCION_BAJA, 'Dado de baja del catálogo.')
        en_uso = nombre.grupos.filter(activo=True).count()
        aviso = ''
        if en_uso:
            aviso = ' El grupo que ya lo usa lo conserva.' if en_uso == 1 else f' Los {en_uso} grupos que ya lo usan lo conservan.'
        messages.success(request, f'«{nombre}» ya no se ofrece al crear grupos.{aviso}')
    return _al_catalogo()


@require_POST
@requiere_permisos('Alumnos.change_nombregrupo')
def nombre_reactivar(request, pk):
    nombre = get_object_or_404(NombreGrupo, pk=pk)
    if not nombre.activo:
        nombre.activo = True
        nombre.save(update_fields=['activo'])
        registrar(request.user, nombre, ACCION_CAMBIO, 'Reactivado en el catálogo.')
        messages.success(request, f'«{nombre}» vuelve a ofrecerse al crear grupos.')
    return _al_catalogo()
