"""Rol de prefectura (pedido del 2026-10-13): el alcance por niveles o grupos en consultas, acciones, archivos,
reportes y exportaciones; justificaciones con comprobante que conservan la asistencia original; registros de acceso
aparte del pase de lista; suspensiones y medidas que esperan la aprobación de Dirección; corrección de lo propio con
motivo y trazabilidad; y que Prefectura no entra a lo administrativo."""
import io
import zipfile
from datetime import timedelta
from xml.etree import ElementTree

from django.contrib.admin.models import LogEntry
from django.test import override_settings
from django.urls import reverse

from Alumnos.asistencias import con_justificada_materia
from Alumnos.models import AsistenciaMateria, CambioJustificacion, DiaNoLectivo, Justificacion
from CISAHUAYO.context_processors import navegacion
from CISAHUAYO.pruebas import PRUEBAS, crear_alumno, crear_grupo, crear_usuario, hoy, inscribir_antes, lunes, materia_en_grado
from Conducta.models import (
    CambioConducta,
    CitaTutor,
    Compromiso,
    MedidaAplicada,
    MedidaDisciplinaria,
    RegistroConducta,
    Suspension,
)
from Conducta.pruebas import CARPETA, BaseConductaTestCase, borrar_carpeta, foto, pdf
from Usuarios.models import Rol

from . import asistencia
from .alcance import alcance_de
from .models import AlcancePrefectura, CambioAcceso, MovimientoAcceso


def tearDownModule():
    borrar_carpeta()


@PRUEBAS
@override_settings(MEDIA_ROOT=CARPETA)
class BasePrefecturaTestCase(BaseConductaTestCase):
    """Primaria 4° A (Ana) y 4° B (Leo), secundaria 1° A (Zoe). Una cuenta de prefectura y una de Dirección."""

    def setUp(self):
        super().setUp()
        self.grupo_b = crear_grupo(self.primaria, 'B')
        self.leo = crear_alumno(nombre='Leo', curp='PREFECTU00000000C3')
        self.inscripcion_leo = inscribir_antes(self.leo, self.ciclo, self.primaria, grupo=self.grupo_b)
        self.rol = Rol.objects.select_related('grupo').get(grupo__name='Prefectura')
        self.prefecto = crear_usuario('prefecto', self.rol)
        self.direccion = crear_usuario('directora', Rol.objects.get(grupo__name='Dirección'))
        self.dirige(self.direccion, 'PRIMARIA')
        self.amonestacion.disponible_prefectura = True
        self.amonestacion.save()

    @staticmethod
    def dirige(usuario, *niveles):
        from Usuarios.models import PerfilUsuario
        perfil = PerfilUsuario.de(usuario)
        perfil.niveles_direccion = list(niveles)
        perfil.save()

    def alcance(self, usuario=None, todo=False, niveles=(), grupos=()):
        fila, _ = AlcancePrefectura.objects.update_or_create(usuario=usuario or self.prefecto, defaults={'todo_el_colegio': todo, 'niveles': list(niveles)})
        fila.grupos.set(grupos)
        return fila

    def como_prefecto(self, **alcance):
        if alcance:
            self.alcance(**alcance)
        self.client.force_login(self.prefecto)

    def registro_de(self, alumno, **cambios):
        """Un registro de conducta hecho por el administrador (para probar lo que ve prefectura)."""
        self.client.force_login(self.admin)
        datos = {'alumno': alumno.pk}
        if alumno == self.otro:
            datos.update(categoria=self.convivencia_sec.pk, motivo=self.agresion_sec.pk)
        datos.update(cambios)
        self.registrar(**datos)
        return self.ultimo()


class RolYAlcanceTests(BasePrefecturaTestCase):
    def test_el_rol_prefectura_existe_con_sus_permisos(self):
        self.assertTrue(self.rol.es_prefectura)
        for permiso in ('consultar', 'registrar', 'corregir', 'justificar', 'solicitar_suspension', 'dar_seguimiento', 'exportar'):
            self.assertTrue(self.prefecto.has_perm(f'Prefectura.{permiso}'), permiso)
        self.assertFalse(self.prefecto.has_perm('Prefectura.corregir_otros'))   # lo concede el administrador si quiere
        self.assertFalse(self.prefecto.has_perm('Conducta.aprobar_suspension'))
        self.assertTrue(self.direccion.has_perm('Conducta.aprobar_suspension'))

    def test_sin_alcance_no_ve_a_ningun_estudiante(self):
        self.registro_de(self.alumno)
        self.como_prefecto()
        self.assertTrue(alcance_de(self.prefecto).vacio)
        self.assertEqual(self.client.get(reverse('prefectura:estudiantes')).context['pagina'].paginator.count, 0)
        self.assertEqual(self.client.get(reverse('prefectura:estudiante', args=[self.alumno.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('conducta:lista')).context['pagina'].paginator.count, 0)
        self.assertEqual(self.client.get(reverse('conducta:buscar'), {'q': 'Ana'}).json()['resultados'], [])
        self.assertContains(self.client.get(reverse('prefectura:inicio')), 'Todavía no tienes un alcance asignado')

    def test_alcance_por_nivel(self):
        de_zoe = self.registro_de(self.otro)
        self.como_prefecto(niveles=['PRIMARIA'])
        nombres = {i.alumno.nombre for i in self.client.get(reverse('prefectura:estudiantes')).context['pagina']}
        self.assertEqual(nombres, {'Ana', 'Leo'})
        self.assertEqual(self.client.get(reverse('prefectura:estudiante', args=[self.otro.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('conducta:detalle', args=[de_zoe.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('conducta:editar', args=[de_zoe.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('conducta:buscar'), {'q': 'Zoe'}).json()['resultados'], [])
        self.assertEqual(self.client.get(reverse('conducta:opciones'), {'alumno': self.otro.pk}).status_code, 400)

    def test_alcance_por_grupo(self):
        self.como_prefecto(grupos=[self.grupo_b])
        nombres = {i.alumno.nombre for i in self.client.get(reverse('prefectura:estudiantes')).context['pagina']}
        self.assertEqual(nombres, {'Leo'})
        self.assertEqual(self.client.get(reverse('prefectura:estudiante', args=[self.alumno.pk])).status_code, 404)

    def test_todo_el_colegio_se_concede_expresamente(self):
        self.como_prefecto(todo=True)
        nombres = {i.alumno.nombre for i in self.client.get(reverse('prefectura:estudiantes')).context['pagina']}
        self.assertEqual(nombres, {'Ana', 'Leo', 'Zoe'})

    def test_el_administrador_define_el_alcance_desde_la_ficha_del_usuario(self):
        url = reverse('usuarios:alcance', args=[self.prefecto.pk])
        respuesta = self.client.post(url, {'niveles': ['SECUNDARIA'], 'grupos': [self.grupo_b.pk]})
        self.assertRedirects(respuesta, reverse('usuarios:detalle', args=[self.prefecto.pk]))
        fila = AlcancePrefectura.objects.get(usuario=self.prefecto)
        self.assertEqual((fila.niveles, list(fila.grupos.all()), fila.modificado_por), (['SECUNDARIA'], [self.grupo_b], self.admin))
        self.assertTrue(LogEntry.objects.filter(object_id=str(self.prefecto.pk), change_message__startswith='Alcance de prefectura').exists())
        self.assertContains(self.client.get(reverse('usuarios:detalle', args=[self.prefecto.pk])), 'Secundaria completa')
        # Una cuenta que no es de prefectura no tiene alcance; y prefectura no administra usuarios
        self.assertRedirects(self.client.get(reverse('usuarios:alcance', args=[self.direccion.pk])), reverse('usuarios:detalle', args=[self.direccion.pk]))
        self.client.force_login(self.prefecto)
        self.assertEqual(self.client.post(url, {'todo_el_colegio': 'on'}).status_code, 403)

    def test_prefectura_no_entra_a_lo_administrativo(self):
        self.como_prefecto(todo=True)
        for nombre, argumentos in (
            ('alumnos:lista', []), ('alumnos:detalle', [self.alumno.pk]), ('alumnos:editar', [self.alumno.pk]),
            ('usuarios:lista', []), ('roles:lista', []), ('inscripciones:lista', []), ('asistencias:materias', []),
            ('asistencias:justificaciones', []), ('conducta:configuracion', []), ('conducta:reportes', []),
            ('conducta:categoria_crear', []), ('periodos:lista', []), ('materias:lista', []),
        ):
            with self.subTest(nombre=nombre):
                self.assertEqual(self.client.get(reverse(nombre, args=argumentos)).status_code, 403)

    def test_su_menu_es_el_de_prefectura(self):
        self.como_prefecto(niveles=['PRIMARIA'])
        self.assertRedirects(self.client.get(reverse('inicio')), reverse('prefectura:inicio'))
        peticion = self.client.get(reverse('prefectura:inicio')).wsgi_request
        titulos = [s['titulo'] for s in navegacion(peticion)['navegacion']]
        self.assertEqual(titulos.count('Prefectura'), 1)   # solo la suya: la general no le muestra nada
        secciones = {s['titulo']: [e['etiqueta'] for e in s['elementos']] for s in navegacion(peticion)['navegacion']}
        self.assertEqual(secciones['Prefectura'], ['Inicio', 'Estudiantes', 'Asistencia', 'Conducta', 'Seguimiento', 'Reportes'])
        self.assertNotIn(None, secciones)   # sin «Panel de control»: su inicio es el de prefectura
        self.assertEqual(secciones['Sistema'], ['Ajustes'])
        # El administrador conserva su menú: su «Prefectura» es la general (asistencia y conducta del colegio)
        self.client.force_login(self.admin)
        peticion = self.client.get(reverse('inicio')).wsgi_request
        secciones = [(s['titulo'], [e['etiqueta'] for e in s['elementos']]) for s in navegacion(peticion)['navegacion']]
        self.assertEqual([t for t, _ in secciones], [None, 'Comunidad escolar', 'Gestión académica', 'Prefectura', 'Sistema'])
        self.assertEqual(dict(secciones)['Prefectura'], ['Asistencias', 'Registro de conducta', 'Reportes de conducta'])

    def test_la_ficha_no_muestra_datos_clinicos_ni_financieros(self):
        self.alumno.alergias = 'Penicilina'
        self.alumno.save()
        self.como_prefecto(niveles=['PRIMARIA'])
        respuesta = self.client.get(reverse('prefectura:estudiante', args=[self.alumno.pk]))
        self.assertContains(respuesta, self.alumno.referencia)
        for oculto in ('Penicilina', 'Grupo sanguíneo', 'Responsable de pagos', 'Domicilio'):
            self.assertNotContains(respuesta, oculto)


class ConductaEnPrefecturaTests(BasePrefecturaTestCase):
    def setUp(self):
        super().setUp()
        self.como_prefecto(niveles=['PRIMARIA'])

    def test_registra_dentro_de_su_alcance(self):
        self.registrar(medidas=[self.amonestacion.pk], reporta='Maestra de guardia')
        registro = self.ultimo()
        self.assertEqual((registro.alumno, registro.registrado_por, registro.reporta), (self.alumno, self.prefecto, 'Maestra de guardia'))
        respuesta = self.registrar(alumno=self.otro.pk, categoria=self.convivencia_sec.pk, motivo=self.agresion_sec.pk)
        self.assertIn('alumno', respuesta.context['form'].errors)
        self.assertEqual(RegistroConducta.objects.count(), 1)

    def test_el_motivo_depende_de_la_categoria_y_del_nivel(self):
        respuesta = self.registrar(categoria=self.reconocimiento.pk, motivo=self.agresion.pk, tipo='POSITIVA')
        self.assertIn('motivo', respuesta.context['form'].errors)
        respuesta = self.registrar(categoria=self.convivencia_sec.pk, motivo=self.agresion_sec.pk)   # catálogo de secundaria
        self.assertIn('categoria', respuesta.context['form'].errors)

    def test_solo_aplica_medidas_habilitadas_y_las_que_requieren_aprobacion_esperan(self):
        respuesta = self.registrar(medidas=[self.compromiso.pk], responsable=self.prefecto.pk, fecha_revision=hoy().isoformat())
        self.assertIn('medidas', respuesta.context['form'].errors)   # no está habilitada para prefectura
        reporte = MedidaDisciplinaria.objects.create(nivel='PRIMARIA', nombre='Reporte a la familia', descripcion='Por escrito',
                                                     disponible_prefectura=True, requiere_aprobacion=True)
        self.registrar(medidas=[reporte.pk])
        medida = self.ultimo().medidas_aplicadas.get()
        self.assertEqual((medida.estado, medida.solicitada_por), ('PENDIENTE', self.prefecto))
        self.assertEqual(self.client.get(reverse('conducta:medida_resolver', args=[medida.pk])).status_code, 403)
        self.client.force_login(self.direccion)
        self.client.post(reverse('conducta:medida_resolver', args=[medida.pk]), {'decision': 'aprobar'})
        medida.refresh_from_db()
        self.assertEqual((medida.estado, medida.resuelta_por), ('APLICADA', self.direccion))

    def test_la_suspension_es_una_solicitud_que_aprueba_direccion(self):
        self.suspender.disponible_prefectura = True
        self.suspender.save()
        datos = {'medidas': [self.suspender.pk], 'suspension_motivo': self.motivo_suspension.pk,
                 'suspension_inicio': (hoy() + timedelta(days=1)).isoformat(), 'suspension_fin': (hoy() + timedelta(days=2)).isoformat()}
        respuesta = self.registrar(**datos)
        self.assertIn('suspension_justificacion', respuesta.context['form'].errors)   # la justificación es obligatoria
        respuesta = self.registrar(**{**datos, 'suspension_fin': hoy().isoformat(), 'suspension_justificacion': 'Golpeó a un compañero en el recreo.'})
        self.assertIn('suspension_fin', respuesta.context['form'].errors)            # el término no va antes del inicio
        self.registrar(**datos, suspension_justificacion='Golpeó a un compañero en el recreo.')
        registro = self.ultimo()
        suspension = registro.suspension
        self.assertEqual((suspension.aprobacion, suspension.solicitada_por, suspension.autorizada_por), ('PENDIENTE', self.prefecto, None))
        self.assertEqual(registro.medidas_aplicadas.get().estado, 'PENDIENTE')
        self.assertEqual(suspension.estado_display, 'Pendiente de aprobación')   # no está vigente ni próxima
        # No cuenta como suspensión mientras no se apruebe
        self.client.force_login(self.admin)
        resumen = self.client.get(reverse('conducta:reportes'), {'reporte': 'resumen'}).context['contenido']['resumen']
        self.assertEqual((resumen['suspensiones'], resumen['solicitudes_pendientes']), (0, 1))
        # Prefectura no la aprueba; Dirección sí
        self.client.force_login(self.prefecto)
        self.assertEqual(self.client.post(reverse('conducta:suspension_resolver', args=[suspension.pk]), {'decision': 'aprobar'}).status_code, 403)
        self.client.force_login(self.direccion)
        self.client.post(reverse('conducta:suspension_resolver', args=[suspension.pk]), {'decision': 'aprobar', 'observaciones': 'Procede.'})
        suspension.refresh_from_db()
        self.assertEqual((suspension.aprobacion, suspension.autorizada_por, suspension.resuelta_por), ('APROBADA', self.direccion, self.direccion))
        self.assertEqual(registro.medidas_aplicadas.get().estado, 'APLICADA')
        acciones = list(registro.cambios.order_by('pk').values_list('accion', flat=True))
        self.assertEqual(acciones, [CambioConducta.CREADO, CambioConducta.SOLICITUD, CambioConducta.RESOLUCION])

    def test_la_autoriza_la_direccion_del_nivel_del_estudiante(self):
        self.suspender.disponible_prefectura = True
        self.suspender.save()
        self.registrar(medidas=[self.suspender.pk], suspension_motivo=self.motivo_suspension.pk, suspension_inicio=hoy().isoformat(),
                       suspension_fin=hoy().isoformat(), suspension_justificacion='Agredió a un compañero en el recreo.')
        suspension = self.ultimo().suspension
        de_secundaria = crear_usuario('direccion_secundaria', Rol.objects.get(grupo__name='Dirección'))
        self.dirige(de_secundaria, 'SECUNDARIA')
        self.client.force_login(de_secundaria)
        self.assertEqual(self.client.post(reverse('conducta:suspension_resolver', args=[suspension.pk]), {'decision': 'aprobar'}).status_code, 403)
        self.assertContains(self.client.get(reverse('conducta:solicitudes')), 'La autoriza la dirección de primaria')
        sin_niveles = crear_usuario('direccion_sin_nivel', Rol.objects.get(grupo__name='Dirección'))
        self.client.force_login(sin_niveles)
        self.assertEqual(self.client.post(reverse('conducta:suspension_resolver', args=[suspension.pk]), {'decision': 'aprobar'}).status_code, 403)
        suspension.refresh_from_db()
        self.assertEqual(suspension.aprobacion, 'PENDIENTE')
        # La de primaria sí, desde la ficha del usuario se le asignó su nivel
        self.client.force_login(self.admin)
        self.client.post(reverse('usuarios:direccion', args=[sin_niveles.pk]), {'niveles': ['PRIMARIA']})
        self.client.force_login(sin_niveles)
        self.client.post(reverse('conducta:suspension_resolver', args=[suspension.pk]), {'decision': 'aprobar'})
        suspension.refresh_from_db()
        self.assertEqual((suspension.aprobacion, suspension.autorizada_por), ('APROBADA', sin_niveles))

    def test_los_registros_de_un_ciclo_cerrado_son_de_solo_lectura(self):
        from Alumnos.models import CicloEscolar
        self.registrar()
        registro = self.ultimo()
        anterior = CicloEscolar.objects.create(nombre='2025-2026', fecha_inicio=self.ciclo.fecha_inicio - timedelta(days=400),
                                               fecha_fin=self.ciclo.fecha_inicio - timedelta(days=40), activo=False)
        RegistroConducta.objects.filter(pk=registro.pk).update(ciclo=anterior)
        for nombre in ('conducta:editar', 'conducta:anular', 'conducta:seguimiento', 'conducta:cita_crear', 'conducta:compromiso_crear'):
            with self.subTest(nombre=nombre):
                self.assertEqual(self.client.get(reverse(nombre, args=[registro.pk])).status_code, 403)
        self.assertContains(self.client.get(reverse('conducta:detalle', args=[registro.pk])), 'es de solo lectura')

    def test_nadie_aprueba_su_propia_solicitud(self):
        registro = self.registro_de(self.alumno)
        suspension = Suspension.objects.create(
            registro=registro, motivo=self.motivo_suspension, motivo_nombre='Agresión grave', fecha_inicio=hoy(), fecha_fin=hoy(),
            aprobacion='PENDIENTE', solicitada_por=self.direccion, justificacion='Prueba de solicitud propia.',
        )
        self.client.force_login(self.direccion)
        self.client.post(reverse('conducta:suspension_resolver', args=[suspension.pk]), {'decision': 'aprobar'})
        suspension.refresh_from_db()
        self.assertEqual(suspension.aprobacion, 'PENDIENTE')

    def test_corrige_lo_propio_abierto_con_motivo_y_queda_constancia(self):
        self.registrar()
        registro = self.ultimo()
        url = reverse('conducta:editar', args=[registro.pk])
        respuesta = self.client.post(url, self.datos(descripcion='Le gritó a un compañero en la fila.', motivo_cambio=''))
        self.assertIn('motivo_cambio', respuesta.context['form'].errors)
        self.client.post(url, self.datos(descripcion='Le gritó a un compañero en la fila.', motivo_cambio='Faltaba el lugar exacto.'))
        cambio = registro.cambios.get(accion=CambioConducta.EDITADO)
        self.assertIn('Faltaba el lugar exacto.', cambio.detalle)
        self.assertEqual(cambio.cambios[0][0], 'Descripción')
        self.assertEqual(cambio.cambios[0][1], 'Le gritó a un compañero durante el recreo.')   # valor anterior y nuevo
        # Cerrado ya no lo corrige; lo de otros tampoco
        self.client.post(reverse('conducta:seguimiento', args=[registro.pk]), {'estado': 'CERRADO', 'observaciones_cierre': 'Se disculpó.'})
        self.assertEqual(self.client.get(url).status_code, 403)
        ajeno = self.registro_de(self.alumno)
        self.client.force_login(self.prefecto)
        self.assertEqual(self.client.get(reverse('conducta:editar', args=[ajeno.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse('conducta:anular', args=[ajeno.pk])).status_code, 403)
        # Con «Corregir de otros» sí
        self.prefecto.user_permissions.add(*__import__('Usuarios.seguridad', fromlist=['x']).objetos_de_permisos({'Prefectura.corregir_otros'}))
        self.client.force_login(self.prefecto)
        self.assertEqual(self.client.get(reverse('conducta:editar', args=[ajeno.pk])).status_code, 200)

    def test_cerrar_el_caso_exige_observacion_final(self):
        self.registrar()
        registro = self.ultimo()
        respuesta = self.client.post(reverse('conducta:seguimiento', args=[registro.pk]), {'estado': 'CERRADO'})
        self.assertIn('observaciones_cierre', respuesta.context['form'].errors)

    def test_anular_no_borra_y_deja_historial(self):
        self.registrar()
        registro = self.ultimo()
        self.client.post(reverse('conducta:anular', args=[registro.pk]), {'motivo': 'Se registró dos veces por error.'})
        registro.refresh_from_db()
        self.assertEqual((registro.anulado, registro.anulado_por), (True, self.prefecto))
        self.assertTrue(registro.cambios.filter(accion=CambioConducta.ANULADO).exists())
        self.assertEqual(RegistroConducta.objects.count(), 1)

    def test_citas_y_compromisos_con_su_historial(self):
        self.registrar()
        registro = self.ultimo()
        self.client.post(reverse('conducta:cita_crear', args=[registro.pk]), {
            'fecha': hoy().isoformat(), 'hora': '12:00', 'modalidad': 'PRESENCIAL', 'tutor': 'otra', 'persona': 'Laura Ruiz (madre)',
            'asunto': 'Revisar lo ocurrido en el recreo.', 'responsable': self.prefecto.pk,
        })
        cita = CitaTutor.objects.get()
        respuesta = self.client.post(reverse('conducta:cita_actualizar', args=[cita.pk]), {'estado': 'REALIZADA'})
        self.assertIn('resultado', respuesta.context['form'].errors)
        self.client.post(reverse('conducta:cita_actualizar', args=[cita.pk]), {'estado': 'REALIZADA', 'resultado': 'Acordamos revisar en una semana.'})
        cita.refresh_from_db()
        self.assertEqual(cita.estado, 'REALIZADA')
        self.client.post(reverse('conducta:compromiso_crear', args=[registro.pk]), {
            'descripcion': 'Ofrecer una disculpa por escrito.', 'quien': 'ESTUDIANTE', 'responsable': self.prefecto.pk,
            'fecha_limite': (hoy() + timedelta(days=3)).isoformat(),
        })
        compromiso = Compromiso.objects.get()
        self.client.post(reverse('conducta:compromiso_resolver', args=[compromiso.pk]), {'estado': 'CUMPLIDO', 'observaciones': 'Entregó la carta.'})
        compromiso.refresh_from_db()
        self.assertEqual((compromiso.estado, compromiso.resuelto_por), ('CUMPLIDO', self.prefecto))
        self.assertEqual(registro.cambios.filter(accion__in=[CambioConducta.CITA, CambioConducta.COMPROMISO]).count(), 4)

    def test_las_evidencias_tienen_el_alcance_del_registro(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('conducta:crear'), {**self.datos(alumno=self.otro.pk, categoria=self.convivencia_sec.pk, motivo=self.agresion_sec.pk),
                                                    'evidencias': foto()})
        evidencia = self.ultimo().evidencias.get()
        self.client.force_login(self.prefecto)
        self.assertEqual(self.client.get(reverse('conducta:evidencia', args=[evidencia.pk])).status_code, 404)
        self.alcance(todo=True)
        self.assertEqual(self.client.get(reverse('conducta:evidencia', args=[evidencia.pk])).status_code, 200)


class AsistenciaEnPrefecturaTests(BasePrefecturaTestCase):
    def setUp(self):
        super().setUp()
        self.mat = materia_en_grado('MAT', self.primaria, self.ciclo, dia=lunes().weekday())
        self.esp = materia_en_grado('ESP', self.primaria, self.ciclo, dia=lunes().weekday(), inicio=(9, 0), fin=(10, 0))
        self.falta_mat = AsistenciaMateria.objects.create(inscripcion=self.inscripcion, materia_grado=self.mat, fecha=lunes(), estado='FALTA')
        self.falta_esp = AsistenciaMateria.objects.create(inscripcion=self.inscripcion, materia_grado=self.esp, fecha=lunes(), estado='FALTA')
        self.como_prefecto(niveles=['PRIMARIA'])

    def justificar(self, **cambios):
        datos = {'alumno': self.alumno.pk, 'desde': lunes().isoformat(), 'hasta': lunes().isoformat(), 'estados': ['FALTA'],
                 'motivo': 'Cita médica con receta del pediatra.', 'confirmados': f'm-{self.falta_esp.pk},m-{self.falta_mat.pk}',
                 'comprobante': foto('receta.jpg')}
        datos.update(cambios)
        return self.client.post(reverse('prefectura:justificar'), {k: v for k, v in datos.items() if v is not None})

    def test_el_panel_distingue_faltas_por_materia_y_estudiantes(self):
        from .asistencia import del_dia
        dia = del_dia(alcance_de(self.prefecto), lunes())
        self.assertEqual((dia['faltas'], dia['estudiantes_con_falta']), (2, 1))
        respuesta = self.client.get(reverse('prefectura:asistencia_registros'), {'desde': lunes().isoformat(), 'hasta': lunes().isoformat(), 'estado': 'FALTA'})
        self.assertEqual((respuesta.context['resumen']['faltas'], respuesta.context['resumen']['estudiantes']), (2, 1))
        por_estudiante = self.client.get(reverse('prefectura:asistencia_registros'), {'desde': lunes().isoformat(), 'hasta': lunes().isoformat(), 'vista': 'estudiantes'})
        self.assertEqual([fila['faltas'] for fila in por_estudiante.context['pagina']], [2])

    def test_la_vista_previa_muestra_lo_que_se_justificara(self):
        datos = self.client.get(reverse('prefectura:justificar_previa'), {'alumno': self.alumno.pk, 'desde': lunes().isoformat(), 'hasta': lunes().isoformat(),
                                                                           'estados': 'FALTA'}).json()
        self.assertEqual(datos['total'], 2)
        self.assertEqual({r['clave'] for r in datos['registros']}, {f'm-{self.falta_mat.pk}', f'm-{self.falta_esp.pk}'})
        fuera = self.client.get(reverse('prefectura:justificar_previa'), {'alumno': self.otro.pk, 'desde': lunes().isoformat(), 'hasta': lunes().isoformat()})
        self.assertEqual(fuera.status_code, 400)

    def test_justificar_exige_una_foto_del_comprobante(self):
        self.assertIn('Adjunta la foto del comprobante', str(self.justificar(comprobante=None).context['form'].non_field_errors()))
        self.assertIn('fotografía', str(self.justificar(comprobante=pdf()).context['form'].non_field_errors()))
        self.assertFalse(Justificacion.objects.exists())

    def test_justificar_conserva_la_falta_y_la_vincula(self):
        self.justificar()
        justificaciones = list(Justificacion.objects.order_by('pk'))
        self.assertEqual(len(justificaciones), 2)
        self.assertEqual({j.asistencia_id for j in justificaciones}, {self.falta_mat.pk, self.falta_esp.pk})
        self.assertEqual(len({j.lote for j in justificaciones}), 1)
        self.assertEqual({j.registrada_por for j in justificaciones}, {self.prefecto})
        self.assertEqual(justificaciones[0].documento.name, justificaciones[1].documento.name)   # un mismo comprobante
        self.falta_mat.refresh_from_db()
        self.assertEqual(self.falta_mat.estado, 'FALTA')   # el estado original no cambia
        self.assertTrue(con_justificada_materia(AsistenciaMateria.objects.filter(pk=self.falta_mat.pk)).get().justificada)
        self.assertEqual(CambioJustificacion.objects.filter(accion='CREADA').count(), 2)

    def test_si_los_registros_cambiaron_no_justifica_nada(self):
        respuesta = self.justificar(confirmados=f'm-{self.falta_mat.pk}')
        self.assertIn('cambiaron', str(respuesta.context['form'].non_field_errors()))
        self.assertFalse(Justificacion.objects.exists())

    def test_no_justifica_fuera_de_su_alcance(self):
        respuesta = self.justificar(alumno=self.otro.pk)
        self.assertIn('alumno', respuesta.context['form'].errors)

    def test_revocar_exige_motivo_y_queda_en_el_historial(self):
        self.justificar()
        justificacion = Justificacion.objects.first()
        url = reverse('prefectura:justificacion_revocar', args=[justificacion.pk])
        self.assertIn('motivo', self.client.post(url, {'motivo': 'no'}).context['form'].errors)
        self.client.post(url, {'motivo': 'La receta no correspondía a esas fechas.'})
        self.assertFalse(Justificacion.objects.filter(activa=True).exists())   # las del mismo envío
        revocada = Justificacion.objects.first()
        self.assertEqual((revocada.revocada_por, revocada.motivo_revocacion), (self.prefecto, 'La receta no correspondía a esas fechas.'))
        self.assertEqual(CambioJustificacion.objects.filter(accion='REVOCADA').count(), 2)
        self.assertEqual(Justificacion.objects.count(), 2)   # no se borra

    def test_el_comprobante_solo_lo_ve_quien_puede(self):
        self.justificar()
        url = reverse('asistencias:comprobante', args=[Justificacion.objects.first().pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.alcance(niveles=['SECUNDARIA'])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.sin_permisos)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_la_matriz_es_de_consulta_y_de_su_alcance(self):
        respuesta = self.client.get(reverse('prefectura:asistencia'), {'materia': self.mat.pk})
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(respuesta.context['puede_cambiar'])
        self.assertEqual(self.client.post(reverse('asistencias:materias_guardar', args=[self.mat.pk])).status_code, 403)
        self.alcance(niveles=['SECUNDARIA'])
        self.assertEqual(self.client.get(reverse('prefectura:asistencia'), {'materia': self.mat.pk}).status_code, 404)

    def test_los_accesos_no_cambian_el_pase_de_lista(self):
        antes = list(AsistenciaMateria.objects.values_list('pk', 'estado'))
        datos = {'alumno': self.alumno.pk, 'tipo': 'RETARDO', 'fecha': lunes().isoformat(), 'hora': '08:25', 'motivo': 'Tráfico en la carretera.'}
        self.client.post(reverse('prefectura:acceso_crear'), datos)
        movimiento = MovimientoAcceso.objects.get()
        self.assertEqual((movimiento.alumno, movimiento.registrado_por, movimiento.tipo), (self.alumno, self.prefecto, 'RETARDO'))
        self.assertEqual(list(AsistenciaMateria.objects.values_list('pk', 'estado')), antes)
        # Corregir pide motivo y deja el antes y el después
        url = reverse('prefectura:acceso_corregir', args=[movimiento.pk])
        self.assertIn('motivo_cambio', self.client.post(url, {**datos, 'hora': '08:40'}).context['form'].errors)
        self.client.post(url, {**datos, 'hora': '08:40', 'motivo_cambio': 'La hora real era 8:40.'})
        cambio = movimiento.cambios.get(accion=CambioAcceso.CORREGIDO)
        self.assertEqual(cambio.cambios, [['Hora', '08:25', '08:40']])
        # Otra cuenta de prefectura no corrige lo ajeno
        otro = crear_usuario('prefecto2', self.rol)
        self.alcance(usuario=otro, niveles=['PRIMARIA'])
        self.client.force_login(otro)
        self.assertEqual(self.client.get(url).status_code, 403)
        # Anular conserva el registro con su motivo
        self.client.force_login(self.prefecto)
        self.client.post(reverse('prefectura:acceso_anular', args=[movimiento.pk]), {'motivo': 'Lo registré en el estudiante equivocado.'})
        movimiento.refresh_from_db()
        self.assertTrue(movimiento.anulado)
        self.assertEqual(MovimientoAcceso.objects.count(), 1)

    def test_los_accesos_respetan_las_fechas_de_clases(self):
        base = {'alumno': self.alumno.pk, 'tipo': 'SALIDA', 'hora': '12:00', 'motivo': 'Cita con el dentista.'}
        respuesta = self.client.post(reverse('prefectura:acceso_crear'), {**base, 'fecha': (hoy() + timedelta(days=1)).isoformat(), 'acompanante': 'Su mamá'})
        self.assertIn('fecha', respuesta.context['form'].errors)
        DiaNoLectivo.registrar(fecha=lunes(), motivo='Puente')
        respuesta = self.client.post(reverse('prefectura:acceso_crear'), {**base, 'fecha': lunes().isoformat(), 'acompanante': 'Su mamá'})
        self.assertIn('fecha', respuesta.context['form'].errors)
        DiaNoLectivo.objects.all().delete()
        respuesta = self.client.post(reverse('prefectura:acceso_crear'), {**base, 'fecha': lunes().isoformat()})
        self.assertIn('acompanante', respuesta.context['form'].errors)   # una salida dice quién lo recoge
        self.assertFalse(MovimientoAcceso.objects.exists())


    def test_un_dia_sin_clases_solo_cuenta_para_su_nivel(self):
        base = {'alumno': self.alumno.pk, 'tipo': 'SALIDA', 'hora': '12:00', 'motivo': 'Cita con el dentista.', 'acompanante': 'Su mamá',
                'fecha': lunes().isoformat()}
        DiaNoLectivo.registrar(fecha=lunes(), motivo='Consejo técnico', niveles=['PRIMARIA'])   # Ana es de primaria
        respuesta = self.client.post(reverse('prefectura:acceso_crear'), base)
        self.assertEqual(respuesta.context['form'].errors['fecha'], ['Ese día no hubo clases en primaria (Consejo técnico).'])
        self.assertEqual(asistencia.por_justificar(self.inscripcion, lunes(), lunes()), [])
        DiaNoLectivo.objects.all().delete()
        DiaNoLectivo.registrar(fecha=lunes(), motivo='Consejo técnico', niveles=['SECUNDARIA'])
        self.assertEqual(len(asistencia.por_justificar(self.inscripcion, lunes(), lunes())), 2)
        self.client.post(reverse('prefectura:acceso_crear'), base)
        self.assertEqual(MovimientoAcceso.objects.count(), 1)


class SuspensionEnLaAsistenciaTests(BasePrefecturaTestCase):
    """Los días de una suspensión se marcan con una S en un círculo blanco: autorizada (bloqueada, no es falta) o
    pendiente de autorizar (solo avisa)."""

    def setUp(self):
        super().setUp()
        self.mat = materia_en_grado('MAT', self.primaria, self.ciclo, dia=lunes().weekday())
        self.registro = self.registro_de(self.alumno)

    def suspension(self, aprobacion):
        return Suspension.objects.create(
            registro=self.registro, motivo=self.motivo_suspension, motivo_nombre='Agresión grave', fecha_inicio=lunes(), fecha_fin=lunes(),
            aprobacion=aprobacion, solicitada_por=self.prefecto,
        )

    def celda(self):
        from Alumnos.asistencia_docente import celda_de
        return celda_de(self.mat, self.inscripcion, lunes(), self.admin)

    def test_autorizada_es_una_s_bloqueada_que_no_cuenta_como_falta(self):
        AsistenciaMateria.objects.create(inscripcion=self.inscripcion, materia_grado=self.mat, fecha=lunes(), estado='FALTA', origen='CIERRE')
        self.suspension('APROBADA')
        celda = self.celda()
        self.assertEqual((celda.letra, celda.clase, celda.editable), ('S', 'suspendido', False))
        self.assertIn('Suspendido', celda.nombre)
        from .asistencia import de_materias
        self.assertFalse(de_materias(alcance_de(self.admin)).filter(inscripcion=self.inscripcion, fecha=lunes()).exists())
        respuesta = self.client.get(reverse('asistencias:materias'), {'materia': self.mat.pk, 'desde': lunes().isoformat(), 'hasta': lunes().isoformat()})
        self.assertContains(respuesta, 'indicador-asistencia--suspendido')
        self.assertContains(respuesta, 'Estudiante suspendido (suspensión autorizada)')   # en la leyenda

    def test_pendiente_solo_avisa(self):
        self.suspension('PENDIENTE')
        celda = self.celda()
        self.assertEqual((celda.letra, celda.clase), ('S', 'solicitado'))
        self.assertIn('pendiente de autorizar', celda.nombre)
        AsistenciaMateria.objects.create(inscripcion=self.inscripcion, materia_grado=self.mat, fecha=lunes(), estado='PRESENTE', origen='PASE')
        celda = self.celda()
        self.assertEqual(celda.letra, 'P')   # si asistió, se ve lo capturado (con el aviso)
        self.assertIn('pendiente de autorizar', celda.nombre)

    def test_la_pantalla_de_entrada_rechaza_a_quien_esta_suspendido(self):
        from Alumnos.asistencias import EntradaRechazada, registrar_entrada
        from CISAHUAYO.pruebas import momento
        from Alumnos.models import AsistenciaGeneral
        suspension = self.suspension('PENDIENTE')
        self.assertTrue(registrar_entrada(self.alumno, 'UID', momento=momento(7, 45)).creada)   # pendiente: todavía entra
        AsistenciaGeneral.objects.all().delete()
        AsistenciaMateria.objects.all().delete()
        suspension.aprobacion = 'APROBADA'
        suspension.save()
        self.assertTrue(registrar_entrada(self.leo, 'UID', momento=momento(7, 45)).creada)     # a otro estudiante no le afecta
        with self.assertRaises(EntradaRechazada) as rechazo:
            registrar_entrada(self.alumno, 'UID', momento=momento(7, 45))
        self.assertEqual(rechazo.exception.codigo, 'SUSPENSION')
        self.assertIn('suspensión', rechazo.exception.mensaje)

    def test_el_retardo_de_ingreso_de_prefectura_es_falta_en_la_primera_hora(self):
        from Alumnos.models import AsistenciaGeneral
        self.como_prefecto(niveles=['PRIMARIA'])
        datos = {'alumno': self.alumno.pk, 'tipo': 'RETARDO', 'fecha': lunes().isoformat(), 'hora': '08:20', 'motivo': 'Se le hizo tarde.'}
        self.client.post(reverse('prefectura:acceso_crear'), datos)
        general = AsistenciaGeneral.objects.get(inscripcion=self.inscripcion, fecha=lunes())
        self.assertEqual((general.estado, general.hora_entrada.strftime('%H:%M')), ('RETARDO', '08:20'))
        self.assertEqual(AsistenciaMateria.objects.get(inscripcion=self.inscripcion, materia_grado=self.mat).estado, 'FALTA')
        # Lo que el docente ya capturó en su pase de lista se respeta
        AsistenciaMateria.objects.filter(materia_grado=self.mat).update(estado='PRESENTE', origen='PASE')
        movimiento = MovimientoAcceso.objects.get()
        self.client.post(reverse('prefectura:acceso_corregir', args=[movimiento.pk]), {**datos, 'hora': '08:30', 'motivo_cambio': 'Llegó a las 8:30.'})
        self.assertEqual(AsistenciaMateria.objects.get(inscripcion=self.inscripcion, materia_grado=self.mat).estado, 'PRESENTE')
        self.assertEqual(AsistenciaGeneral.objects.get(inscripcion=self.inscripcion, fecha=lunes()).hora_entrada.strftime('%H:%M'), '08:30')

    def test_no_se_registra_un_acceso_en_un_dia_de_suspension(self):
        self.suspension('APROBADA')
        self.como_prefecto(niveles=['PRIMARIA'])
        respuesta = self.client.post(reverse('prefectura:acceso_crear'), {
            'alumno': self.alumno.pk, 'tipo': 'RETARDO', 'fecha': lunes().isoformat(), 'hora': '08:20', 'motivo': 'Llegó tarde.'})
        self.assertIn('fecha', respuesta.context['form'].errors)
        self.assertFalse(MovimientoAcceso.objects.exists())

    def test_la_asistencia_del_dia_marca_a_los_suspendidos(self):
        self.suspension('APROBADA')
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('asistencias:dia'), {'fecha': lunes().isoformat()})
        self.assertEqual(respuesta.context['total']['suspendidos'], 1)
        fila = next(i for i in respuesta.context['pagina'] if i.alumno == self.alumno)
        self.assertTrue(fila.suspension.aprobada)
        self.assertContains(respuesta, 'indicador-asistencia--suspendido')
        solo = self.client.get(reverse('asistencias:dia'), {'fecha': lunes().isoformat(), 'estado': 'SUSPENDIDO'})
        self.assertEqual([i.alumno for i in solo.context['pagina']], [self.alumno])
        sin_entrada = self.client.get(reverse('asistencias:dia'), {'fecha': lunes().isoformat(), 'estado': 'SIN_REGISTRO'})
        self.assertNotIn(self.alumno, [i.alumno for i in sin_entrada.context['pagina']])

    def test_el_comprobante_sin_extension_se_reconoce_por_su_contenido(self):
        # Cloudinary guarda los archivos sin extensión: la foto debe verse como foto, no descargarse como desconocida
        from django.core.files.base import ContentFile
        from Alumnos.models import Justificacion
        from Conducta.pruebas import foto
        falta = AsistenciaMateria.objects.create(inscripcion=self.inscripcion, materia_grado=self.mat, fecha=lunes(), estado='FALTA')
        justificacion = Justificacion(inscripcion=self.inscripcion, fecha=lunes(), motivo='Cita médica.', asistencia=falta)
        justificacion.documento.save('comprobante_sin_extension', ContentFile(foto().read()), save=True)
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('asistencias:comprobante', args=[justificacion.pk]))
        self.assertEqual(respuesta['Content-Type'], 'image/jpeg')
        self.assertIn('.jpg', respuesta['Content-Disposition'])

    def test_el_cierre_del_dia_no_pone_faltas_a_quien_esta_suspendido(self):
        from Alumnos.asistencias import cerrar_dia
        self.suspension('APROBADA')
        cerrar_dia(lunes())
        from Alumnos.models import AsistenciaGeneral
        self.assertFalse(AsistenciaMateria.objects.filter(inscripcion=self.inscripcion, fecha=lunes()).exists())
        self.assertFalse(AsistenciaGeneral.objects.filter(inscripcion=self.inscripcion, fecha=lunes()).exists())
        self.assertEqual(AsistenciaGeneral.objects.get(inscripcion=self.inscripcion_leo, fecha=lunes()).estado, 'FALTA')   # Leo sí faltó


class ReportesDePrefecturaTests(BasePrefecturaTestCase):
    def setUp(self):
        super().setUp()
        self.mat = materia_en_grado('MAT', self.primaria, self.ciclo, dia=lunes().weekday())
        AsistenciaMateria.objects.create(inscripcion=self.inscripcion, materia_grado=self.mat, fecha=lunes(), estado='FALTA')
        self.registro_de(self.alumno)
        self.registro_de(self.otro)
        self.como_prefecto(niveles=['PRIMARIA'])

    def filas_de_excel(self, contenido):
        with zipfile.ZipFile(io.BytesIO(contenido)) as libro:
            raiz = ElementTree.fromstring(libro.read('xl/worksheets/sheet1.xml'))
        ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        return [[(c.find('.//x:t', ns).text if c.find('.//x:t', ns) is not None else (c.find('x:v', ns).text if c.find('x:v', ns) is not None else ''))
                 for c in fila.iterfind('x:c', ns)] for fila in raiz.iterfind('.//x:row', ns)]

    def test_los_reportes_respetan_el_alcance(self):
        contenido = self.client.get(reverse('prefectura:reportes'), {'reporte': 'conducta'}).context['contenido']
        self.assertEqual({r.alumno for r in contenido['registros']}, {self.alumno})
        contenido = self.client.get(reverse('prefectura:reportes'), {'reporte': 'asistencia'}).context['contenido']
        self.assertEqual({f['alumno'].nombre for f in contenido['filas']}, {'Ana', 'Leo'})
        self.assertEqual((contenido['total']['faltas'], contenido['total']['estudiantes_con_falta']), (1, 1))

    def test_el_excel_coincide_y_lleva_encabezado(self):
        filtros = {'reporte': 'justificaciones'}
        pantalla = self.client.get(reverse('prefectura:reportes'), filtros).context['contenido']
        filas = self.filas_de_excel(self.client.get(reverse('prefectura:reporte_excel'), filtros).content)
        self.assertEqual(filas[0], ['Colegio Interamericano de Sahuayo'])
        self.assertIn(['Generado por', 'Prefecto Prueba'], filas)
        self.assertEqual(int(next(f[1] for f in filas if f and f[0] == 'Sin justificar')), pantalla['faltas_sin_justificar'])
        hoja = self.client.get(reverse('prefectura:reporte_imprimir'), {**filtros, 'pdf': '1'})
        self.assertContains(hoja, 'Reporte de prefectura · Faltas justificadas y sin justificar')
        self.assertContains(hoja, 'Generado por')

    def test_cada_tipo_de_reporte_se_genera(self):
        for tipo in ('asistencia', 'justificaciones', 'conducta', 'reincidencias', 'medidas', 'suspensiones', 'pendientes', 'historial'):
            with self.subTest(tipo=tipo):
                self.assertEqual(self.client.get(reverse('prefectura:reportes'), {'reporte': tipo, 'alumnos': [self.alumno.pk]}).status_code, 200)
                self.assertEqual(self.client.get(reverse('prefectura:reporte_excel'), {'reporte': tipo, 'alumnos': [self.alumno.pk]}).status_code, 200)

    def test_exportar_es_un_permiso_aparte(self):
        from Usuarios.iniciales import _crear_rol
        consulta = _crear_rol('Prefectura de consulta', '', 6, {'Prefectura.consultar'}, es_prefectura=True)
        cuenta = crear_usuario('consulta', consulta)
        self.alcance(usuario=cuenta, niveles=['PRIMARIA'])
        self.client.force_login(cuenta)
        self.assertEqual(self.client.get(reverse('prefectura:reportes')).status_code, 200)
        for nombre in ('prefectura:reporte_excel', 'prefectura:reporte_imprimir', 'prefectura:asistencia_reporte'):
            self.assertEqual(self.client.get(reverse(nombre)).status_code, 403, nombre)
