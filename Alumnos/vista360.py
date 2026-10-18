"""Vista 360 del estudiante (pedido del 2026-10-17): un tablero del expediente que junta en un círculo lo que ya existe
en cinco módulos (calificaciones, asistencia, conducta, seguimiento y retiros) de un ciclo y un periodo.

No crea registros ni repite reglas: cada sección se arma con las funciones de su módulo y sus permisos.
- **Calificaciones**: las de las actas cerradas (PortalEstudiantes/resumen.py): cada materia trae su calificación final
  calculada con las ponderaciones de su configuración; el promedio general es el mismo que usa el sistema (el de las
  materias, sin las pendientes). Un docente sin «ver todas» solo ve sus materias. El sistema no tiene evaluación
  cualitativa: todos los niveles califican con números.
- **Asistencia**: la general (entrada al colegio), sin los días de una suspensión autorizada, con las justificadas aparte
  (Alumnos/asistencias.py); la de cada materia se muestra por separado y nunca se mezcla con la general. Solo cuentan los
  días con registro hasta hoy: los futuros, sin clases o sin captura no son faltas.
- **Conducta**: los registros formales vigentes del periodo (incidencias y conductas positivas, con medidas y
  suspensiones) y, aparte, las observaciones de las bitácoras de grupo en que aparece el estudiante (informativas: no son
  registros de conducta ni afectan calificaciones).
- **Seguimiento**: en el sistema el seguimiento es el de los casos de conducta (responsable, citas con la familia,
  compromisos, revisión y cierre). Es un estado actual: los casos abiertos hoy, más los que se cerraron en el periodo.
- **Retiros**: los avisos de retiro anticipado del estudiante (solo los suyos, aunque el aviso incluya a sus hermanos),
  con sus estados reales: Avisado, Retirado (salida confirmada) o Cancelado.

Cada sección tiene su estado: con datos, sin registros, no aplica, sin permiso o error de consulta (si una falla, las
demás se muestran igual).
"""
import math
from collections import defaultdict
from dataclasses import dataclass, field
from urllib.parse import urlencode

from django.db import DatabaseError
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from .models import AsistenciaGeneral, AsistenciaMateria, Justificacion, Periodo

OK, VACIO, NO_APLICA, SIN_PERMISO, ERROR = 'ok', 'vacio', 'no_aplica', 'sin_permiso', 'error'
DEL_PERIODO, ACTUAL = 'periodo', 'actual'
HISTORIAL_RECIENTE = 15


@dataclass
class Seccion:
    clave: str
    titulo: str
    icono: str
    estado: str = OK
    valor: str = '—'
    descripcion: str = ''
    alcance: str = DEL_PERIODO      # «periodo» (acumulado del periodo) o «actual» (estado de hoy)
    mensaje: str = ''               # por qué no hay datos, no hay permiso o falló la consulta
    detalle: dict = field(default_factory=dict)
    enlace: str = ''                # «Ver detalle completo»
    etiqueta_enlace: str = ''

    # El segmento del círculo y la caja de su texto, en % del círculo (los pone `secciones_de`)
    trazo: str = ''
    izquierda: float = 0.0
    arriba: float = 0.0
    ancho: float = 0.0
    alto: float = 0.0

    @property
    def lineas(self):
        """La descripción en renglones (en el círculo cada parte va en el suyo)."""
        return [parte for parte in self.descripcion.split(' · ') if parte]

    def sin(self, estado, mensaje, valor='—'):
        self.estado, self.mensaje, self.valor = estado, mensaje, valor
        self.descripcion = self.descripcion or mensaje
        return self


@dataclass
class Filtros:
    ciclos: list
    ciclo: object = None
    inscripcion: object = None
    periodos: list = field(default_factory=list)
    periodo: object = None          # None: todo el ciclo
    desde: object = None
    hasta: object = None

    @property
    def nombre_del_rango(self):
        if self.periodo is not None:
            return self.periodo.nombre
        return f'Ciclo {self.ciclo}' if self.ciclo else ''

    @property
    def consulta(self):
        """Los filtros para las direcciones de los otros módulos (se conservan al navegar)."""
        return {'ciclo': self.ciclo.pk if self.ciclo else '', 'periodo': self.periodo.pk if self.periodo else ''}


# ---------------------------------------------------------------------------
# El estudiante
# ---------------------------------------------------------------------------
def edad(nacimiento, hoy=None):
    """(años, meses) cumplidos a hoy."""
    hoy = hoy or timezone.localdate()
    meses = (hoy.year - nacimiento.year) * 12 + hoy.month - nacimiento.month - (1 if hoy.day < nacimiento.day else 0)
    return max(meses, 0) // 12, max(meses, 0) % 12


def texto_de_edad(nacimiento, hoy=None):
    if not nacimiento:
        return ''
    anios, meses = edad(nacimiento, hoy)
    partes = [f'{anios} año{"" if anios == 1 else "s"}']
    if meses:
        partes.append(f'{meses} mes{"" if meses == 1 else "es"}')
    return ', '.join(partes)


# ---------------------------------------------------------------------------
# Filtros: ciclo y periodo
# ---------------------------------------------------------------------------
def filtros_de(alumno, ciclo_pedido='', periodo_pedido=''):
    """El ciclo (por omisión el actual, si estuvo inscrito; si no, el más reciente) y el periodo (por omisión el
    abierto hoy en el ciclo actual; en otro ciclo, todo el ciclo). `periodo_pedido='ciclo'` es todo el ciclo."""
    from Calificaciones.reglas import periodo_sugerido

    inscripciones = list(alumno.inscripciones.select_related('ciclo', 'grado', 'grupo__nombre', 'grupo__grado')
                         .order_by('-ciclo__fecha_inicio', '-activa', '-fecha_inscripcion'))
    ciclos = list(dict.fromkeys(i.ciclo for i in inscripciones))
    if not ciclos:
        return Filtros(ciclos=[])
    ciclo = next((c for c in ciclos if str(c.pk) == str(ciclo_pedido)), None) or next((c for c in ciclos if c.activo), ciclos[0])
    inscripcion = next(i for i in inscripciones if i.ciclo_id == ciclo.pk)
    periodos = list(Periodo.objects.filter(ciclo=ciclo, nivel=inscripcion.grado.nivel).order_by('fecha_inicio', 'nombre'))
    if periodo_pedido == 'ciclo':
        periodo = None
    elif str(periodo_pedido).isdigit():
        periodo = next((p for p in periodos if p.pk == int(periodo_pedido)), None)
    else:
        periodo = periodo_sugerido(periodos) if ciclo.activo else None
    desde, hasta = (periodo.fecha_inicio, periodo.fecha_fin) if periodo else (ciclo.fecha_inicio, ciclo.fecha_fin)
    return Filtros(ciclos=ciclos, ciclo=ciclo, inscripcion=inscripcion, periodos=periodos, periodo=periodo, desde=desde, hasta=hasta)


def _url(nombre, *args, **consulta):
    url = reverse(nombre, args=args)
    consulta = {k: v for k, v in consulta.items() if v not in (None, '')}
    return f'{url}?{urlencode(consulta, doseq=True)}' if consulta else url


# ---------------------------------------------------------------------------
# Calificaciones
# ---------------------------------------------------------------------------
def calificaciones(usuario, filtros):
    from Calificaciones import reglas as cal
    from Calificaciones.models import ActaCalificaciones
    from PortalEstudiantes.resumen import calificaciones_de, promedio

    seccion = Seccion('calificaciones', 'Calificaciones', 'award')
    if not any(usuario.has_perm(p) for p in cal.ENTRAR):
        return seccion.sin(SIN_PERMISO, 'Sin permiso')
    if filtros.inscripcion is None:
        return seccion.sin(NO_APLICA, 'Sin inscripción en el ciclo')
    datos = calificaciones_de(filtros.inscripcion)
    filas = [fila for fila in datos.filas if cal.puede_ver(usuario, fila.asignacion)]
    if not datos.filas:
        seccion.detalle = {'sin_materias': True}
        return seccion.sin(VACIO, 'Sin calificaciones registradas')
    if not filas:
        return seccion.sin(SIN_PERMISO, 'Sin permiso para sus materias')
    periodos = datos.periodos
    indice = next((i for i, p in enumerate(periodos) if filtros.periodo and p.pk == filtros.periodo.pk), None)
    if filtros.periodo is not None and indice is None:
        return seccion.sin(NO_APLICA, 'El periodo no es de su nivel')
    general = promedio([fila.valores[indice] for fila in filas]) if indice is not None else promedio([fila.promedio for fila in filas])
    en_captura = ActaCalificaciones.objects.filter(
        asignacion__in=[fila.asignacion for fila in filas], estado=ActaCalificaciones.EN_CAPTURA,
        **({'periodo': filtros.periodo} if filtros.periodo else {'periodo__in': periodos}),
    ).count()
    for fila in filas:
        fila.url = _url('calificaciones:inicio', ciclo=filtros.ciclo.pk, materia=fila.asignacion.pk,
                        periodo=filtros.periodo.pk if filtros.periodo else '')
    seccion.detalle = {
        'periodos': periodos, 'filas': filas, 'indice': indice, 'general': general, 'en_captura': en_captura,
        'por_periodo': [promedio([fila.valores[i] for fila in filas]) for i in range(len(periodos))],
        'del_ciclo': promedio([fila.promedio for fila in filas]),
        'solo_suyas': len(filas) < len(datos.filas),
    }
    seccion.enlace = _url('calificaciones:inicio', ciclo=filtros.ciclo.pk, grupo=filtros.inscripcion.grupo_id,
                          periodo=filtros.periodo.pk if filtros.periodo else '')
    seccion.etiqueta_enlace = 'Ir a calificaciones'
    if general is None:
        seccion.sin(VACIO, 'Sin calificaciones registradas')
        if en_captura:
            seccion.descripcion = f'Sin calificaciones cerradas ({en_captura} en captura)'
        return seccion
    seccion.valor = f'{general}'
    seccion.descripcion = 'Promedio general' + (' de tus materias' if seccion.detalle['solo_suyas'] else '')
    return seccion


# ---------------------------------------------------------------------------
# Asistencia
# ---------------------------------------------------------------------------
def _dias_de_suspension(alumno, filtros, hasta):
    """Días de clases del rango que caen en una suspensión autorizada (no son faltas)."""
    from Conducta.models import APROBADA, Suspension

    from .asistencias import dias_de_clases
    suspensiones = Suspension.objects.filter(
        registro__alumno=alumno, registro__anulado=False, aprobacion=APROBADA, fecha_inicio__lte=hasta, fecha_fin__gte=filtros.desde,
    )
    dias = set()
    for suspension in suspensiones:
        dias.update(dias_de_clases(max(filtros.desde, suspension.fecha_inicio), min(hasta, suspension.fecha_fin), filtros.ciclo,
                                   filtros.inscripcion.grado.nivel))
    return len(dias)


def asistencia(usuario, alumno, filtros):
    from .asistencias import con_justificada_general, con_justificada_materia, conteos, porcentaje, sin_dias_suspendidos

    seccion = Seccion('asistencia', 'Asistencia', 'user-check')
    if not usuario.has_perm('Alumnos.view_asistenciageneral'):
        return seccion.sin(SIN_PERMISO, 'Sin permiso')
    if filtros.inscripcion is None:
        return seccion.sin(NO_APLICA, 'Sin inscripción en el ciclo')
    hoy = timezone.localdate()
    if filtros.desde > hoy:
        return seccion.sin(NO_APLICA, 'El periodo todavía no empieza')
    hasta = min(filtros.hasta, hoy)
    inscripcion = filtros.inscripcion
    generales = sin_dias_suspendidos(con_justificada_general(
        AsistenciaGeneral.objects.filter(inscripcion=inscripcion, fecha__range=(filtros.desde, hasta))))
    totales = conteos(generales)
    totales['sin_justificar'] = totales['faltas'] - totales['justificadas']
    totales['porcentaje'] = porcentaje(totales['presentes'], totales['retardos'], totales['registros'])
    totales['suspension'] = _dias_de_suspension(alumno, filtros, hasta)

    materias = sin_dias_suspendidos(con_justificada_materia(
        AsistenciaMateria.objects.filter(inscripcion=inscripcion, fecha__range=(filtros.desde, hasta))))
    por_materia = list(
        materias.order_by().values('materia_grado__materia__nombre').annotate(
            registros=Count('pk'), presentes=Count('pk', filter=Q(estado='PRESENTE')), retardos=Count('pk', filter=Q(estado='RETARDO')),
            faltas=Count('pk', filter=Q(estado='FALTA')), justificadas=Count('pk', filter=Q(estado='FALTA', justificada=True)),
        ).order_by('materia_grado__materia__nombre')
    )
    for fila in por_materia:
        fila['porcentaje'] = porcentaje(fila['presentes'], fila['retardos'], fila['registros'])

    recientes = list(generales.order_by('-fecha')[:HISTORIAL_RECIENTE])
    del_dia = defaultdict(list)
    for registro in materias.filter(fecha__in=[r.fecha for r in recientes]).select_related('materia_grado__materia').order_by('materia_grado__materia__nombre'):
        del_dia[registro.fecha].append(registro)
    for registro in recientes:
        registro.materias = del_dia.get(registro.fecha, [])

    # Las justificaciones (con su motivo y comprobante) solo para quien consulta justificaciones, como en Asistencias
    ve_justificaciones = usuario.has_perm('Alumnos.view_justificacion')
    justificaciones = list(Justificacion.objects.filter(inscripcion=inscripcion, fecha__range=(filtros.desde, hasta))
                           .order_by('-fecha', '-pk')[:HISTORIAL_RECIENTE]) if ve_justificaciones else []
    seccion.detalle = {
        'totales': totales, 'por_materia': por_materia, 'recientes': recientes, 'justificaciones': justificaciones,
        've_comprobantes': ve_justificaciones, 'hasta': hasta,
    }
    seccion.enlace = _url('asistencias:alumno', alumno.pk, ciclo=filtros.ciclo.pk)
    seccion.etiqueta_enlace = 'Ver historial de asistencia'
    if not totales['registros']:
        return seccion.sin(VACIO, 'Sin registros')
    seccion.valor = f'{totales["porcentaje"]} %'
    seccion.descripcion = 'Asistencia de entrada'
    return seccion


# ---------------------------------------------------------------------------
# Conducta y bitácoras
# ---------------------------------------------------------------------------
def _ve_conducta(usuario, alumno):
    """Como en el módulo de conducta: la administración o prefectura, y una cuenta de prefectura solo con los
    estudiantes de su alcance."""
    from Conducta import permisos
    from Prefectura.alcance import alcance_de
    return permisos.puede_ver(usuario) and alcance_de(usuario).permite(alumno)


def conducta(usuario, alumno, filtros):
    from Bitacoras.alcance import alcance_de_bitacoras, puede_entrar
    from Bitacoras.models import EstudianteBitacora
    from Conducta.models import INCIDENCIA, POSITIVA, RegistroConducta
    from Conducta.reglas import con_relaciones

    seccion = Seccion('conducta', 'Conducta', 'flag')
    if not _ve_conducta(usuario, alumno):
        return seccion.sin(SIN_PERMISO, 'Sin permiso')
    if filtros.ciclo is None:
        return seccion.sin(NO_APLICA, 'Sin inscripciones')
    # Como los reportes de conducta: los registros del ciclo y, si se eligió un periodo, los de sus fechas
    registros = RegistroConducta.objects.vigentes().filter(alumno=alumno, ciclo=filtros.ciclo)
    if filtros.periodo is not None:
        registros = registros.filter(fecha__range=(filtros.desde, filtros.hasta))
    registros = list(con_relaciones(registros).order_by('-fecha', '-hora', '-pk'))
    incidencias = sum(1 for r in registros if r.tipo == INCIDENCIA)
    positivas = sum(1 for r in registros if r.tipo == POSITIVA)
    # Las observaciones de bitácora, como en la página de bitácoras del estudiante (con el alcance de la persona)
    bitacora, bitacora_permitida = [], False
    if puede_entrar(usuario):
        alcance = alcance_de_bitacoras(usuario)
        bitacora_permitida = alcance.ve_estudiante(alumno)
    if bitacora_permitida:
        entradas = alcance.entradas().filter(pk__in=EstudianteBitacora.objects.filter(alumno=alumno).values('entrada'), ciclo=filtros.ciclo)
        if filtros.periodo is not None:
            entradas = entradas.filter(fecha__range=(filtros.desde, filtros.hasta))
        bitacora = list(entradas.order_by('-fecha', '-hora_inicio', '-creado', '-pk')[:HISTORIAL_RECIENTE])
    seccion.detalle = {
        'registros': registros, 'incidencias': incidencias, 'positivas': positivas, 'bitacora': bitacora,
        'bitacora_permitida': bitacora_permitida,
        'url_bitacora': _url('bitacoras:estudiante', alumno.pk, ciclo=filtros.ciclo.pk) if bitacora_permitida else '',
    }
    seccion.enlace = _url('conducta:reportes', reporte='historial', alumnos=alumno.pk, ciclo=filtros.ciclo.pk,
                          periodo=filtros.periodo.pk if filtros.periodo else '')
    seccion.etiqueta_enlace = 'Ver reporte de conducta'
    seccion.valor = str(len(registros))
    if registros:
        partes = []
        if incidencias:
            partes.append(f'{incidencias} incidencia{"s" if incidencias != 1 else ""}')
        if positivas:
            partes.append(f'{positivas} positiva{"s" if positivas != 1 else ""}')
        seccion.descripcion = ' · '.join(partes)
    else:
        seccion.estado, seccion.descripcion = VACIO, 'Sin anotaciones en este periodo'
    return seccion


# ---------------------------------------------------------------------------
# Seguimiento (casos de conducta)
# ---------------------------------------------------------------------------
def _proxima_atencion(caso, hoy):
    """La fecha más próxima pendiente del caso: su revisión, una cita programada o un compromiso pendiente."""
    fechas = [caso.fecha_revision] if caso.fecha_revision else []
    fechas += [cita.fecha for cita in caso.citas.all() if cita.abierta]
    fechas += [compromiso.fecha_limite for compromiso in caso.compromisos.all() if compromiso.abierto]
    if not fechas:
        return None, False
    proxima = min(fechas)
    return proxima, proxima < hoy


def seguimiento(usuario, alumno, filtros):
    from Conducta.models import INCIDENCIA, RegistroConducta

    seccion = Seccion('seguimiento', 'Seguimiento', 'clipboard-check', alcance=ACTUAL)
    if not _ve_conducta(usuario, alumno):
        return seccion.sin(SIN_PERMISO, 'Sin permiso')
    casos = (RegistroConducta.objects.vigentes().filter(alumno=alumno, tipo=INCIDENCIA)
             .select_related('responsable', 'cerrado_por').prefetch_related('citas', 'compromisos', 'contactos'))
    abiertos = list(casos.exclude(estado=RegistroConducta.CERRADO).order_by('fecha', 'pk'))
    cerrados = []
    if filtros.ciclo is not None:
        cerrados = list(casos.filter(estado=RegistroConducta.CERRADO, cerrado_en__date__range=(filtros.desde, filtros.hasta))
                        .order_by('-cerrado_en'))
    hoy = timezone.localdate()
    for caso in abiertos + cerrados:
        caso.proxima, caso.atrasada = _proxima_atencion(caso, hoy)
        caso.url = reverse('conducta:seguimiento', args=[caso.pk])
    seccion.detalle = {'abiertos': abiertos, 'cerrados': cerrados}
    seccion.enlace = reverse('conducta:lista') + '?' + urlencode({'q': alumno.referencia, 'ciclo': '', 'estado': 'abiertos'})
    seccion.etiqueta_enlace = 'Ver registro de conducta'
    seccion.valor = str(len(abiertos))
    if abiertos:
        atrasados = sum(1 for caso in abiertos if caso.atrasada)
        seccion.descripcion = f'Caso{"s" if len(abiertos) != 1 else ""} abierto{"s" if len(abiertos) != 1 else ""}' + (f' · {atrasados} atrasado{"s" if atrasados != 1 else ""}' if atrasados else '')
    else:
        seccion.estado, seccion.descripcion = VACIO, 'Sin casos abiertos'
    return seccion


# ---------------------------------------------------------------------------
# Retiros anticipados
# ---------------------------------------------------------------------------
def retiros(usuario, alumno, filtros):
    from Retiros.alcance import alcance_de, condicion, usa_retiros
    from Retiros.models import RetiroEstudiante

    seccion = Seccion('retiros', 'Retiros', 'log-out')
    if not usa_retiros(usuario):
        return seccion.sin(SIN_PERMISO, 'Sin permiso')
    if filtros.inscripcion is None:
        return seccion.sin(NO_APLICA, 'Sin inscripción en el ciclo')
    alcance = alcance_de(usuario)
    if not alcance.permite_grupo(filtros.inscripcion.grupo):
        return seccion.sin(SIN_PERMISO, 'Fuera de tus niveles')
    lista = list(
        RetiroEstudiante.objects.filter(alumno=alumno, fecha__range=(filtros.desde, filtros.hasta)).filter(condicion(alcance))
        .select_related('aviso__motivo', 'aviso__tutor', 'aviso__recoge', 'recogio', 'confirmado_por', 'cancelado_por_usuario',
                        'cancelado_por_tutor')
        .order_by('-fecha', '-aviso__hora')
    )
    salidas = sum(1 for r in lista if r.estado == RetiroEstudiante.RETIRADO)
    pendientes = sum(1 for r in lista if r.estado == RetiroEstudiante.AVISADO)
    vigentes = salidas + pendientes
    seccion.detalle = {'retiros': lista, 'salidas': salidas, 'pendientes': pendientes,
                       'cancelados': len(lista) - vigentes}
    seccion.enlace = _url('retiros:lista', vista='todos', q=alumno.referencia, desde=filtros.desde.isoformat(), hasta=filtros.hasta.isoformat())
    seccion.etiqueta_enlace = 'Ir a retiros anticipados'
    seccion.valor = str(vigentes)
    if lista:
        seccion.descripcion = (f'Aviso{"s" if vigentes != 1 else ""} de retiro · '
                               f'{salidas} salida{"s" if salidas != 1 else ""} confirmada{"s" if salidas != 1 else ""}')
    else:
        seccion.estado, seccion.descripcion = VACIO, 'Sin avisos de retiro'
    return seccion


# ---------------------------------------------------------------------------
# Todo junto
# ---------------------------------------------------------------------------
def _segura(funcion, clave, titulo, icono, *args):
    """La sección, o una con error si la consulta falla (las demás se muestran igual)."""
    try:
        return funcion(*args)
    except DatabaseError:
        return Seccion(clave, titulo, icono).sin(ERROR, 'No se pudo consultar')


# Clave, título, icono, centro de su segmento (grados desde arriba, en el sentido del reloj) y la caja de su texto
# (x e y de su centro, ancho y alto, en unidades del viewBox de -100 a 100). Cada caja es el rectángulo más grande que
# cabe en su segmento dejando 4 de margen con el borde exterior y con el hueco, y 4.5 con las divisiones: el texto va
# dentro de ella (y se achica si no cabe), así nunca se sale del anillo.
SECCIONES = (
    ('calificaciones', 'Calificaciones', 'award', 324, (-26, -64, 42, 32)),      # arriba a la izquierda
    ('asistencia', 'Asistencia', 'user-check', 36, (26, -64, 42, 32)),             # arriba a la derecha
    ('conducta', 'Conducta', 'flag', 108, (68, 10, 40, 40)),                       # abajo a la derecha
    ('seguimiento', 'Seguimiento', 'clipboard-check', 180, (0, 68, 59, 39)),       # abajo
    ('retiros', 'Retiros', 'log-out', 252, (-68, 10, 40, 40)),                     # abajo a la izquierda
)
EXTERIOR, INTERIOR = 98, 44   # radios del anillo (el hueco del centro lleva los datos del estudiante)


def _punto(grados, radio):
    angulo = math.radians(grados)
    return round(radio * math.sin(angulo), 2), round(-radio * math.cos(angulo), 2)


def _segmento(centro):
    """El trazo SVG de un segmento de 72° del anillo, centrado en `centro`."""
    desde, hasta = centro - 36, centro + 36
    (x1, y1), (x2, y2) = _punto(desde, EXTERIOR), _punto(hasta, EXTERIOR)
    (x3, y3), (x4, y4) = _punto(hasta, INTERIOR), _punto(desde, INTERIOR)
    return (f'M{x1} {y1}A{EXTERIOR} {EXTERIOR} 0 0 1 {x2} {y2}'
            f'L{x3} {y3}A{INTERIOR} {INTERIOR} 0 0 0 {x4} {y4}Z')


def secciones_de(usuario, alumno, filtros):
    constructores = {
        'calificaciones': lambda: calificaciones(usuario, filtros),
        'asistencia': lambda: asistencia(usuario, alumno, filtros),
        'conducta': lambda: conducta(usuario, alumno, filtros),
        'seguimiento': lambda: seguimiento(usuario, alumno, filtros),
        'retiros': lambda: retiros(usuario, alumno, filtros),
    }
    secciones = []
    for clave, titulo, icono, centro, (x, y, ancho, alto) in SECCIONES:
        seccion = _segura(constructores[clave], clave, titulo, icono)
        seccion.trazo = _segmento(centro)
        seccion.izquierda, seccion.arriba = 50 + (x - ancho / 2) / 2, 50 + (y - alto / 2) / 2   # de unidades a %
        seccion.ancho, seccion.alto = ancho / 2, alto / 2
        secciones.append(seccion)
    return secciones


def contexto(usuario, alumno, ciclo_pedido='', periodo_pedido='', seccion_pedida=''):
    filtros = filtros_de(alumno, ciclo_pedido, periodo_pedido)
    secciones = secciones_de(usuario, alumno, filtros)
    claves = [s.clave for s in secciones]
    return {
        'alumno': alumno, 'filtros': filtros, 'secciones': secciones,
        'seccion_abierta': seccion_pedida if seccion_pedida in claves else '',
        'edad': texto_de_edad(alumno.fecha_nacimiento),
    }
