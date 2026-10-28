"""El mes del calendario: semanas de lunes a domingo (con los días del mes anterior y del siguiente que completan la
primera y la última) y, en cada semana, los eventos como barras que ocupan sus días.

Un evento de varios días se dibuja como una barra por semana que toca; si empieza antes o sigue después de esa semana
(o del mes), la barra lo indica. Cada semana acomoda sus barras en carriles (renglones) sin encimarlas; caben
`CARRILES` y lo que no cabe se cuenta por día como «+N eventos», con la lista completa de ese día.
"""
from dataclasses import dataclass, field
from datetime import date, time, timedelta

from django.utils.formats import date_format

CARRILES = 3


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

    @property
    def texto(self):
        return date_format(self.fecha, 'l j \\d\\e F').capitalize()


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


def semanas(eventos, primero, hoy, carriles=CARRILES):
    desde, hasta = rango_visible(primero)
    eventos = sorted(eventos, key=_orden)
    lista = []
    lunes = desde
    while lunes <= hasta:
        domingo = lunes + timedelta(days=6)
        dias = [Dia(lunes + timedelta(days=i), (lunes + timedelta(days=i)).month == primero.month, lunes + timedelta(days=i) == hoy, i + 1)
                for i in range(7)]
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
                if carril >= carriles:
                    dia.ocultos += 1
        visibles = [t for t in tramos if t.carril < carriles]
        lista.append(Semana(dias=dias, tramos=visibles, carriles=min(len(ocupado), carriles)))
        lunes += timedelta(days=7)
    return lista


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
