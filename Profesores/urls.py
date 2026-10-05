from django.urls import path

from . import views

app_name = 'profesores'

urlpatterns = [
    path('', views.profesor_lista, name='lista'),
    path('nuevo/', views.profesor_crear, name='crear'),
    path('exportar/', views.profesor_exportar, name='exportar'),
    path('asignar/', views.asignar, name='asignar'),
    path('<int:pk>/', views.profesor_detalle, name='detalle'),
    path('<int:pk>/editar/', views.profesor_editar, name='editar'),
    path('<int:pk>/baja/', views.profesor_baja, name='baja'),
    path('<int:pk>/reactivar/', views.profesor_reactivar, name='reactivar'),
]
