"""Ayudantes de horarios: resumen de bloques, horas por semana, cuadrícula semanal y empalmes.

El horario es de cada grupo (su salón): una materia no puede empalmarse con otra del mismo grupo ni con uno de sus
recesos. Un profesor tampoco puede estar en dos grupos a la vez.

Con semanas A y B (Alumnos/semanas.py): en un grupo, un bloque de la semana A no choca con uno de la B; los recesos son
de todas las semanas. Entre grupos de niveles distintos, dos bloques de un profesor chocan si de verdad caen en una
misma fecha (cada nivel alterna con su propia referencia; los de horario fijo, todas las semanas).
"""
from collections import defaultdict

from .models import HorarioMateria, Recreo

DIAS = dict(HorarioMateria.DIA_CHOICES)
DIAS_CORTOS = {0: 'Lun', 1: 'Mar', 2: 'Mié', 3: 'Jue', 4: 'Vie', 5: 'Sáb', 6: 'Dom'}
DIAS_HABILES = (0, 1, 2, 3, 4)


def minutos(hora):
    return hora.hour * 60 + hora.minute


def duracion(bloque):
    """Minutos que dura un bloque."""
    return minutos(bloque.hora_fin) - minutos(bloque.hora_inicio)


def formatear_duracion(total):
    """90 -> «1 h 30 min»; 120 -> «2 h»; 45 -> «45 min»."""
    horas, resto = divmod(total, 60)
    if horas and resto:
        return f'{horas} h {resto} min'
    if horas:
        return f'{horas} h'
    return f'{resto} min'


def minutos_semanales(bloques):
    """Minutos de clase por semana. Con semanas A y B, los de todas las semanas más los de la semana más cargada."""
    por_semana = defaultdict(int)
    for bloque in bloques:
        por_semana[getattr(bloque, 'semana', '')] += duracion(bloque)
    return por_semana[''] + max(por_semana['A'], por_semana['B'])


def resumen_horario(bloques):
    """Líneas legibles: los días que comparten hora se agrupan («Lun, Mié · 08:00–09:00»)."""
    grupos = {}
    for bloque in bloques:
        grupos.setdefault((getattr(bloque, 'semana', ''), bloque.hora_inicio, bloque.hora_fin), set()).add(bloque.dia_semana)
    lineas = []
    for (semana, inicio, fin), dias in sorted(grupos.items(), key=lambda item: (item[0][0], min(item[1]), item[0][1:])):
        nombres = ', '.join(DIAS_CORTOS[dia] for dia in sorted(dias))
        prefijo = f'Sem. {semana} · ' if semana else ''
        lineas.append(f'{prefijo}{nombres} · {inicio:%H:%M}–{fin:%H:%M}')
    return lineas


def con_resumen_de_horario(asignaciones):
    """Agrega a cada asignación materia-grado su resumen: `lineas`, `bloques`, `minutos` y `duracion`.

    Las asignaciones deben venir con `prefetch_related('horarios')` para no consultar una vez por fila.
    """
    asignaciones = list(asignaciones)
    for asignacion in asignaciones:
        bloques = list(asignacion.horarios.all())
        asignacion.bloques = len(bloques)
        asignacion.lineas = resumen_horario(bloques)
        asignacion.minutos = minutos_semanales(bloques)
        asignacion.duracion = formatear_duracion(asignacion.minutos) if asignacion.minutos else ''
    return asignaciones


class Celda(list):
    """Los bloques de una celda de la cuadrícula (casi siempre uno). `filas`: cuántas franjas seguidas ocupa (el
    `rowspan`); `oculta`: la ocupa una celda de una fila anterior, así que no se dibuja; `con_horas`: los bloques dicen
    su hora porque la celda no coincide con una sola franja."""

    def __init__(self, bloques=(), filas=1, oculta=False):
        super().__init__(bloques)
        self.filas, self.oculta = filas, oculta
        self.con_horas = filas > 1 or len({(b.hora_inicio, b.hora_fin) for b in self}) > 1


def _agrupar_traslapes(bloques):
    """[(inicio, fin, [bloques])] de un día: los bloques que se traslapan (p. ej. de las semanas A y B vistas juntas, o
    un error de captura) comparten celda; los demás, una cada uno. En orden de hora."""
    grupos = []
    for bloque in sorted(bloques, key=lambda b: (b.hora_inicio, b.hora_fin)):
        if grupos and bloque.hora_inicio < grupos[-1][1]:
            inicio, fin, juntos = grupos[-1]
            grupos[-1] = (inicio, max(fin, bloque.hora_fin), juntos + [bloque])
        else:
            grupos.append((bloque.hora_inicio, bloque.hora_fin, [bloque]))
    return grupos


def cuadricula(bloques):
    """Horario semanal como tabla: una fila por franja y una columna por día.

    Las franjas son los tramos entre todas las horas de inicio y de fin del horario (sin los huecos que nadie ocupa), así
    que un bloque que dura dos o más franjas, como un laboratorio de dos horas, ocupa esas filas seguidas (`rowspan`) en
    lugar de abrir una fila propia (corrección del 2026-11-19: antes había una fila por cada par inicio-fin distinto y
    el laboratorio de 08:00 a 09:40 salía en una fila aparte, entre la de 08:00 y la de 08:50).

    Siempre salen de lunes a viernes; sábado y domingo solo si tienen bloques. Cada celda es una `Celda` (una lista de
    bloques); las que cubre un bloque de una fila anterior vienen vacías y con `oculta`.
    """
    bloques = [b for b in bloques if b.hora_inicio < b.hora_fin]
    dias = sorted(set(DIAS_HABILES) | {bloque.dia_semana for bloque in bloques})
    cortes = sorted({b.hora_inicio for b in bloques} | {b.hora_fin for b in bloques})
    franjas = [(inicio, fin) for inicio, fin in zip(cortes, cortes[1:])
               if any(b.hora_inicio <= inicio and fin <= b.hora_fin for b in bloques)]
    fila_de = {inicio: i for i, (inicio, _) in enumerate(franjas)}

    tabla = [[None] * len(dias) for _ in franjas]
    for columna, dia in enumerate(dias):
        for inicio, fin, juntos in _agrupar_traslapes([b for b in bloques if b.dia_semana == dia]):
            primera = fila_de[inicio]
            ocupadas = sum(1 for desde, hasta in franjas if inicio <= desde and hasta <= fin)
            tabla[primera][columna] = Celda(juntos, filas=ocupadas)
            for siguiente in range(primera + 1, primera + ocupadas):
                tabla[siguiente][columna] = Celda(oculta=True)
    return {
        'dias': [{'numero': dia, 'nombre': DIAS[dia], 'corto': DIAS_CORTOS[dia]} for dia in dias],
        'filas': [
            {'inicio': inicio, 'fin': fin, 'celdas': [celda if celda is not None else Celda() for celda in tabla[i]]}
            for i, (inicio, fin) in enumerate(franjas)
        ],
    }


def bloques_empalmados(grupo, ciclo, dia, inicio, fin, excluir_pk=None, semana=''):
    """Bloques de las materias vigentes del grupo que se empalman con el intervalo indicado (mismo día). Con `semana`
    (A o B), solo los de esa semana y los de todas."""
    bloques = HorarioMateria.objects.filter(
        materia_grado__ciclo=ciclo, materia_grado__grupo=grupo, materia_grado__activa=True,
        dia_semana=dia, hora_inicio__lt=fin, hora_fin__gt=inicio,
    ).select_related('materia_grado__materia')
    if semana:
        bloques = bloques.filter(semana__in=['', semana])
    if excluir_pk is not None:
        bloques = bloques.exclude(pk=excluir_pk)
    return bloques


def recreos_empalmados(grupo, ciclo, dia, inicio, fin, excluir_pk=None):
    """Recesos del grupo en el ciclo que se empalman con el intervalo indicado (mismo día)."""
    recreos = Recreo.objects.filter(
        ciclo=ciclo, grupo=grupo, dia_semana=dia, hora_inicio__lt=fin, hora_fin__gt=inicio,
    )
    if excluir_pk is not None:
        recreos = recreos.exclude(pk=excluir_pk)
    return recreos


def recreos_del_grupo(grupo, ciclo):
    """Los recesos del grupo en el ciclo, por día y hora."""
    if ciclo is None:
        return Recreo.objects.none()
    return Recreo.objects.filter(grupo=grupo, ciclo=ciclo).order_by('dia_semana', 'hora_inicio')


def se_empalman(a, b):
    """Dos intervalos (día, inicio, fin) se empalman si son del mismo día y se traslapan (tocarse en el borde no cuenta)."""
    return a[0] == b[0] and a[1] < b[2] and b[1] < a[2]


def bloques_del_profesor_empalmados(profesor, ciclo, dia, inicio, fin, excluir_pk=None, excluir_grupo=None,
                                    semana='', nivel=None, desde=None, excluir_asignacion=None):
    """Bloques de las materias vigentes que el profesor da en el ciclo y que se empalman con el intervalo (mismo día).

    `excluir_grupo` deja fuera a un grupo: sus empalmes ya se revisan aparte, como empalmes del grupo. Con `semana`
    (A o B) y el `nivel` del bloque nuevo, solo cuentan los que de verdad caen en una misma fecha (desde `desde`).
    """
    from .semanas import Calendario, coinciden

    bloques = HorarioMateria.objects.filter(
        materia_grado__profesor=profesor, materia_grado__ciclo=ciclo, materia_grado__activa=True,
        dia_semana=dia, hora_inicio__lt=fin, hora_fin__gt=inicio,
    ).select_related('materia_grado__materia', 'materia_grado__grado', 'materia_grado__grupo__grado', 'materia_grado__grupo__nombre')
    if excluir_pk is not None:
        bloques = bloques.exclude(pk=excluir_pk)
    if excluir_grupo is not None:
        bloques = bloques.exclude(materia_grado__grupo=excluir_grupo)
    if excluir_asignacion is not None:
        bloques = bloques.exclude(materia_grado=excluir_asignacion)
    bloques = list(bloques)
    if not semana or not any(b.semana for b in bloques):
        return bloques
    calendario = Calendario(ciclo)
    return [
        b for b in bloques
        if coinciden(nivel, semana, b.materia_grado.grado.nivel, b.semana, ciclo,
                     desde=max(filter(None, (desde, b.vigente_desde)), default=None), calendario=calendario)
    ]


def mensaje_de_empalme_profesor(profesor, bloques):
    partes = [
        f'{b.materia_grado.materia} en {b.materia_grado.grupo} ({DIAS[b.dia_semana].lower()} {b.hora_inicio:%H:%M}–{b.hora_fin:%H:%M}'
        + (f', semana {b.semana})' if b.semana else ')')
        for b in bloques
    ]
    return f'{profesor} ya da {", ".join(partes)}: un profesor no puede estar en dos grupos a la vez.'


def conflictos_de_asignacion(profesor, asignacion):
    """Bloques de otras materias del profesor que se empalman con el horario ya armado de esta asignación."""
    ajenos = {}
    for propio in asignacion.horarios.all():
        empalmados = bloques_del_profesor_empalmados(
            profesor, asignacion.ciclo, propio.dia_semana, propio.hora_inicio, propio.hora_fin,
            semana=propio.semana, nivel=asignacion.grado.nivel, desde=propio.vigente_desde, excluir_asignacion=asignacion,
        )
        for bloque in empalmados:
            ajenos[bloque.pk] = bloque
    return list(ajenos.values())


def minutos_por_profesor(ids, ciclo):
    """{id de profesor: minutos de clase por semana en el ciclo} para los profesores indicados."""
    minutos = defaultdict(int)
    if ciclo and ids:
        bloques = HorarioMateria.objects.filter(
            materia_grado__profesor__in=ids, materia_grado__ciclo=ciclo, materia_grado__activa=True,
        ).select_related('materia_grado')
        por_profesor = defaultdict(list)
        for bloque in bloques:
            por_profesor[bloque.materia_grado.profesor_id].append(bloque)
        for profesor_id, suyos in por_profesor.items():
            minutos[profesor_id] = minutos_semanales(suyos)   # con semanas A y B, la más cargada
    return minutos
