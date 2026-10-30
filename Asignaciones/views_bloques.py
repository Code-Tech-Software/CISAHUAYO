"""Gestión académica › Asignaciones de materias › Bloques simultáneos: crear un bloque y sus opciones, elegir quién
participa, distribuir a los estudiantes, revisar conflictos y activar o desactivar. Las reglas están en
Asignaciones/bloques.py; toda operación se revalida ahí.
"""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from Alumnos.academico import ciclo_actual, elegir_ciclo
from Alumnos.models import BloqueSimultaneo, CicloEscolar, GrupoClase, Inscripcion
from CISAHUAYO.permisos import requiere_permisos
from Usuarios.seguridad import ACCION_ALTA, ACCION_CAMBIO, registrar

from . import bloques as reglas
from .forms_bloques import BloqueForm, FechaEfectivaForm, FiltroEstudiantesForm, HorariosForm, OpcionForm, SustituyeForm


def _bloque(pk):
    return get_object_or_404(BloqueSimultaneo.objects.select_related('ciclo', 'semestre'), pk=pk)


def _revisar_editable(request, bloque):
    motivo = reglas.bloqueo(bloque)
    if motivo:
        messages.error(request, motivo)
    return not motivo


# ---------------------------------------------------------------------------
# Lista
# ---------------------------------------------------------------------------
@requiere_permisos(reglas.VER)
def lista(request):
    ciclos = list(CicloEscolar.objects.all())
    ciclo = elegir_ciclo(request.GET.get('ciclo', ''), ciclos)
    bloques = []
    if ciclo:
        for bloque in BloqueSimultaneo.objects.filter(ciclo=ciclo).select_related('semestre').prefetch_related('horarios', 'opciones', 'grupos_origen__grado', 'grupos_origen__nombre'):
            datos = reglas.distribucion(bloque)
            bloque.total_estudiantes, bloque.pendientes = datos.total, len(datos.pendientes)
            bloques.append(bloque)
    return render(request, 'asignaciones/bloques.html', {'seccion': 'bloques', 'ciclos': ciclos, 'ciclo': ciclo, 'bloques': bloques})


# ---------------------------------------------------------------------------
# Crear y editar
# ---------------------------------------------------------------------------
@requiere_permisos(reglas.CREAR)
def crear(request):
    actual = ciclo_actual()
    form = BloqueForm(request.POST or None, initial={'ciclo': actual.pk if actual else None})
    if request.method == 'POST':
        if form.is_valid():
            bloque = form.save(commit=False)
            bloque.creado_por = request.user
            bloque.save()
            form.save_m2m()
            registrar(request.user, bloque, ACCION_ALTA, f'Creó el bloque {bloque.nombre} en preparación.')
            messages.success(request, f'Se creó el bloque {bloque.nombre}. Agrega sus horarios y sus opciones.')
            return redirect(bloque)
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return render(request, 'asignaciones/bloque_form.html', {'form': form, 'es_edicion': False})


@requiere_permisos(reglas.GESTIONAR)
def editar(request, pk):
    bloque = _bloque(pk)
    if not _revisar_editable(request, bloque):
        return redirect(bloque)
    form = BloqueForm(request.POST or None, instance=bloque)
    if request.method == 'POST':
        if form.is_valid():
            cambios = form.changed_data
            bloque = form.save()
            if bloque.activo:
                reglas.actualizar_fin(bloque)
            if cambios:
                registrar(request.user, bloque, ACCION_CAMBIO, f'Editó el bloque: {", ".join(cambios)}.')
            messages.success(request, f'Se guardó el bloque {bloque.nombre}.')
            return redirect(bloque)
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return render(request, 'asignaciones/bloque_form.html', {'form': form, 'bloque': bloque, 'es_edicion': True})


@requiere_permisos(reglas.GESTIONAR)
def horarios(request, pk):
    bloque = _bloque(pk)
    if not _revisar_editable(request, bloque):
        return redirect(bloque)
    if bloque.activo:
        messages.error(request, 'Desactiva el bloque para cambiar sus horarios.')
        return redirect(bloque)
    form = HorariosForm(request.POST or None, bloque=bloque)
    if request.method == 'POST':
        if form.is_valid():
            reglas.guardar_horarios(bloque, form.cleaned_data['filas'])
            registrar(request.user, bloque, ACCION_CAMBIO, 'Cambió los días y horarios del bloque.')
            messages.success(request, 'Se guardaron los días y horarios del bloque.')
            return redirect(bloque)
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return render(request, 'asignaciones/bloque_horarios.html', {'form': form, 'bloque': bloque})


@requiere_permisos(reglas.GESTIONAR)
def sustituye(request, pk):
    bloque = _bloque(pk)
    if not _revisar_editable(request, bloque):
        return redirect(bloque)
    if bloque.activo:
        messages.error(request, 'Desactiva el bloque para cambiar las clases que sustituye.')
        return redirect(bloque)
    form = SustituyeForm(request.POST or None, bloque=bloque)
    if request.method == 'POST' and form.is_valid():
        bloque.sustituye.set(form.cleaned_data['sustituye'])
        registrar(request.user, bloque, ACCION_CAMBIO, f'Sustituye: {", ".join(f"{a.materia} ({a.grupo})" for a in form.cleaned_data["sustituye"]) or "ninguna clase"}.')
        messages.success(request, 'Se guardaron las clases que sustituye el bloque.')
        return redirect(bloque)
    return render(request, 'asignaciones/bloque_sustituye.html', {'form': form, 'bloque': bloque})


# ---------------------------------------------------------------------------
# Detalle
# ---------------------------------------------------------------------------
@requiere_permisos(reglas.VER)
def detalle(request, pk):
    bloque = _bloque(pk)
    datos = reglas.distribucion(bloque)
    conflictos = reglas.conflictos(bloque)
    puede = request.user.has_perm(reglas.GESTIONAR) and not reglas.bloqueo(bloque)
    return render(request, 'asignaciones/bloque.html', {
        'bloque': bloque, 'seccion': 'bloques', 'ciclo': bloque.ciclo, 'datos': datos, 'conflictos': conflictos,
        'horarios': list(bloque.horarios.all()), 'grupos': list(bloque.grupos_origen.select_related('grado', 'nombre')),
        'sustituye': list(bloque.sustituye.select_related('materia', 'grupo__nombre', 'grupo__grado')),
        'bloqueo': reglas.bloqueo(bloque), 'puede_gestionar': puede,
        'problemas': reglas.problemas_para_activar(bloque) if puede and not bloque.activo else [],
        'historial': reglas.historial_del_bloque(bloque), 'hoy': timezone.localdate(),
    })


@require_POST
@requiere_permisos(reglas.GESTIONAR)
def activar(request, pk):
    bloque = _bloque(pk)
    try:
        reglas.activar(bloque, request.user)
    except reglas.BloqueRechazado as error:
        messages.error(request, f'No se activó: {error.mensaje}')
    else:
        messages.success(request, f'El bloque {bloque.nombre} está activo: sus clases ya están en el horario.')
    return redirect(bloque)


@require_POST
@requiere_permisos(reglas.GESTIONAR)
def desactivar(request, pk):
    bloque = _bloque(pk)
    fecha = FechaEfectivaForm(request.POST).fecha_o_hoy()
    try:
        reglas.desactivar(bloque, fecha, request.user)
    except reglas.BloqueRechazado as error:
        messages.error(request, error.mensaje)
    else:
        messages.success(request, f'El bloque {bloque.nombre} se desactivó desde el {fecha:%d/%m/%Y}. Lo registrado se conserva.')
    return redirect(bloque)


# ---------------------------------------------------------------------------
# Opciones
# ---------------------------------------------------------------------------
@requiere_permisos(reglas.GESTIONAR)
def opcion_crear(request, pk):
    bloque = _bloque(pk)
    if not _revisar_editable(request, bloque):
        return redirect(bloque)
    form = OpcionForm(request.POST or None, bloque=bloque)
    if request.method == 'POST':
        if form.is_valid():
            try:
                clase = reglas.crear_opcion(bloque, form.datos(), request.user)
            except reglas.BloqueRechazado as error:
                form.add_error(None, error.mensaje)
            else:
                messages.success(request, f'Se agregó {clase.nombre}.')
                return redirect(bloque)
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return render(request, 'asignaciones/opcion_form.html', {'form': form, 'bloque': bloque, 'es_edicion': False})


@requiere_permisos(reglas.GESTIONAR)
def opcion_editar(request, pk):
    clase = get_object_or_404(GrupoClase.objects.select_related('bloque__ciclo', 'bloque__semestre', 'asignacion__materia', 'asignacion__profesor'), pk=pk)
    bloque = clase.bloque
    if not _revisar_editable(request, bloque):
        return redirect(bloque)
    form = OpcionForm(request.POST or None, bloque=bloque, clase=clase)
    if request.method == 'POST':
        if form.is_valid():
            try:
                reglas.editar_opcion(clase, form.datos(), request.user)
            except reglas.BloqueRechazado as error:
                form.add_error(None, error.mensaje)
            else:
                messages.success(request, f'Se guardó {clase.nombre}.')
                return redirect(bloque)
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return render(request, 'asignaciones/opcion_form.html', {'form': form, 'bloque': bloque, 'clase': clase, 'es_edicion': True})


@require_POST
@requiere_permisos(reglas.GESTIONAR)
def opcion_estado(request, pk):
    clase = get_object_or_404(GrupoClase.objects.select_related('bloque__ciclo', 'bloque__semestre', 'asignacion'), pk=pk)
    fecha = FechaEfectivaForm(request.POST).fecha_o_hoy()
    try:
        if clase.activa:
            reglas.desactivar_opcion(clase, fecha, request.user)
            messages.success(request, f'{clase.nombre} se desactivó. Sus estudiantes quedaron pendientes de asignación.')
        else:
            reglas.reactivar_opcion(clase, fecha, request.user)
            messages.success(request, f'{clase.nombre} se reactivó.')
    except reglas.BloqueRechazado as error:
        messages.error(request, error.mensaje)
    return redirect(clase.bloque)


# ---------------------------------------------------------------------------
# Población y distribución
# ---------------------------------------------------------------------------
def _elegidas(request):
    ids = [valor for valor in request.POST.getlist('inscripcion') if valor.isdigit()]
    return list(Inscripcion.objects.filter(pk__in=ids).select_related('alumno', 'grado', 'grupo__nombre', 'grupo__grado', 'ciclo'))


@requiere_permisos(reglas.VER)
def poblacion(request, pk):
    """Con población delimitada: quiénes de los grupos de origen participan."""
    bloque = _bloque(pk)
    if request.method == 'POST':
        if not request.user.has_perm(reglas.GESTIONAR):
            return redirect(bloque)
        elegidas = _elegidas(request)
        if not elegidas:
            messages.error(request, 'Elige al menos un estudiante.')
        else:
            try:
                reglas.delimitar(bloque, elegidas, request.POST.get('accion') != 'quitar', request.user)
            except reglas.BloqueRechazado as error:
                messages.error(request, error.mensaje)
            else:
                messages.success(request, 'Se actualizó la población del bloque.')
        return redirect('asignaciones:bloque_poblacion', pk=bloque.pk)
    participan = set(bloque.participantes.values_list('inscripcion_id', flat=True))
    filas = [{'inscripcion': i, 'participa': i.pk in participan} for i in reglas.candidatos(bloque)]
    return render(request, 'asignaciones/poblacion.html', {
        'bloque': bloque, 'filas': filas, 'participan': len(participan), 'puede_gestionar': request.user.has_perm(reglas.GESTIONAR) and not bloque.activo and not reglas.bloqueo(bloque),
    })


@requiere_permisos(reglas.VER)
def distribuir(request, pk):
    """La distribución de los estudiantes: filtrar, asignar uno o varios a una opción y cambiarlos con fecha efectiva."""
    bloque = _bloque(pk)
    if request.method == 'POST':
        if not request.user.has_perm(reglas.GESTIONAR):
            return redirect(bloque)
        elegidas = _elegidas(request)
        fecha = FechaEfectivaForm(request.POST).fecha_o_hoy()
        accion = request.POST.get('accion', 'asignar')
        try:
            if not elegidas:
                raise reglas.BloqueRechazado('Elige al menos un estudiante.')
            if accion == 'quitar':
                cuantos = reglas.quitar(bloque, elegidas, fecha, request.user)
                messages.success(request, f'{cuantos} estudiante(s) quedaron pendientes de asignación.')
            else:
                clase = bloque.opciones.filter(pk=request.POST.get('opcion') or 0).first()
                if clase is None:
                    raise reglas.BloqueRechazado('Elige la opción.')
                cuantos = reglas.asignar(bloque, clase, elegidas, fecha, request.user)
                messages.success(request, f'{cuantos} estudiante(s) asignados a {clase.nombre}.' if cuantos else 'Ya estaban en esa opción.')
        except reglas.BloqueRechazado as error:
            messages.error(request, error.mensaje)
        return redirect(f"{request.path}?{request.POST.get('filtros', '')}")

    datos = reglas.distribucion(bloque, FechaEfectivaForm(request.GET).fecha_o_hoy() if request.GET.get('fecha') else None)
    filtro = FiltroEstudiantesForm(request.GET or None, bloque=bloque)
    filas = filtro.aplicar(datos.filas) if request.GET else datos.filas
    return render(request, 'asignaciones/distribuir.html', {
        'bloque': bloque, 'datos': datos, 'filas': filas, 'filtro': filtro, 'filtros': request.GET.urlencode(),
        'opciones': [o for o in datos.opciones if o['clase'].activa],
        'puede_gestionar': request.user.has_perm(reglas.GESTIONAR) and not reglas.bloqueo(bloque) and bloque.estado != BloqueSimultaneo.INACTIVO,
        'hoy': timezone.localdate(),
    })
