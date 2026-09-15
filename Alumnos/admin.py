from django.contrib import admin

from .models import (
    Alumno,
    CicloEscolar,
    Grado,
    Inscripcion,
    Materia,
    MateriaGrado,
    HorarioMateria,
    AsistenciaGeneral,
    AsistenciaMateria,
    Justificacion,
)


@admin.register(Alumno)
class AlumnoAdmin(admin.ModelAdmin):
    list_display = (
        'referencia',
        'uid',
        'nombre',
        'apellido_paterno',
        'apellido_materno',
        'sexo',
        'estatus',
    )

    search_fields = (
        'referencia',
        'uid',
        'nombre',
        'apellido_paterno',
        'apellido_materno',
        'curp',
        'correo_electronico',
    )

    list_filter = (
        'estatus',
        'sexo',
    )

    ordering = (
        'apellido_paterno',
        'apellido_materno',
        'nombre',
    )


@admin.register(CicloEscolar)
class CicloEscolarAdmin(admin.ModelAdmin):
    list_display = (
        'nombre',
        'fecha_inicio',
        'fecha_fin',
        'activo',
    )

    list_filter = (
        'activo',
    )

    ordering = (
        '-fecha_inicio',
    )


@admin.register(Grado)
class GradoAdmin(admin.ModelAdmin):
    list_display = (
        'numero',
        'nivel',
    )

    list_filter = (
        'nivel',
    )

    ordering = (
        'nivel',
        'numero',
    )


@admin.register(Inscripcion)
class InscripcionAdmin(admin.ModelAdmin):
    list_display = (
        'alumno',
        'grado',
        'ciclo',
        'fecha_inscripcion',
        'activa',
    )

    list_filter = (
        'ciclo',
        'grado',
        'activa',
    )

    search_fields = (
        'alumno__referencia',
        'alumno__uid',
        'alumno__nombre',
        'alumno__apellido_paterno',
        'alumno__apellido_materno',
    )

    autocomplete_fields = (
        'alumno',
    )

    ordering = (
        '-fecha_inscripcion',
    )


@admin.register(Materia)
class MateriaAdmin(admin.ModelAdmin):
    list_display = (
        'clave',
        'nombre',
        'activa',
    )

    search_fields = (
        'clave',
        'nombre',
    )

    list_filter = (
        'activa',
    )

    ordering = (
        'nombre',
    )


@admin.register(MateriaGrado)
class MateriaGradoAdmin(admin.ModelAdmin):
    list_display = (
        'materia',
        'grado',
        'ciclo',
        'activa',
    )

    list_filter = (
        'ciclo',
        'grado',
        'activa',
    )

    search_fields = (
        'materia__clave',
        'materia__nombre',
    )

    autocomplete_fields = (
        'materia',
    )

    ordering = (
        'ciclo',
        'grado',
        'materia__nombre',
    )


@admin.register(HorarioMateria)
class HorarioMateriaAdmin(admin.ModelAdmin):
    list_display = (
        'materia_grado',
        'dia_semana',
        'hora_inicio',
        'hora_fin',
    )

    list_filter = (
        'dia_semana',
        'materia_grado__ciclo',
        'materia_grado__grado',
    )

    search_fields = (
        'materia_grado__materia__nombre',
        'materia_grado__materia__clave',
    )

    ordering = (
        'dia_semana',
        'hora_inicio',
    )


@admin.register(AsistenciaGeneral)
class AsistenciaGeneralAdmin(admin.ModelAdmin):
    list_display = (
        'inscripcion',
        'fecha',
        'estado',
        'creado',
    )

    list_filter = (
        'fecha',
        'estado',
        'inscripcion__grado',
        'inscripcion__ciclo',
    )

    search_fields = (
        'inscripcion__alumno__referencia',
        'inscripcion__alumno__uid',
        'inscripcion__alumno__nombre',
        'inscripcion__alumno__apellido_paterno',
        'inscripcion__alumno__apellido_materno',
    )

    date_hierarchy = 'fecha'

    ordering = (
        '-fecha',
        '-creado',
    )


@admin.register(AsistenciaMateria)
class AsistenciaMateriaAdmin(admin.ModelAdmin):
    list_display = (
        'inscripcion',
        'materia_grado',
        'fecha',
        'estado',
        'creado',
    )

    list_filter = (
        'fecha',
        'estado',
        'materia_grado__materia',
        'materia_grado__grado',
        'materia_grado__ciclo',
    )

    search_fields = (
        'inscripcion__alumno__referencia',
        'inscripcion__alumno__uid',
        'inscripcion__alumno__nombre',
        'inscripcion__alumno__apellido_paterno',
        'inscripcion__alumno__apellido_materno',
        'materia_grado__materia__nombre',
        'materia_grado__materia__clave',
    )

    date_hierarchy = 'fecha'

    ordering = (
        '-fecha',
        '-creado',
    )


@admin.register(Justificacion)
class JustificacionAdmin(admin.ModelAdmin):
    list_display = (
        'inscripcion',
        'fecha',
        'justifica_general',
        'todas_materias',
        'creado',
    )

    list_filter = (
        'fecha',
        'justifica_general',
        'todas_materias',
        'inscripcion__grado',
        'inscripcion__ciclo',
    )

    search_fields = (
        'inscripcion__alumno__referencia',
        'inscripcion__alumno__uid',
        'inscripcion__alumno__nombre',
        'inscripcion__alumno__apellido_paterno',
        'inscripcion__alumno__apellido_materno',
    )

    filter_horizontal = (
        'materias',
    )

    date_hierarchy = 'fecha'

    ordering = (
        '-fecha',
        '-creado',
    )


from django.contrib import admin

from .models import Tutor, TutorAlumno


@admin.register(Tutor)
class TutorAdmin(admin.ModelAdmin):
    list_display = (
        'nombre',
        'apellido_paterno',
        'apellido_materno',
        'telefono',
        'correo_electronico',
        'ocupacion',
        'estatus',
    )

    search_fields = (
        'nombre',
        'apellido_paterno',
        'apellido_materno',
        'curp',
        'telefono',
        'correo_electronico',
    )

    list_filter = (
        'estatus',
        'estado_civil',
        'estado',
    )

    ordering = (
        'apellido_paterno',
        'apellido_materno',
        'nombre',
    )

    readonly_fields = (
        'creado',
        'modificado',
    )


@admin.register(TutorAlumno)
class TutorAlumnoAdmin(admin.ModelAdmin):
    list_display = (
        'tutor',
        'alumno',
        'parentesco',
        'tutor_principal',
        'contacto_emergencia',
        'autorizado_recoger',
        'recibe_notificaciones',
        'responsable_pagos',
        'activo',
    )

    search_fields = (
        'tutor__nombre',
        'tutor__apellido_paterno',
        'tutor__apellido_materno',
        'alumno__nombre',
        'alumno__apellido_paterno',
        'alumno__apellido_materno',
    )

    list_filter = (
        'parentesco',
        'tutor_principal',
        'contacto_emergencia',
        'autorizado_recoger',
        'recibe_notificaciones',
        'responsable_pagos',
        'activo',
    )

    readonly_fields = (
        'creado',
        'modificado',
    )
