"""Todos los formularios del proyecto usan el estilo del sistema de diseño.

Un formulario que hereda de EstiloCamposMixin pero no llama a `aplicar_estilo()` en su `__init__` se ve «crudo»
(sin la clase .field__control); este fue exactamente el fallo del formulario de materias.
"""
import importlib
import inspect

from django import forms
from django.test import SimpleTestCase

from Alumnos.forms import EstiloCamposMixin

MODULOS = (
    'Alumnos.forms', 'Tutores.forms', 'Ciclos.forms', 'Grados.forms',
    'Inscripciones.forms', 'Materias.forms', 'Horarios.forms', 'Profesores.forms',
)


def formularios_con_estilo():
    for modulo in MODULOS:
        try:
            importlib.import_module(modulo)
        except ModuleNotFoundError:   # una sección que todavía no existe
            continue
    pendientes, vistos = list(EstiloCamposMixin.__subclasses__()), []
    while pendientes:
        clase = pendientes.pop()
        vistos.append(clase)
        pendientes.extend(clase.__subclasses__())
    return [c for c in vistos if c.__module__.split('.')[0] != 'CISAHUAYO' or c.__module__.endswith('forms')]


class EstiloDeFormulariosTests(SimpleTestCase):
    def test_hay_formularios_de_todas_las_secciones(self):
        modulos = {c.__module__ for c in formularios_con_estilo()}
        for esperado in ('Alumnos.forms', 'Tutores.forms', 'Ciclos.forms', 'Grados.forms', 'Inscripciones.forms', 'Materias.forms', 'Horarios.forms'):
            self.assertIn(esperado, modulos)

    def test_todos_llaman_a_aplicar_estilo_en_su_constructor(self):
        sin_estilo = []
        for clase in formularios_con_estilo():
            constructor = clase.__dict__.get('__init__')
            if constructor is None or 'aplicar_estilo' not in inspect.getsource(constructor):
                sin_estilo.append(f'{clase.__module__}.{clase.__name__}')
        self.assertEqual(sin_estilo, [], 'Estos formularios no aplican el estilo del sistema de diseño')

    def test_el_formulario_de_materias_lleva_la_clase_de_los_campos(self):
        from Materias.forms import MateriaForm
        form = MateriaForm()
        for campo in ('clave', 'nombre'):
            self.assertIn('field__control', form[campo].field.widget.attrs['class'], campo)
        self.assertIn('class="field__control', str(form['nombre']))

    def test_el_mixin_respeta_casillas_y_archivos(self):
        class Ejemplo(EstiloCamposMixin, forms.Form):
            texto = forms.CharField()
            opcion = forms.ChoiceField(choices=[('a', 'A')])
            marca = forms.BooleanField()

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.aplicar_estilo()

        form = Ejemplo()
        self.assertIn('field__control', form['texto'].field.widget.attrs['class'])
        self.assertIn('field__control--select', form['opcion'].field.widget.attrs['class'])
        self.assertNotIn('class', form['marca'].field.widget.attrs)
