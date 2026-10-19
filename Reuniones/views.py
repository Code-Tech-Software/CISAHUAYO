"""Reuniones con familias: las pantallas del personal y Ajustes › Reuniones.

- Panel (`inicio`): indicadores de hoy, solicitudes sin programar, citas por confirmar, realizadas, inasistencias y
  acuerdos vencidos, con el filtro por nivel según el alcance; lo que necesita atención y las reuniones de hoy.
- Agenda (día por sala, semana, mes) y lista, con filtros de nivel, grupo, estudiante, tutor, participante, estado,
  prioridad y fechas.
- Registrar la llamada (`nueva`): buscar al tutor y anotar la solicitud.
- Detalle: toda la información, las confirmaciones, los participantes (quién es docente y quién acompaña), la minuta,
  los acuerdos, los documentos y el historial. Cada acción abre su formulario en una ventana (data-modal-form) o como
  página.
- Compromisos: los acuerdos pendientes, en proceso y vencidos.
- Historial del estudiante: sus reuniones y acuerdos.
Todo dentro de lo que la cuenta puede ver (Reuniones/alcance.py): lo de fuera responde 404; las acciones sin permiso,
403.
"""
from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Prefetch, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from Alumnos.models import Alumno, TutorAlumno, Tutor
from CISAHUAYO.paginacion import OPCIONES_POR_PAGINA, POR_PAGINA_DEFECTO, paginar
from CISAHUAYO.permisos import requiere_alguno, requiere_permisos
from Prefectura.alcance import NOMBRE_DE_NIVEL

from . import calendario, notificaciones, reglas
from .alcance import (
    CONFIGURAR, DEL_MODULO, GESTIONAR, PARTICIPAR, QUE_ATIENDEN, REGISTRAR, SIN_NIVELES, TODO, Acceso, cuentas_con_permiso,
)
from .context_processors import datos_de_avisos, generar_si_toca
from .forms import (
    ACEPTA, AYUDA_DE_ARCHIVOS, AcuerdoForm, AvisoForm, BuscarTutorForm, CancelarForm, ConfiguracionForm, ConfirmarTutorForm,
    DisponibilidadForm, DocumentosForm, FiltroForm, IniciarForm, InasistenciaForm, MinutaForm, MotivoForm, ParticipantesForm,
    ProgramarForm, ReprogramarForm, SalaForm, SeguimientoAcuerdoForm, SolicitudForm, SustitutoForm,
)
from .models import (
    Acuerdo, AdjuntoReunion, EstudianteEnReunion, ConfiguracionReuniones, MotivoReunion, ParticipanteReunion, Reunion, SalaReunion, SeguimientoAcuerdo,
)
from .reglas import ReglaRota


def _con_relaciones(consulta):
    return consulta.select_related('tutor', 'motivo', 'sala', 'responsable').prefetch_related(
        Prefetch('estudiantes', queryset=EstudianteEnReunion.objects.select_related(
            'alumno', 'inscripcion__grado', 'inscripcion__grupo__grado', 'inscripcion__grupo__nombre')),
        Prefetch('participantes', queryset=ParticipanteReunion.objects.filter(activo=True).select_related('usuario'), to_attr='activos'),
        'tutores__tutor',
    )


def _comunes(request, acceso):
    return {
        'acceso': acceso, 'tonos': reglas.TONO_DE_ESTADO, 'iconos': reglas.ICONO_DE_ESTADO, 'tonos_prioridad': reglas.TONO_DE_PRIORIDAD,
        'hoy': timezone.localdate(), 'sin_niveles': SIN_NIVELES if acceso.sin_niveles else '',
        'atiende': acceso.registra or acceso.gestiona or acceso.todo,
    }


def _reunion(request, pk, acceso=None):
    """La reunión si la cuenta la puede ver (si no, 404)."""
    acceso = acceso or Acceso(request.user)
    reunion = get_object_or_404(acceso.reuniones().select_related('tutor', 'motivo', 'sala', 'responsable', 'registrada_por'), pk=pk)
    return reunion, acceso


def _exigir(condicion):
    if not condicion:
        raise PermissionDenied


def _al_detalle(reunion, ancla=''):
    return redirect(reverse('reuniones:detalle', args=[reunion.pk]) + (f'#{ancla}' if ancla else ''))


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------
@require_GET
@requiere_alguno(*QUE_ATIENDEN)
def inicio(request):
    acceso = Acceso(request.user)
    hoy = timezone.localdate()
    niveles = acceso.alcance.niveles_visibles() if not acceso.ve_todo else list(NOMBRE_DE_NIVEL.items())
    nivel = request.GET.get('nivel', '')
    if nivel not in dict(niveles):
        nivel = ''
    consulta = acceso.reuniones()
    if nivel:
        consulta = consulta.filter(estudiantes__inscripcion__grado__nivel=nivel).distinct()
    desde = hoy - timedelta(days=30)
    acuerdos = Acuerdo.objects.filter(reunion__in=consulta).exclude(reunion__estado=Reunion.CANCELADA)
    indicadores = [
        ('hoy', 'Reuniones de hoy', consulta.filter(fecha=hoy, estado__in=Reunion.ACTIVAS + (Reunion.REALIZADA,)).count(), 'calendar',
         f'{reverse("reuniones:agenda")}?vista=dia&fecha={hoy:%Y-%m-%d}'),
        ('sin_programar', 'Solicitudes sin programar', consulta.filter(estado__in=Reunion.SIN_PROGRAMAR).count(), 'phone',
         f'{reverse("reuniones:lista")}?estado=SOLICITADA'),
        ('por_confirmar', 'Pendientes de confirmación', consulta.filter(estado=Reunion.PROGRAMADA).count(), 'clock',
         f'{reverse("reuniones:lista")}?estado=PROGRAMADA'),
        ('realizadas', 'Realizadas (últimos 30 días)', consulta.filter(estado=Reunion.REALIZADA, fecha__gte=desde).count(), 'circle-check',
         f'{reverse("reuniones:lista")}?estado=REALIZADA&desde={desde:%Y-%m-%d}'),
        ('inasistencias', 'Inasistencias (últimos 30 días)', consulta.filter(estado=Reunion.NO_REALIZADA, fecha__gte=desde).count(), 'triangle-alert',
         f'{reverse("reuniones:lista")}?estado=NO_REALIZADA&desde={desde:%Y-%m-%d}'),
        ('vencidos', 'Compromisos vencidos', acuerdos.exclude(estado=Acuerdo.CUMPLIDO).filter(fecha_limite__lt=hoy).count(), 'flag',
         f'{reverse("reuniones:compromisos")}?estado=VENCIDO'),
    ]
    de_hoy = _con_relaciones(consulta.filter(fecha=hoy).exclude(estado__in=(Reunion.SOLICITADA, Reunion.PENDIENTE))).order_by('hora_inicio')
    por_programar = _con_relaciones(consulta.filter(estado__in=Reunion.SIN_PROGRAMAR)).order_by('-prioridad', 'creada')[:8]
    # Lo que necesita atención: citas próximas que no se han confirmado (con lo que les falta)
    atencion = []
    for reunion in _con_relaciones(consulta.filter(estado=Reunion.PROGRAMADA, fecha__gte=hoy, fecha__lte=hoy + timedelta(days=7))).order_by('fecha', 'hora_inicio')[:12]:
        atencion.append((reunion, reglas.faltantes(reunion)))
    proximas = _con_relaciones(consulta.filter(estado=Reunion.CONFIRMADA, fecha__gt=hoy)).order_by('fecha', 'hora_inicio')[:6]
    # Prioridad: urgente primero
    orden = {Reunion.URGENTE: 0, Reunion.ALTA: 1, Reunion.NORMAL: 2}
    por_programar = sorted(por_programar, key=lambda r: (orden[r.prioridad], r.creada))
    return render(request, 'reuniones/inicio.html', {
        **_comunes(request, acceso), 'indicadores': indicadores, 'de_hoy': de_hoy, 'por_programar': por_programar,
        'atencion': atencion, 'proximas': proximas, 'niveles': niveles, 'nivel': nivel,
        'puede_registrar': request.user.has_perm(REGISTRAR) or acceso.gestiona or acceso.todo,
    })


# ---------------------------------------------------------------------------
# Lista y agenda
# ---------------------------------------------------------------------------
@require_GET
@requiere_alguno(*DEL_MODULO)
def lista(request):
    acceso = Acceso(request.user)
    filtro = FiltroForm(request.GET or None, acceso=acceso)
    consulta = _con_relaciones(filtro.filtrar(acceso.reuniones()))
    consulta = consulta.order_by('-fecha', '-hora_inicio', '-creada') if request.GET.get('orden') != 'proximas' else consulta.order_by('fecha', 'hora_inicio')
    pagina, rango_paginas, por_pagina = paginar(request, consulta)
    totales = dict(acceso.reuniones().order_by().values_list('estado').annotate(total=Count('pk')))
    return render(request, 'reuniones/lista.html', {
        **_comunes(request, acceso), 'filtro': filtro, 'mas_filtros': filtro.activos, 'pagina': pagina, 'rango_paginas': rango_paginas,
        'por_pagina': por_pagina, 'por_pagina_defecto': POR_PAGINA_DEFECTO, 'opciones_por_pagina': OPCIONES_POR_PAGINA,
        'totales': [(clave, nombre, totales.get(clave, 0)) for clave, nombre in Reunion.ESTADOS],
        'vistas': calendario.VISTAS, 'vista': 'lista', 'consulta': request.GET.urlencode(),
    })


@require_GET
@requiere_alguno(*DEL_MODULO)
def agenda(request):
    acceso = Acceso(request.user)
    hoy = timezone.localdate()
    vista = request.GET.get('vista', 'semana')
    if vista not in ('dia', 'semana', 'mes'):
        vista = 'semana'
    fecha = calendario.fecha_pedida(request.GET.get('fecha', ''), hoy)
    filtro = FiltroForm(request.GET or None, acceso=acceso)
    desde, hasta = calendario.periodo(vista, fecha)
    reuniones = list(_con_relaciones(filtro.filtrar(acceso.reuniones(), con_fechas=False).filter(fecha__gte=desde, fecha__lte=hasta))
                     .order_by('fecha', 'hora_inicio'))
    configuracion = ConfiguracionReuniones.actual()
    contexto = {}
    if vista == 'dia':
        contexto['rejilla'] = calendario.dia(reuniones, fecha, SalaReunion.objects.all(), configuracion)
    elif vista == 'semana':
        contexto['rejilla'] = calendario.semana(reuniones, fecha, hoy, configuracion)
    else:
        contexto['semanas'] = calendario.mes(reuniones, fecha, hoy)
    if 'rejilla' in contexto and (vista == 'dia' and fecha == hoy or vista == 'semana' and desde <= hoy <= hasta):
        contexto['ahora'] = calendario.ahora_en(contexto['rejilla'], hoy, timezone.localtime().time())
    anterior, siguiente = calendario.navegacion(vista, fecha)
    conservar = request.GET.copy()
    for clave in ('vista', 'fecha', 'page'):
        conservar.pop(clave, None)

    def enlace(v=vista, f=fecha):
        datos = conservar.copy()
        datos['vista'], datos['fecha'] = v, f.isoformat()
        return f'{reverse("reuniones:agenda")}?{datos.urlencode()}'

    por_dia = {}
    for reunion in reuniones:
        if reunion.programada:
            por_dia.setdefault(reunion.fecha, []).append(reunion)
    return render(request, 'reuniones/agenda.html', {
        **_comunes(request, acceso), **contexto, 'filtro': filtro, 'mas_filtros': filtro.activos, 'vista': vista, 'vistas': calendario.VISTAS,
        'fecha': fecha, 'titulo': calendario.titulo(vista, fecha), 'reuniones': reuniones, 'por_dia': sorted(por_dia.items()),
        'anterior': enlace(f=anterior), 'siguiente': enlace(f=siguiente), 'hoy_url': enlace(f=hoy),
        'enlaces_de_vista': {v: enlace(v=v) for v, _ in calendario.VISTAS if v != 'lista'},
        'lista_url': f'{reverse("reuniones:lista")}?{conservar.urlencode()}', 'mes_actual': fecha.month,
        'filtros_qs': conservar.urlencode(), 'conservar_ocultos': [('vista', vista), ('fecha', fecha.isoformat())],
    })


# ---------------------------------------------------------------------------
# Registrar la llamada
# ---------------------------------------------------------------------------
def _tutores_encontrados(texto):
    consulta = Tutor.objects.filter(estatus='ACTIVO')
    for palabra in texto.split()[:5]:
        consulta = consulta.filter(
            Q(nombre__icontains=palabra) | Q(apellido_paterno__icontains=palabra) | Q(apellido_materno__icontains=palabra)
            | Q(telefono__icontains=palabra) | Q(telefono_alternativo__icontains=palabra)
            | Q(alumnos_relacionados__alumno__nombre__icontains=palabra, alumnos_relacionados__activo=True)
            | Q(alumnos_relacionados__alumno__apellido_paterno__icontains=palabra, alumnos_relacionados__activo=True))
    return consulta.distinct().order_by('nombre', 'apellido_paterno')[:20]


@requiere_alguno(*QUE_ATIENDEN)
def nueva(request):
    acceso = Acceso(request.user)
    tutor = None
    if request.GET.get('tutor', '').isdigit() or request.POST.get('tutor', '').isdigit():
        tutor = get_object_or_404(Tutor, pk=request.POST.get('tutor') or request.GET.get('tutor'), estatus='ACTIVO')
    if tutor is None:
        buscar = BuscarTutorForm(request.GET or None)
        texto = (request.GET.get('q') or '').strip()
        encontrados = []
        if len(texto) >= 2:
            for t in _tutores_encontrados(texto):
                hijos = [v.alumno for v in TutorAlumno.objects.filter(tutor=t, activo=True, alumno__estatus='ACTIVO').select_related('alumno')]
                encontrados.append((t, hijos))
        return render(request, 'reuniones/nueva_tutor.html', {**_comunes(request, acceso), 'buscar': buscar, 'texto': texto,
                                                               'encontrados': encontrados})

    form = SolicitudForm(request.POST or None, tutor=tutor)
    if request.method == 'POST' and form.is_valid():
        datos = form.cleaned_data
        alumnos = form.alumnos_elegidos()
        try:
            if not acceso.ve_todo:
                from .alcance import cubre
                inscripciones = [reglas.inscripcion_vigente(a) for a in alumnos]
                if not any(cubre(acceso.alcance, i) for i in inscripciones):
                    raise ReglaRota('Solo puedes registrar reuniones de los estudiantes de tus niveles.')
            reunion = reglas.registrar(
                tutor=tutor, alumnos=alumnos, telefono=datos['telefono'], telefono_verificado=datos['telefono_verificado'],
                area=datos['area'], motivo=datos['motivo'], descripcion=datos['descripcion'], prioridad=datos['prioridad'],
                propuestas=datos['lista_de_propuestas'], observaciones=datos['observaciones'], docentes=datos['docentes'],
                acompanante=datos['acompanante'], responsable=datos['responsable'], otros_tutores=datos['otros_tutores'],
                usuario=request.user,
            )
        except ReglaRota as error:
            for mensaje in error.mensajes:
                form.add_error(None, mensaje)
        else:
            messages.success(request, f'Se registró la solicitud {reunion.folio}. Queda {reunion.nombre_estado.lower()}: '
                                      'todavía no hay una cita confirmada.')
            return _al_detalle(reunion)
    antecedentes = (acceso.reuniones().filter(estudiantes__alumno__in=[a for a, _ in form.estudiantes]).distinct()
                    .select_related('motivo').order_by('-creada')[:5])
    return render(request, 'reuniones/nueva.html', {**_comunes(request, acceso), 'form': form, 'tutor': tutor, 'antecedentes': antecedentes})


# ---------------------------------------------------------------------------
# Detalle
# ---------------------------------------------------------------------------
def _puede(acceso, reunion, participacion):
    atiende, gestiona = acceso.atiende_reunion(reunion), acceso.gestiona_reunion(reunion)
    estado, hoy = reunion.estado, timezone.localdate()
    tiene_docentes = any(p.es_docente for p in reunion.activos)
    return {
        'atiende': atiende, 'gestiona': gestiona,
        'participantes': atiende and estado in (Reunion.SOLICITADA, Reunion.PENDIENTE, Reunion.PROGRAMADA, Reunion.CONFIRMADA),
        'programar': atiende and estado in Reunion.SIN_PROGRAMAR,
        'reprogramar': atiende and estado in Reunion.ACTIVAS,
        'confirmar_tutor': atiende and estado in (Reunion.PROGRAMADA, Reunion.CONFIRMADA),
        'aviso': atiende and estado in Reunion.ABIERTAS,
        'disponibilidad': participacion is not None and estado in (Reunion.PROGRAMADA, Reunion.CONFIRMADA),
        'disponibilidad_de_otros': atiende and estado in (Reunion.PROGRAMADA, Reunion.CONFIRMADA),
        'sustituto': gestiona and estado in Reunion.ACTIVAS and (tiene_docentes or any(p.es_acompanante for p in reunion.activos)),
        'iniciar': gestiona and estado in (Reunion.PROGRAMADA, Reunion.CONFIRMADA) and reunion.fecha == hoy,
        'inasistencia': gestiona and estado in (Reunion.PROGRAMADA, Reunion.CONFIRMADA) and reunion.fecha is not None and reunion.fecha <= hoy,
        'finalizar': gestiona and estado == Reunion.EN_CURSO,
        'editar_minuta': gestiona and estado == Reunion.REALIZADA,
        'cancelar': gestiona and estado in (Reunion.SOLICITADA, Reunion.PENDIENTE, Reunion.PROGRAMADA, Reunion.CONFIRMADA),
        'acuerdos': gestiona and estado in (Reunion.EN_CURSO, Reunion.REALIZADA),
        'documentos': gestiona and estado in (Reunion.EN_CURSO, Reunion.REALIZADA),
        'siguiente': atiende and estado in (Reunion.REALIZADA, Reunion.NO_REALIZADA, Reunion.CANCELADA),
        'observaciones': acceso.ve_observaciones(reunion),
        'confidencial': acceso.ve_confidencial(reunion),
    }


@require_GET
@requiere_alguno(*DEL_MODULO)
def detalle(request, pk):
    reunion, acceso = _reunion(request, pk)
    reunion = _con_relaciones(Reunion.objects.filter(pk=reunion.pk)).select_related('registrada_por', 'confirmacion_tutor__recibio',
                                                                                     'reunion_anterior', 'cerrada_por').get()
    participacion = acceso.participacion(reunion)
    puede = _puede(acceso, reunion, participacion)
    notificaciones.marcar_leidas(reunion, usuario=request.user)
    activos = reunion.activos
    alumnos = [e.alumno_id for e in reunion.estudiantes.all()]
    antecedentes = (acceso.reuniones().filter(estudiantes__alumno__in=alumnos).exclude(pk=reunion.pk).distinct()
                    .select_related('motivo').order_by('-creada'))
    acuerdos = list(reunion.acuerdos.select_related('responsable').prefetch_related('seguimientos__usuario'))
    minuta = reunion.minuta if hasattr(reunion, 'minuta') else None
    return render(request, 'reuniones/detalle.html', {
        **_comunes(request, acceso), 'reunion': reunion, 'puede': puede, 'participacion': participacion,
        'docentes': [p for p in activos if p.es_docente], 'acompanantes': [p for p in activos if p.es_acompanante],
        'personal': [p for p in activos if p.papel == ParticipanteReunion.PERSONAL],
        'retirados': reunion.participantes.filter(activo=False).select_related('usuario').order_by('retirado_en'),
        'faltantes': reglas.faltantes(reunion) if reunion.estado in (Reunion.PROGRAMADA, Reunion.CONFIRMADA) else [],
        'acompanamiento': reglas.acompanamiento_pendiente(reunion, activos) if reunion.abierta else [],
        'contactos': reunion.contactos.select_related('tutor', 'recibio', 'registrado_por'),
        'cambios': reunion.cambios_de_fecha.select_related('sala_anterior', 'sala_nueva', 'usuario'),
        'eventos': reunion.eventos.select_related('usuario', 'tutor'),
        'minuta': minuta, 'acuerdos': acuerdos, 'tonos_acuerdo': reglas.TONO_DE_ACUERDO,
        'adjuntos': reunion.adjuntos.select_related('subido_por'),
        'firmada': reunion.adjuntos.filter(clase=AdjuntoReunion.FIRMA).first(),
        'antecedentes': antecedentes[:6], 'total_antecedentes': antecedentes.count(),
        'siguientes': reunion.siguientes.order_by('creada'), 'faltaron': reglas.quienes_faltaron(reunion),
        'tutores': reunion.tutores.select_related('tutor'),
    })


# ---------------------------------------------------------------------------
# Acciones (formularios en ventana)
# ---------------------------------------------------------------------------
def _accion(request, reunion, form, *, plantilla='reuniones/accion.html', titulo, descripcion='', boton='Guardar', peligro=False,
            ejecutar, exito, ancla='', extra=None):
    if request.method == 'POST' and form.is_valid():
        try:
            resultado = ejecutar(form.cleaned_data)
        except ReglaRota as error:
            for mensaje in error.mensajes:
                form.add_error(None, mensaje)
        else:
            messages.success(request, exito(resultado) if callable(exito) else exito)
            destino = resultado if isinstance(resultado, Reunion) and resultado.pk != reunion.pk else reunion
            return _al_detalle(destino, ancla)
    return render(request, plantilla, {
        'reunion': reunion, 'form': form, 'titulo': titulo, 'descripcion': descripcion, 'boton': boton, 'peligro': peligro,
        'volver': reverse('reuniones:detalle', args=[reunion.pk]), **(extra or {}),
    })


@requiere_alguno(*QUE_ATIENDEN)
def participantes(request, pk):
    reunion, acceso = _reunion(request, pk)
    _exigir(acceso.atiende_reunion(reunion))
    form = ParticipantesForm(request.POST or None, reunion=reunion)

    def ejecutar(datos):
        return reglas.definir_participantes(reunion, docentes=datos['docentes'], acompanantes=datos['acompanantes'], personal=datos['personal'],
                                            responsable=datos['responsable'], tutores=datos['tutores'], usuario=request.user)
    return _accion(request, reunion, form, plantilla='reuniones/participantes.html', titulo=f'Participantes de {reunion.folio}',
                   descripcion='Toda reunión con un docente necesita al menos un acompañante directivo (dirección, coordinación académica o '
                               'prefectura de estos niveles). Uno puede acompañar a varios docentes.',
                   ejecutar=ejecutar, exito='Se actualizaron los participantes.', ancla='participantes')


@requiere_alguno(*QUE_ATIENDEN)
def programar(request, pk):
    reunion, acceso = _reunion(request, pk)
    _exigir(acceso.atiende_reunion(reunion))
    form = ProgramarForm(request.POST or None, reunion=reunion)

    def ejecutar(datos):
        return reglas.programar(reunion, fecha=datos['fecha'], inicio=datos['hora_inicio'], fin=datos['hora_fin'], sala=datos['sala'],
                                usuario=request.user)
    return _accion(request, reunion, form, plantilla='reuniones/programar.html', titulo=f'Programar {reunion.folio}',
                   descripcion='Se revisan el horario de atención, las otras reuniones del personal, de la familia y de la sala, y las clases '
                               'de los docentes. Programar no confirma la cita: después se registran las confirmaciones.',
                   boton='Programar', ejecutar=ejecutar, exito='Se programó la cita. Ahora falta que la confirmen la familia y el personal.',
                   extra={'propuestas': reunion.propuestas, 'configuracion': ConfiguracionReuniones.actual()})


@requiere_alguno(*QUE_ATIENDEN)
def reprogramar(request, pk):
    reunion, acceso = _reunion(request, pk)
    _exigir(acceso.atiende_reunion(reunion))
    form = ReprogramarForm(request.POST or None, reunion=reunion)

    def ejecutar(datos):
        return reglas.reprogramar(reunion, fecha=datos['fecha'], inicio=datos['hora_inicio'], fin=datos['hora_fin'], sala=datos['sala'],
                                  motivo=datos['motivo'], usuario=request.user)
    return _accion(request, reunion, form, plantilla='reuniones/programar.html', titulo=f'Reprogramar {reunion.folio}',
                   descripcion='La fecha anterior queda en el historial con el motivo. Las confirmaciones se piden de nuevo.',
                   boton='Reprogramar', ejecutar=ejecutar, exito='Se reprogramó la cita y se pidió confirmar de nuevo.',
                   extra={'propuestas': reunion.propuestas, 'configuracion': ConfiguracionReuniones.actual()})


@requiere_alguno(*QUE_ATIENDEN)
def confirmar_tutor(request, pk):
    reunion, acceso = _reunion(request, pk)
    _exigir(acceso.atiende_reunion(reunion))
    form = ConfirmarTutorForm(request.POST or None, reunion=reunion, usuario=request.user)

    def ejecutar(datos):
        return reglas.confirmar_tutor(reunion, medio=datos['medio'], momento=datos['momento'], recibio=datos['recibio'], nota=datos['nota'],
                                      usuario=request.user, tutor=datos['tutor'])
    return _accion(request, reunion, form, titulo='Registrar la confirmación del tutor',
                   descripcion='Anota quién recibió la confirmación, cuándo y por qué medio. La cita queda confirmada cuando también '
                               'confirmó todo el personal (con su acompañante directivo, si participa un docente).',
                   boton='Registrar confirmación', ejecutar=ejecutar, exito='Se registró la confirmación del tutor.', ancla='confirmaciones')


@requiere_alguno(*QUE_ATIENDEN)
def aviso(request, pk):
    reunion, acceso = _reunion(request, pk)
    _exigir(acceso.atiende_reunion(reunion))
    form = AvisoForm(request.POST or None, reunion=reunion, usuario=request.user)

    def ejecutar(datos):
        return reglas.registrar_aviso(reunion, medio=datos['medio'], momento=datos['momento'], nota=datos['nota'], tutor=datos['tutor'],
                                      usuario=request.user)
    return _accion(request, reunion, form, titulo='Registrar un aviso a la familia',
                   descripcion='El sistema no envía correos ni mensajes de WhatsApp: aquí se anota el aviso que hiciste por teléfono u otro medio.',
                   boton='Registrar aviso', ejecutar=ejecutar, exito='Se registró el aviso a la familia.', ancla='confirmaciones')


@requiere_alguno(*DEL_MODULO)
def disponibilidad(request, pk, participante=None):
    reunion, acceso = _reunion(request, pk)
    if participante is None:
        objeto = acceso.participacion(reunion)
        if objeto is None:
            raise Http404('No participas en esta reunión.')
    else:
        _exigir(acceso.atiende_reunion(reunion))
        objeto = get_object_or_404(reunion.participantes.select_related('usuario'), pk=participante, activo=True)
    form = DisponibilidadForm(request.POST or None)
    from .disponibilidad import nombre_de_usuario
    propio = objeto.usuario_id == request.user.pk

    def ejecutar(datos):
        return reglas.confirmar_disponibilidad(objeto, disponible=datos['disponible'], nota=datos['nota'], usuario=request.user)
    return _accion(request, reunion, form, plantilla='reuniones/disponibilidad.html',
                   titulo='Confirmar tu disponibilidad' if propio else f'Disponibilidad de {nombre_de_usuario(objeto.usuario)}',
                   descripcion='Se revisa que no tengas otra reunión ni clase en ese horario. Confirmar tu disponibilidad no confirma la '
                               'cita con la familia: eso lo registra el personal que la atiende.',
                   boton='Guardar', ejecutar=ejecutar, exito='Se registró la disponibilidad.', ancla='participantes',
                   extra={'participante': objeto})


@requiere_alguno(GESTIONAR, TODO)
def sustituto(request, pk):
    reunion, acceso = _reunion(request, pk)
    _exigir(acceso.gestiona_reunion(reunion))
    form = SustitutoForm(request.POST or None, reunion=reunion)

    def ejecutar(datos):
        return reglas.asignar_sustituto(reunion, nuevo=datos['nuevo'], ausente=datos['ausente'], motivo=datos['motivo'], usuario=request.user)
    return _accion(request, reunion, form, titulo='Asignar un acompañante sustituto',
                   descripcion='Si el acompañante directivo no asiste o dejó de estar disponible. Solo aparecen quienes están autorizados '
                               'para estos niveles y libres en ese horario; si no hay nadie, reprograma la reunión.',
                   boton='Asignar sustituto', ejecutar=ejecutar, exito='Se asignó el acompañante sustituto.', ancla='participantes')


@requiere_alguno(GESTIONAR, TODO)
def iniciar(request, pk):
    reunion, acceso = _reunion(request, pk)
    _exigir(acceso.gestiona_reunion(reunion))
    form = IniciarForm(request.POST or None, reunion=reunion)

    def ejecutar(datos):
        presentes, tutores = form.marcados()
        return reglas.iniciar(reunion, presentes=presentes, tutores_presentes=tutores, usuario=request.user)
    return _accion(request, reunion, form, plantilla='reuniones/asistencia.html', titulo='Iniciar la reunión',
                   descripcion='Marca quién está presente. Con un docente presente debe estar también un acompañante directivo autorizado.',
                   boton='Iniciar reunión', ejecutar=ejecutar, exito='La reunión está en curso. Al terminar, registra la minuta.', ancla='minuta',
                   extra={'puede_sustituir': acceso.gestiona_reunion(reunion)})


@requiere_alguno(GESTIONAR, TODO)
def inasistencia(request, pk):
    reunion, acceso = _reunion(request, pk)
    _exigir(acceso.gestiona_reunion(reunion))
    form = InasistenciaForm(request.POST or None, reunion=reunion)

    def ejecutar(datos):
        personal, tutores = form.marcados()
        return reglas.marcar_inasistencia(reunion, tutores_ausentes=tutores, participantes_ausentes=personal, nota=datos['nota'],
                                          usuario=request.user)
    return _accion(request, reunion, form, plantilla='reuniones/asistencia.html', titulo='No realizada por inasistencia',
                   descripcion='Marca quién faltó: el tutor, un docente o el acompañante directivo. Después puedes programar otra reunión '
                               'vinculada con esta.', boton='Registrar inasistencia', peligro=True, ejecutar=ejecutar,
                   exito='Se registró la inasistencia.')


@requiere_alguno(GESTIONAR, TODO)
def finalizar(request, pk):
    reunion, acceso = _reunion(request, pk)
    _exigir(acceso.gestiona_reunion(reunion))
    editar = reunion.estado == Reunion.REALIZADA
    confidencial = acceso.ve_confidencial(reunion)
    minuta = reunion.minuta if editar and hasattr(reunion, 'minuta') else None
    inicial = None
    if minuta is not None:
        inicial = {campo: getattr(minuta, campo) for campo in ('inicio_real', 'fin_real', 'temas', 'resumen', 'notas_internas',
                                                                 'siguiente_reunion', 'siguiente_reunion_nota')}
    form = MinutaForm(request.POST or None, reunion=reunion, confidencial=confidencial, initial=inicial)

    def ejecutar(datos):
        if editar:
            return reglas.editar_minuta(reunion, datos=datos, usuario=request.user, puede_confidencial=confidencial)
        return reglas.finalizar(reunion, datos=datos, presentes_toda=form.presentes_toda(), usuario=request.user, puede_confidencial=confidencial)
    return _accion(request, reunion, form, plantilla='reuniones/minuta_form.html', titulo='Editar la minuta' if editar else 'Registrar la minuta',
                   descripcion='Los acuerdos y los documentos se agregan en la reunión. Las notas internas confidenciales nunca se muestran '
                               'a la familia.', boton='Guardar minuta' if editar else 'Terminar la reunión', ejecutar=ejecutar,
                   exito='Se guardó la minuta.' if editar else 'La reunión quedó realizada. Registra los acuerdos y los documentos.',
                   ancla='minuta', extra={'editar': editar, 'confidencial': confidencial})


@requiere_alguno(GESTIONAR, TODO)
def cancelar(request, pk):
    reunion, acceso = _reunion(request, pk)
    _exigir(acceso.gestiona_reunion(reunion))
    form = CancelarForm(request.POST or None)
    return _accion(request, reunion, form, titulo=f'Cancelar {reunion.folio}', descripcion='Se avisa al personal y a la familia.',
                   boton='Cancelar la reunión', peligro=True,
                   ejecutar=lambda datos: reglas.cancelar(reunion, motivo=datos['motivo'], usuario=request.user), exito='Se canceló la reunión.')


@require_POST
@requiere_alguno(*QUE_ATIENDEN)
def siguiente(request, pk):
    reunion, acceso = _reunion(request, pk)
    _exigir(acceso.atiende_reunion(reunion))
    try:
        nueva = reglas.programar_siguiente(reunion, usuario=request.user)
    except ReglaRota as error:
        messages.error(request, ' '.join(error.mensajes))
        return _al_detalle(reunion)
    messages.success(request, f'Se registró la reunión de seguimiento {nueva.folio}, vinculada con {reunion.folio}. Prográmala.')
    return _al_detalle(nueva)


# ---------------------------------------------------------------------------
# Acuerdos y documentos
# ---------------------------------------------------------------------------
@requiere_alguno(GESTIONAR, TODO)
def acuerdo(request, pk, acuerdo_pk=None):
    reunion, acceso = _reunion(request, pk)
    _exigir(acceso.gestiona_reunion(reunion))
    instancia = get_object_or_404(reunion.acuerdos, pk=acuerdo_pk) if acuerdo_pk else None
    form = AcuerdoForm(request.POST or None, instance=instancia, reunion=reunion)

    def ejecutar(datos):
        return reglas.guardar_acuerdo(reunion, datos=datos, usuario=request.user, acuerdo=instancia)
    return _accion(request, reunion, form, plantilla='reuniones/accion.html', titulo='Editar el acuerdo' if instancia else 'Nuevo acuerdo',
                   descripcion='Con su responsable y su fecha límite. Si lo compartes, la familia lo ve en su portal y en su minuta.',
                   ejecutar=ejecutar, exito='Se guardó el acuerdo.', ancla='acuerdos')


def _acuerdo_visible(request, pk):
    acceso = Acceso(request.user)
    objeto = get_object_or_404(Acuerdo.objects.select_related('reunion', 'responsable'), pk=pk)
    if not acceso.puede_ver(objeto.reunion):
        raise Http404
    return objeto, acceso


@requiere_alguno(*DEL_MODULO)
def seguimiento(request, pk):
    objeto, acceso = _acuerdo_visible(request, pk)
    _exigir(acceso.gestiona_reunion(objeto.reunion) or objeto.responsable_id == request.user.pk)
    form = SeguimientoAcuerdoForm(request.POST or None, request.FILES or None, acuerdo=objeto)

    def ejecutar(datos):
        return reglas.seguir_acuerdo(objeto, estado=datos['estado'], nota=datos['nota'], usuario=request.user, evidencia=datos.get('evidencia'),
                                     tipo_evidencia=getattr(form, 'tipo_evidencia', ''))
    return _accion(request, objeto.reunion, form, plantilla='reuniones/seguimiento.html', titulo='Seguimiento del acuerdo',
                   descripcion=objeto.descripcion, boton='Guardar seguimiento', ejecutar=ejecutar, exito='Se guardó el seguimiento.',
                   ancla='acuerdos', extra={'acuerdo': objeto})


@requiere_alguno(GESTIONAR, TODO)
def documentos(request, pk):
    reunion, acceso = _reunion(request, pk)
    _exigir(acceso.gestiona_reunion(reunion))
    form = DocumentosForm(request.POST or None, archivos=request.FILES.getlist('archivos') if request.method == 'POST' else None)
    if request.method == 'GET' and request.GET.get('clase') == AdjuntoReunion.FIRMA:
        form = DocumentosForm(initial={'clase': AdjuntoReunion.FIRMA})

    def ejecutar(datos):
        return reglas.agregar_documentos(reunion, archivos=datos['validos'], clase=datos['clase'], compartido=datos['compartido'],
                                         usuario=request.user)
    return _accion(request, reunion, form, plantilla='reuniones/documentos.html', titulo='Agregar documentos',
                   descripcion='La evidencia de firma es la foto o el PDF de la minuta firmada: sin ella, la minuta no se muestra como firmada.',
                   boton='Subir', ejecutar=ejecutar, exito='Se agregaron los documentos.', ancla='documentos',
                   extra={'acepta': ACEPTA, 'ayuda_archivos': AYUDA_DE_ARCHIVOS})


@require_GET
@requiere_alguno(*DEL_MODULO)
def documento(request, pk):
    adjunto = get_object_or_404(AdjuntoReunion.objects.select_related('reunion'), pk=pk)
    if not Acceso(request.user).puede_ver(adjunto.reunion):
        raise Http404
    from Conducta.views import entregar_archivo
    return entregar_archivo(adjunto.archivo, adjunto.nombre_original, adjunto.tipo, descargar=request.GET.get('descargar') == '1')


@require_GET
@requiere_alguno(*DEL_MODULO)
def evidencia(request, pk):
    objeto = get_object_or_404(SeguimientoAcuerdo.objects.select_related('acuerdo__reunion'), pk=pk)
    if not objeto.evidencia or not Acceso(request.user).puede_ver(objeto.acuerdo.reunion):
        raise Http404
    from Conducta.views import entregar_archivo
    return entregar_archivo(objeto.evidencia, objeto.evidencia_nombre, objeto.evidencia_tipo, descargar=request.GET.get('descargar') == '1')


@require_GET
@requiere_alguno(*DEL_MODULO)
def minuta(request, pk):
    """La minuta lista para imprimir o guardar en PDF: la de la familia (sin notas internas ni acuerdos no compartidos) o,
    con el permiso de notas confidenciales, la interna."""
    reunion, acceso = _reunion(request, pk)
    if reunion.estado != Reunion.REALIZADA or not hasattr(reunion, 'minuta'):
        raise Http404('La reunión todavía no tiene minuta.')
    interna = request.GET.get('version') == 'interna'
    if interna and not acceso.ve_confidencial(reunion):
        raise PermissionDenied
    return render(request, 'reuniones/minuta_hoja.html', contexto_de_minuta(request, reunion, interna=interna,
                                                                            volver=reverse('reuniones:detalle', args=[reunion.pk])))


def contexto_de_minuta(request, reunion, *, interna, volver):
    acuerdos = reunion.acuerdos.select_related('responsable')
    if not interna:
        acuerdos = acuerdos.filter(compartido=True)
    from .models import PRESENTE
    asistentes_personal = reunion.participantes.filter(asistencia=PRESENTE).select_related('usuario').order_by('papel')
    asistentes_familia = reunion.tutores.filter(asistencia=PRESENTE).select_related('tutor')
    firma = reunion.adjuntos.filter(clase=AdjuntoReunion.FIRMA).order_by('creado').first()
    return {
        'reunion': reunion, 'minuta': reunion.minuta, 'interna': interna, 'acuerdos': acuerdos, 'personal': asistentes_personal,
        'familia': asistentes_familia, 'estudiantes': reunion.estudiantes.select_related('alumno', 'inscripcion__grado', 'inscripcion__grupo__nombre'),
        'firma': firma, 'generado': timezone.localtime(), 'volver': volver, 'imprimir_al_abrir': request.GET.get('pdf') == '1',
    }


# ---------------------------------------------------------------------------
# Compromisos e historial del estudiante
# ---------------------------------------------------------------------------
@require_GET
@requiere_alguno(*DEL_MODULO)
def compromisos(request):
    acceso = Acceso(request.user)
    hoy = timezone.localdate()
    consulta = (Acuerdo.objects.filter(reunion__in=acceso.reuniones()).exclude(reunion__estado=Reunion.CANCELADA)
                .select_related('reunion__tutor', 'responsable').order_by('fecha_limite', 'pk'))
    estado = request.GET.get('estado', 'ABIERTOS')
    if estado == 'VENCIDO':
        consulta = consulta.exclude(estado=Acuerdo.CUMPLIDO).filter(fecha_limite__lt=hoy)
    elif estado in (Acuerdo.PENDIENTE, Acuerdo.EN_PROCESO, Acuerdo.CUMPLIDO):
        consulta = consulta.filter(estado=estado)
    else:
        estado = 'ABIERTOS'
        consulta = consulta.exclude(estado=Acuerdo.CUMPLIDO)
    if request.GET.get('mios') == '1':
        consulta = consulta.filter(Q(responsable=request.user) | Q(responsable__isnull=True, reunion__responsable=request.user))
    pagina, rango_paginas, por_pagina = paginar(request, consulta)
    return render(request, 'reuniones/compromisos.html', {
        **_comunes(request, acceso), 'pagina': pagina, 'rango_paginas': rango_paginas, 'por_pagina': por_pagina,
        'opciones_por_pagina': OPCIONES_POR_PAGINA, 'estado': estado, 'mios': request.GET.get('mios') == '1',
        'tonos_acuerdo': reglas.TONO_DE_ACUERDO,
        'estados': [('ABIERTOS', 'Sin cumplir'), ('VENCIDO', 'Vencidos'), (Acuerdo.PENDIENTE, 'Pendientes'), (Acuerdo.EN_PROCESO, 'En proceso'),
                    (Acuerdo.CUMPLIDO, 'Cumplidos')],
    })


@require_GET
@requiere_alguno(*DEL_MODULO)
def estudiante(request, pk):
    acceso = Acceso(request.user)
    alumno = get_object_or_404(Alumno, pk=pk)
    reuniones = _con_relaciones(acceso.reuniones().filter(estudiantes__alumno=alumno).distinct()).order_by('-creada')
    if not reuniones.exists() and not (acceso.ve_todo or request.user.has_perm('Alumnos.view_alumno')):
        raise Http404
    acuerdos = (Acuerdo.objects.filter(reunion__in=reuniones).exclude(reunion__estado=Reunion.CANCELADA)
                .select_related('reunion', 'responsable').order_by('estado', 'fecha_limite'))
    return render(request, 'reuniones/estudiante.html', {
        **_comunes(request, acceso), 'alumno': alumno, 'reuniones': reuniones, 'acuerdos': acuerdos, 'tonos_acuerdo': reglas.TONO_DE_ACUERDO,
        'inscripcion': reglas.inscripcion_vigente(alumno),
    })


@require_GET
@requiere_alguno(*DEL_MODULO)
def resumen(request):
    """La sección de reuniones de la campana, en JSON (static/js/reuniones-avisos.js). Antes genera, si toca, los
    recordatorios y los avisos de acuerdos de la cuenta."""
    generar_si_toca(usuario=request.user)
    return JsonResponse(datos_de_avisos(usuario=request.user))


# ---------------------------------------------------------------------------
# Ajustes › Reuniones (solo el administrador)
# ---------------------------------------------------------------------------
@requiere_permisos(CONFIGURAR)
def ajustes(request):
    configuracion = ConfiguracionReuniones.actual()
    form = ConfiguracionForm(request.POST or None, instance=configuracion)
    if request.method == 'POST' and form.is_valid():
        configuracion = form.save(commit=False)
        configuracion.modificado_por = request.user
        configuracion.save()
        messages.success(request, 'Se guardó la configuración de las reuniones.')
        return redirect('reuniones:ajustes')
    permisos = []
    from Usuarios.catalogo import etiqueta_de
    for permiso, descripcion in ((REGISTRAR, 'Registrar llamadas, consultar la disponibilidad y programar'),
                                 (GESTIONAR, 'Gestionar las reuniones de sus niveles'),
                                 ('Reuniones.acompanar', 'Acompañar como directivo las reuniones con docentes'),
                                 ('Reuniones.confidencial', 'Ver las notas internas confidenciales'),
                                 (PARTICIPAR, 'Ver y confirmar las reuniones en que participa')):
        codigo = permiso.split('.')[1]
        from Usuarios.models import Rol
        roles = Rol.objects.filter(Q(acceso_total=True) | Q(grupo__permissions__codename=codigo, grupo__permissions__content_type__app_label='Reuniones')).distinct()
        permisos.append((descripcion, etiqueta_de(permiso), [r.grupo.name for r in roles]))
    return render(request, 'reuniones/ajustes.html', {
        'form': form, 'motivos': MotivoReunion.objects.annotate(usos=Count('reuniones')), 'salas': SalaReunion.objects.annotate(usos=Count('reuniones')),
        'permisos': permisos, 'ajustes_seccion': 'reuniones', 'acompanantes': cuentas_con_permiso('Reuniones.acompanar'),
    })


def _catalogo(request, modelo, formulario, nombre, pk=None):
    instancia = get_object_or_404(modelo, pk=pk) if pk else None
    form = formulario(request.POST or None, instance=instancia)
    if request.method == 'POST' and form.is_valid():
        objeto = form.save()
        messages.success(request, f'Se guardó {nombre} «{objeto}».')
        return redirect('reuniones:ajustes')
    return render(request, 'reuniones/catalogo_form.html', {'form': form, 'instancia': instancia, 'nombre': nombre,
                                                            'volver': reverse('reuniones:ajustes'), 'ajustes_seccion': 'reuniones'})


@requiere_permisos(CONFIGURAR)
def motivo(request, pk=None):
    return _catalogo(request, MotivoReunion, MotivoForm, 'el motivo', pk)


@requiere_permisos(CONFIGURAR)
def sala(request, pk=None):
    return _catalogo(request, SalaReunion, SalaForm, 'la sala', pk)
