# E1 — Especificación de Requisitos
## JIMMY — Asistente personal con IA (CLI + Telegram)

**Versión:** 2.1
**Fecha:** 15/07/2026 (v1.0) → 27/07/2026 (v1.5) → 31/07/2026 (v2.0) → 07/08/2026 (**v2.1**)
**Autor:** Jordi
**Estado:** Vigente — documento vivo

---

## 1. Alcance del proyecto

### 1.1 Descripción general

JIMMY es un asistente personal con IA, **de un solo usuario**, accesible por **terminal
(CLI)** y por **Telegram**, que comparte la misma memoria por los dos canales. Está
escrito **a mano, sin frameworks de agentes**: el bucle de tool calling, el enrutado
entre proveedores LLM y la memoria semántica son código propio.

Se construye en cuatro niveles incrementales (Básico → Intermedio → Avanzado → Experto).
El objetivo es **formativo**: entender cada pieza de un agente antes de usar una
abstracción que la esconda.

### 1.2 Objetivos

| ID | Objetivo |
|---|---|
| **OBJ-01** | Agente conversacional funcional sobre varios proveedores LLM, sin depender de ninguno |
| **OBJ-02** | Memoria que sobreviva al cierre del programa y se recupere **por significado**, no por palabra exacta |
| **OBJ-03** | Herramientas reales (tool calling) validadas y ampliables sin tocar el núcleo |
| **OBJ-04** | Exponerlo por Telegram **sin abrir un agujero de privacidad** — RNF-06 es el requisito rector |
| **OBJ-05** | Documentar el **porqué** de cada decisión (diario + ADR) |

### 1.3 Fuera de alcance (consciente)

Interfaz web o gráfica · multiusuario público · fine-tuning · despliegue en la nube ·
generación de imágenes. La arquitectura modular no impide añadirlos después, pero no
caben en el mes del reto.

---

## 2. Requisitos funcionales (RF)

### 2.1 Núcleo conversacional

| ID | Requisito | Prioridad | Nivel | Estado |
|---|---|---|---|---|
| RF-01 | El usuario escribe por teclado y recibe respuesta del LLM, en bucle | Alta | Básico | ✅ |
| RF-02 | La API key se carga de variables de entorno, nunca del código | Crítica | Básico | ✅ |
| RF-03 | Los errores de API (clave inválida, sin red, cuota) no rompen el programa | Alta | Básico | ✅ |
| RF-04 | El agente recuerda los mensajes anteriores de la sesión | Alta | Intermedio | ✅ |
| RF-05 | El comportamiento se define con un system prompt configurable | Alta | Intermedio | ✅ |
| RF-06 | La conversación se persiste en disco | Media | Intermedio | ✅ |

### 2.2 Herramientas

| ID | Requisito | Prioridad | Nivel | Estado |
|---|---|---|---|---|
| RF-07 | El agente invoca herramientas y usa su resultado para responder | Alta | Avanzado | ✅ |
| RF-08 | Los parámetros que envía el modelo se **validan** antes de ejecutar nada | Crítica | Avanzado | ✅ |
| RF-09 | Se añaden herramientas nuevas sin modificar el núcleo del agente | Media | Avanzado | ✅ |
| RF-13 | Las herramientas se agrupan por categoría y se activan bajo demanda (`/tools`) | Alta | Experto | ✅ |

### 2.3 Multi-proveedor y resiliencia

| ID | Requisito | Prioridad | Nivel | Estado |
|---|---|---|---|---|
| RF-14 | Se cambia de proveedor y de modelo en caliente, sin perder la conversación | Media | Avanzado | ✅ |
| RF-15 | Si el proveedor primario falla, el sistema **reintenta y degrada** al siguiente solo | Alta | Experto | ✅ |
| RF-16 | Un turno tiene **presupuesto máximo de llamadas** al LLM (tope 15) | Alta | Experto | ✅ |
| RF-22 | Un reintento **no vuelve a ejecutar** las herramientas ya ejecutadas en el turno | Alta | Experto | ✅ |

### 2.4 Memoria

| ID | Requisito | Prioridad | Nivel | Estado |
|---|---|---|---|---|
| RF-12 | El agente recupera **por significado** fragmentos de conversaciones de días anteriores | Alta | Experto | ✅ |
| RF-17 | Las conversaciones se guardan **cifradas** en disco (Fernet) | Crítica | Experto | ✅ |
| RF-18 | CLI y Telegram comparten la MISMA memoria: lo guardado por un canal se lee y se borra desde el otro | Alta | Experto | ✅ |
| RF-19 | El usuario puede listar, consultar y **borrar** una conversación de disco y del índice a la vez | Alta | Experto | ✅ |

### 2.5 Canal Telegram

| ID | Requisito | Prioridad | Nivel | Estado |
|---|---|---|---|---|
| RF-10 | El agente resuelve el caso de uso completo: asistente personal por Telegram | Alta | Experto | ✅ |
| RF-11 | El bot **solo** responde a `user_id` en lista blanca; el resto se ignora **antes** de llamar al LLM | Crítica | Experto | ✅ |
| RF-20 | El bot acepta **documentos adjuntos** (PDF/Word) y responde sobre su contenido | Media | Experto | ✅ |
| RF-21 | Entrada y salida por **voz** en Telegram | Media | Experto | ✅ 31/07 |
| RF-23 | El bot **solo responde en chat privado**, nunca dentro de un grupo | Crítica | Experto | ✅ 07/08 |
| RF-24 | CLI y bot **no pueden correr a la vez** sobre el mismo almacén | Alta | Experto | ✅ 01/08 |
| RF-25 | Un documento largo se resume **entero por bloques** (`/condensar`) | Media | Experto | ✅ 02/08 |
| RF-26 | El historial **no crece sin freno**: se compacta y se avisa | Alta | Experto | ✅ 02/08 |

### 2.6 Catálogo de herramientas implementadas

| Herramienta | Categoría | Capacidades (ADR-006) | Nivel | Encendida al arrancar |
|---|---|---|---|---|
| `calcular` | `calculadora` | — (función local pura) | **1** | ✅ |
| `consultar_tiempo` | `tiempo` | `red` (destino fijo) | **2** | ✅ |
| `consultar_historial` | `memoria` | — (lectura local de metadatos) | **2** | ❌ |
| `buscar_en_recuerdos` | `memoria` | — (lectura local descifrada) | **2** | ❌ |
| `consultar_foto_astronomica` | `foto_astronomica` | `red`, `contenido_externo` | **3** | ✅ |
| `leer_documento` | `documentos` | `contenido_externo` arbitrario | **4** | ✅ |
| `resumir_url` | `web` | `red` (**destino elegido por el modelo**), `contenido_externo` | **5** | ❌ |

> El nivel **se calcula** desde las capacidades declaradas, nunca se asigna a ojo (ADR-006).
> `memoria` y `web` arrancan apagadas por lo que **exponen hacia fuera**: `memoria` manda
> al proveedor conversaciones descifradas; `web` deja que el modelo elija el destino.

---

## 3. Requisitos no funcionales (RNF)

| ID | Requisito | Criterio de aceptación |
|---|---|---|
| RNF-01 | Seguridad de credenciales | Ninguna clave en el código ni en el historial de git |
| RNF-02 | Fiabilidad | Ante un fallo de API o un fichero corrupto, el programa avisa y sigue vivo |
| RNF-03 | Mantenibilidad | Cambiar de proveedor = cambiar configuración, no reescribir el agente |
| RNF-04 | Portabilidad | Python 3.13 + venv + `requirements-lock.txt` con versiones fijadas |
| RNF-05 | Seguridad del canal Telegram | Identidad por token, nunca por teléfono personal. Filtrado por `user_id` |
| **RNF-06** | **Privacidad de los datos** | **Los datos NO salen de la máquina salvo la llamada mínima al LLM** (§3.1) |
| RNF-07 | Trazabilidad | Toda llamada a herramienta se registra con **solo metadatos**, nunca contenido |
| RNF-08 | Verificabilidad | Los controles críticos se validan **por mutación**, no solo con tests en verde |

### 3.1 RNF-06 en detalle — el requisito rector del nivel Experto

Este criterio decide buena parte del stack. Cada decisión de abajo se toma **porque** el
dato no puede salir de la máquina:

| Decisión tomada | Alternativa descartada | Motivo |
|---|---|---|
| Vector store local (ChromaDB embebido) | Pinecone (nube) | El índice viviría en un tercero |
| Embeddings locales (fastembed/ONNX) | Embeddings de API | Cada mensaje viajaría al proveedor para vectorizarse |
| Observabilidad local (`logs/`) | LangSmith | Manda las trazas completas a la nube |
| Cifrado en reposo (Fernet) | JSON en claro | Un backup o un portátil perdido expondría todo |
| Logs de **solo metadatos** | Loguear argumentos y resultados | El log en claro anula el cifrado en disco |
| Lista blanca de dominios | Salida libre a internet | Sin ella, el modelo elige a qué servidor mandar datos |

**Límite conocido y aceptado:** el texto del turno actual **sí** viaja al proveedor LLM.
Es inevitable sin modelo local. Está documentado como límite, no disimulado.

**Matiz añadido el 31/07 — la voz (F5.5 #8).** La transcripción de notas de voz manda el
**audio** a Groq (Whisper), y eso es distinto de mandar texto: la voz es un dato
**biométrico** — identifica a la *persona* que habla, no solo lo que dijo. Por eso:

- se declara **aparte** y no dentro de "usa la red";
- la mitad de *escuchar* nace **apagada** y se enciende a mano en `/voz`, con el aviso
  delante en la misma pantalla (ahí, y no aquí, es donde se toma la decisión);
- con el interruptor apagado el audio **ni siquiera se descarga** de Telegram;
- la mitad de *hablar* **no paga nada**: Piper es local, sin clave ni cuota, y el audio
  generado no sale de la máquina.

Se aceptó Groq y no un Whisper local por usabilidad (0,5 s medidos frente a decenas de
segundos en CPU), y la decisión es reversible: `voz.transcribir(bytes) -> str` es una
función con una firma, cambiar el motor no toca el bot.

### 3.2 Incidencia de privacidad registrada (24–27/07) — y la lección

- **Qué pasó.** Las trazas de herramientas escribían argumentos y resultados en claro.
  Como `buscar_en_recuerdos` devuelve mensajes **descifrados**, `logs/agente.log` acabó
  conteniendo justo lo que `storage.py` cifra: **el cifrado en reposo no sirve de nada
  si el mismo dato sale en claro por otro canal.**
- **Por qué se coló.** No por falta de criterio: la regla estaba escrita **tres veces**
  (aquí, en el requisito de la tarea y en el acuerdo de diseño). Ninguna se comprobaba
  sola. **Tres reglas escritas y cero controles ejecutables.**
- **Alcance real.** Limitado a la máquina de desarrollo: `logs/` está en `.gitignore` y
  se verificó (`git log --all -- logs/`) que ningún log llegó al repositorio.
- **Corrección.** Política de **solo metadatos**; depuración opt-in en fichero aparte;
  rotación con tope de tamaño; y registro del *tipo* de excepción, no del texto crudo.
- **Lección, que es lo importante.** De aquí sale **RNF-08**: un requisito de seguridad
  sin un test que lo verifique es una promesa, no un control. Todos los invariantes de
  privacidad tienen ahora su test, y los críticos se validan **por mutación**.

---

## 4. Casos de uso principales

| ID | Caso de uso | Flujo resumido |
|---|---|---|
| CU-01 | Pregunta simple | Usuario pregunta → el LLM responde |
| CU-02 | Conversación con contexto | La pregunta depende de lo dicho antes → responde usando el historial |
| CU-03 | Uso de herramienta | El modelo pide la herramienta → se valida y ejecuta → responde con el dato real |
| CU-04 | Recuerdo multi-día | "¿Qué te conté del médico?" → RAG semántico sobre todo el histórico |
| CU-05 | Leer un documento | El usuario adjunta un PDF → pregunta sobre su contenido |
| CU-06 | Resumir una web autorizada | El usuario da una URL → el guardián valida → se descarga y se resume |
| CU-07 | Cerrar sesión | El usuario sale → la conversación se guarda (o se descarta) y se indexa |

---

## 5. Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Free tier agotado o con límites duros | Bloqueo del desarrollo | Cadena de proveedores (ADR-001) + router con degradación automática (ADR-004) |
| Modelos gratuitos con tool calling pobre | Nivel Avanzado en riesgo | Validado contra documentación oficial antes de decidir |
| Filtración de la API key | Seguridad | `.gitignore` antes que la clave; revocar en el proveedor si ocurre |
| **Prompt injection** vía herramientas que leen texto externo | El agente obedecería instrucciones ocultas en contenido ajeno | **SEG-07**: todo dato externo va delimitado (`<recuerdo>`, `<fuente>`) + saneado + el prompt declara que lo citado es dato, nunca orden |
| **SSRF** en herramientas cuyo destino elige el modelo | Acceso a la red interna o al endpoint de metadatos cloud (credenciales) | Guardián propio (`red_segura.py`): lista blanca + bloqueo de IPs internas + sin redirecciones |
| Requisito de seguridad escrito pero sin control automático | Se incumple sin que nadie lo note (**ocurrió**, §3.2) | RNF-08: test por invariante + validación por mutación |
| **Log injection** (el nombre de la tool lo elige el modelo) | Falsificar entradas del registro de auditoría | Saneado a identificador y longitud acotada antes de escribir en el log |
| Alucinación presentada como dato | El usuario se cree un dato falso | Avisos **en el propio resultado** de la herramienta, en forma de prohibición (patrón NASA APOD / truncado de documentos) |
| El alcance se dispara | No llegar al Experto | Fases cerradas por nivel; los extras son opcionales |

---

## 6. Trazabilidad: requisito → decisión → código → verificación

| Requisito | ADR | Dónde vive | Cómo se verifica |
|---|---|---|---|
| RF-07, RF-08, RF-09 | ADR-003 | `src/tools.py`, `src/llm_client.py` | `tests/test_tools.py` (115) |
| RF-13 | ADR-006 | `src/tools.py` (`categorias_por_defecto`) | `tests/test_tools.py` |
| RF-14, RF-15, RF-16, RF-22 | ADR-001, ADR-004 | `src/llm_router.py`, `src/llm_types.py` | `test_llm_router.py` (24), `test_llm_loop.py` (25), `test_cuota_y_orden.py` (20) |
| RF-12, RF-18 | ADR-002 | `src/rag.py`, `src/storage.py` | `test_rag.py` (29), `test_storage.py` (20) |
| RF-11, RNF-05 | ADR-005 | `src/telegram_bot.py` (puertas grupo −1) | `test_telegram_seguridad.py` (90) |
| RF-17, RNF-06 | ADR-002, ADR-005 | `src/storage.py` (Fernet) | `test_storage.py` |
| RF-20 | ADR-006 | `src/documentos.py` | `test_documentos.py` (39) |
| RNF-06 (SSRF) | ADR-006 | `src/red_segura.py` | `test_red_segura.py` (38), `test_redirecciones.py` (7) |
| RNF-07 | ADR-005 | `src/llm_client.py` (`_ejecutar_tool`) | `test_logging.py` (14), `test_config_logging.py` (16) |
| RF-21 | ADR-006 | `src/voz.py` (Whisper + Piper) | `test_voz.py` (21), `test_telegram_voz.py` (20) |
| RF-23 | ADR-005 | `src/telegram_bot.py` (`puerta_allowlist`) | `test_telegram_seguridad.py` |
| RF-24 | — | `src/cerrojo.py` (cerrojo del SO) | `test_cerrojo.py` (11), uno con subproceso real |
| RF-25 | — | `src/resumen_largo.py` | `test_resumen_largo.py` (36), `test_condensar_lectura.py` (17) |
| RF-26 | — | `src/agent.py` (`compactar_si_hace_falta`) | `test_compactar_historial.py` (12) |
| RNF-08 | — | `docs/diario_decisiones.md` | Pruebas de mutación documentadas con fecha |

---

## 7. Preguntas abiertas y cerradas

**Cerradas**
- ~~Temática del Experto~~ → asistente personal por Telegram (20/07)
- ~~Proveedor definitivo~~ → ADR-001: Groq → Ollama → Gemini (16/07), **revisado el 03/08 a Ollama → Groq → Gemini** por cuota diaria medida
- ~~¿Memoria semántica?~~ → **sí** (21/07): quiero recall multi-día real, no recargar la última conversación
- ~~¿Agente único o multiagente?~~ → **único** (21/07): 30 herramientas es un problema de organización, no de coordinación
- ~~¿Gmail?~~ → aparcada (21/07): el token caduca a los 7 días en modo Testing
- ~~¿Todo apagado por defecto en `/tools`?~~ → **revisado 31/07**: se apaga por *exposición*, no de forma uniforme

**Abiertas**
- **Hosting 24/7** — PC propio (0 €, debe estar encendido) · Raspberry Pi (~36 €, sin riesgo de factura) · Oracle Always Free (riesgo bajo pero real de cobro). Condicionante: si va a un VPS, ChromaDB sigue **embebido**, nunca como servicio (CVE-2026-45829)
- **Particionar el índice del RAG por usuario** — hoy el bot no arranca con más de un `user_id` a propósito

---

## 8. Glosario

| Término | Definición |
|---|---|
| **Tool calling** | Mecanismo por el que el LLM pide ejecutar una función y recibe su resultado |
| **Router** | Pieza que prueba proveedores en orden, con reintentos y degradación (ADR-004) |
| **RAG** | Recuperación por significado de fragmentos pasados para inyectarlos en el contexto |
| **Turno** | Un mensaje del usuario y todo lo que provoca (llamadas, herramientas, reintentos) |
| **Guardián** | Validador de URLs que impide SSRF (`src/red_segura.py`) |
| **SEG-07** | Convención propia: todo dato externo viaja delimitado (`<recuerdo>`, `<fuente>`) |
| **Prueba de mutación** | Romper un control a propósito y comprobar que un test se pone rojo |
| **ADR** | Architecture Decision Record: el porqué de una decisión, con sus alternativas |
| **Fallar cerrado** | Ante la duda o el error, denegar — nunca permitir |

---

*E1 — Especificación de Requisitos v2.0 · 31/07/2026*
