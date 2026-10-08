"""Alta de una materia: el grado que la imparte (uno solo), su profesor (opcional, de ese nivel, y confirmado si se deja
sin él) y la clave que se propone sola («MAT-1P»)."""
import importlib
import re
from datetime import time

from django.apps import apps
from django.test import SimpleTestCase
from django.urls import reverse

from Alumnos.models import HorarioMateria, Materia, MateriaGrado, ProfesorMateria
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    ciclo_cerrado_de_prueba,
    crear_grado,
    crear_profesor,
)

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
        self.assertEqual(codigo_de_grados([]), '')


@PRUEBAS
class AltaConGradoTests(BaseTestCase):
    url = '/materias/nueva/'

    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.primero = crear_grado('PRIMARIA', 1)
        self.segundo = crear_grado('PRIMARIA', 2)
        self.secundaria = crear_grado('SECUNDARIA', 1)

    def alta(self, **cambios):
        datos = {'nombre': 'Matemáticas', 'clave': '', 'grado': self.primero.pk, 'sin_profesor': '1'}
        datos.update(cambios)
        return self.client.post(self.url, {k: v for k, v in datos.items() if v is not None}, follow=True)

    def test_el_alta_pide_un_solo_grado_agrupado_por_nivel(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('Grado que la imparte', html)
        self.assertEqual(len(re.findall(r'<input[^>]*type="radio"[^>]*name="grado"', html)), 3)
        self.assertNotIn('type="checkbox"', html)                          # sin selección múltiple
        self.assertIn('data-nivel="PRIMARIA"', html)
        self.assertIn('nivel-casillas__titulo">Secundaria', html)
        self.assertIn(f'data-clave-url="{reverse("materias:clave")}"', html)
        self.assertIn('js/materia-form.js', html)

    def test_registra_la_materia_con_su_grado_y_la_agrega_al_plan_del_ciclo_actual(self):
        respuesta = self.alta()
        materia = Materia.objects.get()
        self.assertEqual((materia.clave, materia.grado), ('MAT-1P', self.primero))   # sin escribirla: la propuesta
        asignacion = MateriaGrado.objects.get(materia=materia)
        self.assertEqual((asignacion.ciclo, asignacion.grado, asignacion.activa, asignacion.profesor), (self.ciclo, self.primero, True, None))
        self.assertContains(respuesta, 'fue registrada con la clave MAT-1P y se agregó al plan de 1° Primaria (ciclo 2026-2027)')
        self.assertContains(respuesta, 'Queda sin profesor')

    def test_no_acepta_varios_grados(self):
        self.client.post(self.url, {'nombre': 'Matemáticas', 'clave': '', 'grado': [self.primero.pk, self.segundo.pk], 'sin_profesor': '1'})
        self.assertEqual(MateriaGrado.objects.count(), 1)                    # se queda con uno solo

    def test_con_un_grado_de_secundaria_la_clave_lleva_su_codigo(self):
        self.alta(nombre='Educación Física', grado=self.secundaria.pk)
        self.assertEqual(Materia.objects.get().clave, 'EF-1S')

    def test_la_clave_escrita_se_respeta(self):
        self.alta(clave='mate uno')
        self.assertEqual(Materia.objects.get().clave, 'MATE-UNO')

    def test_si_la_propuesta_ya_existe_se_numera(self):
        Materia.objects.create(clave='MAT-1P', nombre='Matemáticas')
        self.alta()
        self.assertTrue(Materia.objects.filter(clave='MAT-1P-2').exists())

    def test_hay_que_elegir_el_grado(self):
        respuesta = self.client.post(self.url, {'nombre': 'Matemáticas', 'clave': 'MAT'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Elige el grado que la imparte.')
        self.assertFalse(Materia.objects.exists())

    def test_quien_solo_registra_materias_tambien_la_deja_en_el_plan_de_su_grado(self):
        self.con_permisos('view_materia', 'add_materia')
        html = self.client.get(self.url).content.decode()
        self.assertIn('name="grado"', html)
        self.assertNotIn('name="profesor"', html)                          # asignar profesor pide otro permiso
        self.client.post(self.url, {'nombre': 'Matemáticas', 'clave': '', 'grado': self.primero.pk})
        materia = Materia.objects.get()
        self.assertEqual((materia.clave, materia.grado), ('MAT-1P', self.primero))
        self.assertTrue(MateriaGrado.objects.filter(materia=materia, grado=self.primero, ciclo=self.ciclo, activa=True).exists())


@PRUEBAS
class ProfesorAlRegistrarTests(BaseTestCase):
    url = '/materias/nueva/'

    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.primero = crear_grado('PRIMARIA', 1)
        self.secundaria = crear_grado('SECUNDARIA', 1)
        self.marta = crear_profesor(nombre='Marta', niveles=['PRIMARIA'])
        self.beto = crear_profesor(nombre='Beto', telefono='3530000002', niveles=['SECUNDARIA'])

    def test_cada_profesor_trae_sus_niveles_para_mostrar_solo_los_del_grado(self):
        html = self.client.get(self.url).content.decode()
        self.assertRegex(html, rf'<option value="{self.marta.pk}" data-niveles="PRIMARIA"')
        self.assertRegex(html, rf'<option value="{self.beto.pk}" data-niveles="SECUNDARIA"')
        self.assertIn('Sin profesor por ahora', html)
        self.assertIn('data-sin-profesor-aviso hidden', html)              # el aviso aparece al enviar sin profesor

    def test_registra_la_materia_con_su_profesor(self):
        respuesta = self.client.post(self.url, {'nombre': 'Matemáticas', 'clave': '', 'grado': self.primero.pk, 'profesor': self.marta.pk}, follow=True)
        asignacion = MateriaGrado.objects.get()
        self.assertEqual((asignacion.grado, asignacion.profesor), (self.primero, self.marta))
        self.assertTrue(ProfesorMateria.objects.filter(profesor=self.marta, materia=asignacion.materia).exists())
        self.assertContains(respuesta, f'La imparte {self.marta}')

    def test_no_acepta_un_profesor_de_otro_nivel(self):
        respuesta = self.client.post(self.url, {'nombre': 'Matemáticas', 'clave': '', 'grado': self.primero.pk, 'profesor': self.beto.pk})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, f'{self.beto} no da clases en Primaria')
        self.assertFalse(Materia.objects.exists())

    def test_sin_profesor_pide_confirmarlo(self):
        respuesta = self.client.post(self.url, {'nombre': 'Matemáticas', 'clave': '', 'grado': self.primero.pk})
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Materia.objects.exists())
        self.assertTrue(respuesta.context['form'].pide_confirmacion)
        html = respuesta.content.decode()
        self.assertIn('¿Seguro que quieres agregar la materia sin asignarle profesor?', html)
        self.assertNotIn('data-sin-profesor-aviso hidden', html)
        self.assertRegex(html, r'<button type="submit"[^>]*name="sin_profesor" value="1"')
        self.assertNotContains(respuesta, 'Revisa los campos marcados')   # no es un error: es una pregunta

    def test_confirmado_se_registra_sin_profesor(self):
        respuesta = self.client.post(self.url, {'nombre': 'Matemáticas', 'clave': '', 'grado': self.primero.pk, 'sin_profesor': '1'}, follow=True)
        self.assertIsNone(MateriaGrado.objects.get().profesor)
        self.assertContains(respuesta, 'Queda sin profesor')

    def test_sin_permiso_para_asignar_profesores_no_lo_pide(self):
        self.con_permisos('view_materia', 'add_materia', 'add_materiagrado')
        html = self.client.get(self.url).content.decode()
        self.assertNotIn('name="profesor"', html)
        self.assertNotIn('data-sin-profesor-aviso', html)
        self.client.post(self.url, {'nombre': 'Matemáticas', 'clave': '', 'grado': self.primero.pk})
        self.assertTrue(MateriaGrado.objects.filter(profesor__isnull=True).exists())

    def test_los_profesores_de_baja_no_se_ofrecen(self):
        baja = crear_profesor(nombre='Inés', telefono='3530000003', estatus='INACTIVO')
        html = self.client.get(self.url).content.decode()
        self.assertNotIn(f'<option value="{baja.pk}"', html)


@PRUEBAS
class EdicionDelGradoTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.primero = crear_grado('PRIMARIA', 1)
        self.segundo = crear_grado('PRIMARIA', 2)
        self.materia = Materia.objects.create(clave='MAT', nombre='Matemáticas', grado=self.primero)
        self.url = reverse('materias:editar', args=[self.materia.pk])

    def editar(self, **cambios):
        datos = {'nombre': 'Matemáticas', 'clave': 'MAT', 'grado': self.primero.pk}
        datos.update(cambios)
        return self.client.post(self.url, {k: v for k, v in datos.items() if v is not None})

    def test_la_edicion_ofrece_el_grado_y_no_el_profesor(self):
        html = self.client.get(self.url).content.decode()
        self.assertRegex(html, rf'<input[^>]*type="radio"[^>]*name="grado"[^>]*value="{self.primero.pk}"[^>]*checked')
        self.assertNotIn('name="profesor"', html)
        self.assertIn(f'data-excluir="{self.materia.pk}"', html)

    def test_la_clave_sigue_siendo_obligatoria(self):
        respuesta = self.editar(clave='')
        self.assertIn('clave', respuesta.context['form'].errors)

    def test_cambia_el_grado_si_no_se_imparte_en_el_anterior(self):
        self.assertEqual(self.editar(grado=self.segundo.pk).status_code, 302)
        self.materia.refresh_from_db()
        self.assertEqual(self.materia.grado, self.segundo)

    def test_al_cambiarle_el_grado_su_clase_del_ciclo_pasa_al_grado_nuevo(self):
        marta = crear_profesor(nombre='Marta', niveles=['PRIMARIA'])
        clase = MateriaGrado.objects.create(materia=self.materia, grado=self.primero, ciclo=self.ciclo, profesor=marta)
        respuesta = self.client.post(self.url, {'nombre': 'Matemáticas', 'clave': 'MAT', 'grado': self.segundo.pk}, follow=True)
        clase.refresh_from_db()
        self.assertEqual((clase.grado, clase.profesor, clase.activa), (self.segundo, marta, True))   # misma clase, mismo profesor
        self.assertEqual(MateriaGrado.objects.count(), 1)
        self.assertContains(respuesta, 'Su clase del ciclo 2026-2027 quedó en 2° Primaria')

    def test_a_otro_nivel_se_queda_sin_el_profesor_que_no_da_clases_ahi(self):
        secundaria = crear_grado('SECUNDARIA', 1)
        marta = crear_profesor(nombre='Marta', niveles=['PRIMARIA'])
        clase = MateriaGrado.objects.create(materia=self.materia, grado=self.primero, ciclo=self.ciclo, profesor=marta)
        respuesta = self.client.post(self.url, {'nombre': 'Matemáticas', 'clave': 'MAT', 'grado': secundaria.pk}, follow=True)
        clase.refresh_from_db()
        self.assertEqual((clase.grado, clase.profesor), (secundaria, None))
        self.assertContains(respuesta, f'{marta} dejó de impartirla porque no da clases en Secundaria')

    def test_no_cambia_de_grado_si_ya_tiene_horario(self):
        clase = MateriaGrado.objects.create(materia=self.materia, grado=self.primero, ciclo=self.ciclo)
        HorarioMateria.objects.create(materia_grado=clase, dia_semana=0, hora_inicio=time(8), hora_fin=time(9))
        respuesta = self.editar(grado=self.segundo.pk)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Ya tiene horario en 1° Primaria (2026-2027)')
        self.materia.refresh_from_db()
        self.assertEqual(self.materia.grado, self.primero)

    def test_un_horario_de_un_ciclo_cerrado_no_lo_impide(self):
        vieja = MateriaGrado.objects.create(materia=self.materia, grado=self.primero, ciclo=ciclo_cerrado_de_prueba())
        HorarioMateria.objects.create(materia_grado=vieja, dia_semana=0, hora_inicio=time(8), hora_fin=time(9))
        self.assertEqual(self.editar(grado=self.segundo.pk).status_code, 302)
        vieja.refresh_from_db()
        self.assertEqual(vieja.grado, self.primero)                       # la historia no se toca
        self.assertTrue(MateriaGrado.objects.filter(materia=self.materia, grado=self.segundo, ciclo=self.ciclo).exists())

    def test_a_una_materia_de_antes_al_elegirle_grado_queda_en_el_plan(self):
        vieja = Materia.objects.create(clave='OLD', nombre='Taller')
        self.client.post(reverse('materias:editar', args=[vieja.pk]), {'nombre': 'Taller', 'clave': 'OLD', 'grado': self.segundo.pk})
        self.assertTrue(MateriaGrado.objects.filter(materia=vieja, grado=self.segundo, ciclo=self.ciclo, activa=True).exists())

    def test_no_se_puede_quitar_el_grado(self):
        respuesta = self.editar(grado=None)
        self.assertContains(respuesta, 'Elige el grado que la imparte.')

    def test_una_materia_de_antes_sin_grado_se_puede_editar_sin_elegirlo(self):
        vieja = Materia.objects.create(clave='OLD', nombre='Taller')
        respuesta = self.client.post(reverse('materias:editar', args=[vieja.pk]), {'nombre': 'Taller de arte', 'clave': 'OLD'})
        self.assertEqual(respuesta.status_code, 302)


@PRUEBAS
class SinCicloActualTests(BaseTestCase):
    def test_sin_ciclo_actual_pide_el_grado_pero_no_lo_agrega_al_plan(self):
        primero = crear_grado('PRIMARIA', 1)
        html = self.client.get('/materias/nueva/').content.decode()
        self.assertIn('name="grado"', html)
        self.assertNotIn('name="profesor"', html)
        self.assertIn('No hay un ciclo escolar actual', html)
        self.client.post('/materias/nueva/', {'nombre': 'Inglés', 'clave': '', 'grado': primero.pk})
        materia = Materia.objects.get()
        self.assertEqual((materia.clave, materia.grado), ('ING-1P', primero))
        self.assertFalse(MateriaGrado.objects.exists())


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

    def test_propone_con_el_nombre_y_el_grado(self):
        self.assertEqual(self.sugerida(nombre='Matemáticas'), 'MAT')
        self.assertEqual(self.sugerida(nombre='Matemáticas', grado=[self.primero.pk]), 'MAT-1P')
        self.assertEqual(self.sugerida(nombre='Matemáticas', grado=[self.tercero.pk]), 'MAT-3S')
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
    def test_sin_grados_se_puede_registrar_sin_grado(self):
        ciclo_actual_de_prueba()
        html = self.client.get('/materias/nueva/').content.decode()
        self.assertNotIn('name="grado"', html)
        self.assertIn('Todavía no hay grados activos', html)
        self.assertEqual(self.client.post('/materias/nueva/', {'nombre': 'Arte', 'clave': ''}).status_code, 302)
        materia = Materia.objects.get()
        self.assertEqual((materia.clave, materia.grado), ('ART', None))


@PRUEBAS
class MigracionDelGradoTests(BaseTestCase):
    def test_cada_materia_toma_el_grado_en_el_que_se_imparte(self):
        migracion = importlib.import_module('Alumnos.migrations.0016_materia_grado')
        actual, cerrado = ciclo_actual_de_prueba(), ciclo_cerrado_de_prueba()
        primero, segundo, tercero = crear_grado('PRIMARIA', 1), crear_grado('PRIMARIA', 2), crear_grado('PRIMARIA', 3)
        una = Materia.objects.create(clave='UNA', nombre='Una')                 # un solo grado en su historia
        cambio = Materia.objects.create(clave='CAM', nombre='Cambió')           # antes en otro; hoy solo en uno
        varios = Materia.objects.create(clave='VAR', nombre='Varios')           # hoy en dos grados: se queda sin grado
        nada = Materia.objects.create(clave='NAD', nombre='Nada')               # nunca se impartió
        MateriaGrado.objects.create(materia=una, grado=primero, ciclo=cerrado)
        MateriaGrado.objects.create(materia=una, grado=primero, ciclo=actual)
        MateriaGrado.objects.create(materia=cambio, grado=primero, ciclo=cerrado)
        MateriaGrado.objects.create(materia=cambio, grado=segundo, ciclo=actual)
        MateriaGrado.objects.create(materia=varios, grado=segundo, ciclo=actual)
        MateriaGrado.objects.create(materia=varios, grado=tercero, ciclo=actual)
        migracion.grado_de_cada_materia(apps, None)
        grados = dict(Materia.objects.values_list('clave', 'grado'))
        self.assertEqual(grados, {'UNA': primero.pk, 'CAM': segundo.pk, 'VAR': None, 'NAD': None})


@PRUEBAS
class SiempreEnElPlanDeSuGradoTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.primero = crear_grado('PRIMARIA', 1)

    def test_al_reactivarla_vuelve_al_plan_de_su_grado(self):
        materia = Materia.objects.create(clave='MAT', nombre='Matemáticas', grado=self.primero, activa=False)
        respuesta = self.client.post(reverse('materias:reactivar', args=[materia.pk]), follow=True)
        self.assertTrue(MateriaGrado.objects.filter(materia=materia, grado=self.primero, ciclo=self.ciclo, activa=True).exists())
        self.assertContains(respuesta, 'Volvió al plan de 1° Primaria del ciclo 2026-2027')

    def test_la_migracion_pone_en_el_ciclo_actual_a_las_que_tienen_grado(self):
        migracion = importlib.import_module('Alumnos.migrations.0017_materias_en_el_plan_de_su_grado')
        fuera = Materia.objects.create(clave='MAT', nombre='Matemáticas', grado=self.primero)
        quitada = Materia.objects.create(clave='ESP', nombre='Español', grado=self.primero)
        MateriaGrado.objects.create(materia=quitada, grado=self.primero, ciclo=self.ciclo, activa=False)
        Materia.objects.create(clave='OLD', nombre='Sin grado')
        Materia.objects.create(clave='BAJ', nombre='De baja', grado=self.primero, activa=False)
        migracion.agregar_al_ciclo_actual(apps, None)
        migracion.agregar_al_ciclo_actual(apps, None)   # repetible
        plan = dict(MateriaGrado.objects.filter(ciclo=self.ciclo).values_list('materia__clave', 'activa'))
        self.assertEqual(plan, {'MAT': True, 'ESP': False})                # la quitada a propósito no se toca
        self.assertTrue(MateriaGrado.objects.filter(materia=fuera, grado=self.primero).exists())
