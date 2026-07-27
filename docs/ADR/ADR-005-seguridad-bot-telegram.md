# ADR-005 — Controles de seguridad del bot de Telegram

**Estado:** ✅ Decisión (27/07/2026)
**Fecha:** 27/07/2026 · **Decisor:** Jordi · **Contexto:** Fase 5.2 (bot de Telegram)

## Contexto

Hasta ahora el agente se usaba desde la terminal de Jordi: el "control de acceso" era
tener acceso físico al ordenador. Exponerlo por Telegram cambia el modelo de amenaza
por completo — **cualquiera que descubra el @usuario del bot puede escribirle**, y los
nombres de bot son fáciles de encontrar o adivinar.

Lo que está en juego no es solo la cuota del LLM. Desde F5.3 el agente tiene la
herramienta `buscar_en_recuerdos`, que consulta la memoria semántica y **descifra**
conversaciones anteriores para responder. Un bot sin control de acceso le entregaría a
un desconocido las conversaciones privadas de Jordi con solo preguntar — la misma fuga
que se cerró en los logs el 27/07 (ver E1 §4.1), pero por la puerta principal y a
petición del atacante.

A esto se suma que `Agente.preguntar()` es **síncrono y lento** (hasta 3 proveedores ×
reintentos con backoff × 5 vueltas del bucle de herramientas), mientras que
`python-telegram-bot` es **asíncrono**: llamarlo mal congela el bot entero.

## Alternativas consideradas

### Control de acceso

- **`filters.User(user_id=[...])` en cada handler.** Es la forma más citada en tutoriales.
  Funciona, pero tiene un **modo de fallo abierto**: el día que se añada un handler nuevo
  —y F5.5 trae ~20 herramientas— y alguien olvide el filtro, ese handler queda accesible
  para cualquiera. El fallo es **silencioso**: el bot funciona perfectamente, solo que
  también para desconocidos.
- **`TypeHandler` en el grupo −1 que lanza `ApplicationHandlerStop`** (elegido). Corre
  antes que cualquier handler del grupo 0+, y `ApplicationHandlerStop` corta la ejecución
  *"even in different groups"* (verificado en la docstring de PTB 22.8 instalado). Un
  handler nuevo queda protegido **automáticamente**, sin que nadie tenga que acordarse.
- **Sin control de acceso, confiando en que nadie encuentre el bot.** Seguridad por
  oscuridad; descartado sin discusión.

### Puente entre el mundo síncrono y el asíncrono

- **Llamar a `Agente.preguntar()` directamente** desde el handler `async`: congelaría el
  bucle de eventos durante decenas de segundos. El bot dejaría de responder a todo,
  **incluida la propia puerta de la allowlist** para los demás mensajes.
- **Reescribir el núcleo en async** (`AsyncGroq`, cliente async de Ollama, `client.aio`
  de Gemini, rehacer el router): semanas de trabajo, duplicar las tres integraciones y
  romper la CLI, para un bot de un solo usuario.
- **`asyncio.to_thread`** (elegido): una línea, biblioteca estándar, **cero cambios en
  `Agente`**. Cumple literalmente lo que su docstring prometía desde F4.5: *"cuando las
  preguntas lleguen por Telegram, esta clase se reutiliza tal cual"*.

### Limitación de peticiones

- **`AIORateLimiter`, que ya trae PTB.** Verificado en su documentación: limita las
  peticiones **salientes** al Bot API (que Telegram no nos corte por flood), **no** los
  mensajes entrantes. Es decir, **no protege ni un gramo de la cuota del LLM**, que es
  justo lo que hay que proteger. Se descarta con este motivo escrito para que nadie
  concluya más adelante que "ya tenemos rate limiting".
- **Ventana deslizante propia de entrada, por usuario** (elegido), en una segunda puerta
  del grupo −1 registrada *después* de la allowlist.

## Decisión

| # | Control | Qué cierra |
|---|---|---|
| 1 | **Lista blanca de `user_id`** en `TypeHandler` (grupo −1) + `ApplicationHandlerStop` | Acceso de desconocidos a la memoria privada y a la cuota |
| 2 | **Fallar cerrado** en todos los casos raros: sin variable, lista ilegible, o `effective_user = None` (pasa en `channel_post`, `poll`, `chat_boost`) | Que un error de configuración se convierta en una puerta abierta |
| 3 | **Silencio ante un no autorizado** (no se responde "no puedes usarme") | Confirmar a quien sondea que el bot existe; gastar cuota a petición suya |
| 4 | **Un `Agente` por `user_id`** + `asyncio.Lock` por usuario | Que la conversación de un usuario viaje dentro del contexto de otro |
| 5 | **`asyncio.to_thread`** para la llamada bloqueante | Congelar el bot, incluida la puerta de acceso |
| 6 | **Rate limit de entrada** (20 mensajes / 60 s, `time.monotonic()`) | Agotar el free tier del LLM con una ráfaga |
| 7 | **Límite de entrada (2000 caracteres)** y rechazo de lo que no sea texto | Crecimiento descontrolado del contexto (AUD-03); adjuntos que el bot no sabe tratar |
| 8 | **Troceo de la salida a 4096** (`MessageLimit.MAX_TEXT_LENGTH`) | Que el usuario **no reciba nada** cuando la respuesta es larga |
| 9 | **Ni el `user_id`, ni el nombre, ni el texto en los logs**; huella con sal solo para rechazos | Convertir el log en un fichero de datos personales |
| 10 | **Polling, no webhook** | Tres superficies nuevas (URL pública, TLS, endpoint expuesto) contra el requisito rector |

**Notas de implementación que son parte de la decisión, no detalles:**

- Las puertas **deben ser bloqueantes**. `ApplicationHandlerStop` *"has no effect, if the
  handler is run in a non-blocking way"* (documentación oficial, verificada en el paquete
  instalado): un `block=False` puesto "para que vaya más rápido" **desactivaría en
  silencio todo el control de acceso**. Hay un test que lo impide.
- **No se llama a `concurrent_updates(True)`**, con el motivo escrito en un comentario:
  sin él, PTB procesa los mensajes de uno en uno y las carreras sobre el historial no
  pueden darse. Los cerrojos están igualmente, por si algún día se activa.
- `construir_aplicacion()` está **separada de `run_polling()`**: sin esa separación no
  hay forma de probar la seguridad sin red ni token real. Es el mismo movimiento que hizo
  `Agente` al no saber nada de la terminal.

## Consecuencias

**A favor**

- El control de acceso **sobrevive al crecimiento de F5.5**: las ~20 herramientas nuevas
  quedan protegidas sin trabajo adicional.
- `Agente`, `LLMRouter` y las herramientas se reutilizan **sin una sola modificación**,
  validando la decisión de desacople de F4.5 y ADR-003.
- Los 10 controles tienen tests que corren **sin red, sin token y sin gastar cuota**; los
  cuatro críticos se validaron además con **pruebas de mutación** (se rompió el control a
  propósito y se comprobó que los tests se ponen rojos).

**En contra / limitaciones asumidas**

- **La memoria semántica es global.** El índice RAG no distingue de quién es cada
  recuerdo, así que con más de un `user_id` autorizado un usuario podría recuperar
  recuerdos de otro aunque cada uno tenga su propio `Agente`. Mitigación actual:
  recomendar **un solo usuario** y avisar por log si hay más. Particionar el índice queda
  en backlog.
- **`asyncio.to_thread` no se puede cancelar**: si el bot se apaga, el hilo termina la
  llamada igual. Acotado por el timeout de 30 s de F5.0/T3.
- **El historial sigue sin tope** (la otra mitad de AUD-03). Mitigación barata: `/limpiar`
  y `/resumen`, que `Agente` ya tiene. La compactación automática queda en backlog.
- El rate limit es **en memoria**: se reinicia si el bot se reinicia. Suficiente para un
  bot personal; un atacante tendría que provocar el reinicio para saltárselo.

## Verificación

24 tests en `tests/test_telegram_seguridad.py`, ninguno toca la red. Los cuatro controles
críticos, verificados por mutación (se rompe el control → el test debe ponerse rojo):

| Mutación aplicada | Test que la detecta |
|---|---|
| La puerta pasa al grupo 0 | `test_la_puerta_corre_antes_que_cualquier_otro_handler` |
| `block=False` en la puerta | `test_ningun_handler_de_las_puertas_es_no_bloqueante` |
| Lista ilegible → permitir a todos | `test_una_lista_blanca_rota_cierra_el_bot_no_lo_abre` (+4 más) |
| Se loguea el `user_id` en claro | `test_la_huella_de_un_rechazo_no_lleva_el_user_id_en_claro` |

Pendiente: prueba real contra Telegram con un bot de verdad, y **decisión de hosting 24/7**
(sigue abierta, ver E1 §7).
