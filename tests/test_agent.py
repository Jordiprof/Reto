# Tests de Agente (F5.0/T2 + T4): que un fallo del LLM no contamine la
# memoria de la conversacion. Desde T4, Agente llama a self.router, asi que
# aqui sustituimos ese router por uno FALSO tras crear el agente - no toca
# ni red ni la cadena real.
from src.agent import Agente
from src.llm_errors import ErrorAutenticacion


class _RouterFalso:
    """Router de mentira: o devuelve un texto fijo, o lanza un ErrorLLM.
    Sustituye a agente.router en los tests."""

    def __init__(self, texto=None, error=None):
        self._texto = texto
        self._error = error

    def responder(self, historial, tools):
        if self._error is not None:
            raise self._error
        return self._texto


def test_error_llm_no_se_guarda_en_historial():
    """Si el router lanza ErrorLLM (todos los proveedores fallaron),
    Agente.preguntar() debe devolver el mensaje generico del error, pero el
    historial NO debe ganar un turno "assistant" con ese texto - solo se
    queda la pregunta del usuario."""
    agente = Agente(system_prompt="Eres un tutor.", proveedor="groq", api_key="x", modelo="fake")
    agente.router = _RouterFalso(error=ErrorAutenticacion("Groq", "clave invalida"))

    respuesta = agente.preguntar("Hola")

    assert respuesta == "⚠️ la clave de API de Groq no es válida."
    # El historial solo tiene: system prompt + la pregunta del usuario.
    assert [m["role"] for m in agente.historial] == ["system", "user"]


def test_turno_normal_si_se_guarda_en_historial():
    """Caso de control: sin error, la respuesta SI se guarda como turno
    del asistente (para no falsear el test de arriba)."""
    agente = Agente(system_prompt="Eres un tutor.", proveedor="groq", api_key="x", modelo="fake")
    agente.router = _RouterFalso(texto="Hola, ¿en qué te ayudo?")

    respuesta = agente.preguntar("Hola")

    assert respuesta == "Hola, ¿en qué te ayudo?"
    assert [m["role"] for m in agente.historial] == ["system", "user", "assistant"]


# --- Comandos CLI (F5): comando /limpiar -----------------------------


def test_limpiar_historial_conserva_el_system_prompt():
    """/limpiar borra la conversacion pero NO quien es el asistente: el
    system prompt (historial[0]) tiene que seguir ahi, o el agente
    'olvidaria' su personalidad y sus reglas de honestidad."""
    agente = Agente(system_prompt="Eres un tutor.", proveedor="groq", api_key="x", modelo="fake")
    agente.router = _RouterFalso(texto="ok")
    agente.preguntar("Hola")
    agente.preguntar("¿Qué tal?")

    agente.limpiar_historial()

    assert agente.historial == [{"role": "system", "content": "Eres un tutor."}]
