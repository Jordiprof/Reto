# json: para serializar el historial (lista de diccionarios) a disco.
import json

# logging: para dejar constancia cuando se guarda SIN cifrar (F5.3).
import logging

# sqlite3: viene con Python, no hace falta instalar nada. Nos da un motor
# de base de datos relacional que vive en un solo fichero (.db).
import sqlite3

# datetime: para generar la fecha/hora que va en el nombre del fichero.
from datetime import datetime

# Path: manejo de rutas multiplataforma, igual que en config.py.
from pathlib import Path

# Fernet: cifrado simetrico autenticado de la libreria "cryptography"
# (F5.3). Autenticado = si alguien modifica el fichero cifrado a mano, al
# descifrar salta InvalidToken en vez de devolver basura silenciosamente.
from cryptography.fernet import Fernet, InvalidToken

from src.config import obtener_clave_conversaciones

# Carpeta donde se guardan las conversaciones. Mismo patron que LOGS_DIR en
# config.py: ruta absoluta relativa a ESTE fichero (no al directorio desde
# donde se ejecute el script), para que funcione igual sin importar desde
# donde se lance `python -m src.main`.
CONVERSATIONS_DIR = Path(__file__).resolve().parent.parent / "conversations"
CONVERSATIONS_DIR.mkdir(exist_ok=True)

# F3.5 (ADR-002): "intro SQLite". El JSON (arriba) sigue siendo la fuente
# COMPLETA de cada conversacion - esta base de datos es solo un INDICE
# consultable con SQL (fecha, proveedor, modelo, cuantos mensajes, y la
# ruta al JSON con el contenido real). Duplicar el contenido entero en
# SQL es trabajo de Fase Avanzada (ADR-002), no de esta introduccion.
DB_PATH = Path(__file__).resolve().parent.parent / "conversations.db"


# --- F5.3: cifrado en reposo del contenido ---------------------------
# Decision REVISITADA el 24/07 (comite de revision). En la auditoria del
# 23/07 se decidio conscientemente NO cifrar ("es una maquina de un solo
# usuario y los ficheros estan en .gitignore"), pero el propio RNF-06
# dejaba escrita la condicion para reabrirlo: "si en el Experto se
# empiezan a guardar datos mas sensibles que conversaciones propias".
# Con el bot de Telegram (F5.2) el agente pasa a recordar tareas y cosas
# de la vida real de Jordi - esa condicion se cumple.
#
# QUE se cifra: solo el historial (los mensajes). Los metadatos (fecha,
# proveedor, modelo) se quedan EN CLARO a proposito: los necesita el
# indice de SQLite y no son el dato sensible. Se acepta a conciencia la
# fuga de metadatos - quien tenga el fichero sabra CUANDO hablaste y con
# QUE modelo, pero no QUE dijiste.
#
# LIMITACIONES documentadas (no son descuidos):
# - Fernet no rota claves. Cambiar la clave sin re-cifrar los ficheros
#   antiguos equivale a perderlos.
# - Si se pierde la clave, el historial cifrado es IRRECUPERABLE. Conviene
#   guardar una copia fuera del .env.
# - No protege contra un atacante con acceso al proceso en caliente: la
#   clave esta en memoria y el historial pasa por RAM en claro.


class ConversacionNoDescifrable(Exception):
    """No se ha podido leer una conversacion cifrada.

    Se distingue a proposito de un error generico: el mensaje dice si
    falta la clave o si la clave no es la correcta. Sin el marcador
    "cifrado" del fichero seria imposible saber si un fallo al descifrar
    es "clave perdida" o "fichero antiguo en claro" (aviso del comite).
    """


def cifrado_activo() -> bool:
    """True si hay clave configurada y las conversaciones se guardaran
    cifradas. Lo consulta la capa de interfaz (main.py) para avisar al
    usuario al arrancar: el cifrado puede estar apagado, pero nunca en
    silencio.
    """
    return obtener_clave_conversaciones() is not None


def _cifrar_historial(historial: list, clave: bytes) -> str:
    """Serializa el historial a JSON y lo cifra entero como un bloque.

    Devuelve texto ASCII (base64), que es lo que se guarda en el fichero
    en lugar de la lista de mensajes.
    """
    texto = json.dumps(historial, ensure_ascii=False)
    return Fernet(clave).encrypt(texto.encode("utf-8")).decode("ascii")


def _descifrar_historial(contenido: str, clave: bytes) -> list:
    """Operacion inversa de _cifrar_historial."""
    try:
        texto = Fernet(clave).decrypt(contenido.encode("ascii"))
    except InvalidToken as error:
        # InvalidToken cubre dos casos: clave equivocada o fichero
        # manipulado. No se puede distinguir uno de otro (es justo lo que
        # hace seguro al cifrado autenticado), asi que se dicen los dos.
        raise ConversacionNoDescifrable(
            "La clave de CONVERSATIONS_KEY no descifra este fichero "
            "(clave distinta a la que se uso al guardarlo, o fichero alterado)."
        ) from error
    return json.loads(texto.decode("utf-8"))


def _inicializar_db() -> None:
    """Crea la tabla 'conversaciones' si todavia no existe.

    CREATE TABLE IF NOT EXISTS: no falla si ya esta creada de una
    ejecucion anterior - se puede llamar en cada arranque sin problema.
    """
    with sqlite3.connect(DB_PATH) as conexion:
        conexion.execute(
            """
            CREATE TABLE IF NOT EXISTS conversaciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT,
                proveedor TEXT,
                modelo TEXT,
                ruta_json TEXT,
                num_mensajes INTEGER
            )
            """
        )
    # El "with" hace conexion.commit() automaticamente al salir sin
    # errores (y rollback si hay excepcion) - OJO, NO cierra la conexion
    # por si sola, pero como no la reutilizamos, Python la libera sola
    # al salir de la funcion.


def _indexar_en_sqlite(ruta_json: Path, proveedor: str, modelo: str, num_mensajes: int) -> None:
    """Deja UNA fila en conversaciones.db por cada JSON real.

    Con "?" como placeholder (nunca con f-strings) se evita SQL injection:
    sqlite3 se encarga de escapar el valor, aunque aqui el dato venga de
    variables internas del programa, no de un usuario externo - es la
    forma correcta de hacerlo siempre, por costumbre segura.

    F5.2+ (memoria compartida): antes esto INSERTABA siempre. Con el bot de
    Telegram, que reescribe el MISMO fichero despues de cada turno, eso
    dejaba una fila nueva por turno y /historial acababa mostrando la misma
    conversacion 30 veces. Ahora primero mira si ya hay fila para esa ruta:
    si la hay, la ACTUALIZA (num_mensajes crece con la charla).
    """
    _inicializar_db()
    with sqlite3.connect(DB_PATH) as conexion:
        fila = conexion.execute(
            "SELECT id FROM conversaciones WHERE ruta_json = ?", (str(ruta_json),)
        ).fetchone()
        if fila is None:
            conexion.execute(
                "INSERT INTO conversaciones (fecha, proveedor, modelo, ruta_json, num_mensajes) "
                "VALUES (?, ?, ?, ?, ?)",
                (datetime.now().isoformat(), proveedor, modelo, str(ruta_json), num_mensajes),
            )
        else:
            conexion.execute(
                "UPDATE conversaciones SET fecha = ?, proveedor = ?, modelo = ?, "
                "num_mensajes = ? WHERE id = ?",
                (datetime.now().isoformat(), proveedor, modelo, num_mensajes, fila[0]),
            )


def _escribir_json_atomico(ruta: Path, datos: dict) -> None:
    """Escribe el JSON de forma que el fichero quede ENTERO o como estaba.

    R-02 (auditoria de seguridad de noviembre). Antes era open(ruta, "w"),
    que VACIA el fichero antes de escribir nada: un corte de luz, un disco
    lleno o una excepcion a mitad dejaban el JSON vacio o truncado. En la
    CLI eso es una conversacion; en el bot, que reescribe el mismo fichero
    en cada turno, es la conversacion ENTERA desde que empezo.

    Se escribe a un temporal EN LA MISMA CARPETA (os.replace solo es
    atomico dentro del mismo sistema de ficheros), se fuerza a disco con
    flush + fsync y se sustituye de golpe con os.replace. Quien lea ve el
    fichero viejo o el nuevo, nunca uno a medias.

    El temporal acaba en ".tmp" y no en ".json" a proposito: si el proceso
    muere justo en medio, listar_conversaciones (glob "*.json") no lo toma
    por una conversacion. mkstemp lo crea con permisos 0600 (solo el dueño),
    que es mas restrictivo que antes y no cambia nada para el propio bot.
    """
    # Import local: solo los usa esta funcion.
    import os
    import tempfile

    descriptor, temporal = tempfile.mkstemp(
        dir=ruta.parent, prefix=f".{ruta.stem}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as fichero:
            # ensure_ascii=False: sin esto, cada tilde/eñe saldria escapada
            # como "ó" en vez de legible al abrir el fichero a mano.
            # indent=2: formato legible, no una sola linea larga.
            json.dump(datos, fichero, ensure_ascii=False, indent=2)
            fichero.flush()
            os.fsync(fichero.fileno())
        os.replace(temporal, ruta)
    except BaseException:
        # BaseException y no Exception: un Ctrl+C a mitad tambien debe
        # llevarse el temporal. Se relanza siempre; aqui solo se limpia.
        Path(temporal).unlink(missing_ok=True)
        raise


def guardar_conversacion(
    historial: list, proveedor: str, modelo: str, nombre: str | None = None,
    ruta: Path | None = None,
) -> Path | None:
    """Guarda la conversacion en un .json con fecha/hora en el nombre.

    F5.2+ (memoria compartida CLI <-> Telegram): "ruta" permite REESCRIBIR
    un fichero concreto en vez de crear uno nuevo. Lo necesita el bot, que
    guarda despues de CADA turno para no perder nada si el proceso se para:
    sin esto crearia un fichero por turno, cada uno superconjunto del
    anterior, y el RAG indexaria la misma frase una vez por fichero (el id
    de cada mensaje es "fichero:indice", ver rag._id_mensaje).

    Reescribiendo el mismo fichero, en cambio, los ids se mantienen
    estables: los mensajes ya indexados conservan el suyo y solo los nuevos
    estrenan id. La reindexacion sigue siendo idempotente sin tocar el RAG.

    Devuelve la ruta del fichero creado, o None si no habia nada real que
    guardar (el usuario escribio "salir" sin llegar a preguntar nada: el
    historial solo tiene el system prompt, ni un turno de conversacion).
    Evita llenar conversations/ de ficheros basura de sesiones vacias.

    F5.3+: "nombre" es una etiqueta opcional que pone Jordi al guardar (ej.
    "Ideas de herramientas"). Se guarda en los METADATOS en claro, no en el
    nombre del fichero (que sigue siendo la marca de tiempo, para ordenar y
    no chocar). Sirve para que /historial liste las sesiones con un titulo
    reconocible; la busqueda semantica sigue yendo por el CONTENIDO.
    """
    # historial[0] es siempre el system prompt (ver main.py); si no hay
    # nada mas, no hubo conversacion que merezca guardarse.
    if len(historial) <= 1:
        return None

    # strftime con "-" en vez de ":" (Windows no permite ":" en nombres de
    # fichero) y en orden año-mes-dia_hora-min-seg: ordena alfabeticamente
    # igual que cronologicamente.
    # "-%f" (microsegundos) al final: F5.3 destapo que dos guardados en el
    # MISMO segundo generaban el mismo nombre y el segundo pisaba al primero
    # (perdida de datos silenciosa). Raro en la CLI, pero posible con el bot
    # de Telegram (F5.2) o un uso rapido. Los microsegundos siguen ordenando
    # bien y hacen la colision practicamente imposible.
    if ruta is None:
        marca_tiempo = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
        ruta = CONVERSATIONS_DIR / f"{marca_tiempo}.json"

    # Envolvemos el historial con metadatos. OJO: proveedor/modelo son los
    # ULTIMOS usados en la conversacion - si se cambio con /proveedor a
    # mitad de charla, aqui solo queda el final, no el historial de
    # cambios. Simplificacion consciente de F3.3, documentada en el diario.
    # F5.3: si hay clave, el historial viaja cifrado (un string base64 en
    # vez de la lista). Si no la hay, se guarda en claro pero SE AVISA -
    # el cifrado puede estar apagado, nunca en silencio.
    clave = obtener_clave_conversaciones()
    if clave is None:
        logging.warning(
            "Conversacion guardada SIN CIFRAR (falta %s en el .env)",
            "CONVERSATIONS_KEY",
        )
        contenido = historial
    else:
        contenido = _cifrar_historial(historial, clave)

    datos = {
        "fecha": datetime.now().isoformat(),
        "proveedor": proveedor,
        "modelo": modelo,
        # nombre en claro (como fecha/proveedor): asi /historial puede
        # listarlo SIN necesitar la clave de descifrado. Si Jordi no puso
        # ninguno, queda cadena vacia.
        "nombre": (nombre or "").strip(),
        # El marcador es lo que hace posible convivir con los ficheros
        # antiguos (guardados antes de F5.3, sin esta clave) y saber si un
        # fallo al leer es "clave mala" o "fichero en claro de siempre".
        "cifrado": clave is not None,
        "historial": contenido,
    }

    _escribir_json_atomico(ruta, datos)

    # F3.5: ademas del JSON (fuente completa), dejamos una fila-indice en
    # SQLite. Si esto fallara por lo que sea, no queremos perder el JSON
    # ya guardado - por eso va DESPUES y en su propia funcion, no antes.
    _indexar_en_sqlite(ruta, proveedor, modelo, len(historial))

    return ruta


def cargar_conversacion(ruta: Path) -> dict:
    """Lee una conversacion guardada y devuelve sus datos con el historial
    ya utilizable (descifrado si hacia falta).

    F5.3: hasta ahora storage.py SOLO escribia - no habia forma de volver
    a leer lo guardado. Esta funcion es la que consumira el RAG para
    indexar las conversaciones pasadas, y es tambien el unico sitio que
    sabe de descifrado, para que quien llame no tenga que enterarse.

    Convive con los ficheros anteriores a F5.3: los que no traen el
    marcador "cifrado" se leen tal cual, sin intentar descifrar nada.
    """
    with open(ruta, encoding="utf-8") as fichero:
        datos = json.load(fichero)

    # .get() y no [""]: los ficheros guardados antes de F5.3 no tienen esta
    # clave, y para ellos la respuesta correcta es "no, no esta cifrado".
    if not datos.get("cifrado"):
        return _en_claro_comprobado(datos, ruta)

    clave = obtener_clave_conversaciones()
    if clave is None:
        raise ConversacionNoDescifrable(
            f"'{ruta.name}' esta cifrada y no hay CONVERSATIONS_KEY en el .env. "
            "Sin esa clave el contenido es irrecuperable."
        )

    datos["historial"] = _descifrar_historial(datos["historial"], clave)
    return datos


def _hay_clave_configurada() -> bool:
    """¿Quiere JIM cifrar? Una clave ROTA tambien cuenta como "si": quien la
    puso queria cifrado, y para esta pregunta da igual que este mal escrita
    (eso ya lo para el arranque con su propio mensaje)."""
    from src.config import ClaveCifradoInvalida

    try:
        return obtener_clave_conversaciones() is not None
    except ClaveCifradoInvalida:
        return True


def _es_historial_legible(historial: object) -> bool:
    """Lista de mensajes {role: str, content: str|None}. Lo minimo que
    necesitan quien lo enseña y el RAG para no reventar al recorrerlo."""
    return isinstance(historial, list) and all(
        isinstance(m, dict)
        and isinstance(m.get("role"), str)
        and isinstance(m.get("content", ""), (str, type(None)))
        for m in historial
    )


def _en_claro_comprobado(datos: dict, ruta: Path) -> dict:
    """Un fichero que dice NO estar cifrado, antes de darlo por bueno.

    R-05 (auditoria de seguridad de noviembre). La marca "cifrado" va en
    claro y nada la protege: Fernet autentica el bloque cifrado, pero un
    fichero que dice "no estoy cifrado" no le da ocasion de autenticar
    nada. Quien pueda escribir en conversations/ podia plantar un JSON en
    claro -o cambiar la marca- y se cargaba como un recuerdo legitimo.

    NO SE RECHAZAN, y es la decision: los ficheros anteriores a F5.3 son
    conversaciones de verdad, en claro y sin marca. Lo mas conservador que
    no pierde nada es:
      1. Si hay clave, se MARCAN (aviso_sin_cifrar) para que quien los
         enseñe lo diga, y se avisa en el log con el NOMBRE del fichero
         (una marca de tiempo), nunca con su contenido.
      2. Si lo que hay dentro no es un historial -p. ej. el bloque cifrado
         de antes con la marca cambiada a mano-, se trata como ilegible.
         Antes se devolvia tal cual y el RAG reventaba al recorrerlo, y con
         el el indexado de TODAS las conversaciones.
    Queda propuesto, no hecho: re-cifrarlos con la clave actual (migracion)
    y, cuando no quede ninguno, rechazar los ficheros en claro.
    """
    if not _es_historial_legible(datos.get("historial")):
        raise ConversacionNoDescifrable(
            f"'{ruta.name}' dice no estar cifrada pero su contenido no es una "
            "conversación legible (¿fichero alterado?)."
        )
    if _hay_clave_configurada():
        logging.warning(
            "Conversacion '%s' guardada SIN CIFRAR aunque hay %s "
            "(anterior a F5.3, o alterada)", ruta.name, "CONVERSATIONS_KEY",
        )
        datos["aviso_sin_cifrar"] = True
    return datos


def leer_metadatos(ruta: Path) -> dict:
    """Lee SOLO los metadatos de una conversacion (fecha, nombre, proveedor,
    modelo), sin tocar el historial. Pensada para /historial: lista las
    sesiones pasadas SIN necesitar la clave de cifrado (los metadatos van
    en claro) ni cargar/descifrar todo el contenido.

    Devuelve tambien "cifrado" por si quien llame quiere avisar de cuales
    podra abrir. num_mensajes NO se incluye: sacarlo obligaria a descifrar.
    """
    with open(ruta, encoding="utf-8") as fichero:
        datos = json.load(fichero)
    return {
        "ruta": ruta,
        "fecha": datos.get("fecha", ""),
        "nombre": datos.get("nombre", ""),
        "proveedor": datos.get("proveedor", ""),
        "modelo": datos.get("modelo", ""),
        "cifrado": datos.get("cifrado", False),
    }


def borrar_conversacion(ruta: Path) -> bool:
    """Borra una conversacion guardada: el JSON y su fila del indice SQLite.

    F5.2+ (peticion de Jordi al probar el bot): con el guardado automatico
    de Telegram, TODO acaba en memoria - hasta un "hola". Sin una forma de
    tirar lo que no vale, la memoria se llena de ruido, que ademas empeora
    la busqueda semantica (mas paja contra la que competir).

    Devuelve True si habia algo que borrar. NO borra del indice vectorial:
    de eso se encarga rag.olvidar_conversacion, porque storage.py no sabe
    -ni debe saber- que existe ChromaDB. Quien borre de verdad tiene que
    llamar a los dos (ver telegram_bot._descartar).

    missing_ok=True: que el fichero ya no este no es un error para quien
    pide borrarlo; el objetivo ("que no exista") ya se cumple.
    """
    existia = ruta.exists()
    ruta.unlink(missing_ok=True)
    _inicializar_db()
    with sqlite3.connect(DB_PATH) as conexion:
        conexion.execute("DELETE FROM conversaciones WHERE ruta_json = ?", (str(ruta),))
    return existia


def listar_conversaciones() -> list[Path]:
    """Rutas de todas las conversaciones guardadas, de mas antigua a mas
    reciente.

    Ordena por nombre, no por fecha de fichero: el nombre lleva la marca
    de tiempo en formato AAAA-MM-DD_HH-MM-SS, que ordena alfabeticamente
    igual que cronologicamente (ver guardar_conversacion) y no depende de
    los metadatos del sistema de ficheros (que una copia o un backup
    pueden cambiar).
    """
    return sorted(CONVERSATIONS_DIR.glob("*.json"))
