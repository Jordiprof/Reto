# E3 — Estado del arte y planificación

**Proyecto:** Agente de IA (terminal → Telegram en Fase 5)
**Autor:** Jordi · **Fecha:** 15/07/2026 (v0.1) → 21/07/2026 (v0.3, cierre Nivel Avanzado + planificación Fase 5 con stack experto) · **Versión:** 0.3

## 1. Estado del arte

_Todo dato cita su fuente oficial y fecha de consulta — lección del 15/07: los LLM citan
modelos retirados; verificar siempre docs oficiales._

- **Proveedores LLM con free tier** — cerrado en ADR-001 (16/07): Groq → Ollama Cloud →
  Gemini → Anthropic. Verificado con smoke tests reales en los 4, no solo documentación.
- **Qué es un agente de IA** (LLM + bucle + herramientas + memoria) — aprendido y construido
  en Fase 4 (F4.1-F4.6), con evidencia real, no solo teoría:
  - **Tool use / function calling**: el modelo no ejecuta código — decide que quiere llamar
    a una función descrita por su nombre, descripción y JSON Schema de parámetros; el
    programa la ejecuta de verdad y le devuelve el resultado para que continúe.
  - **El bucle del agente** (LLM → tool → resultado → LLM) es el mismo patrón conceptual en
    los 3 proveedores, pero **cada uno lo implementa distinto** — verificado con código real,
    no solo con la doc: Groq manda los argumentos como JSON string y exige `tool_call_id`;
    Ollama ya entrega los argumentos como dict y usa `tool_name` en vez de un id; Gemini
    declara las tools sin el envoltorio `"type": "function"` y puede repartir la petición de
    función en cualquier `part` de la respuesta, no siempre en la primera (bug real
    encontrado y corregido en F4.6).
  - **Validación de parámetros** (F4.4): nunca asumir que el modelo manda argumentos
    correctos — un JSON mal formado o un parámetro inventado no debe tirar el programa.
  - **Diseño de una tool**: la calidad de la `description` condiciona si el modelo la usa
    bien — verificado indirectamente en las pruebas de F4.5/F4.6 (el modelo eligió usar la
    calculadora de forma consistente cuando se le pidió explícitamente en el prompt que la
    prefiriera sobre calcular de memoria).
- **Frameworks (LangGraph, etc.) vs agente a mano** — decisión preliminar tomada en
  brainstorming (21/07, ver diario y ADR-003 pendiente de formalizar en F5.1): agente a
  mano con tools agrupadas por categoría; orquestador multi-agente queda como comparación
  con LangGraph en F5.5 (Extra), no como base del bot real.

### 1.1. Stack "experto" — investigación 2026 y criterio de selección por privacidad

Al planificar Fase 5 (21/07) se investigó el estado actual de las tecnologías del ecosistema de
agentes que Jordi quería valorar. **Criterio rector: privacidad** (RNF-06) — los datos del bot no
deben salir de la máquina salvo la llamada al LLM. Ese criterio decide qué entra y qué se descarta.
Fuentes consultadas (2026): comparativas de observabilidad LLM (Langfuse/Phoenix/LangSmith),
comparativas de vector DBs (Chroma/Qdrant/FAISS), y guías de frameworks de agentes
(LangGraph/CrewAI/AutoGen) — todas de 2026, verificadas, no de conocimiento previo.

| Categoría | Herramientas | Decisión | Motivo |
|---|---|---|---|
| Orquestación multi-agente | LangGraph, CrewAI, AutoGen | Solo LangGraph, y solo como comparación (F5.6) | El caso de uso es un agente único; multiagente es para coordinar objetivos distintos. AutoGen además está en mantenimiento (Microsoft movió el foco a otro producto) |
| Framework LLM general | LangChain | Fuera del núcleo | Redundante con `llm_client.py`/`agent.py` ya construidos; ADR-003 = "a mano primero" |
| Validación de datos | Pydantic | ✅ Entra (F5.4) | Librería local sin red; endurece la validación de parámetros de tools de F4.4 |
| Framework de agentes ligero | PydanticAI | Solo comparación opcional (F5.6) | Alternativa a LangChain, pero el bot ya está construido a mano |
| Observabilidad | LangSmith | ❌ Descartada | Cloud SaaS closed-source; manda todas las trazas (prompts/respuestas) a servidores de LangChain — incompatible con "confidencial". Alternativas locales/open-source (Phoenix, Langfuse) sí respetarían la privacidad, pero de momento basta `logs/agente.log` |
| Vector DB (RAG) | Pinecone | ❌ Descartada | Nube, de pago; los embeddings de las conversaciones saldrían de la máquina |
| Vector DB (RAG) | ChromaDB / Qdrant / FAISS | ✅ ChromaDB (F5.3) | Las tres corren locales y gratis; ChromaDB es la más simple para aprender |
| Embeddings | API de pago (OpenAI, etc.) | ❌ Descartados | Enviarían el texto de las conversaciones a un tercero. Se usan embeddings LOCALES (`sentence-transformers`) |
| Embeddings (modelo) | `all-MiniLM-L6-v2` | ❌ Descartado | El más citado en tutoriales, muy ligero (~90MB), pero entrenado sobre todo en inglés — peor calidad semántica buscando en conversaciones en español (RF-12) |
| Embeddings (modelo) | `paraphrase-multilingual-MiniLM-L12-v2` | ✅ Elegido (F5.3, ADR-003) | Multilingüe (incluye español), ligero (~470MB), buen equilibrio calidad/recursos para correr en la máquina de Jordi (o una Raspberry Pi si esa es la opción de hosting de F5.2) |

**Lección transversal:** el requisito de privacidad no limita el aprendizaje — al contrario, obliga
a entender qué hace cada herramienta por dentro y dónde van los datos, en vez de conectar servicios
en la nube a ciegas. Varias decisiones "se toman solas" en cuanto se aplica el criterio.

## 2. Planificación (roadmap)

| Fase | Fechas planeadas | Fechas reales | Entregable | Tag |
|---|---|---|---|---|
| 0 — Esqueleto del repo | 15/07 | 15/07 | Repo + docs base + ADR-001 (hipótesis) | — |
| 1 — Validación proveedores | 15–17/07 | 15–16/07 | Smoke tests + ADR-001 (decisión) | — |
| 2 — Nivel Básico | 17–21/07 | 17/07 | Chat en bucle con errores manejados y logging | `nivel-basico` |
| 3 — Nivel Intermedio | 22–28/07 | 17–20/07 | Historial + system prompt + persistencia + pytest | `nivel-intermedio` |
| 4 — Nivel Avanzado | 29/07–04/08 | 21/07 | Tool calling con bucle de agente a mano | `nivel-avanzado` |
| 5 — Nivel Experto | 05–13/08 | _sin empezar_ | Proyecto final sobre la temática elegida (bot Telegram) | `nivel-experto` |
| 6 — Cierre y entrega | 13–14/08 | _sin empezar_ | E4 + diario completo + reflexión final | — |

**Hito transversal:** ~~decidir la temática del agente experto antes del 28/07~~ — **resuelto
el 20/07** (bot de Telegram personal, ver E1 v1.2 y diario).

## 3. Ideas para revisar en Fase 5 (Nivel Experto)

- **Orquestación multi-agente** (propuesta de Jordi, 16/07) — **resuelto (21/07): agente único**
  (ver §1.1 y diario). NO se usa como base del bot. El patrón orquestador+sub-agentes queda como
  comparación real con LangGraph en F5.6 (Extra), coherente con ADR-003 (a mano primero). Distinto
  de la cadena de fallback de proveedores (ADR-001), que es resiliencia de un único agente.
- **Memoria semántica (RAG local)** — **resuelto (21/07): sí, se implementa** (F5.3). Es lo que
  Jordi pidió como "que se acuerde de días anteriores": ChromaDB local + embeddings locales. Cumple
  la condición de ADR-002 ("solo si se justifica"). Ver RF-12.
- **Correo (Gmail), solo lectura** (propuesta de Jordi, 21/07) — **aparcada tras investigar el
  coste real.** En modo "Testing" de Google Cloud Console (gratis, sin verificación) el refresh
  token de un scope restringido como `gmail.readonly` **caduca a los 7 días** y obliga a
  reautorizar a mano; el modo "Production" exige verificación de Google (posible coste/fricción).
  Ninguna opción encaja limpio con "gratis y sin sorpresas" — queda en el backlog, no en F5, con el
  hallazgo documentado para retomarlo con la decisión ya informada.

## 4. Seguimiento

- **Fases 2-4 completadas muy por delante del calendario planeado** (Fase 3 en 4 días en vez
  de 7, Fase 4 en 1 día en vez de 7). No es trabajo superficial: cada fase tiene evidencia
  real en el diario (llamadas reales a los 3 proveedores, bugs encontrados y corregidos con
  reproducción, no solo teoría) — el ritmo real permitió dedicar el tiempo sobrante a
  profundizar (F2.6b, brainstorming completo de temática y arquitectura) en vez de acumularlo
  sin usar. Se mantiene igualmente el calendario original como referencia de ritmo razonable,
  no como techo a alcanzar antes de tiempo en las fases que quedan.
