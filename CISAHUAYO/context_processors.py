"""Datos disponibles en todas las plantillas."""
from django.db import DatabaseError
from django.urls import NoReverseMatch, reverse
from django.utils.functional import SimpleLazyObject

from CISAHUAYO import temas


def _es_docente_que_pasa_lista(usuario):
    """Una cuenta de profesor que puede ver la asistencia por materia: su entrada a Asistencias es «Mis materias»."""
    if not usuario.has_perm('Alumnos.view_asistenciamateria'):
        return False
    from Usuarios.docentes import profesor_de
    return profesor_de(usuario) is not None


def _entra_a_calificaciones(usuario):
    """Un docente (sus materias) o quien ve o gestiona las calificaciones de todo el colegio."""
    return any(usuario.has_perm(p) for p in ('Calificaciones.capturar', 'Calificaciones.ver_todas', 'Calificaciones.gestionar_todas'))


def _entra_a_bitacoras(usuario):
    """Un docente (sus clases) o quien consulta o registra en las bitácoras de todos los grupos de su alcance."""
    return any(usuario.has_perm(p) for p in ('Bitacoras.registrar', 'Bitacoras.consultar_todas', 'Bitacoras.registrar_todas', 'Bitacoras.gestionar'))


def _registra_en_bitacoras(usuario):
    return usuario.has_perm('Bitacoras.registrar') or usuario.has_perm('Bitacoras.registrar_todas')


def _usa_mensajes(usuario):
    return usuario.has_perm('Mensajes.usar') or usuario.has_perm('Mensajes.contactar_familias')


def _usa_comunicados(usuario):
    """Quien recibe (un profesor), da seguimiento a lo que envía o gestiona los comunicados del colegio."""
    return any(usuario.has_perm(p) for p in ('Comunicados.recibir', 'Comunicados.seguimiento', 'Comunicados.enviar', 'Comunicados.gestionar'))


def _usa_prefectura(usuario):
    """Una cuenta de prefectura (su rol es de prefectura) que puede consultar: su menú es el de prefectura."""
    if not usuario.has_perm('Prefectura.consultar'):
        return False
    from Prefectura.alcance import es_cuenta_de_prefectura
    try:
        return es_cuenta_de_prefectura(usuario)
    except DatabaseError:   # aún no se aplican las migraciones
        return False


def _no_usa_prefectura(usuario):
    return not _usa_prefectura(usuario)


def _permiso_fuera_de_prefectura(permiso):
    """Para las cuentas de prefectura, su sección reemplaza a la general (aunque se les concediera el permiso)."""
    return lambda usuario: usuario.has_perm(permiso) and not _usa_prefectura(usuario)


def _prefectura_con(permiso):
    return lambda usuario: _usa_prefectura(usuario) and usuario.has_perm(permiso)


def _usa_retiros(usuario):
    from Retiros.alcance import usa_retiros
    return usa_retiros(usuario)


def _retiros_en_prefectura(usuario):
    return _usa_prefectura(usuario) and _usa_retiros(usuario)


def _retiros_fuera_de_prefectura(usuario):
    return _no_usa_prefectura(usuario) and _usa_retiros(usuario)


# Navegación lateral. `ruta` es el nombre de la URL (con namespace si lo tiene).
# Mientras una ruta no exista, el enlace del menú apunta a "#" y se activará
# solo en cuanto se registre la URL con ese nombre.
#
# Cada elemento se muestra solo a quien tiene el permiso indicado en `permiso` (el de «ver» de ese módulo; sin
# `permiso`, a todo el que haya iniciado sesión). Si una sección tiene varias pantallas de entrada, `destinos` lista
# (permiso, ruta) en orden de preferencia: el enlace lleva a la primera a la que la persona tiene acceso, así nadie
# aterriza en una página que le negaría el paso. El permiso de un destino también puede ser una función del usuario.
NAVEGACION = (
    {
        'titulo': None,
        'elementos': (
            {'etiqueta': 'Panel de control', 'icono': 'layout-dashboard', 'ruta': 'inicio', 'exacto': True, 'destinos': ((_no_usa_prefectura, 'inicio'),)},
        ),
    },
    {
        # Mensajes y comunicados en su propia categoría (pedido del 2026-10-18)
        'titulo': 'Comunicación',
        'elementos': (
            # Mensajería interna (también en los portales), con los mensajes sin leer junto a la etiqueta
            {'etiqueta': 'Mensajes', 'icono': 'message-circle', 'ruta': 'mensajes:inicio', 'destinos': ((_usa_mensajes, 'mensajes:inicio'),), 'contador': 'mensajes'},
            # Comunicados con seguimiento de lectura (también en los portales), con los recibidos sin leer junto a la etiqueta
            {'etiqueta': 'Comunicados', 'icono': 'megaphone', 'ruta': 'comunicados:inicio', 'destinos': ((_usa_comunicados, 'comunicados:inicio'),), 'contador': 'comunicados'},
            # Agenda / Calendario: todos la consultan (cada quien, los eventos de sus niveles y de todo el colegio)
            {'etiqueta': 'Agenda', 'icono': 'calendar', 'ruta': 'agenda:calendario'},
        ),
    },
    {
        # Solo para las cuentas de prefectura (Rol.es_prefectura): todo dentro de su alcance
        'titulo': 'Prefectura',
        'elementos': (
            {'etiqueta': 'Inicio', 'icono': 'layout-dashboard', 'ruta': 'prefectura:inicio', 'exacto': True, 'destinos': ((_usa_prefectura, 'prefectura:inicio'),)},
            {'etiqueta': 'Estudiantes', 'icono': 'graduation-cap', 'ruta': 'prefectura:estudiantes', 'destinos': ((_usa_prefectura, 'prefectura:estudiantes'),)},
            {
                'etiqueta': 'Asistencia', 'icono': 'user-check', 'ruta': 'prefectura:asistencia',
                'destinos': ((_usa_prefectura, 'prefectura:asistencia_registros'),),
                'activo_en': ('prefectura:accesos', 'prefectura:justificaciones'),
            },
            {'etiqueta': 'Conducta', 'icono': 'flag', 'ruta': 'conducta:lista', 'destinos': ((_usa_prefectura, 'conducta:lista'),)},
            {'etiqueta': 'Retiros anticipados', 'icono': 'log-out', 'ruta': 'retiros:lista', 'destinos': ((_retiros_en_prefectura, 'retiros:lista'),), 'contador': 'retiros'},
            {'etiqueta': 'Seguimiento', 'icono': 'clipboard-check', 'ruta': 'prefectura:seguimiento', 'destinos': ((_usa_prefectura, 'prefectura:seguimiento'),)},
            {'etiqueta': 'Reportes', 'icono': 'bar-chart', 'ruta': 'prefectura:reportes', 'destinos': ((_usa_prefectura, 'prefectura:reportes'),)},
        ),
    },
    {
        'titulo': 'Comunidad escolar',
        'elementos': (
            {'etiqueta': 'Estudiantes', 'icono': 'graduation-cap', 'ruta': 'alumnos:lista', 'permiso': 'Alumnos.view_alumno'},
            {'etiqueta': 'Tutores', 'icono': 'users', 'ruta': 'tutores:lista', 'permiso': 'Alumnos.view_tutor'},
            {'etiqueta': 'Profesores', 'icono': 'presentation', 'ruta': 'profesores:lista', 'permiso': 'Alumnos.view_profesor'},
        ),
    },
    {
        'titulo': 'Gestión académica',
        'elementos': (
            {'etiqueta': 'Ciclos escolares', 'icono': 'calendar-range', 'ruta': 'ciclos:lista', 'permiso': 'Alumnos.view_cicloescolar'},
            {'etiqueta': 'Grados', 'icono': 'layers', 'ruta': 'grados:lista', 'permiso': 'Alumnos.view_grado'},
            {'etiqueta': 'Grupos', 'icono': 'users', 'ruta': 'grupos:lista', 'permiso': 'Alumnos.view_grupo'},
            {'etiqueta': 'Periodos', 'icono': 'clipboard-check', 'ruta': 'periodos:lista', 'permiso': 'Alumnos.view_periodo'},
            {'etiqueta': 'Inscripciones a grupos', 'icono': 'clipboard-list', 'ruta': 'inscripciones:lista', 'permiso': 'Alumnos.view_inscripcion'},
            {'etiqueta': 'Materias', 'icono': 'book-open', 'ruta': 'materias:lista', 'permiso': 'Alumnos.view_materia'},
            {'etiqueta': 'Asignaciones de materias', 'icono': 'link', 'ruta': 'asignaciones:tablero', 'permiso': 'Alumnos.view_materiagrado'},
            {'etiqueta': 'Horarios', 'icono': 'clock', 'ruta': 'horarios:lista', 'permiso': 'Alumnos.view_horariomateria'},
            {'etiqueta': 'Calificaciones', 'icono': 'award', 'ruta': 'calificaciones:inicio', 'destinos': ((_entra_a_calificaciones, 'calificaciones:inicio'),)},
            {'etiqueta': 'Bitácoras por grupo', 'icono': 'notebook-pen', 'ruta': 'bitacoras:lista', 'destinos': ((_entra_a_bitacoras, 'bitacoras:lista'),)},
        ),
    },
    {
        # Asistencia y conducta del colegio (pedido del 2026-10-14). Las cuentas de prefectura no la ven: tienen su propia
        # sección «Prefectura» arriba (con su alcance), así que nadie ve las dos.
        'titulo': 'Prefectura',
        'elementos': (
            {
                'etiqueta': 'Asistencias', 'icono': 'user-check', 'ruta': 'asistencias:inicio',
                'destinos': (
                    ('Alumnos.view_asistenciageneral', 'asistencias:inicio'),
                    (_es_docente_que_pasa_lista, 'asistencias:docente'),   # un profesor entra a sus materias
                    ('Alumnos.view_justificacion', 'asistencias:justificaciones'),
                    ('Alumnos.add_asistenciageneral', 'asistencias:kiosco'),
                ),
            },
            {'etiqueta': 'Retiros anticipados', 'icono': 'log-out', 'ruta': 'retiros:lista', 'destinos': ((_retiros_fuera_de_prefectura, 'retiros:lista'),), 'contador': 'retiros'},
            {'etiqueta': 'Registro de conducta', 'icono': 'flag', 'ruta': 'conducta:lista', 'destinos': ((_permiso_fuera_de_prefectura('Conducta.view_registroconducta'), 'conducta:lista'),)},
            {'etiqueta': 'Reportes de conducta', 'icono': 'bar-chart', 'ruta': 'conducta:reportes', 'destinos': ((_permiso_fuera_de_prefectura('Conducta.view_registroconducta'), 'conducta:reportes'),)},
        ),
    },
    {
        'titulo': 'Sistema',
        'elementos': (
            {'etiqueta': 'Usuarios', 'icono': 'user', 'ruta': 'usuarios:lista', 'permiso': 'auth.view_user'},
            {'etiqueta': 'Roles y permisos', 'icono': 'shield-check', 'ruta': 'roles:lista', 'permiso': 'Usuarios.view_rol'},
            # Sin permiso: cada quien elige cómo ve el sistema; con permiso, ahí están los ajustes de asistencia y conducta
            {'etiqueta': 'Ajustes', 'icono': 'settings', 'ruta': 'ajustes:inicio'},
        ),
    },
)

# Acciones del buscador de comandos (Ctrl+K). Solo aparecen cuando su ruta existe y la persona tiene el permiso (las que
# no piden permiso, a todos).
ACCIONES_RAPIDAS = (
    {'etiqueta': 'Nuevo estudiante', 'icono': 'plus', 'ruta': 'alumnos:crear', 'permiso': 'Alumnos.add_alumno'},
    {'etiqueta': 'Nuevo comunicado', 'icono': 'megaphone', 'ruta': 'comunicados:crear', 'permiso': 'Comunicados.enviar'},
    {'etiqueta': 'Nueva entrada de bitácora', 'icono': 'notebook-pen', 'ruta': 'bitacoras:crear', 'permiso': _registra_en_bitacoras},
    {'etiqueta': 'Nuevo tutor', 'icono': 'plus', 'ruta': 'tutores:crear', 'permiso': 'Alumnos.add_tutor'},
    {'etiqueta': 'Nueva inscripción', 'icono': 'plus', 'ruta': 'inscripciones:crear', 'permiso': 'Alumnos.add_inscripcion'},
    {'etiqueta': 'Nuevo ciclo escolar', 'icono': 'plus', 'ruta': 'ciclos:crear', 'permiso': 'Alumnos.add_cicloescolar'},
    {'etiqueta': 'Nuevo grado', 'icono': 'plus', 'ruta': 'grados:crear', 'permiso': 'Alumnos.add_grado'},
    {'etiqueta': 'Nueva materia', 'icono': 'plus', 'ruta': 'materias:crear', 'permiso': 'Alumnos.add_materia'},
    {'etiqueta': 'Nuevo profesor', 'icono': 'plus', 'ruta': 'profesores:crear', 'permiso': 'Alumnos.add_profesor'},
    {'etiqueta': 'Nuevo periodo de evaluación', 'icono': 'plus', 'ruta': 'periodos:crear', 'permiso': 'Alumnos.add_periodo'},
    {'etiqueta': 'Pantalla de entrada', 'icono': 'user-check', 'ruta': 'asistencias:kiosco', 'permiso': 'Alumnos.add_asistenciageneral'},
    {'etiqueta': 'Nueva justificación', 'icono': 'plus', 'ruta': 'asistencias:justificacion_crear', 'permiso': 'Alumnos.add_justificacion'},
    {'etiqueta': 'Registrar conducta', 'icono': 'plus', 'ruta': 'conducta:crear', 'permiso': 'Conducta.add_registroconducta'},
    {'etiqueta': 'Registrar conducta', 'icono': 'plus', 'ruta': 'conducta:crear', 'permiso': _prefectura_con('Prefectura.registrar')},
    {'etiqueta': 'Registrar entrada o salida', 'icono': 'clock', 'ruta': 'prefectura:acceso_crear', 'permiso': _prefectura_con('Prefectura.registrar')},
    {'etiqueta': 'Justificar faltas o retardos', 'icono': 'plus', 'ruta': 'prefectura:justificar', 'permiso': _prefectura_con('Prefectura.justificar')},
    {'etiqueta': 'Nuevo usuario', 'icono': 'plus', 'ruta': 'usuarios:crear', 'permiso': 'auth.add_user'},
    {'etiqueta': 'Nuevo rol', 'icono': 'plus', 'ruta': 'roles:crear', 'permiso': 'Usuarios.add_rol'},
    {'etiqueta': 'Cambiar el tema de color', 'icono': 'palette', 'ruta': 'ajustes:inicio'},
)

# Si existe una URL con este nombre, el buscador ofrece "Buscar «texto» en todo
# el sistema" y la envía con ?q=texto.
RUTA_BUSQUEDA = 'buscar'


def _resolver(ruta):
    try:
        return reverse(ruta)
    except NoReverseMatch:
        return ''


def _destino_permitido(usuario, elemento):
    """La ruta a la que el usuario puede entrar para este elemento del menú, o None si no puede ver ninguna.

    El permiso de un destino puede ser también una función que recibe al usuario. Sin usuario en la petición (pruebas
    con RequestFactory) no se filtra nada.
    """
    if usuario is None:
        return elemento['ruta']
    destinos = elemento.get('destinos') or ((elemento.get('permiso'), elemento['ruta']),)
    for permiso, ruta in destinos:
        if permiso is None or (permiso(usuario) if callable(permiso) else usuario.has_perm(permiso)):
            return ruta
    return None


def navegacion(request):
    """Construye el menú lateral y marca el elemento activo.

    Solo incluye lo que el usuario puede ver según su rol. Se activa el elemento cuya URL sea la coincidencia más
    específica con la ruta actual, para que /alumnos/ no quede activo dentro de /alumnos/1/inscripciones/.
    """
    usuario = getattr(request, 'user', None)
    secciones = []
    mejor = None
    mejor_longitud = 0

    for seccion in NAVEGACION:
        elementos = []
        for elemento in seccion['elementos']:
            ruta_permitida = _destino_permitido(usuario, elemento)
            if ruta_permitida is None:
                continue
            base = _resolver(elemento['ruta'])
            destino = _resolver(ruta_permitida)
            coincide = bool(base) and (
                request.path == base
                if elemento.get('exacto')
                else request.path.startswith(base)
            )
            # Pantallas de la misma sección con otra dirección (p. ej. accesos y justificaciones dentro de Asistencia)
            for otra in elemento.get('activo_en', ()):
                otra_base = _resolver(otra)
                if otra_base and request.path.startswith(otra_base) and len(otra_base) > len(base or ''):
                    coincide, base = True, otra_base
            item = {**elemento, 'url': destino or '#', 'disponible': bool(destino), 'activo': False}
            if coincide and len(base) > mejor_longitud:
                mejor, mejor_longitud = item, len(base)
            elementos.append(item)
        if elementos:
            secciones.append({'titulo': seccion['titulo'], 'elementos': elementos})

    if mejor:
        mejor['activo'] = True

    acciones = []
    for accion in ACCIONES_RAPIDAS:
        url = _resolver(accion['ruta'])
        permiso = accion.get('permiso')
        if url and (usuario is None or permiso is None or (permiso(usuario) if callable(permiso) else usuario.has_perm(permiso))):
            if any(a['ruta'] == accion['ruta'] for a in acciones):
                continue   # la misma acción por dos caminos (administración y prefectura)
            acciones.append({**accion, 'url': url})

    contexto = {
        'navegacion': secciones,
        'acciones_rapidas': acciones,
        'busqueda_url': _resolver(RUTA_BUSQUEDA),
    }
    if usuario is not None and usuario.is_authenticated:
        from Usuarios.seguridad import rol_de
        try:
            contexto['rol_usuario'] = rol_de(usuario)
        except DatabaseError:
            # Aún no se han aplicado las migraciones de Usuarios: el resto del sistema debe seguir funcionando
            contexto['rol_usuario'] = None
    return contexto


def apariencia(request):
    """El tema de color y el menú lateral de quien navega (los predeterminados sin sesión o sin perfil todavía).

    Se consulta solo si la plantilla lo usa (base.html lo pone en <html> para que la página se pinte ya con sus colores).
    """
    def calcular():
        clave, menu = temas.PREDETERMINADO, temas.MENU_CLARO
        usuario = getattr(request, 'user', None)
        if usuario is not None and usuario.is_authenticated:
            from Usuarios.models import PerfilUsuario
            try:
                fila = PerfilUsuario.objects.filter(usuario=usuario).values_list('tema', 'menu_lateral').first()
            except DatabaseError:   # aún no se aplica la migración de Usuarios
                fila = None
            if fila:
                clave, menu = fila
        tema = temas.tema(clave)
        return {
            'tema': tema['clave'], 'color': tema['color'], 'menu_de_color': menu == temas.MENU_DE_COLOR,
            'fuentes': temas.url_de_fuentes(tema['clave']),
        }

    return {'apariencia': SimpleLazyObject(calcular)}
