"""
Comparación de zonas de inversión, sólo con datos medidos.

Esta vista existía antes y comparaba barrios de una ciudad. La cambié porque los
números de los que partía —el €/m² y la tendencia de cada barrio— estaban
escritos a mano en el proyecto de detección de zonas, que además entrena con
datos sintéticos. Etiquetarlos como «de referencia» no arreglaba el fondo: la
tabla ordenaba barrios por una cifra inventada.

Lo que compara ahora son **municipios de una provincia**, que es el grano al que
existen datos publicados, y con cuatro fuentes oficiales:

  - **Alquiler**: mediana real del municipio, de los arrendamientos declarados a
    la Agencia Tributaria, con su horquilla P25-P75 y su superficie mediana. En
    Cataluña se prefiere el alquiler de los contratos nuevos, que es lo que
    cobraría de verdad quien compre hoy.
  - **Precio de compra**: valor tasado oficial en €/m² **de cada municipio**. La
    media provincial se queda corta en las capitales y se pasa en la periferia
    —Madrid capital 5.466 €/m² frente a Móstoles 3.026, con una media provincial
    de 4.048 que no describe a ninguno—, así que sólo se usa para los municipios
    de menos de 25.000 habitantes, que son los que el ministerio no desglosa.
  - **Renta del hogar** (INE, Atlas), que da el esfuerzo del inquilino. Esta
    métrica es ahora enteramente real: alquiler medido dividido por renta medida.
  - **Evolución del alquiler** (INE, IPVA), que dice hacia dónde va cada uno.

Se perdió el detalle por barrio, que no era real, y se ganó cobertura: 163
municipios sólo en Madrid, frente a los 23 barrios inventados de antes. Para
Madrid y Barcelona se conserva el desglose por distrito censal en lo que sí está
medido —renta y evolución del alquiler— a través de `contexto_distritos`.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from statistics import median

import alquiler_ine
import alquiler_real
import distritos as distritos_ine
import precio_compra
import renta_ine
from formato import euros
from rentabilidad import Supuestos, analizar

# Vivienda tipo sobre la que se compara. Comparar municipios exige que TODOS usen
# la misma, o se estarían comparando tamaños en lugar de zonas.
SUPERFICIE_TIPO = 80

PROVINCIAS = {
    "01": "Álava", "02": "Albacete", "03": "Alicante", "04": "Almería", "05": "Ávila",
    "06": "Badajoz", "07": "Baleares", "08": "Barcelona", "09": "Burgos", "10": "Cáceres",
    "11": "Cádiz", "12": "Castellón", "13": "Ciudad Real", "14": "Córdoba",
    "15": "A Coruña", "16": "Cuenca", "17": "Girona", "18": "Granada",
    "19": "Guadalajara", "20": "Gipuzkoa", "21": "Huelva", "22": "Huesca", "23": "Jaén",
    "24": "León", "25": "Lleida", "26": "La Rioja", "27": "Lugo", "28": "Madrid",
    "29": "Málaga", "30": "Murcia", "31": "Navarra", "32": "Ourense", "33": "Asturias",
    "34": "Palencia", "35": "Las Palmas", "36": "Pontevedra", "37": "Salamanca",
    "38": "Santa Cruz de Tenerife", "39": "Cantabria", "40": "Segovia", "41": "Sevilla",
    "42": "Soria", "43": "Tarragona", "44": "Teruel", "45": "Toledo", "46": "Valencia",
    "47": "Valladolid", "48": "Bizkaia", "49": "Zamora", "50": "Zaragoza",
    "51": "Ceuta", "52": "Melilla",
}
_POR_NOMBRE = {n.lower(): c for c, n in PROVINCIAS.items()}
_ALIAS = {"vizcaya": "48", "guipuzcoa": "20", "la coruña": "15", "coruña": "15",
          "gerona": "17", "lerida": "25", "lérida": "25", "islas baleares": "07",
          "alacant": "03", "valència": "46", "castello": "12", "castelló": "12",
          "araba": "01", "tenerife": "38", "rioja": "26"}


@dataclass
class Municipio:
    codigo_ine: str
    nombre: str
    alquiler_mensual: float
    alquiler_m2_mes: float
    alquiler_base: str
    alquiler_anio: int
    horquilla_municipio: dict
    viviendas_alquiladas: int | None
    precio_m2_compra: float
    precio_es_municipal: bool
    precio_vivienda: float
    cuota_hipoteca_mensual: float
    rentabilidad_bruta: float
    rentabilidad_neta: float
    cash_flow_mensual: float
    capital_necesario: float
    anios_recuperar: float | None
    renta_hogar_anual: float | None = None
    esfuerzo_inquilino_pct: float | None = None
    alquiler_var_anual_pct: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AnalisisZonas:
    provincia: str
    codigo_provincia: str
    superficie_tipo: int
    total_municipios: int
    municipios: list[dict] = field(default_factory=list)
    criterio_orden: str = ""
    precio_compra_provincial: dict | None = None
    mejor_rentabilidad: str | None = None
    mejor_cash_flow: str | None = None
    alquiler_mas_alto: str | None = None
    supuestos: dict = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)
    fuentes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def codigo_de_provincia(provincia: str) -> str | None:
    """Acepta el código INE de dos dígitos o el nombre, con sus variantes."""
    p = (provincia or "").strip().lower()
    if p.zfill(2) in PROVINCIAS:
        return p.zfill(2)
    return _POR_NOMBRE.get(p) or _ALIAS.get(p)


def provincias_disponibles() -> list[dict]:
    return [{"codigo": c, "nombre": n} for c, n in sorted(PROVINCIAS.items(),
                                                          key=lambda x: x[1])]


def _renta_de(codigo_provincia: str) -> dict:
    """{codigo_municipio: renta del hogar} de toda la provincia, de una vez."""
    try:
        return {c: d.get("hogar")
                for c, d in renta_ine._carga_provincia(codigo_provincia).items()
                if d.get("hogar")}
    except Exception:
        return {}


def analizar_zonas(provincia: str = "madrid", superficie: int = SUPERFICIE_TIPO,
                   s: Supuestos | None = None, limite: int = 40) -> AnalisisZonas:
    """Compara los municipios de una provincia como inversión de alquiler."""
    s = s or Supuestos()
    cp = codigo_de_provincia(provincia)
    if not cp:
        return AnalisisZonas(provincia=provincia, codigo_provincia="", superficie_tipo=superficie,
                             total_municipios=0,
                             avisos=[f"No reconozco la provincia «{provincia}». Usa el "
                                     "nombre o su código INE de dos dígitos."])
    nombre_provincia = PROVINCIAS[cp]

    precio = precio_compra.precio_provincia(cp)
    if precio.error or not precio.euros_m2:
        return AnalisisZonas(provincia=nombre_provincia, codigo_provincia=cp,
                             superficie_tipo=superficie, total_municipios=0,
                             avisos=[f"Sin precio de compra publicado para {nombre_provincia}: "
                                     f"{precio.error}"])

    crudos = alquiler_real.municipios_de_provincia(cp)
    if not crudos:
        return AnalisisZonas(provincia=nombre_provincia, codigo_provincia=cp,
                             superficie_tipo=superficie, total_municipios=0,
                             avisos=[f"El ministerio no publica alquileres de ningún "
                                     f"municipio de {nombre_provincia}."])

    rentas = _renta_de(cp)
    precios_municipales = precio_compra.municipios_con_precio()

    municipios: list[Municipio] = []
    for m in crudos[:limite]:
        # El alquiler de los contratos nuevos, donde lo haya, manda sobre el del
        # parque: es lo que cobraría quien compre ahora.
        importe, origen = alquiler_real.alquiler_estimado_de(m["codigo_ine"], superficie)
        if not importe:
            continue

        # El precio del municipio manda sobre el de la provincia. La media
        # provincial se queda corta en las capitales y se pasa en la periferia:
        # Madrid capital está a 5.466 €/m² y Móstoles a 3.026, con una media
        # provincial de 4.048 que no describe a ninguno de los dos.
        euros_m2 = precios_municipales.get(m["codigo_ine"])
        precio_vivienda = (euros_m2 or precio.euros_m2) * superficie

        a = analizar(precio_vivienda, importe, nombre_provincia, s)
        renta = rentas.get(m["codigo_ine"])
        tendencia = alquiler_ine.tendencia_alquiler_municipio(m["codigo_ine"])

        municipios.append(Municipio(
            codigo_ine=m["codigo_ine"],
            nombre=m["nombre"],
            alquiler_mensual=importe,
            alquiler_m2_mes=origen["euros_m2_mes"],
            alquiler_base=origen["base"],
            alquiler_anio=origen["anio"],
            horquilla_municipio=origen["horquilla_municipio"],
            viviendas_alquiladas=m.get("viviendas"),
            precio_m2_compra=round(euros_m2 or precio.euros_m2, 2),
            precio_es_municipal=euros_m2 is not None,
            precio_vivienda=round(precio_vivienda, 2),
            cuota_hipoteca_mensual=a.cuota_mensual,
            rentabilidad_bruta=a.rentabilidad_bruta,
            rentabilidad_neta=a.rentabilidad_neta,
            cash_flow_mensual=a.cash_flow_mensual,
            capital_necesario=a.capital_aportado,
            anios_recuperar=a.anios_recuperar_capital,
            renta_hogar_anual=renta,
            esfuerzo_inquilino_pct=(round(importe * 12 / renta * 100, 1) if renta else None),
            alquiler_var_anual_pct=(None if tendencia.error else tendencia.variacion_anual_pct),
        ))

    municipios.sort(key=lambda x: -x.rentabilidad_neta)

    avisos = [
        "Todas las cifras de alquiler y renta son datos publicados, no estimaciones: "
        "el alquiler procede de los arrendamientos declarados a la Agencia Tributaria "
        "y la renta del Atlas del INE.",
        f"El precio de compra es el valor tasado oficial de CADA municipio "
        f"({precio.anio}T{precio.trimestre}), no una media provincial. Donde el "
        f"ministerio no lo publica —municipios de menos de 25.000 habitantes— se usa "
        f"el de la provincia de {nombre_provincia} ({euros(precio.euros_m2)} €/m²) y la "
        "fila lo indica con `precio_es_municipal`.",
        f"Se comparan los {len(municipios)} municipios con más viviendas alquiladas de "
        "la provincia, que son sobre los que el dato es más sólido.",
    ]

    esfuerzos = [m.esfuerzo_inquilino_pct for m in municipios if m.esfuerzo_inquilino_pct]
    if esfuerzos:
        avisos.append(
            f"Esfuerzo del inquilino típico en esta provincia: {median(esfuerzos):.0f} % "
            "de la renta del hogar. Por encima del 30 % la morosidad deja de ser una "
            "hipótesis, y aquí ambos números están medidos."
        )
    if cp in {"08", "17", "25", "43"}:
        avisos.append(
            "En Cataluña el alquiler usado es el de los CONTRATOS NUEVOS, del registro "
            "de fianzas, que va por encima del parque ya alquilado y es lo que cobraría "
            "quien compre ahora."
        )

    return AnalisisZonas(
        provincia=nombre_provincia,
        codigo_provincia=cp,
        superficie_tipo=superficie,
        total_municipios=len(municipios),
        municipios=[m.to_dict() for m in municipios],
        criterio_orden="mayor rentabilidad neta a precio medio provincial",
        precio_compra_provincial=precio.to_dict(),
        mejor_rentabilidad=municipios[0].nombre if municipios else None,
        mejor_cash_flow=(max(municipios, key=lambda x: x.cash_flow_mensual).nombre
                         if municipios else None),
        alquiler_mas_alto=(max(municipios, key=lambda x: x.alquiler_m2_mes).nombre
                           if municipios else None),
        supuestos={
            "superficie_m2": superficie,
            "entrada_pct": s.entrada_pct,
            "interes_anual": s.interes_anual,
            "anios_hipoteca": s.anios_hipoteca,
            "vacancia_pct": s.vacancia_pct,
            "nota": "Todos los municipios se comparan con la MISMA vivienda tipo: si no, "
                    "se estarían comparando tamaños distintos en lugar de zonas.",
        },
        avisos=avisos,
        fuentes={
            "alquiler": alquiler_real.FUENTE_MIVAU,
            "alquiler_contratos_nuevos": alquiler_real.FUENTE_FIANZAS,
            "precio_compra": precio_compra.FUENTE,
            "renta_hogar": renta_ine.Renta.fuente,
            "evolucion_alquiler": alquiler_ine.FUENTE_IPVA,
            "hipoteca": "sistema francés con el tipo del Banco de España",
            "impuestos": "ITP por comunidad, normativa citada en impuestos.py",
        },
    )


def contexto_distritos(ciudad: str) -> dict:
    """Desglose por distrito censal de lo que sí está medido a ese grano.

    Sólo renta del hogar y evolución del alquiler: el nivel del alquiler y el
    precio de compra no se publican por distrito, y no se inventan.
    """
    codigo = distritos_ine.municipio_de(ciudad)
    if not codigo:
        return {
            "disponible": False,
            "motivo": f"El detalle por distrito sólo está verificado en "
                      f"{' y '.join(c.title() for c in distritos_ine.ciudades_con_distrito())}.",
        }

    filas = []
    for cod in alquiler_ine.distritos_de(codigo):
        renta = renta_ine.renta_distrito(cod)
        t = alquiler_ine.tendencia_alquiler_distrito(cod)
        filas.append({
            "codigo": cod,
            "nombre": distritos_ine.nombre_distrito(cod),
            "renta_hogar_anual": (renta or {}).get("renta_hogar_anual"),
            "alquiler_var_anual_pct": None if t.error else t.variacion_anual_pct,
            "alquiler_desde_2015_pct": None if t.error else t.acumulada_desde_base_pct,
        })
    filas.sort(key=lambda f: -(f["renta_hogar_anual"] or 0))

    return {
        "disponible": True,
        "ciudad": ciudad.title(),
        "codigo_municipio": codigo,
        "distritos": filas,
        "aviso": "Del distrito sólo se publican la renta del hogar y la evolución del "
                 "alquiler. El nivel del alquiler y el precio de compra no bajan de "
                 "municipio y provincia, así que no aparecen aquí.",
        "fuentes": {"renta": renta_ine.Renta.fuente,
                    "evolucion_alquiler": alquiler_ine.FUENTE_IPVA},
    }
