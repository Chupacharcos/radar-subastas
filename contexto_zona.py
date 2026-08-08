"""
Lo que pasa alrededor del inmueble y decide si la inversión envejece bien.

Un piso no se revaloriza por sí mismo: lo hace el barrio. Y un barrio mejora o
empeora por cosas que se pueden mirar antes de comprar.

Este módulo reúne el contexto que un inversor con experiencia comprueba y que
ninguna calculadora del sector muestra:

  - **Zona tensionada**: es lo primero, porque es un límite legal, no una
    opinión. En una zona declarada, la renta de un contrato nuevo no puede
    superar la del anterior de los últimos cinco años. Comprar contando con
    subir el alquiler a precio de mercado es, ahí, ilegal.
  - **Renta de los hogares** de la sección censal: determina qué alquiler puede
    pagar de verdad la gente que vive allí.
  - **Antigüedad del edificio**: por encima de 45-50 años entra la Inspección
    Técnica obligatoria, y ahí aparecen derramas de cinco cifras.
  - **Eficiencia energética**: la normativa europea empuja a reformar los
    edificios peor calificados, y eso lo paga el propietario.

Lo que no está y por qué: los datos de criminalidad del Ministerio del Interior
se publican por municipio y trimestre en informes, no en una API estable; y las
obras de infraestructura futura no tienen fuente única. Ambos se documentan
como pendientes en lugar de inventarse un número.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field

REVISADO = "2026-08-08"

# ── Zonas de mercado residencial tensionado (Ley 12/2023) ───────────────────
# A julio de 2026 hay más de 300 municipios declarados en cuatro comunidades.
# Aquí están los de mayor volumen de inversión; la lista completa la publica
# cada comunidad y cambia, así que `verificar_siempre` obliga a comprobarlo.
MUNICIPIOS_TENSIONADOS = {
    # Cataluña — 271 municipios (marzo y octubre de 2024)
    "barcelona", "l'hospitalet de llobregat", "hospitalet de llobregat", "badalona",
    "terrassa", "sabadell", "lleida", "tarragona", "mataro", "mataró",
    "santa coloma de gramenet", "reus", "girona", "cornella de llobregat",
    "cornellà de llobregat", "sant cugat del valles", "sant cugat del vallès",
    "sant boi de llobregat", "manresa", "rubi", "rubí", "vilanova i la geltru",
    "vilanova i la geltrú", "castelldefels", "granollers", "gava", "gavà",
    "el prat de llobregat", "prat de llobregat", "sitges", "esplugues de llobregat",
    "sant adria de besos", "sant adrià de besòs", "montcada i reixac", "vic",
    # País Vasco — 14 municipios (2025 y febrero de 2026)
    "bilbao", "donostia", "donostia-san sebastian", "san sebastian", "vitoria",
    "vitoria-gasteiz", "barakaldo", "errenteria", "irun", "irún", "hernani",
    "getxo", "basauri", "santurtzi",
    # Navarra — 21 municipios (julio de 2025)
    "pamplona", "iruna", "iruña", "burlada", "barañain", "baranain",
    "villava", "zizur mayor", "ansoain", "antsoain", "berriozar", "egues", "egüés",
}

COMUNIDADES_CON_DECLARACION = {"cataluña", "cataluna", "país vasco", "pais vasco",
                               "navarra", "galicia"}

# Umbrales de antigüedad para la Inspección Técnica del Edificio. El plazo
# concreto lo fija cada comunidad o ayuntamiento (entre 45 y 50 años es lo
# habitual), así que se usa el más exigente para avisar antes.
ANIOS_ITE = 45
ANIOS_ITE_INMINENTE = 40


@dataclass
class ContextoZona:
    municipio: str | None = None
    zona_tensionada: bool = False
    zona_tensionada_certeza: str = "desconocida"   # confirmada | probable | descartada | desconocida
    renta_hogar_anual: float | None = None
    renta_es_estimacion: bool = True
    antiguedad_anios: int | None = None
    ite_situacion: str | None = None
    factores: list[dict] = field(default_factory=list)
    pendientes: list[str] = field(default_factory=list)
    revisado: str = REVISADO

    def to_dict(self) -> dict:
        return asdict(self)


def _normaliza(t: str) -> str:
    acentos = str.maketrans("áàäâéèëêíìïîóòöôúùüûñ", "aaaaeeeeiiiioooouuuun")
    return t.strip().lower().translate(acentos)


def evaluar_zona(municipio: str | None, provincia: str | None = None,
                 anio_construccion: int | None = None,
                 renta_hogar_anual: float | None = None,
                 codigo_ine_provincia: str | None = None,
                 codigo_ine_municipio: str | None = None) -> ContextoZona:
    """Contexto del entorno que condiciona la inversión.

    Si se pasan los códigos INE (los devuelve el Catastro), la renta del hogar
    se consulta al Atlas del INE y deja de ser una estimación."""
    # La renta real manda sobre cualquier supuesto.
    if renta_hogar_anual is None and codigo_ine_provincia:
        try:
            from renta_ine import consultar as consultar_renta
            r = consultar_renta(municipio or "", codigo_ine_provincia, codigo_ine_municipio)
            if r.renta_hogar_anual:
                renta_hogar_anual = r.renta_hogar_anual
        except Exception:
            pass   # sin renta se sigue: el resto del contexto no depende de ella

    ctx = ContextoZona(municipio=municipio, renta_hogar_anual=renta_hogar_anual,
                       renta_es_estimacion=False if renta_hogar_anual else True)
    factores: list[dict] = []

    # 1. Zona tensionada — límite legal a los ingresos
    clave = _normaliza(municipio or "")
    if clave and clave in MUNICIPIOS_TENSIONADOS:
        ctx.zona_tensionada, ctx.zona_tensionada_certeza = True, "confirmada"
        factores.append({
            "factor": "Zona de mercado residencial tensionado",
            "efecto": "negativo",
            "detalle": (
                "La renta de un contrato nuevo no puede superar la del contrato anterior "
                "de los últimos 5 años, actualizada. Si eres gran tenedor o la vivienda "
                "lleva 5 años sin alquilarse, queda topada por el índice estatal."
            ),
            "implicacion": (
                "Comprar contando con subir el alquiler a precio de mercado no es "
                "posible aquí. El alquiler que puedas cobrar puede ser bastante menor "
                "que el de los anuncios de la zona."
            ),
            "fuente": "Ley 12/2023 por el derecho a la vivienda; declaración autonómica",
        })
    elif _normaliza(provincia or "") in {"barcelona", "girona", "lleida", "tarragona",
                                         "vizcaya", "bizkaia", "guipuzcoa", "gipuzkoa",
                                         "alava", "araba", "navarra"}:
        ctx.zona_tensionada_certeza = "probable"
        factores.append({
            "factor": "Provincia con municipios declarados tensionados",
            "efecto": "revisar",
            "detalle": "Cataluña, País Vasco, Navarra y Galicia han declarado más de 300 "
                       "municipios. Este no está en la lista corta que maneja el proyecto.",
            "implicacion": "Comprueba en la comunidad autónoma si el municipio está declarado "
                           "antes de proyectar ingresos por alquiler.",
            "fuente": "Ley 12/2023; listados autonómicos publicados en el BOE",
        })
    else:
        ctx.zona_tensionada_certeza = "descartada"

    # 2. Antigüedad e Inspección Técnica del Edificio
    if anio_construccion:
        from datetime import date
        edad = date.today().year - anio_construccion
        ctx.antiguedad_anios = edad
        if edad >= ANIOS_ITE:
            ctx.ite_situacion = "exigible"
            factores.append({
                "factor": f"Edificio de {edad} años: ITE exigible",
                "efecto": "negativo",
                "detalle": "Los edificios de más de 45-50 años pasan Inspección Técnica "
                           "obligatoria. Un resultado desfavorable obliga a obras.",
                "implicacion": "Pide el acta de la ITE y las de la comunidad: una derrama de "
                               "rehabilitación puede superar los 10.000 € por vivienda.",
                "fuente": "Normativa autonómica y municipal de ITE/IEE",
            })
        elif edad >= ANIOS_ITE_INMINENTE:
            ctx.ite_situacion = "próxima"
            factores.append({
                "factor": f"Edificio de {edad} años: ITE próxima",
                "efecto": "revisar",
                "detalle": "Entrará en plazo de Inspección Técnica en los próximos años.",
                "implicacion": "Pregunta en la comunidad si hay obras previstas o fondo de reserva.",
                "fuente": "Normativa autonómica y municipal de ITE/IEE",
            })
        else:
            ctx.ite_situacion = "no exigible aún"

        if anio_construccion < 1980:
            factores.append({
                "factor": "Construido antes de 1980",
                "efecto": "negativo",
                "detalle": "Anterior a la normativa térmica: es probable una calificación "
                           "energética baja (E, F o G).",
                "implicacion": "La normativa europea empuja a rehabilitar los edificios peor "
                               "calificados, y esa obra la paga el propietario. Además, una "
                               "letra baja resta demanda de alquiler.",
                "fuente": "NBE-CT-79 y directiva europea de eficiencia energética",
            })

    # 3. Capacidad de pago de la zona
    if renta_hogar_anual:
        factores.append({
            "factor": f"Renta media del hogar en la zona: {renta_hogar_anual:,.0f} €/año",
            "efecto": "informativo",
            "detalle": "Determina qué alquiler puede pagar de verdad quien vive allí.",
            "implicacion": "Un alquiler por encima del 35 % de esa renta genera impagos y rotación.",
            "fuente": "INE, Atlas de distribución de renta de los hogares (dato real)",
        })

    ctx.factores = factores
    ctx.pendientes = [
        "Criminalidad por barrio: el Ministerio del Interior publica por municipio y "
        "trimestre en informes, sin API estable. Consulta manual en "
        "estadisticasdecriminalidad.ses.mir.es",
        "Obra pública prevista (metro, hospitales, estaciones): no hay fuente única "
        "nacional; se consulta en los planes de la comunidad y del ayuntamiento",
        "Certificado energético concreto: los registros son autonómicos y no todos "
        "publican API",
        "Oferta futura de vivienda en la zona (promociones en construcción que "
        "competirán por el mismo inquilino)",
    ]
    return ctx
