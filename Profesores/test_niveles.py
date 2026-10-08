"""Niveles en los que da clases cada profesor (preescolar, primaria, secundaria, preparatoria): uno o varios."""
import csv
import importlib
import io
import re

from django.apps import apps
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from Alumnos.docentes import con_habilitados
from Alumnos.models import MateriaGrado, Profesor, ProfesorNivel
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    crear_grado,
    crear_profesor,
    materia_en_grado,
)

from .tests import datos_profesor


def con_niveles(profesor, *niveles):
    profesor.establecer_niveles(niveles)
    return profesor


@PRUEBAS
class NivelesDelModeloTests(BaseTestCase):
    def test_establecer_deja_exactamente_los_indicados_en_orden_escolar(self):
        profesor = crear_profesor()
        profesor.establecer_niveles(['SECUNDARIA', 'PREESCOLAR'])
        self.assertEqual(profesor.niveles_lista, ['PREESCOLAR', 'SECUNDARIA'])
        profesor.establecer_niveles(['PRIMARIA', 'SECUNDARIA'])
        self.assertEqual(profesor.niveles_lista, ['PRIMARIA', 'SECUNDARIA'])
        self.assertEqual(profesor.niveles_texto, 'Primaria, Secundaria')
        self.assertEqual(ProfesorNivel.objects.filter(profesor=profesor).count(), 2)

    def test_sin_niveles(self):
        profesor = crear_profesor(niveles=())
        self.assertEqual((profesor.niveles_lista, profesor.niveles_texto), ([], ''))

    def test_la_migracion_los_deduce_de_lo_que_ya_imparte(self):
        migracion = importlib.import_module('Alumnos.migrations.0014_profesor_niveles')
        ciclo = ciclo_actual_de_prueba()
        primaria, secundaria = crear_grado('PRIMARIA', 3), crear_grado('SECUNDARIA', 1)
        marta = crear_profesor(nombre='Marta', niveles=())
        beto = crear_profesor(nombre='Beto', telefono='3530000002', niveles=())
        sin_materias = crear_profesor(nombre='Ceci', telefono='3530000003', niveles=())
        materia_en_grado('MAT', primaria, ciclo, profesor=marta)
        materia_en_grado('ESP', secundaria, ciclo, profesor=marta, dia=1)
        materia_en_grado('CIE', secundaria, ciclo, profesor=beto, dia=2)
        migracion.niveles_de_lo_que_imparten(apps, None)
        migracion.niveles_de_lo_que_imparten(apps, None)   # repetible sin duplicar
        for profesor in (marta, beto, sin_materias):
            profesor.refresh_from_db()
        self.assertEqual(marta.niveles_lista, ['PRIMARIA', 'SECUNDARIA'])
        self.assertEqual(beto.niveles_lista, ['SECUNDARIA'])
        self.assertEqual(sin_materias.niveles_lista, [])


@PRUEBAS
class FormularioTests(BaseTestCase):
    def test_el_alta_ofrece_los_cuatro_niveles_como_casillas(self):
        html = self.client.get(reverse('profesores:crear')).content.decode()
        valores = re.findall(r'<input[^>]*type="checkbox"[^>]*name="niveles"[^>]*value="([A-Z]+)"', html)
        self.assertEqual(valores, ['PREESCOLAR', 'PRIMARIA', 'SECUNDARIA', 'PREPARATORIA'])
        self.assertIn('Niveles en los que da clases', html)

    def test_registra_uno_o_varios_niveles(self):
        respuesta = self.client.post(reverse('profesores:crear'), datos_profesor(niveles=['PREESCOLAR', 'PRIMARIA']))
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(Profesor.objects.get().niveles_lista, ['PREESCOLAR', 'PRIMARIA'])

    def test_es_obligatorio_elegir_al_menos_uno(self):
        datos = datos_profesor()
        datos.pop('niveles')
        respuesta = self.client.post(reverse('profesores:crear'), datos)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Elige al menos un nivel.')
        self.assertFalse(Profesor.objects.exists())

    def test_rechaza_un_nivel_que_no_existe(self):
        respuesta = self.client.post(reverse('profesores:crear'), datos_profesor(niveles=['UNIVERSIDAD']))
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Profesor.objects.exists())

    def test_al_editar_vienen_marcados_y_se_pueden_cambiar(self):
        profesor = con_niveles(crear_profesor(nombre='Ana', apellido_paterno='Lara', apellido_materno='Ruiz'), 'PRIMARIA', 'SECUNDARIA')
        url = reverse('profesores:editar', args=[profesor.pk])
        html = self.client.get(url).content.decode()
        marcados = re.findall(r'<input[^>]*name="niveles"[^>]*value="([A-Z]+)"[^>]*checked', html)
        self.assertEqual(marcados, ['PRIMARIA', 'SECUNDARIA'])
        self.client.post(url, datos_profesor(niveles=['PREPARATORIA']))
        self.assertEqual(Profesor.objects.get(pk=profesor.pk).niveles_lista, ['PREPARATORIA'])

    def test_un_profesor_anterior_sin_niveles_debe_elegirlos_al_editarlo(self):
        profesor = crear_profesor(nombre='Ana', apellido_paterno='Lara', niveles=())
        datos = datos_profesor()
        datos.pop('niveles')
        respuesta = self.client.post(reverse('profesores:editar', args=[profesor.pk]), datos)
        self.assertContains(respuesta, 'Elige al menos un nivel.')


@PRUEBAS
class ListadoYPerfilTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.marta = con_niveles(crear_profesor(nombre='Marta', apellido_paterno='Rangel'), 'PRIMARIA', 'SECUNDARIA')
        self.beto = con_niveles(crear_profesor(nombre='Beto', apellido_paterno='Aguilar', telefono='3530000002'), 'PREESCOLAR')
        self.ceci = crear_profesor(nombre='Ceci', apellido_paterno='Bravo', telefono='3530000003', niveles=())

    def nombres(self, **filtros):
        respuesta = self.client.get(reverse('profesores:lista'), filtros)
        return [p.nombre for p in respuesta.context['pagina']]

    def test_el_listado_muestra_sus_niveles(self):
        html = self.client.get(reverse('profesores:lista')).content.decode()
        self.assertRegex(html, r'tag--tono-2">Primaria</li><li class="tag tag--tono-3">Secundaria')
        self.assertIn('tag--tono-1">Preescolar', html)
        self.assertIn('Sin nivel', html)

    def test_se_filtra_por_nivel(self):
        self.assertEqual(self.nombres(nivel='SECUNDARIA'), ['Marta'])
        self.assertEqual(self.nombres(nivel='PREESCOLAR'), ['Beto'])
        self.assertEqual(self.nombres(nivel='PREPARATORIA'), [])
        self.assertEqual(self.nombres(nivel='SIN_NIVEL'), ['Ceci'])

    def test_las_consultas_no_crecen_con_los_profesores(self):
        def consultas():
            with CaptureQueriesContext(connection) as capturadas:
                self.client.get(reverse('profesores:lista'), {'por_pagina': 50})
            return len(capturadas)

        antes = consultas()
        for n in range(8):
            con_niveles(crear_profesor(nombre=f'P{n}', telefono=f'35311100{n:02d}'), 'PRIMARIA', 'SECUNDARIA')
        self.assertEqual(consultas(), antes)

    def test_el_perfil_muestra_sus_niveles(self):
        self.assertContains(self.client.get(self.marta.get_absolute_url()), 'Secundaria')
        self.assertContains(self.client.get(self.ceci.get_absolute_url()), 'Sin nivel')

    def test_la_exportacion_incluye_los_niveles(self):
        filas = list(csv.reader(io.StringIO(self.client.get(reverse('profesores:exportar')).content.decode('utf-8').lstrip('﻿'))))
        columna = filas[0].index('Niveles')
        por_nombre = {fila[0]: fila[columna] for fila in filas[1:]}
        self.assertEqual(por_nombre, {'Marta': 'Primaria, Secundaria', 'Beto': 'Preescolar', 'Ceci': ''})


@PRUEBAS
class SugerenciasAlAsignarTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.primaria = crear_grado('PRIMARIA', 2)
        self.marta = con_niveles(crear_profesor(nombre='Marta'), 'PRIMARIA')
        self.beto = con_niveles(crear_profesor(nombre='Beto', telefono='3530000002'), 'SECUNDARIA')
        self.baja = con_niveles(crear_profesor(nombre='Inés', telefono='3530000003', estatus='INACTIVO'), 'PRIMARIA')
        self.asignacion = materia_en_grado('MAT', self.primaria, self.ciclo)

    def test_cada_asignacion_sabe_quien_da_clases_en_el_nivel_de_su_grado(self):
        fila = con_habilitados(MateriaGrado.objects.filter(pk=self.asignacion.pk))[0]
        self.assertEqual(fila.del_nivel, str(self.marta.pk))          # sin los de otro nivel ni los dados de baja
        self.assertEqual(fila.nivel_del_grado, 'Primaria')

    def test_el_perfil_del_grado_lo_manda_a_la_ventana_de_asignar(self):
        html = self.client.get(self.primaria.get_absolute_url()).content.decode()
        boton = re.search(r'<button[^>]*data-asignar-profesor[^>]*>', html).group(0)
        self.assertIn(f'data-del-nivel="{self.marta.pk}"', boton)
        self.assertIn('data-nivel="Primaria"', boton)

    def test_el_perfil_de_la_materia_tambien(self):
        html = self.client.get(reverse('materias:detalle', args=[self.asignacion.materia_id])).content.decode()
        boton = re.search(r'<button[^>]*data-asignar-profesor[^>]*>', html).group(0)
        self.assertIn(f'data-del-nivel="{self.marta.pk}"', boton)

    def test_el_tablero_de_asignaciones_tambien(self):
        html = self.client.get(reverse('asignaciones:tablero')).content.decode()
        boton = re.search(r'<button[^>]*data-asignar-profesor[^>]*>', html).group(0)
        self.assertIn(f'data-del-nivel="{self.marta.pk}"', boton)


@PRUEBAS
class DocenteDesdeUsuariosTests(BaseTestCase):
    def alta(self, **cambios):
        from Usuarios.models import Rol
        datos = {
            'first_name': 'Marta', 'last_name': '', 'username': 'marta.rangel', 'email': '', 'telefono': '353 444 5566',
            'cargo': '', 'rol': Rol.objects.get(grupo__name='Docente').pk, 'contrasena': '',
            'docente-es_docente': 'on', 'docente-modo': 'nuevo', 'docente-apellido_paterno': 'Rangel',
            'docente-niveles': ['PRIMARIA', 'PREPARATORIA'],
        }
        datos.update(cambios)
        return {k: v for k, v in datos.items() if v is not None}

    def test_la_ficha_nueva_lleva_sus_niveles(self):
        html = self.client.get(reverse('usuarios:crear')).content.decode()
        self.assertIn('name="docente-niveles"', html)
        self.assertEqual(self.client.post(reverse('usuarios:crear'), self.alta()).status_code, 302)
        self.assertEqual(Profesor.objects.get().niveles_lista, ['PRIMARIA', 'PREPARATORIA'])

    def test_sin_niveles_no_se_registra(self):
        respuesta = self.client.post(reverse('usuarios:crear'), self.alta(**{'docente-niveles': None}))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Elige al menos un nivel.')
        self.assertFalse(Profesor.objects.exists())

    def test_vincular_a_un_profesor_ya_registrado_no_los_pide(self):
        profesor = con_niveles(crear_profesor(nombre='Marta', apellido_paterno='Rangel'), 'SECUNDARIA')
        datos = self.alta(**{'docente-modo': 'existente', 'docente-profesor': profesor.pk, 'docente-niveles': None})
        self.assertEqual(self.client.post(reverse('usuarios:crear'), datos).status_code, 302)
        profesor.refresh_from_db()
        self.assertEqual(profesor.niveles_lista, ['SECUNDARIA'])
        self.assertIsNotNone(profesor.usuario_id)


@PRUEBAS
class ColumnaDeNivelesTests(BaseTestCase):
    def test_los_niveles_van_en_su_propia_columna(self):
        con_niveles(crear_profesor(nombre='Marta', apellido_paterno='Rangel'), 'PRIMARIA')
        html = self.client.get(reverse('profesores:lista')).content.decode()
        encabezados = re.findall(r'<th class="table__th[^"]*" scope="col">([^<]+)</th>', html)
        self.assertEqual(encabezados[:3], ['Profesor', 'Niveles', 'Contacto'])
        celda = re.search(r'<td class="table__cell" data-label="Niveles">(.*?)</td>', html, re.S).group(1)
        self.assertIn('Primaria', celda)
        persona = re.search(r'<a class="person".*?</a>', html, re.S).group(0)
        self.assertNotIn('tag-list', persona)   # ya no van debajo del nombre
