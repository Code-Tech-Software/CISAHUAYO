"""La tabla principal de estudiantes muestra el parentesco del tutor principal, debajo de su nombre."""
import csv
import io
import re

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from Alumnos.models import TutorAlumno
from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase, crear_alumno, crear_tutor, vincular


def celda_del_tutor(html, alumno):
    """El HTML de la celda «Tutor principal» de la fila de ese estudiante."""
    fila = re.search(r'<tr class="table__row">(?:(?!</tr>).)*?%s(?:(?!</tr>).)*?</tr>' % re.escape(alumno.get_absolute_url()), html, re.S).group(0)
    return re.search(r'<td class="table__cell table__col--wide" data-label="Tutor principal">(.*?)</td>', fila, re.S).group(1)


@PRUEBAS
class ParentescoEnLaTablaTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.alumno = crear_alumno(nombre='Luis', apellido_paterno='Pérez')
        self.tutor = crear_tutor(nombre='Rosa', apellido_paterno='Mora', telefono='3531112233')

    def celda(self):
        return celda_del_tutor(self.client.get(reverse('alumnos:lista')).content.decode(), self.alumno)

    def test_muestra_el_parentesco_debajo_del_nombre_y_antes_del_telefono(self):
        vincular(self.tutor, self.alumno, parentesco='MADRE', tutor_principal=True)
        celda = self.celda()
        self.assertIn('Rosa', celda)
        self.assertIn('Madre', celda)
        self.assertLess(celda.index('Rosa'), celda.index('Madre'))
        self.assertLess(celda.index('Madre'), celda.index('353 111 2233'))
        self.assertRegex(celda, r'cell-stack__main">Rosa[^<]*</span>\s*<span class="cell-stack__sub">Madre</span>')

    def test_muestra_el_nombre_del_parentesco_de_cada_opcion(self):
        for clave, nombre in TutorAlumno.PARENTESCO_CHOICES:
            with self.subTest(parentesco=clave):
                TutorAlumno.objects.all().delete()
                vincular(self.tutor, self.alumno, parentesco=clave, tutor_principal=True)
                self.assertIn(f'<span class="cell-stack__sub">{nombre}</span>', self.celda())

    def test_es_el_del_tutor_principal_y_no_el_de_otro_tutor(self):
        padre = crear_tutor(nombre='Jorge', apellido_paterno='Pérez', telefono='3534445566')
        vincular(padre, self.alumno, parentesco='PADRE', tutor_principal=False)
        vincular(self.tutor, self.alumno, parentesco='ABUELA', tutor_principal=True)
        celda = self.celda()
        self.assertIn('Rosa', celda)
        self.assertIn('Abuela', celda)
        self.assertNotIn('Jorge', celda)
        self.assertNotIn('Padre', celda)

    def test_un_vinculo_dado_de_baja_no_cuenta(self):
        vincular(self.tutor, self.alumno, parentesco='MADRE', tutor_principal=True, activo=False)
        celda = self.celda()
        self.assertIn('Sin tutor', celda)
        self.assertNotIn('Madre', celda)

    def test_sin_tutor_no_hay_parentesco(self):
        celda = self.celda()
        self.assertIn('Sin tutor', celda)
        self.assertNotIn('cell-stack__sub', celda)

    def test_cada_estudiante_muestra_el_suyo(self):
        otra = crear_alumno(nombre='Ana', apellido_paterno='Gómez')
        otro_tutor = crear_tutor(nombre='Pedro', apellido_paterno='Gómez')
        vincular(self.tutor, self.alumno, parentesco='MADRE', tutor_principal=True)
        vincular(otro_tutor, otra, parentesco='TIO', tutor_principal=True)
        html = self.client.get(reverse('alumnos:lista')).content.decode()
        self.assertIn('Madre', celda_del_tutor(html, self.alumno))
        self.assertIn('Tío', celda_del_tutor(html, otra))

    def test_no_agrega_consultas_por_fila(self):
        def consultas():
            with CaptureQueriesContext(connection) as capturadas:
                self.client.get(reverse('alumnos:lista'), {'por_pagina': 100})
            return len(capturadas)

        for n in range(4):
            vincular(crear_tutor(nombre=f'T{n}'), crear_alumno(), parentesco='MADRE', tutor_principal=True)
        pocas = consultas()
        for n in range(10):
            vincular(crear_tutor(nombre=f'U{n}'), crear_alumno(), parentesco='PADRE', tutor_principal=True)
        self.assertEqual(consultas(), pocas)


@PRUEBAS
class ParentescoEnLaExportacionTests(BaseTestCase):
    def filas(self):
        respuesta = self.client.get(reverse('alumnos:exportar'))
        return list(csv.reader(io.StringIO(respuesta.content.decode('utf-8').lstrip('﻿'))))

    def test_la_columna_va_despues_del_tutor_principal(self):
        alumno = crear_alumno()
        vincular(crear_tutor(nombre='Rosa', apellido_paterno='Mora'), alumno, parentesco='MADRE', tutor_principal=True)
        filas = self.filas()
        encabezado = filas[0]
        self.assertEqual(encabezado[encabezado.index('Tutor principal') + 1], 'Parentesco del tutor')
        self.assertEqual(filas[1][encabezado.index('Parentesco del tutor')], 'Madre')
        self.assertIn('Rosa', filas[1][encabezado.index('Tutor principal')])

    def test_sin_tutor_la_celda_queda_vacia(self):
        crear_alumno()
        filas = self.filas()
        self.assertEqual(filas[1][filas[0].index('Parentesco del tutor')], '')
