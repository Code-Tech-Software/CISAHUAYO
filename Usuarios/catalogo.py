"""Catálogo de módulos y funciones del sistema, y qué permiso de Django exige cada acción.

Es la única fuente de verdad de la matriz de permisos de los roles: lo que aquí se declara es lo que se puede conceder
desde «Roles y permisos». Cada **módulo** (una sección del menú) agrupa **funciones**, y cada función tiene hasta cuatro
**acciones** (ver, crear, editar, dar de baja), cada una respaldada por un permiso estándar de Django (`app.codename`),
el mismo que las vistas exigen con `requiere_permisos(...)` y las plantillas consultan con `perms.…`.

Para ofrecer un permiso nuevo basta añadirlo aquí; una prueba (Usuarios/test_catalogo.py) comprueba que todo permiso que
el código del proyecto pide exista en este catálogo, de modo que nada quede imposible de conceder.

Dependencias: «crear», «editar» y «dar de baja» necesitan poder «ver» la misma función (o lo que declare `requiere`);
al conceder una acción se concede también lo que necesita, y quitar «ver» quita lo que depende de ella.
"""
from dataclasses import dataclass, field

ACCIONES = (('ver', 'Ver'), ('crear', 'Crear'), ('editar', 'Editar'), ('baja', 'Dar de baja'))
NOMBRE_DE_ACCION = dict(ACCIONES)
_PREFIJOS = {'ver': 'view', 'crear': 'add', 'editar': 'change', 'baja': 'delete'}


def _permisos(modelo, acciones=('ver', 'crear', 'editar', 'baja'), app='Alumnos'):
    return {accion: f'{app}.{_PREFIJOS[accion]}_{modelo}' for accion in acciones}


@dataclass(frozen=True)
class Funcion:
    nombre: str
    permisos: dict                                   # acción -> 'app.codename'
    ayuda: dict = field(default_factory=dict)        # acción -> qué permite exactamente
    etiquetas: dict = field(default_factory=dict)    # acción -> nombre propio (p. ej. «Usar» en lugar de «Crear»)
    requiere: tuple = ()                             # permisos de otras funciones que esta necesita

    def etiqueta(self, accion):
        return self.etiquetas.get(accion) or NOMBRE_DE_ACCION[accion]


@dataclass(frozen=True)
class Modulo:
    clave: str
    nombre: str
    icono: str
    descripcion: str
    funciones: tuple


MODULOS = (
    Modulo('alumnos', 'Alumnos', 'graduation-cap', 'El padrón de alumnos, sus perfiles y sus credenciales.', (
        Funcion('Alumnos', _permisos('alumno'), ayuda={
            'ver': 'Consultar el padrón y los perfiles, y exportarlos a CSV.',
            'crear': 'Registrar alumnos nuevos.',
            'editar': 'Editar sus datos y tutores, cambiar su estatus y restablecer su contraseña.',
            'baja': 'Dar de baja a un alumno (se conserva su historial).',
        }),
    )),
    Modulo('tutores', 'Tutores', 'users', 'Padres, madres y responsables, y su vínculo con los alumnos.', (
        Funcion('Tutores', _permisos('tutor'), ayuda={
            'ver': 'Consultar tutores y exportarlos a CSV.',
            'crear': 'Registrar tutores nuevos.',
            'editar': 'Editar sus datos y sus vínculos con los alumnos.',
            'baja': 'Dar de baja a un tutor (se conserva su historial).',
        }),
    )),
    Modulo('profesores', 'Profesores', 'presentation', 'El personal docente del colegio.', (
        Funcion('Profesores', _permisos('profesor'), ayuda={
            'ver': 'Consultar profesores, sus materias y su horario, y exportarlos a CSV.',
            'crear': 'Registrar profesores nuevos.',
            'editar': 'Editar sus datos y reactivarlos.',
            'baja': 'Dar de baja a un profesor.',
        }),
    )),
    Modulo('inscripciones', 'Inscripciones', 'clipboard-list', 'En qué grado está cada alumno en cada ciclo escolar.', (
        Funcion('Inscripciones', _permisos('inscripcion'), ayuda={
            'ver': 'Consultar las inscripciones y exportarlas a CSV.',
            'crear': 'Inscribir alumnos, también de forma masiva (reinscripción).',
            'editar': 'Cambiar el grado o el estatus de una inscripción.',
            'baja': 'Dar de baja una inscripción.',
        }),
    )),
    Modulo('ciclos', 'Ciclos escolares', 'calendar-range', 'Los periodos del colegio. Solo hay un ciclo actual.', (
        Funcion('Ciclos escolares', _permisos('cicloescolar', ('ver', 'crear', 'editar')), ayuda={
            'ver': 'Consultar los ciclos y su avance.',
            'crear': 'Crear ciclos escolares nuevos.',
            'editar': 'Editar un ciclo, marcarlo como actual o cerrarlo.',
        }),
    )),
    Modulo('grados', 'Grados', 'layers', 'Los grados del colegio (hay un solo grupo por grado).', (
        Funcion('Grados', _permisos('grado'), ayuda={
            'ver': 'Consultar los grados, sus alumnos y materias, y exportar la lista.',
            'crear': 'Crear grados.',
            'editar': 'Editar un grado.',
            'baja': 'Dar de baja un grado.',
        }),
    )),
    Modulo('materias', 'Materias', 'book-open', 'El catálogo de materias y su plan por grado.', (
        Funcion('Catálogo de materias', _permisos('materia'), ayuda={
            'ver': 'Consultar las materias, y exportarlas a CSV.',
            'crear': 'Registrar materias nuevas.',
            'editar': 'Editar una materia y reactivarla.',
            'baja': 'Dar de baja una materia.',
        }),
        Funcion('Plan de materias por grado', _permisos('materiagrado', ('crear', 'editar', 'baja')), requiere=('Alumnos.view_materia',), ayuda={
            'crear': 'Asignar materias a un grado en un ciclo, o copiar el plan de otro ciclo.',
            'editar': 'Cambiar la asignación y elegir el profesor que imparte cada materia.',
            'baja': 'Quitar una materia de un grado.',
        }),
    )),
    Modulo('horarios', 'Horarios', 'clock', 'El horario semanal de cada grado.', (
        Funcion('Horarios', _permisos('horariomateria'), ayuda={
            'ver': 'Consultar los horarios por grado, profesor y materia.',
            'crear': 'Agregar bloques al horario.',
            'editar': 'Cambiar el día o la hora de un bloque.',
            'baja': 'Quitar bloques del horario.',
        }),
    )),
    Modulo('asistencias', 'Asistencias', 'user-check', 'La entrada al colegio, el pase de lista y las justificaciones.', (
        Funcion('Pantalla de entrada', {'crear': 'Alumnos.add_asistenciageneral'}, etiquetas={'crear': 'Usar'}, ayuda={
            'crear': 'Usar la pantalla de la entrada: registrar la asistencia con la credencial o la referencia del alumno.',
        }),
        Funcion('Asistencia del día y reportes', {'ver': 'Alumnos.view_asistenciageneral', 'editar': 'Alumnos.change_asistenciageneral'}, ayuda={
            'ver': 'Consultar la asistencia del día, los reportes y el historial de cada alumno, y exportarlos.',
            'editar': 'Corregir la asistencia general de un alumno.',
        }),
        Funcion('Cierre del día', {'crear': 'Alumnos.add_cierredia'}, etiquetas={'crear': 'Cerrar'}, requiere=('Alumnos.view_asistenciageneral',), ayuda={
            'crear': 'Cerrar el día: quien no entró queda con falta.',
        }),
        Funcion('Pase de lista por materia', {'ver': 'Alumnos.view_asistenciamateria', 'editar': 'Alumnos.change_asistenciamateria'}, etiquetas={'editar': 'Pasar lista'}, ayuda={
            'ver': 'Consultar las clases del día y su asistencia.',
            'editar': 'Pasar lista: marcar faltas, retardos y justificantes en cada clase.',
        }),
        Funcion('Justificaciones', _permisos('justificacion'), etiquetas={'baja': 'Anular'}, ayuda={
            'ver': 'Consultar las justificaciones de faltas.',
            'crear': 'Justificar la falta general o solo algunas materias.',
            'editar': 'Editar una justificación y reactivarla.',
            'baja': 'Anular una justificación.',
        }),
        Funcion('Ajustes de asistencia', {'ver': 'Alumnos.view_configuracionasistencia', 'editar': 'Alumnos.change_configuracionasistencia'}, ayuda={
            'ver': 'Consultar la hora de entrada, la tolerancia y los días sin clases.',
            'editar': 'Cambiar la hora de entrada y la tolerancia.',
        }),
        Funcion('Días sin clases', {'crear': 'Alumnos.add_dianolectivo', 'baja': 'Alumnos.delete_dianolectivo'}, etiquetas={'baja': 'Quitar'},
                requiere=('Alumnos.view_configuracionasistencia',), ayuda={
            'crear': 'Registrar días sin clases (puentes, suspensiones).',
            'baja': 'Quitar un día sin clases.',
        }),
    )),
    Modulo('seguridad', 'Usuarios y roles', 'shield-check', 'Quién puede entrar al sistema y qué puede hacer.', (
        Funcion('Usuarios', _permisos('user', app='auth'), etiquetas={'baja': 'Desactivar'}, ayuda={
            'ver': 'Consultar las cuentas de usuario y sus permisos.',
            'crear': 'Crear cuentas (se les asigna un rol; solo roles que quien las crea también tiene).',
            'editar': 'Editar cuentas, cambiar su rol, reactivarlas y restablecer contraseñas.',
            'baja': 'Desactivar cuentas (no se borran).',
        }),
        Funcion('Roles y permisos', _permisos('rol', app='Usuarios'), etiquetas={'baja': 'Desactivar'}, ayuda={
            'ver': 'Consultar los roles y qué permite cada uno.',
            'crear': 'Crear roles y copiar uno existente.',
            'editar': 'Cambiar los permisos de un rol: llega a todos los usuarios que lo tienen.',
            'baja': 'Desactivar roles (no se borran).',
        }),
    )),
)


# ---------------------------------------------------------------------------
# Consultas sobre el catálogo
# ---------------------------------------------------------------------------
def _requisitos():
    """permiso -> permisos que necesita (los de «ver» de su función y lo que declare `requiere`)."""
    requisitos = {}
    for modulo in MODULOS:
        for funcion in modulo.funciones:
            ver = funcion.permisos.get('ver')
            for accion, permiso in funcion.permisos.items():
                necesarios = set(funcion.requiere)
                if ver and accion != 'ver':
                    necesarios.add(ver)
                requisitos[permiso] = tuple(sorted(necesarios))
    return requisitos


REQUISITOS = _requisitos()
TODOS = frozenset(REQUISITOS)


def _etiquetas():
    etiquetas = {}
    for modulo in MODULOS:
        for funcion in modulo.funciones:
            for accion, permiso in funcion.permisos.items():
                etiquetas[permiso] = f'{funcion.nombre} · {funcion.etiqueta(accion)}'
    return etiquetas


ETIQUETAS = _etiquetas()


def etiqueta_de(permiso):
    """«Alumnos · Editar»; para un permiso fuera del catálogo, su código."""
    return ETIQUETAS.get(permiso, permiso)


def con_requisitos(permisos):
    """Los permisos pedidos más todo lo que necesitan (un permiso fuera del catálogo se descarta)."""
    resultado = {p for p in permisos if p in TODOS}
    pendientes = list(resultado)
    while pendientes:
        for necesario in REQUISITOS[pendientes.pop()]:
            if necesario not in resultado:
                resultado.add(necesario)
                pendientes.append(necesario)
    return resultado


def dependientes(permiso):
    """Los permisos que necesitan a este (directa o indirectamente): al quitarlo hay que quitarlos también."""
    resultado, pendientes = set(), [permiso]
    while pendientes:
        actual = pendientes.pop()
        for otro, necesarios in REQUISITOS.items():
            if actual in necesarios and otro not in resultado:
                resultado.add(otro)
                pendientes.append(otro)
    return resultado


def permisos_de_modulos(*claves, solo=None):
    """Los permisos de los módulos indicados; `solo` limita a ciertas acciones (p. ej. ('ver',))."""
    resultado = set()
    for modulo in MODULOS:
        if modulo.clave in claves:
            for funcion in modulo.funciones:
                for accion, permiso in funcion.permisos.items():
                    if solo is None or accion in solo:
                        resultado.add(permiso)
    return resultado


def resumen(permisos):
    """El catálogo con lo que `permisos` concede: para dibujar la matriz de solo lectura o los resúmenes.

    Devuelve una lista de módulos: {modulo, filas, concedidos, posibles}; cada fila lleva una celda por acción
    (None si la función no tiene esa acción) con {accion, nombre, permiso, tiene, ayuda}.
    """
    permisos = set(permisos)
    salida = []
    for modulo in MODULOS:
        filas, concedidos, posibles = [], 0, 0
        for funcion in modulo.funciones:
            celdas = []
            for accion, _ in ACCIONES:
                permiso = funcion.permisos.get(accion)
                if not permiso:
                    celdas.append(None)
                    continue
                tiene = permiso in permisos
                concedidos += tiene
                posibles += 1
                celdas.append({
                    'accion': accion, 'nombre': funcion.etiqueta(accion), 'permiso': permiso, 'tiene': tiene,
                    'etiqueta_propia': accion in funcion.etiquetas,
                    'ayuda': funcion.ayuda.get(accion, ''), 'requiere': ' '.join(REQUISITOS[permiso]),
                })
            filas.append({'funcion': funcion, 'celdas': celdas, 'concedidas': [c for c in celdas if c and c['tiene']]})
        salida.append({'modulo': modulo, 'filas': filas, 'concedidos': concedidos, 'posibles': posibles})
    return salida
