"""Agenda / Calendario: el mes de lunes a domingo con eventos de varios días (entre semanas y meses) y «+N eventos»,
los colores por alcance, el registro, la edición y la eliminación (solo el administrador, también en el servidor), las
validaciones del formulario, el filtro por nivel y quién ve qué: el personal según sus niveles, un tutor según los
niveles de sus hijos y un estudiante según el suyo; los eventos de todo el colegio, una sola vez y para todos. La agenda
es informativa: registrar un evento no crea días sin clases ni toca asistencias."""
from datetime import date, time

from django.urls import reverse

from Alumnos.models import AsistenciaGeneral, DiaNoLectivo
from CISAHUAYO import portales
from CISAHUAYO.pruebas import (
    PRUEBAS, BaseTestCase, ciclo_actual_de_prueba, crear_alumno, crear_grado, crear_profesor, crear_tutor, crear_usuario,
    inscribir_antes, vincular,
)
from Usuarios.models import PerfilUsuario

from . import alcance, calendario
from .models import COLEGIO, EventoAgenda

CALENDARIO = reverse('agenda:calendario')
NUEVO = reverse('agenda:crear')
OCTUBRE = date(2026, 10, 1)


def evento(titulo, alcance_='PRIMARIA', inicio=date(2026, 10, 14), fin=None, horas=None, **cambios):
    return EventoAgenda.objects.create(
        titulo=titulo, alcance=alcance_, fecha_inicio=inicio, fecha_fin=fin or inicio, todo_el_dia=horas is None,
        hora_inicio=horas[0] if horas else None, hora_fin=horas[1] if horas else None, **cambios)


def entrar_al_portal(cliente, tipo, cuenta):
    sesion = cliente.session
    sesion[portales.CLAVE_DE_SESION] = {'tipo': tipo, 'id': cuenta.pk, 'huella': portales._huella(tipo, cuenta)}
    sesion.save()


def contraste(fondo, texto):
    """El contraste WCAG entre dos colores «#RRGGBB» (1 a 21)."""
    def luminancia(color):
        canales = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        lineales = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canales]
        return 0.2126 * lineales[0] + 0.7152 * lineales[1] + 0.0722 * lineales[2]
    claro, oscuro = sorted((luminancia(fondo), luminancia(texto)), reverse=True)
    return (claro + 0.05) / (oscuro + 0.05)


def ids_del_mes(respuesta):
    return [dato['id'] for dato in respuesta.context['datos_eventos']]


# ---------------------------------------------------------------------------
# El mes
# ---------------------------------------------------------------------------
class MesTests(BaseTestCase):
    def test_el_mes_va_de_lunes_a_domingo_con_los_dias_que_completan_sus_semanas(self):
        self.assertEqual(calendario.rango_visible(OCTUBRE), (date(2026, 9, 28), date(2026, 11, 1)))
        semanas = calendario.semanas([], OCTUBRE, hoy=date(2026, 10, 18))
        self.assertEqual(len(semanas), 5)
        dias = [dia for semana in semanas for dia in semana.dias]
        self.assertEqual([d.fecha.weekday() for d in semanas[0].dias], list(range(7)))
        self.assertEqual([d.fecha for d in dias if not d.en_mes], [date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30), date(2026, 11, 1)])
        self.assertEqual([d.fecha for d in dias if d.es_hoy], [date(2026, 10, 18)])

    def test_el_mes_se_elige_en_la_direccion_y_se_avanza_o_retrocede(self):
        hoy = date(2026, 10, 18)
        self.assertEqual(calendario.primer_dia('2027-02', hoy), date(2027, 2, 1))
        for invalido in ('', 'octubre', '2026-13', '2026-00', '99999-01'):
            self.assertEqual(calendario.primer_dia(invalido, hoy), OCTUBRE, invalido)
        self.assertEqual(calendario.mes_siguiente(date(2026, 12, 1)), date(2027, 1, 1))
        self.assertEqual(calendario.mes_anterior(date(2026, 1, 1)), date(2025, 12, 1))

    def test_un_evento_de_varios_dias_cruza_semanas_y_meses(self):
        ofrenda = evento('Ofrenda', COLEGIO, date(2026, 10, 28), date(2026, 11, 3))
        vacunas = evento('Vacunación', inicio=date(2026, 9, 28), fin=date(2026, 10, 2))

        octubre = calendario.semanas([ofrenda, vacunas], OCTUBRE, hoy=date(2026, 10, 18))
        primera = octubre[0].tramos
        self.assertEqual([(t.evento, t.inicio, t.fin, t.antes, t.despues) for t in primera], [(vacunas, 1, 5, False, False)])
        ultima = octubre[-1].tramos
        self.assertEqual([(t.evento, t.inicio, t.fin, t.antes, t.despues) for t in ultima], [(ofrenda, 3, 7, False, True)])
        self.assertEqual(ultima[0].columnas, 5)

        noviembre = calendario.semanas([ofrenda], date(2026, 11, 1), hoy=date(2026, 10, 18))
        self.assertEqual([(t.inicio, t.fin, t.antes, t.despues) for t in noviembre[0].tramos], [(3, 7, False, True)])
        self.assertEqual([(t.inicio, t.fin, t.antes, t.despues) for t in noviembre[1].tramos], [(1, 2, True, False)])
        self.assertEqual(noviembre[2].tramos, [])

    def test_las_barras_no_se_enciman_y_reusan_su_carril(self):
        larga = evento('Semana de la ciencia', 'SECUNDARIA', date(2026, 10, 5), date(2026, 10, 7))
        encima = evento('Honores', COLEGIO, date(2026, 10, 6), horas=(time(8), time(8, 30)))
        despues = evento('Junta', inicio=date(2026, 10, 9))
        semana = calendario.semanas([larga, encima, despues], OCTUBRE, hoy=OCTUBRE)[1]
        carriles = {t.evento.titulo: t.carril for t in semana.tramos}
        self.assertEqual(carriles, {'Semana de la ciencia': 0, 'Honores': 1, 'Junta': 0})
        self.assertEqual(semana.carriles, 2)

    def test_lo_que_no_cabe_en_un_dia_se_cuenta_como_mas_eventos(self):
        eventos = [evento(f'Evento {n}', inicio=date(2026, 10, 20), horas=(time(8 + n), time(9 + n))) for n in range(5)]
        semana = calendario.semanas(eventos, OCTUBRE, hoy=OCTUBRE)[3]
        martes = semana.dias[1]
        self.assertEqual(len(semana.tramos), calendario.CARRILES)
        self.assertEqual(semana.carriles, calendario.CARRILES)
        self.assertEqual(martes.ocultos, 2)
        self.assertEqual(martes.eventos, eventos)              # la lista de «+2 eventos» los trae todos, en orden

    def test_la_agenda_del_telefono_muestra_cada_evento_una_vez_por_fecha(self):
        ofrenda = evento('Ofrenda', COLEGIO, date(2026, 10, 28), date(2026, 11, 3))
        vacunas = evento('Vacunación', inicio=date(2026, 9, 28), fin=date(2026, 10, 2))
        junta = evento('Junta', inicio=date(2026, 10, 12), horas=(time(17), time(18)))
        temprano = evento('Honores', COLEGIO, date(2026, 10, 12), horas=(time(8), time(8, 30)))
        self.assertEqual(calendario.agenda_del_mes([ofrenda, junta, vacunas, temprano], OCTUBRE), [
            (date(2026, 10, 1), [vacunas]), (date(2026, 10, 12), [temprano, junta]), (date(2026, 10, 28), [ofrenda]),
        ])
        self.assertEqual(calendario.agenda_del_mes([ofrenda, vacunas], date(2026, 11, 1)), [(date(2026, 11, 1), [ofrenda])])


class EventoTests(BaseTestCase):
    def test_el_color_sale_del_alcance_con_texto_legible(self):
        esperados = {
            'PREESCOLAR': '#48A8D0', 'PRIMARIA': '#A1639C', 'SECUNDARIA': '#C64A24', 'PREPARATORIA': '#507735', COLEGIO: '#DFD327',
        }
        for clave, color in esperados.items():
            uno = evento(clave, clave)
            self.assertEqual(uno.color, color)
            self.assertGreaterEqual(contraste(uno.color, uno.color_texto), 4.5, clave)   # el texto se lee sobre el color
        self.assertEqual(evento('General', COLEGIO).nombre_alcance, 'Todos los niveles')

    def test_fechas_y_horario_en_texto(self):
        uno = evento('Junta', inicio=date(2026, 10, 12), horas=(time(17), time(18, 30)))
        self.assertEqual(uno.texto_de_fechas, 'Lunes 12 de octubre de 2026')
        self.assertEqual(uno.texto_de_horario, '17:00 a 18:30')
        varios = evento('Ofrenda', COLEGIO, date(2026, 10, 28), date(2026, 11, 3))
        self.assertEqual(varios.texto_de_fechas, 'Del 28 de octubre al 3 de noviembre de 2026')
        self.assertEqual(varios.texto_de_horario, 'Todo el día')
        de_un_anio_a_otro = evento('Vacaciones', COLEGIO, date(2026, 12, 21), date(2027, 1, 6))
        self.assertEqual(de_un_anio_a_otro.texto_de_fechas, 'Del 21 de diciembre de 2026 al 6 de enero de 2027')


# ---------------------------------------------------------------------------
# Registrar, editar y eliminar (el administrador)
# ---------------------------------------------------------------------------
@PRUEBAS
class GestionTests(BaseTestCase):
    def datos(self, **cambios):
        datos = {
            'titulo': 'Festival de otoño', 'alcance': 'PREESCOLAR', 'fecha_inicio': '2026-10-15', 'fecha_fin': '',
            'todo_el_dia': 'on', 'hora_inicio': '', 'hora_fin': '', 'lugar': 'Patio central', 'descripcion': '',
            'volver': f'{CALENDARIO}?mes=2026-09&nivel=PREESCOLAR',
        }
        datos.update(cambios)
        return {clave: valor for clave, valor in datos.items() if valor is not None}

    def test_el_administrador_registra_un_evento_y_vuelve_a_su_mes_con_el_mismo_nivel(self):
        dias_sin_clases, asistencias = DiaNoLectivo.objects.count(), AsistenciaGeneral.objects.count()
        respuesta = self.client.post(NUEVO, self.datos())
        self.assertRedirects(respuesta, f'{CALENDARIO}?mes=2026-10&nivel=PREESCOLAR', fetch_redirect_response=False)
        nuevo = EventoAgenda.objects.get()
        self.assertEqual((nuevo.alcance, nuevo.fecha_inicio, nuevo.fecha_fin), ('PREESCOLAR', date(2026, 10, 15), date(2026, 10, 15)))
        self.assertTrue(nuevo.todo_el_dia)
        self.assertEqual((nuevo.creado_por, nuevo.modificado_por), (self.admin, self.admin))
        # Es informativo: no crea días sin clases ni toca asistencias
        self.assertEqual(DiaNoLectivo.objects.count(), dias_sin_clases)
        self.assertEqual(AsistenciaGeneral.objects.count(), asistencias)

    def test_un_evento_de_todo_el_colegio_se_guarda_una_sola_vez(self):
        self.client.post(NUEVO, self.datos(alcance=COLEGIO, fecha_fin='2026-10-17'))
        self.assertEqual(list(EventoAgenda.objects.values_list('alcance', flat=True)), [COLEGIO])

    def test_con_horario_se_guardan_las_horas_y_con_todo_el_dia_no(self):
        self.client.post(NUEVO, self.datos(todo_el_dia=None, hora_inicio='10:00', hora_fin='12:00'))
        self.client.post(NUEVO, self.datos(titulo='Otro', hora_inicio='10:00', hora_fin='12:00'))
        con_horas, sin_horas = EventoAgenda.objects.order_by('pk')
        self.assertEqual((con_horas.todo_el_dia, con_horas.hora_inicio, con_horas.hora_fin), (False, time(10), time(12)))
        self.assertEqual((sin_horas.todo_el_dia, sin_horas.hora_inicio, sin_horas.hora_fin), (True, None, None))

    def test_validaciones_del_formulario(self):
        casos = {
            'fecha_fin': self.datos(fecha_fin='2026-10-14'),
            'hora_inicio': self.datos(todo_el_dia=None),
            'hora_fin': self.datos(todo_el_dia=None, hora_inicio='10:00', hora_fin='09:00'),
            'titulo': self.datos(titulo=''),
            'alcance': self.datos(alcance=''),
        }
        for campo, datos in casos.items():
            with self.subTest(campo):
                respuesta = self.client.post(NUEVO, datos)
                self.assertEqual(respuesta.status_code, 200)
                self.assertIn(campo, respuesta.context['form'].errors)
        self.assertIn('no puede ser anterior', str(self.client.post(NUEVO, casos['fecha_fin']).context['form'].errors))
        self.assertFalse(EventoAgenda.objects.exists())
        # De varios días con horario: la hora final puede ser menor (es de otro día)
        self.client.post(NUEVO, self.datos(fecha_fin='2026-10-16', todo_el_dia=None, hora_inicio='18:00', hora_fin='09:00'))
        self.assertEqual(EventoAgenda.objects.count(), 1)

    def test_al_tocar_un_dia_el_formulario_trae_esa_fecha(self):
        respuesta = self.client.get(NUEVO, {'fecha': '2026-10-21', 'volver': f'{CALENDARIO}?mes=2026-10'})
        form = respuesta.context['form']
        self.assertEqual((form['fecha_inicio'].value(), form['fecha_fin'].value()), ('2026-10-21', '2026-10-21'))
        self.assertTrue(form['todo_el_dia'].value())
        self.assertEqual(respuesta.context['volver'], f'{CALENDARIO}?mes=2026-10')

    def test_editar_un_evento(self):
        uno = evento('Junta', inicio=date(2026, 10, 12))
        respuesta = self.client.post(reverse('agenda:editar', args=[uno.pk]), self.datos(
            titulo='Junta de padres', alcance='SECUNDARIA', fecha_inicio='2026-11-03', volver=f'{CALENDARIO}?mes=2026-10'))
        self.assertRedirects(respuesta, f'{CALENDARIO}?mes=2026-11', fetch_redirect_response=False)
        uno.refresh_from_db()
        self.assertEqual((uno.titulo, uno.alcance, uno.fecha_inicio, uno.modificado_por), ('Junta de padres', 'SECUNDARIA', date(2026, 11, 3), self.admin))

    def test_eliminar_pide_confirmacion(self):
        uno = evento('Junta', inicio=date(2026, 10, 12))
        url = reverse('agenda:eliminar', args=[uno.pk])
        confirmacion = self.client.get(url, {'volver': f'{CALENDARIO}?mes=2026-10&nivel=PRIMARIA'})
        self.assertContains(confirmacion, '¿Eliminar «Junta»?')
        self.assertTrue(EventoAgenda.objects.filter(pk=uno.pk).exists())
        respuesta = self.client.post(url, {'volver': f'{CALENDARIO}?mes=2026-10&nivel=PRIMARIA'})
        self.assertRedirects(respuesta, f'{CALENDARIO}?mes=2026-10&nivel=PRIMARIA', fetch_redirect_response=False)
        self.assertFalse(EventoAgenda.objects.exists())

    def test_solo_se_vuelve_al_calendario(self):
        uno = evento('Junta', inicio=date(2026, 10, 12))
        for volver in ('https://otro.sitio/agenda/', '//otro.sitio/', '/alumnos/', f'{CALENDARIO}//otro.sitio'):
            with self.subTest(volver):
                respuesta = self.client.post(reverse('agenda:editar', args=[uno.pk]), self.datos(volver=volver))
                self.assertRedirects(respuesta, f'{CALENDARIO}?mes=2026-10', fetch_redirect_response=False)

    def test_el_calendario_del_administrador(self):
        for clave in ('PREESCOLAR', 'PRIMARIA', 'SECUNDARIA', 'PREPARATORIA', COLEGIO):
            evento(f'De {clave}', clave)
        respuesta = self.client.get(CALENDARIO, {'mes': '2026-10'})
        self.assertEqual(len(ids_del_mes(respuesta)), 5)
        self.assertTrue(respuesta.context['gestiona'])
        self.assertContains(respuesta, 'Nuevo evento')
        self.assertContains(respuesta, f'{NUEVO}?fecha=2026-10-14')                    # cada día abre el registro
        self.assertEqual([nombre for _, nombre, _, _ in respuesta.context['leyenda']],
                         ['Preescolar', 'Primaria', 'Secundaria', 'Bachillerato', 'Todos los niveles'])
        self.assertTrue(all('editar' in dato and 'eliminar' in dato for dato in respuesta.context['datos_eventos']))

    def test_navegar_entre_meses_conserva_el_nivel(self):
        respuesta = self.client.get(CALENDARIO, {'mes': '2026-12', 'nivel': 'PRIMARIA'})
        self.assertEqual(respuesta.context['primero'], date(2026, 12, 1))
        self.assertEqual(respuesta.context['anterior'], f'{CALENDARIO}?mes=2026-11&nivel=PRIMARIA')
        self.assertEqual(respuesta.context['siguiente'], f'{CALENDARIO}?mes=2027-01&nivel=PRIMARIA')
        self.assertContains(respuesta, 'Diciembre 2026')

    def test_el_filtro_por_nivel(self):
        primaria = evento('Primaria', 'PRIMARIA')
        general = evento('General', COLEGIO)
        evento('Secundaria', 'SECUNDARIA')
        self.assertCountEqual(ids_del_mes(self.client.get(CALENDARIO, {'mes': '2026-10', 'nivel': 'PRIMARIA'})), [primaria.pk, general.pk])
        self.assertEqual(ids_del_mes(self.client.get(CALENDARIO, {'mes': '2026-10', 'nivel': COLEGIO})), [general.pk])
        self.assertEqual(len(ids_del_mes(self.client.get(CALENDARIO, {'mes': '2026-10', 'nivel': 'NADA'}))), 3)
        vacio = self.client.get(CALENDARIO, {'mes': '2026-10', 'nivel': 'PREPARATORIA'})
        self.assertEqual(ids_del_mes(vacio), [general.pk])
        self.assertContains(self.client.get(CALENDARIO, {'mes': '2027-03'}), 'No hay eventos en marzo')

    def test_el_detalle_como_pagina(self):
        uno = evento('Junta', inicio=date(2026, 10, 12), horas=(time(17), time(18)), lugar='Aula 3.º A', descripcion='<b>Traer</b> libreta')
        respuesta = self.client.get(f'{CALENDARIO}?evento={uno.pk}')
        self.assertContains(respuesta, 'Lunes 12 de octubre de 2026')
        self.assertContains(respuesta, '17:00 a 18:00')
        self.assertContains(respuesta, 'Aula 3.º A')
        self.assertContains(respuesta, '&lt;b&gt;Traer&lt;/b&gt; libreta')
        self.assertContains(respuesta, reverse('agenda:editar', args=[uno.pk]))
        for invalido in ('abc', '999999', ''):
            self.assertEqual(self.client.get(CALENDARIO, {'evento': invalido}).status_code, 404)


# ---------------------------------------------------------------------------
# Quién ve qué
# ---------------------------------------------------------------------------
@PRUEBAS
class VisibilidadTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.eventos = {clave: evento(f'De {clave}', clave) for clave in ('PREESCOLAR', 'PRIMARIA', 'SECUNDARIA', 'PREPARATORIA', COLEGIO)}

    def ve(self, respuesta, *claves):
        self.assertEqual(respuesta.status_code, 200)
        self.assertCountEqual(ids_del_mes(respuesta), [self.eventos[clave].pk for clave in claves])

    def personal(self, nombre, **niveles):
        usuario = crear_usuario(nombre)
        PerfilUsuario.objects.filter(usuario=usuario).update(**niveles)
        self.client.force_login(usuario)
        return usuario

    def test_el_personal_ve_sus_niveles_y_los_de_todo_el_colegio(self):
        self.personal('recepcion', niveles_retiros=['PRIMARIA'])
        respuesta = self.client.get(CALENDARIO, {'mes': '2026-10'})
        self.ve(respuesta, 'PRIMARIA', COLEGIO)
        self.assertFalse(respuesta.context['gestiona'])
        self.assertNotContains(respuesta, 'Nuevo evento')
        self.assertNotContains(respuesta, NUEVO)
        self.assertEqual([clave for clave, _ in respuesta.context['opciones']], ['', 'PRIMARIA', COLEGIO])
        self.assertNotIn('editar', respuesta.context['datos_eventos'][0])
        # Pedir otro nivel en el filtro no amplía lo que ve
        self.ve(self.client.get(CALENDARIO, {'mes': '2026-10', 'nivel': 'PREESCOLAR'}), 'PRIMARIA', COLEGIO)

    def test_un_docente_ve_los_niveles_en_que_da_clases(self):
        docente = crear_usuario('marta')
        crear_profesor(niveles=['PREESCOLAR'], usuario=docente)
        self.client.force_login(docente)
        self.ve(self.client.get(CALENDARIO, {'mes': '2026-10'}), 'PREESCOLAR', COLEGIO)

    def test_con_varios_niveles_los_de_todo_el_colegio_se_ven_una_vez(self):
        self.personal('coordinacion', niveles_retiros=['PRIMARIA'], niveles_comunicados=['SECUNDARIA', 'PRIMARIA'])
        respuesta = self.client.get(CALENDARIO, {'mes': '2026-10'})
        self.ve(respuesta, 'PRIMARIA', 'SECUNDARIA', COLEGIO)
        self.assertEqual(len(ids_del_mes(respuesta)), len(set(ids_del_mes(respuesta))))
        self.assertEqual(sum(len(eventos) for _, eventos in respuesta.context['agenda']), 3)

    def test_sin_niveles_solo_los_de_todo_el_colegio(self):
        self.personal('sinniveles')
        respuesta = self.client.get(CALENDARIO, {'mes': '2026-10'})
        self.ve(respuesta, COLEGIO)
        self.assertTrue(respuesta.context['sin_niveles'])
        self.assertContains(respuesta, 'no tiene niveles educativos asignados')

    def test_el_servidor_niega_registrar_editar_y_eliminar_a_quien_no_es_administrador(self):
        self.personal('recepcion', niveles_retiros=['PRIMARIA'])
        visible = self.eventos['PRIMARIA']
        self.assertEqual(self.client.get(NUEVO).status_code, 403)
        self.assertEqual(self.client.post(NUEVO, {'titulo': 'X', 'alcance': COLEGIO, 'fecha_inicio': '2026-10-01', 'todo_el_dia': 'on'}).status_code, 403)
        self.assertEqual(self.client.get(reverse('agenda:editar', args=[visible.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse('agenda:editar', args=[visible.pk]), {'titulo': 'Cambio'}).status_code, 403)
        self.assertEqual(self.client.post(reverse('agenda:eliminar', args=[visible.pk])).status_code, 403)
        self.assertEqual(EventoAgenda.objects.count(), 5)
        visible.refresh_from_db()
        self.assertEqual(visible.titulo, 'De PRIMARIA')

    def test_el_detalle_de_un_evento_ajeno_no_existe_para_quien_no_lo_ve(self):
        self.personal('recepcion', niveles_retiros=['PRIMARIA'])
        self.assertEqual(self.client.get(f'{CALENDARIO}?evento={self.eventos["PREESCOLAR"].pk}').status_code, 404)
        respuesta = self.client.get(f'{CALENDARIO}?evento={self.eventos[COLEGIO].pk}')
        self.assertContains(respuesta, 'Todos los niveles')
        self.assertNotContains(respuesta, reverse('agenda:editar', args=[self.eventos[COLEGIO].pk]))

    def test_sin_sesion_se_pide_iniciar_sesion(self):
        self.client.logout()
        self.assertEqual(self.client.get(CALENDARIO).status_code, 302)
        self.assertEqual(self.client.get(NUEVO).status_code, 302)


@PRUEBAS
class PortalesTests(BaseTestCase):
    """Ana tiene a Lucía en primaria y a Zoe en secundaria; Rosa, a Leo en preescolar y un vínculo ya inactivo con
    Zoe; Iván está en preparatoria."""

    def setUp(self):
        super().setUp()
        self.client.logout()
        ciclo = ciclo_actual_de_prueba()
        grados = {nivel: crear_grado(nivel, 1) for nivel in ('PREESCOLAR', 'PRIMARIA', 'SECUNDARIA', 'PREPARATORIA')}
        self.lucia = crear_alumno(nombre='Lucía')
        self.zoe = crear_alumno(nombre='Zoe')
        self.leo = crear_alumno(nombre='Leo')
        self.ivan = crear_alumno(nombre='Iván')
        for alumno, nivel in ((self.lucia, 'PRIMARIA'), (self.zoe, 'SECUNDARIA'), (self.leo, 'PREESCOLAR'), (self.ivan, 'PREPARATORIA')):
            inscribir_antes(alumno, ciclo, grados[nivel])
        self.ana = crear_tutor(nombre='Ana', usuario='ana.campos')
        self.rosa = crear_tutor(nombre='Rosa', usuario='rosa.mora')
        vincular(self.ana, self.lucia)
        vincular(self.ana, self.zoe)
        vincular(self.rosa, self.leo)
        vincular(self.rosa, self.zoe, parentesco='TIA', activo=False)
        self.eventos = {clave: evento(f'De {clave}', clave) for clave in ('PREESCOLAR', 'PRIMARIA', 'SECUNDARIA', 'PREPARATORIA', COLEGIO)}

    def ve(self, respuesta, *claves):
        self.assertEqual(respuesta.status_code, 200)
        self.assertCountEqual(ids_del_mes(respuesta), [self.eventos[clave].pk for clave in claves])

    def test_un_tutor_ve_los_niveles_de_sus_hijos_y_los_de_todo_el_colegio(self):
        entrar_al_portal(self.client, portales.TUTOR, self.ana)
        respuesta = self.client.get(reverse('portal_tutores:agenda:calendario'), {'mes': '2026-10'})
        self.ve(respuesta, 'PRIMARIA', 'SECUNDARIA', COLEGIO)
        self.assertEqual([clave for clave, _ in respuesta.context['opciones']], ['', 'PRIMARIA', 'SECUNDARIA', COLEGIO])
        self.assertFalse(respuesta.context['gestiona'])
        self.assertNotContains(respuesta, 'Nuevo evento')
        self.assertEqual(respuesta.context['base'], 'portales/base.html')
        self.ve(self.client.get(reverse('portal_tutores:agenda:calendario'), {'mes': '2026-10', 'nivel': 'SECUNDARIA'}), 'SECUNDARIA', COLEGIO)

    def test_un_vinculo_inactivo_no_cuenta(self):
        entrar_al_portal(self.client, portales.TUTOR, self.rosa)
        self.ve(self.client.get(reverse('portal_tutores:agenda:calendario'), {'mes': '2026-10'}), 'PREESCOLAR', COLEGIO)

    def test_el_detalle_en_el_portal(self):
        entrar_al_portal(self.client, portales.TUTOR, self.ana)
        visible = self.client.get(f"{reverse('portal_tutores:agenda:calendario')}?evento={self.eventos['PRIMARIA'].pk}")
        self.assertContains(visible, 'De PRIMARIA')
        self.assertNotContains(visible, reverse('agenda:editar', args=[self.eventos['PRIMARIA'].pk]))
        self.assertEqual(self.client.get(f"{reverse('portal_tutores:agenda:calendario')}?evento={self.eventos['PREESCOLAR'].pk}").status_code, 404)

    def test_un_estudiante_ve_su_nivel_y_los_de_todo_el_colegio(self):
        entrar_al_portal(self.client, portales.ESTUDIANTE, self.ivan)
        self.ve(self.client.get(reverse('portal_estudiantes:agenda:calendario'), {'mes': '2026-10'}), 'PREPARATORIA', COLEGIO)
        self.assertEqual(self.client.get(f"{reverse('portal_estudiantes:agenda:calendario')}?evento={self.eventos['PRIMARIA'].pk}").status_code, 404)

    def test_el_portal_no_da_acceso_a_registrar(self):
        entrar_al_portal(self.client, portales.TUTOR, self.ana)
        self.assertEqual(self.client.get(NUEVO).status_code, 302)                        # el sistema pide su propia sesión
        self.assertEqual(EventoAgenda.objects.count(), 5)

    def test_sin_sesion_del_portal_se_pide_entrar(self):
        self.assertEqual(self.client.get(reverse('portal_tutores:agenda:calendario')).status_code, 302)

    def test_la_vista_de_alcance(self):
        self.assertEqual(alcance.de_tutor(self.ana).niveles, frozenset({'PRIMARIA', 'SECUNDARIA'}))
        self.assertEqual(alcance.de_estudiante(self.leo).niveles, frozenset({'PREESCOLAR'}))
        self.assertTrue(alcance.de_usuario(self.admin).gestiona)
