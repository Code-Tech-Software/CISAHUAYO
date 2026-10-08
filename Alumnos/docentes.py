"""La relación de los profesores con las materias.

Hay dos niveles, y conviene no confundirlos:

- **Habilitación** (`ProfesorMateria`): qué materias puede impartir un profesor. No depende del ciclo ni del grado;
  sirve para sugerir a las personas adecuadas al asignar.
- **Asignación** (`MateriaGrado.profesor`): quién imparte de verdad cada materia en cada grado y ciclo. Como el colegio
  tiene un solo grupo por grado, una asignación es un grupo.

Aquí vive la lógica que comparten las pantallas que asignan profesores (el perfil del profesor, del grado, de la materia y
el tablero de asignaciones) y los cálculos de carga de trabajo.
"""
from collections import defaultdict

from django.db import transaction
from django.db.models import Count, Q

from .academico import ciclo_editable
from .horarios import conflictos_de_asignacion, formatear_duracion, mensaje_de_empalme_profesor, minutos_semanales
from .models import Grado, MateriaGrado, Profesor, ProfesorMateria, ProfesorNivel

ESTADOS_DE_CARGA = {
    'libre': 'Sin clases',
    'normal': 'Con carga',
    'completa': 'Carga completa',
    'sobrecarga': 'Sobrecargado',
    'sin_limite': 'Con carga',
}


# ---------------------------------------------------------------------------
# Asignar
# ---------------------------------------------------------------------------
def asignar_profesor(asignaciones, profesor):
    """Fija `profesor` (o, con None, quita al que estaba) en cada asignación materia-grado.

    Se omite lo que no se puede: un ciclo cerrado, una materia que ya no se imparte en ese grado, un profesor que no da
    clases en el nivel del grado o que quedaría en dos grupos a la vez. Devuelve `(cambios, omitidas)`: `cambios` es la
    lista de `(asignación, profesor anterior)` y `omitidas` los textos que explican cada omisión. No manda mensajes ni deja
    bitácora: eso es de la vista.
    """
    cambios, omitidas = [], []
    niveles = set(profesor.niveles.values_list('nivel', flat=True)) if profesor else set()
    with transaction.atomic():
        for asignacion in asignaciones:
            etiqueta = f'{asignacion.materia} de {asignacion.grado}'
            if not ciclo_editable(asignacion.ciclo):
                omitidas.append(f'{etiqueta}: el ciclo {asignacion.ciclo} está cerrado.')
            elif not asignacion.activa:
                omitidas.append(f'{etiqueta}: ya no se imparte en ese grado.')
            elif asignacion.profesor_id == (profesor.pk if profesor else None):
                continue   # ya lo tenía: nada que cambiar
            elif profesor and asignacion.grado.nivel not in niveles:
                omitidas.append(f'{etiqueta}: {mensaje_fuera_de_nivel(profesor, asignacion.grado)}')
            elif profesor and (empalmes := conflictos_de_asignacion(profesor, asignacion)):
                omitidas.append(f'{etiqueta}: {mensaje_de_empalme_profesor(profesor, empalmes)}')
            else:
                anterior = asignacion.profesor
                asignacion.profesor = profesor
                asignacion.save(update_fields=['profesor'])
                cambios.append((asignacion, anterior))
    return cambios, omitidas


def mensaje_fuera_de_nivel(profesor, grado):
    """Por qué no se le puede asignar una materia del grado: solo imparte en los niveles de su ficha."""
    return (f'{profesor} no da clases en {grado.get_nivel_display()}. Agrégale ese nivel en su ficha para poder '
            f'asignarle materias de ese nivel.')


def descripcion_del_cambio(asignacion, anterior):
    """«Matemáticas de 1° Secundaria · Ciclo 2026-2027: sin profesor → Marta Rangel» (para la bitácora)."""
    antes = str(anterior) if anterior else 'sin profesor'
    despues = str(asignacion.profesor) if asignacion.profesor_id else 'sin profesor'
    return f'{asignacion.materia} de {asignacion.grado} · Ciclo {asignacion.ciclo}: {antes} → {despues}.'


# ---------------------------------------------------------------------------
# Habilitación
# ---------------------------------------------------------------------------
def habilitar(profesor, materias):
    """Agrega `materias` a las que `profesor` puede impartir. Devuelve las que de verdad eran nuevas."""
    materias = list(materias)
    ya = set(ProfesorMateria.objects.filter(profesor=profesor, materia__in=materias).values_list('materia_id', flat=True))
    nuevas = [materia for materia in materias if materia.pk not in ya]
    ProfesorMateria.objects.bulk_create([ProfesorMateria(profesor=profesor, materia=materia) for materia in nuevas], ignore_conflicts=True)
    return nuevas


def deshabilitar(profesor, materias):
    """Quita `materias` de las que `profesor` puede impartir (no toca lo que ya imparte). Devuelve las que quitó."""
    habilitaciones = ProfesorMateria.objects.filter(profesor=profesor, materia__in=materias).select_related('materia')
    quitadas = [habilitacion.materia for habilitacion in habilitaciones]
    habilitaciones.delete()
    return quitadas


def habilitados_por_materia(materias=None):
    """{id de materia: [ids de profesores activos habilitados]} (de las materias indicadas, o de todas)."""
    consulta = ProfesorMateria.objects.filter(profesor__estatus='ACTIVO')
    if materias is not None:
        consulta = consulta.filter(materia__in=materias)
    resultado = defaultdict(list)
    for materia_id, profesor_id in consulta.order_by().values_list('materia_id', 'profesor_id'):
        resultado[materia_id].append(profesor_id)
    return resultado


def profesores_por_nivel():
    """{nivel: [ids de profesores activos que dan clases en él]}."""
    resultado = defaultdict(list)
    for nivel, profesor_id in ProfesorNivel.objects.filter(profesor__estatus='ACTIVO').order_by().values_list('nivel', 'profesor_id'):
        resultado[nivel].append(profesor_id)
    return resultado


def con_habilitados(asignaciones):
    """Agrega a cada asignación `habilitados` (ids de profesores habilitados para su materia, como «3,8,12»),
    `del_nivel` (ids de quienes dan clases en el nivel de su grado) y `nivel_del_grado` («Primaria»)."""
    asignaciones = list(asignaciones)
    mapa = habilitados_por_materia({a.materia_id for a in asignaciones})
    niveles = dict(Grado.objects.filter(pk__in={a.grado_id for a in asignaciones}).values_list('pk', 'nivel'))
    por_nivel = profesores_por_nivel() if asignaciones else {}
    nombres = dict(Grado.NIVEL_CHOICES)
    for asignacion in asignaciones:
        nivel = niveles.get(asignacion.grado_id)
        asignacion.del_nivel = ','.join(str(pk) for pk in por_nivel.get(nivel, []))
        asignacion.nivel_del_grado = nombres.get(nivel, '')
        asignacion.habilitados = ','.join(str(pk) for pk in mapa.get(asignacion.materia_id, []))
        asignacion.profesor_habilitado = (
            asignacion.profesor_id is None or asignacion.profesor_id in mapa.get(asignacion.materia_id, [])
        )
    return asignaciones


# ---------------------------------------------------------------------------
# Carga de trabajo
# ---------------------------------------------------------------------------
def asignaciones_vigentes(ciclo):
    """Asignaciones del ciclo que de verdad se imparten: activas, de una materia y un grado vigentes."""
    return MateriaGrado.objects.filter(ciclo=ciclo, activa=True, materia__activa=True, grado__activo=True)


def estado_de_carga(minutos, total_materias, maximo_horas):
    """libre, normal, completa o sobrecarga (con tope semanal) y sin_limite (sin tope definido)."""
    if not total_materias and not minutos:
        return 'libre'
    if not maximo_horas:
        return 'sin_limite'
    tope = maximo_horas * 60
    if minutos > tope:
        return 'sobrecarga'
    return 'completa' if minutos == tope else 'normal'


def carga_de_profesores(ciclo, profesores=None):
    """La carga de cada profesor activo (o de los indicados) en el ciclo, en el orden de los profesores.

    Cada elemento: profesor, asignaciones, total_materias, total_grados, minutos, duracion, maximo (horas), porcentaje
    (None sin tope), estado y estado_texto. Las horas salen de los horarios ya armados.
    """
    profesores = list(Profesor.objects.filter(estatus='ACTIVO') if profesores is None else profesores)
    por_profesor = defaultdict(list)
    if ciclo is not None and profesores:
        asignaciones = (
            asignaciones_vigentes(ciclo).filter(profesor__in=profesores)
            .select_related('materia', 'grado').prefetch_related('horarios')
        )
        for asignacion in asignaciones:
            por_profesor[asignacion.profesor_id].append(asignacion)

    cargas = []
    for profesor in profesores:
        asignaciones = sorted(por_profesor[profesor.pk], key=lambda a: (a.grado.nivel, a.grado.numero, a.materia.nombre))
        minutos = sum(minutos_semanales(a.horarios.all()) for a in asignaciones)
        estado = estado_de_carga(minutos, len(asignaciones), profesor.horas_maximas)
        cargas.append({
            'profesor': profesor,
            'asignaciones': asignaciones,
            'total_materias': len(asignaciones),
            'total_grados': len({a.grado_id for a in asignaciones}),
            'minutos': minutos,
            'duracion': formatear_duracion(minutos) if minutos else '',
            'maximo': profesor.horas_maximas,
            'porcentaje': round(minutos * 100 / (profesor.horas_maximas * 60)) if profesor.horas_maximas else None,
            'estado': estado,
            'estado_texto': ESTADOS_DE_CARGA[estado],
        })
    return cargas


def resumen_del_ciclo(ciclo):
    """Números del tablero: materias del plan, con y sin profesor, sin horario (tenga o no profesor) y profesores sin clases."""
    if ciclo is None:
        return {'materias': 0, 'con_profesor': 0, 'sin_profesor': 0, 'sin_horario': 0, 'profesores': 0, 'profesores_libres': 0, 'avance': 0}
    # distinct: el filtro por horarios une esa tabla y, sin él, una materia con varios bloques se contaría varias veces
    totales = asignaciones_vigentes(ciclo).aggregate(
        materias=Count('pk', distinct=True),
        con_profesor=Count('pk', filter=Q(profesor__isnull=False), distinct=True),
        sin_profesor=Count('pk', filter=Q(profesor__isnull=True), distinct=True),
        sin_horario=Count('pk', filter=Q(horarios__isnull=True), distinct=True),
    )
    profesores = Profesor.objects.filter(estatus='ACTIVO').count()
    con_clases = asignaciones_vigentes(ciclo).filter(profesor__estatus='ACTIVO').values('profesor').distinct().count()
    totales.update(
        profesores=profesores,
        profesores_libres=profesores - con_clases,
        avance=round(totales['con_profesor'] * 100 / totales['materias']) if totales['materias'] else 0,
    )
    return totales
