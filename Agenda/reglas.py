"""Las operaciones de la agenda (2026-10-27): reunir lo que ve cada persona, los eventos que se repiten, el historial de
cambios, los próximos eventos del inicio, la búsqueda y los archivos de calendario (un evento o la suscripción).

Eventos que se repiten: al registrarlo con «Repetir» se crean de una vez todos los de la serie (cada uno es un evento
normal: se ve, se busca, se recuerda y se exporta igual), hasta la fecha elegida (como máximo un año y 120 eventos).
Cada semana, cada dos semanas, cada mes el mismo día, el mismo día de la semana (el primer lunes) o el último (el último
viernes). Se pueden saltar los días sin clases. Al corregir, cancelar o eliminar uno se elige si aplica a ese o a ese y
los siguientes de la serie («los siguientes» son los que empezaban en su fecha o después, aunque se mueva de fecha).

Desde el 2026-11-02: para quién es (niveles, grados o grupos, familias y estudiantes), cancelar y avisar de los
cambios, archivos adjuntos y confirmación de asistencia de las familias.
"""
import calendar
import uuid
from datetime import date, time, timedelta

from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.safestring import mark_safe

from Mensajes import enriquecido

from . import alcance, fuentes
from .models import COLEGIO, VACACIONES, VARIOS, AdjuntoEvento, AvisoAgenda, ConfirmacionAsistencia, EventoAgenda, NivelEvento

SEMANAL, QUINCENAL, MENSUAL_DIA, MENSUAL_ORDINAL, MENSUAL_ULTIMO = 'SEMANAL', 'QUINCENAL', 'MENSUAL_DIA', 'MENSUAL_ORDINAL', 'MENSUAL_ULTIMO'
REPETICIONES = [
    (SEMANAL, 'Cada semana'),
    (QUINCENAL, 'Cada dos semanas'),
    (MENSUAL_DIA, 'Cada mes, el mismo día'),
    (MENSUAL_ORDINAL, 'Cada mes, el mismo día de la semana (p. ej. el primer lunes)'),
    (MENSUAL_ULTIMO, 'Cada mes, el último día de esa semana (p. ej. el último viernes)'),
]
MAXIMO_DE_LA_SERIE = 120
HASTA_UN_ANIO = 366
DIAS = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
ORDINALES = {1: 'primer', 2: 'segundo', 3: 'tercer', 4: 'cuarto'}
OTRO = 'OTRO'    # el filtro de tipo de los eventos sin tipo


# ---------------------------------------------------------------------------
# Lo que ve cada persona
# ---------------------------------------------------------------------------
def _del_tipo(tipo):
    return '' if tipo == OTRO else tipo


def eventos_de(persona, desde, hasta, filtro='', tipo='', curso=(None, None)):
    """Los eventos de la agenda (de sus niveles, con el filtro de nivel o de grado o grupo) y lo de otros módulos que ve
    esa persona entre esas fechas, con el filtro de tipo. Sin repetir lo que ya está como evento de la agenda (el
    comunicado con que se avisó de un evento, el día sin clases que cubre un evento de vacaciones)."""
    vista = persona.vista
    grado, grupo = curso
    if grado is not None:
        propios = alcance.filtrar_por_curso(vista.eventos(), grado, grupo)
        filtro = grado.nivel        # lo de otros módulos, del nivel de ese grado
    else:
        propios = vista.filtrar(vista.eventos(), filtro)
    propios = propios.filter(fecha_inicio__lte=hasta, fecha_fin__gte=desde).prefetch_related('niveles_varios', 'adjuntos')
    if tipo:
        propios = propios.filter(tipo=_del_tipo(tipo))
    propios = list(propios)
    externos = fuentes.externos(persona, desde, hasta, filtro)
    if tipo:
        externos = [evento for evento in externos if evento.tipo == _del_tipo(tipo)]
    return propios + sin_repetidos(propios, externos)


def sin_repetidos(propios, externos):
    avisados = {f'c{evento.comunicado_id}' for evento in propios if evento.comunicado_id}
    vacaciones = [evento for evento in propios if evento.tipo == VACACIONES and not evento.cancelado]

    def cubierto(externo):
        """Un día sin clases dentro de un evento de vacaciones de esos niveles (o de todo el colegio)."""
        if externo.fuente != 'sin_clases':
            return False
        niveles = set(externo.niveles)
        return any(v.fecha_inicio <= externo.fecha_inicio and v.fecha_fin >= externo.fecha_fin
                   and (v.alcance == COLEGIO or (niveles and niveles <= set(v.niveles_del_evento))) for v in vacaciones)

    return [evento for evento in externos if evento.pk not in avisados and not cubierto(evento)]


def dias_sin_clases_de(persona, desde, hasta, filtro=''):
    """{fecha: motivo} de los días sin clases (de lunes a viernes) que ve esa persona: para marcar sus casillas."""
    dias = {}
    for tramo in fuentes._seguro(fuentes.dias_sin_clases, persona, desde, hasta, filtro):
        fecha = max(tramo.fecha_inicio, desde)
        while fecha <= min(tramo.fecha_fin, hasta):
            if fecha.weekday() < 5:
                dias.setdefault(fecha, tramo.titulo.removeprefix('Sin clases: '))
            fecha += timedelta(days=1)
    return dias


def descripcion_html(evento):
    """La descripción en párrafos, con sus direcciones como enlaces (escapada)."""
    return mark_safe(enriquecido.texto_con_enlaces(evento.descripcion)) if evento.descripcion else ''


def texto_de_publico(evento):
    """«Personal, familias y estudiantes de Primaria · 3.º A»: para quién es (en el detalle y en el resumen)."""
    quienes = ['personal'] + (['familias'] if evento.para_familias else []) + (['estudiantes'] if evento.para_estudiantes else [])
    texto = (', '.join(quienes[:-1]) + ' y ' + quienes[-1]) if len(quienes) > 1 else quienes[0]
    texto = texto.capitalize() + (' de todo el colegio' if evento.alcance == COLEGIO else f' de {evento.nombre_alcance}')
    if evento.por_grupos and evento.pk:
        cursos = [str(grado) for grado in evento.grados.all()] + [str(grupo) for grupo in evento.grupos.all()]
        if cursos:
            texto += ' · solo ' + ', '.join(cursos)
    return texto


# ---------------------------------------------------------------------------
# Eventos que se repiten
# ---------------------------------------------------------------------------
def _mismo_dia_de_la_semana(anio, mes, dia_semana, ordinal):
    """El `ordinal`-ésimo `dia_semana` (0 = lunes) del mes; ordinal -1: el último. None si ese mes no lo tiene."""
    dias = [d for d in range(1, calendar.monthrange(anio, mes)[1] + 1) if date(anio, mes, d).weekday() == dia_semana]
    if ordinal == -1:
        return date(anio, mes, dias[-1])
    return date(anio, mes, dias[ordinal - 1]) if ordinal <= len(dias) else None


def _siguiente_mes(anio, mes):
    return (anio + 1, 1) if mes == 12 else (anio, mes + 1)


def fechas_de_la_serie(inicio, repetir, hasta, saltar=()):
    """Las fechas de inicio de cada evento de la serie (la primera es `inicio`), hasta `hasta` inclusive, sin las de
    `saltar` (como máximo MAXIMO_DE_LA_SERIE)."""
    fechas = []
    if repetir in (SEMANAL, QUINCENAL):
        paso = timedelta(days=7 if repetir == SEMANAL else 14)
        fecha = inicio
        while fecha <= hasta:
            fechas.append(fecha)
            fecha += paso
    else:
        ordinal = -1 if repetir == MENSUAL_ULTIMO else (inicio.day - 1) // 7 + 1
        anio, mes = inicio.year, inicio.month
        while True:
            if repetir == MENSUAL_DIA:
                fecha = date(anio, mes, inicio.day) if inicio.day <= calendar.monthrange(anio, mes)[1] else None
            else:
                fecha = _mismo_dia_de_la_semana(anio, mes, inicio.weekday(), ordinal)
            if fecha is not None and fecha > hasta:
                break
            if fecha is not None and fecha >= inicio:
                fechas.append(fecha)
            anio, mes = _siguiente_mes(anio, mes)
            if date(anio, mes, 1) > hasta:
                break
    saltar = set(saltar)
    return [fecha for fecha in fechas if fecha == inicio or fecha not in saltar][:MAXIMO_DE_LA_SERIE]


def texto_de_repeticion(inicio, repetir, hasta):
    """«Cada lunes hasta el 30 de junio de 2027», «Cada mes, el último viernes…»."""
    dia = DIAS[inicio.weekday()]
    texto = {
        SEMANAL: f'Cada {dia}',
        QUINCENAL: f'Cada dos semanas, en {dia}',
        MENSUAL_DIA: f'Cada mes, el día {inicio.day}',
        MENSUAL_ORDINAL: f'Cada mes, el {ORDINALES.get(min((inicio.day - 1) // 7 + 1, 4))} {dia}',
        MENSUAL_ULTIMO: f'Cada mes, el último {dia}',
    }[repetir]
    return f'{texto} hasta el {date_format(hasta, "j \\d\\e F \\d\\e Y").lower()}'


def dias_a_saltar(niveles, desde, hasta):
    """Los días sin clases de esos niveles entre esas fechas: los de todo el colegio y, con un solo nivel, también los
    de ese nivel."""
    from Alumnos.asistencias import fechas_sin_clases
    if len(niveles) == 1:
        return fechas_sin_clases(desde, hasta, niveles[0])
    return fechas_sin_clases(desde, hasta, None)


# ---------------------------------------------------------------------------
# Para quién y sus archivos
# ---------------------------------------------------------------------------
def poner_destino(evento, niveles=(), grados=(), grupos=()):
    """Los niveles (de uno de varios niveles), los grados y los grupos del evento ya guardado."""
    if evento.alcance == VARIOS:
        NivelEvento.objects.filter(evento=evento).exclude(nivel__in=niveles).delete()
        NivelEvento.objects.bulk_create([NivelEvento(evento=evento, nivel=nivel) for nivel in niveles], ignore_conflicts=True)
    else:
        NivelEvento.objects.filter(evento=evento).delete()
    evento.grados.set(grados)
    evento.grupos.set(grupos)


def destino_de(evento):
    """(niveles, grados, grupos) de un evento guardado, para copiarlo a otro."""
    return evento.niveles_del_evento, list(evento.grados.all()), list(evento.grupos.all())


def guardar_adjuntos(evento, archivos):
    """Guarda los archivos nuevos (ya validados: [(archivo, tipo)])."""
    for archivo, tipo in archivos:
        nombre = (archivo.name or 'archivo').replace('\\', '/').rsplit('/', 1)[-1][:200]
        AdjuntoEvento.objects.create(evento=evento, archivo=archivo, nombre_original=nombre, tipo=tipo, tamano=archivo.size)


def copiar_adjuntos(origen, eventos):
    """Los mismos archivos guardados para otros eventos (los de su serie): no se suben otra vez."""
    adjuntos = list(origen.adjuntos.all())
    AdjuntoEvento.objects.bulk_create([AdjuntoEvento(evento=evento, archivo=a.archivo.name, nombre_original=a.nombre_original,
                                                     tipo=a.tipo, tamano=a.tamano) for evento in eventos for a in adjuntos])


# ---------------------------------------------------------------------------
# Registrar, corregir, cancelar y eliminar
# ---------------------------------------------------------------------------
@transaction.atomic
def crear(evento, usuario, repetir='', hasta=None, saltar_sin_clases=False, destino=((), (), ()), archivos=()):
    """Guarda un evento nuevo (con `repetir`, toda su serie) con su destino (niveles, grados, grupos) y sus archivos.
    Devuelve los eventos creados."""
    niveles, grados, grupos = destino
    evento.creado_por = evento.modificado_por = usuario
    evento.por_grupos = bool(grados or grupos)
    if not repetir:
        evento.save()
        poner_destino(evento, niveles, grados, grupos)
        guardar_adjuntos(evento, archivos)
        registrar(usuario, evento, 'alta', f'Registró el evento ({evento.texto_de_fechas}).')
        _recordar_si_es_pronto([evento])
        return [evento]
    saltar = dias_a_saltar(list(niveles) or evento.niveles_del_evento, evento.fecha_inicio, hasta) if saltar_sin_clases else ()
    duracion = evento.fecha_fin - evento.fecha_inicio
    serie, texto = uuid.uuid4(), texto_de_repeticion(evento.fecha_inicio, repetir, hasta)
    creados = []
    for fecha in fechas_de_la_serie(evento.fecha_inicio, repetir, hasta, saltar):
        copia = EventoAgenda(
            titulo=evento.titulo, descripcion=evento.descripcion, alcance=evento.alcance, tipo=evento.tipo, fecha_inicio=fecha,
            fecha_fin=fecha + duracion, todo_el_dia=evento.todo_el_dia, hora_inicio=evento.hora_inicio, hora_fin=evento.hora_fin,
            lugar=evento.lugar, importante=evento.importante, recordar_dias=evento.recordar_dias, para_familias=evento.para_familias,
            para_estudiantes=evento.para_estudiantes, por_grupos=evento.por_grupos, pide_confirmacion=evento.pide_confirmacion,
            serie=serie, repeticion=texto, creado_por=usuario, modificado_por=usuario,
        )
        copia.save()
        poner_destino(copia, niveles, grados, grupos)
        creados.append(copia)
    guardar_adjuntos(creados[0], archivos)
    copiar_adjuntos(creados[0], creados[1:])
    registrar(usuario, creados[0], 'alta', f'Registró el evento con {len(creados)} fechas ({texto}).')
    _recordar_si_es_pronto(creados[:1])
    return creados


def _recordar_si_es_pronto(eventos):
    """Un evento importante que se registra (o se mueve) para cuando ya toca recordarlo se recuerda en ese momento, sin
    esperar a la siguiente revisión (Agenda/recordatorios.py)."""
    hoy = timezone.localdate()
    if any(e.importante and e.recordatorio_en is None and not e.cancelado and e.fecha_inicio <= hoy + timedelta(days=e.recordar_dias)
           and e.fecha_fin >= hoy for e in eventos):
        from . import recordatorios
        transaction.on_commit(lambda: recordatorios._en_segundo_plano(recordatorios.generar_sin_fallar))


def siguientes_de_la_serie(evento, desde=None):
    """Ese evento y los de su serie que empiezan en `desde` (por omisión, su fecha) o después."""
    if not evento.serie:
        return EventoAgenda.objects.filter(pk=evento.pk)
    return EventoAgenda.objects.filter(Q(pk=evento.pk) | Q(serie=evento.serie, fecha_inicio__gte=desde or evento.fecha_inicio))


CAMPOS_DE_LA_SERIE = ('titulo', 'descripcion', 'alcance', 'tipo', 'todo_el_dia', 'hora_inicio', 'hora_fin', 'lugar', 'importante',
                      'recordar_dias', 'para_familias', 'para_estudiantes', 'por_grupos', 'pide_confirmacion')
CAMPOS_QUE_SE_AVISAN = ('fecha_inicio', 'fecha_fin', 'todo_el_dia', 'hora_inicio', 'hora_fin', 'lugar')


def que_cambio(anterior, evento):
    """Lo que cambió de lo que importa a quien asiste («Nueva fecha: …», «Nuevo horario: …», «Nuevo lugar: …»)."""
    partes = []
    if (anterior['fecha_inicio'], anterior['fecha_fin']) != (evento.fecha_inicio, evento.fecha_fin):
        partes.append(f'Nueva fecha: {evento.texto_de_fechas.lower()}')
    if (anterior['todo_el_dia'], anterior['hora_inicio'], anterior['hora_fin']) != (evento.todo_el_dia, evento.hora_inicio, evento.hora_fin):
        partes.append(f'Nuevo horario: {evento.texto_de_horario.lower()}')
    if anterior['lugar'] != evento.lugar:
        partes.append(f'Nuevo lugar: {evento.lugar}' if evento.lugar else 'Ya no tiene lugar indicado')
    return ' · '.join(partes)


@transaction.atomic
def guardar_cambios(evento, usuario, toda_la_serie=False, destino=None, archivos=(), quitar=(), avisar=False):
    """Guarda lo corregido; con `toda_la_serie`, también en los siguientes de la serie (sus fechas no cambian). Con
    `avisar`, si cambió la fecha, el horario o el lugar de un evento que no ha pasado, se avisa a quienes lo ven.
    Devuelve cuántos otros eventos de la serie cambiaron."""
    evento.modificado_por = usuario
    anterior = EventoAgenda.objects.filter(pk=evento.pk).values(*CAMPOS_QUE_SE_AVISAN).first()
    if destino is not None:
        evento.por_grupos = bool(destino[1] or destino[2])
    if anterior is not None and anterior['fecha_inicio'] != evento.fecha_inicio:
        # Cambió de fecha: se vuelve a recordar para la nueva (el recordatorio de la fecha anterior ya no sirve)
        evento.recordatorio_en = None
        AvisoAgenda.objects.filter(evento=evento, tipo=AvisoAgenda.RECORDATORIO).delete()
    evento.save()
    if destino is not None:
        poner_destino(evento, *destino)
    for adjunto in evento.adjuntos.filter(pk__in=quitar):
        adjunto.delete()     # el archivo guardado se conserva: otros eventos de su serie pueden usarlo
    guardar_adjuntos(evento, archivos)
    _recordar_si_es_pronto([evento])
    otros = []
    if toda_la_serie and evento.serie:
        # «Los siguientes» son los que empezaban en su fecha original o después, aunque este se haya movido
        desde = anterior['fecha_inicio'] if anterior else evento.fecha_inicio
        otros = list(siguientes_de_la_serie(evento, desde).exclude(pk=evento.pk))
        cambios = {campo: getattr(evento, campo) for campo in CAMPOS_DE_LA_SERIE}
        EventoAgenda.objects.filter(pk__in=[e.pk for e in otros]).update(modificado_por=usuario, modificado=timezone.now(), **cambios)
        for otro in otros:
            otro.alcance = evento.alcance
            poner_destino(otro, *(destino or destino_de(evento)))
    cambio = que_cambio(anterior, evento) if anterior else ''
    if avisar and cambio and evento.fecha_fin >= timezone.localdate() and not evento.cancelado:
        from . import recordatorios
        recordatorios.avisar(evento, AvisoAgenda.CAMBIO, cambio + (' (también en las siguientes fechas de la serie)' if otros else ''))
    registrar(usuario, evento, 'cambio', 'Corrigió el evento' + (f' y {len(otros)} siguiente{"s" if len(otros) != 1 else ""} de su serie' if otros else '')
              + (f'. {cambio}.' if cambio else '.'))
    return len(otros)


@transaction.atomic
def cancelar(evento, usuario, motivo='', y_siguientes=False, avisar=True):
    """Lo deja en la agenda, tachado y con su motivo (con `y_siguientes`, también los siguientes de su serie). Se avisa a
    quienes lo ven si no ha pasado. Devuelve cuántos se cancelaron."""
    consulta = (siguientes_de_la_serie(evento) if y_siguientes else EventoAgenda.objects.filter(pk=evento.pk)).filter(cancelado_en__isnull=True)
    total = consulta.update(cancelado_en=timezone.now(), cancelado_por=usuario, motivo_cancelacion=motivo[:200], modificado_por=usuario)
    evento.refresh_from_db()
    if avisar and total and evento.fecha_fin >= timezone.localdate():
        from . import recordatorios
        texto = (motivo or 'Se canceló este evento.') + (' También las siguientes fechas de la serie.' if total > 1 else '')
        recordatorios.avisar(evento, AvisoAgenda.CANCELADO, texto)
    registrar(usuario, evento, 'cambio', 'Canceló el evento' + (f' y {total - 1} siguiente{"s" if total - 1 != 1 else ""} de su serie' if total > 1 else '')
              + (f'. Motivo: {motivo}.' if motivo else '.'))
    return total


@transaction.atomic
def reactivar(evento, usuario):
    """Deshace la cancelación de ese evento."""
    EventoAgenda.objects.filter(pk=evento.pk).update(cancelado_en=None, cancelado_por=None, motivo_cancelacion='', modificado_por=usuario)
    AvisoAgenda.objects.filter(evento=evento, tipo=AvisoAgenda.CANCELADO).delete()
    registrar(usuario, evento, 'cambio', 'Volvió a activar el evento cancelado.')


@transaction.atomic
def eliminar(evento, usuario, y_siguientes=False):
    """Elimina el evento (con `y_siguientes`, también los siguientes de su serie). Devuelve cuántos."""
    consulta = siguientes_de_la_serie(evento) if y_siguientes else EventoAgenda.objects.filter(pk=evento.pk)
    total = consulta.count()
    registrar(usuario, evento, 'baja', 'Eliminó el evento' + (f' y {total - 1} siguiente{"s" if total - 1 != 1 else ""} de su serie.' if total > 1 else '.')
              + f' Era del {evento.texto_de_fechas.lower()}, para {evento.nombre_alcance}.')
    consulta.delete()
    return total


def valores_para_duplicar(evento):
    """Lo que el formulario de «Nuevo evento» trae ya escrito al duplicarlo."""
    niveles, grados, grupos = destino_de(evento)
    return {
        'titulo': evento.titulo, 'descripcion': evento.descripcion, 'alcance': [COLEGIO] if evento.alcance == COLEGIO else niveles,
        'tipo': evento.tipo, 'fecha_inicio': evento.fecha_inicio, 'fecha_fin': evento.fecha_fin, 'todo_el_dia': evento.todo_el_dia,
        'hora_inicio': evento.hora_inicio, 'hora_fin': evento.hora_fin, 'lugar': evento.lugar, 'importante': evento.importante,
        'recordar_dias': evento.recordar_dias, 'para_familias': evento.para_familias, 'para_estudiantes': evento.para_estudiantes,
        'grados': grados, 'grupos': grupos, 'pide_confirmacion': evento.pide_confirmacion,
    }


# ---------------------------------------------------------------------------
# Confirmación de asistencia de las familias
# ---------------------------------------------------------------------------
def puede_confirmar(evento):
    """Se confirma (o se cambia la respuesta) hasta que el evento empieza, si no está cancelado."""
    return evento.pide_confirmacion and evento.para_familias and not evento.cancelado and evento.fecha_inicio >= timezone.localdate()


def confirmar(evento, tutor, asistira, personas=1):
    personas = max(1, min(int(personas or 1), ConfirmacionAsistencia.MAXIMO_DE_PERSONAS)) if asistira else 0
    ConfirmacionAsistencia.objects.update_or_create(evento=evento, tutor=tutor, defaults={'asistira': asistira, 'personas': personas})


def resumen_de_confirmaciones(evento):
    """{'si', 'no', 'personas', 'sin_responder', 'respuestas'} para quien gestiona el evento."""
    from . import recordatorios
    respuestas = list(evento.confirmaciones.select_related('tutor').order_by('-asistira', 'tutor__nombre', 'tutor__apellido_paterno'))
    familias = set(recordatorios.tutores_del_evento(evento, solo_con_notificaciones=False))
    respondieron = {r.tutor_id for r in respuestas}
    return {'si': sum(r.asistira for r in respuestas), 'no': sum(not r.asistira for r in respuestas),
            'personas': sum(r.personas for r in respuestas if r.asistira), 'sin_responder': len(familias - respondieron),
            'respuestas': respuestas}


# ---------------------------------------------------------------------------
# Historial de cambios (la Bitácora de cambios del sistema)
# ---------------------------------------------------------------------------
def registrar(usuario, evento, accion, mensaje):
    from Usuarios.seguridad import ACCION_ALTA, ACCION_BAJA, ACCION_CAMBIO
    from Usuarios.seguridad import registrar as anotar
    anotar(usuario, evento, {'alta': ACCION_ALTA, 'cambio': ACCION_CAMBIO, 'baja': ACCION_BAJA}[accion], mensaje)


# ---------------------------------------------------------------------------
# Próximos eventos (el inicio del sistema y de los portales) y búsqueda
# ---------------------------------------------------------------------------
def _orden(evento):
    return (evento.fecha_inicio, not evento.todo_el_dia, evento.hora_inicio or time.min, evento.titulo, str(evento.pk))


def proximos(persona, dias=14, limite=6):
    """Los próximos eventos de quien mira (de hoy a `dias` después; los que ya empezaron y siguen, también), en orden."""
    hoy = timezone.localdate()
    eventos = sorted(eventos_de(persona, hoy, hoy + timedelta(days=dias)), key=lambda e: (max(e.fecha_inicio, hoy), *_orden(e)[1:]))
    base = persona.url('calendario')

    def url(evento):
        if getattr(evento, 'es_externo', False):
            return evento.url_propia or f'{base}?mes={evento.fecha_inicio:%Y-%m}'
        return f'{base}?evento={evento.pk}'

    return [{'evento': evento, 'fecha': max(evento.fecha_inicio, hoy), 'dia': texto_del_dia(max(evento.fecha_inicio, hoy), hoy),
             'url': url(evento)} for evento in eventos[:limite]]


def para_el_inicio(persona):
    """{'proximos', 'url_agenda'} para el recuadro «Próximos eventos» del inicio (templates/agenda/_proximos.html). Si algo
    falla, el inicio se muestra igual, sin el recuadro. De paso, revisa (en segundo plano) si hay recordatorios por mandar."""
    import logging
    from . import recordatorios
    recordatorios.generar_si_toca()
    try:
        return {'proximos': proximos(persona), 'url_agenda': persona.url('calendario'), 'con_agenda': True}
    except Exception:
        logging.getLogger(__name__).exception('No se pudieron preparar los próximos eventos')
        return {'con_agenda': False}


def texto_del_dia(fecha, hoy):
    if fecha == hoy:
        return 'Hoy'
    if fecha == hoy + timedelta(days=1):
        return 'Mañana'
    if fecha - hoy < timedelta(days=7):
        return date_format(fecha, 'l').capitalize()
    return date_format(fecha, 'D j b').capitalize()


def buscar(persona, texto, filtro='', tipo='', curso=(None, None)):
    """Los eventos que coinciden con cada palabra (título, descripción o lugar) en el año anterior y el siguiente, del
    más cercano a hoy hacia adelante y luego los pasados."""
    hoy = timezone.localdate()
    desde, hasta = hoy - timedelta(days=365), hoy + timedelta(days=365)
    from CISAHUAYO.sin_acentos import quitar_acentos
    claves = [quitar_acentos(p).lower() for p in (texto or '').split() if p]
    eventos = [e for e in eventos_de(persona, desde, hasta, filtro, tipo, curso)
               if all(c in quitar_acentos(f'{e.titulo} {e.descripcion} {e.lugar}').lower() for c in claves)]
    futuros = sorted([e for e in eventos if e.fecha_fin >= hoy], key=_orden)
    pasados = sorted([e for e in eventos if e.fecha_fin < hoy], key=_orden, reverse=True)
    return futuros, pasados


def por_dia(eventos, desde, hasta):
    """[(fecha, [eventos])] de los días entre esas fechas que tienen algo (un evento de varios días, en cada uno)."""
    dias = {}
    for evento in sorted(eventos, key=_orden):
        fecha = max(evento.fecha_inicio, desde)
        while fecha <= min(evento.fecha_fin, hasta):
            dias.setdefault(fecha, []).append(evento)
            fecha += timedelta(days=1)
    return sorted(dias.items())


# ---------------------------------------------------------------------------
# Archivos de calendario
# ---------------------------------------------------------------------------
def _ics(evento, url, privado=False):
    from CISAHUAYO.ics import EventoIcs
    externo = getattr(evento, 'es_externo', False)
    titulo = evento.titulo
    if privado and externo and evento.fuente == 'reunion':
        titulo = evento.nombre_alcance      # en un calendario de fuera, sin el nombre de la familia («Reunión con familia · R-12»)
    return EventoIcs(
        uid=f'{evento.fuente if externo else "agenda"}-{evento.pk}@cisahuayo', titulo=titulo, fecha_inicio=evento.fecha_inicio,
        fecha_fin=evento.fecha_fin, hora_inicio=evento.hora_inicio if evento.con_horario else None,
        hora_fin=evento.hora_fin if evento.con_horario else None, descripcion=evento.descripcion, lugar=evento.lugar, url=url,
        cancelado=evento.cancelado,
    )


def ics_de_evento(evento, url=''):
    from CISAHUAYO.ics import calendario
    return calendario([_ics(evento, url)])


def ics_de_suscripcion(persona, absoluta):
    """El calendario completo de esa persona: de un mes atrás a un año adelante. `absoluta(ruta)`: la dirección completa."""
    from CISAHUAYO.ics import calendario
    hoy = timezone.localdate()
    eventos = sorted(eventos_de(persona, hoy - timedelta(days=31), hoy + timedelta(days=365)), key=_orden)
    archivos = []
    for evento in eventos:
        if getattr(evento, 'es_externo', False):
            url = absoluta(evento.url_propia) if evento.url_propia else ''
        else:
            url = absoluta(f'{reverse(f"{persona.espacio}:calendario")}?evento={evento.pk}')
        archivos.append(_ics(evento, url, privado=True))
    return calendario(archivos, nombre='CISAHUAYO · Agenda', refrescar_horas=6)
