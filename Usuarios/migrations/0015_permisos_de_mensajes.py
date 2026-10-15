from django.contrib.auth.management import create_permissions
from django.db import migrations

# Mensajería interna (pedido del 2026-10-14). Los roles de arranque que ya existen reciben el módulo nuevo como lo
# recibirían al crearse (Usuarios/iniciales.py): todos usan la mensajería; Dirección, Control escolar y los roles de
# prefectura (en su alcance) además atienden a estudiantes y familias. El administrador ya tiene todo.
USAR, FAMILIAS = 'usar', 'contactar_familias'
POR_ROL = {
    'Dirección': (USAR, FAMILIAS),
    'Control escolar': (USAR, FAMILIAS),
    'Docente': (USAR,),
    'Coordinación académica': (USAR,),
    'Recepción': (USAR,),
}


def conceder_mensajes(apps, schema_editor):
    # Los permisos de los modelos nuevos se crean al terminar de migrar; aquí se necesitan ya
    mensajes = apps.get_app_config('Mensajes')
    original, mensajes.models_module = getattr(mensajes, 'models_module', None), True   # en el registro real, se restaura
    create_permissions(mensajes, verbosity=0, apps=apps)
    mensajes.models_module = original

    Permission = apps.get_model('auth', 'Permission')
    Group = apps.get_model('auth', 'Group')
    Rol = apps.get_model('Usuarios', 'Rol')
    permisos = {p.codename: p for p in Permission.objects.filter(content_type__app_label='Mensajes')}
    for nombre, codigos in POR_ROL.items():
        for grupo in Group.objects.filter(name=nombre):
            grupo.permissions.add(*(permisos[c] for c in codigos if c in permisos))
    for rol in Rol.objects.filter(es_prefectura=True, acceso_total=False).select_related('grupo'):
        rol.grupo.permissions.add(*(permisos[c] for c in (USAR, FAMILIAS) if c in permisos))


class Migration(migrations.Migration):

    dependencies = [
        ('Usuarios', '0014_bitacoras_niveles_y_permisos'),
        ('Mensajes', '0001_mensajeria'),
    ]

    operations = [
        migrations.RunPython(conceder_mensajes, migrations.RunPython.noop),
    ]
