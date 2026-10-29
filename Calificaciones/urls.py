from django.urls import path

from . import views, views_configuracion

app_name = 'calificaciones'

urlpatterns = [
    # Gestión académica › Calificaciones: captura, consulta y concentrado
    path('calificaciones/', views.inicio, name='inicio'),
    path('calificaciones/actas/<int:pk>/guardar/', views.guardar, name='guardar'),
    path('calificaciones/actas/<int:pk>/actividades/nueva/', views.actividad_crear, name='actividad_crear'),
    path('calificaciones/actividades/<int:pk>/editar/', views.actividad_editar, name='actividad_editar'),
    path('calificaciones/actividades/<int:pk>/quitar/', views.actividad_quitar, name='actividad_quitar'),
    path('calificaciones/actas/<int:pk>/cerrar/', views.cerrar, name='cerrar'),
    path('calificaciones/actas/<int:pk>/reabrir/', views.reabrir, name='reabrir'),
    path('calificaciones/actas/<int:pk>/historial/', views.historial, name='historial'),
    path('calificaciones/actas/<int:pk>/concentrado/', views.concentrado_imprimir, name='concentrado_imprimir'),
    path('calificaciones/actas/<int:pk>/concentrado/excel/', views.concentrado_excel, name='concentrado_excel'),
    # Bachillerato por semestres: exámenes del semestre y su hoja (para imprimir y en Excel)
    path('calificaciones/semestre/<int:pk>/guardar/', views.semestre_guardar, name='semestre_guardar'),
    path('calificaciones/semestre/<int:pk>/imprimir/', views.semestre_imprimir, name='semestre_imprimir'),
    path('calificaciones/semestre/<int:pk>/excel/', views.semestre_excel, name='semestre_excel'),

    # Sistema › Ajustes › Calificaciones: rubros, porcentajes y reglas de cada materia
    path('ajustes/calificaciones/', views_configuracion.configuracion, name='configuracion'),
    path('ajustes/calificaciones/materias/<int:pk>/', views_configuracion.configuracion_materia, name='configuracion_materia'),
    path('ajustes/calificaciones/materias/<int:pk>/crear/', views_configuracion.configuracion_crear, name='configuracion_crear'),
    path('ajustes/calificaciones/<int:pk>/version/', views_configuracion.configuracion_version, name='configuracion_version'),
    path('ajustes/calificaciones/copiar/', views_configuracion.configuracion_copiar, name='configuracion_copiar'),
]
