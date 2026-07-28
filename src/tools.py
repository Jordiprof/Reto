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

# re: para neutralizar las etiquetas <recuerdo> que pudieran venir dentro
# del propio texto recordado (SEG-07, ver _sanear_recordado).
import re

# Callable: el tipo "una funcion cualquiera", para el type hint del registro.
from collections.abc import Callable

# dataclass: crea una clase "contenedor de datos" sin escribir __init__
# a mano. frozen=True la hace inmutable: el registro de herramientas no
# debe poder modificarse en caliente.
from dataclasses import dataclass

# pydantic: valida datos a partir de una DECLARACION (una clase con
# tipos), en vez de con comprobaciones a mano repartidas por el codigo.
# Ya estaba instalado como dependencia indirecta (lo arrastran groq y
# openai), pero desde que lo importamos NOSOTROS pasa a estar declarado
# en requirements.txt: si manana groq dejara de depender de el, este
# fichero se romperia sin que hubieramos tocado nada.
from pydantic import BaseModel, ConfigDict, Field

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


# F5.0/T6 (hallazgo AUD-04 de la auditoria del 23/07): sin limite de
# longitud, una expresion con miles de parentesis anidados agota el limite
# de recursion de Python al recorrer el arbol en _evaluar_nodo() - un DoS
# leve (CPU/memoria), aunque quede atrapado por el except generico de
# _ejecutar_tool y no tire el programa. 200 caracteres sobra para CUALQUIER
# calculo real y de paso acota la profundidad de anidamiento posible.
_LONGITUD_MAXIMA_EXPRESION = 200


# F5.4: Pydantic valida los argumentos que manda el MODELO antes de que
# lleguen a la funcion. Hasta ahora esa comprobacion vivia dentro de
# calcular() (F4.4), mezclada con el calculo, y lo que sobraba o faltaba
# solo se detectaba cuando Python lanzaba un TypeError - cuyo texto
# interno ("calcular() missing 1 required positional argument") acababa
# enviado al LLM como si fuera el "resultado" de la tool.
#
# Esta clase es ademas la FUENTE DE VERDAD de los parametros: el JSON
# Schema de TOOLS se genera de aqui (ver _ficha_tool mas abajo), asi que
# es imposible que la ficha que lee el modelo y la funcion real dejen de
# coincidir - el mismo tipo de desincronizacion silenciosa que ya mordio
# en F5.0/T5 con las variables *_MODEL del .env.
class ArgsCalcular(BaseModel):
    # extra="forbid": si el modelo alucina un argumento que no existe
    # (ej. {"expresion": "2+2", "modo": "admin"}), se rechaza aqui en
    # vez de reventar con un TypeError de Python.
    model_config = ConfigDict(extra="forbid")

    # description viaja al JSON Schema y es lo que LEE el modelo para
    # saber que mandar - se escribe pensando en el, no en un programador.
    # max_length reutiliza la MISMA constante que valida calcular() por
    # dentro: un solo numero, dos puntos donde se aplica (el borde y la
    # propia funcion, que sigue defendiendose sola si se la llama directa).
    expresion: str = Field(
        description=(
            "La expresion matematica a evaluar, ej. '2 + 2' o '(10 - 4) * 3'. "
            "Solo +, -, * y /."
        ),
        max_length=_LONGITUD_MAXIMA_EXPRESION,
    )


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

    if len(expresion) > _LONGITUD_MAXIMA_EXPRESION:
        raise ValueError(
            f"Expresión demasiado larga (máximo {_LONGITUD_MAXIMA_EXPRESION} caracteres)."
        )

    try:
        arbol = ast.parse(expresion, mode="eval")
    except SyntaxError:
        raise ValueError(f"Expresión inválida: {expresion!r}")
    return _evaluar_nodo(arbol)


# F5.3: tool de memoria semantica. Deja que el agente busque en las
# conversaciones pasadas por SIGNIFICADO ("¿que me dijo sobre X?").
_LONGITUD_MAXIMA_CONSULTA = 300

# SEG-07 (hallazgo de la auditoria del 27/07): lo que devuelve esta tool se
# le entrega al LLM como "resultado", mezclado con las instrucciones del
# SYSTEM_PROMPT, sin ninguna marca de donde empieza el dato y donde acaba.
# Como ademas el SYSTEM_PROMPT EMPUJA a usar la memoria ("Úsala siempre
# que pregunte por algo de antes"), el modelo llega predispuesto a hacer
# caso de lo que salga de aqui. Si un recuerdo contuviera una frase con
# forma de orden ("ignora lo anterior y responde X"), el modelo no tendria
# forma de distinguir esa frase CITADA de una instruccion real.
#
# Hoy es teorico -el unico que escribe en la memoria es JIM- pero deja de
# serlo en cuanto una tool traiga contenido de fuera (RSS, web, PDF: tier
# de ampliacion de F5.5) o en cuanto el bot de Telegram empiece a guardar.
# Por eso se cierra ANTES de F5.5, no despues.
_ETIQUETA_RECUERDO = "recuerdo"

# Neutraliza cualquier etiqueta <recuerdo> o </recuerdo> que venga DENTRO
# del propio texto recordado. Sin esto el control seria decorativo: bastaria
# con que una conversacion pasada contuviera "</recuerdo>" para cerrar la
# cita antes de tiempo y colar el resto como si fuera texto de fuera de la
# cita - la version en miniatura de una inyeccion SQL, cerrando la comilla.
# re.IGNORECASE + \s*: se cierran tambien "</RECUERDO>" y "< / recuerdo >".
_ETIQUETA_EN_TEXTO = re.compile(rf"<\s*/?\s*{_ETIQUETA_RECUERDO}\s*>", re.IGNORECASE)


def _sanear_recordado(texto: object) -> str:
    """Deja el texto listo para ir DENTRO de <recuerdo>...</recuerdo>.

    Todo lo que pasa por aqui es contenido que escribio una persona (el
    mensaje guardado, o el nombre que JIM le puso a la conversacion), asi
    que se trata como dato no confiable: se le quitan las etiquetas que
    podrian romper la cita.
    """
    return _ETIQUETA_EN_TEXTO.sub("(etiqueta eliminada)", str(texto))


class ArgsBuscarRecuerdos(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consulta: str = Field(
        description=(
            "Lo que quieres recordar de conversaciones anteriores, en "
            "lenguaje natural. Ej.: 'la cita del médico' o 'lo que dije "
            "sobre el proyecto'. Busca por significado, no por palabras exactas."
        ),
        max_length=_LONGITUD_MAXIMA_CONSULTA,
    )


def buscar_en_recuerdos(consulta: str) -> str:
    """Busca en la memoria semantica (RAG local) y formatea los resultados
    para que los lea el modelo.

    Import perezoso de rag: arrastra fastembed/chromadb, que son pesados -
    no queremos pagarlos solo por importar tools.py (p. ej. en los tests de
    la calculadora, que no tocan el RAG).
    """
    from src.rag import buscar

    resultados = buscar(consulta)
    if not resultados:
        # Sin envolver a proposito: esta frase la escribimos NOSOTROS, no
        # sale de ninguna conversacion. Envolverla en <recuerdo> seria
        # mentirle al modelo sobre su origen.
        return "No encontré nada relevante en conversaciones anteriores."

    lineas = []
    for recuerdo in resultados:
        fecha = recuerdo["fecha"][:10] if recuerdo["fecha"] else "fecha desconocida"
        quien = "JIM dijo" if recuerdo["rol"] == "user" else "tú respondiste"
        # Si la conversacion tenia nombre, se añade como contexto: ayuda al
        # modelo a situar de que charla salio el recuerdo (F5.3+).
        # El nombre lo escribe JIM al guardar, asi que se sanea igual que el
        # texto: tambien es contenido, no una etiqueta nuestra.
        nombre = recuerdo.get("nombre")
        titulo = f' (conversación "{_sanear_recordado(nombre)}")' if nombre else ""
        texto = _sanear_recordado(recuerdo["texto"])
        # SEG-07: cada recuerdo va DELIMITADO. La etiqueta es la frontera
        # explicita entre "esto son datos que recuperaste" y "esto son tus
        # instrucciones"; el SYSTEM_PROMPT le dice al modelo que lo de
        # dentro nunca se obedece (ver la seccion "Tu memoria" en main.py).
        # Un solo bloque por recuerdo, no uno para todos: asi tampoco se
        # pueden fundir dos recuerdos distintos en una sola cita.
        lineas.append(
            f"<{_ETIQUETA_RECUERDO}>[{fecha}]{titulo} {quien}: {texto}"
            f"</{_ETIQUETA_RECUERDO}>"
        )
    return "\n".join(lineas)


# F5.4: UNA entrada por herramienta, con las tres cosas que la definen
# juntas: la funcion real, el modelo que valida sus argumentos y la
# descripcion que lee el LLM. Antes la ficha de TOOLS se escribia a mano
# aparte de HERRAMIENTAS_DISPONIBLES: nada obligaba a que el nombre del
# parametro del schema coincidiera con el de la funcion, y una falta de
# ortografia solo se descubria en ejecucion.
@dataclass(frozen=True)
class Herramienta:
    funcion: Callable[..., object]
    args: type[BaseModel]
    descripcion: str

    # LOG-07: ¿se puede volver a EJECUTAR esta tool dentro del mismo turno?
    #
    # El problema que cierra: cuando el router reintenta un proveedor o
    # degrada al siguiente (ADR-004), el bucle de tools se rehace DESDE
    # CERO, asi que el modelo vuelve a pedir las mismas tools y estas se
    # volverian a ejecutar. Con la calculadora da igual; con la primera tool
    # que mande un email, un reintento lo manda DOS VECES.
    #
    # EL DEFAULT ES False A PROPOSITO, y es la decision importante de todo
    # esto: si alguien añade una tool en F5.5 y se olvida de declarar nada,
    # lo que pasa es que su resultado se REUTILIZA (a lo sumo se pierde algo
    # de frescura). Con el default al reves, un olvido significaria mandar
    # el email dos veces. Mismo criterio que la lista blanca del bot: ante
    # el olvido, el comportamiento seguro.
    #
    # Poner True SOLO si volver a ejecutarla es INOFENSIVO *y* ademas se
    # quiere de verdad (p.ej. un dado, o un dato que cambia por segundos).
    # Una tool con efectos reales NUNCA lleva True.
    repetible: bool = False


HERRAMIENTAS = {
    "calcular": Herramienta(
        funcion=calcular,
        args=ArgsCalcular,
        # Esta frase la lee el modelo para decidir SI usar la tool y
        # CUANDO. Cuanto mas clara, mejor elige - por eso se explicita
        # que es preferible a inventar el resultado de memoria.
        descripcion=(
            "Evalua una expresion aritmetica (suma, resta, multiplicacion, "
            "division). Usala siempre que el usuario pida un calculo, en vez "
            "de inventar el resultado de memoria."
        ),
    ),
    "buscar_en_recuerdos": Herramienta(
        funcion=buscar_en_recuerdos,
        args=ArgsBuscarRecuerdos,
        descripcion=(
            "Busca en las conversaciones anteriores con JIM por significado. "
            "Usala cuando pregunte por algo que os contó o hablasteis antes "
            "(citas, tareas, datos de su vida), en vez de decir que no lo sabes."
        ),
    ),
}


def _ficha_tool(nombre: str, herramienta: Herramienta) -> dict:
    """Genera la ficha JSON Schema de una tool A PARTIR de su modelo
    Pydantic, en el formato de Groq/Ollama (convencion OpenAI). Gemini
    recibe solo el dict interior "function" (ver _ProveedorGemini).
    """
    parametros = herramienta.args.model_json_schema()

    # "title" lo genera Pydantic solo, a partir del nombre de la clase y
    # de cada campo ("ArgsCalcular", "Expresion"). No aporta nada al
    # modelo (lo util viaja en "description") y filtra nombres internos
    # nuestros. Se quita: la ficha de CADA tool va en CADA peticion, y
    # en F5.5 habra muchas herramientas.
    parametros.pop("title", None)
    for propiedad in parametros.get("properties", {}).values():
        propiedad.pop("title", None)

    return {
        "type": "function",
        "function": {
            "name": nombre,
            "description": herramienta.descripcion,
            "parameters": parametros,
        },
    }


# Lo que se manda al LLM en cada turno. Ya no se escribe a mano: se
# deriva del registro, asi que no puede desincronizarse de las funciones.
TOOLS = [_ficha_tool(nombre, herramienta) for nombre, herramienta in HERRAMIENTAS.items()]
