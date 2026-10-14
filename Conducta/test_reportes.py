"""Reportes de conducta: mismos filtros y conteos en la pantalla, la hoja para imprimir o PDF y el Excel; periodo y
rango que se cruzan; incidentes contados una sola vez aunque tengan varias medidas."""
import io
import re
import zipfile
from datetime import timedelta
from xml.etree import ElementTree

from django.test import override_settings
from django.urls import reverse

from CISAHUAYO.pruebas import PRUEBAS, hoy

from .models import POSITIVA, Suspension
from .pruebas import CARPETA, BaseConductaTestCase, borrar_carpeta

URL = reverse('conducta:reportes')
NS = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def tearDownModule():
    borrar_carpeta()


def filas_de_excel(contenido, hoja=1):
    """Las filas de una hoja del .xlsx como listas de textos."""
    with zipfile.ZipFile(io.BytesIO(contenido)) as libro:
        raiz = ElementTree.fromstring(libro.read(f'xl/worksheets/sheet{hoja}.xml'))
    filas = []
    for fila in raiz.iterfind('.//x:row', NS):
        valores = []
        for celda in fila.iterfind('x:c', NS):
            texto = celda.find('.//x:t', NS)
            numero = celda.find('x:v', NS)
            valores.append(texto.text if texto is not None else (numero.text if numero is not None else ''))
        filas.append(valores)
    return filas


def valor(filas, etiqueta):
    return next(fila[1] for fila in filas if fila and fila[0] == etiqueta)


@PRUEBAS
@override_settings(MEDIA_ROOT=CARPETA)
class ReportesTests(BaseConductaTestCase):
    def setUp(self):
        super().setUp()
        # Ana: dos incidencias (una con dos medidas) y una positiva; Zoe (secundaria): una incidencia
        self.registrar(medidas=[self.amonestacion.pk, self.compromiso.pk], responsable=self.admin.pk, fecha_revision=hoy().isoformat())
        self.registrar(motivo=self.empujon.pk, fecha=(hoy() - timedelta(days=2)).isoformat())
        self.registrar(tipo=POSITIVA, categoria=self.reconocimiento.pk, motivo=self.ayuda.pk, estado='CERRADO', observaciones_cierre='Reconocido frente al grupo.')
        self.registrar(alumno=self.otro.pk, categoria=self.convivencia_sec.pk, motivo=self.agresion_sec.pk)
        # Una anulada que no debe contar
        self.registrar(motivo=self.empujon.pk)
        self.client.post(reverse('conducta:anular', args=[self.ultimo().pk]), {'motivo': 'Registro duplicado por error.'})

    def test_resumen_cuenta_incidentes_y_estudiantes_por_separado(self):
        resumen = self.client.get(URL, {'reporte': 'resumen'}).context['contenido']['resumen']
        self.assertEqual((resumen['incidencias'], resumen['positivas'], resumen['estudiantes'], resumen['estudiantes_con_incidencias']), (3, 1, 2, 2))
        self.assertEqual(resumen['registros_con_medidas'], 1)    # dos medidas, un solo incidente
        self.assertEqual(dict(resumen['medidas']), {'Amonestación verbal': 1, 'Compromiso escrito': 1})
        motivos = dict(resumen['motivos'])   # cada nivel tiene su catálogo: con varios niveles, el nombre lleva el suyo
        self.assertEqual((motivos['Agresión verbal · Primaria'], motivos['Agresión verbal · Secundaria'], motivos['Empujones · Primaria']), (1, 1, 1))
        solo_primaria = self.client.get(URL, {'reporte': 'resumen', 'nivel': 'PRIMARIA'}).context['contenido']['resumen']
        self.assertEqual(dict(solo_primaria['motivos']), {'Agresión verbal': 1, 'Empujones': 1, 'Ayuda a compañeros': 1})
        self.assertEqual(sum(e['incidencias'] for e in resumen['evolucion']), 3)
        # Con los anulados, sí cuenta
        todos = self.client.get(URL, {'reporte': 'resumen', 'registros': 'todos'}).context['contenido']['resumen']
        self.assertEqual(todos['incidencias'], 4)

    def test_el_excel_coincide_con_la_pantalla(self):
        filtros = {'reporte': 'resumen', 'nivel': 'PRIMARIA'}
        resumen = self.client.get(URL, filtros).context['contenido']['resumen']
        respuesta = self.client.get(reverse('conducta:reporte_excel'), filtros)
        self.assertEqual(respuesta['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertIn('attachment; filename="conducta-resumen-estadistico-', respuesta['Content-Disposition'])
        filas = filas_de_excel(respuesta.content)
        self.assertEqual(filas[0], ['Colegio Interamericano de Sahuayo'])
        self.assertEqual(valor(filas, 'Generado por'), 'admin')
        self.assertEqual(valor(filas, 'Filtro: Nivel'), 'Primaria')
        self.assertEqual(int(valor(filas, 'Incidencias (incidentes)')), resumen['incidencias'])
        self.assertEqual(int(valor(filas, 'Conductas positivas')), resumen['positivas'])
        self.assertEqual(int(valor(filas, 'Estudiantes con registros')), resumen['estudiantes'])

    def test_reporte_por_grupo_y_su_excel(self):
        contenido = self.client.get(URL, {'reporte': 'grupo', 'grupo': self.inscripcion.grupo_id}).context['contenido']
        self.assertEqual(len(contenido['registros']), 3)
        self.assertEqual(dict(contenido['totales']['categorias']), {'Convivencia': 2, 'Reconocimientos': 1})
        filas = filas_de_excel(self.client.get(reverse('conducta:reporte_excel'), {'reporte': 'grupo', 'grupo': self.inscripcion.grupo_id}).content)
        renglones = [f for f in filas if f and f[0] and re.match(r'\d\d/\d\d/\d{4}$', f[0])]
        self.assertEqual(len(renglones), 3)

    def test_periodo_y_rango_se_cruzan(self):
        dentro = {'reporte': 'grupo', 'periodo': self.periodo.pk, 'desde': (hoy() - timedelta(days=1)).isoformat()}
        contenido = self.client.get(URL, dentro).context['contenido']
        self.assertEqual(len(contenido['registros']), 2)          # el de hace dos días queda fuera del rango
        self.assertTrue(all(r.nivel == 'PRIMARIA' for r in contenido['registros']))   # el periodo es de primaria
        fuera = {'reporte': 'grupo', 'periodo': self.periodo.pk, 'desde': (self.periodo.fecha_fin + timedelta(days=5)).isoformat()}
        contenido = self.client.get(URL, fuera).context['contenido']
        self.assertIn('no coincide con las fechas del periodo', contenido['aviso'])
        self.assertEqual(contenido['registros'], [])

    def test_historial_individual(self):
        contenido = self.client.get(URL, {'reporte': 'historial'}).context['contenido']
        self.assertTrue(contenido['sin_estudiantes'])
        contenido = self.client.get(URL, {'reporte': 'historial', 'alumnos': [self.alumno.pk, self.otro.pk]}).context['contenido']
        ana, zoe = contenido['historiales']
        self.assertEqual((ana['incidencias'], ana['positivas'], zoe['incidencias']), (2, 1, 1))
        self.assertEqual([r.fecha for r in ana['registros']], sorted(r.fecha for r in ana['registros']))

    def test_reporte_de_suspensiones_con_su_estado(self):
        self.registrar(medidas=[self.suspender.pk], suspension_motivo=self.motivo_suspension.pk, suspension_inicio=hoy().isoformat(),
                       suspension_fin=(hoy() + timedelta(days=1)).isoformat(), suspension_autoriza=self.admin.pk)
        contenido = self.client.get(URL, {'reporte': 'suspensiones'}).context['contenido']
        self.assertEqual([(f['registro'].alumno, f['estado']) for f in contenido['suspensiones']], [(self.alumno, Suspension.VIGENTE)])
        self.assertEqual(self.client.get(URL, {'reporte': 'resumen', 'suspension': 'sin'}).context['contenido']['resumen']['suspensiones'], 0)

    def test_la_hoja_para_imprimir_lleva_encabezado_filtros_y_quien(self):
        respuesta = self.client.get(reverse('conducta:reporte_imprimir'), {'reporte': 'resumen', 'tipo': 'INCIDENCIA', 'pdf': '1'})
        for texto in ('Colegio Interamericano de Sahuayo', 'Reporte de conducta · Resumen estadístico', 'Generado por', 'Incidencia', '@page { size: A4 landscape'):
            self.assertContains(respuesta, texto)
        self.assertContains(respuesta, 'data-imprimir-al-abrir')
        self.assertEqual(respuesta.context['contenido']['resumen']['positivas'], 0)
        self.assertNotIn('pdf=1', respuesta.context['volver'])
        # Los botones de la vista previa llevan los mismos filtros
        vista = self.client.get(URL, {'reporte': 'resumen', 'tipo': 'INCIDENCIA'})
        self.assertIn('tipo=INCIDENCIA', vista.context['url_excel'])
        self.assertIn('tipo=INCIDENCIA', vista.context['url_pdf'])

    def test_sin_ciclo_en_la_direccion_el_selector_muestra_el_actual(self):
        # Llegar con otros filtros (p. ej. solo el tipo de reporte) aplica el ciclo actual y el selector lo dice
        respuesta = self.client.get(URL, {'reporte': 'suspensiones'})
        self.assertEqual(respuesta.context['filtro']['ciclo'].value(), str(self.ciclo.pk))
        self.assertEqual(respuesta.context['filtro'].filtro().ciclo, self.ciclo)
        # «Todos los ciclos» (ciclo vacío) se respeta
        self.assertIsNone(self.client.get(URL, {'reporte': 'suspensiones', 'ciclo': ''}).context['filtro'].filtro().ciclo)

    def test_sin_permiso_no_hay_reportes(self):
        self.client.force_login(self.sin_permisos)
        for nombre in ('conducta:reportes', 'conducta:reporte_imprimir', 'conducta:reporte_excel'):
            self.assertEqual(self.client.get(reverse(nombre)).status_code, 403, nombre)
