"""Grupos: cada grado tiene uno o varios grupos (1° A, 1° B…) con nombres del catálogo. El plan de materias es del grado
y lo comparten sus grupos; cada grupo tiene sus estudiantes, su horario y sus profesores."""
import importlib
from datetime import time

from django.apps import apps
from django.contrib.admin.models import LogEntry
from django.urls import reverse

from Alumnos.academico import agregar_al_plan, extender_plan_al_grupo
from Alumnos.models import Grado, Grupo, HorarioMateria, Inscripcion, Materia, MateriaGrado, NombreGrupo, Recreo
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    crear_alumno,
    crear_grado,
    crear_grupo,
    crear_profesor,
    grupo_de,
    hoy,
    inscribir,
)


def letra(nombre):
    return NombreGrupo.objects.get_or_create(nombre=nombre, defaults={'orden': NombreGrupo.objects.count() + 1})[0]


def crear_materia(clave='MAT', nombre='Matemáticas', grado=None):
    return Materia.objects.create(clave=clave, nombre=nombre, grado=grado)


# ---------------------------------------------------------------------------
# El modelo
# ---------------------------------------------------------------------------
@PRUEBAS
class GrupoTests(BaseTestCase):
    def test_se_nombra_con_su_grado(self):
        grupo = crear_grupo(crear_grado('PRIMARIA', 1), 'B')
        self.assertEqual(str(grupo), '1° B')
        self.assertEqual(grupo.corto, '1° B')

    def test_el_principal_es_el_primero_del_catalogo_y_se_crea_si_falta(self):
        grado = Grado.objects.create(nivel='PRIMARIA', numero=2)
        self.assertFalse(grado.grupos.exists())
        principal = Grupo.principal_de(grado)
        self.assertEqual(str(principal.nombre), 'A')
        crear_grupo(grado, 'B')
        self.assertEqual(Grupo.principal_de(grado), principal)

    def test_un_registro_con_grado_toma_el_grupo_principal_y_uno_con_grupo_toma_su_grado(self):
        ciclo = ciclo_actual_de_prueba()
        grado = crear_grado('PRIMARIA', 1)
        b = crear_grupo(grado, 'B')
        en_a = inscribir(crear_alumno(), ciclo, grado)
        self.assertEqual(en_a.grupo, grupo_de(grado))
        en_b = Inscripcion.objects.create(alumno=crear_alumno(curp='PEMJ100720HMNRRNA5'), ciclo=ciclo, grupo=b)
        self.assertEqual(en_b.grado, grado)


# ---------------------------------------------------------------------------
# Los grupos se eligen al registrar o editar el grado
# ---------------------------------------------------------------------------
@PRUEBAS
class GruposDelGradoTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.a, self.b = letra('A'), letra('B')

    def test_el_formulario_dice_grado_y_ofrece_los_grupos_del_catalogo(self):
        respuesta = self.client.get(reverse('grados:crear'))
        form = respuesta.context['form']
        self.assertEqual(form.fields['numero'].label, 'Grado')
        self.assertNotContains(respuesta, 'Número de grado')
        self.assertEqual(list(form.fields['grupos'].queryset), [self.a, self.b])
        self.assertEqual(form['grupos'].initial, [self.a.pk])   # al menos el «A»

    def test_registra_el_grado_con_sus_grupos(self):
        respuesta = self.client.post(reverse('grados:crear'), {'nivel': 'PRIMARIA', 'numero': 1, 'grupos': [self.a.pk, self.b.pk]}, follow=True)
        grado = Grado.objects.get(nivel='PRIMARIA', numero=1)
        self.assertEqual(sorted(str(g.nombre) for g in grado.grupos.all()), ['A', 'B'])
        self.assertContains(respuesta, 'fue registrado con los grupos A, B')

    def test_sin_grupos_marcados_queda_con_el_a(self):
        self.client.post(reverse('grados:crear'), {'nivel': 'PRIMARIA', 'numero': 1})
        grado = Grado.objects.get(nivel='PRIMARIA', numero=1)
        self.assertEqual([str(g.nombre) for g in grado.grupos.all()], ['A'])

    def test_un_grupo_nuevo_toma_el_plan_de_materias_del_grado(self):
        grado = crear_grado('PRIMARIA', 1)
        mat = crear_materia(grado=grado)
        agregar_al_plan(mat, grado, self.ciclo)
        respuesta = self.client.post(reverse('grados:editar', args=[grado.pk]), {'nivel': 'PRIMARIA', 'numero': 1, 'grupos': [self.a.pk, self.b.pk]}, follow=True)
        self.assertContains(respuesta, 'Se agregó el grupo B con su plan de materias')
        b = grado.grupos.get(nombre=self.b)
        self.assertTrue(MateriaGrado.objects.filter(grupo=b, materia=mat, ciclo=self.ciclo, activa=True, profesor__isnull=True).exists())

    def test_no_se_quita_un_grupo_con_estudiantes(self):
        grado = crear_grado('PRIMARIA', 1)
        b = crear_grupo(grado, 'B')
        Inscripcion.objects.create(alumno=crear_alumno(), ciclo=self.ciclo, grupo=b)
        respuesta = self.client.post(reverse('grados:editar', args=[grado.pk]), {'nivel': 'PRIMARIA', 'numero': 1, 'grupos': [self.a.pk]})
        self.assertIn('El grupo B tiene 1 estudiante inscrito', str(respuesta.context['form'].errors['grupos']))
        b.refresh_from_db()
        self.assertTrue(b.activo)

    def test_quitar_un_grupo_vacio_lo_da_de_baja_y_volver_a_marcarlo_lo_reactiva(self):
        grado = crear_grado('PRIMARIA', 1)
        b = crear_grupo(grado, 'B')
        respuesta = self.client.post(reverse('grados:editar', args=[grado.pk]), {'nivel': 'PRIMARIA', 'numero': 1, 'grupos': [self.a.pk]}, follow=True)
        self.assertContains(respuesta, 'Se dio de baja el grupo B')
        b.refresh_from_db()
        self.assertFalse(b.activo)
        self.client.post(reverse('grados:editar', args=[grado.pk]), {'nivel': 'PRIMARIA', 'numero': 1, 'grupos': [self.a.pk, self.b.pk]})
        b.refresh_from_db()
        self.assertTrue(b.activo)
        self.assertEqual(grado.grupos.count(), 2)   # el mismo grupo, no uno nuevo

    def test_la_tarjeta_del_grado_lista_sus_grupos(self):
        grado = crear_grado('PRIMARIA', 1)
        crear_grupo(grado, 'B')
        self.assertContains(self.client.get(reverse('grados:lista')), 'Grupos A, B')

    def test_el_perfil_del_grado_tiene_un_horario_por_grupo(self):
        grado = crear_grado('PRIMARIA', 1)
        b = crear_grupo(grado, 'B')
        agregar_al_plan(crear_materia(grado=grado), grado, self.ciclo)
        respuesta = self.client.get(grado.get_absolute_url())
        self.assertTrue(respuesta.context['varios_grupos'])
        self.assertEqual(respuesta.context['total_materias'], 1)   # una materia, aunque esté en dos grupos
        self.assertContains(respuesta, reverse('horarios:grupo', args=[grupo_de(grado).pk]))
        self.assertContains(respuesta, reverse('horarios:grupo', args=[b.pk]))


# ---------------------------------------------------------------------------
# El plan del grado es de todos sus grupos
# ---------------------------------------------------------------------------
@PRUEBAS
class PlanPorGrupoTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.grado = crear_grado('PRIMARIA', 1)
        self.b = crear_grupo(self.grado, 'B')

    def test_agregar_al_plan_deja_la_materia_en_cada_grupo(self):
        mat = crear_materia(grado=self.grado)
        asignaciones, cambios = agregar_al_plan(mat, self.grado, self.ciclo)
        self.assertEqual(cambios, 2)
        self.assertEqual({a.grupo for a in asignaciones}, {grupo_de(self.grado), self.b})
        self.assertEqual(agregar_al_plan(mat, self.grado, self.ciclo)[1], 0)   # repetible

    def test_la_materia_nueva_queda_en_todos_los_grupos_con_su_profesor(self):
        marta = crear_profesor()
        respuesta = self.client.post(reverse('materias:crear'), {'nombre': 'Matemáticas', 'clave': '', 'grado': self.grado.pk, 'profesor': marta.pk}, follow=True)
        self.assertEqual(respuesta.status_code, 200)
        filas = MateriaGrado.objects.filter(materia__nombre='Matemáticas', ciclo=self.ciclo)
        self.assertEqual({(f.grupo, f.profesor) for f in filas}, {(grupo_de(self.grado), marta), (self.b, marta)})

    def test_extender_el_plan_a_un_grupo_no_duplica(self):
        mat = crear_materia(grado=self.grado)
        MateriaGrado.objects.create(materia=mat, grado=self.grado, ciclo=self.ciclo)   # solo en el «A»
        self.assertEqual(extender_plan_al_grupo(self.b), 1)
        self.assertEqual(extender_plan_al_grupo(self.b), 0)


# ---------------------------------------------------------------------------
# Inscribir en un grupo
# ---------------------------------------------------------------------------
@PRUEBAS
class InscribirEnUnGrupoTests(BaseTestCase):
    url = property(lambda self: reverse('inscripciones:crear'))

    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.grado = crear_grado('PRIMARIA', 1)
        self.alumno = crear_alumno()

    def datos(self, **cambios):
        return {'alumno': self.alumno.pk, 'ciclo': self.ciclo.pk, 'grado': self.grado.pk, 'fecha_inscripcion': hoy().isoformat(), **cambios}

    def test_con_un_solo_grupo_no_hace_falta_elegirlo(self):
        self.client.post(self.url, self.datos())
        self.assertEqual(Inscripcion.objects.get().grupo, grupo_de(self.grado))

    def test_con_varios_grupos_hay_que_elegirlo(self):
        b = crear_grupo(self.grado, 'B')
        respuesta = self.client.post(self.url, self.datos())
        self.assertEqual(respuesta.context['form'].errors['grupo'], ['Elige el grupo de 1°.'])
        respuesta = self.client.post(self.url, self.datos(grupo=b.pk), follow=True)
        self.assertEqual(Inscripcion.objects.get().grupo, b)
        self.assertContains(respuesta, 'fue inscrito en 1° B')

    def test_el_grupo_tiene_que_ser_del_grado(self):
        otro = crear_grupo(crear_grado('PRIMARIA', 2), 'B')
        respuesta = self.client.post(self.url, self.datos(grupo=otro.pk))
        self.assertEqual(respuesta.context['form'].errors['grupo'], ['Ese grupo no es de 1°.'])
        self.assertFalse(Inscripcion.objects.exists())

    def test_el_campo_sabe_de_que_grado_es_cada_grupo(self):
        b = crear_grupo(self.grado, 'B')
        html = self.client.get(self.url).content.decode()
        self.assertIn('data-grupo-de="grado"', html)
        self.assertIn(f'value="{b.pk}" data-grado="{self.grado.pk}"', html)

    def test_la_importacion_reconoce_el_grupo(self):
        from Alumnos.test_importar import BASICAS, CURP_ANA, CURP_LUIS, importar
        b = crear_grupo(self.grado, 'B')
        resultado = importar(
            [['Ana', 'García', '', CURP_ANA, '1° B Primaria'], ['Luis', 'Pérez', '', CURP_LUIS, '1° Primaria']], BASICAS + ['Grado'],
        )
        self.assertEqual(Inscripcion.objects.get(alumno__curp=CURP_ANA).grupo, b)
        self.assertIn('tiene varios grupos', resultado.errores[0]['motivo'])


# ---------------------------------------------------------------------------
# Cada grupo con su horario
# ---------------------------------------------------------------------------
@PRUEBAS
class HorarioPorGrupoTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.grado = crear_grado('PRIMARIA', 1)
        self.a, self.b = grupo_de(self.grado), crear_grupo(self.grado, 'B')
        self.en_a, self.en_b = agregar_al_plan(crear_materia(grado=self.grado), self.grado, self.ciclo)[0]

    def alta(self, grupo, asignacion):
        return self.client.post(reverse('horarios:crear', args=[grupo.pk]), {
            'materia_grado': asignacion.pk, 'dias': [0], 'inicio_0': '08:00', 'fin_0': '09:00',
        })

    def test_el_alta_solo_ofrece_las_materias_del_grupo(self):
        form = self.client.get(reverse('horarios:crear', args=[self.b.pk])).context['form']
        self.assertEqual(list(form.fields['materia_grado'].queryset), [self.en_b])

    def test_dos_grupos_pueden_llevar_la_misma_materia_a_la_misma_hora(self):
        self.alta(self.a, self.en_a)
        self.alta(self.b, self.en_b)
        self.assertEqual(HorarioMateria.objects.filter(dia_semana=0, hora_inicio=time(8)).count(), 2)
        filas = self.client.get(reverse('horarios:grupo', args=[self.b.pk])).context['cuadricula']['filas']
        self.assertTrue(filas)

    def test_un_profesor_no_puede_estar_en_dos_grupos_a_la_vez(self):
        marta = crear_profesor()
        MateriaGrado.objects.filter(pk__in=[self.en_a.pk, self.en_b.pk]).update(profesor=marta)
        self.alta(self.a, self.en_a)
        respuesta = self.alta(self.b, self.en_b)
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('1° A', str(respuesta.context['form'].errors))
        self.assertEqual(HorarioMateria.objects.count(), 1)

    def test_el_horario_de_un_grado_lleva_al_de_su_primer_grupo(self):
        respuesta = self.client.get(reverse('horarios:grado', args=[self.grado.pk]), {'ciclo': self.ciclo.pk})
        self.assertRedirects(respuesta, f"{reverse('horarios:grupo', args=[self.a.pk])}?ciclo={self.ciclo.pk}")


# ---------------------------------------------------------------------------
# La sección «Grupos»
# ---------------------------------------------------------------------------
@PRUEBAS
class ListadoDeGruposTests(BaseTestCase):
    url = property(lambda self: reverse('grupos:lista'))

    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.grado = crear_grado('PRIMARIA', 1)
        self.b = crear_grupo(self.grado, 'B')
        Inscripcion.objects.create(alumno=crear_alumno(), ciclo=self.ciclo, grupo=self.b)
        agregar_al_plan(crear_materia(grado=self.grado), self.grado, self.ciclo)

    def test_una_tarjeta_por_grupo_con_sus_numeros(self):
        respuesta = self.client.get(self.url)
        primaria = respuesta.context['niveles'][0]
        self.assertEqual(primaria['nombre'], 'Primaria')
        self.assertEqual(
            [(str(f['grupo']), f['inscritos'], f['materias'], f['sin_profesor']) for f in primaria['filas']],
            [('1° A', 0, 1, 1), ('1° B', 1, 1, 1)],
        )
        self.assertContains(respuesta, self.b.get_absolute_url())
        self.assertContains(respuesta, '2 grupos · 1 estudiante inscrito en el ciclo 2026-2027')

    def test_no_muestra_grupos_de_baja_ni_de_grados_de_baja(self):
        self.b.activo = False
        self.b.save()
        otro = crear_grado('PRIMARIA', 2, activo=False)
        grupos = [f['grupo'] for nivel in self.client.get(self.url).context['niveles'] for f in nivel['filas']]
        self.assertEqual(grupos, [grupo_de(self.grado)])
        self.assertNotIn(grupo_de(otro), grupos)

    def test_el_catalogo_dice_en_cuantos_grados_se_usa_cada_nombre(self):
        letra('C')
        catalogo = {str(n): n.en_uso for n in self.client.get(self.url).context['catalogo']}
        self.assertEqual(catalogo, {'A': 1, 'B': 1, 'C': 0})

    def test_sin_permiso_no_se_ve(self):
        self.client.force_login(self.sin_permisos)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.con_permisos('view_grupo')
        self.assertEqual(self.client.get(self.url).status_code, 200)


@PRUEBAS
class PerfilDelGrupoTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.grado = crear_grado('PRIMARIA', 1)
        self.b = crear_grupo(self.grado, 'B')
        self.ana = Inscripcion.objects.create(alumno=crear_alumno(), ciclo=self.ciclo, grupo=self.b)
        self.luis = inscribir(crear_alumno(curp='PEMJ100720HMNRRNA5', nombre='Luis'), self.ciclo, self.grado)   # en el «A»
        self.marta = crear_profesor()
        self.en_a, self.en_b = agregar_al_plan(crear_materia(grado=self.grado), self.grado, self.ciclo)[0]
        self.en_b.profesor = self.marta
        self.en_b.save()

    def test_muestra_solo_sus_estudiantes_y_sus_materias(self):
        respuesta = self.client.get(self.b.get_absolute_url())
        self.assertEqual(respuesta.context['inscripciones'], [self.ana])
        self.assertEqual(respuesta.context['materias'], [self.en_b])
        self.assertEqual(respuesta.context['sin_profesor'], 0)
        self.assertContains(respuesta, '1° B')
        self.assertContains(respuesta, reverse('horarios:grupo', args=[self.b.pk]))

    def test_enlaza_con_los_otros_grupos_del_grado(self):
        respuesta = self.client.get(self.b.get_absolute_url())
        self.assertEqual(respuesta.context['grupos_del_grado'], [grupo_de(self.grado), self.b])

    def test_inscribir_desde_el_grupo_lo_trae_elegido(self):
        respuesta = self.client.get(self.b.get_absolute_url())
        self.assertContains(respuesta, f'grado={self.grado.pk}&amp;grupo={self.b.pk}')
        form = self.client.get(reverse('inscripciones:crear'), {'grado': self.grado.pk, 'grupo': self.b.pk}).context['form']
        self.assertEqual(str(form['grupo'].value()), str(self.b.pk))

    def test_un_grupo_que_no_existe(self):
        self.assertEqual(self.client.get(reverse('grupos:detalle', args=[9999])).status_code, 404)


# ---------------------------------------------------------------------------
# Catálogo de nombres de grupo
# ---------------------------------------------------------------------------
@PRUEBAS
class CatalogoTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.a = letra('A')

    def test_agrega_un_nombre_en_mayusculas_y_al_final(self):
        respuesta = self.client.get(reverse('grupos:nombre_crear'))
        self.assertEqual(respuesta.context['form']['orden'].initial, self.a.orden + 1)
        respuesta = self.client.post(reverse('grupos:nombre_crear'), {'nombre': ' b ', 'orden': 2})
        self.assertRedirects(respuesta, f"{reverse('grupos:lista')}#catalogo")
        nombre = NombreGrupo.objects.get(nombre='B')
        self.assertTrue(LogEntry.objects.filter(object_id=str(nombre.pk), change_message='Nombre de grupo «B».').exists())

    def test_un_nombre_largo_conserva_sus_mayusculas(self):
        self.client.post(reverse('grupos:nombre_crear'), {'nombre': 'Matutino', 'orden': 3})
        self.assertTrue(NombreGrupo.objects.filter(nombre='Matutino').exists())

    def test_no_se_repite_un_nombre(self):
        respuesta = self.client.post(reverse('grupos:nombre_crear'), {'nombre': 'a', 'orden': 5})
        self.assertEqual(respuesta.context['form'].errors['nombre'], ['Ya existe un grupo con ese nombre.'])

    def test_renombrar_renombra_los_grupos_que_lo_usan(self):
        grupo = grupo_de(crear_grado('PRIMARIA', 1))
        self.client.post(reverse('grupos:nombre_editar', args=[self.a.pk]), {'nombre': 'Azul', 'orden': 1})
        grupo.refresh_from_db()
        self.assertEqual(str(grupo), '1° Azul')

    def test_la_baja_deja_de_ofrecerlo_pero_los_grupos_lo_conservan(self):
        b = letra('B')
        grado = crear_grado('PRIMARIA', 1)
        crear_grupo(grado, 'B')
        respuesta = self.client.post(reverse('grupos:nombre_baja', args=[b.pk]), follow=True)
        self.assertContains(respuesta, 'El grupo que ya lo usa lo conserva')
        b.refresh_from_db()
        self.assertFalse(b.activo)
        self.assertNotIn(b, self.client.get(reverse('grados:crear')).context['form'].fields['grupos'].queryset)
        # en el grado que ya lo tiene, se sigue ofreciendo (marcado)
        self.assertIn(b, self.client.get(reverse('grados:editar', args=[grado.pk])).context['form'].fields['grupos'].queryset)
        self.client.post(reverse('grupos:nombre_reactivar', args=[b.pk]))
        b.refresh_from_db()
        self.assertTrue(b.activo)

    def test_la_baja_y_la_reactivacion_solo_por_post(self):
        self.assertEqual(self.client.get(reverse('grupos:nombre_baja', args=[self.a.pk])).status_code, 405)
        self.assertEqual(self.client.get(reverse('grupos:nombre_reactivar', args=[self.a.pk])).status_code, 405)

    def test_sin_permiso_no_se_administra(self):
        self.con_permisos('view_grupo', 'view_nombregrupo')
        self.assertEqual(self.client.get(reverse('grupos:nombre_crear')).status_code, 403)
        self.assertEqual(self.client.post(reverse('grupos:nombre_baja', args=[self.a.pk])).status_code, 403)
        self.a.refresh_from_db()
        self.assertTrue(self.a.activo)


# ---------------------------------------------------------------------------
# Las migraciones: los datos que ya había quedan en el grupo «A» de su grado
# ---------------------------------------------------------------------------
@PRUEBAS
class MigracionTests(BaseTestCase):
    def test_cada_grado_recibe_su_grupo_a_y_los_recreos_pasan_a_llamarse_recesos(self):
        ciclo = ciclo_actual_de_prueba()
        grado = Grado.objects.create(nivel='PRIMARIA', numero=1)   # sin grupos, como antes de la migración
        receso = Recreo.objects.create(ciclo=ciclo, grado=grado, nombre='Recreo largo', dia_semana=0, hora_inicio=time(10), hora_fin=time(10, 30))
        migracion = importlib.import_module('Alumnos.migrations.0020_grupos')
        migracion.un_grupo_por_grado(apps, None)
        migracion.un_grupo_por_grado(apps, None)   # repetible
        self.assertEqual([str(g) for g in grado.grupos.all()], ['1° A'])
        receso.refresh_from_db()
        self.assertEqual(receso.nombre, 'Receso largo')

    def test_quien_consulta_o_edita_los_grados_tambien_los_grupos(self):
        from django.contrib.auth.models import Group, Permission
        consulta = Group.objects.create(name='Consulta')
        consulta.permissions.add(Permission.objects.get(codename='view_grado'))
        gestion = Group.objects.create(name='Gestión')
        gestion.permissions.add(Permission.objects.get(codename='change_grado'))
        importlib.import_module('Usuarios.migrations.0006_permisos_de_grupos').conceder_grupos(apps, None)
        self.assertEqual(set(consulta.permissions.values_list('codename', flat=True)), {'view_grado', 'view_grupo', 'view_nombregrupo'})
        self.assertTrue({'add_nombregrupo', 'change_nombregrupo', 'delete_nombregrupo'} <= set(gestion.permissions.values_list('codename', flat=True)))
