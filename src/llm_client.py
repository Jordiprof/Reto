# logging: para registrar cada llamada y cada error en logs/agente.log
# (la configuracion real vive en config.py, aqui solo lo usamos).
import logging
# time: modulo estandar con funciones de tiempo. perf_counter() es un
# cronometro de alta precision, para medir cuanto tarda cada llamada.
import time


def _preguntar_groq(historial: list, api_key: str, modelo: str) -> str:
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
            # messages: ahora mandamos el historial COMPLETO, no solo la
            # ultima pregunta. El modelo no recuerda nada entre llamadas:
            # la "memoria" es esta lista que le reenviamos entera cada vez.
            # Groq usa el formato canonico (system/user/assistant + content),
            # asi que la lista viaja tal cual, sin traducir.
            messages=historial,
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


def _preguntar_ollama(historial: list, api_key: str, modelo: str) -> str:
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
            # Igual que Groq: Ollama entiende el formato canonico
            # (system/user/assistant + content), historial tal cual.
            messages=historial,
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


def traducir_historial_gemini(historial: list) -> tuple[list, str | None]:
    """Traduce el historial canonico (system/user/assistant + content) al
    formato propio de Gemini. Devuelve (contents, system_instruction).

    Funcion PURA a proposito: no toca la red ni el historial original,
    solo transforma una lista en otra. Asi se puede probar con pytest
    sin gastar llamadas reales (F3.4). Sin guion bajo inicial: es parte
    "publica" del modulo porque los tests la importaran directamente.
    """
    # Gemini no acepta un mensaje con rol "system" dentro de la lista:
    # las instrucciones estables van aparte, como system_instruction.
    system_instruction = None
    # Lista NUEVA (no modificamos historial en el sitio): si mutaramos la
    # original, el formato de Gemini "contaminaria" el historial canonico
    # que main.py sigue usando para Groq/Ollama y para guardarlo en JSON.
    contents = []

    for mensaje in historial:
        if mensaje["role"] == "system":
            # Lo extraemos de la conversacion y lo devolvemos aparte.
            system_instruction = mensaje["content"]
        else:
            # Dos diferencias de nombre respecto al formato canonico:
            # 1) el rol del modelo se llama "model", no "assistant";
            # 2) el texto va en "parts" (lista de trozos), no en "content".
            rol = "model" if mensaje["role"] == "assistant" else "user"
            contents.append({"role": rol, "parts": [{"text": mensaje["content"]}]})

    return contents, system_instruction


def _preguntar_gemini(historial: list, api_key: str, modelo: str) -> str:
    # genai: SDK oficial de Google para la API de Gemini.
    # types: clases de configuracion del SDK (GenerateContentConfig).
    from google import genai
    from google.genai import types

    # OJO: a diferencia de Groq y Ollama, aqui NO se pasa la api_key a
    # mano. El SDK busca el solo la variable de entorno GEMINI_API_KEY
    # (ya cargada por dotenv en config.py).
    client = genai.Client()

    # Traducimos el historial canonico al dialecto de Gemini ANTES de
    # llamar (funcion pura de arriba, verificada en docs oficiales 17/07).
    contents, system_instruction = traducir_historial_gemini(historial)

    inicio = time.perf_counter()
    try:
        # Metodo distinto a los otros dos: generate_content, no
        # chat.completions.create ni chat(). El system prompt NO viaja en
        # contents: va en config, como system_instruction.
        respuesta = client.models.generate_content(
            model=modelo,
            contents=contents,
            config=types.GenerateContentConfig(system_instruction=system_instruction),
        )
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


def preguntar(historial: list, proveedor: str, api_key: str, modelo: str) -> str:
    """Punto de entrada unico: busca la funcion del proveedor elegido y la ejecuta.

    Recibe el historial COMPLETO en formato canonico (system/user/assistant
    + content). Cada funcion interna lo adapta a su proveedor si hace falta.
    """
    funcion = _FUNCIONES[proveedor]
    return funcion(historial, api_key, modelo)