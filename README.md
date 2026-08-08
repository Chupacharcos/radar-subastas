# Radar de Subastas — oportunidades inmobiliarias donde nadie mira

Cuando un inmueble sale a subasta judicial, **no se anuncia en los portales
inmobiliarios**. Aparece en el Portal de Subastas del BOE, entre miles de
expedientes, con un buscador de 2015 que no calcula nada: ni cuánto vale el
inmueble, ni cuánto renta, ni qué riesgos tiene.

Este proyecto responde a la única pregunta que importa ante una subasta:
**¿es una oportunidad o una trampa?**

**Licencia:** MIT (ver [LICENSE](LICENSE)) — uso libre, incluido comercial,
manteniendo el aviso de copyright. Sin garantía ni soporte incluidos.

## Qué hace

```
Portal de Subastas del BOE     ──►  qué se subasta y por cuánto
        │ referencia catastral
        ▼
Sede Electrónica del Catastro  ──►  superficie, año y uso reales
        │
        ├──► modelo de precios        ──►  cuánto vale en el mercado
        ├──► zonas de revalorización  ──►  si la zona sube
        └──► motor financiero          ──►  qué deja al mes de verdad
                    │
                    ▼
        semáforo de riesgo + comprobaciones antes de pujar
```

### Ejemplo real

Subasta `SUB-JA-2026-265154`, Las Rozas (Madrid), consultada en agosto de 2026:

| | |
|---|---|
| Sale a | 817.026 € — 2.053 €/m² |
| Valor de mercado estimado | 1.554.800 € — 3.907 €/m² |
| **Descuento** | **47,5 %** |
| Cash-flow estimado | +2.473 €/mes |
| **Riesgo** | **CRÍTICO (90/100)** |

Ese 47 % parece un chollo. El semáforo explica por qué probablemente no lo es:
**ocupante desconocido**, **no visitable** y **vivienda habitual del deudor**.
Quien puje bloquea 40.851 € de depósito para adjudicarse una vivienda que quizá
no pueda usar en tres años.

Un buscador que sólo muestre descuentos es peligroso. Ese es el motivo de que
este muestre el riesgo con el mismo tamaño que la rentabilidad.

## Por qué los números no son los del folleto

La mayoría de calculadoras dan la **rentabilidad bruta**: alquiler anual entre
precio. Es un número de escaparate. Aquí se descuenta lo que un inversor paga
de verdad:

| Concepto | Por qué importa |
|---|---|
| **ITP** | Del 4 % al 10 % según la comunidad. Sobre 150.000 €, hasta 9.000 € de diferencia entre Madrid y Cataluña. |
| Notaría, registro, gestoría | No se financian: salen del bolsillo el día de la firma. |
| **Vacancia** | El gasto más olvidado. Un 6 % anual equivale a tres semanas al año sin cobrar. |
| IBI, comunidad, seguro, mantenimiento | Recurrentes y ciertos. |
| **IRPF** | Con la reducción por alquiler de vivienda habitual aplicada. |

Sobre un piso de 150.000 € en Madrid alquilado a 900 €/mes: **6,69 % bruto
frente a 4,67 % neto**. Dos puntos de diferencia es la distancia entre una
inversión que sale y otra que no.

También calcula el **precio máximo** que puedes pagar sin que el cash-flow se
vuelva negativo. Con 900 €/mes de alquiler en Madrid: 188.289 €. Por encima de
esa cifra, cada mes pones dinero.

## Endpoints

```
GET  /subastas/buscar?provincia=madrid&limite=10   Subastas de inmuebles en curso
POST /subastas/analizar                            Análisis completo de una subasta
POST /subastas/calculadora                         Rentabilidad de cualquier operación
GET  /subastas/provincias                          Provincias con atajo por nombre
GET  /health
```

Documentación interactiva (OpenAPI) en `/docs`.

```bash
curl -X POST http://localhost:8010/subastas/calculadora \
     -H 'Content-Type: application/json' \
     -d '{"precio_compra":150000,"alquiler_mensual":900,"provincia":"madrid"}'
```

## Integración, datos y licencia

### De dónde salen los datos

| Fuente | Qué aporta | Acceso |
|---|---|---|
| [Portal de Subastas del BOE](https://subastas.boe.es) | Subastas judiciales, de Hacienda y de Seguridad Social | Público, sin registro |
| [Sede Electrónica del Catastro](https://ovc.catastro.meh.es) | Superficie, año y uso del inmueble | API pública, sin clave |
| `prediccion-precio-inmobiliario` | Valor de mercado (R² 0,90 sobre 21.000 transacciones) | Otro proyecto de este portfolio, MIT |
| `deteccion-zonas-revalorizacion` | Señal de revalorización por zona | Ídem |

**No se usan portales inmobiliarios privados.** Sus APIs exigen aprobación
manual y sus condiciones prohíben redistribuir los datos. Todo lo que hay aquí
procede de fuentes públicas reutilizables.

Sobre el BOE: no ofrece API, así que se lee su HTML público, sólo las páginas
que sirve sin registro y a ritmo de lectura humana (1,2 s entre peticiones). No
se puja, no se accede a nada tras autenticación y no se descarga masivamente.

### Qué es dato y qué es estimación

Esta distinción es deliberada y se refleja en cada respuesta de la API:

- **Dato**: todo lo que viene del BOE y del Catastro. Valor de subasta,
  depósito, fechas, situación posesoria, superficie, año, uso.
- **Estimación**: el valor de mercado (con un error medio del 15,4 %, que la
  respuesta incluye) y el alquiler, cuando el usuario no aporta el suyo.

La API devuelve `avisos` con las limitaciones que apliquen a cada caso: si el
modelo de precios está aproximando una ciudad que no cubre, si el alquiler es
una estimación por rentabilidad típica, o si el Catastro no respondió.

> **El alquiler y SERPAVI.** La fuente ideal sería
> [SERPAVI](https://serpavi.mivau.gob.es/), el sistema estatal de referencia con
> alquileres **declarados a Hacienda** — contratos reales, no precios de anuncio.
> Su consulta está protegida con reCAPTCHA, así que no es automatizable de forma
> fiable. Hasta incorporar su descarga masiva, el alquiler se estima con la
> rentabilidad bruta típica de la provincia y se marca como estimación.

### Tratamiento de datos

| Qué | Dónde | Cuánto tiempo |
|---|---|---|
| Consultas de los usuarios | No se registran | — |
| Datos de subastas | Se consultan en vivo al BOE en cada petición | No se persisten |
| Datos personales | **Ninguno**: no hay cuentas ni formularios | — |

**Qué sale del servidor:** peticiones HTTP al BOE y al Catastro, ambos
organismos públicos. **Este proyecto no usa ningún proveedor de IA**: todo es
consulta de fuentes oficiales y aritmética financiera.

### Despliegue propio y costes

El repositorio es la aplicación completa. Funciona sin los otros dos proyectos
del portfolio: si no responden, se omite la valoración de mercado y se dice.

Código gratuito (MIT). El servicio es ligero —no carga modelos en memoria— y el
coste se reduce a la infraestructura donde se aloje. La implantación y el
mantenimiento corren a cargo de quien lo despliega; el autor no ofrece soporte
ni consultoría.

## Aviso importante

**Esto no es asesoramiento legal, financiero ni de inversión.** Comprar en
subasta tiene riesgos reales: cargas que no se cancelan, ocupantes con derecho a
permanecer, imposibilidad de visitar el inmueble antes de pujar y plazos largos
hasta poder disponer de él.

Antes de pujar, pide siempre la **nota simple** en el Registro de la Propiedad y
lee el **edicto completo** de la subasta. Las comprobaciones que genera la API
son una ayuda, no un sustituto del asesoramiento profesional.

## Instalación

```bash
python -m venv venv && ./venv/bin/pip install -r requirements.txt
./venv/bin/uvicorn api:app --host 127.0.0.1 --port 8010

./venv/bin/python tests/test_motor.py      # 32 comprobaciones
```

Los tests no tocan la red: las fórmulas y la detección de riesgos se prueban
aisladas. El BOE y el Catastro se verifican contra el servicio real, porque un
test que dependa de que haya subastas activas fallaría un lunes cualquiera por
motivos ajenos al código.

## Stack

| Capa | Tecnología |
|---|---|
| API | FastAPI + Uvicorn |
| Fuentes | BOE (HTML público) · Catastro (JSON) |
| Cálculo | Sistema francés de amortización, ITP por comunidad |
| Valoración | Reutiliza los modelos del portfolio vía HTTP |

## Los datos caducan: cómo se mantiene esto vivo

El riesgo real de una herramienta así no es equivocarse hoy, sino seguir
diciendo lo mismo dentro de seis meses cuando ya no sea cierto. Nada de eso da
un error: la calculadora seguiría devolviendo cifras con total aplomo.

| Dato | Cada cuánto cambia | Cómo se mantiene |
|---|---|---|
| Tipo de referencia del BCE | Semanas | Se descarga del Banco de España (serie `ti_1_1`) y se cachea 7 días, declarando siempre la fecha del dato |
| Tipos de ITP | Con cada ley autonómica | Revisión manual fechada en `impuestos.REVISADO`; `vigencia.py` avisa a los 180 días |
| Aranceles notariales | Años | Regulados por RD; revisión manual |
| HTML del portal del BOE | Sin aviso | Cada extracción declara `campos_ausentes`; `vigencia.py` lo comprueba contra el portal real |

```bash
python vigencia.py          # informe por consola
python vigencia.py --json   # para engancharlo a un monitor
curl localhost:8010/subastas/vigencia
```

Comprueba cinco cosas: antigüedad de la revisión de los tipos, que el tipo del
BCE se descargue y sea reciente, que estén las 17 comunidades, que el portal del
BOE siga sirviendo los campos esperados y que la API del Catastro responda.

### Correcciones ya aplicadas por esta verificación

La primera versión llevaba tipos escritos de memoria. Al contrastarlos:

- **Cantabria figuraba al 9 %; el tipo general es el 10 %.** Sobre 200.000 €
  son 2.000 € de diferencia.
- **Cataluña no es un tipo plano**: desde el Decreto Ley 5/2025 es una escala
  10 % / 11 % / 12 % por tramos, con un 20 % para grandes tenedores. Sobre
  817.000 € la diferencia frente al 10 % plano son 2.170 €.
- **Baleares y Extremadura también son escalas**, no tipos únicos.
- **Los aranceles de notaría y registro no son un importe fijo**: escalan con el
  precio. Antes se usaban 2.500 € para todo, lo que sobrestimaba en inmuebles
  baratos y se quedaba corto en los caros.
- En **subasta judicial no hay escritura de compraventa**, sólo el testimonio del
  decreto de adjudicación, así que el coste notarial es menor que en una compra
  ordinaria.

Cada tipo cita ahora su norma en `impuestos.py`, y los tests contrastan las 17
comunidades contra los valores verificados.
