"""Libros de Excel (.xlsx) sin dependencias: un .xlsx es un ZIP con XML (Office Open XML). Alcanza para reportes:
varias hojas, textos y números, una fila de títulos en negritas con fondo, títulos de sección y anchos de columna.

    libro([Hoja('Resumen', filas, anchos=[30, 12])])  -> bytes

Cada fila es una lista de celdas; una celda es un valor (texto, número, fecha o None) o `Celda(valor, estilo)` con
estilo TITULO, SECCION o ENCABEZADO. Los textos se escriben como texto (nunca como fórmulas), así que un valor que
empieza con «=» no se ejecuta en Excel.
"""
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from xml.sax.saxutils import escape

NORMAL, TITULO, SECCION, ENCABEZADO = 0, 1, 2, 3
_CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')


@dataclass
class Celda:
    valor: object
    estilo: int = NORMAL


@dataclass
class Hoja:
    nombre: str
    filas: list
    anchos: list = field(default_factory=list)


def _nombre_de_hoja(nombre, usados):
    limpio = re.sub(r'[\[\]:*?/\\]', ' ', nombre).strip()[:31] or 'Hoja'
    base, n = limpio, 2
    while limpio.lower() in usados:
        sufijo = f' ({n})'
        limpio, n = base[:31 - len(sufijo)] + sufijo, n + 1
    usados.add(limpio.lower())
    return limpio


def _columna(indice):
    letras = ''
    indice += 1
    while indice:
        indice, resto = divmod(indice - 1, 26)
        letras = chr(65 + resto) + letras
    return letras


def _celda_xml(referencia, celda):
    if not isinstance(celda, Celda):
        celda = Celda(celda)
    valor, estilo = celda.valor, celda.estilo
    atributo = f' s="{estilo}"' if estilo else ''
    if valor is None or valor == '':
        return f'<c r="{referencia}"{atributo}/>' if estilo else ''
    if isinstance(valor, bool):
        valor = 'Sí' if valor else 'No'
    if isinstance(valor, (int, float)):
        return f'<c r="{referencia}"{atributo}><v>{valor}</v></c>'
    if isinstance(valor, datetime):
        valor = valor.strftime('%d/%m/%Y %H:%M')
    elif isinstance(valor, date):
        valor = valor.strftime('%d/%m/%Y')
    texto = escape(_CONTROL.sub('', str(valor)))
    return f'<c r="{referencia}" t="inlineStr"{atributo}><is><t xml:space="preserve">{texto}</t></is></c>'


def _hoja_xml(hoja):
    filas = []
    for numero, fila in enumerate(hoja.filas, start=1):
        celdas = ''.join(_celda_xml(f'{_columna(i)}{numero}', celda) for i, celda in enumerate(fila))
        filas.append(f'<row r="{numero}">{celdas}</row>')
    columnas = ''
    if hoja.anchos:
        columnas = '<cols>' + ''.join(
            f'<col min="{i}" max="{i}" width="{ancho}" customWidth="1"/>' for i, ancho in enumerate(hoja.anchos, start=1)
        ) + '</cols>'
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'{columnas}<sheetData>{"".join(filas)}</sheetData></worksheet>'
    )


_ESTILOS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="4">'
    '<font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="14"/><name val="Calibri"/></font>'
    '<font><b/><sz val="12"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font>'
    '</fonts>'
    '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFE2E8F0"/><bgColor indexed="64"/></patternFill></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="4">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"><alignment vertical="top" wrapText="1"/></xf>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '<xf numFmtId="0" fontId="3" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
    '</cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    '</styleSheet>'
)


def libro(hojas):
    """Los bytes de un .xlsx con esas hojas."""
    usados = set()
    nombres = [_nombre_de_hoja(hoja.nombre, usados) for hoja in hojas]
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, 'w', zipfile.ZIP_DEFLATED) as archivo:
        archivo.writestr('[Content_Types].xml', (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            + ''.join(
                f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                for i in range(1, len(hojas) + 1)
            ) + '</Types>'
        ))
        archivo.writestr('_rels/.rels', (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>'
        ))
        archivo.writestr('xl/workbook.xml', (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
            + ''.join(f'<sheet name="{escape(nombre, {chr(34): "&quot;"})}" sheetId="{i}" r:id="rId{i}"/>' for i, nombre in enumerate(nombres, start=1))
            + '</sheets></workbook>'
        ))
        archivo.writestr('xl/_rels/workbook.xml.rels', (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + ''.join(
                f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                for i in range(1, len(hojas) + 1)
            )
            + f'<Relationship Id="rId{len(hojas) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '</Relationships>'
        ))
        archivo.writestr('xl/styles.xml', _ESTILOS)
        for i, hoja in enumerate(hojas, start=1):
            archivo.writestr(f'xl/worksheets/sheet{i}.xml', _hoja_xml(hoja))
    return salida.getvalue()
