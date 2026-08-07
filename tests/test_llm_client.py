# pytest descubre automaticamente cualquier funcion que empiece por
# "test_" en un fichero que empiece por "test_" - no hace falta
# registrarlas en ningun sitio.
from src.llm_client import traducir_historial_gemini


def test_extrae_el_system_prompt():
    """El mensaje con role "system" no debe ir en contents: se extrae
    aparte, en system_instruction (asi lo pide la API de Gemini)."""
    historial = [
        {"role": "system", "content": "Eres un tutor."},
        {"role": "user", "content": "Hola"},
    ]

    contents, system_instruction = traducir_historial_gemini(historial)

    assert system_instruction == "Eres un tutor."
    # El mensaje de system NO debe quedar tambien en contents (se
    # extrae, no se duplica).
    assert len(contents) == 1


def test_traduce_roles_y_formato():
    """assistant -> model, y "content": str -> "parts": [{"text": str}]
    (los dos nombres que cambian en el dialecto de Gemini)."""
    historial = [
        {"role": "system", "content": "Eres un tutor."},
        {"role": "user", "content": "Hola"},
        {"role": "assistant", "content": "Hola, que tal"},
    ]

    contents, _ = traducir_historial_gemini(historial)

    # contents[0] es el primer mensaje que NO es system, es decir "Hola".
    assert contents[0] == {"role": "user", "parts": [{"text": "Hola"}]}
    assert contents[1] == {"role": "model", "parts": [{"text": "Hola, que tal"}]}


def test_no_muta_el_historial_original():
    """La funcion debe ser PURA: el historial que le pasamos tiene que
    seguir intacto despues de llamarla (formato canonico, no el de
    Gemini) - si no, se "contaminaria" para Groq/Ollama o para el
    guardado en JSON (ver diseño en el diario de decisiones, F3.1)."""
    historial = [
        {"role": "system", "content": "Eres un tutor."},
        {"role": "user", "content": "Hola"},
    ]
    copia_de_referencia = [dict(m) for m in historial]  # copia independiente para comparar

    traducir_historial_gemini(historial)

    assert historial == copia_de_referencia


def test_un_modelo_retirado_se_explica_como_tal():
    """01/08: Jordi eligio `minimax-m2.5` en el menu y todos sus mensajes
    cayeron al fallback con "ErrorPeticionInvalida", que no dice nada. El
    motivo real -HTTP 410, "was retired at 2026-07-31"- estaba enterrado en
    el detalle. Un catalogo de modelos envejece SIEMPRE, asi que lo que hay
    que arreglar no es este modelo (que tambien) sino que el proximo que
    retiren lo diga solo."""
    import httpx

    from src.llm_client import _ProveedorOllama
    from src.llm_errors import ErrorPeticionInvalida

    class _Retirado(Exception):
        status_code = 410

        def __str__(self):
            return "modelo-x was retired at 2026-07-31"

    class _ClienteQueDaGone:
        def chat(self, **kwargs):
            raise _Retirado()

    proveedor = _ProveedorOllama(api_key="x", modelo="modelo-x")
    estado = {"client": _ClienteQueDaGone(), "mensajes": [], "tools": None}

    try:
        proveedor._llamar(estado)
    except ErrorPeticionInvalida as error:
        assert "retirado" in error.detalle
        assert "modelo-x" in error.detalle
        assert "/modelo" in error.detalle, "hay que decir COMO arreglarlo"
    else:
        raise AssertionError("un 410 debe lanzar ErrorPeticionInvalida")

    assert httpx  # el import se usa para que ruff no lo marque


def test_los_modelos_del_catalogo_no_se_repiten():
    """Invariante barato: un duplicado en el menu es un despiste que se
    cuela facil al editar la lista a mano."""
    from src.config import MODELOS

    for proveedor, modelos in MODELOS.items():
        assert len(modelos) == len(set(modelos)), proveedor
        assert "minimax-m2.5" not in modelos, "retirado el 31/07/2026"
