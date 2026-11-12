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
from telegram.constants import ChatType
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
    telegram_bot._voz_activa.clear()
    telegram_bot._esperando_texto.clear()
    telegram_bot._guardado_fallido.clear()
    telegram_bot._avisados_guardado.clear()
    monkeypatch.setenv(config.TELEGRAM_PERMITIDOS_ENV, "111")
    monkeypatch.setenv(config.TELEGRAM_TOKEN_ENV, "123456:token-de-mentira")
    yield
    telegram_bot._agentes.clear()
    telegram_bot._cerrojos.clear()
    telegram_bot._marcas.clear()
    telegram_bot._rutas.clear()
    telegram_bot._voz_activa.clear()
    telegram_bot._esperando_texto.clear()


def _update(user_id=111, texto="hola", nombre="Jordi", enviados=None, teclados=None,
           tipo_chat=ChatType.PRIVATE):
    """Update falso: solo los atributos que leen nuestros callbacks.

    `teclados` guarda el reply_markup de cada respuesta: desde el 31/07 hay
    menus (historial, /voz, /ayuda) cuyo contenido esta en los BOTONES y no
    en el texto, y sin esto un test no puede verlos.

    `tipo_chat` (04/08, AUT-01): PRIVATE por defecto, para que la bateria
    existente de tests (que representa el uso normal, un chat 1:1) no tenga
    que enterarse del cambio. Se puede poner GROUP/SUPERGROUP a proposito
    para probar el rechazo nuevo.
    """
    enviados = enviados if enviados is not None else []
    teclados = teclados if teclados is not None else []

    async def reply_text(texto_respuesta, *a, **kw):
        enviados.append(texto_respuesta)
        teclados.append(kw.get("reply_markup"))

    mensaje = SimpleNamespace(
        text=texto, chat_id=user_id, reply_text=reply_text,
        enviados=enviados, teclados=teclados,
    )
    usuario = (
        None
        if user_id is None
        else SimpleNamespace(id=user_id, first_name=nombre, username=nombre)
    )
    chat = None if tipo_chat is None else SimpleNamespace(id=user_id, type=tipo_chat)
    return SimpleNamespace(
        effective_user=usuario, effective_message=mensaje, effective_chat=chat,
    )


def _context():
    async def send_chat_action(*a, **kw):
        return None

    return SimpleNamespace(bot=SimpleNamespace(send_chat_action=send_chat_action))


# --- AUD-A1: la lista blanca -----------------------------------------------


@pytest.mark.requisito("RF-11", "RNF-05")
@pytest.mark.control("E2-ACCESO")
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


@pytest.mark.requisito("RF-11", "CU-01")
def test_el_usuario_autorizado_pasa():
    """Caso de control: sin esto, 'rechazarlo todo' pasaria los dos tests
    anteriores y el bot no funcionaria para nadie."""
    asyncio.run(telegram_bot.puerta_allowlist(_update(user_id=111), _context()))


@pytest.mark.requisito("RF-23")
@pytest.mark.control("E2-ACCESO")
@pytest.mark.parametrize("tipo", [ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL])
def test_AUT01_el_usuario_autorizado_NO_pasa_desde_un_grupo(tipo):
    """Auditoria del 04/08 (AUT-01): la allowlist protegia QUIEN puede
    hablar con el bot, pero no DONDE se publica la respuesta. Antes de este
    arreglo, JIM escribiendo desde un grupo (Telegram permite añadir un bot
    a uno en un toque, sin querer o sin pensarlo) pasaba la puerta -es su
    user_id- y la respuesta -memoria, recuerdos, lo que fuera- quedaba
    visible para todo el grupo. Exactamente el escape que RNF-06 promete
    que no pasa, solo que de destino y no de acceso.

    Mismo criterio que la voz: RNF-06 no se cumple porque "no lo hare", se
    cumple porque el codigo no lo deja."""
    update = _update(user_id=111, tipo_chat=tipo)

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(telegram_bot.puerta_allowlist(update, _context()))


@pytest.mark.requisito("RF-23")
def test_AUT01_sin_chat_tampoco_pasa():
    """effective_chat puede ser None de verdad (canal, poll...), igual que
    effective_user. Mismo criterio: sin dato que autorizar, fuera."""
    update = _update(user_id=111, tipo_chat=None)

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(telegram_bot.puerta_allowlist(update, _context()))


@pytest.mark.requisito("RF-23")
def test_AUT01_el_rechazo_por_grupo_es_SILENCIOSO():
    """Mismo criterio que el rechazo por user_id desconocido: no se
    responde nada. Confirmar que el bot existe (aunque sea con un "esto es
    privado") es justo la informacion que un desconocido en un grupo
    tampoco necesita."""
    enviados = []
    update = _update(user_id=111, tipo_chat=ChatType.GROUP, enviados=enviados)

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(telegram_bot.puerta_allowlist(update, _context()))

    assert enviados == []


@pytest.mark.requisito("RF-11")
def test_al_desconocido_no_se_le_responde_nada():
    """Silencio deliberado: responder confirmaria que el bot existe (util
    para quien sondea) y gastaria cuota de salida a peticion suya."""
    enviados = []
    update = _update(user_id=999, enviados=enviados)

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(telegram_bot.puerta_allowlist(update, _context()))

    assert enviados == []


@pytest.mark.requisito("RF-11")
@pytest.mark.control("E2-ACCESO")
@pytest.mark.mutacion("Lista blanca ilegible tratada como permitir a todos")
@pytest.mark.parametrize("valor", ["", "   ", "no-es-un-numero", "111,abc"])
def test_una_lista_blanca_rota_cierra_el_bot_no_lo_abre(monkeypatch, valor):
    """FALLA CERRADO. El modo de fallo peligroso seria interpretar una
    lista ilegible como 'no filtrar', que convierte el control de acceso
    en decoracion."""
    monkeypatch.setenv(config.TELEGRAM_PERMITIDOS_ENV, valor)

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(telegram_bot.puerta_allowlist(_update(user_id=111), _context()))


@pytest.mark.requisito("RF-11")
def test_sin_variable_de_lista_blanca_tambien_cierra(monkeypatch):
    monkeypatch.delenv(config.TELEGRAM_PERMITIDOS_ENV, raising=False)

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(telegram_bot.puerta_allowlist(_update(user_id=111), _context()))


# --- La invariante estructural: la que sobrevive a F5.5 --------------------


@pytest.mark.requisito("RF-11")
@pytest.mark.control("E2-ACCESO")
@pytest.mark.mutacion("Mover la puerta de la lista blanca al grupo 0")
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


@pytest.mark.requisito("RF-11")
@pytest.mark.mutacion("block=False en la puerta")
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


@pytest.mark.control("E2-ABUSO")
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


@pytest.mark.control("E2-ABUSO")
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


@pytest.mark.control("E2-ENTRADA")
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


@pytest.mark.control("E2-ENTRADA")
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


def test_limpiar_AVISA_si_se_apagan_memoria_o_web(monkeypatch):
    """Bug conocido desde el 02/08, avisado en vez de arreglado (decision
    de Jordi, 04/08): /limpiar destruye el Agente y el que lo sustituye
    arranca con categorias_por_defecto() -memoria y web OFF-. Si el que se
    cerraba las tenia encendidas, esa vuelta atras pasaba EN SILENCIO."""
    enviados = []
    monkeypatch.setattr(
        telegram_bot, "_configuracion_por_defecto", lambda: ("groq", "m", "k")
    )
    telegram_bot._agentes[111] = SimpleNamespace(
        historial=[], categorias_activas={"memoria", "web", "calculadora"}
    )

    asyncio.run(telegram_bot.cmd_limpiar(_update(user_id=111, enviados=enviados), _context()))

    aviso = enviados[-1]
    assert "memoria" in aviso
    assert "web" in aviso
    assert "calculadora" not in aviso, "esa nunca se apaga por defecto"


def test_limpiar_NO_avisa_si_no_habia_nada_encendido():
    """Caso de control: sin categorias sensibles activas, el mensaje se
    queda igual que antes del arreglo - no hay que meter ruido de mas."""
    enviados = []
    telegram_bot._agentes[111] = SimpleNamespace(
        historial=[], categorias_activas=set()
    )

    asyncio.run(telegram_bot.cmd_limpiar(_update(user_id=111, enviados=enviados), _context()))

    assert "apagarse" not in enviados[-1]


def test_limpiar_NO_revienta_con_un_agente_sin_categorias_activas():
    """El aviso es de CORTESIA: un doble de test (u objeto futuro) sin el
    atributo no puede tumbar el comando principal."""
    enviados = []
    telegram_bot._agentes[111] = SimpleNamespace(historial=[])

    asyncio.run(telegram_bot.cmd_limpiar(_update(user_id=111, enviados=enviados), _context()))

    assert 111 not in telegram_bot._agentes  # limpio igual, sin reventar


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


@pytest.mark.requisito("RF-03", "RF-06")
def test_R06_si_fallan_TODOS_los_proveedores_ni_se_guarda_ni_se_lee_en_alto(
    monkeypatch, persistencia_espiada
):
    """R-06 (auditoria de seguridad de noviembre). Agente.preguntar devuelve
    el mensaje de error como si fuera una respuesta, y el bot lo trataba
    igual que una de verdad: persistia la pregunta huerfana, la indexaba en
    el RAG y, con la voz encendida, leia en alto el "⚠️ limite superado".

    Con un Agente REAL y un router que falla entero: al usuario le llega el
    aviso escrito, y nada mas."""
    from src.agent import Agente
    from src.llm_errors import ErrorLimitePeticiones

    agente = Agente("s", "groq", "x", "fake")

    def falla(mensajes, tools):
        raise ErrorLimitePeticiones("Groq", "rate limit")

    agente.router = SimpleNamespace(responder=falla, aviso_fallback=None)
    monkeypatch.setattr(
        telegram_bot, "_agente_de", lambda uid: telegram_bot._agentes.setdefault(uid, agente)
    )
    telegram_bot._voz_activa[111] = {"hablar"}
    hablado = []

    async def hablar_espia(update, context, texto):
        hablado.append(texto)

    monkeypatch.setattr(telegram_bot, "_hablar", hablar_espia)
    enviados = []

    asyncio.run(telegram_bot.manejar_mensaje(_update(enviados=enviados), _context()))

    assert enviados and "límite" in enviados[0]
    assert persistencia_espiada.guardados == []
    assert persistencia_espiada.indexados == []
    assert hablado == []


def test_si_falla_el_guardado_el_usuario_recibe_su_respuesta(monkeypatch, persistencia_espiada):
    """Guardar es importante, pero no tanto como contestar: un fallo al
    persistir se registra y se sigue, no rompe el turno."""
    def guardar_que_revienta(*a, **kw):
        raise OSError("disco lleno")

    monkeypatch.setattr(telegram_bot, "guardar_conversacion", guardar_que_revienta)
    _agente_falso(monkeypatch, respuesta="aqui tienes")
    enviados = []

    asyncio.run(telegram_bot.manejar_mensaje(_update(enviados=enviados), _context()))

    # R-02: la respuesta llega PRIMERO y entera; detras, el aviso de que no
    # se pudo guardar (antes el fallo solo iba al log y nadie se enteraba).
    assert enviados[0] == "aqui tienes"


@pytest.mark.requisito("RF-06", "RNF-02")
def test_R02_si_falla_el_guardado_se_DICE_una_vez_y_sin_el_texto_del_error(
    monkeypatch, persistencia_espiada
):
    """R-02 (auditoria de seguridad de noviembre). Un fallo de _persistir
    solo iba al log: el usuario seguia hablando creyendo que todo quedaba
    guardado. Se le dice en el chat, pero UNA vez por racha de fallos (si el
    disco esta lleno, repetirlo en cada mensaje es ruido que se aprende a
    ignorar) y SIN el texto de la excepcion, que puede llevar rutas o
    contenido. Si vuelve a guardar bien y luego falla otra vez, se avisa
    otra vez: es otra racha."""
    estado = {"falla": True}

    def guardar(historial, proveedor, modelo, nombre=None, ruta=None):
        if estado["falla"]:
            raise OSError("disco lleno en /home/bot-jimmy/conversations/secreto.json")
        return persistencia_espiada.ruta

    monkeypatch.setattr(telegram_bot, "guardar_conversacion", guardar)
    _agente_falso(monkeypatch, respuesta="vale")

    def turno():
        enviados = []
        asyncio.run(telegram_bot.manejar_mensaje(_update(enviados=enviados), _context()))
        return [e for e in enviados if e != "vale"]

    primero, segundo = turno(), turno()
    estado["falla"] = False
    tercero = turno()
    estado["falla"] = True
    cuarto = turno()

    assert len(primero) == 1 and "guardar" in primero[0]
    assert segundo == [] and tercero == []
    assert len(cuarto) == 1
    for aviso in primero + cuarto:
        assert "disco lleno" not in aviso and "secreto" not in aviso


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


@pytest.fixture
def arranque_espiado(monkeypatch):
    """main_bot() sin red ni Telegram: se espia si llega a construir la
    Application y a indexar. Devuelve la lista de lo que llego a hacer."""
    hecho = []
    monkeypatch.setattr(
        telegram_bot, "indexar_conversaciones", lambda: hecho.append("indexar") or 0
    )
    monkeypatch.setattr(
        telegram_bot, "construir_aplicacion",
        lambda: SimpleNamespace(run_polling=lambda: hecho.append("polling")),
    )
    return hecho


@pytest.mark.requisito("RF-17", "RNF-06")
@pytest.mark.control("E2-REPOSO")
def test_R04_sin_clave_de_cifrado_el_bot_NO_arranca(monkeypatch, arranque_espiado, capsys):
    """R-04 (auditoria de seguridad de noviembre). Sin CONVERSATIONS_KEY el
    bot arrancaba y guardaba en claro con solo un print, que en la VPS va a
    journalctl y no lo lee nadie. Un bot 24/7 que guarda la vida de alguien
    en claro no debe poder quedarse asi por olvido: falla cerrado."""
    monkeypatch.delenv(config.CLAVE_CONVERSACIONES_ENV, raising=False)
    monkeypatch.delenv(config.PERMITIR_SIN_CIFRAR_ENV, raising=False)

    telegram_bot.main_bot()

    assert arranque_espiado == []
    salida = capsys.readouterr().out
    assert config.CLAVE_CONVERSACIONES_ENV in salida
    assert config.PERMITIR_SIN_CIFRAR_ENV in salida


@pytest.mark.parametrize("valor", ["", "0", "no", "quizas"])
def test_R04_un_consentimiento_AMBIGUO_no_vale(monkeypatch, arranque_espiado, valor):
    """Allowlist de valores, como DEBUG_LOG_CONTENIDO: solo un "si"
    explicito abre la puerta; cualquier otra cosa la deja cerrada."""
    monkeypatch.delenv(config.CLAVE_CONVERSACIONES_ENV, raising=False)
    monkeypatch.setenv(config.PERMITIR_SIN_CIFRAR_ENV, valor)

    telegram_bot.main_bot()

    assert arranque_espiado == []


def test_R04_con_consentimiento_EXPLICITO_arranca_y_avisa(
    monkeypatch, arranque_espiado, capsys
):
    monkeypatch.delenv(config.CLAVE_CONVERSACIONES_ENV, raising=False)
    monkeypatch.setenv(config.PERMITIR_SIN_CIFRAR_ENV, "1")

    telegram_bot.main_bot()

    assert arranque_espiado == ["indexar", "polling"]
    assert "SIN CIFRAR" in capsys.readouterr().out


def test_R04_con_clave_arranca_como_siempre(monkeypatch, arranque_espiado):
    """No romper el arranque de quien YA tiene la clave (la VPS de hoy)."""
    from cryptography.fernet import Fernet

    monkeypatch.setenv(config.CLAVE_CONVERSACIONES_ENV, Fernet.generate_key().decode())
    monkeypatch.delenv(config.PERMITIR_SIN_CIFRAR_ENV, raising=False)

    telegram_bot.main_bot()

    assert arranque_espiado == ["indexar", "polling"]


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
    # R-04: desde que el bot no arranca sin clave, estos tests -que miran el
    # indexado, no el cifrado- necesitan una. Antes pasaban o no segun el
    # .env de la maquina, que es justo lo que un test no puede hacer.
    from cryptography.fernet import Fernet

    monkeypatch.setenv(config.CLAVE_CONVERSACIONES_ENV, Fernet.generate_key().decode())
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
    # R-04: desde que el bot no arranca sin clave, estos tests -que miran el
    # indexado, no el cifrado- necesitan una. Antes pasaban o no segun el
    # .env de la maquina, que es justo lo que un test no puede hacer.
    from cryptography.fernet import Fernet

    monkeypatch.setenv(config.CLAVE_CONVERSACIONES_ENV, Fernet.generate_key().decode())
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
    # El espia que la docstring prometia y no existia (31/07): si alguien
    # mete un cargar_conversacion en el LISTADO, esto lo caza.
    descifrados = []
    monkeypatch.setattr(
        telegram_bot, "cargar_conversacion", lambda ruta: descifrados.append(ruta)
    )
    enviados, teclados = [], []
    update = _update(enviados=enviados, teclados=teclados)

    asyncio.run(telegram_bot.cmd_historial(update, _context()))

    assert descifrados == [], "listar NO debe descifrar ninguna conversación"
    # Desde el 31/07 los nombres van en los BOTONES (para poder abrirlas),
    # no en el texto del mensaje.
    etiquetas = [b.text for fila in teclados[0].inline_keyboard for b in fila]
    assert any("chiste malo" in e for e in etiquetas)


def test_historial_vacio_lo_dice(monkeypatch):
    monkeypatch.setattr(telegram_bot, "listar_conversaciones", lambda: [])
    enviados = []

    asyncio.run(telegram_bot.cmd_historial(_update(enviados=enviados), _context()))

    assert "Todavía no hay" in " ".join(enviados)


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


def _consulta(dato, respondido=None, mensaje=None):
    """CallbackQuery falso (lo que manda Telegram al pulsar un boton)."""
    editado = respondido if respondido is not None else []

    async def answer(*a, **kw):
        return None

    async def edit_message_text(texto, *a, **kw):
        editado.append(texto)

    return SimpleNamespace(
        data=dato, answer=answer, edit_message_text=edit_message_text, message=mensaje
    )


def _update_boton(dato, user_id=111, editado=None, enviados=None, teclados=None):
    """Update falso de pulsar un boton.

    effective_message NO es None: apunta al MISMO mensaje que
    callback_query.message, igual que en un Update real de PTB
    (Update.effective_message cae a callback_query.message cuando no hay
    update.message - verificado en el codigo fuente de la libreria). Hace
    falta desde el 31/07: el menu de /comandos plano REUTILIZA los propios
    cmd_historial/cmd_tools/cmd_voz... al pulsar un boton, y esas funciones
    leen update.effective_message.reply_text() directamente.
    """
    mensaje = _update(user_id=user_id, enviados=enviados, teclados=teclados).effective_message
    return SimpleNamespace(
        callback_query=_consulta(dato, editado, mensaje=mensaje),
        effective_user=SimpleNamespace(id=user_id, first_name="Jordi", username="Jordi"),
        effective_message=mensaje,
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


# --- F5.2+: /recuerdo y /salir (peticion de Jordi al probar en real) ----


def test_recuerdo_ensena_lo_que_hay_en_memoria(monkeypatch):
    """El agente decide SOLO cuando usar buscar_en_recuerdos, y a veces no
    la usa (el 28/07 contesto 'no lo tengo guardado' con el dato indexado).
    Este comando salta al modelo y enseña la memoria en crudo."""
    monkeypatch.setattr(
        "src.rag.buscar",
        # Ventana de turno (02/08): un intercambio entero, no un mensaje suelto.
        lambda consulta, n=3: [
            {"pregunta": "sabes el del plato hondo",
             "respuesta": "el plato hondo cabe mas comida",
             "fecha": "2026-07-28T12:45", "nombre": "chiste_malo", "distancia": 0.1}
        ],
    )
    enviados = []
    contexto = _context()
    contexto.args = ["plato"]

    asyncio.run(telegram_bot.cmd_recuerdo(_update(enviados=enviados), contexto))

    salida = " ".join(enviados)
    # LO QUE ARREGLA LA VENTANA DE TURNO: antes esto enseñaba la PREGUNTA y
    # se quedaba ahi. Buscar "plato" tiene que traer tambien lo que se
    # contesto, que es lo unico que el usuario queria saber.
    assert "sabes el del plato hondo" in salida
    assert "cabe mas comida" in salida


def test_recuerdo_sin_texto_ESPERA_el_siguiente_mensaje():
    """CAMBIO del 07/08. Antes solo se imprimia la sintaxis y no quedaba
    nada esperando, asi que si el usuario hacia lo natural -escribir la
    busqueda sola en el mensaje siguiente- ese mensaje se lo comia el LLM.
    Jordi lo vio con /guardar: escribio el nombre y el bot le contesto con
    un resumen inventado, sin guardar nada.

    Ahora reutiliza la maquina de estados que YA existia para los botones
    del menu, asi que los dos caminos se comportan igual."""
    enviados = []
    contexto = _context()
    contexto.args = []

    asyncio.run(telegram_bot.cmd_recuerdo(_update(enviados=enviados), contexto))

    assert telegram_bot._esperando_texto.get(111) == "recuerdo"
    assert "siguiente mensaje" in " ".join(enviados)


def test_guardar_sin_nombre_ESPERA_el_siguiente_mensaje():
    """El caso que Jordi encontro de verdad (07/08): hizo /guardar, le
    salio la sintaxis, escribio el nombre solo... y el bot le contesto con
    un resumen inventado de la conversacion. La charla NO se guardo."""
    enviados = []
    contexto = _context()
    contexto.args = []

    asyncio.run(telegram_bot.cmd_guardar(_update(enviados=enviados), contexto))

    assert telegram_bot._esperando_texto.get(111) == "guardar"
    assert "siguiente mensaje" in " ".join(enviados)


def test_recuerdo_sin_resultados_lo_dice(monkeypatch):
    monkeypatch.setattr("src.rag.buscar", lambda consulta, n=3: [])
    enviados = []
    contexto = _context()
    contexto.args = ["algo", "que", "no", "existe"]

    asyncio.run(telegram_bot.cmd_recuerdo(_update(enviados=enviados), contexto))

    assert "No encuentro nada" in " ".join(enviados)


def test_salir_sin_conversacion_abierta_lo_dice():
    enviados = []

    asyncio.run(telegram_bot.cmd_salir(_update(enviados=enviados), _context()))

    assert "No hay ninguna conversación" in " ".join(enviados)


def test_descartar_borra_del_disco_Y_del_indice(monkeypatch, tmp_path):
    """LAS DOS COSAS. Borrar solo el JSON dejaria vectores huerfanos en
    ChromaDB; borrar solo del indice dejaria el contenido cifrado en disco."""
    ruta = tmp_path / "conv.json"
    telegram_bot._rutas[111] = ruta
    olvidados, borrados = [], []
    monkeypatch.setattr(telegram_bot, "olvidar_conversacion", lambda r: olvidados.append(r))
    monkeypatch.setattr(
        telegram_bot, "borrar_conversacion", lambda r: borrados.append(r) or True
    )

    editado = []
    asyncio.run(telegram_bot.manejar_boton(
        _update_boton(telegram_bot._DESCARTAR, editado=editado), _context()
    ))

    assert olvidados == [ruta]
    assert borrados == [ruta]
    assert "borrado" in " ".join(editado)


def test_conservar_cierra_la_charla_sin_borrar_nada(monkeypatch, tmp_path):
    """Caso de control: 'guardar y cerrar' no debe tocar el disco."""
    telegram_bot._rutas[111] = tmp_path / "conv.json"
    borrados = []
    monkeypatch.setattr(telegram_bot, "olvidar_conversacion", lambda r: borrados.append(r))
    monkeypatch.setattr(telegram_bot, "borrar_conversacion", lambda r: borrados.append(r))

    editado = []
    asyncio.run(telegram_bot.manejar_boton(
        _update_boton(telegram_bot._CONSERVAR, editado=editado), _context()
    ))

    assert borrados == []
    assert "Guardada" in " ".join(editado)


@pytest.mark.parametrize("dato", ["salir:conservar", "salir:descartar"])
def test_salir_cierra_la_charla_en_los_dos_casos(monkeypatch, tmp_path, dato):
    """Guardando o descartando, la conversacion se CIERRA: se olvida el
    contexto y se suelta el fichero, para que el mensaje siguiente estrene
    conversacion en vez de seguir escribiendo en la anterior."""
    telegram_bot._rutas[111] = tmp_path / "conv.json"
    telegram_bot._nombres[111] = "una etiqueta"
    telegram_bot._agentes[111] = SimpleNamespace(historial=[])
    monkeypatch.setattr(telegram_bot, "olvidar_conversacion", lambda r: 0)
    monkeypatch.setattr(telegram_bot, "borrar_conversacion", lambda r: True)

    asyncio.run(telegram_bot.manejar_boton(_update_boton(dato), _context()))

    assert 111 not in telegram_bot._rutas
    assert 111 not in telegram_bot._agentes
    assert 111 not in telegram_bot._nombres


@pytest.mark.parametrize("dato", ["salir:conservar", "salir:descartar"])
def test_salir_TAMBIEN_avisa_si_se_apagan_categorias(monkeypatch, tmp_path, dato):
    """Mismo aviso que /limpiar, para el otro camino que destruye el
    Agente: guardar-y-cerrar y descartar-y-cerrar comparten el mismo bug."""
    editado = []
    telegram_bot._rutas[111] = tmp_path / "conv.json"
    telegram_bot._nombres[111] = "una etiqueta"
    telegram_bot._agentes[111] = SimpleNamespace(
        historial=[], categorias_activas={"memoria"}
    )
    monkeypatch.setattr(telegram_bot, "olvidar_conversacion", lambda r: 0)
    monkeypatch.setattr(telegram_bot, "borrar_conversacion", lambda r: True)

    asyncio.run(
        telegram_bot.manejar_boton(_update_boton(dato, editado=editado), _context())
    )

    assert "memoria" in editado[-1]


def test_los_botones_de_salir_no_crean_un_agente(monkeypatch, tmp_path):
    """/salir es lo unico que no necesita un Agente vivo - de hecho lo que
    hace es cerrarlo. Crear uno solo por pulsar el boton llamaria al
    proveedor (lee la API key) sin ninguna necesidad."""
    telegram_bot._rutas[111] = tmp_path / "conv.json"
    creados = []
    monkeypatch.setattr(
        telegram_bot, "_agente_de", lambda uid: creados.append(uid) or SimpleNamespace()
    )
    monkeypatch.setattr(telegram_bot, "olvidar_conversacion", lambda r: 0)
    monkeypatch.setattr(telegram_bot, "borrar_conversacion", lambda r: True)

    asyncio.run(telegram_bot.manejar_boton(_update_boton(telegram_bot._DESCARTAR), _context()))

    assert creados == []


# --- F5.2+: /borrar (el comando mas peligroso del bot) -----------------
# El nombre del fichero viaja a Telegram dentro del callback_data y vuelve:
# dato NO confiable usado para BORRAR FICHEROS. Se valida por ALLOWLIST
# (buscarlo en la lista real de conversaciones), no saneando el texto.


@pytest.fixture
def conversaciones_falsas(monkeypatch, tmp_path):
    """Dos conversaciones de mentira en una carpeta temporal."""
    rutas = []
    for nombre in ("2026-07-27_10-00-00.json", "2026-07-28_12-45-10.json"):
        ruta = tmp_path / nombre
        ruta.write_text("{}", encoding="utf-8")
        rutas.append(ruta)
    monkeypatch.setattr(telegram_bot, "listar_conversaciones", lambda: rutas)
    monkeypatch.setattr(
        telegram_bot, "leer_metadatos",
        lambda r: {"fecha": "2026-07-28T12:45", "nombre": "charla", "cifrado": True},
    )
    return rutas


@pytest.mark.parametrize("malicioso", [
    "../../.env",
    "../../src/main.py",
    r"..\..\.env",
    "/etc/passwd",
    "no-existe.json",
])
def test_un_nombre_manipulado_no_borra_nada(monkeypatch, conversaciones_falsas, malicioso):
    """EL TEST QUE IMPORTA DE ESTE COMANDO. El callback_data se puede
    fabricar a mano; si la ruta se construyera concatenando, un '../../.env'
    borraria la configuracion. Se valida contra la lista REAL, asi que un
    nombre que no este en ella no llega a tocar el disco."""
    borrados = []
    monkeypatch.setattr(telegram_bot, "_borrar_del_todo", lambda r: borrados.append(r) or True)
    editado = []

    boton = _update_boton(f"bc:{malicioso}", editado=editado)
    asyncio.run(telegram_bot.manejar_boton(boton, _context()))

    assert borrados == []
    assert "ya no existe" in " ".join(editado)


def test_una_conversacion_real_si_se_borra(monkeypatch, conversaciones_falsas):
    """Caso de control: sin esto, 'no borrar nunca' pasaria el test anterior
    y el comando no serviria para nada."""
    borrados = []
    monkeypatch.setattr(telegram_bot, "_borrar_del_todo", lambda r: borrados.append(r) or True)
    objetivo = conversaciones_falsas[1]
    editado = []

    boton = _update_boton(f"bc:{objetivo.name}", editado=editado)
    asyncio.run(telegram_bot.manejar_boton(boton, _context()))

    assert borrados == [objetivo]
    assert "Borrada" in " ".join(editado)


def test_borrar_pide_confirmacion_antes(monkeypatch, conversaciones_falsas):
    """Paso 1 (elegir) NO borra: solo pregunta. Es irreversible, no hay
    papelera."""
    borrados = []
    monkeypatch.setattr(telegram_bot, "_borrar_del_todo", lambda r: borrados.append(r))
    editado = []

    boton = _update_boton(f"b:{conversaciones_falsas[0].name}", editado=editado)
    asyncio.run(telegram_bot.manejar_boton(boton, _context()))

    assert borrados == []
    assert "¿Seguro?" in " ".join(editado)


def test_cancelar_no_borra_nada(monkeypatch, conversaciones_falsas):
    borrados = []
    monkeypatch.setattr(telegram_bot, "_borrar_del_todo", lambda r: borrados.append(r))
    editado = []

    asyncio.run(telegram_bot.manejar_boton(
        _update_boton(telegram_bot._CANCELAR, editado=editado), _context()
    ))

    assert borrados == []
    assert "no toco nada" in " ".join(editado)


def test_borrar_la_conversacion_abierta_la_suelta(monkeypatch, conversaciones_falsas):
    """Si se borra la charla EN CURSO hay que soltar su ruta: si no, el
    turno siguiente volveria a escribir en ella y la RESUCITARIA
    (guardar_conversacion con ruta= crea el fichero aunque ya no exista)."""
    abierta = conversaciones_falsas[1]
    telegram_bot._rutas[111] = abierta
    telegram_bot._nombres[111] = "etiqueta"
    monkeypatch.setattr(telegram_bot, "_borrar_del_todo", lambda r: True)

    asyncio.run(telegram_bot.manejar_boton(_update_boton(f"bc:{abierta.name}"), _context()))

    assert 111 not in telegram_bot._rutas
    assert 111 not in telegram_bot._nombres


def test_borrar_otra_conversacion_no_toca_la_abierta(monkeypatch, conversaciones_falsas):
    """Caso de control del anterior: borrar una charla vieja no debe cerrar
    la que estas teniendo ahora."""
    abierta = conversaciones_falsas[1]
    otra = conversaciones_falsas[0]
    telegram_bot._rutas[111] = abierta
    monkeypatch.setattr(telegram_bot, "_borrar_del_todo", lambda r: True)

    asyncio.run(telegram_bot.manejar_boton(_update_boton(f"bc:{otra.name}"), _context()))

    assert telegram_bot._rutas[111] == abierta


def test_borrar_sin_conversaciones_lo_dice(monkeypatch):
    monkeypatch.setattr(telegram_bot, "listar_conversaciones", lambda: [])
    enviados = []

    asyncio.run(telegram_bot.cmd_borrar(_update(enviados=enviados), _context()))

    assert "No hay ninguna" in " ".join(enviados)


# --- F5.5: /tools -> "ver sitios autorizados" (30/07) --------------------


def test_escapar_markdown_neutraliza_los_caracteres_especiales():
    """Un '_' sin escapar dentro de *negrita* abre una cursiva a medias y
    Telegram rechaza el MENSAJE ENTERO con un error de parseo. El titulo de
    cada grupo lo escribe Jordi libremente en el .env (el texto tras el
    "#"), asi que puede llevar cualquiera de estos caracteres sin querer."""
    sucio = "Nivel_1 *importante* con `codigo` y [link]"

    limpio = telegram_bot._escapar_markdown(sucio)

    for especial in ("_", "*", "`", "["):
        assert ("\\" + especial) in limpio
    # El texto en si no se pierde, solo se escapa.
    assert "Nivel" in limpio and "importante" in limpio


def test_escapar_markdown_no_toca_texto_sin_caracteres_especiales():
    normal = "Nivel 1: Organismos Oficiales"

    assert telegram_bot._escapar_markdown(normal) == normal


def test_ver_sitios_lista_los_dominios_agrupados(monkeypatch):
    # REGRESION (31/07): manejar_boton llama a _agente_de() antes de mirar
    # el boton pulsado, y eso lee la API key real del .env. En mi maquina
    # pasaba (tenia un .env real); en GitHub Actions, sin .env, revienta
    # antes de llegar a lo que este test de verdad comprueba. Mismo patron
    # que el resto del fichero (ver test_cada_usuario_tiene_su_propio_agente).
    monkeypatch.setattr(
        telegram_bot, "_configuracion_por_defecto", lambda: ("groq", "m", "k")
    )
    monkeypatch.setattr(
        "src.config.obtener_dominios_agrupados",
        lambda: {"Nivel 1: Oficial": ["nasa.gov", "esa.int"]},
    )
    editado = []

    boton = _update_boton(telegram_bot._VER_SITIOS, editado=editado)
    asyncio.run(telegram_bot.manejar_boton(boton, _context()))

    texto = " ".join(editado)
    assert "nasa.gov" in texto and "esa.int" in texto


def test_ver_sitios_escapa_un_titulo_con_guion_bajo(monkeypatch):
    """REGRESION: sin el escapado, un titulo con '_' habria roto el
    Markdown y Telegram habria devuelto un error en vez del mensaje."""
    monkeypatch.setattr(
        telegram_bot, "_configuracion_por_defecto", lambda: ("groq", "m", "k")
    )
    monkeypatch.setattr(
        "src.config.obtener_dominios_agrupados",
        lambda: {"Nivel_uno_importante": ["a.com"]},
    )
    editado = []

    boton = _update_boton(telegram_bot._VER_SITIOS, editado=editado)
    asyncio.run(telegram_bot.manejar_boton(boton, _context()))

    assert "Nivel\\_uno\\_importante" in " ".join(editado)


def test_ver_sitios_sin_ninguno_autorizado_lo_dice(monkeypatch):
    monkeypatch.setattr(
        telegram_bot, "_configuracion_por_defecto", lambda: ("groq", "m", "k")
    )
    monkeypatch.setattr("src.config.obtener_dominios_agrupados", lambda: {})
    editado = []

    boton = _update_boton(telegram_bot._VER_SITIOS, editado=editado)
    asyncio.run(telegram_bot.manejar_boton(boton, _context()))

    assert "No hay ningún sitio autorizado" in " ".join(editado)


# --- F5.5 #7: adjunto PDF/Word ("comando + adjunto", Jordi 31/07) --------
# El modelo NUNCA elige que fichero lee - lo maneja este handler, que solo
# valida y GUARDA en el Agente del usuario. No se prueba red real de
# Telegram: get_file()/download_as_bytearray() se sustituyen por
# funciones async de mentira, igual que send_chat_action en _context().


def _documento_falso(datos: bytes, nombre="informe.pdf"):
    async def download_as_bytearray():
        return bytearray(datos)

    async def get_file():
        return SimpleNamespace(download_as_bytearray=download_as_bytearray)

    return SimpleNamespace(file_name=nombre, get_file=get_file)


def _update_documento(user_id=111, datos=b"", nombre="informe.pdf", enviados=None):
    enviados = enviados if enviados is not None else []

    async def reply_text(texto_respuesta, *a, **kw):
        enviados.append(texto_respuesta)

    mensaje = SimpleNamespace(
        document=_documento_falso(datos, nombre), reply_text=reply_text,
        enviados=enviados,
        # Un mensaje real de Telegram SIEMPRE trae chat_id; el doble no lo
        # tenia y se noto el 01/08, al empezar a mandar "escribiendo..."
        # mientras se prepara el documento.
        chat_id=user_id,
    )
    usuario = SimpleNamespace(id=user_id, first_name="Jordi", username="Jordi")
    return SimpleNamespace(effective_user=usuario, effective_message=mensaje)


def test_un_pdf_valido_se_guarda_en_el_agente_del_usuario(monkeypatch):
    from tests.test_documentos import _pdf_con_texto

    monkeypatch.setattr(
        telegram_bot, "_configuracion_por_defecto", lambda: ("groq", "m", "k")
    )
    enviados = []
    update = _update_documento(
        datos=_pdf_con_texto("Hola"), nombre="informe.pdf", enviados=enviados
    )

    asyncio.run(telegram_bot.manejar_documento(update, _context()))

    agente = telegram_bot._agente_de(111)
    assert agente.documento_pendiente is not None
    assert agente.documento_pendiente.nombre == "informe.pdf"
    assert "recibido" in " ".join(enviados)


def test_un_fichero_no_pdf_ni_docx_se_rechaza_sin_guardarse():
    enviados = []
    update = _update_documento(datos=b"lo que sea", nombre="cancion.mp3", enviados=enviados)

    asyncio.run(telegram_bot.manejar_documento(update, _context()))

    assert 111 not in telegram_bot._agentes
    assert ".pdf o .docx" in " ".join(enviados)


def test_un_documento_sin_nombre_se_rechaza():
    """document.file_name puede venir vacio segun el cliente que lo mande
    - sin nombre no hay extension que validar."""
    enviados = []
    update = _update_documento(datos=b"x", nombre=None, enviados=enviados)

    asyncio.run(telegram_bot.manejar_documento(update, _context()))

    assert 111 not in telegram_bot._agentes
    assert "no tiene nombre" in " ".join(enviados)


def test_recibir_un_documento_NO_enciende_la_categoria_por_su_cuenta(monkeypatch):
    """Sutil pero importante: `documentos` arranca ENCENDIDA (decisión del
    31/07 — entregar el fichero ya es la autorización), pero eso es el
    DEFAULT, no algo que haga este handler.

    Si Jordi la apaga a propósito con /tools, mandar un adjunto NO debe
    volver a encenderla a su espalda: el handler guarda el fichero y avisa,
    nunca decide por él. Por eso se apaga a mano antes de la comprobación —
    si el handler la encendiera, este test se pondría rojo."""
    from tests.test_documentos import _pdf_con_texto

    monkeypatch.setattr(
        telegram_bot, "_configuracion_por_defecto", lambda: ("groq", "m", "k")
    )
    telegram_bot._agente_de(111).categorias_activas.discard("documentos")
    enviados = []
    update = _update_documento(datos=_pdf_con_texto("Hola"), enviados=enviados)

    asyncio.run(telegram_bot.manejar_documento(update, _context()))

    agente = telegram_bot._agente_de(111)
    assert "documentos" not in agente.categorias_activas
    # Y como está apagada, el aviso se lo dice en vez de encenderla solo.
    assert "documentos" in " ".join(enviados)


def test_un_docx_demasiado_grande_no_llega_a_guardarse(monkeypatch):
    import src.documentos as documentos

    monkeypatch.setattr(documentos, "_MAX_BYTES_ADJUNTO", 5)
    enviados = []
    update = _update_documento(datos=b"x" * 6, nombre="grande.pdf", enviados=enviados)

    asyncio.run(telegram_bot.manejar_documento(update, _context()))

    assert 111 not in telegram_bot._agentes
    assert "pesa demasiado" in " ".join(enviados)


@pytest.mark.requisito("RF-20")
@pytest.mark.control("E2-FICHEROS")
def test_R08_un_adjunto_que_Telegram_ya_dice_que_es_enorme_NI_se_descarga(monkeypatch):
    """R-08 (auditoria de seguridad de noviembre). El tope de 15 MB se
    miraba DESPUES de bajarse el fichero entero a memoria. Telegram dice el
    tamaño en el propio update (file_size): si ya pasa del tope, no hay
    nada que descargar. En una VPS con 1 GB de techo, eso es la diferencia
    entre rechazar y caerse."""
    import src.documentos as documentos

    descargas = []
    update = _update_documento(datos=b"%PDF", nombre="enorme.pdf")
    update.effective_message.document.file_size = documentos._MAX_BYTES_ADJUNTO + 1

    async def get_file():
        descargas.append(1)
        raise AssertionError("no deberia ni pedir el fichero")

    update.effective_message.document.get_file = get_file

    asyncio.run(telegram_bot.manejar_documento(update, _context()))

    assert descargas == []
    assert "pesa demasiado" in " ".join(update.effective_message.enviados)


def test_R08_validar_el_adjunto_NO_corre_en_el_bucle_de_eventos(monkeypatch):
    """validar_adjunto descomprime el .docx entero por bloques para medirlo
    (LOG-02): es CPU, y en el bucle de eventos congelaba el bot -incluida la
    puerta de acceso- mientras duraba. Mismo criterio que preparar() y
    Agente.preguntar: a un hilo."""
    import threading

    import src.documentos as documentos

    hilos = []

    def validar_espia(datos, nombre):
        hilos.append(threading.current_thread() is threading.main_thread())
        raise documentos.DocumentoNoValido("no vale")

    monkeypatch.setattr(documentos, "validar_adjunto", validar_espia)

    asyncio.run(telegram_bot.manejar_documento(_update_documento(datos=b"x"), _context()))

    assert hilos == [False]


def test_los_documentos_pasan_por_la_allowlist():
    """Mismo argumento que con los botones (ADR-005): manejar_documento
    esta en el mismo grupo 0 que el resto, y el grupo -1 con las dos
    puertas corre siempre antes - una via de entrada nueva no obliga a
    acordarse de protegerla."""
    aplicacion = telegram_bot.construir_aplicacion()
    grupo_puertas = min(aplicacion.handlers)

    grupos_con_documentos = [
        g for g, hs in aplicacion.handlers.items()
        if any(h.callback is telegram_bot.manejar_documento for h in hs)
    ]

    assert grupos_con_documentos and min(grupos_con_documentos) > grupo_puertas
