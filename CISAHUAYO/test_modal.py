"""Formularios en ventanas modales (static/js/modal-form.js + CISAHUAYO/modal.py).

El navegador pide la página de un formulario con la cabecera `X-Modal-Form` y la envía igual; el servidor solo cambia
una cosa: las redirecciones se devuelven como JSON. Estas pruebas cubren ese contrato, que las páginas de formulario
sigan teniendo la estructura que el script necesita y que ningún botón de alta o edición se quede sin abrirse en la
ventana (cada uno sigue funcionando como enlace normal sin JavaScript).
"""
import re
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse

from CISAHUAYO.modal import ENCABEZADO, FormularioModalMiddleware
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    crear_alumno,
    crear_ciclo,
    crear_grado,
    crear_profesor,
    crear_rol,
    crear_tutor,
    inscribir,
)

CABECERAS = {'HTTP_X_MODAL_FORM': '1', 'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
RAIZ = Path(settings.BASE_DIR)


# ---------------------------------------------------------------------------
# El middleware
# ---------------------------------------------------------------------------
class MiddlewareTests(SimpleTestCase):
    def pasar(self, respuesta, con_cabecera=True):
        peticion = RequestFactory().post('/x/', **({'HTTP_X_MODAL_FORM': '1'} if con_cabecera else {}))
        return FormularioModalMiddleware(lambda _: respuesta)(peticion)

    def test_el_nombre_de_la_cabecera_es_el_que_envia_el_script(self):
        self.assertEqual(ENCABEZADO, 'X-Modal-Form')
        self.assertIn("'X-Modal-Form': '1'", (RAIZ / 'static/js/modal-form.js').read_text(encoding='utf-8'))

    def test_una_redireccion_con_la_cabecera_se_devuelve_como_json(self):
        for codigo in (301, 302, 303, 307, 308):
            with self.subTest(codigo=codigo):
                respuesta = self.pasar(HttpResponse(status=codigo, headers={'Location': '/alumnos/'}))
                self.assertIsInstance(respuesta, JsonResponse)
                self.assertEqual(respuesta.status_code, 200)
                self.assertJSONEqual(respuesta.content, {'redirect': '/alumnos/'})
                self.assertEqual(respuesta['Cache-Control'], 'no-store')

    def test_las_galletas_de_la_redireccion_se_conservan(self):
        """Los mensajes de confirmación viajan en una galleta: sin ella el aviso se perdería."""
        original = HttpResponseRedirect('/alumnos/')
        original.set_cookie('messages', 'aviso', httponly=True)
        original.set_cookie('csrftoken', 'abc')
        respuesta = self.pasar(original)
        self.assertEqual(respuesta.cookies['messages'].value, 'aviso')
        self.assertTrue(respuesta.cookies['messages']['httponly'])
        self.assertEqual(respuesta.cookies['csrftoken'].value, 'abc')

    def test_sin_la_cabecera_la_redireccion_no_se_toca(self):
        original = HttpResponseRedirect('/alumnos/')
        respuesta = self.pasar(original, con_cabecera=False)
        self.assertIs(respuesta, original)
        self.assertEqual(respuesta.status_code, 302)

    def test_lo_que_no_es_redireccion_no_se_toca(self):
        for respuesta in (HttpResponse('<form></form>'), HttpResponse(status=404), HttpResponse(status=403), JsonResponse({'a': 1})):
            with self.subTest(codigo=respuesta.status_code):
                self.assertIs(self.pasar(respuesta), respuesta)

    def test_esta_registrado_despues_de_los_mensajes(self):
        middleware = settings.MIDDLEWARE
        self.assertGreater(
            middleware.index('CISAHUAYO.modal.FormularioModalMiddleware'),
            middleware.index('django.contrib.messages.middleware.MessageMiddleware'),
        )


# ---------------------------------------------------------------------------
# Las vistas reales, como las usa la ventana
# ---------------------------------------------------------------------------
@PRUEBAS
class FlujoDeLaVentanaTests(BaseTestCase):
    def test_guardar_responde_con_la_redireccion_en_json_y_el_aviso_sobrevive(self):
        datos = {'nombre': 'María', 'apellido_paterno': 'López', 'telefono': '353 123 4567', 'estado': 'Michoacán'}
        respuesta = self.client.post(reverse('tutores:crear'), datos, **CABECERAS)
        self.assertEqual(respuesta.status_code, 200)
        destino = respuesta.json()['redirect']
        self.assertTrue(destino.startswith('/tutores/'))
        # La página a la que navega el navegador muestra el mensaje de confirmación
        pagina = self.client.get(destino)
        self.assertContains(pagina, 'fue registrado correctamente')

    def test_sin_la_cabecera_sigue_siendo_una_redireccion_normal(self):
        datos = {'nombre': 'María', 'apellido_paterno': 'López', 'telefono': '353 123 4567', 'estado': 'Michoacán'}
        respuesta = self.client.post(reverse('tutores:crear'), datos)
        self.assertEqual(respuesta.status_code, 302)

    def test_con_errores_se_devuelve_la_pagina_con_el_formulario_y_sus_avisos(self):
        respuesta = self.client.post(reverse('tutores:crear'), {'nombre': '', 'telefono': ''}, **CABECERAS)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta['Content-Type'].split(';')[0], 'text/html')
        self.assertContains(respuesta, 'field__error')
        self.assertContains(respuesta, 'class="form-page"')

    def test_sesion_vencida_se_resuelve_con_json_para_ir_al_acceso(self):
        self.client.logout()
        respuesta = self.client.get(reverse('tutores:crear'), **CABECERAS)
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('login', respuesta.json()['redirect'])

    def test_sin_permiso_no_se_abre_el_formulario(self):
        self.client.force_login(self.sin_permisos)
        respuesta = self.client.get(reverse('tutores:crear'), **CABECERAS)
        self.assertIn(respuesta.status_code, (200, 403))
        if respuesta.status_code == 200:   # redirigió: el script navega ahí
            self.assertIn('redirect', respuesta.json())
        else:
            self.assertNotContains(respuesta, 'class="form-page"', status_code=403)


# ---------------------------------------------------------------------------
# La estructura que el script necesita
# ---------------------------------------------------------------------------
@PRUEBAS
class EstructuraDeLasPaginasDeFormularioTests(BaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.ciclo = ciclo_actual_de_prueba()
        cls.grado = crear_grado()
        cls.alumno = crear_alumno()
        cls.tutor = crear_tutor()
        cls.profesor = crear_profesor()
        cls.inscripcion = inscribir(cls.alumno, cls.ciclo, cls.grado)
        cls.rol_editable = crear_rol('Rol de prueba para la ventana', {'Alumnos.view_alumno'})

    def paginas(self):
        from Alumnos.models import Materia
        materia = Materia.objects.create(clave='MAT', nombre='Matemáticas')
        return {
            'alumnos:crear': reverse('alumnos:crear'),
            'alumnos:editar': reverse('alumnos:editar', args=[self.alumno.pk]),
            'tutores:crear': reverse('tutores:crear'),
            'tutores:editar': reverse('tutores:editar', args=[self.tutor.pk]),
            'profesores:crear': reverse('profesores:crear'),
            'profesores:editar': reverse('profesores:editar', args=[self.profesor.pk]),
            'materias:crear': reverse('materias:crear'),
            'materias:editar': reverse('materias:editar', args=[materia.pk]),
            'ciclos:crear': reverse('ciclos:crear'),
            'ciclos:editar': reverse('ciclos:editar', args=[self.ciclo.pk]),
            'grados:crear': reverse('grados:crear'),
            'grados:editar': reverse('grados:editar', args=[self.grado.pk]),
            'inscripciones:crear': reverse('inscripciones:crear'),
            'inscripciones:editar': reverse('inscripciones:editar', args=[self.inscripcion.pk]),
            'asistencias:justificacion_crear': reverse('asistencias:justificacion_crear'),
            'usuarios:crear': reverse('usuarios:crear'),
            'usuarios:editar': reverse('usuarios:editar', args=[self.admin.pk]),
            'roles:crear': reverse('roles:crear'),
            'roles:editar': reverse('roles:editar', args=[self.rol_editable.pk]),
        }

    def test_cada_pagina_de_formulario_tiene_titulo_y_un_formulario_que_el_script_reconoce(self):
        for nombre, url in self.paginas().items():
            with self.subTest(pagina=nombre):
                respuesta = self.client.get(url, **CABECERAS)
                self.assertEqual(respuesta.status_code, 200)
                html = respuesta.content.decode()
                self.assertIn('page-header__title', html)
                self.assertRegex(html, r'<form class="(form-page|wizard)\b')
                self.assertIn('method="post"', html)
                self.assertIn('csrfmiddlewaretoken', html)
                self.assertIn('id="contenido"', html)
                self.assertIn('class="page"', html)

    def test_cancelar_es_un_enlace_en_la_pagina_y_el_script_lo_convierte_en_boton(self):
        """El script busca estos contenedores; sin JavaScript «Cancelar» es un enlace a la página anterior."""
        for nombre, url in self.paginas().items():
            with self.subTest(pagina=nombre):
                html = self.client.get(url).content.decode()
                self.assertRegex(html, r'(action-bar|wizard__footer)">\s*<a class="btn')

    def test_los_ganchos_del_script_existen_en_la_ventana_de_la_plantilla_base(self):
        script = (RAIZ / 'static/js/modal-form.js').read_text(encoding='utf-8')
        ventana = (RAIZ / 'templates/partials/modal_formulario.html').read_text(encoding='utf-8')
        ganchos = set(re.findall(r'data-form-modal(?:-[a-z]+)?', script))
        self.assertTrue(ganchos, 'el script no usa ningún gancho data-form-modal')
        for gancho in ganchos:
            self.assertIn(gancho, ventana, f'{gancho} lo usa modal-form.js pero no está en la ventana')

    def test_todas_las_paginas_incluyen_la_ventana_y_el_script(self):
        for url in (reverse('inicio'), reverse('alumnos:lista'), reverse('tutores:lista'), reverse('ciclos:lista')):
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                self.assertEqual(html.count('data-form-modal '), 1)
                self.assertIn('id="modal-formulario"', html)
                self.assertIn('js/modal-form.js', html)
        self.assertTrue((RAIZ / 'static/js/modal-form.js').is_file())


@PRUEBAS
class EnlacesQueAbrenLaVentanaTests(BaseTestCase):
    def test_los_botones_de_alta_de_cada_listado_abren_la_ventana(self):
        for nombre in ('alumnos:crear', 'tutores:crear', 'profesores:crear', 'materias:crear', 'ciclos:crear',
                       'grados:crear', 'inscripciones:crear', 'asistencias:justificacion_crear', 'usuarios:crear', 'roles:crear'):
            app, _ = nombre.split(':')
            lista = reverse({'asistencias': 'asistencias:justificaciones'}.get(app, f'{app}:lista'))
            with self.subTest(boton=nombre):
                html = self.client.get(lista).content.decode()
                enlace = re.search(r'<a [^>]*href="' + re.escape(reverse(nombre)) + r'[^"]*"[^>]*>', html)
                self.assertIsNotNone(enlace, f'{lista} no tiene el botón {nombre}')
                self.assertIn('data-modal-form', enlace.group(0))

    def test_los_enlaces_de_edicion_de_una_fila_abren_la_ventana(self):
        crear_tutor()
        html = self.client.get(reverse('tutores:lista')).content.decode()
        enlace = re.search(r'<a [^>]*href="/tutores/\d+/editar/"[^>]*>', html)
        self.assertIsNotNone(enlace)
        self.assertIn('data-modal-form', enlace.group(0))

    def test_ningun_enlace_de_alta_o_edicion_se_queda_fuera(self):
        """Revisa las plantillas: todo <a> hacia una ruta crear/editar lleva data-modal-form (salvo dentro de otras ventanas)."""
        etiqueta = re.compile(r"<a\b(?:[^>{]|\{%[^%]*%\}|\{\{[^}]*\}\}|\{#[^#]*#\})*>")
        ruta = re.compile(
            r"\{%\s*url\s+'(?:alumnos|tutores|profesores|materias|ciclos|grados|inscripciones|horarios|usuarios|roles):(?:crear|editar)'"
            r"|\{%\s*url\s+'asistencias:justificacion_(?:crear|editar)'"
        )
        excepciones = {'_modal_asignar.html'}
        sueltos = []
        for archivo in sorted((RAIZ / 'templates').rglob('*.html')):
            if archivo.name in excepciones:
                continue
            for a in etiqueta.findall(archivo.read_text(encoding='utf-8')):
                if ruta.search(a) and 'data-modal-form' not in a:
                    sueltos.append(f'{archivo.name}: {a[:90]}')
        self.assertEqual(sueltos, [])

    def test_sin_javascript_los_enlaces_siguen_llevando_a_la_pagina_completa(self):
        """El atributo no cambia el href: es un enlace normal."""
        html = self.client.get(reverse('ciclos:lista')).content.decode()
        enlace = re.search(r'<a [^>]*data-modal-form[^>]*>', html).group(0)
        self.assertIn(f'href="{reverse("ciclos:crear")}"', enlace)
        crear_ciclo('2026-2027', -10, 300)
        self.assertContains(self.client.get(reverse('ciclos:crear')), 'Nuevo ciclo escolar')
