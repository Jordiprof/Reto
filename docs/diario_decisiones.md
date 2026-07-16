# Diario de decisiones técnicas ⭐

> Tabla oficial del reto: una fila por decisión, **con fecha**. Registra el porqué,
> no solo el qué. La reflexión final se añade al cierre (F6.2).

| Fecha | Semana/Nivel | Decisión | Alternativas consideradas | Por qué |
|---|---|---|---|---|
| 15/07/2026 | S1 / Fase 0 | `.gitignore` como **primer commit**, antes de cualquier código | Añadirlo más tarde; confiar en no commitear secretos | Hace imposible filtrar la API key en el historial de git; revertir una filtración es mucho más caro que prevenirla |
| 15/07/2026 | S1 / Fase 0 | Verificar **siempre** en docs oficiales antes de decidir (lección) | Fiarse de lo que citan los LLM | Kimi, ChatGPT y Gemini citaron modelos retirados ("Claude 3.5 Sonnet", "GPT-4o mini") como si fueran actuales |
| 15/07/2026 | S1 / Fase 0 | Cadena de proveedores LLM como **hipótesis**: Ollama Cloud → Groq → Anthropic (ADR-001) | Un solo proveedor de pago desde el inicio; OpenAI | Free tier primero (proyecto formativo sin presupuesto) + abstracción `llm_client.py`: cambiar de proveedor = cambiar configuración. Se valida en Fase 1 |
| 15/07/2026 | S1 / Fase 0 | Memoria del agente **evolutiva**: ninguna → lista+JSON → SQLite → semántica solo si se justifica (ADR-002) | SQLite o vector store desde el día 1 | Cada nivel usa la memoria más simple que cumple el requisito; cada salto se registrará con su motivo |
| 15/07/2026 | S1 / Fase 0 | Git: ramas `feature/*` → `main` + tag por nivel, **sin develop** | Git-flow completo con develop | Proyecto individual de 1 mes: develop añade burocracia sin beneficio; los 4 tags marcan las entregas |
| 15/07/2026 | S1 / Fase 0 | Documentación **versión ligera**: README + diario + E1–E4 (~1 pág) + 3-4 ADRs | Documentación exhaustiva (10+ documentos) | La doc debe ser proporcional al código; el tiempo del reto va a programar y comprender |
| 15/07/2026 | S1 / Fase 0 | `.env.example` incluye también los **modelos** por defecto; para Ollama, `gpt-oss:20b` | Solo claves API en `.env`; modelo escrito a fuego en el código | El modelo es configuración. Verificado en docs oficiales (15/07): el free tier de Ollama Cloud limita por cuota de uso, no por catálogo → conviene un modelo ligero (nivel 1) con soporte de tools |
| 16/07/2026 | S1 / Fase 0 | Pruebas reales de modelos gratuitos en 3 proveedores (Ollama Cloud, Google AI Studio, OpenRouter); Google y OpenRouter quedan como **candidatos**, no se amplía la cadena oficial todavía | Ampliar `llm_client.py` a 5 proveedores ya en Fase 0, sin comparación completa ni Groq probado | Evidencia real (`ollama launch`, OpenCode) da más y mejor información que un catálogo sin verificar; pero decidir la cadena definitiva antes de tiempo dispara el alcance (riesgo ya anotado en E1) — la decisión se cierra en F1.4 con todos los datos, ver ADR-001 |

## Reflexión final

_Se redacta al cierre del reto (F6.2)._
