"""Mejoras de Profesores del 2026-10-20: la carga contra su tope en la lista, las señales junto al nombre, el orden desde
los encabezados y el filtro «Rebasa su tope»; la equivalencia del grado en el perfil, el horario y el CSV; la foto; lo
pendiente con las familias al darlo de baja y las materias que tenía, ofrecidas al reactivarlo."""
import csv
import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from Alumnos.models import Grupo, MateriaGrado, Profesor
from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase, ciclo_actual_de_prueba, crear_grado, crear_profesor, crear_tutor, crear_usuario, hoy

from . import tabla
from .tests import asignar, bloque, crear_materia, datos_profesor

LISTA = reverse('profesores:lista')
CARPETA = tempfile.mkdtemp(prefix='cisahuayo-profesores-')


class Base(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)
        self.ciclo = ciclo_actual_de_prueba()
        self.secundaria = crear_grado('SECUNDARIA', 1)   # su equivalencia habitual: 7.º
        self.mat, self.esp = crear_materia('MAT', 'Matemáticas'), crear_materia('ESP', 'Español')
        # Marta: 3 h de 4 h (75 %); Beto: 2 h sin tope; Ceci: 5 h de 4 h (rebasa)
        self.marta = crear_profesor(nombre='Marta', apellido_paterno='Rangel', horas_maximas=4, niveles=['SECUNDARIA'])
        self.beto = crear_profesor(nombre='Beto', apellido_paterno='Aguilar', niveles=['PRIMARIA', 'SECUNDARIA'])
        self.ceci = crear_profesor(nombre='Ceci', apellido_paterno='Zamora', horas_maximas=4, niveles=['PREESCOLAR', 'SECUNDARIA'])
        for profesor, materia, horas in ((self.marta, self.mat, 3), (self.beto, self.esp, 2), (self.ceci, self.mat, 5)):
            asignacion = asignar(materia, crear_grado('SECUNDARIA', 2 if profesor == self.beto else 3), self.ciclo, profesor=profesor) \
                if profesor != self.marta else asignar(materia, self.secundaria, self.ciclo, profesor=profesor)
            for dia in range(horas):
                bloque(asignacion, dia, (8, 0), (9, 0))

    def nombres(self, **parametros):
        return [p.nombre for p in self.client.get(LISTA, parametros).context['pagina']]


# ---------------------------------------------------------------------------
# La lista
# ---------------------------------------------------------------------------
@PRUEBAS
class CargaTests(Base):
    def test_la_carga_contra_su_tope(self):
        filas = {p.nombre: p.carga for p in self.client.get(LISTA).context['pagina']}
        self.assertEqual((filas['Marta']['texto'], filas['Marta']['tope'], filas['Marta']['aviso']), ('3 h', '4 h', ''))
        self.assertEqual((filas['Ceci']['estado'], filas['Ceci']['aviso'], filas['Ceci']['porcentaje']), ('rebasa', 'Rebasa su tope', 125))
        self.assertEqual((filas['Beto']['tope'], filas['Beto']['estado']), (None, 'sin_tope'))
        respuesta = self.client.get(LISTA)
        self.assertContains(respuesta, 'Rebasa su tope')
        self.assertContains(respuesta, '<span class="text-muted">de 4 h</span>', html=True)

    def test_cerca_y_en_su_tope(self):
        self.assertEqual(tabla.carga(self.marta, 204)['aviso'], 'Cerca de su tope')   # 85 % de 4 h
        self.assertEqual(tabla.carga(self.marta, 240)['aviso'], 'En su tope')
        self.assertEqual(tabla.carga(self.marta, 120)['aviso'], '')

    def test_filtro_rebasa_su_tope(self):
        self.assertEqual(self.nombres(situacion='rebasa'), ['Ceci'])
        contenido = self.client.get(reverse('profesores:exportar'), {'situacion': 'rebasa'}).content.decode('utf-8').lstrip('﻿')
        self.assertEqual([fila[0] for fila in list(csv.reader(io.StringIO(contenido)))[1:]], ['Ceci'])

    def test_ordena_desde_los_encabezados(self):
        self.assertEqual(self.nombres(), ['Beto', 'Marta', 'Ceci'])                 # por apellido
        self.assertEqual(self.nombres(orden='-carga'), ['Ceci', 'Marta', 'Beto'])
        self.assertEqual(self.nombres(orden='carga'), ['Beto', 'Marta', 'Ceci'])
        self.assertEqual(self.nombres(orden='niveles'), ['Ceci', 'Beto', 'Marta'])  # preescolar, primaria, secundaria
        self.assertEqual(self.nombres(orden='-niveles'), ['Marta', 'Beto', 'Ceci'])
        asignar(self.esp, self.secundaria, self.ciclo, profesor=self.marta)
        self.assertEqual(self.nombres(orden='-materias'), ['Marta', 'Beto', 'Ceci'])   # a igual número, por apellido
        html = self.client.get(LISTA, {'orden': '-carga'}).content.decode()
        self.assertIn('aria-sort="descending"', html)
        self.assertIn('href="?orden=carga"', html)                                  # otra vez: al revés

    def test_el_csv_lleva_las_horas_por_semana(self):
        contenido = self.client.get(reverse('profesores:exportar')).content.decode('utf-8').lstrip('﻿')
        filas = list(csv.reader(io.StringIO(contenido)))
        columna = filas[0].index('Horas por semana en el ciclo actual')
        self.assertEqual({fila[0]: fila[columna] for fila in filas[1:]}, {'Beto': '2 h', 'Marta': '3 h', 'Ceci': '5 h'})


@PRUEBAS
class SenalesTests(Base):
    def senales(self):
        return {p.nombre: [s['clave'] for s in p.senales] for p in self.client.get(LISTA).context['pagina']}

    def test_solo_las_que_aplican(self):
        from Alumnos.docentes import habilitar
        habilitar(self.marta, [self.mat])
        self.marta.usuario = crear_usuario('marta')
        self.marta.save()
        self.beto.usuario = crear_usuario('beto', is_active=False)
        self.beto.save()
        self.ceci.establecer_niveles([])
        senales = self.senales()
        self.assertEqual(senales['Marta'], [])                                       # con cuenta, niveles y habilitada
        self.assertEqual(senales['Beto'], ['cuenta_inactiva', 'sin_habilitar'])
        self.assertEqual(senales['Ceci'], ['sin_cuenta', 'sin_niveles', 'sin_habilitar'])
        self.assertContains(self.client.get(LISTA), 'Imparte 1 materia sin estar habilitado para ella')

    def test_las_bajas_no_llevan_senales(self):
        self.beto.estatus = 'INACTIVO'
        self.beto.save()
        pagina = self.client.get(LISTA, {'estatus': 'INACTIVO'}).context['pagina']
        self.assertEqual([p.senales for p in pagina], [[]])


# ---------------------------------------------------------------------------
# Equivalencia del grado
# ---------------------------------------------------------------------------
@PRUEBAS
class EquivalenciaTests(Base):
    def test_en_el_perfil_el_horario_y_el_csv(self):
        grupo = Grupo.principal_de(self.secundaria)
        perfil = self.client.get(reverse('profesores:detalle', args=[self.marta.pk]))
        self.assertContains(perfil, f'data-tooltip="{grupo.nombre_de_nivel}">7.º {grupo.nombre}</a>')
        self.assertContains(perfil, f'<span class="slot__code" title="{grupo.nombre_de_nivel}">7.º {grupo.nombre}</span>', html=True)
        hoja = self.client.get(reverse('profesores:horario_imprimir', args=[self.marta.pk]))
        self.assertContains(hoja, f'<td>7.º {grupo.nombre}</td>', html=True)
        contenido = self.client.get(reverse('profesores:exportar')).content.decode('utf-8').lstrip('﻿')
        self.assertIn(f'Matemáticas (7.º {grupo.nombre})', contenido)

    def test_al_asignar_materias(self):
        libre = asignar(self.esp, self.secundaria, self.ciclo)
        perfil = self.client.get(reverse('profesores:detalle', args=[self.marta.pk]))
        self.assertContains(perfil, f'value="{libre.pk}"')
        self.assertContains(perfil, f'7.º {libre.grupo.nombre} <span class="text-muted">· {libre.grupo.nombre_de_nivel}</span>', html=True)


# ---------------------------------------------------------------------------
# Baja y reactivación
# ---------------------------------------------------------------------------
@PRUEBAS
class BajaYReactivacionTests(Base):
    def test_al_darlo_de_baja_avisa_lo_pendiente_con_las_familias(self):
        from Reuniones.models import Acuerdo, MotivoReunion, ParticipanteReunion, Reunion
        self.marta.usuario = crear_usuario('marta')
        self.marta.save()
        reunion = Reunion.objects.create(tutor=crear_tutor(), telefono='3531112233', area=Reunion.DOCENTE,
                                         motivo=MotivoReunion.objects.first(), descripcion='Calificaciones')
        ParticipanteReunion.objects.create(reunion=reunion, usuario=self.marta.usuario, papel=ParticipanteReunion.DOCENTE)
        Acuerdo.objects.create(reunion=reunion, descripcion='Enviar tareas', responsable=self.marta.usuario, fecha_limite=hoy())
        aviso = 'Tiene 1 reunión con familias pendiente y 1 acuerdo a su cargo sin cumplir'
        self.assertContains(self.client.get(LISTA), aviso)
        self.assertContains(self.client.get(reverse('profesores:detalle', args=[self.marta.pk])), aviso)
        # cerrada la reunión y cumplido el acuerdo, ya no
        Reunion.objects.filter(pk=reunion.pk).update(estado=Reunion.CANCELADA)
        Acuerdo.objects.update(estado=Acuerdo.CUMPLIDO)
        self.assertNotContains(self.client.get(LISTA), 'con familias pendiente')

    def test_al_reactivarlo_se_le_ofrecen_las_materias_que_tenia(self):
        self.client.post(reverse('profesores:baja', args=[self.marta.pk]), {'quitar_del_ciclo': 'on'})
        self.marta.refresh_from_db()
        tenia = list(MateriaGrado.objects.filter(materia=self.mat, grado=self.secundaria).values_list('pk', flat=True))
        self.assertEqual(self.marta.materias_al_darse_de_baja, tenia)
        respuesta = self.client.post(reverse('profesores:reactivar', args=[self.marta.pk]), follow=True)
        self.assertContains(respuesta, 'puedes devolvérsela aquí')
        self.assertEqual([m.pk for m in respuesta.context['materias_que_tenia']], tenia)
        # se las devuelve con el mismo formulario de asignar
        self.client.post(reverse('profesores:asignar'), {'profesor': self.marta.pk, 'asignacion': tenia,
                                                          'next': reverse('profesores:detalle', args=[self.marta.pk])})
        self.assertEqual(MateriaGrado.objects.get(pk=tenia[0]).profesor, self.marta)
        self.assertEqual(self.client.get(reverse('profesores:detalle', args=[self.marta.pk])).context['materias_que_tenia'], [])

    def test_no_se_ofrecen_si_ya_tienen_otro_profesor_o_se_descartan(self):
        self.client.post(reverse('profesores:baja', args=[self.marta.pk]), {'quitar_del_ciclo': 'on'})
        MateriaGrado.objects.filter(materia=self.mat, grado=self.secundaria).update(profesor=self.beto)
        respuesta = self.client.post(reverse('profesores:reactivar', args=[self.marta.pk]), follow=True)
        self.assertRedirects(respuesta, LISTA)
        self.assertContains(respuesta, 'Asígnale de nuevo las materias que imparte')
        # descartar: ya no se le ofrecen
        MateriaGrado.objects.filter(materia=self.mat, grado=self.secundaria).update(profesor=None)
        self.assertEqual(len(self.client.get(reverse('profesores:detalle', args=[self.marta.pk])).context['materias_que_tenia']), 1)
        self.client.post(reverse('profesores:descartar_materias', args=[self.marta.pk]))
        self.assertEqual(self.client.get(reverse('profesores:detalle', args=[self.marta.pk])).context['materias_que_tenia'], [])

    def test_baja_sin_quitar_materias_no_guarda_nada_que_ofrecer(self):
        self.client.post(reverse('profesores:baja', args=[self.marta.pk]))
        self.marta.refresh_from_db()
        self.assertEqual(self.marta.materias_al_darse_de_baja, [])


# ---------------------------------------------------------------------------
# Foto y pestaña de llegada
# ---------------------------------------------------------------------------
@PRUEBAS
@override_settings(MEDIA_ROOT=CARPETA)
class FotoTests(Base):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(CARPETA, ignore_errors=True)

    def foto(self, nombre='marta.png'):
        from PIL import Image
        contenido = io.BytesIO()
        Image.new('RGB', (8, 8), (162, 42, 71)).save(contenido, 'PNG')
        return SimpleUploadedFile(nombre, contenido.getvalue(), content_type='image/png')

    def test_sube_cambia_y_quita_la_foto(self):
        url = reverse('profesores:editar', args=[self.marta.pk])
        datos = datos_profesor(nombre='Marta', apellido_paterno='Rangel', niveles=['SECUNDARIA'], horas_maximas='4')
        self.client.post(url, {**datos, 'fotografia': self.foto()})
        self.marta.refresh_from_db()
        self.assertTrue(self.marta.fotografia.name.startswith('profesores/'))
        self.assertContains(self.client.get(LISTA), f'src="{self.marta.fotografia.url}"')   # su avatar en la lista
        self.assertContains(self.client.get(reverse('profesores:detalle', args=[self.marta.pk])), 'class="avatar__img"')
        self.client.post(url, {**datos, 'quitar_fotografia': 'on'})
        self.marta.refresh_from_db()
        self.assertFalse(self.marta.fotografia)

    def test_solo_imagenes_de_hasta_5_mb(self):
        url = reverse('profesores:editar', args=[self.marta.pk])
        datos = datos_profesor(nombre='Marta', apellido_paterno='Rangel', niveles=['SECUNDARIA'])
        respuesta = self.client.post(url, {**datos, 'fotografia': SimpleUploadedFile('x.png', b'no soy imagen', content_type='image/png')})
        self.assertTrue(respuesta.context['form'].errors.get('fotografia'))
        self.assertFalse(Profesor.objects.get(pk=self.marta.pk).fotografia)

    def test_desde_asignaciones_abre_en_materias(self):
        destino = f'{self.marta.get_absolute_url()}?ciclo={self.ciclo.pk}#materias'
        self.assertContains(self.client.get(reverse('asignaciones:tablero'), {'ciclo': self.ciclo.pk}), destino)
        self.assertContains(self.client.get(reverse('asignaciones:carga'), {'ciclo': self.ciclo.pk}), destino)
