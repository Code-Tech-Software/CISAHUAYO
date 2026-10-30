"""Grupos de clase (pedido del 2026-10-30): quién toma qué clase en cada fecha. Es el único lugar con estas reglas: el
horario, la asistencia, las actas, las boletas y las bitácoras preguntan aquí y no a `inscripcion.grupo`.

- Grupo base: en el que está inscrito el estudiante (`Inscripcion.grupo`). No cambia al entrar a una clase.
- Grupo de clase (`GrupoClase`): estudiantes de una o varias procedencias que cursan una materia con un docente. Su
  `asignacion` es una `MateriaGrado` de un grupo técnico; su lista de cada fecha son los `IntegranteClase` de esa fecha.
- Bloque simultáneo (`BloqueSimultaneo`): las clases que se imparten al mismo tiempo. Un bloque en preparación es un
  borrador: no cuenta para nada. Uno desactivado cuenta hasta el día anterior a su desactivación.
- Sustitución: mientras un estudiante está en una clase de un bloque, las clases del horario base que ese bloque
  sustituye (`BloqueSimultaneo.sustituye`) dejan de ser suyas: no le aparecen en el horario, no se le genera asistencia
  y sale de la lista del docente del grupo base en esas fechas. Lo ya registrado queda donde está.
- Las clases tradicionales no pasan por nada de esto: sin bloques en efecto, todo sigue siendo el grupo base.
"""
from dataclasses import dataclass, field
from datetime import timedelta

from django.db.models import Q

from .models import BloqueSimultaneo, EquivalenciaClase, IntegranteClase, MateriaGrado

EN_EFECTO = (BloqueSimultaneo.ACTIVO, BloqueSimultaneo.INACTIVO)


def q_vigentes_en(fecha):
    """Los integrantes de una clase en esa fecha: por sus fechas y por la vigencia de su bloque."""
    return q_traslapan(fecha, fecha)


def q_traslapan(desde, hasta):
    """Los integrantes cuya pertenencia toca el rango de fechas, dentro de la vigencia de su bloque."""
    return (
        Q(clase__bloque__estado__in=EN_EFECTO, desde__lte=hasta, clase__bloque__vigente_desde__lte=hasta, clase__bloque__vigente_hasta__gte=desde)
        & (Q(hasta__isnull=True) | Q(hasta__gte=desde))
        & (Q(clase__bloque__desactivado_en__isnull=True) | Q(clase__bloque__desactivado_en__gt=desde))
    )


def tramo_de(integrante):
    """(primer día, último día) reales de un integrante: sus fechas dentro de las de su bloque."""
    bloque = integrante.clase.bloque
    inicio = max(integrante.desde, bloque.vigente_desde)
    fin = min(integrante.hasta or bloque.vigente_hasta, bloque.vigente_hasta)
    if bloque.desactivado_en is not None:
        fin = min(fin, bloque.desactivado_en - timedelta(days=1))
    return inicio, fin


def _unir(tramos):
    """Une tramos de fechas que se tocan o se traslapan."""
    unidos = []
    for inicio, fin in sorted(tramos):
        if unidos and inicio <= unidos[-1][1] + timedelta(days=1):
            unidos[-1] = (unidos[-1][0], max(unidos[-1][1], fin))
        else:
            unidos.append((inicio, fin))
    return unidos


def _dentro(tramos, fecha):
    return any(inicio <= fecha <= fin for inicio, fin in tramos)


def _cubren(tramos, desde, hasta):
    return any(inicio <= desde and hasta <= fin for inicio, fin in _unir(tramos))


def hay_bloques(ciclo):
    """Si el ciclo tiene bloques en efecto: sin ellos no hace falta preguntar nada más."""
    return ciclo is not None and BloqueSimultaneo.objects.filter(ciclo=ciclo, estado__in=EN_EFECTO).exists()


# ---------------------------------------------------------------------------
# La lista de una asignación
# ---------------------------------------------------------------------------
def tramos_de_asignacion(asignacion, desde, hasta):
    """{id de inscripción: [(inicio, fin), …]}: en una clase, las fechas en que cada integrante está en ella; en una
    materia del grupo base, las fechas en que un bloque se la sustituye a cada estudiante."""
    if asignacion.es_de_clase:
        integrantes = IntegranteClase.objects.filter(q_traslapan(desde, hasta), clase__asignacion=asignacion)
    else:
        if not asignacion.sustituida_en.filter(estado__in=EN_EFECTO).exists():
            return {}
        integrantes = IntegranteClase.objects.filter(q_traslapan(desde, hasta), clase__bloque__sustituye=asignacion,
                                                     inscripcion__grupo=asignacion.grupo)
    tramos = {}
    for integrante in integrantes.select_related('clase__bloque'):
        tramos.setdefault(integrante.inscripcion_id, []).append(tramo_de(integrante))
    return {inscripcion: _unir(lista) for inscripcion, lista in tramos.items()}


@dataclass
class Lista:
    """Quiénes están en una asignación en un rango de fechas y qué días no les corresponden."""
    es_de_clase: bool
    tramos: dict

    def fuera(self, inscripcion_id, fecha):
        """Ese día el estudiante no está en esta asignación (no era de la clase, o el bloque se la sustituía)."""
        tramos = self.tramos.get(inscripcion_id)
        if self.es_de_clase:
            return not tramos or not _dentro(tramos, fecha)
        return bool(tramos) and _dentro(tramos, fecha)

    def salida(self, inscripcion_id, hasta):
        """El último día que estuvo, si dejó la asignación antes de `hasta` (None si siguió hasta el final)."""
        tramos = self.tramos.get(inscripcion_id)
        if not tramos:
            return None
        if self.es_de_clase:
            ultimo = tramos[-1][1]
            return ultimo if ultimo < hasta else None
        return tramos[0][0] - timedelta(days=1) if tramos[-1][1] >= hasta else None


def lista_de(asignacion, desde, hasta):
    return Lista(asignacion.es_de_clase, tramos_de_asignacion(asignacion, desde, hasta))


def sustituidos_todo_el_rango(asignacion, desde, hasta):
    """En una materia del grupo base: los estudiantes a los que un bloque se la sustituye durante todo el rango."""
    return [i for i, tramos in tramos_de_asignacion(asignacion, desde, hasta).items() if _cubren(tramos, desde, hasta)]


def pertenece(inscripcion, asignacion, fecha):
    """Si en esa fecha el estudiante está en esa asignación."""
    if inscripcion.ciclo_id != asignacion.ciclo_id:
        return False
    if asignacion.es_de_clase:
        return IntegranteClase.objects.filter(q_vigentes_en(fecha), clase__asignacion=asignacion, inscripcion=inscripcion).exists()
    if inscripcion.grupo_id != asignacion.grupo_id:
        return False
    return not IntegranteClase.objects.filter(q_vigentes_en(fecha), clase__bloque__sustituye=asignacion, inscripcion=inscripcion).exists()


# ---------------------------------------------------------------------------
# Las clases de un estudiante
# ---------------------------------------------------------------------------
class Pertenencias:
    """Las clases de muchos estudiantes en una fecha, con pocas consultas (la entrada y el cierre del día).

    `clases`: {id de inscripción: {id de asignación de sus clases}}; `sustituidas`: {id de inscripción: {id de las
    asignaciones del grupo base que un bloque le sustituye}}.
    """

    def __init__(self, fecha, ciclo, inscripciones=None):
        self.clases, self.sustituidas = {}, {}
        if not hay_bloques(ciclo):
            return
        integrantes = IntegranteClase.objects.filter(q_vigentes_en(fecha), clase__bloque__ciclo=ciclo)
        if inscripciones is not None:
            integrantes = integrantes.filter(inscripcion__in=inscripciones)
        por_bloque = {}
        for inscripcion, asignacion, bloque in integrantes.values_list('inscripcion_id', 'clase__asignacion_id', 'clase__bloque_id'):
            self.clases.setdefault(inscripcion, set()).add(asignacion)
            por_bloque.setdefault(bloque, set()).add(inscripcion)
        for bloque, asignacion in BloqueSimultaneo.sustituye.through.objects.filter(bloquesimultaneo__in=list(por_bloque)).values_list(
                'bloquesimultaneo_id', 'materiagrado_id'):
            for inscripcion in por_bloque[bloque]:
                self.sustituidas.setdefault(inscripcion, set()).add(asignacion)

    def clases_de(self, inscripcion, clases):
        """Las clases del día de un estudiante, a partir de `clases_por_grupo`: las de su grupo base, sin las que un
        bloque le sustituye, y las de sus grupos de clase. En orden de hora."""
        propias = self.clases.get(inscripcion.pk)
        quitadas = self.sustituidas.get(inscripcion.pk)
        lista = clases.get(inscripcion.grupo_id, [])
        if not propias and not quitadas:
            return lista
        lista = [clase for clase in lista if clase.asignacion.pk not in (quitadas or ())]
        extra = [clase for grupo in clases.values() for clase in grupo if clase.asignacion.pk in (propias or ())]
        return sorted(lista + extra, key=lambda clase: (clase.inicio, clase.asignacion.materia.nombre))


@dataclass
class MateriaCursada:
    """Una materia del plan del estudiante y las asignaciones en que la cursó (de la más antigua a la más reciente): casi
    siempre una; varias si cambió de grupo de clase en la misma materia, sin que eso cree otra materia."""
    materia: object
    asignaciones: list = field(default_factory=list)
    sustituida: bool = False   # la clase del grupo base de esta materia la sustituyó un bloque

    @property
    def actual(self):
        return self.asignaciones[-1]


def _materia_en_el_plan(clase, inscripcion, equivalencias):
    """La materia con que cuenta la clase para ese estudiante: la de su plan, si la clase mezcla grados."""
    return equivalencias.get((clase.pk, inscripcion.grado_id)) or clase.asignacion.materia


def integrantes_de(inscripcion):
    """Sus pasos por grupos de clase, en orden de fechas (los de bloques en preparación no cuentan)."""
    return list(
        IntegranteClase.objects.filter(inscripcion=inscripcion, clase__bloque__estado__in=EN_EFECTO)
        .select_related('clase__bloque', 'clase__asignacion__materia', 'clase__asignacion__profesor', 'clase__asignacion__ciclo',
                        'clase__asignacion__grado', 'clase__asignacion__grupo__grado')
        .order_by('desde', 'pk')
    )


def materias_cursadas(inscripcion):
    """Las materias del estudiante en su inscripción, en orden alfabético: las del plan de su grupo base y las de sus
    grupos de clase, cada materia una sola vez."""
    base = list(MateriaGrado.objects.filter(grupo=inscripcion.grupo, ciclo=inscripcion.ciclo, activa=True)
                .select_related('materia', 'profesor', 'grado', 'grupo__nombre', 'grupo__grado', 'ciclo').order_by('materia__nombre'))
    pasos = integrantes_de(inscripcion) if hay_bloques(inscripcion.ciclo) else []
    por_materia = {a.materia_id: MateriaCursada(a.materia, [a]) for a in base}
    if not pasos:
        return list(por_materia.values())
    equivalencias = {(e.clase_id, e.grado_id): e.materia for e in EquivalenciaClase.objects.filter(clase__in={p.clase_id for p in pasos}).select_related('materia')}
    sustituidas = set(BloqueSimultaneo.sustituye.through.objects.filter(bloquesimultaneo__in={p.clase.bloque_id for p in pasos})
                      .values_list('materiagrado_id', flat=True))
    for paso in pasos:
        materia = _materia_en_el_plan(paso.clase, inscripcion, equivalencias)
        cursada = por_materia.setdefault(materia.pk, MateriaCursada(materia))
        if paso.clase.asignacion not in cursada.asignaciones:
            cursada.asignaciones.append(paso.clase.asignacion)
    for cursada in por_materia.values():
        cursada.sustituida = len(cursada.asignaciones) == 1 and cursada.asignaciones[0].pk in sustituidas
    return sorted(por_materia.values(), key=lambda c: c.materia.nombre)


def grupos_de_clase_de(alumno, ciclo_id=None):
    """Sus pasos por grupos de clase, de los más recientes: el expediente los muestra junto a su grupo base."""
    pasos = (IntegranteClase.objects.filter(inscripcion__alumno=alumno, clase__bloque__estado__in=EN_EFECTO)
             .select_related('clase__bloque__ciclo', 'clase__asignacion__materia', 'clase__asignacion__profesor', 'inscripcion__grupo__grado', 'inscripcion__grupo__nombre')
             .order_by('-desde', '-pk'))
    if ciclo_id is not None:
        pasos = pasos.filter(clase__bloque__ciclo_id=ciclo_id)
    resultado = []
    for paso in pasos:
        inicio, fin = tramo_de(paso)
        resultado.append({
            'nombre': paso.clase.nombre, 'bloque': paso.clase.bloque.nombre, 'ciclo': paso.clase.bloque.ciclo, 'materia': paso.clase.asignacion.materia,
            'profesor': paso.clase.asignacion.profesor, 'aula': paso.clase.aula, 'grupo_base': paso.inscripcion.grupo, 'desde': inicio, 'hasta': fin,
        })
    return resultado


def asignaciones_de(inscripcion):
    """Todas sus asignaciones: las de su grupo base y las de sus grupos de clase."""
    return [a for cursada in materias_cursadas(inscripcion) for a in cursada.asignaciones]


# ---------------------------------------------------------------------------
# Horario del estudiante y del grupo base
# ---------------------------------------------------------------------------
def bloques_del_estudiante(inscripcion, fecha, calendario=None):
    """Los bloques de horario del estudiante en la semana de esa fecha: los de su grupo base, sin los que un bloque
    simultáneo le sustituye ese día, y solo la opción que cursa cada día."""
    from .semanas import bloques_de_semana, lunes_de
    ciclo = inscripcion.ciclo
    if not hay_bloques(ciclo):
        return bloques_de_semana(fecha, ciclo, calendario, materia_grado__grupo=inscripcion.grupo)
    pasos = integrantes_de(inscripcion)
    if not pasos:
        return bloques_de_semana(fecha, ciclo, calendario, materia_grado__grupo=inscripcion.grupo)
    en_clase, sustituidas = {}, {}
    sustituye = {}
    for bloque, asignacion in BloqueSimultaneo.sustituye.through.objects.filter(bloquesimultaneo__in={p.clase.bloque_id for p in pasos}).values_list(
            'bloquesimultaneo_id', 'materiagrado_id'):
        sustituye.setdefault(bloque, []).append(asignacion)
    for paso in pasos:
        tramo = tramo_de(paso)
        en_clase.setdefault(paso.clase.asignacion_id, []).append(tramo)
        for asignacion in sustituye.get(paso.clase.bloque_id, ()):
            sustituidas.setdefault(asignacion, []).append(tramo)
    bloques = bloques_de_semana(fecha, ciclo, calendario).filter(Q(materia_grado__grupo=inscripcion.grupo) | Q(materia_grado__in=list(en_clase)))
    lunes, fuera = lunes_de(fecha), []
    for pk, dia, asignacion in bloques.values_list('pk', 'dia_semana', 'materia_grado_id'):
        dia_real = lunes + timedelta(days=dia)
        if (asignacion in en_clase and not _dentro(en_clase[asignacion], dia_real)) or (asignacion in sustituidas and _dentro(sustituidas[asignacion], dia_real)):
            fuera.append(pk)
    return bloques.exclude(pk__in=fuera)


def bloques_del_grupo(grupo, ciclo):
    """Los bloques simultáneos en efecto en los que participan estudiantes del grupo base, con sus horarios y opciones."""
    if ciclo is None:
        return []
    return list(grupo.bloques_de_origen.filter(ciclo=ciclo, estado=BloqueSimultaneo.ACTIVO).prefetch_related(
        'horarios', 'opciones__asignacion__materia', 'opciones__asignacion__profesor', 'sustituye'))


def bloque_empalmado(grupo, ciclo, dia, inicio, fin, semana='', asignacion=None):
    """El bloque activo del grupo base que choca con esa hora (None si no hay): a esa hora sus estudiantes están en sus
    opciones, salvo que el bloque sustituya justo esa clase."""
    for bloque in bloques_del_grupo(grupo, ciclo):
        if asignacion is not None and any(a.pk == asignacion.pk for a in bloque.sustituye.all()):
            continue
        for horario in bloque.horarios.all():
            if horario.dia_semana == dia and horario.hora_inicio < fin and inicio < horario.hora_fin and (not semana or not horario.semana or semana == horario.semana):
                return bloque
    return None


@dataclass
class BloqueEnElHorario:
    """Un bloque simultáneo en el horario de un grupo base: no es una materia, sino la indicación de que sus estudiantes
    se distribuyen entre varias clases."""
    bloque: object
    dia_semana: int
    hora_inicio: object
    hora_fin: object
    semana: str = ''
    es_simultaneo: bool = True

    @property
    def opciones(self):
        return [o for o in self.bloque.opciones.all() if o.activa]

    @property
    def materias_texto(self):
        return ', '.join(o.nombre for o in self.opciones)


def en_el_horario(bloques):
    """Una celda de horario por cada día y hora de esos bloques."""
    return [BloqueEnElHorario(b, h.dia_semana, h.hora_inicio, h.hora_fin, h.semana) for b in bloques for h in b.horarios.all()]


def sustituidas_por(bloques):
    """{id de asignación: nombre del bloque} de las clases del grupo base que esos bloques sustituyen."""
    return {a.pk: b.nombre for b in bloques for a in b.sustituye.all()}


# ---------------------------------------------------------------------------
# Docentes y estudiantes: quién le da clase a quién (mensajes, reuniones, bitácoras)
# ---------------------------------------------------------------------------
def alumnos_en_clases_de(usuario, ciclo, fecha):
    """Los estudiantes (ids) que esa fecha están en grupos de clase de esa cuenta docente."""
    return IntegranteClase.objects.filter(q_vigentes_en(fecha), clase__asignacion__profesor__usuario=usuario, clase__bloque__ciclo=ciclo).values('inscripcion__alumno')


def asignaciones_de_clase_de(alumnos, ciclo, fecha):
    """Las asignaciones de los grupos de clase en que están esos estudiantes esa fecha."""
    return MateriaGrado.objects.filter(pk__in=IntegranteClase.objects.filter(
        q_vigentes_en(fecha), inscripcion__alumno__in=alumnos, clase__bloque__ciclo=ciclo).values('clase__asignacion'))
