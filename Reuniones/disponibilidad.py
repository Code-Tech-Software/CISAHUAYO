"""La disponibilidad de una cita: el horario de atención, los cruces con otras reuniones activas (de cualquier
participante, tutor o de la sala) y las clases de los docentes (sus horarios del ciclo actual).

Solo cuentan las reuniones que ocupan su horario: programadas, confirmadas o en curso. Los mensajes dicen quién y a qué
hora, nunca el motivo de la otra reunión.

Al programar (2026-10-28) se sugieren los primeros horarios libres para todos (`horarios_libres`), empezando por los que
propuso el tutor.
"""
from datetime import date, datetime, time, timedelta

from django.utils import timezone
from django.utils.formats import date_format

from Alumnos.academico import ciclo_actual
from Alumnos.models import HorarioMateria

from .models import NOMBRE_DE_DIA, ConfiguracionReuniones, ParticipanteReunion, Reunion, SalaReunion, TutorEnReunion


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


# ---------------------------------------------------------------------------
# Horarios libres sugeridos al programar
# ---------------------------------------------------------------------------
PASO = timedelta(minutes=15)
DIAS_A_REVISAR = 15          # días de atención hacia adelante
MARGEN_DE_HOY = timedelta(minutes=30)


def _en(fecha, hora):
    return datetime.combine(fecha, hora)


def _se_cruza(inicio, fin, ocupados):
    return any(a < fin and b > inicio for a, b in ocupados)


def _ocupacion_del_dia(reunion, fecha, usuarios, tutores, ciclo):
    """(lo ocupado del personal y los tutores, lo ocupado de cada sala) ese día, como intervalos de datetime."""
    otras = Reunion.objects.filter(estado__in=Reunion.ACTIVAS, fecha=fecha).exclude(pk=reunion.pk)
    de_personas = []
    if usuarios:
        de_personas += ParticipanteReunion.objects.filter(reunion__in=otras, usuario__in=usuarios, activo=True).values_list(
            'reunion__hora_inicio', 'reunion__hora_fin')
    if tutores:
        de_personas += TutorEnReunion.objects.filter(reunion__in=otras, tutor__in=tutores).values_list('reunion__hora_inicio', 'reunion__hora_fin')
    if usuarios and ciclo is not None:
        from Alumnos.semanas import bloques_de_fecha
        de_personas += bloques_de_fecha(fecha, ciclo, materia_grado__profesor__usuario__in=usuarios).values_list('hora_inicio', 'hora_fin')
    por_sala = {}
    for sala_id, inicio, fin in otras.exclude(sala=None).values_list('sala_id', 'hora_inicio', 'hora_fin'):
        por_sala.setdefault(sala_id, []).append((_en(fecha, inicio), _en(fecha, fin)))
    return [(_en(fecha, a), _en(fecha, b)) for a, b in de_personas if a and b], por_sala


def _libres_del_dia(reunion, fecha, desde, hasta, duracion, salas, ocupacion, ahora):
    """Los horarios libres de ese día entre `desde` y `hasta` (cada 15 minutos), con la primera sala libre."""
    personas, por_sala = ocupacion
    inicio = _en(fecha, desde)
    if fecha == ahora.date():
        inicio = max(inicio, ahora.replace(tzinfo=None) + MARGEN_DE_HOY)
    # A la siguiente hora en punto, y cuarto, y media o menos cuarto
    if inicio.minute % 15 or inicio.second or inicio.microsecond:
        inicio = inicio.replace(second=0, microsecond=0) + timedelta(minutes=15 - inicio.minute % 15)
    limite = _en(fecha, hasta)
    while inicio + duracion <= limite and inicio.date() == fecha:
        fin = inicio + duracion
        mismo = reunion.programada and fecha == reunion.fecha and inicio.time() == reunion.hora_inicio
        if not mismo and not _se_cruza(inicio, fin, personas):
            sala = next((s for s in salas if not _se_cruza(inicio, fin, por_sala.get(s.pk, []))), None)
            if sala is not None:
                yield inicio.time(), fin.time(), sala
        inicio += PASO


def _hora_de_texto(texto):
    try:
        return time.fromisoformat(texto) if texto else None
    except ValueError:
        return None


def _fecha_de_texto(texto):
    try:
        return date.fromisoformat(texto)
    except (TypeError, ValueError):
        return None


DIAS_CORTOS = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']


def texto_de_horario(fecha, inicio, fin, sala):
    """«Lun 3 nov · 10:00 a 10:30 · Dirección»."""
    return f'{DIAS_CORTOS[fecha.weekday()]} {fecha.day} {date_format(fecha, "b")} · {_hora(inicio)} a {_hora(fin)} · {sala}'


def horarios_libres(reunion, *, cantidad=6, por_dia=2, ahora=None):
    """Los primeros horarios en que están libres todo el personal de la reunión, sus tutores y alguna sala: dentro del
    horario de atención, sin clases de los docentes ni días sin clases de todo el colegio. Primero, uno por cada horario
    que propuso el tutor (si está libre); luego, a lo más `por_dia` por día. [{fecha, inicio, fin, sala, texto,
    de_la_familia}]"""
    from Alumnos.asistencias import fechas_sin_clases
    configuracion = ConfiguracionReuniones.actual()
    ahora = timezone.localtime(ahora) if ahora else timezone.localtime()
    hoy = ahora.date()
    duracion = timedelta(minutes=reunion.duracion or configuracion.duracion)
    salas = list(SalaReunion.objects.filter(activo=True))
    if reunion.sala_id:   # la que ya tiene, primero
        salas.sort(key=lambda s: s.pk != reunion.sala_id)
    if not salas:
        return []
    usuarios, tutores, ciclo = personal_de(reunion), tutores_de(reunion), ciclo_actual()
    ultimo = hoy + timedelta(days=DIAS_A_REVISAR * 3)
    sin_clases = fechas_sin_clases(hoy, ultimo)
    dias = configuracion.dias or []
    ocupaciones = {}

    def ocupacion(fecha):
        if fecha not in ocupaciones:
            ocupaciones[fecha] = _ocupacion_del_dia(reunion, fecha, usuarios, tutores, ciclo)
        return ocupaciones[fecha]

    def atiende(fecha):
        return hoy <= fecha <= ultimo and fecha.weekday() in dias and fecha not in sin_clases

    sugeridos, tomados = [], set()

    def agregar(fecha, inicio, fin, sala, de_la_familia=False):
        tomados.add((fecha, inicio))
        sugeridos.append({'fecha': fecha, 'inicio': inicio, 'fin': fin, 'sala': sala, 'de_la_familia': de_la_familia,
                          'texto': texto_de_horario(fecha, inicio, fin, sala)})

    for propuesta in reunion.propuestas or []:
        fecha = _fecha_de_texto(propuesta.get('fecha'))
        if fecha is None or not atiende(fecha):
            continue
        desde = max(_hora_de_texto(propuesta.get('desde')) or configuracion.hora_apertura, configuracion.hora_apertura)
        hasta = min(_hora_de_texto(propuesta.get('hasta')) or configuracion.hora_cierre, configuracion.hora_cierre)
        libre = next(_libres_del_dia(reunion, fecha, desde, hasta, duracion, salas, ocupacion(fecha), ahora), None)
        if libre is not None and (fecha, libre[0]) not in tomados:
            agregar(fecha, *libre, de_la_familia=True)

    fecha, revisados = hoy, 0
    while len(sugeridos) < cantidad and revisados < DIAS_A_REVISAR and fecha <= ultimo:
        if atiende(fecha):
            revisados += 1
            del_dia = 0
            for libre in _libres_del_dia(reunion, fecha, configuracion.hora_apertura, configuracion.hora_cierre, duracion, salas,
                                         ocupacion(fecha), ahora):
                if (fecha, libre[0]) in tomados:
                    continue
                agregar(fecha, *libre)
                del_dia += 1
                if del_dia >= por_dia or len(sugeridos) >= cantidad:
                    break
        fecha += timedelta(days=1)
    return sugeridos
