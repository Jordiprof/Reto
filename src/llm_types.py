# Formas NEUTRAS de datos compartidas por todos los proveedores (F5.0/T1).
#
# Idea: cada proveedor (Groq, Ollama, Gemini) habla su propio dialecto al
# pedir una herramienta. En vez de repetir el bucle de tools 3 veces con
# esas diferencias mezcladas, cada proveedor TRADUCE su respuesta a estas
# dos clases comunes, y el bucle se escribe UNA sola vez contra ellas.
# Mismo principio que traducir_historial_gemini (F3.1), pero para la
# RESPUESTA del modelo cuando pide funciones.
# json: para construir una clave estable a partir de los argumentos de una
# tool (ver Turno._clave).
import json
from dataclasses import dataclass, field

# SEG-03 / LOG-07: el estado del turno vive aqui (no en llm_router.py ni en
# llm_client.py) porque lo usan LOS DOS - llm_router.py lo crea una vez por
# turno, llm_client.py lo consulta en cada vuelta del bucle de tools.
# Ponerlo en cualquiera de los dos modulos crearia un import circular
# (llm_router.py ya importa de llm_client.py).
from src.llm_errors import ErrorPresupuestoAgotado


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


class Turno:
    """Todo lo que hay que contar y recordar DENTRO de un turno de usuario,
    COMPARTIDO entre todos los eslabones de la cadena del router
    (proveedores + fallbacks) y todos sus reintentos.

    Se crea UNA vez por llamada a LLMRouter.responder() y viaja por todo el
    camino (router -> responder_proveedor -> _ProveedorLLM.responder ->
    _ejecutar_tool). Que sea UNO SOLO para todo el turno es justo lo que le
    da sentido: si se creara uno por intento, ni la cuenta ni la memoria de
    lo ya ejecutado sobrevivirian a un reintento, que es cuando hacen falta.

    Lleva dos cosas:
    - El PRESUPUESTO de llamadas (SEG-03): cuantas van gastadas.
    - Los RESULTADOS de las tools ya ejecutadas (LOG-07): para no volver a
      ejecutarlas si el turno se reintenta.

    Antes esta clase se llamaba PresupuestoLlamadas y solo hacia lo primero.
    El presupuesto no ha cambiado: sigue igual, solo que ahora vive dentro
    de una caja un poco mas grande, porque LOG-07 necesitaba exactamente el
    mismo recorrido (crearse una vez por turno y llegar hasta las tools) y
    duplicar esa tuberia habria sido peor.
    """

    def __init__(self, maximo: int):
        self.maximo = maximo
        self.gastadas = 0
        # nombre+argumentos -> resultado de la tool, dentro de ESTE turno.
        self._resultados: dict[tuple[str, str], str] = {}

    # --- Presupuesto de llamadas (SEG-03) ---

    def gastar(self, proveedor: str) -> None:
        """Se llama justo ANTES de cada llamada real de red. Si ya no queda
        presupuesto, lanza SIN dejar que esa llamada llegue a hacerse - la
        llamada que agotaria el presupuesto no se hace, se corta antes."""
        if self.gastadas >= self.maximo:
            raise ErrorPresupuestoAgotado(proveedor)
        self.gastadas += 1

    # --- Memoria de tools ya ejecutadas (LOG-07) ---

    @staticmethod
    def _clave(nombre: str, argumentos: object) -> tuple[str, str]:
        """Identifica una llamada por su nombre MAS sus argumentos.

        sort_keys=True: dos dicts con las mismas claves en distinto orden
        son la MISMA llamada, y sin ordenar darian textos distintos. El
        except cubre argumentos que no sean serializables (no deberia pasar
        -vienen de JSON- pero si pasara, repr() da una clave estable igual y
        es preferible a reventar dentro del bucle de tools).
        """
        try:
            return (nombre, json.dumps(argumentos, sort_keys=True, default=repr))
        except (TypeError, ValueError):
            return (nombre, repr(argumentos))

    def resultado_previo(self, nombre: str, argumentos: object) -> str | None:
        """Lo que ya devolvio esta MISMA llamada en este turno, o None."""
        return self._resultados.get(self._clave(nombre, argumentos))

    def recordar(self, nombre: str, argumentos: object, resultado: str) -> None:
        self._resultados[self._clave(nombre, argumentos)] = resultado
