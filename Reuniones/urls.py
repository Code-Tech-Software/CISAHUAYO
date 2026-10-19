from django.urls import path

from . import views, views_portal

app_name = 'reuniones'

# Gestión (reuniones/…) y configuración en Ajustes (ajustes/reuniones/…): se incluye en la raíz (CISAHUAYO/urls.py)
urlpatterns = [
    path('reuniones/', views.inicio, name='inicio'),
    path('reuniones/lista/', views.lista, name='lista'),
    path('reuniones/agenda/', views.agenda, name='agenda'),
    path('reuniones/compromisos/', views.compromisos, name='compromisos'),
    path('reuniones/resumen/', views.resumen, name='resumen'),
    path('reuniones/nueva/', views.nueva, name='nueva'),
    path('reuniones/estudiante/<int:pk>/', views.estudiante, name='estudiante'),
    path('reuniones/<int:pk>/', views.detalle, name='detalle'),
    path('reuniones/<int:pk>/participantes/', views.participantes, name='participantes'),
    path('reuniones/<int:pk>/programar/', views.programar, name='programar'),
    path('reuniones/<int:pk>/reprogramar/', views.reprogramar, name='reprogramar'),
    path('reuniones/<int:pk>/confirmar-tutor/', views.confirmar_tutor, name='confirmar_tutor'),
    path('reuniones/<int:pk>/aviso/', views.aviso, name='aviso'),
    path('reuniones/<int:pk>/disponibilidad/', views.disponibilidad, name='disponibilidad'),
    path('reuniones/<int:pk>/disponibilidad/<int:participante>/', views.disponibilidad, name='disponibilidad_de'),
    path('reuniones/<int:pk>/sustituto/', views.sustituto, name='sustituto'),
    path('reuniones/<int:pk>/iniciar/', views.iniciar, name='iniciar'),
    path('reuniones/<int:pk>/minuta/registrar/', views.finalizar, name='finalizar'),
    path('reuniones/<int:pk>/minuta/', views.minuta, name='minuta'),
    path('reuniones/<int:pk>/inasistencia/', views.inasistencia, name='inasistencia'),
    path('reuniones/<int:pk>/cancelar/', views.cancelar, name='cancelar'),
    path('reuniones/<int:pk>/siguiente/', views.siguiente, name='siguiente'),
    path('reuniones/<int:pk>/acuerdos/nuevo/', views.acuerdo, name='acuerdo_nuevo'),
    path('reuniones/<int:pk>/acuerdos/<int:acuerdo_pk>/', views.acuerdo, name='acuerdo_editar'),
    path('reuniones/<int:pk>/documentos/', views.documentos, name='documentos'),
    path('reuniones/acuerdos/<int:pk>/seguimiento/', views.seguimiento, name='seguimiento'),
    path('reuniones/acuerdos/evidencia/<int:pk>/', views.evidencia, name='evidencia'),
    path('reuniones/documentos/<int:pk>/', views.documento, name='documento'),
    path('ajustes/reuniones/', views.ajustes, name='ajustes'),
    path('ajustes/reuniones/motivos/nuevo/', views.motivo, name='motivo_crear'),
    path('ajustes/reuniones/motivos/<int:pk>/', views.motivo, name='motivo_editar'),
    path('ajustes/reuniones/salas/nueva/', views.sala, name='sala_crear'),
    path('ajustes/reuniones/salas/<int:pk>/', views.sala, name='sala_editar'),
]


def rutas_de_portal():
    """Las del portal de tutores (PortalTutores/urls.py las pone en portal/tutores/reuniones/)."""
    return [
        path('', views_portal.lista, name='lista'),
        path('resumen/', views_portal.resumen, name='resumen'),
        path('<int:pk>/', views_portal.detalle, name='detalle'),
        path('<int:pk>/confirmar/', views_portal.confirmar, name='confirmar'),
        path('<int:pk>/minuta/', views_portal.minuta, name='minuta'),
        path('documentos/<int:pk>/', views_portal.documento, name='documento'),
    ]
