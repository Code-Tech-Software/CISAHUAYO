"""Ninguna ruta del sistema se puede abrir tecleando su URL sin autorización.

Recorre TODAS las rutas del proyecto (se descubren solas, así una ruta nueva queda cubierta sin tocar esta prueba) y
comprueba que:
- sin sesión, nada responde con datos: se manda a iniciar sesión (o 401 en las que responden JSON);
- con sesión pero sin permisos, todo responde 403;
- cada permiso que una vista exige existe en el catálogo, de modo que un rol puede concederlo;
- las únicas rutas sin permiso propio son las de la lista de excepciones, y están justificadas.
"""
from django.test import Client
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase
from Usuarios import catalogo

# Rutas que cualquiera con sesión puede abrir (o que sirven para iniciar o cerrar sesión), y por qué
SOLO_CON_SESION = {
    'inicio': 'el panel de control: cada quien ve solo los accesos a lo que su rol permite',
    'cuenta:perfil': 'cada persona edita sus propios datos',
    'cuenta:contrasena': 'cada persona cambia su propia contraseña',
}
SIN_SESION = {
    'login': 'iniciar sesión',
    'logout': 'cerrar sesión',
}
# Responden JSON con su propia comprobación de sesión y permiso (la pantalla de entrada no puede redirigir al login)
CON_COMPROBACION_PROPIA = {
    'asistencias:registrar_entrada': 'Alumnos.add_asistenciageneral',
    'asistencias:kiosco_estado': 'Alumnos.add_asistenciageneral',
}
OMITIDAS_POR_PREFIJO = ('media/',)   # los archivos subidos (solo en desarrollo)


def rutas():
    """(nombre con espacio de nombres, patrón, vista, argumentos de ejemplo) de cada ruta del proyecto."""
    def recorrer(patrones, espacio='', prefijo=''):
        for patron in patrones:
            if isinstance(patron, URLResolver):
                nuevo_espacio = f'{espacio}{patron.namespace}:' if patron.namespace else espacio
                yield from recorrer(patron.url_patterns, nuevo_espacio, prefijo + str(patron.pattern))
            elif isinstance(patron, URLPattern):
                ruta = prefijo + str(patron.pattern)
                # El sitio de administración de Django tiene su propio control de acceso (is_staff y permisos de modelo)
                if patron.name and not espacio.startswith('admin:') and not ruta.startswith(OMITIDAS_POR_PREFIJO):
                    convertidores = getattr(patron.pattern, 'converters', {})
                    argumentos = {nombre: 1 for nombre in convertidores}
                    yield f'{espacio}{patron.name}', ruta, patron.callback, argumentos

    return list(recorrer(get_resolver().url_patterns))


@PRUEBAS
class NingunaRutaSeAbreSinAutorizacionTests(BaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.rutas = rutas()

    def peticion(self, cliente, nombre, argumentos, ruta):
        url = reverse(nombre, kwargs=argumentos)
        respuesta = cliente.get(url)
        if respuesta.status_code == 405:   # solo acepta POST
            respuesta = cliente.post(url)
        return url, respuesta

    def test_se_descubren_todas_las_rutas_del_proyecto(self):
        nombres = {r[0] for r in self.rutas}
        self.assertGreater(len(nombres), 80)
        for esperado in ('alumnos:lista', 'tutores:crear', 'asistencias:kiosco', 'usuarios:lista', 'roles:editar', 'cuenta:perfil'):
            self.assertIn(esperado, nombres)

    def test_sin_sesion_nada_responde_con_datos(self):
        anonimo = Client()
        for nombre, ruta, _, argumentos in self.rutas:
            if nombre in SIN_SESION:
                continue
            with self.subTest(ruta=ruta, nombre=nombre):
                _, respuesta = self.peticion(anonimo, nombre, argumentos, ruta)
                if nombre in CON_COMPROBACION_PROPIA:
                    self.assertEqual(respuesta.status_code, 401)
                else:
                    self.assertEqual(respuesta.status_code, 302, f'{ruta} respondió {respuesta.status_code} a alguien sin sesión')
                    self.assertIn('/admin/login/', respuesta['Location'])

    def test_con_sesion_pero_sin_permisos_todo_responde_403(self):
        cuenta = Client()
        cuenta.force_login(self.sin_permisos)
        for nombre, ruta, _, argumentos in self.rutas:
            if nombre in SIN_SESION or nombre in SOLO_CON_SESION:
                continue
            with self.subTest(ruta=ruta, nombre=nombre):
                _, respuesta = self.peticion(cuenta, nombre, argumentos, ruta)
                self.assertEqual(respuesta.status_code, 403, f'{ruta} respondió {respuesta.status_code} a una cuenta sin permisos')

    def test_las_rutas_solo_con_sesion_responden_a_quien_tiene_sesion(self):
        cuenta = Client()
        cuenta.force_login(self.sin_permisos)
        for nombre in SOLO_CON_SESION:
            with self.subTest(nombre=nombre):
                self.assertEqual(cuenta.get(reverse(nombre)).status_code, 200)

    def test_cada_ruta_declara_los_permisos_que_exige_o_esta_en_la_lista_de_excepciones(self):
        sin_declarar = []
        for nombre, ruta, vista, _ in self.rutas:
            if nombre in SIN_SESION or nombre in SOLO_CON_SESION or nombre in CON_COMPROBACION_PROPIA:
                continue
            if not getattr(vista, 'permisos_requeridos', None):
                sin_declarar.append(f'{nombre} ({ruta})')
        self.assertEqual(sin_declarar, [], 'Estas rutas no usan requiere_permisos(...)')

    def test_todo_permiso_exigido_por_una_ruta_se_puede_conceder_desde_el_catalogo(self):
        for nombre, ruta, vista, _ in self.rutas:
            for permiso in getattr(vista, 'permisos_requeridos', ()):
                with self.subTest(ruta=ruta, permiso=permiso):
                    self.assertIn(permiso, catalogo.TODOS)

    def test_las_excepciones_estan_justificadas_y_siguen_existiendo(self):
        nombres = {r[0] for r in self.rutas}
        for excepcion in (*SOLO_CON_SESION, *SIN_SESION, *CON_COMPROBACION_PROPIA):
            self.assertIn(excepcion, nombres, f'{excepcion} ya no existe: quítala de la lista de excepciones')

    def test_las_rutas_con_comprobacion_propia_exigen_el_permiso_de_la_pantalla_de_entrada(self):
        cuenta = Client()
        cuenta.force_login(self.sin_permisos)
        for nombre, permiso in CON_COMPROBACION_PROPIA.items():
            with self.subTest(nombre=nombre):
                respuesta = cuenta.get(reverse(nombre)) if nombre.endswith('estado') else cuenta.post(reverse(nombre))
                self.assertEqual(respuesta.status_code, 403)
                self.assertEqual(respuesta.json()['tipo'], 'PERMISO')
