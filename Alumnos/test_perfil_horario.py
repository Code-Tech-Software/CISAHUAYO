"""Enlace al horario del grado desde el perfil del alumno."""
from django.urls import reverse

from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase, ciclo_actual_de_prueba, crear_alumno, crear_grado, inscribir


@PRUEBAS
class PerfilConHorarioTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.grado = crear_grado('PRIMARIA', 4)
        self.alumno = crear_alumno()
        self.inscripcion = inscribir(self.alumno, self.ciclo, self.grado)
        self.enlace = f"{reverse('horarios:grado', args=[self.grado.pk])}?ciclo={self.ciclo.pk}"

    def test_la_inscripcion_enlaza_con_el_horario_de_su_grado(self):
        self.assertContains(self.client.get(self.alumno.get_absolute_url()), self.enlace)

    def test_una_inscripcion_dada_de_baja_no_enlaza(self):
        self.inscripcion.activa = False
        self.inscripcion.save()
        self.assertNotContains(self.client.get(self.alumno.get_absolute_url()), self.enlace)

    def test_sin_permiso_para_ver_horarios_no_hay_enlace(self):
        self.con_permisos('view_alumno', 'view_inscripcion', 'view_tutor', 'view_grado', 'view_cicloescolar')
        self.assertNotContains(self.client.get(self.alumno.get_absolute_url()), self.enlace)
