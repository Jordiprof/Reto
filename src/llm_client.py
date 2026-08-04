# logging: para registrar cada llamada y cada error en logs/agente.log
# (la configuracion real vive en config.py, aqui solo lo usamos).
# json: los argumentos que manda Groq para una tool vienen como texto JSON
# (no como dict, a diferencia de Ollama) - hay que parsearlos.
# re: para sanear lo que se loguea de una tool (ver _nombre_seguro).
import json
import logging
import re

# time: perf_counter() es un cronometro de alta precision, para medir
# cuanto tarda cada llamada.
import time
from contextvars import ContextVar

# ValidationError: la excepcion que lanza Pydantic cuando los datos no
# encajan con el modelo declarado (F5.4).
from pydantic import ValidationError

# F5.2: modo depuracion opt-in (DEBUG_LOG_CONTENIDO) - ver src/config.py.
from src.config import depuracion_contenido_activa, logger_depuracion

# Excepciones tipadas (F5.0/T2): sustituyen a los strings "⚠️ ..." que se
# detectaban con .startswith() - ver src/llm_errors.py para el porque.
from src.llm_errors import (
    ErrorAutenticacion,
    ErrorConexion,
    ErrorLimitePasos,
    ErrorLimitePeticiones,
    ErrorPeticionInvalida,
    ErrorTimeout,
    ErrorToolCallMalGenerada,
)

# Formas neutras compartidas por los 3 proveedores (F5.0/T1).
# Turno (SEG-03 + LOG-07): el estado que vive lo que dura un turno de
# usuario - presupuesto de llamadas y memoria de tools ya ejecutadas. Ver
# src/llm_types.py para el porque vive ahi.
from src.llm_types import RespuestaLLM, ToolCall, Turno

# HERRAMIENTAS: registro unico de tools (funcion + modelo de args +
# descripcion). Desde F5.4 no basta con la funcion: hace falta tambien su
# modelo Pydantic para validar lo que manda el LLM antes de ejecutar nada.
# (TOOLS, la ficha tecnica JSON Schema, ya no se usa aqui - desde F5.0/T4
# quien decide que tools pasar es Agente, ver src/agent.py).
from src.tools import HERRAMIENTAS, aviso_si_apagada

# Limite de vueltas del bucle LLM -> tool -> resultado -> LLM. Sin esto, si
# el modelo se quedara pidiendo la misma tool una y otra vez (un bug suyo,
# no imposible), el programa se colgaria en un bucle infinito.
_MAX_PASOS_DE_HERRAMIENTAS = 5

# A partir de cuantas llamadas a la MISMA tool en un turno se le avisa al
# modelo de que esta dando vueltas. 3 y no 5 a proposito: con 5 el aviso
# llegaria justo cuando ya se han agotado las rondas, o sea demasiado tarde
# para que sirva de algo.
_AVISAR_REPETICION_TOOL = 3

# AUD-05: cuantas tools se EJECUTAN como mucho en UNA sola respuesta del
# modelo. Es un eje distinto de _MAX_PASOS_DE_HERRAMIENTAS (que limita las
# VUELTAS del bucle): en una sola vuelta, el modelo puede pedir 50 tools de
# golpe -las APIs lo permiten- y hoy se ejecutaban todas.
#
# Con tools puras eso es CPU desperdiciada; con tools de efectos reales
# (F5.5) es 50 emails, 50 recordatorios o 50 peticiones a una API ajena a
# partir de UN mensaje. Junto con el presupuesto por turno (SEG-03, que
# limita las LLAMADAS) y la memoria del turno (LOG-07, que impide
# duplicarlas), cierra el tercer eje: el ANCHO de cada ronda.
#
# 3 es holgado para lo real (pedir el tiempo de dos ciudades y calcular
# algo) y ridiculamente bajo para una avalancha.
_MAX_TOOLS_POR_RONDA = 3

# F5.0/T3 (hallazgo AUD-02 de la auditoria): ninguna llamada de red tenia
# timeout - una conexion colgada bloqueaba el proceso entero sin limite.
# 30s en SEGUNDOS (Groq/Ollama lo piden asi); Gemini lo pide en MILISEGUNDOS,
# ver _ProveedorGemini._estado_inicial.
_TIMEOUT_SEGUNDOS = 30.0

# Timeout AMPLIADO para trabajos largos (02/08). BUG REAL encontrado a la
# primera prueba de /condensar: Jordi le dio un PDF de 284 fragmentos y los
# tres proveedores fallaron, pero Ollama fallo por "timeout tras 30.0s"
# TRES VECES seguidas. No es que no pudiera - es que no le dejamos acabar.
#
# Los 30s son correctos para un turno de chat, donde una espera mas larga
# significa que algo se ha colgado. Resumir 142.000 caracteres es otra cosa:
# el modelo tiene que LEERSELOS y luego escribir, y eso son minutos. El
# mismo numero no puede valer para las dos cosas, igual que _TIMEOUT_TOOLS
# es mas CORTO (8s) porque una API de tiempo que tarda 8s ya esta caida.
_TIMEOUT_TRABAJO_LARGO = 180.0

# Que timeout usar, decidido por quien llama. Es ENTRADA -se fija antes de
# la llamada- que es justo el caso donde un ContextVar SI vale; para salida
# no serviria (leccion del 01/08 con la bandeja de imagenes). Mismo patron
# que el documento adjunto y las categorias activas.
_TIMEOUT_ACTUAL: ContextVar[float | None] = ContextVar("timeout_llm", default=None)

# Timeout PROPIO de algunos proveedores (decision de Jordi, 02/08, con las
# latencias reales de logs/agente.log delante):
#
#   proveedor  llamadas  mediana   p90    max terminado  timeouts
#   groq          146     0,58s   1,82s      38,22s          0
#   ollama        218     2,04s   5,33s      22,55s          9
#   gemini         55     2,14s  13,14s      57,72s          0
#
# Ollama es el UNICO que acumula timeouts, y ademas es el que mas cuota
# libre le queda a Jordi (6,7% de sesion y 13,5% semanal usados), asi que
# es al que interesa dar mas oportunidades. Los otros dos no han dado ni un
# timeout: subirselos solo alargaria la espera cuando algo esta caido.
#
# EL PRECIO, y por eso no se sube a todos: el timeout se paga por CADA
# intento de CADA proveedor. Con 3 proveedores x 3 intentos, pasar todos a
# 90s llevaria el peor caso de 4,5 a 13,5 minutos. Subiendo solo Ollama se
# queda en 7,5, que ya es bastante.
_TIMEOUT_POR_PROVEEDOR = {"ollama": 90.0}


def timeout_actual(proveedor: str | None = None) -> float:
    """Los segundos que se le dan a esta llamada.

    Orden: lo que haya fijado quien llama (el resumen largo) manda sobre
    todo; si no, el propio del proveedor; si no, los 30s de siempre.
    """
    fijado = _TIMEOUT_ACTUAL.get()
    if fijado:
        return fijado
    return _TIMEOUT_POR_PROVEEDOR.get(proveedor or "", _TIMEOUT_SEGUNDOS)


def fijar_timeout(segundos: float | None):
    """Devuelve el token para restaurarlo (mismo contrato que fijar_bandeja).
    SIEMPRE en un try/finally: un timeout largo que se quedara puesto haria
    que un chat normal esperase tres minutos a un proveedor caido."""
    return _TIMEOUT_ACTUAL.set(segundos)


def restaurar_timeout(token) -> None:
    _TIMEOUT_ACTUAL.reset(token)


def _resumir_validacion(error: ValidationError) -> str:
    """Convierte el volcado de Pydantic (que puede ocupar varias lineas,
    con tipos internos y una URL a su documentacion) en UNA linea corta.

    Ese texto acaba enviado al LLM como resultado de la tool, asi que
    debe decirle lo justo para que reintente bien: que campo falla y por
    que. Los mensajes de Pydantic vienen en ingles y se dejan tal cual -
    el modelo los entiende sin problema, y traducirlos obligaria a
    mantener un diccionario propio a cambio de nada.
    """
    partes = []
    for fallo in error.errors():
        # loc es una tupla con la "ruta" al campo que falla; para tools
        # planas es un solo nombre, pero se une por si algun dia hay
        # argumentos anidados.
        campo = ".".join(str(tramo) for tramo in fallo["loc"]) or "(sin campo)"
        partes.append(f"{campo}: {fallo['msg']}")
    return "; ".join(partes)


_CARACTERES_SEGUROS = re.compile(r"[^A-Za-z0-9_.-]")


def _nombre_seguro(texto: object, limite: int = 40) -> str:
    """Deja pasar solo caracteres de identificador (letras/digitos/_.-).

    El nombre de la tool y las claves de "argumentos" los elige el LLM, no
    nosotros: un nombre alucinado con un '\\n' dentro forjaria lineas falsas
    en agente.log, que es justo el fichero que usamos para auditar (log
    injection). Sanear no pierde informacion util - los nombres reales de nuestras
    tools y campos SON identificadores - y cierra ese agujero de paso.
    """
    limpio = _CARACTERES_SEGUROS.sub("?", str(texto))[:limite]
    return limpio or "?"


def _recortar(error: object, limite: int = 300) -> str:
    """Una linea de log con el detalle de un error de CUOTA, sin reventar
    el fichero ni permitir inyeccion de lineas falsas.

    Se usa SOLO donde sabemos que el detalle son cifras de cuota y no
    contenido de la conversacion (ver el except de RateLimitError). Los
    saltos de linea se aplanan por lo mismo que `_nombre_seguro` sanea el
    nombre de una tool: el log se audita, y un '\\n' dentro de un texto
    ajeno forja una entrada que parece nuestra.
    """
    texto = " ".join(str(error).split())
    return texto[:limite] if len(texto) <= limite else texto[:limite] + "…"


def _campos_seguros(argumentos: object) -> str:
    """Devuelve solo los NOMBRES de los campos que mando el LLM, ordenados.

    Los VALORES son PII (el modelo los rellena copiando lo que escribio
    JIM); los NOMBRES vienen del schema Pydantic que escribimos nosotros y
    son lo que hace falta para auditar si el modelo mando la forma correcta
    (el bug que F5.4 vino a cerrar), sin tocar ni un caracter de contenido.
    """
    if not isinstance(argumentos, dict):
        return "(no-es-objeto)"  # JSON valido con forma rara: ya lo cubre el TypeError
    if not argumentos:
        return "(ninguno)"
    return ",".join(sorted(_nombre_seguro(campo) for campo in argumentos))[:200]


# Reconoce la FORMA de una tool-call escrita a mano, para saber que el
# modelo lo intento aunque no se pueda leer. Deliberadamente laxo: aqui solo
# se decide "esto no es una respuesta para JIM".
_PARECE_TOOL_CALL = re.compile(r"<\s*function\s*=", re.IGNORECASE)

# Y esta la LEE. Las tres variantes reales vistas el 02/08 en Groq salen del
# mismo modelo escribiendo mal el mismo formato:
#
#     <function=nombre{"a": 1}</function>      le falta el >
#     <function=nombre {"a": 1} </function>    espacios de mas
#     <function=nombre({"a": 1}</function>     un parentesis de mas
#
# De ahi las partes opcionales: `>?` para el cierre que a veces falta,
# `\(?` para el parentesis, y \s* generoso. El JSON se coge NO GREEDY hasta
# la ultima llave para no tragarse lo que venga detras.
_LEER_TOOL_CALL = re.compile(
    r"<\s*function\s*=\s*([A-Za-z0-9_]+)\s*>?\s*\(?\s*(\{.*\})",
    re.IGNORECASE | re.DOTALL,
)


def _rescatar_tool_call(texto: str | None) -> ToolCall | None:
    """Saca una ToolCall de un texto donde el modelo la escribio a mano, o
    None si no se puede leer con seguridad.

    ES CONSERVADOR A PROPOSITO, y esa es la decision de diseño: ante la duda
    devuelve None y la llamada se descarta. Adivinar el nombre o los
    argumentos de una herramienta seria peor que no ejecutarla - con
    `calcular` daria una cuenta mal, pero la primera tool que mande un email
    lo mandaria a quien el parseo se invente. Mismo criterio que el default
    `repetible=False` de LOG-07: ante el fallo, el comportamiento inofensivo.

    Por eso ademas se comprueba que la tool EXISTA: un nombre que el modelo
    se haya inventado no llega a _ejecutar_tool.
    """
    if not texto:
        return None
    encontrado = _LEER_TOOL_CALL.search(texto)
    if encontrado is None:
        return None

    nombre, argumentos_crudos = encontrado.group(1), encontrado.group(2)
    if nombre not in HERRAMIENTAS:
        logging.warning("Gemini: tool-call de texto con nombre desconocido; descartada")
        return None
    try:
        argumentos = json.loads(argumentos_crudos)
    except json.JSONDecodeError:
        return None
    if not isinstance(argumentos, dict):
        return None
    return ToolCall(nombre=nombre, argumentos=argumentos)


def _codigo_de_error(error: object) -> str | None:
    """El `code` que manda el proveedor dentro del cuerpo del error, o None.

    VERIFICADO CONTRA LA API REAL el 02/08, y no como lo habria escrito de
    memoria: el objeto de excepcion de Groq **no tiene atributo `.code`**
    -devuelve '(no existe)'- y el codigo vive en `body["error"]["code"]`.
    Es el mismo tropiezo que el test de NASA del 30/07, que simulaba
    `{code: 400}` en el cuerpo cuando la API devolvia HTTP 400 de verdad:
    un mock que dice una cosa y una API que hace otra deja tests en verde
    sobre codigo que revienta en real.

    Defensiva a proposito: `body` puede no venir, no ser un dict, o no
    traer "error". Cualquier sorpresa devuelve None, y entonces el error
    se trata como lo que era antes de existir esta funcion.
    """
    cuerpo = getattr(error, "body", None)
    if not isinstance(cuerpo, dict):
        return None
    detalle = cuerpo.get("error")
    if not isinstance(detalle, dict):
        return None
    codigo = detalle.get("code")
    return codigo if isinstance(codigo, str) else None


def _ejecutar_tool(nombre: str, argumentos: dict, turno: Turno | None = None) -> str:
    """Ejecuta una tool por nombre, validando antes sus argumentos.
    Compartida por los 3 proveedores (todos acaban con los argumentos en el
    mismo formato gracias a la capa de traduccion).

    Si la tool no existe, los argumentos no son validos o la funcion falla,
    NO se rompe el programa: se devuelve un string de error, que el modelo
    vera como el "resultado" de la tool.

    turno (LOG-07): si esta MISMA llamada (mismo nombre y mismos argumentos)
    ya se ejecuto en este turno, se devuelve el resultado de entonces sin
    volver a ejecutar nada. Es lo que hace que un reintento del router no
    duplique efectos - ver Herramienta.repetible en src/tools.py.
    """
    # Se mira ANTES de nada: si ya se ejecuto, no se toca la funcion real.
    if turno is not None:
        previo = turno.resultado_previo(nombre, argumentos)
        if previo is not None:
            logging.info(
                "Tool %s | reutilizada del turno | campos=%s",
                _nombre_seguro(nombre), _campos_seguros(argumentos),
            )
            return previo

    inicio = time.perf_counter()
    herramienta = HERRAMIENTAS.get(nombre)
    # Honestidad sobre lo apagado (02/08). LA PUERTA ESTA AQUI, y aqui es
    # donde tiene que estar: este es el unico punto por el que pasan TODAS
    # las tools de TODOS los proveedores, asi que una categoria apagada no
    # se puede ejecutar por ningun camino. Ponerlo en cada tool obligaria a
    # acordarse una vez por tool, que es como se olvidan las cosas.
    #
    # VA ANTES DE VALIDAR LOS ARGUMENTOS a proposito: la ficha de una tool
    # apagada no declara parametros, asi que el modelo la llama vacia y la
    # validacion Pydantic contestaria "argumentos no validos" - devolviendo
    # la misma confusion que esto viene a quitar.
    aviso = aviso_si_apagada(nombre)
    if aviso is not None:
        # No se sale con un return: cayendo por el flujo normal se hereda
        # el log de solo-metadatos y la memoria del turno (LOG-07), y asi
        # una segunda llamada en el mismo turno reutiliza el aviso.
        estado = "apagada"
        resultado = aviso
    elif herramienta is None:
        estado = "inexistente"
        resultado = f"Error: la herramienta '{nombre}' no existe."
    else:
        # BUG REAL de Telegram (31/07): "no mandar nada" no se dice igual en
        # todos los proveedores. `leer_documento` es la primera tool SIN
        # parametros del proyecto, y ahi es donde se nota: Gemini mandaba
        # `{}` (funcionaba en la CLI) y Groq mandaba `null`. Con `**None`
        # Python lanza TypeError, asi que la tool NUNCA se ejecutaba y el
        # modelo recibia "argumentos no validos" - que en el chat se veia
        # como "no puedo leer un documento que no me has proporcionado",
        # culpando al usuario con el fichero ya cargado.
        #
        # Se normaliza AQUI porque este es el unico punto por el que pasan
        # TODAS las tools de TODOS los proveedores: es la misma capa de
        # traduccion de dialectos que ya existe (ver src/llm_types.py).
        # Hacerlo dentro de cada tool obligaria a acordarse una vez por
        # tool, que es como se olvidan las cosas.
        #
        # OJO, solo `None` y la cadena vacia: son las dos formas de decir
        # "nada". Una lista o un numero NO son ausencia de argumentos, son
        # un error del modelo y se siguen rechazando (tiene test).
        if argumentos is None or argumentos == "":
            argumentos = {}
        try:
            # F5.4: el modelo Pydantic decide si lo que manda el LLM es
            # aceptable ANTES de llamar a la funcion. Antes se llamaba a
            # pelo con **argumentos y era Python quien fallaba - con un
            # TypeError cuyo texto interno acababa enviado al modelo.
            # TypeError se captura tambien aqui por si "argumentos" no
            # fuera un diccionario (JSON valido pero con forma rara).
            validados = herramienta.args(**argumentos)
        except (ValidationError, TypeError) as error:
            estado = "args_invalidos"
            if isinstance(error, ValidationError):
                detalle = _resumir_validacion(error)
            else:
                # str(TypeError) trae el nombre de nuestra clase interna y
                # sintaxis de Python ("ArgsX() argument after ** must be a
                # mapping"), que no es vocabulario del modelo. Se sustituye
                # por lo unico que necesita saber para reintentar bien
                # (misma politica que _resumir_validacion, F5.4).
                detalle = "se esperaba un objeto con los parametros, no otra cosa"
            resultado = f"Error: argumentos no validos para '{nombre}' - {detalle}"
        else:
            try:
                # model_dump() devuelve el modelo ya validado como dict
                # limpio: sin campos de mas y con los tipos correctos.
                resultado = str(herramienta.funcion(**validados.model_dump()))
                estado = "ok"
            except Exception as error:
                estado = "fallo"
                resultado = f"Error ejecutando '{nombre}': {error}"

    # AVISO DE BUCLE (01/08). Segunda mitad del arreglo del PDF: la llamada
    # final sin tools evita que el turno se pierda, pero es un rescate. Esto
    # ataca la causa, que es que el modelo no se da cuenta de que esta dando
    # vueltas: llamo a leer_documento CINCO veces cambiando un poco la
    # consulta cada vez ("al final", "el documento", "resumen a lo
    # ultimo"...). Para la memoria de LOG-07 eran cinco llamadas distintas,
    # asi que ninguna se reutilizo y nada le hacia notar la repeticion.
    #
    # El aviso va DENTRO del resultado, que es el sitio donde el modelo no
    # puede no verlo - mismo patron que ya funciono con la fecha de NASA
    # APOD y con el truncado de documentos. Y va DESPUES de ejecutar, no en
    # lugar de: el dato que pidio se le da igual; lo que se añade es que
    # deje de buscar.
    if turno is not None and estado == "ok":
        veces = turno.veces_llamada(nombre) + 1  # +1: esta aun no se apunto
        if veces >= _AVISAR_REPETICION_TOOL:
            resultado = (
                f"⚠️ Ya has llamado a '{nombre}' {veces} veces en este mismo "
                "turno. Deja de buscar y RESPONDE con lo que ya tienes de las "
                "llamadas anteriores. Si algo no aparece, dilo, pero no vuelvas "
                "a llamarme.\n\n" + resultado
            )

    # F5.0/T8 + F5.2 (fuga encontrada el 27/07): esta linea logueaba
    # args=%s y ->%s en claro. Como buscar_en_recuerdos devuelve mensajes
    # DESCIFRADOS de conversaciones pasadas, agente.log acababa conteniendo
    # en claro justo lo que storage.py cifra con Fernet - el cifrado en
    # reposo no sirve de nada si el dato sale en claro por otro canal
    # (mismo razonamiento que el test de privacidad de ChromaDB en
    # tests/test_rag.py). Politica desde hoy: SOLO METADATOS. Se conserva
    # el objetivo de T8 (auditar QUE tool se llamo, con QUE forma y si
    # funciono) sin registrar ni un caracter de contenido.
    logging.info(
        "Tool %s | %s | campos=%s | chars=%d | ms=%.0f",
        _nombre_seguro(nombre),
        estado,
        _campos_seguros(argumentos),
        len(resultado),
        (time.perf_counter() - inicio) * 1000,
    )
    # Modo depuracion opt-in: SOLO si DEBUG_LOG_CONTENIDO esta encendida a
    # proposito (ver src/config.py). Va a un logger APARTE con
    # propagate=False, y por tanto a un fichero aparte
    # (logs/debug_contenido.log): agente.log NUNCA ve esto, apagado o
    # encendido. %r y no %s: en un fichero de depuracion interesa ver los
    # saltos de linea escapados y las comillas (distinguir "3" de 3).
    if depuracion_contenido_activa():
        logger_depuracion().debug("Tool %s args=%r -> %r", nombre, argumentos, resultado)

    # LOG-07: se apunta el resultado para que un reintento no vuelva a
    # ejecutar esta llamada. Las marcadas repetible=True se dejan fuera a
    # proposito: son las que SI deben volver a ejecutarse.
    #
    # Ojo al "herramienta is None": una tool inexistente no esta en el
    # registro, asi que no hay repetible que consultar - y su resultado es
    # un error fijo, perfectamente reutilizable.
    if turno is not None and (herramienta is None or not herramienta.repetible):
        turno.recordar(nombre, argumentos, resultado)
    return resultado


def traducir_historial_gemini(historial: list) -> tuple[list, str | None]:
    """Traduce el historial canonico (system/user/assistant + content) al
    formato propio de Gemini. Devuelve (contents, system_instruction).

    Funcion PURA a proposito: no toca la red ni el historial original, solo
    transforma una lista en otra. Asi se puede probar con pytest sin gastar
    llamadas reales (F3.4). Sin guion bajo inicial: los tests la importan.
    """
    # Gemini no acepta un mensaje con rol "system" dentro de la lista: las
    # instrucciones estables van aparte, como system_instruction.
    system_instruction = None
    # Lista NUEVA (no mutamos historial): si la modificaramos en el sitio, el
    # formato de Gemini contaminaria el historial canonico que se usa para
    # Groq/Ollama y para guardar en JSON.
    contents = []

    for mensaje in historial:
        if mensaje["role"] == "system":
            system_instruction = mensaje["content"]
        else:
            # Dos diferencias de nombre respecto al formato canonico:
            # 1) el rol del modelo se llama "model", no "assistant";
            # 2) el texto va en "parts" (lista de trozos), no en "content".
            rol = "model" if mensaje["role"] == "assistant" else "user"
            contents.append({"role": rol, "parts": [{"text": mensaje["content"]}]})

    return contents, system_instruction


def _texto_de_gemini(respuesta) -> str:
    """Extrae el texto de una respuesta de Gemini de forma DEFENSIVA.

    En vez de usar respuesta.text a pelo (que puede lanzar una excepcion si
    el candidato no trae ninguna parte de texto - p. ej. cuando solo trae
    una function_call, o cuando la respuesta viene bloqueada por seguridad),
    recorremos las partes y concatenamos solo el texto que haya. Tolerante:
    si no hay texto, devuelve "" en vez de reventar (hallazgo #7 de la
    auditoria de seguridad del 23/07).
    """
    try:
        candidato = respuesta.candidates[0]
    except (AttributeError, IndexError, TypeError):
        return ""
    partes = getattr(candidato.content, "parts", None) or []
    return "".join(p.text for p in partes if getattr(p, "text", None))


class _ProveedorLLM:
    """Clase base: define el BUCLE compartido (LLM -> tool -> resultado ->
    LLM) una sola vez. Cada proveedor concreto solo implementa las 4 piezas
    que de verdad cambian entre SDKs; el bucle no las conoce.
    """

    # Nombre para los logs de latencia; lo fija cada subclase.
    _nombre = "?"

    def __init__(self, api_key: str, modelo: str):
        self.api_key = api_key
        self.modelo = modelo

    def responder(self, historial: list, tools: list | None,
                  turno: Turno | None = None) -> str:
        """El bucle unico. Recibe el historial canonico y, opcionalmente, la
        lista de tools disponibles (None = modo sin herramientas). Devuelve
        el texto final de la respuesta - todo el ir y venir de tool-calling
        queda resuelto aqui dentro.

        turno (SEG-03 + LOG-07): lo crea LLMRouter.responder() una vez por
        turno de usuario y viaja hasta aqui - None cuando se llama a este
        metodo directamente (p.ej. los tests del bucle en
        tests/test_llm_loop.py), en cuyo caso no hay ni presupuesto que
        gastar ni memoria de tools que consultar.
        """
        estado = self._estado_inicial(historial, tools)

        for _ in range(_MAX_PASOS_DE_HERRAMIENTAS):
            # Se gasta ANTES de llamar, no despues: si ya no queda
            # presupuesto, esta llamada real ni se hace.
            if turno is not None:
                turno.gastar(self._nombre)
            # _llamar() puede lanzar ErrorLLM (auth, conexion, limite,
            # presupuesto agotado...) - NO se atrapa aqui: sube tal cual a
            # quien llamo a responder(), que decide que hacer (agent.py, y
            # el router T4).
            respuesta = self._llamar(estado)

            if not respuesta.pide_tools:
                # Respuesta final: el modelo ya no pide herramientas.
                return respuesta.texto

            # El modelo pidio una o mas tools: registramos SU peticion (en el
            # formato que su propio SDK necesita ver luego) y ejecutamos.
            self._registrar_peticion(estado, respuesta)
            if len(respuesta.tool_calls) > _MAX_TOOLS_POR_RONDA:
                logging.warning(
                    "AUD-05: %s pidio %d tools en una ronda; se ejecutan %d",
                    self._nombre, len(respuesta.tool_calls), _MAX_TOOLS_POR_RONDA,
                )
            for posicion, llamada in enumerate(respuesta.tool_calls):
                # AUD-05: pasado el tope NO se ejecuta, pero SI se contesta.
                #
                # Contestar a todas es OBLIGATORIO, no cortesia: en el
                # protocolo de Groq/OpenAI, si un mensaje del asistente trae
                # N tool_calls, la peticion siguiente debe incluir un
                # resultado para CADA tool_call_id - si falta uno, la API
                # rechaza la peticion entera y el turno se pierde. Por eso se
                # recorren todas y lo que cambia es solo si se EJECUTAN.
                #
                # El texto explica el motivo a proposito: el modelo lo lee y
                # puede reintentar pidiendo menos de golpe, en vez de quedarse
                # sin saber por que no le llego el dato.
                if posicion >= _MAX_TOOLS_POR_RONDA:
                    resultado = (
                        f"Error: no ejecutada. Has pedido "
                        f"{len(respuesta.tool_calls)} herramientas a la vez y el "
                        f"maximo es {_MAX_TOOLS_POR_RONDA}. Pide las que falten "
                        f"en el paso siguiente."
                    )
                # Si el traductor marco un error de parseo de argumentos
                # (JSON mal formado de Groq, F4.4), NO se ejecuta la tool:
                # ese texto de error hace de "resultado".
                elif llamada.error:
                    resultado = llamada.error
                else:
                    resultado = _ejecutar_tool(llamada.nombre, llamada.argumentos, turno)
                self._registrar_resultado(estado, llamada, resultado)

        # SE ACABARON LAS RONDAS. Antes esto era un `raise ErrorLimitePasos`
        # y ahi estaba el fallo que encontro Jordi el 01/08 probando un PDF:
        #
        #   pregunta -> el modelo busca 5 veces en el documento sin llegar a
        #   contestar -> se agotan las rondas -> ErrorLimitePasos -> el
        #   router DEGRADA al siguiente proveedor -> que empieza el bucle
        #   DESDE CERO y hace exactamente lo mismo -> y el tercero igual ->
        #   "no quedan mas proveedores" y el turno se pierde ENTERO.
        #
        # Se veia en el log: ollama 5 busquedas, groq sin cuota, gemini otras
        # 5 busquedas, y ninguna respuesta. Se habian ejecutado DIEZ
        # busquedas correctas y aun asi el usuario no recibio nada.
        #
        # Lo absurdo era tirar trabajo bueno: el modelo YA tenia el material,
        # lo que no hacia era parar de buscar. Asi que en vez de rendirse se
        # le hace UNA llamada mas SIN TOOLS - sin herramientas que pedir, no
        # le queda otra que redactar la respuesta con lo que ya reunio.
        #
        # Es una degradacion, no un arreglo perfecto: la respuesta se apoya
        # en busquedas parciales. Pero una respuesta parcial y avisada es
        # infinitamente mejor que tres proveedores quemados y un error.
        logging.warning(
            "%s agoto los %d pasos de tools; se le pide respuesta final sin tools",
            self._nombre, _MAX_PASOS_DE_HERRAMIENTAS,
        )
        if turno is not None:
            turno.gastar(self._nombre)
        respuesta = self._llamar(self._estado_sin_tools(estado))
        if respuesta.pide_tools or not respuesta.texto:
            # Ni asi contesta: ahora si es un fallo de verdad y el router
            # hace bien en probar otro proveedor.
            raise ErrorLimitePasos(self._nombre)
        return respuesta.texto

    # --- Piezas que cada proveedor implementa (lo unico que cambia) ---

    def _estado_inicial(self, historial: list, tools: list | None):
        """Prepara el cliente y el estado de trabajo (mensajes/contents)."""
        raise NotImplementedError

    def _estado_sin_tools(self, estado):
        """El MISMO estado (con toda la conversacion y los resultados de las
        tools ya ejecutadas) pero sin herramientas que ofrecer.

        Sirve para la llamada final de rescate: sin tools que pedir, el
        modelo no puede seguir buscando y tiene que redactar la respuesta.

        Groq y Ollama guardan las tools en estado["tools"], asi que les vale
        esta version. Gemini las lleva dentro de un objeto `config` ya
        construido y lo sobreescribe.
        """
        return {**estado, "tools": None}

    def _llamar(self, estado) -> RespuestaLLM:
        """Hace UNA llamada al modelo y traduce su respuesta a RespuestaLLM."""
        raise NotImplementedError

    def _registrar_peticion(self, estado, respuesta: RespuestaLLM) -> None:
        """Anade al estado la peticion de tools del modelo (formato del SDK)."""
        raise NotImplementedError

    def _registrar_resultado(self, estado, llamada: ToolCall, resultado: str) -> None:
        """Anade al estado el resultado de una tool (formato del SDK)."""
        raise NotImplementedError


class _ProveedorGroq(_ProveedorLLM):
    _nombre = "groq"

    def _estado_inicial(self, historial, tools):
        # Import dentro: el SDK de Groq solo se carga si se usa este proveedor.
        from groq import Groq

        # Groq usa el formato canonico tal cual (system/user/assistant +
        # content), asi que los mensajes viajan sin traducir.
        # timeout=_TIMEOUT_SEGUNDOS (F5.0/T3): sin esto, por defecto Groq
        # espera 1 minuto entero antes de rendirse - demasiado para un bot
        # que debe seguir vivo (verificado en groq-python/README.md).
        return {
            "client": Groq(api_key=self.api_key, timeout=timeout_actual(self._nombre)),
            "mensajes": list(historial),
            "tools": tools,
        }

    def _llamar(self, estado):
        # APIError es la clase BASE de la que heredan los errores concretos de
        # Groq (y del que hereda tambien groq.BadRequestError con
        # tool_use_failed, no capturado por las especificas - hallazgo real
        # de F4.5). Sin este ultimo except, el programa se caia.
        # APITimeoutError hereda de APIConnectionError (verificado en el SDK) -
        # por eso se captura ANTES: si fuera despues, nunca se alcanzaria.
        from groq import (
            APIConnectionError,
            APIError,
            APITimeoutError,
            AuthenticationError,
            RateLimitError,
        )

        client = estado["client"]
        # Solo pasamos tools si las hay (modo sin herramientas = tools None).
        kwargs = {"model": self.modelo, "messages": estado["mensajes"]}
        if estado["tools"]:
            kwargs["tools"] = estado["tools"]

        inicio = time.perf_counter()
        try:
            respuesta = client.chat.completions.create(**kwargs)
        except AuthenticationError as error:
            logging.error("Groq: clave de API invalida")
            raise ErrorAutenticacion("Groq", str(error)) from error
        except APITimeoutError as error:
            logging.error(f"Groq: timeout tras {timeout_actual(self._nombre)}s")
            raise ErrorTimeout("Groq", str(error)) from error
        except APIConnectionError as error:
            logging.error("Groq: fallo de conexion")
            raise ErrorConexion("Groq", str(error)) from error
        except RateLimitError as error:
            # 03/08: se GUARDA el detalle del proveedor, no solo "limite
            # superado". Salio intentando diagnosticar por que groq se
            # agotaba: el log repetia quince veces "Groq: limite de
            # peticiones superado" y era imposible saber si el limite era
            # por minuto o del dia -que es justo lo que decide si esperar
            # sirve de algo-. El docstring de ErrorLLM ya prometia que el
            # detalle iba al log "tan detallado como antes"; no iba.
            #
            # SOLO para rate limit, y por eso no rompe la politica de logs
            # de solo metadatos (27/07): el texto de un 429 son cifras de
            # cuota ("on tokens per day (TPD): Limit 100000, Used 99876"),
            # nunca contenido de la conversacion. En los demas except sigue
            # yendo solo el tipo, porque ahi el detalle SI puede arrastrar
            # el cuerpo de la peticion.
            logging.error("Groq: limite de peticiones superado | %s", _recortar(error))
            raise ErrorLimitePeticiones("Groq", str(error)) from error
        except APIError as error:
            # 02/08: se separa el caso en que el MODELO escribio mal la
            # llamada a la tool (code=tool_use_failed), porque ese SI hay
            # que reintentarlo - medido: la misma peticion falla ~25% de
            # las veces. Ver ErrorToolCallMalGenerada para el detalle.
            if _codigo_de_error(error) == "tool_use_failed":
                logging.warning("Groq: el modelo genero mal una tool call; reintentable")
                raise ErrorToolCallMalGenerada("Groq", str(error)) from error
            # F5.2 (27/07): antes iba {error} entero al log. El str() de un
            # error de SDK puede traer el cuerpo de la peticion - de hecho
            # groq.BadRequestError con tool_use_failed HACE ECO del tool call
            # fallido (ver comentario de arriba), con argumentos que el
            # modelo copio de la pregunta de JIM. El TIPO basta para saber
            # que paso; el detalle completo sigue vivo en
            # ErrorPeticionInvalida.detalle (en memoria, no en disco) y
            # visible con DEBUG_LOG_CONTENIDO si hace falta depurar a fondo.
            logging.error("Groq: error de API no especifico (%s)", type(error).__name__)
            raise ErrorPeticionInvalida("Groq", str(error)) from error
        logging.info(f"Latencia (groq/{self.modelo}): {time.perf_counter() - inicio:.2f}s")

        mensaje = respuesta.choices[0].message
        if not mensaje.tool_calls:
            return RespuestaLLM(texto=mensaje.content)

        tool_calls = []
        for llamada in mensaje.tool_calls:
            # Groq (como OpenAI) manda los argumentos como texto JSON, no como
            # dict - hay que parsearlo. Puede fallar si el modelo devuelve un
            # JSON mal formado (raro, pero F4.4 lo vio en real): se marca como
            # error en el ToolCall en vez de reventar.
            try:
                argumentos = json.loads(llamada.function.arguments)
                tool_calls.append(ToolCall(
                    nombre=llamada.function.name, argumentos=argumentos, id=llamada.id,
                ))
            except json.JSONDecodeError as error:
                tool_calls.append(ToolCall(
                    nombre=llamada.function.name, argumentos={}, id=llamada.id,
                    error=f"Error: argumentos no válidos para '{llamada.function.name}' ({error})",
                ))
        # 'raw' = el mensaje del SDK; la API necesita volver a verlo para
        # saber a que peticion responde cada resultado que le mandemos.
        return RespuestaLLM(tool_calls=tool_calls, raw=mensaje)

    def _registrar_peticion(self, estado, respuesta):
        estado["mensajes"].append(respuesta.raw)

    def _registrar_resultado(self, estado, llamada, resultado):
        estado["mensajes"].append({
            "role": "tool",
            # tool_call_id: asi la API sabe que ESTE resultado responde a ESA
            # llamada concreta (puede haber varias en el mismo turno).
            "tool_call_id": llamada.id,
            "content": resultado,
        })


class _ProveedorOllama(_ProveedorLLM):
    _nombre = "ollama"

    def _estado_inicial(self, historial, tools):
        from ollama import Client

        # La clave de Ollama no se pasa como parametro api_key (a diferencia
        # de Groq): va a mano en la cabecera HTTP Authorization: Bearer ...
        # timeout=_TIMEOUT_SEGUNDOS (F5.0/T3): el Client de Ollama reenvia
        # este kwarg tal cual al httpx.Client interno (verificado en la doc
        # del SDK) - sin el, una llamada colgada no tenia limite de tiempo.
        client = Client(
            host="https://ollama.com",
            headers={"Authorization": "Bearer " + self.api_key},
            timeout=timeout_actual(self._nombre),
        )
        return {"client": client, "mensajes": list(historial), "tools": tools}

    def _llamar(self, estado):
        # httpx: libreria HTTP que usa el SDK de Ollama por dentro.
        # TimeoutException es la que lanza si se supera _TIMEOUT_SEGUNDOS -
        # se captura ANTES del except Exception generico de abajo para
        # poder distinguirla (el router de T4 solo reintentara esta).
        import httpx

        client = estado["client"]
        kwargs = {"model": self.modelo, "messages": estado["mensajes"]}
        if estado["tools"]:
            kwargs["tools"] = estado["tools"]

        inicio = time.perf_counter()
        try:
            respuesta = client.chat(**kwargs)
        except httpx.TimeoutException as error:
            logging.error(f"Ollama: timeout tras {timeout_actual(self._nombre)}s")
            raise ErrorTimeout("Ollama", str(error)) from error
        except Exception as error:
            # MODELO RETIRADO (410 Gone), afinado el 01/08 tras un caso real:
            # Jordi eligio `minimax-m2.5` del menu y TODOS sus mensajes
            # cayeron al fallback con "ErrorPeticionInvalida", que no dice
            # nada. El motivo real estaba escondido en el detalle:
            # "minimax-m2.5 was retired at 2026-07-31" - lo habian retirado
            # el dia ANTES. El catalogo de modelos se verifico el 16/07 y ha
            # envejecido, que es exactamente el riesgo que ya avisaba el
            # diario ("verificar siempre en docs oficiales; las IAs citan
            # modelos retirados") - solo que esta vez le toco a este repo.
            #
            # Se distingue A PROPOSITO: un catalogo envejece SIEMPRE, asi
            # que lo util no es quitar este modelo (que tambien) sino que el
            # proximo que retiren lo diga solo, en vez de disfrazarse de
            # fallo generico.
            if getattr(error, "status_code", None) == 410:
                logging.error("Ollama: el modelo %s esta RETIRADO (410)", self.modelo)
                raise ErrorPeticionInvalida(
                    "Ollama",
                    f"El modelo '{self.modelo}' ya no existe: el proveedor lo ha "
                    f"retirado. Elige otro con /modelo. Detalle: {error}",
                ) from error
            # 03/08: se separa lo TRANSITORIO, igual que en Gemini y por el
            # mismo motivo. Salio del log de Jordi: "Ollama: error
            # (ResponseError)" degradaba a la primera SIN reintentar, y la
            # llamada habia tardado 65 segundos - o sea que el servidor
            # estaba haciendo algo, no rechazando de plano.
            #
            # `ollama.ResponseError` trae `.status_code` (verificado
            # inspeccionando el SDK, no supuesto), asi que se clasifica por
            # el CODIGO HTTP - un dato de la API - y no por el nombre de la
            # clase. Misma leccion que el fallo de los nombres inventados de
            # Gemini el 02/08.
            codigo = getattr(error, "status_code", None)
            if codigo == 429:
                # 03/08: un 429 es un LIMITE, no un fallo de red, y hay que
                # tiparlo como tal para que la logica de cuota DIARIA de
                # ErrorLimitePeticiones se aplique tambien aqui. Antes caia
                # en ErrorConexion, que es reintentable SIEMPRE: con la
                # cuota del dia agotada eso son tres llamadas tiradas por
                # mensaje, para siempre.
                logging.error(
                    "Ollama: limite de peticiones superado | %s", _recortar(error)
                )
                raise ErrorLimitePeticiones("Ollama", str(error)) from error
            if isinstance(codigo, int) and 500 <= codigo < 600:
                logging.error("Ollama: fallo transitorio (HTTP %s); reintentable", codigo)
                raise ErrorConexion("Ollama", str(error)) from error
            # 03/08: FALLO DE RED sin codigo HTTP. Salio del log de Jordi:
            # "Ollama: error (ConnectionError)" -> el router lo clasifico
            # como ErrorPeticionInvalida y degrado el proveedor SIN UN SOLO
            # REINTENTO. Un cable que se cae no es una peticion invalida:
            # no hay codigo HTTP porque la peticion no llego a viajar.
            #
            # Se comprueban las dos familias a proposito: httpx.TransportError
            # (lo que lanza el SDK por dentro) y el ConnectionError de
            # Python (lo que sube desde el socket). Quedarse con una sola
            # dejaria fuera justo el caso que aparecio en el log.
            if isinstance(error, (httpx.TransportError, ConnectionError)):
                logging.error("Ollama: fallo de conexion (%s)", type(error).__name__)
                raise ErrorConexion("Ollama", str(error)) from error
            # El resto sigue en el cajon generico (no reintentable): Ollama
            # no define excepciones tan especificas como Groq en su SDK.
            # F5.2 (27/07): tipo, no texto - mismo motivo que en Groq: un
            # except Exception generico puede arrastrar cualquier cosa del
            # SDK, incluido el cuerpo de la peticion. Detalle completo sigue
            # en ErrorPeticionInvalida.detalle.
            logging.error("Ollama: error (%s)", type(error).__name__)
            raise ErrorPeticionInvalida("Ollama", str(error)) from error
        logging.info(f"Latencia (ollama/{self.modelo}): {time.perf_counter() - inicio:.2f}s")

        mensaje = respuesta["message"]
        if not mensaje.get("tool_calls"):
            return RespuestaLLM(texto=mensaje["content"])

        tool_calls = []
        for llamada in mensaje["tool_calls"]:
            # Ollama YA entrega los argumentos como dict (no como texto JSON,
            # a diferencia de Groq) y NO reparte un id por llamada.
            tool_calls.append(ToolCall(
                nombre=llamada["function"]["name"],
                argumentos=llamada["function"]["arguments"],
            ))
        return RespuestaLLM(tool_calls=tool_calls, raw=mensaje)

    def _registrar_peticion(self, estado, respuesta):
        estado["mensajes"].append(respuesta.raw)

    def _registrar_resultado(self, estado, llamada, resultado):
        estado["mensajes"].append({
            "role": "tool",
            "content": resultado,
            # Ollama identifica el resultado por "tool_name", NO por
            # tool_call_id como Groq/OpenAI.
            "tool_name": llamada.nombre,
        })


# F5.4: claves de JSON Schema que la API de Gemini NO reconoce y que
# hacen fallar la peticion ENTERA con 400 INVALID_ARGUMENT ("Unknown name
# ... Cannot find field"). Aparecieron al generar el schema con Pydantic
# (que anade additionalProperties por el extra="forbid" de ArgsCalcular).
#
# Verificado con llamadas REALES el 24/07, no de memoria: el SDK de
# google-genai las acepta en local (las traduce a snake_case sin quejarse)
# pero el servidor las rechaza - validar la forma en el cliente NO
# garantiza que el servidor lo trague. Se comprobo aparte que "maxLength"
# SI se acepta, asi que no se quita: es informacion util para el modelo.
_CLAVES_NO_SOPORTADAS_GEMINI = ("additionalProperties",)


def _limpiar_schema_para_gemini(esquema):
    """Devuelve una COPIA del schema sin las claves que Gemini rechaza.

    Va aqui y no en tools.py a proposito: TOOLS es una lista neutra y
    cada proveedor adapta lo que necesita (mismo principio que la
    traduccion del historial). Groq y Ollama siguen recibiendo el schema
    completo, que es valido para ellos.

    Recursiva porque en F5.5 habra tools con objetos anidados.
    """
    if isinstance(esquema, dict):
        return {
            clave: _limpiar_schema_para_gemini(valor)
            for clave, valor in esquema.items()
            if clave not in _CLAVES_NO_SOPORTADAS_GEMINI
        }
    if isinstance(esquema, list):
        return [_limpiar_schema_para_gemini(elemento) for elemento in esquema]
    return esquema


class _ProveedorGemini(_ProveedorLLM):
    _nombre = "gemini"

    def _estado_inicial(self, historial, tools):
        from google import genai
        from google.genai import types

        # OJO: a diferencia de Groq/Ollama, aqui NO se pasa la api_key a mano.
        # El SDK busca solo la variable de entorno GEMINI_API_KEY.
        # http_options timeout (F5.0/T3): a diferencia de Groq/Ollama, este
        # SDK lo pide en MILISEGUNDOS, no segundos (verificado en la doc de
        # google-genai) - de ahi el *1000. Hay issues abiertos en el repo del
        # SDK reportando que a veces no se respeta del todo; se deja puesto
        # igualmente porque es lo documentado, y el limite del bucle
        # (_MAX_PASOS_DE_HERRAMIENTAS) sigue de red de seguridad.
        client = genai.Client(
            http_options=types.HttpOptions(timeout=int(timeout_actual(self._nombre) * 1000))
        )
        # Traducimos el historial canonico al dialecto de Gemini.
        contents, system_instruction = traducir_historial_gemini(historial)

        if tools:
            # De TOOLS (formato Groq/OpenAI) sacamos solo el dict interior
            # "function" de cada una - es lo que Gemini reconoce - y le
            # quitamos las claves que su API rechaza (F5.4, ver arriba).
            declaraciones = [
                _limpiar_schema_para_gemini(tool["function"]) for tool in tools
            ]
            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                tools=[types.Tool(function_declarations=declaraciones)],
            )
        else:
            config = types.GenerateContentConfig(system_instruction=system_instruction)

        return {"client": client, "contents": contents, "config": config}

    def _estado_sin_tools(self, estado):
        """Gemini no guarda las tools sueltas: van dentro del `config` que ya
        se construyo. Se rehace uno igual pero SOLO con la instruccion de
        sistema, conservando `contents` (que es donde estan la conversacion
        y los resultados de las tools ya ejecutadas)."""
        from google.genai import types

        anterior = estado["config"]
        return {
            **estado,
            "config": types.GenerateContentConfig(
                system_instruction=getattr(anterior, "system_instruction", None)
            ),
        }

    def _llamar(self, estado):
        # httpx: el SDK de Gemini tambien lo usa por debajo para el
        # transporte HTTP; TimeoutException es lo que lanza al superar el
        # timeout de http_options.
        import httpx

        client = estado["client"]
        inicio = time.perf_counter()
        try:
            respuesta = client.models.generate_content(
                model=self.modelo,
                contents=estado["contents"],
                config=estado["config"],
            )
        except httpx.TimeoutException as error:
            logging.error(f"Gemini: timeout tras {timeout_actual(self._nombre)}s")
            raise ErrorTimeout("Gemini", str(error)) from error
        except Exception as error:
            # 02/08: se separa lo TRANSITORIO de lo definitivo, que estaba
            # pendiente en el backlog desde el 24/07 y salio mordiendo a la
            # primera prueba de /condensar - un ServerError degrado Gemini
            # SIN reintentar, justo el proveedor que mejor podia con ello.
            #
            # Un 5xx ("el servidor esta saturado") o un 429 ("vas muy
            # rapido") son invitaciones EXPLICITAS a volver a intentarlo;
            # tratarlos igual que un INVALID_ARGUMENT -que fallaria siempre-
            # quema el proveedor a la primera.
            #
            # SE MIRA EL CODIGO HTTP Y NO EL NOMBRE DE LA CLASE, y esto es
            # una correccion de un fallo mio del mismo 02/08: la primera
            # version buscaba los nombres "ResourceExhausted" y
            # "ServiceUnavailable", que **no existen en este SDK** - los
            # confundi con los de google.api_core. Verificado despues
            # inspeccionando google.genai.errors: solo define APIError,
            # ClientError (4xx) y ServerError (5xx). Resultado: de los tres
            # nombres, solo uno se disparaba, y los 429 -los mas
            # frecuentes- seguian quemando el proveedor.
            #
            # El codigo HTTP es un DATO de la API, no un nombre que yo
            # suponga, asi que no puede volver a pasar lo mismo. Y ademas
            # aguanta que Google renombre o reorganice sus clases.
            codigo = getattr(error, "code", None)
            if codigo == 429:
                # 03/08: igual que en Ollama. Un 429 se tipa como LIMITE y
                # no como fallo de red, para que la distincion "por minuto
                # / por dia" de ErrorLimitePeticiones valga en los tres
                # proveedores y no solo en Groq.
                logging.error(
                    "Gemini: limite de peticiones superado | %s", _recortar(error)
                )
                raise ErrorLimitePeticiones("Gemini", str(error)) from error
            if isinstance(codigo, int) and 500 <= codigo < 600:
                logging.error("Gemini: fallo transitorio (HTTP %s); reintentable", codigo)
                raise ErrorConexion("Gemini", str(error)) from error
            nombre_error = type(error).__name__
            # F5.2 (27/07): tipo, no texto. Gemini con INVALID_ARGUMENT puede
            # devolver "contents[N].parts[0].text = '...'" - el texto que
            # escribio JIM, dentro del propio mensaje de error. Detalle
            # completo sigue en ErrorPeticionInvalida.detalle.
            logging.error("Gemini: error (%s)", nombre_error)
            raise ErrorPeticionInvalida("Gemini", str(error)) from error
        logging.info(f"Latencia (gemini/{self.modelo}): {time.perf_counter() - inicio:.2f}s")

        # Hallazgo real (F4.6): Gemini puede devolver VARIAS partes - una de
        # texto ("Dejame calcular...") y luego la peticion de funcion. Hay que
        # recorrer TODAS las partes, no solo parts[0], o se pierde la llamada.
        content = respuesta.candidates[0].content
        tool_calls = []
        for parte in content.parts:
            funcion = getattr(parte, "function_call", None)
            if funcion:
                # dict(...) normaliza los args (llegan como un tipo del SDK
                # parecido a dict) para poder usarlos con **argumentos.
                tool_calls.append(ToolCall(nombre=funcion.name, argumentos=dict(funcion.args)))

        if tool_calls:
            return RespuestaLLM(tool_calls=tool_calls, raw=content)

        # Hallazgo del 24/07: Gemini a veces ESCRIBE la llamada a la tool
        # como texto normal en vez de usar el mecanismo estructurado, con el
        # formato nativo de Llama que no le corresponde:
        #
        #     <function=buscar_en_recuerdos{"consulta": "..."}</function>
        #
        # Es el MISMO fallo que en Groq da tool_use_failed (arreglado hoy),
        # solo que Groq lo caza y devuelve 400 y Gemini lo deja pasar: la
        # tool nunca se ejecuta y el churro acaba en la pantalla de JIM.
        texto = _texto_de_gemini(respuesta)
        rescatada = _rescatar_tool_call(texto)
        if rescatada is not None:
            logging.warning("Gemini: tool-call escrita como texto; rescatada")
            return RespuestaLLM(tool_calls=[rescatada], raw=content)
        if _PARECE_TOOL_CALL.search(texto or ""):
            # Se reconoce la forma pero no se pudo leer. NO se le enseña a
            # JIM: un churro de maquinaria interna no es una respuesta, y
            # ademas le haria pensar que el bot esta roto de otra manera.
            logging.warning("Gemini: tool-call como texto ILEGIBLE; descartada")
            return RespuestaLLM(texto=(
                "Se me ha cruzado un cable pidiendo una herramienta. "
                "Vuelve a preguntármelo, por favor."
            ))
        return RespuestaLLM(texto=texto)

    def _registrar_peticion(self, estado, respuesta):
        # Con el formato Content/Part propio de Gemini, no dicts sueltos.
        estado["contents"].append(respuesta.raw)

    def _registrar_resultado(self, estado, llamada, resultado):
        from google.genai import types

        estado["contents"].append(
            types.Content(
                role="user",
                parts=[types.Part.from_function_response(
                    name=llamada.nombre,
                    response={"resultado": resultado},
                )],
            )
        )


# Registro nombre de proveedor -> clase. Elegir proveedor en tiempo de
# ejecucion sin un if/elif largo (mismo patron que antes con _FUNCIONES).
_PROVEEDORES = {
    "groq": _ProveedorGroq,
    "ollama": _ProveedorOllama,
    "gemini": _ProveedorGemini,
}


def responder_proveedor(proveedor: str, api_key: str, modelo: str,
                        historial: list, tools: list | None,
                        turno: Turno | None = None) -> str:
    """Ejecuta el bucle completo en UN proveedor concreto y devuelve el
    texto final. Es el UNICO punto de entrada publico desde F5.0/T4: el
    router (src/llm_router.py) lo llama para cada eslabon de la cadena -
    si este proveedor falla, el router captura el ErrorLLM y decide si
    reintentar o degradar al siguiente. Nada mas llama a esto directamente
    (ni siquiera Agente, que solo conoce al router).

    turno (SEG-03 + LOG-07): se reenvia tal cual - lo crea el router una vez
    por turno y es EL MISMO OBJETO para todos los eslabones que se prueben.
    Justo por eso funciona: la cuenta de llamadas y la memoria de tools ya
    ejecutadas sobreviven al cambio de proveedor.
    """
    return _PROVEEDORES[proveedor](api_key, modelo).responder(historial, tools, turno)
