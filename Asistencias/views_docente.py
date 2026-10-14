"""Asistencia para docentes: la matriz de cada materia del profesor (estudiantes × días del periodo abierto) y el
guardado de una celda y el reporte (para imprimir o para Excel) de lo que muestra la matriz. Las reglas viven en
Alumnos/asistencia_docente.py; aquí solo se comprueba quién pide qué.

Solo para cuentas vinculadas a una ficha de profesor, y solo sus materias: lo que no es suyo responde 403 aunque se
teclee la dirección.

La asistencia por materia de la administración (Asistencias/views_materias.py) usa estas mismas piezas —el contexto
de la matriz, el guardado de una celda y el reporte—; cada vista decide qué materias se pueden abrir."""
import csv
import json
from datetime import date

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.http import urlencode
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from Alumnos.academico import ciclo_actual
from Alumnos.asistencia_docente import (
    LEYENDA,
    NOMBRES,
    OBSERVACION_MAXIMA,
    CambioRechazado,
    ajustar,
    asignaciones_del_profesor,
    atajos,
    celda_de,
    guardar_cambio,
    limites_del_periodo,
    matriz,
    periodo_de,
    reporte,
)
from Alumnos.models import Inscripcion
from Alumnos.periodos import meses_si_es_muy_largo
from Alumnos.utils import proteger_celda_csv
from CISAHUAYO.permisos import requiere_permisos
from Usuarios.docentes import profesor_de


def _asignacion_propia(profesor, pk):
    """La materia si es del profesor en el ciclo actual; si no, 403 (no se dice si existe)."""
    asignacion = asignaciones_del_profesor(profesor).filter(pk=pk).first()
    if asignacion is None:
        raise PermissionDenied
    return asignacion


@requiere_permisos('Alumnos.view_asistenciamateria')
def docente(request):
    profesor = profesor_de(request.user)
    contexto = {'seccion': 'docente', 'profesor': profesor, 'ciclo': ciclo_actual()}
    if profesor is None:
        return render(request, 'asistencias/docente.html', contexto)

    asignaciones = list(asignaciones_del_profesor(profesor))
    contexto['asignaciones'] = asignaciones
    if not asignaciones:
        return render(request, 'asistencias/docente.html', contexto)

    elegida = request.GET.get('materia', '')
    if elegida:
        if not elegida.isdigit():
            raise PermissionDenied
        asignacion = _asignacion_propia(profesor, int(elegida))
    else:
        asignacion = asignaciones[0]
    contexto.update(contexto_de_matriz(request, asignacion))
    contexto.update({
        'url_reporte': reverse('asistencias:docente_reporte'),
        'url_guardar': reverse('asistencias:docente_guardar', args=[asignacion.pk]),
    })
    return render(request, 'asistencias/docente.html', contexto)


def contexto_de_matriz(request, asignacion, puede_justificar=False, ver_justificaciones=False, url_lista=None):
    """Lo que dibuja la matriz de una materia (la del docente o la de la administración): las fechas pedidas dentro del
    periodo abierto, los rangos rápidos, la leyenda y si se puede cambiar. Para la administración, además, qué faltas
    se pueden justificar (`puede_justificar`) y los datos de cada J con su comprobante (`ver_justificaciones`)."""
    hoy = timezone.localdate()
    periodo = periodo_de(asignacion)
    limites = limites_del_periodo(periodo, asignacion.ciclo) if periodo else None
    desde, hasta, aviso_de_fechas = _rango_pedido(request.GET, limites)
    datos = matriz(asignacion, usuario=request.user, hoy=hoy, desde=desde, hasta=hasta, puede_justificar=puede_justificar)
    if ver_justificaciones:
        for fila in datos['filas']:
            for celda in fila['celdas']:
                if celda.justificacion is not None:
                    _justificacion_a_la_vista(celda)
                    celda.detalle_justificacion = json.dumps(justificacion_json(celda.justificacion, url_lista), ensure_ascii=False)
    return {
        'asignacion': asignacion,
        'datos': datos,
        'aviso_de_fechas': aviso_de_fechas,
        'meses_del_periodo_largo': meses_si_es_muy_largo(periodo) if periodo else None,
        'atajos': [
            {'nombre': nombre, 'desde': inicio, 'hasta': fin, 'activo': (inicio, fin) == (datos['desde'], datos['hasta'])}
            for nombre, inicio, fin in (atajos(limites, hoy) if limites else [])
        ],
        'puede_cambiar': request.user.has_perm('Alumnos.change_asistenciamateria'),
        'puede_justificar': puede_justificar,
        'observacion_maxima': OBSERVACION_MAXIMA,
        'leyenda': LEYENDA,
    }


def _justificacion_a_la_vista(celda):
    """En la administración una J se abre para ver su justificación: así lo dice su globo de ayuda."""
    celda.nombre = celda.nombre.replace('se cambia desde Justificaciones', 'haz clic para ver su justificación y su comprobante')


def justificacion_json(justificacion, url_lista=None):
    """Lo que la administración ve de la justificación de una J: motivo, quién y cuándo, su comprobante y dónde está en
    la lista de justificaciones (`url_lista`; por omisión, la de la administración). El comprobante se entrega por la
    vista protegida (asistencias:comprobante), nunca con la dirección del archivo."""
    documento = justificacion.documento
    extension = documento.name.rsplit('.', 1)[-1].lower() if documento and '.' in documento.name else ''
    quien = justificacion.registrada_por
    alumno = justificacion.inscripcion.alumno
    return {
        'motivo': justificacion.motivo,
        'registrada_por': (quien.get_full_name() or quien.get_username()) if quien else '',
        'registrada_el': date_format(timezone.localtime(justificacion.creado), 'j \\d\\e F \\d\\e Y, H:i').lower(),
        'de_la_falta': justificacion.asistencia_id is not None,
        'comprobante': reverse('asistencias:comprobante', args=[justificacion.pk]) if documento else '',
        # Sin extensión (Cloudinary guarda así los archivos) se intenta como imagen; si no lo es, la ventana pone un enlace
        'es_imagen': extension in ('jpg', 'jpeg', 'png', 'webp', ''),
        'lista': f"{url_lista or reverse('asistencias:justificaciones')}?{urlencode({'q': alumno.referencia, 'desde': justificacion.fecha, 'hasta': justificacion.fecha})}",
    }


def _fecha(texto):
    try:
        return date.fromisoformat(texto) if texto else None
    except ValueError:
        raise ValueError(texto) from None


def _rango_pedido(datos, limites):
    """(desde, hasta, aviso) de los filtros «Desde» y «Hasta»: (None, None, …) para el mes en curso. Fuera del
    periodo se ajustan a él; mal escritas o al revés, se ignoran. El aviso explica lo que se ajustó (o None)."""
    if limites is None or not (datos.get('desde') or datos.get('hasta')):
        return None, None, None
    try:
        desde, hasta = _fecha(datos.get('desde')), _fecha(datos.get('hasta'))
    except ValueError:
        return None, None, 'Esas fechas no son válidas: se muestra el mes en curso.'
    desde, hasta = desde or limites[0], hasta or limites[1]
    if desde > hasta:
        return None, None, 'La fecha de inicio va después de la de fin: se muestra el mes en curso.'
    if hasta < limites[0] or desde > limites[1]:
        return None, None, 'Esas fechas quedan fuera del periodo: se muestra el mes en curso.'
    if desde < limites[0] or hasta > limites[1]:
        desde, hasta = ajustar(desde, limites), ajustar(hasta, limites)
        return desde, hasta, f'Se ajustó al periodo, que va del {_texto(limites[0])} al {_texto(limites[1])}.'
    return desde, hasta, None


def _texto(fecha):
    return date_format(fecha, 'j \\d\\e F \\d\\e Y').lower()


# ---------------------------------------------------------------------------
# Reporte: lo mismo que se ve en la matriz (la materia y las fechas elegidas), para imprimir o para Excel
# ---------------------------------------------------------------------------
@requiere_permisos('Alumnos.view_asistenciamateria')
def docente_reporte(request):
    profesor = profesor_de(request.user)
    elegida = request.GET.get('materia', '')
    if profesor is None or not elegida.isdigit():
        raise PermissionDenied
    asignacion = _asignacion_propia(profesor, int(elegida))
    return respuesta_de_reporte(request, asignacion, profesor, reverse('asistencias:docente'))


def respuesta_de_reporte(request, asignacion, profesor, url_matriz):
    """La hoja para imprimir (o el CSV con `formato=csv`) de lo que muestra la matriz de la materia; sin nada que
    reportar, de vuelta a la matriz (`url_matriz`) con un aviso."""
    periodo = periodo_de(asignacion)
    limites = limites_del_periodo(periodo, asignacion.ciclo) if periodo else None
    desde, hasta, _ = _rango_pedido(request.GET, limites)
    datos = matriz(asignacion, usuario=request.user, desde=desde, hasta=hasta)
    if not (datos['periodo'] and datos['columnas'] and datos['filas']):
        messages.error(request, 'No hay asistencia que reportar en esas fechas.')
        return redirect(f'{url_matriz}?materia={asignacion.pk}')

    contenido = reporte(datos)
    if request.GET.get('formato') == 'csv':
        return _reporte_csv(asignacion, profesor, datos, contenido)
    return render(request, 'asistencias/docente_reporte.html', {
        'asignacion': asignacion,
        'profesor': profesor,
        'datos': datos,
        'reporte': contenido,
        'generado': timezone.localtime(),
        'volver': f"{url_matriz}?materia={asignacion.pk}&desde={datos['desde']:%Y-%m-%d}&hasta={datos['hasta']:%Y-%m-%d}",
        'leyenda': LEYENDA,
    })


def _reporte_csv(asignacion, profesor, datos, contenido):
    """El reporte en CSV para Excel: encabezado, la matriz con los totales por estudiante y las observaciones."""
    desde, hasta = datos['desde'], datos['hasta']
    nombre = f'asistencia-{slugify(asignacion.materia.nombre)}-{slugify(asignacion.grupo.corto)}-{desde:%Y%m%d}-{hasta:%Y%m%d}.csv'
    respuesta = HttpResponse(content_type='text/csv; charset=utf-8')
    respuesta['Content-Disposition'] = f'attachment; filename="{nombre}"'
    respuesta.write('\ufeff')   # para que Excel reconozca los acentos
    escritor = csv.writer(respuesta)
    periodo = datos['periodo']
    escritor.writerow(['Reporte de asistencia'])
    escritor.writerow(['Materia', proteger_celda_csv(f'{asignacion.materia} · {asignacion.grupo}')])
    escritor.writerow(['Profesor', proteger_celda_csv(str(profesor) if profesor else 'Sin profesor asignado')])
    escritor.writerow(['Periodo', proteger_celda_csv(f'{periodo.nombre} ({periodo.fecha_inicio:%d/%m/%Y} al {periodo.fecha_fin:%d/%m/%Y})')])
    escritor.writerow(['Fechas', f'{desde:%d/%m/%Y} al {hasta:%d/%m/%Y}'])
    escritor.writerow(['Generado', f'{timezone.localtime():%d/%m/%Y %H:%M}'])
    escritor.writerow([])
    escritor.writerow([
        'Estudiante', 'Referencia', *[f"{columna['inicial']} {columna['fecha']:%d/%m}" for columna in datos['columnas']],
        'Presentes', 'Retardos', 'Faltas', 'Faltas justificadas', 'Sin registro', 'Asistencia (%)',
    ])
    for fila in contenido['filas']:
        resumen = fila['resumen']
        escritor.writerow([
            proteger_celda_csv(f"{fila['alumno'].apellido_paterno} {fila['alumno'].apellido_materno} {fila['alumno'].nombre}".strip()),
            proteger_celda_csv(fila['alumno'].referencia),
            *[celda.letra for celda in fila['celdas']],
            resumen['presentes'], resumen['retardos'], resumen['faltas'], resumen['justificadas'], resumen['sin_registro'],
            '' if resumen['porcentaje'] is None else resumen['porcentaje'],
        ])
    escritor.writerow([])
    escritor.writerow(['P = presente, F = falta, R = retardo, J = falta justificada, S = suspensión de clases o estudiante '
                       'suspendido (autorizada o pendiente de autorizar), — = sin registro; vacío = sin clase, fecha futura o aún no inscrito'])
    if contenido['observaciones']:
        escritor.writerow([])
        escritor.writerow(['Observaciones'])
        escritor.writerow(['Fecha', 'Estudiante', 'Estado', 'Observación'])
        for nota in contenido['observaciones']:
            escritor.writerow([
                f"{nota['fecha']:%d/%m/%Y}", proteger_celda_csv(str(nota['alumno'])), nota['estado'], proteger_celda_csv(nota['observacion']),
            ])
    return respuesta


@require_POST
@requiere_permisos('Alumnos.change_asistenciamateria')
def docente_guardar(request, pk):
    """Guarda una celda: responde JSON con la celda ya guardada, o el motivo por el que no se guardó."""
    profesor = profesor_de(request.user)
    if profesor is None:
        raise PermissionDenied
    return respuesta_de_guardado(request, _asignacion_propia(profesor, pk))


def respuesta_de_guardado(request, asignacion, puede_justificar=False, ver_justificaciones=False):
    """Guarda el estado de una celda de la materia (lo que pide el POST) y responde JSON con la celda ya guardada, o
    con el motivo por el que no se guardó y lo que está guardado. Los dos últimos parámetros, como en
    `contexto_de_matriz`."""
    try:
        fecha = date.fromisoformat(request.POST.get('fecha', ''))
    except ValueError:
        return JsonResponse({'ok': False, 'mensaje': 'La fecha no es válida.'}, status=400)
    inscripcion_pk = request.POST.get('inscripcion', '')
    if not inscripcion_pk.isdigit():
        return JsonResponse({'ok': False, 'mensaje': 'Falta el estudiante.'}, status=400)
    inscripcion = get_object_or_404(Inscripcion.objects.select_related('alumno'), pk=int(inscripcion_pk))
    estado = request.POST.get('estado', '')
    try:
        celda = guardar_cambio(
            asignacion, inscripcion, fecha, estado, request.POST.get('version', ''), request.user,
            observaciones=request.POST.get('observaciones', ''), puede_justificar=puede_justificar,
        )
    except CambioRechazado as error:
        datos = {'ok': False, 'mensaje': error.mensaje}
        if inscripcion.grupo_id == asignacion.grupo_id:   # lo que está guardado
            guardada = celda_de(asignacion, inscripcion, fecha, request.user, puede_justificar=puede_justificar)
            datos.update(celda_json(guardada, ver_justificaciones))
        return JsonResponse(datos, status=error.codigo)
    explicacion = f' ({celda.observaciones})' if celda.observaciones else ''
    return JsonResponse({
        'ok': True, **celda_json(celda, ver_justificaciones),
        'mensaje': f'Guardado: {inscripcion.alumno} · {fecha:%d/%m} · {NOMBRES.get(celda.letra, celda.nombre)}{explicacion}.',
    })


def celda_json(celda, ver_justificacion=False):
    """Una celda para el JavaScript de la matriz. Con `ver_justificacion` (solo la administración), en una J también lo
    que se ve de su justificación."""
    if ver_justificacion and celda.justificacion is not None:
        _justificacion_a_la_vista(celda)
    datos = {
        'letra': celda.letra, 'nombre': celda.nombre, 'clase': celda.clase, 'version': celda.version,
        'editable': celda.editable, 'observaciones': celda.observaciones, 'justificable': celda.justificable,
    }
    if ver_justificacion:
        datos['justificacion'] = justificacion_json(celda.justificacion) if celda.justificacion is not None else None
    return datos
