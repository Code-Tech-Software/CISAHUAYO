import csv
import io
from datetime import timedelta
from unittest.mock import patch

from django.db import IntegrityError, connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from Alumnos.models import Alumno, CicloEscolar, Inscripcion
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    ciclo_cerrado_de_prueba,
    ciclo_proximo_de_prueba,
    crear_alumno,
    crear_grado,
    hoy,
    inscribir,
)


def lista(ciclo=None):
    """URL del listado, con el ciclo indicado."""
    return f"{reverse('inscripciones:lista')}?ciclo={ciclo.pk if ciclo else ''}"


# ---------------------------------------------------------------------------
# Permisos
# ---------------------------------------------------------------------------
@PRUEBAS
class PermisosTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.grado = crear_grado()
        self.inscripcion = inscribir(crear_alumno(), self.ciclo, self.grado)

    def paginas(self):
        pk = self.inscripcion.pk
        return (('lista', []), ('crear', []), ('exportar', []), ('promocion', []), ('editar', [pk]))

    def test_anonimo_es_enviado_al_login(self):
        self.client.logout()
        for nombre, args in self.paginas():
            respuesta = self.client.get(reverse(f'inscripciones:{nombre}', args=args))
            self.assertEqual(respuesta.status_code, 302, nombre)
            self.assertIn('/admin/login/', respuesta['Location'])

    def test_sin_permisos_recibe_403(self):
        self.client.force_login(self.sin_permisos)
        for nombre, args in self.paginas():
            self.assertEqual(self.client.get(reverse(f'inscripciones:{nombre}', args=args)).status_code, 403, nombre)
        for nombre in ('baja', 'reactivar'):
            self.assertEqual(self.client.post(reverse(f'inscripciones:{nombre}', args=[self.inscripcion.pk])).status_code, 403, nombre)
        self.assertEqual(self.client.post(reverse('inscripciones:promocion')).status_code, 403)
        self.inscripcion.refresh_from_db()
        self.assertTrue(self.inscripcion.activa)

    def test_las_acciones_solo_aceptan_post(self):
        for nombre in ('baja', 'reactivar'):
            self.assertEqual(self.client.get(reverse(f'inscripciones:{nombre}', args=[self.inscripcion.pk])).status_code, 405, nombre)

    def test_cada_accion_pide_su_permiso(self):
        pk = self.inscripcion.pk
        self.con_permisos('view_inscripcion')
        self.assertEqual(self.client.get(reverse('inscripciones:lista')).status_code, 200)
        self.assertEqual(self.client.get(reverse('inscripciones:exportar')).status_code, 200)
        for nombre, args in (('crear', []), ('promocion', []), ('editar', [pk])):
            self.assertEqual(self.client.get(reverse(f'inscripciones:{nombre}', args=args)).status_code, 403, nombre)
        self.assertEqual(self.client.post(reverse('inscripciones:baja', args=[pk])).status_code, 403)

        self.con_permisos('view_inscripcion', 'add_inscripcion')
        self.assertEqual(self.client.get(reverse('inscripciones:crear')).status_code, 200)
        self.assertEqual(self.client.get(reverse('inscripciones:promocion')).status_code, 200)

        self.con_permisos('view_inscripcion', 'change_inscripcion')
        self.assertEqual(self.client.get(reverse('inscripciones:editar', args=[pk])).status_code, 200)
        self.assertEqual(self.client.post(reverse('inscripciones:baja', args=[pk])).status_code, 403)

        self.con_permisos('view_inscripcion', 'delete_inscripcion')
        self.assertEqual(self.client.post(reverse('inscripciones:baja', args=[pk])).status_code, 302)


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------
@PRUEBAS
class ListaTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.actual = ciclo_actual_de_prueba('2026-2027')
        self.viejo = ciclo_cerrado_de_prueba('2025-2026')
        self.prepa = crear_grado('PREPARATORIA', 1)
        self.primero = crear_grado('PRIMARIA', 1)
        self.segundo = crear_grado('PRIMARIA', 2)
        self.zamora = crear_alumno(nombre='Ana', apellido_paterno='Zamora', referencia='A100')
        self.aranda = crear_alumno(nombre='Beto', apellido_paterno='Aranda', referencia='B200')
        self.medina = crear_alumno(nombre='Cora', apellido_paterno='Medina', referencia='C300')
        inscribir(self.zamora, self.actual, self.primero)
        inscribir(self.aranda, self.actual, self.prepa)
        inscribir(self.medina, self.actual, self.segundo, activa=False)
        inscribir(self.zamora, self.viejo, self.primero)

    def pedir(self, url=None, **filtros):
        respuesta = self.client.get(url or reverse('inscripciones:lista'), filtros)
        self.assertEqual(respuesta.status_code, 200)
        return respuesta

    def apellidos(self, **filtros):
        return [i.alumno.apellido_paterno for i in self.pedir(**filtros).context['pagina']]

    def test_por_defecto_muestra_las_inscripciones_activas_del_ciclo_actual(self):
        self.assertEqual(self.apellidos(), ['Aranda', 'Zamora'])

    def test_con_ciclo_vacio_muestra_todos_los_ciclos(self):
        self.assertEqual(self.apellidos(ciclo=''), ['Aranda', 'Zamora', 'Zamora'])

    def test_elige_otro_ciclo(self):
        self.assertEqual(self.apellidos(ciclo=self.viejo.pk), ['Zamora'])

    def test_las_bajas_se_ven_en_su_filtro(self):
        respuesta = self.pedir(estado='BAJA')
        self.assertEqual([i.alumno.apellido_paterno for i in respuesta.context['pagina']], ['Medina'])
        self.assertTrue(respuesta.context['viendo_bajas'])
        self.assertContains(respuesta, 'Reactivar')

    def test_conteos_de_las_pestanas_respetan_el_resto_de_filtros(self):
        conteos = self.pedir().context['conteos']
        self.assertEqual(conteos, {'activas': 2, 'bajas': 1})
        self.assertEqual(self.pedir(ciclo='').context['conteos'], {'activas': 3, 'bajas': 1})
        self.assertEqual(self.pedir(q='zamora').context['conteos'], {'activas': 1, 'bajas': 0})

    def test_busca_por_nombre_referencia_y_curp(self):
        self.assertEqual(self.apellidos(q='ana zamora'), ['Zamora'])
        self.assertEqual(self.apellidos(q='B200'), ['Aranda'])
        self.assertEqual(self.apellidos(q=self.aranda.curp), ['Aranda'])
        self.assertEqual(self.apellidos(q='nadie'), [])

    def test_filtra_por_grado(self):
        self.assertEqual(self.apellidos(grado=self.prepa.pk), ['Aranda'])

    def test_ordena(self):
        self.assertEqual(self.apellidos(orden='-alumno'), ['Zamora', 'Aranda'])
        self.assertEqual(self.apellidos(orden='grado'), ['Zamora', 'Aranda'])          # primaria antes que preparatoria
        self.assertEqual(self.apellidos(ciclo='', orden='-reciente')[0], 'Zamora')
        self.assertEqual(len(self.apellidos(orden='antigua')), 2)

    def test_orden_por_grado_sigue_el_orden_escolar_y_no_el_alfabetico(self):
        # alfabéticamente PREPARATORIA < PRIMARIA, pero escolarmente va después
        respuesta = self.pedir(orden='grado')
        self.assertEqual([str(i.grado) for i in respuesta.context['pagina']], ['1° Primaria', '1° Preparatoria'])

    def test_filtros_invalidos_se_ignoran(self):
        # un ciclo inválido equivale a «todos los ciclos»; el resto de valores inválidos simplemente no filtran
        self.assertEqual(self.apellidos(estado='XX', grado='999', orden='zzz', ciclo='abc'), ['Aranda', 'Zamora', 'Zamora'])

    def test_resumen_del_ciclo(self):
        pendiente = crear_alumno()                       # activo sin inscripción
        crear_alumno(estatus='BAJA')                     # de baja: no cuenta como pendiente
        resumen = self.pedir().context['resumen']
        self.assertEqual(resumen['ciclo'], self.actual)
        self.assertEqual(resumen['inscritos'], 2)
        self.assertEqual([(n['nombre'], n['total']) for n in resumen['niveles']], [('Primaria', 1), ('Preparatoria', 1)])
        # Cora tiene una inscripción dada de baja: sigue siendo «ya inscrita» para esta cuenta
        self.assertEqual(resumen['sin_inscribir'], 1)
        self.assertEqual(pendiente.estatus, 'ACTIVO')

    def test_sin_ciclo_no_hay_resumen(self):
        self.assertIsNone(self.pedir(ciclo='').context['resumen'])

    def test_el_ciclo_actual_por_defecto_no_cuenta_como_filtro_aplicado(self):
        self.assertEqual(self.pedir().context['filtros_activos'], {})
        self.assertEqual(self.pedir(ciclo=self.actual.pk).context['filtros_activos'], {})      # elegirlo a mano, igual
        self.assertEqual(set(self.pedir(ciclo=self.viejo.pk, q='ana').context['filtros_activos']), {'ciclo', 'q'})
        self.assertEqual(set(self.pedir(ciclo='').context['filtros_activos']), set())

    def test_sin_ciclo_actual_muestra_todo(self):
        CicloEscolar.objects.update(activo=False)
        self.assertEqual(self.apellidos(), ['Aranda', 'Zamora', 'Zamora'])

    def test_pagina_y_tamano(self):
        for i in range(25):
            inscribir(crear_alumno(), self.actual, self.primero)
        respuesta = self.pedir()
        self.assertEqual(respuesta.context['pagina'].paginator.count, 27)
        self.assertEqual(len(respuesta.context['pagina']), 20)
        self.assertEqual(len(self.pedir(page=2).context['pagina']), 7)
        self.assertEqual(len(self.pedir(por_pagina=10).context['pagina']), 10)
        self.assertEqual(self.pedir(por_pagina=7).context['por_pagina'], 20)       # tamaño no permitido

    def test_la_paginacion_conserva_los_filtros(self):
        for i in range(25):
            inscribir(crear_alumno(nombre='Relleno'), self.actual, self.primero)
        self.assertContains(self.pedir(q='relleno', por_pagina=10), 'q=relleno')

    def test_consultas_constantes(self):
        with CaptureQueriesContext(connection) as pocas:
            self.pedir(por_pagina=10)
        for i in range(25):
            inscribir(crear_alumno(), self.actual, self.primero)
        with CaptureQueriesContext(connection) as muchas:
            self.pedir(por_pagina=50)
        self.assertLessEqual(len(muchas), len(pocas))

    def test_estados_vacios(self):
        Inscripcion.objects.all().delete()
        self.assertContains(self.pedir(), 'Aún no hay inscripciones')
        self.assertContains(self.pedir(estado='BAJA'), 'No hay inscripciones dadas de baja')
        self.assertContains(self.pedir(q='nadie'), 'No encontramos inscripciones')


# ---------------------------------------------------------------------------
# Alta
# ---------------------------------------------------------------------------
@PRUEBAS
class CrearTests(BaseTestCase):
    url = property(lambda self: reverse('inscripciones:crear'))

    def setUp(self):
        super().setUp()
        self.actual = ciclo_actual_de_prueba()
        self.proximo = ciclo_proximo_de_prueba()
        self.grado = crear_grado('PRIMARIA', 3)
        self.alumno = crear_alumno()

    def datos(self, **cambios):
        datos = {
            'alumno': self.alumno.pk, 'ciclo': self.actual.pk, 'grado': self.grado.pk,
            'fecha_inscripcion': hoy().isoformat(),
        }
        datos.update(cambios)
        return datos

    def test_el_formulario_propone_el_ciclo_actual_y_la_fecha_de_hoy(self):
        respuesta = self.client.get(self.url)
        form = respuesta.context['form']
        self.assertEqual(form['ciclo'].initial, self.actual)
        self.assertEqual(form['fecha_inscripcion'].initial, hoy())
        self.assertIsNone(respuesta.context['alumno'])

    def test_trae_datos_de_la_url(self):
        respuesta = self.client.get(self.url, {'alumno': self.alumno.pk, 'ciclo': self.proximo.pk, 'grado': self.grado.pk})
        form = respuesta.context['form']
        self.assertEqual(respuesta.context['alumno'], self.alumno)
        self.assertEqual(str(form['ciclo'].value()), str(self.proximo.pk))
        self.assertEqual(str(form['grado'].value()), str(self.grado.pk))
        self.assertContains(respuesta, str(self.alumno))

    def test_ignora_datos_de_la_url_que_no_son_numeros(self):
        respuesta = self.client.get(self.url, {'alumno': 'x', 'ciclo': '1 OR 1=1', 'grado': ''})
        self.assertEqual(respuesta.status_code, 200)
        self.assertIsNone(respuesta.context['alumno'])

    def test_inscribe_y_vuelve_al_listado_del_ciclo_con_mensaje(self):
        respuesta = self.client.post(self.url, self.datos(), follow=True)
        self.assertRedirects(respuesta, lista(self.actual))
        self.assertContains(respuesta, f'{self.alumno} fue inscrito en 3° Primaria (2026-2027)')
        inscripcion = Inscripcion.objects.get()
        self.assertEqual((inscripcion.alumno, inscripcion.ciclo, inscripcion.grado, inscripcion.activa), (self.alumno, self.actual, self.grado, True))
        self.assertContains(respuesta, self.alumno.apellido_paterno)       # ya se ve en el listado

    def test_inscribir_en_un_ciclo_proximo_lleva_a_ese_ciclo(self):
        respuesta = self.client.post(self.url, self.datos(ciclo=self.proximo.pk))
        self.assertRedirects(respuesta, lista(self.proximo), fetch_redirect_response=False)

    def test_exige_alumno_ciclo_y_grado(self):
        respuesta = self.client.post(self.url, {})
        self.assertEqual(set(respuesta.context['form'].errors), {'alumno', 'ciclo', 'grado', 'fecha_inscripcion'})
        self.assertContains(respuesta, 'Busca y elige un estudiante')
        self.assertFalse(Inscripcion.objects.exists())

    def test_alumno_inexistente(self):
        respuesta = self.client.post(self.url, self.datos(alumno=9999))
        self.assertIn('alumno', respuesta.context['form'].errors)

    def test_no_inscribe_a_alumnos_de_baja_ni_egresados(self):
        for estatus, texto in (('BAJA', 'dado de baja'), ('EGRESADO', 'egresado')):
            alumno = crear_alumno(estatus=estatus)
            respuesta = self.client.post(self.url, self.datos(alumno=alumno.pk))
            self.assertEqual(respuesta.status_code, 200, estatus)
            self.assertContains(respuesta, texto)
        self.assertFalse(Inscripcion.objects.exists())

    def test_si_se_puede_inscribir_a_un_alumno_suspendido(self):
        alumno = crear_alumno(estatus='SUSPENDIDO')
        self.assertEqual(self.client.post(self.url, self.datos(alumno=alumno.pk)).status_code, 302)

    def test_no_repite_la_inscripcion_activa(self):
        inscribir(self.alumno, self.actual, crear_grado('PRIMARIA', 1))
        respuesta = self.client.post(self.url, self.datos())
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'ya está inscrito en el ciclo 2026-2027 (1° Primaria)')
        self.assertEqual(Inscripcion.objects.count(), 1)
        self.assertEqual(len(respuesta.context['form'].errors), 1)       # un solo aviso, no dos

    def test_una_inscripcion_dada_de_baja_remite_a_reactivarla(self):
        inscribir(self.alumno, self.actual, self.grado, activa=False)
        respuesta = self.client.post(self.url, self.datos())
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'se dio de baja')
        self.assertContains(respuesta, 'Ir a reactivarla')
        self.assertEqual(Inscripcion.objects.count(), 1)

    def test_el_mismo_alumno_puede_inscribirse_en_otro_ciclo(self):
        inscribir(self.alumno, self.actual, crear_grado('PRIMARIA', 2))
        self.assertEqual(self.client.post(self.url, self.datos(ciclo=self.proximo.pk)).status_code, 302)
        self.assertEqual(Inscripcion.objects.filter(alumno=self.alumno).count(), 2)

    def test_no_ofrece_ni_acepta_grados_dados_de_baja(self):
        baja = crear_grado('PRIMARIA', 4, activo=False)
        respuesta = self.client.post(self.url, self.datos(grado=baja.pk))
        self.assertIn('grado', respuesta.context['form'].errors)
        self.assertNotIn(baja, self.client.get(self.url).context['form'].fields['grado'].queryset)

    def test_no_acepta_fechas_futuras(self):
        respuesta = self.client.post(self.url, self.datos(fecha_inscripcion=(hoy() + timedelta(days=2)).isoformat()))
        self.assertContains(respuesta, 'no puede ser futura')

    def test_conserva_lo_capturado_si_hay_errores(self):
        respuesta = self.client.post(self.url, self.datos(grado=''))
        self.assertEqual(respuesta.context['alumno'], self.alumno)       # el alumno sigue elegido
        self.assertContains(respuesta, 'data-picker-chosen')


# ---------------------------------------------------------------------------
# Edición
# ---------------------------------------------------------------------------
@PRUEBAS
class EditarTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.grado = crear_grado('PRIMARIA', 3)
        self.otro = crear_grado('PRIMARIA', 4)
        self.alumno = crear_alumno()
        self.inscripcion = inscribir(self.alumno, self.ciclo, self.grado)
        self.url = reverse('inscripciones:editar', args=[self.inscripcion.pk])

    def test_solo_se_editan_el_grado_y_la_fecha(self):
        respuesta = self.client.get(self.url)
        self.assertEqual(sorted(respuesta.context['form'].fields), ['fecha_inscripcion', 'grado'])
        self.assertContains(respuesta, str(self.alumno))
        self.assertContains(respuesta, '2026-2027')

    def test_cambia_de_grado_y_vuelve_al_listado_del_ciclo(self):
        respuesta = self.client.post(self.url, {'grado': self.otro.pk, 'fecha_inscripcion': hoy().isoformat()}, follow=True)
        self.assertRedirects(respuesta, lista(self.ciclo))
        self.assertContains(respuesta, 'se actualizó: 4° Primaria')
        self.inscripcion.refresh_from_db()
        self.assertEqual(self.inscripcion.grado, self.otro)

    def test_el_alumno_y_el_ciclo_no_se_pueden_cambiar_por_post(self):
        otro_ciclo = ciclo_proximo_de_prueba()
        otro_alumno = crear_alumno()
        self.client.post(self.url, {
            'grado': self.otro.pk, 'fecha_inscripcion': hoy().isoformat(), 'alumno': otro_alumno.pk, 'ciclo': otro_ciclo.pk,
        })
        self.inscripcion.refresh_from_db()
        self.assertEqual((self.inscripcion.alumno, self.inscripcion.ciclo), (self.alumno, self.ciclo))

    def test_conserva_su_grado_aunque_ya_este_dado_de_baja(self):
        self.grado.activo = False
        self.grado.save()
        form = self.client.get(self.url).context['form']
        self.assertIn(self.grado, form.fields['grado'].queryset)
        respuesta = self.client.post(self.url, {'grado': self.grado.pk, 'fecha_inscripcion': hoy().isoformat()})
        self.assertEqual(respuesta.status_code, 302)

    def test_no_se_puede_cambiar_a_un_grado_dado_de_baja(self):
        self.otro.activo = False
        self.otro.save()
        respuesta = self.client.post(self.url, {'grado': self.otro.pk, 'fecha_inscripcion': hoy().isoformat()})
        self.assertIn('grado', respuesta.context['form'].errors)

    def test_no_acepta_fechas_futuras(self):
        respuesta = self.client.post(self.url, {'grado': self.grado.pk, 'fecha_inscripcion': (hoy() + timedelta(days=1)).isoformat()})
        self.assertContains(respuesta, 'no puede ser futura')

    def test_se_puede_editar_aunque_el_alumno_ya_este_de_baja(self):
        self.alumno.estatus = 'BAJA'
        self.alumno.save()
        respuesta = self.client.post(self.url, {'grado': self.otro.pk, 'fecha_inscripcion': hoy().isoformat()})
        self.assertEqual(respuesta.status_code, 302)

    def test_inscripcion_inexistente_da_404(self):
        self.assertEqual(self.client.get(reverse('inscripciones:editar', args=[9999])).status_code, 404)


# ---------------------------------------------------------------------------
# Baja lógica y reactivación
# ---------------------------------------------------------------------------
@PRUEBAS
class BajaTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.grado = crear_grado()
        self.alumno = crear_alumno()
        self.inscripcion = inscribir(self.alumno, self.ciclo, self.grado)

    def baja(self, **extra):
        return self.client.post(reverse('inscripciones:baja', args=[self.inscripcion.pk]), **extra)

    def test_da_de_baja_vuelve_al_listado_y_confirma(self):
        respuesta = self.baja(follow=True)
        self.assertRedirects(respuesta, lista(self.ciclo))
        self.assertContains(respuesta, 'se dio de baja')
        self.inscripcion.refresh_from_db()
        self.assertFalse(self.inscripcion.activa)

    def test_no_borra_nada_ni_toca_al_alumno(self):
        self.baja()
        self.assertTrue(Inscripcion.objects.filter(pk=self.inscripcion.pk).exists())
        self.alumno.refresh_from_db()
        self.assertEqual(self.alumno.estatus, 'ACTIVO')

    def test_sale_del_listado_normal_y_aparece_en_bajas(self):
        self.baja()
        self.assertEqual(self.client.get(reverse('inscripciones:lista')).context['pagina'].paginator.count, 0)
        pagina = self.client.get(reverse('inscripciones:lista'), {'estado': 'BAJA'}).context['pagina']
        self.assertEqual([i.pk for i in pagina], [self.inscripcion.pk])

    def test_el_alumno_deja_de_tener_grado_actual(self):
        self.baja()
        respuesta = self.client.get(reverse('alumnos:lista'), {'situacion': 'sin_inscripcion'})
        self.assertIn(self.alumno, list(respuesta.context['pagina']))

    def test_dar_de_baja_dos_veces_es_inofensivo(self):
        self.baja()
        self.assertContains(self.baja(follow=True), 'ya estaba dada de baja')

    def test_reactivar(self):
        self.baja()
        respuesta = self.client.post(reverse('inscripciones:reactivar', args=[self.inscripcion.pk]), follow=True)
        self.assertRedirects(respuesta, lista(self.ciclo))
        self.assertContains(respuesta, 'fue reactivada')
        self.inscripcion.refresh_from_db()
        self.assertTrue(self.inscripcion.activa)

    def test_no_se_reactiva_la_inscripcion_de_un_alumno_de_baja_o_egresado(self):
        self.baja()
        for estatus in ('BAJA', 'EGRESADO'):
            self.alumno.estatus = estatus
            self.alumno.save()
            respuesta = self.client.post(reverse('inscripciones:reactivar', args=[self.inscripcion.pk]), follow=True)
            self.assertContains(respuesta, 'No se pudo reactivar')
            self.inscripcion.refresh_from_db()
            self.assertFalse(self.inscripcion.activa, estatus)

    def test_reactivar_una_activa_no_cambia_nada(self):
        respuesta = self.client.post(reverse('inscripciones:reactivar', args=[self.inscripcion.pk]), follow=True)
        self.assertContains(respuesta, 'ya está activa')

    def test_inscripcion_inexistente_da_404(self):
        self.assertEqual(self.client.post(reverse('inscripciones:baja', args=[9999])).status_code, 404)
        self.assertEqual(self.client.post(reverse('inscripciones:reactivar', args=[9999])).status_code, 404)


# ---------------------------------------------------------------------------
# Exportación
# ---------------------------------------------------------------------------
@PRUEBAS
class ExportarTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.actual = ciclo_actual_de_prueba()
        self.viejo = ciclo_cerrado_de_prueba()
        self.grado = crear_grado('PRIMARIA', 2)
        inscribir(crear_alumno(nombre='=Ana', apellido_paterno='Zamora', referencia='1'), self.actual, self.grado)
        inscribir(crear_alumno(nombre='Beto', apellido_paterno='Aranda', referencia='2'), self.actual, self.grado, activa=False)
        inscribir(crear_alumno(nombre='Vieja', apellido_paterno='Gomez', referencia='3'), self.viejo, self.grado)

    def filas(self, **filtros):
        respuesta = self.client.get(reverse('inscripciones:exportar'), filtros)
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('text/csv', respuesta['Content-Type'])
        self.assertIn('attachment; filename="inscripciones-', respuesta['Content-Disposition'])
        contenido = respuesta.content.decode('utf-8')
        self.assertTrue(contenido.startswith('﻿'))
        return list(csv.reader(io.StringIO(contenido.lstrip('﻿'))))

    def test_exporta_lo_mismo_que_el_listado(self):
        filas = self.filas()
        self.assertEqual(filas[0][:2], ['Referencia', 'Apellido paterno'])
        self.assertEqual(len(filas), 2)                               # solo la activa del ciclo actual
        self.assertEqual(filas[1][3], "'=Ana")                        # neutraliza fórmulas de Excel
        self.assertEqual(filas[1][4:], [self.actual.nombre, '2° Primaria', f'{hoy():%d/%m/%Y}', 'Activa'])

    def test_respeta_los_filtros(self):
        self.assertEqual([f[3] for f in self.filas(estado='BAJA')[1:]], ['Beto'])
        self.assertEqual(len(self.filas(ciclo='')), 3)
        self.assertEqual([f[3] for f in self.filas(ciclo=self.viejo.pk)[1:]], ['Vieja'])


# ---------------------------------------------------------------------------
# Reinscripción en bloque
# ---------------------------------------------------------------------------
@PRUEBAS
class PromocionTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.origen = ciclo_actual_de_prueba('2026-2027')
        self.destino = ciclo_proximo_de_prueba('2027-2028')
        self.g1 = crear_grado('PRIMARIA', 1)
        self.g2 = crear_grado('PRIMARIA', 2)
        self.g6 = crear_grado('PRIMARIA', 6)
        self.s1 = crear_grado('SECUNDARIA', 1)
        self.url = reverse('inscripciones:promocion')

    def preparar(self):
        """Dos de 1.° (uno ya inscrito en el destino), uno de 2.° suspendido, uno de 6.° y uno con inscripción de baja."""
        self.a = crear_alumno(nombre='A')
        self.b = crear_alumno(nombre='B')
        self.suspendido = crear_alumno(nombre='S', estatus='SUSPENDIDO')
        self.sexto = crear_alumno(nombre='F')
        self.con_baja = crear_alumno(nombre='X')
        inscribir(self.a, self.origen, self.g1)
        inscribir(self.b, self.origen, self.g1)
        inscribir(self.suspendido, self.origen, self.g2)
        inscribir(self.sexto, self.origen, self.g6)
        inscribir(self.con_baja, self.origen, self.g1, activa=False)
        inscribir(self.b, self.destino, self.g2)                      # B ya está inscrito en el destino

    def parametros(self):
        return {'origen': self.origen.pk, 'destino': self.destino.pk}

    def post(self, decisiones=None, follow=False, **extra):
        datos = {**self.parametros(), 'fecha': hoy().isoformat()}
        for grado, valor in (decisiones or {}).items():
            datos[f'grado_{grado.pk}'] = valor
        datos.update(extra)
        return self.client.post(self.url, datos, follow=follow)

    # --- vista previa ---------------------------------------------------------------
    def test_sin_ciclo_de_destino_avisa(self):
        self.destino.delete()
        respuesta = self.client.get(self.url)
        self.assertFalse(respuesta.context['hay_destinos'])
        self.assertContains(respuesta, 'No hay un ciclo al cual reinscribir')

    def test_propone_del_ciclo_actual_al_proximo(self):
        self.preparar()
        respuesta = self.client.get(self.url)
        form = respuesta.context['form']
        self.assertEqual((respuesta.context['origen'], respuesta.context['destino']), (self.origen, self.destino))
        self.assertEqual(form['fecha'].value(), hoy().isoformat())
        self.assertIsNotNone(respuesta.context['plan'])

    def test_sin_ciclo_proximo_no_hay_vista_previa_automatica(self):
        self.destino.delete()
        ciclo_cerrado_de_prueba()
        respuesta = self.client.get(self.url)
        self.assertIsNone(respuesta.context['plan'])

    def test_el_plan_cuenta_a_quien_si_se_reinscribe_y_a_quien_se_omite(self):
        self.preparar()
        plan = {str(f['grado']): f for f in self.client.get(self.url, self.parametros()).context['plan']}
        self.assertEqual(list(plan), ['1° Primaria', '2° Primaria', '6° Primaria'])         # orden escolar
        self.assertEqual((plan['1° Primaria']['cantidad'], plan['1° Primaria']['ya_inscritos']), (1, 1))   # A pasa, B ya está
        self.assertEqual((plan['2° Primaria']['cantidad'], plan['2° Primaria']['no_activos']), (0, 1))     # suspendido
        self.assertEqual(plan['6° Primaria']['cantidad'], 1)
        # la inscripción dada de baja no forma parte del plan
        self.assertNotIn(self.con_baja.pk, plan['1° Primaria']['alumnos'])

    def test_el_destino_sugerido_es_el_siguiente_grado(self):
        self.preparar()
        plan = {str(f['grado']): f['sugerido'] for f in self.client.get(self.url, self.parametros()).context['plan']}
        self.assertEqual(plan['1° Primaria'], str(self.g2.pk))
        self.assertEqual(plan['2° Primaria'], str(self.g6.pk))    # 3.° a 5.° no existen: sigue el 6.°
        self.assertEqual(plan['6° Primaria'], str(self.s1.pk))    # pasa a 1.° de secundaria

    def test_el_ultimo_grado_se_omite_por_defecto_y_nunca_se_egresa_solo(self):
        ultimo = crear_alumno()
        inscribir(ultimo, self.origen, self.s1)
        plan = {str(f['grado']): f['sugerido'] for f in self.client.get(self.url, self.parametros()).context['plan']}
        self.assertEqual(plan['1° Secundaria'], 'omitir')

    def test_origen_igual_a_destino_es_un_error(self):
        respuesta = self.client.get(self.url, {'origen': self.origen.pk, 'destino': self.origen.pk})
        self.assertIsNone(respuesta.context['plan'])
        self.assertIn('destino', respuesta.context['form'].errors)

    def test_no_se_reinscribe_hacia_un_ciclo_cerrado(self):
        cerrado = ciclo_cerrado_de_prueba()
        respuesta = self.client.get(self.url, {'origen': self.origen.pk, 'destino': cerrado.pk})
        self.assertIsNone(respuesta.context['plan'])
        self.assertIn('destino', respuesta.context['form'].errors)

    def test_origen_sin_alumnos(self):
        respuesta = self.client.get(self.url, self.parametros())
        self.assertEqual(respuesta.context['plan'], [])
        self.assertContains(respuesta, 'no tiene estudiantes inscritos')

    def test_la_vista_previa_usa_consultas_constantes(self):
        self.preparar()
        with CaptureQueriesContext(connection) as pocas:
            self.client.get(self.url, self.parametros())
        for i in range(15):
            inscribir(crear_alumno(), self.origen, self.g1 if i % 2 else self.g2)
        with CaptureQueriesContext(connection) as muchas:
            self.client.get(self.url, self.parametros())
        self.assertEqual(len(muchas), len(pocas))

    # --- confirmación ---------------------------------------------------------------
    def test_reinscribe_a_cada_alumno_en_el_grado_elegido(self):
        self.preparar()
        respuesta = self.post({self.g1: str(self.g2.pk), self.g6: str(self.s1.pk), self.g2: 'omitir'})
        self.assertRedirects(respuesta, lista(self.destino), fetch_redirect_response=False)
        self.assertEqual(Inscripcion.objects.get(alumno=self.a, ciclo=self.destino).grado, self.g2)
        self.assertEqual(Inscripcion.objects.get(alumno=self.sexto, ciclo=self.destino).grado, self.s1)
        self.assertEqual(Inscripcion.objects.get(alumno=self.b, ciclo=self.destino).grado, self.g2)    # no se tocó la que ya tenía
        self.assertFalse(Inscripcion.objects.filter(alumno=self.suspendido, ciclo=self.destino).exists())
        self.assertFalse(Inscripcion.objects.filter(alumno=self.con_baja, ciclo=self.destino).exists())
        self.assertEqual(Inscripcion.objects.filter(ciclo=self.destino).count(), 3)

    def test_usa_la_fecha_indicada_y_confirma_con_un_mensaje(self):
        self.preparar()
        ayer = hoy() - timedelta(days=1)
        respuesta = self.post({self.g1: str(self.g2.pk)}, fecha=ayer.isoformat())
        self.assertEqual(Inscripcion.objects.get(alumno=self.a, ciclo=self.destino).fecha_inscripcion, ayer)
        self.assertContains(self.client.get(respuesta['Location']), 'Se reinscribió a 1 estudiante en 2027-2028')

    def test_no_toca_las_inscripciones_del_ciclo_de_origen(self):
        self.preparar()
        self.post({self.g1: str(self.g2.pk)})
        self.assertEqual(Inscripcion.objects.filter(ciclo=self.origen).count(), 5)
        self.assertTrue(Inscripcion.objects.get(alumno=self.a, ciclo=self.origen).activa)

    def test_omitir_no_crea_nada(self):
        self.preparar()
        respuesta = self.post({self.g1: 'omitir', self.g2: 'omitir', self.g6: 'omitir'}, follow=True)
        self.assertEqual(Inscripcion.objects.filter(ciclo=self.destino).count(), 1)       # solo la que ya existía
        self.assertContains(respuesta, 'No había estudiantes por reinscribir')

    def test_lo_que_no_se_envia_se_omite(self):
        self.preparar()
        self.post({})
        self.assertEqual(Inscripcion.objects.filter(ciclo=self.destino).count(), 1)

    def test_repetirlo_no_duplica_nada(self):
        self.preparar()
        self.post({self.g1: str(self.g2.pk), self.g6: str(self.s1.pk)})
        cantidad = Inscripcion.objects.count()
        respuesta = self.post({self.g1: str(self.g2.pk), self.g6: str(self.s1.pk)}, follow=True)
        self.assertEqual(Inscripcion.objects.count(), cantidad)
        self.assertContains(respuesta, 'No había estudiantes por reinscribir')

    def test_egresar_cambia_el_estatus_sin_inscribir(self):
        self.preparar()
        respuesta = self.post({self.g6: 'egresar'}, follow=True)
        self.sexto.refresh_from_db()
        self.assertEqual(self.sexto.estatus, 'EGRESADO')
        self.assertFalse(Inscripcion.objects.filter(alumno=self.sexto, ciclo=self.destino).exists())
        self.assertContains(respuesta, 'a estatus «Egresado»')
        self.assertTrue(Inscripcion.objects.get(alumno=self.sexto, ciclo=self.origen).activa)   # su historial se conserva

    def test_egresar_pide_permiso_para_cambiar_alumnos(self):
        self.preparar()
        self.con_permisos('view_inscripcion', 'add_inscripcion')
        respuesta = self.post({self.g1: str(self.g2.pk), self.g6: 'egresar'}, follow=True)
        self.assertContains(respuesta, 'No tienes permiso para marcar estudiantes como egresados')
        self.sexto.refresh_from_db()
        self.assertEqual(self.sexto.estatus, 'ACTIVO')
        self.assertEqual(Inscripcion.objects.filter(ciclo=self.destino).count(), 1)             # no se hizo nada
        self.assertFalse(self.client.get(self.url, self.parametros()).context['puede_egresar'])

    def test_rechaza_un_destino_que_no_existe_o_esta_dado_de_baja(self):
        self.preparar()
        baja = crear_grado('PRIMARIA', 5, activo=False)
        for valor in (str(baja.pk), '999999', 'abc', ''):
            respuesta = self.post({self.g1: valor}, follow=True)
            self.assertContains(respuesta, 'ya no está disponible', msg_prefix=valor)
        self.assertEqual(Inscripcion.objects.filter(ciclo=self.destino).count(), 1)

    def test_ciclos_invalidos_no_hacen_nada(self):
        self.preparar()
        for parametros in ({'origen': self.origen.pk, 'destino': self.origen.pk}, {'origen': '', 'destino': ''}, {'origen': 9999, 'destino': self.destino.pk}):
            respuesta = self.post({self.g1: str(self.g2.pk)}, **parametros)
            self.assertRedirects(respuesta, self.url, fetch_redirect_response=False)
        self.assertEqual(Inscripcion.objects.filter(ciclo=self.destino).count(), 1)

    def test_no_acepta_fechas_futuras(self):
        self.preparar()
        self.post({self.g1: str(self.g2.pk)}, fecha=(hoy() + timedelta(days=3)).isoformat())
        self.assertEqual(Inscripcion.objects.filter(ciclo=self.destino).count(), 1)

    def test_un_error_al_guardar_no_deja_cambios_a_medias(self):
        self.preparar()
        with patch('django.db.models.query.QuerySet.bulk_create', side_effect=IntegrityError('duplicado')):
            respuesta = self.post({self.g1: str(self.g2.pk), self.g6: 'egresar'}, follow=True)
        self.assertContains(respuesta, 'otra persona inscribió')
        self.sexto.refresh_from_db()
        self.assertEqual(self.sexto.estatus, 'ACTIVO')
        self.assertEqual(Alumno.objects.filter(estatus='EGRESADO').count(), 0)
        self.assertEqual(Inscripcion.objects.filter(ciclo=self.destino).count(), 1)

    def test_una_baja_de_alumno_no_se_reinscribe(self):
        self.preparar()
        self.a.estatus = 'BAJA'
        self.a.save()
        self.post({self.g1: str(self.g2.pk)})
        self.assertFalse(Inscripcion.objects.filter(alumno=self.a, ciclo=self.destino).exists())

    def test_los_alumnos_reinscritos_ya_tienen_grado_actual_al_cambiar_de_ciclo(self):
        self.preparar()
        self.post({self.g1: str(self.g2.pk)})
        self.client.post(reverse('ciclos:establecer_actual', args=[self.destino.pk]))
        respuesta = self.client.get(reverse('alumnos:lista'), {'situacion': 'inscritos'})
        self.assertIn(self.a, list(respuesta.context['pagina']))
        self.assertContains(respuesta, '2° Primaria')
