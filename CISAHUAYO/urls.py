from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static

from Alumnos.views import inicio
from CISAHUAYO.acceso import acceso, salir

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
    # Portales (cada uno con su propia sesión: CISAHUAYO/portales.py)
    path('portal/estudiantes/', include('PortalEstudiantes.urls')),
    path('portal/tutores/', include('PortalTutores.urls')),
]  # Para servir archivos multimedia en desarrollo
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
