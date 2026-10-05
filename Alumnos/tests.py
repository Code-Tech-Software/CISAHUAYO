import csv
import io
import shutil
import tempfile
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from PIL import Image

from .models import (
    Alumno,
    AsistenciaGeneral,
    CicloEscolar,
    Grado,
    Inscripcion,
    Tutor,
    TutorAlumno,
)
from .utils import (
    datos_de_curp,
    normalizar_telefono,
    proteger_celda_csv,
    siguiente_referencia,
    validar_telefono,
)

MEDIA_TEMPORAL = tempfile.mkdtemp(prefix='cisahuayo-test-media-')

# Los tests corren con DEBUG=False: se usa almacenamiento simple (sin manifiesto ni Cloudinary).
PRUEBAS = override_settings(
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
    MEDIA_ROOT=MEDIA_TEMPORAL,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],  # solo en tests: el real es muy lento
)

CURP_ANA = 'GALA150315MMNRPNA1'    # mujer, 15/03/2015
CURP_LUIS = 'PEMJ100720HMNRRNA5'   # hombre, 20/07/2010
CURP_TUTOR = 'LOPM850101MMNPRR03'  # mujer, 01/01/1985


def tearDownModule():
    shutil.rmtree(MEDIA_TEMPORAL, ignore_errors=True)


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------
def datos_alumno(**cambios):
    datos = {
        'nombre': 'Ana',
        'apellido_paterno': 'García',
        'apellido_materno': 'López',
        'curp': CURP_ANA,
        'fecha_nacimiento': '2015-03-15',
        'sexo': 'F',
        'nacionalidad': 'Mexicana',
        'religion': '',
        'domicilio': 'Calle Hidalgo 123',
        'colonia': 'Centro',
        'ciudad': 'Sahuayo',
        'estado': 'Michoacán',
        'cp': '59000',
        'grupo_sanguineo': 'O+',
        'alergias': '',
        'observaciones_generales': '',
        'fecha_ingreso': '2026-08-24',
        'escuela_procedencia': '',
        'referencia': '1001',
        'uid': '',
        'correo_electronico': '',
        'contrasena_inicial': 'secreto1',
    }
    datos.update(cambios)
    return datos


def tutor_nuevo(**cambios):
    datos = {
        'modo': 'nuevo',
        'nombre': 'María',
        'apellido_paterno': 'López',
        'apellido_materno': 'Ruiz',
        'telefono': '353 123 4567',
        'correo_electronico': 'maria@example.com',
        'parentesco': 'MADRE',
        'mismo_domicilio': 'on',
        'recibe_notificaciones': 'on',
        'activo': 'on',
    }
    datos.update(cambios)
    return datos


def tutor_existente(tutor, **cambios):
    datos = {
        'modo': 'existente',
        'tutor': tutor.pk,
        'parentesco': 'PADRE',
        'recibe_notificaciones': 'on',
        'activo': 'on',
    }
    datos.update(cambios)
    return datos


def datos_tutores(*tutores, iniciales=0):
    """Datos del formset (prefijo 'tutores'); None en un lugar = formulario sin cambios."""
    datos = {
        'tutores-TOTAL_FORMS': len(tutores),
        'tutores-INITIAL_FORMS': iniciales,
        'tutores-MIN_NUM_FORMS': 0,
        'tutores-MAX_NUM_FORMS': 1000,
    }
    for i, tutor in enumerate(tutores):
        for campo, valor in tutor.items():
            datos[f'tutores-{i}-{campo}'] = valor
    return datos


def crear_alumno(**cambios):
    datos = {
        'referencia': '2001', 'nombre': 'Luis', 'apellido_paterno': 'Pérez', 'apellido_materno': 'Mora',
        'curp': CURP_LUIS, 'sexo': 'M', 'fecha_nacimiento': date(2010, 7, 20), 'grupo_sanguineo': 'A+',
        'domicilio': 'Av. Juárez 45', 'colonia': 'Centro', 'ciudad': 'Sahuayo', 'estado': 'Michoacán',
        'cp': '59000', 'contrasena': 'hash',
    }
    datos.update(cambios)
    return Alumno.objects.create(**datos)


def crear_tutor(**cambios):
    datos = {'nombre': 'Rosa', 'apellido_paterno': 'Mora', 'telefono': '3531112233'}
    datos.update(cambios)
    return Tutor.objects.create(**datos)


def png(nombre='foto.png', tamano=(40, 40)):
    buffer = io.BytesIO()
    Image.new('RGB', tamano, (80, 90, 200)).save(buffer, 'PNG')
    return SimpleUploadedFile(nombre, buffer.getvalue(), content_type='image/png')


class BaseTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser('admin', 'admin@example.com', 'x')
        cls.sin_permisos = User.objects.create_user('visitante', password='x')

    def setUp(self):
        self.client.force_login(self.admin)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
class UtilidadesTests(SimpleTestCase):
    def test_curp_de_mujer_nacida_en_los_2000(self):
        self.assertEqual(datos_de_curp(CURP_ANA), {'fecha_nacimiento': date(2015, 3, 15), 'sexo': 'F'})

    def test_curp_de_hombre_y_minusculas(self):
        self.assertEqual(datos_de_curp(CURP_LUIS.lower()), {'fecha_nacimiento': date(2010, 7, 20), 'sexo': 'M'})

    def test_el_digito_diferenciador_define_el_siglo(self):
        self.assertEqual(datos_de_curp(CURP_TUTOR)['fecha_nacimiento'], date(1985, 1, 1))

    def test_curp_invalida(self):
        for curp in ('', 'ABC', 'GALA151315MMNRPNA1', 'GALA150315XMNRPNA1', 'GALA150230MMNRPNA1'):
            self.assertIsNone(datos_de_curp(curp), curp)

    def test_telefono(self):
        self.assertEqual(normalizar_telefono('+52 (353) 123-4567'), '3531234567')
        self.assertEqual(normalizar_telefono('52 1 353 123 4567'), '3531234567')
        self.assertEqual(validar_telefono('353 123 4567'), '3531234567')
        with self.assertRaises(Exception):
            validar_telefono('12345')

    def test_proteger_celdas_csv(self):
        self.assertEqual(proteger_celda_csv('=SUMA(A1)'), "'=SUMA(A1)")
        self.assertEqual(proteger_celda_csv('Ana'), 'Ana')
        self.assertEqual(proteger_celda_csv(None), '')


class ReferenciaTests(TestCase):
    def test_sin_alumnos_usa_el_anio(self):
        self.assertRegex(siguiente_referencia(), r'^\d{4}0001$')

    def test_incrementa_conservando_el_ancho(self):
        crear_alumno(referencia='0099', curp=CURP_LUIS)
        crear_alumno(referencia='ABC-5', curp=CURP_ANA, nombre='Otra')
        self.assertEqual(siguiente_referencia(), '0100')

    def test_compara_numericamente(self):
        crear_alumno(referencia='999', curp=CURP_LUIS)
        crear_alumno(referencia='1000', curp=CURP_ANA, nombre='Otra')
        self.assertEqual(siguiente_referencia(), '1001')


# ---------------------------------------------------------------------------
# Permisos
# ---------------------------------------------------------------------------
@PRUEBAS
class PermisosTests(BaseTestCase):
    def test_anonimo_es_enviado_al_login(self):
        self.client.logout()
        alumno = crear_alumno()
        for nombre, args in (('lista', []), ('crear', []), ('detalle', [alumno.pk]), ('editar', [alumno.pk]), ('exportar', [])):
            respuesta = self.client.get(reverse(f'alumnos:{nombre}', args=args))
            self.assertEqual(respuesta.status_code, 302, nombre)
            self.assertIn('/admin/login/', respuesta['Location'])
            self.assertIn('next=', respuesta['Location'])

    def test_sin_permisos_recibe_403(self):
        self.client.force_login(self.sin_permisos)
        alumno = crear_alumno()
        for nombre, args in (('lista', []), ('crear', []), ('detalle', [alumno.pk]), ('editar', [alumno.pk])):
            self.assertEqual(self.client.get(reverse(f'alumnos:{nombre}', args=args)).status_code, 403, nombre)
        for nombre in ('baja', 'reactivar'):
            self.assertEqual(self.client.post(reverse(f'alumnos:{nombre}', args=[alumno.pk])).status_code, 403, nombre)
        self.assertEqual(self.client.get(reverse('alumnos:tutor_buscar') + '?q=ro').status_code, 403)
        self.assertEqual(self.client.get(reverse('alumnos:buscar') + '?q=lu').status_code, 403)
        alumno.refresh_from_db()
        self.assertEqual(alumno.estatus, 'ACTIVO')

    def test_dar_de_baja_exige_el_permiso_de_eliminar(self):
        self.client.force_login(self.sin_permisos)
        self.sin_permisos.user_permissions.add(Permission.objects.get(codename='change_alumno'))
        alumno = crear_alumno()
        self.assertEqual(self.client.post(reverse('alumnos:baja', args=[alumno.pk])).status_code, 403)
        self.sin_permisos.user_permissions.add(Permission.objects.get(codename='delete_alumno'))
        self.sin_permisos = get_user_model().objects.get(pk=self.sin_permisos.pk)  # descarta el caché de permisos
        self.client.force_login(self.sin_permisos)
        self.assertEqual(self.client.post(reverse('alumnos:baja', args=[alumno.pk])).status_code, 302)

    def test_las_acciones_solo_aceptan_post(self):
        alumno = crear_alumno()
        for nombre in ('estatus', 'contrasena', 'inscribir', 'baja', 'reactivar'):
            self.assertEqual(self.client.get(reverse(f'alumnos:{nombre}', args=[alumno.pk])).status_code, 405, nombre)


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------
@PRUEBAS
class ListaTests(BaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.ciclo = CicloEscolar.objects.create(nombre='2026-2027', fecha_inicio=date(2026, 8, 24), fecha_fin=date(2027, 7, 10), activo=True)
        cls.viejo = CicloEscolar.objects.create(nombre='2024-2025', fecha_inicio=date(2024, 8, 24), fecha_fin=date(2025, 7, 10), activo=False)
        cls.primero = Grado.objects.create(nivel='PRIMARIA', numero=1)
        cls.segundo = Grado.objects.create(nivel='PRIMARIA', numero=2)

        cls.ana = crear_alumno(referencia='A100', nombre='Ana', apellido_paterno='Zamora', curp=CURP_ANA, estatus='ACTIVO')
        cls.luis = crear_alumno(referencia='B200', nombre='Luis', apellido_paterno='Aranda', curp=CURP_LUIS, estatus='BAJA')
        cls.sin_tutor = crear_alumno(referencia='C300', nombre='Sara', apellido_paterno='Medina', curp='RASL020408HMNMNSA8')

        Inscripcion.objects.create(alumno=cls.ana, ciclo=cls.ciclo, grado=cls.primero)
        Inscripcion.objects.create(alumno=cls.luis, ciclo=cls.viejo, grado=cls.segundo)  # ciclo anterior
        cls.tutora = crear_tutor(nombre='Rosa', apellido_paterno='Quintero')
        TutorAlumno.objects.create(tutor=cls.tutora, alumno=cls.ana, parentesco='MADRE', tutor_principal=True)
        TutorAlumno.objects.create(tutor=cls.tutora, alumno=cls.luis, parentesco='MADRE')

    def nombres(self, **filtros):
        respuesta = self.client.get(reverse('alumnos:lista'), filtros)
        self.assertEqual(respuesta.status_code, 200)
        return [str(a) for a in respuesta.context['pagina']]

    def test_orden_por_defecto_alfabetico_por_apellido(self):
        self.assertEqual([n.split()[1] for n in self.nombres()], ['Medina', 'Zamora'])

    def test_las_bajas_no_aparecen_salvo_que_se_pidan(self):
        self.assertNotIn('Luis Aranda Mora', self.nombres())
        self.assertNotIn('Luis Aranda Mora', self.nombres(q='aranda'))
        self.assertIn('Luis Aranda Mora', self.nombres(estatus='BAJA'))

    def test_busca_por_nombre_referencia_y_curp(self):
        self.assertEqual(len(self.nombres(q='ana zamora')), 1)
        self.assertEqual(len(self.nombres(q='MEDINA')), 1)
        self.assertEqual([n.split()[1] for n in self.nombres(q='B200', estatus='BAJA')], ['Aranda'])
        self.assertEqual(self.nombres(q='RASL020408'), ['Sara Medina Mora'])

    def test_busca_por_tutor_sin_duplicar(self):
        self.assertEqual([n.split()[1] for n in self.nombres(q='quintero')], ['Zamora'])
        resultado = self.nombres(q='quintero', estatus='')
        self.assertEqual(sorted(n.split()[1] for n in resultado), ['Zamora'])
        self.assertEqual(sorted(n.split()[1] for n in self.nombres(q='quintero', estatus='BAJA')), ['Aranda'])

    def test_filtra_por_estatus(self):
        self.assertEqual([n.split()[1] for n in self.nombres(estatus='BAJA')], ['Aranda'])
        self.assertEqual(sorted(n.split()[1] for n in self.nombres(estatus='ACTIVO')), ['Medina', 'Zamora'])

    def test_filtra_por_grado_actual(self):
        self.assertEqual([n.split()[1] for n in self.nombres(grado=self.primero.pk)], ['Zamora'])
        self.assertEqual(self.nombres(grado=self.segundo.pk), [])  # su inscripción es de un ciclo que ya no está activo

    def test_filtra_por_situacion(self):
        self.assertEqual([n.split()[1] for n in self.nombres(situacion='inscritos')], ['Zamora'])
        self.assertEqual([n.split()[1] for n in self.nombres(situacion='sin_inscripcion')], ['Medina'])
        self.assertEqual(self.nombres(situacion='sin_tutor'), ['Sara Medina Mora'])

    def test_filtros_invalidos_se_ignoran(self):
        self.assertEqual(len(self.nombres(estatus='XX', grado='999', orden='zzz')), 2)

    def test_ordena(self):
        self.assertEqual(self.nombres(orden='-nombre')[0].split()[1], 'Zamora')

    def test_muestra_grado_tutor_y_conteos(self):
        respuesta = self.client.get(reverse('alumnos:lista'))
        html = respuesta.content.decode()
        self.assertIn('1° Primaria', html)
        self.assertIn('Rosa Quintero', html)
        self.assertIn('Sin tutor', html)
        self.assertEqual(respuesta.context['total_alumnos'], 2)   # las bajas no cuentan como alumnos
        self.assertEqual(respuesta.context['total_bajas'], 1)
        conteos = {e['valor']: e['total'] for e in respuesta.context['estatus_filtros']}
        self.assertEqual(conteos, {'ACTIVO': 2, 'BAJA': 1, 'EGRESADO': 0, 'SUSPENDIDO': 0})

    def rellenar(self, cantidad):
        for i in range(cantidad):
            crear_alumno(referencia=f'9{i:03d}', nombre=f'Alumno{i}', apellido_paterno='Relleno', curp=f'XXXX{i:06d}HMNXXXA8')

    def test_pagina(self):
        self.rellenar(25)   # 27 visibles con Ana y Sara; Luis está de baja
        respuesta = self.client.get(reverse('alumnos:lista'))
        self.assertEqual(len(respuesta.context['pagina']), 20)
        self.assertEqual(respuesta.context['pagina'].paginator.count, 27)
        self.assertContains(respuesta, 'page=2')
        self.assertEqual(len(self.client.get(reverse('alumnos:lista'), {'page': 2}).context['pagina']), 7)

    def test_pagina_inexistente_lleva_a_la_ultima(self):
        self.rellenar(25)
        self.assertEqual(self.client.get(reverse('alumnos:lista'), {'page': 99}).context['pagina'].number, 2)
        self.assertEqual(self.client.get(reverse('alumnos:lista'), {'page': 'x'}).context['pagina'].number, 1)

    def test_elige_cuantos_alumnos_por_pagina(self):
        self.rellenar(25)
        respuesta = self.client.get(reverse('alumnos:lista'), {'por_pagina': 10})
        self.assertEqual(len(respuesta.context['pagina']), 10)
        self.assertEqual(respuesta.context['por_pagina'], 10)
        self.assertContains(respuesta, 'por_pagina=10')
        self.assertEqual(len(self.client.get(reverse('alumnos:lista'), {'por_pagina': 50}).context['pagina']), 27)

    def test_ignora_un_tamano_de_pagina_no_permitido(self):
        self.rellenar(25)
        for valor in ('5', '100000', 'abc', '-3'):
            respuesta = self.client.get(reverse('alumnos:lista'), {'por_pagina': valor})
            self.assertEqual(respuesta.context['por_pagina'], 20, valor)
            self.assertEqual(len(respuesta.context['pagina']), 20, valor)

    def test_la_paginacion_conserva_los_filtros(self):
        self.rellenar(25)
        respuesta = self.client.get(reverse('alumnos:lista'), {'q': 'relleno', 'por_pagina': 10})
        self.assertContains(respuesta, 'q=relleno')
        self.assertEqual(respuesta.context['pagina'].paginator.count, 25)

    def test_consultas_constantes_al_paginar(self):
        self.rellenar(25)
        with CaptureQueriesContext(connection) as pocas:
            self.client.get(reverse('alumnos:lista'), {'por_pagina': 10})
        with CaptureQueriesContext(connection) as muchas:
            self.client.get(reverse('alumnos:lista'), {'por_pagina': 50})
        self.assertLessEqual(len(muchas), len(pocas))   # no hay consultas por fila

    def test_sin_resultados_ofrece_limpiar(self):
        respuesta = self.client.get(reverse('alumnos:lista'), {'q': 'nadie existe'})
        self.assertContains(respuesta, 'No encontramos alumnos')

    def test_sin_alumnos_invita_a_registrar(self):
        Inscripcion.objects.all().delete()
        Alumno.objects.all().delete()
        self.assertContains(self.client.get(reverse('alumnos:lista')), 'Aún no hay alumnos registrados')


# ---------------------------------------------------------------------------
# Registro (asistente)
# ---------------------------------------------------------------------------
@PRUEBAS
class CrearTests(BaseTestCase):
    url = property(lambda self: reverse('alumnos:crear'))

    def publicar(self, alumno=None, tutores=None, **extra):
        datos = {**(alumno or datos_alumno()), **datos_tutores(*(tutores if tutores is not None else [tutor_nuevo(tutor_principal='on')]))}
        datos.update(extra)
        return self.client.post(self.url, datos)

    def test_el_asistente_se_muestra_con_valores_sugeridos(self):
        crear_alumno(referencia='8888')
        respuesta = self.client.get(self.url)
        html = respuesta.content.decode()
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(html.count('data-step-panel'), 5)
        self.assertIn('name="tutores-TOTAL_FORMS"', html)
        self.assertIn('data-tutor-template', html)
        self.assertIn('value="8889"', html)          # siguiente referencia
        self.assertIn('value="Sahuayo"', html)
        self.assertIn('name="insc-inscribir"', html)
        self.assertNotIn('name="estatus"', html)     # al registrar nace como activo
        self.assertEqual(len(respuesta.context['form'].fields['contrasena_inicial'].initial), 8)

    def test_registra_alumno_con_tutor_nuevo(self):
        respuesta = self.publicar()
        alumno = Alumno.objects.get(referencia='1001')
        self.assertRedirects(respuesta, reverse('alumnos:lista'))

        self.assertEqual(alumno.estatus, 'ACTIVO')
        self.assertEqual(alumno.curp, CURP_ANA)
        self.assertIsNone(alumno.correo_electronico)   # vacío => NULL (campo único)
        self.assertIsNone(alumno.uid)
        self.assertNotEqual(alumno.contrasena, 'secreto1')
        self.assertTrue(check_password('secreto1', alumno.contrasena))

        vinculo = alumno.tutores_relacionados.get()
        self.assertEqual(vinculo.parentesco, 'MADRE')
        self.assertTrue(vinculo.tutor_principal)
        self.assertTrue(vinculo.activo)
        tutor = vinculo.tutor
        self.assertEqual(tutor.telefono, '3531234567')          # normalizado
        self.assertEqual(tutor.correo_electronico, 'maria@example.com')
        self.assertIsNone(tutor.curp)                            # sin CURP => NULL
        self.assertEqual((tutor.domicilio, tutor.cp), ('Calle Hidalgo 123', '59000'))  # mismo domicilio

    def test_confirma_el_registro_con_un_mensaje(self):
        respuesta = self.publicar()
        self.assertContains(self.client.get(respuesta['Location']), 'Ana García López')

    def test_las_credenciales_se_muestran_una_sola_vez_en_el_listado(self):
        respuesta = self.publicar()
        listado = self.client.get(respuesta['Location'])
        self.assertContains(listado, 'Credenciales de acceso')
        self.assertContains(listado, 'secreto1')
        self.assertContains(listado, Alumno.objects.get().get_absolute_url())   # enlace al perfil recién creado
        self.assertNotContains(self.client.get(respuesta['Location']), 'secreto1')

    def test_genera_contrasena_si_se_deja_vacia(self):
        respuesta = self.publicar(alumno=datos_alumno(contrasena_inicial=''))
        generada = self.client.session['credenciales_alumno']['contrasena']
        self.assertEqual(len(generada), 8)
        self.assertTrue(check_password(generada, Alumno.objects.get(referencia='1001').contrasena))
        self.assertEqual(respuesta.status_code, 302)

    def test_rechaza_contrasena_corta(self):
        respuesta = self.publicar(alumno=datos_alumno(contrasena_inicial='123'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Usa al menos 6 caracteres')

    def test_vincula_a_un_tutor_existente(self):
        hermano = crear_alumno()
        tutora = crear_tutor()
        TutorAlumno.objects.create(tutor=tutora, alumno=hermano, parentesco='MADRE', tutor_principal=True)

        self.publicar(tutores=[tutor_existente(tutora, parentesco='MADRE')])
        alumno = Alumno.objects.get(referencia='1001')
        self.assertEqual(Tutor.objects.count(), 1)                 # no se duplicó
        vinculo = alumno.tutores_relacionados.get()
        self.assertEqual(vinculo.tutor, tutora)
        self.assertTrue(vinculo.tutor_principal)                   # el primero queda como principal
        self.assertEqual(tutora.alumnos_relacionados.count(), 2)

    def test_varios_tutores_y_un_solo_principal(self):
        existente = crear_tutor(nombre='Jorge', apellido_paterno='Pérez')
        self.publicar(tutores=[
            tutor_nuevo(tutor_principal='on', contacto_emergencia='on'),
            tutor_existente(existente, autorizado_recoger='on', responsable_pagos='on'),
        ])
        alumno = Alumno.objects.get(referencia='1001')
        self.assertEqual(alumno.tutores_relacionados.count(), 2)
        self.assertEqual(alumno.tutores_relacionados.filter(tutor_principal=True).count(), 1)
        padre = alumno.tutores_relacionados.get(tutor=existente)
        self.assertTrue(padre.autorizado_recoger and padre.responsable_pagos)
        self.assertFalse(padre.contacto_emergencia)

    def test_sin_principal_marca_al_primero(self):
        self.publicar(tutores=[tutor_nuevo(), tutor_nuevo(nombre='Pedro', parentesco='PADRE', telefono='3539998877')])
        alumno = Alumno.objects.get(referencia='1001')
        self.assertEqual(alumno.tutores_relacionados.get(tutor_principal=True).tutor.nombre, 'María')

    def test_exige_al_menos_un_tutor(self):
        respuesta = self.publicar(tutores=[])
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Agrega al menos un tutor')
        self.assertFalse(Alumno.objects.exists())

    def test_un_formulario_de_tutor_vacio_se_ignora(self):
        vacio = {'modo': 'nuevo', 'mismo_domicilio': 'on', 'recibe_notificaciones': 'on', 'activo': 'on'}
        self.publicar(tutores=[tutor_nuevo(tutor_principal='on'), vacio])
        self.assertEqual(Alumno.objects.get(referencia='1001').tutores_relacionados.count(), 1)

    def test_rechaza_dos_principales(self):
        respuesta = self.publicar(tutores=[tutor_nuevo(tutor_principal='on'), tutor_nuevo(nombre='Pedro', parentesco='PADRE', telefono='3539998877', tutor_principal='on')])
        self.assertContains(respuesta, 'Solo puede haber un tutor principal')
        self.assertFalse(Alumno.objects.exists())

    def test_rechaza_el_mismo_tutor_dos_veces(self):
        tutor = crear_tutor()
        respuesta = self.publicar(tutores=[tutor_existente(tutor), tutor_existente(tutor, parentesco='TIO')])
        self.assertContains(respuesta, 'no puede agregarse dos veces')
        self.assertFalse(Alumno.objects.exists())

    def test_valida_los_datos_del_tutor_nuevo(self):
        respuesta = self.publicar(tutores=[tutor_nuevo(nombre='', telefono='123', parentesco='')])
        html = respuesta.content.decode()
        self.assertIn('Escribe el nombre del tutor', html)
        self.assertIn('Ingresa un teléfono de 10 dígitos', html)
        self.assertIn('Indica el parentesco', html)
        self.assertFalse(Alumno.objects.exists())

    def test_tutor_existente_sin_seleccion(self):
        respuesta = self.publicar(tutores=[{'modo': 'existente', 'parentesco': 'MADRE', 'recibe_notificaciones': 'on', 'activo': 'on'}])
        self.assertContains(respuesta, 'Selecciona un tutor de la lista')

    def test_sugiere_vincular_si_la_curp_del_tutor_ya_existe(self):
        crear_tutor(nombre='Elena', apellido_paterno='Ruiz', curp=CURP_TUTOR)
        respuesta = self.publicar(tutores=[tutor_nuevo(curp=CURP_TUTOR.lower())])
        self.assertContains(respuesta, 'Ya existe un tutor con esta CURP')
        self.assertContains(respuesta, 'Elena Ruiz')
        self.assertEqual(Tutor.objects.count(), 1)

    def test_curp_de_tutor_nuevo_se_normaliza(self):
        self.publicar(tutores=[tutor_nuevo(curp=f' {CURP_TUTOR.lower()} ', tutor_principal='on')])
        self.assertEqual(Tutor.objects.get().curp, CURP_TUTOR)

    def test_valida_curp_del_alumno(self):
        self.assertContains(self.publicar(alumno=datos_alumno(curp='XXXX')), 'La CURP no tiene un formato válido')
        self.assertFalse(Alumno.objects.exists())

    def test_curp_y_referencia_unicas(self):
        crear_alumno(referencia='1001', curp=CURP_ANA)
        respuesta = self.publicar()
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(Alumno.objects.count(), 1)
        self.assertTrue(respuesta.context['form'].errors.keys() >= {'curp', 'referencia'})

    def test_correo_y_uid_unicos_solo_si_se_capturan(self):
        crear_alumno(referencia='1000', curp=CURP_LUIS, correo_electronico='x@example.com', uid='AB12')
        self.assertEqual(self.publicar(alumno=datos_alumno(correo_electronico='X@example.com')).status_code, 200)
        self.assertEqual(self.publicar(alumno=datos_alumno(uid='AB12')).status_code, 200)
        self.assertEqual(Alumno.objects.count(), 1)
        self.assertEqual(self.publicar().status_code, 302)  # sin correo ni UID: no choca con el otro

    def test_dos_alumnos_sin_correo_ni_uid(self):
        self.assertEqual(self.publicar().status_code, 302)
        otro = datos_alumno(curp=CURP_LUIS, referencia='1002', nombre='Luis')
        self.assertEqual(self.publicar(alumno=otro).status_code, 302)
        self.assertEqual(Alumno.objects.count(), 2)

    def test_fecha_de_nacimiento_futura(self):
        self.assertContains(self.publicar(alumno=datos_alumno(fecha_nacimiento='2999-01-01')), 'no puede ser futura')

    def test_espacios_sobrantes_en_nombres(self):
        self.publicar(alumno=datos_alumno(nombre='  Ana   María ', apellido_paterno=' García  '))
        self.assertEqual(Alumno.objects.get().nombre, 'Ana María')
        self.assertEqual(Alumno.objects.get().apellido_paterno, 'García')

    def test_inscripcion_opcional(self):
        ciclo = CicloEscolar.objects.create(nombre='2026-2027', fecha_inicio=date(2026, 8, 24), fecha_fin=date(2027, 7, 10))
        grado = Grado.objects.create(nivel='PRIMARIA', numero=3)
        respuesta = self.publicar(**{'insc-inscribir': 'on', 'insc-ciclo': ciclo.pk, 'insc-grado': grado.pk})
        alumno = Alumno.objects.get()
        self.assertEqual(alumno.inscripciones.get().grado, grado)
        self.assertRedirects(respuesta, reverse('alumnos:lista'))
        self.assertContains(self.client.get(alumno.get_absolute_url()), '3° Primaria')

    def test_sin_inscribir_no_crea_inscripcion(self):
        self.publicar(**{'insc-ciclo': '', 'insc-grado': ''})
        self.assertFalse(Inscripcion.objects.exists())

    def test_inscribir_exige_ciclo_y_grado(self):
        respuesta = self.publicar(**{'insc-inscribir': 'on'})
        self.assertContains(respuesta, 'Elige el ciclo escolar')
        self.assertContains(respuesta, 'Elige el grado')
        self.assertFalse(Alumno.objects.exists())

    def test_los_errores_vuelven_con_los_datos_capturados(self):
        respuesta = self.publicar(alumno=datos_alumno(curp='MAL'), tutores=[tutor_nuevo(nombre='Marisol')])
        html = respuesta.content.decode()
        self.assertIn('value="Marisol"', html)
        self.assertIn('value="Ana"', html)

    def test_sube_la_fotografia(self):
        self.publicar(alumno=datos_alumno(fotografia=png()))
        alumno = Alumno.objects.get()
        self.assertTrue(alumno.fotografia.name.startswith('alumnos/'))
        self.assertTrue(alumno.fotografia.storage.exists(alumno.fotografia.name))

    def test_rechaza_archivos_que_no_son_imagen(self):
        falso = SimpleUploadedFile('virus.png', b'no soy una imagen', content_type='image/png')
        respuesta = self.publicar(alumno=datos_alumno(fotografia=falso))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('fotografia', respuesta.context['form'].errors)

    def test_rechaza_fotos_que_superan_el_limite(self):
        with patch('Alumnos.forms.TAMANO_MAXIMO_FOTO', 100):  # la foto de prueba pesa más de 100 bytes
            respuesta = self.publicar(alumno=datos_alumno(fotografia=png()))
        self.assertContains(respuesta, 'no debe pesar más de 5 MB')
        self.assertFalse(Alumno.objects.exists())

    def test_no_hay_alumno_a_medias_si_falla_algo(self):
        self.publicar(tutores=[tutor_nuevo(telefono='1')])
        self.assertFalse(Alumno.objects.exists())
        self.assertFalse(Tutor.objects.exists())


# ---------------------------------------------------------------------------
# Edición
# ---------------------------------------------------------------------------
@PRUEBAS
class EditarTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.alumno = crear_alumno(referencia='3001', correo_electronico='luis@example.com')
        self.madre = crear_tutor(nombre='Rosa', apellido_paterno='Mora', curp=CURP_TUTOR)
        self.padre = crear_tutor(nombre='Jorge', apellido_paterno='Pérez', telefono='3534445566')
        self.v_madre = TutorAlumno.objects.create(tutor=self.madre, alumno=self.alumno, parentesco='MADRE', tutor_principal=True, activo=True)
        self.v_padre = TutorAlumno.objects.create(tutor=self.padre, alumno=self.alumno, parentesco='PADRE', activo=False)
        self.url = reverse('alumnos:editar', args=[self.alumno.pk])

    def vinculos_existentes(self):
        def datos(vinculo, **cambios):
            base = {
                'vinculo_id': vinculo.pk, 'modo': 'existente', 'tutor': vinculo.tutor_id, 'parentesco': vinculo.parentesco,
                **{c: 'on' for c in ('tutor_principal', 'contacto_emergencia', 'autorizado_recoger', 'recibe_notificaciones', 'responsable_pagos', 'activo') if getattr(vinculo, c)},
            }
            base.update(cambios)
            return base
        return datos

    def publicar(self, alumno=None, tutores=None, iniciales=2):
        datos = datos_alumno(referencia='3001', curp=CURP_LUIS, estatus='ACTIVO', nombre='Luis', correo_electronico='luis@example.com')
        datos.pop('contrasena_inicial')
        datos.update(alumno or {})
        datos.update(datos_tutores(*tutores, iniciales=iniciales))
        return self.client.post(self.url, datos)

    def test_formulario_precargado_con_vinculos_incluso_inactivos(self):
        respuesta = self.client.get(self.url)
        html = respuesta.content.decode()
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('value="Luis"', html)
        self.assertIn('name="estatus"', html)
        self.assertNotIn('contrasena_inicial', html)
        self.assertIn('name="tutores-INITIAL_FORMS"', html)
        self.assertEqual(len(respuesta.context['tutores'].forms), 2)
        self.assertContains(respuesta, 'Rosa Mora')
        self.assertContains(respuesta, 'Jorge Pérez')
        self.assertEqual(respuesta.context['paso_inicial'], 0)

    def test_abre_en_el_paso_pedido(self):
        self.assertEqual(self.client.get(self.url + '?paso=tutores').context['paso_inicial'], 3)
        self.assertEqual(self.client.get(self.url + '?paso=xx').context['paso_inicial'], 0)

    def test_actualiza_datos_sin_tocar_la_contrasena(self):
        antes = self.alumno.contrasena
        respuesta = self.publicar(alumno={'domicilio': 'Nueva calle 9', 'estatus': 'SUSPENDIDO'}, tutores=[
            self.vinculos_existentes()(self.v_madre), self.vinculos_existentes()(self.v_padre),
        ])
        self.assertRedirects(respuesta, reverse('alumnos:lista'))
        self.alumno.refresh_from_db()
        self.assertEqual(self.alumno.domicilio, 'Nueva calle 9')
        self.assertEqual(self.alumno.estatus, 'SUSPENDIDO')
        self.assertEqual(self.alumno.contrasena, antes)

    def test_conserva_su_propia_curp_y_referencia(self):
        respuesta = self.publicar(tutores=[self.vinculos_existentes()(self.v_madre), self.vinculos_existentes()(self.v_padre)])
        self.assertEqual(respuesta.status_code, 302)

    def test_no_permite_usar_la_curp_de_otro(self):
        crear_alumno(referencia='3002', curp=CURP_ANA)
        respuesta = self.publicar(alumno={'curp': CURP_ANA}, tutores=[self.vinculos_existentes()(self.v_madre), self.vinculos_existentes()(self.v_padre)])
        self.assertEqual(respuesta.status_code, 200)

    def test_cambia_el_tutor_principal_y_reactiva_un_vinculo(self):
        d = self.vinculos_existentes()
        self.publicar(tutores=[
            d(self.v_madre, tutor_principal=''),
            d(self.v_padre, tutor_principal='on', activo='on', autorizado_recoger='on'),
        ])
        self.v_madre.refresh_from_db()
        self.v_padre.refresh_from_db()
        self.assertFalse(self.v_madre.tutor_principal)
        self.assertTrue(self.v_padre.tutor_principal and self.v_padre.activo and self.v_padre.autorizado_recoger)

    def test_quita_un_vinculo_sin_borrarlo(self):
        d = self.vinculos_existentes()
        self.publicar(tutores=[d(self.v_madre), d(self.v_padre, DELETE='on')])
        self.v_padre.refresh_from_db()           # baja lógica: el registro sigue ahí
        self.assertFalse(self.v_padre.activo)
        self.assertFalse(self.v_padre.tutor_principal)
        self.assertTrue(Tutor.objects.filter(pk=self.padre.pk).exists())

    def test_agrega_un_tutor_nuevo_al_editar(self):
        d = self.vinculos_existentes()
        self.publicar(tutores=[d(self.v_madre), d(self.v_padre), tutor_nuevo(nombre='Lupita', parentesco='ABUELA', telefono='3537778899')])
        self.assertEqual(self.alumno.tutores_relacionados.count(), 3)
        self.assertTrue(Tutor.objects.filter(nombre='Lupita').exists())

    def test_quita_la_fotografia(self):
        self.alumno.fotografia.save('x.png', png(), save=True)
        d = self.vinculos_existentes()
        self.publicar(alumno={'quitar_fotografia': 'on'}, tutores=[d(self.v_madre), d(self.v_padre)])
        self.alumno.refresh_from_db()
        self.assertFalse(self.alumno.fotografia)

    def test_reemplaza_la_fotografia(self):
        d = self.vinculos_existentes()
        self.publicar(alumno={'fotografia': png('nueva.png')}, tutores=[d(self.v_madre), d(self.v_padre)])
        self.alumno.refresh_from_db()
        self.assertIn('nueva', self.alumno.fotografia.name)

    def test_puede_dejar_al_alumno_sin_tutores_al_editar(self):
        d = self.vinculos_existentes()
        self.publicar(tutores=[d(self.v_madre, DELETE='on'), d(self.v_padre, DELETE='on')])
        self.assertEqual(self.alumno.tutores_relacionados.filter(activo=True).count(), 0)
        self.assertEqual(self.alumno.tutores_relacionados.count(), 2)   # el historial se conserva

    def test_sin_permiso_de_cambio_no_edita(self):
        self.client.force_login(self.sin_permisos)
        self.assertEqual(self.client.post(self.url, {}).status_code, 403)


# ---------------------------------------------------------------------------
# Perfil y acciones
# ---------------------------------------------------------------------------
@PRUEBAS
class PerfilTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = CicloEscolar.objects.create(nombre='2026-2027', fecha_inicio=date(2026, 8, 24), fecha_fin=date(2027, 7, 10), activo=True)
        self.grado = Grado.objects.create(nivel='PRIMARIA', numero=4)
        self.alumno = crear_alumno(alergias='Penicilina')
        self.tutor = crear_tutor(nombre='Rosa', apellido_paterno='Mora', telefono='3531112233', correo_electronico='rosa@example.com')
        TutorAlumno.objects.create(tutor=self.tutor, alumno=self.alumno, parentesco='MADRE', tutor_principal=True, contacto_emergencia=True, activo=False)

    def test_detalle(self):
        respuesta = self.client.get(self.alumno.get_absolute_url())
        self.assertEqual(respuesta.status_code, 200)
        for texto in ('Luis Pérez Mora', 'Penicilina', 'Rosa Mora', '353 111 2233', 'rosa@example.com', 'Vínculo inactivo', 'Sin inscripción en el ciclo actual'):
            self.assertContains(respuesta, texto)
        self.assertNotContains(respuesta, 'Credenciales de acceso')

    def test_detalle_con_inscripcion_y_asistencia(self):
        inscripcion = Inscripcion.objects.create(alumno=self.alumno, ciclo=self.ciclo, grado=self.grado)
        for dia, estado in ((1, 'PRESENTE'), (2, 'PRESENTE'), (3, 'RETARDO'), (4, 'FALTA')):
            AsistenciaGeneral.objects.create(inscripcion=inscripcion, fecha=date(2026, 9, dia), estado=estado)
        respuesta = self.client.get(self.alumno.get_absolute_url())
        asistencia = respuesta.context['asistencia']
        self.assertEqual((asistencia['presentes'], asistencia['retardos'], asistencia['faltas']), (2, 1, 1))
        self.assertEqual(asistencia['porcentaje'], 75)
        self.assertContains(respuesta, '4° Primaria')

    def test_cambia_el_estatus(self):
        respuesta = self.client.post(reverse('alumnos:estatus', args=[self.alumno.pk]), {'estatus': 'SUSPENDIDO'})
        self.assertRedirects(respuesta, self.alumno.get_absolute_url())
        self.alumno.refresh_from_db()
        self.assertEqual(self.alumno.estatus, 'SUSPENDIDO')

    def test_la_baja_no_se_hace_desde_el_cambio_de_estatus(self):
        self.client.post(reverse('alumnos:estatus', args=[self.alumno.pk]), {'estatus': 'BAJA'})
        self.alumno.refresh_from_db()
        self.assertEqual(self.alumno.estatus, 'ACTIVO')

    def test_rechaza_un_estatus_invalido(self):
        self.client.post(reverse('alumnos:estatus', args=[self.alumno.pk]), {'estatus': 'XX'})
        self.alumno.refresh_from_db()
        self.assertEqual(self.alumno.estatus, 'ACTIVO')

    def test_restablece_la_contrasena(self):
        antes = self.alumno.contrasena
        respuesta = self.client.post(reverse('alumnos:contrasena', args=[self.alumno.pk]))
        self.alumno.refresh_from_db()
        nueva = self.client.session['credenciales_alumno']['contrasena']
        self.assertNotEqual(self.alumno.contrasena, antes)
        self.assertTrue(check_password(nueva, self.alumno.contrasena))
        self.assertContains(self.client.get(respuesta['Location']), nueva)

    def test_inscribe_a_un_alumno_existente(self):
        respuesta = self.client.post(reverse('alumnos:inscribir', args=[self.alumno.pk]), {
            'ciclo': self.ciclo.pk, 'grado': self.grado.pk, 'fecha_inscripcion': '2026-08-25',
        })
        self.assertRedirects(respuesta, self.alumno.get_absolute_url() + '#academico', fetch_redirect_response=False)
        inscripcion = self.alumno.inscripciones.get()
        self.assertEqual((inscripcion.grado, inscripcion.ciclo, inscripcion.activa), (self.grado, self.ciclo, True))

    def test_no_inscribe_dos_veces_en_el_mismo_ciclo(self):
        Inscripcion.objects.create(alumno=self.alumno, ciclo=self.ciclo, grado=self.grado)
        respuesta = self.client.post(reverse('alumnos:inscribir', args=[self.alumno.pk]), {
            'ciclo': self.ciclo.pk, 'grado': self.grado.pk, 'fecha_inscripcion': '2026-08-25',
        }, follow=True)
        self.assertContains(respuesta, 'ya está inscrito en este ciclo')
        self.assertEqual(self.alumno.inscripciones.count(), 1)

    def test_da_de_baja_sin_borrar_nada(self):
        inscripcion = Inscripcion.objects.create(alumno=self.alumno, ciclo=self.ciclo, grado=self.grado)
        respuesta = self.client.post(reverse('alumnos:baja', args=[self.alumno.pk]), follow=True)
        self.assertRedirects(respuesta, reverse('alumnos:lista'))
        self.assertContains(respuesta, 'dado de baja')
        self.assertContains(respuesta, 'Luis Pérez Mora')   # el mensaje nombra al alumno
        self.alumno.refresh_from_db()
        self.assertEqual(self.alumno.estatus, 'BAJA')
        self.assertTrue(Inscripcion.objects.filter(pk=inscripcion.pk).exists())
        self.assertTrue(TutorAlumno.objects.filter(alumno=self.alumno).exists())
        self.assertTrue(Tutor.objects.filter(pk=self.tutor.pk).exists())

    def test_el_alumno_de_baja_sale_del_listado_pero_conserva_su_perfil(self):
        self.client.post(reverse('alumnos:baja', args=[self.alumno.pk]))
        self.assertEqual(self.client.get(reverse('alumnos:lista')).context['total_alumnos'], 0)
        self.assertEqual(len(self.client.get(reverse('alumnos:lista'), {'estatus': 'BAJA'}).context['pagina']), 1)
        perfil = self.client.get(self.alumno.get_absolute_url())
        self.assertEqual(perfil.status_code, 200)
        self.assertTrue(perfil.context['esta_de_baja'])
        self.assertContains(perfil, 'Reactivar')

    def test_reactivar_devuelve_al_alumno_al_listado(self):
        self.alumno.estatus = 'BAJA'
        self.alumno.save()
        respuesta = self.client.post(reverse('alumnos:reactivar', args=[self.alumno.pk]), follow=True)
        self.assertRedirects(respuesta, reverse('alumnos:lista'))
        self.assertContains(respuesta, 'reactivado')
        self.alumno.refresh_from_db()
        self.assertEqual(self.alumno.estatus, 'ACTIVO')

    def test_reactivar_a_quien_no_esta_de_baja_no_cambia_nada(self):
        self.alumno.estatus = 'SUSPENDIDO'
        self.alumno.save()
        self.client.post(reverse('alumnos:reactivar', args=[self.alumno.pk]))
        self.alumno.refresh_from_db()
        self.assertEqual(self.alumno.estatus, 'SUSPENDIDO')

    def test_dar_de_baja_dos_veces_es_inofensivo(self):
        self.client.post(reverse('alumnos:baja', args=[self.alumno.pk]))
        respuesta = self.client.post(reverse('alumnos:baja', args=[self.alumno.pk]))
        self.assertEqual(respuesta.status_code, 302)
        self.alumno.refresh_from_db()
        self.assertEqual(self.alumno.estatus, 'BAJA')

    def test_alumno_inexistente_da_404(self):
        self.assertEqual(self.client.post(reverse('alumnos:baja', args=[9999])).status_code, 404)

    def test_muestra_al_tutor_dado_de_baja(self):
        self.tutor.estatus = 'INACTIVO'
        self.tutor.save()
        vinculo = TutorAlumno.objects.get()
        vinculo.activo = True
        vinculo.save()
        self.assertContains(self.client.get(self.alumno.get_absolute_url()), 'Tutor dado de baja')


# ---------------------------------------------------------------------------
# Exportación y búsqueda de tutores
# ---------------------------------------------------------------------------
@PRUEBAS
class ExportarYBuscarTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ana = crear_alumno(referencia='1', nombre='=Ana', apellido_paterno='Zamora', curp=CURP_ANA)
        self.luis = crear_alumno(referencia='2', nombre='Luis', apellido_paterno='Aranda', curp=CURP_LUIS, estatus='BAJA')
        self.rosa = crear_tutor(nombre='Rosa', apellido_paterno='Quintero', telefono='3531112233')
        TutorAlumno.objects.create(tutor=self.rosa, alumno=self.ana, parentesco='MADRE', tutor_principal=True)

    def test_exporta_csv_respetando_filtros(self):
        respuesta = self.client.get(reverse('alumnos:exportar'), {'estatus': 'ACTIVO'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('text/csv', respuesta['Content-Type'])
        self.assertIn('attachment; filename="alumnos-', respuesta['Content-Disposition'])
        contenido = respuesta.content.decode('utf-8')
        self.assertTrue(contenido.startswith('﻿'))
        filas = list(csv.reader(io.StringIO(contenido.lstrip('﻿'))))
        self.assertEqual(filas[0][:3], ['Referencia', 'Nombre', 'Apellido paterno'])
        self.assertEqual(len(filas), 2)
        self.assertEqual(filas[1][1], "'=Ana")               # neutraliza fórmulas de Excel
        self.assertIn('Rosa Quintero', filas[1])
        self.assertIn('3531112233', filas[1])

    def buscar(self, q, **extra):
        return self.client.get(reverse('alumnos:tutor_buscar'), {'q': q, **extra})

    def test_busca_tutores(self):
        respuesta = self.buscar('quin')
        self.assertEqual(respuesta['Content-Type'], 'application/json')
        resultado = respuesta.json()['resultados']
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0]['nombre'], 'Rosa Quintero')
        self.assertEqual(resultado[0]['iniciales'], 'RQ')
        self.assertEqual(resultado[0]['telefono'], '3531112233')
        self.assertEqual(resultado[0]['alumnos'], ['=Ana Zamora Mora'])

    def test_busca_por_telefono_y_varias_palabras(self):
        self.assertEqual(len(self.buscar('353111').json()['resultados']), 1)
        self.assertEqual(len(self.buscar('rosa quintero').json()['resultados']), 1)
        self.assertEqual(self.buscar('rosa pérez').json()['resultados'], [])

    def test_no_ofrece_tutores_dados_de_baja(self):
        self.rosa.estatus = 'INACTIVO'
        self.rosa.save()
        self.assertEqual(self.buscar('quin').json()['resultados'], [])

    def test_los_alumnos_del_tutor_son_solo_los_vigentes(self):
        otra = crear_alumno(referencia='3', nombre='Eva', apellido_paterno='Beltrán', curp='RASL020408HMNMNSA8')
        TutorAlumno.objects.create(tutor=self.rosa, alumno=self.luis, parentesco='MADRE')                  # alumno de baja
        TutorAlumno.objects.create(tutor=self.rosa, alumno=otra, parentesco='MADRE', activo=False)         # vínculo inactivo
        self.assertEqual(self.buscar('quin').json()['resultados'][0]['alumnos'], ['=Ana Zamora Mora'])

    def test_busca_alumnos_sin_incluir_bajas(self):
        url = reverse('alumnos:buscar')
        resultado = self.client.get(url, {'q': 'zamora'}).json()['resultados']
        self.assertEqual([r['nombre'] for r in resultado], ['=Ana Zamora Mora'])
        self.assertEqual(self.client.get(url, {'q': 'aranda'}).json()['resultados'], [])   # está de baja
        self.assertEqual(self.client.get(url, {'q': 'z'}).json()['resultados'], [])        # mínimo dos letras

    def test_exige_al_menos_dos_caracteres(self):
        self.assertEqual(self.buscar('r').json()['resultados'], [])
        self.assertEqual(self.buscar('').json()['resultados'], [])

    def test_limita_los_resultados(self):
        for i in range(12):
            crear_tutor(nombre=f'Tutor{i}', apellido_paterno='Repetido')
        self.assertEqual(len(self.buscar('repetido').json()['resultados']), 8)
