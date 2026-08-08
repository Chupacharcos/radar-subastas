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


print("\n=== 10) Tipos de ITP verificados contra la norma ===")
from impuestos import calcular_itp, REGIMENES

# Contrastados el 2026-08-08 con las haciendas autonómicas y publicaciones
# fiscales. Cantabria estaba mal en la primera versión (9% en vez de 10%).
esperados = {"madrid": 0.06, "navarra": 0.06, "canarias": 0.065, "andalucia": 0.07,
             "la rioja": 0.07, "aragon": 0.08, "asturias": 0.08, "murcia": 0.08,
             "castilla y leon": 0.08, "galicia": 0.09, "castilla-la mancha": 0.09,
             "cantabria": 0.10, "comunidad valenciana": 0.10, "pais vasco": 0.04}
for comunidad, tipo in esperados.items():
    r = calcular_itp(100_000, comunidad)
    check(abs(r["tipo_efectivo"] - tipo) < 0.0001,
          f"{comunidad}: {r['tipo_efectivo']*100:.2f} % (esperado {tipo*100:.2f} %)")

check(len(REGIMENES) == 17, f"las 17 comunidades cubiertas ({len(REGIMENES)})")
check(all(r.fuente for r in REGIMENES.values()), "cada tipo cita su norma")

print("\n=== 11) Escalas por tramos (no tipo plano) ===")
# Cataluña, Decreto Ley 5/2025: 10 % hasta 600k, 11 % hasta 900k, 12 % después.
bajo = calcular_itp(500_000, "barcelona")
medio = calcular_itp(800_000, "barcelona")
alto = calcular_itp(1_200_000, "barcelona")
check(abs(bajo["tipo_efectivo"] - 0.10) < 0.0001, "Cataluña bajo 600k → 10 %")
check(0.10 < medio["tipo_efectivo"] < 0.11, f"Cataluña 800k → efectivo {medio['tipo_efectivo']*100:.2f} % (entre 10 y 11)")
check(alto["tipo_efectivo"] > medio["tipo_efectivo"], "a más precio, más tipo efectivo")
check(bajo["escalonado"] is True, "Cataluña se marca como escalonada")
check(calcular_itp(200_000, "madrid")["escalonado"] is False, "Madrid es tipo plano")

print("\n=== 12) Aranceles proporcionales al precio ===")
from impuestos import gastos_compra
g1, g2 = gastos_compra(120_000), gastos_compra(800_000)
check(g2["total"] > g1["total"], "un inmueble caro paga más arancel")
check(g1["es_estimacion"] is True, "los aranceles se declaran como estimación")
check("1426/1989" in g1["fuente"], "se cita el RD de aranceles notariales")
check(gastos_compra(300_000, en_subasta=True)["total"] < gastos_compra(300_000, en_subasta=False)["total"],
      "en subasta el coste notarial es menor (no hay escritura de compraventa)")

print("\n=== 13) Provincia desconocida no revienta ===")
r = calcular_itp(150_000, "Terra Media")
check(r["cuota"] > 0, "una provincia inexistente usa el tipo por defecto")
check(calcular_itp(150_000, None)["cuota"] > 0, "sin provincia también calcula")


print("\n=== 14) Métricas de inversor ===")
from inversor import analizar_inversor
from rentabilidad import Supuestos as Sup

m = analizar_inversor(150_000, 900, "madrid", renta_hogar_zona_anual=31_000)
check(m.dscr > 0, f"DSCR calculado ({m.dscr})")
check(0 <= m.ocupacion_minima_pct <= 1, "la ocupación mínima es un porcentaje válido")
check(m.per_inmobiliario > 0, f"PER inmobiliario ({m.per_inmobiliario} años)")
check(m.estres_tipos["cuota_estresada"] > m.estres_tipos["cuota_actual"],
      "subir el tipo encarece la cuota")
check(m.estres_tipos["cash_flow_estresado"] < m.estres_tipos["cash_flow_actual"],
      "subir el tipo empeora el cash-flow")
check(m.esfuerzo_inquilino is not None, "calcula el esfuerzo del inquilino si hay renta de zona")
check(analizar_inversor(150_000, 900, "madrid").esfuerzo_inquilino is None,
      "sin renta de zona no se inventa el esfuerzo")

# Un alquiler desproporcionado para la zona debe saltar
caro = analizar_inversor(150_000, 1_500, "madrid", renta_hogar_zona_anual=24_000)
check(caro.esfuerzo_inquilino["veredicto"] == "inviable",
      f"esfuerzo del {caro.esfuerzo_inquilino['esfuerzo_pct']*100:.0f} % → inviable")
check(any("no puede" in l for l in caro.lecturas), "y lo explica en las lecturas")

sin_h = analizar_inversor(150_000, 900, "madrid", s=Sup(entrada_pct=1.0))
check(sin_h.dscr_veredicto == "sin hipoteca", "sin hipoteca no hay DSCR que evaluar")

print("\n=== 15) Contexto de zona ===")
from contexto_zona import evaluar_zona

bcn = evaluar_zona("Barcelona", "Barcelona", anio_construccion=1968)
check(bcn.zona_tensionada is True, "Barcelona se detecta como zona tensionada")
check(bcn.zona_tensionada_certeza == "confirmada", "y con certeza confirmada")
check(bcn.ite_situacion == "exigible", "un edificio de 1968 tiene ITE exigible")
check(any("1980" in f["factor"] for f in bcn.factores), "avisa de la eficiencia energética")

mad = evaluar_zona("Las Rozas de Madrid", "Madrid", anio_construccion=1995)
check(mad.zona_tensionada is False, "Las Rozas no es zona tensionada")
check(mad.ite_situacion == "no exigible aún", "un edificio de 1995 aún no pasa ITE")

girona = evaluar_zona("Un Pueblo Cualquiera", "Girona")
check(girona.zona_tensionada_certeza == "probable",
      "en provincia con declaraciones se marca como probable, no se afirma")

check(len(bcn.pendientes) >= 3, "declara qué datos faltan en lugar de inventarlos")

print(f"\n{'='*54}")
print(f"  {'TODO OK' if not fallos else 'FALLOS: ' + str(len(fallos))}"
      f" — {len(fallos)} fallo(s)")
if fallos:
    for f in fallos:
        print(f"    ✗ {f}")
sys.exit(1 if fallos else 0)
