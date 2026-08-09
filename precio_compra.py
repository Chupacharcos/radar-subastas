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

**Y por municipio.** El fichero anterior sólo llega a provincia, lo que aplanaba
toda comparación: los 163 municipios de Madrid compartían precio. El ministerio
sí publica el detalle municipal, pero no en su portal de datos abiertos ni en el
CDN: está en el BoletínOnline, en un Excel de formato heredado que sigue vivo y
se actualiza cada trimestre.

    apps.fomento.gob.es/boletinonline2/sedal/35103500.XLS

Una hoja por trimestre desde 2005, y en cada una el €/m² tasado de los municipios
de más de 25.000 habitantes, separando vivienda de hasta cinco años de antigüedad
y de más. Unos 300 municipios con dato en el último trimestre, que son los
mercados donde de verdad hay subastas.

Ese Excel no trae códigos INE, sólo nombres, y los escribe a su manera («Ejido
(El)», «Santa Cruz deTenerife» sin espacio). El emparejamiento con el código INE
se hace normalizando el nombre —sin acentos, sin artículo, sin signos— contra el
listado del propio ministerio, que sí lleva código: 95 % encaja directo, el resto
se resuelve con una tabla de equivalencias explícita y con la provincia del
bloque. Cada valor emparejado se contrasta además con el de su provincia, y si se
sale de una banda razonable se descarta en lugar de arriesgar un cruce erróneo.

Sobre lo que esto NO es: no es una tasación de un inmueble concreto. No sabe si
el piso está reformado, en qué planta va ni si da a un patio. Multiplicar la
media del municipio por la superficie del Catastro da un **orden de magnitud**, y
así se declara. Un modelo por características exigiría microdatos de
transacciones recientes, y no hay ninguno publicado en abierto en España: el
Consejo General del Notariado y el Colegio de Registradores publican agregados,
no operación a operación.
"""
from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

from formato import euros

CACHE_DIR = Path(__file__).parent / "data" / "precio_compra"
MIVAU_URL = "https://cdn.mivau.gob.es/portal-web-mivau/Datos_MIVAU/CSV/VDP006_01.csv"
MUNICIPAL_URL = "https://apps.fomento.gob.es/boletinonline2/sedal/35103500.XLS"
TIMEOUT = 120.0
MAX_BYTES = 20 * 1024 * 1024
MAX_BYTES_XLS = 40 * 1024 * 1024
REGIMEN = "Libre"

FUENTE = ("Ministerio de Vivienda y Agenda Urbana, valor tasado de la vivienda "
          "libre (€/m², por provincia y trimestre)")
FUENTE_MUNICIPAL = ("Ministerio de Vivienda y Agenda Urbana, valor tasado de la "
                    "vivienda libre en municipios de más de 25.000 habitantes "
                    "(€/m², por trimestre)")

# Un municipio no puede valer una fracción ni un múltiplo desmedido de su
# provincia. Si el cruce por nombre produjera algo así, es que el cruce está mal,
# y vale más perder el dato que publicar un precio de otro sitio.
BANDA_PLAUSIBLE = (0.35, 3.5)

# Nombres que el Excel escribe distinto al listado con códigos INE. Cada uno
# comprobado a mano; son los 12 que no encajan por normalización.
ALIAS_MUNICIPIOS = {
    "mahon": "mao",
    "palma de mallorca": "palma",
    "san cristobal laguna": "san cristobal de la laguna",
    "santa cruz detenerife": "santa cruz de tenerife",
    "santa coloma gramanet": "santa coloma de gramenet",
    "calpe calp": "calp",
    "san vicente del raspeig": "san vicente del raspeig sant vicent del raspeig",
    "burriana": "borriana",
    "castellon de la plana": "castello de la plana",
    "villarreal vila real": "vila real",
    "vitoria": "vitoria gasteiz",
    "san sebastian donostia": "donostia san sebastian",
}


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
class PrecioMunicipio:
    codigo_ine: str = ""
    municipio: str = ""
    euros_m2: float | None = None
    euros_m2_hasta_5_anios: float | None = None
    euros_m2_mas_5_anios: float | None = None
    periodo: str | None = None
    fuente: str = FUENTE_MUNICIPAL
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ValorReferencia:
    """Lo que valdría un inmueble según el precio oficial de su zona."""
    valor_referencia: float | None = None
    euros_m2: float | None = None
    superficie_m2: float | None = None
    ambito: str = "provincia"          # municipio | provincia
    periodo: str | None = None
    provincia: str | None = None
    municipio: str | None = None
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


# El fichero no trae Navarra ni Asturias como provincia, sólo como comunidad
# autónoma. Al ser uniprovinciales, la comunidad ES la provincia —mismo
# territorio, mismo dato—, así que se toman de ahí en lugar de dejarlas sin
# precio. Sin esto, la comparación de municipios devolvía cero en esas dos.
CCAA_UNIPROVINCIAL = {"03": "33", "15": "31"}   # Asturias, Navarra


def _destila(contenido: str) -> dict:
    """CSV → {codigo_provincia: {nombre, serie: {'2026-1': 4047.5, …}}}."""
    out: dict[str, dict] = {}
    for fila in csv.DictReader(io.StringIO(contenido), delimiter=";"):
        if (fila.get("Régimen") or "").strip() != REGIMEN:
            continue
        valor = _num(fila.get("Valor") or "")
        if valor is None:
            continue
        cp = (fila.get("CPRO") or "").strip()
        nombre = (fila.get("Provincia") or "").strip()
        if not cp:
            # Fila de comunidad autónoma: sólo interesa si es uniprovincial.
            cp = CCAA_UNIPROVINCIAL.get((fila.get("CODAUTO") or "").strip().zfill(2))
            if not cp:
                continue
            nombre = (fila.get("Comunidad_Autónoma") or "").strip()
        # El fichero trae una fila agregada de «Ceuta y Melilla» con CPRO="null".
        # Sin este filtro se colaba como si fuera una provincia más.
        if not cp.isdigit():
            continue
        cp = cp.zfill(2)
        try:
            anio, trimestre = int(fila["Año"]), int(fila["Trimestre"])
        except (KeyError, ValueError):
            continue
        reg = out.setdefault(cp, {"nombre": nombre, "serie": {}})
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


def _normaliza(texto: str) -> str:
    """«Ejido (El)» y «Ejido, El» → «ejido». Sin acentos, artículo ni signos."""
    t = "".join(c for c in unicodedata.normalize("NFD", texto or "")
                if unicodedata.category(c) != "Mn").lower().strip()
    articulo = r"(el|la|los|las|l|els|les|a|o|os|as)"
    t = re.sub(rf"\s*\({articulo}\)\s*$", "", t)
    t = re.sub(rf",\s*{articulo}\s*$", "", t)
    t = re.sub(r"^(el|la|los|las|els|les)\s+", "", t)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", t)).strip()


def _indice_municipios_ine() -> dict[str, list[str]]:
    """{nombre normalizado: [códigos INE]} desde el fichero de alquiler.

    Se reutiliza ese listado porque es del mismo ministerio y sí lleva el código
    INE, que es lo único que permite cruzar este Excel con el resto del proyecto.
    """
    from alquiler_real import _carga as carga_alquiler
    indice: dict[str, list[str]] = {}
    for codigo, registro in carga_alquiler().items():
        indice.setdefault(_normaliza(registro["nombre"]), []).append(codigo)
    return indice


def _lee_xls_municipal(contenido: bytes) -> tuple[dict, str]:
    """Excel del BoletínOnline → ({codigo_ine: {…}}, periodo).

    Sólo se lee la última hoja, que es el trimestre más reciente; las 84
    anteriores son historia que aquí no se usa.
    """
    import xlrd

    libro = xlrd.open_workbook(file_contents=contenido, on_demand=True)
    nombre_hoja = libro.sheet_names()[-1]
    hoja = libro.sheet_by_name(nombre_hoja)

    # «T1A2026» → «2026T1».
    m = re.match(r"T(\d)A(\d{4})", nombre_hoja.strip())
    periodo = f"{m.group(2)}T{m.group(1)}" if m else nombre_hoja.strip()

    indice = _indice_municipios_ine()
    provincias = _carga()

    # Las etiquetas de provincia no encabezan su bloque: están centradas dentro
    # de él. Se recogen con su fila y luego se asigna a cada municipio la más
    # cercana, que es la de su propio bloque.
    etiquetas: list[tuple[int, str]] = []
    crudos: list[tuple[int, str, float, float | None, float | None]] = []
    for r in range(hoja.nrows):
        fila = hoja.row_values(r)
        if len(fila) < 6:
            continue
        provincia, municipio = str(fila[1]).strip(), str(fila[2]).strip()
        if provincia and not municipio:
            etiquetas.append((r, provincia))
        elif provincia:
            etiquetas.append((r, provincia))
        if not municipio:
            continue
        try:
            total = float(fila[5])
        except (TypeError, ValueError):
            continue                      # «n.r»: no representativo
        crudos.append((r, municipio, total, _num(str(fila[3])), _num(str(fila[4]))))

    por_nombre_provincia = {_normaliza(d["nombre"]): cp for cp, d in provincias.items()}

    out: dict[str, dict] = {}
    for r, municipio, total, hasta5, mas5 in crudos:
        clave = _normaliza(municipio)
        clave = _normaliza(ALIAS_MUNICIPIOS.get(clave, clave))
        candidatos = indice.get(clave, [])

        if len(candidatos) > 1 and etiquetas:
            # Desempate por el bloque: la etiqueta de provincia más cercana.
            _, provincia = min(etiquetas, key=lambda e: abs(e[0] - r))
            cp = por_nombre_provincia.get(_normaliza(provincia))
            candidatos = [c for c in candidatos if c.startswith(cp or "??")]
        if len(candidatos) != 1:
            continue

        codigo = candidatos[0]
        # Guardia contra un cruce erróneo: el municipio debe parecerse a su
        # provincia. Un dato descartado cuesta menos que un dato de otro sitio.
        provincial = _ultimo(provincias.get(codigo[:2], {}).get("serie", {}))
        if provincial:
            razon = total / provincial[2]
            if not BANDA_PLAUSIBLE[0] <= razon <= BANDA_PLAUSIBLE[1]:
                continue

        out[codigo] = {"nombre": municipio, "euros_m2": total,
                       "hasta5": hasta5, "mas5": mas5}
    return out, periodo


def _carga_municipal(forzar: bool = False) -> tuple[dict, str]:
    destino = CACHE_DIR / "valor_tasado_municipal.json"
    if destino.exists() and not forzar:
        try:
            guardado = json.loads(destino.read_text(encoding="utf-8"))
            return guardado["municipios"], guardado["periodo"]
        except Exception:
            pass

    with httpx.stream("GET", MUNICIPAL_URL, timeout=TIMEOUT,
                      follow_redirects=True) as r:
        r.raise_for_status()
        trozos, total = [], 0
        for trozo in r.iter_bytes():
            total += len(trozo)
            if total > MAX_BYTES_XLS:
                raise ValueError("El Excel municipal supera el límite previsto")
            trozos.append(trozo)

    municipios, periodo = _lee_xls_municipal(b"".join(trozos))
    if not municipios:
        raise ValueError("El Excel municipal no trajo ningún municipio emparejado")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps({
        "origen": MUNICIPAL_URL,
        "periodo": periodo,
        "descargado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "municipios": municipios,
    }, ensure_ascii=False), encoding="utf-8")
    return municipios, periodo


def precio_municipio(codigo_ine: str) -> PrecioMunicipio:
    """€/m² tasado de un municipio, si el ministerio lo publica.

    Sólo están los de más de 25.000 habitantes: por debajo hay pocas tasaciones
    y la media dejaría de ser significativa.
    """
    codigo = str(codigo_ine).strip().zfill(5)
    try:
        municipios, periodo = _carga_municipal()
    except Exception as e:
        return PrecioMunicipio(codigo_ine=codigo,
                               error=f"No se pudo obtener el valor tasado municipal: {e}")

    datos = municipios.get(codigo)
    if not datos:
        return PrecioMunicipio(
            codigo_ine=codigo, periodo=periodo,
            error="El ministerio sólo publica el valor tasado de los municipios de "
                  "más de 25.000 habitantes, y este no está entre ellos.")
    return PrecioMunicipio(
        codigo_ine=codigo, municipio=datos["nombre"], euros_m2=datos["euros_m2"],
        euros_m2_hasta_5_anios=datos.get("hasta5"),
        euros_m2_mas_5_anios=datos.get("mas5"), periodo=periodo,
    )


def municipios_con_precio() -> dict:
    """{codigo_ine: €/m²} de todos los municipios publicados, de una vez."""
    try:
        municipios, _ = _carga_municipal()
    except Exception:
        return {}
    return {c: d["euros_m2"] for c, d in municipios.items()}


def valorar_por_superficie(codigo_provincia: str,
                           superficie_m2: float | None,
                           codigo_municipio: str | None = None,
                           anio_construccion: int | None = None) -> ValorReferencia:
    """Valor de referencia de un inmueble: €/m² oficial de su zona × superficie.

    Manda el dato del municipio, que es el que describe el sitio; la provincia
    sólo entra cuando el ministerio no publica ese municipio. La respuesta dice
    siempre cuál de los dos se usó, porque no valen lo mismo.
    """
    if not superficie_m2:
        return ValorReferencia(error="Sin superficie del Catastro no se puede valorar")

    p = precio_provincia(codigo_provincia)
    municipal = precio_municipio(codigo_municipio) if codigo_municipio else None

    if municipal and not municipal.error and municipal.euros_m2:
        # El Excel separa vivienda de hasta cinco años y de más. Si el Catastro
        # da el año de construcción, se usa el tramo que corresponde en lugar de
        # la media de los dos.
        euros_m2, matiz = municipal.euros_m2, ""
        if anio_construccion:
            antiguedad = datetime.now(timezone.utc).year - anio_construccion
            tramo = (municipal.euros_m2_hasta_5_anios if antiguedad <= 5
                     else municipal.euros_m2_mas_5_anios)
            if tramo:
                euros_m2 = tramo
                matiz = (f", en el tramo de vivienda de "
                         f"{'hasta' if antiguedad <= 5 else 'más de'} cinco años de "
                         f"antigüedad (el inmueble tiene {antiguedad})")

        avisos = [
            f"Valor de referencia: {euros(euros_m2)} €/m² tasados de media en "
            f"{municipal.municipio} ({municipal.periodo}){matiz}, por los "
            f"{superficie_m2:.0f} m² del Catastro.",
            "Es la media del MUNICIPIO, no una tasación de este inmueble: no distingue "
            "barrio, estado de conservación, planta ni orientación. Sirve como orden de "
            "magnitud para situar el precio de salida, no como valoración.",
        ]
        if p.euros_m2:
            razon = (euros_m2 / p.euros_m2 - 1) * 100
            avisos.append(
                f"Ese municipio está un {razon:+.0f} % respecto a la media de la "
                f"provincia de {p.provincia} ({euros(p.euros_m2)} €/m²)."
            )
        return ValorReferencia(
            valor_referencia=round(euros_m2 * superficie_m2, 2),
            euros_m2=euros_m2, superficie_m2=superficie_m2, ambito="municipio",
            periodo=municipal.periodo, provincia=p.provincia,
            municipio=municipal.municipio, fuente=FUENTE_MUNICIPAL, avisos=avisos,
        )

    if p.error or not p.euros_m2:
        return ValorReferencia(error=p.error or "Sin precio para esa provincia")

    avisos = [
        f"Valor de referencia: {euros(p.euros_m2)} €/m² tasados de media en la provincia "
        f"de {p.provincia} ({p.anio}T{p.trimestre}), por los {superficie_m2:.0f} m² del "
        "Catastro.",
        "Es una media PROVINCIAL de tasaciones, no una tasación de este inmueble. El "
        "ministerio publica el detalle por municipio sólo para los de más de 25.000 "
        "habitantes, y este no está; dentro de una provincia el precio real varía mucho, "
        "así que tómalo como orden de magnitud largo.",
    ]
    if p.variacion_anual_pct is not None:
        avisos.append(f"En esa provincia el valor tasado se movió un "
                      f"{p.variacion_anual_pct:+.1f} % en el último año.")

    return ValorReferencia(
        valor_referencia=round(p.euros_m2 * superficie_m2, 2),
        euros_m2=p.euros_m2,
        superficie_m2=superficie_m2,
        ambito="provincia",
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
    out = {"origen": MIVAU_URL, "provincias": len(provincias),
           "ultimo_periodo": f"{anio}T{trimestre}"}
    try:
        municipios, periodo = _carga_municipal()
        out["municipal"] = {"origen": MUNICIPAL_URL, "municipios": len(municipios),
                            "ultimo_periodo": periodo}
    except Exception as e:
        out["municipal"] = {"origen": MUNICIPAL_URL, "error": f"{type(e).__name__}: {e}"}
    return out
