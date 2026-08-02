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


def incrustar_textos(textos: list[str]) -> list[list[float]]:
    """Version PUBLICA de _incrustar, para quien necesite vectores sin tocar
    el indice persistente.

    La usa documentos.py para buscar dentro de un PDF/Word (01/08). Se
    reutiliza el MISMO modelo de embeddings ya cargado en memoria - cargar
    otro serian 220 MB mas de RAM para hacer exactamente lo mismo.

    Lo importante es lo que esta funcion NO hace: no toca la coleccion de
    ChromaDB. Los trozos de un adjunto NO deben acabar en la memoria
    permanente - un documento que se lee una vez no es una conversacion, y
    meterlo alli ensuciaria las busquedas de recuerdos para siempre.
    """
    with _cerrojo:
        return _incrustar(textos)


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


# --- Ventana de turno (02/08) ---------------------------------------------
#
# EL FALLO nº1 DE LA MEMORIA, y por que este es el arreglo. Cada mensaje se
# indexa SUELTO, asi que buscar "cual es mi color favorito" encuentra las
# tres veces que se hizo esa PREGUNTA y ninguna respuesta: el dato solo
# aparecia si buscabas "azul gris", o sea SOLO SI YA SABIAS LA RESPUESTA.
# Reproducido con datos el 01/08 y otra vez el 02/08 (`/recuerdo` devolvio
# 5 de 5 preguntas). Mitigado a medias subiendo de 3 a 5 los recuerdos.
#
# LO QUE SE DESCARTO. El backlog decia "indexar PARES pregunta-respuesta",
# o sea meter las dos en un solo vector. Se descarto porque las respuestas
# de este bot son largas (500-1500 caracteres) y una pregunta de 8 palabras
# quedaria diluida en el promedio: se arreglaria buscar la pregunta a costa
# de EMPEORAR busquedas que hoy si aciertan. Ademas obligaria a borrar
# chroma_db/ y reindexarlo todo.
#
# LO QUE SE HACE. Se sigue indexando mensaje a mensaje -vectores afilados,
# indice intacto, CERO reindexado- y es la BUSQUEDA la que devuelve el
# turno completo: si el acierto es una pregunta se adjunta su respuesta, y
# al reves. Encontrar la pregunta pasa a ser suficiente.

# Cuantos aciertos se le piden a Chroma por cada turno que se quiere. Hace
# falta margen porque varios aciertos colapsan en el mismo turno al
# deduplicar (la pregunta Y su respuesta pueden acertar las dos). En HNSW
# pedir 15 vecinos en vez de 5 es coste despreciable: el grafo se recorre
# igual. Y NO cuesta ningun descifrado extra, porque el corte a n ocurre
# ANTES de tocar el disco.
_SOBREMUESTREO = 3

# Tope por mensaje al devolverlo. Antes 5 aciertos podian ser 5 preguntas
# cortas; ahora se garantiza incluir RESPUESTAS, que en este bot son largas,
# y esto se reenvia en cada turno posterior (AUD-03). Se recorta con marca
# VISIBLE, que es la misma politica que el truncado de documentos: recortado
# y a la vista es mejor que ausente y en silencio.
_MAX_CARACTERES_MENSAJE = 800


def _recortar(texto: str) -> str:
    if len(texto) <= _MAX_CARACTERES_MENSAJE:
        return texto
    return texto[:_MAX_CARACTERES_MENSAJE] + "… (recortado)"


# --- Ruido: el bot recordandose a si mismo fallando (02/08) ----------------
#
# EL PROBLEMA, visto por Jordi en cuanto la ventana de turno empezo a
# enseñar las respuestas. Buscando "color favorito" salian 5 recuerdos y
# DOS eran el propio bot diciendo que no lo sabia:
#
#   yo: Lo siento, pero no tengo informacion sobre tus preferencias...
#   yo: Buena pregunta, pero no tengo ni idea. Nunca me lo has dicho...
#
# Esas respuestas se guardaron, se indexaron, y ahora compiten por una de
# las 5 plazas con los recuerdos que SI tienen el dato. Un turno que acaba
# en "no lo se" no aporta nada como recuerdo: ni la pregunta (solo dice que
# se pregunto) ni la respuesta (dice que no se sabia).
#
# Ya pasaba antes de la ventana de turno -las respuestas siempre se
# indexaron- pero era invisible porque la busqueda solo devolvia preguntas.
#
# SE FILTRA AL BUSCAR Y NO AL INDEXAR, a proposito: el indice no se toca,
# asi que si mañana el criterio resulta ser malo se cambia una constante y
# ya esta, sin reindexar nada ni haber perdido conversaciones. Filtrar al
# indexar seria una decision IRREVERSIBLE tomada con un criterio heuristico.
_PATRONES_NEGATIVA = (
    "no lo sé", "no lo se", "no tengo información", "no tengo informacion",
    "no tengo ni idea", "no puedo decirte", "no tengo registro", "no encuentro",
    "no me lo has dicho", "nunca me lo has dicho", "no tengo ese dato",
    "está apagado", "esta apagado", "está apagada", "esta apagada",
)

# Solo se mira el PRINCIPIO de la respuesta, y este numero no es a ojo: sale
# de un caso real de la memoria de Jordi que NO debe filtrarse -
#
#   "JIM, tu comida favorita es la lasaña. Tambien mencionaste que tus
#    colores favoritos son el azul y el gris, pero sobre el deporte
#    favorito no tengo informacion"
#
# Ese recuerdo TIENE el dato y ademas contiene una negativa, en la posicion
# ~155. Una negativa de verdad se anuncia al empezar ("Lo siento, no...",
# "Buena pregunta, pero no tengo ni idea", posiciones 11 y 21); una que
# aparece tarde es un matiz dentro de una respuesta util. Con 80 los tres
# casos reales caen del lado correcto.
_VENTANA_NEGATIVA = 80


def _es_negativa(respuesta: str | None) -> bool:
    """¿Esta respuesta es el bot admitiendo que no sabe algo?

    Es una HEURISTICA y se comporta como tal: ante la duda NO filtra. Un
    falso negativo cuesta una plaza de ruido; un falso positivo esconderia
    un recuerdo bueno, que es mucho peor.
    """
    if not respuesta:
        # Un turno sin respuesta no es una negativa: es un turno que se
        # quedo a medias, y su pregunta puede seguir valiendo.
        return False
    principio = respuesta[:_VENTANA_NEGATIVA].lower()
    return any(patron in principio for patron in _PATRONES_NEGATIVA)


def _inicio_del_turno(meta: dict) -> int:
    """Indice donde EMPIEZA el turno al que pertenece un acierto.

    Se decide por el ROL y no por la paridad del indice: el historial
    guardado es system, user, assistant, user... pero fiarse de esa
    aritmetica romperia con cualquier fichero que no la cumpla.
    """
    indice = meta["indice"]
    if meta.get("rol") == "assistant" and indice > 0:
        return indice - 1
    return indice


def _turnos_ordenados(metadatos: list, distancias: list) -> list[tuple]:
    """FASE A: de los aciertos sueltos a turnos unicos, SIN descifrar nada.

    Deduplica por (fichero, inicio) conservando el orden, que ya viene por
    distancia ascendente.

    NO corta a n: el corte tiene que ocurrir DESPUES de descartar las
    respuestas negativas, porque si no el sobremuestreo no serviria de nada
    -se cortaria a 5 y luego el filtro dejaria 3-. Lo que se sigue evitando
    es descifrar de mas: la fase B para en cuanto reune los n que necesita.
    """
    vistos: dict[tuple[str, int], tuple] = {}
    for meta, distancia in zip(metadatos, distancias):
        clave = (meta["fichero"], _inicio_del_turno(meta))
        # El primero que llega es el mas cercano; los siguientes del mismo
        # turno son redundantes y se tiran (son justo las 3 veces que se
        # pregunto lo mismo, que antes ocupaban 3 de las 5 plazas).
        if clave not in vistos:
            vistos[clave] = (meta, distancia)
    return list(vistos.values())


def buscar(consulta: str, n: int = 3) -> list[dict]:
    """Busca los n TURNOS mas parecidos por SIGNIFICADO a la consulta.

    Devuelve dicts {pregunta, respuesta, fecha, nombre, distancia}. Ya no
    devuelve mensajes sueltos con su `rol`: la unidad es el intercambio,
    porque encontrar una pregunta sin su respuesta no servia de nada.
    `respuesta` puede ser None (turno guardado sin contestar) y `pregunta`
    tambien (un assistant sin user delante).

    El texto se descifra AQUI, bajo demanda, del JSON al que apunta cada
    resultado - no estaba guardado en el indice. Si un fichero ya no existe
    o no se puede descifrar, ese resultado se omite en vez de romper la
    busqueda entera.

    Se descartan los turnos cuya respuesta es el bot admitiendo que no sabe
    (ver _es_negativa): ocupaban plaza sin aportar nada. Si TODO lo
    encontrado fuera de ese tipo, se devuelve igualmente - mas vale ruido
    que dejar al usuario sin nada por una heuristica.
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
            n_results=n * _SOBREMUESTREO,
            include=["metadatas", "distances"],
        )
    # query() devuelve listas anidadas (una por cada consulta); solo mandamos
    # una, asi que se coge el [0].
    turnos = _turnos_ordenados(resultado["metadatas"][0], resultado["distances"][0])

    # FASE B: descifrar los candidatos EN ORDEN hasta reunir n buenos.
    # Cache por fichero: si dos turnos salen del mismo JSON, se descifra una
    # sola vez.
    cache_ficheros: dict[str, list] = {}
    salida = []
    # Los turnos que solo dicen "no lo se" se apartan aqui en vez de tirarse:
    # son la RED DE SEGURIDAD. Si el filtro se lo llevara todo, es mejor
    # devolver ruido que dejar al usuario sin nada por una heuristica.
    apartados = []
    for meta, distancia in turnos:
        if len(salida) >= n:
            break
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

        # El indice puede apuntar FUERA del historial: guardar_conversacion
        # reescribe el mismo fichero, asi que uno que encoja deja ids viejos
        # apuntando al vacio. Antes esto lanzaba IndexError y tumbaba la
        # busqueda ENTERA; ahora se salta ese resultado, igual que ya se
        # hacia con un fichero ilegible.
        inicio = _inicio_del_turno(meta)
        if not 0 <= inicio < len(historial):
            logging.warning("RAG: indice fuera de rango en '%s', se salta", nombre)
            continue

        # No se asume que en `inicio` haya un user ni que en el siguiente
        # haya un assistant: se comprueba el rol y se monta con lo que haya.
        pregunta = respuesta = None
        if historial[inicio].get("role") == "user":
            pregunta = historial[inicio].get("content")
            siguiente = inicio + 1
            if siguiente < len(historial) and historial[siguiente].get("role") == "assistant":
                respuesta = historial[siguiente].get("content")
        else:
            respuesta = historial[inicio].get("content")

        turno = {
            "pregunta": _recortar(pregunta) if pregunta else None,
            "respuesta": _recortar(respuesta) if respuesta else None,
            "fecha": meta["fecha"],
            "nombre": meta.get("nombre", ""),
            "distancia": distancia,
        }
        # Un turno que acaba en "no lo se" no aporta nada como recuerdo, y
        # antes se comia una de las 5 plazas (Jordi lo vio: de 5 resultados
        # de "color favorito", DOS eran el bot diciendo que no sabia).
        if _es_negativa(respuesta):
            apartados.append(turno)
        else:
            salida.append(turno)

    # RED DE SEGURIDAD: si lo unico que habia eran negativas, se devuelven.
    # El filtro puede equivocarse; dejar al usuario sin ningun resultado
    # teniendo algo que enseñar seria peor que enseñarle ruido.
    return salida or apartados[:n]
