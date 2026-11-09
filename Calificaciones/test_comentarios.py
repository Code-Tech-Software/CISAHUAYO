"""Comentarios por periodo y boleta de comentarios (pedido del 2026-11-09): la captura del docente con la lista real, un
solo comentario por estudiante, materia y periodo, la publicación por estudiante, la reapertura con bitácora, los
grupos divididos de un bloque simultáneo, los permisos (también por enlace directo) y los portales."""
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from Agenda.tests import entrar_al_portal
from Alumnos.models import MateriaGrado, Periodo
from Asignaciones.test_bloques import BaseBloquesTestCase
from CISAHUAYO import portales
from CISAHUAYO.pruebas import (
    PRUEBAS,
    ciclo_cerrado_de_prueba,
    crear_alumno,
    crear_grado,
    crear_profesor,
    crear_tutor,
    crear_usuario,
    hoy,
    inscribir,
    materia_en_grado,
    vincular,
)
from Usuarios.models import Rol

from . import comentarios, reglas
from .models import ActaCalificaciones, BoletaComentarios, CambioComentario, ComentarioPeriodo
from .tests import BaseCalificacionesTestCase, dia

URL = reverse('calificaciones:comentarios')


class BaseComentariosTestCase(BaseCalificacionesTestCase):
    """La base de calificaciones (Marta da Matemáticas en 4.º Primaria; Luis y Zoe) más Pablo, que da Español. Ciencias
    no tiene docente. Un segundo bimestre, todavía próximo."""

    def setUp(self):
        super().setUp()
        self.docente_esp = crear_usuario('pablo', Rol.objects.get(grupo__name='Docente'))
        self.profesor_esp = crear_profesor(usuario=self.docente_esp, nombre='Pablo', apellido_paterno='Ibarra')
        self.esp.profesor = self.profesor_esp
        self.esp.save()
        self.siguiente = Periodo.objects.create(ciclo=self.ciclo, nivel='PRIMARIA', nombre='Segundo bimestre', fecha_inicio=dia(12), fecha_fin=dia(70))
        self.luis = self.inscripcion

    def capturar(self, asignacion, datos, periodo=None, usuario=None, versiones=None):
        """POST de la captura: {inscripción: texto}."""
        self.client.force_login(usuario or self.docente)
        periodo = periodo or self.periodo
        cuerpo = {}
        for inscripcion, texto in datos.items():
            cuerpo[f'comentario-{inscripcion.pk}'] = texto
            cuerpo[f'version-{inscripcion.pk}'] = (versiones or {}).get(inscripcion, comentarios.version_de(
                ComentarioPeriodo.objects.filter(inscripcion=inscripcion, periodo=periodo, materia=asignacion.materia).first()))
        return self.client.post(f'{URL}?ciclo={self.ciclo.pk}&materia={asignacion.pk}&periodo={periodo.pk}', cuerpo)

    def completar(self, inscripcion, periodo=None):
        """Los tres comentarios del estudiante (Marta, Pablo y, en Ciencias, el administrador)."""
        periodo = periodo or self.periodo
        for asignacion, usuario in ((self.mat, self.docente), (self.esp, self.docente_esp), (self.cie, self.admin)):
            self.capturar(asignacion, {inscripcion: f'{asignacion.materia} de {inscripcion.alumno.nombre} en {periodo.nombre}.'}, periodo, usuario)


@PRUEBAS
class CapturaTests(BaseComentariosTestCase):
    def test_el_docente_ve_la_lista_real_y_su_avance(self):
        self.client.force_login(self.docente)
        respuesta = self.client.get(URL)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context['asignacion'], self.mat)   # solo sus materias
        self.assertEqual([a.pk for a in respuesta.context['asignaciones']], [self.mat.pk])
        captura = respuesta.context['captura']
        self.assertEqual({f.inscripcion for f in captura.filas}, {self.luis, self.zoe})
        self.assertEqual((captura.capturados, captura.pendientes), (0, 2))
        self.assertContains(respuesta, '0 de 2')

    def test_guarda_en_varias_sesiones_y_solo_cuenta_el_que_tiene_texto(self):
        respuesta = self.capturar(self.mat, {self.luis: '  Participa y entrega a tiempo.  ', self.zoe: ''})
        self.assertRedirects(respuesta, f'{URL}?ciclo={self.ciclo.pk}&materia={self.mat.pk}&periodo={self.periodo.pk}', fetch_redirect_response=False)
        comentario = ComentarioPeriodo.objects.get()
        self.assertEqual((comentario.inscripcion, comentario.materia, comentario.texto), (self.luis, self.mat.materia, 'Participa y entrega a tiempo.'))
        self.assertEqual((comentario.autor, comentario.docente), (self.docente, self.profesor.nombre_completo))
        self.assertIsNotNone(comentario.capturado_en)
        self.assertFalse(ComentarioPeriodo.objects.filter(inscripcion=self.zoe).exists())   # vacío: no se crea
        captura = comentarios.captura(self.mat, self.periodo)
        self.assertEqual((captura.capturados, captura.pendientes), (1, 1))
        # Otra sesión: completa a Zoe y corrige a Luis (mismo registro, conserva autoría y registra la actualización)
        self.capturar(self.mat, {self.luis: 'Participa, entrega a tiempo y ayuda a sus compañeros.', self.zoe: 'Mejoró su lectura.'})
        self.assertEqual(ComentarioPeriodo.objects.count(), 2)
        comentario.refresh_from_db()
        self.assertEqual(comentario.texto, 'Participa, entrega a tiempo y ayuda a sus compañeros.')
        self.assertEqual(comentario.autor, self.docente)
        self.assertGreaterEqual(comentario.actualizado_en, comentario.capturado_en)
        self.assertEqual(comentarios.captura(self.mat, self.periodo).capturados, 2)
        # Borrar el texto lo vuelve pendiente
        self.capturar(self.mat, {self.zoe: '   '})
        self.assertEqual(comentarios.captura(self.mat, self.periodo).capturados, 1)
        self.assertEqual(CambioComentario.objects.filter(accion=CambioComentario.CAPTURA).count(), 4)

    def test_un_solo_comentario_por_estudiante_materia_y_periodo_en_la_base(self):
        ComentarioPeriodo.objects.create(inscripcion=self.luis, materia=self.mat.materia, periodo=self.periodo, texto='Uno')
        with self.assertRaises(IntegrityError), transaction.atomic():
            ComentarioPeriodo.objects.create(inscripcion=self.luis, materia=self.mat.materia, periodo=self.periodo, texto='Dos')
        # Otro periodo es otro comentario
        ComentarioPeriodo.objects.create(inscripcion=self.luis, materia=self.mat.materia, periodo=self.siguiente, texto='Otro periodo')

    def test_los_comentarios_se_separan_por_periodo(self):
        self.capturar(self.mat, {self.luis: 'Primer bimestre.'})
        self.fijar_ahora(9, 0, dia(20))   # ya en el segundo bimestre
        self.capturar(self.mat, {self.luis: 'Segundo bimestre.'}, self.siguiente)
        self.assertEqual(ComentarioPeriodo.objects.get(periodo=self.periodo).texto, 'Primer bimestre.')
        self.assertEqual(ComentarioPeriodo.objects.get(periodo=self.siguiente).texto, 'Segundo bimestre.')

    def test_materia_ajena_periodo_cerrado_y_estudiante_fuera_de_la_lista(self):
        # Marta no abre Español (403 aunque teclee la dirección) ni guarda en ella
        self.client.force_login(self.docente)
        self.assertEqual(self.client.get(f'{URL}?ciclo={self.ciclo.pk}&materia={self.esp.pk}').status_code, 403)
        self.assertEqual(self.capturar(self.esp, {self.luis: 'No es mía.'}).status_code, 403)
        self.assertFalse(ComentarioPeriodo.objects.exists())
        # Un estudiante de otro grado no está en su lista: no se guarda
        ajeno = inscribir(crear_alumno(nombre='Ana'), self.ciclo, crear_grado('PRIMARIA', 5))
        respuesta = self.capturar(self.mat, {ajeno: 'Intruso.'})
        self.assertEqual(respuesta.status_code, 302)   # se ignora: solo se leen los campos de la lista
        self.assertFalse(ComentarioPeriodo.objects.exists())
        guardados, errores = comentarios.guardar(self.mat, self.periodo, self.docente, {ajeno.pk: ('Intruso.', '')})
        self.assertEqual((guardados, list(errores)), (0, [ajeno.pk]))
        # Periodo cerrado: solo lectura
        self.periodo.apertura = Periodo.CERRADO
        self.periodo.save()
        self.assertIn('cerrado', comentarios.motivo_de_solo_lectura(self.mat, self.periodo, self.docente))
        respuesta = self.capturar(self.mat, {self.luis: 'Tarde.'})
        self.assertFalse(ComentarioPeriodo.objects.exists())
        self.assertNotContains(self.client.get(f'{URL}?ciclo={self.ciclo.pk}&materia={self.mat.pk}&periodo={self.periodo.pk}'), 'name="comentario-')

    def test_dos_personas_a_la_vez_no_se_pisan(self):
        self.capturar(self.mat, {self.luis: 'Versión de Marta.'})
        vieja = comentarios.version_de(ComentarioPeriodo.objects.get())
        self.capturar(self.mat, {self.luis: 'Versión del administrador.'}, usuario=self.admin)
        # Marta guarda con la versión que tenía cargada: se rechaza y se le devuelve su texto
        respuesta = self.capturar(self.mat, {self.luis: 'Marta otra vez.'}, versiones={self.luis: vieja})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Alguien más cambió este comentario')
        self.assertContains(respuesta, 'Marta otra vez.')
        self.assertEqual(ComentarioPeriodo.objects.get().texto, 'Versión del administrador.')

    def test_limite_de_largo(self):
        respuesta = self.capturar(self.mat, {self.luis: 'x' * (comentarios.LIMITE + 1)})
        self.assertContains(respuesta, f'el máximo es {comentarios.LIMITE}')
        self.assertFalse(ComentarioPeriodo.objects.exists())


@PRUEBAS
class BoletaYPublicacionTests(BaseComentariosTestCase):
    def setUp(self):
        super().setUp()
        self.direccion = crear_usuario('dir', Rol.objects.get(grupo__name='Dirección'))
        self.boletas = reverse('calificaciones:boletas_periodo', args=[self.luis.alumno_id])

    def publicar(self, inscripcion=None, usuario=None, periodo=None):
        self.client.force_login(usuario or self.direccion)
        return self.client.post(reverse('calificaciones:comentarios_publicar', args=[(inscripcion or self.luis).alumno_id]),
                                {'periodo': (periodo or self.periodo).pk})

    def test_cada_materia_una_vez_con_su_docente_autor(self):
        self.completar(self.luis)
        boleta = comentarios.boleta_de(self.luis, self.periodo)
        self.assertEqual([m.materia.nombre for m in boleta.materias], sorted(['Mat', 'Esp', 'Cie']))
        contenido = comentarios.contenido_de(boleta)
        por_materia = {m['materia']: m for m in contenido['materias']}
        self.assertEqual(por_materia['Mat']['docente'], self.profesor.nombre_completo)
        self.assertEqual(por_materia['Esp']['docente'], self.profesor_esp.nombre_completo)
        self.assertEqual(por_materia['Cie']['docente'], 'admin')   # lo escribió quien gestiona todas (sin ficha de profesor)
        self.assertEqual((contenido['matricula'], contenido['grado'], contenido['nivel'], contenido['periodo']),
                         (self.alumno.referencia, '4.º', 'Primaria', 'Primer bimestre'))

    def test_incompleta_queda_pendiente_y_muestra_lo_que_falta(self):
        self.capturar(self.mat, {self.luis: 'Bien.'})
        boleta = comentarios.boleta_de(self.luis, self.periodo)
        self.assertEqual(boleta.estado, 'pendiente')
        self.assertEqual(sorted(m.materia.nombre for m in boleta.pendientes), ['Cie', 'Esp'])
        respuesta = self.publicar()
        self.assertFalse(BoletaComentarios.objects.filter(publicada=True).exists())
        respuesta = self.client.get(f'{self.boletas}?periodo={self.periodo.pk}')
        self.assertContains(respuesta, 'Faltan comentarios de Cie, Esp.')
        # La de calificaciones sigue su propio flujo: está disponible aunque la de comentarios no
        self.assertContains(respuesta, reverse('calificaciones:boleta', args=[self.luis.alumno_id]))

    def test_publicar_bloquea_y_reabrir_con_motivo_deja_corregir_con_bitacora(self):
        self.completar(self.luis)
        self.completar(self.zoe)
        respuesta = self.publicar()
        self.assertEqual(respuesta.status_code, 302)
        registro = BoletaComentarios.objects.get(inscripcion=self.luis, periodo=self.periodo)
        self.assertTrue(registro.publicada)
        self.assertEqual(len(registro.contenido['materias']), 3)
        # Se evalúa por estudiante: Zoe sigue sin publicar
        self.assertFalse(BoletaComentarios.objects.get(inscripcion=self.zoe, periodo=self.periodo).publicada)
        # Publicada: Marta ya no edita el de Luis (sí el de Zoe)
        respuesta = self.capturar(self.mat, {self.luis: 'Cambio tardío.', self.zoe: 'Zoe corregido.'})
        self.assertContains(respuesta, 'ya se publicó')
        self.assertNotEqual(ComentarioPeriodo.objects.get(inscripcion=self.luis, materia=self.mat.materia).texto, 'Cambio tardío.')
        self.assertEqual(ComentarioPeriodo.objects.get(inscripcion=self.zoe, materia=self.mat.materia).texto, 'Zoe corregido.')
        # Reabrir pide el permiso de reabrir (el docente no) y motivo
        self.client.force_login(self.docente)
        url = reverse('calificaciones:comentarios_reabrir', args=[self.luis.alumno_id])
        self.assertEqual(self.client.post(url, {'periodo': self.periodo.pk, 'motivo': 'Corregir redacción'}).status_code, 403)
        self.client.force_login(self.direccion)
        self.client.post(url, {'periodo': self.periodo.pk, 'motivo': ''})
        self.assertTrue(BoletaComentarios.objects.get(pk=registro.pk).publicada)
        self.client.post(url, {'periodo': self.periodo.pk, 'motivo': 'Corregir la redacción de Matemáticas'})
        registro.refresh_from_db()
        self.assertFalse(registro.publicada)
        reapertura = CambioComentario.objects.get(accion=CambioComentario.REAPERTURA)
        self.assertEqual(reapertura.motivo, 'Corregir la redacción de Matemáticas')
        self.assertEqual(len(reapertura.datos['contenido']['materias']), 3)   # lo que estaba publicado
        # Ya se corrige, queda en la bitácora y se vuelve a publicar
        self.capturar(self.mat, {self.luis: 'Redacción corregida.'})
        cambio = CambioComentario.objects.filter(accion=CambioComentario.CAPTURA, inscripcion=self.luis).first()
        self.assertEqual(cambio.nuevo, 'Redacción corregida.')
        self.assertTrue(cambio.anterior)
        self.publicar()
        registro.refresh_from_db()
        self.assertTrue(registro.publicada)
        self.assertIn('Redacción corregida.', [m['comentario'] for m in registro.contenido['materias']])
        from django.contrib.admin.models import LogEntry
        self.assertEqual(LogEntry.objects.filter(object_id=str(registro.pk)).count(), 3)   # publicó, reabrió, publicó

    def test_lo_publicado_no_cambia_aunque_cambien_las_asignaciones(self):
        self.completar(self.luis)
        self.publicar()
        self.esp.profesor = None
        self.esp.save()
        respuesta = self.client.get(reverse('calificaciones:boleta_comentarios', args=[self.luis.alumno_id]), {'periodo': self.periodo.pk})
        self.assertContains(respuesta, self.profesor_esp.nombre_completo)

    def test_permisos_en_el_servidor(self):
        self.completar(self.luis)
        # El docente no publica ni abre boletas (tampoco por enlace directo)
        self.assertEqual(self.publicar(usuario=self.docente).status_code, 403)
        self.client.force_login(self.docente)
        for url in (self.boletas, reverse('calificaciones:boleta_comentarios', args=[self.luis.alumno_id]),
                    reverse('calificaciones:comentarios_grupo', args=[self.luis.grupo_id])):
            self.assertEqual(self.client.get(url, {'periodo': self.periodo.pk}).status_code, 403, url)
        # Control escolar consulta, pero no publica
        control = crear_usuario('control', Rol.objects.get(grupo__name='Control escolar'))
        self.client.force_login(control)
        self.assertEqual(self.client.get(self.boletas, {'periodo': self.periodo.pk}).status_code, 200)
        self.assertEqual(self.publicar(usuario=control).status_code, 403)
        self.assertFalse(BoletaComentarios.objects.filter(publicada=True).exists())

    def test_la_hoja_lleva_los_comentarios_largos_completos(self):
        largo = ' '.join(['Comentario extenso sobre su desempeño.'] * 50)[:comentarios.LIMITE]
        self.completar(self.luis)
        self.capturar(self.mat, {self.luis: largo})
        self.client.force_login(self.direccion)
        respuesta = self.client.get(reverse('calificaciones:boleta_comentarios', args=[self.luis.alumno_id]), {'periodo': self.periodo.pk, 'pdf': '1'})
        self.assertContains(respuesta, largo.strip())
        self.assertContains(respuesta, 'data-imprimir-al-abrir')
        self.assertContains(respuesta, 'Borrador')   # todavía no publicada
        self.assertContains(respuesta, self.alumno.referencia)

    def test_publicar_las_completas_del_grupo(self):
        self.completar(self.luis)
        self.capturar(self.mat, {self.zoe: 'Solo una.'})
        self.client.force_login(self.direccion)
        url = reverse('calificaciones:comentarios_grupo', args=[self.luis.grupo_id])
        respuesta = self.client.get(url, {'periodo': self.periodo.pk})
        self.assertEqual((respuesta.context['listas'], respuesta.context['publicadas']), (1, 0))
        self.client.post(url, {'periodo': self.periodo.pk})
        self.assertEqual(list(BoletaComentarios.objects.filter(publicada=True).values_list('inscripcion', flat=True)), [self.luis.pk])
        self.assertEqual(self.client.get(reverse('calificaciones:comentarios_grupo_hoja', args=[self.luis.grupo_id]), {'periodo': self.periodo.pk}).status_code, 200)

    def test_boleta_de_calificaciones_historica(self):
        pasado = ciclo_cerrado_de_prueba()
        inscribir(self.alumno, pasado, self.grado, activa=False)
        bimestre = Periodo.objects.create(ciclo=pasado, nivel='PRIMARIA', nombre='Bimestre del ciclo pasado', fecha_inicio=pasado.fecha_inicio,
                                          fecha_fin=pasado.fecha_inicio + timedelta(days=60))
        viejo = materia_en_grado('HIS', self.grado, pasado, inicio=None)
        inscripcion = self.alumno.inscripciones.get(ciclo=pasado)
        ActaCalificaciones.objects.create(asignacion=viejo, periodo=bimestre, estado=ActaCalificaciones.CERRADA, cerrada_en=timezone.now(),
                                          resultados_cerrados=[{'inscripcion': inscripcion.pk, 'final': '8.50', 'faltas': 1}])
        self.client.force_login(self.direccion)
        respuesta = self.client.get(reverse('calificaciones:boleta', args=[self.alumno.pk]), {'ciclo': pasado.pk, 'pdf': '1'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, '8.50')
        self.assertContains(respuesta, 'Bimestre del ciclo pasado')
        # Y el periodo del ciclo pasado aparece entre las boletas por periodo
        respuesta = self.client.get(self.boletas, {'periodo': bimestre.pk})
        self.assertEqual(respuesta.context['periodo'], bimestre)


@PRUEBAS
class PortalesTests(BaseComentariosTestCase):
    def setUp(self):
        super().setUp()
        self.alumno.acceso_portal = True
        self.alumno.save()
        self.completar(self.luis)
        self.completar(self.zoe)
        self.registro = comentarios.publicar(self.luis, self.periodo, self.admin)
        self.tutor = crear_tutor(usuario='rosa.mora', acceso_portal=True)
        self.vinculo = vincular(self.tutor, self.alumno)

    def test_el_estudiante_ve_y_descarga_la_suya(self):
        entrar_al_portal(self.client, portales.ESTUDIANTE, self.alumno)
        inicio = self.client.get(reverse('portal_estudiantes:inicio'))
        url = reverse('portal_estudiantes:boleta_comentarios', args=[self.registro.pk])
        self.assertContains(inicio, url)
        respuesta = self.client.get(url, {'pdf': '1'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Mat de Luis en Primer bimestre.')
        self.assertNotContains(respuesta, 'Borrador')

    def test_una_cuenta_ajena_no_la_abre(self):
        zoe = self.zoe.alumno
        zoe.acceso_portal = True
        zoe.save()
        entrar_al_portal(self.client, portales.ESTUDIANTE, zoe)
        self.assertEqual(self.client.get(reverse('portal_estudiantes:boleta_comentarios', args=[self.registro.pk])).status_code, 404)
        # La de Zoe no está publicada: tampoco
        sin_publicar = BoletaComentarios.objects.get(inscripcion=self.zoe, periodo=self.periodo)
        self.assertEqual(self.client.get(reverse('portal_estudiantes:boleta_comentarios', args=[sin_publicar.pk])).status_code, 404)
        # Un tutor sin vínculo, tampoco; con el vínculo desactivado, deja de verla
        otro = crear_tutor(usuario='otro.tutor', acceso_portal=True, nombre='Otro')
        entrar_al_portal(self.client, portales.TUTOR, otro)
        self.assertEqual(self.client.get(reverse('portal_tutores:boleta_comentarios', args=[self.registro.pk])).status_code, 404)
        # Una cuenta del sistema sin portal recibe 403 (como cualquier ruta de los portales)
        self.client.logout()
        self.client.force_login(self.docente)
        self.assertNotEqual(self.client.get(reverse('portal_tutores:boleta_comentarios', args=[self.registro.pk])).status_code, 200)

    def test_el_tutor_vinculado_la_ve_mientras_su_vinculo_este_activo(self):
        entrar_al_portal(self.client, portales.TUTOR, self.tutor)
        url = reverse('portal_tutores:boleta_comentarios', args=[self.registro.pk])
        self.assertContains(self.client.get(reverse('portal_tutores:estudiante', args=[self.alumno.pk])), url)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.vinculo.activo = False
        self.vinculo.save()
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_reabierta_deja_de_verse_en_el_portal(self):
        comentarios.reabrir(self.luis, self.periodo, 'Corregir un comentario', self.admin)
        entrar_al_portal(self.client, portales.ESTUDIANTE, self.alumno)
        self.assertEqual(self.client.get(reverse('portal_estudiantes:boleta_comentarios', args=[self.registro.pk])).status_code, 404)


@PRUEBAS
class GruposDivididosTests(BaseBloquesTestCase):
    """Inglés de 1.º A y 1.º B repartido en tres grupos de clase (el caso A de bloques simultáneos)."""

    def setUp(self):
        super().setUp()
        from Asignaciones import bloques
        self.bloque, self.opciones, self.reparto = self.ingles_tres()
        bloques.activar(self.bloque, self.admin)
        self.bloque.refresh_from_db()
        # Las clases como las lee una vista (con su bloque ya activo)
        self.clases = [MateriaGrado.objects.select_related('clase__bloque').get(pk=o.asignacion.pk) for o in self.opciones]
        self.periodo_ = Periodo.objects.create(ciclo=self.ciclo, nivel='SECUNDARIA', nombre='Bimestre', fecha_inicio=hoy() - timedelta(days=10),
                                               fecha_fin=hoy() + timedelta(days=20))

    def test_la_clase_usa_su_lista_aunque_vengan_de_varios_grupos(self):
        clase = self.opciones[1]   # Ceci (1.º A) y Dani (1.º B)
        filas = comentarios.captura(clase.asignacion, self.periodo_).filas
        self.assertEqual({f.inscripcion for f in filas}, set(self.reparto[1]))
        self.assertEqual({f.inscripcion.grupo for f in filas}, {self.a, self.b})
        self.assertTrue(all(f.materia == self.ingles for f in filas))
        # El docente del Inglés del grupo base ya no tiene a quienes el bloque se lo sustituye
        self.assertEqual(comentarios.captura(self.ingles_a, self.periodo_).filas, [])

    def test_inglés_una_sola_vez_en_la_boleta_y_cambio_de_clase_reutiliza_el_comentario(self):
        from Asignaciones import bloques
        estudiante = self.reparto[0][0]
        dora, elsa = self.docentes[0], self.docentes[1]
        guardados, _ = comentarios.guardar(self.clases[0], self.periodo_, dora, {estudiante.pk: ('Buen inicio en Básico.', '')})
        self.assertEqual(guardados, 1)
        # Cambia a Intermedio a mitad del periodo: Elsa escribe en el mismo registro y se conserva la autoría de Dora
        bloques.asignar(self.bloque, self.opciones[1], [estudiante], hoy(), self.admin)
        fila = next(f for f in comentarios.captura(self.clases[1], self.periodo_).filas if f.inscripcion == estudiante)
        self.assertEqual(fila.texto, 'Buen inicio en Básico.')
        comentarios.guardar(self.clases[1], self.periodo_, elsa, {estudiante.pk: ('Avanzó a Intermedio y se adaptó bien.', fila.version)})
        comentario = ComentarioPeriodo.objects.get(inscripcion=estudiante)
        self.assertEqual((comentario.autor, comentario.actualizado_por, comentario.asignacion), (dora, elsa, self.clases[1]))
        boleta = comentarios.boleta_de(estudiante, self.periodo_)
        self.assertEqual([m.materia for m in boleta.materias].count(self.ingles), 1)
        ingles = next(m for m in boleta.materias if m.materia == self.ingles)
        self.assertEqual(ingles.comentario.texto, 'Avanzó a Intermedio y se adaptó bien.')
        self.assertEqual(len(ingles.asignaciones), 2)

    def test_otro_docente_no_escribe_en_una_clase_que_no_es_suya(self):
        estudiante = self.reparto[0][0]
        self.client.force_login(self.docentes[2])
        url = f"{URL}?ciclo={self.ciclo.pk}&materia={self.clases[0].pk}&periodo={self.periodo_.pk}"
        self.assertEqual(self.client.post(url, {f'comentario-{estudiante.pk}': 'No es mía.'}).status_code, 403)
        self.assertFalse(ComentarioPeriodo.objects.exists())

    def test_permisos_en_el_catalogo(self):
        from Usuarios import catalogo
        self.assertIn(comentarios.PUBLICAR, catalogo.TODOS)
        self.assertIn(reglas.REABRIR, catalogo.TODOS)
