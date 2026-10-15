"""Inicio de sesión con tres accesos (sistema, estudiantes y tutores) y las restricciones de los portales."""
from datetime import timedelta
from unittest.mock import patch

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from CISAHUAYO import portales
from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase, crear_alumno, crear_tutor

LOGIN = reverse('login')
PORTAL_ESTUDIANTES = reverse('portal_estudiantes:inicio')
PORTAL_TUTORES = reverse('portal_tutores:inicio')


class BasePortalesTestCase(BaseTestCase):
    def setUp(self):
        self.client = Client()   # sin sesión: cada prueba entra con la cuenta que necesita
        self.alumno = crear_alumno(nombre='Zoe', correo_electronico='zoe@colegio.mx')
        self.alumno.establecer_contrasena('sol123')
        self.alumno.save()
        self.tutor = crear_tutor(nombre='Rosa', usuario='rosa.mora')
        self.tutor.establecer_contrasena('luna456')
        self.tutor.save()

    def entrar_estudiante(self, correo='zoe@colegio.mx', contrasena='sol123', **extra):
        return self.client.post(LOGIN, {'acceso': 'estudiantes', 'estudiantes-correo': correo, 'estudiantes-contrasena': contrasena, **extra})

    def entrar_tutor(self, usuario='rosa.mora', contrasena='luna456', **extra):
        return self.client.post(LOGIN, {'acceso': 'tutores', 'tutores-usuario': usuario, 'tutores-contrasena': contrasena, **extra})

    def errores(self, respuesta, pestana):
        return respuesta.context[f'form_{pestana}'].non_field_errors()


@PRUEBAS
class PantallaDeAccesoTests(BasePortalesTestCase):
    def test_ofrece_los_tres_accesos_y_elige_la_pestana_pedida(self):
        respuesta = self.client.get(LOGIN)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context['acceso'], 'sistema')
        for pestana in ('sistema', 'estudiantes', 'tutores'):
            self.assertContains(respuesta, f'id="tab-{pestana}"')
            self.assertContains(respuesta, f'id="panel-{pestana}"')
        self.assertContains(respuesta, 'data-tema="corporate"')
        self.assertContains(respuesta, 'data-password-toggle', count=3)
        self.assertNotContains(respuesta, 'data-access-explicit')   # sin pestaña pedida: acceso.js recuerda la última

        respuesta = self.client.get(LOGIN, {'acceso': 'tutores'})
        self.assertEqual(respuesta.context['acceso'], 'tutores')
        self.assertContains(respuesta, 'data-access-explicit')
        self.assertContains(respuesta, 'id="panel-tutores" aria-labelledby="tab-tutores" data-access-panel="tutores">')
        self.assertContains(respuesta, 'id="panel-sistema" aria-labelledby="tab-sistema" data-access-panel="sistema" hidden>')
        # una pestaña que no existe es la del sistema
        self.assertEqual(self.client.get(LOGIN, {'acceso': 'otra'}).context['acceso'], 'sistema')

    def test_el_inicio_de_sesion_del_sistema_sigue_igual(self):
        respuesta = self.client.post(LOGIN, {'username': 'admin', 'password': 'x'})   # como los formularios de antes
        self.assertRedirects(respuesta, reverse('inicio'), fetch_redirect_response=False)
        self.client.logout()
        respuesta = self.client.post(LOGIN, {'acceso': 'sistema', 'username': 'admin', 'password': 'mala'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'El usuario o la contraseña no son correctos')
        # con una cuenta del sistema, el correo del estudiante no sirve, y al revés
        self.assertEqual(self.client.post(LOGIN, {'username': 'zoe@colegio.mx', 'password': 'sol123'}).status_code, 200)
        self.assertEqual(self.entrar_estudiante('admin', 'x').status_code, 200)

    def test_el_estudiante_entra_con_su_correo_a_su_portal(self):
        respuesta = self.entrar_estudiante('  ZOE@Colegio.mx ')
        self.assertRedirects(respuesta, PORTAL_ESTUDIANTES, fetch_redirect_response=False)
        self.assertEqual(self.client.session[portales.CLAVE_DE_SESION]['tipo'], portales.ESTUDIANTE)
        self.alumno.refresh_from_db()
        self.assertIsNotNone(self.alumno.ultimo_acceso)
        inicio = self.client.get(PORTAL_ESTUDIANTES)
        self.assertEqual(inicio.status_code, 200)
        self.assertIn('no-store', inicio['Cache-Control'])   # sin caché: «atrás» tras salir no muestra sus datos
        self.assertContains(inicio, 'Portal de estudiantes')
        self.assertContains(inicio, 'Zoe')
        # no es una cuenta del sistema
        self.assertFalse(inicio.wsgi_request.user.is_authenticated)

    def test_el_tutor_entra_con_su_usuario_a_su_portal(self):
        respuesta = self.entrar_tutor('ROSA.MORA')
        self.assertRedirects(respuesta, PORTAL_TUTORES, fetch_redirect_response=False)
        self.assertContains(self.client.get(PORTAL_TUTORES), 'Portal de tutores')
        self.tutor.refresh_from_db()
        self.assertIsNotNone(self.tutor.ultimo_acceso)

    def test_credenciales_incorrectas_con_un_mensaje_que_no_revela_si_la_cuenta_existe(self):
        mala = self.entrar_estudiante(contrasena='otra')
        inexistente = self.entrar_estudiante('nadie@colegio.mx')
        self.assertEqual(self.errores(mala, 'estudiantes'), self.errores(inexistente, 'estudiantes'))
        self.assertIn('El correo o la contraseña no son correctos', self.errores(mala, 'estudiantes')[0])
        self.assertEqual(mala.context['acceso'], 'estudiantes')   # vuelve a la pestaña con la que intentó
        self.assertIn('El usuario o la contraseña no son correctos', self.errores(self.entrar_tutor(contrasena='otra'), 'tutores')[0])
        self.assertNotIn(portales.CLAVE_DE_SESION, self.client.session)
        # campos obligatorios y correo con formato
        vacio = self.client.post(LOGIN, {'acceso': 'estudiantes', 'estudiantes-correo': 'zoe', 'estudiantes-contrasena': ''})
        self.assertTrue(vacio.context['form_estudiantes'].errors['correo'])
        self.assertTrue(vacio.context['form_estudiantes'].errors['contrasena'])
        # el formulario del sistema no se marca con errores por el de un portal
        self.assertFalse(mala.context['form'].is_bound)

    def test_tras_varios_intentos_fallidos_la_cuenta_se_bloquea_un_rato(self):
        for intento in range(1, portales.MAXIMO_DE_INTENTOS):
            respuesta = self.entrar_estudiante(contrasena='otra')
            self.alumno.refresh_from_db()
            self.assertEqual(self.alumno.intentos_fallidos, intento)
        self.assertIn('Te queda 1 intento', self.errores(respuesta, 'estudiantes')[0])
        respuesta = self.entrar_estudiante(contrasena='otra')
        self.assertIn('queda bloqueada 15 minutos', self.errores(respuesta, 'estudiantes')[0])
        self.alumno.refresh_from_db()
        self.assertTrue(portales.bloqueada(self.alumno))
        # bloqueada, ni la contraseña correcta entra
        respuesta = self.entrar_estudiante()
        self.assertIn('se bloqueó tras varios intentos fallidos', self.errores(respuesta, 'estudiantes')[0])
        # pasado el bloqueo, entra y el contador vuelve a cero
        despues = timezone.now() + timedelta(minutes=portales.MINUTOS_DE_BLOQUEO + 1)
        with patch('django.utils.timezone.now', return_value=despues):
            self.assertRedirects(self.entrar_estudiante(), PORTAL_ESTUDIANTES, fetch_redirect_response=False)
        self.alumno.refresh_from_db()
        self.assertEqual((self.alumno.intentos_fallidos, self.alumno.bloqueado_hasta), (0, None))

    def test_un_acceso_correcto_reinicia_los_intentos_fallidos(self):
        self.entrar_tutor(contrasena='otra')
        self.entrar_tutor(contrasena='otra')
        self.entrar_tutor()
        self.tutor.refresh_from_db()
        self.assertEqual(self.tutor.intentos_fallidos, 0)

    def test_solo_entran_las_cuentas_activas_y_con_acceso(self):
        casos = [
            (self.alumno, {'estatus': 'BAJA'}, self.entrar_estudiante, 'estudiantes', 'dado de baja'),
            (self.alumno, {'estatus': 'SUSPENDIDO'}, self.entrar_estudiante, 'estudiantes', 'suspendido'),
            (self.alumno, {'estatus': 'ACTIVO', 'acceso_portal': False}, self.entrar_estudiante, 'estudiantes', 'acceso al portal está desactivado'),
            (self.tutor, {'estatus': 'INACTIVO'}, self.entrar_tutor, 'tutores', 'tutor está inactivo'),
            (self.tutor, {'estatus': 'ACTIVO', 'acceso_portal': False}, self.entrar_tutor, 'tutores', 'acceso al portal está desactivado'),
        ]
        for cuenta, cambios, entrar, pestana, texto in casos:
            with self.subTest(cambios=cambios, cuenta=cuenta):
                type(cuenta).objects.filter(pk=cuenta.pk).update(**cambios)
                respuesta = entrar()
                self.assertEqual(respuesta.status_code, 200)
                self.assertIn(texto, self.errores(respuesta, pestana)[0])
                # sin la contraseña correcta no se dice nada del estado de la cuenta
                self.assertIn('no son correctos', self.errores(entrar(contrasena='otra'), pestana)[0])
                self.assertNotIn(portales.CLAVE_DE_SESION, self.client.session)

    def test_sin_contrasena_asignada_no_se_entra(self):
        type(self.tutor).objects.filter(pk=self.tutor.pk).update(contrasena='')
        self.assertIn('no son correctos', self.errores(self.entrar_tutor(), 'tutores')[0])
        self.assertTrue(self.entrar_tutor(contrasena='').context['form_tutores'].errors['contrasena'])   # obligatoria

    def test_vuelve_a_la_pagina_del_portal_que_se_pidio(self):
        pedida = reverse('portal_tutores:estudiante', args=[self.alumno.pk])
        respuesta = self.client.get(pedida)
        self.assertEqual(respuesta['Location'], portales.url_de_acceso(portales.TUTOR, pedida))
        pantalla = self.client.get(respuesta['Location'])
        self.assertEqual(pantalla.context['acceso'], 'tutores')
        self.assertRedirects(self.entrar_tutor(next=pedida), pedida, fetch_redirect_response=False)
        # una página de otro portal o del sistema no: va al inicio de su portal
        self.client.post(reverse('portal_tutores:salir'))
        self.assertRedirects(self.entrar_estudiante(next=pedida), PORTAL_ESTUDIANTES, fetch_redirect_response=False)
        # y una de fuera del sitio, tampoco
        self.client.post(reverse('portal_estudiantes:salir'))
        self.assertRedirects(self.entrar_estudiante(next='https://otro.example.com/'), PORTAL_ESTUDIANTES, fetch_redirect_response=False)


@PRUEBAS
class RestriccionesDeAccesoTests(BasePortalesTestCase):
    def test_sin_sesion_los_portales_mandan_a_su_pestana(self):
        self.assertEqual(self.client.get(PORTAL_ESTUDIANTES)['Location'], f'{LOGIN}?acceso=estudiantes&next=%2Fportal%2Festudiantes%2F')
        self.assertIn('acceso=tutores', self.client.get(PORTAL_TUTORES)['Location'])

    def test_cada_cuenta_entra_solo_a_su_portal(self):
        self.entrar_estudiante()
        respuesta = self.client.get(PORTAL_TUTORES)
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn('acceso=tutores', respuesta['Location'])
        # su sesión sigue abierta: puede volver a su portal
        self.assertEqual(self.client.get(PORTAL_ESTUDIANTES).status_code, 200)
        # y no es una sesión del sistema: las páginas del sistema piden iniciar sesión
        sistema = self.client.get(reverse('alumnos:lista'))
        self.assertEqual(sistema.status_code, 302)
        self.assertIn(LOGIN, sistema['Location'])
        self.assertEqual(self.client.get(reverse('inicio')).status_code, 302)

    def test_una_cuenta_del_sistema_no_entra_a_los_portales(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(PORTAL_ESTUDIANTES).status_code, 403)
        self.assertEqual(self.client.get(PORTAL_TUTORES).status_code, 403)

    def test_la_sesion_termina_al_desactivar_el_acceso_dar_de_baja_o_cambiar_la_contrasena(self):
        cambios = [
            lambda: type(self.alumno).objects.filter(pk=self.alumno.pk).update(acceso_portal=False),
            lambda: type(self.alumno).objects.filter(pk=self.alumno.pk).update(estatus='BAJA'),
            lambda: (self.alumno.establecer_contrasena('nueva789'), self.alumno.save()),
        ]
        for cambio in cambios:
            with self.subTest(cambio=cambio):
                type(self.alumno).objects.filter(pk=self.alumno.pk).update(acceso_portal=True, estatus='ACTIVO')
                self.alumno.refresh_from_db()
                self.client.post(LOGIN, {'acceso': 'estudiantes', 'estudiantes-correo': 'zoe@colegio.mx',
                                         'estudiantes-contrasena': self.alumno.contrasena_visible})
                self.assertEqual(self.client.get(PORTAL_ESTUDIANTES).status_code, 200)
                cambio()
                respuesta = self.client.get(PORTAL_ESTUDIANTES, follow=True)
                self.assertEqual(respuesta.redirect_chain[0][1], 302)
                self.assertContains(respuesta, 'Tu sesión terminó')
                self.assertNotIn(portales.CLAVE_DE_SESION, self.client.session)

    def test_entrar_al_sistema_cierra_la_sesion_del_portal_y_al_reves(self):
        self.entrar_estudiante()
        self.client.post(LOGIN, {'acceso': 'sistema', 'username': 'admin', 'password': 'x'})
        self.assertNotIn(portales.CLAVE_DE_SESION, self.client.session)
        self.assertEqual(self.client.get(reverse('inicio')).status_code, 200)

        # con la sesión del sistema abierta se puede elegir un portal: al entrar, la del sistema se cierra
        self.assertContains(self.client.get(LOGIN, {'acceso': 'tutores'}), 'Si entras a un portal, esa sesión se cerrará')
        self.entrar_tutor()
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(self.client.get(PORTAL_TUTORES).status_code, 200)
        self.assertEqual(self.client.get(reverse('alumnos:lista')).status_code, 302)

    def test_con_la_sesion_del_portal_abierta_la_pantalla_de_acceso_regresa_al_portal(self):
        self.entrar_tutor()
        self.assertRedirects(self.client.get(LOGIN), PORTAL_TUTORES, fetch_redirect_response=False)
        # pero si se elige otra pestaña, se muestra con el aviso de la sesión abierta
        respuesta = self.client.get(LOGIN, {'acceso': 'sistema'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Tienes una sesión abierta en el portal de tutores')

    def test_cerrar_sesion_del_portal(self):
        self.entrar_estudiante()
        self.assertEqual(self.client.get(reverse('portal_estudiantes:salir')).status_code, 405)   # solo con POST
        respuesta = self.client.post(reverse('portal_estudiantes:salir'))
        self.assertContains(respuesta, 'Cerraste tu sesión')
        self.assertContains(respuesta, f'{LOGIN}?acceso=estudiantes')
        self.assertNotIn(portales.CLAVE_DE_SESION, self.client.session)
        self.assertEqual(self.client.get(PORTAL_ESTUDIANTES).status_code, 302)

    def test_la_sesion_del_portal_es_nueva_al_entrar(self):
        self.client.get(LOGIN)
        self.client.session.save()
        antes = self.client.session.session_key
        self.entrar_estudiante()
        self.assertNotEqual(self.client.session.session_key, antes)


@PRUEBAS
class AdministracionDelAccesoTests(BasePortalesTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_la_ficha_muestra_el_estado_del_acceso(self):
        respuesta = self.client.get(self.alumno.get_absolute_url())
        self.assertEqual(respuesta.context['portal'].clave, 'activo')
        self.assertContains(respuesta, 'Acceso al portal')
        self.assertContains(respuesta, 'Todavía no ha entrado')
        self.assertContains(respuesta, 'value="desactivar"')
        type(self.tutor).objects.filter(pk=self.tutor.pk).update(bloqueado_hasta=timezone.now() + timedelta(minutes=5))
        respuesta = self.client.get(self.tutor.get_absolute_url())
        self.assertEqual(respuesta.context['portal'].clave, 'bloqueado')
        self.assertContains(respuesta, 'value="desbloquear"')
        # sin correo, el estudiante todavía no puede entrar
        sin_correo = crear_alumno()
        self.assertEqual(self.client.get(sin_correo.get_absolute_url()).context['portal'].clave, 'sin_credencial')

    def test_activar_desactivar_y_desbloquear(self):
        url = reverse('alumnos:portal', args=[self.alumno.pk])
        self.client.post(url, {'accion': 'desactivar'})
        self.alumno.refresh_from_db()
        self.assertFalse(self.alumno.acceso_portal)
        self.client.post(url, {'accion': 'activar'})
        self.alumno.refresh_from_db()
        self.assertTrue(self.alumno.acceso_portal)

        type(self.tutor).objects.filter(pk=self.tutor.pk).update(intentos_fallidos=3, bloqueado_hasta=timezone.now() + timedelta(minutes=5))
        respuesta = self.client.post(reverse('tutores:portal', args=[self.tutor.pk]), {'accion': 'desbloquear'}, follow=True)
        self.assertContains(respuesta, 'Se desbloqueó el acceso')
        self.tutor.refresh_from_db()
        self.assertEqual((self.tutor.intentos_fallidos, self.tutor.bloqueado_hasta), (0, None))

        self.assertContains(self.client.post(url, {'accion': 'borrar'}, follow=True), 'No se reconoce esa acción')

    def test_solo_quien_edita_administra_el_acceso(self):
        self.con_permisos('view_alumno')
        self.assertEqual(self.client.post(reverse('alumnos:portal', args=[self.alumno.pk]), {'accion': 'desactivar'}).status_code, 403)
        self.alumno.refresh_from_db()
        self.assertTrue(self.alumno.acceso_portal)
        self.assertNotContains(self.client.get(self.alumno.get_absolute_url()), 'value="desactivar"')

    def test_restablecer_la_contrasena_quita_el_bloqueo(self):
        type(self.alumno).objects.filter(pk=self.alumno.pk).update(intentos_fallidos=4, bloqueado_hasta=timezone.now() + timedelta(minutes=5))
        self.client.post(reverse('alumnos:contrasena', args=[self.alumno.pk]), {'contrasena': 'abc12345'})
        self.alumno.refresh_from_db()
        self.assertEqual((self.alumno.intentos_fallidos, self.alumno.bloqueado_hasta), (0, None))
        # las credenciales que se muestran dicen con qué entra al portal
        credenciales = self.client.get(self.alumno.get_absolute_url()).context['credenciales']
        self.assertEqual((credenciales['etiqueta'], credenciales['usuario']), ('Correo electrónico', 'zoe@colegio.mx'))
