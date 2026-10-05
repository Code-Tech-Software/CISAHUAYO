"""Módulo de roles: listado, alta y edición con la matriz de permisos, copiar, desactivar y el efecto en los usuarios."""
import re

from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.test import Client
from django.urls import reverse

from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase, crear_rol, crear_usuario
from Usuarios import catalogo
from Usuarios.models import Rol
from Usuarios.seguridad import permisos_de_rol

Usuario = get_user_model()


def datos_de_rol(permisos=(), **cambios):
    datos = {'nombre': 'Coordinación', 'descripcion': 'Coordina a los docentes', 'tono': 2, 'permisos': list(permisos)}
    datos.update(cambios)
    return datos


def bitacora(rol, accion=None):
    consulta = LogEntry.objects.filter(content_type=ContentType.objects.get_for_model(Rol), object_id=str(rol.pk))
    return consulta.filter(action_flag=accion) if accion else consulta


@PRUEBAS
class BaseRolesTestCase(BaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.docente = Rol.objects.get(grupo__name='Docente')
        cls.administrador = Rol.objects.get(acceso_total=True)

    def entrar_como(self, usuario):
        self.client.force_login(usuario)
        return usuario

    def gestor_de_roles(self, permisos=('Usuarios.view_rol', 'Usuarios.add_rol', 'Usuarios.change_rol', 'Usuarios.delete_rol'), nombre='gestor'):
        rol = crear_rol(f'Gestor de roles {nombre}', set(permisos))
        return crear_usuario(nombre, rol)


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------
class ListadoDeRolesTests(BaseRolesTestCase):
    def test_exige_permiso_para_ver_roles(self):
        self.entrar_como(self.sin_permisos)
        self.assertEqual(self.client.get(reverse('roles:lista')).status_code, 403)

    def test_muestra_los_roles_con_su_conteo_de_usuarios_y_permisos(self):
        crear_usuario('ana', self.docente)
        crear_usuario('beto', self.docente)
        html = self.client.get(reverse('roles:lista')).content.decode()
        for nombre in ('Administrador', 'Dirección', 'Control escolar', 'Docente', 'Recepción'):
            self.assertIn(nombre, html)
        docente = re.search(r'<article class="role-card[^"]*" aria-labelledby="rol-%d">.*?</article>' % self.docente.pk, html, re.S).group(0)
        self.assertIn('2 usuarios', docente)
        self.assertIn(f'<strong>{len(permisos_de_rol(self.docente))}</strong> de {len(catalogo.TODOS)} permisos', docente)

    def test_el_rol_del_sistema_esta_marcado_y_dice_acceso_total(self):
        html = self.client.get(reverse('roles:lista')).content.decode()
        tarjeta = re.search(r'<article class="role-card[^"]*" aria-labelledby="rol-%d">.*?</article>' % self.administrador.pk, html, re.S).group(0)
        self.assertIn('Sistema', tarjeta)
        self.assertIn('Acceso total', tarjeta)
        self.assertNotIn(reverse('roles:editar', args=[self.administrador.pk]), tarjeta)

    def test_los_usuarios_desactivados_no_cuentan(self):
        crear_usuario('activa', self.docente)
        crear_usuario('baja', self.docente, is_active=False)
        html = self.client.get(reverse('roles:lista')).content.decode()
        docente = re.search(r'<article class="role-card[^"]*" aria-labelledby="rol-%d">.*?</article>' % self.docente.pk, html, re.S).group(0)
        self.assertIn('1 usuario<', docente)

    def test_los_roles_desactivados_tienen_su_propio_filtro(self):
        crear_rol('Rol apagado', {'Alumnos.view_alumno'}, activo=False)
        activos = self.client.get(reverse('roles:lista')).content.decode()
        self.assertNotIn('Rol apagado', activos)
        inactivos = self.client.get(reverse('roles:lista'), {'estado': 'INACTIVO'}).content.decode()
        self.assertIn('Rol apagado', inactivos)
        self.assertIn('Reactivar', inactivos)

    def test_sin_permiso_de_alta_o_edicion_no_ofrece_esas_acciones(self):
        self.entrar_como(self.gestor_de_roles(('Usuarios.view_rol',), 'lector'))
        html = self.client.get(reverse('roles:lista')).content.decode()
        self.assertNotIn('Nuevo rol', html)
        self.assertNotIn(reverse('roles:editar', args=[self.docente.pk]), html)

    def test_enlaza_a_los_usuarios_de_cada_rol_solo_si_puede_verlos(self):
        self.assertIn(f'{reverse("usuarios:lista")}?rol={self.docente.pk}', self.client.get(reverse('roles:lista')).content.decode())
        self.entrar_como(self.gestor_de_roles(('Usuarios.view_rol',), 'lector'))
        self.assertNotIn(f'{reverse("usuarios:lista")}?rol=', self.client.get(reverse('roles:lista')).content.decode())


# ---------------------------------------------------------------------------
# Alta
# ---------------------------------------------------------------------------
class AltaDeRolesTests(BaseRolesTestCase):
    def test_exige_permiso_para_crear(self):
        self.entrar_como(self.gestor_de_roles(('Usuarios.view_rol',), 'lector'))
        self.assertEqual(self.client.get(reverse('roles:crear')).status_code, 403)
        self.assertEqual(self.client.post(reverse('roles:crear'), datos_de_rol()).status_code, 403)
        self.assertFalse(Group.objects.filter(name='Coordinación').exists())

    def test_la_matriz_ofrece_una_casilla_por_cada_permiso_del_catalogo(self):
        html = self.client.get(reverse('roles:crear')).content.decode()
        casillas = re.findall(r'<input class="perm-cell__input" type="checkbox" name="permisos" value="([^"]+)"', html)
        self.assertEqual(sorted(casillas), sorted(catalogo.TODOS))
        self.assertEqual(html.count('class="swatch swatch--tone-'), 6)
        self.assertIn('data-modal-tam="lg"', html)

    def test_las_casillas_declaran_lo_que_necesitan(self):
        html = self.client.get(reverse('roles:crear')).content.decode()
        self.assertIn('data-accion="ver"', html)
        self.assertRegex(html, r'value="Alumnos\.change_alumno" data-accion="editar" data-requiere="Alumnos\.view_alumno"')
        self.assertNotRegex(html, r'value="Alumnos\.view_alumno" data-accion="ver" data-requiere')

    def test_crea_el_rol_con_sus_permisos_y_dependencias(self):
        respuesta = self.client.post(reverse('roles:crear'), datos_de_rol({'Alumnos.change_alumno', 'Alumnos.view_tutor'}))
        rol = Rol.objects.get(grupo__name='Coordinación')
        self.assertRedirects(respuesta, reverse('roles:detalle', args=[rol.pk]), fetch_redirect_response=False)
        self.assertEqual((rol.descripcion, rol.tono, rol.activo, rol.es_sistema, rol.acceso_total), ('Coordina a los docentes', 2, True, False, False))
        # «editar» exige «ver»: se concede aunque no se haya marcado
        self.assertEqual(permisos_de_rol(rol), {'Alumnos.change_alumno', 'Alumnos.view_alumno', 'Alumnos.view_tutor'})

    def test_puede_crearse_un_rol_sin_permisos(self):
        self.client.post(reverse('roles:crear'), datos_de_rol())
        self.assertEqual(permisos_de_rol(Rol.objects.get(grupo__name='Coordinación')), set())

    def test_avisa_con_un_mensaje_y_deja_bitacora(self):
        respuesta = self.client.post(reverse('roles:crear'), datos_de_rol({'Alumnos.view_alumno'}), follow=True)
        self.assertContains(respuesta, 'fue creado con 1 permiso')
        rol = Rol.objects.get(grupo__name='Coordinación')
        entrada = bitacora(rol, ADDITION).get()
        self.assertEqual(entrada.user, self.admin)
        self.assertIn('Alumnos · Ver', entrada.change_message)

    def test_responde_con_json_cuando_se_envia_desde_la_ventana(self):
        respuesta = self.client.post(reverse('roles:crear'), datos_de_rol(), HTTP_X_MODAL_FORM='1')
        rol = Rol.objects.get(grupo__name='Coordinación')
        self.assertEqual(respuesta.json(), {'redirect': reverse('roles:detalle', args=[rol.pk])})

    def test_rechaza_datos_incorrectos(self):
        casos = {
            'nombre vacío': ({'nombre': ''}, 'obligatorio'),
            'nombre repetido': ({'nombre': 'Docente'}, 'Ya existe un rol con ese nombre'),
            'nombre repetido sin importar mayúsculas': ({'nombre': 'dOcEnTe'}, 'Ya existe un rol con ese nombre'),
            'nombre muy largo': ({'nombre': 'x' * 81}, 'como máximo'),
            'color inexistente': ({'tono': 9}, 'field__error'),
            'permiso inexistente': ({'permisos': ['Alumnos.hackear']}, 'permisos que no existen'),
            'permiso de otro modelo': ({'permisos': ['auth.delete_permission']}, 'permisos que no existen'),
        }
        for nombre, (cambios, texto) in casos.items():
            with self.subTest(caso=nombre):
                respuesta = self.client.post(reverse('roles:crear'), datos_de_rol(**cambios))
                self.assertEqual(respuesta.status_code, 200)
                self.assertContains(respuesta, texto)
        self.assertFalse(Group.objects.filter(name='Coordinación').exists())

    def test_al_haber_errores_conserva_lo_marcado(self):
        respuesta = self.client.post(reverse('roles:crear'), datos_de_rol({'Alumnos.view_alumno', 'Alumnos.add_tutor'}, nombre=''))
        html = respuesta.content.decode()
        self.assertRegex(html, r'value="Alumnos\.view_alumno"[^>]*checked')
        self.assertRegex(html, r'value="Alumnos\.add_tutor"[^>]*checked')
        self.assertRegex(html, r'value="Alumnos\.view_tutor"[^>]*checked')   # lo que necesita, también
        self.assertNotRegex(html, r'value="Alumnos\.view_grado"[^>]*checked')

    def test_el_nombre_se_limpia_de_espacios(self):
        self.client.post(reverse('roles:crear'), datos_de_rol(nombre='   Mi   rol   nuevo '))
        self.assertTrue(Group.objects.filter(name='Mi rol nuevo').exists())

    def test_no_se_pueden_conceder_permisos_que_quien_crea_no_tiene(self):
        self.entrar_como(self.gestor_de_roles())
        respuesta = self.client.post(reverse('roles:crear'), datos_de_rol({'Alumnos.view_alumno'}))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'No puedes conceder permisos que tú no tienes')
        self.assertFalse(Group.objects.filter(name='Coordinación').exists())

    def test_si_se_pueden_conceder_los_que_si_se_tienen(self):
        self.entrar_como(self.gestor_de_roles())
        self.client.post(reverse('roles:crear'), datos_de_rol({'Usuarios.view_rol'}))
        self.assertEqual(permisos_de_rol(Rol.objects.get(grupo__name='Coordinación')), {'Usuarios.view_rol'})

    def test_las_casillas_que_no_se_tienen_aparecen_bloqueadas(self):
        self.entrar_como(self.gestor_de_roles())
        html = self.client.get(reverse('roles:crear')).content.decode()
        self.assertRegex(html, r'value="Alumnos\.view_alumno"[^>]*disabled')
        self.assertNotRegex(html, r'value="Usuarios\.view_rol"[^>]*disabled')


# ---------------------------------------------------------------------------
# Edición: los cambios llegan a todos los usuarios del rol
# ---------------------------------------------------------------------------
class EdicionDeRolesTests(BaseRolesTestCase):
    def setUp(self):
        super().setUp()
        self.rol = crear_rol('Consulta', {'Alumnos.view_alumno', 'Alumnos.view_tutor'}, descripcion='Solo mirar', tono=4)

    def enviar(self, permisos, **cambios):
        datos = datos_de_rol(permisos, nombre='Consulta', descripcion='Solo mirar', tono=4)
        datos.update(cambios)
        return self.client.post(reverse('roles:editar', args=[self.rol.pk]), datos)

    def test_el_formulario_trae_lo_actual_y_marca_los_permisos_del_rol(self):
        html = self.client.get(reverse('roles:editar', args=[self.rol.pk])).content.decode()
        self.assertIn('value="Consulta"', html)
        self.assertRegex(html, r'value="Alumnos\.view_alumno"[^>]*checked')
        self.assertRegex(html, r'value="Alumnos\.view_tutor"[^>]*checked')
        self.assertNotRegex(html, r'value="Alumnos\.view_grado"[^>]*checked')
        self.assertRegex(html, r'name="tono" value="4" checked')

    def test_guarda_los_cambios_y_vuelve_al_perfil_del_rol(self):
        respuesta = self.enviar({'Alumnos.view_alumno', 'Alumnos.add_alumno', 'Alumnos.view_grado'}, nombre='Consulta y altas', descripcion='Nueva')
        self.assertRedirects(respuesta, reverse('roles:detalle', args=[self.rol.pk]), fetch_redirect_response=False)
        self.rol.refresh_from_db()
        self.assertEqual((self.rol.nombre, self.rol.descripcion), ('Consulta y altas', 'Nueva'))
        self.assertEqual(permisos_de_rol(self.rol), {'Alumnos.view_alumno', 'Alumnos.add_alumno', 'Alumnos.view_grado'})

    def test_el_cambio_llega_a_todos_los_usuarios_del_rol_sin_editarlos(self):
        sesiones = []
        for nombre in ('ana', 'beto'):
            sesion = Client()
            sesion.force_login(crear_usuario(nombre, self.rol))
            sesiones.append(sesion)
        self.assertEqual(sesiones[0].get(reverse('tutores:lista')).status_code, 200)

        self.enviar({'Alumnos.view_alumno', 'Alumnos.view_grado'})   # se quita ver tutores y se da ver grados
        for sesion in sesiones:
            self.assertEqual(sesion.get(reverse('tutores:lista')).status_code, 403)
            self.assertEqual(sesion.get(reverse('grados:lista')).status_code, 200)

    def test_el_aviso_dice_a_cuantos_usuarios_llego(self):
        crear_usuario('ana', self.rol)
        crear_usuario('beto', self.rol)
        respuesta = self.client.post(
            reverse('roles:editar', args=[self.rol.pk]), datos_de_rol({'Alumnos.view_alumno'}, nombre='Consulta', descripcion='Solo mirar', tono=4), follow=True,
        )
        self.assertContains(respuesta, 'ya aplican a 2 usuarios')

    def test_la_bitacora_dice_que_permisos_se_concedieron_y_cuales_se_retiraron(self):
        self.enviar({'Alumnos.view_alumno', 'Alumnos.add_alumno'})
        mensaje = bitacora(self.rol, CHANGE).get().change_message
        self.assertIn('Permisos concedidos: Alumnos · Crear', mensaje)
        self.assertIn('Permisos retirados: Tutores · Ver', mensaje)

    def test_un_cambio_de_nombre_se_registra(self):
        self.enviar({'Alumnos.view_alumno', 'Alumnos.view_tutor'}, nombre='Solo consulta')
        self.assertIn('«Consulta» → «Solo consulta»', bitacora(self.rol, CHANGE).get().change_message)

    def test_sin_cambios_no_llena_la_bitacora(self):
        self.enviar({'Alumnos.view_alumno', 'Alumnos.view_tutor'})
        self.assertFalse(bitacora(self.rol, CHANGE).exists())

    def test_se_puede_dejar_el_rol_sin_permisos(self):
        self.enviar(set())
        self.assertEqual(permisos_de_rol(self.rol), set())

    def test_los_permisos_que_no_son_del_catalogo_se_respetan(self):
        ajeno = Permission.objects.get(content_type__app_label='auth', codename='view_group')
        self.rol.grupo.permissions.add(ajeno)
        self.enviar(set())
        self.assertIn(ajeno, self.rol.grupo.permissions.all())

    def test_el_nombre_puede_conservarse_pero_no_repetir_el_de_otro_rol(self):
        self.assertEqual(self.enviar({'Alumnos.view_alumno'}).status_code, 302)
        respuesta = self.enviar({'Alumnos.view_alumno'}, nombre='Docente')
        self.assertContains(respuesta, 'Ya existe un rol con ese nombre')

    def test_exige_permiso_para_editar(self):
        self.entrar_como(self.gestor_de_roles(('Usuarios.view_rol',), 'lector'))
        self.assertEqual(self.client.get(reverse('roles:editar', args=[self.rol.pk])).status_code, 403)
        self.assertEqual(self.enviar({'Alumnos.view_alumno'}).status_code, 403)

    def test_el_rol_del_sistema_no_se_edita(self):
        url = reverse('roles:editar', args=[self.administrador.pk])
        respuesta = self.client.get(url)
        self.assertRedirects(respuesta, reverse('roles:detalle', args=[self.administrador.pk]), fetch_redirect_response=False)
        respuesta = self.client.post(url, datos_de_rol(nombre='Hackeado'))
        self.assertRedirects(respuesta, reverse('roles:detalle', args=[self.administrador.pk]), fetch_redirect_response=False)
        self.administrador.refresh_from_db()
        self.assertEqual(self.administrador.nombre, 'Administrador')

    def test_nadie_edita_el_rol_que_el_mismo_tiene(self):
        gestor = self.entrar_como(self.gestor_de_roles())
        propio = Rol.objects.get(grupo__user=gestor)
        respuesta = self.client.post(reverse('roles:editar', args=[propio.pk]), datos_de_rol({'Usuarios.view_rol'}, nombre=propio.nombre))
        self.assertRedirects(respuesta, reverse('roles:detalle', args=[propio.pk]), fetch_redirect_response=False)
        self.assertIn('Usuarios.delete_rol', permisos_de_rol(propio))   # no cambió nada

    def test_un_superusuario_si_puede_editar_su_propio_rol_pero_el_del_sistema_no(self):
        self.assertTrue(self.admin.is_superuser)
        self.assertEqual(self.client.get(reverse('roles:editar', args=[self.rol.pk])).status_code, 200)

    def test_no_se_edita_un_rol_con_mas_permisos_que_quien_edita(self):
        """Quien administra roles no puede recortar ni apagar uno más poderoso que el suyo."""
        self.entrar_como(self.gestor_de_roles())
        mayor = crear_rol('Mayor', {'Alumnos.view_alumno', 'Usuarios.view_rol'})
        self.assertEqual(self.client.get(reverse('roles:editar', args=[mayor.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse('roles:editar', args=[mayor.pk]), datos_de_rol(nombre='Mayor')).status_code, 403)
        self.assertEqual(self.client.post(reverse('roles:baja', args=[mayor.pk])).status_code, 403)
        Rol.objects.filter(pk=mayor.pk).update(activo=False)
        self.assertEqual(self.client.post(reverse('roles:reactivar', args=[mayor.pk])).status_code, 403)
        self.assertEqual(permisos_de_rol(mayor), {'Alumnos.view_alumno', 'Usuarios.view_rol'})

    def test_si_edita_un_rol_con_los_mismos_permisos_o_menos(self):
        self.entrar_como(self.gestor_de_roles())
        menor = crear_rol('Menor', {'Usuarios.view_rol'})
        respuesta = self.client.post(reverse('roles:editar', args=[menor.pk]), datos_de_rol(set(), nombre='Menor renombrado'))
        self.assertEqual(respuesta.status_code, 302)
        menor.refresh_from_db()
        self.assertEqual(menor.nombre, 'Menor renombrado')
        self.assertEqual(permisos_de_rol(menor), set())

    def test_el_listado_y_el_perfil_no_ofrecen_editar_un_rol_mayor(self):
        mayor = crear_rol('Mayor', {'Alumnos.view_alumno', 'Usuarios.view_rol'})
        menor = crear_rol('Menor', {'Usuarios.view_rol'})
        self.entrar_como(self.gestor_de_roles())
        html = self.client.get(reverse('roles:lista')).content.decode()
        self.assertNotIn(reverse('roles:editar', args=[mayor.pk]), html)
        self.assertIn(reverse('roles:editar', args=[menor.pk]), html)
        perfil = self.client.get(reverse('roles:detalle', args=[mayor.pk])).content.decode()
        self.assertNotIn(reverse('roles:editar', args=[mayor.pk]), perfil)
        self.assertNotIn('data-modal-open="modal-baja"', perfil)

    def test_un_rol_inexistente_es_404(self):
        self.assertEqual(self.client.get(reverse('roles:editar', args=[99999])).status_code, 404)


# ---------------------------------------------------------------------------
# Perfil del rol
# ---------------------------------------------------------------------------
class PerfilDeRolTests(BaseRolesTestCase):
    def test_muestra_lo_que_permite_sus_usuarios_y_su_actividad(self):
        crear_usuario('lupita', self.docente, first_name='Lupita', last_name='Soto')
        html = self.client.get(reverse('roles:detalle', args=[self.docente.pk])).content.decode()
        self.assertIn('Lo que permite este rol', html)
        self.assertIn('Pase de lista por materia', html)
        self.assertIn('Lupita Soto', html)
        self.assertIn('Actividad del rol', html)
        self.assertIn('Sin acceso a:', html)

    def test_el_administrador_lista_tambien_a_los_superusuarios_sin_grupo(self):
        html = self.client.get(reverse('roles:detalle', args=[self.administrador.pk])).content.decode()
        self.assertIn('admin', html)
        self.assertIn('Rol del sistema', html)
        self.assertNotIn('Sin acceso a:', html)

    def test_los_botones_dependen_de_los_permisos(self):
        html = self.client.get(reverse('roles:detalle', args=[self.docente.pk])).content.decode()
        self.assertIn('data-modal-open="modal-baja"', html)
        self.assertIn(reverse('roles:editar', args=[self.docente.pk]), html)
        self.assertIn(reverse('roles:copiar', args=[self.docente.pk]), html)
        self.entrar_como(self.gestor_de_roles(('Usuarios.view_rol',), 'lector'))
        html = self.client.get(reverse('roles:detalle', args=[self.docente.pk])).content.decode()
        self.assertNotIn('data-modal-open="modal-baja"', html)
        self.assertNotIn(reverse('roles:editar', args=[self.docente.pk]), html)
        self.assertNotIn(reverse('roles:copiar', args=[self.docente.pk]), html)

    def test_el_rol_del_sistema_no_ofrece_editar_ni_desactivar(self):
        html = self.client.get(reverse('roles:detalle', args=[self.administrador.pk])).content.decode()
        self.assertNotIn('data-modal-open="modal-baja"', html)
        self.assertNotIn(reverse('roles:editar', args=[self.administrador.pk]), html)

    def test_exige_permiso_para_ver(self):
        self.entrar_como(self.sin_permisos)
        self.assertEqual(self.client.get(reverse('roles:detalle', args=[self.docente.pk])).status_code, 403)


# ---------------------------------------------------------------------------
# Copiar
# ---------------------------------------------------------------------------
class CopiarRolTests(BaseRolesTestCase):
    def test_crea_una_copia_con_los_mismos_permisos(self):
        respuesta = self.client.post(reverse('roles:copiar', args=[self.docente.pk]))
        copia = Rol.objects.get(grupo__name='Copia de Docente')
        self.assertRedirects(respuesta, reverse('roles:detalle', args=[copia.pk]), fetch_redirect_response=False)
        self.assertEqual(permisos_de_rol(copia), permisos_de_rol(self.docente))
        self.assertEqual((copia.descripcion, copia.tono), (self.docente.descripcion, self.docente.tono))
        self.assertTrue(copia.activo and not copia.es_sistema and not copia.acceso_total)
        self.assertTrue(bitacora(copia, ADDITION).exists())

    def test_las_copias_siguientes_no_repiten_nombre(self):
        for _ in range(3):
            self.client.post(reverse('roles:copiar', args=[self.docente.pk]))
        nombres = set(Group.objects.filter(name__startswith='Copia de Docente').values_list('name', flat=True))
        self.assertEqual(nombres, {'Copia de Docente', 'Copia de Docente (2)', 'Copia de Docente (3)'})

    def test_la_copia_no_tiene_usuarios(self):
        crear_usuario('lupita', self.docente)
        self.client.post(reverse('roles:copiar', args=[self.docente.pk]))
        copia = Rol.objects.get(grupo__name='Copia de Docente')
        self.assertEqual(Usuario.objects.filter(groups=copia.grupo).count(), 0)

    def test_copiar_el_administrador_no_da_acceso_total(self):
        self.client.post(reverse('roles:copiar', args=[self.administrador.pk]))
        copia = Rol.objects.get(grupo__name='Copia de Administrador')
        self.assertFalse(copia.acceso_total or copia.es_sistema)
        self.assertEqual(permisos_de_rol(copia), set(catalogo.TODOS))   # los permisos sí, pero como un rol normal

    def test_quien_copia_solo_se_lleva_los_permisos_que_tiene(self):
        self.entrar_como(self.gestor_de_roles())
        self.client.post(reverse('roles:copiar', args=[self.docente.pk]))
        copia = Rol.objects.get(grupo__name='Copia de Docente')
        self.assertEqual(permisos_de_rol(copia), set())   # el gestor no tiene ninguno de los del docente

    def test_exige_permiso_de_alta_y_post(self):
        self.assertEqual(self.client.get(reverse('roles:copiar', args=[self.docente.pk])).status_code, 405)
        self.entrar_como(self.gestor_de_roles(('Usuarios.view_rol', 'Usuarios.change_rol'), 'sin_alta'))
        self.assertEqual(self.client.post(reverse('roles:copiar', args=[self.docente.pk])).status_code, 403)


# ---------------------------------------------------------------------------
# Desactivar y reactivar
# ---------------------------------------------------------------------------
class DesactivarRolTests(BaseRolesTestCase):
    def setUp(self):
        super().setUp()
        self.rol = crear_rol('Temporal', {'Alumnos.view_alumno'})

    def test_desactiva_un_rol_sin_usuarios_y_no_lo_borra(self):
        respuesta = self.client.post(reverse('roles:baja', args=[self.rol.pk]))
        self.assertRedirects(respuesta, reverse('roles:lista'), fetch_redirect_response=False)
        self.rol.refresh_from_db()
        self.assertFalse(self.rol.activo)
        self.assertTrue(Group.objects.filter(pk=self.rol.grupo_id).exists())
        self.assertTrue(bitacora(self.rol, DELETION).exists())

    def test_no_se_desactiva_un_rol_con_usuarios_activos(self):
        crear_usuario('lupita', self.rol)
        respuesta = self.client.post(reverse('roles:baja', args=[self.rol.pk]), follow=True)
        self.assertContains(respuesta, 'lo tienen 1 usuario activo')
        self.rol.refresh_from_db()
        self.assertTrue(self.rol.activo)

    def test_los_usuarios_desactivados_no_impiden_desactivar_el_rol(self):
        crear_usuario('baja', self.rol, is_active=False)
        self.client.post(reverse('roles:baja', args=[self.rol.pk]))
        self.rol.refresh_from_db()
        self.assertFalse(self.rol.activo)

    def test_el_rol_del_sistema_no_se_desactiva(self):
        self.client.post(reverse('roles:baja', args=[self.administrador.pk]))
        self.administrador.refresh_from_db()
        self.assertTrue(self.administrador.activo)

    def test_un_rol_desactivado_no_se_asigna_pero_conserva_a_sus_usuarios_antiguos(self):
        persona = crear_usuario('antigua', self.rol, is_active=False)
        self.client.post(reverse('roles:baja', args=[self.rol.pk]))
        persona.refresh_from_db()
        from Usuarios.seguridad import puede_asignar, rol_de
        self.assertEqual(rol_de(persona), self.rol)
        self.assertFalse(puede_asignar(self.admin, Rol.objects.get(pk=self.rol.pk)))

    def test_reactivar_lo_devuelve_al_catalogo(self):
        Rol.objects.filter(pk=self.rol.pk).update(activo=False)
        respuesta = self.client.post(reverse('roles:reactivar', args=[self.rol.pk]))
        self.assertRedirects(respuesta, reverse('roles:lista'), fetch_redirect_response=False)
        self.rol.refresh_from_db()
        self.assertTrue(self.rol.activo)
        self.assertTrue(bitacora(self.rol, CHANGE).filter(change_message__contains='reactivado').exists())

    def test_desactivar_desde_el_perfil_vuelve_al_perfil(self):
        respuesta = self.client.post(reverse('roles:baja', args=[self.rol.pk]), {'volver': 'detalle'})
        self.assertRedirects(respuesta, reverse('roles:detalle', args=[self.rol.pk]), fetch_redirect_response=False)

    def test_exige_permisos_y_post(self):
        self.assertEqual(self.client.get(reverse('roles:baja', args=[self.rol.pk])).status_code, 405)
        self.entrar_como(self.gestor_de_roles(('Usuarios.view_rol', 'Usuarios.change_rol'), 'sin_baja'))
        self.assertEqual(self.client.post(reverse('roles:baja', args=[self.rol.pk])).status_code, 403)
        Rol.objects.filter(pk=self.rol.pk).update(activo=False)
        self.entrar_como(self.gestor_de_roles(('Usuarios.view_rol', 'Usuarios.delete_rol'), 'sin_edicion'))
        self.assertEqual(self.client.post(reverse('roles:reactivar', args=[self.rol.pk])).status_code, 403)


# ---------------------------------------------------------------------------
# Archivos estáticos que usan las pantallas de usuarios y roles
# ---------------------------------------------------------------------------
class RecursosDeUsuariosYRolesTests(BaseRolesTestCase):
    def test_existen_los_archivos_que_cargan_las_plantillas(self):
        from pathlib import Path

        from django.conf import settings
        raiz = Path(settings.BASE_DIR)
        for ruta in ('static/css/seguridad.css', 'static/js/roles.js', 'static/js/usuarios-form.js'):
            self.assertTrue((raiz / ruta).is_file(), ruta)

    def test_cada_pantalla_carga_su_hoja_de_estilos_y_su_script(self):
        rol = crear_rol('Para recursos', {'Alumnos.view_alumno'})
        paginas = {
            reverse('usuarios:lista'): ('css/seguridad.css', None),
            reverse('usuarios:crear'): ('css/seguridad.css', 'js/usuarios-form.js'),
            reverse('usuarios:detalle', args=[self.admin.pk]): ('css/seguridad.css', None),
            reverse('roles:lista'): ('css/seguridad.css', None),
            reverse('roles:crear'): ('css/seguridad.css', 'js/roles.js'),
            reverse('roles:editar', args=[rol.pk]): ('css/seguridad.css', 'js/roles.js'),
            reverse('roles:detalle', args=[rol.pk]): ('css/seguridad.css', None),
            reverse('cuenta:perfil'): ('css/seguridad.css', None),
            reverse('cuenta:contrasena'): ('css/seguridad.css', None),
        }
        for url, (hoja, script) in paginas.items():
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                self.assertIn(hoja, html)
                if script:
                    self.assertIn(script, html)

    def test_las_credenciales_temporales_tienen_su_estilo_en_la_hoja_comun(self):
        """La tarjeta la usan alumnos y usuarios: su CSS está en app.css, no en la hoja de una sola sección."""
        from pathlib import Path

        from django.conf import settings
        css = Path(settings.BASE_DIR) / 'static/css'
        self.assertIn('.credentials {', (css / 'app.css').read_text(encoding='utf-8'))
        self.assertNotIn('.credentials {', (css / 'alumnos.css').read_text(encoding='utf-8'))
