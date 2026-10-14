"""Control de calificaciones: el cálculo del formato GeneralSecundaria.xlsx, la configuración por materia (activar,
versiones, copiar), la captura (validación, bitácora, reintentos), los permisos, el cierre y el concentrado."""
import json
from datetime import timedelta
from decimal import Decimal

from django.test import SimpleTestCase
from django.urls import reverse

from Alumnos.models import AsistenciaMateria, Justificacion, Periodo
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseAsistenciaTestCase,
    crear_alumno,
    crear_profesor,
    crear_rol,
    crear_usuario,
    inscribir_antes,
    lunes,
)
from Usuarios.models import Rol

from . import calculo, reglas
from .models import Actividad, CalificacionActividad, CambioCalificacion, ConfiguracionEvaluacion, Rubro

D = Decimal
URL = reverse('calificaciones:inicio')


def dia(desplazamiento):
    return lunes() + timedelta(days=desplazamiento)


# ---------------------------------------------------------------------------
# Cálculo (sin base de datos)
# ---------------------------------------------------------------------------
CONDUCTA = calculo.RubroDeCalculo('c', 'Conducta', D('20'), calculo.DIRECTA)
PROCEDIMIENTOS = calculo.RubroDeCalculo('p', 'Procedimientos', D('50'), calculo.PROCEDIMIENTOS)
EXAMENES = calculo.RubroDeCalculo('e', 'Exámenes', D('30'), calculo.EXAMENES)
FORMATO = [CONDUCTA, PROCEDIMIENTOS, EXAMENES]


def calcular(conducta=None, procedimientos=(), examenes=(), faltas=0, academia=False, reglas_=calculo.Reglas(), rubros=FORMATO):
    numeros = lambda valores: [None if x is None else D(str(x)) for x in valores]   # noqa: E731
    capturas = {'c': conducta, 'p': numeros(procedimientos), 'e': numeros(examenes)}
    if conducta is not None:
        capturas['c'] = D(str(conducta))
    return calculo.calcular(rubros, reglas_, capturas, faltas=faltas, academia=academia)


class CalculoDelFormatoTests(SimpleTestCase):
    def test_caso_de_referencia(self):
        # conducta 9, procedimientos 8 y 10, exámenes 7 y 9, tres faltas y punto de academia: 1.80 + 4.50 + 2.40 − 1 + 1
        r = calcular(9, [8, 10], [7, 9], faltas=3, academia=True)
        self.assertEqual([r.rubros[k].aportacion for k in 'cpe'], [D('1.80'), D('4.50'), D('2.40')])
        self.assertEqual((r.base, r.descuento, r.bonificacion, r.final), (D('8.70'), D('1'), D('1'), D('8.70')))

    def test_un_cero_cuenta_y_una_celda_vacia_no(self):
        self.assertEqual(calcular(10, [10, 0], [10]).rubros['p'].valor, D('5.00'))      # el cero baja el promedio
        self.assertEqual(calcular(10, [10, None], [10]).rubros['p'].valor, D('10.00'))  # la vacía no cuenta

    def test_sin_capturas_no_hay_calificacion_ni_division_entre_cero(self):
        r = calcular()
        self.assertIsNone(r.final)
        self.assertTrue(r.sin_capturas)
        self.assertEqual(r.rubros['p'].capturas, 0)

    def test_falta_un_rubro_no_hay_final_definitiva(self):
        r = calcular(9, [8], [])
        self.assertIsNone(r.final)
        self.assertEqual(r.rubros['p'].aportacion, D('4.00'))

    def test_descuento_por_bloques_completos_de_faltas(self):
        esperado = {0: 0, 1: 0, 2: 1, 3: 1, 4: 2, 5: 2}
        for faltas, puntos in esperado.items():
            with self.subTest(faltas=faltas):
                self.assertEqual(calculo.descuento_por_faltas(faltas, calculo.Reglas()), D(puntos))
        configurada = calculo.Reglas(faltas_por_bloque=3, puntos_por_bloque=D('0.5'))
        self.assertEqual(calculo.descuento_por_faltas(7, configurada), D('1.0'))
        self.assertEqual(calculo.descuento_por_faltas(9, calculo.Reglas(penalizar_faltas=False)), 0)

    def test_redondeos_como_excel(self):
        # promedio de procedimientos 8.325 -> 8.33 (la mitad hacia arriba); por 50 % = 4.165 -> 4.17
        r = calcular(10, ['8.33', '8.32'], [10])
        self.assertEqual((r.rubros['p'].valor, r.rubros['p'].aportacion), (D('8.33'), D('4.17')))
        # exámenes: el promedio exacto se pondera y luego se redondea (8.3333… × 0.30 = 2.50)
        self.assertEqual(calcular(10, [10], [8, 8, 9]).rubros['e'].aportacion, D('2.50'))
        self.assertEqual(calcular('9.25', [10], [10]).rubros['c'].aportacion, D('1.85'))

    def test_tope_de_diez_y_sin_minimo_como_el_formato(self):
        self.assertEqual(calcular(10, [10], [10], academia=True).final, D('10'))
        bajo = calcular(0, [0], [0], faltas=4)
        self.assertEqual(bajo.final, D('-2.00'))   # el formato no tiene límite inferior
        con_minimo = calcular(0, [0], [0], faltas=4, reglas_=calculo.Reglas(limite_minimo=D('5')))
        self.assertEqual((con_minimo.final, con_minimo.tope), (D('5'), 'minimo'))

    def test_punto_de_academia_configurable(self):
        self.assertEqual(calcular(8, [8], [8], academia=True, reglas_=calculo.Reglas(punto_academia=False)).final, D('8.00'))
        self.assertEqual(calcular(8, [8], [8], academia=True, reglas_=calculo.Reglas(valor_punto_academia=D('0.5'))).final, D('8.50'))

    def test_otros_porcentajes(self):
        rubros = [calculo.RubroDeCalculo('c', 'Conducta', D('10'), calculo.DIRECTA), calculo.RubroDeCalculo('p', 'Proyecto', D('90'), calculo.PROCEDIMIENTOS)]
        r = calculo.calcular(rubros, calculo.Reglas(), {'c': D('9'), 'p': [D('7')]})
        self.assertEqual(r.final, D('7.20'))


# ---------------------------------------------------------------------------
# Base: una materia de secundaria con su docente, su periodo abierto y dos estudiantes
# ---------------------------------------------------------------------------
class BaseCalificacionesTestCase(BaseAsistenciaTestCase):
    """Marta da Matemáticas en 4° Primaria (la base de asistencia) con la configuración de referencia; el periodo
    abierto va del lunes de hace dos semanas al viernes de la próxima. Dos estudiantes: Luis (el de la base) y Zoe."""

    hora = (9, 0)

    def setUp(self):
        super().setUp()
        self.docente = crear_usuario('marta', Rol.objects.get(grupo__name='Docente'))
        self.profesor = crear_profesor(usuario=self.docente)
        self.mat.profesor = self.profesor
        self.mat.save()
        self.periodo = Periodo.objects.create(ciclo=self.ciclo, nivel='PRIMARIA', nombre='Primer bimestre', fecha_inicio=dia(-14), fecha_fin=dia(11))
        self.zoe = inscribir_antes(crear_alumno(nombre='Zoe', curp='PEMJ100720HMNRRNA5'), self.ciclo, self.grado)
        self.config = reglas.crear_inicial(self.mat.materia, self.ciclo, self.admin)
        self.acta = reglas.acta_para(self.mat, self.periodo)
        self.conducta, self.procedimientos, self.examenes = self.config.rubros.order_by('orden')

    def actividad(self, nombre, rubro=None, acta=None):
        rubro = rubro or self.procedimientos
        return reglas.crear_actividad(acta or self.acta, {'rubro': rubro, 'nombre': nombre, 'fecha': dia(-3)}, self.admin)

    def guardar(self, cambios, acta=None, usuario=None):
        if usuario is not None:
            self.client.force_login(usuario)
        respuesta = self.client.post(reverse('calificaciones:guardar', args=[(acta or self.acta).pk]), json.dumps({'cambios': cambios}),
                                     content_type='application/json')
        return respuesta

    def capturar_caso_de_referencia(self, *inscripciones):
        """Conducta 9, procedimientos 8 y 10, exámenes 7 y 9 (las mismas cuatro actividades para todos)."""
        inscripciones = inscripciones or (self.inscripcion,)
        p1, p2 = self.actividad('Mapa'), self.actividad('Ensayo')
        e1, e2 = self.actividad('Examen 1', self.examenes), self.actividad('Examen 2', self.examenes)
        cambios = []
        for inscripcion in inscripciones:
            cambios.append({'clave': f'c{inscripcion.pk}', 'tipo': 'rubro', 'id': self.conducta.pk, 'inscripcion': inscripcion.pk, 'valor': '9'})
            for actividad, valor in ((p1, '8'), (p2, '10'), (e1, '7'), (e2, '9')):
                cambios.append({'clave': f'a{actividad.pk}-{inscripcion.pk}', 'tipo': 'actividad', 'id': actividad.pk, 'inscripcion': inscripcion.pk, 'valor': valor})
        return self.guardar(cambios), (p1, p2, e1, e2)

    def faltas_en_asistencia(self, cuantas, inscripcion=None, justificadas=0):
        """Faltas en la materia, cada lunes hacia atrás dentro del periodo."""
        inscripcion = inscripcion or self.inscripcion
        for n in range(cuantas):
            registro = AsistenciaMateria.objects.create(inscripcion=inscripcion, materia_grado=self.mat, fecha=dia(-7 * n), estado='FALTA')
            if n < justificadas:
                justificacion = Justificacion.objects.create(inscripcion=inscripcion, fecha=registro.fecha, motivo='Cita médica.', asistencia=registro)
                justificacion.materias.add(self.mat)


@PRUEBAS
class ConfiguracionTests(BaseCalificacionesTestCase):
    def test_la_configuracion_inicial_es_la_del_formato(self):
        self.assertEqual([(r.nombre, r.porcentaje, r.tipo) for r in self.config.rubros.all()],
                         [(n, p, t) for n, p, t in reglas.INICIAL])
        self.assertTrue(self.config.activa)
        self.assertEqual(reglas.suma_de(self.config.rubros.all()), D('100'))

    def test_solo_se_activa_si_suma_exactamente_cien(self):
        datos = [{'pk': r.pk, 'nombre': r.nombre, 'porcentaje': D('20') if r == self.procedimientos else r.porcentaje, 'tipo': r.tipo,
                  'activo': True, 'orden': r.orden} for r in self.config.rubros.all()]
        problemas = reglas.guardar_configuracion(self.config, self._reglas(), datos, True, self.admin)
        self.config.refresh_from_db()
        self.assertEqual(self.config.estado, ConfiguracionEvaluacion.BORRADOR)   # se guarda como borrador
        self.assertIn('suman 70 %', problemas[0])
        self.assertTrue(reglas.problemas_para_cerrar(self.acta))   # un borrador no sirve para cerrar

    def _reglas(self):
        c = self.config
        return {campo: getattr(c, campo) for campo in ('penalizar_faltas', 'faltas_por_bloque', 'puntos_por_bloque', 'origen_faltas', 'punto_academia',
                                                         'valor_punto_academia', 'limite_maximo', 'usar_limite_minimo', 'limite_minimo')}

    def test_dos_materias_con_porcentajes_distintos(self):
        otra = reglas.crear_inicial(self.esp.materia, self.ciclo, self.admin)
        rubros = [{'pk': r.pk, 'nombre': r.nombre, 'porcentaje': {Rubro.DIRECTA: D('10'), Rubro.PROCEDIMIENTOS: D('40'), Rubro.EXAMENES: D('50')}[r.tipo],
                   'tipo': r.tipo, 'activo': True, 'orden': r.orden} for r in otra.rubros.all()]
        self.assertEqual(reglas.guardar_configuracion(otra, self._reglas(), rubros, True, self.admin), [])
        acta_esp = reglas.acta_para(self.esp, self.periodo)
        e_conducta, e_proc, e_exam = otra.rubros.order_by('orden')
        for acta, conducta, proc, exam in ((self.acta, self.conducta, self.procedimientos, self.examenes), (acta_esp, e_conducta, e_proc, e_exam)):
            p = self.actividad('P', proc, acta)
            e = self.actividad('E', exam, acta)
            self.guardar([{'clave': 'c', 'tipo': 'rubro', 'id': conducta.pk, 'inscripcion': self.inscripcion.pk, 'valor': '10'},
                          {'clave': 'p', 'tipo': 'actividad', 'id': p.pk, 'inscripcion': self.inscripcion.pk, 'valor': '8'},
                          {'clave': 'e', 'tipo': 'actividad', 'id': e.pk, 'inscripcion': self.inscripcion.pk, 'valor': '6'}], acta=acta)
        final = lambda acta: next(f for f in reglas.tabla(acta).filas if f.inscripcion == self.inscripcion).resultado.final   # noqa: E731
        self.assertEqual(final(self.acta), D('7.80'))   # 2 + 4 + 1.8
        self.assertEqual(final(acta_esp), D('7.20'))    # 1 + 3.2 + 3

    def test_copiar_rubros_es_independiente_y_no_copia_calificaciones(self):
        self.capturar_caso_de_referencia()
        destino = reglas.copiar(self.config, self.esp.materia, self.ciclo, None, incluir_reglas=True, usuario=self.admin)
        self.assertEqual([(r.nombre, r.porcentaje, r.tipo) for r in destino.rubros.all()], [(r.nombre, r.porcentaje, r.tipo) for r in self.config.rubros.all()])
        self.assertTrue(set(destino.rubros.values_list('pk', flat=True)).isdisjoint(self.config.rubros.values_list('pk', flat=True)))
        self.assertFalse(Actividad.objects.filter(acta__asignacion=self.esp).exists())
        self.assertFalse(CalificacionActividad.objects.filter(actividad__rubro__configuracion=destino).exists())
        # cambiar el origen después no cambia el destino
        self.procedimientos.porcentaje = D('40')
        self.procedimientos.save()
        self.assertEqual(destino.rubros.get(tipo=Rubro.PROCEDIMIENTOS).porcentaje, D('50'))
        self.assertIn(str(self.mat.materia), destino.copiada_de)

    def test_no_se_reemplaza_una_configuracion_con_capturas(self):
        self.capturar_caso_de_referencia()
        otra = reglas.crear_inicial(self.esp.materia, self.ciclo, self.admin)
        revision = reglas.revisar_copia(otra, self.mat.materia, self.ciclo, None)
        self.assertTrue(revision['reemplaza'])
        self.assertIn('ya tiene calificaciones capturadas', revision['bloqueo'])
        with self.assertRaises(reglas.CapturaRechazada):
            reglas.copiar(otra, self.mat.materia, self.ciclo, None, False, self.admin)
        # a un periodo sin capturas sí: queda como versión de ese periodo y lo ya capturado no cambia
        segundo = Periodo.objects.create(ciclo=self.ciclo, nivel='PRIMARIA', nombre='Segundo bimestre', fecha_inicio=dia(12), fecha_fin=dia(60))
        version = reglas.copiar(otra, self.mat.materia, self.ciclo, segundo, False, self.admin)
        self.assertEqual(reglas.configuracion_de(self.mat.materia, self.ciclo, segundo), version)
        self.assertEqual(reglas.configuracion_de(self.mat.materia, self.ciclo, self.periodo), self.config)

    def test_version_de_periodo_solo_sin_capturas(self):
        self.capturar_caso_de_referencia()
        with self.assertRaises(reglas.CapturaRechazada):
            reglas.nueva_version(self.config, self.periodo, self.admin)
        segundo = Periodo.objects.create(ciclo=self.ciclo, nivel='PRIMARIA', nombre='Segundo bimestre', fecha_inicio=dia(12), fecha_fin=dia(60))
        version = reglas.nueva_version(self.config, segundo, self.admin)
        self.assertEqual(version.rubros.count(), 3)
        self.assertEqual(version.periodo, segundo)

    def test_un_rubro_con_capturas_no_se_elimina_ni_cambia_de_tipo(self):
        self.capturar_caso_de_referencia()
        rubros = [{'pk': r.pk, 'nombre': r.nombre, 'porcentaje': r.porcentaje, 'tipo': r.tipo, 'activo': True, 'orden': r.orden,
                   'eliminar': r == self.conducta} for r in self.config.rubros.all()]
        with self.assertRaises(reglas.CapturaRechazada):
            reglas.guardar_configuracion(self.config, self._reglas(), rubros, True, self.admin)
        rubros[0]['eliminar'], rubros[1]['tipo'] = False, Rubro.EXAMENES
        with self.assertRaises(reglas.CapturaRechazada):
            reglas.guardar_configuracion(self.config, self._reglas(), rubros, True, self.admin)

    def test_pantallas_de_configuracion(self):
        respuesta = self.client.get(reverse('calificaciones:configuracion'))
        self.assertContains(respuesta, self.mat.materia.nombre)
        self.assertContains(respuesta, 'aria-current="page">Calificaciones</a>')   # la pestaña de Ajustes
        pagina = self.client.get(reverse('calificaciones:configuracion_materia', args=[self.mat.materia.pk]), {'ciclo': self.ciclo.pk})
        self.assertContains(pagina, 'Guardar y activar')
        self.assertContains(pagina, 'Copiar configuración de otra materia')
        # Guardar desde el formulario (borrador con 90 %)
        datos = {'ciclo': self.ciclo.pk, 'accion': 'activar', 'rubros-TOTAL_FORMS': '3', 'rubros-INITIAL_FORMS': '3', 'rubros-MIN_NUM_FORMS': '0',
                 'rubros-MAX_NUM_FORMS': '30', 'reglas-faltas_por_bloque': '2', 'reglas-puntos_por_bloque': '1', 'reglas-origen_faltas': 'SIN_JUSTIFICAR',
                 'reglas-valor_punto_academia': '1', 'reglas-limite_maximo': '10', 'reglas-limite_minimo': '0', 'reglas-penalizar_faltas': 'on',
                 'reglas-punto_academia': 'on'}
        for i, r in enumerate(self.config.rubros.all()):
            datos.update({f'rubros-{i}-pk': r.pk, f'rubros-{i}-nombre': r.nombre, f'rubros-{i}-porcentaje': '40' if r == self.procedimientos else str(r.porcentaje),
                          f'rubros-{i}-tipo': r.tipo, f'rubros-{i}-activo': 'on', f'rubros-{i}-orden': i + 1, f'rubros-{i}-eliminar': 'False'})
        respuesta = self.client.post(reverse('calificaciones:configuracion_materia', args=[self.mat.materia.pk]), datos, follow=True)
        self.assertContains(respuesta, 'no se activó')
        self.config.refresh_from_db()
        self.assertEqual((self.config.estado, Rubro.objects.get(pk=self.procedimientos.pk).porcentaje), ('BORRADOR', D('40')))

    def test_asistente_de_copia(self):
        otra = reglas.crear_inicial(self.esp.materia, self.ciclo, self.admin)
        url = reverse('calificaciones:configuracion_copiar')
        vista = self.client.get(url, {'destino': self.cie.materia.pk, 'ciclo': self.ciclo.pk, 'origen': otra.pk, 'reglas': '1'})
        self.assertContains(vista, '4. Vista previa')
        self.assertContains(vista, 'Aplicar la copia')
        self.client.post(url, {'destino': self.cie.materia.pk, 'ciclo': self.ciclo.pk, 'origen': otra.pk, 'reglas': '1', 'confirmar': '1'})
        self.assertEqual(ConfiguracionEvaluacion.objects.get(materia=self.cie.materia).rubros.count(), 3)


@PRUEBAS
class CapturaTests(BaseCalificacionesTestCase):
    def test_caso_de_referencia_por_la_pantalla(self):
        self.config.origen_faltas = ConfiguracionEvaluacion.MANUAL
        self.config.save()
        respuesta, _ = self.capturar_caso_de_referencia()
        self.assertEqual(respuesta.status_code, 200)
        respuesta = self.guardar([{'clave': 'f', 'tipo': 'faltas', 'id': 'manual', 'inscripcion': self.inscripcion.pk, 'valor': '3'},
                                  {'clave': 'a', 'tipo': 'academia', 'id': 'punto', 'inscripcion': self.inscripcion.pk, 'valor': '1'}])
        fila = respuesta.json()['filas'][str(self.inscripcion.pk)]
        self.assertEqual((fila['final'], fila['descuento'], fila['faltas']), ('8.70', '−1', '3'))
        self.assertEqual(fila['estado'], 'En captura')
        self.assertContains(self.client.get(URL, {'materia': self.mat.pk, 'periodo': self.periodo.pk}), '8.70')

    def test_las_faltas_salen_de_la_asistencia(self):
        self.faltas_en_asistencia(3, justificadas=1)
        self.capturar_caso_de_referencia()
        fila = next(f for f in reglas.tabla(self.acta).filas if f.inscripcion == self.inscripcion)
        self.assertEqual(fila.resultado.faltas, 2)   # sin justificar: 2 -> descuenta 1
        self.config.origen_faltas = ConfiguracionEvaluacion.TODAS
        self.config.save()
        fila = next(f for f in reglas.tabla(self.acta).filas if f.inscripcion == self.inscripcion)
        self.assertEqual(fila.resultado.faltas, 3)
        # con faltas de la asistencia no se capturan a mano
        respuesta = self.guardar([{'clave': 'f', 'tipo': 'faltas', 'id': 'manual', 'inscripcion': self.inscripcion.pk, 'valor': '1'}])
        self.assertIn('se toman de la asistencia', respuesta.json()['resultados'][0]['error'])

    def test_validacion_por_celda(self):
        p = self.actividad('Mapa')
        respuesta = self.guardar([
            {'clave': 'ok', 'tipo': 'actividad', 'id': p.pk, 'inscripcion': self.inscripcion.pk, 'valor': '9,5'},
            {'clave': 'alto', 'tipo': 'actividad', 'id': p.pk, 'inscripcion': self.zoe.pk, 'valor': '11'},
            {'clave': 'texto', 'tipo': 'rubro', 'id': self.conducta.pk, 'inscripcion': self.zoe.pk, 'valor': 'diez'},
            {'clave': 'decimales', 'tipo': 'rubro', 'id': self.conducta.pk, 'inscripcion': self.inscripcion.pk, 'valor': '9.555'},
            {'clave': 'ajeno', 'tipo': 'actividad', 'id': p.pk, 'inscripcion': 999999, 'valor': '9'},
        ])
        resultados = {r['clave']: r for r in respuesta.json()['resultados']}
        self.assertEqual((resultados['ok']['ok'], resultados['ok']['valor']), (True, '9.5'))
        for clave in ('alto', 'texto', 'decimales', 'ajeno'):
            self.assertFalse(resultados[clave]['ok'], clave)
        self.assertEqual(CalificacionActividad.objects.get().valor, D('9.50'))

    def test_bitacora_reintento_y_conflicto(self):
        p = self.actividad('Mapa')
        cambio = {'clave': 'x', 'tipo': 'actividad', 'id': p.pk, 'inscripcion': self.inscripcion.pk, 'valor': '8', 'anterior': ''}
        self.guardar([cambio])
        self.guardar([cambio])   # reintento: no duplica
        self.assertEqual(CambioCalificacion.objects.filter(accion='CAPTURA').count(), 1)
        bitacora = CambioCalificacion.objects.get(accion='CAPTURA')
        self.assertEqual((bitacora.anterior, bitacora.nuevo, bitacora.usuario), ('', '8', self.admin))
        # alguien más lo cambió: el cambio con un «anterior» viejo se rechaza
        conflicto = self.guardar([{**cambio, 'valor': '6', 'anterior': '5'}]).json()['resultados'][0]
        self.assertFalse(conflicto['ok'])
        self.assertIn('Alguien más', conflicto['error'])
        # vaciar la celda la deja pendiente (y queda en la bitácora)
        self.guardar([{**cambio, 'valor': '', 'anterior': '8'}])
        self.assertFalse(CalificacionActividad.objects.exists())
        self.assertEqual(CambioCalificacion.objects.filter(accion='CAPTURA').count(), 2)

    def test_agregar_actividades_actualiza_la_matriz_y_lo_pendiente(self):
        self.capturar_caso_de_referencia()
        fila = lambda: next(f for f in reglas.tabla(self.acta).filas if f.inscripcion == self.inscripcion)   # noqa: E731
        self.assertEqual(fila().resultado.pendientes, 0)
        nuevo = self.actividad('Maqueta')
        self.assertEqual(fila().resultado.pendientes, 1)
        self.assertTrue(fila().resultado.provisional)
        respuesta = self.client.get(URL, {'materia': self.mat.pk, 'periodo': self.periodo.pk, 'pestana': 'procedimientos'})
        self.assertContains(respuesta, 'Maqueta')
        self.assertContains(respuesta, f'data-clave="actividad-{nuevo.pk}-{self.inscripcion.pk}"')
        self.guardar([{'clave': 'n', 'tipo': 'actividad', 'id': nuevo.pk, 'inscripcion': self.inscripcion.pk, 'valor': '0'}])
        self.assertEqual(fila().resultado.rubros[str(self.procedimientos.pk)].valor, D('6.00'))   # (8 + 10 + 0) / 3

    def test_anular_y_eliminar_actividades(self):
        con, sin = self.actividad('Con calificación'), self.actividad('Sin calificación')
        self.guardar([{'clave': 'a', 'tipo': 'actividad', 'id': con.pk, 'inscripcion': self.inscripcion.pk, 'valor': '4'}])
        self.client.post(reverse('calificaciones:actividad_quitar', args=[sin.pk]))
        self.assertFalse(Actividad.objects.filter(pk=sin.pk).exists())
        sin_motivo = self.client.post(reverse('calificaciones:actividad_quitar', args=[con.pk]), {'motivo': ''})
        self.assertEqual(sin_motivo.status_code, 200)
        self.client.post(reverse('calificaciones:actividad_quitar', args=[con.pk]), {'motivo': 'Se repitió por error.'})
        con.refresh_from_db()
        self.assertTrue(con.anulada)
        self.assertTrue(CalificacionActividad.objects.filter(actividad=con).exists())   # se conserva
        fila = next(f for f in reglas.tabla(self.acta).filas if f.inscripcion == self.inscripcion)
        self.assertIsNone(fila.resultado.rubros[str(self.procedimientos.pk)].valor)     # ya no cuenta
        self.assertTrue(CambioCalificacion.objects.filter(accion='ACT_ANULADA', motivo='Se repitió por error.').exists())

    def test_una_actividad_fuera_del_periodo_no_se_crea(self):
        respuesta = self.client.post(reverse('calificaciones:actividad_crear', args=[self.acta.pk]),
                                     {'pestana': 'procedimientos', 'nombre': 'Tarde', 'fecha': dia(40).isoformat(), 'rubro': self.procedimientos.pk})
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Actividad.objects.exists())

    def test_las_pestanas_se_ven(self):
        self.capturar_caso_de_referencia()
        for pestana in ('resumen', 'procedimientos', 'examenes', 'concentrado'):
            with self.subTest(pestana=pestana):
                respuesta = self.client.get(URL, {'materia': self.mat.pk, 'periodo': self.periodo.pk, 'pestana': pestana})
                self.assertEqual(respuesta.status_code, 200)
        concentrado = self.client.get(URL, {'materia': self.mat.pk, 'periodo': self.periodo.pk, 'pestana': 'concentrado'})
        self.assertContains(concentrado, 'Firma de enterado')
        self.assertContains(concentrado, 'PROVISIONAL')


@PRUEBAS
class AccesoTests(BaseCalificacionesTestCase):
    def setUp(self):
        super().setUp()
        self.otro = crear_usuario('pedro', Rol.objects.get(grupo__name='Docente'))
        self.otro_profesor = crear_profesor(usuario=self.otro, nombre='Pedro')
        self.esp.profesor = self.otro_profesor
        self.esp.save()

    def test_el_docente_solo_ve_sus_materias(self):
        self.client.force_login(self.docente)
        respuesta = self.client.get(URL)
        self.assertEqual([a.pk for a in respuesta.context['asignaciones']], [self.mat.pk])
        self.assertEqual(self.client.get(URL, {'materia': self.esp.pk}).status_code, 403)
        ajena = reglas.acta_para(self.esp, self.periodo)
        self.assertEqual(self.guardar([], acta=ajena).status_code, 403)
        self.assertEqual(self.client.get(reverse('calificaciones:concentrado_excel', args=[ajena.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse('calificaciones:historial', args=[ajena.pk])).status_code, 403)

    def test_el_docente_captura_lo_suyo(self):
        p = self.actividad('Mapa')
        respuesta = self.guardar([{'clave': 'a', 'tipo': 'actividad', 'id': p.pk, 'inscripcion': self.inscripcion.pk, 'valor': '7'}], usuario=self.docente)
        self.assertTrue(respuesta.json()['ok'])

    def test_quien_solo_consulta_no_captura(self):
        consulta = crear_usuario('coordina', crear_rol('Coordinación', {'Calificaciones.ver_todas'}))
        self.client.force_login(consulta)
        respuesta = self.client.get(URL)
        self.assertEqual(len(respuesta.context['asignaciones']), 3)
        self.assertFalse(respuesta.context['editable'])
        self.assertEqual(self.guardar([]).status_code, 403)

    def test_sin_permiso_no_entra(self):
        self.client.force_login(self.sin_permisos)
        self.assertEqual(self.client.get(URL).status_code, 403)
        self.assertEqual(self.client.get(reverse('calificaciones:configuracion')).status_code, 403)

    def test_periodo_cerrado_es_de_solo_lectura(self):
        self.periodo.apertura = Periodo.CERRADO
        self.periodo.save()
        p = self.actividad('Mapa')
        respuesta = self.guardar([{'clave': 'a', 'tipo': 'actividad', 'id': p.pk, 'inscripcion': self.inscripcion.pk, 'valor': '7'}])
        self.assertEqual(respuesta.status_code, 409)
        self.assertIn('está cerrado', respuesta.json()['mensaje'])


@PRUEBAS
class CierreTests(BaseCalificacionesTestCase):
    def completar(self):
        return self.capturar_caso_de_referencia(self.inscripcion, self.zoe)[1]

    def test_para_cerrar_hay_que_resolver_lo_pendiente(self):
        self.capturar_caso_de_referencia()   # Zoe sin calificar
        problemas = reglas.problemas_para_cerrar(self.acta)
        self.assertTrue(any('sin calificación' in p for p in problemas))
        self.assertTrue(any('pendiente' in p for p in problemas))
        self.client.post(reverse('calificaciones:cerrar', args=[self.acta.pk]))
        self.acta.refresh_from_db()
        self.assertFalse(self.acta.cerrada)

    def test_cerrar_conserva_los_resultados_aunque_cambie_la_configuracion(self):
        self.completar()
        self.client.post(reverse('calificaciones:cerrar', args=[self.acta.pk]))
        self.acta.refresh_from_db()
        self.assertTrue(self.acta.cerrada)
        antes = {f.inscripcion.pk: f.resultado.final for f in reglas.tabla(self.acta).filas}
        self.assertEqual(antes[self.inscripcion.pk], D('8.70'))   # sin faltas ni punto de academia: 1.80 + 4.50 + 2.40
        # cambiar la configuración después no altera lo cerrado
        self.procedimientos.porcentaje, self.examenes.porcentaje = D('40'), D('40')
        self.procedimientos.save()
        self.examenes.save()
        despues = {f.inscripcion.pk: f.resultado.final for f in reglas.tabla(self.acta).filas}
        self.assertEqual(antes, despues)
        # cerrado: no se captura
        respuesta = self.guardar([{'clave': 'c', 'tipo': 'rubro', 'id': self.conducta.pk, 'inscripcion': self.inscripcion.pk, 'valor': '5'}])
        self.assertEqual(respuesta.status_code, 409)
        # el concentrado coincide con el resumen
        concentrado = self.client.get(URL, {'materia': self.mat.pk, 'periodo': self.periodo.pk, 'pestana': 'concentrado'}).context['concentrado']
        self.assertEqual({f['nombre']: f['final'] for f in concentrado['filas']},
                         {f.nombre: reglas.dos_decimales(f.resultado.final) for f in reglas.tabla(self.acta).filas})
        self.assertTrue(concentrado['cerrada'])

    def test_reabrir_exige_permiso_y_motivo(self):
        self.completar()
        reglas.cerrar(self.acta, self.admin)
        self.client.force_login(self.docente)   # el docente cierra, pero no reabre
        self.assertEqual(self.client.post(reverse('calificaciones:reabrir', args=[self.acta.pk]), {'motivo': 'Error de captura.'}).status_code, 403)
        self.client.force_login(self.admin)
        self.client.post(reverse('calificaciones:reabrir', args=[self.acta.pk]), {'motivo': ''})
        self.acta.refresh_from_db()
        self.assertTrue(self.acta.cerrada)
        self.client.post(reverse('calificaciones:reabrir', args=[self.acta.pk]), {'motivo': 'Error de captura en Zoe.'})
        self.acta.refresh_from_db()
        self.assertFalse(self.acta.cerrada)
        reapertura = CambioCalificacion.objects.get(accion='REAPERTURA')
        self.assertEqual(reapertura.motivo, 'Error de captura en Zoe.')
        self.assertEqual(len(reapertura.datos['resultados']), 2)   # lo que se había cerrado queda guardado

    def pagina(self, pestana=None):
        datos = {'materia': self.mat.pk, 'periodo': self.periodo.pk}
        if pestana:
            datos['pestana'] = pestana
        return self.client.get(URL, datos)

    def test_el_historial_de_movimientos_aparece_al_reabrir(self):
        self.completar()
        reglas.cerrar(self.acta, self.admin)
        cerrada = self.pagina()
        self.assertIsNone(cerrada.context['movimientos'])   # cerrada pero nunca reabierta: no hay sección
        self.assertNotContains(cerrada, 'Historial de movimientos')

        reglas.reabrir(self.acta, 'Error de captura en Zoe.', self.admin)
        self.guardar([{'clave': 'c', 'tipo': 'rubro', 'id': self.conducta.pk, 'inscripcion': self.zoe.pk, 'valor': '10', 'anterior': '9'}])
        reglas.cerrar(self.acta, self.docente)
        respuesta = self.pagina()
        movimientos = respuesta.context['movimientos'].lista
        # del más reciente al más antiguo; desde la reapertura (sin el primer cierre ni las capturas de antes)
        self.assertEqual([m.accion for m in movimientos], ['CIERRE', 'CAPTURA', 'REAPERTURA'])
        cierre, captura, reapertura = movimientos
        self.assertEqual(cierre.usuario, self.docente)
        self.assertEqual((captura.inscripcion, captura.que, captura.anterior, captura.nuevo, captura.usuario),
                         (self.zoe, 'Actitudes / Conducta', '9', '10', self.admin))
        self.assertEqual((reapertura.usuario, reapertura.motivo), (self.admin, 'Error de captura en Zoe.'))
        # sigue disponible después del nuevo cierre, debajo de cada tabla de captura (no en el concentrado)
        self.assertContains(respuesta, 'Historial de movimientos')
        self.assertContains(respuesta, 'Nuevo cierre')
        self.assertContains(respuesta, 'Error de captura en Zoe.')
        for pestana in ('procedimientos', 'examenes'):
            self.assertContains(self.pagina(pestana), 'Historial de movimientos')
        self.assertNotContains(self.pagina('concentrado'), 'Historial de movimientos')
        # solo lectura: la sección no lleva formularios ni campos
        seccion = respuesta.content.decode().split('id="titulo-movimientos"')[1].split('</section>')[0]
        self.assertNotIn('<form', seccion)
        self.assertNotIn('<input', seccion)

    def test_el_historial_se_conserva_entre_reaperturas_y_es_de_cada_acta(self):
        self.completar()
        reglas.cerrar(self.acta, self.admin)
        reglas.reabrir(self.acta, 'Primera reapertura.', self.admin)
        reglas.cerrar(self.acta, self.admin)
        reglas.reabrir(self.acta, 'Segunda reapertura.', self.admin)
        movimientos = reglas.historial_de_movimientos(self.acta).lista
        self.assertEqual([m.motivo for m in movimientos if m.accion == 'REAPERTURA'], ['Segunda reapertura.', 'Primera reapertura.'])
        self.assertEqual([m.accion for m in movimientos], ['REAPERTURA', 'CIERRE', 'REAPERTURA'])
        # cada materia, grupo y periodo tiene el suyo
        self.assertIsNone(reglas.historial_de_movimientos(reglas.acta_para(self.esp, self.periodo)))
        # y respeta el acceso: un docente de otra materia no abre esta
        ajeno = crear_usuario('ajeno', Rol.objects.get(grupo__name='Docente'))
        crear_profesor(usuario=ajeno, nombre='Ana')
        self.client.force_login(ajeno)
        self.assertEqual(self.pagina().status_code, 403)

    def test_el_docente_cierra_sus_materias(self):
        self.completar()
        self.client.force_login(self.docente)
        self.client.post(reverse('calificaciones:cerrar', args=[self.acta.pk]))
        self.acta.refresh_from_db()
        self.assertTrue(self.acta.cerrada)
        self.assertEqual(self.acta.cerrada_por, self.docente)

    def test_concentrado_para_imprimir_y_en_excel(self):
        self.completar()
        hoja = self.client.get(reverse('calificaciones:concentrado_imprimir', args=[self.acta.pk]), {'pdf': '1'})
        self.assertContains(hoja, 'data-imprimir-al-abrir')
        self.assertContains(hoja, 'Vo.Bo. Coordinación')
        excel = self.client.get(reverse('calificaciones:concentrado_excel', args=[self.acta.pk]))
        self.assertEqual(excel['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertTrue(excel.content.startswith(b'PK'))


class BaseRolesDeCalificacionesTests(SimpleTestCase):
    def test_los_permisos_estan_en_el_catalogo(self):
        from Usuarios import catalogo
        for permiso in (reglas.CAPTURAR, reglas.VER_TODAS, reglas.GESTIONAR_TODAS, reglas.CERRAR, reglas.REABRIR,
                        reglas.VER_CONFIG, reglas.CREAR_CONFIG, reglas.CAMBIAR_CONFIG):
            self.assertIn(permiso, catalogo.TODOS)

