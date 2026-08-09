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

Ya no queda ningún supuesto en el camino. Cuando el ministerio no publica el
alquiler de un municipio se usa la mediana de los municipios de su provincia que
sí lo publican —una medición de ámbito más ancho, declarada como tal— en lugar de
la «rentabilidad bruta típica» que había antes, que no procedía de ninguna parte.
Si no hay ni eso, no se calcula la rentabilidad y se dice.

Lo que se ha quitado, y por qué: la «señal de revalorización» (alta/media/baja)
venía de un modelo entrenado con datos sintéticos. Un adjetivo derivado de datos
inventados no mejora por ir acompañado de un aviso, así que ya no se calcula.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field

import alquiler_real
import precio_compra


@dataclass
class Valoracion:
    valor_mercado_estimado: float | None = None
    precio_m2_mercado: float | None = None
    precio_m2_subasta: float | None = None
    descuento_pct: float | None = None
    alquiler_mensual: float | None = None
    alquiler_ambito: str | None = None      # inmueble | municipio | provincia
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


def _alquiler(inmueble: dict, superficie: float | None,
              avisos: list[str]) -> tuple[float | None, dict | None]:
    """Alquiler mensual del inmueble, siempre a partir de alquileres medidos.

    Primero el del propio municipio. Si el ministerio no lo publica —más de la
    mitad de los municipios de España, todos pequeños— se usa la mediana de los
    municipios de su provincia que sí lo publican. Sigue siendo una medición,
    sólo que de un ámbito más ancho, y la respuesta dice cuál de las dos es.
    """
    provincia, municipio = _codigos_ine(inmueble)
    if not superficie:
        return None, None

    if municipio:
        importe, origen = alquiler_real.alquiler_estimado_de(municipio, superficie)
        if importe:
            avisos.append(
                f"Alquiler calculado con {origen['euros_m2_mes']} €/m² al mes, que es "
                f"el dato real del municipio ({origen['base']}, {origen['anio']}). "
                f"{origen['aviso']}"
            )
            return importe, origen

    if provincia:
        prov = alquiler_real.mediana_provincial(provincia)
        if prov:
            avisos.append(
                f"El ministerio no publica el alquiler de este municipio: omite los "
                f"pequeños porque con pocos contratos declarados la mediana dejaría de "
                f"ser anónima. Se usa la MEDIANA de los {prov['municipios']} municipios "
                f"de la provincia que sí lo publican: {prov['euros_m2_mes']} €/m² al "
                f"mes ({prov['anio']}), en un recorrido de {prov['minimo']} a "
                f"{prov['maximo']}. Es un dato medido de ámbito provincial, no una "
                "medida de este municipio: si conoces el alquiler real, introdúcelo."
            )
            return round(prov["euros_m2_mes"] * superficie, 0), {
                "disponible": True, "base": "mediana provincial de municipios publicados",
                "ambito": "provincia", "euros_m2_mes": prov["euros_m2_mes"],
                "anio": prov["anio"], "municipios_en_la_mediana": prov["municipios"],
                "fuente": prov["fuente"],
            }

    avisos.append("No hay ningún alquiler publicado para esta zona, así que no se "
                  "calcula la rentabilidad. Introduce el alquiler real si lo conoces.")
    return None, None


def valorar(subasta: dict, inmueble: dict, alquiler_usuario: float | None = None) -> Valoracion:
    """Compara el valor de salida de la subasta con el mercado y con el alquiler real."""
    avisos: list[str] = []
    superficie = inmueble.get("superficie_m2")
    valor_subasta = subasta.get("valor_subasta")
    provincia, municipio = _codigos_ine(inmueble)

    referencia = precio_compra.valorar_por_superficie(
        provincia or "", superficie, municipio, inmueble.get("anio_construccion"))
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
        alquiler, origen = float(alquiler_usuario), {
            "disponible": True, "base": "alquiler aportado por el usuario",
            "ambito": "inmueble",
        }
    else:
        alquiler, origen = _alquiler(inmueble, superficie, avisos)

    return Valoracion(
        valor_mercado_estimado=round(valor_mercado, 2) if valor_mercado else None,
        precio_m2_mercado=referencia.euros_m2,
        precio_m2_subasta=round(precio_m2_subasta, 2) if precio_m2_subasta else None,
        descuento_pct=descuento,
        alquiler_mensual=alquiler,
        alquiler_ambito=(origen or {}).get("ambito", "municipio" if origen else None),
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
