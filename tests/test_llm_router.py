# Tests del router de fallback (F5.0/T4). Todo con proveedores FALSOS
# inyectados (_llamar) y sin dormir de verdad (_dormir) - asi se prueba la
# logica de reintentos/degradacion sin red y sin esperas reales.
import pytest
from google.genai import errors as errores_gemini

from src.llm_errors import (
    ErrorAutenticacion,
    ErrorLimitePeticiones,
    ErrorPeticionInvalida,
    ErrorPresupuestoAgotado,
    ErrorTimeout,
)
from src.llm_router import Eslabon, LLMRouter


def _eslabones(*nombres):
    return [Eslabon(n, "clave", "modelo") for n in nombres]


def test_exito_a_la_primera():
    """Si el primario responde, ni se toca el fallback."""
    def llamar(eslabon, historial, tools, presupuesto):
        return f"ok desde {eslabon.proveedor}"

    router = LLMRouter(_eslabones("groq", "ollama"), _llamar=llamar, _dormir=lambda s: None)

    assert router.responder([], None) == "ok desde groq"
    assert router.ultimo_proveedor == "groq"


def test_reintenta_mismo_proveedor_y_luego_acierta():
    """Fallo transitorio (rate limit) -> espera y reintenta el MISMO
    proveedor; al segundo intento acierta."""
    intentos = {"n": 0}

    def llamar(eslabon, historial, tools, presupuesto):
        intentos["n"] += 1
        if intentos["n"] < 2:
            raise ErrorLimitePeticiones("groq")
        return "ok al segundo intento"

    esperas = []
    router = LLMRouter(
        _eslabones("groq"), max_reintentos=3, backoff_base=1.0,
        _llamar=llamar, _dormir=esperas.append,
    )

    assert router.responder([], None) == "ok al segundo intento"
    assert esperas == [1.0]  # un solo backoff, antes del 2o intento


def test_backoff_exponencial():
    """Reintentos con espera creciente 1s, 2s, 4s (2**intento)."""
    def llamar(eslabon, historial, tools, presupuesto):
        raise ErrorTimeout("groq")  # siempre falla (reintentable)

    esperas = []
    router = LLMRouter(
        _eslabones("groq"), max_reintentos=3, backoff_base=1.0,
        _llamar=llamar, _dormir=esperas.append,
    )

    with pytest.raises(ErrorTimeout):
        router.responder([], None)
    # 3 reintentos -> 3 esperas exponenciales; el 4o intento ya no espera.
    assert esperas == [1.0, 2.0, 4.0]


def test_degrada_al_siguiente_tras_agotar_reintentos():
    """Si el primario agota reintentos, responde el siguiente de la cadena."""
    def llamar(eslabon, historial, tools, presupuesto):
        if eslabon.proveedor == "groq":
            raise ErrorLimitePeticiones("groq")
        return "ok desde ollama"

    router = LLMRouter(
        _eslabones("groq", "ollama"), max_reintentos=2,
        _llamar=llamar, _dormir=lambda s: None,
    )

    assert router.responder([], None) == "ok desde ollama"
    assert router.ultimo_proveedor == "ollama"


def test_error_no_reintentable_degrada_sin_backoff():
    """Un error fatal (auth) NO se reintenta: se degrada directo al
    siguiente, sin dormir ni una vez."""
    esperas = []

    def llamar(eslabon, historial, tools, presupuesto):
        if eslabon.proveedor == "groq":
            raise ErrorAutenticacion("groq")  # no reintentable
        return "ok desde ollama"

    router = LLMRouter(
        _eslabones("groq", "ollama"), max_reintentos=3,
        _llamar=llamar, _dormir=esperas.append,
    )

    assert router.responder([], None) == "ok desde ollama"
    assert esperas == []  # ni un backoff: auth no se reintenta


def test_si_todos_fallan_relanza_el_ultimo_error():
    """Si ningun proveedor responde, se relanza el ultimo ErrorLLM (nada se
    traga en silencio) para que el Agente lo convierta en mensaje_usuario."""
    def llamar(eslabon, historial, tools, presupuesto):
        raise ErrorPeticionInvalida(eslabon.proveedor)

    router = LLMRouter(_eslabones("groq", "ollama"), _llamar=llamar, _dormir=lambda s: None)

    with pytest.raises(ErrorPeticionInvalida):
        router.responder([], None)


def test_cadena_vacia_es_error_de_programacion():
    """Un router sin eslabones no tiene sentido: falla al construirse."""
    with pytest.raises(ValueError):
        LLMRouter([])


# --- SEG-03: presupuesto de llamadas compartido por turno --------------

def test_presupuesto_se_crea_nuevo_en_cada_turno():
    """Cada llamada a responder() (cada turno) parte de un presupuesto
    lleno - un turno agotado no debe dejar "sin cuota" al turno siguiente."""
    vistos = []

    def llamar(eslabon, historial, tools, presupuesto):
        vistos.append(presupuesto.maximo - presupuesto.gastadas)
        presupuesto.gastar(eslabon.proveedor)
        return "ok"

    router = LLMRouter(
        _eslabones("groq"), max_llamadas_por_turno=3,
        _llamar=llamar, _dormir=lambda s: None,
    )

    router.responder([], None)
    router.responder([], None)

    # Las dos veces habia 3 llamadas disponibles ANTES de gastar la 1a:
    # si el presupuesto se compartiera entre turnos, la 2a vez veria menos.
    assert vistos == [3, 3]


def test_presupuesto_agotado_detiene_reintentos_y_fallback():
    """El presupuesto es del TURNO completo (proveedores + reintentos), no
    de un proveedor: si se agota a mitad de un reintento, el router NO
    reintenta el mismo proveedor NI prueba el siguiente de la cadena -
    seguir intentando solo gastaria mas presupuesto sin ninguna llamada
    real de por medio (SEG-03).

    OJO con el orden dentro de "llamar": se registra el intento ANTES de
    gastar, a proposito - asi la lista "intentos" refleja a que eslabon
    llego a LLAMAR el router, aunque esa llamada se corte enseguida por
    presupuesto. Si se registrara despues de gastar(), un mutante que
    quitara el corte en seco (dejando que el router pruebe "ollama" y
    ese intento tambien se corte por presupuesto antes del append) pasaria
    el test sin que se notara - la mutacion NO puede quedar enmascarada."""
    intentos = []

    def llamar(eslabon, historial, tools, presupuesto):
        intentos.append(eslabon.proveedor)
        presupuesto.gastar(eslabon.proveedor)  # simula 1 llamada real gastada
        raise ErrorTimeout(eslabon.proveedor)  # siempre reintentable

    router = LLMRouter(
        _eslabones("groq", "ollama"), max_reintentos=5, max_llamadas_por_turno=2,
        _llamar=llamar, _dormir=lambda s: None,
    )

    with pytest.raises(ErrorPresupuestoAgotado):
        router.responder([], None)

    # 2 intentos gastan el presupuesto entero; el 3o se corta ANTES de
    # gastar mas - y nunca llega a probar "ollama", aunque quedaban
    # reintentos y un fallback disponibles.
    assert intentos == ["groq", "groq", "groq"]


# --- tool_use_failed: el modelo escribe la tool call a mano (02/08) -----
# Medido con 24 llamadas reales a groq/llama-3.3-70b: la MISMA peticion
# fallo 6 veces y funciono 18 (~25%). Antes esto era un ErrorPeticionInvalida
# no reintentable, asi que UNA tirada mala quemaba el proveedor primario
# entero - 16 casos de groq en el log entre el 31/07 y el 02/08.


def test_una_tool_call_mal_generada_se_REINTENTA_sin_perder_el_primario():
    """EL ARREGLO. El modelo escribe mal la llamada, se reintenta el MISMO
    proveedor y a la segunda sale bien: no se degrada a nadie."""
    from src.llm_errors import ErrorToolCallMalGenerada

    intentos = {"n": 0}

    def llamar(eslabon, historial, tools, presupuesto):
        intentos["n"] += 1
        if intentos["n"] < 2:
            raise ErrorToolCallMalGenerada("groq", "tool_use_failed")
        return "ok al segundo intento"

    router = LLMRouter(
        _eslabones("groq", "ollama"), max_reintentos=3, backoff_base=1.0,
        _llamar=llamar, _dormir=lambda s: None,
    )

    assert router.responder([], None) == "ok al segundo intento"
    # Lo que se venia perdiendo: el primario sigue siendo el que contesta.
    assert router.ultimo_proveedor == "groq"


def test_un_400_normal_SIGUE_quemando_el_proveedor():
    """Contrapeso imprescindible: no se ha abierto la mano con los 400 en
    general. Una clave mala o un schema roto fallan siempre, y reintentarlos
    solo gastaria cuota - ese sigue degradando a la primera."""
    intentos = {"n": 0}

    def llamar(eslabon, historial, tools, presupuesto):
        intentos["n"] += 1
        if eslabon.proveedor == "groq":
            raise ErrorPeticionInvalida("groq", "schema roto")
        return "responde el fallback"

    router = LLMRouter(
        _eslabones("groq", "ollama"), max_reintentos=3, backoff_base=1.0,
        _llamar=llamar, _dormir=lambda s: None,
    )

    assert router.responder([], None) == "responde el fallback"
    assert router.ultimo_proveedor == "ollama"
    assert intentos["n"] == 2  # groq UNA vez (sin reintentos) + ollama


# --- Gemini: que se reintenta y que no (02/08) ---------------------------
#
# ESTE TEST NACE DE UN FALLO MIO. La primera version clasificaba por el
# NOMBRE de la clase y buscaba "ResourceExhausted" y "ServiceUnavailable",
# que NO EXISTEN en este SDK - los confundi con los de google.api_core.
# Inspeccionado despues: google.genai.errors solo define APIError,
# ClientError (4xx) y ServerError (5xx).
#
# Y el test de entonces no lo cazo porque **fabricaba clases falsas con
# esos nombres inventados**: verificaba mi suposicion, no la API. Es el
# mismo fallo del test de NASA del 30/07 que este proyecto ya tiene
# documentado - un mock que dice una cosa y una API que hace otra.
#
# Por eso ahora se usan LAS CLASES REALES del SDK, construidas como las
# construye el propio SDK. Si Google cambia la jerarquia, esto se entera.

def _lanzar_en_gemini(error):
    """Ejecuta _ProveedorGemini._llamar con un cliente que lanza `error` y
    devuelve la excepcion tipada que sale."""
    from src.llm_client import _ProveedorGemini

    class ClienteFalso:
        class models:
            @staticmethod
            def generate_content(**kw):
                raise error

    proveedor = _ProveedorGemini("clave", "models/gemini-2.5-flash")
    with pytest.raises(Exception) as capturado:
        _ProveedorGemini._llamar(
            proveedor, {"client": ClienteFalso, "contents": [], "config": None}
        )
    return capturado.value


@pytest.mark.parametrize("codigo,estado,reintentable", [
    (429, "RESOURCE_EXHAUSTED", True),   # cuota: el caso REAL que fallaba
    (503, "UNAVAILABLE", True),          # servidor saturado
    (500, "INTERNAL", True),
    (400, "INVALID_ARGUMENT", False),    # peticion mal formada: fallaria siempre
    (403, "PERMISSION_DENIED", False),
    (404, "NOT_FOUND", False),
])
def test_gemini_se_clasifica_por_CODIGO_HTTP(codigo, estado, reintentable):
    """El codigo es un DATO de la API, no un nombre que yo suponga."""
    Clase = errores_gemini.ClientError if codigo < 500 else errores_gemini.ServerError
    error = Clase(codigo, {"error": {"code": codigo, "message": estado, "status": estado}})

    assert _lanzar_en_gemini(error).reintentable is reintentable


def test_el_SDK_de_google_NO_tiene_las_clases_que_me_invente():
    """Deja constancia del fallo para que nadie las vuelva a usar. Si algun
    dia Google las añade, este test avisa y se puede simplificar el
    clasificador."""
    assert not hasattr(errores_gemini, "ResourceExhausted")
    assert not hasattr(errores_gemini, "ServiceUnavailable")
    # Lo que SI existe, y sobre lo que se construye la clasificacion:
    assert issubclass(errores_gemini.ClientError, errores_gemini.APIError)
    assert issubclass(errores_gemini.ServerError, errores_gemini.APIError)


def test_un_error_sin_codigo_no_revienta_la_clasificacion():
    """Cualquier excepcion rara que no venga del SDK cae en el camino de
    siempre, no en un AttributeError."""
    assert _lanzar_en_gemini(RuntimeError("algo raro")).reintentable is False


# --- Avisos de proveedor caido, en castellano (02/08) --------------------
#
# Peticion de Jordi tras probar: el aviso decia "(ErrorLimitePeticiones)",
# que es el NOMBRE DE LA CLASE y no le dice nada a quien lo lee. Cada
# ErrorLLM ya trae su `plantilla_usuario` redactada para humanos.


def test_el_aviso_de_fallback_explica_el_motivo_EN_CASTELLANO():
    def llamar(eslabon, historial, tools, presupuesto):
        if eslabon.proveedor == "groq":
            raise ErrorLimitePeticiones("groq")
        return "responde el fallback"

    router = LLMRouter(_eslabones("groq", "ollama"), max_reintentos=0,
                       _llamar=llamar, _dormir=lambda s: None)
    router.responder([], None)

    assert "límite" in router.aviso_fallback
    assert "ErrorLimitePeticiones" not in router.aviso_fallback, "eso es el nombre de la clase"
    assert "ollama" in router.aviso_fallback


def test_el_aviso_distingue_TOKENS_de_PETICIONES():
    """Las dos causas se arreglan distinto, y el aviso tiene que decir
    cuál es: por tokens hay que /limpiar, por peticiones basta esperar."""
    def llamar(eslabon, historial, tools, presupuesto):
        if eslabon.proveedor == "groq":
            raise ErrorLimitePeticiones("groq", "Rate limit reached on tokens per minute")
        return "ok"

    router = LLMRouter(_eslabones("groq", "ollama"), max_reintentos=0,
                       _llamar=llamar, _dormir=lambda s: None)
    router.responder([], None)

    assert "TOKENS" in router.aviso_fallback
    assert "/limpiar" in router.aviso_fallback


def test_el_aviso_dice_QUE_MODELO_contesta():
    """Saber que respondio otro modelo importa: cambia la respuesta Y que
    herramientas se llegan a llamar (leccion del 01/08)."""
    def llamar(eslabon, historial, tools, presupuesto):
        if eslabon.proveedor == "groq":
            raise ErrorTimeout("groq")
        return "ok"

    router = LLMRouter(_eslabones("groq", "ollama"), max_reintentos=0,
                       _llamar=llamar, _dormir=lambda s: None)
    router.responder([], None)

    assert router.eslabones[1].modelo in router.aviso_fallback


def test_si_caen_TODOS_se_dice_que_han_caido_todos():
    """Hasta hoy solo se veia el mensaje del ULTIMO error, asi que con los
    tres caidos leias "gemini no responde" y parecia problema de gemini -
    cuando el problema era quedarte sin los tres."""
    def llamar(eslabon, historial, tools, presupuesto):
        raise ErrorLimitePeticiones(eslabon.proveedor)

    router = LLMRouter(_eslabones("groq", "ollama", "gemini"), max_reintentos=0,
                       _llamar=llamar, _dormir=lambda s: None)

    with pytest.raises(ErrorLimitePeticiones):
        router.responder([], None)

    aviso = router.aviso_fallback
    assert "3 proveedores" in aviso
    for proveedor in ("groq", "ollama", "gemini"):
        assert proveedor in aviso
    # Y dice QUE HACER, que es lo que Jordi no sabia: cuando volver.
    assert "minuto" in aviso


def test_si_responde_el_primario_NO_hay_aviso():
    """Contrapeso: un aviso que sale siempre deja de leerse."""
    router = LLMRouter(_eslabones("groq", "ollama"),
                       _llamar=lambda *a: "ok", _dormir=lambda s: None)
    router.responder([], None)

    assert router.aviso_fallback is None
