"""Gestión académica › Calificaciones: elegir materia (de un grupo) y periodo, y trabajar en sus pestañas —Resumen,
Procedimientos, Exámenes y Concentrado—; agregar actividades, guardar capturas, cerrar, reabrir y exportar.

Un docente solo abre sus materias y quien tiene «ver o gestionar todas», todas las del colegio; lo que no se puede
abrir responde 403 aunque se teclee la dirección. Toda captura se valida otra vez en el servidor (Calificaciones/reglas.py).
"""
import json

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from Alumnos.academico import ciclo_actual
from Alumnos.models import Grado
from CISAHUAYO.permisos import requiere_alguno
from CISAHUAYO.xlsx import ENCABEZADO, SECCION, TITULO, Celda, Hoja, libro
from Usuarios.docentes import profesor_de

from . import reglas
from .forms import TIPOS_DE_ACTIVIDAD, ActividadForm, MotivoForm
from .models import ActaCalificaciones, Actividad, Rubro

PESTANAS = (('resumen', 'Resumen de calificaciones'), ('procedimientos', 'Procedimientos'), ('examenes', 'Exámenes'), ('concentrado', 'Concentrado'))


# ---------------------------------------------------------------------------
# Lo que se puede abrir
# ---------------------------------------------------------------------------
def _acta_visible(request, pk):
    """El acta si la persona puede ver su materia; si no, 403 (no se dice si existe)."""
    acta = get_object_or_404(ActaCalificaciones.objects.select_related(
        'asignacion__materia', 'asignacion__ciclo', 'asignacion__grado', 'asignacion__grupo__nombre', 'asignacion__grupo__grado',
        'asignacion__profesor', 'periodo'), pk=pk)
    if not reglas.puede_ver(request.user, acta.asignacion):
        raise PermissionDenied
    return acta


def url_del_acta(acta, pestana='resumen'):
    consulta = {'ciclo': acta.asignacion.ciclo_id, 'materia': acta.asignacion_id, 'periodo': acta.periodo_id}
    if pestana != 'resumen':
        consulta['pestana'] = pestana
    return f"{reverse('calificaciones:inicio')}?{urlencode(consulta)}"


def _elegir(lista, pedido):
    return next((x for x in lista if str(x.pk) == str(pedido)), None) if pedido else None


# ---------------------------------------------------------------------------
# La página
# ---------------------------------------------------------------------------
@requiere_alguno(*reglas.ENTRAR)
def inicio(request):
    usuario = request.user
    ciclos = reglas.ciclos_con_materias(usuario)
    actual = ciclo_actual()
    ciclo = _elegir(ciclos, request.GET.get('ciclo')) or (actual if actual in ciclos else (ciclos[0] if ciclos else None))
    asignaciones = list(reglas.asignaciones_para(usuario, ciclo)) if ciclo else []
    contexto = {
        'ciclos': ciclos, 'ciclo': ciclo, 'asignaciones': asignaciones, 've_todas': reglas.ve_todas(usuario),
        'profesor': profesor_de(usuario), 'pestanas': PESTANAS,
    }
    elegida = request.GET.get('materia', '')
    if not asignaciones:
        if elegida:
            raise PermissionDenied   # una materia pedida que no puede abrir (aunque no tenga ninguna)
        return render(request, 'calificaciones/inicio.html', contexto)

    if elegida:
        asignacion = _elegir(asignaciones, elegida)
        if asignacion is None:
            raise PermissionDenied
    else:
        grupo = request.GET.get('grupo', '')
        asignacion = next((a for a in asignaciones if str(a.grupo_id) == grupo), asignaciones[0])
    grupos = list({a.grupo_id: a.grupo for a in asignaciones}.values())
    periodos = reglas.periodos_de(asignacion)
    periodo = _elegir(periodos, request.GET.get('periodo')) or reglas.periodo_sugerido(periodos)
    pestana = request.GET.get('pestana', 'resumen')
    if pestana not in dict(PESTANAS):
        pestana = 'resumen'
    contexto.update({
        'asignacion': asignacion, 'grupos': grupos, 'materias_del_grupo': [a for a in asignaciones if a.grupo_id == asignacion.grupo_id],
        'periodos': periodos, 'periodo': periodo, 'pestana': pestana,
    })
    if periodo is None:
        return render(request, 'calificaciones/inicio.html', contexto)

    acta = reglas.acta_para(asignacion, periodo)
    tabla = reglas.tabla(acta)
    motivo = reglas.motivo_de_solo_lectura(acta, usuario, tabla.configuracion)
    puede_cerrar = reglas.puede_cerrar(usuario, asignacion) and not acta.cerrada
    contexto.update({
        'acta': acta, 'tabla': tabla, 'editable': not motivo, 'solo_lectura': motivo,
        'puede_cerrar': puede_cerrar, 'puede_reabrir': acta.cerrada and reglas.puede_reabrir(usuario, asignacion),
        'problemas_para_cerrar': reglas.problemas_para_cerrar(acta, tabla) if puede_cerrar else [],
        'columnas': columnas_del_resumen(tabla),
        'url_guardar': reverse('calificaciones:guardar', args=[acta.pk]),
        'configurar': usuario.has_perm(reglas.VER_CONFIG),
        # Debajo de la tabla de captura, si el acta se ha reabierto alguna vez
        'movimientos': reglas.historial_de_movimientos(acta) if pestana != 'concentrado' else None,
    })
    editable = not motivo
    if pestana in TIPOS_DE_ACTIVIDAD:
        tipo = TIPOS_DE_ACTIVIDAD[pestana]
        actividades = tabla.actividades_de(tipo)
        rubros = tabla.rubros_de(Rubro.PROCEDIMIENTOS if tipo == Actividad.PROCEDIMIENTO else Rubro.EXAMENES)
        contexto.update({
            'tipo_actividad': tipo, 'es_procedimiento': tipo == Actividad.PROCEDIMIENTO, 'actividades': actividades, 'rubros_de_la_pestana': rubros,
            'varios_rubros': len({a.rubro_id for a in actividades} | {r.pk for r in rubros}) > 1,
            'filas': [celdas_de_actividades(tabla, f, actividades, rubros, editable) for f in tabla.filas],
            'puede_agregar': editable and bool(reglas.rubros_para_actividades(acta, tipo)),
        })
    elif pestana == 'resumen':
        contexto['filas'] = [celdas_del_resumen(tabla, f, editable) for f in tabla.filas]
    if pestana == 'concentrado':
        contexto['concentrado'] = concentrado(tabla, usuario)
    return render(request, 'calificaciones/inicio.html', contexto)


def columnas_del_resumen(tabla):
    """Las columnas de los rubros en el resumen: [{'rubro', 'directo', 'titulo'}]."""
    return [{'rubro': r, 'directo': r.tipo == Rubro.DIRECTA, 'titulo': f'{r.nombre} {reglas.numero(r.porcentaje)} %'} for r in tabla.rubros]


def calculados(tabla, fila):
    """Lo que se calcula de un estudiante, como texto (lo mismo dibuja la página y responde el guardado)."""
    r = fila.resultado
    datos = {}
    for rubro in tabla.rubros:
        x = r.rubros.get(str(rubro.pk))
        datos[f'valor-{rubro.pk}'] = reglas.dos_decimales(x.valor) if x and x.valor is not None else ''
        datos[f'aportacion-{rubro.pk}'] = reglas.dos_decimales(x.aportacion) if x and x.aportacion is not None else ''
    datos['faltas'] = str(r.faltas)
    datos['descuento'] = f'−{reglas.numero(r.descuento)}' if r.descuento else ''
    datos['final'] = reglas.dos_decimales(r.final) if r.final is not None else ''
    if fila.estado == reglas.CERRADO:
        estado = 'Cerrado'
    elif fila.estado == reglas.SIN_CALIFICAR:
        estado = 'Sin calificar'
    elif r.final is None:
        estado = 'Falta algún rubro'
    elif r.pendientes:
        estado = f'Provisional · {r.pendientes} pendiente{"s" if r.pendientes != 1 else ""}'
    else:
        estado = 'En captura'
    datos['estado'] = estado
    datos['estado_clave'] = 'cerrado' if fila.estado == reglas.CERRADO else ('sin' if fila.estado == reglas.SIN_CALIFICAR else
                                                                             ('incompleto' if r.final is None else ('provisional' if r.pendientes else 'completo')))
    datos['tope'] = r.tope
    return datos


def _entrada(tipo, id_, fila, valor, editable, etiqueta, anulada=False):
    return {'entrada': True, 'tipo': tipo, 'id': id_, 'inscripcion': fila.inscripcion.pk, 'valor': valor,
            'clave': f'{tipo}-{id_}-{fila.inscripcion.pk}', 'editable': editable and not anulada, 'anulada': anulada,
            'etiqueta': f'{etiqueta} de {fila.nombre}'}


def _calculada(nombre, calc, clase=''):
    return {'calc': nombre, 'valor': calc.get(nombre, ''), 'clase': clase}


def celdas_del_resumen(tabla, fila, editable):
    """La fila del resumen: rubros directos para capturar y lo calculado de cada rubro, faltas, academia y final."""
    fila.calc = calc = calculados(tabla, fila)
    celdas = []
    for rubro in tabla.rubros:
        if rubro.tipo == Rubro.DIRECTA:
            celdas.append(_entrada('rubro', rubro.pk, fila, reglas.numero(fila.directas.get(rubro.pk)), editable, rubro.nombre))
        else:
            celdas.append(_calculada(f'valor-{rubro.pk}', calc))
        celdas.append(_calculada(f'aportacion-{rubro.pk}', calc, 'cal-aportacion'))
    # Faltas y, debajo, lo que descuentan (una sola columna)
    if tabla.faltas_manuales:
        valor = '' if fila.faltas_manuales is None else str(fila.faltas_manuales)
        celdas.append({**_entrada('faltas', 'manual', fila, valor, editable, 'Faltas'), 'faltas': True, 'descuento': calc['descuento']})
    else:
        celdas.append({'faltas_calculadas': True, 'faltas': calc['faltas'], 'descuento': calc['descuento']})
    if tabla.con_academia:
        celdas.append({**_entrada('academia', 'punto', fila, '1' if fila.academia else '0', editable, 'Punto de academia'), 'casilla': True,
                       'marcada': fila.academia})
    fila.celdas = celdas
    return fila


def celdas_de_actividades(tabla, fila, actividades, rubros, editable):
    """La fila de procedimientos o de exámenes: una celda por actividad y el promedio de cada rubro de la pestaña."""
    fila.calc = calc = calculados(tabla, fila)
    fila.celdas = [_entrada('actividad', a.pk, fila, reglas.numero(fila.actividades.get(a.pk)), editable, a.nombre, a.anulada) for a in actividades]
    fila.promedios = [_calculada(f'valor-{r.pk}', calc, 'cal-promedio') for r in rubros]
    return fila


# ---------------------------------------------------------------------------
# Guardar capturas (JSON)
# ---------------------------------------------------------------------------
@require_POST
@requiere_alguno(reglas.CAPTURAR, reglas.GESTIONAR_TODAS)
def guardar(request, pk):
    acta = _acta_visible(request, pk)
    if not reglas.puede_capturar(request.user, acta.asignacion):
        return JsonResponse({'ok': False, 'mensaje': 'Solo consulta: no capturas las calificaciones de esta materia.'}, status=403)
    try:
        datos = json.loads(request.body or b'{}')
        cambios = datos.get('cambios')
        if not isinstance(cambios, list) or not all(isinstance(c, dict) for c in cambios):
            raise ValueError
    except (ValueError, json.JSONDecodeError):
        return JsonResponse({'ok': False, 'mensaje': 'No se entendió lo que se envió. Recarga la página.'}, status=400)
    try:
        resultados, tabla = reglas.guardar_capturas(acta, request.user, cambios)
    except reglas.CapturaRechazada as error:
        return JsonResponse({'ok': False, 'mensaje': error.mensaje}, status=409)   # cerrada, periodo cerrado, sin configuración…
    filas = {str(f.inscripcion.pk): calculados(tabla, f) for f in tabla.filas}
    errores = sum(1 for r in resultados if not r['ok'])
    return JsonResponse({'ok': not errores, 'resultados': resultados, 'filas': filas})


# ---------------------------------------------------------------------------
# Actividades
# ---------------------------------------------------------------------------
def _exigir_captura(request, acta):
    motivo = reglas.motivo_de_solo_lectura(acta, request.user)
    if motivo:
        if not reglas.puede_capturar(request.user, acta.asignacion):
            raise PermissionDenied
        messages.error(request, motivo)
        return False
    return True


@requiere_alguno(reglas.CAPTURAR, reglas.GESTIONAR_TODAS)
def actividad_crear(request, pk):
    acta = _acta_visible(request, pk)
    pestana = request.GET.get('pestana') or request.POST.get('pestana') or 'procedimientos'
    if pestana not in TIPOS_DE_ACTIVIDAD:
        raise Http404
    tipo = TIPOS_DE_ACTIVIDAD[pestana]
    if not _exigir_captura(request, acta):
        return redirect(url_del_acta(acta, pestana))
    if not reglas.rubros_para_actividades(acta, tipo):
        messages.error(request, 'La configuración de la materia no tiene un rubro activo para este tipo de actividad.')
        return redirect(url_del_acta(acta, pestana))
    form = ActividadForm(request.POST if request.method == 'POST' else None, acta=acta, tipo=tipo)
    if request.method == 'POST':
        if form.is_valid():
            actividad = reglas.crear_actividad(acta, form.cleaned_data, request.user)
            messages.success(request, f'Se agregó «{actividad.nombre}». Ya puedes capturar sus calificaciones.')
            return redirect(url_del_acta(acta, pestana))
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return render(request, 'calificaciones/actividad_form.html', {
        'form': form, 'acta': acta, 'pestana': pestana, 'tipo': tipo, 'volver': url_del_acta(acta, pestana),
        'titulo': 'Nuevo procedimiento' if tipo == Actividad.PROCEDIMIENTO else 'Nuevo examen',
    })


def _actividad_visible(request, pk):
    actividad = get_object_or_404(Actividad.objects.select_related('acta', 'rubro'), pk=pk)
    acta = _acta_visible(request, actividad.acta_id)
    return actividad, acta


def _pestana_de(actividad):
    return 'procedimientos' if actividad.tipo == Actividad.PROCEDIMIENTO else 'examenes'


@requiere_alguno(reglas.CAPTURAR, reglas.GESTIONAR_TODAS)
def actividad_editar(request, pk):
    actividad, acta = _actividad_visible(request, pk)
    pestana = _pestana_de(actividad)
    if not _exigir_captura(request, acta):
        return redirect(url_del_acta(acta, pestana))
    form = ActividadForm(request.POST if request.method == 'POST' else None, acta=acta, tipo=actividad.tipo, actividad=actividad)
    if request.method == 'POST':
        if form.is_valid():
            try:
                reglas.editar_actividad(actividad, form.cleaned_data, request.user)
            except reglas.CapturaRechazada as error:
                form.add_error('rubro', error.mensaje)
            else:
                messages.success(request, f'Se guardó «{actividad.nombre}».')
                return redirect(url_del_acta(acta, pestana))
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return render(request, 'calificaciones/actividad_form.html', {
        'form': form, 'acta': acta, 'actividad': actividad, 'pestana': pestana, 'tipo': actividad.tipo,
        'volver': url_del_acta(acta, pestana), 'titulo': f'Editar «{actividad.nombre}»',
    })


@requiere_alguno(reglas.CAPTURAR, reglas.GESTIONAR_TODAS)
def actividad_quitar(request, pk):
    """Sin calificaciones se elimina; con calificaciones se anula con motivo (deja de contar en el promedio)."""
    actividad, acta = _actividad_visible(request, pk)
    pestana = _pestana_de(actividad)
    if not _exigir_captura(request, acta):
        return redirect(url_del_acta(acta, pestana))
    if actividad.anulada:
        messages.info(request, f'«{actividad.nombre}» ya está anulada.')
        return redirect(url_del_acta(acta, pestana))
    calificadas = actividad.calificaciones.count()
    form = MotivoForm(request.POST if request.method == 'POST' and calificadas else None)
    if request.method == 'POST':
        if not calificadas:
            reglas.eliminar_actividad(actividad, request.user)
            messages.success(request, f'Se eliminó «{actividad.nombre}» (no tenía calificaciones).')
            return redirect(url_del_acta(acta, pestana))
        if form.is_valid():
            reglas.anular_actividad(actividad, form.cleaned_data['motivo'], request.user)
            messages.success(request, f'Se anuló «{actividad.nombre}»: sus {calificadas} calificaciones ya no cuentan en el promedio.')
            return redirect(url_del_acta(acta, pestana))
        messages.error(request, 'Escribe el motivo de la anulación.')
    return render(request, 'calificaciones/actividad_quitar.html', {
        'actividad': actividad, 'acta': acta, 'form': form, 'calificadas': calificadas, 'volver': url_del_acta(acta, pestana),
    })


# ---------------------------------------------------------------------------
# Cierre, reapertura e historial
# ---------------------------------------------------------------------------
@requiere_alguno(reglas.CERRAR)
def cerrar(request, pk):
    acta = _acta_visible(request, pk)
    if not reglas.puede_cerrar(request.user, acta.asignacion):
        raise PermissionDenied
    tabla = reglas.tabla(acta)
    problemas = reglas.problemas_para_cerrar(acta, tabla)
    if request.method == 'POST':
        try:
            reglas.cerrar(acta, request.user)
        except reglas.CapturaRechazada as error:
            messages.error(request, f'No se cerró: {error.mensaje}')
        else:
            messages.success(request, f'Se cerraron las calificaciones de {acta.asignacion.materia} · {acta.asignacion.grupo} · {acta.periodo.nombre}. '
                                      'Se guardaron la configuración y los resultados usados.')
        return redirect(url_del_acta(acta))
    return render(request, 'calificaciones/cerrar.html', {
        'acta': acta, 'problemas': problemas, 'volver': url_del_acta(acta), 'estudiantes': len(tabla.filas),
    })


@requiere_alguno(reglas.REABRIR)
def reabrir(request, pk):
    acta = _acta_visible(request, pk)
    if not reglas.puede_reabrir(request.user, acta.asignacion):
        raise PermissionDenied
    if not acta.cerrada:
        messages.info(request, 'Esas calificaciones no están cerradas.')
        return redirect(url_del_acta(acta))
    form = MotivoForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        if form.is_valid():
            reglas.reabrir(acta, form.cleaned_data['motivo'], request.user)
            messages.success(request, 'Se reabrieron las calificaciones. Lo que se había cerrado quedó en el historial.')
            return redirect(url_del_acta(acta))
        messages.error(request, 'Escribe el motivo de la reapertura.')
    return render(request, 'calificaciones/reabrir.html', {'acta': acta, 'form': form, 'volver': url_del_acta(acta)})


@requiere_alguno(*reglas.ENTRAR)
def historial(request, pk):
    acta = _acta_visible(request, pk)
    cambios = acta.cambios.select_related('usuario', 'inscripcion__alumno')
    return render(request, 'calificaciones/historial.html', {'acta': acta, 'cambios': cambios[:500], 'volver': url_del_acta(acta)})


# ---------------------------------------------------------------------------
# Concentrado (en pantalla, para imprimir/PDF y en Excel)
# ---------------------------------------------------------------------------
def concentrado(tabla, usuario):
    """Lo que lleva el concentrado: encabezado, estudiantes con su calificación final y si es provisional o cerrado."""
    acta = tabla.acta
    asignacion = acta.asignacion
    nivel = dict(Grado.NIVEL_CHOICES).get(asignacion.grado.nivel, asignacion.grado.nivel)
    filas = []
    for fila in tabla.filas:
        r = fila.resultado
        filas.append({'numero': fila.numero, 'nombre': fila.nombre, 'final': reglas.dos_decimales(r.final) if r.final is not None else '',
                      'provisional': not acta.cerrada and (r.final is None or r.pendientes > 0)})
    if acta.cerrada:
        estado = f'Calificaciones cerradas el {timezone.localtime(acta.cerrada_en):%d/%m/%Y %H:%M}' if acta.cerrada_en else 'Calificaciones cerradas'
    else:
        estado = 'PROVISIONAL: el periodo sigue en captura; los resultados pueden cambiar.'
    return {
        'nivel': nivel, 'ciclo': str(asignacion.ciclo), 'materia': str(asignacion.materia), 'grupo': str(asignacion.grupo),
        'docente': str(asignacion.profesor) if asignacion.profesor_id else 'Sin docente asignado', 'periodo': acta.periodo.nombre,
        'cerrada': acta.cerrada, 'estado': estado, 'filas': filas, 'generado': timezone.localtime(),
        'usuario': usuario.get_full_name() or usuario.get_username(),
    }


@requiere_alguno(*reglas.ENTRAR)
def concentrado_imprimir(request, pk):
    acta = _acta_visible(request, pk)
    return render(request, 'calificaciones/concentrado_hoja.html', {
        'c': concentrado(reglas.tabla(acta), request.user), 'imprimir_al_abrir': request.GET.get('pdf') == '1',
        'volver': url_del_acta(acta, 'concentrado'),
    })


@requiere_alguno(*reglas.ENTRAR)
def concentrado_excel(request, pk):
    acta = _acta_visible(request, pk)
    c = concentrado(reglas.tabla(acta), request.user)
    filas = [
        [Celda(f"Nivel {c['nivel'].lower()} · Ciclo escolar {c['ciclo']}", TITULO)],
        [Celda('Concentrado de calificaciones por materia', SECCION)],
        ['Asignatura', c['materia']], ['Grupo', c['grupo']], ['Profesor', c['docente']], ['Periodo', c['periodo']],
        ['Estado', c['estado']],
        ['Generado', f"{c['generado']:%d/%m/%Y %H:%M} por {c['usuario']}"],
        [],
        [Celda('No.', ENCABEZADO), Celda('Nombre', ENCABEZADO), Celda('Calificación final', ENCABEZADO), Celda('Firma de enterado', ENCABEZADO)],
    ]
    for f in c['filas']:
        if not f['final']:
            final = 'Sin calificar'
        elif f['provisional']:
            final = f"{f['final']} (provisional)"
        else:
            final = float(f['final'])
        filas.append([f['numero'], f['nombre'], final, ''])
    filas += [[], [], ['Firma del profesor', '', 'Vo.Bo. Coordinación', 'Vo.Bo. Dirección'], [c['docente']]]
    datos = libro([Hoja('Concentrado', filas, anchos=[8, 42, 20, 28])])
    nombre = slugify(f"concentrado-{c['materia']}-{c['grupo']}-{c['periodo']}") + '.xlsx'
    respuesta = HttpResponse(datos, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    respuesta['Content-Disposition'] = f'attachment; filename="{nombre}"'
    return respuesta

