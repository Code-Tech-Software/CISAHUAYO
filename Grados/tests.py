import csv
import io

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from Alumnos.models import Grado, Materia, MateriaGrado
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    ciclo_cerrado_de_prueba,
    crear_alumno,
    crear_grado,
    crear_tutor,
    inscribir,
    vincular,
)


# ---------------------------------------------------------------------------
# Permisos
# ---------------------------------------------------------------------------
@PRUEBAS
class PermisosTests(BaseTestCase):
    def test_anonimo_es_enviado_al_login(self):
        self.client.logout()
        grado = crear_grado()
        for nombre, args in (('lista', []), ('crear', []), ('detalle', [grado.pk]), ('editar', [grado.pk]), ('exportar', [grado.pk])):
            respuesta = self.client.get(reverse(f'grados:{nombre}', args=args))
            self.assertEqual(respuesta.status_code, 302, nombre)
            self.assertIn('/admin/login/', respuesta['Location'])

    def test_sin_permisos_recibe_403(self):
        self.client.force_login(self.sin_permisos)
        grado = crear_grado()
        for nombre, args in (('lista', []), ('crear', []), ('detalle', [grado.pk]), ('editar', [grado.pk]), ('exportar', [grado.pk])):
            self.assertEqual(self.client.get(reverse(f'grados:{nombre}', args=args)).status_code, 403, nombre)
        for nombre in ('baja', 'reactivar'):
            self.assertEqual(self.client.post(reverse(f'grados:{nombre}', args=[grado.pk])).status_code, 403, nombre)
        grado.refresh_from_db()
        self.assertTrue(grado.activo)

    def test_las_acciones_solo_aceptan_post(self):
        grado = crear_grado()
        for nombre in ('baja', 'reactivar'):
            self.assertEqual(self.client.get(reverse(f'grados:{nombre}', args=[grado.pk])).status_code, 405, nombre)

    def test_dar_de_baja_pide_el_permiso_de_eliminar(self):
        grado = crear_grado()
        self.con_permisos('view_grado', 'change_grado')
        self.assertEqual(self.client.post(reverse('grados:baja', args=[grado.pk])).status_code, 403)
        self.con_permisos('view_grado', 'delete_grado')
        self.assertEqual(self.client.post(reverse('grados:baja', args=[grado.pk])).status_code, 302)


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------
@PRUEBAS
class ListaTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.prepa = crear_grado('PREPARATORIA', 1)
        self.secundaria = crear_grado('SECUNDARIA', 1)
        self.primero = crear_grado('PRIMARIA', 1)
        self.sexto = crear_grado('PRIMARIA', 6)
        self.preescolar = crear_grado('PREESCOLAR', 3)
        self.retirado = crear_grado('PRIMARIA', 2, activo=False)

    def lista(self, **filtros):
        respuesta = self.client.get(reverse('grados:lista'), filtros)
        self.assertEqual(respuesta.status_code, 200)
        return respuesta

    def test_agrupa_por_nivel_en_orden_escolar(self):
        niveles = self.lista().context['niveles']
        self.assertEqual([n['nombre'] for n in niveles], ['Preescolar', 'Primaria', 'Secundaria', 'Preparatoria'])
        self.assertEqual([str(f['grado']) for f in niveles[1]['filas']], ['1° Primaria', '6° Primaria'])

    def test_no_muestra_los_grados_dados_de_baja_salvo_en_su_filtro(self):
        activos = [str(f['grado']) for n in self.lista().context['niveles'] for f in n['filas']]
        self.assertNotIn('2° Primaria', activos)
        bajas = self.lista(estado='BAJA')
        self.assertTrue(bajas.context['viendo_bajas'])
        self.assertEqual([str(f['grado']) for n in bajas.context['niveles'] for f in n['filas']], ['2° Primaria'])
        self.assertContains(bajas, 'Reactivar')

    def test_conteos_de_las_pestanas(self):
        respuesta = self.lista()
        self.assertEqual((respuesta.context['total_activos'], respuesta.context['total_bajas']), (5, 1))

    def test_cuenta_los_alumnos_del_ciclo_actual(self):
        otro = ciclo_cerrado_de_prueba()
        inscribir(crear_alumno(), self.ciclo, self.primero)
        inscribir(crear_alumno(), self.ciclo, self.primero)
        inscribir(crear_alumno(), self.ciclo, self.primero, activa=False)    # una baja no cuenta
        inscribir(crear_alumno(), otro, self.primero)                        # otro ciclo tampoco
        inscribir(crear_alumno(), self.ciclo, self.sexto)
        respuesta = self.lista()
        primaria = respuesta.context['niveles'][1]
        self.assertEqual([f['inscritos'] for f in primaria['filas']], [2, 1])
        self.assertEqual(primaria['inscritos'], 3)
        self.assertEqual(respuesta.context['total_inscritos'], 3)

    def test_cuenta_las_materias_del_ciclo_actual(self):
        materia = Materia.objects.create(clave='MAT', nombre='Matemáticas')
        MateriaGrado.objects.create(ciclo=self.ciclo, grado=self.primero, materia=materia)
        MateriaGrado.objects.create(ciclo=ciclo_cerrado_de_prueba(), grado=self.primero, materia=materia)
        fila = self.lista().context['niveles'][1]['filas'][0]
        self.assertEqual(fila['materias'], 1)

    def test_sin_ciclo_actual_avisa_y_no_cuenta(self):
        self.ciclo.activo = False
        self.ciclo.save()
        respuesta = self.lista()
        self.assertContains(respuesta, 'No hay un ciclo actual')
        self.assertEqual(respuesta.context['total_inscritos'], 0)

    def test_sin_grados_invita_a_crear(self):
        Grado.objects.all().delete()
        self.assertContains(self.lista(), 'Aún no hay grados')

    def test_consultas_constantes(self):
        with CaptureQueriesContext(connection) as pocas:
            self.lista()
        for i in range(8):
            inscribir(crear_alumno(), self.ciclo, self.primero)
        with CaptureQueriesContext(connection) as muchas:
            self.lista()
        self.assertEqual(len(muchas), len(pocas))


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
@PRUEBAS
class CrearTests(BaseTestCase):
    url = property(lambda self: reverse('grados:crear'))

    def test_el_formulario_no_ofrece_el_estado_activo(self):
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(list(respuesta.context['form'].fields), ['nivel', 'numero'])

    def test_registra_y_redirige_al_listado_con_mensaje(self):
        respuesta = self.client.post(self.url, {'nivel': 'PRIMARIA', 'numero': 3}, follow=True)
        self.assertRedirects(respuesta, reverse('grados:lista'))
        self.assertContains(respuesta, 'El grado 3° Primaria fue registrado')
        grado = Grado.objects.get()
        self.assertTrue(grado.activo)

    def test_limites_por_nivel(self):
        for nivel, numero, valido in (
            ('PREESCOLAR', 3, True), ('PREESCOLAR', 4, False),
            ('PRIMARIA', 6, True), ('PRIMARIA', 7, False),
            ('SECUNDARIA', 3, True), ('SECUNDARIA', 4, False),
            ('PREPARATORIA', 6, True), ('PREPARATORIA', 7, False),
            ('PRIMARIA', 0, False),
        ):
            respuesta = self.client.post(self.url, {'nivel': nivel, 'numero': numero})
            self.assertEqual(respuesta.status_code, 302 if valido else 200, (nivel, numero))
            if not valido:
                self.assertIn('numero', respuesta.context['form'].errors, (nivel, numero))

    def test_no_se_repite_el_grado(self):
        crear_grado('PRIMARIA', 2)
        respuesta = self.client.post(self.url, {'nivel': 'PRIMARIA', 'numero': 2})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Ya existe el grado 2° Primaria')
        self.assertEqual(Grado.objects.count(), 1)
        self.assertEqual(len(respuesta.context['form'].errors), 1)    # un solo aviso, no dos

    def test_un_grado_dado_de_baja_tampoco_se_repite(self):
        crear_grado('PRIMARIA', 2, activo=False)
        self.assertEqual(self.client.post(self.url, {'nivel': 'PRIMARIA', 'numero': 2}).status_code, 200)

    def test_campos_obligatorios(self):
        respuesta = self.client.post(self.url, {})
        self.assertEqual(set(respuesta.context['form'].errors), {'nivel', 'numero'})

    def test_nivel_invalido(self):
        respuesta = self.client.post(self.url, {'nivel': 'UNIVERSIDAD', 'numero': 1})
        self.assertIn('nivel', respuesta.context['form'].errors)


@PRUEBAS
class EditarTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.grado = crear_grado('PRIMARIA', 3)
        self.url = reverse('grados:editar', args=[self.grado.pk])

    def test_formulario_precargado(self):
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context['form'].initial['numero'], 3)
        self.assertNotContains(respuesta, 'en su historial')

    def test_avisa_si_el_grado_ya_tiene_historial(self):
        inscribir(crear_alumno(), ciclo_actual_de_prueba(), self.grado)
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.context['total_inscripciones'], 1)
        self.assertContains(respuesta, '1 inscripción en su historial')

    def test_actualiza_y_redirige_al_listado(self):
        respuesta = self.client.post(self.url, {'nivel': 'PRIMARIA', 'numero': 4}, follow=True)
        self.assertRedirects(respuesta, reverse('grados:lista'))
        self.assertContains(respuesta, 'se actualizó')
        self.grado.refresh_from_db()
        self.assertEqual(self.grado.numero, 4)

    def test_conserva_su_propio_nivel_y_numero(self):
        self.assertEqual(self.client.post(self.url, {'nivel': 'PRIMARIA', 'numero': 3}).status_code, 302)

    def test_no_permite_el_de_otro_grado(self):
        crear_grado('PRIMARIA', 5)
        respuesta = self.client.post(self.url, {'nivel': 'PRIMARIA', 'numero': 5})
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('numero', respuesta.context['form'].errors)

    def test_editar_no_cambia_el_estado_activo(self):
        self.grado.activo = False
        self.grado.save()
        self.client.post(self.url, {'nivel': 'PRIMARIA', 'numero': 3, 'activo': 'on'})
        self.grado.refresh_from_db()
        self.assertFalse(self.grado.activo)

    def test_grado_inexistente_da_404(self):
        self.assertEqual(self.client.get(reverse('grados:editar', args=[9999])).status_code, 404)


# ---------------------------------------------------------------------------
# Perfil del grado
# ---------------------------------------------------------------------------
@PRUEBAS
class DetalleTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba('2026-2027')
        self.viejo = ciclo_cerrado_de_prueba('2025-2026')
        self.grado = crear_grado('PRIMARIA', 4)
        self.siguiente = crear_grado('PRIMARIA', 5)
        self.ana = crear_alumno(nombre='Ana', apellido_paterno='Zamora')
        self.beto = crear_alumno(nombre='Beto', apellido_paterno='Aranda')
        inscribir(self.ana, self.ciclo, self.grado)
        inscribir(self.beto, self.ciclo, self.grado)

    def detalle(self, **filtros):
        respuesta = self.client.get(self.grado.get_absolute_url(), filtros)
        self.assertEqual(respuesta.status_code, 200)
        return respuesta

    def test_lista_de_alumnos_en_orden_alfabetico(self):
        respuesta = self.detalle()
        self.assertEqual([i.alumno.apellido_paterno for i in respuesta.context['inscripciones']], ['Aranda', 'Zamora'])
        self.assertEqual(respuesta.context['ciclo'], self.ciclo)

    def test_solo_inscripciones_activas_del_ciclo(self):
        inscribir(crear_alumno(), self.ciclo, self.grado, activa=False)
        inscribir(crear_alumno(), self.viejo, self.grado)
        inscribir(crear_alumno(), self.ciclo, self.siguiente)
        self.assertEqual(len(self.detalle().context['inscripciones']), 2)

    def test_elige_otro_ciclo(self):
        inscribir(crear_alumno(nombre='Vieja', apellido_paterno='Gomez'), self.viejo, self.grado)
        respuesta = self.detalle(ciclo=self.viejo.pk)
        self.assertEqual(respuesta.context['ciclo'], self.viejo)
        self.assertEqual([i.alumno.nombre for i in respuesta.context['inscripciones']], ['Vieja'])

    def test_un_ciclo_invalido_se_ignora(self):
        for valor in ('x', '9999', '-1'):
            self.assertEqual(self.detalle(ciclo=valor).context['ciclo'], self.ciclo, valor)

    def test_muestra_al_tutor_principal_sin_consultas_por_alumno(self):
        madre = crear_tutor(nombre='Rosa', apellido_paterno='Zamora', telefono='3531112233')
        padre = crear_tutor(nombre='Jorge', apellido_paterno='Zamora', telefono='3532223344')
        vincular(padre, self.ana, parentesco='PADRE')
        vincular(madre, self.ana, tutor_principal=True)
        respuesta = self.detalle()
        self.assertContains(respuesta, 'Rosa Zamora')
        self.assertContains(respuesta, '353 111 2233')
        self.assertContains(respuesta, 'Sin tutor')                    # Beto no tiene
        with CaptureQueriesContext(connection) as pocas:
            self.detalle()
        for i in range(8):
            alumno = crear_alumno()
            inscribir(alumno, self.ciclo, self.grado)
            vincular(crear_tutor(nombre=f'T{i}'), alumno, tutor_principal=True)
        with CaptureQueriesContext(connection) as muchas:
            self.detalle()
        self.assertEqual(len(muchas), len(pocas))

    def test_un_tutor_de_baja_no_cuenta_como_contacto(self):
        tutor = crear_tutor(nombre='Rosa', estatus='INACTIVO')
        vincular(tutor, self.ana, tutor_principal=True)
        self.assertNotContains(self.detalle(), 'Rosa Mora')

    def test_indica_a_que_grado_pasan(self):
        self.assertEqual(self.detalle().context['siguiente'], self.siguiente)
        self.assertContains(self.detalle(), '5° Primaria')

    def test_el_ultimo_grado_no_tiene_siguiente(self):
        respuesta = self.client.get(self.siguiente.get_absolute_url())
        self.assertIsNone(respuesta.context['siguiente'])
        self.assertContains(respuesta, 'Último grado')

    def test_historial_por_ciclo(self):
        inscribir(crear_alumno(), self.viejo, self.grado)
        inscribir(crear_alumno(), self.viejo, self.grado, activa=False)
        historial = self.detalle().context['historial']
        self.assertEqual([(h['ciclo__nombre'], h['activas'], h['bajas']) for h in historial], [('2026-2027', 2, 0), ('2025-2026', 1, 1)])

    def test_materias_del_ciclo(self):
        materia = Materia.objects.create(clave='ESP', nombre='Español')
        MateriaGrado.objects.create(ciclo=self.ciclo, grado=self.grado, materia=materia)
        MateriaGrado.objects.create(ciclo=self.viejo, grado=self.grado, materia=Materia.objects.create(clave='ING', nombre='Inglés'))
        respuesta = self.detalle()
        self.assertEqual([m.materia.nombre for m in respuesta.context['materias']], ['Español'])
        self.assertContains(respuesta, 'Español')

    def test_sin_ciclos_no_falla(self):
        from Alumnos.models import CicloEscolar, Inscripcion
        Inscripcion.objects.all().delete()
        CicloEscolar.objects.all().delete()
        respuesta = self.detalle()
        self.assertIsNone(respuesta.context['ciclo'])
        self.assertContains(respuesta, 'Aún no hay ciclos escolares')

    def test_un_grado_de_baja_lo_indica_y_no_ofrece_inscribir(self):
        self.grado.activo = False
        self.grado.save()
        respuesta = self.detalle()
        self.assertTrue(respuesta.context['esta_de_baja'])
        self.assertContains(respuesta, 'Grado dado de baja')
        self.assertContains(respuesta, 'Reactivar grado')
        self.assertNotContains(respuesta, 'Inscribir alumno')

    def test_el_aviso_de_baja_cuenta_los_inscritos_actuales(self):
        self.assertEqual(self.detalle().context['inscritos_actuales'], 2)
        self.assertContains(self.detalle(), 'Tiene 2 alumnos inscritos en el ciclo actual')

    def test_grado_inexistente_da_404(self):
        self.assertEqual(self.client.get(reverse('grados:detalle', args=[9999])).status_code, 404)


# ---------------------------------------------------------------------------
# Baja lógica y reactivación
# ---------------------------------------------------------------------------
@PRUEBAS
class BajaTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.grado = crear_grado('PRIMARIA', 1)
        self.inscripcion = inscribir(crear_alumno(), self.ciclo, self.grado)

    def test_da_de_baja_redirige_al_listado_y_confirma(self):
        respuesta = self.client.post(reverse('grados:baja', args=[self.grado.pk]), follow=True)
        self.assertRedirects(respuesta, reverse('grados:lista'))
        self.assertContains(respuesta, 'El grado 1° Primaria fue dado de baja')
        self.grado.refresh_from_db()
        self.assertFalse(self.grado.activo)

    def test_no_borra_nada(self):
        self.client.post(reverse('grados:baja', args=[self.grado.pk]))
        self.assertTrue(Grado.objects.filter(pk=self.grado.pk).exists())
        self.inscripcion.refresh_from_db()
        self.assertTrue(self.inscripcion.activa)

    def test_deja_de_ofrecerse_al_inscribir(self):
        self.client.post(reverse('grados:baja', args=[self.grado.pk]))
        opciones = self.client.get(reverse('inscripciones:crear')).context['form'].fields['grado'].queryset
        self.assertNotIn(self.grado, opciones)

    def test_dar_de_baja_dos_veces_es_inofensivo(self):
        self.client.post(reverse('grados:baja', args=[self.grado.pk]))
        respuesta = self.client.post(reverse('grados:baja', args=[self.grado.pk]), follow=True)
        self.assertContains(respuesta, 'ya estaba dado de baja')

    def test_reactivar(self):
        self.client.post(reverse('grados:baja', args=[self.grado.pk]))
        respuesta = self.client.post(reverse('grados:reactivar', args=[self.grado.pk]), follow=True)
        self.assertRedirects(respuesta, reverse('grados:lista'))
        self.assertContains(respuesta, 'fue reactivado')
        self.grado.refresh_from_db()
        self.assertTrue(self.grado.activo)
        opciones = self.client.get(reverse('inscripciones:crear')).context['form'].fields['grado'].queryset
        self.assertIn(self.grado, opciones)

    def test_reactivar_uno_activo_no_cambia_nada(self):
        respuesta = self.client.post(reverse('grados:reactivar', args=[self.grado.pk]), follow=True)
        self.assertNotContains(respuesta, 'fue reactivado')

    def test_grado_inexistente_da_404(self):
        self.assertEqual(self.client.post(reverse('grados:baja', args=[9999])).status_code, 404)


# ---------------------------------------------------------------------------
# Exportación de la lista del grado
# ---------------------------------------------------------------------------
@PRUEBAS
class ExportarTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.viejo = ciclo_cerrado_de_prueba()
        self.grado = crear_grado('PRIMARIA', 4)

    def filas(self, **filtros):
        respuesta = self.client.get(reverse('grados:exportar', args=[self.grado.pk]), filtros)
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('text/csv', respuesta['Content-Type'])
        self.assertIn('attachment; filename="grado-primaria-4-', respuesta['Content-Disposition'])
        contenido = respuesta.content.decode('utf-8')
        self.assertTrue(contenido.startswith('﻿'))
        return list(csv.reader(io.StringIO(contenido.lstrip('﻿'))))

    def test_exporta_a_los_alumnos_activos_del_ciclo(self):
        inscribir(crear_alumno(nombre='=Ana', apellido_paterno='Zamora', referencia='10'), self.ciclo, self.grado)
        inscribir(crear_alumno(nombre='Beto', apellido_paterno='Aranda', referencia='11'), self.ciclo, self.grado)
        inscribir(crear_alumno(nombre='Baja'), self.ciclo, self.grado, activa=False)
        inscribir(crear_alumno(nombre='Vieja'), self.viejo, self.grado)
        filas = self.filas()
        self.assertEqual(filas[0][:2], ['Referencia', 'Apellido paterno'])
        self.assertEqual([f[3] for f in filas[1:]], ['Beto', "'=Ana"])      # orden alfabético y fórmulas neutralizadas

    def test_exporta_otro_ciclo(self):
        inscribir(crear_alumno(nombre='Vieja'), self.viejo, self.grado)
        self.assertEqual([f[3] for f in self.filas(ciclo=self.viejo.pk)[1:]], ['Vieja'])

    def test_sin_alumnos_solo_trae_el_encabezado(self):
        self.assertEqual(len(self.filas()), 1)
