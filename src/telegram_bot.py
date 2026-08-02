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
from src.cerrojo import CerrojoMemoria, MemoriaOcupada
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
    cargar_conversacion,
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

# Tope de bloques al condensar un documento (02/08). Es el mismo que el de
# resumen_largo, pero se nombra AQUI para poder bajarlo en Telegram sin
# tocar la CLI: por el chat es donde se pide sin pensar, y cada bloque es
# una llamada al modelo. Con 10 son ~200 hojas y la mitad de la cuota
# diaria de Groq en un solo documento.
TOPE_BLOQUES_TELEGRAM = 10


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

# F5.5 #8 - Voz: que mitades estan encendidas por usuario, subconjunto de
# {"escuchar", "hablar"}. Empieza VACIO, o sea las dos apagadas.
#
# POR QUE UN DICCIONARIO APARTE Y NO UN CAMPO DEL Agente (como
# categorias_activas): porque /limpiar y /salir hacen _agentes.pop(), y con
# ello se llevarian por delante la preferencia de voz. Vaciar la
# conversacion y dejar de hablarle a alguien son cosas distintas: lo
# primero es estado de la CHARLA, lo segundo es una preferencia del CANAL,
# y confundirlas es como se cuelan los "se me apago solo y no se por que".
_voz_activa: dict[int, set[str]] = {}


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


# --- Puerta 3: soltar una peticion de texto pendiente ----------------------


async def puerta_soltar_espera(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cualquier COMANDO cancela un "dime el nombre / dime qué busco".

    Nace de una mentira en la interfaz (01/08): el propio bot dice "si
    prefieres dejarlo, usa cualquier comando y no toco nada", y NO era
    verdad. Los comandos los atienden los CommandHandler, que no pasan por
    _turno, asi que el estado seguia puesto y el siguiente mensaje escrito
    se lo comia igual.

    Va en el grupo -1 (con la allowlist y el rate limit) y NO lanza
    ApplicationHandlerStop: solo limpia y deja pasar, para que el comando se
    ejecute normalmente despues. Puesto DESPUES de la allowlist a proposito:
    un desconocido no debe poder tocar ni este diccionario.
    """
    usuario = update.effective_user
    mensaje = update.effective_message
    if usuario is None or mensaje is None or not mensaje.text:
        return
    if mensaje.text.startswith("/"):
        _esperando_texto.pop(usuario.id, None)


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

    await _turno(update, context, texto)


async def _cerrar_con_nombre(update: Update, nombre: str) -> None:
    """Guarda la conversacion en curso CON el nombre que acaba de escribir
    el usuario y la cierra.

    El estado ("estabamos esperando un nombre") ya se ha soltado ANTES de
    llegar aqui - lo saca manejar_mensaje con un pop() previo a llamar a
    esta funcion, no un finally aqui dentro. Asi, incluso si esta funcion
    revienta con algo no previsto, el bot no se queda comiendose todos los
    mensajes siguientes creyendo que aun espera un nombre.
    """
    usuario = update.effective_user
    mensaje = update.effective_message
    if usuario is None or mensaje is None:
        return

    # Mismo tope que /guardar: el nombre va EN CLARO a los metadatos del
    # JSON (por eso /historial puede listar sin descifrar), asi que ademas
    # de caber en la lista conviene que no sea un texto libre largo. Y
    # cuidado con lo que se escribe aqui: consultar_historial mete los
    # TITULOS en el contexto del modelo, y ese contexto viaja al proveedor.
    nombre = nombre[:_MAX_NOMBRE].strip()
    if not nombre:
        await mensaje.reply_text("Eso está vacío; la dejo tal cual estaba.")
        return
    try:
        async with _cerrojo_de(usuario.id):
            ruta = await asyncio.to_thread(_persistir, usuario.id, nombre)
            # Se cierra igual que en _CONSERVAR: se olvida el contexto y se
            # suelta el fichero, para que el mensaje siguiente estrene charla.
            _agentes.pop(usuario.id, None)
            _rutas.pop(usuario.id, None)
            _nombres.pop(usuario.id, None)
        if ruta is None:
            await mensaje.reply_text("No había nada que guardar, así que la cierro sin más.")
        else:
            await mensaje.reply_text(
                f"Guardada como «{nombre}». Empezamos conversación nueva."
            )
    except Exception as error:
        logging.error("Telegram: fallo al guardar con nombre (%s)", type(error).__name__)
        await mensaje.reply_text("⚠️ No he podido guardarla con ese nombre.")


async def _guardar_con_texto(update: Update, nombre: str) -> None:
    """Version de /guardar pedida desde el menu de botones (31/07): el
    nombre llega como el mensaje SIGUIENTE en vez de como argumento del
    comando. Comparte el nucleo con cmd_guardar via _ejecutar_guardar - la
    unica diferencia es DE DONDE sale el nombre."""
    usuario = update.effective_user
    mensaje = update.effective_message
    if usuario is None or mensaje is None:
        return
    await _ejecutar_guardar(usuario.id, mensaje, nombre)


async def _recuerdo_con_texto(update: Update, consulta: str) -> None:
    """Version de /recuerdo pedida desde el menu de botones (31/07): mismo
    nucleo que cmd_recuerdo (_ejecutar_recuerdo), la busqueda llega en el
    mensaje SIGUIENTE en vez de como argumento del comando."""
    mensaje = update.effective_message
    if mensaje is None:
        return
    await _ejecutar_recuerdo(mensaje, consulta)


async def _turno(update: Update, context: ContextTypes.DEFAULT_TYPE, texto: str) -> None:
    """El turno de verdad, ya con el texto en la mano.

    Separado de manejar_mensaje en F5.5 #8 porque ahora hay DOS puertas de
    entrada al mismo turno -un mensaje escrito y una nota de voz
    transcrita- y duplicar aqui seria duplicar el cerrojo, el manejo de
    errores y la persistencia: los tres sitios donde este proyecto ya ha
    encontrado bugs reales. Desde aqui hacia abajo, el bot no sabe ni le
    importa si aquello lo dijeron o lo escribieron.
    """
    mensaje = update.effective_message
    usuario = update.effective_user
    if mensaje is None or usuario is None:
        return

    # ¿Le habiamos pedido algo por escrito (un nombre, una busqueda)? Este
    # texto no es una pregunta para el LLM: es la respuesta a algo que
    # preguntamos NOSOTROS.
    #
    # ESTA COMPROBACION VIVE AQUI Y NO EN manejar_mensaje, y es un BUG REAL
    # del 01/08 encontrado por Jordi probando: estaba en manejar_mensaje, que
    # solo cubre el camino ESCRITO. Contesto a "dime que busco" con una NOTA
    # DE VOZ -> manejar_voz llama directo a _turno, se salto la comprobacion,
    # el estado se quedo puesto Y NO SE LIMPIO NUNCA... y varios turnos
    # despues, su siguiente mensaje escrito ("metete en esta web y
    # resumemela") se lo comio /recuerdo en vez de contestarlo.
    #
    # La leccion es la de siempre en este fichero: cuando hay DOS puertas de
    # entrada, el control va en el EMBUDO por el que pasan las dos, no en
    # una de ellas. Aqui abajo, cualquier camino futuro queda cubierto solo.
    #
    # Se saca (.pop()) YA, antes de llamar a nada: asi el estado se suelta
    # pase lo que pase, incluso si la accion revienta con algo no previsto.
    accion = _esperando_texto.pop(usuario.id, None)
    if accion == "salir_nombrar":
        await _cerrar_con_nombre(update, texto)
        return
    if accion == "guardar":
        await _guardar_con_texto(update, texto)
        return
    if accion == "recuerdo":
        await _recuerdo_con_texto(update, texto)
        return

    fallo = False
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
            fallo = True
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

    # Si contesto un fallback, se dice ANTES de la respuesta: si fuera
    # despues, se leeria la respuesta creyendo que la dio el modelo elegido.
    aviso = getattr(getattr(_agentes.get(usuario.id), "router", None), "aviso_fallback", None)
    if aviso and not fallo:
        await mensaje.reply_text(aviso)

    for trozo in _trocear(respuesta):
        await mensaje.reply_text(trozo)

    # Salida binaria (01/08, peticion de Jordi): si alguna tool dejo una
    # imagen en la bandeja del turno, se manda como FOTO. Va despues del
    # texto por el mismo criterio que la voz: el texto es la respuesta
    # completa y no debe depender de que esto funcione. Un fallo aqui se
    # registra y se sigue - Telegram puede rechazar una imagen por tamaño o
    # por no poder descargarla, y eso no puede costarnos la respuesta.
    if not fallo:
        for medio in list(getattr(_agentes.get(usuario.id), "media_pendiente", [])):
            try:
                await mensaje.reply_photo(medio["url"], caption=medio["titulo"][:200])
            except Exception as error:
                logging.warning(
                    "Telegram: no se pudo enviar la imagen (%s)", type(error).__name__
                )

    # F5.5 #8: y si ademas toca hablar, la nota de voz DESPUES del texto.
    # Ese orden y no al reves: el texto es la respuesta completa y siempre
    # funciona, asi que va primero y llega aunque la sintesis se caiga. La
    # voz es el extra.
    #
    # `fallo` se mira aqui: leer en voz alta "se me ha cruzado un cable" no
    # aporta nada y ademas gasta CPU en sintetizar un mensaje de error.
    if not fallo and "hablar" in _voz_activa.get(usuario.id, set()):
        await _hablar(update, context, respuesta)


async def _hablar(update: Update, context: ContextTypes.DEFAULT_TYPE, texto: str) -> None:
    """Manda la respuesta como NOTA DE VOZ, con Piper local.

    Un fallo aqui NUNCA rompe el turno: el usuario ya tiene su respuesta
    escrita, asi que como mucho se le avisa de que el audio no salio. Es la
    misma idea que el guardado de la conversacion: lo accesorio no puede
    tumbar lo principal.
    """
    from src.voz import VozNoDisponible, sintetizar

    mensaje = update.effective_message
    if mensaje is None:
        return
    try:
        # RECORD_VOICE y no TYPING: el indicador que ve el usuario debe
        # decir lo que de verdad esta pasando, y sintetizar tarda unos
        # segundos.
        await context.bot.send_chat_action(mensaje.chat_id, ChatAction.RECORD_VOICE)
        # to_thread por lo mismo que Agente.preguntar(): cargar el modelo,
        # sintetizar y llamar a ffmpeg son operaciones BLOQUEANTES de CPU
        # y de subproceso. Aqui congelarian el bot entero.
        audio = await asyncio.to_thread(sintetizar, texto)
    except VozNoDisponible as error:
        await mensaje.reply_text(f"🔇 {error}")
        return
    except Exception as error:
        logging.error("Telegram: fallo generando la voz (%s)", type(error).__name__)
        await mensaje.reply_text("🔇 No he podido mandarte el audio, pero ahí tienes el texto.")
        return

    await mensaje.reply_voice(audio)


async def manejar_voz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Nota de voz -> transcripcion -> el MISMO turno que un mensaje escrito.

    LA PUERTA ESTA AQUI, y es la razon de ser de este handler: si
    "escuchar" no esta encendido, el audio NO SE DESCARGA Y NO SALE DE
    TELEGRAM. No se transcribe "por probar" ni se cachea: sin permiso
    explicito, la nota se queda donde esta. Es el mismo criterio que
    `memoria` y `web` en /tools -apagado por EXPOSICION, no por costumbre-,
    solo que aqui lo que se expone es un dato biometrico.

    Y a diferencia de un documento adjunto (donde entregar el fichero YA es
    la autorizacion, decision del 31/07), aqui mandar la nota NO puede
    valer como permiso: una nota de voz se manda por comodidad, sin pensar
    en que ese audio va a viajar a un tercero. Por eso la voz si necesita
    su interruptor y los documentos no.
    """
    mensaje = update.effective_message
    usuario = update.effective_user
    if mensaje is None or usuario is None or mensaje.voice is None:
        return

    if "escuchar" not in _voz_activa.get(usuario.id, set()):
        await mensaje.reply_text(
            "🔇 No transcribo notas de voz porque lo tengo apagado, así que ese "
            "audio no ha salido de Telegram.\n\n"
            "Puedes encenderlo en /voz. Antes lee esto: para entenderte mando el "
            "audio a Groq, y tu voz es un dato biométrico (identifica a la "
            "persona, no solo lo que dice)."
        )
        return

    from src.voz import VozNoDisponible, transcribir, validar_duracion

    try:
        # Con el metadato del update: aqui todavia no se ha descargado nada
        # ni se ha tocado la cuota de Groq, asi que rechazar es gratis.
        validar_duracion(mensaje.voice.duration)
    except VozNoDisponible as error:
        await mensaje.reply_text(f"⚠️ {error}")
        return

    async with _cerrojo_de(usuario.id):
        try:
            archivo = await mensaje.voice.get_file()
            datos = bytes(await archivo.download_as_bytearray())
        except Exception as error:
            logging.error("Telegram: fallo descargando la nota de voz (%s)", type(error).__name__)
            await mensaje.reply_text("⚠️ No he podido descargar esa nota de voz.")
            return

        try:
            await context.bot.send_chat_action(mensaje.chat_id, ChatAction.TYPING)
            texto = await asyncio.to_thread(transcribir, datos)
        except VozNoDisponible as error:
            await mensaje.reply_text(f"⚠️ {error}")
            return
        except Exception as error:
            logging.error("Telegram: fallo transcribiendo (%s)", type(error).__name__)
            await mensaje.reply_text("⚠️ No he podido entender esa nota de voz.")
            return

    # El limite de entrada tambien aqui: 5 minutos hablando pueden pasar de
    # _LIMITE_ENTRADA, y el limite existe porque el historial se reenvia
    # ENTERO en cada turno (AUD-03). Que el texto venga de un audio no lo
    # hace mas barato.
    if len(texto) > _LIMITE_ENTRADA:
        await mensaje.reply_text(
            f"Te he entendido, pero eso son {len(texto)} caracteres y solo "
            f"manejo {_LIMITE_ENTRADA} de golpe. Dímelo más corto."
        )
        return

    # SIEMPRE se enseña la transcripcion, y no es un detalle de cortesia:
    #   1. Whisper se equivoca, y sin esto una palabra mal entendida se
    #      convierte en una respuesta absurda sin que se sepa por que.
    #   2. Deja constancia VISIBLE de que ese audio salio de la maquina.
    #      Un permiso que se enciende una vez y luego actua en silencio se
    #      olvida; asi cada nota lo recuerda.
    await mensaje.reply_text(f"🎙️ Te he entendido: «{texto}»")

    await _turno(update, context, texto)


async def manejar_documento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """F5.5 #7 - "comando + adjunto" (decision de Jordi, 31/07): el modelo
    nunca elige que fichero lee, lo elige quien se lo manda a JIM. Aqui
    SOLO se valida y se guarda en el Agente de ESTE usuario - no se
    extrae texto todavia, eso lo hace leer_documento() cuando (y si) el
    modelo la llama, y solo si la categoria 'documentos' esta activa.
    Va ANTES que manejar_no_texto en el registro de handlers (mas
    especifico gana)."""
    mensaje = update.effective_message
    usuario = update.effective_user
    if mensaje is None or usuario is None or mensaje.document is None:
        return

    documento = mensaje.document
    if not documento.file_name:
        await mensaje.reply_text("Ese adjunto no tiene nombre de fichero; no sé qué es.")
        return

    from src.documentos import DocumentoNoValido, validar_adjunto

    async with _cerrojo_de(usuario.id):
        try:
            archivo = await documento.get_file()
            datos = bytes(await archivo.download_as_bytearray())
        except Exception as error:
            logging.error("Telegram: fallo descargando adjunto (%s)", type(error).__name__)
            await mensaje.reply_text("⚠️ No he podido descargar ese fichero.")
            return

        try:
            adjunto = validar_adjunto(datos, documento.file_name)
        except DocumentoNoValido as error:
            await mensaje.reply_text(f"⚠️ {error}")
            return

        agente = _agente_de(usuario.id)
        agente.documento_pendiente = adjunto

        # Se PREPARA aqui (trocear + calcular vectores) y no en la primera
        # pregunta: en un PDF grande eso son ~40 segundos, y cayendo dentro
        # de la pregunta el bot parece colgado. Aqui el usuario acaba de
        # mandar un fichero y espera que tarde un momento.
        # En to_thread porque es CPU pura y bloquearia el bucle de eventos.
        from src.documentos import preparar

        await context.bot.send_chat_action(mensaje.chat_id, ChatAction.TYPING)
        try:
            fragmentos = await asyncio.to_thread(preparar, adjunto)
        except Exception as error:
            # No impide aceptar el documento: la busqueda lo reintentara.
            logging.warning("Telegram: no se pudo preparar el documento (%s)",
                            type(error).__name__)
            fragmentos = 0

    aviso_troceo = (
        f" Es largo, así que lo he partido en {fragmentos} fragmentos: "
        "pregúntame por cualquier parte, también por el final."
        if fragmentos else ""
    )
    aviso_categoria = (
        "" if "documentos" in agente.categorias_activas
        else " Actívalo antes con /tools → categoría 'documentos'."
    )
    await mensaje.reply_text(
        f"Documento recibido: {adjunto.nombre} ({len(datos) // 1000} KB). "
        f"Pregúntame algo sobre él.{aviso_troceo}{aviso_categoria}"
    )


async def manejar_no_texto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fotos, videos, stickers... Sin esto, un adjunto de 20 MB llega a un
    bot que no sabe que hacer con el y acaba en el error handler. El OCR
    sigue en el tier "si sobra tiempo" de F5.5. Ya NO caen aqui ni los
    documentos PDF/Word (los coge manejar_documento, F5.5 #7) ni las notas
    de voz (manejar_voz, F5.5 #8)."""
    if update.effective_message:
        await update.effective_message.reply_text(
            "De momento entiendo texto, notas de voz y PDF/Word como adjunto."
        )


# --- Comandos --------------------------------------------------------------
# Sin estos, un "/loquesea" no encajaba en NINGUN handler y se perdia en
# silencio (hallazgo de la auditoria del 27/07). Ademas de la mala
# experiencia -"/start" es lo primero que escribe cualquiera-, dejaba al
# usuario de Telegram sin forma de vaciar el historial, que crece sin tope
# y se reenvia entero en cada turno.


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """La bienvenida. Es lo PRIMERO que ve cualquiera al abrir el bot, y
    hasta el 31/07 era una sola linea que no decia nada de lo que sabe
    hacer - con 14 comandos detras, eso deja al usuario a ciegas."""
    if update.effective_message:
        await update.effective_message.reply_text(
            "👋 Hola JIM, soy *Jimmy*, tu agente personal.\n\n"
            "Escríbeme normal y ya está. Además puedo:\n\n"
            "🧠 *Acordarme* de lo que hablamos, hoy y dentro de un mes — y lo "
            "que me cuentas se guarda cifrado en tu máquina, no en la nube.\n"
            "🛠️ *Usar herramientas*: calcular, mirar el tiempo, leer una web "
            "autorizada, la foto del día de la NASA…\n"
            "📄 *Leer un PDF o un Word* que me mandes de adjunto.\n"
            "🎙️ *Escucharte y contestarte hablando*, si lo enciendes en /voz.\n\n"
            "Toca /ayuda para verlo por temas, o el botón de menú de aquí abajo.",
            parse_mode="Markdown",
        )


# --- El catalogo de comandos: UNA sola fuente de verdad --------------------
# De aqui salen las DOS cosas que antes se escribian por separado (y por eso
# se desincronizaban): el menu nativo de Telegram (set_my_commands) y los
# botones de /comandos.
#
# REDISEÑADO el 31/07 tras la primera version (comandos agrupados en 4
# familias con una pantalla intermedia por tema): Jordi probandolo dijo que
# no le gustaba - veia /recuerdo "repetido" (una vez en el menu nativo de
# Telegram, otra vez dentro de mi arbol) y prefiere UN SOLO NIVEL: /comandos
# lista TODOS de golpe, y tocar uno lo EJECUTA de verdad en el momento (abre
# el historial, enciende una tool...), no enseña un texto explicandolo.
#
# Cada entrada es (nombre sin "/", descripcion, tipo). El tipo decide que
# hace el boton al pulsarlo:
#   "directo": ejecuta EL MISMO comando (reutiliza cmd_historial, cmd_tools...
#     - funciona sin duplicar nada porque, en un CallbackQuery de verdad,
#     Update.effective_message de la propia libreria PTB YA resuelve solo al
#     mensaje del boton -verificado en su codigo fuente-, exactamente igual
#     que si el usuario hubiera escrito el comando).
#   "texto": el comando necesita un dato escrito (un nombre, una busqueda).
#     El boton lo PIDE y usa el mensaje SIGUIENTE, mismo mecanismo que ya
#     tiene "💾 Guardar con un nombre" en /salir (ver _esperando_texto).
#   "info": NO es un comando real - el adjunto YA es la orden (/documento
#     solo existe en la CLI, que no tiene donde soltar un fichero). El boton
#     solo explica, para que "no se pase ninguno" sin inventar un comando
#     que no hace nada.
_CATALOGO: list[tuple[str, str, str]] = [
    ("recuerdo", "buscar en mi memoria y enseñarte lo que hay, en crudo", "texto"),
    ("historial", "ver tus conversaciones guardadas y abrir cualquiera", "directo"),
    ("guardar", "ponerle nombre a esta charla", "texto"),
    ("borrar", "borrar una conversación del disco y de mi memoria", "directo"),
    ("resumen", "resumir lo hablado hasta ahora", "directo"),
    ("limpiar", "empezar de cero (la guarda y olvida el contexto)", "directo"),
    # "cerrar" y NO "salir" (01/08). Se llamaba /salir por simetria con la
    # CLI, pero ahi significa algo DISTINTO: en la terminal /salir termina el
    # PROGRAMA, aqui solo cierra la conversacion y el bot sigue vivo. Jordi
    # lo probo y se quedo esperando que el proceso se parara.
    #
    # Y no se "arregla" haciendo que /salir apague el bot, porque entonces
    # NO SE PODRIA VOLVER A ENCENDER desde Telegram: habria que ir al PC.
    # Un servicio no se apaga desde su propio chat. Lo que estaba mal era el
    # NOMBRE, no el comportamiento - es la divergencia anotada el 28/07,
    # justo la trampa que la simetria de comandos pretendia evitar.
    ("cerrar", "cerrar esta charla: guardarla, ponerle nombre o descartarla", "directo"),
    ("voz", "escucharte y/o contestarte hablando (los dos empiezan apagados)", "directo"),
    ("tools", "encender o apagar grupos de herramientas", "directo"),
    ("modelo", "cambiar el modelo (mismo proveedor)", "directo"),
    ("proveedor", "cambiar de proveedor (y modelo)", "directo"),
    ("condensar", "resumir el documento adjunto ENTERO y mandártelo en un .md", "directo"),
    ("documento", "mándame un PDF o un Word como adjunto — no hace falta escribirlo", "info"),
]

_CATALOGO_POR_NOMBRE = {
    nombre: (nombre, descripcion, tipo) for nombre, descripcion, tipo in _CATALOGO
}

# Texto de "documento" al pulsarlo: la unica entrada "info" del catalogo, y
# por eso no hace falta una estructura mas general para una sola hoja.
#
# OJO con el Markdown "legacy" de Telegram: la negrita es *asi*, NUNCA
# **asi** (eso es MarkdownV2/CommonMark). Un `**` aqui puede hacer que
# Telegram rechace el mensaje ENTERO, el mismo fallo del 30/07 con los
# titulos de los dominios.
_INFO_DOCUMENTO = (
    "📄 *Documentos*: mándame un PDF o un Word *como adjunto* y podré leerlo. "
    "No hay comando porque no hace falta: el adjunto ya es la orden (en la "
    "terminal, donde no hay dónde soltarlo, sí existe /documento)."
)

# Lo que se pregunta al pulsar un boton "texto" (ver _CATALOGO). El mensaje
# SIGUIENTE del usuario se toma como la respuesta - ver _esperando_texto.
_PETICIONES_TEXTO = {
    "recuerdo": "🔍 Dime qué busco: tomaré tu siguiente mensaje como la búsqueda.\n\n"
                "Si prefieres dejarlo, escribe cualquier comando (/ayuda, por "
                "ejemplo) y no toco nada.",
    "guardar": "💾 Escríbeme el nombre para esta conversación: tomaré tu siguiente "
               "mensaje como el nombre.\n\n"
               "Si prefieres dejarlo, escribe cualquier comando (/ayuda, por "
               "ejemplo) y no toco nada.",
}


def comandos_para_telegram() -> list:
    """La lista para set_my_commands, derivada de _CATALOGO.

    Esto es lo que hace aparecer el BOTON DE MENU azul con los comandos y su
    descripcion, en vez de obligar a escribirlos de memoria. Se excluyen a
    proposito las entradas "info" (hoy solo "documento"): Telegram no puede
    anunciar un comando que el bot no atiende - se veria en el menu, se
    pulsaria y no pasaria nada.
    """
    from telegram import BotCommand

    lista = [BotCommand("start", "empezar y ver qué sé hacer")]
    for nombre, descripcion, tipo in _CATALOGO:
        if tipo == "info":
            continue
        lista.append(BotCommand(nombre, descripcion[:256]))
    lista.append(BotCommand("ayuda", "ver todos los comandos, uno a uno"))
    return lista


_PREFIJO_MENU = "menu:"


def _texto_comandos() -> str:
    """La lista de comandos con su explicacion, EN EL CUERPO del mensaje.

    01/08, Jordi probandolo: "se cortan las instrucciones (...) que se vea
    todo a la izquierda, que no vaya centrado". Las dos quejas tienen la
    misma causa y no tienen arreglo DENTRO de un boton: Telegram **siempre**
    centra el texto de un InlineKeyboardButton y lo recorta si no cabe en el
    ancho del movil (nosotros ademas cortabamos a 60 caracteres).

    Asi que la descripcion se saca de los botones y se pone aqui: el cuerpo
    de un mensaje SI se alinea a la izquierda, no se corta y admite varias
    lineas. Los botones se quedan solo con el nombre del comando, que es lo
    unico que necesitan para caber sin recortarse.
    """
    lineas = ["*Esto es lo que sé hacer* — toca un botón para lanzarlo:\n"]
    lineas += [f"/{nombre} — {descripcion}" for nombre, descripcion, _t in _CATALOGO]
    return "\n".join(lineas)


def _teclado_comandos() -> InlineKeyboardMarkup:
    """Un boton por comando, TODOS al mismo nivel - sin pantalla intermedia
    de temas. Pulsar uno lo EJECUTA (o lo pide, o lo explica).

    DOS POR FILA: con uno por fila salian 12 filas y el menu no cabia en
    una pantalla de movil. Solo el nombre del comando (ver _texto_comandos).
    """
    botones = [
        InlineKeyboardButton(f"/{nombre}", callback_data=f"{_PREFIJO_MENU}{nombre}")
        for nombre, _descripcion, _tipo in _CATALOGO
    ]
    filas = [botones[i:i + 2] for i in range(0, len(botones), 2)]
    filas.append([InlineKeyboardButton("⬅ Cerrar", callback_data=_CANCELAR)])
    return InlineKeyboardMarkup(filas)


async def cmd_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/comandos (y /ayuda, /help): TODOS los comandos en un solo nivel.
    Tocar uno lo ejecuta de verdad - no es un indice, es el menu mismo."""
    if update.effective_message:
        await update.effective_message.reply_text(
            _texto_comandos(),
            parse_mode="Markdown",
            reply_markup=_teclado_comandos(),
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


async def cmd_condensar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pregunta que formato de resumen se quiere. El trabajo lo hace
    _condensar_con_formato cuando se pulsa un boton.

    Se PREGUNTA antes de gastar porque los dos formatos cuestan lo mismo
    -para resumir en diez lineas hay que haberse leido el documento
    entero igual- y elegir mal significa pagarlo dos veces.
    """
    usuario = update.effective_user
    mensaje = update.effective_message
    if usuario is None or mensaje is None:
        return

    if _agente_de(usuario.id).documento_pendiente is None:
        await mensaje.reply_text(
            "No tengo ningún documento a mano. Mándame un PDF o un Word "
            "como adjunto y luego vuelve a pedírmelo."
        )
        return

    await mensaje.reply_text(
        "¿Cómo te lo resumo?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📄 Completo (.md para estudiar)",
                                  callback_data="condensar:completo")],
            [InlineKeyboardButton("⚡ Rápido (unas líneas aquí)",
                                  callback_data="condensar:rapido")],
            [InlineKeyboardButton("⬅ Cerrar", callback_data="condensar:cancelar")],
        ]),
    )


async def _condensar_con_formato(update: Update, formato: str) -> None:
    """El trabajo de verdad, una vez elegido el formato.

    Es un COMANDO y no una tool a proposito: son N llamadas al LLM, y
    dentro de una tool tendriamos al modelo llamando a algo que vuelve a
    llamar al modelo (detalle en el cabecero de src/resumen_largo.py).

    El completo va en .md y no en el chat porque son decenas de miles de
    caracteres: en Telegram serian trece mensajes seguidos.
    """
    usuario = update.effective_user
    mensaje = update.effective_message
    if usuario is None or mensaje is None:
        return

    from src.documentos import extraer_texto
    from src.resumen_largo import (
        ResumenImposible,
        condensar,
        guardar,
        preparar_resumidor,
    )

    async with _cerrojo_de(usuario.id):
        agente = _agente_de(usuario.id)
        adjunto = agente.documento_pendiente
        if adjunto is None:
            await mensaje.reply_text(
                "No tengo ningún documento a mano. Mándame un PDF o un Word "
                "como adjunto y luego vuelve a pedírmelo."
            )
            return

        try:
            texto_doc = await asyncio.to_thread(extraer_texto, adjunto)
            llamar, tamaño, quien = preparar_resumidor(
                agente.proveedor, agente.api_key, agente.modelo
            )
            await mensaje.reply_text(
                f"📚 Voy a leérmelo entero con {quien}. Esto tarda "
                "varios minutos; te voy contando."
            )

            # Los avisos van a una lista y se mandan DESPUES: `condensar`
            # es sincrona y corre en otro hilo, asi que no puede hacer
            # await. Es la misma frontera que la bandeja de imagenes del
            # 01/08 - lo que cruza al hilo es MUTAR una lista que ya
            # existia, no devolver algo por un ContextVar.
            avisos: list[str] = []
            markdown, datos = await asyncio.to_thread(
                condensar, texto_doc, adjunto.nombre, llamar,
                tamaño, TOPE_BLOQUES_TELEGRAM, avisos.append, formato,
            )
        except ResumenImposible as error:
            await mensaje.reply_text(f"⚠️ {error}")
            return
        except Exception as error:
            logging.error("Telegram: fallo condensando (%s)", type(error).__name__)
            await mensaje.reply_text("⚠️ No he podido resumir ese documento.")
            return

        # El rapido va al chat y NO se guarda en disco: son unas lineas que
        # se leen y se olvidan. Guardarlo llenaria resumenes/ de ficheros
        # que nadie va a abrir - mismo criterio que el descarte de /cerrar.
        if formato == "rapido":
            for trozo in _trocear(markdown):
                await mensaje.reply_text(trozo)
            return

        ruta = await asyncio.to_thread(guardar, markdown, adjunto.nombre)

    with ruta.open("rb") as fichero:
        await mensaje.reply_document(
            fichero,
            filename=ruta.name,
            caption=(
                f"✅ Listo: {datos['bloques_procesados']} bloque(s), "
                f"{datos['llamadas']} llamadas al modelo."
            ),
        )


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
    #
    # BOTONES y no texto (31/07): en la CLI /historial SIEMPRE dejo abrir la
    # conversacion elegida (mostrar_conversacion), y aqui solo la listaba.
    # Eso es justo lo que rompia el principio del 28/07 -un estado
    # COMPARTIDO necesita OPERACIONES SIMETRICAS-: las charlas de la
    # terminal si estaban ahi, pero desde el movil no habia forma de
    # llegar a ellas, y eso hacia PARECER que la memoria no se compartia.
    botones = []
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
        botones.append([InlineKeyboardButton(
            f"{candado} {fecha} — {nombre}"[:60],
            callback_data=f"{_PREFIJO_VER}{ruta.name}",
        )])

    if not botones:
        await mensaje.reply_text("No hay ninguna conversación que pueda listar.")
        return

    total = len(rutas)
    cabecera = f"Tus últimas {len(lineas)} conversaciones (de {total}). Toca una para leerla:"
    await mensaje.reply_text(cabecera, reply_markup=InlineKeyboardMarkup(botones))


def _formatear_conversacion(datos: dict) -> str:
    """Pasa una conversacion cargada a texto legible en el chat.

    Funcion PURA: no toca disco ni descifra (eso lo hace
    cargar_conversacion). Igual que mostrar_conversacion en la CLI, se salta
    historial[0] porque es el SYSTEM PROMPT: no es parte de lo que se dijo,
    y ademas ensuciaria la lectura con las instrucciones internas.
    """
    lineas = []
    for entrada in datos.get("historial", [])[1:]:
        quien = "🙋 Tú" if entrada.get("role") == "user" else "🤖 Jimmy"
        lineas.append(f"{quien}: {entrada.get('content', '')}")
    return "\n\n".join(lineas) if lineas else "(esta conversación está vacía)"


async def _ejecutar_guardar(user_id: int, mensaje, nombre: str) -> None:
    """El nucleo de "ponerle nombre a la charla en curso", sin importar de
    DONDE vino el nombre (argumento de /guardar, o mensaje siguiente al
    pulsar el boton en /comandos). Ojo a la diferencia con la CLI: por
    Telegram el guardado ya es automatico despues de cada turno, asi que
    esto no sirve para no perder nada -eso ya esta cubierto- sino para
    ETIQUETAR la charla y poder reconocerla luego en /historial."""
    nombre = nombre.strip()
    if not nombre:
        await mensaje.reply_text("Escribe el nombre; no puede quedar vacío.")
        return
    if len(nombre) > _MAX_NOMBRE:
        await mensaje.reply_text(f"El nombre es muy largo (máximo {_MAX_NOMBRE}).")
        return

    async with _cerrojo_de(user_id):
        ruta = await asyncio.to_thread(_persistir, user_id, nombre)

    if ruta is None:
        await mensaje.reply_text("Todavía no hemos hablado de nada que guardar.")
    else:
        await mensaje.reply_text(f'Guardada como "{nombre}".')


async def cmd_guardar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/guardar <nombre>: el nombre llega como argumento del comando
    ("/guardar ideas de tools"). context.args son las palabras que lo
    siguen (PTB las parte). Ver _guardar_con_texto para la version por
    boton, que pide el nombre en el mensaje SIGUIENTE."""
    usuario = update.effective_user
    mensaje = update.effective_message
    if usuario is None or mensaje is None:
        return

    nombre = " ".join(context.args).strip() if context.args else ""
    if not nombre:
        await mensaje.reply_text(
            "Escribe el nombre después del comando, por ejemplo:\n"
            "/guardar ideas de herramientas"
        )
        return
    await _ejecutar_guardar(usuario.id, mensaje, nombre)


async def _ejecutar_recuerdo(mensaje, consulta: str) -> None:
    """El nucleo de "buscar a mano en la memoria y enseñar lo que hay, en
    crudo", sin importar de DONDE vino la busqueda. Peticion de Jordi
    (28/07): el agente ya decide solo cuando usar buscar_en_recuerdos, pero
    esa decision la toma EL MODELO y a veces no la toma -contesto "no lo
    tengo guardado" teniendo el dato indexado-. Esto salta al modelo entero.

    Ademas es la herramienta de diagnostico que ya sirvio una vez: con esto,
    el bug de "el bot no indexaba al arrancar" se habria visto en 10
    segundos en vez de deducirlo del log."""
    consulta = consulta.strip()
    if not consulta:
        await mensaje.reply_text("Dime qué busco; no puede quedar vacío.")
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

    # Un TURNO por resultado (02/08). El 02/08 este comando devolvio 5 de 5
    # PREGUNTAS de Jordi y ninguna respuesta: encontrar la pregunta sin lo
    # que se contesto no servia de nada, y ademas parecia que la memoria
    # estaba rota cuando el dato estaba guardado.
    lineas = []
    for recuerdo in resultados:
        fecha = (recuerdo.get("fecha") or "")[:10]
        partes = []
        if recuerdo.get("pregunta"):
            partes.append(f"[{fecha}] tú: {recuerdo['pregunta']}")
        if recuerdo.get("respuesta"):
            partes.append(f"yo: {recuerdo['respuesta']}")
        lineas.append("\n".join(partes))

    # Se trocea igual que una respuesta normal: un recuerdo largo puede
    # pasarse del limite de Telegram.
    for trozo in _trocear("Esto es lo que tengo:\n\n" + "\n\n".join(lineas)):
        await mensaje.reply_text(trozo)


async def cmd_recuerdo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/recuerdo <texto>: la busqueda llega como argumento del comando. Ver
    _recuerdo_con_texto para la version por boton, que la pide en el
    mensaje SIGUIENTE."""
    mensaje = update.effective_message
    if mensaje is None:
        return

    consulta = " ".join(context.args).strip() if context.args else ""
    if not consulta:
        await mensaje.reply_text(
            "Dime qué quieres que busque, por ejemplo:\n/recuerdo el chiste del plato"
        )
        return
    await _ejecutar_recuerdo(mensaje, consulta)


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
# 31/07, probando en real: al cerrar con "guardar", Jordi esperaba poder
# ponerle nombre ahi mismo y no podia - el nombre solo se pone ANTES con
# "/guardar <nombre>", que es justo cuando nadie se acuerda de ponerlo.
_NOMBRAR = "salir:nombrar"

# Usuarios a los que se les ha PEDIDO algo por escrito: el valor dice QUE
# accion esta pendiente ("salir_nombrar", "guardar" o "recuerdo"), y se
# atiende con el mensaje SIGUIENTE (ver manejar_mensaje).
#
# Es una maquina de estados minima, y el 28/07 se decidio NO tener ninguna.
# Lo que cambia hoy: entonces habria hecho falta una maquina GENERAL (cada
# comando pidiendo datos en varios pasos con su propia logica); esto es UN
# solo diccionario para las TRES peticiones de texto que hay hoy, cada
# estado dura UN mensaje y se SUELTA SIEMPRE - manejar_mensaje lo saca
# (.pop()) antes de procesar, asi que un fallo dentro no puede dejarlo
# atascado. Los comandos no caen aqui (los CommandHandler van registrados
# antes que el handler de texto), asi que siempre hay salida: /ayuda,
# /limpiar o cualquier otro corta el paso.
_esperando_texto: dict[int, str] = {}


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
        [InlineKeyboardButton("💾 Guardar con un nombre", callback_data=_NOMBRAR)],
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
# Abrir una conversacion guardada desde /historial (31/07). Usa la MISMA
# allowlist que /borrar (_conversacion_valida): el nombre del fichero viaja
# a Telegram y vuelve, asi que tampoco aqui se concatena para formar una
# ruta - aunque leer sea menos grave que borrar, "h:../../.env" leeria la
# configuracion entera y la escupiria por el chat.
_PREFIJO_VER = "h:"
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
# F5.5 #8: los dos interruptores de /voz. Mismo patron de conmutar-y-
# redibujar que /tools.
_PREFIJO_VOZ = "v:"
_MITADES_VOZ = ("escuchar", "hablar")

# Caracteres especiales del Markdown "legacy" de Telegram (NO MarkdownV2,
# que exige escapar muchos mas). "\\" va primero: si se escapara despues de
# los demas, escaparia tambien las barras que ya hemos metido nosotros.
_MARKDOWN_ESPECIALES = ("\\", "_", "*", "`", "[")


def _escapar_markdown(texto: str) -> str:
    """Deja un texto libre listo para ir DENTRO de *negrita* sin romper el
    parseo de Telegram.

    Hace falta porque el titulo de cada grupo de /tools -> "ver sitios" lo
    escribe Jordi a mano en el .env (el texto tras el "#" de cada bloque),
    y un "_" sin escapar ahi dentro abriria una cursiva a medias: Telegram
    rechaza el mensaje ENTERO con un error de parseo en vez de mostrarlo.
    No es SEG-07 (esto no es contenido ajeno que pueda dar ordenes, es tuyo
    propio) - es solo que el formato de Telegram es fragil con estos
    caracteres, venga de donde venga el texto.
    """
    for caracter in _MARKDOWN_ESPECIALES:
        texto = texto.replace(caracter, "\\" + caracter)
    return texto


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


def _teclado_voz(user_id: int) -> InlineKeyboardMarkup:
    """Los dos interruptores de la voz, con su estado a la vista."""
    activas = _voz_activa.get(user_id, set())
    etiquetas = {
        "escuchar": "🎙️ escuchar — transcribir tus notas de voz",
        "hablar": "🔊 hablar — contestarte con una nota de voz",
    }
    filas = [
        [InlineKeyboardButton(
            f"{'✅' if mitad in activas else '⬜'} {etiquetas[mitad]}"[:60],
            callback_data=f"{_PREFIJO_VOZ}{mitad}",
        )]
        for mitad in _MITADES_VOZ
    ]
    filas.append([InlineKeyboardButton("⬅ Cerrar", callback_data=_CANCELAR)])
    return InlineKeyboardMarkup(filas)


def _texto_voz(user_id: int) -> str:
    """El texto que acompaña al menu de /voz.

    Aqui es donde vive el aviso de privacidad, y esta puesto a proposito en
    el sitio donde se toma la decision -no en el README, no en /ayuda, no
    en un log-. Encender "escuchar" teniendo esto delante ES el
    consentimiento informado: pedir ADEMAS un boton de confirmacion en la
    primera nota seria la friccion sin seguridad que ya se quito a
    `documentos` el 31/07.

    Ademas dice si "hablar" puede funcionar de verdad ANTES de encenderlo:
    un interruptor que se enciende y luego falla en cada respuesta es peor
    que uno que avisa de lo que le falta.
    """
    from src.voz import motivo_no_disponible

    lineas = [
        "*Voz* — dos interruptores independientes:\n",
        "🎙️ *escuchar*: transcribo tus notas de voz. Para eso el audio "
        "*sale de esta máquina* y va a Groq (Whisper). Ojo con esto: tu voz "
        "es un dato *biométrico* — identifica a la persona que habla, no "
        "solo lo que dice. Apagado, tus notas de voz no salen de Telegram.\n",
        "🔊 *hablar*: te contesto además con una nota de voz. Esto es "
        "*local* (Piper): no sale nada de la máquina, no gasta cuota y no "
        "necesita clave.\n",
    ]
    motivo = motivo_no_disponible()
    if motivo:
        lineas.append(f"⚠️ Ahora mismo no puedo hablar: {_escapar_markdown(motivo)}\n")
    activas = _voz_activa.get(user_id, set())
    lineas.append(
        "Encendido: " + ", ".join(sorted(activas)) if activas else "Los dos apagados."
    )
    return "\n".join(lineas)


async def cmd_voz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """F5.5 #8. Solo existe en Telegram: una terminal no reproduce audio
    (ADR-006 - el canal cambia la viabilidad, no el riesgo)."""
    usuario = update.effective_user
    mensaje = update.effective_message
    if usuario is None or mensaje is None:
        return
    await mensaje.reply_text(
        _texto_voz(usuario.id),
        parse_mode="Markdown",
        reply_markup=_teclado_voz(usuario.id),
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
    # "Guardar con un nombre": no cierra todavia - pide el nombre y espera
    # al siguiente mensaje de texto (ver _esperando_texto y manejar_mensaje).
    # /condensar: el formato vuelve dentro del callback_data, o sea que es
    # un dato que ha viajado a Telegram y ha vuelto - NO ES DE FIAR. Se
    # valida contra FORMATOS antes de usarlo, igual que el modelo y el
    # proveedor se validan contra el catalogo (F5.2+). Aqui el daño de no
    # hacerlo seria menor que en /borrar, pero la regla es la misma: lo que
    # vuelve de fuera se comprueba contra una lista nuestra, siempre.
    if dato.startswith("condensar:"):
        from src.resumen_largo import FORMATOS

        elegido = dato.split(":", 1)[1]
        if elegido == "cancelar":
            await consulta.edit_message_text("Vale, no toco nada.")
            return
        if elegido not in FORMATOS:
            logging.warning("Telegram: formato de condensado no valido")
            await consulta.edit_message_text("No reconozco esa opción.")
            return
        await consulta.edit_message_text(
            "📄 Resumen completo, marchando." if elegido == "completo"
            else "⚡ Resumen rápido, marchando."
        )
        await _condensar_con_formato(update, elegido)
        return

    if dato == _NOMBRAR:
        if usuario.id not in _rutas:
            await consulta.edit_message_text("Ya no hay ninguna conversación abierta.")
            return
        _esperando_texto[usuario.id] = "salir_nombrar"
        await consulta.edit_message_text(
            "Escríbeme el nombre para esta conversación (el siguiente mensaje "
            "lo tomaré como el nombre).\n\n"
            "Si prefieres dejarlo, usa cualquier comando —por ejemplo /ayuda— "
            "y no toco nada."
        )
        return

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

    # /historial: abrir y LEER una conversacion guardada.
    #
    # Va antes que "b:" por claridad, no por necesidad ("h:" y "b:" no
    # chocan). Se valida por la MISMA allowlist que /borrar y NO se crea
    # ningun Agente: leer el pasado no necesita LLM.
    #
    # Lo que SI hace es DESCIFRAR y mandar el contenido al chat. Eso es una
    # decision consciente: es tu conversacion y va a tu movil, pero Telegram
    # no es cifrado de extremo a extremo (limite ya declarado en E1), asi
    # que pasa por sus servidores. Lo que NO hace es mandarlo al PROVEEDOR
    # del LLM - "leer" y "retomar como contexto" son cosas distintas, y la
    # segunda si tendria ese coste.
    if dato.startswith(_PREFIJO_VER):
        nombre = dato[len(_PREFIJO_VER):]
        ruta = await asyncio.to_thread(_conversacion_valida, nombre)
        if ruta is None:
            await consulta.edit_message_text("Esa conversación ya no existe.")
            return
        try:
            datos = await asyncio.to_thread(cargar_conversacion, ruta)
        except ConversacionNoDescifrable as error:
            # Mensaje util: si falta CONVERSATIONS_KEY, el fichero esta ahi
            # pero es ilegible, y hay que saber por que.
            await consulta.edit_message_text(f"⚠️ {error}")
            return
        except Exception as error:
            logging.error("Telegram: fallo al abrir conversacion (%s)", type(error).__name__)
            await consulta.edit_message_text("⚠️ No he podido abrir esa conversación.")
            return

        texto = _formatear_conversacion(datos)
        # SIN parse_mode a proposito: el nombre y el contenido son texto que
        # escribio un humano (o el modelo), y un "*" suelto romperia el
        # mensaje entero - el mismo fallo que ya hubo el 30/07 con los
        # titulos de la lista de dominios.
        meta_nombre = datos.get("nombre") or "(sin nombre)"
        await consulta.edit_message_text(f"📖 {meta_nombre}")
        mensaje_origen = update.effective_message or consulta.message
        if mensaje_origen is None:  # defensa: sin mensaje no hay donde escribir
            return
        for trozo in _trocear(texto):
            await mensaje_origen.reply_text(trozo)
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

    # /comandos, plano (rediseño del 31/07 - ver el comentario de
    # _CATALOGO). Va arriba con /salir y la voz: navegar el menu no
    # necesita ningun Agente vivo por si mismo (las acciones "directo" que
    # SI lo necesitan lo crean ELLAS, dentro de su propia funcion).
    if dato.startswith(_PREFIJO_MENU):
        nombre = dato[len(_PREFIJO_MENU):]
        # Dato NO confiable (viaja a Telegram y vuelve): se valida contra el
        # catalogo real antes de usarlo. Sin esto, un callback fabricado a
        # mano provocaria un KeyError.
        entrada = _CATALOGO_POR_NOMBRE.get(nombre)
        if entrada is None:
            await consulta.edit_message_text("Ese comando ya no existe.")
            return
        _nombre, _descripcion, tipo = entrada

        if tipo == "info":
            await consulta.edit_message_text(_INFO_DOCUMENTO, parse_mode="Markdown")
            return

        if tipo == "texto":
            _esperando_texto[usuario.id] = nombre
            await consulta.edit_message_text(_PETICIONES_TEXTO[nombre])
            return

        # "directo": reutiliza EL PROPIO comando (cmd_historial, cmd_tools,
        # cmd_voz...). Funciona sin duplicar nada porque, en un
        # CallbackQuery de VERDAD, la propiedad Update.effective_message de
        # PTB ya resuelve al mensaje del boton cuando no hay update.message
        # -verificado en su codigo fuente-, exactamente igual que si el
        # usuario hubiera escrito el comando a mano. No se llama
        # consulta.edit_message_text aqui: la accion manda SU PROPIA
        # respuesta (una lista, un menu con sus botones, etc.).
        await _ACCIONES_DIRECTAS[nombre](update, context)
        return

    # F5.5 #8: conmutar una mitad de la voz y REDIBUJAR el menu. Va aqui
    # arriba, ANTES de _agente_de(), por el mismo motivo que /salir: la
    # preferencia de voz no necesita ningun Agente vivo, y crear uno solo
    # por tocar un boton leeria la API key (y fallaria con
    # ClaveApiNoConfigurada si faltara) sin ninguna necesidad.
    if dato.startswith(_PREFIJO_VOZ):
        mitad = dato[len(_PREFIJO_VOZ):]
        # El callback_data vuelve de Telegram: dato NO confiable. Se valida
        # contra la lista real antes de tocar nada, igual que el modelo, el
        # proveedor y las categorias de /tools. Sin esto, un callback
        # fabricado a mano meteria cualquier cadena en el conjunto.
        if mitad not in _MITADES_VOZ:
            await consulta.edit_message_text("Ese interruptor no existe.")
            return
        async with _cerrojo_de(usuario.id):
            activas = _voz_activa.setdefault(usuario.id, set())
            if mitad in activas:
                activas.discard(mitad)
            else:
                activas.add(mitad)
        await consulta.edit_message_text(
            _texto_voz(usuario.id),
            parse_mode="Markdown",
            reply_markup=_teclado_voz(usuario.id),
        )
        return

    if dato == _CANCELAR:
        await consulta.edit_message_text("Vale, no toco nada.")
        return

    agente = _agente_de(usuario.id)

    # Lista blanca de sitios, sin salir del menu de /tools.
    if dato == _VER_SITIOS:
        from src.config import obtener_dominios_agrupados

        agrupados = obtener_dominios_agrupados()
        if agrupados:
            bloques = ["Puedo leer estos sitios (copia y pega la dirección):\n"]
            for grupo, doms in agrupados.items():
                # El titulo del grupo lo escribe Jordi libremente en el .env
                # (el texto que va tras el "#"). Se escapa antes de meterlo
                # entre *asteriscos*: en el Markdown "legacy" de Telegram,
                # un "_" sin escapar dentro del texto rompe el parseo y
                # Telegram devuelve error en vez del mensaje - un titulo
                # como "Nivel_1" bastaria para tumbar la respuesta entera.
                titulo = _escapar_markdown(grupo)
                # URL completa y una por linea, igual que en la CLI (31/07):
                # `resumir_url` no busca, necesita la direccion exacta, asi
                # que una lista de dominios sueltos obliga a reescribirlos a
                # mano y acaba mirandose pero no usandose.
                urls = "\n".join(f"https://{d}/" for d in doms)
                bloques.append(f"📌 *{titulo}*:\n{urls}\n")
            texto = (
                "\n".join(bloques)
                + "(se añaden en DOMINIOS_PERMITIDOS_WEB del .env)\n"
                + "(si alguna redirige, pídeme la dirección final: no sigo redirecciones)"
            )
        else:
            texto = (
                "⚠️ No hay ningún sitio autorizado, así que no puedo leer "
                "ninguna web. Añádelos a DOMINIOS_PERMITIDOS_WEB en el .env."
            )
        await consulta.edit_message_text(
            texto, reply_markup=_teclado_tools(agente), parse_mode="Markdown"
        )
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


# A que funcion llama cada boton "directo" del menu de /comandos. Va AQUI
# abajo (y no junto a _CATALOGO) porque necesita que cmd_historial,
# cmd_tools... ya esten definidas - un dict a nivel de modulo se evalua al
# cargar el fichero, no puede usar nombres que todavia no existen.
_ACCIONES_DIRECTAS = {
    "historial": cmd_historial,
    "borrar": cmd_borrar,
    "resumen": cmd_resumen,
    "limpiar": cmd_limpiar,
    "cerrar": cmd_salir,
    "condensar": cmd_condensar,
    "voz": cmd_voz,
    "tools": cmd_tools,
    "modelo": cmd_modelo,
    "proveedor": cmd_proveedor,
}

# Invariante que un test comprueba: TODA entrada "directo" del catalogo debe
# tener accion aqui, y viceversa. Si se añade un comando "directo" nuevo y
# se olvida esta linea, _ACCIONES_DIRECTAS[nombre] petaria con KeyError la
# primera vez que alguien pulsara el boton - mejor que lo diga un test.


# --- Arranque --------------------------------------------------------------


async def _publicar_comandos(aplicacion: Application) -> None:
    """Registra los comandos en Telegram para que salga el BOTON DE MENU.

    Un fallo aqui NO impide arrancar: el bot funciona igual escribiendo los
    comandos a mano, asi que quedarse sin bot por no poder pintar un menu
    seria cambiar algo importante por algo cosmetico. Se registra y se
    sigue, igual que con el guardado de una conversacion.
    """
    try:
        await aplicacion.bot.set_my_commands(comandos_para_telegram())
    except Exception as error:
        logging.warning(
            "Telegram: no se pudo publicar el menu de comandos (%s)", type(error).__name__
        )


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
        # post_init: PTB lo llama UNA vez, ya con el bot conectado y antes
        # de empezar a recibir updates. Es el sitio de set_my_commands - en
        # construir_aplicacion() a secas no valdria, porque aqui todavia no
        # hay red y los tests montan la Application sin token de verdad.
        aplicacion = ApplicationBuilder().token(token).post_init(_publicar_comandos).build()
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
    aplicacion.add_handler(TypeHandler(Update, puerta_soltar_espera), group=-1)

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
    # "salir" se mantiene como ALIAS y no se borra: llevas dias escribiendolo
    # y el bot no debe contestarte "no conozco ese comando" por un cambio de
    # nombre nuestro. No se anuncia en el menu (no esta en _CATALOGO), asi
    # que quien empiece hoy solo aprende /cerrar.
    aplicacion.add_handler(CommandHandler(["cerrar", "salir"], cmd_salir))
    aplicacion.add_handler(CommandHandler("borrar", cmd_borrar))
    aplicacion.add_handler(CommandHandler("tools", cmd_tools))
    aplicacion.add_handler(CommandHandler("voz", cmd_voz))
    aplicacion.add_handler(CommandHandler("condensar", cmd_condensar))
    # Los botones de /modelo y /proveedor vuelven como CallbackQuery. Pasan
    # por la allowlist igual que todo lo demas (TypeHandler del grupo -1).
    aplicacion.add_handler(CallbackQueryHandler(manejar_boton))
    # Cualquier otro comando: responde en vez de desaparecer.
    aplicacion.add_handler(MessageHandler(filters.COMMAND, cmd_desconocido))

    aplicacion.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    # F5.5 #7: filters.Document.ALL va ANTES que el generico ~filters.TEXT -
    # PTB entrega el update al primer handler cuyo filtro encaje, asi que
    # el orden de alta decide cual de los dos coge un documento adjunto.
    aplicacion.add_handler(MessageHandler(filters.Document.ALL, manejar_documento))
    # F5.5 #8: igual que el de documentos, filters.VOICE va ANTES del
    # generico ~filters.TEXT o las notas de voz seguirian cayendo en
    # manejar_no_texto ("de momento solo entiendo texto").
    aplicacion.add_handler(MessageHandler(filters.VOICE, manejar_voz))
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
    # CERROJO ENTRE PROCESOS - lo PRIMERO de todo (01/08, ver src/cerrojo.py).
    #
    # Va antes de construir la Application, antes de indexar y antes de
    # hablar con Telegram: si no somos los unicos, no queremos haber tocado
    # NADA. Indexar ya escribe en el indice de ChromaDB, que es justo el
    # fichero que estamos protegiendo.
    #
    # Deja de ser un aviso por pantalla y pasa a IMPEDIRLO porque el aviso
    # no funciono: el 31/07 Jordi ejecuto la CLI con el bot arrancado, y el
    # 01/08 llego a haber DOS bots a la vez. Un aviso que se lee despues de
    # arrancar no evita nada.
    try:
        cerrojo = CerrojoMemoria(quien="bot de Telegram").tomar()
    except MemoriaOcupada as error:
        print(f"⛔ {error}")
        return

    try:
        _arrancar(cerrojo)
    finally:
        cerrojo.soltar()


def _arrancar(cerrojo) -> None:
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
        "Mientras yo esté vivo, la CLI y otro bot NO podrán arrancar: "
        "tengo cogido el cerrojo."
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
