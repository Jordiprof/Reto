"""El modelo escribe la llamada a la tool como TEXTO y el proveedor la rechaza.

REPRODUCIDO CON LLAMADAS REALES el 02/08: mandando 24 veces la MISMA
peticion a groq/llama-3.3-70b, 6 fallaron y 18 funcionaron (~25%). El
cuerpo del error trae code=tool_use_failed y `failed_generation` con lo que
el modelo escribio a mano:

    <function=buscar_en_recuerdos{"consulta": "..."}</function>

Es el MISMO fallo anotado el 24/07 para Gemini, donde nadie lo caza y el
churro acaba en pantalla. Cambia quien lo pilla, no el fallo.

Hasta hoy esto era ErrorPeticionInvalida, marcado NO reintentable con el
motivo "reenviar la misma peticion fallaria igual" - premisa que los 24
intentos demuestran falsa. Cada tirada mala quemaba el proveedor primario
entero (16 casos de groq en el log entre el 31/07 y el 02/08).
"""
import pytest

from src.llm_client import _codigo_de_error
from src.llm_errors import ErrorPeticionInvalida, ErrorToolCallMalGenerada


class ErrorFalso:
    """Imita la forma REAL del error de Groq, verificada el 02/08 contra la
    API: el codigo NO esta en un atributo `.code` -no existe- sino dentro
    de `body["error"]["code"]`."""

    def __init__(self, body):
        self.body = body


# Cuerpo copiado literal de un fallo real (recortado el mensaje largo).
CUERPO_REAL = {
    "error": {
        "message": "Failed to call a function. Please adjust your prompt.",
        "type": "invalid_request_error",
        "code": "tool_use_failed",
        "failed_generation": '<function=buscar_en_recuerdos{"consulta": "x"}</function>',
    }
}


def test_se_reconoce_el_codigo_del_cuerpo_real():
    assert _codigo_de_error(ErrorFalso(CUERPO_REAL)) == "tool_use_failed"


@pytest.mark.parametrize("cuerpo", [
    None,                      # sin body
    "un texto",                # body que no es dict
    {},                        # sin clave "error"
    {"error": "texto"},        # "error" que no es dict
    {"error": {}},             # sin "code"
    {"error": {"code": 400}},  # code que no es str
])
def test_cualquier_forma_rara_devuelve_None_y_no_revienta(cuerpo):
    """Defensiva a proposito: ante una sorpresa se devuelve None y el error
    se trata como lo que era antes de existir esta funcion. Un diagnostico
    que se cae al leer el diagnostico es peor que no tenerlo."""
    assert _codigo_de_error(ErrorFalso(cuerpo)) is None


def test_un_objeto_sin_body_tampoco_revienta():
    assert _codigo_de_error(object()) is None


def test_ES_reintentable():
    """EL PUNTO DE TODO ESTO. Sin esta linea, el router quema el proveedor
    primario entero a la primera tirada mala."""
    assert ErrorToolCallMalGenerada("Groq", "x").reintentable is True


def test_su_PADRE_sigue_sin_serlo():
    """Contrapeso: no se ha abierto la mano con los 400 en general. Una
    clave mala o un schema roto SI fallan siempre, y reintentarlos solo
    gastaria cuota."""
    assert ErrorPeticionInvalida("Groq", "x").reintentable is False


def test_sigue_siendo_un_ErrorPeticionInvalida():
    """Se hereda en vez de crear una clase suelta para que cualquier codigo
    que ya capturaba ErrorPeticionInvalida siga capturando este."""
    assert isinstance(ErrorToolCallMalGenerada("Groq", "x"), ErrorPeticionInvalida)


def test_el_mensaje_al_usuario_no_filtra_el_churro():
    """El detalle trae `failed_generation`, o sea el eco de la llamada con
    argumentos copiados de la pregunta de JIM. Al usuario se le dice que
    paso, no se le enseña el volcado (politica de logs del 27/07)."""
    error = ErrorToolCallMalGenerada("Groq", str(CUERPO_REAL))
    assert "failed_generation" not in error.mensaje_usuario
    assert "buscar_en_recuerdos" not in error.mensaje_usuario
