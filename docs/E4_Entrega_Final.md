# E4 — Entrega Final
## JIMMY — Asistente personal con IA (CLI + Telegram)

**Versión:** 1.2
**Fecha:** 15/07/2026 (v0.1, esqueleto) → 31/07/2026 (v1.0) → 07/08/2026 (v1.1) → 08/09/2026 (**v1.2**)
**Autor:** Jordi
**Estado:** Entregado — Fase 5 cerrada, con mantenimiento post-cierre documentado

> **v1.1 (07/08):** actualizado tras siete días más de trabajo que la v1.0 no recogía —
> voz, cerrojo entre procesos, `/condensar`, reordenación de ADR-001, dos auditorías de
> seguridad y las baterías de prueba manual. Los tests pasaron de 374 a 784.

> **v1.2 (08/09):** un mes de mantenimiento post-cierre que la v1.1 no recogía. Lo más
> relevante: **el hosting 24/7 ya está resuelto** (VPS Hetzner desde el 21/08, con aviso
> automático si el bot se cae — antes era la única pieza abierta en §8); la cobertura de
> rama se mide por primera vez (79,86 %, umbral en CI); la primera ejecución real de
> mutación encuentra y cierra un control sin test en el guardián anti-SSRF (NC-07); kit de
> auto-evaluación contra cuatro normas ISO (`docs/normas/`), con 16 no conformidades
> detectadas y 10 cerradas; y la licencia pasa de MIT a propietaria, corrigiendo una
> contradicción con el propio objetivo del reto. Los tests pasaron de 784 a 831.

---

## 1. Qué es y qué hace

**JIMMY** es un asistente personal con IA, de un solo usuario, accesible por **terminal** y
por **Telegram**, que comparte la misma memoria por los dos canales. Recuerda lo hablado
días atrás buscando **por significado**, usa herramientas reales (tiempo, documentos, web
autorizada…) y **degrada solo** a otro proveedor LLM si el primero falla.

Está escrito **a mano, sin frameworks de agentes**: el bucle de tool calling, el enrutado
entre proveedores y la memoria semántica son código propio, porque el objetivo del reto era
entender esas piezas, no consumirlas.

### 1.0 Veredicto honesto: seguro sí, privado a medias, confidencial no

Se pone aquí, lo primero y no escondido al final, porque es la pregunta que de verdad
importa en un asistente que maneja datos personales:

| | Veredicto | Por qué |
|---|---|---|
| **Seguro** | ✅ **Sí** | Frente a terceros aguanta: acceso por lista blanca y solo chat privado, que **falla cerrado** y está validado por mutación; cero secretos en 80 commits; guardián anti-SSRF (con la doctrina de fallar cerrado ahora también probada por mutación, NC-07); las cuatro inyecciones del documento de prueba rebotaron |
| **Privado** | 🟡 **A medias, por diseño** | El texto de cada turno **viaja al proveedor del LLM**, y con `memoria` encendida viajan recuerdos descifrados. El cifrado protege el disco, no la conversación. Telegram no es E2E. Los **títulos** de las conversaciones salen. La voz es un dato biométrico |
| **Confidencial** | ❌ **No** | La clave de cifrado vive **en la misma carpeta** que los datos que cifra. Protege contra el descuido, no contra alguien con acceso a la máquina |

**Esto no es una disculpa, es el resultado.** Un asistente que usa un LLM en la nube no
puede ser confidencial, y decirlo con precisión vale más que prometer una seguridad que
no se sostiene. Las limitaciones completas están en §6, sin esconder ninguna.

### 1.1 Cifras de la entrega

| Métrica | Valor |
|---|---|
| Código fuente | **11.205 líneas** (18 módulos) |
| Tests | **12.505 líneas · 831 tests, todos en verde** |
| Proporción test/código | **1,12 : 1** — hay más test que código |
| Cobertura de rama | **79,86 %** (medida por primera vez el 04/09; umbral en CI = 79) |
| Verificación por mutación | Primera ejecución real (06/09): 167 mutantes sobre los 3 módulos críticos, 100 muertos, 67 vivos — 1 no era ruido y cerró NC-07 |
| Herramientas implementadas | 7, en 6 categorías |
| ADR | 6 aceptados (ADR-001 **revisado** el 03/08) |
| Entradas del diario de decisiones | **25 días · 181 decisiones** |
| Commits | 80 |
| Lint (`ruff`) | limpio en **todo** el repo (`src`, `tests` y `scripts`) |
| CI (GitHub Actions) | verde: lint + tests + cobertura de rama + `pip-audit` sobre el lockfile; mutación informativa (`\|\| true`) |
| Auditorías de seguridad | **3** (23/07, 27/07, 04-07/08) |
| Auto-evaluación ISO (`docs/normas/`) | 4 familias de normas, 16 no conformidades (**10 cerradas, 2 a medias, 4 abiertas**) tras la segunda pasada del 06/09 |
| Licencia | **Propietaria** (cambiada de MIT el 06/09 — MIT autorizaba justo lo que no se quería conceder) |

---

## 2. Desarrollo por niveles

### Nivel Básico (17/07) — `nivel-basico`
Chat en bucle contra un LLM, con la clave en `.env`, errores manejados y logging.

**Aprendido:** los catálogos de modelos que citan las IA están caducados. Verificar siempre
contra documentación oficial — la lección que gobernó el resto del proyecto.

### Nivel Intermedio (20/07) — `nivel-intermedio`
Historial completo reenviado cada turno, system prompt configurable, `/resumen`,
persistencia en JSON + índice SQLite, y el primer test con `pytest`.

**Aprendido:** el system prompt **cambia comportamiento, no solo estilo** — verificado con
un experimento sobre 3 modelos: el estilo "formal" **se negaba** a contar un chiste en los
tres. Y como el historial se reenvía entero, el coste por turno crece con la longitud del
estilo elegido.

### Nivel Avanzado (22/07) — `nivel-avanzado`
Clase `Agente`, tool calling real en los 3 proveedores, JSON Schema derivado de Pydantic,
validación de argumentos.

**Aprendido:** el bucle es el mismo patrón en los tres proveedores pero **cada uno lo
implementa distinto**. Bug real: Gemini puede repartir la petición de función en **cualquier
`part`** de la respuesta, no siempre en la primera.

### Nivel Experto (23–31/07) — `nivel-experto`

| Sub-fase | Qué se construyó |
|---|---|
| **F5.0** Endurecimiento | El bucle de tools, duplicado ×3, pasa a vivir **una sola vez** sobre formas neutras; errores tipados; timeouts; router de fallback (ADR-004) |
| **F5.2** Bot de Telegram | Dos puertas de seguridad en grupo −1; reutiliza `Agente` sin tocarlo |
| **F5.3** Cifrado + RAG | Fernet en reposo; ChromaDB embebido con embeddings locales; memoria compartida CLI↔bot |
| **F5.5** Herramientas | 7 tools por categorías; guardián anti-SSRF; `/tools` |

**Aprendido, lo más valioso:** endurecer **antes** de exponer. F5.0 no estaba planificada —
salió de una auditoría hecha a propósito antes de tocar Telegram.

### Mantenimiento post-cierre (04–06/09)

Con el reto ya entregado, un mes de trabajo adicional cerró huecos que habían quedado
documentados como abiertos en la v1.1:

| Qué se hizo | Resultado |
|---|---|
| Cobertura de rama medida por primera vez, en un job de CI separado | 78,01 % → **79,86 %** tras 15 tests nuevos sobre `main.py` (17 % → 34 %) |
| Primera ejecución real del job de mutación, escrito desde el 04/09 pero nunca lanzado | 167 mutantes, 100 muertos, 67 vivos; **NC-07**: encontró un `return True`/`False` sin test en el guardián anti-SSRF |
| Auto-evaluación contra 4 normas ISO (`docs/normas/`) | 16 no conformidades detectadas; **10 cerradas, 2 a medias, 4 abiertas** tras la segunda pasada |
| Licencia: MIT → propietaria | MIT autorizaba copiar y redistribuir; el repositorio se comparte para evaluarlo, no para reutilizarlo |
| `pip-audit` cazó 6 CVEs nuevas (2ª vez) | `pypdf` actualizado con cirugía sobre el lockfile; 3 CVEs de `chromadb` ignoradas con motivo escrito en el propio `ci.yml` |

Detalle día a día en el diario de decisiones (04/09 en adelante) y en `docs/normas/09_no_conformidades.md`.

---

## 3. Batería de tests

### 3.1 Distribución real

| Fichero | Tests | Qué protege |
|---|---|---|
| `test_tools.py` | 115 | Herramientas, validación de argumentos, SEG-07, categorías |
| `test_telegram_seguridad.py` | 91 | Las tres puertas, privacidad de logs, comandos, adjuntos |
| `test_telegram_ux.py` | 39 | Menús, catálogo de comandos, estado de espera |
| `test_documentos.py` | 39 | PDF/Word, bomba de descompresión, troceo |
| `test_red_segura.py` | 39 | Guardián anti-SSRF |
| `test_resumen_largo.py` | 36 | `/condensar` por bloques |
| `test_rag.py` | 30 | Memoria semántica, privacidad del índice |
| `test_readme.py` | 28 | **Que el README no mienta** |
| `test_noticias.py` | 27 | `/noticias`: RSS, fechas RFC-822/ISO, lista blanca |
| `test_llm_loop.py` | 25 | Bucle de tools, presupuesto, idempotencia |
| `test_llm_router.py` | 24 | Reintentos, degradación, reservas de modelo |
| `test_voz.py` | 21 | Whisper + Piper, límites de duración |
| `test_telegram_voz.py` | 20 | La puerta de la voz antes de descargar el audio |
| `test_storage.py` | 21 | Cifrado, metadatos en claro, borrado |
| `test_cuota_y_orden.py` | 20 | Cuota diaria, orden de proveedores, tope por proveedor |
| `test_config.py` | 19 | Configuración, lista blanca de dominios |
| `test_avisos_caida.py` | 19 | Avisos de caída distinguiendo tokens/peticiones/día |
| `test_condensar_lectura.py` | 17 | Caché de lectura, una llamada por bloque |
| `test_recuerdo_y_limpiar.py` | 18 | Ruido del RAG, `/limpiar`, reglas del prompt |
| `test_config_logging.py` | 16 | Modo depuración opt-in |
| `test_gemini_toolcall_texto.py` | 15 | Rescate de tool-calls escritas como texto |
| `test_main_cli.py` | 17 | Lista blanca en la CLI, descifrado, `/tools` y **el cerrojo desde `main()`** |
| `test_logging.py` | 14 | Política de solo metadatos |
| `test_agent.py` | 14 | Núcleo, contaminación de historial |
| `test_llm_gemini.py` | 13 | Traducción del dialecto de Gemini |
| `test_tool_call_mal_generada.py` | 12 | `tool_use_failed` como reintentable |
| `test_telegram_presentacion.py` | 12 | Markdown, foto duplicada, estado y adjuntos |
| `test_compactar_historial.py` | 14 | AUD-03: el historial no crece sin freno |
| `test_tools_apagadas.py` | 11 | Aviso de categoría apagada |
| `test_main_menus.py` | 11 | Menús de la CLI |
| `test_cerrojo.py` | 11 | Cerrojo del SO entre procesos |
| `test_telegram_condensar.py` | 9 | `/condensar` por Telegram |
| `test_clave_cifrado.py` | 9 | Validación de la clave Fernet |
| `test_redirecciones.py` | 7 | Que una redirección no salte el guardián |
| `test_llm_client.py` | 5 | Despacho de tools |
| **TOTAL** | **831** | |

### 3.2 Cómo se ejecutan

```bash
venv/Scripts/python.exe -m pytest -q
venv/Scripts/python.exe -m ruff check src tests
```

> **Nota de método, aprendida a base de fallar (31/07):** ejecutar con el intérprete del
> **venv**, no con `python` a secas. Instalé dos dependencias en el Python del sistema y di
> por verdes 362 tests que eran verdes **en el entorno equivocado**; en el venv la
> funcionalidad reventaba. "Verde" no significa nada si no sabes dónde.

### 3.3 Verificación por mutación (RNF-08)

Los controles críticos no se dan por buenos porque los tests pasen: **se rompen a propósito
y se comprueba que un test se pone rojo**. Ocho mutaciones aplicadas; **dos sobrevivieron y
destaparon tests que no comprobaban lo que decían**. Detalle en E3 §6.1.

### 3.4 Pruebas manuales contra APIs reales

Cada herramienta se probó contra su API de verdad antes de darla por hecha. **Esta es la
técnica que más fallos ha encontrado en todo el proyecto** — y ninguno lo vio un test:

| # | Fallo encontrado usando el bot | Causa |
|---|---|---|
| 1 | El modelo se inventaba el título de la foto de la NASA para una fecha pedida | Recibía la de hoy y no lo decía |
| 2 | El bot no indexaba al arrancar lo guardado por la CLI | Todos los tests espiaban el indexado en vez de arrancar el bot de verdad |
| 3 | La lista blanca de dominios quedaba **vacía en silencio** | `python-dotenv` no admite multilínea sin comillas |
| 4 | `leer_documento` reventaba solo en el venv | Dependencias instaladas en el Python equivocado |
| 5 | `leer_documento` **nunca se ejecutaba** en Telegram | Groq manda `null` cuando la tool no tiene parámetros |
| 6 | El agente se **citaba a sí mismo** como prueba tras inventarse un nombre | Su alucinación se persistió, se indexó y volvió como "recuerdo" |
| 7 | El guardián de SSRF **enseñaba a saltárselo** | Una IP interna no está en la lista blanca, así que salía por el mensaje genérico: *"pide que añadan 192.168.1.1 a la lista"* |
| 8 | El modelo **reescribió las fechas** de una previsión meteorológica | Copió las 21 cifras sin error y cambió solo el año y el mes. La API había respondido bien |
| 9 | La cuota diaria se reintentaba **tres veces por mensaje** | El aviso decía "esto no se arregla esperando" y el código, acto seguido, esperaba |
| 10 | `/condensar` leía el documento **dos veces** | Con un solo bloque, la segunda pasada resumía su propio resumen |
| 11 | La foto de la NASA llegaba **duplicada** a Telegram | Dos caminos: `send_photo` y la vista previa del enlace en el texto |
| 12 | `/guardar` **se comió una conversación** | Sin argumento no dejaba nada esperando: el nombre se lo tragó el LLM, que contestó con un resumen inventado |
| 13 | Un adjunto **no cancelaba** un `/recuerdo` pendiente | La pregunta siguiente sobre el documento se la comió la búsqueda en memoria |
| 14 | El modelo hablaba con **un JIM imaginario** | El guardián decía "que JIM lo añada" en tercera persona, y el modelo —hablando con JIM— buscó un intermediario |
| 15 | El bot **envenenó su propia memoria** | Se inventó que su comida favorita era "pizza con albahaca"; quedó indexado como hecho y `/recuerdo` lo devolvía |

**El nº 5 lo destapó el log, no el chat** — y el log solo tenía metadatos. La política de
privacidad del 27/07 resultó tener justo el dato que hacía falta, sin un solo carácter de
contenido.

**Los nº 7, 13 y 14 son el mismo fallo por tres puertas distintas**, y esa es la lección
más útil de todas: arreglar el camino concreto no cierra la clase. El estado de espera
sobrevivía a una nota de voz (01/08, arreglado), y seguía sobreviviendo a un adjunto
(07/08). El guardián dejó de enseñar a saltárselo con IP literales (02/08), y seguía
haciéndolo con `localhost` (07/08).

---

## 4. Cómo ejecutarlo desde cero

```bash
git clone <repo> && cd python-agentes-ia-dq
python -m venv venv
venv\Scripts\activate
pip install -r requirements-lock.txt
copy .env.example .env
```

Rellenar en `.env` al menos una clave de proveedor (`GROQ_API_KEY` recomendada, gratis y sin
tarjeta). Después:

```bash
python -m src.main
```

Para el bot de Telegram hacen falta además `TELEGRAM_BOT_TOKEN` (de @BotFather) y
`TELEGRAM_USER_IDS_PERMITIDOS` (tu `user_id`):

```bash
python -m src.telegram_bot
```

> ⚠️ **No ejecutar la CLI y el bot a la vez:** comparten `chroma_db/` y ese acceso
> concurrente entre **procesos** no está protegido (el cerrojo de `rag.py` protege hilos
> dentro de un proceso, no procesos distintos). Está avisado por pantalla al arrancar.

### 4.1 Variables de entorno

| Variable | Obligatoria | Para qué |
|---|---|---|
| `GROQ_API_KEY` | ✅ (o la de otro proveedor) | Proveedor primario |
| `OLLAMA_API_KEY`, `GEMINI_API_KEY` | Recomendadas | Fallback automático |
| `CONVERSATIONS_KEY` | Recomendada | Cifrado en reposo (Fernet) |
| `TELEGRAM_BOT_TOKEN` | Solo para el bot | Identidad del bot |
| `TELEGRAM_USER_IDS_PERMITIDOS` | Solo para el bot | Lista blanca. **Con más de uno el bot no arranca, a propósito** |
| `TELEGRAM_LOG_SAL` | Solo para el bot | Sal para la huella del `user_id` en los logs |
| `DOMINIOS_PERMITIDOS_WEB` | Para `resumir_url` | Lista blanca de dominios (36 auditados por DNS) |
| `DEBUG_LOG_CONTENIDO` | No | Depuración opt-in, a fichero **aparte** |

---

## 5. Checklist de entrega

### 5.1 Código
- [x] Todo en repositorio Git con historial real (80 commits)
- [x] README funcional y verificado — **con 26 tests que impiden que vuelva a mentir**
- [x] Lint limpio en **todo** el repo (`ruff check .`, incluido `scripts/`)
- [x] Sin secretos en el código ni en el historial (`gitleaks` sobre 80 commits, 4 ramas)
- [x] Dependencias auditadas (`pip-audit` en CI, sin `continue-on-error`)
- [x] Versiones fijadas y **con hashes** en `requirements-lock.txt` (`--require-hashes`)
- [x] Licencia propietaria, coherente con que el proyecto se comparte para evaluarlo, no para reutilizarlo

### 5.2 Tests
- [x] 831 tests en verde
- [x] Cobertura de rama medida (79,86 %) con umbral real en CI, no uno "redondo"
- [x] Controles críticos validados **por mutación** — primera ejecución real el 06/09, cerró NC-07
- [x] Tests de privacidad que reproducen la fuga real del 27/07
- [x] CI verde en GitHub Actions, con permisos mínimos y Actions fijadas por SHA
- [x] Prueba manual contra APIs reales de cada herramienta
- [x] **Baterías de prueba manual guionizadas** (CLI y Telegram), incluida prompt injection

### 5.3 Documentación
- [x] E1, E2, E3, E4 completos y actualizados
- [x] ADR-001 a ADR-006 aceptados (ADR-001 **revisado** el 03/08, con la decisión original intacta)
- [x] Diario de decisiones con **25 días y 181 decisiones**, sin huecos
- [x] Reflexión final (§7)
- [x] Tres informes de auditoría de seguridad (23/07, 27/07, 04-07/08)
- [x] Kit de auto-evaluación contra 4 normas ISO (`docs/normas/`), con matriz de trazabilidad y registro de no conformidades verificable

### 5.4 Funcionalidad
- [x] CLI y bot funcionando
- [x] Memoria compartida entre los dos canales (con test de invariante)
- [x] 7 herramientas activables por categoría
- [x] Router degradando entre proveedores **y entre modelos del mismo proveedor**
- [x] Cifrado en reposo
- [x] **Voz por Telegram** ✅ 31/07 — Whisper por Groq + Piper local, ambos apagados al arrancar
- [x] **Cerrojo entre procesos** ✅ 01/08 — CLI y bot ya no pueden corromper el índice
- [x] **`/condensar`** ✅ 02/08 — resumen por bloques de documentos largos
- [x] **Hosting 24/7** ✅ 21/08 — VPS Hetzner CX23 (Núremberg, sin permanencia), aislado por usuario Linux + `MemoryMax`/`CPUQuota` en systemd, con aviso automático por Telegram si el servicio cae
- [x] Mini eval harness y conversor de formatos — **evaluados y decididos no construir** (07/08, cierre de Fase 5, ver §8)

---

## 6. Limitaciones conocidas (declaradas, no escondidas)

| Limitación | Por qué está así | Cómo se cerraría |
|---|---|---|
| El texto del turno **sí** viaja al proveedor LLM | Inevitable sin modelo local | Ollama local |
| **La clave de cifrado vive junto a los datos que cifra** | `CONVERSATIONS_KEY` está en el `.env`, en la misma carpeta que `conversations/`. Protege contra el descuido (copiar la carpeta, un backup a la nube), **no contra alguien con acceso a la máquina**: tendría la caja fuerte y la llave encima | Contraseña maestra al arrancar, o un gestor de secretos del sistema. Se descartó por usabilidad en un asistente de uso diario |
| **La voz sale de la máquina al transcribir** | Whisper corre en Groq. Es un dato **biométrico** | Whisper local (descartado: decenas de segundos en CPU). Mitigado: apagado por defecto, con el aviso en el propio menú |
| **Telegram no cifra de extremo a extremo** | Los mensajes pasan por sus servidores | Ninguna: es el precio del canal. Declarado, no disimulado |
| Un solo usuario: el bot **no arranca** con más de uno | El índice del RAG no está particionado | Particionar por `user_id` |
| El modelo no ve las **imágenes** de un PDF | `pypdf` extrae texto, no OCR | Contar imágenes y avisar; OCR |
| No se puede pedir **un fragmento por número** | La búsqueda es por significado; un número no significa nada | Índice por posición además del semántico |
| **DNS rebinding** no se cierra en el guardián | Haría falta conectar por IP con cabecera `Host` | Resolver una vez y fijar la IP |
| CVE-2026-45829 en `chromadb` sin parche | **1.5.9 es la última que existe** (verificado en PyPI). No explotable en modo embebido | Vigilada: si va a VPS, **nunca** como servicio |
| El modelo puede **reescribir un dato** que la herramienta le dio bien | No hay control que lo cierre: la API responde bien y el texto se estropea después | Mitigado (día de la semana en las fechas, regla en el prompt) + elegir mejor modelo |
| **La insistencia puede vencer a la cautela** del modelo | Es un límite del modelo, no del código | Regla en el prompt; verificado que ahora aguanta 3 insistencias |

### 6.1 Limitaciones que la v1.0 declaraba y **ya están cerradas**

| Limitación de la v1.0 | Cerrada |
|---|---|
| ~~CLI y bot a la vez sobre `chroma_db/` no está protegido~~ | ✅ **01/08** — `src/cerrojo.py`, cerrojo del SO. El segundo proceso no arranca |
| ~~El RAG devuelve **preguntas, no respuestas**~~ | ✅ **02/08** — ventana de turno: si el acierto es la pregunta, adjunta su respuesta |
| ~~Documentos largos: solo 8.000 caracteres~~ | ✅ **01-02/08** — troceo + búsqueda por relevancia, y `/condensar` para el documento entero |
| ~~`/salir` significa cosas distintas en CLI y bot~~ | ✅ **01/08** — en Telegram pasa a llamarse `/cerrar`, con `/salir` como alias oculto |

---

## 7. Reflexión final

Empecé este reto pensando que la parte difícil sería que el agente **funcionara**. Ha sido
lo más fácil. Lo difícil ha sido que funcione **de forma en la que pueda confiar**.

**Tres cosas que no esperaba aprender:**

**1. Un requisito escrito no es un control.** La fuga de datos personales en los logs (24-27/07)
es el momento del que más he aprendido. La regla estaba escrita **tres veces** en la
documentación, y aun así se incumplió durante días. No falló el criterio: faltaba algo que lo
comprobara solo. De ahí salió RNF-08 y la costumbre de **romper los controles a propósito**
para ver si alguien se entera. Dos de esas mutaciones no encontraron bugs en el código —
encontraron **tests míos que no comprobaban lo que decían comprobar**. Eso me hizo desconfiar
del "los tests pasan" como prueba de nada.

**2. Los tests y la realidad son cosas distintas.** Seis de los fallos más serios del proyecto
aparecieron **usando el bot**, no ejecutando la suite. Los tests protegen contra las regresiones
que ya sabes imaginar; usar el producto te enseña las que no. El caso que mejor lo resume: un
modelo, al recibir un error técnico, **se inventó que yo no había adjuntado el documento** —
me echó la culpa de un fallo del servidor. Ningún test podía ver eso, porque el código hacía
exactamente lo que le habían pedido.

**3. Una alucinación puede convertirse en un recuerdo.** El último día el agente se inventó
que se llamaba "Sam", esa frase se guardó y se indexó como cualquier otra, y minutos después
la recuperó de su propia memoria y **la citó como prueba**. Ver un sistema fabricar evidencia
para sostener un error propio ha sido la lección más incómoda y la más útil: la memoria no
distingue lo que pasó de lo que el modelo dijo que pasó, salvo que se lo digas explícitamente.

**4. Un arreglo cierra un camino, no una clase (añadido el 07/08).** Tres veces me ha pasado
lo mismo: arreglo un fallo, lo doy por cerrado, y semanas después reaparece **por la puerta
de al lado**. El estado de espera que se comía el mensaje siguiente lo arreglé para las notas
de voz (01/08) y seguía roto para los adjuntos (07/08). El guardián que enseñaba a saltárselo
lo arreglé para las IP literales (02/08) y seguía haciéndolo con `localhost` (07/08). La
pregunta que aprendí a hacerme no es *"¿está arreglado?"* sino *"¿por dónde más se entra
aquí?"* — y la respuesta suele estar en el propio código, a un `grep` de distancia.

**5. Verificar una alerta cuesta un comando; no verificarla puede costar mucho más.** Una
auditoría automática marcó como bloqueante un *"secreto filtrado en el historial de git"* y
pedía **rotar la clave y reescribir el historial**. Lo comprobé: era un valor de un test que
existe justamente para verificar que una clave rota **no** se filtra. La misma auditoría pedía
actualizar `chromadb` "a una versión parcheada" que **no existe**. Dos operaciones
destructivas, cero problemas reales. Esto ya me había pasado con una tabla de riesgo generada
por una IA y con una lista de dominios "auditada": la costumbre de pedir evidencia antes de
actuar es de lo más rentable que me llevo.

**Lo que haría distinto.** Comitear más pequeño y más a menudo: al final acabé con cambios de
tres asuntos distintos enredados en los mismos ficheros. Y verificar el entorno de ejecución
antes de cantar victoria, no después.

**Lo que me llevo.** Que la seguridad no es una capa que se añade al final, sino una serie de
decisiones pequeñas que se toman cuando nadie mira: apagar `web` por defecto, no seguir
redirecciones, loguear solo metadatos, no dejar que el modelo elija una ruta de fichero. Ninguna
es espectacular. Juntas son la diferencia entre un juguete y algo que dejaría hablando con
mis datos.

---

## 8. Trabajo futuro

**El hosting 24/7 ya no es trabajo futuro.** JIMMY corre desde el 21/08 en un VPS Hetzner
CX23, aislado por usuario Linux propio, con topes de memoria en systemd y aviso automático
por Telegram si el servicio se cae. Detalle en el diario de decisiones (21/08 en adelante).

**Lo que queda abierto, por orden de valor:**

| Tema | Por qué |
|---|---|
| Tavily, Obsidian, Outlook | Evaluadas y no construidas (ADR-006). Outlook es **la única que sacaría datos personales**: matizaría RNF-06 |
| Indexar pares pregunta-respuesta *de verdad* | Hoy se resuelve al **buscar** (ventana de turno). Indexarlos como pareja sería la solución completa |
| Particionar el RAG por usuario | Hoy el bot **no arranca** con más de un `user_id`, a propósito |

**Descartado por el camino:**

- **Comparación con LangGraph** (F5.6). Era un extra desde el principio y el tiempo se fue en
  cosas con más valor — doce bugs reales del 01/08, la memoria del RAG, el condensado de
  documentos y tres agujeros de seguridad. Una comparación honesta exige reimplementar el
  router entero, y a medias no dice nada.
- **Mini eval harness** (07/08, cierre de Fase 5). Las baterías de prueba manual encontraron
  **15 fallos reales** que un harness automático, midiendo contra un criterio inventado a
  posteriori, no habría encontrado ni uno — el proyecto ya tenía algo mejor para lo mismo.
- **Conversor de formatos** (F5.5 #9, 07/08). Habría sido la primera tool en escribir en disco
  sin que ninguna necesidad real lo pidiera; ya evaluado y descartado en ADR-006.

Detalle completo y motivos de las descartadas en **E3 §9**.

---

*E4 — Entrega Final v1.2 · 08/09/2026*
