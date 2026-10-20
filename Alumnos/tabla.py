"""Lo que la tabla de estudiantes (Alumnos/views.alumno_lista) agrega a las filas de la página, con unas pocas consultas
que no crecen con el número de filas, y siempre con los permisos de quien consulta:

- El orden desde los encabezados (Estudiante, Grado actual y Edad).
- La asistencia de hoy (la entrada al colegio), solo con permiso de consultar la asistencia: llegó, retardo, falta
  (justificada o no) o sin registro; o, si no hay registro, suspensión autorizada o día sin clases de su nivel.
- Las señales junto al nombre, solo las que aplican: requiere atención (el panel de control), retiro anticipado de hoy
  (si atiende retiros y el estudiante está en su alcance), reunión próxima con la familia (si la puede ver), alergias,
  CURP que falta o no es válida y sin fotografía.
"""
from datetime import timedelta

from django.db import DatabaseError
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from .utils import CURP_RE

DIAS_DE_REUNIONES = 7   # cuántos días adelante se avisa de una reunión con la familia


def _hora(valor):
    """«7:52» (sin el cero inicial)."""
    return f'{valor.hour}:{valor.minute:02d}'


def columnas_de_orden(orden):
    """Los encabezados que ordenan la tabla (Estudiante, Grado actual y Edad): a qué orden lleva tocar cada uno (el
    contrario si ya ordena por él) y su aria-sort. El orden predeterminado (por nombre) no se escribe en la dirección."""
    columnas = {}
    for clave in ('nombre', 'grado', 'edad'):
        if orden == clave:
            columna = {'siguiente': f'-{clave}', 'aria': 'ascending', 'activa': True, 'ascendente': True}
        elif orden == f'-{clave}':
            columna = {'siguiente': clave, 'aria': 'descending', 'activa': True, 'ascendente': False}
        else:
            columna = {'siguiente': clave, 'aria': 'none', 'activa': False, 'ascendente': True}
        if columna['siguiente'] == 'nombre':
            columna['siguiente'] = None
        columnas[clave] = columna
    return columnas


# ---------------------------------------------------------------------------
# Asistencia de hoy
# ---------------------------------------------------------------------------
def asistencia_de_hoy(alumnos, hoy):
    """{id del estudiante: {'texto', 'tono', 'detalle'}} de su entrada al colegio hoy (la inscripción del ciclo actual)."""
    from .asistencias import alumnos_suspendidos, con_justificada_general, niveles_sin_clases
    from .models import AsistenciaGeneral
    ids = [alumno.pk for alumno in alumnos]
    registros = {
        registro.inscripcion.alumno_id: registro
        for registro in con_justificada_general(AsistenciaGeneral.objects.filter(
            inscripcion__alumno__in=ids, inscripcion__ciclo__activo=True, inscripcion__activa=True, fecha=hoy)).select_related('inscripcion')
    }
    sin_clases = niveles_sin_clases(hoy)
    suspendidos = alumnos_suspendidos(hoy)
    resultado = {}
    for alumno in alumnos:
        inscripcion = (getattr(alumno, 'inscripciones_actuales', None) or [None])[0]
        registro = registros.get(alumno.pk)
        if registro is not None:
            if registro.estado == 'PRESENTE':
                dato = {'texto': f'Llegó {_hora(registro.hora_entrada)}' if registro.hora_entrada else 'Presente', 'tono': 'success'}
            elif registro.estado == 'RETARDO':
                dato = {'texto': f'Retardo {_hora(registro.hora_entrada)}' if registro.hora_entrada else 'Retardo', 'tono': 'warning'}
            elif registro.justificada:
                dato = {'texto': 'Falta justificada', 'tono': 'info'}
            else:
                dato = {'texto': 'Falta', 'tono': 'danger'}
        elif inscripcion is None:
            dato = {'texto': '—', 'tono': '', 'detalle': 'Sin inscripción en el ciclo actual'}
        elif alumno.pk in suspendidos:
            dato = {'texto': 'Suspensión', 'tono': 'neutral', 'detalle': 'Tiene una suspensión autorizada hoy'}
        elif inscripcion.grado.nivel in sin_clases:
            dato = {'texto': 'Sin clases', 'tono': '', 'detalle': sin_clases[inscripcion.grado.nivel] or 'Día sin clases de su nivel'}
        else:
            dato = {'texto': 'Sin registro', 'tono': ''}
        resultado[alumno.pk] = dato
    return resultado


# ---------------------------------------------------------------------------
# Datos de otros módulos para las señales
# ---------------------------------------------------------------------------
def alertas_de_seguimiento(usuario):
    """{id del estudiante: alerta} de «Estudiantes que requieren atención» del panel de control, con los mismos permisos
    que ahí (asistencia y calificaciones) y en el ciclo actual. Si la consulta falla, la tabla se muestra sin ellas."""
    from Calificaciones.reglas import ve_todas
    asistencia, calificaciones = usuario.has_perm('Alumnos.view_asistenciageneral'), ve_todas(usuario)
    if not (asistencia or calificaciones):
        return {}
    from Panel import seguimiento
    from Panel.filtros import filtros_de
    try:
        lista = seguimiento.alertas(filtros_de({}), asistencia, calificaciones)
    except DatabaseError:
        return {}
    return {alerta.alumno.pk: alerta for alerta in lista}


def retiros_de_hoy(usuario, alumnos, hoy):
    """{id del estudiante: su retiro anticipado de hoy} (avisado o ya confirmado), si la cuenta atiende retiros y el
    estudiante está en su alcance (Retiros/alcance.py)."""
    from Retiros.alcance import alcance_de, condicion, usa_retiros
    if not usa_retiros(usuario):
        return {}
    from Retiros.models import RetiroEstudiante
    try:
        filas = (RetiroEstudiante.objects.filter(condicion(alcance_de(usuario)))
                 .filter(alumno__in=[a.pk for a in alumnos], fecha=hoy, estado__in=(RetiroEstudiante.AVISADO, RetiroEstudiante.RETIRADO))
                 .select_related('aviso').order_by('aviso__hora'))
        return {fila.alumno_id: fila for fila in filas}
    except DatabaseError:
        return {}


def reuniones_proximas(usuario, alumnos, hoy):
    """{id del estudiante: su siguiente reunión con la familia} de hoy a DIAS_DE_REUNIONES días (programada, confirmada
    o en curso; las de hoy que ya terminaron no), solo las que la cuenta puede ver (Reuniones/alcance.py)."""
    from Reuniones.alcance import Acceso, usa_reuniones
    if not usa_reuniones(usuario):
        return {}
    from Reuniones.models import EstudianteEnReunion, Reunion
    ahora = timezone.localtime().time()
    try:
        filas = (EstudianteEnReunion.objects
                 .filter(alumno__in=[a.pk for a in alumnos], reunion__in=Acceso(usuario).reuniones(), reunion__estado__in=Reunion.ACTIVAS,
                         reunion__fecha__gte=hoy, reunion__fecha__lte=hoy + timedelta(days=DIAS_DE_REUNIONES))
                 .select_related('reunion').order_by('reunion__fecha', 'reunion__hora_inicio'))
        proximas = {}
        for fila in filas:
            reunion = fila.reunion
            if reunion.fecha == hoy and reunion.estado != Reunion.EN_CURSO and reunion.hora_fin and reunion.hora_fin < ahora:
                continue
            proximas.setdefault(fila.alumno_id, reunion)
        return proximas
    except DatabaseError:
        return {}


# ---------------------------------------------------------------------------
# Las señales
# ---------------------------------------------------------------------------
def _texto_de_retiro(retiro):
    if retiro.estado == retiro.RETIRADO and retiro.salida_en:
        return f'Salió hoy a las {_hora(timezone.localtime(retiro.salida_en))} (retiro anticipado)'
    return f'Sale hoy a las {_hora(retiro.aviso.hora)} (retiro anticipado avisado por su tutor)'


def _texto_de_reunion(reunion, hoy):
    if reunion.estado == reunion.EN_CURSO:
        return 'Reunión con la familia en curso'
    if reunion.fecha == hoy:
        cuando = 'hoy'
    elif reunion.fecha == hoy + timedelta(days=1):
        cuando = 'mañana'
    else:
        cuando = f'el {date_format(reunion.fecha, "l j").lower()}'
    texto = f'Reunión con la familia {cuando} a las {_hora(reunion.hora_inicio)}'
    return f'{texto} (por confirmar)' if reunion.estado == reunion.PROGRAMADA else texto


def senales_de(alumno, hoy, alerta=None, retiro=None, reunion=None):
    """Las señales rápidas junto al nombre, solo las que aplican, de lo más urgente a lo informativo."""
    senales = []
    if alerta is not None:
        motivos = ' · '.join(texto for _, texto in alerta.motivos)
        senales.append({'clave': 'atencion', 'tono': alerta.prioridad, 'icono': 'triangle-alert',
                        'texto': f'Requiere atención (prioridad {alerta.texto_de_prioridad.lower()}): {motivos}'})
    if retiro is not None:
        senales.append({'clave': 'retiro', 'tono': retiro.estado.lower(), 'icono': 'log-out', 'texto': _texto_de_retiro(retiro),
                        'url': reverse('retiros:detalle', args=[retiro.aviso_id])})
    if reunion is not None:
        senales.append({'clave': 'reunion', 'icono': 'users', 'texto': _texto_de_reunion(reunion, hoy),
                        'url': reverse('reuniones:detalle', args=[reunion.pk])})
    alergias = (alumno.alergias or '').strip()
    if alergias:
        senales.append({'clave': 'salud', 'icono': 'heart',
                        'texto': f'Alergias: {alergias if len(alergias) <= 90 else alergias[:89] + "…"}'})
    if not CURP_RE.match(alumno.curp or ''):
        senales.append({'clave': 'curp', 'icono': 'circle-alert', 'texto': 'La CURP falta o no tiene un formato válido'})
    if not alumno.fotografia:
        senales.append({'clave': 'foto', 'icono': 'camera', 'texto': 'Sin fotografía'})
    return senales


def preparar_filas(usuario, alumnos):
    """Pone en cada estudiante de la página sus señales y, si la cuenta puede consultar la asistencia, su asistencia de
    hoy (`alumno.asistencia_hoy`). Devuelve si se muestra la columna de asistencia."""
    hoy = timezone.localdate()
    ve_asistencia = usuario.has_perm('Alumnos.view_asistenciageneral')
    if not alumnos:
        return ve_asistencia
    alertas = alertas_de_seguimiento(usuario)
    retiros = retiros_de_hoy(usuario, alumnos, hoy)
    reuniones = reuniones_proximas(usuario, alumnos, hoy)
    asistencia = asistencia_de_hoy(alumnos, hoy) if ve_asistencia else {}
    for alumno in alumnos:
        alumno.senales = senales_de(alumno, hoy, alertas.get(alumno.pk), retiros.get(alumno.pk), reuniones.get(alumno.pk))
        alumno.asistencia_hoy = asistencia.get(alumno.pk)
    return ve_asistencia
