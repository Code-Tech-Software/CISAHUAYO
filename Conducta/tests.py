"""Conducta: catálogos de cada nivel (Ajustes › Conducta), su relación con el historial y los permisos del módulo."""
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.urls import reverse

from CISAHUAYO.pruebas import PRUEBAS, crear_rol, crear_usuario
from Usuarios.models import Rol

from . import reglas
from .models import POSITIVA, CategoriaConducta, MedidaDisciplinaria, MotivoConducta, ReglaReincidencia
from .pruebas import CARPETA, BaseConductaTestCase, borrar_carpeta


def tearDownModule():
    borrar_carpeta()


URL = reverse('conducta:configuracion')


@PRUEBAS
@override_settings(MEDIA_ROOT=CARPETA)
class CatalogosPorNivelTests(BaseConductaTestCase):
    def test_cada_nivel_tiene_sus_propios_catalogos(self):
        respuesta = self.client.get(URL, {'nivel': 'PRIMARIA', 'seccion': 'categorias'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual({c.nombre for c in respuesta.context['elementos']}, {'Convivencia', 'Reconocimientos'})
        respuesta = self.client.get(URL, {'nivel': 'SECUNDARIA', 'seccion': 'categorias'})
        self.assertEqual([c.nombre for c in respuesta.context['elementos']], ['Convivencia'])
        self.assertEqual(reglas.opciones_del_nivel('PREESCOLAR')['categorias'], [])
        for seccion in ('motivos', 'medidas', 'suspensiones', 'reincidencia'):
            self.assertEqual(self.client.get(URL, {'nivel': 'PREPARATORIA', 'seccion': seccion}).status_code, 200, seccion)

    def test_el_mismo_nombre_en_otro_nivel_si_pero_repetido_en_el_nivel_no(self):
        respuesta = self.client.post(reverse('conducta:categoria_crear') + '?nivel=PRIMARIA', {'nombre': '  convivencia ', 'tipo': 'INCIDENCIA', 'activo': 'on'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('nombre', respuesta.context['form'].errors)
        respuesta = self.client.post(reverse('conducta:categoria_crear') + '?nivel=PREESCOLAR', {'nombre': 'Convivencia', 'tipo': 'INCIDENCIA', 'activo': 'on'})
        self.assertRedirects(respuesta, f'{URL}?nivel=PREESCOLAR&seccion=categorias')
        self.assertEqual(CategoriaConducta.objects.filter(nombre__iexact='convivencia').count(), 3)
        with self.assertRaises(IntegrityError), transaction.atomic():   # también lo cuida la base de datos
            CategoriaConducta.objects.create(nivel='PRIMARIA', nombre='CONVIVENCIA', tipo='INCIDENCIA')

    def test_un_motivo_es_de_una_categoria_de_su_nivel_y_no_se_repite_en_ella(self):
        url = reverse('conducta:motivo_crear') + '?nivel=PRIMARIA'
        respuesta = self.client.post(url, {'categoria': self.convivencia_sec.pk, 'nombre': 'Robo', 'activo': 'on'})
        self.assertIn('categoria', respuesta.context['form'].errors)
        respuesta = self.client.post(url, {'categoria': self.convivencia.pk, 'nombre': 'agresión VERBAL', 'activo': 'on'})
        self.assertIn('nombre', respuesta.context['form'].errors)
        respuesta = self.client.post(url, {'categoria': self.reconocimiento.pk, 'nombre': 'Agresión verbal', 'gravedad': 'GRAVE', 'activo': 'on'})
        self.assertEqual(respuesta.status_code, 302)   # en otra categoría sí
        self.assertEqual(MotivoConducta.objects.get(categoria=self.reconocimiento, nombre='Agresión verbal').gravedad, '')   # positiva: sin gravedad

    def test_lo_usado_no_se_elimina_se_desactiva_y_sigue_en_el_historial(self):
        self.registrar(medidas=[self.amonestacion.pk])
        registro = self.ultimo()
        respuesta = self.client.post(reverse('conducta:medida_eliminar', args=[self.amonestacion.pk]), follow=True)
        self.assertContains(respuesta, 'ya se usa en el historial')
        self.assertTrue(MedidaDisciplinaria.objects.filter(pk=self.amonestacion.pk).exists())
        self.client.post(reverse('conducta:medida_estado', args=[self.amonestacion.pk]))
        self.amonestacion.refresh_from_db()
        self.assertFalse(self.amonestacion.activo)
        self.assertNotIn(self.amonestacion.pk, [m['id'] for m in reglas.opciones_del_nivel('PRIMARIA')['medidas']])
        self.assertContains(self.client.get(reverse('conducta:detalle', args=[registro.pk])), 'Amonestación verbal')
        # Lo que nunca se usó sí se elimina
        self.client.post(reverse('conducta:motivo_eliminar', args=[self.empujon.pk]))
        self.assertFalse(MotivoConducta.objects.filter(pk=self.empujon.pk).exists())

    def test_lo_inactivo_no_se_ofrece_ni_se_acepta_en_registros_nuevos(self):
        self.agresion.activo = False
        self.agresion.save()
        self.assertNotIn(self.agresion.pk, [m['id'] for m in reglas.opciones_del_nivel('PRIMARIA')['motivos']])
        respuesta = self.registrar()
        self.assertIn('motivo', respuesta.context['form'].errors)
        # Una categoría inactiva se lleva sus motivos
        self.convivencia.activo = False
        self.convivencia.save()
        self.assertNotIn(self.empujon.pk, [m['id'] for m in reglas.opciones_del_nivel('PRIMARIA')['motivos']])

    def test_renombrar_no_cambia_el_significado_del_historial(self):
        self.registrar()
        registro = self.ultimo()
        self.client.post(reverse('conducta:motivo_editar', args=[self.agresion.pk]), {
            'categoria': self.convivencia.pk, 'nombre': 'Insulto', 'gravedad': 'LEVE', 'activo': 'on',
        })
        registro.refresh_from_db()
        self.assertEqual(registro.motivo_nombre, 'Agresión verbal')
        detalle = self.client.get(reverse('conducta:detalle', args=[registro.pk]))
        self.assertContains(detalle, 'Agresión verbal')
        self.assertContains(detalle, 'Hoy se llama «Insulto»')

    def test_lo_usado_no_cambia_de_tipo_ni_de_categoria(self):
        self.registrar()
        respuesta = self.client.post(reverse('conducta:categoria_editar', args=[self.convivencia.pk]), {'nombre': 'Convivencia', 'tipo': POSITIVA, 'activo': 'on'})
        self.assertIn('tipo', respuesta.context['form'].errors)
        respuesta = self.client.post(reverse('conducta:motivo_editar', args=[self.agresion.pk]), {'categoria': self.reconocimiento.pk, 'nombre': 'Agresión verbal', 'activo': 'on'})
        self.assertIn('categoria', respuesta.context['form'].errors)

    def test_las_sugerencias_solo_llenan_un_catalogo_vacio(self):
        self.client.post(reverse('conducta:sugerencias'), {'nivel': 'PREESCOLAR'})
        self.assertEqual(MedidaDisciplinaria.objects.filter(nivel='PREESCOLAR').count(), 4)
        self.assertTrue(MedidaDisciplinaria.objects.get(nivel='PREESCOLAR', nombre='Suspensión').implica_suspension)
        self.client.post(reverse('conducta:sugerencias'), {'nivel': 'PRIMARIA'})
        self.assertEqual(MedidaDisciplinaria.objects.filter(nivel='PRIMARIA').count(), 3)

    def test_aviso_de_reincidencia_por_nivel(self):
        self.client.post(reverse('conducta:reincidencia'), {'nivel': 'PRIMARIA', 'activa': 'on', 'incidencias': 3, 'dias': 15})
        regla = ReglaReincidencia.objects.get(nivel='PRIMARIA')
        self.assertEqual((regla.incidencias, regla.dias, regla.activa, regla.modificado_por), (3, 15, True, self.admin))
        self.client.post(reverse('conducta:reincidencia'), {'nivel': 'PRIMARIA', 'activa': 'on', 'incidencias': 1, 'dias': 15})
        self.assertEqual(ReglaReincidencia.objects.get(nivel='PRIMARIA').incidencias, 3)   # menos de 2 no se acepta
        self.assertFalse(ReglaReincidencia.objects.filter(nivel='SECUNDARIA').exists())


@PRUEBAS
@override_settings(MEDIA_ROOT=CARPETA)
class PermisosTests(BaseConductaTestCase):
    def test_ajustes_muestra_la_pestana_solo_a_quien_configura(self):
        self.assertContains(self.client.get(reverse('ajustes:inicio')), 'href="/ajustes/conducta/"')
        self.client.force_login(self.sin_permisos)
        self.assertNotContains(self.client.get(reverse('ajustes:inicio')), 'href="/ajustes/conducta/"')
        self.assertEqual(self.client.get(URL).status_code, 403)

    def test_cada_catalogo_pide_su_permiso(self):
        usuario = crear_usuario('lupe', crear_rol('Solo categorías', {'Conducta.view_categoriaconducta'}))
        self.client.force_login(usuario)
        respuesta = self.client.get(URL, {'seccion': 'medidas'})
        self.assertEqual(respuesta.context['seccion'], 'categorias')   # solo ve lo que puede
        self.assertEqual([s for s, _ in respuesta.context['secciones']], ['categorias'])
        self.assertNotContains(respuesta, 'Nueva categoría')
        self.assertEqual(self.client.get(reverse('conducta:categoria_crear')).status_code, 403)
        self.assertEqual(self.client.post(reverse('conducta:categoria_estado', args=[self.convivencia.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse('conducta:reincidencia'), {'nivel': 'PRIMARIA'}).status_code, 403)

    def test_el_docente_no_entra_al_registro_ni_a_los_reportes(self):
        docente = crear_usuario('marta', Rol.objects.get(grupo__name='Docente'))
        self.client.force_login(docente)
        for nombre in ('conducta:lista', 'conducta:crear', 'conducta:reportes', 'conducta:pendientes'):
            self.assertEqual(self.client.get(reverse(nombre)).status_code, 403, nombre)

    def test_control_escolar_registra_pero_no_anula(self):
        usuario = crear_usuario('rosa', Rol.objects.get(grupo__name='Control escolar'))
        self.client.force_login(usuario)
        self.assertEqual(self.registrar().status_code, 302)
        registro = self.ultimo()
        self.assertEqual(registro.registrado_por, usuario)
        self.assertEqual(self.client.post(reverse('conducta:anular', args=[registro.pk]), {'motivo': 'Error de captura en el sistema'}).status_code, 403)
        self.assertEqual(self.client.get(URL).status_code, 403)   # los catálogos son de Dirección
        direccion = crear_usuario('dir', Rol.objects.get(grupo__name='Dirección'))
        self.client.force_login(direccion)
        self.assertEqual(self.client.get(URL).status_code, 200)

    def test_el_menu_y_el_buscador_ofrecen_el_modulo(self):
        respuesta = self.client.get(reverse('inicio'))
        etiquetas = [e['etiqueta'] for s in respuesta.context['navegacion'] for e in s['elementos']]
        self.assertIn('Registro de conducta', etiquetas)
        self.assertIn('Reportes de conducta', etiquetas)
        self.assertIn('Registrar conducta', [a['etiqueta'] for a in respuesta.context['acciones_rapidas']])
        self.client.force_login(self.sin_permisos)
        etiquetas = [e['etiqueta'] for s in self.client.get(reverse('inicio')).context['navegacion'] for e in s['elementos']]
        self.assertNotIn('Registro de conducta', etiquetas)
