"""
Análisis de zonas de inversión: barrio a barrio, qué cuesta y qué renta.

Responde a la pregunta con la que empieza cualquier inversor, antes incluso de
mirar un inmueble concreto: **¿en qué barrio me conviene comprar?**

Para cada barrio calcula, sobre una vivienda tipo:

  - el **precio** que costaría comprarla,
  - la **cuota de hipoteca** que pagaría,
  - el **alquiler** que podría cobrar,
  - y lo que queda al mes después de todo.

La gracia está en la comparación: un barrio caro con alquileres altos puede
rentar menos que uno barato, y eso no se ve mirando el precio del metro. Aquí
salen ordenados por lo que de verdad importa, la rentabilidad neta.

Los precios por metro cuadrado vienen del proyecto `deteccion-zonas-revalorizacion`
del portfolio, que ya los tenía por barrio. El alquiler se estima con la
rentabilidad bruta típica de la provincia y **se declara como estimación**:
mientras SERPAVI siga tras un reCAPTCHA no hay alquileres reales por barrio.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, asdict, field

import httpx

from rentabilidad import Supuestos, analizar
from valoracion import YIELD_BRUTO, YIELD_POR_DEFECTO

REVALORIZACION_URL = os.getenv("REVALORIZACION_API_URL", "http://127.0.0.1:8090")
TIMEOUT = 20.0

# Vivienda tipo sobre la que se compara. Se puede cambiar por parámetro, pero
# comparar barrios exige que TODOS usen la misma, o no se comparan precios sino
# tamaños distintos.
SUPERFICIE_TIPO = 80

CIUDAD_A_PROVINCIA = {
    "madrid": "madrid", "barcelona": "barcelona", "valencia": "valencia",
    "sevilla": "sevilla", "malaga": "malaga", "bilbao": "vizcaya",
    "zaragoza": "zaragoza", "alicante": "alicante",
}


@dataclass
class Barrio:
    nombre: str
    precio_m2: float
    precio_vivienda: float
    cuota_hipoteca_mensual: float
    alquiler_estimado_mensual: float
    rentabilidad_bruta: float
    rentabilidad_neta: float
    cash_flow_mensual: float
    capital_necesario: float
    anios_recuperar: float | None
    tendencia_anual: float | None = None
    score_revalorizacion: float | None = None
    lat: float | None = None
    lng: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AnalisisZonas:
    ciudad: str
    superficie_tipo: int
    total_barrios: int
    barrios: list[dict] = field(default_factory=list)
    criterio_orden: str = ""
    mejor_rentabilidad: str | None = None
    mejor_cash_flow: str | None = None
    mas_barato: str | None = None
    supuestos: dict = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)
    fuentes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _barrios_de(ciudad: str) -> list[dict]:
    r = httpx.get(f"{REVALORIZACION_URL}/ml/revalorizacion/mapa",
                  params={"ciudad": ciudad}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json().get("barrios", [])


def ciudades_disponibles() -> list[dict]:
    try:
        r = httpx.get(f"{REVALORIZACION_URL}/ml/revalorizacion/ciudades", timeout=TIMEOUT)
        r.raise_for_status()
        return r.json().get("ciudades", [])
    except Exception:
        return [{"id": c, "nombre": c.title()} for c in CIUDAD_A_PROVINCIA]


def analizar_zonas(ciudad: str = "madrid", superficie: int = SUPERFICIE_TIPO,
                   s: Supuestos | None = None,
                   alquiler_m2: float | None = None) -> AnalisisZonas:
    """Compara todos los barrios de una ciudad como inversión de alquiler."""
    s = s or Supuestos()
    provincia = CIUDAD_A_PROVINCIA.get(ciudad.lower(), ciudad.lower())
    avisos: list[str] = []

    try:
        crudos = _barrios_de(ciudad)
    except Exception as e:
        return AnalisisZonas(
            ciudad=ciudad, superficie_tipo=superficie, total_barrios=0,
            avisos=[f"No se pudieron obtener los barrios de {ciudad}: {type(e).__name__}. "
                    "El servicio de zonas arranca bajo demanda; reinténtalo en unos segundos."],
        )

    if not crudos:
        return AnalisisZonas(ciudad=ciudad, superficie_tipo=superficie, total_barrios=0,
                             avisos=[f"No hay datos de barrios para «{ciudad}»."])

    yield_bruto = YIELD_BRUTO.get(provincia, YIELD_POR_DEFECTO)
    if alquiler_m2:
        avisos.append(f"Alquiler calculado con los {alquiler_m2} €/m² al mes que has indicado.")
    else:
        avisos.append(
            f"El alquiler es una ESTIMACIÓN: se deriva de la rentabilidad bruta típica de "
            f"{provincia} ({yield_bruto*100:.1f}%). No hay alquileres reales por barrio "
            "mientras SERPAVI —los declarados a Hacienda— siga sin poder consultarse."
        )
        avisos.append(
            "IMPORTANTE: al derivar el alquiler del precio con un porcentaje fijo, la "
            "rentabilidad sale casi idéntica en todos los barrios. Eso no significa que "
            "lo sea: significa que esta comparación NO puede distinguir barrios por "
            "rentabilidad. Lo que sí compara de verdad es el precio de entrada, el "
            "capital necesario y la tendencia. Para comparar rentabilidad de verdad, "
            "introduce el alquiler real en €/m² de cada zona."
        )

    barrios: list[Barrio] = []
    for b in crudos:
        precio_m2 = b.get("precio_m2")
        if not precio_m2:
            continue
        precio = precio_m2 * superficie
        alquiler = (alquiler_m2 * superficie) if alquiler_m2 else (precio * yield_bruto / 12)

        a = analizar(precio, alquiler, provincia, s)
        barrios.append(Barrio(
            nombre=b.get("nombre", "?"),
            precio_m2=round(precio_m2, 2),
            precio_vivienda=round(precio, 2),
            cuota_hipoteca_mensual=a.cuota_mensual,
            alquiler_estimado_mensual=round(alquiler, 2),
            rentabilidad_bruta=a.rentabilidad_bruta,
            rentabilidad_neta=a.rentabilidad_neta,
            cash_flow_mensual=a.cash_flow_mensual,
            capital_necesario=a.capital_aportado,
            anios_recuperar=a.anios_recuperar_capital,
            tendencia_anual=b.get("tend_1a"),
            score_revalorizacion=b.get("score"),
            lat=b.get("lat"), lng=b.get("lng"),
        ))

    # Si el alquiler es derivado del precio, ordenar por rentabilidad es
    # engañoso: sale casi plana. Se ordena por tendencia de revalorización, que
    # es un dato real e independiente del precio.
    if alquiler_m2:
        barrios.sort(key=lambda x: -x.rentabilidad_neta)
        criterio = "mayor rentabilidad neta (con el alquiler real que has indicado)"
    else:
        barrios.sort(key=lambda x: -(x.tendencia_anual or 0))
        criterio = ("mayor tendencia de revalorización — la rentabilidad no ordena "
                    "porque el alquiler es derivado del precio")

    return AnalisisZonas(
        ciudad=ciudad,
        superficie_tipo=superficie,
        total_barrios=len(barrios),
        barrios=[b.to_dict() for b in barrios],
        criterio_orden=criterio,
        mejor_rentabilidad=barrios[0].nombre if barrios else None,
        mejor_cash_flow=max(barrios, key=lambda x: x.cash_flow_mensual).nombre if barrios else None,
        mas_barato=min(barrios, key=lambda x: x.precio_vivienda).nombre if barrios else None,
        supuestos={
            "superficie_m2": superficie,
            "entrada_pct": s.entrada_pct,
            "interes_anual": s.interes_anual,
            "anios_hipoteca": s.anios_hipoteca,
            "vacancia_pct": s.vacancia_pct,
            "nota": "Todos los barrios se comparan con la MISMA vivienda tipo: si no, "
                    "se estarían comparando tamaños distintos en lugar de zonas.",
        },
        avisos=avisos,
        fuentes={
            "precio_m2": "deteccion-zonas-revalorizacion (proyecto del portfolio)",
            "hipoteca": "sistema francés con el tipo del Banco de España",
            "impuestos": "ITP por comunidad, normativa citada en impuestos.py",
            "alquiler": "estimación por rentabilidad bruta de la provincia",
        },
    )
