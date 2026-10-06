"""Asignaciones académicas: el mapa materias × grados y la nueva asignación en un solo formulario."""
import json

from django.contrib.admin.models import LogEntry
from django.urls import reverse

from Alumnos.docentes import habilitar
from Alumnos.models import Materia, MateriaGrado, ProfesorMateria
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    ciclo_cerrado_de_prueba,
    ciclo_proximo_de_prueba,
    crear_grado,
    crear_profesor,
)
from Profesores.tests import asignar, bloque, crear_materia


class PlanTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.p1, self.p2 = crear_grado('PRIMARIA', 1), crear_grado('PRIMARIA', 2)
        self.s1 = crear_grado('SECUNDARIA', 1)
        self.mat = crear_materia('MAT', 'Matemáticas')
        self.esp = crear_materia('ESP', 'Español')
        self.marta = crear_profesor(nombre='Marta', apellido_paterno='Rangel')
        self.beto = crear_profesor(nombre='Beto', apellido_paterno='Aguilar', telefono='3530000002')
        self.mat_p1 = asignar(self.mat, self.p1, self.ciclo, profesor=self.marta)
        self.esp_p1 = asignar(self.esp, self.p1, self.ciclo)


# ---------------------------------------------------------------------------
# Mapa
# ---------------------------------------------------------------------------
@PRUEBAS
class MapaTests(PlanTestCase):
    def pedir(self, **parametros):
        return self.client.get(reverse('asignaciones:mapa'), parametros)

    def test_una_fila_por_materia_y_una_columna_por_grado(self):
        respuesta = self.pedir()
        self.assertEqual([f['materia'].clave for f in respuesta.context['filas']], ['ESP', 'MAT'])
        self.assertEqual([str(c['grado']) for c in respuesta.context['columnas']], ['1° Primaria', '2° Primaria', '1° Secundaria'])
        self.assertEqual([g['nombre'] for g in respuesta.context['grupos_de_nivel']], ['Primaria', 'Secundaria'])

    def test_cada_celda_dice_quien_la_imparte_o_permite_agregarla(self):
        respuesta = self.pedir()
        self.assertContains(respuesta, 'M. Rangel')
        self.assertContains(respuesta, 'Sin profesor')
        self.assertContains(respuesta, f'data-asignacion="{self.mat_p1.pk}"')
        agregar = f'{reverse("asignaciones:nueva")}?ciclo={self.ciclo.pk}&amp;materia={self.mat.pk}&amp;grado={self.p2.pk}'
        self.assertContains(respuesta, agregar)

    def test_los_totales_por_grado(self):
        columnas = {str(c['grado']): c for c in self.pedir().context['columnas']}
        self.assertEqual((columnas['1° Primaria']['materias'], columnas['1° Primaria']['sin_profesor']), (2, 1))
        self.assertEqual(columnas['2° Primaria']['materias'], 0)

    def test_filtra_por_nivel_y_por_materia(self):
        self.assertEqual([str(c['grado']) for c in self.pedir(nivel='SECUNDARIA').context['columnas']], ['1° Secundaria'])
        self.assertEqual([f['materia'].clave for f in self.pedir(q='espa').context['filas']], ['ESP'])
        self.assertEqual(len(self.pedir(nivel='XX').context['columnas']), 3)   # un nivel inválido se ignora

    def test_una_materia_de_baja_solo_aparece_si_sigue_en_el_plan(self):
        baja = crear_materia('OLD', 'Antigua', activa=False)
        self.assertNotIn(baja, [f['materia'] for f in self.pedir().context['filas']])
        asignar(baja, self.p2, self.ciclo)
        self.assertIn(baja, [f['materia'] for f in self.pedir().context['filas']])

    def test_la_leyenda_muestra_a_los_profesores_del_mapa(self):
        leyenda = [e['profesor'] for e in self.pedir().context['leyenda']]
        self.assertEqual(leyenda, [self.marta])

    def test_un_ciclo_cerrado_solo_se_consulta(self):
        cerrado = ciclo_cerrado_de_prueba()
        asignar(self.mat, self.p1, cerrado, profesor=self.beto)
        respuesta = self.pedir(ciclo=cerrado.pk)
        self.assertContains(respuesta, 'B. Aguilar')
        self.assertNotContains(respuesta, 'data-asignar-profesor')
        self.assertNotContains(respuesta, reverse('asignaciones:nueva'))

    def test_las_acciones_dependen_de_los_permisos(self):
        self.con_permisos('view_materiagrado')
        respuesta = self.pedir()
        self.assertContains(respuesta, 'M. Rangel')
        self.assertNotContains(respuesta, 'data-asignar-profesor')
        self.assertNotContains(respuesta, reverse('asignaciones:nueva'))
        self.con_permisos('view_materiagrado', 'change_materiagrado')
        self.assertContains(self.pedir(), 'data-asignar-profesor')
        self.con_permisos('view_materiagrado', 'add_materiagrado')
        self.assertContains(self.pedir(), reverse('asignaciones:nueva'))

    def test_sin_ciclos(self):
        MateriaGrado.objects.all().delete()
        self.ciclo.delete()
        self.assertContains(self.pedir(), 'Aún no hay ciclos escolares')

    def test_pide_permiso_de_ver_el_plan(self):
        self.con_permisos('view_materia')
        self.assertEqual(self.pedir().status_code, 403)


# ---------------------------------------------------------------------------
# Nueva asignación
# ---------------------------------------------------------------------------
@PRUEBAS
class NuevaAsignacionTests(PlanTestCase):
    url = None

    def setUp(self):
        super().setUp()
        self.url = reverse('asignaciones:nueva')

    def datos(self, **cambios):
        datos = {'ciclo': self.ciclo.pk, 'origen': 'existente', 'materia': self.esp.pk, 'grados': [self.p2.pk, self.s1.pk],
                 'profesor': self.beto.pk}
        datos.update(cambios)
        return {k: v for k, v in datos.items() if v is not None}

    def test_el_formulario_llega_con_lo_que_se_eligio_en_el_mapa(self):
        respuesta = self.client.get(self.url, {'ciclo': self.ciclo.pk, 'materia': self.mat.pk, 'grado': self.p2.pk})
        form = respuesta.context['form']
        self.assertEqual(form['materia'].value(), self.mat.pk)
        self.assertEqual(form['grados'].value(), [self.p2.pk])
        datos = respuesta.context['datos']
        self.assertEqual(datos['plan'][str(self.ciclo.pk)][str(self.mat.pk)], {str(self.p1.pk): self.marta.pk})
        self.assertContains(respuesta, 'id="asignacion-datos"')
        json.loads(respuesta.content.decode().split('id="asignacion-datos" type="application/json">')[1].split('</script>')[0])

    def test_agrega_la_materia_a_varios_grados_con_su_profesor(self):
        respuesta = self.client.post(self.url, self.datos(), follow=True)
        self.assertRedirects(respuesta, f'{reverse("asignaciones:mapa")}?ciclo={self.ciclo.pk}')
        nuevas = MateriaGrado.objects.filter(ciclo=self.ciclo, materia=self.esp, grado__in=[self.p2, self.s1])
        self.assertEqual(nuevas.count(), 2)
        self.assertTrue(all(mg.profesor == self.beto for mg in nuevas))
        self.assertTrue(ProfesorMateria.objects.filter(profesor=self.beto, materia=self.esp).exists())   # queda habilitado
        self.assertContains(respuesta, 'Español quedó en el plan de 2° Primaria y 1° Secundaria')
        self.assertContains(respuesta, 'Beto Aguilar Soto la imparte en')
        self.assertEqual(LogEntry.objects.count(), 2)

    def test_sin_profesor_por_ahora(self):
        self.client.post(self.url, self.datos(profesor=''))
        self.assertEqual(MateriaGrado.objects.filter(materia=self.esp, profesor__isnull=True).count(), 3)

    def test_un_profesor_distinto_por_grado(self):
        self.client.post(self.url, self.datos(por_grado='on', **{f'profesor_{self.s1.pk}': self.marta.pk}))
        self.assertEqual(MateriaGrado.objects.get(materia=self.esp, grado=self.s1).profesor, self.marta)
        self.assertEqual(MateriaGrado.objects.get(materia=self.esp, grado=self.p2).profesor, self.beto)   # sin el suyo: el general

    def test_crear_la_materia_en_el_mismo_paso(self):
        self.client.post(self.url, self.datos(origen='nueva', materia=None, nueva_nombre='Educación  física', nueva_clave='ed f'))
        materia = Materia.objects.get(clave='ED-F')
        self.assertEqual(materia.nombre, 'Educación física')
        self.assertEqual(MateriaGrado.objects.filter(materia=materia).count(), 2)
        self.assertTrue(LogEntry.objects.filter(object_id=str(materia.pk), change_message__contains='Asignaciones académicas').exists())

    def test_la_materia_nueva_no_repite_clave(self):
        respuesta = self.client.post(self.url, self.datos(origen='nueva', materia=None, nueva_nombre='Mate', nueva_clave='mat'))
        self.assertContains(respuesta, 'Ya existe una materia con esa clave.')
        self.assertEqual(Materia.objects.count(), 2)

    def test_pide_materia_y_grados(self):
        respuesta = self.client.post(self.url, self.datos(materia='', grados=[]))
        self.assertContains(respuesta, 'Elige la materia o crea una nueva.')
        self.assertContains(respuesta, 'Elige al menos un grado.')

    def test_lo_que_ya_estaba_no_se_duplica_y_lo_quitado_se_reactiva(self):
        self.esp_p1.activa = False
        self.esp_p1.save()
        self.client.post(self.url, self.datos(grados=[self.p1.pk], profesor=''))
        self.esp_p1.refresh_from_db()
        self.assertTrue(self.esp_p1.activa)
        respuesta = self.client.post(self.url, self.datos(grados=[self.p1.pk], profesor=''), follow=True)
        self.assertContains(respuesta, 'ya estaba en 1° Primaria')
        self.assertEqual(MateriaGrado.objects.filter(materia=self.esp, grado=self.p1).count(), 1)

    def test_si_el_horario_choca_esa_queda_sin_profesor_y_se_avisa(self):
        bloque(self.mat_p1, 0, (8, 0), (9, 0))
        espanol_p2 = asignar(self.esp, self.p2, self.ciclo)
        bloque(espanol_p2, 0, (8, 30), (9, 30))
        respuesta = self.client.post(self.url, self.datos(grados=[self.p2.pk], profesor=self.marta.pk), follow=True)
        self.assertContains(respuesta, 'No se pudo asignar el profesor')
        espanol_p2.refresh_from_db()
        self.assertIsNone(espanol_p2.profesor)

    def test_un_ciclo_cerrado_no_se_puede_elegir(self):
        cerrado = ciclo_cerrado_de_prueba()
        respuesta = self.client.post(self.url, self.datos(ciclo=cerrado.pk))
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(MateriaGrado.objects.filter(ciclo=cerrado).exists())

    def test_se_puede_armar_el_ciclo_proximo(self):
        proximo = ciclo_proximo_de_prueba()
        self.client.post(self.url, self.datos(ciclo=proximo.pk))
        self.assertEqual(MateriaGrado.objects.filter(ciclo=proximo).count(), 2)

    def test_sin_ciclos_abiertos_regresa_al_mapa(self):
        MateriaGrado.objects.all().delete()
        self.ciclo.delete()
        ciclo_cerrado_de_prueba()
        respuesta = self.client.get(self.url, follow=True)
        self.assertContains(respuesta, 'No hay ciclos abiertos')

    def test_desde_la_ventana_responde_con_la_redireccion(self):
        respuesta = self.client.post(self.url, self.datos(), HTTP_X_MODAL_FORM='1')
        self.assertEqual(respuesta.json(), {'redirect': f'{reverse("asignaciones:mapa")}?ciclo={self.ciclo.pk}'})

    def test_permisos(self):
        self.con_permisos('view_materiagrado')
        self.assertEqual(self.client.get(self.url).status_code, 403)
        # Puede armar el plan pero no elegir profesores: el profesor se ignora
        self.con_permisos('view_materiagrado', 'add_materiagrado', 'view_materia')
        html = self.client.get(self.url).content.decode()
        self.assertNotIn('Quién la imparte', html)
        self.assertNotIn('value="nueva"', html)   # tampoco crear materias
        self.client.post(self.url, self.datos())
        self.assertEqual(MateriaGrado.objects.filter(materia=self.esp, profesor__isnull=True).count(), 3)
        respuesta = self.client.post(self.url, self.datos(origen='nueva', materia=None, nueva_nombre='Arte', nueva_clave='ART'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Materia.objects.filter(clave='ART').exists())


# ---------------------------------------------------------------------------
# Quien imparte una materia la puede impartir
# ---------------------------------------------------------------------------
@PRUEBAS
class HabilitacionAutomaticaTests(PlanTestCase):
    def test_asignar_un_profesor_lo_habilita_en_la_materia(self):
        self.assertFalse(ProfesorMateria.objects.filter(profesor=self.beto, materia=self.esp).exists())
        self.client.post(reverse('profesores:asignar'), {'asignacion': [self.esp_p1.pk], 'profesor': self.beto.pk})
        self.assertTrue(ProfesorMateria.objects.filter(profesor=self.beto, materia=self.esp).exists())

    def test_no_duplica_si_ya_estaba_habilitado(self):
        habilitar(self.beto, [self.esp])
        self.client.post(reverse('profesores:asignar'), {'asignacion': [self.esp_p1.pk], 'profesor': self.beto.pk})
        self.assertEqual(ProfesorMateria.objects.filter(profesor=self.beto, materia=self.esp).count(), 1)

    def test_quitar_al_profesor_no_lo_deshabilita(self):
        self.client.post(reverse('profesores:asignar'), {'asignacion': [self.esp_p1.pk], 'profesor': self.beto.pk})
        self.client.post(reverse('profesores:asignar'), {'asignacion': [self.esp_p1.pk], 'profesor': ''})
        self.assertTrue(ProfesorMateria.objects.filter(profesor=self.beto, materia=self.esp).exists())
