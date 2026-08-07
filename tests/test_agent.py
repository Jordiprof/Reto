# Tests de Agente (F5.0/T2 + T4): que un fallo del LLM no contamine la
# memoria de la conversacion. Desde T4, Agente llama a self.router, asi que
# aqui sustituimos ese router por uno FALSO tras crear el agente - no toca
# ni red ni la cadena real.
from src.agent import Agente
from src.documentos import DocumentoAdjunto
from src.llm_errors import ErrorAutenticacion

# Doble de documento adjunto. Era un str suelto hasta el 01/08; se pasa al
# tipo REAL porque desde entonces Agente lee su .nombre para avisar al modelo
# de que hay un adjunto (ver _mensajes_del_turno). Un doble que no cumple el
# tipo prometido esconde justo esa clase de fallo.
_ADJUNTO_FALSO = DocumentoAdjunto(datos=b"x", nombre="falso.pdf", tipo="pdf")



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
    agente.documento_pendiente = _ADJUNTO_FALSO

    agente.preguntar("Hola")

    assert visto_durante_la_llamada == [_ADJUNTO_FALSO]


def test_el_documento_se_restaura_a_None_despues_del_turno():
    """Fuera de preguntar() no debe quedar nada fijado - si no se
    restaurara, un uso posterior del ContextVar en el mismo hilo (otro
    Agente, otro turno) veria un documento que no es el suyo."""
    from src.documentos import documento_actual

    agente = Agente(system_prompt="p", proveedor="groq", api_key="x", modelo="fake")
    agente.router = _RouterFalso(texto="ok")
    agente.documento_pendiente = _ADJUNTO_FALSO

    agente.preguntar("Hola")

    assert documento_actual() is None


def test_el_documento_se_restaura_incluso_si_el_router_falla():
    from src.documentos import documento_actual

    agente = Agente(system_prompt="p", proveedor="groq", api_key="x", modelo="fake")
    agente.router = _RouterFalso(error=ErrorAutenticacion("Groq", "clave invalida"))
    agente.documento_pendiente = _ADJUNTO_FALSO

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
    agente.documento_pendiente = _ADJUNTO_FALSO

    agente.limpiar_historial()

    assert agente.documento_pendiente is None


# --- El aviso de documento adjunto (bug real del 01/08) --------------------
# Jordi adjunto un PDF, el bot dijo "Documento recibido", pregunto "de que
# trata" y el modelo contesto "por favor sube el PDF". Verificado con el log
# (que registra cada tool ejecutada): NUNCA llamo a leer_documento. La
# tuberia funcionaba; lo que faltaba era que el modelo SUPIERA que hay un
# documento - el "Documento recibido" es un mensaje del bot a Telegram y no
# entra en el historial.


def _agente_con(monkeypatch, documento=None):
    from types import SimpleNamespace

    from src.agent import Agente

    monkeypatch.setattr("src.agent.construir_cadena", lambda *a, **kw: None)
    agente = Agente("SOY EL PROMPT", "groq", "x", "m")
    visto = []
    agente.router = SimpleNamespace(
        responder=lambda mensajes, tools=None: visto.append(mensajes) or "ok"
    )
    agente.documento_pendiente = documento
    return agente, visto


def test_sin_documento_el_historial_va_intacto(monkeypatch):
    agente, visto = _agente_con(monkeypatch)

    agente.preguntar("hola")

    assert visto[0] == agente.historial


def test_con_documento_se_avisa_al_modelo(monkeypatch):
    from src.documentos import DocumentoAdjunto

    doc = DocumentoAdjunto(datos=b"x", nombre="informe.pdf", tipo="pdf")
    agente, visto = _agente_con(monkeypatch, doc)

    agente.preguntar("de que trata")

    ultimo = visto[0][-1]["content"]
    assert "informe.pdf" in ultimo
    assert "leer_documento" in ultimo
    assert "de que trata" in ultimo, "la pregunta original no puede perderse"


def test_el_aviso_NO_se_guarda_en_el_historial(monkeypatch):
    """Es andamiaje del turno. Si se guardara, acabaria en el JSON, en el
    RAG y repetido en todos los turnos siguientes."""
    from src.documentos import DocumentoAdjunto

    doc = DocumentoAdjunto(datos=b"x", nombre="informe.pdf", tipo="pdf")
    agente, _visto = _agente_con(monkeypatch, doc)

    agente.preguntar("de que trata")

    guardado = " ".join(m["content"] for m in agente.historial)
    assert "Aviso del sistema" not in guardado
    assert "informe.pdf" not in guardado


def test_el_aviso_no_rompe_a_gemini(monkeypatch):
    """Por esto el aviso se pega al mensaje del usuario en vez de mandarse
    como role="system": Gemini no admite "system" dentro de la lista y su
    traductor se queda con el ULTIMO, asi que un system inyectado aqui
    habria BORRADO el SYSTEM_PROMPT de verdad."""
    from src.documentos import DocumentoAdjunto
    from src.llm_client import traducir_historial_gemini

    doc = DocumentoAdjunto(datos=b"x", nombre="informe.pdf", tipo="pdf")
    agente, visto = _agente_con(monkeypatch, doc)

    agente.preguntar("de que trata")
    _contents, instruccion = traducir_historial_gemini(visto[0])

    assert instruccion == "SOY EL PROMPT"


def test_un_documento_adjunto_NO_secuestra_toda_la_conversacion():
    """BUG del 02/08 (Jordi probando). Con el PDF cargado pregunto quien
    gano el Mundial y el bot contesto "no encuentro en ese documento algo
    que indique que España gano". El aviso decia "si la pregunta va sobre
    el", pero el modelo lo leia como que TODO va sobre el documento: un
    adjunto secuestraba la conversacion entera.

    Se arregla diciendo TAMBIEN el caso contrario, explicito - misma
    leccion que la alucinacion de "pedire permiso" (01/08) y que el aviso
    de herramienta apagada (02/08).
    """
    from types import SimpleNamespace

    from src.agent import Agente

    agente = Agente("system", "groq", "clave", "llama-3.3-70b-versatile")
    agente.documento_pendiente = SimpleNamespace(nombre="apuntes.pdf")
    agente.historial.append({"role": "user", "content": "quien gano el mundial?"})

    aviso = agente._mensajes_del_turno()[-1]["content"]

    assert "NO va sobre el documento" in aviso
    assert "IGNÓRALO" in aviso
    # Y la pregunta original sigue intacta detras del aviso.
    assert aviso.endswith("quien gano el mundial?")


def test_sin_documento_no_se_añade_ningun_aviso():
    """Contrapeso: el andamiaje solo aparece cuando hace falta."""
    from src.agent import Agente

    agente = Agente("system", "groq", "clave", "llama-3.3-70b-versatile")
    agente.historial.append({"role": "user", "content": "hola"})

    assert agente._mensajes_del_turno() == agente.historial
