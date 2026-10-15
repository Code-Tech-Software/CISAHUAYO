"""Formularios del módulo de conducta: catálogos, registro, seguimiento, anulación, evidencias, contactos y filtros.

El servidor valida todo aunque la pantalla ya lo cuide: que la categoría y el motivo sean del nivel del estudiante y del
tipo elegido, que lo inactivo no se use en registros nuevos, que una conducta positiva no lleve medidas, que una
suspensión tenga motivo y fechas válidas, y el tipo y el tamaño de cada archivo.
"""
from datetime import date

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from Alumnos.academico import ciclo_actual
from Alumnos.forms import EstiloCamposMixin
from Alumnos.models import Alumno, CicloEscolar, Grado, Grupo, Periodo, TutorAlumno, orden_de_nivel

from . import permisos, reglas
from .models import (
    APROBADA,
    GRAVEDADES,
    INCIDENCIA,
    NIVELES,
    PENDIENTE,
    POSITIVA,
    TIPOS,
    CategoriaConducta,
    CitaTutor,
    Compromiso,
    ContactoTutor,
    MedidaAplicada,
    MedidaDisciplinaria,
    MotivoConducta,
    MotivoSuspension,
    RegistroConducta,
    ReglaReincidencia,
)

FECHA = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')
HORA = forms.TimeInput(attrs={'type': 'time'}, format='%H:%M')

# Archivos: fotos y PDF, hasta 5 MB cada uno (se revisa el contenido, no solo la extensión)
TAMANO_MAXIMO_MB = 5
EVIDENCIAS_POR_ENVIO = 5
EVIDENCIAS_POR_REGISTRO = 20
TIPOS_DE_ARCHIVO = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png', 'webp': 'image/webp', 'pdf': 'application/pdf'}
ACEPTA = '.jpg,.jpeg,.png,.webp,.pdf'


def validar_archivo(archivo):
    """El tipo real del archivo ('image/png', 'application/pdf'…) si es una foto o un PDF de hasta 5 MB; si no, error."""
    extension = archivo.name.rsplit('.', 1)[-1].lower() if '.' in archivo.name else ''
    if extension not in TIPOS_DE_ARCHIVO:
        raise ValidationError(f'«{archivo.name}»: solo se aceptan fotos (JPG, PNG o WEBP) y documentos PDF.')
    if archivo.size > TAMANO_MAXIMO_MB * 1024 * 1024:
        raise ValidationError(f'«{archivo.name}» pesa más de {TAMANO_MAXIMO_MB} MB.')
    if archivo.size == 0:
        raise ValidationError(f'«{archivo.name}» está vacío.')
    archivo.seek(0)
    cabecera = archivo.read(8)
    archivo.seek(0)
    tipo = TIPOS_DE_ARCHIVO[extension]
    if tipo == 'application/pdf':
        if not cabecera.startswith(b'%PDF-'):
            raise ValidationError(f'«{archivo.name}» no es un PDF válido.')
        return tipo
    try:
        from PIL import Image
        imagen = Image.open(archivo)
        formato = imagen.format
        imagen.verify()
    except Exception:
        raise ValidationError(f'«{archivo.name}» no es una imagen válida o está dañada.') from None
    finally:
        archivo.seek(0)
    formatos = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'WEBP': 'image/webp'}
    if formato not in formatos:
        raise ValidationError(f'«{archivo.name}»: solo se aceptan fotos JPG, PNG o WEBP.')
    return formatos[formato]


def _texto(valor):
    return ' '.join((valor or '').split())


class UsuarioField(forms.ModelChoiceField):
    """Una cuenta del sistema, por su nombre."""

    def label_from_instance(self, usuario):
        return usuario.get_full_name() or usuario.get_username()


def _casillas(formulario):
    """Las casillas sueltas (activo, requiere seguimiento…) con el estilo de las casillas del sistema."""
    for campo in formulario.fields.values():
        if type(campo.widget) is forms.CheckboxInput:
            campo.widget.attrs['class'] = 'choice__input'


def usuarios_activos():
    return get_user_model().objects.filter(is_active=True).order_by('first_name', 'last_name', 'username')


# ---------------------------------------------------------------------------
# Catálogos
# ---------------------------------------------------------------------------
class _DelNivel:
    """Lo común a los catálogos de un nivel: nombre único en el nivel (sin distinguir mayúsculas). El nivel lo pone la
    vista y no se cambia. Cada formulario llama a `_preparar` y aplica el estilo en su constructor."""

    descripcion_requerida = False

    def _preparar(self, nivel):
        self.nivel = nivel
        self.instance.nivel = nivel
        self.fields['descripcion'].required = self.descripcion_requerida
        self.fields['descripcion'].widget.attrs.setdefault('rows', 3)

    def clean_nombre(self):
        nombre = _texto(self.cleaned_data.get('nombre'))
        repetido = type(self.instance).objects.filter(nivel=self.nivel, nombre__iexact=nombre).exclude(pk=self.instance.pk)
        if repetido.exists():
            raise ValidationError(f'Ya hay {self._meta.model._meta.verbose_name.lower()} con ese nombre en {reglas.NOMBRE_DE_NIVEL[self.nivel].lower()}.')
        return nombre

    def clean_descripcion(self):
        return (self.cleaned_data.get('descripcion') or '').strip()


class CategoriaForm(_DelNivel, EstiloCamposMixin, forms.ModelForm):
    class Meta:
        model = CategoriaConducta
        fields = ['nombre', 'tipo', 'descripcion', 'activo']
        widgets = {'tipo': forms.RadioSelect(attrs={'class': 'choice__input'}), 'descripcion': forms.Textarea}
        labels = {'activo': 'Activa (se ofrece en registros nuevos)'}

    def __init__(self, *args, nivel, **kwargs):
        super().__init__(*args, **kwargs)
        self._preparar(nivel)
        self.aplicar_estilo()
        _casillas(self)

    def clean_tipo(self):
        tipo = self.cleaned_data.get('tipo')
        if self.instance.pk and tipo != self.instance.tipo and self.instance.registros.exists():
            raise ValidationError('Esta categoría ya se usa en el historial: su tipo no cambia. Crea otra categoría.')
        return tipo


class MotivoForm(EstiloCamposMixin, forms.ModelForm):
    class Meta:
        model = MotivoConducta
        fields = ['categoria', 'nombre', 'gravedad', 'descripcion', 'activo']
        widgets = {'descripcion': forms.Textarea(attrs={'rows': 3})}
        labels = {'activo': 'Activo (se ofrece en registros nuevos)', 'gravedad': 'Gravedad (solo incidencias)'}

    def __init__(self, *args, nivel, **kwargs):
        super().__init__(*args, **kwargs)
        self.nivel = nivel
        categorias = CategoriaConducta.objects.filter(nivel=nivel)
        if not self.instance.pk:
            categorias = categorias.filter(activo=True)
        self.fields['categoria'].queryset = categorias.order_by('tipo', 'nombre')
        self.fields['categoria'].label_from_instance = lambda c: f'{c.nombre} ({c.get_tipo_display().lower()}){"" if c.activo else " · inactiva"}'
        self.fields['gravedad'].choices = [('', 'Sin gravedad'), *GRAVEDADES]
        self.aplicar_estilo()
        _casillas(self)

    def clean_nombre(self):
        return _texto(self.cleaned_data.get('nombre'))

    def clean_categoria(self):
        categoria = self.cleaned_data.get('categoria')
        if categoria and categoria.nivel != self.nivel:
            raise ValidationError('La categoría debe ser del mismo nivel educativo.')
        if self.instance.pk and categoria and categoria.pk != self.instance.categoria_id and self.instance.registros.exists():
            raise ValidationError('Este motivo ya se usa en el historial: no cambia de categoría. Crea otro motivo.')
        return categoria

    def clean(self):
        datos = super().clean()
        categoria, nombre = datos.get('categoria'), datos.get('nombre')
        if categoria and nombre:
            repetido = MotivoConducta.objects.filter(categoria=categoria, nombre__iexact=nombre).exclude(pk=self.instance.pk)
            if repetido.exists():
                self.add_error('nombre', f'La categoría «{categoria}» ya tiene un motivo con ese nombre.')
            if categoria.tipo == POSITIVA:
                datos['gravedad'] = ''   # la gravedad es de las incidencias
        return datos


class MedidaForm(_DelNivel, EstiloCamposMixin, forms.ModelForm):
    descripcion_requerida = True

    class Meta:
        model = MedidaDisciplinaria
        fields = ['nombre', 'descripcion', 'requiere_seguimiento', 'implica_suspension', 'disponible_prefectura', 'requiere_aprobacion', 'activo']
        widgets = {'descripcion': forms.Textarea}
        labels = {'activo': 'Activa (se ofrece en registros nuevos)'}
        help_texts = {
            'requiere_seguimiento': 'Al aplicarla se pide un responsable y una fecha de revisión.',
            'implica_suspension': 'Al aplicarla se piden el motivo y las fechas de la suspensión (que siempre necesita aprobación).',
            'disponible_prefectura': 'Prefectura puede aplicarla (o solicitarla, si requiere aprobación).',
            'requiere_aprobacion': 'Queda pendiente hasta que la apruebe Dirección o quien tenga el permiso de aprobar.',
        }

    def __init__(self, *args, nivel, **kwargs):
        super().__init__(*args, **kwargs)
        self._preparar(nivel)
        self.aplicar_estilo()
        _casillas(self)


class MotivoSuspensionForm(_DelNivel, EstiloCamposMixin, forms.ModelForm):
    descripcion_requerida = True

    class Meta:
        model = MotivoSuspension
        fields = ['nombre', 'descripcion', 'activo']
        widgets = {'descripcion': forms.Textarea}
        labels = {'activo': 'Activo (se ofrece en registros nuevos)'}

    def __init__(self, *args, nivel, **kwargs):
        super().__init__(*args, **kwargs)
        self._preparar(nivel)
        self.aplicar_estilo()
        _casillas(self)


class ReglaReincidenciaForm(EstiloCamposMixin, forms.ModelForm):
    class Meta:
        model = ReglaReincidencia
        fields = ['activa', 'incidencias', 'dias']
        labels = {'activa': 'Avisar cuando un estudiante reincida', 'incidencias': 'Incidencias del mismo motivo', 'dias': 'Dentro de (días)'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()
        _casillas(self)


# ---------------------------------------------------------------------------
# Registro de conducta
# ---------------------------------------------------------------------------
class RegistroForm(EstiloCamposMixin, forms.Form):
    """Alta y edición de un registro. El nivel (y con él las opciones) sale del estudiante: de su inscripción en el
    ciclo de la fecha del hecho al registrar, y del propio registro al editar (el estudiante y el ciclo no cambian)."""

    alumno = forms.ModelChoiceField(
        Alumno.objects.exclude(estatus='BAJA'), widget=forms.HiddenInput,
        error_messages={'required': 'Busca y elige un estudiante.', 'invalid_choice': 'Elige un estudiante de la lista.'},
    )
    fecha = forms.DateField(label='Fecha del hecho', widget=FECHA, error_messages={'required': 'Indica la fecha.', 'invalid': 'Escribe una fecha válida.'})
    hora = forms.TimeField(required=False, label='Hora', widget=HORA, error_messages={'invalid': 'Escribe una hora válida.'})
    lugar = forms.CharField(required=False, max_length=120, label='Lugar', widget=forms.TextInput(attrs={'placeholder': 'Patio, salón 3B, autobús…'}))
    reporta = forms.CharField(required=False, max_length=150, label='Personal que reporta', widget=forms.TextInput(attrs={
        'placeholder': 'Quién lo vio o lo reportó (si no fuiste tú)', 'autocomplete': 'off'}))
    tipo = forms.ChoiceField(choices=TIPOS, initial=INCIDENCIA, label='Tipo', widget=forms.RadioSelect(attrs={'class': 'choice__input'}))
    categoria = forms.ModelChoiceField(CategoriaConducta.objects.none(), label='Categoría', empty_label='Elige la categoría…',
                                       error_messages={'required': 'Elige la categoría.', 'invalid_choice': 'Elige una categoría de la lista.'})
    motivo = forms.ModelChoiceField(MotivoConducta.objects.none(), label='Motivo', empty_label='Elige el motivo…',
                                    error_messages={'required': 'Elige el motivo.', 'invalid_choice': 'Elige un motivo de la categoría.'})
    gravedad = forms.ChoiceField(choices=[('', 'Sin gravedad'), *GRAVEDADES], required=False, label='Gravedad')
    descripcion = forms.CharField(
        label='Descripción objetiva de los hechos', min_length=10, max_length=4000,
        widget=forms.Textarea(attrs={'rows': 4, 'placeholder': 'Qué pasó, sin juicios: quién, qué, dónde y cuándo.'}),
        error_messages={'required': 'Describe los hechos.', 'min_length': 'Describe los hechos con más detalle (al menos 10 caracteres).'},
    )
    medidas = forms.ModelMultipleChoiceField(
        MedidaDisciplinaria.objects.none(), required=False, label='Medidas disciplinarias',
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'choice__input'}),
        error_messages={'invalid_choice': 'Elige medidas del nivel del estudiante.', 'invalid_pk_value': 'Elige medidas del nivel del estudiante.'},
    )
    observaciones_medidas = forms.CharField(required=False, max_length=2000, label='Observaciones sobre las medidas', widget=forms.Textarea(attrs={'rows': 2}))

    suspension_motivo = forms.ModelChoiceField(MotivoSuspension.objects.none(), required=False, label='Motivo de la suspensión', empty_label='Elige el motivo…')
    suspension_inicio = forms.DateField(required=False, label='Inicio', widget=FECHA, error_messages={'invalid': 'Escribe una fecha válida.'})
    suspension_fin = forms.DateField(required=False, label='Término', widget=FECHA, error_messages={'invalid': 'Escribe una fecha válida.'})
    suspension_observaciones = forms.CharField(required=False, max_length=2000, label='Observaciones de la suspensión', widget=forms.Textarea(attrs={'rows': 2}))
    suspension_justificacion = forms.CharField(required=False, max_length=2000, label='Justificación de la solicitud', widget=forms.Textarea(attrs={
        'rows': 2, 'placeholder': 'Por qué se propone la suspensión: la revisará quien la apruebe.'}))
    suspension_autoriza = UsuarioField(get_user_model().objects.none(), required=False, label='Autorizó', empty_label='Elige quién la autorizó…')
    confirmar_superposicion = forms.BooleanField(required=False, label='Registrarla de todos modos', widget=forms.CheckboxInput(attrs={'class': 'choice__input'}))

    responsable = UsuarioField(get_user_model().objects.none(), required=False, label='Responsable del seguimiento', empty_label='Sin responsable')
    fecha_revision = forms.DateField(required=False, label='Fecha de compromiso o revisión', widget=FECHA, error_messages={'invalid': 'Escribe una fecha válida.'})
    estado = forms.ChoiceField(choices=RegistroConducta.ESTADOS, initial=RegistroConducta.PENDIENTE, label='Estado del seguimiento')
    acuerdos = forms.CharField(required=False, max_length=4000, label='Acuerdos', widget=forms.Textarea(attrs={'rows': 2}))
    observaciones_cierre = forms.CharField(required=False, max_length=4000, label='Observación final (al cerrar)', widget=forms.Textarea(attrs={'rows': 2}))
    motivo_cambio = forms.CharField(
        required=False, max_length=1000, label='Motivo del cambio',
        widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Por qué se corrige el registro (queda en el historial).'}),
    )

    def __init__(self, *args, registro=None, alumno=None, usuario=None, alumnos=None, **kwargs):
        self.registro = registro
        self.usuario = usuario
        # Lo que puede quien captura: autorizar suspensiones de algún nivel (si no, la suspensión es una solicitud a la
        # dirección del nivel del estudiante) y qué medidas ofrecer
        self.aprueba_alguno = usuario is None or permisos.puede_aprobar(usuario)
        self.aprueba_todos = usuario is None or permisos.niveles_que_aprueba(usuario) is None
        self.solo_prefectura = usuario is not None and permisos.solo_medidas_de_prefectura(usuario)
        self.pide_suspension = usuario is None or permisos.puede_pedir_suspension(usuario)
        if registro is not None and 'initial' not in kwargs:
            kwargs['initial'] = self.iniciales_de(registro)
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()
        self.fields['responsable'].queryset = usuarios_activos()
        self.fields['suspension_autoriza'].queryset = usuarios_activos()
        if registro is not None:
            self.fields['motivo_cambio'].required = True
            self.fields['motivo_cambio'].error_messages['required'] = 'Escribe por qué se corrige el registro.'
        if 'alumno' in self.fields and alumnos is not None:
            self.fields['alumno'].queryset = alumnos.exclude(estatus='BAJA')   # solo los del alcance de quien captura
        self.alumnos_permitidos = alumnos
        self.inscripcion = None
        if registro is not None:
            del self.fields['alumno']
            self.alumno, self.nivel = registro.alumno, registro.nivel
            self.inscripcion = registro.inscripcion
        else:
            datos = self.data if self.is_bound else self.initial
            self.alumno = alumno or self._alumno_de(datos.get('alumno'), alumnos)
            fecha = self._fecha_de(datos.get('fecha')) or timezone.localdate()
            self.inscripcion = reglas.inscripcion_en(self.alumno, fecha) if self.alumno else None
            self.nivel = self.inscripcion.grado.nivel if self.inscripcion else None
            if self.alumno is not None and not self.is_bound:
                self.initial['alumno'] = self.alumno.pk
        self._limitar_opciones()

    @property
    def aprueba(self):
        """Si autoriza la suspensión de este estudiante: es de un nivel que dirige."""
        return self.usuario is None or permisos.puede_aprobar(self.usuario, self.nivel)

    @staticmethod
    def suspension_de(registro):
        """La suspensión aprobada o pendiente del registro (una rechazada o cancelada ya no cuenta)."""
        suspension = getattr(registro, 'suspension', None) if registro is not None and registro.pk else None
        return suspension if suspension is not None and suspension.aprobacion in (APROBADA, PENDIENTE) else None

    @staticmethod
    def medidas_vigentes_de(registro):
        return list(registro.medidas_aplicadas.filter(estado__in=MedidaAplicada.VIGENTES).values_list('medida_id', flat=True))

    @classmethod
    def iniciales_de(cls, registro):
        suspension = cls.suspension_de(registro)
        return {
            'fecha': registro.fecha, 'hora': registro.hora, 'lugar': registro.lugar, 'reporta': registro.reporta, 'tipo': registro.tipo,
            'categoria': registro.categoria_id, 'motivo': registro.motivo_id, 'gravedad': registro.gravedad,
            'descripcion': registro.descripcion, 'medidas': cls.medidas_vigentes_de(registro),
            'observaciones_medidas': registro.observaciones_medidas,
            'suspension_motivo': suspension.motivo_id if suspension else None,
            'suspension_inicio': suspension.fecha_inicio if suspension else None,
            'suspension_fin': suspension.fecha_fin if suspension else None,
            'suspension_observaciones': suspension.observaciones if suspension else '',
            'suspension_justificacion': suspension.justificacion if suspension else '',
            'suspension_autoriza': suspension.autorizada_por_id if suspension else None,
            'responsable': registro.responsable_id, 'fecha_revision': registro.fecha_revision, 'estado': registro.estado,
            'acuerdos': registro.acuerdos, 'observaciones_cierre': registro.observaciones_cierre,
        }

    @staticmethod
    def _alumno_de(valor, alumnos=None):
        consulta = Alumno.objects.all() if alumnos is None else alumnos
        return consulta.filter(pk=valor).exclude(estatus='BAJA').first() if str(valor or '').isdigit() else None

    @staticmethod
    def _fecha_de(valor):
        if not valor:
            return None
        if hasattr(valor, 'year'):
            return valor
        try:
            return date.fromisoformat(str(valor))
        except ValueError:
            return None

    def _limitar_opciones(self):
        """Lo activo del nivel del estudiante, más lo que el registro ya usa (aunque hoy esté inactivo)."""
        if not self.nivel:
            return
        actual = self.registro
        self.fields['categoria'].queryset = CategoriaConducta.objects.filter(
            Q(nivel=self.nivel, activo=True) | Q(pk=actual.categoria_id if actual else None)
        ).order_by('nombre')
        self.fields['motivo'].queryset = MotivoConducta.objects.filter(
            Q(categoria__nivel=self.nivel, activo=True, categoria__activo=True) | Q(pk=actual.motivo_id if actual else None)
        ).select_related('categoria').order_by('nombre')
        aplicadas = self.medidas_vigentes_de(actual) if actual else []
        ofrecidas = Q(nivel=self.nivel, activo=True)
        if self.solo_prefectura:
            ofrecidas &= Q(disponible_prefectura=True)
        if not self.pide_suspension:
            ofrecidas &= Q(implica_suspension=False)
        self.fields['medidas'].queryset = MedidaDisciplinaria.objects.filter(ofrecidas | Q(pk__in=aplicadas)).order_by('nombre')
        suspension = self.suspension_de(actual) if actual else None
        self.fields['suspension_motivo'].queryset = MotivoSuspension.objects.filter(
            Q(nivel=self.nivel, activo=True) | Q(pk=suspension.motivo_id if suspension else None)
        ).order_by('nombre')

    # --- Validación ----------------------------------------------------------------------------------------------
    def clean_descripcion(self):
        return (self.cleaned_data.get('descripcion') or '').strip()

    def clean_fecha(self):
        fecha = self.cleaned_data.get('fecha')
        if fecha and fecha > timezone.localdate():
            raise ValidationError('La fecha del hecho no puede ser futura.')
        return fecha

    def clean(self):
        datos = super().clean()
        fecha = datos.get('fecha')
        if self.registro is None:
            alumno = datos.get('alumno')
            if alumno and fecha:
                self.inscripcion = reglas.inscripcion_en(alumno, fecha)
                if self.inscripcion is None:
                    ciclo = reglas.ciclo_de(fecha)
                    self.add_error('fecha', f'{alumno} no tenía inscripción en el ciclo {ciclo}.' if ciclo
                                   else 'Esa fecha queda fuera de las fechas de cualquier ciclo escolar.')
                    return datos
                if self.inscripcion.ciclo.estado == 'CERRADO':
                    self.add_error('fecha', f'El ciclo {self.inscripcion.ciclo} ya se cerró: es de solo lectura. Registra hechos del ciclo actual.')
                    return datos
                self.nivel = self.inscripcion.grado.nivel
                self._limitar_opciones()
                datos['contexto'] = reglas.contexto_escolar(self.inscripcion, fecha)
        elif fecha and reglas.ciclo_de(fecha) != self.registro.ciclo:
            self.add_error('fecha', f'La fecha debe quedar dentro del ciclo {self.registro.ciclo}. Para otro ciclo, anula este registro y registra uno nuevo.')
        if self.registro is not None and 'motivo_cambio' not in self.errors:
            datos['motivo_cambio'] = _texto(datos.get('motivo_cambio'))
            if len(datos['motivo_cambio']) < 5:
                self.add_error('motivo_cambio', 'Escribe por qué se corrige el registro (al menos 5 caracteres).')
        datos['reporta'] = _texto(datos.get('reporta'))
        if not self.nivel or self.errors.get('fecha'):
            return datos
        self._validar_conducta(datos)
        self._validar_medidas_y_suspension(datos)
        self._validar_seguimiento(datos)
        datos['evidencias'] = self._validar_evidencias()
        return datos

    def _sin_cambio(self, campo, valor):
        """Si el registro ya tenía ese valor (lo inactivo se conserva en los registros que ya lo usan)."""
        return self.registro is not None and getattr(self.registro, f'{campo}_id') == getattr(valor, 'pk', None)

    def _validar_conducta(self, datos):
        tipo, categoria, motivo = datos.get('tipo'), datos.get('categoria'), datos.get('motivo')
        if categoria:
            if categoria.nivel != self.nivel:
                self.add_error('categoria', 'La categoría debe ser del nivel del estudiante.')
            elif categoria.tipo != tipo:
                self.add_error('categoria', f'Esa categoría es de {categoria.get_tipo_display().lower()}: elige una del tipo indicado.')
            elif not categoria.activo and not self._sin_cambio('categoria', categoria):
                self.add_error('categoria', 'Esa categoría está inactiva: ya no se usa en registros nuevos.')
        if motivo and categoria and motivo.categoria_id != categoria.pk:
            self.add_error('motivo', 'El motivo debe ser de la categoría elegida.')
        elif motivo and not (motivo.activo and motivo.categoria.activo) and not self._sin_cambio('motivo', motivo):
            self.add_error('motivo', 'Ese motivo está inactivo: ya no se usa en registros nuevos.')
        if tipo == POSITIVA:
            datos['gravedad'] = ''
        elif motivo and not datos.get('gravedad'):
            datos['gravedad'] = motivo.gravedad

    def _validar_medidas_y_suspension(self, datos):
        medidas = list(datos.get('medidas') or [])
        datos['medidas'] = medidas
        if datos.get('tipo') == POSITIVA and medidas:
            self.add_error('medidas', 'Las conductas positivas no llevan medidas disciplinarias.')
            return
        aplicadas = set(self.medidas_vigentes_de(self.registro)) if self.registro else set()
        for medida in medidas:
            if medida.nivel != self.nivel:
                self.add_error('medidas', f'«{medida}» no es del nivel del estudiante.')
            elif not medida.activo and medida.pk not in aplicadas:
                self.add_error('medidas', f'«{medida}» está inactiva: ya no se aplica en registros nuevos.')
            elif medida.pk not in aplicadas and self.solo_prefectura and not medida.disponible_prefectura:
                self.add_error('medidas', f'«{medida}» no está habilitada para prefectura.')
            elif medida.pk not in aplicadas and medida.implica_suspension and not self.pide_suspension:
                self.add_error('medidas', f'«{medida}» implica una suspensión y no tienes permiso para solicitarla.')

        anterior = self.suspension_de(self.registro) if self.registro else None
        datos['con_suspension'] = any(m.implica_suspension for m in medidas)
        if not datos['con_suspension']:
            if anterior is not None and anterior.aprobacion == APROBADA and not self.aprueba:
                self.add_error('medidas', 'La suspensión ya está aprobada: solo quien aprueba suspensiones puede quitarla.')
            for campo in ('suspension_motivo', 'suspension_inicio', 'suspension_fin', 'suspension_autoriza'):
                datos[campo] = None
            datos['suspension_observaciones'] = datos['suspension_justificacion'] = ''
            return
        motivo, inicio, fin = datos.get('suspension_motivo'), datos.get('suspension_inicio'), datos.get('suspension_fin')
        cambia = anterior is None or (getattr(motivo, 'pk', None), inicio, fin) != (anterior.motivo_id, anterior.fecha_inicio, anterior.fecha_fin)
        if anterior is not None and anterior.aprobacion == APROBADA and not self.aprueba and cambia:
            self.add_error('suspension_inicio', 'La suspensión ya está aprobada: solo quien aprueba suspensiones puede cambiarla.')
        if not motivo:
            self.add_error('suspension_motivo', 'La suspensión requiere su motivo.')
        elif motivo.nivel != self.nivel:
            self.add_error('suspension_motivo', 'El motivo de suspensión debe ser del nivel del estudiante.')
        elif not motivo.activo and not (anterior and anterior.motivo_id == motivo.pk):
            self.add_error('suspension_motivo', 'Ese motivo de suspensión está inactivo.')
        if not inicio:
            self.add_error('suspension_inicio', 'Indica cuándo empieza la suspensión.')
        if not fin:
            self.add_error('suspension_fin', 'Indica cuándo termina la suspensión.')
        if inicio and fin and fin < inicio:
            self.add_error('suspension_fin', 'La fecha de término no puede ser anterior a la de inicio.')
        if self.aprueba:
            # Una solicitud pendiente que no se toca sigue esperando su resolución (en Solicitudes)
            if not datos.get('suspension_autoriza') and (cambia or anterior.aprobada):
                self.add_error('suspension_autoriza', 'Indica quién autorizó la suspensión.')
        else:
            datos['suspension_autoriza'] = None
            datos['suspension_justificacion'] = _texto(datos.get('suspension_justificacion'))
            if len(datos['suspension_justificacion']) < 10:
                self.add_error('suspension_justificacion', 'Explica por qué se propone la suspensión (al menos 10 caracteres): la revisará quien la apruebe.')
        if inicio and fin and fin >= inicio:
            alumno = self.alumno if self.registro else datos.get('alumno')
            self.superpuestas = reglas.suspensiones_superpuestas(alumno, inicio, fin, excluir_registro=self.registro)
            if self.superpuestas and not datos.get('confirmar_superposicion'):
                fechas = '; '.join(f'del {s.fecha_inicio:%d/%m/%Y} al {s.fecha_fin:%d/%m/%Y}' for s in self.superpuestas)
                self.add_error('confirmar_superposicion',
                               f'El estudiante ya tiene una suspensión que se cruza con esas fechas ({fechas}). '
                               'Revísala; si de todos modos procede, marca «Registrarla de todos modos».')

    def _validar_seguimiento(self, datos):
        fecha, revision = datos.get('fecha'), datos.get('fecha_revision')
        if revision and fecha and revision < fecha:
            self.add_error('fecha_revision', 'La fecha de revisión no puede ser anterior a la del hecho.')
        validar_cierre(self, datos)
        if any(m.requiere_seguimiento for m in datos.get('medidas') or []) and datos.get('estado') != RegistroConducta.CERRADO:
            if not datos.get('responsable'):
                self.add_error('responsable', 'Una de las medidas requiere seguimiento: indica quién lo lleva.')
            if not revision:
                self.add_error('fecha_revision', 'Una de las medidas requiere seguimiento: indica la fecha de revisión.')

    def _validar_evidencias(self):
        archivos = self.files.getlist('evidencias') if hasattr(self.files, 'getlist') else []
        validos = []
        if len(archivos) > EVIDENCIAS_POR_ENVIO:
            self.add_error(None, f'Adjunta como máximo {EVIDENCIAS_POR_ENVIO} archivos a la vez.')
            return []
        ya = self.registro.evidencias.filter(activa=True).count() if self.registro else 0
        if ya + len(archivos) > EVIDENCIAS_POR_REGISTRO:
            self.add_error(None, f'Un registro tiene como máximo {EVIDENCIAS_POR_REGISTRO} evidencias.')
            return []
        for archivo in archivos:
            try:
                validos.append((archivo, validar_archivo(archivo)))
            except ValidationError as error:
                self.add_error(None, error)
        return validos


def validar_cierre(formulario, datos):
    """Cerrar el caso exige su observación final."""
    datos['observaciones_cierre'] = (datos.get('observaciones_cierre') or '').strip()
    if datos.get('estado') == RegistroConducta.CERRADO and len(datos['observaciones_cierre']) < 5:
        formulario.add_error('observaciones_cierre', 'Para cerrar el caso escribe la observación final.')


class SeguimientoForm(EstiloCamposMixin, forms.Form):
    responsable = UsuarioField(get_user_model().objects.none(), required=False, label='Responsable del seguimiento', empty_label='Sin responsable')
    fecha_revision = forms.DateField(required=False, label='Fecha de compromiso o revisión', widget=FECHA)
    estado = forms.ChoiceField(choices=RegistroConducta.ESTADOS, label='Estado del seguimiento')
    acuerdos = forms.CharField(required=False, max_length=4000, label='Acuerdos', widget=forms.Textarea(attrs={'rows': 3}))
    observaciones_cierre = forms.CharField(required=False, max_length=4000, label='Observación final (al cerrar)', widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, registro, **kwargs):
        self.registro = registro
        kwargs.setdefault('initial', {
            'responsable': registro.responsable_id, 'fecha_revision': registro.fecha_revision, 'estado': registro.estado,
            'acuerdos': registro.acuerdos, 'observaciones_cierre': registro.observaciones_cierre,
        })
        super().__init__(*args, **kwargs)
        self.fields['responsable'].queryset = usuarios_activos()
        self.aplicar_estilo()

    def clean(self):
        datos = super().clean()
        revision = datos.get('fecha_revision')
        if revision and revision < self.registro.fecha:
            self.add_error('fecha_revision', 'La fecha de revisión no puede ser anterior a la del hecho.')
        validar_cierre(self, datos)
        requiere = self.registro.medidas_aplicadas.filter(requiere_seguimiento=True, estado__in=MedidaAplicada.VIGENTES).exists()
        if requiere and datos.get('estado') != RegistroConducta.CERRADO:
            if not datos.get('responsable'):
                self.add_error('responsable', 'Una de las medidas requiere seguimiento: indica quién lo lleva.')
            if not revision:
                self.add_error('fecha_revision', 'Una de las medidas requiere seguimiento: indica la fecha de revisión.')
        return datos


class AnularForm(forms.Form):
    motivo = forms.CharField(
        label='Motivo de la anulación', min_length=10, max_length=1000,
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'field__control', 'placeholder': 'Por qué se anula (queda en el historial).'}),
        error_messages={'required': 'Escribe por qué se anula.', 'min_length': 'Explica el motivo (al menos 10 caracteres).'},
    )

    def clean_motivo(self):
        return (self.cleaned_data.get('motivo') or '').strip()


class RevisarAvisoForm(forms.Form):
    nota = forms.CharField(
        required=False, max_length=1000, label='Nota de la revisión',
        widget=forms.Textarea(attrs={'rows': 2, 'class': 'field__control', 'placeholder': 'Qué se decidió (opcional).'}),
    )


class ContactoForm(EstiloCamposMixin, forms.Form):
    OTRA = 'otra'

    fecha = forms.DateField(label='Fecha de contacto', widget=FECHA, initial=timezone.localdate,
                            error_messages={'required': 'Indica la fecha del contacto.', 'invalid': 'Escribe una fecha válida.'})
    tutor = forms.ChoiceField(label='Padre, madre o tutor contactado', error_messages={'required': 'Elige a quién se contactó.'})
    persona = forms.CharField(required=False, max_length=160, label='Nombre de la persona contactada')
    medio = forms.ChoiceField(choices=ContactoTutor.MEDIOS, label='Medio utilizado')
    acuerdos = forms.CharField(label='Acuerdos', max_length=4000, widget=forms.Textarea(attrs={'rows': 3}),
                               error_messages={'required': 'Escribe los acuerdos (o lo que se habló).'})
    proxima_revision = forms.DateField(required=False, label='Fecha de próxima revisión', widget=FECHA)

    def __init__(self, *args, registro, **kwargs):
        super().__init__(*args, **kwargs)
        self.registro = registro
        vinculos = (
            TutorAlumno.objects.filter(alumno=registro.alumno, activo=True, tutor__estatus='ACTIVO')
            .select_related('tutor').order_by('-tutor_principal', 'tutor__apellido_paterno')
        )
        self.vinculos = {str(v.tutor_id): v for v in vinculos}
        self.fields['tutor'].choices = [('', 'Elige…')] + [
            (str(v.tutor_id), f'{v.tutor} ({v.get_parentesco_display().lower()})') for v in vinculos
        ] + [(self.OTRA, 'Otra persona')]
        self.aplicar_estilo()

    def clean_fecha(self):
        fecha = self.cleaned_data.get('fecha')
        if fecha and fecha > timezone.localdate():
            raise ValidationError('La fecha del contacto no puede ser futura.')
        return fecha

    def clean(self):
        datos = super().clean()
        eleccion = datos.get('tutor')
        if eleccion == self.OTRA:
            persona = _texto(datos.get('persona'))
            if not persona:
                self.add_error('persona', 'Escribe el nombre de la persona contactada.')
            datos['tutor_obj'], datos['persona'] = None, persona
        elif eleccion in self.vinculos:
            vinculo = self.vinculos[eleccion]
            datos['tutor_obj'] = vinculo.tutor
            datos['persona'] = f'{vinculo.tutor} ({vinculo.get_parentesco_display().lower()})'
        revision, fecha = datos.get('proxima_revision'), datos.get('fecha')
        if revision and fecha and revision < fecha:
            self.add_error('proxima_revision', 'La próxima revisión no puede ser anterior al contacto.')
        archivo = self.files.get('evidencia') if self.files else None
        datos['evidencia'] = None
        if archivo:
            try:
                datos['evidencia'] = (archivo, validar_archivo(archivo))
            except ValidationError as error:
                self.add_error(None, error)
        return datos


# ---------------------------------------------------------------------------
# Solicitudes de aprobación
# ---------------------------------------------------------------------------
class ResolverForm(forms.Form):
    """Aprobar o rechazar una solicitud (suspensión o medida). Rechazar exige explicar por qué."""

    decision = forms.ChoiceField(choices=[('aprobar', 'Aprobar'), ('rechazar', 'Rechazar')], label='Decisión', widget=forms.RadioSelect(attrs={'class': 'choice__input'}),
                                 error_messages={'required': 'Elige si apruebas o rechazas la solicitud.'})
    observaciones = forms.CharField(
        required=False, max_length=2000, label='Observaciones',
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'field__control', 'placeholder': 'Lo que se decidió y por qué (queda en el historial).'}),
    )

    def clean(self):
        datos = super().clean()
        datos['observaciones'] = (datos.get('observaciones') or '').strip()
        if datos.get('decision') == 'rechazar' and len(datos['observaciones']) < 10:
            self.add_error('observaciones', 'Para rechazar, explica por qué (al menos 10 caracteres).')
        return datos


class CancelarSolicitudForm(forms.Form):
    motivo = forms.CharField(
        label='Motivo de la cancelación', min_length=10, max_length=1000,
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'field__control', 'placeholder': 'Por qué se cancela la solicitud (queda en el historial).'}),
        error_messages={'required': 'Escribe por qué se cancela.', 'min_length': 'Explica el motivo (al menos 10 caracteres).'},
    )

    def clean_motivo(self):
        return (self.cleaned_data.get('motivo') or '').strip()


# ---------------------------------------------------------------------------
# Citas y compromisos del caso
# ---------------------------------------------------------------------------
def _tutores_de(alumno):
    vinculos = (
        TutorAlumno.objects.filter(alumno=alumno, activo=True, tutor__estatus='ACTIVO')
        .select_related('tutor').order_by('-tutor_principal', 'tutor__apellido_paterno')
    )
    return {str(v.tutor_id): v for v in vinculos}


class CitaForm(EstiloCamposMixin, forms.Form):
    OTRA = 'otra'

    fecha = forms.DateField(label='Fecha de la cita', widget=FECHA, error_messages={'required': 'Indica la fecha.', 'invalid': 'Escribe una fecha válida.'})
    hora = forms.TimeField(required=False, label='Hora', widget=HORA, error_messages={'invalid': 'Escribe una hora válida.'})
    modalidad = forms.ChoiceField(choices=CitaTutor.MODALIDADES, label='Modalidad')
    tutor = forms.ChoiceField(label='Con quién', error_messages={'required': 'Elige con quién es la cita.'})
    persona = forms.CharField(required=False, max_length=160, label='Nombre de la persona')
    asunto = forms.CharField(label='Asunto', max_length=2000, widget=forms.Textarea(attrs={'rows': 3}),
                             error_messages={'required': 'Escribe el asunto de la cita.'})
    responsable = UsuarioField(get_user_model().objects.none(), required=False, label='Responsable', empty_label='Sin responsable')

    def __init__(self, *args, registro, **kwargs):
        super().__init__(*args, **kwargs)
        self.registro = registro
        self.vinculos = _tutores_de(registro.alumno)
        self.fields['tutor'].choices = [('', 'Elige…')] + [
            (pk, f'{v.tutor} ({v.get_parentesco_display().lower()})') for pk, v in self.vinculos.items()
        ] + [(self.OTRA, 'Otra persona')]
        self.fields['responsable'].queryset = usuarios_activos()
        self.aplicar_estilo()

    def clean_fecha(self):
        fecha = self.cleaned_data.get('fecha')
        if fecha and fecha < self.registro.fecha:
            raise ValidationError('La cita no puede ser antes del hecho.')
        return fecha

    def clean(self):
        datos = super().clean()
        datos['asunto'] = (datos.get('asunto') or '').strip()
        eleccion = datos.get('tutor')
        if eleccion == self.OTRA:
            persona = _texto(datos.get('persona'))
            if not persona:
                self.add_error('persona', 'Escribe el nombre de la persona.')
            datos['tutor_obj'], datos['persona'] = None, persona
        elif eleccion in self.vinculos:
            vinculo = self.vinculos[eleccion]
            datos['tutor_obj'] = vinculo.tutor
            datos['persona'] = f'{vinculo.tutor} ({vinculo.get_parentesco_display().lower()})'
        return datos


class ActualizarCitaForm(EstiloCamposMixin, forms.Form):
    estado = forms.ChoiceField(choices=[c for c in CitaTutor.ESTADOS if c[0] != CitaTutor.PROGRAMADA], label='¿Qué pasó con la cita?',
                               widget=forms.RadioSelect(attrs={'class': 'choice__input'}), error_messages={'required': 'Elige qué pasó con la cita.'})
    resultado = forms.CharField(label='Resultado u observaciones', max_length=4000, widget=forms.Textarea(attrs={'rows': 3}),
                                error_messages={'required': 'Escribe qué se habló o por qué no se realizó.'})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()

    def clean_resultado(self):
        return (self.cleaned_data.get('resultado') or '').strip()


class CompromisoForm(EstiloCamposMixin, forms.Form):
    descripcion = forms.CharField(label='Acuerdo o compromiso', max_length=2000, widget=forms.Textarea(attrs={'rows': 3}),
                                  error_messages={'required': 'Describe el acuerdo o compromiso.'})
    quien = forms.ChoiceField(choices=Compromiso.QUIENES, label='Se compromete')
    responsable = UsuarioField(get_user_model().objects.none(), required=False, label='Responsable del seguimiento', empty_label='Sin responsable')
    fecha_limite = forms.DateField(label='Fecha límite', widget=FECHA, error_messages={'required': 'Indica la fecha límite.', 'invalid': 'Escribe una fecha válida.'})

    def __init__(self, *args, registro, **kwargs):
        super().__init__(*args, **kwargs)
        self.registro = registro
        self.fields['responsable'].queryset = usuarios_activos()
        self.aplicar_estilo()

    def clean_descripcion(self):
        return (self.cleaned_data.get('descripcion') or '').strip()

    def clean_fecha_limite(self):
        fecha = self.cleaned_data.get('fecha_limite')
        if fecha and fecha < self.registro.fecha:
            raise ValidationError('La fecha límite no puede ser antes del hecho.')
        return fecha


class ResolverCompromisoForm(EstiloCamposMixin, forms.Form):
    estado = forms.ChoiceField(choices=[c for c in Compromiso.ESTADOS if c[0] != Compromiso.PENDIENTE_C], label='¿Cómo terminó?',
                               widget=forms.RadioSelect(attrs={'class': 'choice__input'}), error_messages={'required': 'Elige cómo terminó el compromiso.'})
    observaciones = forms.CharField(label='Observaciones', max_length=4000, widget=forms.Textarea(attrs={'rows': 3}),
                                    error_messages={'required': 'Escribe una observación.'})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()

    def clean_observaciones(self):
        return (self.cleaned_data.get('observaciones') or '').strip()


# ---------------------------------------------------------------------------
# Filtros del listado y de los reportes
# ---------------------------------------------------------------------------
class _OpcionNivel(forms.ModelChoiceField):
    """Opción de un catálogo con su nivel (y lo inactivo marcado), para las listas de filtros."""

    def label_from_instance(self, objeto):
        nivel = reglas.NOMBRE_DE_NIVEL.get(getattr(objeto, 'nivel', ''), '')
        return f'{objeto.nombre} · {nivel}{"" if objeto.activo else " (inactivo)"}'


class TiposDeReporte:
    HISTORIAL, GRUPO, RESUMEN, SUSPENSIONES = 'historial', 'grupo', 'resumen', 'suspensiones'
    REPORTES = [
        (RESUMEN, 'Resumen estadístico'),
        (GRUPO, 'Por grupo o nivel'),
        (HISTORIAL, 'Historial individual'),
        (SUSPENSIONES, 'Suspensiones'),
    ]


class FiltroForm(EstiloCamposMixin, forms.Form):
    """Los filtros del registro (`modo='lista'`: busca al estudiante por nombre o número de control) y de los reportes
    (`modo='reporte'`: qué reporte y uno o varios estudiantes). Sin «ciclo» en la dirección se usa el ciclo actual;
    «Todos los ciclos» es ciclo vacío."""

    SUSPENSION = [('', 'Con o sin suspensión'), ('con', 'Con suspensión aprobada'), ('vigente', 'Suspendidos hoy'),
                  ('pendiente', 'Solicitud pendiente'), ('sin', 'Sin suspensión aprobada')]
    ESTADOS = [('', 'Cualquier seguimiento'), ('abiertos', 'Abiertos o en seguimiento'), *RegistroConducta.ESTADOS, ('vencidos', 'Vencidos')]
    REGISTROS = [(reglas.VIGENTES, 'Vigentes'), (reglas.ANULADOS, 'Anulados'), (reglas.TODOS, 'Vigentes y anulados')]
    SOLO_LISTA, SOLO_REPORTE = ('q',), ('reporte', 'alumnos', 'bitacora')
    BITACORA = [('', 'Incluirlas'), ('no', 'Excluirlas')]

    q = forms.CharField(required=False, label='Estudiante', widget=forms.TextInput(attrs={
        'type': 'search', 'placeholder': 'Nombre o número de control…', 'autocomplete': 'off',
    }))
    reporte = forms.ChoiceField(choices=TiposDeReporte.REPORTES, required=False, label='Reporte')
    alumnos = forms.ModelMultipleChoiceField(Alumno.objects.all(), required=False, label='Estudiantes', widget=forms.MultipleHiddenInput)
    ciclo = forms.ModelChoiceField(CicloEscolar.objects.none(), required=False, empty_label='Todos los ciclos', label='Ciclo escolar')
    periodo = forms.ModelChoiceField(Periodo.objects.none(), required=False, empty_label='Cualquier periodo', label='Periodo')
    desde = forms.DateField(required=False, label='Desde', widget=FECHA)
    hasta = forms.DateField(required=False, label='Hasta', widget=FECHA)
    nivel = forms.ChoiceField(choices=[('', 'Todos los niveles'), *NIVELES], required=False, label='Nivel educativo')
    grado = forms.ModelChoiceField(Grado.objects.none(), required=False, empty_label='Todos los grados', label='Grado')
    grupo = forms.ModelChoiceField(Grupo.objects.none(), required=False, empty_label='Todos los grupos', label='Grupo')
    tipo = forms.ChoiceField(choices=[('', 'Incidencias y positivas'), *TIPOS], required=False, label='Tipo')
    categoria = _OpcionNivel(CategoriaConducta.objects.none(), required=False, empty_label='Todas las categorías', label='Categoría')
    motivo = _OpcionNivel(MotivoConducta.objects.none(), required=False, empty_label='Todos los motivos', label='Motivo')
    gravedad = forms.ChoiceField(choices=[('', 'Cualquier gravedad'), *GRAVEDADES], required=False, label='Gravedad')
    medida = _OpcionNivel(MedidaDisciplinaria.objects.none(), required=False, empty_label='Cualquier medida', label='Medida disciplinaria')
    suspension = forms.ChoiceField(choices=SUSPENSION, required=False, label='Suspensión')
    estado = forms.ChoiceField(choices=ESTADOS, required=False, label='Seguimiento')
    registros = forms.ChoiceField(choices=REGISTROS, required=False, label='Registros')
    # Bitácoras por grupo: sección aparte en los reportes por grupo e individuales (solo para quien consulta bitácoras)
    bitacora = forms.ChoiceField(choices=BITACORA, required=False, label='Observaciones de bitácora')

    def __init__(self, *args, modo='lista', alcance=None, reportes=None, con_bitacora=False, **kwargs):
        super().__init__(*args, **kwargs)
        for nombre in (self.SOLO_REPORTE if modo == 'lista' else self.SOLO_LISTA):
            del self.fields[nombre]
        if 'bitacora' in self.fields and not con_bitacora:
            del self.fields['bitacora']
        if reportes is not None and 'reporte' in self.fields:
            self.fields['reporte'].choices = reportes
        self.reportes = dict(reportes or TiposDeReporte.REPORTES)
        self.fields['ciclo'].queryset = CicloEscolar.objects.order_by('-fecha_inicio')
        self.fields['periodo'].queryset = Periodo.objects.select_related('ciclo').order_by('-ciclo__fecha_inicio', orden_de_nivel('nivel'), 'fecha_inicio')
        self.fields['periodo'].label_from_instance = lambda p: f'{p.nombre} · {p.get_nivel_display()} · {p.ciclo}'
        self.fields['grado'].queryset = Grado.objects.academicos()
        self.fields['grupo'].queryset = Grupo.objects.select_related('grado', 'nombre').order_by(orden_de_nivel('grado__nivel'), 'grado__numero', 'nombre__orden', 'nombre__nombre')
        if alcance is not None and not alcance.total:
            # Una cuenta de prefectura solo elige entre lo de su alcance (y el servidor solo le muestra eso)
            grupos = alcance.grupos_visibles()
            self.fields['grupo'].queryset = grupos
            self.fields['grado'].queryset = Grado.objects.academicos().filter(pk__in=grupos.values('grado'))
            self.fields['nivel'].choices = [('', 'Todos mis niveles'), *alcance.niveles_visibles()]
            niveles = [clave for clave, _ in alcance.niveles_visibles()]
            self.fields['periodo'].queryset = self.fields['periodo'].queryset.filter(nivel__in=niveles)
            if 'alumnos' in self.fields:
                self.fields['alumnos'].queryset = alcance.alumnos()
        self.fields['categoria'].queryset = CategoriaConducta.objects.order_by(orden_de_nivel('nivel'), 'nombre')
        self.fields['motivo'].queryset = MotivoConducta.objects.select_related('categoria').order_by('nombre')
        self.fields['motivo'].label_from_instance = lambda m: f'{m.nombre} · {m.categoria.nombre}{"" if m.activo else " (inactivo)"}'
        self.fields['medida'].queryset = MedidaDisciplinaria.objects.order_by(orden_de_nivel('nivel'), 'nombre')
        if not self.is_bound or 'ciclo' not in self.data:
            # Sin «ciclo» en la dirección, el ciclo actual; va en los datos para que el selector muestre lo aplicado
            actual = ciclo_actual()
            if self.is_bound:
                self.data = self.data.copy()
                self.data['ciclo'] = str(actual.pk) if actual else ''
            else:
                self.initial.setdefault('ciclo', actual.pk if actual else None)
        self.aplicar_estilo()

    def _datos(self):
        self.is_valid()
        return {k: v for k, v in (getattr(self, 'cleaned_data', None) or {}).items() if k not in self.errors}

    def filtro(self):
        """El `Filtro` de lo elegido (lo inválido de la dirección se ignora)."""
        datos = self._datos()
        ciclo = datos.get('ciclo')
        if ciclo is None and not (self.is_bound and 'ciclo' in self.data):
            ciclo = ciclo_actual()
        return reglas.Filtro(
            ciclo=ciclo, periodo=datos.get('periodo'), desde=datos.get('desde'), hasta=datos.get('hasta'),
            nivel=datos.get('nivel') or '', grado=datos.get('grado'), grupo=datos.get('grupo'), tipo=datos.get('tipo') or '',
            categoria=datos.get('categoria'), motivo=datos.get('motivo'), gravedad=datos.get('gravedad') or '',
            medida=datos.get('medida'), suspension=datos.get('suspension') or '', estado=datos.get('estado') or '',
            registros=datos.get('registros') or reglas.VIGENTES, texto=datos.get('q') or '',
            alumnos=list(datos.get('alumnos') or []), bitacora=datos.get('bitacora') != 'no',
        )

    @property
    def activos(self):
        """Cuántos filtros de «Más filtros» hay aplicados (para dejarlo abierto)."""
        datos = self._datos()
        principales = ('ciclo', 'q', 'reporte', 'alumnos', 'nivel', 'tipo', 'registros', 'bitacora')
        return sum(1 for k, v in datos.items() if v and k not in principales) + (datos.get('registros') not in (None, '', reglas.VIGENTES))

    @property
    def tipo_de_reporte(self):
        return self._datos().get('reporte') or next(iter(self.reportes))

    @property
    def alumnos_elegidos(self):
        return list(self._datos().get('alumnos') or [])
