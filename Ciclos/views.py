"""Ciclos escolares: lista, alta, edición, detalle y las acciones de marcar como actual, cerrar y borrar.

Marcar como actual y cerrar pasan siempre por su ventana de confirmación y guardan quién y cuándo (2026-10-26). Los
días sin clases están en el detalle de cada ciclo (los de sus fechas).
"""
from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from Alumnos.academico import activar_ciclo, alumnos_sin_inscribir, cerrar_ciclo, ciclo_actual
from Alumnos.asistencias import dias_sin_clases_registrados
from Alumnos.models import CICLO_ACTUAL, CICLO_CERRADO, CICLO_PROXIMO, CicloEscolar, MateriaGrado, Semestre, q_ciclo
from CISAHUAYO.paginacion import OPCIONES_POR_PAGINA, POR_PAGINA_DEFECTO, paginar
from CISAHUAYO.permisos import requiere_permisos

from Asistencias.forms import DiaNoLectivoForm

from Calificaciones import calculo_semestral, semestres
from Calificaciones.forms import MotivoForm
from Calificaciones.models import CambioSemestre

from . import resumen
from .forms import CicloForm, FiltroCiclosForm, SemestresForm
from .reglas import avisos_al_activar, ligado, pendientes_de_cierre

CAMPOS = {'nombre': 'el nombre', 'fecha_inicio': 'la fecha de inicio', 'fecha_fin': 'la fecha de fin'}


def _con_conteos(queryset):
    """Agrega a cada ciclo cuántas inscripciones activas y cuántas bajas tiene."""
    return queryset.annotate(
        inscritos=Count('inscripciones', filter=Q(inscripciones__activa=True)),
        bajas=Count('inscripciones', filter=Q(inscripciones__activa=False, inscripciones__concluida=False)),
    )


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.view_cicloescolar')
def ciclo_lista(request):
    filtro = FiltroCiclosForm(request.GET)
    estado = filtro.activos.get('estado', '')
    ciclos = _con_conteos(filtro.filtrar(CicloEscolar.objects.all()))
    pagina, rango_paginas, por_pagina = paginar(request, ciclos)

    hoy = timezone.localdate()
    conteos = CicloEscolar.objects.aggregate(
        total=Count('pk'),
        actual=Count('pk', filter=q_ciclo(CICLO_ACTUAL)),
        proximo=Count('pk', filter=q_ciclo(CICLO_PROXIMO)),
        cerrado=Count('pk', filter=q_ciclo(CICLO_CERRADO)),
    )
    # La tarjeta del ciclo en curso solo acompaña a la vista completa
    actual = None
    if not estado:
        actual = _con_conteos(CicloEscolar.objects.actuales()).first()

    return render(request, 'ciclos/lista.html', {
        'pagina': pagina,
        'rango_paginas': rango_paginas,
        'por_pagina': por_pagina,
        'por_pagina_defecto': POR_PAGINA_DEFECTO,
        'opciones_por_pagina': OPCIONES_POR_PAGINA,
        'estado': estado,
        'conteos': conteos,
        'actual': actual,
        # Un ciclo que ya empezó y nadie ha marcado como actual
        'por_activar': CicloEscolar.objects.proximos().filter(fecha_inicio__lte=hoy).order_by('fecha_inicio').first(),
        'hoy': hoy,
    })


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
def _formulario(request, form, ciclo=None):
    return render(request, 'ciclos/form.html', {'form': form, 'ciclo': ciclo, 'es_edicion': ciclo is not None})


@requiere_permisos('Alumnos.add_cicloescolar')
def ciclo_crear(request):
    form = CicloForm(request.POST if request.method == 'POST' else None, usuario=request.user)
    if request.method == 'POST':
        if form.is_valid():
            ciclo = form.save()
            messages.success(request, f'El ciclo {ciclo} fue registrado{" y es el ciclo actual" if ciclo.activo else ""}.')
            return redirect('ciclos:lista')
        if not form.pide_confirmacion:
            messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return _formulario(request, form)


@requiere_permisos('Alumnos.change_cicloescolar')
def ciclo_editar(request, pk):
    ciclo = get_object_or_404(CicloEscolar, pk=pk)
    form = CicloForm(request.POST if request.method == 'POST' else None, instance=ciclo, usuario=request.user)
    if request.method == 'POST':
        if form.is_valid():
            cambios = [CAMPOS[campo] for campo in CAMPOS if campo in form.changed_data]
            form.save()
            if cambios:
                from Usuarios.seguridad import ACCION_CAMBIO, registrar
                registrar(request.user, ciclo, ACCION_CAMBIO,
                          f'Cambió {", ".join(cambios)}: {ciclo.nombre}, {ciclo.fecha_inicio:%d/%m/%Y} al {ciclo.fecha_fin:%d/%m/%Y}.')
            messages.success(request, f'El ciclo {ciclo} se actualizó.')
            return redirect('ciclos:lista')
        if not form.pide_confirmacion:
            messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
        ciclo = CicloEscolar.objects.get(pk=pk)   # el título y las migas, con lo guardado (no con lo que se escribió)
    return _formulario(request, form, ciclo)


# ---------------------------------------------------------------------------
# Detalle
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.view_cicloescolar')
def ciclo_detalle(request, pk):
    ciclo = get_object_or_404(CicloEscolar.objects.select_related('activado_por', 'cerrado_por'), pk=pk)
    filas = resumen.por_grado_y_grupo(ciclo)
    total_activas = sum(fila['activas'] for fila in filas)
    total_bajas = sum(fila['bajas'] for fila in filas)
    vigente = ciclo.estado != CICLO_CERRADO

    # Ciclo anterior con alumnos inscritos (de ahí se reinscribe a los que siguen) y ciclo anterior con plan de
    # materias (de ahí se copian las materias y los horarios)
    origen = origen_plan = None
    if vigente:
        anteriores = CicloEscolar.objects.filter(fecha_inicio__lt=ciclo.fecha_inicio).distinct().order_by('-fecha_inicio')
        origen = anteriores.filter(inscripciones__activa=True).first()
        origen_plan = anteriores.filter(materias_grado__activa=True).first()

    usuario = request.user
    puede_cambiar = usuario.has_perm('Alumnos.change_cicloescolar')
    return render(request, 'ciclos/detalle.html', {
        'ciclo': ciclo,
        'filas': filas,
        'total_activas': total_activas,
        'total_bajas': total_bajas,
        # Alumnos activos que todavía no tienen inscripción (de ningún tipo) en este ciclo
        'sin_inscribir': alumnos_sin_inscribir(ciclo).count(),
        'origen_sugerido': origen,
        'origen_plan': origen_plan,
        'materias_del_ciclo': MateriaGrado.objects.filter(ciclo=ciclo, activa=True).count(),
        'otro_actual': ciclo_actual() if not ciclo.activo else None,
        'dias_de_clase': resumen.dias_de_clase_por_nivel(ciclo),
        'comparacion': resumen.comparacion_con_anterior(ciclo),
        'preparacion': resumen.preparacion(ciclo, usuario, origen_plan) if vigente else [],
        'pendientes': pendientes_de_cierre(ciclo, usuario) if puede_cambiar and ciclo.activo else [],
        # Bachillerato por semestres: los semestres del ciclo y lo que impide cerrarlo
        'semestres': _semestres_del_detalle(ciclo),
        'impide_cerrar': semestres.impide_cerrar_ciclo(ciclo) if ciclo.activo else [],
        'tiene_preparatoria': ciclo.semestres.exists() or MateriaGrado.objects.filter(ciclo=ciclo, grado__nivel='PREPARATORIA').exists(),
        'al_activar': avisos_al_activar(ciclo) if puede_cambiar and not ciclo.activo else None,
        'impide_borrar': ligado(ciclo) if usuario.has_perm('Alumnos.delete_cicloescolar') else None,
        # Días sin clases de las fechas del ciclo; se agregan solo al actual o a uno próximo
        'dias_sin_clases': dias_sin_clases_registrados(ciclo=ciclo),
        'dia_form': DiaNoLectivoForm(initial={'ciclo': ciclo}) if vigente and usuario.has_perm('Alumnos.add_dianolectivo') else None,
        'hoy': timezone.localdate(),
    })


@requiere_permisos('Alumnos.view_cicloescolar')
def dias_sin_clases(request):
    """Los días sin clases del ciclo actual (o del que sigue, o del más reciente): enlace fijo para otras pantallas."""
    ciclo = (
        ciclo_actual()
        or CicloEscolar.objects.proximos().order_by('fecha_inicio').first()
        or CicloEscolar.objects.order_by('-fecha_inicio').first()
    )
    if ciclo is None:
        return redirect('ciclos:lista')
    return redirect(f'{ciclo.get_absolute_url()}#dias-sin-clases')


# ---------------------------------------------------------------------------
# Acciones
# ---------------------------------------------------------------------------
@require_POST
@requiere_permisos('Alumnos.change_cicloescolar')
def ciclo_establecer_actual(request, pk):
    ciclo = get_object_or_404(CicloEscolar, pk=pk)
    if ciclo.activo:
        messages.info(request, f'El ciclo {ciclo} ya es el ciclo actual.')
        return redirect(ciclo)

    anterior = activar_ciclo(ciclo, request.user)
    aviso = f' El ciclo {anterior} dejó de ser el actual.' if anterior else ''
    messages.success(request, f'El ciclo {ciclo} es ahora el ciclo actual.{aviso}')
    return redirect(ciclo)


@require_POST
@requiere_permisos('Alumnos.change_cicloescolar')
def ciclo_cerrar(request, pk):
    """Cerrar es lógico: el ciclo deja de ser el actual, pero conserva sus inscripciones y su historial."""
    ciclo = get_object_or_404(CicloEscolar, pk=pk)
    if not ciclo.activo:
        messages.info(request, f'El ciclo {ciclo} no es el ciclo actual.')
        return redirect(ciclo)
    impide = semestres.impide_cerrar_ciclo(ciclo)
    if impide:
        messages.error(request, 'No se cerró el ciclo. ' + ' '.join(impide))
        return redirect(ciclo)

    cerrar_ciclo(ciclo, request.user)
    messages.success(
        request,
        f'El ciclo {ciclo} se cerró. Sus inscripciones y su historial se conservan; marca otro ciclo como actual para seguir inscribiendo.',
    )
    return redirect(ciclo)


@require_POST
@requiere_permisos('Alumnos.delete_cicloescolar')
def ciclo_eliminar(request, pk):
    """Borra un ciclo creado por error: solo si todavía no tiene nada ligado (y no es el actual)."""
    ciclo = get_object_or_404(CicloEscolar, pk=pk)
    impide = ligado(ciclo)
    if impide:
        messages.error(request, f'El ciclo {ciclo} no se puede borrar: {", ".join(impide)}.')
        return redirect(ciclo)
    from Usuarios.seguridad import ACCION_BAJA, registrar
    nombre = str(ciclo)
    registrar(request.user, ciclo, ACCION_BAJA, f'Borró el ciclo {nombre} ({ciclo.fecha_inicio:%d/%m/%Y} al {ciclo.fecha_fin:%d/%m/%Y}).')
    ciclo.delete()
    messages.success(request, f'Se borró el ciclo {nombre}.')
    return redirect('ciclos:lista')


# ---------------------------------------------------------------------------
# Semestres de bachillerato (pedido del 2026-10-28)
# ---------------------------------------------------------------------------
def _semestres_del_detalle(ciclo):
    """Los semestres del ciclo con sus periodos y cuántos extraordinarios o regularizaciones siguen abiertos."""
    lista = list(ciclo.semestres.select_related('cerrado_por', 'abierto_por').prefetch_related('periodos'))
    abiertos = semestres.procesos_abiertos_del_ciclo(ciclo) if any(s.cerrado for s in lista) else {}
    for semestre in lista:
        semestre.procesos_abiertos = abiertos.get(semestre, 0)
        semestre.lista_periodos = sorted(semestre.periodos.all(), key=lambda p: p.fecha_inicio)
    return lista


def _semestre(pk):
    return get_object_or_404(Semestre.objects.select_related('ciclo', 'cerrado_por', 'abierto_por'), pk=pk)


@requiere_permisos('Alumnos.change_cicloescolar')
def semestres_fechas(request, pk):
    """Las fechas del semestre A y del B del ciclo (los crea la primera vez)."""
    ciclo = get_object_or_404(CicloEscolar, pk=pk)
    if ciclo.estado == CICLO_CERRADO:
        messages.error(request, f'El ciclo {ciclo} está cerrado: sus semestres ya no cambian.')
        return redirect(ciclo)
    form = SemestresForm(request.POST or None, ciclo=ciclo)
    if request.method == 'POST':
        if form.is_valid():
            nuevos = not form.existentes
            semestres.guardar_fechas(ciclo, form.cleaned_data['fechas'], request.user)
            messages.success(request, f'Se {"crearon" if nuevos else "guardaron"} los semestres del ciclo {ciclo}.'
                                      + (' Ábrelos cuando empiecen: mientras estén pendientes no se capturan sus calificaciones.' if nuevos else ''))
            return redirect(f'{ciclo.get_absolute_url()}#semestres')
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return render(request, 'ciclos/semestres_form.html', {'ciclo': ciclo, 'form': form})


@requiere_permisos('Alumnos.view_cicloescolar')
def semestre_detalle(request, pk):
    """El semestre: estado, periodos, resumen por materia (completas, pendientes y procesos abiertos) y bitácora."""
    semestre = _semestre(pk)
    datos = semestres.resumen(semestre)
    usuario = request.user
    puede = semestres.puede_gestionar(usuario)
    return render(request, 'ciclos/semestre.html', {
        'semestre': semestre, 'ciclo': semestre.ciclo, 'datos': datos,
        'problemas': semestres.problemas_para_cerrar(semestre, datos) if semestre.abierto else [],
        'puede_gestionar': puede and semestre.ciclo.estado != CICLO_CERRADO,
        'puede_reabrir': semestres.puede_reabrir(usuario) and semestre.cerrado and semestre.ciclo.estado != CICLO_CERRADO,
        'cambios': semestre.cambios.exclude(accion=CambioSemestre.EXAMEN).select_related('usuario')[:30],
        'cambios_al_recerrar': semestres.cambios_desde_reapertura(semestre) if semestre.cerrado else [],
        'estados': calculo_semestral.ESTADOS,
    })


@require_POST
@requiere_permisos('Alumnos.change_cicloescolar')
def semestre_abrir(request, pk):
    semestre = _semestre(pk)
    try:
        semestres.abrir(semestre, request.user)
    except semestres.SemestreRechazado as error:
        messages.error(request, error.mensaje)
    else:
        messages.success(request, f'Se abrió el {semestre.en_frase} del ciclo {semestre.ciclo}: ya se capturan sus periodos y exámenes.')
    return redirect(f'{semestre.ciclo.get_absolute_url()}#semestres')


@requiere_permisos('Alumnos.change_cicloescolar')
def semestre_cerrar(request, pk):
    """Confirmación con el resumen y cierre de la evaluación ordinaria (no cierra el ciclo ni el otro semestre)."""
    semestre = _semestre(pk)
    datos = semestres.resumen(semestre)
    problemas = semestres.problemas_para_cerrar(semestre, datos)
    if request.method == 'POST':
        try:
            semestres.cerrar(semestre, request.user)
        except semestres.SemestreRechazado as error:
            messages.error(request, f'No se cerró: {error.mensaje}')
            return redirect('ciclos:semestre', pk=semestre.pk)
        procesos = datos.procesos_abiertos
        messages.success(request, f'Se cerró la evaluación ordinaria del {semestre.en_frase}. El ciclo {semestre.ciclo} sigue abierto.'
                                  + (f' Quedan {procesos} extraordinario(s) o regularización(es) por capturar.' if procesos else ''))
        return redirect('ciclos:semestre', pk=semestre.pk)
    return render(request, 'ciclos/semestre_cerrar.html', {
        'semestre': semestre, 'datos': datos, 'problemas': problemas, 'volver': reverse('ciclos:semestre', args=[semestre.pk]),
    })


@requiere_permisos('Alumnos.change_cicloescolar', 'Calificaciones.reabrir')
def semestre_reabrir(request, pk):
    semestre = _semestre(pk)
    if not semestre.cerrado:
        messages.info(request, f'El {semestre.en_frase} no está cerrado.')
        return redirect('ciclos:semestre', pk=semestre.pk)
    form = MotivoForm(request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            try:
                semestres.reabrir(semestre, form.cleaned_data['motivo'], request.user)
            except semestres.SemestreRechazado as error:
                messages.error(request, error.mensaje)
            else:
                messages.success(request, f'Se reabrió el {semestre.en_frase}. Su cierre anterior y tu motivo quedaron en la bitácora; '
                                          'al volver a cerrarlo se registrarán las calificaciones definitivas que cambien.')
            return redirect('ciclos:semestre', pk=semestre.pk)
        messages.error(request, 'Escribe el motivo de la reapertura.')
    return render(request, 'ciclos/semestre_reabrir.html', {
        'semestre': semestre, 'form': form, 'volver': reverse('ciclos:semestre', args=[semestre.pk]),
    })
