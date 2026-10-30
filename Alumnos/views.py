import csv
from urllib.parse import urlencode

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from CISAHUAYO import portales
from CISAHUAYO.paginacion import OPCIONES_POR_PAGINA, POR_PAGINA_DEFECTO, paginar
from CISAHUAYO.permisos import requiere_alguno, requiere_permisos
from CISAHUAYO.redireccion import destino_seguro

from . import columnas, historial, importacion, lote, tabla
from .academico import prefetch_inscripciones_actuales, sincronizar_inscripciones
from .asistencias import con_justificada_general
from .clases import grupos_de_clase_de
from .forms import (
    AlumnoForm,
    FiltroAlumnosForm,
    ImportarEstudiantesForm,
    InscribirForm,
    InscripcionInicialForm,
    LoteEstatusForm,
    LoteGrupoForm,
    RestablecerContrasenaForm,
    TutoresFormSet,
    ciclo_activo,
    guardar_vinculos,
    iniciales_vinculos,
)
from .models import Alumno, AsistenciaGeneral, Grado, Inscripcion, Tutor, TutorAlumno
from .utils import ESTADOS_MX, generar_contrasena, proteger_celda_csv
from .vinculos import prefetch_vinculos_activos

SESION_CREDENCIALES = 'credenciales_alumno'


def _credenciales(alumno, contrasena):
    """Las credenciales que se muestran una vez: con su correo, que es con lo que entra al portal de estudiantes."""
    datos = {'pk': alumno.pk, 'nombre': str(alumno), 'url': alumno.get_absolute_url(), 'referencia': alumno.referencia,
             'contrasena': contrasena, 'portal': portales.NOMBRE[portales.ESTUDIANTE]}
    if alumno.correo_electronico:
        datos.update(etiqueta='Correo electrónico', usuario=alumno.correo_electronico)
    else:
        datos['aviso'] = 'Para entrar al portal necesita un correo electrónico: regístralo al editar sus datos.'
    return datos
SESION_IMPORTACION = 'importacion_estudiantes'                  # el resumen de la última importación (se muestra una vez)
SESION_IMPORTACION_CREDENCIALES = 'importacion_credenciales'    # sus contraseñas, para descargarlas
SESION_LOTE_CREDENCIALES = 'lote_credenciales'                  # las contraseñas generadas en lote, para descargarlas
SESION_COMUNICADO = 'comunicado_a_tutores'                      # los tutores elegidos en la tabla para un comunicado

PASOS_FORMULARIO = (
    {'clave': 'identidad', 'titulo': 'Identidad', 'icono': 'user'},
    {'clave': 'domicilio', 'titulo': 'Domicilio y salud', 'icono': 'map-pin'},
    {'clave': 'escolar', 'titulo': 'Datos escolares', 'icono': 'graduation-cap'},
    {'clave': 'tutores', 'titulo': 'Tutores', 'icono': 'users'},
    {'clave': 'revision', 'titulo': 'Revisión', 'icono': 'clipboard-check'},
)


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------
def _acciones_en_lote(usuario):
    """Qué acciones en lote puede usar la cuenta (sin ninguna, la tabla no muestra las casillas)."""
    from Comunicados.alcance import ENVIAR, alcance_de
    acciones = {
        'grupo': usuario.has_perm('Alumnos.add_inscripcion') and usuario.has_perm('Alumnos.change_inscripcion'),
        'estatus': usuario.has_perm('Alumnos.change_alumno'),
        'contrasenas': usuario.has_perm('Alumnos.change_alumno'),
        'exportar': usuario.has_perm('Alumnos.view_alumno'),
        'comunicado': usuario.has_perm(ENVIAR) and alcance_de(usuario).puede_enviar,
    }
    acciones['alguna'] = any(acciones.values())
    return acciones


def _contadores(filtro):
    """Cuántos estudiantes hay en cada nivel y, con un nivel elegido, en cada uno de sus grupos (con los demás filtros)."""
    from .models import ORDEN_NIVELES
    base = filtro.filtrar(Alumno.objects.all(), sin=('nivel', 'grado', 'grupo', 'orden'))
    vigentes = Inscripcion.objects.filter(activa=True, ciclo__activo=True, alumno__in=base.values('pk'))
    nombres = dict(Grado.NIVEL_CHOICES)
    # Los contadores son filtros: los de un grado oculto no se ofrecen (sus estudiantes siguen en la tabla)
    vigentes = vigentes.filter(grado__visible=True)
    por_nivel = dict(vigentes.values_list('grado__nivel').annotate(n=Count('alumno', distinct=True)))
    niveles = [(nivel, nombres.get(nivel, nivel), por_nivel[nivel]) for nivel in ORDEN_NIVELES if por_nivel.get(nivel)]
    nivel = filtro.activos.get('nivel')
    grupos = []
    if nivel:
        filas = (vigentes.filter(grado__nivel=nivel).values('grupo').annotate(n=Count('alumno', distinct=True)).order_by())
        cuenta = {fila['grupo']: fila['n'] for fila in filas}
        from .models import Grupo
        for grupo in Grupo.objects.filter(pk__in=cuenta).select_related('grado', 'nombre').academicos():
            grupos.append((grupo.pk, grupo.nombre_equivalente, cuenta[grupo.pk]))
    return {'niveles': niveles, 'grupos': grupos}


@requiere_permisos('Alumnos.view_alumno')
def alumno_lista(request):
    filtro = FiltroAlumnosForm(request.GET, usuario=request.user)
    alumnos = filtro.filtrar(Alumno.objects.all()).prefetch_related(
        prefetch_inscripciones_actuales(), prefetch_vinculos_activos(),
    )
    pagina, rango_paginas, por_pagina = paginar(request, alumnos)
    visibles = columnas.elegidas(request.user)
    # La página guarda la lista: las señales y los datos de cada columna quedan en los mismos objetos que pinta la tabla
    filas = list(pagina)
    tabla.preparar_filas(request.user, filas, con_asistencia='asistencia_hoy' in visibles)
    columnas.preparar(request.user, filas, visibles)
    orden = filtro.activos.get('orden', 'nombre')
    acciones = _acciones_en_lote(request.user)

    conteos = dict(Alumno.objects.values_list('estatus').annotate(total=Count('pk')))
    estatus_filtros = [
        {'valor': valor, 'etiqueta': etiqueta, 'total': conteos.get(valor, 0)}
        for valor, etiqueta in Alumno.ESTATUS_CHOICES
    ]
    filtros_activos = {k: v for k, v in filtro.activos.items() if k != 'orden'}

    return render(request, 'alumnos/lista.html', {
        'filtro': filtro,
        'pagina': pagina,
        'rango_paginas': rango_paginas,
        'por_pagina': por_pagina,
        'por_pagina_defecto': POR_PAGINA_DEFECTO,
        'opciones_por_pagina': OPCIONES_POR_PAGINA,
        'estatus_filtros': estatus_filtros,
        # «Todos» no incluye las bajas: se consultan en su propio filtro
        'total_alumnos': sum(total for estatus, total in conteos.items() if estatus != 'BAJA'),
        'total_bajas': conteos.get('BAJA', 0),
        'filtros_activos': filtros_activos,
        'orden': orden,
        'columnas': tabla.columnas_de_orden(orden),
        'visibles': visibles,
        'menu_columnas': [(columna, columna.clave in visibles) for columna in columnas.disponibles(request.user)],
        'mas_filtros': filtro.mas_activos,
        'contadores': _contadores(filtro),
        'acciones_lote': acciones,
        'form_lote_grupo': LoteGrupoForm() if acciones['grupo'] else None,
        'form_lote_estatus': LoteEstatusForm() if acciones['estatus'] else None,
        'consulta': request.GET.urlencode(),
        'ciclo_actual': ciclo_activo(),
        # Tras registrar a un alumno se muestran, una sola vez, sus credenciales de acceso
        'credenciales': request.session.pop(SESION_CREDENCIALES, None),
        # Y, tras importar un archivo, el resumen de lo que pasó con cada fila
        'importacion': request.session.pop(SESION_IMPORTACION, None),
        'hay_credenciales_lote': bool(request.session.get(SESION_LOTE_CREDENCIALES)),
    })


@require_POST
@requiere_permisos('Alumnos.view_alumno')
def alumno_columnas(request):
    """El menú «Columnas»: guarda en el perfil las columnas elegidas (o vuelve a las de siempre)."""
    if request.POST.get('restablecer'):
        columnas.guardar(request.user, None)
    else:
        columnas.guardar(request.user, request.POST.getlist('columnas'))
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'columnas': columnas.elegidas(request.user)})
    return redirect(destino_seguro(request, reverse('alumnos:lista')))


# ---------------------------------------------------------------------------
# Alta y edición (asistente de pasos)
# ---------------------------------------------------------------------------
def _contexto_formulario(request, form, tutores, inscripcion=None, alumno=None):
    paso_inicial = request.GET.get('paso')
    claves = [paso['clave'] for paso in PASOS_FORMULARIO]
    return {
        'form': form,
        'tutores': tutores,
        'inscripcion': inscripcion,
        'alumno': alumno,
        'es_edicion': alumno is not None,
        'pasos': PASOS_FORMULARIO,
        'estados_mx': ESTADOS_MX,
        'paso_inicial': claves.index(paso_inicial) if paso_inicial in claves else 0,
    }


@requiere_permisos('Alumnos.add_alumno')
def alumno_crear(request):
    if request.method == 'POST':
        form = AlumnoForm(request.POST, request.FILES)
        tutores = TutoresFormSet(request.POST, prefix='tutores')
        tutores.requiere_tutor = True
        inscripcion = InscripcionInicialForm(request.POST, prefix='insc')

        # Se validan los tres para mostrar todos los errores a la vez.
        if all([form.is_valid(), tutores.is_valid(), inscripcion.is_valid()]):
            try:
                with transaction.atomic():
                    alumno = form.save()
                    guardar_vinculos(alumno, tutores)
                    inscrito = inscripcion.guardar(alumno)
            except IntegrityError:
                form.add_error(None, 'No se pudo guardar: la referencia, la CURP o algún dato único acaba de registrarse. Revisa e intenta de nuevo.')
            else:
                request.session[SESION_CREDENCIALES] = _credenciales(alumno, form.contrasena_en_claro)
                detalle = f' e inscrito en {inscrito.grado}' if inscrito else ''
                historial.anotar(request.user, alumno, f'Registró al estudiante{detalle}.', historial.ALTA)
                messages.success(request, f'{alumno} fue registrado correctamente{detalle}.')
                return redirect('alumnos:lista')
        messages.error(request, 'Revisa los pasos marcados: hay datos por corregir.')
    else:
        form = AlumnoForm()
        tutores = TutoresFormSet(prefix='tutores')
        inscripcion = InscripcionInicialForm(prefix='insc')

    return render(request, 'alumnos/form.html', _contexto_formulario(request, form, tutores, inscripcion))


@requiere_permisos('Alumnos.change_alumno')
def alumno_editar(request, pk):
    alumno = get_object_or_404(Alumno, pk=pk)
    estatus_anterior = alumno.estatus   # antes de validar: el formulario lo cambia en la instancia

    if request.method == 'POST':
        form = AlumnoForm(request.POST, request.FILES, instance=alumno)
        tutores = TutoresFormSet(request.POST, prefix='tutores')

        if all([form.is_valid(), tutores.is_valid()]):
            vinculos_antes = _vinculos_de(alumno)
            try:
                with transaction.atomic():
                    form.save()
                    guardar_vinculos(alumno, tutores)
                    suspendidas, restauradas = sincronizar_inscripciones(alumno, estatus_anterior)
                    _anotar_edicion(request.user, alumno, form, estatus_anterior, vinculos_antes)
            except IntegrityError:
                form.add_error(None, 'No se pudo guardar: algún dato único ya pertenece a otro registro.')
            else:
                messages.success(request, f'Los datos de {alumno} se actualizaron.{_texto_de_inscripciones(suspendidas, restauradas)}')
                return redirect('alumnos:lista')
        messages.error(request, 'Revisa los pasos marcados: hay datos por corregir.')
    else:
        form = AlumnoForm(instance=alumno)
        tutores = TutoresFormSet(initial=iniciales_vinculos(alumno), prefix='tutores')

    return render(request, 'alumnos/form.html', _contexto_formulario(request, form, tutores, alumno=alumno))


def _vinculos_de(alumno):
    return set(TutorAlumno.objects.filter(alumno=alumno).values_list('tutor_id', 'parentesco', 'tutor_principal', 'activo'))


def _anotar_edicion(usuario, alumno, form, estatus_anterior, vinculos_antes):
    """El historial de una edición: qué datos cambiaron, el estatus y si cambiaron sus tutores."""
    partes = []
    cambios = historial.campos_cambiados(form, excluir={'estatus'})
    if cambios:
        partes.append(f'Corrigió {cambios}')
    if alumno.estatus != estatus_anterior:
        partes.append(f'cambió su estatus de «{dict(Alumno.ESTATUS_CHOICES).get(estatus_anterior, estatus_anterior)}» a «{alumno.get_estatus_display()}»')
    if _vinculos_de(alumno) != vinculos_antes:
        partes.append('actualizó sus tutores')
    if partes:
        texto = '; '.join(partes)
        historial.anotar(usuario, alumno, texto[0].upper() + texto[1:] + '.')


# ---------------------------------------------------------------------------
# Perfil
# ---------------------------------------------------------------------------
def _resumen_asistencia(inscripcion):
    if not inscripcion:
        return None
    registros = con_justificada_general(AsistenciaGeneral.objects.filter(inscripcion=inscripcion))
    conteo = registros.aggregate(
        total=Count('pk'),
        presentes=Count('pk', filter=Q(estado='PRESENTE')),
        retardos=Count('pk', filter=Q(estado='RETARDO')),
        faltas=Count('pk', filter=Q(estado='FALTA')),
        justificadas=Count('pk', filter=Q(estado='FALTA', justificada=True)),
    )
    conteo['porcentaje'] = round(100 * (conteo['presentes'] + conteo['retardos']) / conteo['total']) if conteo['total'] else None
    conteo['recientes'] = list(registros.order_by('-fecha')[:8])
    return conteo


@requiere_permisos('Alumnos.view_alumno')
def alumno_detalle(request, pk):
    alumno = get_object_or_404(Alumno, pk=pk)
    inscripciones = list(alumno.inscripciones.select_related('grado', 'grupo__nombre', 'grupo__grado', 'ciclo').order_by('-ciclo__fecha_inicio', '-fecha_inscripcion'))
    inscripcion_actual = next((i for i in inscripciones if i.activa and i.ciclo.activo), None)
    vinculos = list(alumno.tutores_relacionados.select_related('tutor').order_by('-tutor_principal', 'tutor__apellido_paterno'))
    # El primero (los principales van antes) con vínculo activo y tutor vigente es el contacto principal
    tutor_principal = next((v for v in vinculos if v.activo and v.tutor.estatus == 'ACTIVO'), None)

    credenciales = None
    guardadas = request.session.get(SESION_CREDENCIALES)
    if guardadas and guardadas.get('pk') == alumno.pk:
        credenciales = request.session.pop(SESION_CREDENCIALES)  # se muestran una sola vez

    return render(request, 'alumnos/detalle.html', {
        'alumno': alumno,
        'vinculos': vinculos,
        'tutor_principal': tutor_principal,
        'inscripciones': inscripciones,
        'inscripcion_actual': inscripcion_actual,
        'asistencia': _resumen_asistencia(inscripcion_actual),
        'justificaciones': alumno.inscripciones.aggregate(total=Count('justificaciones'))['total'],
        'credenciales': credenciales,
        'portal': portales.estado_de_cuenta(portales.ESTUDIANTE, alumno),
        'esta_de_baja': alumno.estatus == 'BAJA',
        'inscribir_form': InscribirForm(alumno=alumno),
        # La baja tiene su propia acción: el menú ofrece solo los demás estatus
        'estatus_opciones': [(v, e) for v, e in Alumno.ESTATUS_CHOICES if v != 'BAJA'],
        'conducta': _conducta_de(request, alumno),
        'historial': [(entrada, historial.nombre_de_accion(entrada)) for entrada in historial.de(alumno)],
        # Boletas e historial académico (2026-10-29): para quien ve todas las calificaciones
        'boletas_ciclos': _ciclos_de_boleta(request.user, inscripciones),
        'grupos_de_clase': grupos_de_clase_de(alumno),
    })


def _ciclos_de_boleta(usuario, inscripciones):
    """Los ciclos con boleta (los de sus inscripciones, del más reciente) si la cuenta ve todas las calificaciones;
    None si no."""
    from Calificaciones.reglas import ve_todas
    if not ve_todas(usuario):
        return None
    return list({i.ciclo_id: i.ciclo for i in inscripciones}.values())


@require_GET
@requiere_permisos('Alumnos.view_alumno')
def alumno_vista_rapida(request, pk):
    """La vista rápida de la tabla: los datos clave en un panel lateral (static/js/alumnos-lista.js la pide al tocar el
    nombre), sin salir de la lista."""
    alumno = get_object_or_404(Alumno.objects.prefetch_related(prefetch_inscripciones_actuales(), prefetch_vinculos_activos()), pk=pk)
    filas = [alumno]
    ve_asistencia = request.user.has_perm('Alumnos.view_asistenciageneral')
    tabla.preparar_filas(request.user, filas, con_asistencia=ve_asistencia)
    claves = ['portal'] + (['asistencia_ciclo'] if ve_asistencia else []) + [c for c in ('promedio', 'conducta')
                                                                            if columnas.POR_CLAVE[c].permiso(request.user)]
    columnas.preparar(request.user, filas, claves)
    return render(request, 'alumnos/_vista_rapida.html', {
        'alumno': alumno, 'inscripcion': (alumno.inscripciones_actuales or [None])[0], 'vinculos': alumno.vinculos_activos,
        've_asistencia': ve_asistencia, 'claves': claves,
    })


@requiere_permisos('Alumnos.view_alumno')
def alumno_vista360(request, pk):
    """Vista 360 del estudiante: lo de calificaciones, asistencia, conducta, seguimiento y retiros de un ciclo y un
    periodo, en un círculo (Alumnos/vista360.py). Cada sección revisa los permisos de su módulo."""
    from . import vista360
    alumno = get_object_or_404(Alumno, pk=pk)
    contexto = vista360.contexto(
        request.user, alumno, request.GET.get('ciclo', ''), request.GET.get('periodo', ''), request.GET.get('seccion', ''),
    )
    contexto.update({
        'grupos_de_clase': grupos_de_clase_de(alumno, contexto['inscripcion'].ciclo_id) if contexto.get('inscripcion') else [],
        'tiene_conducta': request.user.has_perm('Conducta.view_registroconducta'),
        'estatus_opciones': [(v, e) for v, e in Alumno.ESTATUS_CHOICES if v != 'BAJA'],
        'esta_de_baja': alumno.estatus == 'BAJA',
    })
    return render(request, 'alumnos/vista360.html', contexto)


def _conducta_de(request, alumno):
    """Su historial de conducta (pestaña «Conducta» del expediente), solo para quien puede consultarlo."""
    if not request.user.has_perm('Conducta.view_registroconducta'):
        return None
    from Conducta.reglas import linea_de_tiempo
    return linea_de_tiempo(alumno)


# ---------------------------------------------------------------------------
# Acciones sobre un alumno
# ---------------------------------------------------------------------------
def _texto_de_inscripciones(suspendidas, restauradas):
    """« Su inscripción en 2.º Primaria (2026-2027) quedó desactivada.» (o reactivada; vacío si no había)."""
    partes = []
    for inscripciones, verbo in ((suspendidas, 'desactivada'), (restauradas, 'reactivada')):
        if inscripciones:
            lista = ', '.join(f'{i.grado} ({i.ciclo})' for i in inscripciones)
            plural = len(inscripciones) != 1
            partes.append(f' Su{"s" if plural else ""} inscripci{"ones" if plural else "ón"} en {lista} '
                          f'qued{"aron" if plural else "ó"} {verbo}{"s" if plural else ""}.')
    return ''.join(partes)


@require_POST
@requiere_permisos('Alumnos.change_alumno')
def alumno_estatus(request, pk):
    alumno = get_object_or_404(Alumno, pk=pk)
    estatus = request.POST.get('estatus')
    if estatus == 'BAJA':
        messages.error(request, 'Para dar de baja a un estudiante usa la opción «Dar de baja».')
    elif estatus not in dict(Alumno.ESTATUS_CHOICES):
        messages.error(request, 'El estatus indicado no es válido.')
    else:
        anterior = alumno.estatus
        with transaction.atomic():
            alumno.estatus = estatus
            alumno.save(update_fields=['estatus'])
            suspendidas, restauradas = sincronizar_inscripciones(alumno, anterior)
            if estatus != anterior:
                historial.anotar(request.user, alumno, f'Cambió su estatus de «{dict(Alumno.ESTATUS_CHOICES)[anterior]}» a «{alumno.get_estatus_display()}».')
        messages.success(request, f'{alumno} ahora está en estatus «{alumno.get_estatus_display()}».'
                                  f'{_texto_de_inscripciones(suspendidas, restauradas)}')
    return redirect(destino_seguro(request, alumno.get_absolute_url()))   # la Vista 360 pide volver a ella


@require_POST
@requiere_permisos('Alumnos.delete_alumno')
def alumno_baja(request, pk):
    """Baja lógica: el alumno deja de aparecer en el listado, pero nada se borra. Sus inscripciones del ciclo actual (y
    de los próximos) se desactivan con él, y vuelven si se le reactiva."""
    alumno = get_object_or_404(Alumno, pk=pk)
    if alumno.estatus == 'BAJA':
        messages.info(request, f'{alumno} ya estaba dado de baja.')
    else:
        anterior = alumno.estatus
        with transaction.atomic():
            alumno.estatus = 'BAJA'
            alumno.save(update_fields=['estatus'])
            suspendidas, _ = sincronizar_inscripciones(alumno, anterior)
            historial.anotar(request.user, alumno, 'Lo dio de baja.' + _texto_de_inscripciones(suspendidas, []), historial.BAJA)
        messages.success(
            request,
            f'{alumno} fue dado de baja.{_texto_de_inscripciones(suspendidas, [])} '
            'Su historial se conserva y puedes reactivarlo desde el filtro «Bajas».',
        )
    return redirect('alumnos:lista')


@require_POST
@requiere_permisos('Alumnos.change_alumno')
def alumno_reactivar(request, pk):
    alumno = get_object_or_404(Alumno, pk=pk)
    if alumno.estatus == 'BAJA':
        with transaction.atomic():
            alumno.estatus = 'ACTIVO'
            alumno.save(update_fields=['estatus'])
            _, restauradas = sincronizar_inscripciones(alumno, 'BAJA')
            historial.anotar(request.user, alumno, 'Lo reactivó.' + _texto_de_inscripciones([], restauradas))
        messages.success(request, f'{alumno} fue reactivado.{_texto_de_inscripciones([], restauradas)}')
    return redirect('alumnos:lista')


@require_POST
@requiere_permisos('Alumnos.change_alumno')
def alumno_contrasena(request, pk):
    """Restablece la contraseña: la que se escriba o, si se deja vacía, una generada."""
    alumno = get_object_or_404(Alumno, pk=pk)
    form = RestablecerContrasenaForm(request.POST)
    if not form.is_valid():
        messages.error(request, f'No se cambió la contraseña de {alumno}: {form.errors["contrasena"][0]}')
        return redirect(alumno)
    nueva = form.cleaned_data['contrasena'] or generar_contrasena()
    alumno.establecer_contrasena(nueva)
    alumno.save(update_fields=['contrasena', 'contrasena_visible', 'intentos_fallidos', 'bloqueado_hasta'])
    historial.anotar(request.user, alumno, 'Le asignó una contraseña nueva para el portal.')
    request.session[SESION_CREDENCIALES] = _credenciales(alumno, nueva)
    messages.success(request, f'Se asignó una nueva contraseña a {alumno}.')
    return redirect(alumno)


@require_POST
@requiere_permisos('Alumnos.change_alumno')
def alumno_portal(request, pk):
    """Activa, desactiva o desbloquea el acceso del estudiante al portal de estudiantes."""
    alumno = get_object_or_404(Alumno, pk=pk)
    try:
        resultado = portales.administrar_acceso(alumno, request.POST.get('accion', ''))
    except ValueError as error:
        messages.error(request, str(error))
    else:
        historial.anotar(request.user, alumno, f'Portal: {resultado}')
        messages.success(request, resultado)
    return redirect(alumno)


@require_POST
@requiere_permisos('Alumnos.add_inscripcion')
def alumno_inscribir(request, pk):
    alumno = get_object_or_404(Alumno, pk=pk)
    form = InscribirForm(request.POST, alumno=alumno)
    if form.is_valid():
        inscripcion = form.save()
        historial.anotar(request.user, alumno, f'Lo inscribió en {inscripcion.grupo.nombre_equivalente} ({inscripcion.ciclo}).')
        messages.success(request, f'{alumno} fue inscrito en {inscripcion.grado} ({inscripcion.ciclo}).')
    else:
        error = next(iter(form.non_field_errors()), None) or next(
            (errores[0] for errores in form.errors.values()), 'Revisa los datos de la inscripción.'
        )
        messages.error(request, f'No se pudo inscribir: {error}')
    return redirect(f'{alumno.get_absolute_url()}#academico')


# ---------------------------------------------------------------------------
# Exportación y búsquedas (JSON)
# ---------------------------------------------------------------------------
def _grado_equivalente(inscripcion):
    """«7.º A»: como se ve en la tabla (y como lo reconoce la importación al volver a subir el archivo)."""
    if inscripcion is None:
        return ''
    return inscripcion.grupo.nombre_equivalente if inscripcion.grupo_id else inscripcion.grado.nombre_equivalente


@require_GET
@requiere_permisos('Alumnos.view_alumno')
def alumno_exportar(request):
    filtro = FiltroAlumnosForm(request.GET, usuario=request.user)
    alumnos = filtro.filtrar(Alumno.objects.all()).prefetch_related(
        prefetch_inscripciones_actuales(), prefetch_vinculos_activos(),
    )
    if request.GET.get('formato') == 'xlsx':
        return _excel_de_estudiantes(request.user, list(alumnos), f'estudiantes-{timezone.localdate():%Y-%m-%d}.xlsx')

    respuesta = HttpResponse(content_type='text/csv; charset=utf-8')
    respuesta['Content-Disposition'] = f'attachment; filename="estudiantes-{timezone.localdate():%Y-%m-%d}.csv"'
    respuesta.write('﻿')  # para que Excel reconozca los acentos
    escritor = csv.writer(respuesta)
    escritor.writerow([
        'Referencia', 'Nombre', 'Apellido paterno', 'Apellido materno', 'CURP', 'Sexo',
        'Fecha de nacimiento', 'Edad', 'Estatus', 'Ciclo', 'Grado', 'Tutor principal', 'Parentesco del tutor',
        'Teléfono del tutor', 'Correo electrónico', 'Domicilio', 'Colonia', 'Ciudad', 'Estado', 'CP',
        'Fecha de ingreso',
    ])
    for alumno in alumnos.iterator(chunk_size=500):
        inscripcion = alumno.inscripciones_actuales[0] if alumno.inscripciones_actuales else None
        vinculo = alumno.vinculos_activos[0] if alumno.vinculos_activos else None
        escritor.writerow([proteger_celda_csv(valor) for valor in [
            alumno.referencia, alumno.nombre, alumno.apellido_paterno, alumno.apellido_materno,
            alumno.curp, alumno.get_sexo_display(), alumno.fecha_nacimiento, alumno.edad,
            alumno.get_estatus_display(),
            inscripcion.ciclo if inscripcion else '', _grado_equivalente(inscripcion),
            vinculo.tutor if vinculo else '', vinculo.get_parentesco_display() if vinculo else '',
            vinculo.tutor.telefono if vinculo else '',
            alumno.correo_electronico or '', alumno.domicilio, alumno.colonia, alumno.ciudad,
            alumno.estado, alumno.cp, alumno.fecha_ingreso,
        ]])
    return respuesta


# ---------------------------------------------------------------------------
# Importación desde CSV
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.add_alumno')
def alumno_importar(request):
    """Registra los estudiantes de un archivo CSV (ver Alumnos/importacion.py).

    Si se registra al menos uno, se vuelve al listado con el resumen (una respuesta con HTML rompería la ventana modal);
    si ninguno se pudo registrar, se queda aquí mostrando por qué.
    """
    resultado = None
    if request.method == 'POST':
        form = ImportarEstudiantesForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                filas = importacion.leer_filas(form.cleaned_data['archivo'].read())
            except importacion.ErrorDeArchivo as error:
                form.add_error('archivo', str(error))
            else:
                resultado = importacion.importar(filas)
                if resultado.creados:
                    request.session[SESION_IMPORTACION] = {
                        'archivo': form.cleaned_data['archivo'].name,
                        'total': resultado.total,
                        'creados': len(resultado.creados),
                        'omitidos': resultado.omitidos,
                        'religiones_como_otra': resultado.religiones_como_otra,
                        'errores': resultado.errores[:importacion.ERRORES_GUARDADOS],
                        'errores_total': resultado.con_error,
                    }
                    request.session[SESION_IMPORTACION_CREDENCIALES] = [
                        [c['referencia'], c['nombre'], c['grado'], c['contrasena']] for c in resultado.creados
                    ]
                    n, malas = len(resultado.creados), resultado.con_error
                    messages.success(request, 'Se importó 1 estudiante.' if n == 1 else f'Se importaron {n} estudiantes.')
                    if malas:
                        messages.warning(request, '1 fila no se importó: revisa el resumen.' if malas == 1 else f'{malas} filas no se importaron: revisa el resumen.')
                    return redirect('alumnos:lista')
                messages.error(request, 'No se importó ningún estudiante.')
    else:
        form = ImportarEstudiantesForm()

    return render(request, 'alumnos/importar.html', {
        'form': form,
        'resultado': resultado,
        'columnas': importacion.COLUMNAS,
        'filas_maximas': importacion.FILAS_MAXIMAS,
        'ciclo_actual': ciclo_activo(),
    })


@require_GET
@requiere_permisos('Alumnos.add_alumno')
def alumno_importar_plantilla(request):
    """El CSV con los encabezados que reconoce la importación."""
    respuesta = HttpResponse(importacion.plantilla_csv(), content_type='text/csv; charset=utf-8')
    respuesta['Content-Disposition'] = 'attachment; filename="plantilla-estudiantes.csv"'
    return respuesta


@require_GET
@requiere_permisos('Alumnos.add_alumno')
def alumno_importar_credenciales(request):
    """Las contraseñas de los estudiantes de la última importación (quien importa no siempre puede consultarlas después)."""
    contrasenas = request.session.get(SESION_IMPORTACION_CREDENCIALES)
    if not contrasenas:
        messages.info(request, 'No hay contraseñas de una importación reciente que descargar.')
        return redirect('alumnos:lista')

    respuesta = HttpResponse(content_type='text/csv; charset=utf-8')
    respuesta['Content-Disposition'] = f'attachment; filename="contrasenas-importadas-{timezone.localdate():%Y-%m-%d}.csv"'
    respuesta.write('﻿')
    escritor = csv.writer(respuesta)
    escritor.writerow(['Referencia', 'Nombre', 'Grado', 'Contraseña'])
    for fila in contrasenas:
        escritor.writerow([proteger_celda_csv(valor) for valor in fila])
    return respuesta


@require_GET
@requiere_permisos('Alumnos.view_alumno')
def alumno_buscar(request):
    """Búsqueda de alumnos para vincularlos desde un tutor (JSON). No incluye las bajas."""
    palabras = request.GET.get('q', '').split()
    if not palabras or sum(len(p) for p in palabras) < 2:
        return JsonResponse({'resultados': []})

    alumnos = Alumno.objects.exclude(estatus='BAJA')
    for palabra in palabras:
        alumnos = alumnos.filter(
            Q(nombre__icontains=palabra)
            | Q(apellido_paterno__icontains=palabra)
            | Q(apellido_materno__icontains=palabra)
            | Q(referencia__icontains=palabra)
            | Q(curp__icontains=palabra)
        )

    resultados = []
    for alumno in alumnos.prefetch_related(prefetch_inscripciones_actuales())[:8]:
        inscripcion = alumno.inscripciones_actuales[0] if alumno.inscripciones_actuales else None
        resultados.append({
            'id': alumno.pk,
            'nombre': str(alumno),
            'iniciales': alumno.iniciales,
            'referencia': alumno.referencia,
            'grado': str(inscripcion.grupo) if inscripcion else '',
            'estatus': alumno.get_estatus_display(),
        })
    return JsonResponse({'resultados': resultados})


@require_GET
@requiere_alguno('Alumnos.add_alumno', 'Alumnos.change_alumno')
def tutor_buscar(request):
    """Búsqueda de tutores existentes para vincularlos desde el asistente (JSON). No incluye las bajas."""
    palabras = request.GET.get('q', '').split()
    if not palabras or sum(len(p) for p in palabras) < 2:
        return JsonResponse({'resultados': []})

    tutores = Tutor.objects.filter(estatus='ACTIVO')
    for palabra in palabras:
        tutores = tutores.filter(
            Q(nombre__icontains=palabra)
            | Q(apellido_paterno__icontains=palabra)
            | Q(apellido_materno__icontains=palabra)
            | Q(telefono__icontains=palabra)
            | Q(curp__icontains=palabra)
        )

    alumnos_vigentes = Prefetch(
        'alumnos_relacionados',
        queryset=(
            TutorAlumno.objects.filter(activo=True).exclude(alumno__estatus='BAJA')
            .select_related('alumno').order_by('alumno__apellido_paterno', 'alumno__nombre')
        ),
        to_attr='vinculos_vigentes',
    )
    resultados = []
    for tutor in tutores.prefetch_related(alumnos_vigentes)[:8]:
        resultados.append({
            'id': tutor.pk,
            'nombre': str(tutor),
            'iniciales': tutor.iniciales,
            'telefono': tutor.telefono,
            'correo': tutor.correo_electronico or '',
            'ocupacion': tutor.ocupacion,
            'alumnos': [str(v.alumno) for v in tutor.vinculos_vigentes[:3]],
        })
    return JsonResponse({'resultados': resultados})


# ---------------------------------------------------------------------------
# Excel con las columnas que se ven (la tabla filtrada o los elegidos en lote)
# ---------------------------------------------------------------------------
def _excel_de_estudiantes(usuario, alumnos, nombre):
    from CISAHUAYO.xlsx import ENCABEZADO, TITULO, Celda, Hoja, libro
    visibles = columnas.elegidas(usuario)
    tabla.preparar_filas(usuario, alumnos, con_asistencia='asistencia_hoy' in visibles)
    columnas.preparar(usuario, alumnos, visibles)

    def fecha(momento):
        return timezone.localtime(momento).replace(tzinfo=None) if momento else None

    encabezados, anchos = ['Referencia', 'Estudiante'], [12, 34]
    por_columna = {
        'grado': (['Nivel', 'Grado'], [14, 10]),
        'asistencia_hoy': (['Asistencia hoy'], [16]),
        'asistencia_ciclo': (['% asistencia del ciclo', 'Faltas', 'Justificadas'], [12, 8, 12]),
        'promedio': (['Promedio'], [10]),
        'conducta': (['Casos de conducta abiertos'], [12]),
        'tutor': (['Tutor principal', 'Parentesco', 'Teléfono'], [30, 14, 14]),
        'edad': (['Edad'], [8]),
        'portal': (['Portal del estudiante', 'Último acceso del estudiante', 'Portal del tutor', 'Último acceso del tutor'], [20, 18, 20, 18]),
        'tarjeta': (['Tarjeta de entrada'], [16]),
        'estatus': (['Estatus'], [12]),
    }
    for clave in visibles:
        encabezados += por_columna[clave][0]
        anchos += por_columna[clave][1]
    filas = [[Celda('Estudiantes', TITULO)], [f'Generado el {timezone.localtime():%d/%m/%Y %H:%M} · {len(alumnos)} estudiantes'], [],
             [Celda(texto, ENCABEZADO) for texto in encabezados]]
    for alumno in alumnos:
        inscripcion = (alumno.inscripciones_actuales or [None])[0]
        vinculo = (alumno.vinculos_activos or [None])[0]
        fila = [alumno.referencia, str(alumno)]
        for clave in visibles:
            if clave == 'grado':
                fila += [inscripcion.grado.get_nivel_display() if inscripcion else '', _grado_equivalente(inscripcion) or 'Sin inscripción']
            elif clave == 'asistencia_hoy':
                fila.append((alumno.asistencia_hoy or {}).get('texto', ''))
            elif clave == 'asistencia_ciclo':
                datos = alumno.asistencia_ciclo or {}
                fila += [datos.get('porcentaje'), datos.get('faltas'), datos.get('justificadas')]
            elif clave == 'promedio':
                fila.append(float(alumno.promedio) if alumno.promedio is not None else None)
            elif clave == 'conducta':
                fila.append(alumno.casos_abiertos)
            elif clave == 'tutor':
                fila += [str(vinculo.tutor) if vinculo else 'Sin tutor', vinculo.get_parentesco_display() if vinculo else '',
                         vinculo.tutor.telefono if vinculo else '']
            elif clave == 'edad':
                fila.append(alumno.edad)
            elif clave == 'portal':
                de_alumno, de_tutor = alumno.portal_alumno, alumno.portal_tutor
                fila += [de_alumno.texto, fecha(de_alumno.ultimo_acceso), de_tutor.texto if de_tutor else 'Sin tutor',
                         fecha(de_tutor.ultimo_acceso) if de_tutor else None]
            elif clave == 'tarjeta':
                fila.append('Asignada' if alumno.uid else 'Sin tarjeta')
            elif clave == 'estatus':
                fila.append(alumno.get_estatus_display())
        filas.append(fila)
    respuesta = HttpResponse(libro([Hoja('Estudiantes', filas, anchos=anchos)]),
                             content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    respuesta['Content-Disposition'] = f'attachment; filename="{nombre}"'
    respuesta['Cache-Control'] = 'private, no-store'
    return respuesta


# ---------------------------------------------------------------------------
# Imprimir la lista (por grupo), con columnas en blanco
# ---------------------------------------------------------------------------
@require_GET
@requiere_permisos('Alumnos.view_alumno')
def alumno_imprimir(request):
    """La lista filtrada en una hoja para imprimir, un grupo por página, con columnas en blanco para el pase de lista o las
    firmas. El título, cuántas columnas y si lleva «Firma» se eligen arriba (no se imprimen)."""
    filtro = FiltroAlumnosForm(request.GET, usuario=request.user)
    alumnos = list(filtro.filtrar(Alumno.objects.all()).prefetch_related(prefetch_inscripciones_actuales()))
    titulo = ' '.join(request.GET.get('titulo', '').split())[:60] or 'Pase de lista'
    try:
        en_blanco = min(max(int(request.GET.get('columnas', 10)), 0), 20)
    except ValueError:
        en_blanco = 10
    con_firma = request.GET.get('firma') == '1'
    grupos = {}
    for alumno in alumnos:
        inscripcion = (alumno.inscripciones_actuales or [None])[0]
        grupos.setdefault(inscripcion.grupo if inscripcion else None, []).append(alumno)

    def orden(par):
        grupo = par[0]
        if grupo is None:
            return (1, 0, 0, '')
        from .models import ORDEN_NIVELES
        nivel = grupo.grado.nivel
        return (0, ORDEN_NIVELES.index(nivel) if nivel in ORDEN_NIVELES else 9, grupo.grado.numero, str(grupo.nombre))

    hojas = []
    for grupo, lista in sorted(grupos.items(), key=orden):
        lista.sort(key=lambda a: (a.apellido_paterno, a.apellido_materno, a.nombre))
        hojas.append({'grupo': grupo, 'alumnos': lista})
    conservar = request.GET.copy()
    for clave in ('titulo', 'columnas', 'firma', 'page', 'por_pagina'):
        conservar.pop(clave, None)
    return render(request, 'alumnos/lista_hoja.html', {
        'hojas': hojas, 'titulo': titulo, 'en_blanco': range(en_blanco), 'numero_en_blanco': en_blanco, 'con_firma': con_firma,
        'ciclo': ciclo_activo(), 'generado': timezone.localtime(), 'conservar': list(conservar.lists()),
        'volver': f"{reverse('alumnos:lista')}?{conservar.urlencode()}" if conservar else reverse('alumnos:lista'),
    })


# ---------------------------------------------------------------------------
# Acciones en lote (Alumnos/lote.py)
# ---------------------------------------------------------------------------
def _elegidos(request):
    ids = [int(pk) for pk in request.POST.getlist('alumnos') if pk.isdigit()][:lote.MAXIMO]
    return list(Alumno.objects.filter(pk__in=ids).prefetch_related(prefetch_inscripciones_actuales(), prefetch_vinculos_activos())
                .order_by('apellido_paterno', 'apellido_materno', 'nombre'))


def _resumen_de_omitidos(omitidos):
    if not omitidos:
        return ''
    muestra = ' '.join(omitidos[:3])
    return f' No se pudo con {len(omitidos)}: {muestra}' + (' …' if len(omitidos) > 3 else '')


@require_POST
@requiere_permisos('Alumnos.view_alumno')
def alumno_lote(request):
    from django.core.exceptions import PermissionDenied
    volver = destino_seguro(request, reverse('alumnos:lista'))
    accion = request.POST.get('accion', '')
    permitidas = _acciones_en_lote(request.user)
    if accion not in ('grupo', 'estatus', 'contrasenas', 'exportar', 'comunicado'):
        messages.error(request, 'Elige una acción.')
        return redirect(volver)
    if not permitidas[accion]:
        raise PermissionDenied
    alumnos = _elegidos(request)
    if not alumnos:
        messages.error(request, 'Elige al menos a un estudiante en la tabla.')
        return redirect(volver)

    if accion == 'grupo':
        form = LoteGrupoForm(request.POST)
        if not form.is_valid():
            errores = [e for lista in form.errors.values() for e in lista]
            messages.error(request, f'No se cambió a nadie: {" ".join(errores)}')
            return redirect(volver)
        datos = form.cleaned_data
        hechos, omitidos = lote.inscribir_o_cambiar(alumnos, ciclo=datos['ciclo'], grado=datos['grado'], grupo=datos['grupo'], usuario=request.user)
        texto = f'{len(hechos)} estudiante{"s" if len(hechos) != 1 else ""} en {datos["grupo"].nombre_equivalente} ({datos["ciclo"]}).'
        (messages.success if hechos else messages.warning)(request, texto + _resumen_de_omitidos(omitidos))
    elif accion == 'estatus':
        form = LoteEstatusForm(request.POST)
        if not form.is_valid():
            messages.error(request, 'Elige el nuevo estatus.')
            return redirect(volver)
        cambiados, sin_cambio = lote.cambiar_estatus(alumnos, estatus=form.cleaned_data['estatus'], usuario=request.user)
        nombre = dict(Alumno.ESTATUS_CHOICES)[form.cleaned_data['estatus']]
        messages.success(request, f'{len(cambiados)} estudiante{"s" if len(cambiados) != 1 else ""} ahora en «{nombre}».'
                                  + (f' {len(sin_cambio)} ya lo estaba{"n" if len(sin_cambio) != 1 else ""}.' if sin_cambio else ''))
    elif accion == 'contrasenas':
        filas = lote.generar_contrasenas(alumnos, usuario=request.user)
        request.session[SESION_LOTE_CREDENCIALES] = filas
        messages.success(request, f'Se generaron {len(filas)} contraseñas nuevas. Descárgalas ahora: solo se guardan mientras dure tu sesión.')
    elif accion == 'exportar':
        return _excel_de_estudiantes(request.user, alumnos, f'estudiantes-elegidos-{timezone.localdate():%Y-%m-%d}.xlsx')
    elif accion == 'comunicado':
        tutores = lote.tutores_de(alumnos)
        if not tutores:
            messages.error(request, 'Los estudiantes elegidos no tienen tutores activos.')
            return redirect(volver)
        request.session[SESION_COMUNICADO] = tutores
        return redirect(f"{reverse('comunicados:crear')}?desde=estudiantes")
    return redirect(volver)


@require_GET
@requiere_permisos('Alumnos.change_alumno')
def alumno_lote_credenciales(request):
    """Las contraseñas generadas en lote (en esta sesión), en CSV."""
    filas = request.session.get(SESION_LOTE_CREDENCIALES)
    if not filas:
        messages.info(request, 'No hay contraseñas generadas recientemente que descargar.')
        return redirect('alumnos:lista')
    respuesta = HttpResponse(content_type='text/csv; charset=utf-8')
    respuesta['Content-Disposition'] = f'attachment; filename="contrasenas-{timezone.localdate():%Y-%m-%d}.csv"'
    respuesta['Cache-Control'] = 'private, no-store'
    respuesta.write('\ufeff')
    escritor = csv.writer(respuesta)
    escritor.writerow(['Referencia', 'Nombre', 'Grado', 'Correo (con el que entra)', 'Contraseña'])
    for fila in filas:
        escritor.writerow([proteger_celda_csv(valor) for valor in fila])
    return respuesta
