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

# Tamaño del bloque al MEDIR la descompresion real (LOG-02). 1 MB: grande
# para que no sean miles de llamadas a .read() en un documento normal,
# pequeño para que un ZIP bomb se corte a los pocos bloques y no cerca del
# limite entero.
_BLOQUE_LECTURA_ZIP = 1_000_000

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
                    # LOG-02 (auditoria del 04/08): se MIDE lo que sale de
                    # verdad al descomprimir, no `entrada.file_size`. Ese
                    # campo vive en la cabecera local del ZIP -la escribe
                    # quien crea el fichero- y se puede falsear sin que el
                    # ZIP deje de ser valido: un adjunto con la cabecera
                    # diciendo "1 KB" y el contenido real siendo un ZIP
                    # bomb de gigabytes pasaba este chequeo intacto, porque
                    # nunca se llegaba a mirar lo que habia DENTRO. Es la
                    # misma leccion que "no confiar en el Content-Length"
                    # de un HTTP: la cabecera es lo que DICE el emisor, no
                    # lo que hay.
                    #
                    # Se lee por BLOQUES y se corta en cuanto se supera el
                    # limite -no se descomprime entero antes de comprobar-,
                    # que es justo lo que evita gastar la memoria que este
                    # control existe para proteger.
                    leidos = 0
                    with paquete.open(entrada) as miembro:
                        while trozo := miembro.read(_BLOQUE_LECTURA_ZIP):
                            leidos += len(trozo)
                            if leidos > _MAX_BYTES_DESCOMPRIMIDOS:
                                raise DocumentoNoValido(
                                    "Ese .docx no parece un documento normal (una de "
                                    "sus partes es sospechosamente grande al "
                                    "descomprimir)."
                                )
        except zipfile.BadZipFile:
            raise DocumentoNoValido("Ese .docx está dañado o no es un fichero Word de verdad.")

    # nombre acotado: es texto que viene de fuera (quien manda el adjunto
    # por Telegram elige el nombre del fichero) y solo se usa para
    # mostrarlo en confirmaciones al humano, nunca para abrir ninguna ruta.
    return DocumentoAdjunto(datos=datos, nombre=nombre_original[:100], tipo=tipo)


def leer_fichero(ruta_texto: str) -> tuple[bytes, str]:
    """Lee un fichero del disco a partir de lo que ESCRIBIO una persona.

    Nace de una prueba real fallida (01/08): Jordi intento adjuntar un PDF
    por la CLI cuatro veces y las cuatro fallaron, ninguna por culpa suya:

      - `...\\DAM\\2ºDAM\\Acceso a Datos`  -> era una CARPETA, y el error que
        salia era "[Errno 13] Permission denied", que no dice eso ni de
        lejos y manda a buscar un problema de permisos que no existe.
      - `& 'c:\\...\\Unidad 7.pdf'`        -> es LITERALMENTE lo que pega
        Windows con "Copiar como ruta" y al arrastrar un fichero a
        PowerShell: el `&` es el operador de llamada del shell, no parte
        del nombre. Daba "[Errno 22] Invalid argument".
      - `Acceso a datos Unidad 7.pdf`      -> ruta relativa desde otro
        directorio: "No such file or directory".

    O sea que la funcionalidad estaba bien y aun asi era inusable. Aqui se
    normaliza lo que llega y se traducen los errores del sistema a algo que
    diga QUE hacer. Devuelve (bytes, nombre) o lanza DocumentoNoValido.
    """
    from pathlib import Path

    texto = (ruta_texto or "").strip()
    # El operador de llamada de PowerShell que añade "Copiar como ruta".
    if texto.startswith("& "):
        texto = texto[2:].strip()
    # Comillas de cualquier tipo: las pone el propio Windows cuando la ruta
    # lleva espacios, y son del SHELL, no del nombre del fichero.
    for comilla in ("'", '"'):
        if len(texto) >= 2 and texto.startswith(comilla) and texto.endswith(comilla):
            texto = texto[1:-1].strip()
            break

    if not texto:
        raise DocumentoNoValido("No me has dado ninguna ruta.")

    ruta = Path(texto).expanduser()
    if not ruta.exists():
        raise DocumentoNoValido(
            f"No encuentro «{ruta}». Comprueba la ruta; si tiene espacios, pégala "
            "entera (puedes arrastrar el fichero hasta aquí)."
        )
    if ruta.is_dir():
        raise DocumentoNoValido(
            f"«{ruta}» es una carpeta, no un fichero. Dime la ruta del PDF o del "
            "Word concreto que quieres que lea."
        )

    try:
        return ruta.read_bytes(), ruta.name
    except OSError as error:
        # El texto del SO se queda en el log, no en la cara del usuario.
        raise DocumentoNoValido(
            f"No he podido abrir «{ruta.name}»: {error.strerror or 'error de lectura'}."
        ) from error


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


# --- Trocear y buscar por relevancia (01/08) -------------------------------
# EL PROBLEMA: hasta hoy, de un documento largo el modelo recibia los
# primeros 8.000 caracteres y punto. Medido con un PDF de 19.193: le llegaba
# hasta la seccion 17 de 40, y el final NO existia para el. En unos apuntes
# de 75.000 caracteres, 8.000 son el 10% - y ese 10% suele ser el indice.
#
# LA SOLUCION: trocear el documento y mandarle solo los TROZOS QUE HABLAN DE
# LO QUE SE PREGUNTA, en vez del principio por el principio. Asi el tamaño
# del documento deja de importar: lo que se acota es cuanto se manda, no
# hasta donde se puede leer.
#
# Se reutiliza el modelo de embeddings que ya usa el RAG de conversaciones
# (rag.incrustar_textos). Pero OJO a la diferencia, que es deliberada: esto
# NO toca la coleccion de ChromaDB. Los vectores se calculan, se usan y se
# tiran. Un documento que se lee una vez no es una conversacion, y meterlo
# en la memoria permanente ensuciaria las busquedas de recuerdos para
# siempre (justo el ruido que /salir->descartar viene a evitar).

# Tamaño de cada trozo. NO elegido a ojo: medido el 01/08 con un documento
# de 300 lineas de relleno y UNA linea con el dato buscado al final. Con
# trozos de 1200 y 800 caracteres la busqueda NO encontraba esa linea; con
# 600 y 400, si. El motivo es que el vector de un trozo es el de TODO su
# contenido: una frase corta y concreta dentro de un trozo grande de relleno
# queda diluida y el trozo entero "no se parece" a la pregunta.
#
# Se elige 600 y no 400 porque los dos aciertan y 600 da menos trozos (menos
# vectores que calcular por consulta).
_CARACTERES_POR_TROZO = 600
# Solape entre trozos consecutivos: sin el, una frase que cae justo en la
# frontera se parte y no se parece a nada.
_SOLAPE = 100
# Cuantos fragmentos se mandan. 10 x 600 = 6.000 caracteres, por debajo del
# tope de 8.000 que ya tenia la tool, asi que el coste del turno no sube
# respecto a antes - lo que cambia es DE DONDE sale ese texto.
_FRAGMENTOS_POR_CONSULTA = 10


def trocear(texto: str, tamaño: int | None = None, solape: int | None = None) -> list[str]:
    """Parte el texto en trozos solapados.

    Funcion PURA: sin red, sin modelo, sin disco - se puede probar sola.
    Corta por el ultimo salto de linea del tramo cuando lo hay, para no
    partir a mitad de frase si se puede evitar.

    Los defaults son None y se resuelven DENTRO, no en la firma: Python
    evalua los valores por defecto UNA vez, al definir la funcion, asi que
    con `tamaño=_CARACTERES_POR_TROZO` en la firma el valor quedaba
    congelado y cambiar la constante no tenia ningun efecto. Me mordio el
    01/08 midiendo que tamaño de trozo iba mejor: las cinco medidas dieron
    el mismo resultado porque las cinco usaron 1200.
    """
    tamaño = _CARACTERES_POR_TROZO if tamaño is None else tamaño
    solape = _SOLAPE if solape is None else solape
    if not texto:
        return []
    trozos = []
    inicio = 0
    while inicio < len(texto):
        fin = min(inicio + tamaño, len(texto))
        if fin < len(texto):
            # Se busca un corte "limpio" en el ultimo tercio del trozo: si
            # no lo hay, se corta a lo bruto y no pasa nada (para eso esta
            # el solape).
            corte = texto.rfind("\n", inicio + (tamaño * 2) // 3, fin)
            if corte != -1:
                fin = corte
        trozos.append(texto[inicio:fin].strip())
        if fin >= len(texto):
            break
        inicio = max(fin - solape, inicio + 1)
    return [t for t in trozos if t]


# Vectores ya calculados, por documento. CLAVE DEL ARREGLO del 01/08.
#
# Que paso: al probar con un PDF de verdad (1,1 MB), cada llamada a
# leer_documento tardaba entre 40 y 69 SEGUNDOS, porque volvia a trocear y a
# incrustar el documento ENTERO cada vez. Y como ese mismo dia la tool se
# habia marcado repetible=True -para que el modelo pudiera buscar en varias
# partes-, el modelo la llamo SEIS veces en un turno: casi 4 minutos parado,
# hasta agotar las rondas de tools (ErrorLimitePasos) y caer al fallback.
# Desde fuera se ve como un programa colgado.
#
# Los dos cambios de ese dia eran correctos por separado y desastrosos
# juntos: uno hizo que se llamara muchas veces, el otro hizo que cada
# llamada fuera carisima. Con la cache, la primera consulta paga el coste y
# las demas son instantaneas - que es justo lo que hace util poder buscar
# varias veces.
#
# Se guarda por HASH del texto y no por nombre de fichero: dos adjuntos
# pueden llamarse igual, y el mismo contenido no debe recalcularse aunque
# cambie el nombre.
_CACHE_VECTORES: dict[str, tuple[list[str], list[list[float]]]] = {}
# Tope de documentos cacheados. Cada entrada son los vectores de un
# documento (~1 MB de floats para uno grande), y esto vive en RAM mientras
# el proceso siga vivo: sin tope, una tarde adjuntando PDFs se come la
# memoria. 3 cubre "el que estoy mirando y el anterior".
_MAX_DOCUMENTOS_EN_CACHE = 3


def _trozos_y_vectores(texto: str) -> tuple[list[str], list[list[float]]]:
    """Trocea e incrusta, reutilizando el resultado si ya se hizo."""
    import hashlib

    from src.rag import incrustar_textos

    clave = hashlib.blake2s(texto.encode("utf-8"), digest_size=16).hexdigest()
    if clave in _CACHE_VECTORES:
        return _CACHE_VECTORES[clave]

    trozos = trocear(texto)
    vectores = incrustar_textos(trozos)
    if len(_CACHE_VECTORES) >= _MAX_DOCUMENTOS_EN_CACHE:
        # FIFO simple: se tira el mas antiguo. Los dicts de Python conservan
        # el orden de insercion, asi que no hace falta llevar otra
        # estructura para saber cual es.
        _CACHE_VECTORES.pop(next(iter(_CACHE_VECTORES)))
    _CACHE_VECTORES[clave] = (trozos, vectores)
    return trozos, vectores


def preparar(adjunto: "DocumentoAdjunto") -> int:
    """Deja el documento listo para buscar ANTES de que pregunten nada.

    Devuelve cuantos fragmentos tiene (0 si no hace falta preparar nada).

    POR QUE EXISTE (01/08, midiendo el arreglo de la cache): la cache
    convierte 6 busquedas de 50s en una de 41s y cinco de 40ms, pero esos
    41s seguian cayendo EN MITAD de la primera pregunta - o sea, justo
    cuando el usuario esta esperando una respuesta y no sabe que pasa. Aqui
    se pagan en el momento de ADJUNTAR, que es cuando esperar tiene sentido
    y se puede decir "preparando el documento".

    Es el mismo criterio que ya se aplico al indexado del RAG al arrancar:
    el trabajo caro se hace donde se puede anunciar, no donde sorprende.

    No lanza: si preparar falla, la busqueda lo reintentara luego. Un fallo
    aqui no puede impedir que el documento se acepte.
    """
    try:
        texto = extraer_texto(adjunto)
    except DocumentoNoValido:
        return 0
    if len(trocear(texto)) <= _FRAGMENTOS_POR_CONSULTA:
        return 0  # cabe entero, no se busca nada dentro
    trozos, _vectores = _trozos_y_vectores(texto)
    return len(trozos)


def buscar_en_documento(
    texto: str, consulta: str, cuantos: int | None = None
) -> list[tuple[int, str]]:
    """Los trozos mas parecidos a `consulta`, como (posicion, texto).

    Devuelve la POSICION ademas del texto para poder decirle al modelo "esto
    es el trozo 31 de 40": sin eso no puede saber si lo que lee es del
    principio o del final, y ya vimos con NASA APOD que un dato sin contexto
    invita a rellenar el hueco.

    Se ordena por posicion, no por parecido: al modelo se le da el documento
    en el ORDEN EN QUE ESTA ESCRITO, aunque los haya elegido la relevancia.
    """
    cuantos = _FRAGMENTOS_POR_CONSULTA if cuantos is None else cuantos
    # Se trocea sin incrustar para poder salir pronto: si el documento cabe
    # entero no hay nada que elegir, y calcular vectores seria tirar tiempo.
    if len(trocear(texto)) <= cuantos:
        return list(enumerate(trocear(texto)))

    from src.rag import incrustar_textos

    # Los del DOCUMENTO salen de la cache (se calculan una vez por
    # documento); el de la CONSULTA cambia en cada pregunta, asi que ese si
    # se calcula siempre - pero es UN solo texto corto, no cientos.
    trozos, trozos_v = _trozos_y_vectores(texto)
    consulta_v = incrustar_textos([consulta])[0]

    def parecido(vector):
        # Coseno a mano: los vectores de este modelo ya vienen normalizados,
        # asi que el producto escalar basta. Sin numpy a proposito - es una
        # dependencia mas para una operacion de dos lineas.
        return sum(a * b for a, b in zip(consulta_v, vector))

    mejores = sorted(range(len(trozos)), key=lambda i: parecido(trozos_v[i]), reverse=True)
    elegidos = sorted(mejores[:cuantos])
    return [(i, trozos[i]) for i in elegidos]


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
