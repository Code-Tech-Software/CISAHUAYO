"""Moderación de la mensajería (pedido del 2026-10-20): solo el administrador busca en todas las conversaciones y retira
mensajes; retirar los borra por completo (texto, formato, imágenes y archivos), sin copia ni marca, y las pantallas de
las dos personas se ponen al día al momento."""
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from CISAHUAYO import portales
from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase
from Usuarios import catalogo

from . import reglas, tiempo_real
from .models import Conversacion, ImagenMensaje, Mensaje
from .tests import ARCHIVOS_TEMPORALES, BANDEJA, Colegio, entrar_al_portal, png

BUSCAR = reverse('mensajes:moderacion')


@PRUEBAS
@ARCHIVOS_TEMPORALES
class ModeracionTests(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()
        self.con_ana = reglas.conversacion_con(self.p(self.marta), self.p(self.ana))
        self.con_rosa = reglas.conversacion_con(self.p(self.control), self.p(self.rosa))
        self.hola = reglas.enviar(self.con_ana, self.p(self.marta), 'Hola Ana, ¿terminaste la tarea?')
        self.grosero = reglas.enviar(self.con_ana, self.p(self.ana), 'Eres un tonto <b>maestra</b>')
        self.de_rosa = reglas.enviar(self.con_rosa, self.p(self.rosa), 'Mañana no llevo a Ana, está enferma')
        self.client.force_login(self.admin)

    def buscar(self, **filtros):
        return self.client.get(BUSCAR, filtros)

    def encontrados(self, **filtros):
        return [m.texto for m in self.buscar(**filtros).context['pagina']]

    def retirar(self, mensaje, cliente=None, **datos):
        with self.captureOnCommitCallbacks(execute=True):
            return (cliente or self.client).post(reverse('mensajes:moderacion_retirar', args=[mensaje.pk]), datos)

    # --- Quién modera ------------------------------------------------------------------------------------------------
    def test_el_permiso_es_exclusivo_del_administrador(self):
        self.assertEqual(catalogo.RESERVADOS['Mensajes.moderar'], catalogo.ADMINISTRADOR)
        self.assertIn('Mensajes.moderar', catalogo.reservados_para(es_prefectura=True))
        rutas = [BUSCAR, reverse('mensajes:moderacion_conversacion', args=[self.con_ana.pk]),
                 reverse('mensajes:moderacion_retirar', args=[self.grosero.pk])]
        for usuario in (self.control, self.marta, self.prefecto, self.sin_permisos):
            cliente = Client()
            cliente.force_login(usuario)
            for ruta in rutas:
                self.assertEqual(cliente.get(ruta).status_code, 403, (usuario, ruta))
            self.assertEqual(cliente.post(rutas[-1]).status_code, 403)
        # ni los portales (no son usuarios del sistema)
        ana = Client()
        entrar_al_portal(ana, portales.ESTUDIANTE, self.ana)
        self.assertEqual(ana.get(BUSCAR).status_code, 302)
        self.assertTrue(Mensaje.objects.filter(pk=self.grosero.pk).exists())

    def test_la_entrada_a_la_moderacion_solo_la_ve_el_administrador(self):
        self.assertContains(self.client.get(BANDEJA), f'href="{BUSCAR}"')
        marta = Client()
        marta.force_login(self.marta)
        self.assertNotContains(marta.get(BANDEJA), f'href="{BUSCAR}"')

    # --- Buscar ------------------------------------------------------------------------------------------------------
    def test_sin_criterios_no_se_lista_nada(self):
        respuesta = self.buscar()
        self.assertNotIn('pagina', respuesta.context)
        self.assertContains(respuesta, 'Busca los mensajes que quieres revisar')
        self.assertNotContains(respuesta, 'terminaste la tarea')

    def test_busca_por_persona_texto_y_fechas_en_todas_las_conversaciones(self):
        # Ana: lo que escribió y lo que recibió
        self.assertEqual(self.encontrados(persona='ana'), ['Eres un tonto <b>maestra</b>', 'Hola Ana, ¿terminaste la tarea?'])
        self.assertEqual(self.encontrados(persona='rosa mora'), ['Mañana no llevo a Ana, está enferma'])
        self.assertEqual(self.encontrados(persona='control'), ['Mañana no llevo a Ana, está enferma'])   # por usuario
        self.assertEqual(self.encontrados(texto='ANA'), ['Mañana no llevo a Ana, está enferma', 'Hola Ana, ¿terminaste la tarea?'])
        self.assertEqual(self.encontrados(texto='tonto maestra'), ['Eres un tonto <b>maestra</b>'])
        self.assertEqual(self.encontrados(persona='ana', texto='tarea'), ['Hola Ana, ¿terminaste la tarea?'])
        Mensaje.objects.filter(pk=self.hola.pk).update(creado=timezone.now() - timedelta(days=10))
        hoy = timezone.localdate()
        self.assertEqual(len(self.encontrados(desde=hoy.isoformat())), 2)
        self.assertEqual(self.encontrados(hasta=(hoy - timedelta(days=5)).isoformat()), ['Hola Ana, ¿terminaste la tarea?'])
        # el rango al revés se entiende igual
        self.assertEqual(len(self.encontrados(desde=hoy.isoformat(), hasta=(hoy - timedelta(days=20)).isoformat())), 3)
        self.assertContains(self.buscar(persona='nadie así'), 'No encontramos mensajes con esos filtros')

    def test_los_resultados_muestran_quien_a_quien_y_resaltan_sin_html(self):
        respuesta = self.buscar(texto='tonto')
        self.assertContains(respuesta, 'Eres un <mark>tonto</mark> &lt;b&gt;maestra&lt;/b&gt;', html=False)
        self.assertNotContains(respuesta, '<b>maestra</b>', html=False)
        fila = respuesta.context['pagina'][0]
        self.assertEqual((fila.autor, fila.para), (self.p(self.ana), self.p(self.marta)))
        self.assertContains(respuesta, reverse('mensajes:moderacion_retirar', args=[self.grosero.pk]))

    def test_resaltar_recorta_alrededor_de_la_coincidencia(self):
        texto = 'a ' * 200 + 'palabra final'
        fragmento = str(reglas.resaltar(texto, 'palabra'))
        self.assertTrue(fragmento.startswith('…'))
        self.assertIn('<mark>palabra</mark> final', fragmento)
        self.assertEqual(str(reglas.resaltar('<script>x</script>', '')), '&lt;script&gt;x&lt;/script&gt;')

    def test_la_conversacion_se_ve_completa_y_no_se_marca_como_leida(self):
        antes = reglas.no_leidos(self.p(self.marta))
        respuesta = self.client.get(reverse('mensajes:moderacion_conversacion', args=[self.con_ana.pk]), {'mensaje': self.grosero.pk})
        self.assertContains(respuesta, 'terminaste la tarea')
        self.assertContains(respuesta, 'Eres un tonto &lt;b&gt;maestra&lt;/b&gt;')
        self.assertContains(respuesta, 'is-destacado')
        self.assertEqual(respuesta.context['destacado'], self.grosero.pk)
        self.assertEqual(reglas.no_leidos(self.p(self.marta)), antes)
        self.assertEqual(self.client.get(reverse('mensajes:moderacion_conversacion', args=[99999])).status_code, 404)

    # --- Retirar -----------------------------------------------------------------------------------------------------
    def test_retirar_pide_confirmacion(self):
        respuesta = self.client.get(reverse('mensajes:moderacion_retirar', args=[self.grosero.pk]))
        self.assertContains(respuesta, '¿Retirar este mensaje?')
        self.assertContains(respuesta, 'No queda copia ni aviso de que existió')
        self.assertTrue(Mensaje.objects.filter(pk=self.grosero.pk).exists())

    def test_retirar_lo_borra_por_completo_para_las_dos_personas(self):
        volver = f'{BUSCAR}?texto=tonto'
        respuesta = self.retirar(self.grosero, volver=volver)
        self.assertRedirects(respuesta, volver, fetch_redirect_response=False)
        self.assertFalse(Mensaje.objects.filter(pk=self.grosero.pk).exists())
        self.assertFalse(Mensaje.objects.filter(texto__icontains='tonto').exists())
        # La conversación vuelve al mensaje anterior: vista previa, orden y lo que falta por leer
        self.con_ana.refresh_from_db()
        self.assertEqual(self.con_ana.ultimo_mensaje, self.hola)
        self.assertEqual(self.con_ana.actualizada, self.hola.creado)
        self.assertEqual(reglas.no_leidos(self.p(self.marta)), 0)
        marta = Client()
        marta.force_login(self.marta)
        self.assertNotContains(marta.get(BANDEJA), 'tonto')
        self.assertNotContains(marta.get(reverse('mensajes:conversacion', args=[self.con_ana.pk])), 'tonto')
        ana = Client()
        entrar_al_portal(ana, portales.ESTUDIANTE, self.ana)
        self.assertNotContains(ana.get(reverse('portal_estudiantes:mensajes:conversacion', args=[self.con_ana.pk])), 'tonto')
        # y la búsqueda ya no lo encuentra
        self.assertEqual(self.encontrados(texto='tonto'), [])

    def test_si_era_el_unico_la_conversacion_sale_de_la_bandeja(self):
        self.retirar(self.de_rosa)
        self.assertTrue(Conversacion.objects.filter(pk=self.con_rosa.pk, ultimo_mensaje__isnull=True).exists())
        self.assertEqual(reglas.bandeja(self.p(self.control)), [])
        self.assertEqual(reglas.bandeja(self.p(self.rosa)), [])
        # y se puede seguir conversando
        reglas.enviar(self.con_rosa, self.p(self.control), 'Gracias por avisar')
        self.assertEqual(len(reglas.bandeja(self.p(self.rosa))), 1)

    def test_retirar_borra_sus_imagenes_y_sus_archivos(self):
        marta = Client()
        marta.force_login(self.marta)
        subida = marta.post(reverse('mensajes:imagen_subir', args=[self.con_ana.pk]), {'imagen': png()}).json()
        marta.post(reverse('mensajes:enviar', args=[self.con_ana.pk]),
                   {'html': f'<p>Mira esto</p><p><img data-imagen="{subida["id"]}" alt=""></p>'})
        mensaje = Mensaje.objects.latest('pk')
        imagen = ImagenMensaje.objects.get(mensaje=mensaje)
        archivo = Path(imagen.archivo.path)
        self.assertTrue(archivo.exists())
        # quien modera la ve por su propia ruta, en la conversación y en la confirmación
        de_moderacion = reverse('mensajes:moderacion_imagen', args=[imagen.pk])
        self.assertContains(self.client.get(reverse('mensajes:moderacion_conversacion', args=[self.con_ana.pk])), f'src="{de_moderacion}"')
        self.assertContains(self.client.get(reverse('mensajes:moderacion_retirar', args=[mensaje.pk])), 'con su archivo adjunto')
        entregada = self.client.get(de_moderacion)
        self.assertEqual(entregada.status_code, 200)
        entregada.close()   # suelta el archivo (en Windows no se puede borrar mientras está abierto)

        self.retirar(mensaje)
        self.assertFalse(ImagenMensaje.objects.filter(pk=imagen.pk).exists())
        self.assertFalse(archivo.exists())
        self.assertEqual(self.client.get(de_moderacion).status_code, 404)
        self.assertEqual(marta.get(reverse('mensajes:imagen', args=[imagen.pk])).status_code, 404)

    def test_las_imagenes_sin_enviar_no_se_ven_en_la_moderacion(self):
        marta = Client()
        marta.force_login(self.marta)
        pendiente = marta.post(reverse('mensajes:imagen_subir', args=[self.con_ana.pk]), {'imagen': png()}).json()['id']
        self.assertEqual(self.client.get(reverse('mensajes:moderacion_imagen', args=[pendiente])).status_code, 404)

    def test_volver_solo_a_la_moderacion(self):
        respuesta = self.retirar(self.grosero, volver='https://otro-sitio.example/')
        self.assertRedirects(respuesta, BUSCAR, fetch_redirect_response=False)
        respuesta = self.retirar(self.hola, volver='//otro-sitio.example/mensajes/moderacion/')
        self.assertRedirects(respuesta, BUSCAR, fetch_redirect_response=False)

    def test_avisa_a_las_dos_personas_sin_nada_del_mensaje_retirado(self):
        enviados = []
        with patch.object(tiempo_real, '_enviar', side_effect=lambda pk, evento: enviados.append((pk, evento))):
            self.retirar(self.grosero)
        eventos = {pk: evento for pk, evento in enviados}
        self.assertEqual(set(eventos), {self.p(self.marta).pk, self.p(self.ana).pk})
        para_marta, para_ana = eventos[self.p(self.marta).pk], eventos[self.p(self.ana).pk]
        self.assertEqual(para_marta['type'], 'mensaje.retirado')
        datos = para_marta['datos']
        self.assertEqual((datos['conversacion'], datos['id'], datos['vacia']), (self.con_ana.pk, self.grosero.pk, False))
        self.assertEqual((datos['vista_previa'], datos['mio'], datos['pendientes'], datos['no_leidos']),
                         ('Hola Ana, ¿terminaste la tarea?', True, 0, 0))
        self.assertFalse(para_ana['datos']['mio'])
        self.assertNotIn('tonto', str(enviados))
