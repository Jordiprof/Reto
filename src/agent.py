# F5.0/T4: el Agente ya no habla con UN proveedor, sino con un router que
# prueba la cadena ADR-001 (primario + fallbacks) con reintentos.
# Excepcion base de fallos al hablar con un proveedor (F5.0/T2) - antes se
# detectaba un fallo mirando si el texto empezaba por "⚠️". La lanza el
# router cuando TODOS los proveedores de la cadena han fallado.
from src.llm_errors import ErrorLLM
from src.llm_router import construir_cadena

# Traemos de storage.py la funcion que guarda la conversacion en disco.
from src.storage import guardar_conversacion

# TOOLS: herramientas disponibles; se pasan al router en cada turno normal.
from src.tools import TOOLS


class Agente:
    """Encapsula TODO lo que hace falta para mantener una conversacion:
    el historial, a que proveedor/modelo preguntar, y como guardarla.

    No sabe NADA de terminal (nada de input()/print()/questionary) - asi
    en Fase 5, cuando las preguntas lleguen por Telegram en vez de por
    teclado, esta clase se reutiliza tal cual. Solo cambia quien la
    llama, no como funciona por dentro.
    """

    def __init__(self, system_prompt: str, proveedor: str, api_key: str, modelo: str):
        self.proveedor = proveedor
        self.api_key = api_key
        self.modelo = modelo
        # El router lleva la cadena: proveedor elegido como primario + los
        # demas de ADR-001 (con clave) como fallback automatico (F5.0/T4).
        self.router = construir_cadena(proveedor, api_key, modelo)
        # El historial ES la memoria de la conversacion (ver F3.1) -
        # arranca con el system prompt y solo crece.
        self.historial = [{"role": "system", "content": system_prompt}]

    def cambiar_modelo(self, modelo: str) -> None:
        self.modelo = modelo
        # Rehacemos la cadena con el modelo nuevo como primario.
        self.router = construir_cadena(self.proveedor, self.api_key, modelo)

    def cambiar_proveedor(self, proveedor: str, modelo: str, api_key: str) -> None:
        # El historial NO se toca al cambiar - esta en formato canonico,
        # el proveedor nuevo hereda la conversacion entera (F3.1).
        self.proveedor = proveedor
        self.modelo = modelo
        self.api_key = api_key
        # El proveedor elegido pasa a ser el nuevo primario de la cadena.
        self.router = construir_cadena(proveedor, api_key, modelo)

    def preguntar(self, pregunta: str) -> str:
        """Un turno completo: manda la pregunta (con tools disponibles),
        guarda el turno en el historial si la respuesta fue valida, y
        devuelve el texto para que quien llame lo muestre donde quiera.
        """
        # 1) La pregunta entra al historial ANTES de llamar.
        self.historial.append({"role": "user", "content": pregunta})

        try:
            # 2) El router prueba la cadena (primario + fallbacks) y resuelve
            #    por dentro el tool-calling con la calculadora (F4.3-F4.5).
            #    Solo lanza ErrorLLM si TODOS los proveedores fallaron.
            respuesta = self.router.responder(self.historial, tools=TOOLS)
        except ErrorLLM as error:
            # F5.0/T2: un fallo real (auth, conexion, limite...) NO se
            # guarda en el historial como si el asistente lo hubiera dicho
            # de verdad - contaminaria la memoria de la conversacion en
            # turnos futuros (mismo principio que F3.1, ahora con una
            # excepcion tipada en vez de mirar el texto de la respuesta).
            return error.mensaje_usuario

        self.historial.append({"role": "assistant", "content": respuesta})
        return respuesta

    def resumir(self) -> str:
        """F3.6: pide al modelo un resumen de la conversacion hasta
        ahora, SIN guardar ni la peticion ni el resumen en el historial
        real (es una consulta de lectura, no un turno mas)."""
        peticion = self.historial + [{
            "role": "user",
            "content": "Resume la conversacion anterior en pocas frases, "
                        "destacando solo lo mas importante.",
        }]
        try:
            return self.router.responder(peticion, tools=None)
        except ErrorLLM as error:
            return error.mensaje_usuario

    def guardar(self):
        """Delega en storage.py - devuelve la ruta del fichero, o None
        si no habia nada real que guardar (ver storage.py)."""
        return guardar_conversacion(self.historial, self.proveedor, self.modelo)
