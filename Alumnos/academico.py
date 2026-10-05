"""Reglas académicas que comparten las secciones de ciclos, grados e inscripciones.

El colegio maneja un solo grupo por grado: el grado es la unidad (no existen grupos ni secciones).
"""
import re
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Max, Prefetch
from django.utils import timezone

from .models import ORDEN_NIVELES, Alumno, CicloEscolar, Grado, Inscripcion, Materia, MateriaGrado

# Número máximo de grado por nivel (en preparatoria caben semestres o años).
LIMITE_GRADOS = {'PREESCOLAR': 3, 'PRIMARIA': 6, 'SECUNDARIA': 3, 'PREPARATORIA': 6}

# Un ciclo dura, normalmente, de finales de agosto a mediados de julio.
INICIO_TIPICO = (8, 24)
FIN_TIPICO = (7, 10)

_NOMBRE_DE_CICLO = re.compile(r'^\s*(\d{4})\s*-\s*(\d{4})\s*$')


def ciclo_actual():
    """El ciclo marcado como actual (si por error hubiera varios, el más reciente)."""
    return CicloEscolar.objects.filter(activo=True).order_by('-fecha_inicio').first()


def elegir_ciclo(pedido, ciclos):
    """Ciclo que se consulta: el pedido (id en texto), si no el actual y, si no hay, el más reciente.

    `ciclos` es la lista de todos los ciclos, del más reciente al más antiguo.
    """
    if str(pedido).isdigit():
        elegido = next((ciclo for ciclo in ciclos if ciclo.pk == int(pedido)), None)
        if elegido:
            return elegido
    return next((ciclo for ciclo in ciclos if ciclo.activo), ciclos[0] if ciclos else None)


def ciclo_editable(ciclo):
    """El plan de materias y los horarios solo se cambian en el ciclo actual o en uno próximo."""
    return ciclo is not None and ciclo.estado != 'CERRADO'


def materias_por_asignar(grado, ciclo):
    """Materias activas que el grado todavía no imparte (de forma vigente) en el ciclo."""
    vigentes = MateriaGrado.objects.filter(ciclo=ciclo, grado=grado, activa=True).values('materia_id')
    return Materia.objects.filter(activa=True).exclude(pk__in=vigentes)


def grados_por_asignar(materia, ciclo):
    """Grados activos que todavía no imparten (de forma vigente) la materia en el ciclo, en orden escolar."""
    vigentes = MateriaGrado.objects.filter(ciclo=ciclo, materia=materia, activa=True).values('grado_id')
    return Grado.objects.filter(activo=True).exclude(pk__in=vigentes).academicos()


def prefetch_inscripciones_actuales():
    """Inscripciones activas del ciclo actual, en `alumno.inscripciones_actuales` (solo para los alumnos de la página)."""
    return Prefetch(
        'inscripciones',
        queryset=(
            Inscripcion.objects.filter(activa=True, ciclo__activo=True)
            .select_related('grado', 'ciclo')
            .order_by('-ciclo__fecha_inicio')
        ),
        to_attr='inscripciones_actuales',
    )


def alumnos_sin_inscribir(ciclo):
    """Alumnos activos que todavía no tienen inscripción (de ningún tipo) en el ciclo."""
    return Alumno.objects.filter(estatus='ACTIVO').exclude(inscripciones__ciclo=ciclo)


def activar_ciclo(ciclo):
    """Marca el ciclo como actual y quita la marca a los demás: solo hay un ciclo actual."""
    with transaction.atomic():
        CicloEscolar.objects.filter(activo=True).exclude(pk=ciclo.pk).update(activo=False)
        if not ciclo.activo:
            ciclo.activo = True
            ciclo.save(update_fields=['activo'])


def _un_anio_despues(fecha):
    try:
        return fecha.replace(year=fecha.year + 1)
    except ValueError:  # 29 de febrero
        return fecha.replace(year=fecha.year + 1, day=28)


def sugerir_ciclo():
    """Nombre y fechas propuestos para el siguiente ciclo (el que sigue al más reciente)."""
    ultimo = CicloEscolar.objects.order_by('-fecha_inicio').first()
    existentes = set(CicloEscolar.objects.values_list('nombre', flat=True))

    if ultimo is None:
        hoy = timezone.localdate()
        anio = hoy.year if hoy.month >= 6 else hoy.year - 1
    else:
        coincidencia = _NOMBRE_DE_CICLO.match(ultimo.nombre)
        anio = int(coincidencia[1]) + 1 if coincidencia else ultimo.fecha_inicio.year + 1

    inicio, fin = date(anio, *INICIO_TIPICO), date(anio + 1, *FIN_TIPICO)
    if ultimo is not None and ultimo.duracion_dias >= 150:  # un ciclo normal: se repite su calendario
        inicio, fin = _un_anio_despues(ultimo.fecha_inicio), _un_anio_despues(ultimo.fecha_fin)

    # Los ciclos no se empalman: si la propuesta cae dentro de uno que ya existe (por ejemplo, uno muy largo),
    # empieza el día siguiente a que termine el último y dura como mucho un año.
    ultimo_dia = CicloEscolar.objects.aggregate(ultimo=Max('fecha_fin'))['ultimo']
    if ultimo_dia is not None and inicio <= ultimo_dia:
        duracion = min(fin - inicio, timedelta(days=364))
        inicio = ultimo_dia + timedelta(days=1)
        fin = inicio + duracion

    nombre = f'{anio}-{anio + 1}'
    while nombre in existentes:
        anio += 1
        nombre = f'{anio}-{anio + 1}'
    return {'nombre': nombre, 'fecha_inicio': inicio, 'fecha_fin': fin}


def siguiente_grado(grado, grados):
    """Grado al que pasa normalmente quien cursa `grado`.

    `grados` es la lista de grados disponibles. Es el siguiente número del mismo nivel o, al terminar el
    nivel, el primer grado del siguiente nivel que exista. None si ya no hay un grado que siga.
    """
    mismo_nivel = [g for g in grados if g.nivel == grado.nivel and g.numero > grado.numero]
    if mismo_nivel:
        return min(mismo_nivel, key=lambda g: g.numero)
    if grado.nivel not in ORDEN_NIVELES:
        return None
    for nivel in ORDEN_NIVELES[ORDEN_NIVELES.index(grado.nivel) + 1:]:
        del_nivel = [g for g in grados if g.nivel == nivel]
        if del_nivel:
            return min(del_nivel, key=lambda g: g.numero)
    return None


def motivo_no_inscribible(alumno):
    """Texto que explica por qué no se puede inscribir al alumno; None si sí se puede."""
    if alumno.estatus == 'BAJA':
        return f'{alumno} está dado de baja. Reactívalo antes de inscribirlo.'
    if alumno.estatus == 'EGRESADO':
        return f'{alumno} figura como egresado. Cambia su estatus antes de inscribirlo.'
    return None
