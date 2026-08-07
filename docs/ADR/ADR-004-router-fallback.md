# ADR-004 — Router de proveedores con reintentos y fallback automático

**Estado:** ✅ Decisión (23/07/2026)
**Fecha:** 23/07/2026 · **Decisor:** Jordi · **Contexto:** Fase 5.0 (endurecimiento, tarea T4)

## Contexto

ADR-001 decidió una **cadena** de proveedores (Groq → Ollama Cloud → Gemini →
Anthropic) por resiliencia: si el free tier de uno se agota o falla, seguir con el
siguiente. Pero hasta Fase 5.0 esa cadena **solo existía en la documentación**: el
código hablaba con UN proveedor elegido a mano y, si ese devolvía un 429 (rate
limit), un timeout o caía la red, el turno se perdía (antes como string `⚠️`, tras
T2 como excepción `ErrorLLM`). Para un asistente que se quiere tener **encendido
24/7 en Telegram** (RF-10), un fallo transitorio del proveedor principal no debería
tumbar la respuesta. La revisión externa (punto #1) y la auditoría (AUD-02) lo
señalaron: la resiliencia de ADR-001 estaba prometida pero sin implementar.

## Alternativas consideradas

- **No hacer nada / cambiar de proveedor a mano** (con el comando `/proveedor`): el
  usuario reacciona al fallo. Inservible para un bot desatendido.
- **Solo reintentos en el mismo proveedor** (backoff, sin cambiar de proveedor):
  cubre picos transitorios de rate limit, pero no un proveedor caído del todo.
- **Failover completo** (elegido): reintentos con backoff en el proveedor actual y,
  si aun así falla, degradar automáticamente al siguiente de la cadena ADR-001.
- **Usar un framework** (p. ej. la lógica de routing/fallback de LangChain): descartado
  por ADR-003 (a mano primero) y porque añade dependencia y opacidad para lo que son
  ~60 líneas propias y entendibles.

## Decisión

Un **`LLMRouter`** (`src/llm_router.py`) que recibe una cadena de `Eslabon`
(proveedor + clave + modelo) y, en `responder()`:

1. Prueba el proveedor actual.
2. Ante un fallo **reintentable** (rate limit, timeout, conexión —
   marcados con `reintentable = True` en `src/llm_errors.py`) espera con **backoff
   exponencial** (1 s, 2 s, 4 s...) y reintenta el **mismo** proveedor, hasta
   `max_reintentos`.
3. Ante un fallo **fatal** (clave inválida, petición inválida) o agotados los
   reintentos, **degrada al siguiente** proveedor de la cadena.
4. Si **todos** fallan, relanza el último `ErrorLLM` (nada se traga en silencio; el
   `Agente` lo convierte en un mensaje claro para el usuario).

La cadena se arma con `construir_cadena()`: el proveedor **elegido** en el menú es el
**primario**, y de fallback se añaden los demás de la cadena ADR-001 (Groq → Ollama →
Gemini) **que tengan su clave configurada** en el `.env`. Si solo hay una clave, la
cadena tiene un eslabón y se comporta como antes, sin código especial. `Agente` deja
de hablar con un proveedor suelto y pasa a usar el router; la degradación queda
registrada en `logs/agente.log`.

## Consecuencias

- ADR-001 pasa de promesa documental a comportamiento real: el bot sobrevive a fallos
  transitorios y a un proveedor caído sin intervención humana.
- El **modelo de cada fallback** sale hoy de `MODELOS[proveedor][0]`; **T5** unificará
  de dónde viene el modelo por defecto (una sola fuente de verdad, previsiblemente el
  `.env`). Este ADR no cierra esa cuestión.
- **Interacción con los reintentos del propio SDK:** algunos SDKs (p. ej. Groq) ya
  reintentan por su cuenta ante timeout/conexión. Los reintentos del router se **suman**
  a esos. Para un bot personal es aceptable; si se volviera un problema, se desactivarían
  los reintentos internos del SDK (`max_retries=0`) para que el router sea la única
  fuente de reintentos. Anotado como deuda, no bloqueante.
- El backoff es exponencial simple; **no** respeta todavía la cabecera `Retry-After`
  que algunos proveedores mandan en un 429. Mejora futura si hiciera falta.
- Coherente con ADR-003: hecho a mano, sin framework, testeable con proveedores falsos
  (7 tests en `tests/test_llm_router.py`, con las llamadas y las esperas inyectadas).
