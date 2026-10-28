"""«Visible en el sistema» (2026-10-28): un grado oculto no se ofrece en ninguna lista, selector ni filtro, no se puede
usar para algo nuevo aunque se mande su id a mano, conserva intactos sus registros y su historial, y vuelve a todas
partes al mostrarlo. Solo quien puede cambiar grados lo muestra u oculta."""
from django.contrib.admin.models import LogEntry
from django.urls import reverse

from Alumnos.forms import FiltroAlumnosForm, InscribirForm, grados_disponibles, grupos_disponibles
from Alumnos.models import Grado, Grupo, Inscripcion, Materia, MateriaGrado
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    ciclo_proximo_de_prueba,
    crear_alumno,
    crear_grado,
    grupo_de,
    hoy,
    inscribir,
)


class Semestres:
    """Preparatoria por semestres: 1.º (A) visible y 2.º (B) oculto, con una estudiante inscrita en cada uno."""

    def armar(self):
        self.ciclo = ciclo_actual_de_prueba()
        self.primero = crear_grado('PREPARATORIA', 1)
        self.segundo = crear_grado('PREPARATORIA', 2)
        self.grupo_a, self.grupo_b = grupo_de(self.primero), grupo_de(self.segundo)
        self.ana = crear_alumno(nombre='Ana')
        self.eva = crear_alumno(nombre='Eva')
        self.de_ana = inscribir(self.ana, self.ciclo, self.primero, grupo=self.grupo_a)
        self.de_eva = inscribir(self.eva, self.ciclo, self.segundo, grupo=self.grupo_b)
        self.ocultar(self.segundo)

    def ocultar(self, grado, visible=False):
        return self.client.post(reverse('grados:visibilidad', args=[grado.pk]), {'visible': '1'} if visible else {})


# ---------------------------------------------------------------------------
# El interruptor y sus permisos
# ---------------------------------------------------------------------------
@PRUEBAS
class InterruptorTests(Semestres, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()

    def test_los_grados_quedan_visibles_por_defecto(self):
        self.assertTrue(Grado.objects.create(nivel='PRIMARIA', numero=3).visible)
        self.assertTrue(Grado.objects.get(pk=self.primero.pk).visible)

    def test_ocultar_y_volver_a_mostrar_queda_en_el_historial(self):
        self.segundo.refresh_from_db()
        self.assertFalse(self.segundo.visible)
        respuesta = self.ocultar(self.segundo, visible=True)
        self.assertRedirects(respuesta, reverse('grados:lista'), fetch_redirect_response=False)
        self.segundo.refresh_from_db()
        self.assertTrue(self.segundo.visible)
        mensajes = list(LogEntry.objects.filter(object_id=str(self.segundo.pk)).order_by('pk').values_list('change_message', flat=True))
        self.assertEqual(mensajes, ['Lo ocultó del sistema.', 'Lo mostró en el sistema.'])

    def test_sin_permiso_de_cambiar_grados_no_se_puede(self):
        self.con_permisos('view_grado', 'add_grado', 'delete_grado')
        self.assertEqual(self.ocultar(self.segundo, visible=True).status_code, 403)
        self.assertEqual(self.ocultar(self.primero).status_code, 403)
        self.assertFalse(Grado.objects.get(pk=self.segundo.pk).visible)
        self.assertTrue(Grado.objects.get(pk=self.primero.pk).visible)
        # Y no ve el interruptor, solo el estado
        respuesta = self.client.get(reverse('grados:lista'))
        self.assertNotContains(respuesta, reverse('grados:visibilidad', args=[self.primero.pk]))
        self.assertContains(respuesta, 'Oculto')

    def test_con_permiso_de_cambiar_grados_si(self):
        self.con_permisos('view_grado', 'change_grado')
        self.ocultar(self.primero)
        self.assertFalse(Grado.objects.get(pk=self.primero.pk).visible)

    def test_solo_por_post(self):
        self.assertEqual(self.client.get(reverse('grados:visibilidad', args=[self.segundo.pk])).status_code, 405)

    def test_vuelve_a_la_pagina_desde_la_que_se_hizo(self):
        volver = reverse('grados:detalle', args=[self.segundo.pk])
        respuesta = self.client.post(reverse('grados:visibilidad', args=[self.segundo.pk]), {'visible': '1', 'next': volver})
        self.assertRedirects(respuesta, volver, fetch_redirect_response=False)


# ---------------------------------------------------------------------------
# La administración de grados: los ocultos se consultan y se reactivan
# ---------------------------------------------------------------------------
@PRUEBAS
class AdministracionTests(Semestres, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()

    def test_el_filtro_todos_visibles_y_ocultos(self):
        url = reverse('grados:lista')
        todos = self.client.get(url)
        self.assertEqual([(c, t) for c, _, t in todos.context['visibilidades']], [('', 2), ('visibles', 1), ('ocultos', 1)])
        self.assertContains(todos, '1.º Preparatoria')
        self.assertContains(todos, '2.º Preparatoria')
        self.assertContains(todos, 'Visible en el sistema')

        ocultos = self.client.get(url, {'visibilidad': 'ocultos'})
        self.assertNotContains(ocultos, '1.º Preparatoria')
        self.assertContains(ocultos, '2.º Preparatoria')
        self.assertContains(ocultos, '<span class="tag tag--warning">Oculto</span>', html=True)

        visibles = self.client.get(url, {'visibilidad': 'visibles'})
        self.assertContains(visibles, '1.º Preparatoria')
        self.assertNotContains(visibles, '2.º Preparatoria')

    def test_un_valor_desconocido_del_filtro_es_todos(self):
        respuesta = self.client.get(reverse('grados:lista'), {'visibilidad': 'x'})
        self.assertEqual(respuesta.context['visibilidad'], '')
        self.assertContains(respuesta, '2.º Preparatoria')

    def test_el_perfil_del_oculto_se_consulta_con_sus_estudiantes(self):
        respuesta = self.client.get(reverse('grados:detalle', args=[self.segundo.pk]))
        self.assertContains(respuesta, 'Grado oculto.')
        self.assertContains(respuesta, 'Eva')
        self.assertFalse(respuesta.context['puede_inscribir'])
        self.assertNotContains(respuesta, f'{reverse("inscripciones:crear")}?ciclo={self.ciclo.pk}&amp;grado={self.segundo.pk}')


# ---------------------------------------------------------------------------
# No aparece en ninguna opción (y vuelve al mostrarlo)
# ---------------------------------------------------------------------------
@PRUEBAS
class OpcionesTests(Semestres, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()

    def test_los_selectores_de_grado_y_grupo(self):
        self.assertNotIn(self.segundo, grados_disponibles())
        self.assertNotIn(self.grupo_b, grupos_disponibles())
        form = InscribirForm(alumno=crear_alumno())
        self.assertNotIn(self.segundo, form.fields['grado'].queryset)
        self.assertNotIn(self.grupo_b, form.fields['grupo'].queryset)
        filtro = FiltroAlumnosForm(usuario=self.admin)
        self.assertNotIn(self.segundo, filtro.fields['grado'].queryset)
        self.assertNotIn(self.grupo_b, filtro.fields['grupo'].queryset)
        self.assertIn(self.primero, filtro.fields['grado'].queryset)

    def test_los_filtros_de_otros_modulos(self):
        from Asistencias.forms import FiltroReporteForm
        from Conducta.forms import FiltroForm as FiltroConductaForm
        from Inscripciones.forms import FiltroInscripcionesForm
        from Prefectura.alcance import TOTAL
        for form in (FiltroInscripcionesForm(), FiltroReporteForm(), FiltroConductaForm()):
            with self.subTest(form=type(form).__name__):
                self.assertNotIn(self.segundo, form.fields['grado'].queryset)
                self.assertIn(self.primero, form.fields['grado'].queryset)
        self.assertNotIn(self.grupo_b, TOTAL.grupos_visibles())
        self.assertIn(self.grupo_a, TOTAL.grupos_visibles())

    def test_el_panel_los_ciclos_y_los_niveles(self):
        from Ciclos.resumen import _grados_activos
        from Panel.filtros import filtros_de, niveles_configurados
        filtros = filtros_de({})
        self.assertNotIn(self.segundo, filtros.grados)
        self.assertNotIn(self.grupo_b, filtros.grupos)
        self.assertNotIn(self.segundo, _grados_activos())
        self.assertEqual([clave for clave, _ in niveles_configurados()], ['PREPARATORIA'])
        # Con todos sus grados ocultos, el nivel deja de ofrecerse
        self.ocultar(self.primero)
        self.assertEqual({clave for clave, _ in niveles_configurados()}, {'PREESCOLAR', 'PRIMARIA', 'SECUNDARIA', 'PREPARATORIA'})
        crear_grado('PRIMARIA', 1)
        self.assertEqual([clave for clave, _ in niveles_configurados()], ['PRIMARIA'])

    def test_las_pantallas_de_grupos_horarios_y_comunicados(self):
        from Comunicados.alcance import alcance_de
        from Horarios.forms import RecreoCrearForm
        respuesta = self.client.get(reverse('grupos:lista'))
        grupos = [fila['grupo'] for nivel in respuesta.context['niveles'] for fila in nivel['filas']]
        self.assertEqual(grupos, [self.grupo_a])
        self.assertEqual(respuesta.context['de_grados_ocultos'], 1)
        horarios = self.client.get(reverse('horarios:lista'))
        self.assertEqual([fila['grupo'] for nivel in horarios.context['niveles'] for fila in nivel['filas']], [self.grupo_a])
        self.assertNotIn(self.grupo_b, RecreoCrearForm(ciclo=self.ciclo).fields['grupos'].queryset)
        arbol = alcance_de(self.admin).universo()['arbol']
        self.assertEqual([g['id'] for nivel in arbol for grado in nivel['grados'] for g in grado['grupos']], [self.grupo_a.pk])

    def test_las_listas_de_materias(self):
        from Alumnos.asistencia_docente import asignaciones_del_ciclo
        from Materias.forms import MateriaForm
        quimica = Materia.objects.create(clave='QUI2', nombre='Química', grado=self.segundo)
        clase = MateriaGrado.objects.create(materia=quimica, grado=self.segundo, grupo=self.grupo_b, ciclo=self.ciclo)
        self.assertNotIn(clase, asignaciones_del_ciclo(self.ciclo))
        self.assertNotIn(self.segundo, MateriaForm(ciclo=self.ciclo).fields['grado'].queryset)

    def test_al_mostrarlo_vuelve_a_todas_partes(self):
        self.ocultar(self.segundo, visible=True)
        self.assertIn(self.segundo, grados_disponibles())
        self.assertIn(self.grupo_b, grupos_disponibles())
        self.assertIn(self.segundo, FiltroAlumnosForm(usuario=self.admin).fields['grado'].queryset)
        respuesta = self.client.get(reverse('grupos:lista'))
        self.assertIn(self.grupo_b, [fila['grupo'] for nivel in respuesta.context['niveles'] for fila in nivel['filas']])
        self.assertTrue(self.client.get(reverse('grados:detalle', args=[self.segundo.pk])).context['puede_inscribir'])


# ---------------------------------------------------------------------------
# No se usa para algo nuevo aunque se mande su id; lo que ya lo tiene se conserva
# ---------------------------------------------------------------------------
@PRUEBAS
class AsociacionesTests(Semestres, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()

    def test_no_se_inscribe_mandando_su_id(self):
        nueva = crear_alumno(nombre='Iris')
        respuesta = self.client.post(reverse('inscripciones:crear'), {
            'alumno': nueva.pk, 'ciclo': self.ciclo.pk, 'grado': self.segundo.pk, 'grupo': self.grupo_b.pk,
            'fecha_inscripcion': hoy().isoformat(),
        })
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('grado', respuesta.context['form'].errors)
        self.assertFalse(Inscripcion.objects.filter(alumno=nueva).exists())

    def test_no_se_cambia_a_un_grupo_suyo_desde_otra_inscripcion(self):
        respuesta = self.client.post(reverse('inscripciones:editar', args=[self.de_ana.pk]), {
            'grado': self.segundo.pk, 'grupo': self.grupo_b.pk, 'fecha_inscripcion': self.de_ana.fecha_inscripcion.isoformat(),
        })
        self.assertEqual(respuesta.status_code, 200)
        self.de_ana.refresh_from_db()
        self.assertEqual(self.de_ana.grado, self.primero)

    def test_no_se_agrega_a_su_plan_mandando_su_id(self):
        quimica = Materia.objects.create(clave='QUI', nombre='Química')
        self.client.post(reverse('materias:asignar'), {'ciclo': self.ciclo.pk, 'materia': quimica.pk, 'grado': self.segundo.pk})
        self.assertFalse(MateriaGrado.objects.filter(materia=quimica).exists())

    def test_la_promocion_no_lo_propone_ni_lo_acepta(self):
        proximo = ciclo_proximo_de_prueba()
        datos = {'origen': self.ciclo.pk, 'destino': proximo.pk}
        respuesta = self.client.get(reverse('inscripciones:promocion'), datos)
        fila = next(f for f in respuesta.context['plan'] if f['grado'] == self.primero)
        self.assertEqual(fila['sugerido'], 'omitir')                 # su siguiente (2.º) está oculto
        self.assertEqual(fila['siguiente_oculto'], self.segundo)
        self.assertNotIn(self.segundo, [g for nivel in respuesta.context['grupos_destino'] for g in nivel['grados']])
        self.client.post(reverse('inscripciones:promocion'), {**datos, f'grado_{self.primero.pk}': self.segundo.pk})
        self.assertFalse(Inscripcion.objects.filter(ciclo=proximo).exists())

    def test_se_editan_otros_datos_sin_perder_el_grado_oculto(self):
        ayer = hoy().replace(day=1) if hoy().day > 1 else hoy()
        respuesta = self.client.post(reverse('inscripciones:editar', args=[self.de_eva.pk]), {
            'grado': self.segundo.pk, 'grupo': self.grupo_b.pk, 'fecha_inscripcion': ayer.isoformat(),
        })
        self.assertEqual(respuesta.status_code, 302)
        self.de_eva.refresh_from_db()
        self.assertEqual((self.de_eva.grado, self.de_eva.grupo, self.de_eva.fecha_inscripcion), (self.segundo, self.grupo_b, ayer))

    def test_la_materia_conserva_su_grado_oculto_al_editarla(self):
        quimica = Materia.objects.create(clave='QUI2', nombre='Química', grado=self.segundo)
        respuesta = self.client.post(reverse('materias:editar', args=[quimica.pk]), {
            'clave': 'QUI2', 'nombre': 'Química II', 'grado': self.segundo.pk,
        })
        self.assertEqual(respuesta.status_code, 302)
        quimica.refresh_from_db()
        self.assertEqual((quimica.nombre, quimica.grado), ('Química II', self.segundo))


# ---------------------------------------------------------------------------
# Sus registros quedan intactos y se siguen consultando
# ---------------------------------------------------------------------------
@PRUEBAS
class RegistrosTests(Semestres, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()

    def test_ocultarlo_no_toca_sus_registros(self):
        self.de_eva.refresh_from_db()
        self.assertTrue(self.de_eva.activa)
        self.assertEqual((self.de_eva.grado, self.de_eva.grupo), (self.segundo, self.grupo_b))
        self.assertTrue(Grupo.objects.get(pk=self.grupo_b.pk).activo)
        self.assertTrue(Grado.objects.get(pk=self.segundo.pk).activo)
        self.assertEqual(self.eva.estatus, type(self.eva).objects.get(pk=self.eva.pk).estatus)

    def test_su_historial_se_sigue_consultando_con_su_nombre(self):
        expediente = self.client.get(reverse('alumnos:detalle', args=[self.eva.pk]))
        self.assertContains(expediente, self.segundo.nombre_equivalente)
        lista = self.client.get(reverse('inscripciones:lista'), {'ciclo': self.ciclo.pk})
        self.assertContains(lista, 'Eva')
        estudiantes = self.client.get(reverse('alumnos:lista'))
        self.assertContains(estudiantes, 'Eva')
