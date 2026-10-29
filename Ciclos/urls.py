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
    path('<int:pk>/borrar/', views.ciclo_eliminar, name='eliminar'),
    path('dias-sin-clases/', views.dias_sin_clases, name='dias_sin_clases'),
    # Bachillerato por semestres (2026-10-28)
    path('<int:pk>/semestres/', views.semestres_fechas, name='semestres'),
    path('semestres/<int:pk>/', views.semestre_detalle, name='semestre'),
    path('semestres/<int:pk>/abrir/', views.semestre_abrir, name='semestre_abrir'),
    path('semestres/<int:pk>/cerrar/', views.semestre_cerrar, name='semestre_cerrar'),
    path('semestres/<int:pk>/reabrir/', views.semestre_reabrir, name='semestre_reabrir'),
]
