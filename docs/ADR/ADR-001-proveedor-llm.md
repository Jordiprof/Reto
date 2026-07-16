# ADR-001 — Proveedor(es) LLM

**Estado:** ✅ Decisión (16/07/2026)
**Fecha:** 15/07/2026 (hipótesis) → 16/07/2026 (decisión) · **Decisor:** Jordi

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

## Verificación en documentación oficial — 16/07/2026 (los 5 proveedores)

**Groq** (`console.groq.com/docs`):
- Free tier con rate limits por modelo, ejemplo: `llama-3.3-70b-versatile` y los `gpt-oss` →
  **30 RPM, 6K–15K TPM**; `qwen/qwen3-32b` → 60 RPM. Límites a nivel de organización, no de usuario.
- **Tool use confirmado para TODOS los modelos alojados**, cita textual: *"All models hosted
  on Groq support tool use"*. Confirma la hipótesis de Jordi: `llama-3.3-70b-versatile` sí
  soporta tools. ✅

**Google AI Studio / Gemini API** (`ai.google.dev`):
- Existe free tier, pero la doc no publica cifras exactas de RPM/RPD en la página de rate
  limits — remite al dashboard personal en `aistudio.google.com/rate-limit` (solo visible
  con cuenta creada). **Pendiente:** mirar ese dashboard cuando Jordi tenga cuenta.
- Function calling confirmado en la serie **Gemini 3** (incluye `gemini-3.5-flash`, que
  Jordi ya vio ejecutando tool calls en la prueba interrumpida).

**OpenRouter** (`openrouter.ai/docs`):
- Modelos `:free` **sin compra previa de créditos**: **20 RPM / 50 RPD** (peticiones por día).
- Con al menos **$10 en créditos comprados** (de por vida, no saldo actual): sube a **20 RPM
  / 1000 RPD**.
- Esto explica en parte las "colas" que veía Jordi: 50 peticiones/día en el nivel más bajo
  se agotan muy rápido probando modelos a mano.

**Anthropic** (`platform.claude.com/docs`, actualizado 16/07):
- **No hay free tier real** — solo *"a small amount of free credits"* para nuevas cuentas,
  de prueba. Confirma que Anthropic sigue siendo plan C de pago, no gratuito.
- Precio más barato actual: `claude-haiku-4-5` **$1/$5 MTok**. `claude-sonnet-5` con precio
  introductorio $2/$10 MTok hasta el 31/08/2026 (después $3/$15).

## Smoke tests reales en Python (Fase 1)

- **16/07/2026 — Ollama Cloud ✅** — `scripts/prueba_test_ollama.py`, cliente oficial
  `ollama` (SDK Python, vía API directa `https://ollama.com` con `OLLAMA_API_KEY`),
  modelo `gpt-oss:20b`. Respuesta real recibida de punta a punta.
- **16/07/2026 — Groq ✅** — `scripts/prueba_test_groq.py`, SDK oficial `groq` v1.5.0,
  modelo `llama-3.3-70b-versatile`. Respuesta real recibida; confirma la hipótesis de
  tool use de Jordi (y lo que decía la doc oficial de Groq).
- **16/07/2026 — Google AI Studio (Gemini) ✅** — `scripts/prueba_test_gemini.py`, SDK
  oficial `google-genai` v2.12.0, modelo `gemini-3.5-flash`. Respuesta real y completa
  (a diferencia de la prueba anterior vía OpenCode, que se interrumpió). Nota corregida:
  la variable de entorno correcta es `GEMINI_API_KEY`, no `GOOGLE_API_KEY` — el SDK la
  busca así automáticamente; se corrigió en `.env.example`.
- **16/07/2026 — OpenRouter ✅** — `scripts/prueba_test_openrouter.py`, SDK compatible-
  OpenAI (`openai` v2.45.0) con `base_url="https://openrouter.ai/api/v1"`, modelo
  `poolside/laguna-m.1:free`. Respuesta real recibida. Confirma con código lo que ya se
  había visto a mano vía OpenCode.

**Resumen F1.2–F1.5:** los 4 candidatos (Ollama, Groq, Google AI Studio, OpenRouter)
tienen ahora smoke test real en Python, no solo prueba manual por CLI/OpenCode. Los 4 SDKs
usan un patrón distinto para pasar el modelo y la clave — dato relevante para diseñar la
abstracción de `llm_client.py` en Fase 2.

## Criterios para pasar a decisión (Fase 1)

- [x] F1.1 Groq verificado en docs oficiales (free tier + tool calling)
- [x] F1.2 Smoke test real contra Ollama Cloud con API key propia
- [x] F1.3 Smoke test real contra Groq
- [x] F1.4 Smoke test real contra Google AI Studio
- [x] F1.5 Smoke test real contra OpenRouter
- [x] F1.6 Elegir modelo(s) y SDK → ADR-001 pasa a ✅ Decisión (ver abajo)

## Decisión final (16/07/2026)

Tras revisar Gemini con más detalle (contexto real, comparación con `gemini-2.5-flash`,
y el riesgo de recortes de cuota sin aviso que Google ya aplicó en 12/2025), la cadena de
fallback definitiva queda en **4 proveedores**:

1. **Groq** (`llama-3.3-70b-versatile`) — principal. Tool use garantizado en toda su
   documentación oficial (cita textual: *"All models hosted on Groq support tool use"*),
   rate limit más claro y medible de los 4 (30 RPM / TPM exacto), el más rápido (hardware
   LPU dedicado) — clave para el volumen de pruebas de las Fases 2-4.
2. **Ollama Cloud** (`gpt-oss:20b`) — primer fallback. Buena cuota por sesión, catálogo
   amplio, ya probado y en uso desde F0.3.
3. **Google AI Studio / Gemini** (`gemini-3.5-flash`) — segundo fallback. Contexto de
   ~1M tokens (1.048.576 in / 65.536 out, confirmado en model card oficial) — el mayor
   de los 4, útil para tareas con mucho contexto. Queda en tercer lugar y no más arriba
   por dos motivos: RPM más bajo que Groq (~15 vs 30) y precedente real de recorte de
   cuota sin aviso (Google, 12/2025, de 250 a 20 RPD para algunos usuarios en otro
   modelo) — mayor riesgo de inestabilidad. **Se descarta `gemini-2.5-flash`**: mismo
   contexto que `3.5-flash` pero peor cuota (10 RPM / 250 RPD vs ~15 RPM / ~1.500 RPD) —
   no aporta nada que `3.5-flash` no tenga ya, y `3.5-flash` es estrictamente mejor.
4. **Anthropic** (`claude-haiku-4-5`) — último recurso, de pago. Solo si fallan los 3
   gratuitos, o para pruebas puntuales. Sin free tier real (solo créditos de prueba).

**OpenRouter queda fuera de la cadena**, documentado como candidato: su free tier
(50 peticiones/día sin gastar $10) es insuficiente para desarrollo diario — no aguanta ni
las pruebas de una sesión de trabajo normal.

**Corrección registrada (16/07):** una búsqueda inicial afirmaba que el free tier de
Gemini no está disponible en la UE/España. Se verificó contra el texto legal oficial
(`ai.google.dev/gemini-api/terms`) y es **falso**: en la UE se aplican las condiciones de
privacidad de "Paid Services" también al nivel gratuito (los prompts no se usan para
entrenar), pero el acceso gratuito sí funciona — confirmado además por el smoke test real
de Jordi. Se descarta la fuente no oficial que afirmaba lo contrario.

## Consecuencias

- Ninguna llamada al proveedor fuera de `llm_client.py` (regla de arquitectura, ver E2).
- Los modelos por defecto viven en `.env` / `.env.example`, no en el código.
- Riesgo aceptado: los free tiers cambian sin aviso → la cadena de 4 proveedores es la
  mitigación (y Gemini, el más volátil de los 3 gratuitos, queda deliberadamente en
  tercer lugar, no en los dos primeros).
- `llm_client.py` debe absorber 4 formas distintas de llamar (Groq, Ollama, Gemini,
  Anthropic) — cada SDK tiene su propia firma, visto en los smoke tests de F1.2–F1.5.
- Idea aparcada para Fase 4/5 (ver E3): una tool `consultar_otro_modelo` que delegue en
  otro proveedor de esta misma cadena — orquestación ligera sin romper la arquitectura.
