"""Pruebas de los ayudantes de horarios y del plan de materias (asignación de materias a grados por ciclo)."""
from datetime import time

from django.test import SimpleTestCase, TestCase

from CISAHUAYO.pruebas import (
    ciclo_actual_de_prueba,
    ciclo_cerrado_de_prueba,
    ciclo_proximo_de_prueba,
    crear_grado,
)

from .academico import ciclo_editable, elegir_ciclo, grados_por_asignar, materias_por_asignar
from .horarios import (
    bloques_empalmados,
    con_resumen_de_horario,
    cuadricula,
    duracion,
    formatear_duracion,
    minutos_semanales,
    resumen_horario,
)
from .models import HorarioMateria, Materia, MateriaGrado


def bloque(dia, inicio, fin, materia='Mat'):
    """Bloque sin guardar (basta para probar el cálculo)."""
    return HorarioMateria(dia_semana=dia, hora_inicio=time(*inicio), hora_fin=time(*fin))


class DuracionTests(SimpleTestCase):
    def test_duracion_de_un_bloque(self):
        self.assertEqual(duracion(bloque(0, (8, 0), (8, 50))), 50)
        self.assertEqual(duracion(bloque(0, (10, 30), (12, 0))), 90)

    def test_formato(self):
        self.assertEqual(formatear_duracion(90), '1 h 30 min')
        self.assertEqual(formatear_duracion(120), '2 h')
        self.assertEqual(formatear_duracion(45), '45 min')
        self.assertEqual(formatear_duracion(0), '0 min')

    def test_minutos_por_semana(self):
        bloques = [bloque(0, (8, 0), (9, 0)), bloque(2, (8, 0), (9, 0)), bloque(4, (10, 0), (10, 45))]
        self.assertEqual(minutos_semanales(bloques), 165)
        self.assertEqual(minutos_semanales([]), 0)


class ResumenTests(SimpleTestCase):
    def test_agrupa_los_dias_que_comparten_hora(self):
        bloques = [bloque(2, (8, 0), (8, 50)), bloque(0, (8, 0), (8, 50)), bloque(4, (10, 0), (11, 0))]
        self.assertEqual(resumen_horario(bloques), ['Lun, Mié · 08:00–08:50', 'Vie · 10:00–11:00'])

    def test_ordena_por_el_primer_dia(self):
        bloques = [bloque(4, (8, 0), (9, 0)), bloque(1, (12, 0), (13, 0))]
        self.assertEqual(resumen_horario(bloques), ['Mar · 12:00–13:00', 'Vie · 08:00–09:00'])

    def test_sin_bloques(self):
        self.assertEqual(resumen_horario([]), [])


class CuadriculaTests(SimpleTestCase):
    def test_siempre_hay_lunes_a_viernes(self):
        tabla = cuadricula([bloque(1, (8, 0), (9, 0))])
        self.assertEqual([d['corto'] for d in tabla['dias']], ['Lun', 'Mar', 'Mié', 'Jue', 'Vie'])

    def test_fin_de_semana_solo_si_hay_clases(self):
        tabla = cuadricula([bloque(5, (9, 0), (10, 0))])
        self.assertEqual([d['numero'] for d in tabla['dias']], [0, 1, 2, 3, 4, 5])

    def test_una_fila_por_franja_en_orden(self):
        tabla = cuadricula([bloque(0, (10, 0), (11, 0)), bloque(1, (8, 0), (9, 0)), bloque(2, (8, 0), (9, 0))])
        self.assertEqual([(f['inicio'], f['fin']) for f in tabla['filas']], [(time(8, 0), time(9, 0)), (time(10, 0), time(11, 0))])

    def test_cada_bloque_cae_en_su_dia(self):
        a, b, c = bloque(0, (8, 0), (9, 0)), bloque(2, (8, 0), (9, 0)), bloque(4, (10, 0), (11, 0))
        primera, segunda = cuadricula([a, b, c])['filas']
        self.assertEqual(primera['celdas'], [[a], [], [b], [], []])
        self.assertEqual(segunda['celdas'], [[], [], [], [], [c]])

    def test_sin_bloques_no_hay_filas(self):
        self.assertEqual(cuadricula([])['filas'], [])


class EmpalmesTests(TestCase):
    def setUp(self):
        self.ciclo = ciclo_actual_de_prueba()
        self.grado = crear_grado('PRIMARIA', 4)
        mat = Materia.objects.create(clave='MAT', nombre='Matemáticas')
        esp = Materia.objects.create(clave='ESP', nombre='Español')
        self.mat = MateriaGrado.objects.create(ciclo=self.ciclo, grado=self.grado, materia=mat)
        self.esp = MateriaGrado.objects.create(ciclo=self.ciclo, grado=self.grado, materia=esp)
        self.lunes = HorarioMateria.objects.create(materia_grado=self.mat, dia_semana=0, hora_inicio=time(8, 0), hora_fin=time(9, 0))

    def hay(self, dia, inicio, fin, **extra):
        return list(bloques_empalmados(self.grado, self.ciclo, dia, time(*inicio), time(*fin), **extra))

    def test_detecta_el_empalme_parcial_y_el_total(self):
        self.assertEqual(self.hay(0, (8, 30), (9, 30)), [self.lunes])
        self.assertEqual(self.hay(0, (7, 0), (8, 30)), [self.lunes])
        self.assertEqual(self.hay(0, (8, 10), (8, 50)), [self.lunes])
        self.assertEqual(self.hay(0, (7, 0), (10, 0)), [self.lunes])

    def test_las_franjas_contiguas_no_se_empalman(self):
        self.assertEqual(self.hay(0, (9, 0), (10, 0)), [])
        self.assertEqual(self.hay(0, (7, 0), (8, 0)), [])

    def test_otro_dia_no_cuenta(self):
        self.assertEqual(self.hay(1, (8, 0), (9, 0)), [])

    def test_otro_grado_u_otro_ciclo_no_cuentan(self):
        otro = crear_grado('PRIMARIA', 5)
        self.assertEqual(list(bloques_empalmados(otro, self.ciclo, 0, time(8, 0), time(9, 0))), [])
        proximo = ciclo_proximo_de_prueba()
        self.assertEqual(list(bloques_empalmados(self.grado, proximo, 0, time(8, 0), time(9, 0))), [])

    def test_una_materia_quitada_no_estorba(self):
        self.mat.activa = False
        self.mat.save()
        self.assertEqual(self.hay(0, (8, 0), (9, 0)), [])

    def test_al_editar_se_excluye_el_propio_bloque(self):
        self.assertEqual(self.hay(0, (8, 0), (9, 0), excluir_pk=self.lunes.pk), [])

    def test_resumen_de_las_asignaciones(self):
        HorarioMateria.objects.create(materia_grado=self.mat, dia_semana=2, hora_inicio=time(8, 0), hora_fin=time(9, 0))
        asignaciones = con_resumen_de_horario(MateriaGrado.objects.filter(grado=self.grado).prefetch_related('horarios').order_by('materia__nombre'))
        por_clave = {a.materia.clave: a for a in asignaciones}
        self.assertEqual(por_clave['MAT'].lineas, ['Lun, Mié · 08:00–09:00'])
        self.assertEqual((por_clave['MAT'].bloques, por_clave['MAT'].minutos, por_clave['MAT'].duracion), (2, 120, '2 h'))
        self.assertEqual((por_clave['ESP'].bloques, por_clave['ESP'].lineas, por_clave['ESP'].duracion), (0, [], ''))


class PlanTests(TestCase):
    def setUp(self):
        self.actual = ciclo_actual_de_prueba('2026-2027')
        self.cerrado = ciclo_cerrado_de_prueba('2025-2026')
        self.proximo = ciclo_proximo_de_prueba('2027-2028')
        self.primero = crear_grado('PRIMARIA', 1)
        self.segundo = crear_grado('PRIMARIA', 2)
        crear_grado('PRIMARIA', 3, activo=False)
        self.mat = Materia.objects.create(clave='MAT', nombre='Matemáticas')
        self.esp = Materia.objects.create(clave='ESP', nombre='Español')
        Materia.objects.create(clave='VIEJA', nombre='Vieja', activa=False)

    def test_elegir_ciclo(self):
        ciclos = [self.proximo, self.actual, self.cerrado]
        self.assertEqual(elegir_ciclo('', ciclos), self.actual)
        self.assertEqual(elegir_ciclo(str(self.cerrado.pk), ciclos), self.cerrado)
        for invalido in ('x', '9999', '-1', None):
            self.assertEqual(elegir_ciclo(invalido, ciclos), self.actual, invalido)
        self.assertEqual(elegir_ciclo('', [self.cerrado, self.proximo]), self.cerrado)   # sin actual: el más reciente de la lista
        self.assertIsNone(elegir_ciclo('', []))

    def test_solo_el_ciclo_actual_o_uno_proximo_se_edita(self):
        self.assertTrue(ciclo_editable(self.actual))
        self.assertTrue(ciclo_editable(self.proximo))
        self.assertFalse(ciclo_editable(self.cerrado))
        self.assertFalse(ciclo_editable(None))

    def test_materias_por_asignar_a_un_grado(self):
        self.assertEqual(set(materias_por_asignar(self.primero, self.actual)), {self.mat, self.esp})   # sin la materia de baja
        MateriaGrado.objects.create(ciclo=self.actual, grado=self.primero, materia=self.mat)
        self.assertEqual(set(materias_por_asignar(self.primero, self.actual)), {self.esp})
        self.assertEqual(set(materias_por_asignar(self.primero, self.proximo)), {self.mat, self.esp})   # otro ciclo
        self.assertEqual(set(materias_por_asignar(self.segundo, self.actual)), {self.mat, self.esp})   # otro grado

    def test_una_asignacion_quitada_vuelve_a_ofrecerse(self):
        MateriaGrado.objects.create(ciclo=self.actual, grado=self.primero, materia=self.mat, activa=False)
        self.assertIn(self.mat, materias_por_asignar(self.primero, self.actual))

    def test_grados_por_asignar_a_una_materia_en_orden_escolar(self):
        self.assertEqual(list(grados_por_asignar(self.mat, self.actual)), [self.primero, self.segundo])   # sin el grado de baja
        MateriaGrado.objects.create(ciclo=self.actual, grado=self.primero, materia=self.mat)
        self.assertEqual(list(grados_por_asignar(self.mat, self.actual)), [self.segundo])
