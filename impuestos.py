"""
Impuestos y gastos de compra, con la fuente de cada cifra.

Este módulo existe porque las cifras que trae afectan a decisiones de cientos
de miles de euros. Cada tipo lleva su norma o su fuente al lado, y las que son
estimación se declaran como tales en lugar de disfrazarse de dato.

Verificado el 2026-08-08. Los tipos autonómicos cambian: `revisado` marca la
fecha de la última comprobación y `fuente` dice dónde mirar.
"""
from __future__ import annotations

from dataclasses import dataclass

REVISADO = "2026-08-08"


@dataclass(frozen=True)
class TipoITP:
    """Un tramo de ITP. `hasta` es None en el último tramo."""
    hasta: float | None
    tipo: float


@dataclass(frozen=True)
class RegimenITP:
    comunidad: str
    tramos: tuple[TipoITP, ...]
    fuente: str
    nota: str = ""

    def calcular(self, base: float) -> tuple[float, float]:
        """(cuota, tipo efectivo). En escalas, cada tramo tributa a su tipo."""
        cuota, restante, anterior = 0.0, base, 0.0
        for tramo in self.tramos:
            techo = tramo.hasta if tramo.hasta is not None else float("inf")
            gravable = min(restante, techo - anterior)
            if gravable <= 0:
                break
            cuota += gravable * tramo.tipo
            restante -= gravable
            anterior = techo
        return cuota, (cuota / base if base else 0.0)


def _plano(comunidad: str, tipo: float, fuente: str, nota: str = "") -> RegimenITP:
    return RegimenITP(comunidad, (TipoITP(None, tipo),), fuente, nota)


# ── ITP de transmisiones patrimoniales onerosas, vivienda usada ──────────────
# Tipos GENERALES. No se aplican reducciones por edad, familia numerosa, VPO ni
# zona rural porque dependen del comprador y no del inmueble: quien las tenga
# pagará menos que lo que calcula esta herramienta, nunca más.
REGIMENES: dict[str, RegimenITP] = {
    "madrid": _plano("Madrid", 0.06, "Ley 10/2009 de la CM, art. 28"),
    "navarra": _plano("Navarra", 0.06, "Régimen foral navarro, DF Leg. 129/1999"),
    "canarias": _plano("Canarias", 0.065, "DL 1/2009 de Canarias"),
    "andalucia": _plano("Andalucía", 0.07, "DL 1/2018 de Andalucía, tipo único desde 2021"),
    "la rioja": _plano("La Rioja", 0.07, "Ley 10/2017 de La Rioja"),
    "aragon": _plano("Aragón", 0.08, "DL 1/2005 de Aragón"),
    "asturias": _plano("Asturias", 0.08, "DL 2/2014 de Asturias"),
    "castilla y leon": _plano("Castilla y León", 0.08, "DL 1/2013 de CyL"),
    "murcia": _plano("Murcia", 0.08, "DL 1/2010 de Murcia"),
    "castilla-la mancha": _plano("Castilla-La Mancha", 0.09, "Ley 8/2013 de CLM"),
    "galicia": _plano("Galicia", 0.09, "DL 1/2011 de Galicia"),
    # Corregido el 2026-08-08: figuraba 9% por error, el tipo general es 10%.
    "cantabria": _plano("Cantabria", 0.10, "DL 62/2008 de Cantabria"),
    "comunidad valenciana": _plano("Comunidad Valenciana", 0.10, "Ley 13/1997 de la GV"),
    # Escala desde el Decreto Ley 5/2025, en vigor el 27-06-2025 y sin cambios
    # en 2026. Antes era 10% plano (11% por encima del millón).
    "cataluna": RegimenITP(
        "Cataluña",
        (TipoITP(600_000, 0.10), TipoITP(900_000, 0.11), TipoITP(None, 0.12)),
        "Decreto Ley 5/2025 de Cataluña, en vigor 27-06-2025",
        "Los grandes tenedores (más de 10 viviendas urbanas) tributan al 20%. "
        "Menores de 35 años pueden aplicar el 5%.",
    ),
    "baleares": RegimenITP(
        "Illes Balears",
        (TipoITP(400_000, 0.08), TipoITP(600_000, 0.09), TipoITP(1_000_000, 0.11),
         TipoITP(2_000_000, 0.12), TipoITP(None, 0.13)),
        "DL 1/2014 de Baleares, escala por tramos",
    ),
    "extremadura": RegimenITP(
        "Extremadura",
        (TipoITP(360_000, 0.08), TipoITP(600_000, 0.10), TipoITP(None, 0.11)),
        "DL 1/2018 de Extremadura, escala por tramos",
    ),
    "pais vasco": _plano(
        "País Vasco", 0.04, "Normas forales de Álava, Bizkaia y Gipuzkoa",
        "Régimen foral: el 4% es el tipo habitual en vivienda; "
        "hay supuestos al 7% según territorio histórico y tipo de inmueble.",
    ),
}

PROVINCIA_A_COMUNIDAD = {
    "madrid": "madrid",
    "barcelona": "cataluna", "girona": "cataluna", "gerona": "cataluna",
    "lleida": "cataluna", "lerida": "cataluna", "tarragona": "cataluna",
    "valencia": "comunidad valenciana", "alicante": "comunidad valenciana",
    "castellon": "comunidad valenciana",
    "sevilla": "andalucia", "malaga": "andalucia", "cadiz": "andalucia",
    "granada": "andalucia", "cordoba": "andalucia", "almeria": "andalucia",
    "huelva": "andalucia", "jaen": "andalucia",
    "vizcaya": "pais vasco", "bizkaia": "pais vasco", "guipuzcoa": "pais vasco",
    "gipuzkoa": "pais vasco", "alava": "pais vasco", "araba": "pais vasco",
    "zaragoza": "aragon", "huesca": "aragon", "teruel": "aragon",
    "murcia": "murcia", "asturias": "asturias", "cantabria": "cantabria",
    "navarra": "navarra", "la rioja": "la rioja",
    "islas baleares": "baleares", "baleares": "baleares", "illes balears": "baleares",
    "las palmas": "canarias", "santa cruz de tenerife": "canarias", "canarias": "canarias",
    "badajoz": "extremadura", "caceres": "extremadura",
    "toledo": "castilla-la mancha", "ciudad real": "castilla-la mancha",
    "cuenca": "castilla-la mancha", "guadalajara": "castilla-la mancha",
    "albacete": "castilla-la mancha",
    "a coruna": "galicia", "la coruna": "galicia", "lugo": "galicia",
    "ourense": "galicia", "orense": "galicia", "pontevedra": "galicia",
    "valladolid": "castilla y leon", "burgos": "castilla y leon", "leon": "castilla y leon",
    "salamanca": "castilla y leon", "zamora": "castilla y leon", "avila": "castilla y leon",
    "segovia": "castilla y leon", "soria": "castilla y leon", "palencia": "castilla y leon",
}

# Media nacional ponderada, para cuando no se identifica la provincia.
REGIMEN_POR_DEFECTO = _plano("España (media)", 0.08,
                             "Media orientativa: los tipos van del 4% al 13%")


def _normaliza(texto: str) -> str:
    acentos = str.maketrans("áàäâéèëêíìïîóòöôúùüûñ", "aaaaeeeeiiiioooouuuun")
    return texto.strip().lower().translate(acentos)


def regimen_de(provincia_o_comunidad: str | None) -> RegimenITP:
    if not provincia_o_comunidad:
        return REGIMEN_POR_DEFECTO
    clave = _normaliza(provincia_o_comunidad)
    if clave in REGIMENES:
        return REGIMENES[clave]
    comunidad = PROVINCIA_A_COMUNIDAD.get(clave)
    return REGIMENES.get(comunidad, REGIMEN_POR_DEFECTO) if comunidad else REGIMEN_POR_DEFECTO


def calcular_itp(base: float, provincia: str | None) -> dict:
    r = regimen_de(provincia)
    cuota, efectivo = r.calcular(base)
    return {
        "cuota": round(cuota, 2),
        "tipo_efectivo": round(efectivo, 4),
        "comunidad": r.comunidad,
        "escalonado": len(r.tramos) > 1,
        "fuente": r.fuente,
        "nota": r.nota,
        "revisado": REVISADO,
    }


# ── Notaría, registro y gestoría ─────────────────────────────────────────────
# Notarios y registradores NO fijan precio libremente: sus aranceles están
# regulados por el RD 1426/1989 y el RD 1427/1989 respectivamente, en tramos
# sobre el valor. Aquí se aproxima con porcentajes sobre el precio y suelos y
# techos observados en el mercado, porque el arancel exacto depende de folios,
# copias y suplidos de cada escritura.
NOTARIA_PCT, NOTARIA_MIN, NOTARIA_MAX = 0.0035, 600.0, 2200.0
REGISTRO_PCT, REGISTRO_MIN, REGISTRO_MAX = 0.0018, 400.0, 1500.0
GESTORIA = 350.0


def gastos_compra(precio: float, en_subasta: bool = True) -> dict:
    """Gastos de formalización, sin contar el impuesto.

    En subasta judicial no hay escritura pública de compraventa: la titularidad
    se documenta con el testimonio del decreto de adjudicación, que se inscribe
    igual en el Registro. Por eso el coste notarial es menor que en una compra
    ordinaria, aunque suelen aparecer gastos de procurador y del propio
    procedimiento que aquí no se estiman.
    """
    notaria = min(max(precio * NOTARIA_PCT, NOTARIA_MIN), NOTARIA_MAX)
    if en_subasta:
        notaria *= 0.4   # sólo testimonio y copias, no escritura de compraventa
    registro = min(max(precio * REGISTRO_PCT, REGISTRO_MIN), REGISTRO_MAX)

    return {
        "notaria": round(notaria, 2),
        "registro": round(registro, 2),
        "gestoria": GESTORIA,
        "total": round(notaria + registro + GESTORIA, 2),
        "fuente": "Aranceles regulados: RD 1426/1989 (notarios) y RD 1427/1989 "
                  "(registradores). Importes aproximados: el arancel exacto depende "
                  "de folios, copias y suplidos.",
        "nota_subasta": (
            "En subasta no hay escritura de compraventa (basta el testimonio del "
            "decreto de adjudicación), pero pueden aparecer costes de procurador y "
            "del procedimiento que no se estiman aquí."
        ) if en_subasta else "",
        "es_estimacion": True,
        "revisado": REVISADO,
    }
