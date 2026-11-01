"""Los avisos de los comunicados (2026-10-27): en tiempo real a las pestañas abiertas (Comunicados/tiempo_real.py) y como
notificación push al teléfono o a la computadora aunque el sistema esté cerrado (Mensajes/push.py; los urgentes, con
prioridad alta). Van en segundo plano: quien envía a cientos de familias no espera a que salgan uno por uno.

- Al enviar: si se publica ya, se avisa a todos al guardarse. Si se programó, sus destinatarios lo ven desde su fecha y
  hora (Comunicados/reglas.py lo filtra en cada consulta) y el aviso sale cuando algo revisa los pendientes:
  `publicar_si_toca` (a lo más una vez por minuto, en las pantallas y el resumen de la campana de comunicados) o el
  comando `python manage.py publicar_comunicados` (para un Cron de Railway cada pocos minutos).
- `avisado_en` se escribe al terminar de avisar, no antes (2026-10-31): si el proceso se reinicia a media entrega, el
  aviso sigue pendiente y otro lo retoma. Quien avisa lo reclama (`aviso_reclamado_en`) para que dos procesos no lo
  manden a la vez, y lo intenta hasta `MAXIMO_DE_INTENTOS` veces. Un push repetido no molesta: lleva la misma etiqueta y
  reemplaza al anterior.
- «Recordar a los pendientes»: el mismo aviso, marcado como recordatorio, solo a quienes todavía no lo abren (o no
  responden, si pide respuesta), y que tienen cómo entrar a su portal.
- Un cambio importante (Comunicados/reglas.editar): el mismo aviso, marcado como cambio, a todos sus destinatarios.
- Las imágenes del texto que se subieron y nunca se enviaron se borran al día siguiente, salvo las de un borrador.
"""
import logging
import threading
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import connections
from django.db.models import F, Q
from django.utils import timezone

from . import tiempo_real
from .models import Comunicado, Destinatario, ImagenComunicado

registro = logging.getLogger(__name__)
LLAVE_PUBLICAR = 'comunicados-publicar'
LLAVE_LIMPIAR = 'comunicados-limpiar-imagenes'
RECLAMO = timedelta(minutes=10)   # tras esto, un aviso a medias se da por perdido y se reintenta


def _en_segundo_plano(tarea, *argumentos):
    if not getattr(settings, 'COMUNICADOS_EN_SEGUNDO_PLANO', False):
        tarea(*argumentos)
        return

    def correr():
        try:
            tarea(*argumentos)
        except Exception:   # un aviso que no sale no debe tumbar nada: el comunicado ya está guardado
            registro.exception('No se pudieron mandar los avisos de comunicados')
        finally:
            connections.close_all()

    threading.Thread(target=correr, name='comunicados-avisos', daemon=True).start()


def avisar(comunicado_id, solo=None, recordatorio=False, cambio=False):
    """Avisa (en tiempo real y push) a los destinatarios del comunicado: a todos, o a los de ids `solo`."""
    _en_segundo_plano(_avisar, comunicado_id, solo, recordatorio, cambio)


def publicar(comunicado_id):
    """El aviso de publicación, que cada comunicado da una sola vez."""
    _en_segundo_plano(_publicar, comunicado_id)


def _reclamar(comunicado_id, ahora):
    libre = Q(aviso_reclamado_en__isnull=True) | Q(aviso_reclamado_en__lte=ahora - RECLAMO)
    return Comunicado.objects.filter(libre, pk=comunicado_id, avisado_en__isnull=True, aviso_intentos__lt=Comunicado.MAXIMO_DE_INTENTOS).update(
        aviso_reclamado_en=ahora, aviso_intentos=F('aviso_intentos') + 1)


def _publicar(comunicado_id, ahora=None):
    """True si este proceso dio el aviso. Si falla, queda pendiente y se reintenta."""
    if not _reclamar(comunicado_id, ahora or timezone.now()):
        return False
    _avisar(comunicado_id)
    Comunicado.objects.filter(pk=comunicado_id).update(avisado_en=timezone.now())
    return True


def _avisar(comunicado_id, solo=None, recordatorio=False, cambio=False):
    comunicado = Comunicado.objects.select_related('autor').filter(pk=comunicado_id, eliminado=False).first()
    if comunicado is None:
        return
    destinatarios = comunicado.destinatarios.all()
    if solo is not None:
        destinatarios = destinatarios.filter(pk__in=list(solo))
    filas = list(destinatarios.values('tipo', 'alumno_id', 'tutor_id', 'profesor_id', 'usuario_id'))
    if not filas:
        return
    tiempo_real.enviar_eventos(comunicado, filas, recordatorio, cambio)
    try:
        _push(comunicado, filas, recordatorio, cambio)
    except Exception:
        registro.exception('No se pudieron mandar las notificaciones push del comunicado %s', comunicado.pk)


def _push(comunicado, filas, recordatorio, cambio=False):
    from Alumnos.models import Profesor
    from Mensajes import push
    if not push.activas():
        return
    profesores = dict(Profesor.objects.filter(pk__in=[f['profesor_id'] for f in filas if f['profesor_id']]).values_list('pk', 'usuario_id'))
    claves = []
    for fila in filas:
        if fila['tipo'] == Destinatario.TUTOR:
            claves.append((fila['tipo'], ('tutor', fila['tutor_id'])))
        elif fila['tipo'] == Destinatario.ESTUDIANTE:
            claves.append((fila['tipo'], ('alumno', fila['alumno_id'])))
        elif fila['tipo'] == Destinatario.PROFESOR and profesores.get(fila['profesor_id']):
            claves.append((fila['tipo'], ('usuario', profesores[fila['profesor_id']])))
        elif fila['tipo'] == Destinatario.PERSONAL:
            claves.append((fila['tipo'], ('usuario', fila['usuario_id'])))
    suscripciones = push.suscripciones_de(
        tutores=[c[1] for _, c in claves if c[0] == 'tutor'], alumnos=[c[1] for _, c in claves if c[0] == 'alumno'],
        usuarios=[c[1] for _, c in claves if c[0] == 'usuario'])
    if not suscripciones:
        return
    from .reglas import nombre_de_usuario
    prefijo = 'Cambió: ' if cambio else 'Recordatorio: ' if recordatorio else ('Urgente: ' if comunicado.urgente else 'Comunicado: ')
    texto = f'{nombre_de_usuario(comunicado.autor)} · {tiempo_real.vista_previa(comunicado.descripcion)}'
    envios = []
    for tipo, clave in claves:
        carga = {'titulo': f'{prefijo}{comunicado.titulo}', 'texto': texto, 'url': tiempo_real.url_para(tipo, comunicado.pk),
                 'etiqueta': f'comunicado-{comunicado.pk}', 'urgente': comunicado.urgente}
        envios.extend((suscripcion, carga) for suscripcion in suscripciones.get(clave, []))
    push.enviar_ahora(envios, urgente=comunicado.urgente)


# ---------------------------------------------------------------------------
# Programados
# ---------------------------------------------------------------------------
def _pendientes(ahora):
    """Los que ya llegaron a su hora y no terminan de avisar, sin los que alguien está avisando en este momento."""
    libre = Q(aviso_reclamado_en__isnull=True) | Q(aviso_reclamado_en__lte=ahora - RECLAMO)
    return Comunicado.objects.visibles().filter(libre, avisado_en__isnull=True, publicado_en__lte=ahora,
                                                aviso_intentos__lt=Comunicado.MAXIMO_DE_INTENTOS)


def publicar_pendientes(ahora=None):
    """Avisa de los comunicados cuya hora ya llegó y no han terminado de avisar (cada uno una sola vez, aunque dos procesos
    revisen a la vez). Devuelve los ids que avisó."""
    ahora = ahora or timezone.now()
    avisados = []
    for pk in list(_pendientes(ahora).order_by('publicado_en').values_list('pk', flat=True)[:100]):
        try:
            if _publicar(pk, ahora):
                avisados.append(pk)
        except Exception:   # queda pendiente; los demás siguen
            registro.exception('No se pudo avisar del comunicado %s', pk)
    return avisados


def publicar_si_toca():
    """A lo más una vez por minuto por proceso: los programados que ya llegaron a su hora; una vez al día, las imágenes
    del texto que nunca se enviaron. Nunca debe impedir que se abra una pantalla."""
    try:
        if cache.add(LLAVE_PUBLICAR, 1, 60) and _pendientes(timezone.now()).exists():
            _en_segundo_plano(publicar_pendientes)
        if cache.add(LLAVE_LIMPIAR, 1, 24 * 60 * 60):
            limpiar_imagenes()
    except Exception:
        registro.exception('No se pudieron revisar los comunicados programados')


def limpiar_imagenes():
    """Borra las imágenes del texto que se subieron hace más de un día, nunca se enviaron y no están en un borrador
    (registro y archivo)."""
    viejas = list(ImagenComunicado.objects.filter(comunicado__isnull=True, borrador__isnull=True, creada__lt=timezone.now() - timedelta(days=1)))
    for imagen in viejas:
        try:
            imagen.archivo.delete(save=False)
        except Exception:   # sin el registro nadie puede pedirla: el archivo, si quedó, es inaccesible
            registro.exception('No se pudo borrar una imagen sin enviar de comunicados')
        imagen.delete()
    return len(viejas)
