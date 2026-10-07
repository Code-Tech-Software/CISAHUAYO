from django.urls import path

from . import views

app_name = 'alumnos'

urlpatterns = [
    path('', views.alumno_lista, name='lista'),
    path('nuevo/', views.alumno_crear, name='crear'),
    path('exportar/', views.alumno_exportar, name='exportar'),
    path('importar/', views.alumno_importar, name='importar'),
    path('importar/plantilla/', views.alumno_importar_plantilla, name='importar_plantilla'),
    path('importar/credenciales/', views.alumno_importar_credenciales, name='importar_credenciales'),
    path('buscar/', views.alumno_buscar, name='buscar'),
    path('tutores/buscar/', views.tutor_buscar, name='tutor_buscar'),
    path('<int:pk>/', views.alumno_detalle, name='detalle'),
    path('<int:pk>/editar/', views.alumno_editar, name='editar'),
    path('<int:pk>/estatus/', views.alumno_estatus, name='estatus'),
    path('<int:pk>/baja/', views.alumno_baja, name='baja'),
    path('<int:pk>/reactivar/', views.alumno_reactivar, name='reactivar'),
    path('<int:pk>/contrasena/', views.alumno_contrasena, name='contrasena'),
    path('<int:pk>/inscribir/', views.alumno_inscribir, name='inscribir'),
]
