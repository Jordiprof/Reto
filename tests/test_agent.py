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


# --- F5.5 #7: leer PDF/Word - el ContextVar que sustituye a pasar el
# adjunto como argumento por toda la tuberia del router (ver el porque en
# la cabecera de src/documentos.py) --------------------------------------


def test_preguntar_fija_el_documento_pendiente_durante_la_llamada():
    """El router (y, dentro de el, la tool leer_documento) tiene que poder
    ver el documento del Agente MIENTRAS dura la llamada."""
    from src.documentos import documento_actual

    visto_durante_la_llamada = []

    class _RouterQueMira:
        def responder(self, historial, tools):
            visto_durante_la_llamada.append(documento_actual())
            return "ok"

    agente = Agente(system_prompt="p", proveedor="groq", api_key="x", modelo="fake")
    agente.router = _RouterQueMira()
    agente.documento_pendiente = "un-adjunto-de-mentira"

    agente.preguntar("Hola")

    assert visto_durante_la_llamada == ["un-adjunto-de-mentira"]


def test_el_documento_se_restaura_a_None_despues_del_turno():
    """Fuera de preguntar() no debe quedar nada fijado - si no se
    restaurara, un uso posterior del ContextVar en el mismo hilo (otro
    Agente, otro turno) veria un documento que no es el suyo."""
    from src.documentos import documento_actual

    agente = Agente(system_prompt="p", proveedor="groq", api_key="x", modelo="fake")
    agente.router = _RouterFalso(texto="ok")
    agente.documento_pendiente = "un-adjunto-de-mentira"

    agente.preguntar("Hola")

    assert documento_actual() is None


def test_el_documento_se_restaura_incluso_si_el_router_falla():
    from src.documentos import documento_actual

    agente = Agente(system_prompt="p", proveedor="groq", api_key="x", modelo="fake")
    agente.router = _RouterFalso(error=ErrorAutenticacion("Groq", "clave invalida"))
    agente.documento_pendiente = "un-adjunto-de-mentira"

    agente.preguntar("Hola")

    assert documento_actual() is None


def test_sin_documento_pendiente_el_agente_no_fija_nada():
    """Caso de control: un Agente que nunca ha recibido un adjunto no debe
    'inventarse' que hay uno."""
    agente = Agente(system_prompt="p", proveedor="groq", api_key="x", modelo="fake")

    assert agente.documento_pendiente is None


def test_limpiar_historial_tambien_suelta_el_documento():
    """'Empezamos de cero' (F5) incluye el documento puesto sobre la mesa:
    sin esto, una charla nueva podria seguir leyendo el PDF de la charla
    anterior sin que nadie lo hubiera vuelto a pedir."""
    agente = Agente(system_prompt="p", proveedor="groq", api_key="x", modelo="fake")
    agente.documento_pendiente = "un-adjunto-de-mentira"

    agente.limpiar_historial()

    assert agente.documento_pendiente is None
