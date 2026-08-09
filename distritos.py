"""
Nombres de los distritos censales del INE.

Los datos finos del INE —la renta del Atlas y el índice de alquiler del IPVA—
llegan a **distrito**, pero el INE los publica sin nombre: sus tablas dicen
«2807904», no «Salamanca». Este módulo pone el nombre.

Cómo se verificó la numeración, que es lo delicado (la del INE no tiene por qué
coincidir con la del ayuntamiento): cruzando la renta por distrito del Atlas con
el orden socioeconómico conocido de cada ciudad, arriba y abajo. Sólo entran las
ciudades donde ese contraste sale limpio de punta a punta:

  - **Madrid**: 05 Chamartín 79.274 € arriba, 13 Puente de Vallecas 32.666 € abajo.
  - **Barcelona**: 05 Sarrià-Sant Gervasi 81.478 €, 01 Ciutat Vella 33.802 €.
  - **Valencia**: 06 El Pla del Real 61.479 €, 18 Pobles de l'Oest 32.233 €.
  - **Sevilla**: 11 Los Remedios 56.389 €, 04 Cerro-Amate 26.160 €.
  - **Málaga**: 02 Este 57.109 €, 06 Cruz de Humilladero 30.570 €.

**Zaragoza se quedó fuera a propósito.** Tiene 12 distritos en el Atlas, tantos
como distritos urbanos tiene la ciudad, así que la tentación era darla por buena.
Pero el contraste falla: sale el 08 —que en la numeración municipal es
Oliver-Valdefierro, de los más humildes— en cuarto lugar por renta, y el 12
—Casablanca, de los más acomodados— a mitad de tabla. O el INE numera distinto o
sus distritos no son los del ayuntamiento. Sin saber cuál de las dos, poner
nombres sería inventar.
"""
from __future__ import annotations

import re
import unicodedata

# Código INE del municipio de cada ciudad con detalle por distrito verificado.
MUNICIPIO = {
    "madrid": "28079",
    "barcelona": "08019",
    "valencia": "46250",
    "sevilla": "41091",
    "malaga": "29067",
}

# Nombres oficiales de los distritos. La clave es el código INE de 7 dígitos:
# 5 del municipio + 2 del distrito.
NOMBRES = {
    # Madrid
    "2807901": "Centro", "2807902": "Arganzuela", "2807903": "Retiro",
    "2807904": "Salamanca", "2807905": "Chamartín", "2807906": "Tetuán",
    "2807907": "Chamberí", "2807908": "Fuencarral-El Pardo",
    "2807909": "Moncloa-Aravaca", "2807910": "Latina", "2807911": "Carabanchel",
    "2807912": "Usera", "2807913": "Puente de Vallecas", "2807914": "Moratalaz",
    "2807915": "Ciudad Lineal", "2807916": "Hortaleza", "2807917": "Villaverde",
    "2807918": "Villa de Vallecas", "2807919": "Vicálvaro",
    "2807920": "San Blas-Canillejas", "2807921": "Barajas",
    # Barcelona
    "0801901": "Ciutat Vella", "0801902": "Eixample",
    "0801903": "Sants-Montjuïc", "0801904": "Les Corts",
    "0801905": "Sarrià-Sant Gervasi", "0801906": "Gràcia",
    "0801907": "Horta-Guinardó", "0801908": "Nou Barris",
    "0801909": "Sant Andreu", "0801910": "Sant Martí",
    # Valencia
    "4625001": "Ciutat Vella", "4625002": "L'Eixample", "4625003": "Extramurs",
    "4625004": "Campanar", "4625005": "La Saïdia", "4625006": "El Pla del Real",
    "4625007": "L'Olivereta", "4625008": "Patraix", "4625009": "Jesús",
    "4625010": "Quatre Carreres", "4625011": "Poblats Marítims",
    "4625012": "Camins al Grau", "4625013": "Algirós", "4625014": "Benimaclet",
    "4625015": "Rascanya", "4625016": "Benicalap", "4625017": "Pobles del Nord",
    "4625018": "Pobles de l'Oest", "4625019": "Pobles del Sud",
    # Sevilla
    "4109101": "Casco Antiguo", "4109102": "Macarena", "4109103": "Nervión",
    "4109104": "Cerro-Amate", "4109105": "Sur", "4109106": "Triana",
    "4109107": "Norte", "4109108": "San Pablo-Santa Justa",
    "4109109": "Este-Alcosa-Torreblanca", "4109110": "Bellavista-La Palmera",
    "4109111": "Los Remedios",
    # Málaga
    "2906701": "Centro", "2906702": "Este", "2906703": "Ciudad Jardín",
    "2906704": "Bailén-Miraflores", "2906705": "Palma-Palmilla",
    "2906706": "Cruz de Humilladero", "2906707": "Carretera de Cádiz",
    "2906708": "Churriana", "2906709": "Campanillas",
    "2906710": "Puerto de la Torre", "2906711": "Teatinos-Universidad",
}


def _clave(texto: str) -> str:
    """«Málaga» → «malaga». Sin acentos, sin signos, sin dobles espacios."""
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFD", texto or "")
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", sin_acentos.lower())).strip()


def municipio_de(ciudad: str) -> str | None:
    """Código INE del municipio de una ciudad con detalle por distrito."""
    return MUNICIPIO.get(_clave(ciudad))


def nombre_distrito(codigo: str) -> str:
    """Nombre del distrito, o su código si la ciudad no está verificada."""
    return NOMBRES.get(str(codigo).strip(), str(codigo).strip())


def ciudades_con_distrito() -> list[str]:
    return sorted(MUNICIPIO)
