"""Cálculo de la calificación de un estudiante en un periodo (sin base de datos: recibe números y devuelve números).

Reproduce las fórmulas de la hoja «General» del formato GeneralSecundaria.xlsx, generalizadas a los rubros y
porcentajes de cada materia:

- Rubro de captura directa (conducta):      aportación = REDONDEAR(calificación × %, 2)               (F16)
- Promedio de procedimientos:               promedio   = REDONDEAR(SUMA / CUENTA, 2)                   (G16)
                                            aportación = REDONDEAR(promedio × %, 2)                    (H16)
- Promedio de exámenes:                     aportación = REDONDEAR((SUMA / CUENTA) × %, 2)             (N16)
  (el formato no redondea el promedio de exámenes antes de ponderarlo; aquí tampoco. Se muestra redondeado.)
- Base = suma de las aportaciones. Si falta cualquiera, no hay calificación final (O16 queda vacía).
- Final = base − TRUNCAR(faltas / 2) + (1 si hay punto de academia), con tope de 10 (O16). Sin límite inferior.

Las faltas por bloque, los puntos que se descuentan, el valor del punto de academia y los límites son opciones de
cada materia (`Reglas`); los valores por omisión son los del formato. Una celda vacía no cuenta en el promedio; un
cero sí. «Redondear» es como ROUND de Excel: la mitad se redondea hacia arriba (todas las cantidades son positivas).

Caso de referencia (pedido del 2026-10-14): conducta 9, procedimientos 8 y 10, exámenes 7 y 9, tres faltas y punto de
academia: 1.80 + 4.50 + 2.40 − 1 + 1 = 8.70.
"""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

DIRECTA, PROCEDIMIENTOS, EXAMENES = 'DIRECTA', 'PROCEDIMIENTOS', 'EXAMENES'
CENTESIMOS = Decimal('0.01')
CIEN = Decimal('100')


def redondear(valor):
    """ROUND(valor, 2) de Excel."""
    return valor.quantize(CENTESIMOS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class RubroDeCalculo:
    clave: str            # con qué se identifica (el id del rubro)
    nombre: str
    porcentaje: Decimal   # 20 para 20 %
    tipo: str             # DIRECTA, PROCEDIMIENTOS o EXAMENES


@dataclass(frozen=True)
class Reglas:
    penalizar_faltas: bool = True
    faltas_por_bloque: int = 2
    puntos_por_bloque: Decimal = Decimal('1')
    punto_academia: bool = True
    valor_punto_academia: Decimal = Decimal('1')
    limite_maximo: Decimal = Decimal('10')
    limite_minimo: Decimal = None   # None: sin límite inferior (como el formato)


@dataclass
class ResultadoDeRubro:
    valor: Decimal = None        # la calificación directa o el promedio (2 decimales); None si no tiene captura
    aportacion: Decimal = None   # lo que aporta a la calificación final
    capturas: int = 0            # cuántas calificaciones lo forman


@dataclass
class Resultado:
    rubros: dict = field(default_factory=dict)   # clave -> ResultadoDeRubro
    base: Decimal = None                          # suma de aportaciones (None si falta algún rubro)
    faltas: int = 0                               # las que se consideraron
    descuento: Decimal = Decimal('0')
    bonificacion: Decimal = Decimal('0')
    final: Decimal = None                         # None: sin calificación final (falta algún rubro)
    pendientes: int = 0                           # actividades vigentes sin calificar
    tope: str = ''                                # 'maximo' o 'minimo' si se aplicó un límite

    @property
    def sin_capturas(self):
        return not any(r.capturas for r in self.rubros.values())

    @property
    def completo(self):
        return self.final is not None

    @property
    def provisional(self):
        """Hay calificación final, pero todavía con actividades por calificar."""
        return self.completo and self.pendientes > 0


def resultado_de_rubro(rubro, captura):
    """`captura`: para un rubro directo, la calificación (o None); para uno de promedio, la lista de calificaciones."""
    porcentaje = rubro.porcentaje / CIEN
    if rubro.tipo == DIRECTA:
        if captura is None:
            return ResultadoDeRubro()
        return ResultadoDeRubro(valor=captura, aportacion=redondear(captura * porcentaje), capturas=1)
    calificaciones = [c for c in (captura or []) if c is not None]
    if not calificaciones:
        return ResultadoDeRubro()
    exacto = sum(calificaciones, Decimal('0')) / len(calificaciones)
    if rubro.tipo == PROCEDIMIENTOS:
        promedio = redondear(exacto)
        return ResultadoDeRubro(valor=promedio, aportacion=redondear(promedio * porcentaje), capturas=len(calificaciones))
    return ResultadoDeRubro(valor=redondear(exacto), aportacion=redondear(exacto * porcentaje), capturas=len(calificaciones))


def descuento_por_faltas(faltas, reglas):
    """Puntos que se restan: por cada bloque completo de faltas (con 2 por bloque: 0-1 → 0, 2-3 → 1, 4-5 → 2…)."""
    if not reglas.penalizar_faltas or not faltas or reglas.faltas_por_bloque < 1:
        return Decimal('0')
    return (faltas // reglas.faltas_por_bloque) * reglas.puntos_por_bloque


def calcular(rubros, reglas, capturas, faltas=0, academia=False, pendientes=0):
    """La calificación de un estudiante. `rubros`: los activos de la configuración (RubroDeCalculo); `capturas`:
    {clave del rubro: calificación o lista de calificaciones}; `academia`: si tiene otorgado el punto de academia;
    `pendientes`: actividades vigentes que le faltan por calificar (solo se informa)."""
    resultado = Resultado(faltas=faltas or 0, pendientes=pendientes)
    for rubro in rubros:
        resultado.rubros[rubro.clave] = resultado_de_rubro(rubro, capturas.get(rubro.clave))
    aportaciones = [r.aportacion for r in resultado.rubros.values()]
    if not rubros or any(a is None for a in aportaciones):
        return resultado
    resultado.base = sum(aportaciones, Decimal('0'))
    resultado.descuento = descuento_por_faltas(resultado.faltas, reglas)
    resultado.bonificacion = reglas.valor_punto_academia if (reglas.punto_academia and academia) else Decimal('0')
    final = resultado.base - resultado.descuento + resultado.bonificacion
    if final > reglas.limite_maximo:
        final, resultado.tope = reglas.limite_maximo, 'maximo'
    elif reglas.limite_minimo is not None and final < reglas.limite_minimo:
        final, resultado.tope = reglas.limite_minimo, 'minimo'
    resultado.final = redondear(final)
    return resultado
