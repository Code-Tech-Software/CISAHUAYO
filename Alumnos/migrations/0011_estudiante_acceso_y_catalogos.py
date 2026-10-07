import unicodedata

from django.db import migrations, models

# La lista de religiones de Alumno.RELIGION_CHOICES (copiada: una migración no debe depender del código que cambie después)
RELIGIONES = (
    'Católica', 'Cristiana', 'Evangélica', 'Iglesia de Jesucristo de los Santos de los Últimos Días',
    'Musulmana', 'Judía', 'Budista', 'Hinduista', 'Otra',
)


def _clave(texto):
    sin_acentos = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    return ' '.join(sin_acentos.lower().split())


def normalizar_religiones(apps, schema_editor):
    """«Catolico», «cristiano»… pasan a la forma de la lista («Católica», «Cristiana»). Lo que no se reconoce no se toca."""
    Alumno = apps.get_model('Alumnos', 'Alumno')
    conocidas = {_clave(religion): religion for religion in RELIGIONES}
    for valor in list(Alumno.objects.exclude(religion='').values_list('religion', flat=True).distinct()):
        clave = _clave(valor)
        candidatas = [clave, clave[:-1] + 'a' if clave.endswith('o') else None, clave + 'a' if clave.endswith('n') else None]
        nueva = next((conocidas[c] for c in candidatas if c in conocidas), None)
        if nueva and nueva != valor:
            Alumno.objects.filter(religion=valor).update(religion=nueva)


class Migration(migrations.Migration):

    dependencies = [
        ('Alumnos', '0010_profesores_y_materias'),
    ]

    operations = [
        # La contraseña consultable queda vacía en los estudiantes que ya existen: solo se conocía su cifrado.
        migrations.AddField(
            model_name='alumno',
            name='contrasena_visible',
            field=models.CharField(blank=True, default='', editable=False, max_length=64, verbose_name='Contraseña (consulta)'),
        ),
        # Ya no se ofrece «Otro» en el sexo
        migrations.AlterField(
            model_name='alumno',
            name='sexo',
            field=models.CharField(choices=[('M', 'Masculino'), ('F', 'Femenino')], max_length=1, verbose_name='Sexo'),
        ),
        migrations.RunPython(normalizar_religiones, migrations.RunPython.noop),
    ]
