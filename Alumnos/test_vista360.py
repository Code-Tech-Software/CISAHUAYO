"""Vista 360 del estudiante (Alumnos/vista360.py): el enlace en el expediente, los filtros de ciclo y periodo, cada
sección con los datos reales de su módulo (y sus estados: con datos, sin registros, sin permiso, error) y que nada de
otros estudiantes se mezcle."""
from datetime import time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.db import DatabaseError
from django.urls import reverse

from Calificaciones.models import ActaCalificaciones
from Conducta.models import POSITIVA, RegistroConducta
from Conducta.pruebas import BaseConductaTestCase
from CISAHUAYO.pruebas import PRUEBAS, crear_rol, crear_tutor, crear_usuario, hoy, materia_en_grado
from Retiros.models import AvisoRetiro, MotivoRetiro, RetiroEstudiante
from Usuarios.models import PerfilUsuario

from .models import AsistenciaGeneral, AsistenciaMateria, Justificacion


@PRUEBAS
class Vista360Tests(BaseConductaTestCase):
    """Ana (4.º de primaria) con el «Primer bimestre» abierto hoy; inicia sesión el administrador."""

    def setUp(self):
        super().setUp()
        self.url = reverse('alumnos:vista360', args=[self.alumno.pk])

    def secciones(self, **consulta):
        respuesta = self.client.get(self.url, consulta)
        self.assertEqual(respuesta.status_code, 200)
        return respuesta, {seccion.clave: seccion for seccion in respuesta.context['secciones']}

    # --- La página -----------------------------------------------------------------------------------------------
    def test_el_expediente_enlaza_la_vista_360_justo_despues_del_resumen(self):
        html = self.client.get(reverse('alumnos:detalle', args=[self.alumno.pk])).content.decode()
        resumen, enlace, tutores = html.index('id="tab-resumen"'), html.index(self.url), html.index('id="tab-tutores"')
        self.assertLess(resumen, enlace)
        self.assertLess(enlace, tutores)
        self.assertIn('id="resumen"', html)   # el resumen del expediente sigue ahí

    def test_sin_datos_cada_seccion_lo_dice_sin_inventar_cifras(self):
        respuesta, secciones = self.secciones()
        filtros = respuesta.context['filtros']
        self.assertEqual((filtros.ciclo, filtros.periodo), (self.ciclo, self.periodo))   # los actuales por omisión
        self.assertEqual([s.clave for s in respuesta.context['secciones']],
                         ['calificaciones', 'asistencia', 'conducta', 'seguimiento', 'retiros'])
        calificaciones, asistencia = secciones['calificaciones'], secciones['asistencia']
        self.assertEqual((calificaciones.estado, calificaciones.valor, calificaciones.descripcion), ('vacio', '—', 'Sin calificaciones registradas'))
        self.assertEqual((asistencia.estado, asistencia.valor, asistencia.descripcion), ('vacio', '—', 'Sin registros'))
        self.assertEqual((secciones['conducta'].valor, secciones['conducta'].descripcion), ('0', 'Sin anotaciones en este periodo'))
        self.assertEqual((secciones['seguimiento'].valor, secciones['seguimiento'].alcance), ('0', 'actual'))
        self.assertEqual(secciones['retiros'].valor, '0')
        for texto in ('Sin calificaciones registradas', 'Sin registros', 'Sin anotaciones en este periodo', 'Ana', 'Primer bimestre'):
            self.assertContains(respuesta, texto)

    def test_la_seccion_pedida_se_abre_y_las_demas_quedan_ocultas(self):
        respuesta, _ = self.secciones(seccion='conducta')
        html = respuesta.content.decode()
        self.assertEqual(respuesta.context['seccion_abierta'], 'conducta')
        self.assertRegex(html, r'id="panel-conducta"[^>]*data-v360-panel="conducta" tabindex="-1">')
        self.assertRegex(html, r'id="panel-retiros"[^>]*tabindex="-1" hidden>')
        self.assertEqual(self.secciones(seccion='otra')[0].context['seccion_abierta'], '')

    def test_cambiar_el_estatus_desde_la_vista_vuelve_a_ella(self):
        destino = f'{self.url}?periodo=ciclo'
        respuesta = self.client.post(reverse('alumnos:estatus', args=[self.alumno.pk]), {'estatus': 'INACTIVO', 'next': destino})
        self.assertRedirects(respuesta, destino, fetch_redirect_response=False)
        ajeno = self.client.post(reverse('alumnos:estatus', args=[self.alumno.pk]), {'estatus': 'ACTIVO', 'next': 'https://otro.sitio/'})
        self.assertRedirects(ajeno, self.alumno.get_absolute_url(), fetch_redirect_response=False)

    # --- Calificaciones ------------------------------------------------------------------------------------------
    def test_calificaciones_solo_de_actas_cerradas_y_un_cero_real_se_muestra(self):
        mat = materia_en_grado('MAT', self.primaria, self.ciclo)
        esp = materia_en_grado('ESP', self.primaria, self.ciclo)
        ActaCalificaciones.objects.create(asignacion=mat, periodo=self.periodo, estado=ActaCalificaciones.CERRADA,
                                          resultados_cerrados=[{'inscripcion': self.inscripcion.pk, 'final': '0.00'}])
        ActaCalificaciones.objects.create(asignacion=esp, periodo=self.periodo, estado=ActaCalificaciones.EN_CAPTURA,
                                          resultados_cerrados=[{'inscripcion': self.inscripcion.pk, 'final': '9.00'}])
        respuesta, secciones = self.secciones(seccion='calificaciones')
        calificaciones = secciones['calificaciones']
        self.assertEqual((calificaciones.estado, calificaciones.valor), ('ok', '0.00'))
        self.assertEqual(calificaciones.detalle['general'], Decimal('0.00'))
        self.assertEqual(calificaciones.detalle['en_captura'], 1)
        self.assertEqual([f.valores for f in calificaciones.detalle['filas']], [[None], [Decimal('0.00')]])   # Esp, Mat
        self.assertNotContains(respuesta, '9.00')   # el acta en captura no se ve
        self.assertContains(respuesta, f'materia={mat.pk}')   # «Ver» lleva a la materia con el ciclo y el periodo

    # --- Asistencia ----------------------------------------------------------------------------------------------
    def test_asistencia_de_entrada_aparte_de_la_de_cada_materia(self):
        dias = [hoy() - timedelta(days=n) for n in (1, 2, 3)]
        for fecha, estado in zip(dias, ('PRESENTE', 'RETARDO', 'FALTA')):
            AsistenciaGeneral.objects.create(inscripcion=self.inscripcion, fecha=fecha, estado=estado, hora_entrada=time(7, 50))
        Justificacion.objects.create(inscripcion=self.inscripcion, fecha=dias[2], motivo='Cita médica', justifica_general=True)
        mat = materia_en_grado('MAT', self.primaria, self.ciclo)
        AsistenciaMateria.objects.create(inscripcion=self.inscripcion, materia_grado=mat, fecha=dias[0], estado='FALTA')
        AsistenciaGeneral.objects.create(inscripcion=self.inscripcion_otro, fecha=dias[0], estado='FALTA')   # de otra estudiante

        respuesta, secciones = self.secciones(seccion='asistencia')
        asistencia = secciones['asistencia']
        totales = asistencia.detalle['totales']
        self.assertEqual((totales['registros'], totales['faltas'], totales['justificadas'], totales['sin_justificar']), (3, 1, 1, 0))
        self.assertEqual(asistencia.valor, '67 %')   # presente y retardo de 3 días con registro; la falta de MAT no cuenta
        self.assertEqual([(f['materia_grado__materia__nombre'], f['faltas']) for f in asistencia.detalle['por_materia']], [('Mat', 1)])
        self.assertContains(respuesta, 'Cita médica')

    def test_sin_permiso_de_justificaciones_no_ve_sus_motivos(self):
        AsistenciaGeneral.objects.create(inscripcion=self.inscripcion, fecha=hoy() - timedelta(days=1), estado='FALTA')
        Justificacion.objects.create(inscripcion=self.inscripcion, fecha=hoy() - timedelta(days=1), motivo='Asunto familiar', justifica_general=True)
        self.con_permisos('view_alumno', 'view_asistenciageneral')
        respuesta, secciones = self.secciones(seccion='asistencia')
        self.assertEqual(secciones['asistencia'].estado, 'ok')
        self.assertNotContains(respuesta, 'Asunto familiar')

    # --- Conducta y seguimiento ----------------------------------------------------------------------------------
    def test_conducta_del_periodo_y_casos_abiertos(self):
        self.registrar()
        self.registrar(tipo=POSITIVA, categoria=self.reconocimiento.pk, motivo=self.ayuda.pk, descripcion='Ayudó a un compañero.')
        self.registrar(motivo=self.empujon.pk)
        RegistroConducta.objects.filter(pk=self.ultimo().pk).update(anulado=True)   # los anulados no cuentan
        antes = (hoy() - timedelta(days=45)).isoformat()   # en el ciclo, antes del periodo
        self.registrar(fecha=antes, motivo=self.empujon.pk)
        self.registrar(alumno=self.otro.pk, categoria=self.convivencia_sec.pk, motivo=self.agresion_sec.pk)

        respuesta, secciones = self.secciones(seccion='conducta')
        conducta, seguimiento = secciones['conducta'], secciones['seguimiento']
        self.assertEqual((conducta.valor, conducta.detalle['incidencias'], conducta.detalle['positivas']), ('2', 1, 1))
        self.assertEqual(conducta.descripcion, '1 incidencia · 1 positiva')
        # El seguimiento es el estado de hoy: también el caso abierto antes del periodo
        self.assertEqual((seguimiento.valor, seguimiento.descripcion), ('2', 'Casos abiertos'))
        self.assertContains(respuesta, 'Agresión verbal')
        # Todo el ciclo: también el registro anterior al periodo
        _, ciclo = self.secciones(periodo='ciclo')
        self.assertEqual(ciclo['conducta'].valor, '3')

    def test_un_caso_cerrado_en_el_periodo_sale_de_los_abiertos(self):
        self.registrar()
        caso = self.ultimo()
        RegistroConducta.objects.filter(pk=caso.pk).update(estado=RegistroConducta.CERRADO, cerrado_en=caso.creado, observaciones_cierre='Se habló con la familia.')
        respuesta, secciones = self.secciones(seccion='seguimiento')
        seguimiento = secciones['seguimiento']
        self.assertEqual((seguimiento.estado, seguimiento.valor), ('vacio', '0'))
        self.assertEqual(seguimiento.detalle['cerrados'], [caso])
        self.assertContains(respuesta, 'Se habló con la familia.')

    # --- Retiros -------------------------------------------------------------------------------------------------
    def retiro(self, alumno, inscripcion, fecha, estado, aviso=None):
        if aviso is None:
            tutor = crear_tutor(nombre='Ana', apellido_paterno='Campos')
            aviso = AvisoRetiro.objects.create(tutor=tutor, fecha=fecha, hora=time(11, 30), motivo=MotivoRetiro.objects.get(nombre='Cita médica'), recoge=tutor)
        RetiroEstudiante.objects.create(aviso=aviso, alumno=alumno, inscripcion=inscripcion, fecha=fecha, estado=estado)
        return aviso

    def test_retiros_solo_del_estudiante_y_salidas_aparte_de_los_avisos(self):
        aviso = self.retiro(self.alumno, self.inscripcion, hoy() - timedelta(days=2), RetiroEstudiante.RETIRADO)
        self.retiro(self.otro, self.inscripcion_otro, hoy() - timedelta(days=2), RetiroEstudiante.AVISADO, aviso=aviso)   # su hermana
        self.retiro(self.alumno, self.inscripcion, hoy() - timedelta(days=1), RetiroEstudiante.CANCELADO)
        self.retiro(self.alumno, self.inscripcion, hoy() + timedelta(days=1), RetiroEstudiante.AVISADO)
        _, secciones = self.secciones(seccion='retiros')
        retiros = secciones['retiros']
        self.assertEqual((retiros.valor, retiros.detalle['salidas'], retiros.detalle['pendientes'], retiros.detalle['cancelados']), ('2', 1, 1, 1))
        self.assertEqual({r.alumno_id for r in retiros.detalle['retiros']}, {self.alumno.pk})
        self.assertEqual(retiros.descripcion, 'Avisos de retiro · 1 salida confirmada')

    def test_retiros_fuera_de_sus_niveles_no_se_muestran(self):
        rol = crear_rol('Recepción de secundaria', {'Alumnos.view_alumno', 'Retiros.consultar'})
        recepcion = crear_usuario('recepcion', rol)
        PerfilUsuario.objects.filter(usuario=recepcion).update(niveles_retiros=['SECUNDARIA'])
        self.retiro(self.alumno, self.inscripcion, hoy() - timedelta(days=2), RetiroEstudiante.RETIRADO)
        self.client.force_login(recepcion)
        _, secciones = self.secciones()
        self.assertEqual((secciones['retiros'].estado, secciones['retiros'].detalle), ('sin_permiso', {}))

    # --- Permisos y errores --------------------------------------------------------------------------------------
    def test_sin_los_permisos_de_cada_modulo_no_ve_sus_datos(self):
        self.registrar()
        self.con_permisos('view_alumno')
        respuesta, secciones = self.secciones(seccion='conducta')
        self.assertEqual({s.estado for s in secciones.values()}, {'sin_permiso'})
        self.assertContains(respuesta, 'Sin permiso')
        self.assertNotContains(respuesta, 'Agresión verbal')

    def test_sin_permiso_de_estudiantes_no_entra(self):
        self.con_permisos('view_registroconducta')
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_si_una_seccion_falla_las_demas_se_muestran(self):
        self.registrar()
        with patch('Alumnos.vista360.retiros', side_effect=DatabaseError('caída')):
            respuesta, secciones = self.secciones()
        self.assertEqual(secciones['retiros'].estado, 'error')
        self.assertEqual(secciones['conducta'].valor, '1')
        self.assertContains(respuesta, 'No se pudo consultar')

    def test_un_ciclo_sin_inscripcion_no_aplica(self):
        self.inscripcion.delete()
        _, secciones = self.secciones()
        self.assertEqual(secciones['calificaciones'].estado, 'no_aplica')
        self.assertEqual(secciones['retiros'].estado, 'no_aplica')
