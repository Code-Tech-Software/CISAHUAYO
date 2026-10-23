"""Las rutas de la mensajería. Las mismas vistas se montan tres veces, cada una con su protección:
- en el sistema (/mensajes/, espacio «mensajes»): usuarios con Mensajes.usar o Mensajes.contactar_familias;
- en los portales (/portal/estudiantes/mensajes/ y /portal/tutores/mensajes/, espacios «portal_estudiantes:mensajes» y
  «portal_tutores:mensajes»): la sesión de ese portal (ver PortalEstudiantes/urls.py y PortalTutores/urls.py).
La moderación (/mensajes/moderacion/) existe solo en el sistema, con Mensajes.moderar.
"""
from django.urls import path

from . import views, views_moderacion


def rutas(envolver):
    return [
        path('', envolver(views.bandeja), name='inicio'),
        path('nueva/', envolver(views.nueva), name='nueva'),
        path('contactos/', envolver(views.contactos), name='contactos'),
        path('buscar/', envolver(views.buscar), name='buscar'),
        path('conversaciones/', envolver(views.conversaciones), name='conversaciones'),
        path('resumen/', envolver(views.resumen), name='resumen'),
        path('<int:pk>/', envolver(views.conversacion), name='conversacion'),
        path('<int:pk>/enviar/', envolver(views.enviar), name='enviar'),
        path('mensajes/<int:pk>/editar/', envolver(views.editar), name='editar'),
        path('<int:pk>/leida/', envolver(views.leida), name='leida'),
        path('<int:pk>/imagenes/', envolver(views.imagen_subir), name='imagen_subir'),
        path('<int:pk>/documentos/', envolver(views.documento_subir), name='documento_subir'),
        path('imagenes/<int:pk>/', envolver(views.imagen), name='imagen'),
        path('documentos/<int:pk>/', envolver(views.documento), name='documento'),
    ]


def rutas_de_portal(tipo):
    return rutas(views.para_portal(tipo))


app_name = 'mensajes'
urlpatterns = rutas(views.para_sistema) + [
    # Moderación (solo en el sistema, exclusiva del administrador: Mensajes/views_moderacion.py)
    path('moderacion/', views_moderacion.buscar, name='moderacion'),
    path('moderacion/conversaciones/<int:pk>/', views_moderacion.conversacion, name='moderacion_conversacion'),
    path('moderacion/mensajes/<int:pk>/retirar/', views_moderacion.retirar, name='moderacion_retirar'),
    path('moderacion/imagenes/<int:pk>/', views_moderacion.imagen, name='moderacion_imagen'),
]
