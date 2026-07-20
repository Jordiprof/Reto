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
