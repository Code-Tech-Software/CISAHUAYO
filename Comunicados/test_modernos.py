"""Comunicados modernos (2026-10-27): enlaces que se tocan, de cuál hijo trata, avisos en segundo plano y push, respuestas
(Enterado, autorización y encuesta), corregir, programar, texto con formato e imágenes, usar como base, fijar y
categorías, eventos en la agenda, recordar a los pendientes, lectura por grupo y Excel, y el personal como destinatario.
La revisión antes de enviar es del navegador (static/js/comunicados-form.js)."""
import json
import uuid
from datetime import time, timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from CISAHUAYO import portales
from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase, crear_usuario
from Usuarios.models import Rol

from . import avisos, reglas, tiempo_real
from .alcance import alcance_de
from .models import Adjunto, Comunicado, Destinatario, ImagenComunicado
from .tests import ARCHIVOS_TEMPORALES, CREAR, Colegio, entrar_al_portal, pdf, png

JSON = {'HTTP_ACCEPT': 'application/json'}


class Base(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()
        self.client.force_login(self.laura)

    def publicar(self, usuario=None, seleccion=None, **campos):
        datos = {'titulo': 'Reunión de familias', 'descripcion': 'Los esperamos.', 'urgente': False, 'expira': None}
        datos.update(campos)
        with self.captureOnCommitCallbacks(execute=True):
            comunicado, _ = reglas.enviar(
                usuario or self.laura, clave_envio=uuid.uuid4(),
                seleccion=seleccion or {Destinatario.TUTOR: {self.ana.pk}, Destinatario.ESTUDIANTE: {self.lucia.pk}}, **datos)
        return comunicado

    def portal(self, tutor=None):
        cliente = Client()
        entrar_al_portal(cliente, portales.TUTOR, tutor or self.ana)
        return cliente

    def url_portal(self, nombre, comunicado):
        return reverse(f'portal_tutores:comunicados:{nombre}', args=[comunicado.pk])

    def copia_de(self, comunicado, tutor=None):
        return Destinatario.objects.get(comunicado=comunicado, tutor=tutor or self.ana)


# ---------------------------------------------------------------------------
# 1 y 2. Enlaces y de cuál hijo trata
# ---------------------------------------------------------------------------
@PRUEBAS
class EnlacesYParaQuienTests(Base):
    def test_las_direcciones_del_texto_se_vuelven_enlaces(self):
        comunicado = self.publicar(descripcion='Inscríbanse en https://forms.example.com/x?a=1&b=2. Gracias.')
        respuesta = self.portal().get(self.url_portal('recibido', comunicado))
        self.assertContains(respuesta, '<a href="https://forms.example.com/x?a=1&amp;b=2" target="_blank" '
                                       'rel="noopener noreferrer nofollow">https://forms.example.com/x?a=1&amp;b=2</a>.')

    def test_el_formato_se_limpia_en_el_servidor(self):
        comunicado = self.publicar(descripcion='', html='<p><strong>Hola</strong> <a href="javascript:alert(1)">aquí</a></p>'
                                                        '<script>alert(2)</script><ul><li>Uno</li></ul>')
        self.assertIn('<strong>Hola</strong>', comunicado.html)
        self.assertNotIn('script', comunicado.html)
        self.assertNotIn('javascript', comunicado.html)
        self.assertEqual(comunicado.descripcion.split('\n')[0], 'Hola aquí')
        self.assertContains(self.portal().get(self.url_portal('recibido', comunicado)), '<li>Uno</li>')

    def test_los_hijos_se_nombran_como_se_dice(self):
        from .alcance import _lista
        self.assertEqual(_lista(['Ana'], 3), 'Ana')
        self.assertEqual(_lista(['Ana', 'Luis'], 3), 'Ana y Luis')
        self.assertEqual(_lista(['Ana', 'Luis', 'Sofía'], 3), 'Ana, Luis y Sofía')
        self.assertEqual(_lista(['A', 'B', 'C', 'D', 'E'], 3), 'A, B, C y 2 más')

    def test_el_tutor_sabe_de_cual_de_sus_hijos_trata(self):
        comunicado = self.publicar()
        cliente = self.portal()
        self.assertContains(cliente.get(reverse('portal_tutores:comunicados:inicio')), 'Sobre: Lucía Herrera Campos (2.º A)')
        self.assertContains(cliente.get(self.url_portal('recibido', comunicado)), 'Lucía Herrera Campos (2.º A)')


# ---------------------------------------------------------------------------
# 3 y 4. Avisos en segundo plano y notificaciones push
# ---------------------------------------------------------------------------
@PRUEBAS
class AvisosTests(Base):
    def test_salen_en_un_hilo_aparte(self):
        with override_settings(COMUNICADOS_EN_SEGUNDO_PLANO=True), patch('Comunicados.avisos.threading.Thread') as hilo:
            self.publicar()
        hilo.assert_called_once()
        hilo.return_value.start.assert_called_once()

    def test_push_al_telefono_con_prioridad_si_es_urgente(self):
        from Mensajes import reglas as mensajeria
        from Mensajes.models import SuscripcionPush
        SuscripcionPush.objects.create(participante=mensajeria.de_portal(portales.TUTOR, self.ana), endpoint='https://push.example/ana',
                                       p256dh='clave', auth='secreto')
        claves = override_settings(VAPID_PUBLIC_KEY='B', VAPID_PRIVATE_KEY='privada', VAPID_CONTACTO='https://colegio.example')
        with claves, patch('pywebpush.webpush') as webpush:
            self.publicar(titulo='Suspensión de clases', urgente=True)
        argumentos = webpush.call_args.kwargs
        carga = json.loads(argumentos['data'])
        self.assertEqual(carga['titulo'], 'Urgente: Suspensión de clases')
        self.assertTrue(carga['url'].startswith('/portal/tutores/comunicados/'))
        self.assertTrue(carga['urgente'])
        self.assertEqual(argumentos['headers'], {'Urgency': 'high'})


# ---------------------------------------------------------------------------
# 5. Respuestas
# ---------------------------------------------------------------------------
@PRUEBAS
class RespuestasTests(Base):
    def test_enterado_cuenta_tambien_como_lectura(self):
        comunicado = self.publicar(respuesta=Comunicado.ENTERADO)
        cliente = self.portal()
        self.assertContains(cliente.get(self.url_portal('recibido', comunicado)), 'Confirma que lo leíste')
        respuesta = cliente.post(self.url_portal('responder', comunicado), {'respuesta': 'enterado'})
        self.assertRedirects(respuesta, self.url_portal('recibido', comunicado), fetch_redirect_response=False)
        copia = self.copia_de(comunicado)
        self.assertEqual((copia.respuesta, copia.leido), (Destinatario.RESPUESTA_ENTERADO, True))
        seguimiento = self.client.get(reverse('comunicados:detalle', args=[comunicado.pk]))
        self.assertEqual(seguimiento.context['respuestas']['filas'][0]['cuantos'], 1)
        self.assertEqual(seguimiento.context['respuestas']['sin_responder'], 1)   # Lucía

    def test_una_autorizacion_se_puede_cambiar(self):
        comunicado = self.publicar(respuesta=Comunicado.AUTORIZACION, pregunta='¿Autoriza la excursión?')
        cliente = self.portal()
        cliente.post(self.url_portal('responder', comunicado), {'respuesta': 'si'})
        datos = cliente.post(self.url_portal('responder', comunicado), {'respuesta': 'no'}, **JSON).json()
        self.assertEqual(datos['respuesta'], 'No autoriza')
        self.assertEqual(self.copia_de(comunicado).respuesta, Destinatario.RESPUESTA_NO)
        filas = reglas.resumen_de_respuestas(comunicado, list(comunicado.destinatarios.all()))['filas']
        self.assertEqual([(f['texto'], f['cuantos']) for f in filas], [('Sí autoriza', 0), ('No autoriza', 1)])

    def test_una_encuesta_pide_su_pregunta_y_dos_opciones_distintas(self):
        with self.assertRaisesMessage(reglas.EnvioRechazado, 'pregunta'):
            self.publicar(respuesta=Comunicado.ENCUESTA, opciones=['Lunes', 'Martes'])
        with self.assertRaisesMessage(reglas.EnvioRechazado, 'opciones distintas'):
            self.publicar(respuesta=Comunicado.ENCUESTA, pregunta='¿Qué día?', opciones=['Lunes', ' lunes '])
        comunicado = self.publicar(respuesta=Comunicado.ENCUESTA, pregunta='¿Qué día?', opciones=['Lunes', 'Martes', 'lunes'])
        self.assertEqual([o.texto for o in comunicado.opciones.all()], ['Lunes', 'Martes'])
        martes = comunicado.opciones.get(texto='Martes')
        cliente = self.portal()
        self.assertEqual(cliente.post(self.url_portal('responder', comunicado), {'respuesta': '999999'}, **JSON).status_code, 400)
        cliente.post(self.url_portal('responder', comunicado), {'respuesta': str(martes.pk)})
        self.assertEqual(self.copia_de(comunicado).texto_de_respuesta, 'Martes')

    def test_por_responder_en_la_lista_y_un_caducado_ya_no_se_responde(self):
        comunicado = self.publicar(respuesta=Comunicado.ENTERADO, expira=timezone.now() + timedelta(hours=1))
        cliente = self.portal()
        lista = reverse('portal_tutores:comunicados:inicio')
        self.assertContains(cliente.get(lista, {'estado': 'por_responder'}), 'Reunión de familias')
        cliente.post(self.url_portal('responder', comunicado), {'respuesta': 'enterado'})
        self.assertNotContains(cliente.get(lista, {'estado': 'por_responder'}), 'Reunión de familias')
        otro = self.publicar(titulo='Otro aviso', respuesta=Comunicado.ENTERADO, expira=timezone.now() + timedelta(hours=1))
        Comunicado.objects.filter(pk=otro.pk).update(expira=timezone.now() - timedelta(minutes=1))
        self.assertEqual(cliente.post(self.url_portal('responder', otro), {'respuesta': 'enterado'}).status_code, 404)

    def test_un_comunicado_sin_respuesta_no_se_responde(self):
        comunicado = self.publicar()
        respuesta = self.portal().post(self.url_portal('responder', comunicado), {'respuesta': 'enterado'}, **JSON)
        self.assertEqual(respuesta.status_code, 400)


# ---------------------------------------------------------------------------
# 6. Corregir después de enviar
# ---------------------------------------------------------------------------
@PRUEBAS
@ARCHIVOS_TEMPORALES
class CorregirTests(Base):
    def datos(self, **cambios):
        return {'titulo': 'Reunión de familias (cambió la hora)', 'descripcion': 'Será a las 6.', **cambios}

    def test_el_autor_lo_corrige_y_se_conservan_las_lecturas(self):
        comunicado = self.publicar()
        cliente = self.portal()
        cliente.get(self.url_portal('recibido', comunicado))
        leido = self.copia_de(comunicado).leido_en
        respuesta = self.client.post(reverse('comunicados:editar', args=[comunicado.pk]), self.datos())
        self.assertRedirects(respuesta, reverse('comunicados:detalle', args=[comunicado.pk]), fetch_redirect_response=False)
        comunicado.refresh_from_db()
        self.assertEqual((comunicado.titulo, comunicado.descripcion), ('Reunión de familias (cambió la hora)', 'Será a las 6.'))
        self.assertIsNotNone(comunicado.editado)
        self.assertEqual(self.copia_de(comunicado).leido_en, leido)
        self.assertEqual(comunicado.destinatarios.count(), 2)
        self.assertContains(cliente.get(self.url_portal('recibido', comunicado)), 'Editado el')

    def test_solo_el_autor_o_el_administrador(self):
        comunicado = self.publicar()
        url = reverse('comunicados:editar', args=[comunicado.pk])
        self.client.force_login(self.direccion_sec)   # envía comunicados, pero no es suyo
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.carmen)          # no envía
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(url), 'Corregir comunicado')

    def test_quitar_un_archivo_y_agregar_otro(self):
        comunicado = self.publicar(archivos=[(pdf(), 'application/pdf')])
        self.client.post(reverse('comunicados:editar', args=[comunicado.pk]), {**self.datos(), 'archivos': [png()]})
        self.assertEqual([a.nombre_original for a in comunicado.adjuntos.all()], ['foto.png'])

    def test_un_programado_se_publica_al_quitarle_la_hora(self):
        comunicado = self.publicar(publicar_en=timezone.now() + timedelta(hours=2))
        self.assertIsNone(comunicado.avisado_en)
        with patch('Comunicados.tiempo_real.enviar_eventos') as eventos, self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('comunicados:editar', args=[comunicado.pk]), self.datos())
        comunicado.refresh_from_db()
        self.assertIsNotNone(comunicado.avisado_en)
        self.assertLessEqual(comunicado.publicado_en, timezone.now())
        self.assertIsNone(comunicado.editado)   # nadie lo había visto
        eventos.assert_called_once()


# ---------------------------------------------------------------------------
# 7. Programar el envío
# ---------------------------------------------------------------------------
@PRUEBAS
class ProgramarTests(Base):
    def test_no_se_ve_antes_de_su_hora_y_se_avisa_una_sola_vez(self):
        comunicado = self.publicar(titulo='Aviso del lunes', publicar_en=timezone.now() + timedelta(hours=1))
        cliente = self.portal()
        self.assertNotContains(cliente.get(reverse('portal_tutores:comunicados:inicio')), 'Aviso del lunes')
        self.assertEqual(cliente.get(self.url_portal('recibido', comunicado)).status_code, 404)
        self.assertContains(self.client.get(reverse('comunicados:inicio'), {'vista': 'enviados'}), 'Programado')
        Comunicado.objects.filter(pk=comunicado.pk).update(publicado_en=timezone.now() - timedelta(minutes=1))
        with patch('Comunicados.tiempo_real.enviar_eventos') as eventos:
            self.assertEqual(avisos.publicar_pendientes(), [comunicado.pk])
            self.assertEqual(avisos.publicar_pendientes(), [])
        eventos.assert_called_once()
        self.assertContains(cliente.get(reverse('portal_tutores:comunicados:inicio')), 'Aviso del lunes')

    def test_las_fechas_tienen_que_tener_sentido(self):
        with self.assertRaisesMessage(reglas.EnvioRechazado, 'publicación debe ser posterior'):
            self.publicar(publicar_en=timezone.now() - timedelta(minutes=5))
        with self.assertRaisesMessage(reglas.EnvioRechazado, 'posterior a la publicación'):
            self.publicar(publicar_en=timezone.now() + timedelta(days=2), expira=timezone.now() + timedelta(days=1))

    def test_el_comando_y_las_pantallas_publican_los_pendientes(self):
        comunicado = self.publicar(publicar_en=timezone.now() + timedelta(hours=1))
        Comunicado.objects.filter(pk=comunicado.pk).update(publicado_en=timezone.now() - timedelta(minutes=1))
        salida = StringIO()
        call_command('publicar_comunicados', stdout=salida)
        self.assertIn('Comunicados publicados: 1', salida.getvalue())
        otro = self.publicar(titulo='Otro', publicar_en=timezone.now() + timedelta(hours=1))
        Comunicado.objects.filter(pk=otro.pk).update(publicado_en=timezone.now() - timedelta(minutes=1))
        cache.delete(avisos.LLAVE_PUBLICAR)
        self.portal().get(reverse('portal_tutores:comunicados:resumen'))
        otro.refresh_from_db()
        self.assertIsNotNone(otro.avisado_en)


# ---------------------------------------------------------------------------
# 8. Texto con formato e imágenes dentro del texto
# ---------------------------------------------------------------------------
@PRUEBAS
@ARCHIVOS_TEMPORALES
class ImagenesDelTextoTests(Base):
    def subir(self, cliente=None):
        return (cliente or self.client).post(reverse('comunicados:imagen_subir'), {'imagen': png()}).json()

    def test_solo_la_ve_quien_la_subio_y_despues_quien_recibe_el_comunicado(self):
        imagen = self.subir()
        self.assertEqual(self.client.get(imagen['url']).status_code, 200)
        self.client.force_login(self.direccion_sec)
        self.assertEqual(self.client.get(imagen['url']).status_code, 404)
        comunicado = self.publicar(descripcion='', html=f'<p>Mira:</p><p><img data-imagen="{imagen["id"]}" alt="Mapa"></p>')
        self.assertEqual(ImagenComunicado.objects.get(pk=imagen['id']).comunicado, comunicado)
        ruta = reverse('portal_tutores:comunicados:imagen', args=[imagen['id']])
        self.assertContains(self.portal().get(self.url_portal('recibido', comunicado)), ruta)
        self.assertEqual(self.portal().get(ruta).status_code, 200)
        self.assertEqual(self.portal(self.ruben).get(ruta).status_code, 404)   # no lo recibió

    def test_una_imagen_ajena_no_se_cuela(self):
        self.client.force_login(self.direccion_sec)
        ajena = self.subir()
        self.client.force_login(self.laura)
        comunicado = self.publicar(descripcion='', html=f'<p>Hola</p><p><img data-imagen="{ajena["id"]}" alt=""></p>')
        self.assertNotIn('data-imagen', comunicado.html)


# ---------------------------------------------------------------------------
# 10. Usar como base
# ---------------------------------------------------------------------------
@PRUEBAS
@ARCHIVOS_TEMPORALES
class UsarComoBaseTests(Base):
    def test_empieza_con_lo_del_original_y_copia_sus_archivos(self):
        original = self.publicar(titulo='Junta mensual', archivos=[(pdf('orden.pdf'), 'application/pdf')],
                                 respuesta=Comunicado.ENCUESTA, pregunta='¿A qué hora?', opciones=['5 pm', '6 pm'])
        pantalla = self.client.get(CREAR, {'base': original.pk})
        for texto in ('Basado en «Junta mensual»', 'value="Junta mensual"', 'orden.pdf', 'value="5 pm"', f'&quot;tutores&quot;: [{self.ana.pk}]'):
            self.assertContains(pantalla, texto)
        adjunto = original.adjuntos.get()
        datos = {
            'titulo': 'Junta mensual de noviembre', 'descripcion': 'Los esperamos.', 'clave_envio': str(uuid.uuid4()), 'base': original.pk,
            'destinatarios': json.dumps({'tutores': [self.ana.pk]}), 'copiar_adjuntos': [adjunto.pk],
            'respuesta': Comunicado.ENCUESTA, 'pregunta': '¿A qué hora?', 'opciones': ['5 pm', '6 pm'],
        }
        self.assertTrue(self.client.post(CREAR, datos, **JSON).json()['ok'])
        nuevo = Comunicado.objects.get(titulo='Junta mensual de noviembre')
        copia = nuevo.adjuntos.get()
        self.assertEqual(copia.nombre_original, 'orden.pdf')
        self.assertNotEqual(copia.archivo.name, adjunto.archivo.name)

    def test_no_se_usa_como_base_uno_ajeno(self):
        original = self.publicar(titulo='Junta mensual')
        self.client.force_login(self.direccion_sec)
        self.assertNotContains(self.client.get(CREAR, {'base': original.pk}), 'Basado en')


# ---------------------------------------------------------------------------
# 11. Fijar y categorías
# ---------------------------------------------------------------------------
@PRUEBAS
class FijarYCategoriasTests(Base):
    def test_los_fijados_van_arriba_y_se_filtra_por_categoria(self):
        self.publicar(titulo='Reglamento escolar', fijado=True, categoria=Comunicado.ADMINISTRATIVO)
        self.publicar(titulo='Excursión al museo', categoria=Comunicado.EVENTOS)
        cliente = self.portal()
        html = cliente.get(reverse('portal_tutores:comunicados:inicio')).content.decode()
        lista = html[html.index('comunicados__rejilla'):]   # (la campana de arriba los ordena por fecha)
        self.assertLess(lista.index('Reglamento escolar'), lista.index('Excursión al museo'))   # fijado, aunque es más viejo
        filtrado = cliente.get(reverse('portal_tutores:comunicados:inicio'), {'categoria': Comunicado.EVENTOS})
        self.assertEqual([copia.comunicado.titulo for copia in filtrado.context['pagina']], ['Excursión al museo'])

    def test_una_categoria_que_no_existe(self):
        with self.assertRaisesMessage(reglas.EnvioRechazado, 'categoría'):
            self.publicar(categoria='INVENTADA')


# ---------------------------------------------------------------------------
# 12. Eventos en la agenda y «Agregar a mi calendario»
# ---------------------------------------------------------------------------
@PRUEBAS
class AgendaTests(Base):
    def test_aparece_en_la_agenda_de_quien_lo_recibe_y_se_baja_al_calendario(self):
        hoy = timezone.localdate()
        comunicado = self.publicar(titulo='Junta de familias', evento={'fecha': hoy, 'hora_inicio': time(18, 0), 'hora_fin': time(19, 30),
                                                                       'lugar': 'Auditorio'})
        cliente = self.portal()
        agenda = cliente.get(reverse('portal_tutores:agenda:calendario'), {'mes': f'{hoy:%Y-%m}'})
        self.assertContains(agenda, 'Junta de familias')
        self.assertContains(agenda, self.url_portal('recibido', comunicado))
        calendario = cliente.get(self.url_portal('calendario', comunicado))
        self.assertEqual(calendario['Content-Type'], 'text/calendar; charset=utf-8')
        contenido = calendario.content.decode()
        for texto in ('BEGIN:VEVENT', 'SUMMARY:Junta de familias', 'LOCATION:Auditorio', 'END:VCALENDAR'):
            self.assertIn(texto, contenido)
        # Quien lo envió también lo ve, con enlace a su seguimiento
        self.assertContains(self.client.get(reverse('agenda:calendario'), {'mes': f'{hoy:%Y-%m}'}),
                            reverse('comunicados:detalle', args=[comunicado.pk]))

    def test_un_evento_necesita_su_fecha(self):
        with self.assertRaisesMessage(reglas.EnvioRechazado, 'fecha del evento'):
            self.publicar(evento={'fecha': None, 'hora_inicio': time(9, 0)})


# ---------------------------------------------------------------------------
# 13. Recordar a los pendientes
# ---------------------------------------------------------------------------
@PRUEBAS
class RecordarTests(Base):
    def test_solo_a_los_pendientes_y_una_vez_por_hora(self):
        comunicado = self.publicar(seleccion={Destinatario.TUTOR: {self.ana.pk, self.ruben.pk}})
        self.portal().get(self.url_portal('recibido', comunicado))   # Ana ya lo leyó
        url = reverse('comunicados:recordar', args=[comunicado.pk])
        with patch('Comunicados.tiempo_real.enviar_eventos') as eventos, self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.client.post(url, **JSON).json()['cuantos'], 1)
        filas, recordatorio = eventos.call_args.args[1], eventos.call_args.args[2]
        self.assertEqual([fila['tutor_id'] for fila in filas], [self.ruben.pk])
        self.assertTrue(recordatorio)
        respuesta = self.client.post(url, **JSON)
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('recordó hace poco', respuesta.json()['error'])

    def test_nadie_mas_lo_recuerda(self):
        comunicado = self.publicar()
        url = reverse('comunicados:recordar', args=[comunicado.pk])
        self.client.force_login(self.direccion_sec)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.client.force_login(self.carmen)
        self.assertEqual(self.client.post(url).status_code, 403)


# ---------------------------------------------------------------------------
# 14. Lectura por grupo y Excel
# ---------------------------------------------------------------------------
@PRUEBAS
class SeguimientoTests(Base):
    def test_lectura_por_grupo(self):
        comunicado = self.publicar(seleccion={Destinatario.ESTUDIANTE: {self.lucia.pk, self.paula.pk, self.hugo.pk}, Destinatario.TUTOR: {self.ana.pk}})
        reglas.marcar_leido(comunicado.destinatarios.get(alumno=self.lucia))
        filas = self.client.get(reverse('comunicados:detalle', args=[comunicado.pk])).context['por_grupo']
        self.assertEqual([(f['nombre'], f['total'], f['leidos']) for f in filas],
                         [('2.º A · Primaria', 3, 1), ('2.º B · Primaria', 1, 0)])   # Ana cuenta con Lucía (2.º A)

    def test_la_lista_en_excel(self):
        comunicado = self.publicar(respuesta=Comunicado.ENTERADO)
        respuesta = self.client.get(reverse('comunicados:exportar', args=[comunicado.pk]))
        self.assertEqual(respuesta['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertIn(f'comunicado-{comunicado.pk}-lectura.xlsx', respuesta['Content-Disposition'])
        self.assertEqual(respuesta.content[:2], b'PK')
        self.client.force_login(self.direccion_sec)
        self.assertEqual(self.client.get(reverse('comunicados:exportar', args=[comunicado.pk])).status_code, 404)


# ---------------------------------------------------------------------------
# 15. El personal no docente como destinatario
# ---------------------------------------------------------------------------
@PRUEBAS
class PersonalTests(Base):
    def setUp(self):
        super().setUp()
        self.recepcion = crear_usuario('recepcion', Rol.objects.get(grupo__name='Recepción'))

    def test_el_administrador_le_envia_y_lo_recibe_en_el_sistema(self):
        universo = alcance_de(self.admin).universo()
        recepcion = next(p for p in universo['personal'] if p['id'] == self.recepcion.pk)
        self.assertEqual(recepcion['detalle'], 'Recepción')
        self.assertNotIn(self.laura.pk, [p['id'] for p in universo['personal']])   # los profesores van en su pestaña
        comunicado = self.publicar(self.admin, seleccion={Destinatario.PERSONAL: {self.recepcion.pk}}, titulo='Junta del personal')
        self.client.force_login(self.recepcion)
        self.assertContains(self.client.get(reverse('comunicados:inicio')), 'Junta del personal')
        self.client.get(reverse('comunicados:recibido', args=[comunicado.pk]))
        self.assertTrue(comunicado.destinatarios.get(usuario=self.recepcion).leido)
        self.assertEqual(tiempo_real.grupo_de_usuario(self.recepcion), f'comunicados.personal.{self.recepcion.pk}')

    def test_sin_el_permiso_no_llega_al_personal(self):
        self.assertFalse(alcance_de(self.laura).envia_al_personal)
        with self.assertRaisesMessage(reglas.EnvioRechazado, 'fuera de los niveles'):
            self.publicar(seleccion={Destinatario.PERSONAL: {self.recepcion.pk}})

    def test_con_el_permiso_de_enviar_al_personal(self):
        self.direccion_sec.user_permissions.add(Permission.objects.get(content_type__app_label='Comunicados', codename='enviar_personal'))
        direccion = type(self.direccion_sec).objects.get(pk=self.direccion_sec.pk)
        alcance = alcance_de(direccion)
        self.assertTrue(alcance.envia_al_personal)
        self.assertIn(self.recepcion, alcance.personal())
        self.assertIn('Personal del colegio', alcance.descripcion())

    def test_el_permiso_esta_en_el_catalogo(self):
        from Usuarios import catalogo
        self.assertIn('Comunicados.enviar_personal', catalogo.TODOS)
        self.assertIn('Comunicados.enviar', catalogo.REQUISITOS['Comunicados.enviar_personal'])
