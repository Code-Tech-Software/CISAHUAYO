from django.urls import path

from . import views, views_docente, views_materias

app_name = 'asistencias'

urlpatterns = [
    path('asistencias/', views.inicio, name='inicio'),
    path('asistencias/cerrar/', views.cerrar, name='cerrar'),

    # Pantalla de la entrada
    path('asistencias/entrada/', views.kiosco, name='kiosco'),
    path('asistencias/entrada/registrar/', views.entrada_registrar, name='registrar_entrada'),
    path('asistencias/entrada/estado/', views.kiosco_estado, name='kiosco_estado'),

    # Asistencia general del día
    path('asistencias/dia/', views.dia, name='dia'),
    path('asistencias/dia/guardar/', views.dia_guardar, name='dia_guardar'),

    # Asistencia por materia (administración): la matriz de cualquier materia y justificar una falta con su comprobante
    path('asistencias/materias/', views_materias.materias, name='materias'),
    path('asistencias/materias/<int:pk>/guardar/', views_materias.materias_guardar, name='materias_guardar'),
    path('asistencias/materias/<int:pk>/justificar/', views_materias.materias_justificar, name='materias_justificar'),
    path('asistencias/materias/reporte/', views_materias.materias_reporte, name='materias_reporte'),

    # Asistencia para docentes: la matriz de sus materias en el periodo abierto
    path('asistencias/docente/', views_docente.docente, name='docente'),
    path('asistencias/docente/<int:pk>/guardar/', views_docente.docente_guardar, name='docente_guardar'),
    path('asistencias/docente/reporte/', views_docente.docente_reporte, name='docente_reporte'),

    # Justificaciones
    path('asistencias/justificaciones/', views.justificaciones, name='justificaciones'),
    path('asistencias/justificaciones/nueva/', views.justificacion_crear, name='justificacion_crear'),
    path('asistencias/justificaciones/materias/', views.justificacion_materias, name='justificacion_materias'),
    path('asistencias/justificaciones/<int:pk>/', views.justificacion_editar, name='justificacion_editar'),
    path('asistencias/justificaciones/<int:pk>/anular/', views.justificacion_anular, name='justificacion_anular'),
    path('asistencias/justificaciones/<int:pk>/reactivar/', views.justificacion_reactivar, name='justificacion_reactivar'),
    path('asistencias/justificaciones/<int:pk>/comprobante/', views.comprobante, name='comprobante'),

    # Reportes e historial
    path('asistencias/reporte/', views.reporte, name='reporte'),
    path('asistencias/reporte/exportar/', views.reporte_exportar, name='reporte_exportar'),
    path('asistencias/alumno/<int:pk>/', views.alumno, name='alumno'),

    # Ajustes › Asistencia (menú Sistema): reglas de la entrada, días sin clases y cierres
    path('ajustes/asistencia/', views.ajustes, name='ajustes'),
    path('ajustes/asistencia/dias/nuevo/', views.dia_sin_clases_crear, name='dia_sin_clases_crear'),
    path('ajustes/asistencia/dias/<int:pk>/eliminar/', views.dia_sin_clases_eliminar, name='dia_sin_clases_eliminar'),
]
