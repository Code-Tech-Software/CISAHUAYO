"""«Observaciones de bitácora» en los reportes de conducta (Conducta/reportes.py, también los de prefectura).

Se leen de las entradas originales, sin copiarlas a Conducta, y solo las que la persona puede consultar en la bitácora
(su alcance; sin permiso de bitácora, la sección no aparece). Respetan el ciclo, el periodo o las fechas y el nivel,
grado o grupo del reporte; las anuladas nunca aparecen. Son una sección aparte: no se suman a incidencias, positivas,
medidas ni suspensiones.
- Reporte por grupo: las entradas de los grupos del filtro, con sus observaciones generales.
- Historial individual: solo las entradas que nombran al estudiante (nunca las generales), sin los nombres de los demás.
"""
from django.db.models import Count, Prefetch

from .alcance import alcance_de_bitacoras, puede_entrar
from .models import SELLO, EstudianteBitacora

TITULO = 'Observaciones de bitácora'


def puede_incluir(usuario):
    return puede_entrar(usuario)


def _entradas(usuario, filtro):
    inicio, fin, aviso = filtro.rango()
    entradas = alcance_de_bitacoras(usuario).entradas()
    if aviso:
        return entradas.none()
    if filtro.ciclo is not None:
        entradas = entradas.filter(ciclo=filtro.ciclo)
    if inicio:
        entradas = entradas.filter(fecha__gte=inicio)
    if fin:
        entradas = entradas.filter(fecha__lte=fin)
    nivel = filtro.periodo.nivel if filtro.periodo is not None else filtro.nivel
    if nivel:
        entradas = entradas.filter(nivel=nivel)
    if filtro.grupo is not None:
        entradas = entradas.filter(grupo=filtro.grupo)
    elif filtro.grado is not None:
        entradas = entradas.filter(grado=filtro.grado)
    return entradas.select_related('autor', 'periodo').order_by('-fecha', '-hora_inicio', '-creado', '-pk')


def del_grupo(usuario, filtro):
    """Las entradas de los grupos del reporte (con las observaciones generales y los estudiantes de cada una)."""
    return list(_entradas(usuario, filtro).prefetch_related(
        Prefetch('vinculos', queryset=EstudianteBitacora.objects.select_related('alumno').order_by('alumno__apellido_paterno', 'alumno__nombre')),
    ))


def del_alumno(usuario, filtro, alumno):
    """Las entradas que nombran al estudiante (sin las observaciones generales del grupo)."""
    return list(_entradas(usuario, filtro).filter(pk__in=EstudianteBitacora.objects.filter(alumno=alumno).values('entrada'))
                .annotate(implicados=Count('vinculos', distinct=True)))


def agregar_a(contenido, tipo, filtro, usuario, grupal, individual):
    """Agrega la sección al contenido de un reporte de conducta (si aplica a ese tipo y la persona puede verla)."""
    if tipo not in (grupal, individual):
        return contenido
    disponible = puede_incluir(usuario)
    contenido.update(bitacora_disponible=disponible, bitacora_incluida=disponible and filtro.bitacora, bitacora_sello=SELLO,
                     bitacora_titulo=TITULO)
    if not contenido['bitacora_incluida']:
        return contenido
    if tipo == grupal:
        contenido['bitacora'] = del_grupo(usuario, filtro)
    else:
        for historial in contenido['historiales']:
            historial['bitacora'] = del_alumno(usuario, filtro, historial['alumno'])
    return contenido


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------
def _hora(entrada):
    return f'{entrada.hora_inicio:%H:%M}–{entrada.hora_fin:%H:%M}' if entrada.hora_inicio and entrada.hora_fin else ''


def fila_grupal(entrada):
    implicados = 'Observación general del grupo' if entrada.general else ', '.join(str(v.alumno) for v in entrada.vinculos.all())
    return [entrada.fecha, _hora(entrada), entrada.grupo_texto, entrada.materia_nombre, entrada.autor_nombre, implicados,
            entrada.titulo, entrada.descripcion, entrada.seguimiento, SELLO]


def fila_individual(entrada):
    return [entrada.fecha, _hora(entrada), entrada.grupo_texto, entrada.materia_nombre, entrada.autor_nombre, entrada.titulo,
            entrada.descripcion, entrada.seguimiento, SELLO]


TITULOS_GRUPALES = ('Fecha de la clase', 'Bloque', 'Grupo', 'Materia', 'Autor', 'Estudiantes', 'Título', 'Descripción', 'Acuerdos o seguimiento', 'Carácter')
ANCHOS_GRUPALES = [12, 12, 18, 22, 22, 36, 30, 60, 40, 38]
TITULOS_INDIVIDUALES = ('Fecha de la clase', 'Bloque', 'Grupo', 'Materia', 'Autor', 'Título', 'Descripción', 'Acuerdos o seguimiento', 'Carácter')
