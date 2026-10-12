"""Listas, fechas y horas de todo el sitio usan los controles modernos del sistema.

Recorre todas las páginas que se abren con GET (como administrador y con algunos datos, para que las de detalle existan)
y revisa el HTML que llega al navegador:
- cada lista (<select>, salvo las de selección múltiple) lleva field__control--select: se ve como las demás y se abre
  con el diseño del sistema (appearance: base-select en static/css/app.css);
- los campos de fecha y de hora siguen siendo <input type="date"> / type="time" (sin JavaScript se ve el del navegador)
  y la página carga static/js/fecha.js y static/js/hora.js, que los convierten en los selectores del sistema.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse

from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    crear_alumno,
    crear_grado,
    crear_profesor,
    crear_tutor,
    inscribir,
    materia_en_grado,
    vincular,
)
from Usuarios.test_rutas import SIN_SESION, rutas

ESTATICOS = Path(settings.BASE_DIR) / 'static'
PLANTILLAS = Path(settings.BASE_DIR) / 'templates'
ETIQUETA_SELECT = re.compile(r'<select\b[^>]*>')
CAMPO_FECHA = re.compile(r'<input\b[^>]*\btype="date"')
CAMPO_HORA = re.compile(r'<input\b[^>]*\btype="time"')


@PRUEBAS
class ControlesDeTodasLasPaginasTests(BaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        ciclo = ciclo_actual_de_prueba()
        grado = crear_grado('PRIMARIA', 1)
        alumno = crear_alumno()
        inscribir(alumno, ciclo, grado)
        vincular(crear_tutor(), alumno)
        crear_profesor()
        materia_en_grado('MAT', grado, ciclo)

    def paginas(self):
        """(url, html) de cada página que responde a GET con HTML."""
        for nombre, _, _, argumentos in rutas():
            if nombre in SIN_SESION:
                continue
            url = reverse(nombre, kwargs=argumentos)
            respuesta = self.client.get(url)
            if respuesta.status_code == 200 and 'text/html' in respuesta.get('Content-Type', ''):
                yield url, respuesta.content.decode()

    def test_listas_fechas_y_horas_con_los_controles_del_sistema(self):
        listas_sin_estilo, sin_selector_de_fecha, sin_selector_de_hora = [], [], []
        cuentas = {'paginas': 0, 'listas': 0, 'fechas': 0, 'horas': 0}
        for url, html in self.paginas():
            cuentas['paginas'] += 1
            for etiqueta in ETIQUETA_SELECT.findall(html):
                if re.search(r'\bmultiple\b', etiqueta):
                    continue
                cuentas['listas'] += 1
                if 'field__control--select' not in etiqueta:
                    listas_sin_estilo.append(f'{url}: {etiqueta}')
            if CAMPO_FECHA.search(html):
                cuentas['fechas'] += 1
                if 'js/fecha.js' not in html:
                    sin_selector_de_fecha.append(url)
            if CAMPO_HORA.search(html):
                cuentas['horas'] += 1
                if 'js/hora.js' not in html:
                    sin_selector_de_hora.append(url)
        # Que de verdad recorra el sitio (y no pase en vacío)
        self.assertGreater(cuentas['paginas'], 60)
        self.assertGreater(cuentas['listas'], 40)
        self.assertGreater(cuentas['fechas'], 8)
        self.assertGreater(cuentas['horas'], 2)
        self.assertEqual(listas_sin_estilo, [])
        self.assertEqual(sin_selector_de_fecha, [])
        self.assertEqual(sin_selector_de_hora, [])


class SelectoresEnLaBaseTests(SimpleTestCase):
    """Los selectores de fecha y de hora van en la plantilla base y se mejoran solos los campos que llegan después
    (formularios en ventana): modal-form.js no debe volver a ejecutarlos ni las plantillas incluirlos otra vez."""

    def test_la_base_carga_los_selectores_despues_de_app_js(self):
        base = (PLANTILLAS / 'base.html').read_text(encoding='utf-8')
        app, fecha, hora = (base.index(f"js/{nombre}.js") for nombre in ('app', 'fecha', 'hora'))
        self.assertLess(app, fecha)          # usan window.CISAHUAYO.pickers, que define app.js
        self.assertLess(app, hora)

    def test_las_ventanas_no_los_vuelven_a_ejecutar(self):
        modal = (ESTATICOS / 'js' / 'modal-form.js').read_text(encoding='utf-8')
        linea = next(linea for linea in modal.splitlines() if 'const DE_LA_BASE' in linea)
        for nombre in ('app.js', 'fecha.js', 'hora.js'):
            self.assertIn(f"'{nombre}'", linea)

    def test_ninguna_otra_plantilla_los_incluye(self):
        repetidos = [
            str(plantilla.relative_to(PLANTILLAS))
            for plantilla in PLANTILLAS.rglob('*.html')
            if plantilla.name != 'base.html' and re.search(r"js/(fecha|hora)\.js", plantilla.read_text(encoding='utf-8'))
        ]
        self.assertEqual(repetidos, [])

    def test_los_selectores_se_apoyan_en_la_base_compartida(self):
        app = (ESTATICOS / 'js' / 'app.js').read_text(encoding='utf-8')
        self.assertIn('pickers', app.split('window.CISAHUAYO = Object.freeze(')[1].split(')')[0])
        for nombre, tipo in (('fecha', 'date'), ('hora', 'time')):
            codigo = (ESTATICOS / 'js' / f'{nombre}.js').read_text(encoding='utf-8')
            self.assertIn(f'input[type="{tipo}"]', codigo)
            self.assertIn('base.watch(', codigo)
            self.assertIn('base.field(', codigo)
        # El de una fecha deja los rangos al calendario de rango
        self.assertIn("closest('[data-rango-fechas]')", (ESTATICOS / 'js' / 'fecha.js').read_text(encoding='utf-8'))
