# E3 — Estado del arte y planificación

**Proyecto:** Agente de IA en terminal (nombre provisional)
**Autor:** Jordi · **Fecha:** 15/07/2026 · **Versión:** 0.1 — esqueleto; el estado del arte se completa con la Fase 1 y el Nivel Avanzado

## 1. Estado del arte

_Se completa con lo investigado en F1.1 (proveedores) y la Fase 4 (agentes y tool calling).
Todo dato citará su fuente oficial y fecha de consulta — lección del 15/07: los LLM citan
modelos retirados; verificar siempre docs oficiales._

- **Proveedores LLM con free tier** (comparativa: modelos, límites, tool calling): _pendiente F1.1._
  - Avance 15/07 (docs oficiales de Ollama): el free tier de Ollama Cloud da acceso a todo el
    catálogo cloud y limita por cuota de uso (sesión de 5 h + semanal, 1 modelo concurrente);
    `gpt-oss:20b` es ligero (nivel 1) y soporta tools.
- **Qué es un agente de IA** (LLM + bucle + herramientas + memoria): _pendiente Fase 4._
- **Frameworks (LangGraph, etc.) vs agente a mano:** _pendiente Fase 5 (ADR-003)._

## 2. Planificación (roadmap)

| Fase | Fechas | Entregable | Tag |
|---|---|---|---|
| 0 — Esqueleto del repo | 15/07 | Repo + docs base + ADR-001 (hipótesis) | — |
| 1 — Validación proveedores | 15–17/07 | Smoke tests + ADR-001 (decisión) | — |
| 2 — Nivel Básico | 17–21/07 | Chat en bucle con errores manejados y logging | `nivel-basico` |
| 3 — Nivel Intermedio | 22–28/07 | Historial + system prompt + persistencia + pytest | `nivel-intermedio` |
| 4 — Nivel Avanzado | 29/07–04/08 | Tool calling con bucle de agente a mano | `nivel-avanzado` |
| 5 — Nivel Experto | 05–13/08 | Proyecto final sobre la temática elegida | `nivel-experto` |
| 6 — Cierre y entrega | 13–14/08 | E4 + diario completo + reflexión final | — |

**Hito transversal:** decidir la temática del agente experto antes del **28/07**.

## 3. Ideas para revisar en Fase 5 (Nivel Experto)

- **Orquestación multi-agente** (propuesta de Jordi, 16/07): además del agente principal,
  ¿podría orquestar a 2-3 sub-agentes especializados? Es un patrón real y relacionado con
  ADR-003 (framework vs a mano, y la comparativa opcional con LangGraph). **No se decide
  ahora** — depende de la temática (límite 28/07) y de si aporta algo al caso de uso, no
  se añade solo porque sea posible (ver riesgo de alcance disparado, E1). Distinto de la
  cadena de fallback de proveedores (ADR-001), que es resiliencia de un único agente.

## 4. Seguimiento

_Desviaciones respecto al plan y sus motivos se anotan aquí al cierre de cada fase._
