"""Comunicados (pedido del 2026-10-16): publicaciones informativas del colegio para tutores, estudiantes, profesores y, desde
el 2026-10-27, el personal no docente, con su lista de destinatarios y el seguimiento de lectura de cada uno.

Son independientes de la mensajería (Mensajes/): no son conversaciones. Las personas son las del proyecto (`Alumno`,
`Tutor`, `Profesor` y las cuentas del personal): un `Destinatario` apunta a exactamente una de ellas. La lista de
destinatarios queda fija al enviar (las inscripciones posteriores no agregan a nadie) y cada uno guarda su primera
lectura. Quién puede enviar a quién: Comunicados/alcance.py; las operaciones: Comunicados/reglas.py.

Desde el 2026-10-27 un comunicado puede: llevar formato (`html`, limpio con Mensajes/enriquecido.py, con imágenes dentro
del texto: `ImagenComunicado`); pedir una respuesta («Enterado», una autorización Sí/No o una encuesta); programarse
(`publicado_en` en el futuro: sus destinatarios lo ven desde ese momento y el aviso sale entonces, `avisado_en`);
corregirse después de enviado (`editado`); fijarse arriba y tener categoría; y marcar un evento que aparece en la agenda.

Un comunicado eliminado no se borra (`eliminado`): deja de verse para todos y queda en la base y en el historial de
cambios (LogEntry) para su trazabilidad.
"""
import uuid
from pathlib import Path

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.formats import date_format

from Alumnos.models import Alumno, Grupo, Profesor, Tutor


def ruta_de_adjunto(instancia, nombre):
    """Nombre al azar (sin el del archivo original): la dirección no se puede adivinar ni se muestra; los archivos solo
    se entregan por las vistas del módulo, que revisan quién los pide (como las evidencias de Conducta)."""
    extension = Path(nombre).suffix.lower()[:10]
    return f'comunicados/{timezone.localdate():%Y/%m}/{uuid.uuid4().hex}{extension}'


class ComunicadoQuerySet(models.QuerySet):
    def visibles(self):
        """Los que no se eliminaron."""
        return self.filter(eliminado=False)

    def publicados(self, ahora=None):
        """Los que ya llegaron a su momento de publicación (los programados para después, todavía no)."""
        return self.filter(publicado_en__lte=ahora or timezone.now())

    def activos(self, ahora=None):
        """Los que no han caducado (sin fecha de expiración, o con una todavía por llegar)."""
        ahora = ahora or timezone.now()
        return self.filter(Q(expira__isnull=True) | Q(expira__gt=ahora))

    def caducados(self, ahora=None):
        return self.filter(expira__lte=ahora or timezone.now())


class Comunicado(models.Model):
    MAXIMO_TITULO = 150
    MAXIMO_DESCRIPCION = 5000      # caracteres de texto
    MAXIMO_HTML = 60000            # el HTML limpio, con su formato
    MAXIMO_ADJUNTOS = 5
    MAXIMO_OPCIONES = 6

    # Qué se pide a quien lo recibe
    SIN_RESPUESTA, ENTERADO, AUTORIZACION, ENCUESTA = '', 'ENTERADO', 'AUTORIZACION', 'ENCUESTA'
    RESPUESTAS = [(SIN_RESPUESTA, 'Solo informar'), (ENTERADO, 'Confirmar de enterado'), (AUTORIZACION, 'Autorización (Sí / No)'),
                  (ENCUESTA, 'Encuesta')]
    # Categorías (con su tono de color: la clase tag--tono-N)
    ACADEMICO, EVENTOS, ADMINISTRATIVO, SALUD = 'ACADEMICO', 'EVENTOS', 'ADMINISTRATIVO', 'SALUD'
    CATEGORIAS = [(ACADEMICO, 'Académico'), (EVENTOS, 'Eventos'), (ADMINISTRATIVO, 'Administrativo'), (SALUD, 'Salud y seguridad')]
    TONO_DE_CATEGORIA = {ACADEMICO: 1, EVENTOS: 2, ADMINISTRATIVO: 3, SALUD: 4}

    titulo = models.CharField('título', max_length=MAXIMO_TITULO)
    # El texto plano (tarjetas, avisos, búsqueda y los comunicados anteriores al editor, que no tienen `html`)
    descripcion = models.TextField('descripción', max_length=MAXIMO_DESCRIPCION)
    html = models.TextField(blank=True, default='')
    urgente = models.BooleanField(default=False)
    expira = models.DateTimeField('fecha de expiración', null=True, blank=True,
                                  help_text='A partir de esta fecha deja de mostrarse a los destinatarios.')
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='comunicados_enviados')
    # El rol de quien lo envió, tal como era al enviarlo («Docente», «Dirección»…): lo muestra «Creado por»
    rol_autor = models.CharField('rol del autor', max_length=80, blank=True)
    creado = models.DateTimeField(default=timezone.now, db_index=True)
    # Desde cuándo lo ven sus destinatarios: al enviarlo, o la fecha y hora programadas. El aviso (en tiempo real y push)
    # sale al publicarse: `avisado_en` vacío = programado y todavía sin avisar (Comunicados/avisos.py)
    publicado_en = models.DateTimeField('publicación', default=timezone.now, db_index=True)
    avisado_en = models.DateTimeField(null=True, blank=True)
    # Lo genera el formulario al abrirse: un doble clic o un reintento del mismo envío no crea un segundo comunicado
    clave_envio = models.UUIDField(unique=True, editable=False)
    categoria = models.CharField('categoría', max_length=20, choices=CATEGORIAS, blank=True)
    fijado = models.BooleanField(default=False, help_text='Se muestra arriba de los demás a quien lo recibe.')
    respuesta = models.CharField('respuesta que se pide', max_length=20, choices=RESPUESTAS, blank=True)
    pregunta = models.CharField(max_length=200, blank=True)
    # Un evento (aparece en la agenda de quien lo recibe y se puede agregar al calendario del teléfono)
    evento_fecha = models.DateField('fecha del evento', null=True, blank=True)
    evento_hora_inicio = models.TimeField('hora de inicio del evento', null=True, blank=True)
    evento_hora_fin = models.TimeField('hora de fin del evento', null=True, blank=True)
    evento_lugar = models.CharField('lugar del evento', max_length=150, blank=True)
    # Corregido después de enviarse (los destinatarios lo ven «Editado»)
    editado = models.DateTimeField(null=True, blank=True)
    editado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    # El último «Recordar a los pendientes» (uno por hora como máximo) y cuántos van
    recordado_en = models.DateTimeField(null=True, blank=True)
    recordatorios = models.PositiveSmallIntegerField(default=0)
    eliminado = models.BooleanField(default=False, db_index=True)
    eliminado_en = models.DateTimeField(null=True, blank=True)
    eliminado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    objects = ComunicadoQuerySet.as_manager()

    class Meta:
        verbose_name = 'Comunicado'
        verbose_name_plural = 'Comunicados'
        ordering = ['-publicado_en', '-pk']
        default_permissions = ()
        permissions = [
            ('recibir', 'Consultar los comunicados que recibe (profesores y personal)'),
            ('seguimiento', 'Consultar sus comunicados enviados y quién los ha leído'),
            ('enviar', 'Enviar comunicados a los niveles que tiene asignados'),
            ('enviar_personal', 'Enviar comunicados al personal del colegio'),
            ('eliminar', 'Eliminar sus propios comunicados'),
            ('gestionar', 'Gestionar los comunicados de todo el colegio'),
        ]

    def __str__(self):
        return self.titulo

    def caducado_en(self, ahora=None):
        return self.expira is not None and self.expira <= (ahora or timezone.now())

    @property
    def caducado(self):
        return self.caducado_en()

    @property
    def activo(self):
        return not self.caducado

    @property
    def programado(self):
        """Todavía no llega su momento de publicación."""
        return self.publicado_en > timezone.now()

    @property
    def pide_respuesta(self):
        return bool(self.respuesta)

    @property
    def nombre_categoria(self):
        return dict(self.CATEGORIAS).get(self.categoria, '')

    @property
    def tono_categoria(self):
        return self.TONO_DE_CATEGORIA.get(self.categoria, 1)

    @property
    def tiene_evento(self):
        return self.evento_fecha is not None

    @property
    def texto_del_evento(self):
        """«Viernes 7 de noviembre de 2026 · 9:00 a 11:00 · Auditorio»."""
        if not self.tiene_evento:
            return ''
        partes = [date_format(self.evento_fecha, 'l j \\d\\e F \\d\\e Y').capitalize()]
        if self.evento_hora_inicio and self.evento_hora_fin:
            partes.append(f'{self.evento_hora_inicio:%H:%M} a {self.evento_hora_fin:%H:%M}')
        elif self.evento_hora_inicio:
            partes.append(f'{self.evento_hora_inicio:%H:%M}')
        else:
            partes.append('Todo el día')
        if self.evento_lugar:
            partes.append(self.evento_lugar)
        return ' · '.join(partes)


class OpcionEncuesta(models.Model):
    """Una de las respuestas que ofrece un comunicado de tipo encuesta."""

    comunicado = models.ForeignKey(Comunicado, on_delete=models.CASCADE, related_name='opciones')
    texto = models.CharField(max_length=120)
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = 'Opción de una encuesta'
        verbose_name_plural = 'Opciones de encuestas'
        default_permissions = ()
        ordering = ['orden', 'pk']

    def __str__(self):
        return self.texto


class Destinatario(models.Model):
    ESTUDIANTE, TUTOR, PROFESOR, PERSONAL = 'ESTUDIANTE', 'TUTOR', 'PROFESOR', 'PERSONAL'
    TIPOS = [(TUTOR, 'Tutor'), (ESTUDIANTE, 'Estudiante'), (PROFESOR, 'Profesor'), (PERSONAL, 'Personal')]
    # Lo que guarda `respuesta` (en una encuesta: OPCION, con la opción elegida en `opcion`)
    RESPUESTA_ENTERADO, RESPUESTA_SI, RESPUESTA_NO, RESPUESTA_OPCION = 'ENTERADO', 'SI', 'NO', 'OPCION'

    comunicado = models.ForeignKey(Comunicado, on_delete=models.CASCADE, related_name='destinatarios')
    tipo = models.CharField(max_length=10, choices=TIPOS)
    alumno = models.ForeignKey(Alumno, on_delete=models.CASCADE, null=True, blank=True, related_name='comunicados_recibidos')
    tutor = models.ForeignKey(Tutor, on_delete=models.CASCADE, null=True, blank=True, related_name='comunicados_recibidos')
    profesor = models.ForeignKey(Profesor, on_delete=models.CASCADE, null=True, blank=True, related_name='comunicados_recibidos')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='comunicados_recibidos')
    # Cómo se le ubicaba al enviarlo («2.º A · Primaria», «Tutor de Ana López (2.º A)», el rol de una cuenta del personal)
    detalle = models.CharField(max_length=250, blank=True)
    # El grupo con que cuenta en «Lectura por grupo» (el del estudiante; el de su primer hijo, para un tutor), al enviarlo
    grupo = models.ForeignKey(Grupo, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    # La primera vez que abrió el comunicado (las siguientes no la cambian)
    leido_en = models.DateTimeField('leído el', null=True, blank=True)
    # Su respuesta, si el comunicado pide una (la puede cambiar mientras el comunicado siga activo)
    respuesta = models.CharField(max_length=10, blank=True)
    opcion = models.ForeignKey(OpcionEncuesta, on_delete=models.SET_NULL, null=True, blank=True, related_name='elegida_por')
    respondido_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Destinatario de un comunicado'
        verbose_name_plural = 'Destinatarios de comunicados'
        default_permissions = ()
        constraints = [
            models.CheckConstraint(
                condition=(Q(tipo='ESTUDIANTE', alumno__isnull=False, tutor__isnull=True, profesor__isnull=True, usuario__isnull=True)
                           | Q(tipo='TUTOR', alumno__isnull=True, tutor__isnull=False, profesor__isnull=True, usuario__isnull=True)
                           | Q(tipo='PROFESOR', alumno__isnull=True, tutor__isnull=True, profesor__isnull=False, usuario__isnull=True)
                           | Q(tipo='PERSONAL', alumno__isnull=True, tutor__isnull=True, profesor__isnull=True, usuario__isnull=False)),
                name='destinatario_una_sola_persona',
            ),
            # Cada persona recibe una sola copia (un tutor con varios hijos, también)
            models.UniqueConstraint(fields=['comunicado', 'alumno'], condition=Q(alumno__isnull=False), name='destinatario_estudiante_unico'),
            models.UniqueConstraint(fields=['comunicado', 'tutor'], condition=Q(tutor__isnull=False), name='destinatario_tutor_unico'),
            models.UniqueConstraint(fields=['comunicado', 'profesor'], condition=Q(profesor__isnull=False), name='destinatario_profesor_unico'),
            models.UniqueConstraint(fields=['comunicado', 'usuario'], condition=Q(usuario__isnull=False), name='destinatario_personal_unico'),
        ]
        indexes = [models.Index(fields=['comunicado', 'leido_en'], name='destinatario_lectura')]

    def __str__(self):
        return f'{self.persona} · {self.comunicado}'

    @property
    def persona(self):
        return {self.ESTUDIANTE: self.alumno, self.TUTOR: self.tutor, self.PROFESOR: self.profesor, self.PERSONAL: self.usuario}[self.tipo]

    @property
    def nombre(self):
        persona = self.persona
        if persona is None:
            return ''
        if self.tipo == self.PERSONAL:
            return persona.get_full_name() or persona.get_username()
        return persona.nombre_completo

    @property
    def leido(self):
        return self.leido_en is not None

    @property
    def respondio(self):
        return self.respondido_en is not None

    @property
    def para_quien(self):
        """A un tutor: de cuál de sus hijos trata («Ana López (2.º A)»), sacado de cómo se le ubicaba al enviarlo."""
        if self.tipo != self.TUTOR or not self.detalle.startswith('Tutor de '):
            return ''
        return self.detalle[len('Tutor de '):]

    @property
    def texto_de_respuesta(self):
        if not self.respondio:
            return ''
        if self.respuesta == self.RESPUESTA_OPCION:
            return self.opcion.texto if self.opcion_id else 'Opción retirada'
        return {self.RESPUESTA_ENTERADO: 'Enterado', self.RESPUESTA_SI: 'Sí autoriza', self.RESPUESTA_NO: 'No autoriza'}.get(self.respuesta, '')


class Adjunto(models.Model):
    comunicado = models.ForeignKey(Comunicado, on_delete=models.CASCADE, related_name='adjuntos')
    archivo = models.FileField(upload_to=ruta_de_adjunto, max_length=200)
    nombre_original = models.CharField(max_length=200)
    tipo = models.CharField(max_length=80)
    tamano = models.PositiveIntegerField(default=0)
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = 'Archivo de un comunicado'
        verbose_name_plural = 'Archivos de comunicados'
        default_permissions = ()
        ordering = ['orden', 'pk']

    def __str__(self):
        return self.nombre_original

    @property
    def es_imagen(self):
        return self.tipo.startswith('image/')


def ruta_de_imagen(instancia, nombre):
    extension = Path(nombre).suffix.lower()[:10]
    return f'comunicados/texto/{timezone.localdate():%Y/%m}/{uuid.uuid4().hex}{extension}'


class ImagenComunicado(models.Model):
    """Una imagen dentro del texto con formato (va en el HTML como <img data-imagen="id">). Mientras no se envía el
    comunicado (`comunicado` vacío) solo la ve quien la subió; después, quien puede ver el comunicado. Las que nunca se
    envían se borran al día siguiente (Comunicados/avisos.limpiar_imagenes)."""

    TAMANO_MAXIMO_MB = 5

    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    comunicado = models.ForeignKey(Comunicado, on_delete=models.CASCADE, null=True, blank=True, related_name='imagenes')
    archivo = models.FileField(upload_to=ruta_de_imagen, max_length=200)
    nombre_original = models.CharField(max_length=200)
    tipo = models.CharField(max_length=80)
    tamano = models.PositiveIntegerField(default=0)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Imagen del texto de un comunicado'
        verbose_name_plural = 'Imágenes del texto de comunicados'
        default_permissions = ()

    def __str__(self):
        return self.nombre_original
