"""
Alquiler real en euros al mes, por municipio.

Este módulo cierra el agujero que arrastraba el proyecto desde el principio. Lo
que faltaba no era la evolución del alquiler —eso lo da el IPVA— sino el
**nivel**: cuánto se paga de verdad. Sin él, el alquiler se derivaba del precio
con una rentabilidad fija y la rentabilidad salía casi idéntica en todas partes,
que es tanto como no decir nada.

La conclusión anterior era que ese dato estaba bloqueado, porque la consulta de
SERPAVI está detrás de un reCAPTCHA. Y lo está. Pero el **agregado municipal**
del que sale SERPAVI sí se publica en abierto, en el CDN de datos del
Ministerio de Vivienda:

    cdn.mivau.gob.es/portal-web-mivau/Datos_MIVAU/CSV/VDP001_01.csv

Trae, por municipio, año y tipo de vivienda (colectiva o unifamiliar): la
**mediana**, el **percentil 25** y el **percentil 75** del precio del alquiler,
la superficie mediana y el recuento de viviendas. Son exactamente las variables
que describe la metodología oficial de SERPAVI (percentiles sobre los
arrendamientos de vivienda habitual declarados a la Agencia Tributaria en los
modelos 100 y 109), y el fichero es coherente con ella. 3.346 municipios con
dato de precio en 2024.

Dos advertencias que conviene no perder de vista:

  - **Ese fichero no aparece en el catálogo documentado del ministerio**
    (datos.gob.es publica del VDP002 al VDP007, pero no el VDP001). Se localizó
    sondeando el CDN. Puede cambiar o desaparecer sin aviso, así que `vigencia.py`
    lo vigila.
  - Es el alquiler del **parque arrendado**, no el de los contratos que se firman
    hoy. Los contratos nuevos van por encima.

Para eso segundo están los **registros de fianzas**, que miden los contratos que
se firman hoy porque la fianza se deposita al firmar. Dos comunidades los
publican en abierto:

  - **Cataluña**, ya agregado: alquiler medio por municipio y trimestre, con el
    número de contratos, hasta el trimestre en curso.
  - **Comunitat Valenciana**, depósito a depósito: la mediana por municipio se
    calcula aquí. Cada importe es una mensualidad de renta porque el artículo
    36.1 de la LAU obliga a depositar «cantidad equivalente a una mensualidad»
    en el arrendamiento de viviendas.

Donde llegan, permiten ver la distancia entre lo que paga quien ya vive de
alquiler y lo que pagaría quien entra hoy. Esa distancia no es la misma en las
dos: +26 % en Barcelona y +62 % en Valencia. No es un error de lectura, es que
Cataluña tiene tope legal de renta en zona tensionada desde 2024 y la Comunitat
Valenciana apenas, así que allí los contratos nuevos sí se van al mercado.
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, asdict, field
from statistics import median
from datetime import datetime, timezone
from pathlib import Path

import httpx

CACHE_DIR = Path(__file__).parent / "data" / "alquiler_real"
MIVAU_URL = "https://cdn.mivau.gob.es/portal-web-mivau/Datos_MIVAU/CSV/VDP001_01.csv"
FIANZAS_URL = "https://analisi.transparenciacatalunya.cat/resource/qww9-bvhh.json"
# La Generalitat Valenciana publica los depósitos UNO A UNO, no agregados. Por el
# artículo 36.1 de la LAU la fianza de un arrendamiento de vivienda es «cantidad
# equivalente a una mensualidad de renta», así que cada importe es un alquiler y
# la mediana por municipio es un alquiler mediano de contratos nuevos.
GVA_BUSQUEDA = ("https://dadesobertes.gva.es/api/3/action/package_search"
                "?q=fianzas+alquiler&rows=1")
PROVINCIAS_VALENCIANAS = ("03", "12", "46")
MIN_FIANZAS_MUNICIPIO = 8   # por debajo, la mediana es ruido
TIMEOUT = 180.0
MAX_BYTES = 120 * 1024 * 1024

# Cuántos años del fichero del ministerio se conservan al destilar. Con dos basta
# para dar el dato y decir cómo se movió; guardar los cinco multiplicaría la
# caché sin que nadie los mire.
ANIOS_QUE_SE_GUARDAN = 2

FUENTE_MIVAU = ("Ministerio de Vivienda y Agenda Urbana, precio del alquiler por "
                "municipio (arrendamientos declarados a la Agencia Tributaria)")
FUENTE_FIANZAS = ("Generalitat de Catalunya, registro de fianzas de alquiler "
                  "(contratos nuevos depositados)")
FUENTE_GVA = ("Generalitat Valenciana, fianzas de alquiler depositadas; el importe "
              "es una mensualidad de renta por el artículo 36.1 de la LAU")


@dataclass
class AlquilerReal:
    """Lo que se paga de alquiler en un municipio. Nivel, no índice."""
    codigo_ine: str = ""
    municipio: str = ""
    anio: int | None = None
    tipo_vivienda: str = "colectiva"
    mediana_mensual: float | None = None
    p25_mensual: float | None = None
    p75_mensual: float | None = None
    superficie_mediana_m2: float | None = None
    euros_m2_mes: float | None = None
    viviendas: int | None = None
    contratos_nuevos: dict | None = None
    fuente: str = FUENTE_MIVAU
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


def _descargar(url: str) -> str:
    with httpx.stream("GET", url, timeout=TIMEOUT, follow_redirects=True) as r:
        r.raise_for_status()
        trozos, total = [], 0
        for trozo in r.iter_bytes():
            total += len(trozo)
            if total > MAX_BYTES:
                raise ValueError(f"El fichero {url} supera el límite previsto")
            trozos.append(trozo)
    return b"".join(trozos).decode("utf-8-sig", "ignore")


def _destila(contenido: str) -> dict:
    """CSV del ministerio → {codigo_municipio: {año: {tipo: {…}}}}.

    El fichero viene en formato largo: cada fila es una combinación de elemento
    (PRECIO, SUPERFICIE, VIVIENDA) y medida (MEDIANA, PERCENT25, PERCENT75,
    RECUENTO), así que hay que recomponer los registros.
    """
    claves = {
        ("PRECIO", "MEDIANA"): "mediana",
        ("PRECIO", "PERCENT25"): "p25",
        ("PRECIO", "PERCENT75"): "p75",
        ("SUPERFICIE", "MEDIANA"): "superficie",
        ("VIVIENDA", "RECUENTO"): "viviendas",
    }
    crudo: dict[str, dict] = {}
    lector = csv.DictReader(io.StringIO(contenido), delimiter=";")
    for fila in lector:
        clave = claves.get(((fila.get("ELEMENTO") or "").strip(),
                            (fila.get("TIPO_MEDIDA") or "").strip()))
        if not clave:
            continue
        valor = _num(fila.get("VALOR") or "")
        if valor is None:
            continue
        try:
            anio = int((fila.get("AÑO") or "").strip())
        except ValueError:
            continue
        municipio = (fila.get("COD_POSTAL") or "").strip().zfill(5)
        tipo = (fila.get("TIPO_VIVIENDA") or "").strip().lower()
        if not municipio or not tipo:
            continue
        reg = crudo.setdefault(municipio, {"nombre": (fila.get("NOMBRE_MUNICIPIO") or "").strip(),
                                           "anios": {}})
        reg["anios"].setdefault(str(anio), {}).setdefault(tipo, {})[clave] = valor

    # Sólo los años más recientes, y sólo los registros que traen precio: un
    # municipio con recuento pero sin mediana no sirve para nada aquí.
    anios = sorted({a for m in crudo.values() for a in m["anios"]},
                   reverse=True)[:ANIOS_QUE_SE_GUARDAN]
    out: dict[str, dict] = {}
    for municipio, reg in crudo.items():
        guardado = {a: {t: v for t, v in tipos.items() if v.get("mediana")}
                    for a, tipos in reg["anios"].items() if a in anios}
        guardado = {a: t for a, t in guardado.items() if t}
        if guardado:
            out[municipio] = {"nombre": reg["nombre"], "anios": guardado}
    return out


_MUNICIPIOS_MEMORIA: dict | None = None


def _carga(forzar: bool = False) -> dict:
    """Municipios destilados, memoizados en memoria.

    Sin la memoria intermedia esto releía y reparseaba varios MB de JSON en cada
    consulta: recorrer los 3.388 municipios para el listado nacional tardaba
    minutos en lugar de segundos.
    """
    global _MUNICIPIOS_MEMORIA
    if _MUNICIPIOS_MEMORIA is not None and not forzar:
        return _MUNICIPIOS_MEMORIA

    destino = CACHE_DIR / "mivau_municipios.json"
    if destino.exists() and not forzar:
        try:
            _MUNICIPIOS_MEMORIA = json.loads(destino.read_text(encoding="utf-8"))["municipios"]
            return _MUNICIPIOS_MEMORIA
        except Exception:
            pass

    municipios = _destila(_descargar(MIVAU_URL))
    if not municipios:
        raise ValueError("El fichero del ministerio no trajo ningún municipio utilizable")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps({
        "origen": MIVAU_URL,
        "descargado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "municipios": municipios,
    }, ensure_ascii=False), encoding="utf-8")
    _MUNICIPIOS_MEMORIA = municipios
    return municipios


PROVINCIAS_CATALANAS = ("08", "17", "25", "43")
_FIANZAS_MEMORIA: dict | None = None


def _fianzas_catalunya(forzar: bool = False) -> dict:
    """Todas las fianzas catalanas del año más reciente, en una sola consulta.

    Antes se preguntaba municipio a municipio, lo que suponía cuarenta peticiones
    para pintar una tabla. Se trae el año entero de golpe y se cachea en disco.
    """
    global _FIANZAS_MEMORIA
    if _FIANZAS_MEMORIA is not None and not forzar:
        return _FIANZAS_MEMORIA

    destino = CACHE_DIR / "fianzas_catalunya.json"
    if destino.exists() and not forzar:
        try:
            guardado = json.loads(destino.read_text(encoding="utf-8"))
            # Se rehace cuando cambia el trimestre, que es cuando hay dato nuevo.
            if guardado.get("trimestre_descarga") == _trimestre_actual():
                _FIANZAS_MEMORIA = guardado["municipios"]
                return _FIANZAS_MEMORIA
        except Exception:
            pass

    try:
        anios = httpx.get(FIANZAS_URL, params={
            "$select": "max(any) as ultimo", "ambit_territorial": "Municipi",
        }, timeout=30.0).json()
        ultimo = anios[0]["ultimo"]
        filas = httpx.get(FIANZAS_URL, params={
            "any": ultimo, "ambit_territorial": "Municipi", "$limit": 20000,
        }, timeout=60.0).json()
    except Exception:
        return {}

    # Del año más reciente se toma, por municipio, el periodo con más fianzas: con
    # pocos contratos la media se mueve por ruido.
    mejor: dict[str, dict] = {}
    for f in filas:
        codigo, renda = (f.get("codi_territorial") or "").zfill(5), f.get("renda")
        if not codigo or not renda:
            continue
        n = int(f.get("habitatges") or 0)
        if n <= int(mejor.get(codigo, {}).get("contratos", -1)):
            continue
        mejor[codigo] = {
            "importe_mensual": round(float(renda), 2), "estadistico": "media",
            "contratos": n, "anio": int(f.get("any") or 0),
            "periodo": f.get("periode"), "fuente": FUENTE_FIANZAS,
        }

    if mejor:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps({
            "origen": FIANZAS_URL,
            "trimestre_descarga": _trimestre_actual(),
            "descargado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "municipios": mejor,
        }, ensure_ascii=False), encoding="utf-8")
    _FIANZAS_MEMORIA = mejor
    return mejor


def _trimestre_actual() -> str:
    hoy = datetime.now(timezone.utc)
    return f"{hoy.year}T{(hoy.month - 1) // 3 + 1}"


_GVA_MEMORIA: dict | None = None


def _fianzas_valencianas(forzar: bool = False) -> dict:
    """Mediana de las fianzas depositadas por municipio en la Comunitat Valenciana.

    A diferencia de Cataluña, aquí el portal publica los depósitos uno a uno, así
    que la mediana se calcula aquí. Se usa mediana y no media porque un puñado de
    alquileres de lujo desplazan la media de un municipio pequeño; y se descartan
    los municipios con menos de ocho depósitos, donde el dato sería anecdótico.
    """
    global _GVA_MEMORIA
    if _GVA_MEMORIA is not None and not forzar:
        return _GVA_MEMORIA

    destino = CACHE_DIR / "fianzas_valencia.json"
    if destino.exists() and not forzar:
        try:
            guardado = json.loads(destino.read_text(encoding="utf-8"))
            if guardado.get("trimestre_descarga") == _trimestre_actual():
                _GVA_MEMORIA = guardado["municipios"]
                return _GVA_MEMORIA
        except Exception:
            pass

    try:
        catalogo = httpx.get(GVA_BUSQUEDA, timeout=60.0).json()
        recursos = catalogo["result"]["results"][0]["resources"]
        url = next(r["url"] for r in recursos if r.get("format") == "CSV")
        anio = int(catalogo["result"]["results"][0]["title"].strip()[-4:])
        contenido = _descargar(url)
    except Exception:
        return {}

    importes: dict[str, list[float]] = {}
    for fila in csv.DictReader(io.StringIO(contenido), delimiter=";"):
        importe = _num(fila.get("importe_fianza") or "")
        if not importe or importe <= 0:
            continue
        codigo = ((fila.get("cod_provincia") or "").strip().zfill(2)
                  + (fila.get("cod_municipio") or "").strip().zfill(3))
        if len(codigo) == 5:
            importes.setdefault(codigo, []).append(importe)

    out = {
        codigo: {
            "importe_mensual": round(median(v), 2),
            "estadistico": "mediana",
            "contratos": len(v),
            "anio": anio,
            "periodo": f"año {anio}",
            "fuente": FUENTE_GVA,
        }
        for codigo, v in importes.items() if len(v) >= MIN_FIANZAS_MUNICIPIO
    }

    if out:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps({
            "origen": url,
            "trimestre_descarga": _trimestre_actual(),
            "descargado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "municipios": out,
        }, ensure_ascii=False), encoding="utf-8")
    _GVA_MEMORIA = out
    return out


def _contratos_nuevos(codigo_ine: str) -> dict | None:
    """Alquiler de los contratos nuevos, donde su comunidad publica las fianzas.

    Las fianzas se depositan al firmar, así que esto mide el mercado de hoy y no
    el parque ya alquilado. Lo publican Cataluña —ya agregado— y la Comunitat
    Valenciana —depósito a depósito—. En el resto de España no hay equivalente.
    """
    if codigo_ine.startswith(PROVINCIAS_CATALANAS):
        return _fianzas_catalunya().get(codigo_ine)
    if codigo_ine.startswith(PROVINCIAS_VALENCIANAS):
        return _fianzas_valencianas().get(codigo_ine)
    return None


def alquiler_municipio(codigo_ine: str, tipo_vivienda: str = "colectiva") -> AlquilerReal:
    """Alquiler real de un municipio: mediana y horquilla, en euros al mes.

    `codigo_ine` es el código de 5 dígitos (provincia + municipio) que devuelve el
    Catastro. `tipo_vivienda` distingue piso (`colectiva`) de casa
    (`unifamiliar`), porque mezclarlos da una mediana que no describe a ninguno.
    """
    codigo = str(codigo_ine).strip().zfill(5)
    tipo = tipo_vivienda.strip().lower()
    try:
        municipios = _carga()
    except Exception as e:
        return AlquilerReal(codigo_ine=codigo,
                            error=f"No se pudo obtener el fichero del ministerio: {e}")

    registro = municipios.get(codigo)
    if not registro:
        return AlquilerReal(
            codigo_ine=codigo,
            error="El ministerio no publica precio de alquiler de este municipio. "
                  "Los municipios pequeños se omiten porque con pocos contratos "
                  "declarados la mediana dejaría de ser anónima.")

    por_anio = registro["anios"]
    anio = max(por_anio)
    datos = por_anio[anio].get(tipo)
    avisos: list[str] = []
    if not datos:
        # Mejor el otro tipo declarándolo que ningún dato.
        alternativo = next(iter(por_anio[anio]), None)
        if not alternativo:
            return AlquilerReal(codigo_ine=codigo, anio=int(anio),
                                error="Sin dato de precio para ese año")
        datos, tipo = por_anio[anio][alternativo], alternativo
        avisos.append(f"No hay dato de vivienda {tipo_vivienda}; se usa {alternativo}.")

    superficie = datos.get("superficie")
    mediana = datos.get("mediana")
    resultado = AlquilerReal(
        codigo_ine=codigo,
        municipio=registro["nombre"],
        anio=int(anio),
        tipo_vivienda=tipo,
        mediana_mensual=mediana,
        p25_mensual=datos.get("p25"),
        p75_mensual=datos.get("p75"),
        superficie_mediana_m2=superficie,
        euros_m2_mes=round(mediana / superficie, 2) if (mediana and superficie) else None,
        viviendas=int(datos["viviendas"]) if datos.get("viviendas") else None,
        contratos_nuevos=_contratos_nuevos(codigo),
        avisos=avisos,
    )

    resultado.avisos.append(
        f"Mediana del parque ya alquilado en {anio}: la mitad de las viviendas de "
        f"este municipio se alquilan por debajo de esa cifra y la mitad por encima. "
        f"El recorrido entre el 25 % más barato y el 25 % más caro va de "
        f"{datos.get('p25')} € a {datos.get('p75')} €."
    )
    nuevos = resultado.contratos_nuevos
    if nuevos and mediana:
        salto = (nuevos["importe_mensual"] / mediana - 1) * 100
        resultado.avisos.append(
            f"Los contratos firmados en {nuevos['periodo']} van a "
            f"{nuevos['importe_mensual']:.0f} € de {nuevos['estadistico']} sobre "
            f"{nuevos['contratos']} fianzas depositadas, un {salto:+.0f} % respecto al "
            "parque ya alquilado. Quien compra hoy para alquilar cobra lo de los "
            "contratos nuevos, no la mediana del parque."
        )
    return resultado


def alquiler_estimado_de(codigo_ine: str, superficie_m2: float,
                         tipo_vivienda: str = "colectiva") -> tuple[float | None, dict]:
    """Alquiler mensual esperable de una vivienda concreta, con su procedencia.

    Escala el €/m² real del municipio a la superficie del inmueble. Es una
    proporción sobre un dato medido, no una estimación sobre un supuesto: la
    diferencia con lo que había antes es que el número de partida existe.
    """
    real = alquiler_municipio(codigo_ine, tipo_vivienda)
    if real.error or not real.euros_m2_mes or not superficie_m2:
        return None, {"disponible": False, "motivo": real.error or "sin superficie"}

    # Si hay contratos nuevos, mandan: es lo que cobraría quien compre ahora.
    base_m2, base = real.euros_m2_mes, "parque alquilado"
    nuevos = real.contratos_nuevos
    if nuevos and real.mediana_mensual:
        base_m2 = real.euros_m2_mes * (nuevos["importe_mensual"] / real.mediana_mensual)
        base = f"contratos nuevos de {nuevos['anio']}"

    aviso = ("El €/m² es la mediana del municipio entero aplicada a la superficie de "
             "este inmueble. No distingue calle, estado ni planta.")
    # El €/m² se midió sobre viviendas del tamaño mediano del municipio. Estirarlo
    # a un inmueble mucho mayor lo infla: el alquiler no crece proporcionalmente al
    # metro, y un chalé de 400 m² no se alquila por cinco veces lo que un piso de 80.
    desproporcion = (real.superficie_mediana_m2
                     and not 0.5 <= superficie_m2 / real.superficie_mediana_m2 <= 2)
    if desproporcion:
        aviso += (f" Además, este inmueble tiene {superficie_m2:.0f} m² frente a los "
                  f"{real.superficie_mediana_m2:.0f} m² de la vivienda mediana del "
                  "municipio: a esa distancia el €/m² deja de ser representativo, "
                  "porque el alquiler no sube en proporción al tamaño. Toma la cifra "
                  "como techo, no como previsión.")

    return round(base_m2 * superficie_m2, 0), {
        "disponible": True,
        "ambito": "municipio",
        "euros_m2_mes": round(base_m2, 2),
        "base": base,
        "anio": real.anio,
        "municipio_superficie_mediana_m2": real.superficie_mediana_m2,
        "superficie_fuera_de_rango": bool(desproporcion),
        "horquilla_municipio": {"p25": real.p25_mensual, "mediana": real.mediana_mensual,
                                "p75": real.p75_mensual},
        "fuente": real.fuente,
        "aviso": aviso,
    }


def municipios_de_provincia(codigo_provincia: str) -> list[dict]:
    """Municipios de una provincia con alquiler publicado, con su dato ya resuelto.

    Es la base de la comparación de zonas: son los municipios sobre los que se
    puede decir algo medido en lugar de algo supuesto.
    """
    cp = str(codigo_provincia).strip().zfill(2)
    try:
        municipios = _carga()
    except Exception:
        return []

    out = []
    for codigo, registro in municipios.items():
        if not codigo.startswith(cp):
            continue
        anio = max(registro["anios"])
        datos = registro["anios"][anio].get("colectiva") or next(
            iter(registro["anios"][anio].values()), None)
        if not datos or not datos.get("mediana") or not datos.get("superficie"):
            continue
        out.append({
            "codigo_ine": codigo,
            "nombre": registro["nombre"],
            "anio": int(anio),
            "mediana_mensual": datos["mediana"],
            "p25_mensual": datos.get("p25"),
            "p75_mensual": datos.get("p75"),
            "superficie_mediana_m2": datos["superficie"],
            "euros_m2_mes": round(datos["mediana"] / datos["superficie"], 2),
            "viviendas": int(datos["viviendas"]) if datos.get("viviendas") else None,
        })
    out.sort(key=lambda m: -(m["viviendas"] or 0))
    return out


def mediana_provincial(codigo_provincia: str) -> dict | None:
    """€/m² al mes mediano de los municipios publicados de una provincia.

    Es el recurso para los municipios que el ministerio no desglosa —más de la
    mitad de los de España, todos pequeños—. No es un supuesto: es la mediana de
    municipios medidos de esa misma provincia, y se declara como tal, con cuántos
    municipios la componen y entre qué valores se mueven.

    Se usa la mediana sin ponderar a propósito. Ponderar por número de viviendas
    arrastraría el resultado hacia la capital, y quien consulta un municipio sin
    dato publicado está casi siempre en uno pequeño, que se parece más a los otros
    pequeños que a la capital.
    """
    municipios = municipios_de_provincia(codigo_provincia)
    valores = sorted(m["euros_m2_mes"] for m in municipios if m.get("euros_m2_mes"))
    if len(valores) < 3:
        return None
    return {
        "euros_m2_mes": round(median(valores), 2),
        "municipios": len(valores),
        "minimo": valores[0],
        "maximo": valores[-1],
        "anio": max(m["anio"] for m in municipios),
        "fuente": FUENTE_MIVAU,
    }


def frescura() -> dict:
    """Último año publicado y cobertura, para el control de vigencia."""
    try:
        municipios = _carga()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}", "origen": MIVAU_URL}
    anios = {int(a) for m in municipios.values() for a in m["anios"]}
    return {
        "origen": MIVAU_URL,
        "municipios": len(municipios),
        "ultimo_anio": max(anios) if anios else None,
    }
