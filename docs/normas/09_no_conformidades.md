# 09 — No conformidades

Referencia de formato: **ISO 19011:2018** cláusula 6.4.8 (hallazgos de auditoría).

Auditoría del **04/09/2026** sobre el commit `35f3445`. Auditor: el propio autor
— sin independencia, ver `00_alcance.md` §3.

## Clasificación usada

| Nivel | Qué significa |
|---|---|
| **Mayor** | Un requisito declarado no se cumple, o un control declarado no existe |
| **Menor** | El control existe pero es incompleto, manual o no verificable |
| **Observación** | No incumple nada; es deuda que conviene no olvidar |

## Resumen

| Estado | Mayores | Menores | Observaciones | Total |
|---|---|---|---|---|
| Cerradas | 0 | 6 | 3 | **9** |
| Parcialmente corregidas | 1 | 1 | 0 | **2** |
| Abiertas | 0 | 3 | 2 | **5** |
| **Total** | **1** | **10** | **5** | **16** |

**Segunda pasada, 06/09/2026.** Se cierran NC-06, NC-08, NC-13 y NC-14, y NC-05
baja de abierta a parcial. Quedan **cuatro abiertas**: NC-07, NC-10, NC-12 y
NC-15 — y tres de ellas no son cerrables desde el entorno donde se hizo este
trabajo (`mutmut` necesita la batería en verde, `pip-compile` necesita Python
3.13, y la revisión independiente no existe con un solo autor). La única que
depende de una decisión y no de una limitación es **NC-12**.

---

## Cerradas en esta auditoría

### NC-01 · Menor · La documentación de pruebas se había quedado atrás
**CERRADA**

`docs/E4_Entrega_Final.md` §3.1 declaraba **784 casos en 33 ficheros**. La
realidad eran **815 en 34**: `test_noticias.py` (27 casos) no figuraba en la
tabla, `test_readme.py` declaraba 26 y tenía 28, y `test_recuerdo_y_limpiar.py`
declaraba 16 y tenía 18.

Ninguno de esos tres errores es grave. Lo grave es que **nada los detectaba**:
la tabla se mantenía a mano y podía envejecer indefinidamente en silencio.

*Nota sobre un falso positivo.* Una primera lectura de esta auditoría concluyó
que la tabla declaraba 784 donde había 692, y era erróneo: 692 son las funciones
`def test_`, y la tabla cuenta **casos recolectados**, que es lo correcto porque
36 tests usan `@pytest.mark.parametrize` y cada uno expande a varios. Comparar
funciones contra casos habría sido acusar a la documentación de un fallo que no
tenía. Queda escrito aquí porque el error de método importa más que el hallazgo.

**Corrección aplicada**: tabla actualizada a 815/34, y `scripts/trazabilidad.py`
compara ahora la tabla contra `pytest --collect-only` en cada CI (hallazgos
`DOC-01`, `DOC-02`, `DOC-03`).

### NC-02 · Menor · Ningún test decía a qué requisito respondía
**CERRADA**

`grep -rn "\bRF-[0-9]" src/ tests/` devolvía **cero coincidencias**. La
trazabilidad de `E1 §6` existía solo como tabla escrita a mano, sin ancla en el
código, así que no se podía contrastar con nada — el caso de libro de lo que
`E3 §6.2` llama "un audit pegado".

**Corrección aplicada**: marcador `@pytest.mark.requisito(...)` declarado en
`pyproject.toml` con `--strict-markers`, **78 tests anclados**, y matriz generada
en `07_matriz_trazabilidad.md`. Los cinco requisitos de prioridad Crítica
(RF-02, RF-08, RF-11, RF-17, RF-23) están los cinco trazados, y el script se pone
rojo si uno pierde su ancla.

### NC-03 · Menor · La cobertura de código nunca se había medido
**CERRADA**

`requirements-lock.txt` no contenía `coverage` ni `pytest-cov`, y `ci.yml` no la
medía. El proyecto afirmaba una proporción test/código de 1,10:1, que es una
medida de **volumen**, no de cobertura: 12.000 líneas de test pueden ejercitar el
30 % del código.

**Corrección aplicada**: medida por primera vez. **78 % de cobertura de rama**
(3.251 sentencias, 668 sin cubrir; 924 ramas, 83 parciales), sobre Python 3.13 y
con los 815 casos en verde. Detalle por módulo en `03_ISO-25010_calidad.md` §5.

### NC-04 · Observación · La matriz de E1 §6 no estaba desfasada
**CERRADA — sin acción**

Se abrió como sospecha y se cerró al comprobarla: los conteos entre paréntesis de
`E1:207-225` (115, 24, 25, 20, 29, 20, 90, 39, 21, 20, 11, 36, 17, 12) **cuadran
los catorce** con la realidad. El problema de esa tabla es que está incompleta
(NC-05), no que mienta.

---

## Abiertas

> Dos de las de esta sección (NC-09 y NC-10) se corrigieron durante la propia
> auditoría y llevan su estado marcado. Se dejan aquí, en su orden, para que la
> numeración no baile entre versiones del informe.

### NC-05 · Mayor · Identificadores sin verificación trazada
**PARCIALMENTE CORREGIDA**

Empezó en 0 de 46, pasó a 29 con NC-02 y está en **31 de 46** tras anclar RF-13
y RF-25, cuyos tests ya existían. **103 tests llevan ancla.** Siguen sin traza 15:

| Familia | Sin traza | Tratamiento |
|---|---|---|
| Objetivos | OBJ-01 … OBJ-05 (5 de 5) | **Verificables por inspección**, no por prueba. Un objetivo como "documentar el porqué de cada decisión" no tiene test posible, y fingir uno sería peor que declararlo. 29148 admite inspección y demostración como métodos |
| Funcionales | RF-01, RF-04, RF-10 | RF-10 no es un requisito sino un objetivo disfrazado (ver `01` §5). RF-01 y RF-04 se ejercen de hecho en `test_llm_loop.py`, pero sin ancla explícita |
| No funcionales | **RNF-01**, RNF-03, RNF-04 | **RNF-01 es el único que preocupa** — ver abajo. RNF-03 y RNF-04 son propiedades de diseño verificables por inspección: cuatro proveedores tras la misma interfaz, y `pyproject.toml` + lockfile con hashes |
| Casos de uso | CU-02, CU-03, CU-06, CU-07 | Necesitan pruebas de extremo a extremo que hoy no existen |

*Corrección a la primera versión de esta NC*: decía que RNF-04 "ya tiene tests" y
**era falso**. RF-13 y RF-25 sí los tenían y ya están anclados; RNF-04 no tiene
ninguno, y se declara verificable por inspección en vez de inventarle uno.

**Por qué es Mayor y no Menor**: `RNF-01` (ninguna clave en el código ni en el
historial de git) es un requisito de seguridad que hoy se verifica ejecutando
`gitleaks` **a mano**, según `E4 §5.1`. Un control manual que se ejecutó una vez
en agosto no protege el commit de mañana.

**Lo único que queda de verdad: `RNF-01`.** "Ninguna clave en el código ni en el
historial de git" se comprueba con `gitleaks` **a mano**, según `E4 §5.1`. Un
control manual ejecutado una vez en agosto no protege el commit de mañana.

**Por qué no se ha metido `gitleaks` en el CI en esta pasada**: `DEP-05` obliga a
fijar las acciones **por SHA y no por etiqueta**, y desde el entorno donde se
hizo este trabajo no se pudo resolver el SHA de `gitleaks/gitleaks-action`
(la API de GitHub devolvió 403). Inventarse un hash habría roto el CI y la propia
norma que se intenta cumplir. Es un paso de dos minutos desde una máquina con
acceso, y está descrito en la lista de acciones de este documento.

### NC-06 · Menor · `src/main.py` está al 17 % de cobertura
**CERRADA**

`main.py` es el menú de la CLI: eran 339 sentencias de las que **273 no se
ejecutaban nunca**. No es crítico para la seguridad —la superficie expuesta es
el bot, no la CLI— pero era el mayor agujero de la batería y hasta la auditoría
no estaba declarado en ninguna parte.

**Corrección aplicada**: 15 tests nuevos en `tests/test_main_cli.py`, sobre lo
que estaba a cero:

| Qué cubre | Por qué importa |
|---|---|
| `_imprimir_sitios` | La lista blanca tal y como se ve en la CLI: URL completa y pegable, agrupada, y el aviso de que no se siguen redirecciones |
| `mostrar_conversacion` | Que **no** imprima el system prompt, y que una conversación indescifrable avise en vez de reventar (`RNF-02`) |
| `menu_tools` | Que cancelar **no** apague herramientas por sorpresa, y que encender `web` liste los sitios |
| **`main()`** | **El cerrojo (`RF-24`)**: con la memoria ocupada la CLI no arranca, y el cerrojo se suelta aunque la sesión reviente |

Los tres de `main()` son los que más valen: prueban desde la CLI el control que
nació del 31/07, cuando se ejecutó la terminal **con el bot arrancado**.

| Módulo | Antes | Ahora |
|---|---|---|
| **`src/main.py`** | **17 %** (273 sin cubrir) | **34 %** (220 sin cubrir) |
| **TOTAL del proyecto** | **78,01 %** | **79,86 %** |

El umbral del CI sube de 78 a **79**, detrás de la medición. **79 y no 80**
aunque la tabla de `coverage` imprima "80 %": ese 80 está redondeado, el valor
real es 79,86, y `--cov-fail-under` compara contra el número de verdad. Un
umbral de 80 habría tumbado el CI **con la cobertura subiendo**. Se cazó
comprobándolo en local antes de subir.

**Lo que sigue sin cubrir, y por qué**: las líneas 531-1025, que son `_sesion()`
—el bucle interactivo del chat—. Cubrirlo exigiría simular una terminal entera,
y `E3 §6.1` ya establece que lo que vale es la mutación, no el porcentaje. Se
declara como límite conocido, no como tarea pendiente.

### NC-07 · Menor · `RNF-08` exige validación por mutación y se hace a mano

`RNF-08` dice: *"Los controles críticos se validan por mutación, no solo con
tests en verde"*. Es el requisito más exigente del proyecto y el mejor razonado
(`E3 §6.1`: dos de las ocho mutaciones sobrevivieron y destaparon tests que no
comprobaban lo que decían comprobar).

Y se cumple **a mano**. Las ocho mutaciones están escritas en prosa, con fecha,
pero nada las vuelve a ejecutar. Un requisito verificado a mano se verifica una
vez y nunca más.

**Preparado, no cerrado**: `mutmut` está fijado en `requirements-dev.txt` y hay
un job `mutacion` en `ci.yml` acotado a los cuatro módulos críticos
(`red_segura.py`, `cerrojo.py`, `storage.py`, `documentos.py` — 1.213 líneas;
sobre las 11.205 de `src/` sería inviable).

Ese job **no se ejecuta en cada push**: está detrás de `workflow_dispatch`, para
lanzarlo a mano. Dos motivos, y el segundo es el que manda: cada mutante exige
una pasada entera de la batería, y **esta invocación no se ha podido probar
todavía** — se preparó en un entorno con Python 3.11 y sin red, donde la batería
no pasa entera. Convertirla en puerta de cada push sin haberla visto correr una
sola vez sería exactamente el "audit pegado" del que avisa `E3 §6.2`.

**Acción**: lanzarlo a mano una vez, mirar cuánto tarda y qué score da, y
entonces decidir si pasa a ser puerta. Hasta entonces `RNF-08` sigue
verificándose a mano y esta NC sigue abierta.

### NC-08 · Menor · LLM03 y LLM10 no se declaran en la tabla OWASP
**CERRADA**

`E3:199-209` recorre el OWASP Top 10 for LLM Applications y cierra ocho riesgos
más SSRF, todos con ✅. Faltan **LLM03 (envenenamiento de datos de
entrenamiento)** y **LLM10 (robo del modelo)**, sin una línea que diga por qué.

Un hueco sin explicar en una tabla de conformidad se lee como un olvido, aunque
la respuesta sea trivial: aquí ambos **no aplican**, porque el proyecto no
entrena ni aloja modelos propios. Con el matiz de que el índice ChromaDB sí es
un almacén que el usuario alimenta, así que el envenenamiento de la memoria
merece dos líneas propias.

**Corrección aplicada**: las dos filas están ya en `E3 §6`, con su motivo. LLM03
no aplica porque no se entrena ningún modelo, pero se declara su equivalente real
—envenenar el índice ChromaDB— y cómo lo cierra `SEG-07`. LLM10 no aplica porque
no hay modelo propio que robar. La tabla de `E3` ya no tiene huecos sin explicar.

### NC-09 · Menor · `scripts/` no se lintea en el CI
**CERRADA**

`E4 §5.1` declara: *"Lint limpio en **todo** el repo (`ruff check .`, incluido
`scripts/`)"*. El CI ejecuta `ruff check src tests` (`ci.yml:58`). La carpeta
`scripts/` —14 ficheros, incluidos los `.py` de diagnóstico y el nuevo
`trazabilidad.py`— no la mira nadie automáticamente.

Verificado en esta auditoría: `ruff check src tests scripts` sale **limpio** hoy.
El problema no es el estado, es que nada lo sostiene.

**Corrección aplicada**: `ci.yml` ejecuta ahora `ruff check src tests scripts`.
Verificado: sale limpio, incluido el `scripts/trazabilidad.py` nuevo.

### NC-10 · Menor · `pip-audit` entra en el CI sin hash
**PARCIALMENTE CORREGIDA**

`ci.yml:39` instala todo con `--require-hashes` y lo justifica muy bien
(`DEP-04`: una versión fija dice *qué* paquete quieres, el hash fija su
*contenido*). Pero `ci.yml:81` hace `pip install pip-audit` a secas.

Es decir: **la herramienta que audita la cadena de suministro entra sin auditar**,
resolviendo versión y contenido en el momento, desde una cuenta de PyPI que
podría estar comprometida. Es el mismo ataque del que protege la línea de arriba.

**Corrección aplicada**: `pip-audit==2.10.1` queda fijado en
`requirements-dev.txt`, y `ci.yml` lo instala desde ahí en vez de suelto. Eso
cierra lo peor: ya no se resuelve una versión cualquiera en el momento.

**Lo que falta**: fijar el **contenido** por hash, que es de lo que va `DEP-04`.
Requiere generar `requirements-dev-lock.txt` con
`pip-compile --generate-hashes`, y eso hay que hacerlo **desde una máquina con
Python 3.13**: `pip-compile` resuelve con el intérprete que lo ejecuta, y un
lock resuelto en 3.11 puede pinchar en 3.13 bajo `--require-hashes`. Se dejó
sin generar a propósito — enviar un lock que rompe el CI habría sido peor que
no enviarlo. Instrucciones al principio de `requirements-dev.txt`.

### NC-11 · Menor · La fórmula de riesgo de ADR-006 no es ejecutable

`ADR-006:189-197` define cómo se calcula el nivel de riesgo de una herramienta:

```
Nivel = 1 (base) + 1 por capacidad + 2 si el modelo elige el destino
        + 3 si el contenido externo puede disparar una acción
```

El `dataclass Herramienta` de `src/tools.py:1296-1302` tiene exactamente dos
campos: `repetible: bool` y `categoria: str`. **No hay campo de capacidades ni de
nivel.** La fórmula vive solo en el documento; el nivel de cada tool se escribió
a mano en la tabla de `E1 §2.6`.

Consecuencia concreta: una herramienta nueva puede añadirse sin que nada calcule
ni compruebe su riesgo. El control es una promesa, en el sentido exacto de
`E2 §1`.

**Acción propuesta**: añadir `capacidades: frozenset[str]` a `Herramienta`,
calcular el nivel con la fórmula del ADR y un test que compruebe que el nivel
calculado coincide con el declarado en `E1 §2.6`. Es la no conformidad con mejor
relación valor/coste de las que quedan abiertas.

### NC-12 · Observación · `pytest` y `ruff` se instalan en producción

`requirements.txt:12-13` incluye `pytest` y `ruff`, y `requirements-lock.txt` los
arrastra. La VPS instala ese lock (`scripts/jimmy.service`), así que el bot en
producción lleva instalados el framework de pruebas y el linter: superficie que
no necesita y dos paquetes más que vigilar con `pip-audit`.

**No se corrige en este trabajo a propósito.** Sacarlos cambiaría lo que instala
una máquina que está corriendo 24/7, y el encargo era explícito: no tocar la VPS.
Por eso las herramientas nuevas del kit van en `requirements-dev.txt` aparte, y
esto queda anotado en vez de arreglado.

### NC-13 · Observación · Faltan los ficheros de gobernanza del repositorio
**CERRADA**

No existen `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md` ni `CODEOWNERS`.
`.github/` contiene únicamente `workflows/ci.yml`.

`LICENSE` es el que más pesa: sin licencia, nadie que clone el repositorio sabe
qué puede hacer con él. `SECURITY.md` es el que pide ISO 27001 A.6.8 (canal para
reportar eventos de seguridad); en un proyecto personal basta con una línea
diciendo dónde escribir.

Las "Normas del proyecto" de `README.md:297-302` ya hacían de facto de
`CONTRIBUTING.md` y son buenas; solo les faltaba el sitio canónico.

**Corrección aplicada**: se crean los cuatro.

| Fichero | Qué resuelve |
|---|---|
| `LICENSE` | **Propietario**: todos los derechos reservados, y lo único permitido sin permiso previo es leerlo para evaluarlo. Se escribió MIT en la primera pasada y **el autor lo corrigió el mismo día**: MIT autoriza copiar, modificar y redistribuir, que es justo lo contrario de lo que se quiere aquí — el trabajo se comparte para que se evalúe, no para que se reutilice. Queda anotado porque el error importa: una licencia publicada es una promesa de la que la gente se fía |
| `SECURITY.md` | A.6.8: canal de reporte, alcance, y las cuatro CVE aceptadas con su motivo |
| `CONTRIBUTING.md` | Recoge las 4 normas del proyecto y las 2 doctrinas de verificación, que estaban repartidas |
| `.github/CODEOWNERS` | A.5.2: quién responde de qué. Con un autor, es una línea |

### NC-14 · Observación · Documentos citados que no están en el repositorio
**CERRADA**

| Referencia | Desde | Situación |
|---|---|---|
| `AGENTS.md` | `ADR-002:4`, `ADR-003:4`, `diario:173` | Es el enunciado del ejercicio, externo al repositorio. Legítimo, pero quien clone el repo no lo tiene y las citas quedan colgadas |
| `Tareas_Pendientes.md` | `ci.yml:78` | Citado desde el propio CI como justificación de por qué se ignora `CVE-2026-45829`. **Este es el que importa**: la justificación de una excepción de seguridad apunta a un documento que no está |
| Tres informes de auditoría (23/07, 27/07, 04-07/08) | `E4 §5.3`, marcados `[x]` | Sus hallazgos sí están en el diario y en el código (familias `AUD-`, `SEG-`), pero los informes como tales no |

**Corrección aplicada**: la justificación de `CVE-2026-45829` está ahora escrita
**entera dentro de `ci.yml`**, junto a la línea que la materializa, y ya no
remite a ningún documento ausente. Se aprovechó para hacer lo mismo con las tres
CVE nuevas del 06/09.

`AGENTS.md` es el enunciado del ejercicio, externo al repositorio por naturaleza,
y los tres informes de auditoría dejaron sus hallazgos en el diario y en el
código (familias `AUD-`, `SEG-`, inventariadas en `10_indice_de_identificadores.md`).
Ninguno de esos dos casos sostiene un control de seguridad, que era lo que hacía
grave a este hallazgo.

### NC-16 · Observación · Las acciones del CI apuntan a Node.js 20, que GitHub retira

Detectada el 06/09 leyendo los avisos de una ejecución **en verde**. GitHub
Actions anota, en cada `run`:

> *Node.js 20 is deprecated. The following actions target Node.js 20 but are
> being forced to run on Node.js 24:* `actions/checkout@11d5960…`,
> `actions/setup-python@a26af69…`

Las dos acciones están **bien fijadas por SHA**, como exige `DEP-05`, y esa
decisión no se discute: un tag es móvil y un SHA no. El efecto secundario es que
quedan congeladas en la versión que se fijó el 02/08, y esa versión declara
Node 20 en su `action.yml`.

**Hoy no rompe nada**: GitHub las está forzando a correr sobre Node 24 mientras
dura la transición. El problema llega el día que retiren ese modo de
compatibilidad — y entonces el CI se cae de golpe, sin que nadie haya tocado el
proyecto.

Es la contrapartida honesta de fijar por SHA: **ganas reproducibilidad y pierdes
las actualizaciones automáticas**, incluidas las que arreglan cosas. `DEP-05`
sigue siendo la decisión correcta; lo que hace falta es acordarse de renovar.

**Acción propuesta**: resolver los SHA nuevos **contra la API de GitHub** —el
mismo método del 02/08, y no copiarlos de ningún sitio, que es la lección del
30/07 con la lista de dominios— y actualizar **también** el comentario `# v4` /
`# v5` de al lado, que es lo único que permite saber qué versión es sin ir a
buscar el hash.

Se clasifica como Observación y no como Menor porque no incumple ningún
requisito declarado: es deuda con fecha de caducidad, no un control ausente.

### NC-15 · Menor · No hay revisión independiente de la seguridad

ISO/IEC 27001 **A.5.35** pide revisión independiente de la seguridad de la
información, y ISO 19011 pide que el auditor sea independiente del área
auditada. Aquí el autor, el responsable de seguridad y el auditor son la misma
persona.

**No es cerrable en este contexto** y se declara como limitación estructural, no
como tarea pendiente. Lo que compensa parcialmente ya está hecho: evidencia
citada por fichero y línea, controles validados por mutación, y este documento.

---

## Prioridad sugerida

Por relación valor/coste, no por gravedad:

1. **NC-10 (resto)** — generar `requirements-dev-lock.txt` desde Python 3.13.
   Un comando, y cierra del todo la cadena de suministro del CI.
2. **NC-05 parcial** — anclar RF-13, RF-25 y RNF-04, cuyos tests ya existen.
   Trabajo mecánico, sube la trazabilidad de 29/46 a 32/46.
3. **NC-11** — capacidades en `Herramienta`; convierte un documento en un control.
4. **NC-07** — lanzar a mano una vez el job `mutacion` y, si el tiempo lo
   permite, promoverlo a puerta de cada push.
5. **NC-13** — `LICENSE`, cinco minutos.
6. **NC-06** — cobertura de `main.py`, el trabajo más largo y el menos urgente.
