"""Alta de una materia: los grados en los que se imparte y la clave que se propone sola («MAT-1P»)."""
import re

from django.test import SimpleTestCase
from django.urls import reverse

from Alumnos.models import Materia, MateriaGrado
from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase, ciclo_actual_de_prueba, crear_grado

from .claves import codigo_de_grados, iniciales_de_materia


class Grado:
    """Lo mínimo de un grado para probar la clave sin base de datos."""

    def __init__(self, nivel, numero):
        self.nivel, self.numero = nivel, numero


class PartesDeLaClaveTests(SimpleTestCase):
    def test_iniciales(self):
        casos = {
            'Matemáticas': 'MAT', 'Español': 'ESP', 'Inglés': 'ING', 'Educación Física': 'EF',
            'Formación Cívica y Ética': 'FCE', 'Ciencias Naturales y la Sociedad': 'CNS', 'TICs': 'TIC', '': '', '¿?': '',
        }
        for nombre, esperado in casos.items():
            self.assertEqual(iniciales_de_materia(nombre), esperado, nombre)

    def test_codigo_del_grado(self):
        self.assertEqual(codigo_de_grados([Grado('PRIMARIA', 1)]), '1P')
        self.assertEqual(codigo_de_grados([Grado('SECUNDARIA', 3)]), '3S')
        self.assertEqual(codigo_de_grados([Grado('PREESCOLAR', 2)]), '2K')
        self.assertEqual(codigo_de_grados([Grado('PREPARATORIA', 1)]), '1B')
        self.assertEqual(codigo_de_grados([Grado('PRIMARIA', 1), Grado('PRIMARIA', 2)]), 'P')
        self.assertEqual(codigo_de_grados([Grado('PRIMARIA', 6), Grado('SECUNDARIA', 1)]), '')
        self.assertEqual(codigo_de_grados([]), '')


@PRUEBAS
class AltaConGradosTests(BaseTestCase):
    url = '/materias/nueva/'

    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.primero = crear_grado('PRIMARIA', 1)
        self.segundo = crear_grado('PRIMARIA', 2)
        self.secundaria = crear_grado('SECUNDARIA', 1)

    def test_el_alta_pide_los_grados_agrupados_por_nivel(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('Grados en los que se imparte', html)
        self.assertEqual(len(re.findall(r'<input[^>]*type="checkbox"[^>]*name="grados"', html)), 3)
        self.assertIn('nivel-casillas__titulo">Primaria', html)
        self.assertIn('nivel-casillas__titulo">Secundaria', html)
        self.assertIn(f'data-clave-url="{reverse("materias:clave")}"', html)
        self.assertIn('js/materia-form.js', html)

    def test_registra_la_materia_y_la_agrega_al_plan_del_ciclo_actual(self):
        respuesta = self.client.post(self.url, {'nombre': 'Matemáticas', 'clave': '', 'grados': [self.primero.pk, self.segundo.pk]}, follow=True)
        materia = Materia.objects.get()
        self.assertEqual(materia.clave, 'MAT-P')                     # sin escribirla: la propuesta
        self.assertEqual(
            set(MateriaGrado.objects.filter(materia=materia, ciclo=self.ciclo, activa=True).values_list('grado', flat=True)),
            {self.primero.pk, self.segundo.pk},
        )
        self.assertContains(respuesta, 'fue registrada con la clave MAT-P y se agregó al plan de 1° Primaria, 2° Primaria')

    def test_con_un_solo_grado_la_clave_lleva_el_grado(self):
        self.client.post(self.url, {'nombre': 'Educación Física', 'clave': '', 'grados': [self.secundaria.pk]})
        self.assertEqual(Materia.objects.get().clave, 'EF-1S')

    def test_la_clave_escrita_se_respeta(self):
        self.client.post(self.url, {'nombre': 'Matemáticas', 'clave': 'mate uno', 'grados': [self.primero.pk]})
        self.assertEqual(Materia.objects.get().clave, 'MATE-UNO')

    def test_si_la_propuesta_ya_existe_se_numera(self):
        Materia.objects.create(clave='MAT-1P', nombre='Matemáticas')
        self.client.post(self.url, {'nombre': 'Matemáticas', 'clave': '', 'grados': [self.primero.pk]})
        self.assertTrue(Materia.objects.filter(clave='MAT-1P-2').exists())

    def test_hay_que_elegir_al_menos_un_grado(self):
        respuesta = self.client.post(self.url, {'nombre': 'Matemáticas', 'clave': 'MAT'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Elige al menos un grado.')
        self.assertFalse(Materia.objects.exists())

    def test_la_edicion_no_pide_grados_y_respeta_la_clave(self):
        materia = Materia.objects.create(clave='MAT', nombre='Matemáticas')
        html = self.client.get(reverse('materias:editar', args=[materia.pk])).content.decode()
        self.assertNotIn('name="grados"', html)
        self.assertIn(f'data-excluir="{materia.pk}"', html)
        respuesta = self.client.post(reverse('materias:editar', args=[materia.pk]), {'nombre': 'Matemáticas', 'clave': ''})
        self.assertIn('clave', respuesta.context['form'].errors)   # al editar sigue siendo obligatoria

    def test_sin_permiso_para_el_plan_se_registra_solo_en_el_catalogo(self):
        self.con_permisos('view_materia', 'add_materia')
        html = self.client.get(self.url).content.decode()
        self.assertNotIn('name="grados"', html)
        self.client.post(self.url, {'nombre': 'Matemáticas', 'clave': ''})
        self.assertEqual(Materia.objects.get().clave, 'MAT')
        self.assertFalse(MateriaGrado.objects.exists())


@PRUEBAS
class SinCicloActualTests(BaseTestCase):
    def test_sin_ciclo_actual_no_pide_grados(self):
        crear_grado('PRIMARIA', 1)
        html = self.client.get('/materias/nueva/').content.decode()
        self.assertNotIn('name="grados"', html)
        self.assertIn('No hay un ciclo escolar actual', html)
        self.client.post('/materias/nueva/', {'nombre': 'Inglés', 'clave': ''})
        self.assertEqual(Materia.objects.get().clave, 'ING')


@PRUEBAS
class ClavePropuestaTests(BaseTestCase):
    url = '/materias/clave/'

    def setUp(self):
        super().setUp()
        self.primero = crear_grado('PRIMARIA', 1)
        self.tercero = crear_grado('SECUNDARIA', 3)

    def sugerida(self, **parametros):
        respuesta = self.client.get(self.url, parametros)
        self.assertEqual(respuesta.status_code, 200)
        return respuesta.json()['sugerida']

    def test_propone_con_el_nombre_y_los_grados(self):
        self.assertEqual(self.sugerida(nombre='Matemáticas'), 'MAT')
        self.assertEqual(self.sugerida(nombre='Matemáticas', grado=[self.primero.pk]), 'MAT-1P')
        self.assertEqual(self.sugerida(nombre='Matemáticas', grado=[self.primero.pk, self.tercero.pk]), 'MAT')
        self.assertEqual(self.sugerida(nombre=''), '')

    def test_no_repite_una_clave_que_ya_existe_salvo_la_de_la_propia_materia(self):
        materia = Materia.objects.create(clave='MAT-1P', nombre='Matemáticas')
        self.assertEqual(self.sugerida(nombre='Matemáticas', grado=[self.primero.pk]), 'MAT-1P-2')
        self.assertEqual(self.sugerida(nombre='Matemáticas', grado=[self.primero.pk], excluir=materia.pk), 'MAT-1P')

    def test_la_usa_quien_puede_registrar_o_editar_materias(self):
        self.con_permisos('view_materia')
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.con_permisos('add_materia')
        self.assertEqual(self.client.get(self.url, {'nombre': 'Arte'}).status_code, 200)


@PRUEBAS
class SinGradosTests(BaseTestCase):
    def test_con_ciclo_pero_sin_grados_se_puede_registrar_igual(self):
        ciclo_actual_de_prueba()
        html = self.client.get('/materias/nueva/').content.decode()
        self.assertNotIn('name="grados"', html)
        self.assertIn('Todavía no hay grados activos', html)
        self.assertEqual(self.client.post('/materias/nueva/', {'nombre': 'Arte', 'clave': ''}).status_code, 302)
        self.assertEqual(Materia.objects.get().clave, 'ART')

    def test_sin_permiso_lo_explica(self):
        ciclo_actual_de_prueba()
        crear_grado('PRIMARIA', 1)
        self.con_permisos('view_materia', 'add_materia')
        self.assertContains(self.client.get('/materias/nueva/'), 'No tienes permiso para modificar el plan de materias')
