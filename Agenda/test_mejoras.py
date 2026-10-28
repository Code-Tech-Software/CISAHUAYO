"""Mejoras de la agenda (pedido del 2026-10-27): los días sin clases y lo de otros módulos (fechas de calificaciones,
ciclo escolar) en la agenda, solo para consultar; el historial en la Bitácora de cambios; las direcciones de la
descripción como enlaces; «Próximos eventos» en el inicio; el archivo .ics de un evento y la suscripción del teléfono;
los recordatorios de los eventos importantes (campana y push); los tipos de evento y su filtro; la semana, los próximos
y la búsqueda; los eventos que se repiten; duplicar e imprimir el mes."""
from datetime import date, timedelta
from unittest import mock

from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from Alumnos.models import DiaNoLectivo, Periodo
from CISAHUAYO import portales
from CISAHUAYO.pruebas import (
    PRUEBAS, BaseTestCase, ciclo_actual_de_prueba, crear_alumno, crear_grado, crear_tutor, crear_usuario, inscribir_antes, vincular,
)
from Usuarios.models import PerfilUsuario

from . import recordatorios, reglas
from .fuentes import Persona
from .models import COLEGIO, FESTIVAL, JUNTA, AvisoAgenda, EventoAgenda, SuscripcionCalendario
from .tests import entrar_al_portal, evento

CALENDARIO = reverse('agenda:calendario')
NUEVO = reverse('agenda:crear')


def externos(respuesta, prefijo=''):
    """Lo de otros módulos en la página (días sin clases «s…», calificaciones «p…», ciclo «ci…»…)."""
    return [dato for dato in respuesta.context['datos_eventos'] if not dato['id'].isdigit() and dato['id'].startswith(prefijo)]


def datos_del_evento(**cambios):
    datos = {
        'titulo': 'Taller de lectura', 'alcance': 'PRIMARIA', 'tipo': '', 'fecha_inicio': '2026-11-04', 'fecha_fin': '',
        'todo_el_dia': 'on', 'hora_inicio': '', 'hora_fin': '', 'lugar': 'Biblioteca', 'descripcion': '',
        'volver': f'{CALENDARIO}?mes=2026-11',
    }
    datos.update(cambios)
    return {clave: valor for clave, valor in datos.items() if valor is not None}


# ---------------------------------------------------------------------------
# Días sin clases y lo de otros módulos
# ---------------------------------------------------------------------------
@PRUEBAS
class OtrosModulosTests(BaseTestCase):
    def test_los_dias_sin_clases_de_todo_el_colegio_se_ven_como_una_barra_que_no_se_edita(self):
        # Viernes y lunes, con el fin de semana de por medio: una sola barra
        DiaNoLectivo.registrar(date(2026, 10, 30), 'Puente')
        DiaNoLectivo.registrar(date(2026, 11, 2), 'Puente')
        respuesta = self.client.get(CALENDARIO, {'mes': '2026-11'})
        [dia] = externos(respuesta, 's')
        self.assertEqual(dia['titulo'], 'Sin clases: Puente')
        self.assertIn('Todos los niveles', dia['alcance'])
        self.assertIn('Del 30 de octubre al 2 de noviembre', dia['fechas'])
        for accion in ('editar', 'eliminar', 'duplicar', 'calendario'):
            self.assertNotIn(accion, dia)
        self.assertIn('Días sin clases', [nombre for _, nombre, *_ in respuesta.context['leyenda']])

    def test_un_dia_sin_clases_de_un_nivel_solo_lo_ve_quien_tiene_ese_nivel(self):
        DiaNoLectivo.registrar(date(2026, 11, 13), 'Consejo técnico', ['PRIMARIA'])
        self.assertEqual(len(externos(self.client.get(CALENDARIO, {'mes': '2026-11'}), 's')), 1)
        self.assertEqual(externos(self.client.get(CALENDARIO, {'mes': '2026-11', 'nivel': 'SECUNDARIA'}), 's'), [])
        secundaria = crear_usuario('secundaria')
        PerfilUsuario.objects.filter(usuario=secundaria).update(niveles_retiros=['SECUNDARIA'])
        self.client.force_login(secundaria)
        self.assertEqual(externos(self.client.get(CALENDARIO, {'mes': '2026-11'}), 's'), [])
        primaria = crear_usuario('primaria')
        PerfilUsuario.objects.filter(usuario=primaria).update(niveles_retiros=['PRIMARIA'])
        self.client.force_login(primaria)
        [dia] = externos(self.client.get(CALENDARIO, {'mes': '2026-11'}), 's')
        self.assertIn('Primaria', dia['alcance'])

    def test_las_fechas_de_captura_de_calificaciones_solo_para_quien_captura(self):
        ciclo = ciclo_actual_de_prueba()
        periodo = Periodo.objects.create(ciclo=ciclo, nivel='PRIMARIA', nombre='Primer trimestre', fecha_inicio=date(2026, 11, 9),
                                         fecha_fin=date(2026, 11, 13))
        [dato] = externos(self.client.get(CALENDARIO, {'mes': '2026-11'}), 'p')
        self.assertEqual(dato['id'], f'p{periodo.pk}')
        self.assertIn('Primer trimestre', dato['titulo'])
        self.client.force_login(self.sin_permisos)
        self.assertEqual(externos(self.client.get(CALENDARIO, {'mes': '2026-11'}), 'p'), [])

    def test_el_inicio_y_el_fin_del_ciclo_escolar_para_todos(self):
        ciclo = ciclo_actual_de_prueba()
        self.client.force_login(self.sin_permisos)
        respuesta = self.client.get(CALENDARIO, {'mes': f'{ciclo.fecha_inicio:%Y-%m}'})
        self.assertIn(f'ci{ciclo.pk}i', [dato['id'] for dato in externos(respuesta, 'ci')])

    def test_con_filtro_de_nivel_no_aparece_lo_que_no_tiene_nivel(self):
        ciclo = ciclo_actual_de_prueba()
        respuesta = self.client.get(CALENDARIO, {'mes': f'{ciclo.fecha_inicio:%Y-%m}', 'nivel': 'PRIMARIA'})
        self.assertEqual(externos(respuesta, 'ci'), [])


# ---------------------------------------------------------------------------
# Historial, enlaces, duplicar
# ---------------------------------------------------------------------------
@PRUEBAS
class HistorialYEnlacesTests(BaseTestCase):
    def test_registrar_corregir_y_eliminar_quedan_en_la_bitacora_de_cambios(self):
        self.client.post(NUEVO, datos_del_evento())
        nuevo = EventoAgenda.objects.get()
        self.client.post(reverse('agenda:editar', args=[nuevo.pk]), datos_del_evento(titulo='Taller de escritura'))
        self.client.post(reverse('agenda:eliminar', args=[nuevo.pk]))
        anotaciones = LogEntry.objects.filter(object_id=str(nuevo.pk), content_type__model='eventoagenda').order_by('pk')
        self.assertEqual([a.action_flag for a in anotaciones], [ADDITION, CHANGE, DELETION])
        self.assertTrue(all(a.user_id == self.admin.pk for a in anotaciones))
        self.assertIn('Registró el evento', anotaciones[0].change_message)
        self.assertIn('Eliminó el evento', anotaciones[2].change_message)
        self.assertEqual(anotaciones[2].object_repr, 'Taller de escritura')

    def test_las_direcciones_de_la_descripcion_son_enlaces_y_lo_demas_se_escapa(self):
        nuevo = evento('Inscripciones', COLEGIO, descripcion='Regístrate en https://colegio.mx/registro <b>ya</b>')
        detalle = self.client.get(CALENDARIO, {'evento': nuevo.pk})
        self.assertContains(detalle, 'href="https://colegio.mx/registro"')
        self.assertContains(detalle, '&lt;b&gt;ya&lt;/b&gt;')
        self.assertNotContains(detalle, '<b>ya</b>')
        [dato] = self.client.get(CALENDARIO, {'mes': '2026-10'}).context['datos_eventos']
        self.assertIn('href="https://colegio.mx/registro"', dato['descripcionHtml'])
        self.assertNotIn('<b>', dato['descripcionHtml'])

    def test_duplicar_trae_lo_del_evento_y_crea_uno_nuevo(self):
        original = evento('Festival', 'SECUNDARIA', lugar='Auditorio', tipo=FESTIVAL, importante=True)
        form = self.client.get(NUEVO, {'copiar': original.pk}).context['form']
        self.assertEqual((form['titulo'].value(), form['alcance'].value(), form['lugar'].value(), form['tipo'].value()),
                         ('Festival', 'SECUNDARIA', 'Auditorio', FESTIVAL))
        self.assertTrue(form['importante'].value())
        self.assertEqual([dato.get('duplicar', '') for dato in self.client.get(CALENDARIO, {'mes': '2026-10'}).context['datos_eventos']],
                         [f'{NUEVO}?copiar={original.pk}&volver=%2Fagenda%2F%3Fmes%3D2026-10'])


# ---------------------------------------------------------------------------
# Tipos, semana, próximos y búsqueda; imprimir
# ---------------------------------------------------------------------------
@PRUEBAS
class VistasTests(BaseTestCase):
    def test_el_filtro_por_tipo_y_el_icono(self):
        junta = evento('Junta de padres', COLEGIO, tipo=JUNTA)
        evento('Festival', COLEGIO, tipo=FESTIVAL)
        respuesta = self.client.get(CALENDARIO, {'mes': '2026-10', 'tipo': JUNTA})
        self.assertEqual([dato['id'] for dato in respuesta.context['datos_eventos']], [str(junta.pk)])
        self.assertEqual(respuesta.context['datos_eventos'][0]['tipo'], 'Juntas y reuniones')
        self.assertContains(respuesta, '#users')
        # Un tipo que no existe se ignora
        self.assertEqual(len(self.client.get(CALENDARIO, {'mes': '2026-10', 'tipo': 'NADA'}).context['datos_eventos']), 2)

    def test_la_semana_muestra_sus_siete_dias(self):
        evento('Junta', COLEGIO, inicio=date(2026, 10, 14))
        evento('Excursión', COLEGIO, inicio=date(2026, 10, 15), fin=date(2026, 10, 20))
        respuesta = self.client.get(CALENDARIO, {'vista': 'semana', 'dia': '2026-10-14'})
        dias = respuesta.context['dias_de_la_semana']
        self.assertEqual([fecha for fecha, _ in dias], [date(2026, 10, 12) + timedelta(days=i) for i in range(7)])
        self.assertEqual([e.titulo for e in dias[2][1]], ['Junta'])
        self.assertEqual([e.titulo for e in dias[6][1]], ['Excursión'])   # sigue el domingo
        self.assertEqual(respuesta.context['titulo'], 'Semana del 12 al 18 de octubre de 2026')

    def test_proximos_lista_lo_que_viene_desde_hoy(self):
        hoy = timezone.localdate()
        evento('Pasado', COLEGIO, inicio=hoy - timedelta(days=3))
        evento('Mañana', COLEGIO, inicio=hoy + timedelta(days=1))
        respuesta = self.client.get(CALENDARIO, {'vista': 'lista'})
        self.assertEqual([[e.titulo for e in eventos] for _, eventos in respuesta.context['lista']], [['Mañana']])

    def test_la_busqueda_encuentra_por_titulo_descripcion_o_lugar_en_proximos_y_pasados(self):
        hoy = timezone.localdate()
        evento('Festival de invierno', COLEGIO, inicio=hoy + timedelta(days=40))
        evento('Ensayo', COLEGIO, inicio=hoy - timedelta(days=40), descripcion='Para el festival')
        evento('Junta', COLEGIO, inicio=hoy + timedelta(days=5), lugar='Sala Festival')
        evento('Otro', COLEGIO, inicio=hoy + timedelta(days=5))
        respuesta = self.client.get(CALENDARIO, {'q': 'festival'})
        self.assertEqual([e.titulo for e in respuesta.context['futuros']], ['Junta', 'Festival de invierno'])
        self.assertEqual([e.titulo for e in respuesta.context['pasados']], ['Ensayo'])
        self.assertContains(respuesta, '3 eventos')

    def test_imprimir_el_mes_con_todos_sus_eventos(self):
        for numero in range(5):   # en el calendario serían «+N eventos»; en la hoja, todos
            evento(f'Evento {numero}', COLEGIO, inicio=date(2026, 10, 14))
        respuesta = self.client.get(reverse('agenda:imprimir'), {'mes': '2026-10'})
        self.assertEqual(respuesta.status_code, 200)
        for numero in range(5):
            self.assertContains(respuesta, f'Evento {numero}')
        self.assertContains(respuesta, 'Octubre 2026')
        self.assertNotContains(respuesta, 'data-notificaciones')   # sin menús ni campana


# ---------------------------------------------------------------------------
# Próximos eventos en el inicio
# ---------------------------------------------------------------------------
@PRUEBAS
class ProximosTests(BaseTestCase):
    def test_el_inicio_del_sistema_muestra_los_proximos_dos_semanas(self):
        hoy = timezone.localdate()
        evento('Junta de padres', COLEGIO, inicio=hoy + timedelta(days=1))
        evento('Muy lejos', COLEGIO, inicio=hoy + timedelta(days=20))
        respuesta = self.client.get(reverse('inicio'))
        self.assertContains(respuesta, 'Próximos eventos')
        self.assertEqual([(item['dia'], item['evento'].titulo) for item in respuesta.context['proximos']], [('Mañana', 'Junta de padres')])
        self.assertNotContains(respuesta, 'Muy lejos')

    def test_un_evento_que_ya_empezo_y_sigue_aparece_como_hoy(self):
        hoy = timezone.localdate()
        evento('Semana cultural', COLEGIO, inicio=hoy - timedelta(days=2), fin=hoy + timedelta(days=2))
        [item] = reglas.proximos(Persona(usuario=self.admin))
        self.assertEqual((item['dia'], item['fecha']), ('Hoy', hoy))

    def test_el_portal_de_tutores_muestra_sus_proximos(self):
        hoy = timezone.localdate()
        evento('Festival', COLEGIO, inicio=hoy + timedelta(days=3))
        evento('De preparatoria', 'PREPARATORIA', inicio=hoy + timedelta(days=3))
        tutor = crear_tutor(usuario='rosa.mora')
        self.client.logout()
        entrar_al_portal(self.client, portales.TUTOR, tutor)
        respuesta = self.client.get(reverse('portal_tutores:inicio'))
        self.assertContains(respuesta, 'Próximos eventos')
        self.assertContains(respuesta, 'Festival')
        self.assertNotContains(respuesta, 'De preparatoria')


# ---------------------------------------------------------------------------
# Agregar a mi calendario y suscripción
# ---------------------------------------------------------------------------
@PRUEBAS
class CalendarioDelTelefonoTests(BaseTestCase):
    def test_el_ics_de_un_evento(self):
        junta = evento('Junta de padres', COLEGIO, lugar='Auditorio')
        respuesta = self.client.get(reverse('agenda:evento_ics', args=[junta.pk]))
        self.assertEqual(respuesta['Content-Type'], 'text/calendar; charset=utf-8')
        texto = respuesta.content.decode()
        self.assertIn('BEGIN:VEVENT', texto)
        self.assertIn('SUMMARY:Junta de padres', texto)
        self.assertIn('LOCATION:Auditorio', texto)

    def test_el_ics_de_un_evento_que_no_ve_es_404(self):
        de_primaria = evento('De primaria', 'PRIMARIA')
        self.client.force_login(self.sin_permisos)
        self.assertEqual(self.client.get(reverse('agenda:evento_ics', args=[de_primaria.pk])).status_code, 404)

    def test_la_suscripcion_trae_su_agenda_sin_sesion_y_se_puede_cambiar_el_enlace(self):
        hoy = timezone.localdate()
        evento('Del colegio', COLEGIO, inicio=hoy + timedelta(days=10))
        evento('De primaria', 'PRIMARIA', inicio=hoy + timedelta(days=10))
        self.client.force_login(self.sin_permisos)
        pagina = self.client.get(reverse('agenda:suscripcion'))
        suscripcion = SuscripcionCalendario.objects.get(usuario=self.sin_permisos)
        self.assertIn(suscripcion.token, pagina.context['enlace'])
        self.assertTrue(pagina.context['webcal'].startswith('webcal://'))

        telefono = Client()
        respuesta = telefono.get(reverse('agenda:suscripcion_ics', args=[suscripcion.token]))
        self.assertEqual(respuesta.status_code, 200)
        texto = respuesta.content.decode()
        self.assertIn('SUMMARY:Del colegio', texto)
        self.assertNotIn('De primaria', texto)
        self.assertIn('REFRESH-INTERVAL', texto)
        suscripcion.refresh_from_db()
        self.assertIsNotNone(suscripcion.usada_en)

        # «Generar un enlace nuevo»: el anterior deja de funcionar
        self.client.post(reverse('agenda:suscripcion'))
        nueva = SuscripcionCalendario.objects.get(usuario=self.sin_permisos)
        self.assertNotEqual(nueva.token, suscripcion.token)
        self.assertEqual(telefono.get(reverse('agenda:suscripcion_ics', args=[suscripcion.token])).status_code, 404)
        self.assertEqual(telefono.get(reverse('agenda:suscripcion_ics', args=[nueva.token])).status_code, 200)

    def test_una_cuenta_desactivada_o_sin_acceso_al_portal_no_recibe_nada(self):
        telefono = Client()
        de_usuario = SuscripcionCalendario.objects.create(usuario=self.sin_permisos)
        self.sin_permisos.is_active = False
        self.sin_permisos.save()
        self.assertEqual(telefono.get(reverse('agenda:suscripcion_ics', args=[de_usuario.token])).status_code, 404)
        tutor = crear_tutor(usuario='rosa.mora', acceso_portal=False)
        de_tutor = SuscripcionCalendario.objects.create(tutor=tutor)
        self.assertEqual(telefono.get(reverse('agenda:suscripcion_ics', args=[de_tutor.token])).status_code, 404)
        self.assertEqual(telefono.get(reverse('agenda:suscripcion_ics', args=['no-existe'])).status_code, 404)

    def test_la_suscripcion_en_el_portal(self):
        tutor = crear_tutor(usuario='rosa.mora')
        self.client.logout()
        entrar_al_portal(self.client, portales.TUTOR, tutor)
        self.assertEqual(self.client.get(reverse('portal_tutores:agenda:suscripcion')).status_code, 200)
        suscripcion = SuscripcionCalendario.objects.get(tutor=tutor)
        self.assertEqual(Client().get(reverse('agenda:suscripcion_ics', args=[suscripcion.token])).status_code, 200)


# ---------------------------------------------------------------------------
# Recordatorios de los eventos importantes
# ---------------------------------------------------------------------------
@PRUEBAS
class RecordatoriosTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.hoy = timezone.localdate()
        ciclo = ciclo_actual_de_prueba()
        self.lucia = crear_alumno(nombre='Lucía')
        inscribir_antes(self.lucia, ciclo, crear_grado('PRIMARIA', 1))
        self.ana = crear_tutor(nombre='Ana', usuario='ana.campos')
        vincular(self.ana, self.lucia)

    def test_un_evento_importante_de_manana_se_recuerda_una_vez_a_quien_lo_ve(self):
        importante = evento('Festival', 'PRIMARIA', inicio=self.hoy + timedelta(days=1), importante=True)
        evento('Normal', 'PRIMARIA', inicio=self.hoy + timedelta(days=1))
        evento('Lejano', 'PRIMARIA', inicio=self.hoy + timedelta(days=5), importante=True)
        with mock.patch('Agenda.recordatorios._push') as push:
            self.assertEqual(recordatorios.generar(), 1)
            self.assertEqual(recordatorios.generar(), 0)
        push.assert_called_once()
        importante.refresh_from_db()
        self.assertIsNotNone(importante.recordatorio_en)
        avisos = AvisoAgenda.objects.filter(evento=importante)
        self.assertTrue(avisos.filter(usuario=self.admin).exists())
        self.assertTrue(avisos.filter(tutor=self.ana).exists())
        self.assertTrue(avisos.filter(alumno=self.lucia).exists())
        self.assertFalse(avisos.filter(usuario=self.sin_permisos).exists())   # sin el nivel, no lo ve

    def test_el_aviso_aparece_en_la_campana_y_queda_visto_al_abrir_la_agenda(self):
        evento('Festival', COLEGIO, inicio=self.hoy + timedelta(days=1), importante=True)
        with mock.patch('Agenda.recordatorios._push'):
            recordatorios.generar()
        respuesta = self.client.get(reverse('cuenta:perfil'))
        self.assertContains(respuesta, 'data-agenda-sin-ver="1"')
        self.assertContains(respuesta, 'Mañana: Festival')
        self.client.get(CALENDARIO)
        self.assertContains(self.client.get(reverse('cuenta:perfil')), 'data-agenda-sin-ver="0"')

    def test_en_el_portal_de_tutores_tambien(self):
        evento('Festival', 'PRIMARIA', inicio=self.hoy, importante=True)
        with mock.patch('Agenda.recordatorios._push'):
            recordatorios.generar()
        self.client.logout()
        entrar_al_portal(self.client, portales.TUTOR, self.ana)
        respuesta = self.client.get(reverse('portal_tutores:inicio'))
        self.assertContains(respuesta, 'data-agenda-sin-ver="1"')
        self.assertContains(respuesta, 'Hoy: Festival')

    def test_un_evento_importante_registrado_para_manana_se_recuerda_al_guardarlo(self):
        with mock.patch('Agenda.recordatorios._push'), self.captureOnCommitCallbacks(execute=True):
            self.client.post(NUEVO, datos_del_evento(fecha_inicio=f'{self.hoy + timedelta(days=1):%Y-%m-%d}', importante='on'))
        nuevo = EventoAgenda.objects.get()
        self.assertIsNotNone(nuevo.recordatorio_en)
        self.assertTrue(AvisoAgenda.objects.filter(evento=nuevo, tutor=self.ana).exists())

    def test_si_cambia_de_fecha_se_vuelve_a_recordar(self):
        festival = evento('Festival', 'PRIMARIA', inicio=self.hoy + timedelta(days=1), importante=True)
        with mock.patch('Agenda.recordatorios._push'):
            recordatorios.generar()
        nueva = self.hoy + timedelta(days=10)
        self.client.post(reverse('agenda:editar', args=[festival.pk]), datos_del_evento(
            titulo='Festival', fecha_inicio=f'{nueva:%Y-%m-%d}', importante='on'))
        festival.refresh_from_db()
        self.assertEqual(festival.fecha_inicio, nueva)
        self.assertIsNone(festival.recordatorio_en)
        self.assertFalse(AvisoAgenda.objects.filter(evento=festival).exists())

    def test_el_comando_para_el_cron(self):
        from io import StringIO

        from django.core.management import call_command
        evento('Festival', COLEGIO, inicio=self.hoy + timedelta(days=1), importante=True)
        salida = StringIO()
        with mock.patch('Agenda.recordatorios._push'):
            call_command('recordatorios_de_agenda', stdout=salida)
        self.assertIn('Eventos recordados: 1', salida.getvalue())


# ---------------------------------------------------------------------------
# Eventos que se repiten
# ---------------------------------------------------------------------------
@PRUEBAS
class SeriesTests(BaseTestCase):
    def test_las_fechas_de_cada_repeticion(self):
        casos = {
            reglas.SEMANAL: (date(2026, 11, 4), date(2026, 11, 25), [date(2026, 11, 4), date(2026, 11, 11), date(2026, 11, 18), date(2026, 11, 25)]),
            reglas.QUINCENAL: (date(2026, 11, 4), date(2026, 12, 2), [date(2026, 11, 4), date(2026, 11, 18), date(2026, 12, 2)]),
            # El 31: los meses sin día 31 se saltan
            reglas.MENSUAL_DIA: (date(2027, 1, 31), date(2027, 5, 31), [date(2027, 1, 31), date(2027, 3, 31), date(2027, 5, 31)]),
            # El primer lunes
            reglas.MENSUAL_ORDINAL: (date(2026, 11, 2), date(2027, 2, 28), [date(2026, 11, 2), date(2026, 12, 7), date(2027, 1, 4), date(2027, 2, 1)]),
            # El último viernes
            reglas.MENSUAL_ULTIMO: (date(2026, 10, 30), date(2027, 1, 31), [date(2026, 10, 30), date(2026, 11, 27), date(2026, 12, 25), date(2027, 1, 29)]),
        }
        for repetir, (inicio, hasta, esperadas) in casos.items():
            with self.subTest(repetir):
                self.assertEqual(reglas.fechas_de_la_serie(inicio, repetir, hasta), esperadas)
        self.assertEqual(reglas.texto_de_repeticion(date(2026, 11, 2), reglas.MENSUAL_ORDINAL, date(2027, 2, 28)),
                         'Cada mes, el primer lunes hasta el 28 de febrero de 2027')
        self.assertEqual(len(reglas.fechas_de_la_serie(date(2026, 1, 1), reglas.SEMANAL, date(2030, 1, 1))), reglas.MAXIMO_DE_LA_SERIE)

    def test_registrar_una_serie_saltando_los_dias_sin_clases(self):
        DiaNoLectivo.registrar(date(2026, 11, 18), 'Consejo técnico', ['PRIMARIA'])
        respuesta = self.client.post(NUEVO, datos_del_evento(repetir=reglas.SEMANAL, repetir_hasta='2026-12-02', saltar_sin_clases='on'))
        self.assertEqual(respuesta.status_code, 302)
        serie = list(EventoAgenda.objects.order_by('fecha_inicio'))
        self.assertEqual([e.fecha_inicio for e in serie], [date(2026, 11, 4), date(2026, 11, 11), date(2026, 11, 25), date(2026, 12, 2)])
        self.assertEqual(len({e.serie for e in serie}), 1)
        self.assertIsNotNone(serie[0].serie)
        self.assertEqual(serie[0].repeticion, 'Cada miércoles hasta el 2 de diciembre de 2026')
        self.assertEqual(LogEntry.objects.filter(content_type__model='eventoagenda').count(), 1)
        # Sin saltar, también ese día
        EventoAgenda.objects.all().delete()
        self.client.post(NUEVO, datos_del_evento(repetir=reglas.SEMANAL, repetir_hasta='2026-12-02'))
        self.assertEqual(EventoAgenda.objects.count(), 5)

    def test_validaciones_de_la_repeticion(self):
        casos = {
            'sin fecha final': datos_del_evento(repetir=reglas.SEMANAL),
            'antes del inicio': datos_del_evento(repetir=reglas.SEMANAL, repetir_hasta='2026-11-01'),
            'más de un año': datos_del_evento(repetir=reglas.SEMANAL, repetir_hasta='2027-12-01'),
        }
        for caso, datos in casos.items():
            with self.subTest(caso):
                respuesta = self.client.post(NUEVO, datos)
                self.assertEqual(respuesta.status_code, 200)
                self.assertIn('repetir_hasta', respuesta.context['form'].errors)
        # «El último miércoles» solo si lo es (el 4 de noviembre no); «el quinto» nunca (el 30 de diciembre lo es)
        casos = {
            'no es el último': datos_del_evento(repetir=reglas.MENSUAL_ULTIMO, repetir_hasta='2027-03-01'),
            'es el quinto': datos_del_evento(repetir=reglas.MENSUAL_ORDINAL, fecha_inicio='2026-12-30', repetir_hasta='2027-03-01'),
        }
        for caso, datos in casos.items():
            with self.subTest(caso):
                respuesta = self.client.post(NUEVO, datos)
                self.assertEqual(respuesta.status_code, 200)
                self.assertIn('repetir', respuesta.context['form'].errors)
        self.assertFalse(EventoAgenda.objects.exists())
        self.client.post(NUEVO, datos_del_evento(repetir=reglas.MENSUAL_ULTIMO, fecha_inicio='2026-11-25', repetir_hasta='2027-01-31'))
        self.assertEqual(list(EventoAgenda.objects.order_by('fecha_inicio').values_list('fecha_inicio', flat=True)),
                         [date(2026, 11, 25), date(2026, 12, 30), date(2027, 1, 27)])

    def crear_serie(self):
        self.client.post(NUEVO, datos_del_evento(repetir=reglas.SEMANAL, repetir_hasta='2026-12-02'))
        return list(EventoAgenda.objects.order_by('fecha_inicio'))

    def test_corregir_uno_o_ese_y_los_siguientes(self):
        serie = self.crear_serie()
        segundo = serie[1]
        formulario = self.client.get(reverse('agenda:editar', args=[segundo.pk])).context['form']
        self.assertTrue(formulario.es_de_una_serie)
        self.assertNotIn('repetir', formulario.fields)
        self.client.post(reverse('agenda:editar', args=[segundo.pk]), datos_del_evento(
            titulo='Taller de escritura', fecha_inicio='2026-11-11', lugar='Aula 3', toda_la_serie='on'))
        titulos = list(EventoAgenda.objects.order_by('fecha_inicio').values_list('titulo', 'lugar', 'fecha_inicio'))
        self.assertEqual(titulos[0][:2], ('Taller de lectura', 'Biblioteca'))
        self.assertEqual({t[:2] for t in titulos[1:]}, {('Taller de escritura', 'Aula 3')})
        self.assertEqual([t[2] for t in titulos], [e.fecha_inicio for e in serie])   # las fechas no cambian
        # Solo ese
        self.client.post(reverse('agenda:editar', args=[serie[4].pk]), datos_del_evento(titulo='Último', fecha_inicio='2026-12-02'))
        self.assertEqual(EventoAgenda.objects.get(pk=serie[3].pk).titulo, 'Taller de escritura')
        self.assertEqual(EventoAgenda.objects.get(pk=serie[4].pk).titulo, 'Último')

    def test_eliminar_uno_o_ese_y_los_siguientes(self):
        serie = self.crear_serie()
        pagina = self.client.get(reverse('agenda:eliminar', args=[serie[2].pk]))
        self.assertEqual(pagina.context['siguientes'], 3)
        self.assertContains(pagina, 'name="alcance" value="siguientes"')
        self.client.post(reverse('agenda:eliminar', args=[serie[4].pk]))
        self.assertEqual(EventoAgenda.objects.count(), 4)
        self.client.post(reverse('agenda:eliminar', args=[serie[2].pk]), {'alcance': 'siguientes'})
        self.assertEqual(list(EventoAgenda.objects.order_by('fecha_inicio').values_list('pk', flat=True)), [serie[0].pk, serie[1].pk])
        self.assertIn('y 1 siguiente de su serie', LogEntry.objects.filter(action_flag=DELETION).latest('pk').change_message)

    def test_el_detalle_dice_como_se_repite(self):
        serie = self.crear_serie()
        detalle = self.client.get(CALENDARIO, {'evento': serie[0].pk})
        self.assertContains(detalle, 'Cada miércoles hasta el 2 de diciembre de 2026')
        self.assertEqual(detalle.context['de_la_serie'], 5)
