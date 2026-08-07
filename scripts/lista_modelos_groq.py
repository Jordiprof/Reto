from dotenv import load_dotenv
from groq import Groq

# Carga el .env manualmente (si este script se ejecuta solo, sin pasar por src/config.py).
load_dotenv()

# Lista todos los modelos que tu cuenta de Groq puede usar ahora mismo.
modelos = Groq().models.list()
for modelo in modelos.data:
    print(modelo.id)
