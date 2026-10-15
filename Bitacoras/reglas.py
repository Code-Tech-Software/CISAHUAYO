"""Registrar, editar y anular entradas de bitácora, con su historial.

Nada de aquí escribe fuera de las tablas de la bitácora: ni calificaciones, ni conducta, ni asistencia, ni sanciones.
"""
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from Alumnos.models import Alumno, Inscripcion, Periodo

from .models import CambioBitacora, EntradaBitacora, EstudianteBitacora


def nombre_de(usuario):
    return (usuario.get_full_name() or usuario.get_username()) if usuario else ''


def periodo_de(nivel, ciclo, fecha):
    """El periodo de evaluación del nivel que contiene esa fecha (o None)."""
    return Periodo.objects.filter(ciclo=ciclo, nivel=nivel, fecha_inicio__lte=fecha, fecha_fin__gte=fecha).order_by('fecha_inicio').first()


def inscripciones_del_grupo(grupo, ciclo):
    """Las inscripciones vigentes del grupo en el ciclo: los estudiantes que se pueden elegir."""
    return (Inscripcion.objects.filter(grupo=grupo, ciclo=ciclo, activa=True)
            .select_related('alumno').order_by('alumno__apellido_paterno', 'alumno__apellido_materno', 'alumno__nombre'))


def alumnos_elegibles(grupo, ciclo, entrada=None):
    """Los estudiantes del grupo (y, al editar, los que ya estaban en la entrada aunque hayan cambiado de grupo)."""
    condicion = Q(inscripciones__grupo=grupo, inscripciones__ciclo=ciclo, inscripciones__activa=True)
    if entrada is not None:
        condicion |= Q(vinculos_bitacora__entrada=entrada)
    return Alumno.objects.filter(condicion).distinct().order_by('apellido_paterno', 'apellido_materno', 'nombre')


def _texto_de_alumnos(alumnos):
    return ', '.join(sorted(str(a) for a in alumnos)) or '—'


def _foto(entrada, alumnos):
    """Lo que se compara entre versiones (texto legible para el historial)."""
    horario = f'{entrada.hora_inicio:%H:%M}–{entrada.hora_fin:%H:%M}' if entrada.hora_inicio and entrada.hora_fin else '—'
    return {
        'Materia': entrada.materia_nombre,
        'Fecha de la clase': f'{entrada.fecha:%d/%m/%Y}',
        'Bloque': horario,
        'Tipo': 'Observación general del grupo' if entrada.general else 'Estudiantes implicados',
        'Estudiantes': '—' if entrada.general else _texto_de_alumnos(alumnos),
        'Título': entrada.titulo,
        'Descripción': entrada.descripcion,
        'Acuerdos o seguimiento': entrada.seguimiento or '—',
    }


def _aplicar(entrada, datos):
    asignacion, fecha, bloque = datos['asignacion'], datos['fecha'], datos.get('bloque')
    grupo = asignacion.grupo
    entrada.ciclo, entrada.nivel, entrada.grado, entrada.grupo = asignacion.ciclo, grupo.grado.nivel, grupo.grado, grupo
    entrada.grupo_texto = str(grupo)
    entrada.asignacion, entrada.materia, entrada.materia_nombre = asignacion, asignacion.materia, asignacion.materia.nombre
    entrada.fecha = fecha
    entrada.periodo = periodo_de(grupo.grado.nivel, asignacion.ciclo, fecha)
    entrada.bloque = bloque
    entrada.hora_inicio, entrada.hora_fin = (bloque.hora_inicio, bloque.hora_fin) if bloque else (None, None)
    entrada.general = datos['general']
    entrada.titulo = datos['titulo']
    entrada.descripcion = datos['descripcion']
    entrada.seguimiento = datos.get('seguimiento') or ''


def _vincular(entrada, alumnos):
    """Deja la entrada vinculada exactamente con esos estudiantes (una fila por estudiante, sin duplicar)."""
    alumnos = [] if entrada.general else list(alumnos)
    entrada.vinculos.exclude(alumno__in=alumnos).delete()
    existentes = set(entrada.vinculos.values_list('alumno_id', flat=True))
    inscripciones = {i.alumno_id: i for i in Inscripcion.objects.filter(alumno__in=alumnos, ciclo=entrada.ciclo, grupo=entrada.grupo)}
    EstudianteBitacora.objects.bulk_create([
        EstudianteBitacora(entrada=entrada, alumno=alumno, inscripcion=inscripciones.get(alumno.pk))
        for alumno in alumnos if alumno.pk not in existentes
    ])


def crear(datos, usuario, clave_envio=None):
    """Guarda la entrada una sola vez. Devuelve (entrada, nueva): si ese mismo formulario ya se había guardado (doble
    envío), la que ya existía y False."""
    if clave_envio:
        existente = EntradaBitacora.objects.filter(clave_envio=clave_envio).first()
        if existente is not None:
            return existente, False
    entrada = EntradaBitacora(autor=usuario, autor_nombre=nombre_de(usuario), clave_envio=clave_envio)
    _aplicar(entrada, datos)
    try:
        with transaction.atomic():
            entrada.save()
            _vincular(entrada, datos['alumnos'])
            CambioBitacora.objects.create(
                entrada=entrada, accion=CambioBitacora.CREACION, usuario=usuario, usuario_nombre=nombre_de(usuario),
                cambios=[[que, '', valor] for que, valor in _foto(entrada, datos['alumnos']).items()],
            )
    except IntegrityError:   # el mismo envío llegó dos veces a la vez
        existente = EntradaBitacora.objects.filter(clave_envio=clave_envio).first() if clave_envio else None
        if existente is None:
            raise
        return existente, False
    return entrada, True


@transaction.atomic
def editar(entrada, datos, usuario):
    """Aplica los cambios y deja constancia de cada valor anterior y nuevo. Devuelve la lista de cambios ([] si no
    cambió nada: entonces no se toca la entrada)."""
    entrada = EntradaBitacora.objects.select_for_update().get(pk=entrada.pk)
    antes = _foto(entrada, list(entrada.alumnos.all()))
    _aplicar(entrada, datos)
    despues = _foto(entrada, datos['alumnos'])
    cambios = [[que, antes[que], despues[que]] for que in despues if antes[que] != despues[que]]
    if not cambios:
        return []
    entrada.ediciones += 1
    entrada.editada_por, entrada.editada_en = usuario, timezone.now()
    entrada.save()
    _vincular(entrada, datos['alumnos'])
    CambioBitacora.objects.create(entrada=entrada, accion=CambioBitacora.EDICION, usuario=usuario, usuario_nombre=nombre_de(usuario), cambios=cambios)
    return cambios


@transaction.atomic
def anular(entrada, motivo, usuario):
    entrada = EntradaBitacora.objects.select_for_update().get(pk=entrada.pk)
    entrada.anulada, entrada.anulada_por, entrada.anulada_en, entrada.motivo_anulacion = True, usuario, timezone.now(), motivo
    entrada.save(update_fields=['anulada', 'anulada_por', 'anulada_en', 'motivo_anulacion', 'modificado'])
    CambioBitacora.objects.create(entrada=entrada, accion=CambioBitacora.ANULACION, usuario=usuario, usuario_nombre=nombre_de(usuario),
                                  motivo=motivo, cambios=[['Estado', 'Vigente', 'Anulada']])
    return entrada
