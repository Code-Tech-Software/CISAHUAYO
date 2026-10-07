"""Utilidades de la sección de alumnos: CURP, referencias, contraseñas, religiones y teléfonos."""
import re
import unicodedata
from datetime import date

from django.core.exceptions import ValidationError
from django.db.models.functions import Length
from django.utils import timezone
from django.utils.crypto import get_random_string

ESTADOS_MX = (
    'Aguascalientes', 'Baja California', 'Baja California Sur', 'Campeche', 'Chiapas',
    'Chihuahua', 'Ciudad de México', 'Coahuila', 'Colima', 'Durango', 'Guanajuato',
    'Guerrero', 'Hidalgo', 'Jalisco', 'México', 'Michoacán', 'Morelos', 'Nayarit',
    'Nuevo León', 'Oaxaca', 'Puebla', 'Querétaro', 'Quintana Roo', 'San Luis Potosí',
    'Sinaloa', 'Sonora', 'Tabasco', 'Tamaulipas', 'Tlaxcala', 'Veracruz', 'Yucatán',
    'Zacatecas',
)

# Formato oficial de la CURP (18 caracteres), con claves de entidad válidas.
CURP_RE = re.compile(
    r'^[A-Z][AEIOUX][A-Z]{2}\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])[HM]'
    r'(AS|BC|BS|CC|CL|CM|CS|CH|DF|DG|GT|GR|HG|JC|MC|MN|MS|NT|NL|OC|PL|QT|QR|SP|SL|SR|TC|TS|TL|VZ|YN|ZS|NE)'
    r'[B-DF-HJ-NP-TV-Z]{3}[0-9A-Z]\d$'
)

# Sin vocales ni caracteres que se confunden (0/o, 1/l/i) para que sea fácil de dictar.
ALFABETO_CONTRASENA = 'abcdefghjkmnpqrstuvwxyz23456789'


def compactar_espacios(valor):
    """Quita espacios sobrantes: '  Ana   María ' -> 'Ana María'."""
    return ' '.join((valor or '').split())


def normalizar_curp(valor):
    return re.sub(r'\s+', '', valor or '').upper()


def datos_de_curp(curp):
    """Devuelve {'fecha_nacimiento', 'sexo'} deducidos de una CURP, o None si no es válida.

    El 17.º carácter distingue el siglo: dígito = 1900-1999, letra = 2000 en adelante.
    El sexo se devuelve con los códigos del modelo ('M' masculino, 'F' femenino).
    """
    curp = normalizar_curp(curp)
    if not CURP_RE.match(curp):
        return None
    anio = int(curp[4:6]) + (1900 if curp[16].isdigit() else 2000)
    try:
        nacimiento = date(anio, int(curp[6:8]), int(curp[8:10]))
    except ValueError:
        return None
    return {'fecha_nacimiento': nacimiento, 'sexo': 'M' if curp[10] == 'H' else 'F'}


def siguiente_referencia():
    """Propone la siguiente referencia numérica, conservando el ancho de la última."""
    from .models import Alumno

    ultima = (
        Alumno.objects.filter(referencia__regex=r'^[0-9]+$')
        .annotate(largo=Length('referencia'))
        .order_by('-largo', '-referencia')
        .values_list('referencia', flat=True)
        .first()
    )
    if ultima:
        return str(int(ultima) + 1).zfill(len(ultima))
    return f'{timezone.localdate().year}0001'


def generar_contrasena(longitud=8):
    return get_random_string(longitud, ALFABETO_CONTRASENA)


def sin_acentos(texto):
    """'Católica' -> 'Catolica'."""
    return ''.join(c for c in unicodedata.normalize('NFD', texto or '') if unicodedata.category(c) != 'Mn')


def clave_de_texto(texto):
    """Forma para comparar textos escritos a mano: sin acentos, en minúsculas y con los espacios compactados."""
    return ' '.join(sin_acentos(texto).lower().split())


# Cómo suele escribirse en un archivo lo que la lista de religiones nombra de otro modo
_RELIGIONES_POR_ALIAS = {
    'mormon': 'Iglesia de Jesucristo de los Santos de los Últimos Días',
    'mormona': 'Iglesia de Jesucristo de los Santos de los Últimos Días',
    'sud': 'Iglesia de Jesucristo de los Santos de los Últimos Días',
    'santos de los ultimos dias': 'Iglesia de Jesucristo de los Santos de los Últimos Días',
    'iglesia de jesucristo': 'Iglesia de Jesucristo de los Santos de los Últimos Días',
    'islam': 'Musulmana',
    'islamica': 'Musulmana',
    'judaismo': 'Judía',
    'hinduismo': 'Hinduista',
    'budismo': 'Budista',
}
# Respuestas que significan «sin religión»: se registran vacías
RELIGION_NINGUNA = {'ninguna', 'ninguno', 'ateo', 'atea', 'sin religion', 'no tiene', 'no aplica', 'n/a', 'na', 's/r', '-'}


def normalizar_religion(texto):
    """La religión de la lista (Alumno.RELIGION_CHOICES) a la que corresponde un texto escrito a mano, o None.

    Ignora acentos, mayúsculas y el género: «catolico», «Cristiano» y «musulmán» dan «Católica», «Cristiana» y «Musulmana».
    """
    from .models import Alumno

    conocidas = {clave_de_texto(valor): valor for valor, _ in Alumno.RELIGION_CHOICES}
    clave = clave_de_texto(texto)
    if clave in conocidas:
        return conocidas[clave]
    if clave in _RELIGIONES_POR_ALIAS:
        return _RELIGIONES_POR_ALIAS[clave]
    for variante in (clave[:-1] + 'a' if clave.endswith('o') else None, clave + 'a' if clave.endswith('n') else None):
        if variante in conocidas:
            return conocidas[variante]
    return None


def normalizar_telefono(valor):
    """Deja solo los 10 dígitos del número, quitando espacios, guiones y la lada +52."""
    digitos = re.sub(r'\D', '', valor or '')
    if len(digitos) == 13 and digitos.startswith('521'):
        digitos = digitos[3:]
    elif len(digitos) == 12 and digitos.startswith('52'):
        digitos = digitos[2:]
    return digitos


def validar_telefono(valor):
    """Normaliza y valida un teléfono de 10 dígitos; devuelve el número normalizado."""
    digitos = normalizar_telefono(valor)
    if len(digitos) != 10:
        raise ValidationError('Ingresa un teléfono de 10 dígitos.')
    return digitos


def proteger_celda_csv(valor):
    """Evita que Excel interprete como fórmula un texto que empieza con = + - @."""
    texto = '' if valor is None else str(valor)
    return f"'{texto}" if texto[:1] in ('=', '+', '-', '@') else texto
