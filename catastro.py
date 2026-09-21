"""
Cliente del Catastro (Sede Electrónica, servicio OVC).

La referencia catastral que publica cada subasta del BOE es la llave que
convierte un anuncio en algo analizable: con ella el Catastro devuelve la
superficie construida, el año y el uso reales del inmueble. Sin eso, un valor
de subasta de 817.000 € no dice nada; con 398 m² pasa a ser 2.053 €/m², que ya
se puede comparar con el mercado de la zona.

Es un servicio público y gratuito, sin clave ni registro:
https://ovc.catastro.meh.es/ovcservweb/ovcswlocalizacionrc/ovccallejero.asmx
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, asdict

import httpx

OVC = "https://ovc.catastro.meh.es/OVCServWeb/OVCWcfCallejero/COVCCallejero.svc/json"
TIMEOUT = 25.0

# Usos catastrales que interesan a un inversor de vivienda. El Catastro marca
# como 'Almacen' o 'Industrial' cosas que no son vivienda aunque salgan en
# subastas de inmuebles.
USOS_VIVIENDA = {"residencial", "vivienda"}


@dataclass
class Inmueble:
    referencia_catastral: str
    uso: str | None = None
    superficie_m2: float | None = None
    anio_construccion: int | None = None
    direccion: str | None = None
    municipio: str | None = None
    provincia: str | None = None
    codigo_ine_provincia: str | None = None
    codigo_ine_municipio: str | None = None
    participacion: float | None = None   # % de titularidad del inmueble
    error: str | None = None

    @property
    def es_vivienda(self) -> bool:
        return bool(self.uso) and self.uso.strip().lower() in USOS_VIVIENDA

    def to_dict(self) -> dict:
        return {**asdict(self), "es_vivienda": self.es_vivienda}


def _buscar(datos, *claves):
    """Recorre el JSON anidado del Catastro buscando la primera clave que exista."""
    if isinstance(datos, dict):
        for clave in claves:
            if clave in datos:
                return datos[clave]
        for valor in datos.values():
            encontrado = _buscar(valor, *claves)
            if encontrado is not None:
                return encontrado
    elif isinstance(datos, list):
        for elemento in datos:
            encontrado = _buscar(elemento, *claves)
            if encontrado is not None:
                return encontrado
    return None


# El servidor del Catastro corta la conexión sin responder cuando le llegan dos
# consultas casi seguidas ("Server disconnected without sending a response").
# No es un error nuestro ni un dato inexistente: es su servidor cerrando el
# socket. Sin reintento, una persona que buscara dos inmuebles seguidos se
# llevaba un error en la segunda búsqueda, y el chequeo de /subastas/vigencia
# daba la fuente por caducada. (2026-09-21)
_ERRORES_TRANSITORIOS = (
    httpx.RemoteProtocolError,   # cierra el socket sin responder
    httpx.ReadError,
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
)
_ESPERAS = (0.6, 1.8)   # dos reintentos; el tercero ya sería insistir de más


def _get_con_reintentos(url: str, params: dict) -> dict:
    """GET al Catastro tolerante a sus cortes de conexión. Devuelve el JSON."""
    ultimo: Exception | None = None
    for intento, espera in enumerate((*_ESPERAS, None)):
        try:
            resp = httpx.get(url, params=params, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except _ERRORES_TRANSITORIOS as e:
            ultimo = e
        except httpx.HTTPStatusError as e:
            # 5xx puede ser pasajero; un 4xx es determinista y no se reintenta.
            if e.response.status_code < 500:
                raise
            ultimo = e
        if espera is None:
            break
        time.sleep(espera)
    raise ultimo if ultimo else RuntimeError("fallo desconocido consultando el Catastro")


def consultar(referencia_catastral: str) -> Inmueble:
    """Datos físicos del inmueble a partir de su referencia catastral."""
    rc = re.sub(r"[^A-Z0-9]", "", (referencia_catastral or "").upper())
    if len(rc) < 14:
        return Inmueble(referencia_catastral=referencia_catastral,
                        error="Referencia catastral incompleta (se esperan 14 o 20 caracteres)")

    try:
        datos = _get_con_reintentos(f"{OVC}/Consulta_DNPRC", {"RefCat": rc})
    except Exception as e:
        return Inmueble(referencia_catastral=rc, error=f"No se pudo consultar el Catastro: {e}")

    # El servicio devuelve el error dentro del propio JSON, con HTTP 200.
    descripcion_error = _buscar(datos, "des")
    if descripcion_error and not _buscar(datos, "bico", "bi"):
        return Inmueble(referencia_catastral=rc, error=str(descripcion_error))

    superficie = _buscar(datos, "sfc")
    anio = _buscar(datos, "ant")
    participacion = _buscar(datos, "cpt")

    return Inmueble(
        referencia_catastral=rc,
        uso=_buscar(datos, "luso"),
        superficie_m2=float(superficie) if superficie not in (None, "") else None,
        anio_construccion=int(anio) if anio not in (None, "") else None,
        direccion=_buscar(datos, "ldt"),
        municipio=_buscar(datos, "nm"),
        provincia=_buscar(datos, "np"),
        codigo_ine_provincia=_buscar(datos, "cp"),
        codigo_ine_municipio=_buscar(datos, "cm"),
        participacion=float(str(participacion).replace(",", ".")) if participacion else None,
    )
