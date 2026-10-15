"""Bitácoras por grupo: registro, consulta por grupo y por estudiante, permisos y alcance, historial de cambios,
anulación e integración con los reportes de conducta (criterios de aceptación del pedido del 2026-10-14)."""
import io
import uuid
import zipfile
from datetime import timedelta
from unittest.mock import patch

from django.apps import apps
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from CISAHUAYO.pruebas import (
    PRUEBAS, crear_alumno, crear_grupo, crear_profesor, crear_rol, crear_usuario, grupo_de, hoy, inscribir_antes, lunes,
    materia_en_grado, momento,
)
from Conducta.pruebas import CARPETA, BaseConductaTestCase
from Usuarios.models import PerfilUsuario, Rol

from .models import LEYENDA, SELLO, CambioBitacora, EntradaBitacora, EstudianteBitacora

LISTA = reverse('bitacoras:lista')
CREAR = reverse('bitacoras:crear')


@override_settings(MEDIA_ROOT=CARPETA)
class BaseBitacoraTestCase(BaseConductaTestCase):
    """4° A de primaria con Ana y Beto (Matemáticas de la docente Marta, los lunes de 8 a 9; Español de otro docente),
    4° B con Ciro (Matemáticas de Marta) y 1° de secundaria con Zoe (Historia)."""

    def setUp(self):
        super().setUp()
        self.grupo_a = grupo_de(self.primaria)
        self.grupo_b = crear_grupo(self.primaria, 'B')
        self.beto = crear_alumno(nombre='Beto', curp='BITACORA00000000B1')
        inscribir_antes(self.beto, self.ciclo, self.primaria)
        self.ciro = crear_alumno(nombre='Ciro', curp='BITACORA00000000C1')
        self.inscripcion_ciro = inscribir_antes(self.ciro, self.ciclo, self.primaria, grupo=self.grupo_b)

        docente = Rol.objects.get(grupo__name='Docente')
        self.docente = crear_usuario('marta', docente)
        self.profesor = crear_profesor(usuario=self.docente, nombre='Marta')
        self.otro_docente = crear_usuario('raul', docente)
        self.otro_profesor = crear_profesor(usuario=self.otro_docente, nombre='Raúl', telefono='3530001111')

        self.mat = materia_en_grado('MAT', self.primaria, self.ciclo, dia=0, inicio=(8, 0), fin=(9, 0), profesor=self.profesor)
        self.esp = materia_en_grado('ESP', self.primaria, self.ciclo, dia=0, inicio=(9, 0), fin=(10, 0), profesor=self.otro_profesor)
        self.mat_b = materia_en_grado('MATB', self.primaria, self.ciclo, dia=1, inicio=(8, 0), fin=(9, 0), profesor=self.profesor, grupo=self.grupo_b)
        self.his = materia_en_grado('HIS', self.secundaria, self.ciclo, dia=0, inicio=(10, 0), fin=(11, 0))
        self.bloque = self.mat.horarios.get()

    def datos_entrada(self, **cambios):
        datos = {
            'grupo': self.grupo_a.pk, 'asignacion': self.mat.pk, 'fecha': lunes().isoformat(), 'bloque': self.bloque.pk,
            'alumnos': [self.alumno.pk, self.beto.pk], 'titulo': 'Trabajo en equipo', 'descripcion': 'Resolvieron juntos el problema 4.',
            'seguimiento': 'Revisar la tarea la próxima clase.', 'clave_envio': str(uuid.uuid4()),
        }
        datos.update(cambios)
        return {clave: valor for clave, valor in datos.items() if valor is not None}

    def crear(self, usuario=None, **cambios):
        if usuario is not None:
            self.client.force_login(usuario)
        return self.client.post(CREAR, self.datos_entrada(**cambios))

    def ultima(self):
        return EntradaBitacora.objects.order_by('-pk').first()


@PRUEBAS
class RegistroTests(BaseBitacoraTestCase):
    def test_una_entrada_con_varios_estudiantes_se_guarda_una_vez(self):
        respuesta = self.crear(self.docente)
        self.assertRedirects(respuesta, LISTA, fetch_redirect_response=False)
        entrada = self.ultima()
        self.assertEqual(EntradaBitacora.objects.count(), 1)
        self.assertEqual(set(entrada.alumnos.all()), {self.alumno, self.beto})
        self.assertEqual(EstudianteBitacora.objects.filter(entrada=entrada).count(), 2)
        # dónde, cuándo y quién, como era al registrarla (la fecha de la clase es distinta de la del registro)
        self.assertEqual((entrada.ciclo, entrada.periodo, entrada.nivel, entrada.grado, entrada.grupo, entrada.asignacion),
                         (self.ciclo, self.periodo if self.periodo.fecha_inicio <= lunes() <= self.periodo.fecha_fin else None,
                          'PRIMARIA', self.primaria, self.grupo_a, self.mat))
        self.docente.refresh_from_db()
        self.assertEqual((entrada.materia_nombre, entrada.grupo_texto, entrada.hora_inicio.hour, entrada.autor, entrada.autor_nombre),
                         ('Mat', str(self.grupo_a), 8, self.docente, self.docente.get_full_name()))
        self.assertEqual(entrada.fecha, lunes())
        self.assertEqual(timezone.localtime(entrada.creado).date(), timezone.localdate())
        self.assertEqual(entrada.cambios.get().accion, CambioBitacora.CREACION)

        # en la bitácora del grupo aparece una sola vez; en el historial de cada estudiante, también
        self.client.force_login(self.admin)
        grupo = self.client.get(LISTA, {'grupo': self.grupo_a.pk})
        self.assertEqual(list(grupo.context['pagina']), [entrada])
        self.assertEqual(grupo.context['totales']['estudiantes'], 2)
        for alumno in (self.alumno, self.beto):
            historial = self.client.get(reverse('bitacoras:estudiante', args=[alumno.pk]))
            self.assertEqual(list(historial.context['pagina']), [entrada])
            self.assertContains(historial, 'Junto con 1 estudiante más')   # sin el nombre del otro
        self.assertNotContains(self.client.get(reverse('bitacoras:estudiante', args=[self.alumno.pk])), 'Beto Pérez')

    def test_varias_entradas_de_la_misma_clase_y_guardar_y_registrar_otra(self):
        respuesta = self.crear(self.docente, otra='1')
        self.assertTrue(respuesta['Location'].startswith(CREAR))
        siguiente = self.client.get(respuesta['Location'])
        self.assertEqual(siguiente.context['form'].initial['asignacion'], self.mat.pk)
        self.assertEqual(siguiente.context['form'].initial['bloque'], self.bloque.pk)
        self.crear(alumnos=[self.beto.pk], titulo='Participación destacada')
        self.assertEqual(EntradaBitacora.objects.filter(asignacion=self.mat, fecha=lunes()).count(), 2)

    def test_observacion_general_del_grupo(self):
        self.crear(self.docente, general='on', titulo='El grupo trabajó en silencio')
        entrada = self.ultima()
        self.assertTrue(entrada.general)
        self.assertFalse(entrada.vinculos.exists())   # aunque llegaran estudiantes marcados, no se atribuye a nadie
        self.client.force_login(self.admin)
        self.assertEqual(list(self.client.get(LISTA, {'grupo': self.grupo_a.pk}).context['pagina']), [entrada])
        self.assertContains(self.client.get(LISTA), 'Observación general del grupo')
        self.assertEqual(list(self.client.get(reverse('bitacoras:estudiante', args=[self.alumno.pk])).context['pagina']), [])

    def test_el_doble_envio_no_duplica(self):
        datos = self.datos_entrada()
        self.client.force_login(self.docente)
        self.client.post(CREAR, datos)
        repetido = self.client.post(CREAR, datos, follow=True)
        self.assertEqual(EntradaBitacora.objects.count(), 1)
        self.assertContains(repetido, 'no se duplicó')

    def test_validaciones(self):
        self.client.force_login(self.docente)
        casos = [
            ({'fecha': (hoy() + timedelta(days=1)).isoformat()}, 'fecha', 'posterior a hoy'),
            ({'fecha': (self.ciclo.fecha_inicio - timedelta(days=1)).isoformat()}, 'fecha', 'fuera del ciclo'),
            ({'alumnos': [self.ciro.pk]}, 'alumnos', 'inscritos en ese grupo'),
            ({'alumnos': []}, 'alumnos', 'Elige al menos a un estudiante'),
            ({'asignacion': self.mat_b.pk}, 'asignacion', 'no es de ese grupo'),
            ({'fecha': (lunes() + timedelta(days=1)).isoformat() if lunes() + timedelta(days=1) <= hoy() else (lunes() - timedelta(days=6)).isoformat()},
             'bloque', 'clase fue en'),
            ({'titulo': ''}, 'titulo', 'obligatorio'),
        ]
        for cambios, campo, texto in casos:
            with self.subTest(campo=campo, texto=texto):
                respuesta = self.client.post(CREAR, self.datos_entrada(**cambios))
                self.assertEqual(respuesta.status_code, 200)
                self.assertIn(texto, ' '.join(respuesta.context['form'].errors.get(campo, [])))
        self.assertFalse(EntradaBitacora.objects.exists())
        # La leyenda informativa acompaña siempre al formulario
        self.assertContains(self.client.get(CREAR), LEYENDA)

    def test_las_opciones_de_un_grupo(self):
        self.client.force_login(self.docente)
        opciones = self.client.get(reverse('bitacoras:opciones'), {'grupo': self.grupo_a.pk}).json()
        self.assertEqual([m['nombre'] for m in opciones['materias']], ['Mat'])   # Español no es suyo
        self.assertEqual(opciones['materias'][0]['bloques'][0]['dia'], 0)
        self.assertEqual({a['id'] for a in opciones['alumnos']}, {self.alumno.pk, self.beto.pk})
        ajeno = self.client.get(reverse('bitacoras:opciones'), {'grupo': self.otro_grupo_secundaria().pk}).json()
        self.assertEqual(ajeno, {'materias': [], 'alumnos': []})

    def otro_grupo_secundaria(self):
        return grupo_de(self.secundaria)

    def test_la_captura_arranca_con_la_clase_en_curso_del_docente(self):
        self.client.force_login(self.docente)
        with patch('django.utils.timezone.now', return_value=momento(8, 30)):
            form = self.client.get(CREAR).context['form']
        self.assertEqual((form.initial['grupo'], form.initial['asignacion'], form.initial['bloque']), (self.grupo_a.pk, self.mat.pk, self.bloque.pk))
        with patch('django.utils.timezone.now', return_value=momento(7, 0)):   # antes de su primera clase: nada elegido
            self.assertNotIn('asignacion', self.client.get(CREAR).context['form'].initial)


@PRUEBAS
class PermisosTests(BaseBitacoraTestCase):
    def test_el_docente_solo_registra_en_sus_grupos_y_materias(self):
        respuesta = self.crear(self.docente, asignacion=self.esp.pk)   # Español es de Raúl
        self.assertIn('asignacion', respuesta.context['form'].errors)
        respuesta = self.crear(self.docente, grupo=self.otro_grupo().pk, asignacion=self.his.pk, alumnos=[self.otro.pk])
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(EntradaBitacora.objects.exists())

    def otro_grupo(self):
        return grupo_de(self.secundaria)

    def test_el_docente_solo_consulta_lo_de_sus_clases(self):
        self.crear(self.otro_docente, asignacion=self.esp.pk, bloque=self.esp.horarios.get().pk, titulo='Español')
        de_espanol = self.ultima()
        self.crear(self.admin, titulo='Del administrador en Matemáticas')
        del_admin = self.ultima()
        self.client.force_login(self.docente)
        self.assertEqual(list(self.client.get(LISTA).context['pagina']), [del_admin])   # su clase, aunque la registró otro
        self.assertEqual(self.client.get(reverse('bitacoras:detalle', args=[de_espanol.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('bitacoras:estudiante', args=[self.otro.pk])).status_code, 404)   # Zoe no es de sus grupos
        self.assertEqual(self.client.get(reverse('bitacoras:estudiante', args=[self.alumno.pk])).status_code, 200)

    def test_un_docente_no_modifica_entradas_de_otro(self):
        self.crear(self.admin, titulo='Del administrador')
        entrada = self.ultima()
        self.client.force_login(self.docente)
        self.assertEqual(self.client.get(reverse('bitacoras:editar', args=[entrada.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse('bitacoras:anular', args=[entrada.pk]), {'motivo': 'No me gusta.'}).status_code, 403)
        entrada.refresh_from_db()
        self.assertFalse(entrada.anulada)
        self.assertNotContains(self.client.get(reverse('bitacoras:detalle', args=[entrada.pk])), reverse('bitacoras:editar', args=[entrada.pk]))
        # la suya sí
        self.crear(self.docente)
        suya = self.ultima()
        self.assertEqual(self.client.get(reverse('bitacoras:editar', args=[suya.pk])).status_code, 200)

    def test_prefectura_segun_su_alcance(self):
        from Prefectura.models import AlcancePrefectura
        prefecto = crear_usuario('prefecto', Rol.objects.get(grupo__name='Prefectura'))
        AlcancePrefectura.objects.create(usuario=prefecto, niveles=['SECUNDARIA'])
        self.crear(self.docente)
        de_primaria = self.ultima()
        self.crear(self.admin, grupo=self.otro_grupo().pk, asignacion=self.his.pk, bloque='', alumnos=[self.otro.pk], titulo='Historia')
        de_secundaria = self.ultima()
        self.client.force_login(prefecto)
        self.assertEqual(list(self.client.get(LISTA).context['pagina']), [de_secundaria])
        self.assertEqual(self.client.get(reverse('bitacoras:detalle', args=[de_primaria.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('bitacoras:estudiante', args=[self.alumno.pk])).status_code, 404)
        # registra en su alcance, no fuera de él
        self.assertEqual(self.crear(grupo=self.grupo_a.pk).status_code, 200)
        self.assertEqual(self.crear(grupo=self.otro_grupo().pk, asignacion=self.his.pk, bloque='', alumnos=[self.otro.pk]).status_code, 302)

    def test_coordinacion_segun_sus_niveles(self):
        coordina = crear_usuario('coordina', Rol.objects.get(grupo__name='Coordinación académica'))
        self.crear(self.docente)
        de_primaria = self.ultima()
        self.crear(self.admin, grupo=self.otro_grupo().pk, asignacion=self.his.pk, bloque='', alumnos=[self.otro.pk], titulo='Historia')
        de_secundaria = self.ultima()
        self.client.force_login(coordina)
        self.assertEqual(set(self.client.get(LISTA).context['pagina']), {de_primaria, de_secundaria})   # sin niveles: todo el colegio
        perfil = PerfilUsuario.de(coordina)
        perfil.niveles_bitacora = ['PRIMARIA']
        perfil.save()
        self.client.force_login(coordina)
        self.assertEqual(list(self.client.get(LISTA).context['pagina']), [de_primaria])
        self.assertEqual(self.client.get(reverse('bitacoras:detalle', args=[de_secundaria.pk])).status_code, 404)

    def test_el_administrador_asigna_los_niveles_que_coordina(self):
        coordina = crear_usuario('coordina', Rol.objects.get(grupo__name='Coordinación académica'))
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('usuarios:detalle', args=[coordina.pk])), 'Coordinación de bitácoras')
        self.client.post(reverse('usuarios:coordinacion', args=[coordina.pk]), {'niveles': ['SECUNDARIA']})
        self.assertEqual(PerfilUsuario.de(coordina).niveles_bitacora, ['SECUNDARIA'])
        # a un docente (solo sus clases) no le aplica
        self.assertRedirects(self.client.get(reverse('usuarios:coordinacion', args=[self.docente.pk])), reverse('usuarios:detalle', args=[self.docente.pk]))

    def test_sin_permiso_de_bitacoras_no_se_entra(self):
        solo_alumnos = crear_usuario('lupita', crear_rol('Solo estudiantes', {'Alumnos.view_alumno'}))
        self.client.force_login(solo_alumnos)
        self.assertEqual(self.client.get(LISTA).status_code, 403)
        self.assertEqual(self.client.get(CREAR).status_code, 403)


@PRUEBAS
class CambiosTests(BaseBitacoraTestCase):
    def test_editar_deja_el_historial_con_valores_anteriores_y_nuevos(self):
        self.crear(self.docente)
        entrada = self.ultima()
        respuesta = self.client.post(reverse('bitacoras:editar', args=[entrada.pk]), self.datos_entrada(titulo='Trabajo en parejas', alumnos=[self.alumno.pk]))
        self.assertEqual(respuesta.status_code, 302)
        entrada.refresh_from_db()
        self.assertEqual((entrada.titulo, entrada.ediciones, entrada.editada_por), ('Trabajo en parejas', 1, self.docente))
        self.assertEqual(list(entrada.alumnos.all()), [self.alumno])
        cambio = entrada.cambios.filter(accion=CambioBitacora.EDICION).get()
        self.assertIn(['Título', 'Trabajo en equipo', 'Trabajo en parejas'], cambio.cambios)
        self.assertIn('Estudiantes', [c[0] for c in cambio.cambios])
        detalle = self.client.get(reverse('bitacoras:detalle', args=[entrada.pk]))
        self.assertContains(detalle, 'Historial de cambios')
        self.assertContains(detalle, 'Trabajo en equipo')   # el valor anterior
        self.assertContains(self.client.get(LISTA), 'Editada')
        # sin cambios no se registra una edición
        self.client.post(reverse('bitacoras:editar', args=[entrada.pk]), self.datos_entrada(titulo='Trabajo en parejas', alumnos=[self.alumno.pk]))
        self.assertEqual(entrada.cambios.filter(accion=CambioBitacora.EDICION).count(), 1)

    def test_anular_exige_motivo_y_conserva_la_entrada_para_auditoria(self):
        self.crear(self.docente)
        entrada = self.ultima()
        url = reverse('bitacoras:anular', args=[entrada.pk])
        self.assertEqual(self.client.post(url, {'motivo': ''}).status_code, 200)
        self.client.post(url, {'motivo': 'Se registró en el grupo equivocado.'})
        entrada.refresh_from_db()
        self.assertTrue(entrada.anulada)
        self.assertEqual(entrada.cambios.filter(accion=CambioBitacora.ANULACION).get().motivo, 'Se registró en el grupo equivocado.')
        # deja de aparecer; el autor (sin «gestionar») ya no la ve, la administración sí, para auditoría
        self.assertEqual(list(self.client.get(LISTA).context['pagina']), [])
        self.assertEqual(self.client.get(reverse('bitacoras:detalle', args=[entrada.pk])).status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(list(self.client.get(LISTA).context['pagina']), [])
        self.assertEqual(list(self.client.get(LISTA, {'registros': 'anuladas'}).context['pagina']), [entrada])
        self.assertContains(self.client.get(reverse('bitacoras:detalle', args=[entrada.pk])), 'Entrada anulada')

    def test_se_conserva_el_grupo_de_entonces_y_los_ciclos_cerrados_son_de_solo_lectura(self):
        self.crear(self.docente)
        entrada = self.ultima()
        # Ana cambia de grupo: la entrada sigue siendo de 4° A y sigue en su historial
        self.inscripcion.grupo = self.grupo_b
        self.inscripcion.save()
        self.client.force_login(self.admin)
        historial = self.client.get(reverse('bitacoras:estudiante', args=[self.alumno.pk]))
        self.assertEqual(list(historial.context['pagina']), [entrada])
        self.assertContains(historial, str(self.grupo_a))
        self.assertEqual(list(self.client.get(LISTA, {'grupo': self.grupo_a.pk}).context['pagina']), [entrada])
        self.assertEqual(list(self.client.get(LISTA, {'grupo': self.grupo_b.pk}).context['pagina']), [])
        # Cuando el ciclo se cierra, la entrada se conserva y ya no se edita
        self.ciclo.activo = False
        self.ciclo.save()
        self.assertEqual(self.client.get(reverse('bitacoras:editar', args=[entrada.pk])).status_code, 403)
        self.assertEqual(list(self.client.get(LISTA, {'ciclo': ''}).context['pagina']), [entrada])

    def test_no_cambia_calificaciones_conducta_asistencia_ni_sanciones(self):
        self.registrar()   # un registro de conducta previo
        modelos = [m for app in ('Alumnos', 'Conducta', 'Calificaciones', 'Prefectura') for m in apps.get_app_config(app).get_models()]
        antes = {m._meta.label: m.objects.count() for m in modelos}
        registro = self.ultimo()
        modificado = registro.modificado
        self.crear(self.docente)
        entrada = self.ultima()
        self.client.post(reverse('bitacoras:editar', args=[entrada.pk]), self.datos_entrada(titulo='Otro título'))
        self.client.post(reverse('bitacoras:anular', args=[entrada.pk]), {'motivo': 'Prueba de anulación.'})
        self.assertEqual({m._meta.label: m.objects.count() for m in modelos}, antes)
        registro.refresh_from_db()
        self.assertEqual(registro.modificado, modificado)


@PRUEBAS
class ReportesDeConductaTests(BaseBitacoraTestCase):
    def setUp(self):
        super().setUp()
        self.crear(self.docente, titulo='Ayudó a sus compañeros', alumnos=[self.alumno.pk, self.beto.pk])
        self.con_ana = self.ultima()
        self.crear(general='on', titulo='Grupo muy participativo')
        self.general = self.ultima()
        self.crear(alumnos=[self.beto.pk], titulo='Solo Beto', fecha=(lunes() - timedelta(days=7)).isoformat(), bloque=self.bloque.pk)
        self.solo_beto = self.ultima()
        self.client.force_login(self.admin)
        self.registrar()   # una incidencia de Ana

    def reporte(self, **filtros):
        return self.client.get(reverse('conducta:reportes'), filtros).context['contenido']

    def test_el_reporte_por_grupo_incluye_las_del_grupo_y_las_generales(self):
        contenido = self.reporte(reporte='grupo', grupo=self.grupo_a.pk)
        self.assertEqual(set(contenido['bitacora']), {self.con_ana, self.general, self.solo_beto})
        self.assertEqual(contenido['incidencias'], 1)   # la bitácora no se suma a los conteos de conducta
        respuesta = self.client.get(reverse('conducta:reportes'), {'reporte': 'grupo', 'grupo': self.grupo_a.pk})
        self.assertContains(respuesta, 'Observaciones de bitácora')
        self.assertContains(respuesta, SELLO)
        self.assertContains(respuesta, 'Observación general del grupo')

    def test_el_historial_individual_solo_las_que_nombran_al_estudiante(self):
        contenido = self.reporte(reporte='historial', alumnos=self.alumno.pk)
        historial = contenido['historiales'][0]
        self.assertEqual(historial['bitacora'], [self.con_ana])   # ni la general ni la de Beto
        self.assertEqual(historial['incidencias'], 1)
        respuesta = self.client.get(reverse('conducta:reportes'), {'reporte': 'historial', 'alumnos': self.alumno.pk})
        self.assertNotContains(respuesta, 'Beto Pérez')   # sin los nombres de los demás implicados

    def test_respeta_las_fechas_y_se_puede_excluir(self):
        contenido = self.reporte(reporte='historial', alumnos=self.beto.pk, desde=lunes().isoformat())
        self.assertEqual(contenido['historiales'][0]['bitacora'], [self.con_ana])   # la de la semana pasada queda fuera
        excluida = self.reporte(reporte='grupo', grupo=self.grupo_a.pk, bitacora='no')
        self.assertFalse(excluida['bitacora_incluida'])
        self.assertNotIn('bitacora', excluida)
        self.assertIn(('Observaciones de bitácora', 'Excluidas'), excluida['filtros'])
        # las anuladas no aparecen en los reportes
        self.client.post(reverse('bitacoras:anular', args=[self.general.pk]), {'motivo': 'Duplicada por error.'})
        self.assertNotIn(self.general, self.reporte(reporte='grupo', grupo=self.grupo_a.pk)['bitacora'])

    def test_la_hoja_para_imprimir_y_el_excel_llevan_lo_mismo(self):
        filtros = {'reporte': 'grupo', 'grupo': self.grupo_a.pk}
        hoja = self.client.get(reverse('conducta:reporte_imprimir'), filtros)
        self.assertContains(hoja, 'Grupo muy participativo')
        self.assertContains(hoja, SELLO)
        excel = self.client.get(reverse('conducta:reporte_excel'), filtros)
        with zipfile.ZipFile(io.BytesIO(excel.content)) as archivo:
            xml = ' '.join(archivo.read(nombre).decode('utf-8') for nombre in archivo.namelist() if nombre.endswith('.xml'))
        self.assertIn('Bitácora', xml)
        self.assertIn('Grupo muy participativo', xml)
        individual = self.client.get(reverse('conducta:reporte_excel'), {'reporte': 'historial', 'alumnos': self.alumno.pk})
        with zipfile.ZipFile(io.BytesIO(individual.content)) as archivo:
            xml = ' '.join(archivo.read(nombre).decode('utf-8') for nombre in archivo.namelist() if nombre.endswith('.xml'))
        self.assertIn('Ayudó a sus compañeros', xml)
        self.assertNotIn('Solo Beto', xml)

    def test_quien_no_consulta_bitacoras_no_ve_la_seccion(self):
        solo_conducta = crear_usuario('conducta', crear_rol('Solo conducta', {'Conducta.view_registroconducta'}))
        self.client.force_login(solo_conducta)
        respuesta = self.client.get(reverse('conducta:reportes'), {'reporte': 'grupo', 'grupo': self.grupo_a.pk})
        self.assertFalse(respuesta.context['contenido']['bitacora_incluida'])
        self.assertNotContains(respuesta, 'Observaciones de bitácora')
        self.assertNotIn('bitacora', respuesta.context['contenido'])
        self.assertNotIn('bitacora', respuesta.context['filtro'].fields)

    def test_prefectura_ve_solo_las_de_su_alcance_en_sus_reportes(self):
        from Prefectura.models import AlcancePrefectura
        prefecto = crear_usuario('prefecto', Rol.objects.get(grupo__name='Prefectura'))
        AlcancePrefectura.objects.create(usuario=prefecto, niveles=['SECUNDARIA'])
        self.client.force_login(prefecto)
        contenido = self.client.get(reverse('prefectura:reportes'), {'reporte': 'conducta'}).context['contenido']
        self.assertEqual(contenido['bitacora'], [])
        AlcancePrefectura.objects.filter(usuario=prefecto).update(niveles=['PRIMARIA'])
        self.client.force_login(prefecto)
        contenido = self.client.get(reverse('prefectura:reportes'), {'reporte': 'conducta'}).context['contenido']
        self.assertEqual(set(contenido['bitacora']), {self.con_ana, self.general, self.solo_beto})


@PRUEBAS
class MenuTests(BaseBitacoraTestCase):
    def test_en_gestion_academica_para_quien_tiene_acceso(self):
        self.client.force_login(self.docente)
        self.assertContains(self.client.get(reverse('inicio')), 'Bitácoras por grupo')
        sin = crear_usuario('lupita', crear_rol('Solo estudiantes', {'Alumnos.view_alumno'}))
        self.client.force_login(sin)
        self.assertNotContains(self.client.get(reverse('inicio')), 'Bitácoras por grupo')
