"""Asistencias: permisos, resumen del día, cierre, pantalla de la entrada y asistencia general del día."""
from datetime import time, timedelta
from unittest.mock import patch

from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from Alumnos import asistencias as reglas
from Alumnos.models import (
    AsistenciaGeneral,
    AsistenciaMateria,
    CierreDia,
    ConfiguracionAsistencia,
    DiaNoLectivo,
    Justificacion,
)
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseAsistenciaTestCase,
    ciclo_cerrado_de_prueba,
    crear_alumno,
    crear_grado,
    inscribir_antes,
    lunes,
    materia_en_grado,
    momento,
)


def entrar(alumno, hora=(7, 45), fecha=None, origen='UID', usuario=None):
    """Registra la entrada de un alumno a esa hora (con las reglas reales)."""
    return reglas.registrar_entrada(alumno, origen, usuario=usuario, momento=momento(*hora, fecha=fecha))


def url(nombre, *args, **consulta):
    direccion = reverse(f'asistencias:{nombre}', args=args)
    return f'{direccion}?{"&".join(f"{k}={v}" for k, v in consulta.items())}' if consulta else direccion


# ---------------------------------------------------------------------------
# Permisos
# ---------------------------------------------------------------------------
@PRUEBAS
class PermisosTests(BaseAsistenciaTestCase):
    hora = (8, 5)

    def setUp(self):
        super().setUp()
        reglas.fijar_asistencia_general(self.inscripcion, lunes(), 'FALTA')
        self.justificacion = Justificacion.objects.create(inscripcion=self.inscripcion, fecha=lunes(), motivo='Cita', justifica_general=True)
        self.dia_libre = DiaNoLectivo.objects.create(fecha=lunes() + timedelta(days=30), motivo='Puente')

    def paginas(self):
        return (
            url('inicio'), url('dia'), url('clases'), url('clase', self.mat.pk), url('justificaciones'), url('justificacion_crear'),
            url('justificacion_editar', self.justificacion.pk), url('reporte'), url('alumno', self.alumno.pk), url('ajustes'), url('kiosco'),
        )

    def acciones(self):
        return (
            url('cerrar'), url('dia_guardar'), url('justificacion_anular', self.justificacion.pk), url('justificacion_reactivar', self.justificacion.pk),
            url('dia_sin_clases_crear'), url('dia_sin_clases_eliminar', self.dia_libre.pk),
        )

    def test_anonimo_es_enviado_al_login(self):
        self.client.logout()
        for direccion in self.paginas():
            respuesta = self.client.get(direccion)
            self.assertEqual(respuesta.status_code, 302, direccion)
            self.assertIn('/admin/login/', respuesta['Location'])

    def test_sin_permisos_recibe_403(self):
        self.client.force_login(self.sin_permisos)
        for direccion in self.paginas():
            self.assertEqual(self.client.get(direccion).status_code, 403, direccion)
        for direccion in self.acciones():
            self.assertEqual(self.client.post(direccion).status_code, 403, direccion)
        self.assertTrue(Justificacion.objects.get(pk=self.justificacion.pk).activa)

    def test_las_acciones_solo_aceptan_post(self):
        for direccion in self.acciones():
            self.assertEqual(self.client.get(direccion).status_code, 405, direccion)

    def test_la_pantalla_de_la_entrada_responde_json_sin_sesion_o_sin_permiso(self):
        self.client.logout()
        for direccion, metodo in ((url('registrar_entrada'), self.client.post), (url('kiosco_estado'), self.client.get)):
            respuesta = metodo(direccion, {'codigo': 'AB12CD34'})
            self.assertEqual(respuesta.status_code, 401, direccion)
            self.assertEqual(respuesta.json()['tipo'], 'SESION')
        self.client.force_login(self.sin_permisos)
        respuesta = self.client.post(url('registrar_entrada'), {'codigo': 'AB12CD34'})
        self.assertEqual((respuesta.status_code, respuesta.json()['tipo']), (403, 'PERMISO'))
        self.assertFalse(AsistenciaGeneral.objects.filter(origen='UID').exists())

    def test_cada_seccion_pide_su_permiso(self):
        self.con_permisos('view_asistenciageneral')
        for nombre in ('inicio', 'dia', 'reporte'):
            self.assertEqual(self.client.get(url(nombre)).status_code, 200, nombre)
        self.assertEqual(self.client.get(url('alumno', self.alumno.pk)).status_code, 200)
        for nombre in ('clases', 'justificaciones', 'justificacion_crear', 'ajustes', 'kiosco'):
            self.assertEqual(self.client.get(url(nombre)).status_code, 403, nombre)
        self.con_permisos('view_asistenciamateria')
        self.assertEqual(self.client.get(url('clases')).status_code, 200)
        self.assertEqual(self.client.get(url('clase', self.mat.pk)).status_code, 200)
        self.assertEqual(self.client.get(url('inicio')).status_code, 403)
        self.con_permisos('view_justificacion')
        self.assertEqual(self.client.get(url('justificaciones')).status_code, 200)
        self.assertEqual(self.client.get(url('justificacion_crear')).status_code, 403)
        self.con_permisos('add_justificacion')
        self.assertEqual(self.client.get(url('justificacion_crear')).status_code, 200)
        self.con_permisos('view_configuracionasistencia')
        self.assertEqual(self.client.get(url('ajustes')).status_code, 200)
        self.con_permisos('add_asistenciageneral')
        self.assertEqual(self.client.get(url('kiosco')).status_code, 200)

    def test_cada_accion_pide_su_permiso(self):
        self.con_permisos('view_asistenciageneral', 'add_cierredia')
        self.assertEqual(self.client.post(url('cerrar'), {'alcance': 'pendientes'}).status_code, 302)
        self.assertEqual(self.client.post(url('dia_guardar')).status_code, 403)
        self.con_permisos('view_justificacion', 'delete_justificacion')
        self.assertEqual(self.client.post(url('justificacion_anular', self.justificacion.pk)).status_code, 302)
        self.assertEqual(self.client.post(url('justificacion_reactivar', self.justificacion.pk)).status_code, 403)
        self.con_permisos('view_configuracionasistencia', 'add_dianolectivo')
        self.assertEqual(self.client.post(url('dia_sin_clases_crear'), {}).status_code, 302)
        self.assertEqual(self.client.post(url('dia_sin_clases_eliminar', self.dia_libre.pk)).status_code, 403)

    def test_los_controles_se_muestran_segun_el_permiso(self):
        self.con_permisos('view_asistenciageneral', 'view_asistenciamateria', 'view_justificacion')
        respuesta = self.client.get(url('inicio'))
        self.assertContains(respuesta, url('justificaciones'))
        self.assertNotContains(respuesta, url('ajustes'))
        self.assertNotContains(respuesta, 'Abrir pantalla de entrada')
        self.assertNotContains(respuesta, 'modal-cerrar')


# ---------------------------------------------------------------------------
# Resumen del día
# ---------------------------------------------------------------------------
@PRUEBAS
class InicioTests(BaseAsistenciaTestCase):
    hora = (8, 5)

    def setUp(self):
        super().setUp()
        self.a2 = inscribir_antes(crear_alumno(), self.ciclo, self.grado)
        self.a3 = inscribir_antes(crear_alumno(), self.ciclo, self.grado)
        self.otro = inscribir_antes(crear_alumno(), self.ciclo, crear_grado('PRIMARIA', 5))

    def inicio(self, **consulta):
        respuesta = self.client.get(url('inicio', **consulta))
        self.assertEqual(respuesta.status_code, 200)
        return respuesta

    def test_cuenta_presentes_retardos_faltas_y_quienes_no_han_llegado(self):
        entrar(self.alumno, (7, 45))
        entrar(self.a2.alumno, (8, 25))
        reglas.fijar_asistencia_general(self.a3, lunes(), 'FALTA')
        total = self.inicio().context['total']
        self.assertEqual(total, {'inscritos': 4, 'presentes': 1, 'retardos': 1, 'faltas': 1, 'justificadas': 0, 'sin_registro': 1, 'entraron': 2})

    def test_una_falta_justificada_se_cuenta_aparte(self):
        reglas.fijar_asistencia_general(self.a3, lunes(), 'FALTA')
        Justificacion.objects.create(inscripcion=self.a3, fecha=lunes(), motivo='Cita', justifica_general=True)
        self.assertEqual(self.inicio().context['total']['justificadas'], 1)

    def test_resume_por_grado_en_orden_escolar(self):
        entrar(self.alumno)
        filas = self.inicio().context['resumen']['grados']
        self.assertEqual([(str(f['grado']), f['inscritos'], f['entraron'], f['sin_registro']) for f in filas], [('4° Primaria', 3, 1, 2), ('5° Primaria', 1, 0, 1)])

    def test_porcentaje_de_entrada(self):
        entrar(self.alumno)
        self.assertEqual(self.inicio().context['porcentaje_entrada'], 25)

    def test_no_cuenta_a_quien_no_debe_asistir(self):
        inscribir_antes(crear_alumno(estatus='BAJA'), self.ciclo, self.grado)
        inscribir_antes(crear_alumno(estatus='SUSPENDIDO'), self.ciclo, self.grado)
        self.assertEqual(self.inicio().context['total']['inscritos'], 4)

    def test_elige_otro_dia_y_nunca_muestra_el_futuro(self):
        anterior = lunes() - timedelta(days=7)
        entrar(self.alumno, fecha=anterior)
        self.assertEqual(self.inicio(fecha=anterior.isoformat()).context['total']['entraron'], 1)
        self.assertEqual(self.inicio(fecha=(lunes() + timedelta(days=9)).isoformat()).context['fecha'], lunes())
        self.assertEqual(self.inicio(fecha='basura').context['fecha'], lunes())

    def test_navegacion_entre_dias_habiles(self):
        contexto = self.inicio().context
        self.assertEqual(contexto['anterior'], lunes() - timedelta(days=3))        # el viernes anterior
        self.assertIsNone(contexto['siguiente'])
        self.assertEqual(self.inicio(fecha=(lunes() - timedelta(days=7)).isoformat()).context['siguiente'], lunes() - timedelta(days=6))

    def test_un_dia_sin_clases_lo_dice_y_no_muestra_cifras(self):
        DiaNoLectivo.objects.create(fecha=lunes(), motivo='Consejo técnico')
        respuesta = self.inicio()
        self.assertContains(respuesta, 'No hay clases este día')
        self.assertContains(respuesta, 'Consejo técnico')
        self.assertIsNone(respuesta.context['resumen'])

    def test_un_fin_de_semana_sin_horario_no_es_dia_de_clases(self):
        sabado = lunes() - timedelta(days=2)
        self.assertContains(self.inicio(fecha=sabado.isoformat()), 'No hay clases en fin de semana')

    def test_sin_alumnos_inscritos(self):
        self.inscripcion.activa = self.a2.activa = self.a3.activa = self.otro.activa = False
        for i in (self.inscripcion, self.a2, self.a3, self.otro):
            i.save()
        self.assertContains(self.inicio(), 'No hay estudiantes inscritos este día')

    def test_un_dia_fuera_de_los_ciclos(self):
        self.assertContains(self.inicio(fecha=(lunes() - timedelta(days=700)).isoformat()), 'fuera de los ciclos escolares')

    def test_avisa_de_los_dias_anteriores_sin_cerrar(self):
        entrar(self.alumno, fecha=lunes() - timedelta(days=7))
        respuesta = self.inicio()
        self.assertEqual(respuesta.context['pendientes'], [lunes() - timedelta(days=7)])
        self.assertContains(respuesta, 'día anterior sin cerrar')

    def test_ofrece_cerrar_el_dia_solo_con_permiso(self):
        self.assertTrue(self.inicio().context['puede_cerrar'])
        self.con_permisos('view_asistenciageneral')
        respuesta = self.inicio()
        self.assertFalse(respuesta.context['puede_cerrar'])
        self.assertEqual(respuesta.context['pendientes'], [])

    def test_un_ciclo_cerrado_no_se_puede_cerrar(self):
        cerrado = ciclo_cerrado_de_prueba()
        self.assertFalse(self.inicio(fecha=(cerrado.fecha_inicio + timedelta(days=7)).isoformat()).context['puede_cerrar'])

    def test_muestra_el_cierre_ya_hecho(self):
        reglas.cerrar_dia(lunes(), usuario=self.admin)
        respuesta = self.inicio()
        self.assertEqual(respuesta.context['cierre'].faltas, 4)
        self.assertContains(respuesta, 'Día cerrado')

    def test_consultas_constantes(self):
        with CaptureQueriesContext(connection) as pocas:
            self.inicio()
        for numero in range(6, 14):
            grado = crear_grado('SECUNDARIA', numero)
            inscripcion = inscribir_antes(crear_alumno(), self.ciclo, grado)
            entrar(inscripcion.alumno)
        with CaptureQueriesContext(connection) as muchas:
            self.inicio()
        self.assertEqual(len(muchas), len(pocas))


# ---------------------------------------------------------------------------
# Cerrar el día
# ---------------------------------------------------------------------------
@PRUEBAS
class CerrarTests(BaseAsistenciaTestCase):
    hora = (8, 5)

    def setUp(self):
        super().setUp()
        self.ausente = inscribir_antes(crear_alumno(), self.ciclo, self.grado)
        entrar(self.alumno)

    def cerrar(self, **datos):
        return self.client.post(url('cerrar'), datos, follow=True)

    def test_genera_las_faltas_y_vuelve_al_resumen_con_mensaje(self):
        respuesta = self.cerrar(fecha=lunes().isoformat())
        self.assertRedirects(respuesta, url('inicio', fecha=lunes().isoformat()))
        self.assertContains(respuesta, '1 falta generada')
        self.assertEqual(AsistenciaGeneral.objects.get(inscripcion=self.ausente).estado, 'FALTA')
        self.assertTrue(CierreDia.objects.filter(fecha=lunes(), cerrado_por=self.admin, automatico=False).exists())

    def test_cierra_todos_los_pendientes(self):
        hace_una_semana = lunes() - timedelta(days=7)
        entrar(self.alumno, fecha=hace_una_semana)
        respuesta = self.cerrar(alcance='pendientes')
        self.assertContains(respuesta, 'Se cerraron 1 día')
        self.assertTrue(CierreDia.objects.filter(fecha=hace_una_semana).exists())

    def test_sin_pendientes_avisa(self):
        self.assertContains(self.cerrar(alcance='pendientes'), 'No había días pendientes')

    def test_no_cierra_el_futuro_ni_una_fecha_invalida(self):
        for fecha in ((lunes() + timedelta(days=3)).isoformat(), 'x', ''):
            self.assertContains(self.cerrar(fecha=fecha), 'Elige un día que ya haya empezado', msg_prefix=fecha)
        self.assertFalse(CierreDia.objects.exists())

    def test_no_cierra_un_ciclo_cerrado(self):
        cerrado = ciclo_cerrado_de_prueba()
        fecha = cerrado.fecha_inicio + timedelta(days=7)
        self.assertContains(self.cerrar(fecha=fecha.isoformat()), 'Solo se cierran los días del ciclo actual')

    def test_no_cierra_un_dia_sin_clases(self):
        DiaNoLectivo.objects.create(fecha=lunes(), motivo='Puente')
        self.assertContains(self.cerrar(fecha=lunes().isoformat()), 'Puente')
        self.assertFalse(CierreDia.objects.exists())


# ---------------------------------------------------------------------------
# Pantalla de la entrada
# ---------------------------------------------------------------------------
@PRUEBAS
class KioscoTests(BaseAsistenciaTestCase):
    hora = (8, 5)

    def pantalla(self):
        return self.client.get(url('kiosco'))

    def registrar(self, codigo, modo='uid', cliente=None):
        respuesta = (cliente or self.client).post(url('registrar_entrada'), {'codigo': codigo, 'modo': modo})
        return respuesta, respuesta.json()

    def test_la_pantalla_se_muestra_sin_el_menu(self):
        respuesta = self.pantalla()
        self.assertContains(respuesta, url('registrar_entrada'))
        self.assertContains(respuesta, 'Acerca tu credencial')
        self.assertContains(respuesta, 'Entrada a las 08:00')
        self.assertNotContains(respuesta, 'data-sidebar')

    def test_entrega_la_hora_del_servidor_para_el_reloj(self):
        self.assertContains(self.pantalla(), 'data-ahora="29100"')           # 8:05 en segundos

    def test_un_dia_sin_clases_lo_avisa(self):
        DiaNoLectivo.objects.create(fecha=lunes(), motivo='Puente')
        respuesta = self.pantalla()
        self.assertContains(respuesta, 'Hoy no se registra entrada')
        self.assertContains(respuesta, 'Puente')
        self.assertContains(respuesta, 'data-sin-clases="1"')

    def test_muestra_cuantos_han_entrado_pero_nunca_quienes(self):
        entrar(self.alumno, (7, 40))
        respuesta = self.pantalla()
        self.assertEqual((respuesta.context['estado']['inscritos'], respuesta.context['estado']['entraron']), (1, 1))
        self.assertEqual(set(respuesta.context['estado']), {'fecha', 'ahora', 'inscritos', 'entraron'})
        contenido = respuesta.content.decode()
        for dato in (str(self.alumno), self.alumno.nombre, self.alumno.referencia, self.alumno.uid):
            self.assertNotIn(dato, contenido)
        self.assertNotIn('Últimas entradas', contenido)

    def test_el_resultado_se_quita_solo_y_al_tocarlo(self):
        respuesta = self.pantalla()
        self.assertContains(respuesta, 'data-descartar')            # tocar el resultado lo quita
        self.assertContains(respuesta, 'data-cuenta')              # barra que muestra cuánto falta para que se quite

    # --- registrar -----------------------------------------------------------------------------------
    def test_registra_la_entrada_con_la_credencial(self):
        respuesta, datos = self.registrar('ab12cd34')
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(datos['ok'])
        self.assertEqual((datos['tipo'], datos['estado'], datos['hora'], datos['materias']), ('REGISTRADA', 'PRESENTE', '08:05', 3))
        self.assertEqual(datos['alumno']['nombre'], str(self.alumno))
        self.assertEqual(datos['alumno']['grado'], '4° Primaria')
        self.assertIn('Bienvenido', datos['mensaje'])
        general = AsistenciaGeneral.objects.get()
        self.assertEqual((general.origen, general.registrado_por, general.hora_entrada), ('UID', self.admin, time(8, 5)))
        self.assertEqual(self.estados_de_materias(), {'MAT': 'PRESENTE', 'ESP': 'PRESENTE', 'CIE': 'PRESENTE'})

    def test_registra_con_el_numero_de_referencia(self):
        _, datos = self.registrar(self.alumno.referencia, 'referencia')
        self.assertEqual(datos['tipo'], 'REGISTRADA')
        self.assertEqual(AsistenciaGeneral.objects.get().origen, 'REFERENCIA')

    def test_un_uid_escrito_en_el_campo_de_la_referencia_tambien_funciona(self):
        _, datos = self.registrar('AB12CD34', 'referencia')
        self.assertTrue(datos['ok'])
        self.assertEqual(AsistenciaGeneral.objects.get().origen, 'UID')

    def test_llegar_tarde_es_retardo_y_lo_dice(self):
        self.fijar_ahora(8, 30)
        _, datos = self.registrar('AB12CD34')
        self.assertEqual((datos['ok'], datos['estado']), (True, 'RETARDO'))
        self.assertIn('retardo', datos['mensaje'])
        self.assertEqual(self.estados_de_materias()['MAT'], 'RETARDO')

    def test_un_codigo_desconocido_o_vacio(self):
        for codigo, tipo in (('NOEXISTE', 'NO_ENCONTRADO'), ('', 'VACIO'), ('   ', 'VACIO')):
            respuesta, datos = self.registrar(codigo)
            self.assertEqual((respuesta.status_code, datos['ok'], datos['tipo']), (200, False, tipo), codigo)
            self.assertNotIn('alumno', datos)
        self.assertFalse(AsistenciaGeneral.objects.exists())

    def test_quien_no_esta_activo_no_entra(self):
        suspendido = crear_alumno(uid='SUS1', estatus='SUSPENDIDO')
        inscribir_antes(suspendido, self.ciclo, self.grado)
        _, datos = self.registrar('SUS1')
        self.assertEqual((datos['ok'], datos['tipo']), (False, 'SUSPENDIDO'))
        self.assertIn('dirección', datos['mensaje'])
        self.assertEqual(datos['alumno']['nombre'], str(suspendido))
        self.assertFalse(AsistenciaGeneral.objects.exists())

    def test_sin_inscripcion_en_el_ciclo(self):
        crear_alumno(uid='SIN1')
        _, datos = self.registrar('SIN1')
        self.assertEqual((datos['ok'], datos['tipo']), (False, 'SIN_INSCRIPCION'))

    def test_un_dia_sin_clases_no_registra(self):
        DiaNoLectivo.objects.create(fecha=lunes(), motivo='Puente')
        _, datos = self.registrar('AB12CD34')
        self.assertEqual((datos['ok'], datos['tipo']), (False, 'SIN_CLASES'))

    def test_la_segunda_lectura_no_cambia_nada(self):
        self.registrar('AB12CD34')
        self.fijar_ahora(9, 30)
        _, datos = self.registrar('AB12CD34')
        self.assertEqual((datos['ok'], datos['tipo'], datos['hora']), (True, 'YA_REGISTRADA', '08:05'))
        self.assertEqual(AsistenciaGeneral.objects.count(), 1)
        self.assertEqual(AsistenciaMateria.objects.count(), 3)

    def test_quien_ya_tiene_falta_hoy_es_enviado_a_direccion(self):
        reglas.fijar_asistencia_general(self.inscripcion, lunes(), 'FALTA')
        _, datos = self.registrar('AB12CD34')
        self.assertEqual((datos['ok'], datos['tipo']), (False, 'CON_FALTA'))
        self.assertEqual(AsistenciaGeneral.objects.get().estado, 'FALTA')

    def test_devuelve_los_contadores_actualizados(self):
        otro = inscribir_antes(crear_alumno(uid='OTRO1'), self.ciclo, self.grado)
        _, datos = self.registrar('AB12CD34')
        resumen = datos['resumen']
        self.assertEqual((resumen['inscritos'], resumen['entraron']), (2, 1))
        self.assertEqual(set(resumen), {'fecha', 'ahora', 'inscritos', 'entraron'})        # solo cifras, sin nombres
        self.assertEqual(resumen['ahora'], 29100)
        self.assertEqual(otro.alumno.uid, 'OTRO1')

    def test_cada_resultado_solo_trae_los_datos_de_quien_escaneo(self):
        otro = inscribir_antes(crear_alumno(nombre='Beto', apellido_paterno='Zuñiga', uid='OTRO2'), self.ciclo, self.grado)
        self.registrar('AB12CD34')
        _, datos = self.registrar('OTRO2')
        self.assertEqual(datos['alumno']['nombre'], str(otro.alumno))
        self.assertNotIn(str(self.alumno), str(datos))              # nada del alumno que entró antes

    def test_el_estado_de_la_pantalla(self):
        for i in range(12):
            alumno = crear_alumno()
            inscripcion = inscribir_antes(alumno, self.ciclo, self.grado)
            entrar(alumno, (7, 30 + i))
        respuesta = self.client.get(url('kiosco_estado'))
        datos = respuesta.json()
        self.assertEqual((respuesta.status_code, datos['ok'], datos['inscritos'], datos['entraron'], datos['fecha']), (200, True, 13, 12, lunes().isoformat()))
        self.assertEqual(set(datos), {'ok', 'fecha', 'ahora', 'inscritos', 'entraron'})
        self.assertNotIn(str(inscripcion.alumno), respuesta.content.decode())            # nunca nombres de quienes ya entraron

    def test_las_lecturas_requieren_el_token_csrf(self):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.admin)
        self.assertEqual(cliente.post(url('registrar_entrada'), {'codigo': 'AB12CD34'}).status_code, 403)
        self.assertFalse(AsistenciaGeneral.objects.exists())

    def test_solo_acepta_post_para_registrar(self):
        self.assertEqual(self.client.get(url('registrar_entrada')).status_code, 405)

    # --- cierre automático de los días anteriores ---------------------------------------------------------
    def test_la_primera_entrada_del_dia_cierra_los_dias_anteriores(self):
        ausente = inscribir_antes(crear_alumno(), self.ciclo, self.grado)
        anterior = lunes() - timedelta(days=7)
        entrar(self.alumno, fecha=anterior)
        self.registrar('AB12CD34')
        cierre = CierreDia.objects.get(fecha=anterior)
        self.assertTrue(cierre.automatico)
        self.assertEqual(AsistenciaGeneral.objects.get(inscripcion=ausente, fecha=anterior).estado, 'FALTA')

    def test_el_cierre_automatico_no_se_repite_el_mismo_dia(self):
        anterior = lunes() - timedelta(days=7)
        entrar(self.alumno, fecha=anterior)
        outro = inscribir_antes(crear_alumno(uid='DOS2'), self.ciclo, self.grado)
        with patch('Asistencias.views.cierre_automatico_del_dia', wraps=reglas.cierre_automatico_del_dia) as cierre:
            self.registrar('AB12CD34')
            self.registrar('DOS2')
        self.assertEqual(cierre.call_count, 2)                      # se consulta en cada entrada nueva...
        self.assertEqual(CierreDia.objects.filter(fecha=anterior).count(), 1)   # ...pero el cierre ocurre una sola vez
        self.assertEqual(outro.alumno.uid, 'DOS2')

    def test_un_fallo_al_cerrar_nunca_impide_registrar_la_entrada(self):
        with patch('Asistencias.views.cierre_automatico_del_dia', side_effect=RuntimeError('falla')):
            respuesta, datos = self.registrar('AB12CD34')
        self.assertEqual((respuesta.status_code, datos['ok']), (200, True))
        self.assertTrue(AsistenciaGeneral.objects.exists())

    def test_el_cierre_automatico_se_puede_apagar(self):
        configuracion = ConfiguracionAsistencia.cargar()
        configuracion.cierre_automatico = False
        configuracion.save()
        entrar(self.alumno, fecha=lunes() - timedelta(days=7))
        self.registrar('AB12CD34')
        self.assertFalse(CierreDia.objects.exists())


# ---------------------------------------------------------------------------
# Asistencia general del día
# ---------------------------------------------------------------------------
@PRUEBAS
class DiaTests(BaseAsistenciaTestCase):
    hora = (8, 5)

    def setUp(self):
        super().setUp()
        self.g5 = crear_grado('PRIMARIA', 5)
        materia_en_grado('HIS', self.g5, self.ciclo, inicio=(10, 0), fin=(11, 0))
        self.a2 = inscribir_antes(crear_alumno(nombre='Beto', apellido_paterno='Zuñiga'), self.ciclo, self.grado)
        self.a3 = inscribir_antes(crear_alumno(nombre='Ana', apellido_paterno='Lara'), self.ciclo, self.g5)
        entrar(self.alumno, (7, 45))
        entrar(self.a2.alumno, (8, 25))

    def dia(self, **consulta):
        respuesta = self.client.get(url('dia', **consulta))
        self.assertEqual(respuesta.status_code, 200)
        return respuesta

    def nombres(self, respuesta):
        return [str(i.alumno) for i in respuesta.context['pagina']]

    def test_lista_a_los_alumnos_por_grado_y_nombre(self):
        self.assertEqual(self.nombres(self.dia()), [str(self.alumno), str(self.a2.alumno), str(self.a3.alumno)])

    def test_cada_alumno_trae_su_asistencia_y_el_resumen_de_sus_materias(self):
        filas = {i.alumno_id: i for i in self.dia().context['pagina']}
        general = filas[self.alumno.pk].general
        self.assertEqual((general.estado, general.hora_entrada), ('PRESENTE', time(7, 45)))
        self.assertEqual(filas[self.a2.alumno.pk].general.estado, 'RETARDO')
        self.assertIsNone(filas[self.a3.alumno.pk].general)
        self.assertEqual({k: filas[self.alumno.pk].materias[k] for k in ('total', 'asistidas', 'faltas')}, {'total': 3, 'asistidas': 3, 'faltas': 0})

    def test_filtra_por_grado_estado_y_nombre(self):
        self.assertEqual(self.nombres(self.dia(grado=self.g5.pk)), [str(self.a3.alumno)])
        self.assertEqual(self.nombres(self.dia(estado='RETARDO')), [str(self.a2.alumno)])
        self.assertEqual(self.nombres(self.dia(estado='SIN_REGISTRO')), [str(self.a3.alumno)])
        self.assertEqual(self.nombres(self.dia(q='zuñ')), [str(self.a2.alumno)])
        self.assertEqual(self.nombres(self.dia(q=self.alumno.referencia)), [str(self.alumno)])

    def test_el_resumen_sigue_al_grado_filtrado(self):
        self.assertEqual(self.dia().context['total']['inscritos'], 3)
        self.assertEqual(self.dia(grado=self.grado.pk).context['total']['inscritos'], 2)

    def test_pagina_y_tamano(self):
        for _ in range(25):
            inscribir_antes(crear_alumno(), self.ciclo, self.grado)
        respuesta = self.dia()
        self.assertEqual((respuesta.context['pagina'].paginator.count, len(respuesta.context['pagina'])), (28, 20))
        self.assertEqual(len(self.dia(page=2).context['pagina']), 8)

    def test_una_falta_justificada_se_marca(self):
        reglas.fijar_asistencia_general(self.a3, lunes(), 'FALTA')
        Justificacion.objects.create(inscripcion=self.a3, fecha=lunes(), motivo='Cita', justifica_general=True)
        general = next(i.general for i in self.dia(grado=self.g5.pk).context['pagina'])
        self.assertTrue(general.justificada)
        self.assertContains(self.dia(grado=self.g5.pk), 'Falta justificada')

    def test_un_dia_sin_clases_o_fuera_de_ciclo_no_lista_nada(self):
        DiaNoLectivo.objects.create(fecha=lunes(), motivo='Puente')
        respuesta = self.dia()
        self.assertContains(respuesta, 'No hay clases este día')
        self.assertIsNone(respuesta.context['pagina'])
        self.assertContains(self.dia(fecha=(lunes() - timedelta(days=700)).isoformat()), 'fuera de los ciclos')

    def test_los_dias_pasados_dicen_sin_registro(self):
        respuesta = self.dia(fecha=(lunes() - timedelta(days=7)).isoformat())
        self.assertContains(respuesta, 'Sin registro')

    def test_un_ciclo_cerrado_es_de_solo_lectura(self):
        cerrado = ciclo_cerrado_de_prueba()
        inscribir_antes(crear_alumno(), cerrado, self.grado)
        respuesta = self.dia(fecha=(cerrado.fecha_inicio + timedelta(days=7)).isoformat())
        self.assertFalse(respuesta.context['editable'])
        self.assertNotContains(respuesta, 'modal-asistencia')

    def test_ofrece_corregir_y_justificar(self):
        reglas.fijar_asistencia_general(self.a3, lunes(), 'FALTA')
        respuesta = self.dia()
        self.assertContains(respuesta, 'data-asistencia-editar')
        self.assertContains(respuesta, f'{url("justificacion_crear")}?alumno={self.a3.alumno.pk}')

    def test_consultas_constantes(self):
        with CaptureQueriesContext(connection) as pocas:
            self.dia()
        for _ in range(15):
            inscripcion = inscribir_antes(crear_alumno(), self.ciclo, self.grado)
            entrar(inscripcion.alumno)
        with CaptureQueriesContext(connection) as muchas:
            self.dia()
        self.assertEqual(len(muchas), len(pocas))


@PRUEBAS
class DiaGuardarTests(BaseAsistenciaTestCase):
    hora = (10, 30)

    def setUp(self):
        super().setUp()
        self.destino = url('dia', grado=self.grado.pk)

    def guardar(self, **cambios):
        datos = {'inscripcion': self.inscripcion.pk, 'fecha': lunes().isoformat(), 'estado': 'PRESENTE', 'hora': '', 'observaciones': '', 'next': self.destino}
        datos.update(cambios)
        return self.client.post(url('dia_guardar'), {k: v for k, v in datos.items() if v is not None}, follow=True)

    def test_registra_la_entrada_de_quien_olvido_su_credencial(self):
        respuesta = self.guardar(estado='PRESENTE', hora='07:50', observaciones='  olvidó   su credencial ', propagar='on')
        self.assertRedirects(respuesta, self.destino)
        self.assertContains(respuesta, 'Se guardó la asistencia')
        general = AsistenciaGeneral.objects.get()
        self.assertEqual((general.estado, general.hora_entrada, general.origen, general.registrado_por, general.observaciones),
                         ('PRESENTE', time(7, 50), 'MANUAL', self.admin, 'olvidó su credencial'))
        self.assertEqual(self.estados_de_materias(), {'MAT': 'PRESENTE', 'ESP': 'PRESENTE', 'CIE': 'PRESENTE'})

    def test_sin_hora_se_guarda_la_hora_actual(self):
        self.guardar(estado='RETARDO')
        self.assertEqual(AsistenciaGeneral.objects.get().hora_entrada, time(10, 30))

    def test_sin_hora_en_un_dia_pasado_no_inventa_una(self):
        anterior = lunes() - timedelta(days=7)
        self.guardar(fecha=anterior.isoformat(), estado='PRESENTE')
        self.assertIsNone(AsistenciaGeneral.objects.get(fecha=anterior).hora_entrada)

    def test_una_falta_pasa_a_todas_las_materias_si_se_pide(self):
        entrar(self.alumno, (7, 45))
        self.guardar(estado='FALTA', propagar='on')
        self.assertEqual(AsistenciaGeneral.objects.get().estado, 'FALTA')
        self.assertEqual(set(self.estados_de_materias().values()), {'FALTA'})

    def test_sin_propagar_solo_cambia_la_general(self):
        entrar(self.alumno, (7, 45))
        self.guardar(estado='FALTA')
        self.assertEqual(set(self.estados_de_materias().values()), {'PRESENTE'})

    def test_corrige_un_registro_existente_sin_duplicarlo(self):
        entrar(self.alumno, (7, 45))
        self.guardar(estado='RETARDO', hora='08:20')
        self.assertEqual(AsistenciaGeneral.objects.count(), 1)
        self.assertEqual(AsistenciaGeneral.objects.get().estado, 'RETARDO')

    def test_valida_los_datos(self):
        for cambios in ({'estado': 'XX'}, {'hora': '25:00'}, {'fecha': 'x'}, {'inscripcion': 'abc'}, {'observaciones': 'x' * 300}):
            respuesta = self.guardar(**cambios)
            self.assertContains(respuesta, 'No se guardó', msg_prefix=str(cambios))
        self.assertFalse(AsistenciaGeneral.objects.exists())

    def test_no_guarda_el_futuro_ni_un_dia_sin_clases_ni_un_ciclo_cerrado(self):
        self.assertContains(self.guardar(fecha=(lunes() + timedelta(days=7)).isoformat()), 'ciclo actual que ya empezaron')
        DiaNoLectivo.objects.create(fecha=lunes(), motivo='Puente')
        self.assertContains(self.guardar(), 'Puente')
        cerrado = ciclo_cerrado_de_prueba()
        self.assertContains(self.guardar(fecha=(cerrado.fecha_inicio + timedelta(days=7)).isoformat()), 'no es el ciclo actual')
        self.assertFalse(AsistenciaGeneral.objects.exists())

    def test_solo_alumnos_inscritos_ese_dia(self):
        otro = crear_alumno()
        inscribir_antes(otro, self.ciclo, self.grado, activa=False)
        inscripcion = inscribir_antes(crear_alumno(estatus='BAJA'), self.ciclo, self.grado)
        for inscripcion_id in (inscripcion.pk, 99999):
            self.assertContains(self.guardar(inscripcion=inscripcion_id), 'no tiene una inscripción vigente')
        self.assertFalse(AsistenciaGeneral.objects.exists())

    def test_el_next_solo_acepta_direcciones_de_este_sitio(self):
        for peligroso in ('https://malo.example/', '//malo.example/', 'javascript:alert(1)'):
            respuesta = self.client.post(url('dia_guardar'), {
                'inscripcion': self.inscripcion.pk, 'fecha': lunes().isoformat(), 'estado': 'PRESENTE', 'next': peligroso,
            })
            self.assertRedirects(respuesta, url('dia'), fetch_redirect_response=False, msg_prefix=peligroso)

    def test_crear_pide_el_permiso_de_agregar_y_corregir_el_de_cambiar(self):
        self.con_permisos('view_asistenciageneral', 'change_asistenciageneral')
        self.assertEqual(self.client.post(url('dia_guardar'), {
            'inscripcion': self.inscripcion.pk, 'fecha': lunes().isoformat(), 'estado': 'PRESENTE',
        }).status_code, 403)
        AsistenciaGeneral.objects.create(inscripcion=self.inscripcion, fecha=lunes(), estado='PRESENTE', origen='UID')
        self.assertEqual(self.client.post(url('dia_guardar'), {
            'inscripcion': self.inscripcion.pk, 'fecha': lunes().isoformat(), 'estado': 'RETARDO',
        }).status_code, 302)
        self.assertEqual(AsistenciaGeneral.objects.get().estado, 'RETARDO')
