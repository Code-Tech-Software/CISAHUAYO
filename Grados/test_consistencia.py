"""Pruebas de los cambios del 2026-10-26 en Grados: la baja con estudiantes inscritos, el nivel y el número fijos con
historial, el guardado en una transacción, las materias de los grupos quitados, el listado por ciclo con lo que falta,
el plan por grupo, las bajas y el resumen por grupo, la exportación, la equivalencia única, el admin y el alta de un
nivel completo."""
import csv
import io
from unittest import mock

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from Alumnos.asistencia_docente import asignaciones_del_profesor
from Alumnos.models import Grado, Grupo, MateriaGrado, NombreGrupo
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    ciclo_cerrado_de_prueba,
    ciclo_proximo_de_prueba,
    crear_alumno,
    crear_grado,
    crear_grupo,
    crear_profesor,
    crear_tutor,
    grupo_de,
    inscribir,
    materia_en_grado,
    vincular,
)

from .forms import GradoForm


# ---------------------------------------------------------------------------
# Baja del grado
# ---------------------------------------------------------------------------
@PRUEBAS
class BajaConInscritosTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.grado = crear_grado('PRIMARIA', 1)

    def test_no_se_da_de_baja_con_estudiantes_en_el_ciclo_actual_o_en_uno_proximo(self):
        for ciclo in (self.ciclo, ciclo_proximo_de_prueba()):
            inscripcion = inscribir(crear_alumno(), ciclo, self.grado)
            respuesta = self.client.post(reverse('grados:baja', args=[self.grado.pk]), follow=True)
            self.assertContains(respuesta, 'No se puede dar de baja 1.º Primaria. Tiene 1 estudiante inscrito')
            self.grado.refresh_from_db()
            self.assertTrue(self.grado.activo)
            inscripcion.delete()

    def test_el_listado_explica_por_que_no(self):
        inscribir(crear_alumno(), self.ciclo, self.grado)
        html = self.client.get(reverse('grados:lista')).content.decode()
        self.assertIn('data-bloqueo="Tiene 1 estudiante inscrito en el ciclo actual', html)
        self.assertIn('data-baja-enviar', html)

    def test_la_baja_suspende_su_plan_y_la_reactivacion_lo_devuelve(self):
        profesor = crear_profesor()
        asignacion = materia_en_grado('MAT', self.grado, self.ciclo, profesor=profesor)
        cerrada = materia_en_grado('MAT', self.grado, ciclo_cerrado_de_prueba())
        self.client.post(reverse('grados:baja', args=[self.grado.pk]))
        asignacion.refresh_from_db()
        cerrada.refresh_from_db()
        self.assertEqual((asignacion.activa, asignacion.suspendida), (False, True))
        self.assertEqual((cerrada.activa, cerrada.suspendida), (True, False))   # lo de un ciclo cerrado no se toca
        self.assertNotIn(asignacion, asignaciones_del_profesor(profesor, self.ciclo))
        self.client.post(reverse('grados:reactivar', args=[self.grado.pk]))
        asignacion.refresh_from_db()
        self.assertEqual((asignacion.activa, asignacion.suspendida, asignacion.profesor), (True, False, profesor))
        self.assertEqual(asignacion.horarios.count(), 1)

    def test_desde_el_detalle_vuelve_al_detalle(self):
        detalle = self.grado.get_absolute_url()
        respuesta = self.client.post(reverse('grados:baja', args=[self.grado.pk]), {'next': detalle}, follow=True)
        self.assertRedirects(respuesta, detalle)
        self.assertContains(respuesta, 'fue dado de baja')
        respuesta = self.client.post(reverse('grados:reactivar', args=[self.grado.pk]), {'next': detalle}, follow=True)
        self.assertRedirects(respuesta, detalle)
        self.assertContains(respuesta, f'<input type="hidden" name="next" value="{detalle}">', html=True)
        # Una dirección de otro sitio no se sigue
        respuesta = self.client.post(reverse('grados:baja', args=[self.grado.pk]), {'next': 'https://otro.example/'})
        self.assertRedirects(respuesta, reverse('grados:lista'), fetch_redirect_response=False)


# ---------------------------------------------------------------------------
# Nivel y número fijos con historial; el guardado es una sola operación
# ---------------------------------------------------------------------------
@PRUEBAS
class NivelFijoTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.grado = crear_grado('PRIMARIA', 1)

    def editar(self, **cambios):
        datos = {'nivel': 'PRIMARIA', 'numero': 1, 'equivalencia': '1', 'grupos': [grupo_de(self.grado).nombre_id]}
        datos.update(cambios)
        return self.client.post(reverse('grados:editar', args=[self.grado.pk]), datos)

    def test_vacio_se_puede_corregir(self):
        self.assertEqual(self.editar(nivel='SECUNDARIA', equivalencia='').status_code, 302)
        self.grado.refresh_from_db()
        self.assertEqual((self.grado.nivel, self.grado.equivalencia), ('SECUNDARIA', '7'))

    def test_con_inscripciones_o_plan_no_cambian(self):
        for historial in ('inscripcion', 'plan'):
            with self.subTest(historial):
                if historial == 'inscripcion':
                    registro = inscribir(crear_alumno(), ciclo_cerrado_de_prueba(), self.grado)
                else:
                    registro = materia_en_grado('MAT', self.grado, self.ciclo)
                form = self.client.get(reverse('grados:editar', args=[self.grado.pk])).context['form']
                self.assertTrue(form.fields['nivel'].disabled and form.fields['numero'].disabled)
                self.assertEqual(self.editar(nivel='SECUNDARIA', numero=2).status_code, 302)   # lo bloqueado se ignora
                self.grado.refresh_from_db()
                self.assertEqual((self.grado.nivel, self.grado.numero), ('PRIMARIA', 1))
                registro.delete() if historial == 'inscripcion' else MateriaGrado.objects.all().delete()

    def test_el_modelo_tambien_lo_rechaza(self):
        materia_en_grado('MAT', self.grado, self.ciclo)
        self.grado.nivel = 'SECUNDARIA'
        with self.assertRaisesMessage(ValidationError, 'El nivel y el número ya no se pueden cambiar'):
            self.grado.full_clean()

    def test_el_grado_y_sus_grupos_se_guardan_juntos(self):
        with mock.patch('Grados.forms.extender_plan_al_grupo', side_effect=RuntimeError('falla')):
            with self.assertRaises(RuntimeError):
                self.client.post(reverse('grados:crear'), {'nivel': 'PRIMARIA', 'numero': 2, 'grupos': [NombreGrupo.inicial().pk]})
        self.assertFalse(Grado.objects.filter(nivel='PRIMARIA', numero=2).exists())   # nada a medias


# ---------------------------------------------------------------------------
# Quitar un grupo desactiva sus materias de los ciclos vigentes
# ---------------------------------------------------------------------------
@PRUEBAS
class GrupoQuitadoTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.grado = crear_grado('PRIMARIA', 1)
        self.a = grupo_de(self.grado)
        self.b = crear_grupo(self.grado, 'B')
        self.profesor = crear_profesor()
        self.de_b = materia_en_grado('MAT', self.grado, self.ciclo, grupo=self.b, profesor=self.profesor)
        materia_en_grado('MAT', self.grado, self.ciclo, grupo=self.a)

    def grupos(self, *grupos):
        return self.client.post(reverse('grados:editar', args=[self.grado.pk]), {
            'nivel': 'PRIMARIA', 'numero': 1, 'equivalencia': '1', 'grupos': [g.nombre_id for g in grupos],
        }, follow=True)

    def test_sus_materias_se_suspenden_y_vuelven_con_el_grupo(self):
        respuesta = self.grupos(self.a)
        self.assertContains(respuesta, 'Se dio de baja el grupo B y 1 materia suya del ciclo actual o de los próximos.')
        self.de_b.refresh_from_db()
        self.assertEqual((self.de_b.activa, self.de_b.suspendida), (False, True))
        self.assertNotIn(self.de_b, asignaciones_del_profesor(self.profesor, self.ciclo))   # ya no cuenta en su carga
        self.grupos(self.a, self.b)
        self.de_b.refresh_from_db()
        self.assertEqual((self.de_b.activa, self.de_b.suspendida, self.de_b.profesor), (True, False, self.profesor))

    def test_si_la_materia_se_quito_del_grado_no_vuelve(self):
        self.grupos(self.a)
        del_a = MateriaGrado.objects.get(grupo=self.a)
        self.client.post(reverse('materias:quitar', args=[del_a.pk]))
        self.grupos(self.a, self.b)
        self.de_b.refresh_from_db()
        self.assertFalse(self.de_b.activa)

    def test_el_plan_con_varios_grupos_es_una_tabla_de_materias_por_grupo(self):
        materia_en_grado('ESP', self.grado, self.ciclo, grupo=self.a, inicio=None)
        respuesta = self.client.get(self.grado.get_absolute_url())
        matriz = respuesta.context['matriz']
        self.assertEqual([c.corto for c in respuesta.context['columnas']], ['1.º A', '1.º B'])
        self.assertEqual([f['materia'].clave for f in matriz], ['ESP', 'MAT'])
        espanol, matematicas = matriz
        self.assertIsNone(espanol['celdas'][1])                       # B no lleva Español
        self.assertEqual(matematicas['celdas'][1].profesor, self.profesor)
        self.assertContains(respuesta, '1 h por semana')
        self.assertContains(respuesta, 'Sin horario')


# ---------------------------------------------------------------------------
# Listado por ciclo, con lo que le falta a cada grado
# ---------------------------------------------------------------------------
@PRUEBAS
class ListadoPorCicloTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.actual = ciclo_actual_de_prueba()
        self.proximo = ciclo_proximo_de_prueba()
        self.grado = crear_grado('PRIMARIA', 1)
        self.b = crear_grupo(self.grado, 'B')

    def fila(self, **params):
        respuesta = self.client.get(reverse('grados:lista'), params)
        return respuesta, respuesta.context['niveles'][0]['filas'][0]

    def test_se_elige_el_ciclo_que_se_prepara(self):
        inscribir(crear_alumno(), self.proximo, self.grado)
        materia_en_grado('MAT', self.grado, self.proximo)
        respuesta, fila = self.fila()
        self.assertEqual((respuesta.context['ciclo'], fila['inscritos']), (self.actual, 0))
        respuesta, fila = self.fila(ciclo=self.proximo.pk)
        self.assertEqual((respuesta.context['ciclo'], fila['inscritos'], fila['materias']), (self.proximo, 1, 1))
        self.assertContains(respuesta, '(próximo)')

    def test_avisa_lo_que_falta_y_cuando_esta_listo(self):
        materia_en_grado('MAT', self.grado, self.actual, inicio=None)
        inscribir(crear_alumno(), self.actual, self.grado)
        respuesta, fila = self.fila()
        self.assertEqual(fila['pendientes'], ['1 materia sin profesor', '1 materia sin horario', 'Grupo B sin estudiantes'])
        self.assertContains(respuesta, '1 materia sin profesor · 1 materia sin horario · Grupo B sin estudiantes')
        MateriaGrado.objects.update(profesor=crear_profesor())
        MateriaGrado.objects.filter(grupo=self.b).update(activa=False)
        self.b.activo = False
        self.b.save()
        from Alumnos.models import HorarioMateria
        from datetime import time
        HorarioMateria.objects.create(materia_grado=MateriaGrado.objects.get(activa=True), dia_semana=0,
                                      hora_inicio=time(8), hora_fin=time(9))
        respuesta, fila = self.fila()
        self.assertEqual(fila['pendientes'], [])
        self.assertContains(respuesta, 'Listo para el ciclo')


# ---------------------------------------------------------------------------
# Estudiantes del grado: bajas, resumen por grupo y exportación
# ---------------------------------------------------------------------------
@PRUEBAS
class EstudiantesDelGradoTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.grado = crear_grado('PRIMARIA', 1)
        self.b = crear_grupo(self.grado, 'B')
        self.ana = crear_alumno(nombre='Ana')
        vincular(crear_tutor(nombre='Rosa', telefono='3530001122'), self.ana)
        inscribir(self.ana, self.ciclo, self.grado)
        inscribir(crear_alumno(nombre='Beto'), self.ciclo, self.grado, grupo=self.b)
        inscribir(crear_alumno(nombre='Ciro'), self.ciclo, self.grado, grupo=self.b)
        inscribir(crear_alumno(nombre='Dana'), self.ciclo, self.grado, activa=False)

    def test_resumen_por_grupo_y_bajas_a_pedido(self):
        respuesta = self.client.get(self.grado.get_absolute_url())
        self.assertEqual([(f['grupo'].corto, f['inscritos']) for f in respuesta.context['resumen_por_grupo']], [('1.º A', 1), ('1.º B', 2)])
        self.assertEqual(len(respuesta.context['inscripciones']), 3)
        self.assertContains(respuesta, 'Incluir las bajas (1)')
        con_bajas = self.client.get(self.grado.get_absolute_url(), {'bajas': '1'})
        self.assertEqual(len(con_bajas.context['inscripciones']), 4)
        self.assertEqual(con_bajas.context['total_inscritos'], 3)
        self.assertContains(con_bajas, '<span class="tag">Baja</span>', html=True)

    def leer(self, **params):
        respuesta = self.client.get(reverse('grados:exportar', args=[self.grado.pk]), {'ciclo': self.ciclo.pk, **params})
        return list(csv.reader(io.StringIO(respuesta.content.decode('utf-8-sig'))))

    def test_la_exportacion_trae_grupo_y_tutor(self):
        filas = self.leer()
        self.assertEqual(filas[0][4], 'Grupo')
        self.assertEqual(filas[0][-2:], ['Tutor principal', 'Teléfono del tutor'])
        ana = next(fila for fila in filas if fila[3] == 'Ana')
        self.assertEqual((ana[4], ana[-1]), ('1.º A', '3530001122'))
        self.assertIn('Rosa', ana[-2])
        self.assertEqual(len(filas), 4)   # sin la baja

    def test_se_exporta_un_solo_grupo(self):
        filas = self.leer(grupo=self.b.pk)
        self.assertEqual(sorted(fila[3] for fila in filas[1:]), ['Beto', 'Ciro'])
        self.assertContains(self.client.get(self.grado.get_absolute_url()), 'Exportar solo 1.º B')


# ---------------------------------------------------------------------------
# Equivalencia: un solo criterio y única entre los grados activos
# ---------------------------------------------------------------------------
class EquivalenciaUnicaTests(TestCase):
    def test_la_base_no_permite_dos_grados_activos_con_la_misma(self):
        crear_grado('SECUNDARIA', 1)                       # guarda «7»
        with self.assertRaises(IntegrityError), transaction.atomic():
            Grado.objects.create(nivel='PRIMARIA', numero=5, equivalencia='7')
        Grado.objects.create(nivel='PRIMARIA', numero=6, equivalencia='7', activo=False)   # uno de baja sí

    def test_el_modelo_compara_la_equivalencia_efectiva(self):
        crear_grado('SECUNDARIA', 1)
        with self.assertRaisesMessage(ValidationError, 'La equivalencia 7.º ya la tiene 1.º Secundaria'):
            Grado(nivel='PRIMARIA', numero=5, equivalencia='7').full_clean()

    def test_la_migracion_guarda_la_habitual_a_los_que_no_tienen(self):
        from importlib import import_module

        from django.apps import apps
        guardar = import_module('Alumnos.migrations.0030_grados_consistentes').guardar_equivalencias
        sin = crear_grado('PRIMARIA', 3)
        Grado.objects.filter(pk=sin.pk).update(equivalencia='')
        guardar(apps, None)
        sin.refresh_from_db()
        self.assertEqual(sin.equivalencia, '3')

    def test_se_nombra_con_el_indicador_ordinal(self):
        self.assertEqual(str(crear_grado('SECUNDARIA', 1)), '7.º')
        self.assertEqual(Grado(nivel='PRIMARIA', numero=2).nombre_de_nivel, '2.º Primaria')


# ---------------------------------------------------------------------------
# Admin de Django y alta de un nivel completo
# ---------------------------------------------------------------------------
@PRUEBAS
class AdminYNivelCompletoTests(BaseTestCase):
    def test_el_admin_aplica_las_reglas_y_crea_el_grupo(self):
        url = reverse('admin:Alumnos_grado_add')
        respuesta = self.client.post(url, {'nivel': 'PREESCOLAR', 'numero': 5, 'equivalencia': '', 'activo': 'on'})
        self.assertContains(respuesta, 'En preescolar los grados van del 1.º al 3.º.')
        self.client.post(url, {'nivel': 'PREESCOLAR', 'numero': 2, 'equivalencia': '', 'activo': 'on'})
        grado = Grado.objects.get(nivel='PREESCOLAR', numero=2)
        self.assertEqual(grado.equivalencia, 'K2')
        self.assertEqual(Grupo.objects.filter(grado=grado).count(), 1)
        respuesta = self.client.post(url, {'nivel': 'PRIMARIA', 'numero': 1, 'equivalencia': 'K2', 'activo': 'on'})
        self.assertContains(respuesta, 'ya la tiene 2.º Preescolar')

    def test_un_nivel_completo_de_una_vez(self):
        crear_grado('PRIMARIA', 2)
        respuesta = self.client.post(reverse('grados:nivel'), {'nivel': 'PRIMARIA', 'grupos': [NombreGrupo.inicial().pk]}, follow=True)
        self.assertContains(respuesta, 'Se registraron 5 grados de primaria: 1.º, 3.º, 4.º, 5.º, 6.º. Ya existían 2.º')
        primaria = Grado.objects.filter(nivel='PRIMARIA').order_by('numero')
        self.assertEqual([g.equivalencia for g in primaria], ['1', '2', '3', '4', '5', '6'])
        self.assertTrue(all(g.grupos.filter(activo=True).count() == 1 for g in primaria))

    def test_hasta_un_grado_y_con_conflictos_no_crea_nada(self):
        Grado.objects.create(nivel='PREPARATORIA', numero=4, equivalencia='K1')   # una equivalencia ocupada por error
        respuesta = self.client.post(reverse('grados:nivel'), {'nivel': 'PREESCOLAR', 'hasta': 2})
        self.assertContains(respuesta, '1.º Preescolar: La equivalencia K1 ya la tiene 4.º Preparatoria')
        self.assertFalse(Grado.objects.filter(nivel='PREESCOLAR').exists())
        respuesta = self.client.post(reverse('grados:nivel'), {'nivel': 'SECUNDARIA', 'hasta': 5})
        self.assertContains(respuesta, 'En secundaria los grados van del 1.º al 3.º.')
