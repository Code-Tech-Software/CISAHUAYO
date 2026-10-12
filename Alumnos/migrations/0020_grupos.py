import re

import django.db.models.deletion
from django.db import migrations, models


def un_grupo_por_grado(apps, schema_editor):
    """Hasta ahora cada grado era un solo grupo: cada grado recibe el grupo «A» y todo lo suyo (inscripciones, materias
    del plan y recesos) pasa a ese grupo. Los recesos que se llamaban «Recreo…» pasan a llamarse «Receso…»."""
    NombreGrupo = apps.get_model('Alumnos', 'NombreGrupo')
    Grupo = apps.get_model('Alumnos', 'Grupo')
    Grado = apps.get_model('Alumnos', 'Grado')
    a, _ = NombreGrupo.objects.get_or_create(nombre='A', defaults={'orden': 1})
    for grado in Grado.objects.all():
        grupo, _ = Grupo.objects.get_or_create(grado=grado, nombre=a, defaults={'activo': True})
        for modelo in ('Inscripcion', 'MateriaGrado', 'Recreo'):
            apps.get_model('Alumnos', modelo).objects.filter(grado=grado, grupo__isnull=True).update(grupo=grupo)

    Recreo = apps.get_model('Alumnos', 'Recreo')
    for receso in Recreo.objects.filter(nombre__iregex=r'^recreo'):
        receso.nombre = re.sub(r'^recreo', lambda m: 'Receso' if m.group(0)[0].isupper() else 'receso', receso.nombre, flags=re.I)
        receso.save(update_fields=['nombre'])


class Migration(migrations.Migration):

    dependencies = [
        ('Alumnos', '0019_periodo'),
    ]

    operations = [
        migrations.CreateModel(
            name='NombreGrupo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=20, unique=True, verbose_name='Nombre')),
                ('orden', models.PositiveSmallIntegerField(default=0, verbose_name='Orden')),
                ('activo', models.BooleanField(default=True, verbose_name='Activo')),
            ],
            options={
                'verbose_name': 'Nombre de grupo',
                'verbose_name_plural': 'Nombres de grupo',
                'ordering': ['orden', 'nombre'],
            },
        ),
        migrations.CreateModel(
            name='Grupo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('activo', models.BooleanField(default=True, verbose_name='Activo')),
                ('grado', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='grupos', to='Alumnos.grado', verbose_name='Grado')),
                ('nombre', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='grupos', to='Alumnos.nombregrupo', verbose_name='Grupo')),
            ],
            options={
                'verbose_name': 'Grupo',
                'verbose_name_plural': 'Grupos',
                'constraints': [models.UniqueConstraint(fields=('grado', 'nombre'), name='grupo_grado_nombre_unico')],
            },
        ),
        migrations.RemoveConstraint(model_name='materiagrado', name='materia_grado_ciclo_unica'),
        migrations.AddField(
            model_name='inscripcion',
            name='grupo',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='inscripciones', to='Alumnos.grupo', verbose_name='Grupo'),
        ),
        migrations.AddField(
            model_name='materiagrado',
            name='grupo',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='materias_grupo', to='Alumnos.grupo', verbose_name='Grupo'),
        ),
        migrations.AddField(
            model_name='recreo',
            name='grupo',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='recreos', to='Alumnos.grupo', verbose_name='Grupo'),
        ),
        migrations.AlterField(
            model_name='recreo',
            name='nombre',
            field=models.CharField(default='Receso', max_length=40, verbose_name='Nombre'),
        ),
        migrations.AlterModelOptions(
            name='recreo',
            options={'ordering': ['dia_semana', 'hora_inicio'], 'verbose_name': 'Receso', 'verbose_name_plural': 'Recesos'},
        ),
        migrations.RunPython(un_grupo_por_grado, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='inscripcion',
            name='grupo',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='inscripciones', to='Alumnos.grupo', verbose_name='Grupo'),
        ),
        migrations.AlterField(
            model_name='materiagrado',
            name='grupo',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='materias_grupo', to='Alumnos.grupo', verbose_name='Grupo'),
        ),
        migrations.AlterField(
            model_name='recreo',
            name='grupo',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='recreos', to='Alumnos.grupo', verbose_name='Grupo'),
        ),
        migrations.AddConstraint(
            model_name='materiagrado',
            constraint=models.UniqueConstraint(fields=('ciclo', 'grupo', 'materia'), name='materia_grupo_ciclo_unica'),
        ),
    ]
