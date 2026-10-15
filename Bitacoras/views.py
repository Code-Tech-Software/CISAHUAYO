"""Bitácoras por grupo (Gestión académica): el historial de cada grupo, la captura rápida de una entrada, su detalle con
el historial de cambios, la anulación y el historial de un estudiante. Quién ve y hace qué: Bitacoras/alcance.py."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Prefetch, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views.decorators.http import require_GET

from Alumnos.academico import ciclo_actual
from Alumnos.models import Alumno, CicloEscolar, HorarioMateria
from CISAHUAYO.paginacion import OPCIONES_POR_PAGINA, paginar
from CISAHUAYO.permisos import requiere_alguno

from . import reglas
from .alcance import CONSULTAR_TODAS, GESTIONAR, REGISTRAR, REGISTRAR_TODAS, TODOS, alcance_de_bitacoras
from .forms import AnularForm, EntradaForm, FiltroForm, texto_de_bloque
from .models import LEYENDA, SELLO, CambioBitacora, EntradaBitacora, EstudianteBitacora

ALTA = (REGISTRAR, REGISTRAR_TODAS)
CAMBIO = (REGISTRAR, REGISTRAR_TODAS, GESTIONAR)


def _con_relaciones(entradas):
    return entradas.select_related('autor', 'ciclo', 'periodo', 'grupo__grado', 'grupo__nombre').prefetch_related(
        Prefetch('vinculos', queryset=EstudianteBitacora.objects.select_related('alumno').order_by(
            'alumno__apellido_paterno', 'alumno__apellido_materno', 'alumno__nombre')),
    )


def _volver(request, defecto=None):
    """La página a la que se regresa (el listado con sus filtros o el historial de un estudiante), si es de aquí."""
    destino = request.POST.get('volver') or request.GET.get('volver') or ''
    if destino and destino.startswith('/bitacoras/') and url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
        return destino
    return defecto or reverse('bitacoras:lista')


def _entrada(request, pk, alcance):
    """La entrada, si está a su vista (las anuladas, solo para quien gestiona); si no, 404."""
    entrada = _con_relaciones(alcance.entradas(anuladas=True)).filter(pk=pk).first()
    if entrada is None:
        raise Http404('No existe esa entrada o no está a tu alcance.')
    return entrada


def _marcar_permisos(entradas, alcance):
    for entrada in entradas:
        entrada.modificable = alcance.puede_modificar(entrada)
    return entradas


# ---------------------------------------------------------------------------
# Historial del grupo
# ---------------------------------------------------------------------------
@requiere_alguno(*TODOS)
def lista(request):
    alcance = alcance_de_bitacoras(request.user)
    filtro = FiltroForm(request.GET or None, alcance=alcance)
    entradas, aviso = filtro.aplicar()
    totales = entradas.aggregate(
        total=Count('pk', distinct=True), generales=Count('pk', filter=Q(general=True), distinct=True),
        estudiantes=Count('vinculos__alumno', distinct=True),
    )
    pagina, rango, por_pagina = paginar(request, _con_relaciones(entradas).order_by('-fecha', '-hora_inicio', '-creado', '-pk'))
    _marcar_permisos(pagina, alcance)
    grupo = filtro.datos().get('grupo')
    nueva = reverse('bitacoras:crear')
    if grupo is not None:
        nueva += '?' + urlencode({'grupo': grupo.pk})
    return render(request, 'bitacoras/lista.html', {
        'filtro': filtro, 'pagina': pagina, 'rango': rango, 'por_pagina': por_pagina, 'opciones_por_pagina': OPCIONES_POR_PAGINA,
        'totales': totales, 'aviso': aviso, 'grupo': grupo, 'alcance': alcance, 'url_nueva': nueva,
        'puede_registrar': alcance.asignaciones().exists(), 'volver': request.get_full_path(), 'sello': SELLO,
        'mas_filtros': filtro.activos, 'alumnos_del_filtro': filtro.opciones_de_alumno(),
    })


# ---------------------------------------------------------------------------
# Captura
# ---------------------------------------------------------------------------
def _clase_actual(alcance):
    """El bloque del docente que está en curso (o el último que terminó hoy): la captura arranca con esa clase."""
    if alcance.profesor is None:
        return None
    ahora = timezone.localtime()
    bloques = list(HorarioMateria.objects.filter(
        materia_grado__in=alcance.asignaciones().filter(profesor=alcance.profesor), dia_semana=ahora.weekday(),
    ).select_related('materia_grado').order_by('hora_inicio'))
    hora = ahora.time()
    en_curso = next((b for b in bloques if b.hora_inicio <= hora < b.hora_fin), None)
    terminadas = [b for b in bloques if b.hora_fin <= hora]
    return en_curso or (terminadas[-1] if terminadas else None)


def _inicial(request, alcance):
    """Lo que llega en la dirección (desde el historial de un grupo o «Guardar y registrar otra») o la clase en curso."""
    inicial = {}
    asignaciones = {str(a.pk): a for a in alcance.asignaciones()}
    asignacion = asignaciones.get(request.GET.get('materia', ''))
    grupo = request.GET.get('grupo', '')
    if asignacion is not None:
        inicial.update(grupo=asignacion.grupo_id, asignacion=asignacion.pk)
    elif grupo and any(str(a.grupo_id) == grupo for a in asignaciones.values()):
        inicial['grupo'] = int(grupo)
        del_grupo = [a for a in asignaciones.values() if str(a.grupo_id) == grupo]
        if len(del_grupo) == 1:
            inicial['asignacion'] = del_grupo[0].pk
    else:
        clase = _clase_actual(alcance)
        if clase is not None:
            inicial.update(grupo=clase.materia_grado.grupo_id, asignacion=clase.materia_grado_id, bloque=clase.pk)
            inicial['clase_actual'] = clase
    if request.GET.get('fecha'):
        inicial['fecha'] = request.GET['fecha']
    if request.GET.get('bloque', '').isdigit():
        inicial['bloque'] = int(request.GET['bloque'])
    return inicial


@requiere_alguno(*ALTA)
def crear(request):
    alcance = alcance_de_bitacoras(request.user)
    volver = _volver(request)
    if request.method == 'POST':
        form = EntradaForm(request.POST, alcance=alcance)
        if form.is_valid():
            datos = form.cleaned_data
            entrada, nueva = reglas.crear(datos, request.user, datos.get('clave_envio'))
            if nueva:
                implicados = 'observación general del grupo' if entrada.general else f'{len(datos["alumnos"])} estudiante{"s" if len(datos["alumnos"]) != 1 else ""}'
                messages.success(request, f'Se guardó «{entrada.titulo}» en la bitácora de {entrada.grupo_texto} ({implicados}).')
            else:
                messages.info(request, f'«{entrada.titulo}» ya se había guardado: el formulario se envió dos veces y no se duplicó.')
            if request.POST.get('otra'):
                otra = {'materia': entrada.asignacion_id, 'fecha': entrada.fecha.isoformat(), 'volver': volver}
                if entrada.bloque_id:
                    otra['bloque'] = entrada.bloque_id
                return redirect(f"{reverse('bitacoras:crear')}?{urlencode(otra)}")
            return redirect(volver)
        messages.error(request, 'Revisa los campos marcados.')
    else:
        inicial = _inicial(request, alcance)
        clase_actual = inicial.pop('clase_actual', None)
        form = EntradaForm(initial=inicial, alcance=alcance)
        form.clase_actual = clase_actual
    return render(request, 'bitacoras/form.html', {
        'form': form, 'es_edicion': False, 'volver': volver, 'leyenda': LEYENDA, 'ciclo': form.ciclo,
        'sin_materias': not form.asignaciones, 'clase_actual': getattr(form, 'clase_actual', None),
        'url_opciones': reverse('bitacoras:opciones'),
    })


@requiere_alguno(*CAMBIO)
def editar(request, pk):
    alcance = alcance_de_bitacoras(request.user)
    entrada = _entrada(request, pk, alcance)
    motivo = alcance.motivo_para_no_modificar(entrada)
    if motivo:
        raise PermissionDenied(motivo)
    volver = _volver(request, reverse('bitacoras:detalle', args=[entrada.pk]))
    if request.method == 'POST':
        form = EntradaForm(request.POST, alcance=alcance, entrada=entrada)
        if form.is_valid():
            cambios = reglas.editar(entrada, form.cleaned_data, request.user)
            if cambios:
                messages.success(request, f'Se guardaron los cambios de «{form.cleaned_data["titulo"]}» ({len(cambios)} dato{"s" if len(cambios) != 1 else ""}). Quedan en su historial.')
            else:
                messages.info(request, 'No cambiaste nada.')
            return redirect(volver)
        messages.error(request, 'Revisa los campos marcados.')
    else:
        form = EntradaForm(alcance=alcance, entrada=entrada)
    return render(request, 'bitacoras/form.html', {
        'form': form, 'es_edicion': True, 'entrada': entrada, 'volver': volver, 'leyenda': LEYENDA, 'ciclo': entrada.ciclo,
        'url_opciones': reverse('bitacoras:opciones'),
    })


@requiere_alguno(*CAMBIO)
def anular(request, pk):
    alcance = alcance_de_bitacoras(request.user)
    entrada = _entrada(request, pk, alcance)
    if entrada.anulada:
        messages.info(request, 'Esa entrada ya estaba anulada.')
        return redirect('bitacoras:detalle', entrada.pk)
    motivo = alcance.motivo_para_no_modificar(entrada)
    if motivo:
        raise PermissionDenied(motivo)
    form = AnularForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        if form.is_valid():
            reglas.anular(entrada, form.cleaned_data['motivo'], request.user)
            messages.success(request, f'Se anuló «{entrada.titulo}». Se conserva en su historial y deja de aparecer en la bitácora y en los reportes.')
            return redirect(_volver(request))
        messages.error(request, 'Escribe el motivo de la anulación.')
    return render(request, 'bitacoras/anular.html', {'entrada': entrada, 'form': form, 'volver': _volver(request, reverse('bitacoras:detalle', args=[entrada.pk]))})


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------
@requiere_alguno(*TODOS)
def detalle(request, pk):
    alcance = alcance_de_bitacoras(request.user)
    entrada = _entrada(request, pk, alcance)
    entrada.modificable = alcance.puede_modificar(entrada)
    return render(request, 'bitacoras/detalle.html', {
        'entrada': entrada, 'cambios': entrada.cambios.select_related('usuario'), 'sello': SELLO,
        'motivo_sin_cambios': alcance.motivo_para_no_modificar(entrada), 'volver': _volver(request),
    })


@requiere_alguno(*TODOS)
def estudiante(request, pk):
    """Las entradas en las que el estudiante aparece explícitamente (nunca las observaciones generales), de todos los
    ciclos, con el grupo y la materia de entonces."""
    alcance = alcance_de_bitacoras(request.user)
    alumno = get_object_or_404(Alumno, pk=pk)
    if not alcance.ve_estudiante(alumno):
        raise Http404('Ese estudiante no está a tu alcance.')
    # Por subconsulta (no con un join): así `implicados` cuenta a todos los de cada entrada, no solo a este estudiante
    entradas = alcance.entradas().filter(pk__in=EstudianteBitacora.objects.filter(alumno=alumno).values('entrada'))
    ciclos = CicloEscolar.objects.filter(pk__in=entradas.values('ciclo')).order_by('-fecha_inicio')
    ciclo = next((c for c in ciclos if str(c.pk) == request.GET.get('ciclo', '')), None)
    if ciclo is not None:
        entradas = entradas.filter(ciclo=ciclo)
    entradas = _con_relaciones(entradas).annotate(implicados=Count('vinculos', distinct=True))
    pagina, rango, por_pagina = paginar(request, entradas.order_by('-fecha', '-hora_inicio', '-creado', '-pk'))
    _marcar_permisos(pagina, alcance)
    inscripcion = alumno.inscripciones.filter(activa=True, ciclo__activo=True).select_related('grupo__grado', 'grupo__nombre', 'ciclo').first()
    return render(request, 'bitacoras/estudiante.html', {
        'alumno': alumno, 'pagina': pagina, 'rango': rango, 'por_pagina': por_pagina, 'opciones_por_pagina': OPCIONES_POR_PAGINA,
        'ciclos': ciclos, 'ciclo': ciclo, 'inscripcion': inscripcion, 'sello': SELLO, 'volver': request.get_full_path(),
    })


@require_GET
@requiere_alguno(*ALTA)
def opciones(request):
    """Las materias (con sus bloques) y los estudiantes de un grupo en el que la persona puede registrar (JSON)."""
    alcance = alcance_de_bitacoras(request.user)
    asignaciones = [a for a in alcance.asignaciones() if str(a.grupo_id) == request.GET.get('grupo', '')]
    if not asignaciones:
        return JsonResponse({'materias': [], 'alumnos': []})
    bloques = {}
    for bloque in HorarioMateria.objects.filter(materia_grado__in=asignaciones).order_by('dia_semana', 'hora_inicio'):
        bloques.setdefault(bloque.materia_grado_id, []).append({'id': bloque.pk, 'dia': bloque.dia_semana, 'texto': texto_de_bloque(bloque)})
    grupo, ciclo = asignaciones[0].grupo, asignaciones[0].ciclo
    from Alumnos.templatetags.alumnos_extras import tono
    return JsonResponse({
        'materias': [{'id': a.pk, 'nombre': a.materia.nombre, 'bloques': bloques.get(a.pk, [])} for a in asignaciones],
        'alumnos': [{'id': i.alumno_id, 'nombre': str(i.alumno), 'referencia': i.alumno.referencia, 'iniciales': i.alumno.iniciales,
                     'tono': tono(i.alumno_id)} for i in reglas.inscripciones_del_grupo(grupo, ciclo)],
    })
