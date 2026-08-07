"""Cuando un proveedor se cae, hay que decir POR QUE en castellano.

Petición de Jordi (02/08) tras probar: el aviso ponía
"(ErrorLimitePeticiones)" -el nombre de la clase- y encima "límite
superado" a secas no dice qué hacer. Las dos causas de un rate limit se
arreglan de forma DISTINTA:

  - por PETICIONES: muchos mensajes seguidos. Se pasa en un minuto.
  - por TOKENS: la conversación o el documento ocupan demasiado. Esperar NO
    lo arregla si sigues con el mismo contexto.
"""
import pytest

from src.llm_errors import ErrorLimitePeticiones, ErrorTimeout


@pytest.mark.parametrize("detalle", [
    "Rate limit reached for model X on tokens per minute (TPM)",
    "Limit exceeded: TPM",
    "You have exceeded your token quota",
])
def test_un_limite_por_TOKENS_dice_que_limpiar_la_conversacion(detalle):
    """Esperar no sirve si el contexto sigue siendo igual de gordo."""
    mensaje = ErrorLimitePeticiones("groq", detalle).mensaje_usuario

    assert "TOKENS" in mensaje
    assert "/limpiar" in mensaje


@pytest.mark.parametrize("detalle", [
    "too many requests",
    "RPM exceeded",
])
def test_un_limite_por_PETICIONES_dice_que_esperar(detalle):
    # OJO: "requests per DAY" NO entra aquí. Es cuota diaria y tiene su
    # propio mensaje, porque es la única que no se arregla esperando.
    mensaje = ErrorLimitePeticiones("groq", detalle).mensaje_usuario

    assert "PETICIONES" in mensaje
    assert "minuto" in mensaje


def test_si_no_se_reconoce_la_causa_se_cae_al_mensaje_de_siempre():
    """Es una MEJORA del aviso, nunca un motivo para fallar: un proveedor
    que redacte el error de otra forma no puede romper nada."""
    mensaje = ErrorLimitePeticiones("groq", "algo que no reconocemos").mensaje_usuario

    assert "groq" in mensaje
    assert mensaje.startswith("⚠️")


def test_sin_detalle_tampoco_revienta():
    assert "groq" in ErrorLimitePeticiones("groq").mensaje_usuario


def test_el_aviso_NO_filtra_el_texto_crudo_del_SDK():
    """AUD-07: el detalle interno no llega al usuario final. Puede traer
    ids de organización, nombres de modelo internos o cabeceras."""
    crudo = "Rate limit reached for model X in organization org_01ABCDEF on tokens"
    mensaje = ErrorLimitePeticiones("groq", crudo).mensaje_usuario

    assert "org_01ABCDEF" not in mensaje


def test_un_timeout_sigue_diciendo_que_tardo_demasiado():
    """Contrapeso: los otros errores no se han tocado."""
    assert "tardó demasiado" in ErrorTimeout("ollama").mensaje_usuario


# --- Timeout propio de Ollama (decision de Jordi, 02/08) -----------------


def test_ollama_tiene_MAS_tiempo_que_los_demas():
    """Es el único que acumula timeouts (9 de 218 llamadas) y el que más
    cuota libre le queda: 6,7% de sesión usado."""
    from src.llm_client import _TIMEOUT_SEGUNDOS, timeout_actual

    assert timeout_actual("ollama") == 90.0
    assert timeout_actual("groq") == _TIMEOUT_SEGUNDOS
    assert timeout_actual("gemini") == _TIMEOUT_SEGUNDOS
    assert timeout_actual() == _TIMEOUT_SEGUNDOS


def test_el_timeout_de_un_trabajo_largo_manda_sobre_el_del_proveedor():
    """Si se está condensando un documento, los 180s ganan aunque el
    proveedor tenga el suyo: es una decisión de quien llama, y sabe más."""
    from src.llm_client import (
        _TIMEOUT_TRABAJO_LARGO,
        fijar_timeout,
        restaurar_timeout,
        timeout_actual,
    )

    token = fijar_timeout(_TIMEOUT_TRABAJO_LARGO)
    try:
        assert timeout_actual("ollama") == _TIMEOUT_TRABAJO_LARGO
        assert timeout_actual("groq") == _TIMEOUT_TRABAJO_LARGO
    finally:
        restaurar_timeout(token)

    assert timeout_actual("ollama") == 90.0


# --- Ollama tambien se clasifica por codigo HTTP (03/08) -----------------


def _lanzar_en_ollama(error):
    from src.llm_client import _ProveedorOllama

    class ClienteFalso:
        @staticmethod
        def chat(**kw):
            raise error

    proveedor = _ProveedorOllama("clave", "gpt-oss:120b")
    with pytest.raises(Exception) as capturado:
        _ProveedorOllama._llamar(
            proveedor, {"client": ClienteFalso, "mensajes": [], "tools": None}
        )
    return capturado.value


@pytest.mark.parametrize("codigo,reintentable", [
    (429, True),    # limite
    (503, True),    # servidor saturado
    (500, True),
    (400, False),   # peticion mal formada
    (401, False),
])
def test_ollama_separa_lo_transitorio_de_lo_definitivo(codigo, reintentable):
    """Salio del log de Jordi (03/08): "Ollama: error (ResponseError)"
    degradaba a la primera SIN reintentar, y la llamada habia tardado 65
    segundos - o sea que el servidor estaba haciendo algo, no rechazando.

    Se usa la clase REAL del SDK, no una inventada: es la lección del fallo
    de los nombres de Gemini del 02/08.
    """
    from ollama import ResponseError

    error = ResponseError("algo", codigo)

    assert _lanzar_en_ollama(error).reintentable is reintentable


def test_un_modelo_RETIRADO_sigue_diciendose_aparte():
    """Contrapeso: el 410 tiene su mensaje propio desde el 01/08 (el caso
    de minimax-m2.5) y no puede haberse perdido por esto."""
    from ollama import ResponseError

    error = _lanzar_en_ollama(ResponseError("was retired", 410))

    assert "RETIRADO" in error.detalle or "retirado" in error.detalle
    assert error.reintentable is False


# --- El aviso de tokens, corregido el 03/08 ------------------------------


def test_el_limite_de_tokens_NO_recomienda_limpiar_lo_primero():
    """CORRECCION de un fallo del 02/08: el mensaje decia "prueba con
    /limpiar" y Jordi lo vio en el PRIMER mensaje de una conversación
    nueva, donde no había nada que limpiar. El límite de tokens es casi
    siempre POR MINUTO -de velocidad, no de tamaño- y se recupera solo."""
    mensaje = ErrorLimitePeticiones("groq", "on tokens per minute (TPM)").mensaje_usuario

    assert "minuto" in mensaje
    # /limpiar se menciona, pero como lo segundo y condicionado.
    assert mensaje.index("minuto") < mensaje.index("/limpiar")


def test_una_cuota_DIARIA_dice_que_no_sirve_esperar_un_rato():
    """Es la única que no se arregla ni esperando un rato ni limpiando."""
    mensaje = ErrorLimitePeticiones("groq", "on requests per day (RPD)").mensaje_usuario

    assert "DIARIA" in mensaje
    assert "mañana" in mensaje
    assert "/limpiar" not in mensaje
