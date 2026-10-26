"""Quién envía comunicados y a quién: el alcance por nivel educativo. Toda la selección de destinatarios sale de aquí y
el envío revisa que cada persona elegida esté en ella (Comunicados/reglas.py): ocultar algo en la pantalla no basta.

- Enviar exige `Comunicados.enviar`. El administrador (`Comunicados.gestionar`, exclusivo del rol de acceso total)
  envía a cualquier tutor, estudiante o profesor del colegio, de uno o varios niveles.
- Cualquier otra cuenta solo llega a las personas de los niveles que tiene asignados, la unión de:
  · los «Niveles para comunicados» de su ficha de usuario;
  · los niveles en que da clases si es docente (su ficha de profesor y sus materias del ciclo actual): su alcance es
    su nivel, no solo sus materias;
  · los niveles que dirige (si su rol aprueba suspensiones) y los que coordina (si consulta las bitácoras de todos los
    grupos), cuando se le asignaron;
  · los niveles completos de su alcance de prefectura (todo el colegio, si se le concedió).
  Sin ningún nivel no envía (la pantalla lo explica).
- Quién es de un nivel sale de los vínculos reales del ciclo actual:
  · estudiante: activo, con una inscripción vigente en un grado del nivel;
  · tutor: activo, con un vínculo activo que «Recibe notificaciones» con un estudiante del alcance (si tiene hijos en
    varios niveles, basta uno; al emisor solo se le muestran los hijos que él puede ver);
  · profesor: activo, que da clases en el nivel (su ficha o sus materias del ciclo) y cuya cuenta puede consultar
    comunicados (`Comunicados.recibir`): sin cuenta no tendría dónde leerlo.
"""
from dataclasses import dataclass, field

from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.db.models import Q

from Alumnos.academico import ciclo_actual
from Alumnos.models import ORDEN_NIVELES, Alumno, Grado, Grupo, Inscripcion, MateriaGrado, Profesor, Tutor, TutorAlumno, orden_de_nivel

from .models import Destinatario

RECIBIR = 'Comunicados.recibir'
SEGUIMIENTO = 'Comunicados.seguimiento'
ENVIAR = 'Comunicados.enviar'
ELIMINAR = 'Comunicados.eliminar'
GESTIONAR = 'Comunicados.gestionar'
TODOS = (RECIBIR, SEGUIMIENTO, ENVIAR, ELIMINAR, GESTIONAR)

NOMBRE_DE_NIVEL = dict(Grado.NIVEL_CHOICES)
SIN_NIVELES = ('No tienes niveles educativos asignados, así que todavía no puedes enviar comunicados. Pide al administrador '
               'que te asigne niveles en tu ficha de usuario («Niveles para comunicados»).')
MAXIMO_DE_HIJOS_EN_DETALLE = 3
MAXIMO_DE_MATERIAS_EN_DETALLE = 2


class FueraDeAlcance(Exception):
    """Se pidió a alguien que no está en el alcance de quien envía (la pantalla nunca lo ofrece: la petición se alteró)."""


def es_administrador(usuario):
    return bool(usuario and usuario.is_authenticated and usuario.is_active and usuario.has_perm(GESTIONAR))


def cuentas_con(permiso):
    """Las cuentas activas que tienen el permiso (por su rol, por permiso suelto o por ser superusuario)."""
    app, codigo = permiso.split('.')
    return get_user_model().objects.filter(
        Q(is_superuser=True)
        | Q(groups__permissions__codename=codigo, groups__permissions__content_type__app_label=app)
        | Q(user_permissions__codename=codigo, user_permissions__content_type__app_label=app),
        is_active=True,
    ).values('pk')


# ---------------------------------------------------------------------------
# Nombres
# ---------------------------------------------------------------------------
def apellidos_y_nombre(persona):
    """«Campos Vega Ana»: así se ordenan y se buscan en las listas."""
    return ' '.join(f'{persona.apellido_paterno} {persona.apellido_materno} {persona.nombre}'.split())


def nombre_y_apellidos(persona):
    return ' '.join(f'{persona.nombre} {persona.apellido_paterno} {persona.apellido_materno}'.split())


def _lista(nombres, maximo):
    nombres = list(nombres)
    if len(nombres) <= maximo:
        return ', '.join(nombres)
    return f'{", ".join(nombres[:maximo])} y {len(nombres) - maximo} más'


def _grupo_corto(grupo):
    return grupo.corto   # «7.º A»: la equivalencia del grado


# ---------------------------------------------------------------------------
# Niveles de quien envía
# ---------------------------------------------------------------------------
def niveles_asignados(usuario):
    """{nivel: [de dónde le viene, …]} en orden escolar: los niveles a los que la cuenta puede enviar (sin contar el
    alcance total del administrador)."""
    from Usuarios.docentes import profesor_de
    from Usuarios.models import PerfilUsuario

    encontrados = {}

    def anotar(niveles, motivo):
        for nivel in niveles or ():
            if nivel in NOMBRE_DE_NIVEL and motivo not in encontrados.setdefault(nivel, []):
                encontrados[nivel].append(motivo)

    try:
        perfil = PerfilUsuario.objects.filter(usuario=usuario).values(
            'niveles_comunicados', 'niveles_direccion', 'niveles_bitacora').first() or {}
    except DatabaseError:   # aún no se aplica la migración de Usuarios
        perfil = {}
    anotar(perfil.get('niveles_comunicados'), 'Asignado en su cuenta')

    profesor = profesor_de(usuario)
    if profesor is not None and profesor.estatus == 'ACTIVO':
        docente = set(profesor.niveles.values_list('nivel', flat=True))
        ciclo = ciclo_actual()
        if ciclo is not None:
            docente |= set(MateriaGrado.objects.filter(profesor=profesor, ciclo=ciclo, activa=True).values_list('grado__nivel', flat=True))
        anotar(docente, 'Docente')

    if usuario.has_perm('Conducta.aprobar_suspension'):
        anotar(perfil.get('niveles_direccion'), 'Dirección de nivel')
    if any(usuario.has_perm(p) for p in ('Bitacoras.consultar_todas', 'Bitacoras.registrar_todas', 'Bitacoras.gestionar')):
        anotar(perfil.get('niveles_bitacora'), 'Coordinación')

    from Prefectura.alcance import alcance_de as alcance_de_prefectura
    from Prefectura.alcance import es_cuenta_de_prefectura
    if es_cuenta_de_prefectura(usuario):
        prefectura = alcance_de_prefectura(usuario)
        anotar(ORDEN_NIVELES if prefectura.todo else prefectura.niveles, 'Prefectura')

    return {nivel: encontrados[nivel] for nivel in ORDEN_NIVELES if nivel in encontrados}


@dataclass
class Alcance:
    usuario: object
    total: bool = False                       # el administrador: todo el colegio
    niveles: frozenset = frozenset()
    origenes: dict = field(default_factory=dict)   # nivel -> [de dónde le viene]
    _cache: dict = field(default_factory=dict, repr=False)

    @property
    def puede_enviar(self):
        return self.usuario.has_perm(ENVIAR) and (self.total or bool(self.niveles))

    @property
    def niveles_en_orden(self):
        niveles = ORDEN_NIVELES if self.total else [n for n in ORDEN_NIVELES if n in self.niveles]
        return [(nivel, NOMBRE_DE_NIVEL[nivel]) for nivel in niveles]

    def descripcion(self):
        if self.total:
            return 'Todo el colegio'
        if not self.niveles:
            return 'Sin niveles asignados'
        return ' · '.join(nombre for _, nombre in self.niveles_en_orden)

    # ------------------------------------------------------------------ quién está en el alcance
    def ciclo(self):
        if 'ciclo' not in self._cache:
            self._cache['ciclo'] = ciclo_actual()
        return self._cache['ciclo']

    def inscripciones(self):
        """Las inscripciones vigentes del ciclo actual de estudiantes activos, en los niveles del alcance."""
        ciclo = self.ciclo()
        if ciclo is None:
            return Inscripcion.objects.none()
        consulta = Inscripcion.objects.filter(ciclo=ciclo, activa=True, alumno__estatus='ACTIVO')
        return consulta if self.total else consulta.filter(grado__nivel__in=sorted(self.niveles))

    def estudiantes(self):
        """El administrador llega a todo estudiante activo (aunque no tenga inscripción vigente); los demás, a los
        inscritos en sus niveles."""
        consulta = Alumno.objects.filter(estatus='ACTIVO')
        return consulta if self.total else consulta.filter(pk__in=self.inscripciones().values('alumno'))

    def vinculos(self):
        """Los vínculos tutor-estudiante que cuentan para los comunicados (activos y que reciben notificaciones), con
        estudiantes del alcance."""
        return TutorAlumno.objects.filter(activo=True, recibe_notificaciones=True, tutor__estatus='ACTIVO',
                                          alumno__in=self.estudiantes())

    def tutores(self):
        consulta = Tutor.objects.filter(estatus='ACTIVO')
        return consulta if self.total else consulta.filter(pk__in=self.vinculos().values('tutor'))

    def profesores(self):
        consulta = Profesor.objects.filter(estatus='ACTIVO', usuario__is_active=True, usuario__in=cuentas_con(RECIBIR)).exclude(
            usuario=self.usuario)
        if self.total:
            return consulta
        de_sus_niveles = Q(niveles__nivel__in=sorted(self.niveles))
        ciclo = self.ciclo()
        if ciclo is not None:
            de_sus_niveles |= Q(pk__in=MateriaGrado.objects.filter(ciclo=ciclo, activa=True, grado__nivel__in=sorted(self.niveles),
                                                                   profesor__isnull=False).values('profesor'))
        return consulta.filter(pk__in=Profesor.objects.filter(de_sus_niveles).values('pk'))

    def consulta_de(self, tipo):
        return {Destinatario.ESTUDIANTE: self.estudiantes, Destinatario.TUTOR: self.tutores, Destinatario.PROFESOR: self.profesores}[tipo]()

    # ------------------------------------------------------------------ validación del envío
    def validar(self, seleccion):
        """{tipo: {ids}} con solo personas del alcance; FueraDeAlcance si se pidió a alguien más."""
        elegidos = {}
        for tipo, _ in Destinatario.TIPOS:
            pedidos = set(seleccion.get(tipo) or ())
            if pedidos:
                permitidos = set(self.consulta_de(tipo).filter(pk__in=pedidos).values_list('pk', flat=True))
                if pedidos - permitidos:
                    raise FueraDeAlcance(tipo)
            elegidos[tipo] = pedidos
        return elegidos

    # ------------------------------------------------------------------ cómo se ubica a cada persona
    def _inscripciones_de(self, alumnos):
        """{id de estudiante: inscripción vigente} (la del ciclo actual, con su grupo). `alumnos`: ids o una consulta."""
        ciclo = self.ciclo()
        if ciclo is None:
            return {}
        consulta = Inscripcion.objects.filter(ciclo=ciclo, activa=True, alumno__in=alumnos).select_related('grupo__grado', 'grupo__nombre')
        return {inscripcion.alumno_id: inscripcion for inscripcion in consulta}

    def detalles_de_estudiantes(self, alumnos, consulta=None):
        """{id: (texto, id de grupo o None)} de esos ids (`consulta`: la misma lista como consulta, para no mandar miles
        de ids a la base)."""
        inscripciones = self._inscripciones_de(alumnos if consulta is None else consulta)
        detalles = {}
        for alumno_id in alumnos:
            inscripcion = inscripciones.get(alumno_id)
            if inscripcion is None:
                detalles[alumno_id] = ('Sin inscripción vigente', None)
            else:
                grupo = inscripcion.grupo
                detalles[alumno_id] = (f'{_grupo_corto(grupo)} · {grupo.grado.get_nivel_display()}', grupo.pk)
        return detalles

    def hijos_de(self, tutores):
        """{id de tutor: [estudiantes de su alcance con los que tiene un vínculo que cuenta]}"""
        hijos = {}
        vinculos = self.vinculos().filter(tutor__in=tutores, alumno__estatus='ACTIVO').select_related('alumno').order_by(
            'alumno__nombre', 'alumno__apellido_paterno')
        for vinculo in vinculos:
            hijos.setdefault(vinculo.tutor_id, []).append(vinculo.alumno)
        return hijos

    def detalles_de_tutores(self, tutores):
        hijos = self.hijos_de(tutores)
        return {
            tutor_id: f'Tutor de {_lista((nombre_y_apellidos(a) for a in hijos.get(tutor_id, [])), MAXIMO_DE_HIJOS_EN_DETALLE)}'
            if hijos.get(tutor_id) else 'Tutor'
            for tutor_id in (t if isinstance(t, int) else t.pk for t in tutores)
        }

    def clases_de(self, profesores):
        """{id de profesor: [asignaciones del ciclo actual en el alcance]}"""
        ciclo = self.ciclo()
        if ciclo is None:
            return {}
        consulta = MateriaGrado.objects.filter(ciclo=ciclo, activa=True, profesor__in=profesores).select_related(
            'materia', 'grupo__grado', 'grupo__nombre').order_by('materia__nombre')
        if not self.total:
            consulta = consulta.filter(grado__nivel__in=sorted(self.niveles))
        clases = {}
        for asignacion in consulta:
            clases.setdefault(asignacion.profesor_id, []).append(asignacion)
        return clases

    def niveles_de_profesores(self, profesores, clases):
        """{id de profesor: [niveles en orden]} (su ficha y sus materias del ciclo, dentro del alcance)."""
        niveles = {}
        for profesor in profesores:
            propios = {n.nivel for n in profesor.niveles.all()} | {a.grupo.grado.nivel for a in clases.get(profesor.pk, [])}
            if not self.total:
                propios &= set(self.niveles)
            niveles[profesor.pk] = [n for n in ORDEN_NIVELES if n in propios]
        return niveles

    def detalles_de_profesores(self, profesores):
        profesores = list(Profesor.objects.filter(pk__in=[p if isinstance(p, int) else p.pk for p in profesores]).prefetch_related('niveles'))
        clases = self.clases_de(profesores)
        niveles = self.niveles_de_profesores(profesores, clases)
        return {profesor.pk: self._detalle_de_profesor(niveles[profesor.pk], clases.get(profesor.pk, [])) for profesor in profesores}

    @staticmethod
    def _detalle_de_profesor(niveles, clases):
        partes = [', '.join(NOMBRE_DE_NIVEL[n] for n in niveles)] if niveles else []
        if clases:
            partes.append(_lista((f'{a.materia.nombre} {_grupo_corto(a.grupo)}' for a in clases), MAXIMO_DE_MATERIAS_EN_DETALLE))
        return ' · '.join(partes) or 'Profesor'

    def detalles(self, elegidos):
        """{tipo: {id: texto}} de las personas elegidas, como se guarda en cada destinatario al enviar."""
        return {
            Destinatario.ESTUDIANTE: {pk: texto for pk, (texto, _) in self.detalles_de_estudiantes(sorted(elegidos[Destinatario.ESTUDIANTE])).items()},
            Destinatario.TUTOR: self.detalles_de_tutores(sorted(elegidos[Destinatario.TUTOR])),
            Destinatario.PROFESOR: self.detalles_de_profesores(sorted(elegidos[Destinatario.PROFESOR])),
        }

    # ------------------------------------------------------------------ lo que necesita el selector
    def universo(self):
        """Todo lo que el selector de destinatarios puede ofrecer, para armarlo en el navegador: el árbol (nivel → grado
        → grupo → materia del ciclo actual) y las personas de cada pestaña con lo que las une a cada nodo."""
        estudiantes = list(self.estudiantes().only('pk', 'nombre', 'apellido_paterno', 'apellido_materno', 'acceso_portal',
                                                   'correo_electronico', 'contrasena')
                           .order_by('apellido_paterno', 'apellido_materno', 'nombre'))
        detalles = self.detalles_de_estudiantes([a.pk for a in estudiantes], consulta=self.estudiantes())
        tutores = list(self.tutores().only('pk', 'nombre', 'apellido_paterno', 'apellido_materno', 'acceso_portal', 'usuario', 'contrasena')
                       .order_by('apellido_paterno', 'apellido_materno', 'nombre'))
        hijos = self.hijos_de(self.tutores())
        profesores = list(self.profesores().prefetch_related('niveles').order_by('apellido_paterno', 'apellido_materno', 'nombre'))
        clases = self.clases_de(profesores)
        niveles_de_profesor = self.niveles_de_profesores(profesores, clases)

        # El árbol: solo los grupos con alguien (estudiantes o profesores) a quien enviar
        con_estudiantes = {grupo for _, grupo in detalles.values() if grupo}
        asignaciones = [a for propias in clases.values() for a in propias]
        con_profesor = {a.grupo_id for a in asignaciones}
        grupos = Grupo.objects.filter(pk__in=con_estudiantes | con_profesor).select_related('grado', 'nombre').order_by(
            orden_de_nivel('grado__nivel'), 'grado__numero', 'nombre__orden', 'nombre__nombre')
        materias = {}
        ciclo = self.ciclo()
        if ciclo is not None:
            for asignacion in (MateriaGrado.objects.filter(ciclo=ciclo, activa=True, grupo__in=grupos).select_related('materia')
                               .order_by('materia__nombre')):
                materias.setdefault(asignacion.grupo_id, []).append(
                    {'id': asignacion.pk, 'nombre': asignacion.materia.nombre, 'profesor': asignacion.profesor_id})
        arbol, por_nivel, por_grado = [], {}, {}
        for grupo in grupos:
            grado = grupo.grado
            if grado.nivel not in por_nivel:
                por_nivel[grado.nivel] = {'clave': grado.nivel, 'nombre': grado.get_nivel_display(), 'grados': []}
                arbol.append(por_nivel[grado.nivel])
            if grado.pk not in por_grado:
                por_grado[grado.pk] = {'id': grado.pk, 'nombre': str(grado), 'grupos': []}
                por_nivel[grado.nivel]['grados'].append(por_grado[grado.pk])
            por_grado[grado.pk]['grupos'].append({'id': grupo.pk, 'nombre': f'{_grupo_corto(grupo)}', 'materias': materias.get(grupo.pk, [])})

        return {
            'alcance': {'total': self.total, 'descripcion': self.descripcion()},
            'arbol': arbol,
            'estudiantes': [{
                'id': a.pk, 'nombre': apellidos_y_nombre(a), 'corto': nombre_y_apellidos(a), 'detalle': detalles[a.pk][0],
                'grupo': detalles[a.pk][1], 'sin_acceso': not (a.acceso_portal and a.correo_electronico and a.contrasena),
            } for a in estudiantes],
            'tutores': [{
                'id': t.pk, 'nombre': apellidos_y_nombre(t), 'hijos': [a.pk for a in hijos.get(t.pk, [])],
                'sin_acceso': not (t.acceso_portal and t.usuario and t.contrasena),
            } for t in tutores],
            'profesores': [{
                'id': p.pk, 'nombre': apellidos_y_nombre(p), 'niveles': niveles_de_profesor[p.pk],
                'grupos': sorted({a.grupo_id for a in clases.get(p.pk, [])}), 'materias': [a.pk for a in clases.get(p.pk, [])],
                'detalle': self._detalle_de_profesor(niveles_de_profesor[p.pk], clases.get(p.pk, [])),
            } for p in profesores],
        }


def alcance_de(usuario):
    """El alcance de la cuenta (se calcula una vez por petición: queda en el objeto del usuario)."""
    guardado = getattr(usuario, '_alcance_comunicados', None)
    if guardado is not None:
        return guardado
    if es_administrador(usuario):
        alcance = Alcance(usuario, total=True)
    else:
        origenes = niveles_asignados(usuario) if usuario.is_authenticated else {}
        alcance = Alcance(usuario, niveles=frozenset(origenes), origenes=origenes)
    usuario._alcance_comunicados = alcance
    return alcance
