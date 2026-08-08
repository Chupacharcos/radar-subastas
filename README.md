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
GET  /subastas/alquiler?codigo_municipio=28079     Evolución del alquiler frente al precio
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
| `deteccion-zonas-revalorizacion` | Señal de revalorización por zona. **Sus €/m² por barrio son valores de referencia, no precios de mercado observados**, y así se declaran en cada respuesta | Ídem |
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
> Su consulta está protegida con reCAPTCHA Enterprise, así que no es
> automatizable de forma fiable, y el ministerio no publica una descarga masiva.
> Hasta que la haya, el **nivel** del alquiler se estima con la rentabilidad
> bruta típica de la provincia y se marca como estimación.

### La mitad del problema del alquiler que sí tiene solución

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

./venv/bin/python tests/test_motor.py      # 136 comprobaciones
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
| Fuentes | BOE (HTML público) · Catastro (JSON) · INE (CSV: Atlas de renta, IPVA, IPV) · Banco de España · OpenStreetMap |
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
  ninguno de los dos. El INE publica sus distritos numerados y sin nombre, así que
  la correspondencia con los barrios se verificó cruzando esa renta con el orden
  socioeconómico conocido de cada ciudad; sólo están **Madrid y Barcelona**,
  porque son las dos que se pudieron comprobar así.
- **Por sección censal**, en forma de horquilla. Las 2.450 secciones de Madrid
  van de 17.450 € a 104.774 €. Las secciones enteras no se guardan porque sin la
  cartografía del seccionado no se sabe en qué sección cae una dirección, pero la
  horquilla ya avisa de cuánto esconde la media.

> Un detalle que hay que declarar: **el INE censura por arriba**. 82 de las 2.450
> secciones de Madrid publican exactamente 104.774 €, que es un techo, no un
> máximo real. El destilado lo detecta y lo marca como `maximo_censurado`, para
> no presentar un tope como si fuera un dato.

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
