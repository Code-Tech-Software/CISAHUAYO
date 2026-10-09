"""Dar de baja desde los listados (materias, grados y profesores): cada fila o tarjeta tiene su botón, que abre una sola
ventana de confirmación (static/js/baja-lista.js) con lo mismo que ofrece el perfil."""
import re

from django.urls import reverse

from Alumnos.models import Grado, Materia, MateriaGrado, Profesor
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    crear_alumno,
    crear_grado,
    crear_profesor,
    crear_usuario,
    inscribir,
)


def boton_de_baja(html, accion):
    """El botón [data-baja] que manda a esa ruta, o None."""
    for boton in re.findall(r'<button[^>]*data-baja\b[^>]*>', html, re.S):
        if f'data-action="{accion}"' in boton:
            return boton
    return None


@PRUEBAS
class MateriasTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.grado = crear_grado('PRIMARIA', 2)
        self.en_plan = Materia.objects.create(clave='MAT', nombre='Matemáticas', grado=self.grado)
        MateriaGrado.objects.create(materia=self.en_plan, grado=self.grado, ciclo=self.ciclo)
        self.sin_plan = Materia.objects.create(clave='ART', nombre='Arte')

    def test_cada_fila_tiene_su_boton_y_hay_una_sola_ventana(self):
        html = self.client.get(reverse('materias:lista')).content.decode()
        boton = boton_de_baja(html, reverse('materias:baja', args=[self.en_plan.pk]))
        self.assertIsNotNone(boton)
        self.assertIn('data-modal-open="modal-baja"', boton)
        self.assertIn('data-opcion-plan="También quitarla del plan del ciclo 2026-2027 (2° Primaria)"', boton)
        self.assertIn('data-opcion-plan=""', boton_de_baja(html, reverse('materias:baja', args=[self.sin_plan.pk])))
        self.assertEqual(html.count('id="modal-baja"'), 1)
        self.assertIn('data-baja-opcion="plan"', html)
        self.assertIn('js/baja-lista.js', html)

    def test_la_baja_desde_el_listado_quita_del_plan_si_se_pide(self):
        respuesta = self.client.post(reverse('materias:baja', args=[self.en_plan.pk]), {'quitar_del_ciclo': 'on'}, follow=True)
        self.assertRedirects(respuesta, reverse('materias:lista'))
        self.en_plan.refresh_from_db()
        self.assertFalse(self.en_plan.activa)
        self.assertFalse(MateriaGrado.objects.get(materia=self.en_plan).activa)

    def test_no_aparece_en_las_bajas_ni_sin_permiso(self):
        html = self.client.get(reverse('materias:lista'), {'estado': 'BAJA'}).content.decode()
        self.assertNotIn('data-baja', html)
        self.con_permisos('view_materia', 'change_materia')
        html = self.client.get(reverse('materias:lista')).content.decode()
        self.assertIsNone(boton_de_baja(html, reverse('materias:baja', args=[self.en_plan.pk])))
        self.assertNotIn('id="modal-baja"', html)


@PRUEBAS
class GradosTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.primero, self.segundo = crear_grado('PRIMARIA', 1), crear_grado('PRIMARIA', 2)
        inscribir(crear_alumno(), self.ciclo, self.primero)

    def test_cada_tarjeta_tiene_el_boton_junto_al_lapiz(self):
        html = self.client.get(reverse('grados:lista')).content.decode()
        acciones = re.search(rf'<div class="grade-card__actions">.*?{re.escape(reverse("grados:baja", args=[self.primero.pk]))}.*?</div>', html, re.S).group(0)
        self.assertIn(reverse('grados:editar', args=[self.primero.pk]), acciones)
        boton = boton_de_baja(html, reverse('grados:baja', args=[self.primero.pk]))
        self.assertIn('data-aviso="Tiene 1 estudiante inscrito en el ciclo actual.', boton)
        self.assertIn('data-aviso=""', boton_de_baja(html, reverse('grados:baja', args=[self.segundo.pk])))
        self.assertEqual(html.count('id="modal-baja"'), 1)

    def test_la_baja_funciona_desde_ahi(self):
        self.client.post(reverse('grados:baja', args=[self.segundo.pk]))
        self.assertFalse(Grado.objects.get(pk=self.segundo.pk).activo)

    def test_solo_con_permiso_de_dar_de_baja_y_no_en_las_bajas(self):
        self.assertNotIn('data-baja', self.client.get(reverse('grados:lista'), {'estado': 'BAJA'}).content.decode())
        self.con_permisos('view_grado', 'delete_grado')                     # sin editar: solo el bote
        html = self.client.get(reverse('grados:lista')).content.decode()
        self.assertIsNotNone(boton_de_baja(html, reverse('grados:baja', args=[self.primero.pk])))
        self.assertNotIn(reverse('grados:editar', args=[self.primero.pk]), html)


@PRUEBAS
class ProfesoresTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        grado = crear_grado('PRIMARIA', 1)
        self.marta = crear_profesor(nombre='Marta')
        self.beto = crear_profesor(nombre='Beto', telefono='3530000002')
        materia = Materia.objects.create(clave='MAT', nombre='Matemáticas', grado=grado)
        MateriaGrado.objects.create(materia=materia, grado=grado, ciclo=self.ciclo, profesor=self.marta)
        self.cuenta = crear_usuario('marta.rangel')
        Profesor.objects.filter(pk=self.marta.pk).update(usuario=self.cuenta)

    def test_cada_fila_trae_sus_opciones(self):
        html = self.client.get(reverse('profesores:lista')).content.decode()
        marta = boton_de_baja(html, reverse('profesores:baja', args=[self.marta.pk]))
        self.assertIn('data-aviso="Imparte 1 materia en el ciclo actual.', marta)
        self.assertIn('data-opcion-materias="También quitarlo de su materia del ciclo actual"', marta)
        self.assertIn('data-opcion-cuenta="También desactivar su cuenta «marta.rangel»"', marta)
        beto = boton_de_baja(html, reverse('profesores:baja', args=[self.beto.pk]))
        self.assertIn('data-opcion-materias=""', beto)
        self.assertIn('data-opcion-cuenta=""', beto)
        for opcion in ('materias', 'cuenta'):
            self.assertIn(f'data-baja-opcion="{opcion}"', html)
        self.assertEqual(html.count('id="modal-baja"'), 1)

    def test_la_baja_con_sus_opciones(self):
        self.client.post(reverse('profesores:baja', args=[self.marta.pk]), {'quitar_del_ciclo': 'on', 'desactivar_cuenta': 'on'})
        self.marta.refresh_from_db()
        self.cuenta.refresh_from_db()
        self.assertEqual(self.marta.estatus, 'INACTIVO')
        self.assertFalse(self.cuenta.is_active)
        self.assertIsNone(MateriaGrado.objects.get().profesor)

    def test_sin_permiso_de_cuentas_no_ofrece_desactivarla(self):
        self.con_permisos('view_profesor', 'delete_profesor')
        html = self.client.get(reverse('profesores:lista')).content.decode()
        self.assertIn('data-opcion-cuenta=""', boton_de_baja(html, reverse('profesores:baja', args=[self.marta.pk])))

    def test_no_aparece_en_las_bajas(self):
        Profesor.objects.filter(pk=self.beto.pk).update(estatus='INACTIVO')
        html = self.client.get(reverse('profesores:lista'), {'estatus': 'INACTIVO'}).content.decode()
        self.assertIsNone(boton_de_baja(html, reverse('profesores:baja', args=[self.beto.pk])))
