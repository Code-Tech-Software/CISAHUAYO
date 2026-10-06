import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from CISAHUAYO.paginacion import OPCIONES_POR_PAGINA, POR_PAGINA_DEFECTO, paginar
from CISAHUAYO.permisos import requiere_alguno, requiere_permisos

from .academico import prefetch_inscripciones_actuales
from .asistencias import con_justificada_general
from .forms import (
    AlumnoForm,
    FiltroAlumnosForm,
    InscribirForm,
    InscripcionInicialForm,
    TutoresFormSet,
    ciclo_activo,
    guardar_vinculos,
    iniciales_vinculos,
)
from .models import Alumno, AsistenciaGeneral, Tutor, TutorAlumno
from .utils import ESTADOS_MX, generar_contrasena, proteger_celda_csv
from .vinculos import prefetch_vinculos_activos

SESION_CREDENCIALES = 'credenciales_alumno'

PASOS_FORMULARIO = (
    {'clave': 'identidad', 'titulo': 'Identidad', 'icono': 'user'},
    {'clave': 'domicilio', 'titulo': 'Domicilio y salud', 'icono': 'map-pin'},
    {'clave': 'escolar', 'titulo': 'Datos escolares', 'icono': 'graduation-cap'},
    {'clave': 'tutores', 'titulo': 'Tutores', 'icono': 'users'},
    {'clave': 'revision', 'titulo': 'Revisión', 'icono': 'clipboard-check'},
)


@login_required
def inicio(request):
    """Panel de control: cualquier cuenta con sesión; cada quien ve solo los accesos a lo que su rol permite.

    Si la cuenta es de un profesor, ve además sus clases del día (con acceso directo al pase de lista).
    """
    return render(request, 'index.html', {'mis_clases': _mis_clases_de_hoy(request.user)})


def _mis_clases_de_hoy(usuario):
    """Las clases de hoy del profesor de la cuenta, o None si la cuenta no es de un profesor activo."""
    from Alumnos.asistencias import ciclo_de_fecha, clases_por_grado, motivo_sin_clases
    from Usuarios.docentes import profesor_de

    profesor = profesor_de(usuario)
    if profesor is None or profesor.estatus != 'ACTIVO':
        return None
    ahora = timezone.localtime()
    hoy = ahora.date()
    ciclo = ciclo_de_fecha(hoy)
    motivo = motivo_sin_clases(hoy, ciclo)
    clases = []
    if ciclo and not motivo:
        clases = sorted(
            (clase for lista in clases_por_grado(ciclo, hoy, materia_grado__profesor=profesor).values() for clase in lista),
            key=lambda clase: (clase.inicio, clase.asignacion.grado.nivel, clase.asignacion.grado.numero),
        )
    hora = ahora.time()
    filas = [{'clase': clase, 'en_curso': clase.inicio <= hora < clase.fin, 'terminada': clase.fin <= hora} for clase in clases]
    return {'profesor': profesor, 'clases': filas, 'motivo': motivo, 'ciclo': ciclo}


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

    if request.method == 'POST':
        form = AlumnoForm(request.POST, request.FILES, instance=alumno)
        tutores = TutoresFormSet(request.POST, prefix='tutores')

        if all([form.is_valid(), tutores.is_valid()]):
            try:
                with transaction.atomic():
                    form.save()
                    guardar_vinculos(alumno, tutores)
            except IntegrityError:
                form.add_error(None, 'No se pudo guardar: algún dato único ya pertenece a otro registro.')
            else:
                messages.success(request, f'Los datos de {alumno} se actualizaron.')
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
        alumno.estatus = estatus
        alumno.save(update_fields=['estatus'])
        messages.success(request, f'{alumno} ahora está en estatus «{alumno.get_estatus_display()}».')
    return redirect(alumno)


@require_POST
@requiere_permisos('Alumnos.delete_alumno')
def alumno_baja(request, pk):
    """Baja lógica: el alumno deja de aparecer en el listado, pero nada se borra."""
    alumno = get_object_or_404(Alumno, pk=pk)
    if alumno.estatus == 'BAJA':
        messages.info(request, f'{alumno} ya estaba dado de baja.')
    else:
        alumno.estatus = 'BAJA'
        alumno.save(update_fields=['estatus'])
        messages.success(request, f'{alumno} fue dado de baja. Su historial se conserva y puedes reactivarlo desde el filtro «Bajas».')
    return redirect('alumnos:lista')


@require_POST
@requiere_permisos('Alumnos.change_alumno')
def alumno_reactivar(request, pk):
    alumno = get_object_or_404(Alumno, pk=pk)
    if alumno.estatus == 'BAJA':
        alumno.estatus = 'ACTIVO'
        alumno.save(update_fields=['estatus'])
        messages.success(request, f'{alumno} fue reactivado.')
    return redirect('alumnos:lista')


@require_POST
@requiere_permisos('Alumnos.change_alumno')
def alumno_contrasena(request, pk):
    alumno = get_object_or_404(Alumno, pk=pk)
    nueva = generar_contrasena()
    alumno.contrasena = make_password(nueva)
    alumno.save(update_fields=['contrasena'])
    request.session[SESION_CREDENCIALES] = {
        'pk': alumno.pk,
        'nombre': str(alumno),
        'url': alumno.get_absolute_url(),
        'referencia': alumno.referencia,
        'contrasena': nueva,
    }
    messages.success(request, f'Se generó una nueva contraseña para {alumno}.')
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
