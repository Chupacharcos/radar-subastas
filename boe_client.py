"""
Cliente del Portal de Subastas de la Agencia Estatal BOE.

El portal (subastas.boe.es) publica todas las subastas judiciales, notariales y
administrativas de España — incluidas las de la Agencia Tributaria y la
Seguridad Social. Es información pública y es la fuente donde aparecen las
oportunidades que no llegan a los portales inmobiliarios: cuando un inmueble
sale a subasta, no se anuncia en Idealista.

El portal no ofrece API ni sindicación, así que se lee su HTML. Dos decisiones
sobre eso:

  - Se leen únicamente las páginas de búsqueda y detalle que el portal sirve
    públicamente sin registro, al ritmo de un usuario normal (ver DELAY). No se
    puja, no se accede a nada tras autenticación y no se descarga masivamente.
  - El HTML del portal es de 2015 y estable, pero puede cambiar. Cada extractor
    devuelve None en lugar de reventar, y `parse_detalle` avisa de qué campos no
    encontró, para que un cambio de maquetación se note en vez de producir
    fichas medio vacías en silencio.
"""
from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime

import httpx

BASE = "https://subastas.boe.es"
UA = "Mozilla/5.0 (X11; Linux x86_64) subastas-radar/1.0 (+https://adrianmoreno-dev.com)"
DELAY = 1.2          # segundos entre peticiones: ritmo de lectura humana
TIMEOUT = 30.0

# Códigos del portal (los usa en los parámetros de búsqueda)
ESTADO_EN_CURSO = "EJ"    # celebrándose
TIPO_INMUEBLE = "I"

# Provincias con más volumen de inversión; el resto se consulta por código INE.
PROVINCIAS = {"madrid": "28", "barcelona": "08", "valencia": "46", "sevilla": "41",
              "malaga": "29", "alicante": "03", "vizcaya": "48", "zaragoza": "50"}


@dataclass
class Subasta:
    """Una subasta con el bien asociado. Los importes van en euros."""
    identificador: str
    tipo: str | None = None
    estado: str | None = None
    fecha_inicio: str | None = None
    fecha_fin: str | None = None
    valor_subasta: float | None = None
    tasacion: float | None = None
    puja_minima: float | None = None
    deposito: float | None = None
    tramo_pujas: float | None = None
    cantidad_reclamada: float | None = None
    anuncio_boe: str | None = None
    # Datos del bien
    referencia_catastral: str | None = None
    direccion: str | None = None
    codigo_postal: str | None = None
    localidad: str | None = None
    provincia: str | None = None
    descripcion: str | None = None
    vivienda_habitual: str | None = None
    situacion_posesoria: str | None = None
    visitable: str | None = None
    campos_ausentes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def url(self) -> str:
        return f"{BASE}/detalleSubasta.php?idSub={self.identificador}"


def _texto(fragmento: str) -> str:
    """HTML → texto plano legible."""
    limpio = re.sub(r"<script.*?</script>|<style.*?</style>", " ", fragmento, flags=re.S)
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", limpio))).strip()


def _importe(valor: str) -> float | None:
    """'817.025,89 €' → 817025.89. Devuelve None si no hay número."""
    if not valor:
        return None
    limpio = re.sub(r"[^\d,.]", "", valor)
    if not limpio:
        return None
    # Formato español: el punto separa miles y la coma los decimales.
    limpio = limpio.replace(".", "").replace(",", ".")
    try:
        return float(limpio)
    except ValueError:
        return None


def _fecha_iso(valor: str) -> str | None:
    """El portal incluye la fecha ISO entre paréntesis; se prefiere a la local."""
    m = re.search(r"ISO:\s*([0-9T:+\-]+)", valor)
    if m:
        return m.group(1)
    m = re.search(r"(\d{2})-(\d{2})-(\d{4})\s+(\d{2}:\d{2}:\d{2})", valor)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}T{m.group(4)}" if m else None


def _pares_tabla(html_doc: str) -> dict[str, str]:
    """El portal maqueta los datos como <th>etiqueta</th><td>valor</td>."""
    pares = re.findall(r"<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>", html_doc, re.S)
    return {_texto(k): _texto(v) for k, v in pares if _texto(k)}


class BoeClient:
    def __init__(self, delay: float = DELAY):
        self._delay = delay
        self._ultima = 0.0
        self._cliente = httpx.Client(
            headers={"User-Agent": UA}, timeout=TIMEOUT, follow_redirects=True
        )

    def _get(self, url: str) -> str:
        espera = self._delay - (time.monotonic() - self._ultima)
        if espera > 0:
            time.sleep(espera)
        resp = self._cliente.get(url)
        self._ultima = time.monotonic()
        resp.raise_for_status()
        return resp.text

    def buscar(self, provincia: str = "madrid", limite: int = 40) -> list[str]:
        """Identificadores de subastas de inmuebles en curso en una provincia.

        `provincia` admite nombre ('madrid') o código INE de dos dígitos ('28').
        """
        codigo = PROVINCIAS.get(provincia.lower(), provincia)
        if not re.fullmatch(r"\d{2}", codigo):
            raise ValueError(f"Provincia no reconocida: {provincia!r}")

        url = (
            f"{BASE}/subastas_ava.php"
            f"?campo%5B2%5D=SUBASTA.ESTADO.CODIGO&dato%5B2%5D={ESTADO_EN_CURSO}"
            f"&campo%5B3%5D=BIEN.TIPO&dato%5B3%5D={TIPO_INMUEBLE}"
            f"&campo%5B8%5D=BIEN.COD_PROVINCIA&dato%5B8%5D={codigo}"
            f"&page_hits={min(limite, 100)}"
            f"&sort_field%5B0%5D=SUBASTA.FECHA_FIN&sort_order%5B0%5D=desc&accion=Buscar"
        )
        doc = self._get(url)
        # Orden de aparición = orden de cierre; dict.fromkeys deduplica sin perderlo.
        return list(dict.fromkeys(re.findall(r"SUB-[A-Z]{2}-\d{4}-\d+", doc)))[:limite]

    def detalle(self, identificador: str) -> Subasta:
        """Ficha completa: datos económicos + bien asociado.

        Hay identificadores que aparecen en el listado pero cuya ficha no
        existe: el buscador devuelve subastas de la Agencia Tributaria como
        `SUB-AT-2026-25` y su detalle responde «La subasta no existe». Eso no es
        un cambio de maquetación, es un identificador muerto, y conviene
        distinguirlo: si no, un monitor que sondee la primera subasta de la
        lista puede dar por roto el portal entero.
        """
        html = self._get(f"{BASE}/detalleSubasta.php?idSub={identificador}")
        if "no existe" in html.lower():
            s = Subasta(identificador=identificador)
            s.campos_ausentes = ["ficha_inexistente"]
            return s
        general = _pares_tabla(html)
        # ver=3 es la pestaña de bienes, donde está la referencia catastral.
        bien = _pares_tabla(self._get(f"{BASE}/detalleSubasta.php?idSub={identificador}&ver=3"))

        s = Subasta(
            identificador=identificador,
            tipo=general.get("Tipo de subasta"),
            fecha_inicio=_fecha_iso(general.get("Fecha de inicio", "")),
            fecha_fin=_fecha_iso(general.get("Fecha de conclusión", "")),
            valor_subasta=_importe(general.get("Valor subasta", "")),
            tasacion=_importe(general.get("Tasación", "")),
            puja_minima=_importe(general.get("Puja mínima", "")),
            deposito=_importe(general.get("Importe del depósito", "")),
            tramo_pujas=_importe(general.get("Tramos entre pujas", "")),
            cantidad_reclamada=_importe(general.get("Cantidad reclamada", "")),
            anuncio_boe=general.get("Anuncio BOE"),
            referencia_catastral=bien.get("Referencia catastral"),
            direccion=bien.get("Dirección"),
            codigo_postal=bien.get("Código Postal"),
            localidad=bien.get("Localidad"),
            provincia=bien.get("Provincia"),
            descripcion=bien.get("Descripción"),
            vivienda_habitual=bien.get("Vivienda habitual"),
            situacion_posesoria=bien.get("Situación posesoria"),
            visitable=bien.get("Visitable"),
        )
        # Si el portal cambia de maquetación esto se vacía, y hay que enterarse.
        s.campos_ausentes = [
            campo for campo in ("valor_subasta", "referencia_catastral", "direccion", "localidad")
            if getattr(s, campo) in (None, "")
        ]
        return s

    def buscar_con_detalle(self, provincia: str = "madrid", limite: int = 10) -> list[Subasta]:
        return [self.detalle(i) for i in self.buscar(provincia, limite)]

    def close(self) -> None:
        self._cliente.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
