"""Ayudantes de las pruebas del módulo de conducta: un colegio con primaria y secundaria, sus catálogos y un estudiante
en cada nivel."""
import io
import shutil
import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from Alumnos.models import Periodo
from CISAHUAYO.pruebas import BaseTestCase, ciclo_actual_de_prueba, crear_alumno, crear_grado, hoy, inscribir_antes

from .models import (
    INCIDENCIA,
    MODERADA,
    POSITIVA,
    CategoriaConducta,
    MedidaDisciplinaria,
    MotivoConducta,
    MotivoSuspension,
    RegistroConducta,
)

CARPETA = tempfile.mkdtemp(prefix='cisahuayo-conducta-')


def borrar_carpeta():
    shutil.rmtree(CARPETA, ignore_errors=True)


def foto(nombre='evidencia.jpg'):
    contenido = io.BytesIO()
    Image.new('RGB', (30, 20), (120, 140, 160)).save(contenido, 'JPEG')
    return SimpleUploadedFile(nombre, contenido.getvalue(), content_type='image/jpeg')


def pdf(nombre='acta.pdf'):
    return SimpleUploadedFile(nombre, b'%PDF-1.4 contenido de prueba', content_type='application/pdf')


class BaseConductaTestCase(BaseTestCase):
    """Primaria (4°) con Ana y secundaria (1°) con Zoe; catálogos de primaria completos y una categoría de secundaria.
    Inicia sesión el administrador."""

    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.primaria = crear_grado('PRIMARIA', 4)
        self.secundaria = crear_grado('SECUNDARIA', 1)
        self.alumno = crear_alumno(nombre='Ana', curp='CONDUCTA00000000A1')
        self.inscripcion = inscribir_antes(self.alumno, self.ciclo, self.primaria)
        self.otro = crear_alumno(nombre='Zoe', curp='CONDUCTA00000000B2')
        self.inscripcion_otro = inscribir_antes(self.otro, self.ciclo, self.secundaria)
        self.periodo = Periodo.objects.create(
            ciclo=self.ciclo, nivel='PRIMARIA', nombre='Primer bimestre', fecha_inicio=hoy() - timedelta(days=30), fecha_fin=hoy() + timedelta(days=30),
        )

        self.convivencia = CategoriaConducta.objects.create(nivel='PRIMARIA', nombre='Convivencia', tipo=INCIDENCIA)
        self.reconocimiento = CategoriaConducta.objects.create(nivel='PRIMARIA', nombre='Reconocimientos', tipo=POSITIVA)
        self.agresion = MotivoConducta.objects.create(categoria=self.convivencia, nombre='Agresión verbal', gravedad=MODERADA)
        self.empujon = MotivoConducta.objects.create(categoria=self.convivencia, nombre='Empujones')
        self.ayuda = MotivoConducta.objects.create(categoria=self.reconocimiento, nombre='Ayuda a compañeros')
        self.amonestacion = MedidaDisciplinaria.objects.create(nivel='PRIMARIA', nombre='Amonestación verbal', descripcion='Hablada')
        self.compromiso = MedidaDisciplinaria.objects.create(nivel='PRIMARIA', nombre='Compromiso escrito', descripcion='Firmado', requiere_seguimiento=True)
        self.suspender = MedidaDisciplinaria.objects.create(nivel='PRIMARIA', nombre='Suspensión', descripcion='Temporal', implica_suspension=True)
        self.motivo_suspension = MotivoSuspension.objects.create(nivel='PRIMARIA', nombre='Agresión grave', descripcion='Física')

        self.convivencia_sec = CategoriaConducta.objects.create(nivel='SECUNDARIA', nombre='Convivencia', tipo=INCIDENCIA)
        self.agresion_sec = MotivoConducta.objects.create(categoria=self.convivencia_sec, nombre='Agresión verbal')
        self.amonestacion_sec = MedidaDisciplinaria.objects.create(nivel='SECUNDARIA', nombre='Amonestación verbal', descripcion='Hablada')

    def datos(self, **cambios):
        datos = {
            'alumno': self.alumno.pk, 'fecha': hoy().isoformat(), 'hora': '10:30', 'lugar': 'Patio',
            'tipo': INCIDENCIA, 'categoria': self.convivencia.pk, 'motivo': self.agresion.pk, 'gravedad': '',
            'descripcion': 'Le gritó a un compañero durante el recreo.', 'observaciones_medidas': '',
            'responsable': '', 'fecha_revision': '', 'estado': RegistroConducta.PENDIENTE, 'acuerdos': '', 'observaciones_cierre': '',
            'motivo_cambio': 'Corrección de los datos.',   # solo se usa al corregir
        }
        datos.update(cambios)
        return {clave: valor for clave, valor in datos.items() if valor is not None}

    def registrar(self, **cambios):
        return self.client.post(reverse('conducta:crear'), self.datos(**cambios))

    def ultimo(self):
        return RegistroConducta.objects.order_by('-pk').first()
