"""
Precio de compra de la vivienda, en euros por metro cuadrado y al día de hoy.

Sustituye a lo que había: una llamada a un modelo del portfolio entrenado con
**idealista18**, que son anuncios reales pero de **2018**. Ocho años. El propio
índice oficial de precios del INE dice que en la Comunidad de Madrid la vivienda
subió un 49,6 % entre 2018 y 2025, así que aquel «valor de mercado» estaba
sistemáticamente bajo y el «descuento» de cada subasta —el número que preside el
proyecto— salía mal.

Lo honesto no es afinar un modelo viejo, es cambiar el dato. El Ministerio de
Vivienda publica el **valor tasado de la vivienda libre** en €/m², por provincia
y trimestre, desde 1995 y hasta el trimestre en curso:

    cdn.mivau.gob.es/portal-web-mivau/Datos_MIVAU/CSV/VDP006_01.csv

Es una tasación media, no un precio de cierre, y llega sólo a provincia. A cambio
es un dato oficial, actual y verificable, y el proyecto puede decir exactamente
de dónde sale cada euro.

Sobre lo que esto NO es: no es una tasación de un inmueble concreto. No sabe si
el piso está reformado, en qué planta va ni si da a un patio. Multiplicar la
media provincial por la superficie del Catastro da un **orden de magnitud**, y
así se declara. Un modelo por características exigiría microdatos de
transacciones recientes, y no hay ninguno publicado en abierto en España: el
Consejo General del Notariado y el Colegio de Registradores publican agregados,
no operación a operación.
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

from formato import euros

CACHE_DIR = Path(__file__).parent / "data" / "precio_compra"
MIVAU_URL = "https://cdn.mivau.gob.es/portal-web-mivau/Datos_MIVAU/CSV/VDP006_01.csv"
TIMEOUT = 120.0
MAX_BYTES = 20 * 1024 * 1024
REGIMEN = "Libre"

FUENTE = ("Ministerio de Vivienda y Agenda Urbana, valor tasado de la vivienda "
          "libre (€/m², por provincia y trimestre)")


@dataclass
class PrecioProvincia:
    codigo_provincia: str = ""
    provincia: str = ""
    euros_m2: float | None = None
    anio: int | None = None
    trimestre: int | None = None
    variacion_anual_pct: float | None = None
    fuente: str = FUENTE
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ValorReferencia:
    """Lo que valdría un inmueble según el precio oficial de su provincia."""
    valor_referencia: float | None = None
    euros_m2: float | None = None
    superficie_m2: float | None = None
    periodo: str | None = None
    provincia: str | None = None
    fuente: str = FUENTE
    avisos: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _num(valor: str) -> float | None:
    v = (valor or "").strip().replace(",", ".")
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _destila(contenido: str) -> dict:
    """CSV → {codigo_provincia: {nombre, serie: {'2026-1': 4047.5, …}}}."""
    out: dict[str, dict] = {}
    for fila in csv.DictReader(io.StringIO(contenido), delimiter=";"):
        if (fila.get("Régimen") or "").strip() != REGIMEN:
            continue
        valor = _num(fila.get("Valor") or "")
        if valor is None:
            continue
        cp = (fila.get("CPRO") or "").strip().zfill(2)
        try:
            anio, trimestre = int(fila["Año"]), int(fila["Trimestre"])
        except (KeyError, ValueError):
            continue
        reg = out.setdefault(cp, {"nombre": (fila.get("Provincia") or "").strip(),
                                  "serie": {}})
        reg["serie"][f"{anio}-{trimestre}"] = valor
    return out


def _carga(forzar: bool = False) -> dict:
    destino = CACHE_DIR / "valor_tasado.json"
    if destino.exists() and not forzar:
        try:
            return json.loads(destino.read_text(encoding="utf-8"))["provincias"]
        except Exception:
            pass

    with httpx.stream("GET", MIVAU_URL, timeout=TIMEOUT, follow_redirects=True) as r:
        r.raise_for_status()
        trozos, total = [], 0
        for trozo in r.iter_bytes():
            total += len(trozo)
            if total > MAX_BYTES:
                raise ValueError("El fichero de valor tasado supera el límite previsto")
            trozos.append(trozo)
    provincias = _destila(b"".join(trozos).decode("utf-8-sig", "ignore"))
    if not provincias:
        raise ValueError("El fichero de valor tasado no trajo ninguna provincia")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps({
        "origen": MIVAU_URL,
        "descargado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provincias": provincias,
    }, ensure_ascii=False), encoding="utf-8")
    return provincias


def _ultimo(serie: dict) -> tuple[int, int, float] | None:
    if not serie:
        return None
    clave = max(serie, key=lambda k: tuple(int(x) for x in k.split("-")))
    anio, trimestre = (int(x) for x in clave.split("-"))
    return anio, trimestre, serie[clave]


def precio_provincia(codigo_provincia: str) -> PrecioProvincia:
    """Último €/m² tasado publicado para una provincia."""
    cp = str(codigo_provincia).strip().zfill(2)
    try:
        provincias = _carga()
    except Exception as e:
        return PrecioProvincia(codigo_provincia=cp,
                               error=f"No se pudo obtener el valor tasado: {e}")

    datos = provincias.get(cp)
    if not datos:
        return PrecioProvincia(codigo_provincia=cp,
                               error=f"La provincia {cp} no aparece en el fichero")
    ultimo = _ultimo(datos["serie"])
    if not ultimo:
        return PrecioProvincia(codigo_provincia=cp, provincia=datos["nombre"],
                               error="La provincia no tiene ningún valor publicado")

    anio, trimestre, valor = ultimo
    hace_un_anio = datos["serie"].get(f"{anio - 1}-{trimestre}")
    return PrecioProvincia(
        codigo_provincia=cp,
        provincia=datos["nombre"],
        euros_m2=valor,
        anio=anio,
        trimestre=trimestre,
        variacion_anual_pct=(round((valor / hace_un_anio - 1) * 100, 1)
                             if hace_un_anio else None),
    )


def valorar_por_superficie(codigo_provincia: str,
                           superficie_m2: float | None) -> ValorReferencia:
    """Valor de referencia de un inmueble: €/m² oficial de su provincia × superficie."""
    if not superficie_m2:
        return ValorReferencia(error="Sin superficie del Catastro no se puede valorar")

    p = precio_provincia(codigo_provincia)
    if p.error or not p.euros_m2:
        return ValorReferencia(error=p.error or "Sin precio para esa provincia")

    avisos = [
        f"Valor de referencia: {euros(p.euros_m2)} €/m² tasados de media en la provincia "
        f"de {p.provincia} ({p.anio}T{p.trimestre}), por los {superficie_m2:.0f} m² del "
        "Catastro.",
        "Es una media PROVINCIAL de tasaciones, no una tasación de este inmueble: no "
        "distingue barrio, estado de conservación, planta ni orientación. Sirve como "
        "orden de magnitud para situar el precio de salida, no como valoración.",
    ]
    if p.variacion_anual_pct is not None:
        avisos.append(f"En esa provincia el valor tasado se movió un "
                      f"{p.variacion_anual_pct:+.1f} % en el último año.")

    return ValorReferencia(
        valor_referencia=round(p.euros_m2 * superficie_m2, 2),
        euros_m2=p.euros_m2,
        superficie_m2=superficie_m2,
        periodo=f"{p.anio}T{p.trimestre}",
        provincia=p.provincia,
        avisos=avisos,
    )


def frescura() -> dict:
    """Último trimestre publicado, para el control de vigencia."""
    try:
        provincias = _carga()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}", "origen": MIVAU_URL}
    ultimos = [_ultimo(d["serie"]) for d in provincias.values()]
    ultimos = [u for u in ultimos if u]
    if not ultimos:
        return {"error": "sin series", "origen": MIVAU_URL}
    anio, trimestre, _ = max(ultimos, key=lambda u: (u[0], u[1]))
    return {"origen": MIVAU_URL, "provincias": len(provincias),
            "ultimo_periodo": f"{anio}T{trimestre}"}
