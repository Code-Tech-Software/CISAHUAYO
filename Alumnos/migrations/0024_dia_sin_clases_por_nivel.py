"""Días sin clases por nivel (pedido del 2026-10-14): cada día sin clases dice qué nivel no tiene clases.

Hasta ahora un día sin clases era de todo el colegio, así que cada uno queda registrado en los cuatro niveles.
"""
from django.db import migrations, models

NIVELES = ('PREESCOLAR', 'PRIMARIA', 'SECUNDARIA', 'PREPARATORIA')


def a_todos_los_niveles(apps, schema_editor):
    DiaNoLectivo = apps.get_model('Alumnos', 'DiaNoLectivo')
    DiaNoLectivo.objects.bulk_create([
        DiaNoLectivo(fecha=dia.fecha, nivel=nivel, motivo=dia.motivo)
        for dia in DiaNoLectivo.objects.filter(nivel=NIVELES[0])
        for nivel in NIVELES[1:]
    ])


def a_un_dia_por_fecha(apps, schema_editor):
    """De regreso, la fecha vuelve a ser única: se conserva un registro por fecha."""
    DiaNoLectivo = apps.get_model('Alumnos', 'DiaNoLectivo')
    vistas = set()
    for dia in DiaNoLectivo.objects.order_by('fecha', 'pk'):
        if dia.fecha in vistas:
            dia.delete()
        else:
            vistas.add(dia.fecha)


class Migration(migrations.Migration):

    dependencies = [
        ('Alumnos', '0023_limite_de_entrada_por_nivel'),
    ]

    operations = [
        migrations.AlterField(
            model_name='dianolectivo',
            name='fecha',
            field=models.DateField(verbose_name='Fecha'),
        ),
        migrations.AddField(
            model_name='dianolectivo',
            name='nivel',
            field=models.CharField(choices=[('PREESCOLAR', 'Preescolar'), ('PRIMARIA', 'Primaria'), ('SECUNDARIA', 'Secundaria'), ('PREPARATORIA', 'Preparatoria')], default='PREESCOLAR', max_length=20, verbose_name='Nivel'),
            preserve_default=False,
        ),
        migrations.RunPython(a_todos_los_niveles, a_un_dia_por_fecha),
        migrations.AddConstraint(
            model_name='dianolectivo',
            constraint=models.UniqueConstraint(fields=('fecha', 'nivel'), name='dia_sin_clases_por_nivel'),
        ),
    ]
