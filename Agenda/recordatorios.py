"""Recordatorios de los eventos importantes (pedido del 2026-10-27): un día antes, a quienes lo ven en su agenda.

- A cada persona le queda un aviso en la campana (`AvisoAgenda`, sección «Agenda») y, si activó las notificaciones de
  su navegador, le llega al teléfono (Mensajes/push.py). Cada evento se recuerda una sola vez (`recordatorio_en`).
- Quién lo ve: el personal con ese nivel (o todo el colegio) en su agenda, los tutores con hijos inscritos en ese nivel
  y los estudiantes de ese nivel (con acceso a su portal).
- Se generan cuando alguien abre la agenda o el inicio del sistema o de un portal (a lo más cada 5 minutos por
  proceso) o con `python manage.py recordatorios_de_agenda` (para un Cron). Un evento importante que se registra para
  hoy o mañana se recuerda en ese momento.
- El aviso queda visto al abrir la agenda; los de eventos que ya pasaron dejan de mostrarse.
"""
import logging
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from Alumnos.models import Inscripcion, TutorAlumno

from .models import COLEGIO, AvisoAgenda, EventoAgenda

registro = logging.getLogger(__name__)
LLAVE = 'agenda-recordatorios'
EN_LA_CAMPANA = 5


def audiencia(evento):
    """(ids de usuarios, de tutores, de estudiantes) que ven el evento en su agenda."""
    from . import alcance
    usuarios = [u.pk for u in get_user_model().objects.filter(is_active=True) if alcance.de_usuario(u).puede_ver(evento)]
    inscripciones = Inscripcion.objects.filter(activa=True, ciclo__activo=True, alumno__estatus='ACTIVO')
    if evento.alcance != COLEGIO:
        inscripciones = inscripciones.filter(grado__nivel=evento.alcance)
    alumnos = inscripciones.values('alumno')
    tutores = list(TutorAlumno.objects.filter(activo=True, alumno__in=alumnos, tutor__estatus='ACTIVO', tutor__acceso_portal=True)
                   .values_list('tutor_id', flat=True).distinct())
    estudiantes = list(inscripciones.filter(alumno__acceso_portal=True).values_list('alumno_id', flat=True).distinct())
    return usuarios, tutores, estudiantes


def _cuando(evento, hoy):
    return 'Hoy' if evento.fecha_inicio <= hoy else 'Mañana'


def _push(evento, usuarios, tutores, estudiantes, hoy):
    from Mensajes import push
    if not push.activas():
        return
    suscripciones = push.suscripciones_de(tutores=tutores, alumnos=estudiantes, usuarios=usuarios)
    if not suscripciones:
        return
    texto = ' · '.join(p for p in (evento.texto_de_horario, evento.lugar) if p)
    urls = {'usuario': reverse('agenda:calendario'), 'tutor': reverse('portal_tutores:agenda:calendario'),
            'alumno': reverse('portal_estudiantes:agenda:calendario')}
    envios = []
    for (clase, _), lista in suscripciones.items():
        carga = {'titulo': f'{_cuando(evento, hoy)}: {evento.titulo}', 'texto': texto, 'url': f'{urls[clase]}?evento={evento.pk}',
                 'etiqueta': f'agenda-{evento.pk}'}
        envios.extend((suscripcion, carga) for suscripcion in lista)
    push._en_segundo_plano(envios)


def generar(ahora=None):
    """Los recordatorios de los eventos importantes de hoy y mañana que todavía no se recordaron. Devuelve cuántos
    eventos recordó."""
    ahora = ahora or timezone.now()
    hoy = timezone.localdate(ahora)
    pendientes = EventoAgenda.objects.filter(importante=True, recordatorio_en__isnull=True, fecha_inicio__lte=hoy + timedelta(days=1),
                                             fecha_fin__gte=hoy)
    recordados = 0
    for evento in pendientes:
        if not EventoAgenda.objects.filter(pk=evento.pk, recordatorio_en__isnull=True).update(recordatorio_en=ahora):
            continue   # otro proceso ya lo recordó
        usuarios, tutores, estudiantes = audiencia(evento)
        AvisoAgenda.objects.bulk_create(
            [AvisoAgenda(evento=evento, usuario_id=pk) for pk in usuarios] + [AvisoAgenda(evento=evento, tutor_id=pk) for pk in tutores]
            + [AvisoAgenda(evento=evento, alumno_id=pk) for pk in estudiantes], ignore_conflicts=True)
        try:
            _push(evento, usuarios, tutores, estudiantes, hoy)
        except Exception:
            registro.exception('No se pudieron mandar las notificaciones push del evento %s', evento.pk)
        recordados += 1
    return recordados


def generar_sin_fallar():
    """Nunca debe impedir que se abra una página ni que se guarde un evento."""
    try:
        generar()
    except Exception:
        registro.exception('No se pudieron generar los recordatorios de la agenda')


def generar_si_toca():
    """A lo más cada 5 minutos por proceso."""
    try:
        if not cache.add(LLAVE, 1, 5 * 60):
            return
    except Exception:
        registro.exception('No se pudo revisar si toca generar los recordatorios de la agenda')
        return
    generar_sin_fallar()


# ---------------------------------------------------------------------------
# La campana
# ---------------------------------------------------------------------------
def pendientes_de(persona):
    """Sus recordatorios sin ver de eventos que todavía no terminan."""
    return AvisoAgenda.objects.filter(visto_en__isnull=True, evento__fecha_fin__gte=timezone.localdate(), **persona.filtro_de_persona)


def marcar_vistos(persona, evento=None):
    consulta = AvisoAgenda.objects.filter(visto_en__isnull=True, **persona.filtro_de_persona)
    if evento is not None:
        consulta = consulta.filter(evento=evento)
    return consulta.update(visto_en=timezone.now())


def datos_de_la_campana(persona):
    """{'pendientes', 'avisos': [{titulo, texto, url}], 'mas'}."""
    hoy = timezone.localdate()
    consulta = pendientes_de(persona).select_related('evento').order_by('evento__fecha_inicio', 'evento__hora_inicio')
    avisos = list(consulta[:EN_LA_CAMPANA + 1])
    total = len(avisos) if len(avisos) <= EN_LA_CAMPANA else consulta.count()
    base = persona.url('calendario')
    lista = [{
        'id': aviso.pk, 'titulo': f'{_cuando(aviso.evento, hoy)}: {aviso.evento.titulo}',
        'texto': ' · '.join(p for p in (aviso.evento.texto_de_horario, aviso.evento.lugar) if p),
        'url': f'{base}?evento={aviso.evento_id}',
    } for aviso in avisos[:EN_LA_CAMPANA]]
    return {'pendientes': total, 'avisos': lista, 'mas': max(total - len(lista), 0)}

