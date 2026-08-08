"""
Tests del motor financiero y del evaluador de riesgo.

No tocan la red: el BOE y el Catastro se prueban a mano contra el servicio real
(ver README), porque un test que dependa de que haya subastas activas en Madrid
fallaría un lunes cualquiera por motivos ajenos al código.

Lo que sí se prueba aquí es lo que puede romperse en silencio y arruinar una
decisión de compra: las fórmulas y la detección de riesgos.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rentabilidad import (analizar, cuota_hipoteca, itp_de_provincia,
                          precio_maximo_para_cash_flow, Supuestos)
from riesgo import evaluar

fallos = []


def check(condicion, descripcion):
    print(f"  {'✓' if condicion else '✗'} {descripcion}")
    if not condicion:
        fallos.append(descripcion)


print("\n=== 1) Cuota hipotecaria (sistema francés) ===")
# Contrastado con calculadoras bancarias: 200.000 € al 3% a 30 años ≈ 843,21 €
check(abs(cuota_hipoteca(200_000, 0.03, 30) - 843.21) < 0.5, "200k/3%/30a ≈ 843,21 €")
check(cuota_hipoteca(120_000, 0.0, 10) == 1000.0, "interés 0% reparte el principal")
check(cuota_hipoteca(0, 0.03, 25) == 0.0, "principal 0 → cuota 0")
check(cuota_hipoteca(100_000, 0.05, 30) > cuota_hipoteca(100_000, 0.03, 30),
      "más interés, más cuota")
check(cuota_hipoteca(100_000, 0.03, 15) > cuota_hipoteca(100_000, 0.03, 30),
      "menos años, más cuota")

print("\n=== 2) ITP por comunidad ===")
check(itp_de_provincia("madrid") == 0.06, "Madrid 6%")
check(itp_de_provincia("barcelona") == 0.10, "Barcelona (Cataluña) 10%")
check(itp_de_provincia("valencia") == 0.10, "Valencia 10%")
check(itp_de_provincia(None) == 0.08, "sin provincia → tipo por defecto")
check(itp_de_provincia("marte") == 0.08, "provincia desconocida → tipo por defecto")

print("\n=== 3) La rentabilidad neta siempre por debajo de la bruta ===")
a = analizar(150_000, 900, "madrid")
check(a.rentabilidad_neta < a.rentabilidad_bruta, "neta < bruta")
check(a.inversion_total > a.precio_compra, "la inversión incluye impuestos y gastos")
check(abs(a.itp - 9_000) < 1, "ITP de 150k en Madrid = 9.000 €")
check(a.ingresos_anuales_efectivos < a.ingresos_anuales_brutos, "la vacancia descuenta ingresos")
check(a.capital_aportado < a.inversion_total, "con hipoteca no se aporta todo")

print("\n=== 4) El mismo piso rinde distinto según la comunidad ===")
mad = analizar(150_000, 900, "madrid")
cat = analizar(150_000, 900, "barcelona")
check(cat.itp > mad.itp, "Cataluña cobra más ITP que Madrid")
check(cat.rentabilidad_neta < mad.rentabilidad_neta, "más impuesto, menos rentabilidad")

print("\n=== 5) Precio máximo para no perder dinero ===")
techo = precio_maximo_para_cash_flow(900, 0.0, "madrid")
cf_en_techo = analizar(techo, 900, "madrid").cash_flow_mensual
check(abs(cf_en_techo) < 1.0, f"en el techo ({techo:,.0f} €) el cash-flow es ~0")
check(analizar(techo * 1.2, 900, "madrid").cash_flow_mensual < 0, "por encima del techo se pierde")
check(analizar(techo * 0.8, 900, "madrid").cash_flow_mensual > 0, "por debajo del techo se gana")

print("\n=== 6) Sin hipoteca no hay cuota ===")
sin_hipoteca = analizar(150_000, 900, "madrid", Supuestos(entrada_pct=1.0))
check(sin_hipoteca.cuota_mensual == 0.0, "entrada del 100% → cuota 0")
check(sin_hipoteca.hipoteca == 0.0, "entrada del 100% → sin préstamo")
check(sin_hipoteca.cash_flow_mensual > a.cash_flow_mensual, "sin cuota, más cash-flow")

print("\n=== 7) Entradas inválidas ===")
try:
    analizar(0, 900)
    check(False, "precio 0 debe lanzar error")
except ValueError:
    check(True, "precio 0 lanza ValueError")

print("\n=== 8) Riesgo: lo que de verdad hace perder dinero ===")
critica = evaluar({"situacion_posesoria": "Ocupante desconocido", "visitable": "No consta",
                   "vivienda_habitual": "Sí", "valor_subasta": 100_000},
                  {"es_vivienda": True, "participacion": 100.0})
codigos = {r["codigo"] for r in critica.riesgos}
check("ocupante_desconocido" in codigos, "detecta ocupante desconocido")
check("no_visitable" in codigos, "detecta que no se puede visitar")
check("vivienda_habitual" in codigos, "detecta vivienda habitual del deudor")
check(critica.nivel == "critico", "el conjunto se califica como crítico")

limpia = evaluar({"situacion_posesoria": "Libre de ocupantes", "visitable": "Sí",
                  "vivienda_habitual": "No", "valor_subasta": 100_000},
                 {"es_vivienda": True, "participacion": 100.0})
check(limpia.puntuacion == 0, "una subasta limpia puntúa 0")
check(limpia.nivel == "bajo", "y se califica de riesgo bajo")

parcial = evaluar({"situacion_posesoria": "Libre", "visitable": "Sí", "valor_subasta": 100_000},
                  {"es_vivienda": True, "participacion": 50.0})
check(any(r["codigo"] == "participacion_parcial" for r in parcial.riesgos),
      "detecta que sólo se subasta una parte indivisa")

cargas = evaluar({"situacion_posesoria": "Libre", "visitable": "Sí", "valor_subasta": 100_000,
                  "descripcion": "Existen cargas anteriores no canceladas"},
                 {"es_vivienda": True, "participacion": 100.0})
check(any(r["codigo"] == "cargas_mencionadas" for r in cargas.riesgos),
      "detecta cargas mencionadas en la descripción")

deuda = evaluar({"situacion_posesoria": "Libre", "visitable": "Sí",
                 "valor_subasta": 100_000, "cantidad_reclamada": 150_000},
                {"es_vivienda": True, "participacion": 100.0})
check(any(r["codigo"] == "deuda_supera_valor" for r in deuda.riesgos),
      "detecta deuda superior al valor del inmueble")

print("\n=== 9) El checklist se adapta al caso ===")
check(len(critica.checklist) > len(limpia.checklist),
      "una subasta con riesgos exige más comprobaciones")
check(any("nota simple" in c["item"].lower() for c in limpia.checklist),
      "la nota simple se pide siempre")

print(f"\n{'='*54}")
print(f"  {'TODO OK' if not fallos else 'FALLOS: ' + str(len(fallos))}"
      f" — {len(fallos)} fallo(s)")
if fallos:
    for f in fallos:
        print(f"    ✗ {f}")
sys.exit(1 if fallos else 0)
