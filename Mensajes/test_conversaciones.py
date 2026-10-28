"""Mejoras de la mensajería del 2026-10-20: documentos PDF adjuntos, buscar en el texto de las conversaciones, la bandeja
por partes («Ver más conversaciones»), la conversación recién empezada en la lista, la hora de lectura («Leído a las
10:42») y la limpieza diaria de los archivos que nunca se enviaron."""
import io
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from CISAHUAYO import portales
from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase

from . import limpieza, reglas, tiempo_real
from .models import Conversacion, ImagenMensaje, Mensaje
from .tests import ARCHIVOS_TEMPORALES, BANDEJA, Colegio, entrar_al_portal, png


def pdf(nombre='tarea.pdf', contenido=b'%PDF-1.4\n% prueba\n'):
    return SimpleUploadedFile(nombre, contenido, content_type='application/pdf')


class Base(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()
        cache.delete(limpieza.LLAVE)
        self.conversacion = reglas.conversacion_con(self.p(self.marta), self.p(self.ana))
        self.client.force_login(self.marta)
        self.ana_cliente = Client()
        entrar_al_portal(self.ana_cliente, portales.ESTUDIANTE, self.ana)

    def adjuntar(self, archivo, cliente=None, espacio='mensajes', conversacion=None):
        url = reverse(f'{espacio}:documento_subir', args=[(conversacion or self.conversacion).pk])
        return (cliente or self.client).post(url, {'documento': archivo} if archivo else {})

    def enviar(self, texto='', documentos=(), html='', cliente=None, espacio='mensajes'):
        url = reverse(f'{espacio}:enviar', args=[self.conversacion.pk])
        return (cliente or self.client).post(url, {'texto': texto, 'html': html, 'documentos': list(documentos)}, HTTP_ACCEPT='application/json')

    def pantalla(self, cliente=None, espacio='mensajes', **parametros):
        return (cliente or self.client).get(reverse(f'{espacio}:conversacion', args=[self.conversacion.pk]), parametros)


# ---------------------------------------------------------------------------
# Documentos PDF
# ---------------------------------------------------------------------------
@PRUEBAS
@ARCHIVOS_TEMPORALES
class DocumentosTests(Base):
    def test_se_adjunta_un_pdf_y_lo_ve_la_otra_persona(self):
        subida = self.adjuntar(pdf('Circular 12.pdf'))
        self.assertEqual(subida.status_code, 200)
        documento = ImagenMensaje.objects.get()
        self.assertEqual((documento.tipo, documento.mensaje), (ImagenMensaje.DOCUMENTO, None))
        self.assertEqual(subida.json()['url'], reverse('mensajes:documento', args=[documento.pk]))
        self.assertEqual(subida.json()['tamano'], 'PDF · 1 KB')
        url_de_ana = reverse('portal_estudiantes:mensajes:documento', args=[documento.pk])
        self.assertEqual(self.ana_cliente.get(url_de_ana).status_code, 404)   # aún no se envía

        respuesta = self.enviar('Les comparto la circular', documentos=[documento.pk])
        self.assertEqual(respuesta.status_code, 200)
        datos = respuesta.json()
        self.assertEqual(datos['texto'], 'Les comparto la circular')
        self.assertEqual(datos['documentos'], [{'id': documento.pk, 'nombre': 'Circular 12.pdf', 'tamano': 'PDF · 1 KB',
                                                'url': reverse('mensajes:documento', args=[documento.pk])}])
        documento.refresh_from_db()
        self.assertEqual(documento.mensaje.texto, 'Les comparto la circular')

        entregado = self.ana_cliente.get(url_de_ana)
        self.assertEqual((entregado.status_code, entregado['Content-Type']), (200, 'application/pdf'))
        entregado.close()
        pantalla = self.pantalla(self.ana_cliente, 'portal_estudiantes:mensajes')
        self.assertContains(pantalla, f'href="{url_de_ana}"')
        self.assertContains(pantalla, 'Circular 12.pdf')
        # quien no es de la conversación no lo ve
        rosa = Client()
        entrar_al_portal(rosa, portales.TUTOR, self.rosa)
        self.assertEqual(rosa.get(reverse('portal_tutores:mensajes:documento', args=[documento.pk])).status_code, 404)

    def test_solo_documentos_sin_texto(self):
        uno = self.adjuntar(pdf('tarea.pdf')).json()['id']
        dos = self.adjuntar(pdf('rubrica.pdf')).json()['id']
        datos = self.enviar(documentos=[uno, dos]).json()
        mensaje = Mensaje.objects.get()
        self.assertTrue(mensaje.sin_texto)
        self.assertEqual(mensaje.texto, '📎 tarea.pdf\n📎 rubrica.pdf')   # para vistas previas, avisos y búsquedas
        self.assertEqual((datos['texto'], datos['vista_previa']), ('', mensaje.texto))
        self.assertIn('tarea.pdf', reglas.avisos(self.p(self.ana))[0].ultimo_mensaje.texto)   # la campana de Ana
        pantalla = self.pantalla(self.ana_cliente, 'portal_estudiantes:mensajes')
        self.assertNotContains(pantalla, '<p class="burbuja__texto">📎')   # la burbuja muestra los documentos, no el resumen
        self.assertContains(pantalla, 'rubrica.pdf')

    def test_solo_pdf_y_solo_los_propios_sin_enviar(self):
        self.assertContains(self.adjuntar(png('foto.png')), 'solo se pueden adjuntar documentos PDF', status_code=400)
        falso = SimpleUploadedFile('falso.pdf', b'no soy un pdf', content_type='application/pdf')
        self.assertIn('no es un PDF válido', self.adjuntar(falso).json()['error'])
        self.assertContains(self.adjuntar(None), 'Elige un documento PDF', status_code=400)
        # una imagen no se inserta como documento ni un PDF como imagen
        imagen = self.client.post(reverse('mensajes:imagen_subir', args=[self.conversacion.pk]), {'imagen': png()}).json()['id']
        documento = self.adjuntar(pdf()).json()['id']
        como_imagen = self.client.post(reverse('mensajes:imagen_subir', args=[self.conversacion.pk]), {'imagen': pdf()})
        self.assertEqual(como_imagen.status_code, 400)
        self.assertIn('solo se pueden insertar imágenes', como_imagen.json()['error'])
        respuesta = self.enviar(documentos=[imagen], html=f'<p><img data-imagen="{documento}" alt=""></p>')
        self.assertEqual(respuesta.json()['error'], 'Escribe un mensaje.')
        # ni el de otra persona
        de_ana = self.adjuntar(pdf(), self.ana_cliente, 'portal_estudiantes:mensajes').json()['id']
        self.assertEqual(self.enviar(documentos=[de_ana]).json()['error'], 'Escribe un mensaje.')
        self.assertFalse(Mensaje.objects.exists())

    def test_maximo_de_documentos_por_mensaje(self):
        ids = [self.adjuntar(pdf(f'd{n}.pdf')).json()['id'] for n in range(3)]
        with patch.object(ImagenMensaje, 'DOCUMENTOS_POR_MENSAJE', 2):
            self.assertIn('hasta 2 documentos', self.enviar('Van', documentos=ids).json()['error'])
        self.assertEqual(self.enviar('Van', documentos=ids).status_code, 200)

    def test_el_aviso_en_vivo_lleva_los_documentos_con_la_direccion_de_cada_quien(self):
        documento = self.adjuntar(pdf()).json()['id']
        enviados = []
        with patch.object(tiempo_real, '_enviar', side_effect=lambda pk, evento: enviados.append((pk, evento))):
            with self.captureOnCommitCallbacks(execute=True):
                self.enviar(documentos=[documento])
        para_ana = dict(enviados)[self.p(self.ana).pk]['datos']
        self.assertEqual(para_ana['documentos'][0]['url'], reverse('portal_estudiantes:mensajes:documento', args=[documento]))
        self.assertEqual(para_ana['texto'], '')

    def test_retirar_un_mensaje_borra_tambien_sus_documentos(self):
        from . import moderacion
        documento = ImagenMensaje.objects.get(pk=self.adjuntar(pdf()).json()['id'])
        archivo = Path(documento.archivo.path)
        self.enviar('Ver adjunto', documentos=[documento.pk])
        with self.captureOnCommitCallbacks(execute=True):
            moderacion.retirar(Mensaje.objects.get())
        self.assertFalse(ImagenMensaje.objects.exists())
        self.assertFalse(archivo.exists())


# ---------------------------------------------------------------------------
# Buscar en las conversaciones
# ---------------------------------------------------------------------------
@PRUEBAS
@ARCHIVOS_TEMPORALES
class BuscarTests(Base):
    def setUp(self):
        super().setUp()
        self.examen = reglas.enviar(self.conversacion, self.p(self.marta), 'El examen de fracciones es el lunes')
        self.otro = reglas.enviar(self.conversacion, self.p(self.ana), 'Gracias maestra')
        ajena = reglas.conversacion_con(self.p(self.control), self.p(self.rosa))
        reglas.enviar(ajena, self.p(self.rosa), 'El examen de Ana me preocupa')

    def test_busca_solo_en_sus_conversaciones(self):
        encontrados = reglas.buscar_mensajes(self.p(self.marta), 'examen')
        self.assertEqual([m.pk for m in encontrados], [self.examen.pk])
        self.assertEqual(encontrados[0].otro, self.p(self.ana))
        self.assertIn('<mark>examen</mark>', str(encontrados[0].fragmento))
        self.assertEqual(reglas.buscar_mensajes(self.p(self.marta), 'EXAMEN lunes')[0].pk, self.examen.pk)
        self.assertEqual(reglas.buscar_mensajes(self.p(self.marta), 'preocupa'), [])   # de otra conversación
        self.assertEqual(reglas.buscar_mensajes(self.p(self.marta), 'x'), [])          # muy corto

    def test_tambien_por_el_nombre_de_un_documento(self):
        documento = self.adjuntar(pdf('Guia de estudio.pdf')).json()['id']
        self.enviar('Para el lunes', documentos=[documento])
        self.assertEqual([m.texto for m in reglas.buscar_mensajes(self.p(self.marta), 'guia')], ['Para el lunes'])

    def test_la_busqueda_en_json_y_sin_javascript(self):
        datos = self.client.get(reverse('mensajes:buscar'), {'q': 'fracciones'}).json()['mensajes']
        url = f"{reverse('mensajes:conversacion', args=[self.conversacion.pk])}?mensaje={self.examen.pk}#mensaje-{self.examen.pk}"
        self.assertEqual((datos[0]['url'], datos[0]['nombre'], datos[0]['mio']), (url, str(self.ana), True))
        # en el portal, con sus direcciones
        de_ana = self.ana_cliente.get(reverse('portal_estudiantes:mensajes:buscar'), {'q': 'fracciones'}).json()['mensajes']
        self.assertTrue(de_ana[0]['url'].startswith(reverse('portal_estudiantes:mensajes:conversacion', args=[self.conversacion.pk])))
        self.assertFalse(de_ana[0]['mio'])
        bandeja = self.client.get(BANDEJA, {'q': 'fracciones'})
        self.assertContains(bandeja, 'En tus mensajes')
        self.assertContains(bandeja, '<mark>fracciones</mark>')

    def test_abrir_la_conversacion_en_el_mensaje_encontrado(self):
        with patch.object(reglas, 'POR_MINUTO', 100):   # sin el límite de mensajes seguidos
            for n in range(60):
                reglas.enviar(self.conversacion, self.p(self.marta), f'Recordatorio {n}')
        pantalla = self.pantalla(mensaje=self.examen.pk)
        ids = [m.pk for m in pantalla.context['mensajes']]
        self.assertIn(self.examen.pk, ids)
        self.assertTrue(pantalla.context['hay_posteriores'])
        self.assertContains(pantalla, 'is-destacado')
        self.assertContains(pantalla, 'Ver mensajes más recientes')
        self.assertContains(pantalla, 'data-hay-posteriores')
        self.assertNotContains(self.pantalla(), 'data-hay-posteriores')   # en los más recientes, no


# ---------------------------------------------------------------------------
# La lista de conversaciones
# ---------------------------------------------------------------------------
@PRUEBAS
@ARCHIVOS_TEMPORALES
class BandejaTests(Base):
    def setUp(self):
        super().setUp()
        self.conversaciones = []
        for cuenta in (self.ana, self.beto, self.rosa, self.control, self.recepcion):
            conversacion = reglas.conversacion_con(self.p(self.marta), self.p(cuenta))
            reglas.enviar(conversacion, self.p(cuenta), f'Hola, soy {cuenta}')
            self.conversaciones.append(conversacion.pk)
        self.conversaciones.reverse()   # la más reciente primero

    def test_por_partes_sin_repetir_ni_saltar(self):
        vistas, cursor = [], None
        while True:
            pagina, cursor = reglas.pagina_de_bandeja(self.p(self.marta), despues=cursor, limite=2)
            vistas += [c.pk for c in pagina]
            if cursor is None:
                break
        self.assertEqual(vistas, self.conversaciones)

    def test_ver_mas_conversaciones(self):
        with patch.object(reglas, 'POR_PAGINA_BANDEJA', 2):
            bandeja = self.client.get(BANDEJA)
            self.assertEqual([c.pk for c in bandeja.context['bandeja']], self.conversaciones[:2])
            self.assertContains(bandeja, 'Ver más conversaciones')
            siguientes = bandeja.context['siguientes']
            datos = self.client.get(reverse('mensajes:conversaciones'), {'despues': siguientes}).json()
            self.assertIn(f'data-conversacion-item="{self.conversaciones[2]}"', datos['html'])
            self.assertNotIn(f'data-conversacion-item="{self.conversaciones[0]}"', datos['html'])
            ultima = self.client.get(reverse('mensajes:conversaciones'), {'despues': datos['siguientes']}).json()
            self.assertIn(f'data-conversacion-item="{self.conversaciones[4]}"', ultima['html'])
            self.assertEqual(ultima['siguientes'], '')
            # sin JavaScript: la página siguiente
            self.assertEqual([c.pk for c in self.client.get(BANDEJA, {'despues': siguientes}).context['bandeja']], self.conversaciones[2:4])
        self.assertNotContains(self.client.get(BANDEJA), 'Ver más conversaciones')
        self.assertEqual(self.client.get(reverse('mensajes:conversaciones'), {'despues': 'no-vale'}).status_code, 200)

    def test_la_conversacion_recien_empezada_dice_con_quien(self):
        nueva = reglas.conversacion_con(self.p(self.marta), self.p(self.raul))
        self.conversacion = nueva
        datos = self.enviar('Hola Raúl').json()
        self.assertEqual(datos['con'], {'nombre': self.raul.get_full_name(), 'iniciales': self.p(self.raul).iniciales, 'tipo': 'sistema'})
        self.assertTrue(datos['mio'])


# ---------------------------------------------------------------------------
# Leído a las…
# ---------------------------------------------------------------------------
@PRUEBAS
@ARCHIVOS_TEMPORALES
class LecturaTests(Base):
    def test_guarda_la_hora_en_que_se_leyo_cada_mensaje(self):
        uno = reglas.enviar(self.conversacion, self.p(self.marta), 'Uno')
        dos = reglas.enviar(self.conversacion, self.p(self.marta), 'Dos')
        self.assertIsNone(Mensaje.objects.get(pk=uno.pk).leido_en)
        self.pantalla(self.ana_cliente, 'portal_estudiantes:mensajes')   # Ana la abre
        leidos = Mensaje.objects.filter(pk__in=[uno.pk, dos.pk])
        self.assertTrue(all(m.leido_en for m in leidos))
        hora = timezone.localtime(Mensaje.objects.get(pk=dos.pk).leido_en).strftime('%H:%M')
        pantalla = self.pantalla()
        self.assertContains(pantalla, f'<span class="burbuja__leido" data-leido>Leído a las {hora}</span>', html=True)
        self.assertContains(pantalla, f'data-tooltip="Leído a las {hora}"', count=1)   # el anterior, al pasar el puntero

    def test_al_responder_queda_leido_lo_anterior(self):
        pregunta = reglas.enviar(self.conversacion, self.p(self.marta), '¿Terminaste?')
        enviados = []
        with patch.object(tiempo_real, '_enviar', side_effect=lambda pk, evento: enviados.append((pk, evento))):
            with self.captureOnCommitCallbacks(execute=True):
                respuesta = reglas.enviar(self.conversacion, self.p(self.ana), 'Sí')
        self.assertIsNotNone(Mensaje.objects.get(pk=pregunta.pk).leido_en)
        self.assertIsNone(Mensaje.objects.get(pk=respuesta.pk).leido_en)
        lectura = [evento for pk, evento in enviados if evento['type'] == 'mensaje.leido']
        self.assertEqual(lectura[0]['datos']['hasta'], respuesta.pk)
        self.assertTrue(lectura[0]['datos']['leido'].startswith('Leído a las '))

    def test_el_texto_de_lectura(self):
        ahora = timezone.now()
        self.assertEqual(reglas.texto_de_lectura(None), 'Leído')
        self.assertEqual(reglas.texto_de_lectura(ahora), f"Leído a las {timezone.localtime(ahora):%H:%M}")
        self.assertTrue(reglas.texto_de_lectura(ahora - timedelta(days=1)).startswith('Leído ayer a las '))
        antes = reglas.texto_de_lectura(ahora - timedelta(days=9))
        self.assertTrue(antes.startswith('Leído el ') and ' a las ' in antes, antes)
        self.assertEqual(antes, antes.replace('Octubre', 'octubre'))   # el mes en minúsculas

    def test_los_mensajes_de_antes_dicen_leido_sin_hora(self):
        viejo = reglas.enviar(self.conversacion, self.p(self.marta), 'De antes')
        self.pantalla(self.ana_cliente, 'portal_estudiantes:mensajes')
        Mensaje.objects.filter(pk=viejo.pk).update(leido_en=None)   # como los leídos antes de guardar la hora
        self.assertContains(self.pantalla(), '<span class="burbuja__leido" data-leido>Leído</span>', html=True)


# ---------------------------------------------------------------------------
# Limpieza de lo que nunca se envió
# ---------------------------------------------------------------------------
@PRUEBAS
@ARCHIVOS_TEMPORALES
class LimpiezaTests(Base):
    def subidos(self):
        viejo = ImagenMensaje.objects.get(pk=self.adjuntar(pdf('viejo.pdf')).json()['id'])
        nuevo = ImagenMensaje.objects.get(pk=self.adjuntar(pdf('nuevo.pdf')).json()['id'])
        enviado = ImagenMensaje.objects.get(pk=self.adjuntar(pdf('enviado.pdf')).json()['id'])
        self.enviar(documentos=[enviado.pk])
        ImagenMensaje.objects.filter(pk__in=[viejo.pk, enviado.pk]).update(creada=timezone.now() - timedelta(days=2))
        return viejo, nuevo, enviado

    def test_borra_lo_que_nunca_se_envio_de_hace_mas_de_un_dia(self):
        viejo, nuevo, enviado = self.subidos()
        archivo = Path(viejo.archivo.path)
        self.assertEqual(limpieza.limpiar_pendientes(), 1)
        self.assertFalse(ImagenMensaje.objects.filter(pk=viejo.pk).exists())
        self.assertFalse(archivo.exists())
        self.assertTrue(ImagenMensaje.objects.filter(pk__in=[nuevo.pk, enviado.pk]).count() == 2)   # reciente o ya enviado: se queda

    def test_corre_sola_una_vez_al_dia_al_abrir_la_mensajeria(self):
        viejo, _, _ = self.subidos()
        cache.delete(limpieza.LLAVE)
        self.client.get(BANDEJA)
        self.assertFalse(ImagenMensaje.objects.filter(pk=viejo.pk).exists())
        otro = ImagenMensaje.objects.get(pk=self.adjuntar(pdf('otro.pdf'), conversacion=reglas.conversacion_con(self.p(self.marta), self.p(self.beto))).json()['id'])
        ImagenMensaje.objects.filter(pk=otro.pk).update(creada=timezone.now() - timedelta(days=2))
        self.client.get(BANDEJA)   # ya corrió hoy
        self.assertTrue(ImagenMensaje.objects.filter(pk=otro.pk).exists())

    def test_el_comando(self):
        self.subidos()
        salida = io.StringIO()
        call_command('limpiar_mensajes', stdout=salida)
        self.assertIn('Archivos sin enviar borrados: 1', salida.getvalue())
        self.assertEqual(Conversacion.objects.count(), 1)
