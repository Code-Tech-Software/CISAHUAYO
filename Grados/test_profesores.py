"""El profesor en la pestaña «Materias» del perfil del grado."""
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from Alumnos.models import Materia, MateriaGrado
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    ciclo_cerrado_de_prueba,
    crear_grado,
    crear_profesor,
)


@PRUEBAS
class PlanDelGradoConProfesorTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.cerrado = ciclo_cerrado_de_prueba()
        self.grado = crear_grado('PRIMARIA', 4)
        self.profesor = crear_profesor()
        self.mat = Materia.objects.create(clave='MAT', nombre='Matemáticas')
        self.esp = Materia.objects.create(clave='ESP', nombre='Español')
        self.a_mat = MateriaGrado.objects.create(ciclo=self.ciclo, grado=self.grado, materia=self.mat, profesor=self.profesor)
        self.a_esp = MateriaGrado.objects.create(ciclo=self.ciclo, grado=self.grado, materia=self.esp)

    def detalle(self, **parametros):
        respuesta = self.client.get(self.grado.get_absolute_url(), parametros)
        self.assertEqual(respuesta.status_code, 200)
        return respuesta

    def test_muestra_el_profesor_de_cada_materia_y_marca_las_que_no_lo_tienen(self):
        respuesta = self.detalle()
        self.assertContains(respuesta, self.profesor.get_absolute_url())
        self.assertContains(respuesta, 'Sin profesor')
        self.assertEqual(respuesta.context['sin_profesor'], 1)

    def test_ofrece_asignar_con_los_profesores_activos(self):
        crear_profesor(nombre='Baja', telefono='3530000009', estatus='INACTIVO')
        respuesta = self.detalle()
        self.assertEqual(respuesta.context['profesores_activos'], [self.profesor])
        self.assertContains(respuesta, 'data-asignar-profesor')
        self.assertContains(respuesta, 'modal-asignar-profesor')

    def test_el_destino_de_la_ventana_regresa_a_la_pestana_de_materias(self):
        self.assertContains(self.detalle(), '#materias"')

    def test_un_ciclo_cerrado_es_de_solo_lectura(self):
        MateriaGrado.objects.create(ciclo=self.cerrado, grado=self.grado, materia=self.mat, profesor=self.profesor)
        respuesta = self.detalle(ciclo=self.cerrado.pk)
        self.assertContains(respuesta, self.profesor.get_absolute_url())
        self.assertNotContains(respuesta, 'data-asignar-profesor')

    def test_una_materia_quitada_no_cuenta_como_sin_profesor(self):
        self.a_esp.activa = False
        self.a_esp.save()
        self.assertEqual(self.detalle().context['sin_profesor'], 0)

    def test_sin_permiso_para_cambiar_no_hay_botones(self):
        self.con_permisos('view_grado', 'view_materiagrado', 'view_profesor')
        respuesta = self.detalle()
        self.assertNotContains(respuesta, 'data-asignar-profesor')
        self.assertContains(respuesta, self.profesor.get_absolute_url())

    def test_sin_permiso_para_ver_profesores_el_nombre_no_es_enlace(self):
        self.con_permisos('view_grado', 'view_materiagrado')
        respuesta = self.detalle()
        self.assertNotContains(respuesta, self.profesor.get_absolute_url())
        self.assertContains(respuesta, 'Marta Rangel Soto')

    def test_asignar_desde_el_grado_regresa_al_grado(self):
        destino = f'{self.grado.get_absolute_url()}?ciclo={self.ciclo.pk}#materias'
        respuesta = self.client.post(reverse('profesores:asignar'), {
            'asignacion': self.a_esp.pk, 'profesor': self.profesor.pk, 'next': destino,
        })
        self.assertRedirects(respuesta, destino, fetch_redirect_response=False)
        self.a_esp.refresh_from_db()
        self.assertEqual(self.a_esp.profesor, self.profesor)

    def test_consultas_constantes(self):
        with CaptureQueriesContext(connection) as pocas:
            self.detalle()
        for i in range(6):
            profesor = crear_profesor(nombre=f'P{i}', telefono=f'35300001{i:02d}')
            MateriaGrado.objects.create(
                ciclo=self.ciclo, grado=self.grado, materia=Materia.objects.create(clave=f'X{i}', nombre=f'Otra {i}'), profesor=profesor,
            )
        with CaptureQueriesContext(connection) as muchas:
            self.detalle()
        self.assertLessEqual(len(muchas), len(pocas) )
