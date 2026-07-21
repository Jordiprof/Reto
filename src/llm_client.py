# logging: para registrar cada llamada y cada error en logs/agente.log
# (la configuracion real vive en config.py, aqui solo lo usamos).
import logging
# time: modulo estandar con funciones de tiempo. perf_counter() es un
# cronometro de alta precision, para medir cuanto tarda cada llamada.
import time
# json: los argumentos que manda Groq para una tool vienen como texto
# JSON dentro de la respuesta (no como dict ya hecho, a diferencia de
# Ollama) - hay que parsearlos antes de poder usarlos.
import json
# TOOLS: la ficha tecnica (JSON Schema) de cada herramienta disponible.
# HERRAMIENTAS_DISPONIBLES: el nombre de cada tool -> la funcion real de
# Python que hay que ejecutar cuando el modelo la pida.
from src.tools import TOOLS, HERRAMIENTAS_DISPONIBLES

# Limite de vueltas del bucle LLM -> tool -> resultado -> LLM. Sin esto,
# si el modelo se quedara pidiendo la misma tool una y otra vez (un bug
# suyo, no imposible), el programa se colgaria en un bucle infinito.
_MAX_PASOS_DE_HERRAMIENTAS = 5


def _preguntar_groq(historial: list, api_key: str, modelo: str) -> str:
    # Import dentro de la funcion: asi el SDK de Groq solo se carga
    # cuando de verdad se usa este proveedor, no siempre que se importa
    # llm_client.py.
    # Groq: cliente oficial. Authentication/APIConnection/RateLimit Error:
    # tipos de error concretos definidos por ese mismo SDK. APIError es
    # la clase BASE de la que heredan estos tres (y cualquier otro error
    # de la API de Groq que no hayamos previsto a mano) - verificado con
    # __mro__ tras un fallo real (F4.5): groq.BadRequestError con
    # tool_use_failed, no capturado por ninguna de las 3 especificas.
    from groq import Groq, AuthenticationError, APIConnectionError, RateLimitError, APIError

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
    except APIError as error:
        # Red de seguridad: cualquier otro error de la API de Groq que
        # no sea uno de los 3 de arriba (ej. tool_use_failed cuando el
        # modelo formatea mal una llamada a funcion) cae aqui, en vez
        # de reventar el programa entero.
        logging.error(f"Groq: error de API no especifico - {error}")
        return f"⚠️ Error de Groq: {error}"


def _ejecutar_tool(nombre: str, argumentos: dict) -> str:
    """Ejecuta una tool por nombre, con los argumentos ya en forma de
    dict de Python. Compartida por Groq y Ollama (ambos acaban con los
    argumentos en el mismo formato, aunque lleguen distinto - ver abajo).

    Si la tool no existe o falla, NO se rompe el programa: se devuelve
    un string de error, que el modelo vera como el "resultado" de la
    tool y puede usar para explicarle al usuario que algo fue mal.
    """
    funcion = HERRAMIENTAS_DISPONIBLES.get(nombre)
    if funcion is None:
        return f"Error: la herramienta '{nombre}' no existe."
    try:
        return str(funcion(**argumentos))
    except Exception as error:
        return f"Error ejecutando '{nombre}': {error}"


def _preguntar_groq_con_tools(historial: list, api_key: str, modelo: str) -> str:
    """Version de _preguntar_groq que sabe usar tools (F4.3).

    Bucle: llamar al modelo -> si pide una tool, ejecutarla y mandarle
    el resultado -> volver a llamar -> repetir hasta que responda con
    texto normal (sin mas tool_calls) o se agote _MAX_PASOS_DE_HERRAMIENTAS.
    """
    from groq import Groq, AuthenticationError, APIConnectionError, RateLimitError, APIError

    client = Groq(api_key=api_key)
    # Copia de trabajo: aqui SI se van a colar los mensajes intermedios
    # de tool-calling (peticion del modelo + resultado de la tool), pero
    # esos NUNCA salen de esta funcion - el historial canonico de
    # main.py solo vera la pregunta original y la respuesta final.
    mensajes = list(historial)

    for _ in range(_MAX_PASOS_DE_HERRAMIENTAS):
        inicio = time.perf_counter()
        try:
            respuesta = client.chat.completions.create(
                model=modelo,
                messages=mensajes,
                tools=TOOLS,
            )
        except AuthenticationError:
            logging.error("Groq: clave de API invalida")
            return "⚠️ Error: la clave de API de Groq no es válida."
        except APIConnectionError:
            logging.error("Groq: fallo de conexion")
            return "⚠️ Error: no hay conexión con Groq."
        except RateLimitError:
            logging.error("Groq: limite de peticiones superado")
            return "⚠️ Error: límite de peticiones de Groq superado."
        except APIError as error:
            # F4.5, fallo real encontrado en pruebas en vivo: a veces el
            # modelo formatea mal una llamada a funcion y Groq devuelve
            # groq.BadRequestError (tool_use_failed) - no es ninguna de
            # las 3 excepciones de arriba. Sin esta captura, el programa
            # entero se caia. No-determinismo del modelo (ver F2.5): no
            # siempre pasa con la misma pregunta.
            logging.error(f"Groq: error de API no especifico - {error}")
            return f"⚠️ Error de Groq: {error}"
        logging.info(f"Latencia (groq/{modelo}, con tools): {time.perf_counter() - inicio:.2f}s")

        mensaje = respuesta.choices[0].message

        if not mensaje.tool_calls:
            # Respuesta final: texto normal, el modelo ya no pide tools.
            return mensaje.content

        # El modelo pide usar una o mas tools: guardamos SU mensaje tal
        # cual (incluye los tool_calls) - la API necesita verlo para
        # saber a que peticion responde cada resultado que mandemos.
        mensajes.append(mensaje)

        for llamada in mensaje.tool_calls:
            # Groq (como OpenAI) manda los argumentos como texto JSON,
            # no como dict ya construido - hay que parsearlo a mano.
            # F4.4: este parseo puede fallar si el modelo devuelve un
            # JSON mal formado (raro, pero no imposible) - sin este
            # try/except, un error aqui tiraba abajo TODO el programa
            # en vez de quedarse como un simple resultado de tool fallido.
            try:
                argumentos = json.loads(llamada.function.arguments)
            except json.JSONDecodeError as error:
                resultado = f"Error: argumentos no válidos para '{llamada.function.name}' ({error})"
            else:
                resultado = _ejecutar_tool(llamada.function.name, argumentos)
            mensajes.append({
                "role": "tool",
                # tool_call_id: asi la API sabe que ESTE resultado
                # responde a ESA llamada concreta (puede haber varias
                # en el mismo turno).
                "tool_call_id": llamada.id,
                "content": resultado,
            })

    return "⚠️ El agente no llegó a una respuesta final tras varios pasos de herramientas."


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


def _preguntar_ollama_con_tools(historial: list, api_key: str, modelo: str) -> str:
    """Version de _preguntar_ollama que sabe usar tools (F4.3).

    Mismo bucle que Groq, pero con dos diferencias reales de la API de
    Ollama (verificadas en su documentacion oficial, no supuestas):
    1) los argumentos de la tool ya vienen como dict, no como texto
       JSON - no hace falta json.loads() aqui.
    2) el mensaje de resultado usa la clave "tool_name", NO
       "tool_call_id" como Groq/OpenAI - Ollama no reparte un id por
       cada llamada.
    """
    from ollama import Client

    client = Client(host="https://ollama.com", headers={"Authorization": "Bearer " + api_key})
    mensajes = list(historial)

    for _ in range(_MAX_PASOS_DE_HERRAMIENTAS):
        inicio = time.perf_counter()
        try:
            respuesta = client.chat(model=modelo, messages=mensajes, tools=TOOLS)
        except Exception as error:
            logging.error(f"Ollama: error - {error}")
            return f"⚠️ Error al hablar con Ollama: {error}"
        logging.info(f"Latencia (ollama/{modelo}, con tools): {time.perf_counter() - inicio:.2f}s")

        mensaje = respuesta["message"]

        if not mensaje.get("tool_calls"):
            return mensaje["content"]

        mensajes.append(mensaje)

        for llamada in mensaje["tool_calls"]:
            # Aqui NO hace falta json.loads(): Ollama ya entrega los
            # argumentos como dict de Python, a diferencia de Groq.
            argumentos = llamada["function"]["arguments"]
            nombre = llamada["function"]["name"]
            resultado = _ejecutar_tool(nombre, argumentos)
            mensajes.append({
                "role": "tool",
                "content": resultado,
                "tool_name": nombre,
            })

    return "⚠️ El agente no llegó a una respuesta final tras varios pasos de herramientas."


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


def _preguntar_gemini_con_tools(historial: list, api_key: str, modelo: str) -> str:
    """Version de _preguntar_gemini que sabe usar tools (F4.5).

    Verificado contra la doc oficial (ai.google.dev/gemini-api/docs/
    generate-content/function-calling, con generate_content - no la
    Interactions API, coherente con la decision de F3.1). Tres
    diferencias reales respecto a Groq/Ollama:
    1) las tools se declaran SIN el "type": "function" de fuera - solo
       name/description/parameters, envueltas en types.Tool(...).
    2) la peticion de funcion no viene en un campo tool_calls, sino
       dentro de response.candidates[0].content.parts[0].function_call.
    3) los argumentos ya llegan como dict (como Ollama, no como texto
       JSON como Groq).
    """
    from google import genai
    from google.genai import types

    client = genai.Client()
    contents, system_instruction = traducir_historial_gemini(historial)

    # De TOOLS (formato Groq/OpenAI) sacamos solo el diccionario interior
    # "function" de cada una - es la parte que Gemini SI reconoce.
    declaraciones = [tool["function"] for tool in TOOLS]
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=[types.Tool(function_declarations=declaraciones)],
    )

    for _ in range(_MAX_PASOS_DE_HERRAMIENTAS):
        inicio = time.perf_counter()
        try:
            respuesta = client.models.generate_content(
                model=modelo, contents=contents, config=config,
            )
        except Exception as error:
            logging.error(f"Gemini: error - {error}")
            return f"⚠️ Error al hablar con Gemini: {error}"
        logging.info(f"Latencia (gemini/{modelo}, con tools): {time.perf_counter() - inicio:.2f}s")

        # Hallazgo real (F4.6, probado en vivo por Jordi): Gemini puede
        # devolver VARIAS partes en la misma respuesta - por ejemplo,
        # una de texto ("Dejame calcular...") seguida de la parte real
        # con la peticion de funcion. Mirar solo parts[0] se comia la
        # llamada a la tool si no era la primera parte, y el agente
        # "fingia" que iba a calcular sin hacerlo nunca. Ahora se busca
        # en TODAS las partes, no solo en la primera.
        llamada = None
        for parte in respuesta.candidates[0].content.parts:
            llamada = getattr(parte, "function_call", None)
            if llamada:
                break

        if not llamada:
            # Respuesta final: texto normal, sin peticion de funcion.
            return respuesta.text

        # dict(...) por seguridad: args llega como un tipo propio del
        # SDK parecido a un dict, no un dict de Python puro - dict()
        # lo normaliza para poder usarlo con **argumentos sin sorpresas.
        argumentos = dict(llamada.args)
        resultado = _ejecutar_tool(llamada.name, argumentos)

        # Igual que con Groq/Ollama: guardamos la peticion del modelo y
        # el resultado antes de volver a preguntar - pero con el formato
        # de Content/Part propio de Gemini, no dicts sueltos.
        contents.append(respuesta.candidates[0].content)
        contents.append(
            types.Content(
                role="user",
                parts=[
                    types.Part.from_function_response(
                        name=llamada.name,
                        response={"resultado": resultado},
                    )
                ],
            )
        )

    return "⚠️ El agente no llegó a una respuesta final tras varios pasos de herramientas."


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


# F4.3-F4.5: dispatcher equivalente a _FUNCIONES pero para las
# versiones con tools. Los 3 proveedores soportan ya tool calling real.
_FUNCIONES_CON_TOOLS = {
    "groq": _preguntar_groq_con_tools,
    "ollama": _preguntar_ollama_con_tools,
    "gemini": _preguntar_gemini_con_tools,
}


def preguntar_con_tools(historial: list, proveedor: str, api_key: str, modelo: str) -> str:
    """Como preguntar(), pero permite al modelo usar las tools de TOOLS
    (src/tools.py). Devuelve directamente el texto final de la
    respuesta - todo el ir-y-venir de tool-calling queda resuelto por
    dentro, main.py no necesita saber que ha pasado nada especial.
    """
    funcion = _FUNCIONES_CON_TOOLS[proveedor]
    return funcion(historial, api_key, modelo)