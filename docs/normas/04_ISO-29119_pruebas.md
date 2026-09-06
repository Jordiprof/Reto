# 04 — Pruebas de software

Referencia: **ISO/IEC/IEEE 29119**, partes 1 (conceptos), 2 (procesos), 3
(documentación) y 4 (técnicas).

29119 estructura las pruebas en tres niveles: una **política** (por qué se
prueba), una **estrategia** (cómo se prueba en este proyecto) y los **resultados**
(qué salió). Este documento sigue esa estructura. En su mayor parte no inventa
nada: describe lo que el proyecto ya hacía, y le pone el nombre que la norma usa.

## 1. Política de pruebas (29119-2, §5.2)

La política ya estaba escrita, repartida entre `README.md:297-302` y `E2 §1`. Aquí
se recoge como cuatro reglas:

1. **Un control sin test es una promesa.** Todo control de seguridad tiene un
   test que lo ejerce. Sin test, el control no cuenta como implantado. (`E2 §1`)
2. **Un test que nunca has visto fallar no demuestra nada.** Los controles
   críticos se rompen a propósito y se comprueba que un test se pone rojo.
   (`RNF-08`, `E3 §6.1`)
3. **Los tests no dependen del entorno de quien los corre.** Ni de la red, ni de
   claves reales, ni de qué haya abierto en la máquina.
4. **Toda utilidad sin IA tiene tests.** (`README.md`, Normas del proyecto)

La regla 3 no es teórica: nació de dos fallos reales. Dos tests se pusieron rojos
solo porque había un bot corriendo en el portátil (01/08), y cuatro de cinco
dependían del `.env` de quien los ejecutaba (commit `1ab867e`). Las dos fixtures
`autouse` de `tests/conftest.py` existen por eso, y su docstring lo dice mejor de
lo que lo diría una norma: *"un control que hay que acordarse de pedir no es un
control"*.

## 2. Estrategia (29119-2, §5.3)

### 2.1 Niveles de prueba

| Nivel 29119 | Aquí | Volumen |
|---|---|---|
| Unitario | Funciones puras: cálculo, saneado, clasificación de errores, parseo de fechas | La mayoría de los 815 |
| Integración de componentes | Bucle LLM→tool→resultado→LLM con proveedor falso; RAG contra ChromaDB real en carpeta temporal | `test_llm_loop.py`, `test_rag.py` |
| Sistema | Cerrojo entre **dos procesos de verdad**; bot contra un `Update` de Telegram construido a mano | `test_cerrojo.py`, `test_telegram_*.py` |
| Aceptación | Manual, contra APIs reales | `E4 §3.4` — 15 fallos hallados |

### 2.2 Técnicas (29119-4)

| Técnica | Dónde se aplica |
|---|---|
| Partición de equivalencia y valores límite | Tamaño de fichero, duración de audio, tope de mensaje. `test_documentos.py::test_justo_en_el_limite_de_tamaño_se_acepta` |
| Pruebas basadas en tabla de decisión | Clasificación de errores por código HTTP: `test_llm_router.py::test_gemini_se_clasifica_por_CODIGO_HTTP` |
| Pruebas negativas / de abuso | Inyección de prompt, SSRF, bomba de descompresión, log injection |
| Pruebas de invariante | Lo guardado por un canal lo lee el otro (`RF-18`) |
| **Mutación** | Los controles críticos (§5) |
| Pruebas de documentación | `test_readme.py`: 28 casos cuyo único fin es **que el README no mienta** |

Esa última fila merece una nota. Someter la documentación a tests es poco común
y es, en la práctica, el mismo mecanismo que este kit ha extendido a la
trazabilidad con `scripts/trazabilidad.py`. El proyecto ya había inventado el
patrón; aquí solo se aplica a otro documento.

### 2.3 Criterios de entrada y salida

**Entrada** (para que una rama se pueda considerar lista): la suite pasa en
local, `ruff` limpio, y todo control nuevo llega con su test.

**Salida** (para que el CI se ponga verde):

| Puerta | Comprobación | Dónde |
|---|---|---|
| Lint | `ruff check src tests scripts` | `ci.yml` |
| Pruebas | Los 831 casos en verde | `ci.yml` |
| Cadena de suministro | `pip-audit` sin `continue-on-error` | `ci.yml` |
| Cobertura | No baja del 79 % de rama | job `normas` |
| Trazabilidad | `trazabilidad.py --check` sale 0 | job `normas` |
| Mutación | Los cuatro módulos críticos | job `mutacion` — **a mano todavía**, no es puerta (§5.3) |

Las tres últimas son nuevas de este kit. La de mutación es la única que **no**
bloquea todavía: está detrás de `workflow_dispatch` hasta que se la vea correr
una vez (§5.3).

### 2.4 Entorno y dobles de prueba

**Ninguna prueba automática llama a una API real ni gasta cuota.** Los dobles
viven en `tests/conftest.py`:

- `ProveedorFalso`, un `_ProveedorLLM` al que se le programa de antemano la lista
  de respuestas que devolverá en cada vuelta del bucle.
- `handlers_de_fichero_apartados` (`autouse`), que impide que la batería escriba
  en `logs/agente.log`.
- `cerrojo_aislado` (`autouse`), que redirige el cerrojo a un fichero temporal
  **sin sustituirlo por un simulacro**: el cerrojo se sigue ejerciendo de verdad,
  incluso entre procesos.

Esa distinción —aislar el recurso, no falsificar el mecanismo— es lo que permite
que `test_cerrojo.py` pruebe exclusión mutua real con un subproceso.

## 3. Resultados de la última ejecución (29119-3, informe de pruebas)

Ejecución del **04/09/2026**, commit `35f3445`, en la plataforma objetivo
(**Windows, Python 3.13.15**):

| Resultado | Casos |
|---|---|
| Pasan | **815** |
| Fallan | **0** |
| **Total recolectado** | **815** |

En 54,70 s. Cobertura resultante: **78,01 % de rama**.

**Actualización del 06/09**, al cerrar `NC-06`: la batería sube a **831 casos** en
35 ficheros con los 15 nuevos de `test_main_cli.py`, y la cobertura a **79,86 %**.
Desglose por módulo en `03_ISO-25010_calidad.md` §5.

**Medición previa y por qué se conserva.** Una primera pasada, en un entorno con
Python 3.11 y sin salida a internet, dio *808 pasan · 2 se saltan · 5 no
ejecutables*. Los 5 son de `test_documentos.py` y fallaban con
`httpx.ProxyError: 403 Forbidden` al descargar el modelo de embeddings. El
informe los declaró **no ejecutables por el entorno, no defectos del producto**, y
repetir la medición en la plataforma real lo confirmó: pasan los 815. Se deja
constancia de las dos ejecuciones porque un informe de pruebas que esconde lo que
no pudo ejecutar no sirve de nada — y porque la afirmación de que aquello no era
un defecto no valía hasta que alguien la comprobó.

## 4. Distribución

La tabla completa fichero a fichero está en `E4 §3.1` y **la verifica un script**
en cada CI: `trazabilidad.py` compara esa tabla contra `pytest --collect-only` y
se pone rojo si un fichero falta, sobra o declara un número que no es. Esa
comprobación nació de encontrar la tabla desactualizada (`NC-01`).

Concentración por área:

| Área | Casos | % |
|---|---|---|
| Seguridad (acceso, SSRF, ficheros, logs, cifrado, redirecciones) | ~204 | 25 % |
| Herramientas y validación de argumentos | 126 | 15 % |
| Telegram (UX, voz, presentación, condensar) | 80 | 10 % |
| Proveedores LLM (router, cuota, dialectos, caída) | ~108 | 13 % |
| Memoria y persistencia | 67 | 8 % |
| Resto | ~230 | 29 % |

Una cuarta parte de la suite prueba seguridad. Es coherente con `RNF-06` siendo el
requisito rector del proyecto.

## 5. Validación por mutación (`RNF-08`)

Aquí está la parte más valiosa de la estrategia y también la peor sostenida.

### 5.1 Qué se hizo

`E3 §6.1` documenta ocho mutaciones aplicadas a mano a controles críticos. Seis
fueron detectadas y **dos sobrevivieron**:

| Mutación | Resultado |
|---|---|
| Mover la puerta de la lista blanca al grupo 0 | 🔴 detectada |
| `block=False` en la puerta | 🔴 detectada — y destapó que `handler.block` no es un `bool` sino un centinela cuyo `repr` es `True` pero no **es** `True` |
| Lista blanca ilegible tratada como "permitir a todos" | 🔴 detectada |
| `user_id` en claro en el log | 🔴 detectada |
| Quitar las comillas del `.env` multilínea | 🔴 detectada — bug real: el guardián se quedaba con **cero** dominios, en silencio |
| Quitar el aviso de tamaño en el `.docx` | 🔴 detectada |
| `netloc` en vez de `hostname` en el guardián | 🟢 **sobrevivió** → test flojo, reescrito |
| Guarda de lista vacía | 🟢 **sobrevivió** → resultó ser solo un mensaje |

**El valor está en las dos que sobrevivieron**: no encontraron fallos en el
código, encontraron *tests que no comprobaban lo que decían comprobar*. Eso es
justo lo que la cobertura no puede detectar, y la razón por la que este kit no
propone perseguir el 100 %.

Los tests que detectan cada mutación llevan ahora el marcador
`@pytest.mark.mutacion(...)`, así que la relación mutación→test dejó de vivir
solo en prosa.

### 5.2 Qué fallaba

**Se hizo a mano, una vez, y nada lo volvía a ejecutar.** `RNF-08` es el
requisito más exigente del proyecto y su verificación caducó el día que se
escribió. Fue la no conformidad `NC-07`, **cerrada el 06/09**.

### 5.3 Automatizado: `mutmut` sobre los cuatro módulos críticos

Acotado a los cuatro módulos donde vive la seguridad:

| Módulo | Líneas | Qué protege |
|---|---|---|
| `red_segura.py` | 252 | Guardián anti-SSRF |
| `cerrojo.py` | 140 | Exclusión mutua entre procesos |
| `storage.py` | 342 | Cifrado en reposo |
| `documentos.py` | 479 | Extensión, tamaño, bomba de descompresión |
| **Total** | **1.213** | |

Sobre las 11.205 líneas de `src/` sería inviable: cada mutante exige una pasada
entera de la batería. Acotarlo a 1.213 líneas —el 11 % del código, y el 100 % de
los controles que fallarían abriéndose— es la única forma de que esto llegue a
ejecutarse de verdad.

**Cómo se ejecuta.** `mutmut run`, a secas. Qué se muta y con qué tests se
comprueba vive en `[tool.mutmut]` de `pyproject.toml`, para que el comando sea
literalmente el mismo en local y en el CI: si divergen, esto vuelve a ser una
promesa sin probar.

**El *runner* es la decisión de diseño, no un detalle.** Por defecto `mutmut`
lanza la batería entera por cada mutante: 831 casos × ~55 s × ~300 mutantes son
**más de cuatro horas**, y GitHub corta un job a las seis. Se acota a los tests
que apuntan a esos cuatro módulos y la pasada baja a menos de 2 s. La medida
sigue siendo precisa: no dice *"la batería caza esta mutación"*, dice **"los
tests escritos para este módulo cazan esta mutación"**, que es justo lo que
`RNF-08` pregunta.

**Primera medición real (06/09)**, sobre `red_segura.py`, `cerrojo.py` y
`storage.py` — `documentos.py` queda fuera de esta cifra porque sus tests
descargan el modelo de *embeddings* y el entorno de medición no tenía red:

| | |
|---|---|
| Mutantes generados | **167** |
| Muertos 🎉 | **100** |
| Supervivientes 🙁 | **67** |

**Qué significa ese 67, dicho con precisión.** La mayoría es ruido: `mutmut` 2.x
mutila *cada literal de cadena*, así que cambiar un mensaje de log o una clave de
diccionario y que nadie proteste no informa de nada. Por eso el job **informa y
no vigila** (`|| true` en `ci.yml`): un control que se pone rojo por ruido se
aprende a ignorar, y ahí deja de ser un control. Se fijará umbral cuando se sepa
cuántos supervivientes son reales.

**Y uno no era ruido.** `_es_interna()` de `red_segura.py` termina en un
`except ValueError: return True` — fallar cerrado ante una dirección ilegible,
con su comentario explicándolo. Invertirlo a `return False` **dejaba los 38 tests
del fichero en verde**: la doctrina estaba escrita y nada la sujetaba. Cerrado
con un test propio, validado rompiendo el control y viéndolo en rojo. La primera
ejecución de mutación del proyecto encontró un control sin test en el módulo más
delicado que hay, después de 830 casos en verde y 79,86 % de cobertura de rama.

El job sigue detrás de `workflow_dispatch` y no en la puerta de cada push: aun
acotado, sigue siendo caro para un push, y su valor está en mirarlo, no en que
frene nada.

### 5.4 La mutación aplicada a este propio kit

El control nuevo que introduce esta auditoría (`scripts/trazabilidad.py`) se ha
sometido a su propia doctrina antes de darlo por bueno:

| Mutación aplicada | Resultado |
|---|---|
| Un test apunta a un requisito inexistente (`RF-99`) | 🔴 detectada — `TRZ-01`, salida 1 |
| Se le quita el ancla a un requisito crítico (`RF-11`) | 🔴 detectada — `TRZ-02`, salida 1 |
| Se desactualiza un conteo de `E4 §3.1` | 🔴 detectada — `DOC-02`, salida 1 |

Un control de trazabilidad que no se pusiera rojo al romperlo sería exactamente
la promesa que `E2 §1` dice no aceptar.

## 6. Pruebas manuales contra APIs reales

29119 las llama pruebas de aceptación; el proyecto las llama "probar en real" y
son, medidas por defectos encontrados, la técnica más productiva de todas:
**15 fallos con causa raíz documentada** en `E4 §3.4`, incluido el mejor hallazgo
del proyecto —un mensaje de error que bloqueaba correctamente un acceso a la red
interna pero **enseñaba cómo saltarse la protección**—.

Merece la pena registrar por qué esto no se automatizó. `diario:173` documenta la
decisión de **descartar** un *mini eval harness*: las baterías manuales
encontraron 15 fallos reales que un harness automático, midiendo contra un
criterio inventado a posteriori, no habría encontrado ni uno. Es una decisión
razonada y registrada, no una omisión — y en términos de 29119 es perfectamente
válida: la norma pide que la estrategia esté justificada, no que todo sea
automático.

**Límite honesto**: son manuales, así que no se repiten en cada cambio. Lo que
las hace sostenibles es que cada fallo que encontraron acabó convertido en un
test automático. Esa es la parte que sí se repite.

## 7. Resumen frente a 29119

| Elemento que pide la norma | Estado |
|---|---|
| Política de pruebas documentada | ✅ §1 — existía, repartida; aquí se recoge |
| Estrategia de pruebas | ✅ §2 |
| Niveles definidos | ✅ §2.1 |
| Técnicas justificadas | ✅ §2.2 |
| Criterios de entrada y salida | ✅ §2.3 |
| Entorno y dobles documentados | ✅ §2.4 |
| Informe de resultados | ✅ §3 |
| Trazabilidad requisito → prueba | 🟡 31 de 46 (`NC-05`) |
| Gestión de incidencias de prueba | 🟡 En el diario y en los ADR, sin registro formal |
| Medición y mejora del proceso | ✅ Mutación automatizada: 167 mutantes, 100 muertos (`NC-07` cerrada) |
