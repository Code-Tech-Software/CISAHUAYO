"""Ayudantes de horarios: resumen de bloques, horas por semana, cuadrícula semanal y empalmes.

Con un solo grupo por grado, el horario de un grado en un ciclo es el horario de su salón: una materia no puede
empalmarse con otra del mismo grado.
"""
from collections import defaultdict

from .models import HorarioMateria

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
    return sum(duracion(bloque) for bloque in bloques)


def resumen_horario(bloques):
    """Líneas legibles: los días que comparten hora se agrupan («Lun, Mié · 08:00–09:00»)."""
    grupos = {}
    for bloque in bloques:
        grupos.setdefault((bloque.hora_inicio, bloque.hora_fin), set()).add(bloque.dia_semana)
    lineas = []
    for (inicio, fin), dias in sorted(grupos.items(), key=lambda item: (min(item[1]), item[0])):
        nombres = ', '.join(DIAS_CORTOS[dia] for dia in sorted(dias))
        lineas.append(f'{nombres} · {inicio:%H:%M}–{fin:%H:%M}')
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


def cuadricula(bloques):
    """Horario semanal como tabla: una fila por cada franja (inicio-fin) y una columna por día.

    Siempre salen de lunes a viernes; sábado y domingo solo si tienen bloques. Cada celda es una lista
    (casi siempre de un bloque; si por un error de captura hubiera dos, se muestran ambos).
    """
    bloques = list(bloques)
    dias = sorted(set(DIAS_HABILES) | {bloque.dia_semana for bloque in bloques})
    franjas = sorted({(bloque.hora_inicio, bloque.hora_fin) for bloque in bloques})
    celdas = {}
    for bloque in bloques:
        celdas.setdefault((bloque.hora_inicio, bloque.hora_fin, bloque.dia_semana), []).append(bloque)
    return {
        'dias': [{'numero': dia, 'nombre': DIAS[dia], 'corto': DIAS_CORTOS[dia]} for dia in dias],
        'filas': [
            {'inicio': inicio, 'fin': fin, 'celdas': [celdas.get((inicio, fin, dia), []) for dia in dias]}
            for inicio, fin in franjas
        ],
    }


def bloques_empalmados(grado, ciclo, dia, inicio, fin, excluir_pk=None):
    """Bloques de las materias vigentes del grado que se empalman con el intervalo indicado (mismo día)."""
    bloques = HorarioMateria.objects.filter(
        materia_grado__ciclo=ciclo, materia_grado__grado=grado, materia_grado__activa=True,
        dia_semana=dia, hora_inicio__lt=fin, hora_fin__gt=inicio,
    ).select_related('materia_grado__materia')
    if excluir_pk is not None:
        bloques = bloques.exclude(pk=excluir_pk)
    return bloques


def se_empalman(a, b):
    """Dos intervalos (día, inicio, fin) se empalman si son del mismo día y se traslapan (tocarse en el borde no cuenta)."""
    return a[0] == b[0] and a[1] < b[2] and b[1] < a[2]


def bloques_del_profesor_empalmados(profesor, ciclo, dia, inicio, fin, excluir_pk=None, excluir_grado=None):
    """Bloques de las materias vigentes que el profesor da en el ciclo y que se empalman con el intervalo (mismo día).

    `excluir_grado` deja fuera a un grado: sus empalmes ya se revisan aparte, como empalmes del grupo.
    """
    bloques = HorarioMateria.objects.filter(
        materia_grado__profesor=profesor, materia_grado__ciclo=ciclo, materia_grado__activa=True,
        dia_semana=dia, hora_inicio__lt=fin, hora_fin__gt=inicio,
    ).select_related('materia_grado__materia', 'materia_grado__grado')
    if excluir_pk is not None:
        bloques = bloques.exclude(pk=excluir_pk)
    if excluir_grado is not None:
        bloques = bloques.exclude(materia_grado__grado=excluir_grado)
    return bloques


def mensaje_de_empalme_profesor(profesor, bloques):
    partes = [
        f'{b.materia_grado.materia} en {b.materia_grado.grado} ({DIAS[b.dia_semana].lower()} {b.hora_inicio:%H:%M}–{b.hora_fin:%H:%M})'
        for b in bloques
    ]
    return f'{profesor} ya da {", ".join(partes)}: un profesor no puede estar en dos grupos a la vez.'


def conflictos_de_asignacion(profesor, asignacion):
    """Bloques de otras materias del profesor que se empalman con el horario ya armado de esta asignación."""
    ajenos = {}
    for propio in asignacion.horarios.all():
        empalmados = bloques_del_profesor_empalmados(
            profesor, asignacion.ciclo, propio.dia_semana, propio.hora_inicio, propio.hora_fin,
        ).exclude(materia_grado=asignacion)
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
        for bloque in bloques:
            minutos[bloque.materia_grado.profesor_id] += duracion(bloque)
    return minutos
