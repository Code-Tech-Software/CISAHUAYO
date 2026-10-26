"""Retiros anticipados: el aviso del tutor y sus validaciones (permiso vigente, hijos propios, fechas pasadas, horario
del estudiante, duplicados, quién recoge), la consulta y la cancelación en el portal, la salida confirmada por el
personal (por estudiante y una sola vez), las correcciones en la bitácora, el alcance por nivel, los motivos y las
notificaciones. El retiro no toca la asistencia."""
from datetime import time, timedelta
from unittest.mock import patch

from django.test import Client
from django.urls import reverse

from Alumnos.models import AsistenciaGeneral, DiaNoLectivo
from CISAHUAYO import portales
from CISAHUAYO.pruebas import (
    PRUEBAS, BaseTestCase, ciclo_actual_de_prueba, crear_alumno, crear_grado, crear_rol, crear_tutor, crear_usuario,
    inscribir_antes, lunes, materia_en_grado, momento, vincular,
)
from Usuarios.models import PerfilUsuario

from . import reglas, tiempo_real
from .context_processors import datos_de_avisos
from .models import AvisoRetiro, EventoRetiro, MotivoRetiro, Notificacion, RetiroEstudiante

LISTA = reverse('retiros:lista')
NUEVO = reverse('portal_tutores:retiros:crear')


def entrar_al_portal(cliente, tutor):
    sesion = cliente.session
    sesion[portales.CLAVE_DE_SESION] = {'tipo': portales.TUTOR, 'id': tutor.pk, 'huella': portales._huella(portales.TUTOR, tutor)}
    sesion.save()


class Colegio:
    """2.º de primaria (Lucía y Leo, hermanos) y 1.º de secundaria (Zoe). Clases de 8:00 a 13:00 el lunes y el martes.
    Ana es tutora principal de los tres y puede recogerlos; el abuelo Ernesto solo está autorizado para recoger a Lucía;
    Rosa es tía de Leo, sin permiso para gestionar sus retiros. El reloj se detiene el lunes a las 7:00."""

    def armar(self):
        self.ciclo = ciclo_actual_de_prueba()
        self.primaria = crear_grado('PRIMARIA', 2)
        self.secundaria = crear_grado('SECUNDARIA', 1)
        for grado in (self.primaria, self.secundaria):
            for dia in (0, 1):
                materia_en_grado(f'MAT{grado.pk}{dia}', grado, self.ciclo, dia=dia, inicio=(8, 0), fin=(10, 0))
                materia_en_grado(f'ESP{grado.pk}{dia}', grado, self.ciclo, dia=dia, inicio=(10, 30), fin=(13, 0))
        self.lucia = crear_alumno(nombre='Lucía', curp='RETIROS00000000L01')
        self.leo = crear_alumno(nombre='Leo', curp='RETIROS00000000L02')
        self.zoe = crear_alumno(nombre='Zoe', curp='RETIROS00000000Z01')
        self.inscripciones = {
            alumno.pk: inscribir_antes(alumno, self.ciclo, grado)
            for alumno, grado in ((self.lucia, self.primaria), (self.leo, self.primaria), (self.zoe, self.secundaria))
        }
        self.ana = crear_tutor(nombre='Ana', apellido_paterno='Campos', usuario='ana.campos')
        self.ernesto = crear_tutor(nombre='Ernesto', apellido_paterno='Campos', usuario='ernesto', telefono='3530000001')
        self.rosa = crear_tutor(nombre='Rosa', apellido_paterno='Mora', usuario='rosa.mora')
        for alumno in (self.lucia, self.leo, self.zoe):
            vincular(self.ana, alumno, tutor_principal=True, autorizado_recoger=True)
        vincular(self.ernesto, self.lucia, parentesco='ABUELO', autorizado_recoger=True)
        vincular(self.ernesto, self.leo, parentesco='ABUELO')
        vincular(self.rosa, self.leo, parentesco='TIA')
        self.cita = MotivoRetiro.objects.get(nombre='Cita médica')
        self.otro = MotivoRetiro.objects.get(nombre='Otro')

        self.fijar_ahora(7, 0)
        # Personal: atiende primaria (confirma y corrige) y solo secundaria; sin permisos
        self.rol = crear_rol('Recepción de retiros', {'Retiros.consultar', 'Retiros.confirmar', 'Retiros.corregir'})
        self.recepcion = crear_usuario('recepcion', self.rol)
        PerfilUsuario.objects.filter(usuario=self.recepcion).update(niveles_retiros=['PRIMARIA'])
        self.de_secundaria = crear_usuario('secundaria', self.rol)
        PerfilUsuario.objects.filter(usuario=self.de_secundaria).update(niveles_retiros=['SECUNDARIA'])
        self.sin_permiso = crear_usuario('lupita', crear_rol('Solo estudiantes', {'Alumnos.view_alumno'}))

    def fijar_ahora(self, hora, minuto=0, fecha=None):
        reloj = getattr(self, '_reloj', None)
        if reloj:
            reloj.stop()
        self._reloj = patch('django.utils.timezone.now', return_value=momento(hora, minuto, fecha))
        self._reloj.start()
        self.addCleanup(self._reloj.stop)

    def avisar(self, alumnos, hora=time(11, 30), fecha=None, motivo=None, detalles='', recoge=None, tutor=None):
        return reglas.avisar(tutor or self.ana, [a.pk for a in alumnos], fecha or lunes(), hora, motivo or self.cita, detalles,
                             recoge or self.ana)

    def rechazo(self, *args, **kwargs):
        with self.assertRaises(reglas.RetiroRechazado) as contexto:
            self.avisar(*args, **kwargs)
        return ' '.join(contexto.exception.mensajes)


@PRUEBAS
class AvisoDelTutorTests(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()
        self.tutor = Client()
        entrar_al_portal(self.tutor, self.ana)

    def test_avisa_desde_su_portal_y_ve_el_resumen(self):
        pantalla = self.tutor.get(NUEVO)
        self.assertContains(pantalla, 'Lucía')
        self.assertContains(pantalla, '2.º A · Primaria')   # el grupo con su equivalencia y el nivel
        self.assertContains(pantalla, 'Yo (Ana Campos')
        respuesta = self.tutor.post(NUEVO, {
            'alumnos': [self.lucia.pk, self.leo.pk], 'fecha': lunes().isoformat(), 'hora': '11:30', 'motivo': self.cita.pk,
            'detalles': 'Vacuna', 'recoge': self.ana.pk,
        })
        aviso = AvisoRetiro.objects.get()
        self.assertRedirects(respuesta, reverse('portal_tutores:retiros:detalle', args=[aviso.pk]) + '?nuevo=1', fetch_redirect_response=False)
        self.assertRegex(aviso.folio, r'^RA-\d{4}-00001$')
        self.assertEqual(sorted(aviso.estudiantes.values_list('estado', flat=True)), ['AVISADO', 'AVISADO'])
        self.assertEqual(aviso.eventos.get().tipo, EventoRetiro.CREADO)
        resumen = self.tutor.get(respuesta['Location'])
        for texto in (aviso.folio, 'Aviso enviado', 'Lucía', 'Leo', '11:30', 'Cita médica', 'Avisado'):
            self.assertContains(resumen, texto)
        # El personal del nivel recibe la notificación; el de otro nivel, no
        self.assertTrue(Notificacion.objects.filter(usuario=self.recepcion, aviso=aviso).exists())
        self.assertFalse(Notificacion.objects.filter(usuario=self.de_secundaria).exists())
        # Su lista: próximos
        lista = self.tutor.get(reverse('portal_tutores:retiros:lista'))
        self.assertEqual([a.pk for a in lista.context['proximos']], [aviso.pk])

    def test_validaciones_de_fecha_y_horario(self):
        self.assertIn('ya pasaron', self.rechazo([self.lucia], fecha=lunes() - timedelta(days=7)))
        self.fijar_ahora(12, 0)
        self.assertIn('ya pasaron', self.rechazo([self.lucia], hora=time(11, 30)))
        self.fijar_ahora(7, 0)
        self.assertIn('antes de las 13:00', self.rechazo([self.lucia], hora=time(13, 30)))   # ya terminaron sus clases
        self.assertIn('de 08:00 a 13:00', self.rechazo([self.lucia], hora=time(7, 30)))      # aún no empiezan
        self.assertIn('no tiene clases', self.rechazo([self.lucia], fecha=lunes() + timedelta(days=2)))   # miércoles sin horario
        DiaNoLectivo.registrar(lunes() + timedelta(days=1), 'Consejo técnico', ['PRIMARIA'])
        self.assertIn('Consejo técnico', self.rechazo([self.lucia], fecha=lunes() + timedelta(days=1)))
        self.avisar([self.zoe], fecha=lunes() + timedelta(days=1))   # secundaria sí tiene clases ese martes
        self.assertIn('fuera del ciclo', self.rechazo([self.lucia], fecha=lunes() + timedelta(days=400)))

    def test_permisos_hijos_y_quien_recoge(self):
        self.assertIn('Solo puedes avisar', self.rechazo([self.leo], tutor=self.rosa, recoge=self.ana))   # sin permiso vigente
        ajeno = crear_alumno(nombre='Otro', curp='RETIROS00000000X01')
        inscribir_antes(ajeno, self.ciclo, self.primaria)
        self.assertIn('Solo puedes avisar', self.rechazo([ajeno]))                                        # no es su hijo
        self.assertIn('autorización', self.rechazo([self.lucia, self.leo], recoge=self.ernesto))          # no puede recoger a Leo
        self.assertIn('autorización', self.rechazo([self.lucia], recoge=self.rosa))                        # no autorizada
        aviso = self.avisar([self.lucia], recoge=self.ernesto)
        self.assertEqual(aviso.recoge, self.ernesto)
        # el formulario solo ofrece personas ya autorizadas; no hay campo para escribir a alguien nuevo
        pantalla = self.tutor.get(NUEVO)
        self.assertContains(pantalla, 'Ernesto Campos')
        self.assertNotContains(pantalla, 'Rosa Mora')
        self.assertNotIn('nombre_recoge', pantalla.context['form'].fields)

    def test_motivo_y_duplicados(self):
        self.assertIn('requiere que escribas', self.rechazo([self.lucia], motivo=self.otro))
        self.avisar([self.lucia], motivo=self.otro, detalles='Viaje familiar')
        self.assertIn('ya tiene un aviso activo', self.rechazo([self.lucia], hora=time(12, 0)))
        self.cita.activo = False
        self.cita.save()
        self.assertIn('motivo de la lista', self.rechazo([self.leo]))

    def test_solo_ve_y_cancela_lo_suyo(self):
        aviso = self.avisar([self.lucia])
        otro = Client()
        entrar_al_portal(otro, self.ernesto)
        self.assertEqual(otro.get(reverse('portal_tutores:retiros:detalle', args=[aviso.pk])).status_code, 404)
        self.assertEqual(otro.post(reverse('portal_tutores:retiros:cancelar', args=[aviso.pk]), {'retiros': [1]}).status_code, 404)
        # el personal no entra al portal, ni el tutor a la gestión
        self.client.force_login(self.recepcion)
        self.assertEqual(self.client.get(reverse('portal_tutores:retiros:lista')).status_code, 403)
        self.assertEqual(self.tutor.get(LISTA).status_code, 302)

    def test_cancelacion_parcial_y_total(self):
        aviso = self.avisar([self.lucia, self.leo])
        retiro_leo = aviso.estudiantes.get(alumno=self.leo)
        url = reverse('portal_tutores:retiros:cancelar', args=[aviso.pk])
        self.tutor.post(url, {'retiros': [retiro_leo.pk], 'motivo': 'Ya no es necesario'})
        estados = dict(aviso.estudiantes.values_list('alumno__nombre', 'estado'))
        self.assertEqual(estados, {'Lucía': 'AVISADO', 'Leo': 'CANCELADO'})
        retiro_leo.refresh_from_db()
        self.assertEqual(retiro_leo.cancelado_por_tutor, self.ana)
        self.assertTrue(Notificacion.objects.filter(usuario=self.recepcion, titulo='Retiro cancelado por el tutor').exists())
        # confirmada la salida de Lucía, ya no se puede cancelar ni cambiar desde el portal
        reglas.confirmar_salida(aviso.estudiantes.get(alumno=self.lucia), self.recepcion, self.ana, momento(7, 0))
        respuesta = self.tutor.get(url)
        self.assertRedirects(respuesta, reverse('portal_tutores:retiros:detalle', args=[aviso.pk]), fetch_redirect_response=False)
        with self.assertRaises(reglas.RetiroRechazado):
            reglas.cancelar_por_tutor(aviso, self.ana, list(aviso.estudiantes.values_list('pk', flat=True)))
        self.assertEqual(aviso.eventos.filter(tipo=EventoRetiro.CANCELADO).count(), 1)


@PRUEBAS
class GestionDelPersonalTests(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()
        self.aviso = self.avisar([self.lucia, self.leo], hora=time(11, 30))
        self.de_lucia = self.aviso.estudiantes.get(alumno=self.lucia)
        self.de_leo = self.aviso.estudiantes.get(alumno=self.leo)
        self.fijar_ahora(11, 40)
        self.client.force_login(self.recepcion)

    def confirmar(self, retiro, **datos):
        datos = {'recogio': self.ana.pk, 'hora': '11:35', 'verificado': 'on', **datos}
        return self.client.post(reverse('retiros:confirmar', args=[retiro.pk]), datos)

    def test_hoy_busqueda_y_filtros(self):
        hoy = self.client.get(LISTA)
        self.assertEqual([r.alumno for r in hoy.context['pendientes']], [self.leo, self.lucia])
        self.assertContains(hoy, 'Confirmar salida')
        for buscar in ('Leo', 'Campos', self.aviso.folio):
            pantalla = self.client.get(LISTA, {'vista': 'todos', 'q': buscar})
            self.assertTrue(pantalla.context['pagina'].paginator.count, buscar)
        self.assertEqual(self.client.get(LISTA, {'vista': 'todos', 'estado': 'RETIRADO'}).context['pagina'].paginator.count, 0)
        self.assertEqual(self.client.get(LISTA, {'vista': 'todos', 'motivo': self.otro.pk}).context['pagina'].paginator.count, 0)
        self.assertEqual(self.client.get(LISTA, {'vista': 'todos', 'grupo': self.inscripciones[self.lucia.pk].grupo_id}).context['pagina'].paginator.count, 2)

    def test_confirma_cada_estudiante_por_separado_y_una_sola_vez(self):
        detalle = self.client.get(reverse('retiros:detalle', args=[self.aviso.pk]))
        self.assertContains(detalle, 'Quién recoge')
        self.assertContains(detalle, 'con autorización vigente para recoger')
        respuesta = self.confirmar(self.de_lucia, observaciones='Mostró su INE')
        self.assertRedirects(respuesta, reverse('retiros:detalle', args=[self.aviso.pk]), fetch_redirect_response=False)
        self.de_lucia.refresh_from_db()
        self.de_leo.refresh_from_db()
        self.assertEqual((self.de_lucia.estado, self.de_leo.estado), ('RETIRADO', 'AVISADO'))
        self.assertEqual((self.de_lucia.recogio, self.de_lucia.confirmado_por), (self.ana, self.recepcion))
        self.assertEqual(self.de_lucia.salida_en, momento(11, 35))
        self.assertTrue(Notificacion.objects.filter(tutor=self.ana, titulo='Lucía ya salió del colegio').exists())
        # una segunda vez no hace nada
        self.confirmar(self.de_lucia, hora='11:39')
        self.de_lucia.refresh_from_db()
        self.assertEqual(self.de_lucia.salida_en, momento(11, 35))
        with self.assertRaises(reglas.RetiroRechazado):
            reglas.confirmar_salida(self.de_lucia, self.recepcion, self.ana, momento(11, 39))
        self.assertEqual(EventoRetiro.objects.filter(tipo=EventoRetiro.CONFIRMADO).count(), 1)

    def test_verifica_a_quien_recoge_y_la_hora(self):
        self.assertFormError(self.confirmar(self.de_leo, verificado='').context['form'], 'verificado', 'Confirma que verificaste a la persona que recoge.')
        self.assertEqual(self.confirmar(self.de_leo, recogio=self.ernesto.pk).status_code, 200)   # no autorizado para Leo
        respuesta = self.confirmar(self.de_leo, hora='12:30')
        self.assertIn('no puede ser futura', ' '.join(respuesta.context['form'].non_field_errors()))
        self.de_leo.refresh_from_db()
        self.assertEqual(self.de_leo.estado, 'AVISADO')

    def test_correccion_y_cancelacion_quedan_en_la_bitacora(self):
        self.confirmar(self.de_lucia)
        url = reverse('retiros:corregir', args=[self.de_lucia.pk])
        self.assertEqual(self.client.post(url, {'accion': 'corregir', 'recogio': self.ernesto.pk, 'hora': '11:30'}).status_code, 200)   # sin motivo
        self.client.post(url, {'accion': 'corregir', 'recogio': self.ernesto.pk, 'hora': '11:30', 'motivo': 'Se capturó mal'})
        correccion = EventoRetiro.objects.get(tipo=EventoRetiro.CORREGIDO)
        self.assertEqual(correccion.datos['antes']['recogio'], 'Ana Campos')
        self.assertEqual((correccion.datos['despues']['recogio'], correccion.datos['despues']['hora']), ('Ernesto Campos', '11:30'))
        self.client.post(url, {'accion': 'deshacer', 'motivo': 'Se confirmó por error'})
        self.de_lucia.refresh_from_db()
        self.assertEqual((self.de_lucia.estado, self.de_lucia.salida_en), ('AVISADO', None))
        self.assertEqual(Notificacion.objects.filter(tutor=self.ana, titulo__startswith='Se corrigió').count(), 2)
        # cancelar exige motivo y avisa al tutor
        cancelar = reverse('retiros:cancelar', args=[self.aviso.pk])
        self.assertEqual(self.client.post(cancelar, {'retiros': [self.de_leo.pk]}).status_code, 200)
        self.client.post(cancelar, {'retiros': [self.de_leo.pk], 'motivo': 'El tutor llamó para cancelar'})
        self.de_leo.refresh_from_db()
        self.assertEqual((self.de_leo.estado, self.de_leo.cancelado_por_usuario), ('CANCELADO', self.recepcion))
        self.assertTrue(Notificacion.objects.filter(tutor=self.ana, titulo='El colegio canceló un retiro').exists())
        bitacora = self.client.get(reverse('retiros:detalle', args=[self.aviso.pk]))
        for texto in ('Aviso registrado', 'Salida confirmada', 'Corrección', 'Cancelación'):
            self.assertContains(bitacora, texto)

    def test_observaciones_internas_no_las_ve_el_tutor(self):
        self.client.post(reverse('retiros:nota', args=[self.aviso.pk]), {'texto': 'La mamá llamará antes de llegar'})
        self.assertContains(self.client.get(reverse('retiros:detalle', args=[self.aviso.pk])), 'La mamá llamará antes de llegar')
        tutor = Client()
        entrar_al_portal(tutor, self.ana)
        self.assertNotContains(tutor.get(reverse('portal_tutores:retiros:detalle', args=[self.aviso.pk])), 'La mamá llamará')

    def test_alcance_por_nivel_y_permisos(self):
        self.client.force_login(self.de_secundaria)
        self.assertEqual(list(self.client.get(LISTA).context['pendientes']), [])
        self.assertEqual(self.client.get(reverse('retiros:detalle', args=[self.aviso.pk])).status_code, 404)
        self.assertEqual(self.confirmar(self.de_lucia).status_code, 404)
        sin_niveles = crear_usuario('nueva', self.rol)
        self.client.force_login(sin_niveles)
        self.assertContains(self.client.get(LISTA), 'No tienes niveles educativos asignados')
        self.client.force_login(self.sin_permiso)
        self.assertEqual(self.client.get(LISTA).status_code, 403)
        self.assertEqual(self.client.get(reverse('retiros:motivos')).status_code, 403)
        # una cuenta de prefectura con primaria en su alcance consulta y confirma (permisos de su rol)
        from Prefectura.models import AlcancePrefectura
        prefecto = crear_usuario('prefecto', crear_rol('Prefectura de prueba', {'Prefectura.consultar', 'Retiros.consultar', 'Retiros.confirmar'}, es_prefectura=True))
        AlcancePrefectura.objects.create(usuario=prefecto, niveles=['PRIMARIA'])
        self.client.force_login(prefecto)
        self.assertEqual(len(self.client.get(LISTA).context['pendientes']), 2)
        self.assertEqual(self.client.get(reverse('retiros:corregir', args=[self.de_lucia.pk])).status_code, 403)   # sin «corregir»
        # el administrador ve todo el colegio
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('retiros:detalle', args=[self.aviso.pk])).status_code, 200)

    def test_no_cambia_la_asistencia(self):
        self.confirmar(self.de_lucia)
        self.assertFalse(AsistenciaGeneral.objects.exists())
        from Prefectura.models import MovimientoAcceso
        self.assertFalse(MovimientoAcceso.objects.exists())


@PRUEBAS
class MotivosYNotificacionesTests(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()

    def test_los_motivos_se_administran_y_los_usados_no_se_borran(self):
        self.assertEqual(list(MotivoRetiro.objects.values_list('nombre', flat=True)), ['Cita médica', 'Trámite personal', 'Situación familiar', 'Otro'])
        self.assertTrue(self.otro.requiere_explicacion)
        self.client.post(reverse('retiros:motivo_crear'), {'nombre': 'Competencia deportiva', 'orden': 5, 'activo': 'on'})
        nuevo = MotivoRetiro.objects.get(nombre='Competencia deportiva')
        self.assertEqual(MotivoRetiro.objects.first(), nuevo)   # el orden manda
        self.avisar([self.lucia], motivo=nuevo)
        self.client.post(reverse('retiros:motivo_eliminar', args=[nuevo.pk]))
        self.assertTrue(MotivoRetiro.objects.filter(pk=nuevo.pk).exists())
        self.client.post(reverse('retiros:motivo_activo', args=[nuevo.pk]))
        nuevo.refresh_from_db()
        self.assertFalse(nuevo.activo)
        tutor = Client()
        entrar_al_portal(tutor, self.ana)
        self.assertNotIn(nuevo, tutor.get(NUEVO).context['form'].fields['motivo'].queryset)
        sin_usar = MotivoRetiro.objects.get(nombre='Trámite personal')
        self.client.post(reverse('retiros:motivo_eliminar', args=[sin_usar.pk]))
        self.assertFalse(MotivoRetiro.objects.filter(pk=sin_usar.pk).exists())
        self.assertContains(self.client.get(reverse('ajustes:inicio')), reverse('retiros:motivos'))

    def test_niveles_para_retiros_en_la_ficha_del_usuario(self):
        self.assertContains(self.client.get(reverse('usuarios:detalle', args=[self.de_secundaria.pk])), 'Niveles para retiros')
        self.client.post(reverse('usuarios:retiros', args=[self.de_secundaria.pk]), {'niveles': ['PRIMARIA', 'SECUNDARIA']})
        self.assertEqual(PerfilUsuario.de(self.de_secundaria).niveles_retiros, ['PRIMARIA', 'SECUNDARIA'])
        # quien no atiende retiros no tiene esos niveles
        respuesta = self.client.get(reverse('usuarios:retiros', args=[self.sin_permiso.pk]))
        self.assertRedirects(respuesta, reverse('usuarios:detalle', args=[self.sin_permiso.pk]), fetch_redirect_response=False)

    def test_campana_y_tiempo_real(self):
        enviados = []

        class Capa:
            async def group_send(self, grupo, evento):
                enviados.append((grupo, evento))

        with patch.object(tiempo_real, 'get_channel_layer', return_value=Capa()), self.captureOnCommitCallbacks(execute=True):
            aviso = self.avisar([self.lucia])
        grupos = {grupo for grupo, _ in enviados}
        self.assertIn(f'retiros.usuario.{self.recepcion.pk}', grupos)
        self.assertNotIn(f'retiros.usuario.{self.de_secundaria.pk}', grupos)
        self.assertEqual(enviados[0][1]['type'], 'retiro.aviso')
        self.assertEqual(datos_de_avisos(usuario=self.recepcion)['pendientes'], 1)
        self.client.force_login(self.recepcion)
        self.assertEqual(self.client.get(reverse('retiros:resumen')).json()['pendientes'], 1)
        self.assertContains(self.client.get(LISTA), 'data-retiros-lista')   # la sección de la campana
        self.client.get(reverse('retiros:detalle', args=[aviso.pk]))          # al abrirlo queda leída
        self.assertEqual(datos_de_avisos(usuario=self.recepcion)['pendientes'], 0)
        # el tutor recibe la salida confirmada en su grupo
        enviados.clear()
        self.fijar_ahora(11, 40)
        with patch.object(tiempo_real, 'get_channel_layer', return_value=Capa()), self.captureOnCommitCallbacks(execute=True):
            reglas.confirmar_salida(aviso.estudiantes.get(), self.recepcion, self.ana, momento(11, 35))
        self.assertEqual([g for g, _ in enviados], [f'retiros.tutor.{self.ana.pk}'])
        tutor = Client()
        entrar_al_portal(tutor, self.ana)
        self.assertEqual(tutor.get(reverse('portal_tutores:retiros:resumen')).json()['avisos'][0]['titulo'], 'Lucía ya salió del colegio')
