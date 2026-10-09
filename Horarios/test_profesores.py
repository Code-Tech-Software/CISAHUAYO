"""El profesor en los horarios: no puede estar en dos grupos a la vez, y se ve quién da cada materia."""
from datetime import time

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from Alumnos.horarios import bloques_del_profesor_empalmados, minutos_por_profesor, se_empalman
from Alumnos.models import HorarioMateria, Materia, MateriaGrado
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    ciclo_cerrado_de_prueba,
    crear_grado,
    crear_profesor,
)


def asignar(clave, nombre, grado, ciclo, **cambios):
    materia, _ = Materia.objects.get_or_create(clave=clave, defaults={'nombre': nombre})
    return MateriaGrado.objects.create(materia=materia, grado=grado, ciclo=ciclo, **cambios)


def bloque(asignacion, dia, inicio, fin):
    return HorarioMateria.objects.create(materia_grado=asignacion, dia_semana=dia, hora_inicio=time(*inicio), hora_fin=time(*fin))


def datos(asignacion, dias=(0,), inicio='10:00', fin='11:00'):
    """Lo que envía el alta: la materia, los días marcados y la hora de cada uno (aquí, la misma para todos)."""
    horas = {}
    for dia in dias:
        horas.update({f'inicio_{dia}': inicio, f'fin_{dia}': fin})
    return {'materia_grado': asignacion.pk, 'dias': list(dias), **horas}


class BaseProfesorTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.cerrado = ciclo_cerrado_de_prueba()
        self.profesor = crear_profesor()
        self.g1, self.g2 = crear_grado('PRIMARIA', 1), crear_grado('PRIMARIA', 2)
        self.mat = asignar('MAT', 'Matemáticas', self.g1, self.ciclo, profesor=self.profesor)
        self.esp = asignar('ESP', 'Español', self.g2, self.ciclo, profesor=self.profesor)
        bloque(self.mat, 0, (8, 0), (9, 0))          # lunes 8:00–9:00 en 1°


# ---------------------------------------------------------------------------
# Ayudantes
# ---------------------------------------------------------------------------
@PRUEBAS
class AyudantesTests(BaseProfesorTests):
    def test_se_empalman_solo_si_se_traslapan_el_mismo_dia(self):
        self.assertTrue(se_empalman((0, time(8), time(9)), (0, time(8, 30), time(9, 30))))
        self.assertTrue(se_empalman((0, time(8), time(10)), (0, time(8, 30), time(9))))      # uno dentro del otro
        self.assertFalse(se_empalman((0, time(8), time(9)), (0, time(9), time(10))))         # solo se tocan
        self.assertFalse(se_empalman((0, time(8), time(9)), (1, time(8), time(9))))          # otro día

    def test_bloques_del_profesor_empalmados(self):
        self.assertEqual(len(bloques_del_profesor_empalmados(self.profesor, self.ciclo, 0, time(8, 30), time(9, 30))), 1)
        self.assertEqual(len(bloques_del_profesor_empalmados(self.profesor, self.ciclo, 0, time(9), time(10))), 0)
        self.assertEqual(len(bloques_del_profesor_empalmados(self.profesor, self.cerrado, 0, time(8), time(9))), 0)
        self.assertEqual(len(bloques_del_profesor_empalmados(self.profesor, self.ciclo, 0, time(8), time(9), excluir_grado=self.g1)), 0)

    def test_minutos_por_profesor(self):
        bloque(self.esp, 1, (10, 0), (10, 45))
        otro = crear_profesor(nombre='Otro', telefono='3530000009')
        self.assertEqual(dict(minutos_por_profesor([self.profesor.pk, otro.pk], self.ciclo)), {self.profesor.pk: 105})
        self.assertEqual(dict(minutos_por_profesor([self.profesor.pk], self.cerrado)), {})
        self.assertEqual(dict(minutos_por_profesor([], self.ciclo)), {})
        self.assertEqual(dict(minutos_por_profesor([self.profesor.pk], None)), {})


# ---------------------------------------------------------------------------
# Agregar bloques
# ---------------------------------------------------------------------------
@PRUEBAS
class CrearConProfesorTests(BaseProfesorTests):
    def setUp(self):
        super().setUp()
        self.url = f"{reverse('horarios:crear', args=[self.g2.pk])}?ciclo={self.ciclo.pk}"

    def test_rechaza_empalmar_al_profesor_con_otro_grupo(self):
        respuesta = self.client.post(self.url, datos(self.esp, dias=(0,), inicio='08:30', fin='09:30'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'un profesor no puede estar en dos grupos a la vez')
        self.assertContains(respuesta, 'Matemáticas en 1° Primaria (lunes 08:00–09:00)')
        self.assertFalse(HorarioMateria.objects.filter(materia_grado=self.esp).exists())

    def test_con_varios_dias_basta_un_empalme_para_no_guardar_nada(self):
        respuesta = self.client.post(self.url, datos(self.esp, dias=(1, 0, 2), inicio='08:30', fin='09:30'))
        self.assertContains(respuesta, 'un profesor no puede estar en dos grupos a la vez')
        self.assertFalse(HorarioMateria.objects.filter(materia_grado=self.esp).exists())

    def test_acepta_horas_contiguas_otros_dias_y_otros_ciclos(self):
        self.client.post(self.url, datos(self.esp, dias=(0,), inicio='09:00', fin='10:00'))     # se toca en el borde
        self.client.post(self.url, datos(self.esp, dias=(1, 2), inicio='08:00', fin='09:00'))   # mismo horario, otros días
        self.assertEqual(HorarioMateria.objects.filter(materia_grado=self.esp).count(), 3)

    def test_el_horario_de_un_ciclo_cerrado_no_estorba(self):
        vieja = asignar('MAT', 'Matemáticas', self.g1, self.cerrado, profesor=self.profesor)
        bloque(vieja, 3, (10, 0), (11, 0))
        self.client.post(self.url, datos(self.esp, dias=(3,), inicio='10:00', fin='11:00'))
        self.assertEqual(HorarioMateria.objects.filter(materia_grado=self.esp).count(), 1)

    def test_sin_profesor_no_hay_nada_que_revisar(self):
        libre = asignar('CIE', 'Ciencias', self.g2, self.ciclo)
        self.client.post(self.url, datos(libre, dias=(0,), inicio='08:00', fin='09:00'))
        self.assertEqual(HorarioMateria.objects.filter(materia_grado=libre).count(), 1)

    def test_otro_profesor_en_la_misma_hora_no_es_empalme(self):
        otro = crear_profesor(nombre='Otro', telefono='3530000009')
        self.esp.profesor = otro
        self.esp.save()
        self.client.post(self.url, datos(self.esp, dias=(0,), inicio='08:00', fin='09:00'))
        self.assertEqual(HorarioMateria.objects.filter(materia_grado=self.esp).count(), 1)

    def test_las_materias_quitadas_del_profesor_no_cuentan(self):
        self.mat.activa = False
        self.mat.save()
        self.client.post(self.url, datos(self.esp, dias=(0,), inicio='08:00', fin='09:00'))
        self.assertEqual(HorarioMateria.objects.filter(materia_grado=self.esp).count(), 1)

    def test_el_selector_muestra_al_profesor(self):
        respuesta = self.client.get(self.url)
        etiquetas = [etiqueta for _, etiqueta in respuesta.context['form'].fields['materia_grado'].choices]
        self.assertIn('Español (ESP) · Rangel', etiquetas)


# ---------------------------------------------------------------------------
# Editar bloques
# ---------------------------------------------------------------------------
@PRUEBAS
class EditarConProfesorTests(BaseProfesorTests):
    def setUp(self):
        super().setUp()
        self.libre = bloque(self.esp, 1, (8, 0), (9, 0))
        self.url = reverse('horarios:editar', args=[self.libre.pk])

    def datos(self, **cambios):
        datos = {'materia_grado': self.esp.pk, 'dia_semana': 1, 'hora_inicio': '08:00', 'hora_fin': '09:00'}
        datos.update(cambios)
        return datos

    def test_rechaza_mover_el_bloque_sobre_otra_clase_del_profesor(self):
        respuesta = self.client.post(self.url, self.datos(dia_semana=0, hora_inicio='08:30', hora_fin='09:30'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'un profesor no puede estar en dos grupos a la vez')
        self.libre.refresh_from_db()
        self.assertEqual(self.libre.dia_semana, 1)

    def test_un_bloque_no_choca_consigo_mismo(self):
        self.assertEqual(self.client.post(self.url, self.datos(hora_fin='09:30')).status_code, 302)

    def test_acepta_moverlo_a_un_hueco_libre(self):
        self.assertEqual(self.client.post(self.url, self.datos(dia_semana=0, hora_inicio='09:00', hora_fin='10:00')).status_code, 302)


# ---------------------------------------------------------------------------
# Pantallas
# ---------------------------------------------------------------------------
@PRUEBAS
class PantallasConProfesorTests(BaseProfesorTests):
    def test_el_horario_del_grado_cuenta_las_materias_sin_profesor(self):
        asignar('CIE', 'Ciencias', self.g1, self.ciclo)
        respuesta = self.client.get(reverse('horarios:grado', args=[self.g1.pk]), {'ciclo': self.ciclo.pk})
        self.assertEqual([a.materia.clave for a in respuesta.context['sin_profesor']], ['CIE'])
        self.assertContains(respuesta, 'Sin profesor')

    def test_el_horario_del_grado_muestra_al_profesor_en_cada_bloque(self):
        respuesta = self.client.get(reverse('horarios:grado', args=[self.g1.pk]), {'ciclo': self.ciclo.pk})
        self.assertContains(respuesta, 'Rangel')

    def test_el_indice_marca_los_grados_con_materias_sin_profesor(self):
        asignar('CIE', 'Ciencias', self.g1, self.ciclo)
        respuesta = self.client.get(reverse('horarios:lista'), {'ciclo': self.ciclo.pk})
        filas = {str(f['grado']): f for n in respuesta.context['niveles'] for f in n['filas']}
        self.assertEqual((filas['1° Primaria']['sin_profesor'], filas['2° Primaria']['sin_profesor']), (1, 0))
        self.assertContains(respuesta, '1 sin profesor')

    def test_el_indice_resume_a_los_profesores_con_clases(self):
        bloque(self.esp, 1, (10, 0), (10, 30))
        crear_profesor(nombre='Sin', telefono='3530000009')                 # no da clases: no aparece
        respuesta = self.client.get(reverse('horarios:lista'), {'ciclo': self.ciclo.pk})
        profesores = respuesta.context['profesores']
        self.assertEqual([(p.pk, p.materias, p.duracion) for p in profesores], [(self.profesor.pk, 2, '1 h 30 min')])
        self.assertContains(respuesta, 'Por profesor')
        self.assertContains(respuesta, f'{self.profesor.get_absolute_url()}?ciclo={self.ciclo.pk}#horario')

    def test_el_resumen_por_profesor_pide_permiso_para_ver_profesores(self):
        self.con_permisos('view_horariomateria', 'view_materiagrado')
        respuesta = self.client.get(reverse('horarios:lista'), {'ciclo': self.ciclo.pk})
        self.assertNotContains(respuesta, 'Por profesor')

    def test_el_resumen_por_profesor_no_cuenta_dos_veces_a_quien_da_varias_materias(self):
        asignar('CIE', 'Ciencias', self.g2, self.ciclo, profesor=self.profesor)
        asignar('HIS', 'Historia', self.g1, self.ciclo, profesor=self.profesor)
        respuesta = self.client.get(reverse('horarios:lista'), {'ciclo': self.ciclo.pk})
        self.assertEqual([(p.pk, p.materias) for p in respuesta.context['profesores']], [(self.profesor.pk, 4)])

    def test_el_indice_con_ciclo_cerrado_muestra_los_profesores_de_ese_ciclo(self):
        vieja = asignar('MAT', 'Matemáticas', self.g1, self.cerrado, profesor=self.profesor)
        bloque(vieja, 2, (8, 0), (8, 30))
        respuesta = self.client.get(reverse('horarios:lista'), {'ciclo': self.cerrado.pk})
        self.assertEqual([(p.materias, p.duracion) for p in respuesta.context['profesores']], [(1, '30 min')])

    def test_el_indice_mantiene_consultas_constantes(self):
        with CaptureQueriesContext(connection) as pocas:
            self.client.get(reverse('horarios:lista'), {'ciclo': self.ciclo.pk})
        for i in range(3, 9):
            profesor = crear_profesor(nombre=f'P{i}', telefono=f'35300001{i:02d}')
            bloque(asignar(f'X{i}', f'Otra {i}', crear_grado('PRIMARIA', i), self.ciclo, profesor=profesor), i % 5, (8, 0), (9, 0))
        with CaptureQueriesContext(connection) as muchas:
            self.client.get(reverse('horarios:lista'), {'ciclo': self.ciclo.pk})
        self.assertEqual(len(muchas), len(pocas))
