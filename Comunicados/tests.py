"""Comunicados: alcance por nivel (en el servidor, aunque se altere la petición), envío sin duplicados, tutores con varios
hijos, lectura única, privacidad de los destinatarios, expiración, archivos, eliminación, pantallas y avisos."""
import io
import json
import shutil
import tempfile
import uuid
from datetime import timedelta

from channels.testing import WebsocketCommunicator
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Permission
from django.contrib.sessions.backends.db import SessionStore
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from CISAHUAYO import portales
from CISAHUAYO.pruebas import (
    PRUEBAS, BaseTestCase, ciclo_actual_de_prueba, crear_alumno, crear_grado, crear_grupo, crear_profesor, crear_rol, crear_tutor,
    crear_usuario, inscribir_antes, materia_en_grado, vincular,
)
from Usuarios.models import PerfilUsuario, Rol

from . import reglas
from .alcance import alcance_de
from .models import Adjunto, Comunicado, Destinatario

# Los archivos de las pruebas van a una carpeta temporal (no a la del proyecto)
CARPETA = tempfile.mkdtemp(prefix='cisahuayo-comunicados-')
ARCHIVOS_TEMPORALES = override_settings(MEDIA_ROOT=CARPETA)
INICIO = reverse('comunicados:inicio')
CREAR = reverse('comunicados:crear')
DESTINATARIOS = reverse('comunicados:destinatarios')
EMISOR = ('Comunicados.seguimiento', 'Comunicados.enviar', 'Comunicados.eliminar')


def entrar_al_portal(cliente, tipo, cuenta):
    sesion = cliente.session
    sesion[portales.CLAVE_DE_SESION] = {'tipo': tipo, 'id': cuenta.pk, 'huella': portales._huella(tipo, cuenta)}
    sesion.save()


def png(nombre='foto.png'):
    from PIL import Image
    contenido = io.BytesIO()
    Image.new('RGB', (4, 4), (200, 50, 50)).save(contenido, 'PNG')
    return SimpleUploadedFile(nombre, contenido.getvalue(), content_type='image/png')


def pdf(nombre='circular.pdf'):
    return SimpleUploadedFile(nombre, b'%PDF-1.4 contenido de prueba', content_type='application/pdf')


class Colegio:
    """Primaria: 2.º A (Lucía y Paula; Matemáticas de Laura) y 2.º B (Hugo); Secundaria: 1.º A (Zoe, hermana de Lucía; Álgebra
    de Carmen). Ana es tutora de Lucía y de Zoe (un nivel cada una); Rubén, de Paula; Óscar, de Hugo pero sin recibir
    notificaciones. Laura envía comunicados (docente de primaria); Carmen solo recibe; Dirección de secundaria envía por los
    niveles asignados en su cuenta."""

    def armar(self):
        self.ciclo = ciclo_actual_de_prueba()
        self.segundo = crear_grado('PRIMARIA', 2)
        self.segundo_a = self.segundo.grupos.get()
        self.segundo_b = crear_grupo(self.segundo, 'B')
        self.secundaria = crear_grado('SECUNDARIA', 1)
        self.lucia = crear_alumno(nombre='Lucía', apellido_paterno='Herrera', apellido_materno='Campos', curp='COMUNICA000000LU01')
        self.paula = crear_alumno(nombre='Paula', apellido_paterno='Romero', apellido_materno='Castro', curp='COMUNICA000000PA01')
        self.hugo = crear_alumno(nombre='Hugo', apellido_paterno='Martínez', apellido_materno='Sánchez', curp='COMUNICA000000HU01')
        self.zoe = crear_alumno(nombre='Zoe', apellido_paterno='Herrera', apellido_materno='Campos', curp='COMUNICA000000ZO01')
        self.sin_inscripcion = crear_alumno(nombre='Iván', curp='COMUNICA000000IV01')
        inscribir_antes(self.lucia, self.ciclo, self.segundo, grupo=self.segundo_a)
        inscribir_antes(self.paula, self.ciclo, self.segundo, grupo=self.segundo_a)
        inscribir_antes(self.hugo, self.ciclo, self.segundo, grupo=self.segundo_b)
        inscribir_antes(self.zoe, self.ciclo, self.secundaria)

        self.ana = crear_tutor(nombre='Ana', apellido_paterno='Campos', apellido_materno='Vega', usuario='ana.campos')
        self.ruben = crear_tutor(nombre='Rubén', apellido_paterno='Romero', usuario='ruben.romero')
        self.oscar = crear_tutor(nombre='Óscar', apellido_paterno='Martínez', usuario='oscar.martinez')
        vincular(self.ana, self.lucia)
        vincular(self.ana, self.zoe)
        vincular(self.ruben, self.paula, parentesco='PADRE')
        vincular(self.oscar, self.hugo, parentesco='PADRE', recibe_notificaciones=False)

        self.docente_emisor = crear_rol('Docente que envía', {'Comunicados.recibir', *EMISOR}, es_docente=True)
        self.laura = crear_usuario('laura', self.docente_emisor)
        self.prof_laura = crear_profesor(niveles=('PRIMARIA',), usuario=self.laura, nombre='Laura')
        self.mat = materia_en_grado('MAT', self.segundo, self.ciclo, grupo=self.segundo_a, profesor=self.prof_laura)
        self.carmen = crear_usuario('carmen', Rol.objects.get(grupo__name='Docente'))
        self.prof_carmen = crear_profesor(niveles=('SECUNDARIA',), usuario=self.carmen, nombre='Carmen', telefono='3530002222')
        self.alg = materia_en_grado('ALG', self.secundaria, self.ciclo, profesor=self.prof_carmen)
        self.sin_cuenta = crear_profesor(niveles=('PRIMARIA',), nombre='Rosa', telefono='3530003333')

        self.direccion_sec = crear_usuario('direccion', crear_rol('Comunicados de secundaria', set(EMISOR)))
        perfil = PerfilUsuario.de(self.direccion_sec)
        perfil.niveles_comunicados = ['SECUNDARIA']
        perfil.save()
        self.sin_niveles = crear_usuario('sinniveles', crear_rol('Envía sin niveles', set(EMISOR)))

    def datos(self, **cambios):
        datos = {
            'titulo': 'Excursión a la Granja Escuela', 'descripcion': 'El viernes iremos a la granja.', 'clave_envio': str(uuid.uuid4()),
            'destinatarios': json.dumps({'tutores': [self.ana.pk], 'estudiantes': [self.lucia.pk], 'profesores': []}),
        }
        datos.update(cambios)
        return datos

    def enviar(self, usuario=None, seleccion=None, **cambios):
        seleccion = seleccion or {Destinatario.TUTOR: {self.ana.pk}, Destinatario.ESTUDIANTE: {self.lucia.pk}}
        comunicado, _ = reglas.enviar(
            usuario or self.laura, titulo=cambios.get('titulo', 'Reunión de familias'), descripcion=cambios.get('descripcion', 'Los esperamos.'),
            urgente=cambios.get('urgente', False), expira=cambios.get('expira'), clave_envio=uuid.uuid4(), seleccion=seleccion,
            archivos=cambios.get('archivos', ()),
        )
        return comunicado


@PRUEBAS
class AlcanceTests(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()

    def ids(self, usuario, tipo):
        usuario = type(usuario).objects.get(pk=usuario.pk)   # sin el alcance guardado de otra consulta
        return set(alcance_de(usuario).consulta_de(tipo).values_list('pk', flat=True))

    def test_el_administrador_llega_a_todo_el_colegio(self):
        self.assertEqual(self.ids(self.admin, Destinatario.ESTUDIANTE), {self.lucia.pk, self.paula.pk, self.hugo.pk, self.zoe.pk, self.sin_inscripcion.pk})
        self.assertEqual(self.ids(self.admin, Destinatario.PROFESOR), {self.prof_laura.pk, self.prof_carmen.pk})   # sin cuenta, no
        self.assertTrue(alcance_de(self.admin).total)

    def test_un_docente_llega_a_su_nivel_completo_y_no_solo_a_sus_materias(self):
        # Laura da Matemáticas en 2.º A, pero su alcance es Primaria: también 2.º B; nunca Secundaria
        self.assertEqual(self.ids(self.laura, Destinatario.ESTUDIANTE), {self.lucia.pk, self.paula.pk, self.hugo.pk})
        self.assertEqual(self.ids(self.laura, Destinatario.PROFESOR), set())   # ella misma no; Carmen es de secundaria
        self.assertEqual(alcance_de(self.laura).niveles, frozenset({'PRIMARIA'}))

    def test_los_niveles_asignados_en_la_cuenta_y_la_union_de_varios(self):
        self.assertEqual(self.ids(self.direccion_sec, Destinatario.ESTUDIANTE), {self.zoe.pk})
        self.assertEqual(self.ids(self.direccion_sec, Destinatario.PROFESOR), {self.prof_carmen.pk})
        perfil = PerfilUsuario.de(self.laura)
        perfil.niveles_comunicados = ['SECUNDARIA']
        perfil.save()
        self.assertEqual(self.ids(self.laura, Destinatario.ESTUDIANTE), {self.lucia.pk, self.paula.pk, self.hugo.pk, self.zoe.pk})

    def test_sin_niveles_no_envia(self):
        self.assertFalse(alcance_de(self.sin_niveles).puede_enviar)
        self.client.force_login(self.sin_niveles)
        self.assertContains(self.client.get(INICIO), 'Todavía no puedes enviar comunicados')
        self.assertEqual(self.client.get(DESTINATARIOS).status_code, 403)
        respuesta = self.client.post(CREAR, self.datos(), HTTP_ACCEPT='application/json')
        self.assertEqual(respuesta.status_code, 403)
        self.assertFalse(Comunicado.objects.exists())

    def test_un_tutor_cuenta_si_algun_hijo_es_del_alcance_y_solo_se_muestran_esos_hijos(self):
        self.assertIn(self.ana.pk, self.ids(self.laura, Destinatario.TUTOR))
        self.assertIn(self.ana.pk, self.ids(self.direccion_sec, Destinatario.TUTOR))
        universo = alcance_de(self.laura).universo()
        ana = next(t for t in universo['tutores'] if t['id'] == self.ana.pk)
        self.assertEqual(ana['hijos'], [self.lucia.pk])   # Zoe es de secundaria: no se le muestra a Laura
        self.assertNotIn(self.zoe.pk, {e['id'] for e in universo['estudiantes']})

    def test_un_vinculo_sin_notificaciones_no_cuenta(self):
        self.assertNotIn(self.oscar.pk, self.ids(self.laura, Destinatario.TUTOR))

    def test_el_arbol_es_nivel_grado_grupo_materia_del_ciclo_actual(self):
        arbol = alcance_de(self.laura).universo()['arbol']
        self.assertEqual([n['clave'] for n in arbol], ['PRIMARIA'])
        grupos = arbol[0]['grados'][0]['grupos']
        self.assertEqual([g['nombre'] for g in grupos], ['2.º A', '2.º B'])
        self.assertEqual([m['id'] for m in grupos[0]['materias']], [self.mat.pk])

    def test_la_seleccion_fuera_del_alcance_se_rechaza_aunque_se_altere_la_peticion(self):
        self.client.force_login(self.laura)
        for seleccion in ({'estudiantes': [self.zoe.pk]}, {'profesores': [self.prof_carmen.pk]}, {'tutores': [self.oscar.pk]},
                          {'estudiantes': [999999]}):
            with self.subTest(seleccion=seleccion):
                respuesta = self.client.post(CREAR, self.datos(destinatarios=json.dumps(seleccion)), HTTP_ACCEPT='application/json')
                self.assertEqual(respuesta.status_code, 400)
                self.assertIn('destinatarios', respuesta.json()['errores'])
        self.assertFalse(Comunicado.objects.exists())

    def test_el_selector_solo_trae_el_alcance(self):
        self.client.force_login(self.laura)
        datos = self.client.get(DESTINATARIOS).json()
        self.assertEqual({e['id'] for e in datos['estudiantes']}, {self.lucia.pk, self.paula.pk, self.hugo.pk})
        self.assertEqual(datos['alcance']['descripcion'], 'Primaria')
        self.assertNotIn('Zoe', json.dumps(datos))


@PRUEBAS
@ARCHIVOS_TEMPORALES
class EnvioTests(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()
        self.client.force_login(self.laura)

    def test_enviar_guarda_destinatarios_unicos_con_su_detalle(self):
        respuesta = self.client.post(CREAR, self.datos(destinatarios=json.dumps({
            'tutores': [self.ana.pk, self.ruben.pk, self.ana.pk], 'estudiantes': [self.lucia.pk, self.paula.pk]})), HTTP_ACCEPT='application/json')
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        comunicado = Comunicado.objects.get()
        self.assertEqual(comunicado.destinatarios.count(), 4)
        ana = comunicado.destinatarios.get(tutor=self.ana)
        self.assertEqual(ana.detalle, 'Tutor de Lucía Herrera Campos')   # sin Zoe, fuera del alcance de Laura
        self.assertEqual(comunicado.destinatarios.get(alumno=self.lucia).detalle, '2.º A · Primaria')
        self.assertEqual(comunicado.rol_autor, 'Docente que envía')
        self.assertTrue(LogEntry.objects.filter(object_id=str(comunicado.pk)).exists())

    def test_un_doble_envio_con_la_misma_clave_crea_un_solo_comunicado(self):
        datos = self.datos()
        for _ in range(3):
            self.assertEqual(self.client.post(CREAR, datos, HTTP_ACCEPT='application/json').status_code, 200)
        self.assertEqual(Comunicado.objects.count(), 1)

    def test_validaciones_del_formulario(self):
        casos = {
            'titulo': self.datos(titulo='   '),
            'descripcion': self.datos(descripcion=''),
            'destinatarios': self.datos(destinatarios=json.dumps({'tutores': []})),
            'expira': self.datos(expira_fecha=(timezone.localdate() - timedelta(days=1)).isoformat()),
        }
        for campo, datos in casos.items():
            with self.subTest(campo=campo):
                respuesta = self.client.post(CREAR, datos, HTTP_ACCEPT='application/json')
                self.assertEqual(respuesta.status_code, 400)
                self.assertIn(campo, respuesta.json()['errores'])
        respuesta = self.client.post(CREAR, self.datos(destinatarios='{"tutores": "x"}'), HTTP_ACCEPT='application/json')
        self.assertIn('destinatarios', respuesta.json()['errores'])
        self.assertFalse(Comunicado.objects.exists())

    def test_la_expiracion_sin_hora_es_al_final_del_dia(self):
        manana = timezone.localdate() + timedelta(days=1)
        self.client.post(CREAR, self.datos(expira_fecha=manana.isoformat()), HTTP_ACCEPT='application/json')
        expira = timezone.localtime(Comunicado.objects.get().expira)
        self.assertEqual((expira.date(), expira.hour, expira.minute), (manana, 23, 59))

    def test_archivos_limites_y_tipos(self):
        datos = self.datos()
        datos['archivos'] = [png(f'foto{i}.png') for i in range(6)]
        respuesta = self.client.post(CREAR, datos, HTTP_ACCEPT='application/json')
        self.assertIn('archivos', respuesta.json()['errores'])
        datos = self.datos()
        datos['archivos'] = [SimpleUploadedFile('virus.exe', b'MZ...', content_type='application/octet-stream')]
        self.assertIn('archivos', self.client.post(CREAR, datos, HTTP_ACCEPT='application/json').json()['errores'])
        datos = self.datos()
        datos['archivos'] = [SimpleUploadedFile('falsa.png', b'no es una imagen', content_type='image/png')]
        self.assertIn('archivos', self.client.post(CREAR, datos, HTTP_ACCEPT='application/json').json()['errores'])
        self.assertFalse(Comunicado.objects.exists())
        datos = self.datos()
        datos['archivos'] = [png(), pdf()]
        self.assertEqual(self.client.post(CREAR, datos, HTTP_ACCEPT='application/json').status_code, 200)
        self.assertEqual(list(Adjunto.objects.values_list('nombre_original', 'tipo')), [('foto.png', 'image/png'), ('circular.pdf', 'application/pdf')])

    def test_la_lista_de_destinatarios_queda_fija(self):
        comunicado = self.enviar(seleccion={Destinatario.ESTUDIANTE: {self.lucia.pk, self.paula.pk}})
        nuevo = crear_alumno(nombre='Nueva', curp='COMUNICA000000NU01')
        inscribir_antes(nuevo, self.ciclo, self.segundo, grupo=self.segundo_a)
        self.assertEqual(comunicado.destinatarios.count(), 2)


@PRUEBAS
class LecturaYPrivacidadTests(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()
        self.comunicado = self.enviar(seleccion={Destinatario.TUTOR: {self.ana.pk, self.ruben.pk}, Destinatario.ESTUDIANTE: {self.lucia.pk},
                                                 Destinatario.PROFESOR: set()})
        self.client.logout()
        entrar_al_portal(self.client, portales.TUTOR, self.ana)
        self.url_ana = reverse('portal_tutores:comunicados:recibido', args=[self.comunicado.pk])

    def test_abrir_el_detalle_guarda_una_sola_primera_lectura(self):
        copia = Destinatario.objects.get(tutor=self.ana)
        self.assertIsNone(copia.leido_en)
        self.assertContains(self.client.get(reverse('portal_tutores:comunicados:inicio')), 'Reunión de familias')
        copia.refresh_from_db()
        self.assertIsNone(copia.leido_en)   # la tarjeta no cuenta como lectura
        self.assertEqual(self.client.get(self.url_ana).status_code, 200)
        copia.refresh_from_db()
        primera = copia.leido_en
        self.assertIsNotNone(primera)
        self.client.get(self.url_ana)
        copia.refresh_from_db()
        self.assertEqual(copia.leido_en, primera)

    def test_el_seguimiento_del_autor_y_del_administrador_no_marca_lecturas(self):
        for usuario in (self.laura, self.admin):
            self.client.force_login(usuario)
            respuesta = self.client.get(reverse('comunicados:detalle', args=[self.comunicado.pk]))
            self.assertContains(respuesta, 'Lista de destinatarios')
            self.assertContains(respuesta, 'Rubén')
        self.assertFalse(Destinatario.objects.filter(leido_en__isnull=False).exists())

    def test_contadores_y_porcentajes_sobre_destinatarios_unicos(self):
        self.client.get(self.url_ana)
        comunicado = reglas.preparar(reglas.con_estadisticas(Comunicado.objects.filter(pk=self.comunicado.pk)).get())
        self.assertEqual((comunicado.leidos, comunicado.total, comunicado.porcentaje), (1, 3, 33))
        self.assertEqual(comunicado.resumen_destinatarios, '2 tutores · 1 estudiante')
        self.assertEqual((reglas.porcentaje(0, 0), reglas.porcentaje(1, 200), reglas.porcentaje(199, 200), reglas.porcentaje(5, 5)), (0, 1, 99, 100))

    def test_quien_recibe_no_ve_a_los_demas_destinatarios(self):
        respuesta = self.client.get(self.url_ana)
        self.assertContains(respuesta, 'Reunión de familias')
        self.assertContains(respuesta, 'Tu lectura')
        for ajeno in ('Rubén', 'Paula', 'Lista de destinatarios', 'Estado de lectura'):
            self.assertNotContains(respuesta, ajeno)
        # Ni el seguimiento del sistema (no es una cuenta del sistema)
        self.assertEqual(self.client.get(reverse('comunicados:detalle', args=[self.comunicado.pk])).status_code, 302)

    def test_quien_no_lo_recibio_no_lo_abre(self):
        self.client.logout()
        entrar_al_portal(self.client, portales.TUTOR, self.oscar)
        self.assertEqual(self.client.get(reverse('portal_tutores:comunicados:recibido', args=[self.comunicado.pk])).status_code, 404)

    def test_otro_emisor_del_mismo_nivel_no_ve_los_comunicados_ajenos(self):
        otra = crear_usuario('otra', self.docente_emisor)
        crear_profesor(niveles=('PRIMARIA',), usuario=otra, nombre='Otra', telefono='3530004444')
        self.client.force_login(otra)
        self.assertNotContains(self.client.get(INICIO), 'Reunión de familias')
        self.assertEqual(self.client.get(reverse('comunicados:detalle', args=[self.comunicado.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('comunicados:recibido', args=[self.comunicado.pk])).status_code, 404)

    def test_el_estudiante_lo_ve_en_su_portal(self):
        self.client.logout()
        entrar_al_portal(self.client, portales.ESTUDIANTE, self.lucia)
        respuesta = self.client.get(reverse('portal_estudiantes:comunicados:inicio'))
        self.assertContains(respuesta, 'Reunión de familias')
        self.assertContains(respuesta, 'data-comunicados-pendientes')   # el contador del menú
        self.client.get(reverse('portal_estudiantes:comunicados:recibido', args=[self.comunicado.pk]))
        self.assertIsNotNone(Destinatario.objects.get(alumno=self.lucia).leido_en)

    def test_un_profesor_lo_recibe_en_el_sistema(self):
        comunicado = self.enviar(self.direccion_sec, seleccion={Destinatario.PROFESOR: {self.prof_carmen.pk}}, titulo='Junta de academia')
        self.client.force_login(self.carmen)
        self.assertContains(self.client.get(f'{INICIO}?vista=recibidos'), 'Junta de academia')
        self.assertEqual(self.client.get(reverse('comunicados:recibido', args=[comunicado.pk])).status_code, 200)
        self.assertIsNotNone(Destinatario.objects.get(profesor=self.prof_carmen).leido_en)
        self.assertEqual(self.client.get(reverse('comunicados:detalle', args=[comunicado.pk])).status_code, 403)   # sin seguimiento


@PRUEBAS
@ARCHIVOS_TEMPORALES
class ExpiracionYArchivosTests(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()
        self.comunicado = self.enviar(seleccion={Destinatario.TUTOR: {self.ana.pk}}, archivos=[(png(), 'image/png')],
                                      expira=timezone.now() + timedelta(hours=2))
        self.adjunto = self.comunicado.adjuntos.get()
        self.client.logout()
        entrar_al_portal(self.client, portales.TUTOR, self.ana)

    def test_el_destinatario_descarga_mientras_esta_activo(self):
        respuesta = self.client.get(reverse('portal_tutores:comunicados:adjunto', args=[self.adjunto.pk]))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta['Content-Type'], 'image/png')
        self.client.logout()
        entrar_al_portal(self.client, portales.TUTOR, self.ruben)
        self.assertEqual(self.client.get(reverse('portal_tutores:comunicados:adjunto', args=[self.adjunto.pk])).status_code, 404)

    def test_al_caducar_el_destinatario_ya_no_lo_ve_ni_por_enlace_directo(self):
        Comunicado.objects.filter(pk=self.comunicado.pk).update(expira=timezone.now() - timedelta(minutes=1))
        self.assertNotContains(self.client.get(reverse('portal_tutores:comunicados:inicio')), 'Reunión de familias')
        self.assertEqual(self.client.get(reverse('portal_tutores:comunicados:recibido', args=[self.comunicado.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('portal_tutores:comunicados:adjunto', args=[self.adjunto.pk])).status_code, 404)
        # El autor conserva el histórico y sus archivos
        self.client.force_login(self.laura)
        self.assertContains(self.client.get(f'{INICIO}?vista=enviados&estado=caducados'), 'Reunión de familias')
        self.assertNotContains(self.client.get(f'{INICIO}?vista=enviados&estado=activos'), 'Reunión de familias')
        self.assertContains(self.client.get(reverse('comunicados:detalle', args=[self.comunicado.pk])), 'Caducado')
        self.assertEqual(self.client.get(reverse('comunicados:adjunto', args=[self.adjunto.pk])).status_code, 200)


@PRUEBAS
class EliminarTests(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()
        self.comunicado = self.enviar(seleccion={Destinatario.TUTOR: {self.ana.pk}})

    def test_el_autor_elimina_el_suyo_y_queda_registrado(self):
        self.client.force_login(self.laura)
        respuesta = self.client.post(reverse('comunicados:eliminar', args=[self.comunicado.pk]), {'vista': 'enviados'})
        self.assertRedirects(respuesta, f'{INICIO}?vista=enviados', fetch_redirect_response=False)
        self.comunicado.refresh_from_db()
        self.assertTrue(self.comunicado.eliminado)
        self.assertEqual(self.comunicado.eliminado_por, self.laura)
        self.assertTrue(LogEntry.objects.filter(object_id=str(self.comunicado.pk), change_message__contains='Eliminó').exists())
        self.client.logout()
        entrar_al_portal(self.client, portales.TUTOR, self.ana)
        self.assertEqual(self.client.get(reverse('portal_tutores:comunicados:recibido', args=[self.comunicado.pk])).status_code, 404)

    def test_nadie_mas_lo_elimina_salvo_el_administrador(self):
        self.client.force_login(self.direccion_sec)
        self.assertEqual(self.client.post(reverse('comunicados:eliminar', args=[self.comunicado.pk])).status_code, 404)
        self.client.post(reverse('comunicados:eliminar_varios'), {'comunicados': [self.comunicado.pk]})
        self.assertFalse(Comunicado.objects.get(pk=self.comunicado.pk).eliminado)
        self.client.force_login(self.admin)
        self.client.post(reverse('comunicados:eliminar_varios'), {'comunicados': [self.comunicado.pk], 'vista': 'gestion'})
        self.assertTrue(Comunicado.objects.get(pk=self.comunicado.pk).eliminado)

    def test_sin_permiso_de_eliminar_no_se_elimina_lo_propio(self):
        solo_envia = crear_usuario('soloenvia', crear_rol('Solo envía', {'Comunicados.enviar'}))
        perfil = PerfilUsuario.de(solo_envia)
        perfil.niveles_comunicados = ['PRIMARIA']
        perfil.save()
        propio = self.enviar(solo_envia)
        self.client.force_login(solo_envia)
        self.assertEqual(self.client.post(reverse('comunicados:eliminar', args=[propio.pk])).status_code, 403)
        self.assertFalse(Comunicado.objects.get(pk=propio.pk).eliminado)


@PRUEBAS
class PantallasTests(Colegio, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.armar()

    def test_la_pantalla_principal_con_sus_tarjetas(self):
        urgente = self.enviar(titulo='Excursión urgente', urgente=True)
        self.enviar(titulo='Calendario escolar')
        self.client.force_login(self.laura)
        respuesta = self.client.get(INICIO)
        self.assertContains(respuesta, '2 comunicados')
        self.assertContains(respuesta, 'Buscar comunicados…')
        self.assertContains(respuesta, 'Crear comunicado')
        self.assertContains(respuesta, 'Filtrar por fecha de creación')
        self.assertContains(respuesta, 'tarjeta-comunicado--urgente', count=1)
        self.assertContains(respuesta, '0/2 leídos')
        self.assertContains(respuesta, '1 tutor · 1 estudiante')
        for estado in ('Todos', 'Activos', 'Caducados'):
            self.assertContains(respuesta, f'>{estado}</a>')
        # Búsqueda, fecha y estado se combinan
        self.assertNotContains(self.client.get(INICIO, {'q': 'calendario'}), 'Excursión urgente')
        ayer = timezone.localdate() - timedelta(days=1)
        self.assertContains(self.client.get(INICIO, {'fecha': ayer.isoformat()}), 'No hay comunicados con esos filtros')
        self.assertContains(self.client.get(INICIO, {'fecha': timezone.localdate().isoformat(), 'q': 'excursión'}), 'Excursión urgente')
        self.assertContains(self.client.get(reverse('comunicados:detalle', args=[urgente.pk]), {'parcial': '1'}), 'Urgente')

    def test_el_administrador_tiene_la_gestion_aparte_de_su_bandeja(self):
        self.enviar(titulo='De Laura')
        self.client.force_login(self.admin)
        respuesta = self.client.get(INICIO)
        self.assertContains(respuesta, 'Todos los comunicados')
        self.assertContains(respuesta, 'De Laura')
        self.assertNotContains(self.client.get(INICIO, {'vista': 'enviados'}), 'De Laura')

    def test_la_ventana_de_crear_y_el_selector(self):
        self.client.force_login(self.laura)
        respuesta = self.client.get(INICIO)
        for texto in ('Marcar como urgente', 'Elegir destinatarios', 'Archivos (', 'Enviar comunicado', 'Destinatarios del comunicado',
                      '¿A qué niveles, grupos o materias?', 'Marcar todos', 'Desmarcar todos', 'name="clave_envio"'):
            self.assertContains(respuesta, texto)
        self.assertContains(self.client.get(CREAR), 'Crear comunicado')

    def test_el_menu_muestra_comunicados_a_quien_corresponde(self):
        self.client.force_login(self.laura)
        self.assertContains(self.client.get(reverse('inicio')), 'href="/comunicados/"')
        self.client.force_login(self.sin_permisos)
        self.assertNotContains(self.client.get(reverse('inicio')), 'href="/comunicados/"')
        self.assertEqual(self.client.get(INICIO).status_code, 403)

    def test_la_ficha_del_usuario_asigna_niveles_para_comunicados(self):
        url = reverse('usuarios:comunicados', args=[self.sin_niveles.pk])
        self.assertContains(self.client.get(reverse('usuarios:detalle', args=[self.sin_niveles.pk])), 'Niveles para comunicados')
        self.client.post(url, {'niveles': ['PREESCOLAR', 'PREPARATORIA']})
        self.assertEqual(PerfilUsuario.de(self.sin_niveles).niveles_comunicados, ['PREESCOLAR', 'PREPARATORIA'])
        self.assertTrue(alcance_de(type(self.sin_niveles).objects.get(pk=self.sin_niveles.pk)).puede_enviar)

    def test_los_permisos_estan_en_el_catalogo_y_la_gestion_es_del_administrador(self):
        from Usuarios import catalogo
        for permiso in ('Comunicados.recibir', 'Comunicados.seguimiento', 'Comunicados.enviar', 'Comunicados.eliminar', 'Comunicados.gestionar'):
            self.assertIn(permiso, catalogo.TODOS)
        self.assertEqual(catalogo.RESERVADOS['Comunicados.gestionar'], catalogo.ADMINISTRADOR)
        self.assertIn('Comunicados.seguimiento', catalogo.REQUISITOS['Comunicados.enviar'])
        self.assertTrue(Permission.objects.filter(content_type__app_label='Comunicados', codename='gestionar').exists())


@PRUEBAS
class CampanaTests(Colegio, BaseTestCase):
    """La campana de la barra superior suma los comunicados sin leer a los mensajes y los lista, urgentes primero."""

    def setUp(self):
        super().setUp()
        self.armar()
        self.normal = self.enviar(titulo='Reunión de familias', seleccion={Destinatario.TUTOR: {self.ana.pk}})
        self.urgente = self.enviar(titulo='Suspensión de clases', urgente=True, seleccion={Destinatario.TUTOR: {self.ana.pk}})
        self.client.logout()
        entrar_al_portal(self.client, portales.TUTOR, self.ana)

    def campana(self, html):
        inicio = html.index('data-notificaciones ')
        return html[inicio:html.index('data-notificaciones-vacio', inicio)]

    def test_suma_y_lista_los_comunicados_sin_leer(self):
        campana = self.campana(self.client.get(reverse('portal_tutores:inicio')).content.decode())
        self.assertIn('data-comunicados-sin-leer="2"', campana)
        self.assertIn('data-notificaciones-total>2</span>', campana)
        self.assertIn('2 comunicados sin leer', campana)   # en el nombre accesible del botón
        self.assertLess(campana.index('Suspensión de clases'), campana.index('Reunión de familias'))   # el urgente primero
        self.assertIn(reverse('portal_tutores:comunicados:recibido', args=[self.urgente.pk]), campana)
        # Al leer uno, la campana baja
        self.client.get(reverse('portal_tutores:comunicados:recibido', args=[self.urgente.pk]))
        campana = self.campana(self.client.get(reverse('portal_tutores:inicio')).content.decode())
        self.assertIn('data-notificaciones-total>1</span>', campana)
        self.assertNotIn('Suspensión de clases', campana)

    def test_el_resumen_para_actualizarla_sin_recargar(self):
        datos = self.client.get(reverse('portal_tutores:comunicados:resumen')).json()
        self.assertEqual((datos['pendientes'], datos['urgentes']), (2, 1))
        self.assertEqual([a['titulo'] for a in datos['avisos']], ['Suspensión de clases', 'Reunión de familias'])
        self.assertTrue(datos['avisos'][0]['url'].startswith('/portal/tutores/comunicados/'))
        # Un profesor, en el sistema
        self.enviar(self.direccion_sec, seleccion={Destinatario.PROFESOR: {self.prof_carmen.pk}}, titulo='Junta de academia')
        self.client.force_login(self.carmen)
        datos = self.client.get(reverse('comunicados:resumen')).json()
        self.assertEqual((datos['pendientes'], datos['avisos'][0]['titulo']), (1, 'Junta de academia'))
        self.assertContains(self.client.get(reverse('inicio')), 'data-comunicados-sin-leer="1"')


@PRUEBAS
class AvisoEnTiempoRealTests(Colegio, TransactionTestCase):
    """El aviso llega por el canal de la mensajería (capa en memoria de las pruebas)."""

    def setUp(self):
        from django.contrib.auth import get_user_model

        from Usuarios.iniciales import crear_roles_iniciales
        crear_roles_iniciales()
        self.admin = get_user_model().objects.create_superuser('admin', 'admin@example.com', 'x')
        self.armar()
        sesion = SessionStore()
        sesion[portales.CLAVE_DE_SESION] = {'tipo': portales.TUTOR, 'id': self.ana.pk, 'huella': portales._huella(portales.TUTOR, self.ana)}
        sesion.create()
        self.cookie_ana = sesion.session_key

    async def test_llega_el_aviso_de_un_comunicado_nuevo(self):
        from channels.db import database_sync_to_async

        from CISAHUAYO.asgi import application
        cabeceras = [(b'host', b'testserver'), (b'origin', b'http://testserver'), (b'cookie', f'sessionid={self.cookie_ana}'.encode())]
        ana = WebsocketCommunicator(application, '/ws/mensajes/', headers=cabeceras)
        self.assertTrue((await ana.connect())[0])

        # Al guardarse (on_commit) se avisa a cada destinatario
        await database_sync_to_async(self.enviar)(urgente=True, titulo='Suspensión de clases')
        evento = await ana.receive_json_from(timeout=3)
        self.assertEqual((evento['evento'], evento['titulo'], evento['urgente']), ('comunicado', 'Suspensión de clases', True))
        self.assertTrue(evento['url'].startswith('/portal/tutores/comunicados/'))
        await ana.disconnect()

    async def test_un_profesor_sin_mensajeria_tambien_recibe_el_aviso(self):
        from channels.db import database_sync_to_async
        from django.test import Client

        from CISAHUAYO.asgi import application

        def preparar():
            cuenta = crear_usuario('ines', crear_rol('Solo recibe comunicados', {'Comunicados.recibir'}))
            profesor = crear_profesor(niveles=('SECUNDARIA',), usuario=cuenta, nombre='Inés', telefono='3530005555')
            cliente = Client()
            cliente.force_login(cuenta)
            return profesor, cliente.cookies['sessionid'].value

        profesor, cookie = await database_sync_to_async(preparar)()
        cabeceras = [(b'host', b'testserver'), (b'origin', b'http://testserver'), (b'cookie', f'sessionid={cookie}'.encode())]
        ines = WebsocketCommunicator(application, '/ws/mensajes/', headers=cabeceras)
        self.assertTrue((await ines.connect())[0])
        await database_sync_to_async(self.enviar)(self.direccion_sec, seleccion={Destinatario.PROFESOR: {profesor.pk}}, titulo='Junta de academia')
        evento = await ines.receive_json_from(timeout=3)
        self.assertEqual((evento['evento'], evento['titulo']), ('comunicado', 'Junta de academia'))
        self.assertTrue(evento['url'].startswith('/comunicados/recibidos/'))
        await ines.disconnect()


def tearDownModule():
    shutil.rmtree(CARPETA, ignore_errors=True)
