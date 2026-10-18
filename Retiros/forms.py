"""Formularios de los retiros anticipados. Validan la forma de los datos; las reglas del negocio (permisos, horario,
duplicados, quién puede recoger) están en Retiros/reglas.py."""
from datetime import datetime

from django import forms
from django.db.models import Q
from django.utils import timezone

from Alumnos.forms import EstiloCamposMixin
from Alumnos.models import Grado, Grupo
from Conducta.forms import FECHA, HORA

from .models import MotivoRetiro, RetiroEstudiante
from .reglas import autorizados_para, nombre_de

TEXTO_CORTO = {'rows': 3}


# ---------------------------------------------------------------------------
# Tutor
# ---------------------------------------------------------------------------
class AvisoForm(EstiloCamposMixin, forms.Form):
    """El aviso del tutor. `hijos`: los de reglas.hijos_de (los no disponibles se muestran, pero no se pueden elegir)."""

    alumnos = forms.TypedMultipleChoiceField(coerce=int, label='Estudiantes', error_messages={
        'required': 'Elige al menos un estudiante.', 'invalid_choice': 'Elige estudiantes de la lista.'})
    fecha = forms.DateField(label='Fecha del retiro', widget=FECHA)
    hora = forms.TimeField(label='Hora estimada', widget=HORA)
    motivo = forms.ModelChoiceField(MotivoRetiro.objects.none(), label='Motivo', empty_label='Elige el motivo…')
    detalles = forms.CharField(label='Detalles u observaciones', required=False, max_length=1000,
                               widget=forms.Textarea(attrs={**TEXTO_CORTO, 'placeholder': 'Lo que el colegio deba saber (opcional, salvo que el motivo lo pida)'}))
    recoge = forms.TypedChoiceField(coerce=int, label='¿Quién recogerá?', error_messages={
        'required': 'Elige quién recogerá a los estudiantes.', 'invalid_choice': 'Elige a una persona autorizada de la lista.'})

    def __init__(self, *args, tutor, hijos, **kwargs):
        super().__init__(*args, **kwargs)
        self.tutor, self.hijos = tutor, hijos
        disponibles = [h for h in hijos if h.disponible]
        self.fields['alumnos'].choices = [(h.alumno.pk, nombre_de(h.alumno)) for h in disponibles]
        self.fields['motivo'].queryset = MotivoRetiro.objects.filter(activo=True)
        self.personas = personas_autorizadas(tutor, [h.alumno for h in disponibles])
        self.fields['recoge'].choices = [(p['tutor'].pk, p['nombre']) for p in self.personas]
        hoy = timezone.localdate()
        self.fields['fecha'].widget.attrs['min'] = hoy.isoformat()
        self.aplicar_estilo()

    def elegidos(self):
        """Los ids de los estudiantes marcados (también si el formulario tiene errores), para volver a pintarlos."""
        valores = self.data.getlist('alumnos') if self.is_bound else []
        return {int(v) for v in valores if str(v).isdigit()}


def personas_autorizadas(tutor, alumnos):
    """Quién puede recoger a esos estudiantes: [{'tutor', 'nombre', 'alumnos': {ids}, 'detalle'}], el propio tutor
    primero. Solo personas ya autorizadas en el sistema (tutores del estudiante con «Autorizado para recoger»)."""
    alumnos = list(alumnos)
    nombres = {a.pk: a.nombre for a in alumnos}
    por_tutor = {}
    for alumno_id, vinculos in autorizados_para(nombres).items():
        for tutor_id, vinculo in vinculos.items():
            fila = por_tutor.setdefault(tutor_id, {'tutor': vinculo.tutor, 'alumnos': set(), 'parentescos': {}})
            fila['alumnos'].add(alumno_id)
            fila['parentescos'][alumno_id] = vinculo.get_parentesco_display()
    personas = []
    for tutor_id, fila in por_tutor.items():
        propio = tutor_id == tutor.pk
        de_quien = ', '.join(f'{nombres[pk]} ({fila["parentescos"][pk].lower()})' for pk in nombres if pk in fila['alumnos'])
        personas.append({
            'tutor': fila['tutor'], 'alumnos': fila['alumnos'], 'propio': propio,
            'nombre': f'Yo ({nombre_de(fila["tutor"])})' if propio else nombre_de(fila['tutor']),
            'detalle': f'Puede recoger a: {de_quien}',
            'ids': ','.join(str(pk) for pk in sorted(fila['alumnos'])),
        })
    personas.sort(key=lambda p: (not p['propio'], p['nombre']))
    return personas


class CancelarForm(EstiloCamposMixin, forms.Form):
    """Cancelar algunos o todos los estudiantes todavía avisados. El personal debe escribir el motivo (lo verá el tutor)."""

    retiros = forms.TypedMultipleChoiceField(coerce=int, label='Estudiantes', widget=forms.CheckboxSelectMultiple(attrs={'class': 'choice__input'}), error_messages={
        'required': 'Elige a quién cancelar.', 'invalid_choice': 'Elige estudiantes de la lista.'})
    motivo = forms.CharField(label='Motivo de la cancelación', required=False, max_length=500, widget=forms.Textarea(attrs=TEXTO_CORTO))

    def __init__(self, *args, retiros, motivo_obligatorio=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['retiros'].choices = [(r.pk, nombre_de(r.alumno)) for r in retiros]
        if len(retiros) == 1 and not self.is_bound:
            self.initial['retiros'] = [retiros[0].pk]
        if motivo_obligatorio:
            self.fields['motivo'].required = True
            self.fields['motivo'].help_text = 'El tutor lo verá.'
        else:
            self.fields['motivo'].label = 'Motivo (opcional)'
        self.aplicar_estilo()


# ---------------------------------------------------------------------------
# Personal
# ---------------------------------------------------------------------------
def _opciones_de_quien_recoge(retiro):
    vinculos = autorizados_para([retiro.alumno_id]).get(retiro.alumno_id, {})
    opciones = [(tutor_id, f'{nombre_de(v.tutor)} · {v.get_parentesco_display()}' + (f' · Tel. {v.tutor.telefono}' if v.tutor.telefono else ''))
                for tutor_id, v in vinculos.items()]
    opciones.sort(key=lambda opcion: (opcion[0] != retiro.aviso.recoge_id, opcion[1]))
    return opciones, vinculos


class ConfirmarSalidaForm(EstiloCamposMixin, forms.Form):
    recogio = forms.TypedChoiceField(coerce=int, label='Persona que recoge', error_messages={
        'required': 'Elige a la persona autorizada que lo recoge.', 'invalid_choice': 'Elige a una persona autorizada de la lista.'})
    hora = forms.TimeField(label='Hora real de salida', widget=HORA)
    verificado = forms.BooleanField(label='Verifiqué la identidad de quien recoge (identificación oficial) y que está autorizado.',
                                    error_messages={'required': 'Confirma que verificaste a la persona que recoge.'})
    observaciones = forms.CharField(label='Observaciones (opcional)', required=False, max_length=1000, widget=forms.Textarea(attrs=TEXTO_CORTO))

    def __init__(self, *args, retiro, **kwargs):
        super().__init__(*args, **kwargs)
        self.retiro = retiro
        self.fields['recogio'].choices, self.vinculos = _opciones_de_quien_recoge(retiro)
        if not self.is_bound:
            self.initial.setdefault('hora', timezone.localtime().strftime('%H:%M'))
            if retiro.aviso.recoge_id in self.vinculos:
                self.initial.setdefault('recogio', retiro.aviso.recoge_id)
        self.aplicar_estilo()

    def momento(self):
        return timezone.make_aware(datetime.combine(self.retiro.fecha, self.cleaned_data['hora']), timezone.get_current_timezone())

    def persona(self):
        vinculo = self.vinculos.get(self.cleaned_data['recogio'])
        return vinculo.tutor if vinculo else None


class CorregirSalidaForm(ConfirmarSalidaForm):
    ACCIONES = [('corregir', 'Corregir los datos de la salida'), ('deshacer', 'La salida se registró por error: volver a «Avisado»')]

    accion = forms.ChoiceField(choices=ACCIONES, initial='corregir', label='¿Qué se corrige?', widget=forms.RadioSelect(attrs={'class': 'choice__input'}))
    motivo = forms.CharField(label='Motivo de la corrección', max_length=500, widget=forms.Textarea(attrs=TEXTO_CORTO),
                             help_text='Queda en la bitácora con lo que había y lo que quedó.')

    field_order = ['accion', 'recogio', 'hora', 'observaciones', 'motivo']

    def __init__(self, *args, retiro, **kwargs):
        super().__init__(*args, retiro=retiro, **kwargs)
        del self.fields['verificado']
        if not self.is_bound:
            self.initial.update(hora=timezone.localtime(retiro.salida_en).strftime('%H:%M') if retiro.salida_en else '',
                                recogio=retiro.recogio_id, observaciones=retiro.observaciones_salida)
        if self.data.get('accion') == 'deshacer':   # deshacer no necesita los datos de la salida
            for campo in ('recogio', 'hora'):
                self.fields[campo].required = False
        self.aplicar_estilo()

    @property
    def deshacer(self):
        return self.cleaned_data.get('accion') == 'deshacer'


class NotaForm(EstiloCamposMixin, forms.Form):
    texto = forms.CharField(label='Observación interna', max_length=1000, widget=forms.Textarea(attrs={
        **TEXTO_CORTO, 'placeholder': 'Solo la ve el personal del colegio (el tutor no).'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()


class MotivoForm(EstiloCamposMixin, forms.ModelForm):
    class Meta:
        model = MotivoRetiro
        fields = ['nombre', 'orden', 'requiere_explicacion', 'activo']
        widgets = {'requiere_explicacion': forms.CheckboxInput(attrs={'class': 'choice__input'}),
                   'activo': forms.CheckboxInput(attrs={'class': 'choice__input'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aplicar_estilo()

    def clean_nombre(self):
        nombre = ' '.join(self.cleaned_data['nombre'].split())
        repetido = MotivoRetiro.objects.filter(nombre__iexact=nombre).exclude(pk=self.instance.pk)
        if repetido.exists():
            raise forms.ValidationError('Ya hay un motivo con ese nombre.')
        return nombre


class FiltroRetirosForm(EstiloCamposMixin, forms.Form):
    """Búsqueda y filtros de la gestión de retiros, limitados al alcance de quien consulta."""

    q = forms.CharField(required=False, label='Buscar', widget=forms.TextInput(attrs={
        'type': 'search', 'placeholder': 'Estudiante, tutor o folio…', 'autocomplete': 'off'}))
    desde = forms.DateField(required=False, label='Desde', widget=FECHA)
    hasta = forms.DateField(required=False, label='Hasta', widget=FECHA)
    nivel = forms.ChoiceField(choices=[('', 'Todos los niveles')], required=False, label='Nivel')
    grado = forms.ModelChoiceField(Grado.objects.none(), required=False, empty_label='Todos los grados', label='Grado')
    grupo = forms.ModelChoiceField(Grupo.objects.none(), required=False, empty_label='Todos los grupos', label='Grupo')
    motivo = forms.ModelChoiceField(MotivoRetiro.objects.all(), required=False, empty_label='Todos los motivos', label='Motivo')
    estado = forms.ChoiceField(choices=[('', 'Todos los estados'), *RetiroEstudiante.ESTADOS], required=False, label='Estado')

    def __init__(self, *args, alcance, **kwargs):
        super().__init__(*args, **kwargs)
        grupos = alcance.grupos_visibles()
        self.fields['grupo'].queryset = grupos
        self.fields['grado'].queryset = Grado.objects.academicos().filter(pk__in=grupos.values('grado'))
        self.fields['nivel'].choices = [('', 'Todos los niveles' if alcance.total else 'Todos mis niveles'), *alcance.niveles_visibles()]
        self.aplicar_estilo()

    def datos(self):
        self.is_valid()
        return {k: v for k, v in (getattr(self, 'cleaned_data', None) or {}).items() if k not in self.errors}

    def filtrar(self, consulta, con_fechas=True):
        """Aplica la búsqueda y los filtros a `RetiroEstudiante`."""
        datos = self.datos()
        if con_fechas and datos.get('desde'):
            consulta = consulta.filter(fecha__gte=datos['desde'])
        if con_fechas and datos.get('hasta'):
            consulta = consulta.filter(fecha__lte=datos['hasta'])
        if datos.get('nivel'):
            consulta = consulta.filter(inscripcion__grado__nivel=datos['nivel'])
        if datos.get('grupo'):
            consulta = consulta.filter(inscripcion__grupo=datos['grupo'])
        elif datos.get('grado'):
            consulta = consulta.filter(inscripcion__grado=datos['grado'])
        if datos.get('motivo'):
            consulta = consulta.filter(aviso__motivo=datos['motivo'])
        if datos.get('estado'):
            consulta = consulta.filter(estado=datos['estado'])
        for palabra in (datos.get('q') or '').split():
            condicion = Q(aviso__folio__icontains=palabra)
            for persona in ('alumno', 'aviso__tutor', 'aviso__recoge'):
                condicion |= (Q(**{f'{persona}__nombre__icontains': palabra}) | Q(**{f'{persona}__apellido_paterno__icontains': palabra})
                              | Q(**{f'{persona}__apellido_materno__icontains': palabra}))
            condicion |= Q(alumno__referencia__icontains=palabra)
            consulta = consulta.filter(condicion)
        return consulta

    @property
    def activos(self):
        return sum(1 for clave, valor in self.datos().items() if valor and clave not in ('q',))
