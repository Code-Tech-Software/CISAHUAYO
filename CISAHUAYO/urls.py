from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static

from Panel.views import inicio
from CISAHUAYO.acceso import acceso, salir
from Mensajes import views as mensajes_views
from Mensajes.views_ajustes import ajustes as mensajes_ajustes

urlpatterns = [
    path('', inicio, name='inicio'),
    # Inicio y cierre de sesión del sistema (cualquier cuenta activa, no solo staff). El inicio conserva la ruta del
    # admin (reverse('admin:login') no cambia) y va antes que admin/ para tomar su lugar
    path('admin/login/', acceso, name='login'),
    path('salir/', salir, name='logout'),
    path('admin/', admin.site.urls),
    path('usuarios/', include('Usuarios.urls')),
    path('roles/', include('Roles.urls')),
    path('cuenta/', include('Usuarios.urls_cuenta')),
    path('alumnos/', include('Alumnos.urls')),
    path('tutores/', include('Tutores.urls')),
    path('ciclos/', include('Ciclos.urls')),
    path('grados/', include('Grados.urls')),
    path('inscripciones/', include('Inscripciones.urls')),
    path('materias/', include('Materias.urls')),
    path('horarios/', include('Horarios.urls')),
    path('profesores/', include('Profesores.urls')),
    path('asignaciones/', include('Asignaciones.urls')),
    # Asistencias (asistencias/…) y su configuración en Ajustes (ajustes/asistencia/…)
    path('', include('Asistencias.urls')),
    path('periodos/', include('Periodos.urls')),
    path('grupos/', include('Grupos.urls')),
    # Conducta: el registro y sus reportes (conducta/…) y su configuración en Ajustes (ajustes/conducta/…)
    path('', include('Conducta.urls')),
    path('ajustes/', include('Ajustes.urls')),
    path('prefectura/', include('Prefectura.urls')),
    # Calificaciones (calificaciones/…) y su configuración en Ajustes (ajustes/calificaciones/…)
    path('', include('Calificaciones.urls')),
    # Bitácoras por grupo: observaciones informativas de cada clase (Bitacoras/alcance.py)
    path('bitacoras/', include('Bitacoras.urls')),
    # Mensajería interna (también en los portales: PortalEstudiantes/urls.py, PortalTutores/urls.py), su horario de
    # atención en Ajustes (ajustes/mensajes/) y, en la raíz, lo de las notificaciones push (Mensajes/push.py)
    path('mensajes/', include('Mensajes.urls')),
    path('ajustes/mensajes/', mensajes_ajustes, name='ajustes_mensajes'),
    path('sw.js', mensajes_views.service_worker, name='service_worker'),
    path('manifest.webmanifest', mensajes_views.manifiesto, name='manifiesto'),
    # Comunicados con seguimiento de lectura (también en los portales: PortalEstudiantes/urls.py, PortalTutores/urls.py)
    path('comunicados/', include('Comunicados.urls')),
    # Retiros anticipados: gestión (retiros/…) y motivos en Ajustes (ajustes/retiros/…); el aviso del tutor está en su portal
    path('', include('Retiros.urls')),
    # Panel de control: la lista completa de estudiantes en seguimiento (panel/…) y sus criterios en Ajustes (ajustes/seguimiento/)
    path('', include('Panel.urls')),
    # Agenda / Calendario (agenda/…; en los portales: PortalEstudiantes/urls.py, PortalTutores/urls.py)
    path('agenda/', include('Agenda.urls')),
    # Reuniones con familias: gestión (reuniones/…) y configuración en Ajustes (ajustes/reuniones/…); el tutor las ve en su portal
    path('', include('Reuniones.urls')),
    # Portales (cada uno con su propia sesión: CISAHUAYO/portales.py)
    path('portal/estudiantes/', include('PortalEstudiantes.urls')),
    path('portal/tutores/', include('PortalTutores.urls')),
]  # Para servir archivos multimedia en desarrollo
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
