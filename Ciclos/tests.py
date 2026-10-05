from datetime import timedelta

from django.urls import reverse

from Alumnos.models import CicloEscolar
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    ciclo_cerrado_de_prueba,
    ciclo_proximo_de_prueba,
    crear_alumno,
    crear_ciclo,
    crear_grado,
    hoy,
    inscribir,
)


def datos_ciclo(**cambios):
    datos = {
        'nombre': '2030-2031',
        'fecha_inicio': (hoy() + timedelta(days=2000)).isoformat(),
        'fecha_fin': (hoy() + timedelta(days=2300)).isoformat(),
    }
    datos.update(cambios)
    return datos


# ---------------------------------------------------------------------------
# Permisos
# ---------------------------------------------------------------------------
@PRUEBAS
class PermisosTests(BaseTestCase):
    def test_anonimo_es_enviado_al_login(self):
        self.client.logout()
        ciclo = ciclo_actual_de_prueba()
        for nombre, args in (('lista', []), ('crear', []), ('detalle', [ciclo.pk]), ('editar', [ciclo.pk])):
            respuesta = self.client.get(reverse(f'ciclos:{nombre}', args=args))
            self.assertEqual(respuesta.status_code, 302, nombre)
            self.assertIn('/admin/login/', respuesta['Location'])

    def test_sin_permisos_recibe_403(self):
        self.client.force_login(self.sin_permisos)
        ciclo = ciclo_cerrado_de_prueba()
        for nombre, args in (('lista', []), ('crear', []), ('detalle', [ciclo.pk]), ('editar', [ciclo.pk])):
            self.assertEqual(self.client.get(reverse(f'ciclos:{nombre}', args=args)).status_code, 403, nombre)
        for nombre in ('establecer_actual', 'cerrar'):
            self.assertEqual(self.client.post(reverse(f'ciclos:{nombre}', args=[ciclo.pk])).status_code, 403, nombre)
        ciclo.refresh_from_db()
        self.assertFalse(ciclo.activo)

    def test_las_acciones_solo_aceptan_post(self):
        ciclo = ciclo_actual_de_prueba()
        for nombre in ('establecer_actual', 'cerrar'):
            self.assertEqual(self.client.get(reverse(f'ciclos:{nombre}', args=[ciclo.pk])).status_code, 405, nombre)

    def test_cada_accion_pide_su_permiso(self):
        ciclo = ciclo_cerrado_de_prueba()
        self.con_permisos('view_cicloescolar')
        self.assertEqual(self.client.get(reverse('ciclos:lista')).status_code, 200)
        self.assertEqual(self.client.get(reverse('ciclos:crear')).status_code, 403)
        self.assertEqual(self.client.get(reverse('ciclos:editar', args=[ciclo.pk])).status_code, 403)
        self.con_permisos('view_cicloescolar', 'add_cicloescolar')
        self.assertEqual(self.client.get(reverse('ciclos:crear')).status_code, 200)


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------
@PRUEBAS
class ListaTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.actual = ciclo_actual_de_prueba('2026-2027')
        self.proximo = ciclo_proximo_de_prueba('2027-2028')
        self.cerrado = ciclo_cerrado_de_prueba('2025-2026')

    def nombres(self, **filtros):
        respuesta = self.client.get(reverse('ciclos:lista'), filtros)
        self.assertEqual(respuesta.status_code, 200)
        return [c.nombre for c in respuesta.context['pagina']]

    def test_orden_del_mas_reciente_al_mas_antiguo(self):
        self.assertEqual(self.nombres(), ['2027-2028', '2026-2027', '2025-2026'])

    def test_filtra_por_estado(self):
        self.assertEqual(self.nombres(estado='ACTUAL'), ['2026-2027'])
        self.assertEqual(self.nombres(estado='PROXIMO'), ['2027-2028'])
        self.assertEqual(self.nombres(estado='CERRADO'), ['2025-2026'])
        self.assertEqual(len(self.nombres(estado='XX')), 3)   # un valor inválido se ignora

    def test_conteos_de_las_pestanas(self):
        conteos = self.client.get(reverse('ciclos:lista')).context['conteos']
        self.assertEqual(conteos, {'total': 3, 'actual': 1, 'proximo': 1, 'cerrado': 1})

    def test_muestra_el_ciclo_en_curso_con_sus_inscritos(self):
        grado = crear_grado()
        inscribir(crear_alumno(), self.actual, grado)
        inscribir(crear_alumno(), self.actual, grado)
        inscribir(crear_alumno(), self.actual, grado, activa=False)
        respuesta = self.client.get(reverse('ciclos:lista'))
        actual = respuesta.context['actual']
        self.assertEqual((actual.pk, actual.inscritos, actual.bajas), (self.actual.pk, 2, 1))
        self.assertContains(respuesta, 'Ciclo actual')

    def test_la_tarjeta_del_ciclo_en_curso_no_acompana_a_los_filtros(self):
        self.assertIsNone(self.client.get(reverse('ciclos:lista'), {'estado': 'CERRADO'}).context['actual'])

    def test_los_conteos_por_ciclo_no_mezclan_inscripciones_de_otros(self):
        grado = crear_grado()
        inscribir(crear_alumno(), self.actual, grado)
        inscribir(crear_alumno(), self.cerrado, grado)
        por_nombre = {c.nombre: c.inscritos for c in self.client.get(reverse('ciclos:lista')).context['pagina']}
        self.assertEqual(por_nombre, {'2027-2028': 0, '2026-2027': 1, '2025-2026': 1})

    def test_avisa_si_no_hay_ciclo_actual(self):
        CicloEscolar.objects.update(activo=False)
        self.assertContains(self.client.get(reverse('ciclos:lista')), 'No hay un ciclo actual')

    def test_avisa_si_el_ciclo_actual_esta_fuera_de_fechas(self):
        CicloEscolar.objects.filter(pk=self.actual.pk).update(fecha_fin=hoy() - timedelta(days=1))
        self.assertContains(self.client.get(reverse('ciclos:lista')), 'queda fuera de las fechas')

    def test_sin_ciclos_invita_a_crear_el_primero(self):
        CicloEscolar.objects.all().delete()
        respuesta = self.client.get(reverse('ciclos:lista'))
        self.assertContains(respuesta, 'Aún no hay ciclos escolares')
        self.assertNotContains(respuesta, 'No hay un ciclo actual')

    def test_consultas_constantes(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as pocas:
            self.client.get(reverse('ciclos:lista'))
        for i in range(12):
            crear_ciclo(f'Extra {i}', -2000 - i * 400, -1700 - i * 400)
        with CaptureQueriesContext(connection) as muchas:
            self.client.get(reverse('ciclos:lista'))
        self.assertEqual(len(muchas), len(pocas))


# ---------------------------------------------------------------------------
# Alta
# ---------------------------------------------------------------------------
@PRUEBAS
class CrearTests(BaseTestCase):
    url = property(lambda self: reverse('ciclos:crear'))

    def test_propone_el_siguiente_ciclo(self):
        CicloEscolar.objects.create(nombre='2026-2027', fecha_inicio='2026-08-31', fecha_fin='2027-07-15', activo=True)
        form = self.client.get(self.url).context['form']
        self.assertEqual(form.initial['nombre'], '2027-2028')
        self.assertEqual(str(form.initial['fecha_inicio']), '2027-08-31')
        self.assertFalse(form.initial['activo'])         # ya hay uno actual

    def test_el_primer_ciclo_se_propone_como_actual(self):
        self.assertTrue(self.client.get(self.url).context['form'].initial['activo'])

    def test_registra_y_redirige_al_listado_con_mensaje(self):
        respuesta = self.client.post(self.url, datos_ciclo(), follow=True)
        self.assertRedirects(respuesta, reverse('ciclos:lista'))
        self.assertContains(respuesta, 'El ciclo 2030-2031 fue registrado')
        ciclo = CicloEscolar.objects.get()
        self.assertFalse(ciclo.activo)

    def test_marcarlo_como_actual_quita_la_marca_al_anterior(self):
        anterior = ciclo_actual_de_prueba()
        respuesta = self.client.post(self.url, {**datos_ciclo(), 'activo': 'on'}, follow=True)
        self.assertContains(respuesta, 'y es el ciclo actual')
        anterior.refresh_from_db()
        self.assertFalse(anterior.activo)
        self.assertTrue(CicloEscolar.objects.get(nombre='2030-2031').activo)
        self.assertEqual(CicloEscolar.objects.filter(activo=True).count(), 1)

    def test_normaliza_los_espacios_del_nombre(self):
        self.client.post(self.url, datos_ciclo(nombre='  2030-2031   Extra '))
        self.assertEqual(CicloEscolar.objects.get().nombre, '2030-2031 Extra')

    def test_el_nombre_no_se_repite_aunque_cambien_las_mayusculas(self):
        crear_ciclo('Ciclo Especial', -3000, -2700)
        respuesta = self.client.post(self.url, datos_ciclo(nombre='ciclo especial'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('nombre', respuesta.context['form'].errors)
        self.assertEqual(CicloEscolar.objects.count(), 1)

    def test_el_inicio_debe_ser_anterior_al_fin(self):
        respuesta = self.client.post(self.url, datos_ciclo(fecha_inicio='2031-05-01', fecha_fin='2031-04-01'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'La fecha de inicio debe ser anterior a la fecha de fin')
        self.assertFalse(CicloEscolar.objects.exists())

    def test_no_se_empalma_con_otro_ciclo(self):
        existente = ciclo_actual_de_prueba('2026-2027')
        respuesta = self.client.post(self.url, datos_ciclo(
            fecha_inicio=(existente.fecha_fin - timedelta(days=10)).isoformat(),
            fecha_fin=(existente.fecha_fin + timedelta(days=200)).isoformat(),
        ))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('fecha_inicio', respuesta.context['form'].errors)
        self.assertContains(respuesta, 'se empalman con el ciclo 2026-2027')

    def test_ciclos_contiguos_si_se_permiten(self):
        existente = ciclo_actual_de_prueba('2026-2027')
        respuesta = self.client.post(self.url, datos_ciclo(
            fecha_inicio=(existente.fecha_fin + timedelta(days=1)).isoformat(),
            fecha_fin=(existente.fecha_fin + timedelta(days=300)).isoformat(),
        ))
        self.assertEqual(respuesta.status_code, 302)

    def test_campos_obligatorios(self):
        respuesta = self.client.post(self.url, {})
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(set(respuesta.context['form'].errors), {'nombre', 'fecha_inicio', 'fecha_fin'})


# ---------------------------------------------------------------------------
# Edición
# ---------------------------------------------------------------------------
@PRUEBAS
class EditarTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba('2026-2027')
        self.otro = ciclo_cerrado_de_prueba('2025-2026')
        self.url = reverse('ciclos:editar', args=[self.ciclo.pk])

    def datos(self, **cambios):
        datos = {
            'nombre': self.ciclo.nombre, 'fecha_inicio': self.ciclo.fecha_inicio.isoformat(),
            'fecha_fin': self.ciclo.fecha_fin.isoformat(), 'activo': 'on',
        }
        datos.update(cambios)
        return datos

    def test_formulario_precargado(self):
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, 'value="2026-2027"')
        self.assertTrue(respuesta.context['form'].initial['activo'])

    def test_actualiza_y_redirige_al_listado(self):
        respuesta = self.client.post(self.url, self.datos(nombre='2026-2027 B'), follow=True)
        self.assertRedirects(respuesta, reverse('ciclos:lista'))
        self.assertContains(respuesta, 'se actualizó')
        self.ciclo.refresh_from_db()
        self.assertEqual(self.ciclo.nombre, '2026-2027 B')

    def test_conserva_su_propio_nombre_y_fechas(self):
        self.assertEqual(self.client.post(self.url, self.datos()).status_code, 302)

    def test_no_permite_el_nombre_de_otro_ciclo(self):
        respuesta = self.client.post(self.url, self.datos(nombre='2025-2026'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('nombre', respuesta.context['form'].errors)

    def test_no_permite_empalmarse_con_otro_ciclo(self):
        respuesta = self.client.post(self.url, self.datos(fecha_inicio=(self.otro.fecha_fin - timedelta(days=5)).isoformat()))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('fecha_inicio', respuesta.context['form'].errors)

    def test_desmarcar_el_ciclo_actual_lo_cierra(self):
        datos = self.datos()
        datos.pop('activo')
        self.client.post(self.url, datos)
        self.ciclo.refresh_from_db()
        self.assertFalse(self.ciclo.activo)

    def test_marcar_otro_como_actual_desde_su_edicion(self):
        proximo = ciclo_proximo_de_prueba()
        datos = {
            'nombre': proximo.nombre, 'fecha_inicio': proximo.fecha_inicio.isoformat(),
            'fecha_fin': proximo.fecha_fin.isoformat(), 'activo': 'on',
        }
        self.client.post(reverse('ciclos:editar', args=[proximo.pk]), datos)
        self.ciclo.refresh_from_db()
        proximo.refresh_from_db()
        self.assertTrue(proximo.activo)
        self.assertFalse(self.ciclo.activo)

    def test_ciclo_inexistente_da_404(self):
        self.assertEqual(self.client.get(reverse('ciclos:editar', args=[9999])).status_code, 404)


# ---------------------------------------------------------------------------
# Perfil del ciclo
# ---------------------------------------------------------------------------
@PRUEBAS
class DetalleTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.anterior = ciclo_cerrado_de_prueba('2025-2026')
        self.actual = ciclo_actual_de_prueba('2026-2027')
        self.proximo = ciclo_proximo_de_prueba('2027-2028')
        self.primero = crear_grado('PRIMARIA', 1)
        self.segundo = crear_grado('PRIMARIA', 2)
        self.preescolar = crear_grado('PREESCOLAR', 3)

    def detalle(self, ciclo):
        respuesta = self.client.get(ciclo.get_absolute_url())
        self.assertEqual(respuesta.status_code, 200)
        return respuesta

    def test_resumen_por_grado_en_orden_escolar(self):
        inscribir(crear_alumno(), self.actual, self.segundo)
        inscribir(crear_alumno(), self.actual, self.segundo)
        inscribir(crear_alumno(), self.actual, self.primero)
        inscribir(crear_alumno(), self.actual, self.primero, activa=False)
        respuesta = self.detalle(self.actual)
        filas = respuesta.context['filas']
        self.assertEqual([str(f['grado']) for f in filas], ['3° Preescolar', '1° Primaria', '2° Primaria'])
        self.assertEqual([(f['activas'], f['bajas']) for f in filas], [(0, 0), (1, 1), (2, 0)])
        self.assertEqual([f['porcentaje'] for f in filas], [0, 50, 100])
        self.assertEqual((respuesta.context['total_activas'], respuesta.context['total_bajas']), (3, 1))

    def test_un_grado_dado_de_baja_con_alumnos_sigue_apareciendo(self):
        inscribir(crear_alumno(), self.actual, self.primero)
        self.primero.activo = False
        self.primero.save()
        self.assertIn('1° Primaria', [str(f['grado']) for f in self.detalle(self.actual).context['filas']])
        self.assertContains(self.detalle(self.actual), 'Grado dado de baja')

    def test_un_grado_dado_de_baja_sin_alumnos_no_aparece(self):
        self.primero.activo = False
        self.primero.save()
        self.assertNotIn('1° Primaria', [str(f['grado']) for f in self.detalle(self.actual).context['filas']])

    def test_alumnos_por_inscribir(self):
        inscrito = crear_alumno()
        inscribir(inscrito, self.actual, self.primero)
        crear_alumno()
        crear_alumno()
        crear_alumno(estatus='BAJA')
        self.assertEqual(self.detalle(self.actual).context['sin_inscribir'], 2)

    def test_sugiere_reinscribir_desde_el_ciclo_anterior_con_alumnos(self):
        self.assertIsNone(self.detalle(self.proximo).context['origen_sugerido'])   # nadie inscrito antes
        inscribir(crear_alumno(), self.actual, self.primero)
        respuesta = self.detalle(self.proximo)
        self.assertEqual(respuesta.context['origen_sugerido'], self.actual)
        self.assertContains(respuesta, f'origen={self.actual.pk}&amp;destino={self.proximo.pk}')

    def test_un_ciclo_cerrado_no_ofrece_reinscribir(self):
        inscribir(crear_alumno(), self.anterior, self.primero)
        self.assertIsNone(self.detalle(self.anterior).context['origen_sugerido'])

    def test_ofrece_cerrar_el_ciclo_actual_y_establecer_el_otro(self):
        self.assertContains(self.detalle(self.actual), 'Cerrar el ciclo')
        self.assertNotContains(self.detalle(self.actual), 'Establecer como ciclo actual')
        respuesta = self.detalle(self.proximo)
        self.assertContains(respuesta, 'Establecer como ciclo actual')
        self.assertEqual(respuesta.context['otro_actual'], self.actual)

    def test_sin_permiso_de_cambio_no_hay_acciones(self):
        self.con_permisos('view_cicloescolar')
        respuesta = self.detalle(self.actual)
        self.assertNotContains(respuesta, 'Cerrar el ciclo')
        self.assertNotContains(respuesta, 'Editar')

    def test_consultas_constantes_con_muchos_alumnos(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as pocas:
            self.detalle(self.actual)
        for i in range(10):
            inscribir(crear_alumno(), self.actual, self.primero if i % 2 else self.segundo)
        with CaptureQueriesContext(connection) as muchas:
            self.detalle(self.actual)
        self.assertEqual(len(muchas), len(pocas))

    def test_ciclo_inexistente_da_404(self):
        self.assertEqual(self.client.get(reverse('ciclos:detalle', args=[9999])).status_code, 404)


# ---------------------------------------------------------------------------
# Establecer como actual y cerrar
# ---------------------------------------------------------------------------
@PRUEBAS
class AccionesTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.actual = ciclo_actual_de_prueba('2026-2027')
        self.proximo = ciclo_proximo_de_prueba('2027-2028')

    def test_establecer_como_actual(self):
        respuesta = self.client.post(reverse('ciclos:establecer_actual', args=[self.proximo.pk]), follow=True)
        self.assertRedirects(respuesta, reverse('ciclos:lista'))
        self.assertContains(respuesta, 'es ahora el ciclo actual')
        self.assertContains(respuesta, 'El ciclo 2026-2027 dejó de ser el actual')
        self.actual.refresh_from_db()
        self.proximo.refresh_from_db()
        self.assertEqual((self.actual.activo, self.proximo.activo), (False, True))

    def test_establecer_el_que_ya_es_actual_no_cambia_nada(self):
        respuesta = self.client.post(reverse('ciclos:establecer_actual', args=[self.actual.pk]), follow=True)
        self.assertContains(respuesta, 'ya es el ciclo actual')
        self.assertEqual(CicloEscolar.objects.filter(activo=True).count(), 1)

    def test_cerrar_es_logico(self):
        grado = crear_grado()
        inscripcion = inscribir(crear_alumno(), self.actual, grado)
        respuesta = self.client.post(reverse('ciclos:cerrar', args=[self.actual.pk]), follow=True)
        self.assertRedirects(respuesta, reverse('ciclos:lista'))
        self.assertContains(respuesta, 'se cerró')
        self.actual.refresh_from_db()
        self.assertFalse(self.actual.activo)
        self.assertTrue(CicloEscolar.objects.filter(pk=self.actual.pk).exists())
        inscripcion.refresh_from_db()                 # nada se borra ni se da de baja
        self.assertTrue(inscripcion.activa)

    def test_cerrar_un_ciclo_que_no_es_el_actual_no_cambia_nada(self):
        respuesta = self.client.post(reverse('ciclos:cerrar', args=[self.proximo.pk]), follow=True)
        self.assertContains(respuesta, 'no es el ciclo actual')
        self.actual.refresh_from_db()
        self.assertTrue(self.actual.activo)

    def test_sin_ciclo_actual_los_alumnos_aparecen_sin_inscripcion_actual(self):
        grado = crear_grado()
        alumno = crear_alumno()
        inscribir(alumno, self.actual, grado)
        self.client.post(reverse('ciclos:cerrar', args=[self.actual.pk]))
        respuesta = self.client.get(reverse('alumnos:lista'), {'situacion': 'sin_inscripcion'})
        self.assertIn(alumno, list(respuesta.context['pagina']))

    def test_ciclo_inexistente_da_404(self):
        self.assertEqual(self.client.post(reverse('ciclos:cerrar', args=[9999])).status_code, 404)
        self.assertEqual(self.client.post(reverse('ciclos:establecer_actual', args=[9999])).status_code, 404)
