"""Mensajería interna: quién con quién, conversaciones en el sistema y en los portales, no leídos y leídos, avisos de la
campana, separación de las cuentas, eventos en tiempo real y el WebSocket de avisos."""
from unittest.mock import patch

from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.sessions.backends.db import SessionStore
from django.test import Client, TransactionTestCase
from django.urls import reverse

from Alumnos.models import MateriaGrado
from CISAHUAYO import portales
from CISAHUAYO.pruebas import (
    PRUEBAS, BaseTestCase, ciclo_actual_de_prueba, crear_alumno, crear_grado, crear_profesor, crear_rol, crear_tutor, crear_usuario,
    grupo_de, inscribir_antes, materia_en_grado, vincular,
)
from Usuarios.models import Rol

from . import reglas, tiempo_real
from .models import Conversacion, Mensaje

BANDEJA = reverse('mensajes:inicio')


def entrar_al_portal(cliente, tipo, cuenta):
    """La sesión de un portal, como la deja CISAHUAYO/portales.iniciar_sesion."""
    sesion = cliente.session
    sesion[portales.CLAVE_DE_SESION] = {'tipo': tipo, 'id': cuenta.pk, 'huella': portales._huella(tipo, cuenta)}
    sesion.save()


class Colegio:
    """4° A de primaria (Ana y Beto; Matemáticas de la docente Marta) y 1° de secundaria (Zoe). Rosa es tutora de Ana y
    Tomás de Zoe. Raúl es docente sin grupos de primaria. Control escolar atiende a las familias; prefectura, solo
    secundaria; recepción solo usa la mensajería entre el personal."""

    def armar(self):
        self.ciclo = ciclo_actual_de_prueba()
        self.primaria = crear_grado('PRIMARIA', 4)
        self.secundaria = crear_grado('SECUNDARIA', 1)
        self.ana = crear_alumno(nombre='Ana', curp='MENSAJES0000000A01')
        self.beto = crear_alumno(nombre='Beto', curp='MENSAJES0000000B01')
        self.zoe = crear_alumno(nombre='Zoe', curp='MENSAJES0000000Z01')
        for alumno, grado in ((self.ana, self.primaria), (self.beto, self.primaria), (self.zoe, self.secundaria)):
            inscribir_antes(alumno, self.ciclo, grado)
        self.rosa = crear_tutor(nombre='Rosa', usuario='rosa.mora')
        self.tomas = crear_tutor(nombre='Tomás', apellido_paterno='Luna', usuario='tomas.luna')
        vincular(self.rosa, self.ana)
        vincular(self.tomas, self.zoe, parentesco='PADRE')

        docente = Rol.objects.get(grupo__name='Docente')
        self.marta = crear_usuario('marta', docente)
        self.profesora = crear_profesor(usuario=self.marta, nombre='Marta')
        self.raul = crear_usuario('raul', docente)
        crear_profesor(usuario=self.raul, nombre='Raúl', telefono='3530001111')
        self.asignacion = materia_en_grado('MAT', self.primaria, self.ciclo, profesor=self.profesora)
        self.control = crear_usuario('control', Rol.objects.get(grupo__name='Control escolar'))
        self.recepcion = crear_usuario('recepcion', Rol.objects.get(grupo__name='Recepción'))
        from Prefectura.models import AlcancePrefectura
        self.prefecto = crear_usuario('prefecto', Rol.objects.get(grupo__name='Prefectura'))
        AlcancePrefectura.objects.create(usuario=self.prefecto, niveles=['SECUNDARIA'])

    def p(self, cuenta):
        """El participante de cualquier cuenta."""
        if isinstance(cuenta, type(self.ana)):
            return reglas.de_portal(portales.ESTUDIANTE, cuenta)
        if isinstance(cuenta, type(self.rosa)):
            return reglas.de_portal(portales.TUTOR, cuenta)
        return reglas.de_usuario(cuenta)


@PRUEBAS
class QuienConQuienTests(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()

    def test_las_parejas_permitidas(self):
        casos = [
            (self.marta, self.ana, True),        # docente y su estudiante
            (self.marta, self.rosa, True),       # docente y el tutor de su estudiante
            (self.marta, self.zoe, False),       # no le da clase
            (self.marta, self.tomas, False),
            (self.raul, self.ana, False),
            (self.control, self.zoe, True),      # atiende a estudiantes y familias
            (self.control, self.tomas, True),
            (self.prefecto, self.zoe, True),     # en su alcance
            (self.prefecto, self.ana, False),    # fuera de su alcance
            (self.recepcion, self.ana, False),   # solo entre el personal
            (self.recepcion, self.marta, True),
            (self.ana, self.beto, False),        # nunca entre estudiantes
            (self.rosa, self.tomas, False),      # ni entre tutores
            (self.ana, self.rosa, False),        # ni entre un estudiante y un tutor
        ]
        for uno, otro, esperado in casos:
            with self.subTest(uno=str(uno), otro=str(otro)):
                self.assertEqual(reglas.pueden_conversar(self.p(uno), self.p(otro)), esperado)
                self.assertEqual(reglas.pueden_conversar(self.p(otro), self.p(uno)), esperado)   # en ambos sentidos

    def test_las_cuentas_inactivas_no_conversan(self):
        self.ana.acceso_portal = False
        self.ana.save()
        self.assertFalse(reglas.pueden_conversar(self.p(self.marta), self.p(self.ana)))
        self.marta.is_active = False
        self.marta.save()
        self.assertFalse(reglas.pueden_conversar(self.p(self.marta), self.p(self.control)))

    def test_la_busqueda_de_destinatarios(self):
        def claves(cuenta, texto=''):
            return {c.clave for c in reglas.contactos(self.p(cuenta), texto)}

        de_ana = claves(self.ana)
        self.assertIn(f'u:{self.marta.pk}', de_ana)       # su docente
        self.assertIn(f'u:{self.control.pk}', de_ana)     # quien atiende a las familias
        self.assertNotIn(f'u:{self.raul.pk}', de_ana)
        self.assertNotIn(f'u:{self.prefecto.pk}', de_ana)  # la prefectura de secundaria no es de su alcance
        self.assertFalse({c for c in claves(self.ana, 'Beto') if c.startswith(('a:', 't:'))})
        self.assertIn(f'u:{self.marta.pk}', claves(self.rosa))
        self.assertIn(f'u:{self.prefecto.pk}', claves(self.tomas))
        # un docente encuentra a sus estudiantes y a sus tutores, no a los de otros grupos
        self.assertIn(f'a:{self.beto.pk}', claves(self.marta, 'Beto'))
        self.assertIn(f't:{self.rosa.pk}', claves(self.marta, 'Rosa'))
        self.assertNotIn(f'a:{self.zoe.pk}', claves(self.marta, 'Zoe'))
        self.assertIn(f'a:{self.zoe.pk}', claves(self.control, 'Zoe'))


@PRUEBAS
class ConversacionTests(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()
        self.ana_cliente = Client()
        entrar_al_portal(self.ana_cliente, portales.ESTUDIANTE, self.ana)
        self.client.force_login(self.marta)

    def abrir_con(self, clave, cliente=None, espacio='mensajes'):
        return (cliente or self.client).post(reverse(f'{espacio}:nueva'), {'destinatario': clave})

    def test_conversacion_entre_docente_y_estudiante(self):
        respuesta = self.abrir_con(f'a:{self.ana.pk}')
        conversacion = Conversacion.objects.get()
        self.assertRedirects(respuesta, reverse('mensajes:conversacion', args=[conversacion.pk]), fetch_redirect_response=False)
        self.assertEqual(self.abrir_con(f'a:{self.ana.pk}')['Location'], respuesta['Location'])   # la misma, no otra
        self.client.post(reverse('mensajes:enviar', args=[conversacion.pk]), {'texto': 'Hola Ana, ¿terminaste la tarea?'})
        mensaje = Mensaje.objects.get()
        self.assertEqual((mensaje.autor, mensaje.texto), (self.p(self.marta), 'Hola Ana, ¿terminaste la tarea?'))

        # Ana lo ve en su portal, sin leer, con quién lo envió y una vista previa en la campana
        url_portal = reverse('portal_estudiantes:mensajes:conversacion', args=[conversacion.pk])
        bandeja = self.ana_cliente.get(reverse('portal_estudiantes:mensajes:inicio'))
        self.assertEqual(bandeja.status_code, 200)
        self.assertEqual(bandeja.context['bandeja'][0].no_leidos, 1)
        self.assertEqual(bandeja.context['mensajeria']['no_leidos'], 1)
        aviso = bandeja.context['mensajeria']['avisos'][0]
        self.assertEqual((aviso['nombre'], aviso['url']), (self.marta.get_full_name(), url_portal))
        self.assertIn('terminaste la tarea', aviso['vista_previa'])
        self.assertContains(bandeja, 'data-notificaciones-total')
        # al abrirla queda leída, y Marta ve su mensaje como «Leído»
        conversacion_ana = self.ana_cliente.get(url_portal)
        self.assertContains(conversacion_ana, 'Hola Ana, ¿terminaste la tarea?')
        self.assertEqual(conversacion_ana.context['mensajeria']['no_leidos'], 0)
        self.assertEqual(reglas.no_leidos(self.p(self.ana)), 0)
        de_marta = self.client.get(reverse('mensajes:conversacion', args=[conversacion.pk]))
        self.assertTrue(de_marta.context['mensajes'][0].leido)

        # Ana responde sin recargar (JSON) y queda pendiente para Marta
        respuesta = self.ana_cliente.post(reverse('portal_estudiantes:mensajes:enviar', args=[conversacion.pk]),
                                          {'texto': 'Sí, maestra'}, HTTP_ACCEPT='application/json')
        datos = respuesta.json()
        self.assertTrue(datos['mio'])
        self.assertEqual((datos['texto'], datos['autor']), ('Sí, maestra', str(self.ana)))
        self.assertEqual(reglas.no_leidos(self.p(self.marta)), 1)
        self.assertEqual(self.client.get(BANDEJA).context['mensajeria']['no_leidos'], 1)

    def test_tutor_y_docente_desde_el_portal_de_tutores(self):
        tutor = Client()
        entrar_al_portal(tutor, portales.TUTOR, self.rosa)
        respuesta = self.abrir_con(f'u:{self.marta.pk}', tutor, 'portal_tutores:mensajes')
        conversacion = Conversacion.objects.get()
        self.assertRedirects(respuesta, reverse('portal_tutores:mensajes:conversacion', args=[conversacion.pk]), fetch_redirect_response=False)
        tutor.post(reverse('portal_tutores:mensajes:enviar', args=[conversacion.pk]), {'texto': '¿Cómo va Ana?'})
        self.assertEqual(self.client.get(BANDEJA).context['bandeja'][0].otro.tutor, self.rosa)
        # su menú lateral: Inicio, Mensajes y sus estudiantes
        inicio = tutor.get(reverse('portal_tutores:inicio'))
        secciones = [(s['titulo'], [e['etiqueta'] for e in s['elementos']]) for s in inicio.context['navegacion']]
        self.assertEqual(secciones, [(None, ['Inicio', 'Mensajes']), ('Mis estudiantes', [self.ana.nombre_completo])])
        self.assertContains(inicio, 'class="sidebar"')
        self.assertContains(inicio, 'class="topbar"')

    def test_no_se_abre_con_quien_no_se_puede(self):
        respuesta = self.abrir_con(f'a:{self.ana.pk}', self.ana_cliente, 'portal_estudiantes:mensajes')   # Ana consigo misma
        self.abrir_con(f'a:{self.beto.pk}', self.ana_cliente, 'portal_estudiantes:mensajes')               # entre estudiantes
        self.abrir_con(f'a:{self.zoe.pk}')                                  # Marta no le da clase a Zoe
        self.abrir_con('x:1')
        self.assertFalse(Conversacion.objects.exists())
        self.assertRedirects(respuesta, reverse('portal_estudiantes:mensajes:inicio'), fetch_redirect_response=False)

    def test_cada_quien_solo_ve_sus_conversaciones(self):
        tutor = Client()
        entrar_al_portal(tutor, portales.TUTOR, self.rosa)
        self.abrir_con(f'u:{self.marta.pk}', tutor, 'portal_tutores:mensajes')
        ajena = Conversacion.objects.get()
        self.assertEqual(self.ana_cliente.get(reverse('portal_estudiantes:mensajes:conversacion', args=[ajena.pk])).status_code, 404)
        self.assertEqual(self.ana_cliente.post(reverse('portal_estudiantes:mensajes:enviar', args=[ajena.pk]), {'texto': 'x'}).status_code, 404)
        self.client.force_login(self.control)
        self.assertEqual(self.client.get(reverse('mensajes:conversacion', args=[ajena.pk])).status_code, 404)

    def test_las_cuentas_no_se_mezclan(self):
        # una cuenta del sistema no entra a la mensajería de un portal, ni un estudiante a la del sistema
        self.assertEqual(self.client.get(reverse('portal_estudiantes:mensajes:inicio')).status_code, 403)
        respuesta = self.ana_cliente.get(BANDEJA)
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse('login'), respuesta['Location'])
        self.assertEqual(self.ana_cliente.get(reverse('portal_tutores:mensajes:inicio')).status_code, 302)
        sin_mensajes = crear_usuario('lupita', crear_rol('Solo estudiantes', {'Alumnos.view_alumno'}))
        self.client.force_login(sin_mensajes)
        self.assertEqual(self.client.get(BANDEJA).status_code, 403)
        self.assertNotContains(self.client.get(reverse('inicio')), 'data-notificaciones ')

    def test_si_la_relacion_termina_ya_no_se_escribe(self):
        self.abrir_con(f'a:{self.ana.pk}')
        conversacion = Conversacion.objects.get()
        MateriaGrado.objects.filter(pk=self.asignacion.pk).update(activa=False)
        respuesta = self.client.post(reverse('mensajes:enviar', args=[conversacion.pk]), {'texto': 'Hola'}, HTTP_ACCEPT='application/json')
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('Ya no puedes escribir', respuesta.json()['error'])
        pantalla = self.client.get(reverse('mensajes:conversacion', args=[conversacion.pk]))
        self.assertFalse(pantalla.context['puede_escribir'])
        self.assertContains(pantalla, 'El historial se conserva')

    def test_validaciones_del_texto(self):
        self.abrir_con(f'a:{self.ana.pk}')
        url = reverse('mensajes:enviar', args=[Conversacion.objects.get().pk])
        self.assertEqual(self.client.post(url, {'texto': '   '}, HTTP_ACCEPT='application/json').status_code, 400)
        self.assertEqual(self.client.post(url, {'texto': 'x' * (Mensaje.MAXIMO + 1)}, HTTP_ACCEPT='application/json').status_code, 400)
        self.assertFalse(Mensaje.objects.exists())

    def test_el_historial_se_pagina_y_se_conserva(self):
        self.abrir_con(f'a:{self.ana.pk}')
        conversacion = Conversacion.objects.get()
        autor = self.p(self.marta)
        Mensaje.objects.bulk_create([Mensaje(conversacion=conversacion, autor=autor, texto=f'Mensaje {i}') for i in range(60)])
        pantalla = self.client.get(reverse('mensajes:conversacion', args=[conversacion.pk]))
        self.assertEqual(len(pantalla.context['mensajes']), 50)
        self.assertTrue(pantalla.context['hay_anteriores'])
        anteriores = self.client.get(reverse('mensajes:conversacion', args=[conversacion.pk]), {'antes': pantalla.context['primero']})
        self.assertEqual([m.texto for m in anteriores.context['mensajes']], [f'Mensaje {i}' for i in range(10)])

    def test_resumen_para_ponerse_al_dia(self):
        self.abrir_con(f'a:{self.ana.pk}')
        conversacion = Conversacion.objects.get()
        self.client.post(reverse('mensajes:enviar', args=[conversacion.pk]), {'texto': 'Recuerda traer tu libro'})
        datos = self.ana_cliente.get(reverse('portal_estudiantes:mensajes:resumen')).json()
        self.assertEqual(datos['no_leidos'], 1)
        self.assertEqual(datos['avisos'][0]['vista_previa'], 'Recuerda traer tu libro')
        self.ana_cliente.post(reverse('portal_estudiantes:mensajes:leida', args=[conversacion.pk]))
        self.assertEqual(self.ana_cliente.get(reverse('portal_estudiantes:mensajes:resumen')).json()['no_leidos'], 0)


@PRUEBAS
class TiempoRealTests(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()
        self.conversacion = reglas.conversacion_con(self.p(self.marta), self.p(self.ana))

    def test_avisa_a_cada_miembro_con_su_propia_direccion(self):
        enviados = []
        with patch.object(tiempo_real, '_enviar', side_effect=lambda pk, evento: enviados.append((pk, evento))):
            with self.captureOnCommitCallbacks(execute=True):
                reglas.enviar(self.conversacion, self.p(self.marta), 'Mañana hay examen')
        eventos = {pk: evento for pk, evento in enviados}
        para_ana, para_marta = eventos[self.p(self.ana).pk], eventos[self.p(self.marta).pk]
        self.assertEqual(para_ana['type'], 'mensaje.nuevo')
        self.assertEqual(para_ana['datos']['url'], reverse('portal_estudiantes:mensajes:conversacion', args=[self.conversacion.pk]))
        self.assertEqual(para_marta['datos']['url'], reverse('mensajes:conversacion', args=[self.conversacion.pk]))
        self.assertEqual((para_ana['datos']['mio'], para_ana['datos']['no_leidos'], para_ana['datos']['autor']), (False, 1, self.marta.get_full_name()))
        self.assertTrue(para_marta['datos']['mio'])

        enviados.clear()
        with patch.object(tiempo_real, '_enviar', side_effect=lambda pk, evento: enviados.append((pk, evento))):
            with self.captureOnCommitCallbacks(execute=True):
                reglas.marcar_leida(self.conversacion, self.p(self.ana))
        tipos = {(pk, evento['type']) for pk, evento in enviados}
        self.assertEqual(tipos, {(self.p(self.marta).pk, 'mensaje.leido'), (self.p(self.ana).pk, 'mensajes.resumen')})

    def test_sin_redis_el_mensaje_se_guarda_igual(self):
        class CapaCaida:
            async def group_send(self, *args, **kwargs):
                raise ConnectionError('Redis no responde')

        self.client.force_login(self.marta)
        with patch.object(tiempo_real, 'get_channel_layer', return_value=CapaCaida()), self.assertLogs('Mensajes.tiempo_real', 'ERROR'):
            with self.captureOnCommitCallbacks(execute=True):
                respuesta = self.client.post(reverse('mensajes:enviar', args=[self.conversacion.pk]), {'texto': 'Hola'}, HTTP_ACCEPT='application/json')
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(Mensaje.objects.filter(texto='Hola').exists())


@PRUEBAS
class WebSocketTests(Colegio, TransactionTestCase):
    """El canal de avisos de verdad (ASGI con la sesión de Django), con la capa en memoria de las pruebas."""

    def setUp(self):
        from Usuarios.iniciales import crear_roles_iniciales
        crear_roles_iniciales()
        self.armar()
        self.conversacion = reglas.conversacion_con(self.p(self.marta), self.p(self.ana))
        cliente = Client()
        cliente.force_login(self.marta)
        self.cookie_marta = cliente.cookies['sessionid'].value
        sesion = SessionStore()
        sesion[portales.CLAVE_DE_SESION] = {'tipo': portales.ESTUDIANTE, 'id': self.ana.pk, 'huella': portales._huella(portales.ESTUDIANTE, self.ana)}
        sesion.create()
        self.cookie_ana = sesion.session_key

    def comunicador(self, cookie=None, origen=b'http://testserver'):
        from CISAHUAYO.asgi import application
        cabeceras = [(b'host', b'testserver')]
        if origen:
            cabeceras.append((b'origin', origen))
        if cookie:
            cabeceras.append((b'cookie', f'sessionid={cookie}'.encode()))
        return WebsocketCommunicator(application, '/ws/mensajes/', headers=cabeceras)

    async def test_llega_el_mensaje_al_momento_a_un_portal_y_al_sistema(self):
        ana = self.comunicador(self.cookie_ana)
        marta = self.comunicador(self.cookie_marta)
        conectada, _ = await ana.connect()
        self.assertTrue(conectada)
        self.assertTrue((await marta.connect())[0])
        await database_sync_to_async(reglas.enviar)(self.conversacion, await database_sync_to_async(self.p)(self.marta), '¿Vienes mañana?')
        evento = await ana.receive_json_from(timeout=3)
        self.assertEqual((evento['evento'], evento['texto'], evento['mio'], evento['no_leidos']), ('mensaje', '¿Vienes mañana?', False, 1))
        self.assertTrue((await marta.receive_json_from(timeout=3))['mio'])
        # Ana lo lee: Marta recibe la lectura
        await database_sync_to_async(reglas.marcar_leida)(self.conversacion, await database_sync_to_async(self.p)(self.ana))
        lectura = await marta.receive_json_from(timeout=3)
        self.assertEqual(lectura['evento'], 'leido')
        self.assertEqual((await ana.receive_json_from(timeout=3))['no_leidos'], 0)
        await ana.send_json_to({'evento': 'ping'})
        self.assertEqual(await ana.receive_json_from(timeout=3), {'evento': 'pong'})
        await ana.disconnect()
        await marta.disconnect()

    async def test_sin_sesion_o_desde_otro_sitio_se_rechaza(self):
        for comunicador in (self.comunicador(), self.comunicador(self.cookie_marta, origen=b'https://otro-sitio.example'),
                            self.comunicador(self.cookie_marta, origen=None)):
            conectado, _ = await comunicador.connect()
            self.assertFalse(conectado)
            await comunicador.disconnect()
