"""Las notificaciones de las reuniones con familias, en la campana del sistema y del portal de tutores (la misma de los
mensajes, los comunicados y los retiros).

- Al personal que participa (y al responsable): una reunión asignada, la solicitud de confirmar su disponibilidad, la
  reunión confirmada, las reprogramaciones, las cancelaciones, las inasistencias, los recordatorios previos y los
  acuerdos a su cargo por vencer o vencidos. Quien hizo el cambio no se notifica a sí mismo.
- A los tutores invitados: la solicitud de confirmar la cita, la confirmación, las reprogramaciones, las cancelaciones,
  los recordatorios y los acuerdos compartidos con la familia por vencer o vencidos. Llevan las indicaciones para la
  familia, si las hay.
- A quien atiende (el responsable o, sin él, quien registra o gestiona esa reunión): las solicitudes que pasaron su plazo
  sin programarse (Ajustes › Reuniones), una vez cada una.

Solo dicen cuándo y dónde (y el folio): nunca el motivo, la descripción, los acuerdos ni las notas. Se guardan en la base
de datos y, al confirmarse la transacción, se avisan en tiempo real (Reuniones/tiempo_real.py). Los recordatorios y los
avisos de acuerdos no necesitan un proceso aparte: se generan una vez (`clave`) cuando la persona abre el sistema o con
`python manage.py avisos_de_reuniones`. No hay correo, SMS ni WhatsApp: el sistema no los tiene; los avisos por
teléfono se anotan en la reunión (ContactoReunion).
"""
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.formats import date_format

from .models import Acuerdo, ConfiguracionReuniones, NotificacionReunion, ParticipanteReunion, Reunion


def cuando(reunion):
    """«Lunes 20 de octubre, 10:00 a 10:30 · Sala de juntas» (o «Por programar»)."""
    if not reunion.programada:
        return 'Por programar'
    texto = f'{date_format(reunion.fecha, "l j \\d\\e F").capitalize()}, {reunion.hora_inicio:%H:%M} a {reunion.hora_fin:%H:%M}'
    return f'{texto} · {reunion.sala}' if reunion.sala_id else texto


def _texto(reunion):
    return f'{cuando(reunion)} · {reunion.folio}'[:300]


def _texto_familia(reunion):
    """Para la familia: cuándo, dónde, el folio y sus indicaciones (si las hay)."""
    texto = _texto(reunion)
    return f'{texto} · {reunion.indicaciones}'[:300] if reunion.indicaciones and reunion.programada else texto


def _guardar(notificaciones):
    creadas = NotificacionReunion.objects.bulk_create(notificaciones)
    ids = [n.pk for n in creadas if n.pk]

    def avisar():
        from . import tiempo_real
        tiempo_real.avisar(ids)

    if ids:
        transaction.on_commit(avisar)
    return creadas


def del_personal(reunion):
    """Las cuentas del personal de la reunión: los participantes activos y el responsable."""
    usuarios = {p.usuario_id: p.usuario for p in reunion.participantes.filter(activo=True, usuario__is_active=True).select_related('usuario')}
    if reunion.responsable_id and reunion.responsable.is_active:
        usuarios.setdefault(reunion.responsable_id, reunion.responsable)
    return list(usuarios.values())


def al_personal(reunion, titulo, texto=None, usuarios=None, excluir=None, clave=''):
    usuarios = del_personal(reunion) if usuarios is None else usuarios
    excluido = getattr(excluir, 'pk', None)
    return _guardar([NotificacionReunion(usuario=u, reunion=reunion, titulo=titulo[:160], texto=(texto or _texto(reunion))[:300], clave=clave)
                     for u in usuarios if u.pk != excluido])


def a_la_familia(reunion, titulo, texto=None, clave=''):
    return _guardar([NotificacionReunion(tutor_id=invitado.tutor_id, reunion=reunion, titulo=titulo[:160],
                                         texto=(texto or _texto_familia(reunion))[:300], clave=clave)
                     for invitado in reunion.tutores.all()])


# ---------------------------------------------------------------------------
# Los avisos de cada momento
# ---------------------------------------------------------------------------
def asignada(reunion, usuarios, actor):
    titulo = 'Nueva reunión con familia asignada'
    texto = f'{_texto(reunion)} · Confirma tu disponibilidad' if reunion.programada else f'Por programar · {reunion.folio}'
    return al_personal(reunion, titulo, texto, usuarios=usuarios, excluir=actor)


def programada(reunion, actor, nuevos=()):
    """La cita ya tiene fecha: el personal confirma su disponibilidad y la familia, su asistencia."""
    al_personal(reunion, 'Confirma tu disponibilidad para una reunión con familia', f'{_texto(reunion)}', excluir=actor)
    a_la_familia(reunion, 'Cita programada: confirma tu asistencia')


def confirmada(reunion, actor):
    al_personal(reunion, 'Reunión con familia confirmada', excluir=actor)
    a_la_familia(reunion, 'Tu cita en el colegio está confirmada')


def reprogramada(reunion, actor):
    al_personal(reunion, 'Reunión con familia reprogramada: confirma tu disponibilidad', excluir=actor)
    a_la_familia(reunion, 'Tu cita en el colegio cambió de fecha: confirma tu asistencia')


def cancelada(reunion, actor, usuarios=None):
    texto = f'Era: {cuando(reunion)} · {reunion.folio}' if reunion.programada else reunion.folio
    al_personal(reunion, 'Reunión con familia cancelada', texto, usuarios=usuarios, excluir=actor)
    a_la_familia(reunion, 'Tu cita en el colegio se canceló', texto)


def no_realizada(reunion, actor):
    al_personal(reunion, 'Reunión con familia no realizada por inasistencia', excluir=actor)
    a_la_familia(reunion, 'Tu cita en el colegio quedó como no realizada', f'{_texto(reunion)} · Comunícate con el colegio')


def requiere_atencion(reunion, actor, razon):
    """Al responsable (y a quien gestiona desde la reunión): la cita confirmada volvió a pendiente."""
    usuarios = [reunion.responsable] if reunion.responsable_id and reunion.responsable.is_active else []
    return al_personal(reunion, 'Una reunión con familia necesita atención', f'{razon} · {reunion.folio}'[:300],
                       usuarios=usuarios, excluir=actor)


# ---------------------------------------------------------------------------
# Recordatorios y acuerdos (una sola vez cada uno)
# ---------------------------------------------------------------------------
def _nuevas(destino, propuestas):
    """Guarda las notificaciones cuya clave no existe todavía para ese destinatario."""
    if not propuestas:
        return []
    claves = {n.clave for n in propuestas}
    existentes = set(NotificacionReunion.objects.filter(**destino, clave__in=claves).values_list('clave', flat=True))
    vistas, nuevas = set(existentes), []
    for notificacion in propuestas:
        if notificacion.clave not in vistas:
            vistas.add(notificacion.clave)
            nuevas.append(notificacion)
    return _guardar(nuevas)


def _proximas(reuniones, ahora, horas):
    limite = ahora + timedelta(hours=horas)
    consulta = reuniones.filter(estado__in=(Reunion.PROGRAMADA, Reunion.CONFIRMADA), fecha__gte=ahora.date(), fecha__lte=limite.date())
    return [r for r in consulta.select_related('sala') if r.programada and ahora < r.inicio <= limite]


def _clave_recordatorio(reunion):
    return f'recordatorio:{reunion.pk}:{reunion.fecha:%Y%m%d}{reunion.hora_inicio:%H%M}'


def _clave_espera(reunion):
    return f'espera:{reunion.pk}'


def _esperan(usuario, hoy):
    """Las solicitudes que pasaron su plazo sin programarse y que le toca atender: las suyas como responsable y, sin
    responsable, las que puede atender (registra o gestiona esa reunión)."""
    from .alcance import Acceso, atiende_reuniones
    from .reglas import que_esperan_demasiado
    if not atiende_reuniones(usuario):
        return []
    acceso = Acceso(usuario)
    return [r for r in que_esperan_demasiado(acceso.reuniones(), hoy)
            if r.responsable_id == usuario.pk or (r.responsable_id is None and acceso.atiende_reunion(r))]


def _clave_acuerdo(acuerdo, hoy):
    tipo = 'vencido' if acuerdo.fecha_limite < hoy else 'por-vencer'
    return f'acuerdo-{tipo}:{acuerdo.pk}:{acuerdo.fecha_limite:%Y%m%d}'


def _aviso_de_acuerdo(acuerdo, hoy):
    if acuerdo.fecha_limite < hoy:
        return 'Acuerdo de una reunión vencido', f'Venció el {acuerdo.fecha_limite:%d/%m/%Y} · {acuerdo.reunion.folio}'
    return 'Acuerdo de una reunión por vencer', f'Vence el {acuerdo.fecha_limite:%d/%m/%Y} · {acuerdo.reunion.folio}'


def generar_para(usuario=None, tutor=None, ahora=None):
    """Los recordatorios de las próximas reuniones, los avisos de acuerdos por vencer o vencidos y (al personal que
    atiende) las solicitudes que esperan demasiado, de una cuenta del personal o de un tutor, que todavía no se le hayan
    dado. Devuelve las nuevas."""
    ahora = ahora or timezone.now()
    hoy = timezone.localdate(ahora)
    configuracion = ConfiguracionReuniones.actual()
    limite_acuerdos = hoy + timedelta(days=configuracion.aviso_acuerdos_dias)
    abiertos = Acuerdo.objects.exclude(estado=Acuerdo.CUMPLIDO).exclude(reunion__estado=Reunion.CANCELADA).filter(fecha_limite__lte=limite_acuerdos)
    propuestas = []
    if usuario is not None:
        destino = {'usuario': usuario}
        mias = Reunion.objects.filter(Q(participantes__usuario=usuario, participantes__activo=True) | Q(responsable=usuario)).distinct()
        for reunion in _proximas(mias, ahora, configuracion.recordatorio_horas):
            propuestas.append(NotificacionReunion(usuario=usuario, reunion=reunion, titulo='Recordatorio: reunión con familia',
                                                  texto=_texto(reunion), clave=_clave_recordatorio(reunion)))
        acuerdos = abiertos.filter(Q(responsable=usuario) | Q(responsable__isnull=True, reunion__responsable=usuario)).select_related('reunion')
        for reunion in _esperan(usuario, hoy):
            dias = reunion.dias_de_espera
            propuestas.append(NotificacionReunion(
                usuario=usuario, reunion=reunion, titulo='Una solicitud espera ser programada', clave=_clave_espera(reunion),
                texto=f'{reunion.folio} · Solicitada el {timezone.localtime(reunion.creada):%d/%m} · '
                      f'{dias} día{"s" if dias != 1 else ""} hábil{"es" if dias != 1 else ""} sin programar'))
    else:
        destino = {'tutor': tutor}
        suyas = Reunion.objects.filter(tutores__tutor=tutor).distinct()
        for reunion in _proximas(suyas, ahora, configuracion.recordatorio_horas):
            propuestas.append(NotificacionReunion(tutor=tutor, reunion=reunion, titulo='Recordatorio: tienes una cita en el colegio',
                                                  texto=_texto_familia(reunion), clave=_clave_recordatorio(reunion)))
        acuerdos = abiertos.filter(compartido=True, reunion__tutores__tutor=tutor).exclude(quien='ESCUELA').select_related('reunion').distinct()
    for acuerdo in acuerdos:
        titulo, texto = _aviso_de_acuerdo(acuerdo, hoy)
        propuestas.append(NotificacionReunion(**destino, reunion=acuerdo.reunion, titulo=titulo, texto=texto, clave=_clave_acuerdo(acuerdo, hoy)))
    return _nuevas(destino, propuestas)


def generar_todas(ahora=None):
    """Para todos (el comando avisos_de_reuniones): el personal de las reuniones próximas y de los acuerdos abiertos, y
    sus familias."""
    from django.contrib.auth import get_user_model

    from Alumnos.models import Tutor
    ahora = ahora or timezone.now()
    personal = set(ParticipanteReunion.objects.filter(activo=True, reunion__estado__in=Reunion.ABIERTAS + (Reunion.REALIZADA,))
                   .values_list('usuario_id', flat=True))
    personal |= set(Reunion.objects.exclude(responsable=None).values_list('responsable_id', flat=True))
    personal |= set(Acuerdo.objects.exclude(estado=Acuerdo.CUMPLIDO).exclude(responsable=None).values_list('responsable_id', flat=True))
    if Reunion.objects.filter(estado__in=Reunion.SIN_PROGRAMAR).exists():   # quien atiende, por las solicitudes que esperan
        from .alcance import QUE_ATIENDEN, cuentas_con_permiso
        for permiso in QUE_ATIENDEN:
            personal |= set(cuentas_con_permiso(permiso).values_list('pk', flat=True))
    total = 0
    for usuario in get_user_model().objects.filter(pk__in=personal, is_active=True):
        total += len(generar_para(usuario=usuario, ahora=ahora))
    for tutor in Tutor.objects.filter(reuniones_con_familia__isnull=False).distinct():
        total += len(generar_para(tutor=tutor, ahora=ahora))
    return total


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------
def pendientes_de(usuario=None, tutor=None):
    if usuario is not None:
        return NotificacionReunion.objects.filter(usuario=usuario, leida=False)
    return NotificacionReunion.objects.filter(tutor=tutor, leida=False)


def marcar_leidas(reunion, usuario=None, tutor=None):
    """Al abrir una reunión, sus notificaciones quedan leídas."""
    return pendientes_de(usuario=usuario, tutor=tutor).filter(reunion=reunion).update(leida=True)


def momento(fecha, hora):
    return timezone.make_aware(datetime.combine(fecha, hora))
