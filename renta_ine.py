"""
Renta de los hogares por municipio y sección censal (INE, Atlas de renta).

Es el dato que convierte «el alquiler parece caro» en una cifra: si pides 1.200 €
en un barrio donde la renta media del hogar son 28.000 € al año, estás pidiendo
el 51 % de lo que entra en esa casa. Ahí no hay inquilino solvente, hay impagos y
rotación. Predice el comportamiento del alquiler mejor que ninguna otra variable
del entorno.

El Atlas del INE llega a **sección censal**, que es el grano al que de verdad
cambia un barrio: dos calles separadas pueden tener 15.000 € de diferencia.

Sobre el acceso: la API JSON del INE rechaza estas tablas por volumen
("No puede mostrarse por restricciones de volumen"), así que se usa la descarga
CSV oficial, que sí funciona. Cada provincia es una tabla distinta; el mapa
`TABLA_POR_PROVINCIA` se construyó sondeando las 54 tablas de la operación 353.

Los ficheros pesan decenas de MB, de modo que se descargan bajo demanda, se
destilan a lo mínimo útil y se cachea el resultado.

Del grano fino se guardan dos cosas:

  - la renta de cada **distrito**, que es la que de verdad describe el sitio: en
    Madrid capital va de 79.274 € en Chamartín a 32.666 € en Puente de Vallecas,
    y la media del municipio —que es lo único que había antes— no distingue uno
    de otro;
  - un resumen de la dispersión entre **secciones censales** (cuántas hay, mínimo,
    mediana y máximo). Las secciones enteras no se guardan porque para usarlas
    haría falta saber en qué sección cae una dirección, y eso exige la
    cartografía del seccionado; el resumen, en cambio, ya avisa de cuánto esconde
    la media.
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from statistics import median
from pathlib import Path

import httpx

CACHE_DIR = Path(__file__).parent / "data" / "renta"
CSV_URL = "https://www.ine.es/jaxiT3/files/t/es/csv_bdsc/{tabla}.csv"
INDICADOR = "Renta neta media por hogar"
TIMEOUT = 180.0
MAX_BYTES = 200 * 1024 * 1024

# Versión del destilado. Al subirla, las cachés viejas se ignoran y se vuelven a
# generar: si no, un fichero anterior sin distritos se daría por bueno para
# siempre.
FORMATO = 2

# Código INE de provincia → tabla del Atlas de renta (operación 353).
# Sondeado el 2026-08-08 leyendo la cabecera de cada CSV.
TABLA_POR_PROVINCIA = {
    "01": 30824, "02": 30833, "03": 30842, "04": 30851, "05": 30860, "06": 30869,
    "07": 30878, "08": 30896, "09": 30905, "10": 30914, "11": 30923, "12": 30932,
    "13": 30941, "14": 30950, "15": 30959, "16": 30968, "17": 30977, "18": 30986,
    "19": 30995, "20": 31004, "21": 31013, "22": 31022, "23": 31031, "24": 31040,
    "25": 31049, "26": 31058, "27": 31067, "28": 31097, "29": 31106, "30": 31115,
    "31": 31124, "32": 31133, "33": 31142, "34": 31151, "35": 31160, "36": 31169,
    "37": 31178, "38": 31187, "39": 31196, "41": 31205, "42": 31214, "43": 31223,
    "44": 31232, "45": 31241, "46": 31250, "47": 31259, "48": 31268, "49": 31277,
    "50": 31286, "51": 31295, "52": 31304,
}


@dataclass
class Renta:
    municipio: str | None = None
    codigo_ine: str | None = None
    renta_hogar_anual: float | None = None
    renta_persona_anual: float | None = None
    anio: int | None = None
    distritos: list[dict] = field(default_factory=list)
    dispersion_secciones: dict | None = None
    fuente: str = "INE, Atlas de distribución de renta de los hogares"
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _normaliza(t: str) -> str:
    acentos = str.maketrans("áàäâéèëêíìïîóòöôúùüûñ", "aaaaeeeeiiiioooouuuun")
    return re.sub(r"[^a-z0-9 ]", " ", t.strip().lower().translate(acentos))


def _num(valor: str) -> float | None:
    """'28.415' → 28415.0 (el INE usa el punto como separador de miles)."""
    v = valor.strip().replace(".", "").replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return None


def _cache_path(cp: str) -> Path:
    return CACHE_DIR / f"{cp}.json"


def _acumula(reg: dict, anio: int, indicador: str, valor: float) -> None:
    """Guarda el valor si es del año más reciente visto para ese registro."""
    if anio < reg["anio"]:
        return
    if anio > reg["anio"]:
        reg.update({"anio": anio, "hogar": None, "persona": None})
    reg["hogar" if indicador == INDICADOR else "persona"] = valor


def _destila(contenido: str) -> dict:
    """CSV completo → {codigo_municipio: {nombre, hogar, persona, anio,
    distritos, secciones}}.

    El CSV trae las tres granularidades mezcladas en la misma tabla y se
    distinguen por qué columnas vienen rellenas: sólo municipio, municipio +
    distrito, o los tres. De las secciones sólo sobrevive el resumen
    estadístico: guardar las ~36.000 del país no serviría de nada sin la
    cartografía que dice en qué sección cae cada dirección, pero el resumen ya
    avisa de cuánto esconde la media del municipio.
    """
    out: dict[str, dict] = {}
    lector = csv.DictReader(io.StringIO(contenido), delimiter=";")
    # El nombre de la columna del indicador cambia entre provincias
    # ("Indicadores de renta media" en unas, "…media y mediana" en otras), así
    # que se localiza por prefijo en lugar de darlo por sentado.
    campos = lector.fieldnames or []
    col_muni = next((c for c in campos if c.strip().lstrip("\ufeff").startswith("Municipio")), "Municipios")
    col_ind = next((c for c in campos if c.strip().startswith("Indicadores")), None)
    if not col_ind:
        return out

    # Renta por hogar de cada sección, por año, para el resumen de dispersión.
    secciones: dict[str, dict[int, dict[str, float]]] = {}

    for fila in lector:
        muni = (fila.get(col_muni) or "").strip()
        if not muni:
            continue
        indicador = (fila.get(col_ind) or "").strip()
        if indicador not in (INDICADOR, "Renta neta media por persona"):
            continue
        valor = _num(fila.get("Total") or "")
        if valor is None:
            continue
        try:
            anio = int(fila.get("Periodo") or 0)
        except ValueError:
            continue

        codigo, _, nombre = muni.partition(" ")
        reg = out.setdefault(codigo, {"nombre": nombre.strip(), "anio": 0,
                                      "hogar": None, "persona": None,
                                      "distritos": {}})
        distrito = (fila.get("Distritos") or "").strip()
        seccion = (fila.get("Secciones") or "").strip()

        if seccion:
            if indicador == INDICADOR:
                secciones.setdefault(codigo, {}).setdefault(anio, {})[
                    seccion.partition(" ")[0]] = valor
        elif distrito:
            _acumula(reg["distritos"].setdefault(
                distrito.partition(" ")[0],
                {"anio": 0, "hogar": None, "persona": None}),
                anio, indicador, valor)
        else:
            _acumula(reg, anio, indicador, valor)

    # El INE censura por arriba: en la provincia de Madrid, 134 secciones de
    # municipios distintos declaran exactamente 104.774 €, y 82 de ellas están en
    # la capital. No es el máximo, es un techo. Se detecta como el valor más alto
    # que se repite en varias secciones de la provincia, y se marca para no
    # presentarlo nunca como si fuera un dato.
    todas: dict[int, list[float]] = {}
    for por_anio in secciones.values():
        for anio, valores in por_anio.items():
            todas.setdefault(anio, []).extend(valores.values())
    topes = {anio: max(v) for anio, v in todas.items() if v}
    es_tope = {anio: v.count(topes[anio]) >= 3 for anio, v in todas.items() if v}

    for codigo, por_anio in secciones.items():
        if codigo not in out or not por_anio:
            continue
        anio = max(por_anio)
        valores = sorted(por_anio[anio].values())
        if len(valores) < 2:
            continue
        topado = es_tope.get(anio) and valores[-1] == topes[anio]
        out[codigo]["secciones"] = {
            "anio": anio,
            "total": len(valores),
            "minimo": valores[0],
            "mediana": round(median(valores), 2),
            "maximo": valores[-1],
            "maximo_censurado": bool(topado),
            "secciones_en_el_tope": valores.count(topes[anio]) if topado else 0,
        }
    return out


def _carga_provincia(cp: str, forzar: bool = False) -> dict:
    """Datos destilados de una provincia, desde caché o descargando."""
    destino = _cache_path(cp)
    if destino.exists() and not forzar:
        try:
            guardado = json.loads(destino.read_text(encoding="utf-8"))
            if guardado.get("formato") == FORMATO:
                return guardado["municipios"]
        except Exception:
            pass

    tabla = TABLA_POR_PROVINCIA.get(cp)
    if not tabla:
        raise KeyError(f"No hay tabla del Atlas para la provincia {cp}")

    with httpx.stream("GET", CSV_URL.format(tabla=tabla), timeout=TIMEOUT,
                      follow_redirects=True) as r:
        r.raise_for_status()
        trozos, total = [], 0
        for trozo in r.iter_bytes():
            total += len(trozo)
            if total > MAX_BYTES:
                raise ValueError(f"El CSV de la provincia {cp} supera el límite previsto")
            trozos.append(trozo)
    contenido = b"".join(trozos).decode("utf-8-sig", "ignore")

    municipios = _destila(contenido)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps({
        "provincia": cp,
        "tabla_ine": tabla,
        "formato": FORMATO,
        "descargado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "municipios": municipios,
    }, ensure_ascii=False), encoding="utf-8")
    return municipios


def _a_renta(codigo: str, datos: dict) -> Renta:
    """Registro destilado → respuesta, con sus distritos ordenados de mayor a
    menor renta: así se ve de un vistazo la horquilla que esconde la media."""
    distritos = [
        {"codigo": cod,
         "renta_hogar_anual": d.get("hogar"),
         "renta_persona_anual": d.get("persona"),
         "anio": d.get("anio") or None}
        for cod, d in sorted((datos.get("distritos") or {}).items())
        if d.get("hogar") is not None
    ]
    distritos.sort(key=lambda d: -(d["renta_hogar_anual"] or 0))

    return Renta(
        municipio=datos["nombre"],
        codigo_ine=codigo,
        renta_hogar_anual=datos.get("hogar"),
        renta_persona_anual=datos.get("persona"),
        anio=datos.get("anio") or None,
        distritos=distritos,
        dispersion_secciones=datos.get("secciones"),
    )


def consultar(municipio: str, codigo_provincia: str,
              codigo_municipio: str | None = None) -> Renta:
    """Renta media del hogar en un municipio.

    `codigo_provincia` y `codigo_municipio` son los códigos INE que devuelve el
    Catastro. Si se pasa el del municipio se empareja por código, que es exacto:
    buscar por nombre confundía «Las Rozas de Madrid» con «Madrid», porque una
    cadena contiene a la otra.
    """
    cp = str(codigo_provincia).zfill(2)
    try:
        municipios = _carga_provincia(cp)
    except Exception as e:
        return Renta(municipio=municipio, error=f"No se pudo obtener el Atlas del INE: {e}")

    # 1) Por código INE: exacto y sin ambigüedad.
    if codigo_municipio:
        clave = cp + str(codigo_municipio).zfill(3)
        if clave in municipios:
            return _a_renta(clave, municipios[clave])

    # 2) Por nombre. El INE invierte el artículo («Rozas de Madrid, Las») y el
    #    Catastro no («LAS ROZAS DE MADRID»), así que se compara la forma
    #    reordenada y sólo se acepta coincidencia exacta: un "contiene" hacía
    #    que «Las Rozas de Madrid» encajara con «Madrid».
    def variantes(nombre: str) -> set[str]:
        n = _normaliza(nombre)
        formas = {n}
        if "," in nombre:
            cuerpo, _, articulo = nombre.partition(",")
            formas.add(_normaliza(f"{articulo.strip()} {cuerpo.strip()}"))
        return {re.sub(r"\s+", " ", f).strip() for f in formas}

    objetivo = re.sub(r"\s+", " ", _normaliza(municipio)).strip()
    mejor = None
    for codigo, datos in municipios.items():
        if objetivo in variantes(datos["nombre"]):
            mejor = (codigo, datos)
            break

    if not mejor:
        return Renta(municipio=municipio,
                     error=f"«{municipio}» no aparece en el Atlas de la provincia {cp}")

    return _a_renta(*mejor)


def renta_distrito(codigo_distrito: str) -> dict | None:
    """Renta de un distrito por su código de 7 dígitos (5 municipio + 2 distrito).

    Es el grano al que de verdad cambia un sitio: en Madrid capital la media del
    municipio no distingue Chamartín de Puente de Vallecas, y entre esos dos hay
    más de 46.000 € de diferencia por hogar.
    """
    codigo = str(codigo_distrito).strip()
    if len(codigo) != 7 or not codigo.isdigit():
        return None
    try:
        municipios = _carga_provincia(codigo[:2])
    except Exception:
        return None
    datos = (municipios.get(codigo[:5]) or {}).get("distritos", {}).get(codigo)
    if not datos:
        return None
    return {
        "codigo": codigo,
        "renta_hogar_anual": datos.get("hogar"),
        "renta_persona_anual": datos.get("persona"),
        "anio": datos.get("anio") or None,
        "fuente": Renta.fuente,
    }
