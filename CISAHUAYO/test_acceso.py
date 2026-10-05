"""Pantallas de acceso: el inicio y el cierre de sesión del admin de Django con el diseño del sistema.

La ruta (/admin/login/) y las reglas (solo entra personal de staff con cuenta activa) son las del admin; aquí solo se
comprueba que la plantilla propia muestre bien el formulario, conserve lo escrito, explique los errores y lleve a donde
estaba el usuario.
"""
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse

from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase

RAIZ = Path(settings.BASE_DIR)


@PRUEBAS
class InicioDeSesionTests(BaseTestCase):
    def setUp(self):
        self.client.logout()

    def test_usa_la_plantilla_del_sistema_y_no_la_del_admin(self):
        respuesta = self.client.get(reverse('admin:login'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertTemplateUsed(respuesta, 'acceso_base.html')
        self.assertContains(respuesta, 'Iniciar sesión')
        self.assertContains(respuesta, 'css/acceso.css')
        self.assertContains(respuesta, 'js/acceso.js')
        self.assertNotContains(respuesta, 'admin/css/base.css')

    def test_el_formulario_manda_lo_que_el_admin_espera(self):
        html = self.client.get(reverse('admin:login'), {'next': '/alumnos/'}).content.decode()
        self.assertIn('name="username"', html)
        self.assertIn('name="password"', html)
        self.assertIn('name="csrfmiddlewaretoken"', html)
        self.assertIn('<input type="hidden" name="next" value="/alumnos/">', html)
        self.assertIn('method="post"', html)
        self.assertIn('autocomplete="current-password"', html)

    def test_las_credenciales_correctas_llevan_a_donde_iba(self):
        respuesta = self.client.post(reverse('admin:login'), {'username': 'admin', 'password': 'x', 'next': '/alumnos/'})
        self.assertRedirects(respuesta, '/alumnos/', fetch_redirect_response=False)

    def test_los_datos_incorrectos_explican_el_problema_y_conservan_el_usuario(self):
        respuesta = self.client.post(reverse('admin:login'), {'username': 'admin', 'password': 'mal', 'next': '/alumnos/'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'no son correctos')
        self.assertContains(respuesta, 'value="admin"')
        self.assertNotContains(respuesta, 'value="mal"')
        self.assertContains(respuesta, '<input type="hidden" name="next" value="/alumnos/">', html=False)

    def test_un_usuario_sin_acceso_de_staff_no_entra(self):
        respuesta = self.client.post(reverse('admin:login'), {'username': 'visitante', 'password': 'x'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'no son correctos')

    def test_una_cuenta_inactiva_no_entra(self):
        get_user_model().objects.filter(username='admin').update(is_active=False)
        respuesta = self.client.post(reverse('admin:login'), {'username': 'admin', 'password': 'x'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertNotContains(respuesta, 'Cerraste tu sesión')

    def test_campos_vacios_marcan_cada_campo(self):
        respuesta = self.client.post(reverse('admin:login'), {'username': '', 'password': ''})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'field__error', count=2)
        self.assertContains(respuesta, 'is-invalid')

    def test_quien_ya_inicio_sesion_sin_permiso_lo_ve_explicado(self):
        self.client.force_login(self.sin_permisos)
        respuesta = self.client.get(reverse('admin:login'))
        self.assertContains(respuesta, 'visitante')
        self.assertContains(respuesta, 'no tiene permiso para entrar al sistema')

    def test_quien_ya_tiene_acceso_pasa_de_largo(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('admin:login'), {'next': '/alumnos/'})
        self.assertEqual(respuesta.status_code, 302)

    def test_la_ruta_sigue_siendo_la_del_admin(self):
        self.assertEqual(reverse('admin:login'), '/admin/login/')

    def test_sin_destino_pedido_se_entra_al_sistema_y_no_al_panel_de_django(self):
        """Antes llevaba a /admin/ (el panel de Django); ahora al inicio del sistema."""
        pagina = self.client.get(reverse('admin:login'))
        self.assertContains(pagina, '<input type="hidden" name="next" value="/">', html=False)
        respuesta = self.client.post(reverse('admin:login'), {'username': 'admin', 'password': 'x', 'next': '/'})
        self.assertRedirects(respuesta, reverse('inicio'), fetch_redirect_response=False)

    def test_un_envio_sin_campo_next_tambien_llega_al_sistema(self):
        respuesta = self.client.post(reverse('admin:login'), {'username': 'admin', 'password': 'x'})
        self.assertRedirects(respuesta, reverse('inicio'), fetch_redirect_response=False)

    def test_quien_ya_tiene_sesion_y_abre_el_acceso_pasa_al_sistema(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('admin:login'))
        self.assertRedirects(respuesta, reverse('inicio'), fetch_redirect_response=False)

    def test_si_se_pidio_el_panel_de_django_se_respeta(self):
        pagina = self.client.get(reverse('admin:login'), {'next': '/admin/'})
        self.assertContains(pagina, '<input type="hidden" name="next" value="/admin/">', html=False)
        respuesta = self.client.post(reverse('admin:login'), {'username': 'admin', 'password': 'x', 'next': '/admin/'})
        self.assertRedirects(respuesta, '/admin/', fetch_redirect_response=False)
        self.client.logout()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('admin:login'), {'next': '/admin/'}).status_code, 302)

    def test_sin_restablecer_contrasena_no_se_ofrece_el_enlace(self):
        self.assertNotContains(self.client.get(reverse('admin:login')), 'Olvidaste')

    def test_las_vistas_protegidas_siguen_mandando_a_esta_pantalla(self):
        respuesta = self.client.get(reverse('alumnos:lista'))
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn('/admin/login/', respuesta['Location'])


@PRUEBAS
class CierreDeSesionTests(BaseTestCase):
    def test_muestra_la_pantalla_de_cierre_con_el_diseno_del_sistema(self):
        respuesta = self.client.post(reverse('admin:logout'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertTemplateUsed(respuesta, 'acceso_base.html')
        self.assertContains(respuesta, 'Cerraste tu sesión')
        self.assertContains(respuesta, f'href="{reverse("admin:login")}"')
        # La sesión terminó de verdad
        self.assertEqual(self.client.get(reverse('alumnos:lista')).status_code, 302)


class RecursosDeAccesoTests(BaseTestCase):
    def test_estan_los_archivos_y_el_icono_que_usa_la_pantalla(self):
        for ruta in ('static/css/acceso.css', 'static/js/acceso.js', 'static/img/logointer.svg'):
            self.assertTrue((RAIZ / ruta).is_file(), ruta)
        self.assertIn('id="eye-off"', (RAIZ / 'static/img/icons.svg').read_text(encoding='utf-8'))
