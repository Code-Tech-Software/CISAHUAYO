"""Reuniones con el colegio en el portal de tutores: solo las citas a las que el tutor está invitado.

Ve la fecha, el horario, el lugar, quién lo atenderá, a sus estudiantes, el estado, los acuerdos compartidos con la
familia, los documentos compartidos y la minuta para la familia. Nunca las observaciones internas, las notas
confidenciales, los acuerdos no compartidos ni el historial interno. Puede confirmar su asistencia a una cita programada
(queda como confirmación por el portal). Cualquier otra cita responde 404.

Desde el 2026-10-28 también ve las indicaciones de la cita, la agrega a su calendario (.ics), dice que leyó la minuta y
los acuerdos («enterado»), reporta el avance de los acuerdos de la familia y escribe por Mensajes a quien lo atenderá.
"""
from datetime import time

from django.contrib import messages
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from CISAHUAYO import portales

from . import notificaciones, reglas
from .context_processors import datos_de_avisos, generar_si_toca
from .forms import AvanceFamiliaForm
from .models import Acuerdo, AdjuntoReunion, ContactoReunion, Reunion
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


def _a_quienes_puede_escribir(tutor, personal):
    """Los ids de las cuentas del personal a las que el tutor puede escribir por Mensajes (las mismas reglas de la
    mensajería). Si la mensajería falla, ninguna: la cita se ve igual."""
    try:
        from Mensajes import reglas as mensajeria
        propio = mensajeria.de_portal(portales.TUTOR, tutor)
        return {p.usuario_id for p in personal if mensajeria.pueden_conversar(propio, mensajeria.de_usuario(p.usuario))}
    except Exception:
        return set()


@require_GET
@tutor_requerido
def detalle(request, pk):
    reunion = _suya(request, pk)
    tutor = request.cuenta_portal
    notificaciones.marcar_leidas(reunion, tutor=tutor)
    personal = list(reunion.participantes.filter(activo=True).select_related('usuario').order_by('papel'))
    tiene_minuta = reunion.estado == Reunion.REALIZADA and hasattr(reunion, 'minuta')
    invitado = reunion.tutores.filter(tutor=tutor).first()
    acuerdos = list(reunion.acuerdos.filter(compartido=True).select_related('responsable').prefetch_related('seguimientos'))
    reportables = set(reglas.acuerdos_de_la_familia(reunion).values_list('pk', flat=True))
    for acuerdo in acuerdos:
        acuerdo.reportable = acuerdo.pk in reportables
        acuerdo.mi_avance = next((s for s in reversed(acuerdo.seguimientos.all()) if s.tutor_id == tutor.pk), None)
    return render(request, 'portales/tutores/reuniones/detalle.html', {
        **portales.contexto(request), 'base': 'portales/base.html', 'reunion': reunion, 'personal': personal,
        'estudiantes': reunion.estudiantes.select_related('alumno', 'inscripcion__grado', 'inscripcion__grupo__nombre'),
        'acuerdos': acuerdos, 'form_avance': AvanceFamiliaForm(),
        'documentos': reunion.adjuntos.filter(compartido=True),
        'cambios': reunion.cambios_de_fecha.select_related('sala_anterior'),
        'puede_confirmar': reunion.estado in (Reunion.PROGRAMADA, Reunion.CONFIRMADA) and reunion.confirmacion_tutor_id is None,
        'tonos': reglas.TONO_DE_ESTADO, 'iconos': reglas.ICONO_DE_ESTADO, 'tonos_acuerdo': reglas.TONO_DE_ACUERDO,
        'tiene_minuta': tiene_minuta, 'enterado': invitado.enterado_minuta_en if invitado and tiene_minuta and reglas.enterado_vigente(invitado, reunion.minuta) else None,
        'minuta_cambio': bool(invitado and invitado.enterado_minuta_en and tiene_minuta and not reglas.enterado_vigente(invitado, reunion.minuta)),
        'con_calendario': reunion.programada and reunion.estado in Reunion.ACTIVAS,
        'escribir_a': _a_quienes_puede_escribir(tutor, personal),
    })


@require_POST
@tutor_requerido
def enterado(request, pk):
    """«Leí la minuta y los acuerdos»."""
    reunion = _suya(request, pk)
    try:
        reglas.enterado_de_la_minuta(reunion, tutor=request.cuenta_portal)
    except ReglaRota as error:
        messages.error(request, ' '.join(error.mensajes))
    else:
        messages.success(request, 'Gracias: quedó registrado que leíste la minuta y los acuerdos.')
    return redirect(reverse('portal_tutores:reuniones:detalle', args=[reunion.pk]) + '#minuta')


@require_POST
@tutor_requerido
def avance(request, pk):
    """«Ya lo hice»: el avance de un acuerdo de la familia, con una nota y, si quiere, una foto o un PDF."""
    acuerdo = get_object_or_404(Acuerdo.objects.select_related('reunion', 'responsable', 'reunion__responsable'), pk=pk, compartido=True,
                                reunion__tutores__tutor=request.cuenta_portal)
    form = AvanceFamiliaForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, ' '.join(error for errores in form.errors.values() for error in errores))
    else:
        try:
            reglas.avance_de_la_familia(acuerdo, tutor=request.cuenta_portal, nota=form.cleaned_data['nota'],
                                        evidencia=form.cleaned_data.get('evidencia'), tipo_evidencia=getattr(form, 'tipo_evidencia', ''))
        except ReglaRota as error:
            messages.error(request, ' '.join(error.mensajes))
        else:
            messages.success(request, 'Gracias: enviamos tu avance. El colegio lo revisará.')
    return redirect(reverse('portal_tutores:reuniones:detalle', args=[acuerdo.reunion_id]) + f'#acuerdo-{acuerdo.pk}')


@require_GET
@tutor_requerido
def calendario_ics(request, pk):
    """«Agregar a mi calendario»: la cita con sus indicaciones."""
    reunion = _suya(request, pk)
    if not (reunion.programada and reunion.estado in Reunion.ACTIVAS):
        raise Http404('La cita no está programada.')
    url = request.build_absolute_uri(reverse('portal_tutores:reuniones:detalle', args=[reunion.pk]))
    respuesta = HttpResponse(reglas.ics_de_reunion(reunion, familia=True, url=url), content_type='text/calendar; charset=utf-8')
    respuesta['Content-Disposition'] = f'attachment; filename="cita-{reunion.folio}.ics"'
    return respuesta


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
