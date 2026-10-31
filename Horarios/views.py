from collections import defaultdict
from datetime import timedelta
from itertools import groupby
from urllib.parse import urlencode

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from Alumnos.academico import ciclo_editable, elegir_ciclo
from Alumnos.horarios import (
    DIAS,
    DIAS_CORTOS,
    DIAS_HABILES,
    bloques_del_profesor_empalmados,
    con_resumen_de_horario,
    cuadricula,
    formatear_duracion,
    minutos_por_profesor,
    minutos_semanales,
    recreos_del_grupo,
    resumen_horario,
)
from Alumnos.clases import bloques_del_grupo, en_el_horario, sustituidas_por
from Alumnos.models import CicloEscolar, DiaNoLectivo, Grado, Grupo, HorarioMateria, MateriaGrado, Profesor, Recreo
from Alumnos.semanas import A, B, Calendario, bloques_de_semana, fecha_de
from CISAHUAYO.permisos import requiere_permisos

from . import cambios
from .alcance import asignaciones_del_docente, ciclos_del_docente, no_docentes, solo_sus_clases
from .forms import HorarioCrearForm, HorarioEditarForm, RecreoCrearForm, RecreoEditarForm, mensaje_de_empalme_profesor


def _url_del_grupo(grupo_id, ciclo_id, vista=''):
    url = f"{reverse('horarios:grupo', args=[grupo_id])}?ciclo={ciclo_id}"
    return f'{url}&vista={vista}' if vista else url


def fecha_en_ciclo(fecha, ciclo):
    """La fecha pedida (o hoy) llevada a las fechas del ciclo."""
    fecha = fecha or timezone.localdate()
    if ciclo is None:
        return fecha
    return min(max(fecha, ciclo.fecha_inicio), ciclo.fecha_fin)


def semana_pedida(request, calendario, nivel):
    """La semana A o B que se captura (la de ?semana=, o A); '' si el nivel tiene horario fijo."""
    if not calendario.alternado(nivel):
        return ''
    valor = (request.POST.get('semana') or request.GET.get('semana') or '').upper()
    return valor if valor in (A, B) else A


def _ciclo_de(request):
    """Ciclo que se consulta: ?ciclo=, si no el actual y, si no hay, el más reciente."""
    ciclos = list(CicloEscolar.objects.all())
    return ciclos, elegir_ciclo(request.GET.get('ciclo', ''), ciclos)


def _a_mi_horario(request, campo, pk):
    """El perfil Docente no consulta horarios de grupos ni de grados: va a sus clases de ahí (`campo`: grupo o grado) y, si
    no tiene ninguna, para él no existe."""
    ciclo = elegir_ciclo(request.GET.get('ciclo', ''), ciclos_del_docente(request.user))
    if not asignaciones_del_docente(request.user, ciclo).filter(**{campo: pk}).exists():
        raise Http404
    return redirect(f"{reverse('horarios:mio')}?{urlencode({'ciclo': ciclo.pk, campo: pk})}")


# ---------------------------------------------------------------------------
# Índice: los grupos con un resumen de su horario
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.view_horariomateria')
def horario_lista(request):
    if solo_sus_clases(request.user):
        destino = reverse('horarios:mio')
        return redirect(f'{destino}?{request.GET.urlencode()}' if request.GET else destino)
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
        por_grupo = defaultdict(list)
        for bloque in bloques.select_related('materia_grado').only('semana', 'hora_inicio', 'hora_fin', 'dia_semana', 'materia_grado__grupo_id'):
            por_grupo[bloque.materia_grado.grupo_id].append(bloque)
        for grupo_id, del_grupo in por_grupo.items():
            datos = estadisticas[grupo_id]
            datos['bloques'] = len(del_grupo)
            datos['minutos'] = minutos_semanales(del_grupo)   # con semanas A y B, la más cargada

    # El receso de cada grupo, resumido («Lun, Mar, Mié, Jue, Vie · 10:30–11:00»)
    recesos = {}
    if ciclo:
        for receso in Recreo.objects.filter(ciclo=ciclo).order_by('dia_semana', 'hora_inicio'):
            recesos.setdefault(receso.grupo_id, []).append(receso)

    grupos = (
        Grupo.objects.filter(Q(activo=True, grado__activo=True) | Q(pk__in=estadisticas))
        .select_related('grado', 'nombre').academicos()
    )
    if not (ciclo and ciclo.estado == 'CERRADO'):
        grupos = grupos.filter(grado__visible=True)   # los de grados ocultos, solo en el historial (2026-10-28)
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

    # Los niveles con semanas A y B, con la semana en que va cada uno
    calendario = Calendario(ciclo)
    alternados = [
        {'nombre': nombre, 'semana': calendario.info(fecha_en_ciclo(None, ciclo), nivel)}
        for nivel, nombre in Grado.NIVEL_CHOICES if calendario.alternado(nivel)
    ]
    return render(request, 'horarios/lista.html', {
        'ciclos': ciclos,
        'ciclo': ciclo,
        'alternados': alternados,
        'niveles': niveles,
        'profesores': profesores,
        'editable': ciclo_editable(ciclo),
    })


# ---------------------------------------------------------------------------
# Horario semanal de un grupo
# ---------------------------------------------------------------------------
def comparar_semanas(asignaciones):
    """Lo que cambia entre la semana A y la B de cada materia: sesiones y minutos. Las materias son las mismas (son las
    del grupo); la diferencia que importa es que una no tenga clases en alguna de las dos, o tenga distinta carga."""
    filas, diferencias = [], 0
    for asignacion in asignaciones:
        bloques = list(asignacion.horarios.all())
        semana = {s: [b for b in bloques if b.semana in ('', s)] for s in (A, B)}
        fila = {
            'asignacion': asignacion,
            'sesiones_a': len(semana[A]), 'sesiones_b': len(semana[B]),
            'minutos_a': minutos_semanales(semana[A]), 'minutos_b': minutos_semanales(semana[B]),
        }
        fila['duracion_a'] = formatear_duracion(fila['minutos_a']) if fila['minutos_a'] else '—'
        fila['duracion_b'] = formatear_duracion(fila['minutos_b']) if fila['minutos_b'] else '—'
        fila['falta'] = 'A' if not semana[A] and semana[B] else ('B' if semana[A] and not semana[B] else '')
        fila['distinta'] = fila['sesiones_a'] != fila['sesiones_b'] or fila['minutos_a'] != fila['minutos_b']
        diferencias += fila['distinta']
        filas.append(fila)
    return {'filas': filas, 'diferencias': diferencias, 'faltan': [f for f in filas if f['falta']]}


def _dias_sin_clases(semana, nivel):
    """Los días sin clases (festivos, suspensiones, vacaciones) de esa semana para el nivel: {fecha: motivo}. No mueven
    la alternancia: la semana sigue siendo la que le toca."""
    dias = DiaNoLectivo.objects.filter(fecha__range=(semana.lunes, semana.domingo), nivel=nivel).order_by('fecha')
    return dict(dias.values_list('fecha', 'motivo'))


@requiere_permisos('Alumnos.view_horariomateria')
def horario_grupo(request, grupo_pk):
    """El horario de un grupo. Con horario fijo, su horario semanal. Con semanas A y B: las dos plantillas (pestañas
    «Semana A» y «Semana B», donde se captura) y, aparte, el horario de una semana concreta del calendario («Por
    fecha»), con las versiones que estaban en vigor y los días sin clases. Abre en la plantilla de la semana de hoy."""
    if solo_sus_clases(request.user):
        return _a_mi_horario(request, 'grupo', grupo_pk)
    grupo = get_object_or_404(Grupo.objects.select_related('grado', 'nombre'), pk=grupo_pk)
    ciclos, ciclo = _ciclo_de(request)
    calendario = Calendario(ciclo)
    nivel = grupo.grado.nivel
    alternado = calendario.alternado(nivel)
    # Bloques simultáneos: aquí no hay una materia, sino estudiantes que se distribuyen entre varias clases
    simultaneos = bloques_del_grupo(grupo, ciclo)
    sustituidas = sustituidas_por(simultaneos)
    fecha = fecha_en_ciclo(fecha_de(request.GET.get('fecha')), ciclo)
    semana = calendario.info(fecha, nivel)
    hoy = calendario.info(fecha_en_ciclo(None, ciclo), nivel)

    vista = request.GET.get('vista', '')
    if vista != 'fecha':
        vista = (vista.upper() if vista.upper() in (A, B) else (hoy.tipo or A)) if alternado else ''

    asignaciones = []
    if ciclo:
        asignaciones = con_resumen_de_horario(
            MateriaGrado.objects.filter(grupo=grupo, ciclo=ciclo, activa=True)
            .select_related('materia', 'profesor').prefetch_related('horarios').order_by('materia__nombre')
        )
    recesos = list(recreos_del_grupo(grupo, ciclo))
    # Cada bloque ya trae su asignación (y la materia) gracias al prefetch: sin consultas por celda
    todos = [bloque for asignacion in asignaciones for bloque in asignacion.horarios.all()]
    sin_clases = {}
    if vista == 'fecha':
        bloques = list(
            bloques_de_semana(fecha, ciclo, calendario, materia_grado__grupo=grupo)
            .select_related('materia_grado__materia', 'materia_grado__profesor')
        ) if ciclo else []
        sin_clases = _dias_sin_clases(semana, nivel) if ciclo else {}
    elif vista in (A, B):
        bloques = [bloque for bloque in todos if bloque.semana in ('', vista)]
    else:
        bloques = todos
    minutos = minutos_semanales(bloques)
    editable = ciclo_editable(ciclo)
    for bloque in bloques:
        bloque.sustituida_por = sustituidas.get(bloque.materia_grado_id, '')

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
        'etiqueta_horario': (
            f'Horario de {grupo}, {semana.nombre.lower()}, del {semana.rango}' if vista == 'fecha'
            else f'Horario de {grupo}, plantilla de la semana {vista}, ciclo {ciclo}' if vista
            else f'Horario semanal de {grupo} en el ciclo {ciclo}'
        ) if ciclo else '',
        'cuadricula': cuadricula(bloques + recesos + en_el_horario(simultaneos)),
        'simultaneos': simultaneos,
        'recesos': recesos,
        'resumen_recesos': resumen_horario(recesos),
        'total_bloques': len(bloques),
        'horas_semanales': formatear_duracion(minutos) if minutos else '',
        # En la consulta por fecha no se edita: puede mostrar versiones anteriores del horario
        'editable': editable,
        'editable_aqui': editable and vista != 'fecha',
        'alternado': alternado,
        'vista': vista,
        'semana': semana,
        'semana_de_hoy': hoy,
        'sin_clases': sin_clases,
        'comparacion': comparar_semanas(asignaciones) if alternado else None,
        'vigencia_inicial': cambios.vigencia_inicial(ciclo),
    })


@requiere_permisos('Alumnos.view_horariomateria')
def horario_grado(request, grado_pk):
    """El horario es de cada grupo: el enlace a un grado lleva al horario de su primer grupo."""
    if solo_sus_clases(request.user):
        return _a_mi_horario(request, 'grado', grado_pk)
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
@no_docentes
def horario_crear(request, grupo_pk):
    grupo = get_object_or_404(Grupo.objects.select_related('grado', 'nombre'), pk=grupo_pk)
    _, ciclo = _ciclo_de(request)
    if ciclo is None:
        messages.error(request, 'Crea un ciclo escolar para poder armar horarios.')
        return redirect('horarios:lista')
    if not ciclo_editable(ciclo):
        return _ciclo_cerrado(request, grupo.pk, ciclo)

    semana = semana_pedida(request, Calendario(ciclo), grupo.grado.nivel)
    if request.method == 'POST':
        form = HorarioCrearForm(request.POST, grupo=grupo, ciclo=ciclo, semana=semana)
        if form.is_valid():
            bloques = form.guardar()
            dias = ', '.join(f'{DIAS_CORTOS[b.dia_semana]} {b.hora_inicio:%H:%M}–{b.hora_fin:%H:%M}' for b in bloques)
            en_semana = f' en la semana {semana}' if semana else ''
            messages.success(request, f'Se agregó el horario de {form.cleaned_data["materia_grado"].materia}{en_semana}: {dias}.')
            return redirect(_url_del_grupo(grupo.pk, ciclo.pk, semana))
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    else:
        inicial = {'vigencia': cambios.vigencia_inicial(ciclo)}
        if request.GET.get('materia', '').isdigit():
            inicial['materia_grado'] = int(request.GET['materia'])
        if request.GET.get('dia', '').isdigit() and int(request.GET['dia']) in DIAS:
            inicial['dias'] = [int(request.GET['dia'])]
        form = HorarioCrearForm(grupo=grupo, ciclo=ciclo, semana=semana, initial=inicial)

    return render(request, 'horarios/form.html', {
        'form': form, 'grupo': grupo, 'ciclo': ciclo, 'es_edicion': False, 'semana': semana,
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
@no_docentes
def horario_editar(request, pk):
    bloque = _bloque_vigente(pk)
    grupo, ciclo = bloque.materia_grado.grupo, bloque.materia_grado.ciclo
    if not ciclo_editable(ciclo):
        return _ciclo_cerrado(request, grupo.pk, ciclo)

    alternado = Calendario(ciclo).alternado(grupo.grado.nivel)
    form = HorarioEditarForm(request.POST if request.method == 'POST' else None, instance=bloque, alternado=alternado,
                             initial={'vigencia': cambios.vigencia_inicial(ciclo)})
    if request.method == 'POST':
        if form.is_valid():
            bloque = form.save()
            desde = f' a partir del {bloque.vigente_desde:%d/%m/%Y}' if bloque.vigente_desde else ''
            messages.success(request, f'Se actualizó el horario de {bloque.materia_grado.materia} ({DIAS[bloque.dia_semana].lower()}){desde}.')
            return redirect(_url_del_grupo(grupo.pk, ciclo.pk, bloque.semana))
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')

    return render(request, 'horarios/form.html', {
        'form': form, 'grupo': grupo, 'ciclo': ciclo, 'es_edicion': True, 'bloque': bloque, 'sin_materias': False,
        'semana': bloque.semana,
    })


@require_POST
@requiere_permisos('Alumnos.delete_horariomateria')
@no_docentes
def horario_eliminar(request, pk):
    """Quita un bloque del horario. Sin fecha es una corrección y se borra; con «A partir de», o si una bitácora ya lo
    usó, se conserva cerrado para que el horario de las fechas anteriores no cambie (Horarios/cambios.py)."""
    bloque = _bloque_vigente(pk)
    grupo, ciclo = bloque.materia_grado.grupo, bloque.materia_grado.ciclo
    if not ciclo_editable(ciclo):
        return _ciclo_cerrado(request, grupo.pk, ciclo)

    materia, dia, semana = bloque.materia_grado.materia, DIAS[bloque.dia_semana].lower(), bloque.semana
    texto = f'{bloque.hora_inicio:%H:%M}–{bloque.hora_fin:%H:%M}'
    desde = fecha_de(request.POST.get('vigencia'))
    if desde and not ciclo.fecha_inicio <= desde <= ciclo.fecha_fin:
        messages.error(request, f'Elige una fecha dentro del ciclo {ciclo}.')
        return redirect(_url_del_grupo(grupo.pk, ciclo.pk, semana))
    borrado = cambios.retirar(bloque, desde)
    cuando = '' if borrado else f' a partir del {bloque.vigente_hasta + timedelta(days=1):%d/%m/%Y}; las fechas anteriores lo conservan'
    messages.success(request, f'Se quitó {materia} del horario ({dia} {texto}){cuando}.')
    return redirect(_url_del_grupo(grupo.pk, ciclo.pk, semana))


@require_POST
@requiere_permisos('Alumnos.add_horariomateria', 'Alumnos.delete_horariomateria')
@no_docentes
def copiar_semana(request, grupo_pk):
    """«Copiar semana A a semana B»: la semana B del grupo queda igual que la A (para luego ajustar lo que cambie).
    Los bloques que tenía la B se quitan desde la fecha indicada; si algún bloque copiado empalmaría a un profesor con
    otra clase suya, no se copia nada."""
    grupo = get_object_or_404(Grupo.objects.select_related('grado', 'nombre'), pk=grupo_pk)
    _, ciclo = _ciclo_de(request)
    if ciclo is None:
        return redirect('horarios:lista')
    if not ciclo_editable(ciclo):
        return _ciclo_cerrado(request, grupo.pk, ciclo)
    calendario = Calendario(ciclo)
    if not calendario.alternado(grupo.grado.nivel):
        messages.error(request, f'{grupo.grado.get_nivel_display()} tiene horario fijo en el ciclo {ciclo}: no hay semana A ni B.')
        return redirect(_url_del_grupo(grupo.pk, ciclo.pk))
    desde = fecha_de(request.POST.get('vigencia'))
    if desde and not ciclo.fecha_inicio <= desde <= ciclo.fecha_fin:
        messages.error(request, f'Elige una fecha dentro del ciclo {ciclo}.')
        return redirect(_url_del_grupo(grupo.pk, ciclo.pk, B))

    actuales = list(HorarioMateria.objects.filter(materia_grado__grupo=grupo, materia_grado__ciclo=ciclo, materia_grado__activa=True)
                    .select_related('materia_grado__profesor', 'materia_grado__materia'))
    de_a = [b for b in actuales if b.semana == A]
    if not de_a:
        messages.error(request, 'La semana A todavía no tiene horario: no hay nada que copiar.')
        return redirect(_url_del_grupo(grupo.pk, ciclo.pk, A))
    problemas = []
    for bloque in de_a:
        profesor = bloque.materia_grado.profesor
        if profesor is None:
            continue
        ajenos = bloques_del_profesor_empalmados(
            profesor, ciclo, bloque.dia_semana, bloque.hora_inicio, bloque.hora_fin, excluir_grupo=grupo,
            semana=B, nivel=grupo.grado.nivel, desde=desde,
        )
        if ajenos:
            problemas.append(mensaje_de_empalme_profesor(profesor, ajenos))
    if problemas:
        messages.error(request, 'No se copió la semana A: ' + ' '.join(dict.fromkeys(problemas)))
        return redirect(_url_del_grupo(grupo.pk, ciclo.pk, B))

    with transaction.atomic():
        for bloque in [b for b in actuales if b.semana == B]:
            cambios.retirar(bloque, desde)
        for bloque in de_a:
            cambios.crear(bloque.materia_grado, bloque.dia_semana, bloque.hora_inicio, bloque.hora_fin, semana=B, desde=desde)
    cuando = f' a partir del {desde:%d/%m/%Y}' if cambios.normalizar(desde, ciclo) else ''
    messages.success(request, f'La semana B de {grupo} quedó igual que la A{cuando} ({len(de_a)} bloque{"s" if len(de_a) != 1 else ""}). Ajusta lo que cambie.')
    return redirect(_url_del_grupo(grupo.pk, ciclo.pk, B))


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
@no_docentes
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
@no_docentes
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
@no_docentes
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
