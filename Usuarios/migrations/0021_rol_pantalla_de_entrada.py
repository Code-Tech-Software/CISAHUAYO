from django.db import migrations

NOMBRE = 'Pantalla de entrada'
DESCRIPCION = 'Solo la pantalla de entrada: para la cuenta del equipo donde los estudiantes registran su entrada.'


def crear_rol(apps, schema_editor):
    """El rol de la cuenta del equipo de la entrada (pedido del 2026-10-27), solo con el permiso de usar la pantalla.

    En una instalación nueva lo crean los roles de arranque (Usuarios/iniciales.py) al terminar de migrar; aquí se crea en
    las que ya tenían sus roles. Si ya existe un rol con ese nombre no se toca."""
    Rol = apps.get_model('Usuarios', 'Rol')
    if not Rol.objects.filter(acceso_total=True).exists():
        return   # instalación nueva: lo crean los roles de arranque
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    if Group.objects.filter(name=NOMBRE).exists():
        return
    grupo = Group.objects.create(name=NOMBRE)
    Rol.objects.create(grupo=grupo, descripcion=DESCRIPCION, tono=5)
    permiso = Permission.objects.filter(content_type__app_label='Alumnos', codename='add_asistenciageneral').first()
    if permiso is not None:
        grupo.permissions.add(permiso)


class Migration(migrations.Migration):

    dependencies = [
        ('Usuarios', '0020_busqueda_sin_acentos'),
        ('Alumnos', '0031_asistencia_bitacora_avisos_y_ajustes'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(crear_rol, migrations.RunPython.noop),
    ]
