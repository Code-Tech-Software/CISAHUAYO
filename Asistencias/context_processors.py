"""Los avisos de asistencia en todas las páginas del portal de tutores: la sección «Asistencia» de la campana (contador
y lista). Los genera el cierre del día (Alumnos/asistencias.avisar_a_tutores); aquí solo se leen. Se calcula solo si
la plantilla lo usa."""
from django.db import DatabaseError
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.functional import SimpleLazyObject

from Alumnos.models import NotificacionAsistencia
from CISAHUAYO import portales

EN_LA_CAMPANA = 5


def _hora(momento):
    momento = timezone.localtime(momento)
    return momento.strftime('%H:%M') if momento.date() == timezone.localdate() else momento.strftime('%d/%m')


def pendientes_de(tutor):
    """Los avisos de asistencia sin leer de un tutor."""
    return NotificacionAsistencia.objects.filter(tutor=tutor, leida=False)


def avisos_asistencia(request):
    def calcular():
        try:
            if getattr(request, 'cuenta_portal_tipo', None) != portales.TUTOR:
                return {'activa': False}
            pendientes = pendientes_de(request.cuenta_portal)
            avisos = [
                {'id': aviso.pk, 'titulo': aviso.titulo, 'texto': aviso.texto, 'hora': _hora(aviso.creada),
                 'url': reverse('portal_tutores:aviso_asistencia', args=[aviso.pk])}
                for aviso in pendientes.order_by('-creada', '-pk')[:EN_LA_CAMPANA]
            ]
            total = pendientes.count()
        except (DatabaseError, NoReverseMatch):   # sin la migración o sin las rutas: el resto sigue funcionando
            return {'activa': False}
        return {'activa': True, 'pendientes': total, 'avisos': avisos, 'mas': max(total - len(avisos), 0)}

    return {'avisos_asistencia': SimpleLazyObject(calcular)}
