import pytest

from src.tools import calcular


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
