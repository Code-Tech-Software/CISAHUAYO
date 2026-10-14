from django.contrib.auth.management import create_permissions
from django.db import migrations

# El rol «Prefectura» (pedido del 2026-10-13) con sus permisos de arranque: consultar, registrar, corregir lo propio,
# justificar, solicitar suspensiones, dar seguimiento y exportar. Corregir lo de otros y los casos cerrados es un permiso
# aparte que el administrador concede si quiere. En una base nueva lo crea Usuarios/iniciales.py.
# «Dirección» recibe el permiso de aprobar suspensiones y medidas (como lo recibiría al crearse: todo el módulo de conducta).
PREFECTURA = ('consultar', 'registrar', 'corregir', 'justificar', 'solicitar_suspension', 'dar_seguimiento', 'exportar')
DESCRIPCION = 'Estudiantes, asistencia, conducta y seguimiento de los niveles o grupos que se le asignen.'


def _permisos_de(apps, etiqueta):
    # Los permisos de los modelos nuevos se crean al terminar de migrar; aquí se necesitan ya
    configuracion = apps.get_app_config(etiqueta)
    original, configuracion.models_module = getattr(configuracion, 'models_module', None), True   # en el registro real, se restaura
    create_permissions(configuracion, verbosity=0, apps=apps)
    configuracion.models_module = original


def crear_prefectura(apps, schema_editor):
    _permisos_de(apps, 'Prefectura')
    _permisos_de(apps, 'Conducta')
    Permission = apps.get_model('auth', 'Permission')
    Group = apps.get_model('auth', 'Group')
    Rol = apps.get_model('Usuarios', 'Rol')

    aprobar = Permission.objects.filter(content_type__app_label='Conducta', codename='aprobar_suspension').first()
    if aprobar is not None:
        for grupo in Group.objects.filter(name='Dirección'):
            grupo.permissions.add(aprobar)

    # Solo en una base que ya tiene sus roles (en una nueva los crea Usuarios/iniciales.py al terminar de migrar)
    if not Rol.objects.filter(acceso_total=True).exists() or Group.objects.filter(name='Prefectura').exists():
        return
    grupo = Group.objects.create(name='Prefectura')
    Rol.objects.create(grupo=grupo, descripcion=DESCRIPCION, tono=6, es_prefectura=True)
    grupo.permissions.set(Permission.objects.filter(content_type__app_label='Prefectura', codename__in=PREFECTURA))


class Migration(migrations.Migration):

    dependencies = [
        ('Usuarios', '0009_rol_es_prefectura'),
        ('Prefectura', '0001_initial'),
        ('Conducta', '0002_aprobaciones_y_seguimiento'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(crear_prefectura, migrations.RunPython.noop),
    ]
