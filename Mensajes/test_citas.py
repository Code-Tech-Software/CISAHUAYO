"""Mejoras de la mensajería del 2026-10-23: responder citando, corregir un mensaje propio en sus primeros 2 minutos,
«escribiendo…» y quién es cada familia en la lista («Tutor de Ana … (4° A)»)."""
from datetime import timedelta
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone

from CISAHUAYO.pruebas import PRUEBAS

from . import reglas
from .models import Mensaje
from .test_conversaciones import Base


@PRUEBAS
class CitasTests(Base):
    def test_responde_citando_un_mensaje_de_la_conversacion(self):
        primero = reglas.enviar(self.conversacion, self.p(self.ana), '¿Hay tarea de fracciones?')
        datos = self.client.post(reverse('mensajes:enviar', args=[self.conversacion.pk]),
                                 {'texto': 'Sí, la página 40', 'responde_a': primero.pk}, HTTP_ACCEPT='application/json').json()
        self.assertEqual(datos['cita']['id'], primero.pk)
        self.assertEqual(datos['cita']['texto'], '¿Hay tarea de fracciones?')
        self.assertContains(self.pantalla(), 'burbuja__cita')

    def test_una_cita_de_otra_conversacion_se_ignora(self):
        otra = reglas.conversacion_con(self.p(self.marta), self.p(self.beto))
        ajeno = reglas.enviar(otra, self.p(self.marta), 'Hola Beto')
        mensaje = reglas.enviar(self.conversacion, self.p(self.marta), 'Hola Ana', responde_a=ajeno.pk)
        self.assertIsNone(mensaje.responde_a)


@PRUEBAS
class CorregirTests(Base):
    def editar(self, mensaje, texto, cliente=None, espacio='mensajes'):
        return (cliente or self.client).post(reverse(f'{espacio}:editar', args=[mensaje.pk]), {'texto': texto})

    def test_corrige_su_mensaje_en_los_primeros_minutos(self):
        mensaje = reglas.enviar(self.conversacion, self.p(self.marta), 'Mañana hay exmen')
        respuesta = self.editar(mensaje, 'Mañana hay examen')
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.json()['editado'])
        mensaje.refresh_from_db()
        self.assertEqual(mensaje.texto, 'Mañana hay examen')
        self.assertIsNotNone(mensaje.editado)
        self.assertContains(self.pantalla(self.ana_cliente, 'portal_estudiantes:mensajes'), 'editado')

    def test_pasados_dos_minutos_ya_no(self):
        mensaje = reglas.enviar(self.conversacion, self.p(self.marta), 'Texto')
        Mensaje.objects.filter(pk=mensaje.pk).update(creado=timezone.now() - timedelta(minutes=2, seconds=5))
        self.assertEqual(self.editar(mensaje, 'Otro').status_code, 400)
        mensaje.refresh_from_db()
        self.assertEqual(mensaje.texto, 'Texto')

    def test_no_corrige_lo_de_la_otra_persona(self):
        mensaje = reglas.enviar(self.conversacion, self.p(self.ana), 'Hola maestra')
        self.assertEqual(self.editar(mensaje, 'Cambiado').status_code, 400)

    def test_quien_no_es_de_la_conversacion_no_lo_encuentra(self):
        mensaje = reglas.enviar(self.conversacion, self.p(self.marta), 'Hola')
        self.client.force_login(self.raul)
        self.assertEqual(self.editar(mensaje, 'Cambiado').status_code, 404)

    def test_no_queda_vacio(self):
        mensaje = reglas.enviar(self.conversacion, self.p(self.marta), 'Hola')
        self.assertEqual(self.editar(mensaje, '   ').status_code, 400)


@PRUEBAS
class EscribiendoTests(Base):
    def test_avisa_solo_a_la_otra_persona(self):
        from . import tiempo_real
        with patch.object(tiempo_real, '_enviar') as enviar:
            tiempo_real.avisar_escribiendo(self.conversacion.pk, self.p(self.marta).pk, 'Marta')
        self.assertEqual([llamada.args[0] for llamada in enviar.call_args_list], [self.p(self.ana).pk])
        self.assertEqual(enviar.call_args.args[1]['type'], 'mensaje.escribiendo')


@PRUEBAS
class FamiliaEnLaListaTests(Base):
    def test_tutor_de_su_estudiante_con_grupo(self):
        from Alumnos.models import TutorAlumno
        TutorAlumno.objects.get_or_create(tutor=self.rosa, alumno=self.ana, defaults={'parentesco': 'MADRE'})
        texto = reglas.familias_de([self.rosa])[self.rosa.pk]
        self.assertTrue(texto.startswith('Tutor de Ana'), texto)
        self.assertIn('(', texto)

    def test_la_lista_y_el_encabezado_dicen_de_quien_es_tutor(self):
        con_rosa = reglas.conversacion_con(self.p(self.marta), self.p(self.rosa))
        reglas.enviar(con_rosa, self.p(self.rosa), 'Buenas tardes')
        pantalla = self.client.get(reverse('mensajes:conversacion', args=[con_rosa.pk]))
        self.assertContains(pantalla, 'chat-item__quien')
        self.assertContains(pantalla, 'Tutor de Ana', count=2)   # en la lista y bajo su nombre
