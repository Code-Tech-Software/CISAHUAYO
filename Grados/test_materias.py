"""Pruebas del plan de materias dentro del perfil del grado (pestaña «Materias»)."""
from datetime import time

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from Alumnos.models import HorarioMateria, Materia, MateriaGrado
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    ciclo_cerrado_de_prueba,
    ciclo_proximo_de_prueba,
    crear_grado,
)


@PRUEBAS
class MateriasDelGradoTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba('2026-2027')
        self.cerrado = ciclo_cerrado_de_prueba('2025-2026')
        self.grado = crear_grado('PRIMARIA', 4)
        self.mat = Materia.objects.create(clave='MAT', nombre='Matemáticas')
        self.esp = Materia.objects.create(clave='ESP', nombre='Español')
        self.ing = Materia.objects.create(clave='ING', nombre='Inglés')
        Materia.objects.create(clave='OLD', nombre='Vieja', activa=False)
        self.a_mat = MateriaGrado.objects.create(ciclo=self.ciclo, grado=self.grado, materia=self.mat)
        self.a_esp = MateriaGrado.objects.create(ciclo=self.ciclo, grado=self.grado, materia=self.esp, activa=False)
        for dia in (0, 2):
            HorarioMateria.objects.create(materia_grado=self.a_mat, dia_semana=dia, hora_inicio=time(8, 0), hora_fin=time(9, 0))

    def detalle(self, **filtros):
        respuesta = self.client.get(self.grado.get_absolute_url(), filtros)
        self.assertEqual(respuesta.status_code, 200)
        return respuesta

    def test_muestra_el_plan_con_horario_y_marca_las_quitadas(self):
        respuesta = self.detalle()
        plan = {m.materia.clave: m for m in respuesta.context['materias']}
        self.assertEqual(plan['MAT'].lineas, ['Lun, Mié · 08:00–09:00'])
        self.assertEqual(plan['MAT'].duracion, '2 h')
        self.assertFalse(plan['ESP'].activa)
        self.assertEqual(respuesta.context['total_materias'], 1)            # la quitada no cuenta
        self.assertEqual(respuesta.context['horas_semanales'], '2 h')
        self.assertContains(respuesta, 'Volver a asignar')

    def test_ofrece_solo_las_materias_activas_que_faltan(self):
        pendientes = [m.clave for m in self.detalle().context['materias_por_asignar']]
        self.assertEqual(sorted(pendientes), ['ESP', 'ING'])               # la quitada puede volver; la de baja no se ofrece

    def test_el_plan_se_edita_en_el_ciclo_actual_y_en_el_proximo(self):
        self.assertTrue(self.detalle().context['plan_editable'])
        proximo = ciclo_proximo_de_prueba()
        self.assertTrue(self.detalle(ciclo=proximo.pk).context['plan_editable'])

    def test_un_ciclo_cerrado_es_de_solo_lectura(self):
        MateriaGrado.objects.create(ciclo=self.cerrado, grado=self.grado, materia=self.mat)
        respuesta = self.detalle(ciclo=self.cerrado.pk)
        self.assertFalse(respuesta.context['plan_editable'])
        self.assertEqual(respuesta.context['materias_por_asignar'], [])
        self.assertContains(respuesta, 'su plan de materias se conserva')
        self.assertNotContains(respuesta, 'data-quitar')

    def test_un_grado_de_baja_no_ofrece_asignar(self):
        self.grado.activo = False
        self.grado.save()
        respuesta = self.detalle()
        self.assertFalse(respuesta.context['plan_editable'])
        self.assertEqual(respuesta.context['materias_por_asignar'], [])

    def test_sin_permisos_de_asignacion_no_hay_botones(self):
        self.con_permisos('view_grado')
        respuesta = self.detalle()
        self.assertNotContains(respuesta, 'Asignar materias')
        self.assertNotContains(respuesta, 'data-quitar')

    def test_asignar_desde_el_grado_vuelve_a_su_pestana(self):
        destino = f'{self.grado.get_absolute_url()}#materias'
        respuesta = self.client.post(reverse('materias:asignar'), {
            'ciclo': self.ciclo.pk, 'grado': self.grado.pk, 'materia': [self.ing.pk, self.esp.pk], 'next': destino,
        })
        self.assertRedirects(respuesta, destino, fetch_redirect_response=False)
        self.assertEqual(MateriaGrado.objects.filter(grado=self.grado, ciclo=self.ciclo, activa=True).count(), 3)
        self.assertEqual(self.detalle().context['total_materias'], 3)

    def test_enlaza_con_el_horario_y_con_la_materia(self):
        respuesta = self.detalle()
        self.assertContains(respuesta, reverse('horarios:grado', args=[self.grado.pk]))
        self.assertContains(respuesta, self.mat.get_absolute_url())

    def test_consultas_constantes(self):
        with CaptureQueriesContext(connection) as pocas:
            self.detalle()
        for i in range(6):
            materia = Materia.objects.create(clave=f'X{i}', nombre=f'Extra {i}')
            asignacion = MateriaGrado.objects.create(ciclo=self.ciclo, grado=self.grado, materia=materia)
            HorarioMateria.objects.create(materia_grado=asignacion, dia_semana=1, hora_inicio=time(10 + i, 0), hora_fin=time(11 + i, 0))
        with CaptureQueriesContext(connection) as muchas:
            self.detalle()
        self.assertEqual(len(muchas), len(pocas))
