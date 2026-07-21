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
    # F4.4: el type hint "expresion: str" NO se comprueba solo en
    # tiempo de ejecucion - es solo una anotacion, no una validacion
    # real. Si el modelo mandara, por ejemplo, un numero suelto en vez
    # de texto, ast.parse() lanzaria un TypeError con un mensaje tecnico
    # confuso ("expected string or bytes-like object"). Lo comprobamos
    # a mano primero para dar un error claro, como con cualquier
    # entrada que no controlas del todo.
    if not isinstance(expresion, str):
        raise ValueError(f"La expresión debe ser texto, no {type(expresion).__name__}")

    try:
        arbol = ast.parse(expresion, mode="eval")
    except SyntaxError:
        raise ValueError(f"Expresión inválida: {expresion!r}")
    return _evaluar_nodo(arbol)


# F4.2: descripcion de "calcular" como TOOL, en el formato JSON Schema
# que entienden Groq y Ollama (compatible con la convencion de OpenAI,
# verificado contra la doc oficial de Groq - console.groq.com/docs/
# tool-use/local-tool-calling). Gemini usa su propio formato de
# declaracion de tools - ese adaptador se escribe en F4.3, cuando
# montemos el bucle real y haga falta de verdad (mismo criterio que
# con _preguntar_gemini en F3.1: no se construye hasta que se necesita).
#
# Es una lista porque en el futuro habra mas de una tool - cada
# diccionario de la lista describe una funcion distinta.
TOOLS = [
    {
        # "function": el unico tipo que soportan estos proveedores hoy
        # (llamar a una funcion de tu codigo, no ejecutar codigo suyo).
        "type": "function",
        "function": {
            # name DEBE coincidir letra a letra con el nombre real de la
            # funcion en Python - es la clave que se usara en F4.3 para
            # saber cual ejecutar cuando el modelo pida "calcular".
            "name": "calcular",
            # description: la frase que el modelo lee para decidir SI
            # usar esta tool y CUANDO. Cuanto mas clara, mejor elige -
            # por eso se explicita que es preferible a inventar de memoria.
            "description": (
                "Evalua una expresion aritmetica (suma, resta, multiplicacion, "
                "division). Usala siempre que el usuario pida un calculo, en vez "
                "de inventar el resultado de memoria."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    # Este nombre ("expresion") es el que usara main.py
                    # para leer el parametro de la respuesta del modelo -
                    # tiene que coincidir con el argumento de calcular().
                    "expresion": {
                        "type": "string",
                        "description": (
                            "La expresion matematica a evaluar, ej. '2 + 2' "
                            "o '(10 - 4) * 3'. Solo +, -, * y /."
                        ),
                    }
                },
                # Sin "expresion" la tool no se puede ejecutar - el
                # modelo debe mandarla siempre que llame a esta funcion.
                "required": ["expresion"],
            },
        },
    }
]

# F4.3: diccionario que asocia el NOMBRE de cada tool (el string que
# manda el modelo, igual que en TOOLS) con la funcion real de Python
# que hay que ejecutar. Mismo patron que _FUNCIONES en llm_client.py -
# permite ejecutar la tool correcta sin un if/elif por cada una.
HERRAMIENTAS_DISPONIBLES = {
    "calcular": calcular,
}
