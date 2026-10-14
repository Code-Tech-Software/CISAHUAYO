from django.contrib.auth.management import create_permissions
from django.db import migrations

# Los roles de arranque que ya existen reciben el módulo nuevo como lo recibirían al crearse (Usuarios/iniciales.py):
# Dirección, todo el módulo; Control escolar, consultar, registrar y editar la conducta. El administrador ya tiene todo.
REGISTRO = ('view_registroconducta', 'add_registroconducta', 'change_registroconducta')
# Los del catálogo de permisos (Usuarios/catalogo.py, módulo «Conducta»)
CATALOGO = (
    *(f'{accion}_{modelo}' for modelo in ('registroconducta', 'categoriaconducta', 'motivoconducta', 'medidadisciplinaria', 'motivosuspension')
      for accion in ('view', 'add', 'change', 'delete')),
    'view_reglareincidencia', 'change_reglareincidencia',
)


def conceder_conducta(apps, schema_editor):
    # Los permisos de los modelos nuevos se crean al terminar de migrar; aquí se necesitan ya
    conducta = apps.get_app_config('Conducta')
    original, conducta.models_module = getattr(conducta, 'models_module', None), True   # en el registro real, se restaura
    create_permissions(conducta, verbosity=0, apps=apps)
    conducta.models_module = original

    Permission = apps.get_model('auth', 'Permission')
    Group = apps.get_model('auth', 'Group')
    todos = list(Permission.objects.filter(content_type__app_label='Conducta', codename__in=CATALOGO))
    registro = [p for p in todos if p.codename in REGISTRO]
    for grupo in Group.objects.filter(name='Dirección'):
        grupo.permissions.add(*todos)
    for grupo in Group.objects.filter(name='Control escolar'):
        grupo.permissions.add(*registro)


class Migration(migrations.Migration):

    dependencies = [
        ('Usuarios', '0007_apariencia'),
        ('Conducta', '0001_initial'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(conceder_conducta, migrations.RunPython.noop),
    ]
