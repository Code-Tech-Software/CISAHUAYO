"""Bitácoras por grupo (pedido del 2026-10-14): lo que ocurrió en una clase, escrito por quien la vivió.

Una entrada es una **observación informativa y de seguimiento**: no toca calificaciones (académicas ni de conducta), no
descuenta puntos, no genera faltas disciplinarias ni aplica sanciones. Los reportes de conducta la muestran aparte
(«Observaciones de bitácora») leyendo estas mismas filas, sin copiarlas.

- Se guarda una sola vez y se vincula con todos los estudiantes implicados (`EstudianteBitacora`), o se marca como
  observación general del grupo (`general`): esa no se atribuye a ningún estudiante.
- El ciclo, periodo, nivel, grado, grupo y materia quedan como eran al registrarla (también sus nombres): si después el
  estudiante cambia de grupo o la materia cambia de nombre, la entrada sigue diciendo dónde ocurrió.
- No se borra: se anula con motivo y queda para auditoría. Cada alta, edición y anulación queda en `CambioBitacora`
  con quién, cuándo y los valores anteriores y nuevos.
Quién ve y hace qué: Bitacoras/alcance.py.
"""
from django.conf import settings
from django.db import models

from Alumnos.models import Alumno, CicloEscolar, Grado, Grupo, HorarioMateria, Inscripcion, Materia, MateriaGrado, Periodo

LEYENDA = 'Las observaciones de esta bitácora son informativas y de seguimiento. No afectan las calificaciones académicas ni de conducta.'
SELLO = 'Observación informativa — sin efecto en calificaciones'


class EntradaBitacora(models.Model):
    # Dónde y cuándo (tal como era al registrarla)
    ciclo = models.ForeignKey(CicloEscolar, on_delete=models.PROTECT, related_name='bitacoras', verbose_name='Ciclo escolar')
    periodo = models.ForeignKey(Periodo, on_delete=models.SET_NULL, null=True, blank=True, related_name='bitacoras', verbose_name='Periodo')
    nivel = models.CharField(max_length=20, choices=Grado.NIVEL_CHOICES, verbose_name='Nivel educativo')
    grado = models.ForeignKey(Grado, on_delete=models.PROTECT, related_name='+', verbose_name='Grado')
    grupo = models.ForeignKey(Grupo, on_delete=models.PROTECT, related_name='bitacoras', verbose_name='Grupo')
    grupo_texto = models.CharField(max_length=80, verbose_name='Grupo (como se llamaba)')
    asignacion = models.ForeignKey(MateriaGrado, on_delete=models.PROTECT, related_name='bitacoras', verbose_name='Materia del grupo')
    materia = models.ForeignKey(Materia, on_delete=models.PROTECT, related_name='+', verbose_name='Materia')
    materia_nombre = models.CharField(max_length=100, verbose_name='Materia (como se llamaba)')
    fecha = models.DateField(verbose_name='Fecha de la clase')
    bloque = models.ForeignKey(HorarioMateria, on_delete=models.SET_NULL, null=True, blank=True, related_name='+', verbose_name='Bloque del horario')
    hora_inicio = models.TimeField(null=True, blank=True, verbose_name='Inicio de la clase')
    hora_fin = models.TimeField(null=True, blank=True, verbose_name='Fin de la clase')

    # Qué pasó
    general = models.BooleanField(default=False, verbose_name='Observación general del grupo')
    alumnos = models.ManyToManyField(Alumno, through='EstudianteBitacora', related_name='entradas_bitacora', blank=True, verbose_name='Estudiantes implicados')
    titulo = models.CharField(max_length=120, verbose_name='Título')
    descripcion = models.TextField(verbose_name='Descripción de lo ocurrido')
    seguimiento = models.TextField(blank=True, verbose_name='Acuerdos o acciones de seguimiento')

    # Quién y cuándo se registró (distinto de la fecha de la clase)
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+', verbose_name='Autor')
    autor_nombre = models.CharField(max_length=150, verbose_name='Autor (como se llamaba)')
    creado = models.DateTimeField(auto_now_add=True, verbose_name='Registrada el')
    modificado = models.DateTimeField(auto_now=True)
    ediciones = models.PositiveSmallIntegerField(default=0, verbose_name='Veces que se editó')
    editada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    editada_en = models.DateTimeField(null=True, blank=True, verbose_name='Última edición')
    anulada = models.BooleanField(default=False, verbose_name='Anulada')
    anulada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    anulada_en = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.TextField(blank=True, verbose_name='Motivo de la anulación')
    # El mismo formulario enviado dos veces (doble clic, recarga) guarda una sola entrada
    clave_envio = models.UUIDField(null=True, blank=True, unique=True, editable=False)

    class Meta:
        verbose_name = 'Entrada de bitácora'
        verbose_name_plural = 'Entradas de bitácora'
        ordering = ['-fecha', '-hora_inicio', '-creado']
        default_permissions = ()
        permissions = [
            ('registrar', 'Registrar y consultar la bitácora de sus clases (docente)'),
            ('consultar_todas', 'Consultar las bitácoras de todos los grupos de su alcance'),
            ('registrar_todas', 'Registrar en la bitácora de cualquier grupo de su alcance'),
            ('gestionar', 'Editar o anular entradas de otros usuarios y consultar las anuladas'),
        ]
        indexes = [
            models.Index(fields=['grupo', 'fecha'], name='bitacora_grupo_fecha'),
            models.Index(fields=['ciclo', 'fecha'], name='bitacora_ciclo_fecha'),
        ]

    def __str__(self):
        return f'{self.fecha:%d/%m/%Y} · {self.grupo_texto} · {self.materia_nombre} · {self.titulo}'

    @property
    def editada(self):
        return self.ediciones > 0


class EstudianteBitacora(models.Model):
    """Un estudiante implicado en una entrada, con la inscripción que tenía (el grupo de la entrada es el de entonces)."""

    entrada = models.ForeignKey(EntradaBitacora, on_delete=models.CASCADE, related_name='vinculos')
    alumno = models.ForeignKey(Alumno, on_delete=models.PROTECT, related_name='vinculos_bitacora', verbose_name='Estudiante')
    inscripcion = models.ForeignKey(Inscripcion, on_delete=models.PROTECT, null=True, blank=True, related_name='+')

    class Meta:
        verbose_name = 'Estudiante de una entrada de bitácora'
        verbose_name_plural = 'Estudiantes de entradas de bitácora'
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=['entrada', 'alumno'], name='bitacora_estudiante_unico')]

    def __str__(self):
        return f'{self.alumno} · {self.entrada}'


class CambioBitacora(models.Model):
    """Historial de una entrada: alta, ediciones (con los valores anteriores y nuevos) y anulación (con su motivo)."""

    CREACION, EDICION, ANULACION = 'CREACION', 'EDICION', 'ANULACION'
    ACCIONES = [(CREACION, 'Registro'), (EDICION, 'Edición'), (ANULACION, 'Anulación')]

    entrada = models.ForeignKey(EntradaBitacora, on_delete=models.CASCADE, related_name='cambios')
    accion = models.CharField(max_length=12, choices=ACCIONES)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    usuario_nombre = models.CharField(max_length=150)
    fecha = models.DateTimeField(auto_now_add=True)
    motivo = models.TextField(blank=True)
    cambios = models.JSONField(default=list, blank=True)   # [[qué, antes, después], …]

    class Meta:
        verbose_name = 'Cambio de una entrada de bitácora'
        verbose_name_plural = 'Cambios de entradas de bitácora'
        ordering = ['-fecha', '-pk']
        default_permissions = ()

    def __str__(self):
        return f'{self.get_accion_display()} de {self.entrada_id} · {self.fecha:%d/%m/%Y %H:%M}'
