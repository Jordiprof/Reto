# 07 — Matriz de trazabilidad

> **Fichero generado.** No se edita a mano: lo produce `scripts/trazabilidad.py`
> leyendo los identificadores de `docs/E1_Especificacion_Requisitos.md` y los
> marcadores `@pytest.mark.requisito(...)` de `tests/`. Para regenerarlo:
> `python scripts/trazabilidad.py`.

Norma de referencia: **ISO/IEC/IEEE 29148**, §5.2.8 (trazabilidad) y §5.2.5
(verificabilidad). La traza es **bidireccional**: de requisito a test en la tabla
de abajo, y de test a requisito en el propio codigo, que es donde vive el ancla.

**Cobertura de la traza: 31 de 46 identificadores** tienen al menos
un test que los nombra.

## Estado: conforme

La ultima ejecucion no encontro desajustes: ningun test apunta a un requisito
inexistente, todos los requisitos criticos estan trazados y los conteos de
tests declarados en la documentacion coinciden con los reales.

## Objetivos

| ID | Requisito | Prioridad | Verificado por |
|---|---|---|---|
| **OBJ-01** | Agente conversacional funcional sobre varios proveedores LLM, sin depender de ninguno | — | — *sin test que lo marque* |
| **OBJ-02** | Memoria que sobreviva al cierre del programa y se recupere **por significado**, no por palabra exacta | — | — *sin test que lo marque* |
| **OBJ-03** | Herramientas reales (tool calling) validadas y ampliables sin tocar el núcleo | — | — *sin test que lo marque* |
| **OBJ-04** | Exponerlo por Telegram **sin abrir un agujero de privacidad** — RNF-06 es el requisito rector | — | — *sin test que lo marque* |
| **OBJ-05** | Documentar el **porqué** de cada decisión (diario + ADR) | — | — *sin test que lo marque* |

## Requisitos funcionales

| ID | Requisito | Prioridad | Verificado por |
|---|---|---|---|
| **RF-01** | El usuario escribe por teclado y recibe respuesta del LLM, en bucle | Alta | — *sin test que lo marque* |
| **RF-02** | La API key se carga de variables de entorno, nunca del código | Crítica | `test_config.py` (3) |
| **RF-03** | Los errores de API (clave inválida, sin red, cuota) no rompen el programa | Alta | `test_llm_router.py` (2) |
| **RF-04** | El agente recuerda los mensajes anteriores de la sesión | Alta | — *sin test que lo marque* |
| **RF-05** | El comportamiento se define con un system prompt configurable | Alta | `test_compactar_historial.py` (1) |
| **RF-06** | La conversación se persiste en disco | Media | `test_compactar_historial.py` (1) · `test_storage.py` (1) |
| **RF-07** | El agente invoca herramientas y usa su resultado para responder | Alta | `test_tools.py` (2) |
| **RF-08** | Los parámetros que envía el modelo se **validan** antes de ejecutar nada | Crítica | `test_tools.py` (6) |
| **RF-09** | Se añaden herramientas nuevas sin modificar el núcleo del agente | Media | `test_tools.py` (1) |
| **RF-10** | El agente resuelve el caso de uso completo: asistente personal por Telegram | Alta | — *sin test que lo marque* |
| **RF-11** | El bot **solo** responde a `user_id` en lista blanca; el resto se ignora **antes** de llamar al LLM | Crítica | `test_telegram_seguridad.py` (7) |
| **RF-12** | El agente recupera **por significado** fragmentos de conversaciones de días anteriores | Alta | `test_rag.py` (2) |
| **RF-13** | Las herramientas se agrupan por categoría y se activan bajo demanda (`/tools`) | Alta | `test_main_cli.py` (6) · `test_tools.py` (2) · `test_tools_apagadas.py` (3) |
| **RF-14** | Se cambia de proveedor y de modelo en caliente, sin perder la conversación | Media | `test_config.py` (1) |
| **RF-15** | Si el proveedor primario falla, el sistema **reintenta y degrada** al siguiente solo | Alta | `test_llm_router.py` (2) |
| **RF-16** | Un turno tiene **presupuesto máximo de llamadas** al LLM (tope 15) | Alta | `test_llm_router.py` (1) |
| **RF-17** | Las conversaciones se guardan **cifradas** en disco (Fernet) | Crítica | `test_main_cli.py` (1) · `test_storage.py` (4) |
| **RF-18** | CLI y Telegram comparten la MISMA memoria: lo guardado por un canal se lee y se borra desde el otro | Alta | `test_rag.py` (1) |
| **RF-19** | El usuario puede listar, consultar y **borrar** una conversación de disco y del índice a la vez | Alta | `test_main_cli.py` (1) · `test_rag.py` (1) · `test_storage.py` (2) |
| **RF-20** | El bot acepta **documentos adjuntos** (PDF/Word) y responde sobre su contenido | Media | `test_documentos.py` (6) |
| **RF-21** | Entrada y salida por **voz** en Telegram | Media | `test_voz.py` (3) |
| **RF-22** | Un reintento **no vuelve a ejecutar** las herramientas ya ejecutadas en el turno | Alta | `test_llm_loop.py` (1) |
| **RF-23** | El bot **solo responde en chat privado**, nunca dentro de un grupo | Crítica | `test_telegram_seguridad.py` (3) |
| **RF-24** | CLI y bot **no pueden correr a la vez** sobre el mismo almacén | Alta | `test_cerrojo.py` (4) · `test_main_cli.py` (3) |
| **RF-25** | Un documento largo se resume **entero por bloques** (`/condensar`) | Media | `test_resumen_largo.py` (3) |
| **RF-26** | El historial **no crece sin freno**: se compacta y se avisa | Alta | `test_compactar_historial.py` (4) |

## Requisitos no funcionales

| ID | Requisito | Prioridad | Verificado por |
|---|---|---|---|
| **RNF-01** | Seguridad de credenciales | — | — *sin test que lo marque* |
| **RNF-02** | Fiabilidad | — | `test_llm_router.py` (3) · `test_main_cli.py` (1) |
| **RNF-03** | Mantenibilidad | — | — *sin test que lo marque* |
| **RNF-04** | Portabilidad | — | — *sin test que lo marque* |
| **RNF-05** | Seguridad del canal Telegram | — | `test_telegram_seguridad.py` (1) |
| **RNF-06** | Privacidad de los datos | — | `test_config.py` (1) · `test_main_cli.py` (3) · `test_rag.py` (1) · `test_red_segura.py` (5) · `test_storage.py` (1) |
| **RNF-07** | Trazabilidad | — | `test_logging.py` (3) |
| **RNF-08** | Verificabilidad | — | `test_documentos.py` (1) |

## Casos de uso

| ID | Requisito | Prioridad | Verificado por |
|---|---|---|---|
| **CU-01** | Pregunta simple | — | `test_telegram_seguridad.py` (1) |
| **CU-02** | Conversación con contexto | — | — *sin test que lo marque* |
| **CU-03** | Uso de herramienta | — | — *sin test que lo marque* |
| **CU-04** | Recuerdo multi-día | — | `test_rag.py` (1) |
| **CU-05** | Leer un documento | — | `test_documentos.py` (1) |
| **CU-06** | Resumir una web autorizada | — | — *sin test que lo marque* |
| **CU-07** | Cerrar sesión | — | — *sin test que lo marque* |

## Controles de seguridad

Controles de `docs/E2_Arquitectura.md` §8 y de `ADR-005` marcados desde los tests.

| Control | Verificado por |
|---|---|
| **E2-ABUSO** | `test_telegram_seguridad.py` (2) |
| **E2-ACCESO** | `test_telegram_seguridad.py` (4) |
| **E2-ARGUMENTOS** | `test_tools.py` (2) |
| **E2-CONTENIDO** | `test_tools.py` (3) |
| **E2-COSTE** | `test_llm_router.py` (1) |
| **E2-ENTRADA** | `test_telegram_seguridad.py` (2) |
| **E2-FICHEROS** | `test_documentos.py` (3) |
| **E2-IDEMPOTENCIA** | `test_llm_loop.py` (3) |
| **E2-RED** | `test_red_segura.py` (5) |
| **E2-REPOSO** | `test_rag.py` (1) · `test_storage.py` (2) |
| **E2-TRAZAS** | `test_logging.py` (3) |

## Conteo de casos de prueba

**830 casos** recolectados por pytest en 35 ficheros. Son casos, no funciones: 36 tests usan
`@pytest.mark.parametrize` y cada uno expande a varios casos.

