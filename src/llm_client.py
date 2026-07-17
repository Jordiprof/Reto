# logging: para registrar cada llamada y cada error en logs/agente.log
# (la configuracion real vive en config.py, aqui solo lo usamos).
import logging
# time: modulo estandar con funciones de tiempo. perf_counter() es un
# cronometro de alta precision, para medir cuanto tarda cada llamada.
import time


def _preguntar_groq(mensaje: str, api_key: str, modelo: str) -> str:
    # Import dentro de la funcion: asi el SDK de Groq solo se carga
    # cuando de verdad se usa este proveedor, no siempre que se importa
    # llm_client.py.
    # Groq: cliente oficial. Authentication/APIConnection/RateLimit Error:
    # tipos de error concretos definidos por ese mismo SDK.
    from groq import Groq, AuthenticationError, APIConnectionError, RateLimitError

    client = Groq(api_key=api_key)
    inicio = time.perf_counter()
    try:
        respuesta = client.chat.completions.create(
            model=modelo,
            # messages: lista de turnos de conversacion. "role": "user"
            # dice que este mensaje lo escribe el usuario (tu).
            messages=[{"role": "user", "content": mensaje}],
        )
        logging.info(f"Latencia (groq/{modelo}): {time.perf_counter() - inicio:.2f}s")
        # choices es una lista (podria haber varias respuestas candidatas);
        # cogemos la primera [0] y su texto.
        return respuesta.choices[0].message.content
    except AuthenticationError:
        logging.error("Groq: clave de API invalida")
        return "⚠️ Error: la clave de API de Groq no es válida."
    except APIConnectionError:
        logging.error("Groq: fallo de conexion")
        return "⚠️ Error: no hay conexión con Groq."
    except RateLimitError:
        logging.error("Groq: limite de peticiones superado")
        return "⚠️ Error: límite de peticiones de Groq superado."


def _preguntar_ollama(mensaje: str, api_key: str, modelo: str) -> str:
    # Client: cliente oficial de Ollama. host="https://ollama.com" para
    # hablar directamente con la API en la nube (no un Ollama local).
    from ollama import Client

    # La clave de Ollama no se pasa como parametro "api_key" (a diferencia
    # de Groq): va a mano en la cabecera HTTP "Authorization: Bearer ...".
    client = Client(host="https://ollama.com", headers={"Authorization": "Bearer " + api_key})

    inicio = time.perf_counter()
    try:
        respuesta = client.chat(
            model=modelo,
            messages=[{"role": "user", "content": mensaje}],
        )
        logging.info(f"Latencia (ollama/{modelo}): {time.perf_counter() - inicio:.2f}s")
        # La respuesta de Ollama es un diccionario, no un objeto con
        # .choices como Groq - se accede con corchetes.
        return respuesta["message"]["content"]
    except Exception as error:
        # Ollama no define excepciones tan especificas como Groq en su
        # SDK; capturamos generico y lo afinamos si hace falta.
        logging.error(f"Ollama: error - {error}")
        return f"⚠️ Error al hablar con Ollama: {error}"


def _preguntar_gemini(mensaje: str, api_key: str, modelo: str) -> str:
    # genai: SDK oficial de Google para la API de Gemini.
    from google import genai

    # OJO: a diferencia de Groq y Ollama, aqui NO se pasa la api_key a
    # mano. El SDK busca el solo la variable de entorno GEMINI_API_KEY
    # (ya cargada por dotenv en config.py).
    client = genai.Client()

    inicio = time.perf_counter()
    try:
        # Metodo distinto a los otros dos: generate_content, no
        # chat.completions.create ni chat().
        respuesta = client.models.generate_content(model=modelo, contents=mensaje)
        logging.info(f"Latencia (gemini/{modelo}): {time.perf_counter() - inicio:.2f}s")
        # Aqui la respuesta es la mas simple de los 3: .text directamente.
        return respuesta.text
    except Exception as error:
        logging.error(f"Gemini: error - {error}")
        return f"⚠️ Error al hablar con Gemini: {error}"


# Diccionario que asocia el nombre de cada proveedor con la funcion de
# arriba que sabe hablar con el. Permite elegir proveedor en tiempo de
# ejecucion sin un if/elif largo.
_FUNCIONES = {
    "groq": _preguntar_groq,
    "ollama": _preguntar_ollama,
    "gemini": _preguntar_gemini,
}


def preguntar(mensaje: str, proveedor: str, api_key: str, modelo: str) -> str:
    """Punto de entrada unico: busca la funcion del proveedor elegido y la ejecuta."""
    funcion = _FUNCIONES[proveedor]
    return funcion(mensaje, api_key, modelo)