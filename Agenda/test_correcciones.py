"""Correcciones del diagnóstico de la agenda (2026-11-02): fechas imposibles en la dirección, filtros que conservan la
fecha, recordatorios que no se pierden, que respetan «Recibe notificaciones» y no salen de noche, series movidas;
para quién es un evento (familias, estudiantes, varios niveles, grados y grupos), cancelar y avisar de los cambios,
gestión por nivel, archivos, confirmación de asistencia, la semana en columnas, el ciclo escolar, los días sin clases
sombreados y sin repetir, y la integración con Comunicados y Asistencia."""
import shutil
import tempfile
from datetime import date, datetime, time, timedelta
from unittest import mock

from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from Alumnos.models import DiaNoLectivo, TutorAlumno
from CISAHUAYO import portales
from CISAHUAYO.pruebas import (
    PRUEBAS, BaseTestCase, ciclo_actual_de_prueba, crear_alumno, crear_grado, crear_grupo, crear_tutor, crear_usuario,
    grupo_de, inscribir_antes, vincular,
)
from Usuarios import catalogo
from Usuarios.models import PerfilUsuario

from . import calendario, recordatorios, reglas
from .fuentes import EventoExterno, Persona
from .models import COLEGIO, VACACIONES, VARIOS, AdjuntoEvento, AvisoAgenda, ConfirmacionAsistencia, EventoAgenda, NivelEvento
from .tests import entrar_al_portal, evento

CALENDARIO = reverse('agenda:calendario')
NUEVO = reverse('agenda:crear')
PORTAL = reverse('portal_tutores:agenda:calendario')


def datos(**cambios):
    valores = {
        'titulo': 'Festival', 'alcance': 'PRIMARIA', 'tipo': '', 'fecha_inicio': '2026-11-20', 'fecha_fin': '', 'todo_el_dia': 'on',
        'lugar': 'Patio', 'descripcion': '', 'para_familias': 'on', 'para_estudiantes': 'on', 'volver': f'{CALENDARIO}?mes=2026-11',
    }
    valores.update(cambios)
    return {clave: valor for clave, valor in valores.items() if valor is not None}


def ids(respuesta):
    return [int(dato['id']) for dato in respuesta.context['datos_eventos'] if dato['id'].isdigit()]


class Familias(BaseTestCase):
    """Lucía en 1.º A de primaria (tutora Ana), Leo en 2.º de primaria (tutor Beto) y Zoe en 1.º de secundaria (Ana)."""

    def setUp(self):
        super().setUp()
        self.client.raise_request_exception = False
        self.hoy = timezone.localdate()
        self.ciclo = ciclo_actual_de_prueba()
        self.primero = crear_grado('PRIMARIA', 1)
        self.primero_b = crear_grupo(self.primero, 'B')
        self.segundo = crear_grado('PRIMARIA', 2)
        self.secundaria = crear_grado('SECUNDARIA', 1)
        self.lucia = crear_alumno(nombre='Lucía', acceso_portal=True)
        self.leo = crear_alumno(nombre='Leo', acceso_portal=True)
        self.zoe = crear_alumno(nombre='Zoe', acceso_portal=True)
        inscribir_antes(self.lucia, self.ciclo, self.primero, grupo=grupo_de(self.primero))
        inscribir_antes(self.leo, self.ciclo, self.segundo, grupo=grupo_de(self.segundo))
        inscribir_antes(self.zoe, self.ciclo, self.secundaria, grupo=grupo_de(self.secundaria))
        self.ana = crear_tutor(nombre='Ana', usuario='ana.campos', acceso_portal=True)
        self.beto = crear_tutor(nombre='Beto', usuario='beto.ruiz', acceso_portal=True)
        vincular(self.ana, self.lucia)
        vincular(self.ana, self.zoe)
        vincular(self.beto, self.leo)

    def portal(self, tutor):
        cliente = Client(raise_request_exception=False)
        entrar_al_portal(cliente, portales.TUTOR, tutor)
        return cliente

    def estudiante(self, alumno):
        cliente = Client(raise_request_exception=False)
        entrar_al_portal(cliente, portales.ESTUDIANTE, alumno)
        return cliente


# ---------------------------------------------------------------------------
# Errores confirmados
# ---------------------------------------------------------------------------
@PRUEBAS
class DireccionTests(Familias):
    def test_una_fecha_imposible_en_la_direccion_no_es_un_error(self):
        for consulta in ({'vista': 'semana', 'dia': '2026-02-31'}, {'vista': 'lista', 'desde': '2026-13-45'},
                         {'vista': 'semana', 'dia': '9999-12-31'}, {'vista': 'semana', 'dia': '0001-01-01'}, {'vista': 'ciclo', 'dia': '2026-99-99'}):
            with self.subTest(consulta):
                self.assertEqual(self.client.get(CALENDARIO, consulta).status_code, 200)
        self.assertEqual(self.portal(self.ana).get(PORTAL, {'vista': 'semana', 'dia': '2026-02-31'}).status_code, 200)
        self.assertEqual(self.client.get(CALENDARIO, {'evento': '²'}).status_code, 404)
        self.assertEqual(self.client.get(NUEVO, {'copiar': '²', 'fecha': '2026-02-31'}).status_code, 200)

    def test_filtrar_conserva_la_semana_y_la_lista_que_se_ven(self):
        respuesta = self.client.get(CALENDARIO, {'vista': 'semana', 'dia': '2027-03-03'})
        self.assertContains(respuesta, '<input type="hidden" name="dia" value="2027-03-01">', html=True)
        self.assertIn('1 al 7 de marzo de 2027', self.client.get(CALENDARIO, {'vista': 'semana', 'dia': '2027-03-01', 'nivel': 'PRIMARIA'}).context['titulo'])
        lista = self.client.get(CALENDARIO, {'vista': 'lista', 'desde': '2027-01-10'})
        self.assertContains(lista, '<input type="hidden" name="desde" value="2027-01-10">', html=True)

    def test_desde_una_semana_mes_e_imprimir_van_al_mes_de_esa_semana(self):
        respuesta = self.client.get(CALENDARIO, {'vista': 'semana', 'dia': '2027-03-03'})
        self.assertEqual([url for clave, _, url in respuesta.context['vistas'] if clave == 'mes'], [f'{CALENDARIO}?mes=2027-03'])
        self.assertIn('mes=2027-03', respuesta.context['url_imprimir'])

    def test_lo_de_otros_modulos_sin_pagina_lleva_a_su_mes_no_a_un_error(self):
        dia = date(2026, 11, 16)
        DiaNoLectivo.registrar(dia, 'Revolución')
        respuesta = self.client.get(CALENDARIO, {'mes': '2026-11'})
        enlaces = [evento.url_en_agenda for semana in respuesta.context['semanas'] for tramo in semana.tramos
                   for evento in [tramo.evento] if getattr(evento, 'fuente', '') == 'sin_clases']
        self.assertEqual(enlaces, [f'{CALENDARIO}?mes=2026-11'])

    def test_mover_una_fecha_y_aplicar_a_los_siguientes_incluye_los_que_seguian(self):
        inicio = self.hoy + timedelta(days=7)
        serie = reglas.crear(EventoAgenda(titulo='Taller', alcance='PRIMARIA', fecha_inicio=inicio, fecha_fin=inicio), self.admin,
                             repetir=reglas.SEMANAL, hasta=inicio + timedelta(days=35))
        segundo = serie[1]
        segundo.fecha_inicio = segundo.fecha_fin = serie[4].fecha_inicio + timedelta(days=1)
        segundo.titulo = 'Taller corregido'
        self.assertEqual(reglas.guardar_cambios(segundo, self.admin, toda_la_serie=True), 4)
        self.assertEqual(list(EventoAgenda.objects.filter(serie=segundo.serie).order_by('fecha_inicio').values_list('titulo', flat=True)),
                         ['Taller'] + ['Taller corregido'] * 5)


# ---------------------------------------------------------------------------
# Recordatorios
# ---------------------------------------------------------------------------
@PRUEBAS
class RecordatoriosTests(Familias):
    def a_las(self, hora, minuto=0):
        return timezone.make_aware(datetime.combine(self.hoy, time(hora, minuto)))

    def test_si_falla_a_la_mitad_no_queda_marcado_y_se_vuelve_a_intentar(self):
        importante = evento('Festival', inicio=self.hoy + timedelta(days=1), importante=True)
        with mock.patch.object(recordatorios, 'audiencia', side_effect=RuntimeError('falla')), self.assertLogs('Agenda.recordatorios', 'ERROR'):
            self.assertEqual(recordatorios.generar(self.a_las(9)), 0)
        importante.refresh_from_db()
        self.assertIsNone(importante.recordatorio_en)
        with mock.patch('Agenda.recordatorios._push'):
            self.assertEqual(recordatorios.generar(self.a_las(9)), 1)
        self.assertTrue(AvisoAgenda.objects.filter(evento=importante, tutor=self.ana).exists())

    def test_no_salen_de_noche(self):
        evento('Festival', inicio=self.hoy + timedelta(days=1), importante=True)
        with mock.patch('Agenda.recordatorios._push'):
            self.assertEqual(recordatorios.generar(self.a_las(0, 5)), 0)
            self.assertEqual(recordatorios.generar(self.a_las(21, 30)), 0)
            self.assertEqual(recordatorios.generar(self.a_las(7, 0)), 1)

    def test_respetan_recibe_notificaciones(self):
        TutorAlumno.objects.filter(tutor=self.ana).update(recibe_notificaciones=False)
        _, tutores, _ = recordatorios.audiencia(evento('Festival', importante=True))
        self.assertNotIn(self.ana.pk, tutores)
        self.assertIn(self.beto.pk, tutores)

    def test_con_la_anticipacion_elegida(self):
        semana = evento('Kermés', inicio=self.hoy + timedelta(days=6), importante=True, recordar_dias=7)
        dia = evento('Junta', inicio=self.hoy + timedelta(days=6), importante=True, recordar_dias=1)
        with mock.patch('Agenda.recordatorios._push'):
            self.assertEqual(recordatorios.generar(self.a_las(10)), 1)
        self.assertTrue(AvisoAgenda.objects.filter(evento=semana).exists())
        self.assertFalse(AvisoAgenda.objects.filter(evento=dia).exists())

    def test_no_se_recuerda_un_evento_cancelado(self):
        evento('Festival', inicio=self.hoy + timedelta(days=1), importante=True, cancelado_en=timezone.now())
        self.assertEqual(recordatorios.generar(self.a_las(9)), 0)

    def test_las_consultas_no_crecen_con_cada_evento_del_colegio(self):
        for n in range(5):
            crear_usuario(f'personal{n}')
        del_colegio = evento('Honores', COLEGIO, importante=True)
        with self.assertNumQueries(3):
            recordatorios.audiencia(del_colegio)


# ---------------------------------------------------------------------------
# Para quién: familias, estudiantes, varios niveles, grados y grupos
# ---------------------------------------------------------------------------
@PRUEBAS
class ParaQuienTests(Familias):
    def test_un_evento_interno_solo_lo_ve_el_personal(self):
        interno = evento('Consejo técnico', inicio=self.hoy + timedelta(days=1), para_familias=False, para_estudiantes=False)
        self.assertNotIn(interno.pk, ids(self.portal(self.ana).get(PORTAL, {'vista': 'lista'})))
        self.assertNotIn(interno.pk, ids(self.estudiante(self.lucia).get(reverse('portal_estudiantes:agenda:calendario'), {'vista': 'lista'})))
        self.assertEqual(self.portal(self.ana).get(PORTAL, {'evento': interno.pk}).status_code, 404)
        docente = crear_usuario('maestra')
        PerfilUsuario.objects.filter(usuario=docente).update(niveles_retiros=['PRIMARIA'])
        self.client.force_login(docente)
        self.assertIn(interno.pk, ids(self.client.get(CALENDARIO, {'vista': 'lista'})))
        self.assertEqual(recordatorios.audiencia(interno)[1:], ([], []))

    def test_para_familias_pero_no_para_estudiantes(self):
        junta = evento('Junta de padres', inicio=self.hoy + timedelta(days=1), para_estudiantes=False)
        self.assertIn(junta.pk, ids(self.portal(self.ana).get(PORTAL, {'vista': 'lista'})))
        self.assertNotIn(junta.pk, ids(self.estudiante(self.lucia).get(reverse('portal_estudiantes:agenda:calendario'), {'vista': 'lista'})))

    def test_un_evento_de_varios_niveles_se_guarda_una_vez(self):
        self.client.post(NUEVO, datos(alcance=['SECUNDARIA', 'PREPARATORIA'], fecha_inicio=f'{self.hoy + timedelta(days=3):%Y-%m-%d}'))
        examen = EventoAgenda.objects.get()
        self.assertEqual((examen.alcance, examen.niveles_del_evento, examen.nombre_alcance), (VARIOS, ['SECUNDARIA', 'PREPARATORIA'], 'Secundaria y Bachillerato'))
        self.assertEqual(set(NivelEvento.objects.values_list('nivel', flat=True)), {'SECUNDARIA', 'PREPARATORIA'})
        self.assertIn(examen.pk, ids(self.portal(self.ana).get(PORTAL, {'vista': 'lista'})))     # Zoe va en secundaria
        self.assertNotIn(examen.pk, ids(self.portal(self.beto).get(PORTAL, {'vista': 'lista'})))
        self.assertIn(examen.pk, ids(self.client.get(CALENDARIO, {'vista': 'lista', 'nivel': 'SECUNDARIA'})))
        self.assertNotIn(examen.pk, ids(self.client.get(CALENDARIO, {'vista': 'lista', 'nivel': 'PRIMARIA'})))
        # Elegir los cuatro es «Todos los niveles»
        self.client.post(NUEVO, datos(titulo='Honores', alcance=['PREESCOLAR', 'PRIMARIA', 'SECUNDARIA', 'PREPARATORIA']))
        self.assertEqual(EventoAgenda.objects.get(titulo='Honores').alcance, COLEGIO)

    def test_solo_algunos_grados_o_grupos(self):
        manana = f'{self.hoy + timedelta(days=2):%Y-%m-%d}'
        self.client.post(NUEVO, datos(titulo='Excursión de 1.º', fecha_inicio=manana, grados=[self.primero.pk]))
        self.client.post(NUEVO, datos(titulo='Clase muestra de 1.º B', fecha_inicio=manana, grupos=[self.primero_b.pk]))
        excursion, clase = EventoAgenda.objects.get(titulo='Excursión de 1.º'), EventoAgenda.objects.get(titulo='Clase muestra de 1.º B')
        self.assertTrue(excursion.por_grupos)
        de_ana = ids(self.portal(self.ana).get(PORTAL, {'vista': 'lista'}))
        self.assertIn(excursion.pk, de_ana)          # Lucía va en 1.º A
        self.assertNotIn(clase.pk, de_ana)           # pero no en 1.º B
        self.assertNotIn(excursion.pk, ids(self.portal(self.beto).get(PORTAL, {'vista': 'lista'})))
        self.assertIn(clase.pk, ids(self.client.get(CALENDARIO, {'vista': 'lista'})))       # el personal lo ve igual
        self.assertEqual(recordatorios.tutores_del_evento(excursion), [self.ana.pk])
        # El filtro «Grado o grupo»
        filtrado = ids(self.client.get(CALENDARIO, {'vista': 'lista', 'curso': f'g{self.segundo.pk}'}))
        self.assertNotIn(excursion.pk, filtrado)
        self.assertIn(excursion.pk, ids(self.client.get(CALENDARIO, {'vista': 'lista', 'curso': f'r{self.primero_b.pk}'})))
        self.assertIn(clase.pk, ids(self.client.get(CALENDARIO, {'vista': 'lista', 'curso': f'r{self.primero_b.pk}'})))
        # Un grado de otro nivel no se acepta
        respuesta = self.client.post(NUEVO, datos(titulo='Mal', grados=[self.secundaria.pk]))
        self.assertIn('grados', respuesta.context['form'].errors)

    def test_pedir_confirmacion_exige_que_sea_para_las_familias(self):
        respuesta = self.client.post(NUEVO, datos(para_familias=None, pide_confirmacion='on'))
        self.assertIn('pide_confirmacion', respuesta.context['form'].errors)

    def test_el_tutor_sin_inscripciones_lee_un_aviso_para_familias(self):
        sola = crear_tutor(nombre='Sola', usuario='sola.tutora', acceso_portal=True)
        self.assertIn('Tus estudiantes no tienen inscripción', self.portal(sola).get(PORTAL).context['aviso_sin_niveles'])


# ---------------------------------------------------------------------------
# Cancelar y avisar de los cambios
# ---------------------------------------------------------------------------
@PRUEBAS
class CancelarYCambiosTests(Familias):
    def setUp(self):
        super().setUp()
        self.festival = evento('Festival', inicio=self.hoy + timedelta(days=5), lugar='Patio')

    def test_cancelar_lo_deja_visible_tachado_y_avisa(self):
        url = reverse('agenda:cancelar', args=[self.festival.pk])
        self.assertContains(self.client.get(url), '¿Cancelar «Festival»?')
        with mock.patch('Agenda.recordatorios._push'), self.captureOnCommitCallbacks(execute=True):
            self.client.post(url, {'motivo': 'Por lluvia', 'avisar': 'on', 'volver': CALENDARIO})
        self.festival.refresh_from_db()
        self.assertTrue(self.festival.cancelado)
        self.assertEqual(self.festival.motivo_cancelacion, 'Por lluvia')
        aviso = AvisoAgenda.objects.get(evento=self.festival, tutor=self.ana)
        self.assertEqual((aviso.tipo, aviso.texto), (AvisoAgenda.CANCELADO, 'Por lluvia'))
        campana = recordatorios.datos_de_la_campana(Persona(tutor=self.ana))
        self.assertEqual(campana['avisos'][0]['titulo'], 'Cancelado: Festival')
        familia = self.portal(self.ana)        # al abrir la agenda, el aviso queda visto
        dato = next(d for d in familia.get(PORTAL, {'vista': 'lista'}).context['datos_eventos'] if d['id'] == str(self.festival.pk))
        self.assertTrue(dato['cancelado'])
        self.assertIn('STATUS:CANCELLED', reglas.ics_de_evento(self.festival))
        # Reactivar
        self.client.post(reverse('agenda:reactivar', args=[self.festival.pk]))
        self.festival.refresh_from_db()
        self.assertFalse(self.festival.cancelado)

    def test_un_cambio_de_lugar_se_avisa_si_se_pide(self):
        url = reverse('agenda:editar', args=[self.festival.pk])
        fecha = f'{self.festival.fecha_inicio:%Y-%m-%d}'
        with mock.patch('Agenda.recordatorios._push'), self.captureOnCommitCallbacks(execute=True):
            self.client.post(url, datos(fecha_inicio=fecha, lugar='Auditorio', avisar_cambio='on'))
        aviso = AvisoAgenda.objects.get(evento=self.festival, tutor=self.ana)
        self.assertEqual((aviso.tipo, aviso.texto), (AvisoAgenda.CAMBIO, 'Nuevo lugar: Auditorio'))
        self.assertEqual(recordatorios.datos_de_la_campana(Persona(tutor=self.ana))['avisos'][0]['titulo'], 'Cambió: Festival')
        AvisoAgenda.objects.all().delete()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(url, datos(fecha_inicio=fecha, lugar='Gimnasio'))           # sin «Avisar del cambio»
            self.client.post(url, datos(fecha_inicio=fecha, lugar='Gimnasio', titulo='Gran festival', avisar_cambio='on'))   # sin cambio de lugar
        self.assertFalse(AvisoAgenda.objects.exists())


# ---------------------------------------------------------------------------
# Gestión por nivel
# ---------------------------------------------------------------------------
@PRUEBAS
class GestionPorNivelTests(Familias):
    def setUp(self):
        super().setUp()
        self.directora = crear_usuario('directora')
        PerfilUsuario.objects.filter(usuario=self.directora).update(niveles_retiros=['PRIMARIA'])
        self.directora.user_permissions.add(Permission.objects.get(content_type__app_label='Agenda', codename='gestionar_nivel'))
        self.client.force_login(self.directora)

    def test_registra_y_corrige_solo_lo_de_sus_niveles(self):
        formulario = self.client.get(NUEVO).context['form']
        self.assertEqual([clave for clave, _ in formulario.fields['alcance'].choices], ['PRIMARIA'])
        self.client.post(NUEVO, datos())
        propio = EventoAgenda.objects.get()
        self.assertEqual(self.client.get(reverse('agenda:editar', args=[propio.pk])).status_code, 200)
        ajeno = evento('Torneo', 'SECUNDARIA')
        del_colegio = evento('Honores', COLEGIO)
        for otro in (ajeno, del_colegio):
            for ruta in ('editar', 'cancelar', 'eliminar'):
                self.assertEqual(self.client.get(reverse(f'agenda:{ruta}', args=[otro.pk])).status_code, 403)
        self.assertIn('alcance', self.client.post(NUEVO, datos(alcance=COLEGIO)).context['form'].errors)
        detalle = self.client.get(CALENDARIO, {'vista': 'lista'}).context['datos_eventos']
        self.assertTrue(next(d for d in detalle if d['id'] == str(propio.pk)).get('editar'))

    def test_se_concede_desde_roles(self):
        permisos = {permiso for modulo in catalogo.MODULOS for funcion in modulo.funciones for permiso in funcion.permisos.values()}
        self.assertIn('Agenda.gestionar_nivel', permisos)


# ---------------------------------------------------------------------------
# Archivos y confirmación de asistencia
# ---------------------------------------------------------------------------
@PRUEBAS
class ArchivosYConfirmacionTests(Familias):
    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp()
        self.enterContext(override_settings(MEDIA_ROOT=self.media))

    def tearDown(self):
        shutil.rmtree(self.media, ignore_errors=True)
        super().tearDown()

    def test_los_archivos_solo_los_ve_quien_ve_el_evento(self):
        archivo = SimpleUploadedFile('permiso.pdf', b'%PDF-1.4 permiso', content_type='application/pdf')
        self.client.post(NUEVO, {**datos(), 'archivos': archivo})
        adjunto = AdjuntoEvento.objects.get()
        self.assertEqual((adjunto.nombre_original, adjunto.tipo), ('permiso.pdf', 'application/pdf'))
        self.assertEqual(self.client.get(reverse('agenda:adjunto', args=[adjunto.pk])).status_code, 200)
        self.assertEqual(self.portal(self.ana).get(reverse('portal_tutores:agenda:adjunto', args=[adjunto.pk])).status_code, 200)
        EventoAgenda.objects.update(alcance='SECUNDARIA')
        self.assertEqual(self.portal(self.beto).get(reverse('portal_tutores:agenda:adjunto', args=[adjunto.pk])).status_code, 404)
        malo = SimpleUploadedFile('virus.exe', b'MZ', content_type='application/octet-stream')
        self.assertTrue(self.client.post(NUEVO, {**datos(titulo='Otro'), 'archivos': malo}).context['form'].non_field_errors())

    def test_las_familias_confirman_su_asistencia(self):
        kermes = evento('Kermés', inicio=self.hoy + timedelta(days=3), pide_confirmacion=True)
        familia = self.portal(self.ana)
        url = reverse('portal_tutores:agenda:confirmar', args=[kermes.pk])
        self.assertContains(familia.get(PORTAL, {'evento': kermes.pk}), '¿Asistirán?')
        familia.post(url, {'asistira': 'si', 'personas': '3'})
        self.portal(self.beto).post(reverse('portal_tutores:agenda:confirmar', args=[kermes.pk]), {'asistira': 'no'})
        self.assertEqual(ConfirmacionAsistencia.objects.get(tutor=self.ana).personas, 3)
        resumen = self.client.get(CALENDARIO, {'evento': kermes.pk}).context['confirmaciones']
        self.assertEqual((resumen['si'], resumen['no'], resumen['personas'], resumen['sin_responder']), (1, 1, 3, 0))
        # Ya empezó: no se cambia
        EventoAgenda.objects.filter(pk=kermes.pk).update(fecha_inicio=self.hoy - timedelta(days=1), fecha_fin=self.hoy - timedelta(days=1))
        familia.post(url, {'asistira': 'no'})
        self.assertTrue(ConfirmacionAsistencia.objects.get(tutor=self.ana).asistira)


# ---------------------------------------------------------------------------
# Pantallas: mes, semana en columnas, ciclo escolar, días sin clases
# ---------------------------------------------------------------------------
@PRUEBAS
class PantallasTests(Familias):
    def test_los_eventos_de_un_dia_no_quedan_detras_de_los_de_varios_dias(self):
        lunes = date(2026, 11, 9)
        eventos = [evento(f'Examen {n}', inicio=lunes, fin=lunes + timedelta(days=4)) for n in range(3)]
        eventos += [evento(f'Junta {n}', inicio=lunes + timedelta(days=2), horas=(time(9 + n), time(10 + n))) for n in range(3)]
        semana = calendario.semanas(eventos, date(2026, 11, 1), date(2026, 11, 1))[2]
        self.assertEqual(semana.dias[2].ocultos, 0)
        self.assertEqual(len(semana.tramos), 6)

    def test_la_semana_en_columnas_dibuja_una_barra_por_evento_de_varios_dias(self):
        lunes = date(2026, 11, 9)
        evento('Exámenes', inicio=lunes, fin=lunes + timedelta(days=4))
        evento('Junta', inicio=lunes + timedelta(days=1), horas=(time(9), time(10)))
        semana = self.client.get(CALENDARIO, {'vista': 'semana', 'dia': '2026-11-11'}).context['semana']
        self.assertEqual([tramo.evento.titulo for tramo in semana.tramos], ['Exámenes'])
        self.assertEqual([e.titulo for e in semana.dias[1].de_un_dia], ['Junta'])

    def test_los_dias_sin_clases_se_sombrean_y_no_se_repiten_con_las_vacaciones(self):
        for nivel in ('PRIMARIA', 'SECUNDARIA'):
            DiaNoLectivo.objects.create(fecha=date(2026, 12, 21), nivel=nivel, motivo='Vacaciones')
        respuesta = self.client.get(CALENDARIO, {'mes': '2026-12'})
        dia = next(d for semana in respuesta.context['semanas'] for d in semana.dias if d.fecha == date(2026, 12, 21))
        self.assertEqual(dia.sin_clases, 'Vacaciones')
        self.assertTrue([d for d in respuesta.context['datos_eventos'] if d['id'].startswith('s')])
        evento('Vacaciones de invierno', COLEGIO, date(2026, 12, 21), date(2027, 1, 6), tipo=VACACIONES)
        respuesta = self.client.get(CALENDARIO, {'mes': '2026-12'})
        self.assertFalse([d for d in respuesta.context['datos_eventos'] if d['id'].startswith('s')])

    def test_el_ciclo_escolar_completo_y_su_impresion(self):
        evento('Festival', inicio=self.hoy + timedelta(days=10))
        respuesta = self.client.get(CALENDARIO, {'vista': 'ciclo'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertGreaterEqual(len(respuesta.context['meses']), 10)
        self.assertContains(respuesta, 'Festival')
        self.assertEqual(self.client.get(reverse('agenda:imprimir'), {'vista': 'ciclo'}).status_code, 200)

    def test_filtro_de_los_eventos_sin_tipo(self):
        sin_tipo = evento('Sin tipo', inicio=self.hoy + timedelta(days=1))
        festival = evento('Festival', inicio=self.hoy + timedelta(days=1), tipo='FESTIVAL')
        visibles = ids(self.client.get(CALENDARIO, {'vista': 'lista', 'tipo': reglas.OTRO}))
        self.assertIn(sin_tipo.pk, visibles)
        self.assertNotIn(festival.pk, visibles)

    def test_varios_dias_con_horario_es_un_solo_bloque(self):
        campamento = evento('Campamento', inicio=date(2026, 12, 7), fin=date(2026, 12, 9), horas=(time(9), time(14)))
        self.assertEqual(campamento.texto_de_horario, 'Desde las 09:00 del primer día a las 14:00 del último día')


# ---------------------------------------------------------------------------
# Comunicados, Asistencia y el calendario del teléfono
# ---------------------------------------------------------------------------
@PRUEBAS
class IntegracionTests(Familias):
    def test_avisar_con_un_comunicado_abre_el_formulario_lleno(self):
        festival = evento('Festival de otoño', inicio=self.hoy + timedelta(days=5), lugar='Patio', descripcion='Traer disfraz')
        detalle = self.client.get(CALENDARIO, {'evento': festival.pk})
        self.assertContains(detalle, 'Avisar con un comunicado')
        formulario = self.client.get(detalle.context['url_comunicado'])
        self.assertEqual(formulario.status_code, 200)
        self.assertContains(formulario, 'Festival de otoño')
        self.assertContains(formulario, f'name="evento_agenda" value="{festival.pk}"')

    def test_el_comunicado_ligado_no_se_repite_en_la_agenda(self):
        propio = evento('Festival', comunicado_id=None)
        propio.comunicado_id = 7
        externo = EventoExterno(clave='c7', fuente='comunicado', titulo='Festival', fecha_inicio=self.hoy, fecha_fin=self.hoy,
                                colores=('#000000', '#FFFFFF'), nombre_alcance='Comunicado')
        otro = EventoExterno(clave='c8', fuente='comunicado', titulo='Otro', fecha_inicio=self.hoy, fecha_fin=self.hoy,
                             colores=('#000000', '#FFFFFF'), nombre_alcance='Comunicado')
        self.assertEqual(reglas.sin_repetidos([propio], [externo, otro]), [otro])

    def test_registrar_en_asistencia_abre_el_formulario_de_dias_sin_clases_lleno(self):
        puente = evento('Puente', COLEGIO, date(2026, 11, 16), tipo=VACACIONES)
        url = self.client.get(CALENDARIO, {'evento': puente.pk}).context['url_sin_clases']
        respuesta = self.client.get(url)
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn('sin_clases_motivo=Puente', respuesta['Location'])
        pagina = self.client.get(respuesta['Location'])
        formulario = pagina.context['dia_form']
        self.assertEqual((formulario['motivo'].value(), formulario['desde'].value(), formulario['niveles'].value()), ('Puente', '2026-11-16', ['TODOS']))
        self.assertFalse(DiaNoLectivo.objects.exists())       # se registra hasta confirmarlo allá

    def test_en_el_calendario_del_telefono_una_reunion_no_lleva_el_nombre_de_la_familia(self):
        reunion = EventoExterno(clave='r1', fuente='reunion', titulo='Reunión con familia · Ana Campos', fecha_inicio=self.hoy,
                                fecha_fin=self.hoy, colores=('#000000', '#FFFFFF'), nombre_alcance='Reunión con familia · R-1')
        self.assertEqual(reglas._ics(reunion, '', privado=True).titulo, 'Reunión con familia · R-1')
        self.assertEqual(reglas._ics(reunion, '').titulo, 'Reunión con familia · Ana Campos')
