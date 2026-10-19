"""Reuniones con el colegio en el portal de tutores: solo las citas a las que el tutor está invitado.

Ve la fecha, el horario, el lugar, quién lo atenderá, a sus estudiantes, el estado, los acuerdos compartidos con la
familia, los documentos compartidos y la minuta para la familia. Nunca las observaciones internas, las notas
confidenciales, los acuerdos no compartidos ni el historial interno. Puede confirmar su asistencia a una cita programada
(queda como confirmación por el portal). Cualquier otra cita responde 404.
"""
from datetime import time

from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from CISAHUAYO import portales

from . import notificaciones, reglas
from .context_processors import datos_de_avisos, generar_si_toca
from .models import AdjuntoReunion, ContactoReunion, Reunion
from .reglas import ReglaRota
from .views import contexto_de_minuta

tutor_requerido = portales.portal_requerido(portales.TUTOR)


def _suyas(tutor):
    return Reunion.objects.filter(tutores__tutor=tutor).distinct()


def _suya(request, pk):
    return get_object_or_404(_suyas(request.cuenta_portal).select_related('sala', 'responsable', 'confirmacion_tutor'), pk=pk)


@require_GET
@tutor_requerido
def lista(request):
    hoy = timezone.localdate()
    reuniones = (_suyas(request.cuenta_portal).select_related('sala')
                 .prefetch_related('estudiantes__alumno').order_by('-fecha', '-hora_inicio', '-creada'))
    proximas = [r for r in reuniones if r.abierta]
    anteriores = [r for r in reuniones if not r.abierta]
    proximas.sort(key=lambda r: (r.fecha is None, r.fecha or hoy, r.hora_inicio or time.min))
    return render(request, 'portales/tutores/reuniones/lista.html', {
        **portales.contexto(request), 'base': 'portales/base.html', 'proximas': proximas, 'anteriores': anteriores,
        'tonos': reglas.TONO_DE_ESTADO, 'iconos': reglas.ICONO_DE_ESTADO, 'hoy': hoy,
    })


@require_GET
@tutor_requerido
def detalle(request, pk):
    reunion = _suya(request, pk)
    notificaciones.marcar_leidas(reunion, tutor=request.cuenta_portal)
    personal = reunion.participantes.filter(activo=True).select_related('usuario').order_by('papel')
    return render(request, 'portales/tutores/reuniones/detalle.html', {
        **portales.contexto(request), 'base': 'portales/base.html', 'reunion': reunion, 'personal': personal,
        'estudiantes': reunion.estudiantes.select_related('alumno', 'inscripcion__grado', 'inscripcion__grupo__nombre'),
        'acuerdos': reunion.acuerdos.filter(compartido=True).select_related('responsable'),
        'documentos': reunion.adjuntos.filter(compartido=True),
        'cambios': reunion.cambios_de_fecha.select_related('sala_anterior'),
        'puede_confirmar': reunion.estado in (Reunion.PROGRAMADA, Reunion.CONFIRMADA) and reunion.confirmacion_tutor_id is None,
        'tonos': reglas.TONO_DE_ESTADO, 'iconos': reglas.ICONO_DE_ESTADO, 'tonos_acuerdo': reglas.TONO_DE_ACUERDO,
        'tiene_minuta': reunion.estado == Reunion.REALIZADA and hasattr(reunion, 'minuta'),
    })


@require_POST
@tutor_requerido
def confirmar(request, pk):
    reunion = _suya(request, pk)
    try:
        reglas.confirmar_tutor(reunion, medio='PORTAL', momento=timezone.now(), tutor=request.cuenta_portal)
    except ReglaRota as error:
        messages.error(request, ' '.join(error.mensajes))
    else:
        messages.success(request, 'Gracias: confirmaste tu asistencia. Te avisaremos si hay algún cambio.')
    return redirect('portal_tutores:reuniones:detalle', reunion.pk)


@require_GET
@tutor_requerido
def minuta(request, pk):
    reunion = _suya(request, pk)
    if reunion.estado != Reunion.REALIZADA or not hasattr(reunion, 'minuta'):
        raise Http404('La reunión todavía no tiene minuta.')
    return render(request, 'reuniones/minuta_hoja.html', contexto_de_minuta(
        request, reunion, interna=False, volver=reverse('portal_tutores:reuniones:detalle', args=[reunion.pk])))


@require_GET
@tutor_requerido
def documento(request, pk):
    adjunto = get_object_or_404(AdjuntoReunion.objects.select_related('reunion'), pk=pk, compartido=True,
                                reunion__tutores__tutor=request.cuenta_portal)
    from Conducta.views import entregar_archivo
    return entregar_archivo(adjunto.archivo, adjunto.nombre_original, adjunto.tipo, descargar=request.GET.get('descargar') == '1')


@require_GET
@tutor_requerido
def resumen(request):
    generar_si_toca(tutor=request.cuenta_portal)
    return JsonResponse(datos_de_avisos(tutor=request.cuenta_portal))


__all__ = ['ContactoReunion']
