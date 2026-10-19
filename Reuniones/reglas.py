"""Las reglas de las reuniones con familias: todo cambio de una reunión pasa por aquí (las vistas solo validan formatos).

- **Registro**: la llamada se anota con el tutor, sus estudiantes (con el grupo que tienen hoy), con quién quiere
  reunirse, el motivo, la prioridad y los horarios que propone. Queda «Solicitada» o, si ya tiene personal asignado,
  «Pendiente de programación». Registrar una llamada nunca confirma una cita.
- **Acompañante directivo**: toda reunión con un docente necesita al menos un acompañante autorizado (dirección,
  coordinación académica o prefectura de esos niveles), aunque el tutor pida hablar solo con el maestro. Se puede guardar
  pendiente de asignarlo, pero la cita no queda confirmada sin él (confirmado y libre), no se inicia con un docente sin
  un acompañante presente y no se registra como realizada si no estuvo durante toda la reunión. Uno solo puede acompañar
  a varios docentes. Si falta o deja de estar disponible: se asigna un sustituto autorizado y libre, o se reprograma.
- **Horario**: dentro del horario de atención, sin cruces con otras reuniones activas (personal, tutores y sala) ni con
  las clases de los docentes (disponibilidad.py).
- **Confirmaciones**: la del tutor (quién la recibió, cuándo y por qué medio, o desde su portal) y la de cada
  participante, por separado. La cita queda «Confirmada» sola cuando están todas; si después alguien deja de estar
  disponible o se quita al acompañante, vuelve a «Programada, pendiente de confirmación» y se avisa al responsable.
- **Reprogramar** guarda la fecha anterior, la nueva, el motivo y quién lo hizo (CambioDeFecha); nada se sobrescribe.
- **Inasistencia**: queda registrado quién faltó (tutor, docente o acompañante).
- **Minuta y acuerdos**: la minuta separa las notas internas confidenciales de lo que se comparte con la familia; cada
  acuerdo tiene responsable, fecha límite, estado y seguimiento.

Nada de esto cambia calificaciones, asistencias ni genera sanciones.
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from Alumnos.academico import ciclo_actual
from Alumnos.models import Inscripcion, TutorAlumno

from . import notificaciones
from .alcance import inscripciones_de, puede_acompanar
from .disponibilidad import disponibilidad_de, nombre_de_persona, nombre_de_usuario, problemas_de
from .models import (
    AUSENTE, PRESENTE, Acuerdo, AdjuntoReunion, CambioDeFecha, ContactoReunion, EstudianteEnReunion, EventoReunion, Minuta,
    ParticipanteReunion, Reunion, SeguimientoAcuerdo, TutorEnReunion,
)

TONO_DE_ESTADO = {
    Reunion.SOLICITADA: '', Reunion.PENDIENTE: 'tag--warning', Reunion.PROGRAMADA: 'tag--info', Reunion.CONFIRMADA: 'tag--primary',
    Reunion.EN_CURSO: 'tag--info', Reunion.REALIZADA: 'tag--success', Reunion.CANCELADA: '', Reunion.NO_REALIZADA: 'tag--danger',
}
ICONO_DE_ESTADO = {
    Reunion.SOLICITADA: 'phone', Reunion.PENDIENTE: 'clock', Reunion.PROGRAMADA: 'calendar', Reunion.CONFIRMADA: 'check-check',
    Reunion.EN_CURSO: 'users', Reunion.REALIZADA: 'circle-check', Reunion.CANCELADA: 'circle-x', Reunion.NO_REALIZADA: 'triangle-alert',
}
TONO_DE_PRIORIDAD = {Reunion.NORMAL: '', Reunion.ALTA: 'tag--warning', Reunion.URGENTE: 'tag--danger'}
TONO_DE_ACUERDO = {Acuerdo.PENDIENTE: 'tag--warning', Acuerdo.EN_PROCESO: 'tag--info', Acuerdo.CUMPLIDO: 'tag--success', Acuerdo.VENCIDO: 'tag--danger'}


class ReglaRota(Exception):
    def __init__(self, mensajes):
        self.mensajes = [mensajes] if isinstance(mensajes, str) else list(mensajes)
        super().__init__(' '.join(self.mensajes))


def _evento(reunion, tipo, descripcion, usuario=None, tutor=None):
    return EventoReunion.objects.create(reunion=reunion, tipo=tipo, descripcion=descripcion, usuario=usuario, tutor=tutor)


def _ahora():
    return timezone.now()


def inscripcion_vigente(alumno):
    """La inscripción del ciclo actual del estudiante (con su nivel, grado y grupo), o None."""
    ciclo = ciclo_actual()
    if ciclo is None:
        return None
    return (Inscripcion.objects.filter(alumno=alumno, ciclo=ciclo, activa=True)
            .select_related('grado', 'grupo__grado', 'grupo__nombre').first())


def _activos(reunion):
    return list(reunion.participantes.filter(activo=True).select_related('usuario'))


def _lista(nombres):
    nombres = list(nombres)
    if not nombres:
        return ''
    return nombres[0] if len(nombres) == 1 else f'{", ".join(nombres[:-1])} y {nombres[-1]}'


def _papel(participante):
    return participante.get_papel_display().lower()


# ---------------------------------------------------------------------------
# El acompañante directivo y lo que falta para confirmar
# ---------------------------------------------------------------------------
def acompanamiento_pendiente(reunion, activos=None):
    """Por qué la reunión todavía no cumple la regla del acompañante directivo (lista vacía si la cumple o no tiene
    docentes). La confirmación de cada participante se revisa aparte."""
    activos = _activos(reunion) if activos is None else activos
    if not any(p.es_docente for p in activos):
        return []
    acompanantes = [p for p in activos if p.es_acompanante]
    if not acompanantes:
        return ['Falta asignar un acompañante directivo: toda reunión con un docente necesita uno.']
    inscripciones = inscripciones_de(reunion)
    if not any(puede_acompanar(p.usuario, inscripciones) for p in acompanantes):
        return ['El acompañante asignado ya no está autorizado para estos niveles: asigna a otro.']
    return []


def faltantes(reunion):
    """Lo que falta para que la cita quede confirmada (lista vacía si nada)."""
    if not reunion.programada:
        return ['Falta programar la fecha, el horario y la sala.']
    activos = _activos(reunion)
    faltan = []
    if not activos:
        faltan.append('Falta asignar al personal que atenderá la reunión.')
    faltan += acompanamiento_pendiente(reunion, activos)
    if reunion.confirmacion_tutor_id is None:
        faltan.append('Falta registrar la confirmación del tutor.')
    for participante in activos:
        nombre = nombre_de_usuario(participante.usuario)
        if participante.confirmacion == ParticipanteReunion.NO_DISPONIBLE:
            faltan.append(f'{nombre} ({_papel(participante)}) no está disponible: sustitúyelo, quítalo o reprograma.')
        elif participante.confirmacion != ParticipanteReunion.CONFIRMADA:
            faltan.append(f'Falta que {nombre} ({_papel(participante)}) confirme su disponibilidad.')
    faltan += problemas_de(reunion, reunion.fecha, reunion.hora_inicio, reunion.hora_fin, reunion.sala, usuarios=[p.usuario for p in activos],
                           con_horario=False)
    return faltan


def actualizar_estado(reunion, usuario=None):
    """Confirma la cita cuando ya no falta nada, o la regresa a pendiente de confirmación si algo dejó de cumplirse."""
    if reunion.estado not in (Reunion.PROGRAMADA, Reunion.CONFIRMADA):
        return reunion.estado
    faltan = faltantes(reunion)
    if not faltan and reunion.estado == Reunion.PROGRAMADA:
        reunion.estado = Reunion.CONFIRMADA
        reunion.save(update_fields=['estado', 'modificada'])
        _evento(reunion, EventoReunion.CONFIRMADA, 'Quedó confirmada: confirmaron el tutor y todo el personal'
                + (', con su acompañante directivo.' if any(p.es_docente for p in _activos(reunion)) else '.'), usuario)
        notificaciones.confirmada(reunion, usuario)
    elif faltan and reunion.estado == Reunion.CONFIRMADA:
        reunion.estado = Reunion.PROGRAMADA
        reunion.save(update_fields=['estado', 'modificada'])
        _evento(reunion, EventoReunion.PENDIENTE_CONFIRMAR, 'Volvió a «pendiente de confirmación»: ' + ' '.join(faltan), usuario)
        notificaciones.requiere_atencion(reunion, usuario, faltan[0])
    return reunion.estado


# ---------------------------------------------------------------------------
# Registro de la solicitud
# ---------------------------------------------------------------------------
def _validar_personal(docentes, acompanantes, personal, inscripciones, area):
    errores = []
    docentes, acompanantes, personal = list(docentes), list(acompanantes), list(personal)
    if area == Reunion.DOCENTE and not docentes:
        errores.append('Elige al docente con quien quiere reunirse el tutor.')
    for usuario in acompanantes:
        if usuario in docentes:
            errores.append(f'{nombre_de_usuario(usuario)} no puede ser docente y acompañante de la misma reunión.')
        elif not puede_acompanar(usuario, inscripciones):
            errores.append(f'{nombre_de_usuario(usuario)} no está autorizado como acompañante directivo de estos niveles.')
    return errores


@transaction.atomic
def registrar(*, tutor, alumnos, telefono, area, motivo, descripcion, usuario, telefono_verificado=False,
              prioridad=Reunion.NORMAL, propuestas=(), observaciones='', docentes=(), acompanante=None, responsable=None,
              otros_tutores=()):
    """Registra la solicitud de la llamada. No programa ni confirma nada."""
    alumnos = list(alumnos)
    if not alumnos:
        raise ReglaRota('Elige al menos a un estudiante del tutor.')
    vinculados = set(TutorAlumno.objects.filter(tutor=tutor, activo=True).values_list('alumno_id', flat=True))
    if any(a.pk not in vinculados for a in alumnos):
        raise ReglaRota('Solo se pueden elegir estudiantes vinculados al tutor.')
    inscripciones = {a.pk: inscripcion_vigente(a) for a in alumnos}
    acompanantes = [acompanante] if acompanante else []
    errores = _validar_personal(docentes, acompanantes, [], [i for i in inscripciones.values() if i], area)
    if errores:
        raise ReglaRota(errores)

    reunion = Reunion.objects.create(
        tutor=tutor, telefono=telefono, telefono_verificado=telefono_verificado, area=area, motivo=motivo, descripcion=descripcion,
        prioridad=prioridad, propuestas=list(propuestas), observaciones_internas=observaciones, registrada_por=usuario,
        responsable=responsable or acompanante,
    )
    EstudianteEnReunion.objects.bulk_create([EstudianteEnReunion(reunion=reunion, alumno=a, inscripcion=inscripciones[a.pk]) for a in alumnos])
    TutorEnReunion.objects.create(reunion=reunion, tutor=tutor, solicitante=True)
    hermanos = set(TutorAlumno.objects.filter(alumno__in=alumnos, activo=True).values_list('tutor_id', flat=True))
    TutorEnReunion.objects.bulk_create([TutorEnReunion(reunion=reunion, tutor=t) for t in otros_tutores if t.pk != tutor.pk and t.pk in hermanos])

    asignados = []
    for docente in docentes:
        asignados.append(ParticipanteReunion(reunion=reunion, usuario=docente, papel=ParticipanteReunion.DOCENTE, agregado_por=usuario))
    for acomp in acompanantes:
        asignados.append(ParticipanteReunion(reunion=reunion, usuario=acomp, papel=ParticipanteReunion.ACOMPANANTE, agregado_por=usuario))
    if reunion.responsable and reunion.responsable not in [p.usuario for p in asignados]:
        asignados.append(ParticipanteReunion(reunion=reunion, usuario=reunion.responsable, papel=ParticipanteReunion.PERSONAL, agregado_por=usuario))
    ParticipanteReunion.objects.bulk_create(asignados)
    if asignados:
        reunion.estado = Reunion.PENDIENTE
        reunion.save(update_fields=['estado'])

    detalle = f'Registró la llamada de {nombre_de_persona(tutor)} ({reunion.get_area_display()}, prioridad {reunion.get_prioridad_display().lower()}).'
    if docentes and not acompanantes:
        detalle += ' Queda pendiente de asignar al acompañante directivo.'
    _evento(reunion, EventoReunion.REGISTRADA, detalle, usuario)
    if asignados:
        notificaciones.asignada(reunion, [p.usuario for p in asignados], usuario)
    return reunion


# ---------------------------------------------------------------------------
# Participantes
# ---------------------------------------------------------------------------
@transaction.atomic
def definir_participantes(reunion, *, docentes, acompanantes, personal, responsable, tutores, usuario):
    """Cambia el personal (docentes, acompañantes, otro personal y responsable) y los tutores que asisten. Lo que se
    quita no se borra: queda en el historial."""
    if reunion.estado not in (Reunion.SOLICITADA, Reunion.PENDIENTE, Reunion.PROGRAMADA, Reunion.CONFIRMADA):
        raise ReglaRota('Los participantes solo se cambian antes de iniciar la reunión.')
    docentes, acompanantes, personal = list(docentes), list(acompanantes), list(personal)
    inscripciones = inscripciones_de(reunion)
    errores = _validar_personal(docentes, acompanantes, personal, inscripciones, reunion.area)
    for u in personal:
        if u in docentes or u in acompanantes:
            errores.append(f'{nombre_de_usuario(u)} aparece dos veces: elige un solo papel.')
    if errores:
        raise ReglaRota(errores)

    deseado = {}
    for papel, usuarios in ((ParticipanteReunion.DOCENTE, docentes), (ParticipanteReunion.ACOMPANANTE, acompanantes),
                            (ParticipanteReunion.PERSONAL, personal)):
        for u in usuarios:
            deseado.setdefault(u.pk, (u, papel))
    if responsable is not None:
        deseado.setdefault(responsable.pk, (responsable, ParticipanteReunion.PERSONAL))

    actuales = {p.usuario_id: p for p in _activos(reunion)}
    ahora = _ahora()
    quitados, agregados = [], []
    for usuario_id, participante in actuales.items():
        if usuario_id not in deseado or deseado[usuario_id][1] != participante.papel:
            participante.activo, participante.retirado_en = False, ahora
            participante.retirado_motivo = (f'Se quitó de la reunión ({nombre_de_usuario(usuario)})' if usuario_id not in deseado
                                            else 'Cambió de papel')[:300]
            participante.save(update_fields=['activo', 'retirado_en', 'retirado_motivo'])
            quitados.append(participante)
    nuevos = [(u, papel) for usuario_id, (u, papel) in deseado.items()
              if usuario_id not in actuales or actuales[usuario_id] in quitados]
    if reunion.programada and reunion.estado in Reunion.ACTIVAS and nuevos:
        problemas = problemas_de(reunion, reunion.fecha, reunion.hora_inicio, reunion.hora_fin, None,
                                 usuarios=[u for u, _ in nuevos], tutores=[], con_horario=False)
        if problemas:
            raise ReglaRota(problemas)
    for u, papel in nuevos:
        agregados.append(ParticipanteReunion.objects.create(reunion=reunion, usuario=u, papel=papel, agregado_por=usuario))

    # Los tutores: el solicitante siempre; los demás, solo tutores activos de sus estudiantes
    validos = set(TutorAlumno.objects.filter(alumno__in=reunion.estudiantes.values('alumno'), activo=True).values_list('tutor_id', flat=True))
    pedidos = {t.pk for t in tutores if t.pk in validos} | {reunion.tutor_id}
    actuales_tutores = set(reunion.tutores.values_list('tutor_id', flat=True))
    reunion.tutores.exclude(tutor_id__in=pedidos).delete()
    TutorEnReunion.objects.bulk_create([TutorEnReunion(reunion=reunion, tutor_id=t) for t in pedidos - actuales_tutores])

    reunion.responsable = responsable
    if reunion.estado == Reunion.SOLICITADA and deseado:
        reunion.estado = Reunion.PENDIENTE
    reunion.save(update_fields=['responsable', 'estado', 'modificada'])

    partes = []
    if agregados:
        partes.append('Agregó a ' + _lista(f'{nombre_de_usuario(p.usuario)} ({_papel(p)})' for p in agregados))
    if quitados:
        partes.append('quitó a ' + _lista(f'{nombre_de_usuario(p.usuario)} ({_papel(p)})' for p in quitados))
    if pedidos != actuales_tutores:
        partes.append('actualizó los tutores que asisten')
    partes.append(f'responsable: {nombre_de_usuario(responsable) if responsable else "sin asignar"}')
    _evento(reunion, EventoReunion.PARTICIPANTES, ('; '.join(partes) + '.').capitalize(), usuario)
    if agregados:
        notificaciones.asignada(reunion, [p.usuario for p in agregados], usuario)
    if reunion.programada and pedidos - actuales_tutores:
        notificaciones.a_la_familia(reunion, 'Cita programada: confirma tu asistencia')
    actualizar_estado(reunion, usuario)
    return reunion


# ---------------------------------------------------------------------------
# Programar y reprogramar
# ---------------------------------------------------------------------------
def _validar_horario(reunion, fecha, inicio, fin, sala):
    errores = []
    ahora = timezone.localtime()
    if fecha < ahora.date():
        errores.append('La fecha ya pasó.')
    elif fecha == ahora.date() and inicio <= ahora.time():
        errores.append('Esa hora ya pasó.')
    if fin <= inicio:
        errores.append('La hora de término debe ser posterior a la de inicio.')
    if sala is None:
        errores.append('Elige el lugar o la sala.')
    elif not sala.activo:
        errores.append(f'{sala} ya no se usa: elige otra sala.')
    if not reunion.participantes.filter(activo=True).exists():
        errores.append('Asigna primero al personal que atenderá la reunión.')
    if errores:
        raise ReglaRota(errores)
    problemas = problemas_de(reunion, fecha, inicio, fin, sala)
    if problemas:
        raise ReglaRota(problemas)


def _reiniciar_confirmaciones(reunion):
    reunion.participantes.filter(activo=True).update(confirmacion=ParticipanteReunion.PENDIENTE, confirmacion_en=None,
                                                     confirmacion_por=None, confirmacion_nota='', asistencia='', presente_toda=False)
    reunion.tutores.update(asistencia='')
    reunion.confirmacion_tutor = None


@transaction.atomic
def programar(reunion, *, fecha, inicio, fin, sala, usuario):
    if reunion.estado not in Reunion.SIN_PROGRAMAR:
        raise ReglaRota('Esta reunión ya tiene fecha: usa «Reprogramar».')
    _validar_horario(reunion, fecha, inicio, fin, sala)
    reunion.fecha, reunion.hora_inicio, reunion.hora_fin, reunion.sala = fecha, inicio, fin, sala
    _reiniciar_confirmaciones(reunion)
    reunion.estado = Reunion.PROGRAMADA
    reunion.save()
    _evento(reunion, EventoReunion.PROGRAMADA, f'Programó la cita: {notificaciones.cuando(reunion)}.', usuario)
    notificaciones.programada(reunion, usuario)
    if acompanamiento_pendiente(reunion):
        _evento(reunion, EventoReunion.PROGRAMADA, 'No se podrá confirmar mientras falte el acompañante directivo.', usuario)
    return reunion


@transaction.atomic
def reprogramar(reunion, *, fecha, inicio, fin, sala, motivo, usuario):
    if reunion.estado not in Reunion.ACTIVAS:
        raise ReglaRota('Solo se reprograma una reunión programada, confirmada o en curso.')
    if not (motivo or '').strip():
        raise ReglaRota('Escribe el motivo de la reprogramación.')
    if (fecha, inicio, fin, sala) == (reunion.fecha, reunion.hora_inicio, reunion.hora_fin, reunion.sala):
        raise ReglaRota('Elige una fecha, un horario o una sala distintos de los actuales.')
    _validar_horario(reunion, fecha, inicio, fin, sala)
    CambioDeFecha.objects.create(
        reunion=reunion, fecha_anterior=reunion.fecha, inicio_anterior=reunion.hora_inicio, fin_anterior=reunion.hora_fin,
        sala_anterior=reunion.sala, fecha_nueva=fecha, inicio_nuevo=inicio, fin_nuevo=fin, sala_nueva=sala, motivo=motivo.strip(),
        usuario=usuario,
    )
    anterior = notificaciones.cuando(reunion)
    reunion.fecha, reunion.hora_inicio, reunion.hora_fin, reunion.sala = fecha, inicio, fin, sala
    _reiniciar_confirmaciones(reunion)
    reunion.estado, reunion.iniciada_en = Reunion.PROGRAMADA, None
    reunion.save()
    _evento(reunion, EventoReunion.REPROGRAMADA,
            f'Reprogramó la cita. Antes: {anterior}. Ahora: {notificaciones.cuando(reunion)}. Motivo: {motivo.strip()}', usuario)
    notificaciones.reprogramada(reunion, usuario)
    return reunion


# ---------------------------------------------------------------------------
# Confirmaciones y avisos
# ---------------------------------------------------------------------------
@transaction.atomic
def confirmar_disponibilidad(participante, *, disponible, nota='', usuario):
    reunion = participante.reunion
    if reunion.estado not in (Reunion.PROGRAMADA, Reunion.CONFIRMADA):
        raise ReglaRota('La disponibilidad se confirma cuando la reunión ya está programada.')
    if not participante.activo:
        raise ReglaRota('Esa persona ya no participa en la reunión.')
    nota = (nota or '').strip()
    nombre = nombre_de_usuario(participante.usuario)
    if disponible:
        problemas = disponibilidad_de(participante.usuario, reunion)
        if problemas:
            raise ReglaRota([f'{nombre} no está libre en ese horario.', *problemas])
        if participante.es_acompanante and not puede_acompanar(participante.usuario, inscripciones_de(reunion)):
            raise ReglaRota(f'{nombre} ya no está autorizado como acompañante directivo de estos niveles.')
        participante.confirmacion = ParticipanteReunion.CONFIRMADA
    else:
        if not nota:
            raise ReglaRota('Escribe por qué no está disponible.')
        participante.confirmacion = ParticipanteReunion.NO_DISPONIBLE
    participante.confirmacion_en, participante.confirmacion_por, participante.confirmacion_nota = _ahora(), usuario, nota[:300]
    participante.save(update_fields=['confirmacion', 'confirmacion_en', 'confirmacion_por', 'confirmacion_nota'])
    texto = f'{nombre} ({_papel(participante)}) ' + ('confirmó su disponibilidad' if disponible else f'no está disponible: {nota}')
    if usuario is not None and usuario.pk != participante.usuario_id:
        texto += f' (lo registró {nombre_de_usuario(usuario)})'
    _evento(reunion, EventoReunion.DISPONIBILIDAD, texto + '.', usuario)
    if not disponible and participante.es_acompanante and reunion.estado == Reunion.PROGRAMADA:
        notificaciones.requiere_atencion(reunion, usuario, 'El acompañante directivo no está disponible: asigna un sustituto o reprograma')
    actualizar_estado(reunion, usuario)
    return participante


@transaction.atomic
def confirmar_tutor(reunion, *, medio, momento, recibio=None, nota='', usuario=None, tutor=None):
    """La confirmación del tutor: por teléfono (u otro medio) la anota el personal; desde el portal, el propio tutor."""
    if reunion.estado not in (Reunion.PROGRAMADA, Reunion.CONFIRMADA):
        raise ReglaRota('Solo se confirma una reunión programada.')
    tutor = tutor or reunion.tutor
    contacto = ContactoReunion.objects.create(
        reunion=reunion, tipo=ContactoReunion.CONFIRMACION, medio=medio, tutor=tutor, recibio=recibio, momento=momento,
        nota=(nota or '')[:500], registrado_por=usuario,
    )
    reunion.confirmacion_tutor = contacto
    reunion.save(update_fields=['confirmacion_tutor', 'modificada'])
    if usuario is None:
        texto = f'{nombre_de_persona(tutor)} confirmó su asistencia desde el portal.'
    else:
        texto = (f'{nombre_de_persona(tutor)} confirmó su asistencia ({contacto.get_medio_display().lower()}). La recibió '
                 f'{nombre_de_usuario(recibio)} el {timezone.localtime(momento):%d/%m/%Y a las %H:%M}.')
    _evento(reunion, EventoReunion.CONFIRMACION_TUTOR, texto, usuario, tutor=tutor if usuario is None else None)
    actualizar_estado(reunion, usuario)
    return contacto


@transaction.atomic
def registrar_aviso(reunion, *, medio, momento, nota='', tutor=None, usuario):
    """Un aviso a la familia hecho por teléfono u otro medio (el sistema no envía correos ni mensajes: solo se anota)."""
    tutor = tutor or reunion.tutor
    contacto = ContactoReunion.objects.create(reunion=reunion, tipo=ContactoReunion.AVISO, medio=medio, tutor=tutor, recibio=usuario,
                                              momento=momento, nota=(nota or '')[:500], registrado_por=usuario)
    _evento(reunion, EventoReunion.AVISO, f'Avisó a {nombre_de_persona(tutor)} ({contacto.get_medio_display().lower()}, '
                                          f'{timezone.localtime(momento):%d/%m/%Y %H:%M}){": " + nota if nota else "."}', usuario)
    return contacto


# ---------------------------------------------------------------------------
# Acompañante sustituto
# ---------------------------------------------------------------------------
@transaction.atomic
def asignar_sustituto(reunion, *, nuevo, ausente=None, motivo, usuario):
    """Cuando el acompañante falta o deja de estar disponible: otro autorizado y libre en ese horario."""
    if reunion.estado not in Reunion.ACTIVAS:
        raise ReglaRota('El sustituto se asigna a una reunión programada, confirmada o en curso.')
    motivo = (motivo or '').strip()
    if not motivo:
        raise ReglaRota('Escribe por qué se sustituye al acompañante.')
    nombre = nombre_de_usuario(nuevo)
    if not puede_acompanar(nuevo, inscripciones_de(reunion)):
        raise ReglaRota(f'{nombre} no está autorizado como acompañante directivo de estos niveles.')
    actual = reunion.participantes.filter(activo=True, usuario=nuevo).first()
    if actual is not None and actual.es_docente:
        raise ReglaRota(f'{nombre} participa como docente: no puede ser también el acompañante.')
    if ausente is not None and (ausente.reunion_id != reunion.pk or not ausente.activo or not ausente.es_acompanante):
        raise ReglaRota('Elige a un acompañante de esta reunión.')
    if ausente is not None and ausente.usuario_id == nuevo.pk:
        raise ReglaRota('El sustituto debe ser otra persona.')
    problemas = disponibilidad_de(nuevo, reunion)
    if problemas:
        raise ReglaRota([f'{nombre} no está libre en ese horario.', *problemas])

    ahora = _ahora()
    en_curso = reunion.estado == Reunion.EN_CURSO
    if ausente is not None:
        ausente.activo, ausente.retirado_en = False, ahora
        ausente.retirado_motivo = f'Sustituido: {motivo}'[:300]
        if reunion.fecha <= timezone.localdate() and not ausente.asistencia:
            ausente.asistencia = AUSENTE
        ausente.save(update_fields=['activo', 'retirado_en', 'retirado_motivo', 'asistencia'])
    if actual is not None:
        actual.activo, actual.retirado_en, actual.retirado_motivo = False, ahora, 'Pasó a ser el acompañante directivo'
        actual.save(update_fields=['activo', 'retirado_en', 'retirado_motivo'])
    ParticipanteReunion.objects.create(
        reunion=reunion, usuario=nuevo, papel=ParticipanteReunion.ACOMPANANTE, sustituye_a=ausente, agregado_por=usuario,
        confirmacion=ParticipanteReunion.CONFIRMADA, confirmacion_en=ahora, confirmacion_por=usuario,
        confirmacion_nota='Asignado como sustituto', asistencia=PRESENTE if en_curso else '',
    )
    texto = f'Asignó a {nombre} como acompañante directivo sustituto'
    if ausente is not None:
        texto += f' de {nombre_de_usuario(ausente.usuario)}'
    _evento(reunion, EventoReunion.SUSTITUTO, f'{texto}. Motivo: {motivo}', usuario)
    notificaciones.al_personal(reunion, 'Te asignaron como acompañante de una reunión con familia', usuarios=[nuevo], excluir=usuario)
    actualizar_estado(reunion, usuario)
    return reunion


# ---------------------------------------------------------------------------
# Realización
# ---------------------------------------------------------------------------
def _acompanante_presente(reunion, presentes, inscripciones=None):
    inscripciones = inscripciones_de(reunion) if inscripciones is None else inscripciones
    return [p for p in presentes if p.es_acompanante and puede_acompanar(p.usuario, inscripciones)]


@transaction.atomic
def iniciar(reunion, *, presentes, tutores_presentes, usuario):
    """Registra la asistencia real y la inicia. `presentes`: ids de los participantes que llegaron; `tutores_presentes`:
    ids de TutorEnReunion."""
    if reunion.estado not in (Reunion.PROGRAMADA, Reunion.CONFIRMADA):
        raise ReglaRota('Solo se inicia una reunión programada o confirmada.')
    if reunion.fecha != timezone.localdate():
        raise ReglaRota('La reunión se inicia el día de la cita. Si cambió la fecha, reprográmala.')
    presentes, tutores_presentes = set(presentes), set(tutores_presentes)
    activos = _activos(reunion)
    invitados = list(reunion.tutores.select_related('tutor'))
    if not any(t.pk in tutores_presentes for t in invitados):
        raise ReglaRota('Marca al menos a un tutor presente. Si la familia no llegó, regístrala como no realizada por inasistencia.')
    llegaron = [p for p in activos if p.pk in presentes]
    if not llegaron:
        raise ReglaRota('Marca al personal del colegio que está presente.')
    if any(p.es_docente for p in llegaron) and not _acompanante_presente(reunion, llegaron):
        raise ReglaRota('No se puede iniciar una reunión con un docente sin un acompañante directivo autorizado presente. '
                        'Asigna un acompañante sustituto disponible o reprograma la reunión.')
    for participante in activos:
        participante.asistencia = PRESENTE if participante.pk in presentes else AUSENTE
        participante.save(update_fields=['asistencia'])
    for invitado in invitados:
        invitado.asistencia = PRESENTE if invitado.pk in tutores_presentes else AUSENTE
        invitado.save(update_fields=['asistencia'])
    reunion.estado, reunion.iniciada_en = Reunion.EN_CURSO, _ahora()
    reunion.save(update_fields=['estado', 'iniciada_en', 'modificada'])
    faltaron = [nombre_de_usuario(p.usuario) for p in activos if p.pk not in presentes]
    faltaron += [nombre_de_persona(t.tutor) for t in invitados if t.pk not in tutores_presentes]
    _evento(reunion, EventoReunion.INICIADA, 'Inició la reunión y registró la asistencia.'
            + (f' No llegaron: {_lista(faltaron)}.' if faltaron else ' Llegaron todos.'), usuario)
    return reunion


def _guardar_minuta(reunion, minuta, datos, usuario, puede_confidencial):
    minuta.inicio_real, minuta.fin_real = datos['inicio_real'], datos['fin_real']
    minuta.temas, minuta.resumen = datos['temas'], datos['resumen']
    minuta.siguiente_reunion = datos.get('siguiente_reunion', False)
    minuta.siguiente_reunion_nota = datos.get('siguiente_reunion_nota', '') if minuta.siguiente_reunion else ''
    if puede_confidencial:
        minuta.notas_internas = datos.get('notas_internas', '')
    if minuta.pk is None:
        minuta.registrada_por = usuario
    minuta.modificada_por = usuario
    minuta.save()
    return minuta


@transaction.atomic
def finalizar(reunion, *, datos, presentes_toda, usuario, puede_confidencial):
    """Registra la minuta y deja la reunión como realizada. `presentes_toda`: ids de los acompañantes que estuvieron
    durante toda la reunión."""
    if reunion.estado != Reunion.EN_CURSO:
        raise ReglaRota('Primero inicia la reunión y registra la asistencia.')
    if datos['fin_real'] <= datos['inicio_real']:
        raise ReglaRota('La hora real de término debe ser posterior a la de inicio.')
    presentes = list(reunion.participantes.filter(asistencia=PRESENTE).select_related('usuario'))
    presentes_toda = set(presentes_toda)
    if any(p.es_docente for p in presentes):
        acompanantes = [p for p in _acompanante_presente(reunion, presentes) if p.pk in presentes_toda]
        if not acompanantes:
            raise ReglaRota('Una reunión con docentes solo se registra como realizada si un acompañante directivo autorizado estuvo '
                            'presente durante toda la reunión. Márcalo o, si no fue así, reprograma la reunión.')
    for participante in presentes:
        if participante.es_acompanante:
            participante.presente_toda = participante.pk in presentes_toda
            participante.save(update_fields=['presente_toda'])
    _guardar_minuta(reunion, Minuta(reunion=reunion), datos, usuario, puede_confidencial)
    reunion.estado, reunion.terminada_en = Reunion.REALIZADA, _ahora()
    reunion.save(update_fields=['estado', 'terminada_en', 'modificada'])
    _evento(reunion, EventoReunion.REALIZADA, f'Registró la minuta: de {datos["inicio_real"]:%H:%M} a {datos["fin_real"]:%H:%M}.', usuario)
    return reunion


@transaction.atomic
def editar_minuta(reunion, *, datos, usuario, puede_confidencial):
    if reunion.estado != Reunion.REALIZADA or not hasattr(reunion, 'minuta'):
        raise ReglaRota('Solo se edita la minuta de una reunión realizada.')
    if datos['fin_real'] <= datos['inicio_real']:
        raise ReglaRota('La hora real de término debe ser posterior a la de inicio.')
    _guardar_minuta(reunion, reunion.minuta, datos, usuario, puede_confidencial)
    _evento(reunion, EventoReunion.MINUTA, 'Editó la minuta.', usuario)
    return reunion


@transaction.atomic
def marcar_inasistencia(reunion, *, tutores_ausentes, participantes_ausentes, nota, usuario):
    """La reunión no se hizo porque alguien faltó: queda quién (tutor, docente o acompañante)."""
    if reunion.estado not in (Reunion.PROGRAMADA, Reunion.CONFIRMADA):
        raise ReglaRota('Solo se registra la inasistencia de una reunión programada o confirmada.')
    if reunion.fecha > timezone.localdate():
        raise ReglaRota('La inasistencia se registra el día de la cita o después.')
    tutores_ausentes, participantes_ausentes = set(tutores_ausentes), set(participantes_ausentes)
    if not tutores_ausentes and not participantes_ausentes:
        raise ReglaRota('Marca quién faltó: el tutor, un docente o el acompañante directivo.')
    faltaron = []
    for invitado in reunion.tutores.select_related('tutor'):
        if invitado.pk in tutores_ausentes:
            invitado.asistencia = AUSENTE
            invitado.save(update_fields=['asistencia'])
            faltaron.append(f'{nombre_de_persona(invitado.tutor)} (tutor)')
    for participante in _activos(reunion):
        if participante.pk in participantes_ausentes:
            participante.asistencia = AUSENTE
            participante.save(update_fields=['asistencia'])
            faltaron.append(f'{nombre_de_usuario(participante.usuario)} ({_papel(participante)})')
    reunion.estado, reunion.motivo_cierre = Reunion.NO_REALIZADA, (nota or '').strip()
    reunion.cerrada_por, reunion.cerrada_en = usuario, _ahora()
    reunion.save(update_fields=['estado', 'motivo_cierre', 'cerrada_por', 'cerrada_en', 'modificada'])
    _evento(reunion, EventoReunion.INASISTENCIA, f'No se realizó por inasistencia. Faltó: {_lista(faltaron)}.'
            + (f' {reunion.motivo_cierre}' if reunion.motivo_cierre else ''), usuario)
    notificaciones.no_realizada(reunion, usuario)
    return reunion


def quienes_faltaron(reunion):
    """[(nombre, papel)] de quienes faltaron a una reunión no realizada (o a una realizada)."""
    faltaron = [(nombre_de_persona(t.tutor), 'Tutor') for t in reunion.tutores.select_related('tutor') if t.asistencia == AUSENTE]
    faltaron += [(nombre_de_usuario(p.usuario), p.get_papel_display()) for p in reunion.participantes.select_related('usuario')
                 if p.asistencia == AUSENTE]
    return faltaron


@transaction.atomic
def cancelar(reunion, *, motivo, usuario):
    if reunion.estado not in (Reunion.SOLICITADA, Reunion.PENDIENTE, Reunion.PROGRAMADA, Reunion.CONFIRMADA):
        raise ReglaRota('Esta reunión ya no se puede cancelar.')
    motivo = (motivo or '').strip()
    if not motivo:
        raise ReglaRota('Escribe el motivo de la cancelación.')
    reunion.estado, reunion.motivo_cierre, reunion.cerrada_por, reunion.cerrada_en = Reunion.CANCELADA, motivo, usuario, _ahora()
    reunion.save(update_fields=['estado', 'motivo_cierre', 'cerrada_por', 'cerrada_en', 'modificada'])
    _evento(reunion, EventoReunion.CANCELADA, f'Canceló la reunión. Motivo: {motivo}', usuario)
    notificaciones.cancelada(reunion, usuario)
    return reunion


@transaction.atomic
def programar_siguiente(reunion, *, usuario):
    """Una reunión nueva vinculada con esta (mismos tutores, estudiantes y personal), pendiente de programación."""
    if reunion.estado not in (Reunion.REALIZADA, Reunion.NO_REALIZADA, Reunion.CANCELADA):
        raise ReglaRota('La siguiente reunión se programa cuando esta ya terminó.')
    nueva = Reunion.objects.create(
        tutor=reunion.tutor, telefono=reunion.telefono, telefono_verificado=reunion.telefono_verificado, area=reunion.area,
        motivo=reunion.motivo, descripcion=f'Seguimiento de la reunión {reunion.folio}. {reunion.descripcion}'[:2000],
        prioridad=reunion.prioridad, registrada_por=usuario, responsable=reunion.responsable, reunion_anterior=reunion,
    )
    EstudianteEnReunion.objects.bulk_create([
        EstudianteEnReunion(reunion=nueva, alumno=e.alumno, inscripcion=inscripcion_vigente(e.alumno) or e.inscripcion)
        for e in reunion.estudiantes.select_related('alumno', 'inscripcion')])
    TutorEnReunion.objects.bulk_create([TutorEnReunion(reunion=nueva, tutor=t.tutor, solicitante=t.solicitante) for t in reunion.tutores.all()])
    personal = [p for p in _activos(reunion) if p.usuario.is_active]
    ParticipanteReunion.objects.bulk_create([ParticipanteReunion(reunion=nueva, usuario=p.usuario, papel=p.papel, agregado_por=usuario) for p in personal])
    if personal:
        nueva.estado = Reunion.PENDIENTE
        nueva.save(update_fields=['estado'])
    _evento(nueva, EventoReunion.VINCULADA, f'Se registró como seguimiento de la reunión {reunion.folio}.', usuario)
    _evento(reunion, EventoReunion.VINCULADA, f'Se registró la reunión de seguimiento {nueva.folio}.', usuario)
    if personal:
        notificaciones.asignada(nueva, [p.usuario for p in personal], usuario)
    return nueva


# ---------------------------------------------------------------------------
# Acuerdos y documentos
# ---------------------------------------------------------------------------
EDITABLES_DEL_ACUERDO = ('descripcion', 'quien', 'responsable', 'responsable_texto', 'fecha_limite', 'compartido')


@transaction.atomic
def guardar_acuerdo(reunion, *, datos, usuario, acuerdo=None):
    if reunion.estado not in (Reunion.EN_CURSO, Reunion.REALIZADA):
        raise ReglaRota('Los acuerdos se registran durante la reunión o después de realizarla.')
    nuevo = acuerdo is None
    acuerdo = acuerdo or Acuerdo(reunion=reunion, creado_por=usuario)
    for campo in EDITABLES_DEL_ACUERDO:
        if campo in datos:
            setattr(acuerdo, campo, datos[campo])
    acuerdo.save()
    _evento(reunion, EventoReunion.ACUERDO, f'{"Registró" if nuevo else "Editó"} el acuerdo «{acuerdo.descripcion[:80]}» '
                                            f'(responsable: {acuerdo.nombre_responsable}; fecha límite {acuerdo.fecha_limite:%d/%m/%Y}).', usuario)
    return acuerdo


@transaction.atomic
def seguir_acuerdo(acuerdo, *, estado, nota, usuario, evidencia=None, tipo_evidencia=''):
    nota = (nota or '').strip()
    if not nota:
        raise ReglaRota('Escribe la observación del seguimiento.')
    seguimiento = SeguimientoAcuerdo(acuerdo=acuerdo, estado=estado, nota=nota, usuario=usuario)
    if evidencia is not None:
        seguimiento.evidencia, seguimiento.evidencia_nombre, seguimiento.evidencia_tipo = evidencia, evidencia.name[:200], tipo_evidencia
    seguimiento.save()
    acuerdo.estado = estado
    acuerdo.cumplido_en = _ahora() if estado == Acuerdo.CUMPLIDO else None
    acuerdo.save(update_fields=['estado', 'cumplido_en'])
    _evento(acuerdo.reunion, EventoReunion.ACUERDO, f'Seguimiento del acuerdo «{acuerdo.descripcion[:80]}»: {acuerdo.get_estado_display().lower()}.', usuario)
    return seguimiento


@transaction.atomic
def agregar_documentos(reunion, *, archivos, clase, compartido, usuario):
    """`archivos`: [(archivo, tipo real)] ya validados."""
    if not archivos:
        raise ReglaRota('Elige al menos un archivo.')
    creados = [AdjuntoReunion.objects.create(reunion=reunion, archivo=archivo, nombre_original=archivo.name[:200], tipo=tipo, clase=clase,
                                             compartido=compartido, subido_por=usuario) for archivo, tipo in archivos]
    nombres = _lista(f'«{a.nombre_original}»' for a in creados)
    texto = f'Agregó {"la evidencia de firma" if clase == AdjuntoReunion.FIRMA else "documentos"}: {nombres}'
    _evento(reunion, EventoReunion.DOCUMENTO, texto + (' (compartidos con la familia).' if compartido else '.'), usuario)
    return creados


def proxima_hora(minutos=15):
    """La siguiente hora redonda (para sugerir el inicio al programar)."""
    ahora = timezone.localtime() + timedelta(minutes=minutos)
    return ahora.replace(minute=(ahora.minute // 15) * 15, second=0, microsecond=0).time()
