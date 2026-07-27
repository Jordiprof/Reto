# logging: modulo estandar de Python para registrar eventos (errores,
# informacion) en un fichero permanente, en vez de solo con print()
# que desaparece al cerrar la terminal.
# RotatingFileHandler: variante de logging que corta el fichero al llegar
# a un tamaño y se queda solo con las N copias mas recientes (F5.2, ver
# mas abajo el porque).
import logging
import os
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
PROVEEDORES = {
    "groq": "GROQ_API_KEY",
    "ollama": "OLLAMA_API_KEY",
    "gemini": "GEMINI_API_KEY",
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
    "groq": [
        "llama-3.3-70b-versatile",  # el que veniamos usando de default
        "openai/gpt-oss-120b",      # mismo modelo que en Ollama, para comparar proveedor
        "qwen/qwen3.6-27b",         # modelo de razonamiento, bueno con JSON/multilenguaje
    ],
    # Ollama Cloud: los mismos 6 modelos probados el 16-17/07, RENOMBRADOS
    # el 23/07 (la API quito el sufijo "-cloud"/":cloud" - mismo modelo,
    # nombre distinto). Se descartaron por error 403 (piden suscripcion
    # Pro): glm-5.1, kimi-k2.6, kimi-k2.7-code, deepseek-v4-flash, qwen3.5
    # y qwen3.5:397b.
    "ollama": [
        "gpt-oss:120b",
        "gemma4:31b",
        "minimax-m3",
        "nemotron-3-super",
        "minimax-m2.5",
        "nemotron-3-ultra",
    ],
    # Gemini: "gemini-3.0-flash" no existe (404 real) y "gemini-2.5-pro"
    # tiene cuota 0 en el free tier (429 real) - los dos descartados aposta.
    "gemini": [
        "models/gemini-3.5-flash",       # El mejor, más moderno y recomendado (Rápido y lógico)
        "models/gemini-3.1-flash-lite",  # El más ligero, ideal si haces muchas llamadas seguidas
        "models/gemini-2.5-flash",       # Versión Flash anterior, totalmente operativa y gratuita
        "models/gemma-4-31b-it",    # Modelo abierto de Google, sin cuotas estrictas
    ],
}


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
    return clave.encode() if clave else None


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
