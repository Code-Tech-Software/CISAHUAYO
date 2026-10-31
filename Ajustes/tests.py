"""Ajustes › Apariencia: cada persona elige su tema de color y cómo se ve el menú lateral; se guarda en su perfil y la
página se pinta ya con esos colores. Incluye la comprobación de contraste (WCAG AA) de cada tema de static/css/temas.css."""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse

from CISAHUAYO import temas
from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase
from Usuarios.models import PerfilUsuario

URL = '/ajustes/'
TEMAS_CSS = Path(settings.BASE_DIR) / 'static' / 'css' / 'temas.css'
ENTRADAS = (
    'primary', 'primary-hover', 'primary-dark', 'accent', 'accent-text', 'brand', 'brand-dark', 'stripe', 'sidebar', 'fondo',
    'success', 'warning', 'danger', 'info',
    *(f'tone-{n}' for n in range(1, 7)), *(f'tone-{n}-base' for n in range(1, 7)),
)
OPCIONALES = ('primary-text',)
FORMA = ('font-sans', 'font-display', 'radius-sm', 'radius-md', 'radius-lg', 'radius-xl')


@PRUEBAS
class PaginaTests(BaseTestCase):
    def test_pide_iniciar_sesion(self):
        self.client.logout()
        respuesta = self.client.get(URL)
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn('/admin/login/', respuesta['Location'])

    def test_cualquier_cuenta_la_abre_sin_permisos(self):
        self.client.force_login(self.sin_permisos)
        respuesta = self.client.get(URL)
        self.assertEqual(respuesta.status_code, 200)
        for tema in temas.TEMAS:
            self.assertContains(respuesta, tema['nombre'])
            self.assertContains(respuesta, f'data-tema="{tema["clave"]}"')
            self.assertContains(respuesta, f'Letra {tema["letra"]}.')
        self.assertContains(respuesta, 'family=Fredoka')   # las letras de todos los temas, para las tarjetas
        self.assertContains(respuesta, 'family=IBM+Plex+Sans')
        self.assertContains(respuesta, 'value="corporate" data-color="#2c76cd" checked')
        self.assertContains(respuesta, 'value="claro" checked')

    def test_el_modo_solo_aparece_con_javascript(self):
        html = self.client.get(URL).content.decode()
        self.assertRegex(html, r'data-modo hidden')
        for valor in ('light', 'dark', 'auto'):
            self.assertIn(f'name="modo" value="{valor}"', html)

    def test_se_llega_desde_el_menu_de_usuario_el_lateral_y_el_buscador(self):
        self.client.force_login(self.sin_permisos)
        respuesta = self.client.get(reverse('inicio'))
        self.assertContains(respuesta, 'Ajustes y apariencia')
        self.assertIn('Ajustes', [e['etiqueta'] for s in respuesta.context['navegacion'] for e in s['elementos']])
        self.assertIn('Cambiar el tema de color', [a['etiqueta'] for a in respuesta.context['acciones_rapidas']])


@PRUEBAS
class GuardarTests(BaseTestCase):
    def test_guarda_el_tema_y_el_menu_y_la_pagina_se_pinta_con_ellos(self):
        respuesta = self.client.post(URL, {'tema': 'oceano', 'menu_lateral': 'color'}, follow=True)
        self.assertRedirects(respuesta, URL)
        self.assertContains(respuesta, 'Listo: ahora usas el tema Océano.')
        perfil = PerfilUsuario.de(self.admin)
        self.assertEqual((perfil.tema, perfil.menu_lateral), ('oceano', 'color'))
        html = self.client.get(reverse('inicio')).content.decode()
        self.assertIn('<html lang="es" data-tema="oceano" data-menu="color">', html)
        self.assertIn('<meta name="theme-color" content="#3c50d0">', html)
        self.assertIn('family=Figtree', html)          # solo las letras de su tema
        self.assertNotIn('family=Plus+Jakarta+Sans', html)

    def test_por_omision_corporate_con_el_menu_claro(self):
        PerfilUsuario.objects.filter(usuario=self.admin).delete()
        html = self.client.get(reverse('inicio')).content.decode()
        self.assertIn('<html lang="es" data-tema="corporate">', html)
        self.assertIn('css/temas.css', html)

    def test_con_javascript_responde_json(self):
        respuesta = self.client.post(URL, {'tema': 'esmeralda', 'menu_lateral': 'claro', 'modo': 'dark'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(respuesta.json(), {
            'ok': True, 'mensaje': 'Listo: ahora usas el tema Esmeralda.', 'tema': 'esmeralda', 'color': '#047857', 'menu': 'claro',
        })
        self.assertEqual(PerfilUsuario.de(self.admin).tema, 'esmeralda')

    def test_un_tema_que_no_existe_no_se_guarda(self):
        respuesta = self.client.post(URL, {'tema': 'neon', 'menu_lateral': 'claro'})
        self.assertContains(respuesta, 'Elige uno de los temas de la lista.')
        respuesta = self.client.post(URL, {'tema': 'neon', 'menu_lateral': 'claro'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(respuesta.status_code, 400)
        self.assertFalse(respuesta.json()['ok'])
        self.assertEqual(PerfilUsuario.de(self.admin).tema, temas.PREDETERMINADO)

    def test_un_tema_guardado_que_ya_no_existe_cae_en_el_predeterminado(self):
        PerfilUsuario.objects.filter(pk=PerfilUsuario.de(self.admin).pk).update(tema='retirado')
        self.assertIn('data-tema="corporate"', self.client.get(reverse('inicio')).content.decode())

    def test_quien_ya_tiene_institucional_guardado_lo_conserva(self):
        PerfilUsuario.objects.filter(pk=PerfilUsuario.de(self.admin).pk).update(tema='institucional')
        self.assertIn('data-tema="institucional"', self.client.get(reverse('inicio')).content.decode())

    def test_cada_quien_ve_su_tema(self):
        PerfilUsuario.objects.update_or_create(usuario=self.sin_permisos, defaults={'tema': 'mandarina'})
        self.client.post(URL, {'tema': 'violeta', 'menu_lateral': 'claro'})
        self.assertIn('data-tema="violeta"', self.client.get(reverse('inicio')).content.decode())
        self.client.force_login(self.sin_permisos)
        self.assertIn('data-tema="mandarina"', self.client.get(reverse('inicio')).content.decode())


# ---------------------------------------------------------------------------
# Los colores de static/css/temas.css
# ---------------------------------------------------------------------------
def entradas_de_cada_tema():
    """{clave: {entrada: '#rrggbb'}} leído de temas.css."""
    css = TEMAS_CSS.read_text(encoding='utf-8')
    resultado = {}
    for clave, cuerpo in re.findall(r'^\[data-tema="([a-z]+)"\] \{(.*?)\}', css, flags=re.S | re.M):
        resultado[clave] = dict(re.findall(r'--t-([a-z0-9-]+):\s*(#[0-9a-f]{6});', cuerpo))
    return resultado


def rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def mezcla(color, porcentaje, otro):
    """color-mix(in srgb, color porcentaje%, otro)."""
    a, b = rgb(color), rgb(otro)
    return '#' + ''.join(f'{round(x * porcentaje / 100 + y * (100 - porcentaje) / 100):02x}' for x, y in zip(a, b))


def luminancia(color):
    def canal(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (canal(c) for c in rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(uno, otro):
    claro, oscuro = sorted((luminancia(uno), luminancia(otro)), reverse=True)
    return (claro + 0.05) / (oscuro + 0.05)


def variables(bloque):
    """Los nombres de las propiedades --color-* que define un bloque de CSS."""
    return set(re.findall(r'(--color-[a-z0-9-]+):', bloque))


def bloque(css, selector):
    """El cuerpo de la regla con ese selector exacto."""
    inicio = css.index(selector + ' {') + len(selector) + 2
    return css[inicio:css.index('\n}', inicio)]


class ColoresDeLosTemasTests(SimpleTestCase):
    """Los mismos cálculos que hace temas.css con color-mix(in srgb, …), con los pares de texto y fondo que se usan."""

    BLANCO = '#ffffff'
    TINTOS = [20, 24, 15, 20, 20, 22]   # % del tono en su fondo tenue (--color-tone-N-tint de app.css)

    def test_cada_tema_de_la_lista_tiene_sus_colores(self):
        entradas = entradas_de_cada_tema()
        self.assertEqual(set(entradas), set(temas.POR_CLAVE))
        for clave, valores in entradas.items():
            with self.subTest(tema=clave):
                self.assertEqual(set(valores) - set(OPCIONALES), set(ENTRADAS))
                self.assertEqual(temas.POR_CLAVE[clave]['color'], valores['primary'])   # la barra del navegador

    def test_cada_tema_tiene_su_letra_y_sus_esquinas(self):
        css = TEMAS_CSS.read_text(encoding='utf-8')
        for clave, cuerpo in re.findall(r'^\[data-tema="([a-z]+)"\] \{(.*?)\n\}', css, flags=re.S | re.M):
            with self.subTest(tema=clave):
                forma = dict(re.findall(r'--t-((?:font|radius)-[a-z]+):\s*([^;]+);', cuerpo))
                self.assertEqual(set(forma), set(FORMA))
                # Cada letra que nombra el CSS se carga de Google Fonts
                for familia in re.findall(r'"([^"]+)"', forma['font-sans'] + forma['font-display']):
                    if familia not in ('Segoe UI',):
                        self.assertIn('family=' + familia.replace(' ', '+'), temas.POR_CLAVE[clave]['fuentes'])

    def test_cada_tema_cambia_todos_los_colores_del_sistema(self):
        """Todo color de rol de app.css (claro y oscuro) lo redefine cada tema, salvo los que son blancos o neutros
        a propósito: así no queda nada (etiquetas, avisos, tarjetas, avatares…) con los colores institucionales."""
        app = (Path(settings.BASE_DIR) / 'static' / 'css' / 'app.css').read_text(encoding='utf-8')
        css = TEMAS_CSS.read_text(encoding='utf-8')
        paleta = re.compile(r'--color-(white|slate|teal|gold|crimson|ink)-?')
        claro_app = {v for v in variables(bloque(app, ':root')) if not paleta.match(v) and not v.endswith('-tint')}
        oscuro_app = variables(bloque(app, ':root[data-theme="dark"]'))
        claro = variables(bloque(css, ':root[data-tema]:not([data-tema="institucional"]):not([data-theme="dark"])'))
        oscuro = variables(bloque(css, ':root[data-theme="dark"][data-tema]:not([data-tema="institucional"])'))
        blancos = {'--color-surface', '--color-surface-glass', '--color-field-bg', '--color-logo-tile', '--color-tooltip-fg'}
        self.assertEqual(claro_app - claro, blancos)
        self.assertEqual(oscuro_app - oscuro, {'--color-hover-tint', '--color-overlay'})   # velos neutros

    def pares(self, t):
        """(qué, texto, fondo) de cada combinación que debe leerse bien (4.5:1)."""
        blanco, p, d = self.BLANCO, t['primary'], t['primary-dark']
        fondo, fondo_2 = t['fondo'], mezcla(p, 5, '#eef0f3')
        fondo_oscuro, superficie_oscura, superficie_oscura_2 = mezcla(p, 7, '#090c10'), mezcla(p, 9, '#0f1319'), mezcla(p, 11, '#151a22')
        enlace = t.get('primary-text', p)
        pares = [
            # Tema claro
            ('texto blanco en el botón', blanco, p),
            ('texto blanco en el botón al pasar el ratón', blanco, t['primary-hover']),
            ('enlace sobre blanco', enlace, blanco),
            ('elemento activo del menú', enlace, mezcla(p, 7, blanco)),
            ('texto del acento sobre su fondo', t['accent-text'], mezcla(t['accent'], 22, blanco)),
            ('cifra oscura sobre el acento', mezcla(p, 18, '#0c1015'), t['accent']),
            ('nombre del colegio', t['brand'], blanco),
            ('insignia', blanco, t['brand']),
            ('texto sobre el fondo', mezcla(p, 14, '#1a1f26'), fondo),
            ('texto suave', mezcla(p, 14, '#48505c'), blanco),
            ('texto apagado sobre el fondo', mezcla(p, 12, '#5d6672'), fondo),
            ('texto apagado sobre el gris', mezcla(p, 12, '#5d6672'), fondo_2),
            ('enlace sobre el fondo', enlace, fondo),
            ('globo de ayuda', blanco, mezcla(p, 22, '#0c1015')),
            ('botón de peligro', blanco, t['danger']),
            # Tema oscuro
            ('texto del botón (oscuro)', mezcla(p, 30, '#05070a'), d),
            ('acción como texto (oscuro)', d, superficie_oscura),
            ('texto del elemento activo (oscuro)', mezcla(d, 78, blanco), mezcla(d, 13, superficie_oscura)),
            ('marca (oscuro)', t['brand-dark'], superficie_oscura),
            ('texto del acento (oscuro)', mezcla(t['accent'], 70, blanco), mezcla(t['accent'], 16, superficie_oscura)),
            ('texto (oscuro)', mezcla(d, 10, '#e7e9ec'), fondo_oscuro),
            ('texto suave (oscuro)', mezcla(d, 12, '#c4c9d0'), superficie_oscura),
            ('texto apagado (oscuro)', mezcla(d, 12, '#9aa2ad'), superficie_oscura_2),
            ('globo de ayuda (oscuro)', fondo_oscuro, mezcla(d, 10, '#e7e9ec')),
            ('botón de peligro (oscuro)', superficie_oscura, mezcla(t['danger'], 50, blanco)),
        ]
        # Estados: etiquetas, avisos y asistencia
        for estado in ('success', 'warning', 'danger', 'info'):
            x = t[estado]
            pares += [
                (f'{estado} sobre blanco', x, blanco),
                (f'{estado} sobre el fondo', x, fondo),
                (f'etiqueta {estado}', x, mezcla(x, 8, blanco)),
                (f'etiqueta {estado} (oscuro)', mezcla(x, 50, blanco), mezcla(x, 18, superficie_oscura)),
                (f'etiqueta sólida {estado}', blanco, x),
                (f'etiqueta sólida {estado} (oscuro)', superficie_oscura, mezcla(x, 50, blanco)),
            ]
        # Tonos: tarjetas de grado, avatares, horario y roles
        for n, tinte in enumerate(self.TINTOS, 1):
            base = t[f'tone-{n}-base']
            pares += [
                (f'tono {n}', t[f'tone-{n}'], mezcla(base, tinte, blanco)),
                (f'tono {n} (oscuro)', mezcla(base, 55, blanco), mezcla(base, tinte, superficie_oscura)),
                (f'etiqueta sólida del tono {n}', blanco, t[f'tone-{n}']),
                (f'etiqueta sólida del tono {n} (oscuro)', superficie_oscura, mezcla(base, 55, blanco)),
            ]
        return pares

    def pares_del_menu_de_color(self, t):
        blanco = self.BLANCO
        sidebar_oscuro = mezcla(t['sidebar'], 76, '#000000')
        return [
            ('texto del menú de color', mezcla(blanco, 86, t['sidebar']), t['sidebar']),
            ('títulos del menú de color', mezcla(blanco, 72, t['sidebar']), t['sidebar']),
            ('nombre del colegio en el menú de color', t['accent'], t['sidebar']),
            ('títulos del menú de color (oscuro)', mezcla(blanco, 72, sidebar_oscuro), sidebar_oscuro),
            ('nombre del colegio en el menú de color (oscuro)', t['accent'], sidebar_oscuro),
        ]

    def test_contraste_aa_en_claro_oscuro_y_menu_de_color(self):
        for clave, t in entradas_de_cada_tema().items():
            # El institucional usa los colores afinados a mano de app.css; de temas.css solo toma el menú de color
            pares = self.pares_del_menu_de_color(t) + ([] if clave == 'institucional' else self.pares(t))
            for que, texto, fondo in pares:
                with self.subTest(tema=clave, par=que):
                    self.assertGreaterEqual(round(contraste(texto, fondo), 2), 4.5, f'{texto} sobre {fondo}')

    def test_la_opcion_bajo_el_raton_del_menu_corporate_se_lee(self):
        css = TEMAS_CSS.read_text(encoding='utf-8')
        fondo = re.search(r'\.nav__link:not\(\[aria-current="page"\]\):hover \{\s*background: (#[0-9a-f]{6});', css).group(1)
        texto = mezcla(entradas_de_cada_tema()['corporate']['primary'], 10, '#0c1015')   # --color-text-strong
        self.assertGreaterEqual(round(contraste(texto, fondo), 2), 4.5, f'{texto} sobre {fondo}')
