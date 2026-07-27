# Agente de IA en Python — Reto DataQuantum

**Autor:** Jordi · **Periodo:** 15/07 → ~14/08/2026 · **Estado:** Nivel Avanzado completo (Fase 4); Fase 5 (Experto) en curso — endurecimiento previo (F5.0) antes del bot de Telegram

Agente de IA ejecutado desde la terminal, construido de forma incremental en 4 niveles:
chat simple contra un LLM (**Básico**) → conversación con memoria (**Intermedio**) →
uso de herramientas vía tool calling (**Avanzado**) → proyecto completo sobre un caso
de uso real (**Experto**). El objetivo es formativo: comprender cada pieza de un agente
antes de usar abstracciones.

## Puesta en marcha

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env         # rellenar claves API (ADR-001) y, opcionalmente, *_MODEL
```

`.env.example` documenta qué claves hacen falta y por qué (ADR-001). Las variables
`GROQ_MODEL` / `OLLAMA_MODEL` / `GEMINI_MODEL` son opcionales: fijan el modelo que
aparece preseleccionado en el menú; si se dejan vacías, el programa usa un valor por
defecto ya verificado.

## Uso

```bash
python -m src.main
```

Al arrancar, pide elegir proveedor (`groq` / `ollama` / `gemini` — cadena decidida en
[ADR-001](docs/ADR/ADR-001-proveedor-llm.md)) y modelo, y entra en un chat por terminal
**con memoria**: cada turno se reenvía junto con todo el historial anterior, así que el
agente recuerda lo que ya has hablado (incluso si cambias de proveedor a mitad).

**Failover automático (ADR-004):** el proveedor elegido es el *primario*, pero si falla
de forma transitoria (límite de peticiones, timeout, sin red), el agente reintenta con
espera creciente y, si sigue sin responder, degrada solo al siguiente proveedor de la
cadena ADR-001 que tenga clave configurada — sin que tengas que hacer nada. Si ves una
respuesta cuando esperabas un error, puede haber sido un fallback; el detalle queda en
`logs/agente.log`. Solo si **todos** los proveedores configurados fallan, ves un aviso.

Comandos disponibles dentro del chat (también `/comandos`, `/ayuda` o `/help` para verlos
sin salir de la conversación):

| Comando | Qué hace |
|---|---|
| `/modelo` | Cambia de modelo sin tocar el proveedor actual |
| `/proveedor` | Cambia de proveedor (y de modelo); la conversación sigue igual |
| `/historial` | Muestra tus conversaciones guardadas (fecha y nombre) para volver a leerlas |
| `/resumen` | Pide al modelo un resumen de la conversación hasta ahora, sin guardarlo como turno |
| `/limpiar` | Borra la conversación actual y empieza de cero (no toca lo ya guardado) |
| `/guardar` | Guarda la conversación ahora mismo, sin salir, con nombre opcional |
| `/salir` (o `salir`) | Termina; pregunta si quieres guardar (también se guarda si cortas con `Ctrl+C`) |

Todo menú de flechas (`/proveedor`→modelo, `/comandos`, `/historial`) tiene una opción
"⬅ Volver"/"Cancelar" para no perder el paso anterior sin cerrar el menú entero.

Cada conversación queda guardada en `conversations/<fecha>_<hora>.json` — **cifrada con
Fernet** si configuraste `CONVERSATIONS_KEY` en el `.env` (ver `.env.example`; si no, se
guarda en claro y el programa avisa al arrancar) — y también indexada en
`conversations.db` (SQLite, una fila por conversación — ver [E2 §2](docs/E2_Arquitectura.md)).
Al arrancar, el agente indexa tus conversaciones pasadas en un índice de memoria
semántica local (ChromaDB) para poder buscarlas por significado con la tool
`buscar_en_recuerdos` — pregúntale algo que le contaste antes y la usará.

**Logs (`logs/agente.log`):** registra latencia, tipo de error y, por cada llamada a una
herramienta, metadatos (nombre, si funcionó, nombres de los campos, tamaños) — **nunca
el contenido** de tus mensajes ni de lo que devuelven las herramientas, ni siquiera de
`buscar_en_recuerdos`. Si necesitas depurar con el contenido real, activa
`DEBUG_LOG_CONTENIDO=1` en el `.env`: escribe aparte, en `logs/debug_contenido.log`, y
verás un aviso en pantalla mientras esté activo.

## Documentación

| Documento | Qué contiene |
|---|---|
| [docs/diario_decisiones.md](docs/diario_decisiones.md) | ⭐ Tabla oficial de decisiones técnicas con fecha |
| [docs/E1_Especificacion_Requisitos.md](docs/E1_Especificacion_Requisitos.md) | Requisitos, alcance y riesgos |
| [docs/E2_Arquitectura.md](docs/E2_Arquitectura.md) | Arquitectura y diagrama global |
| [docs/E3_Estado_Arte_Planificacion.md](docs/E3_Estado_Arte_Planificacion.md) | Estado del arte y planificación por fases |
| [docs/E4_Entrega_Final.md](docs/E4_Entrega_Final.md) | Entrega final (se redacta al cierre) |
| [docs/ADR/](docs/ADR/) | Decisiones de arquitectura (ADRs) |

## Normas del proyecto

1. **Ninguna decisión sin fila fechada** en el diario de decisiones.
2. **Toda utilidad sin IA tiene tests** (norma activa desde el Nivel Intermedio).
3. **Toda excepción queda registrada** en `logs/`.
4. Los secretos viven en `.env` (gitignored); el repo solo contiene `.env.example`.

## Git

Ramas `feature/*` → `main`, con un tag por nivel completado:
`nivel-basico` · `nivel-intermedio` · `nivel-avanzado` · `nivel-experto`.
