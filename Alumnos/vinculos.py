"""Reglas de los vínculos tutor-alumno que comparten las secciones de alumnos y tutores."""
from django.db.models import Prefetch

from .models import Alumno, TutorAlumno


def vinculos_vigentes(alumno):
    """Vínculos activos con tutores que no están dados de baja."""
    return TutorAlumno.objects.filter(alumno=alumno, activo=True, tutor__estatus='ACTIVO')


def prefetch_vinculos_activos(desde=''):
    """Vínculos vigentes con tutores vigentes (un tutor dado de baja ya no cuenta como contacto).

    Deja la lista en `alumno.vinculos_activos`, con el tutor principal primero. `desde` es la ruta hasta el
    alumno cuando se parte de otro modelo (por ejemplo 'alumno__' desde una inscripción).
    """
    return Prefetch(
        f'{desde}tutores_relacionados',
        queryset=(
            TutorAlumno.objects.filter(activo=True, tutor__estatus='ACTIVO')
            .select_related('tutor')
            .order_by('-tutor_principal', 'tutor__apellido_paterno')
        ),
        to_attr='vinculos_activos',
    )


def asegurar_tutor_principal(alumno):
    """Si el alumno tiene tutores vigentes pero ninguno principal, promueve al más antiguo."""
    vigentes = vinculos_vigentes(alumno)
    if vigentes.exists() and not vigentes.filter(tutor_principal=True).exists():
        primero = vigentes.order_by('creado', 'pk').first()
        primero.tutor_principal = True
        primero.save(update_fields=['tutor_principal', 'modificado'])


def sincronizar_principales(tutor):
    """Tras cambiar el estatus de un tutor: uno de baja deja de ser principal y otro vigente toma su lugar."""
    if tutor.estatus != 'ACTIVO':
        TutorAlumno.objects.filter(tutor=tutor).update(tutor_principal=False)
    for alumno in Alumno.objects.filter(tutores_relacionados__tutor=tutor).distinct():
        asegurar_tutor_principal(alumno)
