from datetime import date

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone


class Alumno(models.Model):

    SEXO_CHOICES = [
        ('M', 'Masculino'),
        ('F', 'Femenino'),
        ('O', 'Otro'),
    ]

    GRUPO_SANGUINEO_CHOICES = [
        ('A+', 'A+'),
        ('A-', 'A-'),
        ('B+', 'B+'),
        ('B-', 'B-'),
        ('AB+', 'AB+'),
        ('AB-', 'AB-'),
        ('O+', 'O+'),
        ('O-', 'O-'),
    ]

    ESTATUS_CHOICES = [
        ('ACTIVO', 'Activo'),
        ('BAJA', 'Baja'),
        ('EGRESADO', 'Egresado'),
        ('SUSPENDIDO', 'Suspendido'),
    ]

    uid = models.CharField(max_length=50,unique=True,null=True,blank=True,verbose_name='UID de tarjeta')
    referencia = models.CharField(max_length=20,unique=True,verbose_name='Referencia')
    nombre = models.CharField(max_length=80,verbose_name='Nombre')
    apellido_paterno = models.CharField(max_length=60,verbose_name='Apellido paterno')
    apellido_materno = models.CharField(max_length=60,blank=True,verbose_name='Apellido materno')
    curp = models.CharField(max_length=18, unique=True,verbose_name='CURP')
    nacionalidad = models.CharField(max_length=50,default='Mexicana', verbose_name='Nacionalidad')
    sexo = models.CharField(max_length=1, choices=SEXO_CHOICES, verbose_name='Sexo')
    fecha_nacimiento = models.DateField(verbose_name='Fecha de nacimiento')
    grupo_sanguineo = models.CharField(max_length=3, choices=GRUPO_SANGUINEO_CHOICES, verbose_name='Grupo sanguíneo')
    religion = models.CharField(max_length=80, blank=True, verbose_name='Religión')
    alergias = models.TextField(blank=True, verbose_name='Alergias')
    domicilio = models.CharField(max_length=200, verbose_name='Domicilio')
    colonia = models.CharField(max_length=100, verbose_name='Colonia')
    ciudad = models.CharField(max_length=100, verbose_name='Ciudad')
    estado = models.CharField(max_length=100, verbose_name='Estado')
    cp = models.CharField(max_length=5, validators=[RegexValidator(regex=r'^\d{5}$', message='El código postal debe contener exactamente 5 dígitos.')], verbose_name='Código postal')
    fecha_ingreso = models.DateField(default=date.today, verbose_name='Fecha de ingreso')
    escuela_procedencia = models.CharField(max_length=200, blank=True, verbose_name='Escuela de procedencia')
    observaciones_generales = models.TextField(blank=True, verbose_name='Observaciones generales')
    fotografia = models.ImageField(upload_to='alumnos/', blank=True, null=True, verbose_name='Fotografía')
    correo_electronico = models.EmailField(max_length=254, unique=True, null=True, blank=True, verbose_name='Correo electrónico')
    contrasena = models.CharField(max_length=128, verbose_name='Contraseña')
    estatus = models.CharField(max_length=20, choices=ESTATUS_CHOICES, default='ACTIVO', verbose_name='Estatus')

    def __str__(self):
        return (
            f"{self.nombre} "
            f"{self.apellido_paterno} "
            f"{self.apellido_materno}"
        ).strip()

    class Meta:
        verbose_name = 'Alumno'
        verbose_name_plural = 'Alumnos'
        ordering = [
            'apellido_paterno',
            'apellido_materno',
            'nombre'
        ]
        db_table = 'alumnos'


class CicloEscolar(models.Model):

    nombre = models.CharField(max_length=30, unique=True, verbose_name='Ciclo escolar')
    fecha_inicio = models.DateField(verbose_name='Fecha de inicio')
    fecha_fin = models.DateField(verbose_name='Fecha de fin')
    activo = models.BooleanField(default=True, verbose_name='Activo')

    def clean(self):
        if (
            self.fecha_inicio
            and self.fecha_fin
            and self.fecha_inicio >= self.fecha_fin
        ):
            raise ValidationError(
                'La fecha de inicio debe ser anterior a la fecha de fin.'
            )

    def __str__(self):
        return self.nombre

    class Meta:
        verbose_name = 'Ciclo escolar'
        verbose_name_plural = 'Ciclos escolares'
        ordering = ['-fecha_inicio']


class Grado(models.Model):
    NIVEL_CHOICES = [
        ('PREESCOLAR', 'Preescolar'),
        ('PRIMARIA', 'Primaria'),
        ('SECUNDARIA', 'Secundaria'),
        ('PREPARATORIA', 'Preparatoria'),
    ]
    nivel = models.CharField(max_length=20, choices=NIVEL_CHOICES, verbose_name='Nivel')
    numero = models.PositiveSmallIntegerField(verbose_name='Grado')

    def __str__(self):
        return f"{self.numero}° {self.get_nivel_display()}"

    class Meta:
        verbose_name = 'Grado'
        verbose_name_plural = 'Grados'
        ordering = [
            'nivel',
            'numero'
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    'nivel',
                    'numero'
                ],
                name='grado_nivel_numero_unico'
            )
        ]


class Inscripcion(models.Model):

    alumno = models.ForeignKey(Alumno, on_delete=models.PROTECT, related_name='inscripciones')
    ciclo = models.ForeignKey(CicloEscolar, on_delete=models.PROTECT, related_name='inscripciones')
    grado = models.ForeignKey(Grado, on_delete=models.PROTECT, related_name='inscripciones')
    fecha_inscripcion = models.DateField(default=timezone.localdate, verbose_name='Fecha de inscripción')
    activa = models.BooleanField(default=True, verbose_name='Activa')

    def __str__(self):
        return (
            f"{self.alumno} - "
            f"{self.grado} - "
            f"{self.ciclo}"
        )

    def clean(self):

        if (
            self.activa
            and self.alumno_id
            and self.ciclo_id
        ):
            existe = (
                Inscripcion.objects
                .filter(
                    alumno=self.alumno,
                    ciclo=self.ciclo,
                    activa=True
                )
                .exclude(pk=self.pk)
                .exists()
            )

            if existe:
                raise ValidationError(
                    'El alumno ya tiene una inscripción activa '
                    'en este ciclo escolar.'
                )

    class Meta:
        verbose_name = 'Inscripción'
        verbose_name_plural = 'Inscripciones'
        constraints = [
            models.UniqueConstraint(
                fields=[
                    'alumno',
                    'ciclo'
                ],
                name='alumno_ciclo_unico'
            )
        ]


class Materia(models.Model):

    clave = models.CharField(max_length=20, unique=True, verbose_name='Clave')
    nombre = models.CharField(max_length=100, verbose_name='Nombre')
    activa = models.BooleanField(default=True, verbose_name='Activa')

    def __str__(self):
        return self.nombre

    class Meta:
        verbose_name = 'Materia'
        verbose_name_plural = 'Materias'
        ordering = ['nombre']


class MateriaGrado(models.Model):

    ciclo = models.ForeignKey(CicloEscolar, on_delete=models.PROTECT, related_name='materias_grado')
    grado = models.ForeignKey(Grado, on_delete=models.PROTECT, related_name='materias_grado')
    materia = models.ForeignKey(Materia, on_delete=models.PROTECT, related_name='grados_materia')
    activa = models.BooleanField(default=True, verbose_name='Activa')

    def __str__(self):
        return (
            f"{self.materia} - "
            f"{self.grado} - "
            f"{self.ciclo}"
        )

    class Meta:
        verbose_name = 'Materia del grado'
        verbose_name_plural = 'Materias del grado'

        ordering = [
            'grado',
            'materia__nombre'
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    'ciclo',
                    'grado',
                    'materia'
                ],
                name='materia_grado_ciclo_unica'
            )
        ]

class HorarioMateria(models.Model):

    DIA_CHOICES = [
        (0, 'Lunes'),
        (1, 'Martes'),
        (2, 'Miércoles'),
        (3, 'Jueves'),
        (4, 'Viernes'),
        (5, 'Sábado'),
        (6, 'Domingo'),
    ]

    materia_grado = models.ForeignKey(MateriaGrado, on_delete=models.CASCADE, related_name='horarios')
    dia_semana = models.PositiveSmallIntegerField(choices=DIA_CHOICES, verbose_name='Día')
    hora_inicio = models.TimeField(verbose_name='Hora de inicio')
    hora_fin = models.TimeField(verbose_name='Hora de fin')

    def clean(self):

        if (
            self.hora_inicio
            and self.hora_fin
            and self.hora_inicio >= self.hora_fin
        ):
            raise ValidationError(
                'La hora de inicio debe ser anterior a la hora de fin.'
            )

    def __str__(self):
        return (
            f"{self.materia_grado} - "
            f"{self.get_dia_semana_display()} "
            f"{self.hora_inicio} - {self.hora_fin}"
        )

    class Meta:
        verbose_name = 'Horario de materia'
        verbose_name_plural = 'Horarios de materias'
        ordering = [
            'dia_semana',
            'hora_inicio'
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    'materia_grado',
                    'dia_semana',
                    'hora_inicio',
                    'hora_fin'
                ],
                name='horario_materia_unico'
            )
        ]

class AsistenciaGeneral(models.Model):

    ESTADO_CHOICES = [
        ('PRESENTE', 'Presente'),
        ('FALTA', 'Falta'),
        ('RETARDO', 'Retardo'),
    ]

    inscripcion = models.ForeignKey(Inscripcion, on_delete=models.CASCADE, related_name='asistencias_generales')
    fecha = models.DateField(verbose_name='Fecha')
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default='PRESENTE', verbose_name='Estado')
    observaciones = models.CharField(max_length=250, blank=True, verbose_name='Observaciones')
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    def __str__(self):
        return (
            f"{self.inscripcion.alumno} - "
            f"{self.fecha} - "
            f"{self.get_estado_display()}"
        )

    class Meta:
        verbose_name = 'Asistencia general'
        verbose_name_plural = 'Asistencias generales'

        ordering = [
            '-fecha',
            '-creado'
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    'inscripcion',
                    'fecha'
                ],
                name='asistencia_general_unica'
            )
        ]

        indexes = [
            models.Index(
                fields=['fecha']
            ),
        ]


class AsistenciaMateria(models.Model):

    ESTADO_CHOICES = [
        ('PRESENTE', 'Presente'),
        ('FALTA', 'Falta'),
        ('RETARDO', 'Retardo'),
    ]

    inscripcion = models.ForeignKey(Inscripcion, on_delete=models.CASCADE, related_name='asistencias_materias')
    materia_grado = models.ForeignKey(MateriaGrado, on_delete=models.PROTECT, related_name='asistencias')
    fecha = models.DateField(verbose_name='Fecha')
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default='PRESENTE', verbose_name='Estado')
    observaciones = models.CharField(max_length=250, blank=True, verbose_name='Observaciones')
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    def clean(self):

        if not (
            self.inscripcion_id
            and self.materia_grado_id
        ):
            return

        if (
            self.inscripcion.grado_id
            != self.materia_grado.grado_id
        ):
            raise ValidationError(
                'La materia no pertenece al grado del alumno.'
            )

        if (
            self.inscripcion.ciclo_id
            != self.materia_grado.ciclo_id
        ):
            raise ValidationError(
                'La materia no pertenece al ciclo escolar '
                'de la inscripción del alumno.'
            )

    def __str__(self):
        return (
            f"{self.inscripcion.alumno} - "
            f"{self.materia_grado.materia} - "
            f"{self.fecha}"
        )

    class Meta:
        verbose_name = 'Asistencia por materia'
        verbose_name_plural = 'Asistencias por materia'
        ordering = [
            '-fecha',
            '-creado'
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    'inscripcion',
                    'materia_grado',
                    'fecha'
                ],
                name='asistencia_materia_unica'
            )
        ]

        indexes = [
            models.Index(
                fields=['fecha']
            ),
        ]

class Justificacion(models.Model):

    inscripcion = models.ForeignKey(Inscripcion, on_delete=models.CASCADE, related_name='justificaciones')
    fecha = models.DateField(verbose_name='Fecha')
    motivo = models.TextField(verbose_name='Motivo')
    justifica_general = models.BooleanField(default=False, verbose_name='Justificar asistencia general')
    todas_materias = models.BooleanField(default=False, verbose_name='Justificar todas las materias')
    materias = models.ManyToManyField(MateriaGrado, blank=True, related_name='justificaciones', verbose_name='Materias')
    documento = models.FileField(upload_to='justificaciones/%Y/%m/', blank=True, null=True, verbose_name='Comprobante')
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    def __str__(self):
        return (
            f"{self.inscripcion.alumno} - "
            f"{self.fecha}"
        )

    class Meta:
        verbose_name = 'Justificación'
        verbose_name_plural = 'Justificaciones'
        ordering = [
            '-fecha'
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    'inscripcion',
                    'fecha'
                ],
                name='justificacion_alumno_fecha_unica'
            )
        ]


class Tutor(models.Model):



    ESTATUS_CHOICES = [
        ('ACTIVO', 'Activo'),
        ('INACTIVO', 'Inactivo'),
    ]

    ESTADO_CIVIL_CHOICES = [
        ('SOLTERO', 'Soltero/a'),
        ('CASADO', 'Casado/a'),
        ('DIVORCIADO', 'Divorciado/a'),
        ('VIUDO', 'Viudo/a'),
        ('UNION_LIBRE', 'Unión libre'),
        ('OTRO', 'Otro'),
    ]

    nombre = models.CharField(max_length=80, verbose_name='Nombre')
    apellido_paterno = models.CharField(max_length=60, verbose_name='Apellido paterno')
    apellido_materno = models.CharField(max_length=60, blank=True, verbose_name='Apellido materno')
    curp = models.CharField(max_length=18, unique=True, null=True, blank=True, verbose_name='CURP')
    estado_civil = models.CharField(max_length=20, choices=ESTADO_CIVIL_CHOICES, blank=True, verbose_name='Estado civil')
    religion = models.CharField(max_length=80, blank=True, verbose_name='Religión')
    telefono = models.CharField(max_length=20, verbose_name='Teléfono')
    telefono_alternativo = models.CharField(max_length=20, blank=True, verbose_name='Teléfono alternativo')
    correo_electronico = models.EmailField(max_length=254,blank=True,null=True,verbose_name='Correo electrónico')
    domicilio = models.CharField(max_length=200,blank=True, verbose_name='Domicilio')
    colonia = models.CharField(max_length=100,blank=True,verbose_name='Colonia')
    ciudad = models.CharField(max_length=100,blank=True,verbose_name='Ciudad')
    estado = models.CharField(max_length=100,blank=True,verbose_name='Estado')
    cp = models.CharField(max_length=5,blank=True,validators=[RegexValidator(regex=r'^\d{5}$',message='El código postal debe contener exactamente 5 dígitos.')],verbose_name='Código postal')
    ocupacion = models.CharField(max_length=100,blank=True,verbose_name='Ocupación')
    lugar_trabajo = models.CharField(max_length=150,blank=True,verbose_name='Lugar de trabajo')
    telefono_trabajo = models.CharField(max_length=20,blank=True,verbose_name='Teléfono del trabajo')
    observaciones = models.TextField(blank=True,verbose_name='Observaciones')
    estatus = models.CharField(max_length=20,choices=ESTATUS_CHOICES,default='ACTIVO',verbose_name='Estatus')
    creado = models.DateTimeField( auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    def __str__(self):
        return (
            f"{self.nombre} "
            f"{self.apellido_paterno} "
            f"{self.apellido_materno}"
        ).strip()

    class Meta:
        verbose_name = 'Tutor'
        verbose_name_plural = 'Tutores'
        ordering = [
            'apellido_paterno',
            'apellido_materno',
            'nombre'
        ]


class TutorAlumno(models.Model):
    PARENTESCO_CHOICES = [
        ('MADRE', 'Madre'),
        ('PADRE', 'Padre'),
        ('ABUELA', 'Abuela'),
        ('ABUELO', 'Abuelo'),
        ('HERMANA', 'Hermana'),
        ('HERMANO', 'Hermano'),
        ('TIA', 'Tía'),
        ('TIO', 'Tío'),
        ('TUTOR_LEGAL', 'Tutor legal'),
        ('OTRO', 'Otro'),
    ]
    tutor = models.ForeignKey(Tutor,on_delete=models.CASCADE,related_name='alumnos_relacionados')
    alumno = models.ForeignKey(Alumno,on_delete=models.CASCADE,related_name='tutores_relacionados')
    parentesco = models.CharField(max_length=20,choices=PARENTESCO_CHOICES,verbose_name='Parentesco')
    tutor_principal = models.BooleanField( default=False,verbose_name='Tutor principal')
    contacto_emergencia = models.BooleanField(default=False,verbose_name='Contacto de emergencia')
    autorizado_recoger = models.BooleanField(default=False,verbose_name='Autorizado para recoger al alumno')
    recibe_notificaciones = models.BooleanField(default=True,verbose_name='Recibe notificaciones')
    responsable_pagos = models.BooleanField(default=False,verbose_name='Responsable de pagos')
    observaciones = models.TextField(blank=True,verbose_name='Observaciones')
    activo = models.BooleanField(default=True,verbose_name='Activo')
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    def __str__(self):
        return (
            f"{self.tutor} - "
            f"{self.alumno} - "
            f"{self.get_parentesco_display()}"
        )

    class Meta:
        verbose_name = 'Tutor del alumno'
        verbose_name_plural = 'Tutores de alumnos'

        constraints = [
            models.UniqueConstraint(
                fields=[
                    'tutor',
                    'alumno'
                ],
                name='tutor_alumno_unico'
            )
        ]