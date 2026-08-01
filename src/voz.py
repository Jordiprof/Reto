# F5.5 #8 - Voz en Telegram. NO es una herramienta: es un CANAL.
#
# Esta es la diferencia de diseño que hay que entender antes de leer el
# codigo. Las 7 tools anteriores las decide el MODELO (el modelo pide
# "consultar_tiempo" y el router la ejecuta). La voz no: nadie le pregunta
# al modelo si quiere oir o hablar. Es una TRADUCCION en los bordes -
# audio->texto al entrar, texto->audio al salir- y por dentro el Agente
# sigue recibiendo y devolviendo str, sin enterarse de nada. Por eso este
# modulo no aparece en HERRAMIENTAS ni en /tools, y por eso no existe en la
# CLI (ADR-006: el canal cambia la VIABILIDAD, no el riesgo - una terminal
# no reproduce audio).
#
# LO QUE SE PAGA EN PRIVACIDAD, DICHO CLARO (matiza RNF-06):
# la mitad de ESCUCHAR manda tu audio a Groq. Y el audio no es "texto que
# encima pesa": la voz es un dato BIOMETRICO - identifica a la PERSONA que
# habla, no solo lo que dijo. Un texto transcrito lo pudo escribir
# cualquiera; una grabacion de tu voz solo la produces tu. Es una fuga
# cualitativamente distinta a las que ya habia declaradas (los titulos de
# consultar_historial, las URLs de resumir_url), y por eso:
#   - "escuchar" nace APAGADO y hay que encenderlo a mano en /voz;
#   - el aviso esta EN el menu, en el momento y en el sitio donde se toma
#     la decision, no enterrado en la documentacion;
#   - cada transcripcion se enseña de vuelta ("te he entendido: ..."), asi
#     que nunca es invisible que un audio salio de la maquina.
# La mitad de HABLAR no paga nada: Piper es local, sin clave y sin cuota;
# el audio de salida no sale de aqui.
#
# POR QUE GROQ PARA ESCUCHAR Y NO WHISPER LOCAL (decision de Jordi,
# 31/07, confirmando ADR-006): whisper-large-v3-turbo transcribe en menos
# de un segundo y no instala nada; en local serian ~1-2 GB de modelo y
# decenas de segundos por nota en CPU. Se acepta la fuga a cambio de que
# la funcion sea usable, y se declara en E4 en vez de esconderla. La
# decision es reversible sin tocar el bot: transcribir() es una funcion
# con una firma (bytes -> str) y cambiar el motor es cambiar su cuerpo.
import io
import logging
import re
import shutil
import subprocess
import threading
import wave

from src.config import obtener_api_key, obtener_ruta_voz

# Modelo de transcripcion. El "turbo" y no whisper-large-v3 a secas: misma
# familia, mucho mas rapido y con la misma cuota gratuita (2.000
# peticiones/dia, 28.800 segundos de audio/dia). Verificado el 31/07 contra
# la API real con la clave del proyecto: los dos existen.
_MODELO_WHISPER = "whisper-large-v3-turbo"

# Se le dice el idioma en vez de dejar que lo detecte. Sin esto, un "hola"
# suelto o una nota con ruido se detectan a veces como portugues o italiano
# y la transcripcion sale traducida o inventada.
_IDIOMA = "es"

_TIMEOUT_SEGUNDOS = 30.0  # el mismo que usan los proveedores de LLM (F5.0/T3)

# Tope de DURACION, comprobado con el dato que Telegram manda en el propio
# update - o sea, ANTES de descargar el audio y antes de gastar cuota. Cinco
# minutos son ya un monologo; mas que eso no es una nota de voz, es un
# fichero, y ademas la transcripcion resultante reventaria el limite de
# entrada del bot.
_MAX_SEGUNDOS = 300

# Tope de BYTES, por si la duracion no viniera (es opcional en la API de
# Telegram). Un opus de 5 minutos ronda 1-2 MB; 10 MB es holgado.
_MAX_BYTES = 10_000_000

# Cuanto texto se sintetiza como maximo. No es una cifra estetica: Piper
# tarda ~1 segundo de CPU por cada 2-3 segundos de audio, asi que una
# respuesta de 4.000 caracteres son minutos de sintesis y una nota de voz
# que nadie escucha entera. Lo que pase de aqui se corta y se avisa - el
# texto COMPLETO va siempre en el mensaje escrito, asi que no se pierde
# nada (es la misma logica del truncado de leer_documento: cortar sin
# decirlo es lo que hace que el modelo -o el usuario- crea que lo tiene
# todo).
_MAX_CARACTERES_HABLAR = 800

_TIMEOUT_FFMPEG = 60


class VozNoDisponible(Exception):
    """Cualquier motivo por el que no se puede oir o hablar: falta la voz de
    Piper, falta ffmpeg, el audio es demasiado largo, o Groq no contesta.
    Un solo tipo de error, como DocumentoNoValido: quien la captura
    (telegram_bot.py) solo necesita enseñar str(error), no distinguir."""


# --- Escuchar: audio -> texto (Groq Whisper) -------------------------------


def validar_duracion(segundos: int | None) -> None:
    """Se llama con el metadato del update, ANTES de descargar el audio.

    Separada de transcribir() a proposito: aqui todavia no se ha bajado ni
    un byte ni se ha tocado la cuota de Groq, asi que rechazar es gratis.
    """
    if segundos is not None and segundos > _MAX_SEGUNDOS:
        raise VozNoDisponible(
            f"Esa nota dura {segundos // 60} min y solo transcribo hasta "
            f"{_MAX_SEGUNDOS // 60}. Mándamela más corta o escríbemelo."
        )


def transcribir(datos: bytes, nombre: str = "nota.ogg") -> str:
    """Manda el audio a Groq y devuelve lo que se entendio.

    El texto que sale de aqui entra al Agente como el mensaje del usuario,
    EXACTAMENTE igual que si lo hubiera tecleado. No se envuelve en
    <fuente> ni pasa por el saneado de SEG-07, y es a proposito: ese
    saneado es para contenido de TERCEROS que el modelo no debe obedecer
    (una web, un PDF, un recuerdo citado). Aqui quien habla es la misma
    persona autorizada por la allowlist que escribe los mensajes.
    Limite conocido y declarado: si Jordi REENVIA la nota de voz de otra
    persona, esas palabras entran como suyas - pero es exactamente lo que
    ya pasa hoy si copia y pega un texto ajeno, asi que no es un agujero
    nuevo de la voz.
    """
    if not datos:
        raise VozNoDisponible("No me ha llegado ningún audio.")
    if len(datos) > _MAX_BYTES:
        raise VozNoDisponible(
            f"Ese audio pesa demasiado (máximo {_MAX_BYTES // 1_000_000} MB)."
        )

    try:
        from groq import Groq
    except ImportError:  # pragma: no cover - groq es dependencia fija
        raise VozNoDisponible(
            "Falta la librería 'groq' en el entorno donde corro."
        ) from None

    from src.config import ClaveApiNoConfigurada

    try:
        clave = obtener_api_key("groq")
    except ClaveApiNoConfigurada:
        # Se dice cual falta y donde, pero NUNCA se toca el valor.
        raise VozNoDisponible(
            "No puedo transcribir: falta GROQ_API_KEY en el .env."
        ) from None

    try:
        cliente = Groq(api_key=clave, timeout=_TIMEOUT_SEGUNDOS)
        respuesta = cliente.audio.transcriptions.create(
            file=(nombre, datos),
            model=_MODELO_WHISPER,
            language=_IDIOMA,
            response_format="json",
        )
    except Exception as error:
        # Politica de logging del proyecto: al log solo el TIPO. Ni el
        # str(error) (que en los SDK puede llevar la peticion entera), ni
        # el audio, ni por supuesto lo que se dijo.
        logging.error("Voz: fallo transcribiendo (%s)", type(error).__name__)
        raise VozNoDisponible(
            "No he podido transcribir esa nota de voz. Vuelve a intentarlo."
        ) from None

    texto = (respuesta.text or "").strip()
    if not texto:
        raise VozNoDisponible("No he entendido nada en esa nota de voz.")
    return texto


# --- Hablar: texto -> audio (Piper local + ffmpeg) -------------------------

# El modelo de Piper (63 MB) se carga una vez y se reutiliza. El cerrojo es
# la leccion de SEG-06 tal cual: "if _voz is None" NO es atomico, asi que
# dos turnos a la vez pueden entrar los dos y cargar DOS modelos de 63 MB
# en memoria. Ademas serializa la sintesis, que es CPU pura.
_voz_cargada = None
_cerrojo = threading.Lock()


def motivo_no_disponible() -> str | None:
    """Devuelve por que no se puede hablar, o None si todo esta listo.

    Existe para que el menu de /voz pueda decir la verdad ANTES de que
    Jordi encienda el interruptor: un "hablar ✅" que luego falla en cada
    respuesta es peor que no ofrecerlo. Comprueba las dos piezas que no se
    instalan con pip: el fichero de la voz y ffmpeg.
    """
    ruta = obtener_ruta_voz()
    if not ruta.is_file():
        return (
            f"falta la voz de Piper ({ruta.name}). Descárgala con:\n"
            "venv\\Scripts\\python.exe -m piper.download_voices "
            "es_ES-davefx-medium --data-dir voces"
        )
    if shutil.which("ffmpeg") is None:
        return (
            "falta ffmpeg en el PATH. Telegram solo acepta OGG/Opus como nota "
            "de voz y Piper genera WAV, así que hace falta para convertirlo."
        )
    try:
        import piper  # noqa: F401
    except ImportError:
        return "falta la librería 'piper-tts' (pip install -r requirements.txt)."
    return None


def _texto_hablable(texto: str) -> str:
    """Deja el texto listo para que Piper lo lea en voz alta.

    Funcion PURA (str -> str) y por eso testeable sin cargar 63 MB de
    modelo ni llamar a ffmpeg. Hace tres cosas, todas por un motivo que se
    oye:
      - quita los caracteres de Markdown y los emojis: Piper los
        PRONUNCIA. Un "**Listo** ✅" se oye como "asterisco asterisco
        listo asterisco asterisco" seguido de un chasquido raro.
      - sustituye las URLs por "un enlace": leer una direccion letra a
        letra son 20 segundos de audio inutil, y el enlace pinchable ya
        va en el mensaje escrito.
      - corta a _MAX_CARACTERES_HABLAR por frase entera, no a media
        palabra.
    """
    limpio = re.sub(r"https?://\S+", "un enlace", texto)
    # Emojis y simbolos: se quitan por RANGO en vez de por lista, porque
    # una lista de emojis siempre se queda corta.
    limpio = re.sub(
        "[\U0001f000-\U0001faff←-⇿⌀-➿️]", " ", limpio
    )
    limpio = re.sub(r"[*_`#>|~\[\]]", " ", limpio)
    limpio = re.sub(r"\s+", " ", limpio).strip()

    if len(limpio) > _MAX_CARACTERES_HABLAR:
        recorte = limpio[:_MAX_CARACTERES_HABLAR]
        # Cortar en el ultimo punto para no dejar la frase colgando. Si no
        # hay ninguno en la ultima parte, se corta y ya: es preferible a
        # buscar hacia atras hasta el principio y quedarse sin audio.
        corte = recorte.rfind(".")
        if corte > _MAX_CARACTERES_HABLAR // 2:
            recorte = recorte[: corte + 1]
        limpio = recorte + " Te lo dejo entero por escrito."
    return limpio


def _cargar_voz():
    """Carga el modelo de Piper una sola vez. Ver _cerrojo (SEG-06)."""
    global _voz_cargada
    if _voz_cargada is None:
        ruta = obtener_ruta_voz()
        if not ruta.is_file():
            raise VozNoDisponible(
                "No tengo instalada la voz para hablar (falta el modelo de Piper)."
            )
        try:
            from piper import PiperVoice
        except ImportError:
            raise VozNoDisponible(
                "Falta la librería 'piper-tts' en el entorno donde corro."
            ) from None
        try:
            _voz_cargada = PiperVoice.load(str(ruta))
        except Exception as error:
            logging.error("Voz: fallo cargando Piper (%s)", type(error).__name__)
            raise VozNoDisponible("No he podido cargar la voz.") from None
    return _voz_cargada


def _a_opus(wav: bytes) -> bytes:
    """Convierte WAV a OGG/Opus, que es lo unico que Telegram acepta como
    NOTA DE VOZ (send_voice). Con WAV el mensaje sale como fichero adjunto:
    se descarga en vez de reproducirse, que es justo lo contrario de lo que
    se busca.

    Detalle de seguridad, aunque hoy no haya dato de fuera en juego: se
    invoca con una LISTA de argumentos fija y sin shell=True, y el audio
    entra y sale por tuberias (pipe:0 / pipe:1). Ningun nombre de fichero,
    y por tanto ningun texto controlable desde el chat, llega nunca a la
    linea de comandos.
    """
    if shutil.which("ffmpeg") is None:
        raise VozNoDisponible(
            "No puedo mandarte una nota de voz porque falta ffmpeg en esta máquina."
        )
    try:
        proceso = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-i", "pipe:0",
                "-c:a", "libopus", "-b:a", "32k",  # 32 kbps sobra para voz
                "-f", "ogg", "pipe:1",
            ],
            input=wav,
            capture_output=True,
            timeout=_TIMEOUT_FFMPEG,
        )
    except (subprocess.TimeoutExpired, OSError) as error:
        logging.error("Voz: fallo en ffmpeg (%s)", type(error).__name__)
        raise VozNoDisponible("No he podido preparar el audio.") from None

    if proceso.returncode != 0 or not proceso.stdout:
        # stderr de ffmpeg NO va al log tal cual: puede incluir rutas.
        logging.error("Voz: ffmpeg devolvio codigo %s", proceso.returncode)
        raise VozNoDisponible("No he podido preparar el audio.")
    return proceso.stdout


def sintetizar(texto: str) -> bytes:
    """texto -> nota de voz OGG/Opus lista para send_voice.

    Sincrona y bloqueante a proposito (carga de modelo + CPU + subproceso):
    quien la llama desde el bot la mete en asyncio.to_thread, igual que
    hace con Agente.preguntar().
    """
    hablable = _texto_hablable(texto)
    if not hablable:
        raise VozNoDisponible("No hay nada que leer en voz alta.")

    with _cerrojo:
        voz = _cargar_voz()
        buffer = io.BytesIO()
        try:
            with wave.open(buffer, "wb") as fichero:
                voz.synthesize_wav(hablable, fichero)
        except Exception as error:
            logging.error("Voz: fallo sintetizando (%s)", type(error).__name__)
            raise VozNoDisponible("No he podido generar el audio.") from None

    return _a_opus(buffer.getvalue())
