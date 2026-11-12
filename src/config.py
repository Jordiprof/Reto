# logging: modulo estandar de Python para registrar eventos (errores,
# informacion) en un fichero permanente, en vez de solo con print()
# que desaparece al cerrar la terminal.
# RotatingFileHandler: variante de logging que corta el fichero al llegar
# a un tamaño y se queda solo con las N copias mas recientes (F5.2, ver
# mas abajo el porque).
import hashlib
import logging
import os
import re

# secrets: generador criptograficamente seguro (no "random", que es
# predecible). Se usa para la sal del hash de identificadores en el log.
import secrets
from logging.handlers import RotatingFileHandler

# pathlib.Path: forma moderna de manejar rutas de ficheros/carpetas.
# Funciona igual en Windows, Linux y Mac (evita liarte con "\" vs "/").
from pathlib import Path

# dotenv: libreria externa (python-dotenv, instalada con pip) que sabe
# leer el fichero .env (texto plano tipo CLAVE=valor) y meter esas
# lineas dentro de las variables de entorno del sistema (os.environ).
from dotenv import load_dotenv

# Ejecuta la carga: busca el .env en la raiz del proyecto y mete sus
# variables en el entorno. A partir de aqui, os.environ ya las tiene.
load_dotenv()

# __file__ es la ruta de este mismo fichero (config.py). .resolve()
# la convierte en ruta absoluta. .parent sube un nivel de carpeta;
# lo hacemos dos veces (src/ -> raiz del proyecto) y le añadimos "logs".
LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
# Crea la carpeta logs/ si no existe. exist_ok=True evita que de error
# si la carpeta ya estaba creada de antes.
LOGS_DIR.mkdir(exist_ok=True)

# Configura el sistema de logging global del programa.
#
# F5.2 (27/07): antes era basicConfig(filename=...), que escribe sin limite
# - el fichero solo crecia (117 KB y subiendo). Con el bot 24/7 de F5.2 eso
# se dispara, y un tope duro ademas hace que cualquier linea que se cuele
# mal (un dato sensible por error) CADUQUE SOLA en vez de quedarse para
# siempre. RotatingFileHandler corta al llegar a maxBytes y se queda con
# backupCount copias antiguas (agente.log, agente.log.1, agente.log.2,
# agente.log.3) - tope total de unos 4 MB.
#
# encoding="utf-8" no es cosmetico: sin el, Windows usa cp1252 por defecto
# y el programa loguea "⚠️" (ver main.py) - revienta o escribe simbolos
# rotos. Gotcha real: basicConfig NO acepta "filename" y "handlers" a la
# vez (lanza ValueError), por eso se sustituye entero en vez de añadir.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        RotatingFileHandler(
            LOGS_DIR / "agente.log",
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
            # delay=True: no abre el fichero al importar config.py, sino
            # en el primer mensaje. En uso normal no cambia nada (el
            # primer log llega enseguida), pero evita dejar un agente.log
            # vacio cada vez que se importa el modulo sin llegar a
            # loguear - por ejemplo, en la bateria de tests.
            delay=True,
        )
    ],
)

# httpx (usado por Ollama/Gemini por debajo) loguea cada peticion HTTP con
# su URL en cuanto el nivel es INFO - no es un dato de JIM, pero es ruido
# que compite con las lineas de auditoria de _ejecutar_tool y engorda la
# rotacion de arriba sin aportar nada.
logging.getLogger("httpx").setLevel(logging.WARNING)

# Nombre de la variable de entorno donde vive la CLAVE de cada proveedor.
# Solo guardamos el NOMBRE de la variable, no el valor - el valor se lee
# mas tarde, solo del proveedor que se elija (lectura perezosa - leccion
# del diario del 16/07: cargar todo de golpe rompe si falta una clave
# que ni se iba a usar).
#
# EL ORDEN DE ESTE DICCIONARIO ES LA PREFERENCIA OFICIAL DE ADR-001, y no
# es decorativo: de el salen las TRES cosas a la vez -el orden del menu de
# la CLI (o sea con cual arranca Jordi si da a Enter), el proveedor con el
# que arranca el bot de Telegram, y la cadena de fallback del router-.
#
# Se hizo asi el 03/08, al reordenarlo: antes "groq primero" estaba escrito
# a mano en tres sitios distintos y cambiar la decision obligaba a acordarse
# de los tres. Misma leccion que la lista de dominios del 30/07, donde
# obtener_dominios_agrupados() duplicaba el parseo: una sola fuente de
# verdad, y las demas derivan.
#
# El POR QUE del orden (cuota y calidad, con numeros medidos) esta en
# llm_router._ORDEN_ADR001, que es quien lo consume para el fallback.
PROVEEDORES = {
    "ollama": "OLLAMA_API_KEY",
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
}

# Modelos de RESERVA dentro de un mismo proveedor: a estos se degrada antes
# de cambiar de proveedor entero (03/08, idea de Jordi). El porque y la
# medicion que lo respalda estan en llm_router._reservas_del_mismo_proveedor.
#
# Resumen: en Groq el cupo es POR MODELO -verificado con las cabeceras
# x-ratelimit-* de la API, no leido en la documentacion-, asi que quedarse
# sin llama-3.3 no deja sin gpt-oss-120b. Y gpt-oss-120b tiene el DOBLE de
# cuota diaria (200.000 tokens/dia contra 100.000).
#
# Solo Groq: en Ollama y Gemini no esta medido, y un eslabon de mas cuesta
# una llamada tirada cuando el proveedor cae por algo que no sea cuota.
# El ORDEN es la cadena: llama-3.3 -> gpt-oss-120b -> qwen3.6-27b (decision
# de Jordi, 04/08: llama-3.3 se queda de titular y los otros dos entran por
# ese orden). Los tres verificados en vivo el 04/08.
MODELOS_DE_RESERVA = {
    "groq": ["openai/gpt-oss-120b", "qwen/qwen3.6-27b"],
}

# Nombre de la variable de entorno con el modelo POR DEFECTO de cada
# proveedor. F5.0/T5: hasta ahora estas variables (GROQ_MODEL, etc.) estaban
# en .env.example pero NADIE las leia - config.py ignoraba el modelo del
# .env y usaba solo las listas de MODELOS. Eso contradecia la decision del
# diario (15/07): "el modelo es configuracion, vive en .env". Ahora SI se
# leen (ver obtener_modelo_por_defecto): son la FUENTE DE VERDAD del modelo
# por defecto. Las listas MODELOS pasan a ser SOLO el catalogo del menu.
MODELOS_ENV = {
    "groq": "GROQ_MODEL",
    "ollama": "OLLAMA_MODEL",
    "gemini": "GEMINI_MODEL",
}

# Catalogo de modelos por proveedor para el MENU interactivo (/modelo).
# Nombres EXACTOS, verificados con llamadas reales el 16-17/07 y
# RE-verificados el 23/07 (F5.0/T5) contra las APIs en vivo (scripts/lista_
# modelos_*.py) al activar por fin la lectura de *_MODEL del .env - asi se
# encontro que "qwen/qwen3-32b" (Groq) ya no existe y que Ollama Cloud dejo
# de usar el sufijo "-cloud"/":cloud" en sus 6 modelos (mismo hallazgo,
# nuevo ejemplo de la leccion del 15/07: verificar SIEMPRE en fuentes
# oficiales, los catalogos tambien caducan, no solo lo que dicen los LLM).
# El primero de cada lista es el fallback si la variable *_MODEL no esta en
# el .env.
MODELOS = {
    # Groq: 3 modelos verificados en vivo el 23/07 (se retira "qwen3-32b",
    # ya no existe en la API - la version "qwen3.6-27b" sigue viva).
    # AMPLIADO el 04/08 a peticion de Jordi, con los 7 verificados en vivo
    # ese mismo dia (HTTP 200 real, no leidos de una lista).
    #
    # De los 14 que ofrece Groq solo estos SIRVEN PARA CHATEAR. Los otros 7
    # se quedan fuera a proposito y conviene saber por que, para no volver a
    # mirarlo: `canopylabs/orpheus-*` son sintesis de voz, `whisper-large-*`
    # son transcripcion (esos SI se usan, pero desde voz.py y a dedo), y
    # `meta-llama/llama-prompt-guard-2-*` y `openai/gpt-oss-safeguard-20b`
    # son CLASIFICADORES DE SEGURIDAD: devuelven una etiqueta de riesgo, no
    # una conversacion. Meterlos en el menu seria ofrecer modelos que no
    # pueden responder.
    "groq": [
        "llama-3.3-70b-versatile",  # titular (decision de Jordi, 04/08)
        "openai/gpt-oss-120b",      # 1ª reserva: DOBLE cuota diaria (200k/dia)
        "qwen/qwen3.6-27b",         # 2ª reserva. OJO: escribe su razonamiento en <think>
        "openai/gpt-oss-20b",       # hermano pequeño del 120b, misma cuota diaria
        "llama-3.1-8b-instant",     # el mas rapido y barato en tokens
        "groq/compound",            # sistema con herramientas propias de Groq
        "groq/compound-mini",       # la version ligera del anterior
    ],
    # Ollama Cloud: los mismos 6 modelos probados el 16-17/07, RENOMBRADOS
    # el 23/07 (la API quito el sufijo "-cloud"/":cloud" - mismo modelo,
    # nombre distinto). Se descartaron por error 403 (piden suscripcion
    # Pro): glm-5.1, kimi-k2.6, kimi-k2.7-code, deepseek-v4-flash, qwen3.5
    # y qwen3.5:397b.
    # RETIRADO el 31/07/2026 y quitado de aqui el 01/08: "minimax-m2.5"
    # devolvia HTTP 410 con el mensaje "was retired at 2026-07-31". Se
    # descubrio porque Jordi lo eligio en el menu y TODOS sus mensajes
    # cayeron al fallback. Es el aviso del diario cumpliendose sobre este
    # mismo repo: un catalogo de modelos NO es una constante, envejece solo
    # y sin avisar. Los otros cinco se reverificaron ese dia, uno a uno y
    # con llamada real (con tools y sin tools): los cinco responden.
    # Comprobado en vivo el 01/08 al buscarle sustituto: "minimax-m2.7" y
    # "minimax-m2.7:cloud" dan 403 ("this model requires a subscription"),
    # asi que NO son la alternativa - caen en el mismo saco que glm-5.1 y
    # los kimi. El relevo gratuito de minimax-m2.5 es "minimax-m3", que ya
    # estaba en esta lista y responde: no hay nada que añadir.
    # AUDITADO EL CATALOGO ENTERO el 01/08 contra la lista oficial de
    # modelos cloud de Ollama (ollama.com/search?c=cloud) y probando LOS 17
    # con la clave real. Resultado: 7 gratis, 9 dan 403 (piden Pro) y 3 no
    # existen. La pagina de precios NO dice cuales son gratis - solo habla
    # de "niveles"-, asi que la unica fuente fiable es la llamada real.
    # Los 6 de aqui son los gratis con soporte de tools verificado uno a uno.
    #
    # Se añade "gpt-oss:20b" (01/08): gratis, con tools, y es el "nivel 1"
    # ligero de Ollama. Interesa tenerlo a mano precisamente porque Groq se
    # queda sin cuota a menudo y este es el mas barato de la cadena.
    # QUITADO el 04/08: "qwen3.5:cloud". Llevaba en el menu desde el 23/07 y
    # NUNCA ha funcionado - devuelve HTTP 403 "this model requires a
    # subscription". Estaba anotado tres lineas mas arriba, en la lista de
    # descartados por 403, y aun asi seguia ofreciendose para elegir: la
    # nota decia una cosa y el catalogo hacia otra. Salio comprobando en
    # vivo los 7, a peticion de Jordi (que ademas pidio probar
    # `deepseek-v4-flash` en sus tres variantes: los tres 403 tambien, o
    # sea que la restriccion de Pro sigue igual que el 23/07).
    #
    # Los 6 que quedan verificados con HTTP 200 real el 04/08.
    "ollama": [
        "gpt-oss:120b",
        "gpt-oss:20b",
        "gemma4:31b",
        "minimax-m3",
        "nemotron-3-super",
        "nemotron-3-ultra",
    ],
    # Gemini: "gemini-3.0-flash" no existe (404 real) y "gemini-2.5-pro"
    # tiene cuota 0 en el free tier (429 real) - los dos descartados aposta.
    # REORDENADO el 02/08: "2.5-flash" pasa DELANTE de "3.5-flash", y no por
    # ser mejor modelo (no lo es) sino por ser el unico de los cuatro cuyos
    # limites del plan gratuito PUBLICA Google - y resultan ser los mejores
    # de todo el catalogo del proyecto:
    #
    #   gemini-2.5-flash : 250.000 tokens/minuto · 250 peticiones/dia
    #   llama-3.3-70b    :  12.000 tokens/minuto
    #   gpt-oss-120b     :   8.000 tokens/minuto
    #
    # Veinte veces mas cuota por minuto que Groq. Eso es lo que hace posible
    # resumir un documento de 300 hojas (~81.000 tokens): en Groq ni siquiera
    # cabe la peticion, y aqui sobra sitio. De "3.5-flash" y
    # "3.1-flash-lite" Google ya NO publica los limites del free tier
    # (remite a AI Studio, que depende de la cuenta), asi que no se puede
    # decidir con ellos - misma lección que Ollama el 01/08: si no publican
    # el numero, no se puede planificar con el.
    "gemini": [
        "models/gemini-2.5-flash",       # PRIMERO: 250k tokens/min, el unico con limites publicados
        "models/gemini-3.5-flash",       # Mejor modelo, pero cuota del free tier sin publicar
        "models/gemini-3.1-flash-lite",  # El más ligero, ideal si haces muchas llamadas seguidas
        "models/gemma-4-31b-it",    # Modelo abierto de Google, sin cuotas estrictas
    ],
}


class ClaveCifradoInvalida(Exception):
    """CONVERSATIONS_KEY existe pero no es una clave Fernet valida (AUD-04).

    Distinta de "no hay clave", que es un caso LEGITIMO: el cifrado es
    opcional y sin clave se guarda en claro avisando. Esto es otra cosa -
    hay una clave y esta rota-, y ahi no se puede seguir como si nada: se
    guardaria sin cifrar creyendo que se cifra.
    """


class ClaveApiNoConfigurada(Exception):
    """La variable de entorno de la API key de este proveedor no esta en
    el .env (F5.0/T2, hallazgo AUD-06 de la auditoria del 23/07: antes esto
    lanzaba un KeyError sin capturar y el programa moria con un traceback,
    incumpliendo RNF-02 - "ante un fallo de API, el programa avisa y sigue
    vivo")."""


def obtener_api_key(proveedor: str) -> str:
    """Lee del .env solo la clave del proveedor elegido (lectura perezosa)."""
    # Busca el NOMBRE de la variable de entorno para este proveedor...
    nombre_variable = PROVEEDORES[proveedor]
    try:
        # ...y ahora si, lee su VALOR real desde las variables de entorno.
        return os.environ[nombre_variable]
    except KeyError:
        raise ClaveApiNoConfigurada(
            f"Falta configurar {nombre_variable} en tu archivo .env."
        ) from None


# F5.3: nombre de la variable con la clave de cifrado de las conversaciones
# guardadas (RNF-06). Solo el NOMBRE, igual que PROVEEDORES: el valor se lee
# tarde, cuando hace falta.
CLAVE_CONVERSACIONES_ENV = "CONVERSATIONS_KEY"


def obtener_clave_conversaciones() -> bytes | None:
    """Lee del .env la clave Fernet para cifrar las conversaciones, o
    None si no esta configurada.

    Devolver None (en vez de lanzar) es deliberado: el cifrado es
    OPCIONAL, el agente funciona sin el. Lo que NO se acepta es que la
    ausencia de clave pase desapercibida - quien llame a esto avisa
    (ver storage.guardar_conversacion y cifrado_activo).
    """
    clave = os.environ.get(CLAVE_CONVERSACIONES_ENV)
    # El "not" tambien cubre la cadena vacia (variable puesta pero sin valor).
    if not clave:
        return None

    # AUD-04 (auditoria del 23/07, cerrado el 02/08). Hasta hoy esto hacia
    # `.encode()` y ya: una clave mal escrita -un caracter de menos al
    # copiarla, un espacio, una clave de otro sitio- se reportaba como
    # "cifrado activo" y solo reventaba al INTENTAR GUARDAR, o sea al final
    # de una conversacion entera. Se comprueba al leerla, que es cuando aun
    # se puede hacer algo.
    #
    # NO se degrada a "guardar sin cifrar", que era la otra opcion: creerias
    # que tus conversaciones estan cifradas y estarian en claro en disco.
    # Ante una clave rota, el fallo tiene que ser RUIDOSO - es un error de
    # configuracion que se arregla en treinta segundos, no algo que
    # convenga tragarse.
    #
    # Se valida CONSTRUYENDO un Fernet en vez de comprobando el formato a
    # mano (44 caracteres, base64 url-safe...): la unica definicion de
    # "clave valida" que importa es la de la libreria que la va a usar, y
    # replicarla aqui seria mantener dos versiones de la misma regla.
    from cryptography.fernet import Fernet

    try:
        Fernet(clave.encode())
    except Exception as error:
        raise ClaveCifradoInvalida(
            f"{CLAVE_CONVERSACIONES_ENV} no es una clave Fernet válida. "
            "Genera una nueva con:\n"
            '  python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"\n'
            "y pégala en el .env. OJO: si ya tenías conversaciones cifradas "
            "con otra clave, con la nueva NO se podrán abrir."
        ) from error
    return clave.encode()


def obtener_modelo_por_defecto(proveedor: str) -> str:
    """Modelo por defecto del proveedor (F5.0/T5).

    Fuente de verdad: la variable del .env (GROQ_MODEL, OLLAMA_MODEL,
    GEMINI_MODEL). Si no esta puesta (o esta vacia), cae al primero del
    catalogo MODELOS - un valor verificado, para que el programa arranque
    igual sin configuracion extra.
    """
    nombre_variable = MODELOS_ENV[proveedor]
    # os.environ.get devuelve None si no existe; el "or" tambien cubre "".
    return os.environ.get(nombre_variable) or MODELOS[proveedor][0]


# F5.2 (27/07): variable que activa el modo depuracion de contenido.
# Nombre elegido A PROPOSITO para que asuste: no se llama DEBUG ni
# VERBOSE, porque alguien la encenderia creyendo que solo sube el detalle
# tecnico y acabaria escribiendo PII sin saberlo. Que el nombre sea claro
# es parte del control.
DEPURACION_ENV = "DEBUG_LOG_CONTENIDO"

# Allowlist de valores que ENCIENDEN el modo, no blacklist de los que lo
# apagan. Con blacklist, cualquier valor no previsto ("banana", un typo)
# encenderia el modo por accidente. Con allowlist, cualquier cosa que no
# sea explicitamente un "si" se queda apagada.
_VALORES_ENCENDIDO = {"1", "true", "si", "sí", "yes", "on"}


def depuracion_contenido_activa() -> bool:
    """True SOLO si la variable esta puesta a un valor afirmativo
    explicito. Apagado por defecto y apagado ante cualquier duda: ausente,
    vacia, "0", "false" o cualquier texto raro -> False. La unica forma de
    encenderlo es escribirlo a proposito en el .env."""
    return os.environ.get(DEPURACION_ENV, "").strip().lower() in _VALORES_ENCENDIDO


# R-04 (auditoria de seguridad de noviembre): consentimiento EXPLICITO para
# que el BOT arranque sin CONVERSATIONS_KEY. Sin clave, el bot -24/7, en una
# VPS, guardando la vida de alguien- se niega a arrancar; la CLI sigue con su
# aviso de siempre. Nombre largo y en español a proposito, como
# DEBUG_LOG_CONTENIDO: que nadie la encienda sin entender lo que hace.
PERMITIR_SIN_CIFRAR_ENV = "PERMITIR_CONVERSACIONES_SIN_CIFRAR"


def guardar_sin_cifrar_consentido() -> bool:
    """True SOLO con un "si" explicito en PERMITIR_CONVERSACIONES_SIN_CIFRAR.
    Misma allowlist de valores que DEBUG_LOG_CONTENIDO: ausente, vacia, "0"
    o cualquier texto raro -> False, o sea el bot no arranca sin clave."""
    return os.environ.get(PERMITIR_SIN_CIFRAR_ENV, "").strip().lower() in _VALORES_ENCENDIDO


# Logger APARTE para el modo depuracion, con su propio fichero
# (logs/debug_contenido.log). La pieza clave es propagate=False: sin ella,
# todo lo que se escriba aqui subiria al logger raiz y acabaria en
# agente.log - justo lo que este diseño impide. Con propagate=False es
# IMPOSIBLE que se cuele, no una convencion que haya que recordar. Asi
# agente.log gana una invariante comprobable: "este fichero no contiene
# contenido, nunca".
_LOGGER_DEPURACION = "agente.depuracion"
_RUTA_DEPURACION = LOGS_DIR / "debug_contenido.log"


def logger_depuracion() -> logging.Logger:
    """Devuelve el logger del modo depuracion, montando su handler la
    primera vez que se llama (perezoso: si el modo nunca se enciende,
    logs/debug_contenido.log no llega a existir).

    Se comprueba si YA existe un handler NUESTRO (RotatingFileHandler), no
    si la lista de handlers esta vacia: cualquier otra herramienta puede
    haber enganchado el suyo a este logger, y con un "if not log.handlers"
    daríamos el nuestro por montado sin estarlo - el modo depuracion se
    quedaria sin escribir en silencio. Encontrado el 27/07 al revisar: es
    justo lo que hace pytest, que engancha su handler de captura a todo
    logger con propagate=False.
    """
    log = logging.getLogger(_LOGGER_DEPURACION)
    if not any(isinstance(h, RotatingFileHandler) for h in log.handlers):
        log.propagate = False
        log.setLevel(logging.DEBUG)
        handler = RotatingFileHandler(
            _RUTA_DEPURACION, maxBytes=1_000_000, backupCount=1, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        log.addHandler(handler)
    return log


# ---------------------------------------------------------------------------
# F5.5 - Herramientas (ADR-006)
# ---------------------------------------------------------------------------
# Lista blanca de dominios que las tools tienen permiso de visitar. Es la
# mitad "editorial" del guardian de URLs (src/red_segura.py): decide en QUE
# SITIOS confia Jordi, algo que ningun programa puede deducir solo. La otra
# mitad (¿esa direccion esta en mi red?) es tecnica y va en red_segura.
DOMINIOS_WEB_ENV = "DOMINIOS_PERMITIDOS_WEB"

# Clave de api.nasa.gov. OPCIONAL: sin ella se usa DEMO_KEY, que funciona
# pero con 30 peticiones/hora y 50/dia (verificado en su doc). Con clave
# propia (gratis, por email) son 1.000/hora.
NASA_API_KEY_ENV = "NASA_API_KEY"
_NASA_CLAVE_DEMO = "DEMO_KEY"


def _normalizar_dominio(texto: str) -> str:
    """Un dominio tal y como lo compara el guardian: minusculas y sin
    'www.'. UNA sola funcion para las dos lecturas de mas abajo - antes
    cada una normalizaba por su cuenta, y dos sitios que hacen lo mismo por
    separado es donde un dia divergen sin que nadie se entere."""
    return texto.strip().lower().removeprefix("www.")


def obtener_dominios_agrupados() -> dict[str, list[str]]:
    """Dominios autorizados, agrupados por las cabeceras de comentario (#)
    que los preceden en el .env (peticion de Jordi, 30/07: ver la lista
    blanca organizada, no como una sola linea de 41 dominios).

    Formato admitido (multilinea, dentro de comillas - ver DOMINIOS_WEB_ENV
    en .env.example):
        DOMINIOS_PERMITIDOS_WEB="
          # Nivel 1: Organismos oficiales
          nasa.gov, esa.int,
          # Nivel 2: Empresas de IA
          anthropic.com, openai.com
        "
    Un comentario "# ..." abre un grupo nuevo; los dominios que le siguen
    (hasta el proximo comentario) caen dentro. Sin ningun comentario antes,
    van a "Otros dominios" - asi una lista de una sola linea (el formato de
    toda la vida) sigue funcionando sin tener que agruparla a mano.

    ESTA es la funcion que de verdad parsea el .env: obtener_dominios_
    permitidos() (mas abajo) reutiliza su resultado en vez de volver a leer
    la variable por su cuenta - una sola pasada, no dos parseos que puedan
    desincronizarse.
    """
    crudo = os.environ.get(DOMINIOS_WEB_ENV, "")
    agrupados: dict[str, list[str]] = {}
    grupo_actual = "Otros dominios"

    for linea_cruda in crudo.splitlines():
        linea = linea_cruda.strip()
        if not linea:
            continue
        if linea.startswith("#"):
            titulo = linea.lstrip("#").strip()
            if titulo:
                grupo_actual = titulo
            continue

        # El resto de la linea, quitando un comentario que viniera DETRAS
        # de dominios en la misma linea (ej. "a.com, b.com  # nota").
        sin_comentario = linea.split("#")[0].strip()
        for token in sin_comentario.split(","):
            dominio = _normalizar_dominio(token)
            if dominio and dominio not in agrupados.get(grupo_actual, []):
                agrupados.setdefault(grupo_actual, []).append(dominio)

    return {grupo: doms for grupo, doms in agrupados.items() if doms}


def obtener_dominios_permitidos() -> frozenset[str]:
    """Dominios autorizados, en minusculas y sin 'www.', SIN los grupos -
    lo que de verdad consulta el guardian (src/red_segura.py) para decidir
    si visita una URL o no.

    Devuelve un conjunto VACIO si no hay ninguno configurado, y eso es
    deliberado: quien llama (red_segura.validar_url) trata el conjunto
    vacio como "no visito nada". Falla CERRADO, igual que la lista blanca
    del bot - una lista de permitidos que al estar vacia permitiera todo
    seria un control de acceso al reves.
    """
    agrupados = obtener_dominios_agrupados()
    return frozenset(d for dominios in agrupados.values() for d in dominios)


def obtener_clave_nasa() -> str:
    """Clave de NASA, o DEMO_KEY si no hay ninguna configurada.

    Aqui SI se cae a un valor por defecto (a diferencia de los proveedores
    LLM, que lanzan): DEMO_KEY es una clave publica que la propia NASA
    ofrece para probar, asi que la tool funciona nada mas instalar el
    proyecto. Lo unico que se pierde es cuota.
    """
    return os.environ.get(NASA_API_KEY_ENV, "").strip() or _NASA_CLAVE_DEMO


# F5.5 #8 - Voz. La voz de Piper es un fichero .onnx de 63 MB que se
# descarga aparte (no lo instala pip) y vive en voces/, ignorada por git
# igual que .modelos_cache/: es un binario descargado, no codigo del
# proyecto. La variable del .env existe para poder apuntar a otra voz sin
# tocar el codigo, pero tiene un valor por defecto util para que el
# proyecto funcione recien clonado + descargada la voz recomendada.
PIPER_VOZ_ENV = "PIPER_VOZ"
_VOZ_POR_DEFECTO = "es_ES-davefx-medium.onnx"
VOCES_DIR = Path(__file__).resolve().parent.parent / "voces"


def obtener_ruta_voz() -> Path:
    """Ruta del modelo de voz de Piper.

    Devuelve la ruta AUNQUE NO EXISTA el fichero: quien llama decide que
    hacer (voz.motivo_no_disponible() la usa justo para poder decir "falta
    esto y se descarga asi"). Lanzar aqui obligaria a envolver en try cada
    sitio que solo quiere saber donde deberia estar.
    """
    configurada = os.environ.get(PIPER_VOZ_ENV, "").strip()
    if configurada:
        return Path(configurada)
    return VOCES_DIR / _VOZ_POR_DEFECTO


# ---------------------------------------------------------------------------
# F5.2 - Bot de Telegram
# ---------------------------------------------------------------------------
# Solo los NOMBRES de las variables, igual que PROVEEDORES: el valor se lee
# cuando hace falta, no al importar.
TELEGRAM_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
TELEGRAM_PERMITIDOS_ENV = "TELEGRAM_USER_IDS_PERMITIDOS"
TELEGRAM_SAL_ENV = "TELEGRAM_LOG_SAL"


class ConfiguracionTelegramInvalida(Exception):
    """Falta la configuracion del bot o esta mal escrita (F5.2).

    Es una excepcion propia, distinta de ClaveApiNoConfigurada, porque el
    tratamiento es OPUESTO: sin clave de un proveedor el programa puede
    seguir con otro (RNF-02), pero sin lista blanca el bot NO debe
    arrancar bajo ningun concepto.
    """


def obtener_token_telegram() -> str:
    """Token del bot (BotFather). Nunca se loguea ni se imprime."""
    token = os.environ.get(TELEGRAM_TOKEN_ENV, "").strip()
    if not token:
        raise ConfiguracionTelegramInvalida(
            f"Falta {TELEGRAM_TOKEN_ENV} en el .env (te lo da @BotFather en Telegram)."
        )
    return token


def obtener_usuarios_permitidos() -> frozenset[int]:
    """Lista blanca de user_id de Telegram autorizados (RNF-05, AUD-A1).

    FALLA CERRADO en todos los casos raros: si la variable no esta, esta
    vacia o contiene algo que no es un numero, LANZA. Nunca devuelve un
    conjunto vacio en silencio (dejaria el bot mudo sin explicar por que)
    y nunca interpreta la ausencia como "permitir a todos" - que es el
    modo de fallo que convierte un control de acceso en decoracion.

    Se relee en CADA update en vez de cachearse: cuesta un os.environ y
    hace que un .env roto en caliente CIERRE el bot en vez de abrirlo.
    """
    crudo = os.environ.get(TELEGRAM_PERMITIDOS_ENV, "").strip()
    if not crudo:
        raise ConfiguracionTelegramInvalida(
            f"Falta {TELEGRAM_PERMITIDOS_ENV} en el .env: el bot NO arranca sin lista blanca."
        )
    # R-10 (auditoria de seguridad de noviembre): int(t) a secas es mas
    # tolerante de lo que parece - acepta "1_0" (=10), "+5" y digitos de
    # otras escrituras ("١١١" = 111). En el control nº1 del bot, un id que
    # no es LITERALMENTE una tira de cifras se trata como lista ilegible,
    # que falla cerrado. re.ASCII porque sin el, \d tambien casa esos
    # digitos no latinos y el agujero seguiria abierto.
    trozos = [t.strip() for t in crudo.split(",") if t.strip()]
    if not all(re.fullmatch(r"\d+", t, re.ASCII) for t in trozos):
        raise ConfiguracionTelegramInvalida(
            f"{TELEGRAM_PERMITIDOS_ENV} debe ser una lista de numeros separados por comas."
        )
    permitidos = frozenset(int(t) for t in trozos)
    if not permitidos:
        raise ConfiguracionTelegramInvalida(
            f"{TELEGRAM_PERMITIDOS_ENV} no contiene ningun id valido."
        )
    return permitidos


# Sal para el hash de los user_id rechazados (ver telegram_bot._huella).
# Si no se configura una en el .env se genera una ALEATORIA por proceso.
# Eso es deliberado y es la opcion MAS privada: dentro de una misma
# ejecucion sigue distinguiendo "el mismo desconocido 40 veces" de "40
# desconocidos distintos" (que es toda la informacion operativa que hace
# falta), pero los hashes dejan de ser correlacionables entre reinicios.
# Quien quiera esa correlacion -para vigilar sondeos a lo largo de dias-
# solo tiene que fijar la variable.
_SAL_POR_PROCESO = secrets.token_bytes(16)


def obtener_sal_log() -> bytes:
    """Sal del hash de identificadores en el log. Nunca vacia: sin sal, el
    espacio de user_id de Telegram es enumerable por fuerza bruta y el
    hash no protegeria nada.

    SIEMPRE devuelve exactamente 32 bytes, pase lo que pase en el .env.
    Esto NO es cosmetico (auditoria del 27/07, hallazgo critico): blake2s
    -que es quien usa esta sal, en telegram_bot._huella- acepta claves de
    32 bytes COMO MUCHO y lanza ValueError si te pasas. Y esa excepcion
    saltaba dentro del control de acceso, ANTES de su
    ApplicationHandlerStop, con lo que la puerta dejaba pasar al
    desconocido. Una sal larga en el .env (una frase, o un token_hex(32))
    apagaba el control de acceso EN SILENCIO y solo para los no
    autorizados - imposible de notar probando con tu propia cuenta.
    Pasarla por SHA-256 la normaliza a 32 bytes exactos sea cual sea su
    longitud, asi que la excepcion ya no puede darse.
    """
    configurada = os.environ.get(TELEGRAM_SAL_ENV, "").strip()
    if not configurada:
        return _SAL_POR_PROCESO
    return hashlib.sha256(configurada.encode("utf-8")).digest()
