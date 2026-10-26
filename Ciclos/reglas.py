"""Reglas de la sección Ciclos escolares (2026-10-26).

- `avisos_de_datos`: el nombre no coincide con los años de las fechas o la duración es rara (se avisa, no se bloquea).
- `fuera_del_rango`: lo que ya depende del ciclo y quedaría fuera de unas fechas nuevas (al editarlas se rechaza).
- `ligado`: lo que impide borrar un ciclo (solo se borra uno creado por error, sin nada ligado).
- `pendientes_de_cierre`, `avisos_al_activar`: lo que se avisa en las ventanas de cerrar y de establecer como actual.
- `aviso_del_cambio_de_ciclo`: el aviso del Panel de control (sin ciclo actual, o el actual fuera de sus fechas).

El estado del ciclo (actual, próximo, cerrado) está en un solo lugar: `Alumnos.models.q_ciclo`.
"""
import re
from dataclasses import dataclass

from django.db.models import Max, Min, Q
from django.urls import reverse
from django.utils import timezone

from Alumnos.academico import alumnos_sin_inscribir, ciclo_actual
from Alumnos.models import (
    AsistenciaGeneral, AsistenciaMateria, CicloEscolar, ConfiguracionHorario, DiaNoLectivo, Inscripcion, Justificacion,
    Periodo,
)

DURACION_MINIMA, DURACION_MAXIMA = 150, 400   # días; fuera de eso, la duración es rara
_AÑOS = re.compile(r'(\d{4})\D+(\d{4})')


def _plural(cantidad, singular, plural=None):
    return f'{cantidad} {singular if cantidad == 1 else (plural or singular + "s")}'


def _rango(desde, hasta):
    return f'el {desde:%d/%m/%Y}' if desde == hasta else f'del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}'


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
def avisos_de_datos(nombre, inicio, fin):
    """Lo que conviene revisar antes de guardar: el nombre no coincide con los años de las fechas («2026-2027» con
    fechas de 2027) o la duración es rara (menos de 150 días o más de 400)."""
    avisos = []
    años = _AÑOS.search(nombre or '')
    if años and inicio and fin and (int(años[1]), int(años[2])) != (inicio.year, fin.year):
        avisos.append(
            f'El nombre «{nombre}» no coincide con los años de las fechas ({inicio.year} a {fin.year}).'
        )
    if inicio and fin and inicio < fin:
        dias = (fin - inicio).days + 1
        if dias < DURACION_MINIMA:
            avisos.append(f'Dura {dias} días: un ciclo escolar suele durar unos 11 meses.')
        elif dias > DURACION_MAXIMA:
            avisos.append(f'Dura {dias} días: más de un año. Revisa las fechas.')
    return avisos


def fuera_del_rango(ciclo, inicio, fin):
    """Lo que ya depende del ciclo y quedaría fuera de las fechas nuevas: textos para el error («2 periodos de
    evaluación (Bimestre 1 · Primaria, …)»). Vacío si todo cabe.

    Las inscripciones solo cuentan si son posteriores al fin (es normal inscribir antes de que empiece el ciclo).
    """
    if ciclo.pk is None or not (inicio and fin):
        return []
    fuera = Q(fecha__lt=inicio) | Q(fecha__gt=fin)
    textos = []

    periodos = list(
        Periodo.objects.filter(ciclo=ciclo).filter(Q(fecha_inicio__lt=inicio) | Q(fecha_fin__gt=fin))
        .order_by('fecha_inicio')
    )
    if periodos:
        nombres = ', '.join(f'{p.nombre} · {p.get_nivel_display()}' for p in periodos[:3])
        textos.append(f'{_plural(len(periodos), "periodo")} de evaluación ({nombres}{", …" if len(periodos) > 3 else ""})')

    def por_fechas(consulta, singular, plural=None):
        datos = consulta.aggregate(desde=Min('fecha'), hasta=Max('fecha'))
        if datos['desde'] is not None:
            textos.append(f'{_plural(consulta.count(), singular, plural)} ({_rango(datos["desde"], datos["hasta"])})')

    por_fechas(AsistenciaGeneral.objects.filter(fuera, inscripcion__ciclo=ciclo), 'registro de entrada', 'registros de entrada')
    por_fechas(AsistenciaMateria.objects.filter(fuera, inscripcion__ciclo=ciclo), 'registro de asistencia por materia',
               'registros de asistencia por materia')
    por_fechas(Justificacion.objects.filter(fuera, inscripcion__ciclo=ciclo, activa=True), 'justificación', 'justificaciones')
    por_fechas(ciclo.conductas.filter(fuera), 'registro de conducta', 'registros de conducta')
    por_fechas(ciclo.bitacoras.filter(fuera), 'entrada de bitácora', 'entradas de bitácora')
    dias = DiaNoLectivo.objects.filter(fecha__range=(ciclo.fecha_inicio, ciclo.fecha_fin)).filter(fuera)
    fechas = sorted(set(dias.values_list('fecha', flat=True)))
    if fechas:
        textos.append(f'{_plural(len(fechas), "día sin clases", "días sin clases")} ({_rango(fechas[0], fechas[-1])})')
    tardias = Inscripcion.objects.filter(ciclo=ciclo, fecha_inscripcion__gt=fin)
    if tardias.exists():
        ultima = tardias.aggregate(ultima=Max('fecha_inscripcion'))['ultima']
        textos.append(f'{_plural(tardias.count(), "inscripción", "inscripciones")} posteriores al fin (la última, el {ultima:%d/%m/%Y})')
    referencias = ConfiguracionHorario.objects.filter(ciclo=ciclo, fecha_referencia__isnull=False).filter(
        Q(fecha_referencia__lt=inicio) | Q(fecha_referencia__gt=fin)
    )
    if referencias.exists():
        textos.append('la fecha de referencia de las semanas A y B')
    return textos


# ---------------------------------------------------------------------------
# Borrar un ciclo creado por error
# ---------------------------------------------------------------------------
def ligado(ciclo):
    """Lo que impide borrar el ciclo (textos); vacío si no tiene nada ligado. El ciclo actual nunca se borra."""
    textos = []
    if ciclo.activo:
        textos.append('es el ciclo actual')
    for consulta, singular, plural in (
        (ciclo.inscripciones.all(), 'inscripción', 'inscripciones'),
        (ciclo.materias_grado.all(), 'materia en el plan', 'materias en el plan'),
        (ciclo.recreos.all(), 'receso', 'recesos'),
        (ciclo.periodos.all(), 'periodo de evaluación', 'periodos de evaluación'),
        (ciclo.configuraciones_evaluacion.all(), 'configuración de calificaciones', 'configuraciones de calificaciones'),
        (ciclo.configuraciones_horario.all(), 'configuración de semanas A y B', 'configuraciones de semanas A y B'),
        (ciclo.conductas.all(), 'registro de conducta', 'registros de conducta'),
        (ciclo.bitacoras.all(), 'entrada de bitácora', 'entradas de bitácora'),
    ):
        cantidad = consulta.count()
        if cantidad:
            textos.append(_plural(cantidad, singular, plural))
    dias = DiaNoLectivo.objects.filter(fecha__range=(ciclo.fecha_inicio, ciclo.fecha_fin)).values('fecha').distinct().count()
    if dias:
        textos.append(_plural(dias, 'día sin clases', 'días sin clases'))
    return textos


# ---------------------------------------------------------------------------
# Establecer como actual y cerrar
# ---------------------------------------------------------------------------
def avisos_al_activar(ciclo):
    """Lo que la ventana de «Establecer como actual» avisa antes de confirmar."""
    hoy = timezone.localdate()
    return {
        'sin_inscribir': alumnos_sin_inscribir(ciclo).count(),
        'fuera_de_fechas': not (ciclo.fecha_inicio <= hoy <= ciclo.fecha_fin),
        'todavia_no_empieza': hoy < ciclo.fecha_inicio,
        'ya_termino': hoy > ciclo.fecha_fin,
        'reabre': ciclo.cerrado_en is not None,
    }


@dataclass
class Pendiente:
    texto: str
    cantidad: int
    url: str = ''


def pendientes_de_cierre(ciclo, usuario):
    """Lo que conviene resolver antes de cerrar el ciclo (solo se avisa, no bloquea), con su acceso si la cuenta puede
    entrar ahí. Vacío si no hay nada o si el ciclo no es el actual."""
    if not ciclo.activo:
        return []
    from Alumnos.asistencias import dias_pendientes_de_cierre
    from Calificaciones.models import ActaCalificaciones
    from Calificaciones.reglas import ve_todas
    from Conducta.models import RegistroConducta
    from Conducta.permisos import VER
    from Conducta.reglas import solicitudes_pendientes

    hoy = timezone.localdate()
    pendientes = []

    def agregar(texto, cantidad, url='', permiso=True):
        if cantidad:
            pendientes.append(Pendiente(texto, cantidad, url if permiso else ''))

    agregar('Periodos de evaluación abiertos', Periodo.objects.filter(ciclo=ciclo).abiertos(hoy).count(),
            f"{reverse('periodos:lista')}?ciclo={ciclo.pk}", usuario.has_perm('Alumnos.view_periodo'))
    agregar('Actas de calificaciones sin cerrar',
            ActaCalificaciones.objects.filter(periodo__ciclo=ciclo, estado=ActaCalificaciones.EN_CAPTURA).count(),
            reverse('calificaciones:inicio'), ve_todas(usuario))
    agregar('Días de asistencia sin cerrar', len(dias_pendientes_de_cierre(hoy)), reverse('asistencias:inicio'),
            usuario.has_perm('Alumnos.view_asistenciageneral'))
    registros = RegistroConducta.objects.filter(ciclo=ciclo, anulado=False)
    solicitudes = solicitudes_pendientes(registros)
    agregar('Suspensiones o medidas por aprobar', len(solicitudes['suspensiones']) + len(solicitudes['medidas']),
            reverse('conducta:solicitudes'), usuario.has_perm(VER))
    agregar('Casos de conducta con revisión vencida',
            registros.exclude(estado=RegistroConducta.CERRADO).filter(fecha_revision__lt=hoy).count(),
            f"{reverse('conducta:lista')}?estado=vencidos&ciclo={ciclo.pk}", usuario.has_perm(VER))
    return pendientes


# ---------------------------------------------------------------------------
# Panel de control
# ---------------------------------------------------------------------------
def aviso_del_cambio_de_ciclo(usuario):
    """El aviso del cambio de ciclo para el Panel de control, solo para quien puede editar ciclos: no hay ciclo actual,
    o hoy queda fuera de las fechas del actual (y, si ya empezó uno que nadie ha marcado, cuál). None si todo está bien."""
    if not usuario.has_perm('Alumnos.change_cicloescolar'):
        return None
    actual = ciclo_actual()
    if actual is not None and not actual.fuera_de_fechas:
        return None
    hoy = timezone.localdate()
    por_activar = CicloEscolar.objects.proximos().filter(fecha_inicio__lte=hoy).order_by('fecha_inicio').first()
    if actual is None:
        if not CicloEscolar.objects.exists():
            return None
        titulo = 'No hay un ciclo escolar actual.'
        texto = 'No se puede inscribir ni tomar asistencia hasta que marques uno.'
    else:
        titulo = f'Hoy queda fuera de las fechas del ciclo actual ({actual}).'
        texto = 'Revisa sus fechas o marca el ciclo que sigue como actual.'
    if por_activar is not None:
        texto = f'El ciclo {por_activar} empezó el {por_activar.fecha_inicio:%d/%m/%Y} y todavía no se marca como actual.'
    destino = por_activar or actual
    return {
        'titulo': titulo,
        'texto': texto,
        'url': destino.get_absolute_url() if destino else reverse('ciclos:lista'),
        'boton': f'Ver el ciclo {destino}' if destino else 'Ver los ciclos',
    }
