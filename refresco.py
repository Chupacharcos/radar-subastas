"""
Que los datos no se queden viejos sin que nadie se entere.

Todas las fuentes se destilan una vez y se cachean en disco, porque descargarlas
en cada petición sería absurdo: el fichero de alquileres del ministerio pesa
37 MB y el Atlas del INE 33 MB por provincia. El problema es el otro extremo:
esas cachés **no caducaban**. Si el ministerio publica el trimestre siguiente, la
herramienta seguiría sirviendo el anterior indefinidamente y con total aplomo,
que es justo el fallo que este proyecto persigue en todo lo demás.

La consulta de un usuario nunca espera a una descarga: se sirve siempre lo
cacheado. Lo que hace este módulo es **medir la edad** de cada caché y permitir
refrescarlas fuera de banda, desde `vigencia.py` o a mano.

El plazo depende de cada fuente, no es uno solo:

  - **Trimestrales** (valor tasado, fianzas): a los 40 días ya debería haber
    trimestre nuevo o estar a punto.
  - **Anuales** (alquiler del ministerio, índices del INE, Atlas de renta): 100
    días. Publican una vez al año, así que mirar cada tres meses basta y sobra.
  - El **Euríbor** no entra aquí: ya se refresca solo cada siete días en
    `datos_vivos`, porque es diario y pesa nada.

Uso:
    python refresco.py                 # informe de edades
    python refresco.py --refrescar     # vuelve a descargar lo caducado
    python refresco.py --refrescar --todo
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

DATOS = Path(__file__).parent / "data"

TRIMESTRAL = 40
ANUAL = 100


@dataclass
class EstadoCache:
    nombre: str
    fichero: str
    dias: int | None
    limite: int
    caducada: bool
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# Cada caché con su plazo y con cómo se vuelve a generar. La función de refresco
# se importa perezosamente para que un módulo roto no impida ver el informe.
FUENTES: list[tuple[str, str, int, str]] = [
    ("Alquiler por municipio (ministerio)", "alquiler_real/mivau_municipios.json",
     ANUAL, "alquiler_real:_carga"),
    ("Fianzas de Cataluña", "alquiler_real/fianzas_catalunya.json",
     TRIMESTRAL, "alquiler_real:_fianzas_catalunya"),
    ("Fianzas de la Comunitat Valenciana", "alquiler_real/fianzas_valencia.json",
     TRIMESTRAL, "alquiler_real:_fianzas_valencianas"),
    ("Valor tasado por provincia", "precio_compra/valor_tasado.json",
     TRIMESTRAL, "precio_compra:_carga"),
    ("Valor tasado por municipio", "precio_compra/valor_tasado_municipal.json",
     TRIMESTRAL, "precio_compra:_carga_municipal"),
    ("IPVA por municipio", "alquiler/59060.json", ANUAL, "alquiler_ine:59060"),
    ("IPVA por distrito", "alquiler/59061.json", ANUAL, "alquiler_ine:59061"),
    ("IPV por comunidad", "alquiler/80271.json", ANUAL, "alquiler_ine:80271"),
]


def _edad_dias(fichero: Path) -> int | None:
    """Días desde que se descargó, según la marca que guarda el propio fichero."""
    try:
        datos = json.loads(fichero.read_text(encoding="utf-8"))
    except Exception:
        return None
    marca = datos.get("descargado") or datos.get("obtenido")
    if not marca:
        return None
    try:
        cuando = datetime.fromisoformat(marca)
    except ValueError:
        return None
    if cuando.tzinfo is None:
        cuando = cuando.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - cuando).days


def estado() -> list[EstadoCache]:
    """Edad de cada caché frente a su plazo. Incluye el Atlas, provincia a provincia."""
    resultado: list[EstadoCache] = []
    for nombre, ruta, limite, _ in FUENTES:
        fichero = DATOS / ruta
        if not fichero.exists():
            resultado.append(EstadoCache(nombre, ruta, None, limite, False,
                                         "todavía no se ha descargado nunca"))
            continue
        dias = _edad_dias(fichero)
        resultado.append(EstadoCache(nombre, ruta, dias, limite,
                                     dias is not None and dias > limite,
                                     None if dias is not None else "sin marca de descarga"))

    # El Atlas del INE es un fichero por provincia y se descarga bajo demanda, así
    # que sólo se juzgan las que ya existen.
    for fichero in sorted((DATOS / "renta").glob("*.json")):
        dias = _edad_dias(fichero)
        resultado.append(EstadoCache(
            f"Atlas de renta · provincia {fichero.stem}", f"renta/{fichero.name}",
            dias, ANUAL, dias is not None and dias > ANUAL,
            None if dias is not None else "sin marca de descarga"))
    return resultado


def refrescar(todo: bool = False) -> list[dict]:
    """Vuelve a descargar lo caducado. Con `todo`, absolutamente todo.

    Pensado para ejecutarse fuera de una petición de usuario: son cientos de MB
    y varios minutos. Cada fuente se refresca por separado y un fallo no impide
    intentar las demás, porque perder una fuente no es motivo para quedarse sin
    actualizar el resto.
    """
    import alquiler_ine
    import alquiler_real
    import precio_compra
    import renta_ine

    acciones = {
        "alquiler_real:_carga": lambda: alquiler_real._carga(forzar=True),
        "alquiler_real:_fianzas_catalunya": lambda: alquiler_real._fianzas_catalunya(forzar=True),
        "alquiler_real:_fianzas_valencianas": lambda: alquiler_real._fianzas_valencianas(forzar=True),
        "precio_compra:_carga": lambda: precio_compra._carga(forzar=True),
        "precio_compra:_carga_municipal": lambda: precio_compra._carga_municipal(forzar=True),
        "alquiler_ine:59060": lambda: alquiler_ine._carga(59060, forzar=True),
        "alquiler_ine:59061": lambda: alquiler_ine._carga(59061, forzar=True),
        "alquiler_ine:80271": lambda: alquiler_ine._carga(80271, forzar=True),
    }

    caducadas = {e.fichero for e in estado() if e.caducada or e.error}
    hecho: list[dict] = []
    for nombre, ruta, _, clave in FUENTES:
        if not todo and ruta not in caducadas:
            continue
        try:
            acciones[clave]()
            hecho.append({"fuente": nombre, "ok": True})
        except Exception as e:
            hecho.append({"fuente": nombre, "ok": False, "error": f"{type(e).__name__}: {e}"})

    for fichero in sorted((DATOS / "renta").glob("*.json")):
        ruta = f"renta/{fichero.name}"
        if not todo and ruta not in caducadas:
            continue
        try:
            renta_ine._carga_provincia(fichero.stem, forzar=True)
            hecho.append({"fuente": f"Atlas de renta · {fichero.stem}", "ok": True})
        except Exception as e:
            hecho.append({"fuente": f"Atlas de renta · {fichero.stem}", "ok": False,
                          "error": f"{type(e).__name__}: {e}"})
    return hecho


def main() -> int:
    estados = estado()
    if "--refrescar" in sys.argv:
        hecho = refrescar(todo="--todo" in sys.argv)
        if not hecho:
            print("Nada que refrescar: ninguna caché ha pasado su plazo.")
            return 0
        for h in hecho:
            print(f"  {'✅' if h['ok'] else '❌'} {h['fuente']}"
                  + ("" if h["ok"] else f" — {h['error']}"))
        return 1 if any(not h["ok"] for h in hecho) else 0

    print("\n=== Edad de las cachés ===\n")
    for e in estados:
        icono = "❌" if e.caducada else ("⚠️ " if e.error else "✅")
        edad = f"{e.dias} d" if e.dias is not None else "—"
        print(f"  {icono} {e.nombre:44} {edad:>7} (plazo {e.limite} d)"
              + (f" · {e.error}" if e.error else ""))
    caducadas = [e for e in estados if e.caducada]
    if caducadas:
        print(f"\n  {len(caducadas)} caché(s) han pasado su plazo. "
              "Ejecuta: python refresco.py --refrescar")
    return 1 if caducadas else 0


if __name__ == "__main__":
    raise SystemExit(main())
