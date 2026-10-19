from django.contrib.auth.management import create_permissions
from django.db import migrations

# Reuniones con familias (pedido del 2026-10-19). Los roles de arranque que ya existen reciben el módulo nuevo como lo
# recibirían al crearse (Usuarios/iniciales.py): Dirección, Coordinación académica y los roles de prefectura gestionan y
# acompañan las reuniones de sus niveles (y ven sus notas confidenciales); Control escolar y Recepción atienden las
# llamadas de todo el colegio (registrar y programar, sin notas confidenciales); los docentes ven y confirman las
# reuniones en que participan. Ver todo el colegio y configurar es exclusivo del administrador, que ya tiene todo.
PARTICIPAR, REGISTRAR, GESTIONAR, ACOMPANAR, CONFIDENCIAL = 'participar', 'registrar', 'gestionar', 'acompanar', 'confidencial'
DIRECTIVOS = (PARTICIPAR, GESTIONAR, ACOMPANAR, CONFIDENCIAL)
POR_ROL = {
    'Dirección': DIRECTIVOS,
    'Coordinación académica': DIRECTIVOS,
    'Control escolar': (REGISTRAR,),
    'Recepción': (REGISTRAR,),
}


def conceder_reuniones(apps, schema_editor):
    # Los permisos de los modelos nuevos se crean al terminar de migrar; aquí se necesitan ya
    reuniones = apps.get_app_config('Reuniones')
    original, reuniones.models_module = getattr(reuniones, 'models_module', None), True   # en el registro real, se restaura
    create_permissions(reuniones, verbosity=0, apps=apps)
    reuniones.models_module = original

    Permission = apps.get_model('auth', 'Permission')
    Group = apps.get_model('auth', 'Group')
    Rol = apps.get_model('Usuarios', 'Rol')
    permisos = {p.codename: p for p in Permission.objects.filter(content_type__app_label='Reuniones')}
    for nombre, codigos in POR_ROL.items():
        for grupo in Group.objects.filter(name=nombre):
            grupo.permissions.add(*(permisos[c] for c in codigos if c in permisos))
    for rol in Rol.objects.filter(es_prefectura=True, acceso_total=False).select_related('grupo'):
        rol.grupo.permissions.add(*(permisos[c] for c in DIRECTIVOS if c in permisos))
    for rol in Rol.objects.filter(es_docente=True, acceso_total=False).select_related('grupo'):
        rol.grupo.permissions.add(*(permisos[c] for c in (PARTICIPAR,) if c in permisos))


class Migration(migrations.Migration):

    dependencies = [
        ('Usuarios', '0018_retiros_niveles_y_permisos'),
        ('Reuniones', '0002_catalogos_iniciales'),
    ]

    operations = [
        migrations.RunPython(conceder_reuniones, migrations.RunPython.noop),
    ]
