from django.db import migrations


def crear_unaccent(apps, schema_editor):
    # Solo PostgreSQL: en SQLite la función UNACCENT se registra en cada conexión (CISAHUAYO/sin_acentos.py)
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('CREATE EXTENSION IF NOT EXISTS unaccent')


class Migration(migrations.Migration):

    dependencies = [
        ('Usuarios', '0019_reuniones_permisos'),
    ]

    operations = [
        migrations.RunPython(crear_unaccent, migrations.RunPython.noop),
    ]
