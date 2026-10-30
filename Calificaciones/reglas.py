"""Reglas del control de calificaciones: qué configuración usa cada materia, quién ve y captura qué, el guardado de
las capturas (validado celda por celda y con bitácora), las actividades, el cierre y la reapertura, y la copia de
configuraciones entre materias. Los números los calcula Calificaciones/calculo.py.

Decisiones (pedido del 2026-10-14):
- La configuración es de la materia en un ciclo; un periodo puede tener su propia versión. Una versión nueva, o una
  copia, solo se aplica a un alcance sin capturas: nunca cambia en silencio lo que ya se calificó con otra.
- Las actas cerradas guardan la configuración y los resultados que se usaron (`configuracion_cerrada`,
  `resultados_cerrados`): editar después la configuración no las altera.
- Se captura mientras el periodo de evaluación del nivel está abierto (Alumnos/periodos.py), en el ciclo actual y con
  el acta en captura.
- Las faltas se toman de la asistencia por materia (sin justificar o todas, según la configuración) o se capturan a
  mano si así se configura; nunca se capturan dos veces.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q
from django.utils import timezone

from Alumnos.academico import ciclo_actual
from Alumnos.asistencia_docente import asignaciones_del_ciclo, asignaciones_del_profesor, inscripciones_de
from Alumnos.asistencias import con_justificada_materia, sin_dias_suspendidos
from Alumnos.clases import lista_de
from Alumnos.models import AsistenciaMateria, CicloEscolar, Inscripcion, MateriaGrado, Periodo
from Alumnos.periodos import periodos_para_grado
from Usuarios.docentes import profesor_de

from . import calculo
from .models import (
    ActaCalificaciones,
    Actividad,
    AjusteDelEstudiante,
    CalificacionActividad,
    CalificacionRubro,
    CambioCalificacion,
    CambioConfiguracion,
    ConfiguracionEvaluacion,
    Rubro,
)

CAPTURAR, VER_TODAS, GESTIONAR_TODAS = 'Calificaciones.capturar', 'Calificaciones.ver_todas', 'Calificaciones.gestionar_todas'
CERRAR, REABRIR = 'Calificaciones.cerrar', 'Calificaciones.reabrir'
ENTRAR = (CAPTURAR, VER_TODAS, GESTIONAR_TODAS)
VER_CONFIG = 'Calificaciones.view_configuracionevaluacion'
CREAR_CONFIG = 'Calificaciones.add_configuracionevaluacion'
CAMBIAR_CONFIG = 'Calificaciones.change_configuracionevaluacion'

CIEN = Decimal('100')
# Configuración inicial de referencia (el formato GeneralSecundaria.xlsx; su encabezado dice «Procedimientos 30 %»,
# pero sus fórmulas usan 50 %: se usa 50 %)
INICIAL = (
    ('Actitudes / Conducta', Decimal('20'), Rubro.DIRECTA),
    ('Procedimientos', Decimal('50'), Rubro.PROCEDIMIENTOS),
    ('Conocimientos / Exámenes', Decimal('30'), Rubro.EXAMENES),
)
SIN_CALIFICAR, EN_CAPTURA, CERRADO = 'SIN_CALIFICAR', 'EN_CAPTURA', 'CERRADO'
ESTADOS_DE_ESTUDIANTE = {SIN_CALIFICAR: 'Sin calificar', EN_CAPTURA: 'En captura', CERRADO: 'Cerrado'}
MAXIMO_FALTAS = 999


class CapturaRechazada(Exception):
    """No se pudo hacer lo pedido: `mensaje` para la persona."""

    def __init__(self, mensaje):
        super().__init__(mensaje)
        self.mensaje = mensaje


def numero(valor):
    """Un Decimal como texto corto: 8.5, 10, 9.25 (sin ceros de más); '' si es None."""
    if valor is None:
        return ''
    texto = f'{valor:.2f}'
    return texto.rstrip('0').rstrip('.') if '.' in texto else texto


def dos_decimales(valor):
    return '' if valor is None else f'{valor:.2f}'


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
def nivel_de_materia(materia, ciclo):
    """El nivel de la materia: el de su grado o, si no lo tiene registrado, el de los grupos que la llevan en el ciclo."""
    if materia.grado_id:
        return materia.grado.nivel
    return MateriaGrado.objects.filter(materia=materia, ciclo=ciclo).values_list('grado__nivel', flat=True).first()


def configuracion_de(materia, ciclo, periodo=None):
    """La que usa la materia en ese periodo: la versión del periodo si existe; si no, la del ciclo (o None)."""
    configuraciones = ConfiguracionEvaluacion.objects.filter(materia=materia, ciclo=ciclo)
    if periodo is not None:
        propia = configuraciones.filter(periodo=periodo).first()
        if propia is not None:
            return propia
    return configuraciones.filter(periodo__isnull=True).first()


def rubros_activos(configuracion):
    return [r for r in configuracion.rubros.all() if r.activo] if configuracion else []


def suma_de(rubros):
    return sum((r.porcentaje for r in rubros if r.activo), Decimal('0'))


def problemas_para_activar(configuracion, rubros=None):
    """Por qué la configuración no puede estar activa (lista vacía si puede)."""
    rubros = list(configuracion.rubros.all()) if rubros is None else rubros
    activos = [r for r in rubros if r.activo]
    problemas = []
    if not activos:
        problemas.append('No tiene rubros activos.')
    suma = suma_de(activos)
    if activos and suma != CIEN:
        problemas.append(f'Los rubros activos suman {numero(suma)} %: deben sumar exactamente 100 %.')
    if any(r.porcentaje <= 0 for r in activos):
        problemas.append('Cada rubro activo debe valer más de 0 %.')
    return problemas


def reglas_de(configuracion):
    c = configuracion
    return calculo.Reglas(
        penalizar_faltas=c.penalizar_faltas, faltas_por_bloque=c.faltas_por_bloque, puntos_por_bloque=c.puntos_por_bloque,
        punto_academia=c.punto_academia, valor_punto_academia=c.valor_punto_academia, limite_maximo=c.limite_maximo,
        limite_minimo=c.limite_minimo if c.usar_limite_minimo else None,
    )


def foto_de_configuracion(configuracion):
    """La configuración como datos (para guardarla en un acta cerrada y para la vista previa de una copia)."""
    c = configuracion
    return {
        'id': c.pk, 'materia': str(c.materia), 'ciclo': str(c.ciclo), 'alcance': c.alcance, 'estado': c.estado,
        'rubros': [
            {'id': r.pk, 'nombre': r.nombre, 'porcentaje': str(r.porcentaje), 'tipo': r.tipo, 'orden': r.orden}
            for r in rubros_activos(c)
        ],
        'reglas': {
            'penalizar_faltas': c.penalizar_faltas, 'faltas_por_bloque': c.faltas_por_bloque, 'puntos_por_bloque': str(c.puntos_por_bloque),
            'origen_faltas': c.origen_faltas, 'punto_academia': c.punto_academia, 'valor_punto_academia': str(c.valor_punto_academia),
            'limite_maximo': str(c.limite_maximo), 'usar_limite_minimo': c.usar_limite_minimo, 'limite_minimo': str(c.limite_minimo),
        },
    }


def describir_reglas(reglas):
    """Las reglas adicionales en palabras (de una configuración o de su foto)."""
    r = reglas if isinstance(reglas, dict) else foto_de_configuracion(reglas)['reglas']
    origen = dict(ConfiguracionEvaluacion.ORIGENES_DE_FALTAS).get(r['origen_faltas'], r['origen_faltas'])
    lineas = []
    if r['penalizar_faltas']:
        lineas.append(f"Descuenta {numero(Decimal(r['puntos_por_bloque']))} punto(s) por cada {r['faltas_por_bloque']} faltas completas. Cuentan: {origen.lower()}.")
    else:
        lineas.append('No descuenta puntos por faltas.')
    lineas.append(f"Punto de academia: suma {numero(Decimal(r['valor_punto_academia']))} si está otorgado." if r['punto_academia'] else 'Sin punto de academia.')
    lineas.append(f"Calificación máxima: {numero(Decimal(r['limite_maximo']))}.")
    lineas.append(f"Calificación mínima: {numero(Decimal(r['limite_minimo']))}." if r['usar_limite_minimo']
                  else 'Sin calificación mínima (como el formato: el resultado puede quedar debajo de 0).')
    return lineas


def registrar_cambio_de_configuracion(configuracion, usuario, descripcion, cambios=()):
    CambioConfiguracion.objects.create(configuracion=configuracion, usuario=usuario, descripcion=descripcion, cambios=list(cambios))


@transaction.atomic
def crear_inicial(materia, ciclo, usuario, periodo=None):
    """La configuración de referencia (20 % conducta directa, 50 % procedimientos, 30 % exámenes), activa."""
    if ConfiguracionEvaluacion.objects.filter(materia=materia, ciclo=ciclo, periodo=periodo).exists():
        raise CapturaRechazada('Esa materia ya tiene configuración para ese alcance.')
    _exigir_semestre_abierto(materia, ciclo)
    configuracion = ConfiguracionEvaluacion.objects.create(
        materia=materia, ciclo=ciclo, periodo=periodo, estado=ConfiguracionEvaluacion.ACTIVA, modificado_por=usuario,
    )
    for orden, (nombre, porcentaje, tipo) in enumerate(INICIAL, start=1):
        Rubro.objects.create(configuracion=configuracion, nombre=nombre, porcentaje=porcentaje, tipo=tipo, orden=orden)
    registrar_cambio_de_configuracion(configuracion, usuario, 'Creó la configuración de referencia (20 % / 50 % / 30 %).')
    return configuracion


def actas_que_usan(configuracion):
    """Las actas de la materia que calculan con esta configuración: la del periodo, las de ese periodo; la del ciclo,
    las de los periodos sin versión propia."""
    actas = ActaCalificaciones.objects.filter(asignacion__materia=configuracion.materia, asignacion__ciclo=configuracion.ciclo)
    if configuracion.periodo_id:
        return actas.filter(periodo=configuracion.periodo_id)
    con_version = ConfiguracionEvaluacion.objects.filter(
        materia=configuracion.materia, ciclo=configuracion.ciclo, periodo__isnull=False,
    ).values('periodo')
    return actas.exclude(periodo__in=con_version)


def tiene_capturas(actas):
    """¿Alguna de esas actas ya tiene actividades, calificaciones o ajustes capturados?"""
    return (
        Actividad.objects.filter(acta__in=actas).exists()
        or CalificacionRubro.objects.filter(acta__in=actas).exists()
        or AjusteDelEstudiante.objects.filter(acta__in=actas).filter(Q(punto_academia=True) | Q(faltas_manuales__isnull=False)).exists()
    )


def en_uso(configuracion):
    return tiene_capturas(actas_que_usan(configuracion))


def actas_de_periodo(materia, ciclo, periodo):
    return ActaCalificaciones.objects.filter(asignacion__materia=materia, asignacion__ciclo=ciclo, periodo=periodo)


def periodo_tiene_capturas(materia, ciclo, periodo):
    return tiene_capturas(actas_de_periodo(materia, ciclo, periodo))


def rubro_en_uso(rubro):
    return rubro.pk is not None and (rubro.actividades.exists() or rubro.calificaciones_directas.exists())


_CAMPOS_DE_REGLAS = (
    ('penalizar_faltas', 'Descontar por faltas'), ('faltas_por_bloque', 'Faltas para descontar'),
    ('puntos_por_bloque', 'Puntos que se descuentan'), ('origen_faltas', 'Faltas que cuentan'),
    ('punto_academia', 'Punto de academia'), ('valor_punto_academia', 'Valor del punto de academia'),
    ('limite_maximo', 'Calificación máxima'), ('usar_limite_minimo', 'Calificación mínima'), ('limite_minimo', 'Valor mínimo'),
)


def _texto(valor):
    if isinstance(valor, bool):
        return 'Sí' if valor else 'No'
    if isinstance(valor, Decimal):
        return numero(valor)
    return str(valor)


@transaction.atomic
def guardar_configuracion(configuracion, reglas, rubros, activar, usuario):
    """Guarda las reglas (dict con los campos de `_CAMPOS_DE_REGLAS`) y los rubros: [{'pk', 'nombre', 'porcentaje',
    'tipo', 'activo', 'orden', 'eliminar'}]. Un rubro con capturas no se elimina ni cambia de tipo (se desactiva).
    Con `activar` queda activa si la suma es 100 %; si no, borrador. Devuelve los problemas que impidieron activarla."""
    _exigir_semestre_abierto(configuracion.materia, configuracion.ciclo)
    cambios = []
    for campo, nombre in _CAMPOS_DE_REGLAS:
        antes, despues = getattr(configuracion, campo), reglas[campo]
        if antes != despues:
            cambios.append([nombre, _texto(antes), _texto(despues)])
            setattr(configuracion, campo, despues)

    existentes = {r.pk: r for r in configuracion.rubros.all()}
    quedan = []
    for datos in sorted(rubros, key=lambda d: (d['orden'], d.get('pk') or 0)):
        rubro = existentes.get(datos.get('pk')) if datos.get('pk') else None
        if datos.get('pk') and rubro is None:
            raise CapturaRechazada('Uno de los rubros ya no existe. Recarga la página.')
        if datos.get('eliminar'):
            if rubro is None:
                continue
            if rubro_en_uso(rubro):
                raise CapturaRechazada(f'«{rubro.nombre}» ya tiene calificaciones o actividades: no se elimina, desactívalo.')
            cambios.append(['Rubro eliminado', str(rubro), ''])
            rubro.delete()
            continue
        if rubro is None:
            rubro = Rubro(configuracion=configuracion)
            cambios.append(['Rubro nuevo', '', f"{datos['nombre']} ({numero(datos['porcentaje'])} %)"])
        else:
            if rubro.tipo != datos['tipo'] and rubro_en_uso(rubro):
                raise CapturaRechazada(f'«{rubro.nombre}» ya tiene calificaciones o actividades: no cambia de tipo de captura.')
            for campo, nombre in (('nombre', 'Nombre'), ('porcentaje', 'Porcentaje'), ('tipo', 'Tipo'), ('activo', 'Activo')):
                if getattr(rubro, campo) != datos[campo]:
                    cambios.append([f'{rubro.nombre} · {nombre}', _texto(getattr(rubro, campo)), _texto(datos[campo])])
        rubro.nombre, rubro.porcentaje, rubro.tipo, rubro.activo = datos['nombre'], datos['porcentaje'], datos['tipo'], datos['activo']
        quedan.append(rubro)
    for orden, rubro in enumerate(quedan, start=1):
        rubro.orden = orden
        rubro.save()

    problemas = problemas_para_activar(configuracion, quedan)
    estado = ConfiguracionEvaluacion.ACTIVA if activar and not problemas else ConfiguracionEvaluacion.BORRADOR
    if estado != configuracion.estado:
        cambios.append(['Estado', configuracion.get_estado_display(), dict(ConfiguracionEvaluacion.ESTADOS)[estado]])
    configuracion.estado = estado
    configuracion.modificado_por = usuario
    configuracion.save()
    if cambios:
        registrar_cambio_de_configuracion(configuracion, usuario, 'Editó la configuración.', cambios)
    return problemas if activar else []


def _exigir_semestre_abierto(materia, ciclo):
    from .semestres import bloqueo_de_configuracion
    bloqueo = bloqueo_de_configuracion(materia, ciclo)
    if bloqueo:
        raise CapturaRechazada(bloqueo)


def _copiar_en(destino, origen, incluir_reglas):
    for rubro in origen.rubros.all():
        Rubro.objects.create(configuracion=destino, nombre=rubro.nombre, porcentaje=rubro.porcentaje, tipo=rubro.tipo,
                             orden=rubro.orden, activo=rubro.activo)
    if incluir_reglas:
        for campo, _ in _CAMPOS_DE_REGLAS:
            setattr(destino, campo, getattr(origen, campo))


@transaction.atomic
def nueva_version(base, periodo, usuario):
    """Una versión de la configuración solo para ese periodo, igual a la del ciclo para empezar. No se crea si en ese
    periodo ya se capturó con la del ciclo (sus calificaciones cambiarían de rubros)."""
    if base.periodo_id:
        raise CapturaRechazada('Las versiones se crean a partir de la configuración del ciclo.')
    _exigir_semestre_abierto(base.materia, base.ciclo)
    if periodo.ciclo_id != base.ciclo_id or periodo.nivel != nivel_de_materia(base.materia, base.ciclo):
        raise CapturaRechazada('Ese periodo no es del ciclo ni del nivel de la materia.')
    if ConfiguracionEvaluacion.objects.filter(materia=base.materia, ciclo=base.ciclo, periodo=periodo).exists():
        raise CapturaRechazada(f'{periodo.nombre} ya tiene su propia versión.')
    if periodo_tiene_capturas(base.materia, base.ciclo, periodo):
        raise CapturaRechazada(f'En {periodo.nombre} ya hay calificaciones capturadas con la configuración del ciclo: '
                               'una versión propia cambiaría sus resultados. Edita la del ciclo o elige otro periodo.')
    version = ConfiguracionEvaluacion.objects.create(materia=base.materia, ciclo=base.ciclo, periodo=periodo, estado=base.estado,
                                                     modificado_por=usuario, copiada_de=f'Configuración del ciclo {base.ciclo}')
    _copiar_en(version, base, incluir_reglas=True)
    version.save()
    registrar_cambio_de_configuracion(version, usuario, f'Creó la versión de {periodo.nombre} a partir de la del ciclo.')
    return version


def revisar_copia(origen, materia, ciclo, periodo):
    """Qué pasaría al copiar `origen` a la materia (en ese ciclo y periodo, o en todo el ciclo si `periodo` es None):
    {'existente', 'reemplaza', 'bloqueo'}. Si el destino ya tiene capturas con su configuración, no se reemplaza."""
    existente = ConfiguracionEvaluacion.objects.filter(materia=materia, ciclo=ciclo, periodo=periodo).first()
    bloqueo = ''
    if origen.materia_id == materia.pk and origen.ciclo_id == ciclo.pk and origen.periodo_id == (periodo.pk if periodo else None):
        bloqueo = 'El origen y el destino son la misma configuración.'
    elif periodo is not None and periodo.ciclo_id != ciclo.pk:
        bloqueo = 'Ese periodo no es del ciclo elegido.'
    elif existente is not None and en_uso(existente):
        bloqueo = ('La materia de destino ya tiene calificaciones capturadas con esa configuración: no se reemplaza para no '
                   'cambiar sus resultados. Aplica la copia a un periodo sin capturas.')
    elif existente is None and periodo is not None and periodo_tiene_capturas(materia, ciclo, periodo):
        bloqueo = (f'En {periodo.nombre} ya hay calificaciones capturadas con la configuración del ciclo: no se cambia. '
                   'Elige un periodo sin capturas.')
    return {'existente': existente, 'reemplaza': existente is not None, 'bloqueo': bloqueo}


@transaction.atomic
def copiar(origen, materia, ciclo, periodo, incluir_reglas, usuario):
    """Copia rubros y porcentajes (y, si se pide, las reglas adicionales) de `origen` a la materia: una copia
    independiente (cambiar después el origen no la afecta). Nunca copia estudiantes, actividades ni calificaciones."""
    revision = revisar_copia(origen, materia, ciclo, periodo)
    if revision['bloqueo']:
        raise CapturaRechazada(revision['bloqueo'])
    _exigir_semestre_abierto(materia, ciclo)
    destino = revision['existente']
    if destino is None:
        destino = ConfiguracionEvaluacion(materia=materia, ciclo=ciclo, periodo=periodo)
    else:
        destino.rubros.all().delete()
    destino.estado = origen.estado if not problemas_para_activar(origen) else ConfiguracionEvaluacion.BORRADOR
    destino.copiada_de = f'{origen.materia} · {origen.ciclo} · {origen.alcance} (copiada el {timezone.localdate():%d/%m/%Y})'
    destino.modificado_por = usuario
    destino.save()
    _copiar_en(destino, origen, incluir_reglas)
    destino.save()
    registrar_cambio_de_configuracion(
        destino, usuario,
        f"{'Reemplazó' if revision['reemplaza'] else 'Creó'} la configuración copiando {'rubros, porcentajes y reglas' if incluir_reglas else 'rubros y porcentajes'} "
        f'de {origen.materia} ({origen.ciclo}, {origen.alcance}).',
    )
    return destino


# ---------------------------------------------------------------------------
# Quién ve y captura qué
# ---------------------------------------------------------------------------
def ve_todas(usuario):
    return usuario.has_perm(VER_TODAS) or usuario.has_perm(GESTIONAR_TODAS)


def asignaciones_para(usuario, ciclo=None):
    """Las materias (una por grupo) que la persona puede abrir: todas con «ver o gestionar todas»; si no, las suyas.
    Incluye las de grados ocultos cuyo semestre de bachillerato ya se cerró (registros y extraordinarios)."""
    from .semestres import grados_de_semestres_cerrados
    conservar = grados_de_semestres_cerrados(ciclo or ciclo_actual())
    if ve_todas(usuario):
        return asignaciones_del_ciclo(ciclo, conservar)
    if usuario.has_perm(CAPTURAR):
        return asignaciones_del_profesor(profesor_de(usuario), ciclo, conservar)
    return MateriaGrado.objects.none()


def es_suya(usuario, asignacion):
    profesor = profesor_de(usuario)
    return profesor is not None and asignacion.profesor_id == profesor.pk


def puede_ver(usuario, asignacion):
    return ve_todas(usuario) or (usuario.has_perm(CAPTURAR) and es_suya(usuario, asignacion))


def puede_capturar(usuario, asignacion):
    return usuario.has_perm(GESTIONAR_TODAS) or (usuario.has_perm(CAPTURAR) and es_suya(usuario, asignacion))


def puede_cerrar(usuario, asignacion):
    return usuario.has_perm(CERRAR) and puede_capturar(usuario, asignacion)


def puede_reabrir(usuario, asignacion):
    return usuario.has_perm(REABRIR) and puede_ver(usuario, asignacion)


def periodos_de(asignacion):
    """Los periodos de la materia: los de su nivel (en preparatoria por semestres, los de su semestre). Los de un grupo
    de clase, solo los que tocan las fechas de su bloque."""
    periodos = list(periodos_para_grado(asignacion.ciclo, asignacion.grado))
    if asignacion.es_de_clase:
        bloque = asignacion.clase.bloque
        periodos = [p for p in periodos if p.fecha_inicio <= bloque.vigente_hasta and bloque.vigente_desde <= p.fecha_fin]
    return periodos


def periodo_sugerido(periodos, hoy=None):
    """El abierto hoy; si no hay, el último que ya empezó; si no, el primero."""
    hoy = hoy or timezone.localdate()
    abiertos = [p for p in periodos if p.estado_en(hoy) == Periodo.ABIERTO]
    if abiertos:
        return abiertos[0]
    empezados = [p for p in periodos if p.fecha_inicio <= hoy]
    return empezados[-1] if empezados else (periodos[0] if periodos else None)


def acta_para(asignacion, periodo):
    try:
        acta, _ = ActaCalificaciones.objects.get_or_create(asignacion=asignacion, periodo=periodo)
    except IntegrityError:   # dos pestañas a la vez
        acta = ActaCalificaciones.objects.get(asignacion=asignacion, periodo=periodo)
    return acta


def configuracion_del_acta(acta):
    return configuracion_de(acta.asignacion.materia, acta.asignacion.ciclo, acta.periodo)


def motivo_de_solo_lectura(acta, usuario, configuracion=None, hoy=None):
    """Por qué no se puede capturar en el acta (texto) o '' si se puede."""
    hoy = hoy or timezone.localdate()
    if not puede_capturar(usuario, acta.asignacion):
        return 'Solo consulta: no capturas las calificaciones de esta materia.'
    if acta.cerrada:
        return f'Las calificaciones de {acta.periodo.nombre} están cerradas.'
    from .semestres import bloqueo_de_captura
    bloqueo = bloqueo_de_captura(acta.periodo) or bloqueo_de_clase(acta.asignacion)
    if bloqueo:
        return bloqueo
    if not acta.asignacion.ciclo.activo:
        return f'El ciclo {acta.asignacion.ciclo} no es el ciclo actual: sus calificaciones son de solo lectura.'
    estado = acta.periodo.estado_en(hoy)
    if estado == Periodo.CERRADO:
        return f'{acta.periodo.nombre} está cerrado: no se capturan calificaciones.'
    if estado == Periodo.PROXIMO:
        return f'{acta.periodo.nombre} todavía no empieza (se abre el {acta.periodo.fecha_inicio:%d/%m/%Y}).'
    configuracion = configuracion if configuracion is not None else configuracion_del_acta(acta)
    if configuracion is None:
        return 'La materia todavía no tiene configuración de calificaciones (rubros y porcentajes).'
    return ''


def bloque_de_clase(asignacion):
    return asignacion.clase.bloque if asignacion.es_de_clase else None


def bloqueo_de_clase(asignacion):
    """Por qué no se captura en un grupo de clase: su bloque o la opción están desactivados ('' si se puede)."""
    if not asignacion.es_de_clase:
        return ''
    clase = asignacion.clase
    if not clase.bloque.activo:
        return f'El bloque {clase.bloque.nombre} no está activo: sus calificaciones se consultan, pero no se capturan.'
    if not clase.activa:
        return f'{clase.nombre} está desactivada: sus calificaciones se consultan, pero no se capturan.'
    return ''


# ---------------------------------------------------------------------------
# La tabla del acta: estudiantes, actividades, capturas y resultados
# ---------------------------------------------------------------------------
@dataclass
class Fila:
    inscripcion: object
    numero: int
    nombre: str
    directas: dict = field(default_factory=dict)       # id de rubro -> Decimal
    actividades: dict = field(default_factory=dict)    # id de actividad -> Decimal
    faltas_manuales: int = None
    faltas_asistencia: int = 0
    academia: bool = False
    resultado: object = None
    estado: str = SIN_CALIFICAR

    @property
    def estado_texto(self):
        return ESTADOS_DE_ESTUDIANTE[self.estado]

    @property
    def salio(self):
        """El último día que estuvo, si dejó este grupo de clase a mitad del periodo (no impide cerrar)."""
        return getattr(self.inscripcion, 'salio_el', None)


@dataclass
class Tabla:
    acta: object
    configuracion: object                 # la vigente (None si la materia no tiene); en un acta cerrada, la de la foto
    rubros: list                          # los que cuentan: activos de la configuración (o de la foto, si está cerrada)
    reglas: object                        # calculo.Reglas
    origen_faltas: str
    actividades: list                     # todas las del acta (también anuladas), en orden
    filas: list
    foto: dict = None                     # en un acta cerrada, lo que se usó al cerrar

    def rubros_de(self, tipo):
        return [r for r in self.rubros if r.tipo == tipo]

    def actividades_de(self, tipo):
        return [a for a in self.actividades if a.tipo == tipo]

    @property
    def faltas_manuales(self):
        return self.origen_faltas == ConfiguracionEvaluacion.MANUAL

    @property
    def con_academia(self):
        return self.reglas.punto_academia

    @property
    def directos(self):
        return [r for r in self.rubros if r.tipo == Rubro.DIRECTA]


def faltas_de_asistencia(acta, inscripciones, origen):
    """{id de inscripción: faltas} en la materia durante el periodo, según la asistencia por materia: sin justificar o
    todas (sin contar los días con suspensión autorizada del estudiante)."""
    if origen == ConfiguracionEvaluacion.MANUAL or not inscripciones:
        return {}
    periodo, ciclo = acta.periodo, acta.asignacion.ciclo
    desde, hasta = max(periodo.fecha_inicio, ciclo.fecha_inicio), min(periodo.fecha_fin, ciclo.fecha_fin)
    registros = sin_dias_suspendidos(AsistenciaMateria.objects.filter(
        materia_grado=acta.asignacion, inscripcion__in=inscripciones, estado='FALTA', fecha__range=(desde, hasta),
    ))
    if origen == ConfiguracionEvaluacion.SIN_JUSTIFICAR:
        registros = con_justificada_materia(registros).filter(justificada=False)
    return dict(registros.order_by().values_list('inscripcion_id').annotate(total=Count('pk')))


def _rubros_de_calculo(rubros):
    return [calculo.RubroDeCalculo(clave=str(r.pk), nombre=r.nombre, porcentaje=r.porcentaje, tipo=r.tipo) for r in rubros]


@dataclass(frozen=True)
class _RubroDeFoto:
    pk: int
    nombre: str
    porcentaje: Decimal
    tipo: str
    activo: bool = True

    def get_tipo_display(self):
        return dict(Rubro.TIPOS).get(self.tipo, self.tipo)


def _reglas_de_foto(reglas):
    return calculo.Reglas(
        penalizar_faltas=reglas['penalizar_faltas'], faltas_por_bloque=reglas['faltas_por_bloque'],
        puntos_por_bloque=Decimal(reglas['puntos_por_bloque']), punto_academia=reglas['punto_academia'],
        valor_punto_academia=Decimal(reglas['valor_punto_academia']), limite_maximo=Decimal(reglas['limite_maximo']),
        limite_minimo=Decimal(reglas['limite_minimo']) if reglas['usar_limite_minimo'] else None,
    )


def estudiantes_de(acta):
    """Los estudiantes del grupo con su número de lista (orden alfabético por apellidos, como la lista del grupo).
    También los que ya pasaron al semestre siguiente: estas calificaciones son de su semestre. En un grupo de clase, los
    integrantes del periodo: quien lo dejó a la mitad sale marcado (`salio_el`) y no impide cerrar el acta."""
    asignacion, periodo = acta.asignacion, acta.periodo
    desde, hasta = max(periodo.fecha_inicio, asignacion.ciclo.fecha_inicio), min(periodo.fecha_fin, asignacion.ciclo.fecha_fin)
    inscripciones = list(inscripciones_de(asignacion, con_concluidas=True, desde=desde, hasta=hasta))
    lista = lista_de(asignacion, desde, hasta)
    if lista.tramos:
        for inscripcion in inscripciones:
            inscripcion.salio_el = lista.salida(inscripcion.pk, hasta)
    return inscripciones


def tabla(acta, inscripciones=None):
    """Todo lo que muestran las pestañas del acta, ya calculado. En un acta cerrada, los resultados son los guardados al
    cerrar (no se recalculan con la configuración de hoy)."""
    inscripciones = estudiantes_de(acta) if inscripciones is None else inscripciones
    foto = acta.configuracion_cerrada if acta.cerrada and acta.configuracion_cerrada else None
    if foto:
        configuracion = None
        rubros = [_RubroDeFoto(r['id'], r['nombre'], Decimal(r['porcentaje']), r['tipo']) for r in foto['rubros']]
        reglas, origen = _reglas_de_foto(foto['reglas']), foto['reglas']['origen_faltas']
    else:
        configuracion = configuracion_del_acta(acta)
        rubros = rubros_activos(configuracion)
        reglas = reglas_de(configuracion) if configuracion else calculo.Reglas()
        origen = configuracion.origen_faltas if configuracion else ConfiguracionEvaluacion.SIN_JUSTIFICAR

    actividades = list(acta.actividades.select_related('rubro').order_by('tipo', 'orden', 'fecha', 'pk'))
    filas = {i.pk: Fila(inscripcion=i, numero=n, nombre=str(i.alumno)) for n, i in enumerate(inscripciones, start=1)}
    for c in CalificacionActividad.objects.filter(actividad__acta=acta, inscripcion__in=filas):
        filas[c.inscripcion_id].actividades[c.actividad_id] = c.valor
    for c in CalificacionRubro.objects.filter(acta=acta, inscripcion__in=filas):
        filas[c.inscripcion_id].directas[c.rubro_id] = c.valor
    for a in AjusteDelEstudiante.objects.filter(acta=acta, inscripcion__in=filas):
        filas[a.inscripcion_id].faltas_manuales, filas[a.inscripcion_id].academia = a.faltas_manuales, a.punto_academia
    for inscripcion_id, total in faltas_de_asistencia(acta, list(filas), origen).items():
        filas[inscripcion_id].faltas_asistencia = total

    resultado = Tabla(acta=acta, configuracion=configuracion, rubros=rubros, reglas=reglas, origen_faltas=origen,
                      actividades=actividades, filas=list(filas.values()), foto=foto)
    guardados = {r['inscripcion']: r for r in acta.resultados_cerrados} if foto else {}
    for fila in resultado.filas:
        if foto and fila.inscripcion.pk in guardados:
            fila.resultado = _resultado_de_foto(guardados[fila.inscripcion.pk], rubros)
            fila.estado = CERRADO
        else:
            fila.resultado = calcular_fila(resultado, fila)
            fila.estado = CERRADO if acta.cerrada else (SIN_CALIFICAR if fila.resultado.sin_capturas else EN_CAPTURA)
    return resultado


def faltas_consideradas(tabla_, fila):
    if tabla_.faltas_manuales:
        return fila.faltas_manuales or 0
    return fila.faltas_asistencia


def calcular_fila(tabla_, fila):
    vigentes = [a for a in tabla_.actividades if not a.anulada]
    claves = {r.pk for r in tabla_.rubros}
    capturas, pendientes = {}, 0
    for rubro in tabla_.rubros:
        if rubro.tipo == Rubro.DIRECTA:
            capturas[str(rubro.pk)] = fila.directas.get(rubro.pk)
        else:
            capturas[str(rubro.pk)] = [fila.actividades[a.pk] for a in vigentes if a.rubro_id == rubro.pk and a.pk in fila.actividades]
    for actividad in vigentes:
        if actividad.rubro_id in claves and actividad.pk not in fila.actividades:
            pendientes += 1
    return calculo.calcular(_rubros_de_calculo(tabla_.rubros), tabla_.reglas, capturas, faltas=faltas_consideradas(tabla_, fila),
                            academia=fila.academia, pendientes=pendientes)


def _resultado_de_foto(datos, rubros):
    decimal = lambda v: Decimal(v) if v not in (None, '') else None   # noqa: E731
    resultado = calculo.Resultado(
        faltas=datos['faltas'], descuento=Decimal(datos['descuento']), bonificacion=Decimal(datos['bonificacion']),
        base=decimal(datos['base']), final=decimal(datos['final']), pendientes=datos.get('pendientes', 0), tope=datos.get('tope', ''),
    )
    for rubro in rubros:
        r = datos['rubros'].get(str(rubro.pk), {})
        resultado.rubros[str(rubro.pk)] = calculo.ResultadoDeRubro(valor=decimal(r.get('valor')), aportacion=decimal(r.get('aportacion')),
                                                                  capturas=r.get('capturas', 0))
    return resultado


def _foto_de_resultado(fila):
    r = fila.resultado
    return {
        'inscripcion': fila.inscripcion.pk, 'numero': fila.numero, 'nombre': fila.nombre, 'faltas': r.faltas,
        'descuento': str(r.descuento), 'bonificacion': str(r.bonificacion), 'base': dos_decimales(r.base), 'final': dos_decimales(r.final),
        'pendientes': r.pendientes, 'tope': r.tope, 'academia': fila.academia,
        'rubros': {clave: {'valor': dos_decimales(x.valor), 'aportacion': dos_decimales(x.aportacion), 'capturas': x.capturas}
                   for clave, x in r.rubros.items()},
    }


# ---------------------------------------------------------------------------
# Guardar capturas (celda por celda, con bitácora)
# ---------------------------------------------------------------------------
def leer_calificacion(texto):
    """'' -> None (pendiente); '8.5' o '8,5' -> Decimal('8.50'). Lanza CapturaRechazada si no es de 0 a 10."""
    texto = (texto or '').strip().replace(',', '.')
    if texto == '':
        return None
    try:
        valor = Decimal(texto)
    except InvalidOperation:
        raise CapturaRechazada('Escribe un número de 0 a 10.') from None
    if not valor.is_finite():
        raise CapturaRechazada('Escribe un número de 0 a 10.')
    if valor < 0 or valor > 10:
        raise CapturaRechazada('La calificación va de 0 a 10.')
    if valor != valor.quantize(Decimal('0.01')):
        raise CapturaRechazada('Usa como máximo dos decimales.')
    return valor.quantize(Decimal('0.01'))


def leer_faltas(texto):
    texto = (texto or '').strip()
    if texto == '':
        return None
    if not texto.isdigit():
        raise CapturaRechazada('Las faltas son un número entero de 0 en adelante.')
    valor = int(texto)
    if valor > MAXIMO_FALTAS:
        raise CapturaRechazada(f'Revisa el número de faltas (máximo {MAXIMO_FALTAS}).')
    return valor


def leer_si_no(texto):
    texto = (texto or '').strip().lower()
    if texto in ('1', 'true', 'si', 'sí', 'on'):
        return True
    if texto in ('0', 'false', 'no', ''):
        return False
    raise CapturaRechazada('Valor no válido.')


def _iguales(actual, anterior_texto, lector):
    try:
        return actual == lector(anterior_texto)
    except CapturaRechazada:
        return False


def _guardar_celda(acta, tabla_, cambio, usuario, inscripciones):
    """Aplica un cambio {'tipo', 'id', 'inscripcion', 'valor', 'anterior'} y devuelve el valor guardado (texto).
    Si la celda ya tiene el valor nuevo, no hace nada (reintentar no duplica). Si alguien la cambió mientras tanto
    (ya no tiene el valor `anterior`), se rechaza."""
    tipo = cambio.get('tipo')
    inscripcion = inscripciones.get(str(cambio.get('inscripcion')))
    if inscripcion is None:
        raise CapturaRechazada('Ese estudiante no está en este grupo.')
    texto_nuevo = cambio.get('valor', '')
    if tipo == 'actividad':
        actividad = next((a for a in tabla_.actividades if str(a.pk) == str(cambio.get('id'))), None)
        if actividad is None:
            raise CapturaRechazada('Esa actividad ya no existe.')
        if actividad.anulada:
            raise CapturaRechazada('Esa actividad está anulada: no se califica.')
        nuevo = leer_calificacion(texto_nuevo)
        registro = CalificacionActividad.objects.select_for_update().filter(actividad=actividad, inscripcion=inscripcion).first()
        actual = registro.valor if registro else None
        que = f'{actividad.get_tipo_display()}: {actividad.nombre}'
        lector, mostrar = leer_calificacion, numero
    elif tipo == 'rubro':
        rubro = next((r for r in tabla_.directos if str(r.pk) == str(cambio.get('id'))), None)
        if rubro is None:
            raise CapturaRechazada('Ese rubro no es de captura directa en esta materia.')
        nuevo = leer_calificacion(texto_nuevo)
        registro = CalificacionRubro.objects.select_for_update().filter(acta=acta, rubro=rubro, inscripcion=inscripcion).first()
        actual = registro.valor if registro else None
        que, lector, mostrar = rubro.nombre, leer_calificacion, numero
    elif tipo in ('faltas', 'academia'):
        if tipo == 'faltas' and not tabla_.faltas_manuales:
            raise CapturaRechazada('Las faltas se toman de la asistencia: no se capturan aquí.')
        if tipo == 'academia' and not tabla_.con_academia:
            raise CapturaRechazada('Esta materia no usa punto de academia.')
        nuevo = leer_faltas(texto_nuevo) if tipo == 'faltas' else leer_si_no(texto_nuevo)
        registro = AjusteDelEstudiante.objects.select_for_update().filter(acta=acta, inscripcion=inscripcion).first()
        if tipo == 'faltas':
            actual, que, lector, mostrar = (registro.faltas_manuales if registro else None), 'Faltas (captura manual)', leer_faltas, lambda v: '' if v is None else str(v)
        else:
            actual, que, lector, mostrar = (registro.punto_academia if registro else False), 'Punto de academia', leer_si_no, lambda v: 'Otorgado' if v else 'No'
    else:
        raise CapturaRechazada('Cambio no válido.')

    crudo = (lambda v: '1' if v else '0') if tipo == 'academia' else mostrar   # lo que vuelve a la celda
    if actual == nuevo:
        return crudo(nuevo)   # ya estaba así (p. ej., un reintento)
    if 'anterior' in cambio and not _iguales(actual, cambio.get('anterior'), lector):
        raise CapturaRechazada(f'Alguien más la cambió mientras tanto (ahora es «{mostrar(actual) or "vacía"}»). Recarga para ver lo actual.')

    if tipo == 'actividad':
        if nuevo is None:
            registro.delete()
        elif registro:
            registro.valor, registro.modificado_por = nuevo, usuario
            registro.save(update_fields=['valor', 'modificado_por', 'modificado'])
        else:
            CalificacionActividad.objects.create(actividad=actividad, inscripcion=inscripcion, valor=nuevo, modificado_por=usuario)
    elif tipo == 'rubro':
        if nuevo is None:
            registro.delete()
        elif registro:
            registro.valor, registro.modificado_por = nuevo, usuario
            registro.save(update_fields=['valor', 'modificado_por', 'modificado'])
        else:
            CalificacionRubro.objects.create(acta=acta, rubro=rubro, inscripcion=inscripcion, valor=nuevo, modificado_por=usuario)
    else:
        registro = registro or AjusteDelEstudiante(acta=acta, inscripcion=inscripcion)
        if tipo == 'faltas':
            registro.faltas_manuales = nuevo
        else:
            registro.punto_academia = nuevo
        registro.modificado_por = usuario
        registro.save()
    CambioCalificacion.objects.create(acta=acta, accion=CambioCalificacion.CAPTURA, inscripcion=inscripcion, que=que,
                                      anterior=mostrar(actual), nuevo=mostrar(nuevo), usuario=usuario)
    return crudo(nuevo)


def guardar_capturas(acta, usuario, cambios):
    """Guarda una lista de cambios; cada celda se valida y se guarda por separado (un error no detiene a las demás).
    Devuelve ([{'clave', 'ok', 'valor' o 'error'}], tabla recalculada)."""
    motivo = motivo_de_solo_lectura(acta, usuario)
    if motivo:
        raise CapturaRechazada(motivo)
    inscripciones = {str(i.pk): i for i in estudiantes_de(acta)}
    tabla_ = tabla(acta, list(inscripciones.values()))
    resultados = []
    for cambio in cambios[:2000]:
        clave = cambio.get('clave', '')
        try:
            with transaction.atomic():
                valor = _guardar_celda(acta, tabla_, cambio, usuario, inscripciones)
            resultados.append({'clave': clave, 'ok': True, 'valor': valor})
        except CapturaRechazada as error:
            resultados.append({'clave': clave, 'ok': False, 'error': error.mensaje})
    return resultados, tabla(acta, list(inscripciones.values()))


# ---------------------------------------------------------------------------
# Actividades
# ---------------------------------------------------------------------------
def rubros_para_actividades(acta, tipo_de_actividad):
    """Los rubros activos de la configuración del acta en los que caben actividades de ese tipo."""
    tipo_de_rubro = Rubro.PROCEDIMIENTOS if tipo_de_actividad == Actividad.PROCEDIMIENTO else Rubro.EXAMENES
    return [r for r in rubros_activos(configuracion_del_acta(acta)) if r.tipo == tipo_de_rubro]


def _bitacora_de_actividad(actividad, accion, usuario, motivo='', anterior='', nuevo=''):
    CambioCalificacion.objects.create(acta=actividad.acta, accion=accion, que=f'{actividad.get_tipo_display()}: {actividad.nombre}',
                                      anterior=anterior[:60], nuevo=nuevo[:60], motivo=motivo, usuario=usuario)


@transaction.atomic
def crear_actividad(acta, datos, usuario):
    rubro = datos['rubro']
    siguiente = (acta.actividades.filter(tipo=Actividad.DEL_RUBRO[rubro.tipo]).aggregate(m=Max('orden'))['m'] or 0) + 1
    actividad = Actividad.objects.create(
        acta=acta, rubro=rubro, tipo=Actividad.DEL_RUBRO[rubro.tipo], nombre=datos['nombre'], descripcion=datos.get('descripcion', ''),
        fecha=datos['fecha'], orden=datos.get('orden') or siguiente, creada_por=usuario,
    )
    _bitacora_de_actividad(actividad, CambioCalificacion.ACTIVIDAD_NUEVA, usuario, nuevo=f'{actividad.fecha:%d/%m/%Y}')
    return actividad


@transaction.atomic
def editar_actividad(actividad, datos, usuario):
    antes = f'{actividad.nombre} ({actividad.fecha:%d/%m/%Y})'
    if datos['rubro'].pk != actividad.rubro_id and actividad.calificaciones.exists():
        raise CapturaRechazada('Ya tiene calificaciones: no se cambia de rubro.')
    actividad.nombre, actividad.descripcion, actividad.fecha, actividad.rubro = datos['nombre'], datos.get('descripcion', ''), datos['fecha'], datos['rubro']
    if datos.get('orden'):
        actividad.orden = datos['orden']
    actividad.save()
    _bitacora_de_actividad(actividad, CambioCalificacion.ACTIVIDAD_EDITADA, usuario, anterior=antes, nuevo=f'{actividad.nombre} ({actividad.fecha:%d/%m/%Y})')
    return actividad


@transaction.atomic
def anular_actividad(actividad, motivo, usuario):
    """Con calificaciones no se borra: se anula (deja de contar en el promedio y en lo pendiente) con motivo."""
    actividad.anulada, actividad.anulada_por, actividad.anulada_en, actividad.motivo_anulacion = True, usuario, timezone.now(), motivo
    actividad.save()
    _bitacora_de_actividad(actividad, CambioCalificacion.ACTIVIDAD_ANULADA, usuario, motivo=motivo,
                           anterior=f'{actividad.calificaciones.count()} calificaciones')


@transaction.atomic
def eliminar_actividad(actividad, usuario):
    """Solo sin calificaciones (si las tiene, se anula)."""
    if actividad.calificaciones.exists():
        raise CapturaRechazada('Ya tiene calificaciones: no se elimina, se anula con motivo.')
    _bitacora_de_actividad(actividad, CambioCalificacion.ACTIVIDAD_ELIMINADA, usuario)
    actividad.delete()


# ---------------------------------------------------------------------------
# Cierre y reapertura
# ---------------------------------------------------------------------------
def problemas_para_cerrar(acta, tabla_=None):
    """Lo que falta resolver para cerrar (lista vacía si se puede)."""
    if acta.cerrada:
        return ['Ya están cerradas.']
    configuracion = configuracion_del_acta(acta)
    if configuracion is None:
        return ['La materia no tiene configuración de calificaciones.']
    problemas = []
    if not configuracion.activa:
        problemas.append('La configuración de la materia es un borrador (sus rubros activos no suman 100 %): actívala en Ajustes › Calificaciones.')
    tabla_ = tabla_ or tabla(acta)
    if not tabla_.filas:
        problemas.append('El grupo no tiene estudiantes inscritos.')
    for rubro in tabla_.rubros:
        if rubro.tipo != Rubro.DIRECTA and not any(a.rubro_id == rubro.pk and not a.anulada for a in tabla_.actividades):
            problemas.append(f'«{rubro.nombre}» no tiene actividades vigentes.')
    sin_final = [f for f in tabla_.filas if not f.resultado.completo and not f.salio]
    if sin_final:
        problemas.append(f'{len(sin_final)} estudiante(s) sin calificación en algún rubro: ' + ', '.join(f'{f.numero}. {f.nombre}' for f in sin_final[:5])
                         + ('…' if len(sin_final) > 5 else '') + '.')
    pendientes = sum(f.resultado.pendientes for f in tabla_.filas if not f.salio)
    if pendientes:
        problemas.append(f'Hay {pendientes} calificación(es) pendiente(s) en actividades vigentes: captúralas (un cero también cuenta) o anula la actividad.')
    return problemas


@transaction.atomic
def cerrar(acta, usuario):
    acta = ActaCalificaciones.objects.select_for_update().get(pk=acta.pk)
    tabla_ = tabla(acta)
    problemas = problemas_para_cerrar(acta, tabla_)
    if problemas:
        raise CapturaRechazada(' '.join(problemas))
    acta.configuracion_cerrada = foto_de_configuracion(tabla_.configuracion)
    acta.resultados_cerrados = [_foto_de_resultado(f) for f in tabla_.filas]
    acta.estado, acta.cerrada_por, acta.cerrada_en = ActaCalificaciones.CERRADA, usuario, timezone.now()
    acta.save()
    CambioCalificacion.objects.create(acta=acta, accion=CambioCalificacion.CIERRE, que=f'Cierre de {acta.periodo.nombre}',
                                      nuevo='Cerrada', usuario=usuario,
                                      datos={'configuracion': acta.configuracion_cerrada.get('id'), 'estudiantes': len(acta.resultados_cerrados)})
    return acta


def bloqueo_de_reapertura(acta):
    """Por qué no se reabre el acta aunque se tenga permiso: su semestre de bachillerato está cerrado ('' si no)."""
    from .semestres import bloqueo_de_periodo
    if bloqueo_de_periodo(acta.periodo):
        return (f'{acta.periodo.nombre} es del {acta.periodo.semestre.en_frase}, que está cerrado: para corregir una calificación '
                'de periodo, primero se reabre el semestre (Ciclos escolares, con motivo).')
    return ''


@transaction.atomic
def reabrir(acta, motivo, usuario):
    acta = ActaCalificaciones.objects.select_for_update().get(pk=acta.pk)
    if not acta.cerrada:
        raise CapturaRechazada('No están cerradas.')
    bloqueo = bloqueo_de_reapertura(acta)
    if bloqueo:
        raise CapturaRechazada(bloqueo)
    CambioCalificacion.objects.create(
        acta=acta, accion=CambioCalificacion.REAPERTURA, que=f'Reapertura de {acta.periodo.nombre}', anterior='Cerrada', nuevo='En captura',
        motivo=motivo, usuario=usuario,
        datos={'cerrada_en': acta.cerrada_en.isoformat() if acta.cerrada_en else '', 'configuracion': acta.configuracion_cerrada,
               'resultados': acta.resultados_cerrados},
    )
    acta.estado, acta.configuracion_cerrada, acta.resultados_cerrados = ActaCalificaciones.EN_CAPTURA, {}, []
    acta.cerrada_por, acta.cerrada_en = None, None
    acta.save()
    return acta


@dataclass
class Movimientos:
    """El historial de movimientos de un acta reabierta (ver `historial_de_movimientos`)."""
    lista: list          # los más recientes primero (hasta el límite)
    total: int

    @property
    def hay_mas(self):
        return self.total > len(self.lista)


def historial_de_movimientos(acta, limite=200):
    """Desde la primera reapertura del acta (pedido del 2026-10-14): las reaperturas (usuario, fecha y motivo), cada
    calificación modificada (estudiante, rubro o actividad, valor anterior y nuevo, usuario y fecha), los cambios de
    actividades y los nuevos cierres, del más reciente al más antiguo. Es la bitácora del acta (`CambioCalificacion`),
    que no se edita ni se borra: se conserva entre reaperturas y después del cierre. None si nunca se ha reabierto."""
    primera = acta.cambios.filter(accion=CambioCalificacion.REAPERTURA).order_by('fecha', 'pk').first()
    if primera is None:
        return None
    desde = acta.cambios.filter(pk__gte=primera.pk)
    lista = list(desde.select_related('usuario', 'inscripcion__alumno').order_by('-fecha', '-pk')[:limite])
    return Movimientos(lista=lista, total=desde.count())


def ciclos_con_materias(usuario):
    """Los ciclos (del más reciente) en los que la persona tiene materias que ver."""
    if ve_todas(usuario):
        consulta = CicloEscolar.objects.filter(materias_grado__activa=True)
    else:
        profesor = profesor_de(usuario)
        if profesor is None or not usuario.has_perm(CAPTURAR):
            return []
        consulta = CicloEscolar.objects.filter(materias_grado__profesor=profesor, materias_grado__activa=True)
    return list(consulta.distinct().order_by('-fecha_inicio'))


def inscripcion_del_grupo(acta, pk):
    return Inscripcion.objects.filter(pk=pk, grupo=acta.asignacion.grupo, ciclo=acta.asignacion.ciclo).first()


def hoy():
    return timezone.localdate()


def fecha_en_periodo(fecha, periodo):
    return isinstance(fecha, date) and periodo.fecha_inicio <= fecha <= periodo.fecha_fin
