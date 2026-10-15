"""Contraseña consultable de las cuentas del sistema (pedido del 2026-10-15, como en estudiantes y tutores): la que asigna
o restablece quien administra la ve solo un administrador en el perfil de la cuenta; nunca la que elige la propia
persona (si la contraseña cambia por otro camino, la copia legible se borra sola)."""
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from CISAHUAYO.pruebas import crear_profesor, crear_usuario
from Usuarios.docentes import crear_cuenta
from Usuarios.models import PerfilUsuario
from Usuarios.tests import BaseUsuariosTestCase, datos_de_alta

Usuario = get_user_model()
CAMPO = 'id="contrasena-cuenta"'


def visible(usuario):
    return PerfilUsuario.objects.get(usuario=usuario).contrasena_visible


class ContrasenaConsultableTests(BaseUsuariosTestCase):
    def setUp(self):
        super().setUp()
        self.usuario = crear_usuario('lupita', self.docente, contrasena='VieJa-clave-77')
        self.detalle = reverse('usuarios:detalle', args=[self.usuario.pk])

    def restablecer(self, **datos):
        return self.client.post(reverse('usuarios:restablecer', args=[self.usuario.pk]), datos)

    def test_un_administrador_consulta_la_restablecida_en_el_perfil_cada_vez(self):
        self.restablecer(contrasena='Nueva-clave-2026x')
        self.assertEqual(visible(self.usuario), 'Nueva-clave-2026x')
        primera = self.client.get(self.detalle).content.decode()
        self.assertIn('id="credenciales-titulo"', primera)   # la tarjeta de credenciales, al terminar
        for html in (primera, self.client.get(self.detalle).content.decode()):
            self.assertIn(CAMPO, html)
            self.assertIn('value="Nueva-clave-2026x"', html)
            self.assertIn('data-reveal="#contrasena-cuenta"', html)
            self.assertIn('data-copy="#contrasena-cuenta"', html)
        self.assertNotIn('id="credenciales-titulo"', self.client.get(self.detalle).content.decode())   # una sola vez

    def test_la_generada_tambien_se_consulta(self):
        self.restablecer()
        generada = self.client.session['credenciales_usuario']['contrasena']
        self.assertEqual(visible(self.usuario), generada)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password(generada))

    def test_al_crear_la_cuenta_queda_consultable(self):
        self.client.post(reverse('usuarios:crear'), datos_de_alta(self.recepcion))
        usuario = Usuario.objects.get(username='maria.nunez')
        self.assertEqual(visible(usuario), self.client.session['credenciales_usuario']['contrasena'])
        html = self.client.get(reverse('usuarios:detalle', args=[usuario.pk])).content.decode()
        self.assertIn(f'value="{visible(usuario)}"', html)

    def test_la_cuenta_de_un_profesor_queda_consultable(self):
        cuenta, contrasena = crear_cuenta(crear_profesor(), username='marta.rangel', email='', rol=self.docente)
        self.assertEqual(visible(cuenta), contrasena)

    def test_quien_no_es_administrador_la_restablece_pero_no_la_consulta(self):
        self.entrar_como(self.gestor())
        objetivo = crear_usuario('beto', contrasena='VieJa-clave-77')   # sin rol: un gestor de cuentas lo administra
        detalle = reverse('usuarios:detalle', args=[objetivo.pk])
        respuesta = self.client.post(reverse('usuarios:restablecer', args=[objetivo.pk]), {'contrasena': 'Nueva-clave-2026x'})
        self.assertRedirects(respuesta, detalle, fetch_redirect_response=False)
        self.assertEqual(visible(objetivo), 'Nueva-clave-2026x')
        primera = self.client.get(detalle).content.decode()   # la tarjeta de credenciales, una vez
        self.assertIn('no se volverá a mostrar', primera)
        html = self.client.get(detalle).content.decode()
        self.assertNotIn('Nueva-clave-2026x', html)
        self.assertNotIn(CAMPO, html)
        self.assertIn('Vigente', html)
        self.assertIn('data-modal-open="modal-restablecer"', html)

    def test_si_la_cambia_la_propia_persona_ya_no_se_consulta(self):
        self.restablecer(contrasena='Nueva-clave-2026x')
        self.usuario.refresh_from_db()   # con su contraseña nueva (si no, la sesión no sería válida)
        persona = Client()
        persona.force_login(self.usuario)
        persona.post(reverse('cuenta:contrasena'), {
            'old_password': 'Nueva-clave-2026x', 'new_password1': 'Mi-clave-propia-99', 'new_password2': 'Mi-clave-propia-99',
        })
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password('Mi-clave-propia-99'))
        self.assertEqual(visible(self.usuario), '')
        html = self.client.get(self.detalle).content.decode()
        self.assertNotIn('Mi-clave-propia-99', html)
        self.assertIn('la eligió la propia persona', html)

    def test_un_cambio_por_otro_camino_la_borra(self):
        self.restablecer(contrasena='Nueva-clave-2026x')
        self.usuario.refresh_from_db()
        self.usuario.set_password('Otra-clave-distinta-5')   # p. ej. el admin de Django o manage.py changepassword
        self.usuario.save()
        self.assertEqual(visible(self.usuario), '')

    def test_si_solo_cambia_el_cifrado_se_conserva(self):
        """Django vuelve a cifrar la contraseña al entrar si cambió el algoritmo: sigue siendo la misma."""
        self.restablecer(contrasena='Nueva-clave-2026x')
        self.usuario.refresh_from_db()
        self.usuario.password = make_password('Nueva-clave-2026x')   # otro cifrado de la misma contraseña
        self.usuario.save(update_fields=['password'])
        self.assertEqual(visible(self.usuario), 'Nueva-clave-2026x')

    def test_entrar_o_editar_sus_datos_no_la_borra(self):
        self.restablecer(contrasena='Nueva-clave-2026x')
        self.assertTrue(Client().login(username='lupita', password='Nueva-clave-2026x'))   # guarda last_login
        self.usuario.refresh_from_db()
        self.usuario.first_name = 'Guadalupe'
        self.usuario.save()
        self.assertEqual(visible(self.usuario), 'Nueva-clave-2026x')

    def test_una_anterior_a_esta_funcion_explica_por_que_no_se_ve(self):
        html = self.client.get(self.detalle).content.decode()
        self.assertNotIn(CAMPO, html)
        self.assertIn('Restablécela para asignar una que puedas consultar', html)
        self.assertIn('data-modal-open="modal-restablecer"', html)

    def test_nunca_se_ofrece_en_el_admin_de_django(self):
        self.assertFalse(PerfilUsuario._meta.get_field('contrasena_visible').editable)
