"""El estado del ciclo deja de depender de la fecha de inicio (2026-10-26).

Antes, un ciclo que no era el actual se veía «Cerrado» en cuanto llegaba su fecha de inicio, aunque nadie lo hubiera
marcado como actual todavía. Ahora se guarda cuándo y quién lo marcó como actual o lo cerró; «cerrado» es el que se
cerró (`cerrado_en`) o el que terminó sin haberse activado.

Los datos que ya hay:
- Si por error hubiera varios ciclos actuales, se queda el más reciente.
- Un ciclo que ya empezó, no ha terminado, no es el actual y antes se veía «Cerrado» se marca como cerrado, salvo que
  el actual sea uno anterior a él: ese es el caso que se corrige (todavía no se activa) y queda como próximo.
- Solo puede haber un ciclo actual (restricción en la base).
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.utils import timezone


def ordenar_estados(apps, schema_editor):
    CicloEscolar = apps.get_model('Alumnos', 'CicloEscolar')
    ahora, hoy = timezone.now(), timezone.localdate()

    actuales = list(CicloEscolar.objects.filter(activo=True).order_by('-fecha_inicio', '-pk'))
    for sobrante in actuales[1:]:
        CicloEscolar.objects.filter(pk=sobrante.pk).update(activo=False, cerrado_en=ahora)
    actual = actuales[0] if actuales else None

    en_curso = CicloEscolar.objects.filter(activo=False, cerrado_en__isnull=True, fecha_inicio__lte=hoy, fecha_fin__gte=hoy)
    for ciclo in en_curso:
        if actual is not None and actual.fecha_inicio < ciclo.fecha_inicio:
            continue   # todavía no se activa: sigue como próximo
        CicloEscolar.objects.filter(pk=ciclo.pk).update(cerrado_en=ahora)


class Migration(migrations.Migration):

    dependencies = [
        ('Alumnos', '0028_horarios_semanas_a_b'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='cicloescolar',
            name='activo',
            field=models.BooleanField(default=False, verbose_name='Es el ciclo actual'),
        ),
        migrations.AddField(
            model_name='cicloescolar',
            name='activado_en',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Marcado como actual el'),
        ),
        migrations.AddField(
            model_name='cicloescolar',
            name='activado_por',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+',
                                    to=settings.AUTH_USER_MODEL, verbose_name='Marcado como actual por'),
        ),
        migrations.AddField(
            model_name='cicloescolar',
            name='cerrado_en',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Cerrado el'),
        ),
        migrations.AddField(
            model_name='cicloescolar',
            name='cerrado_por',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+',
                                    to=settings.AUTH_USER_MODEL, verbose_name='Cerrado por'),
        ),
        migrations.RunPython(ordenar_estados, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='cicloescolar',
            constraint=models.UniqueConstraint(condition=models.Q(('activo', True)), fields=('activo',), name='un_solo_ciclo_actual'),
        ),
    ]
