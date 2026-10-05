"""Ajustes de la entrada, días sin clases y el comando que cierra los días."""
from datetime import time, timedelta
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from Alumnos import asistencias as reglas
from Alumnos.models import AsistenciaGeneral, CierreDia, ConfiguracionAsistencia, DiaNoLectivo
from Asistencias.tests import entrar, url
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseAsistenciaTestCase,
    crear_alumno,
    inscribir_antes,
    lunes,
)


@PRUEBAS
class ReglasDeLaEntradaTests(BaseAsistenciaTestCase):
    hora = (10, 30)

    def guardar(self, **cambios):
        datos = {'hora_entrada': '07:30', 'tolerancia_minutos': '15', 'cierre_automatico': 'on'}
        datos.update(cambios)
        return self.client.post(url('ajustes'), {k: v for k, v in datos.items() if v is not None}, follow=True)

    def test_la_pantalla_muestra_las_reglas_actuales(self):
        respuesta = self.client.get(url('ajustes'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context['form'].instance.hora_entrada, time(8, 0))
        self.assertContains(respuesta, 'Reglas de la entrada')
        self.assertContains(respuesta, 'cerrar_asistencias')

    def test_guarda_las_reglas_y_las_usa_al_registrar_entradas(self):
        respuesta = self.guardar()
        self.assertRedirects(respuesta, url('ajustes'))
        self.assertContains(respuesta, 'Se guardaron las reglas')
        configuracion = ConfiguracionAsistencia.cargar()
        self.assertEqual((configuracion.hora_entrada, configuracion.tolerancia_minutos), (time(7, 30), 15))
        entrar(self.alumno, (7, 44))
        self.assertEqual(AsistenciaGeneral.objects.get().estado, 'PRESENTE')           # 7:44 está dentro de 7:30 + 15 min
        self.assertEqual(reglas.estado_de_entrada(time(7, 46), ConfiguracionAsistencia.cargar()), 'RETARDO')

    def test_hay_un_solo_registro_de_reglas(self):
        self.guardar()
        self.guardar(tolerancia_minutos='5')
        self.assertEqual(ConfiguracionAsistencia.objects.count(), 1)
        self.assertEqual(ConfiguracionAsistencia.cargar().tolerancia_minutos, 5)

    def test_valida_los_datos(self):
        for cambios in ({'tolerancia_minutos': '500'}, {'tolerancia_minutos': '-1'}, {'tolerancia_minutos': 'x'}, {'hora_entrada': '25:00'}, {'hora_entrada': ''}):
            respuesta = self.guardar(**cambios)
            self.assertTrue(respuesta.context['form'].errors, str(cambios))
        self.assertEqual(ConfiguracionAsistencia.cargar().tolerancia_minutos, 10)

    def test_se_puede_apagar_el_cierre_automatico(self):
        self.guardar(cierre_automatico=None)
        self.assertFalse(ConfiguracionAsistencia.cargar().cierre_automatico)

    def test_ver_los_ajustes_no_da_permiso_para_cambiarlos(self):
        self.con_permisos('view_configuracionasistencia')
        self.assertNotContains(self.client.get(url('ajustes')), 'Guardar reglas')
        self.assertEqual(self.client.post(url('ajustes'), {'hora_entrada': '07:00', 'tolerancia_minutos': '1'}).status_code, 403)
        self.assertEqual(ConfiguracionAsistencia.cargar().tolerancia_minutos, 10)


@PRUEBAS
class DiasSinClasesTests(BaseAsistenciaTestCase):
    hora = (10, 30)

    def crear(self, **cambios):
        datos = {'desde': (lunes() + timedelta(days=7)).isoformat(), 'hasta': '', 'motivo': 'Consejo técnico'}
        datos.update(cambios)
        return self.client.post(url('dia_sin_clases_crear'), datos, follow=True)

    def test_registra_un_dia(self):
        respuesta = self.crear()
        self.assertRedirects(respuesta, url('ajustes'))
        self.assertContains(respuesta, 'Se registró 1 día sin clases')
        dia = DiaNoLectivo.objects.get()
        self.assertEqual((dia.fecha, dia.motivo), (lunes() + timedelta(days=7), 'Consejo técnico'))

    def test_registra_un_periodo(self):
        inicio = lunes() + timedelta(days=7)
        respuesta = self.crear(hasta=(inicio + timedelta(days=4)).isoformat(), motivo='  Semana   santa ')
        self.assertContains(respuesta, 'Se registraron 5 días sin clases')
        self.assertEqual(DiaNoLectivo.objects.count(), 5)
        self.assertEqual(set(DiaNoLectivo.objects.values_list('motivo', flat=True)), {'Semana santa'})

    def test_no_repite_los_dias_ya_registrados(self):
        inicio = lunes() + timedelta(days=7)
        DiaNoLectivo.objects.create(fecha=inicio, motivo='Antes')
        self.crear(hasta=(inicio + timedelta(days=2)).isoformat())
        self.assertEqual(DiaNoLectivo.objects.count(), 3)
        self.assertEqual(DiaNoLectivo.objects.get(fecha=inicio).motivo, 'Antes')
        respuesta = self.crear(desde=inicio.isoformat())
        self.assertContains(respuesta, 'ya está registrado')
        self.assertEqual(DiaNoLectivo.objects.count(), 3)

    def test_valida_los_datos(self):
        casos = (
            {'desde': ''}, {'desde': 'x'}, {'motivo': ''}, {'motivo': 'x' * 200},
            {'hasta': (lunes() - timedelta(days=30)).isoformat()},
            {'hasta': (lunes() + timedelta(days=400)).isoformat()},
        )
        for cambios in casos:
            respuesta = self.crear(**cambios)
            self.assertContains(respuesta, 'No se registró', msg_prefix=str(cambios))
        self.assertFalse(DiaNoLectivo.objects.exists())

    def test_un_dia_sin_clases_deja_de_registrar_entradas(self):
        self.crear(desde=lunes().isoformat(), motivo='Puente')
        with self.assertRaises(reglas.EntradaRechazada):
            entrar(self.alumno)

    def test_quitar_un_dia_vuelve_a_permitir_entradas(self):
        self.crear(desde=lunes().isoformat(), motivo='Puente')
        respuesta = self.client.post(url('dia_sin_clases_eliminar', DiaNoLectivo.objects.get().pk), follow=True)
        self.assertContains(respuesta, 'Se quitó el día sin clases')
        self.assertFalse(DiaNoLectivo.objects.exists())
        entrar(self.alumno)
        self.assertEqual(AsistenciaGeneral.objects.count(), 1)

    def test_quitar_un_dia_inexistente_da_404(self):
        self.assertEqual(self.client.post(url('dia_sin_clases_eliminar', 9999)).status_code, 404)

    def test_la_lista_va_del_mas_reciente_al_mas_antiguo_y_marca_los_proximos(self):
        DiaNoLectivo.objects.create(fecha=lunes() - timedelta(days=14), motivo='Pasado')
        DiaNoLectivo.objects.create(fecha=lunes() + timedelta(days=14), motivo='Futuro')
        respuesta = self.client.get(url('ajustes'))
        self.assertEqual([d.motivo for d in respuesta.context['dias_sin_clases']], ['Futuro', 'Pasado'])
        self.assertEqual(respuesta.context['proximos'], 1)
        self.assertContains(respuesta, 'Próximo')

    def test_sin_permiso_para_agregar_o_quitar_no_hay_controles(self):
        DiaNoLectivo.objects.create(fecha=lunes() + timedelta(days=7), motivo='Puente')
        self.con_permisos('view_configuracionasistencia')
        respuesta = self.client.get(url('ajustes'))
        self.assertNotContains(respuesta, 'dia_sin_clases_crear')
        self.assertNotContains(respuesta, 'Quitar el día sin clases')

    def test_muestra_los_cierres_recientes(self):
        entrar(self.alumno, (7, 45))
        reglas.cerrar_dia(lunes(), usuario=self.admin)
        respuesta = self.client.get(url('ajustes'))
        self.assertEqual([c.fecha for c in respuesta.context['cierres']], [lunes()])
        self.assertContains(respuesta, 'Cierres recientes')

    def test_consultas_constantes(self):
        with CaptureQueriesContext(connection) as pocas:
            self.client.get(url('ajustes'))
        for i in range(20):
            DiaNoLectivo.objects.create(fecha=lunes() + timedelta(days=i + 1), motivo=f'Día {i}')
        with CaptureQueriesContext(connection) as muchas:
            self.client.get(url('ajustes'))
        self.assertEqual(len(muchas), len(pocas))


@PRUEBAS
class ComandoCerrarAsistenciasTests(BaseAsistenciaTestCase):
    hora = (10, 30)

    def setUp(self):
        super().setUp()
        self.ausente = inscribir_antes(crear_alumno(), self.ciclo, self.grado)
        self.anterior = lunes() - timedelta(days=7)
        entrar(self.alumno, (7, 45), self.anterior)

    def ejecutar(self, *argumentos):
        salida = StringIO()
        call_command('cerrar_asistencias', *argumentos, stdout=salida)
        return salida.getvalue()

    def test_cierra_todos_los_dias_pendientes(self):
        texto = self.ejecutar()
        self.assertIn(f'{self.anterior}: cerrado, 1 falta(s) generada(s).', texto)
        cierre = CierreDia.objects.get(fecha=self.anterior)
        self.assertTrue(cierre.automatico)
        self.assertEqual(AsistenciaGeneral.objects.get(inscripcion=self.ausente, fecha=self.anterior).estado, 'FALTA')

    def test_sin_pendientes_lo_dice(self):
        self.ejecutar()
        self.assertIn('No había días pendientes', self.ejecutar())

    def test_cierra_solo_el_dia_pedido(self):
        texto = self.ejecutar('--fecha', self.anterior.isoformat())
        self.assertIn('cerrado', texto)
        self.assertTrue(CierreDia.objects.filter(fecha=self.anterior).exists())

    def test_un_dia_que_no_se_cierra_lo_explica(self):
        DiaNoLectivo.objects.create(fecha=self.anterior, motivo='Puente')
        self.assertIn('no se cierra', self.ejecutar('--fecha', self.anterior.isoformat()))
        self.assertFalse(CierreDia.objects.exists())

    def test_una_fecha_mal_escrita_es_un_error(self):
        with self.assertRaises(CommandError):
            self.ejecutar('--fecha', '05/10/2026')
