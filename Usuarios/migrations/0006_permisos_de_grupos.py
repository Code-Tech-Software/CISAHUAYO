from django.contrib.auth.management import create_permissions
from django.db import migrations

# Quien consulta los grados consulta también sus grupos y el catálogo de nombres; quien edita los grados (y con eso
# elige sus grupos) administra también el catálogo.
CONSULTA = ('view_grupo', 'view_nombregrupo')
GESTION = ('add_nombregrupo', 'change_nombregrupo', 'delete_nombregrupo')


def conceder_grupos(apps, schema_editor):
    # Los permisos de un modelo nuevo se crean al terminar de migrar; aquí se necesitan ya
    alumnos = apps.get_app_config('Alumnos')
    original, alumnos.models_module = getattr(alumnos, 'models_module', None), True   # en el registro real, se restaura
    create_permissions(alumnos, verbosity=0, apps=apps)
    alumnos.models_module = original

    Permission = apps.get_model('auth', 'Permission')
    Group = apps.get_model('auth', 'Group')
    permisos = {p.codename: p for p in Permission.objects.filter(content_type__app_label='Alumnos', codename__in=CONSULTA + GESTION)}
    consulta = [permisos[c] for c in CONSULTA if c in permisos]
    gestion = [permisos[c] for c in GESTION if c in permisos]
    for grupo in Group.objects.filter(permissions__content_type__app_label='Alumnos', permissions__codename='view_grado').distinct():
        grupo.permissions.add(*consulta)
    for grupo in Group.objects.filter(permissions__content_type__app_label='Alumnos', permissions__codename='change_grado').distinct():
        grupo.permissions.add(*consulta, *gestion)


class Migration(migrations.Migration):

    dependencies = [
        ('Usuarios', '0005_permisos_de_periodos'),
        ('Alumnos', '0020_grupos'),
    ]

    operations = [
        migrations.RunPython(conceder_grupos, migrations.RunPython.noop),
    ]
