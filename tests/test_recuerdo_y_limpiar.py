"""Lo que Jordi encontró probando el bot el 04/08: el ruido de `/recuerdo` y
la mentira de `/limpiar`.

Las dos son de la misma familia y por eso están juntas: **el bot decía algo
distinto de lo que hacía**. `/limpiar` prometía borrar y no borraba; y en cada
canal lo prometía con palabras distintas.
"""

import inspect

from src.config import MODELOS, MODELOS_DE_RESERVA
from src.rag import _es_negativa

# --- El ruido de /recuerdo (04/08) ---------------------------------------


def test_se_filtra_el_bot_diciendo_que_es_una_maquina():
    """`/recuerdo cual es tu comida favorita` devolvía DOS turnos con esta
    respuesta. No es un "no lo sé" -por eso el filtro del 02/08 no la
    cazaba- pero como recuerdo vale exactamente lo mismo: nada."""
    assert _es_negativa(
        "No tengo una comida favorita – como IA no como, así que no "
        "desarrollo gustos culinarios."
    )
    assert _es_negativa("No tengo edad, soy una inteligencia artificial.")
    assert _es_negativa("Como IA no tengo cuerpo ni sensaciones.")


def test_NO_se_filtra_una_respuesta_util_que_empieza_parecido():
    """La heurística tiene que seguir fallando hacia el lado seguro: un
    falso positivo esconde un recuerdo bueno, que es mucho peor que dejar
    pasar ruido."""
    assert not _es_negativa("No tengo dudas: tu comida favorita es el conejo.")
    assert not _es_negativa("Tu comida favorita es el conejo.")
    assert not _es_negativa(
        "JIM, tu comida favorita es la lasaña. Sobre el deporte favorito "
        "no tengo información."
    ), "la negativa está en la posición ~155, es un matiz, no la respuesta"


def test_las_respuestas_repetidas_se_deduplican():
    """Jordi vio dos entradas -"cual es tu comida favorita?" y "cual SERA tu
    comida favorita?"- con la respuesta palabra por palabra idéntica. Como
    recuerdos son dos; como información, una."""
    from src import rag

    cuerpo = inspect.getsource(rag.buscar)
    assert "vistas" in cuerpo, "se ha perdido la dedup por respuesta"
    assert "clave in vistas" in cuerpo


def test_la_dedup_NO_se_come_los_turnos_sin_respuesta():
    """Todos tendrían la misma clave vacía y se quedaría solo uno."""
    from src import rag

    cuerpo = inspect.getsource(rag.buscar)
    assert "if respuesta:" in cuerpo, (
        "la dedup debe saltarse los turnos que no tienen respuesta"
    )


# --- /limpiar decía una cosa y hacía otra (04/08) -------------------------


def test_la_CLI_ya_no_dice_que_BORRA():
    """El mensaje era "Conversación borrada. Empezamos de cero." y era
    MENTIRA: no borra nada, lo guardado sigue en conversations/ y en el RAG.

    Lo pilló Jordi poniendo la terminal y Telegram lado a lado: la misma
    operación se describía de dos maneras distintas."""
    from src import main

    # Se quitan las lineas de comentario antes de mirar: el comentario del
    # arreglo CITA el mensaje viejo para explicar por que se cambio, y eso
    # es documentacion, no el texto que ve JIM.
    codigo = "\n".join(
        linea for linea in inspect.getsource(main).splitlines()
        if not linea.strip().startswith("#")
    )
    assert "Conversación borrada" not in codigo


def test_los_DOS_canales_dicen_lo_mismo_de_limpiar():
    """Un estado compartido no puede describirse de dos maneras. Misma
    familia que la divergencia de /salir del 01/08."""
    from src import main, telegram_bot

    frase = "Lo de antes NO se borra"
    assert frase in inspect.getsource(main)
    assert frase in inspect.getsource(telegram_bot.cmd_limpiar)


def test_limpiar_dice_PARA_QUE_sirve_y_cual_es_el_que_borra():
    """La pregunta de Jordi fue literalmente "¿para qué sirve /limpiar?".
    Sirve para que cada mensaje vuelva a ser barato -el historial se reenvía
    entero en cada turno (AUD-03)-, y el que borra de verdad es /borrar."""
    from src import telegram_bot

    texto = inspect.getsource(telegram_bot.cmd_limpiar)
    assert "barato" in texto
    assert "/borrar" in texto


# --- El catálogo de modelos, verificado en vivo el 04/08 -----------------


def test_qwen35_cloud_YA_NO_esta_en_el_menu_de_ollama():
    """Llevaba en el menú desde el 23/07 y NUNCA funcionó: devuelve HTTP 403
    "this model requires a subscription". Estaba anotado tres líneas más
    arriba en la lista de descartados por 403 y aun así se ofrecía: la nota
    decía una cosa y el catálogo hacía otra."""
    assert "qwen3.5:cloud" not in MODELOS["ollama"]


def test_la_cadena_de_reserva_de_groq_es_la_que_decidio_Jordi():
    """llama-3.3 se queda de titular; gpt-oss-120b y qwen3.6-27b entran por
    ese orden (decisión del 04/08). Los tres verificados en vivo."""
    assert MODELOS_DE_RESERVA["groq"] == ["openai/gpt-oss-120b", "qwen/qwen3.6-27b"]
    assert MODELOS["groq"][0] == "llama-3.3-70b-versatile"


def test_las_reservas_estan_TAMBIEN_en_el_catalogo_del_menu():
    """Invariante: si el router puede degradar a un modelo, JIM tiene que
    poder elegirlo a mano con /modelo. Si no, hay modelos que el programa
    usa y él no puede probar."""
    for modelo in MODELOS_DE_RESERVA["groq"]:
        assert modelo in MODELOS["groq"], modelo


def test_ningun_modelo_del_menu_es_un_clasificador_ni_de_voz():
    """De los 14 que ofrece Groq solo 7 sirven para chatear. Los `orpheus-*`
    son síntesis de voz, los `whisper-*` transcripción (esos sí se usan,
    pero desde voz.py y a dedo), y `prompt-guard-*` / `gpt-oss-safeguard-*`
    son CLASIFICADORES: devuelven una etiqueta de riesgo, no conversación.
    Ofrecerlos en el menú sería ofrecer modelos que no pueden responder."""
    prohibidos = ("orpheus", "whisper", "prompt-guard", "safeguard")
    for proveedor, modelos in MODELOS.items():
        for modelo in modelos:
            for palabra in prohibidos:
                assert palabra not in modelo.lower(), f"{proveedor}: {modelo}"
