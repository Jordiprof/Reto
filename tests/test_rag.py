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
    assert "medico" in resultados[0]["texto"].lower()


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
    assert "medico" in resultados[0]["texto"].lower()


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
    assert all("python" not in r["texto"].lower() for r in resultados)


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
    assert "medico" in resultados[0]["texto"].lower()


def test_indexar_conversacion_inexistente_no_revienta(rag_aislado):
    """El bot llama a esto en segundo plano tras responder. Si el fichero
    desapareciera, debe devolver 0, no tumbar el turno (mismo espiritu que
    RNF-02: el programa avisa y sigue vivo)."""
    fantasma = storage.CONVERSATIONS_DIR / "no-existe.json"

    assert rag.indexar_conversacion(fantasma) == 0
