# E1 — Especificación de Requisitos

**Proyecto:** Agente de IA en terminal (nombre provisional)
**Autor:** Jordi · **Fecha:** 15/07/2026 (v1.0) → 17/07/2026 (v1.1) → 20/07/2026 (v1.2, temática Experto) → 21/07/2026 (v1.3, RAG semántico + privacidad rectora) → 27/07/2026 (v1.5, RNF-06 detallado en §4.1, incidencia de privacidad registrada y límite del canal de Telegram documentado) · **Versión:** 1.5 — documento vivo, evolucionará con el proyecto

## 1. Propósito

Construir de forma incremental, durante ~1 mes, un agente de IA ejecutado desde la terminal: primero un chat simple contra un LLM (Nivel Básico), después conversación con memoria (Intermedio), luego uso de herramientas mediante tool calling (Avanzado) y finalmente un proyecto completo sobre un caso de uso real (Experto). El objetivo es formativo: **comprender cada pieza de un agente antes de usar abstracciones**.

## 2. Alcance

**Incluye:** conversación por terminal (entrada/salida de texto) · historial de conversación · system prompt configurable · persistencia de conversaciones (JSON → SQLite) · herramientas vía tool calling · manejo de errores robusto · logging · configuración por variables de entorno (`.env`) · tests de las utilidades que no dependen del modelo · **Nivel Experto: agente asistente personal accesible por Telegram** (Bot API oficial), de un solo usuario autorizado.

**No incluye:** interfaz web o gráfica · **multiusuario público** (el bot de Telegram es de uso personal, con lista blanca — ver RNF-05) · entrenamiento o fine-tuning de modelos · despliegue en la nube · voz o imágenes.

**Evolución futura (conscientemente fuera de alcance):** interfaz web/dashboard y orquestación multiagente — la arquitectura modular (núcleo del agente separado de la CLI) las hace posibles sin reescribir el motor, pero no se abordan dentro del mes del reto.

## 3. Requisitos funcionales

| ID | Requisito | Prioridad | Nivel |
|---|---|---|---|
| RF-01 | El usuario escribe preguntas por teclado y recibe respuesta del LLM, en bucle, hasta escribir "salir" | Alta | Básico |
| RF-02 | La API key se carga desde variables de entorno, nunca desde el código | Alta | Básico |
| RF-03 | Los errores de API (key inválida, sin red, límite de peticiones) se manejan sin romper el programa | Alta | Básico |
| RF-04 | El agente recuerda los mensajes anteriores de la sesión (historial completo) | Alta | Intermedio |
| RF-05 | El comportamiento del asistente se define con un system prompt | Alta | Intermedio |
| RF-06 | La conversación se guarda en un fichero JSON con fecha al terminar | Media | Intermedio |
| RF-07 | El agente puede invocar herramientas (tool calling) y usar su resultado para responder | Alta | Avanzado |
| RF-08 | Los parámetros que el modelo envía a una herramienta se validan antes de ejecutarla | Alta | Avanzado |
| RF-09 | Se pueden añadir herramientas nuevas sin modificar el núcleo del agente | Media | Avanzado |
| RF-10 | El agente resuelve de principio a fin el caso de uso elegido: asistente personal accesible por Telegram | Alta | Experto |
| RF-11 | El bot solo responde a mensajes del usuario autorizado (lista blanca de `user_id` en `.env`); cualquier otro remitente se ignora antes de llamar al LLM | Alta | Experto |
| RF-12 | El agente recuerda lo hablado en conversaciones de días anteriores: recupera por significado (RAG semántico local) los fragmentos pasados relevantes y los usa en el contexto | Alta | Experto |
| RF-13 | El agente dispone de un conjunto de herramientas (calculadora, tiempo, recordatorios, consultar historial, noticias, etc.), añadidas de forma incremental y agrupadas por categoría | Alta | Experto |

## 4. Requisitos no funcionales

| ID | Requisito | Criterio |
|---|---|---|
| RNF-01 | Seguridad | La API key no aparece en el código ni en el historial de git |
| RNF-02 | Fiabilidad | Ante un fallo de API, el programa avisa al usuario y sigue vivo |
| RNF-03 | Mantenibilidad | Arquitectura modular; cambiar de proveedor LLM = cambiar configuración (`llm_client.py`) |
| RNF-04 | Portabilidad | Python 3.13 + venv + `requirements.txt` con versiones fijadas |
| RNF-05 | Seguridad/privacidad del canal (Telegram) | El bot se identifica por token (`.env`), nunca por el número de teléfono personal — sin self-bot (Telethon/Pyrogram descartados). Telegram sandboxea al bot: sin acceso a fotos, contactos ni otros chats. Filtrado por `message.from_user.id` contra lista blanca antes de cualquier llamada al LLM |
| RNF-06 | Privacidad de los datos (dato rector del Experto) | Las conversaciones y datos personales NO salen de la máquina de Jordi salvo la llamada mínima e inevitable al LLM. Se detalla en **§4.1** por ser el requisito rector del nivel Experto |

### 4.1 RNF-06 en detalle — privacidad de los datos

Requisito rector del nivel Experto: el bot es personal y confidencial, así que **los datos no
salen de la máquina salvo la llamada al LLM**. Este criterio decide buena parte del stack.

**Decisiones que se derivan de él**

| Decisión | Alternativa descartada | Motivo |
|---|---|---|
| Vector store local (ChromaDB) | Pinecone (nube) | El índice viviría en un tercero |
| Embeddings locales (fastembed/ONNX) | Embeddings de API de pago | Cada mensaje viajaría al proveedor para vectorizarse |
| Observabilidad solo local (`logs/`) | LangSmith | Manda las trazas completas a la nube |

**Cómo se protege el dato en cada sitio donde vive**

| Dónde | Protección | Qué queda expuesto (a propósito) |
|---|---|---|
| `conversations/*.json` | Cifrado **Fernet** (`cryptography`), F5.3 | Metadatos (fecha, proveedor, modelo, nombre): los necesita el índice |
| `conversations.db` (SQLite) | Solo índice, nunca contenido | Los mismos metadatos |
| `chroma_db/` (índice vectorial) | Solo vectores + punteros, **nunca el texto** | Los embeddings filtran algo de semántica (limitación asumida) |
| `logs/agente.log` | Solo metadatos de cada tool: nombre, estado, nombres de campos, tamaño, ms | Ni contenido, ni argumentos, ni claves |

El texto solo existe en claro **en memoria**, mientras se responde a una consulta: `rag.py`
descifra bajo demanda el mensaje concreto que ha encontrado, lo usa y no lo persiste en
ningún otro sitio.

**Límite del requisito: el canal de Telegram (documentado el 27/07).** Este requisito dice
que los datos no salen de la máquina *salvo la llamada al LLM*. Al añadir el bot (F5.2) esa
frase deja de ser exacta: **los mensajes enviados a un bot de Telegram no van cifrados de
extremo a extremo** — viajan por los servidores de Telegram, que técnicamente puede leerlos.
No es un defecto del código ni algo que el proyecto pueda mitigar: es una propiedad de la
Bot API, y el cifrado extremo a extremo de Telegram (*chats secretos*) no está disponible
para bots. Se documenta explícitamente para que el requisito no prometa más de lo que cumple.

La redacción exacta del requisito pasa a ser: *los datos no salen de la máquina salvo (a) la
llamada al LLM y (b) los mensajes intercambiados por el canal de Telegram, cuando se usa el
bot*. La CLI (`python -m src.main`) no tiene esta limitación. Alternativas descartadas: usar
un cliente de usuario en vez de un bot (self-bot con Telethon/Pyrogram) incumpliría los
términos de servicio y expondría el número personal — ver RNF-05.

**Modo de depuración.** Cuando hace falta depurar con el contenido real, la variable
`DEBUG_LOG_CONTENIDO` lo activa — pero escribe en un fichero **aparte**
(`logs/debug_contenido.log`, mediante un logger con `propagate=False`) y avisa en pantalla
mientras está activo. Así `agente.log` conserva una garantía que se puede verificar con un
test: *este fichero no contiene contenido, nunca*.

**Incidencia registrada — fuga de datos personales en logs (24 → 27/07/2026)**

Se documenta aquí, y no solo en el diario, porque afecta a la garantía que da este requisito.

- **Qué pasó.** La tarea F5.0/T8 (24/07) añadió trazas de auditoría por cada llamada a
  herramienta, registrando los argumentos y el resultado completos. Como la herramienta
  `buscar_en_recuerdos` devuelve mensajes **descifrados** de conversaciones anteriores, esos
  mensajes acababan en texto plano en `logs/agente.log` — anulando en la práctica el cifrado
  Fernet de F5.3 y el diseño sin-texto de ChromaDB, porque el mismo dato salía en claro por
  otro canal.
- **Por qué se coló.** No por falta de criterio: la regla estaba escrita **tres veces** — en
  este mismo RNF-06, en el requisito de la propia tarea T8 (*"sin datos sensibles"*) y en el
  acuerdo de diseño de F5.2. Ninguna de las tres se comprobaba automáticamente. **Tres reglas
  escritas y cero controles ejecutables.**
- **Alcance real.** Limitado a la máquina de desarrollo: `logs/` está en `.gitignore` y se
  verificó (`git log --all -- logs/`) que ningún log llegó nunca al repositorio. El fichero
  afectado se eliminó.
- **Corrección (27/07).** Política de **solo metadatos** en las trazas de herramientas; modo
  de depuración opt-in en fichero separado; rotación con tope de tamaño (~4 MB) para que
  cualquier dato que se cuele caduque solo; y registro del *tipo* de excepción en vez del
  texto crudo del SDK, que también podía arrastrar fragmentos de la petición.
- **Lección aplicada.** El arreglo incluye **tests de privacidad** que reproducen la fuga y
  fallan si vuelve a abrirse — el control que faltaba. Se siguió el patrón que ya existía
  para ChromaDB (`test_chromadb_no_guarda_el_texto_en_claro`), extendiéndolo a un canal que
  nadie había auditado. Análisis completo en `docs/diario_decisiones.md` (27/07).

## 5. Casos de uso principales

- **CU-01 Pregunta simple:** el usuario pregunta → el agente responde con el LLM.
- **CU-02 Conversación con contexto:** el usuario hace una pregunta que depende de lo dicho antes → el agente responde usando el historial.
- **CU-03 Uso de herramienta:** la pregunta requiere una acción (p. ej. un cálculo) → el modelo pide la herramienta, el programa la ejecuta y el agente responde con el resultado real.
- **CU-04 Guardar sesión:** el usuario escribe "salir" → la conversación queda persistida y el programa se cierra con confirmación.

## 6. Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Free tier agotado o con límites duros | Bloqueo del desarrollo | Cadena de proveedores decidida en ADR-001 (Groq → Ollama Cloud → Gemini → Anthropic) + abstracción `llm_client.py`, con selector de proveedor probado en F2.6 |
| Modelos gratuitos con tool calling pobre | Nivel Avanzado en riesgo | Validación previa contra docs oficiales (Fase 1) antes de decidir |
| La documentación de los SDKs cambia | Errores confusos | Usar siempre docs oficiales; fijar versiones en `requirements.txt` |
| El alcance se dispara | No llegar al Experto | Fases cerradas por nivel; los extras son opcionales |
| Filtración de la API key | Seguridad | `.gitignore` antes que la key; si ocurre, revocar en el proveedor |
| Prompt injection vía tools que leen texto externo (noticias RSS, web, correo si se retoma) | El agente podría obedecer instrucciones ocultas en contenido que no controla el usuario | Aislar el contenido no confiable del canal de instrucciones (es dato, nunca orden); tools de solo lectura con allowlist estricta; confirmación humana antes de cualquier acción con efectos (enviar, borrar, modificar); nunca combinar "leer contenido externo" + "actuar" en el mismo agente sin ese paso intermedio (hallazgo de la auditoría de seguridad, 23/07) |
| Un requisito de seguridad escrito pero sin control automático que lo verifique | Se incumple sin que nadie lo note, y la documentación pasa a afirmar una garantía falsa (ocurrió: ver §4.1, incidencia del 24-27/07) | Todo requisito de privacidad que se pueda expresar como invariante lleva un test que lo comprueba y falla si se rompe. Los tres existentes: el texto no aparece en el índice vectorial, no aparece en los logs, y el modo de depuración no contamina el log principal |
| Log injection: el nombre de una herramienta o de sus argumentos lo elige el modelo, no el programa | Un nombre con saltos de línea permitiría **falsificar entradas del registro de auditoría**, que es justo el fichero donde se comprueba qué hizo el agente | Saneado a caracteres de identificador y longitud acotada antes de escribir cualquier valor de origen no confiable en el log (`_nombre_seguro`/`_campos_seguros`), con tests que reproducen el intento (27/07) |

## 7. Preguntas abiertas

- ~~Temática del agente experto~~ — **resuelta (20/07).** Asistente personal accesible por Telegram (ver §2, RF-10/RF-11, RNF-05).
- ~~Proveedor definitivo~~ — **resuelta.** ADR-001 cerrado como Decisión el 16/07: Groq → Ollama Cloud → Gemini → Anthropic.
- ~~¿Groq debería seguir siendo el principal?~~ — **cerrada (20/07), sin cambios.** Tras varias rondas de pruebas con distintos modelos, Jordi decide no seguir ampliando comparativas: la cadena de `config.py` queda definitiva.
- ~~¿Hará falta memoria semántica en el Experto?~~ — **resuelta (21/07): sí.** Jordi la quiere de verdad: que el bot recuerde lo hablado días anteriores buscando en TODO el histórico por significado (no solo recargar la última conversación). Esto cumple la condición de ADR-002 ("memoria semántica solo si se justifica") — la justificación es esta necesidad real de recall multi-día. Se implementa con RAG local (ChromaDB + embeddings locales) en F5.3. Ver RF-12.
- ~~¿Agente único o multiagente?~~ — **resuelta (21/07): agente único.** 30 herramientas es un problema de organización de tools (agrupar/filtrar), no de coordinación entre agentes. Multiagente descartado como base (más complejo, más frágil, más movimiento de datos = menos privado); el patrón se toca solo como comparación educativa con LangGraph en F5.6. Ver diario y E3.
- ~~¿Correo (Gmail) para el bot?~~ — **aparcada (21/07).** Investigado: modo Testing gratis caduca el token cada 7 días (reautorizar a mano); modo Production exige verificación de Google para scope `gmail.readonly`. No encaja con "gratis y sin sorpresas" — en backlog, no en F5.
- **¿Hosting 24/7 del bot?** — abierta. Opciones evaluadas (ver `memory/TASKS.md`): PC propio (0€ pero debe estar encendido), Raspberry Pi (~36€ una vez, cero riesgo de facturación), Oracle Cloud Always Free (riesgo bajo pero real de cobro por error), PythonAnywhere (descartado: whitelist de salida rompería las APIs). Se decide al llegar a F5.2.
