"""Ajustes de la entrada, días sin clases y el comando que cierra los días."""
from datetime import time, timedelta
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from Alumnos import asistencias as reglas
from Alumnos.models import AsistenciaGeneral, CierreDia, ConfiguracionAsistencia, DiaNoLectivo
from Asistencias.tests import entrar, url
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseAsistenciaTestCase,
    ciclo_cerrado_de_prueba,
    ciclo_proximo_de_prueba,
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

    def test_esta_en_ajustes_del_menu_sistema(self):
        respuesta = self.client.get(url('ajustes'))
        self.assertTrue(url('ajustes').startswith('/ajustes/'))
        html = respuesta.content.decode()
        self.assertRegex(html, r'<a class="nav__link" href="/ajustes/" aria-current="page"')   # se marca «Ajustes» en el menú
        self.assertNotRegex(html, r'href="/asistencias/[^"]*" aria-current="page"')
        self.assertContains(respuesta, 'href="/ajustes/">Ajustes</a>')   # la ruta de navegación
        self.assertContains(respuesta, 'aria-current="page">Asistencia</a>')   # la pestaña de Ajustes
        # La sección de asistencias ya no tiene la pestaña de ajustes
        self.assertNotContains(self.client.get(url('inicio')), f'href="{url("ajustes")}" aria-current')

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

    def test_la_hora_limite_de_entrada_por_nivel(self):
        from Alumnos.models import LimiteEntradaNivel
        self.assertContains(self.client.get(url('ajustes')), 'Hora límite de entrada por nivel')
        self.guardar(limite_PRIMARIA='07:40', limite_SECUNDARIA='07:20')
        self.assertEqual(dict(LimiteEntradaNivel.objects.values_list('nivel', 'hora_limite')), {'PRIMARIA': time(7, 40), 'SECUNDARIA': time(7, 20)})
        self.assertEqual(reglas.estado_de_entrada(time(7, 42), ConfiguracionAsistencia.cargar(), 'PRIMARIA'), 'RETARDO')
        self.assertEqual(reglas.estado_de_entrada(time(7, 42), ConfiguracionAsistencia.cargar(), 'PREESCOLAR'), 'PRESENTE')   # la general
        self.guardar(limite_PRIMARIA='07:40')   # vaciar un nivel le quita su límite
        self.assertEqual(list(LimiteEntradaNivel.objects.values_list('nivel', flat=True)), ['PRIMARIA'])
        self.assertTrue(self.guardar(limite_PRIMARIA='25:00').context['form'].errors)

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
    """La tarjeta de días sin clases está en el detalle de cada ciclo (2026-10-26; antes en la lista de ciclos)."""
    hora = (10, 30)

    @property
    def CICLOS(self):   # noqa: N802
        return self.ciclo.get_absolute_url()

    def crear(self, **cambios):
        datos = {'desde': (lunes() + timedelta(days=7)).isoformat(), 'hasta': '', 'motivo': 'Consejo técnico', 'niveles': ['TODOS']}
        datos.update(cambios)
        return self.client.post(url('dia_sin_clases_crear'), datos, follow=True)

    def test_registra_un_dia(self):
        respuesta = self.crear()
        self.assertRedirects(respuesta, f'{self.CICLOS}#dias-sin-clases')
        self.assertContains(respuesta, 'Se registró 1 día sin clases para todos los niveles')
        # «Todos los niveles» lo registra en los cuatro
        self.assertEqual(
            set(DiaNoLectivo.objects.values_list('fecha', 'nivel', 'motivo')),
            {(lunes() + timedelta(days=7), nivel, 'Consejo técnico') for nivel in ('PREESCOLAR', 'PRIMARIA', 'SECUNDARIA', 'PREPARATORIA')},
        )

    def test_registra_solo_los_niveles_elegidos(self):
        respuesta = self.crear(niveles=['PRIMARIA', 'SECUNDARIA'])
        self.assertContains(respuesta, 'Se registró 1 día sin clases para primaria y secundaria')
        self.assertEqual(set(DiaNoLectivo.objects.values_list('nivel', flat=True)), {'PRIMARIA', 'SECUNDARIA'})
        # Otro nivel el mismo día, con su propio motivo
        self.crear(niveles=['PREESCOLAR'], motivo='Festival')
        self.assertEqual(dict(DiaNoLectivo.objects.values_list('nivel', 'motivo')),
                         {'PRIMARIA': 'Consejo técnico', 'SECUNDARIA': 'Consejo técnico', 'PREESCOLAR': 'Festival'})
        # «Todos los niveles» con otro nivel marcado sigue siendo todos
        self.crear(desde=(lunes() + timedelta(days=8)).isoformat(), niveles=['TODOS', 'PRIMARIA'])
        self.assertEqual(DiaNoLectivo.objects.filter(fecha=lunes() + timedelta(days=8)).count(), 4)

    def test_la_lista_agrupa_los_niveles_de_cada_dia(self):
        self.crear()
        self.crear(desde=(lunes() + timedelta(days=8)).isoformat(), niveles=['PREPARATORIA', 'PREESCOLAR'], motivo='Junta')
        respuesta = self.client.get(self.CICLOS)
        dias = respuesta.context['dias_sin_clases']
        self.assertEqual([(d.motivo, d.todos, d.nombres) for d in dias],
                         [('Junta', False, ['Preescolar', 'Preparatoria']), ('Consejo técnico', True, ['Preescolar', 'Primaria', 'Secundaria', 'Preparatoria'])])
        self.assertContains(respuesta, 'Todos los niveles', count=2)   # la casilla y la etiqueta del día
        self.assertContains(respuesta, 'data-niveles-sin-clases')

    def test_registra_un_periodo(self):
        inicio = lunes() + timedelta(days=7)
        respuesta = self.crear(hasta=(inicio + timedelta(days=4)).isoformat(), motivo='  Semana   santa ')
        self.assertContains(respuesta, 'Se registraron 5 días sin clases')
        self.assertEqual(DiaNoLectivo.objects.count(), 20)   # cinco días en cuatro niveles
        self.assertEqual(set(DiaNoLectivo.objects.values_list('motivo', flat=True)), {'Semana santa'})

    def test_no_repite_los_dias_ya_registrados(self):
        inicio = lunes() + timedelta(days=7)
        DiaNoLectivo.registrar(fecha=inicio, motivo='Antes')
        self.crear(hasta=(inicio + timedelta(days=2)).isoformat())
        self.assertEqual(DiaNoLectivo.objects.count(), 12)
        self.assertEqual(set(DiaNoLectivo.objects.filter(fecha=inicio).values_list('motivo', flat=True)), {'Antes'})
        respuesta = self.crear(desde=inicio.isoformat())
        self.assertContains(respuesta, 'ya está registrado')
        self.assertEqual(DiaNoLectivo.objects.count(), 12)

    def test_valida_los_datos(self):
        casos = (
            {'desde': ''}, {'desde': 'x'}, {'motivo': ''}, {'motivo': 'x' * 200}, {'niveles': []}, {'niveles': ['OTRO']},
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
        respuesta = self.client.post(url('dia_sin_clases_eliminar', DiaNoLectivo.objects.first().pk), follow=True)
        self.assertContains(respuesta, 'Se quitó el día sin clases')
        self.assertContains(respuesta, '(todos los niveles)')
        self.assertFalse(DiaNoLectivo.objects.exists())   # se quita con todos sus niveles
        entrar(self.alumno)
        self.assertEqual(AsistenciaGeneral.objects.count(), 1)

    def test_quitar_un_dia_inexistente_da_404(self):
        self.assertEqual(self.client.post(url('dia_sin_clases_eliminar', 9999)).status_code, 404)

    def test_la_lista_va_del_mas_reciente_al_mas_antiguo_y_marca_los_proximos(self):
        DiaNoLectivo.registrar(fecha=lunes() - timedelta(days=14), motivo='Pasado')
        DiaNoLectivo.registrar(fecha=lunes() + timedelta(days=14), motivo='Futuro')
        respuesta = self.client.get(self.CICLOS)
        self.assertEqual([d.motivo for d in respuesta.context['dias_sin_clases']], ['Futuro', 'Pasado'])
        self.assertContains(respuesta, '<span class="tag tag--info">Próximo</span>', count=1)   # solo el futuro

    def test_la_tarjeta_esta_en_el_detalle_del_ciclo_y_no_en_la_lista_ni_en_ajustes(self):
        DiaNoLectivo.registrar(fecha=lunes() + timedelta(days=7), motivo='Puente')
        self.assertNotContains(self.client.get(reverse('ciclos:lista')), 'id="dias-sin-clases"')
        ciclos = self.client.get(self.CICLOS)
        self.assertContains(ciclos, 'id="dias-sin-clases"')
        self.assertContains(ciclos, url('dia_sin_clases_crear'))
        self.assertContains(ciclos, 'js/dias-sin-clases.js')
        ajustes = self.client.get(url('ajustes'))
        self.assertNotContains(ajustes, 'Días sin clases</h2>')
        self.assertNotContains(ajustes, url('dia_sin_clases_crear'))

    def test_sin_ciclo_actual_se_carga_el_calendario_del_ciclo_que_viene(self):
        # En vacaciones: el ciclo anterior ya se cerró y el nuevo todavía no es el actual
        siguiente = ciclo_proximo_de_prueba()
        self.client.post(reverse('ciclos:cerrar', args=[self.ciclo.pk]))
        fecha = siguiente.fecha_inicio + timedelta(days=20)
        respuesta = self.crear(desde=fecha.isoformat(), ciclo=siguiente.pk, motivo='Consejo técnico')
        self.assertRedirects(respuesta, f'{siguiente.get_absolute_url()}#dias-sin-clases')
        self.assertContains(respuesta, 'Se registró 1 día sin clases')
        self.assertEqual(respuesta.context['dias_sin_clases'][0].fecha, fecha)

    def test_solo_en_el_ciclo_actual_o_en_uno_proximo_y_dentro_de_sus_fechas(self):
        cerrado = ciclo_cerrado_de_prueba()
        respuesta = self.crear(desde=(cerrado.fecha_inicio + timedelta(days=10)).isoformat())
        self.assertContains(respuesta, 'ya está cerrado')
        respuesta = self.crear(desde=(cerrado.fecha_fin + timedelta(days=1)).isoformat())   # entre dos ciclos
        self.assertContains(respuesta, 'fuera de las fechas de cualquier ciclo')
        respuesta = self.crear(desde=(self.ciclo.fecha_fin - timedelta(days=1)).isoformat(),
                               hasta=(self.ciclo.fecha_fin + timedelta(days=2)).isoformat())
        self.assertContains(respuesta, f'deben quedar dentro del ciclo {self.ciclo}')
        respuesta = self.crear(ciclo=cerrado.pk)   # el ciclo del detalle manda
        self.assertContains(respuesta, 'ya está cerrado')
        self.assertFalse(DiaNoLectivo.objects.exists())
        # El detalle de un ciclo cerrado no ofrece el formulario; lo registrado se puede seguir quitando
        DiaNoLectivo.registrar(fecha=cerrado.fecha_inicio + timedelta(days=10), motivo='Puente')
        detalle = self.client.get(cerrado.get_absolute_url())
        self.assertContains(detalle, 'El ciclo está cerrado')
        self.assertNotContains(detalle, url('dia_sin_clases_crear'))
        self.assertContains(detalle, 'Quitar el día sin clases')

    def test_cada_ciclo_muestra_solo_sus_dias(self):
        proximo = ciclo_proximo_de_prueba()
        DiaNoLectivo.registrar(fecha=lunes() + timedelta(days=7), motivo='De este ciclo')
        DiaNoLectivo.registrar(fecha=proximo.fecha_inicio + timedelta(days=7), motivo='Del que viene')
        self.assertEqual([d.motivo for d in self.client.get(self.CICLOS).context['dias_sin_clases']], ['De este ciclo'])
        self.assertEqual([d.motivo for d in self.client.get(proximo.get_absolute_url()).context['dias_sin_clases']], ['Del que viene'])
        # El enlace fijo («Ver días sin clases» de Asistencia) lleva al del ciclo actual
        self.assertRedirects(self.client.get(reverse('ciclos:dias_sin_clases')), f'{self.CICLOS}#dias-sin-clases')

    def test_sin_permiso_para_agregar_o_quitar_no_hay_controles(self):
        DiaNoLectivo.registrar(fecha=lunes() + timedelta(days=7), motivo='Puente')
        self.con_permisos('view_cicloescolar')
        respuesta = self.client.get(self.CICLOS)
        self.assertContains(respuesta, 'Puente')   # la lista sí la ve quien ve los ciclos
        self.assertNotContains(respuesta, url('dia_sin_clases_crear'))
        self.assertNotContains(respuesta, 'Quitar el día sin clases')

    def test_muestra_los_cierres_recientes(self):
        entrar(self.alumno, (7, 45))
        reglas.cerrar_dia(lunes(), usuario=self.admin)
        respuesta = self.client.get(url('ajustes'))
        self.assertEqual([c.fecha for c in respuesta.context['cierres']], [lunes()])
        self.assertContains(respuesta, 'Cierres recientes')

    def test_consultas_constantes(self):
        with CaptureQueriesContext(connection) as pocas:
            self.client.get(self.CICLOS)
        for i in range(20):
            DiaNoLectivo.registrar(fecha=lunes() + timedelta(days=i + 1), motivo=f'Día {i}')
        with CaptureQueriesContext(connection) as muchas:
            self.client.get(self.CICLOS)
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
        DiaNoLectivo.registrar(fecha=self.anterior, motivo='Puente')
        self.assertIn('no se cierra', self.ejecutar('--fecha', self.anterior.isoformat()))
        self.assertFalse(CierreDia.objects.exists())

    def test_una_fecha_mal_escrita_es_un_error(self):
        with self.assertRaises(CommandError):
            self.ejecutar('--fecha', '05/10/2026')
