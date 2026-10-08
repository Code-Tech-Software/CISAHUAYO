"""Reglas académicas que comparten las secciones de ciclos, grados e inscripciones.

El colegio maneja un solo grupo por grado: el grado es la unidad (no existen grupos ni secciones).
"""
import re
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Max, Prefetch, Q
from django.utils import timezone

from .models import ORDEN_NIVELES, Alumno, CicloEscolar, Grado, Inscripcion, Materia, MateriaGrado

# Número máximo de grado por nivel (en preparatoria caben semestres o años).
LIMITE_GRADOS = {'PREESCOLAR': 3, 'PRIMARIA': 6, 'SECUNDARIA': 3, 'PREPARATORIA': 6}

# Equivalencia habitual de cada grado en la continuidad escolar, sin importar el nivel: primaria 1.° a 6.°, secundaria
# 7.° a 9.° (1.° de secundaria se nombra «7.°») y preparatoria del 10.° en adelante; preescolar usa un código con letra
# (K1, K2, K3). La equivalencia es un número o un código corto de letras y números. Es solo la propuesta: cada grado
# guarda la suya y se puede cambiar desde el formulario del grado.
BASE_DE_EQUIVALENCIA = {'PRIMARIA': 0, 'SECUNDARIA': 6, 'PREPARATORIA': 9}
PREFIJO_DE_EQUIVALENCIA = {'PREESCOLAR': 'K'}
LARGO_EQUIVALENCIA = 8
FORMATO_EQUIVALENCIA = re.compile(r'^[A-Z0-9]+$')


def equivalencia_sugerida(nivel, numero):
    """La equivalencia habitual de ese grado («7», «K1»), o '' si el nivel no tiene una o falta el número."""
    if not numero:
        return ''
    if nivel in PREFIJO_DE_EQUIVALENCIA:
        return f'{PREFIJO_DE_EQUIVALENCIA[nivel]}{numero}'
    base = BASE_DE_EQUIVALENCIA.get(nivel)
    return '' if base is None else str(base + numero)


def normalizar_equivalencia(valor):
    """Lo que se guarda de lo que se escribió: sin espacios, «°» ni puntos y en mayúsculas («k 1» → «K1», «7°» → «7»)."""
    valor = re.sub(r'[\s°º.]', '', valor or '').upper()
    return str(int(valor)) if valor.isdigit() else valor   # «07» → «7»


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
    """Materias activas del grado (o todavía sin grado) que el grado no imparte (de forma vigente) en el ciclo."""
    vigentes = MateriaGrado.objects.filter(ciclo=ciclo, grado=grado, activa=True).values('materia_id')
    return Materia.objects.filter(Q(grado=grado) | Q(grado__isnull=True), activa=True).exclude(pk__in=vigentes)


def grados_por_asignar(materia, ciclo):
    """Grados activos que todavía no imparten (de forma vigente) la materia en el ciclo, en orden escolar: solo el
    suyo (una materia la imparte un solo grado) o, si todavía no tiene, cualquiera."""
    vigentes = MateriaGrado.objects.filter(ciclo=ciclo, materia=materia, activa=True).values('grado_id')
    grados = Grado.objects.filter(activo=True).exclude(pk__in=vigentes)
    if materia.grado_id:
        grados = grados.filter(pk=materia.grado_id)
    return grados.academicos()


def grados_vigentes_fuera_de(materia, grado):
    """Los grados distintos de `grado` en cuyo plan sigue la materia, en el ciclo actual o en uno próximo (mientras
    siga ahí no se le puede dar otro grado). En orden escolar."""
    vigentes = Q(ciclo__activo=True) | Q(ciclo__fecha_inicio__gt=timezone.localdate())
    en_el_plan = MateriaGrado.objects.filter(vigentes, materia=materia, activa=True).values('grado_id')
    return list(Grado.objects.filter(pk__in=en_el_plan).exclude(pk=grado.pk).academicos())


def asegurar_en_el_plan(materia, ciclo=None):
    """Una materia activa con grado se imparte en su grado: la deja en el plan del ciclo (el actual si no se indica),
    creando la asignación o reactivando la que estaba quitada. Devuelve la asignación, o None si no aplica (sin ciclo
    actual, ciclo cerrado, materia de baja o sin grado, o grado de baja)."""
    ciclo = ciclo if ciclo is not None else ciclo_actual()
    if not ciclo_editable(ciclo) or not materia.activa or not materia.grado_id or not materia.grado.activo:
        return None
    asignacion, _ = MateriaGrado.objects.get_or_create(ciclo=ciclo, grado_id=materia.grado_id, materia=materia)
    if not asignacion.activa:
        asignacion.activa = True
        asignacion.save(update_fields=['activa'])
    return asignacion


def _vigentes_en_otros_grados(materia, grado):
    """Las asignaciones activas de la materia en otro grado, en el ciclo actual o en uno próximo."""
    vigentes = Q(ciclo__activo=True) | Q(ciclo__fecha_inicio__gt=timezone.localdate())
    return MateriaGrado.objects.filter(vigentes, materia=materia, activa=True).exclude(grado=grado)


def motivo_para_no_cambiar_de_grado(materia, grado):
    """Por qué la materia no puede pasar a `grado` ('' si sí puede): en su grado de ahora ya tiene horario o asistencia
    en el ciclo actual o en uno próximo (eso es del grupo de ese grado y no se mueve solo)."""
    con_clases = (
        _vigentes_en_otros_grados(materia, grado)
        .filter(Q(horarios__isnull=False) | Q(asistencias__isnull=False)).select_related('grado', 'ciclo').distinct()
    )
    detalle = ', '.join(sorted({f'{asignacion.grado} ({asignacion.ciclo})' for asignacion in con_clases}))
    if detalle:
        return (f'Ya tiene horario en {detalle}. Quítale ese horario en Horarios antes de cambiarla de grado, o da de baja '
                f'esta materia y registra otra para el grado nuevo.')
    return ''


def pasar_al_grado(materia):
    """Tras elegirle o cambiarle el grado a la materia, mueve su plan del ciclo actual y de los próximos a ese grado.

    Cada asignación vigente en otro grado (sin horario ni asistencia: ver `motivo_para_no_cambiar_de_grado`) pasa al
    grado nuevo; si en ese ciclo ya estaba en él, la otra solo se quita. Su profesor se queda si da clases en el nivel
    del grado nuevo. Al final la materia queda en el plan del ciclo actual. Devuelve los profesores que se quitaron.
    """
    grado = materia.grado
    sin_profesor = []
    with transaction.atomic():
        for asignacion in _vigentes_en_otros_grados(materia, grado).select_related('profesor').order_by('ciclo_id', 'pk'):
            ya_esta = MateriaGrado.objects.filter(ciclo_id=asignacion.ciclo_id, grado=grado, materia=materia).first()
            if ya_esta is not None:
                if not ya_esta.activa:
                    ya_esta.activa = True
                    ya_esta.save(update_fields=['activa'])
                asignacion.activa = False
                asignacion.save(update_fields=['activa'])
                continue
            asignacion.grado = grado
            if asignacion.profesor_id and not asignacion.profesor.niveles.filter(nivel=grado.nivel).exists():
                sin_profesor.append(asignacion.profesor)
                asignacion.profesor = None
            asignacion.save(update_fields=['grado', 'profesor'])
        asegurar_en_el_plan(materia)
    return sin_profesor


def motivo_para_no_agregar(materia, grado):
    """Por qué la materia no se puede agregar al plan de `grado` ('' si sí se puede): una materia la imparte un solo
    grado. Una materia que todavía no tiene grado toma el primero al que se agrega."""
    if materia.grado_id:
        if materia.grado_id != grado.pk:
            return f'{materia} es de {materia.grado}: solo se agrega al plan de ese grado.'
        return ''
    otros = grados_vigentes_fuera_de(materia, grado)
    if otros:
        nombres = ', '.join(str(otro) for otro in otros)
        return f'{materia} todavía se imparte en {nombres}: una materia la imparte un solo grado. Quítala de ahí primero.'
    return ''


def prefetch_inscripciones_actuales(desde=''):
    """Inscripciones activas del ciclo actual, en `alumno.inscripciones_actuales` (solo para los alumnos de la página).

    `desde` es la ruta hasta el alumno cuando se parte de otro modelo (por ejemplo 'alumno__' desde un vínculo).
    """
    return Prefetch(
        f'{desde}inscripciones',
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

    `grados` es la lista de grados disponibles. Si la equivalencia del grado es un número y existe el que sigue en la
    continuidad escolar (equivalencia + 1), ese es el siguiente, aunque cambie de nivel (6.° de primaria → 7.°, 1.° de
    secundaria). Los códigos con letras (K1) no se pueden contar: ahí y si no existe el que sigue, es el siguiente número
    del mismo nivel o, al terminar el nivel, el primer grado del siguiente nivel que exista. None si ya no hay un grado
    que siga.
    """
    if grado.equivalencia_numero is not None:
        por_equivalencia = [g for g in grados if g.equivalencia_numero == grado.equivalencia_numero + 1]
        if por_equivalencia:
            return por_equivalencia[0]
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


def inscripciones_vigentes(alumno):
    """Sus inscripciones del ciclo actual y de los próximos (las de ciclos ya cerrados son historia y no se tocan)."""
    return Inscripcion.objects.filter(alumno=alumno).filter(Q(ciclo__activo=True) | Q(ciclo__fecha_inicio__gt=timezone.localdate()))


def suspender_inscripciones(alumno):
    """Al dar de baja al alumno: sus inscripciones vigentes dejan de estar activas (con la marca para restaurarlas).

    Devuelve las que se desactivaron.
    """
    inscripciones = list(inscripciones_vigentes(alumno).filter(activa=True).select_related('grado', 'ciclo'))
    Inscripcion.objects.filter(pk__in=[i.pk for i in inscripciones]).update(activa=False, suspendida_por_baja=True)
    return inscripciones


def restaurar_inscripciones(alumno):
    """Al reactivar al alumno: vuelven a estar activas las inscripciones vigentes que se desactivaron por su baja.

    Las de un ciclo que ya cerró se quedan como estaban (solo pierden la marca). Devuelve las que se reactivaron.
    """
    inscripciones = list(inscripciones_vigentes(alumno).filter(activa=False, suspendida_por_baja=True).select_related('grado', 'ciclo'))
    Inscripcion.objects.filter(pk__in=[i.pk for i in inscripciones]).update(activa=True, suspendida_por_baja=False)
    Inscripcion.objects.filter(alumno=alumno, suspendida_por_baja=True).update(suspendida_por_baja=False)
    return inscripciones


def sincronizar_inscripciones(alumno, estatus_anterior):
    """Tras cambiar el estatus del alumno (por la acción de baja o reactivar, o desde su edición): pasar a «Baja» suspende
    sus inscripciones vigentes y salir de «Baja» las restaura. Devuelve (suspendidas, restauradas)."""
    if alumno.estatus == 'BAJA' and estatus_anterior != 'BAJA':
        return suspender_inscripciones(alumno), []
    if estatus_anterior == 'BAJA' and alumno.estatus != 'BAJA':
        return [], restaurar_inscripciones(alumno)
    return [], []


def motivo_no_inscribible(alumno):
    """Texto que explica por qué no se puede inscribir al alumno; None si sí se puede."""
    if alumno.estatus == 'BAJA':
        return f'{alumno} está dado de baja. Reactívalo antes de inscribirlo.'
    if alumno.estatus == 'EGRESADO':
        return f'{alumno} figura como egresado. Cambia su estatus antes de inscribirlo.'
    return None
