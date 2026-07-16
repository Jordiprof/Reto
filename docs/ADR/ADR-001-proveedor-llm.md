# ADR-001 — Proveedor(es) LLM

**Estado:** 🟡 Hipótesis (pasa a decisión en Fase 1, ~17/07/2026)
**Fecha:** 15/07/2026 · **Decisor:** Jordi

## Contexto

El agente necesita un LLM por API con: (1) free tier utilizable durante el mes del reto,
(2) **soporte de tool calling** (imprescindible en el Nivel Avanzado) y (3) SDK o API
estable en Python. No hay presupuesto; una filtración de límites a mitad de reto
bloquearía el desarrollo.

## Hipótesis (pendiente de validación)

Cadena de proveedores por orden de preferencia:

1. **Ollama Cloud** — principal.
2. **Groq** — plan B.
3. **Anthropic** (Haiku/Sonnet, prepago) — plan C, solo si los gratuitos fallan.

Diseño que la sostiene: `src/llm_client.py` abstrae el proveedor → cambiar = configuración
(`.env`), no código.

## Evidencia verificada hasta ahora

- **15/07/2026 — Ollama Cloud (docs y pricing oficiales):** el plan Free da acceso a todo
  el catálogo cloud; limita por **cuota de uso** (sesión ~5 h + semanal) y 1 modelo
  concurrente. La cuota se consume según el peso del modelo → elegido `gpt-oss:20b`
  (nivel 1, ligero, etiqueta `tools`) como modelo por defecto. Alternativas ligeras con
  tools: `qwen3.5` (4b–27b), `nemotron-3-nano`.
- **07/2026 — Anthropic (pricing oficial):** sin free tier; `claude-haiku-4-5` $1/$5 MTok,
  `claude-sonnet-4-6` $3/$15. Válido como plan C de pago mínimo.
- **Groq:** pendiente de verificar (F1.1) — modelos, límites del free tier y tool calling.
  Hipótesis sin probar de Jordi (16/07): `llama-3.3-70b-versatile` podría funcionar bien
  en Groq aunque en OpenRouter esté en cola — confirmar en F1.3, no dar por bueno todavía.

## Pruebas reales — 16/07/2026 (Jordi, vía `ollama launch` / OpenCode)

**Ollama Cloud — ampliación de la prueba de F1.2 (adelantada):**

| Modelo | Resultado | Nota |
|---|---|---|
| `gpt-oss:20b-cloud` | ✅ Funciona | Nivel 1, ligero — default actual del proyecto |
| `gpt-oss:120b-cloud` | ✅ Funciona | Nivel 2, más pesado |
| `minimax-m3:cloud` | ✅ Funciona | Nivel 2 — mejor impresión que nemotron-3-super |
| `gemma4:31b-cloud` | ✅ Funciona | Nivel 2 |
| `nemotron-3-super:cloud` | ✅ Funciona | Nivel 2 — peor impresión que minimax-m3 |
| `nemotron-3-ultra:cloud` | ✅ Funciona | Probablemente pesado (nombre "ultra") |
| `kimi-k2.7-code:cloud` | ❌ No disponible en Free | Pide suscripción Pro/Max |

**Candidatos explorados fuera de la cadena original del ADR-001** (Google AI Studio,
OpenRouter) — no estaban en la hipótesis inicial (Ollama → Groq → Anthropic); se registran
como hallazgos, la decisión de si entran en `llm_client.py` se toma en **F1.4** junto con Groq:

| Proveedor | Modelo | Resultado | Nota |
|---|---|---|---|
| Google AI Studio | `gemini-3.5-flash` | ⚠️ Parcial | Arrancó vía OpenCode, ejecutó tool calls (Glob, Read) — interrumpido antes de respuesta final, sin confirmación completa |
| Google AI Studio | `gemini-2.5-pro` | ❌ Descartado | Cola por alta demanda del modelo |
| OpenRouter | modelo de código Qwen (ID exacto pendiente) | ❌ Descartado | Cola / disponibilidad, igual que gemini-2.5-pro |
| OpenRouter | `poolside/laguna-xs-2.1:free` | ✅ Funciona | Según prueba directa de Jordi |
| OpenRouter | `poolside/laguna-m.1:free` | ✅ Funciona | Según prueba directa de Jordi |
| OpenRouter | `tencent/hy3:free` | ✅ Funciona | Según prueba directa de Jordi |
| OpenRouter | `nvidia/nemotron-3-ultra-550b-a55b:free` | ✅ Funciona | Según prueba directa de Jordi |
| OpenRouter | "Llama 3.3 70B Instruct" | ❌ Descartado | Cola / disponibilidad, igual que Qwen y gemini-2.5-pro |

**Riesgo anotado:** ampliar la cadena de proveedores en Fase 0 aumenta el alcance
(ver E1, tabla de riesgos). Se documenta la evidencia pero **no se cambia la arquitectura
todavía** — eso se decide con datos completos en F1.4.

## Criterios para pasar a decisión (Fase 1)

- [ ] F1.1 Groq verificado en docs oficiales (free tier + tool calling)
- [ ] F1.2 Smoke test real contra Ollama Cloud con API key propia
- [ ] F1.3 Smoke test real contra Groq
- [ ] F1.4 Elegir modelo(s) y SDK (oficial vs compatible-OpenAI) → actualizar este ADR a ✅ Decisión
- [ ] F1.4 (extra) Decidir si Google AI Studio y/o OpenRouter entran en la cadena oficial, dado lo explorado el 16/07

## Consecuencias

- Ninguna llamada al proveedor fuera de `llm_client.py` (regla de arquitectura, ver E2).
- Los modelos por defecto viven en `.env` / `.env.example`, no en el código.
- Riesgo aceptado: los free tiers cambian sin aviso → la cadena de 3 proveedores es la mitigación.
