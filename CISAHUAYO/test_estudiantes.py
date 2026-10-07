"""«Estudiante» en lugar de «alumno» en todo lo que se lee en pantalla (las rutas y el código conservan su nombre).

La palabra «alumno/alumnos» ya no debe aparecer en el texto visible: ni en títulos, menús, botones, tablas, mensajes,
formularios, avisos de error, exportaciones ni scripts. Se comprueba renderizando las pantallas con datos y vacías.
"""
import csv
import io
import re
from html import unescape
from pathlib import Path

from django.conf import settings
from django.urls import reverse

from Alumnos.models import Alumno, Grado, HorarioMateria, Inscripcion, Materia, MateriaGrado, TutorAlumno
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    crear_alumno,
    crear_grado,
    crear_profesor,
    crear_tutor,
    inscribir,
    vincular,
)

RAIZ = Path(settings.BASE_DIR)
PALABRA = re.compile(r'alumn[oa]s?\b|alumnado', re.I)


def texto_visible(html):
    """Lo que ve la persona: el texto de la página y los atributos que se leen (aria-label, title, placeholder...)."""
    html = re.sub(r'<(script|style)\b.*?</\1>', ' ', html, flags=re.S | re.I)
    html = re.sub(r'<!--.*?-->', ' ', html, flags=re.S)
    atributos = re.findall(r'\s(?:aria-label|title|alt|placeholder|data-label|data-tooltip)="([^"]*)"', html)
    return unescape(' '.join([re.sub(r'<[^>]+>', ' ', html), *atributos]))


def contexto(texto, hallazgo):
    inicio = max(hallazgo.start() - 40, 0)
    return texto[inicio:hallazgo.end() + 40].replace('\n', ' ')


@PRUEBAS
class NingunaPantallaDiceAlumnoTests(BaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.ciclo = ciclo_actual_de_prueba()
        cls.preescolar = crear_grado('PREESCOLAR', 1)
        cls.primero = crear_grado('SECUNDARIA', 1, equivalencia='7')
        cls.alumno = crear_alumno(nombre='Luis', apellido_paterno='Pérez')
        cls.tutor = crear_tutor()
        vincular(cls.tutor, cls.alumno, tutor_principal=True)
        cls.inscripcion = inscribir(cls.alumno, cls.ciclo, cls.primero)
        cls.profesor = crear_profesor()
        cls.materia = Materia.objects.create(clave='MAT', nombre='Matemáticas')
        cls.asignacion = MateriaGrado.objects.create(materia=cls.materia, grado=cls.primero, ciclo=cls.ciclo, profesor=cls.profesor)

    def urls(self):
        a, t, g, c = self.alumno.pk, self.tutor.pk, self.primero.pk, self.ciclo.pk
        return [
            reverse('inicio'),
            reverse('alumnos:lista'), reverse('alumnos:detalle', args=[a]), reverse('alumnos:crear'), reverse('alumnos:editar', args=[a]),
            reverse('tutores:lista'), reverse('tutores:detalle', args=[t]), reverse('tutores:crear'),
            reverse('profesores:lista'), reverse('profesores:detalle', args=[self.profesor.pk]),
            reverse('ciclos:lista'), reverse('ciclos:detalle', args=[c]),
            reverse('grados:lista'), reverse('grados:detalle', args=[g]), reverse('grados:crear'),
            reverse('inscripciones:lista'), reverse('inscripciones:crear'), reverse('inscripciones:promocion'),
            reverse('inscripciones:editar', args=[self.inscripcion.pk]),
            reverse('materias:lista'), reverse('materias:detalle', args=[self.materia.pk]),
            reverse('horarios:lista'), reverse('horarios:grado', args=[g]),
            reverse('asignaciones:tablero'), reverse('asignaciones:carga'), reverse('asignaciones:movimientos'),
            reverse('asistencias:inicio'), reverse('asistencias:dia'), reverse('asistencias:clases'),
            reverse('asistencias:justificaciones'), reverse('asistencias:justificacion_crear'),
            reverse('asistencias:reporte'), reverse('asistencias:ajustes'), reverse('asistencias:alumno', args=[a]),
            reverse('asistencias:clase', args=[self.asignacion.pk]),
            reverse('usuarios:lista'), reverse('usuarios:detalle', args=[self.admin.pk]), reverse('roles:lista'), reverse('roles:crear'),
            reverse('cuenta:perfil'),
            reverse('alumnos:lista') + '?q=zzzz', reverse('tutores:lista') + '?q=zzzz', reverse('inscripciones:lista') + '?q=zzzz',
            '/no-existe/',
        ]

    def revisar(self, urls):
        pendientes = []
        for url in urls:
            texto = texto_visible(self.client.get(url).content.decode())
            for hallazgo in PALABRA.finditer(texto):
                pendientes.append(f'{url}: …{contexto(texto, hallazgo)}…')
        self.assertEqual(pendientes, [], 'Pantallas que todavía dicen «alumno»')

    def test_con_datos(self):
        self.revisar(self.urls())

    def test_pantalla_de_entrada(self):
        """La pantalla de la entrada es una página aparte (sin menú)."""
        self.revisar([reverse('asistencias:kiosco')])

    def test_con_la_base_vacia(self):
        """Los estados vacíos («aún no hay…») también hablan de estudiantes."""
        TutorAlumno.objects.all().delete()
        HorarioMateria.objects.all().delete()
        MateriaGrado.objects.all().delete()
        Inscripcion.objects.all().delete()
        Alumno.objects.all().delete()
        Grado.objects.exclude(pk=self.primero.pk).delete()
        self.revisar([
            reverse('alumnos:lista'), reverse('tutores:lista'), reverse('inscripciones:lista'), reverse('inscripciones:promocion'),
            reverse('asistencias:inicio'), reverse('asistencias:dia'), reverse('asistencias:clases'),
            reverse('asistencias:justificaciones'), reverse('asistencias:reporte'), reverse('grados:detalle', args=[self.primero.pk]),
            reverse('materias:lista'), reverse('profesores:lista'),
        ])

    def test_los_mensajes_de_validacion_dicen_estudiante(self):
        pendientes = []
        casos = [
            ('post', reverse('inscripciones:crear'), {}),
            ('post', reverse('asistencias:justificacion_crear'), {}),
            ('post', reverse('alumnos:crear'), {}),
            ('post', reverse('tutores:crear'), {}),
        ]
        for metodo, url, datos in casos:
            texto = texto_visible(getattr(self.client, metodo)(url, datos).content.decode())
            pendientes += [f'{url}: {contexto(texto, h)}' for h in PALABRA.finditer(texto)]
        self.assertEqual(pendientes, [])

    def test_estudiante_si_aparece(self):
        texto = texto_visible(self.client.get(reverse('alumnos:lista')).content.decode())
        self.assertIn('Estudiantes', texto)
        self.assertIn('Nuevo estudiante', texto)
        self.assertIn('Estudiantes', texto_visible(self.client.get(reverse('inicio')).content.decode()))

    def test_el_menu_y_los_roles_hablan_de_estudiantes(self):
        menu = texto_visible(self.client.get(reverse('inicio')).content.decode())
        self.assertIn('Estudiantes', menu)
        matriz = texto_visible(self.client.get(reverse('roles:crear')).content.decode())
        self.assertIn('Estudiantes', matriz)
        self.assertNotRegex(matriz, PALABRA)

    def test_las_exportaciones_dicen_estudiante(self):
        respuesta = self.client.get(reverse('alumnos:exportar'))
        self.assertIn('filename="estudiantes-', respuesta['Content-Disposition'])
        filas = list(csv.reader(io.StringIO(respuesta.content.decode('utf-8').lstrip('﻿'))))
        self.assertIn('Parentesco del tutor', filas[0])
        for fila in filas:
            for celda in fila:
                self.assertNotRegex(celda, PALABRA)


@PRUEBAS
class TextosDelCodigoTests(BaseTestCase):
    def test_los_scripts_no_muestran_la_palabra_alumno(self):
        """Cadenas de los .js que son frases (las claves, clases y selectores conservan su nombre)."""
        pendientes = []
        for archivo in sorted((RAIZ / 'static/js').glob('*.js')):
            for n, linea in enumerate(archivo.read_text(encoding='utf-8').splitlines(), 1):
                if linea.strip().startswith(('//', '*', '/*')):
                    continue
                for literal in re.findall(r"""'([^'\\]*(?:\\.[^'\\]*)*)'|"([^"\\]*(?:\\.[^"\\]*)*)"|`([^`]*)`""", linea):
                    texto = re.sub(r'\$\{.*?\}', '', next((x for x in literal if x), ''))   # sin las expresiones ${...}
                    if re.search(r'\s', texto) and re.search(r'(?<![\w\-./#\[$])alumn[oa]s?(?![\w\-/=\]])', texto, re.I) and not re.search(r'[\[\]=/#<>_]', texto):
                        pendientes.append(f'{archivo.name}:{n}: {texto[:80]}')
        self.assertEqual(pendientes, [])

    def test_los_nombres_de_modelos_y_campos_se_muestran_como_estudiante(self):
        from Alumnos.models import Inscripcion, TutorAlumno
        self.assertEqual(Alumno._meta.verbose_name, 'Estudiante')
        self.assertEqual(Alumno._meta.verbose_name_plural, 'Estudiantes')
        self.assertEqual(Inscripcion._meta.get_field('alumno').verbose_name, 'Estudiante')
        self.assertEqual(TutorAlumno._meta.get_field('alumno').verbose_name, 'Estudiante')
        self.assertEqual(TutorAlumno._meta.verbose_name, 'Tutor del estudiante')
        self.assertEqual(TutorAlumno._meta.get_field('autorizado_recoger').verbose_name, 'Autorizado para recoger al estudiante')

    def test_el_nombre_de_la_app_y_las_rutas_no_cambian(self):
        """Solo cambia lo que se lee: las URLs, los permisos y la app siguen llamándose Alumnos."""
        from django.apps import apps
        self.assertEqual(apps.get_app_config('Alumnos').name, 'Alumnos')
        self.assertEqual(str(apps.get_app_config('Alumnos').verbose_name), 'Estudiantes')
        self.assertEqual(reverse('alumnos:lista'), '/alumnos/')
        self.assertTrue(self.admin.has_perm('Alumnos.view_alumno'))
