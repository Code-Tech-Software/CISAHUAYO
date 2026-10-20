"""La tabla de profesores (pedido del 2026-10-20): su carga contra su tope semanal, las señales junto al nombre y los
órdenes que no salen de la base de datos (por nivel, por materias y por carga).

La carga son los minutos de clase por semana del ciclo actual (de los horarios ya armados, Alumnos/horarios.py). Con
«Horas máximas por semana» en su ficha se compara contra ese tope: cerca (desde el 85 %), en su tope o lo rebasa.
"""
from collections import defaultdict

from Alumnos.horarios import formatear_duracion, minutos_por_profesor
from Alumnos.models import MateriaGrado, ORDEN_NIVELES, ProfesorMateria
from Alumnos.tabla import columnas_de_orden

COLUMNAS = ('nombre', 'niveles', 'materias', 'carga')
CERCA = 85   # % del tope desde el que se avisa
# Los órdenes que se calculan aquí (sobre todos los profesores del filtro, no solo la página)
EN_PYTHON = {'niveles', 'materias', 'carga'}


def columnas(orden):
    return columnas_de_orden(orden, COLUMNAS)


def necesita_todos(datos):
    """Si el orden o el filtro piden la carga (o el nivel) de todos los profesores del filtro, no solo de la página."""
    return datos.get('orden', 'nombre').lstrip('-') in EN_PYTHON or datos.get('situacion') == 'rebasa'


def rebasa(profesor, minutos):
    return bool(profesor.horas_maximas) and minutos > profesor.horas_maximas * 60


def ordenar_y_filtrar(profesores, datos, minutos):
    """La lista con el filtro «Rebasa su tope» y el orden por nivel, materias o carga (los demás ya vienen de la base).
    El orden es estable: a igual nivel, materias o carga, quedan por nombre."""
    if datos.get('situacion') == 'rebasa':
        profesores = [p for p in profesores if rebasa(p, minutos[p.pk])]
    orden = datos.get('orden', 'nombre')
    campo = orden.lstrip('-')
    if campo in EN_PYTHON:
        claves = {
            'niveles': lambda p: min((ORDEN_NIVELES.index(n) for n in p.niveles_lista), default=len(ORDEN_NIVELES)),
            'materias': lambda p: getattr(p, 'materias', 0),
            'carga': lambda p: minutos[p.pk],
        }
        profesores = sorted(profesores, key=claves[campo], reverse=orden.startswith('-'))
    return profesores


def carga(profesor, minutos):
    """{'texto', 'tope', 'porcentaje', 'estado', 'aviso'}: «18 h de 20 h», el porcentaje del tope (None sin tope) y el
    aviso cuando está cerca, en su tope o lo rebasa (vacío si no hay que avisar)."""
    texto = formatear_duracion(minutos) if minutos else ''
    if not profesor.horas_maximas:
        return {'texto': texto, 'tope': None, 'porcentaje': None, 'estado': 'sin_tope', 'aviso': ''}
    porcentaje = round(minutos * 100 / (profesor.horas_maximas * 60))
    if porcentaje > 100:
        estado, aviso = 'rebasa', 'Rebasa su tope'
    elif porcentaje == 100:
        estado, aviso = 'tope', 'En su tope'
    elif porcentaje >= CERCA:
        estado, aviso = 'cerca', 'Cerca de su tope'
    else:
        estado, aviso = 'normal', ''
    return {'texto': texto, 'tope': f'{profesor.horas_maximas} h', 'porcentaje': porcentaje, 'estado': estado, 'aviso': aviso}


def _sin_habilitar(profesores, ciclo):
    """{id de profesor: cuántas materias imparte en el ciclo sin estar habilitado para ellas}."""
    conteo = defaultdict(int)
    ids = [p.pk for p in profesores]
    if not (ciclo and ids):
        return conteo
    habilitadas = set(ProfesorMateria.objects.filter(profesor__in=ids).values_list('profesor_id', 'materia_id'))
    imparte = set(MateriaGrado.objects.filter(profesor__in=ids, ciclo=ciclo, activa=True).values_list('profesor_id', 'materia_id'))
    for profesor_id, materia_id in imparte - habilitadas:
        conteo[profesor_id] += 1
    return conteo


def senales(profesores, ciclo):
    """{id de profesor: [{'clave', 'icono', 'texto', 'tono'}]}: solo las que aplican y solo de los profesores activos
    (sin cuenta de acceso, cuenta desactivada, sin niveles, o materias que imparte sin estar habilitado)."""
    sin_habilitar = _sin_habilitar(profesores, ciclo)
    resultado = {}
    for profesor in profesores:
        lista = []
        if profesor.estatus == 'ACTIVO':
            if profesor.usuario_id is None:
                lista.append({'clave': 'sin_cuenta', 'icono': 'key', 'texto': 'Sin cuenta de acceso al sistema', 'tono': 'baja'})
            elif not profesor.usuario.is_active:
                lista.append({'clave': 'cuenta_inactiva', 'icono': 'lock', 'texto': f'Su cuenta «{profesor.usuario.username}» está desactivada', 'tono': 'media'})
            if not profesor.niveles_lista:
                lista.append({'clave': 'sin_niveles', 'icono': 'layers', 'texto': 'Sin niveles registrados: no se le pueden asignar materias', 'tono': 'media'})
            if sin_habilitar[profesor.pk]:
                n = sin_habilitar[profesor.pk]
                lista.append({'clave': 'sin_habilitar', 'icono': 'triangle-alert', 'tono': 'alta',
                              'texto': f'Imparte {n} materia{"s" if n != 1 else ""} sin estar habilitado para ella{"s" if n != 1 else ""}'})
        resultado[profesor.pk] = lista
    return resultado


def preparar_filas(profesores, ciclo, minutos=None):
    """Pone en cada profesor de la página `carga` y `senales` (con `minutos`, los ya calculados de todos)."""
    profesores = list(profesores)
    if minutos is None:
        minutos = minutos_por_profesor([p.pk for p in profesores], ciclo)
    de_cada_uno = senales(profesores, ciclo)
    for profesor in profesores:
        profesor.minutos = minutos[profesor.pk]
        profesor.carga = carga(profesor, profesor.minutos)
        profesor.senales = de_cada_uno[profesor.pk]
    return profesores
