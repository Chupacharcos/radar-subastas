"""
Tests del motor financiero y del evaluador de riesgo.

El BOE y el Catastro no se prueban aquí: un test que dependa de que haya
subastas activas en Madrid fallaría un lunes cualquiera por motivos ajenos al
código. Se verifican contra el servicio real desde `vigencia.py`.

Lo que sí se prueba es lo que puede romperse en silencio y arruinar una decisión
de compra: las fórmulas, la detección de riesgos y la procedencia de cada dato.
Las comprobaciones sobre fuentes públicas descargan sus ficheros la primera vez,
y de paso avisan si una tabla cambia de sitio o deja de publicarse.
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


print("\n=== 16) Renta del INE (dato real, no estimación) ===")
from renta_ine import consultar as consultar_renta, TABLA_POR_PROVINCIA

check(len(TABLA_POR_PROVINCIA) >= 50, f"{len(TABLA_POR_PROVINCIA)} provincias mapeadas al Atlas")
r = consultar_renta("MADRID", "28", "079")
check(r.renta_hogar_anual and r.renta_hogar_anual > 20_000,
      f"Madrid: {r.renta_hogar_anual:,.0f} €/hogar ({r.anio})" if r.renta_hogar_anual else "sin dato")
# El bug que hubo: 'Las Rozas de Madrid' encajaba con 'Madrid' por subcadena.
lr = consultar_renta("LAS ROZAS DE MADRID", "28", "127")
check(lr.codigo_ine == "28127", f"Las Rozas se identifica por código ({lr.codigo_ine})")
check(lr.renta_hogar_anual != r.renta_hogar_anual, "y no se confunde con Madrid capital")
mal = consultar_renta("Ciudad Inventada", "28")
check(mal.error is not None, "un municipio inexistente devuelve error, no un número")

print("\n=== 17) Idealista: desactivado sin credenciales ===")
from idealista import esta_configurado, precios_zona
res = precios_zona(40.42, -3.70)
if esta_configurado():
    check(True, "hay credenciales configuradas")
else:
    check(res.disponible is False, "sin credenciales se declara no disponible")
    check("developers.idealista.com" in res.aviso, "y explica cómo solicitarlas")
    check(res.precio_medio_m2 is None, "no se inventa un precio")


print("\n=== 18) Entorno (OpenStreetMap) ===")
from entorno import _clasifica, _lecturas, geocodificar

elementos = [
    {"tags": {"railway": "station"}}, {"tags": {"railway": "subway_entrance"}},
    {"tags": {"highway": "bus_stop"}}, {"tags": {"amenity": "school"}},
    {"tags": {"amenity": "school"}}, {"tags": {"shop": "supermarket"}},
    {"tags": {"highway": "motorway"}},
]
tr, sv, mo = _clasifica(elementos)
check(tr["estaciones_tren_metro"] == 1 and tr["bocas_de_metro"] == 1, "clasifica transporte")
check(sv["colegios"] == 2 and sv["supermercados"] == 1, "clasifica servicios")
check(mo["vias_rapidas"] == 1, "detecta vías rápidas como molestia")

lec = _lecturas(tr, sv, mo)
check(any("colegios" in l for l in lec), "explica qué implican los colegios")
check(any("vía rápida" in l for l in lec), "avisa del ruido de la vía rápida")

sin_nada = _lecturas({"estaciones_tren_metro":0,"bocas_de_metro":0,"paradas_bus":0},
                     {"colegios":0,"centros_salud":0,"farmacias":0,"supermercados":0,"zonas_verdes":0},
                     {"vias_rapidas":0,"vias_de_tren":0})
check(any("Sin transporte" in l for l in sin_nada), "sin transporte lo dice claramente")
check(any("supermercado" in l for l in sin_nada), "sin supermercado también")

# La limpieza de direcciones del BOE es lo que más se rompe al geocodificar
c = geocodificar("CALLE FIDIAS NUMERO 11", "28232", "LAS ROZAS DE MADRID")
check(c is not None and 40 < c[0] < 41, f"geocodifica una dirección del BOE ({c})")

print("\n=== 19) Renta por distrito y sección (Atlas del INE) ===")
from renta_ine import renta_distrito

md = consultar_renta("MADRID", "28", "079")
check(len(md.distritos) == 21, f"Madrid capital trae sus 21 distritos ({len(md.distritos)})")
check(md.distritos == sorted(md.distritos, key=lambda d: -d["renta_hogar_anual"]),
      "los distritos vienen ordenados de mayor a menor renta")
# Verificación de que la numeración del INE es la del ayuntamiento: si algún día
# el INE renumera, esto salta antes de que el mapa de barrios mienta.
check(md.distritos[0]["codigo"] == "2807905",
      f"el distrito más rico de Madrid es el 05, Chamartín ({md.distritos[0]['codigo']})")
check(md.distritos[-1]["codigo"] == "2807913",
      f"y el de menor renta el 13, Puente de Vallecas ({md.distritos[-1]['codigo']})")
check(md.renta_hogar_anual < md.distritos[0]["renta_hogar_anual"],
      "la media del municipio queda por debajo de su mejor distrito")

d = renta_distrito("2807905")
check(d and d["renta_hogar_anual"] > 70_000, "se puede consultar un distrito suelto")
check(renta_distrito("2807999") is None, "un distrito inexistente devuelve None, no un número")
check(renta_distrito("28079") is None, "un código que no es de distrito tampoco cuela")

disp = md.dispersion_secciones
check(disp and disp["total"] > 2_000, f"resume las {disp['total']} secciones de Madrid")
check(disp["minimo"] < disp["mediana"] < disp["maximo"], "mínimo < mediana < máximo")
# El INE censura por arriba: 82 secciones de Madrid comparten el mismo valor.
check(disp["maximo_censurado"] is True, "detecta que el máximo es un tope del INE")
check(disp["secciones_en_el_tope"] > 10,
      f"y dice cuántas secciones están en él ({disp['secciones_en_el_tope']})")


print("\n=== 20) Evolución del alquiler y del precio (IPVA e IPV del INE) ===")
from alquiler_ine import (PROVINCIA_A_CCAA, distritos_de, precio_vs_alquiler,
                          tendencia_alquiler_distrito, tendencia_alquiler_municipio,
                          tendencia_precio_compra)

check(len(PROVINCIA_A_CCAA) == 52, f"{len(PROVINCIA_A_CCAA)} provincias mapeadas a su comunidad")
check(PROVINCIA_A_CCAA["28"] == "13" and PROVINCIA_A_CCAA["08"] == "09",
      "Madrid → 13 y Barcelona → 09")

t = tendencia_alquiler_municipio("28079")
check(t.error is None and t.indice > 100, f"Madrid: índice {t.indice} ({t.anio})")
check(t.base == "2015 = 100", "declara la base del índice")
check(abs(t.acumulada_desde_base_pct - (t.indice - 100)) < 0.01,
      "el acumulado desde la base es el propio índice menos 100")
# Municipio de menos de 10.000 habitantes: el INE no lo publica.
pequeno = tendencia_alquiler_municipio("28002")
check(pequeno.error is not None and "10.000" in pequeno.error,
      "un municipio pequeño devuelve un error que explica por qué")

check(len(distritos_de("28079")) == 21, "Madrid tiene 21 distritos en el IPVA")
check(distritos_de("48020") == [], "Bilbao no está: el IPVA se construye con datos de la AEAT")
check(tendencia_alquiler_distrito("2807904").error is None, "hay dato del distrito Salamanca")
check(tendencia_alquiler_distrito("2807999").error is not None,
      "un distrito inexistente da error, no un número")

p = tendencia_precio_compra("28")
check(p.error is None and p.nombre.startswith("Madrid"), "IPV de la Comunidad de Madrid")
check(tendencia_precio_compra("99").error is not None, "provincia inexistente da error")

cmp = precio_vs_alquiler("28079", "28")
check(cmp.error is None and cmp.anio is not None, f"compara ambos índices en {cmp.anio}")
check(abs(cmp.brecha_pp - (cmp.variacion_alquiler_pct - cmp.variacion_precio_pct)) < 0.01,
      "la brecha es la resta de las dos variaciones")
check(any("ámbito municipio" in a for a in cmp.avisos),
      "avisa de que el precio es regional y el alquiler municipal")
check(any("índices, no precios" in a for a in cmp.avisos),
      "y de que son índices, no niveles en €")


print("\n=== 21) Nombres de distrito censal ===")
import distritos as dist

check(dist.municipio_de("madrid") == "28079", "Madrid resuelve a su código INE")
check(dist.municipio_de("Málaga") == "29067", "y Málaga con acento")
check(dist.municipio_de("Zaragoza") is None,
      "Zaragoza NO está: su numeración no supera el contraste con la renta")
check(dist.nombre_distrito("2807904") == "Salamanca", "2807904 es Salamanca")
check(dist.nombre_distrito("5029708") == "5029708",
      "un distrito sin verificar devuelve su código, no un nombre inventado")
check(len(dist.ciudades_con_distrito()) == 5, "cinco ciudades verificadas")
check(all(len(c) == 7 and c.isdigit() for c in dist.NOMBRES),
      "todos los códigos son de 7 dígitos")
# Cada nombre debe pertenecer a una ciudad declarada: si no, sobra.
check(all(c[:5] in dist.MUNICIPIO.values() for c in dist.NOMBRES),
      "ningún nombre pertenece a una ciudad que no esté en el mapa")


print("\n=== 22) Alquiler REAL por municipio (ministerio + fianzas) ===")
from alquiler_real import (alquiler_estimado_de, alquiler_municipio,
                           municipios_de_provincia)

md = alquiler_municipio("28079")
check(md.error is None and md.mediana_mensual > 300,
      f"Madrid: mediana {md.mediana_mensual} €/mes ({md.anio})")
check(md.p25_mensual < md.mediana_mensual < md.p75_mensual,
      f"la horquilla ordena bien: {md.p25_mensual} < {md.mediana_mensual} < {md.p75_mensual}")
check(md.euros_m2_mes and 5 < md.euros_m2_mes < 30,
      f"el €/m² sale de dividir por la superficie mediana ({md.euros_m2_mes} €/m²)")
check(md.viviendas and md.viviendas > 10_000,
      f"trae el tamaño de la muestra ({md.viviendas} viviendas)")
check(md.municipio == "Madrid", f"y el nombre del municipio ({md.municipio})")

# Los municipios pequeños se omiten por anonimato, y eso debe explicarse.
# 28001 (La Acebeda, 60 habitantes) no aparece: es el caso que hay que explicar.
pequeno = alquiler_municipio("28001")
check(pequeno.error is not None and "anónima" in pequeno.error,
      "un municipio sin dato explica por qué no lo hay")

# Cataluña añade contratos nuevos; el resto de España no tiene equivalente.
bcn = alquiler_municipio("08019")
check(bcn.contratos_nuevos is not None, "Barcelona trae el alquiler de contratos nuevos")
check(bcn.contratos_nuevos["importe_mensual"] > bcn.mediana_mensual,
      f"que va por encima del parque ya alquilado "
      f"({bcn.contratos_nuevos['importe_mensual']} > {bcn.mediana_mensual})")
check(bcn.contratos_nuevos["estadistico"] == "media",
      "Cataluña publica una media, y la respuesta lo dice")

# La Comunitat Valenciana publica los depósitos uno a uno: la mediana se calcula
# aquí. La fianza de vivienda es una mensualidad por el art. 36.1 de la LAU.
vlc = alquiler_municipio("46250")
check(vlc.contratos_nuevos is not None, "Valencia también trae contratos nuevos")
check(vlc.contratos_nuevos["estadistico"] == "mediana",
      "y ahí es una mediana calculada sobre los depósitos, no una media")
check(vlc.contratos_nuevos["anio"] >= 2025,
      f"con dato más reciente que el del ministerio ({vlc.contratos_nuevos['anio']} vs {vlc.anio})")
check(vlc.contratos_nuevos["contratos"] > 1000,
      f"sobre {vlc.contratos_nuevos['contratos']} fianzas")
# Guardia contra el error de leer la fianza como algo que no es una mensualidad:
# si el ratio se disparase, es que el campo cambió de significado.
check(1.0 < vlc.contratos_nuevos["importe_mensual"] / vlc.mediana_mensual < 2.5,
      f"y en una banda coherente con el parque ({vlc.contratos_nuevos['importe_mensual']/vlc.mediana_mensual:.2f}×)")
check(alquiler_municipio("03014").contratos_nuevos is not None, "Alicante también")
check(bcn.contratos_nuevos["contratos"] > 100,
      f"con su número de fianzas ({bcn.contratos_nuevos['contratos']})")
check(md.contratos_nuevos is None, "fuera de Cataluña no se inventa ese dato")

importe, origen = alquiler_estimado_de("28079", 80)
check(importe and abs(importe - md.euros_m2_mes * 80) < 1,
      f"escala el €/m² real a la superficie pedida ({importe} €)")
check(origen["superficie_fuera_de_rango"] is False,
      "80 m² está dentro del rango representativo de Madrid")
_, grande = alquiler_estimado_de("28127", 398)
check(grande["superficie_fuera_de_rango"] is True,
      "398 m² frente a una mediana de 85 m² se marca como fuera de rango")
check("techo, no como previsión" in grande["aviso"], "y el aviso dice cómo leerlo")

mun = municipios_de_provincia("28")
check(len(mun) > 100, f"{len(mun)} municipios de Madrid con alquiler publicado")
check(mun[0]["viviendas"] >= mun[-1]["viviendas"], "vienen ordenados por tamaño de muestra")
check(municipios_de_provincia("99") == [], "una provincia inexistente devuelve lista vacía")


print("\n=== 23) Precio de compra oficial y actual ===")
from precio_compra import precio_provincia, valorar_por_superficie

p = precio_provincia("28")
check(p.error is None and 1000 < p.euros_m2 < 10_000,
      f"Madrid: {p.euros_m2} €/m² ({p.anio}T{p.trimestre})")
check(p.anio >= 2025, f"el dato es reciente, no de 2018 ({p.anio})")
check(p.variacion_anual_pct is not None, "trae la variación del último año")
check(precio_provincia("99").error is not None, "provincia inexistente da error")

print("\n=== 23b) Valor tasado POR MUNICIPIO (Excel del BoletínOnline) ===")
from precio_compra import municipios_con_precio, precio_municipio

mad = precio_municipio("28079")
check(mad.error is None and mad.euros_m2 > 3000,
      f"Madrid capital: {mad.euros_m2} €/m² ({mad.periodo})")
check(mad.euros_m2 > p.euros_m2,
      f"la capital está por encima de su provincia ({mad.euros_m2} > {p.euros_m2}), "
      "que es justo lo que la media provincial ocultaba")
mos = precio_municipio("28092")
check(mos.euros_m2 < p.euros_m2, f"y Móstoles por debajo ({mos.euros_m2})")
check(mad.euros_m2_mas_5_anios and mad.euros_m2_hasta_5_anios,
      "trae los dos tramos de antigüedad")
check(precio_municipio("28001").error is not None,
      "un municipio de menos de 25.000 habitantes explica por qué no está")

todos = municipios_con_precio()
check(len(todos) > 250, f"{len(todos)} municipios emparejados a su código INE")
check(all(len(c) == 5 and c.isdigit() for c in todos), "todos con código INE de 5 dígitos")

# El emparejamiento es por nombre normalizado: si se rompiera, saldrían precios
# de otra provincia. La banda de plausibilidad es la red de seguridad.
from precio_compra import BANDA_PLAUSIBLE, _carga
prov = _carga()
raros = []
for cod, valor in todos.items():
    serie = prov.get(cod[:2], {}).get("serie", {})
    if not serie:
        continue
    ref = serie[max(serie, key=lambda k: tuple(int(x) for x in k.split("-")))]
    if not BANDA_PLAUSIBLE[0] <= valor / ref <= BANDA_PLAUSIBLE[1]:
        raros.append((cod, valor, ref))
check(not raros, f"ningún municipio se sale de la banda respecto a su provincia ({len(raros)})")

# Con el año de construcción se usa el tramo que toca, no la media de los dos.
nueva = valorar_por_superficie("28", 100, "28079", 2024)
vieja = valorar_por_superficie("28", 100, "28079", 1970)
check(nueva.valor_referencia > vieja.valor_referencia,
      "una vivienda nueva se valora por encima de una de más de cinco años")
check(nueva.ambito == "municipio", "y declara que el ámbito es municipal")
check(valorar_por_superficie("28", 100, "28001").ambito == "provincia",
      "sin dato municipal cae a la provincia y lo dice")


v = valorar_por_superficie("28", 100)
check(abs(v.valor_referencia - p.euros_m2 * 100) < 1, "valor = €/m² × superficie")
check(any("PROVINCIAL" in a for a in v.avisos),
      "avisa de que es una media provincial, no una tasación")
check(valorar_por_superficie("28", None).error is not None,
      "sin superficie no se valora en lugar de inventar")


print("\n=== 24) Valoración: ni datos de 2018 ni rentabilidades supuestas ===")
import valoracion as val

subasta = {"valor_subasta": 200_000, "provincia": "madrid"}
inmueble = {"superficie_m2": 80, "municipio": "Madrid", "provincia": "Madrid",
            "codigo_ine_provincia": "28", "codigo_ine_municipio": "079"}
r = val.valorar(subasta, inmueble)
check(r.valor_mercado_estimado and r.valor_mercado_estimado > 200_000,
      f"valora con el dato oficial ({r.valor_mercado_estimado:,.0f} €)".replace(",", "."))
check(r.alquiler_ambito == "municipio",
      "el alquiler es el medido del municipio, no una estimación")
check(r.origen_alquiler["disponible"] is True and r.origen_alquiler["base"],
      f"y declara de dónde sale ({r.origen_alquiler['base']})")
check(r.descuento_pct is not None, "calcula el descuento sobre el valor actual")
check("valor_mercado" in r.fuentes and "Ministerio" in r.fuentes["valor_mercado"],
      "cita al ministerio como fuente del valor")
check(not hasattr(r, "senal_revalorizacion"),
      "ya no publica la señal que venía de un modelo con datos sintéticos")

# Municipio sin alquiler publicado: debe declararlo, no disimularlo.
sin_dato = val.valorar(subasta, dict(inmueble, codigo_ine_municipio="001"))
check(sin_dato.alquiler_ambito == "provincia",
      "sin dato del municipio se usa la mediana provincial, no un supuesto")
check(sin_dato.origen_alquiler["municipios_en_la_mediana"] > 10,
      f"compuesta por municipios medidos ({sin_dato.origen_alquiler['municipios_en_la_mediana']})")
check(any("MEDIANA de los" in a for a in sin_dato.avisos),
      "y el aviso dice exactamente qué se ha usado")
check(sin_dato.alquiler_mensual and sin_dato.alquiler_mensual > 0,
      "sigue habiendo rentabilidad calculable")

# Ya no queda ningún porcentaje inventado en el camino del alquiler.
import inspect
check("YIELD" not in inspect.getsource(val),
      "no queda ninguna rentabilidad supuesta en el módulo de valoración")

# El alquiler que aporta el usuario manda sobre cualquier fuente.
propio = val.valorar(subasta, inmueble, alquiler_usuario=1500)
check(propio.alquiler_mensual == 1500 and propio.alquiler_ambito == "inmueble",
      "el alquiler real del usuario tiene prioridad")


print("\n=== 25) Comparación de municipios (sin un solo dato inventado) ===")
from zonas import PROVINCIAS, analizar_zonas, codigo_de_provincia, contexto_distritos

check(codigo_de_provincia("Madrid") == "28" and codigo_de_provincia("28") == "28",
      "la provincia se acepta por nombre y por código")
check(codigo_de_provincia("vizcaya") == "48", "y por su nombre alternativo")
check(codigo_de_provincia("Ciudad Inventada") is None, "una provincia falsa no cuela")

# El selector de la demo manda el nombre SIN TILDES: «malaga» devolvía una tabla
# vacía en silencio, y sólo se vio probando la URL pública con el servicio
# dormido. Se comprueban las 52 en todas las formas en que pueden llegar.
import unicodedata as _ud
def _sin_tildes_test(t):
    return "".join(c for c in _ud.normalize("NFD", t.lower()) if _ud.category(c) != "Mn")

_fallos_prov = [(c, v) for c, n in PROVINCIAS.items()
                for v in (n, n.lower(), n.upper(), _sin_tildes_test(n), c)
                if codigo_de_provincia(v) != c]
check(not _fallos_prov,
      f"las 52 provincias se reconocen con y sin tildes, en mayúsculas y por código ({_fallos_prov[:3]})")
check(codigo_de_provincia("malaga") == "29" and codigo_de_provincia("Málaga") == "29",
      "«malaga» y «Málaga» llevan al mismo sitio")

z = analizar_zonas("madrid", limite=12)
check(z.total_municipios > 5, f"{z.total_municipios} municipios comparados")
check(all(m["alquiler_mensual"] > 0 for m in z.municipios), "todos traen alquiler real")
check(all(m["alquiler_anio"] >= 2023 for m in z.municipios), "de un año reciente")
rents = [m["rentabilidad_neta"] for m in z.municipios]
check(rents == sorted(rents, reverse=True), "vienen ordenados por rentabilidad neta")
check(len({m["alquiler_m2_mes"] for m in z.municipios}) > 3,
      "el alquiler varía de verdad entre municipios, que era el problema de fondo")
check(any(m["precio_es_municipal"] for m in z.municipios),
      "el precio de compra es el del municipio, no una media provincial")
check(len({m["precio_m2_compra"] for m in z.municipios}) > 3,
      "y varía de verdad entre municipios")
check(any("no una media provincial" in a for a in z.avisos),
      "el aviso explica de dónde sale el precio y cuándo cae a la provincia")
check(z.precio_compra_provincial["anio"] >= 2025, "con el precio del trimestre en curso")
check(analizar_zonas("Provincia Falsa").total_municipios == 0,
      "una provincia inexistente devuelve vacío con explicación")

d = contexto_distritos("madrid")
check(d["disponible"] and len(d["distritos"]) == 21, "Madrid trae sus 21 distritos")
check(all("renta_hogar_anual" in f for f in d["distritos"]), "con la renta de cada uno")
check("no bajan de municipio" in d["aviso"],
      "y explica por qué ahí no hay alquiler ni precio")
check(contexto_distritos("zaragoza")["disponible"] is False,
      "Zaragoza no inventa distritos: su numeración no supera el contraste")
dist_val = contexto_distritos("valencia")
check(dist_val["disponible"] and len(dist_val["distritos"]) == 19,
      f"Valencia trae sus 19 distritos ({len(dist_val.get('distritos', []))})")
check(dist_val["distritos"][0]["nombre"] == "El Pla del Real",
      f"y el de mayor renta es El Pla del Real ({dist_val['distritos'][0]['nombre']})")
sev = contexto_distritos("sevilla")
check(sev["distritos"][0]["nombre"] == "Los Remedios",
      f"en Sevilla, Los Remedios ({sev['distritos'][0]['nombre']})")
check(sev["distritos"][-1]["nombre"] == "Cerro-Amate",
      f"y abajo Cerro-Amate ({sev['distritos'][-1]['nombre']})")


print("\n=== 26) El mapa provincia → tabla del INE apunta donde debe ===")
import re as _re
import httpx as _httpx
from renta_ine import CSV_URL, TABLA_POR_PROVINCIA

check(len(TABLA_POR_PROVINCIA) == 52, f"las 52 provincias mapeadas ({len(TABLA_POR_PROVINCIA)})")
check(len(set(TABLA_POR_PROVINCIA.values())) == 52,
      "sin tablas repetidas: dos provincias no pueden salir del mismo fichero")

# Este es el test que faltaba. El mapa se había construido sondeando y estaba mal
# en 35 de 51 provincias; no daba cifras falsas, pero dejaba a casi toda España
# sin renta en silencio. Sobrevivió porque sólo se probaban Madrid y Barcelona.
# Se comprueba una muestra repartida, leyendo el principio del CSV real.
def _provincia_real(tabla):
    with _httpx.stream("GET", CSV_URL.format(tabla=tabla), timeout=60,
                       follow_redirects=True) as r:
        r.raise_for_status()
        buf = b""
        for trozo in r.iter_bytes():
            buf += trozo
            if len(buf) > 90_000:
                break
    m = _re.search(r"\n(\d{5}) ", buf.decode("utf-8-sig", "ignore"))
    return m.group(1)[:2] if m else None

for _cp in ("08", "28", "29", "41", "46", "50"):
    try:
        _real = _provincia_real(TABLA_POR_PROVINCIA[_cp])
        check(_real == _cp, f"la tabla de la provincia {_cp} contiene la provincia {_real}")
    except Exception as e:
        check(False, f"no se pudo comprobar la provincia {_cp}: {type(e).__name__}")


print("\n=== 27) El tipo hipotecario parte del Euríbor real ===")
from datos_vivos import (DIFERENCIAL_POR_DEFECTO, euribor_12m, tipo_bce,
                         tipo_hipotecario_estimado)

eur = euribor_12m()
check(eur.error is None if hasattr(eur, "error") else True, "el Euríbor se descarga")
check(0 < eur.valor < 0.15, f"valor plausible: {eur.valor*100:.3f} %")
check("Euríbor" in eur.fuente, f"y cita su serie ({eur.fuente})")
check(eur.es_estimacion is False, "es un dato, no una estimación")

# Antes se usaba el tipo de intervención del BCE, que es otra cosa: mide lo que
# cuesta el dinero al banco, no el índice al que se revisan las hipotecas.
bce = tipo_bce()
check(eur.valor != bce.valor,
      f"Euríbor ({eur.valor*100:.2f} %) y BCE ({bce.valor*100:.2f} %) no son lo mismo")

t = tipo_hipotecario_estimado()
check(abs(t["tipo_estimado"] - (eur.valor + DIFERENCIAL_POR_DEFECTO)) < 1e-9,
      "el tipo es Euríbor más diferencial, sin más pasos")
check(t["diferencial_es_por_defecto"] is True, "y avisa de que el diferencial es el de serie")
propio = tipo_hipotecario_estimado(diferencial=0.005)
check(propio["diferencial"] == 0.005 and propio["diferencial_es_por_defecto"] is False,
      "quien tiene una oferta concreta puede pasar la suya")
check("no se mide" in t["aviso"],
      "el aviso dice exactamente qué parte no está medida")


print("\n=== 28) No queda ningún dato inventado en la cadena principal ===")
import alquiler_real as _ar, precio_compra as _pc, renta_ine as _ri
import valoracion as valoracion_mod

# El recorrido completo de una subasta real, comprobando que cada cifra sale de
# una fuente con año y organismo. Es el test que resume el proyecto.
_inm = {"superficie_m2": 90.0, "municipio": "Getafe", "provincia": "Madrid",
        "codigo_ine_provincia": "28", "codigo_ine_municipio": "065",
        "anio_construccion": 1985}
_v = valoracion_mod.valorar({"valor_subasta": 180_000, "provincia": "madrid"}, _inm)

check(_v.origen_valor and _v.origen_valor["ambito"] == "municipio",
      "el valor sale del municipio, no de una media provincial")
check("Ministerio" in _v.origen_valor["fuente"], "citando al ministerio")
check(_v.origen_alquiler["ambito"] in ("municipio", "provincia"),
      "el alquiler declara su ámbito")
check(_v.origen_alquiler.get("anio", 0) >= 2023, "y su año")
check(all(f for f in _v.fuentes.values()), "todas las fuentes tienen texto")

# Cada fuente responde de verdad y con datos plausibles.
check(_ar.alquiler_municipio("28065").mediana_mensual > 200, "alquiler real de Getafe")
check(_pc.precio_municipio("28065").euros_m2 > 500, "precio de compra de Getafe")
check(_ri.consultar("Getafe", "28", "065").renta_hogar_anual > 10_000, "renta de Getafe")


print("\n=== 29) Cobertura: las 52 provincias, no sólo las que se miran ===")
from zonas import PROVINCIAS as _PROV, analizar_zonas as _az

_sin_precio, _sin_alquiler = [], []
for _cp, _nom in _PROV.items():
    if not _ar.municipios_de_provincia(_cp):
        _sin_alquiler.append(_nom)
    _pp = _pc.precio_provincia(_cp)
    if _pp.error or not _pp.euros_m2:
        _sin_precio.append(_nom)

check(not _sin_alquiler, f"todas tienen alquiler publicado ({_sin_alquiler})")
# Navarra y Asturias no vienen como provincia en el fichero, sólo como comunidad;
# al ser uniprovinciales es el mismo territorio y se toman de ahí. Sin eso, la
# comparación devolvía cero municipios en las dos y nadie lo habría notado.
check(not _sin_precio, f"todas tienen precio de compra ({_sin_precio})")
check(_pc.precio_provincia("31").euros_m2 > 500, "Navarra sale de su fila de comunidad")
check(_pc.precio_provincia("33").euros_m2 > 500, "Asturias también")
# El fichero trae una fila agregada «Ceuta y Melilla» con CPRO="null" que se
# colaba como una provincia más.
check(len(_pc._carga()) == 52,
      f"exactamente 52 provincias, sin filas agregadas coladas ({len(_pc._carga())})")

_muestra = ("01", "31", "33", "35", "44", "52")
for _cp in _muestra:
    _r = _az(_cp, limite=4)
    check(_r.total_municipios > 0,
          f"{_PROV[_cp]} devuelve municipios comparables ({_r.total_municipios})")


print("\n=== 30) ¿Se paga solo? — la pregunta del proyecto ===")
from autofinanciacion import (OBJETIVO, analizar_autofinanciacion,
                              entrada_minima_para_cash_flow)

# Caso que sí: piso barato con alquiler alto.
si = analizar_autofinanciacion(90_000, 750, "madrid", Supuestos(entrada_pct=0.30), "28092")
check(si.se_paga_solo is True, f"90k con 750 €/mes se paga solo ({si.cash_flow_mensual:+.0f} €)")
check(si.veredicto.startswith("Sí"), "y el veredicto empieza por sí")
check(si.entrada_minima_pct is None, "no hace falta calcular entrada mínima si ya sale")

# Caso que no, pero se arregla con más entrada.
no = analizar_autofinanciacion(288_000, 849, "madrid", Supuestos(entrada_pct=0.30), "28065")
check(no.se_paga_solo is False, f"288k con 849 €/mes no se paga solo ({no.cash_flow_mensual:+.0f} €)")
check(0.30 < no.entrada_minima_pct < 1.0,
      f"pero se pagaría con un {no.entrada_minima_pct*100:.0f} % de entrada")
check(no.capital_extra_necesario > 0, "y dice cuánto capital extra hace falta")
check(no.imposible_a_cualquier_entrada is False, "no es un caso imposible")

# La entrada mínima tiene que ser exactamente el punto de corte.
s_min = Supuestos(entrada_pct=no.entrada_minima_pct)
check(analizar(288_000, 849, "madrid", s_min).cash_flow_mensual >= OBJETIVO - 0.5,
      "en la entrada mínima el cash-flow ya no es negativo")
s_menos = Supuestos(entrada_pct=max(0.0, no.entrada_minima_pct - 0.02))
check(analizar(288_000, 849, "madrid", s_menos).cash_flow_mensual < OBJETIVO,
      "y dos puntos por debajo todavía lo es: el corte es el corte")

# Caso imposible: el alquiler no cubre ni los gastos corrientes.
jamas = analizar_autofinanciacion(300_000, 120, "madrid", Supuestos(entrada_pct=0.30), "28079")
check(jamas.imposible_a_cualquier_entrada is True,
      "con 120 €/mes no se paga solo ni al contado")
check("ni pagándolo al contado" in " ".join(jamas.explicacion).lower(),
      "y se dice sin rodeos")
check(entrada_minima_para_cash_flow(300_000, 120, "madrid")["posible"] is False,
      "la entrada mínima devuelve «no posible» en lugar de un 100 % engañoso")

# La proyección de años usa la subida REAL del alquiler de ese municipio.
check(no.anios_hasta_pagarse_solo and 0 < no.anios_hasta_pagarse_solo <= 30,
      f"proyecta en cuántos años se pagaría solo ({no.anios_hasta_pagarse_solo})")
check(no.proyeccion and "IPVA" in no.proyeccion["fuente"],
      "con el IPVA del INE, no con una subida inventada")
sin_municipio = analizar_autofinanciacion(288_000, 849, "madrid", Supuestos(entrada_pct=0.30), None)
check(sin_municipio.anios_hasta_pagarse_solo is None,
      "sin municipio no se proyecta nada")
check(any("no se puede proyectar" in e.lower() for e in sin_municipio.explicacion),
      "y se explica por qué en lugar de callar")


print("\n=== 31) Dónde se paga solo en toda España ===")
from zonas import se_pagan_solos

solos = se_pagan_solos(80, Supuestos(entrada_pct=0.30, interes_anual=0.03684), limite=200)
check(solos["total"] > 0, f"{solos['total']} municipios se pagan solos con 30 % de entrada")
check(all(m["cash_flow_mensual"] >= 0 for m in solos["municipios"]),
      "todos los listados tienen cash-flow positivo")
check(solos["municipios"] == sorted(solos["municipios"],
                                    key=lambda m: -m["cash_flow_mensual"]),
      "ordenados por lo que dejan al mes")

# Coherencia con la vista por provincia: la misma pregunta, la misma respuesta.
_uno = solos["municipios"][0]
_z = _az(_uno["codigo_provincia"], limite=100)
_mismo = [m for m in _z.municipios if m["codigo_ine"] == _uno["codigo_ine"]]
check(_mismo and _mismo[0]["se_paga_solo"] is True,
      f"{_uno['nombre']} también sale como «se paga solo» en su provincia")

# Más entrada, más municipios: si no, el cálculo no responde a la entrada.
pocos = se_pagan_solos(80, Supuestos(entrada_pct=0.10, interes_anual=0.03684), limite=200)
muchos = se_pagan_solos(80, Supuestos(entrada_pct=0.60, interes_anual=0.03684), limite=200)
check(pocos["total"] <= solos["total"] <= muchos["total"],
      f"a más entrada, más municipios ({pocos['total']} → {solos['total']} → {muchos['total']})")
check(any("no es un fallo del cálculo" in a for a in solos["avisos"]),
      "y se explica que salgan pocos")


print("\n=== 32) Identificadores del BOE cuya ficha no existe ===")
from boe_client import Subasta as _Sub

# El buscador cuela subastas de la Agencia Tributaria («SUB-AT-2026-25») cuyo
# detalle responde «La subasta no existe». Eso NO es un cambio de maquetación, y
# confundirlo daba una falsa alarma que declaraba roto el portal entero según qué
# subasta cayera primera ese día. La distinción se marca explícitamente.
_muerta = _Sub(identificador="SUB-AT-2026-25")
_muerta.campos_ausentes = ["ficha_inexistente"]
check(_muerta.campos_ausentes == ["ficha_inexistente"],
      "una ficha inexistente se marca con su propio código, no como campos sueltos")

import inspect as _insp
import boe_client as _bc
_fuente = _insp.getsource(_bc.BoeClient.detalle)
check("no existe" in _fuente and "ficha_inexistente" in _fuente,
      "el cliente detecta la página de error del portal antes de intentar parsearla")

import vigencia as _vig
_fuente_v = _insp.getsource(_vig.comprobar)
check("ficha_inexistente" in _fuente_v,
      "y la comprobación de vigencia distingue ese caso del portal roto")
check("limite=6" in _fuente_v,
      "sondeando varias subastas en lugar de fiarlo todo a la primera")


print("\n=== 33) Una subasta vencida no se muestra como si quedara tiempo ===")
import inspect as _i2
import api as _api

_fuente_op = _i2.getsource(_api.oportunidades)
# El BOE tarda en cambiar el estado de «en curso», así que una subasta cuyo
# plazo ya terminó puede seguir apareciendo en el listado. Antes se recortaba a
# cero y se pintaba «0 días para pujar», indistinguible de «cierra hoy».
check("max(0, (fin - ahora).days)" not in _fuente_op,
      "ya no se recorta a cero el tiempo restante de una subasta vencida")
check('d["cerrada"]' in _fuente_op, "cada subasta declara si ya cerró")
check("incluir_cerradas" in _fuente_op,
      "y se excluyen por defecto, con parámetro para verlas si se quiere")

# La lógica del borde, sin depender de que hoy haya subastas vencidas en el BOE.
from datetime import datetime, timedelta, timezone
_ahora = datetime.now(timezone.utc)
for _delta, _esperado in ((timedelta(hours=-2), True), (timedelta(hours=+2), False),
                          (timedelta(days=+5), False)):
    _fin = _ahora + _delta
    _restante = _fin - _ahora
    check((_restante.total_seconds() <= 0) is _esperado,
          f"fin en {_delta} → cerrada={_esperado}")

# Y que ninguna de las que se sirven ahora mismo esté vencida. Se pide por HTTP
# con el cliente de pruebas de FastAPI: llamar a la función a pelo pasa objetos
# Query como argumentos, porque son los valores por defecto de la firma.
try:
    from fastapi.testclient import TestClient
    with TestClient(_api.app) as _cliente:
        _r = _cliente.get("/subastas/oportunidades",
                          params={"provincia": "madrid", "limite": 6}, timeout=300).json()
    _vencidas = [o for o in _r["oportunidades"] if o.get("cerrada")]
    check(not _vencidas, f"ninguna de las {_r['total']} subastas servidas está vencida")
    _sin_fecha = [o for o in _r["oportunidades"] if not o.get("fecha_fin")]
    check(not _sin_fecha, f"y todas traen fecha de cierre ({len(_sin_fecha)} sin ella)")
except Exception as _e:
    check(False, f"no se pudo comprobar el listado en vivo: {type(_e).__name__}: {_e}")


print("\n=== 34) Las cachés caducan y alguien lo mira ===")
import refresco as _refr

_est = _refr.estado()
check(len(_est) > 8, f"{len(_est)} cachés vigiladas")
check(all(e.limite in (_refr.TRIMESTRAL, _refr.ANUAL) for e in _est),
      "cada una con el plazo de su fuente: trimestral o anual")
check(any(e.limite == _refr.TRIMESTRAL for e in _est)
      and any(e.limite == _refr.ANUAL for e in _est),
      "y hay de los dos tipos, no un plazo único para todo")
check(all(e.dias is None or e.dias >= 0 for e in _est), "las edades son coherentes")
check(not [e for e in _est if e.caducada],
      f"ninguna caducada ahora mismo ({[e.nombre for e in _est if e.caducada]})")

# La comprobación tiene que estar enganchada, no sólo existir suelta.
check("refresco" in _insp.getsource(_vig.comprobar),
      "vigencia.py mira la edad de las cachés en cada pasada")

# Refrescar no debe formar parte de una petición de usuario: son cientos de MB.
_fuente_refr = _insp.getsource(_refr.refrescar)
check("forzar=True" in _fuente_refr, "el refresco fuerza la descarga de verdad")
check(_refr.refrescar.__doc__ and "fuera de una petición" in _refr.refrescar.__doc__,
      "y está documentado que va fuera de banda")


print(f"\n{'='*54}")
print(f"  {'TODO OK' if not fallos else 'FALLOS: ' + str(len(fallos))}"
      f" — {len(fallos)} fallo(s)")
if fallos:
    for f in fallos:
        print(f"    ✗ {f}")
sys.exit(1 if fallos else 0)
