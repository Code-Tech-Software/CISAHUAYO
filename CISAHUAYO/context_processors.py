"""Datos disponibles en todas las plantillas."""
from django.urls import NoReverseMatch, reverse

# Navegación lateral. `ruta` es el nombre de la URL (con namespace si lo tiene).
# Mientras una ruta no exista, el enlace del menú apunta a "#" y se activará
# solo en cuanto se registre la URL con ese nombre.
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
            {'etiqueta': 'Alumnos', 'icono': 'graduation-cap', 'ruta': 'alumnos:lista'},
            {'etiqueta': 'Tutores', 'icono': 'users', 'ruta': 'tutores:lista'},
            {'etiqueta': 'Profesores', 'icono': 'presentation', 'ruta': 'profesores:lista'},
            {'etiqueta': 'Inscripciones', 'icono': 'clipboard-list', 'ruta': 'inscripciones:lista'},
        ),
    },
    {
        'titulo': 'Académico',
        'elementos': (
            {'etiqueta': 'Ciclos escolares', 'icono': 'calendar-range', 'ruta': 'ciclos:lista'},
            {'etiqueta': 'Grados', 'icono': 'layers', 'ruta': 'grados:lista'},
            {'etiqueta': 'Materias', 'icono': 'book-open', 'ruta': 'materias:lista'},
            {'etiqueta': 'Horarios', 'icono': 'clock', 'ruta': 'horarios:lista'},
            {'etiqueta': 'Asistencias', 'icono': 'user-check', 'ruta': 'asistencias:inicio'},
        ),
    },
)

# Acciones del buscador de comandos (Ctrl+K). Solo aparecen cuando su ruta existe.
ACCIONES_RAPIDAS = (
    {'etiqueta': 'Nuevo alumno', 'icono': 'plus', 'ruta': 'alumnos:crear'},
    {'etiqueta': 'Nuevo tutor', 'icono': 'plus', 'ruta': 'tutores:crear'},
    {'etiqueta': 'Nueva inscripción', 'icono': 'plus', 'ruta': 'inscripciones:crear'},
    {'etiqueta': 'Nuevo ciclo escolar', 'icono': 'plus', 'ruta': 'ciclos:crear'},
    {'etiqueta': 'Nuevo grado', 'icono': 'plus', 'ruta': 'grados:crear'},
    {'etiqueta': 'Nueva materia', 'icono': 'plus', 'ruta': 'materias:crear'},
    {'etiqueta': 'Nuevo profesor', 'icono': 'plus', 'ruta': 'profesores:crear'},
    {'etiqueta': 'Pantalla de entrada', 'icono': 'user-check', 'ruta': 'asistencias:kiosco'},
    {'etiqueta': 'Nueva justificación', 'icono': 'plus', 'ruta': 'asistencias:justificacion_crear'},
)

# Si existe una URL con este nombre, el buscador ofrece "Buscar «texto» en todo
# el sistema" y la envía con ?q=texto.
RUTA_BUSQUEDA = 'buscar'


def _resolver(ruta):
    try:
        return reverse(ruta)
    except NoReverseMatch:
        return ''


def navegacion(request):
    """Construye el menú lateral y marca el elemento activo.

    Se activa el elemento cuya URL sea la coincidencia más específica con la
    ruta actual, para que /alumnos/ no quede activo dentro de /alumnos/1/inscripciones/.
    """
    secciones = []
    mejor = None
    mejor_longitud = 0

    for seccion in NAVEGACION:
        elementos = []
        for elemento in seccion['elementos']:
            url = _resolver(elemento['ruta'])
            coincide = bool(url) and (
                request.path == url
                if elemento.get('exacto')
                else request.path.startswith(url)
            )
            item = {**elemento, 'url': url or '#', 'disponible': bool(url), 'activo': False}
            if coincide and len(url) > mejor_longitud:
                mejor, mejor_longitud = item, len(url)
            elementos.append(item)
        secciones.append({'titulo': seccion['titulo'], 'elementos': elementos})

    if mejor:
        mejor['activo'] = True

    acciones = []
    for accion in ACCIONES_RAPIDAS:
        url = _resolver(accion['ruta'])
        if url:
            acciones.append({**accion, 'url': url})

    return {
        'navegacion': secciones,
        'acciones_rapidas': acciones,
        'busqueda_url': _resolver(RUTA_BUSQUEDA),
    }
