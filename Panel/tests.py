"""Panel de control: que sus cifras coincidan con las de cada módulo y respeten sus reglas (sin registro no es falta,
pendiente no es cero, no se mezclan escalas ni se cuenta dos veces a un estudiante), los filtros y su memoria, las
alertas de seguimiento con sus criterios por nivel, los retiros (avisos y estudiantes aparte) y los permisos."""
from datetime import time, timedelta
from decimal import Decimal

from django.urls import reverse

from Alumnos.asistencias import resumen_del_dia
from Alumnos.models import AsistenciaGeneral, Justificacion, Periodo
from Calificaciones.models import ActaCalificaciones
from CISAHUAYO.pruebas import (
    PRUEBAS, BaseTestCase, ciclo_actual_de_prueba, crear_alumno, crear_grado, crear_rol, crear_tutor, crear_usuario, hoy,
    inscribir_antes, lunes, materia_en_grado,
)

from . import academico, indicadores, seguimiento
from .filtros import filtros_de
from .models import CriterioSeguimiento

INICIO = reverse('inicio')


class Colegio:
    """Primaria (2.º) con Ana, Beto y Caro, y secundaria (1.º) con Zoe. Primaria tiene un periodo terminado (P1) y el
    actual (P2, que ya tiene actas cerradas); MAT y ESP en las dos, CIE en captura y una materia con otra escala."""

    def armar(self):
        self.ciclo = ciclo_actual_de_prueba()
        self.primaria = crear_grado('PRIMARIA', 2)
        self.secundaria = crear_grado('SECUNDARIA', 1)
        self.ana = inscribir_antes(crear_alumno(nombre='Ana'), self.ciclo, self.primaria)
        self.beto = inscribir_antes(crear_alumno(nombre='Beto'), self.ciclo, self.primaria)
        self.caro = inscribir_antes(crear_alumno(nombre='Caro'), self.ciclo, self.primaria)
        self.zoe = inscribir_antes(crear_alumno(nombre='Zoe'), self.ciclo, self.secundaria)
        self.p1 = Periodo.objects.create(ciclo=self.ciclo, nivel='PRIMARIA', nombre='P1', fecha_inicio=hoy() - timedelta(days=50), fecha_fin=hoy() - timedelta(days=21))
        self.p2 = Periodo.objects.create(ciclo=self.ciclo, nivel='PRIMARIA', nombre='P2', fecha_inicio=hoy() - timedelta(days=20), fecha_fin=hoy() + timedelta(days=40))
        Periodo.objects.create(ciclo=self.ciclo, nivel='SECUNDARIA', nombre='S1', fecha_inicio=hoy() - timedelta(days=20), fecha_fin=hoy() + timedelta(days=40))
        self.mat = materia_en_grado('MAT', self.primaria, self.ciclo, inicio=None)
        self.esp = materia_en_grado('ESP', self.primaria, self.ciclo, inicio=None)
        self.cie = materia_en_grado('CIE', self.primaria, self.ciclo, inicio=None)
        self.ing = materia_en_grado('ING', self.primaria, self.ciclo, inicio=None)

    def acta(self, asignacion, periodo, finales, estado=ActaCalificaciones.CERRADA, escala='10.00'):
        return ActaCalificaciones.objects.create(
            asignacion=asignacion, periodo=periodo, estado=estado, configuracion_cerrada={'reglas': {'limite_maximo': escala}},
            resultados_cerrados=[{'inscripcion': i.pk, 'final': f} for i, f in finales])

    def calificaciones(self):
        self.acta(self.mat, self.p1, [(self.ana, '9.00'), (self.beto, '7.00'), (self.caro, '8.00')])
        self.acta(self.esp, self.p1, [(self.ana, '9.00'), (self.beto, '7.00'), (self.caro, '8.00')])
        self.acta(self.mat, self.p2, [(self.ana, '5.00'), (self.beto, '7.00'), (self.caro, None)])      # Caro: pendiente
        self.acta(self.esp, self.p2, [(self.ana, '7.00'), (self.beto, '7.50'), (self.caro, '4.00')])
        self.acta(self.cie, self.p2, [(self.caro, '2.00')], estado=ActaCalificaciones.EN_CAPTURA)       # provisional
        self.acta(self.ing, self.p2, [(self.beto, '50.00')], escala='100.00')                         # otra escala

    def entrada(self, inscripcion, fecha, estado):
        return AsistenciaGeneral.objects.create(inscripcion=inscripcion, fecha=fecha, estado=estado,
                                                hora_entrada=None if estado == 'FALTA' else time(7, 50))

    def asistencias(self):
        semana = lunes() - timedelta(days=7)
        # Beto: tres faltas seguidas (lunes a miércoles) y tres días presente
        for dia, estado in zip(range(6), ('FALTA', 'FALTA', 'FALTA', 'PRESENTE', 'PRESENTE', 'PRESENTE')):
            fecha = semana + timedelta(days=dia if dia < 5 else 7)
            self.entrada(self.beto, fecha, estado)
        # Caro: cinco faltas sin justificar, ninguna seguida (lunes, miércoles y viernes)
        for fecha in (semana - timedelta(days=7), semana - timedelta(days=5), semana - timedelta(days=3), semana, semana + timedelta(days=2)):
            self.entrada(self.caro, fecha, 'FALTA')
        # Ana: una falta justificada y una sin justificar
        self.entrada(self.ana, semana, 'FALTA')
        Justificacion.objects.create(inscripcion=self.ana, fecha=semana, motivo='Cita médica', justifica_general=True)
        self.entrada(self.ana, semana + timedelta(days=1), 'FALTA')


@PRUEBAS
class IndicadoresTests(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()

    def test_la_asistencia_del_dia_coincide_con_el_modulo_y_sin_registro_no_es_falta(self):
        dia = lunes() - timedelta(days=14)
        self.entrada(self.ana, dia, 'PRESENTE')
        self.entrada(self.beto, dia, 'FALTA')
        self.entrada(self.zoe, dia, 'RETARDO')                 # Caro, sin registro
        datos = indicadores.entrada_del_dia(filtros_de({}), dia)
        total = resumen_del_dia(dia)['total']
        for clave in ('presentes', 'retardos', 'faltas', 'sin_registro'):
            self.assertEqual(datos[clave], total[clave], clave)
        self.assertEqual((datos['registros'], datos['sin_registro'], datos['porcentaje']), (3, 1, 67))
        # Solo secundaria
        solo = indicadores.entrada_del_dia(filtros_de({'nivel': 'SECUNDARIA'}), dia)
        self.assertEqual((solo['esperados'], solo['retardos'], solo['faltas']), (1, 1, 0))

    def test_estudiantes_activos_por_nivel_sin_repetir(self):
        datos = indicadores.estudiantes(filtros_de({}))
        self.assertEqual(datos['total'], 4)
        self.assertEqual(dict(datos['por_nivel']), {'Primaria': 3, 'Secundaria': 1})
        self.assertEqual(indicadores.estudiantes(filtros_de({'nivel': 'SECUNDARIA'}))['total'], 1)

    def test_calificaciones_solo_cerradas_sin_ceros_por_pendientes_ni_escalas_mezcladas(self):
        self.calificaciones()
        filtros = filtros_de({})
        evaluaciones = academico.evaluaciones(filtros)
        self.assertEqual(evaluaciones['PRIMARIA'].evaluado, self.p2)
        self.assertEqual(evaluaciones['PRIMARIA'].anterior, self.p1)
        self.assertIsNone(evaluaciones['SECUNDARIA'].evaluado)
        datos = indicadores.academico_del_alcance(filtros, evaluaciones)
        # 5, 7, 7, 7.5 y 4: el pendiente de Caro no es cero, CIE está en captura y la de escala 100 se omite
        self.assertEqual(datos['promedio'], Decimal('6.10'))
        self.assertEqual((datos['calificaciones'], datos['estudiantes'], datos['reprobados']), (5, 3, 2))
        self.assertEqual(datos['porcentaje_reprobados'], 66.7)
        self.assertEqual(datos['omitidas'], 1)
        self.assertEqual(datos['previo'], Decimal('8.00'))
        captura = academico.avance_de_captura(filtros, evaluaciones)
        self.assertEqual((captura['cerradas'], captura['en_captura'], captura['sin_acta']), (3, 1, 0))

    def test_un_periodo_sin_actas_cerradas_muestra_el_anterior_y_lo_dice(self):
        self.acta(self.mat, self.p1, [(self.ana, '8.00')])
        ev = academico.evaluaciones(filtros_de({}))['PRIMARIA']
        self.assertEqual((ev.base, ev.evaluado), (self.p2, self.p1))
        self.assertIn('se muestra P1', ev.nota)

    def test_retiros_avisos_y_estudiantes_por_separado(self):
        from Retiros.models import AvisoRetiro, MotivoRetiro, RetiroEstudiante
        tutor = crear_tutor()
        aviso = AvisoRetiro.objects.create(tutor=tutor, fecha=hoy(), hora=time(23, 59), motivo=MotivoRetiro.objects.get(nombre='Cita médica'), recoge=tutor)
        for inscripcion in (self.ana, self.beto):
            RetiroEstudiante.objects.create(aviso=aviso, alumno=inscripcion.alumno, inscripcion=inscripcion, fecha=hoy())
        datos = indicadores.retiros(self.admin, filtros_de({}))
        self.assertEqual((datos['solicitudes'], datos['estudiantes'], datos['pendientes'], datos['realizados']), (1, 2, 2, 0))
        self.assertEqual(indicadores.retiros(self.admin, filtros_de({'nivel': 'SECUNDARIA'}))['estudiantes'], 0)


@PRUEBAS
class AlertasTests(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()
        self.calificaciones()
        self.asistencias()

    def alertas(self, **filtros):
        return {a.inscripcion: a for a in seguimiento.alertas(filtros_de(filtros), True, True)}

    def test_cada_motivo_con_sus_reglas_y_cada_estudiante_una_vez(self):
        alertas = self.alertas()
        self.assertEqual(set(alertas), {self.ana, self.beto, self.caro})
        ana, beto, caro = alertas[self.ana], alertas[self.beto], alertas[self.caro]
        # Ana: rendimiento (reprobada, promedio bajo y descenso en las mismas materias); su falta justificada no cuenta
        self.assertEqual(ana.tipos, {'rendimiento'})
        self.assertEqual((ana.promedio, ana.reprobadas, ana.prioridad), (Decimal('6.00'), 1, 'media'))
        self.assertTrue(any('bajó de 9.00 a 6.00' in t for _, t in ana.motivos))
        # Beto: tres faltas seguidas sin justificar (prioridad alta); con 6 días con registro no se calcula el porcentaje
        self.assertEqual(beto.tipos, {'inasistencia'})
        self.assertEqual((beto.seguidas, beto.prioridad), (3, 'alta'))
        self.assertFalse(any('Inasistencia de' in t for _, t in beto.motivos))
        # Caro: cinco faltas y una reprobada (el pendiente no es cero: su promedio es 4.00): ambos motivos, alta
        self.assertEqual(caro.tipos, {'inasistencia', 'rendimiento'})
        self.assertEqual((caro.faltas_sin_justificar, caro.promedio, caro.prioridad), (5, Decimal('4.00'), 'alta'))
        self.assertEqual(seguimiento.resumen(list(alertas.values())),
                         {'inasistencia': 2, 'rendimiento': 2, 'ambos': 1, 'total': 3, 'alta': 2, 'media': 1, 'baja': 0})

    def test_los_criterios_de_cada_nivel_cambian_las_alertas(self):
        CriterioSeguimiento.objects.create(nivel='PRIMARIA', dias_minimos=3, calificacion_aprobatoria=Decimal('4.00'),
                                           promedio_minimo=Decimal('5.00'))
        alertas = self.alertas()
        self.assertTrue(any('Inasistencia de 50.0 % (3 de 6 días con registro)' in t for _, t in alertas[self.beto].motivos))
        # Ana ya no reprueba ni tiene promedio bajo: solo el descenso, prioridad baja
        self.assertEqual((alertas[self.ana].reprobadas, alertas[self.ana].prioridad), (0, 'baja'))

    def test_el_filtro_de_nivel_y_los_de_motivo_y_prioridad(self):
        self.assertEqual(self.alertas(nivel='SECUNDARIA'), {})
        lista = seguimiento.alertas(filtros_de({}), True, True)
        self.assertEqual([a.inscripcion for a in seguimiento.filtrar(lista, 'ambos')], [self.caro])
        self.assertEqual({a.inscripcion for a in seguimiento.filtrar(lista, prioridad='alta')}, {self.beto, self.caro})

    def test_sin_permiso_de_calificaciones_solo_alertas_de_asistencia(self):
        lista = seguimiento.alertas(filtros_de({}), True, False)
        self.assertEqual({a.inscripcion for a in lista}, {self.beto, self.caro})
        self.assertTrue(all(a.tipos == {'inasistencia'} for a in lista))


@PRUEBAS
class PaginaTests(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()

    def test_el_panel_del_administrador(self):
        respuesta = self.client.get(INICIO)
        self.assertTemplateUsed(respuesta, 'panel/inicio.html')
        for texto in ('Estudiantes activos', 'Asistencia de hoy', 'Rendimiento académico', 'Requiere atención',
                      'Estudiantes que requieren atención', 'Información de todo el colegio', 'Finanzas no está implementado'):
            self.assertContains(respuesta, texto)

    def test_el_alcance_se_conserva_y_se_restablece(self):
        self.client.get(INICIO, {'nivel': 'PRIMARIA'})
        self.assertEqual(self.client.get(INICIO).context['filtros'].nivel, 'PRIMARIA')
        self.assertContains(self.client.get(INICIO), 'Información de Primaria')
        self.assertRedirects(self.client.get(INICIO, {'restablecer': '1'}), INICIO, fetch_redirect_response=False)
        self.assertEqual(self.client.get(INICIO).context['filtros'].nivel, '')

    def test_los_filtros_que_no_corresponden_se_ignoran(self):
        filtros = filtros_de({'nivel': 'SECUNDARIA', 'grado': self.primaria.pk, 'periodo': self.p2.pk})
        self.assertEqual((filtros.nivel, filtros.grado, filtros.periodo), ('SECUNDARIA', None, None))
        self.assertIsNone(filtros_de({'grado': self.primaria.pk}).grado)          # sin nivel no hay grado
        self.assertEqual(filtros_de({'nivel': 'NADA'}).nivel, '')

    def test_cada_bloque_con_el_permiso_de_su_modulo(self):
        rol = crear_rol('Solo asistencia', {'Alumnos.view_alumno', 'Alumnos.view_asistenciageneral'})
        self.client.force_login(crear_usuario('asistencia', rol))
        respuesta = self.client.get(INICIO)
        self.assertIn('asistencia', respuesta.context)
        self.assertNotIn('academico', respuesta.context)
        self.assertNotContains(respuesta, 'Rendimiento académico')
        self.assertNotIn('conducta', respuesta.context)

    def test_sin_permisos_de_los_modulos_el_panel_de_siempre(self):
        self.client.force_login(self.sin_permisos)
        self.assertTemplateUsed(self.client.get(INICIO), 'index.html')

    def test_la_lista_completa_de_seguimiento(self):
        self.calificaciones()
        respuesta = self.client.get(reverse('panel:seguimiento'), {'motivo': 'rendimiento'})
        self.assertEqual(respuesta.context['total_filtradas'], 2)
        self.assertContains(respuesta, 'Reprueba 1 materia')


@PRUEBAS
class CriteriosTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        crear_grado('PRIMARIA', 1)
        self.url = reverse('panel:criterios')

    def datos(self, **cambios):
        datos = {'primaria-revisar_asistencia': 'on', 'primaria-faltas_acumuladas': 4, 'primaria-faltas_consecutivas': 3,
                 'primaria-inasistencia_maxima': '12.00', 'primaria-dias_minimos': 8, 'primaria-revisar_rendimiento': 'on',
                 'primaria-calificacion_aprobatoria': '7.00', 'primaria-materias_reprobadas': 1, 'primaria-promedio_minimo': '7.50',
                 'primaria-descenso_minimo': '1.00', 'primaria-reprobadas_prioridad_alta': 2}
        datos.update(cambios)
        return datos

    def test_propone_valores_y_los_guarda(self):
        self.assertContains(self.client.get(self.url), 'Valores propuestos sin guardar')
        self.assertRedirects(self.client.post(self.url, self.datos()), self.url)
        criterio = CriterioSeguimiento.objects.get(nivel='PRIMARIA')
        self.assertEqual((criterio.faltas_acumuladas, criterio.calificacion_aprobatoria, criterio.modificado_por), (4, Decimal('7.00'), self.admin))

    def test_valores_fuera_de_rango(self):
        respuesta = self.client.post(self.url, self.datos(**{'primaria-calificacion_aprobatoria': '11'}))
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(CriterioSeguimiento.objects.exists())

    def test_quien_solo_consulta_no_guarda_y_sin_permiso_no_entra(self):
        self.client.force_login(crear_usuario('consulta', crear_rol('Consulta', {'Panel.view_criterioseguimiento'})))
        self.assertContains(self.client.get(self.url), 'disabled')
        self.client.post(self.url, self.datos())
        self.assertFalse(CriterioSeguimiento.objects.exists())
        self.client.force_login(self.sin_permisos)
        self.assertEqual(self.client.get(self.url).status_code, 403)
