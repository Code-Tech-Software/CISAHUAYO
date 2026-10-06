"""Una sola cuenta por profesor: se crea o se vincula desde Profesores («Dar acceso al sistema») o desde Usuarios
(«Es docente» o un rol para docentes), y el resultado es el mismo."""
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from Alumnos.models import Profesor, ProfesorMateria
from CISAHUAYO.pruebas import PRUEBAS, BaseAsistenciaTestCase, BaseTestCase, crear_profesor, crear_rol, crear_usuario
from Profesores.tests import crear_materia, datos_profesor
from Usuarios.docentes import crear_cuenta, desvincular, profesor_de, vincular
from Usuarios.models import Rol
from Usuarios.seguridad import rol_de

Usuario = get_user_model()


def bitacora(objeto):
    return LogEntry.objects.filter(content_type=ContentType.objects.get_for_model(objeto), object_id=str(objeto.pk))


class CuentasTestCase(BaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.docente = Rol.objects.get(grupo__name='Docente')
        cls.recepcion = Rol.objects.get(grupo__name='Recepción')
        cls.direccion = Rol.objects.get(grupo__name='Dirección')


# ---------------------------------------------------------------------------
# Reglas de la relación
# ---------------------------------------------------------------------------
@PRUEBAS
class RelacionTests(CuentasTestCase):
    def test_el_rol_docente_de_arranque_es_para_docentes(self):
        self.assertTrue(self.docente.es_docente)
        self.assertFalse(self.direccion.es_docente)

    def test_crear_cuenta_la_vincula_con_el_nombre_de_la_ficha(self):
        profesor = crear_profesor(nombre='Marta', apellido_paterno='Rangel', apellido_materno='Soto')
        cuenta, contrasena = crear_cuenta(profesor, username='marta.rangel', email='marta@escuela.mx', rol=self.docente)
        profesor.refresh_from_db()
        self.assertEqual(profesor.usuario, cuenta)
        self.assertEqual((cuenta.first_name, cuenta.last_name), ('Marta', 'Rangel Soto'))
        self.assertTrue(cuenta.check_password(contrasena))
        self.assertTrue(cuenta.perfil.debe_cambiar_contrasena)
        self.assertEqual(rol_de(cuenta), self.docente)
        self.assertEqual(profesor_de(cuenta), profesor)

    def test_una_cuenta_no_puede_ser_de_dos_profesores_ni_al_reves(self):
        marta, beto = crear_profesor(nombre='Marta'), crear_profesor(nombre='Beto', telefono='3530000002')
        cuenta = crear_usuario('marta')
        vincular(marta, cuenta)
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            vincular(beto, cuenta)
        with self.assertRaises(ValidationError):
            vincular(marta, crear_usuario('otra'))

    def test_desvincular_no_borra_ni_desactiva(self):
        profesor = crear_profesor()
        cuenta = crear_usuario('marta')
        vincular(profesor, cuenta)
        self.assertEqual(desvincular(profesor), cuenta)
        profesor.refresh_from_db()
        cuenta.refresh_from_db()
        self.assertIsNone(profesor.usuario)
        self.assertTrue(cuenta.is_active)

    def test_editar_la_ficha_actualiza_el_nombre_de_la_cuenta(self):
        profesor = crear_profesor(nombre='Marta', apellido_paterno='Rangel')
        cuenta = crear_usuario('marta')
        vincular(profesor, cuenta)
        self.client.post(reverse('profesores:editar', args=[profesor.pk]),
                         datos_profesor(nombre='Martha', apellido_paterno='Rangel', apellido_materno='Díaz', telefono='3534445566'))
        cuenta.refresh_from_db()
        self.assertEqual((cuenta.first_name, cuenta.last_name), ('Martha', 'Rangel Díaz'))

    def test_borrar_la_cuenta_no_borra_al_profesor(self):
        profesor = crear_profesor()
        cuenta = crear_usuario('marta')
        vincular(profesor, cuenta)
        cuenta.delete()
        profesor.refresh_from_db()
        self.assertIsNone(profesor.usuario)


# ---------------------------------------------------------------------------
# Desde Profesores: «Dar acceso al sistema»
# ---------------------------------------------------------------------------
@PRUEBAS
class DarAccesoDesdeProfesoresTests(CuentasTestCase):
    def acceso(self, **cambios):
        datos = datos_profesor(correo_electronico='ana@escuela.mx')
        datos.update({'acceso-dar_acceso': 'on', 'acceso-modo': 'nueva', 'acceso-username': 'ana.lara',
                      'acceso-email': '', 'acceso-rol': self.docente.pk, 'acceso-contrasena': ''})
        datos.update(cambios)
        return datos

    def test_registrar_un_profesor_con_su_cuenta(self):
        respuesta = self.client.post(reverse('profesores:crear'), self.acceso(), follow=True)
        profesor = Profesor.objects.get()
        cuenta = profesor.usuario
        self.assertEqual(cuenta.username, 'ana.lara')
        self.assertEqual(cuenta.email, 'ana@escuela.mx')               # sin correo de cuenta se usa el de la ficha
        self.assertEqual((cuenta.first_name, cuenta.last_name), ('Ana', 'Lara Ruiz'))
        self.assertEqual(rol_de(cuenta), self.docente)
        self.assertTrue(cuenta.perfil.debe_cambiar_contrasena)
        self.assertContains(respuesta, 'Se creó su cuenta «ana.lara»')
        self.assertContains(respuesta, 'Contraseña temporal')            # las credenciales se muestran una vez
        self.assertTrue(bitacora(cuenta).filter(change_message__contains='para el profesor').exists())
        self.assertTrue(bitacora(profesor).filter(change_message__contains='acceso al sistema').exists())

    def test_la_contrasena_escrita_se_usa_y_se_muestra_como_inicial(self):
        respuesta = self.client.post(reverse('profesores:crear'), self.acceso(**{'acceso-contrasena': 'Colegio-2026!'}), follow=True)
        cuenta = Profesor.objects.get().usuario
        self.assertTrue(cuenta.check_password('Colegio-2026!'))
        self.assertContains(respuesta, 'Contraseña inicial')

    def test_una_contrasena_debil_se_rechaza_y_no_se_registra_nada(self):
        respuesta = self.client.post(reverse('profesores:crear'), self.acceso(**{'acceso-contrasena': '123'}))
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Profesor.objects.exists())
        self.assertFalse(Usuario.objects.filter(username='ana.lara').exists())

    def test_sin_marcar_dar_acceso_no_se_crea_cuenta(self):
        datos = self.acceso()
        del datos['acceso-dar_acceso']
        self.client.post(reverse('profesores:crear'), datos)
        self.assertIsNone(Profesor.objects.get().usuario)
        self.assertFalse(Usuario.objects.filter(username='ana.lara').exists())

    def test_usuario_repetido_detiene_todo(self):
        crear_usuario('ana.lara')
        respuesta = self.client.post(reverse('profesores:crear'), self.acceso())
        self.assertContains(respuesta, 'Ya existe una cuenta con ese usuario.')
        self.assertFalse(Profesor.objects.exists())

    def test_pide_usuario_y_rol(self):
        respuesta = self.client.post(reverse('profesores:crear'), self.acceso(**{'acceso-username': '', 'acceso-rol': ''}))
        self.assertContains(respuesta, 'minúsculas, números')
        self.assertContains(respuesta, 'Elige el rol de la cuenta.')
        self.assertFalse(Profesor.objects.exists())

    def test_si_el_correo_de_la_ficha_ya_es_de_otra_cuenta_la_cuenta_queda_sin_correo(self):
        crear_usuario('otra', email='ana@escuela.mx')
        self.client.post(reverse('profesores:crear'), self.acceso())
        self.assertEqual(Profesor.objects.get().usuario.email, '')

    def test_vincular_una_cuenta_que_ya_existe(self):
        cuenta = crear_usuario('laura', self.docente, first_name='Laura', last_name='X')
        self.client.post(reverse('profesores:crear'), self.acceso(**{'acceso-modo': 'existente', 'acceso-cuenta': cuenta.pk}))
        profesor = Profesor.objects.get()
        self.assertEqual(profesor.usuario, cuenta)
        cuenta.refresh_from_db()
        self.assertEqual((cuenta.first_name, cuenta.last_name), ('Ana', 'Lara Ruiz'))   # el nombre sale de la ficha

    def test_no_se_ofrece_una_cuenta_que_ya_es_de_otro_profesor(self):
        cuenta = crear_usuario('laura')
        vincular(crear_profesor(), cuenta)
        respuesta = self.client.post(reverse('profesores:crear'), self.acceso(**{'acceso-modo': 'existente', 'acceso-cuenta': cuenta.pk}))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(Profesor.objects.count(), 1)

    def test_dar_acceso_a_un_profesor_ya_registrado(self):
        profesor = crear_profesor(nombre='Ana', apellido_paterno='Lara', apellido_materno='Ruiz', telefono='3531112233')
        datos = self.acceso()
        self.client.post(reverse('profesores:editar', args=[profesor.pk]), datos)
        profesor.refresh_from_db()
        self.assertEqual(profesor.usuario.username, 'ana.lara')

    def test_el_enlace_dar_acceso_abre_la_seccion(self):
        profesor = crear_profesor()
        html = self.client.get(reverse('profesores:editar', args=[profesor.pk]), {'acceso': '1'}).content.decode()
        self.assertRegex(html, r'name="acceso-dar_acceso"[^>]*\n?\s*checked')

    def test_un_profesor_con_cuenta_no_vuelve_a_ofrecerla(self):
        profesor = crear_profesor()
        vincular(profesor, crear_usuario('marta'))
        html = self.client.get(reverse('profesores:editar', args=[profesor.pk])).content.decode()
        self.assertNotIn('acceso-dar_acceso', html)
        self.assertIn('Entra con la cuenta', html)

    def test_sin_permiso_de_cuentas_no_hay_seccion_y_no_se_puede_forzar(self):
        self.con_permisos('view_profesor', 'add_profesor')
        html = self.client.get(reverse('profesores:crear')).content.decode()
        self.assertNotIn('acceso-dar_acceso', html)
        respuesta = self.client.post(reverse('profesores:crear'), self.acceso())
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Usuario.objects.filter(username='ana.lara').exists())

    def test_solo_se_ofrecen_roles_que_quien_captura_podria_dar(self):
        rol = crear_rol('Captura de profesores', {'Alumnos.view_profesor', 'Alumnos.add_profesor', 'auth.view_user', 'auth.add_user'})
        self.client.force_login(crear_usuario('captura', rol))
        respuesta = self.client.post(reverse('profesores:crear'), self.acceso())   # el rol Docente tiene permisos que no tiene
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Usuario.objects.filter(username='ana.lara').exists())


# ---------------------------------------------------------------------------
# Perfil del profesor: su cuenta, la baja y desvincular
# ---------------------------------------------------------------------------
@PRUEBAS
class PerfilYBajaTests(CuentasTestCase):
    def setUp(self):
        super().setUp()
        self.profesor = crear_profesor()
        self.cuenta = crear_usuario('marta', self.docente)

    def test_sin_cuenta_ofrece_dar_acceso(self):
        html = self.client.get(self.profesor.get_absolute_url()).content.decode()
        self.assertIn('No tiene cuenta', html)
        self.assertIn(f'{reverse("profesores:editar", args=[self.profesor.pk])}?acceso=1', html)

    def test_con_cuenta_muestra_sus_datos(self):
        vincular(self.profesor, self.cuenta)
        html = self.client.get(self.profesor.get_absolute_url()).content.decode()
        self.assertIn('marta', html)
        self.assertIn(reverse('usuarios:detalle', args=[self.cuenta.pk]), html)
        self.assertIn('modal-desvincular', html)

    def test_la_baja_puede_desactivar_su_cuenta(self):
        vincular(self.profesor, self.cuenta)
        self.client.post(reverse('profesores:baja', args=[self.profesor.pk]), {'desactivar_cuenta': 'on'})
        self.cuenta.refresh_from_db()
        self.assertFalse(self.cuenta.is_active)

    def test_la_baja_sin_marcar_deja_la_cuenta_activa(self):
        vincular(self.profesor, self.cuenta)
        self.client.post(reverse('profesores:baja', args=[self.profesor.pk]), {})
        self.cuenta.refresh_from_db()
        self.assertTrue(self.cuenta.is_active)

    def test_la_baja_no_desactiva_sin_permiso_de_cuentas(self):
        vincular(self.profesor, self.cuenta)
        self.con_permisos('view_profesor', 'delete_profesor')
        self.client.post(reverse('profesores:baja', args=[self.profesor.pk]), {'desactivar_cuenta': 'on'})
        self.cuenta.refresh_from_db()
        self.assertTrue(self.cuenta.is_active)

    def test_reactivar_avisa_que_la_cuenta_sigue_desactivada(self):
        vincular(self.profesor, self.cuenta)
        self.client.post(reverse('profesores:baja', args=[self.profesor.pk]), {'desactivar_cuenta': 'on'})
        respuesta = self.client.post(reverse('profesores:reactivar', args=[self.profesor.pk]), follow=True)
        self.assertContains(respuesta, 'sigue desactivada')

    def test_desvincular(self):
        vincular(self.profesor, self.cuenta)
        self.client.post(reverse('profesores:desvincular_cuenta', args=[self.profesor.pk]))
        self.profesor.refresh_from_db()
        self.assertIsNone(self.profesor.usuario)
        self.assertTrue(Usuario.objects.filter(pk=self.cuenta.pk, is_active=True).exists())

    def test_desvincular_pide_permisos_de_profesores_y_de_cuentas(self):
        vincular(self.profesor, self.cuenta)
        self.con_permisos('view_profesor', 'change_profesor')
        self.assertEqual(self.client.post(reverse('profesores:desvincular_cuenta', args=[self.profesor.pk])).status_code, 403)
        self.profesor.refresh_from_db()
        self.assertEqual(self.profesor.usuario, self.cuenta)


# ---------------------------------------------------------------------------
# Desde Usuarios: «Es docente» o un rol para docentes
# ---------------------------------------------------------------------------
@PRUEBAS
class DocenteDesdeUsuariosTests(CuentasTestCase):
    def alta(self, **cambios):
        datos = {
            'first_name': 'Marta', 'last_name': '', 'username': 'marta.rangel', 'email': 'marta@escuela.mx',
            'telefono': '353 444 5566', 'cargo': '', 'rol': self.docente.pk, 'contrasena': '',
            'docente-es_docente': 'on', 'docente-modo': 'nuevo', 'docente-apellido_paterno': 'Rangel',
            'docente-apellido_materno': 'Soto', 'docente-especialidad': 'Matemáticas', 'docente-horas_maximas': '25',
        }
        datos.update(cambios)
        return {k: v for k, v in datos.items() if v is not None}

    def test_crear_la_cuenta_registra_su_ficha_de_profesor(self):
        mat = crear_materia('MAT', 'Matemáticas')
        respuesta = self.client.post(reverse('usuarios:crear'), {**self.alta(), 'docente-materias': [mat.pk]}, follow=True)
        cuenta = Usuario.objects.get(username='marta.rangel')
        profesor = cuenta.profesor
        self.assertEqual((profesor.nombre, profesor.apellido_paterno, profesor.apellido_materno), ('Marta', 'Rangel', 'Soto'))
        self.assertEqual((profesor.telefono, profesor.correo_electronico), ('3534445566', 'marta@escuela.mx'))
        self.assertEqual((profesor.especialidad, profesor.horas_maximas), ('Matemáticas', 25))
        self.assertEqual(cuenta.last_name, 'Rangel Soto')
        self.assertTrue(ProfesorMateria.objects.filter(profesor=profesor, materia=mat).exists())
        self.assertContains(respuesta, 'Se registró su ficha de profesor')
        self.assertTrue(bitacora(profesor).filter(change_message__contains='Ficha registrada junto con').exists())

    def test_un_rol_para_docentes_exige_la_ficha_aunque_no_marquen_la_casilla(self):
        datos = self.alta(**{'docente-es_docente': None, 'docente-apellido_paterno': ''})
        respuesta = self.client.post(reverse('usuarios:crear'), datos)
        self.assertContains(respuesta, 'Escribe el apellido paterno.')
        self.assertFalse(Usuario.objects.filter(username='marta.rangel').exists())
        self.client.post(reverse('usuarios:crear'), self.alta(**{'docente-es_docente': None}))
        self.assertTrue(Profesor.objects.filter(usuario__username='marta.rangel').exists())

    def test_es_docente_con_otro_rol(self):
        self.client.post(reverse('usuarios:crear'), self.alta(rol=self.direccion.pk))
        cuenta = Usuario.objects.get(username='marta.rangel')
        self.assertEqual(rol_de(cuenta), self.direccion)
        self.assertEqual(cuenta.profesor.apellido_paterno, 'Rangel')

    def test_sin_es_docente_ni_rol_docente_no_hay_ficha(self):
        self.client.post(reverse('usuarios:crear'), self.alta(rol=self.recepcion.pk, last_name='Rangel', **{'docente-es_docente': None}))
        self.assertFalse(Profesor.objects.exists())
        self.assertEqual(Usuario.objects.get(username='marta.rangel').last_name, 'Rangel')

    def test_la_ficha_nueva_pide_telefono(self):
        respuesta = self.client.post(reverse('usuarios:crear'), self.alta(telefono=''))
        self.assertContains(respuesta, 'es obligatorio en la ficha del profesor')
        self.assertFalse(Profesor.objects.exists())

    def test_si_el_correo_es_de_un_profesor_registrado_sugiere_vincularlo(self):
        crear_profesor(correo_electronico='marta@escuela.mx')
        respuesta = self.client.post(reverse('usuarios:crear'), self.alta())
        self.assertContains(respuesta, 'vincúlalo en lugar de registrar uno nuevo')

    def test_vincular_con_un_profesor_ya_registrado(self):
        profesor = crear_profesor(nombre='Marta', apellido_paterno='Rangel', apellido_materno='Soto')
        self.client.post(reverse('usuarios:crear'), self.alta(first_name='', **{'docente-modo': 'existente', 'docente-profesor': profesor.pk}))
        profesor.refresh_from_db()
        self.assertEqual(profesor.usuario.username, 'marta.rangel')
        self.assertEqual((profesor.usuario.first_name, profesor.usuario.last_name), ('Marta', 'Rangel Soto'))
        self.assertEqual(Profesor.objects.count(), 1)   # no se duplicó el profesor

    def test_no_se_ofrece_un_profesor_que_ya_tiene_cuenta(self):
        profesor = crear_profesor()
        vincular(profesor, crear_usuario('otra'))
        respuesta = self.client.post(reverse('usuarios:crear'), self.alta(**{'docente-modo': 'existente', 'docente-profesor': profesor.pk}))
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Usuario.objects.filter(username='marta.rangel').exists())

    def test_sin_permiso_de_profesores_no_puede_crear_cuentas_de_docente(self):
        rol = crear_rol('Solo cuentas', {'auth.view_user', 'auth.add_user', 'auth.change_user', 'Alumnos.view_alumno'})
        self.client.force_login(crear_usuario('gestor', rol))
        respuesta = self.client.post(reverse('usuarios:crear'), self.alta(rol=''))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'no tienes permiso para hacerlo')
        self.assertFalse(Usuario.objects.filter(username='marta.rangel').exists())

    def test_la_contrasena_inicial_escrita_se_respeta(self):
        self.client.post(reverse('usuarios:crear'), self.alta(contrasena='Colegio-2026!'))
        self.assertTrue(Usuario.objects.get(username='marta.rangel').check_password('Colegio-2026!'))

    def test_la_cuenta_de_un_profesor_no_cambia_su_nombre_desde_usuarios(self):
        profesor = crear_profesor(nombre='Marta', apellido_paterno='Rangel', apellido_materno='Soto')
        cuenta = crear_usuario('marta', self.docente)
        vincular(profesor, cuenta)
        self.client.post(reverse('usuarios:editar', args=[cuenta.pk]), {
            'first_name': 'Otra', 'last_name': 'Persona', 'username': 'marta', 'email': '', 'telefono': '', 'cargo': '',
            'rol': self.docente.pk,
        })
        cuenta.refresh_from_db()
        self.assertEqual((cuenta.first_name, cuenta.last_name), ('Marta', 'Rangel Soto'))
        html = self.client.get(reverse('usuarios:editar', args=[cuenta.pk])).content.decode()
        self.assertIn('Esta cuenta es de', html)

    def test_una_cuenta_docente_antigua_sin_ficha_se_puede_editar_y_vincular(self):
        cuenta = crear_usuario('laura', self.docente, first_name='Laura', last_name='Méndez')
        datos = {'first_name': 'Laura', 'last_name': 'Méndez', 'username': 'laura', 'email': '', 'telefono': '', 'cargo': '',
                 'rol': self.docente.pk}
        respuesta = self.client.post(reverse('usuarios:editar', args=[cuenta.pk]), datos)
        self.assertEqual(respuesta.status_code, 302)   # no se bloquea por no tener ficha
        profesor = crear_profesor(nombre='Laura', apellido_paterno='Méndez')
        self.client.post(reverse('usuarios:editar', args=[cuenta.pk]),
                         {**datos, 'docente-es_docente': 'on', 'docente-modo': 'existente', 'docente-profesor': profesor.pk})
        profesor.refresh_from_db()
        self.assertEqual(profesor.usuario, cuenta)

    def test_el_perfil_avisa_de_una_cuenta_docente_sin_ficha(self):
        cuenta = crear_usuario('laura', self.docente)
        self.assertContains(self.client.get(reverse('usuarios:detalle', args=[cuenta.pk])), 'Cuenta de docente sin ficha de profesor')

    def test_el_listado_y_el_perfil_muestran_la_ficha(self):
        profesor = crear_profesor(nombre='Marta', apellido_paterno='Rangel')
        cuenta = crear_usuario('marta', self.docente)
        vincular(profesor, cuenta)
        self.assertContains(self.client.get(reverse('usuarios:lista')), 'Ficha de profesor vinculada')
        self.assertContains(self.client.get(reverse('usuarios:detalle', args=[cuenta.pk])), profesor.get_absolute_url())

    def test_mi_cuenta_no_deja_cambiar_el_nombre_de_un_docente(self):
        profesor = crear_profesor(nombre='Marta', apellido_paterno='Rangel', apellido_materno='Soto')
        cuenta = crear_usuario('marta', self.docente)
        vincular(profesor, cuenta)
        self.client.force_login(cuenta)
        self.client.post(reverse('cuenta:perfil'), {'first_name': 'X', 'last_name': 'Y', 'email': '', 'telefono': ''})
        cuenta.refresh_from_db()
        self.assertEqual(cuenta.first_name, 'Marta')


# ---------------------------------------------------------------------------
# Roles: «Rol para docentes»
# ---------------------------------------------------------------------------
@PRUEBAS
class RolParaDocentesTests(CuentasTestCase):
    def test_se_marca_al_crear_y_al_editar_y_se_copia(self):
        self.client.post(reverse('roles:crear'), {'nombre': 'Maestros de taller', 'descripcion': '', 'tono': 2, 'es_docente': 'on',
                                                  'permisos': ['Alumnos.view_alumno']})
        rol = Rol.objects.get(grupo__name='Maestros de taller')
        self.assertTrue(rol.es_docente)
        self.client.post(reverse('roles:editar', args=[rol.pk]), {'nombre': 'Maestros de taller', 'descripcion': '', 'tono': 2,
                                                                 'permisos': ['Alumnos.view_alumno']})
        rol.refresh_from_db()
        self.assertFalse(rol.es_docente)
        self.client.post(reverse('roles:copiar', args=[self.docente.pk]))
        self.assertTrue(Rol.objects.exclude(pk=self.docente.pk).filter(es_docente=True).exists())

    def test_el_perfil_del_rol_lo_indica(self):
        self.assertContains(self.client.get(self.docente.get_absolute_url()), 'Rol para docentes')


# ---------------------------------------------------------------------------
# Panel de control: las clases de hoy del docente
# ---------------------------------------------------------------------------
@PRUEBAS
class MisClasesDeHoyTests(BaseAsistenciaTestCase):
    hora = (8, 30)

    def setUp(self):
        super().setUp()
        self.profesor = crear_profesor(nombre='Marta', apellido_paterno='Rangel')
        for asignacion in (self.mat, self.cie):
            asignacion.profesor = self.profesor
            asignacion.save()
        self.cuenta = crear_usuario('marta', Rol.objects.get(grupo__name='Docente'))
        vincular(self.profesor, self.cuenta)

    def test_el_docente_ve_sus_clases_de_hoy_con_acceso_al_pase_de_lista(self):
        self.client.force_login(self.cuenta)
        respuesta = self.client.get(reverse('inicio'))
        filas = respuesta.context['mis_clases']['clases']
        self.assertEqual([f['clase'].asignacion.materia.clave for f in filas], ['MAT', 'CIE'])
        self.assertTrue(filas[0]['en_curso'])
        self.assertFalse(filas[1]['en_curso'])
        self.assertContains(respuesta, 'Mis clases de hoy')
        self.assertContains(respuesta, reverse('asistencias:clase', args=[self.mat.pk]))
        self.assertContains(respuesta, 'En curso')

    def test_quien_no_es_profesor_no_ve_la_seccion(self):
        respuesta = self.client.get(reverse('inicio'))
        self.assertIsNone(respuesta.context['mis_clases'])
        self.assertNotContains(respuesta, 'Mis clases de hoy')

    def test_sin_clases_hoy_lo_dice(self):
        self.mat.profesor = self.cie.profesor = None
        self.mat.save()
        self.cie.save()
        self.client.force_login(self.cuenta)
        self.assertContains(self.client.get(reverse('inicio')), 'Hoy no tienes clases asignadas.')
