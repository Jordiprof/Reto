# logging: para registrar cada llamada y cada error en logs/agente.log
# (la configuracion real vive en config.py, aqui solo lo usamos).
import logging

# time: modulo estandar de Python con funciones relacionadas con el
# tiempo. Usamos perf_counter(), un cronometro de alta precision, para
# medir cuanto tarda cada llamada a la API (latencia).
import time


def _preguntar_groq(mensaje: str, api_key: str, modelo: str) -> str:
    # Import dentro de la funcion (no al principio del fichero): asi
    # solo se carga el SDK de Groq cuando de verdad se usa ese proveedor,
    # no siempre que se importa llm_client.py.
    # Groq: cliente oficial para hablar con la API de Groq.
    # AuthenticationError/APIConnectionError/RateLimitError: tipos de
    # error concretos que ese mismo SDK define, para poder distinguir
    # "clave mala" de "sin red" de "demasiadas peticiones".
    from groq import Groq, AuthenticationError, APIConnectionError, RateLimitError

    # Crea el cliente autenticado con tu clave.
    client = Groq(api_key=api_key)

    # Arranca el cronometro antes de la llamada.
    inicio = time.perf_counter()
    try:
        respuesta = client.chat.completions.create(
            model=modelo,
            # messages: lista de turnos de conversacion. "role": "user"
            # indica que este mensaje lo escribe el usuario (tu).
            messages=[{"role": "user", "content": mensaje}],
        )
        # Tiempo transcurrido = ahora menos el inicio. Se guarda en el log.
        logging.info(f"Latencia (groq): {time.perf_counter() - inicio:.2f}s")

        # La respuesta trae una lista "choices" (puede haber varias
        # respuestas candidatas); cogemos la primera [0] y su texto.
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
    # Client: cliente oficial de Ollama. Le indicamos host="https://ollama.com"
    # para hablar directamente con la API en la nube (no con un Ollama local).
    from ollama import Client

    # La clave de Ollama no se pasa como parametro "api_key" (a diferencia
    # de Groq): se manda a mano en la cabecera HTTP "Authorization: Bearer ...".
    client = Client(host="https://ollama.com", headers={"Authorization": "Bearer " + api_key})

    inicio = time.perf_counter()
    try:
        respuesta = client.chat(
            model=modelo,
            messages=[{"role": "user", "content": mensaje}],
        )
        logging.info(f"Latencia (ollama): {time.perf_counter() - inicio:.2f}s")

        # La respuesta de Ollama tiene otra forma distinta a la de Groq:
        # es un diccionario, no un objeto con .choices. Se accede con
        # corchetes ["message"]["content"] en vez de puntos.
        return respuesta["message"]["content"]
    except Exception as error:
        # Ollama no define excepciones tan especificas como Groq en su
        # SDK; de momento capturamos cualquier error generico y lo
        # afinamos mas adelante si hace falta distinguir tipos.
        logging.error(f"Ollama: error - {error}")
        return f"⚠️ Error al hablar con Ollama: {error}"


def _preguntar_gemini(mensaje: str, api_key: str, modelo: str) -> str:
    # genai: SDK oficial de Google para la API de Gemini.
    from google import genai

    # OJO: a diferencia de Groq y Ollama, aqui NO le pasamos la api_key
    # a mano. El SDK de Google busca el solo la variable de entorno
    # llamada exactamente GEMINI_API_KEY (ya cargada por dotenv en
    # config.py) y se autentica sin que se lo digamos explicitamente.
    client = genai.Client()

    inicio = time.perf_counter()
    try:
        # Aqui el metodo se llama generate_content, no chat.completions.create
        # como en Groq - cada SDK tiene su propio nombre para "lo mismo".
        respuesta = client.models.generate_content(model=modelo, contents=mensaje)
        logging.info(f"Latencia (gemini): {time.perf_counter() - inicio:.2f}s")

        # Aqui la respuesta es aun mas simple: .text directamente,
        # sin listas ni indices como en los otros dos proveedores.
        return respuesta.text
    except Exception as error:
        logging.error(f"Gemini: error - {error}")
        return f"⚠️ Error al hablar con Gemini: {error}"


# Diccionario que asocia el nombre de cada proveedor con la funcion
# de arriba que sabe hablar con el. Esto es lo que permite elegir
# proveedor en tiempo de ejecucion sin usar un if/elif largo.
_FUNCIONES = {
    "groq": _preguntar_groq,
    "ollama": _preguntar_ollama,
    "gemini": _preguntar_gemini,
}


def preguntar(mensaje: str, proveedor: str, api_key: str, modelo: str) -> str:
    """Punto de entrada unico: busca la funcion del proveedor elegido y la ejecuta."""
    # Busca en el diccionario la funcion correcta segun el texto "proveedor"
    # (ej. "groq") y la guarda en la variable "funcion" (sin ejecutarla aun).
    funcion = _FUNCIONES[proveedor]

    # Ahora si la ejecuta, pasandole los mismos argumentos que recibio esta funcion.
    return funcion(mensaje, api_key, modelo)