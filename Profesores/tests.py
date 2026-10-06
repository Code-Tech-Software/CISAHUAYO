import csv
import io
from datetime import date, time, timedelta

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from Alumnos.models import Grado, HorarioMateria, Materia, MateriaGrado, Profesor
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    ciclo_cerrado_de_prueba,
    crear_grado,
    crear_profesor,
    hoy,
)


def crear_materia(clave='MAT', nombre='Matemáticas', **cambios):
    return Materia.objects.create(clave=clave, nombre=nombre, **cambios)


def grado(nivel, numero):
    return Grado.objects.get_or_create(nivel=nivel, numero=numero)[0]


def asignar(materia, grado, ciclo, **cambios):
    return MateriaGrado.objects.create(materia=materia, grado=grado, ciclo=ciclo, **cambios)


def bloque(asignacion, dia=0, inicio=(8, 0), fin=(9, 0)):
    return HorarioMateria.objects.create(materia_grado=asignacion, dia_semana=dia, hora_inicio=time(*inicio), hora_fin=time(*fin))


def datos_profesor(**cambios):
    datos = {
        'nombre': 'Ana', 'apellido_paterno': 'Lara', 'apellido_materno': 'Ruiz', 'telefono': '353 111 2233',
        'curp': '', 'correo_electronico': '', 'fecha_nacimiento': '', 'fecha_ingreso': '',
    }
    datos.update(cambios)
    return datos


# ---------------------------------------------------------------------------
# Permisos
# ---------------------------------------------------------------------------
@PRUEBAS
class PermisosTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.profesor = crear_profesor()
        self.asignacion = asignar(crear_materia(), crear_grado(), ciclo_actual_de_prueba())

    def paginas(self):
        return (('lista', []), ('crear', []), ('exportar', []), ('detalle', [self.profesor.pk]), ('editar', [self.profesor.pk]))

    def acciones(self):
        return (('baja', [self.profesor.pk]), ('reactivar', [self.profesor.pk]), ('asignar', []))

    def test_anonimo_es_enviado_al_login(self):
        self.client.logout()
        for nombre, args in self.paginas():
            respuesta = self.client.get(reverse(f'profesores:{nombre}', args=args))
            self.assertEqual(respuesta.status_code, 302, nombre)
            self.assertIn('/admin/login/', respuesta['Location'])

    def test_sin_permisos_recibe_403(self):
        self.client.force_login(self.sin_permisos)
        for nombre, args in self.paginas():
            self.assertEqual(self.client.get(reverse(f'profesores:{nombre}', args=args)).status_code, 403, nombre)
        for nombre, args in self.acciones():
            self.assertEqual(self.client.post(reverse(f'profesores:{nombre}', args=args)).status_code, 403, nombre)
        self.profesor.refresh_from_db()
        self.assertEqual(self.profesor.estatus, 'ACTIVO')

    def test_las_acciones_solo_aceptan_post(self):
        for nombre, args in self.acciones():
            self.assertEqual(self.client.get(reverse(f'profesores:{nombre}', args=args)).status_code, 405, nombre)

    def test_cada_accion_pide_su_permiso(self):
        self.con_permisos('view_profesor')
        self.assertEqual(self.client.get(reverse('profesores:lista')).status_code, 200)
        self.assertEqual(self.client.get(reverse('profesores:detalle', args=[self.profesor.pk])).status_code, 200)
        for nombre, args in (('crear', []), ('editar', [self.profesor.pk])):
            self.assertEqual(self.client.get(reverse(f'profesores:{nombre}', args=args)).status_code, 403, nombre)
        self.assertEqual(self.client.post(reverse('profesores:baja', args=[self.profesor.pk])).status_code, 403)
        self.con_permisos('view_profesor', 'add_profesor')
        self.assertEqual(self.client.get(reverse('profesores:crear')).status_code, 200)
        self.con_permisos('view_profesor', 'change_profesor')
        self.assertEqual(self.client.get(reverse('profesores:editar', args=[self.profesor.pk])).status_code, 200)
        self.assertEqual(self.client.post(reverse('profesores:reactivar', args=[self.profesor.pk])).status_code, 302)

    def test_asignar_pide_cambiar_la_asignacion_y_dar_de_baja_pide_borrar(self):
        self.con_permisos('view_profesor', 'change_profesor')
        self.assertEqual(self.client.post(reverse('profesores:asignar'), {'asignacion': self.asignacion.pk, 'profesor': self.profesor.pk}).status_code, 403)
        self.assertEqual(self.client.post(reverse('profesores:baja', args=[self.profesor.pk])).status_code, 403)
        self.con_permisos('change_materiagrado')
        self.assertEqual(self.client.post(reverse('profesores:asignar'), {'asignacion': self.asignacion.pk, 'profesor': self.profesor.pk}).status_code, 302)
        self.con_permisos('delete_profesor')
        self.assertEqual(self.client.post(reverse('profesores:baja', args=[self.profesor.pk])).status_code, 302)

    def test_los_botones_de_asignar_dependen_del_permiso(self):
        self.con_permisos('view_profesor', 'view_materia', 'view_materiagrado')
        ciclo = self.asignacion.ciclo
        materia = self.asignacion.materia
        respuesta = self.client.get(reverse('materias:detalle', args=[materia.pk]), {'ciclo': ciclo.pk})
        self.assertNotContains(respuesta, 'data-asignar-profesor')
        self.con_permisos('view_profesor', 'view_materia', 'view_materiagrado', 'change_materiagrado')
        respuesta = self.client.get(reverse('materias:detalle', args=[materia.pk]), {'ciclo': ciclo.pk})
        self.assertContains(respuesta, 'data-asignar-profesor')


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------
@PRUEBAS
class ListaTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.marta = crear_profesor(nombre='Marta', apellido_paterno='Rangel', telefono='3531000001', correo_electronico='marta@escuela.mx',
                                    especialidad='Matemáticas')
        self.beto = crear_profesor(nombre='Beto', apellido_paterno='Aguilar', telefono='3531000002', especialidad='Inglés')
        self.vieja = crear_profesor(nombre='Vieja', apellido_paterno='Zepeda', telefono='3531000003', estatus='INACTIVO')
        self.mat = crear_materia('MAT', 'Matemáticas')
        self.asignacion = asignar(self.mat, crear_grado('PRIMARIA', 1), self.ciclo, profesor=self.marta)
        bloque(self.asignacion, 0, (8, 0), (9, 30))

    def pedir(self, **parametros):
        return self.client.get(reverse('profesores:lista'), parametros)

    def nombres(self, respuesta):
        return [str(p) for p in respuesta.context['pagina']]

    def test_por_defecto_solo_los_activos_por_apellido(self):
        self.assertEqual(self.nombres(self.pedir()), ['Beto Aguilar Soto', 'Marta Rangel Soto'])

    def test_las_bajas_se_ven_en_su_filtro(self):
        respuesta = self.pedir(estatus='INACTIVO')
        self.assertEqual(self.nombres(respuesta), ['Vieja Zepeda Soto'])
        self.assertTrue(respuesta.context['viendo_bajas'])
        self.assertContains(respuesta, 'Reactivar')

    def test_conteos_de_las_pestanas(self):
        respuesta = self.pedir()
        self.assertEqual((respuesta.context['total_activos'], respuesta.context['total_bajas']), (2, 1))

    def test_busca_por_nombre_telefono_correo_especialidad_y_materia(self):
        for texto, esperado in (('marta', ['Marta Rangel Soto']), ('3531000002', ['Beto Aguilar Soto']), ('escuela.mx', ['Marta Rangel Soto']),
                                ('inglés', ['Beto Aguilar Soto']), ('matem', ['Marta Rangel Soto']), ('zzz', [])):
            self.assertEqual(self.nombres(self.pedir(q=texto)), esperado, texto)

    def test_buscar_por_materia_no_duplica_al_profesor(self):
        asignar(crear_materia('MAT2', 'Matemáticas II'), crear_grado('PRIMARIA', 2), self.ciclo, profesor=self.marta)
        self.assertEqual(self.nombres(self.pedir(q='matem')), ['Marta Rangel Soto'])

    def test_filtra_por_situacion_en_el_ciclo_actual(self):
        self.assertEqual(self.nombres(self.pedir(situacion='con_materias')), ['Marta Rangel Soto'])
        self.assertEqual(self.nombres(self.pedir(situacion='sin_materias')), ['Beto Aguilar Soto'])

    def test_la_situacion_ignora_materias_quitadas_y_de_otros_ciclos(self):
        self.asignacion.activa = False
        self.asignacion.save()
        asignar(crear_materia('OLD', 'Antigua'), crear_grado('PRIMARIA', 3), ciclo_cerrado_de_prueba(), profesor=self.beto)
        self.assertEqual(self.nombres(self.pedir(situacion='con_materias')), [])

    def test_muestra_las_materias_y_la_carga_semanal_del_ciclo_actual(self):
        respuesta = self.pedir()
        marta = next(p for p in respuesta.context['pagina'] if p.pk == self.marta.pk)
        self.assertEqual((marta.materias, marta.duracion), (1, '1 h 30 min'))
        beto = next(p for p in respuesta.context['pagina'] if p.pk == self.beto.pk)
        self.assertEqual((beto.materias, beto.duracion), (0, ''))

    def test_sin_ciclo_actual_no_falla(self):
        self.ciclo.activo = False
        self.ciclo.save()
        respuesta = self.pedir()
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(self.nombres(respuesta), ['Beto Aguilar Soto', 'Marta Rangel Soto'])

    def test_ordena(self):
        self.assertEqual(self.nombres(self.pedir(orden='-nombre')), ['Marta Rangel Soto', 'Beto Aguilar Soto'])

    def test_pagina_y_tamano(self):
        for i in range(26):
            crear_profesor(nombre=f'Prof{i:02d}', apellido_paterno='Zeta', telefono=f'35320000{i:02d}')
        respuesta = self.pedir()
        self.assertEqual(respuesta.context['pagina'].paginator.count, 28)
        self.assertEqual(len(respuesta.context['pagina']), 20)
        self.assertEqual(len(self.pedir(page=2).context['pagina']), 8)
        self.assertEqual(self.pedir(por_pagina=7).context['por_pagina'], 20)

    def test_consultas_constantes(self):
        with CaptureQueriesContext(connection) as pocas:
            self.pedir(por_pagina=10)
        for i in range(25):
            profesor = crear_profesor(nombre=f'Prof{i:02d}', apellido_paterno='Zeta', telefono=f'35320000{i:02d}')
            bloque(asignar(crear_materia(f'X{i:02d}', f'Otra {i:02d}'), grado('SECUNDARIA', 1 + i % 3), self.ciclo, profesor=profesor), i % 5)
        with CaptureQueriesContext(connection) as muchas:
            self.pedir(por_pagina=50)
        self.assertLessEqual(len(muchas), len(pocas))

    def test_estados_vacios(self):
        MateriaGrado.objects.all().delete()
        Profesor.objects.all().delete()
        self.assertContains(self.pedir(), 'Aún no hay profesores registrados')
        self.assertContains(self.pedir(estatus='INACTIVO'), 'No hay profesores dados de baja')
        self.assertContains(self.pedir(q='zzz'), 'No encontramos profesores')

    def test_parametros_invalidos_se_ignoran(self):
        self.assertEqual(self.pedir(estatus='XX', orden='raro', situacion='nada', page='abc').status_code, 200)


# ---------------------------------------------------------------------------
# Alta
# ---------------------------------------------------------------------------
@PRUEBAS
class CrearTests(BaseTestCase):
    url = property(lambda self: reverse('profesores:crear'))

    def test_el_formulario_se_muestra_con_los_campos_con_estilo(self):
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 200)
        for nombre, campo in respuesta.context['form'].fields.items():
            self.assertIn('field__control', campo.widget.attrs.get('class', ''), nombre)

    def test_registra_y_vuelve_al_listado_con_mensaje(self):
        respuesta = self.client.post(self.url, datos_profesor(), follow=True)
        self.assertRedirects(respuesta, reverse('profesores:lista'))
        self.assertContains(respuesta, 'Ana Lara Ruiz fue registrado correctamente')
        profesor = Profesor.objects.get()
        self.assertEqual((profesor.telefono, profesor.estatus), ('3531112233', 'ACTIVO'))

    def test_normaliza_los_datos(self):
        self.client.post(self.url, datos_profesor(
            nombre='  ana   maría ', curp=' lara800101hmnrzn09 ', correo_electronico='  ANA@Escuela.MX ', cedula_profesional=' ab 123 ',
        ))
        profesor = Profesor.objects.get()
        self.assertEqual(profesor.nombre, 'ana maría')
        self.assertEqual(profesor.curp, 'LARA800101HMNRZN09')
        self.assertEqual(profesor.correo_electronico, 'ana@escuela.mx')
        self.assertEqual(profesor.cedula_profesional, 'AB 123')

    def test_curp_y_correo_opcionales_no_chocan_entre_profesores(self):
        self.client.post(self.url, datos_profesor())
        self.client.post(self.url, datos_profesor(nombre='Rosa', telefono='3539998877'))
        self.assertEqual(Profesor.objects.count(), 2)
        self.assertEqual(Profesor.objects.filter(curp__isnull=True, correo_electronico__isnull=True).count(), 2)

    def test_campos_obligatorios(self):
        respuesta = self.client.post(self.url, {})
        self.assertEqual(set(respuesta.context['form'].errors), {'nombre', 'apellido_paterno', 'telefono'})
        self.assertFalse(Profesor.objects.exists())

    def test_telefono_invalido(self):
        for telefono in ('123', 'abcdefghij', '12345678901234'):
            respuesta = self.client.post(self.url, datos_profesor(telefono=telefono))
            self.assertIn('telefono', respuesta.context['form'].errors, telefono)

    def test_telefono_alternativo_se_valida_solo_si_se_captura(self):
        respuesta = self.client.post(self.url, datos_profesor(telefono_alternativo='12'))
        self.assertIn('telefono_alternativo', respuesta.context['form'].errors)
        respuesta = self.client.post(self.url, datos_profesor(telefono_alternativo=''))
        self.assertEqual(respuesta.status_code, 302)

    def test_curp_invalida_o_repetida(self):
        respuesta = self.client.post(self.url, datos_profesor(curp='ABC'))
        self.assertIn('curp', respuesta.context['form'].errors)
        crear_profesor(curp='LARA800101HMNRZN09', telefono='3530000000')
        respuesta = self.client.post(self.url, datos_profesor(curp='lara800101hmnrzn09'))
        self.assertIn('curp', respuesta.context['form'].errors)

    def test_correo_invalido_o_repetido(self):
        respuesta = self.client.post(self.url, datos_profesor(correo_electronico='no-es-correo'))
        self.assertIn('correo_electronico', respuesta.context['form'].errors)
        crear_profesor(correo_electronico='ana@escuela.mx', telefono='3530000000')
        respuesta = self.client.post(self.url, datos_profesor(correo_electronico='ANA@escuela.mx'))
        self.assertIn('correo_electronico', respuesta.context['form'].errors)

    def test_edad_y_fechas(self):
        futura = (hoy() + timedelta(days=2)).isoformat()
        menor = (hoy() - timedelta(days=365 * 15)).isoformat()
        adulto = date(hoy().year - 30, 6, 15).isoformat()
        self.assertIn('fecha_nacimiento', self.client.post(self.url, datos_profesor(fecha_nacimiento=futura)).context['form'].errors)
        self.assertIn('fecha_nacimiento', self.client.post(self.url, datos_profesor(fecha_nacimiento=menor)).context['form'].errors)
        self.assertIn('fecha_ingreso', self.client.post(self.url, datos_profesor(fecha_ingreso=futura)).context['form'].errors)
        self.assertEqual(self.client.post(self.url, datos_profesor(fecha_nacimiento=adulto, fecha_ingreso=hoy().isoformat())).status_code, 302)

    def test_codigo_postal(self):
        self.assertIn('cp', self.client.post(self.url, datos_profesor(cp='123')).context['form'].errors)
        self.assertEqual(self.client.post(self.url, datos_profesor(cp='59000')).status_code, 302)

    def test_el_error_conserva_lo_capturado(self):
        respuesta = self.client.post(self.url, datos_profesor(telefono='1', nombre='Conservado'))
        self.assertContains(respuesta, 'Conservado')
        self.assertContains(respuesta, 'Revisa los campos marcados')


# ---------------------------------------------------------------------------
# Edición
# ---------------------------------------------------------------------------
@PRUEBAS
class EditarTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.profesor = crear_profesor(curp='LARA800101HMNRZN09', correo_electronico='marta@escuela.mx')
        self.otro = crear_profesor(nombre='Otro', curp='OTRO800101HMNRZN09', correo_electronico='otro@escuela.mx', telefono='3530000009')
        self.url = reverse('profesores:editar', args=[self.profesor.pk])

    def datos(self, **cambios):
        return datos_profesor(
            nombre='Marta', apellido_paterno='Rangel', apellido_materno='Soto', telefono='3534445566',
            curp='LARA800101HMNRZN09', correo_electronico='marta@escuela.mx', **cambios,
        )

    def test_formulario_precargado(self):
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.context['form'].initial['nombre'], 'Marta')
        self.assertContains(respuesta, 'marta@escuela.mx')

    def test_actualiza_y_vuelve_al_listado(self):
        respuesta = self.client.post(self.url, self.datos(especialidad='Ciencias'), follow=True)
        self.assertRedirects(respuesta, reverse('profesores:lista'))
        self.assertContains(respuesta, 'se actualizaron')
        self.profesor.refresh_from_db()
        self.assertEqual(self.profesor.especialidad, 'Ciencias')

    def test_conserva_su_propia_curp_y_correo(self):
        self.assertEqual(self.client.post(self.url, self.datos()).status_code, 302)

    def test_no_permite_la_curp_ni_el_correo_de_otro(self):
        respuesta = self.client.post(self.url, self.datos(**{}) | {'curp': 'OTRO800101HMNRZN09', 'correo_electronico': 'otro@escuela.mx'})
        self.assertEqual(set(respuesta.context['form'].errors), {'curp', 'correo_electronico'})

    def test_editar_no_cambia_el_estatus(self):
        self.profesor.estatus = 'INACTIVO'
        self.profesor.save()
        self.client.post(self.url, self.datos() | {'estatus': 'ACTIVO'})
        self.profesor.refresh_from_db()
        self.assertEqual(self.profesor.estatus, 'INACTIVO')

    def test_profesor_inexistente_da_404(self):
        self.assertEqual(self.client.get(reverse('profesores:editar', args=[9999])).status_code, 404)


# ---------------------------------------------------------------------------
# Perfil
# ---------------------------------------------------------------------------
@PRUEBAS
class DetalleTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.actual = ciclo_actual_de_prueba()
        self.cerrado = ciclo_cerrado_de_prueba()
        self.profesor = crear_profesor()
        self.mat, self.esp = crear_materia('MAT', 'Matemáticas'), crear_materia('ESP', 'Español')
        self.p1, self.p2 = crear_grado('PRIMARIA', 1), crear_grado('PRIMARIA', 2)
        self.a1 = asignar(self.mat, self.p1, self.actual, profesor=self.profesor)
        self.a2 = asignar(self.esp, self.p2, self.actual, profesor=self.profesor)
        self.vieja = asignar(self.mat, self.p1, self.cerrado, profesor=self.profesor)
        bloque(self.a1, 0, (8, 0), (9, 0))
        bloque(self.a1, 2, (8, 0), (9, 0))
        bloque(self.a2, 1, (10, 0), (10, 30))

    def detalle(self, **parametros):
        return self.client.get(reverse('profesores:detalle', args=[self.profesor.pk]), parametros)

    def test_muestra_sus_materias_del_ciclo_actual_y_su_carga(self):
        respuesta = self.detalle()
        self.assertEqual(respuesta.context['ciclo'], self.actual)
        self.assertEqual([a.materia.clave for a in respuesta.context['asignaciones']], ['MAT', 'ESP'])   # orden escolar: 1° y luego 2°
        self.assertEqual(respuesta.context['total_grados'], 2)
        self.assertEqual(respuesta.context['total_bloques'], 3)
        self.assertEqual(respuesta.context['horas_semanales'], '2 h 30 min')

    def test_el_horario_semanal_junta_los_bloques_de_todos_sus_grados(self):
        cuadricula = self.detalle().context['cuadricula']
        self.assertEqual([(f['inicio'], f['fin']) for f in cuadricula['filas']], [(time(8, 0), time(9, 0)), (time(10, 0), time(10, 30))])
        self.assertContains(self.detalle(), 'Matemáticas')

    def test_elige_otro_ciclo(self):
        respuesta = self.detalle(ciclo=self.cerrado.pk)
        self.assertEqual(respuesta.context['ciclo'], self.cerrado)
        self.assertEqual([a.pk for a in respuesta.context['asignaciones']], [self.vieja.pk])

    def test_un_ciclo_cerrado_es_de_solo_lectura(self):
        respuesta = self.detalle(ciclo=self.cerrado.pk)
        self.assertFalse(respuesta.context['editable'])
        self.assertNotContains(respuesta, 'modal-asignar-materias')

    def test_ofrece_las_materias_sin_profesor_agrupadas_por_grado(self):
        libre = asignar(crear_materia('CIE', 'Ciencias'), self.p1, self.actual)
        respuesta = self.detalle()
        self.assertEqual(respuesta.context['total_pendientes'], 1)
        self.assertEqual([(str(g['grado']), [a.pk for a in g['asignaciones']]) for g in respuesta.context['pendientes']], [('1° Primaria', [libre.pk])])
        self.assertContains(respuesta, 'modal-asignar-materias')

    def test_no_ofrece_materias_quitadas_ni_de_baja_ni_de_grados_de_baja(self):
        asignar(crear_materia('A', 'Quitada'), self.p1, self.actual, activa=False)
        asignar(crear_materia('B', 'De baja', activa=False), self.p1, self.actual)
        asignar(crear_materia('C', 'Grado de baja'), crear_grado('PRIMARIA', 6, activo=False), self.actual)
        self.assertEqual(self.detalle().context['total_pendientes'], 0)

    def test_un_profesor_de_baja_no_es_editable_y_ofrece_reactivar(self):
        self.profesor.estatus = 'INACTIVO'
        self.profesor.save()
        respuesta = self.detalle()
        self.assertTrue(respuesta.context['esta_de_baja'])
        self.assertFalse(respuesta.context['editable'])
        self.assertContains(respuesta, 'Reactivar profesor')
        self.assertEqual(respuesta.context['asignaciones_actuales'], 0)

    def test_no_hay_ciclos(self):
        MateriaGrado.objects.all().delete()
        self.actual.delete()
        self.cerrado.delete()
        respuesta = self.detalle()
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Aún no hay ciclos escolares')

    def test_sin_materias_en_el_ciclo(self):
        MateriaGrado.objects.filter(ciclo=self.actual).delete()
        respuesta = self.detalle()
        self.assertContains(respuesta, 'No imparte materias en este ciclo')
        self.assertContains(respuesta, 'Todavía no tiene horario')

    def test_consultas_constantes(self):
        with CaptureQueriesContext(connection) as pocas:
            self.detalle()
        for numero in range(3, 8):
            asignacion = asignar(self.mat, crear_grado('PRIMARIA', numero), self.actual, profesor=self.profesor)
            bloque(asignacion, 3, (11, 0), (11, 30))
            asignar(crear_materia(f'L{numero}', f'Libre {numero}'), crear_grado('SECUNDARIA', numero - 2), self.actual)
        with CaptureQueriesContext(connection) as muchas:
            self.detalle()
        self.assertEqual(len(muchas), len(pocas))

    def test_profesor_inexistente_da_404(self):
        self.assertEqual(self.client.get(reverse('profesores:detalle', args=[9999])).status_code, 404)


# ---------------------------------------------------------------------------
# Baja lógica y reactivación
# ---------------------------------------------------------------------------
@PRUEBAS
class BajaTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.actual = ciclo_actual_de_prueba()
        self.cerrado = ciclo_cerrado_de_prueba()
        self.profesor = crear_profesor()
        self.mat = crear_materia()
        self.p1, self.p2 = crear_grado('PRIMARIA', 1), crear_grado('PRIMARIA', 2)
        self.a1 = asignar(self.mat, self.p1, self.actual, profesor=self.profesor)
        self.a2 = asignar(self.mat, self.p2, self.actual, profesor=self.profesor)
        self.vieja = asignar(self.mat, self.p1, self.cerrado, profesor=self.profesor)
        bloque(self.a1)

    def baja(self, datos=None, **extra):
        return self.client.post(reverse('profesores:baja', args=[self.profesor.pk]), datos or {}, **extra)

    def test_da_de_baja_vuelve_al_listado_y_confirma(self):
        respuesta = self.baja(follow=True)
        self.assertRedirects(respuesta, reverse('profesores:lista'))
        self.assertContains(respuesta, 'Marta Rangel Soto fue dado de baja')
        self.profesor.refresh_from_db()
        self.assertEqual(self.profesor.estatus, 'INACTIVO')

    def test_no_borra_nada_y_conserva_sus_materias_si_no_se_pide(self):
        self.baja()
        self.assertTrue(Profesor.objects.filter(pk=self.profesor.pk).exists())
        self.assertEqual(MateriaGrado.objects.filter(profesor=self.profesor).count(), 3)
        self.assertEqual(HorarioMateria.objects.count(), 1)

    def test_puede_dejar_sin_profesor_las_materias_del_ciclo_actual(self):
        respuesta = self.baja({'quitar_del_ciclo': 'on'}, follow=True)
        self.assertContains(respuesta, 'Sus 2 materias del ciclo actual quedaron sin profesor')
        self.assertEqual(MateriaGrado.objects.filter(ciclo=self.actual, profesor__isnull=True).count(), 2)
        self.vieja.refresh_from_db()
        self.assertEqual(self.vieja.profesor, self.profesor)             # el historial de ciclos cerrados no se toca
        self.assertEqual(HorarioMateria.objects.count(), 1)              # el horario de la materia se conserva

    def test_dar_de_baja_dos_veces_es_inofensivo(self):
        self.baja()
        self.assertContains(self.baja(follow=True), 'ya estaba dado de baja')

    def test_reactivar_no_devuelve_las_materias(self):
        self.baja({'quitar_del_ciclo': 'on'})
        respuesta = self.client.post(reverse('profesores:reactivar', args=[self.profesor.pk]), follow=True)
        self.assertRedirects(respuesta, reverse('profesores:lista'))
        self.assertContains(respuesta, 'fue reactivado')
        self.profesor.refresh_from_db()
        self.assertEqual(self.profesor.estatus, 'ACTIVO')
        self.assertEqual(MateriaGrado.objects.filter(ciclo=self.actual, profesor=self.profesor).count(), 0)

    def test_reactivar_a_un_activo_no_cambia_nada(self):
        respuesta = self.client.post(reverse('profesores:reactivar', args=[self.profesor.pk]), follow=True)
        self.assertNotContains(respuesta, 'fue reactivado')

    def test_un_profesor_de_baja_ya_no_se_ofrece_al_asignar(self):
        self.baja()
        respuesta = self.client.get(reverse('materias:detalle', args=[self.mat.pk]), {'ciclo': self.actual.pk})
        self.assertNotIn(self.profesor, respuesta.context['profesores_activos'])

    def test_profesor_inexistente_da_404(self):
        self.assertEqual(self.client.post(reverse('profesores:baja', args=[9999])).status_code, 404)
        self.assertEqual(self.client.post(reverse('profesores:reactivar', args=[9999])).status_code, 404)


# ---------------------------------------------------------------------------
# Asignar o quitar al profesor de una o varias materias
# ---------------------------------------------------------------------------
@PRUEBAS
class AsignarTests(BaseTestCase):
    url = property(lambda self: reverse('profesores:asignar'))

    def setUp(self):
        super().setUp()
        self.actual = ciclo_actual_de_prueba()
        self.cerrado = ciclo_cerrado_de_prueba()
        self.profesor = crear_profesor()
        self.p1, self.p2 = crear_grado('PRIMARIA', 1), crear_grado('PRIMARIA', 2)
        self.mat, self.esp = crear_materia('MAT', 'Matemáticas'), crear_materia('ESP', 'Español')
        self.a1 = asignar(self.mat, self.p1, self.actual)
        self.a2 = asignar(self.esp, self.p2, self.actual)

    def post(self, asignaciones, profesor='', **extra):
        datos = {'asignacion': [a.pk for a in asignaciones], 'profesor': profesor.pk if hasattr(profesor, 'pk') else profesor}
        datos.update(extra)
        return self.client.post(self.url, datos)

    def test_asigna_una_materia(self):
        respuesta = self.post([self.a1], self.profesor, next=reverse('grados:detalle', args=[self.p1.pk]))
        self.assertRedirects(respuesta, reverse('grados:detalle', args=[self.p1.pk]), fetch_redirect_response=False)
        self.a1.refresh_from_db()
        self.assertEqual(self.a1.profesor, self.profesor)

    def test_confirma_con_un_mensaje(self):
        respuesta = self.client.post(self.url, {'asignacion': [self.a1.pk], 'profesor': self.profesor.pk}, follow=True)
        self.assertContains(respuesta, 'Marta Rangel Soto imparte ahora Matemáticas en 1° Primaria')

    def test_asigna_varias_materias_a_la_vez(self):
        respuesta = self.client.post(self.url, {'asignacion': [self.a1.pk, self.a2.pk], 'profesor': self.profesor.pk}, follow=True)
        self.assertContains(respuesta, 'imparte ahora 2 materias más')
        self.assertEqual(MateriaGrado.objects.filter(profesor=self.profesor).count(), 2)

    def test_cambia_de_profesor(self):
        otro = crear_profesor(nombre='Otro', telefono='3530000009')
        self.a1.profesor = otro
        self.a1.save()
        self.post([self.a1], self.profesor)
        self.a1.refresh_from_db()
        self.assertEqual(self.a1.profesor, self.profesor)

    def test_quita_al_profesor(self):
        self.a1.profesor = self.profesor
        self.a1.save()
        respuesta = self.client.post(self.url, {'asignacion': [self.a1.pk], 'profesor': ''}, follow=True)
        self.assertContains(respuesta, 'Se quitó al profesor de 1 materia')
        self.a1.refresh_from_db()
        self.assertIsNone(self.a1.profesor)

    def test_si_ya_lo_tenia_avisa_sin_cambiar_nada(self):
        self.a1.profesor = self.profesor
        self.a1.save()
        respuesta = self.client.post(self.url, {'asignacion': [self.a1.pk], 'profesor': self.profesor.pk}, follow=True)
        self.assertContains(respuesta, 'No hubo cambios')

    def test_no_asigna_a_un_profesor_de_baja_ni_inexistente(self):
        self.profesor.estatus = 'INACTIVO'
        self.profesor.save()
        for valor in (self.profesor.pk, 9999, 'x'):
            respuesta = self.client.post(self.url, {'asignacion': [self.a1.pk], 'profesor': valor}, follow=True)
            self.assertContains(respuesta, 'Elige un profesor activo', msg_prefix=str(valor))
        self.a1.refresh_from_db()
        self.assertIsNone(self.a1.profesor)

    def test_exige_al_menos_una_materia(self):
        respuesta = self.client.post(self.url, {'profesor': self.profesor.pk}, follow=True)
        self.assertContains(respuesta, 'Elige al menos una materia')

    def test_un_ciclo_cerrado_no_se_modifica(self):
        vieja = asignar(self.mat, self.p1, self.cerrado)
        respuesta = self.client.post(self.url, {'asignacion': [vieja.pk], 'profesor': self.profesor.pk}, follow=True)
        self.assertContains(respuesta, 'está cerrado')
        vieja.refresh_from_db()
        self.assertIsNone(vieja.profesor)

    def test_no_asigna_materias_quitadas_del_grado(self):
        self.a1.activa = False
        self.a1.save()
        respuesta = self.client.post(self.url, {'asignacion': [self.a1.pk], 'profesor': self.profesor.pk}, follow=True)
        self.assertContains(respuesta, 'ya no se imparte en ese grado')
        self.a1.refresh_from_db()
        self.assertIsNone(self.a1.profesor)

    def test_un_profesor_no_puede_estar_en_dos_grupos_a_la_vez(self):
        bloque(self.a1, 0, (8, 0), (9, 0))
        bloque(self.a2, 0, (8, 30), (9, 30))
        self.a1.profesor = self.profesor
        self.a1.save()
        respuesta = self.client.post(self.url, {'asignacion': [self.a2.pk], 'profesor': self.profesor.pk}, follow=True)
        self.assertContains(respuesta, 'No se pudo asignar')
        self.assertContains(respuesta, 'un profesor no puede estar en dos grupos a la vez')
        self.assertContains(respuesta, 'Matemáticas en 1° Primaria (lunes 08:00–09:00)')
        self.a2.refresh_from_db()
        self.assertIsNone(self.a2.profesor)

    def test_horas_que_solo_se_tocan_no_se_empalman(self):
        bloque(self.a1, 0, (8, 0), (9, 0))
        bloque(self.a2, 0, (9, 0), (10, 0))
        self.a1.profesor = self.profesor
        self.a1.save()
        self.post([self.a2], self.profesor)
        self.a2.refresh_from_db()
        self.assertEqual(self.a2.profesor, self.profesor)

    def test_el_mismo_horario_en_otro_dia_o_en_otro_ciclo_no_estorba(self):
        bloque(self.a1, 0, (8, 0), (9, 0))
        bloque(self.a2, 1, (8, 0), (9, 0))
        vieja = asignar(self.mat, self.p1, self.cerrado, profesor=self.profesor)
        bloque(vieja, 1, (8, 0), (9, 0))
        self.a1.profesor = self.profesor
        self.a1.save()
        self.post([self.a2], self.profesor)
        self.a2.refresh_from_db()
        self.assertEqual(self.a2.profesor, self.profesor)

    def test_una_materia_quitada_no_cuenta_para_los_empalmes(self):
        quitada = asignar(crear_materia('QUI', 'Quitada'), self.p1, self.actual, profesor=self.profesor, activa=False)
        bloque(quitada, 0, (8, 0), (9, 0))
        bloque(self.a2, 0, (8, 0), (9, 0))
        self.post([self.a2], self.profesor)
        self.a2.refresh_from_db()
        self.assertEqual(self.a2.profesor, self.profesor)

    def test_si_unas_se_pueden_y_otras_no_se_guardan_las_posibles_y_se_avisa(self):
        bloque(self.a1, 0, (8, 0), (9, 0))
        libre = asignar(crear_materia('CIE', 'Ciencias'), self.p2, self.actual)
        bloque(libre, 0, (8, 30), (9, 30))                        # se empalma con a1 si ambas fueran suyas
        ocupada = asignar(crear_materia('HIS', 'Historia'), crear_grado('PRIMARIA', 3), self.actual)
        self.a1.profesor = self.profesor
        self.a1.save()
        respuesta = self.client.post(self.url, {'asignacion': [libre.pk, ocupada.pk], 'profesor': self.profesor.pk}, follow=True)
        libre.refresh_from_db()
        ocupada.refresh_from_db()
        self.assertIsNone(libre.profesor)
        self.assertEqual(ocupada.profesor, self.profesor)
        self.assertContains(respuesta, 'imparte ahora 1 materia más')
        self.assertContains(respuesta, 'Ciencias de 2° Primaria')

    def test_quitar_al_profesor_no_revisa_empalmes(self):
        bloque(self.a1, 0, (8, 0), (9, 0))
        self.a1.profesor = self.profesor
        self.a1.save()
        self.post([self.a1], '')
        self.a1.refresh_from_db()
        self.assertIsNone(self.a1.profesor)

    def test_ignora_valores_que_no_son_numeros(self):
        respuesta = self.client.post(self.url, {'asignacion': ['x', '', str(self.a1.pk)], 'profesor': self.profesor.pk})
        self.assertEqual(respuesta.status_code, 302)
        self.a1.refresh_from_db()
        self.assertEqual(self.a1.profesor, self.profesor)

    def test_el_next_solo_acepta_direcciones_de_este_sitio(self):
        for peligroso in ('https://malo.example/', '//malo.example/', 'javascript:alert(1)'):
            respuesta = self.post([self.a1], self.profesor, next=peligroso)
            self.assertRedirects(respuesta, reverse('profesores:lista'), fetch_redirect_response=False, msg_prefix=peligroso)

    def test_inicial_sin_destino_vuelve_al_listado(self):
        self.assertRedirects(self.post([self.a1], self.profesor), reverse('profesores:lista'), fetch_redirect_response=False)


# ---------------------------------------------------------------------------
# Exportación
# ---------------------------------------------------------------------------
@PRUEBAS
class ExportarTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.actual = ciclo_actual_de_prueba()
        self.marta = crear_profesor(nombre='=Marta', apellido_paterno='Rangel', especialidad='Matemáticas')
        crear_profesor(nombre='Beto', apellido_paterno='Aguilar', telefono='3530000002')
        crear_profesor(nombre='Vieja', apellido_paterno='Zepeda', telefono='3530000003', estatus='INACTIVO')
        asignar(crear_materia('MAT', 'Matemáticas'), crear_grado('PRIMARIA', 2), self.actual, profesor=self.marta)
        asignar(crear_materia('ESP', 'Español'), crear_grado('PRIMARIA', 1), self.actual, profesor=self.marta)

    def filas(self, **filtros):
        respuesta = self.client.get(reverse('profesores:exportar'), filtros)
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('text/csv', respuesta['Content-Type'])
        self.assertIn('attachment; filename="profesores-', respuesta['Content-Disposition'])
        contenido = respuesta.content.decode('utf-8')
        self.assertTrue(contenido.startswith('﻿'))
        return list(csv.reader(io.StringIO(contenido.lstrip('﻿'))))

    def test_exporta_los_activos_con_sus_materias_en_orden_escolar(self):
        filas = self.filas()
        self.assertEqual(filas[0][:3], ['Nombre', 'Apellido paterno', 'Apellido materno'])
        self.assertIn('2026-2027', filas[0][-3])
        self.assertEqual(filas[0][-2:], ['Materias que puede impartir', 'Horas máximas por semana'])
        self.assertEqual([f[0] for f in filas[1:]], ['Beto', "'=Marta"])                 # neutraliza fórmulas de Excel
        self.assertEqual(filas[2][-3], 'Español (1° Primaria); Matemáticas (2° Primaria)')
        self.assertEqual(filas[1][-3], '')

    def test_incluye_lo_que_puede_impartir_y_su_tope_de_horas(self):
        from Alumnos.docentes import habilitar
        habilitar(self.marta, [Materia.objects.get(clave='MAT'), Materia.objects.get(clave='ESP')])
        self.marta.horas_maximas = 25
        self.marta.save()
        filas = self.filas()
        self.assertEqual(filas[2][-2:], ['Español; Matemáticas', '25'])
        self.assertEqual(filas[1][-2:], ['', ''])

    def test_respeta_los_filtros(self):
        self.assertEqual([f[0] for f in self.filas(estatus='INACTIVO')[1:]], ['Vieja'])
        self.assertEqual([f[0] for f in self.filas(situacion='sin_materias')[1:]], ['Beto'])
        self.assertEqual([f[0] for f in self.filas(q='mate')[1:]], ["'=Marta"])

    def test_consultas_constantes(self):
        with CaptureQueriesContext(connection) as pocas:
            self.filas()
        for i in range(15):
            profesor = crear_profesor(nombre=f'P{i}', telefono=f'35300001{i:02d}')
            asignar(crear_materia(f'X{i}', f'Otra {i}'), grado('SECUNDARIA', 1 + i % 3), self.actual, profesor=profesor)
        with CaptureQueriesContext(connection) as muchas:
            self.filas()
        self.assertLessEqual(len(muchas), len(pocas))
