import os
# logging: modulo estandar de Python para registrar eventos (errores,
# informacion) en un fichero permanente, en vez de solo con print()
# que desaparece al cerrar la terminal.
import logging
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

# Modelos disponibles por proveedor. Nombres EXACTOS, TODOS verificados
# con llamadas reales (no solo docs) el 16-17/07 - ver diario de decisiones.
MODELOS = {
    # Groq: los 4 responden bien; los "qwen" muestran su razonamiento
    # interno con <think> antes de la respuesta final.
    "groq": [
        "llama-3.3-70b-versatile",  # el que veniamos usando de default
        "openai/gpt-oss-120b",      # mismo modelo que en Ollama - sirve para comparar proveedor vs modelo
        "qwen/qwen3-32b",           # modelo de razonamiento (preview)
        "qwen/qwen3.6-27b",         # modelo de razonamiento, bueno con JSON/multilenguaje
    ],
    # Ollama Cloud: los 6 que SI funcionan, probados uno a uno. Se
    # descartaron por error 403 (piden suscripcion Pro): glm-5.1, kimi-k2.6,
    # kimi-k2.7-code, deepseek-v4-flash, qwen3.5 y qwen3.5:397b.
    "ollama": [
        "gpt-oss:120b-cloud",
        "gemma4:31b-cloud",
        "minimax-m3:cloud",
        "nemotron-3-super:cloud",
        "minimax-m2.5:cloud",
        "nemotron-3-ultra:cloud",
    ],
    # Gemini: "gemini-3.0-flash" no existe (404 real) y "gemini-2.5-pro"
    # tiene cuota 0 en el free tier (429 real) - los dos descartados aposta.
    "gemini": [
        "models/gemini-3.5-flash",       # El mejor, más moderno y recomendado (Rápido y lógico)
        "models/gemini-3.1-flash-lite",  # El más ligero, ideal si haces muchas llamadas seguidas
        "models/gemini-2.5-flash",       # Versión Flash anterior, totalmente operativa y gratuita
        "models/gemma-4-31b-it",          # El modelo abierto de Google más potente, libre de cuotas estrictas
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