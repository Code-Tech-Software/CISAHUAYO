from django.db import migrations

# Justificar faltas es solo del administrador y de prefectura (pedido del 2026-10-14). Se quita a los demás roles:
# justificar desde Asistencias (crear, editar y anular justificaciones) solo lo conserva el rol de acceso total, y
# justificar desde Prefectura, solo los roles de prefectura. Lo mismo con los permisos puestos directamente a una cuenta
# (que no sea de superusuario). Las descripciones de arranque que hablaban de justificaciones se ajustan si nadie las cambió.
DEL_ADMINISTRADOR = ('add_justificacion', 'change_justificacion', 'delete_justificacion')   # app Alumnos
DE_PREFECTURA = ('justificar',)                                                            # app Prefectura
DESCRIPCIONES = {
    'Altas y cambios de estudiantes, tutores e inscripciones; consulta del resto y justificaciones.':
        'Altas y cambios de estudiantes, tutores e inscripciones; consulta del resto.',
    'Pantalla de entrada, asistencia del día y justificaciones.':
        'Pantalla de entrada y asistencia del día; consulta las justificaciones.',
}


def quitar_justificar(apps, schema_editor):
    Permission = apps.get_model('auth', 'Permission')
    Rol = apps.get_model('Usuarios', 'Rol')
    User = apps.get_model('auth', 'User')
    del_administrador = list(Permission.objects.filter(content_type__app_label='Alumnos', codename__in=DEL_ADMINISTRADOR))
    de_prefectura = list(Permission.objects.filter(content_type__app_label='Prefectura', codename__in=DE_PREFECTURA))

    for rol in Rol.objects.filter(acceso_total=False).select_related('grupo'):
        rol.grupo.permissions.remove(*del_administrador)
        if not rol.es_prefectura:
            rol.grupo.permissions.remove(*de_prefectura)
        nueva = DESCRIPCIONES.get(rol.descripcion)
        if nueva:
            rol.descripcion = nueva
            rol.save(update_fields=['descripcion'])

    for usuario in User.objects.filter(is_superuser=False):
        usuario.user_permissions.remove(*del_administrador, *de_prefectura)


class Migration(migrations.Migration):

    dependencies = [
        ('Usuarios', '0011_niveles_que_dirige'),
        ('Prefectura', '0001_initial'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(quitar_justificar, migrations.RunPython.noop),
    ]
