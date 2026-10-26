"""Semanas A y B: la modalidad de horario de cada nivel en un ciclo y las excepciones de semana (pedido del 2026-10-26).

Solo preescolar y primaria pueden alternar; los demás niveles siguen con horario fijo. Cada cambio queda anotado (quién,
cuándo y qué) en la bitácora de cambios del sistema. Antes de guardar una excepción se ve cómo quedarían las semanas
siguientes.
"""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from Alumnos.academico import ciclo_editable
from Alumnos.models import ConfiguracionHorario, ExcepcionSemana, Grado
from Alumnos.semanas import Calendario, lunes_de
from CISAHUAYO.permisos import requiere_permisos
from Usuarios.seguridad import ACCION_ALTA, ACCION_BAJA, ACCION_CAMBIO, registrar

from . import cambios
from .forms import ConfiguracionHorarioForm, ExcepcionSemanaForm
from .views import _ciclo_de, fecha_en_ciclo

SEMANAS_DE_VISTA_PREVIA = 10
NOMBRES = dict(Grado.NIVEL_CHOICES)


def _url(ciclo, nivel=''):
    url = f"{reverse('horarios:semanas')}?ciclo={ciclo.pk}"
    return f'{url}#nivel-{nivel.lower()}' if nivel else url


def _puede_editar(request, ciclo):
    return ciclo_editable(ciclo) and request.user.has_perm('Alumnos.change_horariomateria')


def _texto(configuracion):
    if not configuracion.alternado:
        return 'horario fijo'
    return (f'semanas A y B; la semana del {lunes_de(configuracion.fecha_referencia):%d/%m/%Y} es la '
            f'{configuracion.semana_referencia}')


def _niveles(request, ciclo, calendario, formularios=None, excepcion=None, vista_previa=None):
    """Una tarjeta por nivel: su modalidad (con el formulario si se puede cambiar), las próximas semanas y sus
    excepciones."""
    formularios = formularios or {}
    hoy = fecha_en_ciclo(None, ciclo)
    niveles = []
    for nivel, nombre in Grado.NIVEL_CHOICES:
        configuracion = calendario.configuracion(nivel)
        alternable = nivel in ConfiguracionHorario.NIVELES_ALTERNABLES
        tarjeta = {
            'nivel': nivel, 'nombre': nombre, 'alternable': alternable, 'configuracion': configuracion,
            'alternado': calendario.alternado(nivel),
        }
        if alternable:
            tarjeta['form'] = formularios.get(nivel) or ConfiguracionHorarioForm(
                prefix=nivel.lower(), ciclo=ciclo, instance=configuracion or ConfiguracionHorario(ciclo=ciclo, nivel=nivel),
            )
        if tarjeta['alternado']:
            tarjeta['proximas'] = calendario.siguientes(hoy, nivel, 6)
            tarjeta['hoy'] = calendario.info(hoy, nivel)
            tarjeta['excepciones'] = list(configuracion.excepciones.select_related('creado_por').order_by('lunes'))
            tarjeta['excepcion_form'] = (excepcion if excepcion is not None and excepcion.nivel == nivel
                                         else ExcepcionSemanaForm(prefix=f'excepcion-{nivel.lower()}', ciclo=ciclo))
            tarjeta['vista_previa'] = vista_previa if vista_previa and vista_previa['nivel'] == nivel else None
        niveles.append(tarjeta)
    return niveles


def _pantalla(request, ciclos, ciclo, **extra):
    calendario = Calendario(ciclo)
    return render(request, 'horarios/semanas.html', {
        'ciclos': ciclos, 'ciclo': ciclo, 'editable': _puede_editar(request, ciclo) if ciclo else False,
        'niveles': _niveles(request, ciclo, calendario, **extra) if ciclo else [],
    })


@requiere_permisos('Alumnos.view_horariomateria')
def semanas(request):
    ciclos, ciclo = _ciclo_de(request)
    return _pantalla(request, ciclos, ciclo)


@require_POST
@requiere_permisos('Alumnos.change_horariomateria')
def modalidad(request):
    """Guarda la modalidad de un nivel. Al activar las semanas A y B, el horario fijo pasa a ser la semana A y se copia
    a la B; al volver al horario fijo, la semana A queda para todas las semanas y la B se quita."""
    ciclos, ciclo = _ciclo_de(request)
    nivel = request.POST.get('nivel', '')
    if ciclo is None or nivel not in ConfiguracionHorario.NIVELES_ALTERNABLES:
        messages.error(request, 'Solo preescolar y primaria pueden tener semanas A y B.')
        return redirect('horarios:semanas')
    if not ciclo_editable(ciclo):
        raise PermissionDenied('El ciclo está cerrado.')
    anterior = ConfiguracionHorario.objects.filter(ciclo=ciclo, nivel=nivel).first()
    estaba_alternado = bool(anterior and anterior.alternado)
    texto_anterior = _texto(anterior) if anterior else 'horario fijo'
    form = ConfiguracionHorarioForm(request.POST, prefix=nivel.lower(), ciclo=ciclo,
                                    instance=anterior or ConfiguracionHorario(ciclo=ciclo, nivel=nivel))
    if not form.is_valid():
        messages.error(request, f'Revisa la configuración de {NOMBRES[nivel].lower()}: hay datos por corregir.')
        return _pantalla(request, ciclos, ciclo, formularios={nivel: form})

    with transaction.atomic():
        configuracion = form.save(commit=False)
        if configuracion.modalidad == ConfiguracionHorario.FIJO:
            configuracion.fecha_referencia = configuracion.fecha_referencia if estaba_alternado else None
        configuracion.modificado_por = request.user
        configuracion.save()
        aviso = ''
        if configuracion.alternado and not estaba_alternado:
            copiados = cambios.activar_alternancia(ciclo, nivel)
            aviso = (f' El horario que tenía cada grupo quedó como semana A y se copió igual a la B ({copiados} bloques): '
                     'ajusta en cada grupo lo que cambie.') if copiados else ' Arma la semana A y la B de cada grupo.'
        elif estaba_alternado and not configuracion.alternado:
            quitados = cambios.quitar_alternancia(ciclo, nivel, desde=cambios.vigencia_inicial(ciclo))
            aviso = f' La semana A quedó como el horario de todas las semanas y se quitaron {quitados} bloques de la semana B.'
        registrar(request.user, configuracion, ACCION_ALTA if anterior is None else ACCION_CAMBIO,
                  f'Horario de {NOMBRES[nivel].lower()} en el ciclo {ciclo}: antes {texto_anterior}; ahora {_texto(configuracion)}.')
    messages.success(request, f'Se guardó el horario de {NOMBRES[nivel].lower()}: {_texto(configuracion)}.{aviso}')
    return redirect(_url(ciclo, nivel))


@require_POST
@requiere_permisos('Alumnos.change_horariomateria')
def excepcion(request):
    """Una excepción de semana. «Ver vista previa» muestra cómo quedan las semanas siguientes sin guardar nada; «Guardar
    excepción» la guarda (si esa semana ya tenía una, la reemplaza)."""
    ciclos, ciclo = _ciclo_de(request)
    nivel = request.POST.get('nivel', '')
    configuracion = ConfiguracionHorario.objects.filter(ciclo=ciclo, nivel=nivel).first() if ciclo else None
    if configuracion is None or not configuracion.alternado:
        messages.error(request, 'Ese nivel no tiene semanas A y B en este ciclo.')
        return redirect(_url(ciclo) if ciclo else 'horarios:semanas')
    if not ciclo_editable(ciclo):
        raise PermissionDenied('El ciclo está cerrado.')
    form = ExcepcionSemanaForm(request.POST, prefix=f'excepcion-{nivel.lower()}', ciclo=ciclo)
    form.nivel = nivel
    if not form.is_valid():
        messages.error(request, 'Revisa la excepción: hay datos por corregir.')
        return _pantalla(request, ciclos, ciclo, excepcion=form)

    lunes = lunes_de(form.cleaned_data['fecha'])
    semana, tipo, motivo = form.cleaned_data['semana'], form.cleaned_data['tipo'], form.cleaned_data['motivo']
    if 'guardar' not in request.POST:
        antes = Calendario(ciclo)
        despues = Calendario(ciclo, extra=(nivel, lunes, semana, tipo))
        semanas = [
            {'antes': antes.info(dia, nivel), 'despues': despues.info(dia, nivel)}
            for dia in [s.lunes for s in antes.siguientes(lunes, nivel, SEMANAS_DE_VISTA_PREVIA)]
        ]
        for fila in semanas:
            fila['cambia'] = fila['antes'].tipo != fila['despues'].tipo
        vista_previa = {'nivel': nivel, 'semanas': semanas, 'lunes': lunes, 'cambios': sum(f['cambia'] for f in semanas)}
        return _pantalla(request, ciclos, ciclo, excepcion=form, vista_previa=vista_previa)

    with transaction.atomic():
        existente = ExcepcionSemana.objects.filter(configuracion=configuracion, lunes=lunes).first()
        ExcepcionSemana.objects.update_or_create(
            configuracion=configuracion, lunes=lunes,
            defaults={'semana': semana, 'tipo': tipo, 'motivo': motivo, 'creado_por': request.user},
        )
        tipo_texto = dict(ExcepcionSemana.TIPO_CHOICES)[tipo].lower()
        registrar(request.user, configuracion, ACCION_CAMBIO,
                  f'Excepción en {NOMBRES[nivel].lower()} ({ciclo}): la semana del {lunes:%d/%m/%Y} es la {semana} ({tipo_texto})'
                  + (f'; reemplaza a la anterior ({existente.semana}, {existente.get_tipo_display().lower()})' if existente else '')
                  + (f'. Motivo: {motivo}' if motivo else '') + '.')
    messages.success(request, f'Se guardó la excepción: la semana del {lunes:%d/%m/%Y} es la {semana} ({tipo_texto}).')
    return redirect(_url(ciclo, nivel))


@require_POST
@requiere_permisos('Alumnos.change_horariomateria')
def excepcion_eliminar(request, pk):
    excepcion = get_object_or_404(ExcepcionSemana.objects.select_related('configuracion__ciclo'), pk=pk)
    configuracion = excepcion.configuracion
    if not ciclo_editable(configuracion.ciclo):
        raise PermissionDenied('El ciclo está cerrado.')
    texto = f'la semana del {excepcion.lunes:%d/%m/%Y} ({excepcion.semana}, {excepcion.get_tipo_display().lower()})'
    with transaction.atomic():
        excepcion.delete()
        registrar(request.user, configuracion, ACCION_BAJA,
                  f'Se quitó la excepción de {NOMBRES[configuracion.nivel].lower()} ({configuracion.ciclo}): {texto}.')
    messages.success(request, f'Se quitó la excepción de {texto}; esa semana vuelve a seguir la alternancia.')
    return redirect(_url(configuracion.ciclo, configuracion.nivel))


