"""Portal de estudiantes (pedido del 2026-10-14): lo que ve el estudiante al entrar con su correo y su contraseña.

El acceso, la sesión y sus restricciones están en CISAHUAYO/portales.py (cada vista lleva `portal_requerido`); lo que
se muestra lo arma `resumen.py`, que también usa el portal de tutores.
"""
from django.shortcuts import render
from django.views.decorators.http import require_POST

from Alumnos.semanas import fecha_de
from CISAHUAYO import portales

from .resumen import resumen

TIPO = portales.ESTUDIANTE


@portales.portal_requerido(TIPO)
def inicio(request):
    return render(request, 'portales/estudiantes/inicio.html', {
        **portales.contexto(request), **resumen(request.cuenta_portal, semana=fecha_de(request.GET.get('semana'))),
    })


@require_POST
@portales.portal_requerido(TIPO)
def salir(request):
    return portales.salir(request, TIPO)
