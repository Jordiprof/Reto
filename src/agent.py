# F5.0/T4: el Agente ya no habla con UN proveedor, sino con un router que
# prueba la cadena ADR-001 (primario + fallbacks) con reintentos.
# Excepcion base de fallos al hablar con un proveedor (F5.0/T2) - antes se
# detectaba un fallo mirando si el texto empezaba por "⚠️". La lanza el
# router cuando TODOS los proveedores de la cadena han fallado.
# F5.5 #7: el adjunto (PDF/Word) que este Agente tiene "puesto sobre la
# mesa" vive AQUI, no en la tool - ver el porque en src/documentos.py.
from src.documentos import DocumentoAdjunto, fijar_documento_actual, restaurar_documento_actual
from src.llm_errors import ErrorLLM
from src.llm_router import construir_cadena

# Traemos de storage.py la funcion que guarda la conversacion en disco.
from src.storage import guardar_conversacion

# ADR-006 (/tools): el Agente ya no manda SIEMPRE el catalogo entero. Manda
# solo las categorias activas, porque la ficha de cada tool viaja en CADA
# peticion (coste en todos los turnos) y el modelo elige peor cuantas mas
# opciones parecidas tiene delante.
from src.tools import categorias_por_defecto, fijar_bandeja, restaurar_bandeja, tools_de


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
        # ADR-006 (revision 31/07): arrancan encendidas todas MENOS las que
        # exponen algo hacia fuera - memoria (manda conversaciones
        # descifradas al proveedor) y web (destino elegido por el modelo).
        # Ver CATEGORIAS_APAGADAS_AL_ARRANCAR en src/tools.py.
        self.categorias_activas = categorias_por_defecto()
        # F5.5 #7: el ultimo PDF/Word que le han dado a JIM (/documento en
        # CLI, adjunto en Telegram). None = no hay ninguno puesto.
        self.documento_pendiente: DocumentoAdjunto | None = None
        # Lo que una tool ha dejado para ENSEÑAR en este turno y no cabe en
        # el texto de la respuesta (hoy: la foto de la NASA). Lo recoge quien
        # sepa mostrarlo -Telegram con send_photo- y lo ignora quien no -la
        # CLI-. Se vacia en cada turno; ver fijar_bandeja en tools.py.
        self.media_pendiente: list = []

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

        # F5.5 #7: se fija el ContextVar a lo que ESTE Agente tiene
        # guardado, se restaura pase lo que pase (finally) - si no se
        # restaurara, un turno sin documento heredaria el del turno
        # anterior mientras el hilo siga vivo.
        token = fijar_documento_actual(self.documento_pendiente)
        # La bandeja se VACIA (no se sustituye) para que quien ya tenga la
        # referencia -telegram_bot- siga mirando la misma lista, y para que
        # una foto del turno anterior no se enseñe otra vez en este.
        self.media_pendiente.clear()
        token_bandeja = fijar_bandeja(self.media_pendiente)
        try:
            # 2) El router prueba la cadena (primario + fallbacks) y resuelve
            #    por dentro el tool-calling con la calculadora (F4.3-F4.5).
            #    Solo lanza ErrorLLM si TODOS los proveedores fallaron.
            respuesta = self.router.responder(
                self._mensajes_del_turno(), tools=tools_de(self.categorias_activas)
            )
        except ErrorLLM as error:
            # F5.0/T2: un fallo real (auth, conexion, limite...) NO se
            # guarda en el historial como si el asistente lo hubiera dicho
            # de verdad - contaminaria la memoria de la conversacion en
            # turnos futuros (mismo principio que F3.1, ahora con una
            # excepcion tipada en vez de mirar el texto de la respuesta).
            return error.mensaje_usuario
        finally:
            restaurar_documento_actual(token)
            restaurar_bandeja(token_bandeja)

        self.historial.append({"role": "assistant", "content": respuesta})
        return respuesta

    def limpiar_historial(self) -> None:
        """Comandos CLI (F5): borra la conversacion en curso pero MANTIENE el system
        prompt (historial[0]). Para el comando /limpiar: empezar de cero
        sin reiniciar el programa ni perder quien es el asistente.
        OJO: no toca lo ya guardado en disco ni la memoria semantica -
        solo el historial de ESTA sesion en memoria."""
        self.historial = self.historial[:1]
        # F5.5 #7: "empezamos de cero" incluye el documento puesto sobre la
        # mesa - si no se soltara aqui, una charla nueva podria seguir
        # leyendo un PDF de la charla anterior sin que nadie lo haya pedido.
        self.documento_pendiente = None

    def _mensajes_del_turno(self) -> list:
        """El historial que se manda al modelo en ESTE turno.

        Normalmente es el historial tal cual. La excepcion es cuando hay un
        documento adjunto: entonces se antepone un aviso al ULTIMO mensaje
        del usuario.

        POR QUE HACE FALTA (bug real del 01/08, encontrado por Jordi
        probando y diagnosticado con el log): adjuntó un PDF, el bot
        contesto "Documento recibido", pregunto "de que trata" y el modelo
        respondio "por favor sube el PDF". **El modelo nunca llamo a
        leer_documento** - verificado por AUSENCIA en el log, que registra
        cada tool ejecutada. Y no era un fallo del codigo (la tuberia
        funciona de punta a punta): era que **el modelo no tenia forma de
        saber que habia un documento**. El "Documento recibido" es un
        mensaje del bot a Telegram, no entra en el historial; lo unico que
        veia el modelo era una herramienta disponible, y tenia que ADIVINAR
        por como estuviera redactada la pregunta. A veces acertaba y a
        veces no - de ahi que funcionara unos dias y fallara otros.

        POR QUE UN AVISO PEGADO AL MENSAJE Y NO UN MENSAJE role="system":
        Gemini no admite "system" dentro de la lista, y su traductor se
        queda con el ULTIMO que encuentre (ver traducir_historial_gemini) -
        inyectar uno aqui le habria borrado el SYSTEM_PROMPT de verdad.
        Pegarlo al texto funciona igual en los tres proveedores.

        NO se toca self.historial: el aviso es andamiaje de este turno, no
        algo que dijera JIM. Si se guardara, acabaria en el JSON, en el RAG
        y en todos los turnos siguientes.
        """
        if self.documento_pendiente is None or not self.historial:
            return self.historial

        ultimo = self.historial[-1]
        aviso = (
            f"[Aviso del sistema: JIM acaba de adjuntar el documento "
            f"«{self.documento_pendiente.nombre}». Si la pregunta va sobre él, "
            f"usa la herramienta leer_documento (no lleva argumentos). NO le "
            f"pidas que lo suba: ya lo ha hecho.]\n\n"
        )
        return self.historial[:-1] + [
            {**ultimo, "content": aviso + ultimo["content"]}
        ]

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

    def guardar(self, nombre: str | None = None):
        """Delega en storage.py - devuelve la ruta del fichero, o None
        si no habia nada real que guardar (ver storage.py). "nombre" es la
        etiqueta opcional que Jordi pone al guardar (F5.3+)."""
        return guardar_conversacion(self.historial, self.proveedor, self.modelo, nombre)
