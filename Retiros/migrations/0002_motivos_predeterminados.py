from django.db import migrations

# Los motivos con que arranca el catálogo (pedido del 2026-10-17). El administrador los edita, ordena y desactiva en
# Ajustes › Retiros. «Otro» pide que el tutor explique.
MOTIVOS = (
    ('Cita médica', 10, False),
    ('Trámite personal', 20, False),
    ('Situación familiar', 30, False),
    ('Otro', 40, True),
)


def crear_motivos(apps, schema_editor):
    MotivoRetiro = apps.get_model('Retiros', 'MotivoRetiro')
    for nombre, orden, requiere in MOTIVOS:
        MotivoRetiro.objects.get_or_create(nombre=nombre, defaults={'orden': orden, 'requiere_explicacion': requiere})


class Migration(migrations.Migration):

    dependencies = [
        ('Retiros', '0001_retiros'),
    ]

    operations = [
        migrations.RunPython(crear_motivos, migrations.RunPython.noop),
    ]
