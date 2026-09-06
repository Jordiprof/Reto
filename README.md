# Agente de IA en Python — Reto DataQuantum

**Autor:** Jordi · **Periodo:** 15/07 → ~14/08/2026 · **Estado:** Niveles Básico,
Intermedio y Avanzado completos (Fases 2–4, con tag). **Nivel Experto (Fase 5) en
cierre:** memoria semántica con RAG local, validación de herramientas con Pydantic,
**bot de Telegram** con memoria compartida con la CLI, catálogo de herramientas por
categorías ([ADR-006](docs/ADR/ADR-006-catalogo-y-riesgo-de-herramientas.md)), lectura de
PDF/Word, voz y resumen de documentos largos por bloques.

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

`requirements.txt` tiene las dependencias directas. Para reproducir el entorno
**exacto** con el que se pasan los tests —las 110 dependencias, transitivas incluidas,
con su hash SHA256— está `requirements-lock.txt`, que es lo que instala el CI:

```bash
pip install --require-hashes -r requirements-lock.txt
```

El hash no es adorno: una versión fija dice *qué* paquete quieres, pero no garantiza que
lo que baja de PyPI sea ese — quien controle la cuenta de un paquete puede reemplazar el
archivo de una versión ya publicada. El hash fija el **contenido**.

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
| `/recuerdo <texto>` | Busca a mano en la memoria semántica y enseña lo encontrado en crudo, sin pasar por el modelo (útil para comprobar qué hay indexado) |
| `/borrar` | Elige una conversación guardada y la borra de verdad (fichero + índice de memoria); pide confirmación porque es irreversible |
| `/tools` | Activa o desactiva categorías de herramientas para esta sesión (ver el default más abajo) |
| `/documento <ruta>` | Le da un PDF o un Word para que pueda leerlo y responder sobre él |
| `/condensar` | Resume el documento **entero** por bloques: completo (un `.md` con secciones) o rápido (unas líneas en pantalla) |
| `/noticias` | Informe en español de lo último en IA, tecnología y ciberseguridad, en un `.md` (ver más abajo) |
| `/salir` (o `salir`) | Termina; pregunta si quieres guardar (también se guarda si cortas con `Ctrl+C`) |

Todo menú de flechas (`/proveedor`→modelo, `/comandos`, `/historial`, `/tools`) tiene una
opción "⬅ Volver"/"Cancelar" para no perder el paso anterior sin cerrar el menú entero.

### `/noticias`: qué hace y qué NO hace

Lee los RSS de ocho medios en inglés (Ars Technica, MIT Technology Review, The Verge,
TechCrunch, WIRED, VentureBeat, BleepingComputer y The Record), se queda con lo publicado
en los últimos días, elige lo de más impacto, abre esos artículos y escribe un informe en
español en `resumenes/`. Prueba real del 08/08: **118 candidatas → 10 noticias, 2 llamadas
al modelo, 73 segundos.**

Dos cosas que conviene tener claras, y por eso están escritas también dentro de cada
informe que genera:

- **No cubre una semana, cubre unos 2 días.** Un RSS no guarda historia: guarda sus
  últimas 10-50 publicaciones. Medido el 08/08, eso va de medio día (The Verge) a 4,9
  días (MIT Technology Review). Pedirle "los últimos 7 días" sería prometer algo que no
  hay al otro lado.
- **No investiga: lee una lista fija.** Si algo importante sale en un medio que no está
  en la lista, no se entera.

**No depende de `/tools` ni de la lista blanca de dominios**, y eso es deliberado. Las
fuentes son una constante de `src/noticias.py`, no una variable del `.env`: el modelo
nunca elige a dónde ir, solo recibe texto ya descargado. Así `resumir_url` **sigue sin
poder visitar una web de noticias por su cuenta** — que es justo lo que se decidió al
dejarlas fuera de la lista blanca por ser el contenido más manipulable que puede leer el
bot. Hay un test que se pone rojo si alguien las añade.

El cuerpo de cada artículo va envuelto en `<fuente>`, igual que `resumir_url` y
`leer_documento`; los metadatos (medio, fecha, enlace) van **fuera** de la cita, porque
son nuestros y no del artículo.

**Herramientas disponibles** (activables por categoría con `/tools`, catálogo completo y
criterio de riesgo en [ADR-006](docs/ADR/ADR-006-catalogo-y-riesgo-de-herramientas.md)):
calculadora, tiempo y previsión (Open-Meteo, sin clave), consulta de historial propio,
foto astronómica del día (NASA APOD), lectura de PDF/Word y resumen de una página web.
Esta última solo acepta URLs de un listado de dominios oficiales autorizado en `.env`
(`DOMINIOS_PERMITIDOS_WEB`), validado además contra IPs internas antes de descargar nada
(`src/red_segura.py`, protección anti-SSRF). Si un dominio autorizado redirige, se sigue
el salto **revalidando el destino con el mismo guardián**, nunca a ciegas.

**Qué arranca encendido y por qué.** No es "todo apagado" ni "todo encendido", sino
apagado **por exposición**: arrancan en OFF solo `memoria` (porque
`buscar_en_recuerdos` manda al proveedor del LLM tus conversaciones pasadas
descifradas — de poco sirve cifrarlas en disco si salen en claro por otro canal) y
`web` (porque es la única cuyo **destino elige el modelo**). El resto arranca en ON:
su coste es de tokens, no de exposición. `documentos` también, porque **entregar el
fichero ya es la autorización** — pedir un segundo permiso era fricción sin seguridad
a cambio.

Cada conversación queda guardada en `conversations/<fecha>_<hora>.json` — **cifrada con
Fernet** si configuraste `CONVERSATIONS_KEY` en el `.env` (ver `.env.example`; si no, se
guarda en claro y el programa avisa al arrancar) — y también indexada en
`conversations.db` (SQLite, una fila por conversación — ver [E2 §2](docs/E2_Arquitectura.md)).
Al arrancar, el agente indexa tus conversaciones pasadas en un índice de memoria
semántica local (ChromaDB) para poder buscarlas por significado con la tool
`buscar_en_recuerdos` — pregúntale algo que le contaste antes y la usará. La búsqueda
devuelve **el intercambio completo**, pregunta y respuesta juntas: encontrar solo la
pregunta no servía de nada, porque el dato está en lo que se contestó.

**Logs (`logs/agente.log`):** registra latencia, tipo de error y, por cada llamada a una
herramienta, metadatos (nombre, si funcionó, nombres de los campos, tamaños) — **nunca
el contenido** de tus mensajes ni de lo que devuelven las herramientas, ni siquiera de
`buscar_en_recuerdos`. Si necesitas depurar con el contenido real, activa
`DEBUG_LOG_CONTENIDO=1` en el `.env`: escribe aparte, en `logs/debug_contenido.log`, y
verás un aviso en pantalla mientras esté activo.

## Bot de Telegram

El mismo agente, accesible desde el móvil. **Reutiliza la clase `Agente` sin modificarla**:
solo cambia quién le hace las preguntas (ver [ADR-005](docs/ADR/ADR-005-seguridad-bot-telegram.md)).

```bash
python -m src.telegram_bot
```

> **Solo puede haber UNO corriendo.** La CLI y el bot comparten `conversations/` y el
> índice de ChromaDB, que están pensados para un único proceso, así que el segundo en
> arrancar se niega con `⛔ Ya hay otro proceso usando la memoria` (ver `src/cerrojo.py`).
> Si te pasa y no ves ninguna ventana abierta, es que quedó un proceso huérfano:
>
> ```bash
> Get-Process python | Stop-Process -Force
> ```
>
> Arráncalo desde una **terminal normal**, no con el botón de depurar del editor: algunos
> lo lanzan dentro de un proceso envoltorio y acabas con dos `python.exe`.

Antes hay que rellenar dos variables en el `.env`:

| Variable | Cómo se obtiene |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Creando el bot con [@BotFather](https://t.me/BotFather) en Telegram |
| `TELEGRAM_USER_IDS_PERMITIDOS` | Tu `user_id`, escribiendo a [@userinfobot](https://t.me/userinfobot) |

**El bot es estrictamente privado.** Solo responde a los `user_id` de la lista blanca y
comprueba esa lista **antes** de llamar al modelo; a cualquier otro lo ignora en silencio,
sin contestar (responder confirmaría que el bot existe y gastaría cuota). **Sin lista
blanca configurada, el bot no arranca** — es deliberado: un bot abierto no solo gastaría
tu cuota, es que la herramienta `buscar_en_recuerdos` le entregaría tus conversaciones a
un desconocido con solo preguntar.

Por el mismo motivo **solo se admite un `user_id`**: la memoria semántica es común a todo
el histórico y todavía no distingue de quién es cada recuerdo, así que dos usuarios
autorizados se leerían mutuamente. Con más de uno, el bot se niega a arrancar.

**La memoria es compartida con la CLI**: lo que guardas desde el terminal se puede buscar
desde Telegram y viceversa (mismo almacén cifrado + mismo índice semántico).

Comandos dentro del chat (`/comandos` los lista con botones que **ejecutan** el comando,
no que lo expliquen):

| Comando | Qué hace |
|---|---|
| `/start` | Bienvenida y las cuatro cosas que sabe hacer |
| `/ayuda` | Lista de comandos con botones |
| `/historial` | Lista tus conversaciones guardadas y **abre** la que elijas (abrir = leerla, no retomarla como contexto) |
| `/recuerdo <texto>` | Busca en la memoria y enseña lo encontrado en crudo, sin pasar por el modelo |
| `/guardar <nombre>` | Guarda la conversación en curso con nombre |
| `/borrar` | Borra una conversación, con confirmación en dos pasos |
| `/resumen` | Resumen de la conversación actual |
| `/limpiar` | Empieza de cero (la guarda y olvida el contexto) |
| `/cerrar` | Cierra la charla: guardarla, ponerle nombre o descartarla |
| `/voz` | Escucharte y/o contestarte hablando — **los dos empiezan apagados** |
| `/tools` | Activar o desactivar categorías de herramientas |
| `/condensar` | Resume el documento adjunto entero: completo (`.md` que te llega como fichero) o rápido |
| `/noticias` | Informe de lo último en IA, tecnología y ciberseguridad; te llega como `.md` |
| `/documento` | No hace falta escribirlo: **mándale el PDF o el Word como adjunto** y ya está |
| `/modelo`, `/proveedor` | Con botones inline en vez de menús de flechas |

`/borrar` y `/condensar` reciben datos que **han viajado a Telegram y vuelven** (el nombre
del fichero, el formato elegido). Ninguno se usa tal cual: se validan contra el catálogo
real antes de tocar nada — concatenar el nombre en una ruta aceptaría `../../.env`.

Las respuestas largas se parten automáticamente en varios mensajes, porque Telegram corta
a 4096 caracteres y si te pasas no llega nada.

**Sobre la voz:** transcribir tu audio lo hace Whisper **en Groq**, así que ese audio sale
de tu máquina — y **la voz es un dato biométrico**, no solo lo que dices. Por eso el
interruptor arranca apagado y el aviso está **en el propio menú `/voz`**: encenderlo
teniéndolo delante *es* el consentimiento. Con el interruptor apagado, el audio **ni se
descarga**. Hablar, en cambio, es local (Piper): no sale nada.

**Sobre privacidad:** los mensajes que envías a un bot de Telegram **no van cifrados de
extremo a extremo** — pasan por los servidores de Telegram. Es una consecuencia de usar
ese canal, no del código, pero conviene saberlo: matiza el requisito RNF-06 del proyecto
(ver [E1 §4.1](docs/E1_Especificacion_Requisitos.md)).

## Corriendo 24/7 en una VPS

Desde el **21/08/2026** el bot no depende de que haya un ordenador encendido: vive en una
VPS (Hetzner CX23 · 2 vCPU · 4 GB · Ubuntu 26.04 · Núremberg · 7,25 €/mes sin permanencia)
como servicio de systemd — [`scripts/jimmy.service`](scripts/jimmy.service), que lleva
dentro el porqué de cada línea.

**Sin Docker, y no por pereza.** Cada bot corre con **su propio usuario de Linux**, su
carpeta a `700` y su tope de memoria. Eso es lo que impide que un bot lea el `.env` de
otro cuando convivan varios en la misma máquina: un venv aísla librerías de Python, **no
la máquina**.

**El tope de memoria no es cosmético.** Sin él, cuando el sistema se queda sin RAM el
kernel no mata al culpable — mata al proceso que más ocupa, que puede ser el bot de al
lado. Con `MemoryMax` cada uno responde de lo suyo.

**Lo que se midió** (con PSS, no a ojo — nadie lo había medido antes):

| | RAM |
|---|---|
| Sin límite, con el RAG **vacío** | 2.515 MB |
| Con `MemoryHigh=1000M` / `MemoryMax=1200M`, usándolo de verdad | **1.000 MB** de pico + 92 MB de swap |
| En reposo, esperando mensajes | 172 MB |

El 60 % de esos 2,5 GB era `onnxruntime` reservando de más «por si acaso»: con un techo
puesto se aprieta y funciona igual, sin un solo OOM y arrancando solo tras reiniciar.

**Lo que hay que saber si lo repites:** Ubuntu 26.04 trae **Python 3.14** y este proyecto
necesita **3.13** (el lockfile está clavado a ruedas `cp313`); el 3.13 se instala **al
lado** con `uv`, sin tocar el del sistema. El `.env` del servidor lleva una
`CONVERSATIONS_KEY` **nueva**, generada allí: la del portátil nunca sale de casa. Y el
cortafuegos solo abre el **puerto 22**, porque el bot habla por *polling* y no necesita
que nadie entre.

**Copia de seguridad:** [`scripts/backup-vps.ps1`](scripts/backup-vps.ps1) se trae las
conversaciones al portátil. Copia **solo `conversations/`**, que es el único dato
irreemplazable: `chroma_db/` es un índice derivado que el bot reconstruye solo al arrancar,
y `conversations.db` guarda metadatos que ya viven en los `.json`. La `CONVERSATIONS_KEY`
**no viaja con la copia** — va una vez a un gestor de contraseñas, porque guardarla al lado
de los datos que cifra repetiría el problema que ya tiene el servidor. Sin ella, la copia
es basura cifrada para siempre: Fernet no tiene recuperación.

**Aviso cuando se cae:** [`scripts/avisar-telegram.sh`](scripts/avisar-telegram.sh) manda
un mensaje con las últimas líneas del log cuando el servicio falla (`OnFailure=`), y
[`scripts/vigilar-bots.timer`](scripts/vigilar-bots.timer) vuelve a comprobarlo cada día
por si el primer aviso se perdió. El aviso lo manda `curl` contra la API de Telegram,
**no el bot** — por eso puede avisar de que el bot está muerto. Lleva un **limitador de un
aviso cada 15 minutos** por unidad, y no es comodidad: probándolo en real se vio que
`OnFailure=` salta en **cada intento fallido**, no una sola vez, así que sin limitador
llegan cinco mensajes seguidos por incidente — y un aviso que satura se acaba silenciando.
**Lo que NO detecta**, y conviene saberlo: un bot vivo pero inútil (cuota agotada, token
caducado, disco lleno) sigue apareciendo como `active (running)` y no dispara nada. Para
eso haría falta un chequeo de salud del propio bot, que es otra cosa.

**Los límites siguen siendo los mismos** que declara [E4 §6](docs/E4_Entrega_Final.md):
un solo `user_id`, sin cifrado E2E en Telegram, y la clave de cifrado conviviendo con los
datos que cifra — con el matiz de que ahora esa clave vive en una máquina alquilada, así
que protege del descuido, **no de quien administra el hierro**.

## Documentación

| Documento | Qué contiene |
|---|---|
| [docs/diario_decisiones.md](docs/diario_decisiones.md) | ⭐ Tabla oficial de decisiones técnicas con fecha |
| [docs/E1_Especificacion_Requisitos.md](docs/E1_Especificacion_Requisitos.md) | Requisitos (RF/RNF), catálogo de herramientas, riesgos y trazabilidad |
| [docs/E2_Arquitectura.md](docs/E2_Arquitectura.md) | Arquitectura, componentes y **diagramas** de flujo, seguridad y datos |
| [docs/E3_Estado_Arte_Planificacion.md](docs/E3_Estado_Arte_Planificacion.md) | Estado del arte, comparativas, OWASP LLM y plan de fases |
| [docs/E4_Entrega_Final.md](docs/E4_Entrega_Final.md) | Entrega final: cifras, tests, cómo ejecutar, límites y reflexión |
| [docs/ADR/](docs/ADR/) | Las 6 decisiones de arquitectura (ADR-001 … ADR-006) |
| [docs/normas/](docs/normas/) | **Kit de normas ISO**: el proyecto evaluado contra 29148, 12207, 25010, 29119, 27001 y 42001, en formato de auditoría |
| [SECURITY.md](SECURITY.md) | Cómo reportar un fallo, alcance, y las CVE aceptadas con su motivo |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Las normas de abajo, ampliadas, y el procedimiento ante una CVE |

El kit de normas es **una autoevaluación, no una certificación**, y lo dice él mismo en la
primera línea. Su parte útil no son los doce documentos: es
[`scripts/trazabilidad.py`](scripts/trazabilidad.py), que se pone **rojo** si un test apunta a un
requisito que no existe, si un requisito crítico pierde su verificación, o si un conteo declarado
en la documentación deja de cuadrar con la realidad. Se ejecuta en cada CI:

```bash
python scripts/trazabilidad.py --check
```

Las **no conformidades abiertas** están publicadas, no escondidas:
[docs/normas/09_no_conformidades.md](docs/normas/09_no_conformidades.md).

## Normas del proyecto

1. **Ninguna decisión sin fila fechada** en el diario de decisiones.
2. **Toda utilidad sin IA tiene tests** (norma activa desde el Nivel Intermedio).
3. **Toda excepción queda registrada** en `logs/`.
4. Los secretos viven en `.env` (gitignored); el repo solo contiene `.env.example`.

Y dos doctrinas de verificación, que son lo que de verdad distingue a este proyecto:

> **Un control sin test es una promesa** ([E2 §1](docs/E2_Arquitectura.md)).
> **Un test que nunca has visto fallar no demuestra nada** — por eso los controles críticos se
> rompen a propósito y se comprueba que un test se pone rojo
> (`RNF-08`, [E3 §6.1](docs/E3_Estado_Arte_Planificacion.md)).

Ampliadas en [CONTRIBUTING.md](CONTRIBUTING.md).

## Git

Ramas `feature/*` → `main`, con un tag por nivel completado:
`nivel-basico` · `nivel-intermedio` · `nivel-avanzado` · `nivel-experto`.
