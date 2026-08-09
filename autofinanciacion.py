"""
La pregunta del proyecto: ¿este piso se paga solo?

Todo lo demás —el descuento sobre el valor tasado, la comparación de municipios,
el semáforo de riesgo— existe para llegar aquí. Un inversor que compra para
alquilar no quiere saber si hay rebaja: quiere saber si, una vez firmado, el
alquiler cubre la hipoteca y los gastos o si va a tener que poner dinero cada mes
durante veinticinco años.

Ese número ya se calculaba (`cash_flow_mensual`), pero estaba enterrado entre
otros veinte y sin veredicto. Aquí se responde de frente, y la respuesta tiene
tres formas posibles:

  - **Sí**, con la entrada que se ha supuesto.
  - **Sí, pero** hace falta poner más entrada; se dice cuánta exactamente.
  - **No se paga solo ni pagándolo al contado**, que ocurre cuando el alquiler no
    llega a cubrir ni siquiera IBI, comunidad, seguro, mantenimiento, vacancia e
    IRPF. Ahí no hay entrada que arregle nada, y conviene decirlo sin rodeos.

Y una cuarta respuesta que sólo se puede dar con datos reales: **cuándo** se
pagará solo. Un piso que hoy pierde 200 € al mes puede ponerse en positivo en
unos años, porque la cuota de una hipoteca a tipo fijo no se mueve y el alquiler
sí. Cuánto sube el alquiler no es una suposición: es el IPVA del INE, construido
con los contratos declarados a Hacienda, y se coge el de ese municipio concreto.
Si el municipio no tiene serie propia, se dice que no se puede proyectar en lugar
de usar una media inventada.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field

import alquiler_ine
from formato import euros
from rentabilidad import Supuestos, analizar

# Más allá de esto la proyección deja de significar nada: son treinta años de
# suponer que el alquiler sigue subiendo al mismo ritmo, y nadie sabe eso.
MAX_ANIOS_PROYECCION = 30

# Por debajo de este cash-flow mensual se considera que no se paga solo. Se deja
# en cero exacto: «se paga solo» significa que no pones dinero, no que pierdas
# poco.
OBJETIVO = 0.0


@dataclass
class Autofinanciacion:
    """Si el inmueble se paga solo, y con qué condiciones."""
    se_paga_solo: bool = False
    veredicto: str = ""
    cash_flow_mensual: float | None = None
    entrada_pct_usada: float | None = None
    entrada_minima_pct: float | None = None
    entrada_minima_euros: float | None = None
    capital_extra_necesario: float | None = None
    imposible_a_cualquier_entrada: bool = False
    anios_hasta_pagarse_solo: int | None = None
    proyeccion: dict | None = None
    explicacion: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def entrada_minima_para_cash_flow(precio_compra: float, alquiler_mensual: float,
                                  provincia: str | None = None,
                                  s: Supuestos | None = None,
                                  objetivo: float = OBJETIVO) -> dict:
    """Qué entrada hace falta para que el inmueble no cueste dinero cada mes.

    Se resuelve por bisección sobre el porcentaje de entrada. Más entrada baja la
    cuota, así que el cash-flow crece de forma monótona con ella y la bisección es
    exacta. El caso interesante es el borde: con entrada del 100 % no hay cuota
    ninguna, de modo que si ahí el cash-flow sigue siendo negativo es que el
    alquiler no cubre los gastos corrientes y no hay dinero que lo arregle.
    """
    s = s or Supuestos()

    def cash_flow(entrada_pct: float) -> float:
        supuestos = Supuestos(**{**vars(s), "entrada_pct": entrada_pct})
        return analizar(precio_compra, alquiler_mensual, provincia, supuestos).cash_flow_mensual

    al_contado = cash_flow(1.0)
    if al_contado < objetivo:
        return {
            "posible": False,
            "cash_flow_al_contado": round(al_contado, 2),
            "motivo": ("Ni pagándolo al contado se paga solo: el alquiler no cubre "
                       "los gastos corrientes (IBI, comunidad, seguro, mantenimiento, "
                       "vacancia e IRPF), y esos no dependen de la hipoteca."),
        }

    if cash_flow(0.0) >= objetivo:
        return {"posible": True, "entrada_pct": 0.0, "entrada_euros": 0.0,
                "nota": "Se paga solo incluso financiando el 100 %."}

    bajo, alto = 0.0, 1.0          # bajo: no llega; alto: sí llega
    for _ in range(40):
        medio = (bajo + alto) / 2
        if cash_flow(medio) >= objetivo:
            alto = medio
        else:
            bajo = medio

    supuestos = Supuestos(**{**vars(s), "entrada_pct": alto})
    a = analizar(precio_compra, alquiler_mensual, provincia, supuestos)
    return {"posible": True, "entrada_pct": round(alto, 4),
            "entrada_euros": round(a.capital_aportado, 2)}


def _crecimiento_alquiler(codigo_ine_municipio: str | None) -> dict | None:
    """Cuánto sube el alquiler al año en ese municipio, medido por el INE."""
    if not codigo_ine_municipio:
        return None
    t = alquiler_ine.tendencia_alquiler_municipio(codigo_ine_municipio)
    if t.error or t.variacion_anual_pct is None:
        return None
    return {"pct_anual": t.variacion_anual_pct, "anio": t.anio,
            "municipio": t.nombre, "fuente": t.fuente}


def analizar_autofinanciacion(precio_compra: float, alquiler_mensual: float,
                              provincia: str | None = None,
                              s: Supuestos | None = None,
                              codigo_ine_municipio: str | None = None) -> Autofinanciacion:
    """Responde: ¿este piso se paga solo? Y si no, qué haría falta y cuándo."""
    s = s or Supuestos()
    base = analizar(precio_compra, alquiler_mensual, provincia, s)
    cf = base.cash_flow_mensual

    r = Autofinanciacion(
        cash_flow_mensual=cf,
        entrada_pct_usada=s.entrada_pct,
        se_paga_solo=cf >= OBJETIVO,
    )

    if r.se_paga_solo:
        r.veredicto = (f"Sí: con una entrada del {s.entrada_pct*100:.0f} % deja "
                       f"{cf:+.0f} € al mes después de la hipoteca y de todos los gastos.")
        r.explicacion.append(
            "El alquiler cubre la cuota, el IBI, la comunidad, el seguro, el "
            "mantenimiento, la vacancia y el IRPF. No tienes que poner nada cada mes."
        )
        return r

    minima = entrada_minima_para_cash_flow(precio_compra, alquiler_mensual, provincia, s)
    if not minima["posible"]:
        r.imposible_a_cualquier_entrada = True
        r.veredicto = (f"No, y no hay entrada que lo arregle: te cuesta "
                       f"{abs(cf):.0f} € al mes y seguiría en negativo pagándolo "
                       "al contado.")
        r.explicacion.append(minima["motivo"])
        return r

    r.entrada_minima_pct = minima["entrada_pct"]
    r.entrada_minima_euros = minima["entrada_euros"]
    r.capital_extra_necesario = round(
        max(0.0, minima["entrada_euros"] - base.capital_aportado), 2)
    r.veredicto = (
        f"Todavía no: con una entrada del {s.entrada_pct*100:.0f} % te cuesta "
        f"{abs(cf):.0f} € al mes de tu bolsillo. Se pagaría solo con una entrada del "
        f"{minima['entrada_pct']*100:.0f} %."
    )
    r.explicacion.append(
        f"Son {euros(r.entrada_minima_euros)} € de tu bolsillo en total, "
        f"{euros(r.capital_extra_necesario)} € más de lo previsto."
    )

    # ¿Y si en lugar de poner más dinero, esperas? La cuota a tipo fijo no se
    # mueve; el alquiler sí, y cuánto lo dice el INE para ese municipio.
    crecimiento = _crecimiento_alquiler(codigo_ine_municipio)
    if crecimiento and crecimiento["pct_anual"] > 0:
        tasa = crecimiento["pct_anual"] / 100
        for anio in range(1, MAX_ANIOS_PROYECCION + 1):
            proyectado = alquiler_mensual * (1 + tasa) ** anio
            if analizar(precio_compra, proyectado, provincia, s).cash_flow_mensual >= OBJETIVO:
                r.anios_hasta_pagarse_solo = anio
                r.proyeccion = {
                    "alquiler_necesario": round(proyectado, 2),
                    "crecimiento_anual_pct": crecimiento["pct_anual"],
                    "anio_del_dato": crecimiento["anio"],
                    "fuente": crecimiento["fuente"],
                }
                r.explicacion.append(
                    f"Sin poner más entrada, se pagaría solo en {anio} año"
                    f"{'s' if anio > 1 else ''}: la cuota no se mueve y el alquiler "
                    f"de {crecimiento['municipio']} sube un "
                    f"{crecimiento['pct_anual']:.1f} % al año según el INE "
                    f"({crecimiento['anio']}). Es una proyección de esa tendencia, no "
                    "una promesa: si el alquiler se estanca, no llega."
                )
                break
        else:
            r.explicacion.append(
                f"Aunque el alquiler siga subiendo un {crecimiento['pct_anual']:.1f} % "
                f"al año como en {crecimiento['anio']}, no se pagaría solo en "
                f"{MAX_ANIOS_PROYECCION} años. La diferencia es demasiado grande."
            )
    else:
        r.explicacion.append(
            "No se puede proyectar cuándo se pagaría solo: el INE no publica la "
            "evolución del alquiler de este municipio, y ponerle una subida media "
            "inventada sería peor que no decir nada."
        )
    return r
