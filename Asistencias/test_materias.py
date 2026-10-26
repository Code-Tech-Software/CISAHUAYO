"""Asistencia por materia de la administración (Asistencias/views_materias.py): la matriz de cualquier materia del ciclo
actual, con la misma fuente de datos que la del docente, y la justificación de una falta con la foto de su comprobante
(Alumnos/asistencia_docente.py: justificar_falta)."""
import io
import shutil
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import NoReverseMatch, reverse
from PIL import Image

from Alumnos.asistencia_docente import version_de
from Alumnos.models import AsistenciaMateria, Justificacion, Periodo
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseAsistenciaTestCase,
    crear_alumno,
    crear_grado,
    crear_profesor,
    crear_rol,
    crear_usuario,
    inscribir_antes,
    lunes,
    materia_en_grado,
)
from Usuarios.models import Rol

CARPETA = tempfile.mkdtemp(prefix='cisahuayo-pruebas-')
URL = reverse('asistencias:materias')
URL_REPORTE = reverse('asistencias:materias_reporte')


def tearDownModule():
    shutil.rmtree(CARPETA, ignore_errors=True)


def dia(desplazamiento):
    """Un día relativo al lunes de prueba (que es «hoy»)."""
    return lunes() + timedelta(days=desplazamiento)


def foto(nombre='comprobante.jpg', formato='JPEG'):
    """Una fotografía de verdad (pequeña), como la que sube el navegador."""
    contenido = io.BytesIO()
    Image.new('RGB', (40, 30), (200, 180, 160)).save(contenido, formato)
    tipo = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'WEBP': 'image/webp', 'GIF': 'image/gif'}[formato]
    return SimpleUploadedFile(nombre, contenido.getvalue(), content_type=tipo)


class BaseMateriasTestCase(BaseAsistenciaTestCase):
    """Como la del docente: Marta da Matemáticas en 4.º A Primaria; Español y Ciencias no tienen profesor; también hay un
    5.º con Historia. El periodo abierto va del lunes de hace dos semanas al viernes de la próxima; «hoy» es el lunes de
    prueba a las 9:00. Inicia sesión quien administra."""

    hora = (9, 0)

    def setUp(self):
        super().setUp()
        self.docente = crear_usuario('marta', Rol.objects.get(grupo__name='Docente'))
        self.profesor = crear_profesor(usuario=self.docente)
        self.mat.profesor = self.profesor
        self.mat.save()
        self.g5 = crear_grado('PRIMARIA', 5)
        self.his = materia_en_grado('HIS', self.g5, self.ciclo)
        Periodo.objects.create(ciclo=self.ciclo, nivel='PRIMARIA', nombre='Primer bimestre', fecha_inicio=dia(-14), fecha_fin=dia(11))
        self.otra = inscribir_antes(crear_alumno(curp='PEMJ100720HMNRRNA5', nombre='Zoe'), self.ciclo, self.grado)

    def falta(self, fecha=None, inscripcion=None, asignacion=None, observaciones='No se presentó'):
        return AsistenciaMateria.objects.create(
            inscripcion=inscripcion or self.inscripcion, materia_grado=asignacion or self.mat, fecha=fecha or dia(-7),
            estado='FALTA', observaciones=observaciones,
        )

    def justificar(self, registro, motivo='Cita médica', comprobante=None, version=None, asignacion=None, **extra):
        datos = {
            'inscripcion': registro.inscripcion_id, 'fecha': registro.fecha.isoformat(), 'motivo': motivo,
            'version': version_de(registro) if version is None else version,
            'comprobante': foto() if comprobante is None else comprobante,
        }
        datos.update(extra)
        datos = {clave: valor for clave, valor in datos.items() if valor is not False}
        return self.client.post(reverse('asistencias:materias_justificar', args=[(asignacion or registro.materia_grado).pk]), datos)

    def celdas(self, url=URL, asignacion=None, inscripcion=None):
        """{fecha: celda} del estudiante en la matriz de todo el periodo."""
        respuesta = self.client.get(url, {'materia': (asignacion or self.mat).pk, 'desde': dia(-14).isoformat(), 'hasta': dia(11).isoformat()})
        datos = respuesta.context['datos']
        fila = next(f for f in datos['filas'] if f['inscripcion'] == (inscripcion or self.inscripcion))
        return {columna['fecha']: celda for columna, celda in zip(datos['columnas'], fila['celdas'])}


# ---------------------------------------------------------------------------
# La pantalla: todas las materias, la misma matriz y quién entra
# ---------------------------------------------------------------------------
@PRUEBAS
class PantallaTests(BaseMateriasTestCase):
    def test_reemplaza_al_pase_de_lista(self):
        respuesta = self.client.get(reverse('asistencias:inicio'))
        self.assertContains(respuesta, f'href="{URL}"')
        self.assertContains(respuesta, '>Asistencia por materia</a>')
        self.assertNotContains(respuesta, 'Pase de lista')
        for nombre in ('asistencias:clases', 'asistencias:clase'):
            with self.assertRaises(NoReverseMatch):
                reverse(nombre, args=[self.mat.pk] if nombre.endswith('clase') else [])

    def test_ve_todas_las_materias_del_ciclo_por_grupo(self):
        respuesta = self.client.get(URL)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context['asignaciones'], [self.cie, self.esp, self.mat, self.his])
        self.assertEqual(respuesta.context['grupos'], [self.mat.grupo, self.his.grupo])
        self.assertEqual(respuesta.context['asignacion'], self.cie)
        self.assertEqual(respuesta.context['materias_del_grupo'], [self.cie, self.esp, self.mat])
        self.assertContains(respuesta, 'data-elegir-grupo')
        self.assertContains(respuesta, 'Sin profesor asignado')

    def test_elige_el_grupo_y_luego_la_materia(self):
        respuesta = self.client.get(URL, {'grupo': self.his.grupo_id})
        self.assertEqual((respuesta.context['asignacion'], respuesta.context['materias_del_grupo']), (self.his, [self.his]))
        respuesta = self.client.get(URL, {'grupo': self.his.grupo_id, 'materia': self.mat.pk})   # manda la materia
        self.assertEqual(respuesta.context['asignacion'], self.mat)
        self.assertContains(respuesta, str(self.profesor))

    def test_una_materia_que_no_es_del_ciclo_actual_da_404(self):
        self.esp.activa = False
        self.esp.save()
        for valor in (self.esp.pk, 999999, 'x'):
            self.assertEqual(self.client.get(URL, {'materia': valor}).status_code, 404, valor)

    def test_un_docente_solo_ve_sus_materias_en_su_pantalla(self):
        self.client.force_login(self.docente)
        registro = self.falta()
        self.assertEqual(self.client.get(URL).status_code, 403)
        self.assertEqual(self.client.get(URL_REPORTE, {'materia': self.mat.pk}).status_code, 403)
        respuesta = self.client.post(reverse('asistencias:materias_guardar', args=[self.esp.pk]), {
            'inscripcion': self.inscripcion.pk, 'fecha': dia(0).isoformat(), 'estado': 'PRESENTE', 'version': '',
        })
        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(self.justificar(registro).status_code, 403)
        self.assertFalse(Justificacion.objects.exists())
        # …y en la suya sigue sin poder justificar
        respuesta = self.client.get(reverse('asistencias:docente'), {'desde': dia(-14).isoformat(), 'hasta': dia(11).isoformat()})
        self.assertNotContains(respuesta, 'data-justificable')
        self.assertNotContains(respuesta, 'data-justificar')
        self.assertFalse(any(c.justificable for f in respuesta.context['datos']['filas'] for c in f['celdas']))

    def test_pide_ver_la_asistencia_del_colegio_y_la_de_las_materias(self):
        self.con_permisos('view_asistenciamateria')
        self.assertEqual(self.client.get(URL).status_code, 403)
        self.con_permisos('view_asistenciageneral')
        self.assertEqual(self.client.get(URL).status_code, 403)
        self.con_permisos('view_asistenciageneral', 'view_asistenciamateria')
        respuesta = self.client.get(URL)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'tu rol no permite cambiarla')

    def test_misma_fuente_de_datos_que_el_docente(self):
        # El docente pone una falta…
        self.client.force_login(self.docente)
        respuesta = self.client.post(reverse('asistencias:docente_guardar', args=[self.mat.pk]), {
            'inscripcion': self.inscripcion.pk, 'fecha': dia(-7).isoformat(), 'estado': 'FALTA', 'version': '', 'observaciones': 'No vino',
        })
        self.assertTrue(respuesta.json()['ok'])
        # …la administración la ve y la cambia a retardo…
        self.client.force_login(self.admin)
        celda = self.celdas()[dia(-7)]
        self.assertEqual((celda.letra, celda.observaciones), ('F', 'No vino'))
        respuesta = self.client.post(reverse('asistencias:materias_guardar', args=[self.mat.pk]), {
            'inscripcion': self.inscripcion.pk, 'fecha': dia(-7).isoformat(), 'estado': 'RETARDO', 'version': celda.version,
            'observaciones': 'Llegó con su mamá',
        })
        self.assertEqual(respuesta.json()['letra'], 'R')
        # …y el docente ve el cambio: es el mismo registro
        self.client.force_login(self.docente)
        self.assertEqual(self.celdas(reverse('asistencias:docente'))[dia(-7)].letra, 'R')
        self.assertEqual(AsistenciaMateria.objects.count(), 1)

    def test_cambia_una_materia_que_no_es_de_ningun_docente(self):
        respuesta = self.client.post(reverse('asistencias:materias_guardar', args=[self.esp.pk]), {
            'inscripcion': self.inscripcion.pk, 'fecha': dia(0).isoformat(), 'estado': 'PRESENTE', 'version': '',
        })
        self.assertTrue(respuesta.json()['ok'])
        registro = AsistenciaMateria.objects.get(materia_grado=self.esp)
        self.assertEqual((registro.estado, registro.registrado_por), ('PRESENTE', self.admin))

    def test_el_reporte_de_cualquier_materia(self):
        self.falta(asignacion=self.esp)
        consulta = {'materia': self.esp.pk, 'desde': dia(-14).isoformat(), 'hasta': dia(11).isoformat()}
        respuesta = self.client.get(URL_REPORTE, consulta)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Sin profesor asignado')
        self.assertContains(respuesta, f'{URL}?materia={self.esp.pk}')   # «Volver» lleva a esta pantalla
        respuesta = self.client.get(URL_REPORTE, {**consulta, 'formato': 'csv'})
        self.assertIn('Profesor,Sin profesor asignado', respuesta.content.decode('utf-8-sig'))
        self.assertContains(self.client.get(URL, {'materia': self.esp.pk}), f'{URL_REPORTE}?materia={self.esp.pk}&amp;')
        self.assertEqual(self.client.get(URL_REPORTE).status_code, 404)


# ---------------------------------------------------------------------------
# Justificar una falta con la foto de su comprobante
# ---------------------------------------------------------------------------
@PRUEBAS
@override_settings(MEDIA_ROOT=CARPETA)
class JustificarTests(BaseMateriasTestCase):
    def test_una_falta_ofrece_justificarla(self):
        self.falta()
        AsistenciaMateria.objects.create(inscripcion=self.inscripcion, materia_grado=self.mat, fecha=dia(-6), estado='PRESENTE')
        celdas = self.celdas()
        self.assertTrue(celdas[dia(-7)].justificable)
        self.assertFalse(celdas[dia(-6)].justificable)
        self.assertFalse(celdas[dia(-5)].justificable)   # sin registro: no es falta
        respuesta = self.client.get(URL, {'materia': self.mat.pk, 'desde': dia(-7).isoformat(), 'hasta': dia(-5).isoformat()})
        self.assertContains(respuesta, 'data-justificable', count=1)
        self.assertContains(respuesta, 'data-justificar ')
        self.assertContains(respuesta, 'data-justificar-dialogo')
        self.assertContains(respuesta, 'js/asistencia-justificar.js')

    def test_justifica_la_falta_con_su_comprobante(self):
        registro = self.falta()
        respuesta = self.justificar(registro)
        self.assertEqual(respuesta.status_code, 200)
        datos = respuesta.json()
        self.assertTrue(datos['ok'])
        self.assertEqual((datos['letra'], datos['clase'], datos['editable'], datos['justificable']), ('J', 'justificada', False, False))
        self.assertIn('Falta justificada', datos['mensaje'])
        self.assertTrue(datos['justificacion']['de_la_falta'])
        self.assertTrue(datos['justificacion']['es_imagen'])
        self.assertIn('justificaciones/', datos['justificacion']['comprobante'])
        self.assertEqual(datos['justificacion']['registrada_por'], 'admin')

        justificacion = Justificacion.objects.get()
        self.assertEqual(justificacion.asistencia, registro)            # vinculada al registro de la falta
        self.assertEqual(list(justificacion.materias.all()), [self.mat])   # solo esa materia
        self.assertEqual((justificacion.inscripcion, justificacion.fecha), (self.inscripcion, registro.fecha))
        self.assertFalse(justificacion.justifica_general or justificacion.todas_materias)
        self.assertEqual((justificacion.registrada_por, justificacion.motivo), (self.admin, 'Cita médica'))
        self.assertIsNotNone(justificacion.creado)
        self.assertTrue(justificacion.documento.name.startswith('justificaciones/'))
        self.assertGreater(justificacion.documento.size, 0)
        registro.refresh_from_db()
        self.assertEqual(registro.estado, 'FALTA')   # sigue siendo falta: no se vuelve asistencia

    def test_la_j_se_ve_en_la_administracion_con_su_comprobante(self):
        self.justificar(self.falta())
        celda = self.celdas()[dia(-7)]
        self.assertEqual((celda.letra, celda.justificacion), ('J', Justificacion.objects.get()))
        self.assertIn('haz clic para ver su justificación', celda.nombre)
        respuesta = self.client.get(URL, {'materia': self.mat.pk, 'desde': dia(-7).isoformat(), 'hasta': dia(-7).isoformat()})
        self.assertContains(respuesta, 'data-justificacion="{&quot;motivo&quot;: &quot;Cita médica&quot;, &quot;registrada_por&quot;: &quot;admin&quot;')
        # El comprobante se entrega por la vista protegida, nunca con la dirección del archivo
        self.assertContains(respuesta, reverse('asistencias:comprobante', args=[Justificacion.objects.get().pk]))
        self.assertNotContains(respuesta, Justificacion.objects.get().documento.url)
        self.assertContains(respuesta, 'data-ver-justificacion')

    def test_la_j_se_ve_en_la_vista_del_docente_sin_el_comprobante(self):
        self.justificar(self.falta())
        self.client.force_login(self.docente)
        celda = self.celdas(reverse('asistencias:docente'))[dia(-7)]
        self.assertEqual((celda.letra, celda.editable, celda.justificable), ('J', False, False))
        respuesta = self.client.get(reverse('asistencias:docente'), {'desde': dia(-7).isoformat(), 'hasta': dia(-7).isoformat()})
        self.assertNotContains(respuesta, 'data-justificacion')
        self.assertNotContains(respuesta, Justificacion.objects.get().documento.url)
        # y no la puede cambiar
        respuesta = self.client.post(reverse('asistencias:docente_guardar', args=[self.mat.pk]), {
            'inscripcion': self.inscripcion.pk, 'fecha': dia(-7).isoformat(), 'estado': 'PRESENTE', 'version': celda.version,
        })
        self.assertEqual(respuesta.status_code, 400)

    def test_sin_foto_no_se_guarda(self):
        registro = self.falta()
        respuesta = self.justificar(registro, comprobante=False)
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('comprobante', respuesta.json()['errores'])
        self.assertIn('Sube la fotografía del comprobante', respuesta.json()['mensaje'])
        self.assertFalse(Justificacion.objects.exists())

    def test_solo_acepta_fotografias(self):
        registro = self.falta()
        malos = [
            SimpleUploadedFile('comprobante.pdf', b'%PDF-1.4 ' + b'0' * 300, content_type='application/pdf'),
            SimpleUploadedFile('comprobante.jpg', b'esto no es una imagen', content_type='image/jpeg'),
            foto('comprobante.gif', 'GIF'),
            foto('comprobante.txt'),   # una foto con otra extensión
        ]
        for archivo in malos:
            with self.subTest(archivo=archivo.name):
                respuesta = self.justificar(registro, comprobante=archivo)
                self.assertEqual(respuesta.status_code, 400)
                self.assertIn('comprobante', respuesta.json()['errores'])
        for formato, nombre in (('PNG', 'nota.png'), ('WEBP', 'nota.webp')):
            with self.subTest(formato=formato):
                self.assertEqual(self.justificar(registro, comprobante=foto(nombre, formato)).status_code, 200)
                Justificacion.objects.all().delete()
        self.assertFalse(Justificacion.objects.exists())

    def test_una_foto_muy_pesada_no_se_guarda(self):
        with patch('Asistencias.forms.TAMANO_MAXIMO_MB', 0.0001):
            respuesta = self.justificar(self.falta())
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('no debe pasar de', respuesta.json()['errores']['comprobante'][0])
        self.assertFalse(Justificacion.objects.exists())

    def test_pide_el_motivo(self):
        registro = self.falta()
        for motivo in ('', '  a  '):
            respuesta = self.justificar(registro, motivo=motivo)
            self.assertEqual(respuesta.status_code, 400)
            self.assertIn('motivo', respuesta.json()['errores'])
        self.assertFalse(Justificacion.objects.exists())

    def test_solo_se_justifica_una_falta_registrada(self):
        presente = AsistenciaMateria.objects.create(inscripcion=self.inscripcion, materia_grado=self.mat, fecha=dia(-6), estado='PRESENTE')
        respuesta = self.justificar(presente)
        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(respuesta.json()['letra'], 'P')   # lo que está guardado, para repintar la celda
        respuesta = self.client.post(reverse('asistencias:materias_justificar', args=[self.mat.pk]), {
            'inscripcion': self.inscripcion.pk, 'fecha': dia(-5).isoformat(), 'version': '', 'motivo': 'Cita', 'comprobante': foto(),
        })
        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(respuesta.json()['mensaje'], 'Solo se justifica una falta registrada.')
        self.assertFalse(Justificacion.objects.exists())

    def test_no_se_justifica_dos_veces(self):
        registro = self.falta()
        self.assertEqual(self.justificar(registro).status_code, 200)
        respuesta = self.justificar(registro)
        self.assertEqual(respuesta.status_code, 409)
        self.assertEqual((respuesta.json()['mensaje'], respuesta.json()['letra']), ('Esa falta ya está justificada.', 'J'))
        self.assertEqual(Justificacion.objects.count(), 1)

    def test_no_pisa_un_cambio_hecho_mientras_tanto(self):
        registro = self.falta()
        version_vieja = version_de(registro)
        # el docente la corrigió mientras se llenaba el formulario (el reloj de la prueba está detenido)
        AsistenciaMateria.objects.filter(pk=registro.pk).update(estado='PRESENTE', modificado=registro.modificado + timedelta(seconds=5))
        registro.refresh_from_db()
        respuesta = self.justificar(registro, version=version_vieja)
        self.assertEqual(respuesta.status_code, 409)
        self.assertEqual(respuesta.json()['letra'], 'P')
        self.assertFalse(Justificacion.objects.exists())

    def test_el_permiso_se_valida_en_el_servidor(self):
        registro = self.falta()
        self.con_permisos('view_asistenciageneral', 'view_asistenciamateria', 'change_asistenciamateria', 'view_justificacion')
        respuesta = self.client.get(URL, {'materia': self.mat.pk})
        self.assertNotContains(respuesta, 'data-justificable')
        self.assertNotContains(respuesta, 'data-justificar-dialogo')
        self.assertEqual(self.justificar(registro).status_code, 403)
        self.assertFalse(Justificacion.objects.exists())
        # Justificar es solo del administrador (y de prefectura): otro rol no lo recibe aunque se le pida
        rol = crear_rol('Control', {'Alumnos.view_asistenciageneral', 'Alumnos.view_asistenciamateria', 'Alumnos.add_justificacion'})
        self.client.force_login(crear_usuario('lupe', rol))
        self.assertNotContains(self.client.get(URL, {'materia': self.mat.pk}), 'data-justificable')
        self.assertEqual(self.justificar(registro).status_code, 403)
        # El administrador, sí
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(URL, {'materia': self.mat.pk}), 'data-justificable')
        self.assertEqual(self.justificar(registro).status_code, 200)
        self.assertEqual(Justificacion.objects.get().registrada_por, self.admin)

    def test_si_el_comprobante_no_se_puede_guardar_la_falta_no_cambia(self):
        registro = self.falta()
        with patch('django.core.files.storage.FileSystemStorage.save', side_effect=OSError('sin espacio')), \
                self.assertLogs('Alumnos.asistencia_docente', 'ERROR'):
            respuesta = self.justificar(registro)
        self.assertEqual(respuesta.status_code, 503)
        self.assertIn('No se pudo guardar el comprobante', respuesta.json()['mensaje'])
        self.assertEqual(respuesta.json()['letra'], 'F')
        self.assertFalse(Justificacion.objects.exists())
        self.assertTrue(self.celdas()[dia(-7)].justificable)

    def test_varias_faltas_del_mismo_dia_cada_una_con_su_comprobante(self):
        de_mat = self.falta()
        de_esp = self.falta(asignacion=self.esp)
        self.assertEqual(self.justificar(de_mat, comprobante=foto('uno.jpg')).status_code, 200)
        self.assertEqual(self.justificar(de_esp, comprobante=foto('dos.jpg')).status_code, 200)
        nombres = {j.asistencia.materia_grado.materia.clave: j.documento.name for j in Justificacion.objects.all()}
        self.assertIn('uno', nombres['MAT'])
        self.assertIn('dos', nombres['ESP'])
        self.assertEqual(self.celdas(asignacion=self.esp)[dia(-7)].letra, 'J')
        self.assertEqual(self.celdas(asignacion=self.cie)[dia(-7)].letra, '—')   # otra materia del día no cambia

    def test_luego_se_puede_justificar_el_dia_completo_desde_justificaciones(self):
        self.justificar(self.falta())
        respuesta = self.client.post(reverse('asistencias:justificacion_crear'), {
            'alumno': self.alumno.pk, 'fecha_desde': dia(-7).isoformat(), 'justifica_general': 'on', 'materias_modo': 'TODAS',
            'motivo': 'Enfermedad', 'next': '',
        })
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(Justificacion.objects.filter(activa=True).count(), 2)
        # La celda muestra la de la falta, la que trae su comprobante
        self.assertTrue(self.celdas()[dia(-7)].justificacion.asistencia_id)

    def test_su_comprobante_se_reemplaza_pero_no_se_quita_desde_justificaciones(self):
        self.justificar(self.falta())
        justificacion = Justificacion.objects.get()
        url = reverse('asistencias:justificacion_editar', args=[justificacion.pk])
        base = {'materias_modo': 'ALGUNAS', 'materias': [self.mat.pk], 'motivo': 'Cita médica'}
        respuesta = self.client.post(url, {**base, 'quitar_documento': 'on'})
        self.assertIn('quitar_documento', respuesta.context['form'].errors)
        respuesta = self.client.post(url, {**base, 'materias': [self.esp.pk]})
        self.assertIn('materias_modo', respuesta.context['form'].errors)
        justificacion.refresh_from_db()
        self.assertTrue(justificacion.documento)
        self.assertEqual(list(justificacion.materias.all()), [self.mat])
        self.assertEqual(self.client.post(url, {**base, 'documento': foto('nueva.jpg')}).status_code, 302)
        justificacion.refresh_from_db()
        self.assertIn('nueva', justificacion.documento.name)

    def test_anularla_devuelve_la_falta_y_se_puede_reactivar(self):
        self.justificar(self.falta())
        justificacion = Justificacion.objects.get()
        self.client.post(reverse('asistencias:justificacion_anular', args=[justificacion.pk]))
        self.assertTrue(self.celdas()[dia(-7)].justificable)
        # Una justificación del día (desde Justificaciones) no impide reactivar la de la falta
        Justificacion.objects.create(inscripcion=self.inscripcion, fecha=dia(-7), motivo='Día', justifica_general=True)
        self.client.post(reverse('asistencias:justificacion_reactivar', args=[justificacion.pk]))
        justificacion.refresh_from_db()
        self.assertTrue(justificacion.activa)

    def test_consultas_constantes(self):
        """Las J con su comprobante no hacen una consulta por celda."""
        def consultas():
            with CaptureQueriesContext(connection) as capturadas:
                self.client.get(URL, {'materia': self.mat.pk, 'desde': dia(-14).isoformat(), 'hasta': dia(11).isoformat()})
            return len(capturadas)

        self.justificar(self.falta(dia(-14)))
        una = consultas()
        for desplazamiento in (-13, -12, -11):
            self.justificar(self.falta(dia(desplazamiento)))
        self.justificar(self.falta(dia(-14), inscripcion=self.otra))
        self.assertEqual(consultas(), una)
