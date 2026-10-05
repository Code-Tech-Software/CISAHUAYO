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
    con_resumen_de_horario,
    cuadricula,
    formatear_duracion,
    minutos_por_profesor,
    minutos_semanales,
)
from Alumnos.models import CicloEscolar, Grado, HorarioMateria, MateriaGrado, Profesor
from CISAHUAYO.permisos import requiere_permisos

from .forms import HorarioCrearForm, HorarioEditarForm


def _url_del_grado(grado_id, ciclo_id):
    return f"{reverse('horarios:grado', args=[grado_id])}?ciclo={ciclo_id}"


def _ciclo_de(request):
    """Ciclo que se consulta: ?ciclo=, si no el actual y, si no hay, el más reciente."""
    ciclos = list(CicloEscolar.objects.all())
    return ciclos, elegir_ciclo(request.GET.get('ciclo', ''), ciclos)


# ---------------------------------------------------------------------------
# Índice: los grados con un resumen de su horario
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.view_horariomateria')
def horario_lista(request):
    ciclos, ciclo = _ciclo_de(request)

    estadisticas = {}
    if ciclo:
        vigentes = MateriaGrado.objects.filter(ciclo=ciclo, activa=True).order_by()
        for grado_id, materias in vigentes.values_list('grado_id').annotate(total=Count('pk')):
            estadisticas[grado_id] = {'materias': materias, 'bloques': 0, 'minutos': 0, 'sin_horario': materias, 'sin_profesor': 0}
        for grado_id, materias in vigentes.filter(profesor__isnull=True).values_list('grado_id').annotate(total=Count('pk')):
            estadisticas[grado_id]['sin_profesor'] = materias
        con_horario = vigentes.filter(horarios__isnull=False).values_list('grado_id').annotate(total=Count('pk', distinct=True))
        for grado_id, materias in con_horario:
            estadisticas[grado_id]['sin_horario'] -= materias
        bloques = HorarioMateria.objects.filter(materia_grado__ciclo=ciclo, materia_grado__activa=True)
        for grado_id, inicio, fin in bloques.values_list('materia_grado__grado_id', 'hora_inicio', 'hora_fin'):
            datos = estadisticas[grado_id]
            datos['bloques'] += 1
            datos['minutos'] += (fin.hour * 60 + fin.minute) - (inicio.hour * 60 + inicio.minute)

    grados = Grado.objects.filter(Q(activo=True) | Q(pk__in=estadisticas)).academicos()
    niveles = []
    for nivel, del_nivel in groupby(grados, key=lambda grado: grado.nivel):
        filas = []
        for grado in del_nivel:
            datos = estadisticas.get(grado.pk, {'materias': 0, 'bloques': 0, 'minutos': 0, 'sin_horario': 0, 'sin_profesor': 0})
            filas.append({**datos, 'grado': grado, 'duracion': formatear_duracion(datos['minutos']) if datos['minutos'] else ''})
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
# Horario semanal de un grado
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.view_horariomateria')
def horario_grado(request, grado_pk):
    grado = get_object_or_404(Grado, pk=grado_pk)
    ciclos, ciclo = _ciclo_de(request)

    asignaciones = []
    if ciclo:
        asignaciones = con_resumen_de_horario(
            MateriaGrado.objects.filter(grado=grado, ciclo=ciclo, activa=True)
            .select_related('materia', 'profesor').prefetch_related('horarios').order_by('materia__nombre')
        )
    # Cada bloque ya trae su asignación (y la materia) gracias al prefetch: sin consultas por celda
    bloques = [bloque for asignacion in asignaciones for bloque in asignacion.horarios.all()]
    minutos = minutos_semanales(bloques)

    return render(request, 'horarios/grado.html', {
        'grado': grado,
        'ciclos': ciclos,
        'ciclo': ciclo,
        'asignaciones': asignaciones,
        'sin_horario': [a for a in asignaciones if not a.bloques],
        'sin_profesor': [a for a in asignaciones if not a.profesor_id],
        'etiqueta_horario': f'Horario semanal de {grado} en el ciclo {ciclo}' if ciclo else '',
        'cuadricula': cuadricula(bloques),
        'total_bloques': len(bloques),
        'horas_semanales': formatear_duracion(minutos) if minutos else '',
        'editable': ciclo_editable(ciclo),
    })


# ---------------------------------------------------------------------------
# Agregar, editar y quitar bloques
# ---------------------------------------------------------------------------
def _ciclo_cerrado(request, grado_id, ciclo):
    messages.error(request, f'El ciclo {ciclo} está cerrado: su horario se conserva tal como quedó y ya no se modifica.')
    return redirect(_url_del_grado(grado_id, ciclo.pk))


@requiere_permisos('Alumnos.add_horariomateria')
def horario_crear(request, grado_pk):
    grado = get_object_or_404(Grado, pk=grado_pk)
    _, ciclo = _ciclo_de(request)
    if ciclo is None:
        messages.error(request, 'Crea un ciclo escolar para poder armar horarios.')
        return redirect('horarios:lista')
    if not ciclo_editable(ciclo):
        return _ciclo_cerrado(request, grado.pk, ciclo)

    if request.method == 'POST':
        form = HorarioCrearForm(request.POST, grado=grado, ciclo=ciclo)
        if form.is_valid():
            bloques = form.guardar()
            dias = ', '.join(DIAS_CORTOS[b.dia_semana] for b in bloques)
            messages.success(request, f'Se agregó el horario de {form.cleaned_data["materia_grado"].materia}: {dias}.')
            return redirect(_url_del_grado(grado.pk, ciclo.pk))
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    else:
        inicial = {}
        if request.GET.get('materia', '').isdigit():
            inicial['materia_grado'] = int(request.GET['materia'])
        if request.GET.get('dia', '').isdigit() and int(request.GET['dia']) in DIAS:
            inicial['dias'] = [int(request.GET['dia'])]
        form = HorarioCrearForm(grado=grado, ciclo=ciclo, initial=inicial)

    return render(request, 'horarios/form.html', {
        'form': form, 'grado': grado, 'ciclo': ciclo, 'es_edicion': False,
        'sin_materias': not form.fields['materia_grado'].queryset.exists(),
    })


def _bloque_vigente(pk):
    return get_object_or_404(
        HorarioMateria.objects.select_related('materia_grado__materia', 'materia_grado__grado', 'materia_grado__ciclo'),
        pk=pk, materia_grado__activa=True,
    )


@requiere_permisos('Alumnos.change_horariomateria')
def horario_editar(request, pk):
    bloque = _bloque_vigente(pk)
    grado, ciclo = bloque.materia_grado.grado, bloque.materia_grado.ciclo
    if not ciclo_editable(ciclo):
        return _ciclo_cerrado(request, grado.pk, ciclo)

    form = HorarioEditarForm(request.POST if request.method == 'POST' else None, instance=bloque)
    if request.method == 'POST':
        if form.is_valid():
            bloque = form.save()
            messages.success(request, f'Se actualizó el horario de {bloque.materia_grado.materia} ({DIAS[bloque.dia_semana].lower()}).')
            return redirect(_url_del_grado(grado.pk, ciclo.pk))
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')

    return render(request, 'horarios/form.html', {
        'form': form, 'grado': grado, 'ciclo': ciclo, 'es_edicion': True, 'bloque': bloque, 'sin_materias': False,
    })


@require_POST
@requiere_permisos('Alumnos.delete_horariomateria')
def horario_eliminar(request, pk):
    """Quita un bloque del horario. Es un dato de configuración: nada depende de él (la asistencia por materia
    se registra por materia y fecha, no por bloque), así que se borra en lugar de dejarlo oculto."""
    bloque = _bloque_vigente(pk)
    grado, ciclo = bloque.materia_grado.grado, bloque.materia_grado.ciclo
    if not ciclo_editable(ciclo):
        return _ciclo_cerrado(request, grado.pk, ciclo)

    materia, dia = bloque.materia_grado.materia, DIAS[bloque.dia_semana].lower()
    texto = f'{bloque.hora_inicio:%H:%M}–{bloque.hora_fin:%H:%M}'
    bloque.delete()
    messages.success(request, f'Se quitó {materia} del horario ({dia} {texto}).')
    return redirect(_url_del_grado(grado.pk, ciclo.pk))
