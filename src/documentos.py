# F5.5 #7 - Leer PDF/Word: la primera tool con "contenido_externo ARBITRARIO"
# sin red de por medio (ADR-006, nivel 4). El riesgo no es a donde va la
# tool (no sale a ningun sitio), es QUE trae: un documento que Jordi no ha
# leido entero puede llevar texto oculto (blanco sobre blanco, tamaño 1)
# que el modelo si procesa - por eso el texto extraido pasa por el mismo
# saneado <fuente> que ya usan consultar_foto_astronomica y resumir_url
# (ver _envolver en tools.py), no se trata distinto por venir de un fichero
# y no de una URL.
#
# DISEÑO (decision de Jordi, 31/07): "comando + adjunto", no "ruta como
# argumento del modelo". El modelo NUNCA elige que fichero lee - lo elige
# Jordi (CLI: /documento <ruta> que EL escribe) o quien le manda el
# adjunto a JIM por Telegram. La tool solo sabe leer "el documento que me
# acaban de dar", igual que resumir_url solo sabe leer "la URL que me han
# pedido" pero, a diferencia de esa, aqui no hace falta un guardian: sin
# argumento que el modelo rellene, no hay path traversal ni SSRF posible.
#
# POR QUE EN MEMORIA Y NO EN DISCO: nada se escribe en adjuntos/ ni en
# ningun sitio persistente. Guardar en disco añadiria limpieza de ficheros
# huerfanos y una forma nueva de que la CLI y el bot (dos procesos, ver
# limitacion ya documentada sobre chroma_db/) se pisaran el uno al otro.
# Los bytes viven solo mientras dura el objeto Agente/turno en RAM.
#
# POR QUE UN ContextVar Y NO UN PARAMETRO MAS: las tools de este proyecto
# son funciones puras (nombre, argumentos) -> str (ver _ejecutar_tool en
# llm_client.py); ninguna tool sabe QUIEN pregunta. Para que leer_documento
# sepa cual es "el documento de este usuario" sin tocar toda la tuberia del
# router (Turno viaja por 4 modulos solo para presupuesto e idempotencia,
# ver llm_types.py), Agente.preguntar fija este ContextVar al ADJUNTO
# GUARDADO EN EL PROPIO AGENTE justo antes de llamar al router, y lo
# restaura al salir. Como cada Agente es por-usuario (ver _agente_de en
# telegram_bot.py, razon: privacidad) y cada turno de Telegram corre en su
# propio asyncio.to_thread (que copia el contexto al lanzarse), dos
# usuarios preguntando a la vez no se cruzan sus documentos.
import zipfile
from contextvars import ContextVar, Token
from dataclasses import dataclass
from io import BytesIO

# Tope de tamaño del propio fichero recibido (antes de descomprimir nada).
# 15 MB de PDF/Word de texto normal son ya centenares de paginas; mas que
# eso huele a algo que no queremos meter entero en el contexto del modelo.
_MAX_BYTES_ADJUNTO = 15_000_000

# ADR-006: "un .docx es un ZIP: acotar tamaño (bomba de descompresion)".
# Se comprueba el tamaño SIN COMPRIMIR de cada entrada ANTES de dejar que
# python-docx la descomprima - si se mirara despues, la descompresion (el
# propio ataque) ya habria ocurrido.
_MAX_BYTES_DESCOMPRIMIDOS = 50_000_000

_EXTENSIONES_VALIDAS = {".pdf": "pdf", ".docx": "docx"}


class DocumentoNoValido(Exception):
    """Cualquier motivo por el que un adjunto no se acepta o no se puede
    leer: extension, tamaño, cifrado, corrupcion, o que no habia ninguno.
    Un solo tipo de error porque quien la captura (tools.py, main.py,
    telegram_bot.py) solo necesita mostrar str(error) al usuario - no
    distingue el motivo."""


@dataclass(frozen=True)
class DocumentoAdjunto:
    datos: bytes
    nombre: str
    tipo: str  # "pdf" o "docx" - ya validado, nunca otra cosa


def validar_adjunto(datos: bytes, nombre_original: str) -> DocumentoAdjunto:
    """Comprueba extension y tamaño, y para .docx ADEMAS el tamaño
    descomprimido de cada entrada del ZIP. NO extrae texto todavia (eso es
    trabajo mas caro que se hace solo si el modelo de verdad lo pide, en
    extraer_texto) - aqui solo se decide si el adjunto se acepta."""
    extension = "." + nombre_original.rsplit(".", 1)[-1].lower() if "." in nombre_original else ""
    tipo = _EXTENSIONES_VALIDAS.get(extension)
    if tipo is None:
        raise DocumentoNoValido(
            "Solo puedo leer ficheros .pdf o .docx (Word). Ese no es ninguno de los dos."
        )

    if len(datos) > _MAX_BYTES_ADJUNTO:
        raise DocumentoNoValido(
            f"Ese fichero pesa demasiado (máximo {_MAX_BYTES_ADJUNTO // 1_000_000} MB)."
        )

    if tipo == "docx":
        try:
            with zipfile.ZipFile(BytesIO(datos)) as paquete:
                for entrada in paquete.infolist():
                    if entrada.file_size > _MAX_BYTES_DESCOMPRIMIDOS:
                        raise DocumentoNoValido(
                            "Ese .docx no parece un documento normal (una de sus partes "
                            "es sospechosamente grande al descomprimir)."
                        )
        except zipfile.BadZipFile:
            raise DocumentoNoValido("Ese .docx está dañado o no es un fichero Word de verdad.")

    # nombre acotado: es texto que viene de fuera (quien manda el adjunto
    # por Telegram elige el nombre del fichero) y solo se usa para
    # mostrarlo en confirmaciones al humano, nunca para abrir ninguna ruta.
    return DocumentoAdjunto(datos=datos, nombre=nombre_original[:100], tipo=tipo)


def _faltan_librerias(cual: str, paquete: str) -> DocumentoNoValido:
    """El mensaje que se le da al MODELO cuando la libreria no esta.

    Nace de un fallo real del 31/07: pypdf estaba en el Python del sistema
    pero no en el venv desde el que se ejecuta el proyecto. El ImportError
    crudo llegaba al modelo ("No module named 'pypdf'") y el modelo, en vez
    de decir que la herramienta habia fallado, se INVENTO que el usuario no
    habia adjuntado el fichero - le echo la culpa a Jordi de un fallo del
    servidor, tanto en la CLI como en Telegram.

    Por eso el texto hace dos cosas a la vez, y las dos hacen falta:
      1. Dice que es un problema de INSTALACION (no del fichero).
      2. Le PROHIBE explicitamente al modelo culpar al usuario.
    Es la misma leccion que la alucinacion de fecha de NASA APOD: cuando el
    modelo puede confundir un fallo con otra cosa, reforzar el prompt no
    basta - hay que hacer el fallo inconfundible en el propio resultado.
    """
    return DocumentoNoValido(
        f"No puedo leer {cual} ahora mismo porque falta instalar la librería "
        f"'{paquete}' en el entorno donde corro. NO es culpa del usuario ni de "
        "su fichero: díselo tal cual y pídele que instale las dependencias "
        "(pip install -r requirements.txt). No le pidas que vuelva a mandar el "
        "documento, porque volvería a fallar igual."
    )


def _extraer_texto_pdf(datos: bytes) -> str:
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError:
        raise _faltan_librerias("PDF", "pypdf") from None

    try:
        lector = PdfReader(BytesIO(datos))
    except PdfReadError:
        raise DocumentoNoValido("No he podido abrir ese PDF; puede estar dañado.")

    if lector.is_encrypted:
        raise DocumentoNoValido("Ese PDF está protegido con contraseña; no puedo leerlo.")

    try:
        paginas = [pagina.extract_text() or "" for pagina in lector.pages]
    except Exception:
        # pypdf puede lanzar varias excepciones internas ante un PDF
        # malformado que SI abre pero no se deja recorrer; no hay forma de
        # listarlas todas de antemano, y el resultado para el usuario es el
        # mismo en cualquier caso: no se pudo leer.
        raise DocumentoNoValido(
            "Ese PDF no se deja leer; puede estar dañado o ser una imagen escaneada."
        )

    return "\n".join(paginas)


def _extraer_texto_docx(datos: bytes) -> str:
    try:
        from docx import Document
        from docx.opc.exceptions import PackageNotFoundError
    except ImportError:
        raise _faltan_librerias("documentos de Word", "python-docx") from None

    try:
        documento = Document(BytesIO(datos))
    except PackageNotFoundError:
        raise DocumentoNoValido("Ese .docx está dañado o no es un fichero Word de verdad.")

    partes = [parrafo.text for parrafo in documento.paragraphs]
    # Las tablas no salen en `.paragraphs` (python-docx las trata aparte) -
    # sin esto, un documento con datos solo en tablas devolveria texto vacio.
    for tabla in documento.tables:
        for fila in tabla.rows:
            partes.append(" | ".join(celda.text for celda in fila.cells))
    return "\n".join(partes)


def extraer_texto(adjunto: DocumentoAdjunto) -> str:
    """Saca el texto visible del adjunto ya validado. Puede lanzar
    DocumentoNoValido si el fichero pasa la validacion de tamaño/extension
    pero luego resulta ilegible (cifrado, corrupto, escaneado sin OCR)."""
    if adjunto.tipo == "pdf":
        return _extraer_texto_pdf(adjunto.datos)
    return _extraer_texto_docx(adjunto.datos)


# --- Contexto del turno: que adjunto esta "puesto sobre la mesa" ----------

_ACTUAL: ContextVar[DocumentoAdjunto | None] = ContextVar("documento_actual", default=None)


def fijar_documento_actual(adjunto: DocumentoAdjunto | None) -> Token:
    """Llamado por Agente.preguntar() al principio de CADA turno, con el
    adjunto que ese Agente (ese usuario) tiene guardado - o None si no ha
    mandado ninguno. Devuelve el Token que hay que pasarle a
    restaurar_documento_actual() al terminar."""
    return _ACTUAL.set(adjunto)


def restaurar_documento_actual(token: Token) -> None:
    _ACTUAL.reset(token)


def documento_actual() -> DocumentoAdjunto | None:
    """Lo que lee la tool leer_documento() - ver tools.py."""
    return _ACTUAL.get()
