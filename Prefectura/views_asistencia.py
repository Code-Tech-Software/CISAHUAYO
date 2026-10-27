"""Asistencia en prefectura: la matriz por materia (la misma de la administración y los docentes, de solo consulta),
la lista de faltas y retardos con sus filtros, los accesos al colegio (retardos de ingreso, entradas posteriores y
salidas anticipadas) y las justificaciones (con comprobante fotográfico, vista previa de lo que se justifica y
revocación con motivo). Todo dentro del alcance de la cuenta; lo de fuera responde 404.

Prefectura no cambia el pase de lista del docente: la matriz es de consulta y los accesos se guardan aparte.
"""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Max, Min, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from Alumnos.academico import ciclo_actual
from Alumnos.asistencia_docente import asignaciones_del_ciclo
from Alumnos.models import Justificacion
from Asistencias.views_docente import contexto_de_matriz, respuesta_de_reporte
from CISAHUAYO.paginacion import OPCIONES_POR_PAGINA, POR_PAGINA_DEFECTO, paginar
from CISAHUAYO.permisos import requiere_alguno, requiere_permisos
from CISAHUAYO.redireccion import destino_seguro
from Conducta import reglas

from . import asistencia
from .alcance import alcance_de
from .forms import FOTOS, TAMANO_MAXIMO, AccesoForm, FiltroAccesosForm, FiltroAsistenciaForm, JustificarForm, MotivoForm, fecha_de
from .models import MovimientoAcceso
from .views import VER, permisos_de

REGISTRAR, CORREGIR, CORREGIR_OTROS = 'Prefectura.registrar', 'Prefectura.corregir', 'Prefectura.corregir_otros'
JUSTIFICAR, EXPORTAR = 'Prefectura.justificar', 'Prefectura.exportar'


def _asignaciones(alcance):
    """Las materias (una por grupo) del ciclo actual de los grupos del alcance."""
    return asignaciones_del_ciclo().filter(grupo__in=alcance.grupos_visibles())


# ---------------------------------------------------------------------------
# La matriz por materia (solo consulta)
# ---------------------------------------------------------------------------
@requiere_permisos(VER)
def matriz(request):
    alcance = alcance_de(request.user)
    ciclo = ciclo_actual()
    asignaciones = list(_asignaciones(alcance)) if ciclo else []
    contexto = {'seccion': 'asistencia', 'ciclo': ciclo, 'asignaciones': asignaciones, 'alcance': alcance, 'puede': permisos_de(request.user)}
    elegida, grupo = request.GET.get('materia', ''), request.GET.get('grupo', '')
    if not asignaciones:
        if elegida:
            raise Http404('Esa materia no es de tu alcance o del ciclo actual.')
        return render(request, 'prefectura/asistencia.html', contexto)

    if elegida:
        asignacion = next((a for a in asignaciones if elegida.isdigit() and a.pk == int(elegida)), None)
        if asignacion is None:
            raise Http404('Esa materia no es de tu alcance o del ciclo actual.')
    else:
        asignacion = next((a for a in asignaciones if grupo.isdigit() and a.grupo_id == int(grupo)), asignaciones[0])

    contexto.update(contexto_de_matriz(request, asignacion, ver_justificaciones=True, url_lista=reverse('prefectura:justificaciones')))
    # Un estudiante: solo su fila
    alumno = request.GET.get('alumno', '')
    estudiantes = [fila['alumno'] for fila in contexto['datos']['filas']]
    if alumno.isdigit():
        contexto['datos']['filas'] = [fila for fila in contexto['datos']['filas'] if fila['alumno'].pk == int(alumno)]
    contexto.update({
        'grupos': list({a.grupo_id: a.grupo for a in asignaciones}.values()),
        'materias_del_grupo': [a for a in asignaciones if a.grupo_id == asignacion.grupo_id],
        'estudiantes': estudiantes,
        'alumno_elegido': int(alumno) if alumno.isdigit() else None,
        'ver_justificaciones': True,
        'url_reporte': reverse('prefectura:asistencia_reporte') if request.user.has_perm(EXPORTAR) else '',
        'url_guardar': '',
        'aviso_solo_consulta': 'Es de consulta: el pase de lista lo capturan los docentes. Para justificar una falta o un retardo usa «Justificar»; '
                               'para una llegada tarde o una salida anticipada, «Entradas y salidas».',
    })
    return render(request, 'prefectura/asistencia.html', contexto)


@requiere_permisos(VER, EXPORTAR)
def matriz_reporte(request):
    elegida = request.GET.get('materia', '')
    if not elegida.isdigit():
        raise Http404('Elige una materia.')
    asignacion = get_object_or_404(_asignaciones(alcance_de(request.user)), pk=int(elegida))
    return respuesta_de_reporte(request, asignacion, asignacion.profesor, reverse('prefectura:asistencia'))


# ---------------------------------------------------------------------------
# Faltas y retardos (cada registro o por estudiante)
# ---------------------------------------------------------------------------
@requiere_permisos(VER)
def registros(request):
    alcance = alcance_de(request.user)
    form = FiltroAsistenciaForm(request.GET or None, alcance=alcance)
    datos = form.datos()
    desde, hasta = form.rango()
    fuente = datos.get('fuente') or 'materias'
    vista = datos.get('vista') or 'registros'
    base = asistencia.de_materias(alcance) if fuente == 'materias' else asistencia.de_entrada(alcance)
    base = form.filtrar_inscripciones(base, prefijo='inscripcion__')
    aviso = None
    if desde and hasta and desde > hasta:
        aviso, base = 'Las fechas no tienen días en común con el periodo elegido.', base.none()
    else:
        if desde:
            base = base.filter(fecha__gte=desde)
        if hasta:
            base = base.filter(fecha__lte=hasta)
    estado = datos.get('estado') or ''
    if estado == 'ENTRARON' and fuente == 'materias':
        base = asistencia.entraron_y_faltaron(base)
    elif estado in ('FALTA', 'RETARDO', 'PRESENTE'):
        base = base.filter(estado=estado)
    elif estado != 'todos':
        base = base.filter(estado__in=('FALTA', 'RETARDO'))
    if datos.get('justificacion') == 'si':
        base = base.filter(justificada=True)
    elif datos.get('justificacion') == 'no':
        base = base.filter(justificada=False)
    if fuente == 'materias' and datos.get('materia'):
        base = base.filter(materia_grado=datos['materia'])

    resumen = base.aggregate(
        registros=Count('pk'), faltas=Count('pk', filter=Q(estado='FALTA')), retardos=Count('pk', filter=Q(estado='RETARDO')),
        justificadas=Count('pk', filter=Q(justificada=True)), estudiantes=Count('inscripcion__alumno', distinct=True),
    )
    if vista == 'estudiantes':
        filas = (
            base.order_by().values('inscripcion', 'inscripcion__alumno', 'inscripcion__alumno__nombre', 'inscripcion__alumno__apellido_paterno',
                                   'inscripcion__alumno__apellido_materno', 'inscripcion__alumno__referencia', 'inscripcion__grupo')
            .annotate(faltas=Count('pk', filter=Q(estado='FALTA')), retardos=Count('pk', filter=Q(estado='RETARDO')),
                      justificadas=Count('pk', filter=Q(justificada=True)), primera=Min('fecha'), ultima=Max('fecha'))
            .order_by('-faltas', '-retardos', 'inscripcion__alumno__apellido_paterno')
        )
    else:
        relacionados = ['inscripcion__alumno', 'inscripcion__grupo__nombre', 'inscripcion__grupo__grado', 'registrado_por']
        if fuente == 'materias':
            relacionados.append('materia_grado__materia')
        filas = base.select_related(*relacionados).order_by('-fecha', 'inscripcion__alumno__apellido_paterno')
    pagina, rango_paginas, por_pagina = paginar(request, filas)
    if vista == 'estudiantes':
        from Alumnos.models import Grupo
        grupos = {g.pk: g for g in Grupo.objects.filter(pk__in={f['inscripcion__grupo'] for f in pagina}).select_related('grado', 'nombre')}
        for fila in pagina:
            fila['grupo'] = grupos.get(fila['inscripcion__grupo'])
            fila['nombre'] = ' '.join(filter(None, (fila['inscripcion__alumno__nombre'], fila['inscripcion__alumno__apellido_paterno'], fila['inscripcion__alumno__apellido_materno'])))
    return render(request, 'prefectura/registros.html', {
        'seccion': 'asistencia', 'filtro': form, 'fuente': fuente, 'vista': vista, 'desde': desde, 'hasta': hasta, 'aviso': aviso,
        'resumen': resumen, 'pagina': pagina, 'rango_paginas': rango_paginas, 'por_pagina': por_pagina,
        'por_pagina_defecto': POR_PAGINA_DEFECTO, 'opciones_por_pagina': OPCIONES_POR_PAGINA, 'mas_filtros': form.activos,
        'puede': permisos_de(request.user), 'alcance': alcance,
    })


# ---------------------------------------------------------------------------
# Accesos al colegio
# ---------------------------------------------------------------------------
@requiere_permisos(VER)
def accesos(request):
    alcance = alcance_de(request.user)
    form = FiltroAccesosForm(request.GET or None, alcance=alcance)
    datos = form.datos()
    consulta = form.filtrar_inscripciones(asistencia.accesos(alcance), prefijo='inscripcion__')
    registros_elegidos = datos.get('registros') or 'vigentes'
    if registros_elegidos == 'vigentes':
        consulta = consulta.filter(anulado=False)
    elif registros_elegidos == 'anulados':
        consulta = consulta.filter(anulado=True)
    if datos.get('tipo'):
        consulta = consulta.filter(tipo=datos['tipo'])
    if datos.get('desde'):
        consulta = consulta.filter(fecha__gte=datos['desde'])
    if datos.get('hasta'):
        consulta = consulta.filter(fecha__lte=datos['hasta'])
    totales = dict(consulta.order_by().values_list('tipo').annotate(total=Count('pk')))
    filas = consulta.select_related('alumno', 'inscripcion__grupo__nombre', 'inscripcion__grupo__grado', 'registrado_por', 'anulado_por')
    pagina, rango_paginas, por_pagina = paginar(request, filas.order_by('-fecha', '-hora', '-pk'))
    for movimiento in pagina:
        movimiento.corregible = asistencia.puede_corregir_acceso(request.user, movimiento)
    return render(request, 'prefectura/accesos.html', {
        'seccion': 'accesos', 'filtro': form, 'pagina': pagina, 'rango_paginas': rango_paginas, 'por_pagina': por_pagina,
        'por_pagina_defecto': POR_PAGINA_DEFECTO, 'opciones_por_pagina': OPCIONES_POR_PAGINA,
        'totales': [(nombre, totales.get(clave, 0)) for clave, nombre in MovimientoAcceso.TIPOS],
        'puede': permisos_de(request.user), 'alcance': alcance,
    })


def _url_buscar():
    return reverse('conducta:buscar')


@requiere_permisos(VER, REGISTRAR)
def acceso_crear(request):
    alcance = alcance_de(request.user)
    alumnos = alcance.alumnos()
    if request.method == 'POST':
        form = AccesoForm(request.POST, alumnos=alumnos)
        if form.is_valid():
            inscripcion = reglas.inscripcion_actual(form.cleaned_data['alumno'])
            if inscripcion is None:
                form.add_error(None, 'El estudiante no tiene inscripción vigente en el ciclo actual.')
            else:
                movimiento = asistencia.registrar_acceso(inscripcion, form.cleaned_data, request.user)
                efecto = (' Cuenta como retardo en la entrada y falta en la primera hora (lo que el docente ya capturó se respeta).'
                          if movimiento.tipo == MovimientoAcceso.RETARDO else ' No cambia el pase de lista de los docentes.')
                messages.success(request, f'Se registró: {movimiento.get_tipo_display().lower()} de {movimiento.alumno} a las {movimiento.hora:%H:%M}.' + efecto)
                return redirect(destino_seguro(request, reverse('prefectura:accesos')))
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    else:
        ahora = timezone.localtime()
        alumno_id = request.GET.get('alumno', '')
        inicial = {'fecha': ahora.date(), 'hora': ahora.strftime('%H:%M'), 'tipo': request.GET.get('tipo') or MovimientoAcceso.RETARDO}
        if alumno_id.isdigit() and alumnos.filter(pk=alumno_id).exists():
            inicial['alumno'] = int(alumno_id)
        form = AccesoForm(alumnos=alumnos, initial=inicial)
    alumno = form.fields['alumno'].queryset.filter(pk=form['alumno'].value()).first() if str(form['alumno'].value() or '').isdigit() else None
    return render(request, 'prefectura/acceso_form.html', {'seccion': 'accesos', 'form': form, 'alumno': alumno, 'url_buscar': _url_buscar(),
                                                            'volver': reverse('prefectura:accesos')})


def _movimiento(request, pk):
    return get_object_or_404(
        asistencia.accesos(alcance_de(request.user)).select_related('alumno', 'inscripcion__ciclo', 'registrado_por'), pk=pk,
    )


@requiere_alguno(CORREGIR, CORREGIR_OTROS)
def acceso_corregir(request, pk):
    movimiento = _movimiento(request, pk)
    if not asistencia.puede_corregir_acceso(request.user, movimiento):
        raise PermissionDenied
    alumnos = alcance_de(request.user).alumnos()
    form = AccesoForm(request.POST if request.method == 'POST' else None, alumnos=alumnos, movimiento=movimiento)
    if request.method == 'POST':
        if form.is_valid():
            dejo_asistencia = asistencia.corregir_acceso(movimiento, form.cleaned_data, form.cleaned_data['motivo_cambio'], request.user)
            messages.success(request, 'Se corrigió el registro de acceso. Queda en su historial.')
            if dejo_asistencia:
                messages.info(request, 'El retardo que se había registrado en la asistencia de ese día no se revierte solo: pide a la administración que lo revise en Asistencias.')
            return redirect(destino_seguro(request, reverse('prefectura:accesos')))
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return render(request, 'prefectura/acceso_form.html', {'seccion': 'accesos', 'form': form, 'movimiento': movimiento, 'alumno': movimiento.alumno,
                                                            'volver': reverse('prefectura:accesos')})


@requiere_alguno(CORREGIR, CORREGIR_OTROS)
def acceso_anular(request, pk):
    movimiento = _movimiento(request, pk)
    if not asistencia.puede_corregir_acceso(request.user, movimiento):
        raise PermissionDenied
    form = MotivoForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        if form.is_valid():
            asistencia.anular_acceso(movimiento, form.cleaned_data['motivo'], request.user)
            messages.success(request, 'Se anuló el registro de acceso. Se conserva con el motivo en su historial.')
            if movimiento.tipo == MovimientoAcceso.RETARDO:
                messages.info(request, 'El retardo que registró en la asistencia de ese día no se revierte solo: pide a la administración que lo revise en Asistencias.')
            return redirect(destino_seguro(request, reverse('prefectura:accesos')))
        messages.error(request, 'Escribe el motivo.')
    return render(request, 'prefectura/motivo.html', {
        'seccion': 'accesos', 'form': form, 'titulo': 'Anular registro de acceso', 'objeto': movimiento,
        'descripcion': f'{movimiento.get_tipo_display()} de {movimiento.alumno} el {movimiento.fecha:%d/%m/%Y} a las {movimiento.hora:%H:%M}. '
                       'No se borra: queda anulado, con el motivo, en su historial.',
        'boton': 'Anular registro', 'volver': reverse('prefectura:accesos'),
    })


@requiere_permisos(VER)
def acceso(request, pk):
    movimiento = _movimiento(request, pk)
    return render(request, 'prefectura/acceso.html', {
        'seccion': 'accesos', 'movimiento': movimiento, 'cambios': list(movimiento.cambios.select_related('usuario')),
        'corregible': asistencia.puede_corregir_acceso(request.user, movimiento),
    })


# ---------------------------------------------------------------------------
# Justificaciones
# ---------------------------------------------------------------------------
def _justificaciones_de(alcance):
    return alcance.filtrar(Justificacion.objects.all(), campo='inscripcion__alumno')


@requiere_permisos(VER)
def justificaciones(request):
    alcance = alcance_de(request.user)
    consulta = _justificaciones_de(alcance).select_related(
        'inscripcion__alumno', 'inscripcion__grupo__nombre', 'inscripcion__grupo__grado', 'registrada_por', 'revocada_por',
        'asistencia__materia_grado__materia',
    )
    texto = request.GET.get('q', '').strip()
    for palabra in texto.split():
        consulta = consulta.filter(
            Q(inscripcion__alumno__nombre__icontains=palabra) | Q(inscripcion__alumno__apellido_paterno__icontains=palabra)
            | Q(inscripcion__alumno__apellido_materno__icontains=palabra) | Q(inscripcion__alumno__referencia__icontains=palabra)
        )
    desde, hasta = fecha_de(request.GET.get('desde')), fecha_de(request.GET.get('hasta'))
    if desde:
        consulta = consulta.filter(fecha__gte=desde)
    if hasta:
        consulta = consulta.filter(fecha__lte=hasta)
    estado = request.GET.get('estado', '')
    if estado == 'vigentes':
        consulta = consulta.filter(activa=True)
    elif estado == 'revocadas':
        consulta = consulta.filter(activa=False)

    # Las de un mismo envío (lote) se ven juntas
    grupos, orden = {}, []
    for justificacion in consulta.order_by('-creado', 'fecha'):
        clave = justificacion.lote or f'j{justificacion.pk}'
        if clave not in grupos:
            grupos[clave] = {'principal': justificacion, 'registros': []}
            orden.append(clave)
        grupos[clave]['registros'].append(justificacion)
    filas = []
    for clave in orden:
        grupo = grupos[clave]
        fechas = sorted(j.fecha for j in grupo['registros'])
        grupo.update(desde=fechas[0], hasta=fechas[-1], vigentes=sum(1 for j in grupo['registros'] if j.activa))
        filas.append(grupo)
    pagina, rango_paginas, por_pagina = paginar(request, filas)
    return render(request, 'prefectura/justificaciones.html', {
        'seccion': 'justificaciones', 'pagina': pagina, 'rango_paginas': rango_paginas, 'por_pagina': por_pagina,
        'por_pagina_defecto': POR_PAGINA_DEFECTO, 'opciones_por_pagina': OPCIONES_POR_PAGINA,
        'q': texto, 'desde': desde, 'hasta': hasta, 'estado': estado, 'puede': permisos_de(request.user),
    })


def _parametros_de_justificacion(datos):
    estados = [e for e in (datos.getlist('estados') if hasattr(datos, 'getlist') else datos.get('estados', [])) if e in ('FALTA', 'RETARDO')]
    return estados or ['FALTA'], datos.get('con_entrada') in ('on', 'true', '1', True)


@requiere_permisos(VER, JUSTIFICAR)
def justificar(request):
    alcance = alcance_de(request.user)
    alumnos = alcance.alumnos()
    if request.method == 'POST':
        form = JustificarForm(request.POST, request.FILES, alumnos=alumnos)
        if form.is_valid():
            datos = form.cleaned_data
            inscripcion = reglas.inscripcion_actual(datos['alumno'])
            if inscripcion is None:
                form.add_error(None, 'El estudiante no tiene inscripción vigente en el ciclo actual.')
            else:
                try:
                    _, creadas = asistencia.justificar(
                        inscripcion, datos['desde'], datos['hasta'], datos['estados'], datos['con_entrada'], datos['confirmados'],
                        datos['motivo'], datos['comprobante'], request.user,
                    )
                except asistencia.JustificacionRechazada as error:
                    form.add_error(None, str(error))
                else:
                    messages.success(request, f'Se justificaron {len(creadas)} registro{"s" if len(creadas) != 1 else ""} de {inscripcion.alumno}. '
                                              'Conservan su estado original (la falta sigue siendo falta) y quedan vinculados a esta justificación.')
                    return redirect(destino_seguro(request, reverse('prefectura:justificaciones')))
        messages.error(request, 'Revisa los datos: la justificación no se guardó.')
    else:
        hoy = timezone.localdate()
        alumno_id = request.GET.get('alumno', '')
        inicial = {'desde': fecha_de(request.GET.get('desde')) or hoy, 'hasta': fecha_de(request.GET.get('hasta')) or hoy,
                   'estados': request.GET.getlist('estados') or ['FALTA'], 'con_entrada': True}
        if alumno_id.isdigit() and alumnos.filter(pk=alumno_id).exists():
            inicial['alumno'] = int(alumno_id)
        form = JustificarForm(alumnos=alumnos, initial=inicial)
    valor = form['alumno'].value()
    alumno = alumnos.filter(pk=valor).first() if str(valor or '').isdigit() else None
    return render(request, 'prefectura/justificar.html', {
        'seccion': 'justificaciones', 'form': form, 'alumno': alumno, 'url_buscar': _url_buscar(),
        'url_previa': reverse('prefectura:justificar_previa'), 'acepta': FOTOS, 'maximo_mb': TAMANO_MAXIMO,
        'volver': reverse('prefectura:justificaciones'),
    })


@require_GET
@requiere_permisos(VER, JUSTIFICAR)
def justificar_previa(request):
    """Los registros que se justificarían (JSON), para mostrarlos y confirmarlos antes de guardar."""
    alcance = alcance_de(request.user)
    alumno_id = request.GET.get('alumno', '')
    alumno = alcance.alumnos().filter(pk=alumno_id).first() if alumno_id.isdigit() else None
    if alumno is None:
        return JsonResponse({'ok': False, 'mensaje': 'Elige un estudiante de tu alcance.'}, status=400)
    desde, hasta = fecha_de(request.GET.get('desde')), fecha_de(request.GET.get('hasta'))
    if not desde or not hasta or desde > hasta:
        return JsonResponse({'ok': False, 'mensaje': 'Indica un rango de fechas válido.'}, status=400)
    if (hasta - desde).days + 1 > asistencia.DIAS_MAXIMOS_POR_JUSTIFICACION:
        return JsonResponse({'ok': False, 'mensaje': f'Justifica como máximo {asistencia.DIAS_MAXIMOS_POR_JUSTIFICACION} días a la vez.'}, status=400)
    inscripcion = reglas.inscripcion_actual(alumno)
    if inscripcion is None:
        return JsonResponse({'ok': False, 'mensaje': 'El estudiante no tiene inscripción vigente en el ciclo actual.'}, status=400)
    estados, con_entrada = _parametros_de_justificacion(request.GET)
    afectados = asistencia.por_justificar(inscripcion, desde, hasta, estados, con_entrada)
    return JsonResponse({'ok': True, 'registros': [a.como_dict() for a in afectados], 'total': len(afectados)})


@requiere_permisos(VER, JUSTIFICAR)
def justificacion_revocar(request, pk):
    justificacion = get_object_or_404(
        _justificaciones_de(alcance_de(request.user)).select_related('inscripcion__alumno', 'inscripcion__ciclo'), pk=pk,
    )
    vigentes = asistencia.del_mismo_envio(justificacion)
    if not vigentes.exists():
        messages.info(request, 'Esa justificación ya estaba revocada.')
        return redirect('prefectura:justificaciones')
    if not justificacion.inscripcion.ciclo.activo:
        messages.error(request, 'Es de un ciclo que ya no se modifica.')
        return redirect('prefectura:justificaciones')
    form = MotivoForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        if form.is_valid():
            cuantas = asistencia.revocar(justificacion, form.cleaned_data['motivo'], request.user)
            messages.success(request, f'Se revocó la justificación ({cuantas} registro{"s" if cuantas != 1 else ""}). '
                                      'Vuelven a contar sin justificar; queda en el historial quién, cuándo y por qué.')
            return redirect(destino_seguro(request, reverse('prefectura:justificaciones')))
        messages.error(request, 'Escribe el motivo de la revocación.')
    cuantas = vigentes.count()
    return render(request, 'prefectura/motivo.html', {
        'seccion': 'justificaciones', 'form': form, 'titulo': 'Revocar justificación', 'objeto': justificacion,
        'descripcion': f'{justificacion.inscripcion.alumno}: {cuantas} registro{"s" if cuantas != 1 else ""} justificado{"s" if cuantas != 1 else ""} '
                       f'con el motivo «{justificacion.motivo[:120]}». Dejarán de estar justificados; nada se borra.',
        'boton': 'Revocar justificación', 'volver': reverse('prefectura:justificaciones'),
    })
