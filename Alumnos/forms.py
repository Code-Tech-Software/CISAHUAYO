from django import forms

class AsistenciaRapidaForm(forms.Form):
    referencia = forms.CharField(
        max_length=20,
        label='Referencia del alumno',
        widget=forms.TextInput(
            attrs={
                'placeholder': 'Ingrese o escanee la referencia',
                'autofocus': True,
                'autocomplete': 'off',
            }
        )
    )