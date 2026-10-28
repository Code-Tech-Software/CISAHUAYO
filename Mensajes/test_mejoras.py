"""Mejoras de la mensajería del 2026-10-27: ponerse al día al reconectarse, resaltar lo buscado sin acentos, no marcar
como leído lo que no se vio, corregir con formato, la campana más ligera, el límite de mensajes seguidos, reportar
mensajes, el horario de atención, las notificaciones push y todas las conversaciones en la moderación."""
import json
from datetime import time, timedelta
from unittest.mock import MagicMock, patch

from django.db import connection
from django.test import Client, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from Alumnos.asistencias import NIVELES
from Alumnos.models import DiaNoLectivo
from CISAHUAYO import portales
from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase, lunes, momento

from . import reglas
from .context_processors import datos_de_avisos
from .models import ConfiguracionMensajes, Mensaje, Miembro, ReporteMensaje, SuscripcionPush
from .tests import BANDEJA, Colegio, entrar_al_portal

CLAVES = override_settings(VAPID_PUBLIC_KEY='BPublica', VAPID_PRIVATE_KEY='privada', VAPID_CONTACTO='https://colegio.example')
SUSCRIPCION = {'endpoint': 'https://push.example/abc', 'keys': {'p256dh': 'clave-p256dh', 'auth': 'clave-auth'}}


class Base(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()
        self.conversacion = reglas.conversacion_con(self.p(self.marta), self.p(self.ana))
        self.client.force_login(self.marta)
        self.ana_cliente = Client()
        entrar_al_portal(self.ana_cliente, portales.ESTUDIANTE, self.ana)

    def enviar(self, autor, texto, conversacion=None):
        with self.captureOnCommitCallbacks(execute=True):
            return reglas.enviar(conversacion or self.conversacion, self.p(autor), texto)

    def pantalla(self, cliente=None, espacio='mensajes', **parametros):
        return (cliente or self.client).get(reverse(f'{espacio}:conversacion', args=[self.conversacion.pk]), parametros)


# ---------------------------------------------------------------------------
# 1. Ponerse al día al reconectarse
# ---------------------------------------------------------------------------
@PRUEBAS
class PonerseAlDiaTests(Base):
    def nuevos(self, cliente=None, espacio='mensajes', **parametros):
        return (cliente or self.client).get(reverse(f'{espacio}:nuevos', args=[self.conversacion.pk]), parametros)

    def test_trae_lo_que_llego_despues_y_lo_que_se_retiro(self):
        primero = self.enviar(self.marta, 'Hola Ana')
        segundo = self.enviar(self.ana, 'Hola maestra')
        tercero = self.enviar(self.ana, 'Ya terminé la tarea')
        from .moderacion import retirar
        with self.captureOnCommitCallbacks(execute=True):
            retirar(Mensaje.objects.get(pk=segundo.pk))
        datos = self.nuevos(despues=primero.pk, desde=primero.pk).json()
        self.assertEqual([m['id'] for m in datos['mensajes']], [tercero.pk])
        self.assertEqual(datos['mensajes'][0]['texto'], 'Ya terminé la tarea')
        self.assertFalse(datos['mensajes'][0]['mio'])
        self.assertEqual(datos['existentes'], [primero.pk])   # el retirado ya no está
        self.assertTrue(datos['completos'])
        # Ana respondió: leyó lo de Marta
        self.assertEqual(datos['leido_hasta'], tercero.pk)
        self.assertTrue(datos['leido'].startswith('Leído'))

    def test_en_el_portal_con_sus_direcciones_y_solo_si_es_miembro(self):
        mensaje = self.enviar(self.marta, 'Recuerda el examen')
        datos = self.nuevos(cliente=self.ana_cliente, espacio='portal_estudiantes:mensajes', despues=0).json()
        self.assertEqual(datos['mensajes'][0]['id'], mensaje.pk)
        self.assertTrue(datos['mensajes'][0]['url'].startswith('/portal/estudiantes/'))
        beto = Client()
        entrar_al_portal(beto, portales.ESTUDIANTE, self.beto)
        self.assertEqual(self.nuevos(cliente=beto, espacio='portal_estudiantes:mensajes').status_code, 404)

    def test_de_cincuenta_en_cincuenta(self):
        autor = self.p(self.ana)
        Mensaje.objects.bulk_create([Mensaje(conversacion=self.conversacion, autor=autor, texto=f'Mensaje {n}') for n in range(55)])
        datos = self.nuevos(despues=0).json()
        self.assertEqual(len(datos['mensajes']), 50)
        self.assertFalse(datos['completos'])
        siguientes = self.nuevos(despues=datos['mensajes'][-1]['id']).json()
        self.assertEqual(len(siguientes['mensajes']), 5)
        self.assertTrue(siguientes['completos'])

    def test_la_pantalla_sabe_donde_pedirlo(self):
        self.assertContains(self.pantalla(), f'data-nuevos-url="{reverse("mensajes:nuevos", args=[self.conversacion.pk])}"')


# ---------------------------------------------------------------------------
# 2. Resaltar lo buscado sin acentos
# ---------------------------------------------------------------------------
class ResaltarTests(BaseTestCase):
    def test_sin_acentos_ni_mayusculas_y_recortado_alrededor(self):
        texto = 'Buenos días. ' * 20 + 'Mañana es la Excursión al museo, lleven lonche.'
        fragmento = str(reglas.resaltar(texto, 'excursion', largo=140))
        self.assertIn('<mark>Excursión</mark>', fragmento)
        self.assertTrue(fragmento.startswith('…'))
        self.assertIn('<mark>Mañana</mark>', str(reglas.resaltar('Mañana hay junta', 'MANANA')))

    def test_sigue_escapando_lo_demas(self):
        self.assertEqual(str(reglas.resaltar('<b>niño</b> & más', 'nino')), '&lt;b&gt;<mark>niño</mark>&lt;/b&gt; &amp; más')


# ---------------------------------------------------------------------------
# 3. Abrir un resultado de búsqueda no marca como leído lo más reciente
# ---------------------------------------------------------------------------
@PRUEBAS
class LeidoAlAbrirTests(Base):
    def test_abierta_en_un_mensaje_anterior_lo_nuevo_sigue_sin_leer(self):
        viejo = self.enviar(self.ana, 'La tarea de fracciones')
        Mensaje.objects.bulk_create([Mensaje(conversacion=self.conversacion, autor=self.p(self.ana), texto=f'Relleno {n}') for n in range(40)])
        Mensaje.objects.update(creado=timezone.now() - timedelta(hours=1))   # de hace rato: sin el límite por minuto
        nuevo = self.enviar(self.ana, '¿Mañana hay examen?')
        pantalla = self.pantalla(mensaje=viejo.pk)
        self.assertTrue(pantalla.context['hay_posteriores'])
        visto = pantalla.context['mensajes'][-1].pk
        miembro = Miembro.objects.get(conversacion=self.conversacion, participante=self.p(self.marta))
        self.assertEqual(miembro.ultimo_leido, visto)
        self.assertLess(visto, nuevo.pk)
        self.assertGreater(reglas.no_leidos(self.p(self.marta)), 0)
        self.assertIsNone(Mensaje.objects.get(pk=nuevo.pk).leido_en)   # Ana no lo ve como «Leído»
        # en los más recientes, todo queda leído
        self.pantalla()
        self.assertEqual(reglas.no_leidos(self.p(self.marta)), 0)


# ---------------------------------------------------------------------------
# 4. Corregir con formato
# ---------------------------------------------------------------------------
@PRUEBAS
class CorregirConFormatoTests(Base):
    def corregir(self, mensaje, **datos):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse('mensajes:editar', args=[mensaje.pk]), datos)

    def test_conserva_el_formato_y_lo_limpia(self):
        with self.captureOnCommitCallbacks(execute=True):
            mensaje = reglas.enviar(self.conversacion, self.p(self.marta), '', '<p><strong>Tarea</strong></p><ul><li>Página 10</li></ul>')
        self.assertIn('<strong>', mensaje.html)
        respuesta = self.corregir(mensaje, texto='Tarea\nPágina 12', html='<p><strong>Tarea</strong></p><ul><li>Página 12</li></ul><script>x()</script>')
        self.assertEqual(respuesta.status_code, 200)
        mensaje.refresh_from_db()
        self.assertIn('<strong>Tarea</strong>', mensaje.html)
        self.assertIn('<li>Página 12</li>', mensaje.html)
        self.assertNotIn('script', mensaje.html)
        self.assertIn('Página 12', mensaje.texto)
        self.assertIsNotNone(mensaje.editado)
        self.assertIn('<strong>Tarea</strong>', respuesta.json()['html'])   # la burbuja se pinta con su formato

    def test_sin_formato_sigue_siendo_texto(self):
        mensaje = self.enviar(self.marta, 'Hola Ana')
        self.corregir(mensaje, texto='Hola, Ana')
        mensaje.refresh_from_db()
        self.assertEqual((mensaje.texto, mensaje.html), ('Hola, Ana', ''))

    def test_solo_formato_vacio_no_se_guarda(self):
        with self.captureOnCommitCallbacks(execute=True):
            mensaje = reglas.enviar(self.conversacion, self.p(self.marta), '', '<p><strong>Tarea</strong></p>')
        respuesta = self.corregir(mensaje, texto='', html='<p><strong></strong></p>')
        self.assertEqual(respuesta.status_code, 400)


# ---------------------------------------------------------------------------
# 5. La campana más ligera
# ---------------------------------------------------------------------------
@PRUEBAS
class CampanaTests(Base):
    def test_sin_nada_sin_leer_es_una_sola_consulta(self):
        self.enviar(self.marta, 'Hola Ana')
        participante = self.p(self.marta)
        with CaptureQueriesContext(connection) as consultas:
            datos = datos_de_avisos(participante, 'mensajes')
        self.assertEqual(datos, {'no_leidos': 0, 'avisos': []})
        self.assertEqual(len(consultas), 1)

    def test_solo_las_conversaciones_con_algo_sin_leer(self):
        self.enviar(self.ana, 'Uno')
        self.enviar(self.ana, 'Dos')
        con_rosa = reglas.conversacion_con(self.p(self.marta), self.p(self.rosa))
        self.enviar(self.marta, 'Hola Rosa', conversacion=con_rosa)   # propio: no cuenta
        datos = datos_de_avisos(self.p(self.marta), 'mensajes')
        self.assertEqual(datos['no_leidos'], 2)
        self.assertEqual([a['conversacion'] for a in datos['avisos']], [self.conversacion.pk])
        self.assertEqual(datos['avisos'][0]['no_leidos'], 2)


# ---------------------------------------------------------------------------
# 10. Límite de mensajes seguidos
# ---------------------------------------------------------------------------
@PRUEBAS
class LimiteTests(Base):
    def test_diez_por_minuto_en_una_conversacion(self):
        for n in range(reglas.POR_MINUTO):
            self.enviar(self.ana, f'Mensaje {n}')
        respuesta = self.ana_cliente.post(reverse('portal_estudiantes:mensajes:enviar', args=[self.conversacion.pk]),
                                          {'texto': 'Otro más'}, HTTP_ACCEPT='application/json')
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('Espera un minuto', respuesta.json()['error'])
        # la otra persona sí puede contestar
        self.enviar(self.marta, 'Tranquila, ya te leí')
        # pasado el minuto, otra vez
        Mensaje.objects.filter(autor=self.p(self.ana)).update(creado=timezone.now() - timedelta(minutes=2))
        self.enviar(self.ana, 'Perdón')


# ---------------------------------------------------------------------------
# 6. Reportar mensajes
# ---------------------------------------------------------------------------
@PRUEBAS
class ReportarTests(Base):
    def setUp(self):
        super().setUp()
        self.grosero = self.enviar(self.marta, 'Eres muy lenta')
        self.de_ana = self.enviar(self.ana, 'Ya voy')

    def reportar(self, mensaje, cliente=None, espacio='portal_estudiantes:mensajes', motivo=''):
        return (cliente or self.ana_cliente).post(reverse(f'{espacio}:reportar', args=[mensaje.pk]), {'motivo': motivo},
                                                  HTTP_ACCEPT='application/json')

    def test_quien_lo_recibio_lo_reporta_una_vez(self):
        respuesta = self.reportar(self.grosero, motivo='  Me  insultó  ')
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('administrador', respuesta.json()['mensaje'])
        reporte = ReporteMensaje.objects.get()
        self.assertEqual((reporte.mensaje, reporte.participante, reporte.motivo), (self.grosero, self.p(self.ana), 'Me insultó'))
        self.reportar(self.grosero, motivo='Otra vez')   # se actualiza, no se duplica
        self.assertEqual(ReporteMensaje.objects.get().motivo, 'Otra vez')
        pantalla = self.pantalla(cliente=self.ana_cliente, espacio='portal_estudiantes:mensajes')
        self.assertContains(pantalla, 'data-reportado')
        self.assertContains(pantalla, 'burbuja__reportado')
        # quien lo escribió no ve nada
        self.assertNotContains(self.pantalla(), 'burbuja__reportado')

    def test_no_los_propios_ni_los_ajenos(self):
        self.assertEqual(self.reportar(self.de_ana).status_code, 400)
        beto = Client()
        entrar_al_portal(beto, portales.ESTUDIANTE, self.beto)
        self.assertEqual(self.reportar(self.grosero, cliente=beto).status_code, 404)
        self.assertFalse(ReporteMensaje.objects.exists())

    def test_el_personal_tambien(self):
        self.assertEqual(self.reportar(self.de_ana, cliente=self.client, espacio='mensajes').status_code, 200)
        self.assertEqual(ReporteMensaje.objects.get().participante, self.p(self.marta))

    def test_el_administrador_lo_ve_en_su_campana_y_en_la_moderacion(self):
        self.reportar(self.grosero, motivo='Me insultó')
        admin = Client()
        admin.force_login(self.admin)
        inicio = admin.get(reverse('inicio'))
        self.assertContains(inicio, 'data-reportados-pendientes="1"')
        self.assertContains(inicio, '1 mensaje reportado')
        lista = admin.get(reverse('mensajes:moderacion_reportados'))
        self.assertContains(lista, 'Eres muy lenta')
        self.assertContains(lista, '«Me insultó»')
        self.assertContains(lista, 'pill__count">1<')
        conversacion = admin.get(reverse('mensajes:moderacion_conversacion', args=[self.conversacion.pk]))
        self.assertContains(conversacion, 'Reportado')
        # la docente (sin moderar) no ve nada de esto
        self.assertNotContains(self.client.get(reverse('inicio')), 'data-reportados-pendientes')
        self.assertEqual(self.client.get(reverse('mensajes:moderacion_reportados')).status_code, 403)

    def test_descartar_deja_el_mensaje_y_retirar_borra_todo(self):
        self.reportar(self.grosero)
        admin = Client()
        admin.force_login(self.admin)
        volver = reverse('mensajes:moderacion_reportados')
        respuesta = admin.post(reverse('mensajes:moderacion_descartar', args=[self.grosero.pk]), {'volver': volver})
        self.assertRedirects(respuesta, volver)
        self.assertFalse(ReporteMensaje.objects.exists())
        self.assertTrue(Mensaje.objects.filter(pk=self.grosero.pk).exists())
        self.reportar(self.grosero)
        with self.captureOnCommitCallbacks(execute=True):
            admin.post(reverse('mensajes:moderacion_retirar', args=[self.grosero.pk]), {'volver': volver})
        self.assertFalse(Mensaje.objects.filter(pk=self.grosero.pk).exists())
        self.assertFalse(ReporteMensaje.objects.exists())   # sin rastro
        self.assertEqual(self.client.post(reverse('mensajes:moderacion_descartar', args=[self.de_ana.pk])).status_code, 403)


# ---------------------------------------------------------------------------
# 7. Horario de atención
# ---------------------------------------------------------------------------
@PRUEBAS
class HorarioTests(Base):
    def aviso(self, de, para, cuando):
        return reglas.aviso_fuera_de_horario(self.p(de), self.p(para), cuando)

    def test_fuera_de_horario_avisa_a_estudiantes_y_tutores(self):
        self.assertEqual(self.aviso(self.ana, self.marta, momento(10)), '')                 # lunes a las 10
        self.assertIn('fuera del horario', self.aviso(self.ana, self.marta, momento(21)))   # de noche
        self.assertIn('de 7:00 a 15:00', self.aviso(self.rosa, self.marta, momento(6, 30)))
        sabado = lunes() + timedelta(days=5)
        self.assertIn('fuera del horario', self.aviso(self.ana, self.marta, momento(10, fecha=sabado)))
        self.assertEqual(self.aviso(self.marta, self.ana, momento(21)), '')                 # al personal no

    def test_en_un_dia_sin_clases_de_todo_el_colegio(self):
        DiaNoLectivo.objects.bulk_create([DiaNoLectivo(fecha=lunes(), nivel=nivel, motivo='Consejo técnico') for nivel in NIVELES])
        self.assertIn('fuera del horario', self.aviso(self.ana, self.marta, momento(10)))

    def test_se_puede_apagar_y_cambiar_el_horario(self):
        configuracion = ConfiguracionMensajes.actual()
        configuracion.hora_fin = time(22, 0)
        configuracion.save()
        self.assertEqual(self.aviso(self.ana, self.marta, momento(21)), '')
        configuracion.avisar_fuera_de_horario = False
        configuracion.save()
        self.assertEqual(self.aviso(self.ana, self.marta, momento(23)), '')

    def test_se_ve_en_la_conversacion_del_portal(self):
        with patch('django.utils.timezone.now', return_value=momento(21)):
            pantalla = self.pantalla(cliente=self.ana_cliente, espacio='portal_estudiantes:mensajes')
        self.assertContains(pantalla, 'chat__horario')
        with patch('django.utils.timezone.now', return_value=momento(10)):
            self.assertNotContains(self.pantalla(cliente=self.ana_cliente, espacio='portal_estudiantes:mensajes'), 'chat__horario')

    def test_ajustes_solo_para_el_administrador(self):
        url = reverse('ajustes_mensajes')
        self.assertEqual(self.client.get(url).status_code, 403)
        admin = Client()
        admin.force_login(self.admin)
        self.assertContains(admin.get(url), 'Horario de atención')
        respuesta = admin.post(url, {'avisar_fuera_de_horario': 'on', 'hora_inicio': '08:00', 'hora_fin': '14:00', 'dias_para_responder': '3'})
        self.assertRedirects(respuesta, url)
        configuracion = ConfiguracionMensajes.actual()
        self.assertEqual((configuracion.hora_inicio.hour, configuracion.hora_fin.hour, configuracion.dias_para_responder, configuracion.modificado_por), (8, 14, 3, self.admin))
        respuesta = admin.post(url, {'hora_inicio': '15:00', 'hora_fin': '14:00'})
        self.assertContains(respuesta, 'Debe ser después de la hora de inicio.')
        self.assertContains(admin.get(reverse('ajustes:inicio')), url)   # su pestaña en Ajustes


# ---------------------------------------------------------------------------
# 8. Notificaciones push
# ---------------------------------------------------------------------------
@PRUEBAS
class PushTests(Base):
    def suscribir(self, cliente=None, espacio='portal_estudiantes:mensajes', datos=None):
        return (cliente or self.ana_cliente).post(reverse(f'{espacio}:push'), json.dumps(datos or SUSCRIPCION),
                                                  content_type='application/json')

    def test_sin_claves_no_se_ofrecen(self):
        self.assertEqual(self.suscribir().status_code, 404)
        self.assertNotContains(self.client.get(BANDEJA), 'data-push-clave')

    @CLAVES
    def test_guarda_la_suscripcion_del_navegador(self):
        self.assertEqual(self.suscribir().status_code, 200)
        suscripcion = SuscripcionPush.objects.get()
        self.assertEqual((suscripcion.participante, suscripcion.p256dh), (self.p(self.ana), 'clave-p256dh'))
        self.assertEqual(self.suscribir(datos={'endpoint': 'http://inseguro', 'keys': {}}).status_code, 400)
        # el mismo navegador con otra cuenta: pasa a esa cuenta
        self.suscribir(cliente=self.client, espacio='mensajes')
        self.assertEqual(SuscripcionPush.objects.get().participante, self.p(self.marta))
        self.assertContains(self.client.get(BANDEJA), 'data-push-clave="BPublica"')

    @CLAVES
    def test_avisa_a_la_otra_persona_y_borra_las_vencidas(self):
        self.suscribir()
        self.suscribir(cliente=self.client, espacio='mensajes', datos={**SUSCRIPCION, 'endpoint': 'https://push.example/marta'})
        with patch('pywebpush.webpush') as webpush:
            self.enviar(self.marta, 'Mañana hay examen')
        self.assertEqual(webpush.call_count, 1)   # solo a Ana: a Marta no se le avisa de su propio mensaje
        llamada = webpush.call_args.kwargs
        self.assertEqual(llamada['subscription_info']['endpoint'], SUSCRIPCION['endpoint'])
        carga = json.loads(llamada['data'])
        self.assertEqual(carga['texto'], 'Mañana hay examen')
        self.assertEqual(carga['url'], reverse('portal_estudiantes:mensajes:conversacion', args=[self.conversacion.pk]))
        self.assertEqual(llamada['vapid_claims'], {'sub': 'https://colegio.example'})
        from pywebpush import WebPushException
        with patch('pywebpush.webpush', side_effect=WebPushException('vencida', response=MagicMock(status_code=410))):
            self.enviar(self.marta, 'Otro aviso')
        self.assertFalse(SuscripcionPush.objects.filter(endpoint=SUSCRIPCION['endpoint']).exists())

    @CLAVES
    def test_al_cerrar_sesion_ese_navegador_deja_de_recibirlos(self):
        self.suscribir()
        self.ana_cliente.post(reverse('portal_estudiantes:salir'))
        self.assertFalse(SuscripcionPush.objects.exists())
        self.suscribir(cliente=self.client, espacio='mensajes')
        self.client.post(reverse('logout'))
        self.assertFalse(SuscripcionPush.objects.exists())

    def test_el_service_worker_y_el_manifiesto(self):
        anonimo = Client()
        sw = anonimo.get('/sw.js')
        self.assertEqual(sw['Content-Type'], 'application/javascript; charset=utf-8')
        self.assertEqual(sw['Service-Worker-Allowed'], '/')
        self.assertContains(sw, "addEventListener('push'")
        manifiesto = anonimo.get('/manifest.webmanifest')
        self.assertEqual(manifiesto.json()['display'], 'standalone')
        self.assertContains(self.client.get(BANDEJA), 'rel="manifest"')


# ---------------------------------------------------------------------------
# 11. Todas las conversaciones en la moderación
# ---------------------------------------------------------------------------
@PRUEBAS
class TodasLasConversacionesTests(Base):
    def setUp(self):
        super().setUp()
        self.enviar(self.marta, 'Hola Ana')
        self.con_rosa = reglas.conversacion_con(self.p(self.marta), self.p(self.rosa))
        self.enviar(self.rosa, 'Buenas tardes, maestra', conversacion=self.con_rosa)
        self.entre_personal = reglas.conversacion_con(self.p(self.marta), self.p(self.control))
        self.enviar(self.control, 'Junta a las 2', conversacion=self.entre_personal)
        reglas.conversacion_con(self.p(self.marta), self.p(self.beto))   # sin mensajes: no aparece
        self.admin_cliente = Client()
        self.admin_cliente.force_login(self.admin)

    def lista(self, **filtros):
        return [c.pk for c in self.admin_cliente.get(reverse('mensajes:moderacion_conversaciones'), filtros).context['pagina']]

    def test_todas_y_por_con_quien(self):
        self.assertEqual(self.lista(), [self.entre_personal.pk, self.con_rosa.pk, self.conversacion.pk])
        self.assertEqual(self.lista(tipo='ESTUDIANTE'), [self.conversacion.pk])
        self.assertEqual(self.lista(tipo='TUTOR'), [self.con_rosa.pk])
        self.assertEqual(self.lista(tipo='PERSONAL'), [self.entre_personal.pk])
        self.assertEqual(self.lista(persona='Rosa'), [self.con_rosa.pk])
        pagina = self.admin_cliente.get(reverse('mensajes:moderacion_conversaciones'))
        self.assertContains(pagina, 'Junta a las 2')
        self.assertContains(pagina, reverse('mensajes:moderacion_conversacion', args=[self.con_rosa.pk]))

    def test_solo_el_administrador(self):
        self.assertEqual(self.client.get(reverse('mensajes:moderacion_conversaciones')).status_code, 403)
