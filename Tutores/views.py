import csv

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Prefetch
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from Alumnos.models import Inscripcion, Tutor, TutorAlumno
from Alumnos.utils import ESTADOS_MX, proteger_celda_csv
from Alumnos.vinculos import asegurar_tutor_principal, sincronizar_principales
from CISAHUAYO.paginacion import OPCIONES_POR_PAGINA, POR_PAGINA_DEFECTO, paginar
from CISAHUAYO.permisos import requiere_permisos

from .forms import FiltroTutoresForm, TutorForm, VinculoForm


def _prefetch_alumnos_vigentes():
    """Alumnos vinculados de forma activa, sin contar las bajas (solo para la página mostrada)."""
    return Prefetch(
        'alumnos_relacionados',
        queryset=(
            TutorAlumno.objects.filter(activo=True)
            .exclude(alumno__estatus='BAJA')
            .select_related('alumno')
            .order_by('alumno__apellido_paterno', 'alumno__nombre')
        ),
        to_attr='vinculos_vigentes',
    )


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.view_tutor')
def tutor_lista(request):
    filtro = FiltroTutoresForm(request.GET)
    tutores = filtro.filtrar(Tutor.objects.all()).prefetch_related(_prefetch_alumnos_vigentes())
    pagina, rango_paginas, por_pagina = paginar(request, tutores)

    conteos = dict(Tutor.objects.values_list('estatus').annotate(total=Count('pk')))
    return render(request, 'tutores/lista.html', {
        'filtro': filtro,
        'pagina': pagina,
        'rango_paginas': rango_paginas,
        'por_pagina': por_pagina,
        'por_pagina_defecto': POR_PAGINA_DEFECTO,
        'opciones_por_pagina': OPCIONES_POR_PAGINA,
        'total_activos': conteos.get('ACTIVO', 0),
        'total_bajas': conteos.get('INACTIVO', 0),
        'viendo_bajas': filtro.activos.get('estatus') == 'INACTIVO',
        'filtros_activos': {k: v for k, v in filtro.activos.items() if k not in ('orden', 'estatus')},
    })


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
def _formulario(request, form, tutor=None):
    return render(request, 'tutores/form.html', {
        'form': form,
        'tutor': tutor,
        'es_edicion': tutor is not None,
        'estados_mx': ESTADOS_MX,
    })


@requiere_permisos('Alumnos.add_tutor')
def tutor_crear(request):
    form = TutorForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        if form.is_valid():
            tutor = form.save()
            messages.success(request, f'{tutor} fue registrado correctamente.')
            return redirect('tutores:lista')
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return _formulario(request, form)


@requiere_permisos('Alumnos.change_tutor')
def tutor_editar(request, pk):
    tutor = get_object_or_404(Tutor, pk=pk)
    form = TutorForm(request.POST if request.method == 'POST' else None, instance=tutor)
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            messages.success(request, f'Los datos de {tutor} se actualizaron.')
            return redirect('tutores:lista')
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return _formulario(request, form, tutor)


# ---------------------------------------------------------------------------
# Perfil
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.view_tutor')
def tutor_detalle(request, pk):
    tutor = get_object_or_404(Tutor, pk=pk)
    vinculos = (
        TutorAlumno.objects.filter(tutor=tutor)
        .select_related('alumno')
        .prefetch_related(Prefetch(
            'alumno__inscripciones',
            queryset=(
                Inscripcion.objects.filter(activa=True, ciclo__activo=True)
                .select_related('grado', 'ciclo')
                .order_by('-ciclo__fecha_inicio')
            ),
            to_attr='inscripciones_actuales',
        ))
        .order_by('-activo', 'alumno__apellido_paterno', 'alumno__nombre')
    )
    vigentes = [v for v in vinculos if v.activo and v.alumno.estatus != 'BAJA']

    # Alumnos que se quedarían sin ningún tutor vigente si este tutor se da de baja (una sola consulta)
    con_otro_tutor = set(
        TutorAlumno.objects.filter(activo=True, tutor__estatus='ACTIVO', alumno_id__in=[v.alumno_id for v in vigentes])
        .exclude(tutor=tutor)
        .values_list('alumno_id', flat=True)
    )
    sin_otro_tutor = sum(1 for v in vigentes if v.alumno_id not in con_otro_tutor)

    return render(request, 'tutores/detalle.html', {
        'tutor': tutor,
        'vinculos': vinculos,
        'total_vigentes': len(vigentes),
        'sin_otro_tutor': sin_otro_tutor,
        'esta_de_baja': tutor.estatus == 'INACTIVO',
        'vinculo_form': VinculoForm(),
    })


# ---------------------------------------------------------------------------
# Acciones sobre un tutor
# ---------------------------------------------------------------------------
@require_POST
@requiere_permisos('Alumnos.delete_tutor')
def tutor_baja(request, pk):
    """Baja lógica: el tutor deja de aparecer en el listado y en las búsquedas, pero nada se borra."""
    tutor = get_object_or_404(Tutor, pk=pk)
    if tutor.estatus == 'INACTIVO':
        messages.info(request, f'{tutor} ya estaba dado de baja.')
        return redirect('tutores:lista')

    with transaction.atomic():
        tutor.estatus = 'INACTIVO'
        tutor.save(update_fields=['estatus', 'modificado'])
        sincronizar_principales(tutor)  # deja de ser el principal; otro tutor vigente toma su lugar
    messages.success(request, f'{tutor} fue dado de baja. Su registro se conserva y puedes reactivarlo desde el filtro «Bajas».')
    return redirect('tutores:lista')


@require_POST
@requiere_permisos('Alumnos.change_tutor')
def tutor_reactivar(request, pk):
    tutor = get_object_or_404(Tutor, pk=pk)
    if tutor.estatus == 'INACTIVO':
        with transaction.atomic():
            tutor.estatus = 'ACTIVO'
            tutor.save(update_fields=['estatus', 'modificado'])
            sincronizar_principales(tutor)
        messages.success(request, f'{tutor} fue reactivado.')
    return redirect('tutores:lista')


@require_POST
@requiere_permisos('Alumnos.change_tutor')
def tutor_vincular(request, pk):
    tutor = get_object_or_404(Tutor, pk=pk)
    destino = f'{tutor.get_absolute_url()}#alumnos'
    if tutor.estatus != 'ACTIVO':
        messages.error(request, 'Reactiva al tutor antes de vincularlo con un alumno.')
        return redirect(destino)

    form = VinculoForm(request.POST)
    if form.is_valid():
        vinculo, creado = form.guardar(tutor)
        if creado:
            messages.success(request, f'{vinculo.alumno} ahora está vinculado con {tutor} ({vinculo.get_parentesco_display()}).')
        else:
            messages.success(request, f'Se actualizó el vínculo de {tutor} con {vinculo.alumno}.')
    else:
        error = next((errores[0] for errores in form.errors.values()), 'Revisa los datos del vínculo.')
        messages.error(request, f'No se pudo guardar el vínculo: {error}')
    return redirect(destino)


@require_POST
@requiere_permisos('Alumnos.change_tutor')
def tutor_desvincular(request, pk):
    """Desvincular es lógico: el vínculo se conserva como inactivo."""
    tutor = get_object_or_404(Tutor, pk=pk)
    vinculo_id = request.POST.get('vinculo', '')
    if not vinculo_id.isdigit():
        raise Http404
    vinculo = get_object_or_404(TutorAlumno.objects.select_related('alumno'), pk=vinculo_id, tutor=tutor)

    vinculo.activo = False
    vinculo.tutor_principal = False
    vinculo.save(update_fields=['activo', 'tutor_principal', 'modificado'])
    asegurar_tutor_principal(vinculo.alumno)
    messages.success(request, f'{tutor} fue desvinculado de {vinculo.alumno}. El vínculo se conserva como inactivo.')
    return redirect(f'{tutor.get_absolute_url()}#alumnos')


# ---------------------------------------------------------------------------
# Exportación
# ---------------------------------------------------------------------------
@require_GET
@requiere_permisos('Alumnos.view_tutor')
def tutor_exportar(request):
    filtro = FiltroTutoresForm(request.GET)
    tutores = filtro.filtrar(Tutor.objects.all()).prefetch_related(_prefetch_alumnos_vigentes())

    respuesta = HttpResponse(content_type='text/csv; charset=utf-8')
    respuesta['Content-Disposition'] = f'attachment; filename="tutores-{timezone.localdate():%Y-%m-%d}.csv"'
    respuesta.write('﻿')  # para que Excel reconozca los acentos
    escritor = csv.writer(respuesta)
    escritor.writerow([
        'Nombre', 'Apellido paterno', 'Apellido materno', 'CURP', 'Estado civil', 'Teléfono',
        'Teléfono alternativo', 'Correo electrónico', 'Ocupación', 'Lugar de trabajo', 'Domicilio',
        'Colonia', 'Ciudad', 'Estado', 'CP', 'Estatus', 'Alumnos vigentes',
    ])
    for tutor in tutores.iterator(chunk_size=500):
        alumnos = '; '.join(v.alumno.nombre_completo for v in tutor.vinculos_vigentes)
        escritor.writerow([proteger_celda_csv(valor) for valor in [
            tutor.nombre, tutor.apellido_paterno, tutor.apellido_materno, tutor.curp or '',
            tutor.get_estado_civil_display(), tutor.telefono, tutor.telefono_alternativo,
            tutor.correo_electronico or '', tutor.ocupacion, tutor.lugar_trabajo, tutor.domicilio,
            tutor.colonia, tutor.ciudad, tutor.estado, tutor.cp, tutor.get_estatus_display(), alumnos,
        ]])
    return respuesta
