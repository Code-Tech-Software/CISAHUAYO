from django.contrib.auth.management import create_permissions
from django.db import migrations, models

# Bitácoras por grupo (pedido del 2026-10-14). Los roles de arranque que ya existen reciben el módulo nuevo como lo
# recibirían al crearse (Usuarios/iniciales.py): Docente registra en sus clases; Dirección, todo el módulo; los roles de
# prefectura consultan y registran en su alcance. Se agrega el rol «Coordinación académica» (sus niveles se eligen en la ficha de
# cada cuenta). El administrador ya tiene todo.
DOCENTE = ('registrar',)
DIRECCION = ('registrar', 'consultar_todas', 'registrar_todas', 'gestionar')
PREFECTURA = ('consultar_todas', 'registrar_todas')
COORDINACION = 'Coordinación académica'
COORDINACION_ALUMNOS = ('view_alumno', 'view_grado', 'view_grupo', 'view_horariomateria', 'view_materia', 'view_materiagrado',
                        'view_nombregrupo', 'view_periodo')


def conceder_bitacoras(apps, schema_editor):
    # Los permisos de los modelos nuevos se crean al terminar de migrar; aquí se necesitan ya
    bitacoras = apps.get_app_config('Bitacoras')
    original, bitacoras.models_module = getattr(bitacoras, 'models_module', None), True   # en el registro real, se restaura
    create_permissions(bitacoras, verbosity=0, apps=apps)
    bitacoras.models_module = original

    Permission = apps.get_model('auth', 'Permission')
    Group = apps.get_model('auth', 'Group')
    Rol = apps.get_model('Usuarios', 'Rol')
    permisos = {p.codename: p for p in Permission.objects.filter(content_type__app_label='Bitacoras')}
    for nombre, codigos in (('Docente', DOCENTE), ('Dirección', DIRECCION)):
        for grupo in Group.objects.filter(name=nombre):
            grupo.permissions.add(*(permisos[c] for c in codigos if c in permisos))
    for rol in Rol.objects.filter(es_prefectura=True, acceso_total=False).select_related('grupo'):
        rol.grupo.permissions.add(*(permisos[c] for c in PREFECTURA if c in permisos))

    # «Coordinación académica», solo si el sistema ya arrancó con sus roles y todavía no existe uno con ese nombre
    if Rol.objects.filter(acceso_total=True).exists() and not Group.objects.filter(name=COORDINACION).exists():
        grupo = Group.objects.create(name=COORDINACION)
        Rol.objects.create(grupo=grupo, tono=1, descripcion='Bitácoras por grupo de los niveles que coordina (se eligen en su ficha); '
                                                         'consulta estudiantes, grupos, materias y horarios.')
        de_alumnos = Permission.objects.filter(content_type__app_label='Alumnos', codename__in=COORDINACION_ALUMNOS)
        grupo.permissions.add(*de_alumnos, *(permisos[c] for c in PREFECTURA if c in permisos))


class Migration(migrations.Migration):

    dependencies = [
        ('Usuarios', '0013_permisos_de_calificaciones'),
        ('Bitacoras', '0001_bitacoras_por_grupo'),
    ]

    operations = [
        migrations.AddField(
            model_name='perfilusuario',
            name='niveles_bitacora',
            field=models.JSONField(blank=True, default=list, help_text='Limita las bitácoras de todos los grupos a estos niveles (vacío: todo el colegio).', verbose_name='niveles que coordina'),
        ),
        migrations.RunPython(conceder_bitacoras, migrations.RunPython.noop),
    ]
