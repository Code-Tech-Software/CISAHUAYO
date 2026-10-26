"""Registro de conducta: alta con el contexto escolar congelado, validaciones, suspensiones, trazabilidad, evidencias
protegidas, contactos con la familia, reincidencia, pendientes y el expediente del estudiante."""
from datetime import timedelta

from django.core import mail
from django.test import Client, override_settings
from django.urls import reverse

from Alumnos.models import CicloEscolar, Grado, TutorAlumno
from CISAHUAYO.pruebas import PRUEBAS, crear_grupo, crear_tutor, crear_usuario, hoy, inscribir_antes

from . import reglas
from .models import (
    INCIDENCIA,
    POSITIVA,
    AvisoReincidencia,
    CambioConducta,
    ContactoTutor,
    EvidenciaConducta,
    RegistroConducta,
    ReglaReincidencia,
    Suspension,
)
from .pruebas import CARPETA, BaseConductaTestCase, borrar_carpeta, foto, pdf


def tearDownModule():
    borrar_carpeta()


@PRUEBAS
@override_settings(MEDIA_ROOT=CARPETA)
class AltaTests(BaseConductaTestCase):
    def test_toma_el_contexto_de_su_inscripcion_y_registra_quien(self):
        respuesta = self.registrar()
        registro = self.ultimo()
        self.assertRedirects(respuesta, reverse('conducta:detalle', args=[registro.pk]))
        self.assertEqual(
            (registro.ciclo, registro.nivel, registro.grado, registro.grupo, registro.grupo_texto, registro.periodo, registro.inscripcion),
            (self.ciclo, 'PRIMARIA', self.primaria, self.inscripcion.grupo, '4.º A', self.periodo, self.inscripcion),
        )
        self.assertEqual((registro.registrado_por, registro.tipo, registro.categoria_nombre, registro.motivo_nombre), (self.admin, INCIDENCIA, 'Convivencia', 'Agresión verbal'))
        self.assertEqual(registro.gravedad, 'MODERADA')   # la del motivo
        self.assertEqual(registro.cambios.get().accion, CambioConducta.CREADO)

    def test_el_contexto_no_cambia_si_despues_cambia_de_grupo_o_de_ciclo(self):
        self.registrar()
        registro = self.ultimo()
        grupo_b = crear_grupo(self.primaria, 'B')
        self.inscripcion.grupo = grupo_b
        self.inscripcion.save()
        siguiente = CicloEscolar.objects.create(nombre='2027-2028', fecha_inicio=self.ciclo.fecha_fin + timedelta(days=30),
                                                fecha_fin=self.ciclo.fecha_fin + timedelta(days=330))
        inscribir_antes(self.alumno, siguiente, Grado.objects.create(nivel='PRIMARIA', numero=5))
        registro.refresh_from_db()
        self.assertEqual((registro.grupo_texto, registro.grado, registro.nivel, registro.ciclo), ('4.º A', self.primaria, 'PRIMARIA', self.ciclo))
        self.assertContains(self.client.get(reverse('conducta:lista')), '4.º A')
        # Editarlo tampoco lo cambia
        self.client.post(reverse('conducta:editar', args=[registro.pk]), self.datos(descripcion='Le gritó a un compañero en el patio.'))
        registro.refresh_from_db()
        self.assertEqual(registro.grupo_texto, '4.º A')

    def test_sin_inscripcion_en_el_ciclo_de_la_fecha_no_se_registra(self):
        self.inscripcion.delete()
        respuesta = self.registrar()
        self.assertIn('fecha', respuesta.context['form'].errors)
        self.assertFalse(RegistroConducta.objects.exists())

    def test_la_fecha_no_puede_ser_futura(self):
        respuesta = self.registrar(fecha=(hoy() + timedelta(days=1)).isoformat())
        self.assertIn('fecha', respuesta.context['form'].errors)

    def test_categoria_y_motivo_del_nivel_y_del_tipo(self):
        respuesta = self.registrar(categoria=self.convivencia_sec.pk, motivo=self.agresion_sec.pk)
        self.assertIn('categoria', respuesta.context['form'].errors)        # de otro nivel
        respuesta = self.registrar(motivo=self.ayuda.pk)
        self.assertIn('motivo', respuesta.context['form'].errors)           # de otra categoría
        respuesta = self.registrar(tipo=POSITIVA)
        self.assertIn('categoria', respuesta.context['form'].errors)        # la categoría es de incidencias
        self.assertFalse(RegistroConducta.objects.exists())

    def test_una_conducta_positiva_no_lleva_medidas_ni_gravedad(self):
        positiva = {'tipo': POSITIVA, 'categoria': self.reconocimiento.pk, 'motivo': self.ayuda.pk, 'estado': 'CERRADO', 'observaciones_cierre': 'Reconocido frente al grupo.'}
        respuesta = self.registrar(**positiva, medidas=[self.amonestacion.pk])
        self.assertIn('medidas', respuesta.context['form'].errors)
        self.registrar(**positiva, gravedad='GRAVE')
        registro = self.ultimo()
        self.assertEqual((registro.tipo, registro.gravedad, registro.medidas_aplicadas.count()), (POSITIVA, '', 0))

    def test_varias_medidas_con_su_nombre_de_entonces(self):
        self.registrar(medidas=[self.amonestacion.pk, self.compromiso.pk], responsable=self.admin.pk, fecha_revision=hoy().isoformat())
        registro = self.ultimo()
        self.assertEqual(sorted(m.nombre for m in registro.medidas_aplicadas.all()), ['Amonestación verbal', 'Compromiso escrito'])
        self.amonestacion.nombre = 'Llamada de atención'
        self.amonestacion.save()
        self.assertIn('Amonestación verbal', [m.nombre for m in registro.medidas_aplicadas.all()])

    def test_una_medida_con_seguimiento_pide_responsable_y_fecha(self):
        respuesta = self.registrar(medidas=[self.compromiso.pk])
        errores = respuesta.context['form'].errors
        self.assertIn('responsable', errores)
        self.assertIn('fecha_revision', errores)

    def test_una_medida_de_otro_nivel_no_se_aplica(self):
        respuesta = self.registrar(medidas=[self.amonestacion_sec.pk])
        self.assertIn('medidas', respuesta.context['form'].errors)


@PRUEBAS
@override_settings(MEDIA_ROOT=CARPETA)
class SuspensionTests(BaseConductaTestCase):
    def suspension(self, inicio=1, fin=3, **cambios):
        datos = {
            'medidas': [self.suspender.pk], 'suspension_motivo': self.motivo_suspension.pk,
            'suspension_inicio': (hoy() + timedelta(days=inicio)).isoformat(), 'suspension_fin': (hoy() + timedelta(days=fin)).isoformat(),
            'suspension_autoriza': self.admin.pk, 'suspension_observaciones': 'Con aviso a la familia',
        }
        datos.update(cambios)
        return self.registrar(**datos)

    def test_requiere_motivo_fechas_y_quien_autoriza(self):
        respuesta = self.registrar(medidas=[self.suspender.pk])
        errores = respuesta.context['form'].errors
        for campo in ('suspension_motivo', 'suspension_inicio', 'suspension_fin', 'suspension_autoriza'):
            self.assertIn(campo, errores)
        self.assertFalse(Suspension.objects.exists())

    def test_el_termino_no_va_antes_del_inicio(self):
        respuesta = self.suspension(inicio=3, fin=1)
        self.assertIn('suspension_fin', respuesta.context['form'].errors)

    def test_queda_vinculada_al_registro_y_no_toca_la_asistencia(self):
        from Alumnos.models import AsistenciaGeneral, Justificacion
        self.suspension()
        suspension = Suspension.objects.get()
        self.assertEqual(suspension.registro, self.ultimo())
        self.assertEqual((suspension.motivo_nombre, suspension.autorizada_por, suspension.dias, suspension.estado), ('Agresión grave', self.admin, 3, Suspension.PROXIMA))
        self.assertFalse(AsistenciaGeneral.objects.exists())
        self.assertFalse(Justificacion.objects.exists())

    def test_advierte_una_suspension_superpuesta(self):
        self.suspension(inicio=1, fin=3)
        respuesta = self.suspension(inicio=2, fin=4)
        self.assertIn('confirmar_superposicion', respuesta.context['form'].errors)
        self.assertEqual(Suspension.objects.count(), 1)
        self.suspension(inicio=2, fin=4, confirmar_superposicion='on')
        self.assertEqual(Suspension.objects.count(), 2)
        self.assertContains(self.client.get(reverse('conducta:detalle', args=[self.ultimo().pk])), 'se cruza con otra')

    def test_sin_la_medida_no_hay_suspension(self):
        self.suspension()
        registro = self.ultimo()
        self.client.post(reverse('conducta:editar', args=[registro.pk]), self.datos(medidas=[self.amonestacion.pk]))
        # No se borra: queda cancelada, igual que su medida (anulada), con quién y por qué
        suspension = Suspension.objects.get()
        self.assertEqual((suspension.aprobacion, suspension.resuelta_por), ('CANCELADA', self.admin))
        self.assertEqual(registro.medidas_aplicadas.get(medida=self.suspender).estado, 'ANULADA')
        self.assertEqual(Suspension.objects.filter(aprobacion='APROBADA').count(), 0)


@PRUEBAS
@override_settings(MEDIA_ROOT=CARPETA)
class TrazabilidadTests(BaseConductaTestCase):
    def test_editar_deja_constancia_de_lo_que_cambio(self):
        self.registrar()
        registro = self.ultimo()
        self.client.post(reverse('conducta:editar', args=[registro.pk]), self.datos(motivo=self.empujon.pk, descripcion='Empujó a un compañero en la fila.'))
        cambio = registro.cambios.filter(accion=CambioConducta.EDITADO).get()
        cambiados = {fila[0]: fila[1:] for fila in cambio.cambios}
        self.assertEqual(cambiados['Motivo'], ['Agresión verbal', 'Empujones'])
        self.assertIn('Descripción', cambiados)
        self.assertEqual(cambio.usuario, self.admin)
        registro.refresh_from_db()
        self.assertEqual((registro.motivo_nombre, registro.modificado_por), ('Empujones', self.admin))

    def test_cerrar_y_reabrir_el_seguimiento(self):
        self.registrar()
        registro = self.ultimo()
        url = reverse('conducta:seguimiento', args=[registro.pk])
        self.client.post(url, {'estado': 'CERRADO', 'acuerdos': 'Ofreció disculpas', 'observaciones_cierre': 'Sin incidentes después'})
        registro.refresh_from_db()
        self.assertEqual((registro.estado, registro.cerrado_por), ('CERRADO', self.admin))
        self.assertIsNotNone(registro.cerrado_en)
        self.client.post(url, {'estado': 'EN_SEGUIMIENTO'})
        registro.refresh_from_db()
        self.assertIsNone(registro.cerrado_en)
        self.assertEqual([c.accion for c in registro.cambios.order_by('pk')], [CambioConducta.CREADO, CambioConducta.CERRADO, CambioConducta.REABIERTO])

    def test_anular_pide_motivo_y_lo_conserva_fuera_de_los_indicadores(self):
        self.registrar()
        registro = self.ultimo()
        url = reverse('conducta:anular', args=[registro.pk])
        self.assertIn('motivo', self.client.post(url, {'motivo': 'no'}).context['form'].errors)
        self.client.post(url, {'motivo': 'Se registró al estudiante equivocado.'})
        registro.refresh_from_db()
        self.assertEqual((registro.anulado, registro.anulado_por, registro.motivo_anulacion), (True, self.admin, 'Se registró al estudiante equivocado.'))
        self.assertEqual(self.client.get(reverse('conducta:lista')).context['pagina'].paginator.count, 0)
        self.assertEqual(self.client.get(reverse('conducta:lista'), {'registros': 'anulados'}).context['pagina'].paginator.count, 1)
        self.assertContains(self.client.get(reverse('conducta:detalle', args=[registro.pk])), 'Registro anulado')
        self.assertEqual(self.client.get(reverse('conducta:editar', args=[registro.pk])).status_code, 302)   # ya no se edita


@PRUEBAS
@override_settings(MEDIA_ROOT=CARPETA)
class EvidenciasTests(BaseConductaTestCase):
    def test_se_suben_al_registrar_y_solo_se_entregan_con_permiso(self):
        respuesta = self.client.post(reverse('conducta:crear'), {**self.datos(), 'evidencias': [foto(), pdf()]})
        self.assertEqual(respuesta.status_code, 302)
        evidencias = list(EvidenciaConducta.objects.order_by('pk'))
        self.assertEqual([e.tipo for e in evidencias], ['image/jpeg', 'application/pdf'])
        self.assertRegex(evidencias[0].archivo.name.rsplit('/', 1)[-1], r'^[0-9a-f]{32}\.jpg$')   # nombre al azar, no el original
        url = reverse('conducta:evidencia', args=[evidencias[0].pk])
        respuesta = self.client.get(url)
        self.assertEqual((respuesta.status_code, respuesta['Content-Type'], respuesta['X-Content-Type-Options']), (200, 'image/jpeg', 'nosniff'))
        self.assertIn('private', respuesta['Cache-Control'])
        detalle = self.client.get(reverse('conducta:detalle', args=[self.ultimo().pk])).content.decode()
        self.assertIn(url, detalle)
        self.assertNotIn(evidencias[0].archivo.name, detalle)   # nunca la dirección del almacenamiento
        self.client.force_login(self.sin_permisos)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(Client().get(url).status_code, 302)

    def test_se_valida_tipo_y_contenido(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        falso = SimpleUploadedFile('foto.jpg', b'no es una imagen', content_type='image/jpeg')
        ejecutable = SimpleUploadedFile('virus.exe', b'MZ...', content_type='application/octet-stream')
        for archivo in (falso, ejecutable):
            respuesta = self.client.post(reverse('conducta:crear'), {**self.datos(), 'evidencias': [archivo]})
            self.assertEqual(respuesta.status_code, 200)
            self.assertTrue(respuesta.context['form'].non_field_errors())
        self.assertFalse(RegistroConducta.objects.exists())

    def test_agregar_y_quitar_deja_constancia(self):
        self.registrar()
        registro = self.ultimo()
        self.client.post(reverse('conducta:evidencias_agregar', args=[registro.pk]), {'evidencias': [foto('otra.jpg')]})
        evidencia = EvidenciaConducta.objects.get()
        self.client.post(reverse('conducta:evidencia_quitar', args=[evidencia.pk]))
        evidencia.refresh_from_db()
        self.assertEqual((evidencia.activa, evidencia.quitada_por), (False, self.admin))
        acciones = list(registro.cambios.values_list('accion', flat=True))
        self.assertIn(CambioConducta.EVIDENCIA, acciones)
        self.assertIn(CambioConducta.EVIDENCIA_QUITADA, acciones)


@PRUEBAS
@override_settings(MEDIA_ROOT=CARPETA)
class FamiliaReincidenciaYPendientesTests(BaseConductaTestCase):
    def test_contacto_con_la_familia_sin_enviar_mensajes(self):
        tutor = crear_tutor(nombre='Rosa')
        TutorAlumno.objects.create(tutor=tutor, alumno=self.alumno, parentesco='MADRE', activo=True)
        self.registrar()
        registro = self.ultimo()
        url = reverse('conducta:contacto_crear', args=[registro.pk])
        respuesta = self.client.post(url, {'fecha': hoy().isoformat(), 'tutor': 'otra', 'medio': 'TELEFONO', 'acuerdos': 'Platicar en casa'})
        self.assertIn('persona', respuesta.context['form'].errors)
        self.client.post(url, {
            'fecha': hoy().isoformat(), 'tutor': tutor.pk, 'medio': 'TELEFONO', 'acuerdos': 'Platicar en casa',
            'proxima_revision': (hoy() + timedelta(days=3)).isoformat(), 'evidencia': pdf('acuse.pdf'),
        })
        contacto = ContactoTutor.objects.get()
        self.assertEqual((contacto.tutor, contacto.persona, contacto.registrado_por), (tutor, 'Rosa Mora (madre)', self.admin))
        self.assertEqual(self.client.get(reverse('conducta:acuse', args=[contacto.pk]))['Content-Type'], 'application/pdf')
        self.assertEqual(mail.outbox, [])
        self.assertIn(contacto, reglas.pendientes()['acuerdos'])

    def test_aviso_de_reincidencia_sin_sancionar(self):
        ReglaReincidencia.objects.create(nivel='PRIMARIA', incidencias=2, dias=10)
        self.registrar(fecha=(hoy() - timedelta(days=20)).isoformat())
        self.registrar(fecha=(hoy() - timedelta(days=5)).isoformat())
        self.assertFalse(AvisoReincidencia.objects.exists())   # fuera del intervalo
        respuesta = self.registrar(fecha=hoy().isoformat())
        aviso = AvisoReincidencia.objects.get()
        self.assertEqual((aviso.cantidad, aviso.registro, aviso.alumno), (2, self.ultimo(), self.alumno))
        self.assertEqual(self.ultimo().medidas_aplicadas.count(), 0)   # no aplica sanciones
        self.assertContains(self.client.get(respuesta['Location']), 'Aviso de reincidencia')
        self.assertIn(aviso, reglas.pendientes()['avisos'])
        self.client.post(reverse('conducta:aviso_revisar', args=[aviso.pk]), {'nota': 'Se habló con la familia'})
        aviso.refresh_from_db()
        self.assertEqual((aviso.revisado, aviso.revisado_por), (True, self.admin))
        self.assertNotIn(aviso, reglas.pendientes()['avisos'])

    def test_panel_de_pendientes(self):
        self.registrar(medidas=[self.compromiso.pk], responsable=self.admin.pk, fecha_revision=hoy().isoformat(),
                       fecha=(hoy() - timedelta(days=4)).isoformat())
        vencido = self.ultimo()
        RegistroConducta.objects.filter(pk=vencido.pk).update(fecha_revision=hoy() - timedelta(days=1))
        self.registrar(medidas=[self.suspender.pk], suspension_motivo=self.motivo_suspension.pk, suspension_inicio=hoy().isoformat(),
                       suspension_fin=(hoy() + timedelta(days=2)).isoformat(), suspension_autoriza=self.admin.pk)
        respuesta = self.client.get(reverse('conducta:pendientes'))
        self.assertEqual([r.pk for r in respuesta.context['vencidos']], [vencido.pk])
        self.assertEqual(len(respuesta.context['suspensiones']), 1)
        self.assertContains(respuesta, reverse('conducta:detalle', args=[vencido.pk]))
        self.assertGreaterEqual(reglas.cuantos_pendientes(), 1)


@PRUEBAS
@override_settings(MEDIA_ROOT=CARPETA)
class ColegioYExpedienteTests(BaseConductaTestCase):
    def test_el_administrador_ve_y_registra_en_todo_el_colegio(self):
        self.registrar()
        self.registrar(alumno=self.otro.pk, categoria=self.convivencia_sec.pk, motivo=self.agresion_sec.pk)
        lista = self.client.get(reverse('conducta:lista'))
        self.assertEqual(lista.context['pagina'].paginator.count, 2)
        self.assertEqual(self.client.get(reverse('conducta:lista'), {'nivel': 'SECUNDARIA'}).context['pagina'].paginator.count, 1)
        self.assertEqual(self.client.get(reverse('conducta:lista'), {'q': self.otro.referencia}).context['pagina'].paginator.count, 1)
        busqueda = self.client.get(reverse('conducta:buscar'), {'q': 'Zoe'}).json()['resultados']
        self.assertEqual([r['id'] for r in busqueda], [self.otro.pk])
        opciones = self.client.get(reverse('conducta:opciones'), {'alumno': self.otro.pk, 'fecha': hoy().isoformat()}).json()
        self.assertEqual((opciones['contexto']['nivel'], [c['id'] for c in opciones['opciones']['categorias']]), ('SECUNDARIA', [self.convivencia_sec.pk]))

    def test_filtrar_por_medida_no_repite_registros(self):
        self.registrar(medidas=[self.amonestacion.pk, self.compromiso.pk], responsable=self.admin.pk, fecha_revision=hoy().isoformat())
        self.assertEqual(self.client.get(reverse('conducta:lista'), {'medida': self.amonestacion.pk}).context['pagina'].paginator.count, 1)
        self.assertEqual(self.client.get(reverse('conducta:lista'), {'suspension': 'con'}).context['pagina'].paginator.count, 0)

    def test_el_expediente_muestra_su_linea_de_tiempo(self):
        self.registrar()
        self.registrar(tipo=POSITIVA, categoria=self.reconocimiento.pk, motivo=self.ayuda.pk, estado='CERRADO', observaciones_cierre='Reconocido frente al grupo.')
        respuesta = self.client.get(reverse('alumnos:detalle', args=[self.alumno.pk]))
        self.assertContains(respuesta, 'id="tab-conducta"')
        conducta = respuesta.context['conducta']
        self.assertEqual((conducta['incidencias'], conducta['positivas']), (1, 1))
        self.assertContains(respuesta, 'Ayuda a compañeros')
        sin_permiso = crear_usuario('vero', None)
        from django.contrib.auth.models import Permission
        sin_permiso.user_permissions.add(Permission.objects.get(codename='view_alumno', content_type__app_label='Alumnos'))
        self.client.force_login(sin_permiso)
        respuesta = self.client.get(reverse('alumnos:detalle', args=[self.alumno.pk]))
        self.assertNotContains(respuesta, 'id="tab-conducta"')
