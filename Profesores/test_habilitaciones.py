"""Las materias que puede impartir cada profesor: perfil, altas y bajas de la lista y tope de horas por semana."""
from django.contrib.admin.models import LogEntry
from django.urls import reverse

from Alumnos.docentes import habilitar
from Alumnos.models import ProfesorMateria
from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase, ciclo_actual_de_prueba, crear_grado, crear_profesor
from Profesores.tests import asignar, crear_materia, datos_profesor


@PRUEBAS
class HabilitarTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.profesor = crear_profesor()
        self.mat = crear_materia('MAT', 'Matemáticas')
        self.esp = crear_materia('ESP', 'Español')
        self.url = reverse('profesores:habilitar', args=[self.profesor.pk])

    def test_agrega_las_materias_elegidas_y_deja_bitacora(self):
        respuesta = self.client.post(self.url, {'materia': [self.mat.pk, self.esp.pk]})
        self.assertRedirects(respuesta, f'{self.profesor.get_absolute_url()}#habilitado', fetch_redirect_response=False)
        self.assertEqual(ProfesorMateria.objects.filter(profesor=self.profesor).count(), 2)
        entrada = LogEntry.objects.get()
        self.assertEqual(entrada.object_id, str(self.profesor.pk))
        self.assertIn('Habilitado para impartir: ', entrada.change_message)
        self.assertIn('Matemáticas', entrada.change_message)

    def test_no_repite_lo_que_ya_estaba_y_lo_avisa(self):
        habilitar(self.profesor, [self.mat])
        respuesta = self.client.post(self.url, {'materia': [self.mat.pk]}, follow=True)
        self.assertContains(respuesta, 'ya estaban en su lista')
        self.assertEqual(ProfesorMateria.objects.count(), 1)
        self.assertEqual(LogEntry.objects.count(), 0)

    def test_pide_al_menos_una_materia(self):
        respuesta = self.client.post(self.url, {}, follow=True)
        self.assertContains(respuesta, 'Elige al menos una materia')

    def test_ignora_materias_de_baja_y_valores_raros(self):
        baja = crear_materia('OLD', 'Antigua', activa=False)
        self.client.post(self.url, {'materia': [baja.pk, 'abc', '99999']})
        self.assertEqual(ProfesorMateria.objects.count(), 0)

    def test_un_profesor_de_baja_no_se_modifica(self):
        self.profesor.estatus = 'INACTIVO'
        self.profesor.save()
        respuesta = self.client.post(self.url, {'materia': [self.mat.pk]}, follow=True)
        self.assertContains(respuesta, 'está dado de baja')
        self.assertEqual(ProfesorMateria.objects.count(), 0)

    def test_solo_acepta_post_y_pide_permiso_de_editar_profesores(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.con_permisos('view_profesor')
        self.assertEqual(self.client.post(self.url, {'materia': [self.mat.pk]}).status_code, 403)
        self.con_permisos('view_profesor', 'change_profesor')
        self.assertEqual(self.client.post(self.url, {'materia': [self.mat.pk]}).status_code, 302)

    def test_next_externo_se_descarta(self):
        respuesta = self.client.post(self.url, {'materia': [self.mat.pk], 'next': 'https://malo.example/'})
        self.assertTrue(respuesta['Location'].startswith(self.profesor.get_absolute_url()))


@PRUEBAS
class DeshabilitarTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.profesor = crear_profesor()
        self.mat = crear_materia('MAT', 'Matemáticas')
        self.esp = crear_materia('ESP', 'Español')
        habilitar(self.profesor, [self.mat, self.esp])
        self.url = reverse('profesores:deshabilitar', args=[self.profesor.pk])

    def test_quita_solo_lo_pedido_y_deja_bitacora(self):
        self.client.post(self.url, {'materia': [self.mat.pk]})
        self.assertEqual(list(ProfesorMateria.objects.values_list('materia__clave', flat=True)), ['ESP'])
        self.assertIn('Ya no está habilitado para impartir: Matemáticas', LogEntry.objects.get().change_message)

    def test_avisa_si_todavia_imparte_esa_materia_y_no_se_la_quita(self):
        asignacion = asignar(self.mat, crear_grado('PRIMARIA', 1), self.ciclo, profesor=self.profesor)
        respuesta = self.client.post(self.url, {'materia': [self.mat.pk]}, follow=True)
        self.assertContains(respuesta, 'Sigue impartiendo 1 grupo')
        asignacion.refresh_from_db()
        self.assertEqual(asignacion.profesor, self.profesor)

    def test_pide_una_materia_de_su_lista(self):
        otra = crear_materia('HIS', 'Historia')
        respuesta = self.client.post(self.url, {'materia': [otra.pk]}, follow=True)
        self.assertContains(respuesta, 'Elige al menos una materia')
        self.assertEqual(ProfesorMateria.objects.count(), 2)

    def test_pide_permiso_de_editar_profesores(self):
        self.con_permisos('view_profesor')
        self.assertEqual(self.client.post(self.url, {'materia': [self.mat.pk]}).status_code, 403)
        self.assertEqual(ProfesorMateria.objects.count(), 2)


@PRUEBAS
class PerfilConHabilitacionesTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.profesor = crear_profesor()
        self.mat = crear_materia('MAT', 'Matemáticas')
        self.esp = crear_materia('ESP', 'Español')
        self.url = reverse('profesores:detalle', args=[self.profesor.pk])

    def test_lista_lo_que_puede_impartir_y_en_cuantos_grupos_lo_imparte(self):
        habilitar(self.profesor, [self.mat, self.esp])
        asignar(self.mat, crear_grado('PRIMARIA', 1), self.ciclo, profesor=self.profesor)
        asignar(self.mat, crear_grado('PRIMARIA', 2), self.ciclo, profesor=self.profesor)
        respuesta = self.client.get(self.url)
        habilitadas = {h['materia'].clave: h['grados'] for h in respuesta.context['habilitadas']}
        self.assertEqual(len(habilitadas['MAT']), 2)
        self.assertEqual(habilitadas['ESP'], [])
        self.assertContains(respuesta, 'Imparte en 2 grupos')
        self.assertContains(respuesta, 'Sin grupos asignados')
        self.assertEqual(respuesta.context['sin_habilitar'], [])

    def test_avisa_de_lo_que_imparte_sin_tenerlo_en_su_lista(self):
        asignar(self.mat, crear_grado('PRIMARIA', 1), self.ciclo, profesor=self.profesor)
        respuesta = self.client.get(self.url)
        self.assertEqual([m.clave for m in respuesta.context['sin_habilitar']], ['MAT'])
        self.assertContains(respuesta, 'Agregarlas a su lista')

    def test_el_modal_ofrece_solo_las_materias_que_faltan(self):
        habilitar(self.profesor, [self.mat])
        crear_materia('OLD', 'Antigua', activa=False)
        respuesta = self.client.get(self.url)
        self.assertEqual([m.clave for m in respuesta.context['materias_por_habilitar']], ['ESP'])
        self.assertContains(respuesta, 'id="modal-habilitar"')

    def test_sin_permiso_de_editar_no_hay_botones_de_agregar_ni_quitar(self):
        habilitar(self.profesor, [self.mat])
        self.con_permisos('view_profesor')
        respuesta = self.client.get(self.url)
        self.assertNotContains(respuesta, 'profesores:habilitar')
        self.assertNotContains(respuesta, reverse('profesores:deshabilitar', args=[self.profesor.pk]))
        self.assertNotContains(respuesta, 'modal-habilitar')


@PRUEBAS
class BusquedaPorHabilitacionTests(BaseTestCase):
    def test_el_listado_encuentra_a_quien_puede_impartir_una_materia_aunque_no_la_de_este_ciclo(self):
        marta = crear_profesor(nombre='Marta', apellido_paterno='Rangel')
        crear_profesor(nombre='Beto', apellido_paterno='Aguilar', telefono='3530000002')
        habilitar(marta, [crear_materia('FIS', 'Física')])
        respuesta = self.client.get(reverse('profesores:lista'), {'q': 'física'})
        self.assertEqual([str(p) for p in respuesta.context['pagina']], [str(marta)])

    def test_no_duplica_al_profesor_con_varias_materias_que_coinciden(self):
        marta = crear_profesor(nombre='Marta', apellido_paterno='Rangel')
        habilitar(marta, [crear_materia('FIS', 'Física I'), crear_materia('FI2', 'Física II')])
        respuesta = self.client.get(reverse('profesores:lista'), {'q': 'física'})
        self.assertEqual(len(respuesta.context['pagina']), 1)


@PRUEBAS
class HorasMaximasTests(BaseTestCase):
    def enviar(self, valor):
        return self.client.post(reverse('profesores:crear'), datos_profesor(horas_maximas=valor))

    def test_es_opcional(self):
        self.assertEqual(self.enviar('').status_code, 302)
        from Alumnos.models import Profesor
        self.assertIsNone(Profesor.objects.get().horas_maximas)

    def test_se_guarda(self):
        self.enviar('25')
        from Alumnos.models import Profesor
        self.assertEqual(Profesor.objects.get().horas_maximas, 25)

    def test_pide_entre_1_y_60_horas(self):
        for valor in ('0', '61', '-3'):
            with self.subTest(valor=valor):
                self.assertEqual(self.enviar(valor).status_code, 200)
        from Alumnos.models import Profesor
        self.assertEqual(Profesor.objects.count(), 0)

    def test_el_perfil_muestra_el_tope_junto_a_las_horas(self):
        profesor = crear_profesor(horas_maximas=20)
        self.assertContains(self.client.get(profesor.get_absolute_url()), 'de 20 h')
