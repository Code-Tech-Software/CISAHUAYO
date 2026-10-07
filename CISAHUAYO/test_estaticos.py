"""Los CSS y JS cambian a menudo: en desarrollo el navegador debe revalidarlos y no quedarse con una copia vieja
(un campo con los estilos de antes y el HTML nuevo se ve roto)."""
from django.conf import settings
from django.test import SimpleTestCase


class EstaticosEnDesarrolloTests(SimpleTestCase):
    def test_runserver_sirve_los_estaticos_con_whitenoise_y_no_con_staticfiles(self):
        """`whitenoise.runserver_nostatic` debe ir ANTES de `django.contrib.staticfiles`: así `runserver` entrega los
        archivos con «Cache-Control: max-age=0» y ETag. Después de él, Django los sirve sin cabeceras de caché y el
        navegador reutiliza copias viejas por horas."""
        apps = settings.INSTALLED_APPS
        self.assertIn('whitenoise.runserver_nostatic', apps)
        self.assertLess(apps.index('whitenoise.runserver_nostatic'), apps.index('django.contrib.staticfiles'))

    def test_whitenoise_esta_en_el_middleware(self):
        self.assertIn('whitenoise.middleware.WhiteNoiseMiddleware', settings.MIDDLEWARE)
