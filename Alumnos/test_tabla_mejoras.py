"""Mejoras de la tabla de estudiantes (pedido del 2026-10-28): el menú «Columnas» (guardado por usuario y con las columnas
de asistencia, calificaciones y conducta solo con su permiso), las columnas nuevas (asistencia del ciclo, promedio de
actas cerradas, casos de conducta abiertos, portal y tarjeta), los filtros nuevos, la búsqueda por teléfono del tutor,
los contadores por nivel y grupo, el Excel, la lista para imprimir, las acciones en lote, la vista rápida y el historial
de cambios del expediente."""
import io
import zipfile
from datetime import date, timedelta

from django.contrib.admin.models import LogEntry
from django.urls import reverse
from django.utils import timezone

from Calificaciones.models import ActaCalificaciones
from CISAHUAYO.pruebas import (
    PRUEBAS, BaseTestCase, ciclo_actual_de_prueba, crear_alumno, crear_grado, crear_grupo, crear_rol, crear_tutor, crear_usuario,
    grupo_de, inscribir_antes, materia_en_grado, vincular,
)
from Conducta.pruebas import BaseConductaTestCase

from . import columnas
from .models import Alumno, AsistenciaGeneral, Inscripcion, TutorAlumno
from .tests import CURP_TUTOR, EditarTests

LISTA = reverse('alumnos:lista')
XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
CURP_VALIDA = 'GOMA150505HMNRRN09'


def hoja_de_excel(respuesta):
    return zipfile.ZipFile(io.BytesIO(respuesta.content)).read('xl/worksheets/sheet1.xml').decode()


# ---------------------------------------------------------------------------
# Columnas
# ---------------------------------------------------------------------------
@PRUEBAS
class ColumnasTests(BaseConductaTestCase):
    """Ana (4.º de primaria) y Zoe (1.º de secundaria), del BaseConductaTestCase; entra el administrador."""

    def test_las_de_siempre_y_elegir_otras_queda_guardado(self):
        self.assertEqual(columnas.elegidas(self.admin), ['grado', 'asistencia_hoy', 'tutor', 'edad', 'estatus'])
        self.client.post(reverse('alumnos:columnas'), {'columnas': ['grado', 'asistencia_ciclo', 'promedio', 'conducta', 'portal', 'tarjeta', 'nada'],
                                                       'next': f'{LISTA}?nivel=PRIMARIA'})
        self.assertEqual(columnas.elegidas(self.admin), ['grado', 'asistencia_ciclo', 'promedio', 'conducta', 'portal', 'tarjeta'])
        respuesta = self.client.get(LISTA)
        self.assertEqual(respuesta.context['visibles'], ['grado', 'asistencia_ciclo', 'promedio', 'conducta', 'portal', 'tarjeta'])
        for titulo in ('Asistencia del ciclo', 'Promedio', 'Conducta', 'Portal', 'Tarjeta'):
            self.assertContains(respuesta, f'scope="col">{titulo}</th>')
        self.assertNotContains(respuesta, 'Tutor principal</th>')
        self.client.post(reverse('alumnos:columnas'), {'restablecer': '1'})
        self.assertEqual(columnas.elegidas(self.admin), ['grado', 'asistencia_hoy', 'tutor', 'edad', 'estatus'])

    def test_sin_permiso_no_se_ofrecen_ni_se_guardan(self):
        recepcion = crear_usuario('recepcion', crear_rol('Solo estudiantes', {'Alumnos.view_alumno'}))
        self.client.force_login(recepcion)
        menu = [c.clave for c, _ in self.client.get(LISTA).context['menu_columnas']]
        self.assertNotIn('asistencia_ciclo', menu)
        self.assertNotIn('promedio', menu)
        self.assertNotIn('conducta', menu)
        self.client.post(reverse('alumnos:columnas'), {'columnas': ['asistencia_ciclo', 'promedio', 'conducta', 'portal']})
        self.assertEqual(columnas.elegidas(recepcion), ['portal'])

    def test_los_datos_de_las_columnas_nuevas(self):
        hoy = timezone.localdate()
        for dias, estado in ((1, 'PRESENTE'), (2, 'RETARDO'), (3, 'PRESENTE'), (4, 'FALTA')):
            AsistenciaGeneral.objects.create(inscripcion=self.inscripcion, fecha=hoy - timedelta(days=dias), estado=estado)
        mat = materia_en_grado('MAT', self.primaria, self.ciclo)
        esp = materia_en_grado('ESP', self.primaria, self.ciclo)
        ActaCalificaciones.objects.create(asignacion=mat, periodo=self.periodo, estado=ActaCalificaciones.CERRADA,
                                          resultados_cerrados=[{'inscripcion': self.inscripcion.pk, 'final': '8.00'}])
        ActaCalificaciones.objects.create(asignacion=esp, periodo=self.periodo, estado=ActaCalificaciones.CERRADA,
                                          resultados_cerrados=[{'inscripcion': self.inscripcion.pk, 'final': '10.00'}])
        self.registrar()   # un caso de conducta abierto para Ana
        Alumno.objects.filter(pk=self.alumno.pk).update(correo_electronico='ana@example.com', uid='UID-ANA')
        columnas.guardar(self.admin, ['asistencia_ciclo', 'promedio', 'conducta', 'portal', 'tarjeta'])
        respuesta = self.client.get(LISTA)
        ana = next(a for a in respuesta.context['pagina'] if a.pk == self.alumno.pk)
        zoe = next(a for a in respuesta.context['pagina'] if a.pk == self.otro.pk)
        self.assertEqual(ana.asistencia_ciclo, {'porcentaje': 75, 'faltas': 1, 'justificadas': 0, 'total': 4})
        self.assertEqual(str(ana.promedio), '9.00')
        self.assertEqual((ana.casos_abiertos, zoe.casos_abiertos), (1, 0))
        self.assertEqual(ana.portal_alumno.texto, 'Nunca ha entrado')
        self.assertIsNone(ana.portal_tutor)   # sin tutor
        self.assertContains(respuesta, '75 %')
        self.assertContains(respuesta, '1 abierto')
        self.assertContains(respuesta, 'Asignada')
        self.assertContains(respuesta, 'Sin tarjeta')   # Zoe
        self.assertIsNone(zoe.promedio)


# ---------------------------------------------------------------------------
# Filtros, búsqueda y contadores
# ---------------------------------------------------------------------------
class Colegio:
    """Ana (3.º A de primaria, con foto, CURP válida y tarjeta), Beto (3.º B, nuevo ingreso, con alergias y correo) y Ciro
    (1.º de secundaria, hijo de Rosa)."""

    def armar(self):
        self.ciclo = ciclo_actual_de_prueba()
        self.primaria = crear_grado('PRIMARIA', 3)
        self.grupo_a = grupo_de(self.primaria)
        self.grupo_b = crear_grupo(self.primaria, 'B')
        self.secundaria = crear_grado('SECUNDARIA', 1)
        self.ana = crear_alumno(nombre='Ana', apellido_paterno='Zamora', sexo='F', curp=CURP_VALIDA, fotografia='alumnos/ana.png', uid='UID-1',
                                fecha_ingreso=self.ciclo.fecha_inicio - timedelta(days=400))
        self.beto = crear_alumno(nombre='Beto', apellido_paterno='Alba', sexo='M', alergias='Penicilina',
                                 fecha_ingreso=self.ciclo.fecha_inicio + timedelta(days=1), correo_electronico='beto@example.com')
        self.ciro = crear_alumno(nombre='Ciro', apellido_paterno='Mora', sexo='M', fecha_ingreso=self.ciclo.fecha_inicio - timedelta(days=30))
        inscribir_antes(self.ana, self.ciclo, self.primaria, grupo=self.grupo_a)
        inscribir_antes(self.beto, self.ciclo, self.primaria, grupo=self.grupo_b)
        inscribir_antes(self.ciro, self.ciclo, self.secundaria)
        self.rosa = crear_tutor(nombre='Rosa', telefono='3531112233', usuario='rosa.mora')
        vincular(self.rosa, self.ciro)


@PRUEBAS
class FiltrosTests(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()

    def apellidos(self, **filtros):
        return sorted(a.apellido_paterno for a in self.client.get(LISTA, filtros).context['pagina'])

    def test_nivel_grupo_y_sexo(self):
        self.assertEqual(self.apellidos(nivel='PRIMARIA'), ['Alba', 'Zamora'])
        self.assertEqual(self.apellidos(grupo=self.grupo_b.pk), ['Alba'])
        self.assertEqual(self.apellidos(sexo='M'), ['Alba', 'Mora'])

    def test_datos_incompletos_alergias_ingreso_y_portal(self):
        self.assertEqual(self.apellidos(datos='sin_foto'), ['Alba', 'Mora'])
        self.assertEqual(self.apellidos(datos='curp_invalida'), ['Alba', 'Mora'])
        self.assertEqual(self.apellidos(datos='sin_tarjeta'), ['Alba', 'Mora'])
        self.assertEqual(self.apellidos(datos='con_alergias'), ['Alba'])
        self.assertEqual(self.apellidos(ingreso='nuevo'), ['Alba'])
        self.assertEqual(self.apellidos(portal='nunca_entro'), ['Alba'])          # el único con correo para entrar
        self.assertEqual(self.apellidos(portal='sin_acceso'), ['Mora', 'Zamora'])
        self.assertEqual(self.apellidos(portal='tutor_nunca'), ['Alba', 'Mora', 'Zamora'])
        self.rosa.ultimo_acceso = timezone.now()
        self.rosa.save(update_fields=['ultimo_acceso'])
        self.assertEqual(self.apellidos(portal='tutor_nunca'), ['Alba', 'Zamora'])
        self.assertEqual(self.client.get(LISTA, {'sexo': 'M', 'datos': 'sin_foto'}).context['mas_filtros'], 2)

    def test_buscar_por_el_telefono_del_tutor(self):
        self.assertEqual(self.apellidos(q='353 111 2233'), ['Mora'])
        self.assertEqual(self.apellidos(q='1112233'), ['Mora'])

    def test_requieren_atencion_solo_con_permiso(self):
        from unittest.mock import patch

        from .test_lista_tabla import AlertaDePrueba
        with patch('Panel.seguimiento.alertas', return_value=[AlertaDePrueba(self.beto)]):
            self.assertEqual(self.apellidos(atencion='si'), ['Alba'])
        recepcion = crear_usuario('recepcion', crear_rol('Solo estudiantes', {'Alumnos.view_alumno'}))
        self.client.force_login(recepcion)
        self.assertNotIn('atencion', self.client.get(LISTA).context['filtro'].fields)

    def test_contadores_por_nivel_y_grupo(self):
        contadores = self.client.get(LISTA).context['contadores']
        self.assertEqual([(n, t) for n, _, t in contadores['niveles']], [('PRIMARIA', 2), ('SECUNDARIA', 1)])
        self.assertEqual(contadores['grupos'], [])
        contadores = self.client.get(LISTA, {'nivel': 'PRIMARIA', 'sexo': 'M'}).context['contadores']
        self.assertEqual([(n, t) for n, _, t in contadores['niveles']], [('PRIMARIA', 1), ('SECUNDARIA', 1)])   # con los demás filtros
        self.assertEqual([(pk, t) for pk, _, t in contadores['grupos']], [(self.grupo_b.pk, 1)])


# ---------------------------------------------------------------------------
# Excel, imprimir, vista rápida
# ---------------------------------------------------------------------------
@PRUEBAS
class ExcelEImprimirTests(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()

    def test_excel_con_las_columnas_que_se_ven_y_los_filtros(self):
        columnas.guardar(self.admin, ['grado', 'tutor', 'tarjeta'])
        respuesta = self.client.get(reverse('alumnos:exportar'), {'nivel': 'PRIMARIA', 'formato': 'xlsx'})
        self.assertEqual(respuesta['Content-Type'], XLSX)
        hoja = hoja_de_excel(respuesta)
        for texto in ('Tutor principal', 'Tarjeta de entrada', 'Zamora', 'Alba', 'Sin tarjeta', 'Asignada'):
            self.assertIn(texto, hoja)
        self.assertNotIn('Ciro', hoja)   # de secundaria
        self.assertNotIn('Edad', hoja)
        csv = self.client.get(reverse('alumnos:exportar'))
        self.assertEqual(csv['Content-Type'], 'text/csv; charset=utf-8')   # el CSV sigue igual

    def test_imprimir_la_lista_por_grupo_con_columnas_en_blanco(self):
        respuesta = self.client.get(reverse('alumnos:imprimir'), {'nivel': 'PRIMARIA', 'titulo': 'Firmas de la junta', 'columnas': '3', 'firma': '1'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual([h['grupo'] for h in respuesta.context['hojas']], [self.grupo_a, self.grupo_b])
        self.assertContains(respuesta, 'Firmas de la junta · 3.º A')
        self.assertContains(respuesta, 'Zamora')
        self.assertNotContains(respuesta, 'Mora Ciro')
        self.assertEqual(respuesta.content.decode().count('<td class="hoja__blanco"></td>'), 6)   # 3 por cada uno
        self.assertContains(respuesta, '>Firma</th>')
        self.assertNotContains(respuesta, 'data-notificaciones')

    def test_vista_rapida(self):
        respuesta = self.client.get(reverse('alumnos:vista_rapida', args=[self.ciro.pk]))
        self.assertEqual(respuesta.status_code, 200)
        for texto in ('vista-rapida__contenido', 'Rosa', '353 111 2233', 'Ver expediente', reverse('alumnos:vista360', args=[self.ciro.pk])):
            self.assertContains(respuesta, texto)
        lista = self.client.get(LISTA)
        self.assertContains(lista, f'data-vista-rapida="{reverse("alumnos:vista_rapida", args=[self.ciro.pk])}"')


# ---------------------------------------------------------------------------
# Acciones en lote
# ---------------------------------------------------------------------------
@PRUEBAS
class LoteTests(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()
        self.dora = crear_alumno(nombre='Dora', apellido_paterno='Luna')   # sin inscripción

    def lote(self, accion, alumnos, **datos):
        return self.client.post(reverse('alumnos:lote'), {'accion': accion, 'alumnos': [a.pk for a in alumnos], 'next': LISTA, **datos})

    def test_inscribir_o_cambiar_de_grupo(self):
        respuesta = self.lote('grupo', [self.ana, self.dora, self.beto], ciclo=self.ciclo.pk, grado=self.primaria.pk, grupo=self.grupo_b.pk)
        self.assertRedirects(respuesta, LISTA, fetch_redirect_response=False)
        self.assertEqual(Inscripcion.objects.get(alumno=self.ana, ciclo=self.ciclo).grupo, self.grupo_b)   # cambió de grupo
        self.assertEqual(Inscripcion.objects.get(alumno=self.dora, ciclo=self.ciclo).grupo, self.grupo_b)  # inscrita
        self.assertEqual(Inscripcion.objects.filter(alumno=self.beto).count(), 1)                          # ya estaba
        self.assertTrue(LogEntry.objects.filter(object_id=str(self.ana.pk), change_message__contains='de 3.º A a 3.º B').exists())
        mensajes = [str(m) for m in respuesta.wsgi_request._messages]
        self.assertIn('2 estudiantes en 3.º B', mensajes[0])
        self.assertIn('ya estaba en', mensajes[0])

    def test_cambiar_estatus(self):
        self.lote('estatus', [self.ana, self.beto], estatus='SUSPENDIDO')
        self.assertEqual(set(Alumno.objects.filter(estatus='SUSPENDIDO').values_list('pk', flat=True)), {self.ana.pk, self.beto.pk})
        self.lote('estatus', [self.ana], estatus='BAJA')   # la baja no se ofrece en lote
        self.assertEqual(Alumno.objects.get(pk=self.ana.pk).estatus, 'SUSPENDIDO')

    def test_generar_contrasenas_y_descargarlas(self):
        antes = Alumno.objects.get(pk=self.beto.pk).contrasena
        self.lote('contrasenas', [self.beto])
        self.assertNotEqual(Alumno.objects.get(pk=self.beto.pk).contrasena, antes)
        self.assertContains(self.client.get(LISTA), 'Descargar contraseñas')
        archivo = self.client.get(reverse('alumnos:lote_credenciales'))
        texto = archivo.content.decode('utf-8-sig')
        self.assertIn('beto@example.com', texto)
        self.assertIn('Contraseña', texto)
        self.assertTrue(LogEntry.objects.filter(object_id=str(self.beto.pk), change_message__contains='contraseña nueva').exists())

    def test_exportar_a_los_elegidos(self):
        respuesta = self.lote('exportar', [self.beto])
        self.assertEqual(respuesta['Content-Type'], XLSX)
        hoja = hoja_de_excel(respuesta)
        self.assertIn('Alba', hoja)
        self.assertNotIn('Zamora', hoja)

    def test_comunicado_a_sus_tutores(self):
        respuesta = self.lote('comunicado', [self.ciro, self.ana])
        self.assertRedirects(respuesta, f"{reverse('comunicados:crear')}?desde=estudiantes", fetch_redirect_response=False)
        formulario = self.client.get(respuesta['Location'])
        self.assertContains(formulario, f'&quot;tutores&quot;: [{self.rosa.pk}]')
        sin_tutores = self.lote('comunicado', [self.ana])
        self.assertRedirects(sin_tutores, LISTA, fetch_redirect_response=False)

    def test_sin_permiso_no_se_puede(self):
        solo_ver = crear_usuario('consulta', crear_rol('Solo estudiantes', {'Alumnos.view_alumno'}))
        self.client.force_login(solo_ver)
        self.assertEqual(self.lote('estatus', [self.ana], estatus='SUSPENDIDO').status_code, 403)
        self.assertEqual(self.lote('contrasenas', [self.ana]).status_code, 403)
        self.assertEqual(Alumno.objects.get(pk=self.ana.pk).estatus, 'ACTIVO')
        lista = self.client.get(LISTA)
        self.assertTrue(lista.context['acciones_lote']['exportar'])
        self.assertFalse(lista.context['acciones_lote']['estatus'])


# ---------------------------------------------------------------------------
# Historial de cambios
# ---------------------------------------------------------------------------
@PRUEBAS
class HistorialTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        # Como EditarTests: Luis con su madre (principal) y su padre (vínculo inactivo)
        self.alumno = crear_alumno(referencia='3001', correo_electronico='luis@example.com')
        self.madre = crear_tutor(nombre='Rosa', apellido_paterno='Mora', curp=CURP_TUTOR)
        self.padre = crear_tutor(nombre='Jorge', apellido_paterno='Pérez', telefono='3534445566')
        self.v_madre = TutorAlumno.objects.create(tutor=self.madre, alumno=self.alumno, parentesco='MADRE', tutor_principal=True, activo=True)
        self.v_padre = TutorAlumno.objects.create(tutor=self.padre, alumno=self.alumno, parentesco='PADRE', activo=False)
        self.url = reverse('alumnos:editar', args=[self.alumno.pk])

    vinculos_existentes = EditarTests.vinculos_existentes
    publicar = EditarTests.publicar

    def mensajes(self):
        return list(LogEntry.objects.filter(object_id=str(self.alumno.pk), content_type__model='alumno').order_by('pk')
                    .values_list('change_message', flat=True))

    def test_editar_cambiar_estatus_y_el_portal_quedan_anotados(self):
        d = self.vinculos_existentes()
        self.publicar(alumno={'domicilio': 'Nueva calle 9', 'estatus': 'SUSPENDIDO'}, tutores=[d(self.v_madre), d(self.v_padre)])
        self.client.post(reverse('alumnos:estatus', args=[self.alumno.pk]), {'estatus': 'ACTIVO'})
        self.client.post(reverse('alumnos:baja', args=[self.alumno.pk]))
        self.client.post(reverse('alumnos:reactivar', args=[self.alumno.pk]))
        self.client.post(reverse('alumnos:contrasena', args=[self.alumno.pk]), {'contrasena': ''})
        mensajes = self.mensajes()
        self.assertIn('domicilio', mensajes[0])
        self.assertIn('«Suspendido»', mensajes[0])
        self.assertNotIn('contraseña', mensajes[0].lower())
        self.assertIn('de «Suspendido» a «Activo»', mensajes[1])
        self.assertIn('Lo dio de baja', mensajes[2])
        self.assertIn('Lo reactivó', mensajes[3])
        self.assertIn('contraseña nueva', mensajes[4])
        detalle = self.client.get(reverse('alumnos:detalle', args=[self.alumno.pk]))
        self.assertContains(detalle, 'Historial de cambios')
        self.assertContains(detalle, 'Lo dio de baja')
        self.assertEqual(len(detalle.context['historial']), 5)

    def test_el_cambio_de_grupo_desde_inscripciones(self):
        ciclo = ciclo_actual_de_prueba()
        grado = crear_grado('PRIMARIA', 2)
        otro = crear_grupo(grado, 'B')
        inscripcion = inscribir_antes(self.alumno, ciclo, grado, grupo=grupo_de(grado))
        self.client.post(reverse('inscripciones:editar', args=[inscripcion.pk]),
                         {'grado': grado.pk, 'grupo': otro.pk, 'fecha_inscripcion': inscripcion.fecha_inscripcion.isoformat()})
        self.assertIn('de 2.º A a 2.º B', self.mensajes()[-1])


__all__ = ['CURP_TUTOR', 'date']
