# Radar de Subastas — oportunidades inmobiliarias donde nadie mira

Cuando un inmueble sale a subasta judicial, **no se anuncia en los portales
inmobiliarios**. Aparece en el Portal de Subastas del BOE, entre miles de
expedientes, con un buscador de 2015 que no calcula nada: ni cuánto vale el
inmueble, ni cuánto renta, ni qué riesgos tiene.

Este proyecto responde a una sola pregunta:

> **¿Merece la pena comprar este piso para alquilarlo y que se pague solo?**

«Se paga solo» tiene un significado exacto: el alquiler cubre la cuota de la
hipoteca, el ITP, la notaría, el IBI, la comunidad, el seguro, el mantenimiento,
la vacancia y el IRPF, sin que tengas que poner dinero ningún mes. Todo lo demás
—el descuento sobre el valor tasado, el semáforo de riesgo, la comparación de
municipios— existe para matizar esa respuesta, no para sustituirla.

Y cuando la respuesta es no, se dice **qué haría falta**: cuánta entrada, o
cuántos años, proyectando con la subida del alquiler que el INE mide en ese
municipio concreto.

**Licencia:** MIT (ver [LICENSE](LICENSE)) — uso libre, incluido comercial,
manteniendo el aviso de copyright. Sin garantía ni soporte incluidos.

<!-- LOOP-MAP:START (generado por `php artisan project:loop readme` — no editar a mano) -->

## El bucle que cierra

<p align="center"><img src="https://adrianmoreno-dev.com/bucle/radar-subastas.svg" alt="Mapa del bucle de Radar de Subastas" width="900"></p>

**Para** quien busca oportunidades en subastas judiciales · **Cada vez que sale una subasta**

| Etapa | Qué pasa | Quién |
|---|---|---|
| **1. Disparador** | Encuentro una subasta judicial en el BOE y quiero saber si es una oportunidad. | persona |
| **2. Acción** | Cruza el anuncio con Catastro, el valor de referencia y el alquiler oficial del municipio, y calcula la rentabilidad neta. | software |
| **3. Medición** | El descuento sobre el valor de referencia, el alquiler del municipio, el riesgo y si se paga solo. | software |
| **4. Decisión** | Decido si pujo, si necesito más entrada o si el alquiler no da para los gastos. | persona |

### Lo que no hace

- No sustituye a un asesor legal: no interpreta la ley ni valora la situación jurídica del inmueble.
- No consulta el Registro: solo ve las cargas que menciona el propio anuncio del BOE, no las demás.
- No predice el mercado: proyecta con series históricas del INE, no con previsiones de precios.

### Por qué está construido así

- **Rentabilidad neta** en vez de rentabilidad bruta — La bruta es un número de escaparate. Aquí se descuentan gastos, impuestos y lo que no se financia el día de la firma.
- **Solo fuentes oficiales** en vez de portales inmobiliarios privados — Las subastas judiciales no se anuncian en los portales, y el alquiler por municipio solo existe en el dato del ministerio.

<!-- LOOP-MAP:END -->

## Qué hace

```
Portal de Subastas del BOE     ──►  qué se subasta y por cuánto
        │ referencia catastral
        ▼
Sede Electrónica del Catastro  ──►  superficie, año y uso reales
        │
        ├──► valor tasado oficial     ──►  cuánto vale hoy en ese municipio
        ├──► alquiler declarado       ──►  cuánto se paga de verdad allí
        └──► motor financiero         ──►  qué deja al mes tras impuestos
                    │
                    ▼
        semáforo de riesgo + comprobaciones antes de pujar
```

### Ejemplo real

Subasta `SUB-JA-2026-265154`, Las Rozas (Madrid), consultada en agosto de 2026:

| | |
|---|---|
| Sale a | 817.026 € — 2.053 €/m² |
| Valor de referencia | 1.758.961 € — 4.420 €/m² tasados en Las Rozas (2026T1) |
| **Descuento** | **53,6 %** |
| Alquiler del municipio | 996 €/mes de mediana (Las Rozas, 2024) |
| **Riesgo** | **CRÍTICO (90/100)** |

Ese 53 % parece un chollo. El semáforo explica por qué probablemente no lo es:
**ocupante desconocido**, **no visitable** y **vivienda habitual del deudor**.
Quien puje bloquea 40.851 € de depósito para adjudicarse una vivienda que quizá
no pueda usar en tres años.

Un buscador que sólo muestre descuentos es peligroso. Ese es el motivo de que
este muestre el riesgo con el mismo tamaño que la rentabilidad.

## La respuesta, cuando es que no

Con los tipos de agosto de 2026 (Euríbor 12M al 2,88 %) y una entrada del 30 %,
**78 municipios de los 3.388 con alquiler publicado se pagan solos**. El resto,
no. Eso no es un defecto del cálculo: es el mercado, y decirlo es el motivo de
que la herramienta exista.

En Madrid capital, por ejemplo, ninguno de los 40 municipios comparados se paga
solo al 30 %. Para Getafe hace falta un **57 % de entrada** —183.452 € de tu
bolsillo, 78.501 € más de lo previsto—; o esperar **14 años**, porque la cuota de
una hipoteca a tipo fijo no se mueve y el alquiler de Getafe sube un 3,2 % al año
según el IPVA del INE.

Hay un tercer caso que conviene nombrar: cuando el alquiler no cubre ni los
gastos corrientes, no hay entrada que lo arregle. Ni pagándolo al contado. La
herramienta lo dice con esas palabras en lugar de devolver un «100 % de entrada»
que suena a solución y no lo es.

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

## Endpoints (17)

```
GET  /subastas/buscar?provincia=madrid&limite=10   Subastas de inmuebles en curso
POST /subastas/analizar                            Análisis completo de una subasta
POST /subastas/calculadora                         Rentabilidad de cualquier operación
GET  /subastas/se-pagan-solos?entrada_pct=0.3      Dónde en España se paga solo
GET  /subastas/zonas?provincia=madrid              Municipios comparados como inversión
GET  /subastas/distritos?ciudad=madrid             Renta y alquiler por distrito censal
GET  /subastas/alquiler?codigo_municipio=28079     Evolución del alquiler frente al precio
GET  /subastas/tipo-interes?diferencial=0.008      Euríbor 12M en vivo + diferencial
GET  /subastas/vigencia                            Frescura de todas las fuentes
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
| [Ministerio de Vivienda](https://cdn.mivau.gob.es/portal-web-mivau/Datos_MIVAU/CSV/VDP001_01.csv) | **Alquiler real por municipio**: mediana, P25 y P75 de los arrendamientos declarados a la Agencia Tributaria | CSV público |
| [Ministerio de Vivienda](https://cdn.mivau.gob.es/portal-web-mivau/Datos_MIVAU/CSV/VDP006_01.csv) | **Valor tasado de la vivienda libre** en €/m², por provincia y trimestre | CSV público |
| [Ministerio de Vivienda](https://apps.fomento.gob.es/boletinonline2/sedal/35103500.XLS) | **Valor tasado por municipio** (más de 25.000 habitantes), por trimestre y tramo de antigüedad | Excel público |
| [Fianzas de alquiler de Cataluña](https://analisi.transparenciacatalunya.cat/resource/qww9-bvhh.json) | Alquiler medio de los **contratos nuevos** por municipio y trimestre | API pública |
| [Fianzas de alquiler de la Comunitat Valenciana](https://dadesobertes.gva.es/dataset?q=fianzas+alquiler) | Depósitos uno a uno; la mediana por municipio es el alquiler de los contratos nuevos | API pública |
| [INE, Atlas de renta](https://www.ine.es/dynt3/inebase/index.htm?padre=7132) | Renta del hogar por municipio, **distrito y sección censal** | CSV público |
| [INE, IPVA (op. 432)](https://www.ine.es/dyngs/INEbase/es/operacion.htm?c=Estadistica_C&cid=1254736169903) | Evolución del alquiler por municipio y distrito, con los **contratos declarados a Hacienda** | CSV público |
| [INE, IPV (op. 15)](https://www.ine.es/dyngs/INEbase/es/operacion.htm?c=Estadistica_C&cid=1254736152838) | Evolución del precio de compra por comunidad autónoma | CSV público |

**No se usan portales inmobiliarios privados.** Sus APIs exigen aprobación
manual y sus condiciones prohíben redistribuir los datos. Todo lo que hay aquí
procede de fuentes públicas reutilizables.

Sobre el BOE: no ofrece API, así que se lee su HTML público, sólo las páginas
que sirve sin registro y a ritmo de lectura humana (1,2 s entre peticiones). No
se puja, no se accede a nada tras autenticación y no se descarga masivamente.

### Qué es dato y qué es estimación

Esta distinción es deliberada y se refleja en cada respuesta de la API:

- **Dato**: el BOE y el Catastro (valor de subasta, depósito, fechas, situación
  posesoria, superficie, año, uso), el alquiler del municipio, el valor tasado de
  la provincia, la renta del hogar y los índices del INE. Todos llevan su año y
  su organismo en la respuesta.
- **Medido pero de ámbito más ancho**: cuando el ministerio no publica el
  alquiler de un municipio —omite los pequeños porque con pocos contratos la
  mediana dejaría de ser anónima— se usa la mediana de los municipios de su
  provincia que sí lo publican. Sigue siendo una medición, y la respuesta dice
  `ambito: "provincia"` y con cuántos municipios se ha construido. Lo mismo con
  el precio de compra: municipal si existe, provincial si no, con
  `precio_es_municipal` en cada fila.
- **Lo único que no se mide** es el diferencial que el banco suma al Euríbor: no
  hay fuente oficial abierta del diferencial medio del mercado. Por eso no es una
  constante escondida sino un parámetro (`diferencial`) con un valor por defecto
  declarado, y el aviso lo señala en cada respuesta.

Los supuestos financieros del usuario —entrada, plazo, vacancia, IRPF, IBI— son
entradas del cálculo, no datos: vienen con valores por defecto y se cambian en
cada petición.

La API devuelve `avisos` con las limitaciones que apliquen a cada caso: si el
€/m² del municipio se está estirando a un inmueble de tamaño muy distinto al
mediano, si el alquiler es de ámbito provincial, o si el Catastro no respondió.

> **Lo que se quitó, y por qué.** Hasta agosto de 2026 el valor de mercado salía
> de un modelo entrenado con *idealista18* —anuncios reales, pero de **2018**— y
> el alquiler se derivaba de él con una «rentabilidad bruta típica» que no
> procedía de ninguna fuente citable. Además, la comparación de barrios usaba
> €/m² escritos a mano en otro proyecto del portfolio, y una «señal de
> revalorización» calculada por un modelo entrenado con datos sintéticos. Nada de
> eso está ya: un número inventado no mejora por llevar un aviso al lado.

> **El alquiler y SERPAVI.** La fuente ideal sería
> [SERPAVI](https://serpavi.mivau.gob.es/), el sistema estatal de referencia con
> alquileres **declarados a Hacienda** — contratos reales, no precios de anuncio.
> Su consulta está protegida con reCAPTCHA Enterprise, así que no es
> automatizable de forma fiable, y el ministerio no publica una descarga masiva.
> Hasta que la haya, el **nivel** del alquiler se estima con la rentabilidad
> bruta típica de la provincia y se marca como estimación.

### El alquiler real: dónde estaba el dato

La conclusión de la primera versión fue que el nivel del alquiler estaba
bloqueado. Y la consulta de SERPAVI lo está: reCAPTCHA Enterprise. Pero el
**agregado municipal del que sale SERPAVI se publica en abierto** en el CDN de
datos del ministerio, sin protección de ningún tipo:

    cdn.mivau.gob.es/portal-web-mivau/Datos_MIVAU/CSV/VDP001_01.csv

Trae por municipio, año y tipo de vivienda la **mediana**, el **percentil 25** y
el **percentil 75** del alquiler, la superficie mediana y el recuento de
viviendas — las mismas variables que describe la metodología oficial de SERPAVI
sobre los arrendamientos declarados a la Agencia Tributaria (modelos 100 y 109).
**3.388 municipios.**

Con eso, la rentabilidad deja de ser circular. Antes el alquiler se derivaba del
precio con un porcentaje fijo y todas las zonas rendían igual; ahora Madrid
capital sale a 13,16 €/m² al mes y Móstoles a 9,09 €, y esa diferencia está
medida.

Dos advertencias que el proyecto lleva encima:

- **Ese fichero no está en el catálogo documentado del ministerio.** datos.gob.es
  publica del VDP002 al VDP007, pero no el VDP001; se localizó sondeando el CDN.
  Puede cambiar de ruta o desaparecer sin aviso, así que `vigencia.py` lo
  comprueba en cada pasada y lo marca como caducado si deja de responder.
- Es el alquiler del **parque ya arrendado**, no el de los contratos que se firman
  hoy. Para eso está la segunda fuente: el **registro de fianzas de Cataluña**,
  que publica el alquiler medio de los contratos nuevos por municipio y trimestre.
  En Barcelona, primer trimestre de 2026: **1.137 € de media sobre 8.156 fianzas
  depositadas**, frente a los 900 € de mediana del parque. Un 26 % por encima, que
  es lo que cobraría de verdad quien compre ahora. Donde hay fianzas, mandan.

Que dos organismos distintos —la Agencia Tributaria vía ministerio y el registro
de fianzas de la Generalitat— den cifras coherentes entre sí, y en la dirección
esperable, es la mejor comprobación disponible de que ninguna de las dos está mal
leída.

### Lo que se firma hoy, no lo que se firmó hace años

El dato del ministerio es la mediana del **parque ya arrendado**. Quien compra
para alquilar no cobra eso: cobra lo de los contratos nuevos. Esos los miden los
registros de fianzas, porque la fianza se deposita al firmar, y dos comunidades
los publican en abierto.

Cataluña lo da ya agregado por municipio y trimestre. La Comunitat Valenciana lo
da **depósito a depósito**: 20.319 depósitos de 2026, con la mediana calculada
por municipio. Cada importe es una mensualidad de renta porque el artículo 36.1
de la LAU obliga a depositar «cantidad equivalente a una mensualidad» al alquilar
una vivienda.

La distancia con el parque arrendado no es la misma en las dos, y la diferencia
es informativa: **+26 % en Barcelona y +62 % en Valencia**. No es un error de
lectura. Cataluña topa por ley la renta de los contratos nuevos en zona
tensionada desde 2024 y la Comunitat Valenciana apenas, así que allí los
contratos nuevos sí se van al mercado. Es exactamente el tipo de cosa que la
media del parque esconde.

Donde hay fianzas, mandan sobre el parque: 499 municipios en siete provincias.

### El precio de compra, municipio a municipio

El otro número que faltaba. El fichero de datos abiertos del ministerio sólo
llega a provincia, y esa media miente por los dos extremos: la Comunidad de
Madrid está en **4.048 €/m²**, pero Madrid capital vale **5.466** y Móstoles
**3.026**. Valorar una subasta de la capital con la media provincial la
infravalora un 26 %, y el descuento —el titular del proyecto— sale mal.

El detalle municipal sí existe, pero no en el portal de datos abiertos ni en el
CDN: está en el BoletínOnline, un Excel de formato heredado que sigue vivo y se
actualiza cada trimestre.

    apps.fomento.gob.es/boletinonline2/sedal/35103500.XLS

Trae los municipios de más de 25.000 habitantes, separando vivienda de hasta
cinco años de antigüedad y de más — de modo que, con el año de construcción del
Catastro, se usa el tramo que corresponde en lugar de la media de los dos.

Ese Excel no lleva códigos INE, sólo nombres escritos a su manera («Ejido (El)»,
«Santa Cruz deTenerife» sin espacio). El cruce se hace normalizando el nombre
contra el listado del propio ministerio, que sí lleva código: el 95 % encaja
directo y el resto con una tabla de equivalencias explícita. Cada valor cruzado
se contrasta después con el de su provincia y, si se sale de una banda razonable,
**se descarta**: un dato menos cuesta menos que un precio de otro sitio.

**302 municipios** con precio propio. Los demás siguen con el de su provincia, y
la respuesta lo dice en `precio_es_municipal`.

### La otra mitad: hacia dónde va

El nivel del alquiler no es público, pero **su evolución sí**. El INE publica el
**IPVA**, un índice construido con los mismos contratos declarados a Hacienda que
alimentan SERPAVI, por municipio (los de más de 10.000 habitantes) y por distrito
de las capitales de provincia.

Eso permite responder algo que el importe de una subasta no dice y que decide una
compra a años vista: **si en esa zona el alquiler sube más deprisa que el precio
de compra o al revés**. El otro lado de la comparación es el **IPV**, el índice
oficial de precios de vivienda. En Madrid, 2024: alquiler +3,6 %, precio +7,7 %.
La rentabilidad se está estrechando; comprar hoy renta menos que hace un año.

Dos límites que la respuesta declara siempre, porque callarlos sería vender más
precisión de la que hay:

- **Son índices, no niveles.** Dicen cuánto sube el alquiler, no cuánto se paga.
- **El IPV sólo llega a comunidad autónoma**, mientras que el IPVA llega a
  municipio y distrito. Se compara un dato local con uno regional.

Tampoco hay dato del País Vasco ni de Navarra: el IPVA se construye con
información de la AEAT, y esas dos comunidades tienen haciendas forales.

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

./venv/bin/python tests/test_motor.py      # 271 comprobaciones
```

El BOE y el Catastro no se prueban aquí: un test que dependa de que haya
subastas activas en Madrid fallaría un lunes cualquiera por motivos ajenos al
código. Se verifican contra el servicio real con `vigencia.py`.

Lo que sí se prueba es lo que puede romperse en silencio y arruinar una decisión
de compra: las fórmulas, la detección de riesgos y el emparejamiento de zonas.
Las comprobaciones sobre datos del INE sí bajan sus CSV la primera vez —y de paso
verifican que las tablas siguen existiendo con el mismo identificador.

## Stack

| Capa | Tecnología |
|---|---|
| API | FastAPI + Uvicorn |
| Fuentes | BOE (HTML) · Catastro (JSON) · Ministerio de Vivienda (CSV y XLS: alquiler municipal, valor tasado provincial y municipal) · INE (CSV: Atlas de renta, IPVA, IPV) · Fianzas de Cataluña (API) · Banco de España (Euríbor 12M) · OpenStreetMap |
| Cálculo | Sistema francés de amortización, ITP por comunidad |
| Valoración | Valor tasado oficial del municipio × superficie del Catastro. Sin modelo: no hay microdatos de transacciones recientes en abierto |

## Los datos caducan: cómo se mantiene esto vivo

El riesgo real de una herramienta así no es equivocarse hoy, sino seguir
diciendo lo mismo dentro de seis meses cuando ya no sea cierto. Nada de eso da
un error: la calculadora seguiría devolviendo cifras con total aplomo.

| Dato | Cada cuánto cambia | Cómo se mantiene |
|---|---|---|
| Euríbor a 12 meses | Diario | Se descarga del Banco de España (serie `ti_1_7.7`) y se cachea 7 días, declarando siempre la fecha del dato. Es el índice al que se revisan las hipotecas; el tipo del BCE queda de reserva |
| Tipos de ITP | Con cada ley autonómica | Revisión manual fechada en `impuestos.REVISADO`; `vigencia.py` avisa a los 180 días |
| Aranceles notariales | Años | Regulados por RD; revisión manual |
| HTML del portal del BOE | Sin aviso | Cada extracción declara `campos_ausentes`; `vigencia.py` lo comprueba contra el portal real |
| Fichero de alquiler del ministerio | Una vez al año, y **no está catalogado** | `vigencia.py` lo descarga en cada pasada; si deja de responder lo marca caducado, porque es la única fuente pública del nivel del alquiler |
| Valor tasado de la vivienda | Cada trimestre | `vigencia.py` comprueba el último trimestre publicado |
| Índices del INE (renta, IPVA, IPV) | Una vez al año | `vigencia.py` avisa si el último año publicado se queda más de dos ejercicios atrás: sería señal de que la tabla cambió de identificador o de que la operación dejó de publicarse |

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

## Contexto de zona y métricas de inversor

### El límite legal que invalida cualquier proyección

**Zona tensionada (Ley 12/2023).** Hay más de 300 municipios declarados: 271 en
Cataluña —Barcelona y todo su área metropolitana—, 14 en País Vasco, 21 en
Navarra y varios en Galicia. Ahí, la renta de un contrato nuevo **no puede
superar la del contrato anterior** de los últimos cinco años. Comprar contando
con subir el alquiler a precio de mercado no es una previsión optimista: es
ilegal en esas zonas. Ninguna calculadora del sector lo advierte.

Cuando el municipio no está en la lista pero su provincia tiene declaraciones,
se marca **«probable»** y se pide comprobarlo, en lugar de afirmar que no lo es.

### Renta real del barrio, no supuestos

La renta media del hogar sale del **Atlas de distribución de renta del INE**.
Con ella se calcula el **esfuerzo del inquilino**: si el alquiler supera el 35 %
de lo que entra en los hogares de esa zona, el problema no es que el inquilino no
quiera pagar, es que no puede — y eso predice impago y rotación mejor que ninguna
otra variable.

La media del municipio es demasiado gruesa para eso, así que se baja de grano:

- **Por distrito censal.** En Madrid capital va de 79.274 € en Chamartín a
  32.666 € en Puente de Vallecas. La media del municipio, 49.916 €, no describe a
  ninguno de los dos. El INE publica sus distritos numerados y **sin nombre**, así
  que la correspondencia se verificó cruzando esa renta con el orden
  socioeconómico conocido de cada ciudad, arriba y abajo: Madrid, Barcelona,
  Valencia (06 El Pla del Real 61.479 € / 18 Pobles de l'Oest 32.233 €), Sevilla
  (11 Los Remedios 56.389 € / 04 Cerro-Amate 26.160 €) y Málaga (02 Este
  57.109 € / 06 Cruz de Humilladero 30.570 €).

  **Zaragoza se quedó fuera a propósito.** Tiene 12 distritos en el Atlas, tantos
  como distritos urbanos tiene la ciudad, así que era fácil darla por buena. Pero
  el contraste falla: el 08 —Oliver-Valdefierro en la numeración municipal, de los
  más humildes— sale cuarto por renta, y el 12 —Casablanca, de los más
  acomodados— a mitad de tabla. Sin saber si el INE numera distinto o si sus
  distritos no son los del ayuntamiento, poner nombres sería inventar.
- **Por sección censal**, en forma de horquilla. Las 2.450 secciones de Madrid
  van de 17.450 € a 104.774 €. Las secciones enteras no se guardan porque sin la
  cartografía del seccionado no se sabe en qué sección cae una dirección, pero la
  horquilla ya avisa de cuánto esconde la media.

> Un detalle que hay que declarar: **el INE censura por arriba**. 82 de las 2.450
> secciones de Madrid publican exactamente 104.774 €, que es un techo, no un
> máximo real. El destilado lo detecta y lo marca como `maximo_censurado`, para
> no presentar un tope como si fuera un dato.

> **Un fallo que estuvo escondido meses.** El mapa que dice qué tabla del INE
> corresponde a cada provincia se había construido sondeando, y estaba **mal en 35
> de las 51 provincias**: la de Zaragoza devolvía Ceuta. No producía cifras falsas
> —al emparejar por código INE, un municipio de otra provincia simplemente no
> aparece— pero dejaba sin renta a casi toda España **en silencio**. Sobrevivió
> porque Madrid y Barcelona sí eran correctas, y eran las únicas que los tests
> comprobaban. Ahora el mapa está resuelto tabla por tabla y hay un test que abre
> el CSV real de una muestra de provincias y verifica que contiene lo que dice.

La API JSON del INE rechaza estas tablas por volumen, así que se usa la descarga
CSV oficial: se baja una vez por provincia, se destila a lo mínimo útil y se
cachea. Consultar después es instantáneo.

### Métricas de solvencia

| Métrica | Qué responde |
|---|---|
| **DSCR** | Cuántas veces cubre el ingreso operativo la cuota. Es lo que mira un banco; por debajo de 1,25 aprieta |
| **Punto muerto de ocupación** | Cuántos meses aguanta vacío al año antes de entrar en pérdidas |
| **Estrés de tipos** | Qué pasa si el Euríbor sube 2 puntos. Entre 2021 y 2023 subió más de cuatro |
| **Esfuerzo del inquilino** | El alquiler frente a la renta real del barrio |
| **Coste de oportunidad** | La prima frente a deuda pública a 10 años, que no tiene inquilinos ni derramas |

## Sobre la API de Idealista

`idealista.py` está escrito y probado, pero **desactivado**: su acceso se
concede por solicitud manual y sus condiciones no permiten redistribuir los
datos a terceros, que es lo que hace un servicio público.

Lo legítimo es que **quien despliegue esto pida su propia clave** y acepte esas
condiciones. Entonces basta con exportar `IDEALISTA_API_KEY` e
`IDEALISTA_SECRET` y reiniciar: el análisis empieza a contrastar el valor de
subasta con precios de oferta reales de la zona, además de con el modelo.

Sin credenciales todo funciona igual, apoyándose en el modelo estadístico y
declarándolo como estimación.

## El entorno: qué hay alrededor del inmueble

Lo que hace que un piso se alquile rápido no es el piso, es tener metro a diez
minutos y un supermercado a pie. Y lo que hace que se alquile mal tampoco está
en la ficha: una autovía pegada o una zona sin comercio.

Se usa **OpenStreetMap** vía Overpass. Es la única fuente de equipamiento urbano
gratuita, sin clave, con cobertura nacional y con una licencia (ODbL) que
**permite redistribuir citando la fuente** — a diferencia de Google Places, que
prohíbe mostrar sus datos fuera de sus mapas.

| | Las Rozas (la subasta del ejemplo) | Sol, Madrid |
|---|---|---|
| Tren y metro (1,2 km) | 1 | 69 |
| Supermercados (900 m) | 8 | 158 |
| Colegios | 11 | 24 |
| Zonas verdes | 59 | 91 |

Se devuelven los recuentos crudos con su lectura, nunca una «puntuación de
barrio»: OSM lo mantienen voluntarios y una zona puede estar mejor cartografiada
que otra. Un número redondo aparentaría una precisión que no existe.

La dirección se geocodifica con Nominatim, limpiando antes el formato del BOE
(«CALLE FIDIAS NUMERO 11», «184 PL. 5ª PTA»), que ningún geocodificador entiende
tal cual.

## Fuentes evaluadas y por qué se usa cada una

| Fuente | Estado | Motivo |
|---|---|---|
| Portal de Subastas del BOE | **En uso** | Público, ~15.000 subastas/año |
| Catastro (OVC) | **En uso** | API pública sin clave; la referencia catastral lo conecta todo |
| INE, Atlas de renta | **En uso** | Renta por municipio y sección censal, descarga oficial |
| Banco de España | **En uso** | Tipo de referencia oficial, diario |
| OpenStreetMap (Overpass + Nominatim) | **En uso** | ODbL permite redistribuir citando |
| Idealista | **Preparado, inactivo** | Requiere clave propia; prohíbe redistribuir |
| SERPAVI | Descartado por ahora | Alquileres declarados a Hacienda, pero tras reCAPTCHA |
| Fotocasa, Habitaclia, pisos.com | Descartados | Sin API pública |
| Google Places | Descartado | Prohíbe almacenar y mostrar fuera de sus mapas |
| Ministerio del Interior (criminalidad) | Pendiente | Publica en informes trimestrales, sin API |
| Registradores y Notariado | Pendiente de evaluar | Publican estadística de transacciones reales |
