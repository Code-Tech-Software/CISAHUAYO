"""Comunicados, mejoras del 2026-10-31: corregir sin engañar a quien ya respondió, autorización por estudiante, «Por atender» y
plazo para responder, quien no tiene acceso a su portal, la bandeja inicial, borradores, corregir un vencido, programados,
la lista por páginas, las consultas del selector, el aviso que se reintenta y los filtros. Lo demás es del navegador
(static/js/comunicados.js y static/js/comunicados-form.js)."""
import io
import json
import zipfile
from datetime import timedelta
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from Alumnos.models import Tutor
from CISAHUAYO.pruebas import PRUEBAS, crear_tutor, crear_usuario, vincular
from Usuarios.models import Rol

from . import avisos, borradores, reglas
from .alcance import alcance_de
from .models import AutorizacionEstudiante, BorradorComunicado, Comunicado, Destinatario, ImagenComunicado, RespuestaAnterior
from .test_modernos import JSON, Base
from .tests import ARCHIVOS_TEMPORALES, CREAR, INICIO, pdf, png

SOLO_ANA = {Destinatario.TUTOR: {'ana'}}


class Mejoras(Base):
    def a_ana(self):
        return {Destinatario.TUTOR: {self.ana.pk}}

    def autorizacion(self, usuario=None, seleccion=None, **campos):
        return self.publicar(usuario=usuario, seleccion=seleccion or self.a_ana(), respuesta=Comunicado.AUTORIZACION, pregunta='¿Autoriza?', **campos)

    def responder(self, comunicado, tutor=None, **datos):
        return self.portal(tutor).post(self.url_portal('responder', comunicado), datos, **JSON)

    def editar(self, comunicado, **datos):
        base = {'titulo': comunicado.titulo, 'descripcion': comunicado.descripcion}
        return self.client.post(reverse('comunicados:editar', args=[comunicado.pk]), {**base, **datos}, **JSON)


@PRUEBAS
class CorregirConRespuestasTests(Mejoras):
    def setUp(self):
        super().setUp()
        self.comunicado = self.autorizacion()
        self.responder(self.comunicado, respuesta='si')

    def test_hay_que_decir_que_tipo_de_correccion_es(self):
        respuesta = self.editar(self.comunicado, descripcion='Otro texto')
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('corrección menor', respuesta.json()['errores']['cambio'][0])
        self.comunicado.refresh_from_db()
        self.assertEqual(self.comunicado.descripcion, 'Los esperamos.')

    def test_la_pantalla_de_corregir_lo_pregunta(self):
        pantalla = self.client.get(reverse('comunicados:editar', args=[self.comunicado.pk]))
        self.assertContains(pantalla, 'Ya respondieron 1 persona')
        self.assertContains(pantalla, 'Cambio importante')

    def test_una_correccion_menor_conserva_las_respuestas(self):
        self.assertEqual(self.editar(self.comunicado, descripcion='Sin errata', cambio='MENOR').status_code, 200)
        copia = self.copia_de(self.comunicado)
        self.assertEqual(copia.respuesta, Destinatario.RESPUESTA_SI)
        self.assertFalse(RespuestaAnterior.objects.exists())

    def test_un_cambio_importante_pide_responder_otra_vez(self):
        with patch('Comunicados.avisos.avisar') as avisar, self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.editar(self.comunicado, descripcion='Ahora cuesta 500 pesos', cambio='IMPORTANTE').status_code, 200)
        avisar.assert_called_once_with(self.comunicado.pk, cambio=True)
        copia = self.copia_de(self.comunicado)
        self.assertIsNone(copia.respondido_en)
        self.assertIsNone(copia.leido_en)
        self.assertEqual(copia.respuesta, '')
        self.assertEqual(copia.autorizaciones.get().respuesta, '')
        anterior = RespuestaAnterior.objects.get(destinatario=copia)
        self.assertEqual(anterior.texto, 'Sí autoriza')
        self.comunicado.refresh_from_db()
        self.assertIsNotNone(self.comunicado.reconfirmar_en)

    def test_quien_lo_recibe_sabe_que_debe_responder_otra_vez(self):
        self.editar(self.comunicado, descripcion='Ahora cuesta 500 pesos', cambio='IMPORTANTE')
        self.assertContains(self.portal().get(self.url_portal('recibido', self.comunicado)), 'responde otra vez')

    def test_el_excel_conserva_lo_que_respondieron(self):
        self.editar(self.comunicado, descripcion='Ahora cuesta 500 pesos', cambio='IMPORTANTE')
        excel = self.client.get(reverse('comunicados:exportar', args=[self.comunicado.pk]))
        with zipfile.ZipFile(io.BytesIO(excel.content)) as archivo:
            self.assertIn('Respuestas anteriores', archivo.read('xl/workbook.xml').decode())

    def test_sin_respuestas_no_se_pregunta(self):
        otro = self.autorizacion()
        self.assertEqual(self.editar(otro, descripcion='Sin errata').status_code, 200)


@PRUEBAS
class AutorizacionPorEstudianteTests(Mejoras):
    """Ana es tutora de Lucía (primaria) y de Zoe (secundaria): al administrador le alcanzan las dos."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)
        self.comunicado = self.autorizacion(usuario=self.admin)

    def test_hay_una_fila_por_cada_hijo(self):
        filas = AutorizacionEstudiante.objects.filter(destinatario__comunicado=self.comunicado)
        self.assertEqual({fila.alumno_id for fila in filas}, {self.lucia.pk, self.zoe.pk})

    def test_solo_cuentan_los_hijos_al_alcance_de_quien_envia(self):
        comunicado = self.autorizacion()   # Laura solo llega a primaria
        self.assertEqual([fila.alumno_id for fila in self.copia_de(comunicado).autorizaciones.all()], [self.lucia.pk])

    def test_otros_comunicados_no_tienen_filas(self):
        comunicado = self.publicar(usuario=self.admin, seleccion=self.a_ana(), respuesta=Comunicado.ENTERADO)
        self.assertFalse(self.copia_de(comunicado).autorizaciones.exists())

    def test_la_pantalla_pregunta_por_cada_uno(self):
        pantalla = self.portal().get(self.url_portal('recibido', self.comunicado))
        self.assertContains(pantalla, f'name="alumno_{self.lucia.pk}"', count=2)
        self.assertContains(pantalla, f'name="alumno_{self.zoe.pk}"', count=2)

    def test_con_un_solo_hijo_quedan_los_dos_botones(self):
        pantalla = self.portal().get(self.url_portal('recibido', self.autorizacion()))
        self.assertContains(pantalla, 'name="respuesta" value="si"')
        self.assertNotContains(pantalla, 'name="alumno_')

    def test_responde_distinto_por_cada_uno(self):
        respuesta = self.responder(self.comunicado, **{f'alumno_{self.lucia.pk}': 'si', f'alumno_{self.zoe.pk}': 'no'})
        self.assertEqual(respuesta.status_code, 200)
        copia = self.copia_de(self.comunicado)
        self.assertEqual(copia.respuesta, Destinatario.RESPUESTA_MIXTA)
        self.assertEqual(copia.texto_de_respuesta, 'Autoriza a algunos')
        self.assertIn('Lucía Herrera Campos: Sí', copia.respuesta_detallada)
        self.assertIn('Zoe Herrera Campos: No', copia.respuesta_detallada)
        estados = {fila['nombre']: fila['clave'] for fila in reglas.autorizaciones_por_estudiante(self.comunicado)}
        self.assertEqual(estados, {'Lucía Herrera Campos': 'autorizado', 'Zoe Herrera Campos': 'no_autorizado'})

    def test_hay_que_responder_por_todos(self):
        respuesta = self.responder(self.comunicado, **{f'alumno_{self.lucia.pk}': 'si'})
        self.assertEqual(respuesta.status_code, 400)
        self.assertIsNone(self.copia_de(self.comunicado).respondido_en)
        self.assertFalse(AutorizacionEstudiante.objects.exclude(respuesta='').exists())

    def test_una_respuesta_sola_vale_para_todos(self):
        self.responder(self.comunicado, respuesta='si')
        self.assertEqual(self.copia_de(self.comunicado).respuesta, Destinatario.RESPUESTA_SI)
        self.assertEqual(AutorizacionEstudiante.objects.filter(respuesta='SI').count(), 2)

    def test_se_puede_cambiar(self):
        self.responder(self.comunicado, respuesta='si')
        self.responder(self.comunicado, respuesta='no')
        self.assertEqual(self.copia_de(self.comunicado).respuesta, Destinatario.RESPUESTA_NO)

    def tutores_de_lucia(self):
        beto = crear_tutor(nombre='Beto', apellido_paterno='Herrera', usuario='beto.herrera', contrasena='hash')
        vincular(beto, self.lucia, parentesco='PADRE')
        return beto, self.autorizacion(seleccion={Destinatario.TUTOR: {self.ana.pk, beto.pk}})

    def test_si_los_tutores_se_contradicen_no_cuenta_como_autorizado(self):
        beto, comunicado = self.tutores_de_lucia()
        self.responder(comunicado, respuesta='si')
        self.responder(comunicado, tutor=beto, respuesta='no')
        fila = reglas.autorizaciones_por_estudiante(comunicado)[0]
        self.assertEqual((fila['clave'], fila['texto']), ('desacuerdo', 'Tutores en desacuerdo'))
        resumen = reglas.resumen_de_respuestas(comunicado, comunicado.destinatarios.select_related('tutor', 'alumno'))
        self.assertEqual({f['texto']: f['cuantos'] for f in resumen['filas']}, {'Sí autoriza': 0, 'No autoriza': 0, 'Tutores en desacuerdo': 1})

    def test_basta_el_si_de_un_tutor(self):
        _, comunicado = self.tutores_de_lucia()
        self.responder(comunicado, respuesta='si')
        self.assertEqual(reglas.autorizaciones_por_estudiante(comunicado)[0]['clave'], 'autorizado')

    def test_el_seguimiento_y_el_excel_van_por_estudiante(self):
        self.responder(self.comunicado, respuesta='si')
        detalle = self.client.get(reverse('comunicados:detalle', args=[self.comunicado.pk]))
        self.assertContains(detalle, 'Autorización por estudiante')
        self.assertContains(detalle, 'Autorizado')
        self.assertEqual(detalle.context['respuestas']['filas'][0], {'texto': 'Sí autoriza', 'cuantos': 2, 'porcentaje': 100})
        lista = self.client.get(reverse('comunicados:lista_por_estudiante', args=[self.comunicado.pk]), {'q': 'zoe'})
        self.assertContains(lista, 'Zoe Herrera Campos')
        self.assertNotContains(lista, 'Lucía Herrera Campos')
        excel = self.client.get(reverse('comunicados:exportar', args=[self.comunicado.pk]))
        with zipfile.ZipFile(io.BytesIO(excel.content)) as archivo:
            self.assertIn('Por estudiante', archivo.read('xl/workbook.xml').decode())

    def test_un_cambio_importante_lo_borra_y_guarda_el_detalle(self):
        self.responder(self.comunicado, **{f'alumno_{self.lucia.pk}': 'si', f'alumno_{self.zoe.pk}': 'no'})
        self.editar(self.comunicado, descripcion='Otro destino', cambio='IMPORTANTE')
        self.assertFalse(AutorizacionEstudiante.objects.exclude(respuesta='').exists())
        self.assertIn('Lucía Herrera Campos: Sí', RespuestaAnterior.objects.get().texto)

    def test_un_comunicado_de_antes_conserva_su_respuesta_unica(self):
        AutorizacionEstudiante.objects.all().delete()
        self.responder(self.comunicado, respuesta='no')
        self.assertEqual(self.copia_de(self.comunicado).respuesta, Destinatario.RESPUESTA_NO)
        self.assertEqual(reglas.autorizaciones_por_estudiante(self.comunicado), [])


@PRUEBAS
class PorAtenderYPlazoTests(Mejoras):
    def lector(self):
        return reglas.lector_de_portal('TUTOR', self.ana)

    def test_abrir_sin_responder_no_lo_saca_de_lo_pendiente(self):
        comunicado = self.autorizacion()
        self.portal().get(self.url_portal('recibido', comunicado))
        self.assertIsNotNone(self.copia_de(comunicado).leido_en)
        self.assertEqual(self.lector().pendientes()[0], 1)
        self.assertEqual([c.titulo for c in (a.comunicado for a in reglas.avisos(self.lector()))], [comunicado.titulo])

    def test_responder_si(self):
        comunicado = self.autorizacion()
        self.responder(comunicado, respuesta='si')
        self.assertEqual(self.lector().pendientes()[0], 0)

    def test_solo_informar_sale_al_abrirlo(self):
        comunicado = self.publicar(seleccion=self.a_ana())
        self.assertEqual(self.lector().pendientes()[0], 1)
        self.portal().get(self.url_portal('recibido', comunicado))
        self.assertEqual(self.lector().pendientes()[0], 0)

    def test_la_bandeja_por_atender(self):
        pendiente = self.autorizacion(titulo='Excursión')
        hecho = self.publicar(titulo='Aviso ya visto', seleccion=self.a_ana())
        self.portal().get(self.url_portal('recibido', hecho))
        self.portal().get(self.url_portal('recibido', pendiente))
        lista = self.portal().get(reverse('portal_tutores:comunicados:inicio'), {'estado': 'por_atender'})
        self.assertEqual([copia.comunicado.titulo for copia in lista.context['pagina']], ['Excursión'])
        self.assertContains(lista, 'Por responder')

    def test_lo_que_espera_respuesta_va_antes_que_un_aviso_nuevo(self):
        self.autorizacion(titulo='Excursión')
        self.publicar(titulo='Aviso general', seleccion=self.a_ana())
        lista = self.portal().get(reverse('portal_tutores:comunicados:inicio'))
        self.assertEqual([copia.comunicado.titulo for copia in lista.context['pagina']], ['Excursión', 'Aviso general'])

    def test_el_estado_siempre_se_dice_con_texto(self):
        self.publicar(titulo='Suspensión', seleccion=self.a_ana(), urgente=True)
        limite = timezone.now() + timedelta(days=3)
        self.autorizacion(titulo='Excursión', responder_hasta=limite)
        lista = self.portal().get(reverse('portal_tutores:comunicados:inicio'))
        self.assertContains(lista, 'Urgente · Sin abrir')
        self.assertContains(lista, 'Responde antes del')

    def test_despues_del_plazo_ya_no_se_responde(self):
        comunicado = self.autorizacion(responder_hasta=timezone.now() + timedelta(days=1))
        Comunicado.objects.filter(pk=comunicado.pk).update(responder_hasta=timezone.now() - timedelta(minutes=1))
        self.assertContains(self.responder(comunicado, respuesta='si'), 'plazo', status_code=400)
        pantalla = self.portal().get(self.url_portal('recibido', comunicado))
        self.assertContains(pantalla, 'El plazo para responder terminó')
        self.assertNotContains(pantalla, 'data-responder')
        self.assertEqual(self.lector().pendientes()[0], 0)   # ya abierto, no hay nada que atender
        self.assertIn('plazo', reglas.motivo_para_no_recordar(Comunicado.objects.get(pk=comunicado.pk)))

    def test_el_plazo_se_revisa(self):
        with self.assertRaisesMessage(reglas.EnvioRechazado, 'posterior a la publicación'):
            self.autorizacion(responder_hasta=timezone.now() - timedelta(days=1))
        with self.assertRaisesMessage(reglas.EnvioRechazado, 'expiración'):
            self.autorizacion(responder_hasta=timezone.now() + timedelta(days=5), expira=timezone.now() + timedelta(days=1))
        with self.assertRaisesMessage(reglas.EnvioRechazado, 'Solo se pone plazo'):
            self.publicar(responder_hasta=timezone.now() + timedelta(days=1))

    def test_se_puede_ampliar_al_corregir(self):
        comunicado = self.autorizacion(responder_hasta=timezone.now() + timedelta(days=1))
        nueva = (timezone.localdate() + timedelta(days=5)).isoformat()
        self.assertEqual(self.editar(comunicado, responder_fecha=nueva).status_code, 200)
        comunicado.refresh_from_db()
        self.assertEqual(timezone.localtime(comunicado.responder_hasta).date().isoformat(), nueva)


@PRUEBAS
class SinAccesoTests(Mejoras):
    def setUp(self):
        super().setUp()
        self.sin_portal = crear_tutor(nombre='Inés', apellido_paterno='Luna', usuario='ines.luna', contrasena='hash', acceso_portal=False)
        vincular(self.sin_portal, self.paula, parentesco='MADRE')
        self.comunicado = self.publicar(seleccion={Destinatario.TUTOR: {self.ana.pk, self.sin_portal.pk}})

    def preparado(self):
        return reglas.preparar(reglas.con_estadisticas(Comunicado.objects.filter(pk=self.comunicado.pk)).get())

    def test_no_cuenta_en_los_porcentajes(self):
        self.portal().get(self.url_portal('recibido', self.comunicado))
        comunicado = self.preparado()
        self.assertEqual((comunicado.total, comunicado.alcanzables, comunicado.n_sin_acceso, comunicado.porcentaje, comunicado.pendientes), (2, 1, 1, 100, 0))

    def test_no_entra_en_recordar(self):
        self.assertEqual([copia.tutor_id for copia in reglas.por_recordar(self.comunicado)], [self.ana.pk])
        self.portal().get(self.url_portal('recibido', self.comunicado))
        self.assertEqual(reglas.motivo_para_no_recordar(self.comunicado), 'Todos lo han abierto.')

    def test_el_seguimiento_lo_dice(self):
        detalle = self.client.get(reverse('comunicados:detalle', args=[self.comunicado.pk]))
        self.assertContains(detalle, 'sin acceso al portal')
        self.assertContains(detalle, 'Sin acceso al portal')
        lista = self.client.get(reverse('comunicados:lista_de_destinatarios', args=[self.comunicado.pk]), {'estado': 'sin-acceso'})
        self.assertContains(lista, 'Inés')
        self.assertNotContains(lista, 'Ana')

    def test_si_consigue_acceso_vuelve_a_contar(self):
        Tutor.objects.filter(pk=self.sin_portal.pk).update(acceso_portal=True)
        self.assertEqual(self.preparado().alcanzables, 2)

    def test_quien_ya_lo_abrio_y_perdio_el_acceso_sigue_contando(self):
        copia = Destinatario.objects.get(comunicado=self.comunicado, tutor=self.sin_portal)
        reglas.marcar_leido(copia)
        self.assertEqual(self.preparado().n_sin_acceso, 0)


@PRUEBAS
class BandejaInicialTests(Mejoras):
    def vista(self):
        return self.client.get(INICIO).context['vista']

    def test_con_algo_por_atender_entra_a_recibidos(self):
        self.publicar(usuario=self.admin, seleccion={Destinatario.PROFESOR: {self.prof_laura.pk}})
        self.assertEqual(self.vista(), 'recibidos')

    def test_sin_pendientes_entra_a_enviados(self):
        self.assertEqual(self.vista(), 'enviados')

    def test_la_pestana_elegida_se_respeta(self):
        self.publicar(usuario=self.admin, seleccion={Destinatario.PROFESOR: {self.prof_laura.pk}})
        self.assertEqual(self.client.get(INICIO, {'vista': 'enviados'}).context['vista'], 'enviados')


def datos_de_borrador(**campos):
    return {'titulo': 'Junta de padres', 'descripcion': 'A medias', 'html': '', 'destinatarios': '', **campos}


@PRUEBAS
@ARCHIVOS_TEMPORALES
class BorradoresTests(Mejoras):
    URL = reverse('comunicados:borrador_guardar')

    def guardar(self, **campos):
        return self.client.post(self.URL, datos_de_borrador(**campos), **JSON)

    def test_guarda_lo_que_haya_sin_validarlo(self):
        respuesta = self.guardar(titulo='', descripcion='', destinatarios=json.dumps({'tutores': [self.ana.pk]}))
        self.assertEqual(respuesta.status_code, 200)
        borrador = BorradorComunicado.objects.get(pk=respuesta.json()['id'])
        self.assertEqual(str(borrador), 'Borrador sin título')

    def test_no_le_llega_a_nadie(self):
        self.guardar(destinatarios=json.dumps({'tutores': [self.ana.pk]}))
        self.assertFalse(Comunicado.objects.exists())
        self.assertFalse(Destinatario.objects.exists())
        self.assertEqual(reglas.lector_de_portal('TUTOR', self.ana).pendientes()[0], 0)

    def test_actualiza_el_mismo_borrador(self):
        pk = self.guardar().json()['id']
        self.guardar(borrador=pk, titulo='Junta de padres de 2.º A')
        self.assertEqual(BorradorComunicado.objects.get().titulo, 'Junta de padres de 2.º A')

    def test_tiene_su_bandeja_y_se_continua(self):
        pk = self.guardar(pregunta='¿Asiste?', respuesta='AUTORIZACION', responder_fecha='2030-01-15').json()['id']
        bandeja = self.client.get(INICIO, {'vista': 'borradores'})
        self.assertContains(bandeja, 'Junta de padres')
        self.assertContains(bandeja, f'?borrador={pk}')
        formulario = self.client.get(CREAR, {'borrador': pk})
        self.assertContains(formulario, 'value="Junta de padres"')
        self.assertContains(formulario, '¿Asiste?')
        self.assertContains(formulario, 'value="2030-01-15"')

    def test_es_solo_de_quien_lo_escribio(self):
        pk = self.guardar().json()['id']
        self.client.force_login(self.admin)
        self.assertNotContains(self.client.get(CREAR, {'borrador': pk}), 'Junta de padres')
        self.assertEqual(self.client.post(reverse('comunicados:borrador_descartar', args=[pk])).status_code, 404)
        respuesta = self.guardar(borrador=pk, titulo='Ajeno')
        self.assertNotEqual(respuesta.json()['id'], pk)
        self.assertEqual(BorradorComunicado.objects.get(pk=pk).titulo, 'Junta de padres')

    def test_al_enviarlo_desaparece_y_lleva_sus_archivos(self):
        pk = self.client.post(self.URL, {**datos_de_borrador(), 'archivos': [pdf()]}, **JSON).json()['id']
        adjunto = BorradorComunicado.objects.get(pk=pk).adjuntos.get()
        datos = self.datos(titulo='Junta de padres', borrador=pk, adjuntos_borrador=[adjunto.pk])
        respuesta = self.client.post(CREAR, datos, **JSON)
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(BorradorComunicado.objects.exists())
        self.assertEqual([a.nombre_original for a in Comunicado.objects.get().adjuntos.all()], ['circular.pdf'])

    def test_un_envio_que_falla_conserva_el_borrador(self):
        pk = self.guardar().json()['id']
        self.client.post(CREAR, {**self.datos(titulo=''), 'borrador': pk}, **JSON)
        self.assertTrue(BorradorComunicado.objects.filter(pk=pk).exists())

    def test_se_descarta_con_sus_archivos(self):
        pk = self.client.post(self.URL, {**datos_de_borrador(), 'archivos': [pdf()]}, **JSON).json()['id']
        archivo = BorradorComunicado.objects.get(pk=pk).adjuntos.get().archivo
        self.client.post(reverse('comunicados:borrador_descartar', args=[pk]))
        self.assertFalse(BorradorComunicado.objects.exists())
        self.assertFalse(archivo.storage.exists(archivo.name))

    def test_rechaza_archivos_que_no_sirven(self):
        falso = pdf('virus.exe')
        self.assertEqual(self.client.post(self.URL, {**datos_de_borrador(), 'archivos': [falso]}, **JSON).status_code, 400)

    def test_tiene_un_tope(self):
        for numero in range(BorradorComunicado.MAXIMO_POR_PERSONA):
            BorradorComunicado.objects.create(autor=self.laura, titulo=str(numero))
        self.assertContains(self.guardar(), 'borradores', status_code=400)

    def test_sus_imagenes_no_se_borran_al_dia_siguiente(self):
        imagen = ImagenComunicado.objects.create(autor=self.laura, archivo=png(), tipo='image/png', nombre_original='foto.png')
        suelta = ImagenComunicado.objects.create(autor=self.laura, archivo=png('otra.png'), tipo='image/png', nombre_original='otra.png')
        ImagenComunicado.objects.update(creada=timezone.now() - timedelta(days=3))
        self.guardar(html=f'<p><img data-imagen="{imagen.pk}" alt=""></p>')
        avisos.limpiar_imagenes()
        self.assertTrue(ImagenComunicado.objects.filter(pk=imagen.pk).exists())
        self.assertFalse(ImagenComunicado.objects.filter(pk=suelta.pk).exists())


@PRUEBAS
class CorregirVencidosYProgramadosTests(Mejoras):
    def test_un_vencido_se_corrige_sin_cambiar_su_fecha(self):
        comunicado = self.publicar(expira=timezone.now() + timedelta(days=1))
        Comunicado.objects.filter(pk=comunicado.pk).update(expira=timezone.now() - timedelta(days=2))
        comunicado.refresh_from_db()
        local = timezone.localtime(comunicado.expira)
        respuesta = self.editar(comunicado, descripcion='Sin errata', expira_fecha=local.date().isoformat(), expira_hora=f'{local:%H:%M}')
        self.assertEqual(respuesta.status_code, 200)
        comunicado.refresh_from_db()
        self.assertEqual(comunicado.descripcion, 'Sin errata')

    def test_una_fecha_nueva_ya_pasada_se_rechaza(self):
        comunicado = self.publicar()
        ayer = (timezone.localdate() - timedelta(days=1)).isoformat()
        self.assertEqual(self.editar(comunicado, expira_fecha=ayer).status_code, 400)

    def programado(self):
        return self.publicar(publicar_en=timezone.now() + timedelta(hours=2))

    def fechas_de(self, comunicado):
        local = timezone.localtime(comunicado.publicado_en)
        return {'publicar_fecha': local.date().isoformat(), 'publicar_hora': f'{local:%H:%M}'}

    def test_borrar_la_fecha_no_lo_publica(self):
        comunicado = self.programado()
        respuesta = self.editar(comunicado, destinatarios=json.dumps({'tutores': [self.ana.pk]}))
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('publicar', respuesta.json()['errores'])
        comunicado.refresh_from_db()
        self.assertTrue(comunicado.programado)

    def test_se_le_cambian_los_destinatarios(self):
        comunicado = self.programado()
        destinatarios = json.dumps({'tutores': [self.ruben.pk], 'estudiantes': [self.paula.pk]})
        pantalla = self.client.get(reverse('comunicados:editar', args=[comunicado.pk]))
        self.assertContains(pantalla, 'data-selector-abrir')
        self.assertEqual(self.editar(comunicado, destinatarios=destinatarios, **self.fechas_de(comunicado)).status_code, 200)
        self.assertEqual({(d.tutor_id, d.alumno_id) for d in comunicado.destinatarios.all()}, {(self.ruben.pk, None), (None, self.paula.pk)})

    def test_el_alcance_tambien_se_revisa(self):
        comunicado = self.programado()
        destinatarios = json.dumps({'estudiantes': [self.zoe.pk]})   # de secundaria: fuera del alcance de Laura
        self.assertEqual(self.editar(comunicado, destinatarios=destinatarios, **self.fechas_de(comunicado)).status_code, 400)
        self.assertEqual(comunicado.destinatarios.count(), 2)

    def test_una_autorizacion_programada_rehace_sus_filas(self):
        comunicado = self.autorizacion(publicar_en=timezone.now() + timedelta(hours=2))
        destinatarios = json.dumps({'tutores': [self.ruben.pk]})
        self.editar(comunicado, destinatarios=destinatarios, **self.fechas_de(comunicado))
        self.assertEqual([fila.alumno_id for fila in AutorizacionEstudiante.objects.all()], [self.paula.pk])

    def test_uno_publicado_no_cambia_de_destinatarios(self):
        comunicado = self.publicar()
        pantalla = self.client.get(reverse('comunicados:editar', args=[comunicado.pk]))
        self.assertNotContains(pantalla, 'data-selector-abrir')
        self.assertEqual(self.editar(comunicado, destinatarios=json.dumps({'tutores': [self.ruben.pk]})).status_code, 200)
        self.assertEqual(comunicado.destinatarios.count(), 2)


@PRUEBAS
class ListaPorPaginasTests(Mejoras):
    def setUp(self):
        super().setUp()
        self.tutores = [crear_tutor(nombre=f'Persona{n:03d}', apellido_paterno='Prueba', telefono='3530000000', usuario=f'prueba{n}', contrasena='hash') for n in range(60)]
        for tutor in self.tutores:
            vincular(tutor, self.lucia, parentesco='MADRE')
        self.comunicado = self.publicar(seleccion={Destinatario.TUTOR: {t.pk for t in self.tutores}})
        self.url = reverse('comunicados:lista_de_destinatarios', args=[self.comunicado.pk])

    def test_el_detalle_no_manda_la_lista_completa(self):
        detalle = self.client.get(reverse('comunicados:detalle', args=[self.comunicado.pk]))
        self.assertEqual(len(detalle.context['destinatarios']), 50)
        self.assertEqual(detalle.context['siguiente'], 2)
        self.assertContains(detalle, 'data-destinatarios-mas="2"')

    def test_la_segunda_pagina(self):
        pagina = self.client.get(self.url, {'pagina': 2})
        self.assertEqual(len(pagina.context['destinatarios']), 10)
        self.assertNotContains(pagina, 'data-destinatarios-mas')

    def test_busca_sin_importar_acentos_ni_mayusculas(self):
        self.assertContains(self.client.get(self.url, {'q': 'PERSONA059'}), 'Persona059')

    def test_filtra_por_estado(self):
        reglas.marcar_leido(self.comunicado.destinatarios.first())
        self.assertEqual(len(self.client.get(self.url, {'estado': 'leido'}).context['destinatarios']), 1)

    def test_una_lista_ajena_no_existe(self):
        self.client.force_login(self.direccion_sec)
        self.assertEqual(self.client.get(self.url).status_code, 404)


@PRUEBAS
class SelectorTests(Mejoras):
    def test_las_consultas_no_crecen_con_el_personal(self):
        rol = Rol.objects.get(grupo__name='Control escolar') if Rol.objects.filter(grupo__name='Control escolar').exists() else Rol.objects.get(grupo__name='Docente')

        def consultas():
            usuario = type(self.admin).objects.get(pk=self.admin.pk)
            with CaptureQueriesContext(connection) as captura:
                alcance_de(usuario).universo()
            return len(captura)

        crear_usuario('uno.mas', rol)
        antes = consultas()
        for numero in range(12):
            crear_usuario(f'otro{numero}', rol)
        self.assertLessEqual(consultas(), antes + 2)


@PRUEBAS
class AvisoConfiableTests(Mejoras):
    def test_queda_marcado_al_terminar_de_avisar(self):
        comunicado = self.publicar()
        comunicado.refresh_from_db()
        self.assertIsNotNone(comunicado.avisado_en)
        self.assertEqual(comunicado.aviso_intentos, 1)

    def test_si_falla_queda_pendiente_y_se_reintenta(self):
        with patch('Comunicados.tiempo_real.enviar_eventos', side_effect=RuntimeError('se cayó')), self.assertLogs('Comunicados.avisos', 'ERROR'):
            comunicado = self.publicar(publicar_en=timezone.now() + timedelta(hours=1))
            Comunicado.objects.filter(pk=comunicado.pk).update(publicado_en=timezone.now() - timedelta(minutes=1))
            self.assertEqual(avisos.publicar_pendientes(), [])
        comunicado.refresh_from_db()
        self.assertIsNone(comunicado.avisado_en)
        self.assertEqual(avisos.publicar_pendientes(), [])   # alguien lo reclamó hace poco: todavía no
        Comunicado.objects.filter(pk=comunicado.pk).update(aviso_reclamado_en=timezone.now() - timedelta(minutes=11))
        self.assertEqual(avisos.publicar_pendientes(), [comunicado.pk])
        comunicado.refresh_from_db()
        self.assertIsNotNone(comunicado.avisado_en)

    def test_no_se_avisa_dos_veces(self):
        comunicado = self.publicar()
        with patch('Comunicados.tiempo_real.enviar_eventos') as eventos:
            self.assertEqual(avisos.publicar_pendientes(), [])
        eventos.assert_not_called()
        self.assertFalse(avisos._publicar(comunicado.pk))

    def test_deja_de_intentar_tras_varios_fallos(self):
        comunicado = self.publicar(publicar_en=timezone.now() + timedelta(hours=1))
        Comunicado.objects.filter(pk=comunicado.pk).update(publicado_en=timezone.now() - timedelta(hours=1), aviso_intentos=Comunicado.MAXIMO_DE_INTENTOS)
        self.assertEqual(avisos.publicar_pendientes(), [])


@PRUEBAS
class FiltrosTests(Mejoras):
    def setUp(self):
        super().setUp()
        self.viejo = self.publicar(titulo='Aviso viejo')
        Comunicado.objects.filter(pk=self.viejo.pk).update(publicado_en=timezone.now() - timedelta(days=30))
        self.nuevo = self.publicar(titulo='Aviso nuevo', urgente=True)

    def titulos(self, **parametros):
        return [c.titulo for c in self.client.get(INICIO, {'vista': 'enviados', **parametros}).context['pagina']]

    def test_por_periodo(self):
        hace_una_semana = (timezone.localdate() - timedelta(days=7)).isoformat()
        self.assertEqual(self.titulos(desde=hace_una_semana), ['Aviso nuevo'])
        self.assertEqual(self.titulos(hasta=hace_una_semana), ['Aviso viejo'])

    def test_una_fecha_invalida_se_ignora(self):
        self.assertEqual(len(self.titulos(desde='ayer', hasta='2026-99-99')), 2)

    def test_con_pendientes(self):
        for copia in self.nuevo.destinatarios.all():
            reglas.marcar_leido(copia)
        self.assertEqual(self.titulos(estado='con_pendientes'), ['Aviso viejo'])

    def test_por_autor_solo_en_la_gestion(self):
        self.publicar(usuario=self.admin, titulo='Del administrador', seleccion=self.a_ana())
        self.client.force_login(self.admin)
        self.assertEqual([c.titulo for c in self.client.get(INICIO, {'vista': 'gestion', 'autor': self.admin.pk}).context['pagina']], ['Del administrador'])
        self.assertContains(self.client.get(INICIO, {'vista': 'gestion'}), 'Cualquier autor')
        self.assertNotContains(self.client.get(INICIO, {'vista': 'enviados'}), 'Cualquier autor')

    def test_los_portales_no_ofrecen_autor(self):
        self.assertNotContains(self.portal().get(reverse('portal_tutores:comunicados:inicio')), 'Cualquier autor')
