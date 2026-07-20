# ADR-002 — Memoria evolutiva del agente

**Estado:** ✅ Decisión (20/07/2026)
**Fecha:** 15/07/2026 (hipótesis, ver `AGENTS.md`) → 20/07/2026 (decisión, tras F3.3/F3.5) · **Decisor:** Jordi

## Contexto

El agente necesita memoria de conversación, con exigencias distintas por nivel: el
Básico no la necesita; el Intermedio necesita recordar el contexto dentro de una
conversación y persistirla a disco; el Avanzado necesitará gestionarla de forma más
estructurada (varias conversaciones, tools que la consulten); el Experto podría
necesitar búsqueda semántica, según la temática elegida.

## Alternativas consideradas

- **SQLite (o un vector store) desde el día 1**, para no migrar después.
- **Memoria evolutiva**: usar en cada nivel la solución más simple que cumpla el
  requisito de ese nivel, documentando cada salto con su motivo.

## Decisión

Memoria evolutiva en 4 escalones, uno por nivel:

1. **Básico** — sin memoria (una pregunta → una respuesta).
2. **Intermedio (cerrado, F3.1–F3.6)** — historial en memoria (lista de mensajes con
   roles `system`/`user`/`assistant`), reenviado completo en cada llamada. Persistencia
   en dos capas: **JSON completo por conversación** (F3.3, `conversations/*.json` —
   fuente de verdad) + **índice ligero en SQLite** (F3.5, `conversations.db`, tabla
   `conversaciones` con fecha/proveedor/modelo/ruta al JSON/nº de mensajes), sin
   duplicar el contenido completo en SQL todavía.
3. **Avanzado** — SQLite pasa a ser la fuente real de las conversaciones (no solo
   índice), previsiblemente con una tabla `mensajes` normalizada y relación con
   `conversaciones`.
4. **Experto** — memoria semántica (embeddings/vector store) **solo si el caso de uso
   elegido la justifica de verdad**, no por defecto.

## Consecuencias

- Cada nivel usa la memoria mínima suficiente para su requisito; no se adelanta
  trabajo de un nivel al anterior (ej.: no se normalizan mensajes en SQL en Intermedio).
- Durante todo el Intermedio, el **JSON es la única fuente completa y fiable** de cada
  conversación; si algún día SQLite y JSON discreparan, gana el JSON.
- El salto a SQLite como fuente real (normalizar `mensajes`) queda pendiente para
  Avanzado — trabajo previsto, no bloqueante ahora.
- No se ha implementado (ni lo pedía ningún nivel hasta ahora) recargar una
  conversación anterior al arrancar el programa; cada ejecución empieza con historial
  vacío. Queda como mejora candidata, no como requisito de este ADR.
