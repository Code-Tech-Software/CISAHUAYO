from django.contrib.auth.management import create_permissions
from django.db import migrations

GESTION = ('add_periodo', 'change_periodo', 'delete_periodo')
# Quien consulta ciclos, grados u horarios también consulta los periodos de evaluación (los profesores necesitan saber
# cuándo pueden capturar); quien administra los ciclos escolares administra también sus periodos.
CONSULTAN = ('view_cicloescolar', 'view_grado', 'view_horariomateria')
ADMINISTRAN = ('change_cicloescolar',)


def conceder_periodos(apps, schema_editor):
    # Los permisos de un modelo nuevo se crean al terminar de migrar; aquí se necesitan ya
    alumnos = apps.get_app_config('Alumnos')
    alumnos.models_module = True
    create_permissions(alumnos, verbosity=0, apps=apps)
    alumnos.models_module = None

    Permission = apps.get_model('auth', 'Permission')
    Group = apps.get_model('auth', 'Group')
    permisos = {p.codename: p for p in Permission.objects.filter(content_type__app_label='Alumnos', content_type__model='periodo')}
    ver = permisos.get('view_periodo')
    if ver is None:
        return
    gestion = [permisos[codigo] for codigo in GESTION if codigo in permisos]
    for grupo in Group.objects.filter(permissions__content_type__app_label='Alumnos', permissions__codename__in=CONSULTAN).distinct():
        grupo.permissions.add(ver)
    for grupo in Group.objects.filter(permissions__content_type__app_label='Alumnos', permissions__codename__in=ADMINISTRAN).distinct():
        grupo.permissions.add(ver, *gestion)


class Migration(migrations.Migration):

    dependencies = [
        ('Usuarios', '0004_cambio_de_contrasena_opcional'),
        ('Alumnos', '0019_periodo'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(conceder_periodos, migrations.RunPython.noop),
    ]
