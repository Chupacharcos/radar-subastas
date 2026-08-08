"""
Evolución real del alquiler y del precio de compra (INE).

El agujero de este proyecto era el alquiler: sin SERPAVI —los alquileres
declarados a Hacienda, que siguen tras un reCAPTCHA— el alquiler se derivaba del
precio con una rentabilidad fija, y eso hacía que todos los barrios rindieran
casi lo mismo. Circularidad declarada, pero circularidad.

El **IPVA** (Índice de Precios de Vivienda en Alquiler, operación 432 del INE)
tapa media parte del agujero. Se construye con los contratos de alquiler
declarados a la Agencia Tributaria, o sea con la misma materia prima que
SERPAVI, y sí se puede descargar. Da dos cosas por municipio (los mayores de
10.000 habitantes) y por distrito de capital de provincia:

  - el **índice** con base 2015 = 100, que dice cuánto ha subido el alquiler
    desde entonces,
  - y la **variación anual**.

Lo que NO da es el nivel: no hay un €/m² al mes. Así que esto no sustituye a
SERPAVI, lo complementa. Sirve para lo que de verdad decide una compra a largo
plazo: si en esa zona el alquiler sube más deprisa que el precio —el yield se
abre, comprar hoy renta más cada año— o al revés.

Para el otro lado de esa comparación se usa el **IPV** (Índice de Precios de
Vivienda, operación 15), que es el índice oficial de precios de compra. Ojo al
grano: el IPV sólo llega a comunidad autónoma, mientras que el IPVA llega a
municipio y distrito. La comparación se hace por tanto entre un dato local de
alquiler y uno regional de precio, y la respuesta lo dice.

Acceso: igual que en `renta_ine`, la API JSON del INE rechaza estas tablas, así
que se descarga el CSV oficial y se destila a lo mínimo útil.
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

CACHE_DIR = Path(__file__).parent / "data" / "alquiler"
CSV_URL = "https://www.ine.es/jaxiT3/files/t/es/csv_bdsc/{tabla}.csv"
TIMEOUT = 180.0
MAX_BYTES = 60 * 1024 * 1024

# Tablas del INE. Sondeadas el 2026-08-08.
TABLA_IPVA_MUNICIPIOS = 59060   # Índices por municipio (municipios > 10.000 hab.)
TABLA_IPVA_DISTRITOS = 59061    # Índices por distritos de municipios capitales
TABLA_IPV_CCAA = 80271          # IPV por CCAA, medias anuales

BASE_IPVA = "2015 = 100"
FUENTE_IPVA = "INE, Índice de Precios de Vivienda en Alquiler (IPVA, operación 432)"
FUENTE_IPV = "INE, Índice de Precios de Vivienda (IPV, operación 15)"

# Provincia (código INE) → comunidad autónoma (código INE), que es el grano al
# que publica el IPV.
PROVINCIA_A_CCAA = {
    "01": "16", "02": "08", "03": "10", "04": "01", "05": "07", "06": "11",
    "07": "04", "08": "09", "09": "07", "10": "11", "11": "01", "12": "10",
    "13": "08", "14": "01", "15": "12", "16": "08", "17": "09", "18": "01",
    "19": "08", "20": "16", "21": "01", "22": "02", "23": "01", "24": "07",
    "25": "09", "26": "17", "27": "12", "28": "13", "29": "01", "30": "14",
    "31": "15", "32": "12", "33": "03", "34": "07", "35": "05", "36": "12",
    "37": "07", "38": "05", "39": "06", "40": "07", "41": "01", "42": "07",
    "43": "09", "44": "02", "45": "08", "46": "10", "47": "07", "48": "16",
    "49": "07", "50": "02", "51": "18", "52": "19",
}


@dataclass
class Tendencia:
    """Cómo se ha movido un índice en un ámbito concreto."""
    ambito: str = ""                       # municipio | distrito | comunidad
    codigo: str = ""
    nombre: str = ""
    anio: int | None = None
    indice: float | None = None
    base: str | None = None
    variacion_anual_pct: float | None = None
    variacion_5a_pct: float | None = None
    acumulada_desde_base_pct: float | None = None
    fuente: str = ""
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PrecioVsAlquiler:
    """Alquiler y precio de compra en el mismo año, uno contra otro."""
    anio: int | None = None
    variacion_alquiler_pct: float | None = None
    variacion_precio_pct: float | None = None
    brecha_pp: float | None = None          # alquiler − precio, en puntos porcentuales
    lectura: str = ""
    alquiler: dict = field(default_factory=dict)
    precio: dict = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _num(valor: str) -> float | None:
    """'122,625' → 122.625. Sólo se tratan puntos como miles si hay coma."""
    v = (valor or "").strip()
    if not v or v in ("..", ".", "-"):
        return None
    if "," in v:
        v = v.replace(".", "").replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return None


def _cache_path(tabla: int) -> Path:
    return CACHE_DIR / f"{tabla}.json"


def _descargar(tabla: int) -> str:
    with httpx.stream("GET", CSV_URL.format(tabla=tabla), timeout=TIMEOUT,
                      follow_redirects=True) as r:
        r.raise_for_status()
        trozos, total = [], 0
        for trozo in r.iter_bytes():
            total += len(trozo)
            if total > MAX_BYTES:
                raise ValueError(f"El CSV de la tabla {tabla} supera el límite previsto")
            trozos.append(trozo)
    return b"".join(trozos).decode("utf-8-sig", "ignore")


def _destila(contenido: str, col_serie: str, col_tipo: str,
             etiquetas: dict[str, str], filtros: dict[str, str] | None = None) -> dict:
    """CSV del INE → {codigo: {nombre, indice: {año: v}, variacion: {año: v}}}.

    `col_serie` es la columna que identifica la serie ('Municipio', 'Distritos'…);
    sus valores vienen como «28079 Madrid», con el código INE por delante.
    `etiquetas` traduce el valor de la columna «Tipo de dato» a la clave interna
    ('Índice' → 'indice'), porque el INE la nombra distinto en cada tabla.
    """
    out: dict[str, dict] = {}
    lector = csv.DictReader(io.StringIO(contenido), delimiter=";")
    campos = [c.strip().lstrip("﻿") for c in (lector.fieldnames or [])]
    if col_serie not in campos or col_tipo not in campos:
        return out

    def limpia(fila: dict) -> dict:
        return {(k or "").strip().lstrip("﻿"): v for k, v in fila.items()}

    for cruda in lector:
        fila = limpia(cruda)
        if filtros and any((fila.get(k) or "").strip() != v for k, v in filtros.items()):
            continue
        serie = (fila.get(col_serie) or "").strip()
        if not serie:
            continue
        clave = etiquetas.get((fila.get(col_tipo) or "").strip())
        if not clave:
            continue
        valor = _num(fila.get("Total") or "")
        if valor is None:
            continue
        try:
            anio = int((fila.get("Periodo") or "").strip())
        except ValueError:
            continue

        codigo, _, nombre = serie.partition(" ")
        if not codigo.isdigit():          # «Total Nacional» y similares
            codigo, nombre = "ES", serie
        reg = out.setdefault(codigo, {"nombre": nombre.strip() or serie,
                                      "indice": {}, "variacion": {}})
        reg[clave][str(anio)] = valor
    return out


def _carga(tabla: int, forzar: bool = False) -> dict:
    """Series destiladas de una tabla, desde caché o descargando."""
    destino = _cache_path(tabla)
    if destino.exists() and not forzar:
        try:
            return json.loads(destino.read_text(encoding="utf-8"))["series"]
        except Exception:
            pass

    contenido = _descargar(tabla)
    if tabla == TABLA_IPVA_MUNICIPIOS:
        series = _destila(contenido, "Municipio", "Tipo de dato",
                          {"Índice": "indice", "Variación anual": "variacion"})
    elif tabla == TABLA_IPVA_DISTRITOS:
        series = _destila(contenido, "Distritos", "Tipo de dato",
                          {"Índice": "indice", "Variación anual": "variacion"})
    elif tabla == TABLA_IPV_CCAA:
        series = _destila(contenido, "Comunidades y Ciudades Autónomas",
                          "Índices y tasas",
                          {"Media anual": "indice", "Variación anual": "variacion"},
                          filtros={"General, vivienda nueva y de segunda mano": "General"})
    else:
        raise KeyError(f"Tabla {tabla} no soportada")

    if not series:
        raise ValueError(f"El CSV de la tabla {tabla} no trajo ninguna serie utilizable")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps({
        "tabla_ine": tabla,
        "descargado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "series": series,
    }, ensure_ascii=False), encoding="utf-8")
    return series


def _a_tendencia(codigo: str, datos: dict, ambito: str, fuente: str,
                 base: str | None) -> Tendencia:
    indices = {int(a): v for a, v in (datos.get("indice") or {}).items()}
    variaciones = {int(a): v for a, v in (datos.get("variacion") or {}).items()}
    if not indices:
        return Tendencia(ambito=ambito, codigo=codigo, nombre=datos.get("nombre", ""),
                         fuente=fuente, error="La serie no trae índices")

    anio = max(indices)
    indice = indices[anio]
    hace5 = indices.get(anio - 5)
    return Tendencia(
        ambito=ambito,
        codigo=codigo,
        nombre=datos.get("nombre", ""),
        anio=anio,
        indice=round(indice, 3),
        base=base,
        variacion_anual_pct=variaciones.get(anio),
        variacion_5a_pct=round((indice / hace5 - 1) * 100, 2) if hace5 else None,
        # El índice es base 100, así que el propio índice ya es el acumulado.
        acumulada_desde_base_pct=round(indice - 100, 2) if base else None,
        fuente=fuente,
    )


def tendencia_alquiler_municipio(codigo_ine_municipio: str) -> Tendencia:
    """Evolución del alquiler en un municipio, por su código INE de 5 dígitos.

    El código es el que devuelve el Catastro (provincia + municipio). Emparejar
    por código y no por nombre es lo que evita el fallo de «Las Rozas de Madrid»
    encajando con «Madrid».
    """
    codigo = str(codigo_ine_municipio).strip().zfill(5)
    try:
        series = _carga(TABLA_IPVA_MUNICIPIOS)
    except Exception as e:
        return Tendencia(ambito="municipio", codigo=codigo, fuente=FUENTE_IPVA,
                         error=f"No se pudo obtener el IPVA del INE: {e}")

    datos = series.get(codigo)
    if not datos:
        return Tendencia(
            ambito="municipio", codigo=codigo, fuente=FUENTE_IPVA,
            error="El INE sólo publica el IPVA de municipios de más de 10.000 "
                  "habitantes, y este no está entre ellos.")
    return _a_tendencia(codigo, datos, "municipio", FUENTE_IPVA, BASE_IPVA)


def distritos_de(codigo_ine_municipio: str) -> list[str]:
    """Códigos de distrito con IPVA de un municipio (sólo capitales de provincia)."""
    codigo = str(codigo_ine_municipio).strip().zfill(5)
    try:
        series = _carga(TABLA_IPVA_DISTRITOS)
    except Exception:
        return []
    return sorted(c for c in series if c.startswith(codigo) and len(c) == 7)


def tendencia_alquiler_distrito(codigo_distrito: str) -> Tendencia:
    """Evolución del alquiler en un distrito, por su código de 7 dígitos
    (5 del municipio + 2 del distrito), p. ej. `2807904` = Madrid, Salamanca."""
    codigo = str(codigo_distrito).strip()
    try:
        series = _carga(TABLA_IPVA_DISTRITOS)
    except Exception as e:
        return Tendencia(ambito="distrito", codigo=codigo, fuente=FUENTE_IPVA,
                         error=f"No se pudo obtener el IPVA del INE: {e}")

    datos = series.get(codigo)
    if not datos:
        return Tendencia(
            ambito="distrito", codigo=codigo, fuente=FUENTE_IPVA,
            error="El INE publica el IPVA por distrito sólo en las capitales de "
                  "provincia; este distrito no aparece.")
    return _a_tendencia(codigo, datos, "distrito", FUENTE_IPVA, BASE_IPVA)


def tendencia_precio_compra(codigo_provincia: str) -> Tendencia:
    """Evolución del precio de compra en la comunidad autónoma de una provincia.

    El IPV no baja de comunidad autónoma; usarlo como si fuera del municipio
    sería inventar precisión.
    """
    cp = str(codigo_provincia).strip().zfill(2)
    ccaa = PROVINCIA_A_CCAA.get(cp)
    if not ccaa:
        return Tendencia(ambito="comunidad", codigo=cp, fuente=FUENTE_IPV,
                         error=f"Código de provincia desconocido: {cp}")
    try:
        series = _carga(TABLA_IPV_CCAA)
    except Exception as e:
        return Tendencia(ambito="comunidad", codigo=ccaa, fuente=FUENTE_IPV,
                         error=f"No se pudo obtener el IPV del INE: {e}")

    datos = series.get(ccaa)
    if not datos:
        return Tendencia(ambito="comunidad", codigo=ccaa, fuente=FUENTE_IPV,
                         error="La comunidad no aparece en el IPV")
    # El IPV se rebasa cada pocos años, así que la base se toma del propio dato:
    # el año cuyo índice vale 100. Si no lo hay, no se afirma ninguna base.
    indices = {int(a): v for a, v in (datos.get("indice") or {}).items()}
    anio_base = next((a for a, v in sorted(indices.items()) if abs(v - 100) < 1e-6), None)
    base = f"{anio_base} = 100" if anio_base else None
    return _a_tendencia(ccaa, datos, "comunidad", FUENTE_IPV, base)


def _lectura_brecha(brecha: float) -> str:
    if brecha >= 2:
        return ("El alquiler sube más deprisa que el precio de compra: la "
                "rentabilidad de comprar aquí se está ensanchando.")
    if brecha <= -2:
        return ("El precio de compra sube más deprisa que el alquiler: la "
                "rentabilidad se está estrechando, comprar hoy renta menos que "
                "hace un año.")
    return ("Alquiler y precio de compra se mueven casi a la par: la "
            "rentabilidad de la zona se mantiene.")


def precio_vs_alquiler(codigo_ine_municipio: str | None,
                       codigo_provincia: str | None,
                       codigo_distrito: str | None = None) -> PrecioVsAlquiler:
    """Contrasta cuánto sube el alquiler con cuánto sube el precio de compra.

    Es la única pregunta que estos dos índices responden bien: no dicen cuánto
    se paga, dicen hacia dónde va. Se compara el último año que tengan en común,
    porque el IPV publica antes que el IPVA y comparar años distintos sería
    inventar una brecha que no existe.
    """
    avisos: list[str] = []

    alq = None
    if codigo_distrito:
        alq = tendencia_alquiler_distrito(codigo_distrito)
        if alq.error and codigo_ine_municipio:
            avisos.append(f"Sin dato de distrito ({alq.error}) se usa el del municipio.")
            alq = None
    if alq is None and codigo_ine_municipio:
        alq = tendencia_alquiler_municipio(codigo_ine_municipio)
    if alq is None:
        return PrecioVsAlquiler(error="Hace falta el código INE del municipio o del distrito")

    if not codigo_provincia and codigo_ine_municipio:
        codigo_provincia = str(codigo_ine_municipio).zfill(5)[:2]
    pre = tendencia_precio_compra(codigo_provincia or "")

    if alq.error or pre.error:
        return PrecioVsAlquiler(
            alquiler=alq.to_dict(), precio=pre.to_dict(),
            error=alq.error or pre.error,
        )

    # Último año con variación en ambas series.
    try:
        series_alq = _carga(TABLA_IPVA_DISTRITOS if alq.ambito == "distrito"
                            else TABLA_IPVA_MUNICIPIOS)[alq.codigo]["variacion"]
        series_pre = _carga(TABLA_IPV_CCAA)[pre.codigo]["variacion"]
    except Exception as e:
        return PrecioVsAlquiler(alquiler=alq.to_dict(), precio=pre.to_dict(),
                                error=f"No se pudieron cruzar las series: {e}")

    comunes = sorted({int(a) for a in series_alq} & {int(a) for a in series_pre})
    if not comunes:
        return PrecioVsAlquiler(alquiler=alq.to_dict(), precio=pre.to_dict(),
                                error="Las dos series no comparten ningún año")

    anio = comunes[-1]
    v_alq = series_alq[str(anio)]
    v_pre = series_pre[str(anio)]
    brecha = round(v_alq - v_pre, 2)

    if anio < max(int(a) for a in series_pre):
        avisos.append(f"El IPV ya publica {max(int(a) for a in series_pre)}, pero el IPVA "
                      f"llega a {anio}; se compara {anio}, el último año común.")
    avisos.append(f"El alquiler es de ámbito {alq.ambito} ({alq.nombre}) y el precio de "
                  f"compra de comunidad autónoma ({pre.nombre}): el INE no publica el "
                  "IPV por municipio. La comparación vale como tendencia, no como "
                  "medida exacta de esa calle.")
    avisos.append("Son índices, no precios: dicen cuánto ha subido el alquiler, no "
                  "cuánto se paga. El nivel en €/m² sigue sin fuente pública "
                  "descargable (SERPAVI exige resolver un reCAPTCHA).")

    return PrecioVsAlquiler(
        anio=anio,
        variacion_alquiler_pct=v_alq,
        variacion_precio_pct=v_pre,
        brecha_pp=brecha,
        lectura=_lectura_brecha(brecha),
        alquiler=alq.to_dict(),
        precio=pre.to_dict(),
        avisos=avisos,
    )


def frescura() -> dict:
    """Último año publicado de cada índice, para el control de vigencia."""
    out: dict = {}
    for nombre, tabla in (("ipva_municipios", TABLA_IPVA_MUNICIPIOS),
                          ("ipva_distritos", TABLA_IPVA_DISTRITOS),
                          ("ipv_ccaa", TABLA_IPV_CCAA)):
        try:
            series = _carga(tabla)
            anios = {int(a) for datos in series.values() for a in datos.get("indice", {})}
            out[nombre] = {"tabla_ine": tabla, "series": len(series),
                           "ultimo_anio": max(anios) if anios else None}
        except Exception as e:
            out[nombre] = {"tabla_ine": tabla, "error": f"{type(e).__name__}: {e}"}
    return out
