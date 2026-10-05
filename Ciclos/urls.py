from django.urls import path

from . import views

app_name = 'ciclos'

urlpatterns = [
    path('', views.ciclo_lista, name='lista'),
    path('nuevo/', views.ciclo_crear, name='crear'),
    path('<int:pk>/', views.ciclo_detalle, name='detalle'),
    path('<int:pk>/editar/', views.ciclo_editar, name='editar'),
    path('<int:pk>/actual/', views.ciclo_establecer_actual, name='establecer_actual'),
    path('<int:pk>/cerrar/', views.ciclo_cerrar, name='cerrar'),
]
