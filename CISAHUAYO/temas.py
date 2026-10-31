"""Temas de color del sistema: cada persona elige el suyo en Ajustes (se guarda en su perfil).

Los colores viven en static/css/temas.css: cada tema define ahí sus colores de entrada en `[data-tema="<clave>"]` y
de ellos salen todos los colores de la interfaz (acción, fondos, textos, estados y tonos), en claro y en oscuro.
Aquí van el nombre que se ve, la descripción, el color de la barra del navegador (`<meta name="theme-color">`) y sus
letras de Google Fonts (`fuentes`: la parte `family=…` de la dirección; `letra`: cómo se llaman, para mostrarlo).
Para agregar un tema: su entrada en esta lista y su bloque en temas.css (lo comprueba Ajustes/tests.py, también el
contraste de sus colores).
"""

PREDETERMINADO = 'corporate'

TEMAS = (
    {
        'clave': 'institucional',
        'nombre': 'Institucional',
        'descripcion': 'Turquesa, amarillo y guinda: los colores del colegio.',
        'color': '#245a62',
        'letra': 'Plus Jakarta Sans y Sora',
        'fuentes': 'family=Plus+Jakarta+Sans:wght@400;500;600;700&family=Sora:wght@600;700',
    },
    {
        'clave': 'oceano',
        'nombre': 'Océano',
        'descripcion': 'Azul intenso con arena y coral.',
        'color': '#3c50d0',
        'letra': 'Figtree y Lexend',
        'fuentes': 'family=Figtree:wght@400;500;600;700&family=Lexend:wght@500;600;700',
    },
    {
        'clave': 'esmeralda',
        'nombre': 'Esmeralda',
        'descripcion': 'Verde vivo con lima y rosa.',
        'color': '#047857',
        'letra': 'Nunito',
        'fuentes': 'family=Nunito+Sans:wght@400;500;600;700&family=Nunito:wght@600;700;800',
    },
    {
        'clave': 'frambuesa',
        'nombre': 'Frambuesa',
        'descripcion': 'Magenta con naranja y violeta.',
        'color': '#be185d',
        'letra': 'Outfit',
        'fuentes': 'family=Outfit:wght@400;500;600;700',
    },
    {
        'clave': 'mandarina',
        'nombre': 'Mandarina',
        'descripcion': 'Naranja con amarillo y verde azulado.',
        'color': '#c2410c',
        'letra': 'Rubik',
        'fuentes': 'family=Rubik:wght@400;500;600;700',
    },
    {
        'clave': 'violeta',
        'nombre': 'Violeta',
        'descripcion': 'Morado con ámbar y fucsia.',
        'color': '#6d28d9',
        'letra': 'DM Sans y Space Grotesk',
        'fuentes': 'family=DM+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700',
    },
    {
        'clave': 'grafito',
        'nombre': 'Grafito',
        'descripcion': 'Gris carbón sobrio con un toque amarillo.',
        'color': '#334155',
        'letra': 'IBM Plex Sans',
        'fuentes': 'family=IBM+Plex+Sans:wght@400;500;600;700',
    },
    {
        'clave': 'nextlevel',
        'nombre': 'Next Level',
        'descripcion': 'Azul marino y verde, los colores de Next Level.',
        'color': '#142c45',
        'letra': 'Nunito y Fredoka',
        'fuentes': 'family=Nunito:wght@400;500;600;700;800&family=Fredoka:wght@500;600;700',
    },
    {
        'clave': 'corporate',
        'nombre': 'Corporate',
        'descripcion': 'Azul zafiro con grises fríos: sobrio y profesional.',
        'color': '#2c76cd',
        'letra': 'Inter',
        'fuentes': 'family=Inter:wght@400;500;600;700',
    },
)

POR_CLAVE = {tema['clave']: tema for tema in TEMAS}

MENU_CLARO = 'claro'
MENU_DE_COLOR = 'color'
MENUS = ((MENU_CLARO, 'Claro'), (MENU_DE_COLOR, 'De color'))


def opciones():
    """(clave, nombre) de cada tema, para el campo del perfil (una función: agregar un tema no pide migración)."""
    return [(tema['clave'], tema['nombre']) for tema in TEMAS]


def tema(clave):
    """El tema con esa clave; si ya no existe, el predeterminado."""
    return POR_CLAVE.get(clave) or POR_CLAVE[PREDETERMINADO]


GOOGLE_FONTS = 'https://fonts.googleapis.com/css2?'


def url_de_fuentes(clave):
    """La hoja de Google Fonts con las letras de ese tema (cada página carga solo las de su tema)."""
    return f"{GOOGLE_FONTS}{tema(clave)['fuentes']}&display=swap"


def url_de_todas_las_fuentes():
    """Las letras de todos los temas, sin repetir familias: para la página de Ajustes, que los muestra todos."""
    familias = {}
    for datos in TEMAS:
        for familia in datos['fuentes'].split('&'):
            nombre, _, pesos = familia.partition(':wght@')
            ya = set(familias.get(nombre, '').split(';')) - {''}
            familias[nombre] = ';'.join(sorted(ya | set(pesos.split(';')), key=int))
    return GOOGLE_FONTS + '&'.join(f'{nombre}:wght@{pesos}' for nombre, pesos in familias.items()) + '&display=swap'
