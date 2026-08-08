"""
Valoración de mercado y alquiler, con datos oficiales y actuales.

Este módulo se reescribió entero porque los dos números que producía eran falsos,
cada uno a su manera:

  - El **valor de mercado** salía de un modelo del portfolio entrenado con
    *idealista18*: anuncios reales, pero de **2018**. Como el descuento de cada
    subasta se calcula contra ese valor, el titular del proyecto estaba mal.
  - El **alquiler** se derivaba del valor multiplicando por una «rentabilidad
    bruta típica de la provincia» que no procedía de ninguna fuente citable. De
    ahí venía la circularidad que hacía que todos los barrios rindieran igual.

Ahora los dos son datos publicados, con año y organismo:

  - Valor: **valor tasado de la vivienda libre** del Ministerio de Vivienda,
    €/m² por provincia y trimestre, al trimestre en curso (`precio_compra`).
  - Alquiler: **mediana del alquiler por municipio** del mismo ministerio, de los
    arrendamientos declarados a la Agencia Tributaria, más el registro de fianzas
    de Cataluña para los contratos nuevos (`alquiler_real`).

Ninguno de los dos es una tasación de este inmueble concreto, y el módulo lo dice
en cada respuesta. La diferencia con lo anterior no es que ahora haya certeza: es
que ahora se puede comprobar de dónde sale cada cifra.

Lo que se ha quitado, y por qué: la «señal de revalorización» (alta/media/baja)
venía de un modelo entrenado con datos sintéticos. Un adjetivo derivado de datos
inventados no mejora por ir acompañado de un aviso, así que ya no se calcula.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field

import alquiler_real
import precio_compra

# Rentabilidad bruta de último recurso, sólo para municipios sin dato publicado
# de alquiler. Es un supuesto, no una medición, y se declara como tal cada vez
# que se usa. Antes era la vía principal; ahora es el plan C.
YIELD_ULTIMO_RECURSO = 0.060


@dataclass
class Valoracion:
    valor_mercado_estimado: float | None = None
    precio_m2_mercado: float | None = None
    precio_m2_subasta: float | None = None
    descuento_pct: float | None = None
    alquiler_mensual_estimado: float | None = None
    alquiler_es_estimacion: bool = True
    origen_alquiler: dict | None = None
    origen_valor: dict | None = None
    fuentes: dict = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _codigos_ine(inmueble: dict) -> tuple[str | None, str | None]:
    """(provincia, municipio) en el formato de 2 y 5 dígitos del INE."""
    cp = inmueble.get("codigo_ine_provincia")
    cm = inmueble.get("codigo_ine_municipio")
    if not cp:
        return None, None
    provincia = str(cp).zfill(2)
    municipio = provincia + str(cm).zfill(3) if cm else None
    return provincia, municipio


def _alquiler(inmueble: dict, superficie: float | None, valor_mercado: float | None,
              avisos: list[str]) -> tuple[float | None, bool, dict | None]:
    """Alquiler mensual: el real del municipio si existe, y si no se declara."""
    _, municipio = _codigos_ine(inmueble)
    if municipio and superficie:
        importe, origen = alquiler_real.alquiler_estimado_de(municipio, superficie)
        if importe:
            avisos.append(
                f"Alquiler calculado con {origen['euros_m2_mes']} €/m² al mes, que es "
                f"el dato real del municipio ({origen['base']}, {origen['anio']}). "
                f"{origen['aviso']}"
            )
            return importe, False, origen

    if not valor_mercado:
        return None, True, None

    # Plan C: sin dato publicado del municipio, se vuelve al supuesto, diciéndolo.
    avisos.append(
        f"No hay alquiler publicado para este municipio, así que se estima con una "
        f"rentabilidad bruta del {YIELD_ULTIMO_RECURSO*100:.1f} %. Esto SÍ es un "
        "supuesto: el ministerio omite los municipios pequeños porque con pocos "
        "contratos la mediana dejaría de ser anónima. Si conoces el alquiler real, "
        "introdúcelo."
    )
    return round(valor_mercado * YIELD_ULTIMO_RECURSO / 12, 0), True, {
        "disponible": False, "base": "supuesto de rentabilidad bruta",
    }


def valorar(subasta: dict, inmueble: dict, alquiler_usuario: float | None = None) -> Valoracion:
    """Compara el valor de salida de la subasta con el mercado y con el alquiler real."""
    avisos: list[str] = []
    superficie = inmueble.get("superficie_m2")
    valor_subasta = subasta.get("valor_subasta")
    provincia, _ = _codigos_ine(inmueble)

    referencia = precio_compra.valorar_por_superficie(provincia or "", superficie)
    if referencia.error:
        avisos.append(f"Sin valor de referencia: {referencia.error}")
    else:
        avisos.extend(referencia.avisos)
    valor_mercado = referencia.valor_referencia

    precio_m2_subasta = (valor_subasta / superficie) if (valor_subasta and superficie) else None
    descuento = None
    if valor_mercado and valor_subasta:
        descuento = round((valor_mercado - valor_subasta) / valor_mercado * 100, 1)

    if alquiler_usuario:
        alquiler, es_estimacion, origen = float(alquiler_usuario), False, {
            "disponible": True, "base": "alquiler aportado por el usuario",
        }
    else:
        alquiler, es_estimacion, origen = _alquiler(inmueble, superficie, valor_mercado, avisos)

    return Valoracion(
        valor_mercado_estimado=round(valor_mercado, 2) if valor_mercado else None,
        precio_m2_mercado=referencia.euros_m2,
        precio_m2_subasta=round(precio_m2_subasta, 2) if precio_m2_subasta else None,
        descuento_pct=descuento,
        alquiler_mensual_estimado=alquiler,
        alquiler_es_estimacion=es_estimacion,
        origen_alquiler=origen,
        origen_valor=referencia.to_dict() if not referencia.error else None,
        fuentes={
            "subasta": "Portal de Subastas del BOE",
            "inmueble": "Sede Electrónica del Catastro",
            "valor_mercado": precio_compra.FUENTE,
            "alquiler": alquiler_real.FUENTE_MIVAU,
        },
        avisos=avisos,
    )
