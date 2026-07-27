# Tests del router de fallback (F5.0/T4). Todo con proveedores FALSOS
# inyectados (_llamar) y sin dormir de verdad (_dormir) - asi se prueba la
# logica de reintentos/degradacion sin red y sin esperas reales.
import pytest

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
