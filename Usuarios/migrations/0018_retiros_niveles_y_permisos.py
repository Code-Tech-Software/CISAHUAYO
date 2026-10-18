from django.contrib.auth.management import create_permissions
from django.db import migrations, models

# Retiros anticipados (pedido del 2026-10-17). Los roles de arranque que ya existen reciben el módulo nuevo como lo
# recibirían al crearse (Usuarios/iniciales.py): Dirección consulta, confirma salidas, cancela y corrige; los roles de
# prefectura consultan y confirman las salidas de su alcance. Ver todo el colegio y configurar los motivos es exclusivo
# del administrador, que ya tiene todo. Cada cuenta que no es de prefectura necesita sus «Niveles para retiros».
CONSULTAR, CONFIRMAR, CORREGIR = 'consultar', 'confirmar', 'corregir'
POR_ROL = {
    'Dirección': (CONSULTAR, CONFIRMAR, CORREGIR),
}
DE_PREFECTURA = (CONSULTAR, CONFIRMAR)


def conceder_retiros(apps, schema_editor):
    # Los permisos de los modelos nuevos se crean al terminar de migrar; aquí se necesitan ya
    retiros = apps.get_app_config('Retiros')
    original, retiros.models_module = getattr(retiros, 'models_module', None), True   # en el registro real, se restaura
    create_permissions(retiros, verbosity=0, apps=apps)
    retiros.models_module = original

    Permission = apps.get_model('auth', 'Permission')
    Group = apps.get_model('auth', 'Group')
    Rol = apps.get_model('Usuarios', 'Rol')
    permisos = {p.codename: p for p in Permission.objects.filter(content_type__app_label='Retiros')}
    for nombre, codigos in POR_ROL.items():
        for grupo in Group.objects.filter(name=nombre):
            grupo.permissions.add(*(permisos[c] for c in codigos if c in permisos))
    for rol in Rol.objects.filter(es_prefectura=True, acceso_total=False).select_related('grupo'):
        rol.grupo.permissions.add(*(permisos[c] for c in DE_PREFECTURA if c in permisos))


class Migration(migrations.Migration):

    dependencies = [
        ('Usuarios', '0017_comunicados_niveles_y_permisos'),
        ('Retiros', '0001_retiros'),
    ]

    operations = [
        migrations.AddField(
            model_name='perfilusuario',
            name='niveles_retiros',
            field=models.JSONField(blank=True, default=list, help_text='Consulta y atiende los retiros anticipados de los estudiantes de estos niveles (si su rol tiene el permiso).', verbose_name='niveles para retiros'),
        ),
        migrations.RunPython(conceder_retiros, migrations.RunPython.noop),
    ]
