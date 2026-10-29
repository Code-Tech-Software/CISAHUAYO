"""Cálculo semestral de bachillerato (pedido del 2026-10-28), sin base de datos: recibe números y devuelve números.

Parte de las calificaciones finales de los periodos del semestre, tal como las calcula Calificaciones/calculo.py (no se
cambia nada de ese cálculo), y de los exámenes capturados:

- Promedio de periodos = suma / número de periodos del semestre. Todos pesan igual y no se fija en tres: son los que
  tenga el semestre. Si falta la calificación de algún periodo no hay promedio (nunca se toma como cero).
- Promedio ≥ 9.5: exento. El examen final toma el valor del promedio («asignado por exención») y la final ordinaria es
  el mismo promedio.
- 6.0 ≤ promedio < 9.5: presenta examen final. Final ordinaria = (promedio + examen final) / 2: el promedio vale 50 % y
  el examen 50 %. Sin examen capturado, el resultado queda pendiente.
- Promedio < 6.0: sin derecho a examen final (política confirmada el 2026-10-28): la final ordinaria es el promedio y
  pasa a extraordinario.
- Final ordinaria < 6.0: extraordinario. Con 6.0 o más lo aprueba y la definitiva es la calificación que obtuvo (sin
  tope, confirmado el 2026-10-28).
- Extraordinario < 6.0: regularización. Con 6.0 o más la aprueba (definitiva: la que obtuvo); con menos, la materia
  queda reprobada en definitiva y no se habilitan más exámenes (confirmado el 2026-10-28).

Precisión (confirmada el 2026-10-28): todo se calcula con el valor exacto (fracciones, sin redondear en ningún paso) y
con él se decide la exención y la aprobación; lo que se muestra y se registra se trunca a dos decimales. Así nunca
aparece un 9.50 o un 6.00 que no se alcanzó: periodos 9.50, 9.50 y 9.49 dan 9.4966…, se muestra 9.49 y no exenta.

Caso de referencia del pedido: periodos 8.0, 7.0 y 9.0 → promedio 8.0; examen final 7.0 → final ordinaria 7.5.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
from math import floor

EXENCION = Fraction(19, 2)   # 9.5
APROBATORIA = Fraction(6)

FINAL, EXTRAORDINARIO, REGULARIZACION = 'FINAL', 'EXTRAORDINARIO', 'REGULARIZACION'

# Ante el examen final
SIN_PROMEDIO, EXENTO, CON_DERECHO, SIN_DERECHO = 'SIN_PROMEDIO', 'EXENTO', 'CON_DERECHO', 'SIN_DERECHO'
SITUACIONES = {
    SIN_PROMEDIO: 'Faltan periodos', EXENTO: 'Exento', CON_DERECHO: 'Con derecho a examen final', SIN_DERECHO: 'Sin derecho a examen final',
}

# Estado académico de la materia en el semestre
PENDIENTE_PERIODOS = 'PENDIENTE_PERIODOS'
PENDIENTE_FINAL = 'PENDIENTE_FINAL'
APROBADA_EXENTO = 'APROBADA_EXENTO'
APROBADA_ORDINARIO = 'APROBADA_ORDINARIO'
PENDIENTE_EXTRAORDINARIO = 'PENDIENTE_EXTRAORDINARIO'
APROBADA_EXTRAORDINARIO = 'APROBADA_EXTRAORDINARIO'
PENDIENTE_REGULARIZACION = 'PENDIENTE_REGULARIZACION'
APROBADA_REGULARIZACION = 'APROBADA_REGULARIZACION'
REPROBADA = 'REPROBADA'
ESTADOS = {
    PENDIENTE_PERIODOS: 'Pendiente: calificaciones de periodo',
    PENDIENTE_FINAL: 'Pendiente: examen final',
    APROBADA_EXENTO: 'Aprobada (exento)',
    APROBADA_ORDINARIO: 'Aprobada en ordinario',
    PENDIENTE_EXTRAORDINARIO: 'Pendiente: extraordinario',
    APROBADA_EXTRAORDINARIO: 'Aprobada en extraordinario',
    PENDIENTE_REGULARIZACION: 'Pendiente: regularización',
    APROBADA_REGULARIZACION: 'Aprobada en regularización',
    REPROBADA: 'Reprobada',
}
# La evaluación ordinaria todavía no tiene resultado (no se puede cerrar el semestre así)
PENDIENTES_ORDINARIOS = (PENDIENTE_PERIODOS, PENDIENTE_FINAL)
# Procesos que siguen abiertos después de la evaluación ordinaria
PROCESOS_ABIERTOS = (PENDIENTE_EXTRAORDINARIO, PENDIENTE_REGULARIZACION)
APROBADAS = (APROBADA_EXENTO, APROBADA_ORDINARIO, APROBADA_EXTRAORDINARIO, APROBADA_REGULARIZACION)


def exacto(valor):
    """Un Decimal (o None) como fracción exacta."""
    return None if valor is None else Fraction(valor)


def truncar(valor):
    """El valor exacto truncado a dos decimales, como Decimal (9.4966… → 9.49); None si es None."""
    if valor is None:
        return None
    return Decimal(floor(Fraction(valor) * 100)) / 100


def texto(valor):
    """Truncado a dos decimales, como texto ('9.49'); '' si es None."""
    return '' if valor is None else f'{truncar(valor):.2f}'


@dataclass
class ResultadoSemestral:
    periodos: list                         # la calificación final de cada periodo (Decimal) o None si falta
    promedio: Fraction = None              # exacto; None si falta algún periodo
    situacion: str = SIN_PROMEDIO
    examen_final: Fraction = None          # el que cuenta: el capturado o, si es exento, el promedio
    final_por_exencion: bool = False
    ordinaria: Fraction = None
    extraordinario: Fraction = None
    regularizacion: Fraction = None
    definitiva: Fraction = None
    estado: str = PENDIENTE_PERIODOS
    capturable: set = field(default_factory=set)   # exámenes que corresponde capturar o corregir ahora
    no_cuentan: set = field(default_factory=set)   # exámenes capturados que, con los periodos de hoy, no aplican

    @property
    def estado_texto(self):
        return ESTADOS[self.estado]

    @property
    def situacion_texto(self):
        return SITUACIONES[self.situacion]

    @property
    def aprobada(self):
        return self.estado in APROBADAS

    @property
    def reprobada(self):
        return self.estado == REPROBADA

    @property
    def pendiente_ordinario(self):
        return self.estado in PENDIENTES_ORDINARIOS

    @property
    def proceso_abierto(self):
        return self.estado in PROCESOS_ABIERTOS

    @property
    def concluida(self):
        """La materia ya tiene calificación definitiva (aprobada o reprobada)."""
        return self.definitiva is not None


def calcular(periodos, final=None, extraordinario=None, regularizacion=None):
    """El resultado semestral de un estudiante en una materia. `periodos`: la calificación final (Decimal) de cada
    periodo del semestre, None si está pendiente; los exámenes, el valor capturado (Decimal) o None."""
    resultado = ResultadoSemestral(periodos=list(periodos))
    capturados = {FINAL: exacto(final), EXTRAORDINARIO: exacto(extraordinario), REGULARIZACION: exacto(regularizacion)}
    usados = set()
    if not periodos or any(p is None for p in periodos):
        return resultado   # sin promedio no se decide nada (los exámenes capturados esperan)

    promedio = sum((Fraction(p) for p in periodos), Fraction(0)) / len(periodos)
    resultado.promedio = promedio
    if promedio >= EXENCION:
        resultado.situacion = EXENTO
        resultado.examen_final, resultado.final_por_exencion = promedio, True
        resultado.ordinaria = promedio
    elif promedio >= APROBATORIA:
        resultado.situacion = CON_DERECHO
        if capturados[FINAL] is None:
            resultado.estado = PENDIENTE_FINAL
            resultado.capturable.add(FINAL)
            resultado.no_cuentan = {t for t in (EXTRAORDINARIO, REGULARIZACION) if capturados[t] is not None}
            return resultado
        resultado.examen_final = capturados[FINAL]
        usados.add(FINAL)
        resultado.ordinaria = (promedio + capturados[FINAL]) / 2
    else:
        resultado.situacion = SIN_DERECHO
        resultado.ordinaria = promedio

    if resultado.ordinaria >= APROBATORIA:
        resultado.estado = APROBADA_EXENTO if resultado.situacion == EXENTO else APROBADA_ORDINARIO
        resultado.definitiva = resultado.ordinaria
        if FINAL in usados:
            resultado.capturable.add(FINAL)   # se puede corregir mientras no haya un examen posterior
    else:
        extra = capturados[EXTRAORDINARIO]
        if extra is None:
            resultado.estado = PENDIENTE_EXTRAORDINARIO
            resultado.capturable.add(EXTRAORDINARIO)
            if FINAL in usados:
                resultado.capturable.add(FINAL)
        else:
            resultado.extraordinario = extra
            usados.add(EXTRAORDINARIO)
            if extra >= APROBATORIA:
                resultado.estado, resultado.definitiva = APROBADA_EXTRAORDINARIO, extra
                resultado.capturable.add(EXTRAORDINARIO)
            else:
                regu = capturados[REGULARIZACION]
                if regu is None:
                    resultado.estado = PENDIENTE_REGULARIZACION
                    resultado.capturable.update({EXTRAORDINARIO, REGULARIZACION})
                else:
                    resultado.regularizacion = regu
                    usados.add(REGULARIZACION)
                    resultado.estado = APROBADA_REGULARIZACION if regu >= APROBATORIA else REPROBADA
                    resultado.definitiva = regu
                    resultado.capturable.add(REGULARIZACION)
    resultado.no_cuentan = {tipo for tipo, valor in capturados.items() if valor is not None and tipo not in usados}
    return resultado
