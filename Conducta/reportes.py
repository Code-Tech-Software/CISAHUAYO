"""Reportes de conducta: un solo `contenido` (mismos filtros y mismos conteos) para la vista previa, la hoja para
imprimir o guardar en PDF y el libro de Excel. Cada incidente cuenta una vez aunque tenga varias medidas; los
estudiantes involucrados se cuentan aparte; los anulados quedan fuera salvo que se pidan.
"""
from django.utils import timezone

from CISAHUAYO.xlsx import ENCABEZADO, SECCION, TITULO, Celda, Hoja

from . import reglas
from .forms import TiposDeReporte as Tipos
from .models import INCIDENCIA, RegistroConducta

COLEGIO = 'Colegio Interamericano de Sahuayo'
TITULOS = dict(Tipos.REPORTES)


def _nombre(usuario):
    return (usuario.get_full_name() or usuario.get_username()) if usuario else ''


def construir(tipo, filtro, usuario, hoy=None, registros=None, titulos=None):
    """El contenido del reporte; `registros` limita a lo que la persona puede ver (su alcance)."""
    hoy = hoy or timezone.localdate()
    titulos = titulos or TITULOS
    registros = filtro.aplicar(RegistroConducta.objects.all() if registros is None else registros)
    _, _, aviso = filtro.rango()
    contenido = {
        'tipo': tipo, 'titulo': f'Reporte de conducta · {titulos[tipo]}', 'subtitulo': titulos[tipo],
        'filtros': filtro.descripcion(), 'aviso': aviso, 'generado': timezone.localtime(), 'usuario': _nombre(usuario),
        'hoy': hoy, 'vacio': False,
    }
    if tipo == Tipos.RESUMEN:
        contenido['resumen'] = reglas.resumen_estadistico(registros, filtro, hoy)
        contenido['vacio'] = contenido['resumen']['total'] == 0
    elif tipo == Tipos.GRUPO:
        lista = list(reglas.con_relaciones(reglas.ordenados_por_nivel(registros)))
        contenido.update({
            'registros': lista, 'totales': reglas.totales_por(registros),
            'incidencias': sum(1 for r in lista if r.tipo == INCIDENCIA),
            'positivas': sum(1 for r in lista if r.tipo != INCIDENCIA),
            'estudiantes': len({r.alumno_id for r in lista}), 'vacio': not lista,
        })
    elif tipo == Tipos.HISTORIAL:
        contenido['sin_estudiantes'] = not filtro.alumnos
        contenido['historiales'] = reglas.historial_individual(registros, filtro.alumnos)
        contenido['vacio'] = not any(h['registros'] for h in contenido['historiales'])
    else:
        contenido['suspensiones'] = reglas.suspensiones_de(registros, hoy)
        contenido['vacio'] = not contenido['suspensiones']
    return contenido


# ---------------------------------------------------------------------------
# Excel: las mismas tablas que la pantalla
# ---------------------------------------------------------------------------
def _encabezado(contenido):
    filas = [
        [Celda(COLEGIO, TITULO)],
        [Celda(contenido['titulo'], SECCION)],
        ['Generado', contenido['generado'].strftime('%d/%m/%Y %H:%M')],
        ['Generado por', contenido['usuario']],
    ]
    filas += [[f'Filtro: {nombre}', valor] for nombre, valor in contenido['filtros']]
    if contenido['aviso']:
        filas.append(['Aviso', contenido['aviso']])
    filas.append([])
    return filas


def _titulos(*nombres):
    return [Celda(nombre, ENCABEZADO) for nombre in nombres]


def _medidas(registro):
    return ', '.join(m.nombre + (' (pendiente de aprobación)' if m.pendiente else '') for m in registro.medidas_aplicadas.all()
                     if m.estado in ('APLICADA', 'PENDIENTE'))


def _suspension_texto(registro):
    suspension = getattr(registro, 'suspension', None)
    if suspension is None or suspension.aprobacion == 'CANCELADA':
        return ''
    texto = f'{suspension.motivo_nombre}: {suspension.fecha_inicio:%d/%m/%Y} al {suspension.fecha_fin:%d/%m/%Y}'
    return texto if suspension.aprobada else f'{texto} ({suspension.get_aprobacion_display().lower()})'


def _fila_de_registro(r):
    return [
        r.fecha, r.hora.strftime('%H:%M') if r.hora else '', str(r.alumno), r.alumno.referencia, reglas.NOMBRE_DE_NIVEL[r.nivel],
        r.grupo_texto, reglas.NOMBRE_DE_TIPO[r.tipo], r.categoria_nombre, r.motivo_nombre, reglas.NOMBRE_DE_GRAVEDAD.get(r.gravedad, ''),
        _medidas(r), _suspension_texto(r), r.get_estado_display(), _nombre(r.registrado_por), 'Anulado' if r.anulado else '',
    ]


TITULOS_DE_REGISTRO = ('Fecha', 'Hora', 'Estudiante', 'Número de control', 'Nivel', 'Grupo', 'Tipo', 'Categoría', 'Motivo',
                       'Gravedad', 'Medidas', 'Suspensión', 'Seguimiento', 'Registró', 'Anulado')
ANCHOS_DE_REGISTRO = [11, 7, 30, 14, 13, 18, 16, 22, 26, 11, 30, 30, 15, 20, 9]


def hojas(contenido):
    tipo = contenido['tipo']
    if tipo == Tipos.RESUMEN:
        r = contenido['resumen']
        filas = _encabezado(contenido) + [
            _titulos('Indicador', 'Total'),
            ['Incidencias (incidentes)', r['incidencias']],
            ['Conductas positivas', r['positivas']],
            ['Estudiantes con registros', r['estudiantes']],
            ['Estudiantes con incidencias', r['estudiantes_con_incidencias']],
            ['Registros con medidas disciplinarias', r['registros_con_medidas']],
            ['Suspensiones aprobadas', r['suspensiones']],
            ['Solicitudes de suspensión pendientes', r['solicitudes_pendientes']],
            ['Suspensiones vigentes hoy', r['suspensiones_vigentes']],
            ['Estudiantes suspendidos', r['estudiantes_suspendidos']],
            ['Casos abiertos', r['pendientes']],
            ['Seguimientos en curso', r['en_seguimiento']],
            ['Seguimientos cerrados', r['cerrados']],
            ['Seguimientos vencidos', r['vencidos']],
            [],
        ]
        for titulo, columna, datos in (
            ('Categorías más frecuentes', 'Categoría', r['categorias']),
            ('Motivos más frecuentes', 'Motivo', r['motivos']),
            ('Incidencias por gravedad', 'Gravedad', r['gravedades']),
            ('Medidas disciplinarias aplicadas (registros)', 'Medida', r['medidas']),
        ):
            filas += [[Celda(titulo, SECCION)], _titulos(columna, 'Registros'), *[[n, t] for n, t in datos], []]
        filas += [[Celda(f'Evolución por {r["unidad"]}', SECCION)], _titulos('Periodo', 'Incidencias', 'Conductas positivas')]
        filas += [[e['etiqueta'], e['incidencias'], e['positivas']] for e in r['evolucion']]
        return [Hoja('Resumen', filas, anchos=[44, 14, 20])]

    if tipo == Tipos.GRUPO:
        filas = _encabezado(contenido) + [
            ['Incidencias', contenido['incidencias']], ['Conductas positivas', contenido['positivas']],
            ['Estudiantes', contenido['estudiantes']], [],
            _titulos(*TITULOS_DE_REGISTRO), *[_fila_de_registro(r) for r in contenido['registros']],
        ]
        totales = contenido['totales']
        filas_totales = _encabezado(contenido)
        for titulo, columna, datos in (('Por categoría', 'Categoría', totales['categorias']), ('Por motivo', 'Motivo', totales['motivos']),
                                       ('Por gravedad', 'Gravedad', totales['gravedades'])):
            filas_totales += [[Celda(titulo, SECCION)], _titulos(columna, 'Registros'), *[[n, t] for n, t in datos], []]
        return [Hoja('Registros', filas, anchos=ANCHOS_DE_REGISTRO), Hoja('Totales', filas_totales, anchos=[40, 12])]

    if tipo == Tipos.HISTORIAL:
        filas = _encabezado(contenido)
        for historial in contenido['historiales']:
            alumno = historial['alumno']
            filas += [
                [Celda(f'{alumno} · {alumno.referencia}', SECCION)],
                ['Grupo actual', str(historial['inscripcion'].grupo) if historial['inscripcion'] else 'Sin inscripción vigente'],
                ['Incidencias', historial['incidencias'], 'Conductas positivas', historial['positivas'], 'Suspensiones', historial['suspensiones']],
                _titulos('Fecha', 'Tipo', 'Categoría', 'Motivo', 'Gravedad', 'Hechos', 'Medidas', 'Suspensión', 'Acuerdos', 'Seguimiento', 'Contactos con la familia', 'Anulado'),
            ]
            for r in historial['registros']:
                contactos = '; '.join(f'{c.fecha:%d/%m/%Y} {c.persona} ({c.get_medio_display()}): {c.acuerdos}' for c in r.contactos.all())
                filas.append([
                    r.fecha, reglas.NOMBRE_DE_TIPO[r.tipo], r.categoria_nombre, r.motivo_nombre, reglas.NOMBRE_DE_GRAVEDAD.get(r.gravedad, ''),
                    r.descripcion, _medidas(r), _suspension_texto(r), r.acuerdos, r.get_estado_display(), contactos, 'Anulado' if r.anulado else '',
                ])
            filas.append([])
        return [Hoja('Historial', filas, anchos=[11, 16, 22, 26, 11, 50, 28, 30, 40, 15, 50, 9])]

    filas = _encabezado(contenido) + [
        _titulos('Estudiante', 'Número de control', 'Grupo', 'Motivo', 'Inicio', 'Término', 'Días', 'Solicitó', 'Autorizó o resolvió', 'Estado',
                 'Justificación', 'Observaciones'),
    ]
    for fila in contenido['suspensiones']:
        s, r = fila['suspension'], fila['registro']
        filas.append([str(r.alumno), r.alumno.referencia, r.grupo_texto, s.motivo_nombre, s.fecha_inicio, s.fecha_fin, s.dias,
                      _nombre(s.solicitada_por), _nombre(s.autorizada_por if s.aprobada else s.resuelta_por), fila['estado_display'],
                      s.justificacion, s.observaciones])
    return [Hoja('Suspensiones', filas, anchos=[30, 14, 18, 28, 11, 11, 6, 22, 22, 22, 40, 40])]
