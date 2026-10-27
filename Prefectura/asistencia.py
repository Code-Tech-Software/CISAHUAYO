"""Asistencia para prefectura: la misma fuente de datos que la administración y los docentes (AsistenciaMateria,
AsistenciaGeneral y Justificacion), siempre dentro del alcance de la cuenta.

- Faltas y retardos: los del pase de lista por materia y los de la entrada al colegio. Se distinguen las **faltas por
  materia** (cada registro) de los **estudiantes con inasistencia** (cada estudiante una vez).
- Justificar: un motivo y un comprobante fotográfico cubren los registros elegidos (de un día o de un rango). Cada
  registro conserva su estado original (la falta sigue siendo falta) y queda vinculado a su justificación; todas las del
  mismo envío comparten su lote. Antes se muestran los registros afectados para confirmarlos. Revocar exige motivo.
- Accesos (MovimientoAcceso): retardos de ingreso, entradas posteriores y salidas anticipadas. Un retardo de ingreso
  cuenta como la entrada con retardo (pedido del 2026-10-14): deja la asistencia general en retardo y la primera clase
  del día en falta, como la pantalla de entrada; lo que el docente ya capturó en su pase de lista no se toca.
"""
import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone

from Alumnos.academico import ciclo_actual
from Alumnos.asistencias import (
    con_justificada_general,
    con_justificada_materia,
    fechas_sin_clases,
    fijar_asistencia_general,
    sin_dias_suspendidos,
)
from Alumnos.models import AsistenciaGeneral, AsistenciaMateria, CambioJustificacion, Justificacion

from .models import CambioAcceso, MovimientoAcceso

logger = logging.getLogger(__name__)
DIAS_MAXIMOS_POR_JUSTIFICACION = 31


class JustificacionRechazada(Exception):
    """No se guardó la justificación (mensaje para la persona)."""


# ---------------------------------------------------------------------------
# Los registros del alcance
# ---------------------------------------------------------------------------
def de_materias(alcance):
    """Los registros por materia del alcance, sin los días de una suspensión autorizada (no son faltas)."""
    return con_justificada_materia(sin_dias_suspendidos(alcance.filtrar(AsistenciaMateria.objects.all(), campo='inscripcion__alumno')))


def de_entrada(alcance):
    return con_justificada_general(sin_dias_suspendidos(alcance.filtrar(AsistenciaGeneral.objects.all(), campo='inscripcion__alumno')))


def accesos(alcance):
    return alcance.filtrar(MovimientoAcceso.objects.all())


def entraron_y_faltaron(registros):
    """De los registros por materia, las faltas que puso el pase de lista a quien sí registró su entrada al colegio ese
    día (presente o con retardo): puede haber salido sin permiso (pedido del 2026-10-27). No cuentan las faltas que pone
    el sistema por la hora de llegada ni los días con una salida anticipada registrada o un retiro confirmado."""
    from Retiros.models import RetiroEstudiante
    entro = AsistenciaGeneral.objects.filter(inscripcion=OuterRef('inscripcion'), fecha=OuterRef('fecha'), estado__in=('PRESENTE', 'RETARDO'))
    salio = MovimientoAcceso.objects.filter(
        inscripcion=OuterRef('inscripcion'), fecha=OuterRef('fecha'), tipo=MovimientoAcceso.SALIDA, anulado=False,
    )
    retirado = RetiroEstudiante.objects.filter(alumno=OuterRef('inscripcion__alumno'), fecha=OuterRef('fecha'), estado=RetiroEstudiante.RETIRADO)
    return registros.filter(estado='FALTA', origen='PASE').filter(Exists(entro)).exclude(Exists(salio)).exclude(Exists(retirado))


def del_dia(alcance, fecha):
    """Los indicadores de asistencia de un día, separando registros (faltas por materia) de estudiantes."""
    materias = de_materias(alcance).filter(fecha=fecha)
    entrada = de_entrada(alcance).filter(fecha=fecha)
    conteo = materias.aggregate(
        faltas=Count('pk', filter=Q(estado='FALTA')),
        faltas_sin_justificar=Count('pk', filter=Q(estado='FALTA', justificada=False)),
        retardos=Count('pk', filter=Q(estado='RETARDO')),
    )
    con_falta = set(materias.filter(estado='FALTA').values_list('inscripcion__alumno', flat=True))
    con_falta |= set(entrada.filter(estado='FALTA').values_list('inscripcion__alumno', flat=True))
    sin_entrar = entrada.filter(estado='FALTA').count()
    retardos_entrada = set(entrada.filter(estado='RETARDO').values_list('inscripcion__alumno', flat=True))
    movimientos = accesos(alcance).filter(fecha=fecha, anulado=False)
    retardos_entrada |= set(movimientos.filter(tipo=MovimientoAcceso.RETARDO).values_list('alumno', flat=True))
    por_tipo = dict(movimientos.order_by().values_list('tipo').annotate(total=Count('pk')))
    return {
        **conteo,
        'estudiantes_con_falta': len(con_falta),
        'entraron_y_faltaron': entraron_y_faltaron(materias).values('inscripcion__alumno').distinct().count(),
        'faltas_de_entrada': sin_entrar,
        'estudiantes_con_retardo_de_entrada': len(retardos_entrada),
        'accesos': {clave: por_tipo.get(clave, 0) for clave, _ in MovimientoAcceso.TIPOS},
        'accesos_total': sum(por_tipo.values()),
    }


# ---------------------------------------------------------------------------
# Justificar faltas y retardos
# ---------------------------------------------------------------------------
@dataclass
class Afectado:
    clave: str          # 'm-<id>' (por materia) o 'g-<id>' (entrada al colegio)
    fecha: object
    que: str            # la materia o «Entrada al colegio»
    estado: str         # 'FALTA' o 'RETARDO'
    registro: object

    @property
    def estado_display(self):
        return 'Falta' if self.estado == 'FALTA' else 'Retardo'

    def como_dict(self):
        return {'clave': self.clave, 'fecha': self.fecha.isoformat(), 'fecha_texto': f'{self.fecha:%d/%m/%Y}', 'que': self.que,
                'estado': self.estado_display}


def por_justificar(inscripcion, desde, hasta, estados=('FALTA',), con_entrada=True):
    """Los registros del estudiante (de esa inscripción) entre esas fechas que se pueden justificar: faltas o retardos
    sin una justificación vigente, fuera de los días sin clases. En orden de fecha."""
    sin_clases = fechas_sin_clases(desde, hasta, inscripcion.grado.nivel)
    afectados = []
    materias = (
        con_justificada_materia(sin_dias_suspendidos(AsistenciaMateria.objects.filter(inscripcion=inscripcion, fecha__range=(desde, hasta), estado__in=estados)))
        .filter(justificada=False).select_related('materia_grado__materia').order_by('fecha', 'materia_grado__materia__nombre')
    )
    afectados += [Afectado(f'm-{r.pk}', r.fecha, str(r.materia_grado.materia), r.estado, r) for r in materias if r.fecha not in sin_clases]
    if con_entrada:
        # Un día con otra justificación por día (aunque no cubra la entrada) no admite otra: se respeta la que hay
        con_justificacion_del_dia = set(
            Justificacion.objects.filter(inscripcion=inscripcion, activa=True, asistencia__isnull=True, fecha__range=(desde, hasta))
            .values_list('fecha', flat=True)
        )
        generales = sin_dias_suspendidos(AsistenciaGeneral.objects.filter(inscripcion=inscripcion, fecha__range=(desde, hasta), estado__in=estados)).order_by('fecha')
        afectados += [
            Afectado(f'g-{r.pk}', r.fecha, 'Entrada al colegio', r.estado, r) for r in generales
            if r.fecha not in sin_clases and r.fecha not in con_justificacion_del_dia
        ]
    return sorted(afectados, key=lambda a: (a.fecha, a.que != 'Entrada al colegio', a.que))


@transaction.atomic
def justificar(inscripcion, desde, hasta, estados, con_entrada, confirmados, motivo, comprobante, usuario):
    """Justifica los registros que la persona confirmó (sus claves). Si ya no coinciden con los que hay (alguien los
    cambió o justificó mientras tanto), no guarda nada. Devuelve (lote, registros justificados)."""
    afectados = por_justificar(inscripcion, desde, hasta, estados, con_entrada)
    if not afectados:
        raise JustificacionRechazada('No hay faltas ni retardos por justificar en esas fechas.')
    if {a.clave for a in afectados} != set(confirmados):
        raise JustificacionRechazada('Los registros por justificar cambiaron mientras llenabas el formulario: revisa la lista de nuevo y confírmala.')
    lote = uuid.uuid4()
    creadas, documento = [], None
    for afectado in afectados:
        es_entrada = afectado.clave.startswith('g-')
        justificacion = Justificacion(
            inscripcion=inscripcion, fecha=afectado.fecha, motivo=motivo, registrada_por=usuario, lote=lote,
            justifica_general=es_entrada, todas_materias=False, asistencia=None if es_entrada else afectado.registro,
        )
        if documento is None:
            justificacion.documento = comprobante
        else:
            justificacion.documento = documento   # el mismo comprobante (ya guardado) sirve para todos
        try:
            with transaction.atomic():
                justificacion.save()
        except IntegrityError:
            raise JustificacionRechazada('Alguno de esos registros ya tiene una justificación vigente: revisa la lista de nuevo.') from None
        except Exception:   # el almacenamiento de archivos no respondió
            logger.exception('No se pudo guardar el comprobante de la justificación')
            raise JustificacionRechazada('No se pudo guardar el comprobante. Inténtalo de nuevo: no se justificó nada.') from None
        documento = documento or justificacion.documento.name
        if not es_entrada:
            justificacion.materias.set([afectado.registro.materia_grado_id])
        CambioJustificacion.objects.create(justificacion=justificacion, accion=CambioJustificacion.CREADA, usuario=usuario, motivo=motivo)
        creadas.append(justificacion)
    return lote, creadas


def del_mismo_envio(justificacion):
    """Las justificaciones vigentes que se registraron junto con esta (su lote), o solo ella."""
    if justificacion.lote:
        return Justificacion.objects.filter(lote=justificacion.lote, activa=True)
    return Justificacion.objects.filter(pk=justificacion.pk, activa=True)


@transaction.atomic
def revocar(justificacion, motivo, usuario):
    """Revoca la justificación (y las de su mismo envío): dejan de cubrir los registros, que vuelven a contar sin
    justificar. No se borran: quedan con quién, cuándo y por qué. Devuelve cuántas se revocaron."""
    ahora = timezone.now()
    vigentes = list(del_mismo_envio(justificacion).select_for_update())
    for fila in vigentes:
        fila.activa, fila.revocada_por, fila.revocada_en, fila.motivo_revocacion = False, usuario, ahora, motivo
        fila.save(update_fields=['activa', 'revocada_por', 'revocada_en', 'motivo_revocacion', 'modificado'])
        CambioJustificacion.objects.create(justificacion=fila, accion=CambioJustificacion.REVOCADA, usuario=usuario, motivo=motivo)
    return len(vigentes)


# ---------------------------------------------------------------------------
# Accesos al colegio
# ---------------------------------------------------------------------------
def _instantanea(movimiento):
    return {
        'Fecha': f'{movimiento.fecha:%d/%m/%Y}', 'Hora': f'{movimiento.hora:%H:%M}', 'Tipo': movimiento.get_tipo_display(),
        'Motivo': movimiento.motivo, 'Quién lo acompaña o lo recoge': movimiento.acompanante,
    }


def _retardo_en_la_entrada(movimiento, usuario):
    """Un retardo de ingreso es la entrada con retardo: asistencia general en retardo a esa hora y la primera clase del
    día en falta (las demás según la hora); lo que el docente ya capturó se respeta."""
    fijar_asistencia_general(
        movimiento.inscripcion, movimiento.fecha, 'RETARDO', hora=movimiento.hora, usuario=usuario,
        observaciones=f'Retardo de ingreso registrado por prefectura: {movimiento.motivo}'[:250],
    )


@transaction.atomic
def registrar_acceso(inscripcion, datos, usuario):
    movimiento = MovimientoAcceso.objects.create(
        alumno=inscripcion.alumno, inscripcion=inscripcion, fecha=datos['fecha'], hora=datos['hora'], tipo=datos['tipo'],
        motivo=datos['motivo'], acompanante=datos['acompanante'], registrado_por=usuario, modificado_por=usuario,
    )
    CambioAcceso.objects.create(movimiento=movimiento, accion=CambioAcceso.CREADO, usuario=usuario)
    if movimiento.tipo == MovimientoAcceso.RETARDO:
        _retardo_en_la_entrada(movimiento, usuario)
    return movimiento


@transaction.atomic
def corregir_acceso(movimiento, datos, motivo, usuario):
    """Corrige el registro. Si sigue siendo un retardo de ingreso, la asistencia se vuelve a calcular con la hora nueva.
    Devuelve True si antes era un retardo y ya no lo es (o cambió de día): esa asistencia no se revierte sola."""
    antes = _instantanea(movimiento)
    era_retardo, fecha_anterior = movimiento.tipo == MovimientoAcceso.RETARDO, movimiento.fecha
    for campo in ('fecha', 'hora', 'tipo', 'motivo', 'acompanante'):
        setattr(movimiento, campo, datos[campo])
    movimiento.modificado_por = usuario
    movimiento.save()
    despues = _instantanea(movimiento)
    cambios = [[clave, antes[clave], valor] for clave, valor in despues.items() if antes[clave] != valor]
    CambioAcceso.objects.create(movimiento=movimiento, accion=CambioAcceso.CORREGIDO, usuario=usuario, motivo=motivo, cambios=cambios)
    es_retardo = movimiento.tipo == MovimientoAcceso.RETARDO
    if es_retardo and cambios:
        _retardo_en_la_entrada(movimiento, usuario)
    return era_retardo and (not es_retardo or movimiento.fecha != fecha_anterior)


@transaction.atomic
def anular_acceso(movimiento, motivo, usuario):
    movimiento.anulado, movimiento.anulado_por, movimiento.anulado_en, movimiento.motivo_anulacion = True, usuario, timezone.now(), motivo
    movimiento.modificado_por = usuario
    movimiento.save()
    CambioAcceso.objects.create(movimiento=movimiento, accion=CambioAcceso.ANULADO, usuario=usuario, motivo=motivo)


def puede_corregir_acceso(usuario, movimiento):
    """Lo propio mientras no esté anulado y sea del ciclo actual; lo de otros, con «Corregir de otros»."""
    if movimiento.anulado:
        return False
    ciclo = ciclo_actual()
    if ciclo is None or movimiento.inscripcion.ciclo_id != ciclo.pk:
        return False
    if usuario.has_perm('Prefectura.corregir_otros'):
        return True
    return usuario.has_perm('Prefectura.corregir') and movimiento.registrado_por_id == usuario.pk


def semana_de(fecha):
    lunes = fecha - timedelta(days=fecha.weekday())
    return lunes, lunes + timedelta(days=4)
