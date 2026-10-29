from datetime import timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction

from Alumnos.academico import activar_ciclo, sugerir_ciclo
from Alumnos.forms import EstiloCamposMixin
from Alumnos.models import NIVEL_POR_SEMESTRES, CicloEscolar, Periodo, Semestre, q_ciclo
from Alumnos.utils import compactar_espacios

from .reglas import avisos_de_datos, fuera_del_rango


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
class CicloForm(EstiloCamposMixin, forms.ModelForm):
    """Nombre y fechas del ciclo. «Es el ciclo actual» solo aparece al crearlo: después, marcarlo como actual o cerrarlo
    pasa siempre por sus botones (con su confirmación). Las fechas que no se empalman con otro ciclo las valida el
    modelo; aquí, que al editarlas no quede fuera nada de lo que ya depende del ciclo. Un nombre que no coincide con
    los años o una duración rara se avisan y se guardan al confirmar («Guardar así»)."""

    es_actual = forms.BooleanField(
        required=False, label='Es el ciclo actual', widget=forms.CheckboxInput(attrs={'class': 'choice__input'}),
        help_text='Solo hay un ciclo actual: al marcarlo, el que lo era se cierra. En el ciclo actual se inscribe y se toma asistencia.',
    )
    confirmar = forms.BooleanField(required=False, widget=forms.HiddenInput)   # lo manda el botón «Guardar así»

    class Meta:
        model = CicloEscolar
        fields = ['nombre', 'fecha_inicio', 'fecha_fin']
        widgets = {
            'nombre': forms.TextInput(attrs={'placeholder': '2026-2027', 'autocomplete': 'off', 'autofocus': True}),
            'fecha_inicio': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'fecha_fin': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }
        help_texts = {
            'nombre': 'Normalmente el año en que empieza y el año en que termina, por ejemplo 2026-2027.',
        }

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario = usuario
        self.creando = self.instance._state.adding
        self.avisos = []          # nombre o duración por revisar (se guardan al confirmar)
        self.pide_confirmacion = False
        if self.creando:
            if not self.is_bound:
                # Propone el ciclo que sigue al más reciente; será el actual si todavía no hay uno.
                self.initial.update(sugerir_ciclo())
                self.initial['es_actual'] = not CicloEscolar.objects.actuales().exists()
        else:
            del self.fields['es_actual']
        self.aplicar_estilo()

    def clean_nombre(self):
        nombre = compactar_espacios(self.cleaned_data.get('nombre'))
        if CicloEscolar.objects.filter(nombre__iexact=nombre).exclude(pk=self.instance.pk).exists():
            raise ValidationError('Ya existe un ciclo con ese nombre.')
        return nombre

    def clean(self):
        datos = super().clean()
        inicio, fin = datos.get('fecha_inicio'), datos.get('fecha_fin')
        if not self.creando and inicio and fin and inicio < fin:
            fuera = fuera_del_rango(self.instance, inicio, fin)
            if fuera:
                raise ValidationError(
                    f'Con esas fechas quedarían fuera del ciclo: {"; ".join(fuera)}. Ajusta las fechas para que los incluyan.',
                    code='fuera_del_rango',
                )
        return datos

    def _post_clean(self):
        super()._post_clean()
        # Los avisos, solo cuando todo lo demás es válido y no se confirmaron
        if not self.errors and not self.cleaned_data.get('confirmar'):
            self.avisos = avisos_de_datos(self.cleaned_data.get('nombre'), self.cleaned_data.get('fecha_inicio'),
                                          self.cleaned_data.get('fecha_fin'))
            if self.avisos:
                self.pide_confirmacion = True
                self.add_error('confirmar', 'Revisa los avisos y confirma.')

    def save(self, commit=True):
        with transaction.atomic():
            ciclo = super().save(commit)
            if commit and self.creando and self.cleaned_data.get('es_actual'):
                activar_ciclo(ciclo, self.usuario)   # el que era actual se cierra
            elif commit and self.creando and self.usuario is not None:
                from Usuarios.seguridad import ACCION_ALTA, registrar
                registrar(self.usuario, ciclo, ACCION_ALTA, 'Registró el ciclo.')
        return ciclo


# ---------------------------------------------------------------------------
# Listado: filtro por estado
# ---------------------------------------------------------------------------
class FiltroCiclosForm(forms.Form):
    ESTADOS = ('ACTUAL', 'PROXIMO', 'CERRADO')

    estado = forms.ChoiceField(required=False, choices=[('', 'Todos'), *[(e, e) for e in ESTADOS]])

    @property
    def activos(self):
        """Valores válidos de los filtros (los inválidos de la URL se ignoran)."""
        self.is_valid()
        return {k: v for k, v in getattr(self, 'cleaned_data', {}).items() if v}

    def filtrar(self, queryset):
        estado = self.activos.get('estado')
        if estado:
            queryset = queryset.filter(q_ciclo(estado))
        return queryset.order_by('-fecha_inicio')


# ---------------------------------------------------------------------------
# Semestres de bachillerato (2026-10-28)
# ---------------------------------------------------------------------------
FECHA_SEMESTRE = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


class SemestresForm(EstiloCamposMixin, forms.Form):
    """Las fechas del semestre A y del B de un ciclo: dentro del ciclo, el A antes que el B y sin empalmarse. Las de un
    semestre cerrado ya no cambian, y los periodos que ya tiene asignados deben seguir dentro de sus fechas."""

    a_inicio = forms.DateField(label='Semestre A: inicio', widget=FECHA_SEMESTRE, error_messages={'required': 'Indica cuándo empieza.'})
    a_fin = forms.DateField(label='Semestre A: fin', widget=FECHA_SEMESTRE, error_messages={'required': 'Indica cuándo termina.'})
    b_inicio = forms.DateField(label='Semestre B: inicio', widget=FECHA_SEMESTRE, error_messages={'required': 'Indica cuándo empieza.'})
    b_fin = forms.DateField(label='Semestre B: fin', widget=FECHA_SEMESTRE, error_messages={'required': 'Indica cuándo termina.'})

    def __init__(self, *args, ciclo, **kwargs):
        self.ciclo = ciclo
        self.existentes = {s.clave: s for s in Semestre.objects.filter(ciclo=ciclo)}
        inicial = kwargs.setdefault('initial', {})
        for clave in ('A', 'B'):
            if clave in self.existentes:
                inicial.setdefault(f'{clave.lower()}_inicio', self.existentes[clave].fecha_inicio)
                inicial.setdefault(f'{clave.lower()}_fin', self.existentes[clave].fecha_fin)
        if not self.existentes:   # propuesta: el ciclo partido a la mitad
            mitad = ciclo.fecha_inicio + (ciclo.fecha_fin - ciclo.fecha_inicio) / 2
            inicial.update({'a_inicio': ciclo.fecha_inicio, 'a_fin': mitad, 'b_inicio': mitad + timedelta(days=1), 'b_fin': ciclo.fecha_fin})
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()

    def clean(self):
        datos = super().clean()
        if self.errors:
            return datos
        ciclo = self.ciclo
        fechas = {'A': (datos['a_inicio'], datos['a_fin']), 'B': (datos['b_inicio'], datos['b_fin'])}
        for clave, (inicio, fin) in fechas.items():
            campo = clave.lower()
            if fin <= inicio:
                self.add_error(f'{campo}_fin', 'Debe terminar después de empezar.')
            if inicio < ciclo.fecha_inicio or fin > ciclo.fecha_fin:
                self.add_error(f'{campo}_inicio', f'Debe quedar dentro del ciclo ({ciclo.fecha_inicio:%d/%m/%Y} al {ciclo.fecha_fin:%d/%m/%Y}).')
            existente = self.existentes.get(clave)
            if existente is not None and existente.cerrado and (existente.fecha_inicio, existente.fecha_fin) != (inicio, fin):
                self.add_error(f'{campo}_inicio', f'El {existente.en_frase} está cerrado: sus fechas ya no cambian.')
            if existente is not None:
                fuera = [p.nombre for p in Periodo.objects.filter(semestre=existente).order_by('fecha_inicio')
                         if p.fecha_inicio < inicio or p.fecha_fin > fin]
                if fuera:
                    self.add_error(f'{campo}_inicio', f'Quedarían fuera sus periodos: {", ".join(fuera)}.')
        if not self.errors and fechas['A'][1] >= fechas['B'][0]:
            self.add_error('b_inicio', 'El semestre B empieza después de que termina el A.')
        datos['fechas'] = fechas
        return datos

    @property
    def periodos_por_asignar(self):
        """Los periodos de preparatoria del ciclo que todavía no tienen semestre (se asignan por su fecha de inicio)."""
        return list(Periodo.objects.filter(ciclo=self.ciclo, nivel=NIVEL_POR_SEMESTRES, semestre__isnull=True).order_by('fecha_inicio'))
