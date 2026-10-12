from itertools import groupby

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from Alumnos.academico import ciclo_editable, elegir_ciclo
from Alumnos.horarios import (
    DIAS,
    DIAS_CORTOS,
    DIAS_HABILES,
    con_resumen_de_horario,
    cuadricula,
    formatear_duracion,
    minutos_por_profesor,
    minutos_semanales,
    recreos_del_grupo,
    resumen_horario,
)
from Alumnos.models import CicloEscolar, Grado, Grupo, HorarioMateria, MateriaGrado, Profesor, Recreo
from CISAHUAYO.permisos import requiere_permisos

from .forms import HorarioCrearForm, HorarioEditarForm, RecreoCrearForm, RecreoEditarForm


def _url_del_grupo(grupo_id, ciclo_id):
    return f"{reverse('horarios:grupo', args=[grupo_id])}?ciclo={ciclo_id}"


def _ciclo_de(request):
    """Ciclo que se consulta: ?ciclo=, si no el actual y, si no hay, el más reciente."""
    ciclos = list(CicloEscolar.objects.all())
    return ciclos, elegir_ciclo(request.GET.get('ciclo', ''), ciclos)


# ---------------------------------------------------------------------------
# Índice: los grupos con un resumen de su horario
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.view_horariomateria')
def horario_lista(request):
    ciclos, ciclo = _ciclo_de(request)

    estadisticas = {}
    if ciclo:
        vigentes = MateriaGrado.objects.filter(ciclo=ciclo, activa=True).order_by()
        for grupo_id, materias in vigentes.values_list('grupo_id').annotate(total=Count('pk')):
            estadisticas[grupo_id] = {'materias': materias, 'bloques': 0, 'minutos': 0, 'sin_horario': materias, 'sin_profesor': 0}
        for grupo_id, materias in vigentes.filter(profesor__isnull=True).values_list('grupo_id').annotate(total=Count('pk')):
            estadisticas[grupo_id]['sin_profesor'] = materias
        con_horario = vigentes.filter(horarios__isnull=False).values_list('grupo_id').annotate(total=Count('pk', distinct=True))
        for grupo_id, materias in con_horario:
            estadisticas[grupo_id]['sin_horario'] -= materias
        bloques = HorarioMateria.objects.filter(materia_grado__ciclo=ciclo, materia_grado__activa=True)
        for grupo_id, inicio, fin in bloques.values_list('materia_grado__grupo_id', 'hora_inicio', 'hora_fin'):
            datos = estadisticas[grupo_id]
            datos['bloques'] += 1
            datos['minutos'] += (fin.hour * 60 + fin.minute) - (inicio.hour * 60 + inicio.minute)

    # El receso de cada grupo, resumido («Lun, Mar, Mié, Jue, Vie · 10:30–11:00»)
    recesos = {}
    if ciclo:
        for receso in Recreo.objects.filter(ciclo=ciclo).order_by('dia_semana', 'hora_inicio'):
            recesos.setdefault(receso.grupo_id, []).append(receso)

    grupos = (
        Grupo.objects.filter(Q(activo=True, grado__activo=True) | Q(pk__in=estadisticas))
        .select_related('grado', 'nombre').academicos()
    )
    niveles = []
    for nivel, del_nivel in groupby(grupos, key=lambda grupo: grupo.grado.nivel):
        filas = []
        for grupo in del_nivel:
            datos = estadisticas.get(grupo.pk, {'materias': 0, 'bloques': 0, 'minutos': 0, 'sin_horario': 0, 'sin_profesor': 0})
            filas.append({
                **datos, 'grupo': grupo, 'duracion': formatear_duracion(datos['minutos']) if datos['minutos'] else '',
                'recesos': resumen_horario(recesos.get(grupo.pk, [])),
            })
        niveles.append({'nombre': dict(Grado.NIVEL_CHOICES)[nivel], 'filas': filas})

    # Los profesores que dan clase en el ciclo, con su carga semanal
    profesores = []
    if ciclo:
        vigentes_del_ciclo = Q(asignaciones__ciclo=ciclo, asignaciones__activa=True)
        profesores = list(
            Profesor.objects.filter(vigentes_del_ciclo).distinct()
            .annotate(materias=Count('asignaciones', filter=vigentes_del_ciclo, distinct=True))
        )
        minutos = minutos_por_profesor([p.pk for p in profesores], ciclo)
        for profesor in profesores:
            profesor.duracion = formatear_duracion(minutos[profesor.pk]) if minutos[profesor.pk] else ''

    return render(request, 'horarios/lista.html', {
        'ciclos': ciclos,
        'ciclo': ciclo,
        'niveles': niveles,
        'profesores': profesores,
        'editable': ciclo_editable(ciclo),
    })


# ---------------------------------------------------------------------------
# Horario semanal de un grupo
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.view_horariomateria')
def horario_grupo(request, grupo_pk):
    grupo = get_object_or_404(Grupo.objects.select_related('grado', 'nombre'), pk=grupo_pk)
    ciclos, ciclo = _ciclo_de(request)

    asignaciones = []
    if ciclo:
        asignaciones = con_resumen_de_horario(
            MateriaGrado.objects.filter(grupo=grupo, ciclo=ciclo, activa=True)
            .select_related('materia', 'profesor').prefetch_related('horarios').order_by('materia__nombre')
        )
    # Cada bloque ya trae su asignación (y la materia) gracias al prefetch: sin consultas por celda
    bloques = [bloque for asignacion in asignaciones for bloque in asignacion.horarios.all()]
    minutos = minutos_semanales(bloques)
    recesos = list(recreos_del_grupo(grupo, ciclo))

    return render(request, 'horarios/grupo.html', {
        'grupo': grupo,
        'grado': grupo.grado,
        # Los grupos del mismo grado, para pasar de uno a otro (solo si tiene varios)
        'grupos_del_grado': list(
            grupo.grado.grupos.filter(Q(activo=True) | Q(pk=grupo.pk)).select_related('nombre', 'grado').order_by('nombre__orden', 'nombre__nombre')
        ),
        'ciclos': ciclos,
        'ciclo': ciclo,
        'asignaciones': asignaciones,
        'sin_horario': [a for a in asignaciones if not a.bloques],
        'sin_profesor': [a for a in asignaciones if not a.profesor_id],
        'etiqueta_horario': f'Horario semanal de {grupo} en el ciclo {ciclo}' if ciclo else '',
        'cuadricula': cuadricula(bloques + recesos),
        'recesos': recesos,
        'resumen_recesos': resumen_horario(recesos),
        'total_bloques': len(bloques),
        'horas_semanales': formatear_duracion(minutos) if minutos else '',
        'editable': ciclo_editable(ciclo),
    })


@requiere_permisos('Alumnos.view_horariomateria')
def horario_grado(request, grado_pk):
    """El horario es de cada grupo: el enlace a un grado lleva al horario de su primer grupo."""
    grado = get_object_or_404(Grado, pk=grado_pk)
    grupo = Grupo.principal_de(grado)
    destino = reverse('horarios:grupo', args=[grupo.pk])
    return redirect(f"{destino}?{request.GET.urlencode()}" if request.GET else destino)


# ---------------------------------------------------------------------------
# Agregar, editar y quitar bloques
# ---------------------------------------------------------------------------
def _ciclo_cerrado(request, grupo_id, ciclo):
    messages.error(request, f'El ciclo {ciclo} está cerrado: su horario se conserva tal como quedó y ya no se modifica.')
    return redirect(_url_del_grupo(grupo_id, ciclo.pk))


@requiere_permisos('Alumnos.add_horariomateria')
def horario_crear(request, grupo_pk):
    grupo = get_object_or_404(Grupo.objects.select_related('grado', 'nombre'), pk=grupo_pk)
    _, ciclo = _ciclo_de(request)
    if ciclo is None:
        messages.error(request, 'Crea un ciclo escolar para poder armar horarios.')
        return redirect('horarios:lista')
    if not ciclo_editable(ciclo):
        return _ciclo_cerrado(request, grupo.pk, ciclo)

    if request.method == 'POST':
        form = HorarioCrearForm(request.POST, grupo=grupo, ciclo=ciclo)
        if form.is_valid():
            bloques = form.guardar()
            dias = ', '.join(f'{DIAS_CORTOS[b.dia_semana]} {b.hora_inicio:%H:%M}–{b.hora_fin:%H:%M}' for b in bloques)
            messages.success(request, f'Se agregó el horario de {form.cleaned_data["materia_grado"].materia}: {dias}.')
            return redirect(_url_del_grupo(grupo.pk, ciclo.pk))
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    else:
        inicial = {}
        if request.GET.get('materia', '').isdigit():
            inicial['materia_grado'] = int(request.GET['materia'])
        if request.GET.get('dia', '').isdigit() and int(request.GET['dia']) in DIAS:
            inicial['dias'] = [int(request.GET['dia'])]
        form = HorarioCrearForm(grupo=grupo, ciclo=ciclo, initial=inicial)

    return render(request, 'horarios/form.html', {
        'form': form, 'grupo': grupo, 'ciclo': ciclo, 'es_edicion': False,
        'sin_materias': not form.fields['materia_grado'].queryset.exists(),
    })


def _bloque_vigente(pk):
    return get_object_or_404(
        HorarioMateria.objects.select_related(
            'materia_grado__materia', 'materia_grado__grupo__grado', 'materia_grado__grupo__nombre', 'materia_grado__ciclo',
        ),
        pk=pk, materia_grado__activa=True,
    )


@requiere_permisos('Alumnos.change_horariomateria')
def horario_editar(request, pk):
    bloque = _bloque_vigente(pk)
    grupo, ciclo = bloque.materia_grado.grupo, bloque.materia_grado.ciclo
    if not ciclo_editable(ciclo):
        return _ciclo_cerrado(request, grupo.pk, ciclo)

    form = HorarioEditarForm(request.POST if request.method == 'POST' else None, instance=bloque)
    if request.method == 'POST':
        if form.is_valid():
            bloque = form.save()
            messages.success(request, f'Se actualizó el horario de {bloque.materia_grado.materia} ({DIAS[bloque.dia_semana].lower()}).')
            return redirect(_url_del_grupo(grupo.pk, ciclo.pk))
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')

    return render(request, 'horarios/form.html', {
        'form': form, 'grupo': grupo, 'ciclo': ciclo, 'es_edicion': True, 'bloque': bloque, 'sin_materias': False,
    })


@require_POST
@requiere_permisos('Alumnos.delete_horariomateria')
def horario_eliminar(request, pk):
    """Quita un bloque del horario. Es un dato de configuración: nada depende de él (la asistencia por materia
    se registra por materia y fecha, no por bloque), así que se borra en lugar de dejarlo oculto."""
    bloque = _bloque_vigente(pk)
    grupo, ciclo = bloque.materia_grado.grupo, bloque.materia_grado.ciclo
    if not ciclo_editable(ciclo):
        return _ciclo_cerrado(request, grupo.pk, ciclo)

    materia, dia = bloque.materia_grado.materia, DIAS[bloque.dia_semana].lower()
    texto = f'{bloque.hora_inicio:%H:%M}–{bloque.hora_fin:%H:%M}'
    bloque.delete()
    messages.success(request, f'Se quitó {materia} del horario ({dia} {texto}).')
    return redirect(_url_del_grupo(grupo.pk, ciclo.pk))


# ---------------------------------------------------------------------------
# Recesos: se agregan a uno o varios grupos a la vez; cada uno se edita o se quita por separado
# (en el código se llaman «recreos», como el modelo)
# ---------------------------------------------------------------------------
def _url_de_la_lista(ciclo_id):
    return f"{reverse('horarios:lista')}?ciclo={ciclo_id}"


def _ciclo_cerrado_en(request, ciclo, destino):
    messages.error(request, f'El ciclo {ciclo} está cerrado: su horario se conserva tal como quedó y ya no se modifica.')
    return redirect(destino)


@requiere_permisos('Alumnos.add_horariomateria')
def recreo_crear(request):
    """Alta de un receso para los grupos que se elijan. Desde el horario de un grupo (`?grupo=`) ese grupo ya va marcado
    y al guardar se regresa a él; desde el índice, se regresa al índice."""
    _, ciclo = _ciclo_de(request)
    if ciclo is None:
        messages.error(request, 'Crea un ciclo escolar para poder armar horarios.')
        return redirect('horarios:lista')
    valor = request.GET.get('grupo', '')
    grupo = Grupo.objects.select_related('grado', 'nombre').filter(pk=valor).first() if valor.isdigit() else None
    volver = _url_del_grupo(grupo.pk, ciclo.pk) if grupo else _url_de_la_lista(ciclo.pk)
    if not ciclo_editable(ciclo):
        return _ciclo_cerrado_en(request, ciclo, volver)

    if request.method == 'POST':
        form = RecreoCrearForm(request.POST, ciclo=ciclo)
        if form.is_valid():
            recesos = form.guardar()
            grupos = list(form.cleaned_data['grupos'])
            nombres = ', '.join(str(g) for g in grupos)
            horas = '; '.join(resumen_horario([r for r in recesos if r.grupo_id == grupos[0].pk]))
            messages.success(request, f'Se agregó «{form.cleaned_data["nombre"]}» a {nombres}: {horas}.')
            return redirect(volver)
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    else:
        # De lunes a viernes, que es lo habitual: se quita el día que no lleve receso
        form = RecreoCrearForm(ciclo=ciclo, initial={'grupos': [grupo.pk] if grupo else [], 'dias': list(DIAS_HABILES)})

    return render(request, 'horarios/recreo_form.html', {
        'form': form, 'ciclo': ciclo, 'grupo': grupo, 'volver': volver, 'es_edicion': False,
    })


def _recreo(pk):
    return get_object_or_404(Recreo.objects.select_related('grupo__grado', 'grupo__nombre', 'ciclo'), pk=pk)


@requiere_permisos('Alumnos.change_horariomateria')
def recreo_editar(request, pk):
    receso = _recreo(pk)
    volver = _url_del_grupo(receso.grupo_id, receso.ciclo_id)
    if not ciclo_editable(receso.ciclo):
        return _ciclo_cerrado_en(request, receso.ciclo, volver)

    form = RecreoEditarForm(request.POST if request.method == 'POST' else None, instance=receso)
    if request.method == 'POST':
        if form.is_valid():
            receso = form.save()
            messages.success(request, f'Se actualizó «{receso.nombre}» de {receso.grupo} ({DIAS[receso.dia_semana].lower()}).')
            return redirect(volver)
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')

    return render(request, 'horarios/recreo_form.html', {
        'form': form, 'ciclo': receso.ciclo, 'grupo': receso.grupo, 'volver': volver, 'es_edicion': True, 'recreo': receso,
    })


@require_POST
@requiere_permisos('Alumnos.delete_horariomateria')
def recreo_eliminar(request, pk):
    """Quita un receso de un grupo (un día). Es configuración del horario: nada depende de él, así que se borra."""
    receso = _recreo(pk)
    volver = _url_del_grupo(receso.grupo_id, receso.ciclo_id)
    if not ciclo_editable(receso.ciclo):
        return _ciclo_cerrado_en(request, receso.ciclo, volver)
    texto = f'{DIAS[receso.dia_semana].lower()} {receso.hora_inicio:%H:%M}–{receso.hora_fin:%H:%M}'
    receso.delete()
    messages.success(request, f'Se quitó «{receso.nombre}» de {receso.grupo} ({texto}).')
    return redirect(volver)
