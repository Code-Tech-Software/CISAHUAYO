"""Llena la base de demostración con un colegio ficticio completo, alrededor de la fecha de hoy.

Todo se registra con las reglas del sistema (inscribir, asignar a un bloque, registrar la entrada, cerrar el día,
justificar, cerrar actas, publicar boletas, avisar un retiro, programar y realizar una reunión, enviar comunicados), así
que los módulos cuadran entre sí: la boleta con las actas, el panel con la asistencia, la Vista 360 con todo lo demás.
Lo que pasó en días anteriores se registra con el reloj detenido en ese momento (`reloj`), para que cada cosa quede con
su fecha y su hora de entonces.

Solo se usa a través de `python manage.py sembrar_demo --settings=CISAHUAYO.settings_demo`.
"""
import random
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from time import monotonic
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.utils import timezone

from Alumnos.models import (
    Alumno, CicloEscolar, ConfiguracionAsistencia, DiaNoLectivo, Grado, Grupo, HorarioMateria, Inscripcion, Materia, MateriaGrado,
    NombreGrupo, Periodo, Profesor, Semestre, Tutor, TutorAlumno,
)
from Usuarios.models import PerfilUsuario, Rol
from Usuarios.seguridad import asignar_rol

from . import datos as D

NIVELES = ('PREESCOLAR', 'PRIMARIA', 'SECUNDARIA', 'PREPARATORIA')
Usuario = get_user_model()


@contextmanager
def reloj(momento):
    """El reloj del sistema detenido en ese momento: lo que se registre queda con esa fecha y hora."""
    with mock.patch('django.utils.timezone.now', return_value=momento):
        yield


def momento(fecha, hora=8, minuto=0):
    return timezone.make_aware(datetime.combine(fecha, time(hora, minuto)))


def sin_acentos(texto):
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn').lower().replace(' ', '')


def lunes_desde(dia):
    return dia + timedelta(days=(7 - dia.weekday()) % 7)


class Demo:
    def __init__(self, avisar, contrasena, semilla=2026):
        self.avisar = avisar
        self.clave = contrasena
        self.cifrada = make_password(contrasena)   # todas las cuentas la comparten: se cifra una sola vez
        self.rng = random.Random(semilla)
        self.hoy = timezone.localdate()
        self.cuentas = []          # (usuario, rol, quién)
        self.portales = []         # (tipo, acceso, quién)
        self.nivel_de = {}         # id de alumno -> su desempeño (5.5 a 9.8)
        self.ausentismo = {}       # id de alumno -> probabilidad de faltar
        self.conteo = {}

    # ------------------------------------------------------------------
    def todo(self):
        pasos = (
            ('Fechas, ciclos y semestres', self.fechas), ('Grados, grupos y materias', self.estructura), ('Personal y cuentas', self.personal),
            ('Docentes', self.docentes), ('Asignaciones y horarios', self.asignaciones), ('Periodos de evaluación', self.periodos),
            ('Estudiantes, tutores e inscripciones', self.estudiantes), ('Bloque simultáneo', self.bloque),
            ('Días sin clases y asistencia', self.asistencia), ('Justificaciones', self.justificaciones),
            ('Calificaciones', self.calificaciones), ('Comentarios por periodo y boletas publicadas', self.comentarios),
            ('Conducta', self.conducta), ('Bitácoras por grupo', self.bitacoras), ('Retiros anticipados', self.retiros),
            ('Reuniones con familias', self.reuniones), ('Agenda', self.agenda), ('Comunicados', self.comunicados), ('Mensajes', self.mensajes),
        )
        for nombre, paso in pasos:
            inicio = monotonic()
            with transaction.atomic():
                paso()
            self.avisar(f'· {nombre} ({monotonic() - inicio:.0f} s)')
        return self.conteo

    def contar(self, clave, n=1):
        self.conteo[clave] = self.conteo.get(clave, 0) + n

    def dias_de_clase(self, desde, hasta):
        dias, dia = [], desde
        while dia <= hasta:
            if dia.weekday() < 5 and dia not in self.festivos:
                dias.append(dia)
            dia += timedelta(days=1)
        return dias

    # ------------------------------------------------------------------
    # Estructura
    # ------------------------------------------------------------------
    def fechas(self):
        y = self.hoy.year if self.hoy.month >= 8 else self.hoy.year - 1
        self.inicio, self.fin = lunes_desde(date(y, 8, 25)), date(y + 1, 7, 9)
        self.inicio_previo, self.fin_previo = lunes_desde(date(y - 1, 8, 25)), date(y, 7, 9)
        self.fin_a, self.inicio_b = date(y + 1, 1, 22), lunes_desde(date(y + 1, 1, 26))
        if self.hoy > self.fin_a:
            self.avisar('  Aviso: la demostración está pensada para el primer semestre de bachillerato (agosto a enero).')
        self.previo = CicloEscolar.objects.create(nombre=f'{y - 1}-{y}', fecha_inicio=self.inicio_previo, fecha_fin=self.fin_previo,
                                                  cerrado_en=momento(self.fin_previo, 14))
        self.ciclo = CicloEscolar.objects.create(nombre=f'{y}-{y + 1}', fecha_inicio=self.inicio, fecha_fin=self.fin, activo=True,
                                                 activado_en=momento(self.inicio - timedelta(days=7), 9))
        self.semestre_a = Semestre.objects.create(ciclo=self.ciclo, clave='A', fecha_inicio=self.inicio, fecha_fin=self.fin_a,
                                                  estado=Semestre.ABIERTO, abierto_en=momento(self.inicio, 7))
        self.semestre_b = Semestre.objects.create(ciclo=self.ciclo, clave='B', fecha_inicio=self.inicio_b, fecha_fin=self.fin)
        # Días sin clases de todo el colegio que caen en el ciclo
        festivos = [(date(y, 9, 16), 'Día de la Independencia'), (date(y, 11, 2), 'Día de Muertos'),
                    (lunes_desde(date(y, 11, 15)), 'Aniversario de la Revolución')]
        viernes = [d for d in (date(y, 10, 1) + timedelta(days=i) for i in range(31)) if d.weekday() == 4]
        festivos.append((viernes[-1], 'Consejo técnico escolar'))
        self.festivos = {f for f, _ in festivos}
        self.motivos_festivos = festivos
        self.contar('ciclos', 2)

    def estructura(self):
        self.grados, self.grupos, self.materias = {}, {}, {}
        b, _ = NombreGrupo.objects.get_or_create(nombre='B', defaults={'orden': 2})
        necesarios = {('PREESCOLAR', 2), ('PREESCOLAR', 3), ('SECUNDARIA', 1), ('SECUNDARIA', 2), ('SECUNDARIA', 3),
                      ('PREPARATORIA', 1), ('PREPARATORIA', 3), ('PREPARATORIA', 5)} | {('PRIMARIA', n) for n in range(1, 7)}
        for nivel, numero in sorted(necesarios, key=lambda x: (NIVELES.index(x[0]), x[1])):
            grado = Grado.objects.create(nivel=nivel, numero=numero)
            self.grados[(nivel, numero)] = grado
            self.grupos[(nivel, numero, 'A')] = Grupo.principal_de(grado)
            for indice, (area, nombre) in enumerate(D.MATERIAS[nivel][numero]):
                self.materias[(nivel, numero, indice)] = Materia.objects.create(
                    clave=f'{D.CLAVE_DE_NIVEL[nivel]}{numero}{indice + 1:02d}', nombre=nombre, grado=grado)
        for nivel, lista in D.GRUPOS.items():
            for numero, letra in lista:
                if letra != 'A':
                    self.grupos[(nivel, numero, letra)] = Grupo.objects.create(grado=self.grados[(nivel, numero)], nombre=b)
        from Calificaciones.models import DatosOficialesNivel
        for nivel in NIVELES:
            director, cargo = D.DIRECTORES[nivel]
            DatosOficialesNivel.objects.create(nivel=nivel, cct=D.CCT[nivel], director=director, cargo=cargo)
        ConfiguracionAsistencia.cargar()
        self.contar('grados', len(self.grados))
        self.contar('grupos', len(self.grupos))
        self.contar('materias', len(self.materias))

    def cuenta(self, usuario, nombre, apellidos, rol, quien, **perfil):
        cuenta = Usuario.objects.create(username=usuario, email=f'{usuario}@cisahuayo.test', password=self.cifrada, first_name=nombre, last_name=apellidos)
        datos = PerfilUsuario.de(cuenta)
        datos.debe_cambiar_contrasena = False
        for campo, valor in perfil.items():
            setattr(datos, campo, valor)
        datos.save()
        asignar_rol(cuenta, Rol.objects.get(grupo__name=rol))
        self.cuentas.append((usuario, rol, quien))
        return cuenta

    def personal(self):
        todos = list(NIVELES)
        self.admin = self.cuenta('admin', 'Andrea', 'Salgado Cuevas', 'Administrador', 'Administración del sistema (todo)')
        self.direccion = self.cuenta('direccion', 'Teresa', 'Villalobos Ruiz', 'Dirección', 'Dirección (todos los niveles)', cargo='Directora general',
                                     niveles_direccion=todos, niveles_comunicados=todos, niveles_retiros=todos)
        self.control = self.cuenta('control', 'Rubén', 'Aguirre Lozano', 'Control escolar', 'Control escolar', niveles_retiros=todos)
        self.coordinacion = self.cuenta('coordinacion', 'Paola', 'Esquivel Durán', 'Coordinación académica', 'Coordinación (secundaria y bachillerato)',
                                        niveles_bitacora=['SECUNDARIA', 'PREPARATORIA'], niveles_comunicados=['SECUNDARIA', 'PREPARATORIA'])
        self.prefectura = self.cuenta('prefectura', 'Ignacio', 'Cárdenas Ponce', 'Prefectura', 'Prefectura (todo el colegio)')
        from Prefectura.models import AlcancePrefectura
        AlcancePrefectura.objects.create(usuario=self.prefectura, todo_el_colegio=True)
        self.recepcion = self.cuenta('recepcion', 'Mariela', 'Gómez Torres', 'Recepción', 'Recepción')

    def docentes(self):
        self.profesores = []       # (profesor, nivel, área, grupos)
        for nombre, paterno, materno, nivel, area, grupos in D.PROFESORES:
            usuario = sin_acentos(f'{nombre.split()[0]}.{paterno}')
            cuenta = self.cuenta(usuario, nombre, f'{paterno} {materno}', 'Docente', f'Docente de {D.NOMBRE_DE_NIVEL[nivel]}: {D.AREAS[area]}')
            profesor = Profesor.objects.create(nombre=nombre, apellido_paterno=paterno, apellido_materno=materno,
                                               telefono=f'353{self.rng.randint(1000000, 9999999)}', correo_electronico=f'{usuario}@cisahuayo.test',
                                               fecha_ingreso=date(self.inicio.year - self.rng.randint(1, 12), 8, 20), usuario=cuenta)
            profesor.establecer_niveles([nivel])
            self.profesores.append((profesor, nivel, area, grupos))
        self.contar('docentes', len(self.profesores))

    def docente_de(self, nivel, area, indice):
        for profesor, nivel_, area_, grupos in self.profesores:
            if nivel_ == nivel and area_ == area and (grupos is None or indice in grupos):
                return profesor
        return None

    def asignaciones(self):
        """Las materias de cada grupo con su docente y su horario (ciclo actual) y las del ciclo pasado (sin horario)."""
        self.asignaciones_actuales = []
        for nivel, lista in D.GRUPOS.items():
            for k, (numero, letra) in enumerate(lista):
                grupo = self.grupos[(nivel, numero, letra)]
                for s, (area, _) in enumerate(D.MATERIAS[nivel][numero]):
                    asignacion = MateriaGrado.objects.create(ciclo=self.ciclo, grado=grupo.grado, grupo=grupo, materia=self.materias[(nivel, numero, s)],
                                                             profesor=self.docente_de(nivel, area, k))
                    self.asignaciones_actuales.append(asignacion)
                    # Una rejilla latina: ningún grupo ni docente tiene dos clases a la misma hora
                    inicio_h, inicio_m, fin_h, fin_m = D.HORAS[(s + k) % len(D.HORAS)]
                    dias = D.DIAS_DE_EDUCACION_FISICA if area == 'fisica' else range(5)
                    for dia in dias:
                        HorarioMateria.objects.create(materia_grado=asignacion, dia_semana=dia, hora_inicio=time(inicio_h, inicio_m), hora_fin=time(fin_h, fin_m))
        # Ciclo pasado: un grupo A por grado (de donde vienen los estudiantes de hoy)
        self.grupos_previos = {}
        previos = {'PREESCOLAR': (2, 3), 'PRIMARIA': (1, 2, 3, 4, 5, 6), 'SECUNDARIA': (1, 2, 3)}
        for nivel, numeros in previos.items():
            for k, numero in enumerate(numeros):
                grupo = self.grupos[(nivel, numero, 'A')]
                self.grupos_previos[(nivel, numero)] = grupo
                for s, (area, _) in enumerate(D.MATERIAS[nivel][numero]):
                    MateriaGrado.objects.create(ciclo=self.previo, grado=grupo.grado, grupo=grupo, materia=self.materias[(nivel, numero, s)],
                                                profesor=self.docente_de(nivel, area, k))
        self.contar('asignaciones', MateriaGrado.objects.count())

    def periodos(self):
        def bimestres(ciclo, inicio, fin):
            for nivel in ('PREESCOLAR', 'PRIMARIA', 'SECUNDARIA'):
                for n in range(5):
                    desde = inicio + timedelta(weeks=8 * n)
                    hasta = fin if n == 4 else desde + timedelta(weeks=8, days=-3)
                    Periodo.objects.create(ciclo=ciclo, nivel=nivel, nombre=f'Bimestre {n + 1}', fecha_inicio=desde, fecha_fin=hasta)

        def parciales(semestre, sufijo):
            dias = (semestre.fecha_fin - semestre.fecha_inicio).days + 1
            for n in range(3):
                desde = semestre.fecha_inicio + timedelta(days=dias * n // 3)
                hasta = semestre.fecha_fin if n == 2 else semestre.fecha_inicio + timedelta(days=dias * (n + 1) // 3 - 1)
                Periodo.objects.create(ciclo=self.ciclo, nivel='PREPARATORIA', semestre=semestre, nombre=f'Parcial {n + 1}{sufijo}',
                                       fecha_inicio=desde, fecha_fin=hasta)

        bimestres(self.ciclo, self.inicio, self.fin)
        bimestres(self.previo, self.inicio_previo, self.fin_previo)
        parciales(self.semestre_a, '')
        parciales(self.semestre_b, ' B')
        self.contar('periodos', Periodo.objects.count())

    # ------------------------------------------------------------------
    # Personas
    # ------------------------------------------------------------------
    def estudiantes(self):
        lugares = []   # (nivel, número, letra) por cada lugar libre
        for nivel, lista in D.GRUPOS.items():
            for numero, letra in lista:
                lugares += [(nivel, numero, letra)] * D.POR_GRUPO[nivel]
        self.rng.shuffle(lugares)
        anterior = {('PREESCOLAR', 3): ('PREESCOLAR', 2), ('PRIMARIA', 1): ('PREESCOLAR', 3), ('SECUNDARIA', 1): ('PRIMARIA', 6),
                    ('PREPARATORIA', 1): ('SECUNDARIA', 3)}
        anterior.update({('PRIMARIA', n): ('PRIMARIA', n - 1) for n in range(2, 7)})
        anterior.update({('SECUNDARIA', n): ('SECUNDARIA', n - 1) for n in (2, 3)})
        usados, numero_alumno, numero_tutor = set(), 0, 0
        self.inscripciones = []
        while lugares:
            paterno, materno = self.rng.sample(D.APELLIDOS, 2)
            while (paterno, materno) in usados:
                paterno, materno = self.rng.sample(D.APELLIDOS, 2)
            usados.add((paterno, materno))
            hijos = 1 if self.rng.random() < 0.7 else (2 if self.rng.random() < 0.85 else 3)
            colonia, calle = self.rng.choice(D.COLONIAS), f'{self.rng.choice(D.CALLES)} {self.rng.randint(10, 899)}'
            # Los tutores: la mamá siempre (principal, con portal); el papá en la mitad de las familias
            tutores = []
            for sexo, parentesco in (('F', 'MADRE'), ('M', 'PADRE')):
                if parentesco == 'PADRE' and self.rng.random() < 0.5:
                    continue
                numero_tutor += 1
                nombre = self.rng.choice(D.NOMBRES_F if sexo == 'F' else D.NOMBRES_M)
                apellido = materno if sexo == 'F' else paterno
                otro = self.rng.choice(D.APELLIDOS)
                tutor = Tutor(nombre=nombre, apellido_paterno=apellido, apellido_materno=otro, telefono=f'353{5000000 + numero_tutor:07d}',
                              correo_electronico=f'{sin_acentos(nombre.split()[0])}.{sin_acentos(apellido)}{numero_tutor}@correo.test',
                              domicilio=calle, colonia=colonia, ciudad='Sahuayo', estado='Michoacán', cp='59000', ocupacion=self.rng.choice(D.OCUPACIONES),
                              usuario=f'{sin_acentos(nombre.split()[0])}.{sin_acentos(apellido)}{numero_tutor}', acceso_portal=parentesco == 'MADRE')
                if tutor.acceso_portal:
                    tutor.contrasena, tutor.contrasena_visible = self.cifrada, self.clave
                tutor.save()
                tutores.append((tutor, parentesco))
            for _ in range(hijos):
                if not lugares:
                    break
                nivel, numero, letra = lugares.pop()
                numero_alumno += 1
                sexo = self.rng.choice('FM')
                nombre = self.rng.choice(D.NOMBRES_F if sexo == 'F' else D.NOMBRES_M)
                grado = self.grados[(nivel, numero)]
                orden = numero if nivel != 'PREPARATORIA' else (numero + 1) // 2
                edad = D.EDAD_DE_INGRESO[nivel] + orden - 1
                nacimiento = date(self.inicio.year - edad - 1, self.rng.randint(9, 12), self.rng.randint(1, 28)) if self.rng.random() < 0.3 else \
                    date(self.inicio.year - edad, self.rng.randint(1, 8), self.rng.randint(1, 28))
                alumno = Alumno(
                    referencia=f'{1000 + numero_alumno}', uid=f'{self.rng.getrandbits(32):08X}', nombre=nombre, apellido_paterno=paterno, apellido_materno=materno,
                    curp=(f'{sin_acentos(paterno)[:2]}{sin_acentos(materno)[0]}{sin_acentos(nombre)[0]}{nacimiento:%y%m%d}{"M" if sexo == "F" else "H"}MN'
                          f'{numero_alumno:04d}').upper()[:18],
                    sexo=sexo, fecha_nacimiento=nacimiento, grupo_sanguineo=self.rng.choice(D.GRUPOS_SANGUINEOS), alergias=self.rng.choice(D.ALERGIAS),
                    domicilio=calle, colonia=colonia, ciudad='Sahuayo', estado='Michoacán', cp='59000',
                    correo_electronico=f'{sin_acentos(nombre.split()[0])}.{sin_acentos(paterno)}{numero_alumno}@alumnos.cisahuayo.test',
                    acceso_portal=nivel in ('SECUNDARIA', 'PREPARATORIA'), estatus='ACTIVO',
                )
                alumno.contrasena, alumno.contrasena_visible = self.cifrada, self.clave
                alumno.save()
                self.nivel_de[alumno.pk] = self._desempeno()
                self.ausentismo[alumno.pk] = 0.15 if self.rng.random() < 0.06 else self.rng.uniform(0.01, 0.05)
                for posicion, (tutor, parentesco) in enumerate(tutores):
                    TutorAlumno.objects.create(tutor=tutor, alumno=alumno, parentesco=parentesco, tutor_principal=posicion == 0,
                                               contacto_emergencia=True, autorizado_recoger=True, recibe_notificaciones=True)
                # La historia: el grado anterior en el ciclo pasado (salvo quien es de nuevo ingreso)
                previo = anterior.get((nivel, numero))
                ingreso = self.inicio
                if previo and self.rng.random() < 0.9:
                    Inscripcion.objects.create(alumno=alumno, ciclo=self.previo, grado=self.grados[previo], grupo=self.grupos_previos[previo],
                                               fecha_inscripcion=self.inicio_previo - timedelta(days=self.rng.randint(5, 30)))
                    ingreso = self.inicio_previo
                inscripcion = Inscripcion.objects.create(alumno=alumno, ciclo=self.ciclo, grado=grado, grupo=self.grupos[(nivel, numero, letra)],
                                                         fecha_inscripcion=self.inicio - timedelta(days=self.rng.randint(3, 25)))
                alumno.fecha_ingreso = ingreso
                alumno.save(update_fields=['fecha_ingreso'])
                self.inscripciones.append(inscripcion)
                if alumno.acceso_portal and len([p for p in self.portales if p[0] == 'Estudiante']) < 3:
                    self.portales.append(('Estudiante', alumno.correo_electronico, f'{alumno} · {inscripcion.grupo}'))
            madre = tutores[0][0]
            if len([p for p in self.portales if p[0] == 'Tutor']) < 3 and hijos > 1:
                self.portales.append(('Tutor', madre.usuario, f'{madre} · {hijos} hijos'))
        self.contar('estudiantes', Alumno.objects.count())
        self.contar('tutores', Tutor.objects.count())
        self.contar('inscripciones', Inscripcion.objects.count())

    def _desempeno(self):
        suerte = self.rng.random()
        if suerte < 0.08:
            return self.rng.uniform(5.4, 6.4)
        if suerte < 0.28:
            return self.rng.uniform(9.1, 9.8)
        return self.rng.uniform(7.0, 9.1)

    def bloque(self):
        """Inglés de 1.º de secundaria (grupos A y B) repartido en tres niveles a la misma hora, con tres docentes."""
        from Alumnos.models import BloqueSimultaneo
        from Asignaciones import bloques
        a, b = self.grupos[('SECUNDARIA', 1, 'A')], self.grupos[('SECUNDARIA', 1, 'B')]
        ingles = self.materias[('SECUNDARIA', 1, 4)]
        base = list(MateriaGrado.objects.filter(ciclo=self.ciclo, materia=ingles))
        maestros = [self.docente_de('SECUNDARIA', 'ingles', 0)] + [p for p, nivel, area, _ in self.profesores if area == 'ingles_bloque']
        estudiantes = [i for i in self.inscripciones if i.grupo_id in (a.pk, b.pk)]
        estudiantes.sort(key=lambda i: self.nivel_de[i.alumno_id])
        tercio = len(estudiantes) // 3
        reparto = [estudiantes[:tercio], estudiantes[tercio:2 * tercio], estudiantes[2 * tercio:]]
        with reloj(momento(self.inicio - timedelta(days=3), 10)):
            bloque = BloqueSimultaneo.objects.create(nombre='Inglés por niveles de 1.º', nivel='SECUNDARIA', ciclo=self.ciclo,
                                                     vigente_desde=self.inicio, vigente_hasta=self.fin, creado_por=self.admin)
            bloque.grupos_origen.set([a, b])
            bloque.sustituye.set(base)
            h1, m1, h2, m2 = D.HORA_DEL_BLOQUE
            bloques.guardar_horarios(bloque, [(dia, time(h1, m1), time(h2, m2), '') for dia in range(5)])
            for nombre, maestro, aula, integrantes in zip(('Básico', 'Intermedio', 'Avanzado'), maestros, ('Aula 11', 'Aula 12', 'Aula 13'), reparto):
                clase = bloques.crear_opcion(bloque, {'nombre': nombre, 'materia': ingles, 'profesor': maestro, 'aula': aula}, self.admin)
                bloques.asignar(bloque, clase, integrantes, None, self.admin)
            problemas = bloques.problemas_para_activar(bloque)
            if problemas:
                self.avisar(f'  El bloque no se activó: {problemas}')
                return
        with reloj(momento(self.inicio, 7)):
            bloques.activar(bloque, self.admin)
        self.contar('bloques simultáneos')

    # ------------------------------------------------------------------
    # Asistencia
    # ------------------------------------------------------------------
    def asistencia(self):
        from Alumnos.asistencias import EntradaRechazada, cerrar_dia, registrar_entrada
        for fecha, motivo in self.motivos_festivos:
            if self.inicio <= fecha <= self.fin:
                for nivel in NIVELES:
                    DiaNoLectivo.objects.create(fecha=fecha, nivel=nivel, motivo=motivo)
        desde = max(self.inicio, self.hoy - timedelta(days=45))
        dias = self.dias_de_clase(desde, self.hoy)
        alumnos = [i.alumno for i in self.inscripciones]
        for fecha in dias:
            for alumno in alumnos:
                if self.rng.random() < self.ausentismo[alumno.pk]:
                    continue
                suerte = self.rng.random()
                if suerte < 0.08:
                    hora, minuto = 8, self.rng.randint(11, 25)     # con retardo
                elif suerte < 0.16:
                    hora, minuto = 8, self.rng.randint(0, 10)      # dentro de la tolerancia
                else:
                    hora, minuto = 7, self.rng.randint(30, 59)
                if fecha == self.hoy and momento(fecha, hora, minuto) > timezone.now():
                    continue
                try:
                    registrar_entrada(alumno, 'UID' if self.rng.random() < 0.85 else 'REFERENCIA', momento=momento(fecha, hora, minuto))
                except EntradaRechazada:
                    pass
            if fecha < self.hoy:
                with reloj(momento(fecha, 15)):
                    cerrar_dia(fecha, automatico=True)
        from Alumnos.models import AsistenciaGeneral, AsistenciaMateria
        self.contar('registros de entrada', AsistenciaGeneral.objects.count())
        self.contar('asistencias por materia', AsistenciaMateria.objects.count())

    def justificaciones(self):
        from Alumnos.models import AsistenciaGeneral
        from Prefectura.asistencia import JustificacionRechazada, justificar, por_justificar
        faltas = list(AsistenciaGeneral.objects.filter(estado='FALTA', fecha__lt=self.hoy).select_related('inscripcion__grado'))
        self.rng.shuffle(faltas)
        motivos = ('Consulta médica', 'Enfermedad (gripe)', 'Trámite familiar', 'Cita con el dentista')
        for falta in faltas[:max(1, len(faltas) // 3)]:
            afectados = por_justificar(falta.inscripcion, falta.fecha, falta.fecha)
            if not afectados:
                continue
            try:
                with reloj(momento(falta.fecha + timedelta(days=1), 9, 15)):
                    justificar(falta.inscripcion, falta.fecha, falta.fecha, ('FALTA',), True, [a.clave for a in afectados],
                               self.rng.choice(motivos), None, self.prefectura)
                self.contar('justificaciones')
            except JustificacionRechazada:
                pass

    # ------------------------------------------------------------------
    # Calificaciones y comentarios
    # ------------------------------------------------------------------
    def _valor(self, base, ruido=0.8, minimo=Decimal('4.0')):
        valor = max(float(minimo), min(10.0, self.rng.gauss(base, ruido)))
        return Decimal(f'{valor:.1f}')

    def _calificar(self, ciclo):
        from Calificaciones import reglas
        from Calificaciones.models import CalificacionActividad, CalificacionRubro
        configuraciones = {}
        for asignacion in MateriaGrado.objects.filter(ciclo=ciclo, activa=True).select_related('materia', 'ciclo', 'grado', 'grupo', 'profesor__usuario'):
            autor = asignacion.profesor.usuario if asignacion.profesor_id and asignacion.profesor.usuario_id else self.admin
            for periodo in reglas.periodos_de(asignacion):
                if periodo.fecha_inicio > self.hoy:
                    continue
                acta = reglas.acta_para(asignacion, periodo)
                inscripciones = reglas.estudiantes_de(acta)
                if not inscripciones:
                    continue
                if asignacion.materia_id not in configuraciones:
                    configuraciones[asignacion.materia_id] = (reglas.configuracion_de(asignacion.materia, ciclo)
                                                             or reglas.crear_inicial(asignacion.materia, ciclo, self.admin))
                conducta, procedimientos, examenes = configuraciones[asignacion.materia_id].rubros.order_by('orden')
                cerrada = periodo.fecha_fin < self.hoy
                fin = min(periodo.fecha_fin, self.hoy)
                avance = 1 if cerrada else max(0.25, (self.hoy - periodo.fecha_inicio).days / max(1, (periodo.fecha_fin - periodo.fecha_inicio).days))
                lista = [('PROCEDIMIENTO', procedimientos, n) for n in D.ACTIVIDADES['PROCEDIMIENTO'][:3]] + \
                        [('EXAMEN', examenes, n) for n in D.ACTIVIDADES['EXAMEN']]
                lista = lista[:max(1, round(len(lista) * avance))] if not cerrada else lista
                actividades = []
                dias = max(1, (fin - periodo.fecha_inicio).days)
                for orden, (tipo, rubro, nombre) in enumerate(lista, 1):
                    fecha = periodo.fecha_inicio + timedelta(days=dias * orden // (len(lista) + 1))
                    actividades.append(reglas.crear_actividad(acta, {'rubro': rubro, 'nombre': nombre, 'fecha': fecha}, autor))
                capturas, directas = [], []
                sesgo = self.rng.uniform(-0.4, 0.4)   # una materia más fácil o más difícil
                for inscripcion in inscripciones:
                    base = self.nivel_de.get(inscripcion.alumno_id, 8) + sesgo
                    for actividad in actividades:
                        if not cerrada and actividad is actividades[-1] and self.rng.random() < 0.15:
                            continue   # en el periodo abierto, algunos pendientes
                        capturas.append(CalificacionActividad(actividad=actividad, inscripcion=inscripcion, valor=self._valor(base), modificado_por=autor))
                    if cerrada or self.rng.random() < 0.6:
                        directas.append(CalificacionRubro(acta=acta, rubro=conducta, inscripcion=inscripcion, valor=self._valor(base + 0.6, 0.5, Decimal('6')),
                                                          modificado_por=autor))
                CalificacionActividad.objects.bulk_create(capturas)
                CalificacionRubro.objects.bulk_create(directas)
                self.contar('calificaciones capturadas', len(capturas) + len(directas))
                if cerrada:
                    try:
                        with reloj(momento(periodo.fecha_fin + timedelta(days=2), 13, self.rng.randint(0, 59))):
                            reglas.cerrar(acta, autor)
                        self.contar('actas cerradas')
                    except reglas.CapturaRechazada as error:
                        self.avisar(f'  No se cerró {acta}: {error.mensaje}')
                else:
                    self.contar('actas en captura')

    def calificaciones(self):
        self._calificar(self.previo)
        self._calificar(self.ciclo)

    def comentarios(self):
        from Calificaciones import comentarios
        from Calificaciones.models import CambioComentario, ComentarioPeriodo
        periodos = [p for p in Periodo.objects.filter(ciclo=self.ciclo, fecha_inicio__lte=self.hoy).order_by('fecha_inicio')]
        for periodo in periodos:
            cerrado = periodo.fecha_fin < self.hoy
            fecha = min(periodo.fecha_fin - timedelta(days=2), self.hoy - timedelta(days=1))
            nuevos, cambios = [], []
            for asignacion in MateriaGrado.objects.filter(ciclo=self.ciclo, grado__nivel=periodo.nivel, activa=True).select_related(
                    'materia', 'ciclo', 'grado', 'grupo', 'profesor__usuario', 'clase__bloque'):
                if not any(p.pk == periodo.pk for p in comentarios.reglas.periodos_de(asignacion)):
                    continue
                autor = asignacion.profesor.usuario if asignacion.profesor_id and asignacion.profesor.usuario_id else self.admin
                for fila in comentarios.captura(asignacion, periodo).filas:
                    if fila.comentario is not None or (not cerrado and self.rng.random() > 0.45):
                        continue
                    nivel = self.nivel_de.get(fila.inscripcion.alumno_id, 8)
                    texto = self.rng.choice(D.COMENTARIOS['alto' if nivel >= 9 else ('bajo' if nivel < 6.8 else 'medio')])
                    cuando = momento(fecha, 16, self.rng.randint(0, 59))
                    nuevos.append(ComentarioPeriodo(inscripcion=fila.inscripcion, materia=fila.materia, periodo=periodo, asignacion=asignacion, texto=texto,
                                                    autor=autor, docente=comentarios.nombre_de_docente(autor), capturado_en=cuando, actualizado_por=autor,
                                                    actualizado_en=cuando, version=1))
                    cambios.append(CambioComentario(inscripcion=fila.inscripcion, periodo=periodo, materia=fila.materia, accion=CambioComentario.CAPTURA,
                                                    nuevo=texto, usuario=autor, datos={'asignacion': asignacion.pk}))
            ComentarioPeriodo.objects.bulk_create(nuevos)
            CambioComentario.objects.bulk_create(cambios)
            self.contar('comentarios', len(nuevos))
            if cerrado:
                for inscripcion in Inscripcion.objects.filter(ciclo=self.ciclo, grado__nivel=periodo.nivel, activa=True).select_related('alumno', 'grado', 'grupo', 'ciclo'):
                    if self.rng.random() < 0.9:
                        try:
                            with reloj(momento(periodo.fecha_fin + timedelta(days=5), 10)):
                                comentarios.publicar(inscripcion, periodo, self.direccion)
                            self.contar('boletas de comentarios publicadas')
                        except comentarios.ComentarioRechazado:
                            pass

    # ------------------------------------------------------------------
    # Conducta y bitácoras
    # ------------------------------------------------------------------
    def conducta(self):
        from Conducta import reglas
        from Conducta.models import CategoriaConducta, MedidaDisciplinaria, MotivoConducta, RegistroConducta
        catalogo = {}
        for nivel in NIVELES:
            for tipo, nombre, motivos in D.CATEGORIAS_CONDUCTA:
                categoria = CategoriaConducta.objects.create(nivel=nivel, nombre=nombre, tipo=tipo)
                for motivo, gravedad in motivos:
                    catalogo.setdefault((nivel, tipo), []).append(MotivoConducta.objects.create(categoria=categoria, nombre=motivo, gravedad=gravedad))
            for nombre, seguimiento in D.MEDIDAS:
                MedidaDisciplinaria.objects.create(nivel=nivel, nombre=nombre, requiere_seguimiento=seguimiento, disponible_prefectura=True)
        pesos = {'PREESCOLAR': 1, 'PRIMARIA': 4, 'SECUNDARIA': 8, 'PREPARATORIA': 4}
        candidatos = [i for i in self.inscripciones for _ in range(pesos[i.grado.nivel])]
        dias = self.dias_de_clase(max(self.inicio, self.hoy - timedelta(days=40)), self.hoy - timedelta(days=1))
        for _ in range(65):
            inscripcion = self.rng.choice(candidatos)
            nivel = inscripcion.grado.nivel
            positiva = self.rng.random() < 0.22
            motivo = self.rng.choice(catalogo[(nivel, 'POSITIVA' if positiva else 'INCIDENCIA')])
            fecha = self.rng.choice(dias)
            hora = time(self.rng.randint(8, 13), self.rng.choice((0, 15, 30, 45)))
            reciente = (self.hoy - fecha).days < 12
            estado = RegistroConducta.CERRADO if positiva or not reciente else self.rng.choice((RegistroConducta.PENDIENTE, RegistroConducta.EN_SEGUIMIENTO))
            medidas = [] if positiva else list(MedidaDisciplinaria.objects.filter(nivel=nivel, nombre__in=(
                ('Llamada de atención',) if motivo.gravedad == 'LEVE' else ('Aviso a los padres', 'Citatorio a padres'))))
            autor = self.prefectura if self.rng.random() < 0.75 else self.direccion
            datos = {
                'fecha': fecha, 'hora': hora, 'lugar': self.rng.choice(D.LUGARES), 'tipo': motivo.categoria.tipo, 'categoria': motivo.categoria,
                'motivo': motivo, 'gravedad': motivo.gravedad, 'descripcion': D.DESCRIPCIONES_CONDUCTA[motivo.nombre], 'observaciones_medidas': '',
                'responsable': self.prefectura if estado == RegistroConducta.EN_SEGUIMIENTO else None,
                'fecha_revision': self.hoy + timedelta(days=self.rng.randint(2, 10)) if estado == RegistroConducta.EN_SEGUIMIENTO else None,
                'estado': estado, 'acuerdos': 'Se habló con el estudiante y se acordó mejorar su conducta.' if not positiva else '',
                'observaciones_cierre': 'Sin incidencias posteriores.' if estado == RegistroConducta.CERRADO and not positiva else '',
                'reporta': autor.get_full_name(), 'medidas': medidas, 'suspension_motivo': None,
            }
            contexto = reglas.contexto_escolar(inscripcion, fecha)
            contexto.pop('periodo')
            with reloj(momento(fecha, hora.hour, hora.minute) + timedelta(minutes=20)):
                reglas.guardar_registro(RegistroConducta(**contexto), datos, autor)
            self.contar('registros de conducta')

    def _titular(self, inscripcion):
        asignacion = MateriaGrado.objects.filter(ciclo=self.ciclo, grupo=inscripcion.grupo, profesor__usuario__isnull=False).select_related('profesor__usuario').first()
        return asignacion.profesor.usuario if asignacion else None

    def bitacoras(self):
        from Bitacoras import reglas
        asignaciones = [a for a in self.asignaciones_actuales if a.profesor_id]
        dias = self.dias_de_clase(max(self.inicio, self.hoy - timedelta(days=30)), self.hoy - timedelta(days=1))
        for _ in range(30):
            asignacion = self.rng.choice(asignaciones)
            fecha = self.rng.choice(dias)
            titulo, descripcion = self.rng.choice(D.BITACORAS)
            general = self.rng.random() < 0.7
            alumnos = [] if general else [i.alumno for i in self.rng.sample([i for i in self.inscripciones if i.grupo_id == asignacion.grupo_id], 2)]
            with reloj(momento(fecha, 14, self.rng.randint(0, 59))):
                reglas.crear({'asignacion': asignacion, 'fecha': fecha, 'general': general, 'titulo': titulo, 'descripcion': descripcion,
                              'seguimiento': '' if general else 'Platicar con sus tutores si se repite.', 'alumnos': alumnos},
                             asignacion.profesor.usuario, clave_envio=uuid.uuid4())
            self.contar('entradas de bitácora')

    # ------------------------------------------------------------------
    # Retiros y reuniones
    # ------------------------------------------------------------------
    def _familias(self, cantidad, niveles=NIVELES):
        """Tutores con portal y uno de sus hijos inscritos (de esos niveles)."""
        vinculos = list(TutorAlumno.objects.filter(tutor_principal=True, tutor__acceso_portal=True, alumno__inscripciones__ciclo=self.ciclo,
                                                   alumno__inscripciones__grado__nivel__in=niveles).select_related('tutor', 'alumno').distinct())
        return self.rng.sample(vinculos, min(cantidad, len(vinculos)))

    def retiros(self):
        from Retiros import reglas
        from Retiros.models import MotivoRetiro, RetiroEstudiante
        motivos = list(MotivoRetiro.objects.filter(activo=True, requiere_explicacion=False)) or list(MotivoRetiro.objects.filter(activo=True))
        dias = self.dias_de_clase(max(self.inicio, self.hoy - timedelta(days=25)), self.hoy - timedelta(days=1))
        for vinculo in self._familias(7):
            fecha = self.rng.choice(dias)
            try:
                with reloj(momento(fecha, 8, 40)):
                    aviso = reglas.avisar(vinculo.tutor, [vinculo.alumno.pk], fecha, time(10, 45), self.rng.choice(motivos), 'Cita médica a las 11:30.', vinculo.tutor)
                with reloj(momento(fecha, 10, 50)):
                    for retiro in RetiroEstudiante.objects.filter(aviso=aviso):
                        reglas.confirmar_salida(retiro, self.prefectura, vinculo.tutor, timezone.now())
                self.contar('retiros confirmados')
            except reglas.RetiroRechazado as error:
                self.avisar(f'  Retiro no registrado: {error}')
        # Avisos por atender: hoy (si todavía no pasa la hora) o el siguiente día de clases
        siguiente = next(d for d in self.dias_de_clase(self.hoy, self.hoy + timedelta(days=10)) if d > self.hoy or timezone.localtime().hour < 10)
        for vinculo in self._familias(2):
            try:
                reglas.avisar(vinculo.tutor, [vinculo.alumno.pk], siguiente, time(10, 45), self.rng.choice(motivos), 'Lo recojo para una cita.', vinculo.tutor)
                self.contar('retiros por atender')
            except reglas.RetiroRechazado as error:
                self.avisar(f'  Retiro no registrado: {error}')

    def reuniones(self):
        from Reuniones import reglas
        from Reuniones.models import MotivoReunion, Reunion, SalaReunion
        motivos = list(MotivoReunion.objects.filter(activo=True))
        salas = list(SalaReunion.objects.filter(activo=True))
        pasados = self.dias_de_clase(max(self.inicio, self.hoy - timedelta(days=25)), self.hoy - timedelta(days=3))
        futuros = self.dias_de_clase(self.hoy + timedelta(days=1), self.hoy + timedelta(days=15))
        familias = self._familias(9, ('PREESCOLAR', 'PRIMARIA', 'SECUNDARIA'))

        def nueva(vinculo, cuando, docente):
            with reloj(cuando):
                return reglas.registrar(tutor=vinculo.tutor, alumnos=[vinculo.alumno], telefono=vinculo.tutor.telefono, area=Reunion.DOCENTE,
                                        motivo=self.rng.choice(motivos), descripcion='La familia pide hablar sobre el avance académico de su hijo(a).',
                                        usuario=self.recepcion, docentes=[docente], acompanante=self.direccion, telefono_verificado=True)

        for indice, vinculo in enumerate(familias):
            docente = self._titular(Inscripcion.objects.get(alumno=vinculo.alumno, ciclo=self.ciclo))
            if docente is None:
                continue
            try:
                if indice < 4:   # ya realizadas, con minuta y un acuerdo
                    dia = self.rng.choice(pasados)
                    reunion = nueva(vinculo, momento(dia - timedelta(days=3), 10), docente)
                    with reloj(momento(dia - timedelta(days=2), 9)):
                        reglas.programar(reunion, fecha=dia, inicio=time(14, 0), fin=time(14, 30), sala=self.rng.choice(salas), usuario=self.recepcion)
                    with reloj(momento(dia, 14, 2)):
                        reunion.refresh_from_db()
                        reglas.iniciar(reunion, presentes=[p.pk for p in reunion.participantes.filter(activo=True)],
                                       tutores_presentes=[t.pk for t in reunion.tutores.all()], usuario=docente)
                    with reloj(momento(dia, 14, 35)):
                        reunion.refresh_from_db()
                        reglas.finalizar(reunion, datos={'inicio_real': time(14, 0), 'fin_real': time(14, 30),
                                                         'temas': 'Avance académico y hábitos de estudio.',
                                                         'resumen': 'Se revisaron las calificaciones del periodo y se acordó una rutina de estudio en casa.'},
                                         presentes_toda=[p.pk for p in reunion.participantes.filter(activo=True).exclude(usuario=docente)],
                                         usuario=docente, puede_confidencial=True)
                        reunion.refresh_from_db()
                        reglas.guardar_acuerdo(reunion, datos={'descripcion': 'Revisar diariamente las tareas en casa.', 'quien': 'FAMILIA',
                                                               'responsable': docente, 'responsable_texto': str(vinculo.tutor),
                                                               'fecha_limite': dia + timedelta(days=21), 'compartido': True}, usuario=docente)
                    self.contar('reuniones realizadas')
                elif indice < 7 and futuros:   # programadas
                    reunion = nueva(vinculo, timezone.now() - timedelta(hours=2), docente)
                    reglas.programar(reunion, fecha=self.rng.choice(futuros), inicio=time(14, 0), fin=time(14, 30), sala=self.rng.choice(salas), usuario=self.recepcion)
                    self.contar('reuniones programadas')
                else:   # solicitudes por atender
                    nueva(vinculo, timezone.now() - timedelta(hours=1), docente)
                    self.contar('solicitudes de reunión')
            except reglas.ReglaRota as error:
                self.avisar(f'  Reunión no registrada: {error}')

    # ------------------------------------------------------------------
    # Agenda, comunicados y mensajes
    # ------------------------------------------------------------------
    def agenda(self):
        from Agenda import reglas
        from Agenda.models import COLEGIO, DEPORTES, EXAMENES, FESTIVAL, JUNTA, VACACIONES, EventoAgenda
        lunes = self.hoy - timedelta(days=self.hoy.weekday())

        def evento(titulo, alcance, inicio, fin=None, horas=None, tipo='', lugar='', descripcion='', repetir='', hasta=None, **extra):
            datos = {'titulo': titulo, 'alcance': alcance, 'tipo': tipo, 'fecha_inicio': inicio, 'fecha_fin': fin or inicio, 'todo_el_dia': horas is None,
                     'hora_inicio': time(*horas[0]) if horas else None, 'hora_fin': time(*horas[1]) if horas else None, 'lugar': lugar,
                     'descripcion': descripcion, 'para_familias': True, 'para_estudiantes': True}
            datos.update(extra)
            with reloj(momento(self.inicio - timedelta(days=5), 9)):
                reglas.crear(EventoAgenda(**datos), self.direccion, repetir=repetir, hasta=hasta)
            self.contar('eventos de agenda')

        evento('Honores a la bandera', COLEGIO, lunes - timedelta(weeks=3), horas=((8, 0), (8, 20)), tipo=FESTIVAL, lugar='Patio central',
               repetir=reglas.SEMANAL, hasta=lunes + timedelta(weeks=8))
        for fecha, motivo in self.motivos_festivos:
            if self.inicio <= fecha <= self.fin:
                evento(f'Sin clases: {motivo}', COLEGIO, fecha, tipo=VACACIONES)
        evento('Vacaciones de invierno', COLEGIO, date(self.inicio.year, 12, 21), date(self.inicio.year + 1, 1, 6), tipo=VACACIONES, importante=True)
        for periodo in Periodo.objects.filter(ciclo=self.ciclo, fecha_fin__gte=self.hoy - timedelta(days=30), fecha_fin__lte=self.hoy + timedelta(days=60)):
            evento(f'Exámenes de {periodo.nombre}', periodo.nivel, periodo.fecha_fin - timedelta(days=4), periodo.fecha_fin, tipo=EXAMENES)
            evento(f'Entrega de boletas de {periodo.nombre}', periodo.nivel, periodo.fecha_fin + timedelta(days=7), horas=((13, 30), (14, 30)), tipo=JUNTA,
                   lugar='Salón de cada grupo', importante=True, pide_confirmacion=True)
        evento('Torneo interescolar de fútbol', 'SECUNDARIA', self.hoy + timedelta(days=9), tipo=DEPORTES, lugar='Unidad deportiva')
        evento('Festival navideño', COLEGIO, date(self.inicio.year, 12, 17), horas=((10, 0), (12, 30)), tipo=FESTIVAL, lugar='Auditorio', importante=True)
        evento('Feria de ciencias', 'PRIMARIA', self.hoy + timedelta(days=16), horas=((9, 0), (13, 0)), tipo=FESTIVAL, lugar='Patio central')
        evento('Junta de consejo técnico', COLEGIO, self.hoy + timedelta(days=4), horas=((14, 0), (16, 0)), tipo=JUNTA, para_familias=False, para_estudiantes=False)
        evento('Visita al museo regional', 'PREPARATORIA', self.hoy - timedelta(days=8), horas=((9, 0), (13, 0)), lugar='Museo Regional')

    def comunicados(self):
        from Comunicados import reglas
        from Comunicados.models import Comunicado, Destinatario
        tutores = set(TutorAlumno.objects.filter(activo=True, alumno__inscripciones__ciclo=self.ciclo).values_list('tutor_id', flat=True))
        cuarto = set(TutorAlumno.objects.filter(activo=True, alumno__inscripciones__ciclo=self.ciclo, alumno__inscripciones__grado__nivel='PRIMARIA',
                                                alumno__inscripciones__grado__numero=4).values_list('tutor_id', flat=True))
        prepa = set(Alumno.objects.filter(inscripciones__ciclo=self.ciclo, inscripciones__grado__nivel='PREPARATORIA').values_list('pk', flat=True))
        profesores = set(Profesor.objects.values_list('pk', flat=True))
        envios = (
            (self.inicio + timedelta(days=1), 'Bienvenida al ciclo escolar', 'Les damos la bienvenida al nuevo ciclo escolar. Les compartimos el calendario y '
             'las indicaciones de entrada y salida.', {Destinatario.TUTOR: tutores}, {}),
            (self.hoy - timedelta(days=12), 'Reunión de padres de familia de 4.º', 'Les esperamos el próximo jueves a las 18:00 en el salón de su grupo '
             'para revisar los avances del bimestre.', {Destinatario.TUTOR: cuarto}, {'respuesta': Comunicado.ENTERADO}),
            (self.hoy - timedelta(days=6), 'Campaña de vacunación', 'El centro de salud aplicará la vacuna contra la influenza en el colegio. '
             'Indiquen si autorizan que su hijo(a) la reciba.', {Destinatario.TUTOR: tutores}, {'respuesta': Comunicado.AUTORIZACION,
                                                                                                    'pregunta': '¿Autoriza que su hijo(a) reciba la vacuna?'}),
            (self.hoy - timedelta(days=5), 'Encuesta: horario del festival navideño', 'Ayúdennos a elegir el horario del festival.',
             {Destinatario.TUTOR: tutores}, {'respuesta': Comunicado.ENCUESTA, 'pregunta': '¿Qué horario le acomoda mejor?',
                                             'opciones': ('Por la mañana (10:00)', 'Por la tarde (17:00)')}),
            (self.hoy - timedelta(days=3), 'Suspensión de clases por consejo técnico', 'Les recordamos que el próximo viernes no habrá clases por la '
             'sesión de consejo técnico escolar.', {Destinatario.TUTOR: tutores}, {'urgente': True}),
            (self.hoy - timedelta(days=2), 'Entrega de proyectos de bachillerato', 'La fecha límite para entregar el proyecto integrador es el viernes.',
             {Destinatario.ESTUDIANTE: prepa}, {}),
            (self.hoy - timedelta(days=1), 'Junta de academia', 'Junta de academia el próximo martes a las 14:00 en la sala de maestros.',
             {Destinatario.PROFESOR: profesores}, {}),
        )
        for fecha, titulo, texto, seleccion, extra in envios:
            if fecha > self.hoy:
                continue
            with reloj(momento(fecha, 9, self.rng.randint(0, 59))):
                comunicado, _ = reglas.enviar(self.direccion, titulo=titulo, descripcion=texto, urgente=extra.pop('urgente', False), expira=None,
                                              clave_envio=uuid.uuid4(), seleccion=seleccion, **extra)
            destinatarios = list(Destinatario.objects.filter(comunicado=comunicado))
            leidos = self.rng.sample(destinatarios, int(len(destinatarios) * self.rng.uniform(0.45, 0.8)))
            for destinatario in leidos:
                destinatario.leido_en = momento(fecha, 9) + timedelta(hours=self.rng.randint(1, 30))
            Destinatario.objects.bulk_update(leidos, ['leido_en'])
            self.contar('comunicados')

    def mensajes(self):
        from CISAHUAYO import portales
        from Mensajes import reglas
        conversaciones = (
            ('Buenas tardes, maestra. ¿Me podría decir qué temas vendrán en el examen?', 'Claro, vienen fracciones y medidas. Les envié la guía en la libreta.',
             'Muchas gracias, la repasamos el fin de semana.'),
            ('Buen día. Mi hijo no podrá asistir mañana por una cita médica.', 'Gracias por avisar. Le guardo las actividades del día.'),
            ('Maestro, ¿cómo va mi hija con las tareas?', 'Va bien, solo le faltó entregar la del martes. Puede traerla el lunes.', '¡Gracias! La entregará el lunes.'),
        )
        for vinculo, textos in zip(self._familias(len(conversaciones), ('PRIMARIA', 'SECUNDARIA')), conversaciones):
            docente = self._titular(Inscripcion.objects.get(alumno=vinculo.alumno, ciclo=self.ciclo))
            if docente is None:
                continue
            uno, otro = reglas.de_portal(portales.TUTOR, vinculo.tutor), reglas.de_usuario(docente)
            conversacion = reglas.conversacion_con(uno, otro)
            cuando = momento(self.hoy - timedelta(days=self.rng.randint(1, 6)), 17)
            for numero, texto in enumerate(textos):
                with reloj(cuando + timedelta(minutes=37 * numero)):
                    reglas.enviar(conversacion, uno if numero % 2 == 0 else otro, texto)
                self.contar('mensajes')
        # Entre el personal
        conversacion = reglas.conversacion_con(reglas.de_usuario(self.direccion), reglas.de_usuario(self.coordinacion))
        for numero, (autor, texto) in enumerate(((self.direccion, '¿Ya tenemos lista la agenda del consejo técnico?'),
                                                 (self.coordinacion, 'Sí, se la envío hoy por la tarde.'))):
            with reloj(momento(self.hoy - timedelta(days=1), 10) + timedelta(minutes=12 * numero)):
                reglas.enviar(conversacion, reglas.de_usuario(autor), texto)
            self.contar('mensajes')
