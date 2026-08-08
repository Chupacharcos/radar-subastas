"""
Radar de Subastas — API.

Encadena cuatro fuentes públicas para responder a una pregunta que hoy nadie
responde de una vez: *esta subasta que sale a X euros, ¿es oportunidad o
trampa?*

    BOE (oportunidad) → Catastro (qué es) → valoración (cuánto vale)
                                          → rentabilidad (qué deja al mes)
                                          → riesgo (qué puede salir mal)

Puerto 8010.
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from boe_client import BoeClient, PROVINCIAS
from catastro import consultar as consultar_catastro
from rentabilidad import Supuestos, analizar, precio_maximo_para_cash_flow
from riesgo import evaluar as evaluar_riesgo
from valoracion import valorar
from zonas import analizar_zonas, contexto_distritos, provincias_disponibles
from inversor import analizar_inversor
from contexto_zona import evaluar_zona
from entorno import analizar_entorno, geocodificar

app = FastAPI(
    title="Radar de Subastas",
    description="Oportunidades inmobiliarias en subastas públicas, valoradas y con su riesgo.",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


class SupuestosIn(BaseModel):
    entrada_pct: float = Field(0.30, ge=0.0, le=1.0)
    interes_anual: float = Field(0.032, ge=0.0, le=0.20)
    anios_hipoteca: int = Field(25, ge=1, le=40)
    reforma: float = Field(0.0, ge=0.0)
    vacancia_pct: float = Field(0.06, ge=0.0, le=0.5)
    irpf_marginal: float = Field(0.30, ge=0.0, le=0.55)
    comunidad_mensual: float = Field(60.0, ge=0.0)
    ibi_anual: float = Field(400.0, ge=0.0)

    def a_supuestos(self) -> Supuestos:
        return Supuestos(**self.model_dump())


class AnalisisIn(BaseModel):
    identificador: str = Field(..., description="Identificador de la subasta, p. ej. SUB-JA-2026-265154")
    alquiler_mensual: Optional[float] = Field(None, ge=0, description="Alquiler real si lo conoces")
    supuestos: Optional[SupuestosIn] = None


class CalculadoraIn(BaseModel):
    precio_compra: float = Field(..., gt=0)
    alquiler_mensual: float = Field(..., gt=0)
    provincia: Optional[str] = Field(None, description="Determina el ITP aplicable")
    supuestos: Optional[SupuestosIn] = None


@app.get("/health")
def health():
    return {"status": "ok", "service": "subastas-radar", "version": "1.0.0"}


@app.get("/subastas/health")
def health_prefijo():
    return health()


@app.get("/subastas/provincias")
def provincias():
    """Provincias con atajo por nombre; el resto se consulta por código INE."""
    return {"provincias": sorted(PROVINCIAS), "nota": "También admite el código INE de dos dígitos."}


@app.get("/subastas/buscar")
def buscar(provincia: str = Query("madrid"), limite: int = Query(10, ge=1, le=40)):
    """Subastas de inmuebles en curso, con sus datos económicos y del bien."""
    try:
        with BoeClient() as cliente:
            subastas = cliente.buscar_con_detalle(provincia, limite)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"El portal del BOE no respondió: {e}")

    return {
        "provincia": provincia,
        "total": len(subastas),
        "subastas": [s.to_dict() | {"url": s.url} for s in subastas],
        "fuente": "Portal de Subastas de la Agencia Estatal BOE",
    }


@app.get("/subastas/zonas")
def zonas(provincia: str = Query("madrid", description="Nombre o código INE de dos dígitos"),
          superficie: int = Query(80, ge=25, le=400),
          entrada_pct: float = Query(0.30, ge=0.0, le=1.0),
          interes_anual: float = Query(None, ge=0.0, le=0.2),
          anios: int = Query(25, ge=5, le=40),
          limite: int = Query(40, ge=5, le=100)):
    """Compara los municipios de una provincia como inversión de alquiler.

    Con el alquiler real de cada municipio —el declarado a la Agencia
    Tributaria—, la renta del hogar del INE y el valor tasado oficial. Nada
    estimado: cada cifra dice de qué organismo y de qué año viene."""
    if interes_anual is None:
        from datos_vivos import tipo_hipotecario_estimado
        interes_anual = tipo_hipotecario_estimado()["tipo_estimado"]
    s = Supuestos(entrada_pct=entrada_pct, interes_anual=interes_anual, anios_hipoteca=anios)
    return analizar_zonas(provincia, superficie, s, limite).to_dict()


@app.get("/subastas/distritos")
def distritos(ciudad: str = Query("madrid")):
    """Renta del hogar y evolución del alquiler por distrito censal.

    Sólo esas dos cosas: son las únicas que el INE publica a ese grano."""
    return contexto_distritos(ciudad)


@app.get("/subastas/ciudades")
def ciudades():
    """Provincias con comparación de municipios disponible."""
    return {"provincias": provincias_disponibles()}


@app.get("/subastas/oportunidades")
def oportunidades(provincia: str = Query("madrid"), limite: int = Query(12, ge=1, le=30),
                  precio_max: float = Query(None, description="Descarta lo que no puedas pagar"),
                  entrada_max: float = Query(None, description="Capital del que dispones"),
                  riesgo_max: int = Query(None, ge=0, le=100),
                  solo_analizables: bool = Query(True)):
    """Subastas ya valoradas y ordenadas por oportunidad.

    El listado crudo obliga a entrar una por una para saber si algo interesa, y
    muchas no se pueden analizar siquiera (sin referencia catastral no hay
    superficie, y sin superficie no hay precio por m²). Aquí llegan ya con su
    riesgo, su precio por m² y el capital que harían falta, ordenadas para que lo
    interesante esté arriba.
    """
    try:
        with BoeClient() as cliente:
            subastas = cliente.buscar_con_detalle(provincia, limite)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"El portal del BOE no respondió: {e}")

    from impuestos import calcular_itp, gastos_compra

    resultados = []
    for s in subastas:
        d = s.to_dict() | {"url": s.url}
        d["analizable"] = bool(s.referencia_catastral and s.valor_subasta)
        d["motivo_no_analizable"] = None
        if not s.valor_subasta:
            d["motivo_no_analizable"] = "la subasta no publica valor de salida"
        elif not s.referencia_catastral:
            d["motivo_no_analizable"] = ("sin referencia catastral no se puede saber "
                                         "la superficie ni el precio por m²")

        riesgo = evaluar_riesgo(s.to_dict(), None)
        d["riesgo_nivel"] = riesgo.nivel
        d["riesgo_puntuacion"] = riesgo.puntuacion
        d["riesgos_clave"] = [r["titulo"] for r in riesgo.riesgos[:3]]

        # Superficie del Catastro sólo si la hay: es lo que permite el €/m².
        d["superficie_m2"] = None
        d["precio_m2"] = None
        if s.referencia_catastral:
            inm = consultar_catastro(s.referencia_catastral)
            if inm.superficie_m2:
                d["superficie_m2"] = inm.superficie_m2
                d["anio_construccion"] = inm.anio_construccion
                if s.valor_subasta:
                    d["precio_m2"] = round(s.valor_subasta / inm.superficie_m2, 2)

        # Capital necesario: es el filtro que de verdad usa un inversor.
        if s.valor_subasta:
            itp = calcular_itp(s.valor_subasta, s.provincia)["cuota"]
            gastos = gastos_compra(s.valor_subasta)["total"]
            d["capital_necesario_estimado"] = round(s.valor_subasta * 0.30 + itp + gastos, 2)
        else:
            d["capital_necesario_estimado"] = None

        # Días hasta el cierre: en subastas la urgencia es parte de la decisión.
        d["dias_para_cierre"] = None
        if s.fecha_fin:
            from datetime import datetime, timezone
            try:
                fin = datetime.fromisoformat(s.fecha_fin)
                ahora = datetime.now(fin.tzinfo or timezone.utc)
                d["dias_para_cierre"] = max(0, (fin - ahora).days)
            except ValueError:
                pass

        resultados.append(d)

    if solo_analizables:
        resultados = [r for r in resultados if r["analizable"]]
    if precio_max:
        resultados = [r for r in resultados if (r["valor_subasta"] or 0) <= precio_max]
    if entrada_max:
        resultados = [r for r in resultados
                      if (r["capital_necesario_estimado"] or 0) <= entrada_max]
    if riesgo_max is not None:
        resultados = [r for r in resultados if r["riesgo_puntuacion"] <= riesgo_max]

    # Orden: primero lo barato por m² y con menos riesgo. Sin €/m² va al final,
    # porque no se puede comparar.
    def clave(r):
        sin_dato = r["precio_m2"] is None
        return (sin_dato, r["riesgo_puntuacion"], r["precio_m2"] or 0)

    resultados.sort(key=clave)

    return {
        "provincia": provincia,
        "total": len(resultados),
        "filtros": {"precio_max": precio_max, "entrada_max": entrada_max,
                    "riesgo_max": riesgo_max, "solo_analizables": solo_analizables},
        "oportunidades": resultados,
        "orden": "menor riesgo y menor precio por m² primero",
        "fuente": "Portal de Subastas del BOE + Catastro",
    }


@app.post("/subastas/analizar")
def analizar_subasta(datos: AnalisisIn):
    """Análisis completo de una subasta: qué es, cuánto vale, qué renta y qué riesgo tiene."""
    try:
        with BoeClient() as cliente:
            subasta = cliente.detalle(datos.identificador)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"No se pudo leer la subasta: {e}")

    if not subasta.valor_subasta:
        raise HTTPException(status_code=422,
                            detail="La subasta no publica valor de salida; no se puede analizar.")

    inmueble = (consultar_catastro(subasta.referencia_catastral).to_dict()
                if subasta.referencia_catastral else
                {"error": "La subasta no publica referencia catastral"})

    v = valorar(subasta.to_dict(), inmueble, datos.alquiler_mensual)
    riesgo = evaluar_riesgo(subasta.to_dict(), inmueble)

    supuestos = datos.supuestos.a_supuestos() if datos.supuestos else Supuestos()
    financiero = None
    if v.alquiler_mensual_estimado:
        financiero = analizar(
            subasta.valor_subasta, v.alquiler_mensual_estimado,
            inmueble.get("provincia") or subasta.provincia, supuestos,
        ).to_dict()
        financiero["precio_maximo_cash_flow_cero"] = precio_maximo_para_cash_flow(
            v.alquiler_mensual_estimado, 0.0,
            inmueble.get("provincia") or subasta.provincia, supuestos,
        )

    # Contexto del entorno: manda sobre la rentabilidad, porque una zona
    # tensionada limita por ley el alquiler que se puede cobrar.
    zona = evaluar_zona(
        inmueble.get("municipio") or subasta.localidad,
        inmueble.get("provincia") or subasta.provincia,
        inmueble.get("anio_construccion"),
        codigo_ine_provincia=inmueble.get("codigo_ine_provincia"),
        codigo_ine_municipio=inmueble.get("codigo_ine_municipio"),
    )

    metricas = None
    if v.alquiler_mensual_estimado:
        metricas = analizar_inversor(
            subasta.valor_subasta, v.alquiler_mensual_estimado,
            inmueble.get("provincia") or subasta.provincia, supuestos,
            renta_hogar_zona_anual=zona.renta_hogar_anual,
        ).to_dict()

    # Entorno: lo que hace que un piso se alquile rápido o se quede vacío.
    entorno = None
    coords = geocodificar(subasta.direccion, subasta.codigo_postal,
                          inmueble.get("municipio") or subasta.localidad)
    if coords:
        entorno = analizar_entorno(*coords).to_dict()
        entorno["coordenadas"] = {"lat": coords[0], "lon": coords[1]}

    return {
        "subasta": subasta.to_dict() | {"url": subasta.url},
        "inmueble": inmueble,
        "valoracion": v.to_dict(),
        "rentabilidad": financiero,
        "metricas_inversor": metricas,
        "contexto_zona": zona.to_dict(),
        "entorno": entorno,
        "riesgo": riesgo.to_dict(),
    }


@app.post("/subastas/inversor")
def metricas_inversor(datos: CalculadoraIn):
    """Métricas de solvencia sobre una operación: DSCR, punto muerto de
    ocupación, estrés de tipos, esfuerzo del inquilino y coste de oportunidad."""
    supuestos = datos.supuestos.a_supuestos() if datos.supuestos else Supuestos()
    m = analizar_inversor(datos.precio_compra, datos.alquiler_mensual,
                          datos.provincia, supuestos)
    return m.to_dict()


@app.get("/subastas/zona")
def zona(municipio: str = Query(...), provincia: str = Query(None),
         anio_construccion: int = Query(None)):
    """Contexto del entorno: zona tensionada, ITE y eficiencia energética."""
    return evaluar_zona(municipio, provincia, anio_construccion).to_dict()


@app.get("/subastas/alquiler")
def alquiler(codigo_municipio: str = Query(..., description="Código INE del municipio, 5 dígitos"),
             codigo_distrito: str = Query(None, description="Código INE del distrito, 7 dígitos")):
    """Cómo evoluciona el alquiler frente al precio de compra en una zona.

    Con los contratos que se declaran a Hacienda (IPVA) y el índice oficial de
    precios de vivienda (IPV), ambos del INE. Son índices, no niveles: dicen
    cuánto sube el alquiler, no cuánto se paga por él.
    """
    from alquiler_ine import (distritos_de, precio_vs_alquiler,
                              tendencia_alquiler_municipio)

    codigo = codigo_municipio.strip().zfill(5)
    municipio = tendencia_alquiler_municipio(codigo)
    comparacion = precio_vs_alquiler(codigo, codigo[:2], codigo_distrito)
    return {
        "municipio": municipio.to_dict(),
        "precio_vs_alquiler": comparacion.to_dict(),
        "distritos_disponibles": distritos_de(codigo),
    }


@app.get("/subastas/entorno")
def entorno_zona(lat: float = Query(...), lon: float = Query(...)):
    """Transporte, servicios y molestias alrededor de unas coordenadas (OSM)."""
    return analizar_entorno(lat, lon).to_dict()


@app.get("/subastas/vigencia")
def vigencia():
    """Estado de frescura de los datos: tipos de ITP, tipo de referencia del
    BCE y las dos fuentes externas. Pensado para engancharlo a un monitor."""
    from vigencia import comprobar
    resultados = [c.to_dict() for c in comprobar()]
    return {
        "comprobaciones": resultados,
        "todo_ok": all(c["estado"] == "ok" for c in resultados),
    }


@app.get("/subastas/tipo-interes")
def tipo_interes():
    """Tipo de referencia oficial en vivo, con su fecha y fuente."""
    from datos_vivos import tipo_hipotecario_estimado
    return tipo_hipotecario_estimado()


@app.post("/subastas/calculadora")
def calculadora(datos: CalculadoraIn):
    """Rentabilidad de cualquier operación, venga o no de una subasta.

    Útil para contrastar: los portales muestran rentabilidad bruta, que ignora
    ITP, gastos de compra y vacancia."""
    supuestos = datos.supuestos.a_supuestos() if datos.supuestos else Supuestos()
    resultado = analizar(datos.precio_compra, datos.alquiler_mensual, datos.provincia, supuestos)
    return {
        "analisis": resultado.to_dict(),
        "precio_maximo_cash_flow_cero": precio_maximo_para_cash_flow(
            datos.alquiler_mensual, 0.0, datos.provincia, supuestos
        ),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", 8010)))
