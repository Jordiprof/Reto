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

from telegram import Update
from telegram.constants import ChatAction, MessageLimit
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ApplicationHandlerStop,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

from src.agent import Agente
from src.config import (
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
from src.rag import indexar_conversacion
from src.storage import guardar_conversacion

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


def _persistir(user_id: int) -> None:
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

    OJO: es SINCRONA y bloqueante (cifra, escribe disco, incrusta el texto
    en un vector). Quien la llame debe hacerlo con asyncio.to_thread, igual
    que con Agente.preguntar - si no, congela el bucle de eventos del bot.
    """
    agente = _agentes.get(user_id)
    if agente is None:
        return
    try:
        ruta = guardar_conversacion(
            agente.historial, agente.proveedor, agente.modelo,
            # El "nombre" es la etiqueta que en la CLI pone Jordi a mano al
            # guardar. Por Telegram no hay donde pedirla sin interrumpir la
            # charla, asi que se marca el origen: al menos /historial deja
            # distinguir de un vistazo que salio del bot.
            nombre="Telegram",
            ruta=_rutas.get(user_id),
        )
        if ruta is None:
            return  # historial vacio (solo el system prompt): nada que guardar
        _rutas[user_id] = ruta
        indexar_conversacion(ruta)
    except Exception as error:
        # Tipo, no texto (politica de logging del proyecto): el str() de un
        # error de cifrado o de ChromaDB puede arrastrar contenido.
        logging.error("Telegram: no se pudo persistir el turno (%s)", type(error).__name__)


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
            "/limpiar — empezar de cero (olvida esta conversación)\n"
            "/resumen — resumir lo hablado hasta ahora\n"
            "/ayuda — esto\n\n"
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
    aplicacion.add_handler(CommandHandler(["ayuda", "help"], cmd_ayuda))
    aplicacion.add_handler(CommandHandler("limpiar", cmd_limpiar))
    aplicacion.add_handler(CommandHandler("resumen", cmd_resumen))
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
    aplicacion.run_polling()


if __name__ == "__main__":
    main_bot()
