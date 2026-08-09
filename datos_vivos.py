"""
Datos que cambian y no pueden vivir escritos en el código.

Un tipo de interés escrito a mano envejece en semanas y nadie se entera: la
herramienta sigue calculando cuotas con un dato viejo y las cifras dejan de ser
ciertas sin dar ningún error. Aquí se traen de su fuente oficial, se cachean en
disco y **se declara siempre la fecha del dato**, para que quien lo lea sepa de
cuándo es.

Fuentes:
  - **Euríbor a 12 meses**: Banco de España, serie ti_1_7.7 (diaria). Es el
    índice al que se revisan las hipotecas españolas, y es el que se usa. Antes
    se usaba el tipo de intervención del BCE, que mide otra cosa —lo que cuesta
    el dinero al banco— y va casi un punto por debajo.
  - Tipos de intervención del BCE: serie ti_1_1, de reserva si el Euríbor falla.
  - Diferencial del banco: no hay fuente oficial abierta del diferencial medio
    del mercado. Es lo único de toda la cadena que no se mide, así que se expone
    como parámetro con valor por defecto en lugar de esconderlo en una constante.

Si la descarga falla, se usa el último valor cacheado y se dice que es viejo.
Nunca se devuelve un número sin decir de cuándo es.
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

CACHE = Path(__file__).parent / "data" / "tipos.json"
BDE_CSV = "https://www.bde.es/webbe/es/estadisticas/compartido/datos/csv/ti_1_1.csv"
COL_OPERACIONES_PRINCIPALES = 3   # facilidad de crédito; ver descripción del CSV

# El Euríbor a 12 meses es la referencia REAL de las hipotecas españolas, no el
# tipo de intervención del BCE. El Banco de España lo publica a diario en la
# tabla ti_1_7, columna 7 (serie D_DNBAF172, «Euríbor. A 12 meses»).
EURIBOR_CSV = "https://www.bde.es/webbe/es/estadisticas/compartido/datos/csv/ti_1_7.csv"
COL_EURIBOR_12M = 7
CACHE_EURIBOR = Path(__file__).parent / "data" / "euribor.json"
MAX_EDAD_CACHE = timedelta(days=7)
TIMEOUT = 25.0

# Diferencial que el banco suma al Euríbor. No existe fuente oficial abierta del
# diferencial medio del mercado, así que es lo ÚNICO que no se mide en toda la
# cadena del tipo. Por eso es un parámetro con valor por defecto y no una
# constante escondida: quien tenga una oferta concreta pasa el suyo.
DIFERENCIAL_POR_DEFECTO = 0.008   # 0,8 pp

MESES = {"ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
         "JUL": 7, "AGO": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DIC": 12}


@dataclass
class TipoOficial:
    valor: float                 # en tanto por uno
    fecha_dato: str              # fecha a la que corresponde el tipo
    obtenido: str                # cuándo se descargó
    fuente: str
    es_estimacion: bool
    aviso: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _parsea_fecha(texto: str) -> str | None:
    """'06 AGO 2026' → '2026-08-06'."""
    m = re.match(r"(\d{1,2})\s*([A-ZÑ]{3})\s*(\d{4})", texto.strip().upper())
    if not m:
        return None
    dia, mes, anio = m.groups()
    if mes not in MESES:
        return None
    return f"{anio}-{MESES[mes]:02d}-{int(dia):02d}"


def _descarga_bde(url: str = BDE_CSV,
                  columna: int = COL_OPERACIONES_PRINCIPALES) -> tuple[float, str] | None:
    """(tipo en %, fecha) del último dato publicado por el Banco de España."""
    try:
        r = httpx.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        filas = list(csv.reader(io.StringIO(r.content.decode("latin-1"))))
    except Exception:
        return None

    for fila in reversed(filas):
        if not fila or not fila[0][:1].isdigit():
            continue
        fecha = _parsea_fecha(fila[0])
        if not fecha:
            continue
        try:
            valor = float(fila[columna].replace(",", "."))
        except (ValueError, IndexError):
            continue     # '_' marca dato no disponible ese día
        return valor, fecha
    return None


def _lee_cache(fichero: Path = CACHE) -> dict | None:
    try:
        return json.loads(fichero.read_text(encoding="utf-8"))
    except Exception:
        return None


def _escribe_cache(datos, fichero: Path = CACHE) -> None:
    if hasattr(datos, "to_dict"):
        datos = datos.to_dict()
    try:
        fichero.parent.mkdir(parents=True, exist_ok=True)
        fichero.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass   # la caché es una comodidad, no puede tumbar una consulta


def tipo_bce(forzar_descarga: bool = False) -> TipoOficial:
    """Último tipo de intervención del BCE publicado por el Banco de España."""
    ahora = datetime.now(timezone.utc)
    cache = _lee_cache()

    if cache and not forzar_descarga:
        try:
            obtenido = datetime.fromisoformat(cache["obtenido"])
            if ahora - obtenido < MAX_EDAD_CACHE:
                return TipoOficial(**cache)
        except Exception:
            pass

    descarga = _descarga_bde()
    if descarga:
        valor_pct, fecha = descarga
        tipo = TipoOficial(
            valor=round(valor_pct / 100, 5),
            fecha_dato=fecha,
            obtenido=ahora.isoformat(timespec="seconds"),
            fuente="Banco de España, serie ti_1_1 (tipos de intervención del BCE)",
            es_estimacion=False,
        )
        _escribe_cache(tipo.to_dict())
        return tipo

    if cache:
        viejo = TipoOficial(**cache)
        viejo.aviso = (f"No se pudo actualizar desde el Banco de España; "
                       f"se usa el último dato descargado el {cache['obtenido'][:10]}.")
        return viejo

    # Sin red y sin caché: se devuelve algo utilizable, pero marcado.
    return TipoOficial(
        valor=0.024, fecha_dato="desconocida",
        obtenido=ahora.isoformat(timespec="seconds"),
        fuente="valor de reserva (no se pudo consultar al Banco de España)",
        es_estimacion=True,
        aviso="Sin conexión con el Banco de España: este tipo es un valor de "
              "reserva y puede estar desfasado. Introduce el de tu oferta.",
    )


def euribor_12m(forzar_descarga: bool = False) -> TipoOficial:
    """Euríbor a 12 meses, la referencia real de las hipotecas españolas.

    Antes se usaba el tipo de intervención del BCE, que es otra cosa: mide el
    precio al que el banco central presta a la banca, no el índice al que se
    revisan las hipotecas. En agosto de 2026 hay casi un punto de diferencia
    entre los dos.
    """
    ahora = datetime.now(timezone.utc)
    cache = _lee_cache(CACHE_EURIBOR)
    if cache and not forzar_descarga:
        try:
            if ahora - datetime.fromisoformat(cache["obtenido"]) < MAX_EDAD_CACHE:
                return TipoOficial(**cache)
        except Exception:
            pass

    descarga = _descarga_bde(EURIBOR_CSV, COL_EURIBOR_12M)
    if not descarga:
        # Sin Euríbor no se inventa uno: se cae al tipo del BCE, que es peor
        # referencia pero es un dato, y se dice en el aviso.
        base = tipo_bce(forzar_descarga)
        return TipoOficial(
            valor=base.valor, fecha_dato=base.fecha_dato, obtenido=base.obtenido,
            fuente=base.fuente, es_estimacion=True,
            aviso="No se pudo descargar el Euríbor a 12 meses; se usa el tipo de "
                  "intervención del BCE, que suele quedar por debajo.",
        )

    valor_pct, fecha = descarga
    tipo = TipoOficial(
        valor=round(valor_pct / 100, 5), fecha_dato=fecha,
        obtenido=ahora.isoformat(timespec="seconds"),
        fuente="Banco de España, serie ti_1_7.7 (Euríbor a 12 meses)",
        es_estimacion=False,
    )
    _escribe_cache(tipo, CACHE_EURIBOR)
    return tipo


def tipo_hipotecario_estimado(diferencial: float | None = None,
                              forzar_descarga: bool = False) -> dict:
    """Tipo de una hipoteca: Euríbor 12M real más el diferencial del banco."""
    dif = DIFERENCIAL_POR_DEFECTO if diferencial is None else float(diferencial)
    base = euribor_12m(forzar_descarga)
    return {
        "tipo_estimado": round(base.valor + dif, 5),
        "euribor_12m": base.valor,
        "diferencial": dif,
        "diferencial_es_por_defecto": diferencial is None,
        "fecha_dato": base.fecha_dato,
        "fuente": base.fuente,
        "aviso": (base.aviso + " " if base.aviso else "") +
                 f"El Euríbor es el dato real del {base.fecha_dato}. El diferencial "
                 f"({dif*100:.2f} pp) es lo único que no se mide: no hay fuente oficial "
                 "abierta del diferencial medio del mercado. Si tienes una oferta "
                 "concreta, pásala en el parámetro `diferencial`.",
        "es_estimacion": base.es_estimacion,
    }
