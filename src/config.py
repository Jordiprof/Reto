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
)