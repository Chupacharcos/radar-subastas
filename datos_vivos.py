"""
Datos que cambian y no pueden vivir escritos en el código.

Un tipo de interés escrito a mano envejece en semanas y nadie se entera: la
herramienta sigue calculando cuotas con un dato viejo y las cifras dejan de ser
ciertas sin dar ningún error. Aquí se traen de su fuente oficial, se cachean en
disco y **se declara siempre la fecha del dato**, para que quien lo lea sepa de
cuándo es.

Fuentes:
  - Tipos de intervención del BCE: Banco de España, serie ti_1_1 (diaria).
  - Diferencial hipotecario: no hay fuente oficial abierta con el diferencial
    medio del mercado, así que es un supuesto declarado, no un dato.

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
MAX_EDAD_CACHE = timedelta(days=7)
TIMEOUT = 25.0

# El Euríbor 12M cotiza habitualmente algo por encima del tipo de intervención
# del BCE, y el banco añade su diferencial. La suma es un SUPUESTO razonable de
# tipo hipotecario, no una cotización: quien tenga una oferta real debe meterla.
DIFERENCIAL_HIPOTECARIO_TIPICO = 0.008   # 0,8 pp

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


def _descarga_bde() -> tuple[float, str] | None:
    """(tipo en %, fecha) del último dato publicado por el Banco de España."""
    try:
        r = httpx.get(BDE_CSV, timeout=TIMEOUT)
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
            valor = float(fila[COL_OPERACIONES_PRINCIPALES].replace(",", "."))
        except (ValueError, IndexError):
            continue     # '_' marca dato no disponible ese día
        return valor, fecha
    return None


def _lee_cache() -> dict | None:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return None


def _escribe_cache(datos: dict) -> None:
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
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


def tipo_hipotecario_estimado(forzar_descarga: bool = False) -> dict:
    """Tipo orientativo para una hipoteca: referencia del BCE + diferencial."""
    base = tipo_bce(forzar_descarga)
    total = round(base.valor + DIFERENCIAL_HIPOTECARIO_TIPICO, 5)
    return {
        "tipo_estimado": total,
        "referencia_bce": base.valor,
        "diferencial_supuesto": DIFERENCIAL_HIPOTECARIO_TIPICO,
        "fecha_dato": base.fecha_dato,
        "fuente": base.fuente,
        "aviso": (base.aviso + " " if base.aviso else "") +
                 "El diferencial es un supuesto: no existe fuente oficial abierta del "
                 "diferencial medio del mercado. Si tienes una oferta concreta, úsala.",
        "es_estimacion": True,
    }
