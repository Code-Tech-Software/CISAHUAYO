"""Reglas del control de asistencia (Alumnos/asistencias.py): entrada, materias automáticas, cierre y justificaciones."""
from datetime import time, timedelta
from unittest.mock import patch

from django.db import IntegrityError, transaction

from Alumnos import asistencias as reglas
from Alumnos.models import (
    AsistenciaGeneral,
    AsistenciaMateria,
    CierreDia,
    ConfiguracionAsistencia,
    DiaNoLectivo,
    HorarioMateria,
    Justificacion,
    Materia,
)
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseAsistenciaTestCase,
    ciclo_cerrado_de_prueba,
    crear_alumno,
    crear_grado,
    hoy,
    inscribir_antes,
    lunes,
    materia_en_grado,
    momento,
)


# ---------------------------------------------------------------------------
# Calendario
# ---------------------------------------------------------------------------
@PRUEBAS
class CalendarioTests(BaseAsistenciaTestCase):
    def test_el_ciclo_de_una_fecha(self):
        self.assertEqual(reglas.ciclo_de_fecha(lunes()), self.ciclo)
        self.assertIsNone(reglas.ciclo_de_fecha(hoy() + timedelta(days=900)))

    def test_un_lunes_del_ciclo_es_dia_de_clases(self):
        self.assertIsNone(reglas.motivo_sin_clases(lunes()))
        self.assertIsNone(reglas.motivo_sin_clases(lunes(), exigir_actual=True))

    def test_fuera_de_un_ciclo(self):
        self.assertIn('fuera de las fechas', reglas.motivo_sin_clases(hoy() + timedelta(days=900)))

    def test_un_dia_sin_clases_registrado(self):
        DiaNoLectivo.objects.create(fecha=lunes(), motivo='Consejo técnico')
        self.assertEqual(reglas.motivo_sin_clases(lunes()), 'Día sin clases: Consejo técnico.')

    def test_fin_de_semana_solo_si_hay_clases_ese_dia(self):
        sabado = lunes() + timedelta(days=5)
        if sabado > hoy():
            sabado -= timedelta(days=7)
        self.assertEqual(reglas.motivo_sin_clases(sabado), 'No hay clases en fin de semana.')
        materia_en_grado('SAB', self.grado, self.ciclo, dia=5)
        self.assertIsNone(reglas.motivo_sin_clases(sabado))

    def test_un_ciclo_cerrado_no_es_el_actual(self):
        cerrado = ciclo_cerrado_de_prueba()
        fecha = cerrado.fecha_inicio + timedelta(days=(7 - cerrado.fecha_inicio.weekday()) % 7)   # un lunes de ese ciclo
        self.assertIsNone(reglas.motivo_sin_clases(fecha))
        self.assertIn('no es el ciclo actual', reglas.motivo_sin_clases(fecha, exigir_actual=True))

    def test_solo_se_captura_en_el_ciclo_actual_y_nunca_en_el_futuro(self):
        self.assertTrue(reglas.asistencia_editable(lunes()))
        self.assertFalse(reglas.asistencia_editable(hoy() + timedelta(days=1)))
        cerrado = ciclo_cerrado_de_prueba()
        self.assertFalse(reglas.asistencia_editable(cerrado.fecha_inicio + timedelta(days=3)))


# ---------------------------------------------------------------------------
# Estados según la hora
# ---------------------------------------------------------------------------
@PRUEBAS
class EstadosTests(BaseAsistenciaTestCase):
    def test_entrada_puntual_o_con_retardo(self):
        configuracion = ConfiguracionAsistencia.cargar()
        self.assertEqual(reglas.estado_de_entrada(time(7, 30), configuracion), 'PRESENTE')
        self.assertEqual(reglas.estado_de_entrada(time(8, 10), configuracion), 'PRESENTE')
        self.assertEqual(reglas.estado_de_entrada(time(8, 10, 59), configuracion), 'PRESENTE')   # se compara por minuto
        self.assertEqual(reglas.estado_de_entrada(time(8, 11), configuracion), 'RETARDO')

    def test_la_tolerancia_es_configurable(self):
        configuracion = ConfiguracionAsistencia.cargar()
        configuracion.tolerancia_minutos = 0
        self.assertEqual(reglas.estado_de_entrada(time(8, 0), configuracion), 'PRESENTE')
        self.assertEqual(reglas.estado_de_entrada(time(8, 1), configuracion), 'RETARDO')

    def test_estado_en_una_clase(self):
        clase = reglas.Clase(self.mat, time(9, 0), time(10, 0))
        self.assertEqual(reglas.estado_en_clase(time(7, 50), clase, 10), 'PRESENTE')
        self.assertEqual(reglas.estado_en_clase(time(9, 10), clase, 10), 'PRESENTE')
        self.assertEqual(reglas.estado_en_clase(time(9, 11), clase, 10), 'RETARDO')
        self.assertEqual(reglas.estado_en_clase(time(9, 59), clase, 10), 'RETARDO')
        self.assertEqual(reglas.estado_en_clase(time(10, 0), clase, 10), 'FALTA')


# ---------------------------------------------------------------------------
# Clases del día
# ---------------------------------------------------------------------------
@PRUEBAS
class ClasesTests(BaseAsistenciaTestCase):
    def test_las_clases_del_dia_van_en_orden_de_hora(self):
        clases = reglas.clases_del_dia(self.grado, self.ciclo, lunes())
        self.assertEqual([(c.asignacion.materia.clave, c.inicio, c.fin) for c in clases],
                         [('MAT', time(8), time(9)), ('ESP', time(9), time(10)), ('CIE', time(11), time(12))])

    def test_varios_bloques_de_una_materia_el_mismo_dia_son_una_sola_clase(self):
        HorarioMateria.objects.create(materia_grado=self.mat, dia_semana=0, hora_inicio=time(12), hora_fin=time(13))
        clase = next(c for c in reglas.clases_del_dia(self.grado, self.ciclo, lunes()) if c.asignacion == self.mat)
        self.assertEqual((clase.inicio, clase.fin), (time(8), time(13)))
        self.assertEqual(clase.bloques, ((time(8), time(9)), (time(12), time(13))))

    def test_no_incluye_otros_dias_materias_quitadas_ni_de_baja(self):
        materia_en_grado('MAR', self.grado, self.ciclo, dia=1)
        materia_en_grado('QUI', self.grado, self.ciclo, activa=False)
        materia_en_grado('BAJ', self.grado, self.ciclo)
        Materia.objects.filter(clave='BAJ').update(activa=False)
        claves = [c.asignacion.materia.clave for c in reglas.clases_del_dia(self.grado, self.ciclo, lunes())]
        self.assertEqual(claves, ['MAT', 'ESP', 'CIE'])

    def test_clases_por_grado_separa_los_grados(self):
        otro = crear_grado('PRIMARIA', 5)
        materia_en_grado('HIS', otro, self.ciclo)
        por_grado = reglas.clases_por_grado(self.ciclo, lunes())
        self.assertEqual({g: len(c) for g, c in por_grado.items()}, {self.grado.pk: 3, otro.pk: 1})

    def test_inscripciones_del_dia(self):
        baja = inscribir_antes(crear_alumno(estatus='BAJA'), self.ciclo, self.grado)
        suspendido = inscribir_antes(crear_alumno(estatus='SUSPENDIDO'), self.ciclo, self.grado)
        inactiva = inscribir_antes(crear_alumno(), self.ciclo, self.grado, activa=False)
        futura = inscribir_antes(crear_alumno(), self.ciclo, self.grado, fecha_inscripcion=lunes() + timedelta(days=1))
        otro_grado = inscribir_antes(crear_alumno(), self.ciclo, crear_grado('PRIMARIA', 5))
        del_dia = set(reglas.inscripciones_del_dia(lunes()))
        self.assertIn(self.inscripcion, del_dia)
        self.assertIn(otro_grado, del_dia)
        self.assertFalse({baja, suspendido, inactiva, futura} & del_dia)
        self.assertEqual(set(reglas.inscripciones_del_dia(lunes(), grado=self.grado)), {self.inscripcion})


# ---------------------------------------------------------------------------
# Buscar al alumno
# ---------------------------------------------------------------------------
@PRUEBAS
class BuscarAlumnoTests(BaseAsistenciaTestCase):
    def test_por_uid_sin_importar_mayusculas(self):
        self.assertEqual(reglas.buscar_alumno('ab12cd34'), (self.alumno, 'UID'))

    def test_por_numero_de_referencia(self):
        self.assertEqual(reglas.buscar_alumno(self.alumno.referencia, 'referencia'), (self.alumno, 'REFERENCIA'))

    def test_si_no_aparece_en_el_modo_se_prueba_el_otro(self):
        self.assertEqual(reglas.buscar_alumno('AB12CD34', 'referencia'), (self.alumno, 'UID'))
        self.assertEqual(reglas.buscar_alumno(self.alumno.referencia, 'uid'), (self.alumno, 'REFERENCIA'))

    def test_ignora_espacios_y_caracteres_de_control(self):
        self.assertEqual(reglas.buscar_alumno('  AB12CD34\r\n')[0], self.alumno)
        self.assertEqual(reglas.buscar_alumno('AB12\x00CD34')[0], self.alumno)

    def test_codigo_desconocido_o_vacio(self):
        for codigo, motivo in (('ZZZ', 'NO_ENCONTRADO'), ('', 'VACIO'), ('   ', 'VACIO'), (None, 'VACIO')):
            with self.assertRaises(reglas.EntradaRechazada) as error:
                reglas.buscar_alumno(codigo)
            self.assertEqual(error.exception.codigo, motivo, repr(codigo))

    def test_un_alumno_sin_uid_no_coincide_con_un_codigo_vacio(self):
        crear_alumno()        # uid nulo
        with self.assertRaises(reglas.EntradaRechazada):
            reglas.buscar_alumno('')


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------
@PRUEBAS
class RegistrarEntradaTests(BaseAsistenciaTestCase):
    def entrar(self, hora=(7, 45), alumno=None, origen='UID', usuario=None):
        return reglas.registrar_entrada(alumno or self.alumno, origen, usuario=usuario, momento=momento(*hora))

    def test_crea_la_asistencia_general_y_la_de_cada_materia_del_dia(self):
        resultado = self.entrar((7, 45), usuario=self.admin)
        self.assertTrue(resultado.creada)
        self.assertEqual(resultado.materias, 3)
        general = AsistenciaGeneral.objects.get(inscripcion=self.inscripcion, fecha=lunes())
        self.assertEqual((general.estado, general.hora_entrada, general.origen, general.registrado_por), ('PRESENTE', time(7, 45), 'UID', self.admin))
        self.assertEqual(self.estados_de_materias(), {'MAT': 'PRESENTE', 'ESP': 'PRESENTE', 'CIE': 'PRESENTE'})
        self.assertEqual(set(AsistenciaMateria.objects.values_list('origen', flat=True)), {'ENTRADA'})

    def test_llegar_despues_de_la_tolerancia_es_retardo_general(self):
        self.entrar((8, 20))
        self.assertEqual(AsistenciaGeneral.objects.get().estado, 'RETARDO')
        # La primera clase ya empezó (retardo), las demás todavía no
        self.assertEqual(self.estados_de_materias(), {'MAT': 'RETARDO', 'ESP': 'PRESENTE', 'CIE': 'PRESENTE'})

    def test_las_clases_que_ya_terminaron_quedan_en_falta(self):
        self.entrar((10, 30))
        self.assertEqual(self.estados_de_materias(), {'MAT': 'FALTA', 'ESP': 'FALTA', 'CIE': 'PRESENTE'})
        nota = AsistenciaMateria.objects.get(materia_grado=self.mat).observaciones
        self.assertIn('10:30', nota)

    def test_llegar_en_medio_de_una_clase_es_retardo_en_ella(self):
        self.entrar((9, 30))
        self.assertEqual(self.estados_de_materias(), {'MAT': 'FALTA', 'ESP': 'RETARDO', 'CIE': 'PRESENTE'})

    def test_si_ya_registro_entrada_no_cambia_nada(self):
        self.entrar((7, 45))
        resultado = self.entrar((9, 30), origen='REFERENCIA')
        self.assertFalse(resultado.creada)
        self.assertEqual(AsistenciaGeneral.objects.count(), 1)
        general = AsistenciaGeneral.objects.get()
        self.assertEqual((general.hora_entrada, general.origen), (time(7, 45), 'UID'))
        self.assertEqual(AsistenciaMateria.objects.count(), 3)

    def test_dos_lecturas_casi_simultaneas_no_duplican(self):
        # La otra lectura ya guardó su registro justo después de que esta comprobó que no existía
        existente = AsistenciaGeneral.objects.create(inscripcion=self.inscripcion, fecha=lunes(), estado='PRESENTE', hora_entrada=time(7, 40), origen='UID')
        real = AsistenciaGeneral.objects.filter
        llamadas = []

        def filtro(*args, **kwargs):
            llamadas.append(1)
            return AsistenciaGeneral.objects.none() if len(llamadas) == 1 else real(*args, **kwargs)

        with patch.object(AsistenciaGeneral.objects, 'filter', side_effect=filtro):
            resultado = self.entrar((7, 45))
        self.assertFalse(resultado.creada)
        self.assertEqual(resultado.asistencia, existente)
        self.assertEqual(AsistenciaGeneral.objects.count(), 1)

    def test_no_pisa_la_asistencia_que_un_profesor_ya_capturo(self):
        AsistenciaMateria.objects.create(inscripcion=self.inscripcion, materia_grado=self.mat, fecha=lunes(), estado='FALTA', origen='PASE')
        self.entrar((7, 45))
        self.assertEqual(self.estados_de_materias()['MAT'], 'FALTA')
        self.assertEqual(AsistenciaMateria.objects.count(), 3)

    def test_rechaza_a_los_alumnos_sin_estatus_activo(self):
        for estatus in ('BAJA', 'EGRESADO', 'SUSPENDIDO'):
            alumno = crear_alumno(estatus=estatus)
            inscribir_antes(alumno, self.ciclo, self.grado)
            with self.assertRaises(reglas.EntradaRechazada) as error:
                self.entrar(alumno=alumno)
            self.assertEqual(error.exception.codigo, estatus)
        self.assertFalse(AsistenciaGeneral.objects.exists())

    def test_rechaza_un_dia_sin_clases(self):
        DiaNoLectivo.objects.create(fecha=lunes(), motivo='Puente')
        with self.assertRaises(reglas.EntradaRechazada) as error:
            self.entrar()
        self.assertEqual(error.exception.codigo, 'SIN_CLASES')
        self.assertIn('Puente', error.exception.mensaje)

    def test_rechaza_a_quien_no_esta_inscrito_en_el_ciclo(self):
        sin_inscripcion = crear_alumno()
        with self.assertRaises(reglas.EntradaRechazada) as error:
            self.entrar(alumno=sin_inscripcion)
        self.assertEqual(error.exception.codigo, 'SIN_INSCRIPCION')
        self.inscripcion.activa = False
        self.inscripcion.save()
        with self.assertRaises(reglas.EntradaRechazada):
            self.entrar()

    def test_un_grado_sin_horario_solo_registra_la_general(self):
        otro = crear_grado('PRIMARIA', 5)
        alumno = crear_alumno()
        inscripcion = inscribir_antes(alumno, self.ciclo, otro)
        resultado = self.entrar(alumno=alumno)
        self.assertEqual(resultado.materias, 0)
        self.assertTrue(AsistenciaGeneral.objects.filter(inscripcion=inscripcion).exists())


# ---------------------------------------------------------------------------
# Captura de quien administra
# ---------------------------------------------------------------------------
@PRUEBAS
class FijarGeneralTests(BaseAsistenciaTestCase):
    def test_una_falta_general_es_falta_en_todas_las_materias(self):
        reglas.registrar_entrada(self.alumno, 'UID', momento=momento(7, 45))
        reglas.fijar_asistencia_general(self.inscripcion, lunes(), 'FALTA', observaciones='Enfermo', usuario=self.admin)
        general = AsistenciaGeneral.objects.get()
        self.assertEqual((general.estado, general.hora_entrada, general.observaciones), ('FALTA', None, 'Enfermo'))
        self.assertEqual(self.estados_de_materias(), {'MAT': 'FALTA', 'ESP': 'FALTA', 'CIE': 'FALTA'})

    def test_crear_una_presencia_manual_crea_sus_materias(self):
        reglas.fijar_asistencia_general(self.inscripcion, lunes(), 'PRESENTE', hora=time(7, 50), usuario=self.admin)
        general = AsistenciaGeneral.objects.get()
        self.assertEqual((general.origen, general.hora_entrada, general.registrado_por), ('MANUAL', time(7, 50), self.admin))
        self.assertEqual(self.estados_de_materias(), {'MAT': 'PRESENTE', 'ESP': 'PRESENTE', 'CIE': 'PRESENTE'})

    def test_pasar_de_falta_a_presente_recalcula_lo_que_genero_el_sistema(self):
        reglas.fijar_asistencia_general(self.inscripcion, lunes(), 'FALTA')
        reglas.fijar_asistencia_general(self.inscripcion, lunes(), 'RETARDO', hora=time(9, 30))
        self.assertEqual(self.estados_de_materias(), {'MAT': 'FALTA', 'ESP': 'RETARDO', 'CIE': 'PRESENTE'})

    def test_el_pase_de_lista_del_profesor_se_respeta(self):
        reglas.registrar_entrada(self.alumno, 'UID', momento=momento(7, 45))
        AsistenciaMateria.objects.filter(materia_grado=self.mat).update(estado='FALTA', origen='PASE')
        reglas.fijar_asistencia_general(self.inscripcion, lunes(), 'PRESENTE', hora=time(7, 40))
        self.assertEqual(self.estados_de_materias()['MAT'], 'FALTA')

    def test_sin_propagar_solo_cambia_la_general(self):
        reglas.registrar_entrada(self.alumno, 'UID', momento=momento(7, 45))
        reglas.fijar_asistencia_general(self.inscripcion, lunes(), 'FALTA', propagar=False)
        self.assertEqual(self.estados_de_materias(), {'MAT': 'PRESENTE', 'ESP': 'PRESENTE', 'CIE': 'PRESENTE'})


# ---------------------------------------------------------------------------
# Pase de lista del profesor
# ---------------------------------------------------------------------------
@PRUEBAS
class PaseDeListaTests(BaseAsistenciaTestCase):
    def setUp(self):
        super().setUp()
        self.otro = inscribir_antes(crear_alumno(), self.ciclo, self.grado)

    def pase(self, filas):
        return reglas.guardar_pase_de_lista(self.mat, lunes(), filas, usuario=self.admin)

    def test_guarda_lo_que_decide_el_profesor(self):
        reglas.registrar_entrada(self.alumno, 'UID', momento=momento(7, 45))
        self.pase([(self.inscripcion, 'FALTA', 'Se salió'), (self.otro, 'PRESENTE', '')])
        registro = AsistenciaMateria.objects.get(inscripcion=self.inscripcion, materia_grado=self.mat)
        self.assertEqual((registro.estado, registro.observaciones, registro.origen, registro.registrado_por), ('FALTA', 'Se salió', 'PASE', self.admin))
        self.assertEqual(AsistenciaMateria.objects.get(inscripcion=self.otro, materia_grado=self.mat).estado, 'PRESENTE')

    def test_solo_toca_esa_materia_y_ese_dia(self):
        reglas.registrar_entrada(self.alumno, 'UID', momento=momento(7, 45))
        self.pase([(self.inscripcion, 'FALTA', '')])
        self.assertEqual(self.estados_de_materias(), {'MAT': 'FALTA', 'ESP': 'PRESENTE', 'CIE': 'PRESENTE'})

    def test_presente_en_clase_sin_entrada_crea_la_asistencia_general(self):
        self.pase([(self.otro, 'PRESENTE', '')])
        general = AsistenciaGeneral.objects.get(inscripcion=self.otro)
        self.assertEqual((general.estado, general.origen, general.hora_entrada), ('PRESENTE', 'MANUAL', None))
        self.assertIn('pase de lista', general.observaciones)

    def test_presente_en_clase_corrige_una_falta_general(self):
        AsistenciaGeneral.objects.create(inscripcion=self.otro, fecha=lunes(), estado='FALTA', origen='CIERRE')
        self.pase([(self.otro, 'RETARDO', '')])
        self.assertEqual(AsistenciaGeneral.objects.get(inscripcion=self.otro).estado, 'PRESENTE')

    def test_marcar_falta_no_crea_asistencia_general(self):
        self.pase([(self.otro, 'FALTA', '')])
        self.assertFalse(AsistenciaGeneral.objects.filter(inscripcion=self.otro).exists())

    def test_no_cambia_la_general_de_quien_ya_estaba_presente_o_con_retardo(self):
        reglas.registrar_entrada(self.alumno, 'UID', momento=momento(8, 30))
        self.pase([(self.inscripcion, 'PRESENTE', '')])
        general = AsistenciaGeneral.objects.get(inscripcion=self.inscripcion)
        self.assertEqual((general.estado, general.origen), ('RETARDO', 'UID'))

    def test_guardar_de_nuevo_actualiza_sin_duplicar(self):
        self.pase([(self.otro, 'FALTA', '')])
        self.pase([(self.otro, 'PRESENTE', 'Llegó')])
        registros = AsistenciaMateria.objects.filter(inscripcion=self.otro, materia_grado=self.mat)
        self.assertEqual([(r.estado, r.observaciones) for r in registros], [('PRESENTE', 'Llegó')])

    def test_sin_filas_no_hace_nada(self):
        self.assertEqual(self.pase([]), 0)


# ---------------------------------------------------------------------------
# Cierre del día
# ---------------------------------------------------------------------------
@PRUEBAS
class CierreTests(BaseAsistenciaTestCase):
    def setUp(self):
        super().setUp()
        self.ausente = inscribir_antes(crear_alumno(), self.ciclo, self.grado)
        reglas.registrar_entrada(self.alumno, 'UID', momento=momento(7, 45))

    def test_genera_la_falta_general_y_de_cada_materia_a_quien_no_entro(self):
        faltas = reglas.cerrar_dia(lunes(), usuario=self.admin)
        self.assertEqual(faltas, 1)
        general = AsistenciaGeneral.objects.get(inscripcion=self.ausente)
        self.assertEqual((general.estado, general.origen, general.registrado_por), ('FALTA', 'CIERRE', self.admin))
        self.assertEqual(self.estados_de_materias(self.ausente), {'MAT': 'FALTA', 'ESP': 'FALTA', 'CIE': 'FALTA'})
        self.assertEqual(set(AsistenciaMateria.objects.filter(inscripcion=self.ausente).values_list('origen', flat=True)), {'CIERRE'})

    def test_no_cambia_lo_de_quien_si_entro(self):
        reglas.cerrar_dia(lunes())
        self.assertEqual(AsistenciaGeneral.objects.get(inscripcion=self.inscripcion).origen, 'UID')
        self.assertEqual(self.estados_de_materias(), {'MAT': 'PRESENTE', 'ESP': 'PRESENTE', 'CIE': 'PRESENTE'})

    def test_completa_las_materias_que_le_faltan_a_quien_si_entro(self):
        materia_en_grado('ART', self.grado, self.ciclo, inicio=(12, 0), fin=(13, 0))      # horario agregado después de su entrada
        reglas.cerrar_dia(lunes())
        self.assertEqual(self.estados_de_materias()['ART'], 'PRESENTE')

    def test_se_puede_repetir(self):
        reglas.cerrar_dia(lunes())
        conteo = (AsistenciaGeneral.objects.count(), AsistenciaMateria.objects.count())
        self.assertEqual(reglas.cerrar_dia(lunes()), 0)
        self.assertEqual((AsistenciaGeneral.objects.count(), AsistenciaMateria.objects.count()), conteo)
        self.assertEqual(CierreDia.objects.count(), 1)

    def test_deja_constancia_del_cierre(self):
        reglas.cerrar_dia(lunes(), usuario=self.admin, automatico=True)
        cierre = CierreDia.objects.get()
        self.assertEqual((cierre.fecha, cierre.faltas, cierre.automatico, cierre.cerrado_por), (lunes(), 1, True, self.admin))

    def test_quien_ya_tenia_falta_sigue_igual_y_sus_materias_pendientes_son_falta(self):
        AsistenciaGeneral.objects.create(inscripcion=self.ausente, fecha=lunes(), estado='FALTA', origen='MANUAL')
        self.assertEqual(reglas.cerrar_dia(lunes()), 0)
        self.assertEqual(self.estados_de_materias(self.ausente), {'MAT': 'FALTA', 'ESP': 'FALTA', 'CIE': 'FALTA'})

    def test_no_cierra_un_dia_sin_clases_ni_el_futuro(self):
        DiaNoLectivo.objects.create(fecha=lunes(), motivo='Asueto')
        self.assertIsNone(reglas.cerrar_dia(lunes()))
        self.assertIsNone(reglas.cerrar_dia(hoy() + timedelta(days=1)))
        self.assertFalse(CierreDia.objects.exists())
        self.assertFalse(AsistenciaGeneral.objects.filter(inscripcion=self.ausente).exists())

    def test_no_incluye_a_quien_no_debia_asistir(self):
        baja = inscribir_antes(crear_alumno(estatus='BAJA'), self.ciclo, self.grado)
        suspendido = inscribir_antes(crear_alumno(estatus='SUSPENDIDO'), self.ciclo, self.grado)
        reglas.cerrar_dia(lunes())
        self.assertFalse(AsistenciaGeneral.objects.filter(inscripcion__in=[baja, suspendido]).exists())

    def test_dias_pendientes_son_los_anteriores_con_entradas_sin_cerrar(self):
        martes = lunes() - timedelta(days=6)      # un martes anterior (si hoy es lunes, el de la semana pasada)
        materia_en_grado('MAR', self.grado, self.ciclo, dia=1)
        reglas.registrar_entrada(self.alumno, 'UID', momento=momento(7, 45, martes))
        dias = reglas.dias_pendientes_de_cierre()
        self.assertEqual(dias, sorted({d for d in (martes, lunes()) if d < hoy()}))

    def test_los_dias_cerrados_o_sin_clases_ya_no_estan_pendientes(self):
        hace_una_semana = lunes() - timedelta(days=7)
        reglas.registrar_entrada(self.alumno, 'UID', momento=momento(7, 45, hace_una_semana))
        self.assertIn(hace_una_semana, reglas.dias_pendientes_de_cierre())
        reglas.cerrar_dia(hace_una_semana)
        self.assertNotIn(hace_una_semana, reglas.dias_pendientes_de_cierre())

    def test_cierre_automatico_una_vez_por_dia(self):
        hace_una_semana = lunes() - timedelta(days=7)
        reglas.registrar_entrada(self.alumno, 'UID', momento=momento(7, 45, hace_una_semana))
        cerrados = reglas.cierre_automatico_del_dia()
        self.assertIn(hace_una_semana, [fecha for fecha, _ in cerrados])
        self.assertTrue(CierreDia.objects.get(fecha=hace_una_semana).automatico)
        self.assertEqual(reglas.cierre_automatico_del_dia(), [])                 # el mismo día no se repite

    def test_el_cierre_automatico_se_puede_apagar(self):
        hace_una_semana = lunes() - timedelta(days=7)
        reglas.registrar_entrada(self.alumno, 'UID', momento=momento(7, 45, hace_una_semana))
        configuracion = ConfiguracionAsistencia.cargar()
        configuracion.cierre_automatico = False
        configuracion.save()
        self.assertEqual(reglas.cierre_automatico_del_dia(), [])
        self.assertFalse(CierreDia.objects.exists())


# ---------------------------------------------------------------------------
# Justificaciones
# ---------------------------------------------------------------------------
@PRUEBAS
class JustificadasTests(BaseAsistenciaTestCase):
    def setUp(self):
        super().setUp()
        reglas.fijar_asistencia_general(self.inscripcion, lunes(), 'FALTA')

    def justificar(self, **cambios):
        datos = {'inscripcion': self.inscripcion, 'fecha': lunes(), 'motivo': 'Cita médica'}
        datos.update(cambios)
        justificacion = Justificacion.objects.create(**datos)
        return justificacion

    def generales(self):
        return {a.fecha: a.justificada for a in reglas.con_justificada_general(AsistenciaGeneral.objects.all())}

    def materias(self):
        return {a.materia_grado.materia.clave: a.justificada for a in reglas.con_justificada_materia(AsistenciaMateria.objects.all())}

    def test_sin_justificacion_nada_esta_justificado(self):
        self.assertEqual(self.generales(), {lunes(): False})
        self.assertEqual(set(self.materias().values()), {False})

    def test_justificar_solo_la_falta_general(self):
        self.justificar(justifica_general=True)
        self.assertEqual(self.generales(), {lunes(): True})
        self.assertEqual(set(self.materias().values()), {False})

    def test_justificar_todas_las_materias(self):
        self.justificar(todas_materias=True)
        self.assertEqual(self.generales(), {lunes(): False})
        self.assertEqual(set(self.materias().values()), {True})

    def test_justificar_solo_algunas_materias(self):
        self.justificar().materias.set([self.mat, self.cie])
        self.assertEqual(self.materias(), {'MAT': True, 'ESP': False, 'CIE': True})

    def test_una_justificacion_anulada_no_cubre(self):
        self.justificar(justifica_general=True, todas_materias=True, activa=False)
        self.assertEqual(self.generales(), {lunes(): False})
        self.assertEqual(set(self.materias().values()), {False})

    def test_solo_cubre_el_dia_y_el_alumno_de_la_justificacion(self):
        otro = inscribir_antes(crear_alumno(), self.ciclo, self.grado)
        reglas.fijar_asistencia_general(otro, lunes(), 'FALTA')
        self.justificar(justifica_general=True, todas_materias=True)
        self.assertEqual(
            {a.inscripcion_id: a.justificada for a in reglas.con_justificada_general(AsistenciaGeneral.objects.all())},
            {self.inscripcion.pk: True, otro.pk: False},
        )

    def test_conteos_y_porcentaje(self):
        otro = inscribir_antes(crear_alumno(), self.ciclo, self.grado)
        reglas.fijar_asistencia_general(otro, lunes(), 'PRESENTE')
        tercero = inscribir_antes(crear_alumno(), self.ciclo, self.grado)
        reglas.fijar_asistencia_general(tercero, lunes(), 'RETARDO', hora=time(8, 30))
        self.justificar(justifica_general=True)
        total = reglas.conteos(reglas.con_justificada_general(AsistenciaGeneral.objects.all()))
        self.assertEqual(total, {'registros': 3, 'presentes': 1, 'retardos': 1, 'faltas': 1, 'justificadas': 1})
        self.assertEqual(reglas.porcentaje(1, 1, 3), 67)
        self.assertIsNone(reglas.porcentaje(0, 0, 0))

    def test_la_misma_fecha_puede_tener_una_anulada_y_una_vigente(self):
        self.justificar(activa=False)
        self.justificar(justifica_general=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.justificar()
