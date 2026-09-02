from django.db import models

# Create your models here.
from datetime import date

from django.contrib.auth.hashers import make_password, check_password
from django.core.validators import RegexValidator
from django.db import models


class Alumno(models.Model):
    # ==============================
    # OPCIONES
    # ==============================

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

    # ==============================
    # IDENTIFICACIÓN
    # ==============================

    referencia = models.CharField(max_length=20, unique=True, verbose_name='Referencia')
    nombre = models.CharField(max_length=80, verbose_name='Nombre')
    apellido_paterno = models.CharField(max_length=60, verbose_name='Apellido paterno')
    apellido_materno = models.CharField(max_length=60, blank=True, verbose_name='Apellido materno')
    curp = models.CharField(max_length=18, unique=True, verbose_name='CURP')

    # ==============================
    # DATOS PERSONALES
    # ==============================

    nacionalidad = models.CharField(max_length=50, default='Mexicana', verbose_name='Nacionalidad')
    sexo = models.CharField(max_length=1, choices=SEXO_CHOICES, verbose_name='Sexo')
    fecha_nacimiento = models.DateField(verbose_name='Fecha de nacimiento')
    grupo_sanguineo = models.CharField(max_length=3, choices=GRUPO_SANGUINEO_CHOICES, verbose_name='Grupo sanguíneo')
    religion = models.CharField(max_length=80, blank=True, verbose_name='Religión')
    alergias = models.TextField(blank=True, verbose_name='Alergias')

    # ==============================
    # DOMICILIO
    # ==============================

    domicilio = models.CharField(max_length=200, verbose_name='Domicilio')
    colonia = models.CharField(max_length=100, verbose_name='Colonia')
    ciudad = models.CharField(max_length=100, verbose_name='Ciudad')
    estado = models.CharField(max_length=100, verbose_name='Estado')
    cp = models.CharField(max_length=5, validators=[
        RegexValidator(regex=r'^\d{5}$', message='El código postal debe contener exactamente 5 dígitos.')],
                          verbose_name='Código postal')
    # ==============================
    # DATOS ESCOLARES
    # ==============================
    fecha_ingreso = models.DateField(default=date.today, verbose_name='Fecha de ingreso')
    escuela_procedencia = models.CharField(max_length=200, blank=True, verbose_name='Escuela de procedencia')
    observaciones_generales = models.TextField(blank=True, verbose_name='Observaciones generales')
    # ==============================
    # FOTO
    # ==============================
    fotografia= models.ImageField(upload_to='alumnos/', blank=True, null=True)
    # ==============================
    # CONTACTO / ACCESO
    # ==============================
    correo_electronico = models.EmailField(max_length=254, unique=True, null=True, blank=True,
                                           verbose_name='Correo electrónico')
    contrasena = models.CharField(max_length=128, verbose_name='Contraseña')
    # ==============================
    # ESTADO
    # ==============================
    estatus = models.CharField(max_length=20, choices=ESTATUS_CHOICES, default='ACTIVO', verbose_name='Estatus')

    # ==============================
    # MÉTODOS
    # ==============================
    def establecer_contrasena(self, contrasena_plana):
        """
        Guarda la contraseña utilizando hash seguro.
        """
        self.contrasena = make_password(contrasena_plana)

    def verificar_contrasena(self, contrasena_plana):
        """
        Comprueba si la contraseña proporcionada es correcta.
        """
        return check_password(
            contrasena_plana,
            self.contrasena
        )

    def save(self, *args, **kwargs):
        # CURP siempre en mayúsculas
        if self.curp:
            self.curp = self.curp.upper()

        # Referencia siempre en mayúsculas
        if self.referencia:
            self.referencia = self.referencia.upper()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nombre} {self.apellido_paterno} {self.apellido_materno}".strip()

    class Meta:
        verbose_name = 'Alumno'
        verbose_name_plural = 'Alumnos'
        ordering = [
            'apellido_paterno',
            'apellido_materno',
            'nombre'
        ]
        db_table = 'alumnos'
