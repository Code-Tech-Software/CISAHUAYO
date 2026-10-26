from django import forms

import json

from django.db import transaction
from django.db.models import Q

from Alumnos.academico import (
    BASE_DE_EQUIVALENCIA,
    LARGO_EQUIVALENCIA,
    LIMITE_GRADOS,
    PREFIJO_DE_EQUIVALENCIA,
    extender_plan_al_grupo,
    suspender_plan,
)
from Alumnos.forms import EstiloCamposMixin
from Alumnos.models import Grado, Grupo, Inscripcion, NombreGrupo, q_ciclo


class GradoForm(EstiloCamposMixin, forms.ModelForm):
    """Alta y edición, con los grupos del grado (A, B…, del catálogo de nombres de grupo). La baja y la reactivación
    son acciones aparte (no hay borrado físico).

    Las reglas del grado (límite del nivel, sin repetir, equivalencia, nivel y número fijos con historial) están en
    `Grado.clean`, así valen también en el admin. Aquí: el nivel y el número se bloquean cuando ya tiene historial, y
    el grado y sus grupos se guardan juntos en una transacción.

    Un grupo que se agrega toma el plan de materias del grado; uno que se quita se da de baja (conserva su historial)
    con sus materias de los ciclos vigentes, y no se puede quitar mientras tenga estudiantes inscritos en el ciclo
    actual o en uno próximo.
    """

    grupos = forms.ModelMultipleChoiceField(
        NombreGrupo.objects.none(), required=False, label='Grupos',
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'choice__input'}),
        error_messages={'invalid_choice': 'Elige grupos de la lista.'},
    )

    class Meta:
        model = Grado
        fields = ['nivel', 'numero', 'equivalencia']
        labels = {'numero': 'Grado', 'equivalencia': 'Equivalencia en la continuidad escolar'}
        widgets = {
            'numero': forms.NumberInput(attrs={'min': 1, 'max': max(LIMITE_GRADOS.values()), 'inputmode': 'numeric'}),
            'equivalencia': forms.TextInput(attrs={
                'maxlength': LARGO_EQUIVALENCIA, 'autocomplete': 'off', 'autocapitalize': 'characters', 'spellcheck': 'false',
                'placeholder': 'Ej.: 7 o K1',
                # Lo usa static/js/grados-form.js para proponer la equivalencia habitual al elegir nivel y número
                'data-bases': json.dumps(BASE_DE_EQUIVALENCIA), 'data-prefijos': json.dumps(PREFIJO_DE_EQUIVALENCIA),
            }),
        }
        help_texts = {
            'numero': 'Preescolar y secundaria llegan hasta el 3.º; primaria y preparatoria, hasta el 6.º.',
            'equivalencia': (
                'Cómo se nombra este grado a lo largo de toda la trayectoria, sin importar el nivel: un número '
                '(1.º de secundaria es el 7) o un código con letras (K1 para 1.º de preescolar). Si la dejas vacía se propone la habitual.'
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['nivel'].choices = [('', 'Selecciona un nivel'), *Grado.NIVEL_CHOICES]
        self.grupos_agregados, self.grupos_quitados = [], []
        self.materias_suspendidas = 0
        # Con inscripciones o plan de materias, el nivel y el número ya no se cambian (moverían todo su historial)
        self.bloqueado = self.instance.tiene_historial
        if self.bloqueado:
            for campo in ('nivel', 'numero'):
                self.fields[campo].disabled = True
            self.fields['numero'].help_text = 'Ya tiene inscripciones o plan de materias: el nivel y el número ya no se cambian.'
        actuales = list(self.instance.grupos.filter(activo=True).values_list('nombre_id', flat=True)) if self.instance.pk else []
        if not actuales and not NombreGrupo.objects.filter(activo=True).exists():
            NombreGrupo.inicial()   # el catálogo nunca queda vacío: al menos «A»
        self.fields['grupos'].queryset = NombreGrupo.objects.filter(Q(activo=True) | Q(pk__in=actuales))
        self.fields['grupos'].help_text = 'Uno o varios. Los nombres se administran en «Grupos».'
        if not self.is_bound:
            self.initial['grupos'] = actuales or [NombreGrupo.inicial().pk]
        self.aplicar_estilo()
        self.fields['grupos'].widget.attrs['class'] = 'choice__input'   # el mixin le habría puesto la clase de los campos de texto

    def clean_grupos(self):
        elegidos = list(self.cleaned_data.get('grupos') or [])
        if not elegidos:
            elegidos = [NombreGrupo.inicial()]   # todo grado tiene al menos un grupo
        if self.instance.pk:
            # Un grupo con estudiantes inscritos (ciclo actual o próximo) no se puede quitar
            vigentes = q_ciclo('VIGENTE', 'ciclo__')
            for grupo in self.instance.grupos.filter(activo=True).exclude(nombre__in=elegidos).select_related('grado', 'nombre'):
                inscritos = Inscripcion.objects.filter(vigentes, grupo=grupo, activa=True).count()
                if inscritos:
                    raise forms.ValidationError(
                        f'El grupo {grupo.nombre} tiene {inscritos} estudiante{"s" if inscritos != 1 else ""} inscrito{"s" if inscritos != 1 else ""}: '
                        'cámbialos de grupo antes de quitarlo.'
                    )
        return elegidos

    def save(self, commit=True):
        # El grado, sus grupos y el plan de los grupos nuevos: todo o nada
        with transaction.atomic():
            grado = super().save(commit)
            if commit:
                self.sincronizar_grupos(grado)
        return grado

    def sincronizar_grupos(self, grado):
        """Deja activos exactamente los grupos elegidos: crea o reactiva los que faltan (con el plan del grado, y las
        materias que tenían si se habían quitado) y da de baja los que se quitaron, con sus materias de los ciclos
        vigentes."""
        elegidos = self.cleaned_data['grupos']
        for nombre in elegidos:
            grupo, creado = Grupo.objects.get_or_create(grado=grado, nombre=nombre)
            if creado or not grupo.activo:
                if not grupo.activo:
                    grupo.activo = True
                    grupo.save(update_fields=['activo'])
                extender_plan_al_grupo(grupo)
                self.grupos_agregados.append(grupo)
        quitados = list(grado.grupos.filter(activo=True).exclude(nombre__in=elegidos))
        for grupo in quitados:
            grupo.activo = False
            grupo.save(update_fields=['activo'])
            self.grupos_quitados.append(grupo)
        self.materias_suspendidas = suspender_plan(quitados)


class NivelCompletoForm(EstiloCamposMixin, forms.Form):
    """Alta de un nivel completo para la configuración inicial: del 1.º al grado elegido, cada uno con su equivalencia
    habitual y los grupos elegidos (con «A» por omisión). Los grados que ya existen se dejan como están."""

    nivel = forms.ChoiceField(label='Nivel', choices=[('', 'Selecciona un nivel'), *Grado.NIVEL_CHOICES],
                              error_messages={'required': 'Elige el nivel.'})
    hasta = forms.IntegerField(
        label='Del 1.º al', min_value=1, max_value=max(LIMITE_GRADOS.values()),
        widget=forms.NumberInput(attrs={'inputmode': 'numeric'}),
        help_text='Vacío: hasta el último grado del nivel (preescolar y secundaria, 3.º; primaria y preparatoria, 6.º).',
        required=False,
    )
    grupos = forms.ModelMultipleChoiceField(
        NombreGrupo.objects.none(), required=False, label='Grupos de cada grado',
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'choice__input'}),
        error_messages={'invalid_choice': 'Elige grupos de la lista.'},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.existentes = []
        if not NombreGrupo.objects.filter(activo=True).exists():
            NombreGrupo.inicial()
        self.fields['grupos'].queryset = NombreGrupo.objects.filter(activo=True)
        self.fields['grupos'].help_text = 'Uno o varios; sin elegir, el grupo «A».'
        if not self.is_bound:
            self.initial['grupos'] = [NombreGrupo.inicial().pk]
        self.aplicar_estilo()
        self.fields['grupos'].widget.attrs['class'] = 'choice__input'

    def clean(self):
        datos = super().clean()
        nivel = datos.get('nivel')
        if not nivel:
            return datos
        limite = LIMITE_GRADOS[nivel]
        hasta = datos.get('hasta') or limite
        if hasta > limite:
            self.add_error('hasta', f'En {dict(Grado.NIVEL_CHOICES)[nivel].lower()} los grados van del 1.º al {limite}.º.')
            return datos
        existentes = {grado.numero: grado for grado in Grado.objects.filter(nivel=nivel, numero__lte=hasta)}
        self.existentes = [existentes[numero] for numero in sorted(existentes)]
        nuevos = [Grado(nivel=nivel, numero=numero) for numero in range(1, hasta + 1) if numero not in existentes]
        if not nuevos:
            self.add_error('hasta', 'Todos esos grados ya existen.')
            return datos
        # Las reglas de cada grado (sobre todo, que su equivalencia habitual no la tenga ya otro grado activo)
        for grado in nuevos:
            try:
                grado.full_clean()
            except forms.ValidationError as error:
                for mensajes in error.message_dict.values():
                    for mensaje in mensajes:
                        self.add_error(None, f'{grado.nombre_de_nivel}: {mensaje}')
        datos['nuevos'] = nuevos
        return datos

    def save(self):
        """Crea los grados que faltan, con sus grupos, todo o nada. Devuelve los creados."""
        nombres = list(self.cleaned_data.get('grupos') or []) or [NombreGrupo.inicial()]
        with transaction.atomic():
            creados = []
            for grado in self.cleaned_data['nuevos']:
                grado.save()
                for nombre in nombres:
                    Grupo.objects.create(grado=grado, nombre=nombre)
                creados.append(grado)
        return creados
