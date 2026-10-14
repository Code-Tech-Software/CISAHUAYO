"""El menú lateral y las acciones rápidas, con las rutas reales del proyecto."""
from django.test import RequestFactory, SimpleTestCase

from CISAHUAYO.context_processors import ACCIONES_RAPIDAS, NAVEGACION, navegacion

# Secciones que todavía no existen: su enlace apunta a «#» hasta que se registre su ruta.
PENDIENTES = set()


class MenuConRutasRealesTests(SimpleTestCase):
    def setUp(self):
        self.contexto = navegacion(RequestFactory().get('/'))
        # Sin usuario no se filtra nada: la sección de prefectura (solo para sus cuentas) se revisa aparte
        self.items = {el['etiqueta']: el for s in self.contexto['navegacion'] if s['titulo'] != 'Prefectura' for el in s['elementos']}

    def test_cada_seccion_del_menu_tiene_su_ruta(self):
        for etiqueta, elemento in self.items.items():
            if etiqueta in PENDIENTES:
                self.assertFalse(elemento['disponible'], etiqueta)
            else:
                self.assertTrue(elemento['disponible'], f'{etiqueta} no tiene ruta registrada')
                self.assertTrue(elemento['url'].startswith('/'), etiqueta)

    def test_el_orden_del_menu(self):
        self.assertEqual(list(self.items), [
            'Panel de control', 'Estudiantes', 'Tutores', 'Profesores',
            'Ciclos escolares', 'Grados', 'Grupos', 'Periodos', 'Inscripciones a grupos', 'Materias', 'Asignaciones de materias',
            'Horarios', 'Asistencias', 'Registro de conducta', 'Reportes de conducta',
            'Usuarios', 'Roles y permisos', 'Ajustes',
        ])

    def test_urls_de_las_secciones(self):
        self.assertEqual(
            {k: self.items[k]['url'] for k in ('Estudiantes', 'Tutores', 'Profesores', 'Inscripciones a grupos', 'Ciclos escolares', 'Grados', 'Materias', 'Asignaciones de materias', 'Horarios', 'Periodos', 'Asistencias')},
            {'Estudiantes': '/alumnos/', 'Tutores': '/tutores/', 'Profesores': '/profesores/', 'Inscripciones a grupos': '/inscripciones/',
             'Ciclos escolares': '/ciclos/', 'Grados': '/grados/', 'Materias': '/materias/', 'Asignaciones de materias': '/asignaciones/',
             'Horarios': '/horarios/', 'Periodos': '/periodos/', 'Asistencias': '/asistencias/'},
        )

    def test_las_acciones_rapidas_existen_todas(self):
        etiquetas = [a['etiqueta'] for a in self.contexto['acciones_rapidas']]
        unicas = []   # la misma acción por dos caminos (administración y prefectura) se ofrece una vez
        for accion in ACCIONES_RAPIDAS:
            if accion['ruta'] not in [a['ruta'] for a in unicas]:
                unicas.append(accion)
        self.assertEqual(etiquetas, [a['etiqueta'] for a in unicas])
        self.assertIn('Nueva materia', etiquetas)
        self.assertIn('Nuevo profesor', etiquetas)
        self.assertIn('Pantalla de entrada', etiquetas)
        self.assertIn('Nueva justificación', etiquetas)

    def test_cada_seccion_se_activa_en_su_ruta(self):
        for ruta, etiqueta in (('/materias/3/', 'Materias'), ('/horarios/grado/2/', 'Horarios'), ('/ciclos/', 'Ciclos escolares'),
                               ('/grados/1/', 'Grados'), ('/inscripciones/promocion/', 'Inscripciones a grupos'), ('/profesores/4/', 'Profesores'),
                               ('/asistencias/', 'Asistencias'), ('/asistencias/clases/3/', 'Asistencias'), ('/asistencias/entrada/', 'Asistencias')):
            contexto = navegacion(RequestFactory().get(ruta))
            activos = [el['etiqueta'] for s in contexto['navegacion'] for el in s['elementos'] if el['activo']]
            self.assertEqual(activos, [etiqueta], ruta)

    def test_el_menu_declara_las_secciones_esperadas(self):
        rutas = [el['ruta'] for s in NAVEGACION for el in s['elementos']]
        self.assertIn('materias:lista', rutas)
        self.assertIn('horarios:lista', rutas)
        self.assertIn('profesores:lista', rutas)
        self.assertIn('asistencias:inicio', rutas)

    def test_las_secciones_del_menu(self):
        secciones = {s['titulo']: [el['etiqueta'] for el in s['elementos']] for s in NAVEGACION}
        self.assertEqual(list(secciones), [None, 'Prefectura', 'Comunidad escolar', 'Gestión académica', 'Sistema'])
        self.assertEqual(secciones[None], ['Panel de control'])
        self.assertEqual(secciones['Prefectura'], ['Inicio', 'Estudiantes', 'Asistencia', 'Conducta', 'Seguimiento', 'Reportes'])
        self.assertEqual(secciones['Comunidad escolar'], ['Estudiantes', 'Tutores', 'Profesores'])
        self.assertEqual(secciones['Gestión académica'], [
            'Ciclos escolares', 'Grados', 'Grupos', 'Periodos', 'Inscripciones a grupos', 'Materias', 'Asignaciones de materias',
            'Horarios', 'Asistencias', 'Registro de conducta', 'Reportes de conducta',
        ])
        self.assertEqual(secciones['Sistema'], ['Usuarios', 'Roles y permisos', 'Ajustes'])
