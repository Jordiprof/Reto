# Tests del BUCLE compartido de tool-calling (F5.0/T1, adelanto de T6).
#
# Antes de este refactor, el bucle LLM->tool->resultado->LLM estaba copiado
# 3 veces (uno por proveedor) y no tenia NI UN test - justo el codigo mas
# complejo y con mas bugs reales (auditoria, hallazgo #9). Ahora el bucle
# vive una sola vez en _ProveedorLLM.responder() y se puede probar con un
# proveedor FALSO, sin gastar llamadas reales ni depender de ningun SDK.
import pytest

from src.llm_client import _MAX_PASOS_DE_HERRAMIENTAS, _ProveedorLLM
from src.llm_errors import ErrorAutenticacion, ErrorLimitePasos, ErrorPresupuestoAgotado
from src.llm_types import PresupuestoLlamadas, RespuestaLLM, ToolCall

# F5.0/T6: ProveedorFalso vive en conftest.py (compartido con otros tests
# que lo necesiten), en vez de duplicado aqui.
from tests.conftest import ProveedorFalso as _ProveedorFalso


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


# --- SEG-03: presupuesto de llamadas compartido por turno --------------

def test_presupuesto_agotado_corta_el_bucle_antes_de_la_llamada():
    """Aunque el modelo siga pidiendo tools sin parar, el bucle NO hace mas
    llamadas reales de las que quedan en el presupuesto del turno - se
    corta con ErrorPresupuestoAgotado en vez de seguir hasta
    _MAX_PASOS_DE_HERRAMIENTAS (SEG-03)."""
    respuestas = [
        RespuestaLLM(tool_calls=[ToolCall(nombre="calcular", argumentos={"expresion": "1 + 1"})])
        for _ in range(_MAX_PASOS_DE_HERRAMIENTAS)
    ]
    prov = _ProveedorFalso(respuestas)
    presupuesto = PresupuestoLlamadas(maximo=2)

    with pytest.raises(ErrorPresupuestoAgotado):
        prov.responder(historial=[], tools=["hay tools"], presupuesto=presupuesto)

    assert presupuesto.gastadas == 2
    # Solo se consumieron 2 de las respuestas programadas: la 3a llamada
    # real ni se llego a hacer.
    assert len(prov._respuestas) == _MAX_PASOS_DE_HERRAMIENTAS - 2


def test_sin_presupuesto_no_hay_limite_compartido():
    """presupuesto=None (el default) es el comportamiento de siempre: sin
    limite compartido, solo manda _MAX_PASOS_DE_HERRAMIENTAS - asi los
    tests del bucle de mas arriba, que no pasan presupuesto, siguen
    funcionando igual que antes de SEG-03."""
    prov = _ProveedorFalso([RespuestaLLM(texto="Hola")])

    assert prov.responder(historial=[], tools=None) == "Hola"
