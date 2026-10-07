import re
import unicodedata

from django.db import migrations, models


# Copia de Alumnos/utils.py (base_de_usuario): una migración no debe depender del código que cambie después
def _sin_acentos(texto):
    return ''.join(c for c in unicodedata.normalize('NFD', texto or '') if unicodedata.category(c) != 'Mn')


def _base_de_usuario(nombre, apellido_paterno):
    partes = []
    for texto in (nombre, apellido_paterno):
        palabras = (texto or '').split()
        palabra = re.sub(r'[^a-z0-9]', '', _sin_acentos(palabras[0]).lower()) if palabras else ''
        if palabra:
            partes.append(palabra)
    base = '.'.join(partes)
    if not re.search(r'[a-z]', base) or len(base) < 3:
        base = f'tutor.{base}' if base else 'tutor'
    return base[:36]


def asignar_usuarios(apps, schema_editor):
    """Cada tutor que ya existe recibe su usuario («maria.lopez», «maria.lopez2»…). La contraseña se asigna después,
    desde su perfil: aquí no se inventa ninguna."""
    Tutor = apps.get_model('Alumnos', 'Tutor')
    usados = set(Tutor.objects.exclude(usuario=None).values_list('usuario', flat=True))
    for tutor in Tutor.objects.filter(usuario=None).order_by('pk'):
        base = _base_de_usuario(tutor.nombre, tutor.apellido_paterno)
        candidato, numero = base, 1
        while candidato in usados:
            numero += 1
            candidato = f'{base}{numero}'
        usados.add(candidato)
        Tutor.objects.filter(pk=tutor.pk).update(usuario=candidato)


class Migration(migrations.Migration):

    dependencies = [
        ('Alumnos', '0011_estudiante_acceso_y_catalogos'),
    ]

    operations = [
        migrations.AddField(
            model_name='tutor',
            name='contrasena',
            field=models.CharField(blank=True, default='', max_length=128, verbose_name='Contraseña'),
        ),
        migrations.AddField(
            model_name='tutor',
            name='contrasena_visible',
            field=models.CharField(blank=True, default='', editable=False, max_length=64, verbose_name='Contraseña (consulta)'),
        ),
        migrations.AddField(
            model_name='tutor',
            name='usuario',
            field=models.CharField(blank=True, max_length=40, null=True, unique=True, verbose_name='Usuario'),
        ),
        migrations.RunPython(asignar_usuarios, migrations.RunPython.noop),
    ]
