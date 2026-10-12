from django.urls import path

from . import views

app_name = 'grupos'

urlpatterns = [
    path('', views.grupo_lista, name='lista'),
    path('<int:pk>/', views.grupo_detalle, name='detalle'),
    path('nombres/nuevo/', views.nombre_crear, name='nombre_crear'),
    path('nombres/<int:pk>/editar/', views.nombre_editar, name='nombre_editar'),
    path('nombres/<int:pk>/baja/', views.nombre_baja, name='nombre_baja'),
    path('nombres/<int:pk>/reactivar/', views.nombre_reactivar, name='nombre_reactivar'),
]
