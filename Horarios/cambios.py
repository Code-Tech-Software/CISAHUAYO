"""Cambios del horario con fecha de entrada en vigor (pedido del 2026-10-26).

Un cambio «desde una fecha» no reescribe el pasado: el bloque anterior se cierra el día previo (`vigente_hasta`) y el
nuevo empieza ese día (`vigente_desde`), así el horario de cualquier fecha anterior se sigue consultando como era. Sin
fecha (o con una que no deja nada atrás) es una corrección: el bloque se cambia o se borra tal cual, salvo que ya lo
use una bitácora; entonces también se conserva, para no alterar lo que ya se registró.
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from Alumnos.models import HorarioMateria


def vigencia_inicial(ciclo, hoy=None):
    """Lo que el formulario propone: hoy si el ciclo ya empezó (y no ha terminado); si no, vacío (todo el ciclo)."""
    hoy = hoy or timezone.localdate()
    return hoy if ciclo and ciclo.fecha_inicio < hoy <= ciclo.fecha_fin else None


def normalizar(fecha, ciclo):
    """None si la fecha no deja nada atrás dentro del ciclo (vacía o en su primer día o antes)."""
    if fecha is None or ciclo is None or fecha <= ciclo.fecha_inicio:
        return None
    return fecha


def _inicio(bloque):
    return bloque.vigente_desde or bloque.materia_grado.ciclo.fecha_inicio


def usado(bloque):
    """Si alguna bitácora ya registró una clase en este bloque."""
    from Bitacoras.models import EntradaBitacora
    return EntradaBitacora.objects.filter(bloque=bloque).exists()


def _desde_para(bloque, desde):
    """La fecha desde la que cambia un bloque ya usado: la pedida o, si no hay, hoy (dentro del ciclo)."""
    ciclo = bloque.materia_grado.ciclo
    fecha = desde or timezone.localdate()
    return min(max(fecha, ciclo.fecha_inicio), ciclo.fecha_fin)


@transaction.atomic
def crear(asignacion, dia, inicio, fin, semana='', desde=None):
    return HorarioMateria.objects.create(
        materia_grado=asignacion, dia_semana=dia, hora_inicio=inicio, hora_fin=fin, semana=semana,
        vigente_desde=normalizar(desde, asignacion.ciclo),
    )


@transaction.atomic
def retirar(bloque, desde=None):
    """Quita el bloque del horario desde esa fecha. Devuelve True si se borró y False si se conservó cerrado."""
    desde = normalizar(desde, bloque.materia_grado.ciclo)
    if (desde is None or desde <= _inicio(bloque)) and not usado(bloque):
        bloque.delete()
        return True
    desde = desde or _desde_para(bloque, None)
    bloque.vigente_hasta = desde - timedelta(days=1)
    bloque.save(update_fields=['vigente_hasta'])
    return False


@transaction.atomic
def cambiar(bloque, desde=None, **valores):
    """Aplica los valores nuevos (materia_grado, dia_semana, hora_inicio, hora_fin, semana) desde esa fecha. Devuelve el
    bloque vigente con los cambios (el mismo, corregido, o uno nuevo si el anterior se conservó)."""
    actual = HorarioMateria.objects.select_related('materia_grado__ciclo').get(pk=bloque.pk)   # tal como está guardado
    desde = normalizar(desde, actual.materia_grado.ciclo)
    if (desde is None or desde <= _inicio(actual)) and not usado(actual):
        for campo, valor in valores.items():
            setattr(actual, campo, valor)
        actual.save()
        return actual
    desde = desde or _desde_para(actual, None)
    actual.vigente_hasta = desde - timedelta(days=1)
    actual.save(update_fields=['vigente_hasta'])
    datos = {campo: getattr(actual, campo) for campo in ('materia_grado', 'dia_semana', 'hora_inicio', 'hora_fin', 'semana')}
    datos.update(valores)
    return HorarioMateria.objects.create(**datos, vigente_desde=desde)


# ---------------------------------------------------------------------------
# Activar o quitar las semanas A y B de un nivel
# ---------------------------------------------------------------------------
@transaction.atomic
def activar_alternancia(ciclo, nivel):
    """El horario fijo del nivel pasa a ser la semana A y se copia igual a la B (con sus versiones), así nada deja de
    tener clases al activar la modalidad; después se ajusta lo que cambie en cada semana. Devuelve cuántos bloques se
    copiaron."""
    fijos = list(HorarioMateria.historial.filter(materia_grado__ciclo=ciclo, materia_grado__grado__nivel=nivel, semana=HorarioMateria.TODAS))
    HorarioMateria.historial.bulk_create([
        HorarioMateria(materia_grado_id=b.materia_grado_id, dia_semana=b.dia_semana, hora_inicio=b.hora_inicio, hora_fin=b.hora_fin,
                       semana=HorarioMateria.SEMANA_B, vigente_desde=b.vigente_desde, vigente_hasta=b.vigente_hasta)
        for b in fijos
    ])
    HorarioMateria.historial.filter(pk__in=[b.pk for b in fijos]).update(semana=HorarioMateria.SEMANA_A)
    return len([b for b in fijos if b.vigente_hasta is None])


@transaction.atomic
def quitar_alternancia(ciclo, nivel, desde=None):
    """De vuelta al horario fijo: la semana A queda como el horario de todas las semanas y los bloques de la B se quitan
    (los que ya usó una bitácora se conservan cerrados). Devuelve cuántos bloques de la B se quitaron."""
    del_nivel = HorarioMateria.historial.filter(materia_grado__ciclo=ciclo, materia_grado__grado__nivel=nivel)
    de_b = list(del_nivel.filter(semana=HorarioMateria.SEMANA_B, vigente_hasta__isnull=True).select_related('materia_grado__ciclo'))
    for bloque in de_b:
        retirar(bloque, desde)
    del_nivel.filter(semana=HorarioMateria.SEMANA_A).update(semana=HorarioMateria.TODAS)
    return len(de_b)
