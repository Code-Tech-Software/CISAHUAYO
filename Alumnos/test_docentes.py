"""La relación de los profesores con las materias: habilitación, asignación y carga de trabajo."""
import importlib

from django.apps import apps
from django.db import IntegrityError, transaction

from Alumnos.docentes import (
    asignaciones_vigentes,
    asignar_profesor,
    carga_de_profesores,
    con_habilitados,
    deshabilitar,
    descripcion_del_cambio,
    estado_de_carga,
    habilitados_por_materia,
    habilitar,
    resumen_del_ciclo,
)
from Alumnos.models import Materia, MateriaGrado, ProfesorMateria
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    ciclo_cerrado_de_prueba,
    crear_grado,
    crear_profesor,
)
from Profesores.tests import asignar, bloque, crear_materia


@PRUEBAS
class HabilitacionTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.marta = crear_profesor(nombre='Marta', apellido_paterno='Rangel')
        self.beto = crear_profesor(nombre='Beto', apellido_paterno='Aguilar', telefono='3530000002')
        self.mat = crear_materia('MAT', 'Matemáticas')
        self.esp = crear_materia('ESP', 'Español')

    def test_habilitar_devuelve_solo_lo_nuevo_y_no_repite(self):
        self.assertEqual(habilitar(self.marta, [self.mat, self.esp]), [self.mat, self.esp])
        self.assertEqual(habilitar(self.marta, [self.mat]), [])
        self.assertEqual(habilitar(self.marta, [self.mat, crear_materia('HIS', 'Historia')]), [Materia.objects.get(clave='HIS')])
        self.assertEqual(ProfesorMateria.objects.filter(profesor=self.marta).count(), 3)

    def test_deshabilitar_devuelve_lo_que_quito_y_no_toca_lo_demas(self):
        habilitar(self.marta, [self.mat, self.esp])
        habilitar(self.beto, [self.mat])
        self.assertEqual(deshabilitar(self.marta, [self.mat, crear_materia('HIS', 'Historia')]), [self.mat])
        self.assertEqual(list(ProfesorMateria.objects.filter(profesor=self.marta).values_list('materia__clave', flat=True)), ['ESP'])
        self.assertTrue(ProfesorMateria.objects.filter(profesor=self.beto, materia=self.mat).exists())

    def test_la_pareja_profesor_materia_es_unica(self):
        ProfesorMateria.objects.create(profesor=self.marta, materia=self.mat)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProfesorMateria.objects.create(profesor=self.marta, materia=self.mat)

    def test_se_borra_con_el_profesor_o_la_materia_pero_no_al_dar_de_baja(self):
        habilitar(self.marta, [self.mat, self.esp])
        self.marta.estatus = 'INACTIVO'
        self.marta.save()
        self.assertEqual(ProfesorMateria.objects.count(), 2)   # la baja es lógica: la lista se conserva
        self.esp.delete()
        self.assertEqual(ProfesorMateria.objects.count(), 1)

    def test_habilitados_por_materia_solo_incluye_profesores_activos(self):
        habilitar(self.marta, [self.mat, self.esp])
        habilitar(self.beto, [self.mat])
        self.beto.estatus = 'INACTIVO'
        self.beto.save()
        mapa = habilitados_por_materia()
        self.assertEqual(mapa[self.mat.pk], [self.marta.pk])
        self.assertEqual(mapa[self.esp.pk], [self.marta.pk])

    def test_habilitados_por_materia_se_limita_a_las_materias_pedidas(self):
        habilitar(self.marta, [self.mat, self.esp])
        self.assertEqual(set(habilitados_por_materia([self.mat])), {self.mat.pk})

    def test_con_habilitados_marca_a_quien_no_esta_en_la_lista(self):
        ciclo = ciclo_actual_de_prueba()
        habilitar(self.marta, [self.mat])
        con_marta = asignar(self.mat, crear_grado('PRIMARIA', 1), ciclo, profesor=self.marta)
        con_beto = asignar(self.mat, crear_grado('PRIMARIA', 2), ciclo, profesor=self.beto)
        sin_nadie = asignar(self.esp, crear_grado('PRIMARIA', 3), ciclo)
        filas = {fila.pk: fila for fila in con_habilitados(MateriaGrado.objects.all())}
        self.assertEqual(filas[con_marta.pk].habilitados, str(self.marta.pk))
        self.assertTrue(filas[con_marta.pk].profesor_habilitado)
        self.assertFalse(filas[con_beto.pk].profesor_habilitado)
        self.assertEqual(filas[sin_nadie.pk].habilitados, '')
        self.assertTrue(filas[sin_nadie.pk].profesor_habilitado)   # sin profesor no hay nada que advertir

    def test_la_migracion_habilita_a_quien_ya_imparte(self):
        ciclo, anterior = ciclo_actual_de_prueba(), ciclo_cerrado_de_prueba()
        asignar(self.mat, crear_grado('PRIMARIA', 1), ciclo, profesor=self.marta)
        asignar(self.mat, crear_grado('PRIMARIA', 2), ciclo, profesor=self.marta)      # repetida: una sola habilitación
        asignar(self.esp, crear_grado('PRIMARIA', 3), anterior, profesor=self.marta)   # de un ciclo cerrado también cuenta
        asignar(self.esp, crear_grado('PRIMARIA', 4), ciclo)                           # sin profesor: no habilita a nadie
        migracion = importlib.import_module('Alumnos.migrations.0010_profesores_y_materias')
        migracion.habilitar_a_quienes_ya_imparten(apps, None)
        migracion.habilitar_a_quienes_ya_imparten(apps, None)   # correrla otra vez no duplica
        self.assertEqual(
            sorted(ProfesorMateria.objects.values_list('profesor_id', 'materia__clave')),
            sorted([(self.marta.pk, 'MAT'), (self.marta.pk, 'ESP')]),
        )


@PRUEBAS
class CargaTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.marta = crear_profesor(nombre='Marta', apellido_paterno='Rangel', horas_maximas=3)
        self.beto = crear_profesor(nombre='Beto', apellido_paterno='Aguilar', telefono='3530000002')
        self.mat = crear_materia('MAT', 'Matemáticas')
        self.esp = crear_materia('ESP', 'Español')

    def test_estado_de_carga(self):
        self.assertEqual(estado_de_carga(0, 0, 10), 'libre')
        self.assertEqual(estado_de_carga(0, 0, None), 'libre')
        self.assertEqual(estado_de_carga(120, 2, None), 'sin_limite')
        self.assertEqual(estado_de_carga(120, 2, 10), 'normal')
        self.assertEqual(estado_de_carga(600, 4, 10), 'completa')
        self.assertEqual(estado_de_carga(601, 4, 10), 'sobrecarga')
        self.assertEqual(estado_de_carga(0, 2, 10), 'normal')   # con materias pero sin horario armado

    def test_suma_materias_grados_y_horas_del_ciclo(self):
        a = asignar(self.mat, crear_grado('PRIMARIA', 1), self.ciclo, profesor=self.marta)
        bloque(a, 0, (8, 0), (9, 30))
        bloque(a, 2, (8, 0), (9, 0))
        b = asignar(self.esp, a.grado, self.ciclo, profesor=self.marta)
        bloque(b, 1, (8, 0), (9, 0))
        carga = {c['profesor'].pk: c for c in carga_de_profesores(self.ciclo)}[self.marta.pk]
        self.assertEqual((carga['total_materias'], carga['total_grados'], carga['minutos']), (2, 1, 210))
        self.assertEqual(carga['duracion'], '3 h 30 min')
        self.assertEqual((carga['maximo'], carga['porcentaje'], carga['estado']), (3, 117, 'sobrecarga'))
        self.assertEqual(carga['estado_texto'], 'Sobrecargado')

    def test_quien_no_tiene_tope_no_tiene_porcentaje(self):
        a = asignar(self.mat, crear_grado('PRIMARIA', 1), self.ciclo, profesor=self.beto)
        bloque(a)
        carga = {c['profesor'].pk: c for c in carga_de_profesores(self.ciclo)}[self.beto.pk]
        self.assertIsNone(carga['porcentaje'])
        self.assertEqual(carga['estado'], 'sin_limite')

    def test_quien_no_imparte_nada_esta_libre(self):
        cargas = {c['profesor'].pk: c for c in carga_de_profesores(self.ciclo)}
        self.assertEqual((cargas[self.beto.pk]['estado'], cargas[self.beto.pk]['duracion']), ('libre', ''))

    def test_no_cuenta_materias_quitadas_de_otros_ciclos_ni_de_materias_o_grados_de_baja(self):
        asignar(self.mat, crear_grado('PRIMARIA', 1), self.ciclo, profesor=self.marta, activa=False)
        asignar(self.mat, crear_grado('PRIMARIA', 2), ciclo_cerrado_de_prueba(), profesor=self.marta)
        asignar(crear_materia('OLD', 'Antigua', activa=False), crear_grado('PRIMARIA', 3), self.ciclo, profesor=self.marta)
        asignar(self.esp, crear_grado('PRIMARIA', 4, activo=False), self.ciclo, profesor=self.marta)
        carga = {c['profesor'].pk: c for c in carga_de_profesores(self.ciclo)}[self.marta.pk]
        self.assertEqual(carga['total_materias'], 0)
        self.assertEqual(asignaciones_vigentes(self.ciclo).count(), 0)

    def test_por_omision_solo_incluye_profesores_activos(self):
        crear_profesor(nombre='Vieja', apellido_paterno='Zepeda', telefono='3530000003', estatus='INACTIVO')
        self.assertEqual({str(c['profesor']) for c in carga_de_profesores(self.ciclo)}, {str(self.marta), str(self.beto)})

    def test_sin_ciclo_no_hay_carga(self):
        self.assertTrue(all(c['total_materias'] == 0 for c in carga_de_profesores(None)))


@PRUEBAS
class ResumenDelCicloTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.marta = crear_profesor(nombre='Marta', apellido_paterno='Rangel')
        crear_profesor(nombre='Beto', apellido_paterno='Aguilar', telefono='3530000002')

    def test_sin_ciclo_todo_en_cero(self):
        self.assertEqual(resumen_del_ciclo(None)['materias'], 0)

    def test_cuenta_con_y_sin_profesor_y_sin_horario(self):
        grado = crear_grado('PRIMARIA', 1)
        a = asignar(crear_materia('MAT', 'Matemáticas'), grado, self.ciclo, profesor=self.marta)
        bloque(a, 0)
        bloque(a, 1)   # con varios bloques la materia se cuenta una sola vez
        asignar(crear_materia('ESP', 'Español'), grado, self.ciclo, profesor=self.marta)   # con profesor, sin horario
        asignar(crear_materia('HIS', 'Historia'), grado, self.ciclo)                       # sin profesor y sin horario
        resumen = resumen_del_ciclo(self.ciclo)
        self.assertEqual((resumen['materias'], resumen['con_profesor'], resumen['sin_profesor'], resumen['sin_horario']), (3, 2, 1, 2))
        self.assertEqual(resumen['avance'], 67)
        self.assertEqual((resumen['profesores'], resumen['profesores_libres']), (2, 1))

    def test_las_materias_quitadas_no_cuentan(self):
        asignar(crear_materia('MAT', 'Matemáticas'), crear_grado('PRIMARIA', 1), self.ciclo, activa=False)
        self.assertEqual(resumen_del_ciclo(self.ciclo)['materias'], 0)


@PRUEBAS
class AsignarProfesorTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.marta = crear_profesor(nombre='Marta', apellido_paterno='Rangel')
        self.beto = crear_profesor(nombre='Beto', apellido_paterno='Aguilar', telefono='3530000002')
        self.mat = asignar(crear_materia('MAT', 'Matemáticas'), crear_grado('PRIMARIA', 1), self.ciclo)

    def test_asigna_y_devuelve_el_profesor_anterior(self):
        cambios, omitidas = asignar_profesor([self.mat], self.marta)
        self.assertEqual((cambios, omitidas), ([(self.mat, None)], []))
        self.mat.refresh_from_db()
        self.assertEqual(self.mat.profesor, self.marta)
        cambios, _ = asignar_profesor([self.mat], self.beto)
        self.assertEqual(cambios[0][1], self.marta)

    def test_quitar_con_none(self):
        self.mat.profesor = self.marta
        self.mat.save()
        cambios, omitidas = asignar_profesor([self.mat], None)
        self.assertEqual((len(cambios), omitidas), (1, []))
        self.mat.refresh_from_db()
        self.assertIsNone(self.mat.profesor)

    def test_si_ya_estaba_no_hay_cambio(self):
        self.mat.profesor = self.marta
        self.mat.save()
        self.assertEqual(asignar_profesor([self.mat], self.marta), ([], []))

    def test_omite_ciclo_cerrado_y_materia_quitada(self):
        cerrada = asignar(crear_materia('ESP', 'Español'), crear_grado('PRIMARIA', 2), ciclo_cerrado_de_prueba())
        quitada = asignar(crear_materia('HIS', 'Historia'), crear_grado('PRIMARIA', 3), self.ciclo, activa=False)
        cambios, omitidas = asignar_profesor([cerrada, quitada], self.marta)
        self.assertEqual(cambios, [])
        self.assertEqual(len(omitidas), 2)
        self.assertIn('cerrado', omitidas[0])
        self.assertIn('ya no se imparte', omitidas[1])

    def test_omite_lo_que_dejaria_al_profesor_en_dos_grupos_a_la_vez(self):
        bloque(self.mat, 0, (8, 0), (9, 0))
        otra = asignar(crear_materia('ESP', 'Español'), crear_grado('PRIMARIA', 2), self.ciclo)
        bloque(otra, 0, (8, 30), (9, 30))
        cambios, omitidas = asignar_profesor([self.mat], self.marta)
        self.assertEqual(len(cambios), 1)
        cambios, omitidas = asignar_profesor([otra], self.marta)
        self.assertEqual((cambios, len(omitidas)), ([], 1))
        otra.refresh_from_db()
        self.assertIsNone(otra.profesor)

    def test_lo_que_se_puede_se_hace_aunque_otra_se_omita(self):
        cerrada = asignar(crear_materia('ESP', 'Español'), crear_grado('PRIMARIA', 2), ciclo_cerrado_de_prueba())
        cambios, omitidas = asignar_profesor([cerrada, self.mat], self.marta)
        self.assertEqual([c[0] for c in cambios], [self.mat])
        self.assertEqual(len(omitidas), 1)

    def test_descripcion_del_cambio(self):
        texto = descripcion_del_cambio(self.mat, None)
        self.assertIn('Matemáticas de 1° Primaria', texto)
        self.assertIn('sin profesor → sin profesor', texto)
        self.mat.profesor = self.marta
        self.assertIn('sin profesor → Marta Rangel Soto', descripcion_del_cambio(self.mat, None))
        self.assertIn('Marta Rangel Soto → sin profesor', descripcion_del_cambio(MateriaGrado(materia=self.mat.materia, grado=self.mat.grado, ciclo=self.ciclo), self.marta))
