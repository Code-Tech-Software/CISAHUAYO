"""Los filtros globales del panel: ciclo, alcance (todo el colegio o un nivel), grado, grupo, periodo y rango de fechas.

- Los niveles son los que el colegio tiene configurados (los que tienen grados activos), en orden escolar.
- El grado depende del nivel y el grupo del grado; algo que no corresponda se ignora (no se mezclan alcances).
- El periodo es de un nivel (cada nivel tiene los suyos: bimestres, trimestres, semestres…): solo se elige con un nivel.
  Sin nivel, cada nivel usa su periodo actual.
- El rango de fechas (por omisión, los últimos 30 días del ciclo hasta hoy) es para lo que se mide por días: la tendencia
  de asistencia, la conducta y los comunicados. Lo de «hoy» no depende de él.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from urllib.parse import urlencode

from django.db.models import Q
from django.utils import timezone

from Alumnos.models import ORDEN_NIVELES, CicloEscolar, Grado, Grupo, Inscripcion, Periodo

DIAS_DEL_RANGO = 30
CLAVES = ('ciclo', 'nivel', 'grado', 'grupo', 'periodo', 'desde', 'hasta')
NOMBRES_DE_NIVEL = dict(Grado.NIVEL_CHOICES)


def niveles_configurados():
    """[(clave, nombre)] de los niveles con grados disponibles (activos y visibles; sin ninguno, todos), en orden escolar."""
    activos = Grado.objects.disponibles().niveles() or set(NOMBRES_DE_NIVEL)
    return [(nivel, NOMBRES_DE_NIVEL[nivel]) for nivel in ORDEN_NIVELES if nivel in activos]


def _fecha(texto):
    try:
        return date.fromisoformat(str(texto))
    except ValueError:
        return None


def _elegir(opciones, valor):
    return next((o for o in opciones if str(o.pk) == str(valor)), None)


@dataclass
class Filtros:
    hoy: date
    ciclos: list = field(default_factory=list)
    ciclo: object = None
    niveles: list = field(default_factory=list)
    nivel: str = ''
    grados: list = field(default_factory=list)       # todos los del ciclo (la página los filtra por nivel)
    grado: object = None
    grupos: list = field(default_factory=list)
    grupo: object = None
    periodos: list = field(default_factory=list)     # los de todos los niveles del ciclo
    periodo: object = None                           # solo con un nivel
    desde: date = None
    hasta: date = None
    rango_predeterminado: bool = True

    # --- Alcance ---------------------------------------------------------------------------------------------------
    @property
    def es_actual(self):
        return bool(self.ciclo and self.ciclo.activo)

    @property
    def hoy_en_ciclo(self):
        """Lo de «hoy» solo aplica al ciclo actual."""
        return self.es_actual and self.ciclo.fecha_inicio <= self.hoy <= self.ciclo.fecha_fin

    @property
    def niveles_en_alcance(self):
        return [self.nivel] if self.nivel else [clave for clave, _ in self.niveles]

    @property
    def nombre_del_nivel(self):
        return NOMBRES_DE_NIVEL.get(self.nivel, '')

    @property
    def texto_del_alcance(self):
        if self.grupo is not None:
            return f'Información de {self.grupo}'
        if self.grado is not None:
            return f'Información de {self.grado}'
        if self.nivel:
            return f'Información de {self.nombre_del_nivel}'
        return 'Información de todo el colegio'

    @property
    def filtrado(self):
        """Si se eligió algo distinto de lo predeterminado (para «Restablecer»)."""
        return bool(self.nivel or not self.es_actual or not self.rango_predeterminado)

    def inscripciones(self):
        """Las inscripciones vigentes del alcance: estudiantes activos inscritos en el ciclo."""
        if self.ciclo is None:
            return Inscripcion.objects.none()
        consulta = Inscripcion.objects.filter(ciclo=self.ciclo, activa=True, alumno__estatus='ACTIVO')
        return self.filtrar(consulta)

    def filtrar(self, consulta, nivel='grado__nivel', grado='grado', grupo='grupo'):
        """Aplica nivel, grado y grupo a una consulta (con los caminos a esos campos)."""
        if self.grupo is not None:
            return consulta.filter(**{grupo: self.grupo})
        if self.grado is not None:
            return consulta.filter(**{grado: self.grado})
        if self.nivel:
            return consulta.filter(**{nivel: self.nivel})
        return consulta

    def periodos_de(self, nivel):
        return [p for p in self.periodos if p.nivel == nivel]

    @property
    def texto_del_rango(self):
        from django.utils.formats import date_format
        if self.desde == self.hasta:
            return date_format(self.desde, 'j M Y')
        return f'{date_format(self.desde, "j M")} – {date_format(self.hasta, "j M Y")}'

    # --- Direcciones -------------------------------------------------------------------------------------------------
    def valores(self):
        datos = {
            'ciclo': self.ciclo.pk if self.ciclo else '', 'nivel': self.nivel,
            'grado': self.grado.pk if self.grado else '', 'grupo': self.grupo.pk if self.grupo else '',
            'periodo': self.periodo.pk if self.periodo else '',
        }
        if not self.rango_predeterminado:
            datos.update(desde=self.desde.isoformat(), hasta=self.hasta.isoformat())
        return {clave: valor for clave, valor in datos.items() if valor not in ('', None)}

    def consulta(self, **extra):
        datos = {**self.valores(), **{k: v for k, v in extra.items() if v not in ('', None)}}
        return urlencode(datos)


def rango_predeterminado(ciclo, hoy):
    hasta = min(hoy, ciclo.fecha_fin) if ciclo else hoy
    if ciclo and hasta < ciclo.fecha_inicio:
        hasta = ciclo.fecha_inicio
    desde = max(ciclo.fecha_inicio, hasta - timedelta(days=DIAS_DEL_RANGO - 1)) if ciclo else hasta - timedelta(days=DIAS_DEL_RANGO - 1)
    return desde, hasta


def filtros_de(datos, hoy=None):
    """Los filtros de un diccionario (request.GET o lo guardado en la sesión), validados."""
    hoy = hoy or timezone.localdate()
    filtros = Filtros(hoy=hoy)
    filtros.ciclos = list(CicloEscolar.objects.order_by('-fecha_inicio'))
    actual = next((c for c in filtros.ciclos if c.activo), filtros.ciclos[0] if filtros.ciclos else None)
    filtros.ciclo = _elegir(filtros.ciclos, datos.get('ciclo')) or actual
    filtros.niveles = niveles_configurados()
    if datos.get('nivel') in dict(filtros.niveles):
        filtros.nivel = datos['nivel']

    ciclo = filtros.ciclo
    if ciclo is not None:
        # Los de baja con inscritos en el ciclo, sí (su historial); los ocultos, nunca (2026-10-28)
        con_inscritos = Q(inscripciones__ciclo=ciclo)
        filtros.grados = list(Grado.objects.filter(Q(activo=True) | con_inscritos, visible=True).distinct().academicos())
        filtros.grupos = list(Grupo.objects.filter(Q(activo=True, grado__activo=True) | con_inscritos, grado__visible=True)
                              .select_related('grado', 'nombre').distinct().academicos())
        filtros.periodos = list(Periodo.objects.filter(ciclo=ciclo).order_by('fecha_inicio', 'nombre'))
    if filtros.nivel:
        grado = _elegir(filtros.grados, datos.get('grado'))
        if grado is not None and grado.nivel == filtros.nivel:
            filtros.grado = grado
            grupo = _elegir(filtros.grupos, datos.get('grupo'))
            if grupo is not None and grupo.grado_id == grado.pk:
                filtros.grupo = grupo
        periodo = _elegir(filtros.periodos_de(filtros.nivel), datos.get('periodo'))
        filtros.periodo = periodo

    desde, hasta = _fecha(datos.get('desde', '')), _fecha(datos.get('hasta', ''))
    predeterminado = rango_predeterminado(ciclo, hoy)
    if desde and hasta and ciclo is not None:
        desde, hasta = max(desde, ciclo.fecha_inicio), min(hasta, ciclo.fecha_fin)
        if desde <= hasta and (desde, hasta) != predeterminado:
            filtros.desde, filtros.hasta, filtros.rango_predeterminado = desde, hasta, False
    if filtros.rango_predeterminado:
        filtros.desde, filtros.hasta = predeterminado
    return filtros
