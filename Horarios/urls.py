from django.urls import path

from . import views, views_semanas

app_name = 'horarios'

urlpatterns = [
    path('', views.horario_lista, name='lista'),
    path('grupo/<int:grupo_pk>/', views.horario_grupo, name='grupo'),
    path('grupo/<int:grupo_pk>/nuevo/', views.horario_crear, name='crear'),
    path('grupo/<int:grupo_pk>/copiar-semana/', views.copiar_semana, name='copiar_semana'),
    path('grado/<int:grado_pk>/', views.horario_grado, name='grado'),
    # Semanas A y B: modalidad por nivel y ciclo, y excepciones de semana
    path('semanas/', views_semanas.semanas, name='semanas'),
    path('semanas/modalidad/', views_semanas.modalidad, name='modalidad'),
    path('semanas/excepciones/', views_semanas.excepcion, name='excepcion'),
    path('semanas/excepciones/<int:pk>/quitar/', views_semanas.excepcion_eliminar, name='excepcion_eliminar'),
    path('<int:pk>/editar/', views.horario_editar, name='editar'),
    path('<int:pk>/eliminar/', views.horario_eliminar, name='eliminar'),
    path('recesos/nuevo/', views.recreo_crear, name='recreo_crear'),
    path('recesos/<int:pk>/editar/', views.recreo_editar, name='recreo_editar'),
    path('recesos/<int:pk>/eliminar/', views.recreo_eliminar, name='recreo_eliminar'),
]
