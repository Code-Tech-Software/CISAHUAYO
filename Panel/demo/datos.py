"""Los datos ficticios de la demostración: nombres, materias por grado, catálogos y textos. Ningún dato es real."""

NOMBRES_F = (
    'Sofía', 'Valentina', 'Regina', 'María José', 'Camila', 'Ximena', 'Renata', 'Natalia', 'Fernanda', 'Victoria', 'Isabella',
    'Daniela', 'Andrea', 'Mariana', 'Paula', 'Romina', 'Ana Paula', 'Lucía', 'Emilia', 'Valeria', 'Jimena', 'Sara', 'Elena',
    'Julieta', 'Abril', 'Aitana', 'Montserrat', 'Alejandra', 'Carolina', 'Frida',
)
NOMBRES_M = (
    'Santiago', 'Mateo', 'Sebastián', 'Leonardo', 'Emiliano', 'Diego', 'Daniel', 'Miguel Ángel', 'Alejandro', 'Iker',
    'Gael', 'Matías', 'Nicolás', 'Andrés', 'José Pablo', 'Rodrigo', 'Emilio', 'Fernando', 'Ángel', 'Bruno', 'Tomás',
    'Joaquín', 'Maximiliano', 'Rafael', 'Adrián', 'Eduardo', 'Patricio', 'Julián', 'Iván', 'Héctor',
)
APELLIDOS = (
    'García', 'Hernández', 'Martínez', 'López', 'González', 'Pérez', 'Rodríguez', 'Sánchez', 'Ramírez', 'Cruz', 'Flores',
    'Gómez', 'Morales', 'Vázquez', 'Jiménez', 'Reyes', 'Díaz', 'Torres', 'Gutiérrez', 'Ruiz', 'Mendoza', 'Aguilar',
    'Ortiz', 'Moreno', 'Castillo', 'Romero', 'Álvarez', 'Méndez', 'Chávez', 'Rivera', 'Juárez', 'Ramos', 'Domínguez',
    'Herrera', 'Medina', 'Castro', 'Vargas', 'Guzmán', 'Velázquez', 'Ochoa', 'Valencia', 'Zepeda', 'Barragán', 'Magaña',
    'Villaseñor', 'Arceo', 'Ceja', 'Gálvez',
)
COLONIAS = ('Centro', 'El Pedregal', 'Las Fuentes', 'Jardines del Carmen', 'La Yerbabuena', 'Infonavit', 'El Rosario', 'Lomas de Sahuayo')
CALLES = ('Av. Juárez', 'Calle Hidalgo', 'Calle Morelos', 'Av. Constitución', 'Calle Madero', 'Calle Allende', 'Calle Zaragoza', 'Av. Revolución')
OCUPACIONES = ('Comerciante', 'Docente', 'Contador', 'Enfermera', 'Ingeniero', 'Médica', 'Abogado', 'Agricultor', 'Empleada', 'Arquitecta')
GRUPOS_SANGUINEOS = ('O+', 'O+', 'O+', 'A+', 'A+', 'B+', 'AB+', 'O-')
ALERGIAS = ('', '', '', '', '', '', 'Penicilina', 'Polen', 'Cacahuate', 'Lactosa')

# Grupos de cada nivel en el ciclo actual: (número de grado, [letras]); y estudiantes por grupo
GRUPOS = {
    'PREESCOLAR': ((2, 'A'), (3, 'A')),
    'PRIMARIA': ((1, 'A'), (2, 'A'), (3, 'A'), (4, 'A'), (4, 'B'), (5, 'A'), (6, 'A')),
    'SECUNDARIA': ((1, 'A'), (1, 'B'), (2, 'A'), (3, 'A')),
    'PREPARATORIA': ((1, 'A'), (3, 'A'), (5, 'A')),
}
POR_GRUPO = {'PREESCOLAR': 9, 'PRIMARIA': 10, 'SECUNDARIA': 9, 'PREPARATORIA': 9}
EDAD_DE_INGRESO = {'PREESCOLAR': 3, 'PRIMARIA': 6, 'SECUNDARIA': 12, 'PREPARATORIA': 15}

# Materias de cada grado: (área, nombre). El área decide quién la imparte (ver PROFESORES) y su lugar en el horario.
_PRIMARIA = (('titular', 'Español'), ('titular', 'Matemáticas'), ('titular', 'Ciencias Naturales'), ('titular', 'Historia'),
             ('ingles', 'Inglés'), ('fisica', 'Educación Física'))
MATERIAS = {
    'PREESCOLAR': {n: (('titular', 'Lenguaje y Comunicación'), ('titular', 'Pensamiento Matemático'),
                       ('titular', 'Exploración del Mundo'), ('fisica', 'Educación Física')) for n in (1, 2, 3)},
    'PRIMARIA': {n: _PRIMARIA for n in range(1, 7)},
    'SECUNDARIA': {
        1: (('espanol', 'Español I'), ('matematicas', 'Matemáticas I'), ('ciencias', 'Biología'), ('historia', 'Historia I'), ('ingles', 'Inglés I'), ('fisica', 'Educación Física I')),
        2: (('espanol', 'Español II'), ('matematicas', 'Matemáticas II'), ('ciencias', 'Física'), ('historia', 'Historia II'), ('ingles', 'Inglés II'), ('fisica', 'Educación Física II')),
        3: (('espanol', 'Español III'), ('matematicas', 'Matemáticas III'), ('ciencias', 'Química'), ('historia', 'Historia III'), ('ingles', 'Inglés III'), ('fisica', 'Educación Física III')),
    },
    'PREPARATORIA': {
        1: (('matematicas', 'Matemáticas I'), ('ciencias', 'Química I'), ('lengua', 'Lectura y Redacción'), ('ingles', 'Inglés I'), ('tecnologia', 'Informática I')),
        3: (('matematicas', 'Matemáticas III'), ('ciencias', 'Física I'), ('lengua', 'Literatura I'), ('ingles', 'Inglés III'), ('tecnologia', 'Historia de México')),
        5: (('matematicas', 'Cálculo Diferencial'), ('ciencias', 'Física III'), ('lengua', 'Filosofía'), ('ingles', 'Inglés V'), ('tecnologia', 'Biología')),
    },
}
CLAVE_DE_NIVEL = {'PREESCOLAR': 'K', 'PRIMARIA': 'P', 'SECUNDARIA': 'S', 'PREPARATORIA': 'B'}

# Docentes: (nivel, área, [índices de grupo] o None = todos los del nivel). Las titulares de preescolar y primaria dan
# las materias «titular» de un solo grupo; los demás, su área en los grupos indicados.
PROFESORES = (
    ('Laura', 'Navarro', 'Ríos', 'PREESCOLAR', 'titular', (0,)),
    ('Patricia', 'Silva', 'Ochoa', 'PREESCOLAR', 'titular', (1,)),
    ('Jorge', 'Mora', 'Ceja', 'PREESCOLAR', 'fisica', None),
    ('Marta', 'Rangel', 'Soto', 'PRIMARIA', 'titular', (0,)),
    ('Rosa', 'Robles', 'Arias', 'PRIMARIA', 'titular', (1,)),
    ('Gabriela', 'Fuentes', 'Lara', 'PRIMARIA', 'titular', (2,)),
    ('Claudia', 'Peña', 'Vega', 'PRIMARIA', 'titular', (3,)),
    ('Verónica', 'Salas', 'Mejía', 'PRIMARIA', 'titular', (4,)),
    ('Adriana', 'Campos', 'Rubio', 'PRIMARIA', 'titular', (5,)),
    ('Ricardo', 'Luna', 'Prado', 'PRIMARIA', 'titular', (6,)),
    ('Karen', 'Wilson', 'Duarte', 'PRIMARIA', 'ingles', (0, 1, 2, 3)),
    ('Daniel', 'Cooper', 'Ruiz', 'PRIMARIA', 'ingles', (4, 5, 6)),
    ('Óscar', 'Bravo', 'Nieto', 'PRIMARIA', 'fisica', (0, 1, 2, 3)),
    ('Hugo', 'Treviño', 'Paz', 'PRIMARIA', 'fisica', (4, 5, 6)),
    ('Pedro', 'Prado', 'Villa', 'SECUNDARIA', 'espanol', None),
    ('Silvia', 'Córdova', 'Ibarra', 'SECUNDARIA', 'matematicas', None),
    ('Arturo', 'Delgado', 'Mora', 'SECUNDARIA', 'ciencias', None),
    ('Beatriz', 'Ponce', 'León', 'SECUNDARIA', 'historia', None),
    ('Diana', 'Díaz', 'Herrera', 'SECUNDARIA', 'ingles', None),
    ('Manuel', 'Orozco', 'Tapia', 'SECUNDARIA', 'fisica', None),
    ('Lorena', 'Brown', 'Castañeda', 'SECUNDARIA', 'ingles_bloque', ()),
    ('Kevin', 'Smith', 'Galindo', 'SECUNDARIA', 'ingles_bloque', ()),
    ('Alberto', 'Quiroz', 'Medina', 'PREPARATORIA', 'matematicas', None),
    ('Elena', 'Zamora', 'Ávila', 'PREPARATORIA', 'ciencias', None),
    ('Raúl', 'Estrada', 'Pineda', 'PREPARATORIA', 'lengua', None),
    ('Mónica', 'Taylor', 'Reyes', 'PREPARATORIA', 'ingles', None),
    ('Javier', 'Macías', 'Ayala', 'PREPARATORIA', 'tecnologia', None),
)

# Cómo se describe a cada docente en demo_cuentas.txt
AREAS = {'titular': 'titular de grupo', 'fisica': 'Educación Física', 'ingles': 'Inglés', 'ingles_bloque': 'Inglés por niveles (bloque simultáneo)',
         'espanol': 'Español', 'matematicas': 'Matemáticas', 'ciencias': 'Ciencias', 'historia': 'Historia', 'lengua': 'Lengua y Literatura',
         'tecnologia': 'Informática, Historia y Biología'}
NOMBRE_DE_NIVEL = {'PREESCOLAR': 'preescolar', 'PRIMARIA': 'primaria', 'SECUNDARIA': 'secundaria', 'PREPARATORIA': 'bachillerato'}

# Horario: 6 horas de clase y, para el bloque simultáneo, una séptima después de la última
HORAS = ((8, 0, 8, 50), (8, 50, 9, 40), (9, 40, 10, 30), (11, 0, 11, 50), (11, 50, 12, 40), (12, 40, 13, 30))
HORA_DEL_BLOQUE = (13, 30, 14, 20)
DIAS_DE_EDUCACION_FISICA = (1, 3)   # martes y jueves

CCT = {'PREESCOLAR': '16PJN0123K', 'PRIMARIA': '16PPR0456M', 'SECUNDARIA': '16PES0789B', 'PREPARATORIA': '16PBH0321X'}
DIRECTORES = {
    'PREESCOLAR': ('Mtra. Lucía Bautista Orozco', 'Directora de Preescolar'),
    'PRIMARIA': ('Mtra. Teresa Villalobos Ruiz', 'Directora de Primaria'),
    'SECUNDARIA': ('Mtro. Ernesto Gallardo Vega', 'Director de Secundaria'),
    'PREPARATORIA': ('Mtro. Fernando Arreola Cruz', 'Director de Bachillerato'),
}

# Conducta: categorías (tipo, nombre, [(motivo, gravedad)]) y medidas (nombre, requiere seguimiento)
CATEGORIAS_CONDUCTA = (
    ('INCIDENCIA', 'Disciplina', (('Interrumpe la clase', 'LEVE'), ('Uso del celular en clase', 'MODERADA'), ('Sale del salón sin permiso', 'MODERADA'))),
    ('INCIDENCIA', 'Responsabilidad', (('No trae el material', 'LEVE'), ('No entrega tareas', 'LEVE'), ('Llega tarde a clase', 'LEVE'))),
    ('INCIDENCIA', 'Convivencia', (('Falta de respeto a un compañero', 'MODERADA'), ('Lenguaje inapropiado', 'MODERADA'), ('Agresión física', 'GRAVE'))),
    ('POSITIVA', 'Reconocimiento', (('Ayuda a sus compañeros', ''), ('Participación destacada', ''), ('Representó al colegio', ''))),
)
MEDIDAS = (('Llamada de atención', False), ('Aviso a los padres', False), ('Reflexión por escrito', False), ('Citatorio a padres', True))

DESCRIPCIONES_CONDUCTA = {
    'Interrumpe la clase': 'Platica y distrae a sus compañeros durante la explicación pese a las indicaciones del docente.',
    'Uso del celular en clase': 'Se le encontró usando el celular durante la clase; se le recogió y se entregó al final del día.',
    'Sale del salón sin permiso': 'Salió del salón sin autorización y se le encontró en el patio.',
    'No trae el material': 'No trajo el material solicitado para la actividad del día.',
    'No entrega tareas': 'Acumula tres tareas sin entregar en la semana.',
    'Llega tarde a clase': 'Llegó tarde después del recreo sin justificación.',
    'Falta de respeto a un compañero': 'Se burló de un compañero frente al grupo.',
    'Lenguaje inapropiado': 'Usó lenguaje ofensivo durante el recreo.',
    'Agresión física': 'Empujó a un compañero durante el recreo; no hubo lesiones.',
    'Ayuda a sus compañeros': 'Apoyó a dos compañeros a ponerse al corriente con los ejercicios.',
    'Participación destacada': 'Participó activamente y presentó su exposición con excelente preparación.',
    'Representó al colegio': 'Representó al colegio en el concurso regional con un desempeño sobresaliente.',
}
LUGARES = ('Salón de clases', 'Patio', 'Laboratorio', 'Cancha', 'Biblioteca')

COMENTARIOS = {
    'alto': (
        'Muestra un excelente desempeño: participa activamente, entrega sus trabajos completos y ayuda a sus compañeros.',
        'Comprende los temas con facilidad y explica su razonamiento con claridad. ¡Sigue así!',
        'Es responsable y constante; sus trabajos destacan por su orden y creatividad.',
    ),
    'medio': (
        'Tiene un buen desempeño. Conviene reforzar en casa los temas vistos y cuidar la entrega puntual de tareas.',
        'Participa en clase y cumple con sus actividades; puede mejorar su concentración durante las explicaciones.',
        'Avanza de manera constante. Se recomienda practicar con los ejercicios de repaso que se envían a casa.',
    ),
    'bajo': (
        'Necesita apoyo para ponerse al corriente: le faltan trabajos por entregar y conviene repasar los temas básicos en casa.',
        'Le cuesta mantener la atención; le ayudaría una rutina de estudio diaria y revisar sus tareas con un adulto.',
        'Requiere acompañamiento cercano. Se sugiere una reunión con el docente para acordar un plan de trabajo.',
    ),
}

ACTIVIDADES = {
    'PROCEDIMIENTO': ('Cuaderno de trabajo', 'Tareas de la semana', 'Proyecto en equipo', 'Exposición', 'Mapa conceptual'),
    'EXAMEN': ('Examen parcial', 'Examen final del periodo'),
}

BITACORAS = (
    ('Trabajo en equipo', 'El grupo trabajó en equipos para resolver los ejercicios del libro; la mayoría terminó a tiempo.'),
    ('Repaso para el examen', 'Se repasaron los temas del periodo con una guía; se resolvieron dudas de forma individual.'),
    ('Actividad en el laboratorio', 'Práctica guiada; los estudiantes siguieron las indicaciones de seguridad.'),
    ('Lectura en voz alta', 'Lectura compartida y comentario del texto; buena participación del grupo.'),
    ('Grupo inquieto', 'El grupo estuvo inquieto después del recreo; se ajustó la actividad para retomar la atención.'),
)
