"""Importación de tutores desde un archivo CSV (Tutores/importacion.py y sus pantallas)."""
import csv
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from Alumnos import lectura_csv
from Alumnos.models import Alumno, Tutor, TutorAlumno
from CISAHUAYO.pruebas import PRUEBAS, BaseTestCase, crear_alumno, crear_tutor, vincular

from . import importacion

CURP_TUTOR = 'LOPM850101MMNPRR03'
CURP_OTRO = 'RAMS120405HMNMRNA3'

BASICAS = ['Nombre', 'Apellido paterno', 'Teléfono']


def csv_bytes(filas, encabezados=None, separador=',', codificacion='utf-8-sig'):
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=separador)
    escritor.writerow(encabezados or BASICAS)
    escritor.writerows(filas)
    return salida.getvalue().encode(codificacion)


def archivo(contenido, nombre='tutores.csv'):
    return SimpleUploadedFile(nombre, contenido, content_type='text/csv')


def importar(filas, encabezados=None, **opciones):
    """Lee y registra las filas; devuelve el resultado."""
    return importacion.importar(importacion.leer_filas(csv_bytes(filas, encabezados, **opciones)))


# ---------------------------------------------------------------------------
# Lectura del archivo
# ---------------------------------------------------------------------------
@PRUEBAS
class LecturaDelArchivoTests(BaseTestCase):
    def test_lee_utf8_cp1252_y_punto_y_coma(self):
        for kwargs in ({}, {'codificacion': 'cp1252'}, {'separador': ';', 'codificacion': 'cp1252'}):
            filas = importacion.leer_filas(csv_bytes([['José', 'Muñoz', '353 123 4567']], **kwargs))
            self.assertEqual(filas, [(2, {'nombre': 'José', 'apellido_paterno': 'Muñoz', 'telefono': '353 123 4567'})])

    def test_reconoce_alias_y_ignora_lo_que_no_conoce(self):
        contenido = csv_bytes([['Ana', 'García', '3531234567', 'x', 'ana@example.com']], ['NOMBRE(S)', 'primer apellido', 'Celular', 'Edad', 'Correo'])
        datos = importacion.leer_filas(contenido)[0][1]
        self.assertEqual(datos, {'nombre': 'Ana', 'apellido_paterno': 'García', 'telefono': '3531234567', 'correo_electronico': 'ana@example.com'})

    def test_exige_nombre_apellido_y_telefono(self):
        with self.assertRaisesMessage(importacion.ErrorDeArchivo, 'Teléfono'):
            importacion.leer_filas(csv_bytes([['Ana', 'García']], ['Nombre', 'Apellido paterno']))

    def test_sin_filas(self):
        with self.assertRaisesMessage(importacion.ErrorDeArchivo, 'El archivo no trae tutores'):
            importacion.leer_filas(csv_bytes([]))

    def test_la_plantilla_trae_todas_las_columnas_sin_choques_y_se_lee_de_vuelta(self):
        plantilla = importacion.plantilla_csv()
        encabezados = next(csv.reader(io.StringIO(plantilla.lstrip('﻿'))))
        self.assertEqual(encabezados, [c.titulo for c in importacion.COLUMNAS])
        indice = lectura_csv.indice_de_encabezados(importacion.COLUMNAS)
        for columna in importacion.COLUMNAS:
            self.assertIs(indice[lectura_csv.clave_de_encabezado(columna.titulo)], columna)
        with self.assertRaisesMessage(importacion.ErrorDeArchivo, 'solo tiene los encabezados'):
            importacion.leer_filas(plantilla.encode('utf-8'))

    def test_lo_que_exporta_el_sistema_se_puede_volver_a_importar(self):
        crear_tutor(nombre='Rosa', apellido_paterno='Mora', telefono='3531112233', estado_civil='CASADO')
        exportado = self.client.get(reverse('tutores:exportar')).content
        filas = importacion.leer_filas(exportado)
        self.assertEqual((filas[0][1]['nombre'], filas[0][1]['telefono'], filas[0][1]['estado_civil']), ('Rosa', '3531112233', 'Casado/a'))
        resultado = importacion.importar(filas)
        self.assertEqual((len(resultado.creados), resultado.omitidos, resultado.errores), (0, 1, []))   # ya estaba: no se duplica


# ---------------------------------------------------------------------------
# Registro de las filas
# ---------------------------------------------------------------------------
@PRUEBAS
class ImportarTutoresTests(BaseTestCase):
    def test_importa_lo_indispensable(self):
        resultado = importar([['María', 'López', '353 123 4567'], ['Jorge', 'Pérez', '(353) 444-5566']])
        self.assertEqual((len(resultado.creados), resultado.errores, resultado.omitidos, resultado.vinculos), (2, [], 0, 0))
        maria = Tutor.objects.get(nombre='María')
        self.assertEqual((maria.telefono, maria.curp, maria.estatus, maria.correo_electronico), ('3531234567', None, 'ACTIVO', None))
        self.assertEqual(Tutor.objects.get(nombre='Jorge').telefono, '3534445566')

    def test_importa_todos_los_datos(self):
        encabezados = BASICAS + [
            'Apellido materno', 'CURP', 'Teléfono alternativo', 'Correo electrónico', 'Estado civil', 'Religión', 'Domicilio',
            'Colonia', 'Ciudad', 'Estado', 'CP', 'Ocupación', 'Lugar de trabajo', 'Teléfono del trabajo', 'Observaciones',
        ]
        resultado = importar([[
            '  María ', 'López', '353 123 4567', 'Ruiz', CURP_TUTOR.lower(), '3535550000', 'Maria@Example.com', 'casada', 'Católica',
            'Calle Hidalgo 123', 'Centro', 'Sahuayo', 'Michoacán', '59000', 'Maestra', 'Escuela Benito Juárez', '353 100 2000 ext. 5',
            'Llamar por la tarde',
        ]], encabezados)
        self.assertEqual(resultado.errores, [])
        tutor = Tutor.objects.get()
        self.assertEqual(
            (str(tutor), tutor.curp, tutor.telefono_alternativo, tutor.correo_electronico, tutor.estado_civil, tutor.cp, tutor.ocupacion),
            ('María López Ruiz', CURP_TUTOR, '3535550000', 'maria@example.com', 'CASADO', '59000', 'Maestra'),
        )
        self.assertEqual((tutor.domicilio, tutor.lugar_trabajo, tutor.observaciones), ('Calle Hidalgo 123', 'Escuela Benito Juárez', 'Llamar por la tarde'))

    def test_una_fila_con_errores_no_impide_registrar_las_demas(self):
        resultado = importar([['María', 'López', '353 123 4567'], ['Jorge', 'Pérez', '12345'], ['Rosa', 'Mora', '353 111 2233']])
        self.assertEqual(len(resultado.creados), 2)
        self.assertEqual(len(resultado.errores), 1)
        error = resultado.errores[0]
        self.assertEqual((error['fila'], error['persona']), (3, 'Jorge Pérez'))
        self.assertIn('Teléfono', error['motivo'])
        self.assertFalse(Tutor.objects.filter(nombre='Jorge').exists())

    def test_informa_todos_los_motivos_de_una_fila(self):
        encabezados = BASICAS + ['CURP', 'Correo electrónico', 'Estado civil']
        resultado = importar([['', 'López', 'abc', 'XYZ', 'no-es-correo', 'complicado']], encabezados)
        motivo = resultado.errores[0]['motivo']
        for texto in ('Nombre', 'Teléfono', 'CURP', 'Correo electrónico', 'Estado civil'):
            self.assertIn(texto, motivo)

    def test_estado_civil_en_varias_formas(self):
        encabezados = BASICAS + ['Estado civil']
        importar([
            ['A', 'Uno', '3530000001', 'Soltero/a'], ['B', 'Dos', '3530000002', 'viuda'],
            ['C', 'Tres', '3530000003', 'UNION LIBRE'], ['D', 'Cuatro', '3530000004', 'divorciado'],
        ], encabezados)
        self.assertEqual(
            list(Tutor.objects.order_by('nombre').values_list('estado_civil', flat=True)), ['SOLTERO', 'VIUDO', 'UNION_LIBRE', 'DIVORCIADO'],
        )

    def test_estatus_inactivo_se_registra_dado_de_baja(self):
        importar([['María', 'López', '353 123 4567', 'Inactivo']], BASICAS + ['Estatus'])
        self.assertEqual(Tutor.objects.get().estatus, 'INACTIVO')

    def test_estatus_invalido(self):
        resultado = importar([['María', 'López', '353 123 4567', 'Visitante']], BASICAS + ['Estatus'])
        self.assertIn('Estatus', resultado.errores[0]['motivo'])

    # --- tutores que ya existen ----------------------------------------------------------------
    def test_un_tutor_con_la_misma_curp_no_se_duplica(self):
        crear_tutor(nombre='María', apellido_paterno='López', telefono='3531234567', curp=CURP_TUTOR)
        resultado = importar([['Maria', 'Lopez', '353 999 8888', CURP_TUTOR]], BASICAS + ['CURP'])
        self.assertEqual((len(resultado.creados), resultado.omitidos, resultado.errores), (0, 1, []))
        self.assertEqual(Tutor.objects.count(), 1)

    def test_un_tutor_con_el_mismo_nombre_y_telefono_no_se_duplica(self):
        crear_tutor(nombre='María', apellido_paterno='López', apellido_materno='Ruiz', telefono='3531234567')
        resultado = importar([['maría', 'LÓPEZ', '(353) 123-4567', 'ruiz']], BASICAS + ['Apellido materno'])
        self.assertEqual((len(resultado.creados), resultado.omitidos), (0, 1))
        self.assertEqual(Tutor.objects.count(), 1)

    def test_personas_distintas_con_el_mismo_telefono_son_tutores_distintos(self):
        importar([['María', 'López', '353 123 4567'], ['Jorge', 'Pérez', '353 123 4567']])
        self.assertEqual(Tutor.objects.count(), 2)

    def test_una_curp_repetida_en_el_archivo_se_registra_una_sola_vez(self):
        resultado = importar([['María', 'López', '353 123 4567', CURP_TUTOR], ['María', 'López', '353 123 4567', CURP_TUTOR]], BASICAS + ['CURP'])
        self.assertEqual((len(resultado.creados), resultado.omitidos), (1, 1))

    def test_volver_a_cargar_el_mismo_archivo_no_duplica_nada(self):
        crear_alumno(referencia='8888')
        filas = [['María', 'López', '353 123 4567', '8888', 'Madre']]
        encabezados = BASICAS + ['Referencia del estudiante', 'Parentesco']
        importar(filas, encabezados)
        segunda = importar(filas, encabezados)
        self.assertEqual((len(segunda.creados), segunda.ampliados, segunda.omitidos, segunda.errores), (0, 0, 1, []))
        self.assertEqual((Tutor.objects.count(), TutorAlumno.objects.count()), (1, 1))

    def test_un_tutor_dado_de_baja_no_se_vincula(self):
        crear_alumno(referencia='8888')
        crear_tutor(nombre='María', apellido_paterno='López', telefono='3531234567', estatus='INACTIVO')
        encabezados = BASICAS + ['Referencia del estudiante', 'Parentesco']
        resultado = importar([['María', 'López', '353 123 4567', '8888', 'Madre']], encabezados)
        self.assertIn('dado de baja', resultado.errores[0]['motivo'])
        self.assertFalse(TutorAlumno.objects.exists())

    # --- vínculos con estudiantes ------------------------------------------------------------------
    def test_vincula_a_los_estudiantes_por_referencia_o_curp(self):
        luis = crear_alumno(referencia='8888', curp='PEMJ100720HMNRRNA5')
        ana = crear_alumno(referencia='8889', curp='GALA150315MMNRPNA1')
        raul = crear_alumno(referencia='8890', curp=CURP_OTRO)
        encabezados = BASICAS + ['Referencia del estudiante', 'CURP del estudiante', 'Parentesco']
        resultado = importar([['María', 'López', '353 123 4567', '8888; 8889', CURP_OTRO.lower(), 'Mamá']], encabezados)
        self.assertEqual((len(resultado.creados), resultado.vinculos, resultado.errores), (1, 3, []))
        tutor = Tutor.objects.get()
        self.assertEqual(
            {v.alumno_id for v in tutor.alumnos_relacionados.all()}, {luis.pk, ana.pk, raul.pk},
        )
        vinculo = tutor.alumnos_relacionados.get(alumno=luis)
        self.assertEqual((vinculo.parentesco, vinculo.activo, vinculo.recibe_notificaciones), ('MADRE', True, True))

    def test_el_primer_tutor_es_el_principal_y_los_siguientes_no(self):
        luis = crear_alumno(referencia='8888')
        encabezados = BASICAS + ['Referencia del estudiante', 'Parentesco']
        importar([['María', 'López', '353 123 4567', '8888', 'Madre'], ['Jorge', 'Pérez', '353 444 5566', '8888', 'Padre']], encabezados)
        self.assertTrue(TutorAlumno.objects.get(alumno=luis, tutor__nombre='María').tutor_principal)
        self.assertFalse(TutorAlumno.objects.get(alumno=luis, tutor__nombre='Jorge').tutor_principal)
        self.assertEqual(TutorAlumno.objects.filter(alumno=luis, tutor_principal=True).count(), 1)

    def test_no_le_quita_lo_principal_al_tutor_que_ya_lo_era(self):
        luis = crear_alumno(referencia='8888')
        principal = crear_tutor(nombre='Rosa', apellido_paterno='Mora')
        vincular(principal, luis, tutor_principal=True)
        importar([['María', 'López', '353 123 4567', '8888', 'Tía']], BASICAS + ['Referencia del estudiante', 'Parentesco'])
        self.assertTrue(TutorAlumno.objects.get(tutor=principal, alumno=luis).tutor_principal)
        self.assertFalse(TutorAlumno.objects.get(tutor__nombre='María', alumno=luis).tutor_principal)

    def test_una_fila_por_estudiante_registra_al_tutor_una_sola_vez(self):
        crear_alumno(referencia='8888')
        crear_alumno(referencia='8889')
        encabezados = BASICAS + ['Referencia del estudiante', 'Parentesco']
        resultado = importar([['María', 'López', '353 123 4567', '8888', 'Madre'], ['María', 'López', '353 123 4567', '8889', 'Madre']], encabezados)
        self.assertEqual((len(resultado.creados), resultado.ampliados, resultado.vinculos), (1, 1, 2))
        self.assertEqual(Tutor.objects.get().alumnos_relacionados.count(), 2)

    def test_a_un_tutor_que_ya_existe_se_le_agregan_solo_los_estudiantes_nuevos(self):
        luis, ana = crear_alumno(referencia='8888'), crear_alumno(referencia='8889')
        tutor = crear_tutor(nombre='María', apellido_paterno='López', telefono='3531234567')
        vincular(tutor, luis, parentesco='MADRE', observaciones='dato propio')
        encabezados = BASICAS + ['Referencia del estudiante', 'Parentesco']
        resultado = importar([['María', 'López', '353 123 4567', '8888; 8889', 'Tía']], encabezados)
        self.assertEqual((len(resultado.creados), resultado.ampliados, resultado.vinculos, resultado.omitidos), (0, 1, 1, 0))
        self.assertEqual(TutorAlumno.objects.get(tutor=tutor, alumno=luis).parentesco, 'MADRE')     # no se pisó lo que ya tenía
        self.assertEqual(TutorAlumno.objects.get(tutor=tutor, alumno=luis).observaciones, 'dato propio')
        self.assertEqual(TutorAlumno.objects.get(tutor=tutor, alumno=ana).parentesco, 'TIA')

    def test_un_vinculo_que_estaba_inactivo_se_reactiva(self):
        luis = crear_alumno(referencia='8888')
        tutor = crear_tutor(nombre='María', apellido_paterno='López', telefono='3531234567')
        vincular(tutor, luis, activo=False)
        resultado = importar([['María', 'López', '353 123 4567', '8888', 'Madre']], BASICAS + ['Referencia del estudiante', 'Parentesco'])
        self.assertEqual(resultado.ampliados, 1)
        self.assertTrue(TutorAlumno.objects.get(tutor=tutor, alumno=luis).activo)

    def test_las_banderas_del_vinculo(self):
        crear_alumno(referencia='8888')
        encabezados = BASICAS + ['Referencia del estudiante', 'Parentesco', 'Contacto de emergencia', 'Puede recoger al estudiante', 'Responsable de pagos']
        importar([['María', 'López', '353 123 4567', '8888', 'Madre', 'Sí', 'no', 'x']], encabezados)
        vinculo = TutorAlumno.objects.get()
        self.assertEqual((vinculo.contacto_emergencia, vinculo.autorizado_recoger, vinculo.responsable_pagos), (True, False, True))

    def test_una_bandera_invalida_es_un_error(self):
        crear_alumno(referencia='8888')
        encabezados = BASICAS + ['Referencia del estudiante', 'Parentesco', 'Responsable de pagos']
        resultado = importar([['María', 'López', '353 123 4567', '8888', 'Madre', 'quizá']], encabezados)
        self.assertIn('Usa Sí o No', resultado.errores[0]['motivo'])

    def test_un_estudiante_que_no_existe_es_un_error_y_no_deja_nada_a_medias(self):
        crear_alumno(referencia='8888')
        encabezados = BASICAS + ['Referencia del estudiante', 'Parentesco']
        resultado = importar([['María', 'López', '353 123 4567', '8888; 9999', 'Madre']], encabezados)
        self.assertIn('«9999»', resultado.errores[0]['motivo'])
        self.assertEqual((Tutor.objects.count(), TutorAlumno.objects.count()), (0, 0))

    def test_un_estudiante_dado_de_baja_no_se_vincula(self):
        crear_alumno(referencia='8888', estatus='BAJA')
        resultado = importar([['María', 'López', '353 123 4567', '8888', 'Madre']], BASICAS + ['Referencia del estudiante', 'Parentesco'])
        self.assertIn('dado de baja', resultado.errores[0]['motivo'])
        self.assertFalse(Tutor.objects.exists())

    def test_con_estudiantes_el_parentesco_es_indispensable(self):
        crear_alumno(referencia='8888')
        resultado = importar([['María', 'López', '353 123 4567', '8888']], BASICAS + ['Referencia del estudiante'])
        self.assertIn('Parentesco', resultado.errores[0]['motivo'])

    def test_un_parentesco_desconocido_queda_como_otro(self):
        crear_alumno(referencia='8888')
        importar([['María', 'López', '353 123 4567', '8888', 'Madrina']], BASICAS + ['Referencia del estudiante', 'Parentesco'])
        self.assertEqual(TutorAlumno.objects.get().parentesco, 'OTRO')

    def test_un_tutor_dado_de_baja_en_el_archivo_no_se_vincula(self):
        crear_alumno(referencia='8888')
        encabezados = BASICAS + ['Estatus', 'Referencia del estudiante', 'Parentesco']
        resultado = importar([['María', 'López', '353 123 4567', 'Inactivo', '8888', 'Madre']], encabezados)
        self.assertIn('no se puede vincular', resultado.errores[0]['motivo'])
        self.assertFalse(Tutor.objects.exists())

    def test_la_curp_de_un_tutor_que_ya_existe_con_otro_nombre_lo_identifica(self):
        """Quien ya está registrado por su CURP es el mismo aunque el archivo escriba distinto el nombre."""
        tutor = crear_tutor(nombre='María', apellido_paterno='López', curp=CURP_TUTOR)
        luis = crear_alumno(referencia='8888')
        encabezados = BASICAS + ['CURP', 'Referencia del estudiante', 'Parentesco']
        resultado = importar([['Ma.', 'López R.', '353 000 0000', CURP_TUTOR, '8888', 'Madre']], encabezados)
        self.assertEqual((resultado.ampliados, Tutor.objects.count()), (1, 1))
        self.assertTrue(TutorAlumno.objects.filter(tutor=tutor, alumno=luis).exists())


# ---------------------------------------------------------------------------
# Pantallas
# ---------------------------------------------------------------------------
@PRUEBAS
class PantallaDeImportacionTests(BaseTestCase):
    url = '/tutores/importar/'

    def subir(self, contenido, nombre='tutores.csv', **extra):
        return self.client.post(self.url, {'archivo': archivo(contenido, nombre)}, **extra)

    def test_la_pagina_explica_las_columnas_y_ofrece_la_plantilla(self):
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 200)
        for texto in ('Importar tutores', 'Descargar plantilla', 'Indispensable', 'Referencia del estudiante', reverse('tutores:importar_plantilla')):
            self.assertContains(respuesta, texto)
        self.assertContains(respuesta, 'enctype="multipart/form-data"')

    def test_importar_vuelve_al_listado_con_un_resumen_que_se_ve_una_sola_vez(self):
        crear_alumno(referencia='8888')
        encabezados = BASICAS + ['Referencia del estudiante', 'Parentesco']
        respuesta = self.subir(csv_bytes([['María', 'López', '353 123 4567', '8888', 'Madre'], ['Jorge', 'Pérez', '123', '', '']], encabezados))
        self.assertRedirects(respuesta, reverse('tutores:lista'), fetch_redirect_response=False)
        listado = self.client.get(reverse('tutores:lista'))
        for texto in ('Importación terminada', 'tutores.csv', 'Tutores registrados', 'Estudiantes vinculados', 'Filas que no se importaron', 'Jorge Pérez'):
            self.assertContains(listado, texto)
        self.assertContains(listado, 'Se importó 1 tutor.')
        self.assertContains(listado, '1 fila no se importó')
        self.assertNotContains(self.client.get(reverse('tutores:lista')), 'Importación terminada')

    def test_vincular_estudiantes_a_tutores_que_ya_existian_tambien_cuenta(self):
        crear_alumno(referencia='8888')
        crear_tutor(nombre='María', apellido_paterno='López', telefono='3531234567')
        encabezados = BASICAS + ['Referencia del estudiante', 'Parentesco']
        respuesta = self.subir(csv_bytes([['María', 'López', '353 123 4567', '8888', 'Madre']], encabezados))
        self.assertRedirects(respuesta, reverse('tutores:lista'), fetch_redirect_response=False)
        listado = self.client.get(reverse('tutores:lista'))
        self.assertContains(listado, 'Se vincularon estudiantes a tutores que ya estaban registrados')
        self.assertContains(listado, 'recibió estudiantes nuevos')

    def test_la_ventana_modal_recibe_la_redireccion_como_json(self):
        respuesta = self.subir(csv_bytes([['María', 'López', '353 123 4567']]), HTTP_X_REQUESTED_WITH='XMLHttpRequest', HTTP_X_MODAL_FORM='1')
        self.assertEqual(respuesta.json(), {'redirect': reverse('tutores:lista')})

    def test_si_no_se_importa_nada_se_queda_en_el_formulario_y_dice_por_que(self):
        respuesta = self.subir(csv_bytes([['María', 'López', '123']]))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'No se importó ningún tutor')
        self.assertContains(respuesta, 'Teléfono')
        self.assertFalse(Tutor.objects.exists())

    def test_si_todos_ya_estaban_registrados_lo_dice(self):
        crear_tutor(nombre='María', apellido_paterno='López', telefono='3531234567')
        respuesta = self.subir(csv_bytes([['María', 'López', '353 123 4567']]))
        self.assertContains(respuesta, 'No se importó ningún tutor')
        self.assertContains(respuesta, '1 ya estaba registrada')

    def test_rechaza_lo_que_no_es_un_csv_y_pide_el_archivo(self):
        self.assertContains(self.subir(b'hola', 'tutores.xlsx'), 'debe ser un CSV')
        self.assertContains(self.client.post(self.url, {}), 'Elige el archivo CSV que quieres importar')

    def test_un_archivo_sin_las_columnas_indispensables_se_explica_en_el_campo(self):
        respuesta = self.subir(csv_bytes([['Ana']], ['Nombre']))
        self.assertContains(respuesta, 'faltan columnas indispensables')

    def test_la_plantilla_se_descarga(self):
        respuesta = self.client.get(reverse('tutores:importar_plantilla'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('plantilla-tutores.csv', respuesta['Content-Disposition'])
        self.assertIn('Nombre,Apellido paterno', respuesta.content.decode('utf-8'))

    def test_el_listado_ofrece_importar_solo_a_quien_puede_registrar(self):
        html = self.client.get(reverse('tutores:lista')).content.decode()
        self.assertRegex(html, r'<a [^>]*href="' + reverse('tutores:importar') + r'"[^>]*data-modal-form')
        self.con_permisos('view_tutor')
        self.assertNotContains(self.client.get(reverse('tutores:lista')), 'Importar CSV')

    def test_exige_el_permiso_de_registrar_tutores(self):
        self.con_permisos('view_tutor', 'change_tutor')
        for nombre in ('importar', 'importar_plantilla'):
            self.assertEqual(self.client.get(reverse(f'tutores:{nombre}')).status_code, 403, nombre)
        self.assertEqual(self.subir(csv_bytes([['María', 'López', '353 123 4567']])).status_code, 403)
        self.assertFalse(Tutor.objects.exists())

    def test_quien_puede_registrar_puede_importar(self):
        self.con_permisos('view_tutor', 'add_tutor')
        respuesta = self.subir(csv_bytes([['María', 'López', '353 123 4567']]))
        self.assertRedirects(respuesta, reverse('tutores:lista'), fetch_redirect_response=False)
        self.assertEqual(Tutor.objects.count(), 1)

    def test_los_tutores_importados_aparecen_con_sus_estudiantes_en_el_listado(self):
        crear_alumno(referencia='8888', nombre='Luis', apellido_paterno='Pérez')
        encabezados = BASICAS + ['Referencia del estudiante', 'Parentesco']
        self.subir(csv_bytes([['María', 'López', '353 123 4567', '8888', 'Madre']], encabezados))
        listado = self.client.get(reverse('tutores:lista'))
        self.assertContains(listado, 'student-chip')
        self.assertContains(listado, 'Luis Pérez')
        self.assertEqual(Alumno.objects.get(referencia='8888').tutores_relacionados.get().tutor.nombre, 'María')
