from django.db import migrations


def agregar_al_ciclo_actual(apps, schema_editor):
    """Una materia activa con grado se imparte en su grado: la que todavía no está en el plan del ciclo actual de su
    grado se agrega (sin profesor ni horario). Una que se había quitado a propósito de ese plan no se toca."""
    CicloEscolar = apps.get_model('Alumnos', 'CicloEscolar')
    Materia = apps.get_model('Alumnos', 'Materia')
    MateriaGrado = apps.get_model('Alumnos', 'MateriaGrado')
    ciclo = CicloEscolar.objects.filter(activo=True).order_by('-fecha_inicio').first()
    if ciclo is None:
        return
    ya_estan = set(MateriaGrado.objects.filter(ciclo=ciclo).values_list('materia_id', 'grado_id'))
    MateriaGrado.objects.bulk_create([
        MateriaGrado(ciclo=ciclo, grado_id=materia.grado_id, materia=materia)
        for materia in Materia.objects.filter(activa=True, grado__isnull=False, grado__activo=True)
        if (materia.pk, materia.grado_id) not in ya_estan
    ])


class Migration(migrations.Migration):

    dependencies = [
        ('Alumnos', '0016_materia_grado'),
    ]

    operations = [
        migrations.RunPython(agregar_al_ciclo_actual, migrations.RunPython.noop),
    ]
