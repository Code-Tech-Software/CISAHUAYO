from django.db import migrations, models

# Equivalencia habitual en la continuidad escolar (sin importar el nivel): primaria 1.° a 6.°, secundaria 7.° a 9.°,
# preparatoria del 10.° en adelante. Preescolar no entra en la numeración. Es solo el punto de partida: cada grado
# conserva la suya y se puede cambiar desde el formulario del grado. (Copia de Alumnos.academico.BASE_DE_EQUIVALENCIA:
# una migración no debe depender del código actual.)
BASE_DE_EQUIVALENCIA = {'PRIMARIA': 0, 'SECUNDARIA': 6, 'PREPARATORIA': 9}


def llenar_equivalencias(apps, schema_editor):
    Grado = apps.get_model('Alumnos', 'Grado')
    for grado in Grado.objects.filter(equivalencia__isnull=True):
        base = BASE_DE_EQUIVALENCIA.get(grado.nivel)
        if base is not None:
            grado.equivalencia = base + grado.numero
            grado.save(update_fields=['equivalencia'])


class Migration(migrations.Migration):

    dependencies = [
        ('Alumnos', '0007_estudiante_etiquetas'),
    ]

    operations = [
        migrations.AddField(
            model_name='grado',
            name='equivalencia',
            field=models.PositiveSmallIntegerField(blank=True, help_text='Lugar del grado en la continuidad escolar, sin importar el nivel: 1.° de secundaria equivale al 7.°.', null=True, verbose_name='Equivalencia'),
        ),
        migrations.RunPython(llenar_equivalencias, migrations.RunPython.noop),
    ]
