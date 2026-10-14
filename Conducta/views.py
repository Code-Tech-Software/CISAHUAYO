"""Registro de conducta: listado, alta, detalle, edición con trazabilidad, seguimiento, anulación, evidencias, contactos
con la familia, citas, compromisos, avisos de reincidencia, pendientes y solicitudes de aprobación.

Sirve a la administración (Conducta.*_registroconducta: todo el colegio) y a prefectura (Prefectura.*): la misma
pantalla y los mismos datos. Una cuenta de prefectura solo ve a los estudiantes de su alcance (Prefectura/alcance.py):
lo de fuera responde 404 aunque se teclee la dirección. Qué puede hacer cada quien con cada registro lo decide
Conducta/permisos.py en cada petición, no solo ocultando botones. Las evidencias y los acuses se entregan solo por
estas vistas, con los mismos permisos (y el mismo alcance) del registro.
"""
import logging

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, F, Prefetch, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from Alumnos.models import Alumno, Inscripcion
from CISAHUAYO.paginacion import OPCIONES_POR_PAGINA, POR_PAGINA_DEFECTO, paginar
from CISAHUAYO.permisos import requiere_alguno, requiere_permisos
from CISAHUAYO.redireccion import destino_seguro
from Prefectura.alcance import alcance_de

from . import permisos as P
from . import reglas
from .forms import (
    ACEPTA,
    EVIDENCIAS_POR_ENVIO,
    TAMANO_MAXIMO_MB,
    ActualizarCitaForm,
    AnularForm,
    CancelarSolicitudForm,
    CitaForm,
    CompromisoForm,
    ContactoForm,
    FiltroForm,
    RegistroForm,
    ResolverCompromisoForm,
    ResolverForm,
    RevisarAvisoForm,
    SeguimientoForm,
    validar_archivo,
)
from .models import (
    INCIDENCIA,
    PENDIENTE,
    POSITIVA,
    AvisoReincidencia,
    CambioConducta,
    CitaTutor,
    Compromiso,
    ContactoTutor,
    EvidenciaConducta,
    MedidaAplicada,
    RegistroConducta,
    Suspension,
)

logger = logging.getLogger(__name__)
SEGUIMIENTO = (P.EDITAR, P.PREF_SEGUIMIENTO)
CORRECCION = (P.EDITAR, P.PREF_CORREGIR, P.PREF_CORREGIR_OTROS)


def registros_de(usuario):
    """Los registros que la persona puede ver: todos, o los de los estudiantes de su alcance."""
    return alcance_de(usuario).filtrar(RegistroConducta.objects.all())


def _registro(request, pk):
    """El registro si está en el alcance de quien pide (si no, 404: no se dice si existe)."""
    return get_object_or_404(
        registros_de(request.user).select_related(
            'alumno', 'inscripcion', 'ciclo', 'grado', 'grupo__nombre', 'grupo__grado', 'periodo', 'categoria', 'motivo',
            'responsable', 'registrado_por', 'modificado_por', 'anulado_por', 'cerrado_por',
        ),
        pk=pk,
    )


def _exigir(condicion):
    if not condicion:
        raise PermissionDenied


def _plural(n, singular, plural=None):
    return f'{n} {singular if n == 1 else (plural or singular + "s")}'


def contexto_de_pestanas(usuario):
    """Las insignias de las pestañas (pendientes y solicitudes) dentro del alcance de la persona."""
    registros = registros_de(usuario)
    return {'pendientes': reglas.cuantos_pendientes(registros=registros), 'solicitudes': reglas.cuantas_solicitudes(registros)}


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------
@requiere_alguno(*P.CONSULTAR)
def lista(request):
    alcance = alcance_de(request.user)
    form = FiltroForm(request.GET or None, modo='lista', alcance=alcance)
    filtro = form.filtro()
    filtrados = filtro.aplicar(registros_de(request.user))
    registros = (
        filtrados.select_related('alumno', 'grado', 'grupo__nombre', 'grupo__grado', 'registrado_por', 'suspension')
        .prefetch_related(reglas.medidas_visibles()).order_by('-fecha', '-hora', '-pk')
    )
    pagina, rango_paginas, por_pagina = paginar(request, registros)
    conteo = filtrados.aggregate(
        incidencias=Count('pk', filter=Q(tipo=INCIDENCIA)), positivas=Count('pk', filter=Q(tipo=POSITIVA)),
        estudiantes=Count('alumno', distinct=True),
    )
    return render(request, 'conducta/lista.html', {
        'seccion': 'registros',
        'filtro': form,
        'alcance': alcance,
        'aviso_de_fechas': filtro.rango()[2],
        'mas_filtros': form.activos,
        'conteo': conteo,
        'pagina': pagina,
        'rango_paginas': rango_paginas,
        'por_pagina': por_pagina,
        'por_pagina_defecto': POR_PAGINA_DEFECTO,
        'opciones_por_pagina': OPCIONES_POR_PAGINA,
        'puede_registrar': P.puede_registrar(request.user),
        **contexto_de_pestanas(request.user),
    })


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
def _guardar_evidencias(registro, archivos, usuario):
    for archivo, tipo in archivos:
        EvidenciaConducta.objects.create(
            registro=registro, archivo=archivo, nombre_original=archivo.name[:200], tipo=tipo, tamano=archivo.size,
            subida_por=usuario,
        )


def _contexto_escolar_mostrado(form, registro):
    """Lo que se ve de su inscripción: el del registro al editar (congelado); al registrar, el de la fecha elegida."""
    if registro is not None:
        return {'ciclo': registro.ciclo, 'nivel': registro.nivel, 'grado': registro.grado, 'grupo_texto': registro.grupo_texto,
                'periodo': registro.periodo}
    if form.inscripcion is None:
        return None
    fecha = form._fecha_de((form.data if form.is_bound else form.initial).get('fecha')) or timezone.localdate()
    return reglas.contexto_escolar(form.inscripcion, fecha)


def _contexto_del_formulario(request, form, registro=None):
    nivel = form.nivel
    return {
        'seccion': 'registros',
        'form': form,
        'registro': registro,
        'es_edicion': registro is not None,
        'alumno': form.alumno,
        'inscripcion': form.inscripcion,
        'contexto': _contexto_escolar_mostrado(form, registro),
        'nombre_de_nivel': reglas.NOMBRE_DE_NIVEL.get(nivel, ''),
        'opciones': reglas.opciones_del_nivel(nivel, solo_prefectura=form.solo_prefectura) if nivel else None,
        'medidas_info': {m.pk: m for m in form.fields['medidas'].queryset} if nivel else {},
        'superpuestas': getattr(form, 'superpuestas', []),
        'aprueba': form.aprueba,
        'aprueba_parcial': form.aprueba_alguno and not form.aprueba_todos and not form.nivel,
        'solo_prefectura': form.solo_prefectura,
        'url_buscar': reverse('conducta:buscar'),
        'url_opciones': reverse('conducta:opciones'),
        'acepta': ACEPTA,
        'maximo_mb': TAMANO_MAXIMO_MB,
        'por_envio': EVIDENCIAS_POR_ENVIO,
    }


def _avisos_de_aprobacion(request, registro):
    suspension = Suspension.objects.filter(registro=registro).first()
    if suspension is not None and suspension.pendiente:
        messages.info(request, 'La suspensión quedó como solicitud pendiente: la debe aprobar Dirección o quien tenga el permiso de aprobar.')
    pendientes = registro.medidas_aplicadas.filter(estado=PENDIENTE, implica_suspension=False)
    if pendientes.exists():
        nombres = ', '.join(f'«{m.nombre}»' for m in pendientes)
        messages.info(request, f'Pendiente de aprobación: {nombres}.')


@requiere_alguno(*P.ALTA)
def crear(request):
    alumnos = alcance_de(request.user).alumnos()
    alumno_id = request.GET.get('alumno', '')
    alumno = alumnos.filter(pk=alumno_id).exclude(estatus='BAJA').first() if alumno_id.isdigit() else None
    if request.method == 'POST':
        form = RegistroForm(request.POST, request.FILES, usuario=request.user, alumnos=alumnos)
        if form.is_valid():
            datos = form.cleaned_data
            contexto = datos['contexto']
            registro = RegistroConducta(
                alumno=contexto['alumno'], inscripcion=contexto['inscripcion'], ciclo=contexto['ciclo'],
                nivel=contexto['nivel'], grado=contexto['grado'], grupo=contexto['grupo'], grupo_texto=contexto['grupo_texto'],
            )
            try:
                with transaction.atomic():
                    registro = reglas.guardar_registro(registro, datos, request.user)
                    _guardar_evidencias(registro, datos['evidencias'], request.user)
            except Exception:   # el almacenamiento de archivos no respondió: no se guarda nada
                logger.exception('No se pudo guardar el registro de conducta con sus evidencias')
                messages.error(request, 'No se pudieron guardar las evidencias: no se registró nada. Inténtalo de nuevo.')
            else:
                texto = f'Se registró la {"incidencia" if registro.tipo == INCIDENCIA else "conducta positiva"} de {registro.alumno}.'
                if datos['evidencias']:
                    texto += f' Con {_plural(len(datos["evidencias"]), "evidencia")}.'
                if hasattr(registro, 'aviso_reincidencia'):
                    messages.warning(request, f'Aviso de reincidencia: {registro.alumno} suma {registro.aviso_reincidencia.cantidad} '
                                              f'incidencias de «{registro.motivo_nombre}» en {registro.aviso_reincidencia.dias} días. Revísalo.')
                messages.success(request, texto)
                _avisos_de_aprobacion(request, registro)
                return redirect('conducta:detalle', registro.pk)
        else:
            messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    else:
        ahora = timezone.localtime()
        form = RegistroForm(alumno=alumno, usuario=request.user, alumnos=alumnos,
                            initial={'fecha': ahora.date(), 'hora': ahora.strftime('%H:%M'), 'tipo': INCIDENCIA})
    return render(request, 'conducta/form.html', _contexto_del_formulario(request, form))


@requiere_alguno(*CORRECCION)
def editar(request, pk):
    registro = _registro(request, pk)
    if registro.anulado:
        messages.info(request, 'Ese registro está anulado: ya no se modifica.')
        return redirect('conducta:detalle', registro.pk)
    _exigir(P.puede_corregir(request.user, registro))
    if request.method == 'POST':
        form = RegistroForm(request.POST, request.FILES, registro=registro, usuario=request.user)
        if form.is_valid():
            datos = form.cleaned_data
            try:
                with transaction.atomic():
                    registro = reglas.guardar_registro(registro, datos, request.user, motivo=datos['motivo_cambio'])
                    if datos['evidencias']:
                        _guardar_evidencias(registro, datos['evidencias'], request.user)
                        reglas.anotar(registro, CambioConducta.EVIDENCIA, request.user,
                                      ', '.join(archivo.name for archivo, _ in datos['evidencias']))
            except Exception:
                logger.exception('No se pudo guardar el registro de conducta %s', pk)
                messages.error(request, 'No se pudieron guardar las evidencias: no se guardó ningún cambio. Inténtalo de nuevo.')
            else:
                messages.success(request, f'Se guardaron los cambios del registro de {registro.alumno}.')
                _avisos_de_aprobacion(request, registro)
                return redirect('conducta:detalle', registro.pk)
        else:
            messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    else:
        form = RegistroForm(registro=registro, usuario=request.user)
    return render(request, 'conducta/form.html', _contexto_del_formulario(request, form, registro))


# ---------------------------------------------------------------------------
# Detalle
# ---------------------------------------------------------------------------
def puede_en(usuario, registro):
    """Lo que la persona puede hacer con el registro (para los botones; las vistas lo vuelven a comprobar)."""
    return {
        'corregir': P.puede_corregir(usuario, registro),
        'anular': P.puede_anular(usuario, registro),
        'seguimiento': P.puede_dar_seguimiento(usuario, registro),
        'aprobar': P.puede_aprobar(usuario, registro.nivel),   # la dirección de su nivel
        'ver_expediente': usuario.has_perm('Alumnos.view_alumno'),
        'ver_ficha': usuario.has_perm(P.PREF_CONSULTAR),
    }


@requiere_alguno(*P.CONSULTAR)
def detalle(request, pk):
    registro = _registro(request, pk)
    suspension = Suspension.objects.filter(registro=registro).select_related('autorizada_por', 'solicitada_por', 'resuelta_por').first()
    superpuestas = (
        reglas.suspensiones_superpuestas(registro.alumno, suspension.fecha_inicio, suspension.fecha_fin, excluir_registro=registro)
        if suspension and suspension.aprobacion in ('APROBADA', 'PENDIENTE') and not registro.anulado else []
    )
    medidas = list(registro.medidas_aplicadas.select_related('solicitada_por', 'resuelta_por'))
    return render(request, 'conducta/detalle.html', {
        'seccion': 'registros',
        'registro': registro,
        'suspension': suspension,
        'superpuestas': superpuestas,
        'medidas': [m for m in medidas if m.estado in MedidaAplicada.VIGENTES],
        'medidas_historicas': [m for m in medidas if m.estado not in MedidaAplicada.VIGENTES],
        'evidencias': list(registro.evidencias.filter(activa=True).select_related('subida_por')),
        'contactos': list(registro.contactos.select_related('registrado_por')),
        'citas': list(registro.citas.select_related('responsable', 'registrado_por')),
        'compromisos': list(registro.compromisos.select_related('responsable', 'resuelto_por')),
        'cambios': list(registro.cambios.select_related('usuario')),
        'aviso': AvisoReincidencia.objects.filter(registro=registro).select_related('revisado_por').first(),
        'aviso_form': RevisarAvisoForm(),
        'puede': puede_en(request.user, registro),
        'otros': (
            registros_de(request.user).filter(anulado=False, alumno=registro.alumno).exclude(pk=registro.pk)
            .order_by('-fecha', '-hora')[:5]
        ),
    })


# ---------------------------------------------------------------------------
# Seguimiento, anulación
# ---------------------------------------------------------------------------
@requiere_alguno(*SEGUIMIENTO)
def seguimiento(request, pk):
    registro = _registro(request, pk)
    if registro.anulado:
        messages.info(request, 'Ese registro está anulado: ya no se modifica.')
        return redirect('conducta:detalle', registro.pk)
    _exigir(P.puede_dar_seguimiento(request.user, registro))
    form = SeguimientoForm(request.POST if request.method == 'POST' else None, registro=registro)
    if request.method == 'POST':
        if form.is_valid():
            reglas.actualizar_seguimiento(registro, form.cleaned_data, request.user)
            messages.success(request, f'Se actualizó el seguimiento: {registro.get_estado_display().lower()}.')
            return redirect('conducta:detalle', registro.pk)
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return render(request, 'conducta/seguimiento.html', {'seccion': 'registros', 'registro': registro, 'form': form})


@requiere_alguno(P.ANULAR, P.PREF_CORREGIR, P.PREF_CORREGIR_OTROS)
def anular(request, pk):
    registro = _registro(request, pk)
    if registro.anulado:
        messages.info(request, 'Ese registro ya estaba anulado.')
        return redirect('conducta:detalle', registro.pk)
    _exigir(P.puede_anular(request.user, registro))
    form = AnularForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        if form.is_valid():
            reglas.anular(registro, form.cleaned_data['motivo'], request.user)
            messages.success(request, f'Se anuló el registro de {registro.alumno}. Se conserva para consulta y deja de contar en los indicadores.')
            return redirect('conducta:detalle', registro.pk)
        messages.error(request, 'Escribe el motivo de la anulación.')
    return render(request, 'conducta/anular.html', {'seccion': 'registros', 'registro': registro, 'form': form})


# ---------------------------------------------------------------------------
# Evidencias (protegidas: solo se entregan por aquí, con el permiso y el alcance del registro)
# ---------------------------------------------------------------------------
@requiere_alguno(*SEGUIMIENTO, *CORRECCION)
def evidencias_agregar(request, pk):
    registro = _registro(request, pk)
    if registro.anulado:
        messages.info(request, 'Ese registro está anulado: ya no se modifica.')
        return redirect('conducta:detalle', registro.pk)
    _exigir(P.puede_dar_seguimiento(request.user, registro) or P.puede_corregir(request.user, registro))
    errores = []
    if request.method == 'POST':
        archivos = request.FILES.getlist('evidencias')
        validos = []
        if not archivos:
            errores.append('Elige al menos un archivo.')
        elif len(archivos) > EVIDENCIAS_POR_ENVIO:
            errores.append(f'Adjunta como máximo {EVIDENCIAS_POR_ENVIO} archivos a la vez.')
        else:
            for archivo in archivos:
                try:
                    validos.append((archivo, validar_archivo(archivo)))
                except Exception as error:   # ValidationError con el mensaje para la persona
                    errores.extend(getattr(error, 'messages', [str(error)]))
        if not errores:
            try:
                with transaction.atomic():
                    _guardar_evidencias(registro, validos, request.user)
                    reglas.anotar(registro, CambioConducta.EVIDENCIA, request.user, ', '.join(a.name for a, _ in validos))
            except Exception:
                logger.exception('No se pudieron guardar las evidencias del registro %s', pk)
                errores.append('No se pudieron guardar los archivos. Inténtalo de nuevo.')
            else:
                messages.success(request, f'Se agregó {_plural(len(validos), "evidencia")}.')
                return redirect('conducta:detalle', registro.pk)
    return render(request, 'conducta/evidencias.html', {
        'seccion': 'registros', 'registro': registro, 'errores': errores, 'acepta': ACEPTA, 'maximo_mb': TAMANO_MAXIMO_MB,
        'por_envio': EVIDENCIAS_POR_ENVIO,
    })


def entregar_archivo(archivo, nombre, tipo, descargar=False):
    """Entrega un archivo guardado sin mostrar su dirección en el almacenamiento (privado, sin caché)."""
    try:
        abierto = archivo.open('rb')
    except Exception:
        logger.exception('No se pudo abrir el archivo %s', archivo.name)
        raise Http404('No se pudo obtener el archivo.') from None
    respuesta = FileResponse(abierto, content_type=tipo or 'application/octet-stream', as_attachment=descargar, filename=nombre)
    respuesta['X-Content-Type-Options'] = 'nosniff'
    respuesta['Cache-Control'] = 'private, no-store'
    return respuesta


@require_GET
@requiere_alguno(*P.CONSULTAR)
def evidencia(request, pk):
    evidencia = get_object_or_404(EvidenciaConducta, pk=pk, registro__in=registros_de(request.user).values('pk'))
    return entregar_archivo(evidencia.archivo, evidencia.nombre_original, evidencia.tipo, descargar=request.GET.get('descargar') == '1')


@require_POST
@requiere_alguno(*CORRECCION)
def evidencia_quitar(request, pk):
    evidencia = get_object_or_404(EvidenciaConducta.objects.select_related('registro'), pk=pk,
                                  registro__in=registros_de(request.user).values('pk'))
    registro = evidencia.registro
    if registro.anulado:
        messages.info(request, 'Ese registro está anulado: ya no se modifica.')
        return redirect('conducta:detalle', registro.pk)
    _exigir(P.puede_corregir(request.user, registro))
    if evidencia.activa:
        evidencia.activa, evidencia.quitada_por, evidencia.quitada_en = False, request.user, timezone.now()
        evidencia.save(update_fields=['activa', 'quitada_por', 'quitada_en'])
        reglas.anotar(registro, CambioConducta.EVIDENCIA_QUITADA, request.user, evidencia.nombre_original)
        messages.success(request, f'Se quitó «{evidencia.nombre_original}». Queda constancia en el historial.')
    return redirect('conducta:detalle', registro.pk)


# ---------------------------------------------------------------------------
# Contactos, citas y compromisos (solo se anotan: no se envía ningún mensaje)
# ---------------------------------------------------------------------------
def _registro_para_seguimiento(request, pk):
    registro = _registro(request, pk)
    if registro.anulado:
        return registro, redirect('conducta:detalle', registro.pk)
    _exigir(P.puede_dar_seguimiento(request.user, registro))
    return registro, None


@requiere_alguno(*SEGUIMIENTO)
def contacto_crear(request, pk):
    registro, salida = _registro_para_seguimiento(request, pk)
    if salida:
        messages.info(request, 'Ese registro está anulado: ya no se modifica.')
        return salida
    form = ContactoForm(request.POST if request.method == 'POST' else None, request.FILES or None, registro=registro)
    if request.method == 'POST':
        if form.is_valid():
            datos = form.cleaned_data
            contacto = ContactoTutor(
                registro=registro, fecha=datos['fecha'], tutor=datos['tutor_obj'], persona=datos['persona'], medio=datos['medio'],
                acuerdos=datos['acuerdos'], proxima_revision=datos['proxima_revision'], registrado_por=request.user,
            )
            if datos['evidencia']:
                archivo, tipo = datos['evidencia']
                contacto.evidencia, contacto.evidencia_nombre, contacto.evidencia_tipo = archivo, archivo.name[:200], tipo
            try:
                with transaction.atomic():
                    contacto.save()
                    reglas.anotar(registro, CambioConducta.CONTACTO, request.user,
                                  f'{contacto.get_medio_display()} con {contacto.persona}: {contacto.acuerdos}')
            except Exception:
                logger.exception('No se pudo guardar el contacto del registro %s', pk)
                messages.error(request, 'No se pudo guardar el contacto (ni su evidencia). Inténtalo de nuevo.')
            else:
                messages.success(request, f'Se anotó el contacto con {contacto.persona}. No se envió ningún mensaje.')
                return redirect('conducta:detalle', registro.pk)
        else:
            messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return render(request, 'conducta/contacto.html', {
        'seccion': 'registros', 'registro': registro, 'form': form, 'acepta': ACEPTA, 'maximo_mb': TAMANO_MAXIMO_MB,
    })


@require_GET
@requiere_alguno(*P.CONSULTAR)
def acuse(request, pk):
    contacto = get_object_or_404(ContactoTutor, pk=pk, registro__in=registros_de(request.user).values('pk'))
    if not contacto.evidencia:
        raise Http404('Ese contacto no tiene evidencia.')
    return entregar_archivo(contacto.evidencia, contacto.evidencia_nombre, contacto.evidencia_tipo, descargar=request.GET.get('descargar') == '1')


@requiere_alguno(*SEGUIMIENTO)
def cita_crear(request, pk):
    registro, salida = _registro_para_seguimiento(request, pk)
    if salida:
        return salida
    form = CitaForm(request.POST if request.method == 'POST' else None, registro=registro)
    if request.method == 'POST':
        if form.is_valid():
            cita = reglas.programar_cita(registro, form.cleaned_data, request.user)
            messages.success(request, f'Se programó la cita con {cita.persona} el {cita.fecha:%d/%m/%Y}. No se envió ningún aviso: avísale por el medio de siempre.')
            return redirect('conducta:detalle', registro.pk)
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return render(request, 'conducta/cita.html', {'seccion': 'registros', 'registro': registro, 'form': form})


@requiere_alguno(*SEGUIMIENTO)
def cita_actualizar(request, pk):
    cita = get_object_or_404(CitaTutor.objects.select_related('registro'), pk=pk, registro__in=registros_de(request.user).values('pk'))
    registro = cita.registro
    _exigir(not registro.anulado and P.puede_dar_seguimiento(request.user, registro))
    if not cita.abierta:
        messages.info(request, f'Esa cita ya está {cita.get_estado_display().lower()}.')
        return redirect('conducta:detalle', registro.pk)
    form = ActualizarCitaForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        if form.is_valid():
            reglas.actualizar_cita(cita, form.cleaned_data['estado'], form.cleaned_data['resultado'], request.user)
            messages.success(request, f'Cita con {cita.persona}: {cita.get_estado_display().lower()}.')
            return redirect('conducta:detalle', registro.pk)
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return render(request, 'conducta/cita_actualizar.html', {'seccion': 'registros', 'registro': registro, 'cita': cita, 'form': form})


@requiere_alguno(*SEGUIMIENTO)
def compromiso_crear(request, pk):
    registro, salida = _registro_para_seguimiento(request, pk)
    if salida:
        return salida
    form = CompromisoForm(request.POST if request.method == 'POST' else None, registro=registro)
    if request.method == 'POST':
        if form.is_valid():
            compromiso = reglas.agregar_compromiso(registro, form.cleaned_data, request.user)
            messages.success(request, f'Se anotó el compromiso, con fecha límite el {compromiso.fecha_limite:%d/%m/%Y}.')
            return redirect('conducta:detalle', registro.pk)
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return render(request, 'conducta/compromiso.html', {'seccion': 'registros', 'registro': registro, 'form': form})


@requiere_alguno(*SEGUIMIENTO)
def compromiso_resolver(request, pk):
    compromiso = get_object_or_404(Compromiso.objects.select_related('registro'), pk=pk, registro__in=registros_de(request.user).values('pk'))
    registro = compromiso.registro
    _exigir(not registro.anulado and P.puede_dar_seguimiento(request.user, registro))
    if not compromiso.abierto:
        messages.info(request, f'Ese compromiso ya está {compromiso.get_estado_display().lower()}.')
        return redirect('conducta:detalle', registro.pk)
    form = ResolverCompromisoForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        if form.is_valid():
            reglas.resolver_compromiso(compromiso, form.cleaned_data['estado'], form.cleaned_data['observaciones'], request.user)
            messages.success(request, f'Compromiso: {compromiso.get_estado_display().lower()}.')
            return redirect('conducta:detalle', registro.pk)
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return render(request, 'conducta/compromiso_resolver.html', {
        'seccion': 'registros', 'registro': registro, 'compromiso': compromiso, 'form': form,
    })


# ---------------------------------------------------------------------------
# Avisos de reincidencia y pendientes
# ---------------------------------------------------------------------------
@require_POST
@requiere_alguno(*SEGUIMIENTO)
def aviso_revisar(request, pk):
    aviso = get_object_or_404(AvisoReincidencia.objects.select_related('registro'), pk=pk,
                              registro__in=registros_de(request.user).values('pk'))
    _exigir(P.puede_dar_seguimiento(request.user, aviso.registro))
    form = RevisarAvisoForm(request.POST)
    if not aviso.revisado and form.is_valid():
        reglas.revisar_aviso(aviso, form.cleaned_data['nota'].strip(), request.user)
        messages.success(request, 'Se marcó el aviso como revisado.')
    return redirect(destino_seguro(request, reverse('conducta:detalle', args=[aviso.registro_id])))


@requiere_alguno(*P.CONSULTAR)
def pendientes(request):
    datos = reglas.pendientes(registros=registros_de(request.user))
    return render(request, 'conducta/pendientes.html', {
        'seccion': 'pendientes', **datos,
        'compromisos_total': len(datos['compromisos']),
        'solicitudes_total': len(datos['solicitudes_suspensiones']) + len(datos['solicitudes_medidas']),
        'pendientes_total': reglas.cuantos_pendientes(registros=registros_de(request.user)),
        'puede_revisar': request.user.has_perm(P.EDITAR) or request.user.has_perm(P.PREF_SEGUIMIENTO),
        **contexto_de_pestanas(request.user),
    })


# ---------------------------------------------------------------------------
# Solicitudes de aprobación: suspensiones y medidas
# ---------------------------------------------------------------------------
@requiere_alguno(P.APROBAR, *P.CONSULTAR)
def solicitudes(request):
    registros = registros_de(request.user)
    ids = registros.values('pk')
    vista = request.GET.get('vista', 'pendientes')
    if vista not in ('pendientes', 'resueltas'):
        vista = 'pendientes'
    resueltas_suspensiones = (
        Suspension.objects.filter(registro__in=ids, solicitada_por__isnull=False, resuelta_por__isnull=False)
        .exclude(aprobacion=PENDIENTE).exclude(resuelta_por=F('solicitada_por')).select_related('registro__alumno', 'solicitada_por', 'resuelta_por').order_by('-resuelta_en')[:50]
    )
    resueltas_medidas = (
        MedidaAplicada.objects.filter(registro__in=ids, solicitada_por__isnull=False, resuelta_por__isnull=False, implica_suspension=False)
        .exclude(estado=PENDIENTE).exclude(resuelta_por=F('solicitada_por')).select_related('registro__alumno', 'solicitada_por', 'resuelta_por').order_by('-resuelta_en')[:50]
    )
    pendientes = reglas.solicitudes_pendientes(registros)
    # Cada solicitud la resuelve la dirección del nivel del estudiante (nunca quien la pidió)
    for solicitud in (*pendientes['suspensiones'], *pendientes['medidas']):
        solicitud.de_mi_nivel = P.puede_aprobar(request.user, solicitud.registro.nivel)
        solicitud.resoluble = solicitud.de_mi_nivel and solicitud.solicitada_por_id != request.user.pk
        solicitud.nivel_nombre = reglas.NOMBRE_DE_NIVEL[solicitud.registro.nivel]
    return render(request, 'conducta/solicitudes.html', {
        'seccion': 'solicitudes',
        'vista': vista,
        **pendientes,
        'total_por_resolver': len(pendientes['suspensiones']) + len(pendientes['medidas']),
        'resueltas_suspensiones': list(resueltas_suspensiones),
        'resueltas_medidas': list(resueltas_medidas),
        'puede_aprobar': P.puede_aprobar(request.user),
        **contexto_de_pestanas(request.user),
    })


def _volver_a_solicitudes(request, registro):
    return redirect(destino_seguro(request, reverse('conducta:detalle', args=[registro.pk])))


@requiere_permisos(P.APROBAR)
def suspension_resolver(request, pk):
    suspension = get_object_or_404(Suspension.objects.select_related('registro__alumno', 'solicitada_por', 'motivo'), pk=pk,
                                   registro__in=registros_de(request.user).values('pk'))
    _exigir(P.puede_aprobar(request.user, suspension.registro.nivel))   # la autoriza la dirección de su nivel
    form = ResolverForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        if form.is_valid():
            try:
                reglas.resolver_suspension(suspension, form.cleaned_data['decision'] == 'aprobar', form.cleaned_data['observaciones'], request.user)
            except reglas.SolicitudRechazada as error:
                messages.error(request, str(error))
            else:
                aprobada = form.cleaned_data['decision'] == 'aprobar'
                messages.success(request, f'Se {"aprobó" if aprobada else "rechazó"} la suspensión de {suspension.registro.alumno}.'
                                          + (' Sus días se marcan con S en la asistencia y no cuentan como faltas.' if aprobada else ''))
            return _volver_a_solicitudes(request, suspension.registro)
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    propia = suspension.solicitada_por_id == request.user.pk
    return render(request, 'conducta/resolver.html', {
        'seccion': 'solicitudes', 'registro': suspension.registro, 'suspension': suspension, 'form': form, 'propia': propia,
        'accion': reverse('conducta:suspension_resolver', args=[suspension.pk]),
    })


@requiere_alguno(P.APROBAR, P.PREF_SOLICITAR, P.REGISTRAR, P.EDITAR)
def suspension_cancelar(request, pk):
    suspension = get_object_or_404(Suspension.objects.select_related('registro__alumno'), pk=pk,
                                   registro__in=registros_de(request.user).values('pk'))
    _exigir(suspension.solicitada_por_id == request.user.pk or P.puede_aprobar(request.user, suspension.registro.nivel))
    form = CancelarSolicitudForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        if form.is_valid():
            try:
                reglas.cancelar_suspension(suspension, form.cleaned_data['motivo'], request.user)
            except reglas.SolicitudRechazada as error:
                messages.error(request, str(error))
            else:
                messages.success(request, 'Se canceló la solicitud de suspensión. Queda en el historial.')
            return _volver_a_solicitudes(request, suspension.registro)
        messages.error(request, 'Escribe el motivo de la cancelación.')
    return render(request, 'conducta/cancelar_solicitud.html', {
        'seccion': 'solicitudes', 'registro': suspension.registro, 'suspension': suspension, 'form': form,
    })


@requiere_permisos(P.APROBAR)
def medida_resolver(request, pk):
    medida = get_object_or_404(MedidaAplicada.objects.select_related('registro__alumno', 'solicitada_por'), pk=pk,
                               registro__in=registros_de(request.user).values('pk'))
    _exigir(P.puede_aprobar(request.user, medida.registro.nivel))
    form = ResolverForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        if form.is_valid():
            try:
                reglas.resolver_medida(medida, form.cleaned_data['decision'] == 'aprobar', form.cleaned_data['observaciones'], request.user)
            except reglas.SolicitudRechazada as error:
                messages.error(request, str(error))
            else:
                messages.success(request, f'Se {"aprobó" if form.cleaned_data["decision"] == "aprobar" else "rechazó"} la medida «{medida.nombre}».')
            return _volver_a_solicitudes(request, medida.registro)
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return render(request, 'conducta/resolver.html', {
        'seccion': 'solicitudes', 'registro': medida.registro, 'medida': medida, 'form': form,
        'propia': medida.solicitada_por_id == request.user.pk,
        'accion': reverse('conducta:medida_resolver', args=[medida.pk]),
    })


# ---------------------------------------------------------------------------
# Para el formulario: buscar estudiantes y las opciones del nivel en una fecha (JSON)
# ---------------------------------------------------------------------------
@require_GET
@requiere_alguno(*P.ALTA, *P.CONSULTAR)
def buscar(request):
    """Estudiantes (del alcance de quien busca) por nombre, número de control (referencia) o CURP, con su grupo actual."""
    palabras = request.GET.get('q', '').split()
    if not palabras or sum(len(p) for p in palabras) < 2:
        return JsonResponse({'resultados': []})
    alumnos = alcance_de(request.user).alumnos(Alumno.objects.exclude(estatus='BAJA'))
    for palabra in palabras:
        alumnos = alumnos.filter(
            Q(nombre__icontains=palabra) | Q(apellido_paterno__icontains=palabra) | Q(apellido_materno__icontains=palabra)
            | Q(referencia__icontains=palabra) | Q(curp__icontains=palabra)
        )
    actuales = Prefetch(
        'inscripciones', to_attr='actuales',
        queryset=Inscripcion.objects.filter(activa=True, ciclo__activo=True).select_related('grupo__nombre', 'grupo__grado'),
    )
    resultados = []
    for alumno in alumnos.order_by('apellido_paterno', 'apellido_materno', 'nombre').prefetch_related(actuales)[:8]:
        inscripcion = alumno.actuales[0] if alumno.actuales else None
        resultados.append({
            'id': alumno.pk, 'nombre': str(alumno), 'iniciales': alumno.iniciales, 'referencia': alumno.referencia,
            'grado': str(inscripcion.grupo) if inscripcion else 'Sin inscripción en el ciclo actual',
            'estatus': alumno.get_estatus_display(),
        })
    return JsonResponse({'resultados': resultados})


@require_GET
@requiere_alguno(*P.ALTA, *CORRECCION)
def opciones(request):
    """El grupo del estudiante en la fecha del hecho (de su inscripción en ese ciclo) y las opciones de su nivel."""
    alumno_id, texto_fecha = request.GET.get('alumno', ''), request.GET.get('fecha', '')
    alumnos = alcance_de(request.user).alumnos()
    alumno = alumnos.filter(pk=alumno_id).first() if alumno_id.isdigit() else None
    fecha = RegistroForm._fecha_de(texto_fecha) or timezone.localdate()
    if alumno is None:
        return JsonResponse({'ok': False, 'mensaje': 'Elige un estudiante.'}, status=400)
    inscripcion = reglas.inscripcion_en(alumno, fecha)
    if inscripcion is None:
        ciclo = reglas.ciclo_de(fecha)
        mensaje = f'{alumno} no tenía inscripción en el ciclo {ciclo}.' if ciclo else 'Esa fecha queda fuera de cualquier ciclo escolar.'
        return JsonResponse({'ok': False, 'mensaje': mensaje})
    contexto = reglas.contexto_escolar(inscripcion, fecha)
    periodo = contexto['periodo']
    return JsonResponse({
        'ok': True,
        'contexto': {
            'ciclo': str(contexto['ciclo']), 'nivel': contexto['nivel'], 'nivel_nombre': reglas.NOMBRE_DE_NIVEL[contexto['nivel']],
            'grado': str(contexto['grado']), 'grupo': contexto['grupo_texto'],
            'periodo': f'{periodo.nombre} ({periodo.fecha_inicio:%d/%m/%Y} al {periodo.fecha_fin:%d/%m/%Y})' if periodo else 'Sin periodo de evaluación en esa fecha',
        },
        'opciones': reglas.opciones_del_nivel(contexto['nivel'], solo_prefectura=P.solo_medidas_de_prefectura(request.user)),
    })
