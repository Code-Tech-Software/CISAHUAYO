"""La clave que se propone para una materia nueva: sus iniciales y, si se sabe, el grado en el que se imparte.

«Matemáticas» en 1° de primaria → «MAT-1P»; «Educación Física» en 3° de secundaria → «EF-3S»; en varios grados del mismo
nivel solo va la letra del nivel («EF-P»), y en grados de niveles distintos, solo las iniciales («EF»). Si ya existe, se le
agrega un número («MAT-1P-2»). Es solo una ayuda: la clave se puede cambiar.
"""
import re

from Alumnos.models import Materia
from Alumnos.utils import clave_de_texto

# La letra de cada nivel en la clave: K de kínder (como la equivalencia K1), B de bachillerato para no chocar con primaria
LETRA_DE_NIVEL = {'PREESCOLAR': 'K', 'PRIMARIA': 'P', 'SECUNDARIA': 'S', 'PREPARATORIA': 'B'}
PALABRAS_VACIAS = {'a', 'al', 'con', 'de', 'del', 'e', 'el', 'en', 'la', 'las', 'lo', 'los', 'o', 'para', 'por', 'u', 'y'}
LARGO_MAXIMO = 20


def iniciales_de_materia(nombre):
    """«Matemáticas» → «MAT» (una palabra: sus tres primeras letras); «Formación Cívica y Ética» → «FCE»."""
    palabras = [p for p in re.findall(r'[a-z0-9]+', clave_de_texto(nombre)) if p not in PALABRAS_VACIAS]
    if not palabras:
        return ''
    if len(palabras) == 1:
        return palabras[0][:3].upper()
    return ''.join(palabra[0] for palabra in palabras)[:5].upper()


def codigo_de_grados(grados):
    """Un grado → «1P»; varios del mismo nivel → «P»; de niveles distintos (o ninguno) → «»."""
    grados = list(grados)
    if len(grados) == 1:
        return f'{grados[0].numero}{LETRA_DE_NIVEL.get(grados[0].nivel, "")}'
    niveles = {grado.nivel for grado in grados}
    return LETRA_DE_NIVEL.get(niveles.pop(), '') if len(niveles) == 1 else ''


def clave_sugerida(nombre, grados=(), excluir=None):
    """La clave libre que corresponde (vacía si el nombre no tiene letras ni números). `excluir`: la materia en edición."""
    base = '-'.join(parte for parte in (iniciales_de_materia(nombre), codigo_de_grados(grados)) if parte)
    if not base:
        return ''
    base = base[:LARGO_MAXIMO - 3]
    usadas = {
        clave.upper()
        for clave in Materia.objects.filter(clave__istartswith=base).exclude(pk=excluir).values_list('clave', flat=True)
    }
    candidata, numero = base, 1
    while candidata.upper() in usadas:
        numero += 1
        candidata = f'{base}-{numero}'
    return candidata
