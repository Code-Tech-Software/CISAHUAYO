"""Justificaciones: listado, alta (un día o varios), edición, anulación y reactivación."""
import shutil
import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from Alumnos import asistencias as reglas
from Alumnos.models import DiaNoLectivo, Justificacion
from Asistencias.tests import url
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseAsistenciaTestCase,
    ciclo_cerrado_de_prueba,
    crear_alumno,
    crear_grado,
    inscribir_antes,
    lunes,
    materia_en_grado,
)

CARPETA = tempfile.mkdtemp(prefix='cisahuayo-pruebas-')


def tearDownModule():
    shutil.rmtree(CARPETA, ignore_errors=True)


def pdf(nombre='justificante.pdf', tamano=2048):
    return SimpleUploadedFile(nombre, b'%PDF-1.4 ' + b'0' * tamano, content_type='application/pdf')


class BaseJustificacionTests(BaseAsistenciaTestCase):
    hora = (10, 30)

    def setUp(self):
        super().setUp()
        self.dia = lunes() - timedelta(days=7)           # un lunes pasado
        self.materias = [self.mat.pk, self.esp.pk]

    def datos(self, **cambios):
        datos = {
            'alumno': self.alumno.pk, 'fecha_desde': self.dia.isoformat(), 'justifica_general': 'on', 'materias_modo': 'TODAS',
            'motivo': 'Cita médica', 'next': '',
        }
        datos.update(cambios)
        return {k: v for k, v in datos.items() if v is not None}

    def crear(self, **cambios):
        return self.client.post(url('justificacion_crear'), self.datos(**cambios), follow=True)


# ---------------------------------------------------------------------------
# Alta
# ---------------------------------------------------------------------------
@PRUEBAS
@override_settings(MEDIA_ROOT=CARPETA)
class CrearJustificacionTests(BaseJustificacionTests):
    def test_el_formulario_viene_con_el_dia_completo_por_omision(self):
        respuesta = self.client.get(url('justificacion_crear'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context['form'].initial['justifica_general'])
        self.assertEqual(respuesta.context['form'].initial['materias_modo'], 'TODAS')

    def test_viene_con_el_alumno_y_el_dia_cuando_se_llega_desde_una_falta(self):
        respuesta = self.client.get(url('justificacion_crear', alumno=self.alumno.pk, fecha=self.dia.isoformat()))
        self.assertEqual(respuesta.context['alumno'], self.alumno)
        self.assertEqual(respuesta.context['inscripcion'], self.inscripcion)
        self.assertEqual(respuesta.context['form'].initial['fecha_desde'], self.dia)
        self.assertEqual(sorted(a.materia.clave for a in respuesta.context['form'].fields['materias'].queryset), ['CIE', 'ESP', 'MAT'])
        for materia in ('Mat', 'Esp', 'Cie'):
            self.assertContains(respuesta, materia)

    def test_justifica_el_dia_completo(self):
        respuesta = self.crear()
        self.assertRedirects(respuesta, url('justificaciones'))
        self.assertContains(respuesta, 'Se registró la justificación de')
        justificacion = Justificacion.objects.get()
        self.assertEqual(
            (justificacion.inscripcion, justificacion.fecha, justificacion.justifica_general, justificacion.todas_materias, justificacion.motivo, justificacion.registrada_por, justificacion.activa),
            (self.inscripcion, self.dia, True, True, 'Cita médica', self.admin, True),
        )
        self.assertFalse(justificacion.materias.exists())

    def test_justifica_solo_la_falta_general(self):
        self.crear(materias_modo='NINGUNA')
        justificacion = Justificacion.objects.get()
        self.assertEqual((justificacion.justifica_general, justificacion.todas_materias, justificacion.materias.count()), (True, False, 0))

    def test_justifica_solo_algunas_materias(self):
        self.crear(justifica_general=None, materias_modo='ALGUNAS', materias=self.materias)
        justificacion = Justificacion.objects.get()
        self.assertEqual((justificacion.justifica_general, justificacion.todas_materias), (False, False))
        self.assertEqual({m.pk for m in justificacion.materias.all()}, set(self.materias))

    def test_puede_combinar_la_falta_general_con_algunas_materias(self):
        self.crear(materias_modo='ALGUNAS', materias=[self.cie.pk])
        justificacion = Justificacion.objects.get()
        self.assertEqual((justificacion.justifica_general, [m.pk for m in justificacion.materias.all()]), (True, [self.cie.pk]))

    def test_hay_que_elegir_que_se_justifica(self):
        respuesta = self.crear(justifica_general=None, materias_modo='NINGUNA')
        self.assertIn('materias_modo', respuesta.context['form'].errors)
        respuesta = self.crear(materias_modo='ALGUNAS')
        self.assertIn('materias', respuesta.context['form'].errors)
        self.assertFalse(Justificacion.objects.exists())

    def test_las_materias_deben_ser_del_grado_del_alumno(self):
        ajena = materia_en_grado('HIS', crear_grado('PRIMARIA', 5), self.ciclo)
        respuesta = self.crear(materias_modo='ALGUNAS', materias=[ajena.pk])
        self.assertIn('materias', respuesta.context['form'].errors)
        self.assertFalse(Justificacion.objects.exists())

    def test_el_motivo_es_obligatorio_y_se_normaliza(self):
        self.assertIn('motivo', self.crear(motivo='   ').context['form'].errors)
        self.crear(motivo='  Cita   médica  de   rutina ')
        self.assertEqual(Justificacion.objects.get().motivo, 'Cita médica de rutina')

    def test_alumno_invalido(self):
        for alumno in (None, 'x', 9999):
            self.assertIn('alumno', self.crear(alumno=alumno).context['form'].errors, str(alumno))
        baja = crear_alumno(estatus='BAJA')
        self.assertIn('alumno', self.crear(alumno=baja.pk).context['form'].errors)
        sin_inscripcion = crear_alumno()
        self.assertIn('alumno', self.crear(alumno=sin_inscripcion.pk).context['form'].errors)
        self.assertFalse(Justificacion.objects.exists())

    def test_la_fecha_debe_ser_un_dia_de_clases_del_ciclo_actual(self):
        sabado = self.dia - timedelta(days=2)
        casos = {
            'fin de semana': (sabado.isoformat(), 'no es de clases'),
            'fuera de ciclo': ((lunes() - timedelta(days=900)).isoformat(), 'fuera de las fechas'),
            'fecha rara': ('x', 'fecha válida'),
        }
        for nombre, (fecha, texto) in casos.items():
            respuesta = self.crear(fecha_desde=fecha)
            self.assertIn(texto, ' '.join(respuesta.context['form'].errors['fecha_desde']), nombre)
        DiaNoLectivo.objects.create(fecha=self.dia, motivo='Puente')
        self.assertIn('fecha_desde', self.crear().context['form'].errors)
        self.assertFalse(Justificacion.objects.exists())

    def test_un_ciclo_cerrado_ya_no_se_justifica(self):
        cerrado = ciclo_cerrado_de_prueba()
        inscribir_antes(self.alumno, cerrado, self.grado)
        fecha = cerrado.fecha_inicio + timedelta(days=(7 - cerrado.fecha_inicio.weekday()) % 7)
        respuesta = self.crear(fecha_desde=fecha.isoformat())
        self.assertIn('no es el ciclo actual', ' '.join(respuesta.context['form'].errors['fecha_desde']))

    def test_se_puede_justificar_por_adelantado(self):
        manana = lunes() + timedelta(days=7)
        self.crear(fecha_desde=manana.isoformat())
        self.assertEqual(Justificacion.objects.get().fecha, manana)

    def test_un_dia_ya_justificado_no_se_repite(self):
        self.crear()
        respuesta = self.crear()
        self.assertIn('ya tiene una justificación vigente', ' '.join(respuesta.context['form'].errors['fecha_desde']))
        self.assertEqual(Justificacion.objects.count(), 1)

    def test_una_anulada_no_impide_registrar_otra(self):
        self.crear()
        Justificacion.objects.update(activa=False)
        self.crear(materias_modo='NINGUNA')
        self.assertEqual(Justificacion.objects.count(), 2)
        self.assertEqual(Justificacion.objects.filter(activa=True).count(), 1)

    # --- varios días --------------------------------------------------------------------------------
    def test_justifica_varios_dias_seguidos_solo_los_de_clases(self):
        viernes = self.dia + timedelta(days=4)
        siguiente_lunes = self.dia + timedelta(days=7)
        respuesta = self.crear(fecha_desde=viernes.isoformat(), fecha_hasta=siguiente_lunes.isoformat())
        self.assertContains(respuesta, 'Se registraron 2 justificaciones')
        self.assertEqual(sorted(Justificacion.objects.values_list('fecha', flat=True)), [viernes, siguiente_lunes])

    def test_los_dias_sin_clases_del_rango_se_omiten(self):
        DiaNoLectivo.objects.create(fecha=self.dia + timedelta(days=1), motivo='Puente')
        self.crear(fecha_hasta=(self.dia + timedelta(days=2)).isoformat())
        self.assertEqual(sorted(Justificacion.objects.values_list('fecha', flat=True)), [self.dia, self.dia + timedelta(days=2)])

    def test_en_un_rango_los_dias_ya_justificados_no_se_tocan(self):
        existente = Justificacion.objects.create(inscripcion=self.inscripcion, fecha=self.dia + timedelta(days=1), motivo='Otra', justifica_general=True)
        respuesta = self.crear(fecha_hasta=(self.dia + timedelta(days=2)).isoformat())
        self.assertContains(respuesta, 'ya tenía una justificación vigente y no se tocó')
        self.assertEqual(Justificacion.objects.count(), 3)
        existente.refresh_from_db()
        self.assertEqual(existente.motivo, 'Otra')

    def test_si_todo_el_rango_ya_estaba_justificado_avisa(self):
        self.crear(fecha_hasta=(self.dia + timedelta(days=1)).isoformat())
        respuesta = self.crear(fecha_hasta=(self.dia + timedelta(days=1)).isoformat())
        self.assertIn('fecha_hasta', respuesta.context['form'].errors)

    def test_el_rango_se_valida(self):
        self.assertIn('fecha_hasta', self.crear(fecha_hasta=(self.dia - timedelta(days=1)).isoformat()).context['form'].errors)
        self.assertIn('fecha_hasta', self.crear(fecha_hasta=(lunes() + timedelta(days=900)).isoformat()).context['form'].errors)
        self.assertIn('fecha_hasta', self.crear(fecha_hasta=(self.dia + timedelta(days=61)).isoformat()).context['form'].errors)
        self.assertFalse(Justificacion.objects.exists())

    def test_los_dias_de_un_rango_con_algunas_materias_comparten_la_eleccion(self):
        self.crear(fecha_hasta=(self.dia + timedelta(days=1)).isoformat(), materias_modo='ALGUNAS', materias=[self.esp.pk])
        for justificacion in Justificacion.objects.all():
            self.assertEqual([m.pk for m in justificacion.materias.all()], [self.esp.pk])

    # --- comprobante ---------------------------------------------------------------------------------
    def test_guarda_el_comprobante(self):
        self.crear(documento=pdf())
        justificacion = Justificacion.objects.get()
        self.assertTrue(justificacion.documento.name.startswith('justificaciones/'))
        self.assertTrue(justificacion.documento.name.endswith('.pdf'))
        self.assertGreater(justificacion.documento.size, 0)

    def test_un_rango_comparte_el_mismo_comprobante(self):
        self.crear(fecha_hasta=(self.dia + timedelta(days=1)).isoformat(), documento=pdf())
        nombres = {j.documento.name for j in Justificacion.objects.all()}
        self.assertEqual(len(nombres), 1)

    def test_rechaza_comprobantes_que_no_son_pdf_o_imagen_o_muy_grandes(self):
        malo = SimpleUploadedFile('virus.exe', b'MZ', content_type='application/octet-stream')
        self.assertIn('documento', self.crear(documento=malo).context['form'].errors)
        enorme = SimpleUploadedFile('enorme.pdf', b'0' * (5 * 1024 * 1024 + 1), content_type='application/pdf')
        self.assertIn('documento', self.crear(documento=enorme).context['form'].errors)
        self.assertFalse(Justificacion.objects.exists())
        imagen = SimpleUploadedFile('foto.JPG', b'\xff\xd8\xff', content_type='image/jpeg')
        self.crear(documento=imagen)
        self.assertEqual(Justificacion.objects.count(), 1)

    # --- las materias del alumno (JSON) --------------------------------------------------------------
    def test_ofrece_las_materias_del_grado_del_alumno(self):
        materia_en_grado('QUI', self.grado, self.ciclo, activa=False)
        otra = crear_grado('PRIMARIA', 5)
        materia_en_grado('HIS', otra, self.ciclo)
        respuesta = self.client.get(url('justificacion_materias', alumno=self.alumno.pk, fecha=self.dia.isoformat()))
        datos = respuesta.json()
        self.assertEqual(datos['grado'], '4° Primaria')
        self.assertEqual(sorted(m['clave'] for m in datos['materias']), ['CIE', 'ESP', 'MAT'])

    def test_sin_alumno_o_sin_inscripcion_no_ofrece_materias(self):
        for alumno in ('', 'x', crear_alumno().pk):
            self.assertEqual(self.client.get(url('justificacion_materias', alumno=alumno)).json(), {'grado': '', 'materias': []}, str(alumno))


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------
@PRUEBAS
class ListaJustificacionesTests(BaseJustificacionTests):
    def setUp(self):
        super().setUp()
        self.g5 = crear_grado('PRIMARIA', 5)
        self.a2 = inscribir_antes(crear_alumno(nombre='Beto', apellido_paterno='Zuñiga'), self.ciclo, self.g5)
        self.j1 = Justificacion.objects.create(inscripcion=self.inscripcion, fecha=self.dia, motivo='Cita médica', justifica_general=True, todas_materias=True)
        self.j2 = Justificacion.objects.create(inscripcion=self.a2, fecha=self.dia + timedelta(days=1), motivo='Torneo deportivo')
        self.j2.materias.set([self.mat, self.esp])
        self.j3 = Justificacion.objects.create(inscripcion=self.a2, fecha=self.dia + timedelta(days=2), motivo='Viaje', justifica_general=True, activa=False)

    def lista(self, **consulta):
        respuesta = self.client.get(url('justificaciones', **consulta))
        self.assertEqual(respuesta.status_code, 200)
        return respuesta

    def pks(self, respuesta):
        return [j.pk for j in respuesta.context['pagina']]

    def test_por_defecto_solo_las_vigentes_de_la_mas_reciente_a_la_mas_antigua(self):
        self.assertEqual(self.pks(self.lista()), [self.j2.pk, self.j1.pk])

    def test_las_anuladas_tienen_su_filtro_y_los_conteos(self):
        respuesta = self.lista(estado='ANULADA')
        self.assertEqual(self.pks(respuesta), [self.j3.pk])
        self.assertTrue(respuesta.context['viendo_anuladas'])
        self.assertEqual(respuesta.context['conteo'], {'vigentes': 2, 'anuladas': 1})
        self.assertContains(respuesta, 'Reactivar')

    def test_muestra_lo_que_justifica_cada_una(self):
        alcances = {j.pk: j.alcance for j in self.lista().context['pagina']}
        self.assertEqual(alcances[self.j1.pk], ['Falta general', 'Todas las materias'])
        self.assertEqual(alcances[self.j2.pk], ['2 materias'])

    def test_busca_por_alumno_referencia_y_motivo(self):
        self.assertEqual(self.pks(self.lista(q='zuñ')), [self.j2.pk])
        self.assertEqual(self.pks(self.lista(q=self.alumno.referencia)), [self.j1.pk])
        self.assertEqual(self.pks(self.lista(q='torneo')), [self.j2.pk])
        self.assertEqual(self.pks(self.lista(q='zzz')), [])

    def test_filtra_por_grado_y_por_fechas(self):
        self.assertEqual(self.pks(self.lista(grado=self.g5.pk)), [self.j2.pk])
        self.assertEqual(self.pks(self.lista(desde=(self.dia + timedelta(days=1)).isoformat())), [self.j2.pk])
        self.assertEqual(self.pks(self.lista(hasta=self.dia.isoformat())), [self.j1.pk])

    def test_pagina(self):
        for i in range(25):
            Justificacion.objects.create(inscripcion=self.inscripcion, fecha=self.dia - timedelta(days=i + 1), motivo='Otra')
        respuesta = self.lista()
        self.assertEqual((respuesta.context['pagina'].paginator.count, len(respuesta.context['pagina'])), (27, 20))

    def test_estados_vacios(self):
        Justificacion.objects.all().delete()
        self.assertContains(self.lista(), 'Aún no hay justificaciones')
        self.assertContains(self.lista(estado='ANULADA'), 'No hay justificaciones anuladas')
        self.assertContains(self.lista(q='zzz'), 'No encontramos justificaciones')

    def test_los_botones_dependen_del_permiso(self):
        self.con_permisos('view_justificacion')
        respuesta = self.lista()
        self.assertNotContains(respuesta, 'data-anular-justificacion')
        self.assertNotContains(respuesta, url('justificacion_editar', self.j1.pk))
        self.assertNotContains(respuesta, 'Nueva justificación</a>')

    def test_consultas_constantes(self):
        with CaptureQueriesContext(connection) as pocas:
            self.lista()
        for i in range(15):
            justificacion = Justificacion.objects.create(inscripcion=self.a2, fecha=self.dia - timedelta(days=i + 3), motivo='Otra')
            justificacion.materias.set([self.mat, self.cie])
        with CaptureQueriesContext(connection) as muchas:
            self.lista(por_pagina=50)
        self.assertEqual(len(muchas), len(pocas))


# ---------------------------------------------------------------------------
# Editar, anular y reactivar
# ---------------------------------------------------------------------------
@PRUEBAS
@override_settings(MEDIA_ROOT=CARPETA)
class EditarJustificacionTests(BaseJustificacionTests):
    def setUp(self):
        super().setUp()
        self.justificacion = Justificacion.objects.create(inscripcion=self.inscripcion, fecha=self.dia, motivo='Cita médica', justifica_general=True, todas_materias=True)

    def editar(self, **cambios):
        datos = {'justifica_general': 'on', 'materias_modo': 'TODAS', 'motivo': 'Cita médica'}
        datos.update(cambios)
        return self.client.post(url('justificacion_editar', self.justificacion.pk), {k: v for k, v in datos.items() if v is not None}, follow=True)

    def test_el_formulario_viene_con_lo_que_ya_cubre(self):
        respuesta = self.client.get(url('justificacion_editar', self.justificacion.pk))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context['form'].initial['materias_modo'], 'TODAS')
        self.assertTrue(respuesta.context['form'].initial['justifica_general'])
        self.assertContains(respuesta, 'Cita médica')
        self.assertNotContains(respuesta, 'name="fecha_desde"')

    def test_pasa_de_todas_las_materias_a_solo_algunas(self):
        respuesta = self.editar(materias_modo='ALGUNAS', materias=[self.mat.pk], justifica_general=None)
        self.assertRedirects(respuesta, url('justificaciones'))
        self.assertContains(respuesta, 'Se actualizó la justificación')
        self.justificacion.refresh_from_db()
        self.assertEqual((self.justificacion.justifica_general, self.justificacion.todas_materias, [m.pk for m in self.justificacion.materias.all()]), (False, False, [self.mat.pk]))

    def test_volver_a_todas_o_a_ninguna_limpia_las_materias_elegidas(self):
        self.justificacion.materias.set([self.mat])
        self.editar(materias_modo='TODAS')
        self.assertEqual(self.justificacion.materias.count(), 0)
        self.justificacion.materias.set([self.mat])
        self.editar(materias_modo='NINGUNA')
        self.assertEqual(self.justificacion.materias.count(), 0)

    def test_valida_lo_mismo_que_al_crear(self):
        self.assertIn('materias_modo', self.editar(justifica_general=None, materias_modo='NINGUNA').context['form'].errors)
        self.assertIn('materias', self.editar(materias_modo='ALGUNAS').context['form'].errors)
        self.assertIn('motivo', self.editar(motivo='').context['form'].errors)
        self.justificacion.refresh_from_db()
        self.assertTrue(self.justificacion.todas_materias)

    def test_reemplaza_y_quita_el_comprobante(self):
        self.editar(documento=pdf('uno.pdf'))
        self.justificacion.refresh_from_db()
        self.assertTrue(self.justificacion.documento)
        self.editar(documento=pdf('dos.pdf'))
        self.justificacion.refresh_from_db()
        self.assertIn('dos', self.justificacion.documento.name)
        self.assertContains(self.client.get(url('justificacion_editar', self.justificacion.pk)), 'Ver comprobante actual')
        self.editar(quitar_documento='on')
        self.justificacion.refresh_from_db()
        self.assertFalse(self.justificacion.documento)

    def test_una_anulada_no_se_edita(self):
        self.justificacion.activa = False
        self.justificacion.save()
        respuesta = self.client.get(url('justificacion_editar', self.justificacion.pk), follow=True)
        self.assertRedirects(respuesta, url('justificaciones'))
        self.assertContains(respuesta, 'está anulada')

    def test_un_ciclo_cerrado_no_se_edita(self):
        self.ciclo.activo = False
        self.ciclo.save()
        respuesta = self.client.get(url('justificacion_editar', self.justificacion.pk), follow=True)
        self.assertContains(respuesta, 'no es el ciclo actual')

    def test_justificacion_inexistente_da_404(self):
        self.assertEqual(self.client.get(url('justificacion_editar', 9999)).status_code, 404)

    # --- anular y reactivar ----------------------------------------------------------------------------
    def test_anular_es_logico_y_confirma(self):
        respuesta = self.client.post(url('justificacion_anular', self.justificacion.pk), follow=True)
        self.assertRedirects(respuesta, url('justificaciones'))
        self.assertContains(respuesta, 'Se anuló la justificación')
        self.justificacion.refresh_from_db()
        self.assertFalse(self.justificacion.activa)
        self.assertTrue(Justificacion.objects.filter(pk=self.justificacion.pk).exists())

    def test_anular_deja_de_justificar_la_falta(self):
        reglas.fijar_asistencia_general(self.inscripcion, self.dia, 'FALTA')
        self.client.post(url('justificacion_anular', self.justificacion.pk))
        general = reglas.con_justificada_general(self.inscripcion.asistencias_generales.all()).get()
        self.assertFalse(general.justificada)

    def test_anular_dos_veces_es_inofensivo(self):
        self.client.post(url('justificacion_anular', self.justificacion.pk))
        respuesta = self.client.post(url('justificacion_anular', self.justificacion.pk), follow=True)
        self.assertEqual(respuesta.status_code, 200)

    def test_vuelve_adonde_se_estaba(self):
        destino = url('justificaciones', q='cita')
        respuesta = self.client.post(url('justificacion_anular', self.justificacion.pk), {'next': destino})
        self.assertRedirects(respuesta, destino, fetch_redirect_response=False)

    def test_un_ciclo_cerrado_no_se_anula(self):
        self.ciclo.activo = False
        self.ciclo.save()
        respuesta = self.client.post(url('justificacion_anular', self.justificacion.pk), follow=True)
        self.assertContains(respuesta, 'no es el ciclo actual')
        self.justificacion.refresh_from_db()
        self.assertTrue(self.justificacion.activa)

    def test_reactivar(self):
        self.justificacion.activa = False
        self.justificacion.save()
        respuesta = self.client.post(url('justificacion_reactivar', self.justificacion.pk), follow=True)
        self.assertContains(respuesta, 'Se reactivó la justificación')
        self.justificacion.refresh_from_db()
        self.assertTrue(self.justificacion.activa)

    def test_no_se_reactiva_si_ese_dia_ya_tiene_otra_vigente(self):
        self.justificacion.activa = False
        self.justificacion.save()
        Justificacion.objects.create(inscripcion=self.inscripcion, fecha=self.dia, motivo='Otra', justifica_general=True)
        respuesta = self.client.post(url('justificacion_reactivar', self.justificacion.pk), follow=True)
        self.assertContains(respuesta, 'ya tiene otra justificación vigente')
        self.justificacion.refresh_from_db()
        self.assertFalse(self.justificacion.activa)

    def test_anular_y_reactivar_inexistentes_dan_404(self):
        self.assertEqual(self.client.post(url('justificacion_anular', 9999)).status_code, 404)
        self.assertEqual(self.client.post(url('justificacion_reactivar', 9999)).status_code, 404)
