"""/condensar en Telegram: resumir el documento entero, completo o rapido.

Lo que se prueba aqui es la CONEXION con el canal -que sin documento no
gasta ni una llamada, que el fichero se manda de verdad, que el formato que
vuelve del boton se valida, que un fallo no tumba el bot-, no la logica del
condensado (esa vive en tests/test_resumen_largo.py, sin red).
"""
import asyncio
from types import SimpleNamespace

from src import telegram_bot


def _update(user_id=111, enviados=None, documentos=None, dato=None, editados=None):
    """Update falso. `dato` simula el callback_data que vuelve de un boton;
    `documentos` recoge lo que se manda con reply_document."""
    enviados = enviados if enviados is not None else []
    documentos = documentos if documentos is not None else []
    editados = editados if editados is not None else []
    teclados = []

    async def reply_text(texto, *a, **kw):
        enviados.append(texto)
        teclados.append(kw.get("reply_markup"))

    async def reply_document(fichero, *a, **kw):
        # Se LEE de verdad: si la ruta estuviera mal o el fichero cerrado,
        # aqui reventaria igual que reventaria en Telegram.
        documentos.append({
            "contenido": fichero.read(),
            "filename": kw.get("filename"),
            "caption": kw.get("caption"),
        })

    mensaje = SimpleNamespace(
        chat_id=user_id, reply_text=reply_text, reply_document=reply_document,
        enviados=enviados, documentos=documentos, teclados=teclados,
    )

    consulta = None
    if dato is not None:
        async def answer(*a, **kw):
            pass

        async def edit_message_text(texto, *a, **kw):
            editados.append(texto)

        consulta = SimpleNamespace(
            data=dato, answer=answer, edit_message_text=edit_message_text,
        )

    return SimpleNamespace(
        effective_message=mensaje,
        effective_user=SimpleNamespace(id=user_id, first_name="Jordi", username="jordi"),
        callback_query=consulta,
    )


def _context():
    return SimpleNamespace(args=[], bot=SimpleNamespace())


class _AgenteFalso:
    def __init__(self, documento=None):
        self.documento_pendiente = documento
        self.proveedor, self.api_key, self.modelo = "groq", "clave", "llama-3.3"
        # 03/08: la lectura cacheada de la pasada 1 (ver Agente.lectura_condensada).
        # Este doble se quedo desfasado del Agente real en cuanto se añadio el
        # atributo, y los dos tests de aqui empezaron a fallar con un
        # AttributeError disfrazado de "no he podido resumir" - que es
        # justamente por lo que el except de cmd_condensar es tan ancho.
        self.lectura_condensada: list[str] = []


def _con_documento(monkeypatch, tmp_path=None, respuesta="# Resumen\n\ncontenido"):
    """Deja el bot listo para condensar, sin red ni cuota."""
    from src import resumen_largo

    if tmp_path is not None:
        monkeypatch.setattr(resumen_largo, "RESUMENES_DIR", tmp_path / "resumenes")
    monkeypatch.setattr(
        telegram_bot, "_agente_de",
        lambda uid: _AgenteFalso(SimpleNamespace(nombre="Apuntes.pdf")),
    )
    monkeypatch.setattr("src.documentos.extraer_texto", lambda adj: "hola\n\nque tal")
    monkeypatch.setattr(
        "src.resumen_largo.preparar_resumidor",
        lambda *a: (lambda prompt: respuesta, 200, "gemini (models/gemini-2.5-flash)"),
    )


# --- La pregunta del formato ---------------------------------------------


def test_sin_documento_avisa_y_NO_gasta_ni_una_llamada(monkeypatch):
    """Cada bloque es una llamada al modelo y la cuota diaria de Groq son
    100.000 tokens: pedirlo sin documento no puede costar nada."""
    llamadas = []
    monkeypatch.setattr(telegram_bot, "_agente_de", lambda uid: _AgenteFalso(None))
    monkeypatch.setattr(
        "src.resumen_largo.preparar_resumidor",
        lambda *a: llamadas.append(a) or (None, 0, ""),
    )

    enviados = []
    asyncio.run(telegram_bot.cmd_condensar(_update(enviados=enviados), _context()))

    assert "documento" in " ".join(enviados).lower()
    assert llamadas == []


def test_con_documento_se_PREGUNTA_el_formato_antes_de_gastar(monkeypatch):
    """Los dos formatos cuestan lo MISMO -para resumir en diez lineas hay
    que haberse leido el documento entero igual-, asi que elegir mal
    significa pagarlo dos veces. Por eso se pregunta antes."""
    llamadas = []
    _con_documento(monkeypatch)
    monkeypatch.setattr(
        "src.resumen_largo.preparar_resumidor",
        lambda *a: llamadas.append(a) or (None, 0, ""),
    )

    update = _update()
    asyncio.run(telegram_bot.cmd_condensar(update, _context()))

    botones = update.effective_message.teclados[-1]
    assert botones is not None
    assert llamadas == [], "no se puede gastar nada antes de elegir"


# --- El formato vuelve del boton: dato NO confiable -----------------------


def test_un_formato_inventado_en_el_callback_se_RECHAZA(monkeypatch):
    """El formato viaja a Telegram dentro del callback_data y VUELVE, o sea
    que es un dato de fuera. Se valida contra FORMATOS igual que el modelo y
    el proveedor se validan contra el catalogo (F5.2+)."""
    llamadas = []
    _con_documento(monkeypatch)
    monkeypatch.setattr(
        "src.resumen_largo.preparar_resumidor",
        lambda *a: llamadas.append(a) or (None, 0, ""),
    )

    editados = []
    asyncio.run(telegram_bot.manejar_boton(
        _update(dato="condensar:formato_inventado", editados=editados), _context()
    ))

    assert llamadas == []
    assert "reconozco" in " ".join(editados).lower()


def test_cancelar_no_gasta_nada(monkeypatch):
    llamadas = []
    _con_documento(monkeypatch)
    monkeypatch.setattr(
        "src.resumen_largo.preparar_resumidor",
        lambda *a: llamadas.append(a) or (None, 0, ""),
    )

    editados = []
    asyncio.run(telegram_bot.manejar_boton(
        _update(dato="condensar:cancelar", editados=editados), _context()
    ))

    assert llamadas == []


# --- El trabajo, ya con formato elegido ----------------------------------


def test_el_COMPLETO_se_manda_como_FICHERO_no_como_mensajes(monkeypatch, tmp_path):
    """Un condensado completo son decenas de miles de caracteres: por el
    chat serian trece mensajes seguidos, que es inusable."""
    _con_documento(monkeypatch, tmp_path)

    update = _update()
    asyncio.run(telegram_bot._condensar_con_formato(update, "completo"))

    documentos = update.effective_message.documentos
    assert len(documentos) == 1
    assert documentos[0]["filename"].endswith(".md")
    assert b"Resumen" in documentos[0]["contenido"]
    assert not any("contenido" in e for e in update.effective_message.enviados)


def test_el_RAPIDO_va_al_chat_y_NO_deja_fichero(monkeypatch, tmp_path):
    """Son unas lineas que se leen y se olvidan. Guardarlas llenaria
    resumenes/ de ficheros que nadie va a abrir - mismo criterio que el
    descarte de /cerrar."""
    destino = tmp_path / "resumenes"
    _con_documento(monkeypatch, tmp_path, respuesta="En dos lineas: va de servicios web.")

    update = _update()
    asyncio.run(telegram_bot._condensar_con_formato(update, "rapido"))

    assert update.effective_message.documentos == []
    assert any("servicios web" in e for e in update.effective_message.enviados)
    assert not destino.exists(), "el rapido no debe escribir en disco"


def test_se_avisa_de_QUIEN_resume_antes_de_empezar(monkeypatch, tmp_path):
    """Tarda minutos: sin aviso parece colgado. Y saber que resume Gemini
    y no el proveedor elegido evita la confusion del 01/08, cuando Groq
    respondia por Ollama sin decirlo."""
    _con_documento(monkeypatch, tmp_path)

    update = _update()
    asyncio.run(telegram_bot._condensar_con_formato(update, "completo"))

    assert any("gemini" in e for e in update.effective_message.enviados)


def test_un_fallo_al_resumir_no_tumba_el_bot(monkeypatch):
    """RNF-02: ante un fallo, el bot avisa y sigue vivo."""
    monkeypatch.setattr(
        telegram_bot, "_agente_de",
        lambda uid: _AgenteFalso(SimpleNamespace(nombre="Apuntes.pdf")),
    )

    def revienta(adj):
        raise RuntimeError("pdf corrupto")

    monkeypatch.setattr("src.documentos.extraer_texto", revienta)

    update = _update()
    asyncio.run(telegram_bot._condensar_con_formato(update, "completo"))

    assert any("⚠️" in e for e in update.effective_message.enviados)


def test_condensar_esta_en_el_menu_Y_su_boton_ejecuta_el_comando():
    """Los botones de /comandos EJECUTAN el comando real (rediseño del
    31/07): si estuviera en el catalogo pero no en el mapa de acciones,
    pulsarlo daria KeyError."""
    nombres = [n for n, _, _ in telegram_bot._CATALOGO]

    assert "condensar" in nombres
    assert telegram_bot._ACCIONES_DIRECTAS["condensar"] is telegram_bot.cmd_condensar
