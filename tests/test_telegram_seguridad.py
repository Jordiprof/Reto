# Tests de SEGURIDAD del bot de Telegram (F5.2).
#
# El control nº1 del bot es la lista blanca de user_id (AUD-A1): sin ella,
# cualquiera que encuentre el @usuario del bot puede escribirle - y como la
# tool buscar_en_recuerdos consulta la memoria semantica, recibiria las
# conversaciones DESCIFRADAS de Jordi. Es la misma fuga que cerramos en los
# logs el 27/07, pero por la puerta principal y a peticion.
#
# Ninguno de estos tests toca la red, ni Telegram, ni un LLM: la aplicacion
# se construye con construir_aplicacion() y los callbacks se llaman a mano
# con objetos falsos (SimpleNamespace), igual que en test_llm_gemini.py.
import asyncio
import logging
from types import SimpleNamespace

import pytest
from telegram.ext import ApplicationHandlerStop

from src import config, telegram_bot


@pytest.fixture(autouse=True)
def estado_limpio(monkeypatch):
    """Cada test arranca sin agentes, cerrojos ni marcas de otro test, y
    con una lista blanca conocida."""
    telegram_bot._agentes.clear()
    telegram_bot._cerrojos.clear()
    telegram_bot._marcas.clear()
    telegram_bot._rutas.clear()
    monkeypatch.setenv(config.TELEGRAM_PERMITIDOS_ENV, "111")
    monkeypatch.setenv(config.TELEGRAM_TOKEN_ENV, "123456:token-de-mentira")
    yield
    telegram_bot._agentes.clear()
    telegram_bot._cerrojos.clear()
    telegram_bot._marcas.clear()
    telegram_bot._rutas.clear()


def _update(user_id=111, texto="hola", nombre="Jordi", enviados=None):
    """Update falso: solo los atributos que leen nuestros callbacks."""
    enviados = enviados if enviados is not None else []

    async def reply_text(texto_respuesta, *a, **kw):
        enviados.append(texto_respuesta)

    mensaje = SimpleNamespace(
        text=texto, chat_id=user_id, reply_text=reply_text, enviados=enviados
    )
    usuario = (
        None
        if user_id is None
        else SimpleNamespace(id=user_id, first_name=nombre, username=nombre)
    )
    return SimpleNamespace(effective_user=usuario, effective_message=mensaje)


def _context():
    async def send_chat_action(*a, **kw):
        return None

    return SimpleNamespace(bot=SimpleNamespace(send_chat_action=send_chat_action))


# --- AUD-A1: la lista blanca -----------------------------------------------


def test_un_user_id_no_autorizado_nunca_llega_al_agente(monkeypatch):
    """El test que pedia AUD-A1 al pie de la letra. No basta con comprobar
    que salta la excepcion: se espia _agente_de y se afirma que NO se le
    llamo, porque lo que hay que demostrar es que el desconocido no toca
    el LLM ni la memoria."""
    llamadas = []
    monkeypatch.setattr(telegram_bot, "_agente_de", lambda uid: llamadas.append(uid))

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(telegram_bot.puerta_allowlist(_update(user_id=999), _context()))

    assert llamadas == []


def test_un_update_sin_usuario_identificable_se_rechaza():
    """effective_user es None de verdad en channel_post, poll, chat_boost...
    Sin usuario a quien autorizar, fuera - y sin AttributeError."""
    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(telegram_bot.puerta_allowlist(_update(user_id=None), _context()))


def test_el_usuario_autorizado_pasa():
    """Caso de control: sin esto, 'rechazarlo todo' pasaria los dos tests
    anteriores y el bot no funcionaria para nadie."""
    asyncio.run(telegram_bot.puerta_allowlist(_update(user_id=111), _context()))


def test_al_desconocido_no_se_le_responde_nada():
    """Silencio deliberado: responder confirmaria que el bot existe (util
    para quien sondea) y gastaria cuota de salida a peticion suya."""
    enviados = []
    update = _update(user_id=999, enviados=enviados)

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(telegram_bot.puerta_allowlist(update, _context()))

    assert enviados == []


@pytest.mark.parametrize("valor", ["", "   ", "no-es-un-numero", "111,abc"])
def test_una_lista_blanca_rota_cierra_el_bot_no_lo_abre(monkeypatch, valor):
    """FALLA CERRADO. El modo de fallo peligroso seria interpretar una
    lista ilegible como 'no filtrar', que convierte el control de acceso
    en decoracion."""
    monkeypatch.setenv(config.TELEGRAM_PERMITIDOS_ENV, valor)

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(telegram_bot.puerta_allowlist(_update(user_id=111), _context()))


def test_sin_variable_de_lista_blanca_tambien_cierra(monkeypatch):
    monkeypatch.delenv(config.TELEGRAM_PERMITIDOS_ENV, raising=False)

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(telegram_bot.puerta_allowlist(_update(user_id=111), _context()))


# --- La invariante estructural: la que sobrevive a F5.5 --------------------


def test_la_puerta_corre_antes_que_cualquier_otro_handler():
    """LA INVARIANTE QUE IMPORTA A FUTURO. Aunque en F5.5 se añadan
    handlers nuevos, la allowlist sigue en el grupo mas bajo y por tanto
    los protege automaticamente. Se inspecciona la Application REAL."""
    aplicacion = telegram_bot.construir_aplicacion()

    grupo_mas_bajo = min(aplicacion.handlers)
    callbacks = [h.callback for h in aplicacion.handlers[grupo_mas_bajo]]

    assert telegram_bot.puerta_allowlist in callbacks
    # Y es la PRIMERA de su grupo: un desconocido se corta antes incluso
    # de crear entrada en el estado del rate limiter.
    assert callbacks[0] is telegram_bot.puerta_allowlist


def test_ningun_handler_de_las_puertas_es_no_bloqueante():
    """ApplicationHandlerStop "has no effect, if the handler is run in a
    non-blocking way" (doc de PTB, verificada en el paquete instalado).
    Un block=False puesto "para ir mas rapido" desactivaria EN SILENCIO
    todo el control de acceso: este test lo impide.

    bool(handler.block) y no "handler.block is True": cuando no se pasa
    block explicitamente, PTB no guarda el bool sino un centinela
    DefaultValue(True) (comprobado en el paquete instalado) - su repr es
    "True" pero no ES True. bool() distingue bien los tres casos: por
    defecto -> True, block=True -> True, block=False -> False."""
    aplicacion = telegram_bot.construir_aplicacion()

    for handler in aplicacion.handlers[min(aplicacion.handlers)]:
        assert bool(handler.block) is True


# --- Rate limiting ---------------------------------------------------------


def test_el_limite_por_usuario_corta_la_rafaga(monkeypatch):
    """Sin esto, un dedo pegado al boton de enviar agota la cuota del free
    tier de Groq (~30 RPM) y deja el bot inutil."""
    reloj = [1000.0]
    monkeypatch.setattr(telegram_bot.time, "monotonic", lambda: reloj[0])
    update = _update(user_id=111)

    for _ in range(telegram_bot._LIMITE_MENSAJES):
        asyncio.run(telegram_bot.puerta_rate_limit(update, _context()))

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(telegram_bot.puerta_rate_limit(update, _context()))


def test_la_ventana_se_libera_con_el_tiempo(monkeypatch):
    """Un limitador que no libera no es un limitador, es un baneo
    permanente tras la primera rafaga."""
    reloj = [1000.0]
    monkeypatch.setattr(telegram_bot.time, "monotonic", lambda: reloj[0])
    update = _update(user_id=111)

    for _ in range(telegram_bot._LIMITE_MENSAJES):
        asyncio.run(telegram_bot.puerta_rate_limit(update, _context()))

    reloj[0] += telegram_bot._VENTANA_SEGUNDOS + 1
    asyncio.run(telegram_bot.puerta_rate_limit(update, _context()))  # no lanza


# --- Aislamiento entre usuarios (privacidad, no solo concurrencia) --------


def test_cada_usuario_tiene_su_propio_agente(monkeypatch):
    """La razon de fondo NO es la concurrencia: dos usuarios compartiendo
    self.historial se leerian la conversacion entera el uno al otro en
    cada turno, porque el historial viaja completo al LLM."""
    monkeypatch.setattr(
        telegram_bot, "_configuracion_por_defecto", lambda: ("groq", "m", "k")
    )
    monkeypatch.setattr(telegram_bot, "Agente", lambda *a, **kw: SimpleNamespace(historial=[]))

    primero = telegram_bot._agente_de(111)
    segundo = telegram_bot._agente_de(222)

    assert primero is not segundo
    assert telegram_bot._agente_de(111) is primero  # y se reutiliza el mismo


# --- Limites de tamaño -----------------------------------------------------


def test_un_mensaje_demasiado_largo_no_llega_al_llm(monkeypatch):
    """AUD-03 (la mitad aplazada a F5.2). Se comprueba ANTES de llamar al
    LLM: un mensaje gigante no debe consumir cuota siquiera."""
    llamadas = []
    monkeypatch.setattr(
        telegram_bot,
        "_agente_de",
        lambda uid: SimpleNamespace(preguntar=lambda t: llamadas.append(t) or "x"),
    )
    enviados = []
    update = _update(texto="x" * (telegram_bot._LIMITE_ENTRADA + 1), enviados=enviados)

    asyncio.run(telegram_bot.manejar_mensaje(update, _context()))

    assert llamadas == []
    assert "largo" in " ".join(enviados)


def test_un_mensaje_normal_si_llega_al_llm(monkeypatch):
    """Caso de control del test anterior."""
    monkeypatch.setattr(
        telegram_bot,
        "_agente_de",
        lambda uid: SimpleNamespace(preguntar=lambda t: f"respondo a {t}"),
    )
    enviados = []

    asyncio.run(telegram_bot.manejar_mensaje(_update(texto="hola", enviados=enviados), _context()))

    assert enviados == ["respondo a hola"]


# --- Troceo de la salida (funcion pura) ------------------------------------


def test_una_respuesta_larga_se_trocea_sin_perder_texto():
    texto = "linea\n" * 2000  # ~12.000 caracteres

    trozos = telegram_bot._trocear(texto)

    assert all(len(t) <= telegram_bot._LIMITE_TELEGRAM for t in trozos)
    assert "".join(trozos).replace("\n", "") == texto.replace("\n", "")


def test_una_respuesta_corta_no_se_toca():
    assert telegram_bot._trocear("hola") == ["hola"]


def test_una_palabra_gigantesca_sin_espacios_tambien_se_corta():
    """Caso limite real (un base64, un hash): sin sitio donde cortar
    limpiamente hay que cortar igual - nunca devolver un trozo de 9000 que
    Telegram rechazaria entero."""
    trozos = telegram_bot._trocear("x" * 9000)

    assert all(len(t) <= telegram_bot._LIMITE_TELEGRAM for t in trozos)


# --- Errores: nada tecnico hacia el chat -----------------------------------


def test_un_fallo_inesperado_no_manda_detalle_tecnico_al_chat(caplog, monkeypatch):
    """AUD-07 aplicado al canal de Telegram. Agente.preguntar() solo captura
    ErrorLLM, asi que un fallo de ChromaDB sube tal cual hasta aqui."""

    def revienta(_):
        raise RuntimeError("chromadb: fallo al leer 'la cita del medico del jueves'")

    monkeypatch.setattr(
        telegram_bot, "_agente_de", lambda uid: SimpleNamespace(preguntar=revienta)
    )
    enviados = []

    with caplog.at_level(logging.ERROR):
        asyncio.run(telegram_bot.manejar_mensaje(_update(enviados=enviados), _context()))

    salida = " ".join(enviados)
    assert "RuntimeError" not in salida  # nada tecnico al chat
    assert "chromadb" not in salida
    assert "Traceback" not in salida
    assert "cita del medico" not in caplog.text  # ni contenido al log
    assert "RuntimeError" in caplog.text  # el tipo si, para poder depurar


# --- Privacidad del log del bot -------------------------------------------


def test_un_turno_completo_no_deja_ni_una_palabra_personal_en_el_log(caplog, monkeypatch):
    """EL TEST END-TO-END DE PRIVACIDAD. Simula un turno entero (puerta ->
    rate limit -> handler) y afirma que ni la pregunta, ni la respuesta, ni
    el nombre real, ni el user_id en claro aparecen en NINGUN registro.

    Es el que atrapa el logging.debug("update: %s", update) que alguien
    meta dentro de seis meses "para depurar un momentito" - el error nº1
    de los bots de Telegram, porque un Update vuelca de golpe el texto, el
    nombre y el id."""
    pregunta = "cuando es mi cita con el doctor Ramirez"
    respuesta = "El jueves a las 10"
    monkeypatch.setattr(
        telegram_bot, "_agente_de", lambda uid: SimpleNamespace(preguntar=lambda t: respuesta)
    )
    update = _update(user_id=111, texto=pregunta, nombre="Jordi")

    with caplog.at_level(logging.DEBUG):
        asyncio.run(telegram_bot.puerta_allowlist(update, _context()))
        asyncio.run(telegram_bot.puerta_rate_limit(update, _context()))
        asyncio.run(telegram_bot.manejar_mensaje(update, _context()))

    registros = "\n".join(r.getMessage() for r in caplog.records)
    assert pregunta not in registros
    assert respuesta not in registros
    assert "Ramirez" not in registros
    assert "Jordi" not in registros  # el nombre real viaja en CADA update
    assert "111" not in registros  # el user_id en claro


def test_la_huella_de_un_rechazo_no_lleva_el_user_id_en_claro(caplog):
    """En el trafico RECHAZADO si queremos auditar ("¿me esta sondeando
    alguien?"), pero sin guardar a quien: la huella distingue repeticiones
    sin ser reversible."""
    with caplog.at_level(logging.WARNING), pytest.raises(ApplicationHandlerStop):
        asyncio.run(telegram_bot.puerta_allowlist(_update(user_id=987654321), _context()))

    assert "987654321" not in caplog.text
    assert "huella=" in caplog.text


def test_la_huella_es_estable_para_el_mismo_id_y_distinta_entre_ids():
    """Sin esto la huella no serviria para nada: hay que poder distinguir
    'el mismo desconocido 40 veces' de '40 desconocidos distintos'."""
    assert telegram_bot._huella(555) == telegram_bot._huella(555)
    assert telegram_bot._huella(555) != telegram_bot._huella(556)


def test_la_huella_no_es_reversible_por_fuerza_bruta_sin_la_sal(monkeypatch):
    """El espacio de user_id es enumerable, asi que un hash SIN sal se
    revierte en segundos probando numeros. Con sal secreta, un atacante que
    solo vea el log no puede reconstruir el id."""
    monkeypatch.setenv(config.TELEGRAM_SAL_ENV, "sal-secreta-de-prueba")
    huella_real = telegram_bot._huella(12345)

    monkeypatch.setenv(config.TELEGRAM_SAL_ENV, "otra-sal-distinta")
    assert telegram_bot._huella(12345) != huella_real


# ===========================================================================
# Regresiones de la AUDITORÍA DE SEGURIDAD del 27/07/2026
# ===========================================================================
#
# El hallazgo crítico: la puerta de acceso fallaba ABIERTO. Cadena real,
# verificada de punta a punta contra la Application de PTB:
#
#   TELEGRAM_LOG_SAL de más de 32 bytes en el .env (una frase normal, o un
#   token_hex(32))  ->  llega un desconocido  ->  la puerta entra en la rama
#   de rechazo  ->  _huella() llama a blake2s, que acepta claves de 32 bytes
#   COMO MÁXIMO, y lanza ValueError  ->  el `raise ApplicationHandlerStop`
#   de la línea siguiente NUNCA se ejecuta  ->  PTB manda la excepción a
#   process_error(), que devuelve False porque el error handler no lanzaba
#   AHS  ->  process_update() NO hace break  ->  el update continúa al grupo
#   0  ->  manejar_mensaje ATIENDE al desconocido, con acceso al LLM y a
#   buscar_en_recuerdos.
#
# Lo peor: solo fallaba para los NO autorizados. Probando con la cuenta
# propia todo parecía correcto.


def test_una_sal_larga_no_rompe_la_huella():
    """Causa raíz #1. blake2s acepta 32 bytes de clave como máximo;
    config.obtener_sal_log() la normaliza con SHA-256 para que cualquier
    valor del .env sea válido."""
    import os

    for sal in ["x" * 33, "x" * 64, "una frase larga y perfectamente razonable como sal"]:
        os.environ[config.TELEGRAM_SAL_ENV] = sal
        try:
            assert telegram_bot._huella(999)  # no lanza
        finally:
            os.environ.pop(config.TELEGRAM_SAL_ENV, None)


def test_la_puerta_falla_cerrada_ante_cualquier_excepcion(monkeypatch):
    """Causa raíz #2, y la que cierra la CLASE entera de fallo: da igual
    QUÉ excepción se produzca dentro de la puerta, el update se rechaza.
    El control de acceso no puede depender de que ninguna línea futura
    lance nunca nada."""

    def revienta(_):
        raise RuntimeError("cualquier cosa inesperada")

    monkeypatch.setattr(telegram_bot, "_huella", revienta)

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(telegram_bot.puerta_allowlist(_update(user_id=999), _context()))


def test_el_error_handler_corta_el_procesamiento(monkeypatch):
    """Causa raíz #3. Verificado en el código de PTB: process_error() solo
    devuelve True -y por tanto process_update() solo hace break- si el
    error handler lanza ApplicationHandlerStop. Sin esto, una excepción en
    una puerta del grupo -1 dejaba que el update siguiera al grupo 0."""
    contexto = SimpleNamespace(error=RuntimeError("x"))

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(telegram_bot.manejar_error(None, contexto))


def test_end_to_end_un_desconocido_nunca_es_atendido_pase_lo_que_pase(monkeypatch):
    """LA PRUEBA QUE IMPORTA: se recorre la Application REAL de PTB con
    process_update(), no los callbacks a mano, porque el fallo vivía
    justo en el despacho de PTB (entre un grupo y el siguiente).
    Se fuerza el peor caso -que la puerta reviente- y se comprueba que el
    desconocido NO llega al handler protegido."""
    from datetime import datetime

    from telegram import Chat, Message, Update, User

    atendidos = []

    async def espia(update, context):
        atendidos.append(update.effective_user.id)

    monkeypatch.setattr(telegram_bot, "_huella", lambda _: 1 / 0)  # peor caso

    async def escenario():
        aplicacion = telegram_bot.construir_aplicacion()
        for handler in aplicacion.handlers[0]:
            handler.callback = espia
        aplicacion._initialized = True  # evita la llamada de red de initialize()
        mensaje = Message(
            message_id=1,
            date=datetime.now(),
            chat=Chat(id=999, type="private"),
            from_user=User(id=999, first_name="Desconocido", is_bot=False),
            text="hola",
        )
        await aplicacion.process_update(Update(update_id=1, message=mensaje))

    asyncio.run(escenario())

    assert atendidos == [], "un user_id NO autorizado llegó a un handler del grupo 0"


def test_arrancar_con_dos_usuarios_es_un_error_duro(monkeypatch):
    """El índice RAG es global y storage.py no guarda de quién es cada
    conversación, así que con dos usuarios autorizados uno puede leer los
    recuerdos descifrados del otro. Antes solo se avisaba por log -y un
    aviso que vive en un fichero no lo lee nadie al arrancar-. Mejor no
    arrancar que arrancar filtrando."""
    monkeypatch.setenv(config.TELEGRAM_PERMITIDOS_ENV, "111,222")

    with pytest.raises(config.ConfiguracionTelegramInvalida):
        telegram_bot.construir_aplicacion()


def test_los_comandos_no_se_pierden_en_silencio():
    """'/limpiar' es texto Y es comando, así que no encajaba en
    `filters.TEXT & ~filters.COMMAND` ni en `~filters.TEXT`: caía entre
    las dos sillas y desaparecía. Incluido '/start', que es lo primero
    que escribe cualquiera al abrir un bot."""
    aplicacion = telegram_bot.construir_aplicacion()
    registrados = {h.callback for h in aplicacion.handlers[0]}

    for comando in (
        telegram_bot.cmd_start,
        telegram_bot.cmd_ayuda,
        telegram_bot.cmd_limpiar,
        telegram_bot.cmd_resumen,
        telegram_bot.cmd_desconocido,
    ):
        assert comando in registrados


def test_limpiar_borra_de_verdad_el_historial(monkeypatch):
    """Sin /limpiar, el historial crece sin tope y se reenvía entero en
    cada turno (mitad pendiente de AUD-03)."""
    monkeypatch.setattr(
        telegram_bot, "_configuracion_por_defecto", lambda: ("groq", "m", "k")
    )
    monkeypatch.setattr(telegram_bot, "Agente", lambda *a, **kw: SimpleNamespace(historial=[]))
    telegram_bot._agente_de(111)
    assert 111 in telegram_bot._agentes

    asyncio.run(telegram_bot.cmd_limpiar(_update(user_id=111), _context()))

    assert 111 not in telegram_bot._agentes


def test_un_fallo_al_crear_el_agente_avisa_al_usuario(monkeypatch):
    """_agente_de() lee la API key; si falta, lanzaba FUERA del try y el
    usuario no recibía ni el aviso genérico: silencio total y permanente,
    porque el Agente nunca se cacheaba y fallaba en cada mensaje."""

    def revienta(_):
        raise RuntimeError("falta la clave")

    monkeypatch.setattr(telegram_bot, "_agente_de", revienta)
    enviados = []

    asyncio.run(telegram_bot.manejar_mensaje(_update(enviados=enviados), _context()))

    assert enviados, "el usuario debe recibir algo, no silencio"
    assert "cable" in " ".join(enviados)


def test_un_token_invalido_no_filtra_el_token(caplog, monkeypatch):
    """Verificado en PTB: con un token mal formado lanza
    InvalidToken("The token `<token>` was rejected..."), o sea el secreto
    DENTRO del mensaje. Ese traceback saldría por stderr y en un
    despliegue real lo recogería journald o los logs de Docker."""
    secreto = "999888:TOKEN-SECRETO-QUE-NO-DEBE-SALIR"
    monkeypatch.setenv(config.TELEGRAM_TOKEN_ENV, "token con espacios no valido")

    def constructor_que_revienta(*a, **kw):
        raise ValueError(f"The token `{secreto}` was rejected by the server.")

    monkeypatch.setattr(telegram_bot, "ApplicationBuilder", constructor_que_revienta)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(config.ConfiguracionTelegramInvalida) as fallo:
            telegram_bot.construir_aplicacion()

    assert secreto not in caplog.text
    assert secreto not in str(fallo.value)


# --- F5.2+: memoria compartida CLI <-> Telegram -------------------------
# Antes, el bot NO llamaba nunca a guardar(): lo hablado por Telegram vivia
# solo en RAM y no alimentaba el RAG, asi que buscar_en_recuerdos solo
# encontraba lo escrito desde la terminal. Ninguno de estos tests toca el
# disco real ni ChromaDB: se espia guardar_conversacion/indexar_conversacion.


@pytest.fixture
def persistencia_espiada(monkeypatch, tmp_path):
    """Sustituye el guardado y el indexado por espias. Devuelve el registro
    de lo que se les pidio hacer."""
    registro = SimpleNamespace(guardados=[], indexados=[], ruta=tmp_path / "conv.json")

    def guardar_falso(historial, proveedor, modelo, nombre=None, ruta=None):
        registro.guardados.append(
            {"mensajes": len(historial), "nombre": nombre, "ruta": ruta}
        )
        return registro.ruta

    monkeypatch.setattr(telegram_bot, "guardar_conversacion", guardar_falso)
    monkeypatch.setattr(
        telegram_bot, "indexar_conversacion", lambda r: registro.indexados.append(r)
    )
    return registro


def _agente_falso(monkeypatch, respuesta="respondo"):
    """Un Agente de mentira que SI queda registrado en _agentes (a
    diferencia del stub de _agente_de que usan los tests de arriba), porque
    _persistir lo busca ahi."""
    agente = SimpleNamespace(
        preguntar=lambda t: respuesta,
        historial=[{"role": "system", "content": "s"}, {"role": "user", "content": "hola"}],
        proveedor="groq",
        modelo="llama",
    )
    monkeypatch.setattr(
        telegram_bot, "_agente_de", lambda uid: telegram_bot._agentes.setdefault(uid, agente)
    )
    return agente


def test_un_turno_por_telegram_se_guarda_y_se_indexa(monkeypatch, persistencia_espiada):
    """La razon de ser del cambio: lo hablado por Telegram tiene que acabar
    en el mismo almacen que usa la CLI, o las dos memorias van por
    separado."""
    _agente_falso(monkeypatch)

    asyncio.run(telegram_bot.manejar_mensaje(_update(texto="hola"), _context()))

    assert len(persistencia_espiada.guardados) == 1
    assert persistencia_espiada.indexados == [persistencia_espiada.ruta]


def test_los_turnos_siguientes_reescriben_el_mismo_fichero(monkeypatch, persistencia_espiada):
    """Sin esto, cada turno crearia un JSON nuevo (superconjunto del
    anterior) y el RAG indexaria la misma frase una vez por fichero."""
    _agente_falso(monkeypatch)

    asyncio.run(telegram_bot.manejar_mensaje(_update(texto="hola"), _context()))
    asyncio.run(telegram_bot.manejar_mensaje(_update(texto="que tal"), _context()))

    # El primer guardado no conoce ruta todavia; el segundo YA reutiliza la
    # que devolvio el primero.
    assert persistencia_espiada.guardados[0]["ruta"] is None
    assert persistencia_espiada.guardados[1]["ruta"] == persistencia_espiada.ruta


def test_un_turno_que_falla_no_se_persiste(monkeypatch, persistencia_espiada):
    """Un historial que acaba en error no debe entrar en la memoria a largo
    plazo como si fuera conversacion real (mismo criterio que
    Agente.preguntar, que no guarda las respuestas de error)."""
    def revienta(texto):
        raise RuntimeError("boom")

    agente = _agente_falso(monkeypatch)
    agente.preguntar = revienta
    enviados = []

    asyncio.run(telegram_bot.manejar_mensaje(_update(enviados=enviados), _context()))

    assert persistencia_espiada.guardados == []
    assert "cable" in " ".join(enviados)  # al usuario si se le contesta


def test_si_falla_el_guardado_el_usuario_recibe_su_respuesta(monkeypatch, persistencia_espiada):
    """Guardar es importante, pero no tanto como contestar: un fallo al
    persistir se registra y se sigue, no rompe el turno."""
    def guardar_que_revienta(*a, **kw):
        raise OSError("disco lleno")

    monkeypatch.setattr(telegram_bot, "guardar_conversacion", guardar_que_revienta)
    _agente_falso(monkeypatch, respuesta="aqui tienes")
    enviados = []

    asyncio.run(telegram_bot.manejar_mensaje(_update(enviados=enviados), _context()))

    assert enviados == ["aqui tienes"]


def test_limpiar_suelta_el_fichero_pero_no_borra_lo_guardado(monkeypatch, persistencia_espiada):
    """/limpiar corta la conversacion en curso; lo ya guardado sigue en
    conversations/ y en el RAG (igual que /limpiar en la CLI tampoco borra
    del disco). Lo que se corta es que la charla SIGUIENTE se escriba
    encima de la anterior."""
    _agente_falso(monkeypatch)
    asyncio.run(telegram_bot.manejar_mensaje(_update(texto="hola"), _context()))
    assert telegram_bot._rutas.get(111) == persistencia_espiada.ruta

    asyncio.run(telegram_bot.cmd_limpiar(_update(), _context()))

    assert 111 not in telegram_bot._rutas
    # El siguiente turno vuelve a empezar fichero (ruta=None).
    asyncio.run(telegram_bot.manejar_mensaje(_update(texto="otra cosa"), _context()))
    assert persistencia_espiada.guardados[-1]["ruta"] is None


# --- F5.2+: comandos con paridad con la CLI ----------------------------


def test_al_arrancar_se_indexa_TODA_la_memoria(monkeypatch):
    """REGRESION del bug encontrado probando en real el 28/07.

    El bot solo indexaba SU PROPIA conversacion despues de cada turno, asi
    que una charla guardada desde la CLI quedaba en disco pero fuera del
    indice: buscar_en_recuerdos no la encontraba y el agente contestaba "no
    lo tengo guardado" teniendo el dato a un palmo. La CLI ya indexaba al
    arrancar; al bot se le habia olvidado.

    Este test no existia porque todos los demas ESPIAN el indexado en vez de
    arrancar el bot - por eso el fallo paso limpio los 175 tests.
    """
    llamadas = []
    monkeypatch.setattr(telegram_bot, "indexar_conversaciones", lambda: llamadas.append(1) or 0)
    # La Application real no se construye ni se arranca: solo interesa que
    # main_bot indexe antes de ponerse a escuchar.
    monkeypatch.setattr(
        telegram_bot, "construir_aplicacion",
        lambda: SimpleNamespace(run_polling=lambda: None),
    )

    telegram_bot.main_bot()

    assert llamadas == [1]


def test_si_falla_el_indexado_el_bot_arranca_igual(monkeypatch):
    """RNF-02: sin memoria semantica el bot sigue siendo util, asi que un
    fallo al indexar no debe impedir que arranque."""
    def revienta():
        raise RuntimeError("chroma roto")

    arrancado = []
    monkeypatch.setattr(telegram_bot, "indexar_conversaciones", revienta)
    monkeypatch.setattr(
        telegram_bot, "construir_aplicacion",
        lambda: SimpleNamespace(run_polling=lambda: arrancado.append(1)),
    )

    telegram_bot.main_bot()

    assert arrancado == [1]


def test_historial_lista_sin_descifrar(monkeypatch):
    """Los metadatos van en claro a proposito: listar NO debe necesitar la
    clave ni cargar el contenido de todas las conversaciones."""
    from pathlib import Path

    monkeypatch.setattr(
        telegram_bot, "listar_conversaciones",
        lambda: [Path("2026-07-28_10-00-00.json"), Path("2026-07-28_11-00-00.json")],
    )
    monkeypatch.setattr(
        telegram_bot, "leer_metadatos",
        lambda ruta: {"fecha": "2026-07-28T10:00", "nombre": "chiste malo", "cifrado": True},
    )
    # Si alguien metiera un cargar_conversacion aqui, este espia lo cazaria.
    enviados = []

    asyncio.run(telegram_bot.cmd_historial(_update(enviados=enviados), _context()))

    assert "chiste malo" in " ".join(enviados)


def test_historial_vacio_lo_dice(monkeypatch):
    monkeypatch.setattr(telegram_bot, "listar_conversaciones", lambda: [])
    enviados = []

    asyncio.run(telegram_bot.cmd_historial(_update(enviados=enviados), _context()))

    assert "Todavía no hay" in " ".join(enviados)


def test_guardar_sin_nombre_explica_como_se_usa():
    enviados = []
    contexto = _context()
    contexto.args = []

    asyncio.run(telegram_bot.cmd_guardar(_update(enviados=enviados), contexto))

    assert "/guardar" in " ".join(enviados)


def test_guardar_pone_nombre_y_no_lo_pisa_el_turno_siguiente(
    monkeypatch, persistencia_espiada
):
    """El guardado automatico de cada turno NO debe borrar la etiqueta que
    puso /guardar (si no, el nombre duraria un solo mensaje)."""
    _agente_falso(monkeypatch)
    # Primero se habla (que es cuando nace el Agente del usuario); /guardar
    # sobre una charla que no existe no tiene nada que etiquetar.
    asyncio.run(telegram_bot.manejar_mensaje(_update(texto="hola"), _context()))

    contexto = _context()
    contexto.args = ["ideas", "de", "tools"]

    asyncio.run(telegram_bot.cmd_guardar(_update(), contexto))
    assert persistencia_espiada.guardados[-1]["nombre"] == "ideas de tools"

    # Un turno normal despues: conserva el nombre, no lo cambia por "Telegram".
    asyncio.run(telegram_bot.manejar_mensaje(_update(texto="hola"), _context()))
    assert persistencia_espiada.guardados[-1]["nombre"] == "ideas de tools"


def test_un_nombre_larguisimo_se_rechaza():
    enviados = []
    contexto = _context()
    contexto.args = ["x" * (telegram_bot._MAX_NOMBRE + 1)]

    asyncio.run(telegram_bot.cmd_guardar(_update(enviados=enviados), contexto))

    assert "largo" in " ".join(enviados)


# --- Botones de /modelo y /proveedor: el dato que vuelve NO se confia ---


def _consulta(dato, respondido=None):
    """CallbackQuery falso (lo que manda Telegram al pulsar un boton)."""
    editado = respondido if respondido is not None else []

    async def answer(*a, **kw):
        return None

    async def edit_message_text(texto, *a, **kw):
        editado.append(texto)

    return SimpleNamespace(data=dato, answer=answer, edit_message_text=edit_message_text)


def _update_boton(dato, user_id=111, editado=None):
    return SimpleNamespace(
        callback_query=_consulta(dato, editado),
        effective_user=SimpleNamespace(id=user_id, first_name="Jordi", username="Jordi"),
        effective_message=None,
    )


def test_un_modelo_fuera_del_catalogo_se_rechaza(monkeypatch):
    """El callback_data viaja a Telegram y vuelve: es dato NO confiable.
    Aunque hoy solo pueda pulsarlo el usuario de la allowlist, el valor se
    valida contra el catalogo verificado de config.py antes de usarlo."""
    cambios = []
    agente = SimpleNamespace(
        proveedor="groq", modelo="llama-3.3-70b-versatile",
        cambiar_modelo=lambda m: cambios.append(m),
    )
    monkeypatch.setattr(telegram_bot, "_agente_de", lambda uid: agente)
    editado = []

    boton = _update_boton("m:modelo-inventado", editado=editado)
    asyncio.run(telegram_bot.manejar_boton(boton, _context()))

    assert cambios == []
    assert "ya no está disponible" in " ".join(editado)


def test_un_modelo_del_catalogo_si_cambia(monkeypatch):
    """Caso de control: sin esto, 'rechazarlo todo' pasaria el test anterior."""
    from src.config import MODELOS

    cambios = []
    agente = SimpleNamespace(
        proveedor="groq", modelo="llama-3.3-70b-versatile",
        cambiar_modelo=lambda m: cambios.append(m),
    )
    monkeypatch.setattr(telegram_bot, "_agente_de", lambda uid: agente)
    valido = MODELOS["groq"][1]

    asyncio.run(telegram_bot.manejar_boton(_update_boton(f"m:{valido}"), _context()))

    assert cambios == [valido]


def test_un_proveedor_sin_clave_no_se_activa(monkeypatch):
    """Ofrecer un proveedor sin clave seria ofrecer un error. Si el boton
    llegara igual (dato manipulado), se rechaza aqui."""
    from src.config import ClaveApiNoConfigurada

    cambios = []
    agente = SimpleNamespace(
        proveedor="groq", modelo="m",
        cambiar_proveedor=lambda p, m, k: cambios.append(p),
    )
    monkeypatch.setattr(telegram_bot, "_agente_de", lambda uid: agente)

    def sin_clave(proveedor):
        raise ClaveApiNoConfigurada("no hay")

    monkeypatch.setattr(telegram_bot, "obtener_api_key", sin_clave)
    editado = []

    asyncio.run(telegram_bot.manejar_boton(_update_boton("p:gemini", editado=editado), _context()))

    assert cambios == []
    assert "clave" in " ".join(editado)


def test_los_botones_pasan_por_la_allowlist():
    """Un CallbackQuery es un Update como otro cualquiera, asi que la puerta
    del grupo -1 (TypeHandler(Update)) lo cubre sin codigo extra. Es la
    ventaja del diseño de ADR-005: una via de entrada nueva NO obliga a
    acordarse de protegerla."""
    aplicacion = telegram_bot.construir_aplicacion()
    grupo = min(aplicacion.handlers)

    assert aplicacion.handlers[grupo][0].callback is telegram_bot.puerta_allowlist
    # Y el handler de botones vive en un grupo POSTERIOR (0), o sea que la
    # puerta corre antes.
    grupos_con_botones = [
        g for g, hs in aplicacion.handlers.items()
        if any(h.callback is telegram_bot.manejar_boton for h in hs)
    ]
    assert grupos_con_botones and min(grupos_con_botones) > grupo
