from django.urls import path

from . import views

app_name = 'usuarios'

urlpatterns = [
    path('', views.usuario_lista, name='lista'),
    path('nuevo/', views.usuario_crear, name='crear'),
    path('<int:pk>/', views.usuario_detalle, name='detalle'),
    path('<int:pk>/editar/', views.usuario_editar, name='editar'),
    path('<int:pk>/baja/', views.usuario_baja, name='baja'),
    path('<int:pk>/reactivar/', views.usuario_reactivar, name='reactivar'),
    path('<int:pk>/restablecer/', views.usuario_restablecer, name='restablecer'),
]
