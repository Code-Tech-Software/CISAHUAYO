"""El sexo ya no ofrece «Otro» y la religión se elige de una lista."""
import importlib
import re

from django.apps import apps
from django.test import SimpleTestCase
from django.urls import reverse

from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase, crear_alumno

from .models import Alumno
from .tests import CURP_ANA, datos_alumno, datos_tutores, tutor_nuevo
from .utils import normalizar_religion

RELIGIONES = [
    'Católica',
    'Cristiana',
    'Evangélica',
    'Iglesia de Jesucristo de los Santos de los Últimos Días',
    'Musulmana',
    'Judía',
    'Budista',
    'Hinduista',
    'Otra',
]


def opciones_de(html, campo):
    """[(valor, texto, seleccionada)] del <select name="campo">."""
    select = re.search(r'<select[^>]*name="' + campo + r'"[^>]*>(.*?)</select>', html, re.S).group(1)
    return [
        (re.search(r'value="([^"]*)"', atributos).group(1), texto.strip(), 'selected' in atributos)
        for atributos, texto in re.findall(r'<option([^>]*)>(.*?)</option>', select, re.S)
    ]


@PRUEBAS
class SexoTests(BaseTestCase):
    def publicar(self, **cambios):
        datos = {**datos_alumno(**cambios), **datos_tutores(tutor_nuevo(tutor_principal='on'))}
        return self.client.post(reverse('alumnos:crear'), datos)

    def test_el_modelo_solo_conoce_masculino_y_femenino(self):
        self.assertEqual(Alumno.SEXO_CHOICES, [('M', 'Masculino'), ('F', 'Femenino')])

    def test_el_formulario_solo_ofrece_masculino_y_femenino(self):
        html = self.client.get(reverse('alumnos:crear')).content.decode()
        valores = re.findall(r'<input[^>]*type="radio"[^>]*name="sexo"[^>]*value="([^"]*)"', html) or \
            re.findall(r'<input[^>]*name="sexo"[^>]*value="([^"]*)"', html)
        self.assertEqual(valores, ['M', 'F'])
        self.assertNotIn('>Otro<', re.search(r'<legend[^>]*>Sexo.*?</fieldset>', html, re.S).group(0))

    def test_rechaza_otro(self):
        respuesta = self.publicar(sexo='O')
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Seleccione una opción válida')
        self.assertFalse(Alumno.objects.exists())

    def test_registra_con_los_dos_que_quedan(self):
        self.assertEqual(self.publicar(sexo='F').status_code, 302)
        self.assertEqual(Alumno.objects.get().sexo, 'F')


@PRUEBAS
class ReligionTests(BaseTestCase):
    def publicar(self, **cambios):
        datos = {**datos_alumno(**cambios), **datos_tutores(tutor_nuevo(tutor_principal='on'))}
        return self.client.post(reverse('alumnos:crear'), datos)

    def test_la_lista_es_la_pedida_en_ese_orden(self):
        self.assertEqual([valor for valor, _ in Alumno.RELIGION_CHOICES], RELIGIONES)

    def test_el_formulario_la_ofrece_como_menu_desplegable(self):
        html = self.client.get(reverse('alumnos:crear')).content.decode()
        opciones = opciones_de(html, 'religion')
        self.assertEqual([texto for _, texto, _ in opciones], ['Selecciona…', *RELIGIONES])
        self.assertEqual(opciones[0][0], '')                         # es opcional
        self.assertEqual([valor for valor, _, seleccionada in opciones if seleccionada], [''])   # nace sin elegir
        self.assertNotRegex(html, r'<input[^>]*name="religion"')     # ya no es un campo de texto libre

    def test_registra_la_religion_elegida(self):
        for religion in RELIGIONES:
            Alumno.objects.all().delete()
            self.assertEqual(self.publicar(religion=religion).status_code, 302, religion)
            self.assertEqual(Alumno.objects.get().religion, religion)

    def test_es_opcional(self):
        self.assertEqual(self.publicar(religion='').status_code, 302)
        self.assertEqual(Alumno.objects.get().religion, '')

    def test_rechaza_lo_que_no_esta_en_la_lista(self):
        respuesta = self.publicar(religion='Pastafari')
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Seleccione una opción válida')
        self.assertFalse(Alumno.objects.exists())

    def test_al_editar_se_preselecciona_la_religion_guardada(self):
        alumno = crear_alumno(religion='Budista')
        html = self.client.get(reverse('alumnos:editar', args=[alumno.pk])).content.decode()
        seleccionadas = [valor for valor, _, seleccionada in opciones_de(html, 'religion') if seleccionada]
        self.assertEqual(seleccionadas, ['Budista'])

    def test_el_perfil_muestra_la_religion(self):
        alumno = crear_alumno(religion='Musulmana')
        self.assertContains(self.client.get(alumno.get_absolute_url()), 'Musulmana')

    # --- registros anteriores, escritos a mano ---------------------------------------------------
    def datos_de_edicion(self, alumno, **cambios):
        datos = datos_alumno(
            referencia=alumno.referencia, curp=alumno.curp, nombre=alumno.nombre, sexo='M',
            fecha_nacimiento=alumno.fecha_nacimiento.isoformat(), estatus='ACTIVO',
        )
        datos.pop('contrasena_inicial')
        datos.update(datos_tutores())
        datos.update(cambios)
        return datos

    def test_una_religion_anterior_que_es_de_la_lista_se_preselecciona_con_su_forma_correcta(self):
        alumno = crear_alumno(religion='Catolico')
        html = self.client.get(reverse('alumnos:editar', args=[alumno.pk])).content.decode()
        seleccionadas = [valor for valor, _, seleccionada in opciones_de(html, 'religion') if seleccionada]
        self.assertEqual(seleccionadas, ['Católica'])
        self.assertEqual(len(opciones_de(html, 'religion')), 10)     # no se agrega una opción repetida

    def test_al_guardar_se_registra_con_la_forma_de_la_lista(self):
        alumno = crear_alumno(religion='Catolico', curp=CURP_ANA)
        respuesta = self.client.post(reverse('alumnos:editar', args=[alumno.pk]), self.datos_de_edicion(alumno, religion='Católica'))
        self.assertEqual(respuesta.status_code, 302)
        alumno.refresh_from_db()
        self.assertEqual(alumno.religion, 'Católica')

    def test_una_religion_anterior_que_no_esta_en_la_lista_se_conserva_como_opcion(self):
        alumno = crear_alumno(religion='Testigo de Jehová', curp=CURP_ANA)
        url = reverse('alumnos:editar', args=[alumno.pk])
        opciones = opciones_de(self.client.get(url).content.decode(), 'religion')
        self.assertEqual(opciones[-1][:2], ('Testigo de Jehová', 'Testigo de Jehová'))
        self.assertTrue(opciones[-1][2])
        # Editar otra cosa no obliga a cambiarla ni la pierde
        respuesta = self.client.post(url, self.datos_de_edicion(alumno, religion='Testigo de Jehová', colonia='Las Palmas'))
        self.assertEqual(respuesta.status_code, 302)
        alumno.refresh_from_db()
        self.assertEqual((alumno.religion, alumno.colonia), ('Testigo de Jehová', 'Las Palmas'))

    def test_el_valor_anterior_no_se_ofrece_a_los_demas(self):
        crear_alumno(religion='Testigo de Jehová')
        html = self.client.get(reverse('alumnos:crear')).content.decode()
        self.assertNotIn('Testigo de Jehová', html)


class NormalizarReligionTests(SimpleTestCase):
    def test_reconoce_la_lista_sin_importar_acentos_mayusculas_ni_genero(self):
        casos = {
            'católica': 'Católica', 'CATOLICO': 'Católica', 'Catolico': 'Católica', 'cristiano': 'Cristiana',
            'evangelico': 'Evangélica', 'Musulmán': 'Musulmana', 'musulmana': 'Musulmana', 'judío': 'Judía', 'JUDIA': 'Judía',
            'budista': 'Budista', 'hinduista': 'Hinduista', 'otra': 'Otra', 'otro': 'Otra', '  Católica  ': 'Católica',
        }
        for texto, esperado in casos.items():
            self.assertEqual(normalizar_religion(texto), esperado, texto)

    def test_reconoce_la_iglesia_de_jesucristo_por_sus_nombres_comunes(self):
        for texto in (
            'Iglesia de Jesucristo de los Santos de los Últimos Días', 'mormón', 'Mormona', 'SUD',
            'Santos de los últimos días', 'Iglesia de Jesucristo',
        ):
            self.assertEqual(normalizar_religion(texto), 'Iglesia de Jesucristo de los Santos de los Últimos Días', texto)

    def test_reconoce_el_nombre_de_la_doctrina(self):
        self.assertEqual(normalizar_religion('Islam'), 'Musulmana')
        self.assertEqual(normalizar_religion('Judaísmo'), 'Judía')
        self.assertEqual(normalizar_religion('Budismo'), 'Budista')
        self.assertEqual(normalizar_religion('Hinduismo'), 'Hinduista')

    def test_lo_que_no_conoce_es_none(self):
        for texto in ('', None, 'Testigo de Jehová', 'Pastafari'):
            self.assertIsNone(normalizar_religion(texto), texto)


@PRUEBAS
class MigracionDeReligionesTests(BaseTestCase):
    def test_la_migracion_normaliza_las_religiones_conocidas_y_no_toca_las_demas(self):
        migracion = importlib.import_module('Alumnos.migrations.0011_estudiante_acceso_y_catalogos')
        a = crear_alumno(religion='Catolico')
        b = crear_alumno(religion='cristiano')
        c = crear_alumno(religion='Testigo de Jehová')
        d = crear_alumno(religion='Católica')
        e = crear_alumno(religion='')
        migracion.normalizar_religiones(apps, None)
        for alumno in (a, b, c, d, e):
            alumno.refresh_from_db()
        self.assertEqual([x.religion for x in (a, b, c, d, e)], ['Católica', 'Cristiana', 'Testigo de Jehová', 'Católica', ''])

    def test_la_copia_de_la_lista_en_la_migracion_coincide_con_el_modelo(self):
        migracion = importlib.import_module('Alumnos.migrations.0011_estudiante_acceso_y_catalogos')
        self.assertEqual(list(migracion.RELIGIONES), RELIGIONES)

    def test_una_migracion_nueva_no_queda_pendiente(self):
        """Los modelos y las migraciones están al día (sin cambios sin migrar)."""
        from django.core.management import call_command
        call_command('makemigrations', 'Alumnos', '--check', '--dry-run')
