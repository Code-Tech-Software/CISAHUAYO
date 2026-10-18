from django.urls import include, path

from CISAHUAYO import portales
from Agenda.urls import rutas_de_portal as rutas_de_agenda
from Comunicados.urls import rutas_de_portal as rutas_de_comunicados
from Mensajes.urls import rutas_de_portal

from . import views

app_name = 'portal_estudiantes'

urlpatterns = [
    path('', views.inicio, name='inicio'),
    path('salir/', views.salir, name='salir'),
    path('mensajes/', include((rutas_de_portal(portales.ESTUDIANTE), 'mensajes'))),
    path('comunicados/', include((rutas_de_comunicados(portales.ESTUDIANTE), 'comunicados'))),
    path('agenda/', include((rutas_de_agenda(portales.ESTUDIANTE), 'agenda'))),
]
