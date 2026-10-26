"""Vista 360 del docente (pedido del 2026-10-23): lo que el profesor tiene pendiente o reciente en otros módulos, junto
en su perfil y en su expediente imprimible. Solo consulta: no crea registros ni repite reglas de captura.

- **Asistencias por capturar**: por cada materia suya del ciclo, los días con clase (según su horario) del periodo
  abierto de su nivel, hasta hoy, que todavía no tienen ningún registro de asistencia; sin contar los días sin clases.
- **Calificaciones por cerrar**: las actas de sus materias en periodos abiertos o ya terminados que siguen en captura
  (o que no se han empezado).
- **Bitácoras**: las entradas que escribió con su cuenta en el ciclo (las anuladas no cuentan); las más recientes.
- **Reuniones**: las abiertas en que es responsable (próximas primero) y las de los últimos 30 días.
Sin cuenta de acceso no hay bitácoras ni reuniones suyas: se dice así en vez de mostrar ceros.
"""
from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

from Alumnos.asistencias import fechas_sin_clases
from Alumnos.models import AsistenciaMateria, HorarioMateria, MateriaGrado, Periodo
from Alumnos.semanas import Calendario

RECIENTES = 5


def _asignaciones(profesor, ciclo):
    if ciclo is None:
        return []
    return list(
        MateriaGrado.objects.filter(profesor=profesor, ciclo=ciclo, activa=True)
        .select_related('materia', 'grado', 'grupo__nombre', 'grupo__grado').prefetch_related('horarios')
        .order_by('grado__nivel', 'grado__numero', 'materia__nombre')
    )


def asistencias_por_capturar(asignaciones, hoy=None):
    """Consultas fijas: los periodos abiertos, los días sin clases de cada nivel y las fechas ya capturadas."""
    hoy = hoy or timezone.localdate()
    if not asignaciones:
        return []
    niveles = {a.grado.nivel for a in asignaciones}
    periodos = {}
    for periodo in Periodo.objects.abiertos(hoy).filter(ciclo=asignaciones[0].ciclo_id, nivel__in=niveles).order_by('-fecha_inicio'):
        periodos[periodo.nivel] = periodo   # el más antiguo queda al final, como en periodo_abierto()
    if not periodos:
        return []
    desde = min(p.fecha_inicio for p in periodos.values())
    sin_clases = {nivel: fechas_sin_clases(p.fecha_inicio, min(hoy, p.fecha_fin), nivel)
                  | fechas_sin_clases(p.fecha_inicio, min(hoy, p.fecha_fin)) for nivel, p in periodos.items()}
    calendario = Calendario(asignaciones[0].ciclo)
    historial = defaultdict(list)
    for bloque in HorarioMateria.historial.filter(materia_grado__in=asignaciones):
        historial[bloque.materia_grado_id].append(bloque)
    capturados = defaultdict(set)
    for asignacion_id, fecha in (AsistenciaMateria.objects.filter(materia_grado__in=asignaciones, fecha__range=(desde, hoy))
                                 .values_list('materia_grado_id', 'fecha').distinct()):
        capturados[asignacion_id].add(fecha)
    pendientes = []
    for asignacion in asignaciones:
        periodo = periodos.get(asignacion.grado.nivel)
        if periodo is None or not asignacion.horarios.all():
            continue
        hasta = min(hoy, periodo.fecha_fin)
        # Días con clase según su semana A/B y la versión del horario de cada fecha (Alumnos/semanas.py)
        fechas = [periodo.fecha_inicio + timedelta(dias) for dias in range((hasta - periodo.fecha_inicio).days + 1)]
        con_clase = {f for f in fechas if any(calendario.aplica(b, f, periodo.nivel) for b in historial[asignacion.pk])}
        faltan = [
            fecha for fecha in fechas
            if fecha in con_clase and fecha not in sin_clases[periodo.nivel] and fecha not in capturados[asignacion.pk]
        ]
        if faltan:
            pendientes.append({'asignacion': asignacion, 'periodo': periodo, 'dias': len(faltan), 'ultimo': faltan[-1]})
    return pendientes


def calificaciones_por_cerrar(asignaciones, hoy=None):
    from Calificaciones.models import ActaCalificaciones
    hoy = hoy or timezone.localdate()
    if not asignaciones:
        return []
    por_nivel = defaultdict(list)
    for periodo in Periodo.objects.filter(ciclo=asignaciones[0].ciclo_id, nivel__in={a.grado.nivel for a in asignaciones},
                                          fecha_inicio__lte=hoy).order_by('fecha_inicio'):
        por_nivel[periodo.nivel].append(periodo)
    actas = {(a.asignacion_id, a.periodo_id): a for a in ActaCalificaciones.objects.filter(asignacion__in=asignaciones)}
    pendientes = []
    for asignacion in asignaciones:
        for periodo in por_nivel[asignacion.grado.nivel]:
            acta = actas.get((asignacion.pk, periodo.pk))
            if acta is None or not acta.cerrada:
                pendientes.append({
                    'asignacion': asignacion, 'periodo': periodo, 'acta': acta,
                    'estado': 'Sin empezar' if acta is None else 'En captura',
                    'vencido': periodo.fecha_fin < hoy,
                })
    return pendientes


def bitacoras(profesor, ciclo):
    from Bitacoras.models import EntradaBitacora
    if not profesor.usuario_id or ciclo is None:
        return None
    entradas = EntradaBitacora.objects.filter(autor_id=profesor.usuario_id, ciclo=ciclo, anulada=False)
    return {'total': entradas.count(), 'recientes': list(entradas.order_by('-fecha', '-pk')[:RECIENTES])}


def reuniones(profesor, hoy=None):
    from Reuniones.models import Reunion
    if not profesor.usuario_id:
        return None
    hoy = hoy or timezone.localdate()
    suyas = Reunion.objects.filter(responsable_id=profesor.usuario_id).select_related('tutor', 'motivo')
    return {
        'abiertas': list(suyas.filter(estado__in=Reunion.ABIERTAS).order_by('fecha', 'pk')[:RECIENTES * 2]),
        'recientes': list(suyas.exclude(estado__in=Reunion.ABIERTAS).filter(fecha__gte=hoy - timedelta(days=30)).order_by('-fecha')[:RECIENTES]),
    }


def contexto(profesor, ciclo, hoy=None):
    asignaciones = _asignaciones(profesor, ciclo)
    datos = {
        'asistencias_pendientes': asistencias_por_capturar(asignaciones, hoy),
        'actas_pendientes': calificaciones_por_cerrar(asignaciones, hoy),
        'bitacoras': bitacoras(profesor, ciclo),
        'reuniones': reuniones(profesor, hoy),
    }
    datos['pendientes_360'] = (
        len(datos['asistencias_pendientes']) + len(datos['actas_pendientes'])
        + (len(datos['reuniones']['abiertas']) if datos['reuniones'] else 0)
    )
    return datos
