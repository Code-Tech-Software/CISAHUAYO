"""«Mi horario» (pedido del 2026-10-30): cada docente consulta solo sus clases, también por URL, y los demás roles siguen igual."""
from datetime import time, timedelta

from django.contrib.auth.models import Permission
from django.urls import reverse

from Alumnos.models import (
    BloqueSimultaneo, ConfiguracionHorario, DiaNoLectivo, Grado, HorarioMateria, Materia, MateriaGrado, Periodo, Semestre,
)
from Asignaciones import bloques
from Asignaciones.test_bloques import BaseBloquesTestCase
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    ciclo_cerrado_de_prueba,
    crear_grado,
    crear_grupo,
    crear_profesor,
    crear_rol,
    crear_usuario,
    grupo_de,
    hoy,
    lunes,
)
from Usuarios.models import Rol

from .alcance import solo_sus_clases

MENSAJE = 'No tienes horarios asignados para este periodo.'


class BaseMiHorarioTestCase(BaseTestCase):
    """Rosa da Matemáticas en 1.º A y Física en 2.º B; Pedro, Matemáticas en 1.º B (la misma materia) y Español en 1.º A y
    Historia en 2.º B (los grupos de Rosa). Sin asignaciones, Marta."""

    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.rol = Rol.objects.get(grupo__name='Docente')
        self.rosa, self.ficha_rosa = self.docente('rosa')
        self.pedro, self.ficha_pedro = self.docente('pedro')
        self.marta, _ = self.docente('marta')
        self.primero, self.segundo = crear_grado('SECUNDARIA', 1), crear_grado('SECUNDARIA', 2)
        self.a1, self.b1 = grupo_de(self.primero), crear_grupo(self.primero, 'B')
        self.a2, self.b2 = grupo_de(self.segundo), crear_grupo(self.segundo, 'B')
        self.mat, self.fis = self.materia('MAT', 'Matemáticas'), self.materia('FIS', 'Física')
        self.esp, self.his = self.materia('ESP', 'Español'), self.materia('HIS', 'Historia')
        self.mat_a = self.clase(self.a1, self.mat, self.ficha_rosa, dia=0, inicio=(8, 0), fin=(9, 0))
        self.fis_b = self.clase(self.b2, self.fis, self.ficha_rosa, dia=1, inicio=(9, 0), fin=(10, 0))
        self.mat_b = self.clase(self.b1, self.mat, self.ficha_pedro, dia=0, inicio=(10, 0), fin=(11, 0))
        self.esp_a = self.clase(self.a1, self.esp, self.ficha_pedro, dia=2, inicio=(11, 0), fin=(12, 0))
        self.his_b = self.clase(self.b2, self.his, self.ficha_pedro, dia=3, inicio=(12, 0), fin=(13, 0))
        self.url = reverse('horarios:mio')

    def docente(self, nombre, rol=None):
        cuenta = crear_usuario(nombre, rol or self.rol)
        return cuenta, crear_profesor(usuario=cuenta, nombre=nombre.title(), telefono=f'353000{cuenta.pk:04d}')

    def materia(self, clave, nombre):
        return Materia.objects.create(clave=clave, nombre=nombre)

    def clase(self, grupo, materia, profesor, dia=0, inicio=(8, 0), fin=(9, 0), semana='', ciclo=None):
        asignacion = MateriaGrado.objects.create(ciclo=ciclo or self.ciclo, grado=grupo.grado, grupo=grupo, materia=materia, profesor=profesor)
        HorarioMateria.objects.create(materia_grado=asignacion, dia_semana=dia, hora_inicio=time(*inicio), hora_fin=time(*fin), semana=semana)
        return asignacion

    def consultar(self, cuenta, **parametros):
        self.client.force_login(cuenta)
        respuesta = self.client.get(self.url, parametros)
        self.assertEqual(respuesta.status_code, 200)
        return respuesta

    def clases(self, respuesta):
        return {bloque.materia_grado for bloque in respuesta.context['bloques']}

    def opciones(self, respuesta, filtro):
        return [valor for valor, _ in respuesta.context['filtro'].fields[filtro].choices if valor]


@PRUEBAS
class SoloSusClasesTests(BaseMiHorarioTestCase):
    def test_cada_docente_ve_exclusivamente_sus_clases(self):
        self.assertEqual(self.clases(self.consultar(self.rosa)), {self.mat_a, self.fis_b})
        self.assertEqual(self.clases(self.consultar(self.pedro)), {self.mat_b, self.esp_a, self.his_b})

    def test_no_muestra_las_demas_materias_de_sus_grupos(self):
        contenido = self.consultar(self.rosa).content.decode()
        self.assertIn('Matemáticas', contenido)
        self.assertIn('Física', contenido)
        self.assertNotIn('Español', contenido)
        self.assertNotIn('Historia', contenido)

    def test_la_misma_materia_con_otro_docente_no_se_cruza(self):
        self.assertNotIn(self.mat_b, self.clases(self.consultar(self.rosa)))
        self.assertNotIn(self.mat_a, self.clases(self.consultar(self.pedro)))

    def test_el_horario_es_una_vista_semanal_de_todas_sus_asignaciones(self):
        respuesta = self.consultar(self.rosa)
        self.assertEqual(respuesta.context['total_materias'], 2)
        self.assertEqual(respuesta.context['total_grupos'], 2)
        self.assertEqual(respuesta.context['horas_semanales'], '2 h')
        self.assertContains(respuesta, 'Mi horario')
        self.assertContains(respuesta, 'data-print')

    def test_sin_asignaciones_avisa(self):
        respuesta = self.consultar(self.marta)
        self.assertContains(respuesta, MENSAJE)
        self.assertEqual(respuesta.context['bloques'], [])

    def test_una_cuenta_docente_sin_ficha_no_ve_nada(self):
        respuesta = self.consultar(crear_usuario('sinficha', self.rol))
        self.assertContains(respuesta, MENSAJE)

    def test_una_asignacion_quitada_no_cuenta(self):
        MateriaGrado.objects.filter(pk=self.fis_b.pk).update(activa=False)
        self.assertEqual(self.clases(self.consultar(self.rosa)), {self.mat_a})

    def test_no_incluye_recesos_ni_enlaces_al_horario_del_grupo(self):
        contenido = self.consultar(self.rosa).content.decode()
        self.assertNotIn(reverse('horarios:grupo', args=[self.a1.pk]), contenido)
        self.assertNotIn('slot--recreo', contenido)

    def test_un_dia_sin_clases_se_avisa_solo_de_sus_niveles(self):
        DiaNoLectivo.objects.create(fecha=lunes(), nivel='SECUNDARIA', motivo='Consejo técnico')
        DiaNoLectivo.objects.create(fecha=lunes(), nivel='PRIMARIA', motivo='Festival')
        respuesta = self.consultar(self.rosa, fecha=lunes().isoformat())
        self.assertContains(respuesta, 'Consejo técnico')
        self.assertNotContains(respuesta, 'Festival')


@PRUEBAS
class FiltrosTests(BaseMiHorarioTestCase):
    def test_las_opciones_son_las_de_sus_asignaciones(self):
        respuesta = self.consultar(self.rosa)
        self.assertEqual(self.opciones(respuesta, 'nivel'), ['SECUNDARIA'])
        self.assertEqual(self.opciones(respuesta, 'grado'), [str(self.primero.pk), str(self.segundo.pk)])
        self.assertEqual(self.opciones(respuesta, 'grupo'), [str(self.a1.pk), str(self.b2.pk)])
        self.assertEqual(self.opciones(respuesta, 'materia'), [str(self.fis.pk), str(self.mat.pk)])

    def test_todos_son_solo_sus_asignaciones(self):
        respuesta = self.consultar(self.rosa, nivel='', grado='', grupo='', materia='')
        self.assertEqual(self.clases(respuesta), {self.mat_a, self.fis_b})

    def test_cada_filtro_acota(self):
        self.assertEqual(self.clases(self.consultar(self.rosa, materia=self.fis.pk)), {self.fis_b})
        self.assertEqual(self.clases(self.consultar(self.rosa, grupo=self.a1.pk)), {self.mat_a})
        self.assertEqual(self.clases(self.consultar(self.rosa, grado=self.segundo.pk)), {self.fis_b})
        self.assertEqual(self.clases(self.consultar(self.rosa, nivel='SECUNDARIA')), {self.mat_a, self.fis_b})

    def test_un_filtro_acota_las_opciones_de_los_siguientes(self):
        respuesta = self.consultar(self.rosa, grado=self.primero.pk)
        self.assertEqual(self.opciones(respuesta, 'grupo'), [str(self.a1.pk)])
        self.assertEqual(self.opciones(respuesta, 'materia'), [str(self.mat.pk)])

    def test_un_valor_de_otra_seleccion_se_ignora(self):
        respuesta = self.consultar(self.rosa, grado=self.primero.pk, materia=self.fis.pk)   # Física no es de ese grado
        self.assertEqual(self.clases(respuesta), {self.mat_a})

    def test_una_seleccion_sin_clases_avisa(self):
        self.mat_a.horarios.update(vigente_hasta=lunes() - timedelta(days=1))
        respuesta = self.consultar(self.rosa, grupo=self.a1.pk, fecha=lunes().isoformat())
        self.assertContains(respuesta, MENSAJE)
        self.assertNotContains(respuesta, 'data-print')

    def test_materias_con_el_mismo_nombre_se_distinguen(self):
        otra = self.materia('MAT2', 'Matemáticas')
        self.clase(self.a2, otra, self.ficha_rosa, dia=4)
        respuesta = self.consultar(self.rosa)
        textos = dict(respuesta.context['filtro'].fields['materia'].choices)
        self.assertEqual(textos[str(otra.pk)], 'Matemáticas (MAT2)')


@PRUEBAS
class SeguridadTests(BaseMiHorarioTestCase):
    def test_la_identidad_sale_de_la_sesion(self):
        respuesta = self.consultar(self.rosa, profesor=self.ficha_pedro.pk, usuario=self.pedro.pk, docente=self.ficha_pedro.pk)
        self.assertEqual(self.clases(respuesta), {self.mat_a, self.fis_b})

    def test_filtros_ajenos_en_la_url_no_dan_nada_de_otros(self):
        for parametros in ({'grupo': self.b1.pk}, {'materia': self.his.pk}, {'grado': 999999}, {'nivel': 'PRIMARIA'}, {'periodo': 999999}):
            with self.subTest(parametros):
                self.assertEqual(self.clases(self.consultar(self.rosa, **parametros)), {self.mat_a, self.fis_b})

    def test_el_horario_del_grupo_lleva_solo_a_sus_clases(self):
        self.client.force_login(self.rosa)
        respuesta = self.client.get(reverse('horarios:grupo', args=[self.a1.pk]))
        self.assertRedirects(respuesta, f'{self.url}?ciclo={self.ciclo.pk}&grupo={self.a1.pk}')
        self.assertEqual(self.clases(self.client.get(respuesta.url)), {self.mat_a})

    def test_un_grupo_sin_clases_suyas_no_existe(self):
        self.client.force_login(self.rosa)
        self.assertEqual(self.client.get(reverse('horarios:grupo', args=[self.b1.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('horarios:grupo', args=[self.b1.pk]), {'vista': 'fecha'}).status_code, 404)

    def test_el_horario_del_grado(self):
        self.client.force_login(self.marta)
        self.assertEqual(self.client.get(reverse('horarios:grado', args=[self.primero.pk])).status_code, 404)
        self.client.force_login(self.rosa)
        self.assertRedirects(self.client.get(reverse('horarios:grado', args=[self.primero.pk])), f'{self.url}?ciclo={self.ciclo.pk}&grado={self.primero.pk}')

    def test_el_indice_y_las_semanas_llevan_a_mi_horario(self):
        self.client.force_login(self.rosa)
        self.assertRedirects(self.client.get(reverse('horarios:lista')), self.url)
        self.assertRedirects(self.client.get(reverse('horarios:lista'), {'ciclo': self.ciclo.pk}), f'{self.url}?ciclo={self.ciclo.pk}')
        self.assertRedirects(self.client.get(reverse('horarios:semanas')), self.url)

    def test_un_ciclo_sin_clases_suyas_no_se_ofrece(self):
        cerrado = ciclo_cerrado_de_prueba()
        self.clase(self.a1, self.mat, self.ficha_pedro, ciclo=cerrado)
        respuesta = self.consultar(self.rosa, ciclo=cerrado.pk)
        self.assertEqual(respuesta.context['ciclo'], self.ciclo)
        self.assertEqual(respuesta.context['ciclos'], [self.ciclo])

    def test_no_crea_edita_ni_quita_aunque_su_rol_tuviera_el_permiso(self):
        self.rol.grupo.permissions.add(*Permission.objects.filter(codename__in=('add_horariomateria', 'change_horariomateria', 'delete_horariomateria')))
        bloque = self.mat_a.horarios.get()
        self.client.force_login(self.rosa)
        for metodo, url in ((self.client.get, reverse('horarios:crear', args=[self.a1.pk])), (self.client.get, reverse('horarios:editar', args=[bloque.pk])),
                            (self.client.post, reverse('horarios:eliminar', args=[bloque.pk])), (self.client.post, reverse('horarios:copiar_semana', args=[self.a1.pk])),
                            (self.client.get, reverse('horarios:recreo_crear')), (self.client.post, reverse('horarios:modalidad')),
                            (self.client.post, reverse('horarios:excepcion'))):
            with self.subTest(url):
                self.assertEqual(metodo(url).status_code, 403)
        self.assertTrue(HorarioMateria.objects.filter(pk=bloque.pk).exists())

    def test_sin_el_permiso_de_consulta_no_entra(self):
        self.client.force_login(self.sin_permisos)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_la_hoja_de_horario_de_otro_profesor(self):
        rol = crear_rol('Maestros con directorio', {'Alumnos.view_profesor', 'Alumnos.view_horariomateria'}, es_docente=True)
        cuenta, ficha = self.docente('lidia', rol)
        self.clase(self.a2, self.mat, ficha, dia=4)
        self.client.force_login(cuenta)
        self.assertEqual(self.client.get(reverse('profesores:horario_imprimir', args=[self.ficha_pedro.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('profesores:horario_imprimir', args=[ficha.pk])).status_code, 200)
        perfil = self.client.get(reverse('profesores:detalle', args=[self.ficha_pedro.pk]))
        self.assertEqual(perfil.context['cuadricula']['filas'], [])
        self.assertEqual(len(self.client.get(reverse('profesores:detalle', args=[ficha.pk])).context['cuadricula']['filas']), 1)


@PRUEBAS
class OtrasPantallasTests(BaseMiHorarioTestCase):
    """Las pantallas de otros módulos que un docente puede abrir no dejan ver el horario de los demás."""
    AJENO = 'Mié · 11:00–12:00'
    PROPIO = 'Lun · 08:00–09:00'

    def test_el_perfil_del_grupo(self):
        self.client.force_login(self.rosa)
        respuesta = self.client.get(reverse('grupos:detalle', args=[self.a1.pk]))
        self.assertContains(respuesta, self.PROPIO)
        self.assertNotContains(respuesta, self.AJENO)
        self.assertNotContains(respuesta, reverse('horarios:grupo', args=[self.a1.pk]))

    def test_el_perfil_del_grado(self):
        self.client.force_login(self.rosa)
        respuesta = self.client.get(reverse('grados:detalle', args=[self.primero.pk]))
        self.assertContains(respuesta, self.PROPIO)
        self.assertNotContains(respuesta, self.AJENO)

    def test_el_perfil_de_la_materia(self):
        self.client.force_login(self.rosa)
        respuesta = self.client.get(reverse('materias:detalle', args=[self.mat.pk]))
        self.assertContains(respuesta, self.PROPIO)
        self.assertNotContains(respuesta, 'Lun · 10:00–11:00')   # Matemáticas de Pedro

    def test_el_tablero_y_su_exportacion(self):
        self.client.force_login(self.rosa)
        self.assertNotContains(self.client.get(reverse('asignaciones:tablero')), self.AJENO)
        exportado = self.client.get(reverse('asignaciones:exportar')).content.decode()
        self.assertIn(self.PROPIO, exportado)
        self.assertNotIn(self.AJENO, exportado)

    def test_quien_no_es_docente_sigue_viendolos_todos(self):
        coordinacion = crear_usuario('coordi', Rol.objects.get(grupo__name='Coordinación académica'))
        self.client.force_login(coordinacion)
        self.assertContains(self.client.get(reverse('grupos:detalle', args=[self.a1.pk])), self.AJENO)
        self.client.force_login(self.admin)
        self.assertIn(self.AJENO, self.client.get(reverse('asignaciones:exportar')).content.decode())


@PRUEBAS
class DemasRolesTests(BaseMiHorarioTestCase):
    def test_administracion_conserva_los_horarios_de_todos(self):
        self.assertFalse(solo_sus_clases(self.admin))
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('horarios:lista')).status_code, 200)
        respuesta = self.client.get(reverse('horarios:grupo', args=[self.a1.pk]))
        self.assertContains(respuesta, 'Español')
        self.assertContains(respuesta, 'Matemáticas')
        self.assertRedirects(self.client.get(self.url), reverse('horarios:lista'))

    def test_un_directivo_que_tambien_da_clases_no_se_restringe(self):
        cuenta, ficha = self.docente('coordina', Rol.objects.get(grupo__name='Coordinación académica'))
        self.clase(self.a2, self.mat, ficha, dia=4)
        self.assertFalse(solo_sus_clases(cuenta))
        self.client.force_login(cuenta)
        self.assertContains(self.client.get(reverse('horarios:grupo', args=[self.b2.pk])), 'Historia')

    def test_otro_rol_para_docentes_tambien_se_restringe(self):
        rol = crear_rol('Maestros de taller', {'Alumnos.view_horariomateria'}, es_docente=True)
        cuenta, ficha = self.docente('tania', rol)
        taller = self.clase(self.a2, self.mat, ficha, dia=4)
        self.assertEqual(self.clases(self.consultar(cuenta)), {taller})


@PRUEBAS
class VisibilidadYSemanasTests(BaseMiHorarioTestCase):
    def test_los_grados_ocultos_no_salen_en_el_ciclo_vigente(self):
        Grado.objects.filter(pk=self.segundo.pk).update(visible=False)
        respuesta = self.consultar(self.rosa)
        self.assertEqual(self.clases(respuesta), {self.mat_a})
        self.assertEqual(self.opciones(respuesta, 'grado'), [str(self.primero.pk)])

    def test_en_un_ciclo_cerrado_si_salen(self):
        cerrado = ciclo_cerrado_de_prueba()
        anterior = self.clase(self.b2, self.mat, self.ficha_rosa, ciclo=cerrado)
        Grado.objects.filter(pk=self.segundo.pk).update(visible=False)
        respuesta = self.consultar(self.rosa, ciclo=cerrado.pk)
        self.assertEqual(self.clases(respuesta), {anterior})
        self.assertContains(respuesta, 'está cerrado')

    def alternar(self):
        primaria = crear_grado('PRIMARIA', 3)
        ConfiguracionHorario.objects.create(ciclo=self.ciclo, nivel='PRIMARIA', modalidad=ConfiguracionHorario.ALTERNADO, fecha_referencia=lunes(), semana_referencia='A')
        grupo = grupo_de(primaria)
        de_a = self.clase(grupo, self.materia('CIE', 'Ciencias'), self.ficha_rosa, dia=0, inicio=(13, 0), fin=(14, 0), semana='A')
        de_b = self.clase(grupo, self.materia('ART', 'Artes'), self.ficha_rosa, dia=1, inicio=(13, 0), fin=(14, 0), semana='B')
        ajena = self.clase(grupo, self.materia('MUS', 'Música'), self.ficha_pedro, dia=2, inicio=(13, 0), fin=(14, 0), semana='A')
        return de_a, de_b, ajena

    def test_semana_a_y_b_muestran_solo_sus_clases_de_esa_semana(self):
        de_a, de_b, ajena = self.alternar()
        semana_a = self.clases(self.consultar(self.rosa, fecha=lunes().isoformat()))
        semana_b = self.clases(self.consultar(self.rosa, fecha=(lunes() + timedelta(days=7)).isoformat()))
        self.assertEqual(semana_a, {self.mat_a, self.fis_b, de_a})
        self.assertEqual(semana_b, {self.mat_a, self.fis_b, de_b})
        self.assertNotIn(ajena, semana_a | semana_b)

    def test_dice_que_semana_le_toca_a_cada_nivel(self):
        self.alternar()
        respuesta = self.consultar(self.rosa, fecha=lunes().isoformat())
        nombres = [(nombre, info.tipo) for nombre, info in respuesta.context['semanas_por_nivel']]
        self.assertEqual(nombres, [('Primaria', 'A')])

    def test_una_semana_sin_sus_clases_avisa(self):
        primaria = crear_grado('PRIMARIA', 4)
        ConfiguracionHorario.objects.create(ciclo=self.ciclo, nivel='PRIMARIA', modalidad=ConfiguracionHorario.ALTERNADO, fecha_referencia=lunes(), semana_referencia='A')
        cuenta, ficha = self.docente('sara')
        self.clase(grupo_de(primaria), self.mat, ficha, semana='A')
        self.assertContains(self.consultar(cuenta, fecha=(lunes() + timedelta(days=7)).isoformat()), MENSAJE)

    def test_las_versiones_son_las_de_esa_semana(self):
        bloque = self.fis_b.horarios.get()
        HorarioMateria.objects.filter(pk=bloque.pk).update(vigente_hasta=lunes() - timedelta(days=1))
        self.assertEqual(self.clases(self.consultar(self.rosa, fecha=lunes().isoformat())), {self.mat_a})
        self.assertEqual(self.clases(self.consultar(self.rosa, fecha=(lunes() - timedelta(days=7)).isoformat())), {self.mat_a, self.fis_b})


@PRUEBAS
class PeriodosYSemestresTests(BaseMiHorarioTestCase):
    def setUp(self):
        super().setUp()
        self.uno, self.dos = crear_grado('PREPARATORIA', 1), crear_grado('PREPARATORIA', 2)
        self.semestre_a = Semestre.objects.create(ciclo=self.ciclo, clave='A', fecha_inicio=self.ciclo.fecha_inicio, fecha_fin=hoy() + timedelta(days=30))
        self.semestre_b = Semestre.objects.create(ciclo=self.ciclo, clave='B', fecha_inicio=hoy() + timedelta(days=31), fecha_fin=self.ciclo.fecha_fin)
        self.prepa_a = self.clase(grupo_de(self.uno), self.materia('QUI', 'Química'), self.ficha_rosa, dia=4)
        self.prepa_b = self.clase(grupo_de(self.dos), self.materia('BIO', 'Biología'), self.ficha_rosa, dia=4)

    def test_por_omision_el_semestre_en_curso(self):
        respuesta = self.consultar(self.rosa)
        self.assertEqual(respuesta.context['filtro']['periodo'].value(), 'semestre-A')
        self.assertEqual(self.clases(respuesta), {self.mat_a, self.fis_b, self.prepa_a})

    def test_el_otro_semestre_va_a_sus_fechas(self):
        respuesta = self.consultar(self.rosa, periodo='semestre-B')
        self.assertEqual(self.clases(respuesta), {self.mat_a, self.fis_b, self.prepa_b})
        self.assertEqual(respuesta.context['desde'], self.semestre_b.fecha_inicio)
        self.assertGreaterEqual(respuesta.context['fecha'], self.semestre_b.fecha_inicio)

    def test_todo_el_ciclo_junta_los_dos(self):
        self.assertEqual(self.clases(self.consultar(self.rosa, periodo='todo')), {self.mat_a, self.fis_b, self.prepa_a, self.prepa_b})

    def test_quien_no_da_clases_por_semestres_no_ve_esas_opciones(self):
        respuesta = self.consultar(self.pedro)
        self.assertEqual(self.opciones(respuesta, 'periodo'), ['todo'])

    def test_un_periodo_es_de_su_nivel_y_de_su_semestre(self):
        secundaria = Periodo.objects.create(ciclo=self.ciclo, nivel='SECUNDARIA', nombre='Bimestre 1', fecha_inicio=hoy() - timedelta(days=10), fecha_fin=hoy() + timedelta(days=10))
        prepa = Periodo.objects.create(ciclo=self.ciclo, nivel='PREPARATORIA', nombre='Parcial 1', semestre=self.semestre_a, fecha_inicio=hoy() - timedelta(days=10), fecha_fin=hoy() + timedelta(days=10))
        primaria = Periodo.objects.create(ciclo=self.ciclo, nivel='PRIMARIA', nombre='Trimestre 1', fecha_inicio=hoy() - timedelta(days=10), fecha_fin=hoy() + timedelta(days=10))
        respuesta = self.consultar(self.rosa, periodo=secundaria.pk)
        self.assertEqual(self.clases(respuesta), {self.mat_a, self.fis_b})
        self.assertEqual(self.clases(self.consultar(self.rosa, periodo=prepa.pk)), {self.prepa_a})
        self.assertNotIn(str(primaria.pk), self.opciones(respuesta, 'periodo'))

    def test_la_fecha_se_queda_dentro_del_periodo(self):
        periodo = Periodo.objects.create(ciclo=self.ciclo, nivel='SECUNDARIA', nombre='Bimestre 2', fecha_inicio=hoy() + timedelta(days=60), fecha_fin=hoy() + timedelta(days=90))
        respuesta = self.consultar(self.rosa, periodo=periodo.pk, fecha=hoy().isoformat())
        self.assertEqual(respuesta.context['fecha'], periodo.fecha_inicio)
        self.assertEqual(self.clases(respuesta), {self.mat_a, self.fis_b})


@PRUEBAS
class GruposDeClaseTests(BaseBloquesTestCase):
    def consultar(self, cuenta):
        self.client.force_login(cuenta)
        return {bloque.materia_grado for bloque in self.client.get(reverse('horarios:mio')).context['bloques']}

    def test_cada_docente_ve_solo_la_opcion_que_tiene_asignada(self):
        bloque, opciones, _ = self.ingles_tres()
        bloques.activar(bloque, self.admin)
        for cuenta, opcion in zip(self.docentes, opciones):
            self.assertEqual(self.consultar(cuenta), {opcion.asignacion})

    def test_un_bloque_en_preparacion_no_sale(self):
        self.ingles_tres()
        self.assertEqual(BloqueSimultaneo.objects.get().estado, BloqueSimultaneo.PREPARACION)
        self.client.force_login(self.docentes[0])
        respuesta = self.client.get(reverse('horarios:mio'))
        self.assertContains(respuesta, MENSAJE)
        self.assertEqual([v for v, _ in respuesta.context['filtro'].fields['grupo'].choices if v], [])

    def test_compartir_grupo_base_no_da_acceso_a_la_opcion(self):
        cuenta = self.docentes[0]
        self.profesores[0].asignaciones.all().delete()
        bloque = self.bloque(sustituye=[self.ingles_a, self.ingles_b])
        opcion = self.opcion(bloque, 'Básico', profesor=self.profesores[1])
        bloques.asignar(bloque, opcion, self.todos, None, self.admin)
        bloques.activar(bloque, self.admin)
        MateriaGrado.objects.filter(pk=self.mate_a.pk).update(profesor=self.profesores[0])
        self.assertEqual(self.consultar(cuenta), {self.mate_a})
