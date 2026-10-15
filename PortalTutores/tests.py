"""Portal de tutores: solo los estudiantes con vínculo activo, con su resumen y su detalle."""
from django.test import Client
from django.urls import reverse

from Alumnos.models import AsistenciaGeneral
from CISAHUAYO.pruebas import (
    PRUEBAS, BaseAsistenciaTestCase, crear_alumno, crear_tutor, inscribir_antes, lunes, vincular,
)

INICIO = reverse('portal_tutores:inicio')


@PRUEBAS
class PortalDeTutoresTests(BaseAsistenciaTestCase):
    hora = (9, 30)

    def setUp(self):
        super().setUp()
        self.tutor = crear_tutor(usuario='rosa.mora')
        self.tutor.establecer_contrasena('luna456')
        self.tutor.save()
        vincular(self.tutor, self.alumno, parentesco='MADRE')
        self.hermana = crear_alumno(nombre='Ana')
        inscribir_antes(self.hermana, self.ciclo, self.grado)
        vincular(self.tutor, self.hermana, parentesco='MADRE')
        self.ajeno = crear_alumno(nombre='Pablo')
        self.anterior = crear_alumno(nombre='Iker')
        vincular(self.tutor, self.anterior, activo=False)   # el vínculo ya no está activo
        AsistenciaGeneral.objects.create(inscripcion=self.inscripcion, fecha=lunes(), estado='PRESENTE')
        self.client = Client()
        self.client.post(reverse('login'), {'acceso': 'tutores', 'tutores-usuario': 'rosa.mora', 'tutores-contrasena': 'luna456'})

    def test_ve_a_sus_estudiantes_con_vinculo_activo(self):
        respuesta = self.client.get(INICIO)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual([e['alumno'] for e in respuesta.context['estudiantes']], [self.hermana, self.alumno])
        self.assertContains(respuesta, '2 estudiantes a tu cargo')
        self.assertContains(respuesta, 'Presente')   # la entrada de hoy de Luis
        self.assertNotContains(respuesta, 'Iker')
        self.assertNotContains(respuesta, 'Pablo')
        self.assertContains(respuesta, reverse('portal_tutores:estudiante', args=[self.alumno.pk]))

    def test_el_detalle_de_uno_de_sus_estudiantes(self):
        respuesta = self.client.get(reverse('portal_tutores:estudiante', args=[self.alumno.pk]))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context['alumno'], self.alumno)
        self.assertContains(respuesta, 'Madre de')
        self.assertEqual(len(respuesta.context['cuadricula']['filas']), 3)
        self.assertEqual(respuesta.context['asistencia']['presentes'], 1)

    def test_no_ve_a_estudiantes_que_no_son_suyos(self):
        for alumno in (self.ajeno, self.anterior):
            with self.subTest(alumno=alumno.nombre):
                self.assertEqual(self.client.get(reverse('portal_tutores:estudiante', args=[alumno.pk])).status_code, 404)

    def test_sin_estudiantes_vinculados(self):
        self.tutor.alumnos_relacionados.update(activo=False)
        respuesta = self.client.get(INICIO)
        self.assertEqual(respuesta.context['estudiantes'], [])
        self.assertContains(respuesta, 'Todavía no tienes estudiantes vinculados')
