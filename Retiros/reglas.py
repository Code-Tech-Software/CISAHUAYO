"""Las reglas de los retiros anticipados: quién puede avisar, a quién se puede mandar por los estudiantes, qué horas son
válidas, y cómo se cancelan, se confirman y se corrigen (todo queda en la bitácora). Las vistas solo llaman aquí: la
pantalla nunca es la única defensa.

- Un tutor avisa el retiro de un hijo si tiene con él un vínculo activo como **tutor principal** o **autorizado para
  recogerlo**, si el estudiante está activo y si tiene inscripción en el ciclo actual.
- Recoge el propio tutor u otra persona ya autorizada en el sistema: un tutor del estudiante (vínculo activo) marcado
  «Autorizado para recoger al estudiante» y activo. Si el aviso es de varios hijos, debe estar autorizado para todos.
- La fecha y la hora deben ser futuras (zona horaria del sistema), dentro del ciclo actual, en un día de clases del nivel
  del estudiante y dentro de su horario de ese día: desde que empieza su primera clase y antes de que termine la última
  (si termina antes, ya no es un retiro anticipado).
- Un estudiante no puede tener dos avisos activos (Avisado) el mismo día; la base de datos también lo impide.
- La salida la confirma el personal (`Retiros.confirmar`), una vez por estudiante, con quién lo recogió (alguien
  autorizado) y la hora real (de ese día y no futura). El tutor no puede cambiar un retiro confirmado.
- Cancelar: el tutor, sus estudiantes todavía avisados; el personal (`Retiros.corregir`), con motivo. Corregir una
  salida confirmada (o deshacerla) también exige motivo y guarda lo que había y lo que quedó.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from Alumnos.academico import ciclo_actual
from Alumnos.asistencias import clases_del_dia, motivo_sin_clases
from Alumnos.models import Inscripcion, TutorAlumno

from . import notificaciones
from .models import AvisoRetiro, EventoRetiro, NotaInterna, RetiroEstudiante

AVISADO, RETIRADO, CANCELADO = RetiroEstudiante.AVISADO, RetiroEstudiante.RETIRADO, RetiroEstudiante.CANCELADO
TONO_DE_ESTADO = {AVISADO: 'tag--info', RETIRADO: 'tag--success', CANCELADO: ''}   # clases de .tag (app.css)
NOMBRE_DE_ESTADO = dict(RetiroEstudiante.ESTADOS)
TOLERANCIA_DEL_RELOJ = timedelta(minutes=2)   # la hora real puede venir del reloj del equipo, un poco adelantado


class RetiroRechazado(Exception):
    """Lo pedido no se puede hacer. `mensajes` son para la persona (uno por cada problema)."""

    def __init__(self, *mensajes):
        self.mensajes = [m for m in mensajes if m]
        super().__init__(' '.join(self.mensajes))


def nombre_de(persona):
    """«Ana Campos Vega» (estudiante o tutor)."""
    return ' '.join(f'{persona.nombre} {persona.apellido_paterno} {persona.apellido_materno}'.split())


def nombre_de_usuario(usuario):
    return (usuario.get_full_name() or usuario.get_username()) if usuario else 'Alguien'


def _lista(nombres):
    nombres = list(nombres)
    return nombres[0] if len(nombres) == 1 else f'{", ".join(nombres[:-1])} y {nombres[-1]}'


def _hora(valor):
    return valor.strftime('%H:%M')


def _fecha(valor):
    return valor.strftime('%d/%m/%Y')


# ---------------------------------------------------------------------------
# Quién avisa y quién recoge
# ---------------------------------------------------------------------------
@dataclass
class Hijo:
    alumno: object
    vinculo: object
    inscripcion: object
    motivo: str = ''          # por qué no se puede elegir (vacío si se puede)

    @property
    def disponible(self):
        return not self.motivo


def hijos_de(tutor, ciclo=None):
    """Los estudiantes con los que el tutor tiene un vínculo activo, con su inscripción del ciclo actual y, si no se
    pueden elegir para un aviso, por qué."""
    ciclo = ciclo if ciclo is not None else ciclo_actual()
    vinculos = list(
        TutorAlumno.objects.filter(tutor=tutor, activo=True).select_related('alumno')
        .order_by('alumno__nombre', 'alumno__apellido_paterno')
    )
    inscripciones = {}
    if ciclo is not None:
        inscripciones = {
            inscripcion.alumno_id: inscripcion
            for inscripcion in Inscripcion.objects.filter(ciclo=ciclo, activa=True, alumno__in=[v.alumno_id for v in vinculos])
            .select_related('ciclo', 'grado', 'grupo__grado', 'grupo__nombre')
        }
    hijos = []
    for vinculo in vinculos:
        inscripcion = inscripciones.get(vinculo.alumno_id)
        if tutor.estatus != 'ACTIVO':
            motivo = 'Tu cuenta de tutor no está activa.'
        elif vinculo.alumno.estatus != 'ACTIVO':
            motivo = 'No está activo en el colegio.'
        elif inscripcion is None:
            motivo = 'No tiene inscripción en el ciclo escolar actual.'
        elif not (vinculo.tutor_principal or vinculo.autorizado_recoger):
            motivo = ('No tienes permiso para gestionar sus retiros: el colegio debe registrarte como tutor principal o '
                      'autorizado para recogerlo.')
        else:
            motivo = ''
        hijos.append(Hijo(vinculo.alumno, vinculo, inscripcion, motivo))
    return hijos


def autorizados_para(alumno_ids):
    """{id de estudiante: {id de tutor: vínculo}}: quién está autorizado en el sistema para recoger a cada uno (vínculo
    activo marcado «Autorizado para recoger al estudiante», tutor activo)."""
    autorizados = defaultdict(dict)
    vinculos = TutorAlumno.objects.filter(
        alumno_id__in=list(alumno_ids), activo=True, autorizado_recoger=True, tutor__estatus='ACTIVO',
    ).select_related('tutor')
    for vinculo in vinculos:
        autorizados[vinculo.alumno_id][vinculo.tutor_id] = vinculo
    return autorizados


def autorizados_para_todos(alumno_ids, autorizados=None):
    """Los ids de los tutores autorizados para recoger a todos esos estudiantes."""
    alumno_ids = list(alumno_ids)
    if not alumno_ids:
        return set()
    autorizados = autorizados if autorizados is not None else autorizados_para(alumno_ids)
    return set.intersection(*(set(autorizados.get(pk, {})) for pk in alumno_ids))


def esta_autorizado(tutor, alumno):
    return TutorAlumno.objects.filter(
        tutor=tutor, alumno=alumno, activo=True, autorizado_recoger=True, tutor__estatus='ACTIVO').exists()


# ---------------------------------------------------------------------------
# Horario del estudiante
# ---------------------------------------------------------------------------
def horario_del_dia(inscripcion, fecha):
    """((inicio, fin), None) de las clases del estudiante ese día, o (None, por qué no tiene clases)."""
    motivo = motivo_sin_clases(fecha, inscripcion.ciclo, nivel=inscripcion.grado.nivel)
    if motivo:
        return None, motivo.rstrip('.')
    clases = clases_del_dia(inscripcion.grupo, inscripcion.ciclo, fecha)
    if not clases:
        return None, 'no tiene clases en su horario ese día'
    return (min(clase.inicio for clase in clases), max(clase.fin for clase in clases)), None


def problema_de_horario(inscripcion, fecha, hora):
    """Por qué esa hora no es un retiro anticipado para el estudiante (texto), o None si es válida."""
    horario, motivo = horario_del_dia(inscripcion, fecha)
    nombre = inscripcion.alumno.nombre
    if horario is None:
        return f'{nombre}: {motivo[:1].lower()}{motivo[1:]}.'
    inicio, fin = horario
    if not inicio <= hora < fin:
        return (f'{nombre}: sus clases de ese día son de {_hora(inicio)} a {_hora(fin)}; un retiro anticipado debe ser '
                f'dentro de ese horario, antes de las {_hora(fin)}.')
    return None


# ---------------------------------------------------------------------------
# Aviso del tutor
# ---------------------------------------------------------------------------
def _momento(fecha, hora):
    return timezone.make_aware(datetime.combine(fecha, hora), timezone.get_current_timezone())


def evento(aviso, tipo, descripcion, estudiante=None, usuario=None, tutor=None, datos=None):
    return EventoRetiro.objects.create(aviso=aviso, estudiante=estudiante, tipo=tipo, descripcion=descripcion,
                                       usuario=usuario, tutor=tutor, datos=datos or {})


def avisar(tutor, alumno_ids, fecha, hora, motivo, detalles, recoge):
    """Registra el aviso y lo notifica al personal. RetiroRechazado con todos los problemas si no se puede."""
    hora = hora.replace(second=0, microsecond=0)
    detalles = (detalles or '').strip()
    ahora = timezone.localtime()
    if _momento(fecha, hora) <= ahora:
        raise RetiroRechazado('La fecha y la hora del retiro ya pasaron: elige un momento futuro.')
    ciclo = ciclo_actual()
    if ciclo is None or not ciclo.fecha_inicio <= fecha <= ciclo.fecha_fin:
        raise RetiroRechazado('Esa fecha queda fuera del ciclo escolar actual.')
    if motivo is None or not motivo.activo:
        raise RetiroRechazado('Elige un motivo de la lista.')
    if motivo.requiere_explicacion and not detalles:
        raise RetiroRechazado(f'El motivo «{motivo}» requiere que escribas los detalles del retiro.')

    hijos = {hijo.alumno.pk: hijo for hijo in hijos_de(tutor, ciclo)}
    elegidos = []
    for pk in dict.fromkeys(alumno_ids):
        hijo = hijos.get(pk)
        if hijo is None or not hijo.disponible:   # la pantalla no lo ofrece: la petición se alteró
            raise RetiroRechazado('Solo puedes avisar el retiro de tus propios hijos, cuando tienes permiso vigente para gestionarlo.')
        elegidos.append(hijo)
    if not elegidos:
        raise RetiroRechazado('Elige al menos un estudiante.')

    problemas = [problema_de_horario(hijo.inscripcion, fecha, hora) for hijo in elegidos]
    activos = RetiroEstudiante.objects.filter(alumno__in=[h.alumno for h in elegidos], fecha=fecha, estado=AVISADO).select_related('aviso', 'alumno')
    for activo in activos:
        problemas.append(f'{activo.alumno.nombre} ya tiene un aviso activo para ese día (folio {activo.aviso.folio}, a las '
                         f'{_hora(activo.aviso.hora)}). Si cambió algo, cancela ese aviso y registra otro.')
    if recoge is None or recoge.pk not in autorizados_para_todos([h.alumno.pk for h in elegidos]):
        problemas.append('Quien recogerá debe tener autorización del colegio para recoger a todos los estudiantes elegidos.')
    if any(problemas):
        raise RetiroRechazado(*problemas)

    try:
        with transaction.atomic():
            aviso = AvisoRetiro.objects.create(tutor=tutor, fecha=fecha, hora=hora, motivo=motivo, detalles=detalles, recoge=recoge)
            retiros = [RetiroEstudiante.objects.create(aviso=aviso, alumno=h.alumno, inscripcion=h.inscripcion, fecha=fecha)
                       for h in elegidos]
            nombres = _lista(nombre_de(h.alumno) for h in elegidos)
            evento(aviso, EventoRetiro.CREADO,
                   f'{nombre_de(tutor)} avisó el retiro de {nombres} el {_fecha(fecha)} a las {_hora(hora)} ({motivo}). '
                   f'Recogerá: {"el mismo tutor" if recoge == tutor else nombre_de(recoge)}.', tutor=tutor)
            notificaciones.al_personal(
                aviso, retiros, 'Nuevo aviso de retiro',
                f'{nombres} · {_fecha(fecha)} a las {_hora(hora)} · {motivo}')
    except IntegrityError:   # otro aviso del mismo estudiante y día entró al mismo tiempo
        raise RetiroRechazado('Uno de los estudiantes ya tiene un aviso activo para ese día. Revisa tus avisos.') from None
    return aviso


def cancelar_por_tutor(aviso, tutor, retiro_ids, motivo=''):
    """El tutor cancela algunos (o todos) sus estudiantes todavía avisados. Devuelve los cancelados."""
    if aviso.tutor_id != tutor.pk:
        raise RetiroRechazado('Solo quien registró el aviso puede cancelarlo.')
    return _cancelar(aviso, retiro_ids, (motivo or '').strip(), tutor=tutor)


def cancelar_por_personal(aviso, usuario, retiro_ids, motivo):
    motivo = (motivo or '').strip()
    if not motivo:
        raise RetiroRechazado('Escribe el motivo de la cancelación: el tutor lo verá.')
    return _cancelar(aviso, retiro_ids, motivo, usuario=usuario)


def _cancelar(aviso, retiro_ids, motivo, tutor=None, usuario=None):
    with transaction.atomic():
        retiros = list(RetiroEstudiante.objects.select_for_update().filter(aviso=aviso, pk__in=list(retiro_ids)).select_related('alumno'))
        confirmados = [r for r in retiros if r.estado == RETIRADO]
        if confirmados:
            raise RetiroRechazado(f'La salida de {_lista(r.alumno.nombre for r in confirmados)} ya se confirmó: no se puede cancelar.')
        pendientes = [r for r in retiros if r.estado == AVISADO]
        if not pendientes:
            raise RetiroRechazado('No hay estudiantes por cancelar en este aviso.')
        ahora = timezone.now()
        for retiro in pendientes:
            retiro.estado, retiro.cancelado_en, retiro.motivo_cancelacion = CANCELADO, ahora, motivo
            retiro.cancelado_por_tutor, retiro.cancelado_por_usuario = tutor, usuario
            retiro.save(update_fields=['estado', 'cancelado_en', 'motivo_cancelacion', 'cancelado_por_tutor', 'cancelado_por_usuario'])
            quien = nombre_de(tutor) if tutor else nombre_de_usuario(usuario)
            evento(aviso, EventoRetiro.CANCELADO,
                   f'{quien} canceló el retiro de {nombre_de(retiro.alumno)}.' + (f' Motivo: {motivo}' if motivo else ''),
                   estudiante=retiro, usuario=usuario, tutor=tutor)
        nombres = _lista(r.alumno.nombre for r in pendientes)
        if tutor is not None:
            notificaciones.al_personal(aviso, pendientes, 'Retiro cancelado por el tutor',
                                       f'{nombres} · {_fecha(aviso.fecha)} a las {_hora(aviso.hora)} · folio {aviso.folio}')
        else:
            notificaciones.al_tutor(aviso, 'El colegio canceló un retiro', f'{nombres} · folio {aviso.folio}. Motivo: {motivo}')
            notificaciones.al_personal(aviso, pendientes, 'Retiro cancelado', f'{nombres} · folio {aviso.folio}', excluir=usuario)
    return pendientes


# ---------------------------------------------------------------------------
# Salida real (personal)
# ---------------------------------------------------------------------------
def _validar_salida(retiro, recogio, momento):
    problemas = []
    if recogio is None or not esta_autorizado(recogio, retiro.alumno):
        problemas.append(f'Quien recoge debe tener autorización en el sistema para recoger a {retiro.alumno.nombre}.')
    momento_local = timezone.localtime(momento)
    if momento_local.date() != retiro.fecha:
        problemas.append(f'La salida debe ser del día del retiro ({_fecha(retiro.fecha)}).')
    elif momento > timezone.now() + TOLERANCIA_DEL_RELOJ:
        problemas.append('La hora de salida no puede ser futura.')
    if problemas:
        raise RetiroRechazado(*problemas)


def confirmar_salida(retiro, usuario, recogio, momento, observaciones=''):
    """El personal confirma que el estudiante salió con una persona autorizada. Una sola vez por estudiante."""
    with transaction.atomic():
        retiro = RetiroEstudiante.objects.select_for_update().select_related('aviso', 'alumno').get(pk=retiro.pk)
        if retiro.estado == RETIRADO:
            raise RetiroRechazado(f'La salida de {retiro.alumno.nombre} ya se había confirmado.')
        if retiro.estado == CANCELADO:
            raise RetiroRechazado(f'El retiro de {retiro.alumno.nombre} se canceló: no se puede confirmar su salida.')
        _validar_salida(retiro, recogio, momento)
        retiro.estado, retiro.salida_en, retiro.recogio = RETIRADO, momento, recogio
        retiro.confirmado_por, retiro.confirmado_en = usuario, timezone.now()
        retiro.observaciones_salida = (observaciones or '').strip()
        retiro.save(update_fields=['estado', 'salida_en', 'recogio', 'confirmado_por', 'confirmado_en', 'observaciones_salida'])
        hora = _hora(timezone.localtime(momento))
        evento(retiro.aviso, EventoRetiro.CONFIRMADO,
               f'{nombre_de_usuario(usuario)} confirmó la salida de {nombre_de(retiro.alumno)} a las {hora}, con '
               f'{nombre_de(recogio)}.' + (f' Observaciones: {retiro.observaciones_salida}' if retiro.observaciones_salida else ''),
               estudiante=retiro, usuario=usuario)
        notificaciones.al_tutor(retiro.aviso, f'{retiro.alumno.nombre} ya salió del colegio',
                                f'Salió a las {hora} con {nombre_de(recogio)} · folio {retiro.aviso.folio}')
    return retiro


def corregir_salida(retiro, usuario, motivo, deshacer=False, recogio=None, momento=None, observaciones=''):
    """Corrige una salida confirmada (o la deshace: el estudiante vuelve a Avisado). Guarda lo que había y lo que quedó."""
    motivo = (motivo or '').strip()
    if not motivo:
        raise RetiroRechazado('Escribe el motivo de la corrección: queda en la bitácora.')
    try:
        with transaction.atomic():
            retiro = RetiroEstudiante.objects.select_for_update().select_related('aviso', 'alumno', 'recogio').get(pk=retiro.pk)
            if retiro.estado != RETIRADO:
                raise RetiroRechazado('Solo se corrigen salidas ya confirmadas.')
            antes = _datos_de_salida(retiro)
            if deshacer:
                retiro.estado, retiro.salida_en, retiro.recogio = AVISADO, None, None
                retiro.confirmado_por = retiro.confirmado_en = None
                retiro.observaciones_salida = ''
                descripcion = f'{nombre_de_usuario(usuario)} deshizo la salida confirmada de {nombre_de(retiro.alumno)} (vuelve a Avisado).'
                titulo, texto = f'Se corrigió la salida de {retiro.alumno.nombre}', f'El colegio la dejó otra vez como «Avisado» · folio {retiro.aviso.folio}'
            else:
                _validar_salida(retiro, recogio, momento)
                retiro.salida_en, retiro.recogio, retiro.observaciones_salida = momento, recogio, (observaciones or '').strip()
                descripcion = f'{nombre_de_usuario(usuario)} corrigió la salida de {nombre_de(retiro.alumno)}.'
                hora = _hora(timezone.localtime(momento))
                titulo, texto = f'Se corrigió la salida de {retiro.alumno.nombre}', f'Salió a las {hora} con {nombre_de(recogio)} · folio {retiro.aviso.folio}'
            retiro.save()
            despues = _datos_de_salida(retiro)
            evento(retiro.aviso, EventoRetiro.CORREGIDO, f'{descripcion} Motivo: {motivo}', estudiante=retiro, usuario=usuario,
                   datos={'antes': antes, 'despues': despues, 'motivo': motivo})
            notificaciones.al_tutor(retiro.aviso, titulo, texto)
    except IntegrityError:   # deshacer chocaría con otro aviso activo del mismo día
        raise RetiroRechazado(f'{retiro.alumno.nombre} ya tiene otro aviso activo ese día: no se puede volver a «Avisado».') from None
    return retiro


def _datos_de_salida(retiro):
    return {
        'estado': NOMBRE_DE_ESTADO[retiro.estado],
        'hora': _hora(timezone.localtime(retiro.salida_en)) if retiro.salida_en else '',
        'recogio': nombre_de(retiro.recogio) if retiro.recogio_id else '',
        'observaciones': retiro.observaciones_salida,
    }


def agregar_nota(aviso, usuario, texto):
    texto = (texto or '').strip()
    if not texto:
        raise RetiroRechazado('Escribe la observación.')
    return NotaInterna.objects.create(aviso=aviso, autor=usuario, texto=texto[:1000])


# ---------------------------------------------------------------------------
# Para mostrar
# ---------------------------------------------------------------------------
def estado_general(retiros):
    """(clave, nombre) del aviso completo: Avisado si alguien sigue pendiente; Cancelado si se cancelaron todos;
    Retirado si ya no queda nadie pendiente y al menos uno salió."""
    estados = {r.estado for r in retiros}
    if AVISADO in estados:
        return AVISADO, NOMBRE_DE_ESTADO[AVISADO]
    if estados and estados <= {CANCELADO}:
        return CANCELADO, NOMBRE_DE_ESTADO[CANCELADO]
    return RETIRADO, NOMBRE_DE_ESTADO[RETIRADO]


def es_proximo(aviso, retiros, hoy=None):
    """Si el aviso sigue por venir (hoy o después, con alguien todavía avisado)."""
    hoy = hoy or timezone.localdate()
    return aviso.fecha >= hoy and any(r.estado == AVISADO for r in retiros)
