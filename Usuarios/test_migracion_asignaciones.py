"""Usuarios.0002: los roles que ya existían y usaban las materias reciben el permiso de ver las asignaciones."""
import importlib

from django.apps import apps
from django.contrib.auth.models import Group, Permission
from django.test import TestCase


class VerLasAsignacionesTests(TestCase):
    def correr(self):
        importlib.import_module('Usuarios.migrations.0002_ver_asignaciones').conceder_ver_el_plan(apps, None)

    def grupo_con(self, nombre, *codigos):
        grupo = Group.objects.create(name=nombre)
        grupo.permissions.set(Permission.objects.filter(content_type__app_label='Alumnos', codename__in=codigos))
        return grupo

    def tiene(self, grupo):
        return grupo.permissions.filter(codename='view_materiagrado').exists()

    def test_lo_reciben_quienes_ya_veian_materias_o_cambiaban_el_plan(self):
        con_materias = self.grupo_con('Antiguo A', 'view_materia')
        con_plan = self.grupo_con('Antiguo B', 'change_materiagrado')
        sin_nada = self.grupo_con('Antiguo C', 'view_alumno')
        self.correr()
        self.assertTrue(self.tiene(con_materias))
        self.assertTrue(self.tiene(con_plan))
        self.assertFalse(self.tiene(sin_nada))

    def test_correrla_otra_vez_no_duplica(self):
        grupo = self.grupo_con('Antiguo A', 'view_materia')
        self.correr()
        self.correr()
        self.assertEqual(grupo.permissions.filter(codename='view_materiagrado').count(), 1)
