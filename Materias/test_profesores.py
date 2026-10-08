"""El profesor en el perfil de la materia y al copiar el plan de un ciclo a otro."""
from datetime import time

from django.urls import reverse

from Alumnos.models import HorarioMateria, Materia, MateriaGrado
from CISAHUAYO.pruebas import (
    PRUEBAS,
    BaseTestCase,
    ciclo_actual_de_prueba,
    ciclo_cerrado_de_prueba,
    ciclo_proximo_de_prueba,
    crear_grado,
    crear_profesor,
)


def crear_materia(clave='MAT', nombre='Matemáticas', **cambios):
    return Materia.objects.create(clave=clave, nombre=nombre, **cambios)


def asignar(materia, grado, ciclo, **cambios):
    return MateriaGrado.objects.create(materia=materia, grado=grado, ciclo=ciclo, **cambios)


def bloque(asignacion, dia=0, inicio=(8, 0), fin=(9, 0)):
    return HorarioMateria.objects.create(materia_grado=asignacion, dia_semana=dia, hora_inicio=time(*inicio), hora_fin=time(*fin))


# ---------------------------------------------------------------------------
# Perfil de la materia
# ---------------------------------------------------------------------------
@PRUEBAS
class DetalleConProfesorTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.ciclo = ciclo_actual_de_prueba()
        self.cerrado = ciclo_cerrado_de_prueba()
        self.profesor = crear_profesor()
        self.p1 = crear_grado('PRIMARIA', 1)
        self.materia = crear_materia(grado=self.p1)
        self.a1 = asignar(self.materia, self.p1, self.ciclo)

    def detalle(self, **parametros):
        return self.client.get(self.materia.get_absolute_url(), parametros)

    def test_muestra_quien_da_la_materia(self):
        respuesta = self.detalle()
        self.assertContains(respuesta, 'Sin profesor')
        self.assertContains(respuesta, 'Asignar profesor')
        MateriaGrado.objects.filter(pk=self.a1.pk).update(profesor=self.profesor)
        respuesta = self.detalle()
        self.assertContains(respuesta, self.profesor.get_absolute_url())
        self.assertContains(respuesta, 'Cambiar profesor')

    def test_ofrece_solo_profesores_activos(self):
        baja = crear_profesor(nombre='Baja', telefono='3530000009', estatus='INACTIVO')
        respuesta = self.detalle()
        self.assertEqual(respuesta.context['profesores_activos'], [self.profesor])
        self.assertNotIn(baja, respuesta.context['profesores_activos'])
        self.assertContains(respuesta, 'modal-asignar-profesor')

    def test_lo_de_un_ciclo_cerrado_no_se_asigna_desde_aqui(self):
        asignar(self.materia, self.p1, self.cerrado, profesor=self.profesor)
        respuesta = self.detalle()
        self.assertContains(respuesta, 'Otros ciclos')
        self.assertEqual(len(respuesta.content.decode().split('data-asignar-profesor')) - 1, 1)   # solo la del ciclo actual

    def test_asignar_desde_el_perfil_vuelve_al_perfil(self):
        respuesta = self.client.post(reverse('profesores:asignar'), {
            'asignacion': self.a1.pk, 'profesor': self.profesor.pk, 'next': self.materia.get_absolute_url(),
        }, follow=True)
        self.assertRedirects(respuesta, self.materia.get_absolute_url())
        self.assertContains(respuesta, 'imparte ahora Matemáticas en 1° Primaria')
        self.assertEqual(respuesta.context['clases'][0].profesor, self.profesor)


# ---------------------------------------------------------------------------
# Copiar el plan conservando al profesor
# ---------------------------------------------------------------------------
@PRUEBAS
class CopiarPlanConProfesorTests(BaseTestCase):
    url = property(lambda self: reverse('materias:copiar'))

    def setUp(self):
        super().setUp()
        self.origen = ciclo_actual_de_prueba('2026-2027')
        self.destino = ciclo_proximo_de_prueba('2027-2028')
        self.marta = crear_profesor()
        self.beto = crear_profesor(nombre='Beto', apellido_paterno='Aguilar', telefono='3530000002')
        self.mat, self.esp = crear_materia('MAT', 'Matemáticas'), crear_materia('ESP', 'Español')
        self.p1, self.p2 = crear_grado('PRIMARIA', 1), crear_grado('PRIMARIA', 2)
        self.a1 = asignar(self.mat, self.p1, self.origen, profesor=self.marta)
        self.a2 = asignar(self.esp, self.p2, self.origen, profesor=self.marta)
        self.a3 = asignar(self.esp, self.p1, self.origen)                       # sin profesor
        bloque(self.a1, 0, (8, 0), (9, 0))
        bloque(self.a2, 1, (8, 0), (9, 0))

    def copiar(self, horarios=True, conservar=True, follow=False):
        datos = {'origen': self.origen.pk, 'destino': self.destino.pk}
        if horarios:
            datos['horarios'] = 'on'
        if conservar:
            datos['conservar_profesor'] = 'on'
        return self.client.post(self.url, datos, follow=follow)

    def profesor_copiado(self, materia, grado):
        return MateriaGrado.objects.get(ciclo=self.destino, materia=materia, grado=grado).profesor

    def test_la_vista_previa_cuenta_las_materias_con_profesor_activo(self):
        self.beto.estatus = 'INACTIVO'
        self.beto.save()
        self.a3.profesor = self.beto
        self.a3.save()
        respuesta = self.client.get(self.url, {'origen': self.origen.pk, 'destino': self.destino.pk})
        self.assertEqual(respuesta.context['total_con_profesor'], 2)                # la del profesor de baja no cuenta
        self.assertContains(respuesta, 'de las 3 materias tienen un profesor activo')
        self.assertContains(respuesta, 'name="conservar_profesor"')

    def test_conserva_al_profesor_de_cada_materia(self):
        respuesta = self.copiar(follow=True)
        self.assertEqual(self.profesor_copiado(self.mat, self.p1), self.marta)
        self.assertEqual(self.profesor_copiado(self.esp, self.p2), self.marta)
        self.assertIsNone(self.profesor_copiado(self.esp, self.p1))
        self.assertNotContains(respuesta, 'quedaron sin profesor')

    def test_si_no_se_marca_la_opcion_se_copia_sin_profesor(self):
        self.copiar(conservar=False)
        self.assertFalse(MateriaGrado.objects.filter(ciclo=self.destino, profesor__isnull=False).exists())

    def test_no_se_copia_a_un_profesor_de_baja(self):
        self.marta.estatus = 'INACTIVO'
        self.marta.save()
        respuesta = self.copiar(follow=True)
        self.assertFalse(MateriaGrado.objects.filter(ciclo=self.destino, profesor__isnull=False).exists())
        self.assertContains(respuesta, '2 materias quedaron sin profesor')

    def test_no_cambia_nada_del_ciclo_de_origen(self):
        self.copiar()
        self.a1.refresh_from_db()
        self.assertEqual(self.a1.profesor, self.marta)
        self.assertEqual(MateriaGrado.objects.filter(ciclo=self.origen, profesor=self.marta).count(), 2)

    def test_un_empalme_con_clases_ya_registradas_en_el_destino_deja_esa_materia_sin_profesor(self):
        ocupada = asignar(crear_materia('HIS', 'Historia'), crear_grado('PRIMARIA', 3), self.destino, profesor=self.marta)
        bloque(ocupada, 0, (8, 30), (9, 30))                                           # choca con Matemáticas del lunes
        respuesta = self.copiar(follow=True)
        self.assertIsNone(self.profesor_copiado(self.mat, self.p1))
        self.assertEqual(self.profesor_copiado(self.esp, self.p2), self.marta)
        self.assertContains(respuesta, '1 materia quedó sin profesor')
        self.assertEqual(HorarioMateria.objects.filter(materia_grado__ciclo=self.destino, materia_grado__materia=self.mat).count(), 1)

    def test_un_empalme_entre_las_propias_materias_copiadas_solo_deja_pasar_la_primera(self):
        # En el origen no podían empalmarse; aquí se fuerza para comprobar que la copia nunca deja a nadie en dos grupos
        HorarioMateria.objects.filter(materia_grado=self.a2).update(dia_semana=0, hora_inicio=time(8, 30), hora_fin=time(9, 30))
        self.copiar()
        conservadas = MateriaGrado.objects.filter(ciclo=self.destino, profesor=self.marta)
        self.assertEqual(conservadas.count(), 1)

    def test_sin_copiar_horarios_no_hay_empalmes_que_revisar(self):
        ocupada = asignar(crear_materia('HIS', 'Historia'), crear_grado('PRIMARIA', 3), self.destino, profesor=self.marta)
        bloque(ocupada, 0, (8, 30), (9, 30))
        self.copiar(horarios=False)
        self.assertEqual(self.profesor_copiado(self.mat, self.p1), self.marta)

    def test_no_pisa_lo_que_el_destino_ya_tiene(self):
        existente = asignar(self.mat, self.p1, self.destino, profesor=self.beto)
        self.copiar()
        existente.refresh_from_db()
        self.assertEqual(existente.profesor, self.beto)
        self.assertEqual(MateriaGrado.objects.filter(ciclo=self.destino, materia=self.mat, grado=self.p1).count(), 1)
