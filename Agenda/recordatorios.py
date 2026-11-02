"""Los avisos de la agenda (pedido del 2026-10-27; ampliado el 2026-11-02): el recordatorio de los eventos importantes y
el aviso de un cambio de fecha, hora o lugar o de una cancelación, a quienes lo ven en su agenda.

- A cada persona le queda un aviso en la campana (`AvisoAgenda`, sección «Agenda»: a lo más uno por evento, el más
  reciente) y, si activó las notificaciones de su navegador, le llega al teléfono (Mensajes/push.py).
- Quién lo ve: el personal con alguno de sus niveles (o todo el colegio) en su agenda; si es para las familias, los
  tutores con hijos inscritos en esos niveles (o en esos grados o grupos) que reciben notificaciones de ese estudiante;
  si es para los estudiantes, los inscritos (con acceso a su portal).
- El recordatorio se manda una sola vez (`recordatorio_en`), con la anticipación elegida (`recordar_dias`), solo entre
  las 7:00 y las 21:00. Se genera cuando alguien abre la agenda o el inicio (a lo más cada 5 minutos por proceso, en
  segundo plano) o con `python manage.py recordatorios_de_agenda` (para un Cron). Si algo falla a la mitad, no queda
  marcado: se vuelve a intentar.
- Los cambios y las cancelaciones se avisan en el momento en que se guardan (quien gestiona elige si avisar).
- El aviso queda visto al abrir la agenda; los de eventos que ya pasaron dejan de mostrarse.
"""
import logging
import threading
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connections, transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from Alumnos.models import Inscripcion, TutorAlumno

from .models import COLEGIO, AvisoAgenda, EventoAgenda

registro = logging.getLogger(__name__)
LLAVE = 'agenda-recordatorios'
EN_LA_CAMPANA = 5
HORA_DESDE, HORA_HASTA = 7, 21     # los recordatorios automáticos no salen de noche


def _en_segundo_plano(tarea, *argumentos):
    """Quien abre la página o guarda el evento no espera a que salgan los avisos."""
    def correr():
        try:
            tarea(*argumentos)
        except Exception:
            registro.exception('No se pudieron mandar los avisos de la agenda')
        finally:
            if getattr(settings, 'AGENDA_EN_SEGUNDO_PLANO', False):
                connections.close_all()

    if getattr(settings, 'AGENDA_EN_SEGUNDO_PLANO', False):
        threading.Thread(target=correr, name='agenda-avisos', daemon=True).start()
    else:
        correr()


# ---------------------------------------------------------------------------
# Quién lo ve
# ---------------------------------------------------------------------------
def inscripciones_del_evento(evento):
    """Las inscripciones vigentes de los estudiantes que tienen el evento en su agenda (sin mirar si es para familias o
    para estudiantes)."""
    inscripciones = Inscripcion.objects.filter(activa=True, ciclo__activo=True, alumno__estatus='ACTIVO')
    if evento.alcance != COLEGIO:
        inscripciones = inscripciones.filter(grado__nivel__in=evento.niveles_del_evento)
    if evento.por_grupos:
        inscripciones = inscripciones.filter(Q(grado__in=evento.grados.values('pk')) | Q(grupo__in=evento.grupos.values('pk')))
    return inscripciones


def tutores_del_evento(evento, solo_con_notificaciones=True):
    """Los ids de los tutores que lo ven (vínculo activo, con acceso a su portal); para avisar, solo los que reciben
    notificaciones de ese estudiante."""
    if not evento.para_familias:
        return []
    vinculos = TutorAlumno.objects.filter(activo=True, alumno__in=inscripciones_del_evento(evento).values('alumno'),
                                          tutor__estatus='ACTIVO', tutor__acceso_portal=True)
    if solo_con_notificaciones:
        vinculos = vinculos.filter(recibe_notificaciones=True)
    return list(vinculos.values_list('tutor_id', flat=True).distinct())


def audiencia(evento, vistas=None):
    """(ids de usuarios, de tutores, de estudiantes) a quienes avisar. `vistas`: {usuario: Vista} ya calculadas (para
    no repetirlas al revisar varios eventos)."""
    from . import alcance
    cuentas = get_user_model().objects.filter(is_active=True)
    if evento.alcance == COLEGIO:
        usuarios = list(cuentas.values_list('pk', flat=True))
    else:
        vistas = {} if vistas is None else vistas
        niveles = set(evento.niveles_del_evento)
        usuarios = []
        for cuenta in cuentas:
            if cuenta.pk not in vistas:
                vistas[cuenta.pk] = alcance.de_usuario(cuenta)
            vista = vistas[cuenta.pk]
            if vista.todos or niveles & vista.niveles:
                usuarios.append(cuenta.pk)
    estudiantes = []
    if evento.para_estudiantes:
        estudiantes = list(inscripciones_del_evento(evento).filter(alumno__acceso_portal=True).values_list('alumno_id', flat=True).distinct())
    return usuarios, tutores_del_evento(evento), estudiantes


# ---------------------------------------------------------------------------
# Mandar los avisos
# ---------------------------------------------------------------------------
def cuando(evento, hoy):
    """«Hoy», «Mañana» o «El jueves 12»."""
    if evento.fecha_inicio <= hoy:
        return 'Hoy'
    if evento.fecha_inicio == hoy + timedelta(days=1):
        return 'Mañana'
    return 'El ' + date_format(evento.fecha_inicio, 'l j')


def titulo_del_aviso(tipo, evento, hoy):
    if tipo == AvisoAgenda.CAMBIO:
        return f'Cambió: {evento.titulo}'
    if tipo == AvisoAgenda.CANCELADO:
        return f'Cancelado: {evento.titulo}'
    return f'{cuando(evento, hoy)}: {evento.titulo}'


def texto_del_aviso(aviso_o_tipo, evento, texto=''):
    tipo = getattr(aviso_o_tipo, 'tipo', aviso_o_tipo)
    if tipo != AvisoAgenda.RECORDATORIO and (texto or getattr(aviso_o_tipo, 'texto', '')):
        return texto or aviso_o_tipo.texto
    return ' · '.join(p for p in (evento.texto_de_horario, evento.lugar) if p)


def _reemplazar(evento, usuarios, tutores, estudiantes, tipo, texto=''):
    """Cada persona se queda solo con la novedad más reciente del evento."""
    AvisoAgenda.objects.filter(evento=evento).delete()
    AvisoAgenda.objects.bulk_create(
        [AvisoAgenda(evento=evento, usuario_id=pk, tipo=tipo, texto=texto) for pk in usuarios]
        + [AvisoAgenda(evento=evento, tutor_id=pk, tipo=tipo, texto=texto) for pk in tutores]
        + [AvisoAgenda(evento=evento, alumno_id=pk, tipo=tipo, texto=texto) for pk in estudiantes])


def _push(evento, usuarios, tutores, estudiantes, tipo, texto, hoy):
    from Mensajes import push
    if not push.activas():
        return
    suscripciones = push.suscripciones_de(tutores=tutores, alumnos=estudiantes, usuarios=usuarios)
    if not suscripciones:
        return
    urls = {'usuario': reverse('agenda:calendario'), 'tutor': reverse('portal_tutores:agenda:calendario'),
            'alumno': reverse('portal_estudiantes:agenda:calendario')}
    envios = []
    for (clase, _), lista in suscripciones.items():
        carga = {'titulo': titulo_del_aviso(tipo, evento, hoy), 'texto': texto_del_aviso(tipo, evento, texto),
                 'url': f'{urls[clase]}?evento={evento.pk}', 'etiqueta': f'agenda-{evento.pk}'}
        envios.extend((suscripcion, carga) for suscripcion in lista)
    push._en_segundo_plano(envios)


def _avisar(evento_id, tipo, texto):
    evento = EventoAgenda.objects.filter(pk=evento_id).first()
    if evento is None:
        return
    with transaction.atomic():
        usuarios, tutores, estudiantes = audiencia(evento)
        _reemplazar(evento, usuarios, tutores, estudiantes, tipo, texto)
    try:
        _push(evento, usuarios, tutores, estudiantes, tipo, texto, timezone.localdate())
    except Exception:
        registro.exception('No se pudieron mandar las notificaciones push del evento %s', evento.pk)


def avisar(evento, tipo, texto=''):
    """Avisa de un cambio o de una cancelación a quienes ven el evento (al confirmarse lo guardado, en segundo plano)."""
    transaction.on_commit(lambda: _en_segundo_plano(_avisar, evento.pk, tipo, texto[:200]))


def generar(ahora=None):
    """Los recordatorios de los eventos importantes que ya toca recordar y todavía no se recordaron (no de noche).
    Devuelve cuántos eventos recordó."""
    ahora = ahora or timezone.now()
    local = timezone.localtime(ahora)
    if not HORA_DESDE <= local.hour < HORA_HASTA:
        return 0
    hoy = local.date()
    pendientes = EventoAgenda.objects.filter(importante=True, recordatorio_en__isnull=True, cancelado_en__isnull=True,
                                             fecha_inicio__lte=hoy + timedelta(days=7), fecha_fin__gte=hoy).prefetch_related('niveles_varios')
    recordados, vistas = 0, {}
    for evento in pendientes:
        if evento.fecha_inicio > hoy + timedelta(days=evento.recordar_dias):
            continue
        try:
            with transaction.atomic():
                if not EventoAgenda.objects.filter(pk=evento.pk, recordatorio_en__isnull=True).update(recordatorio_en=ahora):
                    continue   # otro proceso ya lo recordó
                usuarios, tutores, estudiantes = audiencia(evento, vistas)
                _reemplazar(evento, usuarios, tutores, estudiantes, AvisoAgenda.RECORDATORIO)
        except Exception:
            # Sin marcar: se vuelve a intentar en la siguiente revisión
            registro.exception('No se pudo generar el recordatorio del evento %s', evento.pk)
            continue
        try:
            _push(evento, usuarios, tutores, estudiantes, AvisoAgenda.RECORDATORIO, '', hoy)
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
    """A lo más cada 5 minutos por proceso, en segundo plano."""
    try:
        if not cache.add(LLAVE, 1, 5 * 60):
            return
    except Exception:
        registro.exception('No se pudo revisar si toca generar los recordatorios de la agenda')
        return
    _en_segundo_plano(generar_sin_fallar)


# ---------------------------------------------------------------------------
# La campana
# ---------------------------------------------------------------------------
def pendientes_de(persona):
    """Sus avisos sin ver de eventos que todavía no terminan."""
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
        'id': aviso.pk, 'titulo': titulo_del_aviso(aviso.tipo, aviso.evento, hoy), 'texto': texto_del_aviso(aviso, aviso.evento),
        'url': f'{base}?evento={aviso.evento_id}',
    } for aviso in avisos[:EN_LA_CAMPANA]]
    return {'pendientes': total, 'avisos': lista, 'mas': max(total - len(lista), 0)}
