from dotenv import load_dotenv
from google import genai

# Carga el .env manualmente (este script no pasa por src/config.py).
load_dotenv()

# El cliente busca GEMINI_API_KEY solo, no hace falta pasarla a mano.
client = genai.Client()

# list() devuelve un "Pager" (una lista que se puede recorrer directamente).
for modelo in client.models.list():
    # cada modelo tiene el atributo .name con su identificador.
    print(modelo.name)
