# Tests del BUCLE compartido de tool-calling (F5.0/T1, adelanto de T6).
#
# Antes de este refactor, el bucle LLM->tool->resultado->LLM estaba copiado
# 3 veces (uno por proveedor) y no tenia NI UN test - justo el codigo mas
# complejo y con mas bugs reales (auditoria, hallazgo #9). Ahora el bucle
# vive una sola vez en _ProveedorLLM.responder() y se puede probar con un
# proveedor FALSO, sin gastar llamadas reales ni depender de ningun SDK.
import pytest

from src.llm_client import _ProveedorLLM, _MAX_PASOS_DE_HERRAMIENTAS
from src.llm_errors import ErrorAutenticacion, ErrorLimitePasos
from src.llm_types import RespuestaLLM, ToolCall


class _ProveedorFalso(_ProveedorLLM):
    """Proveedor de mentira: se le programa de antemano la lista de
    respuestas que ira devolviendo, en orden, en cada vuelta del bucle.
    No toca red ni SDK - solo ejerce la logica del bucle compartido."""

    def __init__(self, respuestas):
        super().__init__(api_key="x", modelo="fake")
        self._respuestas = list(respuestas)
        self.resultados_registrados = []

    def _estado_inicial(self, historial, tools):
        return {"historial": list(historial)}

    def _llamar(self, estado):
        # Va soltando las respuestas programadas, una por vuelta.
        return self._respuestas.pop(0)

    def _registrar_peticion(self, estado, respuesta):
        pass  # al falso no le hace falta reconstruir el estado del SDK

    def _registrar_resultado(self, estado, llamada, resultado):
        # Guardamos (nombre, resultado) para poder afirmar sobre ello.
        self.resultados_registrados.append((llamada.nombre, resultado))


def test_bucle_ejecuta_tool_y_devuelve_texto_final():
    """El caso normal: el modelo pide calcular, el bucle ejecuta la tool
    REAL (calcular '2 + 2' = 4) y en la vuelta siguiente el modelo responde
    con texto final."""
    prov = _ProveedorFalso([
        RespuestaLLM(tool_calls=[ToolCall(nombre="calcular", argumentos={"expresion": "2 + 2"})]),
        RespuestaLLM(texto="El resultado es 4."),
    ])

    final = prov.responder(historial=[], tools=["hay tools"])

    assert final == "El resultado es 4."
    # La tool se ejecuto de verdad y devolvio "4".
    assert prov.resultados_registrados == [("calcular", "4")]


def test_bucle_respuesta_directa_sin_tools():
    """Si el modelo responde con texto a la primera, no se ejecuta ninguna
    tool y se devuelve ese texto tal cual."""
    prov = _ProveedorFalso([RespuestaLLM(texto="Hola, que tal")])

    assert prov.responder(historial=[], tools=None) == "Hola, que tal"
    assert prov.resultados_registrados == []


def test_bucle_corta_al_agotar_los_pasos():
    """Si el modelo NUNCA para de pedir tools (bug suyo), el bucle no se
    cuelga: corta al llegar al tope y lanza ErrorLimitePasos (F5.0/T2 -
    antes devolvia un string _MENSAJE_AGOTADO, ahora es una excepcion
    tipada como el resto de fallos)."""
    respuestas = [
        RespuestaLLM(tool_calls=[ToolCall(nombre="calcular", argumentos={"expresion": "1 + 1"})])
        for _ in range(_MAX_PASOS_DE_HERRAMIENTAS + 2)
    ]
    prov = _ProveedorFalso(respuestas)

    with pytest.raises(ErrorLimitePasos):
        prov.responder(historial=[], tools=["hay tools"])


def test_bucle_propaga_error_llm_sin_atraparlo():
    """F5.0/T2: si _llamar() lanza un ErrorLLM (auth, conexion...), el
    bucle NO lo atrapa - sube tal cual a quien llamo a responder(). Quien
    decide que hacer con el fallo es Agente (agent.py), no el bucle."""

    class _ProveedorQueFalla(_ProveedorLLM):
        def _estado_inicial(self, historial, tools):
            return {}

        def _llamar(self, estado):
            raise ErrorAutenticacion("FalsoProveedor", "clave invalida")

        def _registrar_peticion(self, estado, respuesta):
            pass

        def _registrar_resultado(self, estado, llamada, resultado):
            pass

    with pytest.raises(ErrorAutenticacion) as excinfo:
        _ProveedorQueFalla(api_key="x", modelo="fake").responder(historial=[], tools=None)

    assert excinfo.value.mensaje_usuario == "⚠️ la clave de API de FalsoProveedor no es válida."


def test_tool_call_con_error_de_args_no_ejecuta_la_tool():
    """Si el traductor marco error de parseo (JSON mal formado de Groq,
    F4.4), el bucle NO llama a la tool real: usa el texto de error como
    resultado y sigue."""
    prov = _ProveedorFalso([
        RespuestaLLM(tool_calls=[ToolCall(
            nombre="calcular", argumentos={}, error="Error: argumentos no válidos",
        )]),
        RespuestaLLM(texto="Vale, hubo un error con los argumentos."),
    ])

    final = prov.responder(historial=[], tools=["hay tools"])

    assert final == "Vale, hubo un error con los argumentos."
    assert prov.resultados_registrados == [("calcular", "Error: argumentos no válidos")]
