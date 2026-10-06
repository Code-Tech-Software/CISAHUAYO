"""Módulo de usuarios: listado, alta, edición, desactivación, contraseñas, «Mi cuenta» y permisos dinámicos."""
from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import Client
from django.urls import reverse

from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase, crear_rol, crear_usuario
from Usuarios.models import PerfilUsuario, Rol
from Usuarios.seguridad import (
    asignar_rol,
    es_ultimo_administrador,
    puede_asignar,
    puede_gestionar,
    rol_de,
)

Usuario = get_user_model()
SOLO_CUENTAS = {'auth.view_user', 'auth.add_user', 'auth.change_user', 'auth.delete_user'}


def datos_de_alta(rol_inicial, **cambios):
    datos = {
        'first_name': 'María José', 'last_name': 'Núñez Ruiz', 'username': 'maria.nunez', 'email': 'maria@example.com',
        'telefono': '353 123 4567', 'cargo': 'Secretaria', 'rol': rol_inicial.pk,
    }
    datos.update(cambios)
    return datos


def bitacora(objeto, accion=None):
    consulta = LogEntry.objects.filter(content_type=ContentType.objects.get_for_model(objeto), object_id=str(objeto.pk))
    return consulta.filter(action_flag=accion) if accion else consulta


@PRUEBAS
class BaseUsuariosTestCase(BaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.docente = Rol.objects.get(grupo__name='Docente')
        cls.direccion = Rol.objects.get(grupo__name='Dirección')
        cls.recepcion = Rol.objects.get(grupo__name='Recepción')
        cls.administrador = Rol.objects.get(acceso_total=True)

    def entrar_como(self, usuario):
        self.client.force_login(usuario)
        return usuario

    def gestor(self, permisos=SOLO_CUENTAS, nombre='gestor'):
        """Una cuenta con un rol que solo administra cuentas."""
        rol = crear_rol(f'Gestor de {nombre}', permisos)
        return crear_usuario(nombre, rol)


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------
class ListadoDeUsuariosTests(BaseUsuariosTestCase):
    def test_exige_permiso_para_ver_usuarios(self):
        self.entrar_como(self.sin_permisos)
        self.assertEqual(self.client.get(reverse('usuarios:lista')).status_code, 403)

    def test_muestra_las_cuentas_con_su_rol(self):
        crear_usuario('lupita', self.docente, first_name='Lupita', last_name='Soto')
        html = self.client.get(reverse('usuarios:lista')).content.decode()
        self.assertIn('Lupita Soto', html)
        self.assertIn('@lupita', html)
        self.assertIn('Docente', html)

    def test_un_superusuario_sin_grupo_cuenta_como_administrador(self):
        self.assertEqual(rol_de(self.admin), self.administrador)
        self.assertIn('Administrador', self.client.get(reverse('usuarios:lista')).content.decode())

    def test_busca_por_nombre_usuario_correo_y_cargo(self):
        usuario = crear_usuario('beto', self.docente, first_name='Alberto', last_name='Mora', email='beto@escuela.mx')
        perfil = PerfilUsuario.de(usuario)
        perfil.cargo = 'Prefecto'
        perfil.save()
        crear_usuario('otra', self.docente, first_name='Otra', last_name='Persona')
        for consulta in ('Alberto', 'beto', 'escuela.mx', 'prefecto', 'Alberto Mora'):
            with self.subTest(consulta=consulta):
                html = self.client.get(reverse('usuarios:lista'), {'q': consulta}).content.decode()
                self.assertIn('@beto', html)
                self.assertNotIn('@otra', html)

    def test_filtra_por_rol_y_por_sin_rol(self):
        crear_usuario('docente1', self.docente)
        crear_usuario('directora1', self.direccion)
        crear_usuario('sinrol')
        html = self.client.get(reverse('usuarios:lista'), {'rol': self.docente.pk}).content.decode()
        self.assertIn('@docente1', html)
        self.assertNotIn('@directora1', html)
        html = self.client.get(reverse('usuarios:lista'), {'rol': 'sin'}).content.decode()
        self.assertIn('@sinrol', html)
        self.assertNotIn('@docente1', html)
        self.assertNotIn('@admin', html)   # los superusuarios cuentan como administradores

    def test_filtrar_por_administrador_incluye_a_los_superusuarios(self):
        html = self.client.get(reverse('usuarios:lista'), {'rol': self.administrador.pk}).content.decode()
        self.assertIn('@admin', html)

    def test_las_cuentas_desactivadas_tienen_su_propio_filtro(self):
        crear_usuario('baja1', self.docente, is_active=False)
        crear_usuario('vigente', self.docente)
        activos = self.client.get(reverse('usuarios:lista')).content.decode()
        self.assertIn('@vigente', activos)
        self.assertNotIn('@baja1', activos)
        inactivos = self.client.get(reverse('usuarios:lista'), {'estado': 'INACTIVO'}).content.decode()
        self.assertIn('@baja1', inactivos)
        self.assertNotIn('@vigente', inactivos)

    def test_sin_permiso_de_alta_no_ofrece_nuevo_usuario(self):
        solo_ver = self.entrar_como(self.gestor({'auth.view_user'}, 'lector'))
        html = self.client.get(reverse('usuarios:lista')).content.decode()
        self.assertNotIn('Nuevo usuario', html)
        self.assertNotIn(reverse('usuarios:editar', args=[self.admin.pk]), html)
        self.assertEqual(solo_ver.has_perm('auth.add_user'), False)

    def test_pagina_los_resultados(self):
        for n in range(25):
            crear_usuario(f'persona{n:02d}', self.docente)
        pagina = self.client.get(reverse('usuarios:lista'), {'por_pagina': 10}).content.decode()
        self.assertIn('pagination', pagina)
        self.assertEqual(pagina.count('class="person"'), 10)

    def test_no_hace_una_consulta_por_fila(self):
        """Ni para el administrador ni para quien administra cuentas sin ser superusuario (calcula a quién puede gestionar)."""
        for quien in (self.admin, self.gestor()):
            self.client.force_login(quien)
            self.client.get(reverse('usuarios:lista'))   # calienta cachés (tipos de contenido)
            for n in range(12):
                crear_usuario(f'{quien.username}a{n:02d}', self.docente)
            antes = self.consultas_del_listado()
            for n in range(12, 30):
                crear_usuario(f'{quien.username}a{n:02d}', self.docente)
            self.assertEqual(self.consultas_del_listado(), antes, f'el listado hace consultas por fila para {quien.username}')

    def consultas_del_listado(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as capturadas:
            self.client.get(reverse('usuarios:lista'), {'por_pagina': 100})
        return len(capturadas)


# ---------------------------------------------------------------------------
# Alta
# ---------------------------------------------------------------------------
class AltaDeUsuariosTests(BaseUsuariosTestCase):
    def test_exige_permiso_para_crear(self):
        self.entrar_como(self.gestor({'auth.view_user'}, 'lector'))
        self.assertEqual(self.client.get(reverse('usuarios:crear')).status_code, 403)
        self.assertEqual(self.client.post(reverse('usuarios:crear'), datos_de_alta(self.docente)).status_code, 403)
        self.assertFalse(Usuario.objects.filter(username='maria.nunez').exists())

    def test_crea_la_cuenta_con_rol_y_contrasena_temporal(self):
        respuesta = self.client.post(reverse('usuarios:crear'), datos_de_alta(self.recepcion))
        self.assertRedirects(respuesta, reverse('usuarios:lista'), fetch_redirect_response=False)
        usuario = Usuario.objects.get(username='maria.nunez')
        self.assertEqual((usuario.first_name, usuario.last_name, usuario.email), ('María José', 'Núñez Ruiz', 'maria@example.com'))
        self.assertTrue(usuario.is_active)
        self.assertFalse(usuario.is_staff)
        self.assertFalse(usuario.is_superuser)
        self.assertEqual(rol_de(usuario), self.recepcion)
        perfil = usuario.perfil
        self.assertEqual((perfil.telefono, perfil.cargo), ('3531234567', 'Secretaria'))
        self.assertTrue(perfil.debe_cambiar_contrasena)

    def test_la_contrasena_temporal_se_muestra_una_sola_vez_y_funciona(self):
        self.client.post(reverse('usuarios:crear'), datos_de_alta(self.recepcion))
        temporal = self.client.session['credenciales_usuario']['contrasena']
        self.assertGreaterEqual(len(temporal), 8)
        usuario = Usuario.objects.get(username='maria.nunez')
        self.assertTrue(usuario.check_password(temporal))
        self.assertNotEqual(usuario.password, temporal)   # se guarda cifrada

        primera = self.client.get(reverse('usuarios:lista')).content.decode()
        self.assertIn(temporal, primera)
        self.assertIn('no se volverá a mostrar', primera)
        segunda = self.client.get(reverse('usuarios:lista')).content.decode()
        self.assertNotIn(temporal, segunda)

    def test_avisa_con_un_mensaje_y_deja_bitacora(self):
        respuesta = self.client.post(reverse('usuarios:crear'), datos_de_alta(self.recepcion), follow=True)
        self.assertContains(respuesta, 'fue creada con el rol')
        usuario = Usuario.objects.get(username='maria.nunez')
        entrada = bitacora(usuario, ADDITION).get()
        self.assertEqual(entrada.user, self.admin)
        self.assertIn('Recepción', entrada.change_message)

    def test_el_usuario_se_guarda_en_minusculas(self):
        self.client.post(reverse('usuarios:crear'), datos_de_alta(self.recepcion, username='Maria.Nunez'))
        self.assertTrue(Usuario.objects.filter(username='maria.nunez').exists())

    def test_responde_con_json_cuando_se_envia_desde_la_ventana(self):
        respuesta = self.client.post(reverse('usuarios:crear'), datos_de_alta(self.recepcion), HTTP_X_MODAL_FORM='1')
        self.assertEqual(respuesta.json(), {'redirect': reverse('usuarios:lista')})

    def test_rechaza_datos_incorrectos(self):
        crear_usuario('ocupado', self.docente, email='ocupado@example.com')
        casos = {
            'usuario repetido (sin importar mayúsculas)': ({'username': 'OCUPADO'}, 'Ya existe una cuenta con ese usuario.'),
            'usuario con espacios': ({'username': 'con espacios'}, 'minúsculas, números'),
            'usuario muy corto': ({'username': 'ab'}, 'de 3 a 30'),
            'símbolos raros': ({'username': 'a@b!'}, 'minúsculas, números'),
            'correo repetido': ({'email': 'OCUPADO@example.com'}, 'Ya hay una cuenta con ese correo'),
            'sin nombre': ({'first_name': ''}, 'obligatorio'),
            'sin apellidos': ({'last_name': ''}, 'obligatorio'),
            'teléfono incompleto': ({'telefono': '123'}, '10 dígitos'),
        }
        for nombre, (cambios, texto) in casos.items():
            with self.subTest(caso=nombre):
                respuesta = self.client.post(reverse('usuarios:crear'), datos_de_alta(self.recepcion, **cambios))
                self.assertEqual(respuesta.status_code, 200)
                self.assertContains(respuesta, texto)
        self.assertFalse(Usuario.objects.filter(username='maria.nunez').exists())

    def test_el_rol_es_obligatorio_y_debe_existir(self):
        for rol in ('', '99999'):
            respuesta = self.client.post(reverse('usuarios:crear'), datos_de_alta(self.docente, rol=rol))
            self.assertEqual(respuesta.status_code, 200)
            self.assertContains(respuesta, 'field__error')
        self.assertFalse(Usuario.objects.filter(username='maria.nunez').exists())

    def test_un_rol_desactivado_no_se_puede_asignar(self):
        Rol.objects.filter(pk=self.docente.pk).update(activo=False)
        respuesta = self.client.post(reverse('usuarios:crear'), datos_de_alta(self.docente))
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Usuario.objects.filter(username='maria.nunez').exists())

    def test_el_rol_administrador_da_acceso_total_y_entrada_al_admin_de_django(self):
        self.client.post(reverse('usuarios:crear'), datos_de_alta(self.administrador))
        usuario = Usuario.objects.get(username='maria.nunez')
        self.assertTrue(usuario.is_superuser)
        self.assertTrue(usuario.is_staff)

    def test_el_formulario_ofrece_solo_roles_activos(self):
        crear_rol('Rol apagado', {'Alumnos.view_alumno'}, activo=False)
        html = self.client.get(reverse('usuarios:crear')).content.decode()
        self.assertIn('Docente', html)
        self.assertNotIn('Rol apagado', html)


class NadieDaPermisosQueNoTieneTests(BaseUsuariosTestCase):
    """Quien administra cuentas no puede darse (ni dar) más poder del que tiene."""

    def test_solo_ofrece_roles_cuyos_permisos_ya_tiene(self):
        solo_cuentas = crear_rol('Solo cuentas', {'auth.view_user'})
        gestor = self.entrar_como(self.gestor())
        html = self.client.get(reverse('usuarios:crear')).content.decode()
        self.assertIn('Solo cuentas', html)
        self.assertNotIn('Dirección', html)
        self.assertNotIn('Administrador', html)
        self.assertTrue(puede_asignar(gestor, solo_cuentas))
        self.assertFalse(puede_asignar(gestor, self.direccion))
        self.assertFalse(puede_asignar(gestor, self.administrador))

    def test_un_envio_manipulado_con_un_rol_mayor_se_rechaza(self):
        self.entrar_como(self.gestor())
        respuesta = self.client.post(reverse('usuarios:crear'), datos_de_alta(self.administrador))
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Usuario.objects.filter(username='maria.nunez').exists())

    def test_no_edita_a_quien_tiene_mas_permisos_que_el(self):
        self.entrar_como(self.gestor())
        jefa = crear_usuario('jefa', self.direccion)
        for nombre in ('usuarios:editar', 'usuarios:baja', 'usuarios:reactivar', 'usuarios:restablecer'):
            with self.subTest(vista=nombre):
                self.assertEqual(self.client.post(reverse(nombre, args=[jefa.pk]), {}).status_code, 403)
        self.assertEqual(self.client.get(reverse('usuarios:editar', args=[jefa.pk])).status_code, 403)
        self.assertFalse(puede_gestionar(Usuario.objects.get(username='gestor'), jefa))

    def test_no_toca_a_un_superusuario(self):
        self.entrar_como(self.gestor())
        self.assertEqual(self.client.post(reverse('usuarios:baja', args=[self.admin.pk])).status_code, 403)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_si_gestiona_a_quien_tiene_lo_mismo_o_menos(self):
        rol_menor = crear_rol('Solo ver cuentas', {'auth.view_user'})
        otra = crear_usuario('menor', rol_menor)
        self.entrar_como(self.gestor())
        self.assertEqual(self.client.get(reverse('usuarios:editar', args=[otra.pk])).status_code, 200)

    def test_el_listado_no_ofrece_editar_a_quien_no_puede_gestionar(self):
        jefa = crear_usuario('jefa', self.direccion)
        menor = crear_usuario('menor', crear_rol('Solo ver cuentas', {'auth.view_user'}))
        self.entrar_como(self.gestor())
        html = self.client.get(reverse('usuarios:lista')).content.decode()
        self.assertNotIn(reverse('usuarios:editar', args=[jefa.pk]), html)
        self.assertIn(reverse('usuarios:editar', args=[menor.pk]), html)


# ---------------------------------------------------------------------------
# Edición
# ---------------------------------------------------------------------------
class EdicionDeUsuariosTests(BaseUsuariosTestCase):
    def setUp(self):
        super().setUp()
        self.usuario = crear_usuario('lupita', self.docente, first_name='Lupita', last_name='Soto', email='lupita@example.com')

    def datos(self, **cambios):
        datos = {'first_name': 'Lupita', 'last_name': 'Soto', 'username': 'lupita', 'email': 'lupita@example.com',
                 'telefono': '', 'cargo': '', 'rol': self.docente.pk}
        datos.update(cambios)
        return datos

    def test_el_formulario_trae_los_datos_actuales(self):
        html = self.client.get(reverse('usuarios:editar', args=[self.usuario.pk])).content.decode()
        self.assertIn('value="Lupita"', html)
        self.assertIn('value="lupita@example.com"', html)
        self.assertRegex(html, r'<option value="%d" selected>Docente</option>' % self.docente.pk)

    def test_guarda_los_cambios_y_vuelve_al_listado(self):
        respuesta = self.client.post(
            reverse('usuarios:editar', args=[self.usuario.pk]), self.datos(first_name='Guadalupe', cargo='Maestra de 3°', telefono='3535550000'),
        )
        self.assertRedirects(respuesta, reverse('usuarios:lista'), fetch_redirect_response=False)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.first_name, 'Guadalupe')
        self.assertEqual(self.usuario.perfil.cargo, 'Maestra de 3°')
        self.assertEqual(self.usuario.perfil.telefono, '3535550000')
        self.assertIn('Datos modificados', bitacora(self.usuario, CHANGE).get().change_message)

    def test_cambiar_el_rol_cambia_lo_que_puede_hacer_al_instante(self):
        self.assertFalse(self.usuario.has_perm('Alumnos.add_alumno'))
        self.client.post(reverse('usuarios:editar', args=[self.usuario.pk]), self.datos(rol=self.direccion.pk))
        usuario = Usuario.objects.get(pk=self.usuario.pk)
        self.assertEqual(rol_de(usuario), self.direccion)
        self.assertTrue(usuario.has_perm('Alumnos.add_alumno'))
        self.assertEqual(usuario.groups.count(), 1)   # un solo rol: el anterior se quita
        self.assertIn('Docente → Dirección', bitacora(usuario, CHANGE).get().change_message)

    def test_pasar_de_administrador_a_otro_rol_quita_el_acceso_total(self):
        otra_admin = crear_usuario('otra_admin', self.administrador)
        self.assertTrue(otra_admin.is_superuser)
        self.client.post(reverse('usuarios:editar', args=[otra_admin.pk]), self.datos(username='otra_admin', rol=self.recepcion.pk, email='', first_name='Otra_admin', last_name='Prueba'))
        otra_admin.refresh_from_db()
        self.assertFalse(otra_admin.is_superuser)
        self.assertFalse(otra_admin.is_staff)

    def test_nadie_cambia_su_propio_rol(self):
        gestor = self.entrar_como(self.gestor())
        propio = rol_de(gestor)
        respuesta = self.client.post(reverse('usuarios:editar', args=[gestor.pk]), {
            'first_name': 'Nuevo', 'last_name': 'Nombre', 'username': 'gestor', 'email': '', 'telefono': '', 'cargo': '',
            'rol': self.direccion.pk,
        })
        self.assertRedirects(respuesta, reverse('usuarios:lista'), fetch_redirect_response=False)
        gestor = Usuario.objects.get(pk=gestor.pk)
        self.assertEqual(gestor.first_name, 'Nuevo')      # sus datos sí
        self.assertEqual(rol_de(gestor), propio)           # el rol no
        self.assertIn('No puedes cambiar tu propio rol', self.client.get(reverse('usuarios:editar', args=[gestor.pk])).content.decode())

    def test_el_unico_administrador_conserva_su_rol(self):
        self.assertTrue(es_ultimo_administrador(self.admin))
        self.client.post(reverse('usuarios:editar', args=[self.admin.pk]), {
            'first_name': 'Admin', 'last_name': 'Prueba', 'username': 'admin', 'email': 'admin@example.com',
            'telefono': '', 'cargo': '', 'rol': self.docente.pk,
        })
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_superuser)

    def test_otro_administrador_si_puede_cambiarle_el_rol_al_segundo(self):
        segundo = crear_usuario('segundo', self.administrador)
        self.assertFalse(es_ultimo_administrador(segundo))
        self.client.post(reverse('usuarios:editar', args=[segundo.pk]), self.datos(username='segundo', first_name='Segundo', last_name='Prueba', email='', rol=self.recepcion.pk))
        segundo.refresh_from_db()
        self.assertEqual(rol_de(segundo), self.recepcion)

    def test_una_cuenta_antigua_con_usuario_en_mayusculas_se_puede_editar(self):
        antigua = Usuario.objects.create_user('Antigua', password='x', first_name='A', last_name='B')
        asignar_rol(antigua, self.docente)
        respuesta = self.client.post(reverse('usuarios:editar', args=[antigua.pk]), self.datos(username='Antigua', first_name='Ana', last_name='B', email=''))
        self.assertRedirects(respuesta, reverse('usuarios:lista'), fetch_redirect_response=False)

    def test_exige_permiso_para_editar(self):
        self.entrar_como(self.gestor({'auth.view_user'}, 'lector'))
        self.assertEqual(self.client.get(reverse('usuarios:editar', args=[self.usuario.pk])).status_code, 403)

    def test_un_usuario_inexistente_es_404(self):
        self.assertEqual(self.client.get(reverse('usuarios:editar', args=[99999])).status_code, 404)


# ---------------------------------------------------------------------------
# Perfil
# ---------------------------------------------------------------------------
class PerfilDeUsuarioTests(BaseUsuariosTestCase):
    def test_muestra_los_permisos_del_rol_y_la_actividad(self):
        usuario = crear_usuario('lupita', self.docente, first_name='Lupita', last_name='Soto')
        html = self.client.get(reverse('usuarios:detalle', args=[usuario.pk])).content.decode()
        self.assertIn('Lupita Soto', html)
        self.assertIn('Docente', html)
        self.assertIn('Pase de lista por materia', html)
        self.assertIn('Pasar lista', html)
        self.assertIn('Sin acceso a:', html)
        self.assertIn('Actividad de la cuenta', html)

    def test_una_cuenta_sin_rol_lo_advierte(self):
        usuario = crear_usuario('sinrol')
        html = self.client.get(reverse('usuarios:detalle', args=[usuario.pk])).content.decode()
        self.assertIn('no tiene un rol', html)

    def test_el_administrador_muestra_todo_el_catalogo(self):
        html = self.client.get(reverse('usuarios:detalle', args=[self.admin.pk])).content.decode()
        self.assertNotIn('Sin acceso a:', html)

    def test_una_cuenta_desactivada_muestra_lo_que_tendria_al_reactivarla(self):
        usuario = crear_usuario('baja1', self.docente, is_active=False)
        html = self.client.get(reverse('usuarios:detalle', args=[usuario.pk])).content.decode()
        self.assertIn('Cuenta desactivada', html)
        self.assertIn('Pase de lista por materia', html)

    def test_exige_permiso_para_ver(self):
        self.entrar_como(self.sin_permisos)
        self.assertEqual(self.client.get(reverse('usuarios:detalle', args=[self.admin.pk])).status_code, 403)

    def test_los_botones_dependen_de_los_permisos(self):
        objetivo = crear_usuario('objetivo', crear_rol('Solo ver cuentas', {'auth.view_user'}))
        html = self.client.get(reverse('usuarios:detalle', args=[objetivo.pk])).content.decode()
        self.assertIn('data-modal-open="modal-baja"', html)
        self.assertIn('data-modal-open="modal-restablecer"', html)
        self.entrar_como(self.gestor({'auth.view_user'}, 'lector'))
        html = self.client.get(reverse('usuarios:detalle', args=[objetivo.pk])).content.decode()
        self.assertNotIn('data-modal-open="modal-baja"', html)
        self.assertNotIn('data-modal-open="modal-restablecer"', html)
        self.assertNotIn(reverse('usuarios:editar', args=[objetivo.pk]), html)

    def test_en_el_propio_perfil_no_se_ofrece_desactivar_ni_restablecer(self):
        html = self.client.get(reverse('usuarios:detalle', args=[self.admin.pk])).content.decode()
        self.assertNotIn('data-modal-open="modal-baja"', html)
        self.assertNotIn('data-modal-open="modal-restablecer"', html)


# ---------------------------------------------------------------------------
# Desactivar y reactivar
# ---------------------------------------------------------------------------
class DesactivarYReactivarTests(BaseUsuariosTestCase):
    def setUp(self):
        super().setUp()
        self.usuario = crear_usuario('lupita', self.docente)

    def test_desactivar_no_borra_y_deja_bitacora(self):
        respuesta = self.client.post(reverse('usuarios:baja', args=[self.usuario.pk]))
        self.assertRedirects(respuesta, reverse('usuarios:lista'), fetch_redirect_response=False)
        self.usuario.refresh_from_db()
        self.assertFalse(self.usuario.is_active)
        self.assertEqual(rol_de(self.usuario), self.docente)   # conserva su rol
        self.assertTrue(bitacora(self.usuario, DELETION).exists())

    def test_una_cuenta_desactivada_ya_no_puede_entrar(self):
        self.client.post(reverse('usuarios:baja', args=[self.usuario.pk]))
        otro = Client()
        respuesta = otro.post(reverse('admin:login'), {'username': 'lupita', 'password': 'x'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertNotIn('_auth_user_id', otro.session)

    def test_si_tenia_una_sesion_abierta_se_cierra_en_su_siguiente_accion(self):
        sesion = Client()
        sesion.force_login(self.usuario)
        self.assertEqual(sesion.get(reverse('alumnos:lista')).status_code, 200)
        self.client.post(reverse('usuarios:baja', args=[self.usuario.pk]))
        respuesta = sesion.get(reverse('alumnos:lista'))
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn('/admin/login/', respuesta['Location'])

    def test_nadie_desactiva_su_propia_cuenta(self):
        gestor = self.entrar_como(self.gestor())
        self.client.post(reverse('usuarios:baja', args=[gestor.pk]))
        gestor.refresh_from_db()
        self.assertTrue(gestor.is_active)

    def test_no_se_desactiva_al_unico_administrador(self):
        otro_gestor = self.gestor(nombre='otro')
        # Un superusuario único distinto de quien actúa: lo simulamos quitándole el acceso total a los demás
        segundo = crear_usuario('segundo_admin', self.administrador)
        Usuario.objects.filter(pk=self.admin.pk).update(is_superuser=False)
        self.entrar_como(segundo)
        self.assertTrue(es_ultimo_administrador(segundo))
        self.client.post(reverse('usuarios:baja', args=[segundo.pk]))
        segundo.refresh_from_db()
        self.assertTrue(segundo.is_active)
        self.assertTrue(otro_gestor.is_active)

    def test_se_puede_desactivar_a_un_administrador_si_hay_otro(self):
        segundo = crear_usuario('segundo_admin', self.administrador)
        self.assertFalse(es_ultimo_administrador(segundo))
        self.client.post(reverse('usuarios:baja', args=[segundo.pk]))
        segundo.refresh_from_db()
        self.assertFalse(segundo.is_active)

    def test_desactivar_exige_permiso_y_post(self):
        self.entrar_como(self.gestor({'auth.view_user', 'auth.change_user'}, 'sin_baja'))
        self.assertEqual(self.client.post(reverse('usuarios:baja', args=[self.usuario.pk])).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('usuarios:baja', args=[self.usuario.pk])).status_code, 405)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.is_active)

    def test_desactivar_desde_el_perfil_vuelve_al_perfil(self):
        respuesta = self.client.post(reverse('usuarios:baja', args=[self.usuario.pk]), {'volver': 'detalle'})
        self.assertRedirects(respuesta, reverse('usuarios:detalle', args=[self.usuario.pk]), fetch_redirect_response=False)

    def test_reactivar_devuelve_el_acceso(self):
        Usuario.objects.filter(pk=self.usuario.pk).update(is_active=False)
        respuesta = self.client.post(reverse('usuarios:reactivar', args=[self.usuario.pk]))
        self.assertRedirects(respuesta, reverse('usuarios:lista'), fetch_redirect_response=False)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.is_active)
        self.assertTrue(bitacora(self.usuario, CHANGE).filter(change_message__contains='reactivada').exists())
        self.assertEqual(Client().post(reverse('admin:login'), {'username': 'lupita', 'password': 'x'}).status_code, 302)

    def test_reactivar_exige_permiso_de_edicion(self):
        Usuario.objects.filter(pk=self.usuario.pk).update(is_active=False)
        self.entrar_como(self.gestor({'auth.view_user', 'auth.delete_user'}, 'sin_edicion'))
        self.assertEqual(self.client.post(reverse('usuarios:reactivar', args=[self.usuario.pk])).status_code, 403)


# ---------------------------------------------------------------------------
# Restablecer contraseña
# ---------------------------------------------------------------------------
class RestablecerContrasenaTests(BaseUsuariosTestCase):
    def setUp(self):
        super().setUp()
        self.usuario = crear_usuario('lupita', self.docente, contrasena='VieJa-clave-77')

    def test_genera_una_contrasena_temporal_nueva_y_la_anterior_deja_de_servir(self):
        respuesta = self.client.post(reverse('usuarios:restablecer', args=[self.usuario.pk]))
        self.assertRedirects(respuesta, reverse('usuarios:detalle', args=[self.usuario.pk]), fetch_redirect_response=False)
        temporal = self.client.session['credenciales_usuario']['contrasena']
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password(temporal))
        self.assertFalse(self.usuario.check_password('VieJa-clave-77'))
        self.assertTrue(self.usuario.perfil.debe_cambiar_contrasena)
        self.assertTrue(bitacora(self.usuario, CHANGE).filter(change_message__contains='restablecida').exists())

    def test_la_muestra_una_sola_vez(self):
        self.client.post(reverse('usuarios:restablecer', args=[self.usuario.pk]))
        temporal = self.client.session['credenciales_usuario']['contrasena']
        url = reverse('usuarios:detalle', args=[self.usuario.pk])
        self.assertIn(temporal, self.client.get(url).content.decode())
        self.assertNotIn(temporal, self.client.get(url).content.decode())

    def test_cierra_su_sesion_abierta(self):
        sesion = Client()
        sesion.force_login(self.usuario)
        self.assertEqual(sesion.get(reverse('alumnos:lista')).status_code, 200)
        self.client.post(reverse('usuarios:restablecer', args=[self.usuario.pk]))
        self.assertEqual(sesion.get(reverse('alumnos:lista')).status_code, 302)

    def test_nadie_restablece_la_propia_con_esta_via(self):
        gestor = self.entrar_como(self.gestor())
        self.client.post(reverse('usuarios:restablecer', args=[gestor.pk]))
        self.assertNotIn('credenciales_usuario', self.client.session)

    def test_no_restablece_la_de_una_cuenta_desactivada(self):
        Usuario.objects.filter(pk=self.usuario.pk).update(is_active=False)
        self.client.post(reverse('usuarios:restablecer', args=[self.usuario.pk]))
        self.assertNotIn('credenciales_usuario', self.client.session)

    def test_exige_permiso_y_post(self):
        self.assertEqual(self.client.get(reverse('usuarios:restablecer', args=[self.usuario.pk])).status_code, 405)
        self.entrar_como(self.gestor({'auth.view_user'}, 'lector'))
        self.assertEqual(self.client.post(reverse('usuarios:restablecer', args=[self.usuario.pk])).status_code, 403)


# ---------------------------------------------------------------------------
# Mi cuenta y contraseña
# ---------------------------------------------------------------------------
class MiCuentaTests(BaseUsuariosTestCase):
    def test_cualquier_cuenta_con_sesion_ve_la_suya_aunque_no_tenga_permisos(self):
        self.entrar_como(self.sin_permisos)
        respuesta = self.client.get(reverse('cuenta:perfil'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Mis datos')

    def test_muestra_su_rol_y_lo_que_puede_hacer(self):
        self.entrar_como(crear_usuario('lupita', self.docente))
        html = self.client.get(reverse('cuenta:perfil')).content.decode()
        self.assertIn('Docente', html)
        self.assertIn('Lo que puedo hacer', html)
        self.assertIn('Pase de lista por materia', html)

    def test_edita_sus_datos_pero_no_su_usuario_ni_su_rol(self):
        usuario = self.entrar_como(crear_usuario('lupita', self.docente))
        respuesta = self.client.post(reverse('cuenta:perfil'), {
            'first_name': 'Guadalupe', 'last_name': 'Soto', 'email': 'lupe@example.com', 'telefono': '353 555 0000',
            'username': 'hackeado', 'rol': self.administrador.pk, 'is_superuser': 'on',
        })
        self.assertRedirects(respuesta, reverse('cuenta:perfil'), fetch_redirect_response=False)
        usuario.refresh_from_db()
        self.assertEqual((usuario.first_name, usuario.email, usuario.perfil.telefono), ('Guadalupe', 'lupe@example.com', '3535550000'))
        self.assertEqual(usuario.username, 'lupita')
        self.assertEqual(rol_de(usuario), self.docente)
        self.assertFalse(usuario.is_superuser)

    def test_no_repite_un_correo_de_otra_cuenta(self):
        crear_usuario('otra', self.docente, email='otra@example.com')
        self.entrar_como(crear_usuario('lupita', self.docente))
        respuesta = self.client.post(reverse('cuenta:perfil'), {'first_name': 'A', 'last_name': 'B', 'email': 'OTRA@example.com', 'telefono': ''})
        self.assertContains(respuesta, 'Ya hay una cuenta con ese correo')

    def test_exige_sesion(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('cuenta:perfil')).status_code, 302)
        self.assertEqual(self.client.get(reverse('cuenta:contrasena')).status_code, 302)


class CambioDeContrasenaTests(BaseUsuariosTestCase):
    def setUp(self):
        super().setUp()
        self.usuario = self.entrar_como(crear_usuario('lupita', self.docente, contrasena='Actual-clave-91'))

    def cambiar(self, **cambios):
        datos = {'old_password': 'Actual-clave-91', 'new_password1': 'Nueva-clave-2026!', 'new_password2': 'Nueva-clave-2026!'}
        datos.update(cambios)
        return self.client.post(reverse('cuenta:contrasena'), datos)

    def test_cambia_la_contrasena_y_conserva_la_sesion(self):
        respuesta = self.cambiar()
        self.assertRedirects(respuesta, reverse('cuenta:perfil'), fetch_redirect_response=False)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password('Nueva-clave-2026!'))
        self.assertEqual(self.client.get(reverse('alumnos:lista')).status_code, 200)   # sigue con sesión

    def test_exige_la_contrasena_actual(self):
        respuesta = self.cambiar(old_password='incorrecta')
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'field__error')
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password('Actual-clave-91'))

    def test_aplica_las_reglas_de_seguridad_de_django(self):
        for debil in ('12345678', 'corta1', 'password'):
            with self.subTest(clave=debil):
                respuesta = self.cambiar(new_password1=debil, new_password2=debil)
                self.assertEqual(respuesta.status_code, 200)
                self.assertContains(respuesta, 'field__error')

    def test_las_dos_nuevas_deben_coincidir(self):
        respuesta = self.cambiar(new_password2='Otra-clave-2026!')
        self.assertContains(respuesta, 'field__error')

    def test_deja_bitacora(self):
        self.cambiar()
        self.assertTrue(bitacora(self.usuario, CHANGE).filter(change_message__contains='propia contraseña').exists())


class ContrasenaTemporalObligatoriaTests(BaseUsuariosTestCase):
    def setUp(self):
        super().setUp()
        self.usuario = crear_usuario('lupita', self.docente, contrasena='Temporal-77')
        perfil = PerfilUsuario.de(self.usuario)
        perfil.debe_cambiar_contrasena = True
        perfil.save()
        self.client.logout()
        self.client.post(reverse('admin:login'), {'username': 'lupita', 'password': 'Temporal-77'})

    def test_hasta_cambiarla_todo_lleva_a_la_pantalla_de_cambio(self):
        for nombre in ('inicio', 'alumnos:lista', 'cuenta:perfil'):
            with self.subTest(pagina=nombre):
                respuesta = self.client.get(reverse(nombre))
                self.assertRedirects(respuesta, reverse('cuenta:contrasena'), fetch_redirect_response=False)

    def test_la_pantalla_de_cambio_y_cerrar_sesion_si_se_permiten(self):
        respuesta = self.client.get(reverse('cuenta:contrasena'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'contraseña temporal')
        self.assertEqual(self.client.post(reverse('logout')).status_code, 200)

    def test_al_cambiarla_ya_usa_el_sistema(self):
        respuesta = self.client.post(reverse('cuenta:contrasena'), {
            'old_password': 'Temporal-77', 'new_password1': 'Mi-clave-propia-5!', 'new_password2': 'Mi-clave-propia-5!',
        })
        self.assertRedirects(respuesta, reverse('inicio'), fetch_redirect_response=False)
        self.assertFalse(PerfilUsuario.objects.get(usuario=self.usuario).debe_cambiar_contrasena)
        self.assertEqual(self.client.get(reverse('alumnos:lista')).status_code, 200)

    def test_la_marca_no_afecta_a_quien_ya_cambio_su_contrasena(self):
        otro = crear_usuario('otra', self.docente, contrasena='Propia-clave-8')
        sesion = Client()
        sesion.post(reverse('admin:login'), {'username': 'otra', 'password': 'Propia-clave-8'})
        self.assertEqual(sesion.get(reverse('alumnos:lista')).status_code, 200)
        self.assertFalse(otro.perfil.debe_cambiar_contrasena)

    def test_los_archivos_estaticos_no_se_redirigen(self):
        self.assertNotEqual(self.client.get('/static/css/app.css').status_code, 302)


# ---------------------------------------------------------------------------
# Los permisos viven en el rol: cambiarlos llega a todos al instante
# ---------------------------------------------------------------------------
class PermisosDinamicosTests(BaseUsuariosTestCase):
    def test_un_rol_sin_permisos_no_deja_pasar_y_al_darselos_si(self):
        rol = crear_rol('Consulta', set())
        persona = crear_usuario('lupita', rol)
        sesion = Client()
        sesion.force_login(persona)
        self.assertEqual(sesion.get(reverse('alumnos:lista')).status_code, 403)

        from Usuarios.seguridad import objetos_de_permisos
        rol.grupo.permissions.set(objetos_de_permisos({'Alumnos.view_alumno'}))
        self.assertEqual(sesion.get(reverse('alumnos:lista')).status_code, 200)   # misma sesión, sin tocar al usuario

    def test_quitar_un_permiso_al_rol_lo_quita_a_todos_sus_usuarios(self):
        rol = crear_rol('Consulta', {'Alumnos.view_alumno', 'Alumnos.view_tutor'})
        sesiones = []
        for nombre in ('ana', 'beto', 'cata'):
            sesion = Client()
            sesion.force_login(crear_usuario(nombre, rol))
            sesiones.append(sesion)
        for sesion in sesiones:
            self.assertEqual(sesion.get(reverse('tutores:lista')).status_code, 200)

        from Usuarios.seguridad import objetos_de_permisos
        rol.grupo.permissions.set(objetos_de_permisos({'Alumnos.view_alumno'}))
        for sesion in sesiones:
            self.assertEqual(sesion.get(reverse('tutores:lista')).status_code, 403)
            self.assertEqual(sesion.get(reverse('alumnos:lista')).status_code, 200)

    def test_cambiar_el_rol_de_una_persona_cambia_su_acceso_sin_tocar_permisos_sueltos(self):
        persona = crear_usuario('lupita', self.docente)
        self.assertEqual(persona.user_permissions.count(), 0)
        asignar_rol(persona, self.direccion)
        self.assertEqual(Usuario.objects.get(pk=persona.pk).user_permissions.count(), 0)
        self.assertTrue(Usuario.objects.get(pk=persona.pk).has_perm('Alumnos.add_alumno'))

    def test_una_cuenta_desactivada_no_tiene_permisos_aunque_su_rol_los_tenga(self):
        persona = crear_usuario('lupita', self.direccion, is_active=False)
        self.assertFalse(persona.has_perm('Alumnos.view_alumno'))


# ---------------------------------------------------------------------------
# Menú, accesos y buscador según el rol
# ---------------------------------------------------------------------------
class MenuSegunElRolTests(BaseUsuariosTestCase):
    def html_de(self, usuario, url='inicio'):
        self.client.force_login(usuario)
        return self.client.get(reverse(url)).content.decode()

    def enlaces_del_menu(self, html):
        import re
        menu = re.search(r'<nav class="nav".*?</nav>', html, re.S).group(0)
        return re.findall(r'<span class="nav__label">([^<]+)</span>', menu)

    def test_el_administrador_ve_todo_el_menu(self):
        etiquetas = self.enlaces_del_menu(self.html_de(self.admin))
        self.assertEqual(etiquetas[0], 'Panel de control')
        for esperado in ('Estudiantes', 'Tutores', 'Profesores', 'Inscripciones', 'Ciclos escolares', 'Grados', 'Materias',
                         'Asignaciones académicas', 'Carga docente', 'Horarios', 'Resumen del día', 'Pase de lista',
                         'Pantalla de entrada', 'Usuarios', 'Roles y permisos', 'Ajustes de asistencia'):
            self.assertIn(esperado, etiquetas)

    def test_cada_rol_ve_solo_sus_modulos(self):
        casos = {
            'Docente': {'Estudiantes', 'Tutores', 'Asignaciones académicas', 'Materias', 'Grados', 'Horarios', 'Pase de lista', 'Justificaciones'},
            'Recepción': {'Estudiantes', 'Resumen del día', 'Justificaciones', 'Reportes', 'Pantalla de entrada'},
        }
        for nombre_rol, esperados in casos.items():
            with self.subTest(rol=nombre_rol):
                usuario = crear_usuario(f'u_{nombre_rol[:3].lower()}', Rol.objects.get(grupo__name=nombre_rol))
                etiquetas = set(self.enlaces_del_menu(self.html_de(usuario))) - {'Panel de control'}
                self.assertEqual(etiquetas, esperados)

    def test_sin_permisos_solo_queda_el_panel_de_control(self):
        etiquetas = self.enlaces_del_menu(self.html_de(self.sin_permisos))
        self.assertEqual(etiquetas, ['Panel de control'])

    def grupos_del_menu(self, html):
        import re
        return [t.strip() for t in re.findall(r'nav__label nav__label--group">([^<]+)<', html)]

    def test_las_secciones_vacias_no_se_dibujan(self):
        html = self.html_de(crear_usuario('lupita', crear_rol('Solo estudiantes', {'Alumnos.view_alumno'})))
        self.assertIn('Estudiantes', self.enlaces_del_menu(html))
        # Un grupo con una sola opción visible se dibuja como enlace directo; los grupos vacíos no aparecen
        self.assertEqual(self.grupos_del_menu(html), [])

    def test_los_grupos_con_varias_opciones_se_despliegan(self):
        html = self.html_de(crear_usuario('lupita', crear_rol('Escolar', {'Alumnos.view_alumno', 'Alumnos.view_tutor'})))
        self.assertEqual(self.grupos_del_menu(html), ['Control escolar'])
        self.assertNotIn('Configuración', self.grupos_del_menu(html))
        self.assertIn('data-nav-toggle', html)

    def test_el_tablero_ofrece_solo_accesos_permitidos(self):
        html = self.html_de(crear_usuario('lupita', crear_rol('Solo estudiantes', {'Alumnos.view_alumno'})))
        self.assertIn('module__label">Estudiantes', html)
        self.assertNotIn('module__label">Tutores', html)
        self.assertNotIn('module__label">Usuarios', html)

    def test_asistencias_lleva_a_la_primera_pantalla_a_la_que_se_tiene_acceso(self):
        casos = [
            ({'Alumnos.view_asistenciageneral'}, reverse('asistencias:inicio')),
            ({'Alumnos.view_asistenciamateria'}, reverse('asistencias:clases')),
            ({'Alumnos.view_justificacion'}, reverse('asistencias:justificaciones')),
            ({'Alumnos.add_asistenciageneral'}, reverse('asistencias:kiosco')),
            ({'Alumnos.view_configuracionasistencia'}, reverse('asistencias:ajustes')),
        ]
        for n, (permisos, destino) in enumerate(casos):
            with self.subTest(destino=destino):
                usuario = crear_usuario(f'asis{n}', crear_rol(f'Asistencia {n}', permisos))
                html = self.html_de(usuario)
                self.assertIn(f'href="{destino}"', html)
                self.client.force_login(usuario)
                self.assertEqual(self.client.get(destino).status_code, 200, 'el enlace del menú debe llevar a una página accesible')

    def test_el_buscador_de_comandos_solo_ofrece_acciones_permitidas(self):
        html = self.html_de(crear_usuario('lupita', crear_rol('Altas', {'Alumnos.add_alumno'})))
        self.assertIn('Nuevo estudiante', html)
        self.assertNotIn('Nuevo tutor', html)
        self.assertNotIn('Nuevo usuario', html)
        completo = self.html_de(self.admin)
        for accion in ('Nuevo estudiante', 'Nuevo usuario', 'Nuevo rol', 'Pantalla de entrada'):
            self.assertIn(accion, completo)

    def test_el_menu_de_usuario_muestra_el_rol_y_mi_cuenta(self):
        html = self.html_de(crear_usuario('lupita', self.docente, first_name='Lupita', last_name='Soto'))
        self.assertIn('Lupita Soto', html)
        self.assertRegex(html, r'menu__subtitle">\s*Docente\s*<')
        self.assertIn(f'href="{reverse("cuenta:perfil")}"', html)

    def test_solo_el_personal_de_django_ve_la_administracion_de_django(self):
        self.assertNotIn('Administración de Django', self.html_de(crear_usuario('lupita', self.docente)))
        self.assertIn('Administración de Django', self.html_de(self.admin))

    def test_el_elemento_activo_sigue_marcandose(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse('usuarios:lista')).content.decode()
        self.assertRegex(html, r'<a class="nav__sublink" href="/usuarios/" aria-current="page"')
        # y su grupo llega abierto
        self.assertRegex(html, r'data-nav-group="configuracion">\s*<details class="nav__details" open>')


# ---------------------------------------------------------------------------
# Reglas de seguridad (unitarias)
# ---------------------------------------------------------------------------
class ReglasDeSeguridadTests(BaseUsuariosTestCase):
    def test_asignar_rol_deja_un_solo_rol_y_conserva_otros_grupos(self):
        from django.contrib.auth.models import Group
        ajeno = Group.objects.create(name='Grupo suelto')
        persona = crear_usuario('lupita', self.docente)
        persona.groups.add(ajeno)
        asignar_rol(persona, self.direccion)
        self.assertEqual({g.name for g in persona.groups.all()}, {'Dirección', 'Grupo suelto'})

    def test_asignar_el_rol_de_acceso_total_activa_superusuario_y_staff(self):
        persona = crear_usuario('lupita', self.docente)
        asignar_rol(persona, self.administrador)
        persona.refresh_from_db()
        self.assertTrue(persona.is_superuser and persona.is_staff)
        asignar_rol(persona, self.docente)
        persona.refresh_from_db()
        self.assertFalse(persona.is_superuser or persona.is_staff)

    def test_un_superusuario_gestiona_a_todos_y_asigna_cualquier_rol_activo(self):
        persona = crear_usuario('lupita', self.direccion)
        self.assertTrue(puede_gestionar(self.admin, persona))
        self.assertTrue(puede_asignar(self.admin, self.administrador))
        inactivo = crear_rol('Apagado', {'Alumnos.view_alumno'}, activo=False)
        self.assertFalse(puede_asignar(self.admin, inactivo))

    def test_alguien_con_los_mismos_permisos_si_gestiona_a_su_igual(self):
        a = crear_usuario('a', self.docente)
        b = crear_usuario('b', self.docente)
        self.assertTrue(puede_gestionar(a, b))

    def test_nunca_se_gestiona_a_un_superusuario_sin_serlo(self):
        poderoso = crear_usuario('poderoso', self.direccion)
        self.assertFalse(puede_gestionar(poderoso, self.admin))

    def test_el_ultimo_administrador_se_detecta_solo_si_esta_activo_y_es_unico(self):
        self.assertTrue(es_ultimo_administrador(self.admin))
        otro = crear_usuario('otro_admin', self.administrador)
        self.assertFalse(es_ultimo_administrador(self.admin))
        Usuario.objects.filter(pk=otro.pk).update(is_active=False)
        self.assertTrue(es_ultimo_administrador(self.admin))
        self.assertFalse(es_ultimo_administrador(self.sin_permisos))

    def test_la_bitacora_guarda_quien_hizo_el_cambio(self):
        persona = crear_usuario('lupita', self.docente)
        self.client.post(reverse('usuarios:baja', args=[persona.pk]))
        entrada = bitacora(persona, DELETION).get()
        self.assertEqual(entrada.user, self.admin)
        self.assertEqual(entrada.object_repr, str(persona))


class SistemaSinMigrarTests(BaseUsuariosTestCase):
    def test_las_paginas_existentes_siguen_funcionando_si_aun_no_existe_la_tabla_de_roles(self):
        """Antes de correr `migrate`, el menú no debe tumbar el sistema por no poder leer el rol."""
        from unittest.mock import patch

        from django.db import OperationalError
        with patch('Usuarios.seguridad.rol_de', side_effect=OperationalError('no such table: Usuarios_rol')):
            for nombre in ('inicio', 'alumnos:lista', 'tutores:lista'):
                with self.subTest(pagina=nombre):
                    respuesta = self.client.get(reverse(nombre))
                    self.assertEqual(respuesta.status_code, 200)
                    self.assertContains(respuesta, 'menu__subtitle')
