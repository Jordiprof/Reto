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


def _modelo():
    """Devuelve el modelo de embeddings, cargandolo la primera vez."""
    global _modelo_cache
    if _modelo_cache is None:
        # Import perezoso: fastembed es pesado, no queremos pagarlo solo por
        # importar este modulo (p. ej. en tests que no tocan el RAG).
        import warnings

        from fastembed import TextEmbedding

        _MODELO_CACHE_DIR.mkdir(exist_ok=True)
        # fastembed 0.8 avisa de que este modelo usa "mean pooling" en vez de
        # "CLS". Es informativo, no un problema: mean pooling es justo el
        # correcto para los modelos sentence-transformers. Se silencia para no
        # ensuciar la salida en cada arranque.
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
    if _coleccion_cache is None:
        import chromadb

        # anonymized_telemetry=False (auditoria del 27/07): ChromaDB trae la
        # telemetria ACTIVADA por defecto. En la version instalada (1.5.9) su
        # metodo capture() esta vacio y no envia nada -verificado leyendo el
        # paquete-, pero depender de eso es depender de que no cambie en una
        # actualizacion futura. Con RNF-06 ("los datos no salen de la
        # maquina") como requisito rector, se desactiva explicitamente en vez
        # de confiar en un detalle de implementacion ajeno.
        cliente = chromadb.PersistentClient(
            path=str(_CHROMA_DIR),
            settings=chromadb.Settings(anonymized_telemetry=False),
        )
        # get_or_create: no falla si ya existia de una ejecucion anterior.
        # OJO: NO se le pasa embedding_function - los vectores los calculamos
        # nosotros con fastembed y se los damos ya hechos, para que Chroma no
        # descargue ADEMAS su modelo por defecto (all-MiniLM-L6, solo ingles).
        #
        # hnsw:space="cosine": por defecto ChromaDB mide distancia EUCLIDEA
        # (L2), que se deja influir por la MAGNITUD de los vectores. Para
        # buscar por significado importa la DIRECCION, no el tamaño - la
        # distancia coseno mide justo eso. Verificado el 24/07: con L2 una
        # consulta de "programacion" rankeaba mal; con coseno acierta.
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


def indexar_conversaciones() -> int:
    """Recorre las conversaciones guardadas y añade al indice las que aun no
    esten. Idempotente: se puede llamar en cada arranque sin duplicar ni
    reprocesar lo ya indexado (por eso primero mira que ids existen y solo
    incrusta los nuevos - incrustar es lo caro).

    Devuelve cuantos mensajes NUEVOS se indexaron. No lanza: una conversacion
    que no se pueda descifrar (falta la clave) se salta con un aviso, el
    resto se indexa igual (mismo espiritu que RNF-02).
    """
    coleccion = _coleccion()
    # Ids que ya estan en el indice, para no reprocesarlos.
    ya_indexados = set(coleccion.get(include=[])["ids"])

    ids_nuevos, metadatos_nuevos, textos_nuevos = [], [], []

    for ruta in listar_conversaciones():
        try:
            datos = cargar_conversacion(ruta)
        except ConversacionNoDescifrable as error:
            logging.warning("RAG: se salta '%s' (%s)", ruta.name, error)
            continue

        for indice, rol, texto in _mensajes_indexables(datos["historial"]):
            id_msg = _id_mensaje(ruta.name, indice)
            if id_msg in ya_indexados:
                continue
            ids_nuevos.append(id_msg)
            # El texto NO se guarda en ChromaDB (canal lateral): solo el
            # puntero para volver a buscarlo en su JSON al descifrar. El
            # "nombre" de la conversacion (etiqueta de Jordi) SI se guarda:
            # es metadato en claro y da contexto al modelo en los resultados.
            metadatos_nuevos.append({
                "fichero": ruta.name,
                "indice": indice,
                "rol": rol,
                "fecha": datos.get("fecha", ""),
                "nombre": datos.get("nombre", ""),
            })
            textos_nuevos.append(texto)

    if not ids_nuevos:
        return 0

    # Se incrustan los textos (en memoria) pero solo se PERSISTEN los
    # vectores + metadatos; los textos se descartan al salir de la funcion.
    coleccion.add(
        ids=ids_nuevos,
        embeddings=_incrustar(textos_nuevos),
        metadatas=metadatos_nuevos,
    )
    logging.info("RAG: %d mensajes nuevos indexados", len(ids_nuevos))
    return len(ids_nuevos)


def buscar(consulta: str, n: int = 3) -> list[dict]:
    """Busca los n mensajes mas parecidos por SIGNIFICADO a la consulta.

    Devuelve una lista de dicts {texto, rol, fecha, distancia}. El texto se
    descifra AQUI, bajo demanda, del JSON al que apunta cada resultado - no
    estaba guardado en el indice. Si un fichero ya no existe o no se puede
    descifrar, ese resultado se omite en vez de romper la busqueda.
    """
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
