"""Asistencia por materia (administración): la misma matriz que ven los docentes, con todas las materias del ciclo
actual, y la justificación de una falta con la foto de su comprobante. Sustituye al «Pase de lista» (pedido del
2026-10-13).

Las reglas viven en Alumnos/asistencia_docente.py y las piezas de la matriz (contexto, guardado de una celda y
reporte) en views_docente.py: los registros son los mismos, así que lo que se cambia aquí lo ve el docente, y al revés.

Solo para quien ve la asistencia del colegio (`view_asistenciageneral`) y la de las materias: un docente con su rol
de siempre no entra aquí (solo ve sus materias). Justificar exige, además, el permiso de registrar justificaciones; el
servidor lo comprueba en cada petición aunque la pantalla no ofrezca la opción.
"""
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from Alumnos.academico import ciclo_actual
from Alumnos.asistencia_docente import (
    NOMBRES,
    CambioRechazado,
    asignaciones_del_ciclo,
    celda_de,
    justificar_falta,
    puede_justificar,
)
from Alumnos.clases import pertenece
from Alumnos.models import Inscripcion
from CISAHUAYO.permisos import requiere_permisos

from .forms import TAMANO_MAXIMO_MB, JustificarFaltaForm
from .views_docente import celda_json, contexto_de_matriz, respuesta_de_guardado, respuesta_de_reporte

VER = ('Alumnos.view_asistenciageneral', 'Alumnos.view_asistenciamateria')


def _asignacion(pk):
    """Una materia (de un grupo) vigente del ciclo actual; si no, 404."""
    return get_object_or_404(asignaciones_del_ciclo(), pk=pk)


def _permisos_de_la_pantalla(usuario, asignacion):
    """(puede justificar faltas, ve el detalle de las justificaciones) en esta materia."""
    return puede_justificar(usuario, asignacion), usuario.has_perm('Alumnos.view_justificacion')


@requiere_permisos(*VER)
def materias(request):
    ciclo = ciclo_actual()
    asignaciones = list(asignaciones_del_ciclo(ciclo)) if ciclo else []
    contexto = {'seccion': 'materias', 'ciclo': ciclo, 'asignaciones': asignaciones}
    if not asignaciones:
        return render(request, 'asistencias/materias.html', contexto)

    # Primero el grupo y luego su materia; sin elegir, la primera materia del primer grupo
    elegida, grupo = request.GET.get('materia', ''), request.GET.get('grupo', '')
    if elegida:
        asignacion = next((a for a in asignaciones if elegida.isdigit() and a.pk == int(elegida)), None)
        if asignacion is None:
            raise Http404('Esa materia no es del ciclo actual.')
    else:
        asignacion = next((a for a in asignaciones if grupo.isdigit() and a.grupo_id == int(grupo)), asignaciones[0])

    grupos = list({a.grupo_id: a.grupo for a in asignaciones}.values())   # en el orden escolar de las materias
    justifica, ve_justificaciones = _permisos_de_la_pantalla(request.user, asignacion)
    contexto.update(contexto_de_matriz(request, asignacion, puede_justificar=justifica, ver_justificaciones=ve_justificaciones))
    contexto.update({
        'grupos': grupos,
        'materias_del_grupo': [a for a in asignaciones if a.grupo_id == asignacion.grupo_id],
        'ver_justificaciones': ve_justificaciones,
        'tamano_maximo_mb': TAMANO_MAXIMO_MB,
        'url_reporte': reverse('asistencias:materias_reporte'),
        'url_guardar': reverse('asistencias:materias_guardar', args=[asignacion.pk]),
        'url_justificar': reverse('asistencias:materias_justificar', args=[asignacion.pk]) if justifica else '',
    })
    return render(request, 'asistencias/materias.html', contexto)


@require_POST
@requiere_permisos('Alumnos.view_asistenciageneral', 'Alumnos.change_asistenciamateria')
def materias_guardar(request, pk):
    """Guarda una celda (presente, falta o retardo) de cualquier materia del ciclo actual."""
    asignacion = _asignacion(pk)
    justifica, ve_justificaciones = _permisos_de_la_pantalla(request.user, asignacion)
    return respuesta_de_guardado(request, asignacion, puede_justificar=justifica, ver_justificaciones=ve_justificaciones)


@require_POST
@requiere_permisos(*VER, 'Alumnos.add_justificacion')
def materias_justificar(request, pk):
    """Justifica una falta registrada con la foto obligatoria de su comprobante. Responde JSON con la celda ya
    guardada (una J) o con el motivo por el que no se guardó (y, en `errores`, el de cada campo)."""
    asignacion = _asignacion(pk)
    ve_justificaciones = request.user.has_perm('Alumnos.view_justificacion')
    formulario = JustificarFaltaForm(request.POST, request.FILES)
    if not formulario.is_valid():
        errores = {campo: [str(error) for error in lista] for campo, lista in formulario.errors.items()}
        primero = next(iter(errores.values()))[0]
        return JsonResponse({'ok': False, 'mensaje': primero, 'errores': errores}, status=400)

    datos = formulario.cleaned_data
    inscripcion = get_object_or_404(Inscripcion.objects.select_related('alumno'), pk=datos['inscripcion'])
    try:
        celda = justificar_falta(
            asignacion, inscripcion, datos['fecha'], datos['version'], datos['motivo'], datos['comprobante'], request.user,
        )
    except CambioRechazado as error:
        respuesta = {'ok': False, 'mensaje': error.mensaje}
        if pertenece(inscripcion, asignacion, datos['fecha']):   # lo que está guardado
            guardada = celda_de(asignacion, inscripcion, datos['fecha'], request.user, puede_justificar=True)
            respuesta.update(celda_json(guardada, ve_justificaciones))
        return JsonResponse(respuesta, status=error.codigo)
    return JsonResponse({
        'ok': True, **celda_json(celda, ve_justificaciones),
        'mensaje': f'{NOMBRES["J"]}: {inscripcion.alumno} · {asignacion.materia} · {datos["fecha"]:%d/%m/%Y}.',
    })


@requiere_permisos(*VER)
def materias_reporte(request):
    """El reporte de lo que muestra la matriz de cualquier materia del ciclo actual (para imprimir o para Excel)."""
    elegida = request.GET.get('materia', '')
    if not elegida.isdigit():
        raise Http404('Elige una materia.')
    asignacion = _asignacion(int(elegida))
    return respuesta_de_reporte(request, asignacion, asignacion.profesor, reverse('asistencias:materias'))
