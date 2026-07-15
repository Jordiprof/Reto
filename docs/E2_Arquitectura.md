# E2 — Arquitectura

**Proyecto:** Agente de IA en terminal (nombre provisional)
**Autor:** Jordi · **Fecha:** 15/07/2026 · **Versión:** 0.1 — esqueleto; se amplía al cierre de cada nivel

## 1. Visión global

```mermaid
flowchart LR
    U([Usuario]) <--> CLI[CLI<br/>main.py]
    CLI --> AG[Agent<br/>agent.py]
    AG --> LLM[LLMClient<br/>llm_client.py]
    LLM <--> PROV[(Proveedor LLM<br/>Ollama Cloud / Groq / Anthropic)]
    AG --> TOOLS[Tools<br/>tools.py]
    AG --> ST[Storage<br/>storage.py]
    ST --> FS[(conversations/ JSON<br/>→ SQLite)]
```

**Regla de dependencias:** la CLI nunca habla directamente con el proveedor; todo pasa
por `Agent`, y solo `LLMClient` conoce la API del proveedor. Así, cambiar de proveedor
es cambiar configuración (`.env`), no reescribir el agente (ver ADR-001).

## 2. Componentes

| Componente | Fichero | Responsabilidad | Aparece en |
|---|---|---|---|
| CLI | `src/main.py` | Bucle de entrada/salida por terminal | Básico |
| Agent | `src/agent.py` | Orquesta: historial, system prompt, bucle de tools | Intermedio/Avanzado |
| LLMClient | `src/llm_client.py` | Abstrae el proveedor LLM (única pieza que conoce su API) | Básico |
| Tools | `src/tools.py` | Herramientas puras de Python + sus JSON Schema | Avanzado |
| Storage | `src/storage.py` | Persistencia: JSON con fecha → SQLite (ADR-002) | Intermedio |
| Config | `src/config.py` | Carga de `.env` (claves y modelos) | Básico |

## 3. Evolución por niveles

- **Básico:** CLI + LLMClient (sin memoria, una pregunta → una respuesta).
- **Intermedio:** + historial completo reenviado + system prompt + Storage (JSON, intro SQLite).
- **Avanzado:** + Tools con JSON Schema + bucle del agente: LLM → tool → resultado → LLM.
- **Experto:** caso de uso completo sobre la temática elegida (límite de decisión: 28/07).

## 4. Experimento de system prompts

_Pendiente (F3.2, Nivel Intermedio): comparar 2–3 system prompts y documentar aquí las diferencias observadas._

## 5. Decisiones de arquitectura

Ver [ADR/](ADR/) — proveedor (ADR-001, hipótesis), memoria evolutiva (ADR-002, se
formaliza en Intermedio), framework vs a mano (ADR-003, se formaliza en Experto).
