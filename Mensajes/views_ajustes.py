"""Ajustes › Mensajes (pedido del 2026-10-27): el horario de atención de la mensajería. Lo configura quien modera la
mensajería (`Mensajes.moderar`, exclusivo del administrador)."""
from django.contrib import messages
from django.shortcuts import redirect, render

from CISAHUAYO.permisos import requiere_permisos
from Conducta.permisos import puede_configurar

from . import push
from .forms import ConfiguracionMensajesForm
from .models import ConfiguracionMensajes, SuscripcionPush
from .moderacion import MODERAR


@requiere_permisos(MODERAR)
def ajustes(request):
    configuracion = ConfiguracionMensajes.actual()
    form = ConfiguracionMensajesForm(request.POST or None, instance=configuracion)
    if request.method == 'POST':
        if form.is_valid():
            configuracion = form.save(commit=False)
            configuracion.modificado_por = request.user
            configuracion.save()
            messages.success(request, 'Se guardaron los ajustes de mensajes.')
            return redirect('ajustes_mensajes')
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return render(request, 'mensajes/ajustes.html', {
        'ajustes_seccion': 'mensajes', 'puede_configurar_conducta': puede_configurar(request.user), 'form': form,
        'push_activas': push.activas(), 'suscripciones': SuscripcionPush.objects.count(),
    })
