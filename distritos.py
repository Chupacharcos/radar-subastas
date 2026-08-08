"""
De barrio a distrito censal del INE.

Los datos finos del INE —la renta del Atlas y el índice de alquiler del IPVA—
llegan a **distrito**, pero el INE los publica sin nombre: sus tablas dicen
«2807904», no «Salamanca». Y el análisis por zonas de este proyecto habla de
barrios, que es como habla la gente. Este módulo une las dos cosas.

Cómo se verificó la numeración, que es lo delicado (la del INE no tiene por qué
coincidir con la del ayuntamiento): cruzando la renta por distrito del Atlas con
el orden socioeconómico conocido de cada ciudad. En Madrid sale 05 = 79.274 €
(Chamartín) arriba y 13 = 32.666 € (Puente de Vallecas) abajo; en Barcelona,
05 = 81.478 € (Sarrià-Sant Gervasi) arriba y 01 = 33.802 € (Ciutat Vella) abajo.
Ambos órdenes reproducen exactamente la numeración oficial de los dos
ayuntamientos, de principio a fin.

Sólo están Madrid y Barcelona **porque son las dos que se han podido verificar
así**. Para el resto de ciudades el proyecto se queda en el dato municipal, que
también es real, en lugar de repartir barrios por distritos a ojo.

Un aviso que hay que trasladar siempre al usuario: varios barrios caen en el
mismo distrito. Malasaña, Lavapiés, Chueca y Palacio son los cuatro Centro, así
que los cuatro reciben las mismas cifras de distrito. No es un fallo del cálculo,
es el grano al que publica el INE.
"""
from __future__ import annotations

import re
import unicodedata

# Código INE del municipio de cada ciudad con detalle por distrito.
MUNICIPIO = {
    "madrid": "28079",
    "barcelona": "08019",
}

# Nombres oficiales de los distritos. La clave es el código INE de 7 dígitos:
# 5 del municipio + 2 del distrito.
NOMBRES = {
    "2807901": "Centro",
    "2807902": "Arganzuela",
    "2807903": "Retiro",
    "2807904": "Salamanca",
    "2807905": "Chamartín",
    "2807906": "Tetuán",
    "2807907": "Chamberí",
    "2807908": "Fuencarral-El Pardo",
    "2807909": "Moncloa-Aravaca",
    "2807910": "Latina",
    "2807911": "Carabanchel",
    "2807912": "Usera",
    "2807913": "Puente de Vallecas",
    "2807914": "Moratalaz",
    "2807915": "Ciudad Lineal",
    "2807916": "Hortaleza",
    "2807917": "Villaverde",
    "2807918": "Villa de Vallecas",
    "2807919": "Vicálvaro",
    "2807920": "San Blas-Canillejas",
    "2807921": "Barajas",
    "0801901": "Ciutat Vella",
    "0801902": "Eixample",
    "0801903": "Sants-Montjuïc",
    "0801904": "Les Corts",
    "0801905": "Sarrià-Sant Gervasi",
    "0801906": "Gràcia",
    "0801907": "Horta-Guinardó",
    "0801908": "Nou Barris",
    "0801909": "Sant Andreu",
    "0801910": "Sant Martí",
}

# Barrio (como lo nombra el análisis de zonas) → distrito que lo contiene.
BARRIO_A_DISTRITO = {
    "madrid": {
        "malasana": "2807901", "lavapies": "2807901", "chueca": "2807901",
        "palacio": "2807901",
        "arganzuela": "2807902",
        "retiro": "2807903",
        "salamanca": "2807904",
        "tetuan": "2807906",
        "chamberi": "2807907",
        "fuencarral": "2807908",
        "moncloa": "2807909", "arguelles": "2807909",
        "latina": "2807910",
        "carabanchel": "2807911",
        "usera": "2807912",
        "vallecas": "2807913",
        "moratalaz": "2807914",
        "ciudad lineal": "2807915",
        "hortaleza": "2807916",
        "villaverde": "2807917",
        "vicalvaro": "2807919",
        "san blas": "2807920",
        "barajas": "2807921",
    },
    "barcelona": {
        "barri gotic": "0801901", "el born": "0801901",
        "barceloneta": "0801901", "el raval": "0801901",
        "eixample esquerra": "0801902", "eixample dreta": "0801902",
        "sants": "0801903",
        "les corts": "0801904",
        "sarria": "0801905",
        "gracia": "0801906",
        "horta": "0801907",
        "nou barris": "0801908",
        "sant andreu": "0801909",
        "poblenou 22": "0801910", "sant marti": "0801910",
    },
}


def _clave(texto: str) -> str:
    """«Poblenou (22@)» → «poblenou 22». Sin acentos, sin signos, sin dobles espacios."""
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFD", texto or "")
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", sin_acentos.lower())).strip()


def municipio_de(ciudad: str) -> str | None:
    """Código INE del municipio de una ciudad con detalle por distrito."""
    return MUNICIPIO.get(_clave(ciudad))


def distrito_de(ciudad: str, barrio: str) -> dict | None:
    """Distrito censal que contiene a un barrio, o `None` si no consta.

    Devolver `None` no es un error: significa que esa ciudad o ese barrio no se
    han verificado, y quien llama debe quedarse con el dato municipal en lugar de
    inventar una asignación.
    """
    mapa = BARRIO_A_DISTRITO.get(_clave(ciudad))
    if not mapa:
        return None
    codigo = mapa.get(_clave(barrio))
    if not codigo:
        return None
    nombre = NOMBRES.get(codigo, codigo)
    return {
        "codigo": codigo,
        "nombre": nombre,
        # Si el barrio no se llama igual que su distrito, es una parte de él y
        # comparte cifras con los demás barrios del mismo distrito.
        "el_barrio_es_parte_del_distrito": _clave(nombre) != _clave(barrio),
    }


def ciudades_con_distrito() -> list[str]:
    return sorted(BARRIO_A_DISTRITO)
