from datetime import date, time

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, RegexValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone


class Alumno(models.Model):

    SEXO_CHOICES = [
        ('M', 'Masculino'),
        ('F', 'Femenino'),
    ]

    # El texto guardado es el mismo que se lee en pantalla
    RELIGION_CHOICES = [(religion, religion) for religion in (
        'Católica',
        'Cristiana',
        'Evangélica',
        'Iglesia de Jesucristo de los Santos de los Últimos Días',
        'Musulmana',
        'Judía',
        'Budista',
        'Hinduista',
        'Otra',
    )]

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
    # Los formularios la ofrecen como lista (RELIGION_CHOICES), pero el campo no restringe: así los registros anteriores,
    # escritos a mano, siguen siendo válidos y no se pierden al editarlos.
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
    # La contraseña tal como se asignó, para que un administrador pueda consultarla. `contrasena` (cifrada) sigue siendo
    # la que se verifica; esta es solo de consulta y queda vacía en los estudiantes anteriores, hasta que se restablezca.
    contrasena_visible = models.CharField(max_length=64, blank=True, default='', editable=False, verbose_name='Contraseña (consulta)')
    estatus = models.CharField(max_length=20, choices=ESTATUS_CHOICES, default='ACTIVO', verbose_name='Estatus')

    def __str__(self):
        return (
            f"{self.nombre} "
            f"{self.apellido_paterno} "
            f"{self.apellido_materno}"
        ).strip()

    def establecer_contrasena(self, contrasena):
        """Asigna la contraseña (cifrada para verificarla y legible para consulta). No guarda el registro."""
        self.contrasena = make_password(contrasena)
        self.contrasena_visible = contrasena

    @property
    def nombre_completo(self):
        return str(self)

    @property
    def iniciales(self):
        return (self.nombre[:1] + self.apellido_paterno[:1]).upper()

    @property
    def edad(self):
        """Años cumplidos a la fecha de hoy."""
        hoy = timezone.localdate()
        nacimiento = self.fecha_nacimiento
        return hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))

    def get_absolute_url(self):
        return reverse('alumnos:detalle', args=[self.pk])

    class Meta:
        verbose_name = 'Estudiante'
        verbose_name_plural = 'Estudiantes'
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

    def get_absolute_url(self):
        return reverse('ciclos:detalle', args=[self.pk])

    @property
    def estado(self):
        """ACTUAL (el ciclo en curso), PROXIMO (todavía no empieza) o CERRADO."""
        if self.activo:
            return 'ACTUAL'
        return 'PROXIMO' if self.fecha_inicio > timezone.localdate() else 'CERRADO'

    @property
    def estado_display(self):
        return {'ACTUAL': 'Actual', 'PROXIMO': 'Próximo', 'CERRADO': 'Cerrado'}[self.estado]

    @property
    def duracion_dias(self):
        return (self.fecha_fin - self.fecha_inicio).days + 1

    @property
    def avance(self):
        """Porcentaje (0-100) del ciclo que ya transcurrió."""
        hoy = timezone.localdate()
        if hoy <= self.fecha_inicio:
            return 0
        if hoy >= self.fecha_fin:
            return 100
        return round((hoy - self.fecha_inicio).days * 100 / max((self.fecha_fin - self.fecha_inicio).days, 1))

    @property
    def fuera_de_fechas(self):
        """True si es el ciclo actual pero hoy queda fuera de su rango de fechas (conviene revisarlo)."""
        hoy = timezone.localdate()
        return self.activo and not (self.fecha_inicio <= hoy <= self.fecha_fin)

    class Meta:
        verbose_name = 'Ciclo escolar'
        verbose_name_plural = 'Ciclos escolares'
        ordering = ['-fecha_inicio']


ORDEN_NIVELES = ('PREESCOLAR', 'PRIMARIA', 'SECUNDARIA', 'PREPARATORIA')


def orden_de_nivel(campo='nivel'):
    """Expresión para ordenar por nivel escolar (preescolar, primaria, secundaria, preparatoria).

    El orden alfabético de `nivel` pondría a la preparatoria antes que a la primaria. `campo` es la ruta al
    nivel cuando se parte de otro modelo (por ejemplo 'grado__nivel' desde una inscripción).
    """
    return models.Case(
        *[models.When(**{campo: nombre}, then=models.Value(indice)) for indice, nombre in enumerate(ORDEN_NIVELES)],
        default=models.Value(len(ORDEN_NIVELES)),
        output_field=models.IntegerField(),
    )


class GradoQuerySet(models.QuerySet):
    def academicos(self):
        """Orden escolar: por nivel (preescolar a preparatoria) y, dentro de cada nivel, por número."""
        return self.order_by(orden_de_nivel(), 'numero')


class Grado(models.Model):
    NIVEL_CHOICES = [
        ('PREESCOLAR', 'Preescolar'),
        ('PRIMARIA', 'Primaria'),
        ('SECUNDARIA', 'Secundaria'),
        ('PREPARATORIA', 'Preparatoria'),
    ]
    nivel = models.CharField(max_length=20, choices=NIVEL_CHOICES, verbose_name='Nivel')
    numero = models.PositiveSmallIntegerField(verbose_name='Grado')
    activo = models.BooleanField(default=True, verbose_name='Activo')
    equivalencia = models.CharField(
        max_length=8, blank=True, default='', verbose_name='Equivalencia',
        help_text='Cómo se nombra el grado en la continuidad escolar, sin importar el nivel: un número (1.° de secundaria '
                  'equivale al 7.°) o un código con letras (K1 para 1.° de preescolar).',
    )

    objects = GradoQuerySet.as_manager()

    def __str__(self):
        return f"{self.numero}° {self.get_nivel_display()}"

    @property
    def equivalencia_numero(self):
        """La equivalencia como número (7); None si no tiene o es un código con letras (K1)."""
        valor = str(self.equivalencia or '')
        return int(valor) if valor.isdigit() else None

    @property
    def equivalencia_texto(self):
        """«7°» si la equivalencia es un número, el código tal cual («K1») si lleva letras; vacío si no tiene."""
        if not self.equivalencia:
            return ''
        return f'{self.equivalencia_numero}°' if self.equivalencia_numero is not None else self.equivalencia

    @property
    def equivalencia_frase(self):
        """«Equivale al 7°» o «Equivale a K1»; vacío si no tiene equivalencia."""
        if not self.equivalencia:
            return ''
        return f'Equivale al {self.equivalencia_texto}' if self.equivalencia_numero is not None else f'Equivale a {self.equivalencia_texto}'

    def get_absolute_url(self):
        return reverse('grados:detalle', args=[self.pk])

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

    alumno = models.ForeignKey(Alumno, on_delete=models.PROTECT, related_name='inscripciones', verbose_name='Estudiante')
    ciclo = models.ForeignKey(CicloEscolar, on_delete=models.PROTECT, related_name='inscripciones')
    grado = models.ForeignKey(Grado, on_delete=models.PROTECT, related_name='inscripciones')
    fecha_inscripcion = models.DateField(default=timezone.localdate, verbose_name='Fecha de inscripción')
    activa = models.BooleanField(default=True, verbose_name='Activa')
    # Se desactivó sola al dar de baja al estudiante: al reactivarlo vuelve a estar activa. Una inscripción que se dio de
    # baja a mano (desde Inscripciones) no lleva esta marca y no se reactiva con él.
    suspendida_por_baja = models.BooleanField(default=False, editable=False, verbose_name='Desactivada por la baja del estudiante')

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
                    'El estudiante ya tiene una inscripción activa '
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
    """Una materia la imparte un solo grado (`grado`): solo se agrega al plan de ese grado, ciclo tras ciclo.

    `grado` vacío queda solo en materias registradas antes de esta regla que todavía no tienen el suyo; se les elige al
    editarlas o al agregarlas por primera vez al plan de un grado.
    """

    clave = models.CharField(max_length=20, unique=True, verbose_name='Clave')
    nombre = models.CharField(max_length=100, verbose_name='Nombre')
    grado = models.ForeignKey(
        'Grado', null=True, blank=True, on_delete=models.PROTECT, related_name='materias', verbose_name='Grado',
    )
    activa = models.BooleanField(default=True, verbose_name='Activa')

    def __str__(self):
        return self.nombre

    def get_absolute_url(self):
        return reverse('materias:detalle', args=[self.pk])

    class Meta:
        verbose_name = 'Materia'
        verbose_name_plural = 'Materias'
        ordering = ['nombre']


class MateriaGrado(models.Model):

    ciclo = models.ForeignKey(CicloEscolar, on_delete=models.PROTECT, related_name='materias_grado')
    grado = models.ForeignKey(Grado, on_delete=models.PROTECT, related_name='materias_grado')
    materia = models.ForeignKey(Materia, on_delete=models.PROTECT, related_name='grados_materia')
    profesor = models.ForeignKey(
        'Profesor', null=True, blank=True, on_delete=models.PROTECT, related_name='asignaciones',
        verbose_name='Profesor',
    )
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

    ORIGEN_CHOICES = [
        ('UID', 'Credencial (UID)'),
        ('REFERENCIA', 'Número de referencia'),
        ('MANUAL', 'Captura manual'),
        ('CIERRE', 'Cierre del día'),
    ]

    inscripcion = models.ForeignKey(Inscripcion, on_delete=models.CASCADE, related_name='asistencias_generales')
    fecha = models.DateField(verbose_name='Fecha')
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default='PRESENTE', verbose_name='Estado')
    hora_entrada = models.TimeField(null=True, blank=True, verbose_name='Hora de entrada')
    origen = models.CharField(max_length=12, choices=ORIGEN_CHOICES, default='MANUAL', verbose_name='Origen')
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
        verbose_name='Registrado por',
    )
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

    ORIGEN_CHOICES = [
        ('ENTRADA', 'Entrada del estudiante'),
        ('PASE', 'Pase de lista'),
        ('MANUAL', 'Captura manual'),
        ('CIERRE', 'Cierre del día'),
    ]

    inscripcion = models.ForeignKey(Inscripcion, on_delete=models.CASCADE, related_name='asistencias_materias')
    materia_grado = models.ForeignKey(MateriaGrado, on_delete=models.PROTECT, related_name='asistencias')
    fecha = models.DateField(verbose_name='Fecha')
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default='PRESENTE', verbose_name='Estado')
    origen = models.CharField(max_length=10, choices=ORIGEN_CHOICES, default='PASE', verbose_name='Origen')
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
        verbose_name='Registrado por',
    )
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
                'La materia no pertenece al grado del estudiante.'
            )

        if (
            self.inscripcion.ciclo_id
            != self.materia_grado.ciclo_id
        ):
            raise ValidationError(
                'La materia no pertenece al ciclo escolar '
                'de la inscripción del estudiante.'
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
    activa = models.BooleanField(default=True, verbose_name='Vigente')
    registrada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
        verbose_name='Registrada por',
    )
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
            # Una justificación vigente por alumno y día; las anuladas se conservan como historial
            models.UniqueConstraint(
                fields=[
                    'inscripcion',
                    'fecha'
                ],
                condition=models.Q(activa=True),
                name='justificacion_alumno_fecha_unica'
            )
        ]


class ConfiguracionAsistencia(models.Model):
    """Reglas del control de asistencia del colegio. Hay un solo registro (`cargar()` lo crea si falta)."""

    hora_entrada = models.TimeField(default=time(8, 0), verbose_name='Hora de entrada')
    tolerancia_minutos = models.PositiveSmallIntegerField(
        default=10, validators=[MaxValueValidator(120)], verbose_name='Tolerancia (minutos)',
    )
    cierre_automatico = models.BooleanField(default=True, verbose_name='Cerrar automáticamente los días anteriores')

    @classmethod
    def cargar(cls):
        configuracion, _ = cls.objects.get_or_create(pk=1)
        return configuracion

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Entrada {self.hora_entrada:%H:%M} (tolerancia de {self.tolerancia_minutos} min)"

    class Meta:
        verbose_name = 'Configuración de asistencia'
        verbose_name_plural = 'Configuración de asistencia'


class DiaNoLectivo(models.Model):
    """Un día sin clases (asueto, suspensión, vacaciones): no se registra entrada ni se generan faltas."""

    fecha = models.DateField(unique=True, verbose_name='Fecha')
    motivo = models.CharField(max_length=120, verbose_name='Motivo')
    creado = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.fecha} - {self.motivo}"

    class Meta:
        verbose_name = 'Día sin clases'
        verbose_name_plural = 'Días sin clases'
        ordering = ['fecha']


class CierreDia(models.Model):
    """Marca que un día de clases ya se cerró: a quien no registró entrada se le generó la falta."""

    fecha = models.DateField(unique=True, verbose_name='Fecha')
    cerrado_en = models.DateTimeField(default=timezone.now, verbose_name='Cerrado el')
    cerrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
        verbose_name='Cerrado por',
    )
    automatico = models.BooleanField(default=False, verbose_name='Cierre automático')
    faltas = models.PositiveIntegerField(default=0, verbose_name='Faltas generadas')

    def __str__(self):
        return f"Cierre del {self.fecha}"

    class Meta:
        verbose_name = 'Cierre de día'
        verbose_name_plural = 'Cierres de día'
        ordering = ['-fecha']


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
    # Acceso al sistema (para lo que se construya después, como un portal de tutores). El usuario se genera con su nombre
    # si no se escribe; la contraseña se guarda cifrada para verificarla y legible para que un administrador la consulte.
    usuario = models.CharField(max_length=40, unique=True, null=True, blank=True, verbose_name='Usuario')
    contrasena = models.CharField(max_length=128, blank=True, default='', verbose_name='Contraseña')
    contrasena_visible = models.CharField(max_length=64, blank=True, default='', editable=False, verbose_name='Contraseña (consulta)')
    creado = models.DateTimeField( auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    def __str__(self):
        return (
            f"{self.nombre} "
            f"{self.apellido_paterno} "
            f"{self.apellido_materno}"
        ).strip()

    def save(self, *args, **kwargs):
        # Todo tutor tiene usuario, se registre desde donde se registre (su formulario, el alta de un estudiante, una
        # importación o el admin de Django)
        if not self.usuario:
            from .utils import usuario_disponible
            self.usuario = usuario_disponible(self.nombre, self.apellido_paterno, excluir=self.pk)
            if kwargs.get('update_fields') is not None:
                kwargs['update_fields'] = {*kwargs['update_fields'], 'usuario'}
        super().save(*args, **kwargs)

    def establecer_contrasena(self, contrasena):
        """Asigna la contraseña (cifrada para verificarla y legible para consulta). No guarda el registro."""
        self.contrasena = make_password(contrasena)
        self.contrasena_visible = contrasena

    @property
    def nombre_completo(self):
        return str(self)

    @property
    def iniciales(self):
        return (self.nombre[:1] + self.apellido_paterno[:1]).upper()

    def get_absolute_url(self):
        return reverse('tutores:detalle', args=[self.pk])

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
    alumno = models.ForeignKey(Alumno,on_delete=models.CASCADE,related_name='tutores_relacionados', verbose_name='Estudiante')
    parentesco = models.CharField(max_length=20,choices=PARENTESCO_CHOICES,verbose_name='Parentesco')
    tutor_principal = models.BooleanField( default=False,verbose_name='Tutor principal')
    contacto_emergencia = models.BooleanField(default=False,verbose_name='Contacto de emergencia')
    autorizado_recoger = models.BooleanField(default=False,verbose_name='Autorizado para recoger al estudiante')
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
        verbose_name = 'Tutor del estudiante'
        verbose_name_plural = 'Tutores de estudiantes'

        constraints = [
            models.UniqueConstraint(
                fields=[
                    'tutor',
                    'alumno'
                ],
                name='tutor_alumno_unico'
            )
        ]


class Profesor(models.Model):

    ESTATUS_CHOICES = [
        ('ACTIVO', 'Activo'),
        ('INACTIVO', 'Inactivo'),
    ]

    nombre = models.CharField(max_length=80, verbose_name='Nombre')
    apellido_paterno = models.CharField(max_length=60, verbose_name='Apellido paterno')
    apellido_materno = models.CharField(max_length=60, blank=True, verbose_name='Apellido materno')
    curp = models.CharField(max_length=18, unique=True, null=True, blank=True, verbose_name='CURP')
    fecha_nacimiento = models.DateField(null=True, blank=True, verbose_name='Fecha de nacimiento')
    telefono = models.CharField(max_length=20, verbose_name='Teléfono')
    telefono_alternativo = models.CharField(max_length=20, blank=True, verbose_name='Teléfono alternativo')
    correo_electronico = models.EmailField(max_length=254, blank=True, null=True, unique=True, verbose_name='Correo electrónico')
    domicilio = models.CharField(max_length=200, blank=True, verbose_name='Domicilio')
    colonia = models.CharField(max_length=100, blank=True, verbose_name='Colonia')
    ciudad = models.CharField(max_length=100, blank=True, verbose_name='Ciudad')
    estado = models.CharField(max_length=100, blank=True, verbose_name='Estado')
    cp = models.CharField(
        max_length=5, blank=True, verbose_name='Código postal',
        validators=[RegexValidator(regex=r'^\d{5}$', message='El código postal debe contener exactamente 5 dígitos.')],
    )
    profesion = models.CharField(max_length=150, blank=True, verbose_name='Profesión o título')
    cedula_profesional = models.CharField(max_length=20, blank=True, verbose_name='Cédula profesional')
    especialidad = models.CharField(max_length=150, blank=True, verbose_name='Especialidad o áreas que imparte')
    fecha_ingreso = models.DateField(null=True, blank=True, verbose_name='Fecha de ingreso al colegio')
    horas_maximas = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name='Horas máximas por semana',
        help_text='Opcional. Sirve para avisar cuando su carga de clases la rebasa.',
    )
    observaciones = models.TextField(blank=True, verbose_name='Observaciones')
    estatus = models.CharField(max_length=20, choices=ESTATUS_CHOICES, default='ACTIVO', verbose_name='Estatus')
    # Una sola cuenta por profesor y un solo profesor por cuenta: la cuenta guarda el acceso (usuario, contraseña, rol y
    # permisos); aquí solo vive la información del docente
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='profesor',
        verbose_name='Cuenta de acceso',
        help_text='La cuenta con la que entra al sistema. Lo que puede hacer lo define el rol de esa cuenta.',
    )
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.nombre} {self.apellido_paterno} {self.apellido_materno}".strip()

    @property
    def nombre_completo(self):
        return str(self)

    @property
    def apellidos(self):
        return f'{self.apellido_paterno} {self.apellido_materno}'.strip()

    @property
    def niveles_lista(self):
        """Los códigos de sus niveles en orden escolar (['PRIMARIA', 'SECUNDARIA']). Usa lo precargado si lo hay."""
        codigos = {nivel.nivel for nivel in self.niveles.all()}
        return [codigo for codigo in ORDEN_NIVELES if codigo in codigos]

    @property
    def niveles_texto(self):
        """«Primaria, Secundaria» (vacío si no tiene)."""
        nombres = dict(Grado.NIVEL_CHOICES)
        return ', '.join(nombres[codigo] for codigo in self.niveles_lista)

    def establecer_niveles(self, codigos):
        """Deja exactamente esos niveles (los que sobran se quitan, los que faltan se agregan)."""
        codigos = set(codigos)
        self.niveles.exclude(nivel__in=codigos).delete()
        actuales = set(self.niveles.values_list('nivel', flat=True))
        ProfesorNivel.objects.bulk_create([ProfesorNivel(profesor=self, nivel=codigo) for codigo in codigos - actuales])

    @property
    def iniciales(self):
        return (self.nombre[:1] + self.apellido_paterno[:1]).upper()

    def get_absolute_url(self):
        return reverse('profesores:detalle', args=[self.pk])

    class Meta:
        verbose_name = 'Profesor'
        verbose_name_plural = 'Profesores'
        ordering = [
            'apellido_paterno',
            'apellido_materno',
            'nombre'
        ]


class ProfesorNivel(models.Model):
    """Un nivel escolar en el que el profesor da clases (preescolar, primaria, secundaria o preparatoria).

    Un profesor puede estar en varios. Sirve para ubicarlo (listado, filtro, perfil) y limita lo que se le asigna: solo
    imparte materias de grados de sus niveles (ver Alumnos.docentes.asignar_profesor).
    """
    profesor = models.ForeignKey(Profesor, on_delete=models.CASCADE, related_name='niveles')
    nivel = models.CharField(max_length=20, choices=Grado.NIVEL_CHOICES, verbose_name='Nivel')

    def __str__(self):
        return f'{self.profesor} · {self.get_nivel_display()}'

    class Meta:
        verbose_name = 'Nivel en el que da clases'
        verbose_name_plural = 'Niveles en los que da clases'
        constraints = [
            models.UniqueConstraint(fields=['profesor', 'nivel'], name='profesor_nivel_unico'),
        ]


class ProfesorMateria(models.Model):
    """Una materia que el profesor puede impartir (su habilitación).

    Es independiente del ciclo y del grado: dice qué sabe y quiere dar. Quién la imparte de verdad en cada grupo y ciclo
    es `MateriaGrado.profesor`; la habilitación solo sirve para sugerir a los profesores adecuados al asignar.
    """
    profesor = models.ForeignKey(Profesor, on_delete=models.CASCADE, related_name='habilitaciones')
    materia = models.ForeignKey(Materia, on_delete=models.CASCADE, related_name='habilitaciones')
    creado = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.profesor} · {self.materia}'

    class Meta:
        verbose_name = 'Materia que puede impartir'
        verbose_name_plural = 'Materias que puede impartir'
        ordering = ['materia__nombre']
        constraints = [
            models.UniqueConstraint(fields=['profesor', 'materia'], name='profesor_materia_unica'),
        ]

