"""Un profesor solo imparte materias de los niveles en los que da clases, y una materia la imparte un solo grado.

Se revisa en cada camino que asigna: la lógica compartida (`asignar_profesor`), la ventana de asignar, pasar clases,
el perfil del profesor, el tablero, copiar el plan y agregar materias a un grado.
"""
import re

from django.urls import reverse

from Alumnos.docentes import asignar_profesor
from Alumnos.models import Materia, MateriaGrado
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    ciclo_proximo_de_prueba,
    crear_grado,
    crear_profesor,
    materia_en_grado,
)


class NivelTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.primaria = crear_grado('PRIMARIA', 2)
        self.secundaria = crear_grado('SECUNDARIA', 1)
        self.marta = crear_profesor(nombre='Marta', niveles=['PRIMARIA'])
        self.beto = crear_profesor(nombre='Beto', telefono='3530000002', niveles=['SECUNDARIA'])
        self.mat = materia_en_grado('MAT', self.primaria, self.ciclo)
        self.fis = materia_en_grado('FIS', self.secundaria, self.ciclo, dia=1)

    def mensajes(self):
        return [str(m) for m in self.client.get(reverse('materias:lista')).context['messages']]


@PRUEBAS
class AsignarProfesorPorNivelTests(NivelTestCase):
    def test_omite_las_materias_de_un_nivel_en_el_que_no_da_clases(self):
        cambios, omitidas = asignar_profesor([self.mat, self.fis], self.marta)
        self.assertEqual([asignacion for asignacion, _ in cambios], [self.mat])
        self.assertEqual(omitidas, [
            f'Fis de 1° Secundaria: {self.marta} no da clases en Secundaria. Agrégale ese nivel en su ficha para poder '
            'asignarle materias de ese nivel.',
        ])
        self.fis.refresh_from_db()
        self.assertIsNone(self.fis.profesor)

    def test_sin_niveles_no_se_le_asigna_nada(self):
        nadie = crear_profesor(nombre='Ceci', telefono='3530000003', niveles=())
        cambios, omitidas = asignar_profesor([self.mat], nadie)
        self.assertEqual((cambios, len(omitidas)), ([], 1))

    def test_quitar_al_profesor_no_depende_del_nivel(self):
        MateriaGrado.objects.filter(pk=self.fis.pk).update(profesor=self.marta)   # de antes de la regla
        self.fis.refresh_from_db()
        cambios, omitidas = asignar_profesor([self.fis], None)
        self.assertEqual((len(cambios), omitidas), (1, []))

    def test_dejar_al_mismo_profesor_de_antes_no_es_un_error(self):
        MateriaGrado.objects.filter(pk=self.fis.pk).update(profesor=self.marta)
        self.fis.refresh_from_db()
        self.assertEqual(asignar_profesor([self.fis], self.marta), ([], []))

    def test_la_ventana_de_asignar_lo_explica(self):
        self.client.post(reverse('profesores:asignar'), {'asignacion': [self.fis.pk], 'profesor': self.marta.pk})
        self.fis.refresh_from_db()
        self.assertIsNone(self.fis.profesor)
        self.assertTrue(any(f'{self.marta} no da clases en Secundaria' in mensaje for mensaje in self.mensajes()))

    def test_la_ventana_de_asignar_avisa_que_solo_salen_los_del_nivel(self):
        html = self.client.get(self.primaria.get_absolute_url()).content.decode()
        self.assertIn('data-asignar-nivel', html)


@PRUEBAS
class PasarClasesPorNivelTests(NivelTestCase):
    def test_solo_pasan_las_del_nivel_del_nuevo_profesor(self):
        ana = crear_profesor(nombre='Ana', telefono='3530000004', niveles=['PRIMARIA', 'SECUNDARIA'])
        MateriaGrado.objects.filter(pk__in=[self.mat.pk, self.fis.pk]).update(profesor=ana)
        self.client.post(reverse('asignaciones:transferir'), {'ciclo': self.ciclo.pk, 'origen': ana.pk, 'destino': self.marta.pk})
        self.mat.refresh_from_db()
        self.fis.refresh_from_db()
        self.assertEqual((self.mat.profesor, self.fis.profesor), (self.marta, ana))

    def test_la_ventana_solo_ofrece_profesores_de_sus_niveles(self):
        MateriaGrado.objects.filter(pk=self.mat.pk).update(profesor=self.marta)
        html = self.client.get(reverse('asignaciones:carga')).content.decode()
        boton = re.search(rf'<button[^>]*data-origen="{self.marta.pk}"[^>]*>', html).group(0)
        self.assertIn('data-niveles="PRIMARIA"', boton)
        self.assertRegex(html, rf'<option value="{self.beto.pk}" data-niveles="SECUNDARIA">')


@PRUEBAS
class TableroPorNivelTests(NivelTestCase):
    def test_las_filas_y_los_profesores_llevan_su_nivel_para_asignar_en_bloque(self):
        html = self.client.get(reverse('asignaciones:tablero')).content.decode()
        self.assertRegex(html, rf'value="{self.fis.pk}"[^>]*data-nivel="SECUNDARIA"')
        self.assertRegex(html, rf'<option value="{self.marta.pk}" data-niveles="PRIMARIA">')

    def test_asignar_en_bloque_omite_las_de_otro_nivel(self):
        self.client.post(reverse('profesores:asignar'), {'asignacion': [self.mat.pk, self.fis.pk], 'profesor': self.marta.pk})
        self.mat.refresh_from_db()
        self.fis.refresh_from_db()
        self.assertEqual((self.mat.profesor, self.fis.profesor), (self.marta, None))


@PRUEBAS
class PerfilDelProfesorPorNivelTests(NivelTestCase):
    def test_solo_le_ofrece_materias_de_sus_niveles(self):
        respuesta = self.client.get(self.marta.get_absolute_url())
        ofrecidas = [a for grupo in respuesta.context['pendientes'] for a in grupo['asignaciones']]
        self.assertEqual(ofrecidas, [self.mat])

    def test_sin_niveles_lo_explica(self):
        nadie = crear_profesor(nombre='Ceci', telefono='3530000003', niveles=())
        respuesta = self.client.get(nadie.get_absolute_url())
        self.assertEqual(respuesta.context['total_pendientes'], 0)
        self.assertContains(respuesta, 'Primero registra en su ficha los niveles en los que da clases.')


@PRUEBAS
class CopiarPlanPorNivelTests(NivelTestCase):
    def test_no_conserva_a_un_profesor_que_ya_no_da_clases_en_ese_nivel(self):
        MateriaGrado.objects.filter(pk=self.mat.pk).update(profesor=self.marta)
        MateriaGrado.objects.filter(pk=self.fis.pk).update(profesor=self.marta)   # de antes de la regla
        proximo = ciclo_proximo_de_prueba()
        self.client.post(reverse('materias:copiar'), {'origen': self.ciclo.pk, 'destino': proximo.pk, 'conservar_profesor': 'on'})
        copiadas = dict(MateriaGrado.objects.filter(ciclo=proximo).values_list('materia__clave', 'profesor'))
        self.assertEqual(copiadas, {'MAT': self.marta.pk, 'FIS': None})


@PRUEBAS
class UnGradoPorMateriaTests(NivelTestCase):
    def test_el_grado_solo_ofrece_sus_materias_y_las_que_no_tienen_grado(self):
        de_otro = Materia.objects.create(clave='QUI', nombre='Química', grado=self.secundaria)
        sin_grado = Materia.objects.create(clave='ART', nombre='Arte')
        suya = Materia.objects.create(clave='ESP', nombre='Español', grado=self.primaria)
        ofrecidas = self.client.get(self.primaria.get_absolute_url()).context['materias_por_asignar']
        self.assertIn(sin_grado, ofrecidas)
        self.assertIn(suya, ofrecidas)
        self.assertNotIn(de_otro, ofrecidas)

    def test_el_perfil_de_la_materia_solo_la_vuelve_a_agregar_a_su_grado(self):
        materia = Materia.objects.create(clave='ESP', nombre='Español', grado=self.primaria)
        html = self.client.get(materia.get_absolute_url()).content.decode()
        self.assertEqual(re.findall(r'<input type="hidden" name="grado" value="(\d+)"', html), [str(self.primaria.pk)])
        self.assertIn('Agregar al plan de 2° Primaria', html)

    def test_no_se_reactiva_en_un_grado_que_no_es_el_suyo(self):
        materia = Materia.objects.create(clave='ESP', nombre='Español', grado=self.secundaria)
        quitada = MateriaGrado.objects.create(materia=materia, grado=self.primaria, ciclo=self.ciclo, activa=False)
        self.client.post(reverse('materias:reactivar_asignacion', args=[quitada.pk]))
        quitada.refresh_from_db()
        self.assertFalse(quitada.activa)
