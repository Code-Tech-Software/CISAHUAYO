"""Grados consistentes (2026-10-26).

- `MateriaGrado.suspendida`: las materias que se desactivan al quitar su grupo o dar de baja su grado, para que vuelvan
  (con su profesor y su horario) si el grupo o el grado se reactivan.
- La equivalencia de cada grado queda guardada: los que no tenían toman la habitual de su nivel (la que ya se veía en
  todo el sitio), salvo que otro grado activo ya la tenga.
- Dos grados activos no pueden tener la misma equivalencia (restricción en la base). Si ya hubiera dos iguales, el
  segundo (en orden escolar) se queda sin equivalencia guardada para poder crearla; conviene corregirlo en Grados.
"""
from django.db import migrations, models

ORDEN = ('PREESCOLAR', 'PRIMARIA', 'SECUNDARIA', 'PREPARATORIA')
BASE = {'PRIMARIA': 0, 'SECUNDARIA': 6, 'PREPARATORIA': 9}
PREFIJO = {'PREESCOLAR': 'K'}


def sugerida(nivel, numero):
    """Copia de Alumnos.academico.equivalencia_sugerida (las migraciones no importan el código vivo)."""
    if not numero:
        return ''
    if nivel in PREFIJO:
        return f'{PREFIJO[nivel]}{numero}'
    base = BASE.get(nivel)
    return '' if base is None else str(base + numero)


def guardar_equivalencias(apps, schema_editor):
    Grado = apps.get_model('Alumnos', 'Grado')
    grados = sorted(Grado.objects.all(), key=lambda g: (ORDEN.index(g.nivel) if g.nivel in ORDEN else 9, g.numero))
    usadas = set()
    # Primero las ya guardadas de los activos (un repetido pierde la suya)
    for grado in grados:
        if grado.activo and grado.equivalencia:
            if grado.equivalencia in usadas:
                Grado.objects.filter(pk=grado.pk).update(equivalencia='')
                grado.equivalencia = ''
            else:
                usadas.add(grado.equivalencia)
    # Después, la habitual para los que no tienen (si está libre entre los activos)
    for grado in grados:
        if grado.equivalencia:
            continue
        propuesta = sugerida(grado.nivel, grado.numero)
        if propuesta and (not grado.activo or propuesta not in usadas):
            Grado.objects.filter(pk=grado.pk).update(equivalencia=propuesta)
            if grado.activo:
                usadas.add(propuesta)


class Migration(migrations.Migration):

    dependencies = [
        ('Alumnos', '0029_estado_del_ciclo'),
    ]

    operations = [
        migrations.AddField(
            model_name='materiagrado',
            name='suspendida',
            field=models.BooleanField(default=False, verbose_name='Quitada con su grupo o su grado'),
        ),
        migrations.AlterField(
            model_name='grado',
            name='equivalencia',
            field=models.CharField(blank=True, default='', help_text='Cómo se nombra el grado en la continuidad escolar, sin importar el nivel: un número (1.º de secundaria equivale al 7.º) o un código con letras (K1 para 1.º de preescolar).', max_length=8, verbose_name='Equivalencia'),
        ),
        migrations.RunPython(guardar_equivalencias, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='grado',
            constraint=models.UniqueConstraint(condition=models.Q(('activo', True), models.Q(('equivalencia', ''), _negated=True)), fields=('equivalencia',), name='equivalencia_unica_entre_grados_activos'),
        ),
    ]
