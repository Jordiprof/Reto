# inspect: permite mirar la firma real de una funcion de Python en
# tiempo de ejecucion. Lo usamos para comprobar que el schema que lee el
# LLM y los argumentos de la funcion no se han separado (F5.4).
import inspect

import pytest

# _ejecutar_tool vive en llm_client.py (no en tools.py): es la pieza
# que sabe despachar por nombre y capturar errores de CUALQUIER tool,
# no algo propio de la calculadora.
from src.llm_client import _ejecutar_tool
from src.tools import TOOLS, ArgsCalcular, calcular


def test_operaciones_basicas():
    """Las 4 operaciones permitidas, cada una por separado."""
    assert calcular("2 + 2") == 4
    assert calcular("10 - 3") == 7
    assert calcular("4 * 5") == 20
    assert calcular("10 / 4") == 2.5


def test_parentesis_y_precedencia():
    """ast respeta la precedencia normal de operadores y los parentesis,
    sin que tengamos que programarla nosotros a mano."""
    assert calcular("(2 + 3) * 4") == 20
    assert calcular("2 + 3 * 4") == 14  # el * se evalua antes que el +


def test_numero_negativo():
    """El signo negativo (ast.UnaryOp con USub) tambien esta permitido."""
    assert calcular("-3 + 5") == 2
    assert calcular("-3 * -2") == 6


def test_division_entre_cero_lanza_error_controlado():
    """No debe reventar el programa - debe lanzar un error que se pueda
    capturar y mostrar como aviso, igual que los errores de llm_client.py."""
    with pytest.raises(ZeroDivisionError):
        calcular("5 / 0")


@pytest.mark.parametrize("expresion_peligrosa", [
    "__import__('os').system('dir')",  # intento de ejecutar un comando
    "2 ** 3",                          # potencia, operador no permitido
    "x + 1",                           # nombre de variable, no es un numero
    "abrir_archivo('secreto.txt')",    # llamada a funcion
])
def test_expresiones_no_permitidas_se_rechazan(expresion_peligrosa):
    """Esta es la prueba de seguridad real: ninguna de estas debe
    calcularse NUNCA, deben rechazarse con ValueError antes de ejecutar
    nada. parametrize ejecuta el mismo test una vez por cada expresion
    de la lista, en vez de copiar y pegar el mismo assert 4 veces."""
    with pytest.raises(ValueError):
        calcular(expresion_peligrosa)


def test_expresion_con_sintaxis_invalida():
    """Un string que ni siquiera es Python valido (ast.parse falla con
    SyntaxError) tambien debe convertirse en ValueError, no en un
    traceback feo de SyntaxError sin controlar."""
    with pytest.raises(ValueError):
        calcular("2 + + + ")


def test_expresion_de_tipo_incorrecto():
    """F4.4: si el parametro no es texto (ej. el modelo manda un
    numero suelto), debe ser un ValueError claro, no un TypeError
    tecnico escapando de ast.parse()."""
    with pytest.raises(ValueError):
        calcular(2)  # int en vez de str


def test_expresion_demasiado_larga_se_rechaza():
    """F5.0/T6 (AUD-04): una expresion con miles de parentesis anidados
    podria agotar el limite de recursion de Python al recorrer el arbol.
    Se rechaza ANTES de parsear, por longitud, con un ValueError claro -
    no un RecursionError tecnico escapando de _evaluar_nodo()."""
    expresion_gigante = "(" * 300 + "1" + ")" * 300  # 601 caracteres

    with pytest.raises(ValueError):
        calcular(expresion_gigante)


def test_ejecutar_tool_con_parametro_faltante():
    """F4.4, caso limite real: el modelo llama a 'calcular' sin mandar
    'expresion'. _ejecutar_tool no debe reventar - debe devolver un
    string de error que el propio modelo pueda leer y explicar."""
    resultado = _ejecutar_tool("calcular", {})
    assert "Error" in resultado


def test_ejecutar_tool_con_nombre_inventado():
    """F4.4, caso limite real: el modelo "alucina" el nombre de una
    tool que no existe. Debe rechazarse con un mensaje claro, sin
    intentar ejecutar nada."""
    resultado = _ejecutar_tool("buscar_en_internet", {"query": "algo"})
    assert "no existe" in resultado


# --- F5.4: validacion de argumentos con Pydantic ---------------------
# Los dos tests de arriba (F4.4) solo comprueban que aparece la palabra
# "Error": tragan igual el mensaje viejo de Python y el nuevo controlado
# por nosotros, asi que NO habrian detectado si la validacion dejara de
# funcionar. Los de aqui si distinguen.


def test_argumento_que_sobra_se_rechaza():
    """El agujero que abre F5.4: hasta ahora, si el modelo alucinaba un
    argumento de mas, la llamada llegaba a Python y reventaba con un
    TypeError. Con extra="forbid" se rechaza en el borde, y la tool NO
    llega a ejecutarse (por eso no aparece el resultado de 2+2)."""
    resultado = _ejecutar_tool("calcular", {"expresion": "2+2", "modo": "admin"})

    assert "no validos" in resultado
    assert "modo" in resultado          # dice QUE campo sobra
    assert "4" not in resultado          # y NO se ejecuto el calculo


def test_mensajes_de_error_no_filtran_detalles_internos():
    """Mismo principio que los errores tipados de F5.0/T2: el texto que
    se manda al LLM es NUESTRO, no el volcado interno de Python. Sin
    esto, el modelo recibia 'calcular() missing 1 required positional
    argument', que le habla de una funcion de Python que el no conoce."""
    resultado = _ejecutar_tool("calcular", {})

    # Nombra el campo del schema, que es el vocabulario del modelo...
    assert "expresion" in resultado
    # ...y no el de la implementacion de Python.
    assert "positional argument" not in resultado
    assert "calcular()" not in resultado


@pytest.mark.parametrize("argumentos, texto_esperado", [
    ({}, "Field required"),                              # falta
    ({"expresion": 42}, "valid string"),                 # tipo incorrecto
    ({"expresion": "1+" * 150 + "1"}, "at most 200"),    # demasiado largo
])
def test_argumentos_invalidos_dan_mensaje_util(argumentos, texto_esperado):
    """El mensaje debe decirle al modelo QUE arreglar para reintentar
    bien, no solo que hubo un error."""
    resultado = _ejecutar_tool("calcular", argumentos)

    assert "no validos" in resultado
    assert texto_esperado in resultado


def test_ficha_de_tool_se_deriva_del_modelo_pydantic():
    """El motivo de fondo de F5.4: TOOLS ya no se escribe a mano, se
    genera del modelo. Este test es la red de seguridad contra el
    'drift' - si alguien renombra el campo en ArgsCalcular pero no en
    calcular(), o al reves, aqui salta."""
    ficha = next(t for t in TOOLS if t["function"]["name"] == "calcular")
    parametros = ficha["function"]["parameters"]

    # El nombre del parametro del schema es el MISMO que el del modelo...
    assert set(parametros["properties"]) == set(ArgsCalcular.model_fields)
    # ...y el mismo que el argumento real de la funcion de Python.
    assert set(parametros["properties"]) == set(
        inspect.signature(calcular).parameters
    )
    assert parametros["required"] == ["expresion"]


def test_ficha_de_tool_no_lleva_ruido_de_pydantic():
    """Pydantic genera claves 'title' a partir de los nombres internos
    de la clase y de cada campo ('ArgsCalcular', 'Expresion'). No le
    dicen nada al modelo y viajan en CADA peticion, asi que _ficha_tool
    las quita. En F5.5 habra muchas tools y esto se multiplica."""
    parametros = TOOLS[0]["function"]["parameters"]

    assert "title" not in parametros
    for propiedad in parametros["properties"].values():
        assert "title" not in propiedad

    # El limite de longitud SI viaja: es informacion util para el modelo,
    # que antes solo estaba escrita en prosa dentro de la descripcion.
    assert parametros["properties"]["expresion"]["maxLength"] == 200
