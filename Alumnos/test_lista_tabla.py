"""La tabla de estudiantes: se ordena desde sus encabezados (Estudiante, Grado actual y Edad), muestra la equivalencia
del grado en la continuidad escolar, la asistencia de hoy (solo con permiso de consultarla) y, junto al nombre, solo las
señales que aplican (requiere atención en el panel de control, retiro anticipado de hoy, reunión próxima con la
familia, alergias, CURP que falta o no es válida y sin fotografía)."""
import csv
import io
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from unittest.mock import patch

from django.utils import timezone

from django.urls import reverse

from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase, ciclo_actual_de_prueba, crear_alumno, crear_grado, crear_rol, crear_usuario, grupo_de, inscribir

from . import importacion, tabla
from .models import Alumno, AsistenciaGeneral, DiaNoLectivo

LISTA = reverse('alumnos:lista')
CURP_VALIDA = 'GOMA150505HMNRRN09'


@dataclass
class AlertaDePrueba:
    alumno: object
    prioridad: str = 'alta'
    texto_de_prioridad: str = 'Alta'
    motivos: list = field(default_factory=lambda: [('inasistencia', '4 faltas seguidas'), ('rendimiento', 'Reprueba 2 materias')])


@PRUEBAS
class TablaDeEstudiantesTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        ciclo = ciclo_actual_de_prueba()
        self.preescolar = crear_grado('PREESCOLAR', 2, equivalencia='K2')
        self.secundaria = crear_grado('SECUNDARIA', 1, equivalencia='7')
        self.primaria = crear_grado('PRIMARIA', 3)                     # sin equivalencia guardada: se usa la habitual
        self.ana = crear_alumno(nombre='Ana', apellido_paterno='Zamora', fecha_nacimiento=date(2010, 1, 1), curp=CURP_VALIDA,
                                fotografia='alumnos/ana.png')   # solo la ruta: no se escribe ningún archivo
        self.beto = crear_alumno(nombre='Beto', apellido_paterno='Alba', fecha_nacimiento=date(2018, 1, 1), alergias='Penicilina')
        self.ciro = crear_alumno(nombre='Ciro', apellido_paterno='Mora', fecha_nacimiento=date(2014, 6, 1))
        self.dora = crear_alumno(nombre='Dora', apellido_paterno='Luna', fecha_nacimiento=date(2012, 6, 1))   # sin inscripción
        self.insc_ana = inscribir(self.ana, ciclo, self.secundaria, grupo=grupo_de(self.secundaria))
        self.insc_beto = inscribir(self.beto, ciclo, self.preescolar, grupo=grupo_de(self.preescolar))
        self.insc_ciro = inscribir(self.ciro, ciclo, self.primaria, grupo=grupo_de(self.primaria))

    def apellidos(self, **parametros):
        return [a.apellido_paterno for a in self.client.get(LISTA, parametros).context['pagina']]

    def test_ordena_por_grado_en_orden_escolar_y_sin_inscripcion_al_final(self):
        self.assertEqual(self.apellidos(orden='grado'), ['Alba', 'Mora', 'Zamora', 'Luna'])
        self.assertEqual(self.apellidos(orden='-grado'), ['Zamora', 'Mora', 'Alba', 'Luna'])

    def test_ordena_por_edad(self):
        self.assertEqual(self.apellidos(orden='edad'), ['Alba', 'Mora', 'Luna', 'Zamora'])     # de menor a mayor
        self.assertEqual(self.apellidos(orden='-edad'), ['Zamora', 'Luna', 'Mora', 'Alba'])

    def test_los_encabezados_ordenan_y_alternan_el_sentido(self):
        respuesta = self.client.get(LISTA)
        self.assertContains(respuesta, 'class="filters__field alumnos-orden-movil"')   # el selector, solo en el teléfono
        self.assertContains(respuesta, 'aria-sort="ascending"')
        self.assertContains(respuesta, 'href="?orden=-nombre"')
        self.assertContains(respuesta, 'href="?orden=grado"')
        self.assertContains(respuesta, 'href="?orden=edad"')
        por_grado = self.client.get(LISTA, {'orden': 'grado', 'q': 'a'})
        self.assertContains(por_grado, 'orden=-grado')
        self.assertContains(por_grado, '<option value="grado" selected>')                    # al filtrar se conserva
        self.assertEqual(por_grado.context['columnas']['grado']['aria'], 'ascending')
        self.assertEqual(por_grado.context['columnas']['nombre']['siguiente'], None)          # volver al orden de siempre

    def test_muestra_la_equivalencia_del_grado(self):
        respuesta = self.client.get(LISTA)
        self.assertContains(respuesta, '>7° A</span>')
        self.assertContains(respuesta, '>K2 A</span>')
        self.assertContains(respuesta, '>3° A</span>')                         # 3° de primaria: la habitual
        self.assertContains(respuesta, 'data-tooltip="1° A Secundaria"')       # el grado de su nivel, al pasar el cursor

    def test_senales_solo_las_que_aplican(self):
        filas = {a.apellido_paterno: [s['clave'] for s in a.senales] for a in self.client.get(LISTA).context['pagina']}
        self.assertEqual(filas['Zamora'], [])                                   # CURP válida, con foto, sin alergias
        self.assertEqual(filas['Alba'], ['salud', 'curp', 'foto'])
        self.assertEqual(filas['Mora'], ['curp', 'foto'])
        self.assertContains(self.client.get(LISTA), 'Alergias: Penicilina')

    def test_senal_de_requiere_atencion_del_panel(self):
        with patch('Panel.seguimiento.alertas', return_value=[AlertaDePrueba(alumno=self.ana)]):
            respuesta = self.client.get(LISTA)
        ana = next(a for a in respuesta.context['pagina'] if a.pk == self.ana.pk)
        self.assertEqual([s['clave'] for s in ana.senales], ['atencion'])
        self.assertContains(respuesta, 'Requiere atención (prioridad alta): 4 faltas seguidas · Reprueba 2 materias')

    def test_sin_permiso_de_asistencia_ni_calificaciones_no_se_consultan_las_alertas(self):
        self.client.force_login(crear_usuario('consulta', crear_rol('Solo estudiantes', {'Alumnos.view_alumno'})))
        with patch('Panel.seguimiento.alertas') as alertas:
            respuesta = self.client.get(LISTA)
        alertas.assert_not_called()
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(len(respuesta.context['pagina']), Alumno.objects.count())

    # --- Asistencia de hoy -----------------------------------------------------------------------------------------
    def test_asistencia_de_hoy(self):
        hoy = timezone.localdate()
        AsistenciaGeneral.objects.create(inscripcion=self.insc_ana, fecha=hoy, estado='PRESENTE', hora_entrada=time(7, 52))
        AsistenciaGeneral.objects.create(inscripcion=self.insc_beto, fecha=hoy, estado='RETARDO', hora_entrada=time(8, 10))
        DiaNoLectivo.objects.create(fecha=hoy, nivel='PRIMARIA', motivo='Consejo técnico')
        respuesta = self.client.get(LISTA)
        datos = {a.apellido_paterno: a.asistencia_hoy['texto'] for a in respuesta.context['pagina']}
        self.assertEqual(datos, {'Zamora': 'Llegó 7:52', 'Alba': 'Retardo 8:10', 'Mora': 'Sin clases', 'Luna': '—'})
        self.assertContains(respuesta, 'Asistencia hoy')
        self.assertContains(respuesta, 'data-tooltip="Consejo técnico"')
        AsistenciaGeneral.objects.filter(inscripcion=self.insc_beto).update(estado='FALTA', hora_entrada=None)
        DiaNoLectivo.objects.all().delete()
        datos = {a.apellido_paterno: a.asistencia_hoy['texto'] for a in self.client.get(LISTA).context['pagina']}
        self.assertEqual((datos['Alba'], datos['Mora']), ('Falta', 'Sin registro'))

    def test_la_asistencia_solo_con_permiso_de_consultarla(self):
        self.client.force_login(crear_usuario('consulta', crear_rol('Solo estudiantes', {'Alumnos.view_alumno'})))
        respuesta = self.client.get(LISTA)
        self.assertNotContains(respuesta, 'Asistencia hoy')
        self.assertTrue(all(a.asistencia_hoy is None for a in respuesta.context['pagina']))

    def test_las_consultas_no_crecen_con_las_filas(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        for i in range(12):
            alumno = crear_alumno(nombre=f'Relleno{i}', apellido_paterno='Relleno', alergias='Polen')
            inscribir(alumno, self.insc_ana.ciclo, self.secundaria, grupo=grupo_de(self.secundaria))
        with CaptureQueriesContext(connection) as pocas:
            self.client.get(LISTA, {'por_pagina': 10})
        with CaptureQueriesContext(connection) as muchas:
            self.client.get(LISTA, {'por_pagina': 50})
        self.assertLessEqual(len(muchas), len(pocas))

    # --- Retiro de hoy y reunión próxima ----------------------------------------------------------------------------
    def test_senales_de_retiro_y_reunion(self):
        from Retiros.models import AvisoRetiro, RetiroEstudiante
        from Reuniones.models import Reunion
        hoy = date(2026, 10, 19)   # lunes
        retiro = RetiroEstudiante(estado=RetiroEstudiante.AVISADO, aviso=AvisoRetiro(pk=5, hora=time(12, 0)))
        reunion = Reunion(pk=9, fecha=hoy + timedelta(days=3), hora_inicio=time(10, 0), hora_fin=time(10, 30), estado=Reunion.CONFIRMADA)
        senales = tabla.senales_de(self.ana, hoy, retiro=retiro, reunion=reunion)
        self.assertEqual([s['clave'] for s in senales], ['retiro', 'reunion'])
        self.assertEqual(senales[0]['texto'], 'Sale hoy a las 12:00 (retiro anticipado avisado por su tutor)')
        self.assertEqual(senales[0]['url'], reverse('retiros:detalle', args=[5]))
        self.assertEqual(senales[1]['texto'], 'Reunión con la familia el jueves 22 a las 10:00')
        self.assertEqual(senales[1]['url'], reverse('reuniones:detalle', args=[9]))
        reunion.fecha, reunion.estado = hoy + timedelta(days=1), Reunion.PROGRAMADA
        self.assertEqual(tabla.senales_de(self.ana, hoy, reunion=reunion)[0]['texto'], 'Reunión con la familia mañana a las 10:00 (por confirmar)')
        retiro.estado = RetiroEstudiante.RETIRADO
        retiro.salida_en = timezone.make_aware(timezone.datetime(2026, 10, 19, 12, 5))
        self.assertEqual(tabla.senales_de(self.ana, hoy, retiro=retiro)[0]['texto'], 'Salió hoy a las 12:05 (retiro anticipado)')

    def test_retiros_y_reuniones_solo_con_su_permiso(self):
        consulta = crear_usuario('consulta', crear_rol('Solo estudiantes', {'Alumnos.view_alumno'}))
        hoy = timezone.localdate()
        self.assertEqual(tabla.retiros_de_hoy(consulta, [self.ana], hoy), {})
        self.assertEqual(tabla.reuniones_proximas(consulta, [self.ana], hoy), {})

    # --- La equivalencia en la fila, en el filtro y en la exportación ------------------------------------------------
    def test_el_ciclo_no_se_repite_en_cada_fila(self):
        respuesta = self.client.get(LISTA)
        self.assertContains(respuesta, self.insc_ana.ciclo.nombre, count=1)   # solo en el encabezado de la página

    def test_el_filtro_de_grados_usa_la_equivalencia(self):
        html = self.client.get(LISTA).content.decode()
        self.assertIn(f'<option value="{self.secundaria.pk}">7°</option>', html)
        self.assertIn(f'<option value="{self.preescolar.pk}">K2</option>', html)
        self.assertIn(f'<option value="{self.primaria.pk}">3°</option>', html)   # sin equivalencia guardada: la habitual
        self.assertIn('<optgroup label="Secundaria">', html)                      # siguen agrupados por nivel
        self.assertEqual(self.apellidos(grado=self.secundaria.pk), ['Zamora'])

    def test_la_exportacion_usa_la_equivalencia(self):
        contenido = self.client.get(reverse('alumnos:exportar')).content.decode('utf-8').lstrip('\ufeff')
        filas = list(csv.DictReader(io.StringIO(contenido)))
        grados = {fila['Apellido paterno']: fila['Grado'] for fila in filas}
        self.assertEqual(grados, {'Zamora': '7° A', 'Alba': 'K2 A', 'Mora': '3° A', 'Luna': ''})

    def test_la_importacion_reconoce_el_grado_exportado(self):
        grados = importacion._Grados()
        self.assertEqual(grados.buscar('7° A'), grupo_de(self.secundaria))
        self.assertEqual(grados.buscar('K2 A'), grupo_de(self.preescolar))
        self.assertEqual(grados.buscar('3° A'), grupo_de(self.primaria))
        self.assertEqual(grados.buscar('1° A Secundaria'), grupo_de(self.secundaria))   # lo de siempre sigue valiendo
        self.assertEqual(grados.buscar('7'), grupo_de(self.secundaria))
