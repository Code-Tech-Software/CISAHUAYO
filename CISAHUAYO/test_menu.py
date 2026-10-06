"""El menú lateral y las acciones rápidas, con las rutas reales del proyecto."""
from django.test import RequestFactory, SimpleTestCase

from CISAHUAYO.context_processors import ACCIONES_RAPIDAS, NAVEGACION, navegacion

# Secciones que todavía no existen: su enlace apunta a «#» hasta que se registre su ruta.
PENDIENTES = set()


class MenuConRutasRealesTests(SimpleTestCase):
    def setUp(self):
        self.contexto = navegacion(RequestFactory().get('/'))
        self.items = {el['etiqueta']: el for s in self.contexto['navegacion'] for el in s['elementos']}

    def test_cada_seccion_del_menu_tiene_su_ruta(self):
        for etiqueta, elemento in self.items.items():
            if etiqueta in PENDIENTES:
                self.assertFalse(elemento['disponible'], etiqueta)
            else:
                self.assertTrue(elemento['disponible'], f'{etiqueta} no tiene ruta registrada')
                self.assertTrue(elemento['url'].startswith('/'), etiqueta)

    def test_el_orden_del_menu(self):
        self.assertEqual(list(self.items), [
            'Panel de control',
            'Estudiantes', 'Tutores', 'Inscripciones',
            'Asignaciones académicas', 'Materias', 'Grados', 'Ciclos escolares', 'Horarios',
            'Profesores', 'Carga docente',
            'Resumen del día', 'Pase de lista', 'Justificaciones', 'Reportes', 'Pantalla de entrada',
            'Usuarios', 'Roles y permisos', 'Ajustes de asistencia',
        ])

    def test_los_grupos_del_menu(self):
        grupos = [(s['titulo'], s['clave'], s['desplegable']) for s in self.contexto['navegacion']]
        self.assertEqual(grupos, [
            (None, '', False),
            ('Control escolar', 'control', True),
            ('Académico', 'academico', True),
            ('Personal docente', 'personal', True),
            ('Asistencias', 'asistencias', True),
            ('Configuración', 'configuracion', True),
        ])

    def test_el_grupo_de_la_pagina_actual_queda_abierto(self):
        contexto = navegacion(RequestFactory().get('/materias/3/'))
        abiertos = [s['titulo'] for s in contexto['navegacion'] if s['activo']]
        self.assertEqual(abiertos, ['Académico'])
        self.assertEqual([s['titulo'] for s in self.contexto['navegacion'] if s['activo']], [None])   # en el panel, ninguno

    def test_urls_de_las_secciones(self):
        self.assertEqual(
            {k: self.items[k]['url'] for k in (
                'Estudiantes', 'Tutores', 'Profesores', 'Inscripciones', 'Ciclos escolares', 'Grados', 'Materias',
                'Asignaciones académicas', 'Carga docente', 'Horarios', 'Resumen del día', 'Pase de lista', 'Ajustes de asistencia',
            )},
            {'Estudiantes': '/alumnos/', 'Tutores': '/tutores/', 'Profesores': '/profesores/', 'Inscripciones': '/inscripciones/',
             'Ciclos escolares': '/ciclos/', 'Grados': '/grados/', 'Materias': '/materias/', 'Asignaciones académicas': '/asignaciones/',
             'Carga docente': '/asignaciones/profesores/', 'Horarios': '/horarios/', 'Resumen del día': '/asistencias/',
             'Pase de lista': '/asistencias/clases/', 'Ajustes de asistencia': '/asistencias/ajustes/'},
        )

    def test_las_acciones_rapidas_existen_todas(self):
        etiquetas = [a['etiqueta'] for a in self.contexto['acciones_rapidas']]
        self.assertEqual(etiquetas, [a['etiqueta'] for a in ACCIONES_RAPIDAS])
        self.assertIn('Nueva materia', etiquetas)
        self.assertIn('Nuevo profesor', etiquetas)
        self.assertIn('Pantalla de entrada', etiquetas)
        self.assertIn('Nueva justificación', etiquetas)

    def test_cada_seccion_se_activa_en_su_ruta(self):
        for ruta, etiqueta in (('/materias/3/', 'Materias'), ('/horarios/grado/2/', 'Horarios'), ('/ciclos/', 'Ciclos escolares'),
                               ('/grados/1/', 'Grados'), ('/inscripciones/promocion/', 'Inscripciones'), ('/profesores/4/', 'Profesores'),
                               ('/asistencias/', 'Resumen del día'), ('/asistencias/dia/', 'Resumen del día'),
                               ('/asistencias/clases/3/', 'Pase de lista'), ('/asistencias/entrada/', 'Pantalla de entrada'),
                               ('/asistencias/ajustes/', 'Ajustes de asistencia'), ('/asignaciones/', 'Asignaciones académicas'),
                               ('/asignaciones/lista/', 'Asignaciones académicas'), ('/asignaciones/nueva/', 'Asignaciones académicas'),
                               ('/asignaciones/profesores/', 'Carga docente')):
            contexto = navegacion(RequestFactory().get(ruta))
            activos = [el['etiqueta'] for s in contexto['navegacion'] for el in s['elementos'] if el['activo']]
            self.assertEqual(activos, [etiqueta], ruta)

    def test_el_menu_declara_las_secciones_esperadas(self):
        rutas = [el['ruta'] for s in NAVEGACION for el in s['elementos']]
        self.assertIn('materias:lista', rutas)
        self.assertIn('horarios:lista', rutas)
        self.assertIn('profesores:lista', rutas)
        self.assertIn('asistencias:inicio', rutas)
