"""Acciones sobre varios estudiantes a la vez, desde la tabla (pedido del 2026-10-28): inscribirlos o cambiarlos de grupo,
cambiar su estatus, generar sus contraseñas del portal, exportarlos y mandar un comunicado a sus tutores.

Cada una aplica las mismas reglas que la acción de un solo estudiante (Alumnos/views.py e Inscripciones) y devuelve lo
que hizo y lo que no pudo hacer (con el porqué); cada cambio queda en el historial de cada estudiante.
"""
from django.db import transaction
from django.utils import timezone

from . import historial
from .academico import motivo_no_inscribible, sincronizar_inscripciones
from .models import Alumno, Inscripcion, TutorAlumno
from .utils import generar_contrasena

MAXIMO = 500   # estudiantes por acción (una página de la tabla tiene como máximo 100)


def _texto_de_grupo(grado, grupo):
    return grupo.nombre_equivalente if grupo is not None else grado.nombre_equivalente


@transaction.atomic
def inscribir_o_cambiar(alumnos, *, ciclo, grado, grupo, usuario):
    """Los inscribe en ese grado y grupo del ciclo o, si ya están inscritos en él, los cambia de grupo (o de grado).
    Devuelve (hechos, omitidos): listas de textos."""
    hechos, omitidos = [], []
    destino = f'{_texto_de_grupo(grado, grupo)} ({ciclo})'
    for alumno in alumnos:
        motivo = motivo_no_inscribible(alumno)
        if motivo:
            omitidos.append(motivo)
            continue
        actual = Inscripcion.objects.filter(alumno=alumno, ciclo=ciclo).select_related('grado', 'grupo__nombre', 'grupo__grado').first()
        if actual is None:
            Inscripcion.objects.create(alumno=alumno, ciclo=ciclo, grado=grado, grupo=grupo, fecha_inscripcion=timezone.localdate())
            historial.anotar(usuario, alumno, f'Lo inscribió en {destino} (acción en lote).')
            hechos.append(f'{alumno}: inscrito en {destino}')
        elif not actual.activa:
            omitidos.append(f'{alumno} tiene una inscripción dada de baja en {ciclo}: reactívala en Inscripciones.')
        elif actual.grado_id == grado.pk and actual.grupo_id == grupo.pk:
            omitidos.append(f'{alumno} ya estaba en {destino}.')
        else:
            antes = _texto_de_grupo(actual.grado, actual.grupo)
            actual.grado, actual.grupo = grado, grupo
            actual.save(update_fields=['grado', 'grupo'])
            historial.anotar(usuario, alumno, f'Lo cambió de {antes} a {destino} (acción en lote).')
            hechos.append(f'{alumno}: de {antes} a {_texto_de_grupo(grado, grupo)}')
    return hechos, omitidos


@transaction.atomic
def cambiar_estatus(alumnos, *, estatus, usuario):
    """Como «Cambiar estatus» del expediente (la baja tiene su propia acción): sus inscripciones vigentes se suspenden o
    se restauran si entran o salen de la baja. Devuelve (cambiados, sin_cambio)."""
    nombre = dict(Alumno.ESTATUS_CHOICES)[estatus]
    cambiados, sin_cambio = [], []
    for alumno in alumnos:
        if alumno.estatus == estatus:
            sin_cambio.append(str(alumno))
            continue
        anterior = alumno.get_estatus_display()
        estatus_anterior = alumno.estatus
        alumno.estatus = estatus
        alumno.save(update_fields=['estatus'])
        sincronizar_inscripciones(alumno, estatus_anterior)
        historial.anotar(usuario, alumno, f'Cambió su estatus de «{anterior}» a «{nombre}» (acción en lote).')
        cambiados.append(str(alumno))
    return cambiados, sin_cambio


@transaction.atomic
def generar_contrasenas(alumnos, *, usuario):
    """Una contraseña nueva para cada uno (la anterior deja de servir). Devuelve las filas para descargarlas:
    [referencia, nombre, grado, correo (con lo que entra), contraseña]."""
    filas = []
    for alumno in alumnos:
        nueva = generar_contrasena()
        alumno.establecer_contrasena(nueva)
        alumno.save(update_fields=['contrasena', 'contrasena_visible', 'intentos_fallidos', 'bloqueado_hasta'])
        historial.anotar(usuario, alumno, 'Le generó una contraseña nueva para el portal (acción en lote).')
        inscripcion = (getattr(alumno, 'inscripciones_actuales', None) or [None])[0]
        grado = _texto_de_grupo(inscripcion.grado, inscripcion.grupo) if inscripcion else ''
        filas.append([alumno.referencia, str(alumno), grado, alumno.correo_electronico or 'Sin correo: regístralo para que pueda entrar', nueva])
    return filas


def tutores_de(alumnos):
    """Los ids de los tutores vigentes de esos estudiantes (vínculo activo), para el comunicado."""
    return sorted(set(TutorAlumno.objects.filter(alumno__in=[a.pk for a in alumnos], activo=True, tutor__estatus='ACTIVO')
                      .values_list('tutor_id', flat=True)))
