"""Inicio de sesión: la pantalla y las reglas son las del admin de Django (misma ruta, /admin/login/), pero al entrar sin
un destino concreto se llega al sistema del colegio y no al panel de administración de Django.

El admin decide el destino por su cuenta: sin `?next=` manda siempre a `admin:index`. Aquí solo se corrige eso; si hay un
`next` (una página protegida que mandó a iniciar sesión, o el propio /admin/) se respeta tal cual.
"""
from django.contrib import admin
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.shortcuts import redirect


def acceso(request, extra_context=None):
    sin_destino = REDIRECT_FIELD_NAME not in request.GET and REDIRECT_FIELD_NAME not in request.POST
    # Quien ya tiene sesión y acceso, al abrir la pantalla de acceso, pasa directo al sistema
    if sin_destino and request.method == 'GET' and admin.site.has_permission(request):
        return redirect('inicio')
    return admin.site.login(request, extra_context)
