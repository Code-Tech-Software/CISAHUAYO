from django.urls import path

from . import views

app_name = 'tutores'

urlpatterns = [
    path('', views.tutor_lista, name='lista'),
    path('nuevo/', views.tutor_crear, name='crear'),
    path('exportar/', views.tutor_exportar, name='exportar'),
    path('<int:pk>/', views.tutor_detalle, name='detalle'),
    path('<int:pk>/editar/', views.tutor_editar, name='editar'),
    path('<int:pk>/baja/', views.tutor_baja, name='baja'),
    path('<int:pk>/reactivar/', views.tutor_reactivar, name='reactivar'),
    path('<int:pk>/vincular/', views.tutor_vincular, name='vincular'),
    path('<int:pk>/desvincular/', views.tutor_desvincular, name='desvincular'),
]
