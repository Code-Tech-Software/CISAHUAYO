"""Equivalencia de los grados: su nombre en la continuidad escolar sin importar el nivel.

Puede ser un número (1.° de secundaria es el 7) o un código con letras (K1 para 1.° de preescolar).
"""
import importlib
from pathlib import Path

from django.apps import apps as registro
from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse

from Alumnos.academico import (
    BASE_DE_EQUIVALENCIA,
    LARGO_EQUIVALENCIA,
    PREFIJO_DE_EQUIVALENCIA,
    equivalencia_sugerida,
    normalizar_equivalencia,
    siguiente_grado,
)
from Alumnos.models import Grado
from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase, crear_grado
from Grados.forms import GradoForm

RAIZ = Path(settings.BASE_DIR)


class EquivalenciaHabitualTests(SimpleTestCase):
    def test_primaria_secundaria_y_preparatoria_siguen_la_numeracion_corrida(self):
        self.assertEqual([equivalencia_sugerida('PRIMARIA', n) for n in range(1, 7)], ['1', '2', '3', '4', '5', '6'])
        self.assertEqual([equivalencia_sugerida('SECUNDARIA', n) for n in range(1, 4)], ['7', '8', '9'])
        self.assertEqual([equivalencia_sugerida('PREPARATORIA', n) for n in range(1, 4)], ['10', '11', '12'])

    def test_primero_de_secundaria_es_el_septimo(self):
        self.assertEqual(equivalencia_sugerida('SECUNDARIA', 1), '7')

    def test_preescolar_usa_un_codigo_con_letra(self):
        self.assertEqual([equivalencia_sugerida('PREESCOLAR', n) for n in (1, 2, 3)], ['K1', 'K2', 'K3'])

    def test_sin_nivel_o_numero_no_hay_propuesta(self):
        self.assertEqual(equivalencia_sugerida('', 1), '')
        self.assertEqual(equivalencia_sugerida('PRIMARIA', None), '')
        self.assertEqual(equivalencia_sugerida('PRIMARIA', 0), '')

    def test_se_escribe_como_se_quiere_y_se_guarda_ordenada(self):
        casos = {'k1': 'K1', ' K 1 ': 'K1', '7°': '7', '7.': '7', '07': '7', 'kA2': 'KA2', '': '', None: ''}
        for escrito, guardado in casos.items():
            with self.subTest(escrito=escrito):
                self.assertEqual(normalizar_equivalencia(escrito), guardado)


class TextoDeLaEquivalenciaTests(SimpleTestCase):
    def grado(self, equivalencia):
        return Grado(nivel='SECUNDARIA', numero=1, equivalencia=equivalencia)

    def test_un_numero_se_lee_con_grado(self):
        grado = self.grado('7')
        self.assertEqual(grado.equivalencia_texto, '7°')
        self.assertEqual(grado.equivalencia_frase, 'Equivale al 7°')
        self.assertEqual(grado.equivalencia_numero, 7)

    def test_un_codigo_con_letras_se_lee_tal_cual(self):
        grado = self.grado('K1')
        self.assertEqual(grado.equivalencia_texto, 'K1')
        self.assertEqual(grado.equivalencia_frase, 'Equivale a K1')
        self.assertIsNone(grado.equivalencia_numero)

    def test_sin_equivalencia_no_hay_texto(self):
        grado = self.grado('')
        self.assertEqual((grado.equivalencia_texto, grado.equivalencia_frase), ('', ''))
        self.assertIsNone(grado.equivalencia_numero)

    def test_un_entero_asignado_en_memoria_tambien_funciona(self):
        self.assertEqual(self.grado(7).equivalencia_texto, '7°')


@PRUEBAS
class FormularioDeGradoTests(BaseTestCase):
    def datos(self, **cambios):
        datos = {'nivel': 'SECUNDARIA', 'numero': 1, 'equivalencia': ''}
        datos.update(cambios)
        return datos

    def test_sin_equivalencia_se_guarda_la_habitual(self):
        casos = [('PRIMARIA', 3, '3'), ('SECUNDARIA', 1, '7'), ('SECUNDARIA', 3, '9'), ('PREPARATORIA', 2, '11'), ('PREESCOLAR', 2, 'K2')]
        for nivel, numero, esperada in casos:
            with self.subTest(grado=f'{numero} {nivel}'):
                respuesta = self.client.post(reverse('grados:crear'), self.datos(nivel=nivel, numero=numero))
                self.assertRedirects(respuesta, reverse('grados:lista'), fetch_redirect_response=False)
                self.assertEqual(Grado.objects.get(nivel=nivel, numero=numero).equivalencia, esperada)

    def test_una_equivalencia_escrita_se_respeta_y_se_ordena(self):
        casos = [('12', '12'), ('k1', 'K1'), (' 7° ', '7'), ('Ka 2', 'KA2')]
        for n, (escrita, guardada) in enumerate(casos, start=1):
            with self.subTest(escrita=escrita):
                self.client.post(reverse('grados:crear'), self.datos(nivel='PRIMARIA', numero=n, equivalencia=escrita))
                self.assertEqual(Grado.objects.get(nivel='PRIMARIA', numero=n).equivalencia, guardada)

    def test_preescolar_puede_tener_un_numero_si_el_colegio_lo_prefiere(self):
        self.client.post(reverse('grados:crear'), self.datos(nivel='PREESCOLAR', numero=1, equivalencia='15'))
        self.assertEqual(Grado.objects.get(nivel='PREESCOLAR', numero=1).equivalencia, '15')

    def test_no_se_repite_entre_grados_vigentes(self):
        crear_grado('SECUNDARIA', 1, equivalencia='7')
        respuesta = self.client.post(reverse('grados:crear'), self.datos(nivel='PRIMARIA', numero=2, equivalencia='7'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'La equivalencia 7° ya la tiene 1° Secundaria')
        self.assertFalse(Grado.objects.filter(nivel='PRIMARIA', numero=2).exists())

    def test_los_codigos_con_letras_tampoco_se_repiten_aunque_cambien_las_mayusculas(self):
        crear_grado('PREESCOLAR', 1, equivalencia='K1')
        respuesta = self.client.post(reverse('grados:crear'), self.datos(nivel='PREESCOLAR', numero=2, equivalencia='k1'))
        self.assertContains(respuesta, 'La equivalencia K1 ya la tiene 1° Preescolar')

    def test_la_propuesta_automatica_tampoco_puede_repetirse(self):
        crear_grado('PRIMARIA', 1, equivalencia='7')   # alguien ocupó el 7 con otro grado
        respuesta = self.client.post(reverse('grados:crear'), self.datos())
        self.assertContains(respuesta, 'La equivalencia 7° ya la tiene 1° Primaria')

    def test_un_grado_de_baja_no_bloquea_la_equivalencia(self):
        crear_grado('SECUNDARIA', 1, equivalencia='7', activo=False)
        respuesta = self.client.post(reverse('grados:crear'), self.datos(nivel='PRIMARIA', numero=2, equivalencia='7'))
        self.assertEqual(respuesta.status_code, 302)

    def test_al_editar_conserva_la_suya_sin_chocar_consigo_mismo(self):
        grado = crear_grado('SECUNDARIA', 1, equivalencia='7')
        respuesta = self.client.post(reverse('grados:editar', args=[grado.pk]), self.datos(equivalencia='7'))
        self.assertRedirects(respuesta, reverse('grados:lista'), fetch_redirect_response=False)

    def test_al_editar_se_puede_vaciar_para_volver_a_la_habitual(self):
        grado = crear_grado('PREESCOLAR', 1, equivalencia='ZZ')
        self.client.post(reverse('grados:editar', args=[grado.pk]), self.datos(nivel='PREESCOLAR', numero=1, equivalencia=''))
        grado.refresh_from_db()
        self.assertEqual(grado.equivalencia, 'K1')

    def test_formato_invalido(self):
        for valor in ('K-1', 'K#1', '7/8', 'ñ1', 'K1K1K1K1K'):
            with self.subTest(valor=valor):
                respuesta = self.client.post(reverse('grados:crear'), self.datos(equivalencia=valor))
                self.assertEqual(respuesta.status_code, 200)
                self.assertContains(respuesta, 'field__error')
        self.assertFalse(Grado.objects.exists())

    def test_el_largo_maximo(self):
        self.assertEqual(LARGO_EQUIVALENCIA, 8)
        respuesta = self.client.post(reverse('grados:crear'), self.datos(equivalencia='A' * 9))
        self.assertContains(respuesta, 'field__error')
        respuesta = self.client.post(reverse('grados:crear'), self.datos(equivalencia='A' * 8))
        self.assertEqual(respuesta.status_code, 302)

    def test_el_formulario_explica_la_equivalencia_y_propone_la_habitual(self):
        html = self.client.get(reverse('grados:crear')).content.decode()
        self.assertIn('name="equivalencia"', html)
        self.assertIn('Equivalencia en la continuidad escolar', html)
        self.assertIn('un código con letras (K1 para 1.° de preescolar)', html)
        self.assertIn('js/grados-form.js', html)
        for nivel, base in BASE_DE_EQUIVALENCIA.items():
            self.assertIn(f'&quot;{nivel}&quot;: {base}', html)
        for nivel, prefijo in PREFIJO_DE_EQUIVALENCIA.items():
            self.assertIn(f'&quot;{nivel}&quot;: &quot;{prefijo}&quot;', html)

    def test_el_formulario_de_edicion_muestra_la_equivalencia_actual(self):
        grado = crear_grado('PREESCOLAR', 2, equivalencia='K2')
        html = self.client.get(reverse('grados:editar', args=[grado.pk])).content.decode()
        self.assertRegex(html, r'name="equivalencia"[^>]*value="K2"')

    def test_el_formulario_valida_directamente(self):
        form = GradoForm(data=self.datos(nivel='SECUNDARIA', numero=2))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['equivalencia'], '8')
        form = GradoForm(data=self.datos(nivel='PREESCOLAR', numero=3))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['equivalencia'], 'K3')


@PRUEBAS
class EquivalenciaEnLasPantallasTests(BaseTestCase):
    def test_el_listado_muestra_las_equivalencias(self):
        crear_grado('SECUNDARIA', 1, equivalencia='7')
        crear_grado('PREESCOLAR', 1, equivalencia='K1')
        crear_grado('PRIMARIA', 1)   # sin equivalencia
        html = self.client.get(reverse('grados:lista')).content.decode()
        self.assertIn('Equivale al 7°', html)
        self.assertIn('Equivale a K1', html)
        self.assertEqual(html.count('grade-card__eq"'), 2)

    def test_el_perfil_del_grado_muestra_su_equivalencia(self):
        grado = crear_grado('SECUNDARIA', 1, equivalencia='7')
        html = self.client.get(reverse('grados:detalle', args=[grado.pk])).content.decode()
        self.assertIn('Equivale al 7°', html)
        self.assertRegex(html, r'<dt>Equivalencia</dt><dd>7°</dd>')

    def test_el_perfil_de_un_grado_con_codigo(self):
        grado = crear_grado('PREESCOLAR', 1, equivalencia='K1')
        html = self.client.get(reverse('grados:detalle', args=[grado.pk])).content.decode()
        self.assertIn('Equivale a K1', html)
        self.assertRegex(html, r'<dt>Equivalencia</dt><dd>K1</dd>')

    def test_sin_equivalencia_el_perfil_lo_dice(self):
        grado = crear_grado('PREESCOLAR', 1)
        html = self.client.get(reverse('grados:detalle', args=[grado.pk])).content.decode()
        self.assertIn('Sin equivalencia', html)
        self.assertNotIn('Equivale a', html)

    def test_los_archivos_del_formulario_existen(self):
        self.assertTrue((RAIZ / 'static/js/grados-form.js').is_file())
        css = (RAIZ / 'static/css/academico.css').read_text(encoding='utf-8')
        self.assertIn('.grade-card__eq', css)


class SiguienteGradoPorEquivalenciaTests(SimpleTestCase):
    def grado(self, nivel, numero, equivalencia=''):
        return Grado(nivel=nivel, numero=numero, equivalencia=equivalencia)

    def test_de_sexto_de_primaria_se_pasa_al_septimo_que_es_primero_de_secundaria(self):
        sexto = self.grado('PRIMARIA', 6, '6')
        primero = self.grado('SECUNDARIA', 1, '7')
        self.assertEqual(siguiente_grado(sexto, [sexto, primero, self.grado('SECUNDARIA', 2, '8')]), primero)

    def test_la_equivalencia_manda_sobre_el_orden_por_numero(self):
        sexto = self.grado('PRIMARIA', 6, '6')
        a = self.grado('SECUNDARIA', 1, '8')
        b = self.grado('SECUNDARIA', 2, '7')   # el colegio numeró distinto: el siguiente del 6 es el 7
        self.assertEqual(siguiente_grado(sexto, [sexto, a, b]), b)

    def test_un_codigo_con_letras_no_se_cuenta_y_se_usa_el_orden_por_nivel(self):
        k3 = self.grado('PREESCOLAR', 3, 'K3')
        primero = self.grado('PRIMARIA', 1, '1')
        self.assertEqual(siguiente_grado(k3, [k3, primero]), primero)

    def test_dentro_de_preescolar_el_siguiente_de_k1_es_k2(self):
        k1, k2 = self.grado('PREESCOLAR', 1, 'K1'), self.grado('PREESCOLAR', 2, 'K2')
        self.assertEqual(siguiente_grado(k1, [k1, k2]), k2)

    def test_sin_equivalencia_se_usa_el_orden_por_nivel_y_numero(self):
        tercero = self.grado('PREESCOLAR', 3)
        primero = self.grado('PRIMARIA', 1, '1')
        self.assertEqual(siguiente_grado(tercero, [tercero, primero]), primero)

    def test_si_no_existe_el_que_sigue_por_equivalencia_se_cae_al_orden_por_nivel(self):
        sexto = self.grado('PRIMARIA', 6, '6')
        primero = self.grado('SECUNDARIA', 1, '9')   # la equivalencia 7 no existe
        self.assertEqual(siguiente_grado(sexto, [sexto, primero]), primero)

    def test_el_ultimo_grado_no_tiene_siguiente(self):
        tercero = self.grado('SECUNDARIA', 3, '9')
        self.assertIsNone(siguiente_grado(tercero, [tercero]))


@PRUEBAS
class ReactivarGradoConEquivalenciaTests(BaseTestCase):
    def test_se_reactiva_si_su_equivalencia_sigue_libre(self):
        grado = crear_grado('SECUNDARIA', 1, equivalencia='7', activo=False)
        self.client.post(reverse('grados:reactivar', args=[grado.pk]))
        grado.refresh_from_db()
        self.assertTrue(grado.activo)

    def test_no_se_reactiva_si_otro_grado_vigente_tomo_su_equivalencia(self):
        grado = crear_grado('SECUNDARIA', 1, equivalencia='7', activo=False)
        crear_grado('PRIMARIA', 2, equivalencia='7')
        respuesta = self.client.post(reverse('grados:reactivar', args=[grado.pk]), follow=True)
        self.assertContains(respuesta, 'ya la tiene 2° Primaria')
        grado.refresh_from_db()
        self.assertFalse(grado.activo)

    def test_un_grado_sin_equivalencia_se_reactiva_siempre(self):
        grado = crear_grado('PREESCOLAR', 1, activo=False)
        self.client.post(reverse('grados:reactivar', args=[grado.pk]))
        grado.refresh_from_db()
        self.assertTrue(grado.activo)


class MigracionesDeEquivalenciaTests(BaseTestCase):
    def test_los_grados_existentes_reciben_la_equivalencia_habitual(self):
        migracion = importlib.import_module('Alumnos.migrations.0009_equivalencia_con_letras')
        grados = {
            (nivel, numero): crear_grado(nivel, numero)
            for nivel, numero in [('PREESCOLAR', 1), ('PRIMARIA', 1), ('PRIMARIA', 6), ('SECUNDARIA', 1), ('SECUNDARIA', 3), ('PREPARATORIA', 1)]
        }
        propia = crear_grado('PRIMARIA', 2, equivalencia='B2')
        migracion.llenar_equivalencias(registro, None)
        esperadas = {('PREESCOLAR', 1): 'K1', ('PRIMARIA', 1): '1', ('PRIMARIA', 6): '6', ('SECUNDARIA', 1): '7', ('SECUNDARIA', 3): '9', ('PREPARATORIA', 1): '10'}
        for clave, grado in grados.items():
            grado.refresh_from_db()
            self.assertEqual(grado.equivalencia, esperadas[clave], clave)
        propia.refresh_from_db()
        self.assertEqual(propia.equivalencia, 'B2')   # una equivalencia ya capturada no se pisa

    def test_las_migraciones_copian_las_mismas_reglas_que_el_codigo(self):
        for nombre in ('0008_grado_equivalencia', '0009_equivalencia_con_letras'):
            migracion = importlib.import_module(f'Alumnos.migrations.{nombre}')
            self.assertEqual(migracion.BASE_DE_EQUIVALENCIA, BASE_DE_EQUIVALENCIA, nombre)
        migracion = importlib.import_module('Alumnos.migrations.0009_equivalencia_con_letras')
        self.assertEqual(migracion.PREFIJO_DE_EQUIVALENCIA, PREFIJO_DE_EQUIVALENCIA)
