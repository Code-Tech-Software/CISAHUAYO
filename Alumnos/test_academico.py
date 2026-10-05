"""Pruebas del modelo académico compartido: estado de los ciclos, orden de los grados y reglas de inscripción."""
from datetime import date, timedelta

from django.test import SimpleTestCase, TestCase

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
)

from .academico import (
    activar_ciclo,
    alumnos_sin_inscribir,
    ciclo_actual,
    motivo_no_inscribible,
    siguiente_grado,
    sugerir_ciclo,
)
from .forms import InscribirForm, InscripcionInicialForm, grados_disponibles
from .models import CicloEscolar, Grado


# ---------------------------------------------------------------------------
# Ciclos: estado derivado de las fechas y de la marca «actual»
# ---------------------------------------------------------------------------
class EstadoDelCicloTests(TestCase):
    def test_estados(self):
        self.assertEqual(ciclo_actual_de_prueba().estado, 'ACTUAL')
        self.assertEqual(ciclo_proximo_de_prueba().estado, 'PROXIMO')
        self.assertEqual(ciclo_cerrado_de_prueba().estado, 'CERRADO')

    def test_nombres_legibles(self):
        self.assertEqual(ciclo_actual_de_prueba().estado_display, 'Actual')
        self.assertEqual(ciclo_proximo_de_prueba().estado_display, 'Próximo')
        self.assertEqual(ciclo_cerrado_de_prueba().estado_display, 'Cerrado')

    def test_un_ciclo_sin_marcar_que_ya_empezo_esta_cerrado(self):
        self.assertEqual(crear_ciclo('Sin marca', -10, 100).estado, 'CERRADO')

    def test_duracion_y_avance(self):
        ciclo = crear_ciclo('A', -50, 49, activo=True)       # 100 días, van 50
        self.assertEqual(ciclo.duracion_dias, 100)
        self.assertEqual(ciclo.avance, 51)                   # 50 de 99 días transcurridos
        self.assertEqual(crear_ciclo('B', 10, 20).avance, 0)
        self.assertEqual(crear_ciclo('C', -20, -10).avance, 100)

    def test_fuera_de_fechas_solo_aplica_al_ciclo_actual(self):
        self.assertFalse(ciclo_actual_de_prueba().fuera_de_fechas)
        self.assertTrue(crear_ciclo('Vencido', -100, -1, activo=True).fuera_de_fechas)
        self.assertTrue(crear_ciclo('Futuro', 5, 100, activo=True).fuera_de_fechas)
        self.assertFalse(ciclo_cerrado_de_prueba().fuera_de_fechas)

    def test_activar_deja_un_solo_ciclo_actual(self):
        viejo = ciclo_actual_de_prueba()
        nuevo = ciclo_proximo_de_prueba()
        activar_ciclo(nuevo)
        viejo.refresh_from_db()
        nuevo.refresh_from_db()
        self.assertTrue(nuevo.activo)
        self.assertFalse(viejo.activo)
        self.assertEqual(ciclo_actual(), nuevo)

    def test_sin_ciclo_actual(self):
        ciclo_cerrado_de_prueba()
        self.assertIsNone(ciclo_actual())


class SugerirCicloTests(TestCase):
    def test_sin_ciclos_propone_el_del_anio_en_curso(self):
        propuesta = sugerir_ciclo()
        anio = hoy().year if hoy().month >= 6 else hoy().year - 1
        self.assertEqual(propuesta['nombre'], f'{anio}-{anio + 1}')
        self.assertEqual(propuesta['fecha_inicio'], date(anio, 8, 24))
        self.assertEqual(propuesta['fecha_fin'], date(anio + 1, 7, 10))

    def test_continua_el_ciclo_mas_reciente_con_su_calendario(self):
        CicloEscolar.objects.create(nombre='2026-2027', fecha_inicio=date(2026, 8, 31), fecha_fin=date(2027, 7, 15))
        self.assertEqual(sugerir_ciclo(), {
            'nombre': '2027-2028', 'fecha_inicio': date(2027, 8, 31), 'fecha_fin': date(2028, 7, 15),
        })

    def test_un_ciclo_muy_corto_no_se_copia(self):
        CicloEscolar.objects.create(nombre='2026-2027', fecha_inicio=date(2026, 9, 12), fecha_fin=date(2026, 9, 13))
        propuesta = sugerir_ciclo()
        self.assertEqual(propuesta['nombre'], '2027-2028')
        self.assertEqual((propuesta['fecha_inicio'], propuesta['fecha_fin']), (date(2027, 8, 24), date(2028, 7, 10)))

    def test_nombre_que_no_sigue_el_formato(self):
        CicloEscolar.objects.create(nombre='Verano', fecha_inicio=date(2026, 8, 31), fecha_fin=date(2027, 7, 15))
        self.assertEqual(sugerir_ciclo()['nombre'], '2027-2028')

    def test_la_propuesta_nunca_se_empalma_con_un_ciclo_existente(self):
        # un ciclo larguísimo: copiar su calendario un año después caería dentro de él
        CicloEscolar.objects.create(nombre='2026-2027', fecha_inicio=date(2025, 1, 12), fecha_fin=date(2027, 6, 13))
        propuesta = sugerir_ciclo()
        self.assertEqual(propuesta['nombre'], '2027-2028')
        self.assertEqual(propuesta['fecha_inicio'], date(2027, 6, 14))
        self.assertLessEqual((propuesta['fecha_fin'] - propuesta['fecha_inicio']).days, 364)
        self.assertGreater(propuesta['fecha_fin'], propuesta['fecha_inicio'])

    def test_la_propuesta_respeta_tambien_a_un_ciclo_que_termina_despues(self):
        CicloEscolar.objects.create(nombre='2026-2027', fecha_inicio=date(2026, 8, 31), fecha_fin=date(2027, 7, 15))
        CicloEscolar.objects.create(nombre='Largo', fecha_inicio=date(2020, 1, 1), fecha_fin=date(2028, 12, 31))
        propuesta = sugerir_ciclo()
        self.assertGreater(propuesta['fecha_inicio'], date(2028, 12, 31))

    def test_el_nombre_propuesto_no_se_repite(self):
        CicloEscolar.objects.create(nombre='2026-2027', fecha_inicio=date(2026, 8, 31), fecha_fin=date(2027, 7, 15))
        CicloEscolar.objects.create(nombre='2027-2028', fecha_inicio=date(2025, 8, 31), fecha_fin=date(2026, 7, 15))
        self.assertEqual(sugerir_ciclo()['nombre'], '2028-2029')

    def test_fecha_de_29_de_febrero(self):
        CicloEscolar.objects.create(nombre='2027-2028', fecha_inicio=date(2027, 8, 24), fecha_fin=date(2028, 2, 29))
        propuesta = sugerir_ciclo()     # 190 días: se copia el calendario; el 29 de febrero pasa al 28 sin error
        self.assertEqual(propuesta['nombre'], '2028-2029')
        self.assertEqual((propuesta['fecha_inicio'], propuesta['fecha_fin']), (date(2028, 8, 24), date(2029, 2, 28)))


# ---------------------------------------------------------------------------
# Grados: orden escolar y siguiente grado
# ---------------------------------------------------------------------------
class OrdenDeGradosTests(TestCase):
    def test_orden_escolar_en_lugar_de_alfabetico(self):
        for nivel, numero in (('PREPARATORIA', 1), ('SECUNDARIA', 2), ('PRIMARIA', 6), ('PRIMARIA', 1), ('PREESCOLAR', 3), ('SECUNDARIA', 1)):
            crear_grado(nivel, numero)
        self.assertEqual(
            [str(g) for g in Grado.objects.academicos()],
            ['3° Preescolar', '1° Primaria', '6° Primaria', '1° Secundaria', '2° Secundaria', '1° Preparatoria'],
        )

    def test_los_grados_nuevos_nacen_activos(self):
        self.assertTrue(crear_grado('PRIMARIA', 1).activo)

    def test_url_del_perfil(self):
        grado = crear_grado('PRIMARIA', 1)
        self.assertEqual(grado.get_absolute_url(), f'/grados/{grado.pk}/')


class SiguienteGradoTests(SimpleTestCase):
    def grados(self, *pares):
        return [Grado(pk=i + 1, nivel=nivel, numero=numero) for i, (nivel, numero) in enumerate(pares)]

    def test_el_siguiente_numero_del_mismo_nivel(self):
        grados = self.grados(('PRIMARIA', 1), ('PRIMARIA', 2), ('PRIMARIA', 3))
        self.assertEqual(siguiente_grado(grados[0], grados), grados[1])

    def test_al_terminar_el_nivel_pasa_al_primero_del_siguiente(self):
        grados = self.grados(('PREESCOLAR', 3), ('PRIMARIA', 1), ('PRIMARIA', 2))
        self.assertEqual(siguiente_grado(grados[0], grados), grados[1])

    def test_salta_niveles_que_el_colegio_no_ofrece(self):
        grados = self.grados(('PRIMARIA', 6), ('PREPARATORIA', 1))
        self.assertEqual(siguiente_grado(grados[0], grados), grados[1])

    def test_el_ultimo_grado_no_tiene_siguiente(self):
        grados = self.grados(('PRIMARIA', 5), ('PRIMARIA', 6))
        self.assertIsNone(siguiente_grado(grados[1], grados))

    def test_ignora_numeros_menores(self):
        grados = self.grados(('SECUNDARIA', 1), ('SECUNDARIA', 3))
        self.assertEqual(siguiente_grado(grados[0], grados), grados[1])  # si falta el 2.º, sigue el 3.º


# ---------------------------------------------------------------------------
# Reglas de inscripción
# ---------------------------------------------------------------------------
class ReglasDeInscripcionTests(TestCase):
    def test_solo_se_inscribe_a_quien_esta_en_el_colegio(self):
        self.assertIsNone(motivo_no_inscribible(crear_alumno(estatus='ACTIVO')))
        self.assertIsNone(motivo_no_inscribible(crear_alumno(estatus='SUSPENDIDO')))
        self.assertIn('dado de baja', motivo_no_inscribible(crear_alumno(estatus='BAJA')))
        self.assertIn('egresado', motivo_no_inscribible(crear_alumno(estatus='EGRESADO')))

    def test_alumnos_sin_inscribir(self):
        ciclo = ciclo_actual_de_prueba()
        otro = ciclo_cerrado_de_prueba()
        grado = crear_grado()
        inscrito = crear_alumno()
        con_baja = crear_alumno()
        solo_en_otro_ciclo = crear_alumno()
        pendiente = crear_alumno()
        crear_alumno(estatus='BAJA')
        inscribir(inscrito, ciclo, grado)
        inscribir(con_baja, ciclo, grado, activa=False)     # tuvo inscripción: no se vuelve a ofrecer inscribirlo
        inscribir(solo_en_otro_ciclo, otro, grado)
        self.assertEqual(set(alumnos_sin_inscribir(ciclo)), {solo_en_otro_ciclo, pendiente})


@PRUEBAS
class FormulariosDeInscripcionTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.grado = crear_grado('PRIMARIA', 3)
        self.alumno = crear_alumno()

    def datos(self, **cambios):
        datos = {'ciclo': self.ciclo.pk, 'grado': self.grado.pk, 'fecha_inscripcion': hoy().isoformat()}
        datos.update(cambios)
        return datos

    def test_los_grados_dados_de_baja_no_se_ofrecen(self):
        baja = crear_grado('PRIMARIA', 4, activo=False)
        self.assertIn(self.grado, grados_disponibles())
        self.assertNotIn(baja, grados_disponibles())
        self.assertIn(baja, grados_disponibles(incluir=baja))  # al editar se conserva el que ya tenía

    def test_inscribir_rechaza_un_grado_dado_de_baja(self):
        baja = crear_grado('PRIMARIA', 4, activo=False)
        form = InscribirForm(self.datos(grado=baja.pk), alumno=self.alumno)
        self.assertFalse(form.is_valid())
        self.assertIn('grado', form.errors)

    def test_inscribir_rechaza_alumnos_de_baja_o_egresados(self):
        for estatus in ('BAJA', 'EGRESADO'):
            alumno = crear_alumno(estatus=estatus)
            form = InscribirForm(self.datos(), alumno=alumno)
            self.assertFalse(form.is_valid(), estatus)

    def test_inscribir_rechaza_fechas_futuras(self):
        form = InscribirForm(self.datos(fecha_inscripcion=(hoy() + timedelta(days=3)).isoformat()), alumno=self.alumno)
        self.assertFalse(form.is_valid())
        self.assertIn('fecha_inscripcion', form.errors)

    def test_inscribir_acepta_un_alumno_activo(self):
        form = InscribirForm(self.datos(), alumno=self.alumno)
        self.assertTrue(form.is_valid(), form.errors)

    def test_los_selectores_indican_el_estado_del_ciclo_y_agrupan_por_nivel(self):
        crear_grado('PREESCOLAR', 1)
        form = InscribirForm(alumno=self.alumno)
        html = str(form['ciclo'])
        self.assertIn('2026-2027 · actual', html)
        grados = str(form['grado'])
        self.assertIn('<optgroup label="Preescolar">', grados)
        self.assertLess(grados.index('Preescolar'), grados.index('Primaria'))   # orden escolar, no alfabético

    def test_el_ciclo_actual_viene_preseleccionado(self):
        self.assertEqual(InscribirForm(alumno=self.alumno)['ciclo'].initial, self.ciclo)
        self.assertEqual(InscripcionInicialForm(prefix='insc')['ciclo'].initial, self.ciclo)

    def test_la_inscripcion_inicial_solo_ofrece_grados_activos(self):
        crear_grado('PRIMARIA', 4, activo=False)
        valores = []
        for _, etiqueta in InscripcionInicialForm(prefix='insc').fields['grado'].choices:
            if isinstance(etiqueta, (list, tuple)):   # un grupo (<optgroup>): [(valor, etiqueta), ...]
                valores.extend(getattr(valor, 'value', valor) for valor, _ in etiqueta)
        self.assertEqual(valores, [self.grado.pk])
