# Bot de Telegram (F5.2) - capa de entrada/salida, NADA de logica de agente.
#
# Igual que main.py es la capa de terminal, este fichero es la capa de
# Telegram: recibe mensajes, aplica los controles de seguridad y le pasa el
# texto a un Agente (src/agent.py) que no sabe ni le importa de donde viene.
#
# ORDEN DE LOS CONTROLES (importa, y mucho):
#   update -> [puerta 1: allowlist] -> [puerta 2: rate limit] -> handler -> LLM
# La allowlist va PRIMERO para que un desconocido no llegue siquiera a crear
# entrada en el estado del limitador.
#
# PRIVACIDAD (RNF-06): este fichero no loguea NUNCA el texto de un mensaje,
# ni el nombre real del usuario, ni el user_id en claro. Ver _huella() y la
# lista negra del final del fichero.
import asyncio
import hashlib
import logging
import time
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, MessageLimit
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

from src.agent import Agente
from src.config import (
    MODELOS,
    ClaveApiNoConfigurada,
    ConfiguracionTelegramInvalida,
    obtener_api_key,
    obtener_modelo_por_defecto,
    obtener_sal_log,
    obtener_token_telegram,
    obtener_usuarios_permitidos,
)
from src.main import SYSTEM_PROMPT

# F5.2+ (memoria compartida): el bot escribe en el MISMO almacen que la CLI.
# indexar_conversacion se importa aqui arriba (no perezoso) a proposito: si
# faltara chromadb, mejor enterarse al arrancar el bot que a mitad del
# primer turno.
from src.rag import indexar_conversacion, indexar_conversaciones, olvidar_conversacion
from src.storage import (
    ConversacionNoDescifrable,
    borrar_conversacion,
    guardar_conversacion,
    leer_metadatos,
    listar_conversaciones,
)

# --- Limites ---------------------------------------------------------------

# Tope del mensaje de ENTRADA. Telegram ya corta el mensaje suelto en 4096,
# pero eso no cierra AUD-03: el problema real es que self.historial se
# reenvia ENTERO en cada turno, asi que 4096 x N turnos se dispara en coste,
# latencia y riesgo de agotar el contexto. 2000 es holgado para conversar.
_LIMITE_ENTRADA = 2000

# Tope de SALIDA de Telegram (verificado en telegram.constants: 4096). Si se
# supera, send_message lanza BadRequest y el usuario NO RECIBE NADA - justo
# cuando la respuesta era mas larga y probablemente mas valiosa.
_LIMITE_TELEGRAM = MessageLimit.MAX_TEXT_LENGTH

# Tope de trozos: un modelo desbocado no debe generar una avalancha de 40
# mensajes seguidos en el movil de nadie.
_MAX_TROZOS = 5

# Rate limit de ENTRADA por usuario (ventana deslizante).
_LIMITE_MENSAJES = 20
_VENTANA_SEGUNDOS = 60.0

# Cuantas conversaciones enseña /historial. Telegram corta en 4096
# caracteres, y una lista de 200 charlas no la lee nadie: se muestran las
# mas recientes, que son las que se buscan.
_MAX_HISTORIAL = 15

# Tope del nombre de /guardar. Va a los metadatos EN CLARO del JSON, asi
# que ademas de caber en la lista conviene que no sea un texto libre largo.
_MAX_NOMBRE = 60

# Cuantos recuerdos enseña /recuerdo. Mas que los 3 que usa la tool por
# dentro: aqui los lee una persona, que sabe descartar los que no valen.
_RECUERDOS_MOSTRADOS = 5


# --- Estado en memoria -----------------------------------------------------
# Los tres diccionarios estan ACOTADOS por la allowlist: solo pueden crecer
# hasta el numero de usuarios autorizados, que en este proyecto es 1.

_agentes: dict[int, Agente] = {}
_cerrojos: dict[int, asyncio.Lock] = {}
_marcas: dict[int, list[float]] = {}

# F5.2+ (memoria compartida CLI <-> Telegram): fichero donde se va guardando
# la conversacion EN CURSO de cada usuario. Se reescribe el mismo despues de
# cada turno, no uno nuevo por mensaje - ver storage.guardar_conversacion.
# Se borra la entrada en /limpiar: la charla siguiente estrena fichero.
_rutas: dict[int, Path] = {}

# Etiqueta puesta con /guardar, por usuario. Se conserva entre turnos para
# que el guardado automatico no la pise con "Telegram" al reescribir.
_nombres: dict[int, str] = {}


# --- Helpers puros (testeables sin red, sin Telegram y sin LLM) ------------


def _huella(user_id: int | None) -> str:
    """Identificador corto y NO reversible para el log de rechazos.

    El user_id de Telegram es un dato personal (identifica a una persona
    fisica de forma estable, y en chat privado el chat_id ES el user_id,
    asi que renombrarlo no lo esquiva). Pero ante trafico rechazado si
    hace falta poder auditar: la huella distingue "el mismo desconocido 40
    veces" de "40 desconocidos distintos" -toda la informacion operativa
    que necesitamos- sin guardar a quien.

    La sal es imprescindible, no decorativa: el espacio de user_id es
    enumerable, asi que un hash sin sal se revierte por fuerza bruta en
    segundos. Ver config.obtener_sal_log.
    """
    if user_id is None:
        return "sin-usuario"
    return hashlib.blake2s(
        str(user_id).encode("utf-8"), key=obtener_sal_log(), digest_size=4
    ).hexdigest()


def _trocear(texto: str, limite: int = _LIMITE_TELEGRAM) -> list[str]:
    """Parte una respuesta larga en trozos que Telegram acepte.

    Corta por salto de linea y, si no hay, por espacio, para no partir
    palabras ni bloques de codigo por la mitad. Si no hay ningun sitio
    "limpio" donde cortar (un base64, un hash), corta igual: mas vale un
    corte feo que un mensaje que Telegram rechaza entero.
    """
    if len(texto) <= limite:
        return [texto]

    trozos: list[str] = []
    resto = texto
    while resto and len(trozos) < _MAX_TROZOS:
        if len(resto) <= limite:
            trozos.append(resto)
            break
        # Busca el ultimo corte limpio DENTRO del limite.
        corte = resto.rfind("\n", 0, limite)
        if corte <= 0:
            corte = resto.rfind(" ", 0, limite)
        if corte <= 0:
            corte = limite  # sin sitio limpio: corte duro
        trozos.append(resto[:corte])
        resto = resto[corte:].lstrip("\n")
    return trozos


def _configuracion_por_defecto() -> tuple[str, str, str]:
    """Proveedor/modelo/clave con los que arranca el bot. El router
    (ADR-004) se encarga solo de degradar a los fallbacks si este falla."""
    proveedor = "groq"
    modelo = obtener_modelo_por_defecto(proveedor)
    return proveedor, modelo, obtener_api_key(proveedor)


def _agente_de(user_id: int) -> Agente:
    """Un Agente POR USUARIO, no uno compartido.

    La razon de fondo NO es la concurrencia sino la PRIVACIDAD: dos
    usuarios que compartieran el mismo Agente compartirian su
    self.historial, asi que en cada turno la conversacion entera de uno
    viajaria dentro del contexto del otro - y /limpiar, /resumen o guardar
    operarian sobre la conversacion ajena.

    El diccionario esta acotado por la allowlist, asi que no puede crecer
    sin limite.
    """
    if user_id not in _agentes:
        proveedor, modelo, api_key = _configuracion_por_defecto()
        _agentes[user_id] = Agente(SYSTEM_PROMPT, proveedor, api_key, modelo)
    return _agentes[user_id]


def _persistir(user_id: int, nombre: str | None = None) -> Path | None:
    """Guarda el turno recien terminado y lo mete en la memoria semantica.

    ESTO es lo que hace que el bot y la CLI compartan memoria (F5.2+). Antes
    el bot no llamaba nunca a guardar(): lo hablado por Telegram vivia solo
    en RAM, se perdia al parar el proceso y NO alimentaba el RAG, asi que
    buscar_en_recuerdos solo encontraba lo escrito desde la terminal. Ahora
    las dos entradas escriben en el mismo sitio (conversations/ cifrado +
    indice de ChromaDB) y cualquiera de las dos recuerda lo de la otra.

    Se llama DESPUES de responder al usuario, no antes: guardar es
    importante, pero no tanto como contestar. Y por eso mismo no lanza -
    un fallo al guardar se registra y se sigue; el usuario ya tiene su
    respuesta y perder el guardado de un turno no justifica romperle la
    conversacion.

    "nombre" es la etiqueta opcional de /guardar. Si no se pasa, se conserva
    la que ya tuviera la conversacion (para no borrarla en cada turno) y, si
    no tenia ninguna, se marca "Telegram" - asi /historial deja ver de un
    vistazo que salio del bot y no de la terminal.

    Devuelve la ruta del fichero, o None si no habia nada que guardar.

    OJO: es SINCRONA y bloqueante (cifra, escribe disco, incrusta el texto
    en un vector). Quien la llame debe hacerlo con asyncio.to_thread, igual
    que con Agente.preguntar - si no, congela el bucle de eventos del bot.
    """
    agente = _agentes.get(user_id)
    if agente is None:
        return None
    try:
        ruta = guardar_conversacion(
            agente.historial, agente.proveedor, agente.modelo,
            nombre=nombre or _nombres.get(user_id) or "Telegram",
            ruta=_rutas.get(user_id),
        )
        if ruta is None:
            return None  # historial vacio (solo el system prompt): nada que guardar
        _rutas[user_id] = ruta
        if nombre:
            # Se recuerda para que los turnos SIGUIENTES no lo pisen con
            # "Telegram" al reescribir el mismo fichero.
            _nombres[user_id] = nombre
        indexar_conversacion(ruta)
        return ruta
    except Exception as error:
        # Tipo, no texto (politica de logging del proyecto): el str() de un
        # error de cifrado o de ChromaDB puede arrastrar contenido.
        logging.error("Telegram: no se pudo persistir el turno (%s)", type(error).__name__)
        return None


def _cerrojo_de(user_id: int) -> asyncio.Lock:
    """Un cerrojo por usuario: serializa sus turnos aunque algun dia se
    active la concurrencia de PTB. Sin el, dos mensajes seguidos podrian
    intercalar sus append() sobre el mismo self.historial y cruzar
    pregunta y respuesta."""
    if user_id not in _cerrojos:
        _cerrojos[user_id] = asyncio.Lock()
    return _cerrojos[user_id]


# --- Puerta 1: control de acceso (AUD-A1, el control nº1 del bot) ----------


async def puerta_allowlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """PRIMERA comprobacion de todo el bot. Va en un TypeHandler del grupo
    -1, asi que corre ANTES que cualquier handler del grupo 0+, y
    ApplicationHandlerStop corta la ejecucion en TODOS los grupos
    (verificado en la docstring del propio PTB 22.8).

    POR QUE ASI Y NO filters.User(...) EN CADA HANDLER: con filtros por
    handler, el dia que se añada un handler nuevo (F5.5 trae ~20 tools) y
    alguien olvide el filtro, ese handler queda ABIERTO a cualquiera y el
    fallo es SILENCIOSO - el bot funciona perfectamente, solo que tambien
    para desconocidos. Aqui la proteccion es automatica: el control que
    sobrevive es el que no hay que acordarse de aplicar.

    NO PONER block=False EN ESTE HANDLER: ApplicationHandlerStop "has no
    effect, if the handler is run in a non-blocking way" (doc oficial,
    verificada en el paquete instalado). Un block=False puesto "para que
    vaya mas rapido" desactivaria EN SILENCIO todo el control de acceso.
    """
    try:
        usuario = update.effective_user

        try:
            permitidos = obtener_usuarios_permitidos()
        except ConfiguracionTelegramInvalida:
            # Fallar CERRADO: si la lista blanca no se puede leer (alguien
            # rompio el .env en caliente), se rechaza todo. Lo contrario
            # -seguir sirviendo- convertiria un error de configuracion en
            # una puerta abierta.
            logging.error("Telegram: lista blanca ilegible, se rechaza el update")
            raise ApplicationHandlerStop from None

        # effective_user puede ser None de verdad (channel_post, poll,
        # chat_boost... - documentado en PTB). Se comprueba ANTES de tocar
        # .id: sin usuario identificable no hay a quien autorizar, asi que
        # fuera. Escrito en este orden a proposito, no al reves.
        if usuario is None or usuario.id not in permitidos:
            # Silencio deliberado: NO se responde "no puedes usarme".
            # Contestar confirmaria a quien sondea que el bot existe y esta
            # vivo, y gastaria cuota de salida a peticion de un desconocido.
            logging.warning(
                "Telegram: update rechazado (huella=%s)",
                _huella(usuario.id if usuario else None),
            )
            raise ApplicationHandlerStop

    except ApplicationHandlerStop:
        raise  # el rechazo normal: pasa tal cual

    except Exception as error:
        # RED DE SEGURIDAD (auditoria del 27/07, hallazgo critico).
        #
        # Sin este except, CUALQUIER excepcion inesperada aqui dentro
        # dejaba pasar al desconocido. El motivo esta en el propio PTB:
        # process_update() captura las excepciones de un handler y llama a
        # process_error(); si el error handler no lanza
        # ApplicationHandlerStop, process_error devuelve False y el bucle
        # NO hace break -> el update continua al grupo 0 y lo atiende
        # manejar_mensaje. O sea: una excepcion aqui = puerta abierta.
        #
        # Se encontro con un caso REAL: _huella() usa blake2s, que acepta
        # claves de 32 bytes como maximo; una TELEGRAM_LOG_SAL mas larga
        # (una frase normal, o un token_hex(32)) hacia saltar un
        # ValueError justo ANTES del ApplicationHandlerStop de rechazo.
        # Y solo fallaba para los NO autorizados, asi que probando con la
        # cuenta propia todo parecia correcto.
        #
        # La causa concreta ya esta arreglada en config.obtener_sal_log(),
        # pero eso arregla UN camino; esto cierra la CLASE entera. El
        # control de acceso no puede depender de que ninguna linea futura
        # lance nunca nada.
        logging.error(
            "Telegram: fallo inesperado en el control de acceso (%s); se rechaza",
            type(error).__name__,
        )
        raise ApplicationHandlerStop from None


# --- Puerta 2: rate limit de entrada ---------------------------------------


async def puerta_rate_limit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ventana deslizante por usuario, ANTES de llegar al LLM.

    El AIORateLimiter que trae PTB NO sirve para esto: limita las
    peticiones SALIENTES al Bot API (que Telegram no nos tire por flood),
    no los updates ENTRANTES - o sea, no protege ni un gramo de la cuota
    del LLM, que es justo lo que queremos proteger. Confundir las dos
    cosas seria el error clasico aqui.

    Riesgo concreto que cierra: el free tier de Groq son ~30 peticiones por
    minuto y un turno con tools puede gastar varias. Un dedo pegado al
    boton de enviar agota la cuota y deja el bot inutil.

    time.monotonic() y no time.time(): un cambio de hora del sistema (o el
    horario de verano) no debe abrir ni cerrar esta puerta.
    """
    usuario = update.effective_user
    if usuario is None:  # ya lo corto la puerta 1; defensa en profundidad
        raise ApplicationHandlerStop

    ahora = time.monotonic()
    marcas = [t for t in _marcas.get(usuario.id, []) if ahora - t < _VENTANA_SEGUNDOS]

    if len(marcas) >= _LIMITE_MENSAJES:
        _marcas[usuario.id] = marcas
        logging.warning("Telegram: rate limit alcanzado")
        if update.effective_message:
            await update.effective_message.reply_text(
                "Vas muy rápido y puedo quedarme sin cuota. Dame un momento."
            )
        raise ApplicationHandlerStop

    marcas.append(ahora)
    _marcas[usuario.id] = marcas


# --- Handlers --------------------------------------------------------------


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Un turno completo: texto -> Agente -> respuesta troceada."""
    mensaje = update.effective_message
    usuario = update.effective_user
    if mensaje is None or usuario is None or not mensaje.text:
        return

    texto = mensaje.text.strip()

    # Limite de entrada (AUD-03, la mitad que se aplazo a F5.2). Se
    # comprueba ANTES de llamar al LLM: un mensaje gigante no debe llegar
    # siquiera a consumir cuota.
    if len(texto) > _LIMITE_ENTRADA:
        await mensaje.reply_text(
            f"Ese mensaje es muy largo ({len(texto)} caracteres). "
            f"Resúmelo en menos de {_LIMITE_ENTRADA} y te contesto."
        )
        return

    async with _cerrojo_de(usuario.id):
        await context.bot.send_chat_action(mensaje.chat_id, ChatAction.TYPING)
        try:
            # _agente_de() DENTRO del try (auditoria 27/07): al crear el
            # primer Agente de un usuario lee la API key, y si falta lanza
            # ClaveApiNoConfigurada. Estando fuera, esa excepcion subia al
            # error handler y el usuario NO recibia ni el aviso generico -
            # silencio total y permanente, porque el Agente nunca llegaba
            # a cachearse y el fallo se repetia en cada mensaje.
            agente = _agente_de(usuario.id)
            # asyncio.to_thread: Agente.preguntar() es SINCRONO y puede
            # tardar decenas de segundos (3 proveedores x reintentos con
            # backoff x hasta 5 vueltas del bucle de tools). Llamarlo
            # directo aqui congelaria el bucle de eventos: el bot dejaria
            # de responder a todo, incluida la propia puerta de la
            # allowlist para los demas updates.
            #
            # Nota asumida: to_thread no se puede cancelar. Si el bot se
            # apaga, el hilo termina la llamada igual. Acotado por el
            # timeout de 30s de F5.0/T3.
            respuesta = await asyncio.to_thread(agente.preguntar, texto)
        except Exception as error:
            # Agente.preguntar() solo captura ErrorLLM; cualquier otro
            # fallo (ChromaDB, un AttributeError nuestro, un KeyError de
            # un SDK) llega hasta aqui. Al log, el TIPO -politica de
            # logging del proyecto-. Al chat, un texto fijo NUESTRO: ni
            # str(error), ni traceback, ni rutas de fichero.
            logging.error(
                "Telegram: fallo no controlado al responder (%s)", type(error).__name__
            )
            respuesta = "⚠️ Se me ha cruzado un cable. Vuelve a intentarlo en un momento."
        else:
            # Solo se persiste si el turno fue bien: un historial que acaba
            # en un fallo no debe entrar en la memoria a largo plazo como si
            # fuera una conversacion real (mismo criterio que Agente.preguntar,
            # que no mete en el historial las respuestas de error).
            #
            # to_thread por lo mismo que preguntar(): cifrar, escribir en
            # disco e incrustar el texto en un vector son operaciones
            # bloqueantes, y aqui congelarian el bot entero.
            #
            # Dentro del cerrojo del usuario: si no, un mensaje siguiente
            # podria estar modificando self.historial mientras este se
            # serializa a JSON.
            await asyncio.to_thread(_persistir, usuario.id)

    for trozo in _trocear(respuesta):
        await mensaje.reply_text(trozo)


async def manejar_no_texto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fotos, notas de voz, documentos... Sin esto, un adjunto de 20 MB
    llega a un bot que no sabe que hacer con el y acaba en el error
    handler. Transcripcion y OCR estan en el tier "si sobra tiempo" de
    F5.5, no aqui."""
    if update.effective_message:
        await update.effective_message.reply_text(
            "De momento solo entiendo texto."
        )


# --- Comandos --------------------------------------------------------------
# Sin estos, un "/loquesea" no encajaba en NINGUN handler y se perdia en
# silencio (hallazgo de la auditoria del 27/07). Ademas de la mala
# experiencia -"/start" es lo primero que escribe cualquiera-, dejaba al
# usuario de Telegram sin forma de vaciar el historial, que crece sin tope
# y se reenvia entero en cada turno.


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(
            "Hola JIM. Soy tu agente. Escríbeme lo que quieras, o /ayuda para ver qué sé hacer."
        )


async def cmd_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(
            "/recuerdo <algo> — buscar en mi memoria y enseñarte lo que hay\n"
            "/historial — ver tus conversaciones guardadas\n"
            "/borrar — borrar una conversación guardada, del disco y de mi memoria\n"
            "/guardar <nombre> — ponerle nombre a esta charla\n"
            "/salir — cerrar la charla: guardarla o descartarla\n"
            "/limpiar — empezar de cero (la guarda y olvida el contexto)\n"
            "/resumen — resumir lo hablado hasta ahora\n"
            "/modelo — cambiar el modelo (mismo proveedor)\n"
            "/proveedor — cambiar de proveedor (y modelo)\n"
            "/ayuda — esto\n\n"
            "Voy guardando solo según hablamos, así que no se pierde nada aunque "
            "me apaguen. Si una charla no merece la pena, ciérrala con /salir y "
            "elige «descartar».\n"
            "Para todo lo demás, escríbeme normal."
        )


async def cmd_limpiar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Vacia el historial del usuario. No es solo comodidad: el historial
    se reenvia ENTERO en cada turno, asi que sin esto crece sin freno en
    coste, latencia y contexto (mitad pendiente de AUD-03)."""
    usuario = update.effective_user
    if usuario is None or update.effective_message is None:
        return
    async with _cerrojo_de(usuario.id):
        _agentes.pop(usuario.id, None)
        # F5.2+: se suelta tambien el fichero de la charla. Lo ya guardado NO
        # se borra (sigue en conversations/ y en el RAG, igual que /limpiar en
        # la CLI tampoco borra del disco): lo que se corta es que la
        # conversacion SIGUIENTE se escriba encima de la anterior.
        _rutas.pop(usuario.id, None)
        _nombres.pop(usuario.id, None)
    await update.effective_message.reply_text(
        "Listo, empezamos de cero. Lo de antes sigue en mi memoria a largo plazo."
    )


async def cmd_resumen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    usuario = update.effective_user
    mensaje = update.effective_message
    if usuario is None or mensaje is None:
        return
    async with _cerrojo_de(usuario.id):
        try:
            agente = _agente_de(usuario.id)
            respuesta = await asyncio.to_thread(agente.resumir)
        except Exception as error:
            logging.error("Telegram: fallo al resumir (%s)", type(error).__name__)
            respuesta = "⚠️ No he podido resumir ahora mismo."
    for trozo in _trocear(respuesta):
        await mensaje.reply_text(trozo)


async def cmd_historial(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lista las conversaciones guardadas, como /historial en la CLI.

    Usa leer_metadatos y NO cargar_conversacion: los metadatos (fecha,
    nombre, proveedor) van en claro a proposito, asi que listar NO necesita
    descifrar nada. Ademas de ser mas rapido, evita pasear por memoria el
    contenido de todas las conversaciones solo para enseñar una lista.
    """
    mensaje = update.effective_message
    if mensaje is None:
        return

    try:
        rutas = await asyncio.to_thread(listar_conversaciones)
    except Exception as error:
        logging.error("Telegram: fallo al listar historial (%s)", type(error).__name__)
        await mensaje.reply_text("⚠️ No he podido leer el historial.")
        return

    if not rutas:
        await mensaje.reply_text("Todavía no hay conversaciones guardadas.")
        return

    # Las mas recientes primero y solo las ultimas: en Telegram un mensaje
    # tiene tope de 4096 caracteres y una lista de 200 charlas no se lee.
    lineas = []
    for ruta in reversed(rutas[-_MAX_HISTORIAL:]):
        try:
            meta = await asyncio.to_thread(leer_metadatos, ruta)
        except (OSError, ValueError, ConversacionNoDescifrable):
            continue  # un fichero corrupto no debe tumbar la lista entera
        fecha = (meta.get("fecha") or "")[:16].replace("T", " ")
        nombre = meta.get("nombre") or "(sin nombre)"
        candado = "🔒" if meta.get("cifrado") else ""
        lineas.append(f"{candado} {fecha} — {nombre}")

    total = len(rutas)
    cabecera = f"Tus últimas {len(lineas)} conversaciones (de {total}):"
    await mensaje.reply_text(cabecera + "\n\n" + "\n".join(lineas))


async def cmd_guardar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pone NOMBRE a la conversación en curso (y la guarda ya).

    Ojo a la diferencia con la CLI: por Telegram el guardado es automatico
    despues de cada turno, asi que aqui "guardar" no sirve para no perder
    nada -eso ya esta cubierto- sino para ETIQUETAR la charla y poder
    reconocerla luego en /historial.

    El nombre llega como argumento del propio comando ("/guardar ideas de
    tools"): pedirlo en un segundo mensaje obligaria a llevar una maquina de
    estados por usuario, y el bot no tiene ninguna hoy.
    """
    usuario = update.effective_user
    mensaje = update.effective_message
    if usuario is None or mensaje is None:
        return

    # context.args son las palabras que siguen al comando (PTB las parte).
    nombre = " ".join(context.args).strip() if context.args else ""
    if not nombre:
        await mensaje.reply_text(
            "Escribe el nombre después del comando, por ejemplo:\n"
            "/guardar ideas de herramientas"
        )
        return
    if len(nombre) > _MAX_NOMBRE:
        await mensaje.reply_text(f"El nombre es muy largo (máximo {_MAX_NOMBRE}).")
        return

    async with _cerrojo_de(usuario.id):
        ruta = await asyncio.to_thread(_persistir, usuario.id, nombre)

    if ruta is None:
        await mensaje.reply_text("Todavía no hemos hablado de nada que guardar.")
    else:
        await mensaje.reply_text(f'Guardada como "{nombre}".')


async def cmd_recuerdo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Busca A MANO en la memoria y enseña lo que hay, en crudo.

    Peticion de Jordi (28/07). El agente ya decide solo cuando usar
    buscar_en_recuerdos, pero esa decision la toma EL MODELO y a veces no la
    toma: hoy mismo contesto "no lo tengo guardado" teniendo el dato
    indexado. Este comando salta al modelo entero y enseña lo que hay de
    verdad en la memoria.

    Ademas es la herramienta de diagnostico que hoy faltaba: con esto, el
    bug de "el bot no indexaba al arrancar" se habria visto en 10 segundos
    en vez de deducirlo del log.
    """
    mensaje = update.effective_message
    if mensaje is None:
        return

    consulta = " ".join(context.args).strip() if context.args else ""
    if not consulta:
        await mensaje.reply_text(
            "Dime qué quieres que busque, por ejemplo:\n/recuerdo el chiste del plato"
        )
        return

    try:
        # buscar() es sincrona y bloqueante (calcula el vector de la
        # consulta y descifra los JSON): a un hilo, como todo lo demas.
        from src.rag import buscar

        resultados = await asyncio.to_thread(buscar, consulta, _RECUERDOS_MOSTRADOS)
    except Exception as error:
        logging.error("Telegram: fallo al buscar recuerdos (%s)", type(error).__name__)
        await mensaje.reply_text("⚠️ No he podido consultar la memoria.")
        return

    if not resultados:
        await mensaje.reply_text("No encuentro nada sobre eso en mi memoria.")
        return

    lineas = []
    for recuerdo in resultados:
        fecha = (recuerdo.get("fecha") or "")[:10]
        quien = "tú" if recuerdo["rol"] == "user" else "yo"
        lineas.append(f"[{fecha}] {quien}: {recuerdo['texto']}")

    # Se trocea igual que una respuesta normal: un recuerdo largo puede
    # pasarse del limite de Telegram.
    for trozo in _trocear("Esto es lo que tengo:\n\n" + "\n\n".join(lineas)):
        await mensaje.reply_text(trozo)


# --- /salir: cerrar la charla decidiendo si se queda o se tira -------------
# Peticion de Jordi (28/07): por Telegram se guarda TODO automaticamente -
# hasta un "hola" suelto-, asi que sin una forma de descartar, la memoria se
# llena de ruido y la busqueda semantica empeora (mas paja contra la que
# competir). En la CLI esa decision se toma al salir; aqui no habia salida.
#
# Se mantiene el guardado automatico y se añade el DESCARTE, en vez de
# guardar solo al salir: un bot puede morirse en cualquier momento (se cae
# la red, se reinicia el PC) y no se le pide "cerrar sesion" a un chat.
# Guardar siempre y poder tirar es seguro; guardar solo al final, no.

_DESCARTAR = "salir:descartar"
_CONSERVAR = "salir:conservar"


async def cmd_salir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cierra la conversacion en curso preguntando que hacer con ella."""
    usuario = update.effective_user
    mensaje = update.effective_message
    if usuario is None or mensaje is None:
        return

    if usuario.id not in _rutas:
        await mensaje.reply_text("No hay ninguna conversación abierta que cerrar.")
        return

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("Guardar y cerrar", callback_data=_CONSERVAR)],
        [InlineKeyboardButton("Descartar y cerrar", callback_data=_DESCARTAR)],
    ])
    await mensaje.reply_text("¿Qué hago con esta conversación?", reply_markup=teclado)


def _descartar(user_id: int) -> bool:
    """Borra del disco Y del indice la conversacion en curso.

    Las dos cosas, no una: borrar solo el JSON dejaria los vectores
    huerfanos en ChromaDB (ver rag.olvidar_conversacion), y borrar solo del
    indice dejaria el contenido cifrado en disco. Sincrona y bloqueante:
    llamar con asyncio.to_thread.
    """
    ruta = _rutas.get(user_id)
    if ruta is None:
        return False
    return _borrar_del_todo(ruta)


# --- /borrar: tirar una conversacion CONCRETA del historial ---------------
# Peticion de Jordi (28/07). /salir solo puede descartar la charla EN CURSO;
# esto permite entrar al historial y tirar cualquiera.
#
# SEGURIDAD (lo delicado de este comando): el nombre del fichero viaja a
# Telegram dentro del callback_data y vuelve, o sea que es DATO NO CONFIABLE
# usado para BORRAR FICHEROS - la combinacion mas peligrosa que hay en todo
# el bot. Un "b:../../.env" borraria la configuracion; un "b:../../src/
# main.py", el programa. Por eso NO se construye la ruta concatenando: se
# busca el nombre en la lista REAL de conversaciones (allowlist) y se usa el
# Path que devuelve el propio sistema. Si no esta en esa lista, no se toca
# nada. Validar por lista es lo unico que cierra la clase entera; comprobar
# "que no lleve .." solo cierra los casos que se te ocurran.

_PREFIJO_BORRAR = "b:"
_PREFIJO_BORRAR_OK = "bc:"
# Centinela de "no hagas nada", equivalente al VOLVER/Cancelar que en la CLI
# lleva TODO menu de flechas (convencion de F5.5, ver main.py).
_CANCELAR = "cancelar"


def _conversacion_valida(nombre: str) -> Path | None:
    """Devuelve la ruta REAL si "nombre" es una conversacion guardada.

    Allowlist, no saneado: se compara contra lo que devuelve
    listar_conversaciones() y se usa SU objeto Path. Asi el nombre que llega
    de fuera nunca se convierte en una ruta - solo sirve para BUSCAR en una
    lista que hemos hecho nosotros.
    """
    for ruta in listar_conversaciones():
        if ruta.name == nombre:
            return ruta
    return None


async def cmd_borrar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enseña el historial con un boton por conversacion, para borrarla."""
    mensaje = update.effective_message
    if mensaje is None:
        return

    try:
        rutas = await asyncio.to_thread(listar_conversaciones)
    except Exception as error:
        logging.error("Telegram: fallo al listar para borrar (%s)", type(error).__name__)
        await mensaje.reply_text("⚠️ No he podido leer el historial.")
        return

    if not rutas:
        await mensaje.reply_text("No hay ninguna conversación guardada.")
        return

    botones = []
    for ruta in reversed(rutas[-_MAX_HISTORIAL:]):
        try:
            meta = await asyncio.to_thread(leer_metadatos, ruta)
        except (OSError, ValueError, ConversacionNoDescifrable):
            continue
        fecha = (meta.get("fecha") or "")[:10]
        nombre = meta.get("nombre") or "(sin nombre)"
        # El TEXTO del boton puede ser largo y bonito; el callback_data lleva
        # solo el nombre del fichero (Telegram lo limita a 64 bytes, y una
        # marca de tiempo cabe de sobra).
        botones.append([InlineKeyboardButton(
            f"{fecha} — {nombre}"[:60],
            callback_data=f"{_PREFIJO_BORRAR}{ruta.name}",
        )])

    if not botones:
        await mensaje.reply_text("No hay ninguna conversación que pueda listar.")
        return

    await mensaje.reply_text(
        "¿Cuál quieres borrar? (te lo preguntaré otra vez antes de hacerlo)",
        reply_markup=InlineKeyboardMarkup(botones),
    )


def _borrar_del_todo(ruta: Path) -> bool:
    """Borra una conversacion de LOS DOS SITIOS: el indice vectorial y el
    disco. Ver el porque en telegram_bot._descartar."""
    try:
        olvidar_conversacion(ruta)
        return borrar_conversacion(ruta)
    except Exception as error:
        logging.error("Telegram: fallo al borrar (%s)", type(error).__name__)
        return False


# --- /modelo y /proveedor: menus con BOTONES -------------------------------
# En la CLI son menus de flechas (questionary). En Telegram no existe tal
# cosa: el equivalente son los "inline keyboards", botones bajo el mensaje
# que al pulsarse mandan un CallbackQuery de vuelta.
#
# SEGURIDAD: esos CallbackQuery son updates como cualquier otro, asi que
# pasan por puerta_allowlist igual que un mensaje - porque la puerta es un
# TypeHandler(Update) del grupo -1, no un filtro por handler. Es justo la
# ventaja de ese diseño (ver ADR-005): añadir una via de entrada nueva NO
# obliga a acordarse de protegerla.
#
# El callback_data viaja a Telegram y vuelve, asi que NO se le confia nada:
# al volver se comprueba que el valor este en el catalogo de config.py antes
# de usarlo. Telegram ademas lo limita a 64 bytes.

_PREFIJO_MODELO = "m:"
_PREFIJO_PROVEEDOR = "p:"
# ADR-006: /tools. Cada pulsacion CONMUTA una categoria y vuelve a dibujar
# el menu, en vez de cerrarlo: activar varias de una vez es lo normal, y
# cerrar el menu en cada toque obligaria a repetir el comando.
_PREFIJO_TOOLS = "t:"
# Enseña la lista blanca de sitios sin salir del menu de /tools.
# OJO: NO puede empezar por "t:" - lo cazaria antes el conmutador de
# categorias y buscaria una categoria llamada "ver-sitios".
_VER_SITIOS = "ver-sitios"


def _teclado(prefijo: str, opciones: list[str]) -> InlineKeyboardMarkup:
    """Un boton por opcion, uno por fila (los nombres de modelo son largos)."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(op, callback_data=f"{prefijo}{op}")] for op in opciones]
    )


async def cmd_modelo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cambia de modelo DENTRO del proveedor actual."""
    usuario = update.effective_user
    mensaje = update.effective_message
    if usuario is None or mensaje is None:
        return
    agente = _agente_de(usuario.id)
    opciones = MODELOS.get(agente.proveedor, [])
    if not opciones:
        await mensaje.reply_text("No tengo catálogo de modelos para este proveedor.")
        return
    await mensaje.reply_text(
        f"Ahora uso *{agente.modelo}* ({agente.proveedor}). ¿A cuál cambio?",
        parse_mode="Markdown",
        reply_markup=_teclado(_PREFIJO_MODELO, opciones),
    )


async def cmd_proveedor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cambia de proveedor (y coge su modelo por defecto)."""
    usuario = update.effective_user
    mensaje = update.effective_message
    if usuario is None or mensaje is None:
        return
    # Solo los que tienen clave configurada: ofrecer uno sin clave seria
    # ofrecer un error (misma logica que construir_cadena en llm_router).
    disponibles = []
    for proveedor in MODELOS:
        try:
            obtener_api_key(proveedor)
        except ClaveApiNoConfigurada:
            continue
        disponibles.append(proveedor)

    if not disponibles:
        await mensaje.reply_text("No hay ningún proveedor con clave configurada.")
        return
    await mensaje.reply_text(
        f"Ahora hablo con *{_agente_de(usuario.id).proveedor}*. ¿A cuál cambio?",
        parse_mode="Markdown",
        reply_markup=_teclado(_PREFIJO_PROVEEDOR, disponibles),
    )


def _teclado_tools(agente) -> InlineKeyboardMarkup:
    """Un boton por categoria, con marca de encendida/apagada.

    Lleva SIEMPRE "⬅ Cerrar" al final: es la convencion del 27/07 para
    cualquier menu ("Volver"/"Cancelar" visible). Se llama "Cerrar" y no
    "Volver" porque en Telegram no hay un paso anterior al que volver - el
    menu es lo primero que sale.
    """
    from src.tools import categorias_disponibles, nombres_de

    filas = []
    for categoria in categorias_disponibles():
        encendida = categoria in agente.categorias_activas
        marca = "✅" if encendida else "⬜"
        etiqueta = f"{marca} {categoria} — {', '.join(nombres_de(categoria))}"
        filas.append([InlineKeyboardButton(
            etiqueta[:60], callback_data=f"{_PREFIJO_TOOLS}{categoria}",
        )])
    # Ver a que sitios puede ir de verdad la categoria "web": tenerla
    # encendida no dice nada si no sabes la lista blanca (Jordi, 30/07).
    filas.append([InlineKeyboardButton(
        "🌐 Ver sitios autorizados", callback_data=_VER_SITIOS,
    )])
    filas.append([InlineKeyboardButton("⬅ Cerrar", callback_data=_CANCELAR)])
    return InlineKeyboardMarkup(filas)


async def cmd_tools(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enciende o apaga grupos de herramientas (ADR-006).

    Por que existe: la ficha de CADA herramienta activa viaja en CADA
    peticion al modelo, asi que tenerlas todas encendidas se paga en tokens
    en todos los turnos - y ademas el modelo acierta peor al elegir cuantas
    mas opciones parecidas tenga delante.
    """
    usuario = update.effective_user
    mensaje = update.effective_message
    if usuario is None or mensaje is None:
        return
    await mensaje.reply_text(
        "Toca para encender o apagar cada grupo:",
        reply_markup=_teclado_tools(_agente_de(usuario.id)),
    )


async def manejar_boton(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Procesa la pulsacion de un boton de /modelo o /proveedor."""
    consulta = update.callback_query
    usuario = update.effective_user
    if consulta is None or usuario is None:
        return

    # answer() quita el "relojito" de carga del boton. Si no se llama, el
    # cliente de Telegram deja el boton girando unos segundos.
    await consulta.answer()
    dato = consulta.data or ""

    # /salir va primero: es el unico que no necesita un Agente vivo (de
    # hecho lo que hace es cerrarlo), asi que no se crea uno solo por
    # pulsar el boton.
    if dato in (_CONSERVAR, _DESCARTAR):
        async with _cerrojo_de(usuario.id):
            if dato == _DESCARTAR:
                borrado = await asyncio.to_thread(_descartar, usuario.id)
                texto = (
                    "Descartada: la he borrado del disco y de mi memoria."
                    if borrado
                    else "No he encontrado nada que borrar."
                )
            else:
                texto = "Guardada. Empezamos conversación nueva."
            # En los dos casos se cierra la charla: se olvida el contexto en
            # curso y se suelta el fichero, para que el mensaje siguiente
            # estrene conversacion.
            _agentes.pop(usuario.id, None)
            _rutas.pop(usuario.id, None)
            _nombres.pop(usuario.id, None)
        await consulta.edit_message_text(texto)
        return

    # /borrar, paso 1: se ha elegido una conversacion -> se PIDE CONFIRMACION.
    # Dos pasos y no uno porque esto es irreversible: no hay papelera.
    # "bc:" NO empieza por "b:" (el 2o caracter ya difiere), asi que los dos
    # prefijos no chocan y no hace falta desambiguar.
    if dato.startswith(_PREFIJO_BORRAR):
        nombre = dato[len(_PREFIJO_BORRAR):]
        if await asyncio.to_thread(_conversacion_valida, nombre) is None:
            await consulta.edit_message_text("Esa conversación ya no existe.")
            return
        await consulta.edit_message_text(
            "¿Seguro? Esto la borra del disco y de mi memoria, sin vuelta atrás.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "Sí, bórrala", callback_data=f"{_PREFIJO_BORRAR_OK}{nombre}"
                )],
                [InlineKeyboardButton("Cancelar", callback_data=_CANCELAR)],
            ]),
        )
        return

    # /borrar, paso 2: confirmado.
    if dato.startswith(_PREFIJO_BORRAR_OK):
        nombre = dato[len(_PREFIJO_BORRAR_OK):]
        # Se REVALIDA aqui, no se confia en que el paso 1 ya lo hiciera: este
        # callback_data llega de fuera igual que el otro y podria mandarse
        # directamente, sin pasar por el primer boton.
        ruta = await asyncio.to_thread(_conversacion_valida, nombre)
        if ruta is None:
            await consulta.edit_message_text("Esa conversación ya no existe.")
            return
        borrado = await asyncio.to_thread(_borrar_del_todo, ruta)
        # Si era la conversacion ABIERTA, hay que soltarla: si no, el
        # siguiente turno la volveria a escribir en la misma ruta y la
        # resucitaria (guardar_conversacion con ruta= crea el fichero
        # aunque ya no exista).
        if _rutas.get(usuario.id) == ruta:
            _rutas.pop(usuario.id, None)
            _nombres.pop(usuario.id, None)
        await consulta.edit_message_text(
            "Borrada del disco y de mi memoria." if borrado else "No he podido borrarla."
        )
        return

    if dato == _CANCELAR:
        await consulta.edit_message_text("Vale, no toco nada.")
        return

    agente = _agente_de(usuario.id)

    # Lista blanca de sitios, sin salir del menu de /tools.
    if dato == _VER_SITIOS:
        from src.config import obtener_dominios_permitidos

        dominios = sorted(obtener_dominios_permitidos())
        if dominios:
            texto = "Puedo leer estos sitios:\n" + "\n".join(f"· {d}" for d in dominios)
            texto += "\n\n(se añaden en DOMINIOS_PERMITIDOS_WEB del .env)"
        else:
            texto = (
                "⚠️ No hay ningún sitio autorizado, así que no puedo leer "
                "ninguna web. Añádelos a DOMINIOS_PERMITIDOS_WEB en el .env."
            )
        await consulta.edit_message_text(texto, reply_markup=_teclado_tools(agente))
        return

    # ADR-006: conmutar una categoria y REDIBUJAR el menu (no cerrarlo).
    if dato.startswith(_PREFIJO_TOOLS):
        from src.tools import categorias_disponibles

        categoria = dato[len(_PREFIJO_TOOLS):]
        # El callback_data vuelve de Telegram: dato NO confiable. Se valida
        # contra las categorias reales antes de tocar nada, igual que se
        # hace con el modelo y el proveedor.
        if categoria not in categorias_disponibles():
            await consulta.edit_message_text("Ese grupo de herramientas ya no existe.")
            return
        async with _cerrojo_de(usuario.id):
            if categoria in agente.categorias_activas:
                agente.categorias_activas.discard(categoria)
            else:
                agente.categorias_activas.add(categoria)
            activas = sorted(agente.categorias_activas)
        await consulta.edit_message_text(
            ("Activas: " + ", ".join(activas)) if activas
            else "Todas apagadas: responderé sin usar herramientas.",
            reply_markup=_teclado_tools(agente),
        )
        return

    if dato.startswith(_PREFIJO_MODELO):
        elegido = dato[len(_PREFIJO_MODELO):]
        # NO se confia en el dato que vuelve de Telegram: tiene que estar en
        # el catalogo verificado de config.py.
        if elegido not in MODELOS.get(agente.proveedor, []):
            await consulta.edit_message_text("Ese modelo ya no está disponible.")
            return
        async with _cerrojo_de(usuario.id):
            agente.cambiar_modelo(elegido)
        await consulta.edit_message_text(f"Listo, ahora uso {elegido}.")
        return

    if dato.startswith(_PREFIJO_PROVEEDOR):
        elegido = dato[len(_PREFIJO_PROVEEDOR):]
        if elegido not in MODELOS:
            await consulta.edit_message_text("Ese proveedor no existe.")
            return
        try:
            clave = obtener_api_key(elegido)
        except ClaveApiNoConfigurada:
            await consulta.edit_message_text(f"No tengo clave configurada para {elegido}.")
            return
        modelo = obtener_modelo_por_defecto(elegido)
        async with _cerrojo_de(usuario.id):
            # El historial NO se toca al cambiar (F3.1): esta en formato
            # canonico y el proveedor nuevo hereda la conversacion entera.
            agente.cambiar_proveedor(elegido, modelo, clave)
        await consulta.edit_message_text(f"Listo, ahora hablo con {elegido} ({modelo}).")


async def cmd_desconocido(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cualquier otro comando. Responder es mejor que ignorar en silencio:
    quien escribe /algo espera una reaccion, y el silencio parece que el
    bot esta roto."""
    if update.effective_message:
        await update.effective_message.reply_text(
            "No conozco ese comando. Prueba /ayuda."
        )


async def manejar_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Red de seguridad para lo que se rompa FUERA de los handlers (la
    propia PTB, la red hacia Telegram).

    Solo metadatos al log. NUNCA str(context.error), NUNCA
    traceback.format_exc(), NUNCA repr(update) - ese ultimo es el error
    numero 1 de los bots de Telegram: vuelca de golpe el texto del
    mensaje, el nombre real y el id del usuario.

    LANZA ApplicationHandlerStop al final, y eso es un control de
    seguridad, no una floritura (auditoria del 27/07). Verificado en el
    codigo de PTB: process_update() captura la excepcion de un handler y
    llama a process_error(); si este devuelve False, el bucle NO hace
    break y el update SIGUE a los grupos siguientes. Y process_error solo
    devuelve True si el error handler lanza ApplicationHandlerStop. Sin
    esta linea, una excepcion en una de las puertas del grupo -1 dejaria
    que el update llegase igualmente a manejar_mensaje.
    """
    logging.error("Telegram: error no capturado (%s)", type(context.error).__name__)
    raise ApplicationHandlerStop


# --- Arranque --------------------------------------------------------------


def construir_aplicacion() -> Application:
    """Monta la Application con sus handlers, SIN arrancarla.

    Separado de run_polling() a proposito: asi los tests pueden construir
    la aplicacion real, inspeccionar que handlers hay y en que grupo, y
    llamar a los callbacks a mano con objetos falsos - sin red y sin token
    de verdad. Mismo movimiento que hizo Agente al no saber nada de
    terminal.
    """
    # Se validan las dos al arrancar (fallo rapido y mensaje claro) aunque
    # la allowlist se relea luego en cada update.
    token = obtener_token_telegram()
    permitidos = obtener_usuarios_permitidos()

    if len(permitidos) > 1:
        # ERROR DURO, no un aviso (auditoria del 27/07, hallazgo Alto).
        #
        # El indice del RAG es GLOBAL: rag.buscar() consulta la coleccion
        # entera sin ningun filtro por propietario, y storage.py ni
        # siquiera guarda de quien es cada conversacion. Con dos usuarios
        # autorizados, B recupera los recuerdos DESCIFRADOS de A con solo
        # preguntar algo parecido - aunque cada uno tenga su propio Agente.
        #
        # Antes esto era un logging.warning, y un aviso que solo vive en
        # un fichero de log no lo lee nadie mientras arranca el bot. Como
        # el proyecto no puede cumplir el aislamiento hoy, lo correcto es
        # NO ARRANCAR: mejor que no funcione a que funcione filtrando.
        raise ConfiguracionTelegramInvalida(
            f"{len(permitidos)} usuarios en la lista blanca, pero la memoria "
            "semantica (RAG) es COMPARTIDA: cualquiera de ellos podria recuperar "
            "las conversaciones de los demas. Deja un solo user_id hasta que el "
            "indice este particionado por usuario (ver ADR-005 y RNF-06)."
        )

    # NO se llama a .concurrent_updates(True) a proposito. Sin el, PTB
    # procesa los updates de uno en uno ("updates will be processed one by
    # one", doc oficial), lo que evita de raiz las carreras sobre el
    # historial. Los cerrojos por usuario estan igualmente por si algun
    # dia se activa.
    try:
        aplicacion = ApplicationBuilder().token(token).build()
    except Exception as error:
        # El token NO puede acabar en un traceback. Verificado en PTB: con
        # un token invalido lanza InvalidToken("The token `<token>` was
        # rejected by the server."), o sea, el secreto DENTRO del mensaje
        # de la excepcion. Sin este except, ese traceback sale por stderr
        # y en un despliegue real lo recoge journald o los logs de Docker,
        # fuera del control del logging saneado del proyecto.
        logging.error("Telegram: no se pudo crear el bot (%s)", type(error).__name__)
        raise ConfiguracionTelegramInvalida(
            "No se pudo crear el bot con ese token. Revisa TELEGRAM_BOT_TOKEN "
            "en el .env (te lo da @BotFather)."
        ) from None

    # Grupo -1: las dos puertas, en orden. El orden importa: un no
    # autorizado se corta en la primera y ni siquiera crea entrada en el
    # estado del limitador.
    aplicacion.add_handler(TypeHandler(Update, puerta_allowlist), group=-1)
    aplicacion.add_handler(TypeHandler(Update, puerta_rate_limit), group=-1)

    # Grupo 0: el trabajo de verdad.
    # Los comandos van ANTES del handler de texto: "/limpiar" es texto y es
    # comando, asi que sin estos CommandHandler caia entre las dos sillas
    # (filters.TEXT & ~filters.COMMAND lo excluye por comando, ~filters.TEXT
    # lo excluye por texto) y se perdia EN SILENCIO - incluido "/start",
    # que es lo primero que escribe cualquiera al abrir un bot. Hallazgo de
    # la auditoria del 27/07, verificado con los filtros reales de PTB.
    aplicacion.add_handler(CommandHandler("start", cmd_start))
    aplicacion.add_handler(CommandHandler(["ayuda", "help", "comandos"], cmd_ayuda))
    aplicacion.add_handler(CommandHandler("limpiar", cmd_limpiar))
    aplicacion.add_handler(CommandHandler("resumen", cmd_resumen))
    # F5.2+ (paridad con la CLI): historial, guardar, modelo y proveedor.
    aplicacion.add_handler(CommandHandler("historial", cmd_historial))
    aplicacion.add_handler(CommandHandler("guardar", cmd_guardar))
    aplicacion.add_handler(CommandHandler("modelo", cmd_modelo))
    aplicacion.add_handler(CommandHandler("proveedor", cmd_proveedor))
    aplicacion.add_handler(CommandHandler("recuerdo", cmd_recuerdo))
    aplicacion.add_handler(CommandHandler("salir", cmd_salir))
    aplicacion.add_handler(CommandHandler("borrar", cmd_borrar))
    aplicacion.add_handler(CommandHandler("tools", cmd_tools))
    # Los botones de /modelo y /proveedor vuelven como CallbackQuery. Pasan
    # por la allowlist igual que todo lo demas (TypeHandler del grupo -1).
    aplicacion.add_handler(CallbackQueryHandler(manejar_boton))
    # Cualquier otro comando: responde en vez de desaparecer.
    aplicacion.add_handler(MessageHandler(filters.COMMAND, cmd_desconocido))

    aplicacion.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    aplicacion.add_handler(MessageHandler(~filters.TEXT, manejar_no_texto))

    aplicacion.add_error_handler(manejar_error)
    return aplicacion


def main_bot() -> None:
    """Arranca el bot con polling.

    Polling y NO webhook: un webhook exigiria una URL publica, un
    certificado TLS y un endpoint HTTP expuesto a internet - tres
    superficies de ataque nuevas, en contra del requisito rector de que
    los datos no salgan de la maquina. El polling sale de dentro hacia
    fuera y no abre ningun puerto.
    """
    aplicacion = construir_aplicacion()

    # BUG encontrado probando en real el 28/07: sin esto, el bot solo tenia en
    # el indice lo que EL MISMO habia escrito. Una conversacion guardada desde
    # la CLI quedaba en disco pero NADIE la indexaba, porque el bot solo
    # indexa su propio fichero despues de cada turno - asi que
    # buscar_en_recuerdos no la encontraba y el agente contestaba "no lo
    # tengo guardado" teniendo el dato a un palmo. La CLI ya hacia esto al
    # arrancar (main.py); al bot se me olvido, y los tests no lo cogieron
    # porque todos espian el indexado en vez de arrancar el bot de verdad.
    try:
        nuevos = indexar_conversaciones()
        print(f"Memoria semántica al día ({nuevos} recuerdo(s) nuevo(s) indexado(s)).")
    except Exception as error:
        # No impide arrancar: sin memoria semantica el bot sigue siendo util
        # (RNF-02). Tipo, no texto: el str() puede arrastrar contenido.
        logging.error("Telegram: no se pudo indexar al arrancar (%s)", type(error).__name__)
        print("⚠️ No se pudo cargar la memoria semántica; el bot arranca igual.")

    print("Bot de Telegram arrancado. Ctrl+C para parar.")
    # F5.2+: el bot y la CLI comparten memoria, y eso tiene un limite que hay
    # que decir EN PANTALLA (no solo en el log, que nadie mira mientras usa el
    # programa - misma leccion que el aviso de cifrado apagado en main.py).
    # ChromaDB en modo PersistentClient esta pensado para UN proceso: dos a la
    # vez sobre chroma_db/ pueden corromper el indice. El cerrojo de rag.py
    # protege hilos DENTRO de un proceso, no procesos distintos.
    print(
        "ℹ️ Comparto memoria con la CLI (conversations/ + chroma_db/). "
        "NO ejecutes 'python -m src.main' a la vez que el bot."
    )
    try:
        aplicacion.run_polling()
    except KeyboardInterrupt:
        # PTB ya atrapa el PRIMER Ctrl+C y hace un apagado ordenado. Pero si
        # se pulsa OTRA vez mientras esta apagando (justo lo que paso el
        # 28/07 probando), el segundo KeyboardInterrupt cae en mitad del
        # cierre y sale un traceback de 30 lineas que parece un fallo grave
        # y no lo es. Se atrapa para despedirse en una linea.
        print("\nBot parado.")


if __name__ == "__main__":
    main_bot()
