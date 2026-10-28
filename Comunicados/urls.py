"""Las rutas de los comunicados.
- En el sistema (/comunicados/, espacio «comunicados»): cada vista exige sus permisos (Comunicados/alcance.py).
- En los portales (/portal/estudiantes/comunicados/ y /portal/tutores/comunicados/, espacios
  «portal_estudiantes:comunicados» y «portal_tutores:comunicados»): lo recibido, con la sesión de ese portal (ver
  PortalEstudiantes/urls.py y PortalTutores/urls.py).
"""
from django.urls import path

from . import views


def rutas_de_portal(tipo):
    envolver = views.para_portal(tipo)
    return [
        path('', envolver(views.portal_inicio), name='inicio'),
        path('resumen/', envolver(views.portal_resumen), name='resumen'),
        path('<int:pk>/', envolver(views.portal_recibido), name='recibido'),
        path('archivos/<int:pk>/', envolver(views.portal_adjunto), name='adjunto'),
        path('imagenes/<int:pk>/', envolver(views.portal_imagen), name='imagen'),
        path('<int:pk>/responder/', envolver(views.portal_responder), name='responder'),
        path('<int:pk>/calendario.ics', envolver(views.portal_calendario), name='calendario'),
    ]


app_name = 'comunicados'
urlpatterns = [
    path('', views.inicio, name='inicio'),
    path('nuevo/', views.crear, name='crear'),
    path('destinatarios/', views.destinatarios, name='destinatarios'),
    path('eliminar/', views.eliminar_varios, name='eliminar_varios'),
    path('recibidos/<int:pk>/', views.recibido, name='recibido'),
    path('resumen/', views.resumen, name='resumen'),
    path('archivos/<int:pk>/', views.adjunto, name='adjunto'),
    path('imagenes/', views.imagen_subir, name='imagen_subir'),
    path('imagenes/<int:pk>/', views.imagen, name='imagen'),
    path('recibidos/<int:pk>/responder/', views.responder, name='responder'),
    path('<int:pk>/', views.detalle, name='detalle'),
    path('<int:pk>/editar/', views.editar, name='editar'),
    path('<int:pk>/recordar/', views.recordar, name='recordar'),
    path('<int:pk>/exportar/', views.exportar, name='exportar'),
    path('<int:pk>/calendario.ics', views.calendario, name='calendario'),
    path('<int:pk>/eliminar/', views.eliminar, name='eliminar'),
]
