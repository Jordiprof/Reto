"""Gemini escribe la tool-call como TEXTO en vez de usar el mecanismo.

EL FALLO (anotado el 24/07, cerrado el 02/08). Gemini a veces devuelve
esto como respuesta normal, en un `part` de texto:

    <function=buscar_en_recuerdos{"consulta": "mi color favorito"}</function>

El adaptador solo miraba `part.function_call`, asi que la herramienta NUNCA
se ejecutaba y ese churro acababa en la pantalla de JIM.

Es el MISMO fallo que en Groq da `tool_use_failed` -mismo formato nativo de
Llama escrito a mano, mismas tres variantes rotas-, solo que Groq lo caza y
devuelve un 400 y Gemini lo deja pasar. Cambia quien lo pilla, no el fallo.

LA DECISION IMPORTANTE: el rescate es CONSERVADOR. Ante cualquier duda se
descarta, porque adivinar el nombre o los argumentos de una herramienta es
peor que no ejecutarla - con `calcular` daria una cuenta mal, pero la
primera tool que mande un email lo mandaria a quien el parseo se invente.
"""
import pytest

from src.llm_client import _rescatar_tool_call

# Las TRES variantes reales, copiadas de los errores de Groq del 02/08.
VARIANTES_REALES = [
    '<function=buscar_en_recuerdos{"consulta": "mi color favorito"}</function>',
    '<function=buscar_en_recuerdos {"consulta": "mi color favorito"} </function>',
    '<function=buscar_en_recuerdos({"consulta": "mi color favorito"}</function>',
]


@pytest.mark.parametrize("texto", VARIANTES_REALES)
def test_las_tres_variantes_REALES_se_rescatan(texto):
    """El modelo la rompe de forma distinta cada vez porque la escribe a
    mano. Las tres salieron del mismo turno."""
    llamada = _rescatar_tool_call(texto)

    assert llamada is not None
    assert llamada.nombre == "buscar_en_recuerdos"
    assert llamada.argumentos == {"consulta": "mi color favorito"}


def test_tambien_con_el_formato_BIEN_escrito():
    llamada = _rescatar_tool_call('<function=calcular>{"expresion": "2+2"}</function>')

    assert llamada.nombre == "calcular"
    assert llamada.argumentos == {"expresion": "2+2"}


def test_una_respuesta_normal_no_se_toca():
    """Contrapeso imprescindible: esto corre en CADA respuesta de Gemini.
    Un falso positivo convertiria una respuesta buena en una llamada a una
    herramienta."""
    assert _rescatar_tool_call("Tu color favorito es el azul.") is None
    assert _rescatar_tool_call("") is None
    assert _rescatar_tool_call(None) is None


def test_una_tool_que_NO_EXISTE_se_descarta():
    """El modelo puede inventarse el nombre. Si no esta en el registro, no
    llega a _ejecutar_tool."""
    texto = '<function=borrar_todo_el_disco{"ruta": "/"}</function>'

    assert _rescatar_tool_call(texto) is None


@pytest.mark.parametrize("roto", [
    '<function=calcular{esto no es json}</function>',
    '<function=calcular{"expresion": }</function>',
    '<function=calcular</function>',              # sin argumentos
    '<function=calcular>[1, 2, 3]</function>',    # JSON valido pero no un objeto
])
def test_si_no_se_puede_LEER_se_descarta_en_vez_de_adivinar(roto):
    """ANTE LA DUDA, NADA. Adivinar los argumentos de una herramienta es
    peor que no ejecutarla: mismo criterio que el default repetible=False
    de LOG-07 - ante el fallo, el comportamiento inofensivo."""
    assert _rescatar_tool_call(roto) is None


def test_se_lee_aunque_venga_con_texto_alrededor():
    """El modelo suele acompañarlo de prosa ("Voy a mirarlo...")."""
    texto = ('Déjame consultarlo. '
             '<function=calcular{"expresion": "847*293"}</function>')

    llamada = _rescatar_tool_call(texto)

    assert llamada.nombre == "calcular"


def test_los_argumentos_con_llaves_dentro_no_cortan_el_JSON():
    """Un argumento que contenga '}' no puede partir el parseo por la mitad."""
    texto = '<function=calcular{"expresion": "2+2", "nota": "esto } no corta"}</function>'

    llamada = _rescatar_tool_call(texto)

    assert llamada is not None
    assert llamada.argumentos["expresion"] == "2+2"


# --- De punta a punta: lo que sale de _ProveedorGemini --------------------


def _respuesta_gemini(texto):
    """Imita la forma que devuelve el SDK: candidates[0].content.parts[]."""
    from types import SimpleNamespace

    parte = SimpleNamespace(function_call=None, text=texto)
    content = SimpleNamespace(parts=[parte], role="model")
    return SimpleNamespace(candidates=[SimpleNamespace(content=content)], text=texto)


def _llamar_con(texto):
    from src.llm_client import _ProveedorGemini

    class ClienteFalso:
        class models:
            @staticmethod
            def generate_content(**kw):
                return _respuesta_gemini(texto)

    proveedor = _ProveedorGemini("clave", "models/gemini-2.5-flash")
    return _ProveedorGemini._llamar(
        proveedor, {"client": ClienteFalso, "contents": [], "config": None}
    )


def test_la_tool_escrita_como_texto_ACABA_EJECUTANDOSE():
    """Lo que arregla el bug: antes esto salia como `texto` y la herramienta
    no se llamaba nunca."""
    r = _llamar_con('<function=calcular{"expresion": "847*293"}</function>')

    assert r.tool_calls, "la llamada no se rescato: seguiria sin ejecutarse"
    assert r.tool_calls[0].nombre == "calcular"
    assert not r.texto


def test_si_es_ILEGIBLE_no_se_le_enseña_el_churro_a_JIM():
    """La segunda mitad del arreglo. Un volcado de maquinaria interna no es
    una respuesta, y ademas le haria pensar que el bot esta roto de otra
    manera - misma politica que prohibir <fuente>/<recuerdo> en pantalla."""
    r = _llamar_con('<function=calcular{roto roto}</function>')

    assert not r.tool_calls
    assert "<function=" not in (r.texto or "")
    assert "cruzado un cable" in r.texto


def test_una_respuesta_normal_de_Gemini_llega_intacta():
    """Contrapeso: esto corre en CADA respuesta."""
    r = _llamar_con("Tu color favorito es el azul.")

    assert not r.tool_calls
    assert r.texto == "Tu color favorito es el azul."
