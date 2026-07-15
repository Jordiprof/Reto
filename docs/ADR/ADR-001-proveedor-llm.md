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

## Criterios para pasar a decisión (Fase 1)

- [ ] F1.1 Groq verificado en docs oficiales (free tier + tool calling)
- [ ] F1.2 Smoke test real contra Ollama Cloud con API key propia
- [ ] F1.3 Smoke test real contra Groq
- [ ] F1.4 Elegir modelo(s) y SDK (oficial vs compatible-OpenAI) → actualizar este ADR a ✅ Decisión

## Consecuencias

- Ninguna llamada al proveedor fuera de `llm_client.py` (regla de arquitectura, ver E2).
- Los modelos por defecto viven en `.env` / `.env.example`, no en el código.
- Riesgo aceptado: los free tiers cambian sin aviso → la cadena de 3 proveedores es la mitigación.
