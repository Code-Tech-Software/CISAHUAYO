from django.urls import path

from . import views

app_name = 'materias'

urlpatterns = [
    path('', views.materia_lista, name='lista'),
    path('nueva/', views.materia_crear, name='crear'),
    path('clave/', views.materia_clave, name='clave'),
    path('exportar/', views.materia_exportar, name='exportar'),
    path('asignar/', views.asignar, name='asignar'),
    path('copiar/', views.copiar_plan, name='copiar'),
    path('asignaciones/<int:pk>/quitar/', views.asignacion_quitar, name='quitar'),
    path('asignaciones/<int:pk>/reactivar/', views.asignacion_reactivar, name='reactivar_asignacion'),
    path('<int:pk>/', views.materia_detalle, name='detalle'),
    path('<int:pk>/editar/', views.materia_editar, name='editar'),
    path('<int:pk>/habilitar/', views.materia_habilitar, name='habilitar'),
    path('<int:pk>/deshabilitar/', views.materia_deshabilitar, name='deshabilitar'),
    path('<int:pk>/baja/', views.materia_baja, name='baja'),
    path('<int:pk>/reactivar/', views.materia_reactivar, name='reactivar'),
]
