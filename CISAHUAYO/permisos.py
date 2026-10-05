"""Control de acceso compartido por las secciones del sistema."""
from functools import wraps

from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied


def requiere_permisos(*permisos):
    """Exige sesión iniciada (si no, redirige al login) y los permisos indicados (si faltan, 403).

    Los permisos de los modelos de Alumnos y Tutores usan la etiqueta de app «Alumnos»
    (p. ej. 'Alumnos.view_alumno', 'Alumnos.change_tutor'); los de las cuentas, «auth.view_user», y los de los roles,
    «Usuarios.view_rol». Los permisos que se pueden conceder desde «Roles y permisos» están en Usuarios/catalogo.py.

    La vista queda marcada con `permisos_requeridos`: así las pruebas comprueban que ninguna ruta se quede sin
    protección y que cada permiso exigido se pueda conceder desde el catálogo.
    """
    def decorador(vista):
        protegida = login_required(permission_required(permisos, raise_exception=True)(vista))
        protegida.permisos_requeridos = tuple(permisos)
        return protegida
    return decorador


def requiere_alguno(*permisos):
    """Como `requiere_permisos`, pero basta con tener uno de los permisos (p. ej. la búsqueda de tutores del asistente de
    alumnos sirve a quien puede registrar o a quien puede editar)."""
    def decorador(vista):
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if not any(request.user.has_perm(permiso) for permiso in permisos):
                raise PermissionDenied
            return vista(request, *args, **kwargs)

        protegida = login_required(envoltura)
        protegida.permisos_requeridos = tuple(permisos)
        return protegida
    return decorador
