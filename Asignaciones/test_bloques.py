"""Bloques simultáneos y grupos de clase (pedido del 2026-10-30): los casos de aceptación A, B y C de principio a fin y las
reglas críticas (población, conflictos, sustitución, fecha efectiva, permisos y clases tradicionales)."""
from datetime import time, timedelta
from decimal import Decimal

from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from Alumnos import clases
from Alumnos.academico import materias_por_asignar
from Alumnos.asistencia_docente import asignaciones_del_profesor, guardar_cambio, inscripciones_de, matriz
from Alumnos.asistencias import cerrar_dia, clases_del_estudiante
from Alumnos.models import (
    AsistenciaMateria, BloqueSimultaneo, ConfiguracionAsistencia, ConfiguracionHorario, Grupo, HorarioMateria, Inscripcion, IntegranteClase,
    Materia, MateriaGrado, Periodo, Semestre,
)
from Bitacoras import reglas as reglas_bitacoras
from Calificaciones import boletas
from Calificaciones.models import ActaCalificaciones
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    crear_alumno,
    crear_grado,
    crear_grupo,
    crear_profesor,
    crear_usuario,
    grupo_de,
    hoy,
    inscribir,
    lunes,
)
from Usuarios.models import Rol

from . import bloques

D = Decimal


def materia(clave, grado=None):
    return Materia.objects.create(clave=clave, nombre=clave.title(), grado=grado)


def clase_base(grupo, ciclo, nombre, dia=0, inicio=(9, 0), fin=(10, 0), profesor=None):
    asignacion = MateriaGrado.objects.create(ciclo=ciclo, grado=grupo.grado, grupo=grupo, materia=nombre, profesor=profesor)
    HorarioMateria.objects.create(materia_grado=asignacion, dia_semana=dia, hora_inicio=time(*inicio), hora_fin=time(*fin))
    return asignacion


class BaseBloquesTestCase(BaseTestCase):
    """1.º A y 1.º B de secundaria con tres estudiantes cada uno, Inglés y Matemáticas en su plan (Inglés el lunes a las 9,
    Matemáticas a las 8) y tres docentes de Inglés."""

    def setUp(self):
        super().setUp()
        ConfiguracionAsistencia.cargar()
        self.ciclo = ciclo_actual_de_prueba()
        self.grado = crear_grado('SECUNDARIA', 1)
        self.a, self.b = grupo_de(self.grado), crear_grupo(self.grado, 'B')
        self.ingles, self.mate = materia('INGLES', self.grado), materia('MATE', self.grado)
        self.ingles_a = clase_base(self.a, self.ciclo, self.ingles)
        self.ingles_b = clase_base(self.b, self.ciclo, self.ingles)
        self.mate_a = clase_base(self.a, self.ciclo, self.mate, inicio=(8, 0), fin=(9, 0))
        self.mate_b = clase_base(self.b, self.ciclo, self.mate, inicio=(8, 0), fin=(9, 0))
        self.estudiantes_a = [inscribir(crear_alumno(nombre=n, apellido_paterno='Aa'), self.ciclo, self.grado, grupo=self.a, fecha_inscripcion=self.ciclo.fecha_inicio) for n in ('Ana', 'Beto', 'Ceci')]
        self.estudiantes_b = [inscribir(crear_alumno(nombre=n, apellido_paterno='Bb'), self.ciclo, self.grado, grupo=self.b, fecha_inscripcion=self.ciclo.fecha_inicio) for n in ('Dani', 'Eva', 'Fer')]
        self.todos = self.estudiantes_a + self.estudiantes_b
        self.docentes = [crear_usuario(n, Rol.objects.get(grupo__name='Docente')) for n in ('dora', 'elsa', 'fabi')]
        self.profesores = [crear_profesor(usuario=u, nombre=u.username.title()) for u in self.docentes]

    def bloque(self, nombre='Inglés por dominio', grupos=None, horarios=((0, (9, 0), (10, 0), ''),), sustituye=(), **cambios):
        datos = {'nivel': 'SECUNDARIA', 'ciclo': self.ciclo, 'vigente_desde': self.ciclo.fecha_inicio, 'vigente_hasta': self.ciclo.fecha_fin}
        datos.update(cambios)
        bloque = BloqueSimultaneo.objects.create(nombre=nombre, **datos)
        bloque.grupos_origen.set(grupos or [self.a, self.b])
        bloque.sustituye.set(sustituye)
        bloques.guardar_horarios(bloque, [(d, time(*i), time(*f), s) for d, i, f, s in horarios])
        return bloque

    def opcion(self, bloque, nombre, materia_=None, profesor=None, aula=''):
        return bloques.crear_opcion(bloque, {'nombre': nombre, 'materia': materia_ or self.ingles, 'profesor': profesor, 'aula': aula}, self.admin)

    def ingles_tres(self, sustituye=True):
        """El caso A: 1.º A y 1.º B repartidos en tres grupos de Inglés con docentes distintos, activo."""
        bloque = self.bloque(sustituye=[self.ingles_a, self.ingles_b] if sustituye else [])
        opciones = [self.opcion(bloque, n, profesor=p) for n, p in zip(('Básico', 'Intermedio', 'Avanzado'), self.profesores)]
        reparto = [self.todos[:2], self.todos[2:4], self.todos[4:]]
        for clase, estudiantes in zip(opciones, reparto):
            bloques.asignar(bloque, clase, estudiantes, None, self.admin)
        return bloque, opciones, reparto

    def cerrar_acta(self, asignacion, periodo, finales):
        return ActaCalificaciones.objects.create(
            asignacion=asignacion, periodo=periodo, estado=ActaCalificaciones.CERRADA, cerrada_en=timezone.now(),
            resultados_cerrados=[{'inscripcion': i.pk, 'final': f'{v:.2f}', 'faltas': 1} for i, v in finales.items()],
        )

    def periodo(self, nombre='Bimestre 1', dias=(-50, -20)):
        return Periodo.objects.create(ciclo=self.ciclo, nivel='SECUNDARIA', nombre=nombre, fecha_inicio=hoy() + timedelta(days=dias[0]), fecha_fin=hoy() + timedelta(days=dias[1]))


@PRUEBAS
class CasoAMismaMateriaTests(BaseBloquesTestCase):
    def test_tres_grupos_de_ingles_con_docentes_distintos(self):
        bloque, opciones, reparto = self.ingles_tres()
        self.assertEqual(bloques.problemas_para_activar(bloque), [])
        bloques.activar(bloque, self.admin)
        # Los tres se imparten a la misma hora, cada uno con su horario y su docente
        horas = {(h.dia_semana, h.hora_inicio) for o in opciones for h in o.asignacion.horarios.all()}
        self.assertEqual(horas, {(0, time(9, 0))})
        # Cada docente ve solo a sus estudiantes
        for clase, profesor, estudiantes in zip(opciones, self.profesores, reparto):
            self.assertEqual(list(asignaciones_del_profesor(profesor, self.ciclo)), [clase.asignacion])
            self.assertEqual(set(inscripciones_de(clase.asignacion, desde=lunes())), set(estudiantes))

    def test_las_calificaciones_se_integran_a_una_sola_materia(self):
        bloque, opciones, reparto = self.ingles_tres()
        bloques.activar(bloque, self.admin)
        estudiante = reparto[0][0]
        p1, p2 = self.periodo(), self.periodo('Bimestre 2', (-19, 5))
        self.cerrar_acta(opciones[0].asignacion, p1, {estudiante: 7})
        self.cerrar_acta(opciones[1].asignacion, p2, {estudiante: 9})
        # Cambió de grupo de Inglés a mitad del ciclo: sigue siendo una sola materia en la boleta
        bloques.asignar(bloque, opciones[1], [estudiante], hoy() - timedelta(days=19), self.admin)
        filas = [m for m in boletas.boleta(estudiante.alumno, self.ciclo).bloques[0].materias]
        self.assertEqual([m.nombre for m in filas].count('Ingles'), 1)
        fila = next(m for m in filas if m.nombre == 'Ingles')
        self.assertEqual([c for c, _ in fila.periodos], [D('7.00'), D('9.00')])
        self.assertEqual(fila.promedio, D('8.00'))
        self.assertEqual(fila.profesor, self.profesores[1].nombre_completo)   # con quien la cursa ahora


@PRUEBAS
class CasoBMateriasDiferentesTests(BaseBloquesTestCase):
    def talleres(self):
        bloque = self.bloque('Talleres', sustituye=[self.ingles_a, self.ingles_b])
        materias = [materia(c, self.grado) for c in ('ROBOTICA', 'PROGRAMACION', 'DISENO')]
        opciones = [self.opcion(bloque, m.nombre, m, p, aula=f'Lab {n}') for n, (m, p) in enumerate(zip(materias, self.profesores))]
        for clase, estudiantes in zip(opciones, (self.todos[:2], self.todos[2:4], self.todos[4:])):
            bloques.asignar(bloque, clase, estudiantes, None, self.admin)
        bloques.activar(bloque, self.admin)
        return bloque, opciones

    def test_tres_materias_a_la_misma_hora_sin_conflicto(self):
        bloque, _ = self.talleres()
        self.assertEqual(bloques.conflictos(bloque), [])
        self.assertTrue(BloqueSimultaneo.objects.get(pk=bloque.pk).activo)

    def test_cada_estudiante_ve_y_recibe_registros_solo_de_su_opcion(self):
        _, opciones = self.talleres()
        ana, dani = self.todos[0], self.todos[3]
        materias = {b.materia_grado.materia.clave for b in clases.bloques_del_estudiante(ana, lunes())}
        self.assertEqual(materias, {'ROBOTICA', 'MATE'})   # sin Inglés del grupo base ni los otros talleres
        self.assertEqual({c.asignacion.materia.clave for c in clases_del_estudiante(ana, lunes())}, {'ROBOTICA', 'MATE'})
        cerrar_dia(lunes())
        registros = set(AsistenciaMateria.objects.filter(inscripcion=ana, fecha=lunes()).values_list('materia_grado__materia__clave', flat=True))
        self.assertEqual(registros, {'ROBOTICA', 'MATE'})   # sin asistencia duplicada en la clase del grupo base
        self.assertFalse(AsistenciaMateria.objects.filter(inscripcion=ana, materia_grado=self.ingles_a).exists())
        self.assertTrue(AsistenciaMateria.objects.filter(inscripcion=dani, materia_grado=opciones[1].asignacion).exists())

    def test_la_boleta_lleva_la_materia_que_cursa(self):
        _, opciones = self.talleres()
        ana = self.todos[0]
        self.cerrar_acta(opciones[0].asignacion, self.periodo(), {ana: 9})
        nombres = [m.nombre for m in boletas.boleta(ana.alumno, self.ciclo).bloques[0].materias]
        self.assertIn('Robotica', nombres)
        self.assertNotIn('Programacion', nombres)
        self.assertNotIn('Ingles', nombres)   # se sustituyó antes de calificarla


@PRUEBAS
class CasoCRestriccionesTests(BaseBloquesTestCase):
    def test_rechaza_a_estudiantes_de_otro_nivel(self):
        bloque = self.bloque()
        clase = self.opcion(bloque, 'Básico')
        primaria = crear_grado('PRIMARIA', 3)
        ajeno = inscribir(crear_alumno(nombre='Otro'), self.ciclo, primaria)
        with self.assertRaises(bloques.BloqueRechazado) as error:
            bloques.asignar(bloque, clase, [self.todos[0], ajeno], None, self.admin)
        self.assertIn('Primaria', error.exception.mensaje)
        self.assertFalse(IntegranteClase.objects.exists())   # todo o nada

    def test_rechaza_doble_asignacion_de_docente_aula_y_estudiante(self):
        bloque = self.bloque(sustituye=[self.ingles_a, self.ingles_b])
        uno = self.opcion(bloque, 'Básico', profesor=self.profesores[0], aula='Sala 1')
        dos = self.opcion(bloque, 'Intermedio', profesor=self.profesores[0], aula='sala  1')
        bloques.asignar(bloque, uno, self.todos[:3], None, self.admin)
        bloques.asignar(bloque, dos, self.todos[3:], None, self.admin)
        textos = bloques.conflictos(bloque)
        self.assertEqual({c.tipo for c in textos}, {bloques.DOCENTE, bloques.AULA})
        with self.assertRaises(bloques.BloqueRechazado):
            bloques.activar(bloque, self.admin)
        # El mismo estudiante en otro bloque a la misma hora
        bloques.editar_opcion(dos, {'nombre': 'Intermedio', 'materia': self.ingles, 'profesor': self.profesores[1], 'aula': 'Sala 2'}, self.admin)
        bloques.activar(bloque, self.admin)
        otro = self.bloque('Talleres')
        taller = self.opcion(otro, 'Robótica', materia('ROBOTICA', self.grado), self.profesores[2])
        with self.assertRaises(bloques.BloqueRechazado) as error:
            bloques.asignar(otro, taller, [self.todos[0]], None, self.admin)
        self.assertIn('ya tiene', error.exception.mensaje)

    def test_docente_ocupado_en_el_horario_tradicional(self):
        self.ingles_a.profesor = self.profesores[0]
        self.ingles_a.save()
        bloque = self.bloque(sustituye=[self.ingles_b])
        self.opcion(bloque, 'Básico', profesor=self.profesores[0])
        self.assertTrue(any(c.tipo == bloques.DOCENTE for c in bloques.conflictos(bloque)))

    def test_clase_base_sin_sustituir_es_conflicto_de_estudiantes(self):
        bloque = self.bloque()   # a la hora de Inglés, sin sustituirla
        self.assertTrue(any(c.tipo == bloques.ESTUDIANTE and 'Ingles' in c.texto for c in bloques.conflictos(bloque)))

    def test_otros_bloques_compatibles_se_permiten(self):
        bloque, _, _ = self.ingles_tres()
        bloques.activar(bloque, self.admin)
        otro = self.bloque('Deportes', horarios=((2, (12, 0), (13, 0), ''),))
        clase = self.opcion(otro, 'Fútbol', materia('FUTBOL', self.grado), self.profesores[0])
        self.assertEqual(bloques.asignar(otro, clase, self.todos, None, self.admin), 6)

    def test_cambio_con_fecha_efectiva_conserva_lo_anterior(self):
        bloque, opciones, reparto = self.ingles_tres()
        bloques.activar(bloque, self.admin)
        ana = reparto[0][0]
        efectiva = lunes()
        anterior = efectiva - timedelta(days=7)
        AsistenciaMateria.objects.create(inscripcion=ana, materia_grado=opciones[0].asignacion, fecha=anterior, estado='FALTA')
        bloques.asignar(bloque, opciones[1], [ana], efectiva, self.admin)
        # Lo anterior queda donde estaba
        self.assertTrue(AsistenciaMateria.objects.filter(inscripcion=ana, materia_grado=opciones[0].asignacion, fecha=anterior).exists())
        pasos = list(IntegranteClase.objects.filter(inscripcion=ana).order_by('desde'))
        self.assertEqual([(p.clase, p.hasta) for p in pasos], [(opciones[0], efectiva - timedelta(days=1)), (opciones[1], None)])
        # Las listas de cada fecha reflejan la pertenencia de esa fecha
        self.assertIn(ana, inscripciones_de(opciones[0].asignacion, desde=anterior))
        self.assertNotIn(ana, inscripciones_de(opciones[0].asignacion, desde=efectiva))
        self.assertIn(ana, inscripciones_de(opciones[1].asignacion, desde=efectiva))
        self.assertNotIn(ana, inscripciones_de(opciones[1].asignacion, desde=anterior))
        # El docente anterior ya no captura esa fecha; lo pasado sigue a la vista
        self.assertTrue(clases.pertenece(ana, opciones[0].asignacion, anterior))
        self.assertFalse(clases.pertenece(ana, opciones[0].asignacion, efectiva))
        datos = matriz(opciones[0].asignacion, None, hoy=efectiva, desde=anterior, hasta=efectiva)
        fila = next(f for f in datos['filas'] if f['inscripcion'] == ana)
        self.assertEqual(fila['celdas'][-1].letra, '')   # ese día ya no estaba

    def test_semanas_a_y_b_no_chocan(self):
        ConfiguracionHorario.objects.create(ciclo=self.ciclo, nivel='SECUNDARIA', modalidad=ConfiguracionHorario.ALTERNADO, fecha_referencia=self.ciclo.fecha_inicio, semana_referencia='A')
        uno = self.bloque('Semana A', horarios=((3, (12, 0), (13, 0), 'A'),))
        dos = self.bloque('Semana B', horarios=((3, (12, 0), (13, 0), 'B'),))
        clase_uno = self.opcion(uno, 'Coro', materia('CORO', self.grado), self.profesores[0], aula='Música')
        clase_dos = self.opcion(dos, 'Banda', materia('BANDA', self.grado), self.profesores[0], aula='Música')
        bloques.asignar(uno, clase_uno, self.todos, None, self.admin)
        bloques.activar(uno, self.admin)
        self.assertEqual(bloques.asignar(dos, clase_dos, self.todos, None, self.admin), 6)
        self.assertEqual(bloques.conflictos(dos), [])

    def test_vigencias_que_no_se_tocan_no_chocan(self):
        mitad = hoy() + timedelta(days=30)
        uno = self.bloque('Primero', horarios=((3, (12, 0), (13, 0), ''),), vigente_hasta=mitad)
        dos = self.bloque('Después', horarios=((3, (12, 0), (13, 0), ''),), vigente_desde=mitad + timedelta(days=1))
        clase_uno = self.opcion(uno, 'Coro', materia('CORO', self.grado), self.profesores[0])
        clase_dos = self.opcion(dos, 'Banda', materia('BANDA', self.grado), self.profesores[0])
        bloques.asignar(uno, clase_uno, self.todos, None, self.admin)
        bloques.activar(uno, self.admin)
        self.assertEqual(bloques.asignar(dos, clase_dos, self.todos, None, self.admin), 6)
        self.assertEqual(bloques.conflictos(dos), [])

    def test_conservan_su_grupo_base(self):
        bloque, _, _ = self.ingles_tres()
        bloques.activar(bloque, self.admin)
        for inscripcion in self.todos:
            guardada = Inscripcion.objects.get(pk=inscripcion.pk)
            self.assertEqual((guardada.grupo_id, guardada.grado_id, guardada.activa), (inscripcion.grupo_id, inscripcion.grado_id, True))

    def test_las_materias_tradicionales_siguen_igual(self):
        bloque, opciones, _ = self.ingles_tres()
        bloques.activar(bloque, self.admin)
        # Matemáticas no se toca
        self.assertEqual(set(inscripciones_de(self.mate_a, desde=lunes())), set(self.estudiantes_a))
        # Sin el grupo técnico en listas de grupos ni en el plan
        self.assertEqual(set(Grupo.objects.filter(grado=self.grado)), {self.a, self.b})
        self.assertEqual(MateriaGrado.objects.de_plan().filter(ciclo=self.ciclo).count(), 4)
        otra = materia('ROBOTICA', self.grado)
        self.assertIn(otra, materias_por_asignar(self.grado, self.ciclo))
        # Un grupo que no participa no cambia
        c = crear_grupo(self.grado, 'C')
        solo = inscribir(crear_alumno(nombre='Sola'), self.ciclo, self.grado, grupo=c, fecha_inscripcion=self.ciclo.fecha_inicio)
        mate_c = clase_base(c, self.ciclo, self.mate, inicio=(8, 0), fin=(9, 0))
        self.assertEqual(list(inscripciones_de(mate_c, desde=lunes())), [solo])
        self.assertEqual([x.asignacion for x in clases_del_estudiante(solo, lunes())], [mate_c])


@PRUEBAS
class PoblacionYActivacionTests(BaseBloquesTestCase):
    def test_en_preparacion_no_afecta_nada(self):
        bloque, opciones, _ = self.ingles_tres()
        self.assertFalse(HorarioMateria.objects.filter(materia_grado=opciones[0].asignacion).exists())
        self.assertEqual({c.asignacion.materia.clave for c in clases_del_estudiante(self.todos[0], lunes())}, {'INGLES', 'MATE'})
        self.assertEqual(list(asignaciones_del_profesor(self.profesores[0], self.ciclo))[0].clase, opciones[0])   # ya la ve, sin alumnos
        self.assertEqual(list(inscripciones_de(opciones[0].asignacion, desde=lunes())), [])

    def test_no_se_activa_con_pendientes(self):
        bloque = self.bloque(sustituye=[self.ingles_a, self.ingles_b])
        clase = self.opcion(bloque, 'Básico', profesor=self.profesores[0])
        bloques.asignar(bloque, clase, self.todos[:5], None, self.admin)
        problemas = bloques.problemas_para_activar(bloque)
        self.assertTrue(any('sin opción' in p for p in problemas))
        with self.assertRaises(bloques.BloqueRechazado):
            bloques.activar(bloque, self.admin)

    def test_poblacion_delimitada(self):
        bloque = self.bloque(poblacion_delimitada=True, sustituye=[self.ingles_a, self.ingles_b])
        clase = self.opcion(bloque, 'Avanzado', profesor=self.profesores[0])
        bloques.delimitar(bloque, self.todos[:2], True, self.admin)
        with self.assertRaises(bloques.BloqueRechazado):
            bloques.asignar(bloque, clase, [self.todos[3]], None, self.admin)   # no participa
        bloques.asignar(bloque, clase, self.todos[:2], None, self.admin)
        self.assertEqual(bloques.problemas_para_activar(bloque), [])
        bloques.activar(bloque, self.admin)
        # Quien participa sale de la clase sustituida; quien no, sigue en ella
        self.assertNotIn(self.todos[0], inscripciones_de(self.ingles_a, desde=lunes()))
        self.assertIn(self.todos[2], inscripciones_de(self.ingles_a, desde=lunes()))

    def test_mezclar_grados_exige_correspondencia_con_el_plan(self):
        segundo = crear_grado('SECUNDARIA', 2)
        grupo = grupo_de(segundo)
        ingles2 = materia('INGLES2', segundo)
        mayor = inscribir(crear_alumno(nombre='Gil'), self.ciclo, segundo, grupo=grupo, fecha_inscripcion=self.ciclo.fecha_inicio)
        bloque = self.bloque(grupos=[self.a, grupo], mezclar_grados=True, horarios=((3, (12, 0), (13, 0), ''),))
        clase = self.opcion(bloque, 'Básico', self.ingles, self.profesores[0])
        with self.assertRaises(bloques.BloqueRechazado) as error:
            bloques.asignar(bloque, clase, [mayor], None, self.admin)
        self.assertIn('plan', error.exception.mensaje)
        bloques.editar_opcion(clase, {'nombre': 'Básico', 'materia': self.ingles, 'profesor': self.profesores[0], 'aula': '', 'equivalencias': {segundo: ingles2}}, self.admin)
        bloques.asignar(bloque, clase, [*self.estudiantes_a, mayor], None, self.admin)
        bloques.activar(bloque, self.admin)
        self.cerrar_acta(clase.asignacion, self.periodo(), {mayor: 8})
        nombres = [m.nombre for m in boletas.boleta(mayor.alumno, self.ciclo).bloques[0].materias]
        self.assertEqual(nombres, ['Ingles2'])   # la materia de su plan

    def test_desactivar_conserva_y_reactivar_sigue(self):
        bloque, opciones, reparto = self.ingles_tres()
        bloques.activar(bloque, self.admin)
        ana = reparto[0][0]
        AsistenciaMateria.objects.create(inscripcion=ana, materia_grado=opciones[0].asignacion, fecha=lunes() - timedelta(days=7), estado='PRESENTE')
        bloques.desactivar(bloque, lunes(), self.admin)
        self.assertEqual({c.asignacion.materia.clave for c in clases_del_estudiante(ana, lunes())}, {'INGLES', 'MATE'})   # vuelve a su clase base
        self.assertTrue(clases.pertenece(ana, opciones[0].asignacion, lunes() - timedelta(days=7)))   # la historia sigue
        self.assertEqual(AsistenciaMateria.objects.filter(materia_grado=opciones[0].asignacion).count(), 1)
        bloques.activar(bloque, self.admin)
        self.assertTrue(clases.pertenece(ana, opciones[0].asignacion, hoy()))

    def test_bloque_de_otro_grado_mezclado_sin_permiso_se_rechaza_en_el_formulario(self):
        from .forms_bloques import BloqueForm
        segundo = crear_grado('SECUNDARIA', 2)
        datos = {'nombre': 'Mixto', 'nivel': 'SECUNDARIA', 'ciclo': self.ciclo.pk, 'vigente_desde': self.ciclo.fecha_inicio, 'vigente_hasta': self.ciclo.fecha_fin,
                 'grupos_origen': [self.a.pk, grupo_de(segundo).pk]}
        form = BloqueForm(datos)
        self.assertFalse(form.is_valid())
        self.assertIn('distintos grados', str(form.errors))
        form = BloqueForm({**datos, 'mezclar_grados': 'on'})
        self.assertTrue(form.is_valid(), form.errors)
        primaria = crear_grado('PRIMARIA', 1)
        self.assertIn('no mezcla niveles', str(BloqueForm({**datos, 'mezclar_grados': 'on', 'grupos_origen': [self.a.pk, grupo_de(primaria).pk]}).errors))


@PRUEBAS
class IntegracionTests(BaseBloquesTestCase):
    def test_el_docente_pasa_lista_solo_a_los_suyos(self):
        bloque, opciones, reparto = self.ingles_tres()
        bloques.activar(bloque, self.admin)
        datos = matriz(opciones[0].asignacion, self.docentes[0], hoy=lunes(), desde=lunes(), hasta=lunes())
        self.assertEqual({f['inscripcion'] for f in datos['filas']}, set(reparto[0]))
        guardar_cambio(opciones[0].asignacion, reparto[0][0], lunes(), 'PRESENTE', '', self.admin)
        from Alumnos.asistencia_docente import CambioRechazado
        with self.assertRaises(CambioRechazado):
            guardar_cambio(opciones[0].asignacion, reparto[1][0], lunes(), 'PRESENTE', '', self.admin)   # es de otra opción

    def test_el_acta_es_de_los_integrantes_del_periodo(self):
        from Calificaciones import reglas
        bloque, opciones, reparto = self.ingles_tres()
        bloques.activar(bloque, self.admin)
        acta = reglas.acta_para(opciones[0].asignacion, self.periodo())
        self.assertEqual(set(reglas.estudiantes_de(acta)), set(reparto[0]))

    def test_quien_salio_a_mitad_del_periodo_no_impide_cerrar(self):
        from Calificaciones import reglas
        bloque, opciones, reparto = self.ingles_tres()
        bloques.activar(bloque, self.admin)
        periodo = self.periodo(dias=(-30, 10))
        ana = reparto[0][0]
        bloques.asignar(bloque, opciones[1], [ana], lunes(), self.admin)
        acta = reglas.acta_para(opciones[0].asignacion, periodo)
        fila = next(f for f in reglas.tabla(acta).filas if f.inscripcion == ana)
        self.assertEqual(fila.salio, lunes() - timedelta(days=1))

    def test_bitacora_con_la_lista_real(self):
        bloque, opciones, reparto = self.ingles_tres()
        bloques.activar(bloque, self.admin)
        grupo = opciones[0].asignacion.grupo
        self.assertEqual(set(reglas_bitacoras.inscripciones_del_grupo(grupo, self.ciclo)), set(reparto[0]))
        self.assertEqual(set(reglas_bitacoras.alumnos_elegibles(grupo, self.ciclo)), {i.alumno for i in reparto[0]})

    def test_expediente_y_horario_del_grupo_base(self):
        bloque, opciones, reparto = self.ingles_tres()
        bloques.activar(bloque, self.admin)
        self.assertContains(self.client.get(reverse('alumnos:detalle', args=[reparto[0][0].alumno.pk])), 'Grupos de clase')
        respuesta = self.client.get(reverse('horarios:grupo', args=[self.a.pk]))
        self.assertContains(respuesta, 'Se distribuyen en')
        self.assertContains(respuesta, 'Sustituida por')

    def test_una_clase_tradicional_no_se_programa_encima_de_un_bloque_activo(self):
        from Horarios.forms import HorarioCrearForm
        bloque, _, _ = self.ingles_tres()
        bloques.activar(bloque, self.admin)
        form = HorarioCrearForm({'materia_grado': self.mate_a.pk, 'dias': ['0'], 'inicio_0': '09:00', 'fin_0': '10:00'}, grupo=self.a, ciclo=self.ciclo)
        self.assertFalse(form.is_valid())
        self.assertIn('bloque', str(form.errors))

    def test_no_se_copia_al_ciclo_siguiente(self):
        from Materias.views import _plan_de_copia
        from CISAHUAYO.pruebas import ciclo_proximo_de_prueba
        bloque, _, _ = self.ingles_tres()
        destino = ciclo_proximo_de_prueba()
        por_copiar = [a for fila in _plan_de_copia(self.ciclo, destino) for a in fila['por_copiar']]
        self.assertEqual({a.materia.clave for a in por_copiar}, {'INGLES', 'MATE'})
        self.assertEqual({a.grupo for a in por_copiar}, {self.a, self.b})   # solo el plan de los grupos base

    def test_pantallas_y_permisos(self):
        bloque, opciones, _ = self.ingles_tres()
        paginas = [reverse('asignaciones:bloques'), reverse('asignaciones:bloque_crear'), bloque.get_absolute_url(), reverse('asignaciones:bloque_distribuir', args=[bloque.pk]),
                   reverse('asignaciones:bloque_editar', args=[bloque.pk]), reverse('asignaciones:bloque_horarios', args=[bloque.pk]),
                   reverse('asignaciones:bloque_sustituye', args=[bloque.pk]), reverse('asignaciones:opcion_crear', args=[bloque.pk]),
                   reverse('asignaciones:opcion_editar', args=[opciones[0].pk])]
        for url in paginas:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.client.force_login(self.docentes[0])
        for url in paginas:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.con_permisos('view_bloquesimultaneo')
        self.assertEqual(self.client.get(bloque.get_absolute_url()).status_code, 200)
        self.assertEqual(self.client.post(reverse('asignaciones:bloque_activar', args=[bloque.pk])).status_code, 403)

    def test_distribuir_desde_la_pantalla(self):
        bloque = self.bloque(sustituye=[self.ingles_a, self.ingles_b])
        clase = self.opcion(bloque, 'Básico', profesor=self.profesores[0])
        url = reverse('asignaciones:bloque_distribuir', args=[bloque.pk])
        self.client.post(url, {'accion': 'asignar', 'opcion': clase.pk, 'inscripcion': [i.pk for i in self.todos]})
        self.assertEqual(IntegranteClase.objects.filter(clase=clase).count(), 6)
        pendientes = self.client.get(url, {'opcion': 'pendientes'})
        self.assertEqual(pendientes.context['filas'], [])
        self.client.post(reverse('asignaciones:bloque_activar', args=[bloque.pk]))
        self.assertTrue(BloqueSimultaneo.objects.get(pk=bloque.pk).activo)

    def test_opcion_con_registros_no_cambia_de_materia(self):
        bloque, opciones, reparto = self.ingles_tres()
        bloques.activar(bloque, self.admin)
        AsistenciaMateria.objects.create(inscripcion=reparto[0][0], materia_grado=opciones[0].asignacion, fecha=lunes(), estado='PRESENTE')
        with self.assertRaises(bloques.BloqueRechazado):
            bloques.editar_opcion(opciones[0], {'nombre': 'Básico', 'materia': self.mate, 'profesor': self.profesores[0], 'aula': ''}, self.admin)


@PRUEBAS
class BachilleratoPorSemestresTests(BaseTestCase):
    """Un bloque de bachillerato dentro de un semestre: sus clases entran a la hoja semestral, a la boleta y al cierre."""

    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.primero = crear_grado('PREPARATORIA', 1)
        self.a, self.b = grupo_de(self.primero), crear_grupo(self.primero, 'B')
        self.sem_a = Semestre.objects.create(ciclo=self.ciclo, clave='A', fecha_inicio=self.ciclo.fecha_inicio, fecha_fin=hoy() + timedelta(days=60), estado=Semestre.ABIERTO)
        self.parcial = Periodo.objects.create(ciclo=self.ciclo, nivel='PREPARATORIA', nombre='Parcial 1', fecha_inicio=self.ciclo.fecha_inicio, fecha_fin=hoy() + timedelta(days=10), semestre=self.sem_a)
        self.ingles = materia('INGLES', self.primero)
        self.ana = inscribir(crear_alumno(nombre='Ana'), self.ciclo, self.primero, grupo=self.a, fecha_inscripcion=self.ciclo.fecha_inicio)
        self.beto = inscribir(crear_alumno(nombre='Beto'), self.ciclo, self.primero, grupo=self.b, fecha_inscripcion=self.ciclo.fecha_inicio)
        self.bloque = BloqueSimultaneo.objects.create(nombre='Inglés', nivel='PREPARATORIA', ciclo=self.ciclo, semestre=self.sem_a,
                                                      vigente_desde=self.sem_a.fecha_inicio, vigente_hasta=self.sem_a.fecha_fin)
        self.bloque.grupos_origen.set([self.a, self.b])
        bloques.guardar_horarios(self.bloque, [(0, time(9, 0), time(10, 0), '')])
        profesor = crear_profesor(telefono='3531234567')
        self.basico = bloques.crear_opcion(self.bloque, {'nombre': 'Básico', 'materia': self.ingles, 'profesor': profesor, 'aula': ''}, self.admin)
        bloques.asignar(self.bloque, self.basico, [self.ana, self.beto], None, self.admin)
        bloques.activar(self.bloque, self.admin)

    def test_la_hoja_semestral_es_de_los_integrantes(self):
        from Calificaciones import semestres
        ActaCalificaciones.objects.create(asignacion=self.basico.asignacion, periodo=self.parcial, estado=ActaCalificaciones.CERRADA, cerrada_en=timezone.now(),
                                          resultados_cerrados=[{'inscripcion': i.pk, 'final': '9.60', 'faltas': 0} for i in (self.ana, self.beto)])
        hoja = semestres.hoja(self.basico.asignacion, self.sem_a)
        self.assertEqual({f.inscripcion for f in hoja.filas}, {self.ana, self.beto})
        self.assertEqual(hoja.filas[0].resultado.estado, 'APROBADA_EXENTO')
        semestres.cerrar(self.sem_a, self.admin)
        fila = boletas.boleta(self.ana.alumno, self.ciclo).bloques[0].materias[0]
        self.assertEqual((fila.nombre, fila.semestral['definitiva']), ('Ingles', '9.60'))

    def test_con_el_semestre_cerrado_el_bloque_no_cambia(self):
        Semestre.objects.filter(pk=self.sem_a.pk).update(estado=Semestre.CERRADO)
        self.bloque.refresh_from_db()
        with self.assertRaises(bloques.BloqueRechazado):
            bloques.asignar(self.bloque, self.basico, [self.ana], None, self.admin)


class TramosTests(SimpleTestCase):
    def test_unir_tramos_contiguos(self):
        from datetime import date
        a, b, c = date(2026, 1, 1), date(2026, 1, 10), date(2026, 1, 11)
        self.assertEqual(clases._unir([(c, date(2026, 1, 20)), (a, b)]), [(a, date(2026, 1, 20))])


