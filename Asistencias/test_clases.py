"""Pase de lista por materia: las clases del día y la lista de cada una."""
from datetime import timedelta

from django.db import connection
from django.test.utils import CaptureQueriesContext

from Alumnos import asistencias as reglas
from Alumnos.models import AsistenciaGeneral, AsistenciaMateria, DiaNoLectivo, Justificacion
from Asistencias.tests import entrar, url
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseAsistenciaTestCase,
    ciclo_cerrado_de_prueba,
    crear_alumno,
    crear_grado,
    crear_profesor,
    inscribir_antes,
    lunes,
    materia_en_grado,
)


@PRUEBAS
class ClasesTests(BaseAsistenciaTestCase):
    hora = (8, 5)

    def setUp(self):
        super().setUp()
        self.g5 = crear_grado('PRIMARIA', 5)
        self.his = materia_en_grado('HIS', self.g5, self.ciclo, inicio=(8, 30), fin=(9, 30))
        self.a2 = inscribir_antes(crear_alumno(), self.ciclo, self.grado)
        inscribir_antes(crear_alumno(), self.ciclo, self.g5)

    def clases(self, **consulta):
        respuesta = self.client.get(url('clases', **consulta))
        self.assertEqual(respuesta.status_code, 200)
        return respuesta

    def claves(self, respuesta):
        return [fila['asignacion'].materia.clave for fila in respuesta.context['filas']]

    def test_las_clases_del_dia_van_por_hora_y_luego_por_grado(self):
        self.assertEqual(self.claves(self.clases()), ['MAT', 'HIS', 'ESP', 'CIE'])

    def test_no_incluye_materias_de_otros_dias_ni_quitadas(self):
        materia_en_grado('MAR', self.grado, self.ciclo, dia=1)
        materia_en_grado('QUI', self.grado, self.ciclo, activa=False)
        self.assertEqual(self.claves(self.clases()), ['MAT', 'HIS', 'ESP', 'CIE'])

    def test_cuenta_presentes_retardos_faltas_y_pendientes_de_cada_clase(self):
        entrar(self.alumno, (7, 45))
        entrar(self.a2.alumno, (8, 20))
        reglas.guardar_pase_de_lista(self.mat, lunes(), [(self.a2, 'FALTA', '')])
        mat = next(f for f in self.clases().context['filas'] if f['asignacion'] == self.mat)
        self.assertEqual({k: mat[k] for k in ('inscritos', 'presentes', 'retardos', 'faltas', 'sin_registro')}, {'inscritos': 2, 'presentes': 1, 'retardos': 0, 'faltas': 1, 'sin_registro': 0})

    def test_distingue_la_lista_tomada_de_la_que_solo_esta_por_confirmar(self):
        entrar(self.alumno, (7, 45))
        por_confirmar = next(f for f in self.clases().context['filas'] if f['asignacion'] == self.mat)
        self.assertFalse(por_confirmar['confirmada'])
        self.assertContains(self.clases(), 'Por confirmar')
        reglas.guardar_pase_de_lista(self.mat, lunes(), [(self.inscripcion, 'PRESENTE', '')])
        tomada = next(f for f in self.clases().context['filas'] if f['asignacion'] == self.mat)
        self.assertTrue(tomada['confirmada'])
        self.assertContains(self.clases(), 'Lista tomada')

    def test_filtra_por_profesor_y_por_grado(self):
        profesor = crear_profesor()
        self.esp.profesor = profesor
        self.esp.save()
        self.assertEqual(self.claves(self.clases(profesor=profesor.pk)), ['ESP'])
        self.assertEqual(self.claves(self.clases(grado=self.g5.pk)), ['HIS'])
        self.assertEqual(self.claves(self.clases(grado=self.g5.pk, profesor=profesor.pk)), [])
        self.assertContains(self.clases(grado=self.g5.pk, profesor=profesor.pk), 'No hay clases con esos filtros')

    def test_un_dia_sin_horario_o_sin_clases(self):
        martes = lunes() - timedelta(days=6)
        self.assertContains(self.clases(fecha=martes.isoformat()), 'No hay clases en el horario de este día')
        DiaNoLectivo.objects.create(fecha=lunes(), motivo='Puente')
        respuesta = self.clases()
        self.assertContains(respuesta, 'No hay clases este día')
        self.assertEqual(respuesta.context['filas'], [])

    def test_muestra_al_profesor_o_avisa_que_falta(self):
        self.mat.profesor = crear_profesor()
        self.mat.save()
        respuesta = self.clases()
        self.assertContains(respuesta, 'Marta Rangel Soto')
        self.assertContains(respuesta, 'Sin profesor')

    def test_consultas_constantes(self):
        with CaptureQueriesContext(connection) as pocas:
            self.clases()
        for numero in range(6, 12):
            grado = crear_grado('SECUNDARIA', numero)
            materia_en_grado(f'X{numero}', grado, self.ciclo, inicio=(13, 0), fin=(14, 0), profesor=crear_profesor(telefono=f'35300000{numero:02d}'))
            inscribir_antes(crear_alumno(), self.ciclo, grado)
        with CaptureQueriesContext(connection) as muchas:
            self.clases()
        self.assertEqual(len(muchas), len(pocas))


@PRUEBAS
class ClaseTests(BaseAsistenciaTestCase):
    hora = (8, 5)

    def setUp(self):
        super().setUp()
        self.a2 = inscribir_antes(crear_alumno(nombre='Beto', apellido_paterno='Zuñiga'), self.ciclo, self.grado)
        self.a3 = inscribir_antes(crear_alumno(nombre='Ana', apellido_paterno='Lara'), self.ciclo, self.grado)
        self.volver = url('clases', fecha=lunes().isoformat())

    def lista(self, asignacion=None, **consulta):
        respuesta = self.client.get(url('clase', (asignacion or self.mat).pk, **consulta))
        self.assertEqual(respuesta.status_code, 200)
        return respuesta

    def filas(self, respuesta):
        return {f['inscripcion'].pk: f for f in respuesta.context['filas']}

    def guardar(self, estados, observaciones=None, asignacion=None, **extra):
        datos = {'fecha': lunes().isoformat()}
        for inscripcion, estado in estados.items():
            datos[f'estado_{inscripcion.pk}'] = estado
        for inscripcion, texto in (observaciones or {}).items():
            datos[f'obs_{inscripcion.pk}'] = texto
        datos.update(extra)
        return self.client.post(url('clase', (asignacion or self.mat).pk), datos, follow=True)

    # --- la lista -----------------------------------------------------------------------------------
    def test_los_alumnos_van_en_orden_alfabetico(self):
        self.assertEqual([str(f['alumno']) for f in self.lista().context['filas']], [str(self.a3.alumno), str(self.alumno), str(self.a2.alumno)])

    def test_quien_ya_entro_aparece_presente_y_quien_no_con_falta(self):
        entrar(self.alumno, (7, 45))
        entrar(self.a2.alumno, (8, 30))                      # llegó con la clase ya empezada: retardo en ella
        filas = self.filas(self.lista())
        self.assertEqual(filas[self.inscripcion.pk]['sugerido'], 'PRESENTE')
        self.assertEqual(filas[self.a2.pk]['sugerido'], 'RETARDO')
        self.assertEqual(filas[self.a3.pk]['sugerido'], 'FALTA')
        self.assertTrue(filas[self.a3.pk]['sin_entrada'])
        self.assertFalse(filas[self.inscripcion.pk]['sin_entrada'])

    def test_lo_ya_registrado_manda_sobre_lo_propuesto(self):
        entrar(self.alumno, (7, 45))
        AsistenciaMateria.objects.filter(materia_grado=self.mat).update(estado='RETARDO')
        self.assertEqual(self.filas(self.lista())[self.inscripcion.pk]['sugerido'], 'RETARDO')

    def test_una_falta_general_se_propone_como_falta(self):
        reglas.fijar_asistencia_general(self.a3, lunes(), 'FALTA', propagar=False)
        self.assertEqual(self.filas(self.lista())[self.a3.pk]['sugerido'], 'FALTA')

    def test_marca_las_justificaciones_que_cubren_la_clase(self):
        todas = Justificacion.objects.create(inscripcion=self.a2, fecha=lunes(), motivo='Cita', todas_materias=True)
        algunas = Justificacion.objects.create(inscripcion=self.a3, fecha=lunes(), motivo='Torneo')
        algunas.materias.set([self.mat])
        filas = self.filas(self.lista())
        self.assertEqual([filas[i.pk]['justificada'] for i in (self.inscripcion, self.a2, self.a3)], [False, True, True])
        self.assertFalse(self.filas(self.lista(self.esp))[self.a3.pk]['justificada'])
        todas.activa = False
        todas.save()
        self.assertFalse(self.filas(self.lista())[self.a2.pk]['justificada'])

    def test_muestra_el_horario_y_el_profesor_de_la_clase(self):
        self.mat.profesor = crear_profesor()
        self.mat.save()
        respuesta = self.lista()
        self.assertContains(respuesta, '08:00–09:00')
        self.assertContains(respuesta, 'Marta Rangel Soto')

    def test_avisa_si_la_materia_no_se_imparte_ese_dia(self):
        martes = lunes() - timedelta(days=6)
        respuesta = self.lista(fecha=martes.isoformat())
        self.assertFalse(respuesta.context['se_imparte'])
        self.assertContains(respuesta, 'no se imparte los martes')

    def test_no_muestra_el_futuro(self):
        self.assertEqual(self.lista(fecha=(lunes() + timedelta(days=7)).isoformat()).context['fecha'], lunes())

    def test_materia_inexistente_da_404(self):
        self.assertEqual(self.client.get(url('clase', 9999)).status_code, 404)

    # --- guardar ----------------------------------------------------------------------------------------
    def test_guarda_el_pase_de_lista_y_vuelve_a_las_clases_con_mensaje(self):
        entrar(self.alumno, (7, 45))
        respuesta = self.guardar({self.inscripcion: 'FALTA', self.a2: 'RETARDO', self.a3: 'PRESENTE'}, {self.inscripcion: ' salió   temprano '})
        self.assertRedirects(respuesta, self.volver)
        self.assertContains(respuesta, 'Se guardó la lista de Mat (4° Primaria): 1 presente, 1 retardo y 1 falta.')
        registros = {r.inscripcion_id: r for r in AsistenciaMateria.objects.filter(materia_grado=self.mat)}
        self.assertEqual({k: (r.estado, r.origen, r.registrado_por) for k, r in registros.items()}, {
            self.inscripcion.pk: ('FALTA', 'PASE', self.admin), self.a2.pk: ('RETARDO', 'PASE', self.admin), self.a3.pk: ('PRESENTE', 'PASE', self.admin),
        })
        self.assertEqual(registros[self.inscripcion.pk].observaciones, 'salió temprano')

    def test_presente_en_clase_sin_entrada_registra_su_asistencia_general(self):
        self.guardar({self.a3: 'PRESENTE', self.a2: 'FALTA'})
        self.assertEqual(AsistenciaGeneral.objects.get(inscripcion=self.a3).estado, 'PRESENTE')
        self.assertFalse(AsistenciaGeneral.objects.filter(inscripcion=self.a2).exists())

    def test_guardar_de_nuevo_corrige_sin_duplicar(self):
        self.guardar({self.a3: 'FALTA'})
        self.guardar({self.a3: 'PRESENTE'})
        self.assertEqual(AsistenciaMateria.objects.filter(inscripcion=self.a3, materia_grado=self.mat).count(), 1)
        self.assertEqual(AsistenciaMateria.objects.get(inscripcion=self.a3, materia_grado=self.mat).estado, 'PRESENTE')

    def test_ignora_estados_invalidos_y_alumnos_de_otra_lista(self):
        otro = inscribir_antes(crear_alumno(), self.ciclo, crear_grado('PRIMARIA', 5))
        respuesta = self.guardar({self.a3: 'PRESENTE', self.a2: 'LO_QUE_SEA', otro: 'PRESENTE'})
        self.assertContains(respuesta, '1 presente')
        self.assertEqual(AsistenciaMateria.objects.filter(materia_grado=self.mat).count(), 1)
        self.assertFalse(AsistenciaMateria.objects.filter(inscripcion=otro).exists())

    def test_sin_alumnos_que_guardar_avisa(self):
        self.assertContains(self.guardar({}), 'No había estudiantes a quienes pasar lista')

    def test_no_se_guarda_en_un_ciclo_cerrado_ni_en_una_materia_quitada_ni_en_un_dia_sin_clases(self):
        self.mat.activa = False
        self.mat.save()
        self.assertContains(self.guardar({self.a3: 'PRESENTE'}), 'ya no se imparte')
        self.mat.activa = True
        self.mat.save()
        DiaNoLectivo.objects.create(fecha=lunes(), motivo='Puente')
        self.assertContains(self.guardar({self.a3: 'PRESENTE'}), 'Puente')
        self.assertFalse(AsistenciaMateria.objects.exists())

    def test_una_clase_de_un_ciclo_cerrado_es_de_solo_lectura(self):
        cerrado = ciclo_cerrado_de_prueba()
        vieja = materia_en_grado('OLD', self.grado, cerrado)
        inscribir_antes(crear_alumno(), cerrado, self.grado)
        fecha = cerrado.fecha_inicio + timedelta(days=(7 - cerrado.fecha_inicio.weekday()) % 7)
        respuesta = self.lista(vieja, fecha=fecha.isoformat())
        self.assertFalse(respuesta.context['editable'])
        self.assertNotContains(respuesta, 'Guardar lista')
        resultado = self.client.post(url('clase', vieja.pk), {'fecha': fecha.isoformat()}, follow=True)
        self.assertContains(resultado, 'no es el ciclo actual')

    def test_ver_la_lista_no_da_permiso_para_guardarla(self):
        self.con_permisos('view_asistenciamateria')
        respuesta = self.lista()
        self.assertNotContains(respuesta, 'Guardar lista')
        self.assertEqual(self.client.post(url('clase', self.mat.pk), {'fecha': lunes().isoformat(), f'estado_{self.a3.pk}': 'PRESENTE'}).status_code, 403)
        self.assertFalse(AsistenciaMateria.objects.exists())

    def test_indica_quien_tomo_la_lista(self):
        self.guardar({self.a3: 'PRESENTE'})
        respuesta = self.lista()
        self.assertTrue(respuesta.context['confirmada'])
        self.assertEqual(respuesta.context['confirmada_por'], self.admin)
        self.assertContains(respuesta, 'Lista tomada por admin')

    def test_consultas_constantes(self):
        with CaptureQueriesContext(connection) as pocas:
            self.lista()
        for _ in range(15):
            inscripcion = inscribir_antes(crear_alumno(), self.ciclo, self.grado)
            entrar(inscripcion.alumno)
        with CaptureQueriesContext(connection) as muchas:
            self.lista()
        self.assertEqual(len(muchas), len(pocas))
