from django.urls import path

from . import views

app_name = 'asignaciones'

urlpatterns = [
    path('', views.mapa, name='mapa'),
    path('nueva/', views.nueva, name='nueva'),
    path('lista/', views.tablero, name='tablero'),
    path('profesores/', views.carga, name='carga'),
    path('movimientos/', views.movimientos, name='movimientos'),
    path('transferir/', views.transferir, name='transferir'),
    path('exportar/', views.exportar, name='exportar'),
]
