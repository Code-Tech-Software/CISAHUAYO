"""Sistema › Ajustes › Calificaciones: rubros, porcentajes y reglas de evaluación de cada materia en un ciclo (y sus
versiones por periodo), la configuración de referencia y la copia desde otra materia con vista previa."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.http import require_POST

from Alumnos.academico import elegir_ciclo
from Alumnos.models import CicloEscolar, Grado, Materia, MateriaGrado, Periodo, orden_de_nivel
from CISAHUAYO.permisos import requiere_permisos
from Conducta.permisos import puede_configurar

from . import reglas, semestres
from .forms import FiltroConfiguracionForm, NuevaVersionForm, ReglasForm, RubroFormSet, rubros_iniciales
from .models import ConfiguracionEvaluacion, Rubro

NIVELES = dict(Grado.NIVEL_CHOICES)


def _contexto_de_ajustes(request):
    return {'ajustes_seccion': 'calificaciones', 'puede_configurar_conducta': puede_configurar(request.user)}


def _ciclos():
    return list(CicloEscolar.objects.order_by('-fecha_inicio'))


def _materias_del_plan(ciclo):
    """Las materias del plan del ciclo (las que tienen al menos un grupo asignado), en orden escolar."""
    return (
        Materia.objects.filter(grados_materia__ciclo=ciclo, grados_materia__activa=True).select_related('grado')
        .annotate(grupos=Count('grados_materia', filter=Q(grados_materia__ciclo=ciclo, grados_materia__activa=True), distinct=True))
        .order_by(orden_de_nivel('grado__nivel'), 'grado__numero', 'nombre')
    )


def url_de_materia(materia, ciclo, configuracion=None):
    consulta = {'ciclo': ciclo.pk}
    if configuracion is not None and configuracion.periodo_id:
        consulta['version'] = configuracion.pk
    return f"{reverse('calificaciones:configuracion_materia', args=[materia.pk])}?{urlencode(consulta)}"


def _resumen(configuracion):
    if configuracion is None:
        return {'clave': 'sin', 'texto': 'Sin configurar'}
    suma = reglas.suma_de(configuracion.rubros.all())
    if configuracion.activa:
        return {'clave': 'activa', 'texto': 'Activa', 'suma': suma}
    return {'clave': 'borrador', 'texto': f'Borrador · suma {reglas.numero(suma)} %', 'suma': suma}


@requiere_permisos(reglas.VER_CONFIG)
def configuracion(request):
    ciclos = _ciclos()
    ciclo = elegir_ciclo(request.GET.get('ciclo'), ciclos)
    filtro = FiltroConfiguracionForm(request.GET)
    activos = filtro.activos
    filas = []
    if ciclo is not None:
        materias = _materias_del_plan(ciclo)
        if activos.get('nivel'):
            materias = materias.filter(grado__nivel=activos['nivel'])
        for palabra in activos.get('q', '').split():
            materias = materias.filter(Q(nombre__icontains=palabra) | Q(clave__icontains=palabra))
        materias = list(materias)
        configuraciones = (ConfiguracionEvaluacion.objects.filter(ciclo=ciclo, materia__in=materias)
                           .select_related('periodo').prefetch_related('rubros').order_by('periodo__fecha_inicio'))
        por_materia = {}
        for c in configuraciones:
            por_materia.setdefault(c.materia_id, []).append(c)
        grupos = {}
        for asignacion in (MateriaGrado.objects.filter(ciclo=ciclo, activa=True, materia__in=materias)
                           .select_related('grupo__nombre', 'grupo__grado').order_by('grupo__grado__numero', 'grupo__nombre__orden')):
            grupos.setdefault(asignacion.materia_id, []).append(str(asignacion.grupo))
        for materia in materias:
            propias = por_materia.get(materia.pk, [])
            base = next((c for c in propias if not c.periodo_id), None)
            filas.append({'materia': materia, 'grupos': grupos.get(materia.pk, []), 'nivel': NIVELES.get(materia.grado.nivel, '') if materia.grado_id else '',
                          'base': _resumen(base), 'versiones': [c for c in propias if c.periodo_id],
                          'url': url_de_materia(materia, ciclo)})
    return render(request, 'calificaciones/configuracion/lista.html', {
        **_contexto_de_ajustes(request), 'ciclos': ciclos, 'ciclo': ciclo, 'filtro': filtro, 'filtros_activos': activos, 'filas': filas,
        'sin_configurar': sum(1 for f in filas if f['base']['clave'] == 'sin'),
    })


def _materia_del_plan(materia_pk, ciclo):
    materia = get_object_or_404(Materia.objects.select_related('grado'), pk=materia_pk)
    if ciclo is None or not MateriaGrado.objects.filter(materia=materia, ciclo=ciclo).exists():
        raise Http404('Esa materia no está en el plan de ese ciclo.')
    return materia


def _periodos_de(materia, ciclo):
    nivel = reglas.nivel_de_materia(materia, ciclo)
    return Periodo.objects.filter(ciclo=ciclo, nivel=nivel).order_by('fecha_inicio', 'nombre') if nivel else Periodo.objects.none()


def _rubros_de_formset(formset):
    rubros = []
    for numero, form in enumerate(formset.forms):
        d = form.cleaned_data
        if not d:
            continue
        rubros.append({'pk': d.get('pk'), 'nombre': d['nombre'], 'porcentaje': d['porcentaje'], 'tipo': d['tipo'],
                       'activo': d.get('activo', False), 'orden': d.get('orden') if d.get('orden') is not None else numero,
                       'eliminar': d.get('eliminar', False)})
    return rubros


@requiere_permisos(reglas.VER_CONFIG)
def configuracion_materia(request, pk):
    ciclos = _ciclos()
    ciclo = elegir_ciclo(request.GET.get('ciclo') or request.POST.get('ciclo'), ciclos)
    materia = _materia_del_plan(pk, ciclo)
    configuraciones = list(ConfiguracionEvaluacion.objects.filter(materia=materia, ciclo=ciclo).select_related('periodo', 'modificado_por')
                           .prefetch_related('rubros').order_by('periodo__fecha_inicio'))
    base = next((c for c in configuraciones if not c.periodo_id), None)
    versiones = [c for c in configuraciones if c.periodo_id]
    elegida = next((c for c in versiones if str(c.pk) == request.GET.get('version', request.POST.get('version', ''))), None) or base
    periodos = _periodos_de(materia, ciclo)
    con_version = {c.periodo_id for c in versiones}
    disponibles = periodos.exclude(pk__in=con_version)
    # Una materia de un semestre de bachillerato cerrado se consulta, pero su configuración ya no se cambia
    bloqueo_semestre = semestres.bloqueo_de_configuracion(materia, ciclo)
    puede_editar = request.user.has_perm(reglas.CAMBIAR_CONFIG) and not bloqueo_semestre

    reglas_form = formset = None
    if elegida is not None and puede_editar:
        enviado = request.method == 'POST'
        reglas_form = ReglasForm(request.POST if enviado else None, instance=elegida, prefix='reglas')
        formset = RubroFormSet(request.POST if enviado else None, initial=None if enviado else rubros_iniciales(elegida), prefix='rubros')
        if enviado:
            if reglas_form.is_valid() and formset.is_valid():
                datos = {campo: reglas_form.cleaned_data[campo] for campo in ReglasForm.Meta.fields}
                activar = request.POST.get('accion') == 'activar'
                try:
                    problemas = reglas.guardar_configuracion(elegida, datos, _rubros_de_formset(formset), activar, request.user)
                except reglas.CapturaRechazada as error:
                    messages.error(request, f'No se guardó: {error.mensaje}')
                else:
                    if problemas:
                        messages.warning(request, 'Se guardó como borrador, pero no se activó: ' + ' '.join(problemas))
                    elif activar:
                        messages.success(request, 'Se guardó y quedó activa: los rubros suman 100 %.')
                    else:
                        messages.success(request, 'Se guardó como borrador (no sirve para cerrar calificaciones hasta activarla).')
                    return redirect(url_de_materia(materia, ciclo, elegida))
            else:
                messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    elif request.method == 'POST':
        raise PermissionDenied

    uso = None
    if elegida is not None:
        actas = reglas.actas_que_usan(elegida)
        uso = {'con_capturas': reglas.tiene_capturas(actas), 'cerradas': actas.filter(estado='CERRADA').count(),
               'en_captura': actas.filter(estado='EN_CAPTURA').count()}
        en_uso = {str(r.pk) for r in elegida.rubros.all() if reglas.rubro_en_uso(r)}
    else:
        en_uso = set()
    return render(request, 'calificaciones/configuracion/materia.html', {
        **_contexto_de_ajustes(request), 'ciclos': ciclos, 'ciclo': ciclo, 'materia': materia,
        'nivel': NIVELES.get(reglas.nivel_de_materia(materia, ciclo), ''),
        'base': base, 'versiones': versiones, 'elegida': elegida, 'reglas_form': reglas_form, 'formset': formset,
        'puede_editar': puede_editar, 'puede_crear': request.user.has_perm(reglas.CREAR_CONFIG) and not bloqueo_semestre, 'uso': uso, 'en_uso': en_uso,
        'bloqueo_semestre': bloqueo_semestre,
        'resumen': _resumen(elegida), 'problemas': reglas.problemas_para_activar(elegida) if elegida else [],
        'descripcion_reglas': reglas.describir_reglas(elegida) if elegida else [],
        'version_form': NuevaVersionForm(periodos=disponibles) if base is not None else None, 'periodos': periodos,
        'cambios': elegida.cambios.select_related('usuario')[:15] if elegida else [],
        'inicial': reglas.INICIAL, 'tipos': Rubro.TIPOS,
        'url_copiar': f"{reverse('calificaciones:configuracion_copiar')}?{urlencode({'destino': materia.pk, 'ciclo': ciclo.pk, **({'alcance': elegida.periodo_id} if elegida and elegida.periodo_id else {})})}",
    })


@require_POST
@requiere_permisos(reglas.CREAR_CONFIG)
def configuracion_crear(request, pk):
    ciclo = elegir_ciclo(request.POST.get('ciclo'), _ciclos())
    materia = _materia_del_plan(pk, ciclo)
    try:
        configuracion = reglas.crear_inicial(materia, ciclo, request.user)
    except reglas.CapturaRechazada as error:
        messages.error(request, error.mensaje)
        return redirect(url_de_materia(materia, ciclo))
    messages.success(request, 'Se creó con la configuración de referencia: conducta 20 % (directa), procedimientos 50 % y exámenes 30 %. '
                              'Ajústala si la materia evalúa distinto.')
    return redirect(url_de_materia(materia, ciclo, configuracion))


@require_POST
@requiere_permisos(reglas.CREAR_CONFIG)
def configuracion_version(request, pk):
    base = get_object_or_404(ConfiguracionEvaluacion.objects.select_related('materia__grado', 'ciclo'), pk=pk, periodo__isnull=True)
    form = NuevaVersionForm(request.POST, periodos=_periodos_de(base.materia, base.ciclo))
    if not form.is_valid():
        messages.error(request, 'Elige un periodo de la lista.')
        return redirect(url_de_materia(base.materia, base.ciclo))
    try:
        version = reglas.nueva_version(base, form.cleaned_data['periodo'], request.user)
    except reglas.CapturaRechazada as error:
        messages.error(request, error.mensaje)
        return redirect(url_de_materia(base.materia, base.ciclo))
    messages.success(request, f'Se creó la versión de {version.periodo.nombre}, igual a la del ciclo para empezar. Ajústala aquí.')
    return redirect(url_de_materia(base.materia, base.ciclo, version))


# ---------------------------------------------------------------------------
# Copiar la configuración de otra materia
# ---------------------------------------------------------------------------
def _origenes():
    """Las configuraciones que se pueden copiar (de otras materias o de otros ciclos/periodos), en orden."""
    return list(
        ConfiguracionEvaluacion.objects.select_related('materia__grado', 'ciclo', 'periodo').prefetch_related('rubros')
        .order_by('-ciclo__fecha_inicio', orden_de_nivel('materia__grado__nivel'), 'materia__grado__numero', 'materia__nombre', 'periodo__fecha_inicio')
    )


@requiere_permisos(reglas.CREAR_CONFIG, reglas.CAMBIAR_CONFIG)
def configuracion_copiar(request):
    datos = request.POST if request.method == 'POST' else request.GET
    ciclos = _ciclos()
    ciclo = elegir_ciclo(datos.get('ciclo'), ciclos)
    materia = _materia_del_plan(datos.get('destino') if str(datos.get('destino', '')).isdigit() else 0, ciclo)
    periodos = list(_periodos_de(materia, ciclo))
    alcance = next((p for p in periodos if str(p.pk) == str(datos.get('alcance', ''))), None)
    origenes = [o for o in _origenes() if not (o.materia_id == materia.pk and o.ciclo_id == ciclo.pk and o.periodo_id == (alcance.pk if alcance else None))]
    origen = next((o for o in origenes if str(o.pk) == str(datos.get('origen', ''))), None)
    incluir_reglas = datos.get('reglas') == '1'
    revision = reglas.revisar_copia(origen, materia, ciclo, alcance) if origen else None
    alcances = [{'periodo': None, 'nombre': 'Todo el ciclo', 'bloqueo': ''}]
    for periodo in periodos:
        existente = ConfiguracionEvaluacion.objects.filter(materia=materia, ciclo=ciclo, periodo=periodo).first()
        con_capturas = reglas.en_uso(existente) if existente else reglas.periodo_tiene_capturas(materia, ciclo, periodo)
        alcances.append({'periodo': periodo, 'nombre': f'Solo {periodo.nombre}', 'bloqueo': 'ya tiene capturas' if con_capturas else ''})

    if request.method == 'POST':
        if origen is None or request.POST.get('confirmar') != '1':
            messages.error(request, 'Elige la configuración de origen y revisa la vista previa antes de aplicar.')
        else:
            try:
                destino = reglas.copiar(origen, materia, ciclo, alcance, incluir_reglas, request.user)
            except reglas.CapturaRechazada as error:
                messages.error(request, f'No se copió: {error.mensaje}')
            else:
                messages.success(request, f'Se copió la configuración de {origen.materia} ({origen.ciclo}, {origen.alcance}). '
                                          'Es una copia independiente: cambiar la de origen no la afecta.')
                return redirect(url_de_materia(materia, ciclo, destino))

    return render(request, 'calificaciones/configuracion/copiar.html', {
        **_contexto_de_ajustes(request), 'ciclo': ciclo, 'materia': materia, 'alcance': alcance, 'alcances': alcances,
        'origenes': origenes, 'origen': origen, 'incluir_reglas': incluir_reglas, 'revision': revision,
        'foto': reglas.foto_de_configuracion(origen) if origen else None,
        'reglas_origen': reglas.describir_reglas(origen) if origen else [],
        'suma_origen': reglas.suma_de(origen.rubros.all()) if origen else None,
        'reglas_destino': reglas.describir_reglas(revision['existente']) if revision and revision['existente'] else [],
        'tipos': dict(Rubro.TIPOS), 'volver': url_de_materia(materia, ciclo, revision['existente'] if revision else None),
    })
