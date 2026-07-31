# E4 — Entrega Final
## JIMMY — Asistente personal con IA (CLI + Telegram)

**Versión:** 1.0
**Fecha:** 15/07/2026 (v0.1, esqueleto) → 31/07/2026 (**v1.0**, redacción final)
**Autor:** Jordi
**Estado:** Entregado — Fase 5 cerrada

---

## 1. Qué es y qué hace

**JIMMY** es un asistente personal con IA, de un solo usuario, accesible por **terminal** y
por **Telegram**, que comparte la misma memoria por los dos canales. Recuerda lo hablado
días atrás buscando **por significado**, usa herramientas reales (tiempo, documentos, web
autorizada…) y **degrada solo** a otro proveedor LLM si el primero falla.

Está escrito **a mano, sin frameworks de agentes**: el bucle de tool calling, el enrutado
entre proveedores y la memoria semántica son código propio, porque el objetivo del reto era
entender esas piezas, no consumirlas.

### 1.1 Cifras de la entrega

| Métrica | Valor |
|---|---|
| Código fuente | **6.019 líneas** (13 módulos) |
| Tests | **5.559 líneas · 374 tests, todos en verde** |
| Proporción test/código | **0,92 : 1** |
| Herramientas implementadas | 7, en 6 categorías |
| ADR | 6, todos aceptados |
| Entradas del diario de decisiones | 13 días documentados |
| Commits | 64 |
| Lint (`ruff`) | limpio |
| CI (GitHub Actions) | verde: lint + tests + `pip-audit` |

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

---

## 3. Batería de tests

### 3.1 Distribución real

| Fichero | Tests | Qué protege |
|---|---|---|
| `test_tools.py` | 106 | Herramientas, validación de argumentos, SEG-07, categorías |
| `test_telegram_seguridad.py` | 80 | Las dos puertas, privacidad de logs, comandos, adjuntos |
| `test_red_segura.py` | 27 | Guardián anti-SSRF |
| `test_storage.py` | 20 | Cifrado, metadatos en claro, borrado |
| `test_llm_loop.py` | 19 | Bucle de tools, presupuesto, idempotencia |
| `test_documentos.py` | 18 | PDF/Word, bomba de descompresión |
| `test_config.py` | 17 | Configuración, lista blanca de dominios |
| `test_config_logging.py` | 16 | Modo depuración opt-in |
| `test_logging.py` | 14 | Política de solo metadatos |
| `test_rag.py` | 13 | Memoria semántica, privacidad del índice |
| `test_llm_gemini.py` | 13 | Traducción del dialecto de Gemini |
| `test_main_menus.py` | 11 | Menús de la CLI |
| `test_llm_router.py` | 9 | Reintentos y degradación |
| `test_agent.py` | 8 | Núcleo, contaminación de historial |
| `test_llm_client.py` | 3 | Despacho de tools |
| **TOTAL** | **374** | |

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

Cada herramienta se probó contra su API de verdad antes de darla por hecha. Esto encontró
**seis fallos que ningún test vio**:

| # | Fallo encontrado usando el bot | Causa |
|---|---|---|
| 1 | El modelo se inventaba el título de la foto de la NASA para una fecha pedida | Recibía la de hoy y no lo decía |
| 2 | El bot no indexaba al arrancar lo guardado por la CLI | Todos los tests espiaban el indexado en vez de arrancar el bot de verdad |
| 3 | La lista blanca de dominios quedaba **vacía en silencio** | `python-dotenv` no admite multilínea sin comillas |
| 4 | `leer_documento` reventaba solo en el venv | Dependencias instaladas en el Python equivocado |
| 5 | `leer_documento` **nunca se ejecutaba** en Telegram | Groq manda `null` cuando la tool no tiene parámetros |
| 6 | El agente se **citaba a sí mismo** como prueba tras inventarse un nombre | Su alucinación se persistió, se indexó y volvió como "recuerdo" |

**El nº 5 lo destapó el log, no el chat** — y el log solo tenía metadatos. La política de
privacidad del 27/07 resultó tener justo el dato que hacía falta, sin un solo carácter de
contenido.

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
- [x] Todo en repositorio Git con historial real (64 commits)
- [x] README funcional y verificado
- [x] Lint limpio (`ruff check src tests`)
- [x] Sin secretos en el código ni en el historial (verificado con `git log --all`)
- [x] Dependencias auditadas (`pip-audit` en CI, sin `continue-on-error`)
- [x] Versiones fijadas en `requirements-lock.txt`

### 5.2 Tests
- [x] 374 tests en verde
- [x] Controles críticos validados **por mutación**
- [x] Tests de privacidad que reproducen la fuga real del 27/07
- [x] CI verde en GitHub Actions
- [x] Prueba manual contra APIs reales de cada herramienta

### 5.3 Documentación
- [x] E1, E2, E3, E4 completos y actualizados
- [x] ADR-001 a ADR-006 aceptados
- [x] Diario de decisiones con 13 días, sin huecos
- [x] Reflexión final (§7)

### 5.4 Funcionalidad
- [x] CLI y bot funcionando
- [x] Memoria compartida entre los dos canales (con test de invariante)
- [x] 7 herramientas activables por categoría
- [x] Router degradando entre proveedores
- [x] Cifrado en reposo
- [ ] Voz por Telegram — **pendiente**
- [ ] Hosting 24/7 — **decisión abierta**

---

## 6. Limitaciones conocidas (declaradas, no escondidas)

| Limitación | Por qué está así | Cómo se cerraría |
|---|---|---|
| El texto del turno **sí** viaja al proveedor LLM | Inevitable sin modelo local | Ollama local |
| Un solo usuario: el bot **no arranca** con más de uno | El índice del RAG no está particionado | Particionar por `user_id` |
| CLI y bot a la vez sobre `chroma_db/` no está protegido | El cerrojo protege hilos, no procesos | Cerrojo de fichero |
| El RAG devuelve **preguntas, no respuestas** | Cada mensaje se indexa suelto | Indexar pares pregunta-respuesta |
| Documentos largos: solo 8.000 caracteres | Coste de contexto | Trocear + buscar por relevancia |
| El modelo no ve las **imágenes** de un PDF | `pypdf` extrae texto, no OCR | Contar imágenes y avisar; OCR |
| **DNS rebinding** no se cierra en el guardián | Haría falta conectar por IP con cabecera `Host` | Documentado como límite |
| `/salir` significa cosas distintas en CLI y bot | Deuda de nomenclatura | Renombrar o documentar |
| CVE-2026-45829 en `chromadb` sin parche | No explotable en modo embebido | Vigilada: si va a VPS, **nunca** como servicio |

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

Lo inmediato: **voz por Telegram** (Whisper por Groq para escuchar, **Piper local** para
hablar — la voz es un dato biométrico, así que la salida no sale de la máquina).

Después: Tavily, Obsidian y Outlook (evaluadas, no construidas) y la comparación honesta con
**LangGraph** reimplementando el router como grafo.

Detalle completo y motivos de las descartadas en **E3 §9**.

---

*E4 — Entrega Final v1.0 · 31/07/2026*
