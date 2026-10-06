"""La sección de asignaciones: tablero, carga por profesor, pasar clases, movimientos y exportación."""
import csv
import io

from django.contrib.admin.models import LogEntry
from django.urls import reverse

from Alumnos.docentes import habilitar
from Alumnos.models import MateriaGrado
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    ciclo_cerrado_de_prueba,
    ciclo_proximo_de_prueba,
    crear_grado,
    crear_profesor,
)
from Profesores.tests import asignar, bloque, crear_materia


class AsignacionesTestCase(BaseTestCase):
    """Un ciclo actual con tres grados, tres materias y dos profesores (Marta habilitada en Matemáticas)."""

    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.g1, self.g2 = crear_grado('PRIMARIA', 1), crear_grado('PRIMARIA', 2)
        self.sec = crear_grado('SECUNDARIA', 1)
        self.mat = crear_materia('MAT', 'Matemáticas')
        self.esp = crear_materia('ESP', 'Español')
        self.ing = crear_materia('ING', 'Inglés')
        self.marta = crear_profesor(nombre='Marta', apellido_paterno='Rangel', especialidad='Matemáticas', horas_maximas=2)
        self.beto = crear_profesor(nombre='Beto', apellido_paterno='Aguilar', telefono='3530000002')
        habilitar(self.marta, [self.mat])
        self.a_mat1 = asignar(self.mat, self.g1, self.ciclo, profesor=self.marta)
        self.a_esp1 = asignar(self.esp, self.g1, self.ciclo)
        self.a_mat2 = asignar(self.mat, self.g2, self.ciclo, profesor=self.beto)   # Beto no está habilitado en Matemáticas
        self.a_ing_s = asignar(self.ing, self.sec, self.ciclo)
        bloque(self.a_mat1, 0, (8, 0), (9, 30))
        bloque(self.a_mat2, 1, (8, 0), (9, 0))

    def filas(self, **parametros):
        respuesta = self.client.get(reverse('asignaciones:tablero'), parametros)
        return respuesta, [(f.materia.clave, str(f.grado)) for f in respuesta.context['filas']]


# ---------------------------------------------------------------------------
# Permisos
# ---------------------------------------------------------------------------
@PRUEBAS
class PermisosTests(AsignacionesTestCase):
    def test_sin_sesion_se_manda_a_iniciar_sesion(self):
        self.client.logout()
        for nombre in ('tablero', 'carga', 'movimientos', 'exportar'):
            self.assertEqual(self.client.get(reverse(f'asignaciones:{nombre}')).status_code, 302, nombre)

    def test_sin_permiso_todo_es_403(self):
        self.client.force_login(self.sin_permisos)
        for nombre in ('tablero', 'carga', 'movimientos', 'exportar'):
            self.assertEqual(self.client.get(reverse(f'asignaciones:{nombre}')).status_code, 403, nombre)
        self.assertEqual(self.client.post(reverse('asignaciones:transferir')).status_code, 403)

    def test_ver_el_plan_basta_para_el_tablero_los_movimientos_y_la_exportacion(self):
        self.con_permisos('view_materiagrado')
        for nombre in ('tablero', 'movimientos', 'exportar'):
            self.assertEqual(self.client.get(reverse(f'asignaciones:{nombre}')).status_code, 200, nombre)

    def test_la_carga_tambien_pide_ver_profesores(self):
        self.con_permisos('view_materiagrado')
        self.assertEqual(self.client.get(reverse('asignaciones:carga')).status_code, 403)
        self.con_permisos('view_materiagrado', 'view_profesor')
        self.assertEqual(self.client.get(reverse('asignaciones:carga')).status_code, 200)

    def test_transferir_pide_cambiar_el_plan(self):
        datos = {'ciclo': self.ciclo.pk, 'origen': self.marta.pk, 'destino': self.beto.pk}
        self.con_permisos('view_materiagrado', 'view_profesor')
        self.assertEqual(self.client.post(reverse('asignaciones:transferir'), datos).status_code, 403)
        self.con_permisos('change_materiagrado')
        self.assertEqual(self.client.post(reverse('asignaciones:transferir'), datos).status_code, 302)

    def test_los_controles_de_edicion_dependen_del_permiso(self):
        self.con_permisos('view_materiagrado')
        respuesta = self.client.get(reverse('asignaciones:tablero'))
        self.assertNotContains(respuesta, 'data-asignar-profesor')
        self.assertNotContains(respuesta, 'data-asignacion-masiva')
        self.con_permisos('view_materiagrado', 'change_materiagrado', 'view_profesor')
        respuesta = self.client.get(reverse('asignaciones:tablero'))
        self.assertContains(respuesta, 'data-asignar-profesor')
        self.assertContains(respuesta, 'data-asignacion-masiva')

    def test_el_menu_la_ofrece_a_quien_puede_ver_el_plan(self):
        self.con_permisos('view_materiagrado')
        self.assertContains(self.client.get(reverse('inicio')), 'Asignaciones')
        self.con_permisos('view_materia')
        self.assertNotContains(self.client.get(reverse('inicio')), reverse('asignaciones:tablero'))


# ---------------------------------------------------------------------------
# Tablero
# ---------------------------------------------------------------------------
@PRUEBAS
class TableroTests(AsignacionesTestCase):
    def test_lista_las_materias_vigentes_en_orden_escolar(self):
        _, filas = self.filas()
        self.assertEqual(filas, [
            ('ESP', '1° Primaria'), ('MAT', '1° Primaria'), ('MAT', '2° Primaria'), ('ING', '1° Secundaria'),
        ])

    def test_no_muestra_materias_quitadas_ni_de_otros_ciclos(self):
        self.a_esp1.activa = False
        self.a_esp1.save()
        asignar(self.esp, self.g2, ciclo_cerrado_de_prueba())
        _, filas = self.filas()
        self.assertNotIn(('ESP', '1° Primaria'), filas)
        self.assertEqual(len(filas), 3)

    def test_marca_a_quien_no_esta_habilitado(self):
        respuesta, _ = self.filas()
        por_pk = {f.pk: f for f in respuesta.context['filas']}
        self.assertTrue(por_pk[self.a_mat1.pk].profesor_habilitado)
        self.assertFalse(por_pk[self.a_mat2.pk].profesor_habilitado)
        self.assertContains(respuesta, 'Sin habilitar', count=1)
        self.assertContains(respuesta, f'data-habilitados="{self.marta.pk}"')

    def test_indicadores_del_ciclo(self):
        respuesta, _ = self.filas()
        resumen = respuesta.context['resumen']
        self.assertEqual((resumen['materias'], resumen['con_profesor'], resumen['sin_profesor']), (4, 2, 2))
        self.assertEqual(resumen['avance'], 50)
        self.assertEqual(resumen['sin_horario'], 2)

    def test_filtra_por_estado(self):
        for estado, esperado in (
            ('sin_profesor', {('ESP', '1° Primaria'), ('ING', '1° Secundaria')}),
            ('con_profesor', {('MAT', '1° Primaria'), ('MAT', '2° Primaria')}),
            ('no_habilitado', {('MAT', '2° Primaria')}),
            ('sin_horario', {('ESP', '1° Primaria'), ('ING', '1° Secundaria')}),
        ):
            with self.subTest(estado=estado):
                self.assertEqual(set(self.filas(estado=estado)[1]), esperado)

    def test_filtra_por_grado_y_por_profesor(self):
        self.assertEqual(set(self.filas(grado=self.g1.pk)[1]), {('ESP', '1° Primaria'), ('MAT', '1° Primaria')})
        self.assertEqual(self.filas(profesor=self.beto.pk)[1], [('MAT', '2° Primaria')])

    def test_busca_por_materia_clave_y_profesor_sin_duplicar(self):
        for texto, esperado in (('ingl', [('ING', '1° Secundaria')]), ('esp', [('ESP', '1° Primaria')]),
                                ('aguilar', [('MAT', '2° Primaria')]), ('zzz', [])):
            self.assertEqual(self.filas(q=texto)[1], esperado, texto)
        self.assertEqual(len(self.filas(q='mat')[1]), 2)

    def test_un_filtro_invalido_se_ignora(self):
        self.assertEqual(len(self.filas(estado='xx', grado='abc', profesor='999')[1]), 4)

    def test_sin_resultados_ofrece_limpiar_filtros(self):
        respuesta, _ = self.filas(q='zzz')
        self.assertContains(respuesta, 'No encontramos asignaciones con esos filtros')

    def test_pagina_los_resultados(self):
        respuesta = self.client.get(reverse('asignaciones:tablero'), {'por_pagina': 10})
        self.assertEqual(respuesta.context['por_pagina'], 10)
        for n in range(3, 15):
            asignar(crear_materia(f'M{n}', f'Materia {n}'), self.g1, self.ciclo)
        respuesta = self.client.get(reverse('asignaciones:tablero'), {'por_pagina': 10})
        self.assertEqual(len(respuesta.context['filas']), 10)
        self.assertEqual(respuesta.context['pagina'].paginator.num_pages, 2)

    def test_consulta_otro_ciclo(self):
        proximo = ciclo_proximo_de_prueba()
        asignar(self.esp, self.g2, proximo)
        respuesta, filas = self.filas(ciclo=proximo.pk)
        self.assertEqual(filas, [('ESP', '2° Primaria')])
        self.assertEqual(respuesta.context['ciclo'], proximo)

    def test_un_ciclo_cerrado_no_se_edita(self):
        cerrado = ciclo_cerrado_de_prueba()
        asignar(self.esp, self.g2, cerrado, profesor=self.beto)
        respuesta, _ = self.filas(ciclo=cerrado.pk)
        self.assertFalse(respuesta.context['editable'])
        self.assertContains(respuesta, 'está cerrado')
        self.assertNotContains(respuesta, 'data-asignar-profesor')
        self.assertNotContains(respuesta, 'data-asignacion-masiva')

    def test_sin_ciclos_explica_que_hay_que_crear_uno(self):
        MateriaGrado.objects.all().delete()
        self.ciclo.delete()
        respuesta = self.client.get(reverse('asignaciones:tablero'))
        self.assertContains(respuesta, 'Aún no hay ciclos escolares')

    def test_ciclo_sin_materias_explica_que_hay_que_armar_el_plan(self):
        MateriaGrado.objects.all().delete()
        self.assertContains(self.client.get(reverse('asignaciones:tablero')), 'aún no tiene materias en los grados')

    def test_la_barra_de_asignacion_masiva_envia_a_asignar_con_la_pagina_de_regreso(self):
        respuesta = self.client.get(reverse('asignaciones:tablero'), {'estado': 'sin_profesor'})
        self.assertContains(respuesta, f'action="{reverse("profesores:asignar")}"')
        self.assertContains(respuesta, 'value="/asignaciones/lista/?estado=sin_profesor"')
        self.assertContains(respuesta, 'data-masiva-fila', count=2)   # una casilla por materia que sigue en la lista filtrada

    def test_asignar_en_bloque_con_la_vista_de_asignar(self):
        self.client.post(reverse('profesores:asignar'), {
            'asignacion': [self.a_esp1.pk, self.a_ing_s.pk], 'profesor': self.beto.pk, 'next': reverse('asignaciones:tablero'),
        })
        self.a_esp1.refresh_from_db()
        self.a_ing_s.refresh_from_db()
        self.assertEqual((self.a_esp1.profesor, self.a_ing_s.profesor), (self.beto, self.beto))

    def test_el_marcador_de_la_barra_no_quita_profesores_si_no_se_elige_a_nadie(self):
        # La barra manda «-» mientras no se elija un profesor: la vista de asignar lo rechaza en vez de quitarlos
        self.client.post(reverse('profesores:asignar'), {'asignacion': [self.a_mat1.pk], 'profesor': '-'})
        self.a_mat1.refresh_from_db()
        self.assertEqual(self.a_mat1.profesor, self.marta)


# ---------------------------------------------------------------------------
# Carga por profesor
# ---------------------------------------------------------------------------
@PRUEBAS
class CargaTests(AsignacionesTestCase):
    def pedir(self, **parametros):
        return self.client.get(reverse('asignaciones:carga'), parametros)

    def nombres(self, respuesta):
        return [str(c['profesor']) for c in respuesta.context['cargas']]

    def test_muestra_a_los_profesores_activos_con_su_carga(self):
        respuesta = self.pedir()
        cargas = {c['profesor'].pk: c for c in respuesta.context['cargas']}
        self.assertEqual(cargas[self.marta.pk]['duracion'], '1 h 30 min')
        self.assertEqual(cargas[self.marta.pk]['estado'], 'normal')
        self.assertEqual(cargas[self.beto.pk]['estado'], 'sin_limite')
        self.assertContains(respuesta, '1 h 30 min de 2 h')

    def test_la_sobrecarga_se_distingue(self):
        bloque(self.a_mat1, 2, (8, 0), (9, 0))
        respuesta = self.pedir(estado='sobrecarga')
        self.assertEqual(self.nombres(respuesta), [str(self.marta)])
        self.assertContains(respuesta, 'meter--danger')
        self.assertEqual(respuesta.context['conteos']['sobrecarga'], 1)

    def test_filtra_por_estado(self):
        crear_profesor(nombre='Libre', apellido_paterno='Zepeda', telefono='3530000003')
        self.assertEqual(self.nombres(self.pedir(estado='libre')), ['Libre Zepeda Soto'])
        self.assertEqual(sorted(self.nombres(self.pedir(estado='con_carga'))), sorted([str(self.marta), str(self.beto)]))

    def test_busca_por_nombre_y_especialidad(self):
        self.assertEqual(self.nombres(self.pedir(q='matem')), [str(self.marta)])
        self.assertEqual(self.nombres(self.pedir(q='aguilar')), [str(self.beto)])

    def test_ordena_por_carga(self):
        self.assertEqual(self.nombres(self.pedir(orden='-carga')), [str(self.marta), str(self.beto)])
        self.assertEqual(self.nombres(self.pedir(orden='carga')), [str(self.beto), str(self.marta)])

    def test_un_profesor_de_baja_con_clases_aparece_con_aviso(self):
        self.beto.estatus = 'INACTIVO'
        self.beto.save()
        respuesta = self.pedir()
        self.assertIn(str(self.beto), self.nombres(respuesta))
        self.assertEqual([c['profesor'] for c in respuesta.context['de_baja_con_clases']], [self.beto])
        self.assertContains(respuesta, 'está de baja y todavía imparte')

    def test_un_profesor_de_baja_sin_clases_no_aparece(self):
        crear_profesor(nombre='Vieja', apellido_paterno='Zepeda', telefono='3530000003', estatus='INACTIVO')
        self.assertNotIn('Vieja Zepeda Soto', self.nombres(self.pedir()))

    def test_ofrece_pasar_clases_solo_donde_se_puede(self):
        respuesta = self.pedir()
        self.assertContains(respuesta, 'data-origen=', count=2)   # el botón de Marta y el de Beto
        self.assertContains(respuesta, 'id="modal-transferir"')
        cerrado = ciclo_cerrado_de_prueba()
        asignar(self.esp, self.g2, cerrado, profesor=self.beto)
        respuesta = self.pedir(ciclo=cerrado.pk)
        self.assertNotContains(respuesta, 'modal-transferir')

    def test_sin_clases_no_hay_boton_de_pasar_clases(self):
        MateriaGrado.objects.update(profesor=None)
        self.assertNotContains(self.pedir(), 'data-origen=')


# ---------------------------------------------------------------------------
# Pasar las clases de un profesor a otro
# ---------------------------------------------------------------------------
@PRUEBAS
class TransferirTests(AsignacionesTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse('asignaciones:transferir')

    def pasar(self, origen=None, destino=None, **extra):
        datos = {'ciclo': self.ciclo.pk, 'origen': (origen or self.marta).pk, 'destino': destino}
        datos.update(extra)
        return self.client.post(self.url, {k: v for k, v in datos.items() if v is not None}, follow=True)

    def test_pasa_todas_las_clases_del_profesor_y_deja_bitacora(self):
        otra = asignar(self.esp, self.g2, self.ciclo, profesor=self.marta)
        bloque(otra, 3, (10, 0), (11, 0))
        respuesta = self.pasar(destino=self.beto.pk)
        self.assertContains(respuesta, '2 materias de Marta Rangel Soto pasaron a Beto Aguilar Soto')
        self.assertEqual(MateriaGrado.objects.filter(profesor=self.marta).count(), 0)
        self.assertEqual(MateriaGrado.objects.filter(profesor=self.beto).count(), 3)
        self.assertEqual(LogEntry.objects.count(), 2)
        self.assertIn('Marta Rangel Soto → Beto Aguilar Soto', LogEntry.objects.first().change_message)

    def test_una_sola_clase_se_cuenta_en_singular(self):
        self.assertContains(self.pasar(destino=self.beto.pk), '1 materia de Marta Rangel Soto pasó a Beto Aguilar Soto')

    def test_dejarlas_sin_profesor(self):
        respuesta = self.pasar(destino='ninguno')
        self.assertContains(respuesta, 'quedó sin profesor')
        self.a_mat1.refresh_from_db()
        self.assertIsNone(self.a_mat1.profesor)

    def test_lo_que_se_empalma_se_queda_con_quien_estaba_y_se_avisa(self):
        bloque(self.a_mat2, 0, (8, 30), (9, 30))   # Beto ya da clase el lunes a esa hora
        respuesta = self.pasar(destino=self.beto.pk)
        self.assertContains(respuesta, 'No se pudo pasar')
        self.a_mat1.refresh_from_db()
        self.assertEqual(self.a_mat1.profesor, self.marta)
        self.assertEqual(LogEntry.objects.count(), 0)

    def test_no_toca_las_clases_de_otros_profesores_ni_de_otros_ciclos(self):
        otro_ciclo = ciclo_proximo_de_prueba()
        futura = asignar(self.esp, self.g2, otro_ciclo, profesor=self.marta)
        self.pasar(destino=self.beto.pk)
        futura.refresh_from_db()
        self.a_mat2.refresh_from_db()
        self.assertEqual(futura.profesor, self.marta)
        self.assertEqual(self.a_mat2.profesor, self.beto)

    def test_un_ciclo_cerrado_no_se_modifica(self):
        cerrado = ciclo_cerrado_de_prueba()
        vieja = asignar(self.esp, self.g2, cerrado, profesor=self.marta)
        respuesta = self.client.post(self.url, {'ciclo': cerrado.pk, 'origen': self.marta.pk, 'destino': self.beto.pk}, follow=True)
        self.assertContains(respuesta, 'está cerrado')
        vieja.refresh_from_db()
        self.assertEqual(vieja.profesor, self.marta)

    def test_hay_que_elegir_a_quien_pasarselas(self):
        for destino in (None, '-', 'abc', str(self.marta.pk)):
            with self.subTest(destino=destino):
                respuesta = self.pasar(destino=destino)
                self.assertContains(respuesta, 'Elige a quién pasarle las materias')
        self.a_mat1.refresh_from_db()
        self.assertEqual(self.a_mat1.profesor, self.marta)

    def test_el_destino_debe_estar_activo(self):
        self.beto.estatus = 'INACTIVO'
        self.beto.save()
        self.assertContains(self.pasar(destino=self.beto.pk), 'Elige un profesor activo')
        self.a_mat1.refresh_from_db()
        self.assertEqual(self.a_mat1.profesor, self.marta)

    def test_quien_no_imparte_nada_lo_avisa(self):
        libre = crear_profesor(nombre='Libre', apellido_paterno='Zepeda', telefono='3530000003')
        self.assertContains(self.pasar(origen=libre, destino=self.beto.pk), 'no imparte ninguna materia')

    def test_datos_inexistentes(self):
        respuesta = self.client.post(self.url, {'ciclo': '999', 'origen': '999', 'destino': 'ninguno'}, follow=True)
        self.assertContains(respuesta, 'No se encontró el ciclo o el profesor')

    def test_regresa_a_la_carga_del_ciclo_o_a_la_pagina_indicada(self):
        respuesta = self.client.post(self.url, {'ciclo': self.ciclo.pk, 'origen': self.marta.pk, 'destino': self.beto.pk})
        self.assertEqual(respuesta['Location'], f'{reverse("asignaciones:carga")}?ciclo={self.ciclo.pk}')
        respuesta = self.client.post(self.url, {'ciclo': self.ciclo.pk, 'origen': self.beto.pk, 'destino': self.marta.pk,
                                                'next': 'https://malo.example/'})
        self.assertEqual(respuesta['Location'], f'{reverse("asignaciones:carga")}?ciclo={self.ciclo.pk}')

    def test_solo_acepta_post(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)


# ---------------------------------------------------------------------------
# Movimientos
# ---------------------------------------------------------------------------
@PRUEBAS
class MovimientosTests(AsignacionesTestCase):
    def pedir(self, **parametros):
        return self.client.get(reverse('asignaciones:movimientos'), parametros)

    def test_sin_movimientos(self):
        self.assertContains(self.pedir(), 'Todavía no hay movimientos')

    def test_muestra_asignaciones_y_habilitaciones_la_mas_reciente_primero(self):
        self.client.post(reverse('profesores:habilitar', args=[self.beto.pk]), {'materia': [self.esp.pk]})
        self.client.post(reverse('profesores:asignar'), {'asignacion': [self.a_esp1.pk], 'profesor': self.beto.pk})
        respuesta = self.pedir()
        tipos = [e['tipo'] for e in respuesta.context['entradas']]
        self.assertEqual(tipos, ['Asignación', 'Habilitación'])
        self.assertContains(respuesta, 'sin profesor → Beto Aguilar Soto')
        self.assertEqual(respuesta.context['entradas'][0]['quien'], 'admin')

    def test_filtra_por_tipo(self):
        self.client.post(reverse('profesores:habilitar', args=[self.beto.pk]), {'materia': [self.esp.pk]})
        self.client.post(reverse('profesores:asignar'), {'asignacion': [self.a_esp1.pk], 'profesor': self.beto.pk})
        self.assertEqual([e['tipo'] for e in self.pedir(tipo='asignaciones').context['entradas']], ['Asignación'])
        self.assertEqual([e['tipo'] for e in self.pedir(tipo='habilitaciones').context['entradas']], ['Habilitación'])
        self.assertEqual(len(self.pedir(tipo='raro').context['entradas']), 2)

    def test_ignora_otros_cambios_en_profesores(self):
        self.client.post(reverse('profesores:editar', args=[self.beto.pk]), {
            'nombre': 'Beto', 'apellido_paterno': 'Aguilar', 'apellido_materno': 'Soto', 'telefono': '3530000002',
        })
        self.client.post(reverse('profesores:habilitar', args=[self.beto.pk]), {'materia': [self.esp.pk]})
        self.assertEqual(len(self.pedir().context['entradas']), 1)

    def test_pagina(self):
        for n in range(25):
            self.client.post(reverse('profesores:asignar'), {
                'asignacion': [self.a_esp1.pk], 'profesor': (self.beto if n % 2 == 0 else self.marta).pk,
            })
        respuesta = self.pedir()
        self.assertEqual(len(respuesta.context['entradas']), 20)
        self.assertEqual(respuesta.context['pagina'].paginator.num_pages, 2)


# ---------------------------------------------------------------------------
# Exportación
# ---------------------------------------------------------------------------
@PRUEBAS
class ExportarTests(AsignacionesTestCase):
    def pedir(self, **parametros):
        respuesta = self.client.get(reverse('asignaciones:exportar'), parametros)
        contenido = respuesta.content.decode('utf-8').lstrip('﻿')
        return respuesta, list(csv.reader(io.StringIO(contenido)))

    def test_exporta_el_tablero_con_encabezados(self):
        respuesta, filas = self.pedir()
        self.assertEqual(respuesta['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('attachment; filename="asignaciones-', respuesta['Content-Disposition'])
        self.assertEqual(filas[0], ['Ciclo', 'Nivel', 'Grado', 'Materia', 'Clave', 'Profesor', 'Puede impartirla', 'Horario', 'Horas por semana'])
        self.assertEqual(len(filas), 5)

    def test_indica_si_el_profesor_esta_habilitado_y_el_horario(self):
        _, filas = self.pedir()
        por_materia = {(f[3], f[2]): f for f in filas[1:]}
        marta = por_materia[('Matemáticas', '1° Primaria')]
        self.assertEqual((marta[5], marta[6], marta[8]), ('Marta Rangel Soto', 'Sí', '1 h 30 min'))
        self.assertIn('8:00', marta[7])
        self.assertEqual(por_materia[('Matemáticas', '2° Primaria')][6], 'No')
        sin = por_materia[('Español', '1° Primaria')]
        self.assertEqual((sin[5], sin[6], sin[7]), ('Sin profesor', '', ''))

    def test_respeta_los_filtros_y_el_ciclo(self):
        _, filas = self.pedir(estado='sin_profesor')
        self.assertEqual({f[3] for f in filas[1:]}, {'Español', 'Inglés'})
        proximo = ciclo_proximo_de_prueba()
        asignar(self.esp, self.g2, proximo)
        _, filas = self.pedir(ciclo=proximo.pk)
        self.assertEqual([(f[0], f[3]) for f in filas[1:]], [(proximo.nombre, 'Español')])

    def test_neutraliza_formulas(self):
        self.mat.nombre = '=SUMA(1;1)'
        self.mat.save()
        _, filas = self.pedir(q='MAT')
        self.assertTrue(all(f[3].startswith("'=") for f in filas[1:]))

    def test_sin_ciclos_solo_trae_los_encabezados(self):
        MateriaGrado.objects.all().delete()
        self.ciclo.delete()
        _, filas = self.pedir()
        self.assertEqual(len(filas), 1)
