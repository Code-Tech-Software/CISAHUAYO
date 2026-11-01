"""La bandeja organizada (2026-10-31): «Nuevo mensaje» con su directorio, topes por clase de persona, el panel que se abre sin
recargar, las citas, el historial al subir, los filtros de la búsqueda, destacar y archivar, los archivos de la conversación
y la vista compacta."""
from datetime import timedelta

from django.contrib.auth.models import Permission
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from CISAHUAYO import portales
from CISAHUAYO.pruebas import PRUEBAS, crear_usuario
from Usuarios.models import Rol

from . import reglas
from .models import Conversacion, Mensaje, Miembro, Participante
from .reglas import FiltroDeBusqueda
from .test_conversaciones import pdf
from .test_mejoras import Base
from .tests import ARCHIVOS_TEMPORALES, BANDEJA, entrar_al_portal


class BaseOrganizacion(Base):
    def setUp(self):
        super().setUp()
        self.marta_p, self.ana_p = self.p(self.marta), self.p(self.ana)
        self.rosa_cliente = Client()
        entrar_al_portal(self.rosa_cliente, portales.TUTOR, self.rosa)

    def escribir(self, autor, texto='Hola', conversacion=None):
        return reglas.enviar(conversacion or self.conversacion, self.p(autor), texto)

    def adjuntar(self, archivo):
        return self.client.post(reverse('mensajes:documento_subir', args=[self.conversacion.pk]), {'documento': archivo})

    def con_documentos(self, texto, documentos):
        url = reverse('mensajes:enviar', args=[self.conversacion.pk])
        return self.client.post(url, {'texto': texto, 'html': '', 'documentos': documentos}, HTTP_ACCEPT='application/json')

    def directorio(self, cliente=None, espacio='mensajes', **parametros):
        return (cliente or self.client).get(reverse(f'{espacio}:directorio'), parametros).json()['grupos']

    def claves(self, grupos, titulo):
        return [c['clave'] for g in grupos if g['titulo'] == titulo for c in g['contactos']]

    def lista(self, **parametros):
        return [c.pk for c in self.client.get(BANDEJA, parametros).context['bandeja']]


@PRUEBAS
class NuevoMensajeTests(BaseOrganizacion):
    def test_el_boton_esta_en_el_sistema_y_en_los_portales(self):
        self.assertContains(self.client.get(BANDEJA), 'data-chat-nuevo')
        self.assertContains(self.rosa_cliente.get(reverse('portal_tutores:mensajes:inicio')), 'data-chat-nuevo')

    def test_la_familia_ve_a_sus_docentes_con_lo_que_imparten(self):
        grupos = self.directorio(self.rosa_cliente, 'portal_tutores:mensajes')
        docentes = next(g for g in grupos if g['titulo'] == 'Tus docentes')
        self.assertEqual([c['clave'] for c in docentes['contactos']], [f'u:{self.marta.pk}'])
        detalle = docentes['contactos'][0]['detalle']
        self.assertTrue(detalle.startswith('Docente · '), detalle)
        self.assertIn(self.asignacion.materia.nombre, detalle)
        self.assertIn(str(self.asignacion.grupo), detalle)

    def test_el_personal_por_clase_de_persona(self):
        grupos = self.directorio()
        self.assertEqual([g['titulo'] for g in grupos], ['Personal del colegio', 'Estudiantes', 'Tutores'])
        self.assertIn(f'a:{self.ana.pk}', self.claves(grupos, 'Estudiantes'))
        self.assertIn(f't:{self.rosa.pk}', self.claves(grupos, 'Tutores'))

    def test_solo_salen_a_quienes_puede_escribir(self):
        grupos = self.directorio()
        self.assertNotIn(f'a:{self.zoe.pk}', self.claves(grupos, 'Estudiantes'))
        self.assertNotIn(f't:{self.tomas.pk}', self.claves(grupos, 'Tutores'))
        de_ana = self.directorio(self.ana_cliente, 'portal_estudiantes:mensajes')
        self.assertFalse(any(c['clave'].startswith(('a:', 't:')) for g in de_ana for c in g['contactos']))

    def test_el_alcance_de_prefectura(self):
        self.assertIn(f'u:{self.prefecto.pk}', [c.clave for c in reglas.contactos(self.p(self.tomas))])
        self.assertNotIn(f'u:{self.prefecto.pk}', [c.clave for c in reglas.contactos(self.p(self.rosa))])

    def test_el_estudiante_dice_su_grupo(self):
        contacto = next(c for c in self.directorio()[1]['contactos'] if c['clave'] == f'a:{self.ana.pk}')
        self.assertIn(str(self.asignacion.grupo), contacto['detalle'])

    def test_elegir_a_alguien_abre_la_conversacion(self):
        respuesta = self.rosa_cliente.post(reverse('portal_tutores:mensajes:nueva'), {'destinatario': f'u:{self.marta.pk}'})
        conversacion = Conversacion.objects.get(clave=Conversacion.clave_de(self.p(self.rosa), self.marta_p))
        self.assertRedirects(respuesta, reverse('portal_tutores:mensajes:conversacion', args=[conversacion.pk]), fetch_redirect_response=False)


@PRUEBAS
class TopesTests(BaseOrganizacion):
    def personal(self, nombre, cuantos, permiso='usar'):
        rol = Rol.objects.get(grupo__name='Docente')
        for numero in range(cuantos):
            cuenta = crear_usuario(f'{nombre}{numero}', rol, first_name=nombre)
            cuenta.user_permissions.add(Permission.objects.get(codename=permiso))

    def test_muchas_coincidencias_de_personal_no_esconden_a_los_estudiantes(self):
        self.personal('Anabel', 30)
        claves = [c.clave for c in reglas.contactos(self.p(self.control), 'ana', limite=25)]
        self.assertIn(f'a:{self.ana.pk}', claves)
        self.assertEqual(len([c for c in claves if c.startswith('u:')]), 25)

    def test_avisa_si_hay_mas(self):
        self.personal('Anabel', 30)
        personal = reglas.directorio(self.p(self.control), limite=25)[0]
        self.assertTrue(personal.hay_mas)

    def test_las_consultas_no_crecen_con_las_cuentas_que_atienden(self):
        familia = self.p(self.rosa)

        def consultas():
            with CaptureQueriesContext(connection) as captura:
                reglas.contactos(familia)
            return len(captura)

        antes = consultas()
        self.personal('Atiende', 15, 'contactar_familias')
        self.assertLessEqual(consultas(), antes + 2)


@PRUEBAS
class PanelTests(BaseOrganizacion):
    def test_el_panel_trae_solo_la_conversacion(self):
        self.escribir(self.ana, 'Buenos días')
        respuesta = self.client.get(reverse('mensajes:conversacion', args=[self.conversacion.pk]), {'panel': '1'})
        self.assertContains(respuesta, 'data-chat-hilo')
        self.assertContains(respuesta, 'Buenos días')
        self.assertContains(respuesta, f'data-conversacion="{self.conversacion.pk}"')
        self.assertNotContains(respuesta, 'chat__lista')
        self.assertEqual(reglas.no_leidos(self.marta_p), 0)   # abrirla la deja leída, como siempre

    def test_sin_conversacion_trae_la_bienvenida(self):
        respuesta = self.client.get(BANDEJA, {'panel': '1'})
        self.assertContains(respuesta, 'chat__nada')
        self.assertNotContains(respuesta, 'data-conversacion=')

    def test_una_conversacion_ajena_no_existe(self):
        ajena = reglas.conversacion_con(self.p(self.recepcion), self.p(self.raul))
        self.assertEqual(self.client.get(reverse('mensajes:conversacion', args=[ajena.pk]), {'panel': '1'}).status_code, 404)

    def test_la_abierta_sigue_en_la_lista_aunque_sea_de_otra_pagina(self):
        self.escribir(self.ana)
        otra = reglas.conversacion_con(self.marta_p, self.p(self.rosa))
        self.escribir(self.rosa, 'Más reciente', otra)
        conversaciones, siguientes = reglas.pagina_de_bandeja(self.marta_p, limite=1, incluir=self.conversacion.pk)
        self.assertEqual([c.pk for c in conversaciones], [otra.pk, self.conversacion.pk])
        self.assertIsNotNone(siguientes)


@PRUEBAS
class CitasYAnterioresTests(BaseOrganizacion):
    def test_una_cita_lleva_al_mensaje_aunque_no_este_a_la_vista(self):
        primero = self.escribir(self.ana, 'El primero')
        reglas.enviar(self.conversacion, self.marta_p, 'Respondo', responde_a=primero.pk)
        url = reverse('mensajes:conversacion', args=[self.conversacion.pk])
        self.assertContains(self.pantalla(), f'href="{url}?mensaje={primero.pk}#mensaje-{primero.pk}"')

    def test_los_anteriores_llegan_al_subir(self):
        Mensaje.objects.bulk_create([Mensaje(conversacion=self.conversacion, autor=self.ana_p, texto=f'Mensaje {n}') for n in range(120)])
        ultimo = self.conversacion.mensajes.order_by('-pk').first()
        Conversacion.objects.filter(pk=self.conversacion.pk).update(ultimo_mensaje=ultimo, actualizada=timezone.now())
        pantalla = self.pantalla()
        self.assertContains(pantalla, 'data-chat-anteriores')
        primero = pantalla.context['primero']
        datos = self.client.get(reverse('mensajes:anteriores', args=[self.conversacion.pk]), {'antes': primero}).json()
        self.assertIn('Mensaje 69', datos['html'])
        self.assertNotIn('Mensaje 70<', datos['html'])
        self.assertTrue(datos['hay_anteriores'])
        fin = self.client.get(reverse('mensajes:anteriores', args=[self.conversacion.pk]), {'antes': datos['primero']}).json()
        self.assertFalse(fin['hay_anteriores'])
        self.assertIn('Mensaje 0<', fin['html'])

    def test_los_anteriores_de_una_conversacion_ajena_no_existen(self):
        ajena = reglas.conversacion_con(self.p(self.recepcion), self.p(self.raul))
        self.assertEqual(self.client.get(reverse('mensajes:anteriores', args=[ajena.pk]), {'antes': 5}).status_code, 404)


@PRUEBAS
class BusquedaConFiltrosTests(BaseOrganizacion):
    def setUp(self):
        super().setUp()
        self.con_ana = self.escribir(self.ana, 'Tarea de fracciones')
        self.con_rosa_c = reglas.conversacion_con(self.marta_p, self.p(self.rosa))
        self.con_rosa = self.escribir(self.rosa, 'La tarea llegará tarde', self.con_rosa_c)

    def ids(self, texto='tarea', **filtro):
        return [m.pk for m in reglas.buscar_mensajes(self.marta_p, texto, filtro=FiltroDeBusqueda(**filtro))]

    def test_por_clase_de_persona(self):
        self.assertEqual(self.ids(), [self.con_rosa.pk, self.con_ana.pk])
        self.assertEqual(self.ids(tipo=Participante.ESTUDIANTE), [self.con_ana.pk])
        self.assertEqual(self.ids(tipo=Participante.TUTOR), [self.con_rosa.pk])

    def test_por_persona(self):
        self.assertEqual(self.ids(persona='Rosa'), [self.con_rosa.pk])
        self.assertEqual(self.ids(persona='Marta'), [])   # la propia no cuenta: es con quién es la conversación

    def test_por_fechas(self):
        hoy = timezone.localdate()
        Mensaje.objects.filter(pk=self.con_ana.pk).update(creado=timezone.now() - timedelta(days=10))
        self.assertEqual(self.ids(desde=hoy), [self.con_rosa.pk])
        self.assertEqual(self.ids(hasta=hoy - timedelta(days=5)), [self.con_ana.pk])

    def test_por_estado_de_lectura(self):
        reglas.marcar_leida(self.conversacion, self.marta_p)
        self.assertEqual(self.ids(estado=reglas.SIN_LEER), [self.con_rosa.pk])
        self.assertEqual(self.ids(estado=reglas.LEIDOS), [self.con_ana.pk])

    @ARCHIVOS_TEMPORALES
    def test_con_adjuntos_y_sin_escribir_nada(self):
        documento = self.adjuntar(pdf()).json()
        respuesta = self.con_documentos('Va el archivo', [documento['id']])
        self.assertEqual(self.ids('', adjuntos=True), [respuesta.json()['id']])

    def test_sin_texto_ni_filtros_no_busca(self):
        self.assertEqual(self.ids(''), [])
        self.assertEqual(self.ids('t'), [])

    def test_en_una_sola_conversacion(self):
        self.assertEqual(self.ids(conversacion=self.conversacion.pk), [self.con_ana.pk])

    def test_una_conversacion_ajena_no_da_resultados(self):
        ajena = reglas.conversacion_con(self.p(self.recepcion), self.p(self.raul))
        reglas.enviar(ajena, self.p(self.raul), 'Tarea secreta')
        datos = self.client.get(reverse('mensajes:buscar'), {'q': 'secreta', 'conversacion': ajena.pk}).json()
        self.assertEqual(datos['mensajes'], [])

    def test_ver_mas_resultados(self):
        Mensaje.objects.bulk_create([Mensaje(conversacion=self.conversacion, autor=self.ana_p, texto=f'Tarea {n}') for n in range(30)])
        url = reverse('mensajes:buscar')
        primera = self.client.get(url, {'q': 'tarea'}).json()
        self.assertEqual(len(primera['mensajes']), reglas.POR_PAGINA_BUSQUEDA)
        segunda = self.client.get(url, {'q': 'tarea', 'antes': primera['siguiente']}).json()
        self.assertEqual(len(segunda['mensajes']), 12)
        self.assertEqual(segunda['siguiente'], '')
        self.assertFalse({m['id'] for m in primera['mensajes']} & {m['id'] for m in segunda['mensajes']})

    def test_los_filtros_tambien_sin_javascript(self):
        respuesta = self.client.get(BANDEJA, {'q': 'tarea', 'tipo': Participante.TUTOR})
        self.assertEqual([r['id'] for r in respuesta.context['encontrados']], [self.con_rosa.pk])

    def test_un_filtro_invalido_se_ignora(self):
        datos = self.client.get(reverse('mensajes:buscar'), {'q': 'tarea', 'tipo': 'NADA', 'desde': 'ayer'}).json()
        self.assertEqual(len(datos['mensajes']), 2)

    def test_la_casilla_de_adjuntos_va_en_su_caja(self):
        # .choice__input cubre a su contenedor y es transparente: sin .choice taparía todo el panel de filtros
        self.assertContains(self.client.get(BANDEJA), '<label class="choice choice--check" for="filtro-busqueda-adjuntos">')

    def test_el_portal_no_filtra_por_clase_de_persona(self):
        self.assertNotIn('tipo', self.ana_cliente.get(reverse('portal_estudiantes:mensajes:inicio')).context['busqueda_form'].fields)


@PRUEBAS
class OrganizarTests(BaseOrganizacion):
    def setUp(self):
        super().setUp()
        self.escribir(self.ana, 'Hola maestra')
        self.url = reverse('mensajes:archivar', args=[self.conversacion.pk])

    def miembro(self, participante):
        return Miembro.objects.get(conversacion=self.conversacion, participante=participante)

    def test_archivar_la_saca_de_todas_y_no_borra_nada(self):
        total = self.conversacion.mensajes.count()
        self.client.post(self.url, {'valor': '1'})
        self.assertEqual(self.lista(), [])
        self.assertEqual(self.lista(vista='archivadas'), [self.conversacion.pk])
        self.assertEqual(self.conversacion.mensajes.count(), total)

    def test_es_solo_de_quien_la_archiva(self):
        self.client.post(self.url, {'valor': '1'})
        self.assertIsNone(self.miembro(self.ana_p).archivada_en)
        lista = self.ana_cliente.get(reverse('portal_estudiantes:mensajes:inicio')).context['bandeja']
        self.assertEqual([c.pk for c in lista], [self.conversacion.pk])

    def test_un_mensaje_nuevo_la_regresa(self):
        self.client.post(self.url, {'valor': '1'})
        self.escribir(self.ana, 'Otra pregunta')
        self.assertEqual(self.lista(), [self.conversacion.pk])
        self.assertEqual(self.lista(vista='archivadas'), [])

    def test_lo_sin_leer_sigue_contando(self):
        self.client.post(self.url, {'valor': '1'}, HTTP_ACCEPT='application/json')
        self.assertEqual(reglas.no_leidos(self.marta_p), 1)
        self.assertEqual(self.lista(sin_leer='1'), [self.conversacion.pk])

    def test_deshacer(self):
        self.client.post(self.url, {'valor': '1'})
        self.client.post(self.url, {'valor': '0'})
        self.assertEqual(self.lista(), [self.conversacion.pk])

    def test_destacar(self):
        url = reverse('mensajes:destacar', args=[self.conversacion.pk])
        self.assertEqual(self.client.post(url, {'valor': '1'}, HTTP_ACCEPT='application/json').json(), {'destacada': True})
        self.assertEqual(self.lista(vista='destacadas'), [self.conversacion.pk])
        self.assertTrue(self.client.get(BANDEJA).context['bandeja'][0].destacada)
        self.assertIsNone(self.miembro(self.ana_p).destacada_en)
        self.client.post(url, {'valor': '0'})
        self.assertEqual(self.lista(vista='destacadas'), [])

    def test_sin_javascript_regresa_a_la_misma_bandeja(self):
        respuesta = self.client.post(self.url, {'valor': '1', 'vista': 'destacadas'})
        self.assertRedirects(respuesta, f'{BANDEJA}?vista=destacadas', fetch_redirect_response=False)

    def test_en_una_conversacion_ajena_no_se_puede(self):
        ajena = reglas.conversacion_con(self.p(self.recepcion), self.p(self.raul))
        for ruta in ('mensajes:archivar', 'mensajes:destacar'):
            self.assertEqual(self.client.post(reverse(ruta, args=[ajena.pk]), {'valor': '1'}).status_code, 404)

    def test_desde_el_portal(self):
        self.ana_cliente.post(reverse('portal_estudiantes:mensajes:archivar', args=[self.conversacion.pk]), {'valor': '1'})
        self.assertIsNotNone(self.miembro(self.ana_p).archivada_en)

    def test_marcar_todo_como_leido(self):
        otra = reglas.conversacion_con(self.marta_p, self.p(self.rosa))
        self.escribir(self.rosa, 'Buenas tardes', otra)
        self.assertEqual(reglas.no_leidos(self.marta_p), 2)
        datos = self.client.post(reverse('mensajes:marcar_todo'), HTTP_ACCEPT='application/json').json()
        self.assertEqual(datos, {'no_leidos': 0})
        self.assertEqual(self.lista(sin_leer='1'), [])

    def test_los_enlaces_conservan_la_bandeja(self):
        self.client.post(self.url, {'valor': '1'})
        url = reverse('mensajes:conversacion', args=[self.conversacion.pk])
        self.assertContains(self.client.get(BANDEJA, {'vista': 'archivadas'}), f'{url}?vista=archivadas')

    def test_por_clase_de_persona(self):
        otra = reglas.conversacion_con(self.marta_p, self.p(self.rosa))
        self.escribir(self.rosa, 'Buenas tardes', otra)
        self.assertEqual(self.lista(tipo=Participante.TUTOR), [otra.pk])
        self.assertEqual(self.lista(tipo=Participante.ESTUDIANTE), [self.conversacion.pk])
        self.assertEqual(len(self.client.get(BANDEJA).context['chips']), 3)

    def test_en_el_portal_no_hay_filtro_por_clase(self):
        respuesta = self.ana_cliente.get(reverse('portal_estudiantes:mensajes:inicio'), {'tipo': Participante.TUTOR})
        self.assertEqual([c.pk for c in respuesta.context['bandeja']], [self.conversacion.pk])
        self.assertEqual(respuesta.context['chips'], [])


@PRUEBAS
@ARCHIVOS_TEMPORALES
class ArchivosTests(BaseOrganizacion):
    def setUp(self):
        super().setUp()
        self.url = reverse('mensajes:archivos', args=[self.conversacion.pk])

    def enviar_documento(self):
        documento = self.adjuntar(pdf('calendario.pdf')).json()
        self.con_documentos('Te lo paso', [documento['id']])
        return documento

    def test_lista_lo_enviado(self):
        documento = self.enviar_documento()
        archivos = self.client.get(self.url).json()['archivos']
        self.assertEqual([a['id'] for a in archivos], [documento['id']])
        self.assertEqual(archivos[0]['autor'], 'Tú')
        self.assertTrue(archivos[0]['documento'])
        self.assertTrue(archivos[0]['descargar'].endswith('?descargar=1'))

    def test_lo_que_no_se_ha_enviado_no_sale(self):
        self.adjuntar(pdf())
        self.assertEqual(self.client.get(self.url).json()['archivos'], [])

    def test_la_otra_persona_los_ve_con_sus_direcciones(self):
        documento = self.enviar_documento()
        url = reverse('portal_estudiantes:mensajes:archivos', args=[self.conversacion.pk])
        archivo = self.ana_cliente.get(url).json()['archivos'][0]
        self.assertEqual(archivo['url'], reverse('portal_estudiantes:mensajes:documento', args=[documento['id']]))
        self.assertEqual(archivo['autor'], self.marta_p.nombre)

    def test_una_conversacion_ajena_no_existe(self):
        ajena = reglas.conversacion_con(self.p(self.recepcion), self.p(self.raul))
        self.assertEqual(self.client.get(reverse('mensajes:archivos', args=[ajena.pk])).status_code, 404)

    def test_cada_documento_se_puede_descargar(self):
        documento = self.enviar_documento()
        url = reverse('mensajes:documento', args=[documento['id']])
        self.assertContains(self.pantalla(), f'{url}?descargar=1')
        respuesta = self.client.get(url, {'descargar': '1'})
        self.assertIn('attachment', respuesta['Content-Disposition'])


@PRUEBAS
class PantallaTests(BaseOrganizacion):
    def test_la_vista_compacta_se_guarda_con_la_persona(self):
        self.assertNotContains(self.client.get(BANDEJA), 'chat--compacta')
        self.client.post(reverse('mensajes:preferencias'), {'compacta': '1'})
        self.assertContains(self.client.get(BANDEJA), 'chat--compacta')
        self.client.post(reverse('mensajes:preferencias'), {'compacta': '0'})
        self.assertNotContains(self.client.get(BANDEJA), 'chat--compacta')

    def test_tambien_en_el_portal_y_sin_tocar_a_los_demas(self):
        self.ana_cliente.post(reverse('portal_estudiantes:mensajes:preferencias'), {'compacta': '1'})
        self.assertContains(self.ana_cliente.get(reverse('portal_estudiantes:mensajes:inicio')), 'chat--compacta')
        self.assertNotContains(self.client.get(BANDEJA), 'chat--compacta')

    def test_el_contador_conoce_el_limite(self):
        self.assertContains(self.pantalla(), f'data-chat-contador data-maximo="{Mensaje.MAXIMO}"')

    def test_el_aviso_de_conexion_esta_en_la_pantalla(self):
        self.assertContains(self.client.get(BANDEJA), 'data-chat-conexion')

    def test_el_administrador_entra_a_la_moderacion_desde_el_menu(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(BANDEJA), reverse('mensajes:moderacion'))
