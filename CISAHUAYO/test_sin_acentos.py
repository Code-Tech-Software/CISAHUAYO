from django.test import TestCase

from Agenda.models import EventoAgenda


class BusquedaSinAcentosTests(TestCase):
    def setUp(self):
        EventoAgenda.objects.create(titulo='Excursión al museo', alcance='COLEGIO',
                                    fecha_inicio='2026-11-03', fecha_fin='2026-11-03')

    def test_sin_acento_encuentra_con_acento(self):
        self.assertTrue(EventoAgenda.objects.filter(titulo__icontains='excursion').exists())

    def test_con_acento_y_mayusculas(self):
        self.assertTrue(EventoAgenda.objects.filter(titulo__icontains='MUSÉO').exists())

    def test_no_encuentra_lo_que_no_hay(self):
        self.assertFalse(EventoAgenda.objects.filter(titulo__icontains='excursiones').exists())
