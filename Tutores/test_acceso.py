"""Usuario y contraseña de los tutores: se asignan al registrarlos (desde cualquier lugar), un administrador los consulta
en el perfil y quien puede editar los restablece."""
import csv
import importlib
import io
import re

from django.apps import apps
from django.contrib.auth.hashers import check_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.urls import reverse

from Alumnos import importacion as importacion_de_estudiantes
from Alumnos.models import Alumno, Tutor
from Alumnos.tests import datos_alumno, datos_tutores, tutor_nuevo
from Alumnos.utils import base_de_usuario, normalizar_usuario
from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase, crear_alumno, crear_tutor

from . import importacion


def datos_tutor(**cambios):
    datos = {
        'nombre': 'María', 'apellido_paterno': 'López', 'apellido_materno': 'Ruiz', 'curp': '', 'estado_civil': '',
        'religion': '', 'telefono': '353 123 4567', 'telefono_alternativo': '', 'correo_electronico': '',
        'domicilio': '', 'colonia': '', 'ciudad': '', 'estado': '', 'cp': '', 'ocupacion': '', 'lugar_trabajo': '',
        'telefono_trabajo': '', 'observaciones': '', 'usuario': '', 'contrasena_inicial': '',
    }
    datos.update(cambios)
    return datos


# ---------------------------------------------------------------------------
# Cómo se forma el usuario
# ---------------------------------------------------------------------------
class UsuarioSugeridoTests(SimpleTestCase):
    def test_primer_nombre_y_primer_apellido_sin_acentos(self):
        self.assertEqual(base_de_usuario('María José', 'López Ruiz'), 'maria.lopez')
        self.assertEqual(base_de_usuario('  Ángel ', 'Núñez'), 'angel.nunez')
        self.assertEqual(base_de_usuario("O'Brien", 'D’Angelo'), 'obrien.dangelo')

    def test_nombres_muy_cortos_o_sin_letras(self):
        self.assertEqual(base_de_usuario('s', ''), 'tutor.s')
        self.assertEqual(base_de_usuario('', ''), 'tutor')
        self.assertEqual(base_de_usuario('123', ''), 'tutor.123')
        self.assertEqual(base_de_usuario('s', 's'), 's.s')

    def test_no_pasa_del_largo_maximo(self):
        self.assertLessEqual(len(base_de_usuario('A' * 60, 'B' * 60)), 36)

    def test_normalizar_lo_escrito(self):
        self.assertEqual(normalizar_usuario('  María.López '), 'maria.lopez')
        self.assertEqual(normalizar_usuario('Ana Ruiz'), 'anaruiz')


@PRUEBAS
class UsuarioDelModeloTests(BaseTestCase):
    def test_todo_tutor_nuevo_recibe_usuario_y_los_repetidos_se_numeran(self):
        primero = crear_tutor(nombre='María', apellido_paterno='López')
        segundo = crear_tutor(nombre='María Elena', apellido_paterno='López', telefono='3530000002')
        tercero = crear_tutor(nombre='maria', apellido_paterno='LOPEZ', telefono='3530000003')
        self.assertEqual([primero.usuario, segundo.usuario, tercero.usuario], ['maria.lopez', 'maria.lopez2', 'maria.lopez3'])

    def test_el_usuario_no_cambia_al_editar_el_nombre(self):
        tutor = crear_tutor(nombre='María', apellido_paterno='López')
        tutor.nombre = 'Marisol'
        tutor.save()
        tutor.refresh_from_db()
        self.assertEqual(tutor.usuario, 'maria.lopez')

    def test_guardar_solo_algunos_campos_tambien_completa_el_usuario(self):
        tutor = crear_tutor()
        Tutor.objects.filter(pk=tutor.pk).update(usuario=None)
        tutor.refresh_from_db()
        tutor.estatus = 'INACTIVO'
        tutor.save(update_fields=['estatus'])
        tutor.refresh_from_db()
        self.assertEqual((tutor.estatus, tutor.usuario), ('INACTIVO', 'rosa.mora'))

    def test_la_migracion_da_usuario_a_los_tutores_que_ya_existian_sin_inventar_contrasenas(self):
        migracion = importlib.import_module('Alumnos.migrations.0012_tutor_acceso')
        conservado = crear_tutor(nombre='Rosa', apellido_paterno='Mora', telefono='3530000001')
        a = crear_tutor(nombre='Pedro', apellido_paterno='Ramírez', telefono='3530000002')
        b = crear_tutor(nombre='Pedro', apellido_paterno='Ramirez', telefono='3530000003')
        c = crear_tutor(nombre='s', apellido_paterno='s', telefono='3530000004')
        Tutor.objects.filter(pk__in=[a.pk, b.pk, c.pk]).update(usuario=None, contrasena='')
        migracion.asignar_usuarios(apps, None)
        for tutor in (conservado, a, b, c):
            tutor.refresh_from_db()
        self.assertEqual([conservado.usuario, a.usuario, b.usuario, c.usuario], ['rosa.mora', 'pedro.ramirez', 'pedro.ramirez2', 's.s'])
        self.assertEqual((a.contrasena, a.contrasena_visible), ('', ''))

    def test_la_regla_de_la_migracion_es_la_misma_que_la_del_codigo(self):
        migracion = importlib.import_module('Alumnos.migrations.0012_tutor_acceso')
        for nombre, apellido in (('María José', 'López'), ('s', ''), ('', ''), ('123', 'x'), ('Ángel', 'Núñez')):
            self.assertEqual(migracion._base_de_usuario(nombre, apellido), base_de_usuario(nombre, apellido))


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
@PRUEBAS
class AltaConAccesoTests(BaseTestCase):
    url = '/tutores/nuevo/'

    def test_el_formulario_pide_usuario_y_contrasena(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('Acceso al sistema', html)
        campo_usuario = re.search(r'<input[^>]*name="usuario"[^>]*>', html).group(0)
        self.assertIn('placeholder="Se propone con su nombre: maria.lopez"', campo_usuario)
        self.assertIn(f'data-usuario-url="{reverse("tutores:usuario")}"', campo_usuario)
        self.assertIn('data-excluir=""', campo_usuario)
        self.assertIn('data-usuario-estado', html)
        campo = re.search(r'<input[^>]*name="contrasena_inicial"[^>]*>', html).group(0)
        self.assertNotIn('value=', campo)
        self.assertIn('data-password-generate', html)

    def test_sin_escribirlos_se_generan_y_se_muestran_una_vez(self):
        respuesta = self.client.post(self.url, datos_tutor())
        self.assertRedirects(respuesta, reverse('tutores:lista'), fetch_redirect_response=False)
        tutor = Tutor.objects.get()
        self.assertEqual(tutor.usuario, 'maria.lopez')
        self.assertEqual(len(tutor.contrasena_visible), 8)
        self.assertTrue(check_password(tutor.contrasena_visible, tutor.contrasena))
        listado = self.client.get(reverse('tutores:lista'))
        self.assertContains(listado, 'Credenciales de acceso')
        self.assertContains(listado, '<dt class="credentials__label">Usuario</dt><dd class="credentials__value">maria.lopez</dd>', html=False)
        self.assertContains(listado, tutor.contrasena_visible)
        self.assertNotContains(self.client.get(reverse('tutores:lista')), 'Credenciales de acceso')

    def test_se_pueden_escribir_y_la_contrasena_puede_ser_sencilla(self):
        self.client.post(self.url, datos_tutor(usuario=' Mamá.Ana ', contrasena_inicial='1234'))
        tutor = Tutor.objects.get()
        self.assertEqual(tutor.usuario, 'mama.ana')
        self.assertEqual(tutor.contrasena_visible, '1234')
        self.assertTrue(check_password('1234', tutor.contrasena))

    def test_rechaza_usuarios_invalidos_o_repetidos_y_contrasenas_demasiado_cortas(self):
        crear_tutor(nombre='Rosa', apellido_paterno='Mora', usuario='rosa.mora')
        casos = {
            'ab': 'Usa de 3 a 40',
            '12345': 'con al menos una letra',
            'ma@ria': 'Usa de 3 a 40',
            'ROSA.MORA': 'ya lo tiene otro tutor',
        }
        for usuario, mensaje in casos.items():
            with self.subTest(usuario=usuario):
                respuesta = self.client.post(self.url, datos_tutor(usuario=usuario))
                self.assertEqual(respuesta.status_code, 200)
                self.assertContains(respuesta, mensaje)
        self.assertContains(self.client.post(self.url, datos_tutor(contrasena_inicial='12')), 'Usa al menos 4 caracteres')
        self.assertEqual(Tutor.objects.count(), 1)

    def test_al_editar_se_cambia_el_usuario_pero_no_la_contrasena(self):
        tutor = crear_tutor(nombre='María', apellido_paterno='López', telefono='3531234567')
        tutor.establecer_contrasena('sol123')
        tutor.save()
        url = reverse('tutores:editar', args=[tutor.pk])
        html = self.client.get(url).content.decode()
        self.assertIn('value="maria.lopez"', html)
        self.assertNotIn('contrasena_inicial', html)
        self.assertIn('desde su perfil', html)

        datos = datos_tutor(usuario='mary', estatus='ACTIVO')
        datos.pop('contrasena_inicial')
        self.assertEqual(self.client.post(url, datos).status_code, 302)
        tutor.refresh_from_db()
        self.assertEqual((tutor.usuario, tutor.contrasena_visible), ('mary', 'sol123'))

    def test_al_editar_un_usuario_vacio_se_vuelve_a_generar(self):
        tutor = crear_tutor(nombre='María', apellido_paterno='López', telefono='3531234567', usuario='mary')
        datos = datos_tutor(usuario='', estatus='ACTIVO')
        datos.pop('contrasena_inicial')
        self.client.post(reverse('tutores:editar', args=[tutor.pk]), datos)
        tutor.refresh_from_db()
        self.assertEqual(tutor.usuario, 'maria.lopez')

    def test_se_busca_por_usuario(self):
        crear_tutor(nombre='Rosa', apellido_paterno='Mora', usuario='rosita')
        crear_tutor(nombre='Jorge', apellido_paterno='Pérez', telefono='3534445566')
        respuesta = self.client.get(reverse('tutores:lista'), {'q': 'rosita'})
        self.assertEqual(respuesta.context['pagina'].paginator.count, 1)

    def test_la_exportacion_incluye_el_usuario(self):
        crear_tutor(nombre='Rosa', apellido_paterno='Mora')
        filas = list(csv.reader(io.StringIO(self.client.get(reverse('tutores:exportar')).content.decode('utf-8').lstrip('﻿'))))
        self.assertEqual(filas[0][-1], 'Usuario')
        self.assertEqual(filas[1][-1], 'rosa.mora')


@PRUEBAS
class PropuestaDeUsuarioTests(BaseTestCase):
    """La consulta (JSON) con la que el formulario propone el usuario mientras se escribe el nombre y revisa el escrito."""

    url = '/tutores/usuario/'

    def consultar(self, **parametros):
        respuesta = self.client.get(self.url, parametros)
        self.assertEqual(respuesta.status_code, 200)
        return respuesta.json()

    def test_propone_uno_libre_con_el_nombre(self):
        self.assertEqual(self.consultar(nombre='María José', apellido_paterno='López')['sugerido'], 'maria.lopez')
        crear_tutor(nombre='María', apellido_paterno='López')
        self.assertEqual(self.consultar(nombre='Maria', apellido_paterno='LOPEZ')['sugerido'], 'maria.lopez2')

    def test_al_editar_su_propio_usuario_no_cuenta_como_repetido(self):
        tutor = crear_tutor(nombre='María', apellido_paterno='López')
        datos = self.consultar(nombre='María', apellido_paterno='López', excluir=tutor.pk, usuario='maria.lopez')
        self.assertEqual((datos['sugerido'], datos['disponible']), ('maria.lopez', True))

    def test_revisa_el_que_se_escribe(self):
        crear_tutor(nombre='Rosa', apellido_paterno='Mora')
        libre = self.consultar(usuario=' Papá.Jorge ')
        self.assertEqual((libre['usuario'], libre['disponible'], libre['mensaje']), ('papa.jorge', True, '«papa.jorge» está disponible.'))
        repetido = self.consultar(usuario='ROSA.MORA')
        self.assertFalse(repetido['disponible'])
        self.assertIn('ya lo tiene otro tutor', repetido['mensaje'])
        invalido = self.consultar(usuario='ab')
        self.assertFalse(invalido['disponible'])
        self.assertIn('Usa de 3 a 40', invalido['mensaje'])
        self.assertEqual(self.consultar(usuario='')['mensaje'], '')

    def test_sin_usuario_escrito_solo_propone(self):
        self.assertEqual(set(self.consultar(nombre='Ana', apellido_paterno='Ruiz')), {'sugerido'})

    def test_un_excluir_invalido_se_ignora(self):
        self.assertEqual(self.consultar(nombre='Ana', apellido_paterno='Ruiz', excluir='abc')['sugerido'], 'ana.ruiz')

    def test_la_usa_quien_puede_registrar_o_editar_tutores(self):
        self.con_permisos('view_tutor')
        self.assertEqual(self.client.get(self.url).status_code, 403)
        for permiso in ('add_tutor', 'change_tutor'):
            self.con_permisos(permiso)
            self.assertEqual(self.client.get(self.url, {'nombre': 'Ana'}).status_code, 200, permiso)

    def test_el_formulario_de_edicion_excluye_al_propio_tutor(self):
        tutor = crear_tutor(nombre='María', apellido_paterno='López')
        html = self.client.get(reverse('tutores:editar', args=[tutor.pk])).content.decode()
        campo = re.search(r'<input[^>]*name="usuario"[^>]*>', html).group(0)
        self.assertIn(f'data-excluir="{tutor.pk}"', campo)
        self.assertIn('value="maria.lopez"', campo)

    def test_lo_propuesto_se_guarda_y_sigue_siendo_unico_al_enviar(self):
        """Si entre la propuesta y el envío otro tutor tomó ese usuario, el servidor lo rechaza."""
        crear_tutor(nombre='María', apellido_paterno='López', telefono='3530000001')
        respuesta = self.client.post('/tutores/nuevo/', datos_tutor(usuario='maria.lopez'))
        self.assertContains(respuesta, 'ya lo tiene otro tutor')
        self.client.post('/tutores/nuevo/', datos_tutor(usuario=self.consultar(nombre='María', apellido_paterno='López')['sugerido']))
        self.assertTrue(Tutor.objects.filter(usuario='maria.lopez2').exists())


# ---------------------------------------------------------------------------
# Perfil: consultar y restablecer
# ---------------------------------------------------------------------------
@PRUEBAS
class PerfilConAccesoTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.tutor = crear_tutor(nombre='María', apellido_paterno='López')
        self.tutor.establecer_contrasena('sol123')
        self.tutor.save()
        self.perfil = self.tutor.get_absolute_url()

    def test_el_administrador_ve_el_usuario_y_la_contrasena_oculta_hasta_que_la_muestra(self):
        html = self.client.get(self.perfil).content.decode()
        self.assertIn('Acceso al sistema', html)
        self.assertIn('maria.lopez', html)
        campo = re.search(r'<input[^>]*id="contrasena-tutor"[^>]*>', html).group(0)
        self.assertIn('type="password"', campo)
        self.assertIn('value="sol123"', campo)
        self.assertIn('data-reveal="#contrasena-tutor"', html)
        self.assertIn('data-copy="#contrasena-tutor"', html)
        self.assertIn('Restablecer contraseña', html)
        self.assertIn('id="modal-contrasena"', html)

    def test_quien_no_es_administrador_nunca_ve_la_contrasena(self):
        self.con_permisos('view_tutor', 'change_tutor')
        respuesta = self.client.get(self.perfil)
        self.assertNotContains(respuesta, 'sol123')
        self.assertContains(respuesta, 'maria.lopez')
        self.assertContains(respuesta, 'Solo un administrador puede consultarla')
        self.assertContains(respuesta, 'Restablecer contraseña')

    def test_sin_permiso_de_edicion_no_se_ofrece_restablecerla(self):
        self.con_permisos('view_tutor')
        respuesta = self.client.get(self.perfil)
        self.assertNotContains(respuesta, 'modal-contrasena')

    def test_un_tutor_sin_contrasena_lo_dice_y_ofrece_asignarla(self):
        Tutor.objects.filter(pk=self.tutor.pk).update(contrasena='', contrasena_visible='')
        html = self.client.get(self.perfil).content.decode()
        self.assertIn('Todavía no tiene contraseña', html)
        self.assertIn('Asignar contraseña', html)
        self.assertNotIn('Restablecer contraseña', html)

    def test_restablece_con_la_que_se_escribe_y_la_muestra_una_vez(self):
        respuesta = self.client.post(reverse('tutores:contrasena', args=[self.tutor.pk]), {'contrasena': ' abcd '})
        self.assertRedirects(respuesta, self.perfil, fetch_redirect_response=False)
        self.tutor.refresh_from_db()
        self.assertEqual(self.tutor.contrasena_visible, 'abcd')
        self.assertTrue(check_password('abcd', self.tutor.contrasena))
        perfil = self.client.get(self.perfil)
        self.assertContains(perfil, 'Credenciales de acceso')
        self.assertContains(perfil, 'Se asignó una nueva contraseña a María López')
        self.assertNotContains(self.client.get(self.perfil), 'Credenciales de acceso')

    def test_vacia_genera_una(self):
        self.client.post(reverse('tutores:contrasena', args=[self.tutor.pk]), {'contrasena': ''})
        self.tutor.refresh_from_db()
        self.assertEqual(len(self.tutor.contrasena_visible), 8)
        self.assertNotEqual(self.tutor.contrasena_visible, 'sol123')

    def test_no_restablece_con_una_demasiado_corta(self):
        respuesta = self.client.post(reverse('tutores:contrasena', args=[self.tutor.pk]), {'contrasena': 'ab'}, follow=True)
        self.assertContains(respuesta, 'Usa al menos 4 caracteres')
        self.tutor.refresh_from_db()
        self.assertEqual(self.tutor.contrasena_visible, 'sol123')

    def test_restablecer_exige_permiso_de_edicion_y_post(self):
        self.assertEqual(self.client.get(reverse('tutores:contrasena', args=[self.tutor.pk])).status_code, 405)
        self.con_permisos('view_tutor')
        self.assertEqual(self.client.post(reverse('tutores:contrasena', args=[self.tutor.pk]), {'contrasena': 'abcd'}).status_code, 403)
        self.tutor.refresh_from_db()
        self.assertEqual(self.tutor.contrasena_visible, 'sol123')


# ---------------------------------------------------------------------------
# Tutores que se registran desde otros lugares
# ---------------------------------------------------------------------------
@PRUEBAS
class OtrasAltasTests(BaseTestCase):
    def test_el_tutor_nuevo_del_alta_de_un_estudiante_recibe_usuario_y_contrasena(self):
        datos = {**datos_alumno(), **datos_tutores(tutor_nuevo(tutor_principal='on'))}
        self.assertEqual(self.client.post(reverse('alumnos:crear'), datos).status_code, 302)
        tutor = Tutor.objects.get()
        self.assertEqual(tutor.usuario, 'maria.lopez')
        self.assertEqual(len(tutor.contrasena_visible), 8)
        self.assertTrue(check_password(tutor.contrasena_visible, tutor.contrasena))

    def test_el_tutor_nuevo_de_la_importacion_de_estudiantes_tambien(self):
        contenido = ('Nombre,Apellido paterno,CURP,Nombre del tutor,Apellido paterno del tutor,Teléfono del tutor,Parentesco del tutor\n'
                     'Ana,García,GALA150315MMNRPNA1,María,López,3531234567,Madre\n').encode('utf-8')
        importacion_de_estudiantes.importar(importacion_de_estudiantes.leer_filas(contenido))
        tutor = Tutor.objects.get()
        self.assertEqual(tutor.usuario, 'maria.lopez')
        self.assertTrue(check_password(tutor.contrasena_visible, tutor.contrasena))


@PRUEBAS
class ImportacionConAccesoTests(BaseTestCase):
    def importar(self, filas, encabezados):
        salida = io.StringIO()
        escritor = csv.writer(salida)
        escritor.writerow(encabezados)
        escritor.writerows(filas)
        return importacion.importar(importacion.leer_filas(salida.getvalue().encode('utf-8')))

    def test_genera_usuario_y_contrasena_o_usa_los_del_archivo(self):
        resultado = self.importar(
            [['María', 'López', '3531234567', '', ''], ['Jorge', 'Pérez', '3534445566', 'papa.jorge', '4321']],
            ['Nombre', 'Apellido paterno', 'Teléfono', 'Usuario', 'Contraseña'],
        )
        self.assertEqual(resultado.errores, [])
        maria, jorge = Tutor.objects.get(nombre='María'), Tutor.objects.get(nombre='Jorge')
        self.assertEqual(maria.usuario, 'maria.lopez')
        self.assertEqual(len(maria.contrasena_visible), 8)
        self.assertEqual((jorge.usuario, jorge.contrasena_visible), ('papa.jorge', '4321'))
        self.assertTrue(check_password('4321', jorge.contrasena))
        self.assertEqual(
            [(c['usuario'], c['contrasena']) for c in resultado.creados], [('maria.lopez', maria.contrasena_visible), ('papa.jorge', '4321')],
        )

    def test_un_usuario_invalido_o_que_ya_existe_es_un_error_de_esa_fila(self):
        crear_tutor(nombre='Rosa', apellido_paterno='Mora', usuario='rosa.mora')
        resultado = self.importar(
            [['María', 'López', '3531234567', 'rosa.mora'], ['Jorge', 'Pérez', '3534445566', 'x'], ['Ana', 'Ruiz', '3539998877', 'ana.ruiz']],
            ['Nombre', 'Apellido paterno', 'Teléfono', 'Usuario'],
        )
        self.assertEqual(len(resultado.creados), 1)
        self.assertIn('ya lo tiene otro tutor', resultado.errores[0]['motivo'])
        self.assertIn('Usuario', resultado.errores[1]['motivo'])

    def test_a_un_tutor_que_ya_existia_no_se_le_cambian(self):
        tutor = crear_tutor(nombre='María', apellido_paterno='López', telefono='3531234567')
        tutor.establecer_contrasena('sol123')
        tutor.save()
        resultado = self.importar([['María', 'López', '3531234567', 'otro.usuario', '9999']], ['Nombre', 'Apellido paterno', 'Teléfono', 'Usuario', 'Contraseña'])
        self.assertEqual(resultado.omitidos, 1)
        tutor.refresh_from_db()
        self.assertEqual((tutor.usuario, tutor.contrasena_visible), ('maria.lopez', 'sol123'))

    def test_los_usuarios_y_contrasenas_de_la_importacion_se_descargan(self):
        contenido = 'Nombre,Apellido paterno,Teléfono,Contraseña\nMaría,López,3531234567,sol123\n'.encode('utf-8')
        self.client.post(reverse('tutores:importar'), {'archivo': SimpleUploadedFile('tutores.csv', contenido)})
        self.assertContains(self.client.get(reverse('tutores:lista')), 'Descargar usuarios y contraseñas')
        respuesta = self.client.get(reverse('tutores:importar_credenciales'))
        self.assertIn('contrasenas-tutores-', respuesta['Content-Disposition'])
        filas = list(csv.reader(io.StringIO(respuesta.content.decode('utf-8').lstrip('﻿'))))
        self.assertEqual(filas, [['Usuario', 'Nombre', 'Contraseña'], ['maria.lopez', 'María López', 'sol123']])

    def test_sin_importacion_reciente_no_hay_nada_que_descargar(self):
        respuesta = self.client.get(reverse('tutores:importar_credenciales'), follow=True)
        self.assertRedirects(respuesta, reverse('tutores:lista'))
        self.assertContains(respuesta, 'No hay contraseñas de una importación reciente')

    def test_descargar_exige_el_permiso_de_registrar(self):
        self.con_permisos('view_tutor', 'change_tutor')
        self.assertEqual(self.client.get(reverse('tutores:importar_credenciales')).status_code, 403)

    def test_vincular_un_tutor_existente_no_ofrece_descargar_contrasenas(self):
        crear_alumno(referencia='8888')
        crear_tutor(nombre='María', apellido_paterno='López', telefono='3531234567')
        contenido = 'Nombre,Apellido paterno,Teléfono,Referencia del estudiante,Parentesco\nMaría,López,3531234567,8888,Madre\n'.encode('utf-8')
        self.client.post(reverse('tutores:importar'), {'archivo': SimpleUploadedFile('tutores.csv', contenido)})
        self.assertNotContains(self.client.get(reverse('tutores:lista')), 'Descargar usuarios y contraseñas')
        self.assertEqual(Alumno.objects.get().tutores_relacionados.count(), 1)
