import csv
from itertools import groupby

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from Alumnos.academico import alumnos_sin_inscribir, ciclo_actual, motivo_no_inscribible, siguiente_grado
from Alumnos.models import ORDEN_NIVELES, Alumno, CicloEscolar, Grado, Inscripcion
from Alumnos.utils import proteger_celda_csv
from CISAHUAYO.paginacion import OPCIONES_POR_PAGINA, POR_PAGINA_DEFECTO, paginar
from CISAHUAYO.permisos import requiere_permisos

from .forms import FiltroInscripcionesForm, InscripcionForm, PromocionForm


def _url_de_lista(ciclo_id):
    """El listado del ciclo indicado (para volver y ver el registro recién guardado)."""
    return f"{reverse('inscripciones:lista')}?ciclo={ciclo_id}"


def _filtro(request):
    """Filtros del listado. Sin `?ciclo=` se muestra el ciclo actual; con `?ciclo=` vacío, todos."""
    datos = request.GET.copy()
    actual = ciclo_actual()
    por_defecto = 'ciclo' not in datos and actual is not None
    if por_defecto:
        datos['ciclo'] = str(actual.pk)
    return FiltroInscripcionesForm(datos), por_defecto


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.view_inscripcion')
def inscripcion_lista(request):
    filtro, ciclo_por_defecto = _filtro(request)
    inscripciones = filtro.filtrar(Inscripcion.objects.select_related('alumno', 'grado', 'ciclo'))
    pagina, rango_paginas, por_pagina = paginar(request, inscripciones)

    # Los conteos de las pestañas respetan los demás filtros
    conteos = filtro.filtrar(Inscripcion.objects.all(), con_estado=False).order_by().aggregate(
        activas=Count('pk', filter=Q(activa=True)),
        bajas=Count('pk', filter=Q(activa=False)),
    )

    # Resumen del ciclo elegido: cuántos alumnos hay por nivel y cuántos faltan por inscribir
    ciclo = filtro.activos.get('ciclo')
    resumen = None
    if ciclo:
        por_nivel = dict(
            Inscripcion.objects.filter(ciclo=ciclo, activa=True).order_by()
            .values_list('grado__nivel').annotate(total=Count('pk'))
        )
        niveles = dict(Grado.NIVEL_CHOICES)
        resumen = {
            'ciclo': ciclo,
            'inscritos': sum(por_nivel.values()),
            'niveles': [{'nombre': niveles[n], 'total': por_nivel[n]} for n in ORDEN_NIVELES if por_nivel.get(n)],
            'sin_inscribir': alumnos_sin_inscribir(ciclo).count(),
        }

    activos = filtro.activos
    actual = ciclo_actual()
    return render(request, 'inscripciones/lista.html', {
        'filtro': filtro,
        'pagina': pagina,
        'rango_paginas': rango_paginas,
        'por_pagina': por_pagina,
        'por_pagina_defecto': POR_PAGINA_DEFECTO,
        'opciones_por_pagina': OPCIONES_POR_PAGINA,
        'conteos': conteos,
        'viendo_bajas': activos.get('estado') == 'BAJA',
        'resumen': resumen,
        'ciclo_actual': actual,
        # El ciclo actual es el valor por defecto: elegirlo no cuenta como un filtro aplicado
        'filtros_activos': {
            k: v for k, v in activos.items()
            if k not in ('orden', 'estado') and not (k == 'ciclo' and (ciclo_por_defecto or v == actual))
        },
    })


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
def _alumno_elegido(form):
    """El alumno que trae el formulario (para mostrarlo ya seleccionado), si lo hay."""
    valor = str(form['alumno'].value() or '') if 'alumno' in form.fields else ''
    return Alumno.objects.filter(pk=valor).first() if valor.isdigit() else None


def _iniciales(request):
    """Datos que puede traer la URL: ?alumno=, ?ciclo= y ?grado= (desde el perfil o un ciclo)."""
    return {
        campo: request.GET[campo] for campo in ('alumno', 'ciclo', 'grado') if request.GET.get(campo, '').isdigit()
    }


def _error_de_formulario(request):
    messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')


@requiere_permisos('Alumnos.add_inscripcion')
def inscripcion_crear(request):
    if request.method == 'POST':
        form = InscripcionForm(request.POST)
        if form.is_valid():
            inscripcion = form.save()
            messages.success(request, f'{inscripcion.alumno} fue inscrito en {inscripcion.grado} ({inscripcion.ciclo}).')
            return redirect(_url_de_lista(inscripcion.ciclo_id))
        _error_de_formulario(request)
    else:
        form = InscripcionForm(initial=_iniciales(request))

    return render(request, 'inscripciones/form.html', {
        'form': form,
        'es_edicion': False,
        'alumno': _alumno_elegido(form),
        'existente': form.existente,
        'url_alumnos': reverse('alumnos:buscar'),
    })


@requiere_permisos('Alumnos.change_inscripcion')
def inscripcion_editar(request, pk):
    inscripcion = get_object_or_404(Inscripcion.objects.select_related('alumno', 'ciclo', 'grado'), pk=pk)
    form = InscripcionForm(request.POST if request.method == 'POST' else None, instance=inscripcion)
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            messages.success(request, f'La inscripción de {inscripcion.alumno} se actualizó: {inscripcion.grado} ({inscripcion.ciclo}).')
            return redirect(_url_de_lista(inscripcion.ciclo_id))
        _error_de_formulario(request)

    return render(request, 'inscripciones/form.html', {
        'form': form,
        'es_edicion': True,
        'inscripcion': inscripcion,
        'alumno': inscripcion.alumno,
    })


# ---------------------------------------------------------------------------
# Baja lógica
# ---------------------------------------------------------------------------
@require_POST
@requiere_permisos('Alumnos.delete_inscripcion')
def inscripcion_baja(request, pk):
    """Baja lógica: la inscripción deja de contar, pero se conserva (y se puede reactivar)."""
    inscripcion = get_object_or_404(Inscripcion.objects.select_related('alumno', 'ciclo', 'grado'), pk=pk)
    if not inscripcion.activa:
        messages.info(request, f'La inscripción de {inscripcion.alumno} ya estaba dada de baja.')
    else:
        inscripcion.activa = False
        inscripcion.suspendida_por_baja = False   # baja a mano: no vuelve sola al reactivar al estudiante
        inscripcion.save(update_fields=['activa', 'suspendida_por_baja'])
        messages.success(
            request,
            f'La inscripción de {inscripcion.alumno} en {inscripcion.grado} ({inscripcion.ciclo}) se dio de baja. '
            'Se conserva y puedes reactivarla desde el filtro «Bajas».',
        )
    return redirect(_url_de_lista(inscripcion.ciclo_id))


@require_POST
@requiere_permisos('Alumnos.change_inscripcion')
def inscripcion_reactivar(request, pk):
    inscripcion = get_object_or_404(Inscripcion.objects.select_related('alumno', 'ciclo', 'grado'), pk=pk)
    motivo = motivo_no_inscribible(inscripcion.alumno)
    if inscripcion.activa:
        messages.info(request, f'La inscripción de {inscripcion.alumno} ya está activa.')
    elif motivo:
        messages.error(request, f'No se pudo reactivar la inscripción. {motivo}')
    else:
        inscripcion.activa = True
        inscripcion.suspendida_por_baja = False
        inscripcion.save(update_fields=['activa', 'suspendida_por_baja'])
        messages.success(request, f'La inscripción de {inscripcion.alumno} en {inscripcion.grado} ({inscripcion.ciclo}) fue reactivada.')
    return redirect(_url_de_lista(inscripcion.ciclo_id))


# ---------------------------------------------------------------------------
# Exportación
# ---------------------------------------------------------------------------
@require_GET
@requiere_permisos('Alumnos.view_inscripcion')
def inscripcion_exportar(request):
    filtro, _ = _filtro(request)
    inscripciones = filtro.filtrar(Inscripcion.objects.select_related('alumno', 'grado', 'ciclo'))

    respuesta = HttpResponse(content_type='text/csv; charset=utf-8')
    respuesta['Content-Disposition'] = f'attachment; filename="inscripciones-{timezone.localdate():%Y-%m-%d}.csv"'
    respuesta.write('﻿')  # para que Excel reconozca los acentos
    escritor = csv.writer(respuesta)
    escritor.writerow(['Referencia', 'Apellido paterno', 'Apellido materno', 'Nombre', 'Ciclo', 'Grado', 'Fecha de inscripción', 'Estado'])
    for inscripcion in inscripciones.iterator(chunk_size=500):
        alumno = inscripcion.alumno
        escritor.writerow([proteger_celda_csv(valor) for valor in [
            alumno.referencia, alumno.apellido_paterno, alumno.apellido_materno, alumno.nombre,
            inscripcion.ciclo.nombre, str(inscripcion.grado), f'{inscripcion.fecha_inscripcion:%d/%m/%Y}',
            'Activa' if inscripcion.activa else 'Baja',
        ]])
    return respuesta


# ---------------------------------------------------------------------------
# Reinscripción en bloque: de un ciclo al siguiente
# ---------------------------------------------------------------------------
def _plan_de_promocion(origen, destino):
    """Qué pasaría con los alumnos del ciclo de origen, grado por grado.

    Solo se reinscribe a quien tiene inscripción activa en el origen, sigue activo y todavía no tiene
    inscripción en el destino. Devuelve (filas en orden escolar, grados activos disponibles).
    """
    grados = list(Grado.objects.academicos())
    posicion = {grado.pk: indice for indice, grado in enumerate(grados)}
    activos = [grado for grado in grados if grado.activo]
    ya_inscritos = set(Inscripcion.objects.filter(ciclo=destino).values_list('alumno_id', flat=True))

    filas = {}
    for inscripcion in Inscripcion.objects.filter(ciclo=origen, activa=True).select_related('alumno', 'grado'):
        fila = filas.setdefault(
            inscripcion.grado_id, {'grado': inscripcion.grado, 'alumnos': [], 'ya_inscritos': 0, 'no_activos': 0},
        )
        if inscripcion.alumno_id in ya_inscritos:
            fila['ya_inscritos'] += 1
        elif inscripcion.alumno.estatus != 'ACTIVO':
            fila['no_activos'] += 1
        else:
            fila['alumnos'].append(inscripcion.alumno_id)

    plan = sorted(filas.values(), key=lambda fila: posicion[fila['grado'].pk])
    for fila in plan:
        siguiente = siguiente_grado(fila['grado'], activos)
        fila['cantidad'] = len(fila['alumnos'])
        fila['sugerido'] = str(siguiente.pk) if siguiente else 'omitir'
    return plan, activos


def _grupos_de_destino(activos):
    """Los grados de destino agrupados por nivel, para las listas desplegables."""
    return [
        {'nombre': dict(Grado.NIVEL_CHOICES)[nivel], 'grados': list(grupo)}
        for nivel, grupo in groupby(activos, key=lambda grado: grado.nivel)
    ]


def _sugerir_ciclos(ciclos):
    """Origen y destino propuestos: del ciclo actual al próximo que empiece primero."""
    proximos = sorted((c for c in ciclos if c.estado == 'PROXIMO'), key=lambda c: c.fecha_inicio)
    origen = ciclo_actual()
    return (origen, proximos[0]) if origen and proximos else (None, None)


@requiere_permisos('Alumnos.add_inscripcion')
def inscripcion_promocion(request):
    if request.method == 'POST':
        return _ejecutar_promocion(request)

    ciclos = list(CicloEscolar.objects.all())
    datos = request.GET.copy()
    if not datos.get('origen') and not datos.get('destino'):
        origen, destino = _sugerir_ciclos(ciclos)
        if origen:
            datos['origen'], datos['destino'] = str(origen.pk), str(destino.pk)

    if datos.get('origen') or datos.get('destino'):
        datos['fecha'] = datos.get('fecha') or timezone.localdate().isoformat()  # se muestra la de hoy
    form = PromocionForm(datos or None)
    plan = activos = origen = destino = None
    if form.is_bound and form.is_valid():
        origen, destino = form.cleaned_data['origen'], form.cleaned_data['destino']
        plan, activos = _plan_de_promocion(origen, destino)

    return render(request, 'inscripciones/promocion.html', {
        'form': form,
        'origen': origen,
        'destino': destino,
        'plan': plan,
        'grupos_destino': _grupos_de_destino(activos) if activos else [],
        'total_a_reinscribir': sum(fila['cantidad'] for fila in plan) if plan else 0,
        # Hace falta un ciclo de destino (actual o próximo) distinto al de origen, o sea, al menos dos ciclos
        'hay_destinos': form.fields['destino'].queryset.exists() and len(ciclos) > 1,
        'puede_egresar': request.user.has_perm('Alumnos.change_alumno'),
    })


def _volver_a_promocion(request, origen, destino):
    return redirect(f"{reverse('inscripciones:promocion')}?origen={origen.pk}&destino={destino.pk}")


def _ejecutar_promocion(request):
    form = PromocionForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Elige un ciclo de origen y otro de destino distintos.')
        return redirect('inscripciones:promocion')

    origen, destino, fecha = form.cleaned_data['origen'], form.cleaned_data['destino'], form.cleaned_data['fecha']
    plan, activos = _plan_de_promocion(origen, destino)

    permitidos = {str(grado.pk) for grado in activos} | {'omitir', 'egresar'}
    decisiones = {fila['grado'].pk: request.POST.get(f"grado_{fila['grado'].pk}", 'omitir') for fila in plan}
    if any(valor not in permitidos for valor in decisiones.values()):
        messages.error(request, 'Alguno de los grados de destino ya no está disponible. Revisa la vista previa y vuelve a intentarlo.')
        return _volver_a_promocion(request, origen, destino)
    if 'egresar' in decisiones.values() and not request.user.has_perm('Alumnos.change_alumno'):
        messages.error(request, 'No tienes permiso para marcar estudiantes como egresados.')
        return _volver_a_promocion(request, origen, destino)

    nuevas, egresan = [], []
    for fila in plan:
        decision = decisiones[fila['grado'].pk]
        if decision == 'omitir':
            continue
        if decision == 'egresar':
            egresan.extend(fila['alumnos'])
        else:
            nuevas.extend(
                Inscripcion(alumno_id=alumno_id, ciclo=destino, grado_id=int(decision), fecha_inscripcion=fecha)
                for alumno_id in fila['alumnos']
            )

    try:
        with transaction.atomic():
            Inscripcion.objects.bulk_create(nuevas)
            if egresan:
                Alumno.objects.filter(pk__in=egresan, estatus='ACTIVO').update(estatus='EGRESADO')
    except IntegrityError:  # alguien inscribió a uno de ellos mientras tanto
        messages.error(request, 'Mientras revisabas, otra persona inscribió a alguno de estos estudiantes. No se guardó nada: vuelve a revisar.')
        return _volver_a_promocion(request, origen, destino)

    partes = []
    if nuevas:
        partes.append(f'Se reinscribió a {len(nuevas)} estudiante{"s" if len(nuevas) != 1 else ""} en {destino}.')
    if egresan:
        partes.append(f'{len(egresan)} estudiante{"s" if len(egresan) != 1 else ""} pasó{"" if len(egresan) == 1 else "aron"} a estatus «Egresado».')
    if partes:
        messages.success(request, ' '.join(partes))
    else:
        messages.info(request, 'No había estudiantes por reinscribir con esas opciones.')
    return redirect(_url_de_lista(destino.pk))
