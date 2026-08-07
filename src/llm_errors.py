# Excepciones tipadas para los fallos al hablar con un proveedor LLM
# (F5.0/T2). Sustituyen al patron anterior de devolver un string que
# empezaba por "⚠️" y detectarlo con .startswith() - fragil (choca con
# contenido legitimo del modelo, ver hallazgo AUD-01 de la auditoria) y
# mezclaba el canal de datos (la respuesta) con el canal de control
# (si hubo error o no).
#
# Cada subclase representa un TIPO de fallo (auth, red, limite de
# peticiones...) - quien capture la excepcion puede reaccionar distinto
# segun el tipo (p.ej. el router de T4 solo reintentara ante los
# reintentables, nunca ante un error de autenticacion).


class ErrorLLM(Exception):
    """Base de todos los errores al hablar con un proveedor LLM.

    - proveedor/detalle: para el LOG interno (logging.error), con el texto
      tecnico completo del SDK - eso NUNCA cambia de sitio, sigue siendo
      tan detallado como antes.
    - mensaje_usuario: texto GENERICO y seguro para mostrar en pantalla o
      en el bot de Telegram, SIN el texto crudo del SDK (hallazgo AUD-07 de
      la auditoria: el detalle interno no debe llegar al usuario final).
    """

    # Cada subclase sobreescribe esto con su propio texto. "{proveedor}"
    # se rellena solo.
    plantilla_usuario = "error al hablar con {proveedor}."

    # F5.0/T4: si es True, el router puede REINTENTAR el mismo proveedor
    # (con backoff) - tiene sentido para fallos transitorios (rate limit,
    # timeout, red). Si es False, reintentar el mismo proveedor no ayudaria
    # (clave mala, peticion invalida): el router degrada directo al siguiente.
    reintentable = False

    def __init__(self, proveedor: str, detalle: str = ""):
        self.proveedor = proveedor
        self.detalle = detalle
        super().__init__(f"{proveedor}: {detalle}" if detalle else proveedor)

    @property
    def mensaje_usuario(self) -> str:
        return f"⚠️ {self.plantilla_usuario.format(proveedor=self.proveedor)}"


class ErrorAutenticacion(ErrorLLM):
    """La clave de API es invalida o fue rechazada. NO reintentable."""
    plantilla_usuario = "la clave de API de {proveedor} no es válida."


class ErrorLimitePeticiones(ErrorLLM):
    """Se supero el limite del proveedor (rate limit). Reintentable.

    DISTINGUE TOKENS DE PETICIONES (02/08, peticion de Jordi tras probar).
    "Limite superado" a secas no dice que hacer, y las dos causas se
    arreglan de forma distinta:

      - por PETICIONES: has mandado muchos mensajes seguidos. Se pasa en un
        minuto y basta con esperar.
      - por TOKENS: la conversacion o el documento ocupan demasiado. Esperar
        NO lo arregla si sigues con el mismo contexto - hay que /limpiar,
        cerrar la charla o soltar el documento.

    Se saca del texto del error del proveedor, que lo dice ("...on tokens
    per minute (TPM)" / "...on requests per day (RPD)"). Si no se reconoce,
    se cae al mensaje generico de siempre: es una mejora del aviso, nunca
    un motivo para fallar.
    """
    plantilla_usuario = "límite de {proveedor} superado."

    @property
    def es_diario(self) -> bool:
        """True si el limite es POR DIA (y no por minuto).

        Se mira en un solo sitio porque de ello dependen DOS cosas que
        tienen que decir lo mismo: lo que se le cuenta al usuario y lo que
        hace el router. Ver `reintentable` justo debajo.
        """
        detalle = (self.detalle or "").lower()
        return "per day" in detalle or "rpd" in detalle or "tpd" in detalle

    @property
    def reintentable(self) -> bool:
        """Reintentable SALVO si la cuota agotada es la DIARIA.

        CORRECCION del 03/08, encontrada leyendo el log de una sesion de
        pruebas de Jordi. Hasta hoy esto era `reintentable = True` a secas,
        y el resultado era que el codigo CONTRADECIA a su propio mensaje:
        el aviso decia "esto no se arregla esperando un rato" y el router,
        acto seguido, esperaba y reintentaba. Tres veces. En CADA mensaje.

        Medido en el log del 03/08: de 21:50:52 a 22:03:20, trece minutos,
        quince mensajes seguidos, groq fallo en TODOS sin recuperarse ni
        una vez. Cada mensaje se dejaba tres llamadas y ~4 segundos en un
        proveedor que ya sabiamos muerto hasta el dia siguiente: unas 45
        llamadas tiradas.

        La leccion, que es la del 02/08 pero al reves: alli el prompt
        prometia y el codigo no garantizaba; aqui el que rompia la promesa
        era el propio codigo, que sabia distinguir el limite diario para
        HABLAR y no para ACTUAR. Por eso `es_diario` es ahora una sola
        propiedad de la que beben las dos.

        Se deja como property y no como atributo de clase a proposito: el
        dato que lo decide (el detalle del proveedor) solo existe cuando
        hay instancia. Sin detalle -como en los tests del router- sale
        True, que es el comportamiento de siempre.
        """
        return not self.es_diario

    @property
    def mensaje_usuario(self) -> str:
        detalle = (self.detalle or "").lower()
        # Los limites POR DIA se dicen aparte: son los unicos que NO se
        # arreglan esperando un rato ni limpiando nada.
        if self.es_diario:
            return (
                f"⚠️ has agotado la cuota DIARIA de {self.proveedor}. Esto no se "
                "arregla esperando un rato ni limpiando la conversación: hay que "
                "esperar a mañana o cambiar de proveedor con /proveedor."
            )
        if "token" in detalle or "tpm" in detalle:
            # CORRECCION del 03/08. La primera version decia "prueba con
            # /limpiar" y Jordi lo vio en el PRIMER mensaje de una
            # conversacion nueva, donde no habia nada que limpiar. El
            # limite de tokens es casi siempre POR MINUTO -o sea de
            # velocidad, no de tamaño- y se recupera solo. Limpiar ayuda,
            # pero es lo segundo, no lo primero.
            return (
                f"⚠️ {self.proveedor} se ha quedado sin cuota de TOKENS. El límite "
                "por minuto se recupera solo en menos de un minuto: espera un poco "
                "y repite. Si la conversación es muy larga, /limpiar hace que cada "
                "mensaje gaste menos."
            )
        if "request" in detalle or "rpm" in detalle:
            return (
                f"⚠️ has hecho demasiadas PETICIONES seguidas a {self.proveedor}. "
                "Espera un minuto y vuelve a probar."
            )
        return super().mensaje_usuario


class ErrorConexion(ErrorLLM):
    """Fallo de red al hablar con el proveedor. Reintentable."""
    plantilla_usuario = "no hay conexión con {proveedor}."
    reintentable = True


class ErrorTimeout(ErrorLLM):
    """El proveedor tardo demasiado en responder (T3). Reintentable."""
    plantilla_usuario = "{proveedor} tardó demasiado en responder."
    reintentable = True


class ErrorPeticionInvalida(ErrorLLM):
    """El proveedor rechazo la peticion por algo que no es auth ni limite.
    NO reintentable: reenviar la misma peticion fallaria igual.

    OJO al subcaso de abajo: esa premisa resulto ser FALSA para
    tool_use_failed, y hasta el 02/08 este error se los tragaba todos."""
    plantilla_usuario = "{proveedor} rechazó la petición."


class ErrorToolCallMalGenerada(ErrorPeticionInvalida):
    """El modelo escribio la llamada a la herramienta como TEXTO en vez de
    usar el mecanismo estructurado, y el proveedor rechazo la peticion.

    QUE ES EXACTAMENTE (medido el 02/08 con llamadas reales). El modelo
    tiene dos formas de pedir una tool: rellenar el formulario que la API
    entiende, o escribirla a mano. llama-3.3-70b a veces la escribe a mano
    y ademas la escribe MAL - tres variantes reales del mismo turno:

        <function=buscar_en_recuerdos{"consulta": "..."}</function>   falta >
        <function=buscar_en_recuerdos {"consulta": "..."} </function> espacios
        <function=buscar_en_recuerdos({"consulta": "..."}</function>  parentesis

    Groq lo detecta y devuelve HTTP 400 con code=tool_use_failed. Es el
    MISMO fallo que el anotado el 24/07 para Gemini, donde nadie lo caza y
    el churro acaba en pantalla: cambia quien lo pilla, no el fallo.

    POR QUE ES REINTENTABLE Y SU PADRE NO. La premisa de
    ErrorPeticionInvalida -"reenviar la misma peticion fallaria igual"- es
    cierta para una clave mala o un schema roto, y FALSA aqui: mandando 24
    veces la MISMA peticion fallaron 6 y funcionaron 18 (~25%). Es un dado,
    no un determinismo. Como estaba marcada no reintentable, cada tirada
    mala quemaba el proveedor primario entero y degradaba al siguiente -de
    ahi los 16 casos de groq en el log entre el 31/07 y el 02/08, con Jordi
    viendo responder al fallback sin saber por que-. Con 2 reintentos, la
    probabilidad de perder el proveedor baja del 25% a ~1,5%."""
    plantilla_usuario = "{proveedor} generó mal una llamada a herramienta."
    reintentable = True


class ErrorLimitePasos(ErrorLLM):
    """El bucle de tools se agoto sin que el modelo diera una respuesta
    final (antes era el string _MENSAJE_AGOTADO). NO reintentable."""
    plantilla_usuario = (
        "el agente no llegó a una respuesta final tras varios pasos de herramientas."
    )


class ErrorPresupuestoAgotado(ErrorLLM):
    """Se agoto el presupuesto de llamadas al LLM de ESTE turno (SEG-03,
    hallazgo de la auditoria del 27/07): sin este limite, un solo mensaje
    podia disparar hasta 45 llamadas reales (3 proveedores x 3 intentos x 5
    rondas de tools) porque el presupuesto de pasos (_MAX_PASOS_DE_HERRAMIENTAS)
    es POR PROVEEDOR, y el router lo reinicia entero en cada reintento y en
    cada fallback. No es un riesgo frente a terceros (la allowlist del bot
    ya lo cubre) sino de COSTE Y CUOTA: un turno mal encaminado podia agotar
    la cuota diaria de un proveedor entero.

    NO reintentable: el presupuesto es del turno completo, no de un
    proveedor - reintentar el mismo o degradar al siguiente solo gastaria
    mas presupuesto sin sentido (ver LLMRouter.responder)."""
    plantilla_usuario = (
        "se alcanzó el límite de llamadas al modelo en este turno; "
        "intenta reformular la pregunta en un mensaje nuevo."
    )
