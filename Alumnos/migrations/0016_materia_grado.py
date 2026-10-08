from collections import defaultdict

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q
from django.utils import timezone


def grado_de_cada_materia(apps, schema_editor):
    """Cada materia ya registrada toma el grado en el que se imparte: el único de su plan o, si estuvo en varios, el
    único en el que se imparte en el ciclo actual o en uno próximo. Si sigue en varios, se queda sin grado y se elige
    al editarla."""
    Materia = apps.get_model('Alumnos', 'Materia')
    MateriaGrado = apps.get_model('Alumnos', 'MateriaGrado')
    todos, vigentes = defaultdict(set), defaultdict(set)
    vigente = Q(activa=True) & (Q(ciclo__activo=True) | Q(ciclo__fecha_inicio__gt=timezone.localdate()))
    for materia_id, grado_id in MateriaGrado.objects.order_by().values_list('materia_id', 'grado_id'):
        todos[materia_id].add(grado_id)
    for materia_id, grado_id in MateriaGrado.objects.filter(vigente).order_by().values_list('materia_id', 'grado_id'):
        vigentes[materia_id].add(grado_id)
    for materia_id, grados in todos.items():
        elegidos = grados if len(grados) == 1 else vigentes[materia_id]
        if len(elegidos) == 1:
            Materia.objects.filter(pk=materia_id).update(grado_id=next(iter(elegidos)))


class Migration(migrations.Migration):

    dependencies = [
        ('Alumnos', '0015_inscripcion_suspendida_por_baja'),
    ]

    operations = [
        migrations.AddField(
            model_name='materia',
            name='grado',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='materias',
                to='Alumnos.grado', verbose_name='Grado',
            ),
        ),
        migrations.RunPython(grado_de_cada_materia, migrations.RunPython.noop),
    ]
