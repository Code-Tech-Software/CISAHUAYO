"""Dar de baja a un estudiante desactiva sus inscripciones vigentes, y reactivarlo las vuelve a activar."""
import importlib

from django.apps import apps
from django.urls import reverse

from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    ciclo_cerrado_de_prueba,
    ciclo_proximo_de_prueba,
    crear_alumno,
    crear_grado,
    inscribir,
)

from .models import Alumno, Inscripcion
from .tests import CURP_ANA, datos_alumno, datos_tutores


@PRUEBAS
class BajaYReactivacionTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.actual = ciclo_actual_de_prueba()
        self.proximo = ciclo_proximo_de_prueba()
        self.cerrado = ciclo_cerrado_de_prueba()
        self.grado = crear_grado('PRIMARIA', 2)
        self.siguiente = crear_grado('PRIMARIA', 3)
        self.alumno = crear_alumno(nombre='Ana', apellido_paterno='García', apellido_materno='')
        self.de_este_ciclo = inscribir(self.alumno, self.actual, self.grado)
        self.del_proximo = inscribir(self.alumno, self.proximo, self.siguiente)
        self.historica = inscribir(self.alumno, self.cerrado, crear_grado('PRIMARIA', 1))

    def recargar(self):
        for inscripcion in (self.de_este_ciclo, self.del_proximo, self.historica):
            inscripcion.refresh_from_db()

    def test_la_baja_desactiva_la_del_ciclo_actual_y_la_del_proximo(self):
        respuesta = self.client.post(reverse('alumnos:baja', args=[self.alumno.pk]), follow=True)
        self.recargar()
        self.assertEqual((self.de_este_ciclo.activa, self.de_este_ciclo.suspendida_por_baja), (False, True))
        self.assertEqual((self.del_proximo.activa, self.del_proximo.suspendida_por_baja), (False, True))
        self.assertEqual((self.historica.activa, self.historica.suspendida_por_baja), (True, False))   # la historia no se toca
        self.assertContains(respuesta, 'Sus inscripciones en 2° Primaria (2026-2027), 3° Primaria (2027-2028) quedaron desactivadas')

    def test_ya_no_cuenta_como_inscrito_en_el_ciclo(self):
        self.client.post(reverse('alumnos:baja', args=[self.alumno.pk]), follow=True)   # follow: consume el aviso de la baja
        self.assertFalse(Inscripcion.objects.filter(ciclo=self.actual, activa=True).exists())
        # el grado ya no lo cuenta entre sus estudiantes del ciclo
        html = self.client.get(self.grado.get_absolute_url()).content.decode()
        self.assertNotIn('Ana García', html)

    def test_reactivarlo_las_vuelve_a_activar(self):
        self.client.post(reverse('alumnos:baja', args=[self.alumno.pk]))
        respuesta = self.client.post(reverse('alumnos:reactivar', args=[self.alumno.pk]), follow=True)
        self.recargar()
        self.alumno.refresh_from_db()
        self.assertEqual(self.alumno.estatus, 'ACTIVO')
        self.assertEqual((self.de_este_ciclo.activa, self.de_este_ciclo.suspendida_por_baja), (True, False))
        self.assertEqual((self.del_proximo.activa, self.del_proximo.suspendida_por_baja), (True, False))
        self.assertContains(respuesta, 'fue reactivado. Sus inscripciones en')
        self.assertContains(respuesta, 'quedaron reactivadas')

    def test_una_inscripcion_dada_de_baja_a_mano_no_vuelve_con_el_estudiante(self):
        self.client.post(reverse('inscripciones:baja', args=[self.del_proximo.pk]))
        self.client.post(reverse('alumnos:baja', args=[self.alumno.pk]))
        self.client.post(reverse('alumnos:reactivar', args=[self.alumno.pk]))
        self.recargar()
        self.assertTrue(self.de_este_ciclo.activa)
        self.assertFalse(self.del_proximo.activa)   # se había dado de baja por su cuenta

    def test_sin_inscripciones_el_aviso_no_las_menciona(self):
        otro = crear_alumno(nombre='Luis', apellido_paterno='Pérez', apellido_materno='')
        respuesta = self.client.post(reverse('alumnos:baja', args=[otro.pk]), follow=True)
        self.assertContains(respuesta, 'Luis Pérez fue dado de baja. Su historial se conserva')

    def test_el_perfil_distingue_la_inscripcion_desactivada_por_la_baja(self):
        self.client.post(reverse('alumnos:baja', args=[self.alumno.pk]))
        self.assertContains(self.client.get(self.alumno.get_absolute_url()), 'Inactiva por la baja')

    def test_no_se_puede_reactivar_a_mano_la_inscripcion_mientras_siga_de_baja(self):
        self.client.post(reverse('alumnos:baja', args=[self.alumno.pk]))
        self.client.post(reverse('inscripciones:reactivar', args=[self.de_este_ciclo.pk]))
        self.recargar()
        self.assertFalse(self.de_este_ciclo.activa)

    def test_cambiar_el_estatus_de_baja_a_activo_desde_el_perfil_tambien_las_restaura(self):
        self.client.post(reverse('alumnos:baja', args=[self.alumno.pk]))
        self.client.post(reverse('alumnos:estatus', args=[self.alumno.pk]), {'estatus': 'SUSPENDIDO'})
        self.recargar()
        self.assertTrue(self.de_este_ciclo.activa)

    def test_la_baja_desde_la_edicion_tambien_las_desactiva_y_reactivar_desde_ahi_las_restaura(self):
        alumno = crear_alumno(curp=CURP_ANA, referencia='7001', nombre='Ana', apellido_paterno='García')
        inscripcion = inscribir(alumno, self.actual, self.grado)
        url = reverse('alumnos:editar', args=[alumno.pk])

        def datos(estatus):
            base = datos_alumno(referencia='7001', curp=CURP_ANA, estatus=estatus, fecha_nacimiento='2015-03-15')
            base.pop('contrasena_inicial')
            base.update(datos_tutores())
            return base

        self.assertEqual(self.client.post(url, datos('BAJA')).status_code, 302)
        inscripcion.refresh_from_db()
        self.assertEqual((inscripcion.activa, inscripcion.suspendida_por_baja), (False, True))
        self.assertEqual(self.client.post(url, datos('ACTIVO')).status_code, 302)
        inscripcion.refresh_from_db()
        self.assertTrue(inscripcion.activa)

    def test_la_migracion_corrige_a_quien_ya_estaba_de_baja(self):
        migracion = importlib.import_module('Alumnos.migrations.0015_inscripcion_suspendida_por_baja')
        Alumno.objects.filter(pk=self.alumno.pk).update(estatus='BAJA')   # como quedaba antes: de baja e inscrito
        migracion.suspender_las_de_quien_ya_estaba_de_baja(apps, None)
        self.recargar()
        self.assertEqual((self.de_este_ciclo.activa, self.de_este_ciclo.suspendida_por_baja), (False, True))
        self.assertTrue(self.historica.activa)
        self.client.post(reverse('alumnos:reactivar', args=[self.alumno.pk]))
        self.de_este_ciclo.refresh_from_db()
        self.assertTrue(self.de_este_ciclo.activa)
