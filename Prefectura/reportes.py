"""Reportes de prefectura: un solo `contenido` (mismos filtros y mismos conteos) para la vista previa, la hoja para
imprimir o guardar en PDF y el libro de Excel, siempre dentro del alcance de quien lo genera.

Los de conducta (incidencias y reconocimientos, suspensiones e historial) usan Conducta/reportes.py; los de asistencia,
reincidencias, medidas y pendientes se arman aquí con las mismas fuentes de datos. Las faltas por materia (registros)
y los estudiantes con inasistencia se cuentan por separado.
"""
from collections import defaultdict

from django.db.models import Count, Q
from django.utils import timezone

from Alumnos.academico import ciclo_actual
from Alumnos.asistencias import porcentaje
from Alumnos.models import Inscripcion, orden_de_nivel
from CISAHUAYO.xlsx import ENCABEZADO, SECCION, TITULO, Celda, Hoja
from Conducta import reglas
from Conducta import reportes as reportes_de_conducta
from Conducta.models import INCIDENCIA, CitaTutor, Compromiso, MedidaAplicada, RegistroConducta, ReglaReincidencia

from . import asistencia
from .models import MovimientoAcceso

COLEGIO = reportes_de_conducta.COLEGIO
ASISTENCIA, JUSTIFICACIONES, CONDUCTA, REINCIDENCIAS = 'asistencia', 'justificaciones', 'conducta', 'reincidencias'
MEDIDAS, SUSPENSIONES, PENDIENTES, HISTORIAL = 'medidas', 'suspensiones', 'pendientes', 'historial'
TIPOS = [
    (ASISTENCIA, 'Asistencia y retardos'),
    (JUSTIFICACIONES, 'Faltas justificadas y sin justificar'),
    (CONDUCTA, 'Incidencias y reconocimientos'),
    (REINCIDENCIAS, 'Reincidencias'),
    (MEDIDAS, 'Medidas disciplinarias'),
    (SUSPENSIONES, 'Suspensiones'),
    (PENDIENTES, 'Casos y compromisos pendientes'),
    (HISTORIAL, 'Historial individual'),
]
TITULOS = dict(TIPOS)
DE_CONDUCTA = {CONDUCTA: 'grupo', SUSPENSIONES: 'suspensiones', HISTORIAL: 'historial'}


def _nombre(usuario):
    return (usuario.get_full_name() or usuario.get_username()) if usuario else ''


def _rango_de_asistencia(filtro):
    """(desde, hasta, aviso) de la asistencia: el periodo cruzado con las fechas; sin fechas, las del ciclo."""
    inicio, fin, aviso = filtro.rango()
    if aviso:
        return None, None, aviso
    ciclo = filtro.ciclo
    if ciclo is not None:
        inicio, fin = inicio or ciclo.fecha_inicio, fin or ciclo.fecha_fin
    return inicio, fin, None


def _inscripciones(alcance, filtro):
    """Las inscripciones del alcance que cumplen los filtros de nivel, grado, grupo y estudiantes (en el ciclo elegido)."""
    ciclo = filtro.ciclo or ciclo_actual()
    consulta = alcance.filtrar(Inscripcion.objects.filter(ciclo=ciclo), campo='alumno') if ciclo else Inscripcion.objects.none()
    nivel = filtro.periodo.nivel if filtro.periodo is not None else filtro.nivel
    if nivel:
        consulta = consulta.filter(grado__nivel=nivel)
    if filtro.grupo is not None:
        consulta = consulta.filter(grupo=filtro.grupo)
    elif filtro.grado is not None:
        consulta = consulta.filter(grado=filtro.grado)
    if filtro.alumnos:
        consulta = consulta.filter(alumno__in=filtro.alumnos)
    return consulta.select_related('alumno', 'grado', 'grupo__nombre', 'grupo__grado').order_by(
        orden_de_nivel('grado__nivel'), 'grado__numero', 'grupo__nombre__orden', 'alumno__apellido_paterno', 'alumno__apellido_materno', 'alumno__nombre')


def _asistencia(alcance, filtro):
    desde, hasta, aviso = _rango_de_asistencia(filtro)
    inscripciones = list(_inscripciones(alcance, filtro)) if not aviso else []
    ids = [i.pk for i in inscripciones]
    fechas = Q(fecha__range=(desde, hasta)) if desde and hasta else Q()
    materias = {
        fila['inscripcion']: fila for fila in
        asistencia.con_justificada_materia(asistencia.sin_dias_suspendidos(asistencia.AsistenciaMateria.objects.filter(fechas, inscripcion__in=ids))).order_by()
        .values('inscripcion').annotate(
            registros=Count('pk'), presentes=Count('pk', filter=Q(estado='PRESENTE')), retardos=Count('pk', filter=Q(estado='RETARDO')),
            faltas=Count('pk', filter=Q(estado='FALTA')), justificadas=Count('pk', filter=Q(estado='FALTA', justificada=True)),
        )
    }
    entrada = {
        fila['inscripcion']: fila for fila in
        asistencia.sin_dias_suspendidos(asistencia.AsistenciaGeneral.objects.filter(fechas, inscripcion__in=ids)).order_by().values('inscripcion')
        .annotate(retardos=Count('pk', filter=Q(estado='RETARDO')), faltas=Count('pk', filter=Q(estado='FALTA')))
    }
    accesos = defaultdict(dict)
    for fila in (MovimientoAcceso.objects.filter(fechas, inscripcion__in=ids, anulado=False).order_by()
                 .values('inscripcion', 'tipo').annotate(total=Count('pk'))):
        accesos[fila['inscripcion']][fila['tipo']] = fila['total']
    filas, total = [], defaultdict(int)
    for inscripcion in inscripciones:
        m, e, a = materias.get(inscripcion.pk, {}), entrada.get(inscripcion.pk, {}), accesos.get(inscripcion.pk, {})
        fila = {
            'inscripcion': inscripcion, 'alumno': inscripcion.alumno, 'grupo': inscripcion.grupo,
            'registros': m.get('registros', 0), 'presentes': m.get('presentes', 0), 'retardos': m.get('retardos', 0),
            'faltas': m.get('faltas', 0), 'justificadas': m.get('justificadas', 0),
            'retardos_entrada': e.get('retardos', 0), 'faltas_entrada': e.get('faltas', 0),
            'ingreso_tarde': a.get(MovimientoAcceso.RETARDO, 0), 'entradas_posteriores': a.get(MovimientoAcceso.ENTRADA, 0),
            'salidas_anticipadas': a.get(MovimientoAcceso.SALIDA, 0),
        }
        fila['sin_justificar'] = fila['faltas'] - fila['justificadas']
        fila['porcentaje'] = porcentaje(fila['presentes'], fila['retardos'], fila['registros'])
        for clave, valor in fila.items():
            if isinstance(valor, int) and clave != 'porcentaje':
                total[clave] += valor
        filas.append(fila)
    total['porcentaje'] = porcentaje(total['presentes'], total['retardos'], total['registros'])
    total['estudiantes_con_falta'] = sum(1 for f in filas if f['faltas'] or f['faltas_entrada'])
    total['estudiantes_con_retardo'] = sum(1 for f in filas if f['retardos'] or f['retardos_entrada'] or f['ingreso_tarde'])
    return {'filas': filas, 'total': dict(total), 'desde': desde, 'hasta': hasta, 'aviso_asistencia': aviso, 'vacio': not filas}


def _justificaciones(alcance, filtro):
    desde, hasta, aviso = _rango_de_asistencia(filtro)
    ids = list(_inscripciones(alcance, filtro).values_list('pk', flat=True)) if not aviso else []
    fechas = Q(fecha__range=(desde, hasta)) if desde and hasta else Q()
    registros = list(
        asistencia.con_justificada_materia(asistencia.sin_dias_suspendidos(asistencia.AsistenciaMateria.objects.filter(fechas, inscripcion__in=ids, estado__in=('FALTA', 'RETARDO'))))
        .select_related('inscripcion__alumno', 'inscripcion__grupo__nombre', 'inscripcion__grupo__grado', 'materia_grado__materia')
        .order_by('fecha', 'inscripcion__alumno__apellido_paterno', 'materia_grado__materia__nombre')
    )
    cubiertas = {
        j.asistencia_id: j for j in asistencia.Justificacion.objects.filter(activa=True, asistencia__in=[r.pk for r in registros])
        .select_related('registrada_por')
    }
    for registro in registros:
        registro.justificacion = cubiertas.get(registro.pk)
    faltas = [r for r in registros if r.estado == 'FALTA']
    return {
        'registros': registros, 'desde': desde, 'hasta': hasta, 'aviso_asistencia': aviso, 'vacio': not registros,
        'faltas': len(faltas), 'faltas_justificadas': sum(1 for r in faltas if r.justificada),
        'faltas_sin_justificar': sum(1 for r in faltas if not r.justificada),
        'retardos': len(registros) - len(faltas), 'retardos_justificados': sum(1 for r in registros if r.estado == 'RETARDO' and r.justificada),
        'estudiantes': len({r.inscripcion.alumno_id for r in faltas}),
        'estudiantes_sin_justificar': len({r.inscripcion.alumno_id for r in faltas if not r.justificada}),
    }


def _reincidencias(registros):
    """Estudiantes que llegaron al umbral de su nivel (incidencias del mismo motivo) dentro de las fechas: los criterios
    son los que el administrador configuró por nivel. Solo para revisión: no sanciona."""
    umbrales = {r.nivel: r for r in ReglaReincidencia.objects.filter(activa=True)}
    filas = (
        registros.filter(tipo=INCIDENCIA).order_by().values('alumno', 'nivel', 'motivo', 'motivo_nombre')
        .annotate(total=Count('pk', distinct=True))
    )
    alumnos = {r.alumno_id: r.alumno for r in registros.select_related('alumno')}
    salida = []
    for fila in filas:
        regla = umbrales.get(fila['nivel'])
        if regla and fila['total'] >= regla.incidencias:
            salida.append({'alumno': alumnos.get(fila['alumno']), 'nivel': reglas.NOMBRE_DE_NIVEL[fila['nivel']], 'motivo': fila['motivo_nombre'],
                           'total': fila['total'], 'umbral': f'{regla.incidencias} en {regla.dias} días'})
    salida.sort(key=lambda f: (-f['total'], str(f['alumno'])))
    return {'reincidencias': salida, 'reglas': list(umbrales.values()), 'vacio': not salida}


def _medidas(registros):
    filas = list(
        MedidaAplicada.objects.filter(registro__in=registros.values('pk'))
        .select_related('registro__alumno', 'solicitada_por', 'resuelta_por').order_by('registro__fecha', 'nombre')
    )
    totales = defaultdict(lambda: defaultdict(int))
    for medida in filas:
        totales[medida.nombre][medida.estado] += 1
    resumen = [{'nombre': nombre, 'aplicadas': t.get('APLICADA', 0), 'pendientes': t.get('PENDIENTE', 0),
                'rechazadas': t.get('RECHAZADA', 0), 'anuladas': t.get('ANULADA', 0)} for nombre, t in sorted(totales.items())]
    return {'medidas': filas, 'resumen_medidas': resumen, 'vacio': not filas,
            'aplicadas': sum(1 for m in filas if m.estado == 'APLICADA'),
            'registros_con_medidas': len({m.registro_id for m in filas if m.estado == 'APLICADA'})}


def _pendientes(registros):
    abiertos = list(reglas.con_relaciones(registros.filter(anulado=False).exclude(estado=RegistroConducta.CERRADO)).order_by('fecha_revision', 'fecha'))
    ids = registros.filter(anulado=False).values('pk')
    compromisos = list(Compromiso.objects.filter(registro__in=ids, estado=Compromiso.PENDIENTE_C).select_related('registro__alumno', 'responsable').order_by('fecha_limite'))
    citas = list(CitaTutor.objects.filter(registro__in=ids, estado=CitaTutor.PROGRAMADA).select_related('registro__alumno', 'responsable').order_by('fecha', 'hora'))
    return {'abiertos': abiertos, 'compromisos': compromisos, 'citas': citas, 'vacio': not (abiertos or compromisos or citas)}


def construir(tipo, filtro, usuario, alcance, registros, hoy=None):
    """El contenido del reporte (`registros`: los de conducta que la persona puede ver)."""
    hoy = hoy or timezone.localdate()
    if tipo in DE_CONDUCTA:
        contenido = reportes_de_conducta.construir(DE_CONDUCTA[tipo], filtro, usuario, hoy=hoy, registros=registros,
                                                    titulos={DE_CONDUCTA[tipo]: TITULOS[tipo]})
        contenido.update(tipo_prefectura=tipo, titulo=f'Reporte de prefectura · {TITULOS[tipo]}')
        if tipo == HISTORIAL:
            contenido['asistencias'] = {fila['alumno'].pk: fila for fila in _asistencia(alcance, filtro)['filas']} if filtro.alumnos else {}
        return contenido
    _, _, aviso = filtro.rango()
    contenido = {
        'tipo': tipo, 'tipo_prefectura': tipo, 'titulo': f'Reporte de prefectura · {TITULOS[tipo]}', 'subtitulo': TITULOS[tipo],
        'filtros': filtro.descripcion(), 'aviso': aviso, 'generado': timezone.localtime(), 'usuario': _nombre(usuario), 'hoy': hoy,
    }
    if tipo == ASISTENCIA:
        contenido.update(_asistencia(alcance, filtro))
    elif tipo == JUSTIFICACIONES:
        contenido.update(_justificaciones(alcance, filtro))
    else:
        filtrados = filtro.aplicar(registros)
        contenido.update({REINCIDENCIAS: _reincidencias, MEDIDAS: _medidas, PENDIENTES: _pendientes}[tipo](filtrados))
    if contenido.get('aviso_asistencia') and not contenido['aviso']:
        contenido['aviso'] = contenido['aviso_asistencia']
    if tipo in (ASISTENCIA, JUSTIFICACIONES) and contenido.get('desde'):
        # De la asistencia no aplican los criterios propios de la conducta
        contenido['filtros'] = [f for f in contenido['filtros'] if f[0] not in ('Fechas del hecho', 'Registros', 'Tipo', 'Categoría', 'Motivo', 'Gravedad', 'Medida', 'Suspensión', 'Seguimiento')] + [
            ('Fechas de asistencia', f"{contenido['desde']:%d/%m/%Y} al {contenido['hasta']:%d/%m/%Y}")]
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
    if contenido.get('aviso'):
        filas.append(['Aviso', contenido['aviso']])
    filas.append([])
    return filas


def _titulos(*nombres):
    return [Celda(nombre, ENCABEZADO) for nombre in nombres]


def _quien(usuario):
    return _nombre(usuario)


def hojas(contenido):
    tipo = contenido['tipo_prefectura']
    if tipo in DE_CONDUCTA:
        libro = reportes_de_conducta.hojas(contenido)
        if tipo == HISTORIAL and contenido.get('asistencias'):
            filas = _encabezado(contenido) + [_titulos('Estudiante', 'Faltas por materia', 'Justificadas', 'Retardos por materia',
                                                       'Faltas de entrada', 'Retardos de entrada', 'Retardos de ingreso',
                                                       'Entradas posteriores', 'Salidas anticipadas', 'Asistencia (%)')]
            for fila in contenido['asistencias'].values():
                filas.append([str(fila['alumno']), fila['faltas'], fila['justificadas'], fila['retardos'], fila['faltas_entrada'],
                              fila['retardos_entrada'], fila['ingreso_tarde'], fila['entradas_posteriores'], fila['salidas_anticipadas'],
                              '' if fila['porcentaje'] is None else fila['porcentaje']])
            libro.append(Hoja('Asistencia', filas, anchos=[32, 12, 12, 12, 12, 12, 12, 12, 12, 12]))
        return libro

    if tipo == ASISTENCIA:
        t = contenido['total']
        filas = _encabezado(contenido) + [
            ['Estudiantes', len(contenido['filas'])],
            ['Estudiantes con alguna falta', t.get('estudiantes_con_falta', 0)],
            ['Faltas por materia (registros)', t.get('faltas', 0)],
            ['Faltas justificadas', t.get('justificadas', 0)],
            ['Retardos por materia (registros)', t.get('retardos', 0)],
            [],
            _titulos('Estudiante', 'Número de control', 'Grupo', 'Registros por materia', 'Presentes', 'Retardos', 'Faltas', 'Justificadas',
                     'Sin justificar', 'Asistencia (%)', 'Faltas de entrada', 'Retardos de entrada', 'Retardos de ingreso',
                     'Entradas posteriores', 'Salidas anticipadas'),
        ]
        for f in contenido['filas']:
            filas.append([str(f['alumno']), f['alumno'].referencia, str(f['grupo']), f['registros'], f['presentes'], f['retardos'], f['faltas'],
                          f['justificadas'], f['sin_justificar'], '' if f['porcentaje'] is None else f['porcentaje'], f['faltas_entrada'],
                          f['retardos_entrada'], f['ingreso_tarde'], f['entradas_posteriores'], f['salidas_anticipadas']])
        return [Hoja('Asistencia', filas, anchos=[32, 14, 18, 12, 10, 10, 10, 12, 12, 12, 12, 12, 12, 12, 12])]

    if tipo == JUSTIFICACIONES:
        filas = _encabezado(contenido) + [
            ['Faltas por materia', contenido['faltas']], ['Justificadas', contenido['faltas_justificadas']],
            ['Sin justificar', contenido['faltas_sin_justificar']], ['Estudiantes con faltas', contenido['estudiantes']],
            ['Retardos por materia', contenido['retardos']], [],
            _titulos('Fecha', 'Estudiante', 'Número de control', 'Grupo', 'Materia', 'Estado', 'Justificada', 'Motivo', 'Justificó', 'Cuándo'),
        ]
        for r in contenido['registros']:
            j = r.justificacion
            filas.append([r.fecha, str(r.inscripcion.alumno), r.inscripcion.alumno.referencia, str(r.inscripcion.grupo), str(r.materia_grado.materia),
                          r.get_estado_display(), 'Sí' if r.justificada else 'No', j.motivo if j else '', _quien(j.registrada_por) if j else '',
                          j.creado.strftime('%d/%m/%Y %H:%M') if j else ''])
        return [Hoja('Faltas', filas, anchos=[11, 30, 14, 18, 24, 10, 11, 40, 22, 16])]

    if tipo == REINCIDENCIAS:
        filas = _encabezado(contenido) + [
            ['Criterios', '; '.join(f'{r.get_nivel_display()}: {r.incidencias} del mismo motivo en {r.dias} días' for r in contenido['reglas']) or 'Sin criterios configurados'],
            [], _titulos('Estudiante', 'Nivel', 'Motivo', 'Incidencias', 'Criterio del nivel'),
        ]
        filas += [[str(f['alumno']), f['nivel'], f['motivo'], f['total'], f['umbral']] for f in contenido['reincidencias']]
        return [Hoja('Reincidencias', filas, anchos=[32, 14, 30, 12, 20])]

    if tipo == MEDIDAS:
        filas = _encabezado(contenido) + [
            ['Medidas aplicadas', contenido['aplicadas']], ['Registros con medidas aplicadas', contenido['registros_con_medidas']], [],
            [Celda('Totales por medida', SECCION)], _titulos('Medida', 'Aplicadas', 'Pendientes', 'Rechazadas', 'Anuladas'),
            *[[f['nombre'], f['aplicadas'], f['pendientes'], f['rechazadas'], f['anuladas']] for f in contenido['resumen_medidas']], [],
            _titulos('Fecha del hecho', 'Estudiante', 'Motivo', 'Medida', 'Estado', 'Solicitó', 'Resolvió', 'Observaciones'),
        ]
        for m in contenido['medidas']:
            filas.append([m.registro.fecha, str(m.registro.alumno), m.registro.motivo_nombre, m.nombre, m.get_estado_display(),
                          _quien(m.solicitada_por), _quien(m.resuelta_por), m.observaciones])
        return [Hoja('Medidas', filas, anchos=[12, 30, 26, 26, 22, 20, 20, 40])]

    filas = _encabezado(contenido) + [[Celda('Casos abiertos', SECCION)],
                                      _titulos('Fecha', 'Estudiante', 'Motivo', 'Estado', 'Responsable', 'Revisión')]
    for r in contenido['abiertos']:
        filas.append([r.fecha, str(r.alumno), r.motivo_nombre, r.get_estado_display(), _quien(r.responsable),
                      r.fecha_revision.strftime('%d/%m/%Y') if r.fecha_revision else ''])
    filas += [[], [Celda('Compromisos pendientes', SECCION)], _titulos('Fecha límite', 'Estudiante', 'Se compromete', 'Compromiso', 'Responsable')]
    filas += [[c.fecha_limite, str(c.registro.alumno), c.get_quien_display(), c.descripcion, _quien(c.responsable)] for c in contenido['compromisos']]
    filas += [[], [Celda('Citas programadas', SECCION)], _titulos('Fecha', 'Hora', 'Estudiante', 'Con quién', 'Asunto', 'Responsable')]
    filas += [[c.fecha, c.hora.strftime('%H:%M') if c.hora else '', str(c.registro.alumno), c.persona, c.asunto, _quien(c.responsable)]
              for c in contenido['citas']]
    return [Hoja('Pendientes', filas, anchos=[12, 30, 26, 40, 22, 12])]
