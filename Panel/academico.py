"""Calificaciones para el panel: solo las finales de las actas cerradas (las mismas que ven el portal y la Vista 360).

- Un acta en captura es provisional: no entra en promedios ni en reprobación; se cuenta aparte, en el avance de captura.
- Una calificación pendiente (sin final) no se toma como cero: simplemente no cuenta.
- Solo se juntan calificaciones de la misma escala (máximo 10, la que usa el sistema); las de otra escala se omiten y se
  dice cuántas.
- El periodo evaluado de cada nivel es el elegido (o su periodo actual) si ya tiene actas cerradas; si no, el más reciente
  anterior que sí tenga: así el panel muestra resultados reales y dice de qué periodo son.
- Solo cuentan los estudiantes vigentes del alcance (inscripción activa y estudiante activo).
"""
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from Alumnos.models import MateriaGrado
from Calificaciones.models import ActaCalificaciones
from Calificaciones.reglas import periodo_sugerido

ESCALA = Decimal('10')


def promedio(valores):
    """El promedio que usa el sistema (sin las pendientes), a dos decimales; None sin valores."""
    valores = [v for v in valores if v is not None]
    if not valores:
        return None
    return (sum(valores) / len(valores)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


@dataclass
class Evaluacion:
    """Los periodos de un nivel: `base` (el elegido o el actual), `evaluado` (el que tiene actas cerradas) y
    `anterior` (el previo al evaluado, para comparar)."""
    nivel: str
    periodos: list = field(default_factory=list)
    base: object = None
    evaluado: object = None
    anterior: object = None

    @property
    def nota(self):
        if self.evaluado is None:
            return 'Sin actas cerradas en el ciclo'
        if self.base is not None and self.evaluado.pk != self.base.pk:
            return f'{self.base.nombre} sin actas cerradas: se muestra {self.evaluado.nombre}'
        return ''


@dataclass
class Resultado:
    inscripcion: int
    alumno: int
    grupo: int
    grado: int
    nivel: str
    asignacion: int
    materia: str
    final: Decimal


def asignaciones(filtros, nivel):
    """Las materias del alcance. Las de los grupos de clase son de varios grupos base: se toman todas y lo que cuenta de
    ellas son sus estudiantes del alcance (`vigentes`)."""
    del_nivel = MateriaGrado.objects.filter(ciclo=filtros.ciclo, activa=True, grado__nivel=nivel)
    return filtros.filtrar(del_nivel) | del_nivel.filter(clase__isnull=False)


def _escala(acta):
    try:
        return Decimal(str((acta.configuracion_cerrada or {}).get('reglas', {}).get('limite_maximo', '10')))
    except ArithmeticError:
        return None


def resultados(filtros, periodo, nivel, vigentes):
    """([Resultado], omitidas por escala) de las actas cerradas del periodo en el alcance. `vigentes` es
    {inscripcion: (alumno, grupo, grado, nivel)}."""
    actas = (ActaCalificaciones.objects.filter(asignacion__in=asignaciones(filtros, nivel), periodo=periodo, estado=ActaCalificaciones.CERRADA)
             .select_related('asignacion__materia').only('asignacion__materia__nombre', 'asignacion_id', 'resultados_cerrados', 'configuracion_cerrada'))
    lista, omitidas = [], 0
    for acta in actas:
        misma_escala = _escala(acta) == ESCALA
        for fila in acta.resultados_cerrados or []:
            datos = vigentes.get(fila.get('inscripcion'))
            if datos is None or fila.get('final') in (None, ''):
                continue
            if not misma_escala:
                omitidas += 1
                continue
            alumno, grupo, grado, nivel_del = datos
            lista.append(Resultado(fila['inscripcion'], alumno, grupo, grado, nivel_del, acta.asignacion_id,
                                   acta.asignacion.materia.nombre, Decimal(str(fila['final']))))
    return lista, omitidas


def _tiene_cerradas(filtros, nivel, periodo):
    return ActaCalificaciones.objects.filter(asignacion__in=asignaciones(filtros, nivel), periodo=periodo,
                                             estado=ActaCalificaciones.CERRADA).exists()


def evaluaciones(filtros):
    """{nivel: Evaluacion} de los niveles del alcance."""
    datos = {}
    for nivel in filtros.niveles_en_alcance:
        periodos = filtros.periodos_de(nivel)
        ev = Evaluacion(nivel=nivel, periodos=periodos)
        if periodos:
            if filtros.nivel == nivel and filtros.periodo is not None:
                ev.base = filtros.periodo
            elif filtros.hoy_en_ciclo:
                ev.base = periodo_sugerido(periodos, filtros.hoy)
            else:
                ev.base = periodos[-1]
            indice = periodos.index(ev.base)
            for i in range(indice, -1, -1):
                if _tiene_cerradas(filtros, nivel, periodos[i]):
                    ev.evaluado = periodos[i]
                    if i > 0:
                        ev.anterior = periodos[i - 1]
                    break
        datos[nivel] = ev
    return datos


def vigentes_por_inscripcion(filtros):
    """{inscripcion: (alumno, grupo, grado, nivel)} de los estudiantes vigentes del alcance."""
    return {pk: (alumno, grupo, grado, nivel) for pk, alumno, grupo, grado, nivel in
            filtros.inscripciones().values_list('pk', 'alumno_id', 'grupo_id', 'grado_id', 'grado__nivel')}


def avance_de_captura(filtros, evaluaciones_):
    """Las actas del periodo base de cada nivel: cerradas, en captura y sin abrir (materias sin acta todavía)."""
    total = {'cerradas': 0, 'en_captura': 0, 'sin_acta': 0}
    for nivel, ev in evaluaciones_.items():
        if ev.base is None:
            continue
        ids = list(asignaciones(filtros, nivel).values_list('pk', flat=True))
        estados = dict(ActaCalificaciones.objects.filter(asignacion__in=ids, periodo=ev.base).values_list('asignacion_id', 'estado'))
        total['cerradas'] += sum(1 for e in estados.values() if e == ActaCalificaciones.CERRADA)
        total['en_captura'] += sum(1 for e in estados.values() if e == ActaCalificaciones.EN_CAPTURA)
        total['sin_acta'] += len(ids) - len(estados)
    total['total'] = sum(total.values())
    total['pendientes'] = total['en_captura'] + total['sin_acta']
    return total


def pendientes_de_periodos_terminados(filtros):
    """Materias de periodos ya terminados (fecha de cierre anterior a hoy) cuya acta no se ha cerrado."""
    pendientes = 0
    for nivel in filtros.niveles_en_alcance:
        terminados = [p for p in filtros.periodos_de(nivel) if p.fecha_fin < filtros.hoy]
        if not terminados:
            continue
        ids = list(asignaciones(filtros, nivel).values_list('pk', flat=True))
        for periodo in terminados:
            cerradas = ActaCalificaciones.objects.filter(asignacion__in=ids, periodo=periodo, estado=ActaCalificaciones.CERRADA).count()
            pendientes += len(ids) - cerradas
    return pendientes


def por_inscripcion(lista):
    """{inscripcion: {asignacion: final}}."""
    datos = defaultdict(dict)
    for r in lista:
        datos[r.inscripcion][r.asignacion] = r.final
    return datos
