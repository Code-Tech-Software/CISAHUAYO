"""El alcance de una cuenta: qué estudiantes puede consultar y sobre cuáles puede actuar.

Una cuenta con un rol de prefectura (`Rol.es_prefectura`) solo ve a los estudiantes **inscritos en el ciclo actual** en
los niveles completos o en los grupos que el administrador le asignó (`AlcancePrefectura`), con todo su historial.
Todo el colegio se concede expresamente; sin alcance asignado no ve a ningún estudiante. Cualquier otra cuenta
(administración, Dirección, Control escolar…) no se limita: sigue viendo lo que sus permisos le dejan ver.

Toda consulta, acción, reporte, exportación y archivo de prefectura pasa por aquí (`alcance_de(usuario)`): ocultar un
botón no basta, el servidor filtra y responde 404 a lo que está fuera del alcance.
"""
from dataclasses import dataclass

from django.db.models import Exists, OuterRef, Q

from Alumnos.academico import ciclo_actual
from Alumnos.models import Alumno, Grado, Grupo, Inscripcion, orden_de_nivel

NIVELES = Grado.NIVEL_CHOICES
NOMBRE_DE_NIVEL = dict(NIVELES)


@dataclass(frozen=True)
class Alcance:
    restringido: bool = False          # una cuenta de prefectura: ve solo su alcance
    todo: bool = False                 # se le concedió todo el colegio
    niveles: frozenset = frozenset()   # niveles completos
    grupos: frozenset = frozenset()    # ids de grupos sueltos

    @property
    def total(self):
        return not self.restringido or self.todo

    @property
    def vacio(self):
        return not self.total and not self.niveles and not self.grupos

    def condicion(self, nivel='grado__nivel', grupo='grupo'):
        """La condición sobre algo con nivel y grupo (por omisión, una inscripción)."""
        if self.total:
            return Q()
        if self.vacio:
            return Q(pk__in=[])
        condicion = Q()
        if self.niveles:
            condicion |= Q(**{f'{nivel}__in': sorted(self.niveles)})
        if self.grupos:
            condicion |= Q(**{f'{grupo}__in': sorted(self.grupos)})
        return condicion

    def inscripciones(self, ciclo=None):
        """Las inscripciones vigentes del ciclo actual dentro del alcance."""
        ciclo = ciclo or ciclo_actual()
        if ciclo is None:
            return Inscripcion.objects.none()
        return Inscripcion.objects.filter(ciclo=ciclo, activa=True).filter(self.condicion())

    def alumnos(self, consulta=None):
        """Los estudiantes del alcance (con alcance total, todos los de la consulta)."""
        consulta = Alumno.objects.all() if consulta is None else consulta
        return self.filtrar(consulta, campo='pk')

    def filtrar(self, consulta, campo='alumno'):
        """Lo de los estudiantes del alcance: `campo` es el camino al estudiante (p. ej. 'inscripcion__alumno')."""
        if self.total:
            return consulta
        if self.vacio:
            return consulta.none()
        return consulta.filter(Exists(self.inscripciones().filter(alumno=OuterRef(campo))))

    def permite(self, alumno):
        """Si el estudiante (o su id) está en el alcance."""
        if self.total:
            return True
        pk = getattr(alumno, 'pk', alumno)
        return pk is not None and self.alumnos(Alumno.objects.filter(pk=pk)).exists()

    def permite_grupo(self, grupo):
        if self.total:
            return True
        return grupo is not None and (grupo.pk in self.grupos or grupo.grado.nivel in self.niveles)

    def grupos_visibles(self):
        """Los grupos activos del alcance, en orden escolar (para las listas de filtros)."""
        grupos = Grupo.objects.filter(activo=True, grado__activo=True).select_related('grado', 'nombre')
        grupos = grupos.filter(self.condicion(nivel='grado__nivel', grupo='pk'))
        return grupos.order_by(orden_de_nivel('grado__nivel'), 'grado__numero', 'nombre__orden', 'nombre__nombre')

    def niveles_visibles(self):
        """[(clave, nombre)] de los niveles con algo en el alcance."""
        if self.total:
            return list(NIVELES)
        presentes = set(self.niveles) | set(Grupo.objects.filter(pk__in=self.grupos).values_list('grado__nivel', flat=True))
        return [(clave, nombre) for clave, nombre in NIVELES if clave in presentes]

    def descripcion(self):
        """El alcance en palabras («Todo el colegio», «Secundaria completa · 1.º A de Primaria»…)."""
        if not self.restringido:
            return 'Sin restricción (no es una cuenta de prefectura)'
        if self.todo:
            return 'Todo el colegio'
        if self.vacio:
            return 'Sin alcance asignado: no ve a ningún estudiante'
        partes = [f'{NOMBRE_DE_NIVEL[clave]} completa' for clave, _ in NIVELES if clave in self.niveles]
        grupos = Grupo.objects.filter(pk__in=self.grupos).select_related('grado', 'nombre').order_by(
            orden_de_nivel('grado__nivel'), 'grado__numero', 'nombre__orden')
        partes += [str(grupo) for grupo in grupos]
        return ' · '.join(partes)


TOTAL = Alcance()
NINGUNO = Alcance(restringido=True)


def es_cuenta_de_prefectura(usuario):
    """Si la cuenta tiene un rol de prefectura (y no es administrador)."""
    if not getattr(usuario, 'is_authenticated', False) or usuario.is_superuser:
        return False
    guardado = getattr(usuario, '_es_prefectura', None)   # se pregunta varias veces por petición (menú, vistas)
    if guardado is None:
        from Usuarios.seguridad import rol_de
        rol = rol_de(usuario)
        guardado = usuario._es_prefectura = bool(rol and rol.es_prefectura and not rol.acceso_total)
    return guardado


def alcance_de(usuario):
    """El alcance de la cuenta (se calcula una vez por petición: queda en el objeto del usuario)."""
    if not getattr(usuario, 'is_authenticated', False):
        return NINGUNO
    guardado = getattr(usuario, '_alcance_prefectura', None)
    if guardado is not None:
        return guardado
    if not es_cuenta_de_prefectura(usuario):
        alcance = TOTAL
    else:
        from .models import AlcancePrefectura
        fila = AlcancePrefectura.objects.filter(usuario=usuario).first()
        if fila is None:
            alcance = NINGUNO
        else:
            alcance = Alcance(
                restringido=True, todo=fila.todo_el_colegio,
                niveles=frozenset(n for n in fila.niveles if n in NOMBRE_DE_NIVEL),
                grupos=frozenset(fila.grupos.values_list('pk', flat=True)),
            )
    usuario._alcance_prefectura = alcance
    return alcance
