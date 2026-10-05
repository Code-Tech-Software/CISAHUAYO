import csv
from itertools import groupby

from django.contrib import messages
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from Alumnos.academico import ciclo_actual, ciclo_editable, elegir_ciclo, materias_por_asignar, siguiente_grado
from Alumnos.horarios import con_resumen_de_horario, formatear_duracion
from Alumnos.models import CicloEscolar, Grado, Inscripcion, MateriaGrado, Profesor
from Alumnos.utils import proteger_celda_csv
from Alumnos.vinculos import prefetch_vinculos_activos
from CISAHUAYO.permisos import requiere_permisos

from .forms import GradoForm


def _conteos(modelo, ciclo, **filtros):
    """{id de grado: cantidad} de los registros del ciclo; vacío si no hay ciclo."""
    if ciclo is None:
        return {}
    filas = modelo.objects.filter(ciclo=ciclo, **filtros).order_by().values_list('grado_id').annotate(total=Count('pk'))
    return dict(filas)


# ---------------------------------------------------------------------------
# Listado: los grados por nivel, en orden escolar
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.view_grado')
def grado_lista(request):
    viendo_bajas = request.GET.get('estado') == 'BAJA'
    ciclo = ciclo_actual()
    inscritos = _conteos(Inscripcion, ciclo, activa=True)
    materias = _conteos(MateriaGrado, ciclo, activa=True)

    grados = Grado.objects.filter(activo=not viendo_bajas).academicos()
    niveles = []
    for nivel, del_nivel in groupby(grados, key=lambda grado: grado.nivel):
        filas = [
            {'grado': grado, 'inscritos': inscritos.get(grado.pk, 0), 'materias': materias.get(grado.pk, 0)}
            for grado in del_nivel
        ]
        niveles.append({
            'nombre': dict(Grado.NIVEL_CHOICES)[nivel],
            'filas': filas,
            'inscritos': sum(fila['inscritos'] for fila in filas),
        })

    conteos = dict(Grado.objects.order_by().values_list('activo').annotate(total=Count('pk')))
    return render(request, 'grados/lista.html', {
        'niveles': niveles,
        'ciclo': ciclo,
        'viendo_bajas': viendo_bajas,
        'total_activos': conteos.get(True, 0),
        'total_bajas': conteos.get(False, 0),
        'total_inscritos': sum(nivel['inscritos'] for nivel in niveles),
    })


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
def _formulario(request, form, grado=None):
    inscripciones = Inscripcion.objects.filter(grado=grado).count() if grado else 0
    return render(request, 'grados/form.html', {
        'form': form,
        'grado': grado,
        'es_edicion': grado is not None,
        'total_inscripciones': inscripciones,
    })


@requiere_permisos('Alumnos.add_grado')
def grado_crear(request):
    form = GradoForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        if form.is_valid():
            grado = form.save()
            messages.success(request, f'El grado {grado} fue registrado.')
            return redirect('grados:lista')
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return _formulario(request, form)


@requiere_permisos('Alumnos.change_grado')
def grado_editar(request, pk):
    grado = get_object_or_404(Grado, pk=pk)
    form = GradoForm(request.POST if request.method == 'POST' else None, instance=grado)
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            messages.success(request, f'El grado {grado} se actualizó.')
            return redirect('grados:lista')
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return _formulario(request, form, grado)


# ---------------------------------------------------------------------------
# Perfil del grado: el listado de alumnos de un ciclo (con un solo grupo por grado, es la lista del salón)
# ---------------------------------------------------------------------------
def _ciclo_elegido(request, ciclos):
    return elegir_ciclo(request.GET.get('ciclo', ''), ciclos)


def _alumnos_del_grado(grado, ciclo):
    if ciclo is None:
        return Inscripcion.objects.none()
    return (
        Inscripcion.objects.filter(grado=grado, ciclo=ciclo, activa=True)
        .select_related('alumno')
        .order_by('alumno__apellido_paterno', 'alumno__apellido_materno', 'alumno__nombre')
    )


@requiere_permisos('Alumnos.view_grado')
def grado_detalle(request, pk):
    grado = get_object_or_404(Grado, pk=pk)
    ciclos = list(CicloEscolar.objects.all())
    ciclo = _ciclo_elegido(request, ciclos)

    # El tutor principal de cada alumno se trae solo para los alumnos de este grado
    inscripciones = list(_alumnos_del_grado(grado, ciclo).prefetch_related(prefetch_vinculos_activos('alumno__')))

    # Plan de materias del grado en el ciclo (con las quitadas, marcadas) y su resumen de horario
    materias = con_resumen_de_horario(
        MateriaGrado.objects.filter(grado=grado, ciclo=ciclo).select_related('materia', 'profesor')
        .prefetch_related('horarios').order_by('materia__nombre')
        if ciclo else MateriaGrado.objects.none()
    )
    materias_vigentes = [asignacion for asignacion in materias if asignacion.activa]
    minutos = sum(asignacion.minutos for asignacion in materias_vigentes)
    editable = ciclo_editable(ciclo)
    historial = (
        Inscripcion.objects.filter(grado=grado).order_by()
        .values('ciclo_id', 'ciclo__nombre', 'ciclo__fecha_inicio', 'ciclo__activo')
        .annotate(activas=Count('pk', filter=Q(activa=True)), bajas=Count('pk', filter=Q(activa=False)))
        .order_by('-ciclo__fecha_inicio')
    )
    siguiente = siguiente_grado(grado, list(Grado.objects.filter(activo=True).academicos()))
    inscritos_actuales = (
        Inscripcion.objects.filter(grado=grado, activa=True, ciclo__activo=True).count() if grado.activo else 0
    )

    return render(request, 'grados/detalle.html', {
        'grado': grado,
        'ciclos': ciclos,
        'ciclo': ciclo,
        'inscripciones': inscripciones,
        'materias': materias,
        'total_materias': len(materias_vigentes),
        'horas_semanales': formatear_duracion(minutos) if minutos else '',
        'plan_editable': editable and grado.activo,
        'profesores_activos': list(Profesor.objects.filter(estatus='ACTIVO')) if editable and grado.activo else [],
        'sin_profesor': sum(1 for asignacion in materias_vigentes if not asignacion.profesor_id),
        'materias_por_asignar': list(materias_por_asignar(grado, ciclo)) if ciclo and editable and grado.activo else [],
        'historial': list(historial),
        'siguiente': siguiente,
        'inscritos_actuales': inscritos_actuales,
        'esta_de_baja': not grado.activo,
    })


# ---------------------------------------------------------------------------
# Baja lógica
# ---------------------------------------------------------------------------
@require_POST
@requiere_permisos('Alumnos.delete_grado')
def grado_baja(request, pk):
    """Baja lógica: el grado deja de ofrecerse al inscribir, pero conserva sus inscripciones y su historial."""
    grado = get_object_or_404(Grado, pk=pk)
    if not grado.activo:
        messages.info(request, f'El grado {grado} ya estaba dado de baja.')
        return redirect('grados:lista')

    grado.activo = False
    grado.save(update_fields=['activo'])
    messages.success(
        request,
        f'El grado {grado} fue dado de baja. Sus inscripciones se conservan y puedes reactivarlo desde el filtro «Bajas».',
    )
    return redirect('grados:lista')


@require_POST
@requiere_permisos('Alumnos.change_grado')
def grado_reactivar(request, pk):
    grado = get_object_or_404(Grado, pk=pk)
    if not grado.activo:
        grado.activo = True
        grado.save(update_fields=['activo'])
        messages.success(request, f'El grado {grado} fue reactivado.')
    return redirect('grados:lista')


# ---------------------------------------------------------------------------
# Exportación: lista de alumnos del grado
# ---------------------------------------------------------------------------
@require_GET
@requiere_permisos('Alumnos.view_grado')
def grado_exportar(request, pk):
    grado = get_object_or_404(Grado, pk=pk)
    ciclo = _ciclo_elegido(request, list(CicloEscolar.objects.all()))
    inscripciones = _alumnos_del_grado(grado, ciclo)

    respuesta = HttpResponse(content_type='text/csv; charset=utf-8')
    nombre = f'{grado.get_nivel_display()}-{grado.numero}-{ciclo or "sin-ciclo"}'.lower().replace(' ', '-')
    respuesta['Content-Disposition'] = f'attachment; filename="grado-{nombre}-{timezone.localdate():%Y-%m-%d}.csv"'
    respuesta.write('﻿')  # para que Excel reconozca los acentos
    escritor = csv.writer(respuesta)
    escritor.writerow(['Referencia', 'Apellido paterno', 'Apellido materno', 'Nombre', 'Fecha de nacimiento', 'Fecha de inscripción'])
    for inscripcion in inscripciones.iterator(chunk_size=500):
        alumno = inscripcion.alumno
        escritor.writerow([proteger_celda_csv(valor) for valor in [
            alumno.referencia, alumno.apellido_paterno, alumno.apellido_materno, alumno.nombre,
            f'{alumno.fecha_nacimiento:%d/%m/%Y}', f'{inscripcion.fecha_inscripcion:%d/%m/%Y}',
        ]])
    return respuesta
