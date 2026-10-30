"""Boleta de calificaciones e historial académico (kárdex) de un estudiante (pedido del 2026-10-29).

- Solo cuentan las actas cerradas, como en el portal, la Vista 360 y la hoja semestral: un periodo en captura sale
  vacío. Cada periodo lleva la calificación final y las faltas que consideró el acta al calcularla.
- Un bloque por inscripción del ciclo: su grupo, sus materias y sus periodos (en preparatoria por semestres, los del
  semestre de su grado; el ciclo tiene dos bloques, el semestre A y el B).
- Preescolar, primaria y secundaria no tienen calificación final del ciclo: la boleta muestra el promedio de los
  periodos cerrados, rotulado «Promedio» (decisión del 2026-10-29) y calculado igual que en el portal.
- Preparatoria por semestres: además, el resultado del semestre (Calificaciones/calculo_semestral.py) con los mismos
  números que la hoja semestral, truncados a dos decimales. Se calcula para la inscripción misma, así que también sale
  para quien ya egresó o se dio de baja.
- Los datos oficiales del nivel (CCT y quien lo dirige) se capturan en Ajustes › Boletas (`DatosOficialesNivel`).
- La consultan e imprimen quienes ven todas las calificaciones; no está en el portal (decisión del 2026-10-29).
"""
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction

from django.db.models import Q

from Alumnos.clases import materias_cursadas
from Alumnos.models import ORDEN_NIVELES, Grado, Inscripcion
from Alumnos.periodos import periodos_para_grado
from PortalEstudiantes.resumen import promedio

from . import calculo_semestral as cs
from . import semestres
from .models import ActaCalificaciones, DatosOficialesNivel, ExamenSemestral


@dataclass
class MateriaDeBoleta:
    nombre: str
    profesor: str
    periodos: list                 # [(calificación Decimal o None, faltas int o None)], uno por periodo
    promedio: Decimal = None       # promedio de los periodos cerrados (sin cierre semestral)
    resultado: object = None       # preparatoria por semestres: calculo_semestral.ResultadoSemestral

    @property
    def faltas(self):
        return sum(f for _, f in self.periodos if f is not None)

    @property
    def semestral(self):
        """El resultado del semestre en texto (truncado), o None."""
        r = self.resultado
        if r is None:
            return None
        return {
            'promedio': cs.texto(r.promedio), 'exento': r.final_por_exencion, 'final': cs.texto(r.examen_final),
            'ordinaria': cs.texto(r.ordinaria), 'extraordinario': cs.texto(r.extraordinario), 'regularizacion': cs.texto(r.regularizacion),
            'definitiva': cs.texto(r.definitiva), 'estado': r.estado_texto, 'aprobada': r.aprobada, 'reprobada': r.reprobada,
        }


@dataclass
class Bloque:
    """Lo que la boleta y el kárdex muestran de una inscripción: un grupo en un ciclo (en preparatoria, un semestre)."""
    inscripcion: object
    periodos: list
    materias: list
    semestre: object = None
    promedios_por_periodo: list = field(default_factory=list)
    faltas_por_periodo: list = field(default_factory=list)

    @property
    def semestral(self):
        return self.semestre is not None

    @property
    def titulo(self):
        grupo = self.inscripcion.grupo
        return f'{self.semestre.nombre} · {grupo}' if self.semestre else str(grupo)

    @property
    def faltas(self):
        return sum(self.faltas_por_periodo)

    @property
    def por_periodo(self):
        """[(periodo, promedio del periodo, faltas del periodo)] para el pie de la tabla."""
        return list(zip(self.periodos, self.promedios_por_periodo, self.faltas_por_periodo))

    @property
    def promedio_general(self):
        """Sin cierre semestral, el promedio de los promedios de las materias (como el portal). Con cierre semestral,
        el de las calificaciones definitivas, solo cuando todas las materias ya tienen la suya (exacto y truncado)."""
        if not self.semestral:
            return promedio([m.promedio for m in self.materias])
        definitivas = [m.resultado.definitiva for m in self.materias if m.resultado is not None]
        if not self.materias or len(definitivas) != len(self.materias) or any(d is None for d in definitivas):
            return None
        return cs.truncar(sum(definitivas, Fraction(0)) / len(definitivas))

    @property
    def sin_definitiva(self):
        return sum(1 for m in self.materias if m.resultado is None or m.resultado.definitiva is None) if self.semestral else 0

    @property
    def aprobadas(self):
        return sum(1 for m in self.materias if m.resultado is not None and m.resultado.aprobada)

    @property
    def reprobadas(self):
        return sum(1 for m in self.materias if m.resultado is not None and m.resultado.reprobada)

    @property
    def periodos_cerrados(self):
        return sum(1 for valor in self.promedios_por_periodo if valor is not None)


def _del_periodo(cursada, periodo, capturas):
    """(calificación, faltas) de una materia en un periodo. Si la cursó en varias asignaciones (cambió de grupo de clase en
    la misma materia), la calificación de la más reciente que la tenga y la suma de sus faltas."""
    tomadas = [capturas[(a.pk, periodo.pk)] for a in cursada.asignaciones if (a.pk, periodo.pk) in capturas]
    calificacion = next((c for c, _ in reversed(tomadas) if c is not None), None)
    faltas = [f for _, f in tomadas if f is not None]
    return calificacion, (sum(faltas) if faltas else None)


def bloque_de(inscripcion):
    """El bloque de una inscripción, con las actas cerradas de su grupo y, en preparatoria, su resultado semestral."""
    ciclo, grado = inscripcion.ciclo, inscripcion.grado
    periodos = list(periodos_para_grado(ciclo, grado))
    semestre = semestres.semestre_de_grado_en(grado, ciclo)
    if semestre is not None:   # el resultado semestral es de los periodos del semestre
        periodos = [p for p in periodos if p.semestre_id == semestre.pk]
    cursadas = materias_cursadas(inscripcion)   # con sus grupos de clase; una materia, una sola fila
    asignaciones = [a for cursada in cursadas for a in cursada.asignaciones]
    capturas = {}
    for acta in ActaCalificaciones.objects.filter(asignacion__in=asignaciones, periodo__in=periodos, estado=ActaCalificaciones.CERRADA):
        fila = next((r for r in acta.resultados_cerrados or [] if r.get('inscripcion') == inscripcion.pk), None)
        if fila is not None:
            final = Decimal(fila['final']) if fila.get('final') not in (None, '') else None
            capturas[(acta.asignacion_id, acta.periodo_id)] = (final, fila.get('faltas'))
    examenes = {}
    if semestre is not None:
        for examen in ExamenSemestral.objects.filter(asignacion__in=asignaciones, inscripcion=inscripcion):
            examenes[(examen.asignacion_id, examen.tipo)] = examen.valor

    materias = []
    for cursada in cursadas:
        valores = [_del_periodo(cursada, periodo, capturas) for periodo in periodos]
        if cursada.sustituida and all(c is None and f is None for c, f in valores):
            continue   # un bloque simultáneo se la sustituyó antes de calificarla
        asignacion = cursada.actual
        materia = MateriaDeBoleta(nombre=cursada.materia.nombre, periodos=valores,
                                  profesor=asignacion.profesor.nombre_completo if asignacion.profesor_id else '')
        calificaciones = [c for c, _ in valores]
        if semestre is not None:
            # Los periodos que cuentan: en un grupo de clase, los de su bloque (igual que la hoja semestral)
            cuentan = {p.pk for a in cursada.asignaciones for p in semestres.periodos_de_la_hoja(a, periodos)}
            examen = lambda tipo: next((examenes[(a.pk, tipo)] for a in reversed(cursada.asignaciones) if (a.pk, tipo) in examenes), None)   # noqa: E731
            materia.resultado = cs.calcular([c for c, p in zip(calificaciones, periodos) if p.pk in cuentan], final=examen(cs.FINAL),
                                            extraordinario=examen(cs.EXTRAORDINARIO), regularizacion=examen(cs.REGULARIZACION))
        else:
            materia.promedio = promedio(calificaciones)
        materias.append(materia)
    return Bloque(
        inscripcion=inscripcion, periodos=periodos, materias=materias, semestre=semestre,
        promedios_por_periodo=[promedio([m.periodos[i][0] for m in materias]) for i in range(len(periodos))],
        faltas_por_periodo=[sum(m.periodos[i][1] or 0 for m in materias) for i in range(len(periodos))],
    )


def _inscripciones(alumno, ciclo=None):
    consulta = alumno.inscripciones.select_related('ciclo', 'grado', 'grupo__nombre', 'grupo__grado')
    if ciclo is not None:
        consulta = consulta.filter(ciclo=ciclo)
    return list(consulta.order_by('ciclo__fecha_inicio', 'fecha_inscripcion', 'grado__numero', 'pk'))


def datos_oficiales(nivel):
    return DatosOficialesNivel.objects.filter(nivel=nivel).first()


# ---------------------------------------------------------------------------
# Boleta de un ciclo
# ---------------------------------------------------------------------------
@dataclass
class Boleta:
    alumno: object
    ciclo: object
    bloques: list
    datos: object = None      # DatosOficialesNivel del nivel (o None)

    @property
    def nivel(self):
        return self.bloques[-1].inscripcion.grado.nivel if self.bloques else ''

    @property
    def nivel_texto(self):
        return dict(Grado.NIVEL_CHOICES).get(self.nivel, '')

    @property
    def semestral(self):
        return any(b.semestral for b in self.bloques)

    @property
    def grupo(self):
        return self.bloques[-1].inscripcion.grupo if self.bloques else None


def ciclos_con_inscripcion(alumno):
    """Los ciclos en que estuvo inscrito, del más reciente al más antiguo."""
    vistos, ciclos = set(), []
    for inscripcion in reversed(_inscripciones(alumno)):
        if inscripcion.ciclo_id not in vistos:
            vistos.add(inscripcion.ciclo_id)
            ciclos.append(inscripcion.ciclo)
    return ciclos


def boleta(alumno, ciclo):
    """La boleta del estudiante en el ciclo: un bloque por inscripción (en preparatoria, uno por semestre)."""
    bloques = [bloque_de(i) for i in _inscripciones(alumno, ciclo)]
    datos = Boleta(alumno=alumno, ciclo=ciclo, bloques=bloques)
    datos.datos = datos_oficiales(datos.nivel) if bloques else None
    return datos


def boletas_del_grupo(grupo, ciclo):
    """Las boletas de los estudiantes del grupo en el ciclo (también los que ya pasaron al semestre siguiente), en el
    orden de la lista."""
    inscripciones = (Inscripcion.objects.filter(Q(activa=True) | Q(concluida=True), grupo=grupo, ciclo=ciclo)
                     .select_related('alumno').order_by('alumno__apellido_paterno', 'alumno__apellido_materno', 'alumno__nombre'))
    return [boleta(i.alumno, ciclo) for i in inscripciones]


# ---------------------------------------------------------------------------
# Historial académico (kárdex)
# ---------------------------------------------------------------------------
@dataclass
class ResumenDeNivel:
    nivel: str
    nombre: str
    promedio: Decimal = None
    aprobadas: int = 0
    reprobadas: int = 0
    pendientes: int = 0
    semestral: bool = False


@dataclass
class Kardex:
    alumno: object
    bloques: list
    niveles: list            # ResumenDeNivel, en orden escolar


def kardex(alumno):
    """Todos sus ciclos, de su primera inscripción a la más reciente, con el resultado de cada materia y un resumen por
    nivel: en preparatoria por semestres, el promedio de las definitivas y cuántas materias aprobó, reprobó o tiene
    pendientes; en los demás niveles, el promedio de los promedios de sus materias."""
    bloques = [bloque_de(i) for i in _inscripciones(alumno)]
    nombres = dict(Grado.NIVEL_CHOICES)
    niveles = {}
    for bloque in bloques:
        nivel = bloque.inscripcion.grado.nivel
        resumen = niveles.setdefault(nivel, {'definitivas': [], 'promedios': [], 'datos': ResumenDeNivel(nivel, nombres.get(nivel, nivel))})
        if bloque.semestral:
            resumen['datos'].semestral = True
            for materia in bloque.materias:
                r = materia.resultado
                if r.definitiva is not None:
                    resumen['definitivas'].append(r.definitiva)
                resumen['datos'].aprobadas += r.aprobada
                resumen['datos'].reprobadas += r.reprobada
                resumen['datos'].pendientes += r.definitiva is None
        else:
            resumen['promedios'].extend(m.promedio for m in bloque.materias)
    for resumen in niveles.values():
        if resumen['definitivas']:
            resumen['datos'].promedio = cs.truncar(sum(resumen['definitivas'], Fraction(0)) / len(resumen['definitivas']))
        elif resumen['promedios']:
            resumen['datos'].promedio = promedio(resumen['promedios'])
    orden = [niveles[n]['datos'] for n in ORDEN_NIVELES if n in niveles]
    return Kardex(alumno=alumno, bloques=bloques, niveles=orden)
