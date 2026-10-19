from django.urls import include, path

from CISAHUAYO import portales
from Agenda.urls import rutas_de_portal as rutas_de_agenda
from Comunicados.urls import rutas_de_portal as rutas_de_comunicados
from Mensajes.urls import rutas_de_portal
from Retiros.urls import rutas_de_portal as rutas_de_retiros
from Reuniones.urls import rutas_de_portal as rutas_de_reuniones

from . import views

app_name = 'portal_tutores'

urlpatterns = [
    path('', views.inicio, name='inicio'),
    path('estudiantes/<int:pk>/', views.estudiante, name='estudiante'),
    path('salir/', views.salir, name='salir'),
    path('mensajes/', include((rutas_de_portal(portales.TUTOR), 'mensajes'))),
    path('comunicados/', include((rutas_de_comunicados(portales.TUTOR), 'comunicados'))),
    path('agenda/', include((rutas_de_agenda(portales.TUTOR), 'agenda'))),
    path('retiros/', include((rutas_de_retiros(), 'retiros'))),
    path('reuniones/', include((rutas_de_reuniones(), 'reuniones'))),
]
