from django.urls import path

from . import views

app_name = 'tutores'

urlpatterns = [
    path('', views.tutor_lista, name='lista'),
    path('nuevo/', views.tutor_crear, name='crear'),
    path('exportar/', views.tutor_exportar, name='exportar'),
    path('importar/', views.tutor_importar, name='importar'),
    path('importar/plantilla/', views.tutor_importar_plantilla, name='importar_plantilla'),
    path('importar/credenciales/', views.tutor_importar_credenciales, name='importar_credenciales'),
    path('usuario/', views.tutor_usuario, name='usuario'),
    path('<int:pk>/', views.tutor_detalle, name='detalle'),
    path('<int:pk>/editar/', views.tutor_editar, name='editar'),
    path('<int:pk>/baja/', views.tutor_baja, name='baja'),
    path('<int:pk>/reactivar/', views.tutor_reactivar, name='reactivar'),
    path('<int:pk>/contrasena/', views.tutor_contrasena, name='contrasena'),
    path('<int:pk>/vincular/', views.tutor_vincular, name='vincular'),
    path('<int:pk>/desvincular/', views.tutor_desvincular, name='desvincular'),
]
