"""Importación de tutores desde un archivo CSV.

El archivo trae un tutor por fila y, opcionalmente, los estudiantes que tiene a cargo (por su referencia o su CURP) con el
parentesco. Cada fila se valida con las mismas reglas del formulario de registro y se guarda por separado: una fila con
errores no impide registrar las demás.

Volver a cargar un archivo es seguro. Un tutor que ya está registrado (por su CURP o por su nombre y teléfono) no se
duplica: si la fila trae estudiantes que todavía no tiene vinculados, solo se agregan esos vínculos. Por eso sirve tanto
una fila por tutor (con varios estudiantes) como una fila por cada estudiante del mismo tutor.

Lo indispensable es el nombre, el apellido paterno y el teléfono. Todo lo demás es opcional.
"""
import re
from dataclasses import dataclass, field

from django.db import IntegrityError, transaction

from Alumnos import lectura_csv
from Alumnos.lectura_csv import ERRORES_GUARDADOS, FILAS_MAXIMAS, Columna, ErrorDeArchivo, ErrorDeCelda, si_o_no
from Alumnos.models import Alumno, Tutor, TutorAlumno
from Alumnos.utils import clave_de_texto, compactar_espacios, normalizar_curp, normalizar_telefono
from Alumnos.vinculos import parentesco_de_texto, vincular_tutor

from .forms import TutorForm

COLUMNAS = (
    Columna('nombre', 'Nombre', 'Nombre o nombres del tutor.', ('Nombres', 'Nombre(s)'), requerida=True),
    Columna('apellido_paterno', 'Apellido paterno', 'Primer apellido.', ('Primer apellido',), requerida=True),
    Columna('apellido_materno', 'Apellido materno', 'Segundo apellido, si lo tiene.', ('Segundo apellido',)),
    Columna('telefono', 'Teléfono', '10 dígitos. Es el número principal de contacto.', ('Teléfono celular', 'Celular'), requerida=True),
    Columna('curp', 'CURP', 'Opcional. Si la escribes identifica al tutor: no se repite.'),
    Columna('telefono_alternativo', 'Teléfono alternativo', 'Opcional.'),
    Columna('correo_electronico', 'Correo electrónico', 'Opcional.', ('Correo', 'Email', 'E-mail')),
    Columna('estado_civil', 'Estado civil', 'Soltero/a, Casado/a, Divorciado/a, Viudo/a, Unión libre u Otro.'),
    Columna('religion', 'Religión', 'Texto libre.'),
    Columna('domicilio', 'Domicilio', 'Calle y número.'),
    Columna('colonia', 'Colonia', ''),
    Columna('ciudad', 'Ciudad', ''),
    Columna('estado', 'Estado', ''),
    Columna('cp', 'CP', '5 dígitos.', ('Código postal', 'C.P.')),
    Columna('ocupacion', 'Ocupación', ''),
    Columna('lugar_trabajo', 'Lugar de trabajo', ''),
    Columna('telefono_trabajo', 'Teléfono del trabajo', 'Con extensión, si aplica.'),
    Columna('observaciones', 'Observaciones', 'Notas internas sobre el tutor.'),
    Columna('estatus', 'Estatus', 'Activo o Inactivo (dado de baja). Si falta queda Activo.'),
    Columna(
        'estudiantes', 'Referencia del estudiante',
        'Los estudiantes a su cargo, por su referencia (o su CURP). Si son varios, sepáralos con punto y coma: «8888; 8889».',
        ('Referencias de los estudiantes', 'Estudiante', 'Estudiantes', 'Referencia', 'Referencias'),
    ),
    Columna('estudiantes_curp', 'CURP del estudiante', 'Alternativa a la referencia; también se aceptan varias, separadas con punto y coma.', ('CURP de los estudiantes',)),
    Columna('parentesco', 'Parentesco', 'Con esos estudiantes: Madre, Padre, Abuela, Abuelo, Hermana, Hermano, Tía, Tío, Tutor legal u Otro. Indispensable si indicas estudiantes.'),
    Columna('contacto_emergencia', 'Contacto de emergencia', 'Sí o No.'),
    Columna('autorizado_recoger', 'Puede recoger al estudiante', 'Sí o No.', ('Autorizado para recoger',)),
    Columna('responsable_pagos', 'Responsable de pagos', 'Sí o No.'),
)

_BANDERAS = (
    ('contacto_emergencia', 'Contacto de emergencia'),
    ('autorizado_recoger', 'Puede recoger al estudiante'),
    ('responsable_pagos', 'Responsable de pagos'),
)


def _formas_de_estado_civil():
    formas = {}
    for codigo, etiqueta in Tutor.ESTADO_CIVIL_CHOICES:
        clave = clave_de_texto(etiqueta)                       # «soltero/a»
        base = clave.split('/')[0]                              # «soltero»
        femenino = base[:-1] + 'a' if base.endswith('o') else base
        for forma in (clave, base, femenino, clave_de_texto(codigo.replace('_', ' '))):
            formas[forma] = codigo
    return formas


_ESTADOS_CIVILES = _formas_de_estado_civil()
_ESTATUS = {'activo': 'ACTIVO', 'inactivo': 'INACTIVO', 'baja': 'INACTIVO', 'dado de baja': 'INACTIVO'}
_SEPARADOR_DE_ESTUDIANTES = re.compile(r'[;,|\n]+')


# ---------------------------------------------------------------------------
# Lectura del archivo
# ---------------------------------------------------------------------------
def leer_filas(contenido):
    """Las filas del CSV de tutores: lista de (número de fila, {clave de columna: texto}). Ver lectura_csv.leer_filas."""
    return lectura_csv.leer_filas(contenido, COLUMNAS, 'tutores')


def plantilla_csv():
    """El CSV de la plantilla de tutores: solo los encabezados."""
    return lectura_csv.plantilla_csv(COLUMNAS)


# ---------------------------------------------------------------------------
# Interpretación de cada celda
# ---------------------------------------------------------------------------
def _estado_civil(texto):
    clave = clave_de_texto(texto)
    if not clave:
        return ''
    if clave not in _ESTADOS_CIVILES:
        raise ErrorDeCelda(f'Estado civil: «{texto}» no es válido. Usa Soltero/a, Casado/a, Divorciado/a, Viudo/a, Unión libre u Otro.')
    return _ESTADOS_CIVILES[clave]


def _estatus(texto):
    clave = clave_de_texto(texto)
    if not clave:
        return 'ACTIVO'
    if clave not in _ESTATUS:
        raise ErrorDeCelda(f'Estatus: «{texto}» no es válido. Usa Activo o Inactivo.')
    return _ESTATUS[clave]


# ---------------------------------------------------------------------------
# Una fila = un tutor
# ---------------------------------------------------------------------------
@dataclass
class Resultado:
    creados: list = field(default_factory=list)       # {'fila', 'nombre', 'vinculos'}
    ampliados: int = 0                                 # ya estaban registrados y se les vincularon más estudiantes
    errores: list = field(default_factory=list)       # {'fila', 'persona', 'motivo'}
    omitidos: int = 0                                  # ya estaban registrados y no hubo nada nuevo que hacer
    vinculos: int = 0                                  # vínculos con estudiantes que se crearon en total
    total: int = 0

    @property
    def con_error(self):
        return len(self.errores)

    @property
    def hubo_cambios(self):
        return bool(self.creados or self.ampliados)


class Importador:
    """Procesa las filas de un archivo. Úsese una vez por archivo: guarda lo que ya se registró para detectar repetidos."""

    def __init__(self):
        self.por_curp = {}
        self.por_nombre_y_telefono = {}
        for tutor in Tutor.objects.order_by('estatus', 'pk'):       # los activos van antes si hay dos iguales
            self._recordar(tutor)
        self.alumnos_por_referencia, self.alumnos_por_curp = {}, {}
        for alumno in Alumno.objects.only('pk', 'nombre', 'apellido_paterno', 'apellido_materno', 'referencia', 'curp', 'estatus'):
            self.alumnos_por_referencia[alumno.referencia] = alumno
            self.alumnos_por_curp[alumno.curp] = alumno

    @staticmethod
    def _llave(nombre, apellido_paterno, apellido_materno, telefono):
        return normalizar_telefono(telefono), clave_de_texto(f'{nombre} {apellido_paterno} {apellido_materno}')

    def _recordar(self, tutor):
        if tutor.curp:
            self.por_curp.setdefault(tutor.curp, tutor)
        self.por_nombre_y_telefono.setdefault(
            self._llave(tutor.nombre, tutor.apellido_paterno, tutor.apellido_materno, tutor.telefono), tutor,
        )

    # --- estudiantes ------------------------------------------------------------------------------
    def _estudiantes(self, datos, motivos):
        """Los estudiantes de la fila (sin repetir y en el orden en que se escribieron); anota en `motivos` los que no sirven."""
        textos = [datos.get('estudiantes', ''), datos.get('estudiantes_curp', '')]
        encontrados = {}
        for texto in textos:
            for token in _SEPARADOR_DE_ESTUDIANTES.split(texto):
                token = token.strip()
                if not token:
                    continue
                alumno = self.alumnos_por_referencia.get(token) or self.alumnos_por_curp.get(normalizar_curp(token))
                if alumno is None:
                    motivos.append(f'Estudiante: no existe uno con la referencia o la CURP «{token}».')
                elif alumno.estatus == 'BAJA':
                    motivos.append(f'Estudiante: {alumno} está dado de baja y no se puede vincular.')
                else:
                    encontrados.setdefault(alumno.pk, alumno)
        return list(encontrados.values())

    # --- fila -------------------------------------------------------------------------------------
    def procesar(self, datos):
        """Registra al tutor de una fila.

        Devuelve (estado, detalle): ('creado', {...}), ('ampliado', {...}) si ya existía y se le vincularon estudiantes,
        ('omitido', None) si ya existía y no había nada nuevo, o ('error', texto con todos los motivos).
        """
        motivos = []

        def celda(conversor, *argumentos, defecto=''):
            """El valor de una celda ya interpretado; si no es válido, anota el motivo y devuelve `defecto`."""
            try:
                return conversor(*argumentos)
            except ErrorDeCelda as error:
                motivos.append(str(error))
                return defecto

        estado_civil = celda(_estado_civil, datos.get('estado_civil', ''))
        estatus = celda(_estatus, datos.get('estatus', ''), defecto='ACTIVO')
        banderas = {clave: celda(si_o_no, datos.get(clave, ''), etiqueta, defecto=False) for clave, etiqueta in _BANDERAS}

        pidio_estudiantes = any(_SEPARADOR_DE_ESTUDIANTES.sub('', datos.get(c, '')).strip() for c in ('estudiantes', 'estudiantes_curp'))
        estudiantes = self._estudiantes(datos, motivos)
        parentesco = ''
        if pidio_estudiantes:
            texto = datos.get('parentesco', '')
            if not texto:
                motivos.append('Parentesco: indica el parentesco con los estudiantes.')
            else:
                parentesco = parentesco_de_texto(texto) or 'OTRO'

        curp = normalizar_curp(datos.get('curp'))
        existente = self.por_curp.get(curp) if curp else None
        if existente is None:
            existente = self.por_nombre_y_telefono.get(self._llave(
                datos.get('nombre', ''), datos.get('apellido_paterno', ''), datos.get('apellido_materno', ''), datos.get('telefono', ''),
            ))

        form = None
        if existente is not None:
            if estudiantes and existente.estatus != 'ACTIVO':
                motivos.append(f'Tutor: {existente} ya está registrado pero dado de baja. Reactívalo para vincularlo con estudiantes.')
        else:
            form = TutorForm({
                'nombre': datos.get('nombre', ''), 'apellido_paterno': datos.get('apellido_paterno', ''),
                'apellido_materno': datos.get('apellido_materno', ''), 'curp': curp, 'estado_civil': estado_civil,
                'religion': datos.get('religion', ''), 'telefono': datos.get('telefono', ''),
                'telefono_alternativo': datos.get('telefono_alternativo', ''),
                'correo_electronico': datos.get('correo_electronico', ''), 'domicilio': datos.get('domicilio', ''),
                'colonia': datos.get('colonia', ''), 'ciudad': datos.get('ciudad', ''), 'estado': datos.get('estado', ''),
                'cp': datos.get('cp', ''), 'ocupacion': datos.get('ocupacion', ''), 'lugar_trabajo': datos.get('lugar_trabajo', ''),
                'telefono_trabajo': datos.get('telefono_trabajo', ''), 'observaciones': datos.get('observaciones', ''),
            })
            if not form.is_valid():
                for campo, errores in form.errors.items():
                    etiqueta = form.fields[campo].label if campo in form.fields else ''
                    motivos.extend(f'{etiqueta}: {error}' if etiqueta else str(error) for error in errores)
            if estudiantes and estatus != 'ACTIVO':
                motivos.append('Estatus: un tutor dado de baja no se puede vincular con estudiantes.')
        if motivos:
            return 'error', ' · '.join(motivos)

        try:
            with transaction.atomic():
                tutor = existente
                if tutor is None:
                    tutor = form.save()
                    if estatus != 'ACTIVO':
                        tutor.estatus = estatus
                        tutor.save(update_fields=['estatus', 'modificado'])
                nuevos = 0
                for alumno in estudiantes:
                    if TutorAlumno.objects.filter(tutor=tutor, alumno=alumno, activo=True).exists():
                        continue                                        # ya estaba vinculado: no se pisan sus datos
                    vincular_tutor(tutor, alumno, {'parentesco': parentesco, 'activo': True, 'recibe_notificaciones': True, **banderas})
                    nuevos += 1
        except IntegrityError:
            return 'error', 'No se pudo guardar: algún dato único (como la CURP) ya pertenece a otro tutor.'

        if existente is None:
            self._recordar(tutor)
            return 'creado', {'nombre': str(tutor), 'vinculos': nuevos}
        if nuevos:
            return 'ampliado', {'nombre': str(tutor), 'vinculos': nuevos}
        return 'omitido', None


def importar(filas):
    """Registra los tutores de las filas que devolvió `leer_filas` y resume lo ocurrido."""
    importador = Importador()
    resultado = Resultado(total=len(filas))
    for fila, datos in filas:
        estado, detalle = importador.procesar(datos)
        if estado == 'creado':
            resultado.creados.append({'fila': fila, **detalle})
            resultado.vinculos += detalle['vinculos']
        elif estado == 'ampliado':
            resultado.ampliados += 1
            resultado.vinculos += detalle['vinculos']
        elif estado == 'omitido':
            resultado.omitidos += 1
        else:
            nombre = compactar_espacios(f'{datos.get("nombre", "")} {datos.get("apellido_paterno", "")}')
            resultado.errores.append({'fila': fila, 'persona': nombre, 'motivo': detalle})
    return resultado
