"""Inicio del portal de estudiantes: horario, clases de hoy, asistencia y calificaciones de los periodos cerrados."""
from datetime import date, time, timedelta
from decimal import Decimal

from django.test import Client
from django.urls import reverse

from Alumnos.models import AsistenciaGeneral, Justificacion, Periodo, Recreo
from Calificaciones.models import ActaCalificaciones
from CISAHUAYO.pruebas import (
    PRUEBAS, BaseAsistenciaTestCase, crear_alumno, inscribir_antes, lunes, materia_en_grado,
)

INICIO = reverse('portal_estudiantes:inicio')


class BasePortalEstudianteTestCase(BaseAsistenciaTestCase):
    """El alumno de BaseAsistenciaTestCase (MAT 8-9, ESP 9-10 y CIE 11-12 los lunes) con su cuenta del portal."""

    hora = (9, 30)

    def setUp(self):
        super().setUp()
        self.alumno.correo_electronico = 'luis@colegio.mx'
        self.alumno.establecer_contrasena('sol123')
        self.alumno.save()
        Recreo.objects.create(ciclo=self.ciclo, grado=self.grado, grupo=self.inscripcion.grupo, dia_semana=0,
                              hora_inicio=time(10, 0), hora_fin=time(10, 30))
        self.client = Client()
        self.client.post(reverse('login'), {'acceso': 'estudiantes', 'estudiantes-correo': 'luis@colegio.mx', 'estudiantes-contrasena': 'sol123'})

    def asistencia(self, dias_antes, estado, **extra):
        return AsistenciaGeneral.objects.create(inscripcion=self.inscripcion, fecha=lunes() - timedelta(days=dias_antes), estado=estado, **extra)


@PRUEBAS
class InicioDelEstudianteTests(BasePortalEstudianteTestCase):
    def test_muestra_su_grupo_y_el_horario_con_los_recesos(self):
        respuesta = self.client.get(INICIO)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context['inscripcion'], self.inscripcion)
        self.assertContains(respuesta, str(self.inscripcion.grupo))
        self.assertContains(respuesta, f'Referencia {self.alumno.referencia}')
        self.assertEqual(len(respuesta.context['cuadricula']['filas']), 4)   # tres clases y el receso
        self.assertContains(respuesta, 'Todo el grupo')
        # el horario es de consulta: sin enlaces para editarlo ni botones para quitar
        self.assertNotContains(respuesta, 'data-eliminar')
        self.assertNotContains(respuesta, reverse('horarios:editar', args=[self.mat.horarios.first().pk]))

    def test_las_clases_de_hoy_marcan_la_que_esta_en_curso(self):
        clases = self.client.get(INICIO).context['clases_hoy']
        self.assertEqual([(c.nombre, c.momento) for c in clases],
                         [('Mat', 'pasada'), ('Esp', 'ahora'), ('Receso', 'proxima'), ('Cie', 'proxima')])
        self.assertTrue(clases[2].es_receso)

    def test_un_dia_sin_clases_lo_dice(self):
        self.fijar_ahora(10, fecha=lunes() + timedelta(days=5))   # sábado sin horario
        respuesta = self.client.get(INICIO)
        self.assertEqual(respuesta.context['clases_hoy'], [])
        self.assertContains(respuesta, 'No hay clases en fin de semana.')

    def test_la_asistencia_del_ciclo(self):
        self.asistencia(0, 'RETARDO', hora_entrada=time(8, 15))
        self.asistencia(7, 'PRESENTE')
        self.asistencia(14, 'FALTA')
        falta = self.asistencia(21, 'FALTA')
        Justificacion.objects.create(inscripcion=self.inscripcion, fecha=falta.fecha, motivo='Cita médica', justifica_general=True)
        asistencia = self.client.get(INICIO).context['asistencia']
        self.assertEqual((asistencia['registros'], asistencia['presentes'], asistencia['retardos'], asistencia['faltas'],
                          asistencia['justificadas'], asistencia['sin_justificar']), (4, 1, 1, 2, 1, 1))
        self.assertEqual(asistencia['porcentaje'], 50)
        self.assertEqual(asistencia['hoy'].estado, 'RETARDO')
        self.assertEqual([r.estado for r in asistencia['incidencias']], ['RETARDO', 'FALTA', 'FALTA'])
        self.assertTrue(asistencia['incidencias'][2].justificada)
        respuesta = self.client.get(INICIO)
        self.assertContains(respuesta, 'Entrada a las 08:15')
        self.assertContains(respuesta, '50%')

    def test_solo_las_calificaciones_de_actas_cerradas(self):
        primero = Periodo.objects.create(ciclo=self.ciclo, nivel='PRIMARIA', nombre='Primer trimestre',
                                         fecha_inicio=self.ciclo.fecha_inicio, fecha_fin=self.ciclo.fecha_inicio + timedelta(days=60))
        segundo = Periodo.objects.create(ciclo=self.ciclo, nivel='PRIMARIA', nombre='Segundo trimestre',
                                         fecha_inicio=self.ciclo.fecha_inicio + timedelta(days=61), fecha_fin=self.ciclo.fecha_inicio + timedelta(days=120))
        Periodo.objects.create(ciclo=self.ciclo, nivel='SECUNDARIA', nombre='Otro nivel', fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 2, 1))
        otro = inscribir_antes(crear_alumno(), self.ciclo, self.grado)

        def acta(asignacion, periodo, final, estado=ActaCalificaciones.CERRADA):
            return ActaCalificaciones.objects.create(asignacion=asignacion, periodo=periodo, estado=estado, resultados_cerrados=[
                {'inscripcion': otro.pk, 'final': '5.00'}, {'inscripcion': self.inscripcion.pk, 'final': final},
            ])

        acta(self.mat, primero, '8.70')
        acta(self.esp, primero, '5.50')
        acta(self.mat, segundo, '9.30')
        acta(self.esp, segundo, '10.00', estado=ActaCalificaciones.EN_CAPTURA)   # en captura: todavía no se ve
        calificaciones = self.client.get(INICIO).context['calificaciones']
        self.assertEqual([p.nombre for p in calificaciones.periodos], ['Primer trimestre', 'Segundo trimestre'])
        filas = {f.materia: f for f in calificaciones.filas}
        self.assertEqual(filas['Mat'].valores, [Decimal('8.70'), Decimal('9.30')])
        self.assertEqual(filas['Mat'].promedio, Decimal('9.00'))
        self.assertEqual(filas['Esp'].valores, [Decimal('5.50'), None])
        self.assertEqual(filas['Cie'].valores, [None, None])
        self.assertEqual(calificaciones.promedios_por_periodo, [Decimal('7.10'), Decimal('9.30')])
        self.assertEqual(calificaciones.promedio_general, Decimal('7.25'))
        self.assertEqual(calificaciones.cerrados, 2)
        respuesta = self.client.get(INICIO)
        self.assertContains(respuesta, 'is-failing">5.50')
        self.assertNotContains(respuesta, '10.00')

    def test_sin_inscripcion_en_el_ciclo_actual(self):
        self.inscripcion.activa = False
        self.inscripcion.save()
        respuesta = self.client.get(INICIO)
        self.assertIsNone(respuesta.context['inscripcion'])
        self.assertContains(respuesta, 'Sin inscripción en el ciclo actual')
