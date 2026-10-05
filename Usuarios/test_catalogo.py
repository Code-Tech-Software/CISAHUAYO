"""El catálogo de permisos: que todo lo que el código exige se pueda conceder, y sus dependencias."""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import Permission
from django.test import SimpleTestCase, TestCase

from Usuarios import catalogo
from Usuarios.models import Rol
from Usuarios.seguridad import codigos, permisos_de_rol

RAIZ = Path(settings.BASE_DIR)
# «Alumnos.view_alumno», «auth.add_user», «Usuarios.change_rol»... tal como se escriben en vistas y plantillas
CODIGO = re.compile(r"""['"\s.](Alumnos|auth|Usuarios)\.((?:view|add|change|delete)_[a-z]+)\b""")


def archivos_del_proyecto(sufijos):
    for archivo in RAIZ.rglob('*'):
        partes = set(archivo.parts)
        if archivo.suffix in sufijos and not partes & {'.venv', 'staticfiles', 'migrations', '__pycache__', 'node_modules'}:
            yield archivo


class EstructuraDelCatalogoTests(SimpleTestCase):
    def test_cada_permiso_pertenece_a_una_sola_funcion(self):
        vistos = {}
        for modulo in catalogo.MODULOS:
            for funcion in modulo.funciones:
                for permiso in funcion.permisos.values():
                    self.assertNotIn(permiso, vistos, f'{permiso} está en dos funciones')
                    vistos[permiso] = funcion.nombre

    def test_las_claves_de_los_modulos_son_unicas(self):
        claves = [m.clave for m in catalogo.MODULOS]
        self.assertEqual(len(claves), len(set(claves)))

    def test_toda_funcion_tiene_ayuda_para_cada_accion(self):
        for modulo in catalogo.MODULOS:
            for funcion in modulo.funciones:
                self.assertEqual(set(funcion.ayuda), set(funcion.permisos), f'{modulo.nombre} · {funcion.nombre}')

    def test_las_acciones_son_las_cuatro_conocidas(self):
        validas = {clave for clave, _ in catalogo.ACCIONES}
        for modulo in catalogo.MODULOS:
            for funcion in modulo.funciones:
                self.assertLessEqual(set(funcion.permisos), validas)

    def test_los_requisitos_apuntan_a_permisos_del_catalogo(self):
        for permiso, necesarios in catalogo.REQUISITOS.items():
            for necesario in necesarios:
                self.assertIn(necesario, catalogo.TODOS, f'{permiso} necesita {necesario}, que no está en el catálogo')
                self.assertNotEqual(permiso, necesario)

    def test_toda_accion_que_no_es_ver_necesita_poder_ver(self):
        for modulo in catalogo.MODULOS:
            for funcion in modulo.funciones:
                ver = funcion.permisos.get('ver')
                for accion, permiso in funcion.permisos.items():
                    if ver and accion != 'ver':
                        self.assertIn(ver, catalogo.REQUISITOS[permiso], f'{permiso} debería necesitar {ver}')
                    if not ver:
                        # Una función sin «ver» propio depende de algo que sí lo tenga, o es independiente (la pantalla de entrada)
                        for necesario in funcion.requiere:
                            self.assertIn(necesario, catalogo.TODOS)

    def test_no_hay_ciclos_de_dependencias(self):
        for permiso in catalogo.TODOS:
            self.assertNotIn(permiso, catalogo.dependientes(permiso), f'{permiso} depende de sí mismo')


class DependenciasTests(SimpleTestCase):
    def test_conceder_editar_concede_ver(self):
        self.assertEqual(catalogo.con_requisitos({'Alumnos.change_alumno'}), {'Alumnos.change_alumno', 'Alumnos.view_alumno'})

    def test_conceder_el_plan_de_materias_concede_ver_materias(self):
        resultado = catalogo.con_requisitos({'Alumnos.change_materiagrado'})
        self.assertIn('Alumnos.view_materia', resultado)

    def test_ver_no_arrastra_nada(self):
        self.assertEqual(catalogo.con_requisitos({'Alumnos.view_alumno'}), {'Alumnos.view_alumno'})

    def test_un_permiso_desconocido_se_descarta(self):
        self.assertEqual(catalogo.con_requisitos({'Alumnos.view_alumno', 'Alumnos.hackear'}), {'Alumnos.view_alumno'})

    def test_quitar_ver_arrastra_lo_que_depende_de_el(self):
        dependientes = catalogo.dependientes('Alumnos.view_alumno')
        self.assertEqual(dependientes, {'Alumnos.add_alumno', 'Alumnos.change_alumno', 'Alumnos.delete_alumno'})

    def test_el_cierre_del_dia_necesita_ver_la_asistencia(self):
        self.assertIn('Alumnos.view_asistenciageneral', catalogo.REQUISITOS['Alumnos.add_cierredia'])

    def test_la_pantalla_de_entrada_es_independiente(self):
        self.assertEqual(catalogo.REQUISITOS['Alumnos.add_asistenciageneral'], ())

    def test_el_resumen_marca_lo_concedido(self):
        resumen = catalogo.resumen({'Alumnos.view_alumno', 'Alumnos.change_alumno'})
        alumnos = next(m for m in resumen if m['modulo'].clave == 'alumnos')
        self.assertEqual(alumnos['concedidos'], 2)
        self.assertEqual(alumnos['posibles'], 4)
        celdas = alumnos['filas'][0]['celdas']
        self.assertEqual([c['tiene'] for c in celdas], [True, False, True, False])

    def test_el_resumen_deja_celdas_vacias_donde_la_funcion_no_tiene_la_accion(self):
        resumen = catalogo.resumen(set())
        ciclos = next(m for m in resumen if m['modulo'].clave == 'ciclos')
        self.assertIsNone(ciclos['filas'][0]['celdas'][3])   # los ciclos no se dan de baja


class CatalogoContraLaBaseTests(TestCase):
    def test_todos_los_permisos_del_catalogo_existen_en_django(self):
        existentes = codigos(Permission.objects.select_related('content_type'))
        faltantes = sorted(catalogo.TODOS - existentes)
        self.assertEqual(faltantes, [], 'Estos permisos del catálogo no existen como permisos de Django')


class TodoLoQueElCodigoExigeSePuedeConcederTests(SimpleTestCase):
    """Si una vista o una plantilla pide un permiso que no está en el catálogo, ningún rol podría tenerlo."""

    def test_permisos_pedidos_en_las_vistas_y_plantillas(self):
        pedidos = {}
        for archivo in archivos_del_proyecto({'.py', '.html'}):
            if archivo.name.startswith('test') or 'tests' in archivo.parts or archivo.name in ('catalogo.py', 'iniciales.py', 'pruebas.py'):
                continue
            for app, codename in CODIGO.findall(archivo.read_text(encoding='utf-8')):
                pedidos.setdefault(f'{app}.{codename}', set()).add(archivo.name)
        self.assertGreater(len(pedidos), 40, 'la búsqueda no encontró los permisos del proyecto')
        fuera = {p: sorted(a) for p, a in pedidos.items() if p not in catalogo.TODOS}
        self.assertEqual(fuera, {}, 'Estos permisos se exigen en el código pero no se pueden conceder desde Roles')


class RolesInicialesTests(TestCase):
    def test_existe_el_administrador_del_sistema_con_acceso_total(self):
        admin = Rol.objects.get(acceso_total=True)
        self.assertEqual(admin.nombre, 'Administrador')
        self.assertTrue(admin.es_sistema)
        self.assertEqual(permisos_de_rol(admin), set(catalogo.TODOS))

    def test_solo_hay_un_rol_del_sistema(self):
        self.assertEqual(Rol.objects.filter(es_sistema=True).count(), 1)

    def test_los_roles_de_arranque_existen_y_usan_permisos_del_catalogo(self):
        nombres = set(Rol.objects.values_list('grupo__name', flat=True))
        self.assertLessEqual({'Administrador', 'Dirección', 'Control escolar', 'Docente', 'Recepción'}, nombres)
        for rol in Rol.objects.filter(acceso_total=False):
            permisos = permisos_de_rol(rol)
            self.assertTrue(permisos, rol.nombre)
            self.assertLessEqual(permisos, set(catalogo.TODOS), rol.nombre)

    def test_los_roles_de_arranque_son_coherentes_con_sus_dependencias(self):
        for rol in Rol.objects.filter(acceso_total=False):
            permisos = permisos_de_rol(rol)
            self.assertEqual(catalogo.con_requisitos(permisos), permisos, f'{rol.nombre} tiene permisos sin lo que necesitan')

    def test_recepcion_solo_registra_entradas_y_consulta(self):
        permisos = permisos_de_rol(Rol.objects.get(grupo__name='Recepción'))
        self.assertIn('Alumnos.add_asistenciageneral', permisos)
        self.assertNotIn('Alumnos.add_alumno', permisos)
        self.assertNotIn('auth.view_user', permisos)

    def test_nadie_salvo_el_administrador_administra_usuarios_y_roles(self):
        for rol in Rol.objects.filter(acceso_total=False):
            permisos = permisos_de_rol(rol)
            for escritura in ('auth.add_user', 'auth.change_user', 'auth.delete_user', 'Usuarios.add_rol', 'Usuarios.change_rol', 'Usuarios.delete_rol'):
                self.assertNotIn(escritura, permisos, rol.nombre)

    def test_crear_los_roles_iniciales_otra_vez_no_cambia_nada(self):
        from Usuarios.iniciales import crear_roles_iniciales
        antes = Rol.objects.count()
        self.assertFalse(crear_roles_iniciales())
        self.assertEqual(Rol.objects.count(), antes)

    def test_los_superusuarios_existentes_pasan_a_ser_administradores(self):
        from django.contrib.auth import get_user_model
        from Usuarios.iniciales import crear_roles_iniciales
        # Se simula una base con una cuenta de superusuario hecha antes de que existieran los roles
        Rol.objects.all().delete()
        cuenta = get_user_model().objects.create_superuser('luis', 'luis@example.com', 'x')
        self.assertTrue(crear_roles_iniciales())
        cuenta.refresh_from_db()
        self.assertEqual([g.name for g in cuenta.groups.all()], ['Administrador'])
        self.assertTrue(cuenta.is_superuser)
