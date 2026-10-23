from django.urls import path

from . import views, views_bitacora

app_name = 'usuarios'

urlpatterns = [
    path('', views.usuario_lista, name='lista'),
    path('bitacora/', views_bitacora.bitacora, name='bitacora'),
    path('nuevo/', views.usuario_crear, name='crear'),
    path('<int:pk>/', views.usuario_detalle, name='detalle'),
    path('<int:pk>/editar/', views.usuario_editar, name='editar'),
    path('<int:pk>/baja/', views.usuario_baja, name='baja'),
    path('<int:pk>/reactivar/', views.usuario_reactivar, name='reactivar'),
    path('<int:pk>/restablecer/', views.usuario_restablecer, name='restablecer'),
    path('<int:pk>/alcance/', views.usuario_alcance, name='alcance'),
    path('<int:pk>/direccion/', views.usuario_direccion, name='direccion'),
    path('<int:pk>/coordinacion/', views.usuario_coordinacion, name='coordinacion'),
    path('<int:pk>/comunicados/', views.usuario_comunicados, name='comunicados'),
    path('<int:pk>/retiros/', views.usuario_retiros, name='retiros'),
]
