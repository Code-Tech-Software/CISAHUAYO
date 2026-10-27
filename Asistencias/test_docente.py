"""Asistencia para docentes: la matriz de sus materias en el ciclo (sin depender del periodo de evaluación; el docente
captura y corrige los últimos días) y el guardado de cada celda (Alumnos/asistencia_docente.py y
Asistencias/views_docente.py)."""
from datetime import timedelta

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from Alumnos.asistencia_docente import version_de
from Alumnos.models import AsistenciaGeneral, AsistenciaMateria, ConfiguracionAsistencia, DiaNoLectivo, Justificacion, Periodo
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseAsistenciaTestCase,
    crear_alumno,
    crear_grado,
    crear_profesor,
    crear_rol,
    crear_usuario,
    inscribir_antes,
    lunes,
)
from Usuarios.models import Rol

URL = reverse('asistencias:docente')


def dia(desplazamiento):
    """Un día relativo al lunes de prueba (que es «hoy»)."""
    return lunes() + timedelta(days=desplazamiento)


class BaseDocenteTestCase(BaseAsistenciaTestCase):
    """Marta da Matemáticas (los lunes de 8:00 a 9:00) en 4.º Primaria; el periodo abierto va del lunes de hace dos
    semanas al viernes de la próxima. «Hoy» es el lunes de prueba a las 9:00."""

    hora = (9, 0)

    def setUp(self):
        super().setUp()
        self.docente = crear_usuario('marta', Rol.objects.get(grupo__name='Docente'))
        self.profesor = crear_profesor(usuario=self.docente)
        self.mat.profesor = self.profesor
        self.mat.save()
        self.periodo = Periodo.objects.create(
            ciclo=self.ciclo, nivel='PRIMARIA', nombre='Primer bimestre', fecha_inicio=dia(-14), fecha_fin=dia(11),
        )
        self.otra = inscribir_antes(crear_alumno(curp='PEMJ100720HMNRRNA5', nombre='Zoe'), self.ciclo, self.grado)
        self.client.force_login(self.docente)

    def guardar(self, fecha, estado, inscripcion=None, version='', asignacion=None, observaciones=None):
        """Una falta o un retardo llevan su observación (una de prueba si no se indica)."""
        if observaciones is None:
            observaciones = 'Motivo de prueba' if estado in ('FALTA', 'RETARDO') else ''
        return self.client.post(reverse('asistencias:docente_guardar', args=[(asignacion or self.mat).pk]), {
            'inscripcion': (inscripcion or self.inscripcion).pk, 'fecha': fecha.isoformat(), 'estado': estado,
            'version': version, 'observaciones': observaciones,
        })

    def todo_el_periodo(self):
        return {'desde': self.periodo.fecha_inicio.isoformat(), 'hasta': self.periodo.fecha_fin.isoformat()}

    def celdas(self, inscripcion=None):
        """{fecha: celda} del estudiante en la matriz de todo el periodo."""
        datos = self.client.get(URL, self.todo_el_periodo()).context['datos']
        fila = next(f for f in datos['filas'] if f['inscripcion'] == (inscripcion or self.inscripcion))
        return {columna['fecha']: celda for columna, celda in zip(datos['columnas'], fila['celdas'])}


# ---------------------------------------------------------------------------
# Quién entra y qué ve
# ---------------------------------------------------------------------------
@PRUEBAS
class AccesoTests(BaseDocenteTestCase):
    def test_una_cuenta_sin_ficha_de_profesor_ve_el_aviso(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(URL)
        self.assertContains(respuesta, 'Esta sección es para docentes')
        self.assertNotIn('datos', respuesta.context)

    def test_solo_ve_sus_materias(self):
        otro = crear_profesor(nombre='Beto', curp='')
        self.esp.profesor = otro
        self.esp.save()
        respuesta = self.client.get(URL)
        self.assertEqual(respuesta.context['asignaciones'], [self.mat])
        self.assertEqual(respuesta.context['asignacion'], self.mat)
        self.assertContains(respuesta, 'Mat · 4.º A')

    def test_una_materia_ajena_no_se_abre_ni_se_guarda(self):
        self.assertEqual(self.client.get(URL, {'materia': self.esp.pk}).status_code, 403)
        self.assertEqual(self.client.get(URL, {'materia': 'x'}).status_code, 403)
        self.assertEqual(self.guardar(dia(0), 'FALTA', asignacion=self.esp).status_code, 403)
        self.assertFalse(AsistenciaMateria.objects.exists())

    def test_sin_materias_asignadas(self):
        self.mat.profesor = None
        self.mat.save()
        self.assertContains(self.client.get(URL), 'No tienes materias asignadas')

    def test_sin_periodo_abierto_se_sigue_pasando_lista(self):
        # Pedido del 2026-10-27: la asistencia no depende del periodo de evaluación
        self.periodo.delete()
        respuesta = self.client.get(URL)
        self.assertContains(respuesta, 'Sin periodo abierto')
        self.assertTrue(self.celdas()[dia(0)].editable)
        self.assertEqual(self.guardar(dia(0), 'FALTA').status_code, 200)
        self.assertEqual(AsistenciaMateria.objects.get().estado, 'FALTA')

    def test_con_el_periodo_cerrado_a_mano_se_sigue_pasando_lista(self):
        self.periodo.apertura = Periodo.CERRADO
        self.periodo.save()
        self.assertEqual(self.guardar(dia(0), 'PRESENTE').status_code, 200)

    def test_sin_estudiantes(self):
        self.inscripcion.alumno.estatus = 'BAJA'
        self.inscripcion.alumno.save()
        self.otra.delete()
        self.assertContains(self.client.get(URL), 'Sin estudiantes')

    def test_un_rol_que_solo_consulta_ve_pero_no_cambia(self):
        solo_ver = crear_usuario('lupe', crear_rol('Consulta docente', {'Alumnos.view_asistenciamateria'}))
        self.profesor.usuario = solo_ver
        self.profesor.save()
        self.client.force_login(solo_ver)
        respuesta = self.client.get(URL)
        self.assertContains(respuesta, 'tu rol no permite cambiarla')
        self.assertFalse(self.celdas()[dia(0)].editable)
        self.assertEqual(self.guardar(dia(0), 'FALTA').status_code, 403)

    def test_el_menu_lleva_al_docente_a_sus_materias(self):
        respuesta = self.client.get(reverse('inicio'))
        asistencias = next(e for s in respuesta.context['navegacion'] for e in s['elementos'] if e['etiqueta'] == 'Asistencias')
        self.assertEqual(asistencias['url'], URL)
        # Las demás pantallas de asistencias le ofrecen volver a sus materias…
        self.assertContains(self.client.get(reverse('asistencias:justificaciones')), '>Mis materias</a>')
        self.client.force_login(self.admin)   # (sin ficha de profesor: sin esa pestaña)
        self.assertNotContains(self.client.get(reverse('asistencias:materias')), '>Mis materias</a>')

    def test_la_seccion_del_docente_no_lleva_las_pestanas_de_asistencias(self):
        respuesta = self.client.get(URL)
        self.assertNotContains(respuesta, 'pills--section')
        self.assertNotContains(respuesta, reverse('asistencias:materias'))
        self.assertNotContains(respuesta, reverse('asistencias:justificaciones'))
        # ni el enlace a «Asistencias» en la ruta, que un docente no puede abrir
        self.assertNotContains(respuesta, f'href="{reverse("asistencias:inicio")}"')

    def test_el_buscador_va_en_la_tarjeta_de_la_materia(self):
        html = self.client.get(URL).content.decode()
        formulario = html[html.index('data-filtros-docente'):html.index('</form>', html.index('data-filtros-docente'))]
        self.assertIn('data-buscar-estudiante', formulario)
        self.assertEqual(html.count('data-buscar-estudiante'), 1)


# ---------------------------------------------------------------------------
# La matriz
# ---------------------------------------------------------------------------
@PRUEBAS
class MatrizTests(BaseDocenteTestCase):
    def test_por_omision_solo_el_mes_en_curso_dentro_del_ciclo(self):
        datos = self.client.get(URL).context['datos']
        fin_de_mes = (dia(0).replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        esperado = (max(dia(0).replace(day=1), self.ciclo.fecha_inicio), min(fin_de_mes, self.ciclo.fecha_fin))
        self.assertEqual((datos['desde'], datos['hasta']), esperado)
        self.assertEqual(datos['limites'], (self.ciclo.fecha_inicio, self.ciclo.fecha_fin))
        fechas = [c['fecha'] for c in datos['columnas']]
        self.assertTrue(all(esperado[0] <= f <= esperado[1] and f.month == dia(0).month for f in fechas))

    def test_columnas_de_lunes_a_viernes_del_periodo(self):
        columnas = self.client.get(URL, self.todo_el_periodo()).context['datos']['columnas']
        fechas = [c['fecha'] for c in columnas]
        self.assertEqual(fechas[0], dia(-14))
        self.assertEqual(fechas[-1], dia(11))
        self.assertEqual(len(fechas), 20)   # cuatro semanas
        self.assertTrue(all(f.weekday() < 5 for f in fechas))
        self.assertEqual([c['fecha'] for c in columnas if c['hoy']], [dia(0)])

    def test_estados_y_bloqueos(self):
        AsistenciaMateria.objects.create(inscripcion=self.inscripcion, materia_grado=self.mat, fecha=dia(-14), estado='PRESENTE')
        AsistenciaMateria.objects.create(inscripcion=self.inscripcion, materia_grado=self.mat, fecha=dia(-7), estado='FALTA')
        Justificacion.objects.create(inscripcion=self.inscripcion, fecha=dia(-7), motivo='Consulta médica', todas_materias=True)
        DiaNoLectivo.registrar(fecha=dia(-4), motivo='Consejo técnico')
        celdas = self.celdas()
        self.assertEqual((celdas[dia(-14)].letra, celdas[dia(-14)].editable), ('P', False))      # ya pasó su plazo (7 días)
        self.assertIn('la corrige la administración', celdas[dia(-14)].nombre)
        self.assertEqual((celdas[dia(-7)].letra, celdas[dia(-7)].editable), ('J', False))       # justificada: bloqueada
        self.assertEqual((celdas[dia(-4)].letra, celdas[dia(-4)].editable), ('S', False))       # suspensión
        self.assertIn('Consejo técnico', celdas[dia(-4)].nombre)
        self.assertEqual((celdas[dia(-13)].letra, celdas[dia(-13)].editable), ('', False))      # martes: sin clase
        self.assertIn('no tiene clase los martes', celdas[dia(-13)].nombre)
        self.assertEqual((celdas[dia(0)].letra, celdas[dia(0)].editable), ('—', True))         # hoy, sin registro
        self.assertEqual((celdas[dia(7)].letra, celdas[dia(7)].editable), ('', False))          # futura
        # la suspensión aplica a todos
        self.assertEqual(self.celdas(self.otra)[dia(-4)].letra, 'S')

    def test_un_dia_sin_clases_de_otro_nivel_no_bloquea_la_materia(self):
        otro = 'SECUNDARIA' if self.mat.grado.nivel != 'SECUNDARIA' else 'PRIMARIA'
        DiaNoLectivo.registrar(fecha=dia(-4), motivo='Consejo técnico', niveles=[otro])
        self.assertNotEqual(self.celdas()[dia(-4)].letra, 'S')
        DiaNoLectivo.registrar(fecha=dia(-4), motivo='Consejo técnico', niveles=[self.mat.grado.nivel])
        self.assertEqual(self.celdas()[dia(-4)].letra, 'S')

    def test_antes_de_inscribirse_queda_bloqueado(self):
        nuevo = inscribir_antes(crear_alumno(curp='LOGA130822MMNPRNA7', nombre='Ana'), self.ciclo, self.grado, fecha_inscripcion=dia(-3))
        celdas = self.celdas(nuevo)
        self.assertFalse(celdas[dia(-7)].editable)
        self.assertTrue(celdas[dia(0)].editable)

    def test_sin_horario_avisa_y_nada_se_edita(self):
        self.mat.horarios.all().delete()
        respuesta = self.client.get(URL)
        self.assertContains(respuesta, 'no tiene horario')
        self.assertFalse(any(c.editable for c in self.celdas().values()))

    def test_la_pagina_muestra_la_leyenda_y_el_periodo(self):
        respuesta = self.client.get(URL)
        for texto in ('Presente', 'Falta', 'Retardo', 'Falta justificada', 'Suspensión de clases', 'Sin registro', 'Primer bimestre'):
            self.assertContains(respuesta, texto)

    def test_fechas_personalizadas_dentro_del_periodo(self):
        respuesta = self.client.get(URL, {'desde': dia(-7).isoformat(), 'hasta': dia(-3).isoformat()})
        datos = respuesta.context['datos']
        self.assertEqual([c['fecha'] for c in datos['columnas']], [dia(d) for d in range(-7, -2)])
        self.assertFalse(datos['completo'])
        self.assertIsNone(respuesta.context['aviso_de_fechas'])
        self.assertContains(respuesta, f'min="{self.ciclo.fecha_inicio.isoformat()}" max="{self.ciclo.fecha_fin.isoformat()}"')

    def test_fechas_fuera_del_ciclo_se_ajustan(self):
        inicio, fin = self.ciclo.fecha_inicio, self.ciclo.fecha_fin
        respuesta = self.client.get(URL, {'desde': (inicio - timedelta(days=30)).isoformat(), 'hasta': (fin + timedelta(days=30)).isoformat()})
        datos = respuesta.context['datos']
        self.assertEqual((datos['desde'], datos['hasta']), (inicio, fin))
        self.assertTrue(datos['completo'])
        self.assertContains(respuesta, 'Se ajustó al ciclo escolar')

    def test_fechas_invalidas_o_al_reves_vuelven_al_mes_en_curso(self):
        por_omision = self.client.get(URL).context['datos']
        despues = self.ciclo.fecha_fin + timedelta(days=10)
        casos = {
            'no válidas': {'desde': 'ayer', 'hasta': dia(0).isoformat()},
            'al revés': {'desde': dia(5).isoformat(), 'hasta': dia(-5).isoformat()},
            'fuera del ciclo': {'desde': despues.isoformat(), 'hasta': (despues + timedelta(days=10)).isoformat()},
        }
        for que, parametros in casos.items():
            with self.subTest(que):
                respuesta = self.client.get(URL, parametros)
                datos = respuesta.context['datos']
                self.assertEqual((datos['desde'], datos['hasta']), (por_omision['desde'], por_omision['hasta']))
                self.assertIn('se muestra el mes en curso', respuesta.context['aviso_de_fechas'])

    def test_rangos_rapidos(self):
        atajos = self.client.get(URL).context['atajos']
        self.assertEqual([a['nombre'] for a in atajos], ['Esta semana', 'Este mes', 'Periodo «Primer bimestre»', 'Todo el ciclo'])
        semana = next(a for a in atajos if a['nombre'] == 'Esta semana')
        self.assertEqual((semana['desde'], semana['hasta']), (dia(0), dia(4)))
        self.assertEqual([a['nombre'] for a in atajos if a['activo']], ['Este mes'])   # el que se está viendo
        self.assertEqual((atajos[2]['desde'], atajos[2]['hasta']), (dia(-14), dia(11)))
        self.assertEqual((atajos[-1]['desde'], atajos[-1]['hasta']), (self.ciclo.fecha_inicio, self.ciclo.fecha_fin))
        self.periodo.delete()   # sin periodo abierto, sin su rango
        self.assertEqual([a['nombre'] for a in self.client.get(URL).context['atajos']], ['Esta semana', 'Este mes', 'Todo el ciclo'])

    def test_los_meses_se_distinguen(self):
        self.periodo.fecha_inicio, self.periodo.fecha_fin = dia(-45), dia(40)   # cruza al menos dos cambios de mes
        self.periodo.save()
        respuesta = self.client.get(URL, self.todo_el_periodo())
        datos = respuesta.context['datos']
        self.assertGreaterEqual(len(datos['meses']), 3)
        self.assertEqual(sum(m['columnas'] for m in datos['meses']), len(datos['columnas']))
        self.assertEqual([m['par'] for m in datos['meses'][:3]], [False, True, False])   # bandas alternadas
        inicios = [c['fecha'] for c in datos['columnas'] if c['inicio_mes']]
        self.assertEqual(len(inicios), len(datos['meses']) - 1)
        self.assertTrue(all(c['fecha'].day <= 3 for c in datos['columnas'] if c['inicio_mes']))
        semanas = [c['fecha'] for c in datos['columnas'] if c['inicio_semana']]
        self.assertTrue(all(f.weekday() == 0 for f in semanas))
        primer_mes = datos['meses'][0]['nombre']
        self.assertContains(respuesta, f'<span class="asistencia-matriz__mes-nombre">{primer_mes}</span>')
        self.assertContains(respuesta, 'is-inicio-mes')

    def test_el_docente_solo_captura_los_ultimos_dias(self):
        # Pedido del 2026-10-27: hoy y los días que fijan los ajustes (7 por omisión); lo anterior, la administración
        respuesta = self.client.get(URL, self.todo_el_periodo())
        self.assertContains(respuesta, 'Puedes capturar y corregir la asistencia de hoy y de los 7 días anteriores')
        columnas = {c['fecha']: c for c in respuesta.context['datos']['columnas']}
        self.assertTrue(columnas[dia(-14)]['fuera_de_plazo'])
        self.assertFalse(columnas[dia(-7)]['fuera_de_plazo'])
        self.assertEqual(self.guardar(dia(-14), 'FALTA').status_code, 400)
        self.assertEqual(self.guardar(dia(-7), 'FALTA').status_code, 200)
        configuracion = ConfiguracionAsistencia.cargar()
        configuracion.dias_para_corregir = 0
        configuracion.save()
        self.assertFalse(self.celdas()[dia(-7)].editable)
        self.assertTrue(self.celdas()[dia(0)].editable)

    def test_la_administracion_no_tiene_ese_plazo(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('asistencias:materias'), {'materia': self.mat.pk, **self.todo_el_periodo()})
        fila = next(f for f in respuesta.context['datos']['filas'] if f['inscripcion'] == self.inscripcion)
        celdas = {c['fecha']: celda for c, celda in zip(respuesta.context['datos']['columnas'], fila['celdas'])}
        self.assertTrue(celdas[dia(-14)].editable)
        self.assertEqual(self.client.post(reverse('asistencias:materias_guardar', args=[self.mat.pk]), {
            'inscripcion': self.inscripcion.pk, 'fecha': dia(-14).isoformat(), 'estado': 'PRESENTE', 'version': '',
        }).status_code, 200)

    def test_consultas_constantes(self):
        with CaptureQueriesContext(connection) as pocas:
            self.client.get(URL)
        for numero in range(8):
            inscripcion = inscribir_antes(crear_alumno(curp=f'XAXX0101{numero:02d}HMNRRN0{numero}', nombre=f'Extra{numero}'), self.ciclo, self.grado)
            AsistenciaMateria.objects.create(inscripcion=inscripcion, materia_grado=self.mat, fecha=dia(-7), estado='RETARDO')
        with CaptureQueriesContext(connection) as muchas:
            self.client.get(URL)
        self.assertEqual(len(muchas), len(pocas))


# ---------------------------------------------------------------------------
# Guardar una celda
# ---------------------------------------------------------------------------
@PRUEBAS
class GuardarTests(BaseDocenteTestCase):
    def test_guarda_en_el_registro_de_asistencias(self):
        respuesta = self.guardar(dia(0), 'RETARDO')
        datos = respuesta.json()
        self.assertTrue(datos['ok'])
        self.assertEqual((datos['letra'], datos['clase'], datos['editable']), ('R', 'retardo', True))
        registro = AsistenciaMateria.objects.get(inscripcion=self.inscripcion, materia_grado=self.mat, fecha=dia(0))
        self.assertEqual((registro.estado, registro.registrado_por), ('RETARDO', self.docente))
        self.assertEqual(datos['version'], version_de(registro))
        # como en el pase de lista: estuvo en el colegio
        self.assertEqual(AsistenciaGeneral.objects.get(inscripcion=self.inscripcion, fecha=dia(0)).estado, 'PRESENTE')
        # y se ve en el pase de lista de la materia
        self.assertEqual(self.estados_de_materias(fecha=dia(0)), {'MAT': 'RETARDO'})

    def test_cambia_un_registro_con_su_version(self):
        registro = AsistenciaMateria.objects.create(inscripcion=self.inscripcion, materia_grado=self.mat, fecha=dia(-7), estado='PRESENTE')
        respuesta = self.guardar(dia(-7), 'FALTA', version=version_de(registro))
        self.assertEqual(respuesta.json()['letra'], 'F')
        registro.refresh_from_db()
        self.assertEqual(registro.estado, 'FALTA')

    def test_no_sobrescribe_un_cambio_ajeno(self):
        registro = AsistenciaMateria.objects.create(inscripcion=self.inscripcion, materia_grado=self.mat, fecha=dia(-7), estado='PRESENTE')
        respuesta = self.guardar(dia(-7), 'FALTA', version='')   # la pantalla lo tenía sin registro
        self.assertEqual(respuesta.status_code, 409)
        self.assertEqual(respuesta.json()['letra'], 'P')            # lo que está guardado, para mostrarlo
        registro.refresh_from_db()
        self.assertEqual(registro.estado, 'PRESENTE')

    def test_el_mismo_estado_y_la_misma_observacion_no_cambian_nada(self):
        registro = AsistenciaMateria.objects.create(
            inscripcion=self.inscripcion, materia_grado=self.mat, fecha=dia(-7), estado='FALTA', observaciones='No se presentó',
        )
        version = version_de(registro)
        respuesta = self.guardar(dia(-7), 'FALTA', version=version, observaciones='No se presentó')
        self.assertEqual(respuesta.json()['version'], version)

    def test_rechazos_del_servidor(self):
        DiaNoLectivo.registrar(fecha=dia(-4), motivo='Consejo técnico')
        Justificacion.objects.create(inscripcion=self.inscripcion, fecha=dia(-14), motivo='Enfermedad', todas_materias=True)
        otro_grupo = inscribir_antes(crear_alumno(curp='RAMS120405HMNMRNA3', nombre='Raúl'), self.ciclo, crear_grado('PRIMARIA', 5))
        casos = {
            'suspensión': (dia(-4), 'FALTA', None),
            'día sin clase de la materia': (dia(-13), 'FALTA', None),
            'fecha futura': (dia(7), 'FALTA', None),
            'falta justificada': (dia(-14), 'PRESENTE', None),
            'justificar no es del docente': (dia(0), 'JUSTIFICADA', None),
            'estudiante de otro grupo': (dia(0), 'FALTA', otro_grupo),
            'fuera del periodo': (dia(-21), 'FALTA', None),
            'fin de semana': (dia(-2), 'FALTA', None),
        }
        for que, (fecha, estado, inscripcion) in casos.items():
            with self.subTest(que):
                respuesta = self.guardar(fecha, estado, inscripcion=inscripcion)
                self.assertEqual(respuesta.status_code, 400, respuesta.content)
                self.assertFalse(respuesta.json()['ok'])
        self.assertFalse(AsistenciaMateria.objects.exists())

    def test_solo_por_post_y_con_datos_validos(self):
        url = reverse('asistencias:docente_guardar', args=[self.mat.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, {'inscripcion': 'x', 'fecha': dia(0).isoformat(), 'estado': 'FALTA'}).status_code, 400)
        self.assertEqual(self.client.post(url, {'inscripcion': self.inscripcion.pk, 'fecha': 'mañana', 'estado': 'FALTA'}).status_code, 400)


# ---------------------------------------------------------------------------
# Observaciones: una falta o un retardo se explican
# ---------------------------------------------------------------------------
@PRUEBAS
class ObservacionesTests(BaseDocenteTestCase):
    def registro(self, fecha=None):
        return AsistenciaMateria.objects.get(inscripcion=self.inscripcion, materia_grado=self.mat, fecha=fecha or dia(0))

    def test_una_falta_o_un_retardo_sin_observacion_no_se_guardan(self):
        for estado, que in (('FALTA', 'la falta'), ('RETARDO', 'el retardo')):
            with self.subTest(estado):
                respuesta = self.guardar(dia(0), estado, observaciones='  ')
                self.assertEqual(respuesta.status_code, 400)
                self.assertEqual(respuesta.json()['mensaje'], f'Escribe en las observaciones por qué {que}.')
        self.assertFalse(AsistenciaMateria.objects.exists())

    def test_guarda_la_observacion_en_el_registro(self):
        respuesta = self.guardar(dia(0), 'FALTA', observaciones='  No se   presentó a la clase ')
        datos = respuesta.json()
        self.assertTrue(datos['ok'])
        self.assertEqual(datos['observaciones'], 'No se presentó a la clase')
        self.assertIn('Observación: No se presentó a la clase', datos['nombre'])
        self.assertIn('(No se presentó a la clase)', datos['mensaje'])
        self.assertEqual((self.registro().estado, self.registro().observaciones), ('FALTA', 'No se presentó a la clase'))

    def test_una_observacion_demasiado_larga(self):
        respuesta = self.guardar(dia(0), 'RETARDO', observaciones='x' * 251)
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('hasta 250 caracteres', respuesta.json()['mensaje'])

    def test_con_el_mismo_estado_se_corrige_la_observacion(self):
        version = self.guardar(dia(0), 'RETARDO', observaciones='Llegó tarde').json()['version']
        self.fijar_ahora(9, 5)   # cinco minutos después
        respuesta = self.guardar(dia(0), 'RETARDO', version=version, observaciones='Llegó 15 minutos tarde')
        self.assertNotEqual(respuesta.json()['version'], version)
        self.assertEqual(self.registro().observaciones, 'Llegó 15 minutos tarde')

    def test_presente_borra_la_observacion(self):
        version = self.guardar(dia(0), 'FALTA', observaciones='No se presentó').json()['version']
        respuesta = self.guardar(dia(0), 'PRESENTE', version=version, observaciones='esto no se guarda')
        self.assertEqual(respuesta.json()['observaciones'], '')
        self.assertEqual((self.registro().estado, self.registro().observaciones), ('PRESENTE', ''))

    def test_la_matriz_muestra_la_observacion(self):
        AsistenciaMateria.objects.create(
            inscripcion=self.inscripcion, materia_grado=self.mat, fecha=dia(0), estado='RETARDO', observaciones='Llegó tarde',
        )
        celda = self.celdas()[dia(0)]
        self.assertEqual(celda.observaciones, 'Llegó tarde')
        self.assertEqual(celda.nombre, 'Retardo. Observación: Llegó tarde')
        respuesta = self.client.get(URL)
        self.assertContains(respuesta, 'data-observaciones="Llegó tarde"')
        self.assertContains(respuesta, '¿Por qué', count=0)   # el texto de la pregunta lo pone el JavaScript
        self.assertContains(respuesta, 'data-menu-observacion')

    def test_se_ve_en_la_asistencia_por_materia_de_la_administracion(self):
        self.guardar(dia(0), 'FALTA', observaciones='Enfermo, avisó su mamá')
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('asistencias:materias'), {'materia': self.mat.pk})
        self.assertContains(respuesta, 'data-observaciones="Enfermo, avisó su mamá"')


# ---------------------------------------------------------------------------
# Reporte de lo que muestra la matriz (para imprimir o para Excel) y calendario de fechas
# ---------------------------------------------------------------------------
@PRUEBAS
class ReporteTests(BaseDocenteTestCase):
    URL_REPORTE = reverse('asistencias:docente_reporte')

    def setUp(self):
        super().setUp()
        AsistenciaMateria.objects.create(inscripcion=self.inscripcion, materia_grado=self.mat, fecha=dia(-14), estado='PRESENTE')
        AsistenciaMateria.objects.create(inscripcion=self.inscripcion, materia_grado=self.mat, fecha=dia(-7), estado='RETARDO', observaciones='Llegó tarde')
        AsistenciaMateria.objects.create(inscripcion=self.otra, materia_grado=self.mat, fecha=dia(-7), estado='FALTA', observaciones='No vino')
        self.rango = {'materia': self.mat.pk, **self.todo_el_periodo()}

    def test_resumen_de_una_fila(self):
        from Alumnos.asistencia_docente import Celda, resumen_de
        celdas = [Celda(letra, '', True) for letra in ('P', 'P', 'R', 'F', 'J', 'S', '—', '')]
        self.assertEqual(resumen_de(celdas), {
            'presentes': 2, 'retardos': 1, 'faltas': 1, 'justificadas': 1, 'sin_registro': 1, 'registros': 5, 'porcentaje': 60,
        })

    def test_la_hoja_para_imprimir_lleva_lo_de_la_matriz(self):
        respuesta = self.client.get(self.URL_REPORTE, self.rango)
        self.assertEqual(respuesta.status_code, 200)
        reporte = respuesta.context['reporte']
        resumen = {str(f['alumno']): f['resumen'] for f in reporte['filas']}
        self.assertEqual((resumen[str(self.alumno)]['presentes'], resumen[str(self.alumno)]['retardos']), (1, 1))
        self.assertEqual(reporte['totales']['faltas'], 1)
        self.assertEqual(sum(len(m['columnas']) for m in reporte['meses']), len(respuesta.context['datos']['columnas']))
        self.assertEqual([n['observacion'] for n in reporte['observaciones']], ['Llegó tarde', 'No vino'])
        for texto in ('Reporte de asistencia', 'Resumen por estudiante', 'Observaciones', str(self.profesor), 'Primer bimestre', 'Llegó tarde'):
            self.assertContains(respuesta, texto)
        self.assertContains(respuesta, '@page { size: A4 landscape')
        self.assertContains(respuesta, 'data-imprimir')

    def test_respeta_las_fechas_elegidas(self):
        respuesta = self.client.get(self.URL_REPORTE, {'materia': self.mat.pk, 'desde': dia(-7).isoformat(), 'hasta': dia(-3).isoformat()})
        self.assertEqual([c['fecha'] for c in respuesta.context['datos']['columnas']], [dia(d) for d in range(-7, -2)])
        self.assertEqual([n['observacion'] for n in respuesta.context['reporte']['observaciones']], ['Llegó tarde', 'No vino'])
        respuesta = self.client.get(self.URL_REPORTE, {'materia': self.mat.pk, 'desde': dia(-14).isoformat(), 'hasta': dia(-10).isoformat()})
        self.assertEqual(respuesta.context['reporte']['observaciones'], [])

    def test_para_excel(self):
        respuesta = self.client.get(self.URL_REPORTE, {**self.rango, 'formato': 'csv'})
        self.assertEqual(respuesta['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('attachment; filename="asistencia-mat-4-a-', respuesta['Content-Disposition'])
        texto = respuesta.content.decode('utf-8-sig')
        lineas = texto.splitlines()
        self.assertEqual(lineas[0], 'Reporte de asistencia')
        encabezado = next(linea for linea in lineas if linea.startswith('Estudiante,'))
        self.assertIn(f"L {dia(0):%d/%m}", encabezado)
        self.assertTrue(encabezado.endswith('Presentes,Retardos,Faltas,Faltas justificadas,Sin registro,Asistencia (%)'))
        self.assertIn('Observaciones', lineas)
        self.assertIn('No vino', texto)

    def test_solo_sus_materias(self):
        self.assertEqual(self.client.get(self.URL_REPORTE, {'materia': self.esp.pk}).status_code, 403)
        self.assertEqual(self.client.get(self.URL_REPORTE).status_code, 403)
        self.client.force_login(self.admin)   # sin ficha de profesor
        self.assertEqual(self.client.get(self.URL_REPORTE, self.rango).status_code, 403)

    def test_sin_periodo_tambien_hay_reporte(self):
        self.periodo.delete()
        respuesta = self.client.get(self.URL_REPORTE, self.rango)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Ciclo escolar')
        self.assertNotContains(respuesta, 'Periodo abierto')

    def test_sin_dias_de_clase_vuelve_con_aviso(self):
        sabado = (dia(5)).isoformat()
        respuesta = self.client.get(self.URL_REPORTE, {'materia': self.mat.pk, 'desde': sabado, 'hasta': sabado}, follow=True)
        self.assertRedirects(respuesta, f'{URL}?materia={self.mat.pk}')
        self.assertContains(respuesta, 'No hay asistencia que reportar en esas fechas.')

    def test_la_matriz_ofrece_el_reporte_de_lo_que_muestra(self):
        respuesta = self.client.get(URL, {'materia': self.mat.pk, 'desde': dia(-7).isoformat(), 'hasta': dia(-3).isoformat()})
        consulta = f'?materia={self.mat.pk}&amp;desde={dia(-7).isoformat()}&amp;hasta={dia(-3).isoformat()}'
        self.assertContains(respuesta, f'{self.URL_REPORTE}{consulta}"')
        self.assertContains(respuesta, f'{self.URL_REPORTE}{consulta}&amp;formato=csv"')

    def test_las_fechas_usan_el_calendario(self):
        respuesta = self.client.get(URL)
        self.assertContains(respuesta, 'data-rango-fechas data-rango-enviar')
        self.assertContains(respuesta, 'data-rango-desde')
        self.assertContains(respuesta, 'data-rango-hasta')
        self.assertContains(respuesta, 'js/calendario.js')
