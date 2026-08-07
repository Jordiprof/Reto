# ADR-003 — Framework del agente: a mano vs orquestación (LangGraph/PydanticAI) y multiagente

**Estado:** ✅ Decisión (22/07/2026)
**Fecha:** 15/07/2026 (mencionado como comparativa futura, ver `AGENTS.md`) → 21/07/2026 (decisión de fondo, planificación Fase 5) → 22/07/2026 (formalizado) · **Decisor:** Jordi

## Contexto

El objetivo del reto es formativo: comprender cada pieza de un agente antes de usar
abstracciones (E1 §1). Al llegar al Nivel Experto, con ~30 herramientas previstas
(F5.5) y memoria semántica (F5.3), había que decidir dos cosas relacionadas:

1. Si el agente sigue construido **a mano** (bucle propio LLM → tool → resultado,
   como en Avanzado) o se reescribe sobre un **framework de orquestación**
   (LangGraph, CrewAI, AutoGen, PydanticAI...).
2. Si el volumen de herramientas obliga a pasar de **un agente** a **varios agentes
   coordinados** (multiagente).

## Alternativas consideradas

- **Reescribir el núcleo con LangGraph** desde F5.1: grafos de estados,
  checkpointing, más "potencia" de orquestación, pero reescribe lo que ya funciona
  desde F4.5.
- **Multiagente (CrewAI / AutoGen / patrón orquestador+sub-agentes con LangGraph):**
  varios agentes especializados coordinándose para repartirse las ~30 herramientas.
  AutoGen además está en mantenimiento (Microsoft movió el foco a otro producto,
  ver E3 §1.1).
- **LangChain** como capa de utilidades sobre el LLM.
- **Seguir a mano + Pydantic**, con LangGraph/PydanticAI solo como comparación
  educativa al final (F5.6, Extra).

## Decisión

- **Agente único, a mano**, extendiendo `src/agent.py` tal cual — mismo diseño que
  cerró F4.5: el núcleo no conoce la capa de E/S, así lo reutiliza también el bot
  de Telegram sin tocar la lógica.
- **Pydantic sí** (F5.4): valida los parámetros que el modelo LLM manda a cada tool,
  endureciendo la validación manual de F4.4. Es una librería local sin red, no un
  framework de orquestación.
- **LangChain no**: redundante con `llm_client.py`/`agent.py` ya construidos.
- **LangGraph / PydanticAI**: solo como ejercicio comparativo en F5.6 (Extra) —
  reconstruir una parte pequeña y comparar contra lo hecho a mano. No sustituyen
  el motor real del bot.
- **Multiagente descartado como base.** 30 herramientas es un problema de
  *organización* de tools (agrupar por categoría + filtrado dinámico si hiciera
  falta), no de *coordinación* entre agentes con objetivos distintos. Un patrón
  multiagente añadiría más piezas moviendo datos entre sí, lo que choca con
  RNF-06 (privacidad: los datos no salen de la máquina salvo la llamada al LLM).

## Consecuencias

- El motor de Fase 5 sigue siendo el mismo `Agente`/`LLMClient` de Fase 4, sin
  reescritura arquitectónica — coherente con el objetivo formativo del reto
  (E1 §1: entender cada pieza antes de usar abstracciones).
- Añadir Pydantic (F5.4) es una capa de validación adicional, no un cambio de
  arquitectura ni de framework.
- F5.6 (comparación con LangGraph/PydanticAI) queda explícitamente como
  comparación educativa opcional, no bloqueante para cerrar el nivel Experto.
- Si en el futuro el bot creciera mucho (más usuarios, agentes realmente
  especializados con objetivos distintos), esta decisión quedaría obsoleta y
  habría que revisarla — pero eso está fuera del alcance del reto
  (ver E1 §2, "Evolución futura conscientemente fuera de alcance").
