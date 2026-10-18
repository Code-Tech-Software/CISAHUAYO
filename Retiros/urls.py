from django.urls import path

from . import views, views_portal

app_name = 'retiros'

# Gestión (retiros/…) y configuración en Ajustes (ajustes/retiros/…): se incluye en la raíz (CISAHUAYO/urls.py)
urlpatterns = [
    path('retiros/', views.lista, name='lista'),
    path('retiros/resumen/', views.resumen, name='resumen'),
    path('retiros/<int:pk>/', views.detalle, name='detalle'),
    path('retiros/<int:pk>/cancelar/', views.cancelar, name='cancelar'),
    path('retiros/<int:pk>/nota/', views.nota, name='nota'),
    path('retiros/estudiante/<int:pk>/confirmar/', views.confirmar, name='confirmar'),
    path('retiros/estudiante/<int:pk>/corregir/', views.corregir, name='corregir'),
    path('ajustes/retiros/', views.motivos, name='motivos'),
    path('ajustes/retiros/nuevo/', views.motivo_crear, name='motivo_crear'),
    path('ajustes/retiros/<int:pk>/editar/', views.motivo_editar, name='motivo_editar'),
    path('ajustes/retiros/<int:pk>/activo/', views.motivo_activo, name='motivo_activo'),
    path('ajustes/retiros/<int:pk>/eliminar/', views.motivo_eliminar, name='motivo_eliminar'),
]


def rutas_de_portal():
    """Las del portal de tutores (PortalTutores/urls.py las pone en portal/tutores/retiros/)."""
    return [
        path('', views_portal.lista, name='lista'),
        path('nuevo/', views_portal.crear, name='crear'),
        path('resumen/', views_portal.resumen, name='resumen'),
        path('<int:pk>/', views_portal.detalle, name='detalle'),
        path('<int:pk>/cancelar/', views_portal.cancelar, name='cancelar'),
    ]
