"""Las columnas de la tabla de estudiantes (pedido del 2026-10-28).

- Cuáles hay y cuáles puede ver cada cuenta: las de asistencia, solo con permiso de consultar la asistencia; el promedio,
  solo con permiso de ver todas las calificaciones (si solo ve las suyas, el promedio general no sería el real); los
  casos de conducta, solo con permiso de conducta (y de los estudiantes de su alcance).
- Cuáles eligió en el menú «Columnas» (se guardan en su perfil: `PerfilUsuario.preferencias`); sin elegir, las de
  siempre. Ya no dependen del ancho de la pantalla: si no caben, la tabla se desplaza de lado.
- Los datos de las columnas nuevas para las filas de la página (o de la exportación), con pocas consultas que no crecen
  con el número de filas: asistencia del ciclo, promedio de las actas cerradas, casos de conducta abiertos, el acceso al
  portal del estudiante y de su tutor principal, y su tarjeta de entrada.
"""
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.db import DatabaseError
from django.db.models import Count, Q

PREFERENCIA = 'columnas_estudiantes'


def ve_asistencia(usuario):
    return usuario.has_perm('Alumnos.view_asistenciageneral')


def ve_calificaciones(usuario):
    from Calificaciones.reglas import ve_todas
    return ve_todas(usuario)


def ve_conducta(usuario):
    from Conducta import permisos
    return permisos.puede_ver(usuario)


@dataclass(frozen=True)
class Columna:
    clave: str
    titulo: str
    descripcion: str
    permiso: object = None          # función(usuario) -> bool; sin ella, la ve quien ve la lista
    predeterminada: bool = True


COLUMNAS = [
    Columna('grado', 'Grado actual', 'Su grado y grupo en el ciclo actual'),
    Columna('asistencia_hoy', 'Asistencia hoy', 'Su entrada al colegio hoy', ve_asistencia),
    Columna('asistencia_ciclo', 'Asistencia del ciclo', 'Porcentaje de asistencia y faltas en el ciclo actual', ve_asistencia, False),
    Columna('promedio', 'Promedio', 'Promedio general de las actas cerradas del ciclo', ve_calificaciones, False),
    Columna('conducta', 'Conducta', 'Casos de conducta abiertos o en seguimiento', ve_conducta, False),
    Columna('tutor', 'Tutor principal', 'Nombre, parentesco y teléfono'),
    Columna('edad', 'Edad', 'Años cumplidos'),
    Columna('portal', 'Portal', 'Si el estudiante y su tutor pueden entrar y si ya entraron', None, False),
    Columna('tarjeta', 'Tarjeta de entrada', 'Si tiene asignada la tarjeta del registro de entrada', None, False),
    Columna('estatus', 'Estatus', 'Activo, suspendido, egresado…'),
]
POR_CLAVE = {columna.clave: columna for columna in COLUMNAS}


def disponibles(usuario):
    return [c for c in COLUMNAS if c.permiso is None or c.permiso(usuario)]


def elegidas(usuario):
    """Las claves de las columnas que ve, en el orden de la tabla: las que eligió (y todavía puede ver) o las de siempre."""
    from Usuarios.models import PerfilUsuario
    try:
        guardadas = (PerfilUsuario.objects.filter(usuario=usuario).values_list('preferencias', flat=True).first() or {}).get(PREFERENCIA)
    except DatabaseError:   # sin la migración de Usuarios
        guardadas = None
    claves = {c.clave for c in disponibles(usuario)}
    if isinstance(guardadas, list):
        return [c.clave for c in COLUMNAS if c.clave in claves and c.clave in guardadas]
    return [c.clave for c in COLUMNAS if c.clave in claves and c.predeterminada]


def guardar(usuario, claves):
    """Guarda las columnas elegidas (solo las que existen y puede ver). Sin `claves`, vuelve a las de siempre."""
    from Usuarios.models import PerfilUsuario
    perfil = PerfilUsuario.de(usuario)
    preferencias = dict(perfil.preferencias or {})
    if claves is None:
        preferencias.pop(PREFERENCIA, None)
    else:
        validas = {c.clave for c in disponibles(usuario)}
        preferencias[PREFERENCIA] = [c.clave for c in COLUMNAS if c.clave in validas and c.clave in set(claves)]
    perfil.preferencias = preferencias
    perfil.save(update_fields=['preferencias', 'modificado'])
    return preferencias.get(PREFERENCIA)


# ---------------------------------------------------------------------------
# Los datos de las columnas nuevas
# ---------------------------------------------------------------------------
def _inscripcion(alumno):
    return (getattr(alumno, 'inscripciones_actuales', None) or [None])[0]


def asistencia_del_ciclo(alumnos):
    """{id del estudiante: {'porcentaje', 'faltas', 'justificadas', 'total'}} de su inscripción del ciclo actual (como el
    resumen de su expediente: asistió = presente o retardo)."""
    from .asistencias import con_justificada_general
    from .models import AsistenciaGeneral
    inscripciones = {i.pk: a.pk for a in alumnos if (i := _inscripcion(a)) is not None}
    if not inscripciones:
        return {}
    filas = (con_justificada_general(AsistenciaGeneral.objects.filter(inscripcion__in=list(inscripciones)))
             .values('inscripcion_id').order_by()
             .annotate(total=Count('pk'), asistio=Count('pk', filter=Q(estado__in=('PRESENTE', 'RETARDO'))),
                       faltas=Count('pk', filter=Q(estado='FALTA')), justificadas=Count('pk', filter=Q(estado='FALTA', justificada=True))))
    resultado = {}
    for fila in filas:
        total = fila['total']
        resultado[inscripciones[fila['inscripcion_id']]] = {
            'porcentaje': round(100 * fila['asistio'] / total) if total else None, 'faltas': fila['faltas'],
            'justificadas': fila['justificadas'], 'total': total,
        }
    return resultado


def promedios(alumnos):
    """{id del estudiante: su promedio general} de las actas cerradas del ciclo actual, como su portal y su Vista 360:
    el promedio de cada materia de su grupo y luego el de todas (sin las pendientes). Una vuelta por grupo."""
    from Calificaciones.models import ActaCalificaciones
    from PortalEstudiantes.resumen import promedio

    from .models import MateriaGrado, Periodo
    por_grupo = defaultdict(list)
    for alumno in alumnos:
        inscripcion = _inscripcion(alumno)
        if inscripcion is not None and inscripcion.grupo_id:
            por_grupo[(inscripcion.grupo_id, inscripcion.ciclo_id, inscripcion.grado.nivel)].append((alumno.pk, inscripcion.pk))
    resultado = {}
    for (grupo, ciclo, nivel), lista in por_grupo.items():
        periodos = list(Periodo.objects.filter(ciclo_id=ciclo, nivel=nivel).values_list('pk', flat=True))
        asignaciones = list(MateriaGrado.objects.filter(grupo_id=grupo, ciclo_id=ciclo, activa=True).values_list('pk', flat=True))
        ids = {inscripcion for _, inscripcion in lista}
        finales = defaultdict(dict)
        actas = ActaCalificaciones.objects.filter(asignacion__in=asignaciones, periodo__in=periodos, estado=ActaCalificaciones.CERRADA)
        for acta in actas.only('asignacion_id', 'periodo_id', 'resultados_cerrados'):
            for fila in acta.resultados_cerrados or []:
                if fila.get('inscripcion') in ids and fila.get('final') not in (None, ''):
                    finales[fila['inscripcion']][(acta.asignacion_id, acta.periodo_id)] = Decimal(str(fila['final']))
        for alumno, inscripcion in lista:
            por_materia = [promedio([finales[inscripcion].get((a, p)) for p in periodos]) for a in asignaciones]
            resultado[alumno] = promedio(por_materia)
    # Quien cursa grupos de clase tiene materias fuera de las de su grupo: su promedio es el de su portal
    from PortalEstudiantes.resumen import calificaciones_de

    from .models import IntegranteClase
    from .clases import EN_EFECTO
    ids = [i for lista in por_grupo.values() for _, i in lista]
    if ids:
        en_clases = set(IntegranteClase.objects.filter(inscripcion__in=ids, clase__bloque__estado__in=EN_EFECTO).values_list('inscripcion_id', flat=True))
        for alumno in alumnos:
            inscripcion = _inscripcion(alumno)
            if inscripcion is not None and inscripcion.pk in en_clases:
                resultado[alumno.pk] = calificaciones_de(inscripcion).promedio_general
    return resultado


def casos_de_conducta(usuario, alumnos):
    """{id del estudiante: cuántos casos de conducta (incidencias) tiene abiertos o en seguimiento}, de los que la cuenta
    puede ver."""
    from Conducta.models import INCIDENCIA, RegistroConducta
    from Conducta.views import registros_de
    filas = (registros_de(usuario).filter(alumno__in=[a.pk for a in alumnos], anulado=False, tipo=INCIDENCIA)
             .exclude(estado=RegistroConducta.CERRADO).values('alumno').order_by().annotate(n=Count('pk')))
    return {fila['alumno']: fila['n'] for fila in filas}


@dataclass
class Portal:
    """El acceso de una cuenta al portal: si puede entrar (`estado`, de CISAHUAYO/portales.estado_de_cuenta) y cuándo
    entró por última vez."""
    estado: object
    ultimo_acceso: object

    @property
    def puede_entrar(self):
        return self.estado.clave == 'activo'

    @property
    def texto(self):
        if not self.puede_entrar:
            return 'Sin acceso'
        return 'Nunca ha entrado' if self.ultimo_acceso is None else 'Ya entró'


def portales_de(alumno):
    """(Portal del estudiante, Portal de su tutor principal o None)."""
    from CISAHUAYO import portales
    del_alumno = Portal(portales.estado_de_cuenta(portales.ESTUDIANTE, alumno), alumno.ultimo_acceso)
    vinculo = (getattr(alumno, 'vinculos_activos', None) or [None])[0]
    del_tutor = Portal(portales.estado_de_cuenta(portales.TUTOR, vinculo.tutor), vinculo.tutor.ultimo_acceso) if vinculo else None
    return del_alumno, del_tutor


def preparar(usuario, alumnos, claves):
    """Pone en cada estudiante los datos de las columnas nuevas que se muestran (`claves`)."""
    asistencia = asistencia_del_ciclo(alumnos) if 'asistencia_ciclo' in claves else {}
    notas = promedios(alumnos) if 'promedio' in claves else {}
    casos = casos_de_conducta(usuario, alumnos) if 'conducta' in claves else {}
    for alumno in alumnos:
        alumno.asistencia_ciclo = asistencia.get(alumno.pk)
        alumno.promedio = notas.get(alumno.pk)
        alumno.casos_abiertos = casos.get(alumno.pk, 0)
        if 'portal' in claves:
            alumno.portal_alumno, alumno.portal_tutor = portales_de(alumno)
