"""La base de demostración (Panel/demo, pedido del 2026-11-09): el comando solo corre con los ajustes de demostración,
para que nunca llene ni borre otra base."""
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings


class SembrarDemoTests(SimpleTestCase):
    def test_se_niega_fuera_de_los_ajustes_de_demostracion(self):
        with self.assertRaisesMessage(CommandError, 'settings_demo'):
            call_command('sembrar_demo')

    @override_settings(DEMO=True)
    def test_se_niega_con_otra_base_aunque_diga_ser_demostracion(self):
        with self.assertRaisesMessage(CommandError, 'settings_demo'):
            call_command('sembrar_demo')
