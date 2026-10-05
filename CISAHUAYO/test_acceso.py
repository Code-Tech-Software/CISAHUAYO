"""Pantallas de acceso: el inicio y el cierre de sesión del sistema, con el diseño del sistema.

La ruta del inicio sigue siendo /admin/login/ (los demás módulos la usan como LOGIN_URL), pero ya no exige ser personal
«staff»: entra cualquier cuenta activa y lo que puede hacer lo define su rol. Aquí se comprueba que la pantalla muestre
bien el formulario, conserve lo escrito, explique los errores y lleve a donde estaba la persona o, si no venía de
ninguna página, al inicio del sistema (no al panel de administración de Django).
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
        self.assertTemplateUsed(respuesta, 'registration/login.html')
        self.assertTemplateUsed(respuesta, 'acceso_base.html')
        self.assertContains(respuesta, 'Iniciar sesión')
        self.assertContains(respuesta, 'css/acceso.css')
        self.assertContains(respuesta, 'js/acceso.js')
        self.assertNotContains(respuesta, 'admin/css/base.css')

    def test_la_ruta_sigue_siendo_la_del_admin(self):
        self.assertEqual(reverse('admin:login'), '/admin/login/')
        self.assertEqual(reverse('login'), '/admin/login/')

    def test_el_formulario_manda_lo_que_se_espera(self):
        html = self.client.get(reverse('admin:login'), {'next': '/alumnos/'}).content.decode()
        self.assertIn('name="username"', html)
        self.assertIn('name="password"', html)
        self.assertIn('name="csrfmiddlewaretoken"', html)
        self.assertIn('<input type="hidden" name="next" value="/alumnos/">', html)
        self.assertIn('method="post"', html)
        self.assertIn('autocomplete="current-password"', html)

    # --- quién entra y a dónde ----------------------------------------------------------
    def test_las_credenciales_correctas_llevan_a_donde_iba(self):
        respuesta = self.client.post(reverse('admin:login'), {'username': 'admin', 'password': 'x', 'next': '/alumnos/'})
        self.assertRedirects(respuesta, '/alumnos/', fetch_redirect_response=False)

    def test_sin_destino_pedido_se_entra_al_sistema_y_no_al_panel_de_django(self):
        """Antes llevaba a /admin/ (el panel de Django); ahora al inicio del sistema."""
        respuesta = self.client.post(reverse('admin:login'), {'username': 'admin', 'password': 'x'})
        self.assertRedirects(respuesta, reverse('inicio'), fetch_redirect_response=False)
        self.client.logout()
        respuesta = self.client.post(reverse('admin:login'), {'username': 'admin', 'password': 'x', 'next': ''})
        self.assertRedirects(respuesta, reverse('inicio'), fetch_redirect_response=False)

    def test_una_cuenta_que_no_es_de_staff_tambien_entra(self):
        """Las cuentas del sistema no son de staff: su acceso lo define el rol."""
        self.assertFalse(self.sin_permisos.is_staff)
        respuesta = self.client.post(reverse('admin:login'), {'username': 'visitante', 'password': 'x'})
        self.assertRedirects(respuesta, reverse('inicio'), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('inicio')).status_code, 200)

    def test_los_datos_incorrectos_explican_el_problema_y_conservan_el_usuario(self):
        respuesta = self.client.post(reverse('admin:login'), {'username': 'admin', 'password': 'mal', 'next': '/alumnos/'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'no son correctos')
        self.assertContains(respuesta, 'value="admin"')
        self.assertNotContains(respuesta, 'value="mal"')
        self.assertContains(respuesta, '<input type="hidden" name="next" value="/alumnos/">', html=False)

    def test_una_cuenta_desactivada_no_entra(self):
        get_user_model().objects.filter(username='visitante').update(is_active=False)
        respuesta = self.client.post(reverse('admin:login'), {'username': 'visitante', 'password': 'x'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'desactivada')
        self.assertEqual(self.client.get(reverse('alumnos:lista')).status_code, 302)

    def test_campos_vacios_marcan_cada_campo(self):
        respuesta = self.client.post(reverse('admin:login'), {'username': '', 'password': ''})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'field__error', count=2)
        self.assertContains(respuesta, 'is-invalid')

    def test_no_se_sigue_un_destino_de_otro_sitio(self):
        respuesta = self.client.post(reverse('admin:login'), {'username': 'admin', 'password': 'x', 'next': 'https://ejemplo.com/'})
        self.assertRedirects(respuesta, reverse('inicio'), fetch_redirect_response=False)

    # --- quien ya tiene sesión -----------------------------------------------------------
    def test_quien_ya_tiene_sesion_y_abre_el_acceso_pasa_al_sistema(self):
        self.client.force_login(self.sin_permisos)
        respuesta = self.client.get(reverse('admin:login'))
        self.assertRedirects(respuesta, reverse('inicio'), fetch_redirect_response=False)

    def test_quien_ya_tiene_sesion_pasa_a_la_pagina_que_pidio(self):
        self.client.force_login(self.sin_permisos)
        respuesta = self.client.get(reverse('admin:login'), {'next': '/alumnos/'})
        self.assertRedirects(respuesta, '/alumnos/', fetch_redirect_response=False)

    def test_quien_no_es_de_staff_y_pide_el_panel_de_django_lo_ve_explicado_sin_dar_vueltas(self):
        """El admin manda aquí a quien no es de staff: dejarlo pasar a /admin/ daría redirecciones sin fin."""
        self.client.force_login(self.sin_permisos)
        respuesta = self.client.get(reverse('admin:login'), {'next': '/admin/'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'visitante')
        self.assertContains(respuesta, 'no puede entrar a la administración de Django')
        self.assertEqual(self.client.get('/admin/', follow=False).status_code, 302)

    def test_si_se_pidio_el_panel_de_django_se_respeta_para_el_personal(self):
        pagina = self.client.get(reverse('admin:login'), {'next': '/admin/'})
        self.assertContains(pagina, '<input type="hidden" name="next" value="/admin/">', html=False)
        respuesta = self.client.post(reverse('admin:login'), {'username': 'admin', 'password': 'x', 'next': '/admin/'})
        self.assertRedirects(respuesta, '/admin/', fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('admin:login'), {'next': '/admin/'}).status_code, 302)

    def test_las_vistas_protegidas_siguen_mandando_a_esta_pantalla(self):
        respuesta = self.client.get(reverse('alumnos:lista'))
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn('/admin/login/', respuesta['Location'])

    def test_el_panel_de_control_exige_sesion(self):
        respuesta = self.client.get(reverse('inicio'))
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn('/admin/login/?next=/', respuesta['Location'])


@PRUEBAS
class CierreDeSesionTests(BaseTestCase):
    def test_muestra_la_pantalla_de_cierre_con_el_diseno_del_sistema(self):
        respuesta = self.client.post(reverse('logout'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertTemplateUsed(respuesta, 'acceso_base.html')
        self.assertContains(respuesta, 'Cerraste tu sesión')
        self.assertContains(respuesta, f'href="{reverse("admin:login")}"')
        # La sesión terminó de verdad
        self.assertEqual(self.client.get(reverse('alumnos:lista')).status_code, 302)

    def test_una_cuenta_que_no_es_de_staff_tambien_puede_cerrar_sesion(self):
        """El cierre del admin dejaría a esta cuenta con la sesión abierta (la manda al login): por eso hay /salir/."""
        self.client.force_login(self.sin_permisos)
        respuesta = self.client.post(reverse('logout'))
        self.assertContains(respuesta, 'Cerraste tu sesión')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_el_menu_de_usuario_cierra_sesion_por_la_ruta_del_sistema(self):
        html = self.client.get(reverse('inicio')).content.decode()
        self.assertIn(f'action="{reverse("logout")}"', html)

    def test_salir_solo_acepta_post(self):
        self.assertEqual(self.client.get(reverse('logout')).status_code, 405)


class RecursosDeAccesoTests(BaseTestCase):
    def test_estan_los_archivos_y_el_icono_que_usa_la_pantalla(self):
        for ruta in ('static/css/acceso.css', 'static/js/acceso.js', 'static/img/logointer.svg'):
            self.assertTrue((RAIZ / ruta).is_file(), ruta)
        self.assertIn('id="eye-off"', (RAIZ / 'static/img/icons.svg').read_text(encoding='utf-8'))
