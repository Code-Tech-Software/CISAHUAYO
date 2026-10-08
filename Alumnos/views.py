import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from CISAHUAYO.paginacion import OPCIONES_POR_PAGINA, POR_PAGINA_DEFECTO, paginar
from CISAHUAYO.permisos import requiere_alguno, requiere_permisos

from . import importacion
from .academico import prefetch_inscripciones_actuales, sincronizar_inscripciones
from .asistencias import con_justificada_general
from .forms import (
    AlumnoForm,
    FiltroAlumnosForm,
    ImportarEstudiantesForm,
    InscribirForm,
    InscripcionInicialForm,
    RestablecerContrasenaForm,
    TutoresFormSet,
    ciclo_activo,
    guardar_vinculos,
    iniciales_vinculos,
)
from .models import Alumno, AsistenciaGeneral, Tutor, TutorAlumno
from .utils import ESTADOS_MX, generar_contrasena, proteger_celda_csv
from .vinculos import prefetch_vinculos_activos

SESION_CREDENCIALES = 'credenciales_alumno'
SESION_IMPORTACION = 'importacion_estudiantes'                  # el resumen de la última importación (se muestra una vez)
SESION_IMPORTACION_CREDENCIALES = 'importacion_credenciales'    # sus contraseñas, para descargarlas

PASOS_FORMULARIO = (
    {'clave': 'identidad', 'titulo': 'Identidad', 'icono': 'user'},
    {'clave': 'domicilio', 'titulo': 'Domicilio y salud', 'icono': 'map-pin'},
    {'clave': 'escolar', 'titulo': 'Datos escolares', 'icono': 'graduation-cap'},
    {'clave': 'tutores', 'titulo': 'Tutores', 'icono': 'users'},
    {'clave': 'revision', 'titulo': 'Revisión', 'icono': 'clipboard-check'},
)


@login_required
def inicio(request):
    """Panel de control: cualquier cuenta con sesión; cada quien ve solo los accesos a lo que su rol permite."""
    return render(request, 'index.html')


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.view_alumno')
def alumno_lista(request):
    filtro = FiltroAlumnosForm(request.GET)
    alumnos = filtro.filtrar(Alumno.objects.all()).prefetch_related(
        prefetch_inscripciones_actuales(), prefetch_vinculos_activos(),
    )
    pagina, rango_paginas, por_pagina = paginar(request, alumnos)

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
        'ciclo_actual': ciclo_activo(),
        # Tras registrar a un alumno se muestran, una sola vez, sus credenciales de acceso
        'credenciales': request.session.pop(SESION_CREDENCIALES, None),
        # Y, tras importar un archivo, el resumen de lo que pasó con cada fila
        'importacion': request.session.pop(SESION_IMPORTACION, None),
    })


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
                request.session[SESION_CREDENCIALES] = {
                    'pk': alumno.pk,
                    'nombre': str(alumno),
                    'url': alumno.get_absolute_url(),
                    'referencia': alumno.referencia,
                    'contrasena': form.contrasena_en_claro,
                }
                detalle = f' e inscrito en {inscrito.grado}' if inscrito else ''
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
            try:
                with transaction.atomic():
                    form.save()
                    guardar_vinculos(alumno, tutores)
                    suspendidas, restauradas = sincronizar_inscripciones(alumno, estatus_anterior)
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
    inscripciones = list(alumno.inscripciones.select_related('grado', 'ciclo').order_by('-ciclo__fecha_inicio', '-fecha_inscripcion'))
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
        'esta_de_baja': alumno.estatus == 'BAJA',
        'inscribir_form': InscribirForm(alumno=alumno),
        # La baja tiene su propia acción: el menú ofrece solo los demás estatus
        'estatus_opciones': [(v, e) for v, e in Alumno.ESTATUS_CHOICES if v != 'BAJA'],
    })


# ---------------------------------------------------------------------------
# Acciones sobre un alumno
# ---------------------------------------------------------------------------
def _texto_de_inscripciones(suspendidas, restauradas):
    """« Su inscripción en 2° Primaria (2026-2027) quedó desactivada.» (o reactivada; vacío si no había)."""
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
        messages.success(request, f'{alumno} ahora está en estatus «{alumno.get_estatus_display()}».'
                                  f'{_texto_de_inscripciones(suspendidas, restauradas)}')
    return redirect(alumno)


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
    alumno.save(update_fields=['contrasena', 'contrasena_visible'])
    request.session[SESION_CREDENCIALES] = {
        'pk': alumno.pk,
        'nombre': str(alumno),
        'url': alumno.get_absolute_url(),
        'referencia': alumno.referencia,
        'contrasena': nueva,
    }
    messages.success(request, f'Se asignó una nueva contraseña a {alumno}.')
    return redirect(alumno)


@require_POST
@requiere_permisos('Alumnos.add_inscripcion')
def alumno_inscribir(request, pk):
    alumno = get_object_or_404(Alumno, pk=pk)
    form = InscribirForm(request.POST, alumno=alumno)
    if form.is_valid():
        inscripcion = form.save()
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
@require_GET
@requiere_permisos('Alumnos.view_alumno')
def alumno_exportar(request):
    filtro = FiltroAlumnosForm(request.GET)
    alumnos = filtro.filtrar(Alumno.objects.all()).prefetch_related(
        prefetch_inscripciones_actuales(), prefetch_vinculos_activos(),
    )

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
            inscripcion.ciclo if inscripcion else '', inscripcion.grado if inscripcion else '',
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
            'grado': str(inscripcion.grado) if inscripcion else '',
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
