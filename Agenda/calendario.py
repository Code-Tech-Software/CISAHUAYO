"""El mes del calendario: semanas de lunes a domingo (con los días del mes anterior y del siguiente que completan la
primera y la última) y, en cada semana, los eventos como barras que ocupan sus días.

Un evento de varios días se dibuja como una barra por semana que toca; si empieza antes o sigue después de esa semana
(o del mes), la barra lo indica. Cada semana acomoda sus barras en carriles (renglones) sin encimarlas; la semana crece
hasta `CARRILES` renglones (así los eventos de un día no quedan escondidos detrás de los de varios días) y lo que aun
así no cabe se cuenta por día como «+N eventos», con la lista completa de ese día.

También: la semana en columnas (barras arriba y, en cada día, sus eventos de un día), el mes en miniatura (el teléfono
y la vista del ciclo escolar) y los meses del ciclo.
"""
from dataclasses import dataclass, field
from datetime import date, time, timedelta

from django.utils.formats import date_format

CARRILES = 6
PUNTOS = 3      # colores distintos por día en el mes en miniatura


@dataclass
class Tramo:
    """Lo que un evento ocupa en una semana: de la columna `inicio` a la `fin` (1 a 7)."""
    evento: object
    inicio: int
    fin: int
    antes: bool        # empezó antes de esta semana
    despues: bool      # sigue después de esta semana
    carril: int = 0

    @property
    def columnas(self):
        return self.fin - self.inicio + 1


@dataclass
class Dia:
    fecha: date
    en_mes: bool
    es_hoy: bool
    columna: int
    eventos: list = field(default_factory=list)   # todos los del día, en orden
    ocultos: int = 0                               # los que no caben en los carriles
    sin_clases: str = ''                           # el motivo, si ese día no hay clases

    @property
    def texto(self):
        return date_format(self.fecha, 'l j \\d\\e F').capitalize()

    @property
    def de_un_dia(self):
        """Sus eventos de un solo día (en la semana en columnas, las barras de varios días van arriba)."""
        return [evento for evento in self.eventos if not evento.varios_dias]

    @property
    def colores(self):
        """Hasta PUNTOS colores distintos de sus eventos (los puntos del mes en miniatura). Lo que dura más de una semana
        (una captura de calificaciones de un mes) no marca cada día: llenaría el mes; va en la lista."""
        colores = []
        for evento in self.eventos:
            if evento.color not in colores and not evento.cancelado and (evento.fecha_fin - evento.fecha_inicio).days < 7:
                colores.append(evento.color)
        return colores[:PUNTOS]

    @property
    def con_aviso_de_sin_clases(self):
        """Ya trae su «Sin clases: …» como evento (en la semana no se repite el rótulo)."""
        return any(getattr(evento, 'fuente', '') == 'sin_clases' for evento in self.eventos)


@dataclass
class Semana:
    dias: list
    tramos: list
    carriles: int = 0


def primer_dia(texto, hoy):
    """El primer día del mes pedido («2026-10»); si no es válido, el del mes actual."""
    try:
        anio, mes = (int(parte) for parte in str(texto).split('-'))
        if 1900 <= anio <= 2200 and 1 <= mes <= 12:
            return date(anio, mes, 1)
    except ValueError:
        pass
    return hoy.replace(day=1)


def mes_siguiente(primero):
    return (primero + timedelta(days=32)).replace(day=1)


def mes_anterior(primero):
    return (primero - timedelta(days=1)).replace(day=1)


def rango_visible(primero):
    """Del lunes de la primera semana al domingo de la última."""
    ultimo = mes_siguiente(primero) - timedelta(days=1)
    return primero - timedelta(days=primero.weekday()), ultimo + timedelta(days=6 - ultimo.weekday())


def _orden(evento):
    # El último criterio, como texto: junto a los eventos del colegio van los de otros módulos (Agenda/fuentes.py)
    return (evento.fecha_inicio, -(evento.fecha_fin - evento.fecha_inicio).days, not evento.todo_el_dia,
            evento.hora_inicio or time.min, evento.titulo, str(evento.pk))


def _semana(eventos, lunes, primero, hoy, carriles, sin_clases):
    domingo = lunes + timedelta(days=6)
    dias = [Dia(lunes + timedelta(days=i), primero is None or (lunes + timedelta(days=i)).month == primero.month,
                lunes + timedelta(days=i) == hoy, i + 1, sin_clases=sin_clases.get(lunes + timedelta(days=i), '')) for i in range(7)]
    tramos, ocupado = [], []   # ocupado[carril] = última columna usada
    for evento in eventos:
        if evento.fecha_fin < lunes or evento.fecha_inicio > domingo:
            continue
        inicio = max(evento.fecha_inicio, lunes)
        fin = min(evento.fecha_fin, domingo)
        tramo = Tramo(evento, (inicio - lunes).days + 1, (fin - lunes).days + 1, evento.fecha_inicio < lunes, evento.fecha_fin > domingo)
        carril = next((c for c, columna in enumerate(ocupado) if columna < tramo.inicio), len(ocupado))
        if carril == len(ocupado):
            ocupado.append(tramo.fin)
        else:
            ocupado[carril] = tramo.fin
        tramo.carril = carril
        tramos.append(tramo)
        for columna in range(tramo.inicio, tramo.fin + 1):
            dia = dias[columna - 1]
            dia.eventos.append(evento)
            if carriles is not None and carril >= carriles:
                dia.ocultos += 1
    visibles = [t for t in tramos if carriles is None or t.carril < carriles]
    return Semana(dias=dias, tramos=visibles, carriles=len(ocupado) if carriles is None else min(len(ocupado), carriles))


def semanas(eventos, primero, hoy, carriles=CARRILES, sin_clases=None):
    desde, hasta = rango_visible(primero)
    eventos = sorted(eventos, key=_orden)
    lista = []
    lunes = desde
    while lunes <= hasta:
        lista.append(_semana(eventos, lunes, primero, hoy, carriles, sin_clases or {}))
        lunes += timedelta(days=7)
    return lista


def semana_en_columnas(eventos, lunes, hoy, sin_clases=None):
    """La semana en siete columnas: los eventos de varios días como barras arriba (todos, sin «+N») y, en cada día
    (`Dia.de_un_dia`), sus eventos de un día."""
    varios = sorted([e for e in eventos if e.varios_dias], key=_orden)
    semana = _semana(varios, lunes, None, hoy, None, sin_clases or {})
    for evento in sorted(eventos, key=_orden):
        if evento.varios_dias:
            continue
        for dia in semana.dias:
            if dia.fecha == evento.fecha_inicio:
                dia.eventos.append(evento)
    return semana


def mini_mes(primero, eventos, hoy, sin_clases=None):
    """El mes en miniatura: [[Dia]] por semana, con los eventos de cada día (para sus puntos de color)."""
    return [semana.dias for semana in semanas(eventos, primero, hoy, carriles=None, sin_clases=sin_clases)]


def agenda_del_mes(eventos, primero):
    """Para la vista de agenda (teléfono): [(fecha, [eventos])] del mes, cada evento una vez, en el primer día del mes
    en que ocurre."""
    ultimo = mes_siguiente(primero) - timedelta(days=1)
    por_dia = {}
    for evento in sorted(eventos, key=_orden):
        if evento.fecha_fin < primero or evento.fecha_inicio > ultimo:
            continue
        dia = max(evento.fecha_inicio, primero)
        por_dia.setdefault(dia, []).append(evento)
    return sorted(por_dia.items())


def meses_del_ciclo(inicio, fin, eventos, hoy, sin_clases=None):
    """Los meses de un ciclo escolar: [{'primero', 'semanas' (en miniatura), 'eventos'}]. En la lista de cada mes, un
    evento que se repite aparece una sola vez (el primero de ese mes) y lo de otros módulos sin fecha propia del colegio
    (comunicados, reuniones) no aparece: es la vista general del ciclo."""
    meses = []
    primero = inicio.replace(day=1)
    while primero <= fin:
        ultimo = mes_siguiente(primero) - timedelta(days=1)
        del_mes = [e for e in eventos if e.fecha_inicio <= ultimo and e.fecha_fin >= primero]
        lista, series = [], set()
        for evento in sorted(del_mes, key=_orden):
            if getattr(evento, 'fuente', '') in ('comunicado', 'reunion'):
                continue
            if evento.serie:
                if evento.serie in series:
                    continue
                series.add(evento.serie)
            lista.append(evento)
        meses.append({'primero': primero, 'semanas': mini_mes(primero, del_mes, hoy, sin_clases), 'eventos': lista})
        primero = mes_siguiente(primero)
    return meses
