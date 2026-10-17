"""Mensajes con formato (pedido del 2026-10-17): limpieza en el servidor, texto plano y presentación.

El editor de la pantalla de mensajes (static/js/editor-mensajes.js) manda HTML. Nunca se guarda tal cual: aquí se vuelve
a construir con una lista cerrada de etiquetas, atributos y estilos (con valores comprobados uno por uno); lo demás se
descarta. Las etiquetas peligrosas (script, style, iframe…) se quitan con todo su contenido; las desconocidas se quitan
pero su texto se conserva. El texto siempre se escapa al volver a escribirlo, así que nada de lo que llegue puede
convertirse en código.

Imágenes: solo las subidas a la propia conversación (Mensajes.models.ImagenMensaje). Se guardan como
<img data-imagen="7" alt="…"> sin dirección; la dirección se pone al mostrarlas, según quién mira (el sistema y cada portal
tienen su propia ruta protegida).

Enlaces: solo http, https, mailto y tel; se abren en otra pestaña sin dar acceso a la página de origen.
"""
import re
from html import escape
from html.parser import HTMLParser

# Etiquetas que se conservan (con sus atributos permitidos, abajo)
ETIQUETAS = {
    'p', 'div', 'br', 'h1', 'h2', 'h3', 'blockquote', 'strong', 'b', 'em', 'i', 'u', 's', 'strike', 'del', 'span', 'sub', 'sup',
    'a', 'ul', 'ol', 'li', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'img',
}
# Se quitan con todo lo que tengan dentro
DESCARTAR_CON_CONTENIDO = {
    'script', 'style', 'template', 'iframe', 'object', 'embed', 'noscript', 'svg', 'math', 'textarea', 'select', 'option',
    'title', 'head', 'frame', 'frameset', 'canvas', 'video', 'audio', 'button', 'form', 'input', 'applet', 'xml', 'meta', 'link',
}
VACIAS = {'br', 'img'}
EN_LINEA = {'strong', 'b', 'em', 'i', 'u', 's', 'strike', 'del', 'span', 'sub', 'sup', 'a', 'font'}
BLOQUES_CON_ALINEACION = {'p', 'div', 'h1', 'h2', 'h3', 'blockquote', 'li', 'td', 'th'}
PROFUNDIDAD_MAXIMA = 40

# Tipografías que ofrece el editor (la clave, en minúsculas; el valor, como se escribe)
FUENTES = {
    'nunito': 'Nunito', 'arial': 'Arial', 'georgia': 'Georgia', 'times new roman': 'Times New Roman',
    'courier new': 'Courier New', 'verdana': 'Verdana', 'trebuchet ms': 'Trebuchet MS',
}
ESTILOS_DE_LISTA = {
    'ol': {'decimal', 'lower-alpha', 'upper-alpha', 'lower-roman', 'upper-roman'},
    'ul': {'disc', 'circle', 'square'},
}
TIPO_DE_LISTA = {'1': 'decimal', 'a': 'lower-alpha', 'A': 'upper-alpha', 'i': 'lower-roman', 'I': 'upper-roman'}
ESQUEMAS = ('http://', 'https://', 'mailto:', 'tel:')

_COLOR = re.compile(r'^(#[0-9a-f]{3}|#[0-9a-f]{6}|rgba?\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*(,\s*(0|1|0?\.\d{1,3})\s*)?\))$', re.I)
_TAMANO = re.compile(r'^(\d{1,2}(?:\.\d)?)(pt|px)$')
_PIXELES = re.compile(r'^(\d{1,4})(?:\.\d+)?px$')
_ANCHO = re.compile(r'^(\d{1,4})(?:\.\d+)?(%|px)$')
_NUMERO = re.compile(r'^\d{1,4}$')
_CONTROL = re.compile(r'[\x00-\x20\x7f]+')


# ---------------------------------------------------------------------------
# Estilos
# ---------------------------------------------------------------------------
def _color(valor):
    return valor.lower().replace(' ', '') if _COLOR.match(valor) else None


def _fuente(valor):
    primera = valor.split(',')[0].strip().strip('\'"').strip().lower()
    nombre = FUENTES.get(primera)
    return f"'{nombre}'" if nombre and ' ' in nombre else nombre


def _tamano(valor):
    coincide = _TAMANO.match(valor)
    if not coincide:
        return None
    numero, unidad = float(coincide.group(1)), coincide.group(2)
    limites = (8, 48) if unidad == 'pt' else (10, 64)
    return f'{coincide.group(1)}{unidad}' if limites[0] <= numero <= limites[1] else None


def _peso(valor):
    return {'bold': 'bold', 'bolder': 'bold', '700': 'bold', '600': 'bold', '800': 'bold', '900': 'bold',
            'normal': 'normal', '400': 'normal'}.get(valor)


def _decoracion(valor):
    marcas = [parte for parte in valor.split() if parte in ('underline', 'line-through', 'none')]
    return ' '.join(dict.fromkeys(marcas)) or None


def _alineacion(valor):
    return {'left': 'left', 'start': 'left', 'center': 'center', 'right': 'right', 'end': 'right', 'justify': 'justify'}.get(valor)


def _sangria(valor):
    coincide = _PIXELES.match(valor)
    if not coincide:
        return None
    return f'{min(int(coincide.group(1)), 400)}px' if int(coincide.group(1)) else None


def _ancho(valor):
    coincide = _ANCHO.match(valor)
    if not coincide:
        return None
    numero, unidad = int(coincide.group(1)), coincide.group(2)
    if unidad == '%':
        return f'{numero}%' if 10 <= numero <= 100 else None
    return f'{numero}px' if 16 <= numero <= 1600 else None


_EN_LINEA = {
    'color': ('color', _color), 'background-color': ('background-color', _color), 'background': ('background-color', _color),
    'font-family': ('font-family', _fuente), 'font-size': ('font-size', _tamano), 'font-weight': ('font-weight', _peso),
    'font-style': ('font-style', lambda v: v if v in ('italic', 'normal') else None),
    'text-decoration': ('text-decoration-line', _decoracion), 'text-decoration-line': ('text-decoration-line', _decoracion),
}
_BLOQUE = {
    'text-align': ('text-align', _alineacion), 'margin-left': ('margin-left', _sangria), 'padding-left': ('margin-left', _sangria),
}


def limpiar_estilo(etiqueta, estilo):
    """Las propiedades permitidas para esa etiqueta, con valores comprobados ('' si no queda ninguna)."""
    permitidas = {}
    if etiqueta in EN_LINEA:
        permitidas.update(_EN_LINEA)
    if etiqueta in BLOQUES_CON_ALINEACION:
        permitidas.update(_BLOQUE)
    if etiqueta in ESTILOS_DE_LISTA:
        tipos = ESTILOS_DE_LISTA[etiqueta]
        permitidas['list-style-type'] = ('list-style-type', lambda v, tipos=tipos: v if v in tipos else None)
        permitidas['margin-left'] = ('margin-left', _sangria)
    if etiqueta == 'img':
        permitidas['width'] = ('width', _ancho)
    resultado = {}
    for declaracion in (estilo or '').split(';'):
        propiedad, _, valor = declaracion.partition(':')
        propiedad = propiedad.strip().lower()
        valor = valor.replace('!important', '').strip()
        # Nada que pueda cargar recursos o ejecutar: ni url(), ni expression(), ni escapes de CSS
        if not valor or '\\' in valor or 'url(' in valor.lower() or 'expression' in valor.lower() or propiedad not in permitidas:
            continue
        nombre, comprobar = permitidas[propiedad]
        limpio = comprobar(valor if propiedad == 'font-family' else valor.lower())
        if limpio:
            resultado[nombre] = limpio
    return '; '.join(f'{nombre}: {valor}' for nombre, valor in resultado.items())


def limpiar_enlace(direccion):
    """La dirección si es http(s), mailto o tel (las que empiezan con «www.», como https); si no, None."""
    direccion = _CONTROL.sub('', direccion or '')
    if direccion.lower().startswith('www.'):
        direccion = f'https://{direccion}'
    return direccion if direccion.lower().startswith(ESQUEMAS) and len(direccion) <= 2000 else None


# ---------------------------------------------------------------------------
# Limpieza
# ---------------------------------------------------------------------------
class _Limpiador(HTMLParser):
    def __init__(self, imagenes_validas=None, url_de_imagen=None):
        super().__init__(convert_charrefs=True)
        self.imagenes_validas = imagenes_validas
        self.url_de_imagen = url_de_imagen
        self.salida = []
        self.abiertas = []        # etiquetas abiertas que se escribieron
        self.descartando = 0      # dentro de una etiqueta peligrosa
        self.imagenes = []

    # --- etiquetas -----------------------------------------------------------------------------------------
    def handle_starttag(self, etiqueta, atributos):
        etiqueta = etiqueta.lower()
        if self.descartando:
            if etiqueta in DESCARTAR_CON_CONTENIDO and etiqueta not in VACIAS:
                self.descartando += 1
            return
        if etiqueta in DESCARTAR_CON_CONTENIDO:
            if etiqueta not in ('input', 'meta', 'link'):   # vacías: no tienen contenido que descartar
                self.descartando = 1
            return
        if etiqueta == 'font':   # la que pone el navegador con algunos comandos: se vuelve un <span>
            etiqueta = 'span'
            atributos = self._de_font(atributos)
        if etiqueta not in ETIQUETAS or len(self.abiertas) >= PROFUNDIDAD_MAXIMA:
            return
        texto_atributos = self._atributos(etiqueta, dict(atributos))
        if texto_atributos is None:
            return
        self.salida.append(f'<{etiqueta}{texto_atributos}>')
        if etiqueta not in VACIAS:
            self.abiertas.append(etiqueta)

    def handle_startendtag(self, etiqueta, atributos):
        self.handle_starttag(etiqueta, atributos)
        if etiqueta.lower() not in VACIAS and self.abiertas and self.abiertas[-1] == etiqueta.lower():
            self.handle_endtag(etiqueta)

    def handle_endtag(self, etiqueta):
        etiqueta = etiqueta.lower()
        if self.descartando:
            if etiqueta in DESCARTAR_CON_CONTENIDO:
                self.descartando -= 1
            return
        if etiqueta == 'font':
            etiqueta = 'span'
        if etiqueta in VACIAS or etiqueta not in self.abiertas:
            return
        while self.abiertas:
            ultima = self.abiertas.pop()
            self.salida.append(f'</{ultima}>')
            if ultima == etiqueta:
                break

    def handle_data(self, datos):
        if not self.descartando:
            self.salida.append(escape(datos, quote=False))

    def handle_comment(self, datos):
        return

    def handle_decl(self, declaracion):
        return

    def handle_pi(self, datos):
        return

    def unknown_decl(self, datos):
        return

    def cerrar(self):
        self.close()
        while self.abiertas:
            self.salida.append(f'</{self.abiertas.pop()}>')
        return ''.join(self.salida)

    # --- atributos -----------------------------------------------------------------------------------------
    @staticmethod
    def _de_font(atributos):
        datos = dict(atributos)
        estilo = []
        if datos.get('color'):
            estilo.append(f"color: {datos['color']}")
        if datos.get('face'):
            estilo.append(f"font-family: {datos['face']}")
        return [('style', '; '.join(estilo))] if estilo else []

    def _atributos(self, etiqueta, datos):
        """El texto de los atributos permitidos (' href="…"'), o None si la etiqueta no debe quedar (una imagen ajena)."""
        partes = []
        estilo = datos.get('style', '')
        if etiqueta in ('ol', 'ul') and datos.get('type') in TIPO_DE_LISTA and etiqueta == 'ol':
            estilo = f"list-style-type: {TIPO_DE_LISTA[datos['type']]}; {estilo}"
        if etiqueta == 'a':
            direccion = limpiar_enlace(datos.get('href', ''))
            if direccion:
                partes.append(f' href="{escape(direccion)}" target="_blank" rel="noopener noreferrer nofollow"')
            if datos.get('title'):
                partes.append(f' title="{escape(datos["title"][:200])}"')
        elif etiqueta == 'img':
            imagen = datos.get('data-imagen', '')
            if not imagen.isdigit() or (self.imagenes_validas is not None and int(imagen) not in self.imagenes_validas):
                return None
            self.imagenes.append(int(imagen))
            partes.append(f' data-imagen="{int(imagen)}"')
            if self.url_de_imagen is not None:
                partes.append(f' src="{escape(self.url_de_imagen(int(imagen)))}" loading="lazy"')
            partes.append(f' alt="{escape((datos.get("alt") or "")[:250])}"')
        elif etiqueta == 'ol' and _NUMERO.match(datos.get('start', '')) and int(datos['start']) > 1:
            partes.append(f' start="{int(datos["start"])}"')
        elif etiqueta in ('td', 'th'):
            for nombre in ('colspan', 'rowspan'):
                if _NUMERO.match(datos.get(nombre, '')) and 1 < int(datos[nombre]) <= 20:
                    partes.append(f' {nombre}="{int(datos[nombre])}"')
        estilo = limpiar_estilo(etiqueta, estilo)
        if estilo:
            partes.append(f' style="{escape(estilo)}"')
        return ''.join(partes)


def limpiar(html, imagenes_validas=None, url_de_imagen=None):
    """(html limpio, [ids de las imágenes que quedaron]). `imagenes_validas`: los ids que puede usar (None = cualquiera);
    `url_de_imagen(id)`: la dirección con que se muestra cada imagen (sin ella, las imágenes quedan sin dirección)."""
    limpiador = _Limpiador(imagenes_validas, url_de_imagen)
    limpiador.feed(html or '')
    resultado = limpiador.cerrar()
    return resultado.strip(), limpiador.imagenes


def presentar(html, url_de_imagen):
    """El HTML guardado, listo para mostrarse a quien mira (se vuelve a limpiar: lo guardado tampoco se da por bueno)."""
    return limpiar(html, url_de_imagen=url_de_imagen)[0]


# ---------------------------------------------------------------------------
# Texto plano (vista previa, avisos, búsqueda) y mensajes vacíos
# ---------------------------------------------------------------------------
TEXTO_DE_IMAGEN = '📷 Imagen'
_SALTOS = {'p', 'div', 'h1', 'h2', 'h3', 'blockquote', 'li', 'tr', 'table', 'ul', 'ol'}


class _Texto(HTMLParser):
    """Un renglón por bloque (sin renglones vacíos de más) y un salto por cada <br>."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partes = []

    def _salto(self):
        if self.partes and not self.partes[-1].endswith('\n'):
            self.partes.append('\n')

    def handle_starttag(self, etiqueta, atributos):
        if etiqueta == 'br':
            self.partes.append('\n')
        elif etiqueta == 'img':
            self.partes.append(f' {TEXTO_DE_IMAGEN} ')
        elif etiqueta in ('td', 'th'):
            self.partes.append(' ')
        elif etiqueta in _SALTOS:
            self._salto()
            if etiqueta == 'li':
                self.partes.append('• ')

    def handle_endtag(self, etiqueta):
        if etiqueta in _SALTOS:
            self._salto()
        elif etiqueta in ('td', 'th'):
            self.partes.append(' ')

    def handle_data(self, datos):
        datos = datos.replace('\xa0', ' ').replace('\u200b', '')
        if datos:
            self.partes.append(datos)


def texto_plano(html):
    """El texto del mensaje, sin formato: un renglón por párrafo, «• » en las listas y «📷 Imagen» por cada imagen."""
    lector = _Texto()
    lector.feed(html or '')
    lector.close()
    renglones = [' '.join(renglon.split()) for renglon in ''.join(lector.partes).split('\n')]
    texto = '\n'.join(renglones)
    return re.sub(r'\n{3,}', '\n\n', texto).strip()


def tiene_contenido(html):
    """Si hay algo más que etiquetas de formato vacías: texto visible o una imagen."""
    texto = texto_plano(html).replace(TEXTO_DE_IMAGEN, '').replace('•', '')
    return bool(texto.strip()) or '<img ' in (html or '')


_SIMPLE = re.compile(r'^(<p>[^<]*(<br>[^<]*)*</p>)+$')


def es_texto_simple(html):
    """Si el HTML limpio solo tiene párrafos de texto sin formato (entonces basta con guardar el texto plano)."""
    return bool(_SIMPLE.match(html or ''))
