"""Reportes de asistencia por grado e historial de un alumno."""
import csv
import io
from datetime import time, timedelta

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from Alumnos import asistencias as reglas
from Alumnos.models import AsistenciaGeneral, AsistenciaMateria, DiaNoLectivo, Justificacion
from Asistencias.tests import entrar, url
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseAsistenciaTestCase,
    ciclo_cerrado_de_prueba,
    crear_alumno,
    crear_grado,
    inscribir_antes,
    lunes,
    materia_en_grado,
)


class BaseReporteTests(BaseAsistenciaTestCase):
    """Tres alumnos de 4° con tres lunes de asistencia: A siempre presente; B presente, retardo y falta; C falta
    justificada, falta y presente."""

    hora = (10, 30)

    def setUp(self):
        super().setUp()
        self.b = inscribir_antes(crear_alumno(nombre='Beto', apellido_paterno='Mora'), self.ciclo, self.grado)
        self.c = inscribir_antes(crear_alumno(nombre='Carla', apellido_paterno='Nava'), self.ciclo, self.grado)
        self.d1, self.d2, self.d3 = lunes() - timedelta(days=14), lunes() - timedelta(days=7), lunes()
        for dia in (self.d1, self.d2, self.d3):
            entrar(self.alumno, (7, 45), dia)
        entrar(self.b.alumno, (7, 50), self.d1)
        entrar(self.b.alumno, (8, 30), self.d2)
        reglas.fijar_asistencia_general(self.b, self.d3, 'FALTA')
        reglas.fijar_asistencia_general(self.c, self.d1, 'FALTA')
        reglas.fijar_asistencia_general(self.c, self.d2, 'FALTA')
        entrar(self.c.alumno, (7, 55), self.d3)
        Justificacion.objects.create(inscripcion=self.c, fecha=self.d1, motivo='Cita', justifica_general=True, todas_materias=True)

    def consulta(self, **extra):
        datos = {'grado': self.grado.pk, 'desde': self.d1.isoformat(), 'hasta': self.d3.isoformat()}
        datos.update(extra)
        return datos


@PRUEBAS
class ReporteTests(BaseReporteTests):
    def reporte(self, **extra):
        respuesta = self.client.get(url('reporte'), self.consulta(**extra))
        self.assertEqual(respuesta.status_code, 200)
        return respuesta

    def filas(self, respuesta):
        return {str(f.alumno): f for f in respuesta.context['filas']}

    def test_sin_grado_pide_elegir_uno(self):
        respuesta = self.client.get(url('reporte'))
        self.assertContains(respuesta, 'Elige un grado')
        self.assertEqual(respuesta.context['filas'], [])

    def test_resumen_por_alumno(self):
        filas = self.filas(self.reporte())
        self.assertEqual(filas[str(self.alumno)].cuenta, {'registros': 3, 'presentes': 3, 'retardos': 0, 'faltas': 0, 'justificadas': 0})
        self.assertEqual(filas[str(self.b.alumno)].cuenta, {'registros': 3, 'presentes': 1, 'retardos': 1, 'faltas': 1, 'justificadas': 0})
        self.assertEqual(filas[str(self.c.alumno)].cuenta, {'registros': 3, 'presentes': 1, 'retardos': 0, 'faltas': 2, 'justificadas': 1})

    def test_porcentaje_y_marca_de_quien_esta_bajo_el_umbral(self):
        filas = self.filas(self.reporte())
        self.assertEqual([filas[str(a.alumno)].porcentaje for a in (self.inscripcion, self.b, self.c)], [100, 67, 33])
        self.assertEqual([filas[str(a.alumno)].bajo_umbral for a in (self.inscripcion, self.b, self.c)], [False, True, True])
        self.assertEqual(filas[str(self.c.alumno)].sin_justificar, 1)
        self.assertContains(self.reporte(), 'Bajo 85%')

    def test_totales_del_grupo(self):
        self.assertEqual(self.reporte().context['total'], {'registros': 9, 'presentes': 5, 'retardos': 1, 'faltas': 3, 'justificadas': 1, 'porcentaje': 67})

    def test_los_alumnos_van_en_orden_alfabetico_y_sin_las_bajas(self):
        inscribir_antes(crear_alumno(estatus='BAJA'), self.ciclo, self.grado)
        self.assertEqual([str(f.alumno) for f in self.reporte().context['filas']], [str(self.b.alumno), str(self.c.alumno), str(self.alumno)])

    def test_solo_cuenta_el_periodo_pedido(self):
        respuesta = self.reporte(desde=self.d2.isoformat(), hasta=self.d2.isoformat())
        self.assertEqual(respuesta.context['total']['registros'], 3)

    def test_por_materia_usa_la_asistencia_de_esa_clase(self):
        AsistenciaMateria.objects.filter(inscripcion=self.inscripcion, materia_grado=self.mat, fecha=self.d1).update(estado='FALTA')
        respuesta = self.reporte(materia=self.mat.pk)
        self.assertEqual(respuesta.context['asignacion'], self.mat)
        self.assertEqual(self.filas(respuesta)[str(self.alumno)].cuenta['faltas'], 1)
        self.assertContains(respuesta, 'Mat')

    def test_una_materia_de_otro_grado_se_ignora(self):
        ajena = materia_en_grado('HIS', crear_grado('PRIMARIA', 5), self.ciclo)
        self.assertIsNone(self.reporte(materia=ajena.pk).context['asignacion'])

    def test_por_omision_muestra_el_mes_en_curso_hasta_hoy(self):
        respuesta = self.client.get(url('reporte'), {'grado': self.grado.pk})
        self.assertEqual((respuesta.context['desde'], respuesta.context['hasta']), (lunes().replace(day=1), lunes()))

    def test_el_periodo_no_sale_del_ciclo(self):
        respuesta = self.reporte(desde=(lunes() - timedelta(days=900)).isoformat(), hasta=(lunes() + timedelta(days=900)).isoformat())
        self.assertEqual((respuesta.context['desde'], respuesta.context['hasta']), (self.ciclo.fecha_inicio, self.ciclo.fecha_fin))

    def test_un_grado_sin_alumnos(self):
        respuesta = self.reporte(grado=crear_grado('PRIMARIA', 5).pk)
        self.assertContains(respuesta, 'no tiene estudiantes inscritos')

    def test_un_ciclo_cerrado_tambien_se_puede_consultar(self):
        cerrado = ciclo_cerrado_de_prueba()
        inscribir_antes(crear_alumno(), cerrado, self.grado)
        respuesta = self.reporte(ciclo=cerrado.pk, desde=cerrado.fecha_inicio.isoformat(), hasta=cerrado.fecha_fin.isoformat())
        self.assertEqual(respuesta.context['ciclo'], cerrado)
        self.assertEqual(len(respuesta.context['filas']), 1)

    def test_consultas_constantes(self):
        with CaptureQueriesContext(connection) as pocas:
            self.reporte()
        for _ in range(12):
            inscripcion = inscribir_antes(crear_alumno(), self.ciclo, self.grado)
            entrar(inscripcion.alumno, (7, 40), self.d3)
        with CaptureQueriesContext(connection) as muchas:
            self.reporte()
        self.assertEqual(len(muchas), len(pocas))


@PRUEBAS
class CuadriculaTests(BaseReporteTests):
    def cuadricula(self, **extra):
        respuesta = self.client.get(url('reporte'), self.consulta(vista='cuadricula', **extra))
        self.assertEqual(respuesta.status_code, 200)
        return respuesta

    def test_una_celda_por_dia_de_clases_con_su_letra(self):
        respuesta = self.cuadricula()
        dias = respuesta.context['dias']
        self.assertEqual(len(dias), 11)                               # tres semanas hábiles, hasta el lunes de hoy
        self.assertTrue(all(d.weekday() < 5 for d in dias))
        celdas = {str(f.alumno): dict(zip(dias, f.celdas)) for f in respuesta.context['filas']}
        self.assertEqual([celdas[str(self.alumno)][d] for d in (self.d1, self.d2, self.d3)], ['A', 'A', 'A'])
        self.assertEqual([celdas[str(self.b.alumno)][d] for d in (self.d1, self.d2, self.d3)], ['A', 'R', 'F'])
        self.assertEqual([celdas[str(self.c.alumno)][d] for d in (self.d1, self.d2, self.d3)], ['J', 'F', 'A'])
        self.assertEqual(celdas[str(self.alumno)][self.d1 + timedelta(days=1)], '')

    def test_los_dias_sin_clases_no_son_columnas(self):
        DiaNoLectivo.objects.create(fecha=self.d1 + timedelta(days=1), motivo='Puente')
        self.assertNotIn(self.d1 + timedelta(days=1), self.cuadricula().context['dias'])

    def test_con_mas_de_31_dias_avisa(self):
        respuesta = self.cuadricula(desde=(lunes() - timedelta(days=60)).isoformat())
        self.assertFalse(respuesta.context['cuadricula_posible'])
        self.assertContains(respuesta, 'hasta 31 días')

    def test_muestra_la_leyenda(self):
        self.assertContains(self.cuadricula(), 'falta justificada')


@PRUEBAS
class ExportarReporteTests(BaseReporteTests):
    def filas(self, **extra):
        respuesta = self.client.get(url('reporte_exportar'), self.consulta(**extra))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('text/csv', respuesta['Content-Type'])
        self.assertIn('attachment; filename="asistencia-primaria-4-', respuesta['Content-Disposition'])
        contenido = respuesta.content.decode('utf-8')
        self.assertTrue(contenido.startswith('﻿'))
        return list(csv.reader(io.StringIO(contenido.lstrip('﻿'))))

    def test_exporta_el_resumen(self):
        filas = self.filas()
        self.assertIn('4° Primaria', filas[0][0])
        self.assertEqual(filas[1][:3], ['Estudiante', 'Referencia', 'Días registrados'])
        self.assertEqual([f[0] for f in filas[2:]], [str(self.b.alumno), str(self.c.alumno), str(self.alumno)])
        self.assertEqual(filas[3][2:], ['3', '1', '0', '2', '1', '33'])

    def test_exporta_la_cuadricula(self):
        filas = self.filas(vista='cuadricula')
        self.assertEqual(filas[1][:2], ['Estudiante', 'Referencia'])
        self.assertEqual(len(filas[1]), 2 + 11)
        self.assertIn('A = asistió', filas[-1][0])

    def test_neutraliza_formulas_de_excel(self):
        self.b.alumno.nombre = '=Beto'
        self.b.alumno.save()
        self.assertTrue(self.filas()[2][0].startswith("'="))

    def test_sin_grado_no_exporta(self):
        respuesta = self.client.get(url('reporte_exportar'), follow=True)
        self.assertRedirects(respuesta, url('reporte'))
        self.assertContains(respuesta, 'Elige un grado')


# ---------------------------------------------------------------------------
# Historial de un alumno
# ---------------------------------------------------------------------------
@PRUEBAS
class HistorialDelAlumnoTests(BaseReporteTests):
    def historial(self, alumno=None, **consulta):
        respuesta = self.client.get(url('alumno', (alumno or self.c.alumno).pk, **consulta))
        self.assertEqual(respuesta.status_code, 200)
        return respuesta

    def test_resume_el_ciclo(self):
        resumen = self.historial().context['resumen']
        self.assertEqual((resumen['registros'], resumen['presentes'], resumen['faltas'], resumen['justificadas'], resumen['sin_justificar'], resumen['porcentaje']), (3, 1, 2, 1, 1, 33))

    def test_lista_los_dias_del_mas_reciente_al_mas_antiguo_con_sus_materias(self):
        pagina = self.historial().context['pagina']
        self.assertEqual([g.fecha for g in pagina], [self.d3, self.d2, self.d1])
        self.assertEqual([g.justificada for g in pagina], [False, False, True])
        self.assertEqual(sorted(r.materia_grado.materia.clave for r in pagina[0].materias), ['CIE', 'ESP', 'MAT'])

    def test_las_faltas_de_materia_tambien_se_ven_justificadas(self):
        justificadas = [r for g in self.historial().context['pagina'] for r in g.materias if r.justificada]
        self.assertEqual(len(justificadas), 3)                       # el lunes justificado cubre sus tres materias

    def test_resume_por_materia(self):
        por_materia = {f['clave']: f for f in self.historial().context['por_materia']}
        self.assertEqual({k: por_materia['MAT'][k] for k in ('registros', 'presentes', 'faltas', 'justificadas', 'porcentaje')}, {'registros': 3, 'presentes': 1, 'faltas': 2, 'justificadas': 1, 'porcentaje': 33})
        self.assertEqual(sorted(por_materia), ['CIE', 'ESP', 'MAT'])

    def test_pagina(self):
        for i in range(25):
            AsistenciaGeneral.objects.create(inscripcion=self.c, fecha=self.d1 - timedelta(days=i + 1), estado='PRESENTE', origen='MANUAL')
        respuesta = self.historial()
        self.assertEqual((respuesta.context['pagina'].paginator.count, len(respuesta.context['pagina'])), (28, 20))

    def test_elige_el_ciclo(self):
        cerrado = ciclo_cerrado_de_prueba()
        inscribir_antes(self.c.alumno, cerrado, self.grado)
        respuesta = self.historial()
        self.assertEqual(respuesta.context['ciclo'], self.ciclo)
        self.assertEqual(len(respuesta.context['ciclos']), 2)
        respuesta = self.historial(ciclo=cerrado.pk)
        self.assertEqual(respuesta.context['ciclo'], cerrado)
        self.assertContains(respuesta, 'Sin registros de asistencia')

    def test_un_alumno_sin_inscripcion(self):
        respuesta = self.historial(crear_alumno())
        self.assertContains(respuesta, 'no tiene inscripciones')

    def test_alumno_inexistente_da_404(self):
        self.assertEqual(self.client.get(url('alumno', 9999)).status_code, 404)

    def test_el_perfil_del_alumno_enlaza_al_historial_y_cuenta_las_justificadas(self):
        respuesta = self.client.get(reverse('alumnos:detalle', args=[self.c.alumno.pk]))
        self.assertContains(respuesta, url('alumno', self.c.alumno.pk))
        self.assertEqual(respuesta.context['asistencia']['justificadas'], 1)
        self.assertContains(respuesta, 'Falta justificada')

    def test_el_perfil_sin_permiso_de_asistencia_no_ofrece_el_historial(self):
        self.con_permisos('view_alumno', 'view_tutor', 'view_inscripcion')
        respuesta = self.client.get(reverse('alumnos:detalle', args=[self.c.alumno.pk]))
        self.assertNotContains(respuesta, url('alumno', self.c.alumno.pk))

    def test_consultas_constantes(self):
        with CaptureQueriesContext(connection) as pocas:
            self.historial()
        for i in range(12):
            dia = self.d1 - timedelta(days=i + 1)
            AsistenciaGeneral.objects.create(inscripcion=self.c, fecha=dia, estado='PRESENTE', origen='MANUAL', hora_entrada=time(7, 50))
        with CaptureQueriesContext(connection) as muchas:
            self.historial()
        self.assertEqual(len(muchas), len(pocas))
