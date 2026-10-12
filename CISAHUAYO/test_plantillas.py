"""Revisiones de todas las plantillas que evitan errores que solo se notan al ver la página."""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

PLANTILLAS = Path(settings.BASE_DIR) / 'templates'


class ComentariosTests(SimpleTestCase):
    def test_los_comentarios_cortos_caben_en_una_linea(self):
        """Django solo reconoce {# … #} dentro de una misma línea: partido en dos, se muestra como texto en la página
        (pasó en asistencias/docente.html). Los comentarios largos van en {% comment %}."""
        partidos = []
        for plantilla in sorted(PLANTILLAS.rglob('*.html')):
            for numero, linea in enumerate(plantilla.read_text(encoding='utf-8').splitlines(), start=1):
                if linea.count('{#') > linea.count('#}'):
                    partidos.append(f'{plantilla.relative_to(PLANTILLAS)}:{numero}')
        self.assertEqual(partidos, [])


class ListasDesplegablesTests(SimpleTestCase):
    def test_todas_las_listas_llevan_el_estilo_del_sistema(self):
        """Las listas escritas a mano en las plantillas llevan field__control--select: así se ven modernas (la lista
        abierta también, con appearance: base-select, en app.css). Las de los formularios la reciben de
        EstiloCamposMixin."""
        sin_estilo, revisadas = [], 0
        for plantilla in sorted(PLANTILLAS.rglob('*.html')):
            for etiqueta in re.findall(r'<select\b[^>]*>', plantilla.read_text(encoding='utf-8')):
                revisadas += 1
                if 'field__control--select' not in etiqueta:
                    sin_estilo.append(f'{plantilla.relative_to(PLANTILLAS)}: {etiqueta}')
        self.assertGreater(revisadas, 10)   # que de verdad las encuentre
        self.assertEqual(sin_estilo, [])
