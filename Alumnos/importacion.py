"""Importación de estudiantes desde un archivo CSV.

El archivo trae un estudiante por fila y, opcionalmente, su tutor principal y el grado en el que se inscribe en el ciclo
actual. Cada fila se valida con las mismas reglas que el formulario de registro y se guarda por separado: una fila con
errores no impide registrar las demás, y volver a cargar el archivo corregido es seguro (los estudiantes que ya están
registrados, por su CURP, se omiten).

Lo indispensable es el nombre, el apellido paterno y la CURP: de ella salen la fecha de nacimiento y el sexo si el archivo
no los trae. Todo lo demás es opcional y se puede completar después editando al estudiante.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.utils import timezone

from . import lectura_csv
from .academico import ciclo_actual
from .forms import AlumnoForm
from .lectura_csv import ERRORES_GUARDADOS, FILAS_MAXIMAS, Columna, ErrorDeArchivo, ErrorDeCelda
from .models import Alumno, Grado, Inscripcion, Tutor, TutorAlumno
from .utils import (
    RELIGION_NINGUNA,
    clave_de_texto,
    compactar_espacios,
    datos_de_curp,
    generar_contrasena,
    normalizar_curp,
    normalizar_religion,
    siguiente_referencia,
    validar_telefono,
)
from .vinculos import parentesco_de_texto

COLUMNAS = (
    Columna('nombre', 'Nombre', 'Nombre o nombres del estudiante.', ('Nombres', 'Nombre(s)'), requerida=True),
    Columna('apellido_paterno', 'Apellido paterno', 'Primer apellido.', ('Primer apellido',), requerida=True),
    Columna('apellido_materno', 'Apellido materno', 'Segundo apellido, si lo tiene.', ('Segundo apellido',)),
    Columna('curp', 'CURP', '18 caracteres. Es lo que identifica al estudiante: no se repite.', requerida=True),
    Columna('referencia', 'Referencia', 'Código único para pasar asistencia. Si falta, se asigna el siguiente número.', ('Matrícula',)),
    Columna('sexo', 'Sexo', 'Masculino o Femenino. Si falta se toma de la CURP.'),
    Columna('fecha_nacimiento', 'Fecha de nacimiento', 'AAAA-MM-DD o DD/MM/AAAA. Si falta se toma de la CURP.', ('Nacimiento',)),
    Columna('nacionalidad', 'Nacionalidad', 'Si falta se registra «Mexicana».'),
    Columna('religion', 'Religión', 'Una de la lista del formulario; lo que no se reconozca se registra como «Otra».'),
    Columna('grupo_sanguineo', 'Grupo sanguíneo', 'A+, A-, B+, B-, AB+, AB-, O+ u O-.', ('Tipo de sangre',)),
    Columna('alergias', 'Alergias', 'Alergias, padecimientos o medicamentos.'),
    Columna('observaciones_generales', 'Observaciones', 'Notas generales.', ('Observaciones generales',)),
    Columna('domicilio', 'Domicilio', 'Calle y número.'),
    Columna('colonia', 'Colonia', ''),
    Columna('ciudad', 'Ciudad', ''),
    Columna('estado', 'Estado', ''),
    Columna('cp', 'CP', '5 dígitos.', ('Código postal', 'C.P.')),
    Columna('correo_electronico', 'Correo electrónico', 'Debe ser único entre los estudiantes.', ('Correo', 'Email', 'E-mail')),
    Columna('uid', 'UID de tarjeta', 'Número de la tarjeta, si la usa.', ('UID', 'Tarjeta')),
    Columna('fecha_ingreso', 'Fecha de ingreso', 'AAAA-MM-DD o DD/MM/AAAA. Si falta se usa la de hoy.'),
    Columna('escuela_procedencia', 'Escuela de procedencia', ''),
    Columna('estatus', 'Estatus', 'Activo, Egresado o Suspendido. Si falta queda Activo.'),
    Columna('grado', 'Grado', 'Para inscribirlo en el ciclo actual: «1° Primaria», «3 Secundaria»… o su equivalencia (7, K1).'),
    Columna('contrasena', 'Contraseña', 'La que se le asigna (4 caracteres o más). Si falta se genera una.'),
    Columna('tutor_nombre', 'Nombre del tutor', 'Si lo escribes, también hacen falta su apellido paterno, su teléfono y su parentesco.', ('Nombre del tutor principal',)),
    Columna('tutor_apellido_paterno', 'Apellido paterno del tutor', ''),
    Columna('tutor_apellido_materno', 'Apellido materno del tutor', ''),
    Columna('tutor_telefono', 'Teléfono del tutor', '10 dígitos. Con el mismo teléfono y nombre se reutiliza al tutor de un hermano.'),
    Columna('tutor_parentesco', 'Parentesco del tutor', 'Madre, Padre, Abuela, Abuelo, Hermana, Hermano, Tía, Tío, Tutor legal u Otro.'),
    Columna('tutor_correo', 'Correo del tutor', ''),
)


_TUTOR_CAMPOS = ('tutor_nombre', 'tutor_apellido_paterno', 'tutor_apellido_materno', 'tutor_telefono', 'tutor_parentesco', 'tutor_correo')

_ESTATUS = {clave_de_texto(etiqueta): codigo for codigo, etiqueta in Alumno.ESTATUS_CHOICES}
_SEXOS = {
    'masculino': 'M', 'hombre': 'M', 'nino': 'M', 'varon': 'M', 'h': 'M',
    'femenino': 'F', 'mujer': 'F', 'nina': 'F', 'f': 'F',
}
_GRUPO_SANGUINEO = re.compile(r'^(ab|a|b|o)\s*([+-]|pos(?:itivo)?|neg(?:ativo)?)$')
_ORDINALES = {
    'primero': '1', 'primer': '1', 'segundo': '2', 'tercero': '3', 'tercer': '3',
    'cuarto': '4', 'quinto': '5', 'sexto': '6',
}
_NIVELES_ABREVIADOS = {'prepa': 'preparatoria', 'kinder': 'preescolar', 'prescolar': 'preescolar'}


# ---------------------------------------------------------------------------
# Lectura del archivo
# ---------------------------------------------------------------------------
def leer_filas(contenido):
    """Las filas del CSV de estudiantes: lista de (número de fila, {clave de columna: texto}). Ver lectura_csv.leer_filas."""
    return lectura_csv.leer_filas(contenido, COLUMNAS, 'estudiantes')


def plantilla_csv():
    """El CSV de la plantilla de estudiantes: solo los encabezados."""
    return lectura_csv.plantilla_csv(COLUMNAS)


# ---------------------------------------------------------------------------
# Interpretación de cada celda
# ---------------------------------------------------------------------------
def _fecha(texto, etiqueta):
    if not texto:
        return ''
    texto = texto.split(' ')[0].split('T')[0]
    for formato in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d'):
        try:
            return datetime.strptime(texto, formato).date().isoformat()
        except ValueError:
            continue
    raise ErrorDeCelda(f'{etiqueta}: «{texto}» no es una fecha. Usa AAAA-MM-DD o DD/MM/AAAA.')


def _sexo(texto):
    """'M' o 'F'; '' si no se indicó o no se puede saber (una «M» sola es ambigua: masculino o mujer)."""
    clave = clave_de_texto(texto)
    if not clave or clave == 'm':
        return ''
    if clave not in _SEXOS:
        raise ErrorDeCelda(f'Sexo: «{texto}» no es válido. Usa Masculino o Femenino.')
    return _SEXOS[clave]


def _grupo_sanguineo(texto):
    clave = clave_de_texto(texto)
    if not clave:
        return ''
    coincidencia = _GRUPO_SANGUINEO.match(clave)
    if not coincidencia:
        raise ErrorDeCelda(f'Grupo sanguíneo: «{texto}» no es válido. Usa A+, A-, B+, B-, AB+, AB-, O+ u O-.')
    grupo, signo = coincidencia.groups()
    return grupo.upper() + ('+' if signo[0] in '+p' else '-')


def _estatus(texto):
    clave = clave_de_texto(texto)
    if not clave:
        return 'ACTIVO'
    if clave not in _ESTATUS:
        raise ErrorDeCelda(f'Estatus: «{texto}» no es válido. Usa Activo, Egresado o Suspendido.')
    return _ESTATUS[clave]


def _religion(texto):
    """(religión de la lista, True si hubo que registrarla como «Otra»)."""
    if not texto or clave_de_texto(texto) in RELIGION_NINGUNA:
        return '', False
    reconocida = normalizar_religion(texto)
    return (reconocida, False) if reconocida else ('Otra', True)


def _clave_de_grado(texto):
    clave = clave_de_texto(texto).replace('°', ' ').replace('º', ' ').replace('.', ' ')
    palabras = []
    for palabra in clave.split():
        palabra = _ORDINALES.get(palabra, _NIVELES_ABREVIADOS.get(palabra, palabra))
        palabra = re.sub(r'^(\d+)(?:ro|do|er|to|vo|mo|o|a)$', r'\1', palabra)
        if palabra not in ('de', 'del', 'grado', 'el', 'la'):
            palabras.append(palabra)
    return ' '.join(palabras)


class _Grados:
    """Los grados activos, para reconocer «1° Primaria», «primero de secundaria» o una equivalencia («7», «K1»)."""

    def __init__(self):
        self.indice = {}
        for grado in Grado.objects.filter(activo=True):
            nivel = clave_de_texto(grado.get_nivel_display())
            for clave in (f'{grado.numero} {nivel}', f'{nivel} {grado.numero}', f'{grado.numero}{nivel}'):
                self.indice[clave] = grado
        for grado in Grado.objects.filter(activo=True).exclude(equivalencia=''):
            self.indice.setdefault(clave_de_texto(grado.equivalencia), grado)

    def buscar(self, texto):
        grado = self.indice.get(_clave_de_grado(texto))
        if grado is None:
            raise ErrorDeCelda(f'Grado: «{texto}» no existe o está dado de baja. Escríbelo como «1° Primaria».')
        return grado


# ---------------------------------------------------------------------------
# Una fila = un estudiante
# ---------------------------------------------------------------------------
class AlumnoImportForm(AlumnoForm):
    """El formulario de registro, pero que solo exige lo indispensable: nombre, apellido paterno y CURP.

    El sexo y la fecha de nacimiento, si no vienen, se deducen de la CURP. Lo demás se puede completar después.
    """

    OPCIONALES = ('fecha_nacimiento', 'sexo', 'domicilio', 'colonia', 'ciudad', 'estado', 'cp', 'grupo_sanguineo')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)   # aplica el estilo (aplicar_estilo); este formulario no se dibuja, solo valida
        for nombre in self.OPCIONALES:
            self.fields[nombre].required = False

    def clean(self):
        datos = super().clean()
        deducidos = datos_de_curp(datos.get('curp') or '')
        if deducidos:
            if not datos.get('fecha_nacimiento') and 'fecha_nacimiento' not in self.errors:
                datos['fecha_nacimiento'] = deducidos['fecha_nacimiento']
            if not datos.get('sexo') and 'sexo' not in self.errors:
                datos['sexo'] = deducidos['sexo']
        return datos


@dataclass
class Resultado:
    creados: list = field(default_factory=list)       # {'fila', 'referencia', 'nombre', 'contrasena', 'grado'}
    errores: list = field(default_factory=list)       # {'fila', 'persona', 'motivo'}
    omitidos: int = 0                                  # ya estaban registrados (misma CURP)
    religiones_como_otra: int = 0
    total: int = 0

    @property
    def con_error(self):
        return len(self.errores)


class Importador:
    """Procesa las filas de un archivo. Úsese una vez por archivo: guarda lo que ya se registró para detectar repetidos."""

    def __init__(self, reservadas=()):
        self.ciclo = ciclo_actual()
        self.grados = _Grados()
        self.curps = set(Alumno.objects.values_list('curp', flat=True))
        self.referencias = set(Alumno.objects.values_list('referencia', flat=True))
        self.reservadas = set(reservadas)              # las que el archivo asigna a mano: las generadas no las usan
        self.tutores = {}                              # (teléfono, nombre) -> Tutor ya usado o encontrado
        self._ultima_referencia = siguiente_referencia()

    # --- referencias -----------------------------------------------------------------------------
    def _siguiente_referencia(self):
        while self._ultima_referencia in self.referencias or self._ultima_referencia in self.reservadas:
            self._ultima_referencia = str(int(self._ultima_referencia) + 1).zfill(len(self._ultima_referencia))
        return self._ultima_referencia

    # --- tutor ------------------------------------------------------------------------------------
    def _datos_del_tutor(self, datos):
        """Los datos limpios del tutor de la fila, o None si la fila no trae tutor. Lanza ErrorDeCelda si están incompletos."""
        if not any(datos.get(campo) for campo in _TUTOR_CAMPOS):
            return None
        faltan = [
            etiqueta for campo, etiqueta in (
                ('tutor_nombre', 'su nombre'), ('tutor_apellido_paterno', 'su apellido paterno'),
                ('tutor_telefono', 'su teléfono'), ('tutor_parentesco', 'su parentesco'),
            ) if not datos.get(campo)
        ]
        if faltan:
            raise ErrorDeCelda('Tutor: falta ' + ', '.join(faltan) + '. Déjalo todo vacío si no hay tutor que registrar.')
        try:
            telefono = validar_telefono(datos['tutor_telefono'])
        except ValidationError:
            raise ErrorDeCelda(f'Teléfono del tutor: «{datos["tutor_telefono"]}» no tiene 10 dígitos.')
        correo = (datos.get('tutor_correo') or '').strip().lower()
        if correo:
            try:
                validate_email(correo)
            except ValidationError:
                raise ErrorDeCelda(f'Correo del tutor: «{correo}» no es válido.')
        return {
            'nombre': compactar_espacios(datos['tutor_nombre']),
            'apellido_paterno': compactar_espacios(datos['tutor_apellido_paterno']),
            'apellido_materno': compactar_espacios(datos.get('tutor_apellido_materno')),
            'telefono': telefono,
            'correo_electronico': correo or None,
            'parentesco': parentesco_de_texto(datos['tutor_parentesco']) or 'OTRO',
        }

    def _tutor(self, datos_tutor, alumno):
        """El tutor ya registrado con ese nombre y teléfono (p. ej. el de un hermano) o uno nuevo con el domicilio del estudiante."""
        nombre = clave_de_texto(f'{datos_tutor["nombre"]} {datos_tutor["apellido_paterno"]} {datos_tutor["apellido_materno"]}')
        llave = (datos_tutor['telefono'], nombre)
        if llave not in self.tutores:
            existente = next(
                (
                    tutor for tutor in Tutor.objects.filter(telefono=datos_tutor['telefono'], estatus='ACTIVO')
                    if clave_de_texto(str(tutor)) == nombre
                ),
                None,
            )
            if existente is None:
                existente = Tutor(
                    nombre=datos_tutor['nombre'], apellido_paterno=datos_tutor['apellido_paterno'],
                    apellido_materno=datos_tutor['apellido_materno'], telefono=datos_tutor['telefono'],
                    correo_electronico=datos_tutor['correo_electronico'],
                    domicilio=alumno.domicilio, colonia=alumno.colonia, ciudad=alumno.ciudad,
                    estado=alumno.estado, cp=alumno.cp,
                )
                existente.establecer_contrasena(generar_contrasena())   # su usuario se genera al guardar
                existente.save()
            self.tutores[llave] = existente
        return self.tutores[llave]

    # --- fila -------------------------------------------------------------------------------------
    def procesar(self, datos):
        """Registra al estudiante de una fila.

        Devuelve (estado, detalle, religion_como_otra): ('creado', {datos del registro}, ...), ('omitido', None, ...) si
        ya estaba registrado o ('error', texto con todos los motivos, ...).
        """
        curp = normalizar_curp(datos.get('curp'))
        if curp and curp in self.curps:
            return 'omitido', None, False

        referencia = datos.get('referencia', '').strip()
        if referencia and referencia in self.referencias:
            return 'error', f'Referencia: «{referencia}» ya la tiene otro estudiante.', False

        motivos = []

        def celda(conversor, *argumentos, defecto=''):
            """El valor de una celda ya interpretado; si no es válido, anota el motivo y devuelve `defecto`."""
            try:
                return conversor(*argumentos)
            except ErrorDeCelda as error:
                motivos.append(str(error))
                return defecto

        religion, como_otra = _religion(datos.get('religion', ''))
        formulario = {
            'referencia': referencia or self._siguiente_referencia(),
            'nombre': datos.get('nombre', ''),
            'apellido_paterno': datos.get('apellido_paterno', ''),
            'apellido_materno': datos.get('apellido_materno', ''),
            'curp': curp,
            'fecha_nacimiento': celda(_fecha, datos.get('fecha_nacimiento', ''), 'Fecha de nacimiento'),
            'sexo': celda(_sexo, datos.get('sexo', '')),
            'nacionalidad': datos.get('nacionalidad') or 'Mexicana',
            'religion': religion,
            'grupo_sanguineo': celda(_grupo_sanguineo, datos.get('grupo_sanguineo', '')),
            'alergias': datos.get('alergias', ''),
            'observaciones_generales': datos.get('observaciones_generales', ''),
            'domicilio': datos.get('domicilio', ''),
            'colonia': datos.get('colonia', ''),
            'ciudad': datos.get('ciudad', ''),
            'estado': datos.get('estado', ''),
            'cp': datos.get('cp', ''),
            'correo_electronico': datos.get('correo_electronico', ''),
            'uid': datos.get('uid', ''),
            'fecha_ingreso': celda(_fecha, datos.get('fecha_ingreso', ''), 'Fecha de ingreso') or timezone.localdate().isoformat(),
            'escuela_procedencia': datos.get('escuela_procedencia', ''),
            'contrasena_inicial': datos.get('contrasena', ''),
        }
        tutor = celda(self._datos_del_tutor, datos, defecto=None)
        estatus = celda(_estatus, datos.get('estatus', ''), defecto='ACTIVO')
        grado = celda(self.grados.buscar, datos['grado'], defecto=None) if datos.get('grado') else None
        if grado:
            if self.ciclo is None:
                motivos.append('Grado: no hay un ciclo escolar actual en el que inscribirlo. Márcalo en «Ciclos escolares».')
            elif estatus != 'ACTIVO' and estatus != 'SUSPENDIDO':
                motivos.append('Grado: solo se puede inscribir a un estudiante activo o suspendido.')

        form = AlumnoImportForm(formulario)
        if not form.is_valid():
            for campo, errores in form.errors.items():
                etiqueta = form.fields[campo].label if campo in form.fields else ''
                motivos.extend(f'{etiqueta}: {error}' if etiqueta else str(error) for error in errores)
        if motivos:
            return 'error', ' · '.join(motivos), False

        try:
            with transaction.atomic():
                alumno = form.save()
                if estatus != 'ACTIVO':
                    alumno.estatus = estatus
                    alumno.save(update_fields=['estatus'])
                if tutor:
                    TutorAlumno.objects.create(
                        tutor=self._tutor(tutor, alumno), alumno=alumno, parentesco=tutor['parentesco'],
                        tutor_principal=True, recibe_notificaciones=True,
                    )
                if grado:
                    Inscripcion.objects.create(alumno=alumno, ciclo=self.ciclo, grado=grado)
        except IntegrityError:
            # Si la transacción se deshizo, el tutor creado en ella ya no existe: no se debe reutilizar
            self.tutores.clear()
            return 'error', 'No se pudo guardar: algún dato único (referencia, correo o tarjeta) ya pertenece a otro estudiante.', False

        self.curps.add(alumno.curp)
        self.referencias.add(alumno.referencia)
        return 'creado', {
            'referencia': alumno.referencia,
            'nombre': str(alumno),
            'contrasena': form.contrasena_en_claro,
            'grado': str(grado) if grado else '',
        }, como_otra


def importar(filas):
    """Registra los estudiantes de las filas que devolvió `leer_filas` y resume lo ocurrido."""
    importador = Importador(reservadas={datos['referencia'].strip() for _, datos in filas if datos.get('referencia', '').strip()})
    resultado = Resultado(total=len(filas))
    for fila, datos in filas:
        estado, detalle, como_otra = importador.procesar(datos)
        if estado == 'creado':
            resultado.creados.append({'fila': fila, **detalle})
            resultado.religiones_como_otra += como_otra
        elif estado == 'omitido':
            resultado.omitidos += 1
        else:
            nombre = compactar_espacios(f'{datos.get("nombre", "")} {datos.get("apellido_paterno", "")}')
            resultado.errores.append({'fila': fila, 'persona': nombre, 'motivo': detalle})
    return resultado
