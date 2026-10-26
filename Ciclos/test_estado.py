"""Pruebas de los cambios del 2026-10-26 en Ciclos escolares: el estado ya no depende de la fecha de inicio, quién y
cuándo se marcó como actual o se cerró, un solo ciclo actual en la base, fechas que cubren lo que ya existe, avisos del
nombre y la duración, borrar un ciclo creado por error, el detalle (preparación, pendientes, grupos, días de clase y
comparación) y el aviso del Panel."""
from datetime import timedelta

from django.apps import apps
from django.contrib.admin.models import LogEntry
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from Alumnos.academico import activar_ciclo, cerrar_ciclo, ciclo_editable
from Alumnos.models import AsistenciaGeneral, CicloEscolar, DiaNoLectivo, Grupo, NombreGrupo, Periodo
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    ciclo_cerrado_de_prueba,
    ciclo_proximo_de_prueba,
    crear_alumno,
    crear_ciclo,
    crear_grado,
    hoy,
    inscribir,
    materia_en_grado,
)
from Inscripciones.forms import PromocionForm

from .reglas import avisos_de_datos


def bitacora(ciclo):
    return list(LogEntry.objects.filter(object_id=str(ciclo.pk), content_type__model='cicloescolar')
                .order_by('pk').values_list('change_message', flat=True))


# ---------------------------------------------------------------------------
# Estado: un ciclo que no se marcó a tiempo no se ve «Cerrado»
# ---------------------------------------------------------------------------
@PRUEBAS
class CambioDeCicloTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.anterior = crear_ciclo('2025-2026', -330, -5, activo=True)   # ya terminó, sigue marcado
        self.nuevo = crear_ciclo('2026-2027', 0, 320)                     # empezó hoy y nadie lo marcó

    def test_el_ciclo_nuevo_sigue_como_proximo_y_se_puede_preparar(self):
        self.assertEqual(self.nuevo.estado, 'PROXIMO')
        self.assertTrue(self.nuevo.por_activar)
        self.assertTrue(ciclo_editable(self.nuevo))                       # materias y horarios
        self.assertIn(self.nuevo, PromocionForm().fields['destino'].queryset)   # acepta inscripciones
        self.assertIn(self.nuevo, CicloEscolar.objects.vigentes())

    def test_el_detalle_conserva_los_atajos_y_avisa(self):
        grado = crear_grado()
        inscribir(crear_alumno(), self.anterior, grado)
        materia_en_grado('MAT', grado, self.anterior)
        respuesta = self.client.get(self.nuevo.get_absolute_url())
        self.assertContains(respuesta, f'Reinscribir desde {self.anterior}')
        self.assertContains(respuesta, f'Copiar materias y horarios de {self.anterior}')
        self.assertContains(respuesta, 'todavía no es el actual')
        self.assertContains(respuesta, 'Ya empezó: falta marcarlo como actual')

    def test_la_lista_cuenta_y_filtra_con_la_misma_regla(self):
        ciclo_cerrado_de_prueba('2024-2025')
        respuesta = self.client.get(reverse('ciclos:lista'))
        self.assertEqual(respuesta.context['conteos'], {'total': 3, 'actual': 1, 'proximo': 1, 'cerrado': 1})
        self.assertEqual(respuesta.context['por_activar'], self.nuevo)
        self.assertEqual([c.nombre for c in self.client.get(reverse('ciclos:lista'), {'estado': 'PROXIMO'}).context['pagina']],
                         ['2026-2027'])

    def test_activar_guarda_quien_y_cuando_y_cierra_el_anterior(self):
        self.client.post(reverse('ciclos:establecer_actual', args=[self.nuevo.pk]))
        self.nuevo.refresh_from_db()
        self.anterior.refresh_from_db()
        self.assertTrue(self.nuevo.activo)
        self.assertEqual(self.nuevo.activado_por, self.admin)
        self.assertIsNotNone(self.nuevo.activado_en)
        self.assertEqual(self.anterior.estado, 'CERRADO')
        self.assertEqual(self.anterior.cerrado_por, self.admin)
        self.assertEqual(bitacora(self.nuevo), ['Lo marcó como ciclo actual.'])
        self.assertIn('quedó cerrado', bitacora(self.anterior)[0])
        self.assertContains(self.client.get(self.nuevo.get_absolute_url()), 'Actual desde')

    def test_cerrar_guarda_quien_y_cuando(self):
        self.client.post(reverse('ciclos:cerrar', args=[self.anterior.pk]))
        self.anterior.refresh_from_db()
        self.assertEqual((self.anterior.activo, self.anterior.cerrado_por), (False, self.admin))
        self.assertEqual(bitacora(self.anterior), ['Cerró el ciclo.'])
        self.assertContains(self.client.get(self.anterior.get_absolute_url()), 'Cerrado el')

    def test_un_ciclo_marcado_por_adelantado_vuelve_a_proximo(self):
        futuro = ciclo_proximo_de_prueba('2027-2028')
        activar_ciclo(futuro)
        activar_ciclo(self.nuevo)
        futuro.refresh_from_db()
        self.assertEqual(futuro.estado, 'PROXIMO')   # todavía no empezaba: no se cierra
        self.assertIsNone(futuro.cerrado_en)

    def test_reabrir_un_ciclo_cerrado_avisa_y_quita_el_cierre(self):
        cerrar_ciclo(self.anterior)
        respuesta = self.client.get(self.anterior.get_absolute_url())
        self.assertContains(respuesta, 'El ciclo está cerrado: se volverá a abrir.')
        activar_ciclo(self.anterior)
        self.anterior.refresh_from_db()
        self.assertEqual((self.anterior.estado, self.anterior.cerrado_en), ('ACTUAL', None))


# ---------------------------------------------------------------------------
# Solo un ciclo actual y sin fechas empalmadas, también fuera del formulario
# ---------------------------------------------------------------------------
class ReglasDelModeloTests(TestCase):
    def test_la_base_no_permite_dos_ciclos_actuales(self):
        ciclo_actual_de_prueba()
        with self.assertRaises(IntegrityError), transaction.atomic():
            crear_ciclo('Otro', 400, 700, activo=True)

    def test_el_modelo_rechaza_fechas_empalmadas_y_otro_actual(self):
        actual = ciclo_actual_de_prueba('2026-2027')
        empalmado = CicloEscolar(nombre='X', fecha_inicio=actual.fecha_fin - timedelta(days=5), fecha_fin=actual.fecha_fin + timedelta(days=300))
        with self.assertRaisesMessage(ValidationError, 'se empalman con el ciclo 2026-2027'):
            empalmado.full_clean()
        otro = CicloEscolar(nombre='Y', fecha_inicio=actual.fecha_fin + timedelta(days=1), fecha_fin=actual.fecha_fin + timedelta(days=300), activo=True)
        with self.assertRaisesMessage(ValidationError, 'ya es el ciclo actual'):
            otro.full_clean()

    def test_en_el_admin_la_marca_de_actual_es_de_solo_lectura(self):
        from Alumnos.admin import CicloEscolarAdmin
        self.assertIn('activo', CicloEscolarAdmin.readonly_fields)
        self.assertIn('cerrado_en', CicloEscolarAdmin.readonly_fields)

    def test_la_migracion_ordena_los_estados_que_ya_hay(self):
        from importlib import import_module
        ordenar = import_module('Alumnos.migrations.0029_estado_del_ciclo').ordenar_estados
        viejo = crear_ciclo('Viejo', -400, -60)
        en_curso = crear_ciclo('En curso', -50, 300)   # ya empezó, no es el actual y antes se veía «Cerrado»
        ordenar(apps, None)
        en_curso.refresh_from_db()
        self.assertIsNotNone(en_curso.cerrado_en)         # sin actual anterior a él: estaba cerrado
        self.assertEqual(CicloEscolar.objects.get(pk=viejo.pk).estado, 'CERRADO')
        # Con un actual anterior, el que ya empezó es el que faltaba activar: sigue próximo
        CicloEscolar.objects.filter(pk=en_curso.pk).update(cerrado_en=None)
        CicloEscolar.objects.filter(pk=viejo.pk).update(activo=True)
        ordenar(apps, None)
        en_curso.refresh_from_db()
        self.assertIsNone(en_curso.cerrado_en)
        self.assertEqual(en_curso.estado, 'PROXIMO')


# ---------------------------------------------------------------------------
# Edición: fechas que cubren lo que ya existe, sin casilla de actual, avisos
# ---------------------------------------------------------------------------
@PRUEBAS
class EditarFechasTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba('2026-2027')
        self.url = reverse('ciclos:editar', args=[self.ciclo.pk])

    def editar(self, inicio=None, fin=None, **extra):
        datos = {
            'nombre': self.ciclo.nombre, 'confirmar': '1',
            'fecha_inicio': (inicio or self.ciclo.fecha_inicio).isoformat(),
            'fecha_fin': (fin or self.ciclo.fecha_fin).isoformat(),
        }
        datos.update(extra)
        return self.client.post(self.url, datos)

    def test_no_deja_fuera_lo_que_ya_depende_del_ciclo(self):
        grado = crear_grado()
        inscripcion = inscribir(crear_alumno(), self.ciclo, grado)
        dia = hoy() - timedelta(days=30)
        AsistenciaGeneral.objects.create(inscripcion=inscripcion, fecha=dia)
        Periodo.objects.create(ciclo=self.ciclo, nivel='PRIMARIA', nombre='Bimestre 1', fecha_inicio=dia, fecha_fin=dia + timedelta(days=50))
        DiaNoLectivo.registrar(fecha=self.ciclo.fecha_fin - timedelta(days=3), motivo='Fin de cursos')
        respuesta = self.editar(inicio=hoy() - timedelta(days=10), fin=self.ciclo.fecha_fin - timedelta(days=10))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'quedarían fuera del ciclo')
        self.assertContains(respuesta, '1 periodo de evaluación (Bimestre 1 · Primaria)')
        self.assertContains(respuesta, '1 registro de entrada')
        self.assertContains(respuesta, '1 día sin clases')
        self.ciclo.refresh_from_db()
        self.assertEqual(self.ciclo.fecha_inicio, hoy() - timedelta(days=60))
        # Ampliarlo o acortarlo sin dejar nada fuera sí se puede
        self.assertEqual(self.editar(inicio=dia - timedelta(days=5)).status_code, 302)

    def test_una_inscripcion_posterior_al_fin_tambien_cuenta(self):
        inscribir(crear_alumno(), self.ciclo, crear_grado(), fecha_inscripcion=hoy())
        self.assertContains(self.editar(fin=hoy() - timedelta(days=1)), 'inscripción posteriores al fin')

    def test_el_nombre_que_no_coincide_con_los_anios_se_confirma(self):
        fin = self.ciclo.fecha_fin
        datos = {'nombre': '1999-2000', 'fecha_inicio': self.ciclo.fecha_inicio.isoformat(), 'fecha_fin': fin.isoformat()}
        respuesta = self.client.post(self.url, datos)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'no coincide con los años de las fechas')
        self.assertContains(respuesta, 'Guardar así')
        self.assertNotContains(respuesta, 'hay datos por corregir')
        self.ciclo.refresh_from_db()
        self.assertEqual(self.ciclo.nombre, '2026-2027')
        self.assertEqual(self.client.post(self.url, {**datos, 'confirmar': '1'}).status_code, 302)
        self.ciclo.refresh_from_db()
        self.assertEqual(self.ciclo.nombre, '1999-2000')
        self.assertIn('Cambió el nombre', bitacora(self.ciclo)[-1])

    def test_avisos_de_duracion(self):
        inicio = hoy()
        self.assertIn('Dura 100 días', avisos_de_datos(f'{inicio.year}-{inicio.year + 1}', inicio, inicio + timedelta(days=99))[-1])
        self.assertIn('más de un año', avisos_de_datos('', inicio, inicio + timedelta(days=500))[0])
        self.assertEqual(avisos_de_datos('Verano', inicio, inicio + timedelta(days=300)), [])   # sin años en el nombre

    def test_crear_tambien_avisa(self):
        respuesta = self.client.post(reverse('ciclos:crear'), {'nombre': '2030-2031', 'fecha_inicio': '2031-08-25', 'fecha_fin': '2032-07-10'})
        self.assertContains(respuesta, 'no coincide con los años')
        self.assertFalse(CicloEscolar.objects.filter(nombre='2030-2031').exists())


# ---------------------------------------------------------------------------
# Borrar un ciclo creado por error
# ---------------------------------------------------------------------------
@PRUEBAS
class BorrarTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.actual = ciclo_actual_de_prueba('2026-2027')
        self.error = ciclo_proximo_de_prueba('2027-2028')

    def test_borra_un_ciclo_sin_nada_ligado(self):
        respuesta = self.client.post(reverse('ciclos:eliminar', args=[self.error.pk]), follow=True)
        self.assertRedirects(respuesta, reverse('ciclos:lista'))
        self.assertContains(respuesta, 'Se borró el ciclo 2027-2028')
        self.assertFalse(CicloEscolar.objects.filter(pk=self.error.pk).exists())
        self.assertTrue(LogEntry.objects.filter(change_message__startswith='Borró el ciclo 2027-2028').exists())

    def test_no_borra_si_tiene_algo_ligado_ni_el_actual(self):
        inscribir(crear_alumno(), self.error, crear_grado())
        respuesta = self.client.post(reverse('ciclos:eliminar', args=[self.error.pk]), follow=True)
        self.assertContains(respuesta, 'no se puede borrar: 1 inscripción')
        respuesta = self.client.post(reverse('ciclos:eliminar', args=[self.actual.pk]), follow=True)
        self.assertContains(respuesta, 'es el ciclo actual')
        self.assertEqual(CicloEscolar.objects.count(), 2)

    def test_la_ventana_explica_por_que_no(self):
        DiaNoLectivo.registrar(fecha=self.error.fecha_inicio + timedelta(days=3), motivo='Puente')
        respuesta = self.client.get(self.error.get_absolute_url())
        self.assertContains(respuesta, 'Borrar el ciclo')
        self.assertContains(respuesta, 'no se puede borrar porque ya tiene información ligada')
        self.assertContains(respuesta, '1 día sin clases')

    def test_pide_su_permiso(self):
        self.con_permisos('view_cicloescolar', 'change_cicloescolar')
        self.assertNotContains(self.client.get(self.error.get_absolute_url()), 'Borrar el ciclo')
        self.assertEqual(self.client.post(reverse('ciclos:eliminar', args=[self.error.pk])).status_code, 403)
        self.assertTrue(CicloEscolar.objects.filter(pk=self.error.pk).exists())


# ---------------------------------------------------------------------------
# Detalle: preparación, pendientes, avisos al activar, grupos, días de clase y comparación
# ---------------------------------------------------------------------------
@PRUEBAS
class DetalleGuiadoTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.anterior = ciclo_cerrado_de_prueba('2025-2026')
        self.actual = ciclo_actual_de_prueba('2026-2027')
        self.proximo = ciclo_proximo_de_prueba('2027-2028')
        self.grado = crear_grado('PRIMARIA', 1)

    def test_preparacion_del_ciclo_proximo(self):
        respuesta = self.client.get(self.proximo.get_absolute_url())
        pasos = {paso.titulo: paso for paso in respuesta.context['preparacion']}
        self.assertEqual(list(pasos), ['Grupos', 'Plan de materias', 'Horarios', 'Profesores asignados', 'Periodos de evaluación',
                                       'Configuración de calificaciones', 'Recesos', 'Días sin clases'])
        self.assertTrue(pasos['Grupos'].listo)
        self.assertFalse(pasos['Plan de materias'].listo)
        self.assertEqual(pasos['Periodos de evaluación'].detalle, 'Sin periodos: Primaria.')
        materia_en_grado('MAT', self.grado, self.proximo)
        Periodo.objects.create(ciclo=self.proximo, nivel='PRIMARIA', nombre='B1', fecha_inicio=self.proximo.fecha_inicio,
                               fecha_fin=self.proximo.fecha_inicio + timedelta(days=60))
        DiaNoLectivo.registrar(fecha=self.proximo.fecha_inicio + timedelta(days=10), motivo='Puente')
        pasos = {paso.titulo: paso for paso in self.client.get(self.proximo.get_absolute_url()).context['preparacion']}
        self.assertTrue(pasos['Plan de materias'].listo)
        self.assertTrue(pasos['Horarios'].listo)
        self.assertFalse(pasos['Profesores asignados'].listo)
        self.assertEqual(pasos['Profesores asignados'].detalle, '1 materia sin profesor.')
        self.assertTrue(pasos['Periodos de evaluación'].listo)
        self.assertFalse(pasos['Recesos'].listo)
        self.assertTrue(pasos['Días sin clases'].listo)
        # Un ciclo cerrado no tiene lista de preparación
        self.assertEqual(self.client.get(self.anterior.get_absolute_url()).context['preparacion'], [])

    def test_pendientes_antes_de_cerrar(self):
        Periodo.objects.create(ciclo=self.actual, nivel='PRIMARIA', nombre='B1', fecha_inicio=hoy() - timedelta(days=5),
                               fecha_fin=hoy() + timedelta(days=5))
        respuesta = self.client.get(self.actual.get_absolute_url())
        self.assertEqual([(p.texto, p.cantidad) for p in respuesta.context['pendientes']], [('Periodos de evaluación abiertos', 1)])
        self.assertContains(respuesta, 'Antes de cerrar el ciclo')
        self.assertContains(respuesta, 'Todavía hay pendientes')   # también en la ventana de cerrar (no la bloquea)

    def test_avisos_al_establecer_como_actual(self):
        crear_alumno()
        crear_alumno()
        respuesta = self.client.get(self.proximo.get_absolute_url())
        self.assertContains(respuesta, '2 estudiantes activos quedarán sin inscripción actual')
        self.assertContains(respuesta, 'Hoy queda fuera de sus fechas: el ciclo empieza el')

    def test_desglose_por_grupo(self):
        grupo_b = Grupo.objects.create(grado=self.grado, nombre=NombreGrupo.objects.get_or_create(nombre='B', defaults={'orden': 2})[0])
        inscribir(crear_alumno(), self.actual, self.grado)
        inscribir(crear_alumno(), self.actual, self.grado, grupo=grupo_b)
        inscribir(crear_alumno(), self.actual, self.grado, grupo=grupo_b)
        fila = self.client.get(self.actual.get_absolute_url()).context['filas'][0]
        self.assertEqual(fila['activas'], 3)
        self.assertEqual([(str(g['grupo'].nombre), g['activas']) for g in fila['grupos']], [('A', 1), ('B', 2)])

    def test_dias_de_clase_por_nivel(self):
        fila = self.client.get(self.actual.get_absolute_url()).context['dias_de_clase'][0]
        self.assertEqual(fila['nivel'], 'Primaria')
        self.assertTrue(200 <= fila['total'] <= 260)    # días hábiles de unos 12 meses
        self.assertTrue(35 <= fila['van'] <= 45)        # unas 8 semanas desde el inicio
        self.assertContains(self.client.get(self.actual.get_absolute_url()), f'{fila["total"]} días de clase, van {fila["van"]}')

    def test_comparacion_con_el_ciclo_anterior(self):
        siguen, se_fue = crear_alumno(), crear_alumno()
        inscribir(siguen, self.anterior, self.grado)
        inscribir(se_fue, self.anterior, self.grado)
        inscribir(siguen, self.actual, self.grado)
        inscribir(crear_alumno(), self.actual, self.grado)
        inscribir(crear_alumno(), self.actual, self.grado, activa=False)
        comparacion = self.client.get(self.actual.get_absolute_url()).context['comparacion']
        self.assertEqual(comparacion['anterior'], self.anterior)
        self.assertEqual((comparacion['inscritos'], comparacion['inscritos_antes'], comparacion['diferencia']), (2, 2, 0))
        self.assertEqual((comparacion['reinscritos'], comparacion['porcentaje_reinscritos'], comparacion['nuevos']), (1, 50, 1))
        self.assertEqual((comparacion['bajas'], comparacion['bajas_antes']), (1, 0))


# ---------------------------------------------------------------------------
# Aviso del cambio de ciclo en el Panel de control
# ---------------------------------------------------------------------------
@PRUEBAS
class AvisoDelPanelTests(BaseTestCase):
    def test_sin_ciclo_actual_avisa_a_quien_edita_ciclos(self):
        ciclo_cerrado_de_prueba('2025-2026')
        nuevo = crear_ciclo('2026-2027', -3, 330)
        respuesta = self.client.get(reverse('inicio'))
        self.assertContains(respuesta, 'No hay un ciclo escolar actual.')
        self.assertContains(respuesta, f'El ciclo {nuevo} empezó el')
        self.assertContains(respuesta, nuevo.get_absolute_url())
        self.con_permisos('view_alumno', 'view_cicloescolar')
        self.assertNotContains(self.client.get(reverse('inicio')), 'No hay un ciclo escolar actual.')

    def test_el_actual_fuera_de_fechas(self):
        crear_ciclo('2025-2026', -330, -5, activo=True)
        respuesta = self.client.get(reverse('inicio'))
        self.assertContains(respuesta, 'Hoy queda fuera de las fechas del ciclo actual (2025-2026).')

    def test_sin_problema_no_hay_aviso(self):
        ciclo_actual_de_prueba()
        self.assertIsNone(self.client.get(reverse('inicio')).context['aviso_ciclo'])
