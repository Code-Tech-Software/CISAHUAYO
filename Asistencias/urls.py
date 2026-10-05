from django.urls import path

from . import views

app_name = 'asistencias'

urlpatterns = [
    path('', views.inicio, name='inicio'),
    path('cerrar/', views.cerrar, name='cerrar'),

    # Pantalla de la entrada
    path('entrada/', views.kiosco, name='kiosco'),
    path('entrada/registrar/', views.entrada_registrar, name='registrar_entrada'),
    path('entrada/estado/', views.kiosco_estado, name='kiosco_estado'),

    # Asistencia general del día
    path('dia/', views.dia, name='dia'),
    path('dia/guardar/', views.dia_guardar, name='dia_guardar'),

    # Pase de lista por materia
    path('clases/', views.clases, name='clases'),
    path('clases/<int:pk>/', views.clase, name='clase'),

    # Justificaciones
    path('justificaciones/', views.justificaciones, name='justificaciones'),
    path('justificaciones/nueva/', views.justificacion_crear, name='justificacion_crear'),
    path('justificaciones/materias/', views.justificacion_materias, name='justificacion_materias'),
    path('justificaciones/<int:pk>/', views.justificacion_editar, name='justificacion_editar'),
    path('justificaciones/<int:pk>/anular/', views.justificacion_anular, name='justificacion_anular'),
    path('justificaciones/<int:pk>/reactivar/', views.justificacion_reactivar, name='justificacion_reactivar'),

    # Reportes e historial
    path('reporte/', views.reporte, name='reporte'),
    path('reporte/exportar/', views.reporte_exportar, name='reporte_exportar'),
    path('alumno/<int:pk>/', views.alumno, name='alumno'),

    # Ajustes
    path('ajustes/', views.ajustes, name='ajustes'),
    path('ajustes/dias/nuevo/', views.dia_sin_clases_crear, name='dia_sin_clases_crear'),
    path('ajustes/dias/<int:pk>/eliminar/', views.dia_sin_clases_eliminar, name='dia_sin_clases_eliminar'),
]
