# 06 — Gestión del sistema de IA

Referencia: **ISO/IEC 42001:2023** (sistema de gestión de IA) e **ISO/IEC
23894:2023** (gestión del riesgo en IA).

42001 es la norma más nueva de este kit y la que peor encaja en un proyecto de un
autor: buena parte de su articulado describe una organización con políticas de IA,
roles asignados y revisión por la dirección. Lo que sí encaja, y muy bien, es su
núcleo técnico: **el riesgo específico de usar un modelo de lenguaje**, que aquí
no es teórico.

## 1. Qué sistema de IA es este

| Aspecto | Valor |
|---|---|
| Tipo | Asistente conversacional con LLM y llamada a herramientas |
| Papel del proyecto (42001 §4) | **Usuario** de sistemas de IA de terceros. No se entrena, ni se afina, ni se aloja ningún modelo |
| Modelos usados | Groq, Google Gemini, OpenRouter y Ollama (local), intercambiables (`ADR-001`, `ADR-004`) |
| Autonomía | Media: el modelo elige qué herramienta invocar y con qué argumentos; **no** ejecuta nada sin validación previa |
| Efectos externos | **Ninguno hoy**. Ninguna herramienta escribe fuera del proceso ni envía nada a terceros |
| Intervención humana | El usuario ve cada respuesta. No hay decisiones automáticas sin persona delante |

Ese papel de "usuario, no desarrollador de modelos" descarta de golpe buena parte
de 42001 (datos de entrenamiento, sesgo del modelo, evaluación del rendimiento
del modelo) y concentra lo aplicable en cómo se usa el modelo y qué se le deja
hacer.

## 2. Riesgos de IA y su tratamiento

Los identificadores `IA-nn` son de este kit. El registro completo, con
probabilidad e impacto, está en `08_registro_riesgos.md`.

### IA-01 · Inyección de prompt · **Alto**

Contenido externo (una web, un documento, un recuerdo del RAG) que lleva
instrucciones ocultas y el modelo las obedece.

**Tratamiento** — `SEG-07`, en tres capas que no dependen de la buena voluntad
del modelo:

1. Todo dato externo va **delimitado** con etiqueta propia (`<fuente>`, `<recuerdo>`).
2. Se **sanea** para que el texto no pueda cerrar la cita y salirse de la etiqueta.
3. El prompt declara que lo citado es **dato, nunca orden**.

**Verificación**: 3 tests anclados como `E2-CONTENIDO` en `test_tools.py`,
incluido uno que prueba variantes de la etiqueta. Probado además en real contra
un documento con cuatro inyecciones: las cuatro rebotaron (`E4 §1.0`).

**Riesgo residual: medio.** Ninguna defensa contra inyección de prompt es
completa, y decir lo contrario sería falso. Lo que hace que aquí sea asumible es
que ninguna herramienta tiene efectos externos: una inyección que triunfara
podría ensuciar una respuesta, no mandar un correo.

### IA-02 · Alucinación presentada como dato · **Medio**

El modelo inventa un dato y el usuario se lo cree.

**Tratamiento**: avisos anti-alucinación **dentro del resultado de cada
herramienta**, redactados como prohibición, no en el prompt general. La
diferencia importa: el aviso viaja pegado al dato que podría inventarse.

**Verificación**: tests del patrón en `test_tools.py` y `test_documentos.py`.

Hay un caso real que conviene registrar porque enseña cómo se equivoca esto: con
un PDF cargado, preguntar quién ganó el Mundial devolvía *"no encuentro en ese
documento algo que indique que España ganó"*. El aviso decía "si la pregunta va
sobre él", y el modelo lo leía como que **todo** iba sobre el documento. Se
corrigió declarando también el caso contrario, explícitamente (commit `f4fadfa`).

### IA-03 · Envenenamiento de la memoria · **Bajo** — *cierra OWASP LLM03*

`E3 §6` recorre el OWASP Top 10 for LLM Applications y deja **LLM03 sin declarar**
(`NC-08`). Se cierra aquí.

LLM03 es envenenamiento de datos de entrenamiento y **no aplica**: el proyecto no
entrena ni afina modelos. Pero su equivalente sí existe: el índice ChromaDB es un
almacén persistente que el usuario alimenta, y del que se recuperan fragmentos
que acaban en el contexto del modelo. Un texto malicioso guardado hoy puede
influir en una respuesta dentro de un mes.

**Tratamiento**: el mismo `SEG-07` de IA-01 — todo recuerdo recuperado va
delimitado y saneado antes de entrar en el prompt, exactamente igual que una web.
La categoría `memoria` viene además **apagada al arrancar** (`ADR-006`).

**Riesgo residual: bajo**, y con un atenuante que no siempre existirá: el único
que puede escribir en la memoria es el propio usuario de la lista blanca.

### IA-04 · Robo del modelo · **No aplica** — *cierra OWASP LLM10*

El otro hueco de `E3 §6`. **No aplica**: no hay modelo propio que robar. Los
modelos son de terceros y se acceden por API con clave; Ollama corre en local con
modelos públicos. No hay activo de propiedad intelectual que proteger aquí.

Se declara para que la tabla de conformidad no tenga huecos sin explicación: un
hueco sin motivo se lee como un olvido, aunque la respuesta sea trivial.

### IA-05 · Fuga de datos al proveedor del LLM · **Alto** — aceptado

El texto de cada turno viaja al proveedor. Con `memoria` encendida, viajan además
recuerdos **descifrados** de conversaciones anteriores.

**Tratamiento**: no hay control que lo elimine, y el proyecto no finge que lo
haya. Lo que hay es reducción y declaración:

- La categoría `memoria` viene **apagada al arrancar**, así que por defecto no
  viajan recuerdos.
- Ollama en local permite operar **sin salida a internet**, a costa de calidad.
- El cifrado en reposo protege el disco, **no la conversación** — dicho tal cual
  en `E4 §1.0`.

**Riesgo residual: alto y aceptado.** Es el "privado a medias, por diseño" del
veredicto honesto. Un asistente que usa un LLM en la nube no puede ser
confidencial, y decirlo con precisión vale más que prometer lo contrario.

### IA-06 · Dependencia de un proveedor · **Bajo**

Que un proveedor cierre el nivel gratuito, cambie precios o retire un modelo.

**Tratamiento**: cadena de cuatro proveedores con degradación automática
(`ADR-001`, `ADR-004`), y Ollama local como último recurso, que no depende de
nadie. 24 tests en `test_llm_router.py`.

**Riesgo residual: bajo.** Es el riesgo mejor tratado del proyecto.

### IA-07 · La voz como dato biométrico · **Medio**

Las notas de voz se envían a Groq para transcribir. La voz es un dato biométrico,
y el propio `E4 §1.0` lo señala sin que nadie se lo pidiera.

**Tratamiento**: la categoría de voz viene **apagada al arrancar**; el audio no
se conserva tras transcribirlo; la síntesis (Piper) es **local**.

**Riesgo residual: medio.** La transcripción sigue siendo remota. Whisper local
lo cerraría, a coste de latencia y de tamaño de despliegue.

### IA-08 · Agencia excesiva · **Bajo hoy, alto mañana**

Que el modelo ejecute acciones con efecto real que nadie pidió.

**Tratamiento**, y aquí el diseño se adelantó al problema:

- **Ninguna herramienta tiene efectos externos todavía** — decisión consciente,
  registrada en `ADR-006`.
- El campo `repetible` de `Herramienta` tiene **`False` por defecto**, con el
  motivo escrito en el propio código (`src/tools.py:1290-1296`): ante el olvido,
  el comportamiento seguro.
- La idempotencia por turno ya está implementada y trazada (`RF-22`,
  `E2-IDEMPOTENCIA`): un reintento no ejecuta dos veces la misma herramienta.
- Presupuesto de 15 llamadas por turno (`RF-16`), nacido de un caso real en que
  un mensaje disparaba 45.

**Riesgo residual: bajo hoy.** La advertencia es que sube de golpe el día que se
añada la primera herramienta que escriba fuera del proceso. `ADR-006` ya define
cómo calcular ese riesgo; lo que falta es que el código lo calcule (`NC-11`).

## 3. Tabla OWASP LLM completada

Sustituye a la de `E3:199-209`, que dejaba dos filas sin declarar.

| Riesgo | Cómo se cierra | Estado |
|---|---|---|
| LLM01 Inyección de prompt | `SEG-07`: delimitar + sanear + declarar dato ≠ orden | ✅ IA-01 |
| LLM02 Manejo inseguro de salidas | Validación Pydantic; errores propios, nunca volcados de Python | ✅ |
| **LLM03 Envenenamiento de datos** | **No aplica (no se entrena). Su equivalente —envenenar la memoria— se trata con el mismo `SEG-07`** | ✅ **IA-03** |
| LLM04 Denegación de servicio | Rate limit + presupuesto de 15 llamadas + timeouts | ✅ |
| LLM05 Cadena de suministro | `pip-audit` sin `continue-on-error`; lockfile con hashes | ✅ |
| LLM06 Fuga de información | Cifrado en reposo + logs de solo metadatos (hubo incidencia real) | ✅ |
| LLM07 Plugins inseguros | Cada tool declara capacidades; activación por categorías | 🟡 el riesgo se define pero **no se calcula en código** (`NC-11`) |
| LLM08 Agencia excesiva | Ninguna tool con efectos externos; idempotencia lista | ✅ IA-08 |
| LLM09 Exceso de confianza | Avisos anti-alucinación dentro del resultado de la tool | ✅ IA-02 |
| **LLM10 Robo del modelo** | **No aplica: no hay modelo propio** | ✅ **IA-04** |
| SSRF (fuera del Top 10, el riesgo real aquí) | Guardián propio: lista blanca + IPs internas + sin redirecciones | ✅ |

## 4. Evaluación frente a 42001

| Cláusula | Estado |
|---|---|
| 4 · Contexto y papel en el ciclo de vida de la IA | ✅ §1 y `00_alcance.md` |
| 5 · Liderazgo y política de IA | 🟡 Hay criterio explícito ("la privacidad decide", `E3 §1`), no un documento de política |
| 6 · Planificación y tratamiento del riesgo | ✅ §2 y `08_registro_riesgos.md` |
| 7 · Recursos, competencia y documentación | ✅ 6 ADR y 170 decisiones fechadas |
| 8 · Operación | ✅ Controles implantados y probados |
| 9 · Evaluación del desempeño | 🟡 Sin métricas de calidad de respuesta. Ver §5 |
| 10 · Mejora continua | ✅ Diario, auditorías, este kit |
| A.2 Política de IA | 🟡 Implícita |
| A.4 Recursos del sistema de IA | ✅ `ADR-001` con comparativa medida, no supuesta |
| A.5 Evaluación de impacto | 🟡 Parcial: `E1 §3.1` y `E4 §1.0` cubren privacidad; falta el impacto en la persona usuaria |
| A.6 Ciclo de vida del sistema de IA | ✅ E1-E4 y los ADR |
| A.7 Datos para el sistema de IA | ✅ `00_alcance.md` §5 |
| A.9 Uso responsable | ✅ Limitaciones declaradas sin adornos (`E4 §1.0` y §6) |
| A.10 Terceros y proveedores | 🟡 Evaluados técnicamente; sin acuerdo de tratamiento de datos |

## 5. El hueco: no se mide la calidad de las respuestas

42001 §9 pide evaluar el desempeño del sistema de IA. Aquí **no se mide**: no hay
métrica de exactitud, ni de tasa de alucinación, ni conjunto de evaluación.

Y hay una decisión razonada detrás, no un olvido. `diario:173` registra el
descarte de un *mini eval harness*: las baterías manuales contra APIs reales
encontraron **15 fallos reales** que un harness automático, midiendo contra un
criterio inventado a posteriori, no habría encontrado ni uno.

Es un argumento bueno y este kit no lo contradice. Lo que sí señala es su límite:
las pruebas manuales **no se repiten en cada cambio**. Hoy nada detectaría que un
cambio de modelo empeora las respuestas, salvo que el usuario lo note usándolo.

**Propuesta mínima**, sin construir el harness descartado: un puñado de preguntas
fijas con respuesta conocida, ejecutadas a mano al cambiar de modelo, con el
resultado anotado en el diario. Diez minutos por cambio de modelo, y convierte una
impresión en un dato.
