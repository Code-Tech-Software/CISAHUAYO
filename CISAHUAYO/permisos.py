"""Control de acceso compartido por las secciones del sistema."""
from django.contrib.auth.decorators import login_required, permission_required


def requiere_permisos(*permisos):
    """Exige sesión iniciada (si no, redirige al login) y los permisos indicados (si faltan, 403).

    Los permisos de los modelos de Alumnos y Tutores usan la etiqueta de app «Alumnos»
    (p. ej. 'Alumnos.view_alumno', 'Alumnos.change_tutor').
    """
    def decorador(vista):
        return login_required(permission_required(permisos, raise_exception=True)(vista))
    return decorador
