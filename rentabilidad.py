"""
Motor de rentabilidad para compra en subasta.

Una calculadora que enseñe «precio, hipoteca y alquiler» da un número bonito y
equivocado. Un inversor decide con otras cifras, y son las que hay aquí:

  - **Gastos de compra**: entre un 10% y un 13% del precio (ITP, notaría,
    registro, gestoría, tasación) que NADIE financia y que salen del bolsillo.
    Omitirlos infla la rentabilidad en torno a un 20%.
  - **Rentabilidad neta**, descontando IBI, comunidad, seguro, mantenimiento y
    sobre todo vacancia — los meses que el piso está vacío entre inquilinos.
  - **Cash-flow mensual**: si el piso da o quita dinero cada mes.
  - **Retorno sobre el capital aportado**, no sobre el precio total: con
    hipoteca, lo que se pone es la entrada más los gastos.

Los porcentajes de ITP son los tipos generales vigentes por comunidad; hay
tipos reducidos (menores de 32 años, familia numerosa, VPO) que no se aplican
automáticamente porque dependen del comprador, no del inmueble.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field

# ITP de transmisiones patrimoniales onerosas, tipo general por comunidad (2026).
# En subasta judicial se tributa por ITP igual que en una compraventa entre
# particulares: es el impuesto que más pesa y varía mucho según dónde compres.
ITP_POR_COMUNIDAD = {
    "madrid": 0.06, "pais vasco": 0.04, "navarra": 0.06, "canarias": 0.065,
    "murcia": 0.08, "la rioja": 0.07, "aragon": 0.08, "asturias": 0.08,
    "baleares": 0.08, "andalucia": 0.07, "castilla y leon": 0.08,
    "castilla-la mancha": 0.09, "cataluna": 0.10, "extremadura": 0.08,
    "galicia": 0.09, "cantabria": 0.09, "comunidad valenciana": 0.10,
}
ITP_POR_DEFECTO = 0.08

PROVINCIA_A_COMUNIDAD = {
    "madrid": "madrid", "barcelona": "cataluna", "girona": "cataluna",
    "lleida": "cataluna", "tarragona": "cataluna", "valencia": "comunidad valenciana",
    "alicante": "comunidad valenciana", "castellon": "comunidad valenciana",
    "sevilla": "andalucia", "malaga": "andalucia", "cadiz": "andalucia",
    "granada": "andalucia", "cordoba": "andalucia", "almeria": "andalucia",
    "huelva": "andalucia", "jaen": "andalucia", "vizcaya": "pais vasco",
    "bizkaia": "pais vasco", "guipuzcoa": "pais vasco", "alava": "pais vasco",
    "zaragoza": "aragon", "huesca": "aragon", "teruel": "aragon",
    "murcia": "murcia", "asturias": "asturias", "cantabria": "cantabria",
    "navarra": "navarra", "la rioja": "la rioja",
}


@dataclass
class Supuestos:
    """Todo lo que el usuario puede ajustar. Los valores por defecto son
    conservadores a propósito: más vale que la realidad sorprenda a favor."""
    entrada_pct: float = 0.30          # en subasta la financiación es más difícil que en compra normal
    interes_anual: float = 0.032       # Euríbor + diferencial típico
    anios_hipoteca: int = 25
    itp_pct: float | None = None       # si es None se deduce de la provincia
    notaria_registro_gestoria: float = 2500.0
    reforma: float = 0.0
    ibi_anual: float = 400.0
    comunidad_mensual: float = 60.0
    seguro_anual: float = 250.0
    mantenimiento_pct_alquiler: float = 0.05
    vacancia_pct: float = 0.06         # ~3 semanas al año vacío
    gestion_pct_alquiler: float = 0.0  # si se delega en una agencia, 5-10%
    irpf_marginal: float = 0.30
    reduccion_alquiler_habitual: float = 0.50   # reducción del rendimiento neto en vivienda habitual


def itp_de_provincia(provincia: str | None) -> float:
    if not provincia:
        return ITP_POR_DEFECTO
    clave = provincia.strip().lower()
    comunidad = PROVINCIA_A_COMUNIDAD.get(clave, clave)
    return ITP_POR_COMUNIDAD.get(comunidad, ITP_POR_DEFECTO)


def cuota_hipoteca(principal: float, interes_anual: float, anios: int) -> float:
    """Cuota mensual por el sistema francés, que es el de casi toda hipoteca
    española: cuota constante, con más intereses al principio."""
    if principal <= 0:
        return 0.0
    n = anios * 12
    i = interes_anual / 12
    if i == 0:
        return principal / n
    return principal * (i * (1 + i) ** n) / ((1 + i) ** n - 1)


@dataclass
class Analisis:
    precio_compra: float
    itp_pct: float
    itp: float
    otros_gastos_compra: float
    reforma: float
    inversion_total: float
    capital_aportado: float
    hipoteca: float
    cuota_mensual: float
    alquiler_mensual: float
    ingresos_anuales_brutos: float
    ingresos_anuales_efectivos: float
    gastos_anuales: float
    beneficio_neto_anual_antes_impuestos: float
    irpf_estimado: float
    beneficio_neto_anual: float
    cash_flow_mensual: float
    rentabilidad_bruta: float
    rentabilidad_neta: float
    retorno_capital_aportado: float
    anios_recuperar_capital: float | None
    detalle: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def analizar(precio_compra: float, alquiler_mensual: float, provincia: str | None = None,
             s: Supuestos | None = None) -> Analisis:
    """Análisis completo de una operación de compra para alquilar."""
    s = s or Supuestos()
    if precio_compra <= 0:
        raise ValueError("El precio de compra debe ser mayor que cero")

    itp_pct = s.itp_pct if s.itp_pct is not None else itp_de_provincia(provincia)
    itp = precio_compra * itp_pct
    gastos_compra = itp + s.notaria_registro_gestoria
    inversion_total = precio_compra + gastos_compra + s.reforma

    hipoteca = precio_compra * (1 - s.entrada_pct)
    # Los gastos e impuestos no se financian: salen íntegros del bolsillo.
    capital_aportado = precio_compra * s.entrada_pct + gastos_compra + s.reforma
    cuota = cuota_hipoteca(hipoteca, s.interes_anual, s.anios_hipoteca)

    ingresos_brutos = alquiler_mensual * 12
    # La vacancia es el gasto que más se olvida y el que más duele.
    ingresos_efectivos = ingresos_brutos * (1 - s.vacancia_pct)

    gastos = (
        s.ibi_anual
        + s.comunidad_mensual * 12
        + s.seguro_anual
        + ingresos_efectivos * s.mantenimiento_pct_alquiler
        + ingresos_efectivos * s.gestion_pct_alquiler
    )

    # Hacienda permite deducir los intereses, no la amortización del principal.
    intereses_primer_anio = hipoteca * s.interes_anual
    base_irpf = max(0.0, ingresos_efectivos - gastos - intereses_primer_anio)
    irpf = base_irpf * (1 - s.reduccion_alquiler_habitual) * s.irpf_marginal

    neto_antes_impuestos = ingresos_efectivos - gastos
    neto = neto_antes_impuestos - irpf
    cash_flow_mensual = (ingresos_efectivos - gastos - irpf) / 12 - cuota

    rent_bruta = ingresos_brutos / inversion_total
    rent_neta = neto / inversion_total
    retorno_capital = neto / capital_aportado if capital_aportado > 0 else 0.0
    anios_recuperar = capital_aportado / neto if neto > 0 else None

    return Analisis(
        precio_compra=round(precio_compra, 2),
        itp_pct=itp_pct,
        itp=round(itp, 2),
        otros_gastos_compra=round(s.notaria_registro_gestoria, 2),
        reforma=round(s.reforma, 2),
        inversion_total=round(inversion_total, 2),
        capital_aportado=round(capital_aportado, 2),
        hipoteca=round(hipoteca, 2),
        cuota_mensual=round(cuota, 2),
        alquiler_mensual=round(alquiler_mensual, 2),
        ingresos_anuales_brutos=round(ingresos_brutos, 2),
        ingresos_anuales_efectivos=round(ingresos_efectivos, 2),
        gastos_anuales=round(gastos, 2),
        beneficio_neto_anual_antes_impuestos=round(neto_antes_impuestos, 2),
        irpf_estimado=round(irpf, 2),
        beneficio_neto_anual=round(neto, 2),
        cash_flow_mensual=round(cash_flow_mensual, 2),
        rentabilidad_bruta=round(rent_bruta, 4),
        rentabilidad_neta=round(rent_neta, 4),
        retorno_capital_aportado=round(retorno_capital, 4),
        anios_recuperar_capital=round(anios_recuperar, 1) if anios_recuperar else None,
        detalle={
            "vacancia_aplicada_pct": s.vacancia_pct,
            "meses_vacio_equivalente": round(s.vacancia_pct * 12, 1),
            "intereses_primer_anio": round(intereses_primer_anio, 2),
            "nota_itp": "Tipo general de la comunidad; no se aplican reducciones "
                        "por edad, familia numerosa o VPO porque dependen del comprador.",
        },
    )


def precio_maximo_para_cash_flow(alquiler_mensual: float, objetivo_mensual: float = 0.0,
                                 provincia: str | None = None,
                                 s: Supuestos | None = None) -> float:
    """Cuánto se puede pagar como máximo para que el cash-flow no baje del
    objetivo. Es la cifra que de verdad sirve al pujar: el techo por encima del
    cual la operación deja de tener sentido."""
    s = s or Supuestos()
    bajo, alto = 1000.0, alquiler_mensual * 12 * 60  # horquilla amplia
    for _ in range(60):                              # bisección: converge de sobra
        medio = (bajo + alto) / 2
        cf = analizar(medio, alquiler_mensual, provincia, s).cash_flow_mensual
        if cf > objetivo_mensual:
            bajo = medio
        else:
            alto = medio
    return round(bajo, 2)
