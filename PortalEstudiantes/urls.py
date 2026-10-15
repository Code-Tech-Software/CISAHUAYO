from django.urls import include, path

from CISAHUAYO import portales
from Mensajes.urls import rutas_de_portal

from . import views

app_name = 'portal_estudiantes'

urlpatterns = [
    path('', views.inicio, name='inicio'),
    path('salir/', views.salir, name='salir'),
    path('mensajes/', include((rutas_de_portal(portales.ESTUDIANTE), 'mensajes'))),
]
