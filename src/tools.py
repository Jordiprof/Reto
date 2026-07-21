# ast: permite analizar una expresion de Python como arbol de nodos, sin
# ejecutarla. Es la forma segura de "calcular" un string matematico: en
# vez de eval() (que ejecutaria CUALQUIER codigo Python que venga en el
# string), recorremos el arbol a mano y solo aceptamos los nodos que
# nosotros decidimos - numeros y +-*/. Cualquier otra cosa (llamadas a
# funcion, nombres de variable, atributos...) se rechaza antes de
# calcular nada.
import ast
# operator: funciones equivalentes a +, -, *, / pero como funciones
# normales (operator.add(2, 3) == 5). Las usamos en un diccionario para
# no escribir un if/elif largo por cada operador.
import operator

# Diccionario que asocia cada tipo de nodo de operador binario de ast
# con la funcion real que hace esa operacion. Solo estan estos 4 - si
# el arbol trae un operador que no esta aqui (ej. potencia **), no se
# reconoce y se rechaza en _evaluar_nodo.
_OPERADORES_PERMITIDOS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


def _evaluar_nodo(nodo):
    """Recorre el arbol de la expresion a mano, nodo a nodo.

    Solo reconoce numeros, +-*/ y el signo negativo. Cualquier otro
    tipo de nodo (llamadas, nombres, atributos, etc.) lanza ValueError
    antes de intentar calcular nada - por eso es seguro frente a eval().
    """
    if isinstance(nodo, ast.Expression):
        # Nodo raiz que envuelve la expresion real - bajamos a .body.
        return _evaluar_nodo(nodo.body)

    if isinstance(nodo, ast.Constant):
        # Un numero suelto, ej. el "2" de "2 + 2".
        if isinstance(nodo.value, (int, float)):
            return nodo.value
        raise ValueError(f"Valor no permitido: {nodo.value!r}")

    if isinstance(nodo, ast.BinOp):
        # Una operacion binaria: izquierda OPERADOR derecha, ej. "2 + 2".
        tipo_operador = type(nodo.op)
        if tipo_operador not in _OPERADORES_PERMITIDOS:
            raise ValueError(f"Operador no permitido: {tipo_operador.__name__}")
        izquierda = _evaluar_nodo(nodo.left)
        derecha = _evaluar_nodo(nodo.right)
        if tipo_operador is ast.Div and derecha == 0:
            raise ZeroDivisionError("No se puede dividir entre cero")
        return _OPERADORES_PERMITIDOS[tipo_operador](izquierda, derecha)

    if isinstance(nodo, ast.UnaryOp) and isinstance(nodo.op, ast.USub):
        # Signo negativo, ej. el "-3" de "5 + -3" o de "-3 * 2".
        return -_evaluar_nodo(nodo.operand)

    # Cualquier otro tipo de nodo (llamada a funcion, nombre de
    # variable, atributo...) se rechaza aqui, ANTES de ejecutar nada.
    raise ValueError(f"Expresión no permitida: {type(nodo).__name__}")


def calcular(expresion: str) -> float:
    """Evalua una expresion aritmetica simple (+-*/) de forma segura.

    Nunca usa eval() - parsea la expresion con ast y la recorre a mano,
    aceptando solo numeros y los 4 operadores basicos. Pensada para ser
    una tool del agente: el modelo manda el string, esta funcion decide
    si es seguro calcularlo, no el modelo.
    """
    try:
        arbol = ast.parse(expresion, mode="eval")
    except SyntaxError:
        raise ValueError(f"Expresión inválida: {expresion!r}")
    return _evaluar_nodo(arbol)
