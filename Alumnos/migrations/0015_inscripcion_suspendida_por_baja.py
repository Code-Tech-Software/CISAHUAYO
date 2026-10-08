from django.db import migrations, models
from django.db.models import Q
from django.utils import timezone


def suspender_las_de_quien_ya_estaba_de_baja(apps, schema_editor):
    """Corrige lo que quedó de antes: un estudiante dado de baja con su inscripción del ciclo actual (o de uno próximo)
    todavía activa. Esas inscripciones se desactivan con la marca, para que vuelvan si se le reactiva."""
    Inscripcion = apps.get_model('Alumnos', 'Inscripcion')
    vigentes = Q(ciclo__activo=True) | Q(ciclo__fecha_inicio__gt=timezone.localdate())
    Inscripcion.objects.filter(vigentes, alumno__estatus='BAJA', activa=True).update(activa=False, suspendida_por_baja=True)


class Migration(migrations.Migration):

    dependencies = [
        ('Alumnos', '0014_profesor_niveles'),
    ]

    operations = [
        migrations.AddField(
            model_name='inscripcion',
            name='suspendida_por_baja',
            field=models.BooleanField(default=False, editable=False, verbose_name='Desactivada por la baja del estudiante'),
        ),
        migrations.RunPython(suspender_las_de_quien_ya_estaba_de_baja, migrations.RunPython.noop),
    ]
