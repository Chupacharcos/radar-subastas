"""
Evaluación de riesgo de una subasta y comprobaciones previas a pujar.

Un buscador que sólo ordene por descuento es peligroso. En subasta se compra
sin ver el inmueble por dentro, a menudo con alguien viviendo en él, y con
cargas que pueden no cancelarse. Quien puja sin mirar esto pierde el depósito,
o algo peor: se adjudica una vivienda que tardará años en poder usar.

Cada riesgo lleva su porqué en lenguaje llano, porque el objetivo no es dar un
número sino que alguien entienda dónde se está metiendo antes de bloquear un
depósito de decenas de miles de euros.

No es asesoramiento legal. Antes de pujar hay que pedir la nota simple
registral y leer el edicto completo de la subasta.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict, field

CRITICO, ALTO, MEDIO, BAJO = "critico", "alto", "medio", "bajo"
PESO = {CRITICO: 40, ALTO: 25, MEDIO: 12, BAJO: 4}


@dataclass
class Riesgo:
    codigo: str
    nivel: str
    titulo: str
    explicacion: str
    que_hacer: str


@dataclass
class Evaluacion:
    puntuacion: int              # 0 = limpio, 100 = máximo riesgo
    nivel: str
    riesgos: list[dict] = field(default_factory=list)
    checklist: list[dict] = field(default_factory=list)
    aviso: str = ("Esto no es asesoramiento legal ni financiero. Antes de pujar, "
                  "pide la nota simple en el Registro de la Propiedad y lee el edicto "
                  "completo de la subasta.")

    def to_dict(self) -> dict:
        return asdict(self)


def _ocupacion(texto: str | None) -> Riesgo | None:
    """La situación posesoria es, con diferencia, lo que más dinero cuesta."""
    if not texto:
        return Riesgo(
            "posesion_desconocida", ALTO,
            "No consta la situación posesoria",
            "El anuncio no dice si la vivienda está ocupada. Si lo está y el ocupante "
            "no se va voluntariamente, recuperarla exige un procedimiento judicial.",
            "Pregunta en el juzgado por el estado posesorio antes de pujar.",
        )
    t = texto.lower()
    if "desconocido" in t:
        return Riesgo(
            "ocupante_desconocido", CRITICO,
            "Ocupante desconocido",
            "Hay alguien en la vivienda y no se sabe con qué título. Puede haber un "
            "contrato de alquiler que te obligue a respetarlo, o una ocupación sin "
            "título que exige un desahucio: entre uno y tres años de juzgado, con "
            "costes legales y sin poder alquilar mientras tanto.",
            "Cuenta el coste y el tiempo del desahucio en tu oferta, o descártala.",
        )
    if "arrendat" in t or "inquilin" in t or "alquil" in t:
        return Riesgo(
            "ocupada_con_contrato", ALTO,
            "Ocupada con contrato de arrendamiento",
            "Si hay un contrato anterior a la hipoteca ejecutada, te subrogas en él: "
            "heredas al inquilino, su renta y su plazo, aunque la renta esté muy por "
            "debajo del mercado.",
            "Pide copia del contrato y su fecha; determina si es anterior a la hipoteca.",
        )
    if "ocupad" in t and "sin" not in t:
        return Riesgo(
            "ocupada", ALTO,
            "Vivienda ocupada",
            "No podrás disponer del inmueble al adjudicártelo. La recuperación puede "
            "requerir procedimiento judicial.",
            "Valora el coste de recuperación de la posesión antes de pujar.",
        )
    if "libre" in t or "desocupad" in t or "vací" in t:
        return None
    return Riesgo(
        "posesion_ambigua", MEDIO,
        f"Situación posesoria poco clara: «{texto}»",
        "El texto del anuncio no permite saber con certeza si podrás usar la vivienda.",
        "Confirma el estado posesorio con el juzgado que gestiona la subasta.",
    )


def evaluar(subasta: dict, inmueble: dict | None = None) -> Evaluacion:
    """Riesgos de una subasta a partir de sus datos y los del Catastro."""
    riesgos: list[Riesgo] = []

    r = _ocupacion(subasta.get("situacion_posesoria"))
    if r:
        riesgos.append(r)

    visitable = (subasta.get("visitable") or "").lower()
    if "sí" not in visitable and "si" not in visitable:
        riesgos.append(Riesgo(
            "no_visitable", ALTO,
            "No se puede visitar",
            "Vas a comprar sin ver el interior. El estado real puede exigir una reforma "
            "integral —instalaciones, humedades, incluso que falten la cocina o los "
            "sanitarios— y eso no se descubre hasta tener las llaves.",
            "Reserva entre 400 y 900 €/m² para reforma según antigüedad, o visita el portal "
            "y pregunta a los vecinos.",
        ))

    if (subasta.get("vivienda_habitual") or "").lower().startswith("s"):
        riesgos.append(Riesgo(
            "vivienda_habitual", ALTO,
            "Es la vivienda habitual del deudor",
            "La ley da al deudor más protección cuando se trata de su vivienda habitual: "
            "plazos más largos, posibilidad de enervar la ejecución pagando la deuda y "
            "más margen para recursos que retrasen la entrega.",
            "Asume plazos más largos hasta poder disponer del inmueble.",
        ))

    texto_completo = " ".join(str(subasta.get(c) or "") for c in ("descripcion", "observaciones"))
    if re.search(r"\bcarga|hipoteca anterior|censo|servidumbre|embargo", texto_completo, re.I):
        riesgos.append(Riesgo(
            "cargas_mencionadas", CRITICO,
            "El anuncio menciona cargas",
            "Las cargas anteriores a la que se ejecuta NO se cancelan: las heredas y se "
            "suman al precio que pagas. Una hipoteca previa puede duplicar el coste real.",
            "Pide la nota simple registral y suma las cargas subsistentes al precio.",
        ))

    valor = subasta.get("valor_subasta")
    reclamada = subasta.get("cantidad_reclamada")
    if valor and reclamada and reclamada > valor:
        riesgos.append(Riesgo(
            "deuda_supera_valor", MEDIO,
            "La deuda reclamada supera el valor de subasta",
            f"Se reclaman {reclamada:,.0f} € sobre un inmueble valorado en {valor:,.0f} €. "
            "Suele indicar cargas acumuladas o un bien sobrevalorado en su día.",
            "Revisa el historial registral: puede haber más acreedores.",
        ))

    if inmueble:
        if inmueble.get("error"):
            riesgos.append(Riesgo(
                "sin_datos_catastro", MEDIO,
                "No se han podido verificar los datos en el Catastro",
                "Sin superficie ni antigüedad oficiales, cualquier cálculo de precio por "
                "metro cuadrado es una estimación.",
                "Consulta la referencia catastral manualmente en la Sede del Catastro.",
            ))
        elif inmueble.get("es_vivienda") is False:
            riesgos.append(Riesgo(
                "no_es_vivienda", MEDIO,
                f"El Catastro no lo clasifica como vivienda (uso: {inmueble.get('uso')})",
                "Si no es residencial, no podrás alquilarlo como vivienda sin un cambio "
                "de uso, que depende del ayuntamiento y no siempre se concede.",
                "Verifica el uso urbanístico en el ayuntamiento antes de pujar.",
            ))
        participacion = inmueble.get("participacion")
        if participacion is not None and participacion < 100:
            riesgos.append(Riesgo(
                "participacion_parcial", CRITICO,
                f"Se subasta sólo el {participacion:.0f}% del inmueble",
                "Comprarías una parte indivisa: serías copropietario con el resto de "
                "titulares y no podrías vender ni alquilar sin contar con ellos.",
                "Sólo tiene sentido si ya eres copropietario o vas a una división de cosa común.",
            ))

    puntos = min(100, sum(PESO[r.nivel] for r in riesgos))
    nivel = (CRITICO if puntos >= 60 else ALTO if puntos >= 35
             else MEDIO if puntos >= 15 else BAJO)

    return Evaluacion(
        puntuacion=puntos,
        nivel=nivel,
        riesgos=[asdict(r) for r in riesgos],
        checklist=_checklist(subasta, riesgos),
    )


def _checklist(subasta: dict, riesgos: list[Riesgo]) -> list[dict]:
    """Comprobaciones antes de bloquear el depósito. El orden importa: primero
    lo que puede hacer que la operación no valga la pena."""
    codigos = {r.codigo for r in riesgos}
    items = [
        ("Nota simple del Registro de la Propiedad",
         "Es el documento que revela las cargas que subsisten tras la subasta. "
         "Cuesta unos 10 € y es la comprobación más rentable que existe.", True),
        ("Leer el edicto completo de la subasta",
         "El anuncio del portal es un resumen. El edicto contiene las condiciones "
         "particulares, que mandan sobre lo demás.", True),
        ("Confirmar la situación posesoria con el juzgado",
         "Saber si hay alguien dentro y con qué título cambia por completo el cálculo.",
         "ocupante_desconocido" in codigos or "posesion_desconocida" in codigos),
        ("Presupuestar la reforma sin haber visto el interior",
         "Al no poder visitarlo, presupuesta el peor escenario razonable para el año "
         "de construcción del inmueble.", "no_visitable" in codigos),
        ("Comprobar deudas con la comunidad de propietarios",
         "El adjudicatario responde de las cuotas del año en curso y los tres anteriores.",
         True),
        ("Verificar el ITP de la comunidad autónoma",
         "Va del 4% al 10% según dónde compres: sobre 150.000 € son hasta 9.000 € de "
         "diferencia.", True),
        ("Tener el depósito disponible y saber cuándo se devuelve",
         f"Hay que bloquear {subasta.get('deposito') or 'el importe exigido'} € para pujar; "
         "si no ganas se devuelve, pero tarda.", True),
        ("Calcular el plazo real hasta poder alquilar",
         "Entre adjudicación, testimonio, inscripción registral y toma de posesión pueden "
         "pasar meses; con ocupantes, años. Son meses sin ingresos.", True),
    ]
    return [{"item": t, "por_que": p} for t, p, aplica in items if aplica]
