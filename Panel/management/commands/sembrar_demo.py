"""python manage.py sembrar_demo --settings=CISAHUAYO.settings_demo

Deja `demo.sqlite3` como un colegio ficticio listo para una demostración (Panel/demo/sembrar.py): borra la base de
demostración y sus archivos, la vuelve a crear con las migraciones y la llena. Se puede repetir las veces que haga
falta. Las cuentas y la contraseña quedan en `demo_cuentas.txt` (fuera de git).

Solo funciona con los ajustes de demostración: con cualquier otra base se niega, para nunca tocar la de producción.
"""
import secrets
import shutil
import time
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = 'Crea la base de demostración (demo.sqlite3) con un colegio ficticio. Solo con --settings=CISAHUAYO.settings_demo.'

    def add_arguments(self, parser):
        parser.add_argument('--contrasena', default='', help='Contraseña de todas las cuentas de la demostración (si no, se genera una).')
        parser.add_argument('--semilla', type=int, default=2026, help='Cambia los nombres y los datos que se generan.')

    def handle(self, *args, **opciones):
        base = Path(settings.DATABASES['default']['NAME'])
        if not getattr(settings, 'DEMO', False) or connection.vendor != 'sqlite' or base.name != 'demo.sqlite3':
            raise CommandError('Solo se usa con los ajustes de demostración: python manage.py sembrar_demo --settings=CISAHUAYO.settings_demo')
        contrasena = opciones['contrasena'] or f'Demo-{secrets.token_urlsafe(6)}'
        inicio = time.monotonic()

        self.stdout.write('Borrando la demostración anterior…')
        connection.close()
        for sufijo in ('', '-wal', '-shm', '-journal'):
            try:
                Path(f'{base}{sufijo}').unlink(missing_ok=True)
            except PermissionError:
                raise CommandError('La base de demostración está abierta: detén el servidor de la demostración y vuelve a correr el comando.') from None
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)
        self.stdout.write('Creando la base (migraciones)…')
        call_command('migrate', verbosity=0)

        from Panel.demo.sembrar import Demo
        demo = Demo(self.stdout.write, contrasena, opciones['semilla'])
        conteo = demo.todo()
        self._cuentas(demo, contrasena)

        self.stdout.write(self.style.SUCCESS(f'Listo en {round(time.monotonic() - inicio)} s.'))
        for clave, valor in conteo.items():
            self.stdout.write(f'  {clave}: {valor}')
        self.stdout.write('Las cuentas y la contraseña están en demo_cuentas.txt. Para abrir la demostración:')
        self.stdout.write('  python manage.py runserver --settings=CISAHUAYO.settings_demo')

    def _cuentas(self, demo, contrasena):
        lineas = [
            'CISAHUAYO · Cuentas de la demostración (datos ficticios; base demo.sqlite3)',
            '',
            f'Contraseña de todas las cuentas: {contrasena}',
            'Abrir: python manage.py runserver --settings=CISAHUAYO.settings_demo  →  http://127.0.0.1:8000/',
            '',
            'Personal (pestaña «Sistema» del inicio de sesión):',
        ]
        lineas += [f'  {usuario:<22} {rol:<24} {quien}' for usuario, rol, quien in demo.cuentas]
        lineas += ['', 'Portales (pestañas «Estudiantes» y «Tutores»): todos los estudiantes de secundaria y bachillerato y las mamás tienen acceso. Ejemplos:']
        lineas += [f'  {tipo:<11} {acceso:<50} {quien}' for tipo, acceso, quien in demo.portales]
        lineas += ['', 'Para el sistema y un portal a la vez: uno en http://localhost:8000/ y el otro en http://127.0.0.1:8000/.']
        Path(settings.BASE_DIR, 'demo_cuentas.txt').write_text('\n'.join(lineas) + '\n', encoding='utf-8')
