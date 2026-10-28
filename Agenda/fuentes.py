"""Quién mira la agenda y lo que aparece en ella además de los eventos del colegio (pedido del 2026-10-27).

`Persona`: una cuenta del sistema, un tutor o un estudiante, tanto en la página como en la suscripción del teléfono y en
los recordatorios (de ahí salen su vista por niveles, Agenda/alcance.py, y las direcciones de su espacio).

Lo de otros módulos (solo para leer: se cambia en su propio módulo), cada cosa con su color:
- Días sin clases (Asistencia): los de todo el colegio y los de los niveles de quien mira; los días seguidos con el
  mismo motivo (también separados por un fin de semana) son una sola barra.
- Comunicados con evento: los que recibe y, en el sistema, los que envió.
- Reuniones con familias programadas o confirmadas: las del tutor y las del personal que participa o es responsable.
- Fechas de captura de calificaciones (periodos por fechas): para quien captura o cierra calificaciones, de sus niveles.
- Inicio y fin del ciclo escolar: para todos.
Si una fuente falla (p. ej. sin la migración de su módulo), la agenda sigue con las demás.
"""
import logging
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from functools import cached_property

from django.urls import reverse
from django.utils.formats import date_format

from Alumnos.models import ORDEN_NIVELES

from .models import ICONO_DE_TIPO, NOMBRE_DE_ALCANCE, NOMBRE_DE_TIPO, EXAMENES, JUNTA, VACACIONES

registro = logging.getLogger(__name__)

# (fondo, texto) de lo que viene de otros módulos (el texto, con al menos 4.5:1 de contraste)
SIN_CLASES = ('#6B7280', '#FFFFFF')     # gris (4.83)
COMUNICADO = ('#2F737C', '#FFFFFF')     # turquesa del sistema (5.5)
REUNION = ('#7C3AED', '#FFFFFF')        # violeta (5.7)
PERIODO = ('#B45309', '#FFFFFF')        # ámbar oscuro (5.0)
CICLO = ('#0F766E', '#FFFFFF')          # verde azulado (5.5)
LEYENDA = {'sin_clases': ('Días sin clases', *SIN_CLASES), 'comunicado': ('Comunicados', *COMUNICADO),
           'reunion': ('Reuniones con familias', *REUNION), 'periodo': ('Captura de calificaciones', *PERIODO),
           'ciclo': ('Ciclo escolar', *CICLO)}


# ---------------------------------------------------------------------------
# Quién mira
# ---------------------------------------------------------------------------
@dataclass
class Persona:
    usuario: object = None
    tutor: object = None
    alumno: object = None

    @classmethod
    def de_request(cls, request):
        usuario = getattr(request, 'user', None)
        if usuario is not None and usuario.is_authenticated:
            return cls(usuario=usuario)
        from CISAHUAYO import portales
        cuenta = getattr(request, 'cuenta_portal', None)
        if cuenta is None:
            return None
        return cls(tutor=cuenta) if request.cuenta_portal_tipo == portales.TUTOR else cls(alumno=cuenta)

    @property
    def espacio(self):
        """El espacio de rutas de su agenda («agenda», «portal_tutores:agenda» o «portal_estudiantes:agenda»)."""
        if self.usuario is not None:
            return 'agenda'
        return 'portal_tutores:agenda' if self.tutor is not None else 'portal_estudiantes:agenda'

    @property
    def espacio_del_portal(self):
        return '' if self.usuario is not None else ('portal_tutores' if self.tutor is not None else 'portal_estudiantes')

    def url(self, nombre, *args):
        return reverse(f'{self.espacio}:{nombre}', args=args)

    @cached_property
    def vista(self):
        from . import alcance
        if self.usuario is not None:
            return alcance.de_usuario(self.usuario)
        return alcance.de_tutor(self.tutor) if self.tutor is not None else alcance.de_estudiante(self.alumno)

    @property
    def filtro_de_persona(self):
        """Para buscar sus avisos y su suscripción: {'usuario': …} / {'tutor': …} / {'alumno': …}."""
        if self.usuario is not None:
            return {'usuario': self.usuario}
        return {'tutor': self.tutor} if self.tutor is not None else {'alumno': self.alumno}


# ---------------------------------------------------------------------------
# Un evento de otro módulo, con lo mismo que el calendario usa de un EventoAgenda
# ---------------------------------------------------------------------------
@dataclass
class EventoExterno:
    clave: str                  # su identificador en la página («s2026-11-02-1», «c12», «r5», «p3», «ci4i»)
    fuente: str                 # sin_clases, comunicado, reunion, periodo, ciclo
    titulo: str
    fecha_inicio: date
    fecha_fin: date
    colores: tuple
    nombre_alcance: str
    hora_inicio: time = None
    hora_fin: time = None
    lugar: str = ''
    descripcion: str = ''
    url_propia: str = ''        # su página (el comunicado, la reunión); sin ella se abre la ventana de la agenda
    tipo: str = ''
    niveles: tuple = field(default_factory=tuple)

    es_externo = True
    importante = False
    serie = None

    @property
    def pk(self):
        return self.clave

    @property
    def color(self):
        return self.colores[0]

    @property
    def color_texto(self):
        return self.colores[1]

    @property
    def todo_el_dia(self):
        return self.hora_inicio is None

    @property
    def varios_dias(self):
        return self.fecha_fin > self.fecha_inicio

    @property
    def icono(self):
        return {'comunicado': 'megaphone', 'ciclo': 'school'}.get(self.fuente) or ICONO_DE_TIPO.get(self.tipo, 'calendar')

    @property
    def nombre_tipo(self):
        return NOMBRE_DE_TIPO.get(self.tipo, 'Otro')

    @property
    def texto_de_fechas(self):
        if not self.varios_dias:
            return date_format(self.fecha_inicio, 'l j \\d\\e F \\d\\e Y').capitalize()
        mismo_anio = self.fecha_inicio.year == self.fecha_fin.year
        inicio = date_format(self.fecha_inicio, 'j \\d\\e F' if mismo_anio else 'j \\d\\e F \\d\\e Y')
        return f'Del {inicio.lower()} al {date_format(self.fecha_fin, "j \\d\\e F \\d\\e Y").lower()}'

    @property
    def texto_de_horario(self):
        if self.hora_inicio is None:
            return 'Todo el día'
        return f'{self.hora_inicio:%H:%M} a {self.hora_fin:%H:%M}' if self.hora_fin else f'Desde las {self.hora_inicio:%H:%M}'

    @property
    def hora_corta(self):
        return '' if self.hora_inicio is None else f'{self.hora_inicio:%H:%M}'


# ---------------------------------------------------------------------------
# Las fuentes
# ---------------------------------------------------------------------------
def _niveles_del_colegio():
    from Alumnos.models import Grado
    return Grado.objects.disponibles().niveles() or set(ORDEN_NIVELES)


def _seguidos(anterior, siguiente):
    """Si dos fechas van seguidas (o solo las separa un fin de semana)."""
    dias = (siguiente - anterior).days
    return dias == 1 or (dias <= 3 and all((anterior + timedelta(days=i)).weekday() >= 5 for i in range(1, dias)))


def dias_sin_clases(persona, desde, hasta, filtro=''):
    """Los días sin clases de todo el colegio y los de los niveles de quien mira (con el filtro de nivel de la agenda)."""
    from Alumnos.models import DiaNoLectivo
    from .alcance import SOLO_COLEGIO
    vista = persona.vista
    del_colegio = _niveles_del_colegio()
    por_fecha = {}
    for fecha, nivel, motivo in DiaNoLectivo.objects.filter(fecha__range=(desde, hasta)).values_list('fecha', 'nivel', 'motivo').order_by('fecha'):
        por_fecha.setdefault(fecha, {})[nivel] = motivo
    piezas = []   # (fecha, niveles mostrados, motivo, de todo el colegio)
    for fecha, niveles in sorted(por_fecha.items()):
        if del_colegio <= set(niveles):
            motivo = ', '.join(dict.fromkeys(niveles[n] for n in ORDEN_NIVELES if n in niveles))
            piezas.append((fecha, (), motivo, True))
            continue
        if filtro == SOLO_COLEGIO:
            continue
        suyos = [n for n in ORDEN_NIVELES if n in niveles and (vista.todos or n in vista.niveles) and (not filtro or filtro == n)]
        for motivo in dict.fromkeys(niveles[n] for n in suyos):
            piezas.append((fecha, tuple(n for n in suyos if niveles[n] == motivo), motivo, False))
    # Los días seguidos con el mismo motivo y los mismos niveles, en una sola barra
    tramos = []
    for fecha, niveles, motivo, colegio in piezas:
        previo = next((t for t in reversed(tramos) if t['niveles'] == niveles and t['motivo'] == motivo), None)
        if previo and _seguidos(previo['fin'], fecha):
            previo['fin'] = fecha
        else:
            tramos.append({'inicio': fecha, 'fin': fecha, 'niveles': niveles, 'motivo': motivo, 'colegio': colegio})
    eventos = []
    for tramo in tramos:
        alcance = 'Todos los niveles' if tramo['colegio'] else ' y '.join(NOMBRE_DE_ALCANCE[n] for n in tramo['niveles'])
        eventos.append(EventoExterno(
            clave=f's{tramo["inicio"]:%Y%m%d}-{"-".join(tramo["niveles"]) or "colegio"}', fuente='sin_clases',
            titulo=f'Sin clases: {tramo["motivo"]}', fecha_inicio=tramo['inicio'], fecha_fin=tramo['fin'], colores=SIN_CLASES,
            nombre_alcance=f'Día sin clases · {alcance}', tipo=VACACIONES, niveles=tramo['niveles'],
            descripcion='Registrado en Asistencia: ese día no se toma asistencia.' + ('' if tramo['colegio'] else f' Solo en {alcance}.'),
        ))
    return eventos


def comunicados(persona, desde, hasta):
    """Los comunicados con evento: los que recibe y, en el sistema, los que envió (con enlace a su seguimiento)."""
    from Comunicados import reglas
    from Comunicados.alcance import SEGUIMIENTO
    if persona.usuario is not None:
        lector = reglas.lector_de_usuario(persona.usuario)
        autor = persona.usuario if persona.usuario.has_perm(SEGUIMIENTO) else None
        espacio = 'comunicados'
    else:
        from CISAHUAYO import portales
        tipo = portales.TUTOR if persona.tutor is not None else portales.ESTUDIANTE
        lector, autor = reglas.lector_de_portal(tipo, persona.tutor or persona.alumno), None
        espacio = f'{persona.espacio_del_portal}:comunicados'
    eventos = []
    for comunicado, recibido in reglas.eventos_para_la_agenda(lector, autor, desde, hasta):
        url = reverse(f'{espacio}:recibido', args=[comunicado.pk]) if recibido else reverse('comunicados:detalle', args=[comunicado.pk])
        texto = ' '.join(comunicado.descripcion.split())
        eventos.append(EventoExterno(
            clave=f'c{comunicado.pk}', fuente='comunicado', titulo=comunicado.titulo, fecha_inicio=comunicado.evento_fecha,
            fecha_fin=comunicado.evento_fecha, colores=COMUNICADO, nombre_alcance='Comunicado', hora_inicio=comunicado.evento_hora_inicio,
            hora_fin=comunicado.evento_hora_fin, lugar=comunicado.evento_lugar, url_propia=url,
            descripcion=texto if len(texto) <= 400 else texto[:399].rstrip() + '…',
        ))
    return eventos


def reuniones(persona, desde, hasta):
    """Las reuniones con familias programadas o confirmadas del tutor, o del personal que participa o es responsable.
    Como sus avisos, solo dicen cuándo y dónde (nunca el motivo)."""
    if persona.alumno is not None:
        return []
    from django.db.models import Q

    from Reuniones.models import Reunion
    consulta = Reunion.objects.filter(estado__in=Reunion.ACTIVAS, fecha__range=(desde, hasta)).select_related('sala', 'tutor')
    if persona.tutor is not None:
        consulta = consulta.filter(Q(tutor=persona.tutor) | Q(tutores__tutor=persona.tutor))
        detalle = 'portal_tutores:reuniones:detalle'
    else:
        consulta = consulta.filter(Q(responsable=persona.usuario) | Q(participantes__usuario=persona.usuario, participantes__activo=True))
        detalle = 'reuniones:detalle'
    eventos = []
    for reunion in consulta.distinct():
        titulo = (f'Reunión en el colegio · {reunion.get_area_display()}' if persona.tutor is not None
                  else f'Reunión con familia · {reunion.tutor}')
        eventos.append(EventoExterno(
            clave=f'r{reunion.pk}', fuente='reunion', titulo=titulo, fecha_inicio=reunion.fecha, fecha_fin=reunion.fecha,
            colores=REUNION, nombre_alcance=f'Reunión con familia · {reunion.folio}', hora_inicio=reunion.hora_inicio,
            hora_fin=reunion.hora_fin, lugar=reunion.sala.nombre if reunion.sala_id else '', tipo=JUNTA,
            url_propia=reverse(detalle, args=[reunion.pk]),
        ))
    return eventos


def periodos(persona, desde, hasta, filtro=''):
    """Las fechas de captura de calificaciones (periodos por fechas) de sus niveles, para quien captura o cierra."""
    from Alumnos.models import Periodo
    from .alcance import SOLO_COLEGIO
    usuario = persona.usuario
    if usuario is None or filtro == SOLO_COLEGIO:
        return []
    vista = persona.vista
    if not (vista.gestiona or usuario.has_perm('Calificaciones.capturar') or usuario.has_perm('Calificaciones.cerrar')):
        return []
    consulta = Periodo.objects.filter(apertura=Periodo.POR_FECHAS, fecha_inicio__lte=hasta, fecha_fin__gte=desde)
    if not vista.todos:
        consulta = consulta.filter(nivel__in=sorted(vista.niveles))
    if filtro:
        consulta = consulta.filter(nivel=filtro)
    eventos = []
    for periodo in consulta.order_by('fecha_inicio', 'nivel'):
        nivel = NOMBRE_DE_ALCANCE.get(periodo.nivel, periodo.nivel)
        eventos.append(EventoExterno(
            clave=f'p{periodo.pk}', fuente='periodo', titulo=f'Captura de calificaciones: {periodo.nombre} ({nivel})',
            fecha_inicio=periodo.fecha_inicio, fecha_fin=periodo.fecha_fin, colores=PERIODO, nombre_alcance=f'Calificaciones · {nivel}',
            tipo=EXAMENES, niveles=(periodo.nivel,),
            descripcion=f'La captura se abre el {date_format(periodo.fecha_inicio, "j \\d\\e F").lower()} y se cierra el '
                        f'{date_format(periodo.fecha_fin, "j \\d\\e F").lower()}.',
        ))
    return eventos


def ciclos(persona, desde, hasta):
    """El inicio y el fin de cada ciclo escolar que cae entre esas fechas."""
    from django.db.models import Q

    from Alumnos.models import CicloEscolar
    eventos = []
    for ciclo in CicloEscolar.objects.filter(Q(fecha_inicio__range=(desde, hasta)) | Q(fecha_fin__range=(desde, hasta))):
        for clave, fecha, texto in ((f'ci{ciclo.pk}i', ciclo.fecha_inicio, 'Inicio'), (f'ci{ciclo.pk}f', ciclo.fecha_fin, 'Fin')):
            if desde <= fecha <= hasta:
                eventos.append(EventoExterno(
                    clave=clave, fuente='ciclo', titulo=f'{texto} del ciclo escolar {ciclo.nombre}', fecha_inicio=fecha, fecha_fin=fecha,
                    colores=CICLO, nombre_alcance='Ciclo escolar',
                ))
    return eventos


def _seguro(funcion, *argumentos):
    try:
        return funcion(*argumentos)
    except Exception:
        registro.exception('No se pudo agregar a la agenda: %s', funcion.__name__)
        return []


def externos(persona, desde, hasta, filtro=''):
    """Todo lo de otros módulos que ve esa persona entre esas fechas. Con filtro de nivel, solo lo que tiene nivel (los
    días sin clases y las fechas de calificaciones)."""
    eventos = _seguro(dias_sin_clases, persona, desde, hasta, filtro) + _seguro(periodos, persona, desde, hasta, filtro)
    if not filtro:
        eventos += _seguro(comunicados, persona, desde, hasta) + _seguro(reuniones, persona, desde, hasta) + _seguro(ciclos, persona, desde, hasta)
    return eventos
