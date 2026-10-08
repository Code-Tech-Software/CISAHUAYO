import csv
from collections import defaultdict

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Prefetch, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from Alumnos.academico import (
    asegurar_en_el_plan,
    ciclo_actual,
    ciclo_editable,
    motivo_para_no_agregar,
)
from Alumnos.docentes import asignar_profesor, descripcion_del_cambio, deshabilitar, habilitar, profesores_por_nivel
from Alumnos.horarios import con_resumen_de_horario, formatear_duracion, se_empalman
from Alumnos.models import CicloEscolar, Grado, HorarioMateria, Materia, MateriaGrado, Profesor, orden_de_nivel
from Alumnos.utils import proteger_celda_csv
from CISAHUAYO.paginacion import OPCIONES_POR_PAGINA, POR_PAGINA_DEFECTO, paginar
from CISAHUAYO.permisos import requiere_alguno, requiere_permisos
from CISAHUAYO.redireccion import destino_seguro, solo_numeros
from Usuarios.seguridad import ACCION_ALTA, ACCION_CAMBIO, registrar

from .claves import clave_sugerida
from .forms import CopiarPlanForm, FiltroMateriasForm, MateriaForm


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------
def _plan_del_ciclo(ciclo):
    """Prefetch: las asignaciones vigentes de cada materia en el ciclo, con su grado y su profesor (en `plan_actual`)."""
    return Prefetch(
        'grados_materia',
        queryset=MateriaGrado.objects.filter(ciclo=ciclo, activa=True).select_related('grado', 'profesor')
        .order_by(orden_de_nivel('grado__nivel'), 'grado__numero'),
        to_attr='plan_actual',
    )


@requiere_permisos('Alumnos.view_materia')
def materia_lista(request):
    ciclo = ciclo_actual()
    filtro = FiltroMateriasForm(request.GET, ciclo=ciclo)
    materias = filtro.filtrar(Materia.objects.select_related('grado'))
    if ciclo:
        materias = materias.prefetch_related(_plan_del_ciclo(ciclo))
    pagina, rango_paginas, por_pagina = paginar(request, materias)

    conteos = filtro.filtrar(Materia.objects.all(), con_estado=False).order_by().aggregate(
        activas=Count('pk', filter=Q(activa=True)),
        bajas=Count('pk', filter=Q(activa=False)),
    )
    activos = filtro.activos
    return render(request, 'materias/lista.html', {
        'filtro': filtro,
        'pagina': pagina,
        'rango_paginas': rango_paginas,
        'por_pagina': por_pagina,
        'por_pagina_defecto': POR_PAGINA_DEFECTO,
        'opciones_por_pagina': OPCIONES_POR_PAGINA,
        'conteos': conteos,
        'viendo_bajas': activos.get('estado') == 'BAJA',
        'filtros_activos': {k: v for k, v in activos.items() if k != 'estado'},
        'ciclo': ciclo,
    })


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
def _formulario(request, form, materia=None):
    return render(request, 'materias/form.html', {'form': form, 'materia': materia, 'es_edicion': materia is not None})


@requiere_permisos('Alumnos.add_materia')
def materia_crear(request):
    ciclo = ciclo_actual()
    form = MateriaForm(
        request.POST if request.method == 'POST' else None,
        ciclo=ciclo if ciclo and ciclo_editable(ciclo) else None,
        puede_asignar_profesor=request.user.has_perm('Alumnos.change_materiagrado'),
    )
    if request.method == 'POST':
        if form.is_valid():
            profesor = form.cleaned_data.get('profesor')
            with transaction.atomic():
                materia = form.save()
                asignacion = form.asignacion
                cambios = []
                if asignacion is not None and profesor is not None:
                    cambios, _ = asignar_profesor([asignacion], profesor)
                    if cambios:
                        habilitar(profesor, [materia])   # quien la imparte, puede impartirla
                registrar(request.user, materia, ACCION_ALTA, f'Registrada con la clave {materia.clave}'
                          f'{f" para {materia.grado}" if materia.grado_id else ""}.')
                for cambio, anterior in cambios:
                    registrar(request.user, cambio, ACCION_CAMBIO, descripcion_del_cambio(cambio, anterior))

            detalle = ''
            if asignacion is not None:
                detalle = f' y se agregó al plan de {materia.grado} (ciclo {form.ciclo})'
                detalle += f'. La imparte {profesor}' if cambios else '. Queda sin profesor: asígnalo desde su perfil o en Asignaciones'
            elif materia.grado_id:
                detalle = f' para {materia.grado}'
            messages.success(request, f'La materia {materia} fue registrada con la clave {materia.clave}{detalle}.')
            return redirect('materias:lista')
        if not form.solo_falta_confirmar:
            messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return _formulario(request, form)


@require_GET
@requiere_alguno('Alumnos.add_materia', 'Alumnos.change_materia')
def materia_clave(request):
    """Para el formulario de materia (JSON): la clave libre que corresponde al nombre y a los grados elegidos."""
    grados = Grado.objects.filter(pk__in=solo_numeros(request.GET.getlist('grado')))
    excluir = request.GET.get('excluir', '')
    return JsonResponse({'sugerida': clave_sugerida(
        request.GET.get('nombre', ''), list(grados), excluir=int(excluir) if excluir.isdigit() else None,
    )})


@requiere_permisos('Alumnos.change_materia')
def materia_editar(request, pk):
    materia = get_object_or_404(Materia, pk=pk)
    form = MateriaForm(request.POST if request.method == 'POST' else None, instance=materia)
    if request.method == 'POST':
        if form.is_valid():
            with transaction.atomic():
                form.save()
            detalle = ''
            if form.cambio_de_grado and form.asignacion is not None:
                detalle = f' Su clase del ciclo {form.asignacion.ciclo} quedó en {materia.grado}.'
            elif form.cambio_de_grado:
                detalle = f' Ahora es de {materia.grado}.'
            for profesor in form.profesores_quitados:
                detalle += f' {profesor} dejó de impartirla porque no da clases en {materia.grado.get_nivel_display()}.'
            messages.success(request, f'La materia {materia} se actualizó.{detalle}')
            return redirect('materias:lista')
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return _formulario(request, form, materia)


# ---------------------------------------------------------------------------
# Perfil: su clase en el ciclo actual (una materia la imparte un solo grado)
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.view_materia')
def materia_detalle(request, pk):
    materia = get_object_or_404(Materia.objects.select_related('grado'), pk=pk)
    ciclo = ciclo_actual()
    editable = ciclo_editable(ciclo)

    # Su clase del ciclo actual: la del plan de su grado (una materia de antes de la regla podría tener más de una)
    clases = []
    if ciclo:
        clases = con_resumen_de_horario(
            MateriaGrado.objects.filter(materia=materia, ciclo=ciclo, activa=True)
            .select_related('grado', 'profesor').prefetch_related('horarios')
            .order_by(orden_de_nivel('grado__nivel'), 'grado__numero')
        )
    por_nivel = profesores_por_nivel()
    for clase in clases:
        clase.del_nivel = ','.join(str(pk) for pk in por_nivel.get(clase.grado.nivel, []))
    minutos = sum(clase.minutos for clase in clases)
    # Si se quitó del plan (o el ciclo empezó después de registrarla) se puede volver a poner en su grado
    puede_agregarse = (
        editable and materia.activa and materia.grado_id is not None and materia.grado.activo
        and not any(clase.grado_id == materia.grado_id for clase in clases)
    )
    historial = list(
        MateriaGrado.objects.filter(materia=materia, activa=True).exclude(ciclo=ciclo)
        .select_related('ciclo', 'grado', 'profesor').order_by('-ciclo__fecha_inicio', orden_de_nivel('grado__nivel'), 'grado__numero')
    )

    # Quién puede impartirla (habilitados) y quién la imparte de verdad en el ciclo actual
    habilitados = list(Profesor.objects.filter(habilitaciones__materia=materia))
    grados_de = defaultdict(list)
    for clase in clases:
        if clase.profesor_id:
            grados_de[clase.profesor_id].append(clase.grado)
    ids_habilitados = {profesor.pk for profesor in habilitados}
    for profesor in habilitados:
        profesor.grados_del_ciclo = grados_de.get(profesor.pk, [])
    sin_habilitar = list({c.profesor_id: c.profesor for c in clases if c.profesor_id and c.profesor_id not in ids_habilitados}.values())

    return render(request, 'materias/detalle.html', {
        'materia': materia,
        'habilitados': habilitados,
        'habilitados_csv': ','.join(str(profesor.pk) for profesor in habilitados if profesor.estatus == 'ACTIVO'),
        'sin_habilitar': sin_habilitar,
        'profesores_por_habilitar': list(Profesor.objects.filter(estatus='ACTIVO').exclude(pk__in=ids_habilitados)) if materia.activa else [],
        'ciclo': ciclo,
        'editable': editable,
        'clases': clases,
        'puede_agregarse': puede_agregarse,
        'historial': historial,
        'horas_semanales': formatear_duracion(minutos) if minutos else '',
        'profesores_activos': list(Profesor.objects.filter(estatus='ACTIVO')) if editable else [],
        'asignaciones_actuales': len(clases) if materia.activa else 0,
        'esta_de_baja': not materia.activa,
    })


# ---------------------------------------------------------------------------
# Profesores que pueden impartirla (habilitación)
# ---------------------------------------------------------------------------
def _volver_a_la_materia(request, materia):
    return redirect(destino_seguro(request, f'{materia.get_absolute_url()}#profesores'))


@require_POST
@requiere_permisos('Alumnos.change_profesor')
def materia_habilitar(request, pk):
    """Agrega profesores a los que pueden impartir la materia. Sirve para sugerirlos al asignar; no asigna nada."""
    materia = get_object_or_404(Materia, pk=pk)
    if not materia.activa:
        messages.error(request, f'{materia} está dada de baja. Reactívala antes de cambiar quién puede impartirla.')
        return _volver_a_la_materia(request, materia)

    profesores = list(Profesor.objects.filter(pk__in=solo_numeros(request.POST.getlist('profesor')), estatus='ACTIVO'))
    if not profesores:
        messages.error(request, 'Elige al menos un profesor.')
        return _volver_a_la_materia(request, materia)

    agregados = []
    with transaction.atomic():
        for profesor in profesores:
            if habilitar(profesor, [materia]):
                agregados.append(profesor)
                registrar(request.user, profesor, ACCION_CAMBIO, f'Habilitado para impartir: {materia.nombre}.')
    if agregados:
        nombres = ', '.join(str(profesor) for profesor in agregados)
        registrar(request.user, materia, ACCION_CAMBIO, f'Pueden impartirla ahora: {nombres}.')
        messages.success(request, f'Pueden impartir {materia}: {nombres}.')
    else:
        messages.info(request, 'Esos profesores ya podían impartirla.')
    return _volver_a_la_materia(request, materia)


@require_POST
@requiere_permisos('Alumnos.change_profesor')
def materia_deshabilitar(request, pk):
    """Quita profesores de los que pueden impartir la materia. No toca lo que ya imparten: eso se quita en las asignaciones."""
    materia = get_object_or_404(Materia, pk=pk)
    ids = solo_numeros(request.POST.getlist('profesor'))
    profesores = list(Profesor.objects.filter(pk__in=ids, habilitaciones__materia=materia))
    if not profesores:
        messages.error(request, 'Elige al menos un profesor.')
        return _volver_a_la_materia(request, materia)

    with transaction.atomic():
        for profesor in profesores:
            deshabilitar(profesor, [materia])
            registrar(request.user, profesor, ACCION_CAMBIO, f'Ya no está habilitado para impartir: {materia.nombre}.')
    nombres = ', '.join(str(profesor) for profesor in profesores)
    registrar(request.user, materia, ACCION_CAMBIO, f'Ya no pueden impartirla: {nombres}.')
    messages.success(request, f'{nombres} ya no figura{"n" if len(profesores) != 1 else ""} entre quienes pueden impartir {materia}.')

    siguen = MateriaGrado.objects.filter(materia=materia, profesor__in=profesores, ciclo__activo=True, activa=True).count()
    if siguen:
        messages.info(
            request,
            f'Siguen impartiéndola en {siguen} grupo{"s" if siguen != 1 else ""} del ciclo actual: '
            'si ya no la darán, cámbialos desde «Grados que la imparten».',
        )
    return _volver_a_la_materia(request, materia)


# ---------------------------------------------------------------------------
# Baja lógica
# ---------------------------------------------------------------------------
@require_POST
@requiere_permisos('Alumnos.delete_materia')
def materia_baja(request, pk):
    """Baja lógica: la materia deja de ofrecerse al asignarla, pero conserva su historial."""
    materia = get_object_or_404(Materia, pk=pk)
    if not materia.activa:
        messages.info(request, f'La materia {materia} ya estaba dada de baja.')
        return redirect('materias:lista')

    quitadas = 0
    with transaction.atomic():
        materia.activa = False
        materia.save(update_fields=['activa'])
        if request.POST.get('quitar_del_ciclo'):
            quitadas = MateriaGrado.objects.filter(materia=materia, ciclo__activo=True, activa=True).update(activa=False)

    aviso = f' También se quitó de {quitadas} grado{"s" if quitadas != 1 else ""} del ciclo actual.' if quitadas else ''
    messages.success(
        request,
        f'La materia {materia} fue dada de baja.{aviso} Su historial se conserva y puedes reactivarla desde el filtro «Bajas».',
    )
    return redirect('materias:lista')


@require_POST
@requiere_permisos('Alumnos.change_materia')
def materia_reactivar(request, pk):
    materia = get_object_or_404(Materia, pk=pk)
    if not materia.activa:
        with transaction.atomic():
            materia.activa = True
            materia.save(update_fields=['activa'])
            asignacion = asegurar_en_el_plan(materia)   # vuelve al plan de su grado en el ciclo actual
        detalle = f' Volvió al plan de {asignacion.grado} del ciclo {asignacion.ciclo}.' if asignacion else ''
        messages.success(request, f'La materia {materia} fue reactivada.{detalle}')
    return redirect('materias:lista')


# ---------------------------------------------------------------------------
# Asignar materias a grados (por ciclo)
# ---------------------------------------------------------------------------
@require_POST
@requiere_permisos('Alumnos.add_materiagrado')
def asignar(request):
    """Asigna materias a grados en un ciclo. Se usa desde el perfil de una materia (muchos grados) y desde el
    de un grado (muchas materias): se crean todas las combinaciones que falten y se reactivan las quitadas."""
    ciclo = get_object_or_404(CicloEscolar, pk=request.POST['ciclo']) if request.POST.get('ciclo', '').isdigit() else None
    if ciclo is None:
        messages.error(request, 'Elige un ciclo escolar.')
        return redirect(destino_seguro(request, reverse('materias:lista')))
    destino = destino_seguro(request, reverse('materias:lista'))
    if not ciclo_editable(ciclo):
        messages.error(request, f'El ciclo {ciclo} está cerrado: su plan de materias ya no se modifica.')
        return redirect(destino)

    materias = list(Materia.objects.filter(pk__in=solo_numeros(request.POST.getlist('materia')), activa=True))
    grados = list(Grado.objects.filter(pk__in=solo_numeros(request.POST.getlist('grado')), activo=True))
    if not materias or not grados:
        messages.error(request, 'Elige al menos una materia y un grado.')
        return redirect(destino)

    with transaction.atomic():
        existentes = {
            (mg.materia_id, mg.grado_id): mg
            for mg in MateriaGrado.objects.filter(ciclo=ciclo, materia__in=materias, grado__in=grados)
        }
        nuevas, reactivar, omitidas = [], [], []
        for materia in materias:
            # Una materia la imparte un solo grado: la que todavía no tiene grado toma el elegido, si es uno solo
            if not materia.grado_id and len(grados) > 1:
                omitidas.append(f'{materia} la imparte un solo grado: elige solo uno.')
                continue
            for grado in grados:
                motivo = motivo_para_no_agregar(materia, grado)
                if motivo:
                    omitidas.append(motivo)
                    continue
                if not materia.grado_id:
                    materia.grado = grado
                    materia.save(update_fields=['grado'])
                actual = existentes.get((materia.pk, grado.pk))
                if actual is None:
                    nuevas.append(MateriaGrado(ciclo=ciclo, grado=grado, materia=materia))
                elif not actual.activa:
                    reactivar.append(actual.pk)
        MateriaGrado.objects.bulk_create(nuevas)
        MateriaGrado.objects.filter(pk__in=reactivar).update(activa=True)

    total = len(nuevas) + len(reactivar)
    if total:
        messages.success(request, f'Se agregaron {total} asignaci{"ones" if total != 1 else "ón"} de materia a grados en el ciclo {ciclo}.')
    elif not omitidas:
        messages.info(request, 'Esas materias ya estaban asignadas a esos grados.')
    for motivo in omitidas[:5]:
        messages.error(request, f'No se agregó. {motivo}')
    if len(omitidas) > 5:
        messages.error(request, f'Y {len(omitidas) - 5} más con el mismo problema.')
    return redirect(destino)


@require_POST
@requiere_permisos('Alumnos.delete_materiagrado')
def asignacion_quitar(request, pk):
    """Quitar es lógico: la materia deja de impartirse en ese grado, pero se conservan su horario y su asistencia."""
    asignacion = get_object_or_404(MateriaGrado.objects.select_related('materia', 'grado', 'ciclo'), pk=pk)
    destino = destino_seguro(request, asignacion.materia.get_absolute_url())
    if not ciclo_editable(asignacion.ciclo):
        messages.error(request, f'El ciclo {asignacion.ciclo} está cerrado: su plan de materias ya no se modifica.')
    elif not asignacion.activa:
        messages.info(request, f'{asignacion.materia} ya estaba quitada de {asignacion.grado}.')
    else:
        asignacion.activa = False
        asignacion.save(update_fields=['activa'])
        messages.success(
            request,
            f'{asignacion.materia} se quitó de {asignacion.grado} ({asignacion.ciclo}). Su horario y su asistencia se conservan; puedes volver a asignarla.',
        )
    return redirect(destino)


@require_POST
@requiere_permisos('Alumnos.change_materiagrado')
def asignacion_reactivar(request, pk):
    asignacion = get_object_or_404(MateriaGrado.objects.select_related('materia', 'grado', 'ciclo'), pk=pk)
    destino = destino_seguro(request, asignacion.materia.get_absolute_url())
    if not ciclo_editable(asignacion.ciclo):
        messages.error(request, f'El ciclo {asignacion.ciclo} está cerrado: su plan de materias ya no se modifica.')
    elif not asignacion.materia.activa:
        messages.error(request, f'La materia {asignacion.materia} está dada de baja: reactívala primero.')
    elif not asignacion.grado.activo:
        messages.error(request, f'El grado {asignacion.grado} está dado de baja: reactívalo primero.')
    elif not asignacion.activa and (motivo := motivo_para_no_agregar(asignacion.materia, asignacion.grado)):
        messages.error(request, f'No se reactivó. {motivo}')
    elif not asignacion.activa:
        with transaction.atomic():
            asignacion.activa = True
            asignacion.save(update_fields=['activa'])
            if not asignacion.materia.grado_id:
                asignacion.materia.grado = asignacion.grado
                asignacion.materia.save(update_fields=['grado'])
        messages.success(request, f'{asignacion.materia} volvió a impartirse en {asignacion.grado} ({asignacion.ciclo}).')
    return redirect(destino)


# ---------------------------------------------------------------------------
# Exportación
# ---------------------------------------------------------------------------
@require_GET
@requiere_permisos('Alumnos.view_materia')
def materia_exportar(request):
    ciclo = ciclo_actual()
    filtro = FiltroMateriasForm(request.GET, ciclo=ciclo)
    materias = filtro.filtrar(Materia.objects.select_related('grado'))
    if ciclo:
        materias = materias.prefetch_related(_plan_del_ciclo(ciclo))

    respuesta = HttpResponse(content_type='text/csv; charset=utf-8')
    respuesta['Content-Disposition'] = f'attachment; filename="materias-{timezone.localdate():%Y-%m-%d}.csv"'
    respuesta.write('﻿')  # para que Excel reconozca los acentos
    escritor = csv.writer(respuesta)
    escritor.writerow(['Clave', 'Nombre', 'Grado', 'Equivalencia', 'Estado', f'Profesor en el ciclo actual{f" ({ciclo})" if ciclo else ""}'])
    for materia in materias.iterator(chunk_size=500):
        plan = getattr(materia, 'plan_actual', [])
        if not plan:
            profesores = 'Fuera del plan' if ciclo and materia.grado_id else ''
        else:
            profesores = '; '.join(str(mg.profesor) if mg.profesor_id else 'Sin profesor' for mg in plan)
        escritor.writerow([proteger_celda_csv(valor) for valor in [
            materia.clave, materia.nombre, str(materia.grado) if materia.grado_id else 'Sin grado',
            materia.grado.equivalencia_texto if materia.grado_id else '', 'Activa' if materia.activa else 'Baja', profesores,
        ]])
    return respuesta


# ---------------------------------------------------------------------------
# Copiar el plan de un ciclo a otro (materias y, si se quiere, horarios)
# ---------------------------------------------------------------------------
def _plan_de_copia(origen, destino):
    """Qué se copiaría, grado por grado: las asignaciones vigentes del origen que el destino todavía no tiene."""
    existentes = set(MateriaGrado.objects.filter(ciclo=destino).values_list('materia_id', 'grado_id'))
    fuente = (
        MateriaGrado.objects.filter(ciclo=origen, activa=True, materia__activa=True, grado__activo=True)
        .filter(Q(materia__grado__isnull=True) | Q(materia__grado=F('grado')))   # una materia, solo en su grado
        .select_related('materia', 'grado', 'profesor').prefetch_related('horarios', 'profesor__niveles')
        .order_by(orden_de_nivel('grado__nivel'), 'grado__numero', 'materia__nombre')
    )
    filas = {}
    for asignacion in fuente:
        fila = filas.setdefault(asignacion.grado_id, {'grado': asignacion.grado, 'por_copiar': [], 'ya_existen': 0})
        if (asignacion.materia_id, asignacion.grado_id) in existentes:
            fila['ya_existen'] += 1
        else:
            fila['por_copiar'].append(asignacion)
    plan = list(filas.values())
    for fila in plan:
        fila['materias'] = len(fila['por_copiar'])
        fila['bloques'] = sum(len(a.horarios.all()) for a in fila['por_copiar'])
        fila['con_profesor'] = sum(1 for a in fila['por_copiar'] if _profesor_vigente(a))
    return plan


def _profesor_vigente(asignacion):
    """El profesor de la asignación de origen, si todavía está activo y da clases en el nivel del grado (a quien está de
    baja o ya no da clases en ese nivel no se le copian materias)."""
    profesor = asignacion.profesor
    if profesor and profesor.estatus == 'ACTIVO' and asignacion.grado.nivel in profesor.niveles_lista:
        return profesor
    return None


def _profesores_que_se_conservan(por_copiar, destino, con_horarios):
    """Quién seguiría dando cada materia copiada: ({pk de la asignación de origen: profesor}, cuántas quedan sin él).

    Se queda sin profesor la materia cuyo profesor ya está de baja o, al copiar horarios, la que lo empalmaría con otra
    clase suya (ya registrada en el ciclo de destino o copiada antes): un profesor no puede estar en dos grupos a la vez.
    """
    candidatos = [a for a in por_copiar if a.profesor_id]
    ocupados = defaultdict(list)  # id de profesor -> [(día, inicio, fin)]
    if con_horarios and candidatos:
        registrados = HorarioMateria.objects.filter(
            materia_grado__ciclo=destino, materia_grado__activa=True, materia_grado__profesor__in={a.profesor_id for a in candidatos},
        ).values_list('materia_grado__profesor_id', 'dia_semana', 'hora_inicio', 'hora_fin')
        for profesor_id, dia, inicio, fin in registrados:
            ocupados[profesor_id].append((dia, inicio, fin))

    conservados, perdidos = {}, 0
    for asignacion in candidatos:
        profesor = _profesor_vigente(asignacion)
        bloques = [(h.dia_semana, h.hora_inicio, h.hora_fin) for h in asignacion.horarios.all()] if con_horarios else []
        agenda = ocupados[asignacion.profesor_id]
        if profesor is None or any(se_empalman(nuevo, previo) for nuevo in bloques for previo in agenda):
            perdidos += 1
            continue
        conservados[asignacion.pk] = profesor
        agenda.extend(bloques)
    return conservados, perdidos


def _sugerir_ciclos(ciclos):
    """Origen y destino propuestos: del ciclo más reciente con plan al próximo (o al actual)."""
    proximos = sorted((c for c in ciclos if c.estado == 'PROXIMO'), key=lambda c: c.fecha_inicio)
    destino = proximos[0] if proximos else next((c for c in ciclos if c.activo), None)
    if destino is None:
        return None, None
    origen = next(
        (c for c in ciclos if c.pk != destino.pk and MateriaGrado.objects.filter(ciclo=c, activa=True).exists()), None,
    )
    return (origen, destino) if origen else (None, None)


def _despues_de_copiar(request, destino):
    if request.user.has_perm('Alumnos.view_horariomateria'):
        return redirect(f"{reverse('horarios:lista')}?ciclo={destino.pk}")
    return redirect('materias:lista')


@requiere_permisos('Alumnos.add_materiagrado')
def copiar_plan(request):
    if request.method == 'POST':
        return _ejecutar_copia(request)

    ciclos = list(CicloEscolar.objects.all())
    datos = request.GET.copy()
    if not datos.get('origen') and not datos.get('destino'):
        origen, destino = _sugerir_ciclos(ciclos)
        if origen:
            datos['origen'], datos['destino'] = str(origen.pk), str(destino.pk)

    form = CopiarPlanForm(datos or None)
    plan = origen = destino = None
    if form.is_bound and form.is_valid():
        origen, destino = form.cleaned_data['origen'], form.cleaned_data['destino']
        plan = _plan_de_copia(origen, destino)

    return render(request, 'materias/copiar.html', {
        'form': form,
        'origen': origen,
        'destino': destino,
        'plan': plan,
        'total_materias': sum(fila['materias'] for fila in plan) if plan else 0,
        'total_bloques': sum(fila['bloques'] for fila in plan) if plan else 0,
        'total_existentes': sum(fila['ya_existen'] for fila in plan) if plan else 0,
        'total_con_profesor': sum(fila['con_profesor'] for fila in plan) if plan else 0,
        # Hace falta un ciclo de destino (actual o próximo) distinto al de origen: al menos dos ciclos
        'hay_destinos': form.fields['destino'].queryset.exists() and len(ciclos) > 1,
        'puede_copiar_horarios': request.user.has_perm('Alumnos.add_horariomateria'),
    })


def _ejecutar_copia(request):
    form = CopiarPlanForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Elige un ciclo de origen y otro de destino distintos.')
        return redirect('materias:copiar')

    origen, destino = form.cleaned_data['origen'], form.cleaned_data['destino']
    con_horarios = form.cleaned_data['horarios']
    if con_horarios and not request.user.has_perm('Alumnos.add_horariomateria'):
        messages.error(request, 'No tienes permiso para copiar horarios.')
        return redirect(f"{reverse('materias:copiar')}?origen={origen.pk}&destino={destino.pk}")

    plan = _plan_de_copia(origen, destino)
    por_copiar = [asignacion for fila in plan for asignacion in fila['por_copiar']]
    conservados, sin_profesor = _profesores_que_se_conservan(por_copiar, destino, con_horarios) if form.cleaned_data['conservar_profesor'] else ({}, 0)
    try:
        with transaction.atomic():
            MateriaGrado.objects.bulk_create([
                MateriaGrado(ciclo=destino, grado_id=a.grado_id, materia_id=a.materia_id, profesor=conservados.get(a.pk))
                for a in por_copiar
            ])
            bloques = []
            if con_horarios:
                ids = {(m.materia_id, m.grado_id): m.pk for m in MateriaGrado.objects.filter(ciclo=destino)}
                bloques = [
                    HorarioMateria(
                        materia_grado_id=ids[(a.materia_id, a.grado_id)],
                        dia_semana=h.dia_semana, hora_inicio=h.hora_inicio, hora_fin=h.hora_fin,
                    )
                    for a in por_copiar for h in a.horarios.all()
                ]
                HorarioMateria.objects.bulk_create(bloques)
    except IntegrityError:  # alguien asignó una de esas materias mientras tanto
        messages.error(request, 'Mientras revisabas, otra persona cambió el plan del ciclo de destino. No se guardó nada: vuelve a revisar.')
        return redirect(f"{reverse('materias:copiar')}?origen={origen.pk}&destino={destino.pk}")

    if por_copiar:
        extra = f' y {len(bloques)} bloque{"s" if len(bloques) != 1 else ""} de horario' if bloques else ''
        messages.success(
            request,
            f'Se copiaron {len(por_copiar)} materia{"s" if len(por_copiar) != 1 else ""} a los grados del ciclo {destino}{extra}.',
        )
        if sin_profesor:
            quedaron = f'{sin_profesor} materias quedaron' if sin_profesor != 1 else '1 materia quedó'
            messages.warning(
                request,
                f'{quedaron} sin profesor (porque está de baja, no da clases en ese nivel o se empalmaría con otra de sus clases). '
                f'Asígnalas desde el perfil del grado o del profesor.',
            )
    else:
        messages.info(request, 'No había nada nuevo que copiar: el ciclo de destino ya tiene esas materias.')
    return _despues_de_copiar(request, destino)
