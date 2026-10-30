"""Control de calificaciones (pedido del 2026-10-14, con el formato «GeneralSecundaria.xlsx» como referencia).

- **Configuración** (`ConfiguracionEvaluacion` + `Rubro`): cada materia tiene sus rubros y porcentajes en cada ciclo
  (nada fijo en el código) y, si hace falta, una versión propia para un periodo. Mientras la suma de los rubros activos
  no sea 100 % es un borrador: se puede guardar, pero no sirve para cerrar calificaciones. Además lleva las reglas del
  formato convertidas en opciones: descuento por faltas, punto de academia y límites.
- **Acta** (`ActaCalificaciones`): las calificaciones de una materia de un grupo (`MateriaGrado`) en un periodo de
  evaluación. Está en captura o cerrada; al cerrarse guarda la configuración y los resultados que se usaron, así que un
  cambio posterior en la configuración no altera lo cerrado. Se reabre solo con permiso, motivo y bitácora.
- **Actividades** (`Actividad`): procedimientos y exámenes del periodo, cada uno de un rubro de promedio. Todas pesan
  lo mismo dentro de su rubro. Con calificaciones no se borran: se anulan con motivo.
- **Capturas**: la calificación de cada estudiante en cada actividad (`CalificacionActividad`), la de los rubros de
  captura directa como conducta (`CalificacionRubro`) y, por estudiante, las faltas capturadas a mano y el punto de
  academia (`AjusteDelEstudiante`). Una celda vacía es «pendiente» (no hay registro); un cero sí es calificación.
- **Bitácora** (`CambioCalificacion`, `CambioConfiguracion`): quién cambió qué, cuándo, el valor anterior y el nuevo.
- **Bachillerato por semestres** (pedido del 2026-10-28): sobre las calificaciones de los periodos, los exámenes del
  semestre (`ExamenSemestral`: final, extraordinario y regularización, cada uno por separado) y la bitácora del
  semestre (`CambioSemestre`: apertura, cierre, reapertura con motivo y cada examen capturado).

Los cálculos viven en Calificaciones/calculo.py y Calificaciones/calculo_semestral.py (puros) y las reglas de negocio
en Calificaciones/reglas.py y Calificaciones/semestres.py.
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q

from Alumnos.models import CicloEscolar, Grado, Inscripcion, Materia, MateriaGrado, Periodo, Semestre

CERO, DIEZ = Decimal('0'), Decimal('10')
CALIFICACION = [MinValueValidator(CERO), MaxValueValidator(DIEZ)]


class ConfiguracionEvaluacion(models.Model):
    BORRADOR, ACTIVA = 'BORRADOR', 'ACTIVA'
    ESTADOS = [(BORRADOR, 'Borrador'), (ACTIVA, 'Activa')]

    # Qué faltas descuentan (el formato no lo dice: se elige explícitamente)
    SIN_JUSTIFICAR, TODAS, MANUAL = 'SIN_JUSTIFICAR', 'TODAS', 'MANUAL'
    ORIGENES_DE_FALTAS = [
        (SIN_JUSTIFICAR, 'Faltas sin justificar de la asistencia de la materia'),
        (TODAS, 'Todas las faltas de la asistencia de la materia (justificadas o no)'),
        (MANUAL, 'Captura manual en el resumen'),
    ]

    materia = models.ForeignKey(Materia, on_delete=models.PROTECT, related_name='configuraciones_evaluacion', verbose_name='Materia')
    ciclo = models.ForeignKey(CicloEscolar, on_delete=models.PROTECT, related_name='configuraciones_evaluacion', verbose_name='Ciclo escolar')
    # Vacío: la del ciclo, que usan los periodos sin versión propia
    periodo = models.ForeignKey(Periodo, null=True, blank=True, on_delete=models.PROTECT, related_name='configuraciones_evaluacion',
                                verbose_name='Periodo')
    estado = models.CharField(max_length=10, choices=ESTADOS, default=BORRADOR, verbose_name='Estado')

    penalizar_faltas = models.BooleanField(default=True, verbose_name='Descontar puntos por faltas')
    faltas_por_bloque = models.PositiveSmallIntegerField(default=2, validators=[MinValueValidator(1)], verbose_name='Faltas para descontar')
    puntos_por_bloque = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal('1'), validators=[MinValueValidator(CERO)],
                                            verbose_name='Puntos que se descuentan')
    origen_faltas = models.CharField(max_length=15, choices=ORIGENES_DE_FALTAS, default=SIN_JUSTIFICAR, verbose_name='Faltas que cuentan')
    punto_academia = models.BooleanField(default=True, verbose_name='Punto de academia')
    valor_punto_academia = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal('1'), validators=[MinValueValidator(CERO)],
                                               verbose_name='Valor del punto de academia')
    limite_maximo = models.DecimalField(max_digits=4, decimal_places=2, default=DIEZ, validators=CALIFICACION, verbose_name='Calificación máxima')
    # El formato no pone límite inferior: solo se aplica si se activa
    usar_limite_minimo = models.BooleanField(default=False, verbose_name='Aplicar una calificación mínima')
    limite_minimo = models.DecimalField(max_digits=4, decimal_places=2, default=CERO, validators=CALIFICACION, verbose_name='Calificación mínima')

    copiada_de = models.CharField(max_length=250, blank=True, verbose_name='Copiada de')
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)
    modificado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        verbose_name = 'Configuración de calificaciones'
        verbose_name_plural = 'Configuraciones de calificaciones'
        default_permissions = ('view', 'add', 'change')
        constraints = [
            models.UniqueConstraint(fields=['materia', 'ciclo', 'periodo'], name='configuracion_por_periodo_unica'),
            models.UniqueConstraint(fields=['materia', 'ciclo'], condition=Q(periodo__isnull=True), name='configuracion_del_ciclo_unica'),
        ]

    def __str__(self):
        return f'{self.materia} · {self.ciclo} · {self.alcance}'

    @property
    def alcance(self):
        return self.periodo.nombre if self.periodo_id else 'todo el ciclo'

    @property
    def activa(self):
        return self.estado == self.ACTIVA


class Rubro(models.Model):
    DIRECTA, PROCEDIMIENTOS, EXAMENES = 'DIRECTA', 'PROCEDIMIENTOS', 'EXAMENES'
    TIPOS = [
        (DIRECTA, 'Calificación directa'),
        (PROCEDIMIENTOS, 'Promedio de procedimientos'),
        (EXAMENES, 'Promedio de exámenes'),
    ]
    DE_ACTIVIDADES = (PROCEDIMIENTOS, EXAMENES)

    configuracion = models.ForeignKey(ConfiguracionEvaluacion, on_delete=models.CASCADE, related_name='rubros')
    nombre = models.CharField(max_length=80, verbose_name='Nombre')
    porcentaje = models.DecimalField(max_digits=5, decimal_places=2, validators=[MinValueValidator(CERO), MaxValueValidator(Decimal('100'))],
                                     verbose_name='Porcentaje')
    tipo = models.CharField(max_length=15, choices=TIPOS, verbose_name='Tipo de captura')
    orden = models.PositiveSmallIntegerField(default=0, verbose_name='Orden')
    activo = models.BooleanField(default=True, verbose_name='Activo')

    class Meta:
        verbose_name = 'Rubro'
        verbose_name_plural = 'Rubros'
        ordering = ['orden', 'pk']
        default_permissions = ()   # se administran con la configuración

    def __str__(self):
        texto = f'{self.porcentaje:.2f}'.rstrip('0').rstrip('.')
        return f'{self.nombre} ({texto} %)'

    @property
    def de_actividades(self):
        return self.tipo in self.DE_ACTIVIDADES


class ActaCalificaciones(models.Model):
    """Las calificaciones de una materia de un grupo en un periodo."""

    EN_CAPTURA, CERRADA = 'EN_CAPTURA', 'CERRADA'
    ESTADOS = [(EN_CAPTURA, 'En captura'), (CERRADA, 'Cerrada')]

    asignacion = models.ForeignKey(MateriaGrado, on_delete=models.PROTECT, related_name='actas_calificaciones', verbose_name='Materia del grupo')
    periodo = models.ForeignKey(Periodo, on_delete=models.PROTECT, related_name='actas_calificaciones', verbose_name='Periodo')
    estado = models.CharField(max_length=12, choices=ESTADOS, default=EN_CAPTURA, verbose_name='Estado')
    cerrada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    cerrada_en = models.DateTimeField(null=True, blank=True)
    # Lo que se usó al cerrar: no cambia aunque después se edite la configuración
    configuracion_cerrada = models.JSONField(default=dict, blank=True)
    resultados_cerrados = models.JSONField(default=list, blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Acta de calificaciones'
        verbose_name_plural = 'Actas de calificaciones'
        default_permissions = ()
        permissions = [
            ('capturar', 'Capturar las calificaciones de sus materias (docente)'),
            ('ver_todas', 'Consultar las calificaciones de todas las materias'),
            ('gestionar_todas', 'Capturar y gestionar las calificaciones de todas las materias'),
            ('cerrar', 'Cerrar las calificaciones de un periodo'),
            ('reabrir', 'Reabrir calificaciones cerradas'),
        ]
        constraints = [models.UniqueConstraint(fields=['asignacion', 'periodo'], name='acta_por_materia_y_periodo')]

    def __str__(self):
        return f'{self.asignacion} · {self.periodo.nombre}'

    @property
    def cerrada(self):
        return self.estado == self.CERRADA


class Actividad(models.Model):
    PROCEDIMIENTO, EXAMEN = 'PROCEDIMIENTO', 'EXAMEN'
    TIPOS = [(PROCEDIMIENTO, 'Procedimiento'), (EXAMEN, 'Examen')]
    DEL_RUBRO = {Rubro.PROCEDIMIENTOS: PROCEDIMIENTO, Rubro.EXAMENES: EXAMEN}

    acta = models.ForeignKey(ActaCalificaciones, on_delete=models.PROTECT, related_name='actividades')
    rubro = models.ForeignKey(Rubro, on_delete=models.PROTECT, related_name='actividades', verbose_name='Rubro')
    tipo = models.CharField(max_length=15, choices=TIPOS, verbose_name='Tipo')
    nombre = models.CharField(max_length=120, verbose_name='Nombre')
    descripcion = models.TextField(blank=True, verbose_name='Descripción')
    fecha = models.DateField(verbose_name='Fecha')
    orden = models.PositiveIntegerField(default=0, verbose_name='Orden')

    anulada = models.BooleanField(default=False, verbose_name='Anulada')
    anulada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    anulada_en = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.TextField(blank=True, verbose_name='Motivo de la anulación')

    creada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Actividad'
        verbose_name_plural = 'Actividades'
        ordering = ['orden', 'fecha', 'pk']
        default_permissions = ()

    def __str__(self):
        return self.nombre


class CalificacionActividad(models.Model):
    actividad = models.ForeignKey(Actividad, on_delete=models.CASCADE, related_name='calificaciones')
    inscripcion = models.ForeignKey(Inscripcion, on_delete=models.PROTECT, related_name='calificaciones_actividad')
    valor = models.DecimalField(max_digits=4, decimal_places=2, validators=CALIFICACION)
    modificado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=['actividad', 'inscripcion'], name='calificacion_por_actividad_unica')]


class CalificacionRubro(models.Model):
    """La calificación de un rubro de captura directa (p. ej. conducta) de un estudiante en un acta."""

    acta = models.ForeignKey(ActaCalificaciones, on_delete=models.CASCADE, related_name='calificaciones_directas')
    rubro = models.ForeignKey(Rubro, on_delete=models.PROTECT, related_name='calificaciones_directas')
    inscripcion = models.ForeignKey(Inscripcion, on_delete=models.PROTECT, related_name='calificaciones_rubro')
    valor = models.DecimalField(max_digits=4, decimal_places=2, validators=CALIFICACION)
    modificado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=['acta', 'rubro', 'inscripcion'], name='calificacion_por_rubro_unica')]


class AjusteDelEstudiante(models.Model):
    """Por estudiante y acta: faltas capturadas a mano (si la configuración lo pide) y el punto de academia."""

    acta = models.ForeignKey(ActaCalificaciones, on_delete=models.CASCADE, related_name='ajustes')
    inscripcion = models.ForeignKey(Inscripcion, on_delete=models.PROTECT, related_name='ajustes_calificacion')
    faltas_manuales = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name='Faltas (captura manual)')
    punto_academia = models.BooleanField(default=False, verbose_name='Punto de academia otorgado')
    modificado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=['acta', 'inscripcion'], name='ajuste_por_estudiante_unico')]


class CambioCalificacion(models.Model):
    """Bitácora de un acta: cada calificación cambiada (antes y después), las actividades, el cierre y la reapertura."""

    CAPTURA, ACTIVIDAD_NUEVA, ACTIVIDAD_EDITADA, ACTIVIDAD_ANULADA, ACTIVIDAD_ELIMINADA, CIERRE, REAPERTURA = (
        'CAPTURA', 'ACT_NUEVA', 'ACT_EDITADA', 'ACT_ANULADA', 'ACT_ELIMINADA', 'CIERRE', 'REAPERTURA',
    )
    ACCIONES = [
        (CAPTURA, 'Calificación'), (ACTIVIDAD_NUEVA, 'Actividad agregada'), (ACTIVIDAD_EDITADA, 'Actividad editada'),
        (ACTIVIDAD_ANULADA, 'Actividad anulada'), (ACTIVIDAD_ELIMINADA, 'Actividad eliminada'), (CIERRE, 'Cierre'),
        (REAPERTURA, 'Reapertura'),
    ]

    acta = models.ForeignKey(ActaCalificaciones, on_delete=models.CASCADE, related_name='cambios')
    accion = models.CharField(max_length=15, choices=ACCIONES)
    inscripcion = models.ForeignKey(Inscripcion, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    que = models.CharField(max_length=200)            # «Conducta», «Procedimiento: Mapa conceptual», «Faltas»…
    anterior = models.CharField(max_length=60, blank=True)
    nuevo = models.CharField(max_length=60, blank=True)
    motivo = models.TextField(blank=True)
    datos = models.JSONField(default=dict, blank=True)   # lo que se cerró (al reabrir) u otros detalles
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha', '-pk']
        default_permissions = ()


class CambioConfiguracion(models.Model):
    configuracion = models.ForeignKey(ConfiguracionEvaluacion, on_delete=models.CASCADE, related_name='cambios')
    descripcion = models.TextField()
    cambios = models.JSONField(default=list, blank=True)   # [[qué, antes, después], …]
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha', '-pk']
        default_permissions = ()


class ExamenSemestral(models.Model):
    """Un examen del semestre de un estudiante en una materia de su grupo: el final, el extraordinario o la
    regularización. Cada uno se guarda por separado (no se sobrescriben entre sí) y cada cambio queda en la bitácora del
    semestre. El examen final de quien queda exento no se captura: lo asigna el cálculo (calculo_semestral.py)."""

    FINAL, EXTRAORDINARIO, REGULARIZACION = 'FINAL', 'EXTRAORDINARIO', 'REGULARIZACION'
    TIPOS = [(FINAL, 'Examen final'), (EXTRAORDINARIO, 'Extraordinario'), (REGULARIZACION, 'Regularización')]

    asignacion = models.ForeignKey(MateriaGrado, on_delete=models.PROTECT, related_name='examenes_semestrales', verbose_name='Materia del grupo')
    inscripcion = models.ForeignKey(Inscripcion, on_delete=models.PROTECT, related_name='examenes_semestrales')
    tipo = models.CharField(max_length=15, choices=TIPOS, verbose_name='Examen')
    valor = models.DecimalField(max_digits=4, decimal_places=2, validators=CALIFICACION, verbose_name='Calificación')
    modificado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Examen semestral'
        verbose_name_plural = 'Exámenes semestrales'
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=['asignacion', 'inscripcion', 'tipo'], name='examen_semestral_unico')]

    def __str__(self):
        return f'{self.get_tipo_display()} · {self.asignacion.materia} · {self.valor}'


class CambioSemestre(models.Model):
    """Bitácora de un semestre de bachillerato: apertura, cierre (con los resultados que quedaron), reapertura (con
    motivo y lo que estaba cerrado), cambio de fechas y cada examen capturado o corregido (antes y después)."""

    APERTURA, CIERRE, REAPERTURA, FECHAS, EXAMEN = 'APERTURA', 'CIERRE', 'REAPERTURA', 'FECHAS', 'EXAMEN'
    ACCIONES = [(APERTURA, 'Apertura'), (CIERRE, 'Cierre'), (REAPERTURA, 'Reapertura'), (FECHAS, 'Fechas'), (EXAMEN, 'Examen')]

    semestre = models.ForeignKey(Semestre, on_delete=models.CASCADE, related_name='cambios')
    accion = models.CharField(max_length=12, choices=ACCIONES)
    asignacion = models.ForeignKey(MateriaGrado, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    inscripcion = models.ForeignKey(Inscripcion, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    que = models.CharField(max_length=200)
    anterior = models.CharField(max_length=60, blank=True)
    nuevo = models.CharField(max_length=60, blank=True)
    motivo = models.TextField(blank=True)
    datos = models.JSONField(default=dict, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha', '-pk']
        default_permissions = ()


class DatosOficialesNivel(models.Model):
    """Los datos oficiales de un nivel que llevan sus boletas (pedido del 2026-10-29): la clave del centro de trabajo
    (CCT) y quien lo dirige, para el encabezado y la firma. Sin registro, la boleta sale sin esos datos."""

    nivel = models.CharField(max_length=20, choices=Grado.NIVEL_CHOICES, unique=True, verbose_name='Nivel')
    cct = models.CharField(
        max_length=10, blank=True, verbose_name='Clave del centro de trabajo (CCT)',
        validators=[RegexValidator(r'^[0-9]{2}[A-Z]{3}[0-9]{4}[A-Z0-9]$', 'Escribe la clave como la da la SEP: 10 caracteres, p. ej. 16PPR0123K.')],
    )
    director = models.CharField(max_length=120, blank=True, verbose_name='Nombre de quien dirige el nivel')
    cargo = models.CharField(max_length=80, blank=True, verbose_name='Cargo', help_text='Como aparece bajo la firma: «Directora de Primaria».')
    modificado = models.DateTimeField(auto_now=True)
    modificado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        verbose_name = 'Datos oficiales de un nivel'
        verbose_name_plural = 'Datos oficiales por nivel'
        default_permissions = ('view', 'change')

    def __str__(self):
        return f'{self.get_nivel_display()}: {self.cct or "sin CCT"}'

    @property
    def cargo_o_predeterminado(self):
        return self.cargo or f'Dirección de {self.get_nivel_display()}'
