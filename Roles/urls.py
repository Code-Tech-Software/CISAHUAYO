from django.urls import path

from . import views

app_name = 'roles'

urlpatterns = [
    path('', views.rol_lista, name='lista'),
    path('nuevo/', views.rol_crear, name='crear'),
    path('<int:pk>/', views.rol_detalle, name='detalle'),
    path('<int:pk>/editar/', views.rol_editar, name='editar'),
    path('<int:pk>/copiar/', views.rol_copiar, name='copiar'),
    path('<int:pk>/baja/', views.rol_baja, name='baja'),
    path('<int:pk>/reactivar/', views.rol_reactivar, name='reactivar'),
]
