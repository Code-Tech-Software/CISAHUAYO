"""«Estudiantes que requieren atención»: alertas preventivas de seguimiento por inasistencia y por rendimiento.

Se calculan cada vez con los registros reales (no se guardan: cambian en cuanto cambia lo que las origina) y con los
criterios de cada nivel (Panel/models.py · CriterioSeguimiento). No afirman que alguien abandonará sus estudios, no
generan sanciones ni cambian calificaciones.

Inasistencia — la de entrada al colegio (la fuente institucional), en el periodo de evaluación actual del nivel hasta hoy:
- Solo días con registro: los días sin captura no son faltas. Sin días sin clases del nivel ni días de suspensión
  autorizada (Alumnos/asistencias.py).
- Faltas acumuladas y seguidas: solo las sin justificar. Seguidas = en días de clases consecutivos.
- Porcentaje de inasistencia: faltas (justificadas o no) entre días con registro, si hay suficientes días.

Rendimiento — las finales de las actas cerradas del periodo evaluado (Panel/academico.py):
- Materias reprobadas: final menor que la calificación aprobatoria del nivel.
- Promedio bajo: el de sus materias, menor que el mínimo del nivel.
- Descenso: su promedio en las mismas materias bajó respecto del periodo anterior del mismo nivel.

Prioridad (reglas a la vista en la página):
- Alta: inasistencia y bajo rendimiento a la vez, faltas seguidas, o tantas materias reprobadas como el umbral de
  prioridad alta del nivel.
- Media: cualquier otra alerta de inasistencia o de rendimiento.
- Baja: solo un descenso de rendimiento.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Count, Q

from Alumnos.asistencias import con_justificada_general, dias_de_clases, fechas_sin_clases, sin_dias_suspendidos
from Alumnos.models import AsistenciaGeneral, Inscripcion

from . import academico
from .models import CriterioSeguimiento

INASISTENCIA, RENDIMIENTO = 'inasistencia', 'rendimiento'
ALTA, MEDIA, BAJA = 'alta', 'media', 'baja'
PRIORIDADES = ((ALTA, 'Alta'), (MEDIA, 'Media'), (BAJA, 'Baja'))
MOTIVOS = ((INASISTENCIA, 'Inasistencia'), (RENDIMIENTO, 'Bajo rendimiento'), ('ambos', 'Ambos motivos'))
_RANGO = {ALTA: 0, MEDIA: 1, BAJA: 2}


@dataclass
class Alerta:
    inscripcion: object
    motivos: list = field(default_factory=list)      # [(tipo, texto)]
    tipos: set = field(default_factory=set)
    prioridad: str = MEDIA
    periodo_asistencia: str = ''
    periodo_calificaciones: str = ''
    registros: int = 0
    faltas: int = 0
    faltas_sin_justificar: int = 0
    seguidas: int = 0
    inasistencia: Decimal = None
    promedio: Decimal = None
    reprobadas: int = 0
    solo_descenso: bool = False

    @property
    def alumno(self):
        return self.inscripcion.alumno

    @property
    def ambos(self):
        return INASISTENCIA in self.tipos and RENDIMIENTO in self.tipos

    @property
    def gravedad(self):
        """Para ordenar: prioridad, cantidad de motivos y luego la magnitud."""
        return (_RANGO[self.prioridad], -len(self.motivos), -self.reprobadas, -self.faltas_sin_justificar, self.promedio or Decimal('99'))

    @property
    def texto_de_prioridad(self):
        return dict(PRIORIDADES)[self.prioridad]


def _seguidas(fechas, indice):
    """La racha más larga de días de clases consecutivos (por su posición en el calendario escolar) entre las fechas."""
    posiciones = sorted(indice[f] for f in fechas if f in indice)
    mejor = actual = 0
    anterior = None
    for p in posiciones:
        actual = actual + 1 if anterior is not None and p == anterior + 1 else 1
        mejor = max(mejor, actual)
        anterior = p
    return mejor


def _rango_de_asistencia(filtros, ev):
    if ev.base is not None:
        desde, hasta, nombre = ev.base.fecha_inicio, ev.base.fecha_fin, ev.base.nombre
    else:
        desde, hasta, nombre = filtros.ciclo.fecha_inicio, filtros.ciclo.fecha_fin, f'el ciclo {filtros.ciclo}'
    return max(desde, filtros.ciclo.fecha_inicio), min(hasta, filtros.hoy, filtros.ciclo.fecha_fin), nombre


def _asistencia(filtros, nivel, ids, criterio, ev, alertas):
    desde, hasta, nombre = _rango_de_asistencia(filtros, ev)
    if desde > hasta or not ids:
        return
    registros = sin_dias_suspendidos(con_justificada_general(
        AsistenciaGeneral.objects.filter(inscripcion__in=ids, fecha__range=(desde, hasta))))
    sin_clases = fechas_sin_clases(desde, hasta, nivel)
    if sin_clases:
        registros = registros.exclude(fecha__in=sin_clases)
    totales = registros.order_by().values('inscripcion_id').annotate(
        registros=Count('pk'), faltas=Count('pk', filter=Q(estado='FALTA')),
        sin_justificar=Count('pk', filter=Q(estado='FALTA', justificada=False)),
    )
    faltas_por = defaultdict(list)
    for inscripcion, fecha in registros.filter(estado='FALTA', justificada=False).values_list('inscripcion_id', 'fecha'):
        faltas_por[inscripcion].append(fecha)
    indice = {f: i for i, f in enumerate(dias_de_clases(desde, hasta, filtros.ciclo, nivel))}
    for fila in totales:
        motivos = []
        seguidas = _seguidas(faltas_por.get(fila['inscripcion_id'], []), indice)
        if fila['sin_justificar'] >= criterio.faltas_acumuladas:
            motivos.append(f'Acumula {fila["sin_justificar"]} faltas sin justificar')
        if seguidas >= criterio.faltas_consecutivas:
            motivos.append(f'{seguidas} faltas seguidas sin justificar')
        porcentaje = None
        if fila['registros']:
            porcentaje = (Decimal(fila['faltas']) * 100 / fila['registros']).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
        if porcentaje is not None and fila['registros'] >= criterio.dias_minimos and porcentaje > criterio.inasistencia_maxima:
            motivos.append(f'Inasistencia de {porcentaje} % ({fila["faltas"]} de {fila["registros"]} días con registro)')
        if not motivos:
            continue
        alerta = alertas[fila['inscripcion_id']]
        alerta.motivos += [(INASISTENCIA, m) for m in motivos]
        alerta.tipos.add(INASISTENCIA)
        alerta.periodo_asistencia = nombre
        alerta.registros, alerta.faltas, alerta.faltas_sin_justificar = fila['registros'], fila['faltas'], fila['sin_justificar']
        alerta.seguidas, alerta.inasistencia = seguidas, porcentaje


def _rendimiento(filtros, nivel, vigentes, criterio, ev, alertas):
    if ev.evaluado is None:
        return
    actuales = academico.por_inscripcion(academico.resultados(filtros, ev.evaluado, nivel, vigentes)[0])
    previos = academico.por_inscripcion(academico.resultados(filtros, ev.anterior, nivel, vigentes)[0]) if ev.anterior else {}
    materias = {}
    for inscripcion, finales in actuales.items():
        motivos, solo_descenso = [], False
        reprobadas = [a for a, final in finales.items() if final < criterio.calificacion_aprobatoria]
        promedio = academico.promedio(finales.values())
        if len(reprobadas) >= criterio.materias_reprobadas:
            if not materias:
                materias = dict(academico.asignaciones(filtros, nivel).values_list('pk', 'materia__nombre'))
            nombres = ', '.join(sorted(materias.get(a, '') for a in reprobadas))
            motivos.append(f'Reprueba {len(reprobadas)} materia{"s" if len(reprobadas) != 1 else ""}: {nombres}')
        if promedio is not None and promedio < criterio.promedio_minimo:
            motivos.append(f'Promedio de {promedio} (mínimo del nivel: {criterio.promedio_minimo})')
        comunes = [a for a in finales if a in previos.get(inscripcion, {})]
        if comunes:
            antes = academico.promedio(previos[inscripcion][a] for a in comunes)
            ahora = academico.promedio(finales[a] for a in comunes)
            if antes - ahora >= criterio.descenso_minimo:
                motivos.append(f'Su promedio bajó de {antes} a {ahora} desde {ev.anterior.nombre} (en las mismas {len(comunes)} materias)')
                solo_descenso = len(motivos) == 1
        if not motivos:
            continue
        alerta = alertas[inscripcion]
        alerta.motivos += [(RENDIMIENTO, m) for m in motivos]
        alerta.tipos.add(RENDIMIENTO)
        alerta.periodo_calificaciones = ev.evaluado.nombre
        alerta.promedio, alerta.reprobadas, alerta.solo_descenso = promedio, len(reprobadas), solo_descenso


def alertas(filtros, ve_asistencia, ve_calificaciones, evaluaciones_=None):
    """[Alerta] de los estudiantes vigentes del alcance, de la más grave a la menos grave."""
    if filtros.ciclo is None or not (ve_asistencia or ve_calificaciones):
        return []
    evaluaciones_ = evaluaciones_ or academico.evaluaciones(filtros)
    vigentes = academico.vigentes_por_inscripcion(filtros)
    por_nivel = defaultdict(list)
    for pk, (_, _, _, nivel) in vigentes.items():
        por_nivel[nivel].append(pk)
    criterios = CriterioSeguimiento.por_nivel()
    encontradas = defaultdict(lambda: Alerta(inscripcion=None))
    for nivel in filtros.niveles_en_alcance:
        criterio, ev = criterios[nivel], evaluaciones_[nivel]
        if ve_asistencia and criterio.revisar_asistencia:
            _asistencia(filtros, nivel, por_nivel.get(nivel, []), criterio, ev, encontradas)
        if ve_calificaciones and criterio.revisar_rendimiento:
            _rendimiento(filtros, nivel, {k: v for k, v in vigentes.items() if v[3] == nivel}, criterio, ev, encontradas)
    if not encontradas:
        return []
    inscripciones = {i.pk: i for i in Inscripcion.objects.filter(pk__in=list(encontradas)).select_related('alumno', 'grupo__nombre', 'grupo__grado', 'grado')}
    lista = []
    for pk, alerta in encontradas.items():
        alerta.inscripcion = inscripciones[pk]
        criterio = criterios[alerta.inscripcion.grado.nivel]
        textos = ' '.join(t for _, t in alerta.motivos)
        if alerta.ambos or alerta.seguidas >= criterio.faltas_consecutivas or alerta.reprobadas >= criterio.reprobadas_prioridad_alta:
            alerta.prioridad = ALTA
        elif alerta.tipos == {RENDIMIENTO} and alerta.solo_descenso:
            alerta.prioridad = BAJA
        else:
            alerta.prioridad = MEDIA
        alerta.resumen = textos
        lista.append(alerta)
    return sorted(lista, key=lambda a: (a.gravedad, str(a.alumno)))


def resumen(lista):
    """Estudiantes únicos por motivo (cada estudiante cuenta una sola vez en el total)."""
    return {
        'inasistencia': sum(1 for a in lista if INASISTENCIA in a.tipos),
        'rendimiento': sum(1 for a in lista if RENDIMIENTO in a.tipos),
        'ambos': sum(1 for a in lista if a.ambos),
        'total': len(lista),
        'alta': sum(1 for a in lista if a.prioridad == ALTA),
        'media': sum(1 for a in lista if a.prioridad == MEDIA),
        'baja': sum(1 for a in lista if a.prioridad == BAJA),
    }


def filtrar(lista, motivo='', prioridad=''):
    if motivo == 'ambos':
        lista = [a for a in lista if a.ambos]
    elif motivo in (INASISTENCIA, RENDIMIENTO):
        lista = [a for a in lista if motivo in a.tipos]
    if prioridad in _RANGO:
        lista = [a for a in lista if a.prioridad == prioridad]
    return lista
