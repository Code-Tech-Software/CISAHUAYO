"""El listado de tutores: tarjetas de sus estudiantes con enlace al perfil y el botón «Dar de baja»."""
import re

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    crear_alumno,
    crear_grado,
    crear_tutor,
    inscribir,
    vincular,
)

from Alumnos.models import Tutor


def tarjetas(html):
    """Las etiquetas <a class="student-chip …"> del listado."""
    return re.findall(r'<a class="student-chip[^"]*"[^>]*>', html)


def botones_de_baja(html):
    return re.findall(r'<button[^>]*data-baja\b[^>]*>', html)


@PRUEBAS
class TarjetasDeEstudiantesTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.grado = crear_grado('PRIMARIA', 4)
        self.tutor = crear_tutor(nombre='Rosa', apellido_paterno='Mora')
        self.luis = crear_alumno(nombre='Luis', apellido_paterno='Pérez', referencia='R1')
        self.ana = crear_alumno(nombre='Ana', apellido_paterno='García', referencia='R2')
        vincular(self.tutor, self.luis, parentesco='MADRE', tutor_principal=True)
        vincular(self.tutor, self.ana, parentesco='MADRE')
        inscribir(self.luis, self.ciclo, self.grado)
        self.lista = reverse('tutores:lista')

    def test_cada_estudiante_es_una_tarjeta_que_lleva_a_su_perfil(self):
        html = self.client.get(self.lista).content.decode()
        enlaces = tarjetas(html)
        self.assertEqual(len(enlaces), 2)
        for estudiante in (self.luis, self.ana):
            tarjeta = next(a for a in enlaces if f'href="{estudiante.get_absolute_url()}"' in a)
            self.assertIn(f'aria-label="Ver perfil de {estudiante}"', tarjeta)

    def test_la_tarjeta_muestra_nombre_parentesco_y_grado_actual(self):
        html = self.client.get(self.lista).content.decode()
        tarjeta_de_luis = re.search(r'<a class="student-chip"[^>]*href="' + self.luis.get_absolute_url() + r'".*?</a>', html, re.S).group(0)
        self.assertIn('Luis Pérez', tarjeta_de_luis)
        self.assertIn('Madre · 4° Primaria', tarjeta_de_luis)
        tarjeta_de_ana = re.search(r'<a class="student-chip"[^>]*href="' + self.ana.get_absolute_url() + r'".*?</a>', html, re.S).group(0)
        self.assertIn('Madre · Sin inscripción', tarjeta_de_ana)

    def test_las_tarjetas_traen_las_iniciales_o_la_foto(self):
        html = self.client.get(self.lista).content.decode()
        self.assertIn('avatar--sm', html)
        self.assertIn('>LP<', html)

    def test_solo_cuentan_los_estudiantes_vigentes(self):
        baja = crear_alumno(nombre='Beto', apellido_paterno='Baja', referencia='R3', estatus='BAJA')
        sin_vinculo = crear_alumno(nombre='Cora', apellido_paterno='Suelta', referencia='R4')
        vincular(self.tutor, baja)
        vincular(self.tutor, sin_vinculo, activo=False)
        html = self.client.get(self.lista).content.decode()
        self.assertEqual(len(tarjetas(html)), 2)
        self.assertNotIn('Beto Baja', html)
        self.assertNotIn('Cora Suelta', html)

    def test_con_mas_de_tres_se_resumen_en_un_enlace_al_perfil_del_tutor(self):
        for n in range(3):
            vincular(self.tutor, crear_alumno(nombre=f'Extra{n}', apellido_paterno='Mas', referencia=f'X{n}'))
        html = self.client.get(self.lista).content.decode()
        self.assertEqual(len(tarjetas(html)), 4)                      # tres tarjetas y «+2 más»
        mas = re.search(r'<a class="student-chip student-chip--more" href="([^"]+)">(.*?)</a>', html, re.S)
        self.assertEqual(mas.group(1), self.tutor.get_absolute_url() + '#alumnos')
        self.assertEqual(mas.group(2), '+2 más')

    def test_sin_estudiantes_vigentes_lo_avisa(self):
        crear_tutor(nombre='Sola', apellido_paterno='Persona', telefono='3539998877')
        html = self.client.get(self.lista).content.decode()
        self.assertIn('Sin estudiantes vigentes', html)

    def test_sin_permiso_para_ver_estudiantes_las_tarjetas_no_son_enlaces(self):
        self.con_permisos('view_tutor')
        html = self.client.get(self.lista).content.decode()
        enlaces = tarjetas(html)
        self.assertEqual(len(enlaces), 2)
        for tarjeta in enlaces:
            self.assertNotIn('href=', tarjeta)
        self.assertIn('Luis Pérez', html)

    def test_en_el_filtro_de_bajas_tambien_se_ven(self):
        Tutor.objects.filter(pk=self.tutor.pk).update(estatus='INACTIVO')
        html = self.client.get(self.lista + '?estatus=INACTIVO').content.decode()
        self.assertEqual(len(tarjetas(html)), 2)

    def test_las_consultas_no_crecen_con_los_tutores_ni_con_los_estudiantes(self):
        def consultas():
            with CaptureQueriesContext(connection) as capturadas:
                self.assertEqual(self.client.get(self.lista, {'por_pagina': 50}).status_code, 200)
            return len(capturadas)

        antes = consultas()
        for n in range(12):
            tutor = crear_tutor(nombre=f'Tutor{n}', apellido_paterno='Relleno', telefono=f'35300000{n:02d}')
            for m in range(2):
                alumno = crear_alumno(nombre=f'Est{n}{m}', apellido_paterno='Relleno', referencia=f'T{n}-{m}')
                vincular(tutor, alumno)
                inscribir(alumno, self.ciclo, self.grado)
        self.assertEqual(consultas(), antes)


@PRUEBAS
class BajaDesdeElListadoTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.rosa = crear_tutor(nombre='Rosa', apellido_paterno='Mora', telefono='3531112233')
        self.jorge = crear_tutor(nombre='Jorge', apellido_paterno='Pérez', telefono='3534445566')
        self.lista = reverse('tutores:lista')

    def boton_de(self, html, tutor):
        return next(b for b in botones_de_baja(html) if f'data-action="{reverse("tutores:baja", args=[tutor.pk])}"' in b)

    def test_cada_fila_trae_su_boton_de_baja_con_la_ruta_y_el_nombre(self):
        html = self.client.get(self.lista).content.decode()
        self.assertEqual(len(botones_de_baja(html)), 2)
        for tutor in (self.rosa, self.jorge):
            boton = self.boton_de(html, tutor)
            self.assertIn(f'data-nombre="{tutor}"', boton)
            self.assertIn('data-modal-open="modal-baja"', boton)
            self.assertIn(f'aria-label="Dar de baja a {tutor}"', boton)

    def test_hay_una_sola_ventana_de_confirmacion_que_envia_por_post(self):
        html = self.client.get(self.lista).content.decode()
        self.assertEqual(html.count('id="modal-baja"'), 1)
        ventana = re.search(r'<dialog[^>]*id="modal-baja".*?</dialog>', html, re.S).group(0)
        for texto in ('method="post"', 'csrfmiddlewaretoken', 'data-baja-form', 'data-baja-aviso', 'baja lógica'):
            self.assertIn(texto, ventana)
        self.assertIn('js/baja-lista.js', html)

    def test_dar_de_baja_desde_el_listado_lo_oculta_y_vuelve_al_listado(self):
        respuesta = self.client.post(reverse('tutores:baja', args=[self.rosa.pk]), follow=True)
        self.assertRedirects(respuesta, self.lista)
        self.assertContains(respuesta, 'Rosa Mora fue dado de baja')
        self.rosa.refresh_from_db()
        self.assertEqual(self.rosa.estatus, 'INACTIVO')
        self.assertEqual(len(botones_de_baja(respuesta.content.decode())), 1)

    def test_en_el_filtro_de_bajas_se_ofrece_reactivar_y_no_dar_de_baja(self):
        Tutor.objects.filter(pk=self.rosa.pk).update(estatus='INACTIVO')
        html = self.client.get(self.lista + '?estatus=INACTIVO').content.decode()
        self.assertEqual(botones_de_baja(html), [])
        self.assertIn(reverse('tutores:reactivar', args=[self.rosa.pk]), html)

    def test_solo_lo_ve_quien_puede_dar_de_baja(self):
        self.con_permisos('view_tutor', 'change_tutor')
        html = self.client.get(self.lista).content.decode()
        self.assertEqual(botones_de_baja(html), [])
        self.assertNotIn('modal-baja', html)
        self.con_permisos('view_tutor', 'delete_tutor')
        self.assertEqual(len(botones_de_baja(self.client.get(self.lista).content.decode())), 2)

    # --- el aviso de los estudiantes que se quedarían sin tutor ----------------------------------------
    def test_avisa_cuantos_estudiantes_se_quedarian_sin_tutor(self):
        compartido = crear_alumno(referencia='R1', nombre='Luis')
        solo_de_rosa = crear_alumno(referencia='R2', nombre='Ana')
        otro_solo_de_rosa = crear_alumno(referencia='R3', nombre='Beto')
        vincular(self.rosa, compartido, tutor_principal=True)
        vincular(self.jorge, compartido)
        vincular(self.rosa, solo_de_rosa)
        vincular(self.rosa, otro_solo_de_rosa)
        html = self.client.get(self.lista).content.decode()
        self.assertIn('data-aviso="2 estudiantes se quedarán sin ningún tutor vigente', self.boton_de(html, self.rosa))
        self.assertIn('data-aviso=""', self.boton_de(html, self.jorge))      # Luis conserva a Rosa

    def test_en_singular(self):
        vincular(self.rosa, crear_alumno(referencia='R1'))
        html = self.client.get(self.lista).content.decode()
        self.assertIn('data-aviso="1 estudiante se quedará sin ningún tutor vigente', self.boton_de(html, self.rosa))

    def test_otro_tutor_dado_de_baja_o_un_vinculo_inactivo_no_cuentan_como_otro_tutor(self):
        luis = crear_alumno(referencia='R1')
        vincular(self.rosa, luis)
        inactivo = crear_tutor(nombre='Inés', apellido_paterno='Baja', telefono='3537778899', estatus='INACTIVO')
        vincular(inactivo, luis)
        vincular(self.jorge, luis, activo=False)
        html = self.client.get(self.lista).content.decode()
        self.assertIn('data-aviso="1 estudiante se quedará', self.boton_de(html, self.rosa))

    def test_un_estudiante_dado_de_baja_no_cuenta(self):
        vincular(self.rosa, crear_alumno(referencia='R1', estatus='BAJA'))
        html = self.client.get(self.lista).content.decode()
        self.assertIn('data-aviso=""', self.boton_de(html, self.rosa))

    def test_el_texto_de_la_ventana_habla_de_estudiantes(self):
        html = self.client.get(self.lista).content.decode()
        ventana = re.search(r'<dialog[^>]*id="modal-baja".*?</dialog>', html, re.S).group(0)
        self.assertNotRegex(ventana, r'(?i)alumn[oa]s?\b')
