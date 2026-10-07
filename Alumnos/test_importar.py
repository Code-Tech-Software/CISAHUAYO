"""Importación de estudiantes desde un archivo CSV (Alumnos/importacion.py y sus pantallas)."""
import csv
import io
from datetime import date
from unittest.mock import patch

from django.contrib.auth.hashers import check_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    crear_alumno,
    crear_grado,
    crear_tutor,
)

from . import importacion, lectura_csv
from .models import Alumno, Inscripcion, Tutor, TutorAlumno
from .utils import siguiente_referencia

CURP_ANA = 'GALA150315MMNRPNA1'     # mujer, 15/03/2015
CURP_LUIS = 'PEMJ100720HMNRRNA5'    # hombre, 20/07/2010
CURP_SOFIA = 'LOGA130822MMNPRNA7'   # mujer, 22/08/2013
CURP_RAUL = 'RAMS120405HMNMRNA3'    # hombre, 05/04/2012
CURP_TOMAS = 'TOVC140111HMNRLRA2'   # hombre, 11/01/2014

BASICAS = ['Nombre', 'Apellido paterno', 'Apellido materno', 'CURP']


def csv_bytes(filas, encabezados=None, separador=',', codificacion='utf-8-sig'):
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=separador)
    escritor.writerow(encabezados or BASICAS)
    escritor.writerows(filas)
    return salida.getvalue().encode(codificacion)


def archivo(contenido, nombre='estudiantes.csv'):
    return SimpleUploadedFile(nombre, contenido, content_type='text/csv')


def importar(filas, encabezados=None, **opciones):
    """Lee y registra las filas; devuelve el resultado."""
    return importacion.importar(importacion.leer_filas(csv_bytes(filas, encabezados, **opciones)))


# ---------------------------------------------------------------------------
# Lectura del archivo
# ---------------------------------------------------------------------------
@PRUEBAS
class LecturaDelArchivoTests(BaseTestCase):
    def test_lee_utf8_con_o_sin_bom(self):
        for codificacion in ('utf-8', 'utf-8-sig'):
            filas = importacion.leer_filas(csv_bytes([['José', 'Muñoz', '', CURP_LUIS]], codificacion=codificacion))
            self.assertEqual(filas, [(2, {'nombre': 'José', 'apellido_paterno': 'Muñoz', 'apellido_materno': '', 'curp': CURP_LUIS})])

    def test_lee_el_csv_que_excel_guarda_en_espanol(self):
        """Windows-1252 y punto y coma."""
        contenido = csv_bytes([['José', 'Muñoz', '', CURP_LUIS]], separador=';', codificacion='cp1252')
        self.assertEqual(importacion.leer_filas(contenido)[0][1]['nombre'], 'José')

    def test_acepta_tabuladores(self):
        contenido = csv_bytes([['Ana', 'García', '', CURP_ANA]], separador='\t')
        self.assertEqual(importacion.leer_filas(contenido)[0][1]['curp'], CURP_ANA)

    def test_reconoce_los_encabezados_sin_importar_acentos_ni_mayusculas_ni_alias(self):
        contenido = csv_bytes([['Ana', 'García', CURP_ANA, 'ana@example.com']], ['NOMBRE(S)', 'primer apellido', 'Curp', 'Correo'])
        datos = importacion.leer_filas(contenido)[0][1]
        self.assertEqual(datos, {'nombre': 'Ana', 'apellido_paterno': 'García', 'curp': CURP_ANA, 'correo_electronico': 'ana@example.com'})

    def test_ignora_las_columnas_que_no_conoce_y_las_filas_vacias(self):
        contenido = csv_bytes([['Ana', 'García', CURP_ANA, 'x'], ['', '', '', ''], ['Luis', 'Pérez', CURP_LUIS, 'y']], ['Nombre', 'Apellido paterno', 'CURP', 'Edad'])
        filas = importacion.leer_filas(contenido)
        self.assertEqual([numero for numero, _ in filas], [2, 4])
        self.assertNotIn('Edad', filas[0][1])

    def test_los_saltos_de_linea_dentro_de_una_celda_no_cuentan_como_filas(self):
        contenido = csv_bytes([['Ana', 'García', CURP_ANA, 'Alergia\ntodo el año'], ['Luis', 'Pérez', CURP_LUIS, '']], ['Nombre', 'Apellido paterno', 'CURP', 'Alergias'])
        filas = importacion.leer_filas(contenido)
        self.assertEqual(len(filas), 2)
        self.assertEqual(filas[0][1]['alergias'], 'Alergia\ntodo el año')

    def test_exige_las_columnas_indispensables(self):
        with self.assertRaisesMessage(importacion.ErrorDeArchivo, 'Apellido paterno'):
            importacion.leer_filas(csv_bytes([['Ana', CURP_ANA]], ['Nombre', 'CURP']))

    def test_archivo_vacio_o_solo_con_encabezados(self):
        with self.assertRaisesMessage(importacion.ErrorDeArchivo, 'vacío'):
            importacion.leer_filas(b'')
        with self.assertRaisesMessage(importacion.ErrorDeArchivo, 'solo tiene los encabezados'):
            importacion.leer_filas(csv_bytes([]))

    def test_limites_de_tamano_y_de_filas(self):
        with patch.object(lectura_csv, 'FILAS_MAXIMAS', 2):
            with self.assertRaisesMessage(importacion.ErrorDeArchivo, 'máximo es 2'):
                importacion.leer_filas(csv_bytes([['A', 'B', CURP_ANA], ['C', 'D', CURP_LUIS], ['E', 'F', CURP_RAUL]], ['Nombre', 'Apellido paterno', 'CURP']))
        with patch.object(lectura_csv, 'TAMANO_MAXIMO', 10):
            with self.assertRaisesMessage(importacion.ErrorDeArchivo, 'pesa más de'):
                importacion.leer_filas(csv_bytes([['Ana', 'García', '', CURP_ANA]]))

    def test_no_es_texto(self):
        with self.assertRaisesMessage(importacion.ErrorDeArchivo, 'No se pudo leer'):
            importacion.leer_filas(b'\x81\x8d\x8f\x90\x9d')

    def test_la_plantilla_trae_todas_las_columnas_y_se_lee_de_vuelta(self):
        plantilla = importacion.plantilla_csv()
        self.assertTrue(plantilla.startswith('﻿'))
        encabezados = next(csv.reader(io.StringIO(plantilla.lstrip('﻿'))))
        self.assertEqual(encabezados, [columna.titulo for columna in importacion.COLUMNAS])
        # Cada encabezado se reconoce como su propia columna (ninguno choca con otro)
        indice = lectura_csv.indice_de_encabezados(importacion.COLUMNAS)
        for columna in importacion.COLUMNAS:
            self.assertIs(indice[lectura_csv.clave_de_encabezado(columna.titulo)], columna)
        with self.assertRaisesMessage(importacion.ErrorDeArchivo, 'solo tiene los encabezados'):
            importacion.leer_filas(plantilla.encode('utf-8'))

    def test_lo_que_exporta_el_sistema_se_puede_volver_a_importar(self):
        """Los encabezados de «Exportar CSV» se reconocen (las columnas que no son datos de importación se ignoran)."""
        crear_alumno(curp=CURP_LUIS, referencia='700')
        exportado = self.client.get(reverse('alumnos:exportar')).content
        filas = importacion.leer_filas(exportado)
        self.assertEqual(filas[0][1]['curp'], CURP_LUIS)
        self.assertEqual(filas[0][1]['referencia'], '700')


# ---------------------------------------------------------------------------
# Registro de las filas
# ---------------------------------------------------------------------------
@PRUEBAS
class ImportarEstudiantesTests(BaseTestCase):
    def test_importa_lo_indispensable_y_saca_el_sexo_y_la_fecha_de_la_curp(self):
        resultado = importar([['Ana', 'García', 'López', CURP_ANA], ['Luis', 'Pérez', '', CURP_LUIS]])
        self.assertEqual((len(resultado.creados), resultado.errores, resultado.omitidos), (2, [], 0))
        ana = Alumno.objects.get(curp=CURP_ANA)
        self.assertEqual((ana.sexo, ana.fecha_nacimiento, ana.nacionalidad, ana.estatus), ('F', date(2015, 3, 15), 'Mexicana', 'ACTIVO'))
        self.assertEqual((ana.apellido_materno, ana.religion, ana.domicilio, ana.grupo_sanguineo), ('López', '', '', ''))
        self.assertEqual(Alumno.objects.get(curp=CURP_LUIS).sexo, 'M')
        self.assertFalse(Inscripcion.objects.exists())
        self.assertFalse(TutorAlumno.objects.exists())

    def test_asigna_referencias_consecutivas_y_contrasenas_consultables(self):
        resultado = importar([['Ana', 'García', '', CURP_ANA], ['Luis', 'Pérez', '', CURP_LUIS]])
        referencias = [c['referencia'] for c in resultado.creados]
        self.assertEqual(int(referencias[1]), int(referencias[0]) + 1)
        for creado in resultado.creados:
            alumno = Alumno.objects.get(referencia=creado['referencia'])
            self.assertEqual(len(creado['contrasena']), 8)
            self.assertEqual(alumno.contrasena_visible, creado['contrasena'])
            self.assertTrue(check_password(creado['contrasena'], alumno.contrasena))

    def test_las_referencias_generadas_no_chocan_con_las_que_el_archivo_asigna_a_mano(self):
        siguiente = siguiente_referencia()
        resultado = importar(
            [['Ana', 'García', '', CURP_ANA, ''], ['Luis', 'Pérez', '', CURP_LUIS, siguiente]],
            BASICAS + ['Referencia'],
        )
        self.assertEqual(resultado.errores, [])
        self.assertEqual(Alumno.objects.get(curp=CURP_LUIS).referencia, siguiente)
        self.assertNotEqual(Alumno.objects.get(curp=CURP_ANA).referencia, siguiente)

    def test_importa_un_estudiante_completo_con_tutor_y_grado(self):
        ciclo = ciclo_actual_de_prueba()
        grado = crear_grado('PRIMARIA', 4)
        encabezados = BASICAS + [
            'Sexo', 'Fecha de nacimiento', 'Religión', 'Grupo sanguíneo', 'Domicilio', 'Colonia', 'Ciudad', 'Estado', 'CP',
            'Correo electrónico', 'Grado', 'Contraseña', 'Nombre del tutor', 'Apellido paterno del tutor',
            'Apellido materno del tutor', 'Teléfono del tutor', 'Parentesco del tutor', 'Correo del tutor',
        ]
        resultado = importar([[
            'Ana', 'García', 'López', CURP_ANA, 'Femenino', '15/03/2015', 'católico', 'o positivo', 'Calle Hidalgo 123', 'Centro',
            'Sahuayo', 'Michoacán', '59000', 'Ana@Example.com', '4° Primaria', 'sol123', 'María', 'López', 'Ruiz',
            '353 123 4567', 'Mamá', 'maria@example.com',
        ]], encabezados)
        self.assertEqual((len(resultado.creados), resultado.errores), (1, []))
        ana = Alumno.objects.get(curp=CURP_ANA)
        self.assertEqual(
            (ana.sexo, ana.fecha_nacimiento, ana.religion, ana.grupo_sanguineo, ana.cp, ana.correo_electronico),
            ('F', date(2015, 3, 15), 'Católica', 'O+', '59000', 'ana@example.com'),
        )
        self.assertEqual((ana.contrasena_visible, check_password('sol123', ana.contrasena)), ('sol123', True))
        inscripcion = ana.inscripciones.get()
        self.assertEqual((inscripcion.grado, inscripcion.ciclo), (grado, ciclo))
        vinculo = ana.tutores_relacionados.get()
        self.assertEqual((vinculo.parentesco, vinculo.tutor_principal, vinculo.activo, vinculo.recibe_notificaciones), ('MADRE', True, True, True))
        tutor = vinculo.tutor
        self.assertEqual((str(tutor), tutor.telefono, tutor.correo_electronico), ('María López Ruiz', '3531234567', 'maria@example.com'))
        self.assertEqual((tutor.domicilio, tutor.colonia, tutor.cp), ('Calle Hidalgo 123', 'Centro', '59000'))   # el del estudiante

    def test_los_hermanos_comparten_al_tutor(self):
        encabezados = BASICAS + ['Nombre del tutor', 'Apellido paterno del tutor', 'Teléfono del tutor', 'Parentesco del tutor']
        importar([
            ['Ana', 'García', '', CURP_ANA, 'María', 'López', '3531234567', 'Madre'],
            ['Luis', 'García', '', CURP_LUIS, 'maría', 'LÓPEZ', '(353) 123-4567', 'madre'],
        ], encabezados)
        self.assertEqual(Tutor.objects.count(), 1)
        self.assertEqual(Tutor.objects.get().alumnos_relacionados.count(), 2)

    def test_reutiliza_a_un_tutor_que_ya_estaba_registrado(self):
        existente = crear_tutor(nombre='María', apellido_paterno='López', telefono='3531234567')
        encabezados = BASICAS + ['Nombre del tutor', 'Apellido paterno del tutor', 'Teléfono del tutor', 'Parentesco del tutor']
        importar([['Ana', 'García', '', CURP_ANA, 'María', 'López', '3531234567', 'Madre']], encabezados)
        self.assertEqual(Tutor.objects.count(), 1)
        self.assertEqual(Alumno.objects.get().tutores_relacionados.get().tutor, existente)

    def test_dos_tutores_con_el_mismo_telefono_pero_distinto_nombre_son_personas_distintas(self):
        encabezados = BASICAS + ['Nombre del tutor', 'Apellido paterno del tutor', 'Teléfono del tutor', 'Parentesco del tutor']
        importar([
            ['Ana', 'García', '', CURP_ANA, 'María', 'López', '3531234567', 'Madre'],
            ['Luis', 'Pérez', '', CURP_LUIS, 'Jorge', 'Pérez', '3531234567', 'Padre'],
        ], encabezados)
        self.assertEqual(Tutor.objects.count(), 2)

    def test_los_estudiantes_que_ya_estan_registrados_se_omiten_sin_error(self):
        crear_alumno(curp=CURP_ANA, referencia='9001')
        resultado = importar([['Ana', 'García', '', CURP_ANA.lower()], ['Luis', 'Pérez', '', CURP_LUIS]])
        self.assertEqual((len(resultado.creados), resultado.omitidos, resultado.errores), (1, 1, []))
        self.assertEqual(Alumno.objects.count(), 2)

    def test_volver_a_cargar_el_mismo_archivo_no_duplica_nada(self):
        filas = [['Ana', 'García', '', CURP_ANA], ['Luis', 'Pérez', '', CURP_LUIS]]
        importar(filas)
        segunda = importar(filas)
        self.assertEqual((len(segunda.creados), segunda.omitidos, segunda.errores), (0, 2, []))
        self.assertEqual(Alumno.objects.count(), 2)

    def test_una_curp_repetida_en_el_archivo_se_registra_una_sola_vez(self):
        resultado = importar([['Ana', 'García', '', CURP_ANA], ['Ana', 'García', '', CURP_ANA]])
        self.assertEqual((len(resultado.creados), resultado.omitidos), (1, 1))

    def test_una_fila_con_errores_no_impide_registrar_las_demas(self):
        resultado = importar([['Ana', 'García', '', CURP_ANA], ['Luis', 'Pérez', '', 'ABC'], ['Raúl', 'Mora', '', CURP_RAUL]])
        self.assertEqual(len(resultado.creados), 2)
        self.assertEqual(len(resultado.errores), 1)
        error = resultado.errores[0]
        self.assertEqual((error['fila'], error['persona']), (3, 'Luis Pérez'))
        self.assertIn('CURP', error['motivo'])
        self.assertFalse(Alumno.objects.filter(nombre='Luis').exists())

    def test_informa_todos_los_motivos_de_una_fila_a_la_vez(self):
        resultado = importar(
            [['', 'García', '', 'ABC', 'Otro', '99/99/2015']],
            BASICAS + ['Sexo', 'Fecha de nacimiento'],
        )
        motivo = resultado.errores[0]['motivo']
        for texto in ('Nombre', 'CURP', 'Sexo', 'no es una fecha'):
            self.assertIn(texto, motivo)

    def test_la_referencia_de_otro_estudiante_es_un_error(self):
        crear_alumno(curp=CURP_LUIS, referencia='500')
        resultado = importar([['Ana', 'García', '', CURP_ANA, '500']], BASICAS + ['Referencia'])
        self.assertEqual(len(resultado.creados), 0)
        self.assertIn('«500» ya la tiene otro estudiante', resultado.errores[0]['motivo'])

    def test_un_correo_repetido_es_un_error_de_esa_fila(self):
        crear_alumno(curp=CURP_LUIS, correo_electronico='ana@example.com')
        resultado = importar([['Ana', 'García', '', CURP_ANA, 'ana@example.com']], BASICAS + ['Correo electrónico'])
        self.assertIn('Correo electrónico', resultado.errores[0]['motivo'])

    def test_una_fila_con_errores_no_deja_nada_a_medias(self):
        """El tutor no se crea si el grado de la misma fila no existe."""
        ciclo_actual_de_prueba()
        encabezados = BASICAS + ['Grado', 'Nombre del tutor', 'Apellido paterno del tutor', 'Teléfono del tutor', 'Parentesco del tutor']
        resultado = importar([['Ana', 'García', '', CURP_ANA, '9° Primaria', 'María', 'López', '3531234567', 'Madre']], encabezados)
        self.assertEqual(len(resultado.errores), 1)
        self.assertEqual((Alumno.objects.count(), Tutor.objects.count()), (0, 0))

    # --- sexo, fechas, estatus ---------------------------------------------------------------------
    def test_el_sexo_se_entiende_en_varias_formas(self):
        filas = [['A', 'Uno', '', CURP_ANA, 'Masculino'], ['B', 'Dos', '', CURP_LUIS, 'mujer'], ['C', 'Tres', '', CURP_RAUL, 'F']]
        importar(filas, BASICAS + ['Sexo'])
        self.assertEqual(
            [Alumno.objects.get(curp=c).sexo for c in (CURP_ANA, CURP_LUIS, CURP_RAUL)], ['M', 'F', 'F'],   # lo escrito manda sobre la CURP
        )

    def test_una_m_sola_es_ambigua_y_se_toma_la_curp(self):
        importar([['Ana', 'García', '', CURP_ANA, 'M']], BASICAS + ['Sexo'])
        self.assertEqual(Alumno.objects.get().sexo, 'F')

    def test_otro_ya_no_es_un_sexo_valido(self):
        resultado = importar([['Ana', 'García', '', CURP_ANA, 'Otro']], BASICAS + ['Sexo'])
        self.assertIn('Masculino o Femenino', resultado.errores[0]['motivo'])

    def test_fechas_en_formato_iso_o_dia_mes_ano(self):
        importar(
            [['Ana', 'García', '', CURP_ANA, '2015-03-15', '2026-08-24'], ['Luis', 'Pérez', '', CURP_LUIS, '20/07/2010', '24/08/2026 00:00:00']],
            BASICAS + ['Fecha de nacimiento', 'Fecha de ingreso'],
        )
        for curp, nacimiento in ((CURP_ANA, date(2015, 3, 15)), (CURP_LUIS, date(2010, 7, 20))):
            alumno = Alumno.objects.get(curp=curp)
            self.assertEqual((alumno.fecha_nacimiento, alumno.fecha_ingreso), (nacimiento, date(2026, 8, 24)))

    def test_rechaza_fechas_imposibles_o_futuras(self):
        resultado = importar(
            [['Ana', 'García', '', CURP_ANA, '31/02/2015'], ['Luis', 'Pérez', '', CURP_LUIS, '2999-01-01']],
            BASICAS + ['Fecha de nacimiento'],
        )
        self.assertEqual(len(resultado.errores), 2)
        self.assertIn('no es una fecha', resultado.errores[0]['motivo'])
        self.assertIn('no puede ser futura', resultado.errores[1]['motivo'])

    def test_estatus(self):
        resultado = importar(
            [['Ana', 'García', '', CURP_ANA, 'Egresado'], ['Luis', 'Pérez', '', CURP_LUIS, ''], ['Raúl', 'Mora', '', CURP_RAUL, 'Visitante']],
            BASICAS + ['Estatus'],
        )
        self.assertEqual(Alumno.objects.get(curp=CURP_ANA).estatus, 'EGRESADO')
        self.assertEqual(Alumno.objects.get(curp=CURP_LUIS).estatus, 'ACTIVO')
        self.assertIn('Estatus', resultado.errores[0]['motivo'])

    def test_grupo_sanguineo_se_normaliza_o_se_rechaza(self):
        resultado = importar(
            [['Ana', 'García', '', CURP_ANA, 'ab-'], ['Luis', 'Pérez', '', CURP_LUIS, 'O positivo'], ['Raúl', 'Mora', '', CURP_RAUL, 'Z+']],
            BASICAS + ['Grupo sanguíneo'],
        )
        self.assertEqual(Alumno.objects.get(curp=CURP_ANA).grupo_sanguineo, 'AB-')
        self.assertEqual(Alumno.objects.get(curp=CURP_LUIS).grupo_sanguineo, 'O+')
        self.assertIn('Grupo sanguíneo', resultado.errores[0]['motivo'])

    # --- religión ----------------------------------------------------------------------------------
    def test_la_religion_se_lleva_a_la_lista(self):
        resultado = importar(
            [
                ['A', 'Uno', '', CURP_ANA, 'Católico'], ['B', 'Dos', '', CURP_LUIS, 'cristiana'], ['C', 'Tres', '', CURP_RAUL, 'Mormón'],
                ['D', 'Cuatro', '', CURP_SOFIA, 'Musulmán'], ['E', 'Cinco', '', CURP_TOMAS, 'Judío'],
            ],
            BASICAS + ['Religión'],
        )
        self.assertEqual(resultado.errores, [])
        self.assertEqual(
            [Alumno.objects.get(curp=c).religion for c in (CURP_ANA, CURP_LUIS, CURP_RAUL, CURP_SOFIA, CURP_TOMAS)],
            ['Católica', 'Cristiana', 'Iglesia de Jesucristo de los Santos de los Últimos Días', 'Musulmana', 'Judía'],
        )
        self.assertEqual(resultado.religiones_como_otra, 0)

    def test_una_religion_que_no_esta_en_la_lista_se_registra_como_otra_y_se_cuenta(self):
        resultado = importar([['Ana', 'García', '', CURP_ANA, 'Testigo de Jehová']], BASICAS + ['Religión'])
        self.assertEqual(Alumno.objects.get().religion, 'Otra')
        self.assertEqual(resultado.religiones_como_otra, 1)

    def test_sin_religion_queda_vacia(self):
        importar([['Ana', 'García', '', CURP_ANA, 'Ninguna'], ['Luis', 'Pérez', '', CURP_LUIS, '']], BASICAS + ['Religión'])
        self.assertEqual(set(Alumno.objects.values_list('religion', flat=True)), {''})

    # --- contraseña --------------------------------------------------------------------------------
    def test_la_contrasena_del_archivo_puede_ser_sencilla(self):
        importar([['Ana', 'García', '', CURP_ANA, '1234']], BASICAS + ['Contraseña'])
        ana = Alumno.objects.get()
        self.assertEqual(ana.contrasena_visible, '1234')
        self.assertTrue(check_password('1234', ana.contrasena))

    def test_una_contrasena_demasiado_corta_es_un_error(self):
        resultado = importar([['Ana', 'García', '', CURP_ANA, '12']], BASICAS + ['Contraseña'])
        self.assertIn('Usa al menos 4 caracteres', resultado.errores[0]['motivo'])

    # --- tutor -------------------------------------------------------------------------------------
    def test_el_tutor_a_medias_es_un_error(self):
        resultado = importar([['Ana', 'García', '', CURP_ANA, 'María']], BASICAS + ['Nombre del tutor'])
        self.assertIn('Tutor: falta su apellido paterno, su teléfono, su parentesco', resultado.errores[0]['motivo'])

    def test_telefono_o_correo_del_tutor_invalidos(self):
        encabezados = BASICAS + ['Nombre del tutor', 'Apellido paterno del tutor', 'Teléfono del tutor', 'Parentesco del tutor', 'Correo del tutor']
        resultado = importar([
            ['Ana', 'García', '', CURP_ANA, 'María', 'López', '12345', 'Madre', ''],
            ['Luis', 'Pérez', '', CURP_LUIS, 'Jorge', 'Pérez', '3531234567', 'Padre', 'no-es-correo'],
        ], encabezados)
        self.assertIn('no tiene 10 dígitos', resultado.errores[0]['motivo'])
        self.assertIn('Correo del tutor', resultado.errores[1]['motivo'])

    def test_un_parentesco_desconocido_queda_como_otro(self):
        encabezados = BASICAS + ['Nombre del tutor', 'Apellido paterno del tutor', 'Teléfono del tutor', 'Parentesco del tutor']
        importar([['Ana', 'García', '', CURP_ANA, 'María', 'López', '3531234567', 'Madrina']], encabezados)
        self.assertEqual(TutorAlumno.objects.get().parentesco, 'OTRO')

    # --- grado -------------------------------------------------------------------------------------
    def test_el_grado_se_reconoce_de_varias_formas(self):
        ciclo_actual_de_prueba()
        primero = crear_grado('SECUNDARIA', 1, equivalencia='7')
        crear_grado('PREESCOLAR', 2, equivalencia='K2')
        filas = [
            ['A', 'Uno', '', CURP_ANA, '1° Secundaria'], ['B', 'Dos', '', CURP_LUIS, 'primero de secundaria'],
            ['C', 'Tres', '', CURP_RAUL, '1ro. SECUNDARIA'], ['D', 'Cuatro', '', CURP_SOFIA, '7'], ['E', 'Cinco', '', CURP_TOMAS, 'k2'],
        ]
        resultado = importar(filas, BASICAS + ['Grado'])
        self.assertEqual(resultado.errores, [])
        grados = [Alumno.objects.get(curp=c).inscripciones.get().grado for c in (CURP_ANA, CURP_LUIS, CURP_RAUL, CURP_SOFIA, CURP_TOMAS)]
        self.assertEqual(grados[:4], [primero] * 4)
        self.assertEqual(str(grados[4]), '2° Preescolar')

    def test_un_grado_que_no_existe_o_esta_de_baja_es_un_error(self):
        ciclo_actual_de_prueba()
        crear_grado('PRIMARIA', 1, activo=False)
        resultado = importar(
            [['Ana', 'García', '', CURP_ANA, '1° Primaria'], ['Luis', 'Pérez', '', CURP_LUIS, 'Kínder 9']], BASICAS + ['Grado'],
        )
        self.assertEqual(len(resultado.errores), 2)
        self.assertIn('Grado: «1° Primaria» no existe o está dado de baja', resultado.errores[0]['motivo'])
        self.assertEqual(Alumno.objects.count(), 0)

    def test_sin_ciclo_actual_no_se_puede_inscribir(self):
        crear_grado('PRIMARIA', 1)
        resultado = importar([['Ana', 'García', '', CURP_ANA, '1° Primaria']], BASICAS + ['Grado'])
        self.assertIn('no hay un ciclo escolar actual', resultado.errores[0]['motivo'])

    def test_un_egresado_no_se_inscribe(self):
        ciclo_actual_de_prueba()
        crear_grado('PRIMARIA', 1)
        resultado = importar([['Ana', 'García', '', CURP_ANA, 'Egresado', '1° Primaria']], BASICAS + ['Estatus', 'Grado'])
        self.assertIn('activo o suspendido', resultado.errores[0]['motivo'])


# ---------------------------------------------------------------------------
# Pantallas
# ---------------------------------------------------------------------------
@PRUEBAS
class PantallaDeImportacionTests(BaseTestCase):
    url = '/alumnos/importar/'

    def subir(self, contenido, nombre='estudiantes.csv', **extra):
        return self.client.post(self.url, {'archivo': archivo(contenido, nombre)}, **extra)

    def test_la_pagina_explica_las_columnas_y_ofrece_la_plantilla(self):
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 200)
        for texto in ('Importar estudiantes', 'Descargar plantilla', 'Indispensable', 'Teléfono del tutor', reverse('alumnos:importar_plantilla')):
            self.assertContains(respuesta, texto)
        self.assertContains(respuesta, 'enctype="multipart/form-data"')
        self.assertContains(respuesta, 'name="archivo"')

    def test_importar_vuelve_al_listado_con_un_resumen_que_se_ve_una_sola_vez(self):
        respuesta = self.subir(csv_bytes([['Ana', 'García', '', CURP_ANA], ['Luis', 'Pérez', '', 'ABC']]))
        self.assertRedirects(respuesta, reverse('alumnos:lista'), fetch_redirect_response=False)
        listado = self.client.get(reverse('alumnos:lista'))
        for texto in ('Importación terminada', 'estudiantes.csv', 'Filas que no se importaron', 'Descargar contraseñas'):
            self.assertContains(listado, texto)
        self.assertContains(listado, 'Se importó 1 estudiante.')
        self.assertContains(listado, '1 fila no se importó')
        self.assertContains(listado, 'Ana García')
        self.assertNotContains(self.client.get(reverse('alumnos:lista')), 'Importación terminada')

    def test_la_ventana_modal_recibe_la_redireccion_como_json(self):
        respuesta = self.subir(csv_bytes([['Ana', 'García', '', CURP_ANA]]), HTTP_X_REQUESTED_WITH='XMLHttpRequest', HTTP_X_MODAL_FORM='1')
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json(), {'redirect': reverse('alumnos:lista')})

    def test_si_no_se_importa_ninguno_se_queda_en_el_formulario_y_dice_por_que(self):
        respuesta = self.subir(csv_bytes([['Ana', 'García', '', 'ABC']]))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'No se importó ningún estudiante')
        self.assertContains(respuesta, 'CURP')
        self.assertFalse(Alumno.objects.exists())

    def test_si_todos_ya_estaban_registrados_lo_dice(self):
        crear_alumno(curp=CURP_ANA)
        respuesta = self.subir(csv_bytes([['Ana', 'García', '', CURP_ANA]]))
        self.assertContains(respuesta, 'No se importó ningún estudiante')
        self.assertContains(respuesta, '1 ya estaba registrada')

    def test_rechaza_lo_que_no_es_un_csv(self):
        respuesta = self.subir(b'hola', 'estudiantes.xlsx')
        self.assertContains(respuesta, 'debe ser un CSV')

    def test_pide_el_archivo(self):
        respuesta = self.client.post(self.url, {})
        self.assertContains(respuesta, 'Elige el archivo CSV que quieres importar')

    def test_un_archivo_sin_las_columnas_indispensables_se_explica_en_el_campo(self):
        respuesta = self.subir(csv_bytes([['Ana']], ['Nombre']))
        self.assertContains(respuesta, 'faltan columnas indispensables')
        self.assertFalse(Alumno.objects.exists())

    def test_la_plantilla_se_descarga(self):
        respuesta = self.client.get(reverse('alumnos:importar_plantilla'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('plantilla-estudiantes.csv', respuesta['Content-Disposition'])
        self.assertIn('Nombre,Apellido paterno', respuesta.content.decode('utf-8'))

    def test_las_contrasenas_de_la_ultima_importacion_se_descargan(self):
        self.subir(csv_bytes([['Ana', 'García', '', CURP_ANA, 'sol123']], BASICAS + ['Contraseña']))
        respuesta = self.client.get(reverse('alumnos:importar_credenciales'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('contrasenas-importadas-', respuesta['Content-Disposition'])
        filas = list(csv.reader(io.StringIO(respuesta.content.decode('utf-8').lstrip('﻿'))))
        self.assertEqual(filas[0], ['Referencia', 'Nombre', 'Grado', 'Contraseña'])
        self.assertEqual(filas[1][1:], ['Ana García', '', 'sol123'])

    def test_sin_importacion_reciente_no_hay_contrasenas_que_descargar(self):
        respuesta = self.client.get(reverse('alumnos:importar_credenciales'), follow=True)
        self.assertRedirects(respuesta, reverse('alumnos:lista'))
        self.assertContains(respuesta, 'No hay contraseñas de una importación reciente')

    def test_el_listado_ofrece_importar_solo_a_quien_puede_registrar(self):
        enlace = reverse('alumnos:importar')
        html = self.client.get(reverse('alumnos:lista')).content.decode()
        self.assertRegex(html, r'<a [^>]*href="' + enlace + r'"[^>]*data-modal-form')
        self.assertIn('Importar CSV', html)
        self.con_permisos('view_alumno')
        self.assertNotContains(self.client.get(reverse('alumnos:lista')), 'Importar CSV')

    def test_exige_el_permiso_de_registrar_estudiantes(self):
        self.con_permisos('view_alumno', 'change_alumno')
        for nombre in ('importar', 'importar_plantilla', 'importar_credenciales'):
            self.assertEqual(self.client.get(reverse(f'alumnos:{nombre}')).status_code, 403, nombre)
        self.assertEqual(self.subir(csv_bytes([['Ana', 'García', '', CURP_ANA]])).status_code, 403)
        self.assertFalse(Alumno.objects.exists())

    def test_quien_puede_registrar_puede_importar(self):
        self.con_permisos('view_alumno', 'add_alumno')
        respuesta = self.subir(csv_bytes([['Ana', 'García', '', CURP_ANA]]))
        self.assertRedirects(respuesta, reverse('alumnos:lista'), fetch_redirect_response=False)
        self.assertEqual(Alumno.objects.count(), 1)
