# Test de config.py (F5.0/T2, hallazgo AUD-06 de la auditoria del 23/07):
# antes, una API key ausente en .env lanzaba un KeyError sin capturar y el
# programa moria con un traceback crudo, incumpliendo RNF-02 ("ante un
# fallo de API, el programa avisa al usuario y sigue vivo").
import pytest

from src.config import obtener_api_key, ClaveApiNoConfigurada, PROVEEDORES


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
