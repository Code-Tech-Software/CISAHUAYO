"""Los archivos estáticos nunca deben llegar viejos al navegador (pasó con el menú lateral y el sprite de iconos)."""
import re

from django.conf import settings
from django.templatetags.static import static
from django.test import SimpleTestCase, override_settings

from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase


class ServidoDeEstaticosTests(SimpleTestCase):
    def test_whitenoise_va_antes_que_staticfiles(self):
        # Si no, en desarrollo los sirve el servidor de Django sin Cache-Control y el navegador se queda con copias viejas
        apps = settings.INSTALLED_APPS
        self.assertLess(apps.index('whitenoise.runserver_nostatic'), apps.index('django.contrib.staticfiles'))

    def test_el_almacenamiento_es_el_versionado(self):
        self.assertEqual(settings.STORAGES['staticfiles']['BACKEND'], 'CISAHUAYO.almacenamiento.EstaticosConVersion')

    @override_settings(DEBUG=True)
    def test_en_desarrollo_cada_url_lleva_la_fecha_del_archivo(self):
        for nombre in ('js/app.js', 'css/app.css', 'img/icons.svg'):
            with self.subTest(nombre=nombre):
                self.assertRegex(static(nombre), rf'^/static/{re.escape(nombre)}\?v=\d+$')

    @override_settings(DEBUG=True)
    def test_un_archivo_que_no_existe_no_rompe_la_url(self):
        self.assertEqual(static('no/existe.js'), '/static/no/existe.js')


@PRUEBAS
class ElMenuSeDespliegaSinJavaScriptTests(BaseTestCase):
    def test_los_grupos_son_details_nativos(self):
        html = self.client.get('/').content.decode()
        self.assertIn('<details class="nav__details"', html)
        self.assertIn('<summary class="nav__link nav__toggle" data-nav-toggle', html)
        self.assertNotRegex(html, r'class="nav__sub"[^>]*hidden')   # la lista no se esconde con hidden: la abre <details>

    def test_el_grupo_de_la_pagina_llega_abierto(self):
        html = self.client.get('/usuarios/').content.decode()
        self.assertRegex(html, r'data-nav-group="configuracion">\s*<details class="nav__details" open>')
        self.assertRegex(html, r'data-nav-group="control">\s*<details class="nav__details">')

    def test_el_icono_de_configuracion_existe_en_el_sprite(self):
        sprite = (settings.BASE_DIR / 'static' / 'img' / 'icons.svg').read_text(encoding='utf-8')
        html = self.client.get('/').content.decode()
        for nombre in set(re.findall(r'icons\.svg[^"#]*#([a-z0-9-]+)"', html)):
            with self.subTest(icono=nombre):
                self.assertIn(f'<symbol id="{nombre}"', sprite)
