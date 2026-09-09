from django.contrib import admin

from Alumnos.models import Alumno

# Register your models here.
admin.site.register(Alumno)


from .models import (
    Alumno,
    CicloEscolar,
    Grado,
    Grupo,
    Inscripcion,
    Materia,
    MateriaGrupo,
    HorarioMateria,
    AsistenciaGeneral,
    AsistenciaMateria,
    Justificacion,
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


@admin.register(Grado)
class GradoAdmin(admin.ModelAdmin):
    list_display = (
        'nivel',
        'numero',
    )


@admin.register(Grupo)
class GrupoAdmin(admin.ModelAdmin):
    list_display = (
        'grado',
        'nombre',
        'ciclo',
        'activo',
    )

    list_filter = (
        'ciclo',
        'grado',
        'activo',
    )


@admin.register(Inscripcion)
class InscripcionAdmin(admin.ModelAdmin):
    list_display = (
        'alumno',
        'grupo',
        'fecha_inscripcion',
        'activa',
    )

    list_filter = (
        'grupo__ciclo',
        'grupo',
        'activa',
    )

    search_fields = (
        'alumno__nombre',
        'alumno__apellido_paterno',
        'alumno__apellido_materno',
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


@admin.register(MateriaGrupo)
class MateriaGrupoAdmin(admin.ModelAdmin):
    list_display = (
        'materia',
        'grupo',
        'activa',
    )

    list_filter = (
        'grupo',
        'activa',
    )


@admin.register(HorarioMateria)
class HorarioMateriaAdmin(admin.ModelAdmin):
    list_display = (
        'materia_grupo',
        'dia_semana',
        'hora_inicio',
        'hora_fin',
    )


@admin.register(AsistenciaGeneral)
class AsistenciaGeneralAdmin(admin.ModelAdmin):
    list_display = (
        'inscripcion',
        'fecha',
        'estado',
    )

    list_filter = (
        'fecha',
        'estado',
        'inscripcion__grupo',
    )

    search_fields = (
        'inscripcion__alumno__nombre',
        'inscripcion__alumno__apellido_paterno',
    )


@admin.register(AsistenciaMateria)
class AsistenciaMateriaAdmin(admin.ModelAdmin):
    list_display = (
        'inscripcion',
        'materia_grupo',
        'fecha',
        'estado',
    )

    list_filter = (
        'fecha',
        'estado',
        'materia_grupo__materia',
        'materia_grupo__grupo',
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

    filter_horizontal = (
        'materias',
    )
