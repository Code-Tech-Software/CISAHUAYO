"""Quién puede impartir cada materia: su perfil, altas y bajas de esa lista y el orden del selector de profesor."""
from django.contrib.admin.models import LogEntry
from django.urls import reverse

from Alumnos.docentes import habilitar
from Alumnos.models import ProfesorMateria
from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase, ciclo_actual_de_prueba, crear_grado, crear_profesor
from Profesores.tests import asignar, crear_materia


@PRUEBAS
class HabilitarProfesoresTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.mat = crear_materia('MAT', 'Matemáticas')
        self.marta = crear_profesor(nombre='Marta', apellido_paterno='Rangel')
        self.beto = crear_profesor(nombre='Beto', apellido_paterno='Aguilar', telefono='3530000002')
        self.url = reverse('materias:habilitar', args=[self.mat.pk])

    def test_agrega_a_los_profesores_elegidos_y_deja_bitacora_en_cada_uno_y_en_la_materia(self):
        respuesta = self.client.post(self.url, {'profesor': [self.marta.pk, self.beto.pk]})
        self.assertRedirects(respuesta, f'{self.mat.get_absolute_url()}#profesores', fetch_redirect_response=False)
        self.assertEqual(ProfesorMateria.objects.filter(materia=self.mat).count(), 2)
        self.assertEqual(LogEntry.objects.count(), 3)
        self.assertTrue(LogEntry.objects.filter(object_id=str(self.mat.pk), change_message__startswith='Pueden impartirla ahora').exists())

    def test_no_repite_y_lo_avisa(self):
        habilitar(self.marta, [self.mat])
        respuesta = self.client.post(self.url, {'profesor': [self.marta.pk]}, follow=True)
        self.assertContains(respuesta, 'ya podían impartirla')
        self.assertEqual(ProfesorMateria.objects.count(), 1)
        self.assertEqual(LogEntry.objects.count(), 0)

    def test_solo_habilita_a_profesores_activos(self):
        self.beto.estatus = 'INACTIVO'
        self.beto.save()
        self.client.post(self.url, {'profesor': [self.marta.pk, self.beto.pk]})
        self.assertEqual(list(ProfesorMateria.objects.values_list('profesor_id', flat=True)), [self.marta.pk])

    def test_pide_al_menos_un_profesor(self):
        self.assertContains(self.client.post(self.url, {}, follow=True), 'Elige al menos un profesor')

    def test_una_materia_de_baja_no_se_modifica(self):
        self.mat.activa = False
        self.mat.save()
        respuesta = self.client.post(self.url, {'profesor': [self.marta.pk]}, follow=True)
        self.assertContains(respuesta, 'está dada de baja')
        self.assertEqual(ProfesorMateria.objects.count(), 0)

    def test_pide_permiso_de_editar_profesores_y_solo_acepta_post(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.con_permisos('view_materia', 'view_profesor')
        self.assertEqual(self.client.post(self.url, {'profesor': [self.marta.pk]}).status_code, 403)
        self.con_permisos('change_profesor')
        self.assertEqual(self.client.post(self.url, {'profesor': [self.marta.pk]}).status_code, 302)


@PRUEBAS
class DeshabilitarProfesoresTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.mat = crear_materia('MAT', 'Matemáticas')
        self.marta = crear_profesor(nombre='Marta', apellido_paterno='Rangel')
        self.beto = crear_profesor(nombre='Beto', apellido_paterno='Aguilar', telefono='3530000002')
        habilitar(self.marta, [self.mat])
        habilitar(self.beto, [self.mat])
        self.url = reverse('materias:deshabilitar', args=[self.mat.pk])

    def test_quita_solo_al_pedido(self):
        self.client.post(self.url, {'profesor': [self.marta.pk]})
        self.assertEqual(list(ProfesorMateria.objects.values_list('profesor_id', flat=True)), [self.beto.pk])
        self.assertTrue(LogEntry.objects.filter(object_id=str(self.marta.pk), change_message__startswith='Ya no está habilitado').exists())

    def test_avisa_si_todavia_la_imparte_y_no_se_la_quita(self):
        asignacion = asignar(self.mat, crear_grado('PRIMARIA', 1), self.ciclo, profesor=self.marta)
        respuesta = self.client.post(self.url, {'profesor': [self.marta.pk]}, follow=True)
        self.assertContains(respuesta, 'Siguen impartiéndola en 1 grupo')
        asignacion.refresh_from_db()
        self.assertEqual(asignacion.profesor, self.marta)

    def test_pide_a_alguien_de_la_lista(self):
        otro = crear_profesor(nombre='Otro', apellido_paterno='Zepeda', telefono='3530000003')
        self.assertContains(self.client.post(self.url, {'profesor': [otro.pk]}, follow=True), 'Elige al menos un profesor')
        self.assertEqual(ProfesorMateria.objects.count(), 2)

    def test_pide_permiso_de_editar_profesores(self):
        self.con_permisos('view_materia')
        self.assertEqual(self.client.post(self.url, {'profesor': [self.marta.pk]}).status_code, 403)


@PRUEBAS
class PerfilDeLaMateriaTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.mat = crear_materia('MAT', 'Matemáticas')
        self.marta = crear_profesor(nombre='Marta', apellido_paterno='Rangel')
        self.beto = crear_profesor(nombre='Beto', apellido_paterno='Aguilar', telefono='3530000002')
        self.url = reverse('materias:detalle', args=[self.mat.pk])

    def test_lista_a_los_habilitados_con_sus_grupos_del_ciclo(self):
        habilitar(self.marta, [self.mat])
        habilitar(self.beto, [self.mat])
        asignar(self.mat, crear_grado('PRIMARIA', 1), self.ciclo, profesor=self.marta)
        asignar(self.mat, crear_grado('PRIMARIA', 2), self.ciclo, profesor=self.marta)
        respuesta = self.client.get(self.url)
        grados = {p.pk: len(p.grados_del_ciclo) for p in respuesta.context['habilitados']}
        self.assertEqual(grados, {self.marta.pk: 2, self.beto.pk: 0})
        self.assertContains(respuesta, '2 grupos')
        self.assertContains(respuesta, 'No la imparte')
        self.assertEqual(respuesta.context['sin_habilitar'], [])

    def test_avisa_de_quien_la_imparte_sin_estar_en_la_lista(self):
        habilitar(self.marta, [self.mat])
        asignar(self.mat, crear_grado('PRIMARIA', 1), self.ciclo, profesor=self.beto)
        asignar(self.mat, crear_grado('PRIMARIA', 2), self.ciclo, profesor=self.beto)
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.context['sin_habilitar'], [self.beto])   # una sola vez aunque la dé en dos grados
        self.assertContains(respuesta, 'sin estar en esta lista')

    def test_el_modal_ofrece_solo_a_los_activos_que_faltan(self):
        habilitar(self.marta, [self.mat])
        crear_profesor(nombre='Vieja', apellido_paterno='Zepeda', telefono='3530000003', estatus='INACTIVO')
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.context['profesores_por_habilitar'], [self.beto])

    def test_el_selector_de_profesor_lleva_los_habilitados_primero(self):
        habilitar(self.marta, [self.mat])
        asignar(self.mat, crear_grado('PRIMARIA', 1), self.ciclo)
        respuesta = self.client.get(self.url, {'ciclo': self.ciclo.pk})
        self.assertContains(respuesta, f'data-habilitados="{self.marta.pk}"')

    def test_sin_permiso_de_ver_profesores_no_se_muestra_la_lista(self):
        habilitar(self.marta, [self.mat])
        self.con_permisos('view_materia', 'view_materiagrado')
        respuesta = self.client.get(self.url)
        self.assertNotContains(respuesta, 'Profesores que pueden impartirla')

    def test_sin_permiso_de_editar_profesores_no_hay_botones(self):
        habilitar(self.marta, [self.mat])
        self.con_permisos('view_materia', 'view_profesor')
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, 'Profesores que pueden impartirla')
        self.assertNotContains(respuesta, reverse('materias:deshabilitar', args=[self.mat.pk]))
        self.assertNotContains(respuesta, 'modal-habilitar-profesores')


@PRUEBAS
class SelectorDelGradoTests(BaseTestCase):
    def test_los_botones_de_asignar_llevan_los_habilitados_de_cada_materia(self):
        ciclo = ciclo_actual_de_prueba()
        mat, esp = crear_materia('MAT', 'Matemáticas'), crear_materia('ESP', 'Español')
        marta = crear_profesor(nombre='Marta', apellido_paterno='Rangel')
        habilitar(marta, [mat])
        grado = crear_grado('PRIMARIA', 1)
        asignar(mat, grado, ciclo)
        asignar(esp, grado, ciclo)
        respuesta = self.client.get(reverse('grados:detalle', args=[grado.pk]), {'ciclo': ciclo.pk})
        self.assertContains(respuesta, f'data-habilitados="{marta.pk}"', count=1)
        self.assertContains(respuesta, 'data-habilitados=""', count=1)
