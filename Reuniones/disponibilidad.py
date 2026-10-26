"""La disponibilidad de una cita: el horario de atención, los cruces con otras reuniones activas (de cualquier
participante, tutor o de la sala) y las clases de los docentes (sus horarios del ciclo actual).

Solo cuentan las reuniones que ocupan su horario: programadas, confirmadas o en curso. Los mensajes dicen quién y a qué
hora, nunca el motivo de la otra reunión.
"""
from datetime import datetime, timedelta

from Alumnos.academico import ciclo_actual
from Alumnos.models import HorarioMateria

from .models import NOMBRE_DE_DIA, ConfiguracionReuniones, ParticipanteReunion, Reunion, TutorEnReunion


def _hora(valor):
    return valor.strftime('%H:%M')


def nombre_de_usuario(usuario):
    return (usuario.get_full_name() or usuario.get_username()) if usuario else 'Alguien'


def nombre_de_persona(persona):
    return ' '.join(f'{persona.nombre} {persona.apellido_paterno} {persona.apellido_materno}'.split())


def fuera_de_horario(fecha, inicio, fin, configuracion=None):
    """Por qué la cita queda fuera del horario de atención de Ajustes › Reuniones (o una lista vacía)."""
    configuracion = configuracion or ConfiguracionReuniones.actual()
    problemas = []
    if fecha.weekday() not in (configuracion.dias or []):
        dias = ', '.join(configuracion.nombres_de_dias) or 'ninguno'
        problemas.append(f'El {NOMBRE_DE_DIA[fecha.weekday()].lower()} no es día de atención (días de atención: {dias.lower()}).')
    if inicio < configuracion.hora_apertura or fin > configuracion.hora_cierre:
        problemas.append(f'El horario de atención es de {_hora(configuracion.hora_apertura)} a {_hora(configuracion.hora_cierre)}.')
    return problemas


def _que_se_cruzan(fecha, inicio, fin, excluir=None):
    consulta = Reunion.objects.filter(estado__in=Reunion.ACTIVAS, fecha=fecha, hora_inicio__lt=fin, hora_fin__gt=inicio)
    if excluir is not None:
        consulta = consulta.exclude(pk=excluir)
    return consulta


def cruces(fecha, inicio, fin, *, sala=None, usuarios=(), tutores=(), excluir=None):
    """Las otras reuniones activas que chocan con ese horario para la sala, el personal o los tutores."""
    otras = _que_se_cruzan(fecha, inicio, fin, excluir)
    problemas = []
    if sala is not None:
        for otra in otras.filter(sala=sala).order_by('hora_inicio'):
            problemas.append(f'{sala} está ocupada de {_hora(otra.hora_inicio)} a {_hora(otra.hora_fin)} ({otra.folio}).')
    usuarios = [u for u in usuarios if u is not None]
    if usuarios:
        ocupados = (ParticipanteReunion.objects.filter(reunion__in=otras, usuario__in=usuarios, activo=True)
                    .select_related('usuario', 'reunion').order_by('reunion__hora_inicio'))
        for participante in ocupados:
            otra = participante.reunion
            problemas.append(f'{nombre_de_usuario(participante.usuario)} ya tiene otra reunión de {_hora(otra.hora_inicio)} '
                             f'a {_hora(otra.hora_fin)} ({otra.folio}).')
    tutores = [t for t in tutores if t is not None]
    if tutores:
        ocupados = (TutorEnReunion.objects.filter(reunion__in=otras, tutor__in=tutores)
                    .select_related('tutor', 'reunion').order_by('reunion__hora_inicio'))
        for invitado in ocupados:
            otra = invitado.reunion
            problemas.append(f'{nombre_de_persona(invitado.tutor)} ya tiene otra reunión de {_hora(otra.hora_inicio)} '
                             f'a {_hora(otra.hora_fin)} ({otra.folio}).')
    return problemas


def clases(fecha, inicio, fin, usuarios):
    """Las clases del ciclo actual que el personal (si es docente) imparte en ese horario."""
    usuarios = [u for u in usuarios if u is not None]
    ciclo = ciclo_actual()
    if not usuarios or ciclo is None:
        return []
    from Alumnos.semanas import bloques_de_fecha
    # Las de esa fecha: su semana A/B y la versión del horario (Alumnos/semanas.py)
    horarios = (bloques_de_fecha(fecha, ciclo, materia_grado__profesor__usuario__in=usuarios, hora_inicio__lt=fin, hora_fin__gt=inicio)
                .select_related('materia_grado__profesor__usuario', 'materia_grado__materia', 'materia_grado__grupo__grado',
                                'materia_grado__grupo__nombre')
                .order_by('hora_inicio'))
    problemas = []
    for horario in horarios:
        clase = horario.materia_grado
        problemas.append(f'{nombre_de_usuario(clase.profesor.usuario)} tiene clase de {clase.materia.nombre} con '
                         f'{clase.grupo} de {_hora(horario.hora_inicio)} a {_hora(horario.hora_fin)}.')
    return problemas


def personal_de(reunion):
    """Las cuentas del personal que participan (activas)."""
    return [p.usuario for p in reunion.participantes.filter(activo=True).select_related('usuario')]


def tutores_de(reunion):
    return [t.tutor for t in reunion.tutores.select_related('tutor')]


def problemas_de(reunion, fecha, inicio, fin, sala, *, usuarios=None, tutores=None, con_horario=True):
    """Todo lo que impide poner la reunión en ese horario (lista vacía si está libre)."""
    usuarios = personal_de(reunion) if usuarios is None else usuarios
    tutores = tutores_de(reunion) if tutores is None else tutores
    problemas = []
    if con_horario:
        problemas += fuera_de_horario(fecha, inicio, fin)
    problemas += cruces(fecha, inicio, fin, sala=sala, usuarios=usuarios, tutores=tutores, excluir=reunion.pk)
    problemas += clases(fecha, inicio, fin, usuarios)
    return problemas


def disponibilidad_de(usuario, reunion):
    """Por qué esa cuenta no está libre en el horario de la reunión (lista vacía si lo está)."""
    if not reunion.programada:
        return []
    return (cruces(reunion.fecha, reunion.hora_inicio, reunion.hora_fin, usuarios=[usuario], excluir=reunion.pk)
            + clases(reunion.fecha, reunion.hora_inicio, reunion.hora_fin, [usuario]))


def hora_fin_sugerida(inicio, minutos):
    """La hora de término con la duración predeterminada (sin pasar de la medianoche)."""
    fin = datetime.combine(datetime.min, inicio) + timedelta(minutes=minutos)
    return fin.time() if fin.date() == datetime.min.date() else inicio.replace(hour=23, minute=59)
