# logging: para registrar cada llamada y cada error en logs/agente.log
# (la configuracion real vive en config.py, aqui solo lo usamos).
import logging
# time: perf_counter() es un cronometro de alta precision, para medir
# cuanto tarda cada llamada.
import time
# json: los argumentos que manda Groq para una tool vienen como texto JSON
# (no como dict, a diferencia de Ollama) - hay que parsearlos.
import json
# HERRAMIENTAS_DISPONIBLES: nombre de cada tool -> funcion real de Python.
# (TOOLS, la ficha tecnica JSON Schema, ya no se usa aqui - desde F5.0/T4
# quien decide que tools pasar es Agente, ver src/agent.py).
from src.tools import HERRAMIENTAS_DISPONIBLES
# Formas neutras compartidas por los 3 proveedores (F5.0/T1).
from src.llm_types import RespuestaLLM, ToolCall
# Excepciones tipadas (F5.0/T2): sustituyen a los strings "⚠️ ..." que se
# detectaban con .startswith() - ver src/llm_errors.py para el porque.
from src.llm_errors import (
    ErrorAutenticacion, ErrorConexion, ErrorLimitePasos,
    ErrorLimitePeticiones, ErrorPeticionInvalida, ErrorTimeout,
)

# Limite de vueltas del bucle LLM -> tool -> resultado -> LLM. Sin esto, si
# el modelo se quedara pidiendo la misma tool una y otra vez (un bug suyo,
# no imposible), el programa se colgaria en un bucle infinito.
_MAX_PASOS_DE_HERRAMIENTAS = 5

# F5.0/T3 (hallazgo AUD-02 de la auditoria): ninguna llamada de red tenia
# timeout - una conexion colgada bloqueaba el proceso entero sin limite.
# 30s en SEGUNDOS (Groq/Ollama lo piden asi); Gemini lo pide en MILISEGUNDOS,
# ver _ProveedorGemini._estado_inicial.
_TIMEOUT_SEGUNDOS = 30.0


def _ejecutar_tool(nombre: str, argumentos: dict) -> str:
    """Ejecuta una tool por nombre, con los argumentos ya en forma de dict.
    Compartida por los 3 proveedores (todos acaban con los argumentos en el
    mismo formato gracias a la capa de traduccion).

    Si la tool no existe o falla, NO se rompe el programa: se devuelve un
    string de error, que el modelo vera como el "resultado" de la tool.
    """
    funcion = HERRAMIENTAS_DISPONIBLES.get(nombre)
    if funcion is None:
        return f"Error: la herramienta '{nombre}' no existe."
    try:
        return str(funcion(**argumentos))
    except Exception as error:
        return f"Error ejecutando '{nombre}': {error}"


def traducir_historial_gemini(historial: list) -> tuple[list, str | None]:
    """Traduce el historial canonico (system/user/assistant + content) al
    formato propio de Gemini. Devuelve (contents, system_instruction).

    Funcion PURA a proposito: no toca la red ni el historial original, solo
    transforma una lista en otra. Asi se puede probar con pytest sin gastar
    llamadas reales (F3.4). Sin guion bajo inicial: los tests la importan.
    """
    # Gemini no acepta un mensaje con rol "system" dentro de la lista: las
    # instrucciones estables van aparte, como system_instruction.
    system_instruction = None
    # Lista NUEVA (no mutamos historial): si la modificaramos en el sitio, el
    # formato de Gemini contaminaria el historial canonico que se usa para
    # Groq/Ollama y para guardar en JSON.
    contents = []

    for mensaje in historial:
        if mensaje["role"] == "system":
            system_instruction = mensaje["content"]
        else:
            # Dos diferencias de nombre respecto al formato canonico:
            # 1) el rol del modelo se llama "model", no "assistant";
            # 2) el texto va en "parts" (lista de trozos), no en "content".
            rol = "model" if mensaje["role"] == "assistant" else "user"
            contents.append({"role": rol, "parts": [{"text": mensaje["content"]}]})

    return contents, system_instruction


def _texto_de_gemini(respuesta) -> str:
    """Extrae el texto de una respuesta de Gemini de forma DEFENSIVA.

    En vez de usar respuesta.text a pelo (que puede lanzar una excepcion si
    el candidato no trae ninguna parte de texto - p. ej. cuando solo trae
    una function_call, o cuando la respuesta viene bloqueada por seguridad),
    recorremos las partes y concatenamos solo el texto que haya. Tolerante:
    si no hay texto, devuelve "" en vez de reventar (hallazgo #7 de la
    auditoria de seguridad del 23/07).
    """
    try:
        candidato = respuesta.candidates[0]
    except (AttributeError, IndexError, TypeError):
        return ""
    partes = getattr(candidato.content, "parts", None) or []
    return "".join(p.text for p in partes if getattr(p, "text", None))


class _ProveedorLLM:
    """Clase base: define el BUCLE compartido (LLM -> tool -> resultado ->
    LLM) una sola vez. Cada proveedor concreto solo implementa las 4 piezas
    que de verdad cambian entre SDKs; el bucle no las conoce.
    """

    # Nombre para los logs de latencia; lo fija cada subclase.
    _nombre = "?"

    def __init__(self, api_key: str, modelo: str):
        self.api_key = api_key
        self.modelo = modelo

    def responder(self, historial: list, tools: list | None) -> str:
        """El bucle unico. Recibe el historial canonico y, opcionalmente, la
        lista de tools disponibles (None = modo sin herramientas). Devuelve
        el texto final de la respuesta - todo el ir y venir de tool-calling
        queda resuelto aqui dentro.
        """
        estado = self._estado_inicial(historial, tools)

        for _ in range(_MAX_PASOS_DE_HERRAMIENTAS):
            # _llamar() puede lanzar ErrorLLM (auth, conexion, limite...) -
            # NO se atrapa aqui: sube tal cual a quien llamo a responder(),
            # que decide que hacer (agent.py, y mas adelante el router T4).
            respuesta = self._llamar(estado)

            if not respuesta.pide_tools:
                # Respuesta final: el modelo ya no pide herramientas.
                return respuesta.texto

            # El modelo pidio una o mas tools: registramos SU peticion (en el
            # formato que su propio SDK necesita ver luego) y ejecutamos.
            self._registrar_peticion(estado, respuesta)
            for llamada in respuesta.tool_calls:
                # Si el traductor marco un error de parseo de argumentos
                # (JSON mal formado de Groq, F4.4), NO se ejecuta la tool:
                # ese texto de error hace de "resultado".
                if llamada.error:
                    resultado = llamada.error
                else:
                    resultado = _ejecutar_tool(llamada.nombre, llamada.argumentos)
                self._registrar_resultado(estado, llamada, resultado)

        raise ErrorLimitePasos(self._nombre)

    # --- Piezas que cada proveedor implementa (lo unico que cambia) ---

    def _estado_inicial(self, historial: list, tools: list | None):
        """Prepara el cliente y el estado de trabajo (mensajes/contents)."""
        raise NotImplementedError

    def _llamar(self, estado) -> RespuestaLLM:
        """Hace UNA llamada al modelo y traduce su respuesta a RespuestaLLM."""
        raise NotImplementedError

    def _registrar_peticion(self, estado, respuesta: RespuestaLLM) -> None:
        """Anade al estado la peticion de tools del modelo (formato del SDK)."""
        raise NotImplementedError

    def _registrar_resultado(self, estado, llamada: ToolCall, resultado: str) -> None:
        """Anade al estado el resultado de una tool (formato del SDK)."""
        raise NotImplementedError


class _ProveedorGroq(_ProveedorLLM):
    _nombre = "groq"

    def _estado_inicial(self, historial, tools):
        # Import dentro: el SDK de Groq solo se carga si se usa este proveedor.
        from groq import Groq

        # Groq usa el formato canonico tal cual (system/user/assistant +
        # content), asi que los mensajes viajan sin traducir.
        # timeout=_TIMEOUT_SEGUNDOS (F5.0/T3): sin esto, por defecto Groq
        # espera 1 minuto entero antes de rendirse - demasiado para un bot
        # que debe seguir vivo (verificado en groq-python/README.md).
        return {
            "client": Groq(api_key=self.api_key, timeout=_TIMEOUT_SEGUNDOS),
            "mensajes": list(historial),
            "tools": tools,
        }

    def _llamar(self, estado):
        # APIError es la clase BASE de la que heredan los errores concretos de
        # Groq (y del que hereda tambien groq.BadRequestError con
        # tool_use_failed, no capturado por las especificas - hallazgo real
        # de F4.5). Sin este ultimo except, el programa se caia.
        # APITimeoutError hereda de APIConnectionError (verificado en el SDK) -
        # por eso se captura ANTES: si fuera despues, nunca se alcanzaria.
        from groq import (
            AuthenticationError, APIConnectionError, APITimeoutError,
            RateLimitError, APIError,
        )

        client = estado["client"]
        # Solo pasamos tools si las hay (modo sin herramientas = tools None).
        kwargs = {"model": self.modelo, "messages": estado["mensajes"]}
        if estado["tools"]:
            kwargs["tools"] = estado["tools"]

        inicio = time.perf_counter()
        try:
            respuesta = client.chat.completions.create(**kwargs)
        except AuthenticationError as error:
            logging.error("Groq: clave de API invalida")
            raise ErrorAutenticacion("Groq", str(error)) from error
        except APITimeoutError as error:
            logging.error(f"Groq: timeout tras {_TIMEOUT_SEGUNDOS}s")
            raise ErrorTimeout("Groq", str(error)) from error
        except APIConnectionError as error:
            logging.error("Groq: fallo de conexion")
            raise ErrorConexion("Groq", str(error)) from error
        except RateLimitError as error:
            logging.error("Groq: limite de peticiones superado")
            raise ErrorLimitePeticiones("Groq", str(error)) from error
        except APIError as error:
            logging.error(f"Groq: error de API no especifico - {error}")
            raise ErrorPeticionInvalida("Groq", str(error)) from error
        logging.info(f"Latencia (groq/{self.modelo}): {time.perf_counter() - inicio:.2f}s")

        mensaje = respuesta.choices[0].message
        if not mensaje.tool_calls:
            return RespuestaLLM(texto=mensaje.content)

        tool_calls = []
        for llamada in mensaje.tool_calls:
            # Groq (como OpenAI) manda los argumentos como texto JSON, no como
            # dict - hay que parsearlo. Puede fallar si el modelo devuelve un
            # JSON mal formado (raro, pero F4.4 lo vio en real): se marca como
            # error en el ToolCall en vez de reventar.
            try:
                argumentos = json.loads(llamada.function.arguments)
                tool_calls.append(ToolCall(
                    nombre=llamada.function.name, argumentos=argumentos, id=llamada.id,
                ))
            except json.JSONDecodeError as error:
                tool_calls.append(ToolCall(
                    nombre=llamada.function.name, argumentos={}, id=llamada.id,
                    error=f"Error: argumentos no válidos para '{llamada.function.name}' ({error})",
                ))
        # 'raw' = el mensaje del SDK; la API necesita volver a verlo para
        # saber a que peticion responde cada resultado que le mandemos.
        return RespuestaLLM(tool_calls=tool_calls, raw=mensaje)

    def _registrar_peticion(self, estado, respuesta):
        estado["mensajes"].append(respuesta.raw)

    def _registrar_resultado(self, estado, llamada, resultado):
        estado["mensajes"].append({
            "role": "tool",
            # tool_call_id: asi la API sabe que ESTE resultado responde a ESA
            # llamada concreta (puede haber varias en el mismo turno).
            "tool_call_id": llamada.id,
            "content": resultado,
        })


class _ProveedorOllama(_ProveedorLLM):
    _nombre = "ollama"

    def _estado_inicial(self, historial, tools):
        from ollama import Client

        # La clave de Ollama no se pasa como parametro api_key (a diferencia
        # de Groq): va a mano en la cabecera HTTP Authorization: Bearer ...
        # timeout=_TIMEOUT_SEGUNDOS (F5.0/T3): el Client de Ollama reenvia
        # este kwarg tal cual al httpx.Client interno (verificado en la doc
        # del SDK) - sin el, una llamada colgada no tenia limite de tiempo.
        client = Client(
            host="https://ollama.com",
            headers={"Authorization": "Bearer " + self.api_key},
            timeout=_TIMEOUT_SEGUNDOS,
        )
        return {"client": client, "mensajes": list(historial), "tools": tools}

    def _llamar(self, estado):
        # httpx: libreria HTTP que usa el SDK de Ollama por dentro.
        # TimeoutException es la que lanza si se supera _TIMEOUT_SEGUNDOS -
        # se captura ANTES del except Exception generico de abajo para
        # poder distinguirla (el router de T4 solo reintentara esta).
        import httpx

        client = estado["client"]
        kwargs = {"model": self.modelo, "messages": estado["mensajes"]}
        if estado["tools"]:
            kwargs["tools"] = estado["tools"]

        inicio = time.perf_counter()
        try:
            respuesta = client.chat(**kwargs)
        except httpx.TimeoutException as error:
            logging.error(f"Ollama: timeout tras {_TIMEOUT_SEGUNDOS}s")
            raise ErrorTimeout("Ollama", str(error)) from error
        except Exception as error:
            # Ollama no define excepciones tan especificas como Groq en su
            # SDK; capturamos generico. ErrorPeticionInvalida como cajon
            # generico (no reintentable) - se afina si algun dia se necesita
            # distinguir auth/conexion/limite tambien aqui.
            logging.error(f"Ollama: error - {error}")
            raise ErrorPeticionInvalida("Ollama", str(error)) from error
        logging.info(f"Latencia (ollama/{self.modelo}): {time.perf_counter() - inicio:.2f}s")

        mensaje = respuesta["message"]
        if not mensaje.get("tool_calls"):
            return RespuestaLLM(texto=mensaje["content"])

        tool_calls = []
        for llamada in mensaje["tool_calls"]:
            # Ollama YA entrega los argumentos como dict (no como texto JSON,
            # a diferencia de Groq) y NO reparte un id por llamada.
            tool_calls.append(ToolCall(
                nombre=llamada["function"]["name"],
                argumentos=llamada["function"]["arguments"],
            ))
        return RespuestaLLM(tool_calls=tool_calls, raw=mensaje)

    def _registrar_peticion(self, estado, respuesta):
        estado["mensajes"].append(respuesta.raw)

    def _registrar_resultado(self, estado, llamada, resultado):
        estado["mensajes"].append({
            "role": "tool",
            "content": resultado,
            # Ollama identifica el resultado por "tool_name", NO por
            # tool_call_id como Groq/OpenAI.
            "tool_name": llamada.nombre,
        })


class _ProveedorGemini(_ProveedorLLM):
    _nombre = "gemini"

    def _estado_inicial(self, historial, tools):
        from google import genai
        from google.genai import types

        # OJO: a diferencia de Groq/Ollama, aqui NO se pasa la api_key a mano.
        # El SDK busca solo la variable de entorno GEMINI_API_KEY.
        # http_options timeout (F5.0/T3): a diferencia de Groq/Ollama, este
        # SDK lo pide en MILISEGUNDOS, no segundos (verificado en la doc de
        # google-genai) - de ahi el *1000. Hay issues abiertos en el repo del
        # SDK reportando que a veces no se respeta del todo; se deja puesto
        # igualmente porque es lo documentado, y el limite del bucle
        # (_MAX_PASOS_DE_HERRAMIENTAS) sigue de red de seguridad.
        client = genai.Client(
            http_options=types.HttpOptions(timeout=int(_TIMEOUT_SEGUNDOS * 1000))
        )
        # Traducimos el historial canonico al dialecto de Gemini.
        contents, system_instruction = traducir_historial_gemini(historial)

        if tools:
            # De TOOLS (formato Groq/OpenAI) sacamos solo el dict interior
            # "function" de cada una - es lo que Gemini reconoce.
            declaraciones = [tool["function"] for tool in tools]
            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                tools=[types.Tool(function_declarations=declaraciones)],
            )
        else:
            config = types.GenerateContentConfig(system_instruction=system_instruction)

        return {"client": client, "contents": contents, "config": config}

    def _llamar(self, estado):
        # httpx: el SDK de Gemini tambien lo usa por debajo para el
        # transporte HTTP; TimeoutException es lo que lanza al superar el
        # timeout de http_options.
        import httpx

        client = estado["client"]
        inicio = time.perf_counter()
        try:
            respuesta = client.models.generate_content(
                model=self.modelo,
                contents=estado["contents"],
                config=estado["config"],
            )
        except httpx.TimeoutException as error:
            logging.error(f"Gemini: timeout tras {_TIMEOUT_SEGUNDOS}s")
            raise ErrorTimeout("Gemini", str(error)) from error
        except Exception as error:
            logging.error(f"Gemini: error - {error}")
            raise ErrorPeticionInvalida("Gemini", str(error)) from error
        logging.info(f"Latencia (gemini/{self.modelo}): {time.perf_counter() - inicio:.2f}s")

        # Hallazgo real (F4.6): Gemini puede devolver VARIAS partes - una de
        # texto ("Dejame calcular...") y luego la peticion de funcion. Hay que
        # recorrer TODAS las partes, no solo parts[0], o se pierde la llamada.
        content = respuesta.candidates[0].content
        tool_calls = []
        for parte in content.parts:
            funcion = getattr(parte, "function_call", None)
            if funcion:
                # dict(...) normaliza los args (llegan como un tipo del SDK
                # parecido a dict) para poder usarlos con **argumentos.
                tool_calls.append(ToolCall(nombre=funcion.name, argumentos=dict(funcion.args)))

        if tool_calls:
            return RespuestaLLM(tool_calls=tool_calls, raw=content)
        return RespuestaLLM(texto=_texto_de_gemini(respuesta))

    def _registrar_peticion(self, estado, respuesta):
        # Con el formato Content/Part propio de Gemini, no dicts sueltos.
        estado["contents"].append(respuesta.raw)

    def _registrar_resultado(self, estado, llamada, resultado):
        from google.genai import types

        estado["contents"].append(
            types.Content(
                role="user",
                parts=[types.Part.from_function_response(
                    name=llamada.nombre,
                    response={"resultado": resultado},
                )],
            )
        )


# Registro nombre de proveedor -> clase. Elegir proveedor en tiempo de
# ejecucion sin un if/elif largo (mismo patron que antes con _FUNCIONES).
_PROVEEDORES = {
    "groq": _ProveedorGroq,
    "ollama": _ProveedorOllama,
    "gemini": _ProveedorGemini,
}


def responder_proveedor(proveedor: str, api_key: str, modelo: str,
                        historial: list, tools: list | None) -> str:
    """Ejecuta el bucle completo en UN proveedor concreto y devuelve el
    texto final. Es el UNICO punto de entrada publico desde F5.0/T4: el
    router (src/llm_router.py) lo llama para cada eslabon de la cadena -
    si este proveedor falla, el router captura el ErrorLLM y decide si
    reintentar o degradar al siguiente. Nada mas llama a esto directamente
    (ni siquiera Agente, que solo conoce al router).
    """
    return _PROVEEDORES[proveedor](api_key, modelo).responder(historial, tools)
