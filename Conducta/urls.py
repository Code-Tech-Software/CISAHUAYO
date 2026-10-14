from django.urls import path

from . import views, views_configuracion, views_reportes

app_name = 'conducta'

urlpatterns = [
    # Registro de conducta (Gestión académica)
    path('conducta/', views.lista, name='lista'),
    path('conducta/nuevo/', views.crear, name='crear'),
    path('conducta/pendientes/', views.pendientes, name='pendientes'),
    path('conducta/buscar/', views.buscar, name='buscar'),
    path('conducta/opciones/', views.opciones, name='opciones'),
    path('conducta/<int:pk>/', views.detalle, name='detalle'),
    path('conducta/<int:pk>/editar/', views.editar, name='editar'),
    path('conducta/<int:pk>/seguimiento/', views.seguimiento, name='seguimiento'),
    path('conducta/<int:pk>/anular/', views.anular, name='anular'),
    path('conducta/<int:pk>/evidencias/', views.evidencias_agregar, name='evidencias_agregar'),
    path('conducta/<int:pk>/contacto/', views.contacto_crear, name='contacto_crear'),
    path('conducta/evidencias/<int:pk>/', views.evidencia, name='evidencia'),
    path('conducta/evidencias/<int:pk>/quitar/', views.evidencia_quitar, name='evidencia_quitar'),
    path('conducta/contactos/<int:pk>/acuse/', views.acuse, name='acuse'),
    path('conducta/avisos/<int:pk>/revisar/', views.aviso_revisar, name='aviso_revisar'),
    path('conducta/<int:pk>/cita/', views.cita_crear, name='cita_crear'),
    path('conducta/citas/<int:pk>/', views.cita_actualizar, name='cita_actualizar'),
    path('conducta/<int:pk>/compromiso/', views.compromiso_crear, name='compromiso_crear'),
    path('conducta/compromisos/<int:pk>/', views.compromiso_resolver, name='compromiso_resolver'),

    # Solicitudes de aprobación (suspensiones y medidas)
    path('conducta/solicitudes/', views.solicitudes, name='solicitudes'),
    path('conducta/suspensiones/<int:pk>/resolver/', views.suspension_resolver, name='suspension_resolver'),
    path('conducta/suspensiones/<int:pk>/cancelar/', views.suspension_cancelar, name='suspension_cancelar'),
    path('conducta/medidas/<int:pk>/resolver/', views.medida_resolver, name='medida_resolver'),

    # Reportes de conducta (Gestión académica)
    path('conducta/reportes/', views_reportes.reportes_vista, name='reportes'),
    path('conducta/reportes/imprimir/', views_reportes.reporte_imprimir, name='reporte_imprimir'),
    path('conducta/reportes/excel/', views_reportes.reporte_excel, name='reporte_excel'),

    # Ajustes › Conducta: catálogos de cada nivel y aviso de reincidencia
    path('ajustes/conducta/', views_configuracion.configuracion, name='configuracion'),
    path('ajustes/conducta/reincidencia/', views_configuracion.reincidencia, name='reincidencia'),
    path('ajustes/conducta/sugerencias/', views_configuracion.sugerencias, name='sugerencias'),
]

for clave, catalogo in views_configuracion.CATALOGOS.items():
    crear, editar, estado, eliminar = views_configuracion.VISTAS[clave]
    urlpatterns += [
        path(f'ajustes/conducta/{clave}/nuevo/', crear, name=f'{catalogo.nombre}_crear'),
        path(f'ajustes/conducta/{clave}/<int:pk>/', editar, name=f'{catalogo.nombre}_editar'),
        path(f'ajustes/conducta/{clave}/<int:pk>/estado/', estado, name=f'{catalogo.nombre}_estado'),
        path(f'ajustes/conducta/{clave}/<int:pk>/eliminar/', eliminar, name=f'{catalogo.nombre}_eliminar'),
    ]
