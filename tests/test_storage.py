# F5.3: primeros tests de storage.py. Hasta hoy este fichero tenia CERO
# cobertura (hallazgo del comite del 24/07) - se guardaban conversaciones
# reales sin ninguna red de seguridad. Ahora que ademas se cifra, un fallo
# aqui no es "un test rojo": son conversaciones ilegibles para siempre.
#
# Todos los tests usan tmp_path (carpeta temporal que pytest crea y borra
# sola) y monkeypatch para redirigir las rutas del modulo: NUNCA tocan las
# conversaciones reales de Jordi ni su conversations.db.
import json

import pytest
from cryptography.fernet import Fernet

from src import storage
from src.storage import (
    ConversacionNoDescifrable,
    cargar_conversacion,
    cifrado_activo,
    guardar_conversacion,
    listar_conversaciones,
)

HISTORIAL = [
    {"role": "system", "content": "Eres un asistente."},
    {"role": "user", "content": "Acuérdate: el jueves tengo médico a las 10:30."},
    {"role": "assistant", "content": "Anotado, jueves 10:30 médico."},
]


@pytest.fixture
def entorno_aislado(tmp_path, monkeypatch):
    """Redirige las rutas de storage.py a una carpeta temporal."""
    monkeypatch.setattr(storage, "CONVERSATIONS_DIR", tmp_path / "conversations")
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "conversations.db")
    storage.CONVERSATIONS_DIR.mkdir()
    return tmp_path


@pytest.fixture
def con_clave(monkeypatch):
    """Configura una clave de cifrado valida en el entorno."""
    clave = Fernet.generate_key().decode()
    monkeypatch.setenv("CONVERSATIONS_KEY", clave)
    return clave


@pytest.fixture
def sin_clave(monkeypatch):
    """Garantiza que NO hay clave, aunque el .env real de Jordi la tenga."""
    monkeypatch.delenv("CONVERSATIONS_KEY", raising=False)


# --- Round-trip: lo que se guarda es lo que se lee --------------------


def test_round_trip_cifrado(entorno_aislado, con_clave):
    """La prueba que el comite pidio ANTES de tocar el formato: guardar
    cifrado y volver a leer debe devolver EXACTAMENTE el mismo historial.
    Si esto falla, las conversaciones son irrecuperables."""
    ruta = guardar_conversacion(HISTORIAL, "groq", "llama-3.3-70b-versatile")

    datos = cargar_conversacion(ruta)

    assert datos["historial"] == HISTORIAL
    assert datos["proveedor"] == "groq"


def test_round_trip_sin_cifrar(entorno_aislado, sin_clave):
    """Sin clave el agente sigue funcionando: guarda en claro y lee igual."""
    ruta = guardar_conversacion(HISTORIAL, "groq", "llama-3.3-70b-versatile")

    assert cargar_conversacion(ruta)["historial"] == HISTORIAL


# --- Que el cifrado cifra de verdad -----------------------------------


def test_el_contenido_no_aparece_en_claro_en_el_fichero(entorno_aislado, con_clave):
    """El test que de verdad demuestra que sirve de algo: el texto de los
    mensajes NO debe poder leerse abriendo el fichero."""
    ruta = guardar_conversacion(HISTORIAL, "groq", "llama-3.3-70b-versatile")

    crudo = ruta.read_text(encoding="utf-8")

    assert "médico" not in crudo
    assert "10:30" not in crudo
    assert "Eres un asistente" not in crudo


def test_los_metadatos_siguen_en_claro(entorno_aislado, con_clave):
    """Decision consciente, no descuido: fecha/proveedor/modelo se quedan
    legibles porque los necesita el indice de SQLite. Este test deja la
    fuga de metadatos por escrito, para que sea una decision visible y no
    una sorpresa."""
    ruta = guardar_conversacion(HISTORIAL, "groq", "llama-3.3-70b-versatile")

    datos_crudos = json.loads(ruta.read_text(encoding="utf-8"))

    assert datos_crudos["proveedor"] == "groq"
    assert datos_crudos["modelo"] == "llama-3.3-70b-versatile"
    assert datos_crudos["cifrado"] is True
    # El historial ya no es una lista: es un bloque de texto cifrado.
    assert isinstance(datos_crudos["historial"], str)


# --- Compatibilidad con lo ya guardado --------------------------------


def test_fichero_antiguo_sin_marcador_se_lee_en_claro(entorno_aislado, con_clave):
    """Las 9 conversaciones que Jordi ya tiene guardadas NO llevan el
    campo "cifrado". Deben seguir leyendose tal cual, sin intentar
    descifrarlas - aunque ahora SI haya clave configurada."""
    antiguo = entorno_aislado / "conversations" / "2026-07-20_10-00-00.json"
    antiguo.write_text(
        json.dumps({
            "fecha": "2026-07-20T10:00:00",
            "proveedor": "groq",
            "modelo": "llama-3.3-70b-versatile",
            "historial": HISTORIAL,
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    assert cargar_conversacion(antiguo)["historial"] == HISTORIAL


# --- Fallos: cada uno con su mensaje, no un error generico ------------


def test_sin_clave_al_leer_algo_cifrado_avisa_claro(entorno_aislado, con_clave, monkeypatch):
    """Escenario real que el comite marco como riesgo: reinstalas Windows,
    pierdes el .env, y te quedan los ficheros cifrados. El mensaje debe
    decir que falta la clave - no fallar de forma confusa."""
    ruta = guardar_conversacion(HISTORIAL, "groq", "llama-3.3-70b-versatile")
    monkeypatch.delenv("CONVERSATIONS_KEY")

    with pytest.raises(ConversacionNoDescifrable, match="CONVERSATIONS_KEY"):
        cargar_conversacion(ruta)


def test_clave_equivocada_avisa_claro(entorno_aislado, con_clave, monkeypatch):
    """Otra clave valida pero distinta (ej. regeneraste la clave sin
    re-cifrar: la limitacion de 'Fernet no rota claves' en accion)."""
    ruta = guardar_conversacion(HISTORIAL, "groq", "llama-3.3-70b-versatile")
    monkeypatch.setenv("CONVERSATIONS_KEY", Fernet.generate_key().decode())

    with pytest.raises(ConversacionNoDescifrable, match="no descifra"):
        cargar_conversacion(ruta)


def test_fichero_cifrado_manipulado_no_pasa_desapercibido(entorno_aislado, con_clave):
    """Fernet es cifrado AUTENTICADO: si alguien edita el bloque cifrado a
    mano, al descifrar salta un error en vez de devolver datos alterados
    en silencio."""
    ruta = guardar_conversacion(HISTORIAL, "groq", "llama-3.3-70b-versatile")
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["historial"] = datos["historial"][:-6] + "AAAAAA"
    ruta.write_text(json.dumps(datos), encoding="utf-8")

    with pytest.raises(ConversacionNoDescifrable):
        cargar_conversacion(ruta)


# --- Comportamiento que ya existia y ahora queda cubierto -------------


def test_no_guarda_conversaciones_vacias(entorno_aislado, con_clave):
    """F3.3: si solo esta el system prompt, no hubo conversacion. Evita
    llenar conversations/ de ficheros basura."""
    assert guardar_conversacion([{"role": "system", "content": "x"}], "groq", "m") is None


def test_cifrado_activo_refleja_la_configuracion(con_clave, monkeypatch):
    """main.py usara esto para avisar al arrancar si el cifrado esta
    apagado - la parte de "nunca en silencio"."""
    assert cifrado_activo() is True

    monkeypatch.delenv("CONVERSATIONS_KEY")
    assert cifrado_activo() is False


def test_listar_conversaciones_ordena_cronologicamente(entorno_aislado, sin_clave):
    """El nombre lleva la marca de tiempo, asi que ordenar por nombre es
    ordenar por fecha - sin depender de los metadatos del sistema de
    ficheros, que una copia o un backup pueden alterar."""
    for nombre in ["2026-07-22_09-00-00", "2026-07-20_10-00-00", "2026-07-21_23-59-59"]:
        (entorno_aislado / "conversations" / f"{nombre}.json").write_text("{}", encoding="utf-8")

    nombres = [ruta.stem for ruta in listar_conversaciones()]

    assert nombres == ["2026-07-20_10-00-00", "2026-07-21_23-59-59", "2026-07-22_09-00-00"]
