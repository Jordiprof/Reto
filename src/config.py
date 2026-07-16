import os
# python-dotenv: libreria que lee el fichero .env y mete sus variables
# dentro de las variables de entorno del sistema (os.environ).
from dotenv import load_dotenv

# Busca el fichero .env en la raiz del proyecto y carga sus variables.
load_dotenv()

# Leemos las variables ya cargadas. Si no existieran, esto lanzaria un
# error KeyError - preferible a que el programa siga con una clave vacia.
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GROQ_MODEL = os.environ["GROQ_MODEL"]

    