"""
Las métricas con las que decide quien vive de esto.

La rentabilidad neta dice si una operación es buena. Estas métricas dicen si es
**segura**, que es la pregunta que se hace quien ya tiene patrimonio y lo que
teme no es ganar poco, sino quedarse atrapado en un activo ilíquido con una
deuda encima.

  - **DSCR**: cuántas veces cubre el alquiler la cuota. Es el número que mira un
    banco antes de prestar, y por debajo de 1,25 la operación aprieta.
  - **Punto muerto de ocupación**: cuántos meses puede estar vacío el piso al
    año antes de que la operación entre en pérdidas. Un inversor no piensa «se
    alquilará»: piensa «cuánto aguanto si no se alquila».
  - **Estrés de tipos**: qué pasa con una hipoteca variable si el Euríbor sube.
    Entre 2021 y 2023 subió más de cuatro puntos.
  - **Esfuerzo del inquilino**: el alquiler frente a la renta real del barrio.
    Si supera el 35 %, no es que el inquilino no quiera pagar: es que no puede.
    Predice impagos y rotación mejor que cualquier otra cifra.
  - **PER inmobiliario**: años de alquiler bruto para pagar el inmueble. Sirve
    para comparar zonas y con otros activos.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field

from rentabilidad import Supuestos, analizar, cuota_hipoteca

# Umbrales de referencia del sector financiero e inmobiliario.
DSCR_COMODO, DSCR_JUSTO = 1.40, 1.25
ESFUERZO_SANO, ESFUERZO_LIMITE = 0.30, 0.35   # % de la renta del hogar en alquiler
SUBIDA_TIPOS_ESTRES = 0.02                    # +2 pp, escenario 2021-2023


@dataclass
class MetricasInversor:
    dscr: float
    dscr_veredicto: str
    meses_vacio_soportables: float
    ocupacion_minima_pct: float
    per_inmobiliario: float
    estres_tipos: dict
    esfuerzo_inquilino: dict | None
    coste_oportunidad: dict
    lecturas: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _veredicto_dscr(dscr: float) -> str:
    if dscr >= DSCR_COMODO:
        return "holgado"
    if dscr >= DSCR_JUSTO:
        return "ajustado"
    if dscr >= 1.0:
        return "justo: el alquiler apenas cubre la cuota"
    return "insuficiente: el alquiler no cubre la cuota"


def analizar_inversor(precio_compra: float, alquiler_mensual: float,
                      provincia: str | None = None, s: Supuestos | None = None,
                      renta_hogar_zona_anual: float | None = None,
                      rentabilidad_bono_10a: float = 0.032) -> MetricasInversor:
    """Métricas de solvencia y riesgo sobre una operación ya calculada."""
    s = s or Supuestos()
    base = analizar(precio_compra, alquiler_mensual, provincia, s)
    lecturas: list[str] = []

    # ── DSCR ────────────────────────────────────────────────────────────────
    # Se compara el ingreso ya descontados los gastos recurrentes con la cuota:
    # el alquiler bruto frente a la cuota da un DSCR engañosamente bueno.
    ingreso_operativo_mensual = (base.ingresos_anuales_efectivos - base.gastos_anuales) / 12
    dscr = (ingreso_operativo_mensual / base.cuota_mensual) if base.cuota_mensual else float("inf")
    dscr_txt = "sin hipoteca" if base.cuota_mensual == 0 else _veredicto_dscr(dscr)
    if base.cuota_mensual and dscr < DSCR_JUSTO:
        lecturas.append(
            f"El DSCR es {dscr:.2f}: por debajo del 1,25 que suele exigir un banco. "
            "Cualquier imprevisto —una derrama, dos meses vacío— lo convierte en pérdidas."
        )

    # ── Punto muerto de ocupación ───────────────────────────────────────────
    # ¿Cuántos meses puede estar vacío antes de que el año cierre en negativo?
    gastos_anuales_totales = base.gastos_anuales + base.cuota_mensual * 12 + base.irpf_estimado
    ingreso_mensual_pleno = base.alquiler_mensual
    meses_necesarios = (gastos_anuales_totales / ingreso_mensual_pleno) if ingreso_mensual_pleno else 12
    meses_vacio = max(0.0, 12 - meses_necesarios)
    ocupacion_minima = min(1.0, meses_necesarios / 12)
    if meses_vacio < 1:
        lecturas.append(
            f"Necesita estar alquilado {meses_necesarios:.1f} meses de cada 12 sólo para "
            "cubrir gastos. No hay margen para un mes vacío."
        )

    # ── Estrés de tipos ─────────────────────────────────────────────────────
    s_estres = Supuestos(**{**s.__dict__, "interes_anual": s.interes_anual + SUBIDA_TIPOS_ESTRES})
    con_estres = analizar(precio_compra, alquiler_mensual, provincia, s_estres)
    estres = {
        "escenario": f"Euríbor +{SUBIDA_TIPOS_ESTRES*100:.0f} puntos "
                     f"({s.interes_anual*100:.2f} % → {s_estres.interes_anual*100:.2f} %)",
        "cuota_actual": base.cuota_mensual,
        "cuota_estresada": con_estres.cuota_mensual,
        "incremento_mensual": round(con_estres.cuota_mensual - base.cuota_mensual, 2),
        "cash_flow_actual": base.cash_flow_mensual,
        "cash_flow_estresado": con_estres.cash_flow_mensual,
        "aguanta": con_estres.cash_flow_mensual >= 0,
    }
    if base.cash_flow_mensual >= 0 and con_estres.cash_flow_mensual < 0:
        lecturas.append(
            f"Con el tipo actual da {base.cash_flow_mensual:+,.0f} €/mes, pero si el Euríbor "
            f"sube 2 puntos pasa a {con_estres.cash_flow_mensual:+,.0f} €/mes. Entre 2021 y "
            "2023 subió más de cuatro."
        )

    # ── Esfuerzo del inquilino ──────────────────────────────────────────────
    esfuerzo = None
    if renta_hogar_zona_anual and renta_hogar_zona_anual > 0:
        ratio = (alquiler_mensual * 12) / renta_hogar_zona_anual
        esfuerzo = {
            "renta_hogar_zona_anual": round(renta_hogar_zona_anual, 2),
            "alquiler_anual": round(alquiler_mensual * 12, 2),
            "esfuerzo_pct": round(ratio, 4),
            "veredicto": ("sano" if ratio <= ESFUERZO_SANO
                          else "tenso" if ratio <= ESFUERZO_LIMITE else "inviable"),
        }
        if ratio > ESFUERZO_LIMITE:
            lecturas.append(
                f"Ese alquiler supone el {ratio*100:.0f} % de la renta media de los hogares "
                "de la zona. Por encima del 35 % el problema no es que el inquilino no "
                "quiera pagar, es que no puede: sube el impago y la rotación."
            )

    # ── PER inmobiliario y coste de oportunidad ─────────────────────────────
    per = round(base.inversion_total / (alquiler_mensual * 12), 1) if alquiler_mensual else 0.0
    prima = base.rentabilidad_neta - rentabilidad_bono_10a
    coste_oportunidad = {
        "rentabilidad_neta": base.rentabilidad_neta,
        "referencia_sin_riesgo": rentabilidad_bono_10a,
        "prima_de_riesgo": round(prima, 4),
        "veredicto": ("compensa el riesgo" if prima >= 0.02
                      else "prima escasa" if prima > 0 else "no compensa"),
    }
    if prima <= 0:
        lecturas.append(
            f"La rentabilidad neta ({base.rentabilidad_neta*100:.2f} %) no supera a la deuda "
            f"pública a 10 años ({rentabilidad_bono_10a*100:.2f} %), que no tiene ni "
            "inquilinos, ni derramas, ni riesgo de impago."
        )

    return MetricasInversor(
        dscr=round(dscr, 2) if base.cuota_mensual else 0.0,
        dscr_veredicto=dscr_txt,
        meses_vacio_soportables=round(meses_vacio, 1),
        ocupacion_minima_pct=round(ocupacion_minima, 4),
        per_inmobiliario=per,
        estres_tipos=estres,
        esfuerzo_inquilino=esfuerzo,
        coste_oportunidad=coste_oportunidad,
        lecturas=lecturas,
    )
