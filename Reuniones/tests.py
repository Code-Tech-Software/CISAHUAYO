"""Reuniones con familias: el registro de la llamada (que nunca confirma una cita), la regla del acompañante directivo
para toda reunión con un docente (al registrar, al confirmar, al iniciar y al terminar, con sustituto o reprogramación),
los cruces de horario (personal, tutores, sala, clases de los docentes y horario de atención), las confirmaciones por
separado, el historial de las reprogramaciones, las inasistencias, la minuta y los acuerdos, los permisos en el
servidor (personal, docentes y tutores, sin notas internas para la familia), las notificaciones sin motivos y que nada
de esto toca calificaciones, asistencias ni conducta."""
from datetime import time, timedelta
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from Alumnos.models import AsistenciaGeneral
from CISAHUAYO import portales
from CISAHUAYO.pruebas import (
    PRUEBAS, BaseTestCase, ciclo_actual_de_prueba, crear_alumno, crear_grado, crear_profesor, crear_rol, crear_tutor, crear_usuario,
    grupo_de, hoy, inscribir_antes, materia_en_grado, momento, vincular,
)
from Conducta.models import RegistroConducta
from Usuarios.models import PerfilUsuario

from . import notificaciones, reglas
from .alcance import ACOMPANAR, CONFIDENCIAL, GESTIONAR, PARTICIPAR, REGISTRAR, Acceso
from .models import (
    AUSENTE, Acuerdo, AdjuntoReunion, CambioDeFecha, EventoReunion, MotivoReunion, NotificacionReunion, ParticipanteReunion, Reunion,
    SalaReunion,
)
from .reglas import ReglaRota

DIRECTIVOS = {PARTICIPAR, GESTIONAR, ACOMPANAR, CONFIDENCIAL}


def entrar_al_portal(cliente, tutor):
    sesion = cliente.session
    sesion[portales.CLAVE_DE_SESION] = {'tipo': portales.TUTOR, 'id': tutor.pk, 'huella': portales._huella(portales.TUTOR, tutor)}
    sesion.save()


class Colegio:
    """Lucía (2° de primaria) y Zoe (1° de secundaria) son hijas de Ana; Leo (2° de primaria) es hijo de Rosa.
    La directora dirige primaria y el subdirector, secundaria; el coordinador coordina los dos niveles. Recepción
    atiende las llamadas. Marta y Pedro son docentes; Marta da clase al grupo de Lucía los lunes de 8:00 a 9:00."""

    def armar(self):
        self.ciclo = ciclo_actual_de_prueba()
        self.primaria = crear_grado('PRIMARIA', 2)
        self.secundaria = crear_grado('SECUNDARIA', 1)
        self.lucia = crear_alumno(nombre='Lucía', curp='REUNION0000000L01')
        self.zoe = crear_alumno(nombre='Zoe', curp='REUNION0000000Z01')
        self.leo = crear_alumno(nombre='Leo', curp='REUNION0000000E01')
        for alumno, grado in ((self.lucia, self.primaria), (self.zoe, self.secundaria), (self.leo, self.primaria)):
            inscribir_antes(alumno, self.ciclo, grado)
        self.ana = crear_tutor(nombre='Ana', apellido_paterno='Campos', usuario='ana.campos', telefono='3531112233')
        self.rosa = crear_tutor(nombre='Rosa', apellido_paterno='Mora', usuario='rosa.mora', telefono='3530000002')
        vincular(self.ana, self.lucia, tutor_principal=True)
        vincular(self.ana, self.zoe, tutor_principal=True)
        vincular(self.rosa, self.leo, tutor_principal=True)

        directivo = crear_rol('Dirección de prueba', DIRECTIVOS)
        self.directora = crear_usuario('directora', directivo)
        self.subdirector = crear_usuario('subdirector', directivo)
        self.coordinador = crear_usuario('coordinador', directivo)
        PerfilUsuario.objects.filter(usuario=self.directora).update(niveles_direccion=['PRIMARIA'])
        PerfilUsuario.objects.filter(usuario=self.subdirector).update(niveles_direccion=['SECUNDARIA'])
        PerfilUsuario.objects.filter(usuario=self.coordinador).update(niveles_bitacora=['PRIMARIA', 'SECUNDARIA'])
        self.recepcion = crear_usuario('recepcion', crear_rol('Recepción de prueba', {REGISTRAR}))
        docente = crear_rol('Docente de prueba', {PARTICIPAR})
        self.marta = crear_usuario('marta', docente)
        self.pedro = crear_usuario('pedro', docente)
        self.prof_marta = crear_profesor(niveles=['PRIMARIA'], usuario=self.marta, telefono='3534440001')
        self.prof_pedro = crear_profesor(niveles=['PRIMARIA', 'SECUNDARIA'], usuario=self.pedro, nombre='Pedro', telefono='3534440002')
        materia_en_grado('MATRF', self.primaria, self.ciclo, dia=0, inicio=(8, 0), fin=(9, 0), grupo=grupo_de(self.primaria), profesor=self.prof_marta)

        self.motivo = MotivoReunion.objects.get(nombre='Desempeño académico')
        self.sala = SalaReunion.objects.get(nombre='Dirección')
        self.otra_sala = SalaReunion.objects.get(nombre='Sala de juntas')
        dias = (7 - hoy().weekday()) % 7 or 7
        self.dia = hoy() + timedelta(days=dias)   # el próximo lunes (nunca hoy)

    # --- atajos -----------------------------------------------------------------------------------------------
    def solicitud(self, docentes=(), acompanante=None, alumnos=None, tutor=None, responsable=None, area=Reunion.DIRECCION):
        return reglas.registrar(tutor=tutor or self.ana, alumnos=alumnos or [self.lucia], telefono='3531112233', area=area, motivo=self.motivo,
                                descripcion='Quiere hablar de las tareas de matemáticas.', usuario=self.recepcion, docentes=docentes,
                                acompanante=acompanante, responsable=responsable)

    def programar(self, reunion, inicio=(10, 0), fin=(10, 30), sala=None, fecha=None):
        return reglas.programar(reunion, fecha=fecha or self.dia, inicio=time(*inicio), fin=time(*fin), sala=sala or self.sala, usuario=self.recepcion)

    def confirmar_tutor(self, reunion):
        return reglas.confirmar_tutor(reunion, medio='TELEFONO', momento=timezone.now(), recibio=self.recepcion, usuario=self.recepcion)

    def confirmar_personal(self, reunion):
        for participante in reunion.participantes.filter(activo=True):
            reglas.confirmar_disponibilidad(participante, disponible=True, usuario=participante.usuario)

    def participante(self, reunion, usuario):
        return reunion.participantes.get(usuario=usuario, activo=True)

    def el_dia_de_la_cita(self, hora=9, minuto=55):
        reloj = patch('django.utils.timezone.now', return_value=momento(hora, minuto, self.dia))
        reloj.start()
        self.addCleanup(reloj.stop)

    def refrescar(self, reunion):
        return Reunion.objects.get(pk=reunion.pk)


# ---------------------------------------------------------------------------
# Registro de la llamada
# ---------------------------------------------------------------------------
@PRUEBAS
class RegistroTests(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()
        self.client.force_login(self.recepcion)

    def datos(self, **cambios):
        datos = {'tutor': self.ana.pk, 'alumnos': [self.lucia.pk], 'telefono': '3531112233', 'telefono_verificado': 'on', 'area': 'DIRECCION',
                 'motivo': self.motivo.pk, 'prioridad': 'ALTA', 'descripcion': 'Pide hablar de las calificaciones.',
                 'observaciones': 'Llamó molesta.', 'propuesta_1_fecha': self.dia.isoformat(), 'propuesta_1_desde': '10:00',
                 'propuesta_1_hasta': '12:00', 'responsable': self.directora.pk}
        datos.update(cambios)
        return {k: v for k, v in datos.items() if v is not None}

    def test_registrar_la_llamada_no_confirma_ninguna_cita(self):
        respuesta = self.client.post(reverse('reuniones:nueva'), self.datos())
        reunion = Reunion.objects.get()
        self.assertRedirects(respuesta, reverse('reuniones:detalle', args=[reunion.pk]), fetch_redirect_response=False)
        self.assertEqual(reunion.folio, f'RF-{reunion.creada:%Y}-{reunion.pk:05d}')
        self.assertEqual((reunion.registrada_por, reunion.estado), (self.recepcion, Reunion.PENDIENTE))
        self.assertIsNone(reunion.fecha)
        self.assertIsNone(reunion.confirmacion_tutor)
        self.assertEqual(reunion.propuestas, [{'fecha': self.dia.isoformat(), 'desde': '10:00', 'hasta': '12:00'}])
        self.assertTrue(reunion.telefono_verificado)
        estudiante = reunion.estudiantes.get()
        self.assertEqual((estudiante.alumno, estudiante.inscripcion.grado), (self.lucia, self.primaria))
        self.assertEqual(list(reunion.tutores.values_list('tutor', 'solicitante')), [(self.ana.pk, True)])
        self.assertTrue(EventoReunion.objects.filter(reunion=reunion, tipo=EventoReunion.REGISTRADA).exists())

    def test_el_formulario_trae_el_telefono_y_los_estudiantes_con_su_nivel(self):
        respuesta = self.client.get(reverse('reuniones:nueva'), {'tutor': self.ana.pk})
        self.assertContains(respuesta, 'value="3531112233"')
        self.assertContains(respuesta, 'Primaria, 2° A')
        self.assertContains(respuesta, 'Secundaria, 1° A')
        busqueda = self.client.get(reverse('reuniones:nueva'), {'q': 'Campos'})
        self.assertContains(busqueda, f'?tutor={self.ana.pk}')
        self.assertNotContains(busqueda, f'?tutor={self.rosa.pk}')

    def test_sin_responsable_queda_solicitada(self):
        self.client.post(reverse('reuniones:nueva'), self.datos(responsable=''))
        self.assertEqual(Reunion.objects.get().estado, Reunion.SOLICITADA)

    def test_solo_estudiantes_del_tutor(self):
        respuesta = self.client.post(reverse('reuniones:nueva'), self.datos(alumnos=[self.leo.pk]))
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Reunion.objects.exists())

    def test_con_un_docente_se_exige_el_acompanante_o_dejarlo_pendiente(self):
        sin = self.client.post(reverse('reuniones:nueva'), self.datos(area='DOCENTE', docentes=[self.marta.pk]))
        self.assertEqual(sin.status_code, 200)
        self.assertIn('acompanante', sin.context['form'].errors)
        self.assertFalse(Reunion.objects.exists())
        self.client.post(reverse('reuniones:nueva'), self.datos(area='DOCENTE', docentes=[self.marta.pk], acompanante_despues='on'))
        reunion = Reunion.objects.get()
        self.assertEqual(reunion.estado, Reunion.PENDIENTE)
        self.assertTrue(reglas.acompanamiento_pendiente(reunion))
        self.client.post(reverse('reuniones:nueva'), self.datos(area='DOCENTE', docentes=[self.marta.pk], acompanante=self.directora.pk))
        conacompanante = Reunion.objects.latest('pk')
        self.assertEqual(set(conacompanante.participantes.values_list('usuario', 'papel')),
                         {(self.marta.pk, 'DOCENTE'), (self.directora.pk, 'ACOMPANANTE')})
        self.assertEqual(reglas.acompanamiento_pendiente(conacompanante), [])

    def test_el_acompanante_debe_estar_autorizado_para_ese_nivel(self):
        with self.assertRaises(ReglaRota):
            self.solicitud(docentes=[self.marta], acompanante=self.subdirector)            # dirige secundaria, Lucía es de primaria
        with self.assertRaises(ReglaRota):
            self.solicitud(docentes=[self.marta], acompanante=self.recepcion)              # sin el permiso de acompañar
        reunion = self.solicitud(docentes=[self.pedro], acompanante=self.subdirector, alumnos=[self.zoe])
        self.assertEqual(reglas.acompanamiento_pendiente(reunion), [])


# ---------------------------------------------------------------------------
# Acompañante directivo, confirmaciones y cruces
# ---------------------------------------------------------------------------
@PRUEBAS
class AcompananteTests(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()

    def test_una_cita_con_docente_no_se_confirma_sin_acompanante(self):
        reunion = self.solicitud(docentes=[self.marta], area=Reunion.DOCENTE)
        self.programar(reunion)
        self.confirmar_tutor(reunion)
        self.confirmar_personal(reunion)
        reunion = self.refrescar(reunion)
        self.assertEqual(reunion.estado, Reunion.PROGRAMADA)
        self.assertTrue(any('acompañante' in falta for falta in reglas.faltantes(reunion)))
        # Con el acompañante asignado, falta que confirme su disponibilidad
        reglas.definir_participantes(reunion, docentes=[self.marta], acompanantes=[self.directora], personal=[], responsable=self.directora,
                                     tutores=[], usuario=self.directora)
        reunion = self.refrescar(reunion)
        self.assertEqual(reunion.estado, Reunion.PROGRAMADA)
        reglas.confirmar_disponibilidad(self.participante(reunion, self.directora), disponible=True, usuario=self.directora)
        self.assertEqual(self.refrescar(reunion).estado, Reunion.CONFIRMADA)

    def test_no_se_confirma_si_el_acompanante_no_esta_libre(self):
        otra = self.solicitud(responsable=self.coordinador, alumnos=[self.zoe])
        self.programar(otra, inicio=(12, 0), fin=(12, 30), sala=self.otra_sala)
        reunion = self.solicitud(docentes=[self.marta], acompanante=self.coordinador, area=Reunion.DOCENTE)
        self.programar(reunion)
        # Después de programarla, al acompañante le asignan una clase a esa hora: al confirmar se revisa su disponibilidad
        profesor = crear_profesor(niveles=['PRIMARIA'], usuario=self.coordinador, nombre='Coordinador', telefono='3534440003')
        materia_en_grado('CIERF', self.primaria, self.ciclo, dia=self.dia.weekday(), inicio=(10, 0), fin=(11, 0),
                         grupo=grupo_de(self.primaria), profesor=profesor)
        with self.assertRaises(ReglaRota) as error:
            reglas.confirmar_disponibilidad(self.participante(reunion, self.coordinador), disponible=True, usuario=self.coordinador)
        self.assertIn('tiene clase', ' '.join(error.exception.mensajes))
        self.assertEqual(self.participante(reunion, self.coordinador).confirmacion, ParticipanteReunion.PENDIENTE)
        # Y no se puede mover la cita a la hora de otra reunión del acompañante
        with self.assertRaises(ReglaRota) as error:
            reglas.reprogramar(reunion, fecha=self.dia, inicio=time(12, 0), fin=time(12, 30), sala=self.sala, motivo='Lo pidió la familia',
                               usuario=self.recepcion)
        self.assertIn('ya tiene otra reunión', ' '.join(error.exception.mensajes))

    def test_si_el_acompanante_deja_de_estar_disponible_la_cita_vuelve_a_pendiente(self):
        reunion = self.solicitud(docentes=[self.marta], acompanante=self.directora, area=Reunion.DOCENTE)
        self.programar(reunion)
        self.confirmar_tutor(reunion)
        self.confirmar_personal(reunion)
        self.assertEqual(self.refrescar(reunion).estado, Reunion.CONFIRMADA)
        reglas.confirmar_disponibilidad(self.participante(reunion, self.directora), disponible=False, nota='Junta de consejo', usuario=self.directora)
        reunion = self.refrescar(reunion)
        self.assertEqual(reunion.estado, Reunion.PROGRAMADA)
        self.assertTrue(reunion.eventos.filter(tipo=EventoReunion.PENDIENTE_CONFIRMAR).exists())
        # Sin nota no se puede decir que no está disponible
        with self.assertRaises(ReglaRota):
            reglas.confirmar_disponibilidad(self.participante(reunion, self.marta), disponible=False, usuario=self.marta)

    def test_quitar_al_acompanante_exige_reemplazo_antes_de_seguir_confirmada(self):
        reunion = self.solicitud(docentes=[self.marta], acompanante=self.directora, area=Reunion.DOCENTE)
        self.programar(reunion)
        self.confirmar_tutor(reunion)
        self.confirmar_personal(reunion)
        reglas.definir_participantes(reunion, docentes=[self.marta], acompanantes=[], personal=[], responsable=None, tutores=[],
                                     usuario=self.directora)
        reunion = self.refrescar(reunion)
        self.assertEqual(reunion.estado, Reunion.PROGRAMADA)
        self.assertTrue(reglas.acompanamiento_pendiente(reunion))
        quitada = reunion.participantes.get(usuario=self.directora)
        self.assertFalse(quitada.activo)   # queda en el historial

    def test_un_acompanante_comun_para_varios_docentes_presente_toda_la_reunion(self):
        reunion = self.solicitud(docentes=[self.marta, self.pedro], acompanante=self.directora, area=Reunion.DOCENTE)
        self.programar(reunion)
        self.confirmar_tutor(reunion)
        self.confirmar_personal(reunion)
        self.assertEqual(self.refrescar(reunion).estado, Reunion.CONFIRMADA)
        self.el_dia_de_la_cita()
        presentes = set(reunion.participantes.filter(activo=True).values_list('pk', flat=True))
        reglas.iniciar(reunion, presentes=presentes, tutores_presentes=set(reunion.tutores.values_list('pk', flat=True)), usuario=self.directora)
        reunion = self.refrescar(reunion)
        datos = {'inicio_real': time(10, 0), 'fin_real': time(10, 40), 'temas': 'Tareas', 'resumen': 'Se revisaron las tareas.',
                 'notas_internas': 'Nada'}
        with self.assertRaises(ReglaRota):
            reglas.finalizar(reunion, datos=datos, presentes_toda=set(), usuario=self.directora, puede_confidencial=True)
        acompanante = self.participante(reunion, self.directora)
        reglas.finalizar(reunion, datos=datos, presentes_toda={acompanante.pk}, usuario=self.directora, puede_confidencial=True)
        reunion = self.refrescar(reunion)
        self.assertEqual(reunion.estado, Reunion.REALIZADA)
        self.assertTrue(self.participante(reunion, self.directora).presente_toda)


@PRUEBAS
class RealizacionTests(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()
        self.reunion = self.solicitud(docentes=[self.marta], acompanante=self.directora, area=Reunion.DOCENTE)
        self.programar(self.reunion)
        self.confirmar_tutor(self.reunion)
        self.confirmar_personal(self.reunion)

    def test_sin_acompanante_presente_no_se_inicia_con_un_docente(self):
        self.el_dia_de_la_cita()
        marta = self.participante(self.reunion, self.marta)
        tutores = set(self.reunion.tutores.values_list('pk', flat=True))
        with self.assertRaises(ReglaRota) as error:
            reglas.iniciar(self.reunion, presentes={marta.pk}, tutores_presentes=tutores, usuario=self.directora)
        self.assertIn('sustituto', ' '.join(error.exception.mensajes))
        self.assertEqual(self.refrescar(self.reunion).estado, Reunion.CONFIRMADA)

    def test_si_falta_el_acompanante_se_asigna_un_sustituto_autorizado_y_libre(self):
        self.el_dia_de_la_cita()
        ausente = self.participante(self.reunion, self.directora)
        with self.assertRaises(ReglaRota):    # no autorizado para primaria
            reglas.asignar_sustituto(self.reunion, nuevo=self.subdirector, ausente=ausente, motivo='No llegó', usuario=self.coordinador)
        with self.assertRaises(ReglaRota):    # sin motivo
            reglas.asignar_sustituto(self.reunion, nuevo=self.coordinador, ausente=ausente, motivo='', usuario=self.coordinador)
        reglas.asignar_sustituto(self.reunion, nuevo=self.coordinador, ausente=ausente, motivo='No llegó', usuario=self.coordinador)
        reunion = self.refrescar(self.reunion)
        ausente.refresh_from_db()
        self.assertFalse(ausente.activo)
        self.assertEqual(ausente.asistencia, AUSENTE)
        sustituto = self.participante(reunion, self.coordinador)
        self.assertEqual((sustituto.papel, sustituto.sustituye_a), (ParticipanteReunion.ACOMPANANTE, ausente))
        presentes = set(reunion.participantes.filter(activo=True).values_list('pk', flat=True))
        reglas.iniciar(reunion, presentes=presentes, tutores_presentes=set(reunion.tutores.values_list('pk', flat=True)), usuario=self.coordinador)
        self.assertEqual(self.refrescar(reunion).estado, Reunion.EN_CURSO)

    def test_o_se_reprograma(self):
        reglas.reprogramar(self.reunion, fecha=self.dia + timedelta(days=1), inicio=time(10, 0), fin=time(10, 30), sala=self.sala,
                           motivo='El acompañante no podrá asistir', usuario=self.recepcion)
        reunion = self.refrescar(self.reunion)
        self.assertEqual(reunion.estado, Reunion.PROGRAMADA)
        self.assertIsNone(reunion.confirmacion_tutor)
        self.assertEqual(set(reunion.participantes.filter(activo=True).values_list('confirmacion', flat=True)), {ParticipanteReunion.PENDIENTE})

    def test_inasistencia_registra_quien_falto(self):
        self.el_dia_de_la_cita(hora=11)
        tutor = self.reunion.tutores.get()
        docente = self.participante(self.reunion, self.marta)
        with self.assertRaises(ReglaRota):
            reglas.marcar_inasistencia(self.reunion, tutores_ausentes=set(), participantes_ausentes=set(), nota='', usuario=self.directora)
        reglas.marcar_inasistencia(self.reunion, tutores_ausentes={tutor.pk}, participantes_ausentes={docente.pk}, nota='No llegaron',
                                   usuario=self.directora)
        reunion = self.refrescar(self.reunion)
        self.assertEqual(reunion.estado, Reunion.NO_REALIZADA)
        self.assertCountEqual(reglas.quienes_faltaron(reunion), [('Ana Campos', 'Tutor'), ('Marta Prueba', 'Docente')])
        siguiente = reglas.programar_siguiente(reunion, usuario=self.directora)
        self.assertEqual((siguiente.reunion_anterior, siguiente.estado), (reunion, Reunion.PENDIENTE))


@PRUEBAS
class CrucesTests(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()
        self.primera = self.solicitud(responsable=self.directora)
        self.programar(self.primera)

    def rechaza(self, reunion, **horario):
        datos = {'inicio': (10, 15), 'fin': (10, 45), 'sala': self.otra_sala, **horario}
        with self.assertRaises(ReglaRota) as error:
            self.programar(reunion, **datos)
        return ' '.join(error.exception.mensajes)

    def test_la_misma_sala_no_se_cruza(self):
        otra = self.solicitud(responsable=self.coordinador, alumnos=[self.zoe], tutor=self.ana)
        otra_familia = reglas.registrar(tutor=self.rosa, alumnos=[self.leo], telefono='1', area=Reunion.DIRECCION, motivo=self.motivo,
                                        descripcion='x', usuario=self.recepcion, responsable=self.coordinador)
        self.assertIn('está ocupada', self.rechaza(otra_familia, sala=self.sala))
        self.programar(otra_familia, inicio=(10, 30), fin=(11, 0), sala=self.sala)   # justo al terminar: sí
        self.assertIn('Ana Campos ya tiene otra reunión', self.rechaza(otra, sala=self.otra_sala))   # el mismo tutor

    def test_el_personal_no_se_cruza(self):
        otra = reglas.registrar(tutor=self.rosa, alumnos=[self.leo], telefono='1', area=Reunion.DIRECCION, motivo=self.motivo,
                                descripcion='x', usuario=self.recepcion, responsable=self.directora)
        self.assertIn('Directora Prueba ya tiene otra reunión', self.rechaza(otra))

    def test_las_clases_de_los_docentes_y_el_horario_de_atencion(self):
        otra = reglas.registrar(tutor=self.rosa, alumnos=[self.leo], telefono='1', area=Reunion.DOCENTE, motivo=self.motivo, descripcion='x',
                                usuario=self.recepcion, docentes=[self.marta], acompanante=self.coordinador)
        self.assertIn('tiene clase de Matrf', self.rechaza(otra, inicio=(8, 30), fin=(9, 0)))
        self.assertIn('horario de atención', self.rechaza(otra, inicio=(16, 0), fin=(16, 30)))
        self.assertIn('no es día de atención', self.rechaza(otra, fecha=self.dia + timedelta(days=5)))
        self.assertIn('ya pasó', self.rechaza(otra, fecha=hoy() - timedelta(days=1)))
        self.programar(otra, inicio=(9, 0), fin=(9, 30), sala=self.otra_sala)

    def test_una_reunion_cancelada_libera_su_horario(self):
        reglas.cancelar(self.primera, motivo='La familia ya no puede', usuario=self.directora)
        otra = reglas.registrar(tutor=self.rosa, alumnos=[self.leo], telefono='1', area=Reunion.DIRECCION, motivo=self.motivo,
                                descripcion='x', usuario=self.recepcion, responsable=self.directora)
        self.programar(otra)
        self.assertEqual(self.refrescar(otra).estado, Reunion.PROGRAMADA)


@PRUEBAS
class HistorialTests(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()

    def test_reprogramar_conserva_el_historial(self):
        reunion = self.solicitud(responsable=self.directora)
        self.programar(reunion)
        with self.assertRaises(ReglaRota):
            reglas.reprogramar(reunion, fecha=self.dia, inicio=time(11, 0), fin=time(11, 30), sala=self.sala, motivo='', usuario=self.recepcion)
        reglas.reprogramar(reunion, fecha=self.dia, inicio=time(11, 0), fin=time(11, 30), sala=self.sala, motivo='Lo pidió la mamá', usuario=self.recepcion)
        reglas.reprogramar(reunion, fecha=self.dia + timedelta(days=1), inicio=time(9, 0), fin=time(9, 30), sala=self.otra_sala,
                           motivo='La directora tiene junta', usuario=self.directora)
        cambios = list(CambioDeFecha.objects.filter(reunion=reunion))
        self.assertEqual([(c.fecha_anterior, c.inicio_anterior, c.fecha_nueva, c.inicio_nuevo, c.motivo, c.usuario) for c in cambios], [
            (self.dia, time(10, 0), self.dia, time(11, 0), 'Lo pidió la mamá', self.recepcion),
            (self.dia, time(11, 0), self.dia + timedelta(days=1), time(9, 0), 'La directora tiene junta', self.directora),
        ])
        self.assertEqual(cambios[1].sala_anterior, self.sala)
        self.assertEqual(reunion.eventos.filter(tipo=EventoReunion.REPROGRAMADA).count(), 2)

    def test_la_minuta_y_los_acuerdos_con_su_seguimiento(self):
        reunion = self.solicitud(responsable=self.directora)
        self.programar(reunion)
        self.el_dia_de_la_cita()
        reglas.iniciar(reunion, presentes=set(reunion.participantes.values_list('pk', flat=True)),
                       tutores_presentes=set(reunion.tutores.values_list('pk', flat=True)), usuario=self.directora)
        reglas.finalizar(self.refrescar(reunion), datos={'inicio_real': time(10, 0), 'fin_real': time(10, 30), 'temas': 'T', 'resumen': 'R',
                                                         'notas_internas': 'Secreto'}, presentes_toda=set(), usuario=self.directora,
                         puede_confidencial=True)
        reunion = self.refrescar(reunion)
        acuerdo = reglas.guardar_acuerdo(reunion, datos={'descripcion': 'Revisar tareas', 'quien': 'FAMILIA', 'responsable': self.directora,
                                                         'responsable_texto': '', 'fecha_limite': hoy() - timedelta(days=1), 'compartido': True},
                                         usuario=self.directora)
        self.assertEqual(acuerdo.estado_actual, Acuerdo.VENCIDO)
        reglas.seguir_acuerdo(acuerdo, estado=Acuerdo.EN_PROCESO, nota='Ya empezó', usuario=self.directora)
        reglas.seguir_acuerdo(acuerdo, estado=Acuerdo.CUMPLIDO, nota='Entregó todo', usuario=self.directora)
        acuerdo.refresh_from_db()
        self.assertEqual(acuerdo.estado_actual, Acuerdo.CUMPLIDO)
        self.assertEqual(acuerdo.seguimientos.count(), 2)
        self.assertEqual(reunion.minuta.notas_internas, 'Secreto')

    def test_no_toca_calificaciones_asistencias_ni_conducta(self):
        antes = (AsistenciaGeneral.objects.count(), RegistroConducta.objects.count())
        reunion = self.solicitud(docentes=[self.marta], acompanante=self.directora, area=Reunion.DOCENTE)
        self.programar(reunion)
        self.confirmar_tutor(reunion)
        self.confirmar_personal(reunion)
        self.el_dia_de_la_cita()
        reglas.marcar_inasistencia(self.refrescar(reunion), tutores_ausentes=set(reunion.tutores.values_list('pk', flat=True)),
                                   participantes_ausentes=set(), nota='', usuario=self.directora)
        self.assertEqual((AsistenciaGeneral.objects.count(), RegistroConducta.objects.count()), antes)


# ---------------------------------------------------------------------------
# Permisos y vistas
# ---------------------------------------------------------------------------
@PRUEBAS
class PermisosTests(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()
        self.reunion = self.solicitud(docentes=[self.marta], acompanante=self.directora, area=Reunion.DOCENTE)
        self.reunion.observaciones_internas = 'OBSERVACION-INTERNA'
        self.reunion.save()
        self.programar(self.reunion)
        self.ajena = reglas.registrar(tutor=self.rosa, alumnos=[self.leo], telefono='1', area=Reunion.DIRECCION, motivo=self.motivo,
                                      descripcion='De otra familia', usuario=self.recepcion, responsable=self.coordinador)
        self.de_secundaria = self.solicitud(alumnos=[self.zoe], responsable=self.subdirector)

    def realizar(self):
        self.confirmar_tutor(self.reunion)
        self.confirmar_personal(self.reunion)
        self.el_dia_de_la_cita()
        reglas.iniciar(self.reunion, presentes=set(self.reunion.participantes.values_list('pk', flat=True)),
                       tutores_presentes=set(self.reunion.tutores.values_list('pk', flat=True)), usuario=self.directora)
        reglas.finalizar(self.refrescar(self.reunion), datos={'inicio_real': time(10, 0), 'fin_real': time(10, 30), 'temas': 'TEMAS-VISIBLES',
                                                              'resumen': 'RESUMEN-VISIBLE', 'notas_internas': 'NOTA-CONFIDENCIAL'},
                         presentes_toda={self.participante(self.reunion, self.directora).pk}, usuario=self.directora, puede_confidencial=True)
        base = {'quien': 'FAMILIA', 'responsable': self.directora, 'responsable_texto': '', 'fecha_limite': self.dia}
        reglas.guardar_acuerdo(self.refrescar(self.reunion), datos={**base, 'descripcion': 'ACUERDO-COMPARTIDO', 'compartido': True}, usuario=self.directora)
        reglas.guardar_acuerdo(self.refrescar(self.reunion), datos={**base, 'descripcion': 'ACUERDO-PRIVADO', 'compartido': False}, usuario=self.directora)

    def test_el_alcance_de_cada_cuenta(self):
        self.assertCountEqual(Acceso(self.recepcion).reuniones(), [self.reunion, self.ajena, self.de_secundaria])   # atiende llamadas
        self.assertCountEqual(Acceso(self.directora).reuniones(), [self.reunion, self.ajena])                    # primaria
        self.assertCountEqual(Acceso(self.subdirector).reuniones(), [self.de_secundaria])                        # secundaria
        self.assertCountEqual(Acceso(self.marta).reuniones(), [self.reunion])                                    # solo donde participa
        self.assertFalse(Acceso(self.subdirector).gestiona_reunion(self.reunion))

    def test_un_docente_solo_ve_sus_reuniones_y_sin_lo_interno(self):
        self.client.force_login(self.marta)
        self.assertEqual(self.client.get(reverse('reuniones:detalle', args=[self.ajena.pk])).status_code, 404)
        detalle = self.client.get(reverse('reuniones:detalle', args=[self.reunion.pk]))
        self.assertContains(detalle, 'Confirmar mi disponibilidad')
        self.assertNotContains(detalle, 'OBSERVACION-INTERNA')
        self.assertNotContains(detalle, reverse('reuniones:confirmar_tutor', args=[self.reunion.pk]))
        # El servidor niega lo que no le toca, aunque se teclee la dirección
        for nombre in ('programar', 'reprogramar', 'confirmar_tutor', 'participantes', 'iniciar', 'cancelar', 'sustituto'):
            self.assertEqual(self.client.get(reverse(f'reuniones:{nombre}', args=[self.reunion.pk])).status_code, 403, nombre)
        self.assertEqual(self.client.get(reverse('reuniones:inicio')).status_code, 403)
        respuesta = self.client.post(reverse('reuniones:disponibilidad', args=[self.reunion.pk]), {'disponible': 'si'})
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(self.participante(self.reunion, self.marta).confirmacion, ParticipanteReunion.CONFIRMADA)

    def test_quien_atiende_llamadas_no_ve_notas_confidenciales(self):
        self.realizar()
        self.client.force_login(self.recepcion)
        detalle = self.client.get(reverse('reuniones:detalle', args=[self.reunion.pk]))
        self.assertContains(detalle, 'RESUMEN-VISIBLE')
        self.assertContains(detalle, 'OBSERVACION-INTERNA')
        self.assertNotContains(detalle, 'NOTA-CONFIDENCIAL')
        self.assertEqual(self.client.get(reverse('reuniones:minuta', args=[self.reunion.pk]), {'version': 'interna'}).status_code, 403)
        self.assertEqual(self.client.get(reverse('reuniones:iniciar', args=[self.reunion.pk])).status_code, 403)
        self.client.force_login(self.directora)
        self.assertContains(self.client.get(reverse('reuniones:detalle', args=[self.reunion.pk])), 'NOTA-CONFIDENCIAL')
        self.assertContains(self.client.get(reverse('reuniones:minuta', args=[self.reunion.pk]), {'version': 'interna'}), 'NOTA-CONFIDENCIAL')

    def test_un_tutor_solo_ve_sus_citas_sin_notas_internas(self):
        self.realizar()
        self.client.logout()
        entrar_al_portal(self.client, self.ana)
        lista = self.client.get(reverse('portal_tutores:reuniones:lista'))
        self.assertContains(lista, reverse('portal_tutores:reuniones:detalle', args=[self.reunion.pk]))
        self.assertNotContains(lista, reverse('portal_tutores:reuniones:detalle', args=[self.ajena.pk]))
        detalle = self.client.get(reverse('portal_tutores:reuniones:detalle', args=[self.reunion.pk]))
        for privado in ('NOTA-CONFIDENCIAL', 'OBSERVACION-INTERNA', 'ACUERDO-PRIVADO'):
            self.assertNotContains(detalle, privado)
        self.assertContains(detalle, 'ACUERDO-COMPARTIDO')
        minuta = self.client.get(reverse('portal_tutores:reuniones:minuta', args=[self.reunion.pk]))
        self.assertContains(minuta, 'RESUMEN-VISIBLE')
        self.assertContains(minuta, 'ACUERDO-COMPARTIDO')
        for privado in ('NOTA-CONFIDENCIAL', 'ACUERDO-PRIVADO', 'versión interna'):
            self.assertNotContains(minuta, privado)
        self.assertEqual(self.client.get(reverse('portal_tutores:reuniones:detalle', args=[self.ajena.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('portal_tutores:reuniones:minuta', args=[self.ajena.pk])).status_code, 404)
        # Otra familia no ve la cita de Ana
        self.client.logout()
        entrar_al_portal(self.client, self.rosa)
        self.assertEqual(self.client.get(reverse('portal_tutores:reuniones:detalle', args=[self.reunion.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('reuniones:detalle', args=[self.reunion.pk])).status_code, 302)   # no es del personal

    def test_el_tutor_confirma_desde_su_portal(self):
        self.client.logout()
        entrar_al_portal(self.client, self.ana)
        self.client.post(reverse('portal_tutores:reuniones:confirmar', args=[self.reunion.pk]))
        reunion = self.refrescar(self.reunion)
        self.assertEqual(reunion.confirmacion_tutor.medio, 'PORTAL')
        self.assertEqual(reunion.estado, Reunion.PROGRAMADA)   # falta el personal
        entrar_al_portal(self.client, self.rosa)
        self.assertEqual(self.client.post(reverse('portal_tutores:reuniones:confirmar', args=[self.reunion.pk])).status_code, 404)

    def test_la_minuta_no_dice_firmada_sin_evidencia(self):
        self.realizar()
        self.client.force_login(self.directora)
        self.assertContains(self.client.get(reverse('reuniones:minuta', args=[self.reunion.pk])), 'Pendiente de firma')
        pdf = SimpleUploadedFile('minuta-firmada.pdf', b'%PDF-1.4 firmada', content_type='application/pdf')
        reglas.agregar_documentos(self.refrescar(self.reunion), archivos=[(pdf, 'application/pdf')], clase=AdjuntoReunion.FIRMA,
                                  compartido=False, usuario=self.directora)
        minuta = self.client.get(reverse('reuniones:minuta', args=[self.reunion.pk]))
        self.assertContains(minuta, 'Se registró la evidencia de firma')
        self.assertNotContains(minuta, 'Pendiente de firma')

    def test_las_pantallas_responden(self):
        self.realizar()
        self.client.force_login(self.admin)
        rutas = [reverse('reuniones:inicio'), reverse('reuniones:lista'), reverse('reuniones:compromisos'),
                 reverse('reuniones:detalle', args=[self.reunion.pk]), reverse('reuniones:estudiante', args=[self.lucia.pk]),
                 reverse('reuniones:ajustes'), reverse('reuniones:nueva')]
        rutas += [f'{reverse("reuniones:agenda")}?vista={v}&fecha={self.dia:%Y-%m-%d}' for v in ('dia', 'semana', 'mes')]
        rutas += [f'{reverse("reuniones:lista")}?nivel=PRIMARIA&estado=ABIERTAS&prioridad=NORMAL&tutor=Campos&estudiante=Lucía',
                  f'{reverse("reuniones:inicio")}?nivel=SECUNDARIA']
        for ruta in rutas:
            with self.subTest(ruta=ruta):
                self.assertEqual(self.client.get(ruta).status_code, 200)
        semana = self.client.get(f'{reverse("reuniones:agenda")}?vista=semana&fecha={self.dia:%Y-%m-%d}')
        self.assertContains(semana, reverse('reuniones:detalle', args=[self.reunion.pk]))
        self.assertNotContains(semana, '%; height: 4,')   # porcentajes sin coma decimal
        filtrada = self.client.get(reverse('reuniones:lista'), {'nivel': 'SECUNDARIA'})
        self.assertNotContains(filtrada, reverse('reuniones:detalle', args=[self.reunion.pk]))


@PRUEBAS
class NotificacionesTests(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()

    def test_avisan_sin_exponer_el_motivo(self):
        reunion = self.solicitud(docentes=[self.marta], acompanante=self.directora, area=Reunion.DOCENTE)
        self.assertTrue(NotificacionReunion.objects.filter(usuario=self.marta, reunion=reunion).exists())   # asignada
        self.programar(reunion)
        self.assertTrue(NotificacionReunion.objects.filter(tutor=self.ana, reunion=reunion).exists())       # confirmar asistencia
        for notificacion in NotificacionReunion.objects.all():
            self.assertNotIn('matemáticas', notificacion.texto + notificacion.titulo)
            self.assertNotIn(self.motivo.nombre, notificacion.texto + notificacion.titulo)
        self.confirmar_tutor(reunion)
        self.confirmar_personal(reunion)
        self.assertTrue(NotificacionReunion.objects.filter(tutor=self.ana, titulo__icontains='confirmada').exists())
        reglas.cancelar(self.refrescar(reunion), motivo='Motivo privado de la cancelación', usuario=self.directora)
        cancelacion = NotificacionReunion.objects.filter(tutor=self.ana, titulo__icontains='cancel').get()
        self.assertNotIn('privado', cancelacion.texto)

    def test_recordatorios_y_acuerdos_una_sola_vez(self):
        reunion = self.solicitud(responsable=self.directora)
        self.programar(reunion)
        antes = momento(10, 0, self.dia) - timedelta(hours=3)
        nuevas = notificaciones.generar_para(usuario=self.directora, ahora=antes)
        self.assertEqual([n.titulo for n in nuevas], ['Recordatorio: reunión con familia'])
        self.assertEqual(notificaciones.generar_para(usuario=self.directora, ahora=antes), [])
        self.assertEqual(len(notificaciones.generar_para(tutor=self.ana, ahora=antes)), 1)
        # Demasiado pronto (más de 24 horas antes): todavía no
        self.assertEqual(notificaciones.generar_para(usuario=self.recepcion, ahora=antes), [])

    def test_la_campana_cuenta_y_se_lee_al_abrir(self):
        reunion = self.solicitud(responsable=self.directora)
        self.client.force_login(self.directora)
        respuesta = self.client.get(reverse('reuniones:resumen'))
        self.assertEqual(respuesta.json()['pendientes'], 1)
        self.client.get(reverse('reuniones:detalle', args=[reunion.pk]))
        self.assertEqual(self.client.get(reverse('reuniones:resumen')).json()['pendientes'], 0)
