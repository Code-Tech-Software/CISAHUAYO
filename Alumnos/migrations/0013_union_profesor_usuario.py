from django.db import migrations


class Migration(migrations.Migration):
    """Une las dos ramas que salieron de la 0010.

    `0011_profesor_usuario` (la cuenta de acceso del profesor) se había quitado del código, pero la base de desarrollo ya
    la tenía aplicada: se recupera con el mismo nombre para que esa base no intente crear otra vez la columna, y esta
    migración solo junta ese camino con el de los estudiantes y tutores (0011 → 0012). No cambia nada en la base.
    """

    dependencies = [
        ('Alumnos', '0011_profesor_usuario'),
        ('Alumnos', '0012_tutor_acceso'),
    ]

    operations = []
