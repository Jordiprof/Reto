# F5.3: tests de la memoria semantica (RAG local).
#
# NO usan el modelo de embeddings real (fastembed): descargarlo son ~220MB
# y necesitaria red - los tests deben ser deterministas y a coste 0 (misma
# regla que el ProveedorFalso de F5.0/T6). Se inyecta un "modelo" falso que
# convierte cada texto en un vector trivial pero suficiente para que la
# busqueda por cercania funcione y se pueda comprobar la logica.
#
# Lo que de verdad se prueba aqui:
#   1. Round-trip: indexar y luego encontrar por significado aproximado.
#   2. Idempotencia: reindexar no duplica.
#   3. EL PUNTO CLAVE DE PRIVACIDAD: el texto en claro NO queda guardado en
#      ChromaDB (solo vectores + punteros) - el "canal lateral" que advirtio
#      el comite. Si esto se rompe, el cifrado de storage.py no sirve.
import json

import pytest
from cryptography.fernet import Fernet

from src import rag, storage


class ModeloFalso:
    """Embeddings deterministas sin red: cada texto -> un vector de 3
    numeros basado en cuantas veces aparecen 3 palabras clave. Suena
    tonto, pero basta para que 'medico'/'cita' queden cerca y 'python'
    lejos, que es lo que necesita la busqueda por cercania."""

    _PALABRAS = ("medico", "cita", "python")

    def embed(self, textos):
        for texto in textos:
            t = texto.lower()
            yield _Vector([float(t.count(p)) for p in self._PALABRAS])


class _Vector(list):
    """Lista que ademas responde a .tolist() (como los arrays de numpy que
    devuelve fastembed), para que rag._incrustar la trate igual."""

    def tolist(self):
        return list(self)


@pytest.fixture
def rag_aislado(tmp_path, monkeypatch):
    """Redirige TODAS las rutas (conversaciones + indice ChromaDB) a una
    carpeta temporal, inyecta el modelo falso y resetea los singletons de
    rag para que cada test empiece limpio."""
    # storage: conversaciones y su indice SQLite en la carpeta temporal.
    monkeypatch.setattr(storage, "CONVERSATIONS_DIR", tmp_path / "conversations")
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "conversations.db")
    storage.CONVERSATIONS_DIR.mkdir()
    # rag mira CONVERSATIONS_DIR importado en su propio modulo: se apunta igual.
    monkeypatch.setattr(rag, "CONVERSATIONS_DIR", storage.CONVERSATIONS_DIR)
    monkeypatch.setattr(rag, "_CHROMA_DIR", tmp_path / "chroma_db")

    # Singletons: resetear + inyectar el modelo falso (evita descargar nada).
    monkeypatch.setattr(rag, "_modelo_cache", ModeloFalso())
    monkeypatch.setattr(rag, "_coleccion_cache", None)

    # Sin clave de cifrado en estos tests salvo que el test la ponga.
    monkeypatch.delenv("CONVERSATIONS_KEY", raising=False)
    return tmp_path


def _guardar(historial):
    return storage.guardar_conversacion(historial, "groq", "llama-3.3-70b-versatile")


def _texto_de(resultado):
    """Todo el texto de un resultado, venga del lado que venga.

    VENTANA DE TURNO (02/08): buscar() devuelve el intercambio entero
    {pregunta, respuesta} en vez de un mensaje suelto con su `rol`. Estos
    tests preguntan "¿aparece esta palabra en lo que se recuperó?", y esa
    pregunta sigue teniendo el mismo sentido - solo cambia dónde mirar.
    """
    return " ".join(
        filter(None, [resultado.get("pregunta"), resultado.get("respuesta")])
    )


CONV_MEDICO = [
    {"role": "system", "content": "Eres un asistente."},
    {"role": "user", "content": "Apúntame la cita del medico del jueves"},
    {"role": "assistant", "content": "Hecho, jueves apuntado."},
]
CONV_PYTHON = [
    {"role": "system", "content": "Eres un asistente."},
    {"role": "user", "content": "Enséñame python desde cero"},
]


def test_indexar_y_buscar_por_significado(rag_aislado):
    """El round-trip completo: guardo conversaciones, las indexo, y una
    busqueda encuentra la relevante por encima de la irrelevante."""
    _guardar(CONV_MEDICO)
    _guardar(CONV_PYTHON)

    assert rag.indexar_conversaciones() == 3  # 2 del medico + 1 del python

    resultados = rag.buscar("cuando es mi cita con el medico", n=1)

    assert len(resultados) == 1
    assert "medico" in _texto_de(resultados[0]).lower()


def test_reindexar_no_duplica(rag_aislado):
    """Idempotencia: llamar dos veces no vuelve a añadir lo ya indexado."""
    _guardar(CONV_MEDICO)

    assert rag.indexar_conversaciones() == 3 - 1  # 2 mensajes (sin el system)
    assert rag.indexar_conversaciones() == 0       # segunda vez: nada nuevo


def test_el_system_prompt_no_se_indexa(rag_aislado):
    """El system prompt es fijo, no es 'memoria' - no debe entrar al indice."""
    _guardar(CONV_MEDICO)
    rag.indexar_conversaciones()

    # 2 mensajes indexados (user + assistant), nunca el system.
    assert rag._coleccion().count() == 2


def test_chromadb_no_guarda_el_texto_en_claro(rag_aislado):
    """EL TEST DE PRIVACIDAD (comite 24/07): en el indice solo debe haber
    vectores y punteros (fichero + indice + rol + fecha), NUNCA el texto de
    los mensajes. Si el texto apareciera aqui, chroma_db/ seria un canal
    lateral que deja legible lo que storage.py cifra."""
    _guardar(CONV_MEDICO)
    rag.indexar_conversaciones()

    volcado = rag._coleccion().get(include=["metadatas", "documents"])

    # El contenido de los mensajes NO esta en ninguna parte del indice.
    texto_completo = json.dumps(volcado, ensure_ascii=False, default=str)
    assert "cita del medico" not in texto_completo
    assert "jueves apuntado" not in texto_completo
    # Lo que SI hay: punteros para volver a buscarlo en el JSON.
    assert volcado["metadatas"][0]["fichero"].endswith(".json")
    assert "indice" in volcado["metadatas"][0]


def test_busqueda_descifra_bajo_demanda(rag_aislado, monkeypatch):
    """Con cifrado activo: el texto NO esta en el indice (cifrado o no), y
    aun asi buscar() lo devuelve en claro - porque lo descifra del JSON en
    el momento. Demuestra que las dos piezas (F5.3 1/2 y 2/2) encajan."""
    monkeypatch.setenv("CONVERSATIONS_KEY", Fernet.generate_key().decode())
    _guardar(CONV_MEDICO)
    rag.indexar_conversaciones()

    # El JSON en disco esta cifrado (el texto no se ve)...
    ruta = next(storage.CONVERSATIONS_DIR.glob("*.json"))
    assert "medico" not in ruta.read_text(encoding="utf-8")

    # ...pero la busqueda lo devuelve descifrado.
    resultados = rag.buscar("cita del medico", n=1)
    assert "medico" in _texto_de(resultados[0]).lower()


def test_buscar_sin_indice_devuelve_vacio(rag_aislado):
    """Sin nada indexado, buscar no revienta: devuelve lista vacia."""
    assert rag.buscar("lo que sea") == []


# --- F5.2+: indexado incremental de UNA conversacion -------------------
# Lo que usa el bot de Telegram despues de cada turno. La alternativa
# (indexar_conversaciones() en cada mensaje) obliga a releer y DESCIFRAR el
# historial entero de todas las conversaciones entre mensaje y mensaje.


def test_indexar_una_sola_conversacion(rag_aislado):
    """Solo entra al indice la conversacion indicada, no las demas."""
    ruta_medico = _guardar(CONV_MEDICO)
    _guardar(CONV_PYTHON)

    assert rag.indexar_conversacion(ruta_medico) == 2  # user + assistant
    assert rag._coleccion().count() == 2               # el python NO esta

    resultados = rag.buscar("python", n=3)
    assert all("python" not in _texto_de(r).lower() for r in resultados)


def test_reindexar_la_misma_conversacion_no_duplica(rag_aislado):
    """Idempotencia, igual que la version completa."""
    ruta = _guardar(CONV_MEDICO)

    assert rag.indexar_conversacion(ruta) == 2
    assert rag.indexar_conversacion(ruta) == 0


def test_conversacion_reescrita_solo_indexa_lo_nuevo(rag_aislado):
    """EL CASO DEL BOT: guarda el turno 1, indexa; llega el turno 2, se
    REESCRIBE el mismo fichero y se reindexa. Solo deben entrar los
    mensajes nuevos - los de antes ya tienen su id 'fichero:indice' y no se
    vuelven a incrustar (incrustar es lo caro)."""
    ruta = _guardar(CONV_MEDICO)
    assert rag.indexar_conversacion(ruta) == 2

    ampliada = CONV_MEDICO + [
        {"role": "user", "content": "y apunta tambien la cita del dentista"},
        {"role": "assistant", "content": "Dentista apuntado."},
    ]
    storage.guardar_conversacion(ampliada, "groq", "m", ruta=ruta)

    assert rag.indexar_conversacion(ruta) == 2  # solo los 2 nuevos
    assert rag._coleccion().count() == 4        # 2 + 2, sin duplicados


def test_lo_guardado_por_una_via_lo_encuentra_la_otra(rag_aislado):
    """La razon de ser de todo esto (memoria compartida CLI <-> Telegram):
    una conversacion escrita por un lado tiene que ser recuperable por el
    otro. Aqui se simula guardando/indexando como hace el bot y buscando
    como hace la tool buscar_en_recuerdos."""
    ruta = _guardar(CONV_MEDICO)
    rag.indexar_conversacion(ruta)

    resultados = rag.buscar("cita del medico", n=1)

    assert len(resultados) == 1
    assert "medico" in _texto_de(resultados[0]).lower()


def test_indexar_conversacion_inexistente_no_revienta(rag_aislado):
    """El bot llama a esto en segundo plano tras responder. Si el fichero
    desapareciera, debe devolver 0, no tumbar el turno (mismo espiritu que
    RNF-02: el programa avisa y sigue vivo)."""
    fantasma = storage.CONVERSATIONS_DIR / "no-existe.json"

    assert rag.indexar_conversacion(fantasma) == 0


def test_olvidar_conversacion_la_saca_del_indice(rag_aislado):
    """La otra mitad de borrar: sin esto quedarian vectores huerfanos en
    ChromaDB, saliendo como resultados que luego se descartan al no poder
    abrir el fichero - ocupando sitio y empeorando la busqueda en silencio."""
    ruta = _guardar(CONV_MEDICO)
    rag.indexar_conversacion(ruta)
    assert rag._coleccion().count() == 2

    assert rag.olvidar_conversacion(ruta) == 2

    assert rag._coleccion().count() == 0
    assert rag.buscar("cita del medico") == []


def test_olvidar_solo_afecta_a_esa_conversacion(rag_aislado):
    """Borrar una charla no puede llevarse por delante las demas."""
    ruta_medico = _guardar(CONV_MEDICO)
    _guardar(CONV_PYTHON)
    rag.indexar_conversaciones()

    rag.olvidar_conversacion(ruta_medico)

    assert rag._coleccion().count() == 1  # queda el de python
    assert _texto_de(rag.buscar("python", n=1)[0]).lower().count("python") >= 1


# --- VENTANA DE TURNO (02/08) -----------------------------------------
# El fallo nº1 de la memoria: cada mensaje se indexa SUELTO, asi que buscar
# "cual es mi color favorito" devolvia las tres veces que se hizo esa
# PREGUNTA y ninguna respuesta. Reproducido con datos el 01/08 y otra vez el
# 02/08 (/recuerdo devolvio 5 de 5 preguntas). El dato solo aparecia si
# buscabas por la respuesta - o sea, SOLO SI YA LA SABIAS.

CONV_COLOR = [
    {"role": "system", "content": "Eres un asistente."},
    {"role": "user", "content": "cual es mi cita python"},
    {"role": "assistant", "content": "Tu cita es el jueves con el medico"},
]


def test_encontrar_la_pregunta_TRAE_la_respuesta(rag_aislado):
    """EL TEST QUE JUSTIFICA TODO ESTO. Se busca por palabras que solo
    estan en la PREGUNTA, y el resultado tiene que traer lo que se
    contesto. Antes devolvia la pregunta a secas y no servia de nada."""
    _guardar(CONV_COLOR)
    rag.indexar_conversaciones()

    resultado = rag.buscar("python", n=1)[0]

    assert "cita python" in resultado["pregunta"]
    assert "jueves con el medico" in resultado["respuesta"]


def test_encontrar_la_respuesta_TRAE_la_pregunta(rag_aislado):
    """El camino inverso: si el acierto es del assistant, se adjunta la
    pregunta que lo origino, que es la que le da sentido."""
    _guardar(CONV_COLOR)
    rag.indexar_conversaciones()

    resultado = rag.buscar("medico", n=1)[0]

    assert "jueves con el medico" in resultado["respuesta"]
    assert "cita python" in resultado["pregunta"]


def test_la_pregunta_y_su_respuesta_NO_ocupan_dos_plazas(rag_aislado):
    """La deduplicacion. Los dos mensajes de este turno aciertan a la vez
    (los dos contienen palabras de la consulta), y aun asi tiene que salir
    UN resultado: antes eran las 3 veces que se pregunto lo mismo comiendose
    3 de las 5 plazas."""
    _guardar(CONV_COLOR)
    rag.indexar_conversaciones()
    assert rag._coleccion().count() == 2  # los DOS mensajes indexados

    resultados = rag.buscar("python medico", n=5)

    assert len(resultados) == 1


def test_se_piden_a_chroma_mas_aciertos_que_turnos(rag_aislado, monkeypatch):
    """El sobremuestreo. Sin margen, los aciertos que colapsan en el mismo
    turno dejarian menos resultados de los pedidos. Se comprueba sobre la
    llamada real a Chroma, no sobre la constante."""
    _guardar(CONV_MEDICO)
    rag.indexar_conversaciones()

    pedidos = []
    coleccion = rag._coleccion()
    original = coleccion.query
    monkeypatch.setattr(
        coleccion, "query",
        lambda **kw: pedidos.append(kw["n_results"]) or original(**kw),
    )

    rag.buscar("medico", n=2)

    assert pedidos == [2 * rag._SOBREMUESTREO]


def test_un_turno_sin_respuesta_no_revienta(rag_aislado):
    """La conversacion se guardo con la pregunta pero sin contestar (el
    proceso murio a mitad). Tiene que devolverse igual, con respuesta None."""
    _guardar(CONV_PYTHON)  # solo system + user, sin assistant
    rag.indexar_conversaciones()

    resultado = rag.buscar("python", n=1)[0]

    assert "python" in resultado["pregunta"].lower()
    assert resultado["respuesta"] is None


def test_un_indice_fuera_de_rango_no_tumba_la_busqueda(rag_aislado):
    """BUG LATENTE que se cierra de paso: guardar_conversacion REESCRIBE el
    mismo fichero, asi que uno que encoja deja ids apuntando al vacio. Antes
    era un IndexError que se llevaba por delante la busqueda ENTERA.

    OJO AL MONTAJE, que la primera version de este test estaba MAL y lo
    destapo una mutacion: si se encoge solo un mensaje, el assistant
    huerfano del indice 2 mapea al user del 1, que SI existe - la ventana de
    turno tapaba el caso por accidente y el test pasaba con el guard
    quitado. Hace falta que el INICIO del turno quede fuera, y para eso la
    conversacion tiene que encoger por debajo de un turno entero.
    """
    ruta = _guardar([
        {"role": "system", "content": "Eres un asistente."},
        {"role": "user", "content": "primera cita python"},
        {"role": "assistant", "content": "Primera respuesta con medico"},
        {"role": "user", "content": "segunda cita python"},
        {"role": "assistant", "content": "Segunda respuesta con medico"},
    ])
    rag.indexar_conversaciones()

    # Encoge a system + user: los indices 2, 3 y 4 dejan de existir, asi que
    # el turno que empezaba en el 3 apunta entero al vacio.
    storage.guardar_conversacion(
        [
            {"role": "system", "content": "Eres un asistente."},
            {"role": "user", "content": "primera cita python"},
        ],
        "groq", "llama-3.3-70b-versatile", ruta=ruta,
    )

    resultados = rag.buscar("python medico", n=5)  # no lanza

    assert all(r["pregunta"] or r["respuesta"] for r in resultados)


def test_un_mensaje_larguisimo_se_recorta_con_marca_visible(rag_aislado):
    """Ahora se garantiza incluir RESPUESTAS, y en este bot son largas: esto
    se reenvia en CADA turno posterior (AUD-03). Recortado y a la vista es
    mejor que ausente y en silencio, misma politica que los documentos."""
    largo = "medico " * 500
    _guardar([
        {"role": "system", "content": "Eres un asistente."},
        {"role": "user", "content": "cuentame"},
        {"role": "assistant", "content": largo},
    ])
    rag.indexar_conversaciones()

    resultado = rag.buscar("medico", n=1)[0]

    assert len(resultado["respuesta"]) < len(largo)
    assert "(recortado)" in resultado["respuesta"]


def test_de_un_turno_se_conserva_el_acierto_MAS_CERCANO():
    """TEST QUE NACE DE UNA MUTACION SUPERVIVIENTE (02/08).

    Quitar el `if clave not in vistos` dejaba los 20 tests en VERDE, y eso
    destapo que la deduplicacion no la hace ese `if`: la hace el propio
    dict, porque la clave (fichero, inicio) ya es unica. Lo que el `if`
    protege de verdad es CUAL de los aciertos del mismo turno se conserva -
    y como llegan ordenados por distancia ascendente, el primero es el mas
    cercano. Sin el `if` se quedaba el PEOR, y la distancia es informacion
    que buscar() devuelve a quien la llame.

    Se prueba sobre la funcion pura, sin Chroma: asi el test mide la regla
    y no la casualidad de que dos vectores queden a tal o cual distancia.
    """
    metadatos = [
        {"fichero": "a.json", "indice": 1, "rol": "user"},
        {"fichero": "a.json", "indice": 2, "rol": "assistant"},
    ]

    turnos = rag._turnos_ordenados(metadatos, [0.1, 0.9])

    assert len(turnos) == 1
    assert turnos[0][1] == 0.1


# --- Ruido: el bot recordandose a si mismo fallando (02/08) ------------
# Visto por Jordi en cuanto la ventana de turno empezo a enseñar las
# respuestas: buscando "color favorito" salian 5 recuerdos y DOS eran el
# propio bot diciendo que no lo sabia. Los textos de estos tests son los
# SUYOS, copiados de la memoria real, no inventados.

NEGATIVAS_REALES = [
    "Lo siento, pero no tengo información sobre tus preferencias personales "
    "como deporte favorito, comida favorita o color favorito. No lo sé.",
    "Buena pregunta, pero no tengo ni idea. Nunca me lo has dicho (al menos, "
    "yo no lo recuerdo). Si quieres, te lo anoto y lo guardo en mi memoria.",
    "Lo siento, no puedo decirte cuál es tu deporte favorito porque mi "
    "herramienta de memoria está apagada. Puedes encenderla en /tools.",
]

# EL CASO QUE NO SE PUEDE FILTRAR, y por el que la ventana es de 80 y no de
# 200: tiene el dato (lasaña) Y ademas una negativa, pero al final.
CON_DATO_Y_NEGATIVA_AL_FINAL = (
    "JIM, tu comida favorita es la lasaña. También mencionaste anteriormente "
    "que tus colores favoritos son el azul y el gris, pero sobre el deporte "
    "favorito no tengo información."
)


@pytest.mark.parametrize("texto", NEGATIVAS_REALES)
def test_las_negativas_reales_se_detectan(texto):
    assert rag._es_negativa(texto)


def test_una_respuesta_con_el_dato_NO_se_filtra_aunque_lleve_una_negativa():
    """El falso positivo que habria costado caro. Si se mirara la respuesta
    entera en vez de su principio, este recuerdo -que es el que SI tiene la
    lasaña- desapareceria de las busquedas."""
    assert not rag._es_negativa(CON_DATO_Y_NEGATIVA_AL_FINAL)


def test_un_turno_sin_respuesta_no_cuenta_como_negativa():
    """Quedarse a medias no es lo mismo que decir que no se sabe: la
    pregunta de ese turno puede seguir valiendo."""
    assert not rag._es_negativa(None)
    assert not rag._es_negativa("")


def test_el_ruido_no_ocupa_plaza_en_la_busqueda(rag_aislado):
    """DE PUNTA A PUNTA, que es lo que de verdad importa: dos turnos hablan
    de lo mismo y solo uno tiene el dato. El bueno tiene que salir aunque el
    ruido estuviera mas cerca de la consulta."""
    _guardar([
        {"role": "system", "content": "Eres un asistente."},
        {"role": "user", "content": "cual es mi cita python"},
        {"role": "assistant", "content": NEGATIVAS_REALES[0]},
    ])
    _guardar([
        {"role": "system", "content": "Eres un asistente."},
        {"role": "user", "content": "mi cita python"},
        {"role": "assistant", "content": "Tu cita es el jueves con el medico"},
    ])
    rag.indexar_conversaciones()

    resultados = rag.buscar("cita python", n=5)

    assert len(resultados) == 1
    assert "jueves con el medico" in resultados[0]["respuesta"]


def test_si_TODO_es_ruido_se_devuelve_igual(rag_aislado):
    """LA RED DE SEGURIDAD. El filtro es una heuristica y puede
    equivocarse: dejar al usuario sin ningun resultado teniendo algo que
    enseñarle seria peor que enseñarle ruido."""
    _guardar([
        {"role": "system", "content": "Eres un asistente."},
        {"role": "user", "content": "cual es mi cita python"},
        {"role": "assistant", "content": NEGATIVAS_REALES[0]},
    ])
    rag.indexar_conversaciones()

    resultados = rag.buscar("cita python", n=5)

    assert len(resultados) == 1
    assert "no tengo información" in resultados[0]["respuesta"]


def test_el_filtro_no_deja_la_busqueda_corta(rag_aislado):
    """El corte a n va DESPUES de filtrar. Si fuera antes, se cortaria a n y
    luego el filtro dejaria menos de los pedidos - el sobremuestreo no
    serviria para nada."""
    # 1 con ruido + 2 buenas. Pidiendo 2, tienen que salir las 2 buenas.
    _guardar([
        {"role": "system", "content": "Eres un asistente."},
        {"role": "user", "content": "cita python uno"},
        {"role": "assistant", "content": NEGATIVAS_REALES[0]},
    ])
    _guardar([
        {"role": "system", "content": "Eres un asistente."},
        {"role": "user", "content": "cita python dos"},
        {"role": "assistant", "content": "El jueves con el medico"},
    ])
    _guardar([
        {"role": "system", "content": "Eres un asistente."},
        {"role": "user", "content": "cita python tres"},
        {"role": "assistant", "content": "El viernes con el medico"},
    ])
    rag.indexar_conversaciones()

    resultados = rag.buscar("cita python", n=2)

    assert len(resultados) == 2
    assert all("no tengo información" not in r["respuesta"] for r in resultados)
