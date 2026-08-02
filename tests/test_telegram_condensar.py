"""/condensar en Telegram: resumir el documento entero y mandarlo en .md.

Lo que se prueba aqui es la CONEXION con el canal -que sin documento no
gasta ni una llamada, que el fichero se manda de verdad, que un fallo no
tumba el bot-, no la logica del condensado (esa vive en
tests/test_resumen_largo.py, sin red).
"""
import asyncio
from types import SimpleNamespace

from src import telegram_bot


def _update(user_id=111, enviados=None, documentos=None):
    """Update falso con reply_document, que es lo que /condensar necesita
    y los updates falsos de los otros tests no tienen."""
    enviados = enviados if enviados is not None else []
    documentos = documentos if documentos is not None else []

    async def reply_text(texto, *a, **kw):
        enviados.append(texto)

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
        enviados=enviados, documentos=documentos,
    )
    return SimpleNamespace(
        effective_message=mensaje,
        effective_user=SimpleNamespace(id=user_id, first_name="Jordi", username="jordi"),
    )


def _context():
    return SimpleNamespace(args=[], bot=SimpleNamespace())


class _AgenteFalso:
    def __init__(self, documento=None):
        self.documento_pendiente = documento
        self.proveedor, self.api_key, self.modelo = "groq", "clave", "llama-3.3"


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


def test_el_md_se_manda_como_FICHERO_no_como_mensajes(monkeypatch, tmp_path):
    """Un condensado son decenas de miles de caracteres: por el chat serian
    trece mensajes seguidos, que es inusable."""
    from src import resumen_largo

    monkeypatch.setattr(resumen_largo, "RESUMENES_DIR", tmp_path / "resumenes")
    monkeypatch.setattr(
        telegram_bot, "_agente_de",
        lambda uid: _AgenteFalso(SimpleNamespace(nombre="Apuntes.pdf")),
    )
    monkeypatch.setattr("src.documentos.extraer_texto", lambda adj: "hola\n\nque tal")
    monkeypatch.setattr(
        "src.resumen_largo.preparar_resumidor",
        lambda *a: (lambda prompt: "# Resumen\n\ncontenido", 200, "gemini (2.5)"),
    )

    documentos, enviados = [], []
    asyncio.run(telegram_bot.cmd_condensar(
        _update(enviados=enviados, documentos=documentos), _context()
    ))

    assert len(documentos) == 1
    assert documentos[0]["filename"].endswith(".md")
    assert b"Resumen" in documentos[0]["contenido"]
    # El contenido del .md NO se escupe ademas por el chat.
    assert not any("contenido" in e for e in enviados)


def test_se_avisa_de_QUIEN_resume_antes_de_empezar(monkeypatch, tmp_path):
    """Tarda minutos: sin aviso parece colgado. Y saber que resume Gemini
    y no el proveedor elegido evita la confusion del 01/08, cuando Groq
    respondia por Ollama sin decirlo."""
    from src import resumen_largo

    monkeypatch.setattr(resumen_largo, "RESUMENES_DIR", tmp_path / "resumenes")
    monkeypatch.setattr(
        telegram_bot, "_agente_de",
        lambda uid: _AgenteFalso(SimpleNamespace(nombre="Apuntes.pdf")),
    )
    monkeypatch.setattr("src.documentos.extraer_texto", lambda adj: "hola")
    monkeypatch.setattr(
        "src.resumen_largo.preparar_resumidor",
        lambda *a: (lambda p: "# X", 200, "gemini (models/gemini-2.5-flash)"),
    )

    enviados = []
    asyncio.run(telegram_bot.cmd_condensar(_update(enviados=enviados), _context()))

    assert any("gemini" in e for e in enviados)


def test_un_fallo_al_resumir_no_tumba_el_bot(monkeypatch):
    """RNF-02: ante un fallo, el bot avisa y sigue vivo."""
    monkeypatch.setattr(
        telegram_bot, "_agente_de",
        lambda uid: _AgenteFalso(SimpleNamespace(nombre="Apuntes.pdf")),
    )

    def revienta(adj):
        raise RuntimeError("pdf corrupto")

    monkeypatch.setattr("src.documentos.extraer_texto", revienta)

    enviados = []
    asyncio.run(telegram_bot.cmd_condensar(_update(enviados=enviados), _context()))

    assert any("⚠️" in e for e in enviados)


def test_condensar_esta_en_el_menu_Y_su_boton_ejecuta_el_comando():
    """Los botones de /comandos EJECUTAN el comando real (rediseño del
    31/07): si estuviera en el catalogo pero no en el mapa de acciones,
    pulsarlo daria KeyError."""
    nombres = [n for n, _, _ in telegram_bot._CATALOGO]

    assert "condensar" in nombres
    assert telegram_bot._ACCIONES_DIRECTAS["condensar"] is telegram_bot.cmd_condensar
