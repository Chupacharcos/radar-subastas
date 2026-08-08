"""
Adaptador para la API de Idealista — desactivado hasta que haya credenciales.

Por qué está aquí sin usarse: la API de Idealista existe y es la mejor fuente
de precios de oferta que hay, pero **no se puede activar por cuenta ajena**. Su
acceso se concede tras solicitud manual y sus condiciones no permiten
redistribuir los datos a terceros, que es justo lo que hace un servicio
público. Usar la clave de otro, o scrapear su web, sería incumplir sus términos.

Lo que sí es legítimo: que **quien despliegue este proyecto pida su propia
clave**, acepte sus condiciones y la configure. En ese caso este módulo hace el
trabajo y el análisis pasa a contrastar el valor de subasta con precios de
oferta reales de la zona, además de con el modelo estadístico.

Para activarlo:

    1. Solicita acceso en https://developers.idealista.com/access-request
    2. Exporta las credenciales que te den:
         export IDEALISTA_API_KEY="..."
         export IDEALISTA_SECRET="..."
    3. Reinicia el servicio. `esta_configurado()` pasará a True y el análisis
       incorporará la comparación con oferta real.

Sin credenciales, todo el proyecto sigue funcionando: la valoración se apoya en
el modelo estadístico y se declara como estimación, que es lo que hace ahora.
"""
from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass, asdict

import httpx

API_KEY = os.getenv("IDEALISTA_API_KEY", "")
SECRET = os.getenv("IDEALISTA_SECRET", "")
TOKEN_URL = "https://api.idealista.com/oauth/token"
SEARCH_URL = "https://api.idealista.com/3.5/es/search"
TIMEOUT = 25.0

_token: dict = {"valor": None, "expira": 0.0}


@dataclass
class ResumenMercado:
    disponible: bool
    total_anuncios: int | None = None
    precio_medio_m2: float | None = None
    precio_mediano_m2: float | None = None
    muestra: int | None = None
    fuente: str = "API de Idealista"
    aviso: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def esta_configurado() -> bool:
    return bool(API_KEY and SECRET)


def _obtener_token() -> str | None:
    """Token OAuth2, cacheado hasta poco antes de expirar."""
    if _token["valor"] and time.time() < _token["expira"]:
        return _token["valor"]
    if not esta_configurado():
        return None

    credenciales = base64.b64encode(f"{API_KEY}:{SECRET}".encode()).decode()
    try:
        r = httpx.post(
            TOKEN_URL, timeout=TIMEOUT,
            headers={"Authorization": f"Basic {credenciales}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials", "scope": "read"},
        )
        r.raise_for_status()
        datos = r.json()
    except Exception:
        return None

    _token["valor"] = datos.get("access_token")
    # Se renueva un minuto antes de caducar para no apurar.
    _token["expira"] = time.time() + max(0, int(datos.get("expires_in", 600)) - 60)
    return _token["valor"]


def precios_zona(latitud: float, longitud: float, radio_km: float = 1.0,
                 tipo: str = "homes") -> ResumenMercado:
    """Precios de oferta alrededor de unas coordenadas.

    Devuelve `disponible=False` con su motivo cuando no hay credenciales, en
    lugar de fallar: el proyecto está pensado para funcionar sin esto.
    """
    if not esta_configurado():
        return ResumenMercado(
            disponible=False,
            aviso="Sin credenciales de Idealista. El acceso se solicita en "
                  "developers.idealista.com y sus condiciones no permiten "
                  "redistribuir los datos, así que cada despliegue necesita la suya.",
        )

    token = _obtener_token()
    if not token:
        return ResumenMercado(disponible=False,
                              aviso="Las credenciales de Idealista no fueron aceptadas.")

    try:
        r = httpx.post(
            SEARCH_URL, timeout=TIMEOUT,
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"operation": "sale", "propertyType": tipo, "country": "es",
                  "center": f"{latitud},{longitud}", "distance": int(radio_km * 1000),
                  "maxItems": 50, "numPage": 1},
        )
        r.raise_for_status()
        datos = r.json()
    except Exception as e:
        return ResumenMercado(disponible=False,
                              aviso=f"La API de Idealista no respondió: {type(e).__name__}")

    anuncios = datos.get("elementList") or []
    precios = [a["priceByArea"] for a in anuncios
               if isinstance(a.get("priceByArea"), (int, float)) and a["priceByArea"] > 0]
    if not precios:
        return ResumenMercado(disponible=True, total_anuncios=datos.get("total", 0),
                              muestra=0,
                              aviso="No hay anuncios con precio por m² en ese radio.")

    precios.sort()
    mediano = (precios[len(precios) // 2] if len(precios) % 2
               else (precios[len(precios) // 2 - 1] + precios[len(precios) // 2]) / 2)
    return ResumenMercado(
        disponible=True,
        total_anuncios=datos.get("total"),
        precio_medio_m2=round(sum(precios) / len(precios), 2),
        precio_mediano_m2=round(mediano, 2),
        muestra=len(precios),
        aviso="Son precios de OFERTA (lo que se pide), no de cierre. "
              "Suelen estar por encima del precio al que se firma.",
    )
