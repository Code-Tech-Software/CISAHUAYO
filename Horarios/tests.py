from datetime import time

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from Alumnos.models import HorarioMateria, Materia, MateriaGrado
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    ciclo_cerrado_de_prueba,
    ciclo_proximo_de_prueba,
    crear_grado,
)


def asignar(clave, nombre, grado, ciclo, **cambios):
    materia, _ = Materia.objects.get_or_create(clave=clave, defaults={'nombre': nombre})
    return MateriaGrado.objects.create(materia=materia, grado=grado, ciclo=ciclo, **cambios)


def bloque(asignacion, dia, inicio, fin):
    return HorarioMateria.objects.create(materia_grado=asignacion, dia_semana=dia, hora_inicio=time(*inicio), hora_fin=time(*fin))


def datos(asignacion, dias=(0,), inicio='10:00', fin='11:00'):
    return {'materia_grado': asignacion.pk, 'dias': list(dias), 'hora_inicio': inicio, 'hora_fin': fin}


# ---------------------------------------------------------------------------
# Permisos
# ---------------------------------------------------------------------------
@PRUEBAS
class PermisosTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.grado = crear_grado('PRIMARIA', 4)
        self.asignacion = asignar('MAT', 'Matemáticas', self.grado, self.ciclo)
        self.bloque = bloque(self.asignacion, 0, (8, 0), (9, 0))

    def paginas(self):
        return (('lista', []), ('grado', [self.grado.pk]), ('crear', [self.grado.pk]), ('editar', [self.bloque.pk]))

    def test_anonimo_es_enviado_al_login(self):
        self.client.logout()
        for nombre, args in self.paginas():
            respuesta = self.client.get(reverse(f'horarios:{nombre}', args=args))
            self.assertEqual(respuesta.status_code, 302, nombre)
            self.assertIn('/admin/login/', respuesta['Location'])

    def test_sin_permisos_recibe_403(self):
        self.client.force_login(self.sin_permisos)
        for nombre, args in self.paginas():
            self.assertEqual(self.client.get(reverse(f'horarios:{nombre}', args=args)).status_code, 403, nombre)
        self.assertEqual(self.client.post(reverse('horarios:eliminar', args=[self.bloque.pk])).status_code, 403)
        self.assertTrue(HorarioMateria.objects.filter(pk=self.bloque.pk).exists())

    def test_eliminar_solo_acepta_post(self):
        self.assertEqual(self.client.get(reverse('horarios:eliminar', args=[self.bloque.pk])).status_code, 405)

    def test_cada_accion_pide_su_permiso(self):
        self.con_permisos('view_horariomateria')
        self.assertEqual(self.client.get(reverse('horarios:grado', args=[self.grado.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('horarios:crear', args=[self.grado.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse('horarios:editar', args=[self.bloque.pk])).status_code, 403)
        self.con_permisos('view_horariomateria', 'add_horariomateria')
        self.assertEqual(self.client.get(reverse('horarios:crear', args=[self.grado.pk])).status_code, 200)
        self.con_permisos('view_horariomateria', 'change_horariomateria')
        self.assertEqual(self.client.get(reverse('horarios:editar', args=[self.bloque.pk])).status_code, 200)
        self.assertEqual(self.client.post(reverse('horarios:eliminar', args=[self.bloque.pk])).status_code, 403)
        self.con_permisos('view_horariomateria', 'delete_horariomateria')
        self.assertEqual(self.client.post(reverse('horarios:eliminar', args=[self.bloque.pk])).status_code, 302)

    def test_sin_permisos_de_cambio_no_se_ofrecen_acciones(self):
        self.con_permisos('view_horariomateria')
        respuesta = self.client.get(reverse('horarios:grado', args=[self.grado.pk]))
        self.assertNotContains(respuesta, 'Agregar horario')
        self.assertNotContains(respuesta, 'data-eliminar')
        self.assertNotContains(respuesta, reverse('horarios:editar', args=[self.bloque.pk]))


# ---------------------------------------------------------------------------
# Índice de grados
# ---------------------------------------------------------------------------
@PRUEBAS
class ListaTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba('2026-2027')
        self.proximo = ciclo_proximo_de_prueba('2027-2028')
        self.p1, self.p2, self.p3 = crear_grado('PRIMARIA', 1), crear_grado('PRIMARIA', 2), crear_grado('PRIMARIA', 3)
        self.pre = crear_grado('PREESCOLAR', 1)
        mat = asignar('MAT', 'Matemáticas', self.p1, self.ciclo)
        asignar('ESP', 'Español', self.p1, self.ciclo)                  # sin horario
        asignar('CIE', 'Ciencias', self.p1, self.ciclo, activa=False)   # quitada: no cuenta
        bloque(mat, 0, (8, 0), (9, 0))
        bloque(mat, 2, (8, 0), (9, 30))
        asignar('MAT', 'Matemáticas', self.p2, self.ciclo)

    def filas(self, **filtros):
        respuesta = self.client.get(reverse('horarios:lista'), filtros)
        self.assertEqual(respuesta.status_code, 200)
        return respuesta, {str(f['grado']): f for n in respuesta.context['niveles'] for f in n['filas']}

    def test_agrupa_por_nivel_en_orden_escolar(self):
        respuesta, _ = self.filas()
        self.assertEqual([n['nombre'] for n in respuesta.context['niveles']], ['Preescolar', 'Primaria'])

    def test_resumen_de_cada_grado(self):
        _, filas = self.filas()
        primero = filas['1° Primaria']
        self.assertEqual((primero['materias'], primero['bloques'], primero['minutos'], primero['sin_horario']), (2, 2, 150, 1))
        self.assertEqual(primero['duracion'], '2 h 30 min')
        segundo = filas['2° Primaria']
        self.assertEqual((segundo['materias'], segundo['bloques'], segundo['sin_horario'], segundo['duracion']), (1, 0, 1, ''))
        sin_nada = filas['3° Primaria']
        self.assertEqual((sin_nada['materias'], sin_nada['bloques'], sin_nada['sin_horario']), (0, 0, 0))

    def test_elige_otro_ciclo(self):
        respuesta, filas = self.filas(ciclo=self.proximo.pk)
        self.assertEqual(respuesta.context['ciclo'], self.proximo)
        self.assertEqual(filas['1° Primaria']['materias'], 0)

    def test_un_ciclo_invalido_se_ignora(self):
        respuesta, _ = self.filas(ciclo='x')
        self.assertEqual(respuesta.context['ciclo'], self.ciclo)

    def test_un_grado_de_baja_con_materias_sigue_apareciendo(self):
        self.p2.activo = False
        self.p2.save()
        _, filas = self.filas()
        self.assertIn('2° Primaria', filas)
        self.p3.activo = False
        self.p3.save()
        _, filas = self.filas()
        self.assertNotIn('3° Primaria', filas)

    def test_sin_ciclos_invita_a_crear_uno(self):
        from Alumnos.models import CicloEscolar
        HorarioMateria.objects.all().delete()
        MateriaGrado.objects.all().delete()
        CicloEscolar.objects.all().delete()
        self.assertContains(self.client.get(reverse('horarios:lista')), 'Aún no hay ciclos escolares')

    def test_un_ciclo_cerrado_avisa_que_es_de_solo_lectura(self):
        cerrado = ciclo_cerrado_de_prueba()
        respuesta, _ = self.filas(ciclo=cerrado.pk)
        self.assertFalse(respuesta.context['editable'])
        self.assertContains(respuesta, 'está cerrado')

    def test_consultas_constantes(self):
        with CaptureQueriesContext(connection) as pocas:
            self.filas()
        for numero in range(4, 7):
            grado = crear_grado('PRIMARIA', numero)
            bloque(asignar('MAT', 'Matemáticas', grado, self.ciclo), 1, (8, 0), (9, 0))
        with CaptureQueriesContext(connection) as muchas:
            self.filas()
        self.assertEqual(len(muchas), len(pocas))


# ---------------------------------------------------------------------------
# Horario semanal de un grado
# ---------------------------------------------------------------------------
@PRUEBAS
class GradoTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba('2026-2027')
        self.cerrado = ciclo_cerrado_de_prueba('2025-2026')
        self.grado = crear_grado('PRIMARIA', 4)
        self.mat = asignar('MAT', 'Matemáticas', self.grado, self.ciclo)
        self.esp = asignar('ESP', 'Español', self.grado, self.ciclo)
        self.sin = asignar('ING', 'Inglés', self.grado, self.ciclo)
        bloque(self.mat, 0, (8, 0), (9, 0))
        bloque(self.mat, 2, (8, 0), (9, 0))
        bloque(self.esp, 0, (9, 0), (10, 0))

    def pedir(self, **filtros):
        respuesta = self.client.get(reverse('horarios:grado', args=[self.grado.pk]), filtros)
        self.assertEqual(respuesta.status_code, 200)
        return respuesta

    def test_cuadricula_semanal(self):
        tabla = self.pedir().context['cuadricula']
        self.assertEqual([d['corto'] for d in tabla['dias']], ['Lun', 'Mar', 'Mié', 'Jue', 'Vie'])
        self.assertEqual([(f['inicio'], f['fin']) for f in tabla['filas']], [(time(8, 0), time(9, 0)), (time(9, 0), time(10, 0))])
        primera = tabla['filas'][0]['celdas']
        self.assertEqual([[b.materia_grado.materia.clave for b in celda] for celda in primera], [['MAT'], [], ['MAT'], [], []])

    def test_resumen_y_materias_sin_horario(self):
        respuesta = self.pedir()
        self.assertEqual(respuesta.context['total_bloques'], 3)
        self.assertEqual(respuesta.context['horas_semanales'], '3 h')
        self.assertEqual([a.materia.clave for a in respuesta.context['sin_horario']], ['ING'])
        self.assertContains(respuesta, 'Materias sin horario')
        self.assertContains(respuesta, f'materia={self.sin.pk}')

    def test_una_materia_quitada_no_aparece(self):
        self.esp.activa = False
        self.esp.save()
        respuesta = self.pedir()
        self.assertEqual(respuesta.context['total_bloques'], 2)
        self.assertNotContains(respuesta, 'Español')

    def test_solo_el_ciclo_pedido(self):
        otra = asignar('HIS', 'Historia', self.grado, self.cerrado)
        bloque(otra, 1, (8, 0), (9, 0))
        respuesta = self.pedir(ciclo=self.cerrado.pk)
        self.assertEqual(respuesta.context['ciclo'], self.cerrado)
        self.assertEqual(respuesta.context['total_bloques'], 1)
        self.assertEqual([a.materia.clave for a in respuesta.context['asignaciones']], ['HIS'])

    def test_un_ciclo_cerrado_es_de_solo_lectura(self):
        otra = asignar('HIS', 'Historia', self.grado, self.cerrado)
        bloque(otra, 1, (8, 0), (9, 0))
        respuesta = self.pedir(ciclo=self.cerrado.pk)
        self.assertFalse(respuesta.context['editable'])
        self.assertContains(respuesta, 'está cerrado')
        self.assertNotContains(respuesta, 'Agregar horario')
        self.assertNotContains(respuesta, 'data-eliminar')

    def test_grado_sin_materias_remite_a_asignarlas(self):
        otro = crear_grado('PRIMARIA', 5)
        respuesta = self.client.get(reverse('horarios:grado', args=[otro.pk]))
        self.assertContains(respuesta, 'no tiene materias en este ciclo')
        self.assertContains(respuesta, 'Asignar materias')

    def test_grado_con_materias_pero_sin_horario(self):
        otro = crear_grado('PRIMARIA', 5)
        asignar('MAT', 'Matemáticas', otro, self.ciclo)
        respuesta = self.client.get(reverse('horarios:grado', args=[otro.pk]))
        self.assertContains(respuesta, 'Todavía no hay horario')

    def test_sin_ciclos_no_falla(self):
        from Alumnos.models import CicloEscolar
        HorarioMateria.objects.all().delete()
        MateriaGrado.objects.all().delete()
        CicloEscolar.objects.all().delete()
        self.assertContains(self.pedir(), 'Aún no hay ciclos escolares')

    def test_consultas_constantes_con_muchos_bloques(self):
        with CaptureQueriesContext(connection) as pocas:
            self.pedir()
        for i, (clave, inicio) in enumerate((('A1', (10, 0)), ('A2', (11, 0)), ('A3', (12, 0)), ('A4', (13, 0)))):
            asignacion = asignar(clave, f'Materia {clave}', self.grado, self.ciclo)
            for dia in range(5):
                bloque(asignacion, dia, inicio, (inicio[0] + 1, 0))
        with CaptureQueriesContext(connection) as muchas:
            respuesta = self.pedir()
        self.assertEqual(respuesta.context['total_bloques'], 23)
        self.assertEqual(len(muchas), len(pocas))

    def test_grado_inexistente_da_404(self):
        self.assertEqual(self.client.get(reverse('horarios:grado', args=[9999])).status_code, 404)


# ---------------------------------------------------------------------------
# Agregar
# ---------------------------------------------------------------------------
@PRUEBAS
class CrearTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba('2026-2027')
        self.cerrado = ciclo_cerrado_de_prueba('2025-2026')
        self.grado = crear_grado('PRIMARIA', 4)
        self.mat = asignar('MAT', 'Matemáticas', self.grado, self.ciclo)
        self.esp = asignar('ESP', 'Español', self.grado, self.ciclo)
        self.url = f"{reverse('horarios:crear', args=[self.grado.pk])}?ciclo={self.ciclo.pk}"

    def volver(self):
        return f"{reverse('horarios:grado', args=[self.grado.pk])}?ciclo={self.ciclo.pk}"

    def test_el_formulario_solo_ofrece_las_materias_vigentes_del_grado(self):
        asignar('QUI', 'Quitada', self.grado, self.ciclo, activa=False)
        asignar('OTR', 'De otro grado', crear_grado('PRIMARIA', 5), self.ciclo)
        asignar('VIE', 'De otro ciclo', self.grado, self.cerrado)
        form = self.client.get(self.url).context['form']
        self.assertEqual(sorted(a.materia.clave for a in form.fields['materia_grado'].queryset), ['ESP', 'MAT'])

    def test_trae_datos_de_la_url(self):
        respuesta = self.client.get(f'{self.url}&materia={self.esp.pk}&dia=2')
        form = respuesta.context['form']
        self.assertEqual(form['materia_grado'].value(), self.esp.pk)
        self.assertEqual(form['dias'].value(), [2])
        self.assertEqual(self.client.get(f'{self.url}&materia=x&dia=99').status_code, 200)

    def test_agrega_varios_dias_con_la_misma_hora(self):
        respuesta = self.client.post(self.url, datos(self.mat, dias=(0, 2, 4), inicio='08:00', fin='08:50'), follow=True)
        self.assertRedirects(respuesta, self.volver())
        self.assertContains(respuesta, 'Se agregó el horario de Matemáticas: Lun, Mié, Vie.')
        bloques = HorarioMateria.objects.filter(materia_grado=self.mat)
        self.assertEqual(sorted(b.dia_semana for b in bloques), [0, 2, 4])
        self.assertTrue(all((b.hora_inicio, b.hora_fin) == (time(8, 0), time(8, 50)) for b in bloques))

    def test_hora_de_inicio_y_fin(self):
        respuesta = self.client.post(self.url, datos(self.mat, inicio='11:00', fin='10:00'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'La hora de inicio debe ser anterior a la hora de fin')
        respuesta = self.client.post(self.url, datos(self.mat, inicio='10:00', fin='10:00'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(HorarioMateria.objects.exists())

    def test_campos_obligatorios(self):
        respuesta = self.client.post(self.url, {})
        self.assertEqual(set(respuesta.context['form'].errors), {'materia_grado', 'dias', 'hora_inicio', 'hora_fin'})
        self.assertContains(respuesta, 'Elige al menos un día')

    def test_horas_que_no_son_horas(self):
        respuesta = self.client.post(self.url, datos(self.mat, inicio='25:99'))
        self.assertIn('hora_inicio', respuesta.context['form'].errors)

    def test_dias_invalidos(self):
        respuesta = self.client.post(self.url, {**datos(self.mat), 'dias': ['9']})
        self.assertIn('dias', respuesta.context['form'].errors)

    def test_no_se_empalma_con_otra_materia_del_mismo_grado(self):
        bloque(self.esp, 0, (8, 0), (9, 0))
        respuesta = self.client.post(self.url, datos(self.mat, dias=(0, 1), inicio='08:30', fin='09:30'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Se empalma con Español (lunes 08:00–09:00)')
        self.assertContains(respuesta, 'un grado solo tiene un grupo')
        self.assertFalse(HorarioMateria.objects.filter(materia_grado=self.mat).exists())     # no se guardó ni el martes
        self.assertEqual(len(respuesta.context['form'].errors), 1)

    def test_no_se_empalma_con_la_misma_materia(self):
        bloque(self.mat, 0, (8, 0), (9, 0))
        respuesta = self.client.post(self.url, datos(self.mat, inicio='08:00', fin='09:00'))
        self.assertContains(respuesta, 'Se empalma con Matemáticas')

    def test_franjas_contiguas_si_se_permiten(self):
        bloque(self.esp, 0, (8, 0), (9, 0))
        self.assertEqual(self.client.post(self.url, datos(self.mat, inicio='09:00', fin='10:00')).status_code, 302)

    def test_otro_dia_otro_grado_u_otro_ciclo_no_estorban(self):
        otro_grado = crear_grado('PRIMARIA', 5)
        bloque(asignar('HIS', 'Historia', otro_grado, self.ciclo), 0, (8, 0), (9, 0))
        bloque(asignar('HIS', 'Historia', self.grado, self.cerrado), 0, (8, 0), (9, 0))
        bloque(self.esp, 1, (8, 0), (9, 0))
        self.assertEqual(self.client.post(self.url, datos(self.mat, dias=(0,), inicio='08:00', fin='09:00')).status_code, 302)

    def test_una_materia_quitada_no_estorba(self):
        quitada = asignar('QUI', 'Quitada', self.grado, self.ciclo, activa=False)
        bloque(quitada, 0, (8, 0), (9, 0))
        self.assertEqual(self.client.post(self.url, datos(self.mat, inicio='08:00', fin='09:00')).status_code, 302)

    def test_no_acepta_una_materia_de_otro_grado(self):
        ajena = asignar('HIS', 'Historia', crear_grado('PRIMARIA', 5), self.ciclo)
        respuesta = self.client.post(self.url, datos(ajena))
        self.assertIn('materia_grado', respuesta.context['form'].errors)

    def test_un_ciclo_cerrado_no_se_modifica(self):
        otra = asignar('HIS', 'Historia', self.grado, self.cerrado)
        url = f"{reverse('horarios:crear', args=[self.grado.pk])}?ciclo={self.cerrado.pk}"
        respuesta = self.client.post(url, datos(otra), follow=True)
        self.assertContains(respuesta, 'está cerrado')
        self.assertFalse(HorarioMateria.objects.exists())
        self.assertRedirects(self.client.get(url), f"{reverse('horarios:grado', args=[self.grado.pk])}?ciclo={self.cerrado.pk}")

    def test_sin_materias_remite_a_asignarlas(self):
        otro = crear_grado('PRIMARIA', 5)
        respuesta = self.client.get(f"{reverse('horarios:crear', args=[otro.pk])}?ciclo={self.ciclo.pk}")
        self.assertTrue(respuesta.context['sin_materias'])
        self.assertContains(respuesta, 'no tiene materias en este ciclo')

    def test_sin_ciclos_regresa_al_indice(self):
        from Alumnos.models import CicloEscolar
        HorarioMateria.objects.all().delete()
        MateriaGrado.objects.all().delete()
        CicloEscolar.objects.all().delete()
        self.assertRedirects(self.client.get(reverse('horarios:crear', args=[self.grado.pk])), reverse('horarios:lista'))

    def test_grado_inexistente_da_404(self):
        self.assertEqual(self.client.get(reverse('horarios:crear', args=[9999])).status_code, 404)


# ---------------------------------------------------------------------------
# Editar y quitar
# ---------------------------------------------------------------------------
@PRUEBAS
class EditarTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba('2026-2027')
        self.cerrado = ciclo_cerrado_de_prueba('2025-2026')
        self.grado = crear_grado('PRIMARIA', 4)
        self.mat = asignar('MAT', 'Matemáticas', self.grado, self.ciclo)
        self.esp = asignar('ESP', 'Español', self.grado, self.ciclo)
        self.bloque = bloque(self.mat, 0, (8, 0), (9, 0))
        self.otro = bloque(self.esp, 0, (9, 0), (10, 0))
        self.url = reverse('horarios:editar', args=[self.bloque.pk])
        self.volver = f"{reverse('horarios:grado', args=[self.grado.pk])}?ciclo={self.ciclo.pk}"

    def datos(self, **cambios):
        datos = {'materia_grado': self.mat.pk, 'dia_semana': 0, 'hora_inicio': '08:00', 'hora_fin': '09:00'}
        datos.update(cambios)
        return datos

    def test_formulario_precargado(self):
        respuesta = self.client.get(self.url)
        form = respuesta.context['form']
        self.assertEqual(list(form.fields), ['materia_grado', 'dia_semana', 'hora_inicio', 'hora_fin'])
        self.assertEqual(form.initial['dia_semana'], 0)
        self.assertContains(respuesta, 'Quitar del horario')

    def test_cambia_el_dia_y_la_hora_y_vuelve_al_horario(self):
        respuesta = self.client.post(self.url, self.datos(dia_semana=3, hora_inicio='12:00', hora_fin='13:00'), follow=True)
        self.assertRedirects(respuesta, self.volver)
        self.assertContains(respuesta, 'Se actualizó el horario de Matemáticas (jueves)')
        self.bloque.refresh_from_db()
        self.assertEqual((self.bloque.dia_semana, self.bloque.hora_inicio, self.bloque.hora_fin), (3, time(12, 0), time(13, 0)))

    def test_cambia_de_materia_dentro_del_grado(self):
        self.client.post(self.url, self.datos(materia_grado=self.esp.pk, dia_semana=4))
        self.bloque.refresh_from_db()
        self.assertEqual(self.bloque.materia_grado, self.esp)

    def test_conserva_su_propia_hora(self):
        self.assertEqual(self.client.post(self.url, self.datos()).status_code, 302)

    def test_no_se_empalma_con_otra_materia(self):
        respuesta = self.client.post(self.url, self.datos(hora_fin='09:30'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Se empalma con Español (lunes 09:00–10:00)')
        self.bloque.refresh_from_db()
        self.assertEqual(self.bloque.hora_fin, time(9, 0))

    def test_hora_de_fin_anterior_al_inicio(self):
        respuesta = self.client.post(self.url, self.datos(hora_inicio='10:00', hora_fin='09:00'))
        self.assertContains(respuesta, 'La hora de inicio debe ser anterior a la hora de fin')
        self.assertEqual(len(respuesta.context['form'].errors), 1)

    def test_no_acepta_una_materia_de_otro_grado(self):
        ajena = asignar('HIS', 'Historia', crear_grado('PRIMARIA', 5), self.ciclo)
        respuesta = self.client.post(self.url, self.datos(materia_grado=ajena.pk))
        self.assertIn('materia_grado', respuesta.context['form'].errors)

    def test_un_ciclo_cerrado_no_se_modifica(self):
        otra = asignar('HIS', 'Historia', self.grado, self.cerrado)
        vieja = bloque(otra, 1, (8, 0), (9, 0))
        respuesta = self.client.post(reverse('horarios:editar', args=[vieja.pk]), {
            'materia_grado': otra.pk, 'dia_semana': 2, 'hora_inicio': '10:00', 'hora_fin': '11:00',
        }, follow=True)
        self.assertContains(respuesta, 'está cerrado')
        vieja.refresh_from_db()
        self.assertEqual(vieja.dia_semana, 1)

    def test_el_bloque_de_una_materia_quitada_no_se_edita(self):
        self.mat.activa = False
        self.mat.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_bloque_inexistente_da_404(self):
        self.assertEqual(self.client.get(reverse('horarios:editar', args=[9999])).status_code, 404)


@PRUEBAS
class EliminarTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.cerrado = ciclo_cerrado_de_prueba()
        self.grado = crear_grado('PRIMARIA', 4)
        self.mat = asignar('MAT', 'Matemáticas', self.grado, self.ciclo)
        self.bloque = bloque(self.mat, 0, (8, 0), (9, 0))
        self.otro = bloque(self.mat, 2, (8, 0), (9, 0))

    def test_quita_el_bloque_y_vuelve_al_horario_con_mensaje(self):
        respuesta = self.client.post(reverse('horarios:eliminar', args=[self.bloque.pk]), follow=True)
        self.assertRedirects(respuesta, f"{reverse('horarios:grado', args=[self.grado.pk])}?ciclo={self.ciclo.pk}")
        self.assertContains(respuesta, 'Se quitó Matemáticas del horario (lunes 08:00–09:00)')
        self.assertFalse(HorarioMateria.objects.filter(pk=self.bloque.pk).exists())

    def test_solo_quita_ese_bloque_y_la_materia_sigue_asignada(self):
        self.client.post(reverse('horarios:eliminar', args=[self.bloque.pk]))
        self.assertTrue(HorarioMateria.objects.filter(pk=self.otro.pk).exists())
        self.mat.refresh_from_db()
        self.assertTrue(self.mat.activa)

    def test_un_ciclo_cerrado_no_se_modifica(self):
        otra = asignar('HIS', 'Historia', self.grado, self.cerrado)
        vieja = bloque(otra, 1, (8, 0), (9, 0))
        respuesta = self.client.post(reverse('horarios:eliminar', args=[vieja.pk]), follow=True)
        self.assertContains(respuesta, 'está cerrado')
        self.assertTrue(HorarioMateria.objects.filter(pk=vieja.pk).exists())

    def test_bloque_inexistente_da_404(self):
        self.assertEqual(self.client.post(reverse('horarios:eliminar', args=[9999])).status_code, 404)
