# Tests del BUCLE compartido de tool-calling (F5.0/T1, adelanto de T6).
#
# Antes de este refactor, el bucle LLM->tool->resultado->LLM estaba copiado
# 3 veces (uno por proveedor) y no tenia NI UN test - justo el codigo mas
# complejo y con mas bugs reales (auditoria, hallazgo #9). Ahora el bucle
# vive una sola vez en _ProveedorLLM.responder() y se puede probar con un
# proveedor FALSO, sin gastar llamadas reales ni depender de ningun SDK.
import pytest

from src.llm_client import (
    _MAX_PASOS_DE_HERRAMIENTAS,
    _MAX_TOOLS_POR_RONDA,
    _ProveedorLLM,
)
from src.llm_errors import ErrorAutenticacion, ErrorLimitePasos, ErrorPresupuestoAgotado
from src.llm_types import RespuestaLLM, ToolCall, Turno

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
    turno = Turno(maximo=2)

    with pytest.raises(ErrorPresupuestoAgotado):
        prov.responder(historial=[], tools=["hay tools"], turno=turno)

    assert turno.gastadas == 2
    # Solo se consumieron 2 de las respuestas programadas: la 3a llamada
    # real ni se llego a hacer.
    assert len(prov._respuestas) == _MAX_PASOS_DE_HERRAMIENTAS - 2


def test_sin_presupuesto_no_hay_limite_compartido():
    """turno=None (el default) es el comportamiento de siempre: sin
    limite compartido, solo manda _MAX_PASOS_DE_HERRAMIENTAS - asi los
    tests del bucle de mas arriba, que no pasan turno, siguen
    funcionando igual que antes de SEG-03."""
    prov = _ProveedorFalso([RespuestaLLM(texto="Hola")])

    assert prov.responder(historial=[], tools=None) == "Hola"


# --- LOG-07: un reintento NO vuelve a ejecutar las tools ---------------
# El router rehace el bucle DESDE CERO en cada reintento y en cada fallback
# (ADR-004), asi que el modelo vuelve a pedir las mismas tools. Con la
# calculadora da igual; con la primera tool que mande un email, un reintento
# lo mandaria DOS VECES.


def _tool_con_efectos(registro):
    """Simula una tool con efecto real (mandar un email, cobrar...): cada
    ejecucion deja una marca. Contar marcas = contar efectos."""
    from pydantic import BaseModel, ConfigDict

    from src.tools import HERRAMIENTAS, Herramienta

    class ArgsEnviar(BaseModel):
        model_config = ConfigDict(extra="forbid")
        destinatario: str

    def enviar(destinatario):
        registro.append(destinatario)
        return f"enviado a {destinatario}"

    HERRAMIENTAS["enviar_email"] = Herramienta(
        funcion=enviar, args=ArgsEnviar, descripcion="Manda un email (de mentira)."
    )
    return ArgsEnviar


@pytest.fixture
def tool_con_efectos(monkeypatch):
    """Registra una tool con efectos y la quita al acabar el test."""
    from src.tools import HERRAMIENTAS

    registro = []
    _tool_con_efectos(registro)
    yield registro
    HERRAMIENTAS.pop("enviar_email", None)


def test_un_reintento_no_repite_el_efecto(tool_con_efectos):
    """EL TEST DE LOG-07. Se simula lo que hace el router: ejecutar el bucle
    DOS veces con el MISMO Turno (primer intento + reintento). El modelo
    pide la misma tool las dos veces, pero el efecto ocurre UNA sola."""
    turno = Turno(maximo=10)
    peticion = RespuestaLLM(tool_calls=[ToolCall(
        nombre="enviar_email", argumentos={"destinatario": "jordi@example.com"},
    )])

    # Intento 1: pide la tool y luego "falla" (se corta el bucle aqui).
    prov1 = _ProveedorFalso([peticion, RespuestaLLM(texto="ya esta")])
    prov1.responder(historial=[], tools=["hay tools"], turno=turno)

    # Intento 2 (el reintento): bucle NUEVO, mismo Turno.
    prov2 = _ProveedorFalso([peticion, RespuestaLLM(texto="ya esta")])
    prov2.responder(historial=[], tools=["hay tools"], turno=turno)

    # La tool se "pidio" dos veces...
    assert len(prov1.resultados_registrados) == 1
    assert len(prov2.resultados_registrados) == 1
    # ...pero el EFECTO ocurrio una sola vez.
    assert tool_con_efectos == ["jordi@example.com"]
    # Y el modelo recibio el mismo resultado, no un error ni un hueco.
    assert prov2.resultados_registrados[0][1] == "enviado a jordi@example.com"


def test_sin_turno_compartido_el_efecto_SI_se_repite(tool_con_efectos):
    """Caso de control que demuestra que el arreglo es el Turno compartido y
    no otra cosa: con un Turno distinto por intento (o sin turno), la tool
    se ejecuta las dos veces. Es el comportamiento que tenia el proyecto
    ANTES de LOG-07."""
    peticion = RespuestaLLM(tool_calls=[ToolCall(
        nombre="enviar_email", argumentos={"destinatario": "jordi@example.com"},
    )])

    for _ in range(2):
        prov = _ProveedorFalso([peticion, RespuestaLLM(texto="ya esta")])
        prov.responder(historial=[], tools=["hay tools"], turno=Turno(maximo=10))

    assert tool_con_efectos == ["jordi@example.com", "jordi@example.com"]


def test_argumentos_distintos_si_se_ejecutan(tool_con_efectos):
    """La memoria es por llamada CONCRETA (nombre + argumentos), no por
    nombre de tool: mandar un email a otra persona es otra llamada y debe
    ejecutarse de verdad."""
    turno = Turno(maximo=10)

    for destinatario in ("ana@example.com", "luis@example.com"):
        prov = _ProveedorFalso([
            RespuestaLLM(tool_calls=[ToolCall(
                nombre="enviar_email", argumentos={"destinatario": destinatario},
            )]),
            RespuestaLLM(texto="ya esta"),
        ])
        prov.responder(historial=[], tools=["hay tools"], turno=turno)

    assert tool_con_efectos == ["ana@example.com", "luis@example.com"]


def test_el_orden_de_los_argumentos_no_crea_una_llamada_nueva():
    """Dos dicts con las mismas claves en distinto orden son la MISMA
    llamada. Sin ordenar al construir la clave, el reintento se colaria."""
    turno = Turno(maximo=10)
    turno.recordar("t", {"a": 1, "b": 2}, "resultado")

    assert turno.resultado_previo("t", {"b": 2, "a": 1}) == "resultado"


def test_una_tool_repetible_si_se_vuelve_a_ejecutar(monkeypatch):
    """Escape hatch: una tool marcada repetible=True (un dado, un dato que
    cambia por segundos) SI se reejecuta. Solo debe marcarse asi cuando
    volver a ejecutarla es inofensivo - nunca una con efectos reales."""
    from pydantic import BaseModel, ConfigDict

    from src.tools import HERRAMIENTAS, Herramienta

    class SinArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")

    veces = []
    HERRAMIENTAS["tirar_dado"] = Herramienta(
        funcion=lambda: veces.append(1) or len(veces),
        args=SinArgs,
        descripcion="Tira un dado.",
        repetible=True,
    )
    try:
        turno = Turno(maximo=10)
        for _ in range(2):
            prov = _ProveedorFalso([
                RespuestaLLM(tool_calls=[ToolCall(nombre="tirar_dado", argumentos={})]),
                RespuestaLLM(texto="ya"),
            ])
            prov.responder(historial=[], tools=["hay tools"], turno=turno)
        assert len(veces) == 2
    finally:
        HERRAMIENTAS.pop("tirar_dado", None)


def test_el_default_de_repetible_es_el_seguro():
    """LA DECISION IMPORTANTE de LOG-07. Si alguien añade una tool en F5.5 y
    se olvida de declarar nada, el default tiene que ser el que NO duplica
    efectos. Con el default al reves, un olvido = email enviado dos veces."""
    from pydantic import BaseModel

    from src.tools import Herramienta

    herramienta = Herramienta(funcion=lambda: None, args=BaseModel, descripcion="x")

    assert herramienta.repetible is False


def test_las_tools_actuales_no_son_repetibles():
    """calcular y buscar_en_recuerdos son puras: reutilizar su resultado
    dentro de un turno es correcto y ademas ahorra trabajo."""
    from src.tools import HERRAMIENTAS

    for nombre, herramienta in HERRAMIENTAS.items():
        assert herramienta.repetible is False, nombre


# --- AUD-05: tope de tools EJECUTADAS por ronda ------------------------
# Eje distinto de _MAX_PASOS_DE_HERRAMIENTAS (que limita las VUELTAS): en
# UNA sola vuelta el modelo puede pedir 50 tools de golpe. Con tools puras
# es CPU tirada; con tools de efectos (F5.5), 50 emails de un mensaje.


def _peticion_de(n, nombre="calcular"):
    """Una respuesta del modelo pidiendo n tools DE GOLPE (misma ronda),
    cada una con argumentos distintos para que no se reutilicen entre si
    por la memoria del turno de LOG-07."""
    return RespuestaLLM(tool_calls=[
        ToolCall(nombre=nombre, argumentos={"expresion": f"{i} + 1"}, id=f"id{i}")
        for i in range(n)
    ])


def test_solo_se_ejecutan_las_primeras_del_tope():
    """El tope limita lo que se EJECUTA."""
    pedidas = _MAX_TOOLS_POR_RONDA + 4
    prov = _ProveedorFalso([_peticion_de(pedidas), RespuestaLLM(texto="listo")])

    prov.responder(historial=[], tools=["hay tools"])

    ejecutadas = [
        r for _, r in prov.resultados_registrados if not r.startswith("Error: no ejecutada")
    ]
    assert len(ejecutadas) == _MAX_TOOLS_POR_RONDA


def test_a_TODAS_se_les_contesta_aunque_no_se_ejecuten():
    """EL DETALLE DE PROTOCOLO. En Groq/OpenAI, si el mensaje del asistente
    trae N tool_calls, la peticion siguiente debe traer un resultado para
    CADA tool_call_id: si falta uno, la API rechaza la peticion entera y el
    turno se pierde. O sea que 'ignorar' las que sobran romperia el bot."""
    pedidas = _MAX_TOOLS_POR_RONDA + 4
    prov = _ProveedorFalso([_peticion_de(pedidas), RespuestaLLM(texto="listo")])

    prov.responder(historial=[], tools=["hay tools"])

    assert len(prov.resultados_registrados) == pedidas


def test_el_modelo_recibe_el_motivo_para_poder_reintentar():
    """A las no ejecutadas se les contesta con el porque, no con un hueco:
    asi el modelo puede pedir las que faltan en el paso siguiente."""
    prov = _ProveedorFalso([
        _peticion_de(_MAX_TOOLS_POR_RONDA + 1), RespuestaLLM(texto="listo"),
    ])

    prov.responder(historial=[], tools=["hay tools"])

    ultimo = prov.resultados_registrados[-1][1]
    assert "no ejecutada" in ultimo
    assert str(_MAX_TOOLS_POR_RONDA) in ultimo


def test_una_ronda_dentro_del_tope_se_ejecuta_entera():
    """Caso de control: sin esto, 'no ejecutar nunca nada' pasaria los tests
    de arriba y el agente no serviria para nada."""
    prov = _ProveedorFalso([
        _peticion_de(_MAX_TOOLS_POR_RONDA), RespuestaLLM(texto="listo"),
    ])

    prov.responder(historial=[], tools=["hay tools"])

    assert len(prov.resultados_registrados) == _MAX_TOOLS_POR_RONDA
    assert not any(
        r.startswith("Error: no ejecutada") for _, r in prov.resultados_registrados
    )


def test_el_tope_no_gasta_efectos_de_las_que_sobran(tool_con_efectos):
    """Lo que de verdad importa de AUD-05 de cara a F5.5: las tools que
    pasan del tope NO llegan a ejecutarse, asi que no producen su efecto."""
    pedidas = _MAX_TOOLS_POR_RONDA + 5
    peticion = RespuestaLLM(tool_calls=[
        ToolCall(nombre="enviar_email", argumentos={"destinatario": f"n{i}@x.com"}, id=f"i{i}")
        for i in range(pedidas)
    ])
    prov = _ProveedorFalso([peticion, RespuestaLLM(texto="listo")])

    prov.responder(historial=[], tools=["hay tools"], turno=Turno(maximo=10))

    # Se pidieron 8 envios; solo salieron los del tope.
    assert len(tool_con_efectos) == _MAX_TOOLS_POR_RONDA
