from django.urls import include, path

from CISAHUAYO import portales
from Mensajes.urls import rutas_de_portal

from . import views

app_name = 'portal_tutores'

urlpatterns = [
    path('', views.inicio, name='inicio'),
    path('estudiantes/<int:pk>/', views.estudiante, name='estudiante'),
    path('salir/', views.salir, name='salir'),
    path('mensajes/', include((rutas_de_portal(portales.TUTOR), 'mensajes'))),
]
