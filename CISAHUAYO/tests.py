import sys
import types

from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.shortcuts import render
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import include, path

from CISAHUAYO.context_processors import navegacion

# Los tests se ejecutan con DEBUG=False; el almacenamiento con manifiesto de
# WhiteNoise exigiría haber corrido collectstatic.
STORAGES_DE_PRUEBA = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


def inicio(request):
    return render(request, 'index.html')


def con_mensajes(request):
    messages.success(request, 'Guardado correctamente.')
    messages.error(request, 'No se pudo guardar.')
    return render(request, 'index.html')


sub_urlpatterns = ([
    path('', inicio, name='lista'),
    path('nuevo/', inicio, name='crear'),
], 'alumnos')

# Anidada bajo /alumnos/ a propósito: comprueba que el menú activa la coincidencia más específica.
inscripciones_urlpatterns = ([
    path('', inicio, name='lista'),
], 'inscripciones')

# Rutas mínimas: 'tutores:lista', 'buscar' y el resto del menú no existen a propósito.
urlpatterns = [
    path('', inicio, name='inicio'),
    path('mensajes/', con_mensajes, name='mensajes'),
    path('alumnos/inscripciones/', include(inscripciones_urlpatterns)),
    path('alumnos/', include(sub_urlpatterns)),
    path('admin/', admin.site.urls),
]

# Módulo de URLs auxiliar: igual que este, pero con la búsqueda global disponible.
URLCONF_CON_BUSQUEDA = f'{__name__}_con_busqueda'
_modulo_con_busqueda = types.ModuleType(URLCONF_CON_BUSQUEDA)
_modulo_con_busqueda.urlpatterns = urlpatterns + [path('buscar/', inicio, name='buscar')]
sys.modules[URLCONF_CON_BUSQUEDA] = _modulo_con_busqueda


def contexto(request):
    return navegacion(request)


def elementos(request):
    """Aplana el menú en {etiqueta: elemento}."""
    return {
        el['etiqueta']: el
        for seccion in contexto(request)['navegacion']
        for el in seccion['elementos']
    }


@override_settings(ROOT_URLCONF=__name__)
class NavegacionTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_rutas_inexistentes_apuntan_a_almohadilla_y_no_estan_disponibles(self):
        items = elementos(self.factory.get('/'))
        self.assertEqual(items['Tutores']['url'], '#')
        self.assertFalse(items['Tutores']['disponible'])
        self.assertEqual(items['Estudiantes']['url'], '/alumnos/')
        self.assertTrue(items['Estudiantes']['disponible'])

    def test_panel_de_control_solo_es_activo_en_la_raiz(self):
        self.assertTrue(elementos(self.factory.get('/'))['Panel de control']['activo'])
        self.assertFalse(elementos(self.factory.get('/alumnos/'))['Panel de control']['activo'])

    def test_se_activa_la_coincidencia_mas_especifica(self):
        items = elementos(self.factory.get('/alumnos/inscripciones/'))
        self.assertTrue(items['Inscripciones']['activo'])
        self.assertFalse(items['Estudiantes']['activo'])

    def test_prefijo_de_ruta_mantiene_activo_el_elemento(self):
        items = elementos(self.factory.get('/alumnos/7/editar/'))
        self.assertTrue(items['Estudiantes']['activo'])

    def test_los_elementos_sin_ruta_nunca_se_activan(self):
        items = elementos(self.factory.get('/alumnos/'))
        self.assertFalse(items['Tutores']['activo'])

    def test_solo_aparecen_las_acciones_rapidas_con_ruta(self):
        acciones = contexto(self.factory.get('/'))['acciones_rapidas']
        self.assertEqual([a['etiqueta'] for a in acciones], ['Nuevo estudiante'])
        self.assertEqual(acciones[0]['url'], '/alumnos/nuevo/')

    def test_sin_ruta_de_busqueda_no_hay_url(self):
        self.assertEqual(contexto(self.factory.get('/'))['busqueda_url'], '')

    @override_settings(ROOT_URLCONF=URLCONF_CON_BUSQUEDA)
    def test_con_ruta_de_busqueda_se_expone_la_url(self):
        self.assertEqual(contexto(self.factory.get('/'))['busqueda_url'], '/buscar/')


@override_settings(ROOT_URLCONF=__name__, STORAGES=STORAGES_DE_PRUEBA)
class PlantillaBaseTests(TestCase):
    def entrar_con_acceso_total(self):
        """El menú solo muestra lo que el rol permite: para ver todo se entra con una cuenta de acceso total."""
        self.client.force_login(get_user_model().objects.create_superuser('jefa', 'jefa@example.com', 'x'))

    def test_estructura_basica(self):
        self.entrar_con_acceso_total()
        html = self.client.get('/').content.decode()
        for fragmento in (
            'class="sidebar"',
            'class="topbar"',
            'aria-label="Navegación principal"',
            'aria-label="Ruta de navegación"',
            'Gestión escolar',
            'Académico',
            'Ciclos escolares',
            'img/logointer.svg',
            'css/app.css',
            'js/app.js',
            'js/preload.js',
        ):
            self.assertIn(fragmento, html)

    def test_buscador_de_comandos(self):
        self.entrar_con_acceso_total()
        html = self.client.get('/').content.decode()
        self.assertIn('<dialog class="palette"', html)
        self.assertIn('data-palette-open', html)
        self.assertIn('aria-keyshortcuts="Control+K Meta+K"', html)
        # Solo las páginas con ruta real, las acciones disponibles y las preferencias
        self.assertIn('Panel de control', html)
        self.assertIn('Nuevo estudiante', html)
        self.assertIn('data-palette-action="toggle-theme"', html)
        self.assertNotIn('data-palette-search', html)

    def test_buscador_ofrece_busqueda_global_si_existe_la_ruta(self):
        self.entrar_con_acceso_total()
        with override_settings(ROOT_URLCONF=URLCONF_CON_BUSQUEDA):
            html = self.client.get('/').content.decode()
        self.assertIn('data-palette-search', html)
        self.assertIn('href="/buscar/"', html)

    def test_interruptor_de_tema(self):
        html = self.client.get('/').content.decode()
        self.assertIn('data-theme-toggle', html)
        self.assertIn('aria-pressed="false"', html)

    def test_anonimo_ve_acceso_al_login(self):
        html = self.client.get('/').content.decode()
        self.assertIn('Iniciar sesión', html)
        self.assertNotIn('Cerrar sesión', html)

    def test_usuario_autenticado_ve_su_menu_y_saludo(self):
        usuario = get_user_model().objects.create_user(
            'laura', email='laura@example.com', first_name='Laura', last_name='Méndez',
        )
        self.client.force_login(usuario)
        html = self.client.get('/').content.decode()
        self.assertIn('Laura Méndez', html)
        self.assertIn('laura@example.com', html)
        self.assertIn('Cerrar sesión', html)
        self.assertIn('csrfmiddlewaretoken', html)
        self.assertNotIn('Iniciar sesión', html)
        self.assertRegex(html, r'(Buenos días|Buenas tardes|Buenas noches), Laura')

    def test_solo_el_personal_ve_el_enlace_de_administracion(self):
        usuario = get_user_model().objects.create_user('pablo')
        self.client.force_login(usuario)
        self.assertNotIn('Administración de Django', self.client.get('/').content.decode())

    def test_mensajes_de_django_como_avisos_flotantes(self):
        html = self.client.get('/mensajes/').content.decode()
        self.assertIn('toast toast--success', html)
        self.assertIn('Guardado correctamente.', html)
        self.assertIn('toast toast--error', html)
        self.assertIn('role="alert"', html)
        self.assertIn('role="status"', html)

    def test_solo_los_avisos_informativos_se_cierran_solos(self):
        html = self.client.get('/mensajes/').content.decode()
        self.assertEqual(html.count('data-toast-progress'), 1)  # éxito sí, error no

    def test_sin_mensajes_no_hay_contenedor(self):
        self.assertNotIn('class="toasts"', self.client.get('/').content.decode())
