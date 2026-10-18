"""Mensajería interna: quién con quién, conversaciones en el sistema y en los portales, no leídos y leídos, avisos de la
campana, separación de las cuentas, eventos en tiempo real, el WebSocket de avisos y los mensajes con formato (limpieza
del HTML en el servidor, imágenes y caracteres especiales)."""
import io
import json
import re
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.sessions.backends.db import SessionStore
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase, TransactionTestCase, override_settings
from django.urls import reverse

from Alumnos.models import MateriaGrado
from CISAHUAYO import portales
from CISAHUAYO.pruebas import (
    PRUEBAS, BaseTestCase, ciclo_actual_de_prueba, crear_alumno, crear_grado, crear_profesor, crear_rol, crear_tutor, crear_usuario,
    grupo_de, inscribir_antes, materia_en_grado, vincular,
)
from Usuarios.models import Rol

from . import enriquecido, reglas, tiempo_real
from .models import Conversacion, ImagenMensaje, Mensaje

BANDEJA = reverse('mensajes:inicio')
# Las imágenes de las pruebas van a una carpeta temporal (no a la del proyecto)
CARPETA = tempfile.mkdtemp(prefix='cisahuayo-mensajes-')
ARCHIVOS_TEMPORALES = override_settings(MEDIA_ROOT=CARPETA)


def png(nombre='foto.png'):
    from PIL import Image
    contenido = io.BytesIO()
    Image.new('RGB', (4, 4), (47, 115, 124)).save(contenido, 'PNG')
    return SimpleUploadedFile(nombre, contenido.getvalue(), content_type='image/png')


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
        # su menú lateral: Inicio, Mensajes, Comunicados, Retiros anticipados y sus estudiantes
        inicio = tutor.get(reverse('portal_tutores:inicio'))
        secciones = [(s['titulo'], [e['etiqueta'] for e in s['elementos']]) for s in inicio.context['navegacion']]
        self.assertEqual(secciones, [(None, ['Inicio', 'Mensajes', 'Comunicados', 'Retiros anticipados']), ('Mis estudiantes', [self.ana.nombre_completo])])
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


class LimpiezaDelFormatoTests(SimpleTestCase):
    """El HTML del editor se rehace en el servidor con una lista de lo permitido: nada de scripts ni de eventos."""

    def limpio(self, html, **opciones):
        return enriquecido.limpiar(html, **opciones)[0]

    def test_quita_scripts_eventos_y_enlaces_peligrosos(self):
        casos = {
            '<p>Hola <script>alert(1)</script><b>ok</b></p>': '<p>Hola <b>ok</b></p>',
            '<p onclick="robar()">x<img src="x" onerror="alert(1)"></p>': '<p>x</p>',
            '<svg><script>alert(1)</script><text>svg</text></svg><iframe src="https://x"></iframe><p>queda</p>': '<p>queda</p>',
            '<p>&lt;script&gt; texto</p><!-- comentario --><style>p{color:red}</style>': '<p>&lt;script&gt; texto</p>',
            '<p><a href="javascript:alert(1)">mala</a></p>': '<p><a>mala</a></p>',
            '<table><tbody><tr><td colspan="2" onmouseover="x">c</td></tr></tbody></table>':
                '<table><tbody><tr><td colspan="2">c</td></tr></tbody></table>',
        }
        for html, esperado in casos.items():
            with self.subTest(html=html):
                self.assertEqual(self.limpio(html), esperado)

    def test_conserva_el_formato_permitido(self):
        casos = {
            '<p><a href="www.sep.gob.mx">SEP</a></p>':
                '<p><a href="https://www.sep.gob.mx" target="_blank" rel="noopener noreferrer nofollow">SEP</a></p>',
            '<p><span style="color: rgb(192, 57, 43); position: fixed; background: url(javascript:alert(1))">rojo</span></p>':
                '<p><span style="color: rgb(192,57,43)">rojo</span></p>',
            '<p style="text-align: center; margin-left: 40px; font-size: 900px">centro</p>':
                '<p style="text-align: center; margin-left: 40px">centro</p>',
            '<p><font color="#ff0000" face="Arial">viejo</font></p>': '<p><span style="color: #ff0000; font-family: Arial">viejo</span></p>',
            '<ol style="list-style-type: lower-alpha" start="3"><li>a</li></ol>': '<ol start="3" style="list-style-type: lower-alpha"><li>a</li></ol>',
        }
        for html, esperado in casos.items():
            with self.subTest(html=html):
                self.assertEqual(self.limpio(html), esperado)

    def test_solo_imagenes_permitidas_y_con_la_direccion_de_quien_mira(self):
        html = '<p><img data-imagen="5" src="https://otro-sitio.example/x.png" alt="Foto"><img data-imagen="9" alt="ajena"></p>'
        self.assertEqual(enriquecido.limpiar(html, imagenes_validas={5}), ('<p><img data-imagen="5" alt="Foto"></p>', [5]))
        self.assertEqual(enriquecido.presentar('<p><img data-imagen="5" alt="Foto"></p>', lambda pk: f'/portal/imagenes/{pk}/'),
                         '<p><img data-imagen="5" src="/portal/imagenes/5/" loading="lazy" alt="Foto"></p>')

    def test_texto_sin_formato_y_mensajes_vacios(self):
        self.assertEqual(enriquecido.texto_plano('<p><b>Aviso</b><br>Junta</p><ul><li>uno</li><li>dos</li></ul><p><img data-imagen="1" alt=""></p>'),
                         'Aviso\nJunta\n• uno\n• dos\n📷 Imagen')
        self.assertFalse(enriquecido.tiene_contenido('<p><b></b><br></p><ul><li><br></li></ul>'))
        self.assertTrue(enriquecido.tiene_contenido('<p><img data-imagen="1" alt=""></p>'))
        self.assertTrue(enriquecido.es_texto_simple('<p>Hola<br>Ana</p>'))
        self.assertFalse(enriquecido.es_texto_simple('<p><b>Hola</b></p>'))


@PRUEBAS
@ARCHIVOS_TEMPORALES
class MensajesConFormatoTests(Colegio, BaseTestCase):
    """El editor con formato: lo que se guarda, cómo lo ve quien lo recibe y quién puede ver sus imágenes."""

    def setUp(self):
        super().setUp()
        self.armar()
        self.conversacion = reglas.conversacion_con(self.p(self.marta), self.p(self.ana))
        self.client.force_login(self.marta)
        self.ana_cliente = Client()
        entrar_al_portal(self.ana_cliente, portales.ESTUDIANTE, self.ana)

    def enviar(self, html, texto=''):
        return self.client.post(reverse('mensajes:enviar', args=[self.conversacion.pk]), {'texto': texto, 'html': html},
                                HTTP_ACCEPT='application/json')

    def subir(self, archivo, cliente=None, espacio='mensajes', conversacion=None):
        url = reverse(f'{espacio}:imagen_subir', args=[(conversacion or self.conversacion).pk])
        return (cliente or self.client).post(url, {'imagen': archivo} if archivo else {})

    def test_el_formato_se_guarda_limpio_y_se_ve_al_recargar(self):
        respuesta = self.enviar('<p><b>Examen</b> el <u>lunes</u><script>alert(1)</script></p><ul><li>Tema 1</li></ul>'
                                '<p><a href="https://cisahuayo.edu.mx/temario" onclick="robar()">Temario</a></p>', texto='se ignora')
        self.assertEqual(respuesta.status_code, 200)
        mensaje = Mensaje.objects.get()
        self.assertEqual(mensaje.html, '<p><b>Examen</b> el <u>lunes</u></p><ul><li>Tema 1</li></ul><p><a href="https://cisahuayo.edu.mx/temario" '
                                       'target="_blank" rel="noopener noreferrer nofollow">Temario</a></p>')
        self.assertEqual(mensaje.texto, 'Examen el lunes\n• Tema 1\nTemario')
        self.assertEqual(respuesta.json()['html'], mensaje.html)
        # la campana de Ana muestra el texto sin formato; la conversación, con formato
        self.assertTrue(self.ana_cliente.get(reverse('portal_estudiantes:mensajes:resumen')).json()['avisos'][0]['vista_previa'].startswith('Examen el lunes'))
        pantalla = self.ana_cliente.get(reverse('portal_estudiantes:mensajes:conversacion', args=[self.conversacion.pk]))
        self.assertContains(pantalla, f'<div class="burbuja__texto burbuja__texto--rico">{mensaje.html}</div>')
        self.assertNotContains(pantalla, 'alert(1)')
        self.assertNotContains(pantalla, 'robar()')

    def test_sin_formato_se_guarda_como_texto_y_los_mensajes_de_antes_se_ven_igual(self):
        self.enviar('<p>Hola<br>Ana</p>')
        mensaje = Mensaje.objects.get()
        self.assertEqual((mensaje.texto, mensaje.html), ('Hola\nAna', ''))
        Mensaje.objects.create(conversacion=self.conversacion, autor=self.p(self.marta), texto='Mensaje de antes <b>sin</b> formato')
        pantalla = self.client.get(reverse('mensajes:conversacion', args=[self.conversacion.pk]))
        self.assertContains(pantalla, '<p class="burbuja__texto">Hola<br>Ana</p>', html=True)
        self.assertContains(pantalla, 'Mensaje de antes &lt;b&gt;sin&lt;/b&gt; formato')
        self.assertNotContains(pantalla, 'burbuja__texto--rico')

    def test_solo_formato_no_es_un_mensaje(self):
        for html in ('<p><b></b><br></p><ul><li><br></li></ul>', '<script>alert(1)</script>', '<p><img data-imagen="999" alt=""></p>'):
            with self.subTest(html=html):
                respuesta = self.enviar(html)
                self.assertEqual(respuesta.status_code, 400)
                self.assertEqual(respuesta.json()['error'], 'Escribe un mensaje.')
        self.assertFalse(Mensaje.objects.exists())

    def test_las_imagenes_solo_las_ven_quienes_conversan(self):
        subida = self.subir(png('grupo.png'))
        self.assertEqual(subida.status_code, 200)
        imagen = ImagenMensaje.objects.get()
        self.assertEqual(subida.json()['url'], reverse('mensajes:imagen', args=[imagen.pk]))
        url_de_ana = reverse('portal_estudiantes:mensajes:imagen', args=[imagen.pk])
        self.assertEqual(self.client.get(subida.json()['url']).status_code, 200)   # quien la subió
        self.assertEqual(self.ana_cliente.get(url_de_ana).status_code, 404)        # aún no se envía

        self.enviar(f'<p>Foto del grupo</p><p><img data-imagen="{imagen.pk}" alt="Grupo" style="width: 50%"></p>')
        mensaje = Mensaje.objects.get()
        imagen.refresh_from_db()
        self.assertEqual(imagen.mensaje, mensaje)
        self.assertEqual(mensaje.texto, 'Foto del grupo\n📷 Imagen')
        respuesta = self.ana_cliente.get(url_de_ana)
        self.assertEqual((respuesta.status_code, respuesta['Content-Type']), (200, 'image/png'))
        pantalla = self.ana_cliente.get(reverse('portal_estudiantes:mensajes:conversacion', args=[self.conversacion.pk]))
        self.assertContains(pantalla, f'<img data-imagen="{imagen.pk}" src="{url_de_ana}" loading="lazy" alt="Grupo" style="width: 50%">')

        # quien no es de la conversación no la ve, aunque use la mensajería (ni la tutora de Ana)
        self.client.force_login(self.control)
        self.assertEqual(self.client.get(reverse('mensajes:imagen', args=[imagen.pk])).status_code, 404)
        rosa = Client()
        entrar_al_portal(rosa, portales.TUTOR, self.rosa)
        self.assertEqual(rosa.get(reverse('portal_tutores:mensajes:imagen', args=[imagen.pk])).status_code, 404)

    def test_solo_se_insertan_imagenes_propias_de_la_conversacion(self):
        otra = reglas.conversacion_con(self.p(self.marta), self.p(self.beto))
        de_otra = self.subir(png(), conversacion=otra).json()['id']
        de_ana = self.subir(png(), self.ana_cliente, 'portal_estudiantes:mensajes').json()['id']
        self.enviar(f'<p>Mira</p><p><img data-imagen="{de_otra}" alt=""><img data-imagen="{de_ana}" alt=""></p>')
        mensaje = Mensaje.objects.get()
        self.assertEqual((mensaje.texto, mensaje.html), ('Mira', ''))
        self.assertFalse(ImagenMensaje.objects.filter(mensaje__isnull=False).exists())

    def test_validaciones_de_la_subida(self):
        casos = [
            (SimpleUploadedFile('falsa.png', b'no soy una imagen', content_type='image/png'), 'no es una imagen válida'),
            (SimpleUploadedFile('circular.pdf', b'%PDF-1.4 contenido', content_type='application/pdf'), 'solo se pueden insertar imágenes'),
            (SimpleUploadedFile('programa.exe', b'MZ', content_type='application/octet-stream'), 'solo se aceptan'),
            (SimpleUploadedFile('enorme.png', b'0' * (ImagenMensaje.TAMANO_MAXIMO_MB * 1024 * 1024 + 1), content_type='image/png'), 'pesa más de'),
            (None, 'Elige una imagen'),
        ]
        for archivo, error in casos:
            with self.subTest(archivo=getattr(archivo, 'name', None)):
                respuesta = self.subir(archivo)
                self.assertEqual(respuesta.status_code, 400)
                self.assertIn(error, respuesta.json()['error'])
        self.assertFalse(ImagenMensaje.objects.exists())
        # en una conversación ajena no se sube nada; en la propia, también el estudiante desde su portal
        ajena = reglas.conversacion_con(self.p(self.control), self.p(self.zoe))
        self.assertEqual(self.subir(png(), conversacion=ajena).status_code, 404)
        self.assertEqual(self.subir(png(), self.ana_cliente, 'portal_estudiantes:mensajes').status_code, 200)

    def test_si_ya_no_se_puede_escribir_no_se_suben_imagenes(self):
        MateriaGrado.objects.filter(pk=self.asignacion.pk).update(activa=False)
        self.assertEqual(self.subir(png()).status_code, 403)
        self.assertFalse(ImagenMensaje.objects.exists())

    def test_el_aviso_en_tiempo_real_lleva_el_formato_con_la_direccion_de_cada_quien(self):
        imagen = self.subir(png()).json()['id']
        enviados = []
        with patch.object(tiempo_real, '_enviar', side_effect=lambda pk, evento: enviados.append((pk, evento))):
            with self.captureOnCommitCallbacks(execute=True):
                self.enviar(f'<p><i>Hola</i></p><p><img data-imagen="{imagen}" alt="x"></p>')
        datos = {pk: evento['datos'] for pk, evento in enviados}
        self.assertIn(f'src="{reverse("portal_estudiantes:mensajes:imagen", args=[imagen])}"', datos[self.p(self.ana).pk]['html'])
        self.assertIn(f'src="{reverse("mensajes:imagen", args=[imagen])}"', datos[self.p(self.marta).pk]['html'])
        self.assertTrue(datos[self.p(self.ana).pk]['html'].startswith('<p><i>Hola</i></p>'))

    def test_los_caracteres_especiales_se_guardan_y_se_ven_igual(self):
        especiales = '€ — ✓ ∑ ½ «» → Ω ñ'
        respuesta = self.enviar(f'<p>Cuota: <b>350 €</b> — pago ✓</p><p>{especiales}</p>')
        self.assertEqual(respuesta.status_code, 200)
        mensaje = Mensaje.objects.get()
        self.assertEqual(mensaje.html, f'<p>Cuota: <b>350 €</b> — pago ✓</p><p>{especiales}</p>')
        self.assertEqual(mensaje.texto, f'Cuota: 350 € — pago ✓\n{especiales}')
        self.assertIn('<b>350 €</b>', respuesta.json()['html'])
        for pantalla in (self.client.get(reverse('mensajes:conversacion', args=[self.conversacion.pk])),
                         self.ana_cliente.get(reverse('portal_estudiantes:mensajes:conversacion', args=[self.conversacion.pk]))):
            self.assertContains(pantalla, f'<p>Cuota: <b>350 €</b> — pago ✓</p><p>{especiales}</p>')
        # sin formato, como texto
        self.enviar('<p>Grados: 25 °C</p>')
        self.assertEqual(Mensaje.objects.latest('pk').texto, 'Grados: 25 °C')

    def test_la_conversacion_trae_la_ventana_de_caracteres_especiales(self):
        pantalla = self.client.get(reverse('mensajes:conversacion', args=[self.conversacion.pk]))
        self.assertContains(pantalla, 'data-comando="caracteres"')
        self.assertContains(pantalla, 'data-editor-caracteres')
        self.assertContains(pantalla, 'js/caracteres-especiales.js')
        self.assertNotContains(pantalla, '{#')   # ningún comentario de plantilla mal cerrado a la vista
        # quien ya no puede escribir no recibe el editor
        MateriaGrado.objects.filter(pk=self.asignacion.pk).update(activa=False)
        sin_escribir = self.client.get(reverse('mensajes:conversacion', args=[self.conversacion.pk]))
        self.assertNotContains(sin_escribir, 'js/caracteres-especiales.js')


class CatalogoDeCaracteresTests(SimpleTestCase):
    """static/js/caracteres-especiales.js: las categorías del pedido, en su orden, con caracteres de verdad y nombres."""
    ARCHIVO = Path(__file__).resolve().parent.parent / 'static' / 'js' / 'caracteres-especiales.js'
    CADENA = r'"((?:[^"\\]|\\.)*)"'

    def categorias(self):
        contenido = self.ARCHIVO.read_text(encoding='utf-8')
        partes = re.split(r'\{ nombre: ' + self.CADENA + r', caracteres: \[', contenido)[1:]
        resultado = {}
        for nombre, cuerpo in zip(partes[0::2], partes[1::2]):
            pares = re.findall(r'\[' + self.CADENA + ', ' + self.CADENA + r'\]', cuerpo)
            resultado[json.loads(f'"{nombre}"')] = [(json.loads(f'"{c}"'), json.loads(f'"{n}"')) for c, n in pares]
        return resultado

    def test_categorias_y_caracteres(self):
        categorias = self.categorias()
        self.assertEqual(list(categorias), ['Divisa', 'Texto', 'Comillas', 'Matemáticos', 'Latín extendido', 'Símbolos', 'Flechas'])
        todos = set()
        for categoria, caracteres in categorias.items():
            with self.subTest(categoria=categoria):
                self.assertGreater(len(caracteres), 15)
                self.assertEqual(len({c for c, _ in caracteres}), len(caracteres))   # sin repetidos en la categoría
                for caracter, nombre in caracteres:
                    self.assertEqual(len(caracter), 1, caracter)
                    self.assertTrue(nombre.strip(), caracter)
                todos |= {c for c, _ in caracteres}
        self.assertGreater(len(todos), 600)
        for caracter in '$€£¥©®™§¶±×÷≠≤≥∞√∑πΩ←→⇒«»“”ñÑáé✓★':
            self.assertIn(caracter, todos)


def tearDownModule():
    shutil.rmtree(CARPETA, ignore_errors=True)
