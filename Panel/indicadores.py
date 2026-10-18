"""Los indicadores del panel de control, calculados en el servidor con las reglas de cada módulo.

Cada función recibe los filtros (Panel/filtros.py) y devuelve solo cifras y listas ya agregadas: nada se calcula en el
navegador. Los permisos los revisa la vista (Panel/views.py) antes de llamar a cada una.

Asistencia: la de entrada al colegio es la fuente institucional del día (Alumnos/asistencias.py: mismos estudiantes
esperados, sin días sin clases, sin días de suspensión autorizada, con las justificadas aparte). La de cada materia
(pase de lista) se presenta por separado: son registros de clases, no estudiantes. Los días o estudiantes sin captura
no cuentan como faltas.
"""
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.db.models import Count, Q
from django.db.models.functions import TruncWeek
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from Alumnos.asistencias import (
    alumnos_suspendidos, con_justificada_general, con_justificada_materia, conteos, dias_de_clases, fechas_sin_clases,
    inscripciones_del_dia, motivo_sin_clases, porcentaje, sin_dias_suspendidos,
)
from Alumnos.models import AsistenciaGeneral, AsistenciaMateria, Inscripcion

from . import academico
from .filtros import NOMBRES_DE_NIVEL

RANGOS = ((Decimal('0'), Decimal('6'), 'Menos de 6'), (Decimal('6'), Decimal('7'), '6 a 6.9'), (Decimal('7'), Decimal('8'), '7 a 7.9'),
          (Decimal('8'), Decimal('9'), '8 a 8.9'), (Decimal('9'), Decimal('10.01'), '9 a 10'))
LISTA_BREVE = 5


def _url(nombre, *args, consulta=''):
    url = reverse(nombre, args=args)
    return f'{url}?{consulta}' if consulta else url


def _ancho(valor, maximo):
    if not maximo or valor is None:
        return 0
    return round(float(valor) * 100 / float(maximo), 1)


def _rutas_inscripcion(prefijo='inscripcion__'):
    return {'nivel': f'{prefijo}grado__nivel', 'grado': f'{prefijo}grado', 'grupo': f'{prefijo}grupo'}


# ---------------------------------------------------------------------------
# Estudiantes
# ---------------------------------------------------------------------------
def estudiantes(filtros):
    inscripciones = filtros.inscripciones()
    total = inscripciones.values('alumno').distinct().count()
    por_nivel = dict(inscripciones.order_by().values_list('grado__nivel').annotate(n=Count('alumno', distinct=True)))
    consulta = {'estatus': 'ACTIVO'}
    if filtros.grado is not None:
        consulta['grado'] = filtros.grado.pk
    return {
        'total': total,
        'por_nivel': [(NOMBRES_DE_NIVEL[n], por_nivel[n]) for n, _ in filtros.niveles if n in por_nivel],
        'url': _url('alumnos:lista', consulta=urlencode(consulta)),
    }


# ---------------------------------------------------------------------------
# Asistencia
# ---------------------------------------------------------------------------
def entrada_del_dia(filtros, fecha):
    """La asistencia de entrada del día en el alcance (como Alumnos/asistencias.py · resumen_del_dia, con grupo)."""
    if filtros.ciclo is None or not (filtros.ciclo.fecha_inicio <= fecha <= filtros.ciclo.fecha_fin):
        return {'aplica': False, 'motivo': 'Fuera del ciclo elegido'}
    motivo = motivo_sin_clases(fecha, filtros.ciclo, nivel=filtros.nivel or None)
    if motivo:
        return {'aplica': False, 'motivo': motivo}
    inscripciones = filtros.filtrar(inscripciones_del_dia(fecha, filtros.ciclo))
    esperados = inscripciones.count()
    suspendidos = inscripciones.filter(alumno__in=alumnos_suspendidos(fecha)).count()
    datos = conteos(con_justificada_general(sin_dias_suspendidos(AsistenciaGeneral.objects.filter(fecha=fecha, inscripcion__in=inscripciones))))
    datos.update(esperados=esperados, suspendidos=suspendidos, aplica=True, fecha=fecha)
    datos['sin_registro'] = max(esperados - datos['registros'] - suspendidos, 0)
    datos['porcentaje'] = porcentaje(datos['presentes'], datos['retardos'], datos['registros'])
    datos['sin_justificar'] = datos['faltas'] - datos['justificadas']
    return datos


def dia_anterior_con_registros(filtros):
    """El día de clases anterior a hoy con entradas registradas, para dar contexto (no es una meta)."""
    if not filtros.hoy_en_ciclo:
        return None
    inscripciones = filtros.filtrar(Inscripcion.objects.filter(ciclo=filtros.ciclo))
    fecha = (AsistenciaGeneral.objects.filter(inscripcion__in=inscripciones, fecha__lt=filtros.hoy, fecha__gte=filtros.ciclo.fecha_inicio)
             .order_by('-fecha').values_list('fecha', flat=True).first())
    if fecha is None:
        return None
    datos = entrada_del_dia(filtros, fecha)
    return datos if datos.get('aplica') and datos['registros'] else None


def _registros_del_rango(filtros, desde, hasta):
    consulta = AsistenciaGeneral.objects.filter(inscripcion__ciclo=filtros.ciclo, fecha__range=(desde, hasta))
    consulta = filtros.filtrar(consulta, **_rutas_inscripcion())
    sin_clases = fechas_sin_clases(desde, hasta, filtros.nivel or None)
    if sin_clases:
        consulta = consulta.exclude(fecha__in=sin_clases)
    return con_justificada_general(sin_dias_suspendidos(consulta))


def asistencia_del_rango(filtros):
    if filtros.ciclo is None:
        return None
    desde, hasta = filtros.desde, min(filtros.hasta, filtros.hoy)
    if desde > hasta:
        return {'vacio': True, 'motivo': 'El rango todavía no empieza'}
    registros = _registros_del_rango(filtros, desde, hasta)
    totales = conteos(registros)
    totales['porcentaje'] = porcentaje(totales['presentes'], totales['retardos'], totales['registros'])
    totales['sin_justificar'] = totales['faltas'] - totales['justificadas']

    # Tendencia: un punto por día de clases con registros (los días sin captura quedan sin punto)
    por_dia = {f['fecha']: f for f in registros.order_by().values('fecha').annotate(
        n=Count('pk'), p=Count('pk', filter=Q(estado='PRESENTE')), r=Count('pk', filter=Q(estado='RETARDO')),
        f=Count('pk', filter=Q(estado='FALTA')))}
    dias = dias_de_clases(desde, hasta, filtros.ciclo, filtros.nivel or None)
    serie = []
    for fecha in dias:
        fila = por_dia.get(fecha)
        valor = porcentaje(fila['p'], fila['r'], fila['n']) if fila else None
        serie.append({'fecha': fecha, 'valor': valor, 'registros': fila['n'] if fila else 0,
                      'asistieron': (fila['p'] + fila['r']) if fila else 0, 'faltas': fila['f'] if fila else 0})
    grafica = _grafica_de_linea(serie)

    # Comparación: por nivel, por grado o por grupo, según el alcance
    if filtros.grupo is not None:
        comparacion, unidad = [], ''
    else:
        campo, unidad = (('inscripcion__grupo', 'grupo') if filtros.grado is not None else
                         ('inscripcion__grado', 'grado') if filtros.nivel else ('inscripcion__grado__nivel', 'nivel'))
        filas = registros.order_by().values(campo).annotate(
            n=Count('pk'), p=Count('pk', filter=Q(estado='PRESENTE')), r=Count('pk', filter=Q(estado='RETARDO')))
        nombres = _nombres(unidad, [f[campo] for f in filas], filtros)
        comparacion = sorted(
            ({'nombre': nombres.get(f[campo], str(f[campo])), 'orden': _orden(unidad, f[campo], filtros), 'valor': porcentaje(f['p'], f['r'], f['n']),
              'base': f['n']} for f in filas), key=lambda x: x['orden'])
        for fila in comparacion:
            fila['ancho'] = _ancho(fila['valor'], 100)

    # Suspensiones del rango: estudiantes y días de clases suspendidos
    from Conducta.models import APROBADA, Suspension
    alumnos = filtros.filtrar(Inscripcion.objects.filter(ciclo=filtros.ciclo)).values('alumno')
    suspensiones = Suspension.objects.filter(aprobacion=APROBADA, registro__anulado=False, registro__alumno__in=alumnos,
                                             fecha_inicio__lte=hasta, fecha_fin__gte=desde).select_related('registro')
    dias_suspendidos = sum(len(dias_de_clases(max(s.fecha_inicio, desde), min(s.fecha_fin, hasta), filtros.ciclo, s.registro.nivel)) for s in suspensiones)
    totales['suspendidos'] = len({s.registro.alumno_id for s in suspensiones})
    totales['dias_suspendidos'] = dias_suspendidos

    # Asistencia por clase (pase de lista): aparte, son registros de clases
    materias = AsistenciaMateria.objects.filter(inscripcion__ciclo=filtros.ciclo, fecha__range=(desde, hasta))
    materias = conteos(con_justificada_materia(sin_dias_suspendidos(filtros.filtrar(materias, **_rutas_inscripcion()))))
    materias['porcentaje'] = porcentaje(materias['presentes'], materias['retardos'], materias['registros'])

    # Estudiantes vigentes con más faltas en el rango
    vigentes = filtros.inscripciones()
    mas_faltas = list(registros.filter(inscripcion__in=vigentes, estado='FALTA').order_by().values('inscripcion').annotate(
        faltas=Count('pk'), sin_justificar=Count('pk', filter=Q(justificada=False))).order_by('-sin_justificar', '-faltas')[:LISTA_BREVE])
    inscripciones = {i.pk: i for i in Inscripcion.objects.filter(pk__in=[f['inscripcion'] for f in mas_faltas])
                     .select_related('alumno', 'grupo__nombre', 'grupo__grado')}
    for fila in mas_faltas:
        fila['inscripcion'] = inscripciones[fila['inscripcion']]
        fila['url'] = _url('alumnos:vista360', fila['inscripcion'].alumno_id, consulta='seccion=asistencia')

    return {
        'vacio': not totales['registros'], 'desde': desde, 'hasta': hasta, 'totales': totales, 'grafica': grafica,
        'comparacion': comparacion, 'unidad': unidad, 'materias': materias, 'mas_faltas': mas_faltas,
        'dias_de_clases': len(dias), 'dias_con_registro': len(por_dia),
    }


def _nombres(unidad, claves, filtros):
    if unidad == 'nivel':
        return {c: NOMBRES_DE_NIVEL.get(c, c) for c in claves}
    if unidad == 'grado':
        return {g.pk: str(g) for g in filtros.grados if g.pk in set(claves)}
    return {g.pk: g.corto for g in filtros.grupos if g.pk in set(claves)}


def _orden(unidad, clave, filtros):
    lista = ([n for n, _ in filtros.niveles] if unidad == 'nivel' else
             [g.pk for g in (filtros.grados if unidad == 'grado' else filtros.grupos)])
    return lista.index(clave) if clave in lista else len(lista)


def _grafica_de_linea(serie, alto=120):
    """Puntos de la tendencia en un lienzo de 0 a 100 en x y de 0 a `alto` en y. La escala vertical va del múltiplo de
    10 bajo el mínimo hasta 100 (una línea no necesita partir de cero; se rotulan sus extremos)."""
    valores = [p['valor'] for p in serie if p['valor'] is not None]
    if not valores:
        return None
    piso = max(0, min(valores) // 10 * 10 - (10 if min(valores) % 10 < 3 else 0))
    piso = min(piso, 90)
    total = len(serie)
    puntos, tramos, tramo = [], [], []
    for i, p in enumerate(serie):
        x = 50.0 if total == 1 else round(i * 100 / (total - 1), 2)
        if p['valor'] is None:
            if tramo:
                tramos.append(tramo)
            tramo = []
            puntos.append({**p, 'x': x, 'y': None})
            continue
        y = round(alto - (p['valor'] - piso) * alto / (100 - piso), 2) if piso < 100 else 0
        tramo.append((x, y))
        puntos.append({**p, 'x': x, 'y': y, 'y_pct': round(y * 100 / alto, 2)})
    if tramo:
        tramos.append(tramo)
    trazos = [' '.join(f'{"M" if j == 0 else "L"}{x} {y}' for j, (x, y) in enumerate(t)) for t in tramos]
    ultimo = next((p for p in reversed(puntos) if p['y'] is not None), None)
    return {'puntos': puntos, 'trazos': trazos, 'piso': piso, 'alto': alto, 'y_fondo': alto - 0.5, 'medio': (piso + 100) // 2,
            'y_medio': round(alto / 2, 2), 'ultimo': ultimo, 'ancho_columna': round(100 / max(total, 1), 3)}


# ---------------------------------------------------------------------------
# Desempeño académico
# ---------------------------------------------------------------------------
def academico_del_alcance(filtros, evaluaciones):
    from .models import CriterioSeguimiento
    criterios = CriterioSeguimiento.por_nivel()
    vigentes = academico.vigentes_por_inscripcion(filtros)
    lista, omitidas, anteriores = [], 0, []
    for nivel, ev in evaluaciones.items():
        if ev.evaluado is not None:
            actuales, n = academico.resultados(filtros, ev.evaluado, nivel, vigentes)
            lista += actuales
            omitidas += n
        if ev.anterior is not None:
            anteriores += academico.resultados(filtros, ev.anterior, nivel, vigentes)[0]

    finales = [r.final for r in lista]
    por_estudiante = defaultdict(list)
    for r in lista:
        por_estudiante[r.inscripcion].append(r)
    reprobados = {i for i, rs in por_estudiante.items() if any(r.final < criterios[r.nivel].calificacion_aprobatoria for r in rs)}
    promedios = {i: academico.promedio(r.final for r in rs) for i, rs in por_estudiante.items()}

    # Comparación: por nivel, grado, grupo o materia
    if filtros.grupo is not None:
        clave, unidad = (lambda r: r.materia), 'materia'
    elif filtros.grado is not None:
        clave, unidad = (lambda r: r.grupo), 'grupo'
    elif filtros.nivel:
        clave, unidad = (lambda r: r.grado), 'grado'
    else:
        clave, unidad = (lambda r: r.nivel), 'nivel'
    grupos = defaultdict(list)
    for r in lista:
        grupos[clave(r)].append(r.final)
    nombres = {} if unidad == 'materia' else _nombres(unidad, list(grupos), filtros)
    comparacion = [{'nombre': nombres.get(k, str(k)), 'valor': academico.promedio(v), 'base': len(v),
                    'orden': (k if unidad == 'materia' else _orden(unidad, k, filtros))} for k, v in grupos.items()]
    comparacion.sort(key=lambda x: x['orden'])
    for fila in comparacion:
        fila['ancho'] = _ancho(fila['valor'], academico.ESCALA)

    # Distribución de estudiantes por rango de su promedio
    distribucion = [{'nombre': nombre, 'valor': sum(1 for p in promedios.values() if p is not None and desde <= p < hasta)}
                    for desde, hasta, nombre in RANGOS]
    maximo = max((d['valor'] for d in distribucion), default=0)
    for fila in distribucion:
        fila['alto'] = _ancho(fila['valor'], maximo)

    # Materias con mayor porcentaje de reprobación
    por_materia = defaultdict(lambda: [0, 0])
    for r in lista:
        por_materia[r.materia][0] += 1
        if r.final < criterios[r.nivel].calificacion_aprobatoria:
            por_materia[r.materia][1] += 1
    reprobacion = sorted(
        ({'nombre': m, 'evaluados': e, 'reprobados': f, 'valor': round(f * 100 / e, 1)} for m, (e, f) in por_materia.items() if f),
        key=lambda x: (-x['valor'], -x['reprobados'], x['nombre']))[:LISTA_BREVE]
    for fila in reprobacion:
        fila['ancho'] = _ancho(fila['valor'], 100)

    # Comparación con el periodo anterior: solo si todos los niveles del alcance tienen uno con resultados
    previo = None
    if anteriores and all(ev.anterior is not None for ev in evaluaciones.values() if ev.evaluado is not None):
        previo = academico.promedio(r.final for r in anteriores)

    evaluados = [ev for ev in evaluaciones.values() if ev.evaluado is not None]
    if len(evaluaciones) == 1:
        texto_periodo = evaluados[0].evaluado.nombre if evaluados else 'Sin actas cerradas'
    else:
        texto_periodo = 'Periodo actual de cada nivel' if evaluados else 'Sin actas cerradas'
    return {
        'vacio': not lista, 'promedio': academico.promedio(finales), 'calificaciones': len(finales),
        'estudiantes': len(por_estudiante), 'reprobados': len(reprobados),
        'porcentaje_reprobados': round(len(reprobados) * 100 / len(por_estudiante), 1) if por_estudiante else None,
        'comparacion': comparacion, 'unidad': unidad, 'distribucion': distribucion, 'reprobacion': reprobacion,
        'omitidas': omitidas, 'previo': previo, 'texto_periodo': texto_periodo,
        'periodos': [(NOMBRES_DE_NIVEL[n], ev) for n, ev in evaluaciones.items()],
        'aprobatorias': sorted({(NOMBRES_DE_NIVEL[n], criterios[n].calificacion_aprobatoria, criterios[n].es_propuesto) for n in evaluaciones}),
    }


# ---------------------------------------------------------------------------
# Conducta y bitácoras
# ---------------------------------------------------------------------------
def conducta(filtros):
    from Conducta.models import APROBADA, INCIDENCIA, RegistroConducta, Suspension
    from Conducta.reglas import solicitudes_pendientes
    registros = filtros.filtrar(RegistroConducta.objects.vigentes().filter(ciclo=filtros.ciclo), nivel='nivel', grado='grado', grupo='grupo')
    en_rango = registros.filter(fecha__range=(filtros.desde, filtros.hasta))
    incidencias = en_rango.filter(tipo=INCIDENCIA)
    hoy = registros.filter(fecha=filtros.hoy, tipo=INCIDENCIA) if filtros.hoy_en_ciclo else registros.none()
    categorias = list(incidencias.order_by().values('categoria_nombre').annotate(n=Count('pk')).order_by('-n', 'categoria_nombre')[:LISTA_BREVE])
    maximo = max((c['n'] for c in categorias), default=0)
    for c in categorias:
        c['ancho'] = _ancho(c['n'], maximo)
    por_nivel = []
    if not filtros.nivel:
        conteo = dict(incidencias.order_by().values_list('nivel').annotate(n=Count('pk')))
        por_nivel = [{'nombre': nombre, 'n': conteo.get(n, 0)} for n, nombre in filtros.niveles if conteo.get(n)]
        maximo_n = max((x['n'] for x in por_nivel), default=0)
        for x in por_nivel:
            x['ancho'] = _ancho(x['n'], maximo_n)
    semanas = {s['semana'].date() if hasattr(s['semana'], 'date') else s['semana']: s['n'] for s in
               incidencias.annotate(semana=TruncWeek('fecha')).order_by().values('semana').annotate(n=Count('pk'))}
    tendencia, inicio = [], filtros.desde - timedelta(days=filtros.desde.weekday())
    while inicio <= filtros.hasta:
        tendencia.append({'semana': inicio, 'n': semanas.get(inicio, 0)})
        inicio += timedelta(days=7)
    maximo_s = max((t['n'] for t in tendencia), default=0)
    for t in tendencia:
        t['alto'] = _ancho(t['n'], maximo_s)
    abiertos = registros.filter(tipo=INCIDENCIA).exclude(estado=RegistroConducta.CERRADO)
    suspendidos_hoy = (Suspension.objects.filter(aprobacion=APROBADA, registro__in=registros.values('pk'),
                                                 fecha_inicio__lte=filtros.hoy, fecha_fin__gte=filtros.hoy)
                       .values('registro__alumno').distinct().count()) if filtros.hoy_en_ciclo else 0
    solicitudes = solicitudes_pendientes(registros)
    return {
        'incidencias': incidencias.count(), 'estudiantes': incidencias.values('alumno').distinct().count(),
        'positivas': en_rango.exclude(tipo=INCIDENCIA).count(),
        'hoy': hoy.count(), 'estudiantes_hoy': hoy.values('alumno').distinct().count(),
        'categorias': categorias, 'por_nivel': por_nivel, 'tendencia': tendencia,
        'abiertos': abiertos.count(), 'vencidos': abiertos.filter(fecha_revision__lt=filtros.hoy).count(),
        'suspendidos_hoy': suspendidos_hoy,
        'solicitudes': len(solicitudes['suspensiones']) + len(solicitudes['medidas']),
    }


def bitacoras(usuario, filtros):
    from Bitacoras.alcance import alcance_de_bitacoras
    entradas = filtros.filtrar(alcance_de_bitacoras(usuario).entradas().filter(ciclo=filtros.ciclo), nivel='nivel', grado='grado', grupo='grupo')
    en_rango = entradas.filter(fecha__range=(filtros.desde, filtros.hasta))
    return {
        'total': en_rango.count(),
        'recientes': list(en_rango.order_by('-fecha', '-creado', '-pk')[:4]),
    }


# ---------------------------------------------------------------------------
# Retiros anticipados (hoy)
# ---------------------------------------------------------------------------
def retiros(usuario, filtros):
    from Retiros.alcance import alcance_de, condicion
    from Retiros.models import RetiroEstudiante
    alcance = alcance_de(usuario)
    base = filtros.filtrar(RetiroEstudiante.objects.filter(condicion(alcance)), **_rutas_inscripcion())
    hoy = base.filter(fecha=filtros.hoy)
    vigentes_hoy = hoy.exclude(estado=RetiroEstudiante.CANCELADO)
    ahora = timezone.localtime().time()
    proximos = list(hoy.filter(estado=RetiroEstudiante.AVISADO).select_related(
        'alumno', 'inscripcion__grupo__nombre', 'inscripcion__grupo__grado', 'aviso__tutor', 'aviso__motivo').order_by('aviso__hora', 'pk')[:LISTA_BREVE])
    for r in proximos:
        r.atrasado = r.aviso.hora < ahora
    return {
        'solicitudes': vigentes_hoy.values('aviso').distinct().count(),
        'estudiantes': vigentes_hoy.count(),
        'pendientes': hoy.filter(estado=RetiroEstudiante.AVISADO).count(),
        'realizados': hoy.filter(estado=RetiroEstudiante.RETIRADO).count(),
        'cancelados': hoy.filter(estado=RetiroEstudiante.CANCELADO).count(),
        'atrasados': base.filter(estado=RetiroEstudiante.AVISADO, fecha__lt=filtros.hoy).count(),
        'proximos': proximos,
        'url': reverse('retiros:lista'),
    }


# ---------------------------------------------------------------------------
# Comunicados (todo el colegio: sus destinatarios no se eligen por nivel de estudiante)
# ---------------------------------------------------------------------------
def comunicados(usuario, filtros):
    from Comunicados.alcance import ENVIAR, es_administrador
    from Comunicados.reglas import con_estadisticas, gestionables, preparar
    if es_administrador(usuario):
        consulta, de_quien = gestionables(usuario, 'gestion'), 'Todos los del colegio'
    elif usuario.has_perm(ENVIAR):
        consulta, de_quien = gestionables(usuario, 'enviados'), 'Los que tú enviaste'
    else:
        return None
    desde = timezone.make_aware(datetime.combine(filtros.desde, time.min))
    hasta = timezone.make_aware(datetime.combine(filtros.hasta + timedelta(days=1), time.min))
    en_rango = consulta.filter(creado__gte=desde, creado__lt=hasta)
    lista = list(con_estadisticas(en_rango).order_by('-creado', '-pk'))
    destinatarios = sum(c.total for c in lista)
    leidos = sum(c.leidos for c in lista)
    return {
        'de_quien': de_quien, 'publicados': len(lista), 'destinatarios': destinatarios, 'leidos': leidos,
        'porcentaje': round(leidos * 100 / destinatarios) if destinatarios else None,
        'recientes': [preparar(c) for c in lista[:3]],
        'puede_crear': usuario.has_perm(ENVIAR),
    }


# ---------------------------------------------------------------------------
# Actividad reciente (de registros reales con autor y fecha)
# ---------------------------------------------------------------------------
def _nombre(usuario):
    if usuario is None:
        return 'Sistema'
    return usuario.get_full_name() or usuario.get_username()


def actividad(usuario, filtros, permisos, limite=8):
    items = []
    if permisos.get('conducta'):
        from Conducta.models import RegistroConducta
        for r in (filtros.filtrar(RegistroConducta.objects.filter(ciclo=filtros.ciclo), nivel='nivel', grado='grado', grupo='grupo')
                  .select_related('registrado_por').order_by('-creado')[:limite]):
            items.append({'cuando': r.creado, 'quien': _nombre(r.registrado_por), 'icono': 'flag',
                          'accion': f'Registró {"una incidencia" if r.tipo == "INCIDENCIA" else "una conducta positiva"}',
                          'detalle': r.grupo_texto, 'url': reverse('conducta:detalle', args=[r.pk])})
    if permisos.get('calificaciones'):
        from Calificaciones.models import ActaCalificaciones
        actas = ActaCalificaciones.objects.filter(estado=ActaCalificaciones.CERRADA, cerrada_en__isnull=False, asignacion__ciclo=filtros.ciclo)
        for a in (filtros.filtrar(actas, nivel='asignacion__grado__nivel', grado='asignacion__grado', grupo='asignacion__grupo')
                  .select_related('cerrada_por', 'asignacion__materia', 'asignacion__grupo__nombre', 'asignacion__grupo__grado', 'periodo')
                  .order_by('-cerrada_en')[:limite]):
            items.append({'cuando': a.cerrada_en, 'quien': _nombre(a.cerrada_por), 'icono': 'award', 'accion': 'Cerró calificaciones',
                          'detalle': f'{a.asignacion.materia.nombre} · {a.asignacion.grupo.corto} · {a.periodo.nombre}',
                          'url': _url('calificaciones:inicio', consulta=f'ciclo={filtros.ciclo.pk}&materia={a.asignacion_id}&periodo={a.periodo_id}')})
    if permisos.get('justificaciones'):
        from Alumnos.models import Justificacion
        for j in (filtros.filtrar(Justificacion.objects.filter(inscripcion__ciclo=filtros.ciclo), **_rutas_inscripcion())
                  .select_related('registrada_por', 'inscripcion__grupo__nombre', 'inscripcion__grupo__grado').order_by('-creado')[:limite]):
            items.append({'cuando': j.creado, 'quien': _nombre(j.registrada_por), 'icono': 'file-text', 'accion': 'Registró una justificación',
                          'detalle': j.inscripcion.grupo.corto if j.inscripcion.grupo_id else '', 'url': reverse('asistencias:justificaciones')})
    if permisos.get('retiros'):
        from Retiros.alcance import alcance_de, condicion
        from Retiros.models import EventoRetiro, RetiroEstudiante
        visibles = filtros.filtrar(RetiroEstudiante.objects.filter(condicion(alcance_de(usuario))), **_rutas_inscripcion()).values('aviso')
        for e in EventoRetiro.objects.filter(aviso__in=visibles).select_related('usuario', 'tutor', 'aviso').order_by('-creado')[:limite]:
            quien = _nombre(e.usuario) if e.usuario_id else (f'{e.tutor.nombre} {e.tutor.apellido_paterno} (tutor)' if e.tutor_id else 'Sistema')
            items.append({'cuando': e.creado, 'quien': quien, 'icono': 'log-out', 'accion': e.get_tipo_display(),
                          'detalle': f'Retiro {e.aviso.folio}', 'url': reverse('retiros:detalle', args=[e.aviso_id])})
    if permisos.get('comunicados'):
        from Comunicados.alcance import es_administrador
        from Comunicados.models import Comunicado
        consulta = Comunicado.objects.visibles().select_related('autor')
        if not es_administrador(usuario):
            consulta = consulta.filter(autor=usuario)
        for c in consulta.order_by('-creado')[:limite]:
            items.append({'cuando': c.creado, 'quien': _nombre(c.autor), 'icono': 'megaphone', 'accion': 'Envió un comunicado',
                          'detalle': c.titulo, 'url': reverse('comunicados:detalle', args=[c.pk])})
    if permisos.get('bitacoras'):
        from Bitacoras.alcance import alcance_de_bitacoras
        for b in (filtros.filtrar(alcance_de_bitacoras(usuario).entradas().filter(ciclo=filtros.ciclo), nivel='nivel', grado='grado', grupo='grupo')
                  .order_by('-creado')[:limite]):
            items.append({'cuando': b.creado, 'quien': b.autor_nombre, 'icono': 'notebook-pen', 'accion': 'Registró una observación de bitácora',
                          'detalle': f'{b.grupo_texto} · {b.materia_nombre}', 'url': reverse('bitacoras:detalle', args=[b.pk])})
    items.sort(key=lambda i: i['cuando'], reverse=True)
    return items[:limite]


def texto_de_fecha(fecha):
    return date_format(fecha, 'l j \\d\\e F')
