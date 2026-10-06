from django.db import migrations

# El tablero de asignaciones se abre con «ver» el plan de materias (Alumnos.view_materiagrado), un permiso que antes no
# se podía conceder desde «Roles y permisos». Los roles que ya trabajaban con las materias lo reciben para no perder
# esa pantalla; en una base nueva todavía no hay roles y los predeterminados ya lo traen del catálogo.
RELACIONADOS = ('view_materia', 'add_materiagrado', 'change_materiagrado', 'delete_materiagrado')


def conceder_ver_el_plan(apps, schema_editor):
    Permission = apps.get_model('auth', 'Permission')
    Group = apps.get_model('auth', 'Group')
    ver = Permission.objects.filter(content_type__app_label='Alumnos', codename='view_materiagrado').first()
    if ver is None:
        return
    relacionados = Permission.objects.filter(content_type__app_label='Alumnos', codename__in=RELACIONADOS)
    for grupo in Group.objects.filter(permissions__in=relacionados).distinct():
        grupo.permissions.add(ver)


class Migration(migrations.Migration):

    dependencies = [
        ('Usuarios', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(conceder_ver_el_plan, migrations.RunPython.noop),
    ]
