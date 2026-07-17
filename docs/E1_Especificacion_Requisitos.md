# E1 — Especificación de Requisitos

**Proyecto:** Agente de IA en terminal (nombre provisional)
**Autor:** Jordi · **Fecha:** 15/07/2026 (v1.0) → 17/07/2026 (v1.1, cierre Nivel Básico) · **Versión:** 1.1 — documento vivo, evolucionará con el proyecto

## 1. Propósito

Construir de forma incremental, durante ~1 mes, un agente de IA ejecutado desde la terminal: primero un chat simple contra un LLM (Nivel Básico), después conversación con memoria (Intermedio), luego uso de herramientas mediante tool calling (Avanzado) y finalmente un proyecto completo sobre un caso de uso real (Experto). El objetivo es formativo: **comprender cada pieza de un agente antes de usar abstracciones**.

## 2. Alcance

**Incluye:** conversación por terminal (entrada/salida de texto) · historial de conversación · system prompt configurable · persistencia de conversaciones (JSON → SQLite) · herramientas vía tool calling · manejo de errores robusto · logging · configuración por variables de entorno (`.env`) · tests de las utilidades que no dependen del modelo.

**No incluye:** interfaz web o gráfica · multiusuario · entrenamiento o fine-tuning de modelos · despliegue en la nube · voz o imágenes.

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
| RF-10 | El agente resuelve de principio a fin el caso de uso elegido (temática pendiente) | Alta | Experto |

## 4. Requisitos no funcionales

| ID | Requisito | Criterio |
|---|---|---|
| RNF-01 | Seguridad | La API key no aparece en el código ni en el historial de git |
| RNF-02 | Fiabilidad | Ante un fallo de API, el programa avisa al usuario y sigue vivo |
| RNF-03 | Mantenibilidad | Arquitectura modular; cambiar de proveedor LLM = cambiar configuración (`llm_client.py`) |
| RNF-04 | Portabilidad | Python 3.13 + venv + `requirements.txt` con versiones fijadas |

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

## 7. Preguntas abiertas

- **Temática del agente experto** — decidir antes del 28/07 (condiciona herramientas y arquitectura final).
- ~~Proveedor definitivo~~ — **resuelta.** ADR-001 cerrado como Decisión el 16/07: Groq → Ollama Cloud → Gemini → Anthropic.
- **¿Groq debería seguir siendo el principal?** — F2.6 detectó un fallo factual de Groq (`llama-3.3-70b-versatile`) frente a aciertos de Ollama y Gemini en la misma pregunta, pero la comparación mezcló modelos distintos, no el mismo modelo en proveedores distintos. Pendiente de una prueba controlada (`gpt-oss:120b` también vía Groq) antes de tocar el ADR-001.
- **¿Hará falta memoria semántica en el Experto?** — solo si la temática lo justifica; se decide con la temática.
