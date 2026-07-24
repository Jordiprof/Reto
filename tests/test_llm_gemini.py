# Test de regresion del bug real de F4.6 (F5.0/T6, hallazgo #9 de la
# revision: el codigo mas complejo no tenia NI UN test propio) + cobertura
# directa de _texto_de_gemini() (hallazgo #7: el .text de Gemini puede
# reventar si el candidato no trae texto).
#
# Bug historico (F4.6): Gemini puede devolver VARIAS partes en la misma
# respuesta - una de texto ("Dejame calcular...") seguida de la parte real
# con la peticion de funcion. Mirar solo parts[0] se comia la llamada a la
# tool si no era la primera parte (encontrado a mano por Jordi probando
# main.py). _ProveedorGemini._llamar() ya recorre TODAS las partes (T1).
#
# Los objetos falsos se construyen con types.SimpleNamespace (libreria
# estandar): _ProveedorGemini solo LEE atributos (respuesta.candidates[0]
# .content.parts, cada parte .text/.function_call) - no hace falta una
# clase propia por cada uno, un contenedor de atributos sueltos basta.
from types import SimpleNamespace

from src.llm_client import _ProveedorGemini, _texto_de_gemini


def _parte(text=None, function_call=None):
    return SimpleNamespace(text=text, function_call=function_call)


def _function_call(name, args):
    return SimpleNamespace(name=name, args=args)


def _respuesta(parts=None, candidates=None):
    """Por defecto construye una respuesta con un unico candidato y las
    partes dadas. Si se pasa 'candidates' directamente, se usa tal cual
    (para simular respuestas sin candidatos, F5.0/T6)."""
    if candidates is not None:
        return SimpleNamespace(candidates=candidates)
    return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=parts))])


def _cliente_falso(respuesta_programada):
    """Sustituye a genai.Client(): solo necesita .models.generate_content()
    devolviendo la respuesta programada, sin tocar la red."""
    return SimpleNamespace(
        models=SimpleNamespace(generate_content=lambda **kwargs: respuesta_programada)
    )


def _estado_gemini(respuesta_programada):
    """El 'estado' minimo que _llamar() necesita, sin pasar por
    _estado_inicial() (que montaria el cliente real de Gemini)."""
    return {"client": _cliente_falso(respuesta_programada), "contents": [], "config": None}


# --- Bucle completo: _ProveedorGemini._llamar() ---

def test_encuentra_function_call_fuera_de_la_primera_parte():
    """Regresion del bug F4.6: la function_call va en parts[1], no en
    parts[0] (la parte 0 es solo texto introductorio). Debe encontrarse
    igual, recorriendo TODAS las partes."""
    partes = [
        _parte(text="Dejame calcular eso..."),
        _parte(function_call=_function_call("calcular", {"expresion": "2 + 2"})),
    ]
    proveedor = _ProveedorGemini(api_key="x", modelo="fake")

    respuesta = proveedor._llamar(_estado_gemini(_respuesta(partes)))

    assert respuesta.pide_tools
    assert len(respuesta.tool_calls) == 1
    assert respuesta.tool_calls[0].nombre == "calcular"
    assert respuesta.tool_calls[0].argumentos == {"expresion": "2 + 2"}


def test_function_call_en_la_primera_parte_tambien_funciona():
    """Caso de control: si la function_call SI esta en parts[0] (el caso
    normal, mas comun), tambien debe encontrarse - no es un fix que solo
    valga para el caso raro."""
    partes = [_parte(function_call=_function_call("calcular", {"expresion": "3 * 3"}))]
    proveedor = _ProveedorGemini(api_key="x", modelo="fake")

    respuesta = proveedor._llamar(_estado_gemini(_respuesta(partes)))

    assert respuesta.tool_calls[0].argumentos == {"expresion": "3 * 3"}


def test_respuesta_de_solo_texto_sin_function_call():
    """Caso de control: sin ninguna function_call en ninguna parte, se
    devuelve el texto (via _texto_de_gemini)."""
    partes = [_parte(text="Hola, ¿en qué te ayudo?")]
    proveedor = _ProveedorGemini(api_key="x", modelo="fake")

    respuesta = proveedor._llamar(_estado_gemini(_respuesta(partes)))

    assert not respuesta.pide_tools
    assert respuesta.texto == "Hola, ¿en qué te ayudo?"


# --- _texto_de_gemini() en directo: los casos raros que la motivaron ---

def test_texto_de_gemini_concatena_varias_partes_de_texto():
    """Gemini puede trocear el texto en varias partes - _texto_de_gemini
    debe juntarlas TODAS, no quedarse solo con la primera (a diferencia de
    'parts[0].text', que perderia el resto)."""
    partes = [_parte(text="Hola, "), _parte(text="¿en qué te ayudo?")]

    assert _texto_de_gemini(_respuesta(partes)) == "Hola, ¿en qué te ayudo?"


def test_texto_de_gemini_sin_candidatos_no_revienta():
    """Hallazgo #7: si la respuesta no trae ni un candidato (bloqueada por
    seguridad, p. ej.), NO debe lanzar IndexError - debe devolver ''."""
    assert _texto_de_gemini(_respuesta(candidates=[])) == ""


def test_texto_de_gemini_sin_atributo_candidates_no_revienta():
    """Igual que arriba pero con un objeto que ni siquiera tiene
    'candidates' (AttributeError en vez de IndexError)."""
    assert _texto_de_gemini(SimpleNamespace()) == ""


def test_texto_de_gemini_con_parts_none_no_revienta():
    """Un candidato cuyo content.parts sea None (no una lista vacia) -
    caso limite real, no debe reventar en el 'for' de partes."""
    respuesta_sin_partes = SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=None))]
    )

    assert _texto_de_gemini(respuesta_sin_partes) == ""


def test_texto_de_gemini_con_solo_function_call_devuelve_vacio():
    """El caso que motivo el arreglo: un candidato con SOLO function_call
    y ninguna parte de texto. respuesta.text a pelo lanzaria una excepcion
    aqui; _texto_de_gemini debe devolver '' con calma."""
    partes = [_parte(function_call=_function_call("calcular", {"expresion": "1 + 1"}))]

    assert _texto_de_gemini(_respuesta(partes)) == ""
