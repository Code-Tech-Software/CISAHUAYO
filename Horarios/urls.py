from django.urls import path

from . import views

app_name = 'horarios'

urlpatterns = [
    path('', views.horario_lista, name='lista'),
    path('grado/<int:grado_pk>/', views.horario_grado, name='grado'),
    path('grado/<int:grado_pk>/nuevo/', views.horario_crear, name='crear'),
    path('<int:pk>/editar/', views.horario_editar, name='editar'),
    path('<int:pk>/eliminar/', views.horario_eliminar, name='eliminar'),
    path('recreos/nuevo/', views.recreo_crear, name='recreo_crear'),
    path('recreos/<int:pk>/editar/', views.recreo_editar, name='recreo_editar'),
    path('recreos/<int:pk>/eliminar/', views.recreo_eliminar, name='recreo_eliminar'),
]
