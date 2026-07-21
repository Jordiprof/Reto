# Traemos de llm_client.py las dos funciones que hacen la llamada real.
from src.llm_client import preguntar, preguntar_con_tools
# Traemos de storage.py la funcion que guarda la conversacion en disco.
from src.storage import guardar_conversacion


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
        # El historial ES la memoria de la conversacion (ver F3.1) -
        # arranca con el system prompt y solo crece.
        self.historial = [{"role": "system", "content": system_prompt}]

    def cambiar_modelo(self, modelo: str) -> None:
        self.modelo = modelo

    def cambiar_proveedor(self, proveedor: str, modelo: str, api_key: str) -> None:
        # El historial NO se toca al cambiar - esta en formato canonico,
        # el proveedor nuevo hereda la conversacion entera (F3.1).
        self.proveedor = proveedor
        self.modelo = modelo
        self.api_key = api_key

    def preguntar(self, pregunta: str) -> str:
        """Un turno completo: manda la pregunta (con tools disponibles),
        guarda el turno en el historial si la respuesta fue valida, y
        devuelve el texto para que quien llame lo muestre donde quiera.
        """
        # 1) La pregunta entra al historial ANTES de llamar.
        self.historial.append({"role": "user", "content": pregunta})

        # 2) preguntar_con_tools() puede usar la calculadora por dentro
        #    (F4.3-F4.5) sin que este metodo tenga que enterarse de nada.
        respuesta = preguntar_con_tools(self.historial, self.proveedor, self.api_key, self.modelo)

        # 3) Igual que en F3.1: los errores ("⚠️...") no se guardan como
        #    si el asistente los hubiera dicho de verdad - contaminarian
        #    la memoria de la conversacion en turnos futuros.
        if not respuesta.startswith("⚠️"):
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
        return preguntar(peticion, self.proveedor, self.api_key, self.modelo)

    def guardar(self):
        """Delega en storage.py - devuelve la ruta del fichero, o None
        si no habia nada real que guardar (ver storage.py)."""
        return guardar_conversacion(self.historial, self.proveedor, self.modelo)
