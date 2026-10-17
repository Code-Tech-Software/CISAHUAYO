"""El formulario para crear un comunicado. El servidor valida todo aunque la pantalla ya lo cuide: título y descripción
obligatorios, expiración posterior al envío, al menos un destinatario y hasta cinco archivos del tipo y tamaño que el
sistema ya acepta para las evidencias (fotos y PDF de hasta 5 MB; se revisa el contenido, no solo la extensión). Que
cada destinatario esté en el alcance de quien envía lo revisa Comunicados/reglas.py."""
import json
from datetime import datetime, time

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from Conducta.forms import ACEPTA, TAMANO_MAXIMO_MB, validar_archivo

from .models import Comunicado, Destinatario

# Formatos que acepta el sistema para los archivos (los de las evidencias de Conducta)
FORMATOS = 'JPG, PNG, WEBP o PDF'
CLAVES = {'tutores': Destinatario.TUTOR, 'estudiantes': Destinatario.ESTUDIANTE, 'profesores': Destinatario.PROFESOR}
FIN_DEL_DIA = time(23, 59)


def _texto(valor):
    return ' '.join((valor or '').split())


class ComunicadoForm(forms.Form):
    titulo = forms.CharField(label='Título', max_length=Comunicado.MAXIMO_TITULO, error_messages={
        'required': 'Escribe un título para el comunicado.',
        'max_length': f'El título puede tener hasta {Comunicado.MAXIMO_TITULO} caracteres.',
    })
    descripcion = forms.CharField(label='Descripción', max_length=Comunicado.MAXIMO_DESCRIPCION, strip=True, error_messages={
        'required': 'Escribe la descripción del comunicado.',
        'max_length': f'La descripción puede tener hasta {Comunicado.MAXIMO_DESCRIPCION} caracteres.',
    })
    urgente = forms.BooleanField(required=False)
    expira_fecha = forms.DateField(required=False, input_formats=['%Y-%m-%d'], error_messages={'invalid': 'Elige una fecha válida.'})
    expira_hora = forms.TimeField(required=False, input_formats=['%H:%M', '%H:%M:%S'], error_messages={'invalid': 'Elige una hora válida.'})
    clave_envio = forms.UUIDField(error_messages={
        'required': 'El formulario caducó. Vuelve a abrirlo.', 'invalid': 'El formulario caducó. Vuelve a abrirlo.'})
    destinatarios = forms.CharField(required=False)
    # Los archivos llegan en request.FILES (se pasan en `archivos`); el campo solo sirve para colgarles sus errores
    archivos = forms.Field(required=False)

    def __init__(self, *args, archivos=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.archivos = list(archivos)
        self.archivos_validos = []

    def clean_titulo(self):
        titulo = _texto(self.cleaned_data['titulo'])
        if not titulo:
            raise ValidationError('Escribe un título para el comunicado.')
        return titulo

    def clean_descripcion(self):
        descripcion = (self.cleaned_data['descripcion'] or '').strip()
        if not descripcion:
            raise ValidationError('Escribe la descripción del comunicado.')
        return descripcion

    def clean_destinatarios(self):
        """{tipo: {ids}} de lo que trae el campo ({"tutores": [3, 4], "estudiantes": [...], "profesores": [...]})."""
        texto = self.cleaned_data.get('destinatarios') or ''
        try:
            datos = json.loads(texto) if texto else {}
        except ValueError:
            raise ValidationError('No se entendió la selección de destinatarios. Vuelve a elegirlos.') from None
        if not isinstance(datos, dict):
            raise ValidationError('No se entendió la selección de destinatarios. Vuelve a elegirlos.')
        seleccion = {}
        for clave, tipo in CLAVES.items():
            valores = datos.get(clave) or []
            if not isinstance(valores, list) or not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in valores):
                raise ValidationError('No se entendió la selección de destinatarios. Vuelve a elegirlos.')
            seleccion[tipo] = set(valores)
        if not any(seleccion.values()):
            raise ValidationError('Elige al menos un destinatario.')
        return seleccion

    def clean(self):
        datos = super().clean()
        fecha, hora = datos.get('expira_fecha'), datos.get('expira_hora')
        datos['expira'] = None
        if hora and not fecha and 'expira_fecha' not in self.errors:
            self.add_error('expira_fecha', 'Elige también la fecha de expiración (o borra la hora).')
        elif fecha:
            expira = timezone.make_aware(datetime.combine(fecha, hora or FIN_DEL_DIA))
            if expira <= timezone.now():
                self.add_error('expira_fecha', 'La fecha de expiración debe ser posterior al momento del envío.')
            else:
                datos['expira'] = expira

        if len(self.archivos) > Comunicado.MAXIMO_ADJUNTOS:
            self.add_error('archivos', f'Adjunta como máximo {Comunicado.MAXIMO_ADJUNTOS} archivos.')
        else:
            for archivo in self.archivos:
                try:
                    self.archivos_validos.append((archivo, validar_archivo(archivo)))
                except ValidationError as error:
                    self.add_error('archivos', error)
        return datos

    def errores(self):
        """{campo: [mensajes]} para la pantalla; la expiración, en «expira»."""
        errores = {}
        for campo, mensajes in self.errors.items():
            destino = 'expira' if campo in ('expira_fecha', 'expira_hora') else campo
            errores.setdefault(destino, []).extend(mensajes)
        return errores


AYUDA_DE_ARCHIVOS = f'Hasta {Comunicado.MAXIMO_ADJUNTOS} archivos {FORMATOS}, de {TAMANO_MAXIMO_MB} MB como máximo cada uno.'
__all__ = ['ACEPTA', 'AYUDA_DE_ARCHIVOS', 'ComunicadoForm', 'TAMANO_MAXIMO_MB']
