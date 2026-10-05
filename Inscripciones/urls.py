from django.urls import path

from . import views

app_name = 'inscripciones'

urlpatterns = [
    path('', views.inscripcion_lista, name='lista'),
    path('nueva/', views.inscripcion_crear, name='crear'),
    path('exportar/', views.inscripcion_exportar, name='exportar'),
    path('promocion/', views.inscripcion_promocion, name='promocion'),
    path('<int:pk>/editar/', views.inscripcion_editar, name='editar'),
    path('<int:pk>/baja/', views.inscripcion_baja, name='baja'),
    path('<int:pk>/reactivar/', views.inscripcion_reactivar, name='reactivar'),
]
