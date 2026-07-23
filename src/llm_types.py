# Formas NEUTRAS de datos compartidas por todos los proveedores (F5.0/T1).
#
# Idea: cada proveedor (Groq, Ollama, Gemini) habla su propio dialecto al
# pedir una herramienta. En vez de repetir el bucle de tools 3 veces con
# esas diferencias mezcladas, cada proveedor TRADUCE su respuesta a estas
# dos clases comunes, y el bucle se escribe UNA sola vez contra ellas.
# Mismo principio que traducir_historial_gemini (F3.1), pero para la
# RESPUESTA del modelo cuando pide funciones.
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    """Una peticion de herramienta del modelo, ya normalizada (da igual el
    proveedor de donde venga).

    - nombre/argumentos: que funcion quiere ejecutar y con que parametros
      (argumentos SIEMPRE como dict de Python; el traductor de cada
      proveedor se encarga de dejarlo asi - Groq lo manda como texto JSON).
    - id: solo lo usa Groq, para casar cada resultado con su peticion.
      Ollama y Gemini no reparten id, por eso puede ser None.
    - error: si los argumentos no se pudieron parsear (JSON mal formado de
      Groq, F4.4), se marca aqui y el bucle NO llega a ejecutar la tool -
      devuelve este texto como "resultado" para que el modelo lo lea.
    """
    nombre: str
    argumentos: dict
    id: str | None = None
    error: str | None = None


@dataclass
class RespuestaLLM:
    """Lo que devuelve un proveedor tras UNA llamada, en forma comun.

    O trae texto final (el modelo ya respondio), o trae tool_calls (el
    modelo quiere usar una o mas herramientas) - nunca las dos cosas.

    'raw' guarda el objeto original del proveedor (mensaje del SDK de Groq,
    dict de Ollama, Content de Gemini) SOLO para poder reenviarselo a ese
    mismo proveedor en la siguiente vuelta del bucle. No sale de la capa de
    proveedores: ni el Agente ni el historial canonico lo ven nunca.
    """
    texto: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: object = None

    @property
    def pide_tools(self) -> bool:
        """True si el modelo pidio herramientas en vez de responder."""
        return len(self.tool_calls) > 0
