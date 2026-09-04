# 01 — Calidad de los requisitos

Referencia: **ISO/IEC/IEEE 29148:2018**, §5.2 (características de un buen
requisito) y §5.2.8 (trazabilidad).

Objeto de la evaluación: los **46 identificadores** de
`docs/E1_Especificacion_Requisitos.md` — 5 objetivos, 26 requisitos funcionales,
8 no funcionales y 7 casos de uso.

## 1. Veredicto general

`E1` es una especificación **mejor que la media** de lo que se ve en un proyecto
de este tamaño: los requisitos tienen ID estable, prioridad, nivel de entrega y
estado; los no funcionales llevan criterio de aceptación escrito, cosa que rara
vez ocurre; y hay una sección de trazabilidad que nadie pide a este nivel.

Sus dos debilidades son concretas y están en §3 y §4: **algunos criterios de
aceptación no son medibles**, y **la trazabilidad estaba incompleta y sin ancla
en el código**. La segunda se ha corregido en parte durante esta auditoría.

## 2. Evaluación contra las características de 29148 §5.2

| Característica | Veredicto | Comentario |
|---|---|---|
| **Necesario** | ✅ | Ningún requisito sobra. Los descartados están escritos como descartados (`E1 §1.3`), no borrados |
| **Apropiado** (nivel correcto de abstracción) | 🟡 | `RF-10` ("resuelve el caso de uso completo: asistente personal por Telegram") es un objetivo disfrazado de requisito |
| **Inequívoco** | ✅ | El lenguaje es concreto. Ayuda el glosario de `E1 §8` |
| **Completo** | ✅ | Cada requisito se entiende sin recurrir a otro documento |
| **Singular** | 🟡 | `RNF-06` empaqueta privacidad, SSRF y cifrado en un solo ID, y por eso aparece trazado desde cuatro módulos distintos |
| **Factible** | ✅ | Los 26 RF están implementados y marcados ✅ con fecha |
| **Verificable** | 🟡 | El punto flojo. Detalle en §3 |
| **Correcto** | ✅ | Los requisitos describen lo que el sistema hace de verdad — comprobado por muestreo contra el código |
| **Conforme** (formato consistente) | ✅ | Mismo formato de tabla en las cinco secciones |
| **Trazable** | 🟡 | 29 de 46. Detalle en §4 |

## 3. Verificabilidad de los criterios de aceptación

29148 §5.2.5 exige que un requisito pueda comprobarse por inspección, análisis,
demostración o prueba. Los ocho RNF de `E1 §3` llevan criterio escrito, lo cual
ya es más de lo habitual; el problema es que **tres de ellos no son medibles tal
como están redactados**.

| ID | Criterio actual | Evaluación |
|---|---|---|
| RNF-01 | "Ninguna clave en el código ni en el historial de git" | ✅ Verificable y binario. Hoy se comprueba a mano con `gitleaks` (`NC-05`) |
| **RNF-02** | "Ante un fallo de API o un fichero corrupto, el programa avisa y sigue vivo" | 🟡 **No medible.** ¿Ante cuántos fallos? ¿De qué proveedores? ¿"Sigue vivo" cuánto tiempo? Se verifica bien en la práctica (19 tests en `test_avisos_caida.py`), pero el criterio no dice cuándo se ha cumplido |
| **RNF-03** | "Cambiar de proveedor = cambiar configuración, no reescribir el agente" | 🟡 **No medible.** Es una propiedad de diseño, no un criterio de aceptación. Demostrable por inspección (4 proveedores tras la misma interfaz), no por prueba |
| RNF-04 | "Python 3.13 + venv + `requirements-lock.txt` con versiones fijadas" | ✅ Verificable |
| RNF-05 | "Identidad por token, nunca por teléfono personal. Filtrado por `user_id`" | ✅ Verificable |
| RNF-06 | "Los datos NO salen de la máquina salvo la llamada mínima al LLM" | 🟡 Verificable pero **no singular**: mezcla tres controles distintos |
| RNF-07 | "Toda llamada a herramienta se registra con solo metadatos, nunca contenido" | ✅ Verificable, y de hecho verificado (`test_logging.py`) |
| **RNF-08** | "Los controles críticos se validan por mutación, no solo con tests en verde" | ✅ Verificable ⚠️ pero **no automatizado** (`NC-07`) |

**Propuesta de reformulación** para los dos peores, respetando el estilo del
documento:

> **RNF-02** — Ante un fallo de cualquier proveedor LLM (error de red, cuota
> agotada, respuesta malformada) o un fichero de conversación corrupto, el
> programa informa al usuario en castellano distinguiendo la causa y continúa
> aceptando mensajes. *Criterio: la degradación entre los cuatro proveedores
> configurados está cubierta por test, y ningún fallo de proveedor termina el
> proceso.*

> **RNF-03** — Añadir o sustituir un proveedor LLM no requiere modificar
> `agent.py` ni `tools.py`. *Criterio: verificable por inspección; los cuatro
> proveedores actuales implementan `_ProveedorLLM` sin tocar el núcleo.*

Nótese que la segunda declara explícitamente que se verifica **por inspección**.
29148 lo admite; lo que no admite es un criterio que parezca una prueba y no lo
sea.

## 4. Trazabilidad

### 4.1 Situación al empezar

`E1 §6` es una tabla de 15 filas "requisito → ADR → dónde vive → cómo se
verifica". Escrita a mano y, lo importante, **sin ancla en el código**:
`grep -rn "\bRF-[0-9]" src/ tests/` devolvía **cero coincidencias**.

Una precisión, porque una primera lectura de esta auditoría se equivocó: los
conteos entre paréntesis de esa tabla (115, 24, 25, 20, 29, 20, 90, 39, 21, 20,
11, 36, 17, 12) **cuadran los catorce** con la realidad. La tabla no mentía. Su
problema era que estaba incompleta y que nada impedía que empezara a mentir.

### 4.2 Qué se ha hecho

Marcador `@pytest.mark.requisito(...)` declarado en `pyproject.toml` con
`--strict-markers`, aplicado a **78 tests**. El resultado se genera en
`07_matriz_trazabilidad.md` y lo verifica `scripts/trazabilidad.py` en cada CI.

| | Antes | Ahora |
|---|---|---|
| Identificadores con verificación trazada | 0 de 46 | **29 de 46** (63 %) |
| Requisitos críticos trazados | 0 de 5 | **5 de 5** (100 %) |
| Controles de `E2 §8` anclados | 0 de 12 | **11 de 12** |
| Traza inversa (test → requisito) | No existía | En el código |

### 4.3 Lo que sigue sin traza (`NC-05`)

| Familia | Sin traza |
|---|---|
| Objetivos | OBJ-01, OBJ-02, OBJ-03, OBJ-04, OBJ-05 |
| Funcionales | RF-01, RF-04, RF-10, RF-13, RF-25 |
| No funcionales | RNF-01, RNF-03, RNF-04 |
| Casos de uso | CU-02, CU-03, CU-06, CU-07 |

Tres grupos, con tratamiento distinto:

- **RF-13, RF-25 y RNF-04 ya tienen tests**; solo les falta el marcador. Es
  trabajo mecánico.
- **Los 5 objetivos y los 4 casos de uso** necesitan pruebas de extremo a
  extremo que no existen. La propuesta honesta no es fabricarlas para llenar la
  tabla: es **declararlos verificables por inspección o por demostración** —29148
  lo permite— y dejarlo escrito.
- **RNF-01** es el único que preocupa: "ninguna clave en el código ni en el
  historial" se comprueba con `gitleaks` **a mano**, según `E4 §5.1`. Un control
  manual ejecutado una vez en agosto no protege el commit de mañana. Debería ir
  al CI.

## 5. Observaciones menores

**`RF-10` no es un requisito.** "El agente resuelve el caso de uso completo:
asistente personal por Telegram" describe un objetivo. Encaja mejor como `OBJ-06`
o como enunciado de alcance. No tiene consecuencia práctica más allá de que nunca
podrá trazarse a un test concreto.

**La numeración de los RF no es contigua por sección.** `§2.2` salta de RF-09 a
RF-13; `§2.3` contiene 14, 15, 16 y 22. Es un efecto de agrupar por tema
requisitos numerados por orden histórico. No falta ningún número entre 01 y 26 y
los IDs son estables, que es lo que de verdad importa: renumerar para que quede
bonito rompería todas las referencias del diario y de los ADR. **Se recomienda
no tocarlo.**

**`SEG-nn` se usa sin estar declarado.** `SEG-07` (defensa contra inyección de
prompt) aparece 31 veces en el repositorio y `SEG-03` 26, pero ninguna tabla de
`E1` los define: son una familia paralela de identificadores de auditoría. Están
inventariados en `10_indice_de_identificadores.md`.

## 6. Resumen frente a 29148

| Elemento que pide la norma | Estado |
|---|---|
| Identificadores únicos y estables | ✅ |
| Prioridad asignada | ✅ Crítica / Alta / Media |
| Criterios de aceptación | 🟡 Presentes; tres no medibles (§3) |
| Requisitos verificables | 🟡 |
| Trazabilidad bidireccional | 🟡 29 de 46, con ancla en código y verificación automática |
| Gestión de cambios de requisitos | ✅ `E1` se declara "documento vivo" v2.1, y el diario registra cada cambio con fecha |
| Requisitos fuera de alcance declarados | ✅ `E1 §1.3` |
| Partes interesadas identificadas | 🟡 Implícitas; recogidas en `00_alcance.md` §4 |
