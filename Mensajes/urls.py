"""Las rutas de la mensajería. Las mismas vistas se montan tres veces, cada una con su protección:
- en el sistema (/mensajes/, espacio «mensajes»): usuarios con Mensajes.usar o Mensajes.contactar_familias;
- en los portales (/portal/estudiantes/mensajes/ y /portal/tutores/mensajes/, espacios «portal_estudiantes:mensajes» y
  «portal_tutores:mensajes»): la sesión de ese portal (ver PortalEstudiantes/urls.py y PortalTutores/urls.py).
"""
from django.urls import path

from . import views


def rutas(envolver):
    return [
        path('', envolver(views.bandeja), name='inicio'),
        path('nueva/', envolver(views.nueva), name='nueva'),
        path('contactos/', envolver(views.contactos), name='contactos'),
        path('resumen/', envolver(views.resumen), name='resumen'),
        path('<int:pk>/', envolver(views.conversacion), name='conversacion'),
        path('<int:pk>/enviar/', envolver(views.enviar), name='enviar'),
        path('<int:pk>/leida/', envolver(views.leida), name='leida'),
    ]


def rutas_de_portal(tipo):
    return rutas(views.para_portal(tipo))


app_name = 'mensajes'
urlpatterns = rutas(views.para_sistema)
