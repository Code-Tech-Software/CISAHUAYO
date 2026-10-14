from django.contrib.auth.management import create_permissions
from django.db import migrations

# Control de calificaciones (pedido del 2026-10-14). Los roles de arranque que ya existen reciben el módulo nuevo como
# lo recibirían al crearse (Usuarios/iniciales.py): Docente captura y cierra sus materias; Dirección, todo el módulo;
# Control escolar, solo consulta. El administrador ya tiene todo.
DOCENTE = ('capturar', 'cerrar')
CONSULTA = ('ver_todas', 'view_configuracionevaluacion')
TODO = ('capturar', 'ver_todas', 'gestionar_todas', 'cerrar', 'reabrir',
        'view_configuracionevaluacion', 'add_configuracionevaluacion', 'change_configuracionevaluacion')


def conceder_calificaciones(apps, schema_editor):
    # Los permisos de los modelos nuevos se crean al terminar de migrar; aquí se necesitan ya
    calificaciones = apps.get_app_config('Calificaciones')
    original, calificaciones.models_module = getattr(calificaciones, 'models_module', None), True   # en el registro real, se restaura
    create_permissions(calificaciones, verbosity=0, apps=apps)
    calificaciones.models_module = original

    Permission = apps.get_model('auth', 'Permission')
    Group = apps.get_model('auth', 'Group')
    permisos = {p.codename: p for p in Permission.objects.filter(content_type__app_label='Calificaciones', codename__in=TODO)}
    for nombre, codigos in (('Docente', DOCENTE), ('Dirección', TODO), ('Control escolar', CONSULTA)):
        for grupo in Group.objects.filter(name=nombre):
            grupo.permissions.add(*(permisos[c] for c in codigos if c in permisos))


class Migration(migrations.Migration):

    dependencies = [
        ('Usuarios', '0012_justificar_solo_administrador_y_prefectura'),
        ('Calificaciones', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(conceder_calificaciones, migrations.RunPython.noop),
    ]
