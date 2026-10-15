"""Quién ve y hace qué en las bitácoras por grupo. Toda vista pasa por aquí: ocultar un botón no basta, el servidor
filtra lo que se lista y responde 404 a lo que queda fuera del alcance y 403 a lo que no se puede modificar.

Permisos (Usuarios/catalogo.py, módulo «Bitácoras por grupo»):
- `registrar` (docente): registra y consulta las entradas de los grupos y materias que tiene asignados (en cualquier
  ciclo en que los tuvo) y edita o anula las suyas.
- `consultar_todas` / `registrar_todas`: consulta / registra en todos los grupos **de su alcance**: una cuenta de
  prefectura, el suyo (Prefectura/alcance.py); cualquier otra, los «Niveles que coordina» de su cuenta (sin niveles,
  todo el colegio). El administrador, todo.
- `gestionar`: edita o anula entradas de otros usuarios de su alcance y consulta las anuladas (auditoría).
Nadie edita ni anula en un ciclo cerrado (solo lectura) ni una entrada ya anulada. Estudiantes y familias no entran:
los portales no muestran bitácoras.
"""
from dataclasses import dataclass, field

from django.db import DatabaseError
from django.db.models import Exists, OuterRef, Q

from Alumnos.academico import ciclo_actual
from Alumnos.models import Grado, Grupo, Inscripcion, MateriaGrado, orden_de_nivel
from Prefectura.alcance import alcance_de, es_cuenta_de_prefectura
from Usuarios.docentes import profesor_de

from .models import EntradaBitacora

REGISTRAR = 'Bitacoras.registrar'
CONSULTAR_TODAS = 'Bitacoras.consultar_todas'
REGISTRAR_TODAS = 'Bitacoras.registrar_todas'
GESTIONAR = 'Bitacoras.gestionar'
TODOS = (REGISTRAR, CONSULTAR_TODAS, REGISTRAR_TODAS, GESTIONAR)
NOMBRE_DE_NIVEL = dict(Grado.NIVEL_CHOICES)


def puede_entrar(usuario):
    return any(usuario.has_perm(permiso) for permiso in TODOS)


def puede_registrar(usuario):
    return usuario.has_perm(REGISTRAR) or usuario.has_perm(REGISTRAR_TODAS)


def niveles_que_coordina(usuario):
    """Los niveles de una cuenta de coordinación; None = sin límite (vacío en su cuenta, o el administrador)."""
    if usuario.is_superuser:
        return None
    from Usuarios.models import PerfilUsuario
    try:
        niveles = PerfilUsuario.objects.filter(usuario=usuario).values_list('niveles_bitacora', flat=True).first()
    except DatabaseError:   # aún no se aplica la migración
        niveles = None
    niveles = {n for n in (niveles or []) if n in NOMBRE_DE_NIVEL}
    return niveles or None


@dataclass
class Alcance:
    """Lo que la cuenta puede hacer en las bitácoras (se calcula una vez por petición)."""
    usuario: object
    amplio: bool = False             # consulta todos los grupos de su alcance
    registra_amplio: bool = False    # registra en todos los grupos de su alcance
    gestiona: bool = False
    propio: bool = False             # docente: sus grupos y materias
    profesor: object = None
    prefectura: object = None        # el alcance de una cuenta de prefectura
    niveles: frozenset = None        # niveles que coordina (None = todos)
    descripcion: str = ''
    _cache: dict = field(default_factory=dict, repr=False)

    def condicion(self, nivel='nivel', grupo='grupo'):
        """Hasta dónde llegan sus permisos amplios, sobre algo con nivel y grupo. Sin límite es una condición que se
        cumple siempre (no `Q()`: al combinarla con «|», Django descarta la vacía y quedaría la otra parte sola)."""
        if self.prefectura is not None:
            condicion = self.prefectura.condicion(nivel=nivel, grupo=grupo)
        elif self.niveles is not None:
            condicion = Q(**{f'{nivel}__in': sorted(self.niveles)})
        else:
            condicion = Q()
        return condicion if condicion else Q(pk__isnull=False)

    # ------------------------------------------------------------------ consultar
    def entradas(self, anuladas=False):
        """Las entradas que puede consultar. Las anuladas solo con «gestionar» y si se piden (`anuladas`: True = todas,
        'solo' = solo anuladas)."""
        if 'visibles' not in self._cache:
            condicion = Q(pk__in=[])
            if self.amplio:
                condicion |= self.condicion()
            if self.propio and self.profesor is not None:
                condicion |= Q(asignacion__profesor=self.profesor)
            if self.propio or self.registra_amplio:
                condicion |= Q(autor=self.usuario)
            self._cache['visibles'] = condicion
        consulta = EntradaBitacora.objects.filter(self._cache['visibles'])
        if not (self.gestiona and anuladas):
            return consulta.filter(anulada=False)
        return consulta.filter(anulada=True) if anuladas == 'solo' else consulta

    def ve(self, entrada):
        return self.entradas(anuladas=True).filter(pk=entrada.pk).exists()

    def grupos(self):
        """Los grupos cuya bitácora puede consultar (para el filtro): los de su alcance y los de sus materias."""
        condicion = Q(pk__in=[])
        if self.amplio:
            condicion |= self.condicion(nivel='grado__nivel', grupo='pk') & Q(activo=True)
        if self.propio and self.profesor is not None:
            condicion |= Q(pk__in=MateriaGrado.objects.filter(profesor=self.profesor).values('grupo'))
        condicion |= Q(pk__in=self.entradas(anuladas=True).values('grupo'))
        return (Grupo.objects.filter(condicion).select_related('grado', 'nombre')
                .order_by(orden_de_nivel('grado__nivel'), 'grado__numero', 'nombre__orden', 'nombre__nombre'))

    def ve_estudiante(self, alumno):
        """Si puede abrir el historial del estudiante: está (o estuvo) en un grupo de su alcance o de sus materias, o
        ya tiene entradas suyas a la vista."""
        if self.amplio:
            if self.prefectura is not None:
                if self.prefectura.permite(alumno):
                    return True
            elif self.niveles is None or alumno.inscripciones.filter(grado__nivel__in=self.niveles).exists():
                return True
        if self.propio and self.profesor is not None:
            suyas = MateriaGrado.objects.filter(profesor=self.profesor, grupo=OuterRef('grupo'), ciclo=OuterRef('ciclo'))
            if Inscripcion.objects.filter(alumno=alumno).filter(Exists(suyas)).exists():
                return True
        return self.entradas().filter(vinculos__alumno=alumno).exists()

    # ------------------------------------------------------------------ registrar
    def asignaciones(self, ciclo=None):
        """Las materias de cada grupo (del ciclo actual) en las que puede registrar."""
        ciclo = ciclo or ciclo_actual()
        if ciclo is None or ciclo.estado == 'CERRADO':
            return MateriaGrado.objects.none()
        condicion = Q(pk__in=[])
        if self.registra_amplio:
            condicion |= self.condicion(nivel='grado__nivel', grupo='grupo')
        if self.propio and self.profesor is not None:
            condicion |= Q(profesor=self.profesor)
        return (MateriaGrado.objects.filter(condicion, ciclo=ciclo, activa=True, materia__activa=True)
                .select_related('materia', 'profesor', 'ciclo', 'grado', 'grupo__nombre', 'grupo__grado')
                .order_by(orden_de_nivel('grado__nivel'), 'grado__numero', 'grupo__nombre__orden', 'grupo__nombre__nombre', 'materia__nombre'))

    def puede_registrar_en(self, asignacion):
        return self.asignaciones(asignacion.ciclo).filter(pk=asignacion.pk).exists()

    # ------------------------------------------------------------------ modificar
    def motivo_para_no_modificar(self, entrada):
        """Por qué no puede editar ni anular la entrada, o '' si puede."""
        if entrada.anulada:
            return 'La entrada está anulada.'
        if entrada.ciclo.estado == 'CERRADO':
            return f'El ciclo {entrada.ciclo} está cerrado: sus bitácoras son de solo lectura.'
        if self.gestiona and EntradaBitacora.objects.filter(self.condicion(), pk=entrada.pk).exists():
            return ''
        if entrada.autor_id == self.usuario.pk and (self.propio or self.registra_amplio):
            return ''
        return 'Solo quien la registró o la administración puede modificarla.'

    def puede_modificar(self, entrada):
        return not self.motivo_para_no_modificar(entrada)


def _descripcion(alcance):
    if alcance.usuario.is_superuser:
        return 'Todo el colegio'
    partes = []
    if alcance.amplio:
        if alcance.prefectura is not None:
            partes.append(alcance.prefectura.descripcion())
        elif alcance.niveles is not None:
            partes.append(' · '.join(nombre for clave, nombre in Grado.NIVEL_CHOICES if clave in alcance.niveles))
        else:
            partes.append('Todo el colegio')
    if alcance.propio:
        partes.append('Tus grupos y materias asignados' if alcance.profesor is not None else 'Sin materias asignadas (tu cuenta no tiene ficha de profesor)')
    return ' · '.join(partes)


def alcance_de_bitacoras(usuario):
    guardado = getattr(usuario, '_alcance_bitacoras', None)
    if guardado is not None:
        return guardado
    alcance = Alcance(
        usuario=usuario,
        amplio=any(usuario.has_perm(p) for p in (CONSULTAR_TODAS, REGISTRAR_TODAS, GESTIONAR)),
        registra_amplio=usuario.has_perm(REGISTRAR_TODAS),
        gestiona=usuario.has_perm(GESTIONAR),
        propio=usuario.has_perm(REGISTRAR),
    )
    if alcance.propio:
        alcance.profesor = profesor_de(usuario)
    if alcance.amplio and not usuario.is_superuser:
        if es_cuenta_de_prefectura(usuario):
            alcance.prefectura = alcance_de(usuario)
        else:
            niveles = niveles_que_coordina(usuario)
            alcance.niveles = frozenset(niveles) if niveles is not None else None
    alcance.descripcion = _descripcion(alcance)
    usuario._alcance_bitacoras = alcance
    return alcance
