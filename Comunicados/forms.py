"""El formulario para crear (y corregir) un comunicado. El servidor valida todo aunque la pantalla ya lo cuide: título y
descripción obligatorios, fechas de publicación y de expiración, al menos un destinatario, la respuesta que se pide, el
evento y hasta cinco archivos del tipo y tamaño que el sistema ya acepta para las evidencias (fotos y PDF de hasta 5 MB;
se revisa el contenido, no solo la extensión). Que cada destinatario esté en el alcance de quien envía, que las fechas
tengan sentido entre sí y el contenido con formato lo revisa Comunicados/reglas.py."""
import json
from datetime import datetime, time

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from Conducta.forms import ACEPTA, TAMANO_MAXIMO_MB, validar_archivo

from .models import Comunicado, Destinatario

# Formatos que acepta el sistema para los archivos (los de las evidencias de Conducta)
FORMATOS = 'JPG, PNG, WEBP o PDF'
CLAVES = {'tutores': Destinatario.TUTOR, 'estudiantes': Destinatario.ESTUDIANTE, 'profesores': Destinatario.PROFESOR,
          'personal': Destinatario.PERSONAL}
FIN_DEL_DIA = time(23, 59)
HORAS = ['%H:%M', '%H:%M:%S']
# Dónde se muestra el error de cada campo en la pantalla (los que van juntos comparten lugar)
LUGAR_DEL_ERROR = {'expira_fecha': 'expira', 'expira_hora': 'expira', 'publicar_fecha': 'publicar', 'publicar_hora': 'publicar',
                   'evento_fecha': 'evento', 'evento_hora_inicio': 'evento', 'evento_hora_fin': 'evento', 'evento_lugar': 'evento',
                   'pregunta': 'respuesta', 'html': 'descripcion'}


def _texto(valor):
    return ' '.join((valor or '').split())


class ComunicadoForm(forms.Form):
    titulo = forms.CharField(label='Título', max_length=Comunicado.MAXIMO_TITULO, error_messages={
        'required': 'Escribe un título para el comunicado.',
        'max_length': f'El título puede tener hasta {Comunicado.MAXIMO_TITULO} caracteres.',
    })
    # Con el editor con formato llega también `html` (Comunicados/reglas.preparar_contenido saca de él el texto)
    descripcion = forms.CharField(label='Descripción', required=False, max_length=Comunicado.MAXIMO_DESCRIPCION, strip=True, error_messages={
        'max_length': f'La descripción puede tener hasta {Comunicado.MAXIMO_DESCRIPCION} caracteres.',
    })
    html = forms.CharField(required=False, strip=False, max_length=Comunicado.MAXIMO_HTML * 3, error_messages={
        'max_length': 'La descripción es demasiado larga.',
    })
    urgente = forms.BooleanField(required=False)
    expira_fecha = forms.DateField(required=False, input_formats=['%Y-%m-%d'], error_messages={'invalid': 'Elige una fecha válida.'})
    expira_hora = forms.TimeField(required=False, input_formats=HORAS, error_messages={'invalid': 'Elige una hora válida.'})
    clave_envio = forms.UUIDField(required=False, error_messages={'invalid': 'El formulario caducó. Vuelve a abrirlo.'})
    destinatarios = forms.CharField(required=False)
    categoria = forms.ChoiceField(required=False, choices=[('', 'Sin categoría'), *Comunicado.CATEGORIAS],
                                  error_messages={'invalid_choice': 'Elige una categoría de la lista.'})
    fijado = forms.BooleanField(required=False)
    publicar_fecha = forms.DateField(required=False, input_formats=['%Y-%m-%d'], error_messages={'invalid': 'Elige una fecha válida.'})
    publicar_hora = forms.TimeField(required=False, input_formats=HORAS, error_messages={'invalid': 'Elige una hora válida.'})
    respuesta = forms.ChoiceField(required=False, choices=Comunicado.RESPUESTAS, error_messages={'invalid_choice': 'Elige qué respuesta se pide.'})
    pregunta = forms.CharField(required=False, max_length=200, error_messages={'max_length': 'La pregunta puede tener hasta 200 caracteres.'})
    evento_fecha = forms.DateField(required=False, input_formats=['%Y-%m-%d'], error_messages={'invalid': 'Elige una fecha válida.'})
    evento_hora_inicio = forms.TimeField(required=False, input_formats=HORAS, error_messages={'invalid': 'Elige una hora válida.'})
    evento_hora_fin = forms.TimeField(required=False, input_formats=HORAS, error_messages={'invalid': 'Elige una hora válida.'})
    evento_lugar = forms.CharField(required=False, max_length=150, error_messages={'max_length': 'El lugar puede tener hasta 150 caracteres.'})
    # Los archivos llegan en request.FILES (se pasan en `archivos`); el campo solo sirve para colgarles sus errores
    archivos = forms.Field(required=False)

    def __init__(self, *args, archivos=(), para_editar=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.archivos = list(archivos)
        self.archivos_validos = []
        self.para_editar = para_editar

    def clean_titulo(self):
        titulo = _texto(self.cleaned_data['titulo'])
        if not titulo:
            raise ValidationError('Escribe un título para el comunicado.')
        return titulo

    def clean_clave_envio(self):
        clave = self.cleaned_data.get('clave_envio')
        if clave is None and not self.para_editar:
            raise ValidationError('El formulario caducó. Vuelve a abrirlo.')
        return clave

    def clean_destinatarios(self):
        """{tipo: {ids}} de lo que trae el campo ({"tutores": [3, 4], "estudiantes": [...], "profesores": [...], "personal": []})."""
        if self.para_editar:
            return {}
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
        if not (datos.get('descripcion') or '').strip() and not (datos.get('html') or '').strip() and 'descripcion' not in self.errors:
            self.add_error('descripcion', 'Escribe la descripción del comunicado.')

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

        # Programar: fecha y hora juntas (sin ninguna, se publica al enviarlo)
        fecha, hora = datos.get('publicar_fecha'), datos.get('publicar_hora')
        datos['publicar_en'] = None
        if (fecha or hora) and not (fecha and hora) and not ({'publicar_fecha', 'publicar_hora'} & set(self.errors)):
            self.add_error('publicar_fecha', 'Elige la fecha y la hora de publicación (o bórralas para enviarlo ya).')
        elif fecha and hora:
            datos['publicar_en'] = timezone.make_aware(datetime.combine(fecha, hora))

        datos['opciones'] = [texto for texto in self.data.getlist('opciones') if texto.strip()] if hasattr(self.data, 'getlist') else []
        datos['evento'] = {'fecha': datos.get('evento_fecha'), 'hora_inicio': datos.get('evento_hora_inicio'),
                           'hora_fin': datos.get('evento_hora_fin'), 'lugar': datos.get('evento_lugar') or ''}

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
        """{campo: [mensajes]} para la pantalla: los de las fechas y del evento, juntos en su lugar."""
        errores = {}
        for campo, mensajes in self.errors.items():
            errores.setdefault(LUGAR_DEL_ERROR.get(campo, campo), []).extend(mensajes)
        return errores


AYUDA_DE_ARCHIVOS = f'Hasta {Comunicado.MAXIMO_ADJUNTOS} archivos {FORMATOS}, de {TAMANO_MAXIMO_MB} MB como máximo cada uno.'
__all__ = ['ACEPTA', 'AYUDA_DE_ARCHIVOS', 'ComunicadoForm', 'TAMANO_MAXIMO_MB']
