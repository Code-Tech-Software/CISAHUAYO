from django.urls import path

from . import views, views_bloques

app_name = 'asignaciones'

urlpatterns = [
    path('', views.tablero, name='tablero'),
    path('profesores/', views.carga, name='carga'),
    path('movimientos/', views.movimientos, name='movimientos'),
    path('transferir/', views.transferir, name='transferir'),
    path('exportar/', views.exportar, name='exportar'),
    # Bloques simultáneos y grupos de clase
    path('bloques/', views_bloques.lista, name='bloques'),
    path('bloques/nuevo/', views_bloques.crear, name='bloque_crear'),
    path('bloques/<int:pk>/', views_bloques.detalle, name='bloque'),
    path('bloques/<int:pk>/editar/', views_bloques.editar, name='bloque_editar'),
    path('bloques/<int:pk>/horarios/', views_bloques.horarios, name='bloque_horarios'),
    path('bloques/<int:pk>/sustituye/', views_bloques.sustituye, name='bloque_sustituye'),
    path('bloques/<int:pk>/poblacion/', views_bloques.poblacion, name='bloque_poblacion'),
    path('bloques/<int:pk>/distribuir/', views_bloques.distribuir, name='bloque_distribuir'),
    path('bloques/<int:pk>/activar/', views_bloques.activar, name='bloque_activar'),
    path('bloques/<int:pk>/desactivar/', views_bloques.desactivar, name='bloque_desactivar'),
    path('bloques/<int:pk>/opciones/nueva/', views_bloques.opcion_crear, name='opcion_crear'),
    path('opciones/<int:pk>/editar/', views_bloques.opcion_editar, name='opcion_editar'),
    path('opciones/<int:pk>/estado/', views_bloques.opcion_estado, name='opcion_estado'),
]
