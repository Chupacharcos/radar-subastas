"""
Comprobación de que los datos siguen siendo ciertos.

El problema de este proyecto no es escribir bien los tipos hoy: es que dentro
de seis meses sigan escritos igual y ya no sean ciertos. Los tipos de ITP
cambian con cada ley autonómica (Cataluña los subió en junio de 2025), los
aranceles se revisan, y el tipo del BCE se mueve cada pocas semanas.

Nada de eso produce un error: la herramienta seguiría calculando con datos
viejos y devolviendo cifras equivocadas con total aplomo. Este módulo existe
para que eso se note.

Uso:
    python vigencia.py            # informe por consola
    python vigencia.py --json     # para engancharlo a un monitor
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

import impuestos
from datos_vivos import tipo_bce

# Un tipo autonómico sin revisar en más de seis meses es sospechoso: las leyes
# de acompañamiento a los presupuestos suelen tocarlos cada ejercicio.
MAX_DIAS_ITP = 180
# El tipo del BCE se publica a diario; más de 30 días es que algo no funciona.
MAX_DIAS_TIPO = 30


@dataclass
class Comprobacion:
    dato: str
    estado: str          # "ok" | "revisar" | "caducado"
    detalle: str
    dias: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _dias_desde(fecha_iso: str) -> int | None:
    try:
        f = datetime.fromisoformat(fecha_iso.replace("Z", "+00:00"))
        if f.tzinfo is None:
            f = f.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - f).days
    except Exception:
        return None


def comprobar() -> list[Comprobacion]:
    resultados: list[Comprobacion] = []

    # 1. Tipos de ITP: cuánto hace que se revisaron a mano.
    dias = _dias_desde(impuestos.REVISADO)
    if dias is None:
        estado, detalle = "revisar", "La fecha de revisión de los tipos no es legible."
    elif dias > MAX_DIAS_ITP:
        estado = "caducado"
        detalle = (f"Los tipos de ITP se revisaron hace {dias} días. Las comunidades "
                   f"los cambian con sus leyes de presupuestos: toca contrastarlos "
                   f"con cada hacienda autonómica.")
    else:
        estado = "ok"
        detalle = f"Revisados hace {dias} días (último repaso: {impuestos.REVISADO})."
    resultados.append(Comprobacion("Tipos de ITP por comunidad", estado, detalle, dias))

    # 2. Tipo de referencia del BCE: que la descarga siga viva.
    t = tipo_bce()
    dias_tipo = _dias_desde(t.fecha_dato) if t.fecha_dato != "desconocida" else None
    if t.es_estimacion:
        resultados.append(Comprobacion(
            "Tipo de interés de referencia", "caducado",
            "No se pudo descargar del Banco de España y se está usando un valor de reserva.",
        ))
    elif dias_tipo is not None and dias_tipo > MAX_DIAS_TIPO:
        resultados.append(Comprobacion(
            "Tipo de interés de referencia", "revisar",
            f"El último dato del Banco de España es del {t.fecha_dato} "
            f"({dias_tipo} días). Puede que la serie haya cambiado de formato.",
            dias_tipo,
        ))
    else:
        resultados.append(Comprobacion(
            "Tipo de interés de referencia", "ok",
            f"{t.valor*100:.2f} % con fecha {t.fecha_dato}, del Banco de España.",
            dias_tipo,
        ))

    # 3. Cobertura: que no falte ninguna comunidad.
    faltan = 17 - len(impuestos.REGIMENES)
    resultados.append(Comprobacion(
        "Cobertura autonómica",
        "ok" if faltan <= 0 else "revisar",
        f"{len(impuestos.REGIMENES)} comunidades cubiertas de 17."
        + ("" if faltan <= 0 else f" Faltan {faltan}."),
    ))

    # 4. Que el portal del BOE siga sirviendo lo que esperamos.
    try:
        from boe_client import BoeClient
        with BoeClient(delay=0) as c:
            ids = c.buscar("madrid", limite=3)
            if not ids:
                resultados.append(Comprobacion(
                    "Portal de Subastas del BOE", "revisar",
                    "La búsqueda no devolvió subastas. Puede no haberlas, o puede "
                    "que el portal haya cambiado su HTML.",
                ))
            else:
                s = c.detalle(ids[0])
                if s.campos_ausentes:
                    resultados.append(Comprobacion(
                        "Portal de Subastas del BOE", "caducado",
                        f"Faltan campos al extraer una subasta ({', '.join(s.campos_ausentes)}). "
                        f"El portal probablemente ha cambiado de maquetación.",
                    ))
                else:
                    resultados.append(Comprobacion(
                        "Portal de Subastas del BOE", "ok",
                        f"Extracción correcta sobre {len(ids)} subastas de prueba.",
                    ))
    except Exception as e:
        resultados.append(Comprobacion(
            "Portal de Subastas del BOE", "caducado",
            f"No se pudo consultar el portal: {type(e).__name__}.",
        ))

    # 5. Catastro: que la API pública siga respondiendo igual.
    try:
        from catastro import consultar
        # Referencia real usada como sonda; si deja de resolver, algo cambió.
        i = consultar("2951517VK2825S0001TB")
        if i.error or not i.superficie_m2:
            resultados.append(Comprobacion(
                "API del Catastro", "caducado",
                f"La consulta de prueba no devolvió datos usables: {i.error or 'sin superficie'}.",
            ))
        else:
            resultados.append(Comprobacion(
                "API del Catastro", "ok",
                f"Responde correctamente ({i.superficie_m2} m², {i.anio_construccion}).",
            ))
    except Exception as e:
        resultados.append(Comprobacion(
            "API del Catastro", "caducado", f"No se pudo consultar: {type(e).__name__}.",
        ))

    # 6. Índices del INE: son anuales, así que lo que hay que vigilar no es que
    #    respondan, sino que no se hayan quedado atrás. Si en 2027 el último dato
    #    del alquiler sigue siendo 2024, o el INE dejó de publicar o la tabla
    #    cambió de identificador.
    try:
        from alquiler_ine import frescura
        anio_actual = datetime.now(timezone.utc).year
        for nombre, datos in frescura().items():
            if datos.get("error"):
                resultados.append(Comprobacion(
                    f"INE · {nombre}", "caducado",
                    f"No se pudo cargar la tabla {datos['tabla_ine']}: {datos['error']}.",
                ))
                continue
            ultimo = datos.get("ultimo_anio")
            retraso = anio_actual - ultimo if ultimo else None
            # El INE publica el año n a lo largo del n+1, así que dos años de
            # retraso es lo normal a principios de año y tres ya no lo es.
            if retraso is None:
                estado, detalle = "caducado", "La tabla no trajo ningún año."
            elif retraso > 2:
                estado = "caducado"
                detalle = (f"El último dato es de {ultimo}, {retraso} años atrás. "
                           f"Revisa si la tabla {datos['tabla_ine']} cambió de "
                           f"identificador o si la operación dejó de publicarse.")
            else:
                estado = "ok"
                detalle = (f"{datos['series']} series, último año publicado {ultimo} "
                           f"(tabla {datos['tabla_ine']}).")
            resultados.append(Comprobacion(f"INE · {nombre}", estado, detalle))
    except Exception as e:
        resultados.append(Comprobacion(
            "Índices del INE", "caducado", f"No se pudieron comprobar: {type(e).__name__}.",
        ))

    # 7. Alquiler real y precio de compra del ministerio. El del alquiler importa
    #    más que ninguno: NO está en el catálogo documentado del ministerio, se
    #    localizó sondeando su CDN. Si un día devuelve un 404, medio proyecto se
    #    queda sin la única fuente de nivel de alquiler que hay en abierto.
    try:
        from alquiler_real import frescura as frescura_alquiler
        datos = frescura_alquiler()
        anio_actual = datetime.now(timezone.utc).year
        if datos.get("error"):
            resultados.append(Comprobacion(
                "Alquiler real por municipio (ministerio)", "caducado",
                f"No se pudo descargar {datos['origen']}: {datos['error']}. Es un "
                "fichero no catalogado; revisa si ha cambiado de nombre o de ruta.",
            ))
        else:
            retraso = anio_actual - (datos.get("ultimo_anio") or 0)
            resultados.append(Comprobacion(
                "Alquiler real por municipio (ministerio)",
                "ok" if retraso <= 2 else "caducado",
                f"{datos['municipios']} municipios, último año {datos['ultimo_anio']}."
                + ("" if retraso <= 2 else " Demasiado atrás: comprueba el fichero."),
            ))
    except Exception as e:
        resultados.append(Comprobacion("Alquiler real por municipio (ministerio)",
                                       "caducado", f"No se pudo comprobar: {type(e).__name__}."))

    try:
        from precio_compra import frescura as frescura_precio
        datos = frescura_precio()
        if datos.get("error"):
            resultados.append(Comprobacion("Valor tasado de la vivienda (ministerio)",
                                           "caducado", f"No se pudo descargar: {datos['error']}."))
        else:
            resultados.append(Comprobacion(
                "Valor tasado de la vivienda (ministerio)", "ok",
                f"{datos['provincias']} provincias, último trimestre {datos['ultimo_periodo']}.",
            ))
            # El detalle municipal es la fuente más frágil del proyecto: un .XLS
            # en un portal heredado, cruzado por nombre. Si el cruce se degrada
            # —porque el ministerio renombre municipios— hay que enterarse.
            muni = datos.get("municipal") or {}
            if muni.get("error"):
                resultados.append(Comprobacion(
                    "Valor tasado por municipio", "caducado",
                    f"No se pudo leer {muni['origen']}: {muni['error']}. Es un Excel de "
                    "formato heredado; comprueba si ha cambiado de ruta o de estructura.",
                ))
            else:
                pocos = muni.get("municipios", 0) < 200
                resultados.append(Comprobacion(
                    "Valor tasado por municipio", "revisar" if pocos else "ok",
                    f"{muni.get('municipios')} municipios cruzados con su código INE, "
                    f"último trimestre {muni.get('ultimo_periodo')}."
                    + (" Son menos de los esperados: el cruce por nombre puede haberse "
                       "degradado." if pocos else ""),
                ))
    except Exception as e:
        resultados.append(Comprobacion("Valor tasado de la vivienda (ministerio)",
                                       "caducado", f"No se pudo comprobar: {type(e).__name__}."))

    return resultados


def main() -> int:
    resultados = comprobar()
    if "--json" in sys.argv:
        print(json.dumps([r.to_dict() for r in resultados], ensure_ascii=False, indent=2))
    else:
        print("\n=== Vigencia de los datos ===\n")
        iconos = {"ok": "✅", "revisar": "⚠️ ", "caducado": "❌"}
        for r in resultados:
            print(f"  {iconos[r.estado]} {r.dato}")
            print(f"      {r.detalle}")
    problemas = [r for r in resultados if r.estado != "ok"]
    if problemas:
        print(f"\n  {len(problemas)} punto(s) a revisar.")
    return 1 if any(r.estado == "caducado" for r in resultados) else 0


if __name__ == "__main__":
    raise SystemExit(main())
