from django.urls import path

from . import views

app_name = 'grados'

urlpatterns = [
    path('', views.grado_lista, name='lista'),
    path('nuevo/', views.grado_crear, name='crear'),
    path('<int:pk>/', views.grado_detalle, name='detalle'),
    path('<int:pk>/editar/', views.grado_editar, name='editar'),
    path('<int:pk>/baja/', views.grado_baja, name='baja'),
    path('<int:pk>/reactivar/', views.grado_reactivar, name='reactivar'),
    path('<int:pk>/exportar/', views.grado_exportar, name='exportar'),
]
