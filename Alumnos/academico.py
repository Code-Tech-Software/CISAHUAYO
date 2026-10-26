"""Reglas académicas que comparten las secciones de ciclos, grados e inscripciones.

Cada grado tiene uno o varios grupos (1.º A, 1.º B). El plan de materias es del grado y lo comparten sus grupos: una
materia del grado tiene una asignación (`MateriaGrado`) por grupo, con su profesor, su horario y su asistencia. Los
estudiantes se inscriben en un grupo.
"""
import re
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Count, Max, Prefetch, Q
from django.utils import timezone

from .models import ORDEN_NIVELES, Alumno, CicloEscolar, Grado, Grupo, Inscripcion, Materia, MateriaGrado, q_ciclo

# Número máximo de grado por nivel (en preparatoria caben semestres o años).
LIMITE_GRADOS = {'PREESCOLAR': 3, 'PRIMARIA': 6, 'SECUNDARIA': 3, 'PREPARATORIA': 6}

# Equivalencia habitual de cada grado en la continuidad escolar, sin importar el nivel: primaria 1.º a 6.º, secundaria
# 7.º a 9.º (1.º de secundaria se nombra «7.º») y preparatoria del 10.º en adelante; preescolar usa un código con letra
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
    """Lo que se guarda de lo que se escribió: sin espacios, «°» ni puntos y en mayúsculas («k 1» → «K1», «7.º» → «7»)."""
    valor = re.sub(r'[\s°º.]', '', valor or '').upper()
    return str(int(valor)) if valor.isdigit() else valor   # «07» → «7»


# Un ciclo dura, normalmente, de finales de agosto a mediados de julio.
INICIO_TIPICO = (8, 24)
FIN_TIPICO = (7, 10)

_NOMBRE_DE_CICLO = re.compile(r'^\s*(\d{4})\s*-\s*(\d{4})\s*$')


def ciclo_actual():
    """El ciclo marcado como actual (la base no permite más de uno)."""
    return CicloEscolar.objects.actuales().first()


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
    vigentes = q_ciclo('VIGENTE', 'ciclo__')
    en_el_plan = MateriaGrado.objects.filter(vigentes, materia=materia, activa=True).values('grado_id')
    return list(Grado.objects.filter(pk__in=en_el_plan).exclude(pk=grado.pk).academicos())


def grupos_del_grado(grado):
    """Los grupos activos del grado, en orden (A, B…). Si todavía no tiene ninguno, se le crea el primero."""
    grupos = list(grado.grupos.filter(activo=True).select_related('nombre', 'grado').order_by('nombre__orden', 'nombre__nombre'))
    return grupos or [Grupo.principal_de(grado)]


def agregar_al_plan(materia, grado, ciclo):
    """Deja la materia en el plan del grado en el ciclo: una asignación por cada grupo activo del grado (crea las que
    faltan y reactiva las quitadas). Devuelve (asignaciones, cuántas eran nuevas o reactivadas)."""
    asignaciones, cambios = [], 0
    for grupo in grupos_del_grado(grado):
        asignacion, creada = MateriaGrado.objects.get_or_create(
            ciclo=ciclo, grupo=grupo, materia=materia, defaults={'grado': grado},
        )
        if creada:
            cambios += 1
        elif not asignacion.activa:
            asignacion.activa = True
            asignacion.save(update_fields=['activa'])
            cambios += 1
        asignaciones.append(asignacion)
    return asignaciones, cambios


def asegurar_en_el_plan(materia, ciclo=None):
    """Una materia activa con grado se imparte en su grado: la deja en el plan del ciclo (el actual si no se indica)
    en cada grupo del grado. Devuelve sus asignaciones (una por grupo), o [] si no aplica (sin ciclo actual, ciclo
    cerrado, materia de baja o sin grado, o grado de baja)."""
    ciclo = ciclo if ciclo is not None else ciclo_actual()
    if not ciclo_editable(ciclo) or not materia.activa or not materia.grado_id or not materia.grado.activo:
        return []
    return agregar_al_plan(materia, materia.grado, ciclo)[0]


def suspender_plan(grupos):
    """Al quitar grupos (o dar de baja su grado): sus materias del ciclo actual y de los próximos dejan de impartirse,
    con la marca para restaurarlas (conservan profesor y horario). Así no siguen contando en la carga de los
    profesores ni en los horarios. Devuelve cuántas se suspendieron."""
    return MateriaGrado.objects.filter(q_ciclo('VIGENTE', 'ciclo__'), grupo__in=grupos, activa=True).update(
        activa=False, suspendida=True,
    )


def extender_plan_al_grupo(grupo):
    """Un grupo nuevo (o reactivado) toma el plan de su grado en el ciclo actual y en los próximos: primero vuelven
    sus materias suspendidas al quitarlo (con su profesor y su horario); después, cada materia que el grado imparte
    ahí y el grupo no tiene queda en el grupo, todavía sin profesor ni horario. Devuelve cuántas agregó o volvieron."""
    vigentes = q_ciclo('VIGENTE', 'ciclo__')
    restauradas = MateriaGrado.objects.filter(vigentes, grupo=grupo, suspendida=True, materia__activa=True).update(
        activa=True, suspendida=False,
    )
    MateriaGrado.objects.filter(grupo=grupo, suspendida=True).update(suspendida=False)   # las de ciclos ya cerrados
    plan = set(
        MateriaGrado.objects.filter(vigentes, grado=grupo.grado, activa=True, materia__activa=True)
        .values_list('ciclo_id', 'materia_id')
    )
    agregadas = 0
    for ciclo_id, materia_id in sorted(plan):
        _, creada = MateriaGrado.objects.get_or_create(
            ciclo_id=ciclo_id, grupo=grupo, materia_id=materia_id, defaults={'grado_id': grupo.grado_id},
        )
        agregadas += creada
    return agregadas + restauradas


def inscritos_vigentes(grado):
    """Estudiantes con inscripción activa en el grado, en el ciclo actual o en uno próximo."""
    return Inscripcion.objects.filter(q_ciclo('VIGENTE', 'ciclo__'), grado=grado, activa=True).count()


def inscritos_vigentes_por_grado():
    """{id de grado: estudiantes con inscripción activa en el ciclo actual o en uno próximo} (una sola consulta)."""
    return dict(
        Inscripcion.objects.filter(q_ciclo('VIGENTE', 'ciclo__'), activa=True).order_by()
        .values_list('grado_id').annotate(total=Count('pk'))
    )


def motivo_para_no_dar_de_baja(grado, inscritos=None):
    """Por qué el grado no se puede dar de baja ('' si sí): tiene estudiantes inscritos en el ciclo actual o en uno
    próximo (sus grupos dejarían de verse en Horarios, Prefectura y Grupos mientras siguen tomando clase).
    `inscritos`, si ya se contaron (`inscritos_vigentes_por_grado`)."""
    inscritos = inscritos_vigentes(grado) if inscritos is None else inscritos
    if not inscritos:
        return ''
    return (
        f'Tiene {inscritos} estudiante{"s" if inscritos != 1 else ""} inscrito{"s" if inscritos != 1 else ""} en el ciclo '
        'actual o en uno próximo. Cámbialos de grado o dalo de baja cuando el ciclo termine y ya no tenga inscritos.'
    )


def _vigentes_en_otros_grados(materia, grado):
    """Las asignaciones activas de la materia en otro grado, en el ciclo actual o en uno próximo."""
    vigentes = q_ciclo('VIGENTE', 'ciclo__')
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
    grupo del grado nuevo que se llama igual (o al primero); si en ese ciclo ya estaba en él, la otra solo se quita. Su
    profesor se queda si da clases en el nivel del grado nuevo. Al final la materia queda en el plan del ciclo actual
    en todos los grupos del grado. Devuelve los profesores que se quitaron.
    """
    grado = materia.grado
    grupos = grupos_del_grado(grado)
    por_nombre = {grupo.nombre_id: grupo for grupo in grupos}
    sin_profesor = []
    with transaction.atomic():
        for asignacion in _vigentes_en_otros_grados(materia, grado).select_related('profesor', 'grupo').order_by('ciclo_id', 'pk'):
            destino = por_nombre.get(asignacion.grupo.nombre_id, grupos[0])
            ya_esta = MateriaGrado.objects.filter(ciclo_id=asignacion.ciclo_id, grupo=destino, materia=materia).first()
            if ya_esta is not None:
                if not ya_esta.activa:
                    ya_esta.activa = True
                    ya_esta.save(update_fields=['activa'])
                asignacion.activa = False
                asignacion.save(update_fields=['activa'])
                continue
            asignacion.grado, asignacion.grupo = grado, destino
            if asignacion.profesor_id and not asignacion.profesor.niveles.filter(nivel=grado.nivel).exists():
                sin_profesor.append(asignacion.profesor)
                asignacion.profesor = None
            asignacion.save(update_fields=['grado', 'grupo', 'profesor'])
        asegurar_en_el_plan(materia)
    return list(dict.fromkeys(sin_profesor))


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
            .select_related('grado', 'grupo__nombre', 'grupo__grado', 'ciclo')
            .order_by('-ciclo__fecha_inicio')
        ),
        to_attr='inscripciones_actuales',
    )


def alumnos_sin_inscribir(ciclo):
    """Alumnos activos que todavía no tienen inscripción (de ningún tipo) en el ciclo."""
    return Alumno.objects.filter(estatus='ACTIVO').exclude(inscripciones__ciclo=ciclo)


def _anotar(usuario, ciclo, mensaje):
    """Lo deja en la bitácora de cambios (si lo hizo una persona)."""
    if usuario is not None and usuario.pk:
        from Usuarios.seguridad import ACCION_CAMBIO, registrar
        registrar(usuario, ciclo, ACCION_CAMBIO, mensaje)


def _quitar_marca(ciclo, usuario, ahora, cerrar):
    """El ciclo deja de ser el actual. Si `cerrar`, queda cerrado (con quién y cuándo); si no, vuelve a próximo."""
    ciclo.activo = False
    ciclo.cerrado_en, ciclo.cerrado_por = (ahora, usuario) if cerrar else (None, None)
    ciclo.save(update_fields=['activo', 'cerrado_en', 'cerrado_por'])


def activar_ciclo(ciclo, usuario=None):
    """Marca el ciclo como actual (con quién y cuándo) y quita la marca al que lo era: solo hay un ciclo actual.

    El que era actual queda cerrado si ya había empezado; si todavía no empezaba (se marcó por adelantado), vuelve a
    próximo. Devuelve el ciclo que era actual (o None).
    """
    ahora, hoy = timezone.now(), timezone.localdate()
    usuario = usuario if usuario is not None and usuario.pk else None
    with transaction.atomic():
        anterior = CicloEscolar.objects.select_for_update().filter(activo=True).exclude(pk=ciclo.pk).first()
        if anterior is not None:
            cerrar = anterior.fecha_inicio <= hoy
            _quitar_marca(anterior, usuario, ahora, cerrar)
            _anotar(usuario, anterior, f'Dejó de ser el ciclo actual al marcar {ciclo} como actual'
                                       f'{" (quedó cerrado)" if cerrar else " (vuelve a próximo)"}.')
        if not ciclo.activo:
            reabierto = ciclo.cerrado_en is not None
            ciclo.activo, ciclo.activado_en, ciclo.activado_por = True, ahora, usuario
            ciclo.cerrado_en = ciclo.cerrado_por = None
            ciclo.save(update_fields=['activo', 'activado_en', 'activado_por', 'cerrado_en', 'cerrado_por'])
            _anotar(usuario, ciclo, 'Lo marcó como ciclo actual (estaba cerrado).' if reabierto else 'Lo marcó como ciclo actual.')
    return anterior


def cerrar_ciclo(ciclo, usuario=None):
    """El ciclo deja de ser el actual y queda cerrado (con quién y cuándo). Es lógico: conserva sus inscripciones y su
    historial, y se puede volver a marcar como actual."""
    with transaction.atomic():
        _quitar_marca(ciclo, usuario if usuario is not None and usuario.pk else None, timezone.now(), cerrar=True)
        _anotar(usuario, ciclo, 'Cerró el ciclo.')


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
    continuidad escolar (equivalencia + 1), ese es el siguiente, aunque cambie de nivel (6.º de primaria → 7.º, 1.º de
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
    return Inscripcion.objects.filter(alumno=alumno).filter(q_ciclo('VIGENTE', 'ciclo__'))


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
