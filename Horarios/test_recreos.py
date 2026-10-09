"""Recreos: se agregan a uno o varios grupos a la vez (cada día con su hora), ocupan el horario del grupo y se ven en
la cuadrícula; cada uno se edita o se quita por separado."""
from datetime import time

from django.urls import reverse

from Alumnos.models import HorarioMateria, Recreo
from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase, ciclo_actual_de_prueba, ciclo_cerrado_de_prueba, crear_grado

from .tests import asignar, bloque


def horas(dias, inicio='10:30', fin='11:00'):
    datos = {'dias': list(dias)}
    for dia in dias:
        datos.update({f'inicio_{dia}': inicio, f'fin_{dia}': fin})
    return datos


def recreo(grado, ciclo, dia=0, inicio=(10, 30), fin=(11, 0), nombre='Recreo'):
    return Recreo.objects.create(grado=grado, ciclo=ciclo, nombre=nombre, dia_semana=dia, hora_inicio=time(*inicio), hora_fin=time(*fin))


class RecreoTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba('2026-2027')
        self.cerrado = ciclo_cerrado_de_prueba('2025-2026')
        self.primero, self.segundo = crear_grado('PRIMARIA', 1), crear_grado('PRIMARIA', 2)
        self.url = f"{reverse('horarios:recreo_crear')}?ciclo={self.ciclo.pk}"

    def del_grado(self, grado):
        return f"{reverse('horarios:grado', args=[grado.pk])}?ciclo={self.ciclo.pk}"


@PRUEBAS
class AgregarRecreoTests(RecreoTestCase):
    def test_se_agrega_a_varios_grupos_a_la_vez(self):
        respuesta = self.client.post(self.url, {'grados': [self.primero.pk, self.segundo.pk], 'nombre': 'Recreo', **horas(range(5))}, follow=True)
        self.assertRedirects(respuesta, f"{reverse('horarios:lista')}?ciclo={self.ciclo.pk}")
        self.assertEqual(Recreo.objects.filter(ciclo=self.ciclo, grado=self.primero).count(), 5)
        self.assertEqual(Recreo.objects.filter(ciclo=self.ciclo, grado=self.segundo).count(), 5)
        self.assertContains(respuesta, 'Se agregó «Recreo» a 1° Primaria, 2° Primaria: Lun, Mar, Mié, Jue, Vie · 10:30–11:00.')

    def test_cada_dia_con_su_hora(self):
        self.client.post(self.url, {
            'grados': [self.primero.pk], 'nombre': 'Recreo', 'dias': [0, 4],
            'inicio_0': '10:30', 'fin_0': '11:00', 'inicio_4': '11:00', 'fin_4': '11:20',
        })
        self.assertEqual(
            sorted(Recreo.objects.values_list('dia_semana', 'hora_inicio', 'hora_fin')),
            [(0, time(10, 30), time(11)), (4, time(11), time(11, 20))],
        )

    def test_desde_el_horario_de_un_grado_lo_trae_marcado_con_los_dias_habiles_y_regresa_a_el(self):
        url = f'{self.url}&grado={self.primero.pk}'
        respuesta = self.client.get(url)
        self.assertEqual(respuesta.context['form']['grados'].value(), [self.primero.pk])
        html = respuesta.content.decode()
        for dia in range(5):
            self.assertIn(f'data-horario-dia="{dia}">', html)                # de lunes a viernes ya marcados
        self.assertIn('data-horario-dia="5" hidden>', html)
        respuesta = self.client.post(url, {'grados': [self.primero.pk], 'nombre': 'Recreo', **horas([0])})
        self.assertRedirects(respuesta, self.del_grado(self.primero), fetch_redirect_response=False)

    def test_pide_grupos_nombre_dias_y_las_horas_de_cada_dia(self):
        respuesta = self.client.post(self.url, {'nombre': ''})
        self.assertEqual(set(respuesta.context['form'].errors), {'grados', 'nombre', 'dias'})
        respuesta = self.client.post(self.url, {'grados': [self.primero.pk], 'nombre': 'Recreo', 'dias': [2], 'inicio_2': '11:00', 'fin_2': '10:30'})
        self.assertContains(respuesta, 'La hora de fin del miércoles debe ser posterior a la de inicio.')
        self.assertFalse(Recreo.objects.exists())

    def test_no_se_empalma_con_una_materia_de_algun_grupo_y_entonces_no_se_guarda_en_ninguno(self):
        bloque(asignar('MAT', 'Matemáticas', self.segundo, self.ciclo), 0, (10, 0), (11, 0))
        respuesta = self.client.post(self.url, {'grados': [self.primero.pk, self.segundo.pk], 'nombre': 'Recreo', **horas([0, 1])})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'En 2° Primaria: Se empalma con Matemáticas (lunes 10:00–11:00)')
        self.assertEqual(list(respuesta.context['form'].errors), ['inicio_0'])
        self.assertFalse(Recreo.objects.exists())

    def test_no_se_empalma_con_otro_recreo_del_grupo(self):
        recreo(self.primero, self.ciclo, 0, (10, 0), (10, 45))
        respuesta = self.client.post(self.url, {'grados': [self.primero.pk], 'nombre': 'Recreo largo', **horas([0])})
        self.assertContains(respuesta, 'Se empalma con el recreo (lunes 10:00–10:45): a esa hora el grupo está en recreo.')
        self.assertEqual(Recreo.objects.count(), 1)

    def test_lo_de_otro_ciclo_u_horas_contiguas_no_estorba(self):
        recreo(self.primero, self.cerrado, 0)
        bloque(asignar('MAT', 'Matemáticas', self.primero, self.ciclo), 0, (9, 30), (10, 30))
        self.client.post(self.url, {'grados': [self.primero.pk], 'nombre': 'Recreo', **horas([0])})
        self.assertEqual(Recreo.objects.filter(ciclo=self.ciclo).count(), 1)

    def test_solo_ofrece_grados_activos(self):
        crear_grado('PRIMARIA', 3, activo=False)
        grados = self.client.get(self.url).context['form'].fields['grados'].queryset
        self.assertEqual(list(grados), [self.primero, self.segundo])

    def test_un_ciclo_cerrado_no_se_modifica(self):
        url = f"{reverse('horarios:recreo_crear')}?ciclo={self.cerrado.pk}"
        respuesta = self.client.post(url, {'grados': [self.primero.pk], 'nombre': 'Recreo', **horas([0])}, follow=True)
        self.assertContains(respuesta, 'está cerrado')
        self.assertFalse(Recreo.objects.exists())


@PRUEBAS
class RecreoEnElHorarioTests(RecreoTestCase):
    def setUp(self):
        super().setUp()
        self.mat = asignar('MAT', 'Matemáticas', self.primero, self.ciclo)
        bloque(self.mat, 0, (8, 0), (9, 0))
        self.recreo = recreo(self.primero, self.ciclo, 0)

    def test_se_ve_en_la_cuadricula_del_grupo(self):
        respuesta = self.client.get(self.del_grado(self.primero))
        celdas = [b for fila in respuesta.context['cuadricula']['filas'] for celda in fila['celdas'] for b in celda]
        self.assertIn(self.recreo, celdas)
        self.assertContains(respuesta, 'slot--recreo')
        self.assertContains(respuesta, 'Todo el grupo')
        self.assertContains(respuesta, reverse('horarios:recreo_editar', args=[self.recreo.pk]))
        self.assertContains(respuesta, 'Recreo: Lun · 10:30–11:00')
        self.assertEqual(respuesta.context['horas_semanales'], '1 h')             # el recreo no cuenta como clase

    def test_el_indice_resume_el_recreo_de_cada_grado(self):
        html = self.client.get(f"{reverse('horarios:lista')}?ciclo={self.ciclo.pk}").content.decode()
        self.assertIn('Recreo: Lun · 10:30–11:00', html)
        self.assertIn('Sin recreo', html)                                     # 2° Primaria todavía no tiene

    def test_una_materia_no_se_puede_poner_en_el_recreo(self):
        url = f"{reverse('horarios:crear', args=[self.primero.pk])}?ciclo={self.ciclo.pk}"
        respuesta = self.client.post(url, {'materia_grado': self.mat.pk, 'dias': [0], 'inicio_0': '10:45', 'fin_0': '11:30'})
        self.assertContains(respuesta, 'Se empalma con el recreo (lunes 10:30–11:00): a esa hora el grupo está en recreo.')
        self.assertEqual(HorarioMateria.objects.count(), 1)

    def test_ni_moviendo_una_clase_a_esa_hora(self):
        clase = HorarioMateria.objects.get()
        respuesta = self.client.post(reverse('horarios:editar', args=[clase.pk]), {
            'materia_grado': self.mat.pk, 'dia_semana': 0, 'hora_inicio': '10:30', 'hora_fin': '11:30',
        })
        self.assertContains(respuesta, 'a esa hora el grupo está en recreo')

    def test_quien_solo_consulta_no_puede_agregarlo(self):
        self.con_permisos('view_horariomateria', 'view_grado')
        self.assertNotContains(self.client.get(self.del_grado(self.primero)), reverse('horarios:recreo_crear'))
        self.assertEqual(self.client.get(self.url).status_code, 403)


@PRUEBAS
class EditarYQuitarRecreoTests(RecreoTestCase):
    def setUp(self):
        super().setUp()
        self.recreo = recreo(self.primero, self.ciclo, 0)
        self.url_editar = reverse('horarios:recreo_editar', args=[self.recreo.pk])

    def datos(self, **cambios):
        datos = {'nombre': 'Recreo', 'dia_semana': 0, 'hora_inicio': '10:30', 'hora_fin': '11:00'}
        datos.update(cambios)
        return datos

    def test_cambia_su_hora_y_regresa_al_horario_del_grupo(self):
        respuesta = self.client.post(self.url_editar, self.datos(hora_inicio='11:00', hora_fin='11:30', nombre='Recreo largo'), follow=True)
        self.assertRedirects(respuesta, self.del_grado(self.primero))
        self.recreo.refresh_from_db()
        self.assertEqual((self.recreo.nombre, self.recreo.hora_inicio, self.recreo.hora_fin), ('Recreo largo', time(11), time(11, 30)))
        self.assertContains(respuesta, 'Se actualizó «Recreo largo» de 1° Primaria (lunes).')

    def test_puede_quedarse_a_la_misma_hora_pero_no_empalmarse_con_una_clase(self):
        self.assertEqual(self.client.post(self.url_editar, self.datos()).status_code, 302)     # no choca consigo mismo
        bloque(asignar('MAT', 'Matemáticas', self.primero, self.ciclo), 1, (10, 0), (11, 0))
        respuesta = self.client.post(self.url_editar, self.datos(dia_semana=1))
        self.assertContains(respuesta, 'Se empalma con Matemáticas (martes 10:00–11:00)')

    def test_la_hora_de_fin_debe_ser_posterior(self):
        respuesta = self.client.post(self.url_editar, self.datos(hora_inicio='11:00', hora_fin='10:00'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'La hora de inicio debe ser anterior a la hora de fin.')

    def test_se_quita_solo_ese_dia_de_ese_grupo(self):
        otro_dia = recreo(self.primero, self.ciclo, 1)
        respuesta = self.client.post(reverse('horarios:recreo_eliminar', args=[self.recreo.pk]), follow=True)
        self.assertRedirects(respuesta, self.del_grado(self.primero))
        self.assertEqual(list(Recreo.objects.all()), [otro_dia])
        self.assertContains(respuesta, 'Se quitó «Recreo» de 1° Primaria (lunes 10:30–11:00).')

    def test_quitar_pide_post(self):
        self.assertEqual(self.client.get(reverse('horarios:recreo_eliminar', args=[self.recreo.pk])).status_code, 405)

    def test_un_ciclo_cerrado_no_se_modifica(self):
        viejo = recreo(self.primero, self.cerrado, 2)
        self.client.post(reverse('horarios:recreo_editar', args=[viejo.pk]), self.datos(dia_semana=3))
        self.client.post(reverse('horarios:recreo_eliminar', args=[viejo.pk]))
        viejo.refresh_from_db()
        self.assertEqual(viejo.dia_semana, 2)
