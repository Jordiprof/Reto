import os

from dotenv import load_dotenv
from ollama import Client

# Carga el .env manualmente (este script no pasa por src/config.py).
load_dotenv()

client = Client(
    host="https://ollama.com",
    headers={"Authorization": "Bearer " + os.environ["OLLAMA_API_KEY"]},
)

# list() llama a GET /api/tags y devuelve un objeto con una lista "models".
respuesta = client.list()
for modelo in respuesta.models:
    # cada modelo tiene el atributo .model con el nombre/tag exacto.
    print(modelo.model)
