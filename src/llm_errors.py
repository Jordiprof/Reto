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
    """Se supero el limite de peticiones (rate limit). Reintentable."""
    plantilla_usuario = "límite de peticiones de {proveedor} superado."
    reintentable = True


class ErrorConexion(ErrorLLM):
    """Fallo de red al hablar con el proveedor. Reintentable."""
    plantilla_usuario = "no hay conexión con {proveedor}."
    reintentable = True


class ErrorTimeout(ErrorLLM):
    """El proveedor tardo demasiado en responder (T3). Reintentable."""
    plantilla_usuario = "{proveedor} tardó demasiado en responder."
    reintentable = True


class ErrorPeticionInvalida(ErrorLLM):
    """El proveedor rechazo la peticion por algo que no es auth ni
    limite (p.ej. groq.BadRequestError con tool_use_failed, F4.5).
    NO reintentable: reenviar la misma peticion fallaria igual."""
    plantilla_usuario = "{proveedor} rechazó la petición."


class ErrorLimitePasos(ErrorLLM):
    """El bucle de tools se agoto sin que el modelo diera una respuesta
    final (antes era el string _MENSAJE_AGOTADO). NO reintentable."""
    plantilla_usuario = (
        "el agente no llegó a una respuesta final tras varios pasos de herramientas."
    )
