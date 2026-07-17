from groq import Groq, AuthenticationError, APIConnectionError, RateLimitError
import logging
from src.config import GROQ_API_KEY, GROQ_MODEL

client = Groq(api_key=GROQ_API_KEY)


def preguntar(mensaje: str) -> str:
    try:
        respuesta = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": mensaje}],
        )
        return respuesta.choices[0].message.content
    except AuthenticationError:
        logging.error("Fallo de autenticacion: clave de API invalida")
        return "⚠️ Error: la clave de API no es válida. Revisa tu .env"
    except APIConnectionError:
        logging.error("Fallo de conexion: no se pudo contactar con Groq")
        return "⚠️ Error: no hay conexión con Groq. Comprueba tu internet."
    except RateLimitError:
        logging.error("Limite de peticiones superado (rate limit)")
        return "⚠️ Error: se ha superado el limite de peticiones. Espera un momento."