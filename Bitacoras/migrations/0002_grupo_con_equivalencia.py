"""El nombre del grupo guardado en cada bitácora, con la equivalencia del grado («7° A» en lugar de «1° A Secundaria»):
desde el 2026-10-20 así se nombran los grupos en todo el sitio, y las bitácoras de antes se verían distintas a las nuevas.
Solo cambia el texto; el grupo (y su grado y nivel) siguen siendo los mismos. Al revertir, vuelve el nombre por nivel."""
from django.db import migrations

BASE = {'PRIMARIA': 0, 'SECUNDARIA': 6, 'PREPARATORIA': 9}
PREFIJO = {'PREESCOLAR': 'K'}
NIVELES = {'PREESCOLAR': 'Preescolar', 'PRIMARIA': 'Primaria', 'SECUNDARIA': 'Secundaria', 'PREPARATORIA': 'Preparatoria'}


def _de_nivel(grupo):
    return f'{grupo.grado.numero}° {grupo.nombre.nombre} {NIVELES.get(grupo.grado.nivel, grupo.grado.nivel)}'


def _con_equivalencia(grupo):
    """Como Alumnos.models.Grupo.nombre_equivalente (con la equivalencia guardada o la habitual de su nivel)."""
    grado = grupo.grado
    codigo = grado.equivalencia
    if not codigo and grado.numero:
        if grado.nivel in PREFIJO:
            codigo = f'{PREFIJO[grado.nivel]}{grado.numero}'
        elif grado.nivel in BASE:
            codigo = str(BASE[grado.nivel] + grado.numero)
    if not codigo:
        return _de_nivel(grupo)
    return f'{codigo}° {grupo.nombre.nombre}' if codigo.isdigit() else f'{codigo} {grupo.nombre.nombre}'


def _renombrar(nombrar):
    def aplicar(apps, schema_editor):
        Entrada = apps.get_model('Bitacoras', 'EntradaBitacora')
        Grupo = apps.get_model('Alumnos', 'Grupo')
        ids = Entrada.objects.values_list('grupo', flat=True).distinct()
        for grupo in Grupo.objects.filter(pk__in=ids).select_related('grado', 'nombre'):
            Entrada.objects.filter(grupo=grupo).update(grupo_texto=nombrar(grupo)[:80])
    return aplicar


class Migration(migrations.Migration):

    dependencies = [
        ('Bitacoras', '0001_bitacoras_por_grupo'),
        ('Alumnos', '0026_foto_y_materias_de_profesor'),
    ]

    operations = [
        migrations.RunPython(_renombrar(_con_equivalencia), _renombrar(_de_nivel)),
    ]
