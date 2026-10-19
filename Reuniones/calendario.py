"""Las vistas de la agenda de reuniones: día (una columna por sala), semana (una columna por día de atención) y mes (el
mismo cálculo de la Agenda del colegio: Agenda/calendario.py). La lista está en las vistas.

En el día y la semana cada reunión es un bloque colocado por su horario (porcentajes de la columna); las que se empalman
en la misma columna (distintas salas el mismo día, o reuniones canceladas a la misma hora) se reparten el ancho.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from django.utils.formats import date_format

from Agenda import calendario as calendario_del_mes

VISTAS = (('dia', 'Día'), ('semana', 'Semana'), ('mes', 'Mes'), ('lista', 'Lista'))
ALTO_POR_HORA = 5.5    # rem: una reunión de 30 minutos muestra hora, familia y sala


@dataclass
class Bloque:
    reunion: object
    arriba: float
    alto: float
    izquierda: float
    ancho: float


@dataclass
class Columna:
    clave: str
    titulo: str
    subtitulo: str = ''
    fecha: date = None
    es_hoy: bool = False
    bloques: list = field(default_factory=list)


@dataclass
class Rejilla:
    columnas: list
    horas: list           # [(texto, arriba %)]
    alto: float           # rem


def fecha_pedida(texto, hoy):
    try:
        return date.fromisoformat(str(texto))
    except ValueError:
        return hoy


def _minutos(hora):
    return hora.hour * 60 + hora.minute


def _acomodar(reuniones):
    """[(reunión, carril, carriles del grupo)]: las que se empalman van lado a lado."""
    resultado, grupo, fines, fin_del_grupo = [], [], [], None

    def cerrar():
        for reunion, carril in grupo:
            resultado.append((reunion, carril, len(fines)))

    for reunion in sorted(reuniones, key=lambda r: (r.hora_inicio, r.hora_fin, r.pk)):
        if fin_del_grupo is not None and reunion.hora_inicio >= fin_del_grupo:
            cerrar()
            grupo, fines, fin_del_grupo = [], [], None
        carril = next((i for i, fin in enumerate(fines) if fin <= reunion.hora_inicio), None)
        if carril is None:
            fines.append(reunion.hora_fin)
            carril = len(fines) - 1
        else:
            fines[carril] = reunion.hora_fin
        grupo.append((reunion, carril))
        fin_del_grupo = reunion.hora_fin if fin_del_grupo is None else max(fin_del_grupo, reunion.hora_fin)
    if grupo:
        cerrar()
    return resultado


def _rango(configuracion, reuniones):
    desde = min([configuracion.hora_apertura] + [r.hora_inicio for r in reuniones])
    hasta = max([configuracion.hora_cierre] + [r.hora_fin for r in reuniones])
    inicio = desde.hour
    fin = hasta.hour + (1 if hasta.minute or hasta.second else 0)
    return inicio, max(fin, inicio + 1)


def _rejilla(definiciones, configuracion):
    """`definiciones`: [(Columna, [reuniones])]."""
    todas = [r for _, reuniones in definiciones for r in reuniones]
    inicio, fin = _rango(configuracion, todas)
    total = (fin - inicio) * 60
    columnas = []
    for columna, reuniones in definiciones:
        for reunion, carril, carriles in _acomodar(reuniones):
            arriba = (_minutos(reunion.hora_inicio) - inicio * 60) / total * 100
            alto = max(_minutos(reunion.hora_fin) - _minutos(reunion.hora_inicio), 10) / total * 100
            columna.bloques.append(Bloque(reunion, round(arriba, 3), round(alto, 3), round(carril / carriles * 100, 3), round(100 / carriles, 3)))
        columnas.append(columna)
    horas = [(f'{h:02d}:00', round((h - inicio) * 60 / total * 100, 3)) for h in range(inicio, fin)]
    return Rejilla(columnas=columnas, horas=horas, alto=(fin - inicio) * ALTO_POR_HORA)


def dia(reuniones, fecha, salas, configuracion):
    """Una columna por sala (las activas y las que tengan reuniones ese día)."""
    reuniones = [r for r in reuniones if r.fecha == fecha and r.programada]
    usadas = {r.sala_id for r in reuniones}
    columnas = []
    for sala in salas:
        if sala.activo or sala.pk in usadas:
            columnas.append((Columna(clave=str(sala.pk), titulo=sala.nombre, subtitulo=sala.ubicacion), [r for r in reuniones if r.sala_id == sala.pk]))
    sin_sala = [r for r in reuniones if r.sala_id is None]
    if sin_sala:
        columnas.append((Columna(clave='sin-sala', titulo='Sin sala'), sin_sala))
    return _rejilla(columnas, configuracion)


def lunes_de(fecha):
    return fecha - timedelta(days=fecha.weekday())


def semana(reuniones, fecha, hoy, configuracion):
    """Una columna por día de atención de la semana (y por cualquier otro día con reuniones)."""
    lunes = lunes_de(fecha)
    dias = [lunes + timedelta(days=i) for i in range(7)]
    reuniones = [r for r in reuniones if r.programada and lunes <= r.fecha <= dias[-1]]
    con_reuniones = {r.fecha for r in reuniones}
    columnas = []
    for dia_ in dias:
        if dia_.weekday() in (configuracion.dias or []) or dia_ in con_reuniones:
            columna = Columna(clave=dia_.isoformat(), titulo=date_format(dia_, 'D j').capitalize(), fecha=dia_, es_hoy=dia_ == hoy,
                              subtitulo=date_format(dia_, 'l').capitalize())
            columnas.append((columna, [r for r in reuniones if r.fecha == dia_]))
    return _rejilla(columnas, configuracion)


def mes(reuniones, fecha, hoy):
    primero = fecha.replace(day=1)
    return calendario_del_mes.semanas([r for r in reuniones if r.programada], primero, hoy)


def periodo(vista, fecha):
    """(desde, hasta) de lo que muestra la vista."""
    if vista == 'dia':
        return fecha, fecha
    if vista == 'semana':
        lunes = lunes_de(fecha)
        return lunes, lunes + timedelta(days=6)
    primero = fecha.replace(day=1)
    return calendario_del_mes.rango_visible(primero)


def navegacion(vista, fecha):
    """(anterior, siguiente) de la vista."""
    if vista == 'dia':
        return fecha - timedelta(days=1), fecha + timedelta(days=1)
    if vista == 'semana':
        return fecha - timedelta(days=7), fecha + timedelta(days=7)
    primero = fecha.replace(day=1)
    return calendario_del_mes.mes_anterior(primero), calendario_del_mes.mes_siguiente(primero)


def titulo(vista, fecha):
    if vista == 'dia':
        return date_format(fecha, 'l j \\d\\e F \\d\\e Y').capitalize()
    if vista == 'semana':
        lunes = lunes_de(fecha)
        domingo = lunes + timedelta(days=6)
        if lunes.month == domingo.month:
            return f'Del {lunes.day} al {date_format(domingo, "j \\d\\e F \\d\\e Y").lower()}'
        return f'Del {date_format(lunes, "j \\d\\e F").lower()} al {date_format(domingo, "j \\d\\e F \\d\\e Y").lower()}'
    return date_format(fecha, 'F Y').capitalize()


def ahora_en(rejilla_, hoy, ahora):
    """La posición (%) de la línea de «ahora» si cae dentro del rango de horas, o None."""
    if not rejilla_.horas:
        return None
    inicio = int(rejilla_.horas[0][0][:2])
    total = len(rejilla_.horas) * 60
    minutos = _minutos(ahora) - inicio * 60
    return round(minutos / total * 100, 3) if 0 <= minutos <= total else None


def combinar(fecha, hora):
    return datetime.combine(fecha, hora or time.min)
