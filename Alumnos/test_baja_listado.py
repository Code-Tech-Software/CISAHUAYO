"""El botón «Dar de baja» de las acciones del listado de estudiantes."""
import re

from django.urls import reverse

from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase, crear_alumno

from .models import Alumno


def botones_de_baja(html):
    """Las etiquetas <button data-baja ...> del listado."""
    return re.findall(r'<button[^>]*data-baja\b[^>]*>', html)


@PRUEBAS
class BajaDesdeElListadoTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ana = crear_alumno(nombre='Ana', apellido_paterno='García', apellido_materno='', curp='GALA150315MMNRPNA1')
        self.luis = crear_alumno(nombre='Luis', apellido_paterno='Pérez', apellido_materno='', curp='PEMJ100720HMNRRNA5')
        self.lista = reverse('alumnos:lista')

    def test_cada_fila_trae_su_boton_de_baja_con_la_ruta_y_el_nombre(self):
        botones = botones_de_baja(self.client.get(self.lista).content.decode())
        self.assertEqual(len(botones), 2)
        for estudiante in (self.ana, self.luis):
            boton = next(b for b in botones if f'data-action="{reverse("alumnos:baja", args=[estudiante.pk])}"' in b)
            self.assertIn(f'data-nombre="{estudiante}"', boton)
            self.assertIn('data-modal-open="modal-baja"', boton)
            self.assertIn(f'aria-label="Dar de baja a {estudiante}"', boton)

    def test_hay_una_sola_ventana_de_confirmacion_que_envia_por_post(self):
        html = self.client.get(self.lista).content.decode()
        self.assertEqual(html.count('id="modal-baja"'), 1)
        ventana = re.search(r'<dialog[^>]*id="modal-baja".*?</dialog>', html, re.S).group(0)
        self.assertIn('method="post"', ventana)
        self.assertIn('csrfmiddlewaretoken', ventana)
        self.assertIn('data-baja-form', ventana)
        self.assertIn('js/baja-lista.js', html)

    def test_dar_de_baja_desde_el_listado_la_oculta_y_vuelve_al_listado(self):
        respuesta = self.client.post(reverse('alumnos:baja', args=[self.ana.pk]), follow=True)
        self.assertRedirects(respuesta, self.lista)
        self.assertContains(respuesta, 'Ana García fue dado de baja')
        self.ana.refresh_from_db()
        self.assertEqual(self.ana.estatus, 'BAJA')
        self.assertEqual(len(botones_de_baja(respuesta.content.decode())), 1)      # ya no está en el listado principal

    def test_en_el_filtro_de_bajas_se_ofrece_reactivar_y_no_dar_de_baja(self):
        Alumno.objects.filter(pk=self.ana.pk).update(estatus='BAJA')
        html = self.client.get(self.lista + '?estatus=BAJA').content.decode()
        self.assertEqual(botones_de_baja(html), [])
        self.assertIn(reverse('alumnos:reactivar', args=[self.ana.pk]), html)

    def test_solo_lo_ve_quien_puede_dar_de_baja(self):
        self.con_permisos('view_alumno', 'change_alumno')
        html = self.client.get(self.lista).content.decode()
        self.assertEqual(botones_de_baja(html), [])
        self.assertNotIn('modal-baja', html)
        self.con_permisos('view_alumno', 'delete_alumno')
        self.assertEqual(len(botones_de_baja(self.client.get(self.lista).content.decode())), 2)

    def test_el_texto_de_la_ventana_habla_de_estudiantes(self):
        html = self.client.get(self.lista).content.decode()
        ventana = re.search(r'<dialog[^>]*id="modal-baja".*?</dialog>', html, re.S).group(0)
        self.assertNotRegex(ventana, r'(?i)alumn[oa]s?\b')
        self.assertIn('baja lógica', ventana)
