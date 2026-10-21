from django import forms

import json

from django.db.models import Q
from django.utils import timezone

from Alumnos.academico import (
    BASE_DE_EQUIVALENCIA,
    FORMATO_EQUIVALENCIA,
    LARGO_EQUIVALENCIA,
    LIMITE_GRADOS,
    PREFIJO_DE_EQUIVALENCIA,
    equivalencia_sugerida,
    extender_plan_al_grupo,
    normalizar_equivalencia,
)
from Alumnos.forms import EstiloCamposMixin
from Alumnos.models import Grado, Grupo, Inscripcion, NombreGrupo


class GradoForm(EstiloCamposMixin, forms.ModelForm):
    """Alta y edición, con los grupos del grado (A, B…, del catálogo de nombres de grupo). La baja y la reactivación
    son acciones aparte (no hay borrado físico).

    Un grupo que se agrega toma el plan de materias del grado; uno que se quita se da de baja (conserva su historial),
    y no se puede quitar mientras tenga estudiantes inscritos en el ciclo actual o en uno próximo.
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
            'numero': 'Preescolar y secundaria llegan hasta el 3.°; primaria, hasta el 6.°.',
            'equivalencia': (
                'Cómo se nombra este grado a lo largo de toda la trayectoria, sin importar el nivel: un número '
                '(1.° de secundaria es el 7) o un código con letras (K1 para 1.° de preescolar). Si la dejas vacía se propone la habitual.'
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['nivel'].choices = [('', 'Selecciona un nivel'), *Grado.NIVEL_CHOICES]
        self.grupos_agregados, self.grupos_quitados = [], []
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
            vigentes = Q(ciclo__activo=True) | Q(ciclo__fecha_inicio__gt=timezone.localdate())
            for grupo in self.instance.grupos.filter(activo=True).exclude(nombre__in=elegidos).select_related('grado', 'nombre'):
                inscritos = Inscripcion.objects.filter(vigentes, grupo=grupo, activa=True).count()
                if inscritos:
                    raise forms.ValidationError(
                        f'El grupo {grupo.nombre} tiene {inscritos} estudiante{"s" if inscritos != 1 else ""} inscrito{"s" if inscritos != 1 else ""}: '
                        'cámbialos de grupo antes de quitarlo.'
                    )
        return elegidos

    def save(self, commit=True):
        grado = super().save(commit)
        if commit:
            self.sincronizar_grupos(grado)
        return grado

    def sincronizar_grupos(self, grado):
        """Deja activos exactamente los grupos elegidos: crea o reactiva los que faltan (con el plan del grado) y da de
        baja los que se quitaron."""
        elegidos = self.cleaned_data['grupos']
        for nombre in elegidos:
            grupo, creado = Grupo.objects.get_or_create(grado=grado, nombre=nombre)
            if creado or not grupo.activo:
                if not grupo.activo:
                    grupo.activo = True
                    grupo.save(update_fields=['activo'])
                extender_plan_al_grupo(grupo)
                self.grupos_agregados.append(grupo)
        for grupo in grado.grupos.filter(activo=True).exclude(nombre__in=elegidos):
            grupo.activo = False
            grupo.save(update_fields=['activo'])
            self.grupos_quitados.append(grupo)

    def clean(self):
        datos = super().clean()
        nivel, numero = datos.get('nivel'), datos.get('numero')
        if nivel and numero is not None:  # el 0 también debe validarse
            nombre = dict(Grado.NIVEL_CHOICES)[nivel]
            limite = LIMITE_GRADOS[nivel]
            if not 1 <= numero <= limite:
                self.add_error('numero', f'En {nombre.lower()} los grados van del 1.° al {limite}.°.')
            elif Grado.objects.filter(nivel=nivel, numero=numero).exclude(pk=self.instance.pk).exists():
                self.add_error('numero', f'Ya existe el grado {numero}° {nombre}.')

        # Sin equivalencia escrita se propone la habitual del grado (primaria 1–6, secundaria 7–9, preescolar K1–K3...)
        if 'equivalencia' not in self.errors:
            equivalencia = datos.get('equivalencia') or equivalencia_sugerida(nivel, numero)
            datos['equivalencia'] = equivalencia
            if equivalencia:
                otro = Grado.objects.filter(activo=True, equivalencia=equivalencia).exclude(pk=self.instance.pk).first()
                if otro:
                    texto = Grado(equivalencia=equivalencia).equivalencia_texto
                    self.add_error('equivalencia', f'La equivalencia {texto} ya la tiene {otro.nombre_de_nivel}: cada grado tiene la suya.')
        return datos

    def clean_equivalencia(self):
        valor = normalizar_equivalencia(self.cleaned_data.get('equivalencia'))
        if valor and not FORMATO_EQUIVALENCIA.match(valor):
            raise forms.ValidationError('Usa solo letras y números, sin símbolos (7, 10, K1).')
        return valor
