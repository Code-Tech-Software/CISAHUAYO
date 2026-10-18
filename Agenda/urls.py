from django.urls import path

from . import views


def rutas_de_portal(tipo):
    """El calendario en un portal (solo consulta: los eventos de los niveles de sus estudiantes y de todo el colegio)."""
    envolver = views.para_portal(tipo)
    return [
        path('', envolver(views.portal_calendario), name='calendario'),
    ]


app_name = 'agenda'
urlpatterns = [
    path('', views.calendario_vista, name='calendario'),
    path('nuevo/', views.crear, name='crear'),
    path('<int:pk>/editar/', views.editar, name='editar'),
    path('<int:pk>/eliminar/', views.eliminar, name='eliminar'),
]
