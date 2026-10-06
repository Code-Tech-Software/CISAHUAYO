from django.db import migrations, models


def marcar_rol_docente(apps, schema_editor):
    """El rol de arranque «Docente» pasa a ser el rol para profesores (en una base nueva ya nace así)."""
    Rol = apps.get_model('Usuarios', 'Rol')
    Rol.objects.filter(grupo__name='Docente', acceso_total=False).update(es_docente=True)


class Migration(migrations.Migration):

    dependencies = [
        ('Usuarios', '0002_ver_asignaciones'),
    ]

    operations = [
        migrations.AddField(
            model_name='rol',
            name='es_docente',
            field=models.BooleanField(default=False, help_text='Las cuentas con este rol son de profesores: al crearlas se registra o se vincula su ficha de profesor.', verbose_name='rol para docentes'),
        ),
        migrations.RunPython(marcar_rol_docente, migrations.RunPython.noop),
    ]
