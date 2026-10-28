"""Pendientes de la mensajería (2026-10-27): el filtro «Sin leer» de la bandeja, dejar una conversación «no leída» y, en
la moderación, las conversaciones que esperan respuesta. Los borradores viven en el navegador (static/js/mensajes.js)."""
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from Alumnos.asistencias import NIVELES
from Alumnos.models import DiaNoLectivo
from CISAHUAYO.pruebas import PRUEBAS

from . import moderacion, reglas
from .context_processors import datos_de_avisos
from .models import ConfiguracionMensajes, Conversacion, Mensaje
from .test_mejoras import Base


def sin_clases(fecha):
    DiaNoLectivo.objects.bulk_create([DiaNoLectivo(fecha=fecha, nivel=nivel, motivo='Consejo técnico') for nivel in NIVELES])


# ---------------------------------------------------------------------------
# El filtro «Sin leer» de la bandeja
# ---------------------------------------------------------------------------
@PRUEBAS
class SinLeerTests(Base):
    def setUp(self):
        super().setUp()
        self.con_rosa = reglas.conversacion_con(self.p(self.marta), self.p(self.rosa))
        self.enviar(self.marta, 'Hola Ana')
        self.enviar(self.rosa, 'Buenas tardes, maestra', conversacion=self.con_rosa)   # sin leer para Marta

    def lista(self, **parametros):
        return [c.pk for c in self.client.get(reverse('mensajes:inicio'), parametros).context['bandeja']]

    def test_solo_las_que_tienen_algo_sin_leer(self):
        self.assertEqual(self.lista(), [self.con_rosa.pk, self.conversacion.pk])
        self.assertEqual(self.lista(sin_leer='1'), [self.con_rosa.pk])

    def test_la_abierta_se_queda_y_los_enlaces_conservan_el_filtro(self):
        url = reverse('mensajes:conversacion', args=[self.con_rosa.pk])
        respuesta = self.client.get(url, {'sin_leer': '1'})
        self.assertEqual([c.pk for c in respuesta.context['bandeja']], [self.con_rosa.pk])   # ya leída, pero abierta
        self.assertContains(respuesta, f'{url}?sin_leer=1')
        self.assertContains(respuesta, 'data-sin-leer')
        self.assertEqual(self.lista(sin_leer='1'), [])   # fuera de ella, ya no queda nada sin leer
        self.assertContains(self.client.get(reverse('mensajes:inicio'), {'sin_leer': '1'}), 'No tienes conversaciones sin leer.')

    def test_las_siguientes_con_el_filtro(self):
        datos = self.client.get(reverse('mensajes:conversaciones'), {'sin_leer': '1'}).json()
        self.assertIn(f'{reverse("mensajes:conversacion", args=[self.con_rosa.pk])}?sin_leer=1', datos['html'])
        self.assertNotIn(reverse('mensajes:conversacion', args=[self.conversacion.pk]), datos['html'])

    def test_tambien_en_el_portal(self):
        self.enviar(self.marta, 'Mañana hay examen')
        respuesta = self.ana_cliente.get(reverse('portal_estudiantes:mensajes:inicio'), {'sin_leer': '1'})
        self.assertEqual([c.pk for c in respuesta.context['bandeja']], [self.conversacion.pk])


# ---------------------------------------------------------------------------
# Dejar una conversación «no leída»
# ---------------------------------------------------------------------------
@PRUEBAS
class MarcarNoLeidaTests(Base):
    def setUp(self):
        super().setUp()
        self.mensaje = self.enviar(self.ana, 'Maestra, ¿mañana hay examen?')
        self.pantalla()   # Marta la abre: queda leída

    def marcar(self, cliente=None, espacio='mensajes', **datos):
        return (cliente or self.client).post(reverse(f'{espacio}:no_leida', args=[self.conversacion.pk]), datos)

    def test_cuenta_como_pendiente_sin_cambiar_lo_que_ve_la_otra_persona(self):
        marta = self.p(self.marta)
        self.assertEqual(reglas.no_leidos(marta), 0)
        self.assertRedirects(self.marcar(), reverse('mensajes:inicio'), fetch_redirect_response=False)
        self.assertEqual(reglas.no_leidos(marta), 1)
        self.assertEqual(reglas.sin_leer_por_conversacion(marta), {self.conversacion.pk: 1})
        self.assertEqual([a['conversacion'] for a in datos_de_avisos(marta, 'mensajes')['avisos']], [self.conversacion.pk])
        # Ana sigue viendo su mensaje como leído
        self.assertEqual(reglas.leido_por_el_otro(self.conversacion, self.p(self.ana)), self.mensaje.pk)

    def test_al_abrirla_o_al_escribir_deja_de_estarlo(self):
        self.marcar()
        self.pantalla()
        self.assertEqual(reglas.no_leidos(self.p(self.marta)), 0)
        self.marcar()
        self.enviar(self.marta, 'No, es el jueves')
        self.assertEqual(reglas.no_leidos(self.p(self.marta)), 0)

    def test_con_mensajes_nuevos_cuentan_los_nuevos(self):
        self.marcar()
        self.enviar(self.ana, 'Y otra cosa')
        self.enviar(self.ana, 'Gracias')
        self.assertEqual(reglas.sin_leer_por_conversacion(self.p(self.marta)), {self.conversacion.pk: 2})

    def test_vuelve_al_filtro_y_ahi_aparece(self):
        respuesta = self.marcar(sin_leer='1')
        self.assertRedirects(respuesta, reverse('mensajes:inicio') + '?sin_leer=1', fetch_redirect_response=False)
        lista = self.client.get(reverse('mensajes:inicio'), {'sin_leer': '1'}).context['bandeja']
        self.assertEqual([(c.pk, c.no_leidos) for c in lista], [(self.conversacion.pk, 1)])

    def test_avisa_a_sus_otras_pestanas(self):
        with patch('Mensajes.tiempo_real._enviar') as enviar, self.captureOnCommitCallbacks(execute=True):
            self.marcar()
        participante, evento = enviar.call_args.args
        self.assertEqual(participante, self.p(self.marta).pk)
        self.assertEqual(evento['type'], 'mensajes.resumen')
        self.assertEqual((evento['datos']['pendientes'], evento['datos']['no_leidos']), (1, 1))
        # Al abrirla otra vez, sus pestañas la ven sin pendientes
        with patch('Mensajes.tiempo_real._enviar') as enviar, self.captureOnCommitCallbacks(execute=True):
            self.pantalla()
        self.assertEqual(enviar.call_args.args[1]['datos']['pendientes'], 0)

    def test_desde_el_portal(self):
        self.enviar(self.marta, 'No, es el jueves')
        self.marcar(cliente=self.ana_cliente, espacio='portal_estudiantes:mensajes')
        self.assertEqual(reglas.no_leidos(self.p(self.ana)), 1)

    def test_sin_mensajes_no_y_solo_en_las_propias(self):
        vacia = reglas.conversacion_con(self.p(self.marta), self.p(self.beto))
        respuesta = self.client.post(reverse('mensajes:no_leida', args=[vacia.pk]), follow=True)
        self.assertContains(respuesta, 'todavía no tiene mensajes')
        ajena = reglas.conversacion_con(self.p(self.control), self.p(self.tomas))
        self.assertEqual(self.client.post(reverse('mensajes:no_leida', args=[ajena.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('mensajes:no_leida', args=[self.conversacion.pk])).status_code, 405)


# ---------------------------------------------------------------------------
# Moderación › Todas las conversaciones › «Esperando respuesta»
# ---------------------------------------------------------------------------
@PRUEBAS
class EsperandoRespuestaTests(Base):
    MIERCOLES = date(2026, 10, 28)

    def setUp(self):
        super().setUp()
        self.con_rosa = reglas.conversacion_con(self.p(self.marta), self.p(self.rosa))
        self.entre_personal = reglas.conversacion_con(self.p(self.marta), self.p(self.control))
        self.con_tomas = reglas.conversacion_con(self.p(self.control), self.p(self.tomas))
        self.admin_cliente = Client()
        self.admin_cliente.force_login(self.admin)

    def escrito(self, conversacion, autor, cuando):
        mensaje = self.enviar(autor, 'Hola', conversacion=conversacion)
        Mensaje.objects.filter(pk=mensaje.pk).update(creado=cuando)
        Conversacion.objects.filter(pk=conversacion.pk).update(actualizada=cuando)

    def pagina(self, **filtros):
        return self.admin_cliente.get(reverse('mensajes:moderacion_conversaciones'), filtros)

    def test_los_dias_habiles(self):
        def limite(hoy):
            return timezone.localtime(moderacion.limite_de_espera(2, hoy=hoy)).date()
        martes, sabado = self.MIERCOLES - timedelta(days=1), self.MIERCOLES + timedelta(days=3)
        self.assertEqual((self.MIERCOLES.weekday(), sabado.weekday()), (2, 5))
        self.assertEqual(limite(self.MIERCOLES), martes)                     # un mensaje del lunes ya espera
        self.assertEqual(limite(martes), martes - timedelta(days=1))         # uno del viernes, desde el martes
        self.assertEqual(limite(sabado), self.MIERCOLES + timedelta(days=1))  # el fin de semana no cuenta
        sin_clases(martes - timedelta(days=1))                                 # el lunes, sin clases en todo el colegio
        self.assertEqual(limite(martes), martes - timedelta(days=4))          # el viernes anterior

    def test_cuantos_dias_lleva_cada_una(self):
        viernes = self.MIERCOLES - timedelta(days=5)
        conversacion = SimpleNamespace(pk=1, actualizada=timezone.make_aware(datetime.combine(viernes, time(10, 0))))
        martes = self.MIERCOLES - timedelta(days=1)
        self.assertEqual(moderacion.con_espera([conversacion], hoy=martes)[0].dias_esperando, 2)   # lunes y martes
        sin_clases(martes - timedelta(days=1))
        self.assertEqual(moderacion.con_espera([conversacion], hoy=martes)[0].dias_esperando, 1)

    def test_las_de_estudiantes_y_tutores_sin_contestar(self):
        hace_diez = timezone.now() - timedelta(days=10)
        self.escrito(self.con_rosa, self.rosa, hace_diez)
        self.escrito(self.conversacion, self.ana, hace_diez - timedelta(days=1))   # la que más lleva: primero
        self.escrito(self.entre_personal, self.control, hace_diez)                  # entre el personal: no
        con_beto = reglas.conversacion_con(self.p(self.marta), self.p(self.beto))
        self.escrito(con_beto, self.beto, hace_diez)
        self.escrito(con_beto, self.marta, hace_diez + timedelta(days=1))           # ya le contestaron
        respuesta = self.pagina(estado='esperando')
        self.assertEqual([c.pk for c in respuesta.context['pagina']], [self.conversacion.pk, self.con_rosa.pk])
        self.assertGreaterEqual(min(c.dias_esperando for c in respuesta.context['pagina']), 2)
        self.assertContains(respuesta, 'Sin respuesta:')
        # Un mensaje reciente de la estudiante: todavía no espera
        self.enviar(self.ana, '¿Me puede contestar?')
        self.assertEqual([c.pk for c in self.pagina(estado='esperando').context['pagina']], [self.con_rosa.pk])

    def test_el_aviso_y_los_dias_de_ajustes(self):
        self.escrito(self.con_tomas, self.tomas, timezone.now() - timedelta(days=10))
        respuesta = self.pagina()
        self.assertEqual(respuesta.context['esperan'], 1)
        self.assertContains(respuesta, '1 conversación espera respuesta')
        self.assertContains(respuesta, '?estado=esperando')
        configuracion = ConfiguracionMensajes.actual()
        configuracion.dias_para_responder = 15
        configuracion.save()
        self.assertEqual(self.pagina().context['esperan'], 0)
        self.assertContains(self.pagina(estado='esperando'), 'Ninguna conversación espera respuesta')

    def test_dias_para_responder_entre_1_y_15(self):
        datos = {'avisar_fuera_de_horario': 'on', 'hora_inicio': '07:00', 'hora_fin': '15:00'}
        url = reverse('ajustes_mensajes')
        self.assertEqual(self.admin_cliente.post(url, {**datos, 'dias_para_responder': '0'}).status_code, 200)
        self.assertEqual(self.admin_cliente.post(url, {**datos, 'dias_para_responder': '16'}).status_code, 200)
        self.assertRedirects(self.admin_cliente.post(url, {**datos, 'dias_para_responder': '5'}), url)
        self.assertEqual(ConfiguracionMensajes.actual().dias_para_responder, 5)

    def test_solo_el_administrador(self):
        self.assertEqual(self.client.get(reverse('mensajes:moderacion_conversaciones'), {'estado': 'esperando'}).status_code, 403)
