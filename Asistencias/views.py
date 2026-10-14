import csv
import logging
from collections import defaultdict
from datetime import date, timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.views.decorators.http import require_GET, require_POST

from Alumnos.academico import elegir_ciclo
from Alumnos.asistencias import (
    EntradaRechazada,
    asistencia_editable,
    aviso_de_niveles_sin_clases,
    buscar_alumno,
    cerrar_dia,
    cerrar_dias_pendientes,
    ciclo_de_fecha,
    cierre_automatico_del_dia,
    con_justificada_general,
    con_justificada_materia,
    conteos,
    dias_de_clases,
    dias_pendientes_de_cierre,
    fijar_asistencia_general,
    inscripciones_del_dia,
    motivo_sin_clases,
    porcentaje,
    alumnos_suspendidos,
    registrar_entrada,
    sin_dias_suspendidos,
    suspensiones_del_dia,
    resumen_del_dia,
    texto_de_niveles,
)
from Alumnos.models import (
    Alumno,
    AsistenciaGeneral,
    CambioJustificacion,
    AsistenciaMateria,
    CicloEscolar,
    CierreDia,
    ConfiguracionAsistencia,
    DiaNoLectivo,
    Inscripcion,
    Justificacion,
    MateriaGrado,
    orden_de_nivel,
)
from Alumnos.utils import proteger_celda_csv
from CISAHUAYO.paginacion import OPCIONES_POR_PAGINA, POR_PAGINA_DEFECTO, paginar
from CISAHUAYO.permisos import requiere_alguno, requiere_permisos
from CISAHUAYO.redireccion import destino_seguro
from Conducta.permisos import puede_configurar

from .forms import (
    UMBRAL_ASISTENCIA,
    AsistenciaDiaForm,
    ConfiguracionForm,
    DiaNoLectivoForm,
    FiltroDiaForm,
    FiltroJustificacionesForm,
    FiltroReporteForm,
    JustificacionEdicionForm,
    JustificacionForm,
)

logger = logging.getLogger(__name__)

DIAS_MAXIMOS_CUADRICULA = 31
ESTADO_TEXTO = {'PRESENTE': 'Presente', 'RETARDO': 'Con retardo', 'FALTA': 'Falta'}
ESTADOS_EN_ORDEN = [('PRESENTE', 'Presente'), ('RETARDO', 'Retardo'), ('FALTA', 'Falta')]


# ---------------------------------------------------------------------------
# Ayudantes
# ---------------------------------------------------------------------------
def _fecha(valor, defecto):
    try:
        return date.fromisoformat(valor) if valor else defecto
    except ValueError:
        return defecto


def _dia_habil_anterior(fecha):
    fecha -= timedelta(days=1)
    while fecha.weekday() >= 5:
        fecha -= timedelta(days=1)
    return fecha


def _dia_habil_siguiente(fecha, hoy):
    fecha += timedelta(days=1)
    while fecha.weekday() >= 5:
        fecha += timedelta(days=1)
    return fecha if fecha <= hoy else None


def _navegacion_de_fecha(fecha, hoy):
    return {'fecha': fecha, 'hoy': hoy, 'es_hoy': fecha == hoy, 'anterior': _dia_habil_anterior(fecha), 'siguiente': _dia_habil_siguiente(fecha, hoy)}


def _texto_de_fecha(fecha):
    return date_format(fecha, 'j \\d\\e F \\d\\e Y').lower()


def _plural(cantidad, singular, plural=None):
    return f'{cantidad} {singular if cantidad == 1 else (plural or singular + "s")}'


def _orden_de_alumnos(prefijo=''):
    return [f'{prefijo}alumno__apellido_paterno', f'{prefijo}alumno__apellido_materno', f'{prefijo}alumno__nombre']


# ---------------------------------------------------------------------------
# Resumen del día
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.view_asistenciageneral')
def inicio(request):
    hoy = timezone.localdate()
    fecha = min(_fecha(request.GET.get('fecha'), hoy), hoy)
    ciclo = ciclo_de_fecha(fecha)
    motivo = motivo_sin_clases(fecha, ciclo)
    resumen = resumen_del_dia(fecha, ciclo) if ciclo and not motivo else None
    total = resumen['total'] if resumen else None
    puede_cerrar_dias = request.user.has_perm('Alumnos.add_cierredia')

    return render(request, 'asistencias/inicio.html', {
        **_navegacion_de_fecha(fecha, hoy),
        'seccion': 'inicio',
        'ciclo': ciclo,
        'motivo': motivo,
        'aviso_niveles': aviso_de_niveles_sin_clases(fecha) if ciclo and not motivo else None,
        'resumen': resumen,
        'total': total,
        'porcentaje_entrada': round(100 * total['entraron'] / total['inscritos']) if total and total['inscritos'] else 0,
        'sin_entradas': bool(total and total['inscritos'] and not (total['entraron'] or total['faltas'])),
        'cierre': CierreDia.objects.filter(fecha=fecha).first(),
        'puede_cerrar': bool(ciclo and not motivo and puede_cerrar_dias and asistencia_editable(fecha)),
        'pendientes': dias_pendientes_de_cierre(hoy) if puede_cerrar_dias else [],
    })


@require_POST
@requiere_permisos('Alumnos.add_cierredia')
def cerrar(request):
    """Cierra un día (o todos los pendientes): genera las faltas de quien no registró entrada."""
    hoy = timezone.localdate()
    if request.POST.get('alcance') == 'pendientes':
        cerrados = cerrar_dias_pendientes(usuario=request.user)
        if cerrados:
            faltas = sum(f for _, f in cerrados)
            messages.success(request, f'Se cerraron {_plural(len(cerrados), "día")}: {_plural(faltas, "falta")} generada{"s" if faltas != 1 else ""}.')
        else:
            messages.info(request, 'No había días pendientes por cerrar.')
        return redirect('asistencias:inicio')

    fecha = _fecha(request.POST.get('fecha'), None)
    if fecha is None or fecha > hoy:
        messages.error(request, 'Elige un día que ya haya empezado.')
        return redirect('asistencias:inicio')
    destino = f"{reverse('asistencias:inicio')}?fecha={fecha:%Y-%m-%d}"
    if not asistencia_editable(fecha):
        messages.error(request, 'Solo se cierran los días del ciclo actual.')
        return redirect(destino)
    faltas = cerrar_dia(fecha, usuario=request.user)
    if faltas is None:
        messages.error(request, motivo_sin_clases(fecha) or 'Ese día no se puede cerrar.')
    else:
        messages.success(request, f'Se cerró el {_texto_de_fecha(fecha)}: {_plural(faltas, "falta")} generada{"s" if faltas != 1 else ""}.')
    return redirect(destino)


# ---------------------------------------------------------------------------
# Pantalla de entrada (kiosco)
# ---------------------------------------------------------------------------
def _foto(alumno):
    try:
        return alumno.fotografia.url if alumno.fotografia else ''
    except ValueError:
        return ''


def _datos_alumno(alumno, grado=''):
    return {
        'id': alumno.pk, 'nombre': str(alumno), 'iniciales': alumno.iniciales, 'grado': str(grado) if grado else '',
        'foto': _foto(alumno), 'tono': alumno.pk % 6 + 1,
    }


def _estado_del_kiosco(fecha):
    """Cuántos han entrado y la hora del servidor, para la pantalla de la entrada.

    Solo cifras: la pantalla la ven los alumnos que esperan su turno, así que nunca lleva nombres de quienes ya
    entraron (el único nombre que se muestra es el de quien acaba de escanear, en su propio resultado).
    """
    ciclo = ciclo_de_fecha(fecha)
    inscripciones = inscripciones_del_dia(fecha, ciclo).exclude(alumno__in=alumnos_suspendidos(fecha))   # los suspendidos no entran
    ahora = timezone.localtime()
    return {
        'fecha': fecha.isoformat(),
        # Hora del servidor (segundos desde la medianoche): la pantalla muestra esta y no la del equipo, para que
        # coincida con la que decide los retardos aunque el reloj del equipo esté mal.
        'ahora': ahora.hour * 3600 + ahora.minute * 60 + ahora.second,
        'inscritos': inscripciones.count() if ciclo else 0,
        'entraron': AsistenciaGeneral.objects.filter(
            fecha=fecha, estado__in=('PRESENTE', 'RETARDO'), inscripcion__in=inscripciones,
        ).count(),
    }


@requiere_permisos('Alumnos.add_asistenciageneral')
def kiosco(request):
    hoy = timezone.localdate()
    return render(request, 'asistencias/kiosco.html', {
        'hoy': hoy,
        'motivo': motivo_sin_clases(hoy, exigir_actual=True),
        'aviso_niveles': aviso_de_niveles_sin_clases(hoy),
        'estado': _estado_del_kiosco(hoy),
        'configuracion': ConfiguracionAsistencia.cargar(),
    })


def _sin_acceso(request):
    """Respuesta JSON cuando la pantalla de la entrada ya no tiene sesión o permiso (no se redirige al login)."""
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'tipo': 'SESION', 'mensaje': 'Tu sesión terminó. Inicia sesión de nuevo en esta pantalla.'}, status=401)
    if not request.user.has_perm('Alumnos.add_asistenciageneral'):
        return JsonResponse({'ok': False, 'tipo': 'PERMISO', 'mensaje': 'Esta cuenta no puede registrar entradas.'}, status=403)
    return None


@require_POST
def entrada_registrar(request):
    """Registra la entrada de quien escaneó su credencial o escribió su referencia (JSON para la pantalla)."""
    sin_acceso = _sin_acceso(request)
    if sin_acceso:
        return sin_acceso

    alumno = None
    try:
        alumno, origen = buscar_alumno(request.POST.get('codigo'), request.POST.get('modo'))
        resultado = registrar_entrada(alumno, origen, usuario=request.user)
    except EntradaRechazada as rechazo:
        carga = {'ok': False, 'tipo': rechazo.codigo, 'mensaje': rechazo.mensaje}
        if alumno:
            carga['alumno'] = _datos_alumno(alumno)
        return JsonResponse(carga)

    asistencia = resultado.asistencia
    nombre = alumno.nombre.split()[0] if alumno.nombre.split() else alumno.nombre
    hora = f'{asistencia.hora_entrada:%H:%M}' if asistencia.hora_entrada else ''
    carga = {
        'ok': True, 'estado': asistencia.estado, 'hora': hora, 'materias': resultado.materias,
        'alumno': _datos_alumno(alumno, asistencia.inscripcion.grupo),
    }
    if resultado.creada:
        carga.update(tipo='REGISTRADA', mensaje=f'Entrada registrada con retardo, {nombre}.' if asistencia.estado == 'RETARDO' else f'¡Bienvenido, {nombre}!')
        try:  # la primera entrada del día cierra los días anteriores; un fallo ahí nunca debe impedir esta entrada
            cierre_automatico_del_dia()
        except Exception:
            logger.exception('No se pudo cerrar automáticamente los días anteriores')
    elif asistencia.estado == 'FALTA':
        carga.update(ok=False, tipo='CON_FALTA', mensaje='Hoy tienes una falta registrada. Acude a dirección.')
    else:
        carga.update(tipo='YA_REGISTRADA', mensaje=f'Ya registraste tu entrada hoy{f" a las {hora}" if hora else ""}.')
    carga['resumen'] = _estado_del_kiosco(timezone.localdate())
    return JsonResponse(carga)


@require_GET
def kiosco_estado(request):
    sin_acceso = _sin_acceso(request)
    if sin_acceso:
        return sin_acceso
    return JsonResponse({'ok': True, **_estado_del_kiosco(timezone.localdate())})


# ---------------------------------------------------------------------------
# Asistencia general del día (quien administra)
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.view_asistenciageneral')
def dia(request):
    hoy = timezone.localdate()
    fecha = min(_fecha(request.GET.get('fecha'), hoy), hoy)
    ciclo = ciclo_de_fecha(fecha)
    motivo = motivo_sin_clases(fecha, ciclo)
    filtro = FiltroDiaForm(request.GET)
    datos = filtro.activos

    pagina = rango_paginas = por_pagina = None
    total = None
    if ciclo and not motivo:
        inscripciones = inscripciones_del_dia(fecha, ciclo).select_related('alumno', 'grado', 'grupo__nombre', 'grupo__grado')
        for palabra in datos.get('q', '').split():
            inscripciones = inscripciones.filter(
                Q(alumno__nombre__icontains=palabra) | Q(alumno__apellido_paterno__icontains=palabra)
                | Q(alumno__apellido_materno__icontains=palabra) | Q(alumno__referencia__icontains=palabra)
            )
        if datos.get('grado'):
            inscripciones = inscripciones.filter(grado=datos['grado'])
        estado = datos.get('estado')
        suspendidos = alumnos_suspendidos(fecha)   # con suspensión autorizada: no cuentan como faltas ni como sin entrada
        if estado == 'SUSPENDIDO':
            inscripciones = inscripciones.filter(alumno__in=suspendidos)
        elif estado == 'SIN_REGISTRO':
            inscripciones = inscripciones.exclude(asistencias_generales__fecha=fecha).exclude(alumno__in=suspendidos)
        elif estado:
            inscripciones = inscripciones.filter(asistencias_generales__fecha=fecha, asistencias_generales__estado=estado).exclude(alumno__in=suspendidos)
        inscripciones = inscripciones.order_by(orden_de_nivel('grado__nivel'), 'grado__numero', *_orden_de_alumnos())

        pagina, rango_paginas, por_pagina = paginar(request, inscripciones)
        ids = [inscripcion.pk for inscripcion in pagina]
        generales = {g.inscripcion_id: g for g in con_justificada_general(AsistenciaGeneral.objects.filter(fecha=fecha, inscripcion__in=ids))}
        materias = {
            fila['inscripcion_id']: fila
            for fila in AsistenciaMateria.objects.filter(fecha=fecha, inscripcion__in=ids).order_by().values('inscripcion_id').annotate(
                total=Count('pk'), asistidas=Count('pk', filter=Q(estado__in=('PRESENTE', 'RETARDO'))), faltas=Count('pk', filter=Q(estado='FALTA')),
            )
        }
        suspensiones = suspensiones_del_dia(fecha, [inscripcion.alumno_id for inscripcion in pagina])
        for inscripcion in pagina:
            inscripcion.general = generales.get(inscripcion.pk)
            inscripcion.materias = materias.get(inscripcion.pk)
            inscripcion.suspension = suspensiones.get(inscripcion.alumno_id)
        resumen = resumen_del_dia(fecha, ciclo)
        total = resumen['total']
        if datos.get('grado'):
            total = next((fila for fila in resumen['grados'] if fila['grado'] == datos['grado']), total)

    return render(request, 'asistencias/dia.html', {
        **_navegacion_de_fecha(fecha, hoy),
        'seccion': 'dia',
        'ciclo': ciclo,
        'motivo': motivo,
        'aviso_niveles': aviso_de_niveles_sin_clases(fecha) if ciclo and not motivo else None,
        'filtro': filtro,
        'filtros_activos': datos,
        'pagina': pagina,
        'rango_paginas': rango_paginas,
        'por_pagina': por_pagina,
        'por_pagina_defecto': POR_PAGINA_DEFECTO,
        'opciones_por_pagina': OPCIONES_POR_PAGINA,
        'total': total,
        'editable': bool(ciclo and not motivo and asistencia_editable(fecha)),
        'estados': ESTADOS_EN_ORDEN,
    })


@require_POST
@requiere_permisos('Alumnos.change_asistenciageneral')
def dia_guardar(request):
    """Captura o corrige la asistencia general de un alumno en un día."""
    destino = destino_seguro(request, reverse('asistencias:dia'))
    form = AsistenciaDiaForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'No se guardó: ' + ' '.join(error for errores in form.errors.values() for error in errores))
        return redirect(destino)
    datos = form.cleaned_data
    fecha = datos['fecha']
    motivo = motivo_sin_clases(fecha, exigir_actual=True)
    if motivo or not asistencia_editable(fecha):
        messages.error(request, motivo or 'Solo se captura asistencia de los días del ciclo actual que ya empezaron.')
        return redirect(destino)
    inscripcion = inscripciones_del_dia(fecha).filter(pk=datos['inscripcion']).select_related('alumno', 'grado', 'grupo__nombre', 'grupo__grado', 'ciclo').first()
    if inscripcion is None:
        messages.error(request, 'Ese estudiante no tiene una inscripción vigente en ese día.')
        return redirect(destino)
    if not AsistenciaGeneral.objects.filter(inscripcion=inscripcion, fecha=fecha).exists() and not request.user.has_perm('Alumnos.add_asistenciageneral'):
        raise PermissionDenied

    hora = datos['hora']
    if datos['estado'] != 'FALTA' and hora is None and fecha == timezone.localdate():
        hora = timezone.localtime().time()          # una entrada capturada hoy sin hora se registra a la hora actual
    fijar_asistencia_general(
        inscripcion, fecha, datos['estado'], hora=hora, observaciones=datos['observaciones'],
        usuario=request.user, propagar=datos['propagar'],
    )
    messages.success(request, f'Se guardó la asistencia de {inscripcion.alumno}: {ESTADO_TEXTO[datos["estado"]].lower()}.')
    return redirect(destino)


# ---------------------------------------------------------------------------
# Justificaciones
# ---------------------------------------------------------------------------
def _alcance_texto(justificacion):
    partes = []
    if justificacion.justifica_general:
        partes.append('Falta general')
    if justificacion.todas_materias:
        partes.append('Todas las materias')
    else:
        materias = list(justificacion.materias.all())
        if materias:
            partes.append(_plural(len(materias), 'materia'))
    return partes


@requiere_permisos('Alumnos.view_justificacion')
def justificaciones(request):
    filtro = FiltroJustificacionesForm(request.GET)
    datos = filtro.activos
    base = Justificacion.objects.select_related('inscripcion__alumno', 'inscripcion__grado', 'inscripcion__grupo__nombre', 'inscripcion__grupo__grado', 'inscripcion__ciclo', 'registrada_por').prefetch_related('materias__materia')
    lista = filtro.filtrar(base).order_by('-fecha', '-creado')
    pagina, rango_paginas, por_pagina = paginar(request, lista)
    conteo = filtro.filtrar(Justificacion.objects.all(), con_estado=False).aggregate(
        vigentes=Count('pk', filter=Q(activa=True)), anuladas=Count('pk', filter=Q(activa=False)),
    )
    for justificacion in pagina:
        justificacion.alcance = _alcance_texto(justificacion)
    return render(request, 'asistencias/justificaciones.html', {
        'seccion': 'justificaciones',
        'filtro': filtro,
        'filtros_activos': {k: v for k, v in datos.items() if k != 'estado'},
        'viendo_anuladas': datos.get('estado') == 'ANULADA',
        'conteo': conteo,
        'pagina': pagina,
        'rango_paginas': rango_paginas,
        'por_pagina': por_pagina,
        'por_pagina_defecto': POR_PAGINA_DEFECTO,
        'opciones_por_pagina': OPCIONES_POR_PAGINA,
    })


def _guardar_alcance(justificacion, datos):
    """Aplica a la justificación lo que se eligió en el formulario (falta general, todas las materias o algunas)."""
    modo = datos['materias_modo']
    justificacion.justifica_general = bool(datos['justifica_general'])
    justificacion.todas_materias = modo == 'TODAS'
    justificacion.motivo = datos['motivo']


@requiere_permisos('Alumnos.add_justificacion')
def justificacion_crear(request):
    if request.method == 'POST':
        form = JustificacionForm(request.POST, request.FILES)
        if form.is_valid():
            datos = form.cleaned_data
            inscripcion = datos['inscripcion']
            with transaction.atomic():
                primera = None
                for fecha in datos['fechas']:
                    justificacion = Justificacion(inscripcion=inscripcion, fecha=fecha, registrada_por=request.user)
                    _guardar_alcance(justificacion, datos)
                    if primera is None:
                        justificacion.documento = datos['documento'] or None
                    elif primera.documento:
                        justificacion.documento = primera.documento.name         # el mismo comprobante sirve para todos los días
                    justificacion.save()
                    if datos['materias_modo'] == 'ALGUNAS':
                        justificacion.materias.set(datos['materias'])
                    primera = primera or justificacion
            cantidad = len(datos['fechas'])
            if cantidad == 1:
                texto = f'Se registró la justificación de {inscripcion.alumno} para el {_texto_de_fecha(datos["fechas"][0])}.'
            else:
                texto = f'Se registraron {cantidad} justificaciones de {inscripcion.alumno} ({_texto_de_fecha(datos["fechas"][0])} al {_texto_de_fecha(datos["fechas"][-1])}).'
            if datos['omitidas']:
                texto += f' {_plural(len(datos["omitidas"]), "día")} ya tenía{"n" if len(datos["omitidas"]) != 1 else ""} una justificación vigente y no se tocó.'
            messages.success(request, texto)
            return redirect('asistencias:justificaciones')
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
        alumno_id = request.POST.get('alumno')
    else:
        inicial = {'justifica_general': True, 'materias_modo': 'TODAS'}
        alumno_id = request.GET.get('alumno', '')
        if alumno_id.isdigit():
            inicial['alumno'] = int(alumno_id)
        inicial['fecha_desde'] = min(_fecha(request.GET.get('fecha'), timezone.localdate()), timezone.localdate())
        form = JustificacionForm(initial=inicial)

    alumno = Alumno.objects.filter(pk=alumno_id).first() if str(alumno_id).isdigit() else None
    return render(request, 'asistencias/justificacion_form.html', {
        'seccion': 'justificaciones',
        'form': form,
        'alumno': alumno,
        'inscripcion': form.inscripcion_previa,
        'es_edicion': False,
        'url_alumnos': reverse('alumnos:buscar'),
        'url_materias': reverse('asistencias:justificacion_materias'),
    })


@require_GET
@requiere_permisos('Alumnos.add_justificacion')
def justificacion_materias(request):
    """Las materias del grado de un alumno (JSON), para elegir cuáles se justifican."""
    fecha = _fecha(request.GET.get('fecha'), timezone.localdate())
    inscripcion = JustificacionForm._inscripcion_de(request.GET.get('alumno'), fecha.isoformat())
    if inscripcion is None:
        return JsonResponse({'grado': '', 'materias': []})
    materias = (
        MateriaGrado.objects.filter(ciclo=inscripcion.ciclo, grupo=inscripcion.grupo, activa=True, materia__activa=True)
        .select_related('materia').order_by('materia__nombre')
    )
    return JsonResponse({
        'grado': str(inscripcion.grupo),
        'materias': [{'id': m.pk, 'nombre': m.materia.nombre, 'clave': m.materia.clave} for m in materias],
    })


@requiere_permisos('Alumnos.change_justificacion')
def justificacion_editar(request, pk):
    justificacion = get_object_or_404(Justificacion.objects.select_related('inscripcion__alumno', 'inscripcion__grado', 'inscripcion__grupo__nombre', 'inscripcion__grupo__grado', 'inscripcion__ciclo'), pk=pk)
    if not justificacion.activa:
        messages.info(request, 'Esa justificación está anulada. Reactívala si quieres modificarla.')
        return redirect('asistencias:justificaciones')
    if not justificacion.inscripcion.ciclo.activo:
        messages.error(request, f'El ciclo {justificacion.inscripcion.ciclo} no es el ciclo actual: sus justificaciones ya no se modifican.')
        return redirect('asistencias:justificaciones')

    if request.method == 'POST':
        form = JustificacionEdicionForm(request.POST, request.FILES, justificacion=justificacion)
        if form.is_valid():
            datos = form.cleaned_data
            _guardar_alcance(justificacion, datos)
            if datos['documento']:
                justificacion.documento = datos['documento']
            elif datos['quitar_documento']:
                justificacion.documento = None
            with transaction.atomic():
                justificacion.save()
                justificacion.materias.set(datos['materias'] if datos['materias_modo'] == 'ALGUNAS' else [])
            messages.success(request, f'Se actualizó la justificación de {justificacion.inscripcion.alumno} del {_texto_de_fecha(justificacion.fecha)}.')
            return redirect('asistencias:justificaciones')
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    else:
        form = JustificacionEdicionForm(justificacion=justificacion)

    return render(request, 'asistencias/justificacion_form.html', {
        'seccion': 'justificaciones',
        'form': form,
        'alumno': justificacion.inscripcion.alumno,
        'inscripcion': justificacion.inscripcion,
        'justificacion': justificacion,
        'es_edicion': True,
    })


@require_POST
@requiere_permisos('Alumnos.delete_justificacion')
def justificacion_anular(request, pk):
    """Anular es lógico: la justificación deja de cubrir faltas pero se conserva como historial."""
    justificacion = get_object_or_404(Justificacion.objects.select_related('inscripcion__alumno', 'inscripcion__ciclo'), pk=pk)
    if not justificacion.inscripcion.ciclo.activo:
        messages.error(request, f'El ciclo {justificacion.inscripcion.ciclo} no es el ciclo actual: sus justificaciones ya no se modifican.')
    elif justificacion.activa:
        justificacion.activa, justificacion.revocada_por, justificacion.revocada_en = False, request.user, timezone.now()
        justificacion.save(update_fields=['activa', 'revocada_por', 'revocada_en', 'modificado'])
        CambioJustificacion.objects.create(justificacion=justificacion, accion=CambioJustificacion.REVOCADA, usuario=request.user,
                                           motivo='Anulada desde Justificaciones.')
        messages.success(request, f'Se anuló la justificación de {justificacion.inscripcion.alumno} del {_texto_de_fecha(justificacion.fecha)}. Sus faltas vuelven a contar sin justificar.')
    return redirect(destino_seguro(request, reverse('asistencias:justificaciones')))


@require_POST
@requiere_permisos('Alumnos.change_justificacion')
def justificacion_reactivar(request, pk):
    justificacion = get_object_or_404(Justificacion.objects.select_related('inscripcion__alumno', 'inscripcion__ciclo'), pk=pk)
    if not justificacion.inscripcion.ciclo.activo:
        messages.error(request, f'El ciclo {justificacion.inscripcion.ciclo} no es el ciclo actual: sus justificaciones ya no se modifican.')
    elif not justificacion.activa:
        # Una por día entre las de Justificaciones; las hechas desde una falta, una por falta
        vigentes = Justificacion.objects.filter(activa=True)
        if justificacion.asistencia_id:
            otra = vigentes.filter(asistencia=justificacion.asistencia_id).exists()
        else:
            otra = vigentes.filter(inscripcion=justificacion.inscripcion, fecha=justificacion.fecha, asistencia__isnull=True).exists()
        if otra:
            messages.error(request, f'{"Esa falta" if justificacion.asistencia_id else "Ese día"} ya tiene otra justificación vigente: no se puede reactivar esta.')
        else:
            justificacion.activa = True
            justificacion.save(update_fields=['activa', 'modificado'])
            CambioJustificacion.objects.create(justificacion=justificacion, accion=CambioJustificacion.REACTIVADA, usuario=request.user)
            messages.success(request, f'Se reactivó la justificación de {justificacion.inscripcion.alumno} del {_texto_de_fecha(justificacion.fecha)}.')
    return redirect(destino_seguro(request, reverse('asistencias:justificaciones')))


@require_GET
@requiere_alguno('Alumnos.view_justificacion', 'Prefectura.consultar')
def comprobante(request, pk):
    """El comprobante de una justificación, solo para quien puede verla: quien consulta las justificaciones o, en
    prefectura, si el estudiante está en su alcance. Nunca se muestra la dirección del archivo en el almacenamiento."""
    from Conducta.views import entregar_archivo
    from Prefectura.alcance import alcance_de

    justificaciones = Justificacion.objects.exclude(documento='').exclude(documento__isnull=True)
    if not request.user.has_perm('Alumnos.view_justificacion'):
        justificaciones = alcance_de(request.user).filtrar(justificaciones, campo='inscripcion__alumno')
    justificacion = get_object_or_404(justificaciones, pk=pk)
    tipo, extension = _tipo_de_comprobante(justificacion.documento)
    return entregar_archivo(justificacion.documento, f'comprobante-{justificacion.pk}.{extension}', tipo,
                            descargar=request.GET.get('descargar') == '1')


_FIRMAS = ((b'\xff\xd8\xff', 'image/jpeg', 'jpg'), (b'\x89PNG', 'image/png', 'png'), (b'%PDF-', 'application/pdf', 'pdf'))
_POR_EXTENSION = {'jpg': ('image/jpeg', 'jpg'), 'jpeg': ('image/jpeg', 'jpg'), 'png': ('image/png', 'png'),
                  'webp': ('image/webp', 'webp'), 'pdf': ('application/pdf', 'pdf')}


def _tipo_de_comprobante(documento):
    """(tipo, extensión) del comprobante: por su extensión o, si no la tiene (Cloudinary guarda los archivos sin ella),
    por sus primeros bytes. Así una foto se ve en el navegador en lugar de descargarse como un archivo desconocido."""
    nombre = documento.name.rsplit('/', 1)[-1]
    extension = nombre.rsplit('.', 1)[-1].lower() if '.' in nombre else ''
    if extension in _POR_EXTENSION:
        return _POR_EXTENSION[extension]
    try:
        documento.open('rb')
        cabecera = documento.read(16)
        documento.seek(0)
    except Exception:
        return 'application/octet-stream', 'bin'
    for firma, tipo, propia in _FIRMAS:
        if cabecera.startswith(firma):
            return tipo, propia
    if cabecera[:4] == b'RIFF' and cabecera[8:12] == b'WEBP':
        return 'image/webp', 'webp'
    return 'application/octet-stream', 'bin'


# ---------------------------------------------------------------------------
# Reportes
# ---------------------------------------------------------------------------
def _datos_del_reporte(filtro):
    """Todo lo que muestran el reporte y su exportación, según los filtros."""
    ciclo, grado, asignacion, desde, hasta, vista = filtro.resolver()
    hoy = timezone.localdate()
    datos = {
        'ciclo': ciclo, 'grado': grado, 'asignacion': asignacion, 'desde': desde, 'hasta': hasta, 'vista': vista,
        'filas': [], 'total': None, 'dias': [], 'cuadricula_posible': True, 'materias': [],
    }
    if not (ciclo and grado):
        return datos

    datos['materias'] = list(
        MateriaGrado.objects.filter(ciclo=ciclo, grado=grado, activa=True).select_related('materia').order_by('materia__nombre')
    )
    inscripciones = list(
        Inscripcion.objects.filter(ciclo=ciclo, grado=grado, activa=True).exclude(alumno__estatus='BAJA')
        .select_related('alumno').order_by(*_orden_de_alumnos())
    )
    if asignacion:
        registros = con_justificada_materia(sin_dias_suspendidos(AsistenciaMateria.objects.filter(materia_grado=asignacion, fecha__range=(desde, hasta), inscripcion__in=inscripciones)))
    else:
        registros = con_justificada_general(sin_dias_suspendidos(AsistenciaGeneral.objects.filter(fecha__range=(desde, hasta), inscripcion__in=inscripciones)))

    cuenta = {
        fila['inscripcion_id']: fila
        for fila in registros.order_by().values('inscripcion_id').annotate(
            registros=Count('pk'), presentes=Count('pk', filter=Q(estado='PRESENTE')), retardos=Count('pk', filter=Q(estado='RETARDO')),
            faltas=Count('pk', filter=Q(estado='FALTA')), justificadas=Count('pk', filter=Q(estado='FALTA', justificada=True)),
        )
    }
    total = dict.fromkeys(('registros', 'presentes', 'retardos', 'faltas', 'justificadas'), 0)
    for inscripcion in inscripciones:
        fila = cuenta.get(inscripcion.pk, {})
        inscripcion.cuenta = {clave: fila.get(clave, 0) for clave in total}
        inscripcion.porcentaje = porcentaje(inscripcion.cuenta['presentes'], inscripcion.cuenta['retardos'], inscripcion.cuenta['registros'])
        inscripcion.sin_justificar = inscripcion.cuenta['faltas'] - inscripcion.cuenta['justificadas']
        inscripcion.bajo_umbral = inscripcion.porcentaje is not None and inscripcion.porcentaje < UMBRAL_ASISTENCIA
        for clave in total:
            total[clave] += inscripcion.cuenta[clave]
    total['porcentaje'] = porcentaje(total['presentes'], total['retardos'], total['registros'])
    datos.update(filas=inscripciones, total=total)

    if vista == 'cuadricula':
        dias = dias_de_clases(desde, min(hasta, hoy), ciclo, grado.nivel)
        if len(dias) > DIAS_MAXIMOS_CUADRICULA:
            datos['cuadricula_posible'] = False
        else:
            celdas = {(r.inscripcion_id, r.fecha): ('J' if r.estado == 'FALTA' and r.justificada else {'PRESENTE': 'A', 'RETARDO': 'R', 'FALTA': 'F'}[r.estado]) for r in registros}
            datos['dias'] = dias
            for inscripcion in inscripciones:
                inscripcion.celdas = [celdas.get((inscripcion.pk, dia), '') for dia in dias]
    return datos


@requiere_permisos('Alumnos.view_asistenciageneral')
def reporte(request):
    filtro = FiltroReporteForm(request.GET)
    datos = _datos_del_reporte(filtro)
    return render(request, 'asistencias/reporte.html', {
        'seccion': 'reporte',
        'filtro': filtro,
        'ciclos': CicloEscolar.objects.all(),
        'umbral': UMBRAL_ASISTENCIA,
        'consulta': request.GET.urlencode(),
        **datos,
    })


@require_GET
@requiere_permisos('Alumnos.view_asistenciageneral')
def reporte_exportar(request):
    filtro = FiltroReporteForm(request.GET)
    datos = _datos_del_reporte(filtro)
    if not (datos['ciclo'] and datos['grado']):
        messages.error(request, 'Elige un grado para exportar su reporte.')
        return redirect('asistencias:reporte')

    nombre = f'asistencia-{datos["grado"].nivel.lower()}-{datos["grado"].numero}-{datos["desde"]:%Y%m%d}-{datos["hasta"]:%Y%m%d}.csv'
    respuesta = HttpResponse(content_type='text/csv; charset=utf-8')
    respuesta['Content-Disposition'] = f'attachment; filename="{nombre}"'
    respuesta.write('﻿')  # para que Excel reconozca los acentos
    escritor = csv.writer(respuesta)
    materia = f' · {datos["asignacion"].materia}' if datos['asignacion'] else ' · asistencia general'
    escritor.writerow([f'{datos["grado"]} · {datos["ciclo"]}{materia} · del {datos["desde"]:%d/%m/%Y} al {datos["hasta"]:%d/%m/%Y}'])
    if datos['vista'] == 'cuadricula' and datos['cuadricula_posible']:
        escritor.writerow(['Estudiante', 'Referencia', *[f'{dia:%d/%m}' for dia in datos['dias']]])
        for inscripcion in datos['filas']:
            escritor.writerow([proteger_celda_csv(str(inscripcion.alumno)), proteger_celda_csv(inscripcion.alumno.referencia), *inscripcion.celdas])
        escritor.writerow(['A = asistió, R = retardo, F = falta, J = falta justificada'])
    else:
        escritor.writerow(['Estudiante', 'Referencia', 'Días registrados', 'Presentes', 'Retardos', 'Faltas', 'Faltas justificadas', 'Asistencia (%)'])
        for inscripcion in datos['filas']:
            cuenta = inscripcion.cuenta
            escritor.writerow([
                proteger_celda_csv(str(inscripcion.alumno)), proteger_celda_csv(inscripcion.alumno.referencia),
                cuenta['registros'], cuenta['presentes'], cuenta['retardos'], cuenta['faltas'], cuenta['justificadas'],
                '' if inscripcion.porcentaje is None else inscripcion.porcentaje,
            ])
    return respuesta


# ---------------------------------------------------------------------------
# Historial de un alumno
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.view_asistenciageneral')
def alumno(request, pk):
    alumno = get_object_or_404(Alumno, pk=pk)
    ciclos = list(CicloEscolar.objects.filter(inscripciones__alumno=alumno).distinct())
    ciclo = elegir_ciclo(request.GET.get('ciclo', ''), ciclos)
    inscripcion = Inscripcion.objects.filter(alumno=alumno, ciclo=ciclo).select_related('grado', 'grupo__nombre', 'grupo__grado', 'ciclo').first() if ciclo else None

    contexto = {
        'seccion': 'reporte', 'alumno': alumno, 'ciclos': ciclos, 'ciclo': ciclo, 'inscripcion': inscripcion,
        'resumen': None, 'pagina': None, 'por_materia': [],
    }
    if inscripcion:
        generales = con_justificada_general(sin_dias_suspendidos(AsistenciaGeneral.objects.filter(inscripcion=inscripcion))).order_by('-fecha')
        resumen = conteos(generales)
        resumen['porcentaje'] = porcentaje(resumen['presentes'], resumen['retardos'], resumen['registros'])
        resumen['sin_justificar'] = resumen['faltas'] - resumen['justificadas']
        pagina, rango_paginas, por_pagina = paginar(request, generales)

        del_dia = defaultdict(list)
        for registro in con_justificada_materia(
            AsistenciaMateria.objects.filter(inscripcion=inscripcion, fecha__in=[g.fecha for g in pagina])
        ).select_related('materia_grado__materia').order_by('materia_grado__materia__nombre'):
            del_dia[registro.fecha].append(registro)
        for general in pagina:
            general.materias = del_dia.get(general.fecha, [])

        por_materia = []
        filas = (
            con_justificada_materia(sin_dias_suspendidos(AsistenciaMateria.objects.filter(inscripcion=inscripcion))).order_by().values('materia_grado__materia__nombre', 'materia_grado__materia__clave')
            .annotate(
                registros=Count('pk'), presentes=Count('pk', filter=Q(estado='PRESENTE')), retardos=Count('pk', filter=Q(estado='RETARDO')),
                faltas=Count('pk', filter=Q(estado='FALTA')), justificadas=Count('pk', filter=Q(estado='FALTA', justificada=True)),
            ).order_by('materia_grado__materia__nombre')
        )
        for fila in filas:
            fila['nombre'], fila['clave'] = fila['materia_grado__materia__nombre'], fila['materia_grado__materia__clave']
            fila['porcentaje'] = porcentaje(fila['presentes'], fila['retardos'], fila['registros'])
            por_materia.append(fila)
        contexto.update(
            resumen=resumen, pagina=pagina, rango_paginas=rango_paginas, por_pagina=por_pagina, por_materia=por_materia,
            por_pagina_defecto=POR_PAGINA_DEFECTO, opciones_por_pagina=OPCIONES_POR_PAGINA, umbral=UMBRAL_ASISTENCIA,
        )
    return render(request, 'asistencias/alumno.html', contexto)


# ---------------------------------------------------------------------------
# Ajustes › Asistencia (en Ajustes, menú Sistema): reglas de la entrada y días sin clases
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.view_configuracionasistencia')
def ajustes(request):
    configuracion = ConfiguracionAsistencia.cargar()
    if request.method == 'POST':
        if not request.user.has_perm('Alumnos.change_configuracionasistencia'):
            raise PermissionDenied
        form = ConfiguracionForm(request.POST, instance=configuracion)
        if form.is_valid():
            form.save()
            messages.success(request, 'Se guardaron las reglas de la entrada.')
            return redirect('asistencias:ajustes')
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    else:
        form = ConfiguracionForm(instance=configuracion)

    hoy = timezone.localdate()
    return render(request, 'asistencias/ajustes.html', {
        'ajustes_seccion': 'asistencia', 'puede_configurar_conducta': puede_configurar(request.user),
        'form': form,
        'cierres': CierreDia.objects.select_related('cerrado_por')[:8],
        'hoy': hoy,
    })


def URL_DIAS_SIN_CLASES():   # noqa: N802 (la tarjeta está en Ciclos escolares desde el 2026-10-14)
    return f"{reverse('ciclos:lista')}#dias-sin-clases"


@require_POST
@requiere_permisos('Alumnos.add_dianolectivo')
def dia_sin_clases_crear(request):
    form = DiaNoLectivoForm(request.POST)
    if form.is_valid():
        datos = form.cleaned_data
        fechas = datos['fechas']
        DiaNoLectivo.objects.bulk_create([DiaNoLectivo(fecha=fecha, nivel=nivel, motivo=datos['motivo']) for fecha, nivel in datos['nuevos']])
        messages.success(request, f'Se registr{"ó" if len(fechas) == 1 else "aron"} {_plural(len(fechas), "día")} sin clases '
                                  f'para {texto_de_niveles(datos["niveles"])}: {datos["motivo"]}.')
    else:
        messages.error(request, 'No se registró: ' + ' '.join(error for errores in form.errors.values() for error in errores))
    return redirect(URL_DIAS_SIN_CLASES())


@require_POST
@requiere_permisos('Alumnos.delete_dianolectivo')
def dia_sin_clases_eliminar(request, pk):
    """Quita el día sin clases tal como se registró (esa fecha y ese motivo, con todos sus niveles). Es borrado físico a
    propósito: es configuración del calendario, nada depende de él."""
    dia = get_object_or_404(DiaNoLectivo, pk=pk)
    registros = DiaNoLectivo.objects.filter(fecha=dia.fecha, motivo=dia.motivo)
    niveles = list(registros.values_list('nivel', flat=True))
    registros.delete()
    messages.success(request, f'Se quitó el día sin clases del {_texto_de_fecha(dia.fecha)} ({texto_de_niveles(niveles)}).')
    return redirect(URL_DIAS_SIN_CLASES())
