from datetime import date, time

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
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
    # Portal (pedido del 2026-10-14): el estudiante entra con su correo electrónico y su contraseña. Se puede desactivar sin cambiar
    # su estatus; tras varios intentos fallidos se bloquea un rato (CISAHUAYO/portales.py).
    acceso_portal = models.BooleanField(default=True, verbose_name='Acceso al portal')
    ultimo_acceso = models.DateTimeField(null=True, blank=True, editable=False, verbose_name='Último acceso al portal')
    intentos_fallidos = models.PositiveSmallIntegerField(default=0, editable=False, verbose_name='Intentos fallidos')
    bloqueado_hasta = models.DateTimeField(null=True, blank=True, editable=False, verbose_name='Bloqueado hasta')

    def __str__(self):
        return (
            f"{self.nombre} "
            f"{self.apellido_paterno} "
            f"{self.apellido_materno}"
        ).strip()

    def establecer_contrasena(self, contrasena):
        """Asigna la contraseña (cifrada para verificarla y legible para consulta) y quita el bloqueo del portal por
        intentos fallidos. No guarda el registro."""
        self.contrasena = make_password(contrasena)
        self.contrasena_visible = contrasena
        self.intentos_fallidos, self.bloqueado_hasta = 0, None

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


CICLO_ACTUAL, CICLO_PROXIMO, CICLO_CERRADO = 'ACTUAL', 'PROXIMO', 'CERRADO'
NOMBRES_DE_ESTADO_DE_CICLO = {CICLO_ACTUAL: 'Actual', CICLO_PROXIMO: 'Próximo', CICLO_CERRADO: 'Cerrado'}


def q_ciclo(estado, campo='', hoy=None):
    """La regla del estado de un ciclo, en un solo lugar (la usan la propiedad `estado`, los filtros y los conteos).

    - ACTUAL: el marcado como actual (solo hay uno).
    - CERRADO: el que se cerró (`cerrado_en`) o el que terminó sin haberse marcado nunca como actual.
    - PROXIMO: los demás, aunque ya haya llegado su fecha de inicio: todavía no se activan (`por_activar`).
    - VIGENTE: el actual y los próximos (en ellos se inscribe y se arma el plan).

    `campo` es la ruta al ciclo desde otro modelo, por ejemplo 'ciclo__' desde una inscripción.
    """
    hoy = hoy or timezone.localdate()
    actual = models.Q(**{f'{campo}activo': True})
    proximo = models.Q(**{f'{campo}activo': False, f'{campo}cerrado_en__isnull': True, f'{campo}fecha_fin__gte': hoy})
    reglas = {CICLO_ACTUAL: actual, CICLO_PROXIMO: proximo, 'VIGENTE': actual | proximo}
    return reglas[estado] if estado in reglas else ~(actual | proximo)


class CicloQuerySet(models.QuerySet):
    def actuales(self):
        return self.filter(q_ciclo(CICLO_ACTUAL))

    def proximos(self):
        return self.filter(q_ciclo(CICLO_PROXIMO))

    def cerrados(self):
        return self.filter(q_ciclo(CICLO_CERRADO))

    def vigentes(self):
        """El actual y los próximos: en ellos se inscribe y se cambian el plan de materias y los horarios."""
        return self.filter(q_ciclo('VIGENTE'))


class CicloEscolar(models.Model):
    """Un ciclo escolar. Se marca como actual y se cierra con sus botones (Ciclos escolares), que guardan quién y
    cuándo; solo puede haber un ciclo actual (restricción en la base)."""

    nombre = models.CharField(max_length=30, unique=True, verbose_name='Ciclo escolar')
    fecha_inicio = models.DateField(verbose_name='Fecha de inicio')
    fecha_fin = models.DateField(verbose_name='Fecha de fin')
    activo = models.BooleanField(default=False, verbose_name='Es el ciclo actual')
    activado_en = models.DateTimeField(null=True, blank=True, verbose_name='Marcado como actual el')
    activado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
        verbose_name='Marcado como actual por',
    )
    cerrado_en = models.DateTimeField(null=True, blank=True, verbose_name='Cerrado el')
    cerrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='Cerrado por',
    )

    objects = CicloQuerySet.as_manager()

    def clean(self):
        if (
            self.fecha_inicio
            and self.fecha_fin
            and self.fecha_inicio >= self.fecha_fin
        ):
            raise ValidationError(
                'La fecha de inicio debe ser anterior a la fecha de fin.'
            )
        otros = CicloEscolar.objects.exclude(pk=self.pk)
        if self.fecha_inicio and self.fecha_fin:
            otro = otros.filter(fecha_inicio__lte=self.fecha_fin, fecha_fin__gte=self.fecha_inicio).order_by('fecha_inicio').first()
            if otro:
                raise ValidationError({'fecha_inicio': (
                    f'Las fechas se empalman con el ciclo {otro.nombre} '
                    f'({otro.fecha_inicio:%d/%m/%Y} al {otro.fecha_fin:%d/%m/%Y}).'
                )})
        if self.activo:
            otro = otros.filter(activo=True).first()
            if otro:
                raise ValidationError(
                    f'El ciclo {otro} ya es el ciclo actual: solo puede haber uno. Usa «Establecer como ciclo actual».'
                )

    def __str__(self):
        return self.nombre

    def get_absolute_url(self):
        return reverse('ciclos:detalle', args=[self.pk])

    @property
    def estado(self):
        """ACTUAL, PROXIMO o CERRADO (la regla está en `q_ciclo`)."""
        if self.activo:
            return CICLO_ACTUAL
        if self.cerrado_en is not None or self.fecha_fin < timezone.localdate():
            return CICLO_CERRADO
        return CICLO_PROXIMO

    @property
    def estado_display(self):
        return NOMBRES_DE_ESTADO_DE_CICLO[self.estado]

    @property
    def por_activar(self):
        """Ya llegó su fecha de inicio pero nadie lo ha marcado como actual (sigue como próximo)."""
        return self.estado == CICLO_PROXIMO and self.fecha_inicio <= timezone.localdate()

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
        constraints = [
            models.UniqueConstraint(fields=['activo'], condition=models.Q(activo=True), name='un_solo_ciclo_actual'),
        ]


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


def q_grado_disponible(prefijo=''):
    """La condición de un grado que se ofrece para algo nuevo (inscribir, armar el plan, elegirlo en un formulario): activo
    (no dado de baja) y visible en el sistema (2026-10-28). `prefijo` es la ruta al grado desde otro modelo ('grado__',
    'grupo__grado__').

    Solo para las opciones: los registros que ya tienen el grado (inscripciones, calificaciones, historial) se consultan
    sin ella y conservan su nombre aunque esté oculto.
    """
    return models.Q(**{f'{prefijo}activo': True, f'{prefijo}visible': True})


class GradoQuerySet(models.QuerySet):
    def academicos(self):
        """Orden escolar: por nivel (preescolar a preparatoria) y, dentro de cada nivel, por número."""
        return self.order_by(orden_de_nivel(), 'numero')

    def disponibles(self):
        """Los que se pueden elegir para algo nuevo: activos y visibles (ver `q_grado_disponible`)."""
        return self.filter(q_grado_disponible())

    def visibles(self):
        """Sin los ocultos: para los filtros que también ofrecen los dados de baja (para consultar su historial)."""
        return self.filter(visible=True)

    def niveles(self):
        """Los niveles que tienen alguno de estos grados (un conjunto)."""
        return set(self.order_by().values_list('nivel', flat=True).distinct())


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
    # Mostrar u ocultar sin dar de baja (2026-10-28): en bachillerato, los grados del semestre A o los del B. Oculto, no
    # se ofrece en ninguna lista, selector ni filtro del sitio, pero sus grupos, inscripciones y registros quedan intactos.
    visible = models.BooleanField(
        default=True, verbose_name='Visible en el sistema',
        help_text='Oculto, no se ofrece como opción en ninguna parte del sitio; sus registros se conservan y se siguen consultando.',
    )
    equivalencia = models.CharField(
        max_length=8, blank=True, default='', verbose_name='Equivalencia',
        help_text='Cómo se nombra el grado en la continuidad escolar, sin importar el nivel: un número (1.º de secundaria '
                  'equivale al 7.º) o un código con letras (K1 para 1.º de preescolar).',
    )

    objects = GradoQuerySet.as_manager()

    def __str__(self):
        """Su nombre en todo el sitio: la equivalencia en la continuidad escolar («7.º», «K1»; pedido del 2026-10-20). Sin
        ninguna, el de su nivel («1.º Secundaria»)."""
        return self.nombre_equivalente

    @property
    def disponible(self):
        """Se puede elegir para algo nuevo: activo y visible (ver `q_grado_disponible`)."""
        return self.activo and self.visible

    @property
    def tiene_historial(self):
        """Ya tiene inscripciones o un plan de materias (de cualquier ciclo): su nivel y su número ya no se cambian."""
        return self.pk is not None and (self.inscripciones.exists() or self.materias_grado.exists())

    def clean(self):
        """Las reglas del grado, también para el admin de Django (2026-10-26):

        - el número dentro del límite de su nivel y sin repetir el grado;
        - el nivel y el número no cambian si ya tiene historial (moverían inscripciones, periodos, días sin clases,
          habilitaciones, alcances y la promoción): solo se corrigen mientras esté vacío;
        - la equivalencia: sin escribir, la habitual; con formato válido y sin repetirse entre los grados activos (la
          efectiva: la guardada o la habitual).

        Los errores van en su campo; así la validación de las restricciones de la base no los repite.
        """
        from .academico import FORMATO_EQUIVALENCIA, LIMITE_GRADOS, equivalencia_sugerida, normalizar_equivalencia
        errores = {}
        nombre = dict(self.NIVEL_CHOICES).get(self.nivel, '')
        if self.nivel and self.numero is not None:   # el 0 también debe validarse
            limite = LIMITE_GRADOS[self.nivel]
            if not 1 <= self.numero <= limite:
                errores['numero'] = f'En {nombre.lower()} los grados van del 1.º al {limite}.º.'
            elif Grado.objects.filter(nivel=self.nivel, numero=self.numero).exclude(pk=self.pk).exists():
                errores['numero'] = f'Ya existe el grado {self.numero}.º {nombre}.'
        if self.pk is not None and 'numero' not in errores:
            guardado = Grado.objects.filter(pk=self.pk).values('nivel', 'numero').first()
            if guardado and (guardado['nivel'], guardado['numero']) != (self.nivel, self.numero) and self.tiene_historial:
                errores['nivel'] = (
                    'El nivel y el número ya no se pueden cambiar: el grado tiene inscripciones o un plan de materias, y '
                    'cambiarlos movería todo su historial. Si se registró mal, da de baja este grado y crea el correcto.'
                )

        self.equivalencia = normalizar_equivalencia(self.equivalencia) or equivalencia_sugerida(self.nivel, self.numero)
        if self.equivalencia and not FORMATO_EQUIVALENCIA.match(self.equivalencia):
            errores['equivalencia'] = 'Usa solo letras y números, sin símbolos (7, 10, K1).'
        elif self.equivalencia and self.activo and 'numero' not in errores:   # un grado repetido ya tiene su aviso
            otro = next(
                (g for g in Grado.objects.filter(activo=True).exclude(pk=self.pk) if g.equivalencia_efectiva == self.equivalencia),
                None,
            )
            if otro is not None:
                texto = Grado(equivalencia=self.equivalencia).equivalencia_texto
                errores['equivalencia'] = f'La equivalencia {texto} ya la tiene {otro.nombre_de_nivel}: cada grado tiene la suya.'
        if errores:
            raise ValidationError(errores)

    def save(self, *args, **kwargs):
        # La equivalencia siempre queda guardada (sin escribir, la habitual): la que se ve es la que se valida
        if not self.equivalencia and self.nivel and self.numero:
            from .academico import equivalencia_sugerida
            self.equivalencia = equivalencia_sugerida(self.nivel, self.numero)
            if kwargs.get('update_fields') is not None:
                kwargs['update_fields'] = {*kwargs['update_fields'], 'equivalencia'}
        super().save(*args, **kwargs)

    @property
    def nombre_de_nivel(self):
        """«1.º Secundaria»: el grado dentro de su nivel. Lo usan Grados (donde se configura la equivalencia) y las
        descripciones emergentes junto a la equivalencia."""
        return f"{self.numero}.º {self.get_nivel_display()}"

    @property
    def numero_ordinal(self):
        """«1.º»: el número del grado con el indicador ordinal."""
        return f'{self.numero}.º'

    @property
    def semestre(self):
        """El semestre del ciclo en que se cursa ('A' o 'B'), o None fuera de preparatoria (ver `semestre_de_grado`)."""
        return semestre_de_grado(self.nivel, self.numero)

    @property
    def equivalencia_numero(self):
        """La equivalencia (efectiva) como número (7); None si no tiene o es un código con letras (K1)."""
        valor = str(self.equivalencia_efectiva or '')
        return int(valor) if valor.isdigit() else None

    @property
    def equivalencia_texto(self):
        """«7.º» si la equivalencia (efectiva) es un número, el código tal cual («K1») si lleva letras; vacío si no
        tiene ninguna."""
        codigo = self.equivalencia_efectiva
        if not codigo:
            return ''
        return f'{self.equivalencia_numero}.º' if self.equivalencia_numero is not None else str(codigo)

    @property
    def equivalencia_efectiva(self):
        """La equivalencia guardada o, si no tiene, la habitual de su nivel («7», «K1»); vacío si no hay ninguna."""
        from .academico import equivalencia_sugerida
        return self.equivalencia or equivalencia_sugerida(self.nivel, self.numero)

    @property
    def nombre_equivalente(self):
        """Cómo se nombra en la continuidad escolar: «7.º» o «K1» (la equivalencia efectiva); sin ninguna, el de su nivel
        («1.º Secundaria»)."""
        codigo = str(self.equivalencia_efectiva)
        if not codigo:
            return self.nombre_de_nivel
        return f'{codigo}.º' if codigo.isdigit() else codigo

    @property
    def equivalencia_frase(self):
        """«Equivale al 7.º» o «Equivale a K1» (la equivalencia efectiva); vacío si no tiene ninguna."""
        if not self.equivalencia_texto:
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
            ),
            # Dos grados activos no se nombran igual («7.º» junto a otro «7.º»)
            models.UniqueConstraint(
                fields=['equivalencia'], condition=models.Q(activo=True) & ~models.Q(equivalencia=''),
                name='equivalencia_unica_entre_grados_activos',
            ),
        ]


# ---------------------------------------------------------------------------
# Grupos: cada grado tiene uno o varios (1.º A, 1.º B)
# ---------------------------------------------------------------------------
class NombreGrupo(models.Model):
    """El catálogo de nombres de grupo que usa el colegio («A», «B», «Matutino»…). Renombrar uno renombra los grupos que
    lo usan; uno dado de baja ya no se ofrece al crear grupos, pero los que ya lo tienen lo conservan."""

    NOMBRE_INICIAL = 'A'

    nombre = models.CharField(max_length=20, unique=True, verbose_name='Nombre')
    orden = models.PositiveSmallIntegerField(default=0, verbose_name='Orden')
    activo = models.BooleanField(default=True, verbose_name='Activo')

    def __str__(self):
        return self.nombre

    @classmethod
    def inicial(cls):
        """El nombre que recibe el grupo de un grado que todavía no tiene ninguno: el primero activo o «A»."""
        primero = cls.objects.filter(activo=True).order_by('orden', 'nombre').first()
        if primero is not None:
            return primero
        nombre, _ = cls.objects.get_or_create(nombre=cls.NOMBRE_INICIAL)
        return nombre

    class Meta:
        verbose_name = 'Nombre de grupo'
        verbose_name_plural = 'Nombres de grupo'
        ordering = ['orden', 'nombre']


class GrupoQuerySet(models.QuerySet):
    def academicos(self):
        """Orden escolar: por nivel, por número de grado y por el orden del nombre (A, B…)."""
        return self.order_by(orden_de_nivel('grado__nivel'), 'grado__numero', 'nombre__orden', 'nombre__nombre')

    def disponibles(self):
        """Los que se pueden elegir para algo nuevo: activos y de un grado disponible (activo y visible)."""
        return self.filter(q_grado_disponible('grado__'), activo=True)


class Grupo(models.Model):
    """Un grupo de un grado (1.º A, 1.º B): su salón. Los estudiantes se inscriben en un grupo; el plan de materias es del
    grado y lo comparten sus grupos, pero cada grupo tiene su profesor en cada materia, su horario y sus recesos."""

    grado = models.ForeignKey(Grado, on_delete=models.CASCADE, related_name='grupos', verbose_name='Grado')
    nombre = models.ForeignKey(NombreGrupo, on_delete=models.PROTECT, related_name='grupos', verbose_name='Grupo')
    activo = models.BooleanField(default=True, verbose_name='Activo')

    objects = GrupoQuerySet.as_manager()

    def __str__(self):
        """Su nombre en todo el sitio: «7.º A» o «K3 B», con la equivalencia del grado (pedido del 2026-10-20)."""
        return self.nombre_equivalente

    @property
    def nombre_de_nivel(self):
        """«1.º A Secundaria»: el grupo dentro de su nivel (para las descripciones emergentes junto a la equivalencia)."""
        return f'{self.grado.numero}.º {self.nombre} {self.grado.get_nivel_display()}'

    @property
    def corto(self):
        """Sin el nivel: «7.º A» (o, si el grado no tiene equivalencia, «1.º A»)."""
        if not self.grado.equivalencia_efectiva:
            return f'{self.grado.numero}.º {self.nombre}'
        return self.nombre_equivalente

    @property
    def nombre_equivalente(self):
        """«7.º A» o «K3 B»: la equivalencia del grado en la continuidad escolar con el grupo; sin equivalencia, el de su
        nivel («1.º A Secundaria»)."""
        if not self.grado.equivalencia_efectiva:
            return self.nombre_de_nivel
        return f'{self.grado.nombre_equivalente} {self.nombre}'

    @classmethod
    def principal_de(cls, grado):
        """El primer grupo activo del grado; si todavía no tiene ninguno, se le crea uno con el nombre inicial. Lo usa
        lo que solo conoce el grado (y para un grado de un solo grupo, es su grupo)."""
        grupo = cls.objects.filter(grado=grado, activo=True).order_by('nombre__orden', 'nombre__nombre').first()
        if grupo is None:
            grupo = cls.objects.filter(grado=grado).order_by('nombre__orden', 'nombre__nombre').first()
        if grupo is None:
            grupo = cls.objects.create(grado=grado, nombre=NombreGrupo.inicial())
        return grupo

    def get_absolute_url(self):
        return reverse('grupos:detalle', args=[self.pk])

    class Meta:
        verbose_name = 'Grupo'
        verbose_name_plural = 'Grupos'
        constraints = [
            models.UniqueConstraint(fields=['grado', 'nombre'], name='grupo_grado_nombre_unico'),
        ]


def _con_grupo(registro):
    """Antes de guardar algo que es de un grupo (inscripción, materia del plan, receso): si solo trae el grado, va al
    grupo principal de ese grado; si trae el grupo, su grado es el del grupo."""
    if registro.grupo_id is None and registro.grado_id is not None:
        registro.grupo = Grupo.principal_de(registro.grado)
    elif registro.grupo_id is not None and registro.grado_id != registro.grupo.grado_id:
        registro.grado_id = registro.grupo.grado_id


class Inscripcion(models.Model):

    alumno = models.ForeignKey(Alumno, on_delete=models.PROTECT, related_name='inscripciones', verbose_name='Estudiante')
    ciclo = models.ForeignKey(CicloEscolar, on_delete=models.PROTECT, related_name='inscripciones')
    grado = models.ForeignKey(Grado, on_delete=models.PROTECT, related_name='inscripciones')
    grupo = models.ForeignKey(Grupo, on_delete=models.PROTECT, related_name='inscripciones', verbose_name='Grupo')
    fecha_inscripcion = models.DateField(default=timezone.localdate, verbose_name='Fecha de inscripción')
    activa = models.BooleanField(default=True, verbose_name='Activa')
    # Se desactivó sola al dar de baja al estudiante: al reactivarlo vuelve a estar activa. Una inscripción que se dio de
    # baja a mano (desde Inscripciones) no lleva esta marca y no se reactiva con él.
    suspendida_por_baja = models.BooleanField(default=False, editable=False, verbose_name='Desactivada por la baja del estudiante')
    # Preparatoria por semestres (2026-10-28): al pasar al semestre B del mismo ciclo, la inscripción del semestre A
    # deja de estar activa y queda concluida (no es una baja). Conserva su grupo, sus calificaciones y su historial, y
    # sigue en las listas de las materias de ese semestre (actas, exámenes extraordinarios y de regularización).
    concluida = models.BooleanField(default=False, editable=False, verbose_name='Semestre concluido')

    def __str__(self):
        return (
            f"{self.alumno} - "
            f"{self.grupo if self.grupo_id else self.grado} - "
            f"{self.ciclo}"
        )

    @property
    def estado_texto(self):
        """«Activa», «Semestre concluido» o «Baja»."""
        if self.activa:
            return 'Activa'
        return 'Semestre concluido' if self.concluida else 'Baja'

    def save(self, *args, **kwargs):
        _con_grupo(self)
        super().save(*args, **kwargs)

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
            # Una sola inscripción vigente (activa o dada de baja) por ciclo; las de semestres concluidos de preparatoria
            # quedan aparte, una por grado (2026-10-28)
            models.UniqueConstraint(fields=['alumno', 'ciclo'], condition=models.Q(concluida=False), name='alumno_ciclo_unico'),
            models.UniqueConstraint(fields=['alumno', 'ciclo', 'grado'], name='inscripcion_por_grado_unica'),
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
    grupo = models.ForeignKey(Grupo, on_delete=models.PROTECT, related_name='materias_grupo', verbose_name='Grupo')
    materia = models.ForeignKey(Materia, on_delete=models.PROTECT, related_name='grados_materia')
    profesor = models.ForeignKey(
        'Profesor', null=True, blank=True, on_delete=models.PROTECT, related_name='asignaciones',
        verbose_name='Profesor',
    )
    activa = models.BooleanField(default=True, verbose_name='Activa')
    # Se desactivó porque se quitó su grupo o se dio de baja su grado: vuelve (con su profesor y su horario) si el
    # grupo o el grado se reactivan mientras el ciclo siga vigente
    suspendida = models.BooleanField(default=False, verbose_name='Quitada con su grupo o su grado')

    def __str__(self):
        return (
            f"{self.materia} - "
            f"{self.grupo if self.grupo_id else self.grado} - "
            f"{self.ciclo}"
        )

    def save(self, *args, **kwargs):
        _con_grupo(self)
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = 'Materia del grado'
        verbose_name_plural = 'Materias del grado'

        ordering = [
            'grado',
            'materia__nombre'
        ]

        constraints = [
            models.UniqueConstraint(fields=['ciclo', 'grupo', 'materia'], name='materia_grupo_ciclo_unica'),
        ]

class HorarioActualManager(models.Manager):
    """Los bloques de la versión actual del horario (los que no se han cerrado con una fecha de fin)."""

    def get_queryset(self):
        return super().get_queryset().filter(vigente_hasta__isnull=True)


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

    # Semanas A y B (pedido del 2026-10-26): en los niveles con horario alternado cada bloque es de la semana A o de la
    # B; en los de horario fijo, de todas las semanas (''). Qué semana es una fecha: Alumnos/semanas.py
    TODAS, SEMANA_A, SEMANA_B = '', 'A', 'B'
    SEMANA_CHOICES = [(TODAS, 'Todas las semanas'), (SEMANA_A, 'Semana A'), (SEMANA_B, 'Semana B')]

    materia_grado = models.ForeignKey(MateriaGrado, on_delete=models.CASCADE, related_name='horarios')
    dia_semana = models.PositiveSmallIntegerField(choices=DIA_CHOICES, verbose_name='Día')
    hora_inicio = models.TimeField(verbose_name='Hora de inicio')
    hora_fin = models.TimeField(verbose_name='Hora de fin')
    semana = models.CharField(max_length=1, choices=SEMANA_CHOICES, default=TODAS, blank=True, verbose_name='Semana')
    # Versiones: un cambio con fecha de entrada en vigor cierra el bloque anterior (vigente_hasta) y crea otro desde esa
    # fecha, así el horario de cualquier fecha pasada se sigue consultando igual. Vacío = desde el inicio / sin fin.
    vigente_desde = models.DateField(null=True, blank=True, verbose_name='En vigor desde')
    vigente_hasta = models.DateField(null=True, blank=True, verbose_name='En vigor hasta')

    # `objects` (y `materia.horarios`) dan la versión actual de cada bloque: la que no se ha cerrado. Para el horario
    # de una fecha concreta, con las versiones de entonces, `historial` y Alumnos/semanas.py
    objects = HorarioActualManager()
    historial = models.Manager()

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

    @property
    def etiqueta_semana(self):
        """«Semana A», «Semana B» o '' (horario fijo)."""
        return self.get_semana_display() if self.semana else ''

    def vigente_en(self, fecha):
        return (self.vigente_desde is None or self.vigente_desde <= fecha) and (self.vigente_hasta is None or fecha <= self.vigente_hasta)

    class Meta:
        verbose_name = 'Horario de materia'
        verbose_name_plural = 'Horarios de materias'
        ordering = [
            'dia_semana',
            'hora_inicio'
        ]
        constraints = [
            # Solo entre los bloques actuales: las versiones cerradas pueden repetir día y hora. El mismo bloque puede
            # estar en la semana A y en la B
            models.UniqueConstraint(
                fields=[
                    'materia_grado',
                    'semana',
                    'dia_semana',
                    'hora_inicio',
                    'hora_fin'
                ],
                condition=models.Q(vigente_hasta__isnull=True),
                name='horario_materia_unico'
            )
        ]


class ConfiguracionHorario(models.Model):
    """Cómo se reparte el horario de un nivel en un ciclo: fijo (todas las semanas igual) o alternado A/B. Sin registro,
    el nivel tiene horario fijo. La secuencia es del nivel: todos sus grupos están en la misma semana."""

    FIJO, ALTERNADO = 'FIJO', 'ALTERNADO'
    MODALIDAD_CHOICES = [(FIJO, 'Horario fijo'), (ALTERNADO, 'Alternado: semana A y semana B')]
    # El horario alternado es para estos niveles (pedido del 2026-10-26); los demás siguen con horario fijo
    NIVELES_ALTERNABLES = ('PREESCOLAR', 'PRIMARIA')

    ciclo = models.ForeignKey(CicloEscolar, on_delete=models.CASCADE, related_name='configuraciones_horario', verbose_name='Ciclo escolar')
    nivel = models.CharField(max_length=20, choices=Grado.NIVEL_CHOICES, verbose_name='Nivel')
    modalidad = models.CharField(max_length=10, choices=MODALIDAD_CHOICES, default=FIJO, verbose_name='Modalidad')
    # La semana (de lunes a domingo) de esta fecha es la de `semana_referencia`; de ahí se alternan las demás
    fecha_referencia = models.DateField(null=True, blank=True, verbose_name='Fecha de referencia')
    semana_referencia = models.CharField(max_length=1, choices=HorarioMateria.SEMANA_CHOICES[1:], default=HorarioMateria.SEMANA_A,
                                         verbose_name='Esa semana es la')
    modificado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    modificado = models.DateTimeField(auto_now=True)

    @property
    def alternado(self):
        return self.modalidad == self.ALTERNADO and self.fecha_referencia is not None

    def __str__(self):
        return f'{self.get_nivel_display()} · {self.ciclo} · {self.get_modalidad_display()}'

    class Meta:
        verbose_name = 'Configuración de horario'
        verbose_name_plural = 'Configuraciones de horario'
        constraints = [models.UniqueConstraint(fields=['ciclo', 'nivel'], name='configuracion_horario_unica')]


class ExcepcionSemana(models.Model):
    """Una semana que no sigue la alternancia: solo esa semana cambia, o la alternancia vuelve a empezar desde ella."""

    SOLO_ESTA, REINICIO = 'SOLO_ESTA', 'REINICIO'
    TIPO_CHOICES = [(SOLO_ESTA, 'Cambiar solo esta semana'), (REINICIO, 'Reiniciar la alternancia desde esta semana')]

    configuracion = models.ForeignKey(ConfiguracionHorario, on_delete=models.CASCADE, related_name='excepciones')
    lunes = models.DateField(verbose_name='Semana del')
    semana = models.CharField(max_length=1, choices=HorarioMateria.SEMANA_CHOICES[1:], verbose_name='Será la')
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default=SOLO_ESTA, verbose_name='Tipo de cambio')
    motivo = models.CharField(max_length=200, blank=True, verbose_name='Motivo')
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    creado = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Semana del {self.lunes:%d/%m/%Y}: {self.get_semana_display()} ({self.get_tipo_display().lower()})'

    class Meta:
        verbose_name = 'Excepción de semana'
        verbose_name_plural = 'Excepciones de semana'
        ordering = ['lunes']
        constraints = [models.UniqueConstraint(fields=['configuracion', 'lunes'], name='excepcion_semana_unica')]


class Recreo(models.Model):
    """Un receso de un grupo en un ciclo: un día con su hora. No es una clase (no tiene materia ni profesor), pero ocupa
    el horario del grupo: ninguna materia se le puede empalmar. (En pantalla se llama «receso».)"""

    es_recreo = True   # para distinguirlo de un bloque de materia en la cuadrícula del horario

    ciclo = models.ForeignKey(CicloEscolar, on_delete=models.PROTECT, related_name='recreos')
    grado = models.ForeignKey(Grado, on_delete=models.PROTECT, related_name='recreos')
    grupo = models.ForeignKey(Grupo, on_delete=models.PROTECT, related_name='recreos', verbose_name='Grupo')
    nombre = models.CharField(max_length=40, default='Receso', verbose_name='Nombre')
    dia_semana = models.PositiveSmallIntegerField(choices=HorarioMateria.DIA_CHOICES, verbose_name='Día')
    hora_inicio = models.TimeField(verbose_name='Hora de inicio')
    hora_fin = models.TimeField(verbose_name='Hora de fin')

    def clean(self):
        if self.hora_inicio and self.hora_fin and self.hora_inicio >= self.hora_fin:
            raise ValidationError('La hora de inicio debe ser anterior a la hora de fin.')

    def __str__(self):
        return f'{self.nombre} de {self.grupo if self.grupo_id else self.grado} - {self.get_dia_semana_display()} {self.hora_inicio:%H:%M}–{self.hora_fin:%H:%M}'

    def save(self, *args, **kwargs):
        _con_grupo(self)
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = 'Receso'
        verbose_name_plural = 'Recesos'
        ordering = ['dia_semana', 'hora_inicio']


SEMESTRE_A, SEMESTRE_B = 'A', 'B'
NIVEL_POR_SEMESTRES = 'PREPARATORIA'


def semestre_de_grado(nivel, numero):
    """En preparatoria cada grado es un semestre (2026-10-28): 1.º, 3.º y 5.º se cursan en el semestre A del ciclo y
    2.º, 4.º y 6.º en el B. None en los demás niveles (o sin número)."""
    if nivel != NIVEL_POR_SEMESTRES or not numero:
        return None
    return SEMESTRE_A if numero % 2 else SEMESTRE_B


class Semestre(models.Model):
    """Un semestre de bachillerato (A o B) de un ciclo escolar (pedido del 2026-10-28).

    Tiene sus fechas, sus periodos de evaluación (`Periodo.semestre`) y su estado: pendiente (todavía no se abre),
    abierto (se capturan sus periodos y sus exámenes finales) o cerrado (la evaluación ordinaria ya no se edita; solo
    se capturan los extraordinarios y las regularizaciones pendientes). Se abre, se cierra y se reabre desde Ciclos
    escolares, con bitácora (Calificaciones.CambioSemestre); cerrarlo no cierra el ciclo, el otro semestre ni los
    periodos de los demás niveles.
    """

    CLAVES = [(SEMESTRE_A, 'Semestre A'), (SEMESTRE_B, 'Semestre B')]
    PENDIENTE, ABIERTO, CERRADO = 'PENDIENTE', 'ABIERTO', 'CERRADO'
    ESTADOS = [(PENDIENTE, 'Pendiente'), (ABIERTO, 'Abierto'), (CERRADO, 'Cerrado')]

    ciclo = models.ForeignKey(CicloEscolar, on_delete=models.PROTECT, related_name='semestres', verbose_name='Ciclo escolar')
    clave = models.CharField(max_length=1, choices=CLAVES, verbose_name='Semestre')
    fecha_inicio = models.DateField(verbose_name='Fecha de inicio')
    fecha_fin = models.DateField(verbose_name='Fecha de fin')
    estado = models.CharField(max_length=10, choices=ESTADOS, default=PENDIENTE, verbose_name='Estado')
    abierto_en = models.DateTimeField(null=True, blank=True, verbose_name='Abierto el')
    abierto_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    cerrado_en = models.DateTimeField(null=True, blank=True, verbose_name='Cerrado el')
    cerrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.get_clave_display()} · {self.ciclo}'

    @property
    def nombre(self):
        return self.get_clave_display()

    @property
    def en_frase(self):
        """«semestre A», para usarlo dentro de una oración («El semestre A está cerrado»)."""
        return f'semestre {self.clave}'

    @property
    def abierto(self):
        return self.estado == self.ABIERTO

    @property
    def cerrado(self):
        return self.estado == self.CERRADO

    class Meta:
        verbose_name = 'Semestre de bachillerato'
        verbose_name_plural = 'Semestres de bachillerato'
        ordering = ['ciclo', 'clave']
        default_permissions = ()   # se administran con el ciclo (Alumnos.change_cicloescolar)
        constraints = [models.UniqueConstraint(fields=['ciclo', 'clave'], name='semestre_por_ciclo_unico')]


class PeriodoQuerySet(models.QuerySet):
    def abiertos(self, fecha=None):
        """Los periodos abiertos en esa fecha (hoy si no se indica): abiertos a mano, o por sus fechas si siguen sus
        fechas. Los cerrados a mano nunca."""
        fecha = fecha or timezone.localdate()
        return self.filter(
            models.Q(apertura=Periodo.ABIERTO)
            | models.Q(apertura=Periodo.POR_FECHAS, fecha_inicio__lte=fecha, fecha_fin__gte=fecha)
        )


class Periodo(models.Model):
    """Un periodo de evaluación de un nivel en un ciclo (parcial, bimestre, trimestre…, como lo llame el colegio).

    Mientras está abierto, los profesores de ese nivel pueden capturar calificaciones. Por omisión se abre en su fecha
    de inicio y se cierra al terminar su fecha de cierre; además se puede abrir o cerrar a mano (`apertura`), por
    ejemplo para cerrarlo antes o para dar unos días más de captura, y después volver a sus fechas.
    """

    POR_FECHAS, ABIERTO, CERRADO = 'FECHAS', 'ABIERTO', 'CERRADO'
    APERTURA_CHOICES = [
        (POR_FECHAS, 'Según sus fechas'),
        (ABIERTO, 'Abierto a mano'),
        (CERRADO, 'Cerrado a mano'),
    ]
    PROXIMO = 'PROXIMO'
    ESTADOS = {ABIERTO: 'Abierto', PROXIMO: 'Próximo', CERRADO: 'Cerrado'}

    ciclo = models.ForeignKey(CicloEscolar, on_delete=models.PROTECT, related_name='periodos', verbose_name='Ciclo escolar')
    nivel = models.CharField(max_length=20, choices=Grado.NIVEL_CHOICES, verbose_name='Nivel')
    nombre = models.CharField(max_length=60, verbose_name='Nombre')
    fecha_inicio = models.DateField(verbose_name='Se abre el')
    fecha_fin = models.DateField(verbose_name='Se cierra el')
    apertura = models.CharField(max_length=10, choices=APERTURA_CHOICES, default=POR_FECHAS, verbose_name='Apertura')
    # Solo en preparatoria, cuando el ciclo tiene semestres: el semestre al que pertenece (sus calificaciones forman la
    # calificación semestral de las materias de ese semestre)
    semestre = models.ForeignKey(Semestre, null=True, blank=True, on_delete=models.PROTECT, related_name='periodos', verbose_name='Semestre')
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    objects = PeriodoQuerySet.as_manager()

    def estado_en(self, fecha):
        """ABIERTO, PROXIMO (todavía no llega su fecha de inicio) o CERRADO en esa fecha."""
        if self.apertura in (self.ABIERTO, self.CERRADO):
            return self.apertura
        if fecha < self.fecha_inicio:
            return self.PROXIMO
        return self.ABIERTO if fecha <= self.fecha_fin else self.CERRADO

    @property
    def estado(self):
        return self.estado_en(timezone.localdate())

    @property
    def estado_display(self):
        return self.ESTADOS[self.estado]

    @property
    def esta_abierto(self):
        return self.estado == self.ABIERTO

    @property
    def a_mano(self):
        return self.apertura != self.POR_FECHAS

    def clean(self):
        if self.fecha_inicio and self.fecha_fin and self.fecha_fin < self.fecha_inicio:
            raise ValidationError({'fecha_fin': 'La fecha de cierre no puede ser anterior a la de inicio.'})

    def __str__(self):
        return f'{self.nombre} de {self.get_nivel_display()} ({self.ciclo})'

    class Meta:
        verbose_name = 'Periodo de evaluación'
        verbose_name_plural = 'Periodos de evaluación'
        ordering = ['fecha_inicio', 'nombre']
        constraints = [
            models.UniqueConstraint(fields=['ciclo', 'nivel', 'nombre'], name='periodo_nombre_unico_por_nivel'),
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
    # La falta de una materia que se justificó desde la asistencia por materia (con la foto del comprobante); vacío en
    # las que se registran desde Justificaciones (por día). La de una falta cubre solo esa materia (`materias`).
    asistencia = models.ForeignKey(
        'AsistenciaMateria', null=True, blank=True, on_delete=models.CASCADE, related_name='justificaciones',
        verbose_name='Falta justificada',
    )
    activa = models.BooleanField(default=True, verbose_name='Vigente')
    registrada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
        verbose_name='Registrada por',
    )
    # Las que se registran juntas (prefectura: varias faltas o retardos de un rango de fechas con un mismo motivo y
    # comprobante) comparten su lote; cada una apunta al registro de asistencia que cubre
    lote = models.UUIDField(null=True, blank=True, db_index=True, editable=False)
    revocada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='Revocada por',
    )
    revocada_en = models.DateTimeField(null=True, blank=True, verbose_name='Revocada el')
    motivo_revocacion = models.TextField(blank=True, verbose_name='Motivo de la revocación')
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
            # Una justificación vigente por alumno y día (las de una falta de materia, aparte: una por falta); las
            # anuladas se conservan como historial
            models.UniqueConstraint(
                fields=[
                    'inscripcion',
                    'fecha'
                ],
                condition=models.Q(activa=True, asistencia__isnull=True),
                name='justificacion_alumno_fecha_unica'
            ),
            models.UniqueConstraint(
                fields=['asistencia'],
                condition=models.Q(activa=True, asistencia__isnull=False),
                name='justificacion_falta_unica'
            ),
        ]


class CambioJustificacion(models.Model):
    """Bitácora de una justificación: quién la registró, revocó o reactivó, cuándo y por qué."""

    CREADA, REVOCADA, REACTIVADA, EDITADA = 'CREADA', 'REVOCADA', 'REACTIVADA', 'EDITADA'
    ACCIONES = [(CREADA, 'Justificó'), (REVOCADA, 'Revocó'), (REACTIVADA, 'Reactivó'), (EDITADA, 'Editó')]

    justificacion = models.ForeignKey(Justificacion, on_delete=models.CASCADE, related_name='cambios')
    accion = models.CharField(max_length=10, choices=ACCIONES)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    fecha = models.DateTimeField(auto_now_add=True)
    motivo = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Cambio en una justificación'
        verbose_name_plural = 'Cambios en justificaciones'
        ordering = ['-fecha', '-pk']
        default_permissions = ()


class ConfiguracionAsistencia(models.Model):
    """Reglas del control de asistencia del colegio. Hay un solo registro (`cargar()` lo crea si falta)."""

    hora_entrada = models.TimeField(default=time(8, 0), verbose_name='Hora de entrada')
    tolerancia_minutos = models.PositiveSmallIntegerField(
        default=10, validators=[MaxValueValidator(120)], verbose_name='Tolerancia (minutos)',
    )
    cierre_automatico = models.BooleanField(default=True, verbose_name='Cerrar automáticamente los días anteriores')
    # Pedidos del 2026-10-27: el docente captura y corrige sin depender del periodo de evaluación, pero solo los últimos
    # días; la entrada con número de referencia se puede apagar; el umbral de asistencia de los reportes y el aviso a los
    # tutores se configuran aquí
    dias_para_corregir = models.PositiveSmallIntegerField(
        default=7, validators=[MaxValueValidator(60)], verbose_name='Días que el docente puede capturar o corregir',
    )
    entrada_con_referencia = models.BooleanField(default=True, verbose_name='Permitir la entrada con número de referencia')
    umbral_asistencia = models.PositiveSmallIntegerField(
        default=85, validators=[MinValueValidator(1), MaxValueValidator(100)], verbose_name='Umbral de asistencia (%)',
    )
    avisar_a_tutores = models.BooleanField(default=True, verbose_name='Avisar a los tutores de las faltas y los retardos')

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


class LimiteEntradaNivel(models.Model):
    """La hora límite de entrada de un nivel (pedido del 2026-10-14). Quien registra su entrada después queda con
    retardo en la entrada general, y la primera clase de su día le cuenta como falta. Un nivel sin límite usa la regla
    general: la hora de entrada más la tolerancia."""

    nivel = models.CharField(max_length=20, choices=Grado.NIVEL_CHOICES, unique=True, verbose_name='Nivel')
    hora_limite = models.TimeField(verbose_name='Hora límite de entrada')

    def __str__(self):
        return f"{self.get_nivel_display()}: {self.hora_limite:%H:%M}"

    class Meta:
        verbose_name = 'Hora límite de entrada de un nivel'
        verbose_name_plural = 'Horas límite de entrada por nivel'
        default_permissions = ()   # se administran con los ajustes de asistencia


class UmbralAsistenciaNivel(models.Model):
    """El umbral de asistencia de un nivel (pedido del 2026-10-27): en los reportes se marca a quien queda por debajo.
    Un nivel sin umbral propio usa el general (`ConfiguracionAsistencia.umbral_asistencia`)."""

    nivel = models.CharField(max_length=20, choices=Grado.NIVEL_CHOICES, unique=True, verbose_name='Nivel')
    umbral = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(100)], verbose_name='Umbral (%)')

    def __str__(self):
        return f"{self.get_nivel_display()}: {self.umbral} %"

    class Meta:
        verbose_name = 'Umbral de asistencia de un nivel'
        verbose_name_plural = 'Umbrales de asistencia por nivel'
        default_permissions = ()   # se administran con los ajustes de asistencia


class CambioAsistencia(models.Model):
    """Bitácora de la asistencia (pedido del 2026-10-27): cada captura o corrección que hace una persona, con lo que
    había antes y lo que quedó. Sin `materia_grado` es la asistencia general (la entrada al colegio). Lo que genera el
    sistema (la pantalla de entrada y el cierre del día) no se anota: ya queda en el origen del registro."""

    inscripcion = models.ForeignKey(Inscripcion, on_delete=models.CASCADE, related_name='cambios_de_asistencia')
    fecha = models.DateField(verbose_name='Día de la asistencia')
    materia_grado = models.ForeignKey(
        MateriaGrado, null=True, blank=True, on_delete=models.CASCADE, related_name='+', verbose_name='Materia',
    )
    estado_anterior = models.CharField(max_length=15, blank=True, verbose_name='Estado anterior')   # vacío: sin registro
    estado_nuevo = models.CharField(max_length=15, verbose_name='Estado nuevo')
    hora_anterior = models.TimeField(null=True, blank=True, verbose_name='Hora anterior')
    hora_nueva = models.TimeField(null=True, blank=True, verbose_name='Hora nueva')
    observacion_anterior = models.CharField(max_length=250, blank=True, verbose_name='Observación anterior')
    observacion_nueva = models.CharField(max_length=250, blank=True, verbose_name='Observación nueva')
    via = models.CharField(max_length=120, blank=True, verbose_name='Desde dónde')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='Quién')
    creado = models.DateTimeField(auto_now_add=True, verbose_name='Cuándo')

    def __str__(self):
        return f"{self.inscripcion.alumno} - {self.fecha} - {self.estado_anterior or 'sin registro'} → {self.estado_nuevo}"

    class Meta:
        verbose_name = 'Cambio en la asistencia'
        verbose_name_plural = 'Cambios en la asistencia'
        ordering = ['-creado', '-pk']
        default_permissions = ()   # se consulta con la asistencia del estudiante
        indexes = [models.Index(fields=['inscripcion', 'fecha'], name='cambio_asistencia_dia')]


class NotificacionAsistencia(models.Model):
    """Un aviso de asistencia en la campana del portal de tutores (pedido del 2026-10-27): al cerrar el día, la falta o
    el retardo de su hijo. Uno por tutor, estudiante y día."""

    FALTA, RETARDO = 'FALTA', 'RETARDO'
    TIPOS = [(FALTA, 'Falta'), (RETARDO, 'Retardo')]

    tutor = models.ForeignKey('Tutor', on_delete=models.CASCADE, related_name='+')
    inscripcion = models.ForeignKey(Inscripcion, on_delete=models.CASCADE, related_name='+')
    fecha = models.DateField(verbose_name='Día')
    tipo = models.CharField(max_length=10, choices=TIPOS)
    titulo = models.CharField(max_length=160)
    texto = models.CharField(max_length=300)
    leida = models.BooleanField(default=False)
    creada = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f"{self.titulo}: {self.texto}"

    class Meta:
        verbose_name = 'Aviso de asistencia'
        verbose_name_plural = 'Avisos de asistencia'
        ordering = ['-creada', '-pk']
        default_permissions = ()
        indexes = [models.Index(fields=['tutor', 'leida'], name='asistencia_notif_tutor')]
        constraints = [
            models.UniqueConstraint(fields=['tutor', 'inscripcion', 'fecha'], name='asistencia_notif_unica'),
        ]


class DiaNoLectivo(models.Model):
    """Un día sin clases de un nivel (asueto, consejo técnico, vacaciones): sus estudiantes no registran entrada ni se
    les generan faltas. Un día de todo el colegio se registra en cada nivel («Todos los niveles» en Ajustes ›
    Asistencia)."""

    fecha = models.DateField(verbose_name='Fecha')
    nivel = models.CharField(max_length=20, choices=Grado.NIVEL_CHOICES, verbose_name='Nivel')
    motivo = models.CharField(max_length=120, verbose_name='Motivo')
    creado = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.fecha} - {self.get_nivel_display()} - {self.motivo}"

    @classmethod
    def registrar(cls, fecha, motivo, niveles=None):
        """Registra ese día sin clases en esos niveles (sin niveles, en todos). Devuelve los registros creados."""
        niveles = niveles or [clave for clave, _ in Grado.NIVEL_CHOICES]
        return cls.objects.bulk_create([cls(fecha=fecha, nivel=nivel, motivo=motivo) for nivel in niveles])

    class Meta:
        verbose_name = 'Día sin clases'
        verbose_name_plural = 'Días sin clases'
        ordering = ['fecha']
        constraints = [models.UniqueConstraint(fields=['fecha', 'nivel'], name='dia_sin_clases_por_nivel')]


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
    # Portal (pedido del 2026-10-14): el tutor entra con su usuario y su contraseña. Se puede desactivar sin cambiar
    # su estatus; tras varios intentos fallidos se bloquea un rato (CISAHUAYO/portales.py).
    acceso_portal = models.BooleanField(default=True, verbose_name='Acceso al portal')
    ultimo_acceso = models.DateTimeField(null=True, blank=True, editable=False, verbose_name='Último acceso al portal')
    intentos_fallidos = models.PositiveSmallIntegerField(default=0, editable=False, verbose_name='Intentos fallidos')
    bloqueado_hasta = models.DateTimeField(null=True, blank=True, editable=False, verbose_name='Bloqueado hasta')
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
        """Asigna la contraseña (cifrada para verificarla y legible para consulta) y quita el bloqueo del portal por
        intentos fallidos. No guarda el registro."""
        self.contrasena = make_password(contrasena)
        self.contrasena_visible = contrasena
        self.intentos_fallidos, self.bloqueado_hasta = 0, None

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
    # A quién llamar si al profesor le pasa algo en el colegio (vista 360 del docente, 2026-10-23)
    emergencia_nombre = models.CharField(max_length=150, blank=True, verbose_name='Contacto de emergencia')
    emergencia_parentesco = models.CharField(max_length=60, blank=True, verbose_name='Parentesco o relación')
    emergencia_telefono = models.CharField(max_length=20, blank=True, verbose_name='Teléfono de emergencia')
    profesion = models.CharField(max_length=150, blank=True, verbose_name='Profesión o título')
    cedula_profesional = models.CharField(max_length=20, blank=True, verbose_name='Cédula profesional')
    especialidad = models.CharField(max_length=150, blank=True, verbose_name='Especialidad o áreas que imparte')
    fecha_ingreso = models.DateField(null=True, blank=True, verbose_name='Fecha de ingreso al colegio')
    horas_maximas = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name='Horas máximas por semana',
        help_text='Opcional. Sirve para avisar cuando su carga de clases la rebasa.',
    )
    observaciones = models.TextField(blank=True, verbose_name='Observaciones')
    fotografia = models.ImageField(upload_to='profesores/', blank=True, null=True, verbose_name='Fotografía')
    estatus = models.CharField(max_length=20, choices=ESTATUS_CHOICES, default='ACTIVO', verbose_name='Estatus')
    # Las materias (MateriaGrado) del ciclo actual que se le quitaron en su última baja: al reactivarlo se le ofrecen de
    # nuevo, las que sigan sin profesor (Profesores/views.py)
    materias_al_darse_de_baja = models.JSONField(default=list, blank=True, editable=False)
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

