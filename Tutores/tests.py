import csv
import io
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from Alumnos.models import Alumno, CicloEscolar, Grado, Inscripcion, Tutor, TutorAlumno

# Los tests corren con DEBUG=False: se usa almacenamiento simple (sin manifiesto ni Cloudinary).
PRUEBAS = override_settings(
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
)

CURP_ANA = 'GALA150315MMNRPNA1'
CURP_LUIS = 'PEMJ100720HMNRRNA5'
CURP_TUTOR = 'LOPM850101MMNPRR03'


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------
def crear_alumno(**cambios):
    datos = {
        'referencia': '2001', 'nombre': 'Luis', 'apellido_paterno': 'Pérez', 'apellido_materno': 'Mora',
        'curp': CURP_LUIS, 'sexo': 'M', 'fecha_nacimiento': '2010-07-20', 'grupo_sanguineo': 'A+',
        'domicilio': 'Av. Juárez 45', 'colonia': 'Centro', 'ciudad': 'Sahuayo', 'estado': 'Michoacán',
        'cp': '59000', 'contrasena': 'hash',
    }
    datos.update(cambios)
    return Alumno.objects.create(**datos)


def crear_tutor(**cambios):
    datos = {'nombre': 'Rosa', 'apellido_paterno': 'Mora', 'telefono': '3531112233'}
    datos.update(cambios)
    return Tutor.objects.create(**datos)


def vincular(tutor, alumno, **cambios):
    datos = {'parentesco': 'MADRE', 'activo': True}
    datos.update(cambios)
    return TutorAlumno.objects.create(tutor=tutor, alumno=alumno, **datos)


def datos_tutor(**cambios):
    datos = {
        'nombre': 'María', 'apellido_paterno': 'López', 'apellido_materno': 'Ruiz', 'curp': '',
        'estado_civil': '', 'religion': '', 'telefono': '353 123 4567', 'telefono_alternativo': '',
        'correo_electronico': '', 'domicilio': 'Calle Hidalgo 123', 'colonia': 'Centro', 'ciudad': 'Sahuayo',
        'estado': 'Michoacán', 'cp': '59000', 'ocupacion': '', 'lugar_trabajo': '', 'telefono_trabajo': '',
        'observaciones': '',
    }
    datos.update(cambios)
    return datos


class BaseTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser('admin', 'admin@example.com', 'x')
        cls.sin_permisos = User.objects.create_user('visitante', password='x')

    def setUp(self):
        self.client.force_login(self.admin)

    def con_permisos(self, *codigos):
        self.usuarios = getattr(self, 'usuarios', 0) + 1
        usuario = get_user_model().objects.create_user(f'usuario{self.usuarios}', password='x')
        usuario.user_permissions.add(*Permission.objects.filter(codename__in=codigos))
        self.client.force_login(usuario)


# ---------------------------------------------------------------------------
# Permisos
# ---------------------------------------------------------------------------
@PRUEBAS
class PermisosTests(BaseTestCase):
    def test_anonimo_es_enviado_al_login(self):
        self.client.logout()
        tutor = crear_tutor()
        for nombre, args in (('lista', []), ('crear', []), ('detalle', [tutor.pk]), ('editar', [tutor.pk]), ('exportar', [])):
            respuesta = self.client.get(reverse(f'tutores:{nombre}', args=args))
            self.assertEqual(respuesta.status_code, 302, nombre)
            self.assertIn('/admin/login/', respuesta['Location'])
            self.assertIn('next=', respuesta['Location'])

    def test_sin_permisos_recibe_403(self):
        self.client.force_login(self.sin_permisos)
        tutor = crear_tutor()
        for nombre, args in (('lista', []), ('crear', []), ('detalle', [tutor.pk]), ('editar', [tutor.pk]), ('exportar', [])):
            self.assertEqual(self.client.get(reverse(f'tutores:{nombre}', args=args)).status_code, 403, nombre)
        for nombre in ('baja', 'reactivar', 'vincular', 'desvincular'):
            self.assertEqual(self.client.post(reverse(f'tutores:{nombre}', args=[tutor.pk])).status_code, 403, nombre)
        tutor.refresh_from_db()
        self.assertEqual(tutor.estatus, 'ACTIVO')

    def test_las_acciones_solo_aceptan_post(self):
        tutor = crear_tutor()
        for nombre in ('baja', 'reactivar', 'vincular', 'desvincular'):
            self.assertEqual(self.client.get(reverse(f'tutores:{nombre}', args=[tutor.pk])).status_code, 405, nombre)

    def test_cada_accion_pide_su_permiso(self):
        tutor = crear_tutor()
        self.con_permisos('view_tutor')
        self.assertEqual(self.client.get(reverse('tutores:lista')).status_code, 200)
        self.assertEqual(self.client.get(reverse('tutores:detalle', args=[tutor.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('tutores:crear')).status_code, 403)
        self.assertEqual(self.client.get(reverse('tutores:editar', args=[tutor.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse('tutores:baja', args=[tutor.pk])).status_code, 403)

        self.con_permisos('view_tutor', 'change_tutor')
        self.assertEqual(self.client.get(reverse('tutores:editar', args=[tutor.pk])).status_code, 200)
        self.assertEqual(self.client.post(reverse('tutores:baja', args=[tutor.pk])).status_code, 403)  # pide delete_tutor

        self.con_permisos('view_tutor', 'delete_tutor')
        self.assertEqual(self.client.post(reverse('tutores:baja', args=[tutor.pk])).status_code, 302)


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------
@PRUEBAS
class ListaTests(BaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.ana = crear_alumno(referencia='A100', nombre='Ana', apellido_paterno='Zamora', curp=CURP_ANA)
        cls.luis = crear_alumno(referencia='B200', nombre='Luis', apellido_paterno='Aranda', curp=CURP_LUIS, estatus='BAJA')

        cls.rosa = crear_tutor(nombre='Rosa', apellido_paterno='Quintero', telefono='3531112233', curp=CURP_TUTOR)
        cls.pedro = crear_tutor(nombre='Pedro', apellido_paterno='Bravo', telefono='3534445566', ocupacion='Contador')
        cls.mario = crear_tutor(nombre='Mario', apellido_paterno='Castro', telefono='3537778899')   # solo con un alumno de baja
        cls.elena = crear_tutor(nombre='Elena', apellido_paterno='Duarte', telefono='3530001122', estatus='INACTIVO')

        vincular(cls.rosa, cls.ana, tutor_principal=True)
        vincular(cls.mario, cls.luis, tutor_principal=True)
        vincular(cls.elena, cls.ana, tutor_principal=False)

    def nombres(self, **filtros):
        respuesta = self.client.get(reverse('tutores:lista'), filtros)
        self.assertEqual(respuesta.status_code, 200)
        return [t.apellido_paterno for t in respuesta.context['pagina']]

    def test_por_defecto_solo_muestra_tutores_activos_en_orden_alfabetico(self):
        self.assertEqual(self.nombres(), ['Bravo', 'Castro', 'Quintero'])

    def test_las_bajas_se_consultan_en_su_propio_filtro(self):
        self.assertEqual(self.nombres(estatus='INACTIVO'), ['Duarte'])
        respuesta = self.client.get(reverse('tutores:lista'), {'estatus': 'INACTIVO'})
        self.assertTrue(respuesta.context['viendo_bajas'])
        self.assertContains(respuesta, 'Reactivar')

    def test_conteos(self):
        respuesta = self.client.get(reverse('tutores:lista'))
        self.assertEqual((respuesta.context['total_activos'], respuesta.context['total_bajas']), (3, 1))
        self.assertFalse(respuesta.context['viendo_bajas'])

    def test_busca_por_nombre_telefono_curp_y_ocupacion(self):
        self.assertEqual(self.nombres(q='rosa quintero'), ['Quintero'])
        self.assertEqual(self.nombres(q='3534445566'), ['Bravo'])
        self.assertEqual(self.nombres(q='LOPM8501'), ['Quintero'])
        self.assertEqual(self.nombres(q='contador'), ['Bravo'])

    def test_busca_por_el_alumno_sin_duplicar(self):
        self.assertEqual(self.nombres(q='zamora'), ['Quintero'])      # Elena también lo es, pero está de baja
        self.assertEqual(self.nombres(q='ana'), ['Quintero'])
        self.assertEqual(self.nombres(q='A100'), ['Quintero'])
        vincular(self.rosa, crear_alumno(referencia='A101', nombre='Ana', apellido_paterno='Zamora', curp=CURP_TUTOR[:-1] + '9'), parentesco='MADRE')
        self.assertEqual(self.nombres(q='ana zamora'), ['Quintero'])  # dos coincidencias, una sola fila

    def test_filtra_por_situacion(self):
        self.assertEqual(self.nombres(situacion='con_alumnos'), ['Quintero'])
        # Mario solo tiene un alumno dado de baja: no cuenta como alumno vigente.
        self.assertEqual(self.nombres(situacion='sin_alumnos'), ['Bravo', 'Castro'])

    def test_un_vinculo_inactivo_no_cuenta_como_vigente(self):
        TutorAlumno.objects.filter(tutor=self.rosa).update(activo=False)
        self.assertEqual(self.nombres(situacion='con_alumnos'), [])

    def test_ordena(self):
        self.assertEqual(self.nombres(orden='-nombre'), ['Quintero', 'Castro', 'Bravo'])
        for dias, tutor in enumerate((self.rosa, self.pedro, self.mario)):   # fechas explícitas: el reloj de Windows empata
            Tutor.objects.filter(pk=tutor.pk).update(creado=timezone.now() - timedelta(days=10 - dias))
        self.assertEqual(self.nombres(orden='antiguo'), ['Quintero', 'Bravo', 'Castro'])
        self.assertEqual(self.nombres(orden='-reciente'), ['Castro', 'Bravo', 'Quintero'])

    def test_filtros_invalidos_se_ignoran(self):
        self.assertEqual(len(self.nombres(estatus='XX', situacion='zzz', orden='zzz')), 3)

    def test_muestra_alumnos_vigentes_y_sin_resultados(self):
        respuesta = self.client.get(reverse('tutores:lista'))
        self.assertContains(respuesta, 'Ana Zamora')
        self.assertNotContains(respuesta, 'Luis Aranda')            # alumno de baja
        self.assertContains(self.client.get(reverse('tutores:lista'), {'q': 'nadie existe'}), 'No encontramos tutores')

    def test_sin_tutores_invita_a_registrar(self):
        TutorAlumno.objects.all().delete()
        Tutor.objects.all().delete()
        self.assertContains(self.client.get(reverse('tutores:lista')), 'Aún no hay tutores registrados')

    # --- paginación -----------------------------------------------------------------------
    def rellenar(self, cantidad):
        for i in range(cantidad):
            crear_tutor(nombre=f'Tutor{i}', apellido_paterno='Relleno', telefono=f'35399{i:05d}')

    def test_pagina(self):
        self.rellenar(25)   # 28 activos en total
        respuesta = self.client.get(reverse('tutores:lista'))
        self.assertEqual(len(respuesta.context['pagina']), 20)
        self.assertEqual(respuesta.context['pagina'].paginator.count, 28)
        self.assertContains(respuesta, 'page=2')
        self.assertEqual(len(self.client.get(reverse('tutores:lista'), {'page': 2}).context['pagina']), 8)

    def test_pagina_inexistente_lleva_a_la_ultima(self):
        self.rellenar(25)
        self.assertEqual(self.client.get(reverse('tutores:lista'), {'page': 99}).context['pagina'].number, 2)
        self.assertEqual(self.client.get(reverse('tutores:lista'), {'page': 'x'}).context['pagina'].number, 1)

    def test_elige_cuantos_por_pagina_y_rechaza_valores_no_permitidos(self):
        self.rellenar(25)
        self.assertEqual(len(self.client.get(reverse('tutores:lista'), {'por_pagina': 10}).context['pagina']), 10)
        self.assertEqual(len(self.client.get(reverse('tutores:lista'), {'por_pagina': 50}).context['pagina']), 28)
        for valor in ('5', '100000', 'abc', '-3'):
            respuesta = self.client.get(reverse('tutores:lista'), {'por_pagina': valor})
            self.assertEqual(respuesta.context['por_pagina'], 20, valor)

    def test_la_paginacion_conserva_los_filtros(self):
        self.rellenar(25)
        respuesta = self.client.get(reverse('tutores:lista'), {'q': 'relleno', 'por_pagina': 10})
        self.assertContains(respuesta, 'q=relleno')
        self.assertEqual(respuesta.context['pagina'].paginator.count, 25)

    def test_consultas_constantes_al_paginar(self):
        self.rellenar(25)
        with CaptureQueriesContext(connection) as pocas:
            self.client.get(reverse('tutores:lista'), {'por_pagina': 10})
        with CaptureQueriesContext(connection) as muchas:
            self.client.get(reverse('tutores:lista'), {'por_pagina': 50})
        self.assertLessEqual(len(muchas), len(pocas))   # no hay consultas por fila


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
@PRUEBAS
class CrearTests(BaseTestCase):
    url = property(lambda self: reverse('tutores:crear'))

    def test_el_formulario_no_ofrece_estatus_al_registrar(self):
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertNotIn('estatus', respuesta.context['form'].fields)
        self.assertContains(respuesta, 'data-persona-form')

    def test_registra_y_redirige_al_listado_con_mensaje(self):
        respuesta = self.client.post(self.url, datos_tutor(), follow=True)
        self.assertRedirects(respuesta, reverse('tutores:lista'))
        self.assertContains(respuesta, 'María López Ruiz fue registrado correctamente')
        tutor = Tutor.objects.get()
        self.assertEqual(tutor.estatus, 'ACTIVO')
        self.assertEqual(tutor.telefono, '3531234567')      # normalizado
        self.assertIsNone(tutor.curp)                       # vacío => NULL (campo único)
        self.assertIsNone(tutor.correo_electronico)

    def test_normaliza_curp_telefonos_correo_y_espacios(self):
        self.client.post(self.url, datos_tutor(
            nombre='  María   Luisa ', curp=CURP_TUTOR.lower(), telefono='+52 (353) 123-4567',
            telefono_alternativo='353 999 8877', correo_electronico='  Maria@Example.COM ', ocupacion='  Maestra   de  inglés ',
        ))
        tutor = Tutor.objects.get()
        self.assertEqual(tutor.nombre, 'María Luisa')
        self.assertEqual(tutor.curp, CURP_TUTOR)
        self.assertEqual((tutor.telefono, tutor.telefono_alternativo), ('3531234567', '3539998877'))
        self.assertEqual(tutor.correo_electronico, 'maria@example.com')
        self.assertEqual(tutor.ocupacion, 'Maestra de inglés')

    def test_varios_tutores_sin_curp_ni_correo_no_chocan(self):
        self.client.post(self.url, datos_tutor())
        self.client.post(self.url, datos_tutor(nombre='Otro', telefono='353 000 1111'))
        self.assertEqual(Tutor.objects.count(), 2)

    def test_rechaza_datos_invalidos(self):
        for campo, valor, texto in (
            ('telefono', '12345', 'teléfono'),
            ('curp', 'ABC', 'CURP'),
            ('cp', '590', '5 dígitos'),
            ('correo_electronico', 'no-es-correo', 'correo'),
            ('nombre', '', 'obligatorio'),
        ):
            respuesta = self.client.post(self.url, datos_tutor(**{campo: valor}))
            self.assertEqual(respuesta.status_code, 200, campo)
            self.assertContains(respuesta, 'hay datos por corregir', msg_prefix=campo)
            self.assertIn(campo, respuesta.context['form'].errors, campo)
        self.assertFalse(Tutor.objects.exists())

    def test_la_curp_es_unica(self):
        crear_tutor(curp=CURP_TUTOR)
        respuesta = self.client.post(self.url, datos_tutor(curp=CURP_TUTOR))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('curp', respuesta.context['form'].errors)
        self.assertEqual(Tutor.objects.count(), 1)

    def test_conserva_lo_capturado_si_hay_errores(self):
        respuesta = self.client.post(self.url, datos_tutor(telefono='1', ocupacion='Ingeniera'))
        self.assertContains(respuesta, 'value="Ingeniera"')


@PRUEBAS
class EditarTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.tutor = crear_tutor(curp=CURP_TUTOR, correo_electronico='rosa@example.com', domicilio='Calle 1', cp='59000')
        self.url = reverse('tutores:editar', args=[self.tutor.pk])

    def datos(self, **cambios):
        base = {
            'nombre': 'Rosa', 'apellido_paterno': 'Mora', 'apellido_materno': '', 'curp': CURP_TUTOR,
            'telefono': '3531112233', 'correo_electronico': 'rosa@example.com', 'estatus': 'ACTIVO',
        }
        return datos_tutor(**{**base, **cambios})

    def test_formulario_precargado_con_estatus(self):
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('estatus', respuesta.context['form'].fields)
        self.assertContains(respuesta, 'value="Rosa"')
        self.assertContains(respuesta, CURP_TUTOR)

    def test_actualiza_y_redirige_al_listado(self):
        respuesta = self.client.post(self.url, self.datos(domicilio='Nueva calle 9', ocupacion='Contadora'), follow=True)
        self.assertRedirects(respuesta, reverse('tutores:lista'))
        self.assertContains(respuesta, 'se actualizaron')
        self.tutor.refresh_from_db()
        self.assertEqual((self.tutor.domicilio, self.tutor.ocupacion), ('Nueva calle 9', 'Contadora'))

    def test_conserva_su_propia_curp_y_correo(self):
        self.assertEqual(self.client.post(self.url, self.datos()).status_code, 302)

    def test_no_permite_usar_la_curp_de_otro_tutor(self):
        crear_tutor(nombre='Otro', curp=CURP_ANA)
        respuesta = self.client.post(self.url, self.datos(curp=CURP_ANA))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('curp', respuesta.context['form'].errors)

    def test_se_puede_quitar_la_curp_y_el_correo(self):
        self.client.post(self.url, {**self.datos(curp=''), 'correo_electronico': ''})
        self.tutor.refresh_from_db()
        self.assertIsNone(self.tutor.curp)
        self.assertIsNone(self.tutor.correo_electronico)

    def test_cambiar_el_estatus_desde_el_formulario_reasigna_al_tutor_principal(self):
        alumno = crear_alumno()
        otra = crear_tutor(nombre='Jorge', apellido_paterno='Pérez', telefono='3532223344')
        principal = vincular(self.tutor, alumno, tutor_principal=True)
        secundario = vincular(otra, alumno, parentesco='PADRE')

        self.client.post(self.url, {**self.datos(), 'estatus': 'INACTIVO'})
        principal.refresh_from_db()
        secundario.refresh_from_db()
        self.assertFalse(principal.tutor_principal)
        self.assertTrue(secundario.tutor_principal)

        self.client.post(self.url, {**self.datos(), 'estatus': 'ACTIVO'})   # reactivar no le quita el rol a nadie
        secundario.refresh_from_db()
        self.assertTrue(secundario.tutor_principal)

    def test_tutor_inexistente_da_404(self):
        self.assertEqual(self.client.get(reverse('tutores:editar', args=[9999])).status_code, 404)


# ---------------------------------------------------------------------------
# Perfil
# ---------------------------------------------------------------------------
@PRUEBAS
class PerfilTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = CicloEscolar.objects.create(nombre='2026-2027', fecha_inicio='2026-08-24', fecha_fin='2027-07-10', activo=True)
        self.grado = Grado.objects.create(nivel='PRIMARIA', numero=4)
        self.tutor = crear_tutor(correo_electronico='rosa@example.com', ocupacion='Contadora', observaciones='Prefiere llamadas')
        self.ana = crear_alumno(referencia='A100', nombre='Ana', apellido_paterno='Zamora', curp=CURP_ANA)
        self.luis = crear_alumno(referencia='B200', nombre='Luis', apellido_paterno='Aranda', curp=CURP_LUIS)
        self.vinculo_ana = vincular(self.tutor, self.ana, tutor_principal=True, contacto_emergencia=True)
        self.vinculo_luis = vincular(self.tutor, self.luis, activo=False)
        Inscripcion.objects.create(alumno=self.ana, ciclo=self.ciclo, grado=self.grado)

    def test_detalle(self):
        respuesta = self.client.get(self.tutor.get_absolute_url())
        self.assertEqual(respuesta.status_code, 200)
        for texto in ('Rosa Mora', '353 111 2233', 'rosa@example.com', 'Contadora', 'Prefiere llamadas', 'Ana Zamora Mora', '4° Primaria'):
            self.assertContains(respuesta, texto)
        self.assertEqual(respuesta.context['total_vigentes'], 1)
        self.assertEqual(len(respuesta.context['vinculos']), 2)
        self.assertFalse(respuesta.context['esta_de_baja'])

    def test_los_vinculos_inactivos_se_muestran_marcados(self):
        self.assertContains(self.client.get(self.tutor.get_absolute_url()), 'Vínculo inactivo')

    def test_un_alumno_de_baja_no_cuenta_como_vigente(self):
        self.ana.estatus = 'BAJA'
        self.ana.save()
        respuesta = self.client.get(self.tutor.get_absolute_url())
        self.assertEqual(respuesta.context['total_vigentes'], 0)
        self.assertEqual(respuesta.context['sin_otro_tutor'], 0)

    def test_avisa_de_los_alumnos_que_quedarian_sin_tutor(self):
        respuesta = self.client.get(self.tutor.get_absolute_url())
        self.assertEqual(respuesta.context['sin_otro_tutor'], 1)
        vincular(crear_tutor(nombre='Jorge', apellido_paterno='Pérez', telefono='3532223344'), self.ana, parentesco='PADRE')
        self.assertEqual(self.client.get(self.tutor.get_absolute_url()).context['sin_otro_tutor'], 0)
        # un segundo tutor dado de baja no cuenta como respaldo
        Tutor.objects.filter(nombre='Jorge').update(estatus='INACTIVO')
        self.assertEqual(self.client.get(self.tutor.get_absolute_url()).context['sin_otro_tutor'], 1)

    def test_el_perfil_de_un_tutor_de_baja_ofrece_reactivar(self):
        self.tutor.estatus = 'INACTIVO'
        self.tutor.save()
        respuesta = self.client.get(self.tutor.get_absolute_url())
        self.assertTrue(respuesta.context['esta_de_baja'])
        self.assertContains(respuesta, 'Reactivar')

    def test_consultas_constantes_con_muchos_alumnos(self):
        with CaptureQueriesContext(connection) as pocas:
            self.client.get(self.tutor.get_absolute_url())
        for i in range(10):
            alumno = crear_alumno(referencia=f'R{i}', nombre=f'Alumno{i}', apellido_paterno='Relleno', curp=f'XXXX{i:06d}HMNXXXA8')
            vincular(self.tutor, alumno)
            Inscripcion.objects.create(alumno=alumno, ciclo=self.ciclo, grado=self.grado)
        with CaptureQueriesContext(connection) as muchas:
            self.client.get(self.tutor.get_absolute_url())
        self.assertEqual(len(muchas), len(pocas))

    def test_tutor_inexistente_da_404(self):
        self.assertEqual(self.client.get(reverse('tutores:detalle', args=[9999])).status_code, 404)


# ---------------------------------------------------------------------------
# Baja lógica y reactivación
# ---------------------------------------------------------------------------
@PRUEBAS
class BajaTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.alumno = crear_alumno()
        self.madre = crear_tutor(nombre='Rosa', apellido_paterno='Mora')
        self.padre = crear_tutor(nombre='Jorge', apellido_paterno='Pérez', telefono='3532223344')
        self.v_madre = vincular(self.madre, self.alumno, tutor_principal=True)
        self.v_padre = vincular(self.padre, self.alumno, parentesco='PADRE')

    def baja(self, tutor, **extra):
        return self.client.post(reverse('tutores:baja', args=[tutor.pk]), **extra)

    def test_da_de_baja_redirige_al_listado_y_confirma(self):
        respuesta = self.baja(self.madre, follow=True)
        self.assertRedirects(respuesta, reverse('tutores:lista'))
        self.assertContains(respuesta, 'Rosa Mora fue dado de baja')
        self.madre.refresh_from_db()
        self.assertEqual(self.madre.estatus, 'INACTIVO')

    def test_no_borra_nada(self):
        self.baja(self.madre)
        self.assertTrue(Tutor.objects.filter(pk=self.madre.pk).exists())
        self.assertTrue(TutorAlumno.objects.filter(pk=self.v_madre.pk).exists())
        self.assertTrue(Alumno.objects.filter(pk=self.alumno.pk).exists())

    def test_el_tutor_de_baja_sale_del_listado_y_de_las_busquedas(self):
        self.baja(self.madre)
        nombres = [t.nombre for t in self.client.get(reverse('tutores:lista')).context['pagina']]
        self.assertEqual(nombres, ['Jorge'])
        self.assertEqual(self.client.get(reverse('alumnos:tutor_buscar'), {'q': 'rosa'}).json()['resultados'], [])

    def test_otro_tutor_vigente_pasa_a_ser_el_principal(self):
        self.baja(self.madre)
        self.v_madre.refresh_from_db()
        self.v_padre.refresh_from_db()
        self.assertFalse(self.v_madre.tutor_principal)
        self.assertTrue(self.v_padre.tutor_principal)

    def test_si_era_el_unico_el_alumno_queda_sin_tutor_principal(self):
        self.baja(self.padre)
        self.baja(self.madre)
        self.assertFalse(TutorAlumno.objects.filter(alumno=self.alumno, tutor_principal=True).exists())

    def test_el_alumno_aparece_sin_tutor_en_su_listado(self):
        self.baja(self.padre)
        self.baja(self.madre)
        respuesta = self.client.get(reverse('alumnos:lista'), {'situacion': 'sin_tutor'})
        self.assertEqual(len(respuesta.context['pagina']), 1)

    def test_dar_de_baja_dos_veces_es_inofensivo(self):
        self.baja(self.madre)
        respuesta = self.baja(self.madre, follow=True)
        self.assertContains(respuesta, 'ya estaba dado de baja')

    def test_reactivar(self):
        self.baja(self.madre)
        respuesta = self.client.post(reverse('tutores:reactivar', args=[self.madre.pk]), follow=True)
        self.assertRedirects(respuesta, reverse('tutores:lista'))
        self.assertContains(respuesta, 'fue reactivado')
        self.madre.refresh_from_db()
        self.assertEqual(self.madre.estatus, 'ACTIVO')
        self.assertEqual(self.alumno.tutores_relacionados.filter(tutor_principal=True).count(), 1)

    def test_reactivar_al_unico_tutor_lo_vuelve_a_dejar_como_principal(self):
        self.baja(self.padre)
        self.baja(self.madre)
        self.client.post(reverse('tutores:reactivar', args=[self.madre.pk]))
        self.v_madre.refresh_from_db()
        self.assertTrue(self.v_madre.tutor_principal)

    def test_reactivar_a_un_tutor_activo_no_cambia_nada(self):
        antes = self.madre.modificado
        self.client.post(reverse('tutores:reactivar', args=[self.madre.pk]))
        self.madre.refresh_from_db()
        self.assertEqual(self.madre.modificado, antes)

    def test_tutor_inexistente_da_404(self):
        self.assertEqual(self.client.post(reverse('tutores:baja', args=[9999])).status_code, 404)


# ---------------------------------------------------------------------------
# Vincular y desvincular
# ---------------------------------------------------------------------------
@PRUEBAS
class VinculosTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.alumno = crear_alumno()
        self.otro = crear_alumno(referencia='2002', nombre='Ana', apellido_paterno='Zamora', curp=CURP_ANA)
        self.tutor = crear_tutor()
        self.destino = self.tutor.get_absolute_url() + '#alumnos'

    def vincular(self, tutor=None, follow=False, **datos):
        tutor = tutor or self.tutor
        datos = {'alumno': self.alumno.pk, 'parentesco': 'MADRE', 'activo': 'on', 'recibe_notificaciones': 'on', **datos}
        return self.client.post(reverse('tutores:vincular', args=[tutor.pk]), datos, follow=follow)

    def test_vincula_a_un_alumno(self):
        respuesta = self.vincular(contacto_emergencia='on', observaciones='Llamar primero')
        self.assertRedirects(respuesta, self.destino, fetch_redirect_response=False)
        vinculo = TutorAlumno.objects.get()
        self.assertEqual((vinculo.tutor, vinculo.alumno, vinculo.parentesco), (self.tutor, self.alumno, 'MADRE'))
        self.assertTrue(vinculo.contacto_emergencia and vinculo.activo and vinculo.recibe_notificaciones)
        self.assertEqual(vinculo.observaciones, 'Llamar primero')
        self.assertFalse(vinculo.autorizado_recoger)

    def test_el_primer_tutor_del_alumno_queda_como_principal(self):
        self.vincular()
        self.assertTrue(TutorAlumno.objects.get().tutor_principal)

    def test_un_segundo_tutor_no_le_quita_el_rol_al_principal(self):
        self.vincular()
        otro = crear_tutor(nombre='Jorge', apellido_paterno='Pérez', telefono='3532223344')
        self.vincular(tutor=otro, parentesco='PADRE')
        self.assertEqual(list(TutorAlumno.objects.filter(tutor_principal=True).values_list('tutor', flat=True)), [self.tutor.pk])

    def test_pedir_ser_principal_se_lo_quita_al_anterior(self):
        self.vincular()
        otro = crear_tutor(nombre='Jorge', apellido_paterno='Pérez', telefono='3532223344')
        self.vincular(tutor=otro, parentesco='PADRE', tutor_principal='on')
        self.assertEqual(list(TutorAlumno.objects.filter(tutor_principal=True).values_list('tutor', flat=True)), [otro.pk])

    def test_un_vinculo_inactivo_nunca_es_principal(self):
        self.vincular(tutor_principal='on', activo='')
        vinculo = TutorAlumno.objects.get()
        self.assertFalse(vinculo.activo or vinculo.tutor_principal)

    def test_vincular_otra_vez_actualiza_en_lugar_de_duplicar(self):
        self.vincular()
        respuesta = self.client.post(reverse('tutores:vincular', args=[self.tutor.pk]), {
            'alumno': self.alumno.pk, 'parentesco': 'TUTOR_LEGAL', 'activo': 'on', 'autorizado_recoger': 'on',
        }, follow=True)
        self.assertContains(respuesta, 'Se actualizó el vínculo')
        vinculo = TutorAlumno.objects.get()
        self.assertEqual(vinculo.parentesco, 'TUTOR_LEGAL')
        self.assertTrue(vinculo.autorizado_recoger)
        self.assertFalse(vinculo.recibe_notificaciones)   # no venía marcado

    def test_reactiva_un_vinculo_inactivo(self):
        vincular(self.tutor, self.alumno, activo=False)
        self.vincular()
        vinculo = TutorAlumno.objects.get()
        self.assertTrue(vinculo.activo)

    def test_exige_alumno_y_parentesco(self):
        respuesta = self.vincular(alumno='', follow=True)
        self.assertContains(respuesta, 'Busca y elige un alumno')
        respuesta = self.vincular(parentesco='', follow=True)
        self.assertContains(respuesta, 'Indica el parentesco')
        self.assertContains(self.vincular(alumno=9999, follow=True), 'No se pudo guardar el vínculo')
        self.assertFalse(TutorAlumno.objects.exists())

    def test_un_tutor_de_baja_no_se_puede_vincular(self):
        self.tutor.estatus = 'INACTIVO'
        self.tutor.save()
        respuesta = self.vincular(follow=True)
        self.assertContains(respuesta, 'Reactiva al tutor')
        self.assertFalse(TutorAlumno.objects.exists())

    # --- desvincular ---------------------------------------------------------------------
    def desvincular(self, vinculo_id, tutor=None):
        return self.client.post(reverse('tutores:desvincular', args=[(tutor or self.tutor).pk]), {'vinculo': vinculo_id})

    def test_desvincular_es_logico(self):
        vinculo = vincular(self.tutor, self.alumno, tutor_principal=True)
        respuesta = self.desvincular(vinculo.pk)
        self.assertRedirects(respuesta, self.destino, fetch_redirect_response=False)
        vinculo.refresh_from_db()
        self.assertFalse(vinculo.activo)
        self.assertFalse(vinculo.tutor_principal)
        self.assertTrue(Tutor.objects.filter(pk=self.tutor.pk).exists())

    def test_al_desvincular_al_principal_otro_tutor_toma_su_lugar(self):
        otro = crear_tutor(nombre='Jorge', apellido_paterno='Pérez', telefono='3532223344')
        principal = vincular(self.tutor, self.alumno, tutor_principal=True)
        secundario = vincular(otro, self.alumno, parentesco='PADRE')
        self.desvincular(principal.pk)
        secundario.refresh_from_db()
        self.assertTrue(secundario.tutor_principal)

    def test_no_desvincula_vinculos_de_otro_tutor(self):
        otro = crear_tutor(nombre='Jorge', apellido_paterno='Pérez', telefono='3532223344')
        ajeno = vincular(otro, self.alumno)
        self.assertEqual(self.desvincular(ajeno.pk).status_code, 404)
        ajeno.refresh_from_db()
        self.assertTrue(ajeno.activo)

    def test_vinculo_invalido_da_404(self):
        for valor in ('', 'abc', '-1', '9999', '1 OR 1=1'):
            self.assertEqual(self.desvincular(valor).status_code, 404, valor)


# ---------------------------------------------------------------------------
# Exportación
# ---------------------------------------------------------------------------
@PRUEBAS
class ExportarTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ana = crear_alumno(referencia='1', nombre='Ana', apellido_paterno='Zamora', curp=CURP_ANA)
        self.rosa = crear_tutor(nombre='=Rosa', apellido_paterno='Quintero', telefono='3531112233', correo_electronico='rosa@example.com')
        self.baja = crear_tutor(nombre='Elena', apellido_paterno='Duarte', telefono='3530001122', estatus='INACTIVO')
        vincular(self.rosa, self.ana, tutor_principal=True)

    def filas(self, **filtros):
        respuesta = self.client.get(reverse('tutores:exportar'), filtros)
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('text/csv', respuesta['Content-Type'])
        self.assertIn('attachment; filename="tutores-', respuesta['Content-Disposition'])
        contenido = respuesta.content.decode('utf-8')
        self.assertTrue(contenido.startswith('﻿'))
        return list(csv.reader(io.StringIO(contenido.lstrip('﻿'))))

    def test_exporta_solo_los_activos_por_defecto(self):
        filas = self.filas()
        self.assertEqual(filas[0][:3], ['Nombre', 'Apellido paterno', 'Apellido materno'])
        self.assertEqual(len(filas), 2)
        self.assertEqual(filas[1][0], "'=Rosa")                  # neutraliza fórmulas de Excel
        self.assertIn('Ana Zamora Mora', filas[1])
        self.assertIn('3531112233', filas[1])

    def test_respeta_los_filtros(self):
        filas = self.filas(estatus='INACTIVO')
        self.assertEqual([fila[1] for fila in filas[1:]], ['Duarte'])
        self.assertEqual(len(self.filas(q='nadie')), 1)
