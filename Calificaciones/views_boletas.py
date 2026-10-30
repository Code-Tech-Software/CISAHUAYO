"""Boletas e historial académico (kárdex) listos para imprimir o guardar en PDF, y Ajustes › Boletas (pedido del
2026-10-29).

La boleta junta las materias de todos los docentes del grupo: la abren quienes ven todas las calificaciones («ver o
gestionar todas»). No hay acceso desde el portal (decisión del 2026-10-29). Los números salen de Calificaciones/boletas.py.
"""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from Alumnos.academico import ciclo_actual
from Alumnos.models import ORDEN_NIVELES, Alumno, CicloEscolar, Grado, Grupo
from CISAHUAYO.permisos import requiere_alguno, requiere_permisos
from Conducta.permisos import puede_configurar
from Usuarios.seguridad import ACCION_CAMBIO, registrar

from . import boletas, reglas
from .forms import DatosOficialesForm
from .models import DatosOficialesNivel

VER_DATOS, CAMBIAR_DATOS = 'Calificaciones.view_datosoficialesnivel', 'Calificaciones.change_datosoficialesnivel'


def _quien(usuario):
    return usuario.get_full_name() or usuario.get_username()


def _hoja(request, lista, titulo, volver):
    """Todas las boletas en una sola hoja (cada una en su página al imprimir)."""
    semestral = any(b.semestral for b in lista)
    return render(request, 'calificaciones/boletas_hoja.html', {
        'boletas': lista, 'titulo': titulo, 'volver': volver, 'horizontal': semestral,
        'imprimir_al_abrir': request.GET.get('pdf') == '1', 'generado': timezone.localtime(), 'usuario': _quien(request.user),
    })


@requiere_alguno(reglas.VER_TODAS, reglas.GESTIONAR_TODAS)
def boleta_estudiante(request, pk):
    """La boleta del estudiante en un ciclo (?ciclo=; si no, el actual o el más reciente en que estuvo inscrito)."""
    alumno = get_object_or_404(Alumno, pk=pk)
    ciclos = boletas.ciclos_con_inscripcion(alumno)
    if not ciclos:
        messages.info(request, f'{alumno} no tiene inscripciones: todavía no hay boleta que imprimir.')
        return redirect(alumno)
    actual = ciclo_actual()
    ciclo = (next((c for c in ciclos if str(c.pk) == request.GET.get('ciclo', '')), None)
             or (actual if actual in ciclos else ciclos[0]))
    return _hoja(request, [boletas.boleta(alumno, ciclo)], f'Boleta · {alumno} · {ciclo}', f'{alumno.get_absolute_url()}#academico')


@requiere_alguno(reglas.VER_TODAS, reglas.GESTIONAR_TODAS)
def boletas_grupo(request, pk):
    """Las boletas de todo el grupo en el ciclo (?ciclo=; si no, el actual), una por página."""
    grupo = get_object_or_404(Grupo.objects.select_related('grado', 'nombre'), pk=pk)
    pedido = request.GET.get('ciclo', '')
    ciclo = (CicloEscolar.objects.filter(pk=pedido).first() if pedido.isdigit() else None) or ciclo_actual()
    if ciclo is None:
        messages.error(request, 'No hay un ciclo escolar actual.')
        return redirect('calificaciones:inicio')
    lista = boletas.boletas_del_grupo(grupo, ciclo)
    volver = f"{reverse('calificaciones:inicio')}?{urlencode({'ciclo': ciclo.pk, 'grupo': grupo.pk})}"
    if not lista:
        messages.info(request, f'{grupo} no tiene estudiantes inscritos en el ciclo {ciclo}.')
        return redirect(volver)
    return _hoja(request, lista, f'Boletas · {grupo} · {ciclo}', volver)


@requiere_alguno(reglas.VER_TODAS, reglas.GESTIONAR_TODAS)
def kardex(request, pk):
    """El historial académico del estudiante: todos sus ciclos y un resumen por nivel."""
    alumno = get_object_or_404(Alumno, pk=pk)
    return render(request, 'calificaciones/kardex_hoja.html', {
        'k': boletas.kardex(alumno), 'alumno': alumno, 'volver': f'{alumno.get_absolute_url()}#academico',
        'imprimir_al_abrir': request.GET.get('pdf') == '1', 'generado': timezone.localtime(), 'usuario': _quien(request.user),
    })


# ---------------------------------------------------------------------------
# Ajustes › Boletas: datos oficiales de cada nivel
# ---------------------------------------------------------------------------
@requiere_permisos(VER_DATOS)
def datos_oficiales(request):
    puede_cambiar = request.user.has_perm(CAMBIAR_DATOS)
    if request.method == 'POST' and not puede_cambiar:
        raise PermissionDenied
    actuales = {d.nivel: d for d in DatosOficialesNivel.objects.all()}
    nombres = dict(Grado.NIVEL_CHOICES)
    datos = request.POST if request.method == 'POST' else None
    formularios = [
        (nivel, nombres[nivel], DatosOficialesForm(datos, instance=actuales.get(nivel) or DatosOficialesNivel(nivel=nivel), prefix=nivel.lower()))
        for nivel in ORDEN_NIVELES
    ]
    if datos is not None:
        if all(form.is_valid() for _, _, form in formularios):
            with transaction.atomic():
                for nivel, nombre, form in formularios:
                    if not form.has_changed():
                        continue
                    registro = form.save(commit=False)
                    registro.modificado_por = request.user
                    registro.save()
                    registrar(request.user, registro, ACCION_CAMBIO,
                              f'Datos oficiales de {nombre}: CCT {registro.cct or "—"}, {registro.director or "sin nombre"} ({registro.cargo_o_predeterminado}).')
            messages.success(request, 'Se guardaron los datos oficiales de las boletas.')
            return redirect('calificaciones:datos_oficiales')
        messages.error(request, 'Revisa los campos marcados: hay datos por corregir.')
    return render(request, 'calificaciones/configuracion/datos_oficiales.html', {
        'formularios': formularios, 'puede_cambiar': puede_cambiar,
        'ajustes_seccion': 'boletas', 'puede_configurar_conducta': puede_configurar(request.user),
    })
