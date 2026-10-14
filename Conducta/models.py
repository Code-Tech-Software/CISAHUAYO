"""Conducta: catálogos de cada nivel educativo y el registro de conducta de los estudiantes (pedido del 2026-10-13).

Se apoya en lo que ya existe: los niveles son los de `Grado.NIVEL_CHOICES`, el estudiante es `Alumno` (su número de
control es la referencia), su grado y grupo salen de su `Inscripcion` del ciclo de la fecha del hecho y el periodo es el
`Periodo` de evaluación de su nivel que contiene esa fecha. Nada de eso se duplica: el registro guarda los vínculos y,
además, una copia de los nombres que tenían al registrarse (grupo, categoría, motivo, medidas y motivo de suspensión),
para que el historial conserve su significado aunque después cambien el grupo del estudiante o los catálogos.

Los catálogos no se borran si ya se usaron (PROTECT): se desactivan, y un elemento inactivo sigue viéndose en los
registros que lo usan pero ya no se ofrece para registros nuevos. Las reglas viven en Conducta/reglas.py.
"""
import uuid
from pathlib import Path

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from Alumnos.models import Alumno, CicloEscolar, Grado, Grupo, Inscripcion, Periodo, Tutor

NIVELES = Grado.NIVEL_CHOICES

INCIDENCIA, POSITIVA = 'INCIDENCIA', 'POSITIVA'
TIPOS = [(INCIDENCIA, 'Incidencia'), (POSITIVA, 'Conducta positiva')]

LEVE, MODERADA, GRAVE = 'LEVE', 'MODERADA', 'GRAVE'
GRAVEDADES = [(LEVE, 'Leve'), (MODERADA, 'Moderada'), (GRAVE, 'Grave')]


def _ruta_privada(carpeta, nombre):
    """Nombre al azar (sin el del archivo original): la dirección del archivo no se puede adivinar ni se muestra; los
    archivos solo se entregan por las vistas del módulo, que piden permiso (ver Conducta/views.py)."""
    extension = Path(nombre).suffix.lower()[:10]
    return f'conducta/{carpeta}/{timezone.localdate():%Y/%m}/{uuid.uuid4().hex}{extension}'


def ruta_de_evidencia(instancia, nombre):
    return _ruta_privada('evidencias', nombre)


def ruta_de_acuse(instancia, nombre):
    return _ruta_privada('acuses', nombre)


# ---------------------------------------------------------------------------
# Catálogos de cada nivel
# ---------------------------------------------------------------------------
class CatalogoQuerySet(models.QuerySet):
    def activos(self):
        return self.filter(activo=True)

    def del_nivel(self, nivel):
        return self.filter(nivel=nivel)


class _Catalogo(models.Model):
    """Lo común a los catálogos que pertenecen a un nivel: nombre único en el nivel (sin distinguir mayúsculas)."""

    nivel = models.CharField(max_length=20, choices=NIVELES, verbose_name='Nivel educativo')
    nombre = models.CharField(max_length=100, verbose_name='Nombre')
    descripcion = models.TextField(blank=True, verbose_name='Descripción')
    activo = models.BooleanField(default=True, verbose_name='Activo')
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    objects = CatalogoQuerySet.as_manager()

    class Meta:
        abstract = True
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class CategoriaConducta(_Catalogo):
    tipo = models.CharField(max_length=12, choices=TIPOS, verbose_name='Tipo')

    class Meta(_Catalogo.Meta):
        verbose_name = 'Categoría de conducta'
        verbose_name_plural = 'Categorías de conducta'
        constraints = [
            models.UniqueConstraint(Lower('nombre'), 'nivel', name='categoria_conducta_unica_en_el_nivel'),
        ]


class MotivoConducta(models.Model):
    """Un motivo de una categoría: su nivel es el de la categoría (no puede ser de otro)."""

    categoria = models.ForeignKey(CategoriaConducta, on_delete=models.PROTECT, related_name='motivos', verbose_name='Categoría')
    nombre = models.CharField(max_length=100, verbose_name='Nombre del motivo')
    descripcion = models.TextField(blank=True, verbose_name='Descripción')
    # Solo en las incidencias: la que se propone al registrar (se puede ajustar en cada registro)
    gravedad = models.CharField(max_length=10, choices=GRAVEDADES, blank=True, verbose_name='Gravedad')
    activo = models.BooleanField(default=True, verbose_name='Activo')
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    objects = CatalogoQuerySet.as_manager()

    class Meta:
        verbose_name = 'Motivo de conducta'
        verbose_name_plural = 'Motivos de conducta'
        ordering = ['nombre']
        constraints = [
            models.UniqueConstraint(Lower('nombre'), 'categoria', name='motivo_conducta_unico_en_la_categoria'),
        ]

    def __str__(self):
        return self.nombre

    @property
    def nivel(self):
        return self.categoria.nivel


class MedidaDisciplinaria(_Catalogo):
    requiere_seguimiento = models.BooleanField(default=False, verbose_name='Requiere seguimiento')
    implica_suspension = models.BooleanField(default=False, verbose_name='Implica suspensión')
    # Prefectura solo aplica las medidas habilitadas para ella; las que requieren aprobación (y toda suspensión) quedan
    # pendientes hasta que alguien con el permiso de aprobar las resuelva
    disponible_prefectura = models.BooleanField(default=False, verbose_name='Disponible para prefectura')
    requiere_aprobacion = models.BooleanField(default=False, verbose_name='Requiere aprobación')

    class Meta(_Catalogo.Meta):
        verbose_name = 'Medida disciplinaria'
        verbose_name_plural = 'Medidas disciplinarias'
        constraints = [
            models.UniqueConstraint(Lower('nombre'), 'nivel', name='medida_disciplinaria_unica_en_el_nivel'),
        ]


class MotivoSuspension(_Catalogo):
    class Meta(_Catalogo.Meta):
        verbose_name = 'Motivo de suspensión'
        verbose_name_plural = 'Motivos de suspensión'
        constraints = [
            models.UniqueConstraint(Lower('nombre'), 'nivel', name='motivo_suspension_unico_en_el_nivel'),
        ]


class ReglaReincidencia(models.Model):
    """Aviso de reincidencia de un nivel: al llegar a `incidencias` del mismo motivo en `dias` días, se avisa para que
    alguien lo revise. Nunca aplica sanciones por sí sola."""

    nivel = models.CharField(max_length=20, choices=NIVELES, unique=True, verbose_name='Nivel educativo')
    incidencias = models.PositiveSmallIntegerField(
        default=3, validators=[MinValueValidator(2), MaxValueValidator(50)], verbose_name='Incidencias del mismo motivo',
    )
    dias = models.PositiveSmallIntegerField(
        default=30, validators=[MinValueValidator(1), MaxValueValidator(365)], verbose_name='En cuántos días',
    )
    activa = models.BooleanField(default=True, verbose_name='Activa')
    modificado = models.DateTimeField(auto_now=True)
    modificado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        verbose_name = 'Aviso de reincidencia'
        verbose_name_plural = 'Avisos de reincidencia'

    def __str__(self):
        return f'{self.get_nivel_display()}: {self.incidencias} en {self.dias} días'


# ---------------------------------------------------------------------------
# Registro de conducta
# ---------------------------------------------------------------------------
class RegistroQuerySet(models.QuerySet):
    def vigentes(self):
        """Sin los anulados (los indicadores y reportes los excluyen por omisión)."""
        return self.filter(anulado=False)


class RegistroConducta(models.Model):
    PENDIENTE, EN_SEGUIMIENTO, CERRADO = 'PENDIENTE', 'EN_SEGUIMIENTO', 'CERRADO'
    ESTADOS = [(PENDIENTE, 'Abierto'), (EN_SEGUIMIENTO, 'En seguimiento'), (CERRADO, 'Cerrado')]

    # Quién y en qué grupo estaba al momento del hecho (no cambia aunque después cambie de grupo o de ciclo)
    alumno = models.ForeignKey(Alumno, on_delete=models.PROTECT, related_name='conductas', verbose_name='Estudiante')
    inscripcion = models.ForeignKey(Inscripcion, on_delete=models.PROTECT, related_name='conductas', verbose_name='Inscripción')
    ciclo = models.ForeignKey(CicloEscolar, on_delete=models.PROTECT, related_name='conductas', verbose_name='Ciclo escolar')
    nivel = models.CharField(max_length=20, choices=NIVELES, verbose_name='Nivel educativo')
    grado = models.ForeignKey(Grado, on_delete=models.PROTECT, related_name='+', verbose_name='Grado')
    grupo = models.ForeignKey(Grupo, on_delete=models.PROTECT, related_name='+', verbose_name='Grupo')
    grupo_texto = models.CharField(max_length=80, verbose_name='Grupo (como se llamaba)')
    periodo = models.ForeignKey(Periodo, on_delete=models.SET_NULL, null=True, blank=True, related_name='conductas', verbose_name='Periodo')

    # El hecho
    fecha = models.DateField(verbose_name='Fecha')
    hora = models.TimeField(null=True, blank=True, verbose_name='Hora')
    lugar = models.CharField(max_length=120, blank=True, verbose_name='Lugar')
    reporta = models.CharField(max_length=150, blank=True, verbose_name='Personal que reporta')
    tipo = models.CharField(max_length=12, choices=TIPOS, verbose_name='Tipo')
    categoria = models.ForeignKey(CategoriaConducta, on_delete=models.PROTECT, related_name='registros', verbose_name='Categoría')
    categoria_nombre = models.CharField(max_length=100, verbose_name='Categoría (como se llamaba)')
    motivo = models.ForeignKey(MotivoConducta, on_delete=models.PROTECT, related_name='registros', verbose_name='Motivo')
    motivo_nombre = models.CharField(max_length=100, verbose_name='Motivo (como se llamaba)')
    gravedad = models.CharField(max_length=10, choices=GRAVEDADES, blank=True, verbose_name='Gravedad')
    descripcion = models.TextField(verbose_name='Descripción de los hechos')

    # Medidas y seguimiento
    medidas = models.ManyToManyField(MedidaDisciplinaria, through='MedidaAplicada', related_name='registros', blank=True, verbose_name='Medidas')
    observaciones_medidas = models.TextField(blank=True, verbose_name='Observaciones sobre las medidas')
    responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
        verbose_name='Responsable del seguimiento',
    )
    fecha_revision = models.DateField(null=True, blank=True, verbose_name='Fecha de compromiso o revisión')
    estado = models.CharField(max_length=16, choices=ESTADOS, default=PENDIENTE, verbose_name='Estado del seguimiento')
    acuerdos = models.TextField(blank=True, verbose_name='Acuerdos')
    observaciones_cierre = models.TextField(blank=True, verbose_name='Observaciones de cierre')
    cerrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    cerrado_en = models.DateTimeField(null=True, blank=True)

    # Trazabilidad (el detalle de cada cambio está en CambioConducta)
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='Registró')
    creado = models.DateTimeField(auto_now_add=True, verbose_name='Registrado el')
    modificado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    modificado = models.DateTimeField(auto_now=True)
    anulado = models.BooleanField(default=False, verbose_name='Anulado')
    anulado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    anulado_en = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.TextField(blank=True, verbose_name='Motivo de la anulación')

    objects = RegistroQuerySet.as_manager()

    class Meta:
        verbose_name = 'Registro de conducta'
        verbose_name_plural = 'Registros de conducta'
        ordering = ['-fecha', '-hora', '-pk']
        indexes = [
            models.Index(fields=['fecha']),
            models.Index(fields=['alumno', 'fecha']),
        ]

    def __str__(self):
        return f'{self.alumno} · {self.motivo_nombre} · {self.fecha:%d/%m/%Y}'

    @property
    def es_incidencia(self):
        return self.tipo == INCIDENCIA

    @property
    def vencido(self):
        """El seguimiento sigue abierto y su fecha de revisión ya pasó."""
        return (
            not self.anulado and self.estado != self.CERRADO and self.fecha_revision is not None
            and self.fecha_revision < timezone.localdate()
        )


APLICADA, PENDIENTE, APROBADA, RECHAZADA, CANCELADA, ANULADA = 'APLICADA', 'PENDIENTE', 'APROBADA', 'RECHAZADA', 'CANCELADA', 'ANULADA'


class MedidaAplicada(models.Model):
    """Una medida aplicada en un registro, con su nombre y sus marcas tal como estaban al aplicarla.

    Nunca se borra: si se quita del registro queda anulada (con quién, cuándo y por qué); si requiere aprobación, queda
    pendiente hasta que alguien con el permiso de aprobar la resuelva. Solo las aplicadas cuentan en los reportes."""

    ESTADOS = [(APLICADA, 'Aplicada'), (PENDIENTE, 'Pendiente de aprobación'), (RECHAZADA, 'Rechazada'), (ANULADA, 'Anulada')]
    VIGENTES = (APLICADA, PENDIENTE)

    registro = models.ForeignKey(RegistroConducta, on_delete=models.CASCADE, related_name='medidas_aplicadas')
    medida = models.ForeignKey(MedidaDisciplinaria, on_delete=models.PROTECT, related_name='aplicaciones')
    nombre = models.CharField(max_length=100)
    requiere_seguimiento = models.BooleanField(default=False)
    implica_suspension = models.BooleanField(default=False)
    estado = models.CharField(max_length=10, choices=ESTADOS, default=APLICADA, verbose_name='Estado')
    solicitada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    solicitada_en = models.DateTimeField(null=True, blank=True)
    resuelta_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    resuelta_en = models.DateTimeField(null=True, blank=True)
    observaciones = models.TextField(blank=True, verbose_name='Observaciones de la resolución o la anulación')

    class Meta:
        verbose_name = 'Medida aplicada'
        verbose_name_plural = 'Medidas aplicadas'
        ordering = ['nombre']
        constraints = [
            models.UniqueConstraint(fields=['registro', 'medida'], name='medida_aplicada_unica'),
        ]

    def __str__(self):
        return self.nombre

    @property
    def pendiente(self):
        return self.estado == PENDIENTE


class Suspension(models.Model):
    """La suspensión de un registro. Toda suspensión necesita aprobación (`aprobacion`): la registra aprobada quien
    tiene el permiso de aprobar; la de cualquier otra persona es una solicitud pendiente, y nadie aprueba la que pidió
    él mismo. Solo una aprobada está próxima, vigente o finalizada. Nunca toca la asistencia."""

    PROXIMA, VIGENTE, FINALIZADA = 'PROXIMA', 'VIGENTE', 'FINALIZADA'
    ESTADOS = {PROXIMA: 'Próxima', VIGENTE: 'Vigente', FINALIZADA: 'Finalizada'}
    APROBACIONES = [(PENDIENTE, 'Pendiente de aprobación'), (APROBADA, 'Aprobada'), (RECHAZADA, 'Rechazada'), (CANCELADA, 'Cancelada')]

    registro = models.OneToOneField(RegistroConducta, on_delete=models.CASCADE, related_name='suspension')
    motivo = models.ForeignKey(MotivoSuspension, on_delete=models.PROTECT, related_name='suspensiones', verbose_name='Motivo de suspensión')
    motivo_nombre = models.CharField(max_length=100)
    fecha_inicio = models.DateField(verbose_name='Fecha de inicio')
    fecha_fin = models.DateField(verbose_name='Fecha de término')
    observaciones = models.TextField(blank=True, verbose_name='Observaciones')
    autorizada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='Autorizó',
    )
    aprobacion = models.CharField(max_length=10, choices=APROBACIONES, default=APROBADA, verbose_name='Aprobación')
    justificacion = models.TextField(blank=True, verbose_name='Justificación de la solicitud')
    solicitada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='Solicitó')
    solicitada_en = models.DateTimeField(null=True, blank=True)
    resuelta_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='Resolvió')
    resuelta_en = models.DateTimeField(null=True, blank=True)
    observaciones_resolucion = models.TextField(blank=True, verbose_name='Observaciones de la resolución')
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Suspensión'
        verbose_name_plural = 'Suspensiones'
        ordering = ['-fecha_inicio']
        permissions = [('aprobar_suspension', 'Aprobar o rechazar suspensiones y medidas que requieren aprobación')]
        constraints = [
            models.CheckConstraint(condition=models.Q(fecha_fin__gte=models.F('fecha_inicio')), name='suspension_fechas_en_orden'),
        ]

    def __str__(self):
        return f'{self.registro.alumno}: {self.fecha_inicio:%d/%m/%Y} al {self.fecha_fin:%d/%m/%Y}'

    @property
    def aprobada(self):
        return self.aprobacion == APROBADA

    @property
    def pendiente(self):
        return self.aprobacion == PENDIENTE

    def estado_en(self, fecha):
        """Próxima, vigente o finalizada (si está aprobada); si no, su estado de aprobación."""
        if not self.aprobada:
            return self.aprobacion
        if fecha < self.fecha_inicio:
            return self.PROXIMA
        return self.VIGENTE if fecha <= self.fecha_fin else self.FINALIZADA

    @property
    def estado(self):
        return self.estado_en(timezone.localdate())

    @property
    def estado_display(self):
        return self.ESTADOS.get(self.estado) or self.get_aprobacion_display()

    @property
    def dias(self):
        return (self.fecha_fin - self.fecha_inicio).days + 1


class EvidenciaConducta(models.Model):
    """Una foto o documento del registro. Quitarla es lógico (queda en el historial)."""

    registro = models.ForeignKey(RegistroConducta, on_delete=models.CASCADE, related_name='evidencias')
    archivo = models.FileField(upload_to=ruta_de_evidencia, max_length=200)
    nombre_original = models.CharField(max_length=200)
    tipo = models.CharField(max_length=80)
    tamano = models.PositiveIntegerField(default=0)
    activa = models.BooleanField(default=True)
    subida_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    subida_en = models.DateTimeField(auto_now_add=True)
    quitada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    quitada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Evidencia de conducta'
        verbose_name_plural = 'Evidencias de conducta'
        ordering = ['subida_en', 'pk']

    def __str__(self):
        return self.nombre_original

    @property
    def es_imagen(self):
        return self.tipo.startswith('image/')


class ContactoTutor(models.Model):
    """Un contacto con la familia por el registro. Solo se anota: no envía ningún mensaje."""

    MEDIOS = [
        ('PRESENCIAL', 'En persona'),
        ('TELEFONO', 'Llamada telefónica'),
        ('MENSAJE', 'Mensaje (WhatsApp o SMS)'),
        ('CORREO', 'Correo electrónico'),
        ('VIDEOLLAMADA', 'Videollamada'),
        ('NOTA', 'Nota o recado escrito'),
        ('OTRO', 'Otro'),
    ]

    registro = models.ForeignKey(RegistroConducta, on_delete=models.CASCADE, related_name='contactos')
    fecha = models.DateField(verbose_name='Fecha de contacto')
    tutor = models.ForeignKey(Tutor, null=True, blank=True, on_delete=models.SET_NULL, related_name='contactos_conducta', verbose_name='Padre, madre o tutor')
    persona = models.CharField(max_length=160, verbose_name='Persona contactada')
    medio = models.CharField(max_length=14, choices=MEDIOS, verbose_name='Medio')
    acuerdos = models.TextField(verbose_name='Acuerdos')
    proxima_revision = models.DateField(null=True, blank=True, verbose_name='Próxima revisión')
    evidencia = models.FileField(upload_to=ruta_de_acuse, max_length=200, blank=True, verbose_name='Evidencia o acuse')
    evidencia_nombre = models.CharField(max_length=200, blank=True)
    evidencia_tipo = models.CharField(max_length=80, blank=True)
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Contacto con la familia'
        verbose_name_plural = 'Contactos con la familia'
        ordering = ['-fecha', '-creado']

    def __str__(self):
        return f'{self.persona} · {self.fecha:%d/%m/%Y}'


class CambioConducta(models.Model):
    """Bitácora de un registro: quién hizo qué, cuándo y qué cambió (para la trazabilidad)."""

    CREADO, EDITADO, SEGUIMIENTO, CERRADO, REABIERTO, ANULADO = 'CREADO', 'EDITADO', 'SEGUIMIENTO', 'CERRADO', 'REABIERTO', 'ANULADO'
    EVIDENCIA, EVIDENCIA_QUITADA, CONTACTO, AVISO = 'EVIDENCIA', 'EVIDENCIA_QUITADA', 'CONTACTO', 'AVISO'
    SOLICITUD, RESOLUCION, CITA, COMPROMISO = 'SOLICITUD', 'RESOLUCION', 'CITA', 'COMPROMISO'
    ACCIONES = [
        (CREADO, 'Registró'),
        (EDITADO, 'Editó'),
        (SEGUIMIENTO, 'Actualizó el seguimiento'),
        (CERRADO, 'Cerró el seguimiento'),
        (REABIERTO, 'Reabrió el seguimiento'),
        (ANULADO, 'Anuló el registro'),
        (EVIDENCIA, 'Agregó evidencias'),
        (EVIDENCIA_QUITADA, 'Quitó una evidencia'),
        (CONTACTO, 'Anotó un contacto con la familia'),
        (AVISO, 'Revisó el aviso de reincidencia'),
        (SOLICITUD, 'Solicitó una aprobación'),
        (RESOLUCION, 'Resolvió una solicitud'),
        (CITA, 'Cita con la familia'),
        (COMPROMISO, 'Compromiso'),
    ]

    registro = models.ForeignKey(RegistroConducta, on_delete=models.CASCADE, related_name='cambios')
    accion = models.CharField(max_length=20, choices=ACCIONES)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    fecha = models.DateTimeField(auto_now_add=True)
    detalle = models.TextField(blank=True)
    cambios = models.JSONField(default=list, blank=True)   # [[qué, antes, después], …]

    class Meta:
        verbose_name = 'Cambio en un registro de conducta'
        verbose_name_plural = 'Cambios en registros de conducta'
        ordering = ['-fecha', '-pk']


class AvisoReincidencia(models.Model):
    """El registro con el que un estudiante llegó al umbral de su nivel. Queda para revisión: no sanciona."""

    registro = models.OneToOneField(RegistroConducta, on_delete=models.CASCADE, related_name='aviso_reincidencia')
    alumno = models.ForeignKey(Alumno, on_delete=models.CASCADE, related_name='avisos_reincidencia')
    motivo = models.ForeignKey(MotivoConducta, on_delete=models.CASCADE, related_name='avisos_reincidencia')
    cantidad = models.PositiveSmallIntegerField()
    dias = models.PositiveSmallIntegerField()
    creado = models.DateTimeField(auto_now_add=True)
    revisado = models.BooleanField(default=False)
    revisado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    revisado_en = models.DateTimeField(null=True, blank=True)
    nota = models.TextField(blank=True, verbose_name='Nota de la revisión')

    class Meta:
        verbose_name = 'Aviso de reincidencia generado'
        verbose_name_plural = 'Avisos de reincidencia generados'
        ordering = ['-creado']


class CitaTutor(models.Model):
    """Una cita con la madre, el padre o el tutor por el caso. Registrarla no envía ningún aviso: solo se anota."""

    PROGRAMADA, REALIZADA, NO_ASISTIO, CANCELADA_CITA = 'PROGRAMADA', 'REALIZADA', 'NO_ASISTIO', 'CANCELADA'
    ESTADOS = [(PROGRAMADA, 'Programada'), (REALIZADA, 'Realizada'), (NO_ASISTIO, 'No asistió'), (CANCELADA_CITA, 'Cancelada')]
    MODALIDADES = [('PRESENCIAL', 'En persona'), ('VIDEOLLAMADA', 'Videollamada'), ('TELEFONO', 'Llamada telefónica')]

    registro = models.ForeignKey(RegistroConducta, on_delete=models.CASCADE, related_name='citas')
    fecha = models.DateField(verbose_name='Fecha')
    hora = models.TimeField(null=True, blank=True, verbose_name='Hora')
    modalidad = models.CharField(max_length=14, choices=MODALIDADES, default='PRESENCIAL', verbose_name='Modalidad')
    tutor = models.ForeignKey(Tutor, null=True, blank=True, on_delete=models.SET_NULL, related_name='citas_conducta', verbose_name='Padre, madre o tutor')
    persona = models.CharField(max_length=160, verbose_name='Con quién')
    asunto = models.TextField(verbose_name='Asunto')
    responsable = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='Responsable')
    estado = models.CharField(max_length=12, choices=ESTADOS, default=PROGRAMADA, verbose_name='Estado')
    resultado = models.TextField(blank=True, verbose_name='Resultado u observaciones')
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    creado = models.DateTimeField(auto_now_add=True)
    modificado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Cita con la familia'
        verbose_name_plural = 'Citas con la familia'
        ordering = ['fecha', 'hora', 'pk']

    def __str__(self):
        return f'{self.persona} · {self.fecha:%d/%m/%Y}'

    @property
    def abierta(self):
        return self.estado == self.PROGRAMADA


class Compromiso(models.Model):
    """Un acuerdo o compromiso del caso, con quién se compromete, su responsable y su fecha límite."""

    PENDIENTE_C, CUMPLIDO, INCUMPLIDO, CANCELADO = 'PENDIENTE', 'CUMPLIDO', 'INCUMPLIDO', 'CANCELADO'
    ESTADOS = [(PENDIENTE_C, 'Pendiente'), (CUMPLIDO, 'Cumplido'), (INCUMPLIDO, 'No cumplido'), (CANCELADO, 'Cancelado')]
    QUIENES = [('ESTUDIANTE', 'El estudiante'), ('FAMILIA', 'La familia'), ('COLEGIO', 'El colegio'), ('VARIOS', 'Varios')]

    registro = models.ForeignKey(RegistroConducta, on_delete=models.CASCADE, related_name='compromisos')
    descripcion = models.TextField(verbose_name='Acuerdo o compromiso')
    quien = models.CharField(max_length=12, choices=QUIENES, default='ESTUDIANTE', verbose_name='Se compromete')
    responsable = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='Responsable del seguimiento')
    fecha_limite = models.DateField(verbose_name='Fecha límite')
    estado = models.CharField(max_length=12, choices=ESTADOS, default=PENDIENTE_C, verbose_name='Estado')
    observaciones = models.TextField(blank=True, verbose_name='Observaciones')
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    creado = models.DateTimeField(auto_now_add=True)
    resuelto_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    resuelto_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Compromiso'
        verbose_name_plural = 'Compromisos'
        ordering = ['fecha_limite', 'pk']

    def __str__(self):
        return f'{self.descripcion[:60]} · {self.fecha_limite:%d/%m/%Y}'

    @property
    def abierto(self):
        return self.estado == self.PENDIENTE_C

    @property
    def vencido(self):
        return self.abierto and self.fecha_limite < timezone.localdate()
