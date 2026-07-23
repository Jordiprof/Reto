# Test de config.py (F5.0/T2, hallazgo AUD-06 de la auditoria del 23/07):
# antes, una API key ausente en .env lanzaba un KeyError sin capturar y el
# programa moria con un traceback crudo, incumpliendo RNF-02 ("ante un
# fallo de API, el programa avisa al usuario y sigue vivo").
import pytest

from src.config import (
    obtener_api_key, obtener_modelo_por_defecto,
    ClaveApiNoConfigurada, PROVEEDORES, MODELOS_ENV, MODELOS,
)


def test_clave_ausente_lanza_error_controlado(monkeypatch):
    """Si la variable de entorno de la API key no esta puesta, debe
    lanzarse ClaveApiNoConfigurada (con un mensaje claro) - NUNCA un
    KeyError crudo."""
    # Borramos la variable de Groq del entorno, este puesta o no de antes
    # (raising=False: no falla si ya no estaba).
    monkeypatch.delenv(PROVEEDORES["groq"], raising=False)

    with pytest.raises(ClaveApiNoConfigurada) as excinfo:
        obtener_api_key("groq")

    assert PROVEEDORES["groq"] in str(excinfo.value)


def test_clave_presente_se_devuelve_tal_cual(monkeypatch):
    """Caso de control: si la variable SI esta, se devuelve su valor."""
    monkeypatch.setenv(PROVEEDORES["groq"], "clave-de-prueba")

    assert obtener_api_key("groq") == "clave-de-prueba"


def test_modelo_por_defecto_lee_del_env(monkeypatch):
    """F5.0/T5: el modelo por defecto sale de la variable *_MODEL del .env."""
    monkeypatch.setenv(MODELOS_ENV["gemini"], "models/gemini-2.5-flash")

    assert obtener_modelo_por_defecto("gemini") == "models/gemini-2.5-flash"


def test_modelo_por_defecto_cae_al_catalogo_si_no_hay_env(monkeypatch):
    """Si la variable no esta puesta, cae al primero del catalogo MODELOS
    (un valor verificado) para que el programa arranque igual."""
    monkeypatch.delenv(MODELOS_ENV["gemini"], raising=False)

    assert obtener_modelo_por_defecto("gemini") == MODELOS["gemini"][0]


def test_modelo_por_defecto_env_vacio_cae_al_catalogo(monkeypatch):
    """Una variable puesta pero VACIA tambien cae al catalogo (el 'or'
    cubre el string vacio, no solo la ausencia)."""
    monkeypatch.setenv(MODELOS_ENV["groq"], "")

    assert obtener_modelo_por_defecto("groq") == MODELOS["groq"][0]
