"""Bachillerato por semestres (pedido del 2026-10-28): el cálculo semestral (exención, examen final, extraordinario,
regularización, truncado), la hoja de cada materia, la captura de exámenes, el cierre y la reapertura de cada semestre,
el paso de los estudiantes al semestre B y el cierre del ciclo."""
import json
from datetime import timedelta
from decimal import Decimal
from fractions import Fraction

from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from Alumnos.asistencia_docente import inscripciones_de
from Alumnos.models import CicloEscolar, Inscripcion, Periodo, Semestre
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    crear_alumno,
    crear_grado,
    crear_profesor,
    crear_usuario,
    grupo_de,
    hoy,
    inscribir,
    materia_en_grado,
)
from Usuarios.models import Rol

from . import calculo_semestral as cs
from . import reglas, semestres
from .models import ActaCalificaciones, CambioSemestre, ExamenSemestral

D = Decimal


def calcular(periodos, final=None, extra=None, regu=None):
    numero = lambda v: None if v is None else D(str(v))   # noqa: E731
    return cs.calcular([numero(p) for p in periodos], final=numero(final), extraordinario=numero(extra), regularizacion=numero(regu))


# ---------------------------------------------------------------------------
# Cálculo (sin base de datos)
# ---------------------------------------------------------------------------
class CalculoSemestralTests(SimpleTestCase):
    def test_promedio_de_9_5_exenta_y_el_examen_final_es_el_promedio(self):
        r = calcular([9.5, 9.5, 9.5])
        self.assertEqual((r.situacion, r.estado), (cs.EXENTO, cs.APROBADA_EXENTO))
        self.assertTrue(r.final_por_exencion)
        self.assertEqual((cs.texto(r.examen_final), cs.texto(r.ordinaria), cs.texto(r.definitiva)), ('9.50', '9.50', '9.50'))
        self.assertEqual(r.capturable, set())   # el examen final del exento no se captura

    def test_ejemplo_del_pedido_9_6(self):
        r = calcular([9.6, 9.6, 9.6])
        self.assertEqual((cs.texto(r.examen_final), cs.texto(r.ordinaria)), ('9.60', '9.60'))

    def test_no_se_redondea_antes_de_decidir_la_exencion(self):
        r = calcular([9.5, 9.5, 9.49])   # 9.4966…
        self.assertEqual(r.situacion, cs.CON_DERECHO)
        self.assertEqual(cs.texto(r.promedio), '9.49')   # truncado: nunca aparece un 9.50 que no se alcanzó
        self.assertEqual((r.estado, r.capturable), (cs.PENDIENTE_FINAL, {cs.FINAL}))

    def test_ejemplo_del_pedido_examen_final_50_y_50(self):
        r = calcular([8, 7, 9], final=7)
        self.assertEqual(cs.texto(r.promedio), '8.00')
        self.assertEqual(cs.texto(r.ordinaria), '7.50')   # (8 + 7) / 2, no el promedio de las cuatro (7.75)
        self.assertEqual(r.estado, cs.APROBADA_ORDINARIO)

    def test_promedio_de_6_tiene_derecho_a_final(self):
        r = calcular([6, 6, 6])
        self.assertEqual((r.situacion, r.estado), (cs.CON_DERECHO, cs.PENDIENTE_FINAL))

    def test_promedio_menor_que_6_va_directo_a_extraordinario(self):
        r = calcular([6, 6, 5.99])   # 5.9966…
        self.assertEqual(r.situacion, cs.SIN_DERECHO)
        self.assertEqual((r.estado, cs.texto(r.ordinaria)), (cs.PENDIENTE_EXTRAORDINARIO, '5.99'))
        self.assertEqual(r.capturable, {cs.EXTRAORDINARIO})   # sin examen final

    def test_ordinaria_reprobatoria_habilita_extraordinario(self):
        r = calcular([6, 6, 6], final=5)
        self.assertEqual((cs.texto(r.ordinaria), r.estado), ('5.50', cs.PENDIENTE_EXTRAORDINARIO))
        self.assertEqual(r.capturable, {cs.FINAL, cs.EXTRAORDINARIO})

    def test_extraordinario_aprobado_queda_tal_cual(self):
        r = calcular([6, 6, 6], final=5, extra=8.5)
        self.assertEqual((r.estado, cs.texto(r.definitiva)), (cs.APROBADA_EXTRAORDINARIO, '8.50'))   # sin tope
        self.assertEqual(r.capturable, {cs.EXTRAORDINARIO})   # el final ya no se corrige
        self.assertEqual(cs.texto(r.ordinaria), '5.50')   # el resultado ordinario se conserva aparte

    def test_extraordinario_reprobado_va_a_regularizacion(self):
        r = calcular([4, 5, 5], extra=5)
        self.assertEqual((r.estado, r.capturable), (cs.PENDIENTE_REGULARIZACION, {cs.EXTRAORDINARIO, cs.REGULARIZACION}))
        aprobada = calcular([4, 5, 5], extra=5, regu=7)
        self.assertEqual((aprobada.estado, cs.texto(aprobada.definitiva)), (cs.APROBADA_REGULARIZACION, '7.00'))
        reprobada = calcular([4, 5, 5], extra=5, regu=4)
        self.assertEqual((reprobada.estado, cs.texto(reprobada.definitiva)), (cs.REPROBADA, '4.00'))
        self.assertTrue(reprobada.reprobada)
        self.assertEqual(reprobada.capturable, {cs.REGULARIZACION})   # no hay más exámenes

    def test_periodo_pendiente_no_cuenta_como_cero(self):
        r = calcular([9, None, 9], final=8)
        self.assertIsNone(r.promedio)
        self.assertIsNone(r.definitiva)
        self.assertEqual((r.estado, r.capturable), (cs.PENDIENTE_PERIODOS, set()))

    def test_examen_final_pendiente_no_da_resultado(self):
        r = calcular([8, 8, 8])
        self.assertIsNone(r.ordinaria)
        self.assertIsNone(r.definitiva)

    def test_no_fija_tres_periodos(self):
        self.assertEqual(cs.texto(calcular([8, 9]).promedio), '8.50')
        self.assertEqual(cs.texto(calcular([10, 9, 9, 10]).promedio), '9.50')
        self.assertEqual(calcular([10, 9, 9, 10]).situacion, cs.EXENTO)

    def test_un_examen_que_ya_no_aplica_se_conserva_pero_no_cuenta(self):
        r = calcular([10, 10, 9], final=6)   # exento: el final capturado antes ya no cuenta
        self.assertEqual(r.estado, cs.APROBADA_EXENTO)
        self.assertEqual(r.no_cuentan, {cs.FINAL})

    def test_truncar(self):
        self.assertEqual(cs.truncar(Fraction(43, 6)), D('7.16'))   # 7.1666…
        self.assertEqual(cs.truncar(Fraction(6)), D('6.00'))
        self.assertEqual(cs.texto(None), '')


# ---------------------------------------------------------------------------
# Base: preparatoria por semestres con 1.º (semestre A) y 2.º (semestre B)
# ---------------------------------------------------------------------------
class BaseSemestresTestCase(BaseTestCase):
    """Ciclo actual con el semestre A (abierto) y el B (pendiente); tres periodos en cada uno. Cálculo I es de 1.º
    (semestre A) y Cálculo II de 2.º (semestre B), las dos con la docente Marta. Ana y Beto están en 1.º."""

    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.primero, self.segundo = crear_grado('PREPARATORIA', 1), crear_grado('PREPARATORIA', 2)
        self.sem_a = Semestre.objects.create(ciclo=self.ciclo, clave='A', fecha_inicio=self.ciclo.fecha_inicio,
                                             fecha_fin=hoy() + timedelta(days=40), estado=Semestre.ABIERTO)
        self.sem_b = Semestre.objects.create(ciclo=self.ciclo, clave='B', fecha_inicio=hoy() + timedelta(days=41), fecha_fin=self.ciclo.fecha_fin)
        dias = lambda d: hoy() + timedelta(days=d)   # noqa: E731
        self.periodos_a = [
            Periodo.objects.create(ciclo=self.ciclo, nivel='PREPARATORIA', nombre='Parcial 1', fecha_inicio=self.ciclo.fecha_inicio, fecha_fin=dias(-31), semestre=self.sem_a),
            Periodo.objects.create(ciclo=self.ciclo, nivel='PREPARATORIA', nombre='Parcial 2', fecha_inicio=dias(-30), fecha_fin=dias(-1), semestre=self.sem_a),
            Periodo.objects.create(ciclo=self.ciclo, nivel='PREPARATORIA', nombre='Parcial 3', fecha_inicio=dias(0), fecha_fin=dias(20), semestre=self.sem_a),
        ]
        self.periodos_b = [
            Periodo.objects.create(ciclo=self.ciclo, nivel='PREPARATORIA', nombre=f'Parcial {n} B', fecha_inicio=dias(41 + 60 * (n - 1)),
                                   fecha_fin=dias(100 + 60 * (n - 1)), semestre=self.sem_b)
            for n in (1, 2, 3)
        ]
        self.docente = crear_usuario('marta', Rol.objects.get(grupo__name='Docente'))
        self.profesor = crear_profesor(usuario=self.docente)
        self.calculo1 = materia_en_grado('CAL1', self.primero, self.ciclo, inicio=None, profesor=self.profesor)
        self.calculo2 = materia_en_grado('CAL2', self.segundo, self.ciclo, inicio=None, profesor=self.profesor)
        self.ana = inscribir(crear_alumno(nombre='Ana', apellido_paterno='Aguilar'), self.ciclo, self.primero)
        self.beto = inscribir(crear_alumno(nombre='Beto', apellido_paterno='Barrios'), self.ciclo, self.primero)

    def cerrar_actas(self, asignacion, periodos, finales):
        """Actas cerradas con la calificación final de cada estudiante en cada periodo ({inscripción: [p1, p2, p3]})."""
        for indice, periodo in enumerate(periodos):
            ActaCalificaciones.objects.create(
                asignacion=asignacion, periodo=periodo, estado=ActaCalificaciones.CERRADA, cerrada_en=timezone.now(),
                resultados_cerrados=[{'inscripcion': i.pk, 'final': f'{valores[indice]:.2f}'} for i, valores in finales.items() if valores[indice] is not None],
            )

    def guardar_examen(self, asignacion, inscripcion, tipo, valor, usuario=None):
        if usuario is not None:
            self.client.force_login(usuario)
        cambio = {'clave': 'x', 'tipo': 'examen', 'id': tipo, 'inscripcion': inscripcion.pk, 'valor': str(valor)}
        return self.client.post(reverse('calificaciones:semestre_guardar', args=[asignacion.pk]), json.dumps({'cambios': [cambio]}),
                                content_type='application/json')

    def resultado(self, asignacion, inscripcion):
        return semestres.resultado_de(inscripcion, asignacion)


@PRUEBAS
class HojaSemestralTests(BaseSemestresTestCase):
    def test_cada_materia_usa_solo_los_periodos_de_su_semestre(self):
        self.assertEqual(reglas.periodos_de(self.calculo1), self.periodos_a)
        self.assertEqual(reglas.periodos_de(self.calculo2), self.periodos_b)
        self.assertEqual(semestres.hoja(self.calculo1).periodos, self.periodos_a)

    def test_solo_cuentan_las_actas_cerradas(self):
        self.cerrar_actas(self.calculo1, self.periodos_a[:2], {self.ana: [9, 9, None]})
        ActaCalificaciones.objects.create(asignacion=self.calculo1, periodo=self.periodos_a[2], resultados_cerrados=[])   # en captura
        r = self.resultado(self.calculo1, self.ana)
        self.assertEqual(r.estado, cs.PENDIENTE_PERIODOS)
        self.assertEqual(semestres.hoja(self.calculo1).periodos_sin_cerrar, [self.periodos_a[2]])

    def test_la_hoja_en_calificaciones_muestra_el_resultado(self):
        self.cerrar_actas(self.calculo1, self.periodos_a, {self.ana: [9.6, 9.6, 9.6], self.beto: [8, 7, 9]})
        respuesta = self.client.get(reverse('calificaciones:inicio'), {'ciclo': self.ciclo.pk, 'materia': self.calculo1.pk, 'periodo': 'semestre'})
        self.assertTrue(respuesta.context['vista_semestre'])
        filas = {f.nombre: f for f in respuesta.context['filas_semestre']}
        self.assertEqual(filas[str(self.ana.alumno)].calc['estado'], 'Aprobada (exento)')
        self.assertContains(respuesta, 'exención')
        self.assertEqual(filas[str(self.beto.alumno)].calc['habilita-FINAL'], '1')

    def test_impresion_y_excel_identifican_ciclo_y_semestre(self):
        self.cerrar_actas(self.calculo1, self.periodos_a, {self.ana: [8, 7, 9]})
        hoja = self.client.get(reverse('calificaciones:semestre_imprimir', args=[self.calculo1.pk]))
        self.assertContains(hoja, 'Semestre A')
        self.assertContains(hoja, self.ciclo.nombre)
        excel = self.client.get(reverse('calificaciones:semestre_excel', args=[self.calculo1.pk]))
        self.assertEqual(excel.status_code, 200)
        self.assertIn('semestre-a', excel['Content-Disposition'])


@PRUEBAS
class CapturaDeExamenesTests(BaseSemestresTestCase):
    def setUp(self):
        super().setUp()
        self.cerrar_actas(self.calculo1, self.periodos_a, {self.ana: [8, 7, 9], self.beto: [10, 9.5, 9.5]})

    def test_el_docente_captura_el_final_y_se_habilita_el_extraordinario(self):
        respuesta = self.guardar_examen(self.calculo1, self.ana, cs.FINAL, '3', usuario=self.docente)
        datos = respuesta.json()
        self.assertTrue(datos['ok'])
        fila = datos['filas'][str(self.ana.pk)]
        self.assertEqual((fila['ordinaria'], fila['estado'], fila['habilita-EXTRAORDINARIO']), ('5.50', 'Pendiente: extraordinario', '1'))
        self.assertEqual(CambioSemestre.objects.filter(accion=CambioSemestre.EXAMEN, inscripcion=self.ana).count(), 1)

    def test_no_se_captura_lo_que_no_corresponde(self):
        exento = self.guardar_examen(self.calculo1, self.beto, cs.FINAL, '8').json()   # Beto: 9.66, exento
        self.assertFalse(exento['ok'])
        self.assertIn('exento', exento['resultados'][0]['error'])
        sin_reprobar = self.guardar_examen(self.calculo1, self.ana, cs.EXTRAORDINARIO, '8').json()
        self.assertFalse(sin_reprobar['ok'])
        self.assertFalse(ExamenSemestral.objects.exists())

    def test_solo_se_corrige_el_ultimo_examen(self):
        self.guardar_examen(self.calculo1, self.ana, cs.FINAL, '3')
        self.guardar_examen(self.calculo1, self.ana, cs.EXTRAORDINARIO, '9')
        respuesta = self.guardar_examen(self.calculo1, self.ana, cs.FINAL, '10').json()
        self.assertFalse(respuesta['ok'])
        self.assertEqual(ExamenSemestral.objects.get(inscripcion=self.ana, tipo=cs.FINAL).valor, D('3'))

    def test_otro_docente_no_captura(self):
        otra = crear_usuario('otra', Rol.objects.get(grupo__name='Docente'))
        crear_profesor(usuario=otra, telefono='3530000000')
        self.client.force_login(otra)
        respuesta = self.client.post(reverse('calificaciones:semestre_guardar', args=[self.calculo1.pk]), json.dumps({'cambios': []}),
                                     content_type='application/json')
        self.assertEqual(respuesta.status_code, 403)

    def test_semestre_pendiente_no_captura_periodos_ni_examenes(self):
        acta = reglas.acta_para(self.calculo2, self.periodos_b[0])
        self.assertIn('todavía no se abre', reglas.motivo_de_solo_lectura(acta, self.admin))
        beto_b = inscribir(crear_alumno(nombre='Ceci'), self.ciclo, self.segundo)
        respuesta = self.guardar_examen(self.calculo2, beto_b, cs.FINAL, '8')
        self.assertEqual(respuesta.status_code, 409)


@PRUEBAS
class CierreDeSemestreTests(BaseSemestresTestCase):
    def completar_a(self):
        self.cerrar_actas(self.calculo1, self.periodos_a, {self.ana: [6, 6, 6], self.beto: [10, 9.5, 9.5]})

    def test_no_se_cierra_con_la_evaluacion_ordinaria_pendiente(self):
        self.cerrar_actas(self.calculo1, self.periodos_a[:2], {self.ana: [6, 6, None], self.beto: [10, 9.5, None]})
        problemas = semestres.problemas_para_cerrar(self.sem_a)
        self.assertTrue(any('acta' in p for p in problemas))
        self.client.post(reverse('ciclos:semestre_cerrar', args=[self.sem_a.pk]))
        self.sem_a.refresh_from_db()
        self.assertTrue(self.sem_a.abierto)
        # con las actas cerradas, falta el examen final de Ana
        self.cerrar_actas(self.calculo1, self.periodos_a[2:], {self.ana: [6], self.beto: [9.5]})
        self.assertTrue(any('examen' in p for p in semestres.problemas_para_cerrar(self.sem_a)))

    def test_cerrar_resume_bloquea_lo_ordinario_y_deja_los_procesos(self):
        self.completar_a()
        self.guardar_examen(self.calculo1, self.ana, cs.FINAL, '4')   # 5.00: extraordinario
        pagina = self.client.get(reverse('ciclos:semestre_cerrar', args=[self.sem_a.pk]))
        self.assertEqual(pagina.context['datos'].procesos_abiertos, 1)
        self.client.post(reverse('ciclos:semestre_cerrar', args=[self.sem_a.pk]))
        self.sem_a.refresh_from_db()
        self.assertTrue(self.sem_a.cerrado)
        self.assertTrue(CicloEscolar.objects.get(pk=self.ciclo.pk).activo)   # el ciclo sigue abierto
        self.sem_b.refresh_from_db()
        self.assertEqual(self.sem_b.estado, Semestre.PENDIENTE)   # el otro semestre no cambia
        cierre = self.sem_a.cambios.get(accion=CambioSemestre.CIERRE)
        self.assertEqual(len(cierre.datos['resultados']), 2)
        # lo ordinario queda bloqueado
        acta = ActaCalificaciones.objects.filter(asignacion=self.calculo1).first()
        with self.assertRaises(reglas.CapturaRechazada):
            reglas.reabrir(acta, 'Corrección de captura.', self.admin)
        self.assertFalse(self.guardar_examen(self.calculo1, self.ana, cs.FINAL, '9').json()['ok'])
        with self.assertRaises(reglas.CapturaRechazada):
            reglas.crear_inicial(self.calculo1.materia, self.ciclo, self.admin)
        editar = self.client.post(reverse('periodos:editar', args=[self.periodos_a[0].pk]), {})
        self.assertRedirects(editar, f"{reverse('periodos:lista')}?ciclo={self.ciclo.pk}")
        # el extraordinario pendiente sí se captura
        self.assertTrue(self.guardar_examen(self.calculo1, self.ana, cs.EXTRAORDINARIO, '7').json()['ok'])
        self.assertEqual(self.resultado(self.calculo1, self.ana).estado, cs.APROBADA_EXTRAORDINARIO)

    def test_reabrir_exige_permisos_y_motivo_y_el_recierre_registra_cambios(self):
        self.completar_a()
        self.guardar_examen(self.calculo1, self.ana, cs.FINAL, '8')
        semestres.cerrar(self.sem_a, self.admin)
        self.con_permisos('change_cicloescolar', 'view_cicloescolar')   # sin «reabrir calificaciones»
        self.assertEqual(self.client.post(reverse('ciclos:semestre_reabrir', args=[self.sem_a.pk]), {'motivo': 'Error en el parcial 2.'}).status_code, 403)
        self.client.force_login(self.admin)
        self.client.post(reverse('ciclos:semestre_reabrir', args=[self.sem_a.pk]), {'motivo': ''})
        self.sem_a.refresh_from_db()
        self.assertTrue(self.sem_a.cerrado)
        self.client.post(reverse('ciclos:semestre_reabrir', args=[self.sem_a.pk]), {'motivo': 'Error en el parcial 2.'})
        self.sem_a.refresh_from_db()
        self.assertTrue(self.sem_a.abierto)
        reapertura = self.sem_a.cambios.get(accion=CambioSemestre.REAPERTURA)
        self.assertEqual((reapertura.motivo, reapertura.usuario), ('Error en el parcial 2.', self.admin))
        self.guardar_examen(self.calculo1, self.ana, cs.FINAL, '10')   # 8.00 → definitiva 8.00
        semestres.cerrar(self.sem_a, self.admin)
        cambios = semestres.cambios_desde_reapertura(self.sem_a)
        self.assertEqual([(c['antes'], c['despues']) for c in cambios], [('7.00', '8.00')])

    def test_solo_quien_edita_ciclos_cierra_un_semestre(self):
        self.completar_a()
        self.guardar_examen(self.calculo1, self.ana, cs.FINAL, '8')
        self.client.force_login(self.docente)
        self.assertEqual(self.client.post(reverse('ciclos:semestre_cerrar', args=[self.sem_a.pk])).status_code, 403)
        self.sem_a.refresh_from_db()
        self.assertTrue(self.sem_a.abierto)

    def test_el_ciclo_no_se_cierra_con_semestres_abiertos(self):
        self.client.post(reverse('ciclos:cerrar', args=[self.ciclo.pk]))
        self.assertTrue(CicloEscolar.objects.get(pk=self.ciclo.pk).activo)
        Semestre.objects.filter(ciclo=self.ciclo).update(estado=Semestre.CERRADO)
        self.client.post(reverse('ciclos:cerrar', args=[self.ciclo.pk]))
        self.assertFalse(CicloEscolar.objects.get(pk=self.ciclo.pk).activo)


@PRUEBAS
class PasoDeSemestreTests(BaseSemestresTestCase):
    def pasar(self):
        return self.client.post(reverse('inscripciones:semestre'), {f'grado_{self.primero.pk}': str(self.segundo.pk), 'fecha': hoy().isoformat()})

    def test_pasan_al_grado_siguiente_y_la_inscripcion_del_a_queda_concluida(self):
        self.pasar()
        self.ana.refresh_from_db()
        self.assertEqual((self.ana.activa, self.ana.concluida), (False, True))
        nueva = Inscripcion.objects.get(alumno=self.ana.alumno, ciclo=self.ciclo, activa=True)
        self.assertEqual((nueva.grado, nueva.grupo), (self.segundo, grupo_de(self.segundo)))
        # no es una baja
        lista = self.client.get(reverse('inscripciones:lista'))
        self.assertEqual((lista.context['conteos']['bajas'], lista.context['conteos']['concluidas']), (0, 2))
        self.client.post(reverse('inscripciones:reactivar', args=[self.ana.pk]))
        self.ana.refresh_from_db()
        self.assertFalse(self.ana.activa)
        # sigue en las listas de calificaciones de su semestre, pero ya no en el pase de lista
        self.assertIn(self.ana, semestres.estudiantes_de(self.calculo1))
        self.assertNotIn(self.ana, list(inscripciones_de(self.calculo1)))
        self.assertIn(nueva, list(inscripciones_de(self.calculo2)))

    def test_escenario_extraordinario_del_a_con_el_b_abierto(self):
        """Cerrar la evaluación ordinaria del semestre A, comenzar el B y registrar un extraordinario pendiente del A, con
        el mismo ciclo abierto y sin alterar las calificaciones del B."""
        self.cerrar_actas(self.calculo1, self.periodos_a, {self.ana: [5, 5, 5], self.beto: [8, 8, 8]})
        self.guardar_examen(self.calculo1, self.beto, cs.FINAL, '9')
        self.client.post(reverse('ciclos:semestre_cerrar', args=[self.sem_a.pk]))
        self.pasar()
        self.client.post(reverse('ciclos:semestre_abrir', args=[self.sem_b.pk]))
        self.sem_a.refresh_from_db()
        self.sem_b.refresh_from_db()
        self.assertEqual((self.sem_a.estado, self.sem_b.estado), (Semestre.CERRADO, Semestre.ABIERTO))
        ana_b = Inscripcion.objects.get(alumno=self.ana.alumno, ciclo=self.ciclo, activa=True)
        self.cerrar_actas(self.calculo2, self.periodos_b[:1], {ana_b: [9, None, None]})
        antes_b = self.resultado(self.calculo2, ana_b)

        # El grado del A se oculta en el semestre B: su materia sigue en Calificaciones para el extraordinario
        self.primero.visible = False
        self.primero.save()
        self.client.force_login(self.docente)
        pagina = self.client.get(reverse('calificaciones:inicio'), {'ciclo': self.ciclo.pk, 'materia': self.calculo1.pk, 'periodo': 'semestre'})
        self.assertEqual(pagina.status_code, 200)
        respuesta = self.guardar_examen(self.calculo1, self.ana, cs.EXTRAORDINARIO, '6.5').json()
        self.assertTrue(respuesta['ok'])

        self.assertEqual(self.resultado(self.calculo1, self.ana).estado, cs.APROBADA_EXTRAORDINARIO)
        self.assertEqual(cs.texto(self.resultado(self.calculo1, self.ana).definitiva), '6.50')
        despues_b = self.resultado(self.calculo2, ana_b)
        self.assertEqual((antes_b.periodos, antes_b.estado), (despues_b.periodos, despues_b.estado))
        self.assertTrue(CicloEscolar.objects.get(pk=self.ciclo.pk).activo)
        self.assertFalse(ExamenSemestral.objects.filter(asignacion=self.calculo2).exists())

    def test_regularizacion_y_reprobacion_definitiva(self):
        self.cerrar_actas(self.calculo1, self.periodos_a, {self.ana: [4, 4, 4], self.beto: [9.5, 9.5, 9.5]})
        semestres.cerrar(self.sem_a, self.admin)
        self.guardar_examen(self.calculo1, self.ana, cs.EXTRAORDINARIO, '5')
        self.assertEqual(self.resultado(self.calculo1, self.ana).estado, cs.PENDIENTE_REGULARIZACION)
        self.guardar_examen(self.calculo1, self.ana, cs.REGULARIZACION, '3')
        r = self.resultado(self.calculo1, self.ana)
        self.assertEqual((r.estado, cs.texto(r.definitiva)), (cs.REPROBADA, '3.00'))
        # se conservan por separado
        self.assertEqual(sorted(ExamenSemestral.objects.filter(inscripcion=self.ana).values_list('tipo', 'valor')),
                         [(cs.EXTRAORDINARIO, D('5.00')), (cs.REGULARIZACION, D('3.00'))])


@PRUEBAS
class PeriodosYPortalTests(BaseSemestresTestCase):
    def test_el_periodo_toma_el_semestre_por_sus_fechas_y_no_entra_a_uno_cerrado(self):
        datos = {'nivel': 'PREPARATORIA', 'nombre': 'Final B', 'fecha_inicio': self.periodos_b[2].fecha_fin + timedelta(days=1),
                 'fecha_fin': self.periodos_b[2].fecha_fin + timedelta(days=5), 'semestre': ''}
        self.client.post(f"{reverse('periodos:crear')}?ciclo={self.ciclo.pk}", datos)
        self.assertEqual(Periodo.objects.get(nombre='Final B').semestre, self.sem_b)
        Semestre.objects.filter(pk=self.sem_a.pk).update(estado=Semestre.CERRADO)
        datos.update(nombre='Extra A', fecha_inicio=self.periodos_a[2].fecha_fin + timedelta(days=1), fecha_fin=self.periodos_a[2].fecha_fin + timedelta(days=3))
        self.client.post(f"{reverse('periodos:crear')}?ciclo={self.ciclo.pk}", datos)
        self.assertFalse(Periodo.objects.filter(nombre='Extra A').exists())

    def test_el_portal_muestra_el_semestre_solo_cerrado(self):
        from PortalEstudiantes.resumen import semestrales
        self.cerrar_actas(self.calculo1, self.periodos_a, {self.ana: [9.5, 9.5, 9.5], self.beto: [9.5, 9.5, 9.5]})
        self.assertEqual(semestrales(self.ana.alumno, self.ciclo), [])   # abierto: todavía puede cambiar
        semestres.cerrar(self.sem_a, self.admin)
        lista = semestrales(self.ana.alumno, self.ciclo)
        self.assertEqual(len(lista), 1)
        self.assertEqual((lista[0].filas[0]['definitiva'], lista[0].filas[0]['exento']), ('9.50', True))


@PRUEBAS
class CalculoDePeriodoIntegradoTests(BaseSemestresTestCase):
    """El periodo se sigue calculando igual (rubros, porcentajes y actividades) y su final cerrada alimenta el semestre."""

    def test_la_final_del_acta_cerrada_entra_al_promedio(self):
        configuracion = reglas.crear_inicial(self.calculo1.materia, self.ciclo, self.admin)
        conducta, procedimientos, examenes = configuracion.rubros.order_by('orden')
        acta = reglas.acta_para(self.calculo1, self.periodos_a[2])
        actividades = [reglas.crear_actividad(acta, {'rubro': r, 'nombre': n, 'fecha': hoy()}, self.admin)
                       for r, n in ((procedimientos, 'Mapa'), (procedimientos, 'Ensayo'), (examenes, 'Examen 1'), (examenes, 'Examen 2'))]
        cambios = []
        for inscripcion in (self.ana, self.beto):
            cambios.append({'clave': 'c', 'tipo': 'rubro', 'id': conducta.pk, 'inscripcion': inscripcion.pk, 'valor': '9'})
            for actividad, valor in zip(actividades, ('8', '10', '7', '9')):
                cambios.append({'clave': 'a', 'tipo': 'actividad', 'id': actividad.pk, 'inscripcion': inscripcion.pk, 'valor': valor})
        reglas.guardar_capturas(acta, self.admin, cambios)
        reglas.cerrar(acta, self.admin)
        self.cerrar_actas(self.calculo1, self.periodos_a[:2], {self.ana: [8.70, 8.70, None], self.beto: [8.70, 8.70, None]})
        r = self.resultado(self.calculo1, self.ana)
        self.assertEqual(r.periodos[2], D('8.70'))   # 1.80 + 4.50 + 2.40, el caso de referencia del formato
        self.assertEqual((cs.texto(r.promedio), r.estado), ('8.70', cs.PENDIENTE_FINAL))
