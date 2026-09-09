from django.shortcuts import render

# Create your views here.
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import (render)
from django.utils import timezone
from .forms import AsistenciaRapidaForm
from .models import (
    Alumno,
    Inscripcion,
    MateriaGrupo,
    AsistenciaGeneral,
    AsistenciaMateria,
)

def asistencia_rapida(request):

    fecha = timezone.localdate()
    alumno_registrado = None
    materias_registradas = []

    if request.method == 'POST':

        form = AsistenciaRapidaForm(request.POST)

        if form.is_valid():

            referencia = form.cleaned_data['referencia'].strip()

            # ---------------------------------------
            # BUSCAR ALUMNO
            # ---------------------------------------

            try:
                alumno = Alumno.objects.get(
                    referencia=referencia,
                    estatus='ACTIVO'
                )

            except Alumno.DoesNotExist:

                messages.error(
                    request,
                    f'No existe un alumno activo con la referencia {referencia}.'
                )

                form = AsistenciaRapidaForm()

                return render(
                    request,
                    'colegio/asistencia/rapida.html',
                    {
                        'form': form,
                        'fecha': fecha,
                    }
                )

            # ---------------------------------------
            # BUSCAR INSCRIPCIÓN ACTIVA
            # ---------------------------------------

            inscripcion = (
                Inscripcion.objects
                .filter(
                    alumno=alumno,
                    activa=True,
                    grupo__activo=True,
                    grupo__ciclo__activo=True
                )
                .select_related(
                    'grupo',
                    'grupo__grado',
                    'grupo__ciclo'
                )
                .order_by(
                    '-grupo__ciclo__fecha_inicio'
                )
                .first()
            )

            if not inscripcion:

                messages.error(
                    request,
                    f'{alumno} no tiene una inscripción activa.'
                )

                form = AsistenciaRapidaForm()

                return render(
                    request,
                    'colegio/asistencia/rapida.html',
                    {
                        'form': form,
                        'fecha': fecha,
                    }
                )

            # ---------------------------------------
            # OBTENER MATERIAS DEL GRUPO
            # ---------------------------------------

            materias_grupo = (
                MateriaGrupo.objects
                .filter(
                    grupo=inscripcion.grupo,
                    activa=True,
                    materia__activa=True
                )
                .select_related('materia')
                .order_by('materia__nombre')
            )

            materias_nuevas = 0
            materias_existentes = 0

            with transaction.atomic():

                # =======================================
                # ASISTENCIA GENERAL
                # =======================================

                asistencia_general, general_creada = (
                    AsistenciaGeneral.objects.get_or_create(
                        inscripcion=inscripcion,
                        fecha=fecha,
                        defaults={
                            'estado': 'PRESENTE',
                            'observaciones': '',
                        }
                    )
                )

                # =======================================
                # ASISTENCIA DE TODAS SUS MATERIAS
                # =======================================

                for materia_grupo in materias_grupo:

                    asistencia_materia, creada = (
                        AsistenciaMateria.objects.get_or_create(
                            inscripcion=inscripcion,
                            materia_grupo=materia_grupo,
                            fecha=fecha,
                            defaults={
                                'estado': 'PRESENTE',
                                'observaciones': '',
                            }
                        )
                    )

                    if creada:
                        materias_nuevas += 1
                    else:
                        materias_existentes += 1

                    materias_registradas.append({
                        'nombre': materia_grupo.materia.nombre,
                        'estado': asistencia_materia.get_estado_display(),
                        'creada': creada,
                    })

            alumno_registrado = alumno

            # =======================================
            # MENSAJES
            # =======================================

            if general_creada:

                messages.success(
                    request,
                    f'Asistencia registrada correctamente para {alumno}.'
                )

            else:

                # La general ya existía
                if materias_nuevas > 0:

                    messages.warning(
                        request,
                        (
                            f'{alumno} ya tenía asistencia general '
                            f'el día de hoy. Se registraron '
                            f'{materias_nuevas} materias que faltaban.'
                        )
                    )

                else:

                    messages.warning(
                        request,
                        (
                            f'{alumno} ya tiene registrada la asistencia '
                            f'general y sus materias del día de hoy.'
                        )
                    )

            # Limpiar para siguiente alumno
            form = AsistenciaRapidaForm()

    else:

        form = AsistenciaRapidaForm()

    return render(
        request,
        'colegio/asistencia/rapida.html',
        {
            'form': form,
            'fecha': fecha,
            'alumno_registrado': alumno_registrado,
            'materias_registradas': materias_registradas,
        }
    )