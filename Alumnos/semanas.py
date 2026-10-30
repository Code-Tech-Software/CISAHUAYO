"""Semanas A y B (pedido del 2026-10-26): qué horario corresponde a cada fecha. Es el único lugar con esta regla: la
asistencia, las bitácoras, los portales, las reuniones y los empalmes de los profesores la toman de aquí.

- Cada nivel tiene su configuración por ciclo (`ConfiguracionHorario`); sin ella, o en modalidad fija, el horario es
  el mismo todas las semanas. Solo preescolar y primaria pueden alternar.
- Las semanas van de lunes a domingo. La semana de la fecha de referencia es la que se indicó (A o B) y desde ahí se
  alternan, hacia adelante y hacia atrás, contando semanas de calendario: no se usa el número de semana del año, así
  que el cambio de mes o de año no altera nada.
- Las vacaciones y las semanas sin clases siguen la alternancia; los días festivos y las suspensiones son días sin
  clases (Alumnos/asistencias.py) y tampoco la mueven.
- Excepciones (`ExcepcionSemana`): «solo esta semana» cambia esa semana y nada más; «reiniciar» hace que esa semana
  sea la indicada y que las siguientes se alternen desde ella.
- Versiones: cada bloque tiene vigencia (`vigente_desde`, `vigente_hasta`); el horario de una fecha usa las versiones
  que estaban en vigor ese día.
"""
from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import Q
from django.utils import timezone
from django.utils.formats import date_format

from .models import ORDEN_NIVELES, ConfiguracionHorario, ExcepcionSemana, HorarioMateria

A, B = HorarioMateria.SEMANA_A, HorarioMateria.SEMANA_B
TODAS = HorarioMateria.TODAS
DIA_MES = 'j \\d\\e F'
DIA_MES_ANIO = 'j \\d\\e F \\d\\e Y'


def lunes_de(fecha):
    return fecha - timedelta(days=fecha.weekday())


def otra(semana):
    return B if semana == A else A


def calcular(lunes, referencia, semana_referencia, excepciones=()):
    """La semana (A o B) de la semana que empieza en `lunes`.

    `referencia`: el lunes de la semana de referencia. `excepciones`: [(lunes, semana, tipo)]. Manda el reinicio más
    reciente que no sea posterior a esa semana (o la referencia, si es más reciente); si la semana es anterior a todos,
    se cuenta hacia atrás desde el primero. Una excepción de «solo esta semana» la cambia sin mover las demás.
    """
    for lunes_excepcion, semana, tipo in excepciones:
        if tipo == ExcepcionSemana.SOLO_ESTA and lunes_excepcion == lunes:
            return semana
    anclas = sorted([(referencia, semana_referencia)] + [(l, s) for l, s, t in excepciones if t == ExcepcionSemana.REINICIO])
    previas = [ancla for ancla in anclas if ancla[0] <= lunes]
    inicio, semana = previas[-1] if previas else anclas[0]
    saltos = (lunes - inicio).days // 7
    return semana if saltos % 2 == 0 else otra(semana)


@dataclass(frozen=True)
class Semana:
    """Una semana de calendario de un nivel: su letra ('' si el horario es fijo) y sus fechas."""
    tipo: str
    lunes: date

    @property
    def domingo(self):
        return self.lunes + timedelta(days=6)

    @property
    def alternada(self):
        return bool(self.tipo)

    @property
    def nombre(self):
        return f'Semana {self.tipo}' if self.tipo else 'Horario fijo'

    @property
    def rango(self):
        """«19 al 25 de octubre», «29 de septiembre al 5 de octubre» o, entre años, con los dos años."""
        inicio, fin = self.lunes, self.domingo
        if inicio.year != fin.year:
            texto = f'{date_format(inicio, DIA_MES_ANIO)} al {date_format(fin, DIA_MES_ANIO)}'
        elif inicio.month != fin.month:
            texto = f'{date_format(inicio, DIA_MES)} al {date_format(fin, DIA_MES)}'
        else:
            texto = f'{inicio.day} al {date_format(fin, DIA_MES)}'
        return texto.lower()   # «26 de octubre», como en el resto del sistema

    @property
    def anterior(self):
        return self.lunes - timedelta(days=7)

    @property
    def siguiente(self):
        return self.lunes + timedelta(days=7)

    def dias(self):
        return [self.lunes + timedelta(days=indice) for indice in range(7)]


class Calendario:
    """Las semanas de un ciclo: carga sus configuraciones y excepciones una sola vez (dos consultas) y calcula en
    memoria. `extra` agrega una excepción sin guardarla (la vista previa) y `sin` deja fuera una (al editarla)."""

    def __init__(self, ciclo, extra=None, sin=None):
        self.ciclo = ciclo
        self.configuraciones = {}
        self.excepciones = {}
        if ciclo is None:
            return
        for configuracion in ConfiguracionHorario.objects.filter(ciclo=ciclo):
            self.configuraciones[configuracion.nivel] = configuracion
            self.excepciones[configuracion.nivel] = []
        por_id = {c.pk: c.nivel for c in self.configuraciones.values()}
        for excepcion in ExcepcionSemana.objects.filter(configuracion__ciclo=ciclo).order_by('lunes'):
            if sin is not None and excepcion.pk == sin:
                continue
            self.excepciones[por_id[excepcion.configuracion_id]].append((excepcion.lunes, excepcion.semana, excepcion.tipo))
        if extra is not None:
            nivel, lunes, semana, tipo = extra
            lista = [e for e in self.excepciones.setdefault(nivel, []) if e[0] != lunes]
            self.excepciones[nivel] = sorted(lista + [(lunes, semana, tipo)])

    def configuracion(self, nivel):
        return self.configuraciones.get(nivel)

    def alternado(self, nivel):
        configuracion = self.configuraciones.get(nivel)
        return configuracion is not None and configuracion.alternado

    def semana(self, fecha, nivel):
        """'A' o 'B' en los niveles con horario alternado; '' en los de horario fijo."""
        if not self.alternado(nivel):
            return TODAS
        configuracion = self.configuraciones[nivel]
        return calcular(lunes_de(fecha), lunes_de(configuracion.fecha_referencia), configuracion.semana_referencia,
                        self.excepciones.get(nivel, ()))

    def info(self, fecha, nivel):
        return Semana(self.semana(fecha, nivel), lunes_de(fecha))

    def siguientes(self, desde, nivel, cuantas=10):
        """Las `cuantas` semanas a partir de la de `desde` (para la vista previa de una excepción)."""
        inicio = lunes_de(desde)
        return [self.info(inicio + timedelta(weeks=indice), nivel) for indice in range(cuantas)]

    def aplica(self, bloque, fecha, nivel):
        """Si el bloque corresponde a esa fecha: su día, su vigencia y su semana (los de todas las semanas, siempre)."""
        if bloque.dia_semana != fecha.weekday() or not bloque.vigente_en(fecha):
            return False
        return not bloque.semana or bloque.semana == self.semana(fecha, nivel)

    def q_semana(self, fecha, prefijo=''):
        """Filtro de bloques (o de lo que se indique con `prefijo`, p. ej. 'horarios__') de la semana de esa fecha en
        cada nivel: en los alternados, los de esa semana; en los fijos, solo los de todas las semanas."""
        condicion = Q()
        for nivel in ORDEN_NIVELES:
            semana = self.semana(fecha, nivel)
            condicion |= Q(**{f'{prefijo}materia_grado__grado__nivel': nivel, f'{prefijo}semana__in': [TODAS, semana] if semana else [TODAS]})
        return condicion

    def q_fecha(self, fecha, prefijo=''):
        """Los bloques de esa fecha: su día de la semana, su vigencia y su semana."""
        return Q(**{f'{prefijo}dia_semana': fecha.weekday()}) & q_vigente(fecha, prefijo) & self.q_semana(fecha, prefijo)


def q_vigente(fecha, prefijo=''):
    """Las versiones en vigor en esa fecha."""
    return (
        (Q(**{f'{prefijo}vigente_desde__isnull': True}) | Q(**{f'{prefijo}vigente_desde__lte': fecha}))
        & (Q(**{f'{prefijo}vigente_hasta__isnull': True}) | Q(**{f'{prefijo}vigente_hasta__gte': fecha}))
        & (Q(**{f'{prefijo}fin_programado__isnull': True}) | Q(**{f'{prefijo}fin_programado__gte': fecha}))
    )


def _ciclo_de(fecha):
    from .asistencias import ciclo_de_fecha
    return ciclo_de_fecha(fecha)


def semana_de(fecha, nivel, ciclo=None):
    """La semana (A, B o '' si es fija) de esa fecha para un nivel."""
    ciclo = ciclo or _ciclo_de(fecha)
    return Calendario(ciclo).semana(fecha, nivel) if ciclo else TODAS


def bloques_de_fecha(fecha, ciclo=None, calendario=None, **filtros):
    """Los bloques de las materias vigentes que se imparten en esa fecha (según su semana A/B y su versión)."""
    ciclo = ciclo or (calendario.ciclo if calendario else _ciclo_de(fecha))
    if ciclo is None:
        return HorarioMateria.historial.none()
    calendario = calendario or Calendario(ciclo)
    return HorarioMateria.historial.filter(
        calendario.q_fecha(fecha), materia_grado__ciclo=ciclo, materia_grado__activa=True, **filtros,
    )


def bloques_de_semana(fecha, ciclo, calendario=None, **filtros):
    """Los bloques de los siete días de la semana de esa fecha, cada uno con la versión y la semana de su día."""
    if ciclo is None:
        return HorarioMateria.historial.none()
    calendario = calendario or Calendario(ciclo)
    condicion = Q(pk__in=[])
    for dia in Semana(TODAS, lunes_de(fecha)).dias():
        condicion |= calendario.q_fecha(dia)
    return HorarioMateria.historial.filter(condicion, materia_grado__ciclo=ciclo, materia_grado__activa=True, **filtros)


def fechas_con_clase(asignacion, fechas, calendario=None):
    """De esas fechas, en las que la materia tiene clase según su horario (una consulta)."""
    fechas = list(fechas)
    if not fechas:
        return set()
    calendario = calendario or Calendario(asignacion.ciclo)
    bloques = list(HorarioMateria.historial.filter(materia_grado=asignacion))
    nivel = asignacion.grado.nivel
    return {fecha for fecha in fechas if any(calendario.aplica(bloque, fecha, nivel) for bloque in bloques)}


def coinciden(nivel_1, semana_1, nivel_2, semana_2, ciclo, desde=None, calendario=None):
    """Si dos bloques del mismo día y hora pueden caer en la misma fecha: siempre, si alguno es de todas las semanas;
    si los dos son de semanas A/B, cuando en alguna semana del ciclo (desde `desde`) a los dos niveles les toca la suya
    (los niveles alternan cada uno con su propia referencia)."""
    if not semana_1 or not semana_2:
        return True
    if ciclo is None:
        return semana_1 == semana_2
    calendario = calendario or Calendario(ciclo)
    lunes = lunes_de(max(desde or ciclo.fecha_inicio, ciclo.fecha_inicio))
    while lunes <= ciclo.fecha_fin:
        if calendario.semana(lunes, nivel_1) == semana_1 and calendario.semana(lunes, nivel_2) == semana_2:
            return True
        lunes += timedelta(weeks=1)
    return False


def semanas_compatibles(semana_1, semana_2):
    """En un mismo grupo (un solo nivel y una sola secuencia): chocan si son de la misma semana o alguna es de todas."""
    return not semana_1 or not semana_2 or semana_1 == semana_2


def hoy():
    return timezone.localdate()


def mapa_de_semanas(calendario, nivel):
    """{lunes en AAAA-MM-DD: 'A' o 'B'} de todas las semanas del ciclo de un nivel alternado ({} si es fijo): para que
    una pantalla elija los bloques de una fecha sin preguntar al servidor."""
    ciclo = calendario.ciclo
    if ciclo is None or not calendario.alternado(nivel):
        return {}
    mapa, lunes = {}, lunes_de(ciclo.fecha_inicio)
    while lunes <= ciclo.fecha_fin:
        mapa[lunes.isoformat()] = calendario.semana(lunes, nivel)
        lunes += timedelta(weeks=1)
    return mapa


def explicar(bloque, fecha, calendario, nivel):
    """Por qué un bloque no corresponde a una fecha (texto), o '' si sí corresponde."""
    from .horarios import DIAS
    if bloque.dia_semana != fecha.weekday():
        return f'Ese bloque es del {DIAS[bloque.dia_semana].lower()} y la clase fue en {DIAS[fecha.weekday()].lower()}.'
    if not bloque.vigente_en(fecha):
        return 'Ese bloque no estaba en vigor en esa fecha (el horario cambió).'
    semana = calendario.semana(fecha, nivel)
    if bloque.semana and bloque.semana != semana:
        return f'Ese bloque es de la semana {bloque.semana} y esa fecha cae en {"la semana " + semana if semana else "horario fijo"}.'
    return ''


def fecha_de(texto):
    """Una fecha AAAA-MM-DD de la dirección o de un formulario; None si no es válida."""
    try:
        return date.fromisoformat((texto or '').strip())
    except ValueError:
        return None
