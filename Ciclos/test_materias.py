"""Pruebas de los atajos del ciclo hacia el plan de materias y los horarios."""
from django.urls import reverse

from Alumnos.models import Materia, MateriaGrado
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    ciclo_cerrado_de_prueba,
    ciclo_proximo_de_prueba,
    crear_ciclo,
    crear_grado,
)


@PRUEBAS
class AtajosDeMateriasTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.actual = ciclo_actual_de_prueba('2026-2027')
        self.proximo = ciclo_proximo_de_prueba('2027-2028')
        self.cerrado = ciclo_cerrado_de_prueba('2025-2026')
        self.grado = crear_grado()
        self.materia = Materia.objects.create(clave='MAT', nombre='Matemáticas')

    def asignar(self, ciclo, **cambios):
        return MateriaGrado.objects.create(ciclo=ciclo, grado=self.grado, materia=self.materia, **cambios)

    def test_ofrece_copiar_el_plan_del_ciclo_anterior_que_lo_tiene(self):
        self.assertIsNone(self.client.get(self.proximo.get_absolute_url()).context['origen_plan'])      # nadie tiene plan todavía
        self.asignar(self.actual)
        respuesta = self.client.get(self.proximo.get_absolute_url())
        self.assertEqual(respuesta.context['origen_plan'], self.actual)
        self.assertContains(respuesta, f'origen={self.actual.pk}&amp;destino={self.proximo.pk}')
        self.assertContains(respuesta, 'Copiar materias y horarios de 2026-2027')

    def test_un_plan_con_todo_quitado_no_cuenta(self):
        self.asignar(self.actual, activa=False)
        self.assertIsNone(self.client.get(self.proximo.get_absolute_url()).context['origen_plan'])

    def test_un_ciclo_cerrado_no_ofrece_copiar_hacia_si_mismo(self):
        antiguo = crear_ciclo('2024-2025', -800, -440)
        self.asignar(antiguo)
        self.assertIsNone(self.client.get(self.cerrado.get_absolute_url()).context['origen_plan'])   # nadie copia a un ciclo cerrado
        self.assertEqual(self.client.get(self.actual.get_absolute_url()).context['origen_plan'], antiguo)  # pero sí desde uno cerrado

    def test_cuenta_las_materias_asignadas_y_enlaza_a_los_horarios(self):
        self.asignar(self.actual)
        respuesta = self.client.get(self.actual.get_absolute_url())
        self.assertEqual(respuesta.context['materias_del_ciclo'], 1)
        self.assertContains(respuesta, f"{reverse('horarios:lista')}?ciclo={self.actual.pk}")
