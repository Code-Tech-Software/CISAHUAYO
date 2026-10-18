"""Retiros anticipados en el portal de tutores: avisar que recogerá a uno o varios de sus hijos antes de la salida,
consultar sus avisos próximos y su historial (el estado de cada hijo) y cancelarlos mientras no se haya confirmado la
salida. Solo sus propios avisos; lo ajeno responde 404. Las reglas están en Retiros/reglas.py."""
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from CISAHUAYO import portales

from . import notificaciones, reglas
from .context_processors import datos_de_avisos
from .forms import AvisoForm, CancelarForm
from .models import AvisoRetiro, RetiroEstudiante

TIPO = portales.TUTOR


def _avisos_del_tutor(tutor):
    return (AvisoRetiro.objects.filter(tutor=tutor).select_related('motivo', 'recoge')
            .prefetch_related('estudiantes__alumno', 'estudiantes__inscripcion__grupo__grado', 'estudiantes__inscripcion__grupo__nombre',
                              'estudiantes__recogio'))


def _con_estado(avisos):
    for aviso in avisos:
        aviso.retiros = list(aviso.estudiantes.all())
        aviso.estado_general = reglas.estado_general(aviso.retiros)
    return avisos


@portales.portal_requerido(TIPO)
def lista(request):
    tutor = request.cuenta_portal
    hoy = timezone.localdate()
    avisos = _con_estado(list(_avisos_del_tutor(tutor)))
    proximos = sorted((a for a in avisos if reglas.es_proximo(a, a.retiros, hoy)), key=lambda a: (a.fecha, a.hora))
    historial = [a for a in avisos if not reglas.es_proximo(a, a.retiros, hoy)][:60]
    return render(request, 'portales/tutores/retiros/lista.html', {
        **portales.contexto(request), 'proximos': proximos, 'historial': historial, 'clases': reglas.TONO_DE_ESTADO,
        'puede_avisar': any(hijo.disponible for hijo in reglas.hijos_de(tutor)),
    })


@portales.portal_requerido(TIPO)
def crear(request):
    tutor = request.cuenta_portal
    hijos = reglas.hijos_de(tutor)
    form = AvisoForm(request.POST or None, tutor=tutor, hijos=hijos)
    if request.method == 'POST' and form.is_valid():
        datos = form.cleaned_data
        recoge = next((p['tutor'] for p in form.personas if p['tutor'].pk == datos['recoge']), None)
        try:
            aviso = reglas.avisar(tutor, datos['alumnos'], datos['fecha'], datos['hora'], datos['motivo'], datos['detalles'], recoge)
        except reglas.RetiroRechazado as rechazo:
            for mensaje in rechazo.mensajes:
                form.add_error(None, mensaje)
        else:
            messages.success(request, 'Listo: el colegio recibió tu aviso. Te avisaremos cuando confirme la salida de cada estudiante.')
            return redirect(reverse('portal_tutores:retiros:detalle', args=[aviso.pk]) + '?nuevo=1')
    if request.method == 'POST' and not form.is_valid():
        messages.error(request, 'Revisa lo marcado: hay datos por corregir.')
    return render(request, 'portales/tutores/retiros/crear.html', {
        **portales.contexto(request), 'form': form, 'hijos': hijos, 'elegidos': form.elegidos(),
        'personas': form.personas, 'hay_disponibles': any(h.disponible for h in hijos),
        'requieren_explicacion': [m.pk for m in form.fields['motivo'].queryset if m.requiere_explicacion],
    })


@portales.portal_requerido(TIPO)
def detalle(request, pk):
    tutor = request.cuenta_portal
    aviso = get_object_or_404(_avisos_del_tutor(tutor), pk=pk)
    notificaciones.marcar_leidas(aviso, tutor=tutor)
    _con_estado([aviso])
    return render(request, 'portales/tutores/retiros/detalle.html', {
        **portales.contexto(request), 'aviso': aviso, 'clases': reglas.TONO_DE_ESTADO, 'nuevo': request.GET.get('nuevo') == '1',
        'cancelables': [r for r in aviso.retiros if r.estado == RetiroEstudiante.AVISADO],
    })


@portales.portal_requerido(TIPO)
def cancelar(request, pk):
    tutor = request.cuenta_portal
    aviso = get_object_or_404(_avisos_del_tutor(tutor), pk=pk)
    volver = reverse('portal_tutores:retiros:detalle', args=[aviso.pk])
    cancelables = list(aviso.estudiantes.filter(estado=RetiroEstudiante.AVISADO).select_related('alumno'))
    if not cancelables:
        messages.info(request, 'Este aviso ya no tiene estudiantes por cancelar (las salidas confirmadas no se pueden cambiar).')
        return redirect(volver)
    form = CancelarForm(request.POST or None, retiros=cancelables)
    if request.method == 'POST' and form.is_valid():
        try:
            cancelados = reglas.cancelar_por_tutor(aviso, tutor, form.cleaned_data['retiros'], form.cleaned_data['motivo'])
        except reglas.RetiroRechazado as rechazo:
            for mensaje in rechazo.mensajes:
                form.add_error(None, mensaje)
        else:
            messages.success(request, f'Se canceló el retiro de {", ".join(r.alumno.nombre for r in cancelados)}. El colegio ya lo sabe.')
            return redirect(volver)
    return render(request, 'portales/tutores/retiros/cancelar.html', {
        **portales.contexto(request), 'aviso': aviso, 'form': form, 'volver': volver,
    })


@require_GET
@portales.portal_requerido(TIPO)
def resumen(request):
    return JsonResponse(datos_de_avisos(tutor=request.cuenta_portal))
