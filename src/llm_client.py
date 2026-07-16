# SDK oficial de Groq (instalado con pip install groq).
from groq import Groq
from src.config import GROQ_API_KEY, GROQ_MODEL

# Cliente que sabe autenticarse y hablar con la API de Groq.
# Se crea una sola vez, aqui fuera de la funcion, para reutilizarlo.
client = Groq(api_key=GROQ_API_KEY)


def preguntar(mensaje: str) -> str:
    """Envia un mensaje al modelo y devuelve solo el texto de la respuesta."""
    respuesta = client.chat.completions.create(
        model=GROQ_MODEL,
        # "messages" es el historial que se envia al modelo. De momento
        # solo mandamos un mensaje del usuario (sin memoria todavia).
        messages=[{"role": "user", "content": mensaje}],
    )
    # La respuesta trae varias posibles opciones (choices); usamos la primera.
    return respuesta.choices[0].message.content