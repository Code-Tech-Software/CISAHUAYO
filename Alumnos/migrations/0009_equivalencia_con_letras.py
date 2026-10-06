from django.db import migrations, models

# La equivalencia pasa de ser un número a un código corto (7, 10, K1): los números que ya estaban guardados se conservan
# como texto y los grados que no tenían equivalencia reciben la habitual. (Copia de las reglas de
# Alumnos.academico: una migración no debe depender del código actual.)
BASE_DE_EQUIVALENCIA = {'PRIMARIA': 0, 'SECUNDARIA': 6, 'PREPARATORIA': 9}
PREFIJO_DE_EQUIVALENCIA = {'PREESCOLAR': 'K'}


def llenar_equivalencias(apps, schema_editor):
    Grado = apps.get_model('Alumnos', 'Grado')
    for grado in Grado.objects.filter(equivalencia=''):
        if grado.nivel in PREFIJO_DE_EQUIVALENCIA:
            sugerida = f'{PREFIJO_DE_EQUIVALENCIA[grado.nivel]}{grado.numero}'
        elif grado.nivel in BASE_DE_EQUIVALENCIA:
            sugerida = str(BASE_DE_EQUIVALENCIA[grado.nivel] + grado.numero)
        else:
            continue
        grado.equivalencia = sugerida
        grado.save(update_fields=['equivalencia'])


class Migration(migrations.Migration):

    dependencies = [
        ('Alumnos', '0008_grado_equivalencia'),
    ]

    operations = [
        migrations.AlterField(
            model_name='grado',
            name='equivalencia',
            field=models.CharField(blank=True, default='', help_text='Cómo se nombra el grado en la continuidad escolar, sin importar el nivel: un número (1.° de secundaria equivale al 7.°) o un código con letras (K1 para 1.° de preescolar).', max_length=8, verbose_name='Equivalencia'),
        ),
        migrations.RunPython(llenar_equivalencias, migrations.RunPython.noop),
    ]
