from django.urls import path

from . import views, views_asistencia, views_reportes

app_name = 'prefectura'

urlpatterns = [
    path('', views.inicio, name='inicio'),
    path('estudiantes/', views.estudiantes, name='estudiantes'),
    path('estudiantes/<int:pk>/', views.estudiante, name='estudiante'),
    path('seguimiento/', views.seguimiento, name='seguimiento'),

    # Asistencia: la matriz por materia (consulta), faltas y retardos, accesos y justificaciones
    path('asistencia/', views_asistencia.matriz, name='asistencia'),
    path('asistencia/reporte/', views_asistencia.matriz_reporte, name='asistencia_reporte'),
    path('asistencia/registros/', views_asistencia.registros, name='asistencia_registros'),
    path('accesos/', views_asistencia.accesos, name='accesos'),
    path('accesos/nuevo/', views_asistencia.acceso_crear, name='acceso_crear'),
    path('accesos/<int:pk>/', views_asistencia.acceso, name='acceso'),
    path('accesos/<int:pk>/corregir/', views_asistencia.acceso_corregir, name='acceso_corregir'),
    path('accesos/<int:pk>/anular/', views_asistencia.acceso_anular, name='acceso_anular'),
    path('justificaciones/', views_asistencia.justificaciones, name='justificaciones'),
    path('justificaciones/nueva/', views_asistencia.justificar, name='justificar'),
    path('justificaciones/previa/', views_asistencia.justificar_previa, name='justificar_previa'),
    path('justificaciones/<int:pk>/revocar/', views_asistencia.justificacion_revocar, name='justificacion_revocar'),

    # Reportes
    path('reportes/', views_reportes.reportes_vista, name='reportes'),
    path('reportes/imprimir/', views_reportes.reporte_imprimir, name='reporte_imprimir'),
    path('reportes/excel/', views_reportes.reporte_excel, name='reporte_excel'),
]
