"""Catálogo de módulos y funciones del sistema, y qué permiso de Django exige cada acción.

Es la única fuente de verdad de la matriz de permisos de los roles: lo que aquí se declara es lo que se puede conceder
desde «Roles y permisos». Cada **módulo** (una sección del menú) agrupa **funciones**, y cada función tiene hasta cuatro
**acciones** (ver, crear, editar, dar de baja), cada una respaldada por un permiso estándar de Django (`app.codename`),
el mismo que las vistas exigen con `requiere_permisos(...)` y las plantillas consultan con `perms.…`.

Para ofrecer un permiso nuevo basta añadirlo aquí; una prueba (Usuarios/test_catalogo.py) comprueba que todo permiso que
el código del proyecto pide exista en este catálogo, de modo que nada quede imposible de conceder.

Dependencias: «crear», «editar» y «dar de baja» necesitan poder «ver» la misma función (o lo que declare `requiere`);
al conceder una acción se concede también lo que necesita, y quitar «ver» quita lo que depende de ella.

Permisos reservados (`reservado`): no se conceden a cualquier rol. Justificar faltas es solo del administrador y de
prefectura (pedido del 2026-10-14): justificar desde Asistencias lo tiene únicamente el rol Administrador (por ser de
acceso total) y justificar desde Prefectura, únicamente los roles de prefectura.
"""
from dataclasses import dataclass, field

ACCIONES = (('ver', 'Ver'), ('crear', 'Crear'), ('editar', 'Editar'), ('baja', 'Dar de baja'))
# Quién puede tener un permiso reservado
ADMINISTRADOR, PREFECTURA = 'administrador', 'prefectura'
MOTIVO_RESERVADO = {
    ADMINISTRADOR: 'Exclusivo del rol Administrador.',
    PREFECTURA: 'Solo para roles de prefectura (marca «Rol de prefectura»).',
}
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
    reservado: dict = field(default_factory=dict)    # acción -> ADMINISTRADOR o PREFECTURA (no se da a cualquier rol)

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
    Modulo('alumnos', 'Estudiantes', 'graduation-cap', 'El padrón de estudiantes, sus perfiles y sus credenciales.', (
        Funcion('Estudiantes', _permisos('alumno'), ayuda={
            'ver': 'Consultar el padrón y los perfiles, y exportarlos a CSV.',
            'crear': 'Registrar estudiantes nuevos, uno por uno o varios a la vez importando un archivo CSV.',
            'editar': 'Editar sus datos y tutores, cambiar su estatus y restablecer su contraseña. Consultar la contraseña es exclusivo de los administradores.',
            'baja': 'Dar de baja a un estudiante (se conserva su historial).',
        }),
    )),
    Modulo('tutores', 'Tutores', 'users', 'Padres, madres y responsables, y su vínculo con los estudiantes.', (
        Funcion('Tutores', _permisos('tutor'), ayuda={
            'ver': 'Consultar tutores y exportarlos a CSV.',
            'crear': 'Registrar tutores nuevos, uno por uno o varios a la vez importando un archivo CSV.',
            'editar': 'Editar sus datos y sus vínculos con los estudiantes, y asignar o restablecer su contraseña. Consultar la contraseña es exclusivo de los administradores.',
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
    Modulo('inscripciones', 'Inscripciones', 'clipboard-list', 'En qué grado está cada estudiante en cada ciclo escolar.', (
        Funcion('Inscripciones', _permisos('inscripcion'), ayuda={
            'ver': 'Consultar las inscripciones y exportarlas a CSV.',
            'crear': 'Inscribir estudiantes, también de forma masiva (reinscripción).',
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
        Funcion('Días sin clases', {'crear': 'Alumnos.add_dianolectivo', 'baja': 'Alumnos.delete_dianolectivo'}, etiquetas={'baja': 'Quitar'},
                requiere=('Alumnos.view_cicloescolar',), ayuda={
            'crear': 'Registrar días sin clases (puentes, consejos técnicos, vacaciones) de los niveles elegidos, en Ciclos escolares.',
            'baja': 'Quitar un día sin clases.',
        }),
    )),
    Modulo('grados', 'Grados', 'layers', 'Los grados del colegio (hay un solo grupo por grado).', (
        Funcion('Grados', _permisos('grado'), ayuda={
            'ver': 'Consultar los grados, sus estudiantes y materias, y exportar la lista.',
            'crear': 'Crear grados.',
            'editar': 'Editar un grado.',
            'baja': 'Dar de baja un grado.',
        }),
    )),
    Modulo('grupos', 'Grupos', 'users', 'Los grupos de cada grado (1° A, 1° B…) y el catálogo de nombres de grupo.', (
        Funcion('Grupos', {'ver': 'Alumnos.view_grupo'}, ayuda={
            'ver': 'Consultar los grupos con sus estudiantes, sus materias y sus profesores. Los grupos de un grado se eligen al editar el grado.',
        }),
        Funcion('Nombres de grupo', _permisos('nombregrupo'), ayuda={
            'ver': 'Consultar el catálogo de nombres de grupo.',
            'crear': 'Agregar nombres de grupo (A, B, Matutino…).',
            'editar': 'Renombrar un grupo del catálogo o reactivarlo.',
            'baja': 'Dar de baja un nombre de grupo del catálogo.',
        }),
    )),
    Modulo('materias', 'Materias', 'book-open', 'El catálogo de materias, su plan por grado y qué profesor imparte cada una.', (
        Funcion('Catálogo de materias', _permisos('materia'), ayuda={
            'ver': 'Consultar las materias, y exportarlas a CSV.',
            'crear': 'Registrar materias nuevas.',
            'editar': 'Editar una materia y reactivarla.',
            'baja': 'Dar de baja una materia.',
        }),
        Funcion('Plan de materias y asignaciones', _permisos('materiagrado'), requiere=('Alumnos.view_materia',), ayuda={
            'ver': 'Consultar el tablero de asignaciones (qué profesor imparte cada materia), la carga de cada profesor y los movimientos, y exportarlos a CSV.',
            'crear': 'Asignar materias a un grado en un ciclo, o copiar el plan de otro ciclo.',
            'editar': 'Elegir el profesor que imparte cada materia, asignar varias a la vez y pasar las clases de un profesor a otro.',
            'baja': 'Quitar una materia de un grado.',
        }),
    )),
    Modulo('horarios', 'Horarios', 'clock', 'El horario semanal de cada grado.', (
        Funcion('Horarios', _permisos('horariomateria'), ayuda={
            'ver': 'Consultar los horarios por grupo, profesor y materia, con los recesos de cada grupo.',
            'crear': 'Agregar bloques y recesos al horario.',
            'editar': 'Cambiar el día o la hora de un bloque o de un receso.',
            'baja': 'Quitar bloques y recesos del horario.',
        }),
    )),
    Modulo('periodos', 'Periodos de evaluación', 'clipboard-check', 'Los parciales, bimestres o trimestres de cada nivel y cuándo se puede capturar en cada uno.', (
        Funcion('Periodos de evaluación', _permisos('periodo'), ayuda={
            'ver': 'Consultar los periodos de cada nivel y si están abiertos.',
            'crear': 'Agregar periodos a un nivel.',
            'editar': 'Editar un periodo, abrirlo o cerrarlo a mano y devolverlo a sus fechas.',
            'baja': 'Eliminar un periodo.',
        }),
    )),
    Modulo('asistencias', 'Asistencias', 'user-check', 'La entrada al colegio, el pase de lista y las justificaciones.', (
        Funcion('Pantalla de entrada', {'crear': 'Alumnos.add_asistenciageneral'}, etiquetas={'crear': 'Usar'}, ayuda={
            'crear': 'Usar la pantalla de la entrada: registrar la asistencia con la credencial o la referencia del estudiante.',
        }),
        Funcion('Asistencia del día y reportes', {'ver': 'Alumnos.view_asistenciageneral', 'editar': 'Alumnos.change_asistenciageneral'}, ayuda={
            'ver': 'Consultar la asistencia del día, los reportes y el historial de cada estudiante, y exportarlos.',
            'editar': 'Corregir la asistencia general de un estudiante.',
        }),
        Funcion('Cierre del día', {'crear': 'Alumnos.add_cierredia'}, etiquetas={'crear': 'Cerrar'}, requiere=('Alumnos.view_asistenciageneral',), ayuda={
            'crear': 'Cerrar el día: quien no entró queda con falta.',
        }),
        Funcion('Pase de lista por materia', {'ver': 'Alumnos.view_asistenciamateria', 'editar': 'Alumnos.change_asistenciamateria'}, etiquetas={'editar': 'Pasar lista'}, ayuda={
            'ver': 'Consultar la asistencia de las materias en el periodo abierto (un docente, solo la de sus materias; todas, con «Asistencia del día y reportes»).',
            'editar': 'Pasar lista: poner presente, falta o retardo en la matriz de asistencia.',
        }),
        Funcion('Justificaciones', _permisos('justificacion'), etiquetas={'baja': 'Anular'},
                reservado={'crear': ADMINISTRADOR, 'editar': ADMINISTRADOR, 'baja': ADMINISTRADOR}, ayuda={
            'ver': 'Consultar las justificaciones de faltas.',
            'crear': 'Justificar la falta general o solo algunas materias, o una falta de la asistencia por materia con la foto de su comprobante. Exclusivo del administrador.',
            'editar': 'Editar una justificación y reactivarla. Exclusivo del administrador.',
            'baja': 'Anular una justificación. Exclusivo del administrador.',
        }),
        Funcion('Ajustes de asistencia', {'ver': 'Alumnos.view_configuracionasistencia', 'editar': 'Alumnos.change_configuracionasistencia'}, ayuda={
            'ver': 'Consultar la hora de entrada, la tolerancia, la hora límite por nivel y los cierres del día (Ajustes › Asistencia).',
            'editar': 'Cambiar la hora de entrada y la tolerancia.',
        }),
    )),
    Modulo('calificaciones', 'Calificaciones', 'award', 'Rubros y porcentajes de cada materia, captura de procedimientos y exámenes, cierre y concentrado.', (
        Funcion('Calificaciones de sus materias', {'crear': 'Calificaciones.capturar'}, etiquetas={'crear': 'Capturar'}, ayuda={
            'crear': 'Un docente consulta y captura las calificaciones de sus materias asignadas (actividades, conducta, punto de academia) mientras el periodo está abierto.',
        }),
        Funcion('Calificaciones de todas las materias', {'ver': 'Calificaciones.ver_todas', 'editar': 'Calificaciones.gestionar_todas'},
                etiquetas={'editar': 'Capturar y gestionar'}, ayuda={
            'ver': 'Consultar las calificaciones y concentrados de todas las materias y grupos, e imprimirlos o exportarlos.',
            'editar': 'Capturar calificaciones y agregar, editar o anular actividades en cualquier materia del colegio.',
        }),
        Funcion('Cierre de calificaciones', {'crear': 'Calificaciones.cerrar'}, etiquetas={'crear': 'Cerrar'}, ayuda={
            'crear': 'Cerrar las calificaciones de un periodo en las materias que captura (exige resolver lo pendiente y guarda la configuración y los resultados).',
        }),
        Funcion('Reapertura de calificaciones', {'editar': 'Calificaciones.reabrir'}, etiquetas={'editar': 'Reabrir'},
                requiere=('Calificaciones.ver_todas',), ayuda={
            'editar': 'Reabrir calificaciones cerradas indicando el motivo (lo cerrado queda en el historial).',
        }),
        Funcion('Configuración de calificaciones', _permisos('configuracionevaluacion', ('ver', 'crear', 'editar'), app='Calificaciones'), ayuda={
            'ver': 'Consultar los rubros, porcentajes y reglas de cada materia (Ajustes › Calificaciones).',
            'crear': 'Crear la configuración de referencia, versiones por periodo y copiar la de otra materia.',
            'editar': 'Editar rubros, porcentajes y reglas, y activar la configuración.',
        }),
    )),
    Modulo('mensajes', 'Mensajes', 'message-circle', 'Conversaciones en tiempo real entre el personal, los docentes, los estudiantes y los tutores.', (
        Funcion('Mensajería', {'crear': 'Mensajes.usar'}, etiquetas={'crear': 'Usar'}, ayuda={
            'crear': 'Conversar con otros usuarios del sistema. Un docente, además, con los estudiantes de los grupos donde imparte '
                     'clase y con sus tutores.',
        }),
        Funcion('Atención a estudiantes y familias', {'crear': 'Mensajes.contactar_familias'}, etiquetas={'crear': 'Atender'}, ayuda={
            'crear': 'Escribir a cualquier estudiante o tutor y aparecer entre los contactos de todos ellos (una cuenta de '
                     'prefectura, solo los de su alcance).',
        }),
    )),
    Modulo('comunicados', 'Comunicados', 'megaphone', 'Avisos informativos para tutores, estudiantes y profesores, con seguimiento de lectura.', (
        Funcion('Comunicados recibidos', {'ver': 'Comunicados.recibir'}, etiquetas={'ver': 'Consultar'}, ayuda={
            'ver': 'Un profesor consulta los comunicados que le envían. Los tutores y los estudiantes los ven en su portal, '
                   'sin necesidad de permisos.',
        }),
        Funcion('Envío de comunicados', {'ver': 'Comunicados.seguimiento', 'crear': 'Comunicados.enviar', 'baja': 'Comunicados.eliminar'},
                etiquetas={'ver': 'Seguimiento', 'crear': 'Enviar', 'baja': 'Eliminar'}, ayuda={
            'ver': 'Consultar los comunicados que envió, su estado y quién los ha leído (nunca los de otros emisores).',
            'crear': 'Enviar comunicados a tutores, estudiantes y profesores de los niveles que tiene asignados: los que da como '
                     'docente, dirige o coordina, su alcance de prefectura y los «Niveles para comunicados» de su ficha.',
            'baja': 'Eliminar sus propios comunicados: dejan de verse y se conservan en el historial para auditoría.',
        }),
        Funcion('Gestión de todos los comunicados', {'editar': 'Comunicados.gestionar'}, etiquetas={'editar': 'Gestionar'},
                requiere=('Comunicados.seguimiento',), reservado={'editar': ADMINISTRADOR}, ayuda={
            'editar': 'Enviar a todo el colegio y consultar, dar seguimiento y eliminar los comunicados de cualquier emisor. '
                      'Exclusivo del administrador.',
        }),
    )),
    Modulo('retiros', 'Retiros anticipados', 'log-out', 'Los avisos de los tutores que recogerán a sus hijos antes de la salida y la confirmación de cada salida.', (
        Funcion('Retiros anticipados', {'ver': 'Retiros.consultar', 'crear': 'Retiros.confirmar', 'editar': 'Retiros.corregir'},
                etiquetas={'ver': 'Consultar', 'crear': 'Confirmar salidas', 'editar': 'Cancelar y corregir'}, ayuda={
            'ver': 'Consultar los avisos de retiro de los estudiantes de sus niveles (los «Niveles para retiros» de su ficha y, en '
                   'una cuenta de prefectura, su alcance), con quién los recogerá, y anotar observaciones internas.',
            'crear': 'Confirmar la salida de cada estudiante después de verificar que quien lo recoge está autorizado.',
            'editar': 'Cancelar avisos (con motivo, se avisa al tutor) y corregir o deshacer salidas ya confirmadas (queda en la bitácora).',
        }),
        Funcion('Retiros de todo el colegio', {'editar': 'Retiros.gestionar'}, etiquetas={'editar': 'Gestionar'},
                requiere=('Retiros.consultar',), reservado={'editar': ADMINISTRADOR}, ayuda={
            'editar': 'Consultar y atender los retiros de todos los niveles. Exclusivo del administrador.',
        }),
        Funcion('Motivos de retiro', {'editar': 'Retiros.configurar'}, etiquetas={'editar': 'Configurar'},
                reservado={'editar': ADMINISTRADOR}, ayuda={
            'editar': 'Crear, editar, ordenar, activar y desactivar los motivos que eligen los tutores (Ajustes › Retiros). '
                      'Exclusivo del administrador.',
        }),
    )),
    Modulo('agenda', 'Agenda', 'calendar', 'El calendario de eventos del colegio por nivel educativo. Todos consultan los de sus niveles y los de todo el colegio.', (
        Funcion('Eventos de la agenda', {'editar': 'Agenda.gestionar'}, etiquetas={'editar': 'Gestionar'},
                reservado={'editar': ADMINISTRADOR}, ayuda={
            'editar': 'Crear, editar y eliminar los eventos de cualquier nivel o de todo el colegio. Exclusivo del administrador.',
        }),
    )),
    Modulo('panel', 'Panel de control', 'layout-dashboard', 'Los indicadores del colegio y las alertas de los estudiantes que requieren atención.', (
        Funcion('Criterios de seguimiento', {'ver': 'Panel.view_criterioseguimiento', 'editar': 'Panel.change_criterioseguimiento'}, ayuda={
            'ver': 'Consultar los criterios con que el panel señala a los estudiantes que requieren atención (Ajustes › Seguimiento).',
            'editar': 'Cambiar esos criterios por nivel: faltas, inasistencia, calificación aprobatoria, promedio mínimo, descenso y prioridad.',
        }),
    )),
    Modulo('bitacoras', 'Bitácoras por grupo', 'notebook-pen', 'Observaciones informativas de lo ocurrido en cada clase, por grupo y por estudiante (no afectan calificaciones ni conducta).', (
        Funcion('Bitácora de sus clases', {'crear': 'Bitacoras.registrar'}, etiquetas={'crear': 'Registrar'}, ayuda={
            'crear': 'Un docente registra y consulta las entradas de los grupos y materias que tiene asignados, y edita o anula las suyas.',
        }),
        Funcion('Bitácoras de todos los grupos', {'ver': 'Bitacoras.consultar_todas', 'crear': 'Bitacoras.registrar_todas', 'editar': 'Bitacoras.gestionar'},
                etiquetas={'editar': 'Gestionar'}, ayuda={
            'ver': 'Consultar la bitácora de cualquier grupo y el historial de cualquier estudiante de su alcance: una cuenta de prefectura, '
                   'el suyo; otra cuenta, los «Niveles que coordina» de su ficha (sin niveles, todo el colegio).',
            'crear': 'Registrar entradas en cualquier grupo y materia de su alcance (y editar o anular las propias).',
            'editar': 'Editar o anular entradas de otros usuarios de su alcance y consultar las anuladas (auditoría).',
        }),
    )),
    Modulo('conducta', 'Conducta', 'flag', 'El registro de conducta de los estudiantes, sus reportes y los catálogos de cada nivel.', (
        Funcion('Registro de conducta', _permisos('registroconducta', app='Conducta'), etiquetas={'baja': 'Anular'}, ayuda={
            'ver': 'Consultar la conducta de todo el colegio, sus evidencias, los pendientes y los reportes (imprimir, PDF y Excel).',
            'crear': 'Registrar incidencias y conductas positivas, con medidas, suspensión y evidencias.',
            'editar': 'Editar registros (queda constancia de cada cambio), su seguimiento, evidencias y contactos con la familia, y revisar avisos de reincidencia.',
            'baja': 'Anular un registro indicando el motivo (se conserva para consulta).',
        }),
        Funcion('Categorías de conducta', _permisos('categoriaconducta', app='Conducta'), etiquetas={'baja': 'Eliminar'}, ayuda={
            'ver': 'Consultar las categorías de cada nivel (en Ajustes › Conducta).',
            'crear': 'Agregar categorías.',
            'editar': 'Editarlas, activarlas o desactivarlas.',
            'baja': 'Eliminar una categoría que nunca se usó.',
        }),
        Funcion('Motivos de conducta', _permisos('motivoconducta', app='Conducta'), etiquetas={'baja': 'Eliminar'}, ayuda={
            'ver': 'Consultar los motivos de cada categoría.',
            'crear': 'Agregar motivos.',
            'editar': 'Editarlos, activarlos o desactivarlos.',
            'baja': 'Eliminar un motivo que nunca se usó.',
        }),
        Funcion('Medidas disciplinarias', _permisos('medidadisciplinaria', app='Conducta'), etiquetas={'baja': 'Eliminar'}, ayuda={
            'ver': 'Consultar las medidas de cada nivel.',
            'crear': 'Agregar medidas.',
            'editar': 'Editarlas, activarlas o desactivarlas.',
            'baja': 'Eliminar una medida que nunca se aplicó.',
        }),
        Funcion('Motivos de suspensión', _permisos('motivosuspension', app='Conducta'), etiquetas={'baja': 'Eliminar'}, ayuda={
            'ver': 'Consultar los motivos de suspensión de cada nivel.',
            'crear': 'Agregar motivos de suspensión.',
            'editar': 'Editarlos, activarlos o desactivarlos.',
            'baja': 'Eliminar un motivo que nunca se usó.',
        }),
        Funcion('Avisos de reincidencia', {'ver': 'Conducta.view_reglareincidencia', 'editar': 'Conducta.change_reglareincidencia'}, ayuda={
            'ver': 'Consultar cuándo se avisa de una reincidencia en cada nivel.',
            'editar': 'Cambiar el número de incidencias y los días del aviso de cada nivel.',
        }),
        Funcion('Aprobación de suspensiones y medidas', {'editar': 'Conducta.aprobar_suspension'}, etiquetas={'editar': 'Aprobar o rechazar'}, ayuda={
            'editar': 'Aprobar o rechazar las solicitudes de suspensión y las medidas que requieren aprobación (nunca las que pidió uno mismo). '
                      'Quien tiene este permiso registra las suspensiones ya aprobadas.',
        }),
    )),
    Modulo('prefectura', 'Prefectura', 'clipboard-check', 'Estudiantes, asistencia, conducta y seguimiento de los niveles o grupos asignados a cada cuenta de prefectura.', (
        Funcion('Prefectura', {'ver': 'Prefectura.consultar', 'crear': 'Prefectura.registrar', 'editar': 'Prefectura.corregir'},
                etiquetas={'ver': 'Consultar', 'crear': 'Registrar', 'editar': 'Corregir lo propio'}, ayuda={
            'ver': 'Su panel, la ficha de los estudiantes (sin datos financieros, documentos ni expediente clínico), la asistencia, '
                   'la conducta, el seguimiento y los reportes en pantalla. Una cuenta de prefectura solo ve su alcance.',
            'crear': 'Registrar incidencias, conductas positivas y entradas o salidas fuera de horario.',
            'editar': 'Corregir o anular, con motivo, sus propios registros mientras estén abiertos.',
        }),
        Funcion('Corrección ampliada', {'editar': 'Prefectura.corregir_otros'}, etiquetas={'editar': 'Corregir de otros'},
                requiere=('Prefectura.consultar',), ayuda={
            'editar': 'Corregir o anular registros de otros usuarios y casos cerrados.',
        }),
        Funcion('Justificaciones de prefectura', {'crear': 'Prefectura.justificar'}, etiquetas={'crear': 'Justificar'},
                requiere=('Prefectura.consultar',), reservado={'crear': PREFECTURA}, ayuda={
            'crear': 'Justificar faltas y retardos con su comprobante fotográfico, y revocar justificaciones indicando el motivo. Solo roles de prefectura.',
        }),
        Funcion('Solicitudes de suspensión', {'crear': 'Prefectura.solicitar_suspension'}, etiquetas={'crear': 'Solicitar'},
                requiere=('Prefectura.consultar',), ayuda={
            'crear': 'Solicitar suspensiones y medidas que requieren aprobación (las aprueba Dirección o el administrador).',
        }),
        Funcion('Seguimiento de casos', {'editar': 'Prefectura.dar_seguimiento'}, etiquetas={'editar': 'Dar seguimiento'},
                requiere=('Prefectura.consultar',), ayuda={
            'editar': 'Citas con la familia, contactos, acuerdos y compromisos, responsable, fecha límite y cierre de los casos.',
        }),
        Funcion('Reportes de prefectura', {'crear': 'Prefectura.exportar'}, etiquetas={'crear': 'Exportar'},
                requiere=('Prefectura.consultar',), ayuda={
            'crear': 'Imprimir los reportes y exportarlos a PDF y Excel.',
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
# permiso reservado -> quién puede tenerlo
RESERVADOS = {
    permiso: funcion.reservado[accion]
    for modulo in MODULOS for funcion in modulo.funciones for accion, permiso in funcion.permisos.items() if accion in funcion.reservado
}


def reservados_para(es_prefectura=False):
    """Los permisos que un rol que no es de acceso total no puede tener (los de prefectura, si no es de prefectura)."""
    return {permiso for permiso, quien in RESERVADOS.items() if quien == ADMINISTRADOR or (quien == PREFECTURA and not es_prefectura)}


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
                    'reservado': RESERVADOS.get(permiso, ''),
                })
            filas.append({'funcion': funcion, 'celdas': celdas, 'concedidas': [c for c in celdas if c and c['tiene']]})
        salida.append({'modulo': modulo, 'filas': filas, 'concedidos': concedidos, 'posibles': posibles})
    return salida
