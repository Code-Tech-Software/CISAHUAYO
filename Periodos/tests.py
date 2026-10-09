"""Periodos de evaluación: los de cada nivel en tarjetas, su alta y edición, abrirlos o cerrarlos a mano, volver a sus
fechas y eliminarlos; y la regla que usará la captura de calificaciones (`periodos_abiertos`)."""
import importlib
import re
from datetime import timedelta

from django.apps import apps
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Group, Permission
from django.urls import reverse
from django.utils import timezone

from Alumnos.models import Periodo
from Alumnos.periodos import describir, periodo_abierto, periodos_abiertos
from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase, ciclo_actual_de_prueba, ciclo_cerrado_de_prueba, crear_rol
from Usuarios.models import Rol

HOY = timezone.localdate


def dias(n):
    return HOY() + timedelta(days=n)


def crear_periodo(ciclo, nivel='PRIMARIA', nombre='Primer bimestre', desde=-10, hasta=10, **cambios):
    return Periodo.objects.create(ciclo=ciclo, nivel=nivel, nombre=nombre, fecha_inicio=dias(desde), fecha_fin=dias(hasta), **cambios)


# ---------------------------------------------------------------------------
# Cuándo está abierto
# ---------------------------------------------------------------------------
@PRUEBAS
class EstadoTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()

    def test_por_sus_fechas(self):
        periodo = crear_periodo(self.ciclo, desde=0, hasta=5)
        self.assertEqual(periodo.estado_en(dias(-1)), Periodo.PROXIMO)
        self.assertEqual(periodo.estado_en(dias(0)), Periodo.ABIERTO)        # se abre el día de inicio
        self.assertEqual(periodo.estado_en(dias(5)), Periodo.ABIERTO)        # y sigue abierto todo el día de cierre
        self.assertEqual(periodo.estado_en(dias(6)), Periodo.CERRADO)

    def test_a_mano_no_importan_las_fechas(self):
        abierto = crear_periodo(self.ciclo, desde=-30, hasta=-20, apertura=Periodo.ABIERTO)
        cerrado = crear_periodo(self.ciclo, nombre='Segundo bimestre', desde=-5, hasta=5, apertura=Periodo.CERRADO)
        self.assertTrue(abierto.esta_abierto)
        self.assertFalse(cerrado.esta_abierto)
        self.assertEqual(cerrado.estado, Periodo.CERRADO)

    def test_periodos_abiertos_de_un_nivel(self):
        hoy = crear_periodo(self.ciclo, desde=-1, hasta=1)
        crear_periodo(self.ciclo, nombre='Futuro', desde=5, hasta=9)
        crear_periodo(self.ciclo, nombre='Cerrado a mano', desde=-20, hasta=-15, apertura=Periodo.CERRADO)
        reabierto = crear_periodo(self.ciclo, nombre='Reabierto', desde=-40, hasta=-30, apertura=Periodo.ABIERTO)
        crear_periodo(self.ciclo, nivel='SECUNDARIA', nombre='Otro nivel', desde=-1, hasta=1)
        self.assertEqual(list(periodos_abiertos('PRIMARIA')), [reabierto, hoy])
        self.assertEqual(periodo_abierto('PRIMARIA'), reabierto)
        self.assertIsNone(periodo_abierto('PREESCOLAR'))
        self.assertEqual(list(periodos_abiertos('PRIMARIA', fecha=dias(6))), [reabierto, Periodo.objects.get(nombre='Futuro')])

    def test_explica_su_estado(self):
        self.assertEqual(describir(crear_periodo(self.ciclo, nombre='A', desde=-1, hasta=5)), 'Se cierra en 5 días.')
        self.assertEqual(describir(crear_periodo(self.ciclo, nombre='B', desde=-1, hasta=1)), 'Se cierra mañana.')
        self.assertEqual(describir(crear_periodo(self.ciclo, nombre='C', desde=1, hasta=5)), 'Se abre mañana.')
        self.assertEqual(describir(crear_periodo(self.ciclo, nombre='D', desde=-3, hasta=0)), 'Se cierra al terminar el día de hoy.')
        self.assertTrue(describir(crear_periodo(self.ciclo, nombre='E', desde=-9, hasta=-5)).startswith('Se cerró el '))
        self.assertEqual(describir(crear_periodo(self.ciclo, nombre='F', apertura=Periodo.CERRADO)), 'No se puede capturar hasta que lo abras.')
        self.assertEqual(describir(crear_periodo(self.ciclo, nombre='G', apertura=Periodo.ABIERTO)), 'Se puede capturar hasta que lo cierres.')


# ---------------------------------------------------------------------------
# Tarjetas por nivel
# ---------------------------------------------------------------------------
@PRUEBAS
class ListaTests(BaseTestCase):
    url = '/periodos/'

    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.primero = crear_periodo(self.ciclo, nombre='Primer bimestre', desde=-20, hasta=-1)
        self.segundo = crear_periodo(self.ciclo, nombre='Segundo bimestre', desde=0, hasta=30)
        self.parcial = crear_periodo(self.ciclo, nivel='SECUNDARIA', nombre='Primer parcial', desde=5, hasta=40)

    def test_los_cuatro_niveles_en_orden_con_sus_periodos_numerados(self):
        respuesta = self.client.get(self.url)
        niveles = respuesta.context['niveles']
        self.assertEqual([n['nombre'] for n in niveles], ['Preescolar', 'Primaria', 'Secundaria', 'Preparatoria'])
        self.assertEqual([(p.numero, p.nombre) for p in niveles[1]['periodos']], [(1, 'Primer bimestre'), (2, 'Segundo bimestre')])
        self.assertEqual(niveles[1]['abiertos'], [self.segundo])
        self.assertEqual(niveles[0]['periodos'], [])
        html = respuesta.content.decode()
        self.assertIn('Preescolar todavía no tiene periodos', html)
        self.assertIn('periodo-card--abierto', html)
        self.assertIn('periodo-card--cerrado', html)
        self.assertIn('periodo-card--proximo', html)

    def test_dice_en_que_se_puede_capturar_hoy(self):
        self.assertContains(self.client.get(self.url), 'Hoy se puede capturar en:</strong>\n            Primaria · Segundo bimestre.')
        Periodo.objects.filter(pk=self.segundo.pk).update(apertura=Periodo.CERRADO)
        self.assertContains(self.client.get(self.url), 'Hoy no hay ningún periodo abierto')

    def test_acciones_de_cada_tarjeta(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn(reverse('periodos:cerrar', args=[self.segundo.pk]), html)       # abierto: se puede cerrar
        self.assertIn(reverse('periodos:abrir', args=[self.primero.pk]), html)        # cerrado: se puede abrir
        self.assertNotIn(reverse('periodos:por_fechas', args=[self.primero.pk]), html)   # sigue sus fechas
        self.assertIn(f'href="{reverse("periodos:editar", args=[self.primero.pk])}" data-modal-form', html)
        self.assertIn(f'{reverse("periodos:crear")}?ciclo={self.ciclo.pk}&amp;nivel=PREPARATORIA', html)

    def test_otro_ciclo(self):
        cerrado = ciclo_cerrado_de_prueba()
        viejo = crear_periodo(cerrado, nombre='Viejo', desde=-300, hasta=-280)
        respuesta = self.client.get(self.url, {'ciclo': cerrado.pk})
        self.assertEqual(respuesta.context['niveles'][1]['periodos'], [viejo])
        self.assertFalse(respuesta.context['editable'])
        self.assertContains(respuesta, 'está cerrado')
        self.assertNotContains(respuesta, 'aria-controls="menu-periodo')
        self.assertNotContains(respuesta, f'href="{reverse("periodos:crear")}?ciclo=')

    def test_quien_solo_consulta_no_ve_acciones(self):
        self.con_permisos('view_periodo')
        html = self.client.get(self.url).content.decode()
        self.assertNotIn('menu-periodo-', html)
        self.assertNotIn(reverse('periodos:crear'), html)

    def test_sin_ciclos(self):
        Periodo.objects.all().delete()
        self.ciclo.delete()
        self.assertContains(self.client.get(self.url), 'Aún no hay ciclos escolares')

    def test_en_el_menu(self):
        html = self.client.get(self.url).content.decode()
        self.assertRegex(html, r'href="/periodos/"[^>]*aria-current="page"|aria-current="page"[^>]*href="/periodos/"')


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
@PRUEBAS
class AltaTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.url = f"{reverse('periodos:crear')}?ciclo={self.ciclo.pk}"

    def datos(self, **cambios):
        datos = {'nivel': 'PRIMARIA', 'nombre': 'Primer bimestre', 'fecha_inicio': dias(0).isoformat(), 'fecha_fin': dias(30).isoformat()}
        datos.update(cambios)
        return datos

    def test_agrega_un_periodo_al_nivel(self):
        respuesta = self.client.post(self.url, self.datos(nombre='  Primer   bimestre '), follow=True)
        self.assertRedirects(respuesta, f"{reverse('periodos:lista')}?ciclo={self.ciclo.pk}")
        periodo = Periodo.objects.get()
        self.assertEqual((periodo.ciclo, periodo.nivel, periodo.nombre, periodo.apertura), (self.ciclo, 'PRIMARIA', 'Primer bimestre', Periodo.POR_FECHAS))
        self.assertContains(respuesta, 'Se agregó «Primer bimestre» a Primaria')
        self.assertContains(respuesta, 'Se cierra en 30 días.')
        self.assertRegex(respuesta.content.decode(), r'Primaria: del \d+ de [a-z]+ al \d+ de [a-z]+ de \d{4}\.')   # meses en minúscula
        self.assertTrue(LogEntry.objects.filter(object_id=str(periodo.pk), change_message__contains='Periodo de Primaria').exists())

    def test_el_formulario_pide_nivel_nombre_y_fechas(self):
        html = self.client.get(self.url).content.decode()
        self.assertEqual(re.findall(r'<input[^>]*type="radio"[^>]*name="nivel"[^>]*value="([A-Z]+)"', html), ['PREESCOLAR', 'PRIMARIA', 'SECUNDARIA', 'PREPARATORIA'])
        self.assertIn('name="nombre"', html)
        self.assertIn('type="date" name="fecha_inicio"', html)
        self.assertIn('type="date" name="fecha_fin"', html)
        respuesta = self.client.post(self.url, {})
        self.assertEqual(set(respuesta.context['form'].errors), {'nivel', 'nombre', 'fecha_inicio', 'fecha_fin'})

    def test_desde_un_nivel_lo_trae_elegido_y_propone_empezar_tras_su_ultimo_periodo(self):
        crear_periodo(self.ciclo, desde=0, hasta=30)
        form = self.client.get(f'{self.url}&nivel=PRIMARIA').context['form']
        self.assertEqual(form['nivel'].value(), 'PRIMARIA')
        self.assertEqual(form['fecha_inicio'].value(), dias(31))
        form = self.client.get(f'{self.url}&nivel=SECUNDARIA').context['form']
        self.assertEqual(form['fecha_inicio'].value(), self.ciclo.fecha_inicio)   # el primero del nivel: al iniciar el ciclo

    def test_la_fecha_de_cierre_no_puede_ser_anterior(self):
        respuesta = self.client.post(self.url, self.datos(fecha_fin=dias(-1).isoformat()))
        self.assertContains(respuesta, 'La fecha de cierre no puede ser anterior a la de inicio.')
        self.assertEqual(self.client.post(self.url, self.datos(fecha_fin=dias(0).isoformat())).status_code, 302)   # un solo día, sí

    def test_las_fechas_quedan_dentro_del_ciclo(self):
        respuesta = self.client.post(self.url, self.datos(fecha_fin=(self.ciclo.fecha_fin + timedelta(days=1)).isoformat()))
        self.assertContains(respuesta, f'Las fechas deben quedar dentro del ciclo {self.ciclo}')
        self.assertFalse(Periodo.objects.exists())

    def test_no_se_empalma_con_otro_del_mismo_nivel(self):
        crear_periodo(self.ciclo, nombre='Primer bimestre', desde=0, hasta=30)
        respuesta = self.client.post(self.url, self.datos(nombre='Segundo bimestre', fecha_inicio=dias(30).isoformat(), fecha_fin=dias(60).isoformat()))
        self.assertContains(respuesta, 'Se empalma con «Primer bimestre»')
        respuesta = self.client.post(self.url, self.datos(nivel='SECUNDARIA'))          # otro nivel: sí
        self.assertEqual(respuesta.status_code, 302)

    def test_el_nombre_no_se_repite_en_el_nivel(self):
        crear_periodo(self.ciclo, nombre='Primer bimestre', desde=40, hasta=50)
        respuesta = self.client.post(self.url, self.datos(nombre='primer BIMESTRE'))
        self.assertContains(respuesta, 'Primaria ya tiene un periodo con ese nombre')
        self.assertEqual(self.client.post(self.url, self.datos(nivel='PREESCOLAR')).status_code, 302)

    def test_en_un_ciclo_cerrado_no_se_agregan(self):
        cerrado = ciclo_cerrado_de_prueba()
        respuesta = self.client.post(f"{reverse('periodos:crear')}?ciclo={cerrado.pk}", self.datos(), follow=True)
        self.assertContains(respuesta, 'está cerrado')
        self.assertFalse(Periodo.objects.exists())


@PRUEBAS
class EdicionTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.periodo = crear_periodo(self.ciclo, desde=0, hasta=30)
        self.url = reverse('periodos:editar', args=[self.periodo.pk])

    def test_cambia_sus_datos_sin_chocar_consigo_mismo(self):
        respuesta = self.client.post(self.url, {
            'nivel': 'PRIMARIA', 'nombre': 'Primer bimestre', 'fecha_inicio': dias(0).isoformat(), 'fecha_fin': dias(20).isoformat(),
        }, follow=True)
        self.periodo.refresh_from_db()
        self.assertEqual(self.periodo.fecha_fin, dias(20))
        self.assertContains(respuesta, 'Se actualizó «Primer bimestre» de Primaria.')

    def test_muestra_su_estado(self):
        self.assertContains(self.client.get(self.url), 'Ahora está abierto.')
        Periodo.objects.filter(pk=self.periodo.pk).update(apertura=Periodo.CERRADO)
        self.assertContains(self.client.get(self.url), 'Ahora está cerrado a mano.')


# ---------------------------------------------------------------------------
# Abrir, cerrar, volver a sus fechas y eliminar
# ---------------------------------------------------------------------------
@PRUEBAS
class AperturaTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.periodo = crear_periodo(self.ciclo, desde=-30, hasta=-1)   # por sus fechas ya se cerró

    def post(self, accion):
        return self.client.post(reverse(f'periodos:{accion}', args=[self.periodo.pk]), follow=True)

    def test_abrir_a_mano_un_periodo_ya_cerrado_por_sus_fechas(self):
        respuesta = self.post('abrir')
        self.periodo.refresh_from_db()
        self.assertEqual(self.periodo.apertura, Periodo.ABIERTO)
        self.assertTrue(self.periodo.esta_abierto)
        self.assertContains(respuesta, 'quedó abierto: los profesores de Primaria pueden capturar hasta que lo cierres.')
        self.assertTrue(LogEntry.objects.filter(object_id=str(self.periodo.pk), change_message='Apertura: abierto a mano.').exists())

    def test_cerrar_y_volver_a_sus_fechas(self):
        self.post('cerrar')
        self.periodo.refresh_from_db()
        self.assertEqual(self.periodo.apertura, Periodo.CERRADO)
        respuesta = self.post('por_fechas')
        self.periodo.refresh_from_db()
        self.assertEqual(self.periodo.apertura, Periodo.POR_FECHAS)
        self.assertContains(respuesta, 'vuelve a seguir sus fechas')
        self.assertContains(respuesta, 'hoy está cerrado.')

    def test_solo_por_post_y_con_permiso_de_editar(self):
        self.assertEqual(self.client.get(reverse('periodos:abrir', args=[self.periodo.pk])).status_code, 405)
        self.con_permisos('view_periodo')
        self.assertEqual(self.client.post(reverse('periodos:abrir', args=[self.periodo.pk])).status_code, 403)

    def test_eliminar(self):
        respuesta = self.post('eliminar')
        self.assertFalse(Periodo.objects.exists())
        self.assertContains(respuesta, 'Se eliminó «Primer bimestre» de Primaria.')

    def test_en_un_ciclo_cerrado_no_se_tocan(self):
        viejo = crear_periodo(ciclo_cerrado_de_prueba(), nombre='Viejo', desde=-300, hasta=-280)
        for accion in ('abrir', 'cerrar', 'eliminar'):
            self.client.post(reverse(f'periodos:{accion}', args=[viejo.pk]))
        viejo.refresh_from_db()
        self.assertEqual(viejo.apertura, Periodo.POR_FECHAS)


# ---------------------------------------------------------------------------
# Permisos de los roles
# ---------------------------------------------------------------------------
@PRUEBAS
class PermisosDeRolesTests(BaseTestCase):
    def test_los_roles_de_arranque(self):
        def permisos(nombre):
            return set(Rol.objects.get(grupo__name=nombre).grupo.permissions.filter(content_type__model='periodo').values_list('codename', flat=True))
        self.assertEqual(permisos('Dirección'), {'view_periodo', 'add_periodo', 'change_periodo', 'delete_periodo'})
        self.assertEqual(permisos('Control escolar'), {'view_periodo'})
        self.assertEqual(permisos('Docente'), {'view_periodo'})

    def test_la_migracion_se_los_da_a_los_roles_que_ya_existian(self):
        migracion = importlib.import_module('Usuarios.migrations.0005_permisos_de_periodos')
        consulta = crear_rol('Consulta de ciclos', {'Alumnos.view_cicloescolar'}).grupo
        administra = crear_rol('Coordinación', {'Alumnos.view_cicloescolar', 'Alumnos.change_cicloescolar'}).grupo
        ajeno = crear_rol('Solo estudiantes', {'Alumnos.view_alumno'}).grupo
        for grupo in (consulta, administra):
            grupo.permissions.remove(*Permission.objects.filter(codename__endswith='_periodo'))
        migracion.conceder_periodos(apps, None)

        def de(grupo):
            return set(Group.objects.get(pk=grupo.pk).permissions.filter(codename__endswith='_periodo').values_list('codename', flat=True))
        self.assertEqual(de(consulta), {'view_periodo'})
        self.assertEqual(de(administra), {'view_periodo', 'add_periodo', 'change_periodo', 'delete_periodo'})
        self.assertEqual(de(ajeno), set())
