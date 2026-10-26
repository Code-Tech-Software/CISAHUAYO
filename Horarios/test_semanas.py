"""Semanas A y B (pedido del 2026-10-26): el cálculo de la semana de cada fecha, las excepciones, los empalmes de los
profesores entre niveles, las versiones del horario y las pantallas de captura y configuración."""
from datetime import date, time, timedelta

from django.contrib.admin.models import LogEntry
from django.test import SimpleTestCase
from django.urls import reverse

from Alumnos.asistencias import clases_por_grupo, motivo_sin_clases
from Alumnos.models import CicloEscolar, ConfiguracionHorario, DiaNoLectivo, ExcepcionSemana, HorarioMateria
from Alumnos.semanas import Calendario, bloques_de_fecha, calcular, fechas_con_clase
from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase, crear_grado, crear_profesor, grupo_de, materia_en_grado

from . import cambios
from .forms import HorarioCrearForm

LUNES = date(2026, 10, 19)
SOLO, REINICIO = ExcepcionSemana.SOLO_ESTA, ExcepcionSemana.REINICIO


def semana(n):
    """El lunes n semanas después de LUNES."""
    return LUNES + timedelta(weeks=n)


class CalculoTests(SimpleTestCase):
    def test_una_semana_a_le_sigue_b_y_luego_a(self):
        self.assertEqual([calcular(semana(n), LUNES, 'A') for n in range(-2, 4)], ['A', 'B', 'A', 'B', 'A', 'B'])

    def test_al_cambiar_de_mes_y_de_anio(self):
        referencia = date(2026, 12, 21)
        self.assertEqual(calcular(date(2026, 11, 30), referencia, 'A'), 'B')   # tres semanas antes
        self.assertEqual(calcular(date(2026, 12, 28), referencia, 'A'), 'B')   # la semana que cruza el año
        self.assertEqual(calcular(date(2027, 1, 4), referencia, 'A'), 'A')
        self.assertEqual(calcular(date(2027, 2, 1), referencia, 'A'), 'A')

    def test_no_usa_la_paridad_del_numero_de_semana(self):
        # La semana 53 de 2026 y la 1 de 2027 son las dos impares, pero son semanas seguidas: B y A
        self.assertEqual(date(2026, 12, 28).isocalendar()[1] % 2, date(2027, 1, 4).isocalendar()[1] % 2)
        self.assertNotEqual(calcular(date(2026, 12, 28), date(2026, 12, 21), 'A'), calcular(date(2027, 1, 4), date(2026, 12, 21), 'A'))

    def test_una_excepcion_de_una_semana_no_altera_las_siguientes(self):
        excepciones = [(semana(2), 'B', SOLO)]
        self.assertEqual([calcular(semana(n), LUNES, 'A', excepciones) for n in range(5)], ['A', 'B', 'B', 'B', 'A'])

    def test_reiniciar_cambia_las_semanas_siguientes(self):
        excepciones = [(semana(2), 'B', REINICIO)]
        self.assertEqual([calcular(semana(n), LUNES, 'A', excepciones) for n in range(5)], ['A', 'B', 'B', 'A', 'B'])
        self.assertEqual(calcular(semana(-1), LUNES, 'A', excepciones), 'B')   # lo anterior no cambia


@PRUEBAS
class SemanasTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = CicloEscolar.objects.create(nombre='2026-2027', fecha_inicio=date(2026, 8, 24), fecha_fin=date(2027, 7, 9), activo=True)
        self.primaria = crear_grado('PRIMARIA', 1)
        self.secundaria = crear_grado('SECUNDARIA', 1)
        self.preescolar = crear_grado('PREESCOLAR', 1)
        self.config = ConfiguracionHorario.objects.create(
            ciclo=self.ciclo, nivel='PRIMARIA', modalidad=ConfiguracionHorario.ALTERNADO, fecha_referencia=LUNES + timedelta(days=2),
        )
        self.profesor = crear_profesor()
        self.mat = materia_en_grado('MAT', self.primaria, self.ciclo, inicio=None, profesor=self.profesor)
        self.bloque_a = HorarioMateria.objects.create(materia_grado=self.mat, semana='A', dia_semana=0, hora_inicio=time(8), hora_fin=time(9))
        self.bloque_b = HorarioMateria.objects.create(materia_grado=self.mat, semana='B', dia_semana=1, hora_inicio=time(8), hora_fin=time(9))
        self.grupo = grupo_de(self.primaria)

    def materias(self, fecha):
        return [c.asignacion.materia.clave for c in clases_por_grupo(self.ciclo, fecha).get(self.grupo.pk, [])]

    # --- Calendario y asistencia ----------------------------------------------------------------------------------
    def test_las_clases_de_cada_fecha_siguen_la_semana(self):
        self.assertEqual(self.materias(LUNES), ['MAT'])                         # lunes de semana A
        self.assertEqual(self.materias(semana(1)), [])                          # lunes de semana B: la clase es el martes
        self.assertEqual(self.materias(semana(1) + timedelta(days=1)), ['MAT'])
        self.assertEqual(fechas_con_clase(self.mat, [LUNES, semana(1), semana(2)]), {LUNES, semana(2)})

    def test_un_festivo_no_cambia_la_secuencia(self):
        DiaNoLectivo.objects.create(fecha=semana(1), nivel='PRIMARIA', motivo='Asueto')
        self.assertIn('sin clases', motivo_sin_clases(semana(1), self.ciclo, nivel='PRIMARIA').lower())
        calendario = Calendario(self.ciclo)
        self.assertEqual([calendario.semana(semana(n), 'PRIMARIA') for n in range(3)], ['A', 'B', 'A'])

    def test_las_vacaciones_siguen_la_alternancia(self):
        for n in (1, 2):
            for dia in range(5):
                DiaNoLectivo.objects.create(fecha=semana(n) + timedelta(days=dia), nivel='PRIMARIA', motivo='Vacaciones')
        self.assertEqual(Calendario(self.ciclo).semana(semana(3), 'PRIMARIA'), 'B')

    def test_excepciones_guardadas(self):
        ExcepcionSemana.objects.create(configuracion=self.config, lunes=semana(2), semana='B', tipo=SOLO)
        ExcepcionSemana.objects.create(configuracion=self.config, lunes=semana(6), semana='A', tipo=REINICIO)
        calendario = Calendario(self.ciclo)
        self.assertEqual([calendario.semana(semana(n), 'PRIMARIA') for n in range(9)], ['A', 'B', 'B', 'B', 'A', 'B', 'A', 'B', 'A'])
        self.assertEqual(self.materias(semana(2)), [])   # esa semana es B: el lunes no hay clase

    def test_los_niveles_con_horario_fijo_siguen_igual(self):
        historia = materia_en_grado('HIS', self.secundaria, self.ciclo, dia=0, inicio=(10, 0), fin=(11, 0))
        grupo = grupo_de(self.secundaria)
        for n in range(3):
            clases = clases_por_grupo(self.ciclo, semana(n)).get(grupo.pk, [])
            self.assertEqual([c.asignacion for c in clases], [historia])
        self.assertEqual(Calendario(self.ciclo).semana(LUNES, 'SECUNDARIA'), '')

    # --- Empalmes ---------------------------------------------------------------------------------------------------
    def test_el_mismo_bloque_puede_estar_en_a_y_en_b(self):
        form = HorarioCrearForm({'materia_grado': self.mat.pk, 'dias': [0], 'inicio_0': '08:00', 'fin_0': '09:00'},
                                grupo=self.grupo, ciclo=self.ciclo, semana='B')
        self.assertTrue(form.is_valid(), form.errors)
        form.guardar()
        self.assertEqual(HorarioMateria.objects.filter(materia_grado=self.mat, dia_semana=0).count(), 2)

    def test_un_profesor_no_da_dos_clases_en_una_misma_fecha(self):
        fisica = materia_en_grado('FIS', self.secundaria, self.ciclo, inicio=None, profesor=self.profesor)
        grupo = grupo_de(self.secundaria)
        choca = HorarioCrearForm({'materia_grado': fisica.pk, 'dias': [0], 'inicio_0': '08:30', 'fin_0': '09:30'}, grupo=grupo, ciclo=self.ciclo)
        self.assertFalse(choca.is_valid())   # secundaria es fija: coincide con el lunes de la semana A de primaria
        self.assertIn('semana A', choca.errors['inicio_0'][0])
        libre = HorarioCrearForm({'materia_grado': fisica.pk, 'dias': [2], 'inicio_0': '08:00', 'fin_0': '09:00',
                                  'inicio_2': '08:00', 'fin_2': '09:00'}, grupo=grupo, ciclo=self.ciclo)
        self.assertTrue(libre.is_valid(), libre.errors)

    def test_entre_niveles_alternados_solo_choca_lo_que_cae_en_la_misma_fecha(self):
        # Preescolar alterna al revés que primaria: su semana A es la B de primaria
        ConfiguracionHorario.objects.create(ciclo=self.ciclo, nivel='PREESCOLAR', modalidad=ConfiguracionHorario.ALTERNADO,
                                            fecha_referencia=LUNES, semana_referencia='B')
        juego = materia_en_grado('JUE', self.preescolar, self.ciclo, inicio=None, profesor=self.profesor)
        grupo = grupo_de(self.preescolar)
        datos = {'materia_grado': juego.pk, 'dias': [0], 'inicio_0': '08:00', 'fin_0': '09:00'}
        self.assertTrue(HorarioCrearForm(datos, grupo=grupo, ciclo=self.ciclo, semana='A').is_valid())    # nunca coinciden
        self.assertFalse(HorarioCrearForm(datos, grupo=grupo, ciclo=self.ciclo, semana='B').is_valid())   # misma fecha

    # --- Versiones e historial --------------------------------------------------------------------------------------
    def test_un_cambio_con_fecha_conserva_el_horario_anterior(self):
        nuevo = cambios.cambiar(self.bloque_a, desde=semana(2), hora_inicio=time(10), hora_fin=time(11))
        self.bloque_a.refresh_from_db()
        self.assertEqual(self.bloque_a.vigente_hasta, semana(2) - timedelta(days=1))
        self.assertEqual(nuevo.vigente_desde, semana(2))
        self.assertEqual([b.hora_inicio for b in bloques_de_fecha(LUNES, self.ciclo, materia_grado=self.mat)], [time(8)])
        self.assertEqual([b.hora_inicio for b in bloques_de_fecha(semana(2), self.ciclo, materia_grado=self.mat)], [time(10)])
        self.assertEqual(list(self.mat.horarios.all()), [nuevo, self.bloque_b] if nuevo.dia_semana < 1 else [self.bloque_b, nuevo])

    def test_los_registros_historicos_quedan_intactos(self):
        from Bitacoras import reglas
        entrada, _ = reglas.crear({
            'grupo': self.grupo, 'asignacion': self.mat, 'fecha': LUNES, 'bloque': self.bloque_a, 'general': True, 'alumnos': [],
            'titulo': 'Clase', 'descripcion': 'Todo bien', 'seguimiento': '',
        }, self.admin)
        borrado = cambios.retirar(self.bloque_a)   # «quitar» sin fecha: como la bitácora ya lo usa, se conserva cerrado
        self.assertFalse(borrado)
        entrada.refresh_from_db()
        self.assertEqual(entrada.bloque_id, self.bloque_a.pk)
        self.assertEqual((entrada.hora_inicio, entrada.hora_fin), (time(8), time(9)))
        self.assertTrue(HorarioMateria.historial.filter(pk=self.bloque_a.pk).exists())
        self.assertFalse(self.mat.horarios.filter(pk=self.bloque_a.pk).exists())

    # --- Pantallas --------------------------------------------------------------------------------------------------
    def url_grupo(self, **parametros):
        return reverse('horarios:grupo', args=[self.grupo.pk]), {'ciclo': self.ciclo.pk, **parametros}

    def test_pestanas_de_las_dos_semanas_y_por_fecha(self):
        url, parametros = self.url_grupo(vista='A')
        respuesta = self.client.get(url, parametros)
        self.assertContains(respuesta, 'Semana A')
        self.assertContains(respuesta, 'Copiar semana A a semana B')
        self.assertEqual([b.pk for fila in respuesta.context['cuadricula']['filas'] for celda in fila['celdas'] for b in celda
                          if not getattr(b, 'es_recreo', False)], [self.bloque_a.pk])
        url, parametros = self.url_grupo(vista='fecha', fecha=(semana(1) + timedelta(days=3)).isoformat())
        respuesta = self.client.get(url, parametros)
        self.assertEqual(respuesta.context['semana'].tipo, 'B')
        self.assertEqual(respuesta.context['semana'].lunes, semana(1))
        self.assertContains(respuesta, '26 de octubre al 1 de noviembre')
        self.assertFalse(respuesta.context['editable_aqui'])

    def test_copiar_la_semana_a_en_la_b(self):
        url = reverse('horarios:copiar_semana', args=[self.grupo.pk])
        self.client.post(f'{url}?ciclo={self.ciclo.pk}', {'vigencia': ''})
        de_b = list(self.mat.horarios.filter(semana='B'))
        self.assertEqual([(b.dia_semana, b.hora_inicio) for b in de_b], [(0, time(8))])

    def test_la_comparacion_avisa_de_una_materia_que_falta(self):
        materia_en_grado('ESP', self.primaria, self.ciclo, inicio=None)
        HorarioMateria.objects.create(materia_grado=self.mat.__class__.objects.get(materia__clave='ESP'), semana='A',
                                      dia_semana=2, hora_inicio=time(8), hora_fin=time(9))
        url, parametros = self.url_grupo(vista='A')
        comparacion = self.client.get(url, parametros).context['comparacion']
        self.assertEqual([(f['asignacion'].materia.clave, f['falta']) for f in comparacion['faltan']], [('ESP', 'B')])

    def test_activar_las_semanas_copia_el_horario_fijo_y_queda_registrado(self):
        juego = materia_en_grado('JUE', self.preescolar, self.ciclo, dia=3, inicio=(9, 0), fin=(10, 0))
        respuesta = self.client.post(f"{reverse('horarios:modalidad')}?ciclo={self.ciclo.pk}", {
            'nivel': 'PREESCOLAR', 'preescolar-modalidad': 'ALTERNADO', 'preescolar-fecha_referencia': LUNES.isoformat(),
            'preescolar-semana_referencia': 'A',
        })
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(sorted(juego.horarios.values_list('semana', flat=True)), ['A', 'B'])
        self.assertTrue(LogEntry.objects.filter(change_message__contains='preescolar').exists())

    def test_secundaria_no_puede_alternar(self):
        self.client.post(f"{reverse('horarios:modalidad')}?ciclo={self.ciclo.pk}", {
            'nivel': 'SECUNDARIA', 'secundaria-modalidad': 'ALTERNADO', 'secundaria-fecha_referencia': LUNES.isoformat(),
        })
        self.assertFalse(ConfiguracionHorario.objects.filter(nivel='SECUNDARIA').exists())

    def test_la_vista_previa_no_guarda_y_guardar_si(self):
        url = f"{reverse('horarios:excepcion')}?ciclo={self.ciclo.pk}"
        datos = {'nivel': 'PRIMARIA', 'excepcion-primaria-fecha': (semana(2) + timedelta(days=2)).isoformat(),
                 'excepcion-primaria-semana': 'B', 'excepcion-primaria-tipo': REINICIO}
        vista = self.client.post(url, datos)
        self.assertContains(vista, 'Vista previa')
        self.assertFalse(ExcepcionSemana.objects.exists())
        filas = next(t for t in vista.context['niveles'] if t['nivel'] == 'PRIMARIA')['vista_previa']['semanas']
        self.assertEqual([(f['antes'].tipo, f['despues'].tipo) for f in filas[:3]], [('A', 'B'), ('B', 'A'), ('A', 'B')])
        self.client.post(url, {**datos, 'guardar': '1'})
        excepcion = ExcepcionSemana.objects.get()
        self.assertEqual((excepcion.lunes, excepcion.tipo, excepcion.creado_por), (semana(2), REINICIO, self.admin))
        self.assertTrue(LogEntry.objects.filter(change_message__contains='Excepción').exists())

    def test_la_configuracion_pide_permiso_para_cambiar(self):
        self.con_permisos('view_horariomateria')
        self.assertEqual(self.client.get(reverse('horarios:semanas'), {'ciclo': self.ciclo.pk}).status_code, 200)
        respuesta = self.client.post(f"{reverse('horarios:excepcion')}?ciclo={self.ciclo.pk}", {'nivel': 'PRIMARIA'})
        self.assertEqual(respuesta.status_code, 403)

    def test_el_portal_muestra_la_semana_con_sus_fechas(self):
        from CISAHUAYO.pruebas import crear_alumno, inscribir
        from PortalEstudiantes.resumen import resumen
        alumno = crear_alumno()
        inscribir(alumno, self.ciclo, self.primaria, fecha_inscripcion=self.ciclo.fecha_inicio)
        for lunes, letra, bloque in ((LUNES, 'A', self.bloque_a), (semana(1), 'B', self.bloque_b)):
            datos = resumen(alumno, semana=lunes + timedelta(days=2))
            self.assertEqual((datos['semana'].tipo, datos['semana'].lunes), (letra, lunes))
            bloques = [b for fila in datos['cuadricula']['filas'] for celda in fila['celdas'] for b in celda if not getattr(b, 'es_recreo', False)]
            self.assertEqual(bloques, [bloque])
