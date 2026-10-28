"""Mensajería interna (pedido del 2026-10-14): conversaciones individuales entre estudiantes, tutores y usuarios del
sistema (docentes y personal), en tiempo real.

Las tres clases de cuenta siguen separadas: un `Participante` envuelve exactamente una (un usuario del sistema, un
`Alumno` o un `Tutor`) y es lo único que la mensajería conoce. Las conversaciones y los mensajes se guardan aquí, en
la base de datos del proyecto (sobreviven a cualquier reinicio); Redis solo reparte los avisos en tiempo real
(Mensajes/tiempo_real.py). Quién puede escribirle a quién: Mensajes/reglas.py.

Desde el 2026-10-17 un mensaje puede llevar formato (negritas, listas, tablas, enlaces, imágenes…): `html` guarda la
versión limpia (Mensajes/enriquecido.py) y `texto`, la de texto plano (vista previa, avisos, búsqueda). Los mensajes
anteriores, sin `html`, se siguen mostrando como texto.

Desde el 2026-10-20 el administrador puede retirar mensajes inapropiados (moderación, Mensajes/moderacion.py): se borran
por completo, sin dejar copia ni marca.
"""
import uuid
from datetime import time
from pathlib import Path

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from Alumnos.models import Alumno, Tutor


class Participante(models.Model):
    SISTEMA, ESTUDIANTE, TUTOR = 'SISTEMA', 'ESTUDIANTE', 'TUTOR'
    TIPOS = [(SISTEMA, 'Usuario del sistema'), (ESTUDIANTE, 'Estudiante'), (TUTOR, 'Tutor')]

    tipo = models.CharField(max_length=10, choices=TIPOS)
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='participante_mensajes')
    alumno = models.OneToOneField(Alumno, on_delete=models.CASCADE, null=True, blank=True, related_name='participante_mensajes')
    tutor = models.OneToOneField(Tutor, on_delete=models.CASCADE, null=True, blank=True, related_name='participante_mensajes')
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Participante de la mensajería'
        verbose_name_plural = 'Participantes de la mensajería'
        default_permissions = ()
        permissions = [
            ('usar', 'Usar la mensajería con otros usuarios del sistema (y un docente, con sus estudiantes y sus tutores)'),
            ('contactar_familias', 'Escribir a estudiantes y tutores y atender sus mensajes'),
            ('moderar', 'Buscar en todas las conversaciones y retirar mensajes inapropiados'),
        ]
        constraints = [
            # Exactamente una cuenta, la de su tipo
            models.CheckConstraint(
                condition=(Q(tipo='SISTEMA', usuario__isnull=False, alumno__isnull=True, tutor__isnull=True)
                           | Q(tipo='ESTUDIANTE', usuario__isnull=True, alumno__isnull=False, tutor__isnull=True)
                           | Q(tipo='TUTOR', usuario__isnull=True, alumno__isnull=True, tutor__isnull=False)),
                name='participante_una_sola_cuenta',
            ),
        ]

    def __str__(self):
        return self.nombre

    @property
    def cuenta(self):
        return self.usuario if self.tipo == self.SISTEMA else (self.alumno if self.tipo == self.ESTUDIANTE else self.tutor)

    @property
    def nombre(self):
        if self.tipo == self.SISTEMA:
            return self.usuario.get_full_name() or self.usuario.get_username()
        return self.cuenta.nombre_completo

    @property
    def iniciales(self):
        if self.tipo == self.SISTEMA:
            partes = [p for p in (self.usuario.first_name, self.usuario.last_name) if p] or [self.usuario.get_username()]
            return ''.join(p[0] for p in partes)[:2].upper()
        return self.cuenta.iniciales

    @property
    def tipo_corto(self):
        """La clase de cuenta en una palabra (en la moderación, junto al nombre)."""
        return {self.SISTEMA: 'Personal', self.ESTUDIANTE: 'Estudiante', self.TUTOR: 'Tutor'}[self.tipo]

    @property
    def clave(self):
        """Cómo se identifica la cuenta fuera de la base («u:7», «a:12», «t:3»), en búsquedas y formularios."""
        return {self.SISTEMA: f'u:{self.usuario_id}', self.ESTUDIANTE: f'a:{self.alumno_id}', self.TUTOR: f't:{self.tutor_id}'}[self.tipo]


class Conversacion(models.Model):
    """Una conversación individual entre dos participantes (`clave`: sus ids ordenados, para que sea una sola)."""

    clave = models.CharField(max_length=40, unique=True)
    participantes = models.ManyToManyField(Participante, through='Miembro', related_name='conversaciones')
    creada = models.DateTimeField(auto_now_add=True)
    actualizada = models.DateTimeField(auto_now_add=True, db_index=True)   # la del último mensaje: ordena la bandeja
    ultimo_mensaje = models.ForeignKey('Mensaje', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        verbose_name = 'Conversación'
        verbose_name_plural = 'Conversaciones'
        default_permissions = ()
        ordering = ['-actualizada']

    def __str__(self):
        return f'Conversación {self.clave}'

    @staticmethod
    def clave_de(*participantes):
        return '-'.join(str(pk) for pk in sorted(p.pk for p in participantes))


class Miembro(models.Model):
    """Un participante en una conversación, con hasta dónde leyó (el id del último mensaje leído)."""

    conversacion = models.ForeignKey(Conversacion, on_delete=models.CASCADE, related_name='miembros')
    participante = models.ForeignKey(Participante, on_delete=models.CASCADE, related_name='membresias')
    ultimo_leido = models.PositiveBigIntegerField(default=0)
    leido_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Miembro de una conversación'
        verbose_name_plural = 'Miembros de conversaciones'
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=['conversacion', 'participante'], name='miembro_unico')]

    def __str__(self):
        return f'{self.participante} en {self.conversacion}'


class Mensaje(models.Model):
    MAXIMO = 2000            # caracteres de texto
    MAXIMO_HTML = 40000      # el HTML limpio, con su formato (tablas, listas, estilos)

    conversacion = models.ForeignKey(Conversacion, on_delete=models.CASCADE, related_name='mensajes')
    autor = models.ForeignKey(Participante, on_delete=models.CASCADE, related_name='mensajes_enviados')
    texto = models.TextField(max_length=MAXIMO)
    # Vacío en los mensajes sin formato (y en todos los anteriores al editor): se muestran como texto
    html = models.TextField(blank=True, default='')
    # Solo documentos, sin nada escrito: `texto` es su resumen («📎 circular.pdf») para vistas previas, avisos y
    # búsquedas, y la burbuja no lo muestra (ya muestra los documentos)
    sin_texto = models.BooleanField(default=False)
    creado = models.DateTimeField(auto_now_add=True)
    # Cuándo lo leyó la otra persona (vacío: sin leer, o leído antes del 2026-10-20, cuando no se guardaba la hora)
    leido_en = models.DateTimeField(null=True, blank=True)
    # El mensaje al que responde citándolo (2026-10-23); si ese se retira, la cita desaparece
    responde_a = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    # Cuándo lo corrigió su autor (solo se puede en los primeros minutos: reglas.MINUTOS_PARA_EDITAR); vacío si nunca
    editado = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Mensaje'
        verbose_name_plural = 'Mensajes'
        default_permissions = ()
        ordering = ['pk']
        indexes = [models.Index(fields=['conversacion', 'id'], name='mensaje_conversacion_id')]

    def __str__(self):
        return f'{self.autor}: {self.texto[:40]}'


def ruta_de_imagen(instancia, nombre):
    """Nombre al azar: la dirección del archivo no se adivina ni se muestra; se entrega solo por Mensajes/views.imagen."""
    extension = Path(nombre).suffix.lower()[:10]
    return f'mensajes/{timezone.localdate():%Y/%m}/{uuid.uuid4().hex}{extension}'


class ImagenMensaje(models.Model):
    """Un archivo subido a una conversación: una imagen del editor (va dentro del HTML del mensaje) o, desde el
    2026-10-20, un documento PDF adjunto (va debajo del texto). Mientras no se envía el mensaje (`mensaje` vacío) solo
    lo ve quien lo subió; después, los miembros de la conversación. Lo que nunca se envía se borra al día siguiente
    (Mensajes/limpieza.py)."""

    DOCUMENTO = 'application/pdf'
    TAMANO_MAXIMO_MB = 5
    PENDIENTES_MAXIMAS = 20   # subidas sin enviar por persona y conversación
    DOCUMENTOS_POR_MENSAJE = 10

    conversacion = models.ForeignKey(Conversacion, on_delete=models.CASCADE, related_name='imagenes')
    autor = models.ForeignKey(Participante, on_delete=models.CASCADE, related_name='imagenes_subidas')
    mensaje = models.ForeignKey(Mensaje, on_delete=models.CASCADE, null=True, blank=True, related_name='imagenes')
    archivo = models.FileField(upload_to=ruta_de_imagen, max_length=200)
    nombre_original = models.CharField(max_length=200)
    tipo = models.CharField(max_length=80)
    tamano = models.PositiveIntegerField(default=0)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Archivo de un mensaje'
        verbose_name_plural = 'Archivos de mensajes'
        default_permissions = ()
        indexes = [models.Index(fields=['conversacion', 'autor', 'mensaje'], name='imagen_mensaje_pendiente')]

    def __str__(self):
        return self.nombre_original

    @property
    def es_documento(self):
        return self.tipo == self.DOCUMENTO

    @property
    def tamano_texto(self):
        """«PDF · 240 KB» / «PDF · 1.3 MB»."""
        if self.tamano >= 1024 * 1024:
            return f'PDF · {self.tamano / (1024 * 1024):.1f} MB'
        return f'PDF · {max(1, round(self.tamano / 1024))} KB'

    def como_dict(self, url):
        return {'id': self.pk, 'nombre': self.nombre_original, 'tamano': self.tamano_texto, 'url': url}


class ReporteMensaje(models.Model):
    """Un mensaje que reportó como inapropiado la persona que lo recibió (pedido del 2026-10-27). Lo revisa el
    administrador en la moderación (Mensajes/moderacion.py): si retira el mensaje, el reporte se borra con él (sin
    rastro); si no, lo descarta. Quien escribió el mensaje no se entera."""

    MOTIVO_MAXIMO = 300

    mensaje = models.ForeignKey(Mensaje, on_delete=models.CASCADE, related_name='reportes')
    participante = models.ForeignKey(Participante, on_delete=models.CASCADE, related_name='reportes')
    motivo = models.CharField(max_length=MOTIVO_MAXIMO, blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Mensaje reportado'
        verbose_name_plural = 'Mensajes reportados'
        default_permissions = ()
        ordering = ['-creado']
        constraints = [models.UniqueConstraint(fields=['mensaje', 'participante'], name='reporte_unico')]

    def __str__(self):
        return f'Reporte de {self.participante} sobre el mensaje {self.mensaje_id}'


class ConfiguracionMensajes(models.Model):
    """Una sola fila (pk=1): el horario de atención de la mensajería (pedido del 2026-10-27). Fuera de él (de noche, en
    fin de semana o en un día sin clases de todo el colegio), los estudiantes y las familias ven al escribirle al
    personal que la respuesta puede llegar hasta el siguiente día de clases. No impide escribir."""

    avisar_fuera_de_horario = models.BooleanField(
        'avisar a las familias fuera del horario de atención', default=True,
        help_text='Al escribirle a un docente o al personal fuera del horario, el estudiante o el tutor ve que la respuesta '
                  'puede llegar hasta el siguiente día de clases.')
    hora_inicio = models.TimeField('horario de atención: desde', default=time(7, 0))
    hora_fin = models.TimeField('hasta', default=time(15, 0))
    modificado = models.DateTimeField(auto_now=True)
    modificado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        verbose_name = 'configuración de la mensajería'
        verbose_name_plural = 'configuración de la mensajería'
        default_permissions = ()

    def __str__(self):
        return 'Configuración de la mensajería'

    @classmethod
    def actual(cls):
        configuracion, _ = cls.objects.get_or_create(pk=1)
        return configuracion


class SuscripcionPush(models.Model):
    """Un navegador (una computadora o un celular) que recibe el aviso de los mensajes nuevos aunque la página esté
    cerrada (notificaciones push, pedido del 2026-10-27: Mensajes/push.py). Si el servicio de push dice que ya no
    existe, se borra; al cerrar sesión en ese navegador, también."""

    participante = models.ForeignKey(Participante, on_delete=models.CASCADE, related_name='suscripciones_push')
    endpoint = models.URLField(max_length=1000, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Suscripción a notificaciones push'
        verbose_name_plural = 'Suscripciones a notificaciones push'
        default_permissions = ()

    def __str__(self):
        return f'Notificaciones push de {self.participante}'
