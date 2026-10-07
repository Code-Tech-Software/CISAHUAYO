"""Lectura de archivos CSV para las importaciones (estudiantes y tutores).

Convierte los bytes de un CSV en filas `{clave de columna: texto}` según las columnas que declara cada importación.
Es tolerante con lo que producen las hojas de cálculo en español: UTF-8 con o sin BOM, Windows-1252, y separadores
coma, punto y coma, tabulador o barra vertical. Aquí no se interpreta el contenido de las celdas, solo se lee.
"""
import csv
import io
import re
from dataclasses import dataclass

from .utils import clave_de_texto

TAMANO_MAXIMO = 2 * 1024 * 1024  # 2 MB
FILAS_MAXIMAS = 1000
ERRORES_GUARDADOS = 200          # cuántos errores se conservan para mostrarlos tras importar


@dataclass(frozen=True)
class Columna:
    clave: str
    titulo: str                  # el encabezado de la plantilla
    ayuda: str                   # qué se escribe en ella
    alias: tuple = ()            # otros nombres que se reconocen
    requerida: bool = False


class ErrorDeArchivo(Exception):
    """El archivo no se puede importar (no se leyó, faltan columnas, es demasiado grande…)."""


class ErrorDeCelda(Exception):
    """El contenido de una celda no es válido; el mensaje dice qué corregir."""


def clave_de_encabezado(texto):
    texto = clave_de_texto(texto).replace('(s)', '')
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', texto).split())


def indice_de_encabezados(columnas):
    """{encabezado normalizado: Columna} con los títulos y los alias de cada columna."""
    return {clave_de_encabezado(nombre): columna for columna in columnas for nombre in (columna.titulo, *columna.alias)}


def leer_filas(contenido, columnas, registros='estudiantes'):
    """Convierte los bytes de un CSV en una lista de (número de fila, {clave de columna: texto}).

    Las columnas que no se reconocen se ignoran y las filas vacías se saltan. `registros` solo se usa en los mensajes.
    """
    if len(contenido) > TAMANO_MAXIMO:
        raise ErrorDeArchivo(f'El archivo pesa más de {TAMANO_MAXIMO // (1024 * 1024)} MB. Divídelo en varios.')
    for codificacion in ('utf-8-sig', 'cp1252'):
        try:
            texto = contenido.decode(codificacion)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ErrorDeArchivo('No se pudo leer el archivo: guárdalo como CSV (UTF-8) desde tu hoja de cálculo.')

    primera = next((linea for linea in texto.splitlines() if linea.strip()), '')
    if not primera:
        raise ErrorDeArchivo('El archivo está vacío.')
    separador = max(',;\t|', key=primera.count)

    lector = csv.reader(io.StringIO(texto, newline=''), delimiter=separador)
    encabezados = next((fila for fila in lector if any(celda.strip() for celda in fila)), [])
    indice = indice_de_encabezados(columnas)
    reconocidas = [indice.get(clave_de_encabezado(encabezado)) for encabezado in encabezados]

    faltan = [c.titulo for c in columnas if c.requerida and c not in reconocidas]
    if faltan:
        raise ErrorDeArchivo(
            'Al archivo le faltan columnas indispensables: ' + ', '.join(faltan) + '. '
            'Descarga la plantilla para ver los encabezados.'
        )

    filas = []
    for fila in lector:
        if not any(celda.strip() for celda in fila):
            continue
        datos = {}
        for columna, celda in zip(reconocidas, fila):
            if columna is not None and columna.clave not in datos:
                datos[columna.clave] = celda.strip()
        filas.append((lector.line_num, datos))
    if not filas:
        raise ErrorDeArchivo(f'El archivo no trae {registros}: solo tiene los encabezados.')
    if len(filas) > FILAS_MAXIMAS:
        raise ErrorDeArchivo(f'El archivo tiene {len(filas)} filas y el máximo es {FILAS_MAXIMAS}. Divídelo en varios.')
    return filas


def plantilla_csv(columnas):
    """El CSV que se descarga: solo los encabezados, con BOM para que Excel respete los acentos."""
    salida = io.StringIO()
    salida.write('﻿')
    csv.writer(salida).writerow([columna.titulo for columna in columnas])
    return salida.getvalue()


_SI = {'si', 's', 'x', 'yes', 'y', '1', 'true', 'verdadero'}
_NO = {'no', 'n', '0', 'false', 'falso'}


def si_o_no(texto, etiqueta):
    """True/False de una celda «Sí»/«No» (vacía = False)."""
    clave = clave_de_texto(texto)
    if not clave or clave in _NO:
        return False
    if clave in _SI:
        return True
    raise ErrorDeCelda(f'{etiqueta}: «{texto}» no es válido. Usa Sí o No.')
