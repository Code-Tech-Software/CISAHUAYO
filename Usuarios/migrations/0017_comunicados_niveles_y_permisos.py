from django.contrib.auth.management import create_permissions
from django.db import migrations, models

# Comunicados (pedido del 2026-10-16). Los roles de arranque que ya existen reciben el módulo nuevo como lo recibirían al
# crearse (Usuarios/iniciales.py): Dirección, todo menos la gestión global (exclusiva del administrador); Coordinación
# académica envía a los niveles que coordina; Docente consulta lo que recibe. Además, todo rol que ya tenga una cuenta de
# profesor puede consultar lo recibido (si no, ese profesor no tendría dónde leerlo). El administrador ya tiene todo.
RECIBIR, SEGUIMIENTO, ENVIAR, ELIMINAR = 'recibir', 'seguimiento', 'enviar', 'eliminar'
POR_ROL = {
    'Dirección': (RECIBIR, SEGUIMIENTO, ENVIAR, ELIMINAR),
    'Coordinación académica': (RECIBIR, SEGUIMIENTO, ENVIAR),
    'Docente': (RECIBIR,),
}


def conceder_comunicados(apps, schema_editor):
    # Los permisos de los modelos nuevos se crean al terminar de migrar; aquí se necesitan ya
    comunicados = apps.get_app_config('Comunicados')
    original, comunicados.models_module = getattr(comunicados, 'models_module', None), True   # en el registro real, se restaura
    create_permissions(comunicados, verbosity=0, apps=apps)
    comunicados.models_module = original

    Permission = apps.get_model('auth', 'Permission')
    Group = apps.get_model('auth', 'Group')
    Rol = apps.get_model('Usuarios', 'Rol')
    Profesor = apps.get_model('Alumnos', 'Profesor')
    permisos = {p.codename: p for p in Permission.objects.filter(content_type__app_label='Comunicados')}
    for nombre, codigos in POR_ROL.items():
        for grupo in Group.objects.filter(name=nombre):
            grupo.permissions.add(*(permisos[c] for c in codigos if c in permisos))
    if RECIBIR not in permisos:
        return
    cuentas_de_profesores = Profesor.objects.filter(usuario__isnull=False).values('usuario')
    roles = Rol.objects.filter(acceso_total=False).filter(
        models.Q(es_docente=True) | models.Q(grupo__user__in=cuentas_de_profesores)).select_related('grupo').distinct()
    for rol in roles:
        rol.grupo.permissions.add(permisos[RECIBIR])


class Migration(migrations.Migration):

    dependencies = [
        ('Usuarios', '0016_contrasena_visible'),
        ('Comunicados', '0001_comunicados'),
        ('Alumnos', '0025_acceso_a_los_portales'),
    ]

    operations = [
        migrations.AddField(
            model_name='perfilusuario',
            name='niveles_comunicados',
            field=models.JSONField(blank=True, default=list, help_text='Puede enviar comunicados a los tutores, estudiantes y profesores de estos niveles (si su rol tiene el permiso).', verbose_name='niveles para comunicados'),
        ),
        migrations.RunPython(conceder_comunicados, migrations.RunPython.noop),
    ]
