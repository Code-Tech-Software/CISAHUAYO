import calendar
from datetime import timedelta

from django import forms
from django.core.exceptions import ValidationError

from Alumnos.forms import EstiloCamposMixin
from Alumnos.models import ORDEN_NIVELES, Grado, Grupo
from Conducta.forms import validar_archivo

from .models import COLEGIO, NIVELES, TIPOS, VARIOS, EventoAgenda
from .reglas import DIAS, HASTA_UN_ANIO, MENSUAL_ORDINAL, MENSUAL_ULTIMO, REPETICIONES

FECHA = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')
HORA = forms.TimeInput(attrs={'type': 'time'}, format='%H:%M')
CASILLA = forms.CheckboxInput(attrs={'class': 'choice__input'})


class CasillasPorNivel(forms.CheckboxSelectMultiple):
    """Cada casilla lleva el nivel de su grado (data-nivel): el formulario muestra solo los grados y grupos de los
    niveles elegidos (static/js/agenda-formulario.js)."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        opcion = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        instancia = getattr(value, 'instance', None)
        if instancia is not None:
            opcion['attrs']['data-nivel'] = getattr(instancia, 'nivel', None) or instancia.grado.nivel
        return opcion


class EventoForm(EstiloCamposMixin, forms.ModelForm):
    """Registrar o editar un evento. La finalización no puede ser anterior al inicio; sin «Todo el día», las horas son
    obligatorias (y con «Todo el día» se descartan). Al registrarlo se puede repetir (Agenda/reglas.py: hasta la fecha
    elegida, como máximo un año); al editar uno de una serie, se elige si los cambios van también a los siguientes.

    Para quién (2026-11-02): uno o varios niveles (o todo el colegio) y, dentro de ellos, si se quiere, solo algunos
    grados o grupos; si lo ven las familias y los estudiantes (el personal de esos niveles, siempre). Quien gestiona solo
    sus niveles (`vista.gestiona_niveles`) no ve «Todos los niveles» ni los otros niveles. `archivos`: los que se suben."""

    alcance = forms.MultipleChoiceField(label='Niveles', widget=forms.CheckboxSelectMultiple(attrs={'class': 'choice__input'}),
                                        error_messages={'required': 'Elige al menos un nivel (o «Todos los niveles»).'})
    grados = forms.ModelMultipleChoiceField(Grado.objects.none(), required=False, label='Solo estos grados',
                                            widget=CasillasPorNivel(attrs={'class': 'choice__input'}))
    grupos = forms.ModelMultipleChoiceField(Grupo.objects.none(), required=False, label='Solo estos grupos',
                                            widget=CasillasPorNivel(attrs={'class': 'choice__input'}))
    repetir = forms.ChoiceField(label='Repetir', required=False, choices=[('', 'No se repite'), *REPETICIONES])
    repetir_hasta = forms.DateField(label='Hasta', required=False, widget=FECHA, input_formats=['%Y-%m-%d'])
    saltar_sin_clases = forms.BooleanField(label='Saltar los días sin clases', required=False, initial=True)
    toda_la_serie = forms.BooleanField(label='Aplicar los cambios también a los siguientes de la serie', required=False,
                                       help_text='Sus fechas no cambian: solo el título, la descripción, para quién es, el tipo, el horario, el lugar y los avisos.')
    avisar_cambio = forms.BooleanField(label='Avisar del cambio a quienes lo ven', required=False, initial=True,
                                       help_text='Si cambias la fecha, el horario o el lugar, les llega un aviso en la campana y en el teléfono.')

    class Meta:
        model = EventoAgenda
        fields = ['titulo', 'descripcion', 'tipo', 'fecha_inicio', 'fecha_fin', 'todo_el_dia', 'hora_inicio', 'hora_fin', 'lugar',
                  'importante', 'recordar_dias', 'para_familias', 'para_estudiantes', 'pide_confirmacion']
        widgets = {
            'descripcion': forms.Textarea(attrs={'rows': 3}),
            'fecha_inicio': FECHA, 'fecha_fin': FECHA, 'hora_inicio': HORA, 'hora_fin': HORA,
            'todo_el_dia': forms.CheckboxInput(attrs={'class': 'choice__input', 'data-agenda-todo-el-dia': ''}),
            'importante': forms.CheckboxInput(attrs={'class': 'choice__input', 'data-agenda-importante': ''}),
            'para_familias': forms.CheckboxInput(attrs={'class': 'choice__input', 'data-agenda-familias': ''}),
            'para_estudiantes': forms.CheckboxInput(attrs={'class': 'choice__input', 'data-agenda-estudiantes': ''}),
            'pide_confirmacion': CASILLA,
        }

    def __init__(self, *args, vista=None, archivos=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.vista = vista
        self.archivos = list(archivos)
        self.archivos_validos = []
        self.destino = ((), (), ())
        niveles = vista.niveles_que_gestiona if vista is not None else list(ORDEN_NIVELES)
        todo = vista is None or vista.gestiona_todo
        nombres = dict(NIVELES)
        self.fields['alcance'].choices = [*([(COLEGIO, 'Todos los niveles')] if todo else []), *[(n, nombres[n]) for n in niveles]]
        grados = Grado.objects.disponibles().filter(nivel__in=niveles)
        if self.instance.pk:
            grados = grados | Grado.objects.filter(pk__in=self.instance.grados.values('pk'))
            self.initial.setdefault('alcance', [COLEGIO] if self.instance.alcance == COLEGIO else self.instance.niveles_del_evento)
            self.initial.setdefault('grados', list(self.instance.grados.all()))
            self.initial.setdefault('grupos', list(self.instance.grupos.all()))
        self.fields['grados'].queryset = grados.distinct().order_by('nivel', 'numero')
        grupos = Grupo.objects.filter(grado__in=self.fields['grados'].queryset, activo=True)
        if self.instance.pk:
            grupos = grupos | Grupo.objects.filter(pk__in=self.instance.grupos.values('pk'))
        self.fields['grupos'].queryset = grupos.distinct().select_related('grado', 'nombre').order_by('grado__nivel', 'grado__numero', 'pk')
        self.fields['grados'].label_from_instance = str
        self.fields['grupos'].label_from_instance = str
        self.fields['tipo'].choices = [('', 'Otro (sin tipo)'), *TIPOS]
        self.fields['fecha_fin'].required = False
        self.fields['fecha_fin'].help_text = 'Vacía: el mismo día.'
        self.fields['descripcion'].help_text = 'Las direcciones (https://…) se podrán tocar.'
        self.fields['recordar_dias'].label = 'Recordar'
        self.fields['recordar_dias'].required = False   # sin recordatorio no importa; vacío, un día antes
        self.fields['pide_confirmacion'].help_text = 'Las familias responden en su portal si asistirán y cuántas personas; tú ves el resumen en el detalle.'
        self.fields['repetir'].widget.attrs['data-agenda-repetir'] = ''
        for nombre in ('saltar_sin_clases', 'toda_la_serie', 'avisar_cambio'):
            self.fields[nombre].widget.attrs['class'] = 'choice__input'
        if self.instance.pk:   # editar: la repetición ya se eligió al registrarlo
            del self.fields['repetir'], self.fields['repetir_hasta'], self.fields['saltar_sin_clases']
            if not self.instance.serie:
                del self.fields['toda_la_serie']
        else:
            del self.fields['toda_la_serie'], self.fields['avisar_cambio']
        self.aplicar_estilo()

    @property
    def es_de_una_serie(self):
        return 'toda_la_serie' in self.fields

    @property
    def adjuntos_guardados(self):
        return list(self.instance.adjuntos.all()) if self.instance.pk else []

    def quitar_adjuntos(self):
        """Los archivos ya guardados que se marcaron para quitar."""
        if not self.instance.pk or not hasattr(self.data, 'getlist'):
            return []
        return [int(pk) for pk in self.data.getlist('quitar_adjuntos') if pk.isascii() and pk.isdigit()]

    def _limpiar_destino(self, datos):
        elegidos = datos.get('alcance') or []
        if not elegidos:
            return
        todo = self.vista is None or self.vista.gestiona_todo
        if COLEGIO in elegidos or (todo and set(ORDEN_NIVELES) <= set(elegidos)):
            alcance, niveles = COLEGIO, list(ORDEN_NIVELES)
        else:
            niveles = [n for n in ORDEN_NIVELES if n in elegidos]
            alcance = niveles[0] if len(niveles) == 1 else VARIOS
        grados, grupos = list(datos.get('grados') or []), list(datos.get('grupos') or [])
        fuera = [str(g) for g in grados if g.nivel not in niveles] + [str(g) for g in grupos if g.grado.nivel not in niveles]
        if fuera:
            self.add_error('grados', f'{", ".join(fuera)} no {"es" if len(fuera) == 1 else "son"} de los niveles elegidos.')
        self.instance.alcance = alcance
        self.destino = (niveles if alcance == VARIOS else (), grados, grupos)

    def clean(self):
        datos = super().clean()
        self._limpiar_destino(datos)
        datos['recordar_dias'] = datos.get('recordar_dias') or 1
        inicio, fin = datos.get('fecha_inicio'), datos.get('fecha_fin')
        if inicio and not fin:
            datos['fecha_fin'] = fin = inicio
        if inicio and fin and fin < inicio:
            self.add_error('fecha_fin', 'La fecha de finalización no puede ser anterior a la de inicio.')
        repetir = datos.get('repetir')
        if repetir:
            hasta = datos.get('repetir_hasta')
            if not hasta:
                self.add_error('repetir_hasta', 'Elige hasta cuándo se repite.')
            elif inicio and hasta <= inicio:
                self.add_error('repetir_hasta', 'Debe ser después de la fecha de inicio.')
            elif inicio and hasta > inicio + timedelta(days=HASTA_UN_ANIO):
                self.add_error('repetir_hasta', 'Se puede repetir hasta un año después de la fecha de inicio.')
            if inicio and repetir == MENSUAL_ULTIMO and inicio.day + 7 <= calendar.monthrange(inicio.year, inicio.month)[1]:
                self.add_error('repetir', f'Esa fecha no es el último {DIAS[inicio.weekday()]} del mes: elige otra repetición o cambia la fecha.')
            if inicio and repetir == MENSUAL_ORDINAL and inicio.day > 28:
                self.add_error('repetir', f'Es el quinto {DIAS[inicio.weekday()]} del mes y no todos los meses lo tienen: '
                                          f'elige «Cada mes, el último {DIAS[inicio.weekday()]}».')
        if datos.get('pide_confirmacion') and not datos.get('para_familias'):
            self.add_error('pide_confirmacion', 'Para pedir confirmación, el evento tiene que ser para las familias.')
        self._limpiar_archivos()
        if datos.get('todo_el_dia'):
            datos['hora_inicio'] = datos['hora_fin'] = None
            return datos
        hora_inicio, hora_fin = datos.get('hora_inicio'), datos.get('hora_fin')
        if hora_inicio is None:
            self.add_error('hora_inicio', 'Indica la hora de inicio (o marca «Todo el día»).')
        if hora_fin is None:
            self.add_error('hora_fin', 'Indica la hora de finalización (o marca «Todo el día»).')
        if hora_inicio and hora_fin and inicio and fin and inicio == fin and hora_fin <= hora_inicio:
            self.add_error('hora_fin', 'La hora de finalización debe ser posterior a la de inicio.')
        return datos

    def _limpiar_archivos(self):
        guardados = len([a for a in self.adjuntos_guardados if a.pk not in self.quitar_adjuntos()])
        if guardados + len(self.archivos) > EventoAgenda.MAXIMO_ADJUNTOS:
            self.add_error(None, f'Adjunta como máximo {EventoAgenda.MAXIMO_ADJUNTOS} archivos.')
            return
        for archivo in self.archivos:
            try:
                self.archivos_validos.append((archivo, validar_archivo(archivo)))
            except ValidationError as error:
                self.add_error(None, error)


class CancelarForm(EstiloCamposMixin, forms.Form):
    motivo = forms.CharField(label='Motivo (lo verán quienes tienen el evento en su agenda)', max_length=200, required=False,
                             widget=forms.TextInput(attrs={'placeholder': 'Por lluvia, se pospone…'}))
    avisar = forms.BooleanField(label='Avisar de la cancelación a quienes lo ven', required=False, initial=True,
                                widget=forms.CheckboxInput(attrs={'class': 'choice__input'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()

    def clean_motivo(self):
        return ' '.join(self.cleaned_data.get('motivo', '').split())
