"""Páginas de error con el diseño del sistema: 404, 403, token de seguridad vencido y error del servidor."""
import re
from pathlib import Path

from django.conf import settings
from django.test import Client, RequestFactory
from django.urls import reverse
from django.views.defaults import server_error

from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase

RAIZ = Path(settings.BASE_DIR)


@PRUEBAS
class PaginasDeErrorTests(BaseTestCase):
    def test_pagina_inexistente_con_sesion_conserva_el_menu(self):
        respuesta = self.client.get('/esto-no-existe/')
        self.assertEqual(respuesta.status_code, 404)
        self.assertTemplateUsed(respuesta, '404.html')
        self.assertContains(respuesta, 'No encontramos esa página', status_code=404)
        self.assertContains(respuesta, 'class="sidebar', status_code=404)
        self.assertContains(respuesta, f'href="{reverse("inicio")}"', status_code=404)

    def test_pagina_inexistente_sin_sesion_tambien_se_ve_bien(self):
        self.client.logout()
        respuesta = self.client.get('/esto-no-existe/')
        self.assertEqual(respuesta.status_code, 404)
        self.assertContains(respuesta, 'No encontramos esa página', status_code=404)

    def test_registro_que_no_existe_muestra_la_misma_pagina(self):
        respuesta = self.client.get(reverse('tutores:detalle', args=[99999]))
        self.assertEqual(respuesta.status_code, 404)
        self.assertTemplateUsed(respuesta, '404.html')

    def test_sin_permiso_explica_que_hacer(self):
        self.client.force_login(self.sin_permisos)
        respuesta = self.client.get(reverse('alumnos:lista'))
        self.assertEqual(respuesta.status_code, 403)
        self.assertTemplateUsed(respuesta, '403.html')
        self.assertContains(respuesta, 'No tienes permiso para esto', status_code=403)
        self.assertContains(respuesta, 'revise tus permisos', status_code=403)

    def test_token_vencido_no_muestra_el_motivo_tecnico(self):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.admin)
        respuesta = cliente.post(reverse('tutores:crear'), {'nombre': 'x'})
        self.assertEqual(respuesta.status_code, 403)
        self.assertTemplateUsed(respuesta, '403_csrf.html')
        self.assertContains(respuesta, 'Esta página caducó', status_code=403)
        self.assertNotContains(respuesta, 'CSRF', status_code=403)

    def test_error_del_servidor_es_una_pagina_autonoma(self):
        respuesta = server_error(RequestFactory().get('/'))
        self.assertEqual(respuesta.status_code, 500)
        html = respuesta.content.decode()
        self.assertIn('Algo salió mal', html)
        self.assertIn('href="/"', html)
        # No depende de archivos estáticos ni de hojas externas: se muestra justo cuando algo falla
        self.assertNotIn('<link', html)
        self.assertNotIn('<script', html)
        self.assertNotIn('/static/', html)

    def test_la_plantilla_500_no_usa_etiquetas_ni_variables(self):
        """Sin {% static %}, {% url %}, {% include %}... : ninguna puede fallar cuando ya hay un error."""
        fuente = (RAIZ / 'templates/500.html').read_text(encoding='utf-8')
        sin_comentario = re.sub(r'\{% comment %\}.*?\{% endcomment %\}', '', fuente, flags=re.S)
        self.assertNotIn('{%', sin_comentario)
        self.assertNotIn('{{', sin_comentario)
