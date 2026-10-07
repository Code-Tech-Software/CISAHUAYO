"""Reglas de los vínculos tutor-alumno que comparten las secciones de alumnos y tutores."""
from django.db.models import Prefetch

from .models import Alumno, TutorAlumno
from .utils import clave_de_texto

# Cómo se escribe a mano el parentesco: por su nombre, por su código o con las formas de uso común
_PARENTESCOS = {
    **{clave_de_texto(etiqueta): codigo for codigo, etiqueta in TutorAlumno.PARENTESCO_CHOICES},
    **{clave_de_texto(codigo.replace('_', ' ')): codigo for codigo, _ in TutorAlumno.PARENTESCO_CHOICES},
    'mama': 'MADRE', 'mami': 'MADRE', 'papa': 'PADRE', 'papi': 'PADRE',
    'abuelita': 'ABUELA', 'abuelito': 'ABUELO',
    'tutor': 'TUTOR_LEGAL', 'tutora': 'TUTOR_LEGAL', 'tutora legal': 'TUTOR_LEGAL', 'otra': 'OTRO',
}


def parentesco_de_texto(texto):
    """El código de parentesco de un texto escrito a mano («Mamá», «tío», «tutor legal»); None si no se reconoce."""
    return _PARENTESCOS.get(clave_de_texto(texto))


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


def vincular_tutor(tutor, alumno, valores):
    """Crea o actualiza el vínculo del tutor con el alumno; devuelve (vínculo, creado).

    `valores` trae los campos del vínculo (parentesco, activo, tutor_principal, contacto_emergencia…). Todo alumno con
    tutores vigentes tiene exactamente un principal: este lo es si es el primero o si se pide y es vigente, y un vínculo
    inactivo nunca lo es.
    """
    valores = dict(valores)
    otro_principal = (
        TutorAlumno.objects.filter(alumno=alumno, activo=True, tutor_principal=True, tutor__estatus='ACTIVO')
        .exclude(tutor=tutor).exists()
    )
    if valores.get('activo', True) and not otro_principal:
        valores['tutor_principal'] = True  # todo alumno con tutores vigentes tiene un principal
    if not valores.get('activo', True):
        valores['tutor_principal'] = False

    vinculo, creado = TutorAlumno.objects.update_or_create(tutor=tutor, alumno=alumno, defaults=valores)
    if vinculo.tutor_principal:
        TutorAlumno.objects.filter(alumno=alumno).exclude(pk=vinculo.pk).update(tutor_principal=False)
    return vinculo, creado
