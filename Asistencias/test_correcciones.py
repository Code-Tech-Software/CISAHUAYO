"""Correcciones de asistencia del 2026-10-27: faltas de días que luego quedan sin clases, días sin registros, la
bitácora de cambios, el aviso del pase de lista al poner falta, la pantalla de entrada (sesión, referencia y su rol),
el cierre en segundo plano, los avisos a los tutores, la lista de Prefectura y los filtros por grupo."""
from datetime import time, timedelta
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.test import Client, override_settings
from django.urls import reverse

from Alumnos import asistencias as reglas
from Alumnos.models import (
    AsistenciaGeneral,
    AsistenciaMateria,
    CambioAsistencia,
    CierreDia,
    ConfiguracionAsistencia,
    DiaNoLectivo,
    NotificacionAsistencia,
)
from Asistencias.tests import entrar, url
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseAsistenciaTestCase,
    crear_alumno,
    crear_grupo,
    crear_rol,
    crear_tutor,
    crear_usuario,
    inscribir_antes,
    lunes,
    vincular,
)


def semana_pasada(dias=0):
    """Un día de la semana pasada (el lunes, por omisión): ya terminó y es del ciclo actual de prueba."""
    return lunes() - timedelta(days=7) + timedelta(days=dias)


# ---------------------------------------------------------------------------
# 1. Un día sin clases registrado después del cierre
# ---------------------------------------------------------------------------
@PRUEBAS
class DiaSinClasesDespuesDelCierreTests(BaseAsistenciaTestCase):
    hora = (10, 30)

    def setUp(self):
        super().setUp()
        self.ausente = inscribir_antes(crear_alumno(nombre='Ausente'), self.ciclo, self.grado)
        entrar(self.alumno, fecha=semana_pasada())
        reglas.cerrar_dia(semana_pasada())

    def registrar(self, **cambios):
        datos = {'desde': semana_pasada().isoformat(), 'hasta': '', 'motivo': 'Suspensión por lluvia', 'niveles': ['PRIMARIA']}
        datos.update(cambios)
        return self.client.post(url('dia_sin_clases_crear'), datos, follow=True)

    def test_quita_las_faltas_que_genero_el_cierre(self):
        self.assertEqual(AsistenciaGeneral.objects.get(inscripcion=self.ausente).estado, 'FALTA')
        respuesta = self.registrar()
        self.assertContains(respuesta, 'Se quitaron 1 falta que había generado el cierre')
        self.assertFalse(AsistenciaGeneral.objects.filter(inscripcion=self.ausente).exists())
        self.assertFalse(AsistenciaMateria.objects.filter(inscripcion=self.ausente).exists())
        # Lo que registró la pantalla de entrada se queda
        self.assertEqual(AsistenciaGeneral.objects.get(inscripcion=self.inscripcion).estado, 'PRESENTE')

    def test_otro_nivel_no_toca_las_faltas(self):
        self.registrar(niveles=['SECUNDARIA'])
        self.assertTrue(AsistenciaGeneral.objects.filter(inscripcion=self.ausente).exists())

    def test_lo_que_una_persona_corrigio_a_presente_se_queda(self):
        reglas.fijar_asistencia_general(self.ausente, semana_pasada(), 'PRESENTE', usuario=self.admin)
        self.registrar()
        self.assertEqual(AsistenciaGeneral.objects.get(inscripcion=self.ausente).estado, 'PRESENTE')
        self.assertFalse(AsistenciaMateria.objects.filter(inscripcion=self.ausente, estado='FALTA').exists())

    def test_tambien_quita_el_aviso_de_falta_a_sus_tutores(self):
        tutor = crear_tutor()
        NotificacionAsistencia.objects.create(tutor=tutor, inscripcion=self.ausente, fecha=semana_pasada(), tipo='FALTA', titulo='t', texto='x')
        self.registrar()
        self.assertFalse(NotificacionAsistencia.objects.exists())

    def test_quitar_el_dia_sin_clases_lo_deja_pendiente_de_cierre(self):
        self.registrar()
        self.assertTrue(CierreDia.objects.filter(fecha=semana_pasada()).exists())
        dia = DiaNoLectivo.objects.get(fecha=semana_pasada())
        respuesta = self.client.post(url('dia_sin_clases_eliminar', dia.pk), follow=True)
        self.assertContains(respuesta, 'vuelve a quedar pendiente de cierre')
        self.assertFalse(CierreDia.objects.filter(fecha=semana_pasada()).exists())
        self.assertIn(semana_pasada(), reglas.dias_pendientes_de_cierre())
        reglas.cerrar_dias_pendientes()
        self.assertEqual(AsistenciaGeneral.objects.get(inscripcion=self.ausente).estado, 'FALTA')


# ---------------------------------------------------------------------------
# 3 y 4. La asistencia del día: sin hora y el aviso del pase de lista
# ---------------------------------------------------------------------------
@PRUEBAS
class PaseDeListaContraLaFaltaGeneralTests(BaseAsistenciaTestCase):
    hora = (10, 30)

    def setUp(self):
        super().setUp()
        reglas.guardar_pase_de_lista(self.mat, lunes(), [(self.inscripcion, 'PRESENTE', '')], usuario=self.admin)

    def test_la_pantalla_avisa_antes_de_poner_falta(self):
        respuesta = self.client.get(url('dia'))
        self.assertContains(respuesta, f'data-pase="{self.mat.materia}"')
        self.assertContains(respuesta, 'data-asistencia-aviso-pase hidden')

    def test_al_guardar_la_falta_dice_que_cambio_el_pase(self):
        respuesta = self.client.post(url('dia_guardar'), {
            'inscripcion': self.inscripcion.pk, 'fecha': lunes().isoformat(), 'estado': 'FALTA', 'propagar': 'on', 'next': url('dia'),
        }, follow=True)
        self.assertContains(respuesta, f'El pase de lista lo tenía presente en {self.mat.materia}')
        self.assertEqual(self.estados_de_materias()['MAT'], 'FALTA')


# ---------------------------------------------------------------------------
# 5. Días de clases sin registros
# ---------------------------------------------------------------------------
@PRUEBAS
class DiasSinRegistrosTests(BaseAsistenciaTestCase):
    hora = (10, 30)

    def test_un_dia_sin_ni_un_registro_se_avisa_y_no_se_cierra_solo(self):
        entrar(self.alumno, fecha=semana_pasada())             # lunes de la semana pasada: hubo entradas
        self.assertIn(semana_pasada(1), reglas.dias_sin_registros())   # el martes nadie entró
        self.assertNotIn(semana_pasada(), reglas.dias_sin_registros())
        reglas.cerrar_dias_pendientes()
        self.assertFalse(CierreDia.objects.filter(fecha=semana_pasada(1)).exists())
        respuesta = self.client.get(url('inicio'))
        self.assertContains(respuesta, 'días de clases sin registros')
        self.assertContains(respuesta, f'?fecha={semana_pasada(1).isoformat()}')

    def test_antes_del_primer_registro_del_ciclo_no_se_avisa(self):
        self.assertEqual(reglas.dias_sin_registros(), [])   # el sistema todavía no se usaba
        entrar(self.alumno, fecha=semana_pasada(3))
        self.assertNotIn(semana_pasada(1), reglas.dias_sin_registros())

    def test_un_dia_cerrado_o_sin_clases_no_se_avisa(self):
        entrar(self.alumno, fecha=semana_pasada())
        reglas.cerrar_dia(semana_pasada(1))
        DiaNoLectivo.registrar(fecha=semana_pasada(2), motivo='Consejo técnico')
        sin_registros = reglas.dias_sin_registros()
        self.assertNotIn(semana_pasada(1), sin_registros)
        self.assertNotIn(semana_pasada(2), sin_registros)
        self.assertIn(semana_pasada(3), sin_registros)


# ---------------------------------------------------------------------------
# 7. El cierre automático en segundo plano
# ---------------------------------------------------------------------------
@PRUEBAS
class CierreEnSegundoPlanoTests(BaseAsistenciaTestCase):
    hora = (7, 50)

    def test_corre_en_un_hilo_aparte(self):
        with override_settings(ASISTENCIA_CIERRE_EN_SEGUNDO_PLANO=True), patch('Alumnos.asistencias.threading.Thread') as hilo:
            reglas.en_segundo_plano(lambda: None, 'falla')
        hilo.assert_called_once()
        hilo.return_value.start.assert_called_once()

    def test_si_falla_la_siguiente_entrada_lo_intenta_de_nuevo(self):
        with patch('Alumnos.asistencias.cerrar_dias_pendientes', side_effect=RuntimeError('falla')):
            with self.assertRaises(RuntimeError):
                reglas.cierre_automatico_del_dia()
        with patch('Alumnos.asistencias.cerrar_dias_pendientes', return_value=[]) as cierre:
            reglas.cierre_automatico_del_dia()
            reglas.cierre_automatico_del_dia()
        cierre.assert_called_once()   # una vez que salió bien, ya no se repite ese día


# ---------------------------------------------------------------------------
# 8. La bitácora de cambios
# ---------------------------------------------------------------------------
@PRUEBAS
class BitacoraTests(BaseAsistenciaTestCase):
    hora = (10, 30)

    def test_anota_la_correccion_de_la_asistencia_del_dia_con_lo_que_habia(self):
        entrar(self.alumno, (8, 20))
        reglas.fijar_asistencia_general(self.inscripcion, lunes(), 'PRESENTE', hora=time(7, 55), observaciones='Se le olvidó', usuario=self.admin)
        general = CambioAsistencia.objects.get(materia_grado__isnull=True)
        self.assertEqual((general.estado_anterior, general.hora_anterior, general.estado_nuevo, general.hora_nueva),
                         ('RETARDO', time(8, 20), 'PRESENTE', time(7, 55)))
        self.assertEqual((general.usuario, general.via, general.observacion_nueva), (self.admin, 'Asistencia del día', 'Se le olvidó'))
        # la primera clase había quedado con falta por el retardo; con la hora nueva queda presente
        materia = CambioAsistencia.objects.get(materia_grado=self.mat)
        self.assertEqual((materia.estado_anterior, materia.estado_nuevo), ('FALTA', 'PRESENTE'))

    def test_anota_el_pase_de_lista_y_no_lo_que_no_cambio(self):
        reglas.guardar_pase_de_lista(self.mat, lunes(), [(self.inscripcion, 'FALTA', 'No llegó')], usuario=self.admin)
        reglas.guardar_pase_de_lista(self.mat, lunes(), [(self.inscripcion, 'FALTA', 'No llegó')], usuario=self.admin)
        reglas.guardar_pase_de_lista(self.mat, lunes(), [(self.inscripcion, 'PRESENTE', '')], usuario=self.admin)
        cambios = list(CambioAsistencia.objects.filter(materia_grado=self.mat).order_by('pk').values_list('estado_anterior', 'estado_nuevo', 'via'))
        via = f'Pase de lista de {self.mat.materia}'
        self.assertEqual(cambios, [('', 'FALTA', via), ('FALTA', 'PRESENTE', via)])
        # al quedar presente en una clase, la entrada al colegio también se anota
        self.assertTrue(CambioAsistencia.objects.filter(materia_grado__isnull=True, estado_nuevo='PRESENTE').exists())

    def test_la_pantalla_de_entrada_y_el_cierre_no_se_anotan(self):
        entrar(self.alumno)
        reglas.cerrar_dia(semana_pasada())
        self.assertFalse(CambioAsistencia.objects.exists())

    def test_el_historial_del_estudiante_muestra_la_bitacora(self):
        reglas.guardar_pase_de_lista(self.mat, lunes(), [(self.inscripcion, 'FALTA', 'No llegó')], usuario=self.admin)
        respuesta = self.client.get(url('alumno', self.alumno.pk))
        self.assertContains(respuesta, 'Cambios en la asistencia')
        self.assertContains(respuesta, f'Pase de lista de {self.mat.materia}')
        self.assertContains(respuesta, 'No llegó')


# ---------------------------------------------------------------------------
# 6, 9 y 10. La pantalla de entrada
# ---------------------------------------------------------------------------
@PRUEBAS
class PantallaDeEntradaTests(BaseAsistenciaTestCase):
    hora = (7, 50)

    def registrar(self, codigo, modo='uid', cliente=None):
        respuesta = (cliente or self.client).post(url('registrar_entrada'), {'codigo': codigo, 'modo': modo})
        return respuesta.json()

    def test_la_sesion_de_la_pantalla_no_caduca_mientras_esta_abierta(self):
        self.client.get(url('kiosco'))
        self.assertGreater(self.client.session.get_expiry_age(), 29 * 24 * 3600)
        self.client.get(url('kiosco_estado'))
        self.assertGreater(self.client.session.get_expiry_age(), 29 * 24 * 3600)

    def test_la_entrada_con_referencia_se_puede_apagar(self):
        self.alumno.referencia = '4455'
        self.alumno.save()
        configuracion = ConfiguracionAsistencia.cargar()
        configuracion.entrada_con_referencia = False
        configuracion.save()
        pantalla = self.client.get(url('kiosco'))
        self.assertContains(pantalla, 'Acude a control escolar para que registren tu entrada')
        self.assertContains(pantalla, 'data-manual novalidate autocomplete="off" hidden')
        datos = self.registrar('4455', modo='referencia')
        self.assertEqual((datos['ok'], datos['tipo']), (False, 'NO_ENCONTRADO'))
        self.assertFalse(AsistenciaGeneral.objects.exists())
        self.assertTrue(self.registrar('AB12CD34')['ok'])   # la credencial sí

    def test_el_reporte_cuenta_las_entradas_con_referencia(self):
        self.alumno.referencia = '4455'
        self.alumno.save()
        self.registrar('4455', modo='referencia')
        respuesta = self.client.get(url('reporte', grado=self.grado.pk, desde=lunes().isoformat(), hasta=lunes().isoformat()))
        self.assertEqual(respuesta.context['filas'][0].cuenta['con_referencia'], 1)
        self.assertContains(respuesta, 'Con referencia')

    def test_el_rol_de_la_pantalla_solo_registra_entradas(self):
        from Usuarios.iniciales import PANTALLA_DE_ENTRADA, PREDETERMINADOS
        self.assertIn(PANTALLA_DE_ENTRADA, [nombre for nombre, *_ in PREDETERMINADOS])
        cuenta = crear_usuario('entrada', crear_rol('Pantalla de prueba', {'Alumnos.add_asistenciageneral'}))
        cliente = Client()
        cliente.force_login(cuenta)
        pantalla = cliente.get(url('kiosco'))
        self.assertEqual(pantalla.status_code, 200)
        self.assertContains(pantalla, 'Cerrar sesión')          # salir es cerrar su sesión
        self.assertNotContains(pantalla, f'href="{url("inicio")}"')
        self.assertTrue(self.registrar('AB12CD34', cliente=cliente)['ok'])
        for pagina in (url('inicio'), url('dia'), url('justificaciones')):
            self.assertEqual(cliente.get(pagina).status_code, 403, pagina)

    def test_la_migracion_crea_el_rol_en_un_sistema_que_ya_tenia_roles(self):
        from importlib import import_module
        from django.apps import apps
        migracion = import_module('Usuarios.migrations.0021_rol_pantalla_de_entrada')
        Group.objects.filter(name='Pantalla de entrada').delete()
        migracion.crear_rol(apps, None)
        grupo = Group.objects.get(name='Pantalla de entrada')
        self.assertEqual([p.codename for p in grupo.permissions.all()], ['add_asistenciageneral'])
        migracion.crear_rol(apps, None)   # si ya existe, no se toca
        self.assertEqual(Group.objects.filter(name='Pantalla de entrada').count(), 1)


# ---------------------------------------------------------------------------
# 11. Avisos a los tutores
# ---------------------------------------------------------------------------
@PRUEBAS
class AvisosATutoresTests(BaseAsistenciaTestCase):
    hora = (10, 30)

    def setUp(self):
        super().setUp()
        self.tutor = crear_tutor(usuario='rosa.mora')
        self.tutor.establecer_contrasena('luna456')
        self.tutor.save()
        vincular(self.tutor, self.alumno)
        self.tarde = inscribir_antes(crear_alumno(nombre='Tardío', uid='TARDE1'), self.ciclo, self.grado)
        vincular(self.tutor, self.tarde.alumno)
        self.puntual = inscribir_antes(crear_alumno(nombre='Puntual', uid='BIEN1'), self.ciclo, self.grado)
        vincular(self.tutor, self.puntual.alumno)
        self.dia = semana_pasada(4)   # el viernes pasado
        entrar(self.tarde.alumno, (8, 30), fecha=self.dia)
        entrar(self.puntual.alumno, (7, 50), fecha=self.dia)

    def test_al_cerrar_el_dia_avisa_de_la_falta_y_del_retardo(self):
        reglas.cerrar_dia(self.dia)
        avisos = {a.inscripcion_id: a for a in NotificacionAsistencia.objects.all()}
        self.assertEqual(set(avisos), {self.inscripcion.pk, self.tarde.pk})
        self.assertEqual(avisos[self.inscripcion.pk].tipo, 'FALTA')
        self.assertIn('no asistió al colegio', avisos[self.inscripcion.pk].texto)
        self.assertIn('llegó con retardo a las 08:30', avisos[self.tarde.pk].texto)
        reglas.cerrar_dia(self.dia)   # cerrar otra vez no repite los avisos
        self.assertEqual(NotificacionAsistencia.objects.count(), 2)

    def test_no_avisa_de_faltas_justificadas_ni_a_quien_no_recibe_notificaciones(self):
        from Alumnos.models import Justificacion
        Justificacion.objects.create(inscripcion=self.inscripcion, fecha=self.dia, motivo='Cita médica', justifica_general=True)
        self.tutor.alumnos_relacionados.filter(alumno=self.tarde.alumno).update(recibe_notificaciones=False)
        reglas.cerrar_dia(self.dia)
        self.assertFalse(NotificacionAsistencia.objects.exists())

    def test_se_puede_apagar_y_no_avisa_de_dias_viejos(self):
        configuracion = ConfiguracionAsistencia.cargar()
        configuracion.avisar_a_tutores = False
        configuracion.save()
        reglas.cerrar_dia(self.dia)
        self.assertFalse(NotificacionAsistencia.objects.exists())
        configuracion.avisar_a_tutores = True
        configuracion.save()
        reglas.cerrar_dia(lunes() - timedelta(days=14))
        self.assertFalse(NotificacionAsistencia.objects.exists())

    def test_el_tutor_lo_ve_en_la_campana_del_portal_y_queda_leido_al_abrir_a_su_hijo(self):
        reglas.cerrar_dia(self.dia)
        portal = Client()
        portal.post(reverse('login'), {'acceso': 'tutores', 'tutores-usuario': 'rosa.mora', 'tutores-contrasena': 'luna456'})
        inicio = portal.get(reverse('portal_tutores:inicio'))
        self.assertContains(inicio, 'data-asistencia-sin-leer="2"')
        self.assertContains(inicio, f'Falta de {self.alumno.nombre}')
        aviso = NotificacionAsistencia.objects.get(inscripcion=self.inscripcion)
        respuesta = portal.get(reverse('portal_tutores:aviso_asistencia', args=[aviso.pk]))
        self.assertRedirects(respuesta, reverse('portal_tutores:estudiante', args=[self.alumno.pk]))
        aviso.refresh_from_db()
        self.assertTrue(aviso.leida)
        self.assertContains(portal.get(reverse('portal_tutores:inicio')), 'data-asistencia-sin-leer="1"')

    def test_un_aviso_ajeno_da_404(self):
        reglas.cerrar_dia(self.dia)
        otro = crear_tutor(usuario='otro', nombre='Otro')
        otro.establecer_contrasena('sol789')
        otro.save()
        portal = Client()
        portal.post(reverse('login'), {'acceso': 'tutores', 'tutores-usuario': 'otro', 'tutores-contrasena': 'sol789'})
        aviso = NotificacionAsistencia.objects.first()
        self.assertEqual(portal.get(reverse('portal_tutores:aviso_asistencia', args=[aviso.pk])).status_code, 404)


# ---------------------------------------------------------------------------
# 12. Prefectura: entraron y faltaron a clases
# ---------------------------------------------------------------------------
@PRUEBAS
class EntraronYFaltaronTests(BaseAsistenciaTestCase):
    hora = (12, 30)

    def setUp(self):
        super().setUp()
        entrar(self.alumno, (7, 50))
        reglas.guardar_pase_de_lista(self.cie, lunes(), [(self.inscripcion, 'FALTA', 'No estaba en el salón')], usuario=self.admin)
        self.no_vino = inscribir_antes(crear_alumno(nombre='Nadie'), self.ciclo, self.grado)
        reglas.guardar_pase_de_lista(self.cie, lunes(), [(self.no_vino, 'FALTA', 'No vino')], usuario=self.admin)

    def test_solo_quien_entro_y_le_pusieron_falta(self):
        from Prefectura import asistencia
        quienes = set(asistencia.entraron_y_faltaron(AsistenciaMateria.objects.all()).values_list('inscripcion', flat=True))
        self.assertEqual(quienes, {self.inscripcion.pk})

    def test_una_salida_anticipada_lo_explica(self):
        from Prefectura import asistencia
        from Prefectura.models import MovimientoAcceso
        MovimientoAcceso.objects.create(alumno=self.alumno, inscripcion=self.inscripcion, fecha=lunes(), hora=time(10, 30),
                                        tipo=MovimientoAcceso.SALIDA, motivo='Cita médica')
        self.assertFalse(asistencia.entraron_y_faltaron(AsistenciaMateria.objects.all()).exists())

    def test_la_lista_de_prefectura(self):
        respuesta = self.client.get(reverse('prefectura:asistencia_registros'), {'fuente': 'materias', 'estado': 'ENTRARON'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual([r.inscripcion for r in respuesta.context['pagina']], [self.inscripcion])
        self.assertContains(self.client.get(reverse('prefectura:inicio')), 'Entraron y faltaron a clases')


# ---------------------------------------------------------------------------
# 14. Filtro por grupo
# ---------------------------------------------------------------------------
@PRUEBAS
class FiltroPorGrupoTests(BaseAsistenciaTestCase):
    hora = (10, 30)

    def setUp(self):
        super().setUp()
        self.grupo_b = crear_grupo(self.grado, 'B')
        self.de_b = inscribir_antes(crear_alumno(nombre='Bruno'), self.ciclo, self.grado, grupo=self.grupo_b)

    def test_la_asistencia_del_dia_por_grupo(self):
        respuesta = self.client.get(url('dia', grupo=self.grupo_b.pk))
        self.assertEqual([i.pk for i in respuesta.context['pagina']], [self.de_b.pk])
        self.assertEqual(respuesta.context['total']['inscritos'], 1)

    def test_el_reporte_por_grupo(self):
        respuesta = self.client.get(url('reporte', grado=self.grado.pk, grupo=self.grupo_b.pk))
        self.assertEqual([i.pk for i in respuesta.context['filas']], [self.de_b.pk])
        self.assertEqual(respuesta.context['grupo'], self.grupo_b)
        exportacion = self.client.get(url('reporte_exportar', grado=self.grado.pk, grupo=self.grupo_b.pk))
        self.assertIn('-b-', exportacion['Content-Disposition'])
        exportado = exportacion.content.decode('utf-8')
        self.assertIn('Bruno', exportado)
        self.assertNotIn(str(self.alumno), exportado)

    def test_un_grupo_de_otro_grado_se_ignora(self):
        from CISAHUAYO.pruebas import crear_grado
        otro = crear_grupo(crear_grado('PRIMARIA', 5), 'C')
        respuesta = self.client.get(url('reporte', grado=self.grado.pk, grupo=otro.pk))
        self.assertIsNone(respuesta.context['grupo'])
        self.assertEqual(len(respuesta.context['filas']), 2)
