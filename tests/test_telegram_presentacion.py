"""Los defectos de presentación que Jordi encontró probando el bot el 04/08.

Ninguno los cazó la suite: son cosas que solo se ven MIRANDO el chat. Dos de
los cinco que reportó resultaron NO ser bugs al ir al código, y eso también
está aquí escrito para que no se vuelva a investigar.
"""

import re

from src.telegram_bot import _sin_markdown, _trocear

# --- Los asteriscos del modelo (04/08) -----------------------------------


def test_la_negrita_del_modelo_no_llega_con_asteriscos():
    """"veo muchos símbolos * ** no me gusta". Los turnos normales se mandan
    SIN parse_mode, así que el Markdown del modelo llegaba en crudo."""
    limpio = _sin_markdown("Tu comida favorita es el **conejo** y punto.")

    assert limpio == "Tu comida favorita es el conejo y punto."
    assert "*" not in limpio


def test_las_viñetas_se_vuelven_puntos_de_verdad():
    """No se borran: se cambian por «•», que es lo que el asterisco quería
    decir. Y la sangría se conserva para que una lista anidada siga
    leyéndose como una lista."""
    limpio = _sin_markdown("* Recordatorios\n* Cálculos\n  - anidado\n")

    assert "• Recordatorios" in limpio
    assert "• Cálculos" in limpio
    assert "  • anidado" in limpio


def test_los_titulos_markdown_se_quitan():
    assert _sin_markdown("## Resumen\ntexto").startswith("Resumen")


def test_un_asterisco_suelto_NO_rompe_nada():
    """LA RAZÓN DE SER de limpiar en vez de encender parse_mode: el texto lo
    escribe el MODELO y puede traer Markdown roto. Con parse_mode, Telegram
    ante eso rechaza el mensaje ENTERO -pasó el 30/07 con un `_` sin escapar
    en el nombre de un dominio-, o sea que encender el formato convertiría
    un defecto cosmético en una respuesta perdida.

    Limpiar es determinista: en el peor caso queda un asterisco, que es
    exactamente lo que ya pasaba antes."""
    for roto in ["2 * 3 = 6", "un *asterisco suelto", "**sin cerrar", "a ** b"]:
        assert isinstance(_sin_markdown(roto), str), roto

    # Una multiplicación NO es cursiva: no puede desaparecer el operador.
    assert "*" in _sin_markdown("2 * 3 = 6")


def test_no_se_come_los_guiones_bajos_de_los_comandos():
    """`/limpiar` y los nombres de conversación llevan guiones bajos, y no
    son cursiva de Markdown aunque lo parezcan."""
    limpio = _sin_markdown("Guardada como pruebas_telegram2, usa /tools")

    assert "pruebas_telegram2" in limpio
    assert "/tools" in limpio


def test_limpiar_y_trocear_se_llevan_bien():
    """El troceo a 4096 sigue funcionando sobre el texto ya limpio: quitar
    los asteriscos acorta, nunca alarga."""
    largo = "**negrita** y texto. " * 500
    trozos = _trocear(_sin_markdown(largo))

    assert all(len(t) <= 4096 for t in trozos)
    assert not any("**" in t for t in trozos)


# --- Lo que Jordi reportó y NO era un bug --------------------------------


def test_start_es_BREVE_y_enumera_las_herramientas():
    """Jordi: "el mensaje de bienvenida sobra, debería decirme las
    herramientas y punto, cosa breve y muy amistosa".

    OJO al diagnóstico, que es la parte interesante: el tocho que vio NO era
    /start -eso ya eran 6 líneas- sino la respuesta IMPROVISADA del modelo a
    una nota de voz preguntándole qué sabía hacer. Y ahí se inventó
    capacidades que NO TIENE ("recordatorios y tareas: anoto lo que me
    cuentes y luego te lo recuerdo"), que es un problema bastante peor que
    la longitud. Eso se arregló en el SYSTEM_PROMPT, no aquí.

    Este test cubre lo que sí pidió de /start: corto y con la lista."""
    import inspect

    from src import telegram_bot

    cuerpo = inspect.getsource(telegram_bot.cmd_start)
    # Solo los literales del cuerpo, sin el docstring (que es comentario).
    sin_doc = cuerpo.split('"""', 2)[-1]
    texto = "".join(re.findall(r'"([^"]*)"', sin_doc))

    assert len(texto) < 450, f"/start se ha vuelto largo: {len(texto)} caracteres"
    for herramienta in ["acuerdo", "Calculo", "tiempo", "PDF", "NASA", "web", "voz"]:
        assert herramienta in texto, f"falta {herramienta} en la bienvenida"


def test_el_historial_enseña_la_HORA_y_no_solo_el_dia():
    """Reportó "con /cerrar lo guarda dos veces y a la misma hora". NO las
    guardaba dos veces -verificado: 11 ficheros, cero duplicados-: la lista
    cortaba la fecha a `[:10]`, así que dos charlas del mismo día salían con
    la etiqueta idéntica salvo el nombre y PARECÍAN la misma. Para el caso,
    igual de malo. La otra lista del fichero ya usaba `[:16]`."""
    import inspect

    from src import telegram_bot

    cuerpo = inspect.getsource(telegram_bot.cmd_historial)
    assert '[:10]' not in cuerpo, "vuelve a cortar la fecha sin la hora"
    assert '[:16]' in cuerpo


# --- El estado de espera y los adjuntos (07/08) --------------------------


def _update_texto(uid=111, texto="hola"):
    from types import SimpleNamespace

    async def reply_text(t, *a, **kw):
        return None

    return SimpleNamespace(
        effective_user=SimpleNamespace(id=uid),
        effective_message=SimpleNamespace(text=texto, voice=None, reply_text=reply_text),
    )


def _update_adjunto(uid=111):
    from types import SimpleNamespace

    async def reply_text(t, *a, **kw):
        return None

    return SimpleNamespace(
        effective_user=SimpleNamespace(id=uid),
        effective_message=SimpleNamespace(
            text=None, voice=None, document=SimpleNamespace(file_name="x.docx"),
            reply_text=reply_text,
        ),
    )


def _update_voz(uid=111):
    from types import SimpleNamespace

    async def reply_text(t, *a, **kw):
        return None

    return SimpleNamespace(
        effective_user=SimpleNamespace(id=uid),
        effective_message=SimpleNamespace(
            text=None, voice=SimpleNamespace(duration=3), reply_text=reply_text,
        ),
    )


def test_un_ADJUNTO_cancela_el_dime_que_busco():
    """BUG REAL de Jordi (07/08): tenía un «dime qué busco» pendiente de
    /recuerdo, mandó un documento, y la pregunta siguiente -"de qué trata el
    documento?"- se la comió /recuerdo, devolviéndole una búsqueda en la
    memoria en vez de leer el fichero.

    La puerta exigía `mensaje.text` y un adjunto no lo tiene, así que salía
    sin limpiar; y manejar_documento tampoco pasa por `_turno`, que es donde
    el estado se consume. Mismo agujero que la nota de voz del 01/08, por la
    puerta de al lado."""
    import asyncio

    from src import telegram_bot

    telegram_bot._esperando_texto[111] = "recuerdo"
    asyncio.run(telegram_bot.puerta_soltar_espera(_update_adjunto(), None))

    assert 111 not in telegram_bot._esperando_texto


def test_un_COMANDO_sigue_cancelando():
    """Caso de control: lo del 01/08 no se puede haber roto al ampliar."""
    import asyncio

    from src import telegram_bot

    telegram_bot._esperando_texto[111] = "guardar"
    asyncio.run(telegram_bot.puerta_soltar_espera(_update_texto(texto="/ayuda"), None))

    assert 111 not in telegram_bot._esperando_texto


def test_un_TEXTO_normal_NO_cancela():
    """El texto normal es justo lo que se está esperando: si lo cancelara,
    /recuerdo y /guardar por botón no funcionarían nunca."""
    import asyncio

    from src import telegram_bot

    telegram_bot._esperando_texto[111] = "recuerdo"
    asyncio.run(telegram_bot.puerta_soltar_espera(_update_texto(texto="tarta"), None))

    assert telegram_bot._esperando_texto.get(111) == "recuerdo"
    telegram_bot._esperando_texto.clear()


def test_una_NOTA_DE_VOZ_no_la_cancela_aqui():
    """A propósito: la voz SÍ acaba en `_turno`, que consume el estado por
    el camino normal (arreglo del 01/08). Cancelarla aquí además rompería
    poder contestar por voz a un «dime qué busco»."""
    import asyncio

    from src import telegram_bot

    telegram_bot._esperando_texto[111] = "recuerdo"
    asyncio.run(telegram_bot.puerta_soltar_espera(_update_voz(), None))

    assert telegram_bot._esperando_texto.get(111) == "recuerdo"
    telegram_bot._esperando_texto.clear()
