from django.urls import path

from . import views

app_name = 'horarios'

urlpatterns = [
    path('', views.horario_lista, name='lista'),
    path('grupo/<int:grupo_pk>/', views.horario_grupo, name='grupo'),
    path('grupo/<int:grupo_pk>/nuevo/', views.horario_crear, name='crear'),
    path('grado/<int:grado_pk>/', views.horario_grado, name='grado'),
    path('<int:pk>/editar/', views.horario_editar, name='editar'),
    path('<int:pk>/eliminar/', views.horario_eliminar, name='eliminar'),
    path('recesos/nuevo/', views.recreo_crear, name='recreo_crear'),
    path('recesos/<int:pk>/editar/', views.recreo_editar, name='recreo_editar'),
    path('recesos/<int:pk>/eliminar/', views.recreo_eliminar, name='recreo_eliminar'),
]
