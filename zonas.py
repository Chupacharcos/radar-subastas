"""
Análisis de zonas de inversión: barrio a barrio, qué cuesta y qué renta.

Responde a la pregunta con la que empieza cualquier inversor, antes incluso de
mirar un inmueble concreto: **¿en qué barrio me conviene comprar?**

Para cada barrio calcula, sobre una vivienda tipo:

  - el **precio** que costaría comprarla,
  - la **cuota de hipoteca** que pagaría,
  - el **alquiler** que podría cobrar,
  - y lo que queda al mes después de todo.

La gracia está en la comparación: un barrio caro con alquileres altos puede
rentar menos que uno barato, y eso no se ve mirando el precio del metro. Aquí
salen ordenados por lo que de verdad importa, la rentabilidad neta.

De dónde sale cada número, que es lo que decide si esto sirve para algo:

  - **Precio por m²**: del proyecto `deteccion-zonas-revalorizacion` del
    portfolio. Son valores **de referencia**, no una medición de mercado: ese
    proyecto entrena con datos sintéticos calibrados y su tabla de barrios está
    escrita a mano. Sirven para ordenar barrios por nivel de precio, no para
    tasar un piso. Va dicho en `avisos` y en `fuentes`, porque presentarlos como
    precio observado sería mentir.
  - **Alquiler**: estimado con la rentabilidad bruta típica de la provincia.
    Mientras SERPAVI siga tras un reCAPTCHA no hay alquileres reales por barrio.
  - **Renta del hogar del distrito** (INE, Atlas): dato real, por distrito
    censal, en las ciudades donde el barrio se ha podido situar en su distrito.
  - **Evolución del alquiler** (INE, IPVA): dato real, construido con los
    contratos declarados a Hacienda. Es índice, no nivel: dice cuánto sube, no
    cuánto se paga.

O sea: lo que sube y quién vive ahí es real; el precio de partida es de
referencia. Mezclarlos sin decirlo sería lo peor de los dos mundos.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, asdict, field
from statistics import median

import httpx

import alquiler_ine
import distritos as distritos_ine
import renta_ine
from rentabilidad import Supuestos, analizar
from valoracion import YIELD_BRUTO, YIELD_POR_DEFECTO

REVALORIZACION_URL = os.getenv("REVALORIZACION_API_URL", "http://127.0.0.1:8090")
TIMEOUT = 20.0

# Vivienda tipo sobre la que se compara. Se puede cambiar por parámetro, pero
# comparar barrios exige que TODOS usen la misma, o no se comparan precios sino
# tamaños distintos.
SUPERFICIE_TIPO = 80

CIUDAD_A_PROVINCIA = {
    "madrid": "madrid", "barcelona": "barcelona", "valencia": "valencia",
    "sevilla": "sevilla", "malaga": "malaga", "bilbao": "vizcaya",
    "zaragoza": "zaragoza", "alicante": "alicante",
}


@dataclass
class Barrio:
    nombre: str
    precio_m2: float
    precio_vivienda: float
    cuota_hipoteca_mensual: float
    alquiler_estimado_mensual: float
    rentabilidad_bruta: float
    rentabilidad_neta: float
    cash_flow_mensual: float
    capital_necesario: float
    anios_recuperar: float | None
    tendencia_anual: float | None = None
    score_revalorizacion: float | None = None
    lat: float | None = None
    lng: float | None = None
    # Datos reales del INE por distrito censal, cuando el barrio se puede situar.
    distrito: str | None = None
    renta_hogar_distrito: float | None = None
    alquiler_var_anual_pct: float | None = None
    alquiler_desde_2015_pct: float | None = None
    esfuerzo_inquilino_pct: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AnalisisZonas:
    ciudad: str
    superficie_tipo: int
    total_barrios: int
    barrios: list[dict] = field(default_factory=list)
    criterio_orden: str = ""
    mejor_rentabilidad: str | None = None
    mejor_cash_flow: str | None = None
    mas_barato: str | None = None
    supuestos: dict = field(default_factory=dict)
    precio_vs_alquiler: dict | None = None
    renta_municipio: dict | None = None
    avisos: list[str] = field(default_factory=list)
    fuentes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _barrios_de(ciudad: str) -> list[dict]:
    r = httpx.get(f"{REVALORIZACION_URL}/ml/revalorizacion/mapa",
                  params={"ciudad": ciudad}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json().get("barrios", [])


def ciudades_disponibles() -> list[dict]:
    try:
        r = httpx.get(f"{REVALORIZACION_URL}/ml/revalorizacion/ciudades", timeout=TIMEOUT)
        r.raise_for_status()
        return r.json().get("ciudades", [])
    except Exception:
        return [{"id": c, "nombre": c.title()} for c in CIUDAD_A_PROVINCIA]


def _datos_ine(codigo_municipio: str | None) -> tuple[dict | None, dict]:
    """Renta del municipio y, por distrito, renta e índice de alquiler del INE.

    Si el INE no responde se sigue sin estos datos: son un extra sobre el
    análisis, no su condición. Nunca deben tumbar la comparación de barrios.
    """
    if not codigo_municipio:
        return None, {}

    renta_muni = None
    try:
        r = renta_ine.consultar("", codigo_municipio[:2], codigo_municipio[2:])
        if not r.error:
            renta_muni = r.to_dict()
    except Exception:
        pass

    por_distrito: dict[str, dict] = {}
    for codigo in alquiler_ine.distritos_de(codigo_municipio):
        entrada: dict = {}
        t = alquiler_ine.tendencia_alquiler_distrito(codigo)
        if not t.error:
            entrada["alquiler"] = t.to_dict()
        renta = renta_ine.renta_distrito(codigo)
        if renta:
            entrada["renta"] = renta
        if entrada:
            por_distrito[codigo] = entrada
    return renta_muni, por_distrito


def _precio_vs_alquiler(codigo_municipio: str | None) -> dict | None:
    """Si el alquiler sube más que el precio de compra, o al revés.

    Es lo único que estos índices responden bien, y responde a la pregunta que
    la comparación de barrios no puede: si el momento de comprar mejora o empeora.
    """
    if not codigo_municipio:
        return None
    try:
        r = alquiler_ine.precio_vs_alquiler(codigo_municipio, codigo_municipio[:2])
    except Exception:
        return None
    return r.to_dict() if not r.error else None


def _adjunta_distrito(barrio: Barrio, ciudad: str, por_distrito: dict,
                      alquiler_mensual: float) -> None:
    """Añade a un barrio los datos reales del INE de su distrito."""
    ref = distritos_ine.distrito_de(ciudad, barrio.nombre)
    if not ref:
        return
    barrio.distrito = ref["nombre"]

    datos = por_distrito.get(ref["codigo"]) or {}
    renta = (datos.get("renta") or {}).get("renta_hogar_anual")
    if renta:
        barrio.renta_hogar_distrito = renta
        # Qué parte de la renta del hogar se lleva el alquiler. Por encima del
        # 30 % la morosidad deja de ser una hipótesis. El alquiler es estimado,
        # así que esto orienta sobre el encaje, no lo mide.
        barrio.esfuerzo_inquilino_pct = round(alquiler_mensual * 12 / renta * 100, 1)

    alq = datos.get("alquiler") or {}
    barrio.alquiler_var_anual_pct = alq.get("variacion_anual_pct")
    barrio.alquiler_desde_2015_pct = alq.get("acumulada_desde_base_pct")


def analizar_zonas(ciudad: str = "madrid", superficie: int = SUPERFICIE_TIPO,
                   s: Supuestos | None = None,
                   alquiler_m2: float | None = None) -> AnalisisZonas:
    """Compara todos los barrios de una ciudad como inversión de alquiler."""
    s = s or Supuestos()
    provincia = CIUDAD_A_PROVINCIA.get(ciudad.lower(), ciudad.lower())
    avisos: list[str] = []

    try:
        crudos = _barrios_de(ciudad)
    except Exception as e:
        return AnalisisZonas(
            ciudad=ciudad, superficie_tipo=superficie, total_barrios=0,
            avisos=[f"No se pudieron obtener los barrios de {ciudad}: {type(e).__name__}. "
                    "El servicio de zonas arranca bajo demanda; reinténtalo en unos segundos."],
        )

    if not crudos:
        return AnalisisZonas(ciudad=ciudad, superficie_tipo=superficie, total_barrios=0,
                             avisos=[f"No hay datos de barrios para «{ciudad}»."])

    yield_bruto = YIELD_BRUTO.get(provincia, YIELD_POR_DEFECTO)
    if alquiler_m2:
        avisos.append(f"Alquiler calculado con los {alquiler_m2} €/m² al mes que has indicado.")
    else:
        avisos.append(
            f"El alquiler es una ESTIMACIÓN: se deriva de la rentabilidad bruta típica de "
            f"{provincia} ({yield_bruto*100:.1f}%). No hay alquileres reales por barrio "
            "mientras SERPAVI —los declarados a Hacienda— siga sin poder consultarse."
        )
        avisos.append(
            "IMPORTANTE: al derivar el alquiler del precio con un porcentaje fijo, la "
            "rentabilidad sale casi idéntica en todos los barrios. Eso no significa que "
            "lo sea: significa que esta comparación NO puede distinguir barrios por "
            "rentabilidad. Lo que sí compara de verdad es el precio de entrada, el "
            "capital necesario y la tendencia. Para comparar rentabilidad de verdad, "
            "introduce el alquiler real en €/m² de cada zona."
        )

    avisos.append(
        "Los €/m² por barrio son valores DE REFERENCIA del proyecto de detección "
        "de zonas de revalorización, no precios observados de mercado: sirven "
        "para ordenar barrios por nivel, no para tasar un piso concreto. Los "
        "datos del INE que aparecen en cada fila —renta del hogar y evolución "
        "del alquiler— sí son reales."
    )

    codigo_municipio = distritos_ine.municipio_de(ciudad)
    renta_muni, por_distrito = _datos_ine(codigo_municipio)

    barrios: list[Barrio] = []
    for b in crudos:
        precio_m2 = b.get("precio_m2")
        if not precio_m2:
            continue
        precio = precio_m2 * superficie
        alquiler = (alquiler_m2 * superficie) if alquiler_m2 else (precio * yield_bruto / 12)

        a = analizar(precio, alquiler, provincia, s)
        barrio = Barrio(
            nombre=b.get("nombre", "?"),
            precio_m2=round(precio_m2, 2),
            precio_vivienda=round(precio, 2),
            cuota_hipoteca_mensual=a.cuota_mensual,
            alquiler_estimado_mensual=round(alquiler, 2),
            rentabilidad_bruta=a.rentabilidad_bruta,
            rentabilidad_neta=a.rentabilidad_neta,
            cash_flow_mensual=a.cash_flow_mensual,
            capital_necesario=a.capital_aportado,
            anios_recuperar=a.anios_recuperar_capital,
            tendencia_anual=b.get("tend_1a"),
            score_revalorizacion=b.get("score"),
            lat=b.get("lat"), lng=b.get("lng"),
        )
        _adjunta_distrito(barrio, ciudad, por_distrito, alquiler)
        barrios.append(barrio)

    if por_distrito:
        avisos.append(
            "La renta del hogar y la evolución del alquiler son del DISTRITO "
            "censal, que es el grano al que publica el INE. Varios barrios caen "
            "en el mismo distrito (Malasaña, Lavapiés, Chueca y Palacio son los "
            "cuatro Centro) y comparten esas dos cifras."
        )
    elif codigo_municipio is None:
        avisos.append(
            f"El detalle por distrito del INE sólo está verificado en "
            f"{' y '.join(c.title() for c in distritos_ine.ciudades_con_distrito())}; "
            f"para {ciudad.title()} se muestra el dato del municipio."
        )

    # Contraste de realidad: el alquiler derivado del precio se compara con la
    # renta REAL del hogar del distrito. Si el esfuerzo típico se dispara, lo que
    # falla no es el barrio, son los supuestos —el €/m² de referencia o la
    # rentabilidad bruta con la que se deriva el alquiler—, y conviene decirlo
    # antes de que alguien tome una decisión con ello.
    esfuerzos = [b.esfuerzo_inquilino_pct for b in barrios
                 if b.esfuerzo_inquilino_pct is not None]
    if esfuerzos and not alquiler_m2:
        tipico = median(esfuerzos)
        if tipico > 40:
            avisos.append(
                f"Aviso de coherencia: el alquiler estimado se llevaría el "
                f"{tipico:.0f} % de la renta media del hogar del distrito, muy por "
                "encima del 30 % que se considera sostenible. Eso no dice que la "
                "zona sea mala: dice que el €/m² de referencia y la rentabilidad "
                "bruta con la que se deriva el alquiler no cuadran con la renta "
                "real de esos hogares. Introduce el alquiler real en €/m² para "
                "que las cifras dejen de ser orientativas."
            )

    # Si el alquiler es derivado del precio, ordenar por rentabilidad es
    # engañoso: sale casi plana. Se ordena entonces por el mejor dato REAL que
    # haya. Antes se ordenaba por la tendencia del proyecto de revalorización
    # llamándola dato real, y no lo es: viene de la misma tabla de referencia que
    # los €/m². Con el IPVA sí hay un dato medido, así que manda ese.
    if alquiler_m2:
        barrios.sort(key=lambda x: -x.rentabilidad_neta)
        criterio = "mayor rentabilidad neta (con el alquiler real que has indicado)"
    elif any(b.alquiler_var_anual_pct is not None for b in barrios):
        barrios.sort(key=lambda x: -(x.alquiler_var_anual_pct or -99))
        criterio = ("mayor subida real del alquiler en su distrito (INE, IPVA) — la "
                    "rentabilidad no ordena porque el alquiler es derivado del precio")
    else:
        barrios.sort(key=lambda x: -(x.tendencia_anual or 0))
        criterio = ("mayor tendencia de revalorización, que es un valor de referencia "
                    "del proyecto de zonas, no una medición — la rentabilidad no "
                    "ordena porque el alquiler es derivado del precio")

    return AnalisisZonas(
        ciudad=ciudad,
        superficie_tipo=superficie,
        total_barrios=len(barrios),
        barrios=[b.to_dict() for b in barrios],
        criterio_orden=criterio,
        # Por su nombre, no por su posición: el orden de la tabla ya no es
        # siempre el de rentabilidad.
        mejor_rentabilidad=(max(barrios, key=lambda x: x.rentabilidad_neta).nombre
                            if barrios else None),
        mejor_cash_flow=max(barrios, key=lambda x: x.cash_flow_mensual).nombre if barrios else None,
        mas_barato=min(barrios, key=lambda x: x.precio_vivienda).nombre if barrios else None,
        supuestos={
            "superficie_m2": superficie,
            "entrada_pct": s.entrada_pct,
            "interes_anual": s.interes_anual,
            "anios_hipoteca": s.anios_hipoteca,
            "vacancia_pct": s.vacancia_pct,
            "nota": "Todos los barrios se comparan con la MISMA vivienda tipo: si no, "
                    "se estarían comparando tamaños distintos en lugar de zonas.",
        },
        precio_vs_alquiler=_precio_vs_alquiler(codigo_municipio),
        renta_municipio=renta_muni,
        avisos=avisos,
        fuentes={
            "precio_m2": "deteccion-zonas-revalorizacion (proyecto del portfolio): "
                         "valores DE REFERENCIA, no precios de mercado observados",
            "hipoteca": "sistema francés con el tipo del Banco de España",
            "impuestos": "ITP por comunidad, normativa citada en impuestos.py",
            "alquiler": "estimación por rentabilidad bruta de la provincia",
            "renta_hogar": renta_ine.Renta.fuente,
            "evolucion_alquiler": alquiler_ine.FUENTE_IPVA,
            "evolucion_precio_compra": alquiler_ine.FUENTE_IPV,
        },
    )
