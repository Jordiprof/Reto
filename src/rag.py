"""F5.3: memoria semantica (RAG local) sobre las conversaciones guardadas.

Cierra el escalon 4 de ADR-002. Deja que el agente "recuerde" cosas de
dias anteriores buscando por SIGNIFICADO, no por palabras exactas.

Privacidad (RNF-06), decision del comite del 24/07: el indice de ChromaDB
guarda SOLO el vector de cada mensaje + un puntero (fichero + posicion),
NUNCA el texto en claro. Asi el cifrado de storage.py no se queda a medias
(si guardaramos el texto aqui, chroma_db/ seria un "canal lateral" con todo
legible al lado). El texto se descifra del JSON solo en el instante de
devolver un resultado de busqueda.

RNF-06 tambien: todo es LOCAL. El modelo de embeddings corre en la maquina
(fastembed/ONNX, sin PyTorch); ningun dato sale salvo, como siempre, la
llamada al LLM - que aqui ni interviene.
"""
import logging

# threading: para el cerrojo que serializa el acceso al indice (SEG-06).
import threading
from pathlib import Path

from src.storage import (
    CONVERSATIONS_DIR,
    ConversacionNoDescifrable,
    cargar_conversacion,
    listar_conversaciones,
)

# Modelo de embeddings elegido en F5.1 (ADR-003) por su calidad en español:
# multilingue, 384 dimensiones, ~0.22GB en su version ONNX (verificado el
# 24/07 con list_supported_models() de fastembed). El nombre debe ser EXACTO.
_MODELO_EMBEDDINGS = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Raiz del proyecto (rag.py vive en src/). Se usa para las rutas de disco.
_RAIZ = Path(__file__).resolve().parent.parent

# Donde ChromaDB guarda el indice vectorial (gitignored, RNF-06).
_CHROMA_DIR = _RAIZ / "chroma_db"

# Cache del modelo de embeddings. Se fija a proposito DENTRO del proyecto:
# fastembed por defecto lo mete en la carpeta temporal del sistema, que se
# vacia sola - y volveria a descargar los ~220MB cada dos por tres.
_MODELO_CACHE_DIR = _RAIZ / ".modelos_cache"

# Nombre de la coleccion dentro de ChromaDB (como una "tabla").
_COLECCION = "conversaciones"

# Singletons perezosos: cargar el modelo y abrir ChromaDB cuesta tiempo, asi
# que se hace una sola vez y solo cuando de verdad se usa (no al importar).
_modelo_cache = None
_coleccion_cache = None

# SEG-06: cerrojo que protege los singletons y las operaciones sobre el
# indice. Hasta hoy este fallo estaba marcado como "no alcanzable": solo la
# CLI tocaba el RAG, y en un unico hilo. Deja de serlo al hacer que el bot
# guarde e indexe, porque telegram_bot.py ejecuta el agente con
# asyncio.to_thread - o sea, en un hilo distinto del bucle de eventos.
#
# Que protege exactamente: el patron "if _cache is None: _cache = crear()"
# NO es atomico. Dos hilos pueden ver None a la vez y construir los dos -
# dos modelos de embeddings (~220MB cada uno) o dos clientes de ChromaDB
# sobre el mismo directorio. Y coleccion.add() concurrente sobre el mismo
# indice HNSW puede corromperlo.
#
# RLock y no Lock: indexar_conversaciones() llama a _coleccion() y a
# _incrustar() teniendolo ya cogido; con un Lock normal se bloquearia a si
# mismo (deadlock). RLock deja que el MISMO hilo lo vuelva a coger.
#
# LIMITE CONOCIDO (no lo cierra esto): un cerrojo solo vale DENTRO de un
# proceso. Si se ejecutan a la vez `python -m src.main` y
# `python -m src.telegram_bot`, son dos procesos con dos ChromaDB abiertos
# sobre chroma_db/, y eso ni esto ni ningun lock lo arregla. Ver el aviso
# en main.py y telegram_bot.py.
_cerrojo = threading.RLock()


def _modelo():
    """Devuelve el modelo de embeddings, cargandolo la primera vez."""
    global _modelo_cache
    with _cerrojo:
        if _modelo_cache is None:
            # Import perezoso: fastembed es pesado, no queremos pagarlo solo
            # por importar este modulo (p. ej. en tests que no tocan el RAG).
            import warnings

            from fastembed import TextEmbedding

            _MODELO_CACHE_DIR.mkdir(exist_ok=True)
            # fastembed 0.8 avisa de que este modelo usa "mean pooling" en vez
            # de "CLS". Es informativo, no un problema: mean pooling es justo
            # el correcto para los modelos sentence-transformers. Se silencia
            # para no ensuciar la salida en cada arranque.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=UserWarning)
                _modelo_cache = TextEmbedding(
                    model_name=_MODELO_EMBEDDINGS,
                    cache_dir=str(_MODELO_CACHE_DIR),
                )
        return _modelo_cache


def _coleccion():
    """Devuelve la coleccion de ChromaDB, abriendola la primera vez."""
    global _coleccion_cache
    with _cerrojo:
        if _coleccion_cache is None:
            import chromadb

            # anonymized_telemetry=False (auditoria del 27/07): ChromaDB trae
            # la telemetria ACTIVADA por defecto. En la version instalada
            # (1.5.9) su metodo capture() esta vacio y no envia nada
            # -verificado leyendo el paquete-, pero depender de eso es
            # depender de que no cambie en una actualizacion futura. Con
            # RNF-06 ("los datos no salen de la maquina") como requisito
            # rector, se desactiva explicitamente en vez de confiar en un
            # detalle de implementacion ajeno.
            cliente = chromadb.PersistentClient(
                path=str(_CHROMA_DIR),
                settings=chromadb.Settings(anonymized_telemetry=False),
            )
            # get_or_create: no falla si ya existia de una ejecucion anterior.
            # OJO: NO se le pasa embedding_function - los vectores los
            # calculamos nosotros con fastembed y se los damos ya hechos, para
            # que Chroma no descargue ADEMAS su modelo por defecto
            # (all-MiniLM-L6, solo ingles).
            #
            # hnsw:space="cosine": por defecto ChromaDB mide distancia
            # EUCLIDEA (L2), que se deja influir por la MAGNITUD de los
            # vectores. Para buscar por significado importa la DIRECCION, no
            # el tamaño - la distancia coseno mide justo eso. Verificado el
            # 24/07: con L2 una consulta de "programacion" rankeaba mal; con
            # coseno acierta.
            _coleccion_cache = cliente.get_or_create_collection(
                _COLECCION, metadata={"hnsw:space": "cosine"}
            )
        return _coleccion_cache


def _incrustar(textos: list[str]) -> list[list[float]]:
    """Convierte una lista de textos en sus vectores. embed() devuelve un
    generador de arrays numpy; se pasan a lista de floats para ChromaDB."""
    return [vector.tolist() for vector in _modelo().embed(textos)]


def _id_mensaje(nombre_fichero: str, indice: int) -> str:
    """ID estable y unico de un mensaje: fichero + posicion. Al ser
    deterministico, reindexar NO duplica (mismo id = misma entrada)."""
    return f"{nombre_fichero}:{indice}"


def _mensajes_indexables(historial: list) -> list[tuple[int, str, str]]:
    """De un historial, devuelve (indice, rol, texto) de los mensajes que
    vale la pena indexar: user y assistant, nunca el system prompt (es fijo,
    no es 'memoria' de nada) ni mensajes sin texto real."""
    indexables = []
    for indice, mensaje in enumerate(historial):
        rol = mensaje.get("role")
        texto = mensaje.get("content")
        if rol in ("user", "assistant") and isinstance(texto, str) and texto.strip():
            indexables.append((indice, rol, texto))
    return indexables


def _recolectar_nuevos(ruta: Path, ya_indexados: set) -> tuple[list, list, list]:
    """De UNA conversacion, saca (ids, metadatos, textos) de los mensajes que
    todavia no estan en el indice. No toca ChromaDB: solo lee y filtra.

    Separado en su propia funcion (F5.2+) para que indexar UNA conversacion y
    indexarlas TODAS compartan exactamente la misma logica - si un dia cambia
    que se indexa o con que metadatos, cambia en un solo sitio.
    """
    try:
        datos = cargar_conversacion(ruta)
    except (ConversacionNoDescifrable, FileNotFoundError) as error:
        logging.warning("RAG: se salta '%s' (%s)", ruta.name, error)
        return [], [], []

    ids, metadatos, textos = [], [], []
    for indice, rol, texto in _mensajes_indexables(datos["historial"]):
        id_msg = _id_mensaje(ruta.name, indice)
        if id_msg in ya_indexados:
            continue
        ids.append(id_msg)
        # El texto NO se guarda en ChromaDB (canal lateral): solo el
        # puntero para volver a buscarlo en su JSON al descifrar. El
        # "nombre" de la conversacion (etiqueta de Jordi) SI se guarda:
        # es metadato en claro y da contexto al modelo en los resultados.
        metadatos.append({
            "fichero": ruta.name,
            "indice": indice,
            "rol": rol,
            "fecha": datos.get("fecha", ""),
            "nombre": datos.get("nombre", ""),
        })
        textos.append(texto)
    return ids, metadatos, textos


def _añadir_al_indice(coleccion, ids: list, metadatos: list, textos: list) -> int:
    """Incrusta y persiste. Devuelve cuantos se añadieron."""
    if not ids:
        return 0
    # Se incrustan los textos (en memoria) pero solo se PERSISTEN los
    # vectores + metadatos; los textos se descartan al salir de la funcion.
    coleccion.add(ids=ids, embeddings=_incrustar(textos), metadatas=metadatos)
    logging.info("RAG: %d mensajes nuevos indexados", len(ids))
    return len(ids)


def indexar_conversacion(ruta: Path) -> int:
    """Indexa SOLO la conversacion indicada. Devuelve cuantos mensajes
    nuevos se añadieron.

    La usa el bot de Telegram despues de cada turno (F5.2+). Frente a
    llamar a indexar_conversaciones() cada vez, esta evita releer y
    DESCIFRAR el historial entero de todas las conversaciones entre
    mensaje y mensaje - un coste que crece con el tiempo y que se pagaria
    sin necesidad, porque ya sabemos que fichero cambio.

    Sigue siendo idempotente: los ids son "fichero:indice", asi que
    reindexar el mismo fichero reescrito solo añade los mensajes nuevos.
    """
    with _cerrojo:
        coleccion = _coleccion()
        # Se consultan solo los ids de ESTE fichero, no los del indice
        # entero: con muchas conversaciones, traerse todos los ids en cada
        # turno es justo el coste que esta funcion viene a evitar.
        existentes = set(coleccion.get(where={"fichero": ruta.name}, include=[])["ids"])
        return _añadir_al_indice(coleccion, *_recolectar_nuevos(ruta, existentes))


def indexar_conversaciones() -> int:
    """Recorre las conversaciones guardadas y añade al indice las que aun no
    esten. Idempotente: se puede llamar en cada arranque sin duplicar ni
    reprocesar lo ya indexado (por eso primero mira que ids existen y solo
    incrusta los nuevos - incrustar es lo caro).

    Devuelve cuantos mensajes NUEVOS se indexaron. No lanza: una conversacion
    que no se pueda descifrar (falta la clave) se salta con un aviso, el
    resto se indexa igual (mismo espiritu que RNF-02).
    """
    with _cerrojo:
        coleccion = _coleccion()
        # Ids que ya estan en el indice, para no reprocesarlos.
        ya_indexados = set(coleccion.get(include=[])["ids"])

        ids_nuevos, metadatos_nuevos, textos_nuevos = [], [], []
        for ruta in listar_conversaciones():
            ids, metadatos, textos = _recolectar_nuevos(ruta, ya_indexados)
            ids_nuevos += ids
            metadatos_nuevos += metadatos
            textos_nuevos += textos

        return _añadir_al_indice(coleccion, ids_nuevos, metadatos_nuevos, textos_nuevos)


def olvidar_conversacion(ruta: Path) -> int:
    """Quita del indice vectorial TODOS los mensajes de una conversacion.

    La otra mitad de storage.borrar_conversacion: borrar el JSON sin esto
    dejaria los vectores huerfanos en ChromaDB. No serian legibles (el texto
    nunca se guarda ahi, solo el puntero), pero seguirian saliendo como
    resultados de busqueda que luego se descartan al no poder abrir el
    fichero - o sea, ocupando sitio y empeorando los resultados en silencio.

    Devuelve cuantos se quitaron. Se filtra por el metadato "fichero", que
    es justo como se indexaron (ver _recolectar_nuevos).
    """
    with _cerrojo:
        coleccion = _coleccion()
        ids = coleccion.get(where={"fichero": ruta.name}, include=[])["ids"]
        if not ids:
            return 0
        coleccion.delete(ids=ids)
        logging.info("RAG: %d mensajes olvidados", len(ids))
        return len(ids)


def buscar(consulta: str, n: int = 3) -> list[dict]:
    """Busca los n mensajes mas parecidos por SIGNIFICADO a la consulta.

    Devuelve una lista de dicts {texto, rol, fecha, distancia}. El texto se
    descifra AQUI, bajo demanda, del JSON al que apunta cada resultado - no
    estaba guardado en el indice. Si un fichero ya no existe o no se puede
    descifrar, ese resultado se omite en vez de romper la busqueda.
    """
    # SEG-06: la consulta tambien va bajo cerrojo. Una lectura mientras otro
    # hilo esta a mitad de un coleccion.add() puede ver el indice HNSW en un
    # estado intermedio; y en el bot esos dos hilos existen de verdad
    # (asyncio.to_thread para el turno + el guardado/indexado posterior).
    with _cerrojo:
        coleccion = _coleccion()
        if coleccion.count() == 0:
            return []

        resultado = coleccion.query(
            query_embeddings=_incrustar([consulta]),
            n_results=n,
            include=["metadatas", "distances"],
        )
    # query() devuelve listas anidadas (una por cada consulta); solo mandamos
    # una, asi que se coge el [0].
    metadatos = resultado["metadatas"][0]
    distancias = resultado["distances"][0]

    # Cache por fichero: si dos resultados salen del mismo JSON, se descifra
    # una sola vez.
    cache_ficheros: dict[str, list] = {}
    salida = []
    for meta, distancia in zip(metadatos, distancias):
        nombre = meta["fichero"]
        if nombre not in cache_ficheros:
            try:
                cache_ficheros[nombre] = cargar_conversacion(
                    CONVERSATIONS_DIR / nombre
                )["historial"]
            except (FileNotFoundError, ConversacionNoDescifrable) as error:
                logging.warning("RAG: no se pudo leer '%s' al buscar (%s)", nombre, error)
                cache_ficheros[nombre] = None
        historial = cache_ficheros[nombre]
        if historial is None:
            continue
        salida.append({
            "texto": historial[meta["indice"]]["content"],
            "rol": meta["rol"],
            "fecha": meta["fecha"],
            "nombre": meta.get("nombre", ""),
            "distancia": distancia,
        })
    return salida
