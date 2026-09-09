from django.db import models

# Create your models here.
from datetime import date
from django.core.validators import RegexValidator
from django.db import models


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
    referencia = models.CharField(max_length=20, unique=True, verbose_name='Referencia')
    nombre = models.CharField(max_length=80, verbose_name='Nombre')
    apellido_paterno = models.CharField(max_length=60, verbose_name='Apellido paterno')
    apellido_materno = models.CharField(max_length=60, blank=True, verbose_name='Apellido materno')
    curp = models.CharField(max_length=18, unique=True, verbose_name='CURP')
    nacionalidad = models.CharField(max_length=50, default='Mexicana', verbose_name='Nacionalidad')
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
        return f"{self.nombre} {self.apellido_paterno} {self.apellido_materno}".strip()

    class Meta:
        verbose_name = 'Alumno'
        verbose_name_plural = 'Alumnos'
        ordering = ['apellido_paterno', 'apellido_materno', 'nombre']
        db_table = 'alumnos'

from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone


class CicloEscolar(models.Model):
    nombre = models.CharField(
        max_length=30,
        unique=True,
        verbose_name='Ciclo escolar'
    )
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    activo = models.BooleanField(default=True)

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

    nivel = models.CharField(
        max_length=20,
        choices=NIVEL_CHOICES
    )

    numero = models.PositiveSmallIntegerField(
        verbose_name='Grado'
    )

    def __str__(self):
        return f"{self.numero}° {self.get_nivel_display()}"

    class Meta:
        verbose_name = 'Grado'
        verbose_name_plural = 'Grados'
        constraints = [
            models.UniqueConstraint(
                fields=['nivel', 'numero'],
                name='grado_nivel_numero_unico'
            )
        ]


class Grupo(models.Model):
    ciclo = models.ForeignKey(
        CicloEscolar,
        on_delete=models.PROTECT,
        related_name='grupos'
    )

    grado = models.ForeignKey(
        Grado,
        on_delete=models.PROTECT,
        related_name='grupos'
    )

    nombre = models.CharField(
        max_length=20,
        verbose_name='Grupo'
    )

    activo = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.grado} - {self.nombre} ({self.ciclo})"

    class Meta:
        verbose_name = 'Grupo'
        verbose_name_plural = 'Grupos'
        constraints = [
            models.UniqueConstraint(
                fields=['ciclo', 'grado', 'nombre'],
                name='grupo_unico_por_ciclo'
            )
        ]


class Inscripcion(models.Model):
    alumno = models.ForeignKey(
        Alumno,
        on_delete=models.PROTECT,
        related_name='inscripciones'
    )

    grupo = models.ForeignKey(
        Grupo,
        on_delete=models.PROTECT,
        related_name='inscripciones'
    )

    fecha_inscripcion = models.DateField(
        default=timezone.localdate
    )

    activa = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.alumno} - {self.grupo}"

    def clean(self):
        """
        Evita que el alumno aparezca en dos grupos activos
        del mismo ciclo escolar.
        """
        if self.activa and self.grupo_id and self.alumno_id:

            existe = Inscripcion.objects.filter(
                alumno=self.alumno,
                grupo__ciclo=self.grupo.ciclo,
                activa=True
            ).exclude(pk=self.pk).exists()

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
                fields=['alumno', 'grupo'],
                name='alumno_grupo_unico'
            )
        ]


class Materia(models.Model):
    clave = models.CharField(
        max_length=20,
        unique=True
    )

    nombre = models.CharField(
        max_length=100
    )

    activa = models.BooleanField(default=True)

    def __str__(self):
        return self.nombre

    class Meta:
        verbose_name = 'Materia'
        verbose_name_plural = 'Materias'
        ordering = ['nombre']


class MateriaGrupo(models.Model):
    """
    Indica qué materias lleva determinado grupo.
    """

    grupo = models.ForeignKey(
        Grupo,
        on_delete=models.CASCADE,
        related_name='materias_grupo'
    )

    materia = models.ForeignKey(
        Materia,
        on_delete=models.PROTECT,
        related_name='grupos_materia'
    )

    activa = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.materia} - {self.grupo}"

    class Meta:
        verbose_name = 'Materia del grupo'
        verbose_name_plural = 'Materias del grupo'
        constraints = [
            models.UniqueConstraint(
                fields=['grupo', 'materia'],
                name='materia_grupo_unica'
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

    materia_grupo = models.ForeignKey(
        MateriaGrupo,
        on_delete=models.CASCADE,
        related_name='horarios'
    )

    dia_semana = models.PositiveSmallIntegerField(
        choices=DIA_CHOICES
    )

    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()

    def __str__(self):
        return (
            f"{self.materia_grupo} - "
            f"{self.get_dia_semana_display()} "
            f"{self.hora_inicio}"
        )

    class Meta:
        verbose_name = 'Horario de materia'
        verbose_name_plural = 'Horarios de materias'
        ordering = [
            'dia_semana',
            'hora_inicio'
        ]


class AsistenciaGeneral(models.Model):

    ESTADO_CHOICES = [
        ('PRESENTE', 'Presente'),
        ('FALTA', 'Falta'),
        ('RETARDO', 'Retardo'),
    ]

    inscripcion = models.ForeignKey(
        Inscripcion,
        on_delete=models.CASCADE,
        related_name='asistencias_generales'
    )

    fecha = models.DateField()

    estado = models.CharField(
        max_length=15,
        choices=ESTADO_CHOICES,
        default='PRESENTE'
    )

    observaciones = models.CharField(
        max_length=250,
        blank=True
    )

    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.inscripcion.alumno} - {self.fecha} - {self.estado}"

    class Meta:
        verbose_name = 'Asistencia general'
        verbose_name_plural = 'Asistencias generales'
        ordering = ['-fecha']

        constraints = [
            models.UniqueConstraint(
                fields=['inscripcion', 'fecha'],
                name='asistencia_general_unica'
            )
        ]

        indexes = [
            models.Index(fields=['fecha']),
        ]


class AsistenciaMateria(models.Model):

    ESTADO_CHOICES = [
        ('PRESENTE', 'Presente'),
        ('FALTA', 'Falta'),
        ('RETARDO', 'Retardo'),
    ]

    inscripcion = models.ForeignKey(
        Inscripcion,
        on_delete=models.CASCADE,
        related_name='asistencias_materias'
    )

    materia_grupo = models.ForeignKey(
        MateriaGrupo,
        on_delete=models.PROTECT,
        related_name='asistencias'
    )

    fecha = models.DateField()

    estado = models.CharField(
        max_length=15,
        choices=ESTADO_CHOICES,
        default='PRESENTE'
    )

    observaciones = models.CharField(
        max_length=250,
        blank=True
    )

    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    def clean(self):
        if (
            self.inscripcion_id
            and self.materia_grupo_id
            and self.inscripcion.grupo_id != self.materia_grupo.grupo_id
        ):
            raise ValidationError(
                'La materia no pertenece al grupo del alumno.'
            )

    def __str__(self):
        return (
            f"{self.inscripcion.alumno} - "
            f"{self.materia_grupo.materia} - "
            f"{self.fecha}"
        )

    class Meta:
        verbose_name = 'Asistencia por materia'
        verbose_name_plural = 'Asistencias por materia'

        constraints = [
            models.UniqueConstraint(
                fields=[
                    'inscripcion',
                    'materia_grupo',
                    'fecha'
                ],
                name='asistencia_materia_unica'
            )
        ]

        indexes = [
            models.Index(fields=['fecha']),
        ]


class Justificacion(models.Model):

    inscripcion = models.ForeignKey(
        Inscripcion,
        on_delete=models.CASCADE,
        related_name='justificaciones'
    )

    fecha = models.DateField()

    motivo = models.TextField()

    # Justificar la falta de entrada general al colegio
    justifica_general = models.BooleanField(
        default=False,
        verbose_name='Justificar asistencia general'
    )

    # Justificar todas las materias de ese día
    todas_materias = models.BooleanField(
        default=False,
        verbose_name='Justificar todas las materias'
    )

    # Si no son todas, cuáles materias se justifican
    materias = models.ManyToManyField(
        MateriaGrupo,
        blank=True,
        related_name='justificaciones'
    )

    documento = models.FileField(
        upload_to='justificaciones/%Y/%m/',
        blank=True,
        null=True,
        verbose_name='Comprobante'
    )

    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.inscripcion.alumno} - {self.fecha}"

    class Meta:
        verbose_name = 'Justificación'
        verbose_name_plural = 'Justificaciones'

        constraints = [
            models.UniqueConstraint(
                fields=['inscripcion', 'fecha'],
                name='justificacion_alumno_fecha_unica'
            )
        ]