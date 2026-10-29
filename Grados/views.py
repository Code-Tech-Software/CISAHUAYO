import csv
from itertools import groupby

from django.contrib import messages
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from Alumnos.academico import (
    ciclo_actual,
    ciclo_editable,
    elegir_ciclo,
    extender_plan_al_grupo,
    inscritos_vigentes_por_grado,
    materias_por_asignar,
    motivo_para_no_dar_de_baja,
    siguiente_grado,
    suspender_plan,
)
from Alumnos.docentes import con_habilitados
from Alumnos.horarios import con_resumen_de_horario, formatear_duracion
from Alumnos.models import CicloEscolar, Grado, Grupo, HorarioMateria, Inscripcion, MateriaGrado, Profesor
from Alumnos.utils import proteger_celda_csv
from Alumnos.vinculos import prefetch_vinculos_activos
from CISAHUAYO.permisos import requiere_permisos
from CISAHUAYO.redireccion import destino_seguro
from Usuarios.seguridad import ACCION_CAMBIO, registrar

from .forms import GradoForm, NivelCompletoForm

# El filtro de visibilidad del listado (2026-10-28): Todos · Visibles · Ocultos
VISIBILIDADES = {'': None, 'visibles': True, 'ocultos': False}


def _conteos(modelo, ciclo, contar='pk', **filtros):
    """{id de grado: cantidad} de los registros del ciclo; vacío si no hay ciclo."""
    if ciclo is None:
        return {}
    filas = modelo.objects.filter(ciclo=ciclo, **filtros).order_by().values_list('grado_id').annotate(total=Count(contar, distinct=True))
    return dict(filas)


def _grupos_activos():
    return Prefetch(
        'grupos', queryset=Grupo.objects.filter(activo=True).select_related('nombre').order_by('nombre__orden', 'nombre__nombre'),
        to_attr='grupos_activos',
    )


def _pendientes_por_grado(ciclo):
    """{id de grado: [avisos]} de lo que le falta para el ciclo: materias sin profesor, materias sin horario y grupos
    sin estudiantes. Solo para el ciclo actual o uno próximo (de uno cerrado no hay nada que preparar)."""
    if not ciclo_editable(ciclo):
        return {}
    plan = MateriaGrado.objects.filter(ciclo=ciclo, activa=True, grupo__activo=True)
    sin_profesor = dict(plan.filter(profesor__isnull=True).order_by().values_list('grado_id').annotate(total=Count('pk')))
    sin_horario = dict(
        plan.exclude(pk__in=HorarioMateria.objects.values('materia_grado_id'))
        .order_by().values_list('grado_id').annotate(total=Count('pk'))
    )
    con_estudiantes = set(Inscripcion.objects.filter(ciclo=ciclo, activa=True).values_list('grupo_id', flat=True).distinct())
    sin_estudiantes = {}
    for grupo in Grupo.objects.filter(activo=True, grado__activo=True).select_related('nombre').order_by('nombre__orden', 'nombre__nombre'):
        if grupo.pk not in con_estudiantes:
            sin_estudiantes.setdefault(grupo.grado_id, []).append(str(grupo.nombre))

    avisos = {}
    for grado_id in {*sin_profesor, *sin_horario, *sin_estudiantes}:
        lista = []
        if sin_profesor.get(grado_id):
            n = sin_profesor[grado_id]
            lista.append(f'{n} materia{"s" if n != 1 else ""} sin profesor')
        if sin_horario.get(grado_id):
            n = sin_horario[grado_id]
            lista.append(f'{n} materia{"s" if n != 1 else ""} sin horario')
        if sin_estudiantes.get(grado_id):
            nombres = sin_estudiantes[grado_id]
            lista.append(f'{"Grupo" if len(nombres) == 1 else "Grupos"} {", ".join(nombres)} sin estudiantes')
        avisos[grado_id] = lista
    return avisos


# ---------------------------------------------------------------------------
# Listado: los grados por nivel, en orden escolar, en el ciclo elegido
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.view_grado')
def grado_lista(request):
    viendo_bajas = request.GET.get('estado') == 'BAJA'
    visibilidad = request.GET.get('visibilidad', '')
    if visibilidad not in VISIBILIDADES:
        visibilidad = ''
    ciclos = list(CicloEscolar.objects.all())
    pedido = request.GET.get('ciclo', '')
    # Sin elegir, el ciclo actual (mientras se prepara el próximo, se puede consultar ese)
    ciclo = elegir_ciclo(pedido, ciclos) if pedido else ciclo_actual()
    inscritos = _conteos(Inscripcion, ciclo, activa=True)
    materias = _conteos(MateriaGrado, ciclo, contar='materia', activa=True)   # el plan es del grado: una por materia
    pendientes = {} if viendo_bajas else _pendientes_por_grado(ciclo)
    vigentes = {} if viendo_bajas else inscritos_vigentes_por_grado()

    del_estado = Grado.objects.filter(activo=not viendo_bajas)
    grados = del_estado if VISIBILIDADES[visibilidad] is None else del_estado.filter(visible=VISIBILIDADES[visibilidad])
    grados = grados.academicos().prefetch_related(_grupos_activos())
    niveles = []
    for nivel, del_nivel in groupby(grados, key=lambda grado: grado.nivel):
        filas = [
            {
                'grado': grado, 'inscritos': inscritos.get(grado.pk, 0), 'materias': materias.get(grado.pk, 0),
                'pendientes': pendientes.get(grado.pk, []),
                # Con estudiantes en el ciclo actual o en uno próximo no se da de baja (el servidor también lo revisa)
                'bloqueo_baja': '' if viendo_bajas else motivo_para_no_dar_de_baja(grado, vigentes.get(grado.pk, 0)),
            }
            for grado in del_nivel
        ]
        niveles.append({
            'nombre': dict(Grado.NIVEL_CHOICES)[nivel],
            'filas': filas,
            'inscritos': sum(fila['inscritos'] for fila in filas),
        })

    conteos = dict(Grado.objects.order_by().values_list('activo').annotate(total=Count('pk')))
    por_visibilidad = dict(del_estado.order_by().values_list('visible').annotate(total=Count('pk')))
    return render(request, 'grados/lista.html', {
        'visibilidad': visibilidad,
        'visibilidades': [
            ('', 'Todos', sum(por_visibilidad.values())),
            ('visibles', 'Visibles', por_visibilidad.get(True, 0)),
            ('ocultos', 'Ocultos', por_visibilidad.get(False, 0)),
        ],
        'niveles': niveles,
        'ciclos': ciclos,
        'ciclo': ciclo,
        'preparando': ciclo_editable(ciclo),
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
            grupos = ', '.join(str(g.nombre) for g in form.grupos_agregados)
            messages.success(request, f'El grado {grado.nombre_de_nivel} fue registrado con {"los grupos" if len(form.grupos_agregados) > 1 else "el grupo"} {grupos}.')
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
            detalle = ''
            if form.grupos_agregados:
                varios = len(form.grupos_agregados) > 1
                detalle += f' {"Se agregaron los grupos" if varios else "Se agregó el grupo"} {", ".join(str(g.nombre) for g in form.grupos_agregados)} con su plan de materias.'
            if form.grupos_quitados:
                varios = len(form.grupos_quitados) > 1
                detalle += f' {"Se dieron de baja los grupos" if varios else "Se dio de baja el grupo"} {", ".join(str(g.nombre) for g in form.grupos_quitados)}'
                n = form.materias_suspendidas
                detalle += f' y {n} materia{"s" if n != 1 else ""} suya{"s" if n != 1 else ""} del ciclo actual o de los próximos.' if n else '.'
            messages.success(request, f'El grado {grado.nombre_de_nivel} se actualizó.{detalle}')
            return redirect('grados:lista')
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
        grado = Grado.objects.get(pk=pk)   # el título, con lo guardado (no con lo que se escribió)
    return _formulario(request, form, grado)


@requiere_permisos('Alumnos.add_grado')
def grado_nivel(request):
    """Alta de un nivel completo (configuración inicial): del 1.º al grado elegido, con su equivalencia habitual y sus
    grupos. Los grados que ya existen se dejan como están."""
    form = NivelCompletoForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        if form.is_valid():
            creados = form.save()
            nivel = dict(Grado.NIVEL_CHOICES)[form.cleaned_data['nivel']]
            texto = ', '.join(g.numero_ordinal for g in creados)
            omitidos = form.existentes
            aviso = f' Ya existían {", ".join(g.numero_ordinal for g in omitidos)} y se dejaron como estaban.' if omitidos else ''
            messages.success(request, f'Se registraron {len(creados)} grado{"s" if len(creados) != 1 else ""} de {nivel.lower()}: {texto}.{aviso}')
            return redirect('grados:lista')
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return render(request, 'grados/nivel.html', {'form': form})


# ---------------------------------------------------------------------------
# Perfil del grado: sus alumnos de un ciclo, grupo por grupo, y su plan de materias
# ---------------------------------------------------------------------------
def _ciclo_elegido(request, ciclos):
    return elegir_ciclo(request.GET.get('ciclo', ''), ciclos)


def _alumnos_del_grado(grado, ciclo, con_bajas=False, grupo=None):
    if ciclo is None:
        return Inscripcion.objects.none()
    inscripciones = Inscripcion.objects.filter(grado=grado, ciclo=ciclo)
    if not con_bajas:
        inscripciones = inscripciones.filter(activa=True)
    if grupo is not None:
        inscripciones = inscripciones.filter(grupo=grupo)
    return (
        inscripciones.select_related('alumno', 'grupo__nombre', 'grupo__grado')
        .order_by('-activa', 'grupo__nombre__orden', 'grupo__nombre__nombre', 'alumno__apellido_paterno', 'alumno__apellido_materno', 'alumno__nombre')
    )


def _matriz_del_plan(materias, grupos):
    """El plan con varios grupos: una fila por materia y una celda por grupo (su asignación, o None si ese grupo no la
    lleva en el ciclo)."""
    filas = {}
    for asignacion in materias:
        fila = filas.setdefault(asignacion.materia_id, {'materia': asignacion.materia, 'por_grupo': {}})
        fila['por_grupo'][asignacion.grupo_id] = asignacion
    resultado = []
    for fila in sorted(filas.values(), key=lambda fila: fila['materia'].nombre):
        asignaciones = list(fila['por_grupo'].values())
        resultado.append({
            'materia': fila['materia'],
            'celdas': [fila['por_grupo'].get(grupo.pk) for grupo in grupos],
            # Quitar y volver a asignar son del grado: se hacen desde una de sus asignaciones (una activa si la hay)
            'del_grado': next((a for a in asignaciones if a.activa), asignaciones[0]),
            'activa': any(a.activa for a in asignaciones),
        })
    return resultado


@requiere_permisos('Alumnos.view_grado')
def grado_detalle(request, pk):
    grado = get_object_or_404(Grado, pk=pk)
    ciclos = list(CicloEscolar.objects.all())
    ciclo = _ciclo_elegido(request, ciclos)
    con_bajas = request.GET.get('bajas') == '1'

    # El tutor principal de cada alumno se trae solo para los alumnos de este grado
    inscripciones = list(_alumnos_del_grado(grado, ciclo, con_bajas).prefetch_related(prefetch_vinculos_activos('alumno__')))
    activas = [inscripcion for inscripcion in inscripciones if inscripcion.activa]

    # Plan de materias del grado en el ciclo (con las quitadas, marcadas) y su resumen de horario
    materias = con_habilitados(con_resumen_de_horario(
        MateriaGrado.objects.filter(grado=grado, ciclo=ciclo).select_related('materia', 'profesor', 'grupo__nombre', 'grupo__grado')
        .prefetch_related('horarios').order_by('materia__nombre', 'grupo__nombre__orden', 'grupo__nombre__nombre')
        if ciclo else MateriaGrado.objects.none()
    ))
    materias_vigentes = [asignacion for asignacion in materias if asignacion.activa]
    grupos = list(grado.grupos.filter(activo=True).select_related('nombre', 'grado').order_by('nombre__orden', 'nombre__nombre'))
    # Las columnas de la tabla del plan: los grupos activos y los que tuvieron materias en el ciclo consultado
    con_plan = {asignacion.grupo_id for asignacion in materias} - {grupo.pk for grupo in grupos}
    columnas = sorted(
        [*grupos, *Grupo.objects.filter(pk__in=con_plan).select_related('nombre', 'grado')],
        key=lambda grupo: (grupo.nombre.orden, grupo.nombre.nombre),
    )
    # Horas por semana de un grupo (el primero): todos los grupos llevan el mismo plan
    minutos = sum(asignacion.minutos for asignacion in materias_vigentes if grupos and asignacion.grupo_id == grupos[0].pk)
    editable = ciclo_editable(ciclo)
    historial = (
        Inscripcion.objects.filter(grado=grado).order_by()
        .values('ciclo_id', 'ciclo__nombre', 'ciclo__fecha_inicio', 'ciclo__activo')
        .annotate(activas=Count('pk', filter=Q(activa=True)), bajas=Count('pk', filter=Q(activa=False, concluida=False)))
        .order_by('-ciclo__fecha_inicio')
    )
    siguiente = siguiente_grado(grado, list(Grado.objects.filter(activo=True).academicos()))
    bajas_del_ciclo = (
        Inscripcion.objects.filter(grado=grado, ciclo=ciclo, activa=False, concluida=False).count() if ciclo else 0
    )
    por_grupo = {}
    for inscripcion in activas:
        por_grupo[inscripcion.grupo_id] = por_grupo.get(inscripcion.grupo_id, 0) + 1

    return render(request, 'grados/detalle.html', {
        'grado': grado,
        'ciclos': ciclos,
        'ciclo': ciclo,
        'inscripciones': inscripciones,
        'total_inscritos': len(activas),
        'con_bajas': con_bajas,
        'bajas_del_ciclo': bajas_del_ciclo,
        # Cuántos estudiantes hay en cada grupo (para equilibrarlos al inscribir)
        'resumen_por_grupo': [{'grupo': grupo, 'inscritos': por_grupo.get(grupo.pk, 0)} for grupo in grupos],
        'materias': materias,
        'matriz': _matriz_del_plan(materias, columnas) if len(columnas) > 1 else None,
        'columnas': columnas,
        'total_materias': len({asignacion.materia_id for asignacion in materias_vigentes}),
        'grupos': grupos,
        'varios_grupos': len(grupos) > 1,
        'horas_semanales': formatear_duracion(minutos) if minutos else '',
        'plan_editable': editable and grado.activo,
        'puede_inscribir': grado.disponible,   # a un grado oculto o de baja no se inscribe
        'profesores_activos': list(Profesor.objects.filter(estatus='ACTIVO')) if editable and grado.activo else [],
        'sin_profesor': sum(1 for asignacion in materias_vigentes if not asignacion.profesor_id),
        'materias_por_asignar': list(materias_por_asignar(grado, ciclo)) if ciclo and editable and grado.activo else [],
        'historial': list(historial),
        'siguiente': siguiente,
        'bloqueo_baja': motivo_para_no_dar_de_baja(grado) if grado.activo else '',
        'esta_de_baja': not grado.activo,
    })


# ---------------------------------------------------------------------------
# Baja lógica y reactivación (vuelven a la página desde la que se hicieron)
# ---------------------------------------------------------------------------
@require_POST
@requiere_permisos('Alumnos.delete_grado')
def grado_baja(request, pk):
    """Baja lógica: el grado deja de ofrecerse al inscribir, pero conserva sus inscripciones y su historial. No se
    permite mientras tenga estudiantes inscritos en el ciclo actual o en uno próximo; sus materias de esos ciclos se
    suspenden (vuelven si se reactiva)."""
    grado = get_object_or_404(Grado, pk=pk)
    volver = destino_seguro(request, reverse('grados:lista'))   # el detalle y el listado mandan a dónde volver
    if not grado.activo:
        messages.info(request, f'El grado {grado.nombre_de_nivel} ya estaba dado de baja.')
        return redirect(volver)
    motivo = motivo_para_no_dar_de_baja(grado)
    if motivo:
        messages.error(request, f'No se puede dar de baja {grado.nombre_de_nivel}. {motivo}')
        return redirect(volver)

    grado.activo = False
    grado.save(update_fields=['activo'])
    suspender_plan(grado.grupos.all())
    messages.success(
        request,
        f'El grado {grado.nombre_de_nivel} fue dado de baja. Sus inscripciones se conservan y puedes reactivarlo desde el filtro «Bajas».',
    )
    return redirect(volver)


@require_POST
@requiere_permisos('Alumnos.change_grado')
def grado_reactivar(request, pk):
    grado = get_object_or_404(Grado, pk=pk)
    volver = destino_seguro(request, reverse('grados:lista'))
    if not grado.activo:
        # Mientras estuvo de baja, otro grado vigente pudo tomar su equivalencia
        otro = next(
            (g for g in Grado.objects.filter(activo=True).exclude(pk=grado.pk) if g.equivalencia_efectiva == grado.equivalencia_efectiva),
            None,
        ) if grado.equivalencia_efectiva else None
        if otro:
            messages.error(
                request,
                f'No se puede reactivar {grado.nombre_de_nivel}: su equivalencia ({grado.equivalencia_texto}) ya la tiene {otro.nombre_de_nivel}. '
                f'Cambia primero la equivalencia de {otro.nombre_de_nivel} y vuelve a intentarlo.',
            )
            return redirect(volver)
        grado.activo = True
        grado.save(update_fields=['activo'])
        for grupo in grado.grupos.filter(activo=True):
            extender_plan_al_grupo(grupo)   # vuelven sus materias suspendidas con la baja
        messages.success(request, f'El grado {grado.nombre_de_nivel} fue reactivado.')
    return redirect(volver)


# ---------------------------------------------------------------------------
# Visible en el sistema (2026-10-28): mostrar u ocultar sin dar de baja
# ---------------------------------------------------------------------------
@require_POST
@requiere_permisos('Alumnos.change_grado')
def grado_visibilidad(request, pk):
    """Muestra u oculta el grado (`visible`: '1' lo muestra; sin él, lo oculta: así funciona también el interruptor sin
    JavaScript). Oculto, no se ofrece en ninguna lista, selector ni filtro del sitio; sus grupos, inscripciones,
    calificaciones y demás registros quedan como estaban. Al mostrarlo vuelve a aparecer en todas partes."""
    grado = get_object_or_404(Grado, pk=pk)
    volver = destino_seguro(request, reverse('grados:lista'))
    visible = request.POST.get('visible') == '1'
    if grado.visible == visible:
        messages.info(request, f'El grado {grado.nombre_de_nivel} ya estaba {"visible" if visible else "oculto"}.')
        return redirect(volver)
    grado.visible = visible
    grado.save(update_fields=['visible'])
    registrar(request.user, grado, ACCION_CAMBIO, 'Lo mostró en el sistema.' if visible else 'Lo ocultó del sistema.')
    if visible:
        messages.success(request, f'El grado {grado.nombre_de_nivel} vuelve a estar visible: aparece otra vez en todas las listas, selectores y filtros.')
    else:
        messages.success(
            request,
            f'El grado {grado.nombre_de_nivel} quedó oculto: ya no se ofrece en ninguna lista, selector ni filtro. '
            'Sus grupos, inscripciones y registros se conservan; vuelve a mostrarlo desde el filtro «Ocultos».',
        )
    return redirect(volver)


# ---------------------------------------------------------------------------
# Exportación: lista de alumnos del grado (o de uno de sus grupos)
# ---------------------------------------------------------------------------
@require_GET
@requiere_permisos('Alumnos.view_grado')
def grado_exportar(request, pk):
    grado = get_object_or_404(Grado, pk=pk)
    ciclo = _ciclo_elegido(request, list(CicloEscolar.objects.all()))
    grupo = None
    if str(request.GET.get('grupo', '')).isdigit():
        grupo = Grupo.objects.filter(grado=grado, pk=request.GET['grupo']).select_related('nombre').first()
    inscripciones = _alumnos_del_grado(grado, ciclo, grupo=grupo).prefetch_related(prefetch_vinculos_activos('alumno__'))

    respuesta = HttpResponse(content_type='text/csv; charset=utf-8')
    nombre = f'{grado.get_nivel_display()}-{grado.numero}{f"-{grupo.nombre}" if grupo else ""}-{ciclo or "sin-ciclo"}'.lower().replace(' ', '-')
    respuesta['Content-Disposition'] = f'attachment; filename="grado-{nombre}-{timezone.localdate():%Y-%m-%d}.csv"'
    respuesta.write('﻿')  # para que Excel reconozca los acentos
    escritor = csv.writer(respuesta)
    escritor.writerow([
        'Referencia', 'Apellido paterno', 'Apellido materno', 'Nombre', 'Grupo', 'Fecha de nacimiento', 'Fecha de inscripción',
        'Tutor principal', 'Teléfono del tutor',
    ])
    for inscripcion in inscripciones.iterator(chunk_size=500):
        alumno = inscripcion.alumno
        vinculo = next(iter(alumno.vinculos_activos), None)
        escritor.writerow([proteger_celda_csv(valor) for valor in [
            alumno.referencia, alumno.apellido_paterno, alumno.apellido_materno, alumno.nombre,
            inscripcion.grupo.corto if inscripcion.grupo_id else '',
            f'{alumno.fecha_nacimiento:%d/%m/%Y}', f'{inscripcion.fecha_inscripcion:%d/%m/%Y}',
            str(vinculo.tutor) if vinculo else '', vinculo.tutor.telefono if vinculo else '',
        ]])
    return respuesta
