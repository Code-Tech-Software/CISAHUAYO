"""Reglas del módulo de conducta. Las vistas solo orquestan; los formularios validan lo que llega.

- El contexto escolar de un registro (ciclo, nivel, grado, grupo y periodo) sale de la inscripción del estudiante en el
  ciclo de la fecha del hecho y se congela al registrar: un cambio de grupo o de ciclo posterior no lo altera.
- Los nombres de categoría, motivo, medidas y motivo de suspensión se copian al registro: el historial conserva lo que
  significaba aunque el catálogo cambie. Los vínculos se guardan también, para filtrar.
- Cada alta, edición, cierre, anulación, evidencia o contacto queda en CambioConducta (quién, cuándo y qué cambió).
- Los avisos de reincidencia solo avisan: no aplican sanciones. Los días de una suspensión se marcan con S en la
  asistencia (pendiente o autorizada); autorizada, el cierre del día no genera faltas y esos días no cuentan como faltas.
- Toda suspensión necesita aprobación: quien tiene el permiso de aprobar la registra aprobada; la de cualquier otra
  persona queda pendiente, y nadie resuelve la que pidió él mismo. Las medidas que requieren aprobación, igual. Nada se
  borra: una medida que se quita queda anulada y una suspensión que se quita, cancelada (con motivo e historial).
- Un mismo filtro (`Filtro`) sirve al listado y a los reportes (pantalla, impresión y Excel): cuentan igual. Solo las
  medidas aplicadas y las suspensiones aprobadas cuentan en los indicadores.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Count, Exists, Max, Min, OuterRef, Prefetch, Q
from django.db.models.functions import TruncMonth, TruncWeek
from django.utils import timezone
from django.utils.formats import date_format

from Alumnos.academico import ciclo_actual
from Alumnos.models import CicloEscolar, Inscripcion, Periodo, orden_de_nivel

from .models import (
    ANULADA,
    APLICADA,
    APROBADA,
    CANCELADA,
    GRAVEDADES,
    INCIDENCIA,
    NIVELES,
    PENDIENTE,
    POSITIVA,
    RECHAZADA,
    TIPOS,
    AvisoReincidencia,
    CambioConducta,
    CategoriaConducta,
    CitaTutor,
    Compromiso,
    ContactoTutor,
    MedidaAplicada,
    MedidaDisciplinaria,
    MotivoConducta,
    MotivoSuspension,
    RegistroConducta,
    ReglaReincidencia,
    Suspension,
)


class SolicitudRechazada(Exception):
    """Una aprobación, rechazo o cancelación que no procede (mensaje para la persona)."""

NOMBRE_DE_NIVEL = dict(NIVELES)
NOMBRE_DE_TIPO = dict(TIPOS)
NOMBRE_DE_GRAVEDAD = dict(GRAVEDADES)
NOMBRE_DE_ESTADO = dict(RegistroConducta.ESTADOS)
NOMBRE_DE_SUSPENSION = {'con': 'Con suspensión aprobada', 'sin': 'Sin suspensión aprobada', 'vigente': 'Suspendidos hoy',
                        'pendiente': 'Solicitud de suspensión pendiente'}
DIAS_POR_VENCER = 7


def texto_fecha(fecha):
    return date_format(fecha, 'j \\d\\e F \\d\\e Y').lower() if fecha else ''


# ---------------------------------------------------------------------------
# El estudiante en la fecha del hecho
# ---------------------------------------------------------------------------
def ciclo_de(fecha):
    """El ciclo escolar que contiene esa fecha (si se empalmaran, el actual)."""
    return (
        CicloEscolar.objects.filter(fecha_inicio__lte=fecha, fecha_fin__gte=fecha)
        .order_by('-activo', '-fecha_inicio').first()
    )


def inscripcion_en(alumno, fecha):
    """La inscripción del estudiante en el ciclo de esa fecha: la vigente o, si ya se desactivó, la que tuvo."""
    ciclo = ciclo_de(fecha)
    if ciclo is None:
        return None
    return (
        Inscripcion.objects.filter(alumno=alumno, ciclo=ciclo)
        .select_related('ciclo', 'grado', 'grupo__nombre', 'grupo__grado')
        .order_by('-activa', '-fecha_inscripcion').first()
    )


def inscripcion_actual(alumno):
    """Su inscripción vigente del ciclo actual (o None)."""
    ciclo = ciclo_actual()
    if ciclo is None:
        return None
    return (
        Inscripcion.objects.filter(alumno=alumno, ciclo=ciclo, activa=True)
        .select_related('ciclo', 'grado', 'grupo__nombre', 'grupo__grado').first()
    )


def periodo_de(nivel, ciclo, fecha):
    """El periodo de evaluación del nivel, en ese ciclo, que contiene la fecha (según sus fechas), o None."""
    return (
        Periodo.objects.filter(ciclo=ciclo, nivel=nivel, fecha_inicio__lte=fecha, fecha_fin__gte=fecha)
        .order_by('fecha_inicio').first()
    )


def contexto_escolar(inscripcion, fecha):
    """Lo que el registro congela del estudiante: ciclo, nivel, grado, grupo (y cómo se llamaba) y periodo."""
    nivel = inscripcion.grado.nivel
    return {
        'alumno': inscripcion.alumno, 'inscripcion': inscripcion, 'ciclo': inscripcion.ciclo, 'nivel': nivel,
        'grado': inscripcion.grado, 'grupo': inscripcion.grupo, 'grupo_texto': str(inscripcion.grupo),
        'periodo': periodo_de(nivel, inscripcion.ciclo, fecha),
    }


# ---------------------------------------------------------------------------
# Opciones de un nivel (solo lo activo: lo inactivo no se ofrece para registros nuevos)
# ---------------------------------------------------------------------------
def medidas_ofrecidas(nivel, solo_prefectura=False):
    """Las medidas activas del nivel; para prefectura, solo las habilitadas para ella."""
    medidas = MedidaDisciplinaria.objects.activos().del_nivel(nivel)
    if solo_prefectura:
        medidas = medidas.filter(disponible_prefectura=True)
    return medidas.order_by('nombre')


def opciones_del_nivel(nivel, solo_prefectura=False):
    """Las categorías, motivos, medidas y motivos de suspensión activos del nivel, para el formulario."""
    categorias = list(CategoriaConducta.objects.activos().del_nivel(nivel).order_by('nombre'))
    activas = {categoria.pk for categoria in categorias}
    motivos = (
        MotivoConducta.objects.activos().filter(categoria__in=activas).order_by('nombre')
    )
    return {
        'nivel': nivel,
        'categorias': [{'id': c.pk, 'nombre': c.nombre, 'tipo': c.tipo} for c in categorias],
        'motivos': [{'id': m.pk, 'nombre': m.nombre, 'categoria': m.categoria_id, 'gravedad': m.gravedad} for m in motivos],
        'medidas': [
            {'id': m.pk, 'nombre': m.nombre, 'requiere_seguimiento': m.requiere_seguimiento, 'implica_suspension': m.implica_suspension,
             'requiere_aprobacion': m.requiere_aprobacion}
            for m in medidas_ofrecidas(nivel, solo_prefectura)
        ],
        'motivos_suspension': [
            {'id': m.pk, 'nombre': m.nombre} for m in MotivoSuspension.objects.activos().del_nivel(nivel).order_by('nombre')
        ],
    }


# ---------------------------------------------------------------------------
# Suspensiones
# ---------------------------------------------------------------------------
def suspensiones_superpuestas(alumno, inicio, fin, excluir_registro=None):
    """Las suspensiones aprobadas o pendientes (de registros no anulados) del estudiante que se cruzan con esas fechas."""
    otras = Suspension.objects.filter(
        registro__alumno=alumno, registro__anulado=False, fecha_inicio__lte=fin, fecha_fin__gte=inicio,
        aprobacion__in=(APROBADA, PENDIENTE),
    ).select_related('registro')
    if excluir_registro is not None and excluir_registro.pk:
        otras = otras.exclude(registro=excluir_registro)
    return list(otras.order_by('fecha_inicio'))


# ---------------------------------------------------------------------------
# Historial de un registro
# ---------------------------------------------------------------------------
def _nombre_de_usuario(usuario):
    return (usuario.get_full_name() or usuario.get_username()) if usuario else ''


def _texto_suspension(suspension):
    if suspension is None or suspension.aprobacion == CANCELADA:
        return ''
    texto = f'{suspension.motivo_nombre}: del {suspension.fecha_inicio:%d/%m/%Y} al {suspension.fecha_fin:%d/%m/%Y}'
    if suspension.aprobada:
        return f'{texto} (autorizó {_nombre_de_usuario(suspension.autorizada_por) or "—"})'
    return f'{texto} ({suspension.get_aprobacion_display().lower()})'


def instantanea(registro):
    """Lo que se compara para saber qué cambió (textos legibles)."""
    suspension = Suspension.objects.filter(registro=registro).select_related('autorizada_por').first() if registro.pk else None
    medidas = ', '.join(sorted(
        m.nombre + ('' if m.estado == APLICADA else ' (pendiente de aprobación)')
        for m in registro.medidas_aplicadas.filter(estado__in=MedidaAplicada.VIGENTES)
    )) if registro.pk else ''
    return {
        'Fecha': registro.fecha.strftime('%d/%m/%Y') if registro.fecha else '',
        'Hora': registro.hora.strftime('%H:%M') if registro.hora else '',
        'Lugar': registro.lugar,
        'Personal que reporta': registro.reporta,
        'Tipo': NOMBRE_DE_TIPO.get(registro.tipo, ''),
        'Categoría': registro.categoria_nombre,
        'Motivo': registro.motivo_nombre,
        'Gravedad': NOMBRE_DE_GRAVEDAD.get(registro.gravedad, ''),
        'Descripción': registro.descripcion,
        'Medidas': medidas,
        'Observaciones sobre las medidas': registro.observaciones_medidas,
        'Suspensión': _texto_suspension(suspension),
        'Observaciones de la suspensión': suspension.observaciones if suspension and suspension.aprobacion != CANCELADA else '',
        'Justificación de la suspensión': suspension.justificacion if suspension and suspension.aprobacion != CANCELADA else '',
        'Responsable del seguimiento': _nombre_de_usuario(registro.responsable),
        'Fecha de revisión': registro.fecha_revision.strftime('%d/%m/%Y') if registro.fecha_revision else '',
        'Estado': NOMBRE_DE_ESTADO.get(registro.estado, ''),
        'Acuerdos': registro.acuerdos,
        'Observaciones de cierre': registro.observaciones_cierre,
    }


def diferencias(antes, despues):
    return [[clave, antes.get(clave, ''), valor] for clave, valor in despues.items() if antes.get(clave, '') != valor]


def anotar(registro, accion, usuario, detalle='', cambios=()):
    return CambioConducta.objects.create(registro=registro, accion=accion, usuario=usuario, detalle=detalle, cambios=list(cambios))


def _con_motivo(texto, motivo):
    return f'{texto} Motivo: {motivo}' if motivo else texto


# ---------------------------------------------------------------------------
# Guardar un registro (alta o edición)
# ---------------------------------------------------------------------------
def _necesita_aprobacion(medida, usuario):
    from .permisos import puede_aprobar
    return (medida.requiere_aprobacion or medida.implica_suspension) and not puede_aprobar(usuario, medida.nivel)


def _aplicar_medidas(registro, elegidas, usuario, motivo, ahora):
    """Deja aplicadas (o pendientes de aprobación) las medidas elegidas; las que se quitaron quedan anuladas con el
    motivo del cambio (nunca se borran). Las que siguen conservan su nombre de entonces."""
    existentes = {m.medida_id: m for m in registro.medidas_aplicadas.all()}
    for pk, medida in elegidas.items():
        actual = existentes.get(pk)
        if actual is not None and actual.estado in MedidaAplicada.VIGENTES:
            continue
        pendiente = _necesita_aprobacion(medida, usuario)
        if actual is None:
            actual = MedidaAplicada(registro=registro, medida=medida, nombre=medida.nombre,
                                    requiere_seguimiento=medida.requiere_seguimiento, implica_suspension=medida.implica_suspension)
        actual.estado = PENDIENTE if pendiente else APLICADA
        actual.solicitada_por, actual.solicitada_en = (usuario, ahora) if pendiente else (None, None)
        actual.resuelta_por, actual.resuelta_en, actual.observaciones = None, None, ''
        actual.save()
    for pk, actual in existentes.items():
        if pk not in elegidas and actual.estado in MedidaAplicada.VIGENTES:
            actual.estado, actual.resuelta_por, actual.resuelta_en = ANULADA, usuario, ahora
            actual.observaciones = motivo or 'Se quitó del registro.'
            actual.save(update_fields=['estado', 'resuelta_por', 'resuelta_en', 'observaciones'])


def _aplicar_suspension(registro, datos, usuario, motivo, ahora):
    """La suspensión del registro: quien aprueba la deja aprobada; cualquier otra persona la deja pendiente (una
    solicitud). Si se quita, queda cancelada. Devuelve 'solicitada' si quedó una solicitud nueva o cambiada."""
    from .permisos import puede_aprobar
    suspension = Suspension.objects.filter(registro=registro).first()
    if not datos.get('suspension_motivo'):
        if suspension is not None and suspension.aprobacion in (APROBADA, PENDIENTE):
            suspension.aprobacion, suspension.resuelta_por, suspension.resuelta_en = CANCELADA, usuario, ahora
            suspension.observaciones_resolucion = motivo or 'Se quitó del registro.'
            suspension.save()
        return None
    nueva = suspension is None
    suspension = suspension or Suspension(registro=registro)
    antes = (suspension.motivo_id, suspension.fecha_inicio, suspension.fecha_fin, suspension.aprobacion)
    if suspension.motivo_id != datos['suspension_motivo'].pk:
        suspension.motivo_nombre = datos['suspension_motivo'].nombre
    suspension.motivo = datos['suspension_motivo']
    suspension.fecha_inicio, suspension.fecha_fin = datos['suspension_inicio'], datos['suspension_fin']
    suspension.observaciones = datos.get('suspension_observaciones') or ''
    suspension.justificacion = datos.get('suspension_justificacion') or suspension.justificacion
    cambio = nueva or antes[:3] != (suspension.motivo_id, suspension.fecha_inicio, suspension.fecha_fin) or antes[3] in (RECHAZADA, CANCELADA)
    resultado = None
    if puede_aprobar(usuario, registro.nivel):
        # Quien aprueba registra (o cambia) la suspensión ya aprobada; una solicitud ajena que no toca sigue pendiente
        if cambio:
            suspension.aprobacion = APROBADA
            suspension.autorizada_por = datos.get('suspension_autoriza') or usuario
            suspension.resuelta_por, suspension.resuelta_en = usuario, ahora
            suspension.observaciones_resolucion = ''
            if nueva:
                suspension.solicitada_por, suspension.solicitada_en = usuario, ahora
        elif datos.get('suspension_autoriza') and suspension.aprobada:
            suspension.autorizada_por = datos['suspension_autoriza']
    elif cambio:
        suspension.aprobacion = PENDIENTE
        suspension.autorizada_por = None
        suspension.solicitada_por, suspension.solicitada_en = usuario, ahora
        suspension.resuelta_por, suspension.resuelta_en, suspension.observaciones_resolucion = None, None, ''
        resultado = 'solicitada'
    suspension.save()
    _sincronizar_medidas_de_suspension(registro, suspension, usuario, ahora)
    return resultado


def _sincronizar_medidas_de_suspension(registro, suspension, usuario, ahora):
    """Las medidas que implican suspensión siguen a su suspensión: pendientes mientras lo esté, aplicadas al aprobarse,
    rechazadas o anuladas con ella."""
    estado = {PENDIENTE: PENDIENTE, APROBADA: APLICADA, RECHAZADA: RECHAZADA, CANCELADA: ANULADA}[suspension.aprobacion]
    for medida in registro.medidas_aplicadas.filter(implica_suspension=True, estado__in=MedidaAplicada.VIGENTES):
        if medida.estado != estado:
            medida.estado = estado
            if estado != PENDIENTE:
                medida.resuelta_por, medida.resuelta_en = usuario, ahora
                medida.observaciones = suspension.observaciones_resolucion
            medida.save()


@transaction.atomic
def guardar_registro(registro, datos, usuario, motivo=''):
    """Guarda el registro con lo que validó el formulario (`datos`): copia los nombres de catálogo, aplica las medidas y
    la suspensión (pendientes de aprobación si hace falta), deja constancia del cambio en el historial (con `motivo`, el
    motivo del cambio) y revisa el aviso de reincidencia. Devuelve el registro."""
    nuevo = registro.pk is None
    antes = {} if nuevo else instantanea(registro)
    estado_anterior = None if nuevo else registro.estado
    ahora = timezone.now()

    categoria_previa, motivo_previo = registro.categoria_id, registro.motivo_id
    for campo in ('fecha', 'hora', 'lugar', 'tipo', 'categoria', 'motivo', 'gravedad', 'descripcion', 'observaciones_medidas',
                  'responsable', 'fecha_revision', 'estado', 'acuerdos', 'observaciones_cierre'):
        setattr(registro, campo, datos[campo])
    registro.reporta = datos.get('reporta', registro.reporta) or ''
    # El nombre de entonces se conserva mientras no se elija otra categoría u otro motivo
    if registro.categoria_id != categoria_previa:
        registro.categoria_nombre = registro.categoria.nombre
    if registro.motivo_id != motivo_previo:
        registro.motivo_nombre = registro.motivo.nombre
    registro.periodo = periodo_de(registro.nivel, registro.ciclo, registro.fecha)
    if registro.estado == RegistroConducta.CERRADO and estado_anterior != RegistroConducta.CERRADO:
        registro.cerrado_por, registro.cerrado_en = usuario, ahora
    elif registro.estado != RegistroConducta.CERRADO:
        registro.cerrado_por, registro.cerrado_en = None, None
    if nuevo:
        registro.registrado_por = usuario
    registro.modificado_por = usuario
    registro.save()

    _aplicar_medidas(registro, {medida.pk: medida for medida in datos['medidas']}, usuario, motivo, ahora)
    solicitud = _aplicar_suspension(registro, datos, usuario, motivo, ahora)

    registro = RegistroConducta.objects.select_related('suspension', 'responsable').get(pk=registro.pk)
    if nuevo:
        anotar(registro, CambioConducta.CREADO, usuario, f'{NOMBRE_DE_TIPO[registro.tipo]}: {registro.motivo_nombre}.')
    else:
        cambios = diferencias(antes, instantanea(registro))
        if cambios:
            anotar(registro, CambioConducta.EDITADO, usuario,
                   _con_motivo('Cambió ' + ', '.join(c[0].lower() for c in cambios) + '.', motivo), cambios)
    if not nuevo and estado_anterior != registro.estado:
        if registro.estado == RegistroConducta.CERRADO:
            anotar(registro, CambioConducta.CERRADO, usuario, registro.observaciones_cierre)
        elif estado_anterior == RegistroConducta.CERRADO:
            anotar(registro, CambioConducta.REABIERTO, usuario, motivo)
    pendientes = registro.medidas_aplicadas.filter(estado=PENDIENTE, implica_suspension=False, solicitada_en=ahora)
    if solicitud or pendientes.exists():
        que = ['la suspensión'] if solicitud else []
        que += [f'la medida «{m.nombre}»' for m in pendientes]
        anotar(registro, CambioConducta.SOLICITUD, usuario, f'Solicitó la aprobación de {", ".join(que)}.')
    evaluar_reincidencia(registro)
    return registro


@transaction.atomic
def actualizar_seguimiento(registro, datos, usuario):
    """Solo el seguimiento (responsable, fecha de revisión, estado, acuerdos y cierre), con su constancia."""
    antes = instantanea(registro)
    estado_anterior = registro.estado
    for campo in ('responsable', 'fecha_revision', 'estado', 'acuerdos', 'observaciones_cierre'):
        setattr(registro, campo, datos[campo])
    if registro.estado == RegistroConducta.CERRADO and estado_anterior != RegistroConducta.CERRADO:
        registro.cerrado_por, registro.cerrado_en = usuario, timezone.now()
    elif registro.estado != RegistroConducta.CERRADO:
        registro.cerrado_por, registro.cerrado_en = None, None
    registro.modificado_por = usuario
    registro.save()
    cambios = diferencias(antes, instantanea(registro))
    if estado_anterior != registro.estado and registro.estado == RegistroConducta.CERRADO:
        anotar(registro, CambioConducta.CERRADO, usuario, registro.observaciones_cierre, cambios)
    elif estado_anterior == RegistroConducta.CERRADO and registro.estado != RegistroConducta.CERRADO:
        anotar(registro, CambioConducta.REABIERTO, usuario, '', cambios)
    elif cambios:
        anotar(registro, CambioConducta.SEGUIMIENTO, usuario, 'Cambió ' + ', '.join(c[0].lower() for c in cambios) + '.', cambios)
    return registro


@transaction.atomic
def anular(registro, motivo, usuario):
    registro.anulado, registro.anulado_por, registro.anulado_en, registro.motivo_anulacion = True, usuario, timezone.now(), motivo
    registro.modificado_por = usuario
    registro.save()
    # Lo que esperaba aprobación ya no procede
    ahora = timezone.now()
    Suspension.objects.filter(registro=registro, aprobacion=PENDIENTE).update(
        aprobacion=CANCELADA, resuelta_por=usuario, resuelta_en=ahora, observaciones_resolucion='Se anuló el registro.')
    registro.medidas_aplicadas.filter(estado=PENDIENTE).update(
        estado=ANULADA, resuelta_por=usuario, resuelta_en=ahora, observaciones='Se anuló el registro.')
    anotar(registro, CambioConducta.ANULADO, usuario, motivo)


# ---------------------------------------------------------------------------
# Solicitudes: aprobar, rechazar o cancelar una suspensión o una medida pendiente
# ---------------------------------------------------------------------------
@transaction.atomic
def resolver_suspension(suspension, aprobar, observaciones, usuario):
    """Aprueba o rechaza una solicitud de suspensión pendiente. Nadie resuelve la que pidió él mismo."""
    from .permisos import puede_aprobar
    suspension = Suspension.objects.select_for_update().select_related('registro__alumno', 'registro__ciclo').get(pk=suspension.pk)
    if not puede_aprobar(usuario, suspension.registro.nivel):
        raise SolicitudRechazada(f'La autoriza la dirección de {NOMBRE_DE_NIVEL[suspension.registro.nivel].lower()}.')
    if suspension.aprobacion != PENDIENTE:
        raise SolicitudRechazada(f'Esa solicitud ya está {suspension.get_aprobacion_display().lower()}.')
    if suspension.solicitada_por_id == usuario.pk:
        raise SolicitudRechazada('No puedes resolver una solicitud que hiciste tú: la debe resolver otra persona autorizada.')
    if suspension.registro.anulado:
        raise SolicitudRechazada('El registro está anulado.')
    if suspension.registro.ciclo.estado == 'CERRADO':
        raise SolicitudRechazada(f'El ciclo {suspension.registro.ciclo} ya se cerró: es de solo lectura.')
    ahora = timezone.now()
    suspension.aprobacion = APROBADA if aprobar else RECHAZADA
    suspension.resuelta_por, suspension.resuelta_en, suspension.observaciones_resolucion = usuario, ahora, observaciones
    if aprobar:
        suspension.autorizada_por = usuario
    suspension.save()
    _sincronizar_medidas_de_suspension(suspension.registro, suspension, usuario, ahora)
    texto = (f'{"Aprobó" if aprobar else "Rechazó"} la suspensión del {suspension.fecha_inicio:%d/%m/%Y} al '
             f'{suspension.fecha_fin:%d/%m/%Y}.')
    anotar(suspension.registro, CambioConducta.RESOLUCION, usuario, _con_motivo(texto, observaciones).replace('Motivo:', 'Observaciones:'))
    return suspension


@transaction.atomic
def cancelar_suspension(suspension, motivo, usuario):
    """Cancela una solicitud pendiente (quien la pidió o quien aprueba)."""
    from .permisos import puede_aprobar
    suspension = Suspension.objects.select_for_update().select_related('registro').get(pk=suspension.pk)
    if suspension.aprobacion != PENDIENTE:
        raise SolicitudRechazada(f'Esa solicitud ya está {suspension.get_aprobacion_display().lower()}.')
    if suspension.solicitada_por_id != usuario.pk and not puede_aprobar(usuario, suspension.registro.nivel):
        raise SolicitudRechazada('Solo quien hizo la solicitud o la dirección de su nivel pueden cancelarla.')
    if suspension.registro.ciclo.estado == 'CERRADO':
        raise SolicitudRechazada(f'El ciclo {suspension.registro.ciclo} ya se cerró: es de solo lectura.')
    ahora = timezone.now()
    suspension.aprobacion, suspension.resuelta_por, suspension.resuelta_en = CANCELADA, usuario, ahora
    suspension.observaciones_resolucion = motivo
    suspension.save()
    _sincronizar_medidas_de_suspension(suspension.registro, suspension, usuario, ahora)
    anotar(suspension.registro, CambioConducta.RESOLUCION, usuario, _con_motivo('Canceló la solicitud de suspensión.', motivo))
    return suspension


@transaction.atomic
def resolver_medida(medida, aprobar, observaciones, usuario):
    """Aprueba o rechaza una medida pendiente (las que implican suspensión se resuelven con su suspensión)."""
    from .permisos import puede_aprobar
    medida = MedidaAplicada.objects.select_for_update().select_related('registro').get(pk=medida.pk)
    if not puede_aprobar(usuario, medida.registro.nivel):
        raise SolicitudRechazada(f'La autoriza la dirección de {NOMBRE_DE_NIVEL[medida.registro.nivel].lower()}.')
    if medida.estado != PENDIENTE:
        raise SolicitudRechazada(f'Esa medida ya está {medida.get_estado_display().lower()}.')
    if medida.implica_suspension:
        raise SolicitudRechazada('Esa medida se resuelve junto con su solicitud de suspensión.')
    if medida.solicitada_por_id == usuario.pk:
        raise SolicitudRechazada('No puedes resolver una solicitud que hiciste tú: la debe resolver otra persona autorizada.')
    if medida.registro.anulado:
        raise SolicitudRechazada('El registro está anulado.')
    if medida.registro.ciclo.estado == 'CERRADO':
        raise SolicitudRechazada(f'El ciclo {medida.registro.ciclo} ya se cerró: es de solo lectura.')
    medida.estado = APLICADA if aprobar else RECHAZADA
    medida.resuelta_por, medida.resuelta_en, medida.observaciones = usuario, timezone.now(), observaciones
    medida.save()
    texto = f'{"Aprobó" if aprobar else "Rechazó"} la medida «{medida.nombre}».'
    anotar(medida.registro, CambioConducta.RESOLUCION, usuario, _con_motivo(texto, observaciones).replace('Motivo:', 'Observaciones:'))
    return medida


def solicitudes_pendientes(registros):
    """Las suspensiones y medidas pendientes de aprobación de esos registros (no anulados)."""
    vigentes = registros.filter(anulado=False)
    return {
        'suspensiones': list(
            Suspension.objects.filter(registro__in=vigentes.values('pk'), aprobacion=PENDIENTE)
            .select_related('registro__alumno', 'solicitada_por').order_by('solicitada_en', 'pk')
        ),
        'medidas': list(
            MedidaAplicada.objects.filter(registro__in=vigentes.values('pk'), estado=PENDIENTE, implica_suspension=False)
            .select_related('registro__alumno', 'solicitada_por').order_by('solicitada_en', 'pk')
        ),
    }


# ---------------------------------------------------------------------------
# Citas y compromisos del caso
# ---------------------------------------------------------------------------
@transaction.atomic
def programar_cita(registro, datos, usuario):
    cita = CitaTutor.objects.create(
        registro=registro, fecha=datos['fecha'], hora=datos['hora'], modalidad=datos['modalidad'], tutor=datos['tutor_obj'],
        persona=datos['persona'], asunto=datos['asunto'], responsable=datos['responsable'], registrado_por=usuario,
        modificado_por=usuario,
    )
    hora = f' a las {cita.hora:%H:%M}' if cita.hora else ''
    anotar(registro, CambioConducta.CITA, usuario, f'Programó una cita con {cita.persona} el {cita.fecha:%d/%m/%Y}{hora}: {cita.asunto}')
    return cita


@transaction.atomic
def actualizar_cita(cita, estado, resultado, usuario):
    antes = cita.get_estado_display()
    cita.estado, cita.resultado, cita.modificado_por = estado, resultado, usuario
    cita.save()
    anotar(cita.registro, CambioConducta.CITA, usuario,
           f'Cita con {cita.persona} del {cita.fecha:%d/%m/%Y}: {cita.get_estado_display().lower()}. {resultado}'.strip(),
           [['Estado de la cita', antes, cita.get_estado_display()]])
    return cita


@transaction.atomic
def agregar_compromiso(registro, datos, usuario):
    compromiso = Compromiso.objects.create(
        registro=registro, descripcion=datos['descripcion'], quien=datos['quien'], responsable=datos['responsable'],
        fecha_limite=datos['fecha_limite'], registrado_por=usuario,
    )
    anotar(registro, CambioConducta.COMPROMISO, usuario,
           f'{compromiso.get_quien_display()} se compromete, a más tardar el {compromiso.fecha_limite:%d/%m/%Y}: {compromiso.descripcion}')
    return compromiso


@transaction.atomic
def resolver_compromiso(compromiso, estado, observaciones, usuario):
    antes = compromiso.get_estado_display()
    compromiso.estado, compromiso.observaciones = estado, observaciones
    compromiso.resuelto_por, compromiso.resuelto_en = usuario, timezone.now()
    compromiso.save()
    anotar(compromiso.registro, CambioConducta.COMPROMISO, usuario,
           f'Compromiso «{compromiso.descripcion[:80]}»: {compromiso.get_estado_display().lower()}. {observaciones}'.strip(),
           [['Estado del compromiso', antes, compromiso.get_estado_display()]])
    return compromiso


# ---------------------------------------------------------------------------
# Reincidencia
# ---------------------------------------------------------------------------
def evaluar_reincidencia(registro):
    """Si con este registro el estudiante llega al umbral de su nivel (incidencias del mismo motivo en N días), deja un
    aviso para revisión. Devuelve el aviso o None. No sanciona."""
    if registro.anulado or registro.tipo != INCIDENCIA:
        return None
    regla = ReglaReincidencia.objects.filter(nivel=registro.nivel, activa=True).first()
    if regla is None:
        return None
    desde = registro.fecha - timedelta(days=regla.dias - 1)
    cantidad = RegistroConducta.objects.vigentes().filter(
        alumno=registro.alumno_id, motivo=registro.motivo_id, tipo=INCIDENCIA, fecha__range=(desde, registro.fecha),
    ).count()
    if cantidad < regla.incidencias:
        return None
    aviso, creado = AvisoReincidencia.objects.get_or_create(registro=registro, defaults={
        'alumno_id': registro.alumno_id, 'motivo_id': registro.motivo_id, 'cantidad': cantidad, 'dias': regla.dias,
    })
    if not creado and not aviso.revisado and (aviso.cantidad, aviso.motivo_id) != (cantidad, registro.motivo_id):
        aviso.cantidad, aviso.motivo_id, aviso.dias = cantidad, registro.motivo_id, regla.dias
        aviso.save(update_fields=['cantidad', 'motivo', 'dias'])
    return aviso


def revisar_aviso(aviso, nota, usuario):
    aviso.revisado, aviso.revisado_por, aviso.revisado_en, aviso.nota = True, usuario, timezone.now(), nota
    aviso.save(update_fields=['revisado', 'revisado_por', 'revisado_en', 'nota'])
    anotar(aviso.registro, CambioConducta.AVISO, usuario, nota)


# ---------------------------------------------------------------------------
# Pendientes
# ---------------------------------------------------------------------------
def pendientes(hoy=None, registros=None):
    """Lo que necesita atención: avisos de reincidencia sin revisar, seguimientos vencidos y por vencer, acuerdos con la
    familia por revisar, citas y compromisos próximos, solicitudes por aprobar y suspensiones vigentes o próximas. Solo
    de registros no anulados; `registros` limita a los que la persona puede ver (su alcance)."""
    hoy = hoy or timezone.localdate()
    limite = hoy + timedelta(days=DIAS_POR_VENCER)
    base = (RegistroConducta.objects.all() if registros is None else registros).filter(anulado=False)
    ids = base.values('pk')
    abiertos = base.exclude(estado=RegistroConducta.CERRADO).select_related('alumno', 'responsable')
    datos = {
        'avisos': list(
            AvisoReincidencia.objects.filter(revisado=False, registro__in=ids)
            .select_related('alumno', 'motivo', 'registro').order_by('-creado')
        ),
        'vencidos': list(abiertos.filter(fecha_revision__lt=hoy).order_by('fecha_revision')),
        'por_vencer': list(abiertos.filter(fecha_revision__range=(hoy, limite)).order_by('fecha_revision')),
        'acuerdos': list(
            ContactoTutor.objects.filter(registro__in=ids, proxima_revision__isnull=False, proxima_revision__lte=limite)
            .exclude(registro__estado=RegistroConducta.CERRADO)
            .select_related('registro__alumno').order_by('proxima_revision')
        ),
        'citas': list(
            CitaTutor.objects.filter(registro__in=ids, estado=CitaTutor.PROGRAMADA, fecha__lte=limite)
            .select_related('registro__alumno', 'responsable').order_by('fecha', 'hora')
        ),
        'compromisos': list(
            Compromiso.objects.filter(registro__in=ids, estado=Compromiso.PENDIENTE_C, fecha_limite__lte=limite)
            .select_related('registro__alumno', 'responsable').order_by('fecha_limite')
        ),
        'suspensiones': list(
            Suspension.objects.filter(registro__in=ids, aprobacion=APROBADA, fecha_fin__gte=hoy)
            .select_related('registro__alumno', 'autorizada_por').order_by('fecha_inicio')
        ),
        **{f'solicitudes_{clave}': valor for clave, valor in solicitudes_pendientes(base).items()},
    }
    datos['total'] = (
        len(datos['avisos']) + len(datos['vencidos']) + sum(1 for c in datos['acuerdos'] if c.proxima_revision <= hoy)
        + sum(1 for c in datos['citas'] if c.fecha < hoy) + sum(1 for c in datos['compromisos'] if c.fecha_limite < hoy)
    )
    datos['hoy'] = hoy
    return datos


def cuantos_pendientes(hoy=None, registros=None):
    """Para la insignia de la pestaña: avisos sin revisar y seguimientos, acuerdos, citas y compromisos vencidos."""
    hoy = hoy or timezone.localdate()
    base = (RegistroConducta.objects.all() if registros is None else registros).filter(anulado=False)
    ids = base.values('pk')
    abiertos = ~Q(registro__estado=RegistroConducta.CERRADO)
    return (
        AvisoReincidencia.objects.filter(revisado=False, registro__in=ids).count()
        + base.exclude(estado=RegistroConducta.CERRADO).filter(fecha_revision__lt=hoy).count()
        + ContactoTutor.objects.filter(abiertos, registro__in=ids, proxima_revision__lte=hoy).count()
        + CitaTutor.objects.filter(registro__in=ids, estado=CitaTutor.PROGRAMADA, fecha__lt=hoy).count()
        + Compromiso.objects.filter(registro__in=ids, estado=Compromiso.PENDIENTE_C, fecha_limite__lt=hoy).count()
    )


def cuantas_solicitudes(registros=None):
    """Suspensiones y medidas esperando aprobación (de registros no anulados)."""
    base = (RegistroConducta.objects.all() if registros is None else registros).filter(anulado=False)
    return (
        Suspension.objects.filter(registro__in=base.values('pk'), aprobacion=PENDIENTE).count()
        + MedidaAplicada.objects.filter(registro__in=base.values('pk'), estado=PENDIENTE, implica_suspension=False).count()
    )


# ---------------------------------------------------------------------------
# Filtros (listado y reportes)
# ---------------------------------------------------------------------------
VIGENTES, ANULADOS, TODOS = 'vigentes', 'anulados', 'todos'


@dataclass
class Filtro:
    ciclo: object = None
    periodo: object = None
    desde: date = None
    hasta: date = None
    nivel: str = ''
    grado: object = None
    grupo: object = None
    alumnos: list = field(default_factory=list)
    texto: str = ''
    tipo: str = ''
    categoria: object = None
    motivo: object = None
    gravedad: str = ''
    medida: object = None
    suspension: str = ''        # 'con' (aprobada), 'sin', 'vigente' (hoy) o 'pendiente' (solicitud por aprobar)
    estado: str = ''            # un estado, 'abiertos' (abierto o en seguimiento) o 'vencidos'
    registros: str = VIGENTES   # vigentes, anulados o todos
    bitacora: bool = True       # reportes por grupo e individuales: con la sección «Observaciones de bitácora»

    def rango(self):
        """(inicio, fin, aviso) de las fechas del hecho: las del periodo (si se eligió) cruzadas con el rango. `aviso`
        explica si no hay fechas en común; entonces inicio y fin son None y no hay resultados."""
        inicio, fin = self.desde, self.hasta
        if self.periodo is not None:
            inicio = max(filter(None, (inicio, self.periodo.fecha_inicio)))
            fin = min(filter(None, (fin, self.periodo.fecha_fin)))
        if inicio and fin and inicio > fin:
            if self.periodo is not None and (self.desde or self.hasta):
                return None, None, (
                    f'El rango elegido no coincide con las fechas del periodo «{self.periodo.nombre}» '
                    f'({self.periodo.fecha_inicio:%d/%m/%Y} al {self.periodo.fecha_fin:%d/%m/%Y}): no hay fechas en común.'
                )
            return None, None, 'La fecha inicial va después de la final: no hay fechas en común.'
        return inicio, fin, None

    def aplicar(self, registros):
        """Los registros que cumplen el filtro, sin repetir ninguno (aunque tenga varias medidas)."""
        inicio, fin, aviso = self.rango()
        if aviso:
            return registros.none()
        if self.registros == VIGENTES:
            registros = registros.filter(anulado=False)
        elif self.registros == ANULADOS:
            registros = registros.filter(anulado=True)
        if self.ciclo is not None:
            registros = registros.filter(ciclo=self.ciclo)
        if inicio:
            registros = registros.filter(fecha__gte=inicio)
        if fin:
            registros = registros.filter(fecha__lte=fin)
        nivel = self.periodo.nivel if self.periodo is not None else self.nivel
        if nivel:
            registros = registros.filter(nivel=nivel)
        if self.grupo is not None:
            registros = registros.filter(grupo=self.grupo)
        elif self.grado is not None:
            registros = registros.filter(grado=self.grado)
        if self.alumnos:
            registros = registros.filter(alumno__in=self.alumnos)
        for palabra in self.texto.split():
            registros = registros.filter(
                Q(alumno__nombre__icontains=palabra) | Q(alumno__apellido_paterno__icontains=palabra)
                | Q(alumno__apellido_materno__icontains=palabra) | Q(alumno__referencia__icontains=palabra)
            )
        if self.tipo:
            registros = registros.filter(tipo=self.tipo)
        if self.motivo is not None:
            registros = registros.filter(motivo=self.motivo)
        elif self.categoria is not None:
            registros = registros.filter(categoria=self.categoria)
        if self.gravedad:
            registros = registros.filter(gravedad=self.gravedad)
        if self.medida is not None:
            registros = registros.filter(Exists(MedidaAplicada.objects.filter(registro=OuterRef('pk'), medida=self.medida, estado=APLICADA)))
        aprobadas = Suspension.objects.filter(registro=OuterRef('pk'), aprobacion=APROBADA)
        if self.suspension == 'con':
            registros = registros.filter(Exists(aprobadas))
        elif self.suspension == 'sin':
            registros = registros.exclude(Exists(aprobadas))
        elif self.suspension == 'vigente':
            hoy = timezone.localdate()
            registros = registros.filter(Exists(aprobadas.filter(fecha_inicio__lte=hoy, fecha_fin__gte=hoy)))
        elif self.suspension == 'pendiente':
            registros = registros.filter(Exists(Suspension.objects.filter(registro=OuterRef('pk'), aprobacion=PENDIENTE)))
        if self.estado == 'vencidos':
            registros = registros.exclude(estado=RegistroConducta.CERRADO).filter(fecha_revision__lt=timezone.localdate())
        elif self.estado == 'abiertos':
            registros = registros.exclude(estado=RegistroConducta.CERRADO)
        elif self.estado:
            registros = registros.filter(estado=self.estado)
        return registros

    def descripcion(self):
        """[(filtro, valor)] de lo que se aplicó, para el encabezado de los reportes."""
        inicio, fin, _ = self.rango()
        partes = []
        if self.ciclo is not None:
            partes.append(('Ciclo escolar', str(self.ciclo)))
        if self.periodo is not None:
            partes.append(('Periodo', f'{self.periodo.nombre} de {self.periodo.get_nivel_display()} '
                                      f'({self.periodo.fecha_inicio:%d/%m/%Y} al {self.periodo.fecha_fin:%d/%m/%Y})'))
        if inicio or fin:
            partes.append(('Fechas del hecho', f'{inicio:%d/%m/%Y} al {fin:%d/%m/%Y}' if inicio and fin
                           else (f'desde el {inicio:%d/%m/%Y}' if inicio else f'hasta el {fin:%d/%m/%Y}')))
        if self.nivel and self.periodo is None:
            partes.append(('Nivel', NOMBRE_DE_NIVEL.get(self.nivel, self.nivel)))
        if self.grupo is not None:
            partes.append(('Grupo', str(self.grupo)))
        elif self.grado is not None:
            partes.append(('Grado', str(self.grado)))
        if self.alumnos:
            partes.append(('Estudiantes', ', '.join(str(a) for a in self.alumnos)))
        if self.texto:
            partes.append(('Búsqueda', self.texto))
        if self.tipo:
            partes.append(('Tipo', NOMBRE_DE_TIPO[self.tipo]))
        if self.categoria is not None:
            partes.append(('Categoría', self.categoria.nombre))
        if self.motivo is not None:
            partes.append(('Motivo', self.motivo.nombre))
        if self.gravedad:
            partes.append(('Gravedad', NOMBRE_DE_GRAVEDAD[self.gravedad]))
        if self.medida is not None:
            partes.append(('Medida', self.medida.nombre))
        if self.suspension:
            partes.append(('Suspensión', NOMBRE_DE_SUSPENSION.get(self.suspension, self.suspension)))
        if self.estado:
            partes.append(('Seguimiento', {'vencidos': 'Vencidos', 'abiertos': 'Abiertos o en seguimiento'}.get(self.estado) or NOMBRE_DE_ESTADO[self.estado]))
        partes.append(('Registros', {VIGENTES: 'Vigentes (sin anulados)', ANULADOS: 'Solo anulados', TODOS: 'Vigentes y anulados'}[self.registros]))
        if not self.bitacora:
            partes.append(('Observaciones de bitácora', 'Excluidas'))
        return partes


# ---------------------------------------------------------------------------
# Reportes: los mismos datos para la pantalla, la impresión y Excel
# ---------------------------------------------------------------------------
def medidas_visibles():
    """Las medidas que se muestran en un registro: aplicadas y pendientes de aprobación (no las anuladas ni rechazadas)."""
    return Prefetch('medidas_aplicadas', queryset=MedidaAplicada.objects.filter(estado__in=MedidaAplicada.VIGENTES))


def con_relaciones(registros):
    return (
        registros.select_related('alumno', 'grado', 'grupo__nombre', 'grupo__grado', 'registrado_por', 'responsable', 'suspension__autorizada_por', 'periodo')
        .prefetch_related(medidas_visibles(), 'contactos')
    )


def _conteo(registros, campo, nombre):
    """[(nombre, total)] de registros por un campo, de más a menos (cada registro cuenta una vez). Cada nivel tiene su
    catálogo: si el conjunto abarca varios niveles, el nombre lleva el suyo («Agresión verbal · Primaria»)."""
    filas = list(registros.order_by().values(campo, nombre, 'nivel').annotate(total=Count('pk', distinct=True)).order_by('-total', nombre))
    varios = len({fila['nivel'] for fila in filas}) > 1
    return [(f'{fila[nombre]} · {NOMBRE_DE_NIVEL[fila["nivel"]]}' if varios else fila[nombre], fila['total']) for fila in filas]


def totales_por(registros):
    """Totales por categoría, motivo y gravedad (cada registro una vez)."""
    gravedades = registros.order_by().values('gravedad').annotate(total=Count('pk', distinct=True))
    por_gravedad = {fila['gravedad']: fila['total'] for fila in gravedades}
    return {
        'categorias': _conteo(registros, 'categoria', 'categoria_nombre'),
        'motivos': _conteo(registros, 'motivo', 'motivo_nombre'),
        'gravedades': [(nombre, por_gravedad.get(clave, 0)) for clave, nombre in GRAVEDADES] + (
            [('Sin gravedad', por_gravedad[''])] if por_gravedad.get('') else []
        ),
    }


def evolucion(registros, inicio, fin):
    """Registros por semana (rangos de hasta ~3 meses) o por mes: [(etiqueta, incidencias, positivas)]."""
    if not registros.exists():
        return 'semana', []
    if inicio is None or fin is None:
        fechas = registros.order_by().aggregate(primera=Min('fecha'), ultima=Max('fecha'))
        inicio, fin = inicio or fechas['primera'], fin or fechas['ultima']
    por_semana = (fin - inicio).days <= 92
    truncar = TruncWeek('fecha') if por_semana else TruncMonth('fecha')
    filas = (
        registros.order_by().annotate(bloque=truncar).values('bloque')
        .annotate(incidencias=Count('pk', filter=Q(tipo=INCIDENCIA), distinct=True), positivas=Count('pk', filter=Q(tipo=POSITIVA), distinct=True))
        .order_by('bloque')
    )
    salida = []
    for fila in filas:
        bloque = fila['bloque']
        bloque = bloque.date() if hasattr(bloque, 'date') else bloque
        if por_semana:
            etiqueta = f'Semana del {bloque:%d/%m/%Y}'
        else:
            etiqueta = date_format(bloque, 'F Y').capitalize()
        salida.append((etiqueta, fila['incidencias'], fila['positivas']))
    return ('semana' if por_semana else 'mes'), salida


def resumen_estadistico(registros, filtro, hoy=None):
    """El resumen del conjunto: incidentes (registros) y estudiantes involucrados por separado, lo más frecuente, medidas,
    suspensiones, seguimientos y la evolución. Cada registro cuenta una vez aunque tenga varias medidas."""
    hoy = hoy or timezone.localdate()
    inicio, fin, _ = filtro.rango()
    totales = registros.aggregate(
        incidencias=Count('pk', filter=Q(tipo=INCIDENCIA), distinct=True),
        positivas=Count('pk', filter=Q(tipo=POSITIVA), distinct=True),
        estudiantes=Count('alumno', distinct=True),
        estudiantes_con_incidencias=Count('alumno', filter=Q(tipo=INCIDENCIA), distinct=True),
        pendientes=Count('pk', filter=Q(estado=RegistroConducta.PENDIENTE), distinct=True),
        en_seguimiento=Count('pk', filter=Q(estado=RegistroConducta.EN_SEGUIMIENTO), distinct=True),
        cerrados=Count('pk', filter=Q(estado=RegistroConducta.CERRADO), distinct=True),
        vencidos=Count('pk', filter=Q(fecha_revision__lt=hoy) & ~Q(estado=RegistroConducta.CERRADO), distinct=True),
    )
    medidas = (
        MedidaAplicada.objects.filter(registro__in=registros.values('pk'), estado=APLICADA).order_by().values('nombre')
        .annotate(total=Count('registro', distinct=True)).order_by('-total', 'nombre')
    )
    suspensiones = Suspension.objects.filter(registro__in=registros.values('pk'), aprobacion=APROBADA)
    unidad, filas_evolucion = evolucion(registros, inicio, fin)
    maximo = max((i + p for _, i, p in filas_evolucion), default=0)
    return {
        **totales,
        'total': totales['incidencias'] + totales['positivas'],
        'categorias': _conteo(registros, 'categoria', 'categoria_nombre')[:10],
        'motivos': _conteo(registros, 'motivo', 'motivo_nombre')[:10],
        'gravedades': totales_por(registros.filter(tipo=INCIDENCIA))['gravedades'],
        'medidas': [(fila['nombre'], fila['total']) for fila in medidas],
        'registros_con_medidas': registros.filter(Exists(MedidaAplicada.objects.filter(registro=OuterRef('pk'), estado=APLICADA))).count(),
        'solicitudes_pendientes': Suspension.objects.filter(registro__in=registros.values('pk'), aprobacion=PENDIENTE).count(),
        'suspensiones': suspensiones.count(),
        'suspensiones_vigentes': suspensiones.filter(fecha_inicio__lte=hoy, fecha_fin__gte=hoy).count(),
        'estudiantes_suspendidos': suspensiones.values('registro__alumno').distinct().count(),
        'unidad': unidad,
        'evolucion': [
            {'etiqueta': e, 'incidencias': i, 'positivas': p, 'ancho_i': round(100 * i / maximo) if maximo else 0,
             'ancho_p': round(100 * p / maximo) if maximo else 0}
            for e, i, p in filas_evolucion
        ],
    }


def historial_individual(registros, alumnos):
    """Por cada estudiante: sus datos, sus registros en orden de fecha y sus totales."""
    salida = []
    for alumno in alumnos:
        propios = list(con_relaciones(registros.filter(alumno=alumno)).order_by('fecha', 'hora', 'pk'))
        salida.append({
            'alumno': alumno,
            'inscripcion': inscripcion_actual(alumno),
            'registros': propios,
            'incidencias': sum(1 for r in propios if r.tipo == INCIDENCIA),
            'positivas': sum(1 for r in propios if r.tipo == POSITIVA),
            'suspensiones': sum(1 for r in propios if _suspension_aprobada(r)),
        })
    return salida


def _suspension_aprobada(registro):
    suspension = getattr(registro, 'suspension', None) if hasattr(registro, 'suspension') else None
    return suspension is not None and suspension.aprobada


def suspensiones_de(registros, hoy=None):
    hoy = hoy or timezone.localdate()
    filas = (
        Suspension.objects.filter(registro__in=registros.values('pk')).exclude(aprobacion=CANCELADA)
        .select_related('registro__alumno', 'autorizada_por', 'solicitada_por').order_by('fecha_inicio', 'registro__alumno__apellido_paterno')
    )
    return [{'suspension': s, 'registro': s.registro, 'estado': s.estado_en(hoy),
             'estado_display': Suspension.ESTADOS.get(s.estado_en(hoy)) or s.get_aprobacion_display()} for s in filas]


def ordenados_por_nivel(registros):
    return registros.order_by(orden_de_nivel('nivel'), 'grado__numero', 'grupo_texto', 'fecha', 'hora', 'pk')


# ---------------------------------------------------------------------------
# El expediente del estudiante
# ---------------------------------------------------------------------------
def linea_de_tiempo(alumno):
    """Todo su historial de conducta, del más reciente al más antiguo (los anulados, marcados), con sus totales vigentes."""
    registros = list(con_relaciones(RegistroConducta.objects.filter(alumno=alumno)).order_by('-fecha', '-hora', '-pk'))
    vigentes = [r for r in registros if not r.anulado]
    return {
        'registros': registros,
        'incidencias': sum(1 for r in vigentes if r.tipo == INCIDENCIA),
        'positivas': sum(1 for r in vigentes if r.tipo == POSITIVA),
        'suspensiones': sum(1 for r in vigentes if _suspension_aprobada(r)),
        'abiertos': sum(1 for r in vigentes if r.estado != RegistroConducta.CERRADO and r.tipo == INCIDENCIA),
    }
