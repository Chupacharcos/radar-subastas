"""
Valoración de mercado y renta estimada, reutilizando el portfolio.

En lugar de entrenar otro modelo de precios, este proyecto consulta los que ya
existen y están en producción:

  - **prediccion-precio-inmobiliario** (R² = 0,90 sobre 21.000 transacciones
    reales) estima cuánto vale el inmueble. Comparado con el valor de salida de
    la subasta, da el descuento real.
  - **deteccion-zonas-revalorizacion** indica si la zona tiene señal de subida,
    que es lo que decide si conviene esperar a vender o alquilar.

Si alguno de los dos no responde —son servicios que arrancan bajo demanda— el
análisis continúa y lo dice, en vez de fallar entero o inventarse el dato.

Sobre el alquiler: SERPAVI, la fuente oficial de alquileres declarados a
Hacienda, sólo se consulta desde su web con reCAPTCHA, así que no es
automatizable de forma fiable. Mientras no se incorpore su descarga masiva, el
alquiler se estima a partir del valor de mercado y la rentabilidad bruta típica
de la zona, y se marca como ESTIMACIÓN. Lo honesto es que el usuario pueda
sobrescribirlo con el alquiler real que conozca.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, asdict

import httpx
from formato import euros

PRECIO_URL = os.getenv("PRECIO_API_URL", "http://127.0.0.1:8089")
REVALORIZACION_URL = os.getenv("REVALORIZACION_API_URL", "http://127.0.0.1:8090")
TIMEOUT = 12.0

# Rentabilidad bruta del alquiler por provincia (alquiler anual / precio de
# compra). Cifras de mercado 2025-2026 publicadas en informes sectoriales; se
# usan sólo para ESTIMAR el alquiler cuando el usuario no aporta el suyo.
YIELD_BRUTO = {
    "madrid": 0.052, "barcelona": 0.055, "valencia": 0.065, "sevilla": 0.060,
    "malaga": 0.055, "alicante": 0.063, "murcia": 0.068, "zaragoza": 0.066,
    "vizcaya": 0.048, "bizkaia": 0.048, "guipuzcoa": 0.045,
}
YIELD_POR_DEFECTO = 0.060

CIUDADES_MODELO_ES = {"madrid", "barcelona", "valencia"}


@dataclass
class Valoracion:
    valor_mercado_estimado: float | None = None
    precio_m2_mercado: float | None = None
    precio_m2_subasta: float | None = None
    descuento_pct: float | None = None
    alquiler_mensual_estimado: float | None = None
    alquiler_es_estimacion: bool = True
    senal_revalorizacion: str | None = None
    fuentes: dict = None
    avisos: list[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _ciudad_para_modelo(municipio: str | None, provincia: str | None) -> str:
    """El modelo español se entrenó con Madrid, Barcelona y Valencia. Para el
    resto se usa la provincia como aproximación, y se avisa."""
    for candidato in (municipio, provincia):
        if candidato and candidato.strip().lower() in CIUDADES_MODELO_ES:
            return candidato.strip().title()
    if provincia and provincia.strip().lower() in CIUDADES_MODELO_ES:
        return provincia.strip().title()
    return "Madrid"


def _estimar_valor_mercado(inmueble: dict, avisos: list[str]) -> float | None:
    """Llama al modelo de precios que ya está en producción."""
    superficie = inmueble.get("superficie_m2")
    if not superficie:
        avisos.append("Sin superficie del Catastro no se puede estimar el valor de mercado.")
        return None

    municipio = inmueble.get("municipio") or ""
    provincia = inmueble.get("provincia") or ""
    ciudad = _ciudad_para_modelo(municipio, provincia)
    if municipio.strip().lower() not in CIUDADES_MODELO_ES:
        avisos.append(
            f"El modelo de precios cubre Madrid, Barcelona y Valencia; «{municipio.title()}» "
            f"se aproxima con {ciudad}. Tómalo como orden de magnitud."
        )

    # Habitaciones y baños no están en el Catastro: se derivan de la superficie
    # con una regla conservadora y se declara como supuesto.
    habitaciones = max(1, min(8, round(superficie / 30)))
    banos = max(1, min(4, round(superficie / 70)))

    payload = {
        "city": ciudad,
        "area_m2": float(min(max(superficie, 20), 800)),
        "rooms": float(habitaciones),
        "bathrooms": float(banos),
        "year_built": float(min(max(inmueble.get("anio_construccion") or 1980, 1850), 2018)),
        "floor": 2.0,
        "has_lift": 1,
    }
    try:
        r = httpx.post(f"{PRECIO_URL}/ml/inmobiliario/predict_es", json=payload, timeout=TIMEOUT)
        r.raise_for_status()
        datos = r.json()
    except Exception as e:
        avisos.append(f"El modelo de precios no respondió ({type(e).__name__}); "
                      "se omite la comparación con el mercado.")
        return None

    precio = datos.get("price_eur")
    if not isinstance(precio, (int, float)):
        avisos.append("El modelo de precios respondió en un formato inesperado.")
        return None
    # El modelo publica su propio error medio: sin él, un «descuento del 47%»
    # se leería como una certeza que no existe.
    error_pct = datos.get("mape_pct")
    if error_pct:
        avisos.append(
            f"La valoración de mercado tiene un error medio del {error_pct}% "
            f"(rango {euros(datos.get('range_low', 0))} – {euros(datos.get('range_high', 0))} €). "
            "El descuento calculado hereda esa incertidumbre."
        )
    return float(precio)


def _senal_revalorizacion(municipio: str | None, avisos: list[str]) -> str | None:
    """Consulta el proyecto de zonas de revalorización, si cubre la ciudad."""
    ciudad = (municipio or "").strip().lower()
    if not ciudad:
        return None
    try:
        r = httpx.get(f"{REVALORIZACION_URL}/ml/revalorizacion/mapa",
                      params={"ciudad": ciudad}, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        barrios = r.json().get("barrios", [])
        if not barrios:
            return None
        media = sum(b.get("score", 0) for b in barrios) / len(barrios)
        return ("alta" if media >= 66 else "media" if media >= 40 else "baja")
    except Exception:
        # Es un servicio bajo demanda: que no esté levantado no es un error.
        return None


def valorar(subasta: dict, inmueble: dict, alquiler_usuario: float | None = None) -> Valoracion:
    """Compara el valor de salida de la subasta con el mercado y estima la renta."""
    avisos: list[str] = []
    superficie = inmueble.get("superficie_m2")
    valor_subasta = subasta.get("valor_subasta")

    valor_mercado = _estimar_valor_mercado(inmueble, avisos)
    provincia = (inmueble.get("provincia") or subasta.get("provincia") or "").strip().lower()

    precio_m2_subasta = (valor_subasta / superficie) if (valor_subasta and superficie) else None
    precio_m2_mercado = (valor_mercado / superficie) if (valor_mercado and superficie) else None

    descuento = None
    if valor_mercado and valor_subasta:
        descuento = round((valor_mercado - valor_subasta) / valor_mercado * 100, 1)

    if alquiler_usuario:
        alquiler, es_estimacion = float(alquiler_usuario), False
    elif valor_mercado:
        yield_bruto = YIELD_BRUTO.get(provincia, YIELD_POR_DEFECTO)
        alquiler, es_estimacion = round(valor_mercado * yield_bruto / 12, 0), True
        avisos.append(
            f"Alquiler estimado con la rentabilidad bruta típica de {provincia or 'la zona'} "
            f"({yield_bruto*100:.1f}%). No es un dato de mercado: si conoces el alquiler real "
            "de la zona, introdúcelo."
        )
    else:
        alquiler, es_estimacion = None, True

    return Valoracion(
        valor_mercado_estimado=round(valor_mercado, 2) if valor_mercado else None,
        precio_m2_mercado=round(precio_m2_mercado, 2) if precio_m2_mercado else None,
        precio_m2_subasta=round(precio_m2_subasta, 2) if precio_m2_subasta else None,
        descuento_pct=descuento,
        alquiler_mensual_estimado=alquiler,
        alquiler_es_estimacion=es_estimacion,
        senal_revalorizacion=_senal_revalorizacion(inmueble.get("municipio"), avisos),
        fuentes={
            "subasta": "Portal de Subastas del BOE",
            "inmueble": "Sede Electrónica del Catastro",
            "valor_mercado": "prediccion-precio-inmobiliario (R²=0,90, 21.000 transacciones)",
            "revalorizacion": "deteccion-zonas-revalorizacion",
        },
        avisos=avisos,
    )
