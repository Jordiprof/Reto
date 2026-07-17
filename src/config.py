import os
import logging
from pathlib import Path # python-dotenv: libreria que lee el fichero .env y mete sus variables
from dotenv import load_dotenv # dentro de las variables de entorno del sistema (os.environ).

# Busca el fichero .env en la raiz del proyecto y carga sus variables.
load_dotenv()

# Leemos las variables ya cargadas. Si no existieran, esto lanzaria un
# error KeyError - preferible a que el programa siga con una clave vacia.
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GROQ_MODEL = os.environ["GROQ_MODEL"]

# Carpeta logs/ en la raiz del proyecto (esta en .gitignore, no se sube a git).
LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)  # la crea si no existe, no falla si ya existe

logging.basicConfig(
    filename=LOGS_DIR / "agente.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)# os: modulo estandar de Python para hablar con el sistema operativo.
# Lo usamos para leer las variables de entorno (os.environ), que es
# donde acaban las claves y modelos despues de cargar el .env.
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

# Diccionario que asocia el nombre corto de cada proveedor con el
# nombre EXACTO de sus variables de entorno en el .env. No leemos los
# valores aqui todavia (leerlos todos de golpe rompe si falta uno que
# no vamos a usar - leccion del diario del 16/07) - solo guardamos
# donde estan, para leerlos mas tarde bajo demanda.
PROVEEDORES = {
    "groq": {"api_key": "GROQ_API_KEY", "modelo": "GROQ_MODEL"},
    "ollama": {"api_key": "OLLAMA_API_KEY", "modelo": "OLLAMA_MODEL"},
    "gemini": {"api_key": "GEMINI_API_KEY", "modelo": "GEMINI_MODEL"},
}


def obtener_credenciales(proveedor: str):
    """Lee del .env solo las variables del proveedor elegido (lectura perezosa)."""
    # Busca en el diccionario de arriba los NOMBRES de las variables
    # que corresponden a este proveedor (no los valores, los nombres).
    datos = PROVEEDORES[proveedor]

    # Ahora si, lee los VALORES reales desde las variables de entorno
    # (las que cargo load_dotenv() al principio del fichero).
    api_key = os.environ[datos["api_key"]]
    modelo = os.environ[datos["modelo"]]

    # Devuelve los dos valores juntos, como una tupla (api_key, modelo).
    return api_key, modelo