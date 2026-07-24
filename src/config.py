# logging: modulo estandar de Python para registrar eventos (errores,
# informacion) en un fichero permanente, en vez de solo con print()
# que desaparece al cerrar la terminal.
import logging
import os

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

# Configura el sistema de logging global del programa:
# - filename: donde se escriben los mensajes.
# - level: a partir de que gravedad se registra (INFO incluye INFO y ERROR).
# - format: como se ve cada linea (fecha, nivel, mensaje).
logging.basicConfig(
    filename=LOGS_DIR / "agente.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

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
