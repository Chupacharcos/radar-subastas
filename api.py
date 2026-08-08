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
from inversor import analizar_inversor
from contexto_zona import evaluar_zona

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

    return {
        "subasta": subasta.to_dict() | {"url": subasta.url},
        "inmueble": inmueble,
        "valoracion": v.to_dict(),
        "rentabilidad": financiero,
        "metricas_inversor": metricas,
        "contexto_zona": zona.to_dict(),
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
