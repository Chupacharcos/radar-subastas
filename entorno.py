"""
Qué hay alrededor del inmueble: transporte, servicios y ruido.

Lo que hace que un piso se alquile rápido y a buen precio no es el piso: es
tener metro a diez minutos, un colegio cerca y un supermercado a pie. Y lo que
hace que se alquile mal tampoco está en la ficha: una vía de tren pegada, una
autovía o una zona sin comercio.

Se usa **OpenStreetMap** a través de la API Overpass. Es la única fuente de
equipamiento urbano que es gratuita, sin clave, con cobertura nacional y con
una licencia (ODbL) que **permite redistribuir citando la fuente** — a
diferencia de Google Places, que prohíbe almacenar y mostrar sus datos fuera de
sus mapas.

Los recuentos son un indicio, no un censo: OSM lo mantienen voluntarios y una
zona puede estar mejor cartografiada que otra. Por eso se devuelven los números
crudos junto a su lectura, y nunca una "puntuación de barrio" que aparente una
precisión que no existe.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict, field

import httpx

OVERPASS = "https://overpass-api.de/api/interpreter"
TIMEOUT = 45.0
ATRIBUCION = "© colaboradores de OpenStreetMap (ODbL)"
# Overpass rechaza con 406 las peticiones sin User-Agent identificable: pide
# saber quién consulta para poder contactar si un cliente se pasa de vueltas.
UA = "subastas-radar/1.0 (+https://adrianmoreno-dev.com; analisis de subastas BOE)"

# Radios en metros, elegidos por lo que de verdad importa a un inquilino:
# el transporte se acepta más lejos que el supermercado del día a día.
RADIO_TRANSPORTE = 1200
RADIO_SERVICIOS = 900
RADIO_MOLESTIAS = 300


@dataclass
class Entorno:
    disponible: bool = False
    transporte: dict = field(default_factory=dict)
    servicios: dict = field(default_factory=dict)
    molestias: dict = field(default_factory=dict)
    lecturas: list[str] = field(default_factory=list)
    atribucion: str = ATRIBUCION
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _consulta(lat: float, lon: float) -> str:
    """Una sola consulta Overpass con todo lo que interesa, etiquetado."""
    return f"""
[out:json][timeout:40];
(
  nwr["railway"="station"](around:{RADIO_TRANSPORTE},{lat},{lon});
  nwr["railway"="subway_entrance"](around:{RADIO_TRANSPORTE},{lat},{lon});
  nwr["highway"="bus_stop"](around:{RADIO_SERVICIOS},{lat},{lon});
  nwr["amenity"="school"](around:{RADIO_SERVICIOS},{lat},{lon});
  nwr["amenity"~"^(hospital|clinic|doctors)$"](around:{RADIO_SERVICIOS},{lat},{lon});
  nwr["amenity"="pharmacy"](around:{RADIO_SERVICIOS},{lat},{lon});
  nwr["shop"~"^(supermarket|convenience)$"](around:{RADIO_SERVICIOS},{lat},{lon});
  nwr["leisure"~"^(park|garden|pitch)$"](around:{RADIO_SERVICIOS},{lat},{lon});
  nwr["highway"~"^(motorway|trunk)$"](around:{RADIO_MOLESTIAS},{lat},{lon});
  nwr["railway"="rail"](around:{RADIO_MOLESTIAS},{lat},{lon});
);
out tags center;
"""


def _clasifica(elementos: list[dict]) -> tuple[dict, dict, dict]:
    transporte = {"estaciones_tren_metro": 0, "bocas_de_metro": 0, "paradas_bus": 0}
    servicios = {"colegios": 0, "centros_salud": 0, "farmacias": 0,
                 "supermercados": 0, "zonas_verdes": 0}
    molestias = {"vias_rapidas": 0, "vias_de_tren": 0}

    for e in elementos:
        t = e.get("tags") or {}
        if t.get("railway") == "station":
            transporte["estaciones_tren_metro"] += 1
        elif t.get("railway") == "subway_entrance":
            transporte["bocas_de_metro"] += 1
        elif t.get("highway") == "bus_stop":
            transporte["paradas_bus"] += 1
        elif t.get("amenity") == "school":
            servicios["colegios"] += 1
        elif t.get("amenity") in ("hospital", "clinic", "doctors"):
            servicios["centros_salud"] += 1
        elif t.get("amenity") == "pharmacy":
            servicios["farmacias"] += 1
        elif t.get("shop") in ("supermarket", "convenience"):
            servicios["supermercados"] += 1
        elif t.get("leisure") in ("park", "garden", "pitch"):
            servicios["zonas_verdes"] += 1
        elif t.get("highway") in ("motorway", "trunk"):
            molestias["vias_rapidas"] += 1
        elif t.get("railway") == "rail":
            molestias["vias_de_tren"] += 1

    return transporte, servicios, molestias


def _lecturas(transporte: dict, servicios: dict, molestias: dict) -> list[str]:
    """Lo que significan los recuentos para quien va a alquilar el piso."""
    out: list[str] = []
    tren = transporte["estaciones_tren_metro"] + transporte["bocas_de_metro"]

    if tren:
        out.append(
            f"Hay {tren} acceso(s) a tren o metro a menos de {RADIO_TRANSPORTE} m. "
            "Es lo que más acorta el tiempo hasta alquilar en las grandes ciudades."
        )
    elif transporte["paradas_bus"]:
        out.append(
            f"Sin tren ni metro cerca, sólo {transporte['paradas_bus']} parada(s) de autobús. "
            "Reduce el número de inquilinos posibles a quien tenga coche."
        )
    else:
        out.append(
            "Sin transporte público cartografiado alrededor. Comprueba la conexión real: "
            "sin ella el alquiler se resiente y la reventa también."
        )

    if servicios["supermercados"] == 0:
        out.append("No consta ningún supermercado a menos de 900 m: en vivienda urbana "
                   "es un lastre para alquilar.")
    if servicios["colegios"] >= 2:
        out.append(f"{servicios['colegios']} colegios cerca: atrae a familias, que suelen "
                   "ser inquilinos más estables y de contrato más largo.")
    if servicios["zonas_verdes"] >= 2:
        out.append(f"{servicios['zonas_verdes']} zonas verdes en el entorno.")

    if molestias["vias_rapidas"]:
        out.append(f"Hay una vía rápida a menos de {RADIO_MOLESTIAS} m: ruido y contaminación "
                   "que se notan en el precio y en la rotación de inquilinos.")
    if molestias["vias_de_tren"]:
        out.append(f"Vía de tren a menos de {RADIO_MOLESTIAS} m: valora el ruido antes de comprar.")

    return out


def analizar_entorno(latitud: float, longitud: float) -> Entorno:
    """Equipamiento y molestias alrededor de unas coordenadas."""
    try:
        r = httpx.post(OVERPASS, data={"data": _consulta(latitud, longitud)},
                       headers={"User-Agent": UA}, timeout=TIMEOUT)
        r.raise_for_status()
        elementos = r.json().get("elements", [])
    except Exception as e:
        return Entorno(
            disponible=False,
            error=f"OpenStreetMap no respondió ({type(e).__name__}). El entorno no se "
                  "ha podido analizar; el resto del informe no depende de ello.",
        )

    transporte, servicios, molestias = _clasifica(elementos)
    return Entorno(
        disponible=True,
        transporte=transporte,
        servicios=servicios,
        molestias=molestias,
        lecturas=_lecturas(transporte, servicios, molestias),
    )


NOMINATIM = "https://nominatim.openstreetmap.org/search"


def geocodificar(direccion: str, codigo_postal: str | None = None,
                 municipio: str | None = None) -> tuple[float, float] | None:
    """Coordenadas de una dirección, vía Nominatim (OpenStreetMap).

    El servicio de coordenadas del Catastro exige provincia y municipio con su
    grafía exacta y falla con la que publica el BOE, así que se geocodifica la
    dirección. La política de uso de Nominatim pide un máximo de una petición
    por segundo y un User-Agent identificable: ambas se respetan.
    """
    # El BOE escribe «CALLE FIDIAS NUMERO 11» y Nominatim no reconoce «NUMERO»,
    # ni las abreviaturas de portal, escalera o puerta. Se limpian antes.
    limpia = re.sub(r"\bN[UÚ]MERO\b|\bN[ºO]\.?\b", " ", (direccion or ""), flags=re.I)
    limpia = re.sub(r"\b(PL|PTA|ESC|ESCALERA|PISO|BAJO|ATICO|ÁTICO|PORTAL)\b.*$", " ",
                    limpia, flags=re.I)
    # Tras el número de portal ya no hay nada geocodificable: «62, esc 1, 9º D»
    # confunde a Nominatim, que devuelve vacío. Se corta en el primer número.
    m = re.match(r"^(.*?\d+)\b", limpia)
    if m:
        limpia = m.group(1)
    limpia = re.sub(r"\s+", " ", limpia).strip(" ,.")

    consulta = ", ".join(x for x in (limpia, codigo_postal, municipio, "España") if x)
    try:
        r = httpx.get(NOMINATIM, params={"q": consulta, "format": "json", "limit": 1},
                      headers={"User-Agent": UA}, timeout=20.0)
        r.raise_for_status()
        datos = r.json()
    except Exception:
        return None
    if not datos:
        return None
    try:
        return float(datos[0]["lat"]), float(datos[0]["lon"])
    except (KeyError, ValueError, IndexError):
        return None
