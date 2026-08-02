"""Honestidad sobre las herramientas APAGADAS (02/08).

EL FALLO QUE CIERRAN ESTOS TESTS. El 01/08 se le puso al SYSTEM_PROMPT una
regla que le prohibe al modelo decir "no tengo registro de eso" cuando NO
tiene `buscar_en_recuerdos`. El 02/08 Jordi pregunto por su comida favorita
con `memoria` apagada y llama-3.3-70b contesto "no tengo informacion sobre
tus preferencias personales": se salto la regla, y Jordi perdio una sesion
entera creyendo que la memoria compartida estaba rota cuando funcionaba.

La regla no podia funcionar porque le pedia al modelo razonar sobre una
AUSENCIA. Ahora la tool apagada SIGUE declarada y, si la llama, recibe un
DATO nuestro. El prompt es la promesa; el codigo es la garantia.
"""
import pytest

from src.llm_client import _ejecutar_tool
from src.tools import (
    HERRAMIENTAS,
    aviso_si_apagada,
    fijar_categorias_activas,
    restaurar_categorias_activas,
    tools_de,
)


@pytest.fixture
def categorias():
    """Fija las categorias activas del "turno" y las restaura al salir.

    Con `yield` dentro de la fixture, lo de despues del yield se ejecuta
    aunque el test falle: sin eso, un ContextVar mal restaurado se filtraria
    al test siguiente y los fallos apareceran en sitios que no son.
    """
    tokens = []

    def fijar(activas):
        tokens.append(fijar_categorias_activas(activas))

    yield fijar
    for token in reversed(tokens):
        restaurar_categorias_activas(token)


def _nombre_de(categoria: str) -> str:
    """Una tool cualquiera de esa categoria, sacada del registro REAL.

    Se busca en vez de escribirse a fuego para que estos tests no se queden
    mintiendo si un dia se renombra la tool o cambia de categoria.
    """
    for nombre, herramienta in HERRAMIENTAS.items():
        if herramienta.categoria == categoria:
            return nombre
    raise AssertionError(f"no hay ninguna tool de la categoria '{categoria}'")


# --- Lo que ve el modelo (tools_de) ---------------------------------------


def test_la_tool_apagada_sigue_declarada():
    """El fallo original: al omitirla, el modelo no percibia ninguna
    ausencia y contestaba como si hubiera mirado."""
    fichas = tools_de({"calculadora"})
    nombres = {f["function"]["name"] for f in fichas}
    assert _nombre_de("memoria") in nombres


def test_la_ficha_apagada_va_marcada_y_sin_parametros():
    """Marcada, para que el modelo pueda leerlo sin llamarla; y sin
    parametros, porque su ficha viaja en CADA peticion igual que las demas."""
    fichas = tools_de({"calculadora"})
    apagada = next(
        f for f in fichas if f["function"]["name"] == _nombre_de("memoria")
    )
    assert "APAGADA" in apagada["function"]["description"]
    assert apagada["function"]["parameters"]["properties"] == {}


def test_la_ficha_encendida_conserva_sus_parametros():
    """Contrapeso del anterior: lo de arriba no debe habernos comido los
    argumentos de las tools que SI estan activas."""
    fichas = tools_de({"calculadora"})
    encendida = next(
        f for f in fichas if f["function"]["name"] == _nombre_de("calculadora")
    )
    assert encendida["function"]["parameters"]["properties"] != {}
    assert "APAGADA" not in encendida["function"]["description"]


# --- La puerta (aviso_si_apagada) -----------------------------------------


def test_sin_contexto_no_se_bloquea_nada(categorias):
    """None = "nadie ha dicho nada". La CLI, los tests y cualquier llamada
    suelta a _ejecutar_tool tienen que seguir funcionando igual que antes."""
    categorias(None)
    assert aviso_si_apagada(_nombre_de("memoria")) is None


def test_categoria_activa_no_avisa(categorias):
    categorias({"memoria"})
    assert aviso_si_apagada(_nombre_de("memoria")) is None


def test_categoria_apagada_avisa_y_nombra_el_grupo(categorias):
    categorias({"calculadora"})
    aviso = aviso_si_apagada(_nombre_de("memoria"))
    assert aviso is not None
    # El grupo se nombra para que el usuario sepa QUE encender en /tools.
    assert "memoria" in aviso


def test_una_tool_inexistente_no_se_confunde_con_una_apagada(categorias):
    """Son dos cosas distintas y el modelo debe poder distinguirlas: una no
    existe (error suyo), la otra existe y esta apagada (decision de JIM)."""
    categorias({"calculadora"})
    assert aviso_si_apagada("tool_que_no_existe") is None


# --- La garantia de verdad: que NO se ejecute ------------------------------


def test_la_tool_apagada_no_se_ejecuta(categorias, monkeypatch):
    """EL TEST QUE IMPORTA. Que el modelo reciba un aviso bonito da igual si
    por debajo la busqueda se ha hecho: `memoria` se apaga porque manda al
    proveedor conversaciones DESCIFRADAS, asi que lo que hay que garantizar
    es que la funcion real no llegue a correr.
    """
    nombre = _nombre_de("memoria")
    ejecutada = []
    monkeypatch.setitem(
        HERRAMIENTAS,
        nombre,
        # replace() de dataclasses no: HERRAMIENTAS es un dict normal y
        # basta con sustituir la entrada durante el test.
        type(HERRAMIENTAS[nombre])(
            funcion=lambda **kwargs: ejecutada.append(kwargs) or "SECRETO",
            args=HERRAMIENTAS[nombre].args,
            descripcion=HERRAMIENTAS[nombre].descripcion,
            categoria=HERRAMIENTAS[nombre].categoria,
        ),
    )

    categorias({"calculadora"})
    resultado = _ejecutar_tool(nombre, {"consulta": "mi comida favorita"})

    assert ejecutada == [], "la tool apagada NO puede llegar a ejecutarse"
    assert "SECRETO" not in resultado
    assert "apagad" in resultado.lower()


def test_encendida_si_se_ejecuta(categorias):
    """Contrapeso: sin este, borrar la funcionalidad entera dejaria los
    tests en verde."""
    categorias({"calculadora"})
    assert _ejecutar_tool("calcular", {"expresion": "2 + 2"}) == "4"


def test_el_aviso_llega_antes_que_la_validacion_de_argumentos(categorias):
    """La ficha apagada no declara parametros, asi que el modelo la llama
    VACIA. Si la validacion Pydantic fuera antes, contestaria "argumentos no
    validos" - devolviendo justo la confusion que esto viene a quitar.
    """
    categorias({"calculadora"})
    resultado = _ejecutar_tool(_nombre_de("memoria"), {})
    assert "apagad" in resultado.lower()
    assert "no validos" not in resultado


def test_el_aviso_le_prohibe_decir_que_ha_buscado(categorias):
    """El texto es el control: si solo dijera "esta apagada", el modelo
    podria seguir traduciendolo a "no lo encuentro"."""
    categorias({"calculadora"})
    aviso = aviso_si_apagada(_nombre_de("memoria"))
    assert "NO digas" in aviso
