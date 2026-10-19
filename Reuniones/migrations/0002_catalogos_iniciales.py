from django.db import migrations

# Un punto de partida que el administrador edita en Ajustes › Reuniones (se pueden desactivar, renombrar u ordenar)
MOTIVOS = (
    'Desempeño académico',
    'Conducta y convivencia',
    'Asistencia y puntualidad',
    'Salud y bienestar',
    'Seguimiento de acuerdos',
    'Trámites y documentación',
    'Otro',
)
SALAS = (('Dirección', ''), ('Sala de juntas', ''), ('Coordinación académica', ''))


def crear(apps, schema_editor):
    Motivo = apps.get_model('Reuniones', 'MotivoReunion')
    Sala = apps.get_model('Reuniones', 'SalaReunion')
    Configuracion = apps.get_model('Reuniones', 'ConfiguracionReuniones')
    for orden, nombre in enumerate(MOTIVOS, start=1):
        Motivo.objects.get_or_create(nombre=nombre, defaults={'orden': orden * 10})
    for orden, (nombre, ubicacion) in enumerate(SALAS, start=1):
        Sala.objects.get_or_create(nombre=nombre, defaults={'orden': orden * 10, 'ubicacion': ubicacion})
    Configuracion.objects.get_or_create(pk=1)


class Migration(migrations.Migration):

    dependencies = [
        ('Reuniones', '0001_reuniones_con_familias'),
    ]

    operations = [
        migrations.RunPython(crear, migrations.RunPython.noop),
    ]
