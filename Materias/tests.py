import csv
import io
from datetime import time
from unittest.mock import patch

from django.db import IntegrityError, connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from Alumnos.academico import materias_por_asignar
from Alumnos.models import HorarioMateria, Materia, MateriaGrado
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    ciclo_cerrado_de_prueba,
    ciclo_proximo_de_prueba,
    crear_grado,
)


def crear_materia(clave='MAT', nombre='Matemáticas', **cambios):
    return Materia.objects.create(clave=clave, nombre=nombre, **cambios)


def asignar(materia, grado, ciclo, **cambios):
    return MateriaGrado.objects.create(materia=materia, grado=grado, ciclo=ciclo, **cambios)


def bloque(asignacion, dia=0, inicio=(8, 0), fin=(9, 0)):
    return HorarioMateria.objects.create(materia_grado=asignacion, dia_semana=dia, hora_inicio=time(*inicio), hora_fin=time(*fin))


# ---------------------------------------------------------------------------
# Permisos
# ---------------------------------------------------------------------------
@PRUEBAS
class PermisosTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.materia = crear_materia()
        self.ciclo = ciclo_actual_de_prueba()
        self.asignacion = asignar(self.materia, crear_grado(), self.ciclo)

    def paginas(self):
        return (('lista', []), ('crear', []), ('exportar', []), ('copiar', []), ('detalle', [self.materia.pk]), ('editar', [self.materia.pk]))

    def acciones(self):
        return (('baja', [self.materia.pk]), ('reactivar', [self.materia.pk]), ('quitar', [self.asignacion.pk]),
                ('reactivar_asignacion', [self.asignacion.pk]), ('asignar', []))

    def test_anonimo_es_enviado_al_login(self):
        self.client.logout()
        for nombre, args in self.paginas():
            respuesta = self.client.get(reverse(f'materias:{nombre}', args=args))
            self.assertEqual(respuesta.status_code, 302, nombre)
            self.assertIn('/admin/login/', respuesta['Location'])

    def test_sin_permisos_recibe_403(self):
        self.client.force_login(self.sin_permisos)
        for nombre, args in self.paginas():
            self.assertEqual(self.client.get(reverse(f'materias:{nombre}', args=args)).status_code, 403, nombre)
        for nombre, args in self.acciones():
            self.assertEqual(self.client.post(reverse(f'materias:{nombre}', args=args)).status_code, 403, nombre)
        self.materia.refresh_from_db()
        self.assertTrue(self.materia.activa)

    def test_las_acciones_solo_aceptan_post(self):
        for nombre, args in self.acciones():
            self.assertEqual(self.client.get(reverse(f'materias:{nombre}', args=args)).status_code, 405, nombre)

    def test_cada_accion_pide_su_permiso(self):
        self.con_permisos('view_materia')
        self.assertEqual(self.client.get(reverse('materias:lista')).status_code, 200)
        for nombre, args in (('crear', []), ('editar', [self.materia.pk]), ('copiar', [])):
            self.assertEqual(self.client.get(reverse(f'materias:{nombre}', args=args)).status_code, 403, nombre)
        self.con_permisos('view_materia', 'add_materia')
        self.assertEqual(self.client.get(reverse('materias:crear')).status_code, 200)
        self.con_permisos('view_materia', 'change_materia')
        self.assertEqual(self.client.get(reverse('materias:editar', args=[self.materia.pk])).status_code, 200)
        self.assertEqual(self.client.post(reverse('materias:baja', args=[self.materia.pk])).status_code, 403)   # pide delete_materia
        self.con_permisos('view_materia', 'delete_materia')
        self.assertEqual(self.client.post(reverse('materias:baja', args=[self.materia.pk])).status_code, 302)

    def test_asignar_y_quitar_piden_permisos_de_asignacion(self):
        self.con_permisos('view_materia', 'add_materiagrado')
        self.assertEqual(self.client.post(reverse('materias:asignar')).status_code, 302)       # entra (y avisa que faltan datos)
        self.assertEqual(self.client.post(reverse('materias:quitar', args=[self.asignacion.pk])).status_code, 403)
        self.con_permisos('view_materia', 'delete_materiagrado')
        self.assertEqual(self.client.post(reverse('materias:quitar', args=[self.asignacion.pk])).status_code, 302)


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------
@PRUEBAS
class ListaTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.mat = crear_materia('MAT', 'Matemáticas')
        self.esp = crear_materia('ESP', 'Español')
        self.ing = crear_materia('ING', 'Inglés')
        self.vieja = crear_materia('OLD', 'Taller antiguo', activa=False)
        self.p1, self.p2 = crear_grado('PRIMARIA', 1), crear_grado('PRIMARIA', 2)
        asignar(self.mat, self.p1, self.ciclo)
        asignar(self.mat, self.p2, self.ciclo)
        asignar(self.esp, self.p1, self.ciclo)
        asignar(self.esp, self.p2, self.ciclo, activa=False)           # quitada: no cuenta
        asignar(self.ing, self.p1, ciclo_cerrado_de_prueba())          # otro ciclo: no cuenta

    def pedir(self, **filtros):
        respuesta = self.client.get(reverse('materias:lista'), filtros)
        self.assertEqual(respuesta.status_code, 200)
        return respuesta

    def claves(self, **filtros):
        return [m.clave for m in self.pedir(**filtros).context['pagina']]

    def test_por_defecto_solo_las_activas_en_orden_alfabetico(self):
        self.assertEqual(self.claves(), ['ESP', 'ING', 'MAT'])

    def test_las_bajas_se_ven_en_su_filtro(self):
        respuesta = self.pedir(estado='BAJA')
        self.assertEqual([m.clave for m in respuesta.context['pagina']], ['OLD'])
        self.assertTrue(respuesta.context['viendo_bajas'])
        self.assertContains(respuesta, 'Reactivar')

    def test_conteos_de_las_pestanas(self):
        self.assertEqual(self.pedir().context['conteos'], {'activas': 3, 'bajas': 1})
        self.assertEqual(self.pedir(q='mat').context['conteos'], {'activas': 1, 'bajas': 0})

    def test_busca_por_clave_y_nombre(self):
        self.assertEqual(self.claves(q='mat'), ['MAT'])
        self.assertEqual(self.claves(q='españ'), ['ESP'])
        self.assertEqual(self.claves(q='IN'), ['ING'])
        self.assertEqual(self.claves(q='nadie'), [])

    def test_cuenta_los_grados_del_ciclo_actual(self):
        grados = {m.clave: m.grados for m in self.pedir().context['pagina']}
        self.assertEqual(grados, {'ESP': 1, 'ING': 0, 'MAT': 2})

    def test_sin_ciclo_actual_no_falla(self):
        self.ciclo.activo = False
        self.ciclo.save()
        respuesta = self.pedir()
        self.assertEqual({m.grados for m in respuesta.context['pagina']}, {0})

    def test_pagina_y_tamano(self):
        for i in range(25):
            crear_materia(f'X{i:02d}', f'Relleno {i:02d}')
        respuesta = self.pedir()
        self.assertEqual(respuesta.context['pagina'].paginator.count, 28)
        self.assertEqual(len(respuesta.context['pagina']), 20)
        self.assertEqual(len(self.pedir(page=2).context['pagina']), 8)
        self.assertEqual(self.pedir(por_pagina=7).context['por_pagina'], 20)

    def test_consultas_constantes(self):
        with CaptureQueriesContext(connection) as pocas:
            self.pedir(por_pagina=10)
        for i in range(25):
            crear_materia(f'Y{i:02d}', f'Otra {i:02d}')
        with CaptureQueriesContext(connection) as muchas:
            self.pedir(por_pagina=50)
        self.assertLessEqual(len(muchas), len(pocas))

    def test_estados_vacios(self):
        MateriaGrado.objects.all().delete()
        Materia.objects.all().delete()
        self.assertContains(self.pedir(), 'Aún no hay materias')
        self.assertContains(self.pedir(estado='BAJA'), 'No hay materias dadas de baja')
        self.assertContains(self.pedir(q='zzz'), 'No encontramos materias')


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
@PRUEBAS
class CrearTests(BaseTestCase):
    url = property(lambda self: reverse('materias:crear'))

    def test_registra_y_vuelve_al_listado_con_mensaje(self):
        respuesta = self.client.post(self.url, {'clave': 'mat', 'nombre': 'Matemáticas'}, follow=True)
        self.assertRedirects(respuesta, reverse('materias:lista'))
        self.assertContains(respuesta, 'La materia Matemáticas fue registrada')
        materia = Materia.objects.get()
        self.assertEqual((materia.clave, materia.activa), ('MAT', True))

    def test_normaliza_clave_y_nombre(self):
        self.client.post(self.url, {'clave': '  ed   fis ', 'nombre': '  Educación   física '})
        materia = Materia.objects.get()
        self.assertEqual((materia.clave, materia.nombre), ('ED-FIS', 'Educación física'))

    def test_la_clave_no_se_repite_aunque_cambien_las_mayusculas(self):
        crear_materia('MAT', 'Matemáticas')
        respuesta = self.client.post(self.url, {'clave': 'mat', 'nombre': 'Otra'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Ya existe una materia con esa clave')
        self.assertEqual(Materia.objects.count(), 1)

    def test_la_clave_solo_admite_letras_numeros_punto_y_guion(self):
        for clave in ('M@T', 'mat/1', 'a,b'):
            respuesta = self.client.post(self.url, {'clave': clave, 'nombre': 'X'})
            self.assertIn('clave', respuesta.context['form'].errors, clave)
        for clave in ('MAT-1', 'ed.fis', 'ÉTICA', 'A_1'):
            self.assertEqual(self.client.post(self.url, {'clave': clave, 'nombre': 'X'}).status_code, 302, clave)

    def test_campos_obligatorios_y_largo(self):
        respuesta = self.client.post(self.url, {})
        self.assertEqual(set(respuesta.context['form'].errors), {'clave', 'nombre'})
        respuesta = self.client.post(self.url, {'clave': 'A' * 21, 'nombre': 'X'})
        self.assertIn('clave', respuesta.context['form'].errors)


@PRUEBAS
class EditarTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.materia = crear_materia('MAT', 'Matemáticas')
        self.otra = crear_materia('ESP', 'Español')
        self.url = reverse('materias:editar', args=[self.materia.pk])

    def test_formulario_precargado(self):
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, 'value="MAT"')
        self.assertEqual(list(respuesta.context['form'].fields), ['clave', 'nombre'])

    def test_actualiza_y_vuelve_al_listado(self):
        respuesta = self.client.post(self.url, {'clave': 'MATE', 'nombre': 'Matemáticas I'}, follow=True)
        self.assertRedirects(respuesta, reverse('materias:lista'))
        self.assertContains(respuesta, 'se actualizó')
        self.materia.refresh_from_db()
        self.assertEqual((self.materia.clave, self.materia.nombre), ('MATE', 'Matemáticas I'))

    def test_conserva_su_propia_clave(self):
        self.assertEqual(self.client.post(self.url, {'clave': 'mat', 'nombre': 'Mate'}).status_code, 302)

    def test_no_permite_la_clave_de_otra_materia(self):
        respuesta = self.client.post(self.url, {'clave': 'ESP', 'nombre': 'Mate'})
        self.assertIn('clave', respuesta.context['form'].errors)

    def test_editar_no_cambia_el_estado(self):
        self.materia.activa = False
        self.materia.save()
        self.client.post(self.url, {'clave': 'MAT', 'nombre': 'Mate', 'activa': 'on'})
        self.materia.refresh_from_db()
        self.assertFalse(self.materia.activa)

    def test_materia_inexistente_da_404(self):
        self.assertEqual(self.client.get(reverse('materias:editar', args=[9999])).status_code, 404)


# ---------------------------------------------------------------------------
# Perfil
# ---------------------------------------------------------------------------
@PRUEBAS
class DetalleTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.actual = ciclo_actual_de_prueba('2026-2027')
        self.proximo = ciclo_proximo_de_prueba('2027-2028')
        self.cerrado = ciclo_cerrado_de_prueba('2025-2026')
        self.materia = crear_materia()
        self.p1, self.p2, self.p3 = crear_grado('PRIMARIA', 1), crear_grado('PRIMARIA', 2), crear_grado('PRIMARIA', 3)
        self.a1 = asignar(self.materia, self.p1, self.actual)
        self.a2 = asignar(self.materia, self.p2, self.actual, activa=False)
        bloque(self.a1, 0, (8, 0), (9, 0))
        bloque(self.a1, 2, (8, 0), (9, 0))
        bloque(self.a1, 4, (10, 0), (10, 45))

    def detalle(self, **filtros):
        respuesta = self.client.get(self.materia.get_absolute_url(), filtros)
        self.assertEqual(respuesta.status_code, 200)
        return respuesta

    def test_grados_del_ciclo_con_su_horario(self):
        respuesta = self.detalle()
        filas = respuesta.context['asignaciones']
        self.assertEqual([str(f.grado) for f in filas], ['1° Primaria', '2° Primaria'])
        self.assertEqual(filas[0].lineas, ['Lun, Mié · 08:00–09:00', 'Vie · 10:00–10:45'])
        self.assertEqual(filas[0].duracion, '2 h 45 min')
        self.assertEqual(respuesta.context['total_grados'], 1)                  # la quitada no cuenta
        self.assertEqual(respuesta.context['horas_semanales'], '2 h 45 min')

    def test_muestra_las_quitadas_y_ofrece_volver_a_asignarlas(self):
        self.assertContains(self.detalle(), 'Volver a asignar')

    def test_ofrece_los_grados_pendientes_agrupados_por_nivel(self):
        grupos = self.detalle().context['grupos_por_asignar']
        self.assertEqual([(g['nombre'], [str(x) for x in g['grados']]) for g in grupos], [('Primaria', ['2° Primaria', '3° Primaria'])])

    def test_elige_otro_ciclo(self):
        respuesta = self.detalle(ciclo=self.proximo.pk)
        self.assertEqual(respuesta.context['ciclo'], self.proximo)
        self.assertEqual(respuesta.context['asignaciones'], [])
        self.assertEqual(respuesta.context['total_grados'], 0)

    def test_un_ciclo_cerrado_es_de_solo_lectura(self):
        asignar(self.materia, self.p1, self.cerrado)
        respuesta = self.detalle(ciclo=self.cerrado.pk)
        self.assertFalse(respuesta.context['editable'])
        self.assertEqual(respuesta.context['grupos_por_asignar'], [])
        self.assertContains(respuesta, 'está cerrado')
        self.assertNotContains(respuesta, 'data-quitar')

    def test_una_materia_de_baja_no_ofrece_asignar(self):
        self.materia.activa = False
        self.materia.save()
        respuesta = self.detalle()
        self.assertEqual(respuesta.context['grupos_por_asignar'], [])
        self.assertContains(respuesta, 'Materia dada de baja')
        self.assertContains(respuesta, 'Reactivar materia')

    def test_enlaza_con_el_horario_del_grado(self):
        self.assertContains(self.detalle(), reverse('horarios:grado', args=[self.p1.pk]))

    def test_consultas_constantes(self):
        with CaptureQueriesContext(connection) as pocas:
            self.detalle()
        for numero in range(4, 7):
            asignacion = asignar(self.materia, crear_grado('PRIMARIA', numero), self.actual)
            bloque(asignacion, 1)
        with CaptureQueriesContext(connection) as muchas:
            self.detalle()
        self.assertEqual(len(muchas), len(pocas))

    def test_materia_inexistente_da_404(self):
        self.assertEqual(self.client.get(reverse('materias:detalle', args=[9999])).status_code, 404)


# ---------------------------------------------------------------------------
# Baja lógica y reactivación
# ---------------------------------------------------------------------------
@PRUEBAS
class BajaTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.actual = ciclo_actual_de_prueba()
        self.cerrado = ciclo_cerrado_de_prueba()
        self.materia = crear_materia()
        self.p1, self.p2 = crear_grado('PRIMARIA', 1), crear_grado('PRIMARIA', 2)
        self.a1 = asignar(self.materia, self.p1, self.actual)
        self.a2 = asignar(self.materia, self.p2, self.actual)
        self.vieja = asignar(self.materia, self.p1, self.cerrado)
        bloque(self.a1)

    def baja(self, datos=None, **extra):
        return self.client.post(reverse('materias:baja', args=[self.materia.pk]), datos or {}, **extra)

    def test_da_de_baja_vuelve_al_listado_y_confirma(self):
        respuesta = self.baja(follow=True)
        self.assertRedirects(respuesta, reverse('materias:lista'))
        self.assertContains(respuesta, 'La materia Matemáticas fue dada de baja')
        self.materia.refresh_from_db()
        self.assertFalse(self.materia.activa)

    def test_no_borra_nada_y_deja_las_asignaciones_si_no_se_pide(self):
        self.baja()
        self.assertTrue(Materia.objects.filter(pk=self.materia.pk).exists())
        self.assertEqual(MateriaGrado.objects.filter(activa=True).count(), 3)
        self.assertEqual(HorarioMateria.objects.count(), 1)

    def test_puede_quitarla_tambien_de_los_grados_del_ciclo_actual(self):
        respuesta = self.baja({'quitar_del_ciclo': 'on'}, follow=True)
        self.assertContains(respuesta, 'También se quitó de 2 grados del ciclo actual')
        self.assertEqual(MateriaGrado.objects.filter(ciclo=self.actual, activa=True).count(), 0)
        self.vieja.refresh_from_db()
        self.assertTrue(self.vieja.activa)                               # el historial de ciclos cerrados no se toca
        self.assertEqual(HorarioMateria.objects.count(), 1)              # sus horarios se conservan

    def test_la_baja_deja_de_ofrecerla_al_asignar(self):
        self.baja()
        self.assertNotIn(self.materia, list(materias_por_asignar(crear_grado('PRIMARIA', 5), self.actual)))

    def test_dar_de_baja_dos_veces_es_inofensivo(self):
        self.baja()
        self.assertContains(self.baja(follow=True), 'ya estaba dada de baja')

    def test_reactivar_no_devuelve_las_asignaciones(self):
        self.baja({'quitar_del_ciclo': 'on'})
        respuesta = self.client.post(reverse('materias:reactivar', args=[self.materia.pk]), follow=True)
        self.assertRedirects(respuesta, reverse('materias:lista'))
        self.assertContains(respuesta, 'fue reactivada')
        self.materia.refresh_from_db()
        self.assertTrue(self.materia.activa)
        self.assertEqual(MateriaGrado.objects.filter(ciclo=self.actual, activa=True).count(), 0)

    def test_reactivar_una_activa_no_cambia_nada(self):
        respuesta = self.client.post(reverse('materias:reactivar', args=[self.materia.pk]), follow=True)
        self.assertNotContains(respuesta, 'fue reactivada')

    def test_materia_inexistente_da_404(self):
        self.assertEqual(self.client.post(reverse('materias:baja', args=[9999])).status_code, 404)


# ---------------------------------------------------------------------------
# Asignar materias a grados
# ---------------------------------------------------------------------------
@PRUEBAS
class AsignarTests(BaseTestCase):
    url = property(lambda self: reverse('materias:asignar'))

    def setUp(self):
        super().setUp()
        self.actual = ciclo_actual_de_prueba()
        self.cerrado = ciclo_cerrado_de_prueba()
        self.mat, self.esp = crear_materia('MAT', 'Matemáticas'), crear_materia('ESP', 'Español')
        self.p1, self.p2 = crear_grado('PRIMARIA', 1), crear_grado('PRIMARIA', 2)

    def post(self, ciclo=None, materias=(), grados=(), **extra):
        datos = {'ciclo': (ciclo or self.actual).pk, 'materia': [m.pk for m in materias], 'grado': [g.pk for g in grados]}
        datos.update(extra)
        return self.client.post(self.url, datos)

    def test_una_materia_a_varios_grados(self):
        respuesta = self.post(materias=[self.mat], grados=[self.p1, self.p2], next=self.mat.get_absolute_url())
        self.assertRedirects(respuesta, self.mat.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(MateriaGrado.objects.filter(ciclo=self.actual, materia=self.mat, activa=True).count(), 2)

    def test_varias_materias_a_un_grado(self):
        self.post(materias=[self.mat, self.esp], grados=[self.p1])
        self.assertEqual(MateriaGrado.objects.filter(ciclo=self.actual, grado=self.p1, activa=True).count(), 2)

    def test_crea_todas_las_combinaciones_y_confirma(self):
        self.post(materias=[self.mat, self.esp], grados=[self.p1, self.p2])
        self.assertEqual(MateriaGrado.objects.count(), 4)
        mensajes = [str(m) for m in self.client.get(reverse('materias:lista')).context['messages']]
        self.assertIn('Se agregaron 4 asignaciones de materia a grados en el ciclo 2026-2027.', mensajes)

    def test_no_duplica_lo_que_ya_estaba(self):
        asignar(self.mat, self.p1, self.actual)
        self.post(materias=[self.mat], grados=[self.p1, self.p2])
        self.assertEqual(MateriaGrado.objects.count(), 2)

    def test_reactiva_una_asignacion_quitada(self):
        quitada = asignar(self.mat, self.p1, self.actual, activa=False)
        self.post(materias=[self.mat], grados=[self.p1])
        quitada.refresh_from_db()
        self.assertTrue(quitada.activa)
        self.assertEqual(MateriaGrado.objects.count(), 1)

    def test_si_ya_estaba_todo_avisa_sin_cambiar_nada(self):
        asignar(self.mat, self.p1, self.actual)
        self.post(materias=[self.mat], grados=[self.p1])
        mensajes = [str(m) for m in self.client.get(reverse('materias:lista')).context['messages']]
        self.assertIn('Esas materias ya estaban asignadas a esos grados.', mensajes)

    def test_no_asigna_materias_ni_grados_dados_de_baja(self):
        baja = crear_materia('OLD', 'Vieja', activa=False)
        grado_baja = crear_grado('PRIMARIA', 3, activo=False)
        self.post(materias=[baja, self.mat], grados=[grado_baja, self.p1])
        self.assertEqual(list(MateriaGrado.objects.values_list('materia__clave', 'grado__numero')), [('MAT', 1)])

    def test_exige_al_menos_una_materia_y_un_grado(self):
        for materias, grados in (([], [self.p1]), ([self.mat], []), ([], [])):
            self.post(materias=materias, grados=grados)
        self.assertFalse(MateriaGrado.objects.exists())

    def test_un_ciclo_cerrado_no_se_modifica(self):
        self.post(ciclo=self.cerrado, materias=[self.mat], grados=[self.p1])
        self.assertFalse(MateriaGrado.objects.exists())

    def test_ciclo_invalido(self):
        for ciclo in ('', 'x', '9999'):
            respuesta = self.client.post(self.url, {'ciclo': ciclo, 'materia': [self.mat.pk], 'grado': [self.p1.pk]})
            self.assertIn(respuesta.status_code, (302, 404), ciclo)
        self.assertFalse(MateriaGrado.objects.exists())

    def test_ignora_valores_que_no_son_numeros(self):
        respuesta = self.client.post(self.url, {'ciclo': self.actual.pk, 'materia': [self.mat.pk, 'x', '1 OR 1=1'], 'grado': [self.p1.pk, '']})
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(MateriaGrado.objects.count(), 1)

    def test_el_next_solo_acepta_direcciones_de_este_sitio(self):
        for siguiente in ('https://malo.example/robar', '//malo.example', 'javascript:alert(1)'):
            respuesta = self.post(materias=[self.mat], grados=[self.p1], next=siguiente)
            self.assertRedirects(respuesta, reverse('materias:lista'), fetch_redirect_response=False)
        respuesta = self.post(materias=[self.mat], grados=[self.p1], next='/grados/1/?ciclo=2#materias')
        self.assertRedirects(respuesta, '/grados/1/?ciclo=2#materias', fetch_redirect_response=False)


# ---------------------------------------------------------------------------
# Quitar y volver a asignar
# ---------------------------------------------------------------------------
@PRUEBAS
class QuitarTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.actual = ciclo_actual_de_prueba()
        self.cerrado = ciclo_cerrado_de_prueba()
        self.materia = crear_materia()
        self.grado = crear_grado('PRIMARIA', 1)
        self.asignacion = asignar(self.materia, self.grado, self.actual)
        self.bloque = bloque(self.asignacion)

    def quitar(self, **extra):
        return self.client.post(reverse('materias:quitar', args=[self.asignacion.pk]), **extra)

    def test_quitar_es_logico_y_conserva_el_horario(self):
        respuesta = self.quitar(follow=True)
        self.assertRedirects(respuesta, self.materia.get_absolute_url())
        self.assertContains(respuesta, 'se quitó de 1° Primaria')
        self.asignacion.refresh_from_db()
        self.assertFalse(self.asignacion.activa)
        self.assertTrue(HorarioMateria.objects.filter(pk=self.bloque.pk).exists())

    def test_vuelve_a_donde_se_estaba(self):
        respuesta = self.client.post(reverse('materias:quitar', args=[self.asignacion.pk]), {'next': '/grados/1/#materias'})
        self.assertRedirects(respuesta, '/grados/1/#materias', fetch_redirect_response=False)

    def test_el_horario_de_una_materia_quitada_no_aparece_ni_estorba(self):
        self.quitar()
        respuesta = self.client.get(reverse('horarios:grado', args=[self.grado.pk]))
        self.assertEqual(respuesta.context['cuadricula']['filas'], [])

    def test_quitar_dos_veces_es_inofensivo(self):
        self.quitar()
        self.assertContains(self.quitar(follow=True), 'ya estaba quitada')

    def test_un_ciclo_cerrado_no_se_modifica(self):
        vieja = asignar(self.materia, self.grado, self.cerrado)
        respuesta = self.client.post(reverse('materias:quitar', args=[vieja.pk]), follow=True)
        self.assertContains(respuesta, 'está cerrado')
        vieja.refresh_from_db()
        self.assertTrue(vieja.activa)

    def test_volver_a_asignar(self):
        self.quitar()
        respuesta = self.client.post(reverse('materias:reactivar_asignacion', args=[self.asignacion.pk]), follow=True)
        self.assertContains(respuesta, 'volvió a impartirse en 1° Primaria')
        self.asignacion.refresh_from_db()
        self.assertTrue(self.asignacion.activa)

    def test_no_se_reasigna_una_materia_o_un_grado_de_baja(self):
        self.quitar()
        self.materia.activa = False
        self.materia.save()
        self.assertContains(self.client.post(reverse('materias:reactivar_asignacion', args=[self.asignacion.pk]), follow=True), 'reactívala primero')
        self.materia.activa = True
        self.materia.save()
        self.grado.activo = False
        self.grado.save()
        self.assertContains(self.client.post(reverse('materias:reactivar_asignacion', args=[self.asignacion.pk]), follow=True), 'reactívalo primero')
        self.asignacion.refresh_from_db()
        self.assertFalse(self.asignacion.activa)

    def test_asignacion_inexistente_da_404(self):
        self.assertEqual(self.client.post(reverse('materias:quitar', args=[9999])).status_code, 404)
        self.assertEqual(self.client.post(reverse('materias:reactivar_asignacion', args=[9999])).status_code, 404)


# ---------------------------------------------------------------------------
# Exportación
# ---------------------------------------------------------------------------
@PRUEBAS
class ExportarTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.actual = ciclo_actual_de_prueba()
        self.mat = crear_materia('MAT', '=Matemáticas')
        crear_materia('ESP', 'Español')
        crear_materia('OLD', 'Antigua', activa=False)
        asignar(self.mat, crear_grado('PRIMARIA', 2), self.actual)
        asignar(self.mat, crear_grado('PRIMARIA', 1), self.actual)

    def filas(self, **filtros):
        respuesta = self.client.get(reverse('materias:exportar'), filtros)
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('text/csv', respuesta['Content-Type'])
        self.assertIn('attachment; filename="materias-', respuesta['Content-Disposition'])
        contenido = respuesta.content.decode('utf-8')
        self.assertTrue(contenido.startswith('﻿'))
        return list(csv.reader(io.StringIO(contenido.lstrip('﻿'))))

    def test_exporta_las_activas_con_sus_grados_en_orden_escolar(self):
        filas = self.filas()
        self.assertEqual(filas[0][:3], ['Clave', 'Nombre', 'Estado'])
        self.assertIn('2026-2027', filas[0][3])
        self.assertEqual([f[0] for f in filas[1:]], ['MAT', 'ESP'])           # por nombre: «=Matemáticas» va antes que «Español»
        self.assertEqual(filas[1][1], "'=Matemáticas")                      # neutraliza fórmulas de Excel
        self.assertEqual(filas[1][3], '1° Primaria; 2° Primaria')

    def test_respeta_los_filtros(self):
        self.assertEqual([f[0] for f in self.filas(estado='BAJA')[1:]], ['OLD'])
        self.assertEqual([f[0] for f in self.filas(q='esp')[1:]], ['ESP'])


# ---------------------------------------------------------------------------
# Copiar el plan de un ciclo a otro
# ---------------------------------------------------------------------------
@PRUEBAS
class CopiarPlanTests(BaseTestCase):
    url = property(lambda self: reverse('materias:copiar'))

    def setUp(self):
        super().setUp()
        self.origen = ciclo_actual_de_prueba('2026-2027')
        self.destino = ciclo_proximo_de_prueba('2027-2028')
        self.mat, self.esp = crear_materia('MAT', 'Matemáticas'), crear_materia('ESP', 'Español')
        self.p1, self.p2 = crear_grado('PRIMARIA', 1), crear_grado('PRIMARIA', 2)
        self.a1 = asignar(self.mat, self.p1, self.origen)
        self.a2 = asignar(self.esp, self.p1, self.origen)
        self.a3 = asignar(self.mat, self.p2, self.origen)
        bloque(self.a1, 0, (8, 0), (9, 0))
        bloque(self.a1, 2, (8, 0), (9, 0))
        bloque(self.a2, 1, (9, 0), (10, 0))

    def parametros(self):
        return {'origen': self.origen.pk, 'destino': self.destino.pk}

    def copiar(self, horarios=True, follow=False, **extra):
        datos = {**self.parametros(), **extra}
        if horarios:
            datos['horarios'] = 'on'
        return self.client.post(self.url, datos, follow=follow)

    # --- vista previa ---------------------------------------------------------------
    def test_sin_ciclo_de_destino_avisa(self):
        self.destino.delete()
        respuesta = self.client.get(self.url)
        self.assertFalse(respuesta.context['hay_destinos'])
        self.assertContains(respuesta, 'No hay un ciclo al cual copiar')

    def test_propone_del_ciclo_con_plan_al_proximo(self):
        respuesta = self.client.get(self.url)
        self.assertEqual((respuesta.context['origen'], respuesta.context['destino']), (self.origen, self.destino))
        self.assertIsNotNone(respuesta.context['plan'])

    def test_la_vista_previa_cuenta_materias_bloques_y_existentes(self):
        asignar(self.esp, self.p1, self.destino)            # esa ya estaba en el destino
        respuesta = self.client.get(self.url, self.parametros())
        plan = {str(f['grado']): f for f in respuesta.context['plan']}
        self.assertEqual((plan['1° Primaria']['materias'], plan['1° Primaria']['bloques'], plan['1° Primaria']['ya_existen']), (1, 2, 1))
        self.assertEqual((plan['2° Primaria']['materias'], plan['2° Primaria']['bloques']), (1, 0))
        self.assertEqual((respuesta.context['total_materias'], respuesta.context['total_bloques'], respuesta.context['total_existentes']), (2, 2, 1))

    def test_no_se_copian_materias_quitadas_ni_de_baja_ni_de_grados_de_baja(self):
        self.a3.activa = False
        self.a3.save()
        self.esp.activa = False
        self.esp.save()
        respuesta = self.client.get(self.url, self.parametros())
        self.assertEqual([(str(f['grado']), f['materias']) for f in respuesta.context['plan']], [('1° Primaria', 1)])
        self.p1.activo = False
        self.p1.save()
        self.assertEqual(self.client.get(self.url, self.parametros()).context['plan'], [])

    def test_origen_igual_a_destino_o_destino_cerrado_no_es_valido(self):
        respuesta = self.client.get(self.url, {'origen': self.origen.pk, 'destino': self.origen.pk})
        self.assertIn('destino', respuesta.context['form'].errors)
        cerrado = ciclo_cerrado_de_prueba()
        respuesta = self.client.get(self.url, {'origen': self.origen.pk, 'destino': cerrado.pk})
        self.assertIn('destino', respuesta.context['form'].errors)
        self.assertIsNone(respuesta.context['plan'])

    def test_origen_sin_materias(self):
        vacio = ciclo_cerrado_de_prueba()
        respuesta = self.client.get(self.url, {'origen': vacio.pk, 'destino': self.destino.pk})
        self.assertEqual(respuesta.context['plan'], [])
        self.assertContains(respuesta, 'no tiene materias asignadas')

    def test_consultas_constantes(self):
        with CaptureQueriesContext(connection) as pocas:
            self.client.get(self.url, self.parametros())
        for numero in range(3, 8):
            asignacion = asignar(self.mat, crear_grado('PRIMARIA', numero), self.origen)
            bloque(asignacion)
        with CaptureQueriesContext(connection) as muchas:
            self.client.get(self.url, self.parametros())
        self.assertEqual(len(muchas), len(pocas))

    # --- confirmación ---------------------------------------------------------------
    def test_copia_las_materias_con_sus_horarios(self):
        respuesta = self.copiar()
        self.assertRedirects(respuesta, f"{reverse('horarios:lista')}?ciclo={self.destino.pk}", fetch_redirect_response=False)
        copiadas = MateriaGrado.objects.filter(ciclo=self.destino)
        self.assertEqual(copiadas.count(), 3)
        self.assertTrue(all(m.activa for m in copiadas))
        self.assertEqual(HorarioMateria.objects.filter(materia_grado__ciclo=self.destino).count(), 3)
        copia = copiadas.get(materia=self.mat, grado=self.p1)
        self.assertEqual(sorted(copia.horarios.values_list('dia_semana', 'hora_inicio', 'hora_fin')), [(0, time(8, 0), time(9, 0)), (2, time(8, 0), time(9, 0))])

    def test_confirma_con_un_mensaje(self):
        respuesta = self.copiar(follow=True)
        self.assertContains(respuesta, 'Se copiaron 3 materias a los grados del ciclo 2027-2028 y 3 bloques de horario')

    def test_se_pueden_copiar_solo_las_materias(self):
        self.copiar(horarios=False)
        self.assertEqual(MateriaGrado.objects.filter(ciclo=self.destino).count(), 3)
        self.assertFalse(HorarioMateria.objects.filter(materia_grado__ciclo=self.destino).exists())

    def test_no_toca_el_ciclo_de_origen(self):
        self.copiar()
        self.assertEqual(MateriaGrado.objects.filter(ciclo=self.origen).count(), 3)
        self.assertEqual(HorarioMateria.objects.filter(materia_grado__ciclo=self.origen).count(), 3)

    def test_no_duplica_ni_pisa_lo_que_el_destino_ya_tiene(self):
        existente = asignar(self.esp, self.p1, self.destino)
        bloque(existente, 4, (12, 0), (13, 0))
        self.copiar()
        self.assertEqual(MateriaGrado.objects.filter(ciclo=self.destino).count(), 3)
        self.assertEqual(list(existente.horarios.values_list('dia_semana', flat=True)), [4])   # su horario propio se respeta

    def test_repetirlo_no_duplica_nada(self):
        self.copiar()
        total = (MateriaGrado.objects.count(), HorarioMateria.objects.count())
        respuesta = self.copiar(follow=True)
        self.assertEqual((MateriaGrado.objects.count(), HorarioMateria.objects.count()), total)
        self.assertContains(respuesta, 'No había nada nuevo que copiar')

    def test_copiar_horarios_pide_su_permiso(self):
        self.con_permisos('view_materia', 'add_materiagrado')
        respuesta = self.copiar(follow=True)
        self.assertContains(respuesta, 'No tienes permiso para copiar horarios')
        self.assertFalse(MateriaGrado.objects.filter(ciclo=self.destino).exists())
        self.copiar(horarios=False)                            # solo materias sí puede
        self.assertEqual(MateriaGrado.objects.filter(ciclo=self.destino).count(), 3)

    def test_sin_permiso_de_ver_horarios_vuelve_al_listado_de_materias(self):
        self.con_permisos('view_materia', 'add_materiagrado')
        respuesta = self.copiar(horarios=False)
        self.assertRedirects(respuesta, reverse('materias:lista'), fetch_redirect_response=False)

    def test_ciclos_invalidos_no_hacen_nada(self):
        cerrado = ciclo_cerrado_de_prueba()
        for parametros in ({'origen': self.origen.pk, 'destino': self.origen.pk}, {'origen': '', 'destino': ''},
                           {'origen': self.origen.pk, 'destino': cerrado.pk}):
            respuesta = self.client.post(self.url, parametros)
            self.assertRedirects(respuesta, self.url, fetch_redirect_response=False)
        self.assertFalse(MateriaGrado.objects.filter(ciclo=self.destino).exists())

    def test_un_error_al_guardar_no_deja_nada_a_medias(self):
        with patch('django.db.models.query.QuerySet.bulk_create', side_effect=IntegrityError('duplicado')):
            respuesta = self.copiar(follow=True)
        self.assertContains(respuesta, 'otra persona cambió el plan')
        self.assertFalse(MateriaGrado.objects.filter(ciclo=self.destino).exists())
