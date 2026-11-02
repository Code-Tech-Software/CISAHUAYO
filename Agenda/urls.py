from django.urls import path

from . import views


def rutas_de_portal(tipo):
    """El calendario en un portal (solo consulta: los eventos de los niveles de sus estudiantes y de todo el colegio; las
    familias, además, confirman su asistencia cuando el evento lo pide)."""
    envolver = views.para_portal(tipo)
    return [
        path('', envolver(views.portal_calendario), name='calendario'),
        path('<int:pk>/calendario.ics', envolver(views.portal_evento_ics), name='evento_ics'),
        path('<int:pk>/confirmar/', envolver(views.portal_confirmar), name='confirmar'),
        path('archivos/<int:pk>/', envolver(views.portal_adjunto), name='adjunto'),
        path('suscripcion/', envolver(views.portal_suscripcion), name='suscripcion'),
        path('imprimir/', envolver(views.portal_imprimir), name='imprimir'),
    ]


app_name = 'agenda'
urlpatterns = [
    path('', views.calendario_vista, name='calendario'),
    path('nuevo/', views.crear, name='crear'),
    path('<int:pk>/editar/', views.editar, name='editar'),
    path('<int:pk>/cancelar/', views.cancelar, name='cancelar'),
    path('<int:pk>/reactivar/', views.reactivar, name='reactivar'),
    path('<int:pk>/eliminar/', views.eliminar, name='eliminar'),
    path('<int:pk>/calendario.ics', views.evento_ics, name='evento_ics'),
    path('archivos/<int:pk>/', views.adjunto, name='adjunto'),
    path('suscripcion/', views.suscripcion, name='suscripcion'),
    # El calendario del teléfono lo lee sin sesión: lo protege el enlace secreto (Agenda/models.SuscripcionCalendario)
    path('suscripcion/<str:token>.ics', views.suscripcion_ics, name='suscripcion_ics'),
    path('imprimir/', views.imprimir, name='imprimir'),
]
