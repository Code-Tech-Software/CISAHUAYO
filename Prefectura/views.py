"""Prefectura: su panel de inicio, la consulta de estudiantes (búsqueda y ficha) y el seguimiento de los casos.

Todo dentro del alcance de la cuenta (Prefectura/alcance.py): un estudiante fuera de él responde 404 aunque se teclee
su dirección. La ficha muestra lo necesario para el seguimiento (identificación escolar, grupo, contactos autorizados de
la familia e historial de asistencia y conducta); no muestra datos financieros, documentos personales ni el expediente
clínico, y desde aquí no se modifican los datos del estudiante.
"""
from datetime import timedelta

from django.db.models import Count, IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from Alumnos.asistencias import conteos, porcentaje
from Alumnos.models import AsistenciaMateria, TutorAlumno, orden_de_nivel
from CISAHUAYO.paginacion import OPCIONES_POR_PAGINA, POR_PAGINA_DEFECTO, paginar
from CISAHUAYO.permisos import requiere_alguno, requiere_permisos
from Conducta import permisos as PC
from Conducta import reglas
from Conducta.models import (
    INCIDENCIA,
    AvisoReincidencia,
    CitaTutor,
    Compromiso,
    MedidaAplicada,
    RegistroConducta,
    ReglaReincidencia,
)
from Conducta.views import registros_de

from . import asistencia
from .alcance import alcance_de
from .forms import FiltroEstudiantesForm

VER = 'Prefectura.consultar'
DIAS_RECIENTES = 7


def con(url, **parametros):
    return f'{url}?{urlencode({k: v for k, v in parametros.items() if v not in (None, "")})}'


def permisos_de(usuario):
    """Lo que la cuenta puede hacer en prefectura (para los botones; cada vista lo vuelve a comprobar)."""
    return {
        'registrar_conducta': PC.puede_registrar(usuario),
        'registrar_acceso': usuario.has_perm('Prefectura.registrar'),
        'justificar': usuario.has_perm('Prefectura.justificar'),
        'exportar': usuario.has_perm('Prefectura.exportar'),
        'seguimiento': usuario.has_perm('Prefectura.dar_seguimiento') or usuario.has_perm(PC.EDITAR),
    }


# ---------------------------------------------------------------------------
# Panel de inicio
# ---------------------------------------------------------------------------
@requiere_permisos(VER)
def inicio(request):
    alcance = alcance_de(request.user)
    hoy = timezone.localdate()
    hace_una_semana = hoy - timedelta(days=DIAS_RECIENTES - 1)
    registros = registros_de(request.user)
    vigentes = registros.filter(anulado=False)
    pendientes = reglas.pendientes(hoy, registros)
    dia = asistencia.del_dia(alcance, hoy)
    recientes = vigentes.filter(tipo=INCIDENCIA, fecha__gte=hace_una_semana)
    abiertos = vigentes.exclude(estado=RegistroConducta.CERRADO)

    asistencia_url = reverse('prefectura:asistencia_registros')
    lista = reverse('conducta:lista')
    seguimiento = reverse('prefectura:seguimiento')
    texto_hoy = hoy.isoformat()
    proximos = len(pendientes['citas']) + len(pendientes['compromisos'])
    return render(request, 'prefectura/inicio.html', {
        'alcance': alcance,
        'hoy': hoy,
        'dia': dia,
        'recientes': list(recientes.select_related('alumno').order_by('-fecha', '-hora', '-pk')[:6]),
        'cuantas_recientes': recientes.count(),
        'positivas_recientes': vigentes.exclude(tipo=INCIDENCIA).filter(fecha__gte=hace_una_semana).count(),
        'abiertos': abiertos.count(),
        'vencidos': len(pendientes['vencidos']),
        'solicitudes_suspension': len(pendientes['solicitudes_suspensiones']),
        'solicitudes_medidas': len(pendientes['solicitudes_medidas']),
        'suspendidos_hoy': sum(1 for s in pendientes['suspensiones'] if s.fecha_inicio <= hoy),
        'suspensiones_proximas': sum(1 for s in pendientes['suspensiones'] if s.fecha_inicio > hoy),
        'citas': pendientes['citas'],
        'compromisos': pendientes['compromisos'],
        'proximos': proximos,
        'avisos': pendientes['avisos'][:6],
        'cuantos_avisos': len(pendientes['avisos']),
        'reglas': list(ReglaReincidencia.objects.filter(activa=True, nivel__in=[c for c, _ in alcance.niveles_visibles()]).order_by(orden_de_nivel('nivel'))),
        'puede': permisos_de(request.user),
        'enlaces': {
            'faltas': con(asistencia_url, fuente='materias', estado='FALTA', desde=texto_hoy, hasta=texto_hoy),
            'estudiantes_con_falta': con(asistencia_url, fuente='materias', estado='FALTA', desde=texto_hoy, hasta=texto_hoy, vista='estudiantes'),
            'entraron_y_faltaron': con(asistencia_url, fuente='materias', estado='ENTRARON', desde=texto_hoy, hasta=texto_hoy, vista='estudiantes'),
            'faltas_de_entrada': con(asistencia_url, fuente='entrada', estado='FALTA', desde=texto_hoy, hasta=texto_hoy),
            'retardos': con(asistencia_url, fuente='materias', estado='RETARDO', desde=texto_hoy, hasta=texto_hoy),
            'retardos_de_entrada': con(asistencia_url, fuente='entrada', estado='RETARDO', desde=texto_hoy, hasta=texto_hoy),
            'accesos': con(reverse('prefectura:accesos'), desde=texto_hoy, hasta=texto_hoy),
            'recientes': con(lista, tipo=INCIDENCIA, desde=hace_una_semana.isoformat()),
            'abiertos': con(lista, estado='abiertos', ciclo=''),
            'vencidos': con(lista, estado='vencidos', ciclo=''),
            'solicitudes': reverse('conducta:solicitudes'),
            'suspendidos': con(lista, suspension='vigente', ciclo=''),
            'citas': con(seguimiento, vista='citas'),
            'compromisos': con(seguimiento, vista='compromisos'),
            'reincidencias': con(seguimiento, vista='reincidencias'),
        },
    })


# ---------------------------------------------------------------------------
# Estudiantes: búsqueda y ficha
# ---------------------------------------------------------------------------
@requiere_permisos(VER)
def estudiantes(request):
    alcance = alcance_de(request.user)
    form = FiltroEstudiantesForm(request.GET or None, alcance=alcance)
    faltas = (
        AsistenciaMateria.objects.filter(inscripcion=OuterRef('pk'), estado='FALTA').order_by()
        .values('inscripcion').annotate(total=Count('pk')).values('total')
    )
    incidencias = (
        RegistroConducta.objects.filter(alumno=OuterRef('alumno'), ciclo=OuterRef('ciclo'), anulado=False, tipo=INCIDENCIA).order_by()
        .values('alumno').annotate(total=Count('pk')).values('total')
    )
    inscripciones = (
        form.filtrar_inscripciones(alcance.inscripciones())
        .select_related('alumno', 'grado', 'grupo__nombre', 'grupo__grado', 'ciclo')
        .annotate(
            faltas=Coalesce(Subquery(faltas, output_field=IntegerField()), Value(0)),
            incidencias=Coalesce(Subquery(incidencias, output_field=IntegerField()), Value(0)),
        )
        .order_by(orden_de_nivel('grado__nivel'), 'grado__numero', 'grupo__nombre__orden', 'alumno__apellido_paterno', 'alumno__apellido_materno', 'alumno__nombre')
    )
    pagina, rango_paginas, por_pagina = paginar(request, inscripciones)
    return render(request, 'prefectura/estudiantes.html', {
        'seccion': 'estudiantes', 'alcance': alcance, 'filtro': form, 'pagina': pagina, 'rango_paginas': rango_paginas,
        'por_pagina': por_pagina, 'por_pagina_defecto': POR_PAGINA_DEFECTO, 'opciones_por_pagina': OPCIONES_POR_PAGINA,
        'puede': permisos_de(request.user),
    })


@requiere_permisos(VER)
def estudiante(request, pk):
    alcance = alcance_de(request.user)
    alumno = get_object_or_404(alcance.alumnos(), pk=pk)
    inscripcion = reglas.inscripcion_actual(alumno)
    contactos = list(
        TutorAlumno.objects.filter(alumno=alumno, activo=True, tutor__estatus='ACTIVO').select_related('tutor')
        .order_by('-tutor_principal', '-contacto_emergencia', 'tutor__apellido_paterno')
    )

    resumen_materias = resumen_entrada = None
    recientes, movimientos, justificaciones = [], [], []
    if inscripcion is not None:
        materias = asistencia.con_justificada_materia(asistencia.sin_dias_suspendidos(AsistenciaMateria.objects.filter(inscripcion=inscripcion)))
        resumen_materias = conteos(materias)
        resumen_materias['porcentaje'] = porcentaje(resumen_materias['presentes'], resumen_materias['retardos'], resumen_materias['registros'])
        resumen_materias['sin_justificar'] = resumen_materias['faltas'] - resumen_materias['justificadas']
        entrada = asistencia.con_justificada_general(asistencia.sin_dias_suspendidos(inscripcion.asistencias_generales.all()))
        resumen_entrada = conteos(entrada)
        recientes = list(
            materias.filter(estado__in=('FALTA', 'RETARDO')).select_related('materia_grado__materia').order_by('-fecha', 'materia_grado__materia__nombre')[:25]
        )
        movimientos = list(asistencia.accesos(alcance).filter(alumno=alumno, inscripcion=inscripcion).select_related('registrado_por')[:15])
        justificaciones = list(
            inscripcion.justificaciones.filter(activa=True).select_related('registrada_por', 'asistencia__materia_grado__materia').order_by('-fecha')[:15]
        )

    conducta = reglas.linea_de_tiempo(alumno)
    ids = [r.pk for r in conducta['registros']]
    return render(request, 'prefectura/estudiante.html', {
        'seccion': 'estudiantes',
        'alumno': alumno,
        'inscripcion': inscripcion,
        'contactos': contactos,
        'resumen_materias': resumen_materias,
        'resumen_entrada': resumen_entrada,
        'recientes': recientes,
        'movimientos': movimientos,
        'justificaciones': justificaciones,
        'conducta': conducta,
        'medidas': list(MedidaAplicada.objects.filter(registro__in=ids).select_related('registro').order_by('-registro__fecha', 'nombre')),
        'compromisos': list(Compromiso.objects.filter(registro__in=ids).select_related('registro', 'responsable').order_by('estado', 'fecha_limite')),
        'citas': list(CitaTutor.objects.filter(registro__in=ids).select_related('registro').order_by('-fecha')),
        'puede': permisos_de(request.user),
    })


# ---------------------------------------------------------------------------
# Seguimiento: casos abiertos, citas, compromisos y reincidencias
# ---------------------------------------------------------------------------
VISTAS_DE_SEGUIMIENTO = [
    ('casos', 'Casos abiertos'), ('citas', 'Citas con la familia'), ('compromisos', 'Compromisos'), ('reincidencias', 'Reincidencias'),
]


def _buscar(consulta, texto, campo):
    for palabra in texto.split():
        consulta = consulta.filter(
            Q(**{f'{campo}__nombre__icontains': palabra}) | Q(**{f'{campo}__apellido_paterno__icontains': palabra})
            | Q(**{f'{campo}__apellido_materno__icontains': palabra}) | Q(**{f'{campo}__referencia__icontains': palabra})
        )
    return consulta


@requiere_alguno(VER, PC.VER)
def seguimiento(request):
    vista = request.GET.get('vista', 'casos')
    vista = vista if vista in dict(VISTAS_DE_SEGUIMIENTO) else 'casos'
    estado = request.GET.get('estado', '')
    texto = request.GET.get('q', '').strip()
    registros = registros_de(request.user).filter(anulado=False)
    ids = registros.values('pk')
    hoy = timezone.localdate()

    if vista == 'casos':
        filas = registros.exclude(estado=RegistroConducta.CERRADO)
        if estado == 'vencidos':
            filas = filas.filter(fecha_revision__lt=hoy)
        elif estado in (RegistroConducta.PENDIENTE, RegistroConducta.EN_SEGUIMIENTO):
            filas = filas.filter(estado=estado)
        filas = _buscar(filas, texto, 'alumno').select_related('alumno', 'responsable').order_by('fecha_revision', '-fecha')
        estados = [('', 'Abiertos y en seguimiento'), (RegistroConducta.PENDIENTE, 'Abiertos'), (RegistroConducta.EN_SEGUIMIENTO, 'En seguimiento'), ('vencidos', 'Vencidos')]
    elif vista == 'citas':
        filas = CitaTutor.objects.filter(registro__in=ids)
        filas = filas.filter(estado=estado) if estado else filas.filter(estado=CitaTutor.PROGRAMADA)
        filas = _buscar(filas, texto, 'registro__alumno').select_related('registro__alumno', 'responsable').order_by('fecha', 'hora')
        estados = [('', 'Programadas')] + [(c, n) for c, n in CitaTutor.ESTADOS if c != CitaTutor.PROGRAMADA]
    elif vista == 'compromisos':
        filas = Compromiso.objects.filter(registro__in=ids)
        if estado == 'vencidos':
            filas = filas.filter(estado=Compromiso.PENDIENTE_C, fecha_limite__lt=hoy)
        else:
            filas = filas.filter(estado=estado or Compromiso.PENDIENTE_C)
        filas = _buscar(filas, texto, 'registro__alumno').select_related('registro__alumno', 'responsable').order_by('fecha_limite')
        estados = [('', 'Pendientes'), ('vencidos', 'Vencidos')] + [(c, n) for c, n in Compromiso.ESTADOS if c != Compromiso.PENDIENTE_C]
    else:
        filas = AvisoReincidencia.objects.filter(registro__in=ids, revisado=(estado == 'revisados'))
        filas = _buscar(filas, texto, 'alumno').select_related('alumno', 'registro', 'motivo', 'revisado_por').order_by('-creado')
        estados = [('', 'Sin revisar'), ('revisados', 'Revisados')]

    pagina, rango_paginas, por_pagina = paginar(request, filas)
    return render(request, 'prefectura/seguimiento.html', {
        'seccion': 'seguimiento', 'vista': vista, 'vistas': VISTAS_DE_SEGUIMIENTO, 'estado': estado, 'estados': estados, 'q': texto,
        'hoy': hoy, 'pagina': pagina, 'rango_paginas': rango_paginas, 'por_pagina': por_pagina,
        'por_pagina_defecto': POR_PAGINA_DEFECTO, 'opciones_por_pagina': OPCIONES_POR_PAGINA,
        'reglas': list(ReglaReincidencia.objects.filter(activa=True).order_by(orden_de_nivel('nivel'))),
        'puede': permisos_de(request.user),
        'puede_revisar': request.user.has_perm(PC.EDITAR) or request.user.has_perm('Prefectura.dar_seguimiento'),
    })
