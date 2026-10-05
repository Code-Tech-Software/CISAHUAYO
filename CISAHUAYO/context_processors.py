"""Datos disponibles en todas las plantillas."""
from django.db import DatabaseError
from django.urls import NoReverseMatch, reverse

# Navegación lateral. `ruta` es el nombre de la URL (con namespace si lo tiene).
# Mientras una ruta no exista, el enlace del menú apunta a "#" y se activará
# solo en cuanto se registre la URL con ese nombre.
#
# Cada elemento se muestra solo a quien tiene el permiso indicado en `permiso` (el de «ver» de ese módulo; sin
# `permiso`, a todo el que haya iniciado sesión). Si una sección tiene varias pantallas de entrada, `destinos` lista
# (permiso, ruta) en orden de preferencia: el enlace lleva a la primera a la que la persona tiene acceso, así nadie
# aterriza en una página que le negaría el paso.
NAVEGACION = (
    {
        'titulo': None,
        'elementos': (
            {'etiqueta': 'Panel de control', 'icono': 'layout-dashboard', 'ruta': 'inicio', 'exacto': True},
        ),
    },
    {
        'titulo': 'Gestión escolar',
        'elementos': (
            {'etiqueta': 'Alumnos', 'icono': 'graduation-cap', 'ruta': 'alumnos:lista', 'permiso': 'Alumnos.view_alumno'},
            {'etiqueta': 'Tutores', 'icono': 'users', 'ruta': 'tutores:lista', 'permiso': 'Alumnos.view_tutor'},
            {'etiqueta': 'Profesores', 'icono': 'presentation', 'ruta': 'profesores:lista', 'permiso': 'Alumnos.view_profesor'},
            {'etiqueta': 'Inscripciones', 'icono': 'clipboard-list', 'ruta': 'inscripciones:lista', 'permiso': 'Alumnos.view_inscripcion'},
        ),
    },
    {
        'titulo': 'Académico',
        'elementos': (
            {'etiqueta': 'Ciclos escolares', 'icono': 'calendar-range', 'ruta': 'ciclos:lista', 'permiso': 'Alumnos.view_cicloescolar'},
            {'etiqueta': 'Grados', 'icono': 'layers', 'ruta': 'grados:lista', 'permiso': 'Alumnos.view_grado'},
            {'etiqueta': 'Materias', 'icono': 'book-open', 'ruta': 'materias:lista', 'permiso': 'Alumnos.view_materia'},
            {'etiqueta': 'Horarios', 'icono': 'clock', 'ruta': 'horarios:lista', 'permiso': 'Alumnos.view_horariomateria'},
            {
                'etiqueta': 'Asistencias', 'icono': 'user-check', 'ruta': 'asistencias:inicio',
                'destinos': (
                    ('Alumnos.view_asistenciageneral', 'asistencias:inicio'),
                    ('Alumnos.view_asistenciamateria', 'asistencias:clases'),
                    ('Alumnos.view_justificacion', 'asistencias:justificaciones'),
                    ('Alumnos.add_asistenciageneral', 'asistencias:kiosco'),
                    ('Alumnos.view_configuracionasistencia', 'asistencias:ajustes'),
                ),
            },
        ),
    },
    {
        'titulo': 'Sistema',
        'elementos': (
            {'etiqueta': 'Usuarios', 'icono': 'user', 'ruta': 'usuarios:lista', 'permiso': 'auth.view_user'},
            {'etiqueta': 'Roles y permisos', 'icono': 'shield-check', 'ruta': 'roles:lista', 'permiso': 'Usuarios.view_rol'},
        ),
    },
)

# Acciones del buscador de comandos (Ctrl+K). Solo aparecen cuando su ruta existe y la persona tiene el permiso.
ACCIONES_RAPIDAS = (
    {'etiqueta': 'Nuevo alumno', 'icono': 'plus', 'ruta': 'alumnos:crear', 'permiso': 'Alumnos.add_alumno'},
    {'etiqueta': 'Nuevo tutor', 'icono': 'plus', 'ruta': 'tutores:crear', 'permiso': 'Alumnos.add_tutor'},
    {'etiqueta': 'Nueva inscripción', 'icono': 'plus', 'ruta': 'inscripciones:crear', 'permiso': 'Alumnos.add_inscripcion'},
    {'etiqueta': 'Nuevo ciclo escolar', 'icono': 'plus', 'ruta': 'ciclos:crear', 'permiso': 'Alumnos.add_cicloescolar'},
    {'etiqueta': 'Nuevo grado', 'icono': 'plus', 'ruta': 'grados:crear', 'permiso': 'Alumnos.add_grado'},
    {'etiqueta': 'Nueva materia', 'icono': 'plus', 'ruta': 'materias:crear', 'permiso': 'Alumnos.add_materia'},
    {'etiqueta': 'Nuevo profesor', 'icono': 'plus', 'ruta': 'profesores:crear', 'permiso': 'Alumnos.add_profesor'},
    {'etiqueta': 'Pantalla de entrada', 'icono': 'user-check', 'ruta': 'asistencias:kiosco', 'permiso': 'Alumnos.add_asistenciageneral'},
    {'etiqueta': 'Nueva justificación', 'icono': 'plus', 'ruta': 'asistencias:justificacion_crear', 'permiso': 'Alumnos.add_justificacion'},
    {'etiqueta': 'Nuevo usuario', 'icono': 'plus', 'ruta': 'usuarios:crear', 'permiso': 'auth.add_user'},
    {'etiqueta': 'Nuevo rol', 'icono': 'plus', 'ruta': 'roles:crear', 'permiso': 'Usuarios.add_rol'},
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

    Sin usuario en la petición (pruebas con RequestFactory) no se filtra nada.
    """
    if usuario is None:
        return elemento['ruta']
    destinos = elemento.get('destinos') or ((elemento.get('permiso'), elemento['ruta']),)
    for permiso, ruta in destinos:
        if permiso is None or usuario.has_perm(permiso):
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
        if url and (usuario is None or usuario.has_perm(accion['permiso'])):
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
