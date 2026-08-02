# F5.0/T4: el Agente ya no habla con UN proveedor, sino con un router que
# prueba la cadena ADR-001 (primario + fallbacks) con reintentos.
# Excepcion base de fallos al hablar con un proveedor (F5.0/T2) - antes se
# detectaba un fallo mirando si el texto empezaba por "⚠️". La lanza el
# router cuando TODOS los proveedores de la cadena han fallado.
# F5.5 #7: el adjunto (PDF/Word) que este Agente tiene "puesto sobre la
# mesa" vive AQUI, no en la tool - ver el porque en src/documentos.py.
import logging

from src.documentos import DocumentoAdjunto, fijar_documento_actual, restaurar_documento_actual
from src.llm_errors import ErrorLLM
from src.llm_router import construir_cadena

# Traemos de storage.py la funcion que guarda la conversacion en disco.
from src.storage import guardar_conversacion

# ADR-006 (/tools): el Agente ya no manda SIEMPRE el catalogo entero. Manda
# solo las categorias activas, porque la ficha de cada tool viaja en CADA
# peticion (coste en todos los turnos) y el modelo elige peor cuantas mas
# opciones parecidas tiene delante.
from src.tools import (
    categorias_por_defecto,
    fijar_bandeja,
    fijar_categorias_activas,
    restaurar_bandeja,
    restaurar_categorias_activas,
    tools_de,
)

# AUD-03: a partir de cuantos caracteres de historial se empieza a tirar lo
# viejo. 20.000 caracteres son ~5.400 tokens, o sea el 45% de los 12.000
# tokens/minuto que da Groq en el plan gratuito - queda margen para la
# pregunta, la respuesta y las fichas de las tools, que tambien cuentan.
#
# El numero sale de las conversaciones REALES de Jordi: la mas larga (23
# mensajes) son 19.211 caracteres, asi que el tope no molesta en una charla
# normal y solo entra cuando la cosa se alarga de verdad.
_MAX_CARACTERES_HISTORIAL = 20_000

# Cuantos mensajes se conservan enteros al compactar. 10 son unos 5 turnos
# de ida y vuelta: suficiente para que el modelo no pierda el hilo de lo que
# se esta hablando AHORA, que es lo unico que el RAG no puede devolverle
# (buscar_en_recuerdos encuentra lo de dias pasados, no el matiz de hace
# tres mensajes).
_MENSAJES_QUE_SE_CONSERVAN = 10


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
        # AUD-03: cuantos mensajes se tiraron del contexto en el ultimo
        # turno. Lo lee el canal para avisar por pantalla.
        self.compactados = 0
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

    def preguntar(self, pregunta: str, persistir=None) -> str:
        """Un turno completo: manda la pregunta (con tools disponibles),
        guarda el turno en el historial si la respuesta fue valida, y
        devuelve el texto para que quien llame lo muestre donde quiera.
        """
        # 1) La pregunta entra al historial ANTES de llamar.
        self.historial.append({"role": "user", "content": pregunta})

        # AUD-03: se compacta AQUI, con la pregunta nueva ya dentro y antes
        # de llamar al modelo, que es el unico momento en que sirve de algo
        # - el objetivo es que ESTA peticion sea mas barata, no la siguiente.
        # Se guarda en `compactados` para que el canal pueda avisar: nada en
        # silencio, que es la norma del proyecto desde el aviso de cifrado.
        self.compactados = self.compactar_si_hace_falta(persistir)

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
        # Honestidad sobre lo apagado (02/08): _ejecutar_tool vive en
        # llm_client.py y no tiene forma de saber que categorias estan
        # activas. Se le hacen llegar por el mismo camino que el documento
        # adjunto, y se restauran en el finally por el mismo motivo: si no,
        # un turno heredaria las del turno anterior mientras el hilo viva.
        token_categorias = fijar_categorias_activas(self.categorias_activas)
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
            restaurar_categorias_activas(token_categorias)

        self.historial.append({"role": "assistant", "content": respuesta})
        return respuesta

    def compactar_si_hace_falta(self, persistir=None) -> int:
        """Tira los mensajes mas viejos si el historial se ha puesto gordo.
        Devuelve cuantos se tiraron (0 si no hizo falta).

        AUD-03, cerrado el 02/08. EL PROBLEMA, medido sobre las
        conversaciones REALES de Jordi: cada turno reenvia TODO lo anterior,
        asi que el coste no crece, se ACUMULA - es la suma de las sumas. Su
        conversacion mas larga (23 mensajes) ya son ~5.200 tokens, el 43% de
        lo que Groq deja gastar en un minuto. Proyectando desde sus datos:

            turno 10 ->  4.515 tokens/peticion |  24.832 gastados
            turno 20 ->  9.030 tokens/peticion |  94.813 gastados  <- la cuota DIARIA
            turno 30 -> 13.545 tokens/peticion | NO CABE en un minuto

        O sea: una conversacion de 20 turnos se comia el dia entero de Groq,
        y una de 30 dejaba de funcionar. Sin tope, la unica salida era
        acordarse de /limpiar.

        POR QUE VENTANA Y NO RESUMEN (decision de Jordi, 02/08): resumir lo
        viejo cuesta una llamada al LLM cada vez que se compacta, y aqui
        NO HACE FALTA, porque este proyecto ya tiene memoria permanente. Lo
        que sale del historial no se pierde: esta en conversations/ y en el
        indice del RAG, y `buscar_en_recuerdos` lo puede traer de vuelta si
        el modelo lo necesita. Se deja de REENVIAR, que es lo que costaba
        dinero; no se olvida.

        Y DE AHI EL `persistir`, que es lo que hace segura la ventana:
        antes de tirar nada hay que asegurarse de que esta guardado. En
        Telegram ya se persiste despues de cada turno, asi que llega
        cubierto; la CLI solo guarda AL SALIR, y sin esto lo tirado a mitad
        de sesion se habria perdido de verdad. Se recibe como funcion en vez
        de llamar a self.guardar() a pelo porque cada canal guarda distinto
        (el bot reescribe SU fichero con `ruta=`), y el Agente no tiene por
        que saberlo - misma frontera que el resto de F4.5.
        """
        if self._tamaño_historial() <= _MAX_CARACTERES_HISTORIAL:
            return 0

        # El system prompt (historial[0]) NUNCA se toca: es quien es el
        # agente, no es "memoria" de nada. Mismo criterio que /limpiar.
        conservados = self.historial[-_MENSAJES_QUE_SE_CONSERVAN:]
        tirados = len(self.historial) - 1 - len(conservados)
        if tirados <= 0:
            # Los mensajes que quedan ya son pocos y aun asi abultan: es un
            # documento pegado o una respuesta larguisima. Tirar mas seria
            # quedarse sin conversacion, y el aviso de aqui no arregla eso.
            return 0

        if persistir is not None:
            # Si guardar falla, NO se compacta: mejor un turno caro que
            # perder lo hablado. Es la misma prioridad que en _persistir del
            # bot - guardar importa, pero nunca a costa del contenido.
            try:
                persistir()
            except Exception as error:
                logging.error(
                    "No se compacta el historial: fallo al guardar antes (%s)",
                    type(error).__name__,
                )
                return 0

        self.historial = self.historial[:1] + conservados
        logging.info("Historial compactado: %d mensajes fuera del contexto", tirados)
        return tirados

    def _tamaño_historial(self) -> int:
        """Caracteres de todo lo que se reenviaria en el proximo turno."""
        return sum(len(m.get("content") or "") for m in self.historial)

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
