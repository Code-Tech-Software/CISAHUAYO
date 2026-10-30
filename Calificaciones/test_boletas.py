"""Boletas e historial académico (pedido del 2026-10-29): qué calificaciones y faltas salen (solo actas cerradas), el
promedio de periodos en los niveles sin calificación final, el resultado semestral en preparatoria, las boletas del
grupo, el kárdex, los datos oficiales de cada nivel y quién puede abrirlas."""
from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from Alumnos.models import Periodo
from CISAHUAYO.pruebas import PRUEBAS, crear_alumno, crear_grado, hoy, inscribir, materia_en_grado
from PortalEstudiantes.resumen import calificaciones_de

from . import boletas, semestres
from . import calculo_semestral as cs
from .models import ActaCalificaciones, DatosOficialesNivel, ExamenSemestral
from .test_semestres import BaseSemestresTestCase

D = Decimal


def acta_cerrada(asignacion, periodo, filas):
    """Un acta cerrada con {inscripción: (final, faltas)}."""
    return ActaCalificaciones.objects.create(
        asignacion=asignacion, periodo=periodo, estado=ActaCalificaciones.CERRADA, cerrada_en=timezone.now(),
        resultados_cerrados=[{'inscripcion': i.pk, 'final': f'{final:.2f}', 'faltas': faltas} for i, (final, faltas) in filas.items()],
    )


class BaseBoletasTestCase(BaseSemestresTestCase):
    """La base de semestres (1.º y 2.º de preparatoria) más 4.º de primaria con Matemáticas y Español, tres bimestres
    (el tercero en captura) y Zoe inscrita."""

    def setUp(self):
        super().setUp()
        self.cuarto = crear_grado('PRIMARIA', 4)
        self.mat = materia_en_grado('MATP', self.cuarto, self.ciclo, inicio=None)
        self.esp = materia_en_grado('ESPP', self.cuarto, self.ciclo, inicio=None)
        self.bimestres = [
            Periodo.objects.create(ciclo=self.ciclo, nivel='PRIMARIA', nombre=f'Bimestre {n}', fecha_inicio=self.ciclo.fecha_inicio + timedelta(days=60 * (n - 1)),
                                   fecha_fin=self.ciclo.fecha_inicio + timedelta(days=60 * n - 1))
            for n in (1, 2, 3)
        ]
        self.zoe = inscribir(crear_alumno(nombre='Zoe', apellido_paterno='Zamora'), self.ciclo, self.cuarto)
        acta_cerrada(self.mat, self.bimestres[0], {self.zoe: (8, 2)})
        acta_cerrada(self.mat, self.bimestres[1], {self.zoe: (9.5, 0)})
        acta_cerrada(self.esp, self.bimestres[0], {self.zoe: (7, 1)})
        ActaCalificaciones.objects.create(asignacion=self.esp, periodo=self.bimestres[1], resultados_cerrados=[])   # en captura

    def cerrar_semestre_a(self, valores):
        for inscripcion, (p1, p2, p3) in valores.items():
            for periodo, final in zip(self.periodos_a, (p1, p2, p3)):
                acta = ActaCalificaciones.objects.filter(asignacion=self.calculo1, periodo=periodo).first() or acta_cerrada(self.calculo1, periodo, {})
                acta.resultados_cerrados = acta.resultados_cerrados + [{'inscripcion': inscripcion.pk, 'final': f'{final:.2f}', 'faltas': 1}]
                acta.save()


@PRUEBAS
class BoletaPrimariaTests(BaseBoletasTestCase):
    def test_periodos_cerrados_faltas_y_promedio_como_el_portal(self):
        b = boletas.boleta(self.zoe.alumno, self.ciclo)
        bloque = b.bloques[0]
        self.assertFalse(bloque.semestral)
        materias = {m.nombre: m for m in bloque.materias}
        self.assertEqual(materias['Matp'].periodos, [(D('8.00'), 2), (D('9.50'), 0), (None, None)])
        self.assertEqual(materias['Espp'].periodos, [(D('7.00'), 1), (None, None), (None, None)])   # en captura: vacío
        self.assertEqual((materias['Matp'].promedio, materias['Matp'].faltas), (D('8.75'), 2))
        self.assertEqual(bloque.faltas_por_periodo, [3, 0, 0])
        # el mismo promedio que ven las familias en el portal
        portal = {f.materia: f.promedio for f in calificaciones_de(self.zoe).filas}
        self.assertEqual({m.nombre: m.promedio for m in bloque.materias}, portal)
        self.assertEqual(bloque.promedio_general, calificaciones_de(self.zoe).promedio_general)

    def test_la_hoja_lleva_la_cct_y_quien_dirige(self):
        DatosOficialesNivel.objects.create(nivel='PRIMARIA', cct='16PPR0123K', director='Laura Méndez', cargo='Directora de Primaria')
        respuesta = self.client.get(reverse('calificaciones:boleta', args=[self.zoe.alumno.pk]), {'ciclo': self.ciclo.pk})
        self.assertContains(respuesta, 'CCT 16PPR0123K')
        self.assertContains(respuesta, 'Laura Méndez')
        self.assertContains(respuesta, 'Directora de Primaria')
        self.assertContains(respuesta, 'no es la calificación final del ciclo')
        self.assertContains(respuesta, 'size: A4 portrait')


@PRUEBAS
class BoletaPreparatoriaTests(BaseBoletasTestCase):
    def test_semestre_con_resultado_y_promedio_de_definitivas(self):
        self.cerrar_semestre_a({self.ana: (9.6, 9.6, 9.6)})
        b = boletas.boleta(self.ana.alumno, self.ciclo)
        bloque = b.bloques[0]
        self.assertTrue(bloque.semestral)
        self.assertEqual(bloque.titulo, f'Semestre A · {self.ana.grupo}')
        semestral = bloque.materias[0].semestral
        self.assertEqual((semestral['definitiva'], semestral['exento'], semestral['estado']), ('9.60', True, 'Aprobada (exento)'))
        self.assertEqual(bloque.promedio_general, D('9.60'))
        # los mismos números que la hoja semestral
        self.assertEqual(cs.texto(semestres.resultado_de(self.ana, self.calculo1).definitiva), semestral['definitiva'])

    def test_sin_todas_las_definitivas_no_hay_promedio_general(self):
        self.cerrar_semestre_a({self.ana: (8, 8, 8)})   # le falta el examen final
        bloque = boletas.boleta(self.ana.alumno, self.ciclo).bloques[0]
        self.assertIsNone(bloque.promedio_general)
        self.assertEqual(bloque.sin_definitiva, 1)

    def test_el_ciclo_lleva_el_semestre_a_y_el_b(self):
        self.cerrar_semestre_a({self.ana: (9.6, 9.6, 9.6), self.beto: (9.6, 9.6, 9.6)})
        semestres.cerrar(self.sem_a, self.admin)
        self.client.post(reverse('inscripciones:semestre'), {f'grado_{self.primero.pk}': str(self.segundo.pk), 'fecha': hoy().isoformat()})
        b = boletas.boleta(self.ana.alumno, self.ciclo)
        self.assertEqual([bl.semestre.clave for bl in b.bloques], ['A', 'B'])
        self.assertEqual(b.bloques[1].periodos, self.periodos_b)
        respuesta = self.client.get(reverse('calificaciones:boleta', args=[self.ana.alumno.pk]), {'ciclo': self.ciclo.pk})
        self.assertContains(respuesta, 'size: A4 landscape')
        self.assertContains(respuesta, 'semestre concluido')

    def test_boletas_del_grupo_incluyen_a_quienes_pasaron_al_b(self):
        self.client.post(reverse('inscripciones:semestre'), {f'grado_{self.primero.pk}': str(self.segundo.pk), 'fecha': hoy().isoformat()})
        lista = boletas.boletas_del_grupo(self.ana.grupo, self.ciclo)
        self.assertEqual([b.alumno for b in lista], [self.ana.alumno, self.beto.alumno])
        respuesta = self.client.get(reverse('calificaciones:boletas_grupo', args=[self.ana.grupo.pk]), {'ciclo': self.ciclo.pk})
        self.assertEqual(len(respuesta.context['boletas']), 2)


@PRUEBAS
class KardexTests(BaseBoletasTestCase):
    def test_resumen_por_nivel_y_egresados(self):
        self.cerrar_semestre_a({self.ana: (4, 4, 4)})
        ExamenSemestral.objects.create(asignacion=self.calculo1, inscripcion=self.ana, tipo=cs.EXTRAORDINARIO, valor=D('5'))
        ExamenSemestral.objects.create(asignacion=self.calculo1, inscripcion=self.ana, tipo=cs.REGULARIZACION, valor=D('7.5'))
        alumno = self.ana.alumno
        alumno.estatus = 'EGRESADO'   # ya no está en las listas activas, pero su historial sigue
        alumno.save()
        k = boletas.kardex(alumno)
        self.assertEqual(len(k.bloques), 1)
        materia = k.bloques[0].materias[0]
        self.assertEqual((materia.semestral['definitiva'], materia.semestral['estado']), ('7.50', 'Aprobada en regularización'))
        nivel = k.niveles[0]
        self.assertEqual((nivel.nombre, nivel.promedio, nivel.aprobadas, nivel.reprobadas), ('Preparatoria', D('7.50'), 1, 0))
        respuesta = self.client.get(reverse('calificaciones:kardex', args=[alumno.pk]))
        self.assertContains(respuesta, 'Historial académico')
        self.assertContains(respuesta, 'Aprobada en regularización')

    def test_niveles_sin_final_muestran_el_promedio_de_periodos(self):
        k = boletas.kardex(self.zoe.alumno)
        self.assertEqual(k.niveles[0].nombre, 'Primaria')
        self.assertFalse(k.niveles[0].semestral)
        self.assertEqual(k.niveles[0].promedio, boletas.boleta(self.zoe.alumno, self.ciclo).bloques[0].promedio_general)


@PRUEBAS
class AccesoYAjustesTests(BaseBoletasTestCase):
    def test_solo_quien_ve_todas_las_calificaciones(self):
        rutas = [reverse('calificaciones:boleta', args=[self.zoe.alumno.pk]), reverse('calificaciones:kardex', args=[self.zoe.alumno.pk]),
                 reverse('calificaciones:boletas_grupo', args=[self.zoe.grupo.pk])]
        self.client.force_login(self.docente)   # captura sus materias, pero no ve las de los demás
        for ruta in rutas:
            self.assertEqual(self.client.get(ruta).status_code, 403, ruta)
        self.con_permisos('ver_todas')
        for ruta in rutas:
            self.assertEqual(self.client.get(ruta).status_code, 200, ruta)

    def test_el_expediente_muestra_el_acceso_solo_a_quien_puede(self):
        detalle = reverse('alumnos:detalle', args=[self.zoe.alumno.pk])
        self.assertContains(self.client.get(detalle), reverse('calificaciones:kardex', args=[self.zoe.alumno.pk]))
        self.con_permisos('view_alumno')
        self.assertNotContains(self.client.get(detalle), reverse('calificaciones:kardex', args=[self.zoe.alumno.pk]))

    def test_datos_oficiales_se_validan_y_solo_los_cambia_quien_puede(self):
        url = reverse('calificaciones:datos_oficiales')
        datos = {f'{n}-{c}': '' for n in ('preescolar', 'primaria', 'secundaria', 'preparatoria') for c in ('cct', 'director', 'cargo')}
        datos.update({'primaria-cct': '16ppr 0123k', 'primaria-director': ' Laura   Méndez '})
        self.client.post(url, datos)
        guardado = DatosOficialesNivel.objects.get(nivel='PRIMARIA')
        self.assertEqual((guardado.cct, guardado.director), ('16PPR0123K', 'Laura Méndez'))
        self.assertFalse(DatosOficialesNivel.objects.filter(nivel='SECUNDARIA').exists())   # sin cambios, no se crea
        datos['secundaria-cct'] = 'ABC'
        self.assertFalse(self.client.post(url, datos).context['formularios'][2][2].is_valid())
        self.con_permisos('view_datosoficialesnivel')
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, datos).status_code, 403)
