# F5.5 #8 - Voz en Telegram: tests del CANAL (el modulo suelto se prueba en
# tests/test_voz.py).
#
# La voz no es una tool, es un canal, y su mitad de ESCUCHAR es lo primero
# de todo el proyecto que manda un dato BIOMETRICO fuera de la maquina. El
# control central -y el que se valida por mutacion- es que con el
# interruptor apagado el audio NI SIQUIERA SE DESCARGA.
#
# Se reutilizan los objetos falsos de test_telegram_seguridad (mismo
# movimiento que ese fichero hace con _pdf_con_texto de test_documentos):
# nada de red, nada de Telegram, nada de LLM.
import asyncio
from types import SimpleNamespace

import pytest

import src.voz as voz
from src import config, telegram_bot
from tests.test_telegram_seguridad import _context, _update, _update_boton


@pytest.fixture(autouse=True)
def estado_limpio(monkeypatch):
    for diccionario in (
        telegram_bot._agentes, telegram_bot._cerrojos, telegram_bot._marcas,
        telegram_bot._rutas, telegram_bot._voz_activa,
    ):
        diccionario.clear()
    monkeypatch.setenv(config.TELEGRAM_PERMITIDOS_ENV, "111")
    monkeypatch.setenv(config.TELEGRAM_TOKEN_ENV, "123456:token-de-mentira")
    yield
    for diccionario in (
        telegram_bot._agentes, telegram_bot._cerrojos, telegram_bot._marcas,
        telegram_bot._rutas, telegram_bot._voz_activa,
    ):
        diccionario.clear()


def _update_voz(user_id=111, duracion=5, datos=b"OggS-audio", enviados=None, audios=None):
    """Update con una nota de voz. get_file()/download_as_bytearray() son
    async de mentira, igual que en los tests de documentos."""
    enviados = enviados if enviados is not None else []
    audios = audios if audios is not None else []

    async def reply_text(texto_respuesta, *a, **kw):
        enviados.append(texto_respuesta)

    async def reply_voice(audio, *a, **kw):
        audios.append(audio)

    async def download_as_bytearray():
        return bytearray(datos)

    async def get_file():
        return SimpleNamespace(download_as_bytearray=download_as_bytearray)

    nota = SimpleNamespace(duration=duracion, get_file=get_file)
    mensaje = SimpleNamespace(
        voice=nota, text=None, chat_id=user_id,
        reply_text=reply_text, reply_voice=reply_voice,
        enviados=enviados, audios=audios,
    )
    usuario = SimpleNamespace(id=user_id, first_name="Jordi", username="Jordi")
    return SimpleNamespace(effective_user=usuario, effective_message=mensaje)


# --- Escuchar: la puerta ----------------------------------------------------


def test_con_escuchar_apagado_la_nota_de_voz_NI_SE_DESCARGA(monkeypatch):
    """EL test de esta funcionalidad. No basta con comprobar que no
    transcribe: con el interruptor apagado el audio no debe salir de
    Telegram. Se revienta get_file() -si alguien lo llama, el test falla
    con ruido- y ademas se espia el transcriptor."""
    transcritas = []
    monkeypatch.setattr(voz, "transcribir", lambda *a, **kw: transcritas.append(a))

    update = _update_voz()

    async def get_file_prohibido():
        raise AssertionError("se ha descargado el audio con escuchar APAGADO")

    update.effective_message.voice.get_file = get_file_prohibido

    asyncio.run(telegram_bot.manejar_voz(update, _context()))

    assert transcritas == []
    dicho = " ".join(update.effective_message.enviados)
    assert "apagado" in dicho and "/voz" in dicho


def test_el_aviso_de_apagado_explica_por_que():
    """Un "no puedo" a secas invita a encenderlo sin leer nada. El motivo
    va donde se lee, no en la documentacion."""
    update = _update_voz()

    asyncio.run(telegram_bot.manejar_voz(update, _context()))

    dicho = " ".join(update.effective_message.enviados)
    assert "biométrico" in dicho and "Groq" in dicho


def test_con_escuchar_encendido_se_transcribe_y_se_enseña_lo_entendido(monkeypatch):
    """Caso de control. Y ademas: la transcripcion SIEMPRE se enseña, por
    dos motivos - Whisper se equivoca, y asi queda constancia visible de
    que ese audio salio de la maquina."""
    monkeypatch.setattr(voz, "transcribir", lambda datos, *a, **kw: "hola qué tal")
    monkeypatch.setattr(
        telegram_bot, "_agente_de",
        lambda uid: SimpleNamespace(preguntar=lambda t: f"respondo a {t}"),
    )
    telegram_bot._voz_activa[111] = {"escuchar"}
    update = _update_voz()

    asyncio.run(telegram_bot.manejar_voz(update, _context()))

    enviados = update.effective_message.enviados
    assert any("Te he entendido" in e and "hola qué tal" in e for e in enviados)
    assert "respondo a hola qué tal" in enviados


def test_una_nota_larguisima_se_rechaza_sin_descargarla():
    """La duracion viene en el propio update, asi que rechazar es gratis:
    ni cuota de Groq ni ancho de banda."""
    telegram_bot._voz_activa[111] = {"escuchar"}
    update = _update_voz(duracion=voz._MAX_SEGUNDOS + 60)

    async def get_file_prohibido():
        raise AssertionError("se ha descargado un audio que se iba a rechazar")

    update.effective_message.voice.get_file = get_file_prohibido

    asyncio.run(telegram_bot.manejar_voz(update, _context()))

    assert "corta" in " ".join(update.effective_message.enviados)


def test_una_transcripcion_gigante_no_llega_al_llm(monkeypatch):
    """El limite de entrada (AUD-03) vale igual para la voz: el historial
    se reenvia ENTERO en cada turno, y que el texto venga de un audio no lo
    hace mas barato."""
    largo = "x" * (telegram_bot._LIMITE_ENTRADA + 1)
    monkeypatch.setattr(voz, "transcribir", lambda *a, **kw: largo)
    preguntas = []
    monkeypatch.setattr(
        telegram_bot, "_agente_de",
        lambda uid: SimpleNamespace(preguntar=lambda t: preguntas.append(t)),
    )
    telegram_bot._voz_activa[111] = {"escuchar"}
    update = _update_voz()

    asyncio.run(telegram_bot.manejar_voz(update, _context()))

    assert preguntas == []
    assert "más corto" in " ".join(update.effective_message.enviados)


def test_si_groq_falla_el_usuario_se_entera(monkeypatch):
    def revienta(*a, **kw):
        raise voz.VozNoDisponible("No he podido transcribir esa nota de voz.")

    monkeypatch.setattr(voz, "transcribir", revienta)
    telegram_bot._voz_activa[111] = {"escuchar"}
    update = _update_voz()

    asyncio.run(telegram_bot.manejar_voz(update, _context()))

    assert "transcribir" in " ".join(update.effective_message.enviados)


# --- Hablar -----------------------------------------------------------------


def test_con_hablar_encendido_la_respuesta_llega_tambien_como_audio(monkeypatch):
    monkeypatch.setattr(voz, "sintetizar", lambda texto: b"OGG:" + texto.encode())
    monkeypatch.setattr(
        telegram_bot, "_agente_de",
        lambda uid: SimpleNamespace(preguntar=lambda t: "ahí va"),
    )
    telegram_bot._voz_activa[111] = {"hablar"}
    enviados, audios = [], []
    update = _update(enviados=enviados)

    async def reply_voice(audio, *a, **kw):
        audios.append(audio)

    update.effective_message.reply_voice = reply_voice

    asyncio.run(telegram_bot.manejar_mensaje(update, _context()))

    # El texto va SIEMPRE y va PRIMERO: es la respuesta completa y no
    # depende de que la sintesis funcione. El audio es el extra.
    assert enviados == ["ahí va"]
    assert audios == ["OGG:ahí va".encode()]


def test_con_hablar_apagado_no_se_sintetiza_nada(monkeypatch):
    """Caso de control: sin esto, "siempre habla" pasaria el test anterior."""
    sintetizados = []
    monkeypatch.setattr(voz, "sintetizar", lambda texto: sintetizados.append(texto))
    monkeypatch.setattr(
        telegram_bot, "_agente_de",
        lambda uid: SimpleNamespace(preguntar=lambda t: "ahí va"),
    )

    asyncio.run(telegram_bot.manejar_mensaje(_update(), _context()))

    assert sintetizados == []


def test_no_se_lee_en_voz_alta_un_mensaje_de_error(monkeypatch):
    """Sintetizar "se me ha cruzado un cable" no aporta nada y encima gasta
    CPU en un momento en el que algo ya ha ido mal."""
    sintetizados = []
    monkeypatch.setattr(voz, "sintetizar", lambda texto: sintetizados.append(texto))

    def revienta(_):
        raise RuntimeError("boom")

    monkeypatch.setattr(telegram_bot, "_agente_de", revienta)
    telegram_bot._voz_activa[111] = {"hablar"}
    enviados = []

    asyncio.run(telegram_bot.manejar_mensaje(_update(enviados=enviados), _context()))

    assert sintetizados == []
    assert "cable" in " ".join(enviados)


def test_si_falla_la_sintesis_el_usuario_conserva_su_texto(monkeypatch):
    """Lo accesorio no tumba lo principal, mismo criterio que el guardado
    de la conversacion."""
    def no_puedo(texto):
        raise voz.VozNoDisponible("falta la voz de Piper.")

    monkeypatch.setattr(voz, "sintetizar", no_puedo)
    monkeypatch.setattr(
        telegram_bot, "_agente_de",
        lambda uid: SimpleNamespace(preguntar=lambda t: "aquí tienes"),
    )
    telegram_bot._voz_activa[111] = {"hablar"}
    enviados = []
    update = _update(enviados=enviados)

    async def reply_voice(audio, *a, **kw):
        raise AssertionError("no deberia mandarse audio si la sintesis fallo")

    update.effective_message.reply_voice = reply_voice

    asyncio.run(telegram_bot.manejar_mensaje(update, _context()))

    assert "aquí tienes" in enviados
    assert any("Piper" in e for e in enviados)


# --- El menu /voz y su callback_data ---------------------------------------


def test_un_interruptor_de_voz_inventado_se_rechaza():
    """El callback_data viaja a Telegram y vuelve: dato NO confiable, igual
    que el modelo, el proveedor y las categorias de /tools."""
    editado = []

    asyncio.run(telegram_bot.manejar_boton(
        _update_boton("v:borralo-todo", editado=editado), _context()
    ))

    assert telegram_bot._voz_activa.get(111, set()) == set()
    assert "no existe" in " ".join(editado)


def test_conmutar_la_voz_no_crea_ningun_agente(monkeypatch):
    """La rama va ANTES de _agente_de() a proposito: crear un Agente lee la
    API key y fallaria con ClaveApiNoConfigurada al pulsar un boton que no
    necesita ningun LLM."""
    def prohibido(uid):
        raise AssertionError("no hace falta un Agente para tocar un interruptor de voz")

    monkeypatch.setattr(telegram_bot, "_agente_de", prohibido)

    asyncio.run(telegram_bot.manejar_boton(_update_boton("v:hablar"), _context()))

    assert telegram_bot._voz_activa[111] == {"hablar"}


def test_conmutar_dos_veces_lo_deja_apagado():
    asyncio.run(telegram_bot.manejar_boton(_update_boton("v:escuchar"), _context()))
    asyncio.run(telegram_bot.manejar_boton(_update_boton("v:escuchar"), _context()))

    assert telegram_bot._voz_activa[111] == set()


def test_ver_sitios_no_lo_caza_el_prefijo_de_voz(monkeypatch):
    """"ver-sitios" empieza por 'v' pero NO por 'v:'. Es la misma clase de
    choque de prefijos que ya se cuido entre "b:" y "bc:"."""
    monkeypatch.setattr(
        telegram_bot, "_agente_de", lambda uid: SimpleNamespace(categorias_activas=set())
    )
    editado = []

    asyncio.run(telegram_bot.manejar_boton(
        _update_boton(telegram_bot._VER_SITIOS, editado=editado), _context()
    ))

    assert telegram_bot._voz_activa.get(111, set()) == set()
    assert "no existe" not in " ".join(editado)


def test_limpiar_no_apaga_la_voz():
    """La preferencia de voz NO vive en el Agente justamente por esto:
    vaciar la conversacion y dejar de hablarle a alguien son cosas
    distintas, y /limpiar hace _agentes.pop()."""
    telegram_bot._voz_activa[111] = {"hablar", "escuchar"}

    asyncio.run(telegram_bot.cmd_limpiar(_update(), _context()))

    assert telegram_bot._voz_activa[111] == {"hablar", "escuchar"}


def test_el_menu_de_voz_avisa_de_que_el_audio_sale_de_la_maquina():
    """El aviso vive donde se toma la decision: encender "escuchar" con
    esto delante ES el consentimiento informado."""
    texto = telegram_bot._texto_voz(111)

    assert "biométrico" in texto
    assert "Groq" in texto
    assert "local" in texto  # y que la mitad de hablar NO sale


def test_el_menu_avisa_si_no_puede_hablar(monkeypatch):
    """Un interruptor que se enciende y luego falla en cada respuesta es
    peor que uno que dice lo que le falta."""
    monkeypatch.setattr(voz, "motivo_no_disponible", lambda: "falta ffmpeg en el PATH")

    assert "ffmpeg" in telegram_bot._texto_voz(111)


# --- Cableado en la Application real ---------------------------------------


def test_las_notas_de_voz_pasan_por_la_allowlist():
    """Mismo argumento que con los botones y los documentos (ADR-005): la
    puerta es un TypeHandler del grupo -1, asi que una via de entrada nueva
    no obliga a acordarse de protegerla."""
    aplicacion = telegram_bot.construir_aplicacion()
    grupo_puertas = min(aplicacion.handlers)

    grupos = [
        g for g, hs in aplicacion.handlers.items()
        if any(h.callback is telegram_bot.manejar_voz for h in hs)
    ]

    assert grupos and min(grupos) > grupo_puertas


def test_el_handler_de_voz_va_antes_del_generico_de_no_texto():
    """PTB entrega el update al PRIMER handler cuyo filtro encaje, asi que
    el orden de alta decide quien coge una nota de voz. Al reves, caerian
    en "de momento entiendo texto...", que es justo lo que pasaba antes."""
    aplicacion = telegram_bot.construir_aplicacion()
    callbacks = [h.callback for h in aplicacion.handlers[0]]

    assert callbacks.index(telegram_bot.manejar_voz) < callbacks.index(
        telegram_bot.manejar_no_texto
    )


def test_el_comando_voz_esta_registrado():
    aplicacion = telegram_bot.construir_aplicacion()
    callbacks = {h.callback for h in aplicacion.handlers[0]}

    assert telegram_bot.cmd_voz in callbacks
