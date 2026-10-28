"""Mejoras de las reuniones con familias (pedido del 2026-10-28): los horarios libres sugeridos al programar, «Agregar
a mi calendario» (.ics), las indicaciones para la familia, el «Leí la minuta y los acuerdos» y el avance de los acuerdos
desde el portal, «Escribir» a quien atenderá, las solicitudes que esperan demasiado, los reportes y el Excel, la agenda
del día para imprimir y registrar la reunión desde la ficha del estudiante o un caso de Conducta."""
from datetime import datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from Alumnos.models import DiaNoLectivo
from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase, crear_rol, hoy, momento
from Usuarios.seguridad import asignar_rol

from . import notificaciones, reglas
from .alcance import PARTICIPAR
from .disponibilidad import horarios_libres
from .models import (
    AUSENTE, Acuerdo, EventoReunion, Minuta, MotivoReunion, NotificacionReunion, Reunion, SeguimientoAcuerdo, TutorEnReunion,
)
from .reglas import ReglaRota
from .tests import Colegio, entrar_al_portal

XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


class ConReunion(Colegio):
    def realizar(self, reunion):
        """La inicia el día de la cita (con todos presentes) y registra la minuta."""
        self.el_dia_de_la_cita()
        reglas.iniciar(reunion, presentes=set(reunion.participantes.values_list('pk', flat=True)),
                       tutores_presentes=set(reunion.tutores.values_list('pk', flat=True)), usuario=self.directora)
        reglas.finalizar(self.refrescar(reunion), datos={'inicio_real': time(10, 0), 'fin_real': time(10, 30), 'temas': 'Tareas',
                                                         'resumen': 'RESUMEN', 'notas_internas': ''}, presentes_toda=set(), usuario=self.directora,
                         puede_confidencial=True)
        return self.refrescar(reunion)

    def acuerdo(self, reunion, quien='FAMILIA', compartido=True):
        return reglas.guardar_acuerdo(reunion, datos={'descripcion': f'Acuerdo de {quien}', 'quien': quien, 'responsable': self.directora,
                                                      'responsable_texto': '', 'fecha_limite': hoy() + timedelta(days=10),
                                                      'compartido': compartido}, usuario=self.directora)

    def solicitada_hace(self, dias, prioridad=Reunion.NORMAL, responsable=None, desde=None):
        reunion = self.solicitud(responsable=responsable)
        creada = timezone.make_aware(datetime.combine((desde or hoy()) - timedelta(days=dias), time(10)))
        Reunion.objects.filter(pk=reunion.pk).update(creada=creada, prioridad=prioridad)
        return self.refrescar(reunion)


# ---------------------------------------------------------------------------
# Horarios libres sugeridos
# ---------------------------------------------------------------------------
@PRUEBAS
class HorariosLibresTests(ConReunion, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()
        self.reunion = self.solicitud(docentes=[self.marta], acompanante=self.directora, area=Reunion.DOCENTE)
        self.temprano = momento(7, 0, self.dia)   # el lunes de la cita, antes de abrir

    def ocupar(self, inicio, fin, sala=None, responsable=None):
        otra = self.solicitud(responsable=responsable or self.directora, alumnos=[self.leo], tutor=self.rosa)
        self.programar(otra, inicio=inicio, fin=fin, sala=sala or self.sala)
        return otra

    def test_sin_clases_del_docente_ni_otras_reuniones_del_personal(self):
        self.ocupar((9, 0), (9, 30))   # la directora (acompañante) tiene otra reunión
        sugeridos = horarios_libres(self.reunion, ahora=self.temprano)
        # Marta da clase de 8:00 a 9:00; la directora está ocupada de 9:00 a 9:30
        self.assertEqual([(h['fecha'], h['inicio']) for h in sugeridos[:2]], [(self.dia, time(9, 30)), (self.dia, time(9, 45))])
        self.assertEqual(sugeridos[0]['fin'], time(10, 0))
        self.assertTrue(all(not h['de_la_familia'] for h in sugeridos))
        self.assertLessEqual(sum(1 for h in sugeridos if h['fecha'] == self.dia), 2)   # a lo más dos por día
        self.assertEqual(len(sugeridos), 6)

    def test_otra_sala_si_la_primera_esta_ocupada(self):
        otro = self.solicitud(responsable=self.coordinador, alumnos=[self.leo], tutor=self.rosa)
        self.programar(otro, inicio=(9, 0), fin=(10, 0), sala=self.sala)
        primeras = horarios_libres(self.reunion, ahora=self.temprano)[:1]
        sala_9 = primeras[0]['sala']
        self.assertEqual(primeras[0]['inicio'], time(9, 0))
        self.assertNotEqual(sala_9, self.sala)   # la Dirección está ocupada de 9:00 a 10:00

    def test_primero_lo_que_propuso_el_tutor(self):
        manana = self.dia + timedelta(days=1)
        self.reunion.propuestas = [{'fecha': manana.isoformat(), 'desde': '12:00', 'hasta': '13:00'},
                                   {'fecha': (self.dia - timedelta(days=3)).isoformat(), 'desde': '', 'hasta': ''}]   # ya pasó
        self.reunion.save(update_fields=['propuestas'])
        primero = horarios_libres(self.reunion, ahora=self.temprano)[0]
        self.assertEqual((primero['fecha'], primero['inicio'], primero['de_la_familia']), (manana, time(12, 0), True))

    def test_se_saltan_los_dias_sin_clases(self):
        DiaNoLectivo.registrar(self.dia, 'Consejo técnico')
        sugeridos = horarios_libres(self.reunion, ahora=self.temprano)
        self.assertTrue(sugeridos)
        self.assertNotIn(self.dia, [h['fecha'] for h in sugeridos])

    def test_al_programar_se_ofrecen_y_se_guardan_las_indicaciones(self):
        self.client.force_login(self.recepcion)
        respuesta = self.client.get(reverse('reuniones:programar', args=[self.reunion.pk]))
        self.assertTrue(respuesta.context['sugeridos'])
        self.assertContains(respuesta, 'Horarios libres para todos')
        self.assertContains(respuesta, 'data-reuniones-sugeridos')
        self.client.post(reverse('reuniones:programar', args=[self.reunion.pk]), {
            'fecha': self.dia.isoformat(), 'hora_inicio': '11:00', 'hora_fin': '11:30', 'sala': self.sala.pk,
            'indicaciones': 'Trae la boleta firmada.'})
        reunion = self.refrescar(self.reunion)
        self.assertEqual((reunion.estado, reunion.indicaciones), (Reunion.PROGRAMADA, 'Trae la boleta firmada.'))
        aviso = NotificacionReunion.objects.get(tutor=self.ana, reunion=reunion)
        self.assertIn('Trae la boleta firmada.', aviso.texto)


# ---------------------------------------------------------------------------
# .ics e indicaciones
# ---------------------------------------------------------------------------
@PRUEBAS
class CalendarioEIndicacionesTests(ConReunion, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()
        self.reunion = self.solicitud(responsable=self.directora)

    def test_el_ics_de_la_cita_para_el_personal_y_la_familia_sin_el_motivo(self):
        self.client.force_login(self.recepcion)
        self.assertEqual(self.client.get(reverse('reuniones:calendario_ics', args=[self.reunion.pk])).status_code, 404)   # sin fecha
        self.programar(self.reunion)
        reglas.cambiar_indicaciones(self.refrescar(self.reunion), texto='Preséntate en recepción.', usuario=self.recepcion)
        respuesta = self.client.get(reverse('reuniones:calendario_ics', args=[self.reunion.pk]))
        self.assertEqual(respuesta['Content-Type'], 'text/calendar; charset=utf-8')
        texto = respuesta.content.decode()
        self.assertIn(f'UID:reunion-r{self.reunion.pk}@cisahuayo', texto)
        self.assertIn('SUMMARY:Reunión con familia · Ana Campos', texto)
        self.assertNotIn('Desempeño', texto)
        self.assertNotIn('matemáticas', texto)

        self.client.logout()
        entrar_al_portal(self.client, self.ana)
        familia = self.client.get(reverse('portal_tutores:reuniones:calendario_ics', args=[self.reunion.pk])).content.decode()
        self.assertIn('SUMMARY:Cita en el colegio · Dirección', familia)
        self.assertIn('Preséntate en recepción.', familia)
        self.assertNotIn('Desempeño', familia)
        entrar_al_portal(self.client, self.rosa)
        self.assertEqual(self.client.get(reverse('portal_tutores:reuniones:calendario_ics', args=[self.reunion.pk])).status_code, 404)

    def test_cambiar_las_indicaciones_avisa_a_la_familia_y_se_ven_en_su_portal(self):
        self.programar(self.reunion)
        NotificacionReunion.objects.all().delete()
        self.client.force_login(self.recepcion)
        self.client.post(reverse('reuniones:indicaciones', args=[self.reunion.pk]), {'indicaciones': 'Llega 10 minutos antes.'})
        reunion = self.refrescar(self.reunion)
        self.assertEqual(reunion.indicaciones, 'Llega 10 minutos antes.')
        self.assertTrue(reunion.eventos.filter(tipo=EventoReunion.INDICACIONES).exists())
        self.assertEqual(NotificacionReunion.objects.get(tutor=self.ana).titulo, 'Nuevas indicaciones para tu cita en el colegio')
        with self.assertRaises(ReglaRota):   # sin cambios
            reglas.cambiar_indicaciones(reunion, texto='Llega 10 minutos antes.', usuario=self.recepcion)
        # El recordatorio de la familia también las lleva
        nuevas = notificaciones.generar_para(tutor=self.ana, ahora=momento(9, 0, self.dia))
        self.assertIn('Llega 10 minutos antes.', nuevas[0].texto)
        self.client.logout()
        entrar_al_portal(self.client, self.ana)
        detalle = self.client.get(reverse('portal_tutores:reuniones:detalle', args=[self.reunion.pk]))
        self.assertContains(detalle, 'Llega 10 minutos antes.')
        self.assertContains(detalle, reverse('portal_tutores:reuniones:calendario_ics', args=[self.reunion.pk]))

    def test_un_docente_no_cambia_las_indicaciones(self):
        reunion = self.solicitud(docentes=[self.marta], acompanante=self.directora, area=Reunion.DOCENTE)
        self.client.force_login(self.marta)
        self.assertEqual(self.client.post(reverse('reuniones:indicaciones', args=[reunion.pk]), {'indicaciones': 'X'}).status_code, 403)


# ---------------------------------------------------------------------------
# Desde el portal: enterado, avance de los acuerdos y escribir
# ---------------------------------------------------------------------------
@PRUEBAS
class DesdeElPortalTests(ConReunion, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()
        self.reunion = self.solicitud(responsable=self.directora)
        self.programar(self.reunion)

    def test_lei_la_minuta_queda_como_constancia_hasta_que_se_edita(self):
        self.client.logout()
        entrar_al_portal(self.client, self.ana)
        url = reverse('portal_tutores:reuniones:enterado', args=[self.reunion.pk])
        self.client.post(url)   # todavía no hay minuta
        self.assertIsNone(TutorEnReunion.objects.get(reunion=self.reunion, tutor=self.ana).enterado_minuta_en)
        reunion = self.realizar(self.reunion)
        detalle = self.client.get(reverse('portal_tutores:reuniones:detalle', args=[reunion.pk]))
        self.assertContains(detalle, 'Leí la minuta y los acuerdos')
        self.client.post(url)
        invitado = TutorEnReunion.objects.get(reunion=reunion, tutor=self.ana)
        self.assertIsNotNone(invitado.enterado_minuta_en)
        self.assertTrue(reunion.eventos.filter(tipo=EventoReunion.ENTERADO, tutor=self.ana).exists())
        self.assertContains(self.client.get(reverse('portal_tutores:reuniones:detalle', args=[reunion.pk])), 'Confirmaste que leíste la minuta')
        self.assertEqual(self.client.post(url).status_code, 302)   # otra vez: solo un aviso
        self.assertEqual(reunion.eventos.filter(tipo=EventoReunion.ENTERADO).count(), 1)

        # El personal lo ve en la reunión y en la minuta para la familia
        self.client.force_login(self.directora)
        self.assertContains(self.client.get(reverse('reuniones:detalle', args=[reunion.pk])), 'La familia la leyó en su portal')
        hoja = self.client.get(reverse('reuniones:minuta', args=[reunion.pk]))
        self.assertContains(hoja, 'La familia confirmó en su portal')
        self.assertNotContains(hoja, 'Pendiente de firma')

        # Si la minuta se edita después, hay que volver a confirmarla
        reglas.editar_minuta(self.refrescar(reunion), datos={'inicio_real': time(10, 0), 'fin_real': time(10, 40), 'temas': 'Tareas',
                                                            'resumen': 'Otro resumen'}, usuario=self.directora, puede_confidencial=True)
        Minuta.objects.filter(reunion=reunion).update(modificada_en=invitado.enterado_minuta_en + timedelta(minutes=5))   # el reloj de prueba no avanza
        self.assertEqual(reglas.enterados(self.refrescar(reunion)), [])
        self.client.logout()
        entrar_al_portal(self.client, self.ana)
        self.assertContains(self.client.get(reverse('portal_tutores:reuniones:detalle', args=[reunion.pk])), 'La minuta se actualizó')

        # Otra familia no
        entrar_al_portal(self.client, self.rosa)
        self.assertEqual(self.client.post(url).status_code, 404)

    def test_la_familia_reporta_avance_y_el_responsable_lo_revisa(self):
        reunion = self.realizar(self.reunion)
        de_la_familia = self.acuerdo(reunion)
        del_colegio = self.acuerdo(reunion, quien='ESCUELA')
        privado = self.acuerdo(reunion, compartido=False)
        NotificacionReunion.objects.all().delete()
        self.client.logout()
        entrar_al_portal(self.client, self.ana)
        detalle = self.client.get(reverse('portal_tutores:reuniones:detalle', args=[reunion.pk]))
        self.assertContains(detalle, reverse('portal_tutores:reuniones:avance', args=[de_la_familia.pk]))
        self.assertNotContains(detalle, reverse('portal_tutores:reuniones:avance', args=[del_colegio.pk]))

        foto = SimpleUploadedFile('tareas.pdf', b'%PDF-1.4 tareas', content_type='application/pdf')
        self.client.post(reverse('portal_tutores:reuniones:avance', args=[de_la_familia.pk]), {'nota': 'Ya revisamos las tareas', 'evidencia': foto})
        avance = SeguimientoAcuerdo.objects.get(acuerdo=de_la_familia)
        self.assertEqual((avance.tutor, avance.usuario, avance.nota, avance.por_revisar), (self.ana, None, 'Ya revisamos las tareas', True))
        self.assertTrue(avance.evidencia)
        de_la_familia.refresh_from_db()
        self.assertEqual(de_la_familia.estado, Acuerdo.PENDIENTE)   # no cambia hasta que el colegio lo revise
        self.assertEqual(NotificacionReunion.objects.get(usuario=self.directora).titulo, 'La familia reportó avance de un acuerdo')
        self.assertContains(self.client.get(reverse('portal_tutores:reuniones:detalle', args=[reunion.pk])), 'el colegio lo revisará')

        # Lo que no admite avance
        self.client.post(reverse('portal_tutores:reuniones:avance', args=[del_colegio.pk]), {'nota': 'Hecho'})
        self.client.post(reverse('portal_tutores:reuniones:avance', args=[de_la_familia.pk]), {'nota': '   '})
        self.assertEqual(SeguimientoAcuerdo.objects.count(), 1)
        self.assertEqual(self.client.post(reverse('portal_tutores:reuniones:avance', args=[privado.pk]), {'nota': 'X'}).status_code, 404)
        entrar_al_portal(self.client, self.rosa)
        self.assertEqual(self.client.post(reverse('portal_tutores:reuniones:avance', args=[de_la_familia.pk]), {'nota': 'X'}).status_code, 404)

        # El personal: por revisar en compromisos y en el seguimiento; al guardar queda revisado
        self.client.force_login(self.directora)
        compromisos = self.client.get(reverse('reuniones:compromisos'), {'estado': 'POR_REVISAR'})
        self.assertEqual([a.pk for a in compromisos.context['pagina']], [de_la_familia.pk])
        self.assertContains(self.client.get(reverse('reuniones:detalle', args=[reunion.pk])), 'Revisar el avance')
        self.assertContains(self.client.get(reverse('reuniones:seguimiento', args=[de_la_familia.pk])), 'Ya revisamos las tareas')
        self.client.post(reverse('reuniones:seguimiento', args=[de_la_familia.pk]), {'estado': Acuerdo.CUMPLIDO, 'nota': 'Revisado con la maestra'})
        avance.refresh_from_db()
        self.assertEqual((avance.por_revisar, avance.revisado_por), (False, self.directora))
        de_la_familia.refresh_from_db()
        self.assertEqual(de_la_familia.estado, Acuerdo.CUMPLIDO)
        self.assertFalse(self.client.get(reverse('reuniones:compromisos'), {'estado': 'POR_REVISAR'}).context['pagina'].object_list)

    def test_escribir_a_quien_atendera_abre_la_conversacion_con_el_folio(self):
        asignar_rol(self.marta, crear_rol('Docente con mensajes', {PARTICIPAR, 'Mensajes.usar'}))
        reunion = self.solicitud(docentes=[self.marta], acompanante=self.directora, area=Reunion.DOCENTE)
        self.client.logout()
        entrar_al_portal(self.client, self.ana)
        detalle = self.client.get(reverse('portal_tutores:reuniones:detalle', args=[reunion.pk]))
        self.assertEqual(detalle.context['escribir_a'], {self.marta.pk})   # da clase a Lucía; la directora no usa la mensajería
        self.assertContains(detalle, f'value="u:{self.marta.pk}"')
        respuesta = self.client.post(reverse('portal_tutores:mensajes:nueva'), {'destinatario': f'u:{self.marta.pk}',
                                                                               'asunto': f'Sobre la reunión {reunion.folio}'})
        self.assertIn('asunto=Sobre+la+reuni', respuesta['Location'])
        conversacion = self.client.get(respuesta['Location'])
        self.assertContains(conversacion, f'data-asunto="Sobre la reunión {reunion.folio}"')


# ---------------------------------------------------------------------------
# Solicitudes que esperan demasiado
# ---------------------------------------------------------------------------
@PRUEBAS
class EsperaTests(ConReunion, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()

    def test_dias_habiles_y_plazo(self):
        lunes = self.dia
        normal_vieja = self.solicitada_hace(7, desde=lunes)          # el lunes anterior: 5 días hábiles
        normal_reciente = self.solicitada_hace(3, desde=lunes)       # el viernes: 1 día hábil
        urgente = self.solicitada_hace(3, prioridad=Reunion.URGENTE, desde=lunes)
        programada = self.solicitada_hace(7, desde=lunes, responsable=self.directora)
        self.programar(programada)
        reuniones = reglas.esperas([normal_vieja, normal_reciente, urgente, self.refrescar(programada)], hoy=lunes)
        self.assertEqual([(r.dias_de_espera, r.espera_vencida) for r in reuniones], [(5, True), (1, False), (1, True), (None, False)])
        # Un día sin clases de todo el colegio no cuenta
        DiaNoLectivo.registrar(lunes - timedelta(days=6), 'Puente')
        self.assertEqual(reglas.esperas([normal_vieja], hoy=lunes)[0].dias_de_espera, 4)

    def test_en_el_panel_la_lista_y_el_detalle(self):
        vieja = self.solicitada_hace(14)
        self.solicitada_hace(0)
        self.client.force_login(self.recepcion)
        panel = self.client.get(reverse('reuniones:inicio'))
        self.assertEqual(dict((c, t) for c, _, t, *_ in panel.context['indicadores'])['esperan'], 1)
        lista = self.client.get(reverse('reuniones:lista'), {'estado': 'ESPERA'})
        self.assertEqual([r.pk for r in lista.context['pagina']], [vieja.pk])
        self.assertContains(lista, 'esperando')
        self.assertContains(self.client.get(reverse('reuniones:detalle', args=[vieja.pk])), 'Espera demasiado')

    def test_se_avisa_una_vez_a_quien_la_atiende(self):
        sin_responsable = self.solicitada_hace(14)
        con_responsable = self.solicitada_hace(14, responsable=self.directora)
        nuevas = notificaciones.generar_para(usuario=self.recepcion)
        self.assertEqual([n.reunion_id for n in nuevas if n.clave.startswith('espera:')], [sin_responsable.pk])
        self.assertEqual(notificaciones.generar_para(usuario=self.recepcion), [])
        # La directora: la suya y la que no tiene responsable (gestiona primaria)
        de_la_directora = [n for n in notificaciones.generar_para(usuario=self.directora) if n.clave.startswith('espera:')]
        self.assertCountEqual([n.reunion_id for n in de_la_directora], [con_responsable.pk, sin_responsable.pk])
        self.assertNotIn('Desempeño', de_la_directora[0].texto)   # sin el motivo
        # El subdirector (secundaria) no: no puede atender esas reuniones de primaria
        self.assertFalse([n for n in notificaciones.generar_para(usuario=self.subdirector) if n.clave.startswith('espera:')])
        # Un docente no recibe estos avisos
        self.assertFalse([n for n in notificaciones.generar_para(usuario=self.marta) if n.clave.startswith('espera:')])


# ---------------------------------------------------------------------------
# Reportes, Excel e imprimir el día
# ---------------------------------------------------------------------------
@PRUEBAS
class ReportesTests(ConReunion, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()
        self.inicio = hoy()   # antes de mover el reloj al día de la cita
        self.otro_motivo = MotivoReunion.objects.exclude(pk=self.motivo.pk).first()
        self.realizada = self.solicitud(responsable=self.directora)
        self.programar(self.realizada)
        self.cancelada = self.solicitud(responsable=self.directora, alumnos=[self.zoe])
        reglas.cancelar(self.cancelada, motivo='Ya no hace falta', usuario=self.directora)
        self.faltaron = self.solicitud(responsable=self.directora, alumnos=[self.leo], tutor=self.rosa)
        Reunion.objects.filter(pk=self.faltaron.pk).update(motivo=self.otro_motivo)
        self.programar(self.refrescar(self.faltaron), inicio=(11, 0), fin=(11, 30))

    def test_las_cifras_del_periodo(self):
        realizada = self.realizar(self.realizada)
        self.acuerdo(realizada)
        reglas.marcar_inasistencia(self.refrescar(self.faltaron), tutores_ausentes=set(self.faltaron.tutores.values_list('pk', flat=True)),
                                   participantes_ausentes=set(), nota='', usuario=self.directora)
        self.client.force_login(self.recepcion)
        respuesta = self.client.get(reverse('reuniones:reportes'), {'desde': (self.inicio - timedelta(days=1)).isoformat()})
        datos = respuesta.context
        self.assertEqual((datos['total'], datos['realizadas'], datos['no_realizadas'], datos['inasistencia']), (3, 1, 1, 50))
        self.assertEqual((datos['falto_familia'], datos['falto_personal']), (1, 0))
        motivos = {f['nombre']: f['total'] for f in datos['por_motivo']}
        self.assertEqual(motivos, {str(self.motivo): 2, str(self.otro_motivo): 1})
        self.assertEqual({f['nombre']: f['total'] for f in datos['por_nivel']}, {'Primaria': 2, 'Secundaria': 1})
        self.assertEqual((datos['acuerdos'], datos['cumplidos_porcentaje']), (1, 0))
        self.assertEqual(datos['con_programacion'], 2)
        self.assertEqual(datos['en_plazo_porcentaje'], 100)   # se programaron el mismo día
        self.assertContains(respuesta, 'Reportes de reuniones')
        excel = self.client.get(reverse('reuniones:reportes'), {'desde': self.inicio.isoformat(), 'formato': 'xlsx'})
        self.assertEqual(excel['Content-Type'], XLSX)
        self.assertTrue(excel.content.startswith(b'PK'))

    def test_un_docente_no_ve_los_reportes_ni_descarga_la_lista(self):
        self.client.force_login(self.marta)
        self.assertEqual(self.client.get(reverse('reuniones:reportes')).status_code, 403)
        self.assertEqual(self.client.get(reverse('reuniones:lista'), {'formato': 'xlsx'}).status_code, 403)

    def test_la_lista_en_excel_con_sus_filtros(self):
        self.client.force_login(self.recepcion)
        lista = self.client.get(reverse('reuniones:lista'), {'estado': Reunion.PROGRAMADA})
        self.assertContains(lista, 'Descargar en Excel (2)')
        excel = self.client.get(reverse('reuniones:lista'), {'estado': Reunion.PROGRAMADA, 'formato': 'xlsx'})
        self.assertEqual(excel['Content-Type'], XLSX)
        self.assertIn('attachment; filename="reuniones-', excel['Content-Disposition'])
        import io
        import zipfile
        hoja = zipfile.ZipFile(io.BytesIO(excel.content)).read('xl/worksheets/sheet1.xml').decode()
        self.assertIn(self.realizada.folio, hoja)
        self.assertNotIn(self.cancelada.folio, hoja)
        self.assertNotIn('matemáticas', hoja)   # ni la descripción ni las observaciones

    def test_imprimir_el_dia_por_sala(self):
        self.client.force_login(self.recepcion)
        hoja = self.client.get(reverse('reuniones:imprimir_dia'), {'fecha': self.dia.isoformat()})
        self.assertEqual(hoja.status_code, 200)
        for texto in (self.realizada.folio, self.faltaron.folio, 'Ana Campos', 'Rosa Mora', str(self.sala)):
            self.assertContains(hoja, texto)
        self.assertNotContains(hoja, self.cancelada.folio)
        self.assertNotContains(hoja, 'data-notificaciones')
        self.assertContains(self.client.get(reverse('reuniones:agenda'), {'vista': 'dia', 'fecha': self.dia.isoformat()}), 'Imprimir el día')
        # Un docente solo ve las suyas
        self.client.force_login(self.marta)
        self.assertNotContains(self.client.get(reverse('reuniones:imprimir_dia'), {'fecha': self.dia.isoformat()}), self.realizada.folio)


# ---------------------------------------------------------------------------
# Registrar desde la ficha del estudiante o un caso de Conducta
# ---------------------------------------------------------------------------
@PRUEBAS
class DesdeOtroModuloTests(ConReunion, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()
        self.client.force_login(self.recepcion)

    def test_desde_la_ficha_aparecen_sus_tutores_y_el_estudiante_ya_elegido(self):
        paso_1 = self.client.get(reverse('reuniones:nueva'), {'alumno': self.zoe.pk})
        self.assertEqual([t for t, _ in paso_1.context['encontrados']], [self.ana])
        self.assertContains(paso_1, f'?tutor={self.ana.pk}&amp;alumno={self.zoe.pk}')
        paso_2 = self.client.get(reverse('reuniones:nueva'), {'tutor': self.ana.pk, 'alumno': self.zoe.pk})
        self.assertEqual(paso_2.context['form']['alumnos'].value(), [str(self.zoe.pk)])
        # Un estudiante que no es de ese tutor no se marca
        otro = self.client.get(reverse('reuniones:nueva'), {'tutor': self.ana.pk, 'alumno': self.leo.pk})
        self.assertFalse(otro.context['form']['alumnos'].value())

    def test_desde_un_caso_de_conducta_trae_la_descripcion(self):
        caso = SimpleNamespace(pk=77, fecha=hoy())
        registros = MagicMock()
        registros.filter.return_value.first.return_value = caso
        with patch('Conducta.views.registros_de', return_value=registros):
            respuesta = self.client.get(reverse('reuniones:nueva'), {'tutor': self.ana.pk, 'alumno': self.lucia.pk, 'conducta': 77})
        self.assertIn(f'reporte de conducta del {hoy():%d/%m/%Y}', respuesta.context['form']['descripcion'].value())
        # Sin acceso al caso, no se usa
        registros.filter.return_value.first.return_value = None
        with patch('Conducta.views.registros_de', return_value=registros):
            respuesta = self.client.get(reverse('reuniones:nueva'), {'tutor': self.ana.pk, 'alumno': self.lucia.pk, 'conducta': 77})
        self.assertFalse(respuesta.context['form']['descripcion'].value())

    def test_el_enlace_en_la_ficha_del_estudiante(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('alumnos:detalle', args=[self.lucia.pk])), f'{reverse("reuniones:nueva")}?alumno={self.lucia.pk}')


@PRUEBAS
class AjustesTests(ConReunion, BaseTestCase):
    def test_el_plazo_se_configura(self):
        from .models import ConfiguracionReuniones
        respuesta = self.client.get(reverse('reuniones:ajustes'))
        self.assertContains(respuesta, 'lazo para programar una solicitud')
        datos = {'dias': ['0', '1', '2', '3', '4'], 'hora_apertura': '08:00', 'hora_cierre': '15:00', 'duracion': '30',
                 'recordatorio_horas': '24', 'aviso_acuerdos_dias': '2', 'espera_dias': '5'}
        self.client.post(reverse('reuniones:ajustes'), datos)
        self.assertEqual(ConfiguracionReuniones.actual().espera_dias, 5)


__all__ = ['AUSENTE']
