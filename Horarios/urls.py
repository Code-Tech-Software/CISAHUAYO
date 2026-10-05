from django.urls import path

from . import views

app_name = 'horarios'

urlpatterns = [
    path('', views.horario_lista, name='lista'),
    path('grado/<int:grado_pk>/', views.horario_grado, name='grado'),
    path('grado/<int:grado_pk>/nuevo/', views.horario_crear, name='crear'),
    path('<int:pk>/editar/', views.horario_editar, name='editar'),
    path('<int:pk>/eliminar/', views.horario_eliminar, name='eliminar'),
]
