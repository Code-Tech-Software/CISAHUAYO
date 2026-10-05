from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static

from Alumnos.views import inicio
from CISAHUAYO.acceso import acceso

urlpatterns = [
    path('', inicio, name='inicio'),
    # Misma ruta que la del admin (reverse('admin:login') no cambia), pero al entrar lleva al sistema; va antes que admin/
    path('admin/login/', acceso),
    path('admin/', admin.site.urls),
    path('alumnos/', include('Alumnos.urls')),
    path('tutores/', include('Tutores.urls')),
    path('ciclos/', include('Ciclos.urls')),
    path('grados/', include('Grados.urls')),
    path('inscripciones/', include('Inscripciones.urls')),
    path('materias/', include('Materias.urls')),
    path('horarios/', include('Horarios.urls')),
    path('profesores/', include('Profesores.urls')),
    path('asistencias/', include('Asistencias.urls')),
]  # Para servir archivos multimedia en desarrollo
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
