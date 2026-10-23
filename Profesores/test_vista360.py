from datetime import date, timedelta

from django.urls import reverse

from Alumnos.models import AsistenciaMateria, Periodo
from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase, ciclo_actual_de_prueba, crear_grado, crear_profesor
from Profesores import vista360

from .tests import asignar, bloque, crear_materia


@PRUEBAS
class VistaDocenteTests(BaseTestCase):
    """Vista 360 del docente (2026-10-23): pendientes de asistencia y calificaciones, pestaña y expediente."""

    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.profesor = crear_profesor(emergencia_nombre='Rosa Lara', emergencia_parentesco='Hermana', emergencia_telefono='3531112233')
        self.asignacion = asignar(crear_materia(), crear_grado('PRIMARIA', 1), self.ciclo, profesor=self.profesor)
        # Un periodo abierto de dos semanas que empezó un lunes; la materia es los lunes y miércoles
        self.hoy = date(2026, 10, 21)   # miércoles
        self.periodo = Periodo.objects.create(ciclo=self.ciclo, nivel='PRIMARIA', nombre='Primer parcial',
                                              fecha_inicio=date(2026, 10, 12), fecha_fin=date(2026, 10, 30), apertura=Periodo.ABIERTO)
        bloque(self.asignacion, 0)
        bloque(self.asignacion, 2)

    def test_cuenta_los_dias_de_clase_sin_lista(self):
        pendientes = vista360.asistencias_por_capturar([self.asignacion], self.hoy)
        self.assertEqual(pendientes[0]['dias'], 4)   # 12, 14, 19 y 21 de octubre
        self.assertEqual(pendientes[0]['ultimo'], self.hoy)

    def test_actas_sin_cerrar_del_periodo_iniciado(self):
        pendientes = vista360.calificaciones_por_cerrar([self.asignacion], self.hoy)
        self.assertEqual([(p['periodo'], p['estado']) for p in pendientes], [(self.periodo, 'Sin empezar')])

    def test_sin_cuenta_no_hay_bitacoras_ni_reuniones(self):
        self.assertIsNone(vista360.bitacoras(self.profesor, self.ciclo))
        self.assertIsNone(vista360.reuniones(self.profesor))

    def test_perfil_y_expediente(self):
        respuesta = self.client.get(reverse('profesores:detalle', args=[self.profesor.pk]))
        self.assertContains(respuesta, 'Vista 360')
        self.assertContains(respuesta, 'Rosa Lara')
        expediente = self.client.get(reverse('profesores:expediente', args=[self.profesor.pk]))
        self.assertContains(expediente, 'Expediente del profesor')
        self.assertContains(expediente, 'Hermana')

    def test_expediente_pide_permiso(self):
        self.client.force_login(self.sin_permisos)
        self.assertEqual(self.client.get(reverse('profesores:expediente', args=[self.profesor.pk])).status_code, 403)
