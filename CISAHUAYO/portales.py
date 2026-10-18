"""Acceso a los portales de estudiantes y de tutores (pedido del 2026-10-14).

Las cuentas de los portales no son usuarios del sistema (django.contrib.auth): son los propios registros `Alumno` y
`Tutor`, que ya guardaban su contraseña cifrada (`contrasena`). Se administran desde Estudiantes y Tutores.

- Estudiante: entra con su correo electrónico. Tutor: con su usuario. Ambos con su contraseña.
- Solo entra una cuenta con estatus activo y con el acceso al portal activado (`acceso_portal`).
- Tras `MAXIMO_DE_INTENTOS` contraseñas equivocadas seguidas la cuenta se bloquea `MINUTOS_DE_BLOQUEO` minutos
  (también se puede desbloquear desde su ficha).
- Los mensajes no revelan si el correo o el usuario existen; el estado de la cuenta solo se dice con la contraseña
  correcta.
- La sesión del portal es propia (`CLAVE_DE_SESION`) y lleva una huella de la contraseña: si se restablece, las
  sesiones abiertas terminan. Entrar a un portal cierra la sesión del sistema que hubiera, y al revés.
"""
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache, wraps

from django.contrib import messages
from django.contrib.auth import logout as cerrar_sesion_del_sistema
from django.contrib.auth.hashers import check_password, make_password
from django.middleware.csrf import rotate_token
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import add_never_cache_headers
from django.utils.crypto import constant_time_compare, salted_hmac
from django.utils.http import urlencode

ESTUDIANTE, TUTOR = 'estudiante', 'tutor'
CLAVE_DE_SESION = '_cisahuayo_portal'
MAXIMO_DE_INTENTOS = 5
MINUTOS_DE_BLOQUEO = 15
# Pestaña de la pantalla de acceso y pantalla de inicio de cada portal
PESTANA = {ESTUDIANTE: 'estudiantes', TUTOR: 'tutores'}
INICIO = {ESTUDIANTE: 'portal_estudiantes:inicio', TUTOR: 'portal_tutores:inicio'}
SALIR = {ESTUDIANTE: 'portal_estudiantes:salir', TUTOR: 'portal_tutores:salir'}
NOMBRE = {ESTUDIANTE: 'Portal de estudiantes', TUTOR: 'Portal de tutores'}
ROTULO = {ESTUDIANTE: 'Estudiante', TUTOR: 'Tutor'}


_ESTATUS_ESTUDIANTE = {
    'BAJA': 'Tu registro está dado de baja',
    'EGRESADO': 'Tu registro es de un estudiante egresado',
    'SUSPENDIDO': 'Tu registro está suspendido',
}


@lru_cache(maxsize=1)
def _sin_cuenta():
    """Una contraseña cifrada cualquiera: se verifica contra ella cuando la cuenta no existe, para que la respuesta
    tarde lo mismo y no delate qué correos o usuarios están registrados."""
    return make_password('cuenta-que-no-existe')


class AccesoRechazado(Exception):
    """No se entra: `mensaje` es lo que ve la persona."""

    def __init__(self, mensaje):
        super().__init__(mensaje)
        self.mensaje = mensaje


def _modelo(tipo):
    from Alumnos.models import Alumno, Tutor
    return Alumno if tipo == ESTUDIANTE else Tutor


def buscar_cuenta(tipo, identificador):
    """La cuenta con ese correo (estudiante) o usuario (tutor), sin distinguir mayúsculas; None si no hay."""
    identificador = (identificador or '').strip()
    if not identificador:
        return None
    campo = 'correo_electronico__iexact' if tipo == ESTUDIANTE else 'usuario__iexact'
    return _modelo(tipo).objects.filter(**{campo: identificador}).first()


def bloqueada(cuenta, ahora=None):
    return bool(cuenta.bloqueado_hasta and cuenta.bloqueado_hasta > (ahora or timezone.now()))


def motivo_sin_acceso(tipo, cuenta):
    """Por qué una cuenta (con la contraseña ya verificada) no puede entrar, o '' si puede."""
    if tipo == ESTUDIANTE and cuenta.estatus != 'ACTIVO':
        return f'{_ESTATUS_ESTUDIANTE.get(cuenta.estatus, "Tu registro no está activo")}: no puedes entrar al portal. Acude a control escolar.'
    if tipo == TUTOR and cuenta.estatus != 'ACTIVO':
        return 'Tu registro de tutor está inactivo: no puedes entrar al portal. Acude a la dirección del colegio.'
    if not cuenta.acceso_portal:
        return 'Tu acceso al portal está desactivado. Acude a la dirección del colegio para que lo activen.'
    return ''


def _guardar(cuenta, *campos):
    cuenta.save(update_fields=list(campos))


def autenticar(tipo, identificador, contrasena, ahora=None):
    """La cuenta si las credenciales son correctas y puede entrar; si no, lanza AccesoRechazado con un mensaje claro."""
    ahora = ahora or timezone.now()
    que = 'El correo o la contraseña' if tipo == ESTUDIANTE else 'El usuario o la contraseña'
    incorrectas = f'{que} no son correctos. Revisa que estén bien escritos (en la contraseña importan las mayúsculas).'
    cuenta = buscar_cuenta(tipo, identificador)
    if cuenta is None or not cuenta.contrasena:
        check_password(contrasena or '', _sin_cuenta())
        raise AccesoRechazado(incorrectas)
    if bloqueada(cuenta, ahora):
        minutos = max(1, round((cuenta.bloqueado_hasta - ahora).total_seconds() / 60))
        raise AccesoRechazado(f'Por seguridad, la cuenta se bloqueó tras varios intentos fallidos. Intenta de nuevo en {minutos} minuto{"s" if minutos != 1 else ""} '
                              'o pide a la dirección del colegio que la desbloquee.')

    def actualizar_hash(contrasena_en_claro):   # si cambia el algoritmo de cifrado, se actualiza sin tocar la legible
        cuenta.contrasena = make_password(contrasena_en_claro)
        _guardar(cuenta, 'contrasena')

    if not check_password(contrasena or '', cuenta.contrasena, setter=actualizar_hash):
        cuenta.intentos_fallidos += 1
        if cuenta.intentos_fallidos >= MAXIMO_DE_INTENTOS:
            cuenta.intentos_fallidos, cuenta.bloqueado_hasta = 0, ahora + timedelta(minutes=MINUTOS_DE_BLOQUEO)
            _guardar(cuenta, 'intentos_fallidos', 'bloqueado_hasta')
            raise AccesoRechazado(f'Demasiados intentos fallidos: por seguridad, la cuenta queda bloqueada {MINUTOS_DE_BLOQUEO} minutos.')
        _guardar(cuenta, 'intentos_fallidos')
        restantes = MAXIMO_DE_INTENTOS - cuenta.intentos_fallidos
        aviso = f' Te queda{"n" if restantes != 1 else ""} {restantes} intento{"s" if restantes != 1 else ""} antes de que se bloquee.' if restantes <= 2 else ''
        raise AccesoRechazado(incorrectas + aviso)
    motivo = motivo_sin_acceso(tipo, cuenta)
    if motivo:
        raise AccesoRechazado(motivo)
    cuenta.intentos_fallidos, cuenta.bloqueado_hasta, cuenta.ultimo_acceso = 0, None, ahora
    _guardar(cuenta, 'intentos_fallidos', 'bloqueado_hasta', 'ultimo_acceso')
    return cuenta


# ---------------------------------------------------------------------------
# Sesión del portal
# ---------------------------------------------------------------------------
def _huella(tipo, cuenta):
    return salted_hmac(f'cisahuayo.portal.{tipo}', cuenta.contrasena).hexdigest()


def iniciar_sesion(request, tipo, cuenta):
    """Abre la sesión del portal. Si había una del sistema (o de otro portal), la cierra primero."""
    if request.user.is_authenticated:
        cerrar_sesion_del_sistema(request)
    request.session.flush()   # sesión nueva (otra clave): evita que alguien fije la sesión antes de entrar
    request.session[CLAVE_DE_SESION] = {'tipo': tipo, 'id': cuenta.pk, 'huella': _huella(tipo, cuenta)}
    rotate_token(request)


def cerrar_sesion(request):
    request.session.flush()


def salir(request, tipo):
    """Cierra la sesión del portal y muestra la pantalla de sesión cerrada (con la pestaña de ese portal para volver)."""
    cerrar_sesion(request)
    return render(request, 'registration/logged_out.html', {'acceso': PESTANA[tipo], 'portal_nombre': NOMBRE[tipo]})


def saludo(hora):
    return 'Buenos días' if hora.hour < 12 else ('Buenas tardes' if hora.hour < 19 else 'Buenas noches')


def _elemento(etiqueta, icono, url, activo, **extra):
    return {'etiqueta': etiqueta, 'icono': icono, 'url': url, 'disponible': True, 'activo': activo, **extra}


def navegacion(request, tipo, cuenta):
    """El menú lateral del portal, con el mismo formato que el del sistema (CISAHUAYO.context_processors): Inicio,
    Mensajes (con los no leídos), Comunicados (con los sin leer) y, para un tutor, cada uno de sus estudiantes."""
    inicio = reverse(INICIO[tipo])
    espacio = INICIO[tipo].split(':')[0]
    mensajes = reverse(f'{espacio}:mensajes:inicio')
    comunicados = reverse(f'{espacio}:comunicados:inicio')
    secciones = [{'titulo': None, 'elementos': [
        _elemento('Inicio', 'layout-dashboard', inicio, request.path == inicio),
        _elemento('Mensajes', 'message-circle', mensajes, request.path.startswith(mensajes), contador='mensajes'),
        _elemento('Comunicados', 'megaphone', comunicados, request.path.startswith(comunicados), contador='comunicados'),
    ]}]
    if tipo == TUTOR:
        # Retiros anticipados (2026-10-17): avisar que recogerá a sus hijos antes de la salida, con sus notificaciones
        retiros = reverse('portal_tutores:retiros:lista')
        secciones[0]['elementos'].append(
            _elemento('Retiros anticipados', 'log-out', retiros, request.path.startswith(retiros), contador='retiros'))
        from Alumnos.models import TutorAlumno
        estudiantes = []
        for vinculo in TutorAlumno.objects.filter(tutor=cuenta, activo=True).select_related('alumno').order_by('alumno__nombre'):
            url = reverse('portal_tutores:estudiante', args=[vinculo.alumno_id])
            estudiantes.append(_elemento(vinculo.alumno.nombre_completo, 'graduation-cap', url, request.path == url))
        if estudiantes:
            secciones.append({'titulo': 'Mis estudiantes', 'elementos': estudiantes})
    return secciones


def contexto(request):
    """Lo que usa la base de los portales (templates/portales/base.html): de qué portal es, quién entró y su menú."""
    tipo, cuenta = request.cuenta_portal_tipo, request.cuenta_portal
    return {
        'portal': {
            'tipo': tipo, 'nombre': NOMBRE[tipo], 'rotulo': ROTULO[tipo], 'cuenta': cuenta,
            'inicio': reverse(INICIO[tipo]), 'salir': reverse(SALIR[tipo]), 'saludo': saludo(timezone.localtime()),
        },
        'navegacion': navegacion(request, tipo, cuenta),
    }


def sesion(request):
    """(tipo, cuenta) de la sesión del portal vigente, o (None, None). Una cuenta que ya no puede entrar (baja,
    acceso desactivado, contraseña restablecida) ya no tiene sesión."""
    return sesion_de(request.session)


def sesion_de(sesion_django):
    """Lo mismo que `sesion`, a partir de la sesión de Django (también la de un WebSocket: scope['session'])."""
    datos = sesion_django.get(CLAVE_DE_SESION)
    if not isinstance(datos, dict) or datos.get('tipo') not in (ESTUDIANTE, TUTOR):
        return None, None
    tipo = datos['tipo']
    cuenta = _modelo(tipo).objects.filter(pk=datos.get('id')).first()
    if cuenta is None or not constant_time_compare(datos.get('huella', ''), _huella(tipo, cuenta)) or motivo_sin_acceso(tipo, cuenta):
        return tipo, None
    return tipo, cuenta


def url_de_acceso(tipo=None, siguiente=''):
    """La pantalla de inicio de sesión, con la pestaña del portal elegida y la página a la que se vuelve al entrar."""
    parametros = {}
    if tipo:
        parametros['acceso'] = PESTANA[tipo]
    if siguiente:
        parametros['next'] = siguiente
    url = reverse('login')
    return f'{url}?{urlencode(parametros)}' if parametros else url


def portal_requerido(tipo):
    """Protege una vista de un portal: sin la sesión de ese portal se va a la pantalla de acceso (con su pestaña
    elegida); una cuenta del sistema recibe 403 (los portales no son para el personal). Sus páginas no se guardan en
    caché: en una computadora compartida, «atrás» tras cerrar sesión no vuelve a mostrar los datos."""
    def decorador(vista):
        @wraps(vista)
        def protegida(request, *args, **kwargs):
            tipo_de_sesion, cuenta = sesion(request)
            if tipo_de_sesion == tipo and cuenta is not None:
                request.cuenta_portal, request.cuenta_portal_tipo = cuenta, tipo
                respuesta = vista(request, *args, **kwargs)
                add_never_cache_headers(respuesta)
                return respuesta
            if request.user.is_authenticated:
                raise PermissionDenied('Esta página es de un portal: inicia sesión con la cuenta de ese portal.')
            if tipo_de_sesion == tipo:   # tenía sesión pero ya no vale
                cerrar_sesion(request)
                messages.warning(request, 'Tu sesión terminó (tu cuenta cambió o ya no tiene acceso). Vuelve a iniciar sesión.')
            elif tipo_de_sesion is not None:
                messages.info(request, f'Esa página es del {NOMBRE[tipo].lower()}. Ya tienes una sesión abierta en el {NOMBRE[tipo_de_sesion].lower()}.')
            return redirect(url_de_acceso(tipo, request.get_full_path() if request.method == 'GET' else ''))
        protegida.portal_requerido = tipo
        return protegida
    return decorador


def administrar_acceso(cuenta, accion):
    """Una acción de la ficha del estudiante o del tutor sobre su acceso al portal ('activar', 'desactivar' o
    'desbloquear'). Guarda y regresa el mensaje para quien la hizo; ValueError si la acción no existe."""
    if accion == 'activar':
        cuenta.acceso_portal = True
        campos, mensaje = ['acceso_portal'], f'Se activó el acceso de {cuenta} al portal.'
    elif accion == 'desactivar':
        cuenta.acceso_portal = False
        campos, mensaje = ['acceso_portal'], f'Se desactivó el acceso de {cuenta} al portal: ya no puede entrar y, si tenía la sesión abierta, se cerró.'
    elif accion == 'desbloquear':
        cuenta.intentos_fallidos, cuenta.bloqueado_hasta = 0, None
        campos, mensaje = ['intentos_fallidos', 'bloqueado_hasta'], f'Se desbloqueó el acceso de {cuenta} al portal: ya puede volver a intentar.'
    else:
        raise ValueError('No se reconoce esa acción sobre el acceso al portal.')
    if any(campo.name == 'modificado' for campo in cuenta._meta.concrete_fields):
        campos.append('modificado')
    _guardar(cuenta, *campos)
    return mensaje


@dataclass
class EstadoDeCuenta:
    """Para la ficha del estudiante o del tutor: cómo está su acceso al portal."""
    clave: str     # 'activo', 'desactivado', 'bloqueado', 'sin_credencial', 'inactivo'
    texto: str
    tono: str      # clase de etiqueta


def estado_de_cuenta(tipo, cuenta, ahora=None):
    identificador = cuenta.correo_electronico if tipo == ESTUDIANTE else cuenta.usuario
    if not identificador or not cuenta.contrasena:
        falta = 'correo electrónico' if tipo == ESTUDIANTE and not identificador else ('usuario' if not identificador else 'contraseña')
        return EstadoDeCuenta('sin_credencial', f'Sin {falta}: todavía no puede entrar', 'tag--warning')
    if cuenta.estatus != 'ACTIVO':
        return EstadoDeCuenta('inactivo', f'No puede entrar: su estatus es «{cuenta.get_estatus_display()}»', 'tag--warning')
    if not cuenta.acceso_portal:
        return EstadoDeCuenta('desactivado', 'Acceso desactivado', 'tag--danger')
    if bloqueada(cuenta, ahora):
        return EstadoDeCuenta('bloqueado', f'Bloqueado por intentos fallidos hasta las {timezone.localtime(cuenta.bloqueado_hasta):%H:%M}', 'tag--danger')
    return EstadoDeCuenta('activo', 'Puede entrar', 'tag--success')
