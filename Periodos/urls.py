from django.urls import path

from . import views

app_name = 'periodos'

urlpatterns = [
    path('', views.periodo_lista, name='lista'),
    path('nuevo/', views.periodo_crear, name='crear'),
    path('<int:pk>/editar/', views.periodo_editar, name='editar'),
    path('<int:pk>/abrir/', views.periodo_abrir, name='abrir'),
    path('<int:pk>/cerrar/', views.periodo_cerrar, name='cerrar'),
    path('<int:pk>/por-fechas/', views.periodo_por_fechas, name='por_fechas'),
    path('<int:pk>/eliminar/', views.periodo_eliminar, name='eliminar'),
]
