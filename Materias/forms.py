import re

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Exists, OuterRef, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property

from Alumnos.academico import asegurar_en_el_plan, motivo_para_no_cambiar_de_grado, pasar_al_grado
from Alumnos.docentes import mensaje_fuera_de_nivel
from Alumnos.forms import CicloChoiceField, EstiloCamposMixin
from Alumnos.models import CicloEscolar, Grado, Materia, MateriaGrado, Profesor, orden_de_nivel
from Alumnos.utils import compactar_espacios

from .claves import clave_sugerida

CLAVE_VALIDA = re.compile(r'^[\w.-]+$')


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
class SelectorDeProfesor(forms.Select):
    """Cada opción lleva los niveles en los que da clases el profesor (data-niveles="PRIMARIA,SECUNDARIA"): materia-form.js
    deja a la vista solo a quienes dan clases en el nivel del grado elegido."""

    niveles = {}

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        opcion = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value not in (None, ''):
            opcion['attrs']['data-niveles'] = ','.join(self.niveles.get(int(str(value)), []))
        return opcion


class MateriaForm(EstiloCamposMixin, forms.ModelForm):
    """Alta y edición. La baja y la reactivación son acciones aparte (no hay borrado físico).

    Una materia la imparte un solo grado, y con eso queda en el plan de ese grado: al registrarla se agrega al ciclo actual
    (si lo hay) y al cambiarle el grado su clase pasa al grado nuevo. Al registrarla se le puede asignar el profesor, que
    solo puede ser uno que dé clases en el nivel del grado. Es opcional, pero registrarla sin profesor se confirma
    (`sin_profesor`). La clave se propone con las iniciales y el grado («MAT-1P») y se puede cambiar; si se deja vacía,
    se usa la propuesta.
    """

    profesor = forms.ModelChoiceField(
        queryset=Profesor.objects.none(), required=False, label='Profesor que la imparte', empty_label='Sin profesor por ahora',
        widget=SelectorDeProfesor,
    )
    # Lo envía el botón «Sí, registrar sin profesor» del aviso de confirmación
    sin_profesor = forms.BooleanField(required=False)

    class Meta:
        model = Materia
        fields = ['clave', 'nombre', 'grado']
        widgets = {
            'clave': forms.TextInput(attrs={'placeholder': 'MAT-1P', 'autocapitalize': 'characters', 'autocomplete': 'off', 'spellcheck': 'false'}),
            'nombre': forms.TextInput(attrs={'placeholder': 'Matemáticas', 'autocomplete': 'off', 'autofocus': True}),
            'grado': forms.RadioSelect(attrs={'class': 'choice__input'}),
        }
        help_texts = {
            'clave': 'Código corto y único: letras, números, punto o guion. Se guarda en mayúsculas.',
            'nombre': 'Cómo aparece en los horarios y en los listados.',
        }

    def __init__(self, *args, ciclo=None, puede_asignar_profesor=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.creando = self.instance._state.adding
        self.ciclo = ciclo
        self.asignacion = None          # su clase en el plan del ciclo actual (al registrarla o al cambiarle el grado)
        self.cambio_de_grado = False
        self.profesores_quitados = []   # al pasar a otro grado, los que no dan clases en su nivel
        self.pide_confirmacion = False  # se eligió el grado pero no el profesor, y falta confirmarlo

        # El grado que la imparte: uno solo. Al editar se ofrece también el suyo aunque esté dado de baja.
        grados = Grado.objects.filter(activo=True)
        if self.instance.grado_id:
            grados = Grado.objects.filter(Q(activo=True) | Q(pk=self.instance.grado_id))
        campo = self.fields['grado']
        campo.queryset = grados.academicos()
        campo.empty_label = None
        campo.label = 'Grado que la imparte'
        campo.required = False   # se exige en clean_grado cuando hay grados (ver grado_obligatorio)

        # Al registrarla se agrega al plan del ciclo actual de su grado (si hay ciclo actual y grados)
        self.motivo_sin_plan = ''
        if self.creando:
            if ciclo is None:
                self.motivo_sin_plan = 'No hay un ciclo escolar actual'
            elif not self.hay_grados:
                self.motivo_sin_plan = 'Todavía no hay grados activos'
        self.agrega_al_plan = self.creando and not self.motivo_sin_plan
        if self.agrega_al_plan:
            campo.help_text = f'Una materia la imparte un solo grado. Queda en su plan del ciclo {ciclo}.'
        elif self.creando:
            campo.help_text = 'Una materia la imparte un solo grado.'
        elif not self.instance.grado_id:
            campo.help_text = 'Una materia la imparte un solo grado. Al elegirlo, queda en su plan del ciclo actual.'
        else:
            campo.help_text = ('Una materia la imparte un solo grado. Si lo cambias, su clase del ciclo actual pasa al grado '
                               'nuevo (mientras todavía no tenga horario).')

        if self.agrega_al_plan and puede_asignar_profesor:
            profesores = list(Profesor.objects.filter(estatus='ACTIVO').prefetch_related('niveles'))
            self.fields['profesor'].queryset = Profesor.objects.filter(pk__in=[profesor.pk for profesor in profesores])
            self.fields['profesor'].widget.niveles = {profesor.pk: profesor.niveles_lista for profesor in profesores}
            self.fields['profesor'].help_text = 'Opcional. Solo aparecen quienes dan clases en el nivel del grado elegido.'
        else:
            del self.fields['profesor']
            del self.fields['sin_profesor']

        if self.creando:
            self.fields['clave'].required = False
            self.fields['clave'].help_text = (
                'Se propone con sus iniciales y el grado (P primaria, S secundaria, K preescolar, B preparatoria); puedes '
                'cambiarla. Debe ser única: letras, números, punto o guion.'
            )
        # materia-form.js pide la propuesta al servidor mientras se escribe el nombre y se elige el grado
        self.fields['clave'].widget.attrs.update({'data-clave-url': reverse('materias:clave'), 'data-excluir': self.instance.pk or ''})
        self.aplicar_estilo()

    @cached_property
    def hay_grados(self):
        return self.fields['grado'].queryset.exists()

    @property
    def grado_obligatorio(self):
        """Se pide siempre que haya grados, salvo al editar una materia de antes que todavía no tiene el suyo (se puede
        dejar así para corregir solo su nombre)."""
        return self.hay_grados and (self.creando or bool(self.instance.grado_id))

    @property
    def grados_por_nivel(self):
        """Las opciones del grado agrupadas por nivel: [{'nivel': 'PRIMARIA', 'nombre': 'Primaria', 'opciones': [...]}, ...]."""
        if not self.hay_grados:
            return []
        niveles = dict(self.fields['grado'].queryset.values_list('pk', 'nivel'))
        nombres = dict(Grado.NIVEL_CHOICES)
        grupos = []
        for opcion in self['grado']:
            nivel = niveles[int(str(opcion.data['value']))]
            if not grupos or grupos[-1]['nivel'] != nivel:
                grupos.append({'nivel': nivel, 'nombre': nombres[nivel], 'opciones': []})
            grupos[-1]['opciones'].append(opcion)
        return grupos

    def clean_clave(self):
        clave = re.sub(r'\s+', '-', compactar_espacios(self.cleaned_data.get('clave'))).upper()
        if not clave and self.creando:
            return ''   # se usa la propuesta (en clean, cuando ya se conocen el nombre y el grado)
        if not CLAVE_VALIDA.match(clave):
            raise ValidationError('Usa solo letras, números, punto o guion.')
        if Materia.objects.filter(clave__iexact=clave).exclude(pk=self.instance.pk).exists():
            raise ValidationError('Ya existe una materia con esa clave.')
        return clave

    def clean_nombre(self):
        return compactar_espacios(self.cleaned_data.get('nombre'))

    def clean_grado(self):
        grado = self.cleaned_data.get('grado')
        if grado is None and self.grado_obligatorio:
            raise ValidationError('Elige el grado que la imparte.', code='required')
        if self.creando or grado is None or grado.pk == self.instance.grado_id:
            return grado
        motivo = motivo_para_no_cambiar_de_grado(self.instance, grado)
        if motivo:
            raise ValidationError(motivo)
        return grado

    def clean(self):
        datos = super().clean()
        grado = datos.get('grado')
        if self.creando and not datos.get('clave') and 'clave' not in self.errors and datos.get('nombre'):
            datos['clave'] = clave_sugerida(datos['nombre'], [grado] if grado else ())
            if not datos['clave']:
                self.add_error('clave', 'Escribe la clave de la materia.')
        if 'profesor' in self.fields and grado is not None:
            profesor = datos.get('profesor')
            if profesor and grado.nivel not in profesor.niveles_lista:
                self.add_error('profesor', mensaje_fuera_de_nivel(profesor, grado))
            elif not profesor and not datos.get('sin_profesor'):
                # No es un error: se pregunta si de verdad va sin profesor (el aviso del formulario tiene el «Sí»)
                self.pide_confirmacion = True
                self.fields['nombre'].widget.attrs.pop('autofocus', None)
                self.add_error('sin_profesor', 'Confirma que la registras sin profesor.')
        return datos

    @property
    def solo_falta_confirmar(self):
        """Todo está bien salvo la confirmación de registrarla sin profesor (no es un dato por corregir)."""
        return self.pide_confirmacion and list(self.errors) == ['sin_profesor']

    def save(self, commit=True):
        self.cambio_de_grado = not self.creando and 'grado' in self.changed_data and self.cleaned_data.get('grado') is not None
        materia = super().save(commit)
        if not commit or not materia.grado_id:
            return materia
        if self.agrega_al_plan:
            self.asignacion = asegurar_en_el_plan(materia, self.ciclo)
        elif self.cambio_de_grado:
            self.profesores_quitados = pasar_al_grado(materia)
            self.asignacion = MateriaGrado.objects.filter(materia=materia, grado=materia.grado, ciclo__activo=True, activa=True).first()
        return materia


# ---------------------------------------------------------------------------
# Listado: filtros
# ---------------------------------------------------------------------------
class FiltroMateriasForm(EstiloCamposMixin, forms.Form):
    SITUACION_CHOICES = [
        ('', 'Con o sin profesor'),
        ('con_profesor', 'Con profesor en el ciclo actual'),
        ('sin_profesor', 'Sin profesor en el ciclo actual'),
        ('fuera_del_plan', 'Fuera del plan del ciclo actual'),
    ]
    ORDEN_CHOICES = [
        ('', 'Nombre (A-Z)'),
        ('-nombre', 'Nombre (Z-A)'),
        ('grado', 'Grado (orden escolar)'),
        ('clave', 'Clave'),
    ]

    q = forms.CharField(required=False, label='Buscar', widget=forms.TextInput(attrs={
        'type': 'search', 'placeholder': 'Clave o nombre de la materia…', 'autocomplete': 'off',
    }))
    estado = forms.ChoiceField(required=False, choices=[('', 'Activas'), ('BAJA', 'Bajas')], label='Estado')
    nivel = forms.ChoiceField(required=False, label='Nivel', choices=[('', 'Todos los niveles'), *Grado.NIVEL_CHOICES])
    grado = forms.ChoiceField(required=False, label='Grado')
    situacion = forms.ChoiceField(required=False, choices=SITUACION_CHOICES, label='Profesor')
    orden = forms.ChoiceField(required=False, choices=ORDEN_CHOICES, label='Ordenar por')

    def __init__(self, *args, ciclo=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.ciclo = ciclo
        # Los grados agrupados por nivel (<optgroup>), y al final las materias que todavía no tienen grado
        nombres = dict(Grado.NIVEL_CHOICES)
        grupos = {}
        for grado in Grado.objects.academicos():
            grupos.setdefault(nombres[grado.nivel], []).append((str(grado.pk), str(grado) if grado.activo else f'{grado} (de baja)'))
        self.fields['grado'].choices = [('', 'Todos los grados'), *grupos.items(), ('SIN_GRADO', 'Sin grado')]
        if ciclo is None:
            del self.fields['situacion']   # «con o sin profesor» se refiere al ciclo actual
        self.aplicar_estilo()

    @property
    def activos(self):
        """Valores válidos de los filtros (los inválidos de la URL se ignoran)."""
        self.is_valid()
        return {k: v for k, v in getattr(self, 'cleaned_data', {}).items() if v}

    def filtrar(self, queryset, con_estado=True):
        datos = self.activos
        for palabra in datos.get('q', '').split():
            queryset = queryset.filter(Q(clave__icontains=palabra) | Q(nombre__icontains=palabra))
        if con_estado:
            queryset = queryset.filter(activa=datos.get('estado') != 'BAJA')
        if datos.get('nivel'):
            queryset = queryset.filter(grado__nivel=datos['nivel'])
        if datos.get('grado') == 'SIN_GRADO':
            queryset = queryset.filter(grado__isnull=True)
        elif datos.get('grado'):
            queryset = queryset.filter(grado_id=datos['grado'])
        situacion = datos.get('situacion')
        if situacion and self.ciclo is not None:
            plan = MateriaGrado.objects.filter(ciclo=self.ciclo, activa=True, materia=OuterRef('pk'))
            if situacion == 'con_profesor':
                queryset = queryset.filter(Exists(plan.filter(profesor__isnull=False)))
            elif situacion == 'sin_profesor':
                queryset = queryset.filter(Exists(plan.filter(profesor__isnull=True)))
            else:
                queryset = queryset.exclude(Exists(plan))
        orden = datos.get('orden')
        if orden == 'grado':   # las que no tienen grado, al final
            return queryset.order_by(orden_de_nivel('grado__nivel'), 'grado__numero', 'nombre', 'clave')
        if orden == '-nombre':
            return queryset.order_by('-nombre', 'clave')
        if orden == 'clave':
            return queryset.order_by('clave')
        return queryset.order_by('nombre', 'clave')


# ---------------------------------------------------------------------------
# Copiar el plan (materias y horarios) de un ciclo a otro
# ---------------------------------------------------------------------------
class CopiarPlanForm(EstiloCamposMixin, forms.Form):
    origen = CicloChoiceField(CicloEscolar.objects.all(), empty_label='Selecciona el ciclo de origen', label='Copiar de este ciclo')
    destino = CicloChoiceField(CicloEscolar.objects.all(), empty_label='Selecciona el ciclo de destino', label='A este ciclo')
    horarios = forms.BooleanField(required=False, initial=True, label='Copiar también los horarios', widget=forms.CheckboxInput(attrs={'class': 'choice__input'}))
    conservar_profesor = forms.BooleanField(
        required=False, initial=True, label='Conservar al profesor de cada materia', widget=forms.CheckboxInput(attrs={'class': 'choice__input'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Se copia hacia el ciclo actual o hacia uno próximo, nunca hacia uno cerrado.
        self.fields['destino'].queryset = CicloEscolar.objects.filter(Q(activo=True) | Q(fecha_inicio__gt=timezone.localdate()))
        self.aplicar_estilo()

    def clean(self):
        datos = super().clean()
        origen, destino = datos.get('origen'), datos.get('destino')
        if origen and destino and origen == destino:
            self.add_error('destino', 'El ciclo de destino debe ser distinto al de origen.')
        return datos
