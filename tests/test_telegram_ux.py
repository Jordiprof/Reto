# UX del bot (31/07): los tres huecos que salieron probando en REAL, no
# leyendo el codigo, y un REDISEÑO sobre la marcha del propio menu (misma
# tarde) despues de que Jordi lo probara y no le convenciera.
#
#   1. /historial listaba pero no ABRIA ninguna conversacion. En la CLI si
#      (mostrar_conversacion), asi que era una asimetria - y de ahi salia la
#      impresion FALSA de que la memoria no se comparte entre CLI y bot.
#   2. /salir -> "guardar" no dejaba ponerle nombre.
#   3. /comandos era un muro de 14 lineas, y no habia menu nativo.
#
# El primer diseño de la #3 agrupaba los comandos en 4 "familias" con una
# pantalla intermedia por tema. Jordi, probandolo: no le gustaba, veia
# /recuerdo "repetido" (una vez en el menu nativo de Telegram, otra vez
# dentro del arbol) y prefiere UN SOLO NIVEL - /comandos lista TODOS de
# golpe y cada boton EJECUTA de verdad (abre el historial, enciende una
# tool...), no enseña un texto explicandolo. Ver el comentario de _CATALOGO
# en telegram_bot.py para el diseño final.
#
# Nada de esto lo habria encontrado un test: los tres "funcionaban".
import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import config, telegram_bot
from tests.test_telegram_seguridad import _context, _update, _update_boton


@pytest.fixture(autouse=True)
def estado_limpio(monkeypatch):
    for coleccion in (
        telegram_bot._agentes, telegram_bot._cerrojos, telegram_bot._marcas,
        telegram_bot._rutas, telegram_bot._nombres, telegram_bot._voz_activa,
        telegram_bot._esperando_texto,
    ):
        coleccion.clear()
    monkeypatch.setenv(config.TELEGRAM_PERMITIDOS_ENV, "111")
    monkeypatch.setenv(config.TELEGRAM_TOKEN_ENV, "123456:token-de-mentira")
    yield
    for coleccion in (
        telegram_bot._agentes, telegram_bot._cerrojos, telegram_bot._marcas,
        telegram_bot._rutas, telegram_bot._nombres, telegram_bot._voz_activa,
        telegram_bot._esperando_texto,
    ):
        coleccion.clear()


# --- 1. /historial ABRE una conversacion -----------------------------------


def _historial_falso(monkeypatch, nombre_fichero="2026-07-28_10-00-00.json"):
    ruta = Path(nombre_fichero)
    monkeypatch.setattr(telegram_bot, "listar_conversaciones", lambda: [ruta])
    monkeypatch.setattr(
        telegram_bot, "leer_metadatos",
        lambda r: {"fecha": "2026-07-28T10:00", "nombre": "chiste malo", "cifrado": True},
    )
    return ruta


def test_historial_ofrece_botones_para_abrir(monkeypatch):
    """La asimetria que Jordi encontro probando: en la CLI podia abrirlas y
    por Telegram no."""
    _historial_falso(monkeypatch)
    teclados = []

    asyncio.run(telegram_bot.cmd_historial(_update(teclados=teclados), _context()))

    datos = [b.callback_data for fila in teclados[0].inline_keyboard for b in fila]
    assert any(d.startswith(telegram_bot._PREFIJO_VER) for d in datos)


def test_abrir_una_conversacion_enseña_lo_que_se_dijo(monkeypatch):
    ruta = _historial_falso(monkeypatch)
    monkeypatch.setattr(telegram_bot, "_conversacion_valida", lambda n: ruta)
    monkeypatch.setattr(telegram_bot, "cargar_conversacion", lambda r: {
        "nombre": "chiste malo",
        "historial": [
            {"role": "system", "content": "ERES UN AGENTE - instrucciones internas"},
            {"role": "user", "content": "cuéntame un chiste"},
            {"role": "assistant", "content": "va un pingüino"},
        ],
    })
    enviados = []

    asyncio.run(telegram_bot.manejar_boton(
        _update_boton(f"{telegram_bot._PREFIJO_VER}{ruta.name}", enviados=enviados),
        _context(),
    ))

    dicho = " ".join(enviados)
    assert "cuéntame un chiste" in dicho and "va un pingüino" in dicho
    # El system prompt NO se enseña: no es parte de lo que se dijo, y ademas
    # sacaria las instrucciones internas por pantalla (igual que en la CLI).
    assert "instrucciones internas" not in dicho


def test_R05_abrir_una_conversacion_EN_CLARO_con_cifrado_activo_lo_dice(monkeypatch):
    """R-05: lo que storage marca como "en claro aunque hay clave" se enseña
    con un aviso delante. No se esconde (puede ser legitima, anterior a
    F5.3), pero tampoco se presenta igual que una cifrada."""
    ruta = _historial_falso(monkeypatch)
    monkeypatch.setattr(telegram_bot, "_conversacion_valida", lambda n: ruta)
    monkeypatch.setattr(telegram_bot, "cargar_conversacion", lambda r: {
        "nombre": "vieja", "aviso_sin_cifrar": True,
        "historial": [{"role": "system", "content": "s"}, {"role": "user", "content": "hola"}],
    })
    editado = []

    asyncio.run(telegram_bot.manejar_boton(
        _update_boton(f"{telegram_bot._PREFIJO_VER}{ruta.name}", editado=editado),
        _context(),
    ))

    assert "sin cifrar" in " ".join(editado).lower()


def test_abrir_una_conversacion_que_no_esta_en_la_lista_no_lee_nada(monkeypatch):
    """MISMA allowlist que /borrar: el nombre del fichero viaja a Telegram y
    vuelve. Leer es menos grave que borrar, pero "h:../../.env" escupiria la
    configuracion entera por el chat."""
    _historial_falso(monkeypatch)
    leidos = []
    monkeypatch.setattr(telegram_bot, "cargar_conversacion", lambda r: leidos.append(r))
    editado = []

    asyncio.run(telegram_bot.manejar_boton(
        _update_boton("h:../../.env", editado=editado), _context()
    ))

    assert leidos == []
    assert "ya no existe" in " ".join(editado)


def test_abrir_sin_la_clave_lo_dice_en_vez_de_reventar(monkeypatch):
    from src.storage import ConversacionNoDescifrable

    ruta = _historial_falso(monkeypatch)
    monkeypatch.setattr(telegram_bot, "_conversacion_valida", lambda n: ruta)

    def sin_clave(r):
        raise ConversacionNoDescifrable("falta CONVERSATIONS_KEY")

    monkeypatch.setattr(telegram_bot, "cargar_conversacion", sin_clave)
    editado = []

    asyncio.run(telegram_bot.manejar_boton(
        _update_boton(f"h:{ruta.name}", editado=editado), _context()
    ))

    assert "CONVERSATIONS_KEY" in " ".join(editado)


def test_abrir_una_conversacion_no_la_manda_al_llm(monkeypatch):
    """"Leer" y "retomar como contexto" son cosas distintas. Leer descifra y
    va a TU chat; retomar mandaria todo al proveedor del LLM en el turno
    siguiente. Hoy se hace lo primero, a proposito."""
    ruta = _historial_falso(monkeypatch)
    monkeypatch.setattr(telegram_bot, "_conversacion_valida", lambda n: ruta)
    monkeypatch.setattr(telegram_bot, "cargar_conversacion", lambda r: {
        "nombre": "x", "historial": [{"role": "system", "content": "s"},
                                     {"role": "user", "content": "hola"}],
    })

    def prohibido(uid):
        raise AssertionError("leer el historial no debe crear ningun Agente")

    monkeypatch.setattr(telegram_bot, "_agente_de", prohibido)

    asyncio.run(telegram_bot.manejar_boton(_update_boton(f"h:{ruta.name}"), _context()))

    assert 111 not in telegram_bot._agentes


# --- 2. /salir permite ponerle nombre --------------------------------------


def test_salir_ofrece_guardar_con_nombre():
    telegram_bot._rutas[111] = Path("abierta.json")
    teclados = []

    asyncio.run(telegram_bot.cmd_salir(_update(teclados=teclados), _context()))

    datos = [b.callback_data for fila in teclados[0].inline_keyboard for b in fila]
    assert telegram_bot._NOMBRAR in datos


def test_pedir_nombre_no_cierra_todavia_la_conversacion():
    """Si cerrara aqui, el nombre llegaria cuando ya no hay nada que
    nombrar."""
    telegram_bot._rutas[111] = Path("abierta.json")
    telegram_bot._agentes[111] = SimpleNamespace(historial=[1, 2])

    asyncio.run(telegram_bot.manejar_boton(_update_boton(telegram_bot._NOMBRAR), _context()))

    assert telegram_bot._esperando_texto.get(111) == "salir_nombrar"
    assert 111 in telegram_bot._rutas and 111 in telegram_bot._agentes


def test_el_mensaje_siguiente_se_usa_como_nombre_y_no_va_al_llm(monkeypatch):
    guardados = []
    monkeypatch.setattr(
        telegram_bot, "_persistir",
        lambda uid, nombre=None: guardados.append(nombre) or Path("guardada.json"),
    )

    def prohibido(uid):
        raise AssertionError("el nombre no es una pregunta para el LLM")

    monkeypatch.setattr(telegram_bot, "_agente_de", prohibido)
    telegram_bot._rutas[111] = Path("abierta.json")
    telegram_bot._esperando_texto[111] = "salir_nombrar"
    enviados = []

    asyncio.run(telegram_bot.manejar_mensaje(
        _update(texto="ideas de herramientas", enviados=enviados), _context()
    ))

    assert guardados == ["ideas de herramientas"]
    assert "ideas de herramientas" in " ".join(enviados)
    # Y la charla queda CERRADA: el mensaje siguiente estrena conversacion.
    assert 111 not in telegram_bot._rutas
    assert 111 not in telegram_bot._esperando_texto


def test_solo_se_come_UN_mensaje(monkeypatch):
    """El estado dura un mensaje. Si se quedara puesto, el bot dejaria de
    contestar y pareceria colgado."""
    monkeypatch.setattr(telegram_bot, "_persistir", lambda uid, nombre=None: Path("g.json"))
    monkeypatch.setattr(
        telegram_bot, "_agente_de",
        lambda uid: SimpleNamespace(preguntar=lambda t: f"respondo a {t}"),
    )
    telegram_bot._rutas[111] = Path("abierta.json")
    telegram_bot._esperando_texto[111] = "salir_nombrar"
    enviados = []

    primero = _update(texto="mi nombre", enviados=enviados)
    asyncio.run(telegram_bot.manejar_mensaje(primero, _context()))
    asyncio.run(telegram_bot.manejar_mensaje(_update(texto="hola", enviados=enviados), _context()))

    assert "respondo a hola" in enviados


def test_si_guardar_falla_el_estado_se_suelta_igual(monkeypatch):
    """El pop() ANTES de llamar a la accion: dejarlo puesto convertiria un
    fallo de guardado en un bot que se come todos los mensajes siguientes."""
    def revienta(update, texto):
        raise OSError("disco lleno")

    monkeypatch.setattr(telegram_bot, "_cerrar_con_nombre", revienta)
    telegram_bot._rutas[111] = Path("abierta.json")
    telegram_bot._esperando_texto[111] = "salir_nombrar"

    with pytest.raises(OSError):
        asyncio.run(telegram_bot.manejar_mensaje(_update(texto="un nombre"), _context()))

    assert 111 not in telegram_bot._esperando_texto


def test_un_nombre_vacio_no_cierra_nada(monkeypatch):
    guardados = []
    monkeypatch.setattr(
        telegram_bot, "_persistir", lambda uid, nombre=None: guardados.append(nombre)
    )
    telegram_bot._rutas[111] = Path("abierta.json")
    telegram_bot._esperando_texto[111] = "salir_nombrar"

    asyncio.run(telegram_bot.manejar_mensaje(_update(texto="    "), _context()))

    assert guardados == []
    assert 111 in telegram_bot._rutas  # sigue abierta


def test_el_nombre_se_acota(monkeypatch):
    """Va EN CLARO a los metadatos (por eso /historial lista sin descifrar) y
    ademas consultar_historial mete los titulos en el contexto del modelo."""
    guardados = []
    monkeypatch.setattr(
        telegram_bot, "_persistir",
        lambda uid, nombre=None: guardados.append(nombre) or Path("g.json"),
    )
    telegram_bot._rutas[111] = Path("abierta.json")
    telegram_bot._esperando_texto[111] = "salir_nombrar"

    asyncio.run(telegram_bot.manejar_mensaje(_update(texto="x" * 300), _context()))

    assert len(guardados[0]) <= telegram_bot._MAX_NOMBRE


# --- 3. /comandos plano: un boton, una accion real --------------------------


def test_la_ayuda_explica_en_el_cuerpo_y_actua_con_los_botones():
    """Este test CAMBIO el 01/08 y merece explicacion, porque su version
    anterior exigia lo contrario ("la ayuda debe ser corta, no un muro").

    El problema original (31/07) no era la longitud: era que 14 lineas de
    texto no dejaban HACER nada. Al arreglarlo meti la descripcion DENTRO
    de cada boton, y probandolo Jordi vio las dos consecuencias: Telegram
    **centra** el texto de un boton y lo **recorta** si no cabe.

    O sea que ninguno de los dos sitios sirve para las dos cosas: el cuerpo
    del mensaje explica (izquierda, completo, multilinea) y los botones
    actuan. La ayuda ahora usa cada uno para lo suyo, y por eso volver a
    exigir "que sea corta" seria volver al recorte."""
    enviados, teclados = [], []

    asyncio.run(telegram_bot.cmd_ayuda(_update(enviados=enviados, teclados=teclados), _context()))

    # La explicacion COMPLETA de cada comando, en el cuerpo y sin recortar.
    for nombre, descripcion, _tipo in telegram_bot._CATALOGO:
        assert f"/{nombre}" in enviados[0]
        assert descripcion in enviados[0], f"la descripcion de /{nombre} sale recortada"
    assert teclados[0] is not None


def test_las_etiquetas_de_los_botones_no_las_recorta_telegram():
    """Un boton con texto largo lo recorta el CLIENTE de Telegram, y no hay
    forma de evitarlo desde aqui: la unica defensa es que quepa. Con solo
    "/comando" cabe siempre."""
    teclados = []

    asyncio.run(telegram_bot.cmd_ayuda(_update(teclados=teclados), _context()))

    for fila in teclados[0].inline_keyboard:
        for boton in fila:
            assert len(boton.text) <= 20, f"'{boton.text}' es largo y se va a recortar"


def test_el_menu_tiene_un_boton_por_comando_sin_pantalla_intermedia():
    """Rediseño del 31/07: Jordi no queria una capa de "familias" con texto
    explicativo - queria TODOS los comandos a un toque, ejecutando."""
    teclados = []

    asyncio.run(telegram_bot.cmd_ayuda(_update(teclados=teclados), _context()))

    datos = {b.callback_data for fila in teclados[0].inline_keyboard for b in fila}
    for nombre, _descripcion, _tipo in telegram_bot._CATALOGO:
        assert f"{telegram_bot._PREFIJO_MENU}{nombre}" in datos


def test_tocar_historial_desde_el_menu_ejecuta_historial_de_verdad(monkeypatch):
    """No enseña un texto diciendo "para ver el historial usa /historial":
    LO EJECUTA, en el mismo toque."""
    _historial_falso(monkeypatch)
    enviados, teclados = [], []

    asyncio.run(telegram_bot.manejar_boton(
        _update_boton(f"{telegram_bot._PREFIJO_MENU}historial",
                      enviados=enviados, teclados=teclados),
        _context(),
    ))

    assert "conversaciones" in " ".join(enviados).lower()
    datos = [b.callback_data for fila in teclados[0].inline_keyboard for b in fila]
    assert any(d.startswith(telegram_bot._PREFIJO_VER) for d in datos)


def test_tocar_tools_desde_el_menu_enseña_las_activadas(monkeypatch):
    """Jordi: "cuando pulse herramientas dentro de comandos me salgan todas
    las que estan activadas"."""
    from src.tools import categorias_por_defecto

    monkeypatch.setattr(
        telegram_bot, "_agente_de",
        lambda uid: SimpleNamespace(categorias_activas=set(categorias_por_defecto())),
    )
    teclados = []

    asyncio.run(telegram_bot.manejar_boton(
        _update_boton(f"{telegram_bot._PREFIJO_MENU}tools", teclados=teclados), _context()
    ))

    etiquetas = " ".join(
        b.text for fila in teclados[0].inline_keyboard for b in fila
    )
    # Al menos una categoria por defecto sale marcada como encendida (✅).
    assert "✅" in etiquetas


def test_tocar_voz_desde_el_menu_enseña_los_dos_interruptores():
    teclados = []

    asyncio.run(telegram_bot.manejar_boton(
        _update_boton(f"{telegram_bot._PREFIJO_MENU}voz", teclados=teclados), _context()
    ))

    datos = [b.callback_data for fila in teclados[0].inline_keyboard for b in fila]
    assert any(d.startswith(telegram_bot._PREFIJO_VOZ) for d in datos)


def test_tocar_documento_solo_explica_no_es_un_comando_real():
    """"documento" es la unica entrada "info" del catalogo: el adjunto YA es
    la orden, no hay nada que "ejecutar"."""
    editado = []

    asyncio.run(telegram_bot.manejar_boton(
        _update_boton(f"{telegram_bot._PREFIJO_MENU}documento", editado=editado), _context()
    ))

    assert "adjunto" in " ".join(editado).lower()


def test_tocar_recuerdo_pide_la_busqueda_y_no_ejecuta_todavia(monkeypatch):
    buscado = []
    monkeypatch.setattr(telegram_bot, "_ejecutar_recuerdo", lambda m, c: buscado.append(c))
    editado = []

    asyncio.run(telegram_bot.manejar_boton(
        _update_boton(f"{telegram_bot._PREFIJO_MENU}recuerdo", editado=editado), _context()
    ))

    assert buscado == []
    assert telegram_bot._esperando_texto.get(111) == "recuerdo"
    assert "busco" in " ".join(editado).lower() or "búsqueda" in " ".join(editado).lower()


def test_el_mensaje_siguiente_a_recuerdo_dispara_la_busqueda(monkeypatch):
    buscado = []

    async def _recuerdo_falso(mensaje, consulta):
        buscado.append(consulta)

    monkeypatch.setattr(telegram_bot, "_ejecutar_recuerdo", _recuerdo_falso)

    def prohibido(uid):
        raise AssertionError("una busqueda en memoria no es una pregunta para el LLM")

    monkeypatch.setattr(telegram_bot, "_agente_de", prohibido)
    telegram_bot._esperando_texto[111] = "recuerdo"

    asyncio.run(telegram_bot.manejar_mensaje(_update(texto="el chiste del plato"), _context()))

    assert buscado == ["el chiste del plato"]
    assert 111 not in telegram_bot._esperando_texto


def test_tocar_guardar_pide_el_nombre_y_no_ejecuta_todavia(monkeypatch):
    guardados = []
    monkeypatch.setattr(telegram_bot, "_ejecutar_guardar", lambda uid, m, n: guardados.append(n))
    editado = []

    asyncio.run(telegram_bot.manejar_boton(
        _update_boton(f"{telegram_bot._PREFIJO_MENU}guardar", editado=editado), _context()
    ))

    assert guardados == []
    assert telegram_bot._esperando_texto.get(111) == "guardar"


def test_el_mensaje_siguiente_a_guardar_dispara_el_guardado(monkeypatch):
    guardados = []

    async def _guardar_falso(uid, mensaje, nombre):
        guardados.append((uid, nombre))

    monkeypatch.setattr(telegram_bot, "_ejecutar_guardar", _guardar_falso)
    telegram_bot._esperando_texto[111] = "guardar"

    asyncio.run(telegram_bot.manejar_mensaje(_update(texto="ideas sueltas"), _context()))

    assert guardados == [(111, "ideas sueltas")]
    assert 111 not in telegram_bot._esperando_texto


def test_una_entrada_de_menu_inventada_se_rechaza():
    """callback_data = dato NO confiable. Sin validar contra el catalogo
    real, un boton fabricado a mano provocaria un KeyError."""
    editado = []

    asyncio.run(telegram_bot.manejar_boton(
        _update_boton(f"{telegram_bot._PREFIJO_MENU}no-existe", editado=editado), _context()
    ))

    assert "ya no existe" in " ".join(editado)


def test_toda_entrada_directo_tiene_su_accion_y_viceversa():
    """Invariante: si se añade un comando "directo" al catalogo y se olvida
    _ACCIONES_DIRECTAS, el boton petaria con KeyError la primera vez que
    alguien lo pulsara. Mejor que lo diga un test."""
    directos = {n for n, _d, t in telegram_bot._CATALOGO if t == "directo"}
    assert directos == set(telegram_bot._ACCIONES_DIRECTAS)


def test_el_menu_nativo_sale_del_mismo_catalogo_que_los_botones():
    """UNA fuente de verdad: si mañana se añade un comando a _CATALOGO,
    aparece en los dos sitios sin tocar nada mas."""
    publicados = {c.command for c in telegram_bot.comandos_para_telegram()}

    del_catalogo = {
        nombre for nombre, _d, tipo in telegram_bot._CATALOGO if tipo != "info"
    }

    assert del_catalogo <= publicados


def test_documento_no_se_publica_como_comando_del_bot():
    """"documento" es "info", no un comando real - Telegram no debe
    anunciar algo que el bot no atiende (se veria en el menu, se pulsaria y
    no pasaria nada)."""
    publicados = {c.command for c in telegram_bot.comandos_para_telegram()}

    assert "documento" not in publicados


def test_todos_los_comandos_publicados_existen_de_verdad():
    """Que Telegram anuncie un comando que el bot no atiende es peor que no
    anunciarlo: se ve en el menu, se pulsa y no pasa nada."""
    aplicacion = telegram_bot.construir_aplicacion()
    registrados = set()
    for handlers in aplicacion.handlers.values():
        for handler in handlers:
            registrados |= {c.lower() for c in getattr(handler, "commands", None) or []}

    for comando in telegram_bot.comandos_para_telegram():
        assert comando.command in registrados, f"/{comando.command} se anuncia y no existe"


def test_las_descripciones_caben_en_telegram():
    """Telegram rechaza la lista ENTERA si una descripcion pasa de 256."""
    for comando in telegram_bot.comandos_para_telegram():
        assert 1 <= len(comando.description) <= 256
        assert 1 <= len(comando.command) <= 32


def test_publicar_comandos_no_tumba_el_arranque(caplog):
    """Quedarse sin bot por no poder pintar un menu seria cambiar algo
    importante por algo cosmetico."""
    class _BotRoto:
        async def set_my_commands(self, comandos):
            raise RuntimeError("Telegram no contesta")

    aplicacion = SimpleNamespace(bot=_BotRoto())

    with caplog.at_level("WARNING"):
        asyncio.run(telegram_bot._publicar_comandos(aplicacion))

    assert "RuntimeError" in caplog.text


def _sin_escapes(texto: str) -> str:
    """Quita cada caracter que va precedido de "\\": un "\\_" no cuenta
    para el balance de cursivas, porque Telegram lo lee como un guion bajo
    LITERAL (es la escapada que documenta su propia API para "_", "*",
    "`" y "["), no como delimitador. Sin esto el contador de parejas
    marcaba como roto un texto que en realidad estaba bien escapado."""
    return re.sub(r"\\.", "", texto)


def test_ningun_texto_del_menu_usa_markdown_invalido(monkeypatch):
    """En el Markdown "legacy" de Telegram la negrita es *asi*, nunca
    **asi** (eso es MarkdownV2). Un `**` o un * desparejado hace que
    Telegram RECHACE EL MENSAJE ENTERO - es el fallo real del 30/07 con los
    titulos de los dominios, aqui blindado para los textos nuevos.

    BUG REAL, ENCONTRADO POR EL CI (14/08), en DOS capas a la vez:

    1. El contador estaba MAL: contaba TODOS los "_", tambien los que ya
       iban escapados como "\\_" (que son seguros: Telegram los lee tal
       cual, no como cursiva). _texto_voz() escapa el mensaje de
       motivo_no_disponible() con _escapar_markdown, y ese mensaje real
       ("...download_voices es_ES-davefx-medium...") tiene TRES guiones
       bajos - impar, y aun asi el texto final era valido porque los tres
       estaban escapados. El test lo marcaba roto sin estarlo.

    2. Y aun con el contador bien, el texto que se comprobaba dependia de
       si la maquina que ejecuta el test tiene la voz de Piper descargada:
       en la de Jordi si, asi que motivo_no_disponible() devuelve None y
       esa rama JAMAS se ejercitaba en local - solo en una maquina limpia
       como el runner de GitHub. Se fuerza aqui a proposito, para que el
       caso que de verdad rompio se compruebe siempre, en cualquier
       maquina."""
    monkeypatch.setattr(
        "src.voz.motivo_no_disponible",
        lambda: (
            "falta la voz de Piper (es_ES-davefx-medium.onnx). Descárgala con:\n"
            "venv\\Scripts\\python.exe -m piper.download_voices "
            "es_ES-davefx-medium --data-dir voces"
        ),
    )

    textos = {"_INFO_DOCUMENTO": telegram_bot._INFO_DOCUMENTO}
    textos.update(telegram_bot._PETICIONES_TEXTO)
    textos["voz"] = telegram_bot._texto_voz(111)
    textos["comandos"] = telegram_bot._texto_comandos()

    for nombre, texto in textos.items():
        limpio = _sin_escapes(texto)
        assert "**" not in texto, f"{nombre} usa ** (no existe en Markdown legacy)"
        assert limpio.count("*") % 2 == 0, f"{nombre} tiene un * desparejado"
        assert limpio.count("_") % 2 == 0, f"{nombre} tiene un _ SIN ESCAPAR desparejado"


# --- Regresion: el estado pendiente y las DOS puertas de entrada -----------
# BUG REAL del 01/08, encontrado por Jordi probando el bot entero de una
# sentada. La comprobacion de _esperando_texto vivia en manejar_mensaje, que
# solo cubre el camino ESCRITO. Secuencia que lo destapo:
#   1. pulsa el boton /recuerdo -> "dime que busco"
#   2. contesta con una NOTA DE VOZ -> manejar_voz llama directo a _turno y
#      se salta la comprobacion; el estado se queda puesto Y YA NO SE VA
#   3. varios turnos despues, su siguiente mensaje ESCRITO ("metete en esta
#      web y resumemela") se lo come /recuerdo en vez de contestarlo
# El arreglo mueve la comprobacion al EMBUDO (_turno), por donde pasan las
# dos puertas.


def _update_voz_min(user_id=111, enviados=None):
    """Update con nota de voz, minimo para estos tests (el completo esta en
    test_telegram_voz.py)."""
    enviados = enviados if enviados is not None else []

    async def reply_text(t, *a, **kw):
        enviados.append(t)

    async def download_as_bytearray():
        return bytearray(b"OggS-audio")

    async def get_file():
        return SimpleNamespace(download_as_bytearray=download_as_bytearray)

    mensaje = SimpleNamespace(
        voice=SimpleNamespace(duration=5, get_file=get_file), text=None,
        chat_id=user_id, reply_text=reply_text, enviados=enviados,
    )
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id, first_name="J", username="J"),
        effective_message=mensaje,
    )


def test_contestar_por_VOZ_a_una_peticion_de_texto_tambien_la_consume(monkeypatch):
    """El bug tal cual: si la respuesta llega hablada en vez de escrita,
    tiene que valer igual - y sobre todo, el estado NO puede quedarse
    puesto."""
    import src.voz as voz

    buscado = []

    async def _recuerdo_falso(mensaje, consulta):
        buscado.append(consulta)

    monkeypatch.setattr(telegram_bot, "_ejecutar_recuerdo", _recuerdo_falso)
    monkeypatch.setattr(voz, "validar_duracion", lambda d: None)
    monkeypatch.setattr(voz, "transcribir", lambda datos: "el chiste del plato")
    telegram_bot._voz_activa[111] = {"escuchar"}
    telegram_bot._esperando_texto[111] = "recuerdo"

    asyncio.run(telegram_bot.manejar_voz(_update_voz_min(), _context()))

    assert buscado == ["el chiste del plato"]
    assert 111 not in telegram_bot._esperando_texto


def test_el_estado_pendiente_no_sobrevive_a_una_nota_de_voz(monkeypatch):
    """La consecuencia que de verdad dolio: el estado sobrevivia a la nota
    de voz y varios turnos despues se comia un mensaje normal."""
    import src.voz as voz

    monkeypatch.setattr(voz, "validar_duracion", lambda d: None)
    monkeypatch.setattr(voz, "transcribir", lambda datos: "lo que sea")
    monkeypatch.setattr(telegram_bot, "_ejecutar_recuerdo", _noop_async)
    telegram_bot._voz_activa[111] = {"escuchar"}
    telegram_bot._esperando_texto[111] = "recuerdo"

    asyncio.run(telegram_bot.manejar_voz(_update_voz_min(), _context()))

    # Y ahora un mensaje ESCRITO normal debe ir al LLM, no a la busqueda.
    monkeypatch.setattr(
        telegram_bot, "_agente_de",
        lambda uid: SimpleNamespace(preguntar=lambda t: f"respondo a {t}"),
    )
    monkeypatch.setattr(telegram_bot, "_persistir", lambda uid, nombre=None: None)
    enviados = []

    asyncio.run(telegram_bot.manejar_mensaje(
        _update(texto="metete en esta web y resumemela", enviados=enviados), _context()
    ))

    assert "respondo a metete en esta web y resumemela" in enviados


async def _noop_async(*a, **kw):
    return None


def test_un_comando_cancela_de_verdad_la_peticion_pendiente():
    """La interfaz PROMETE que cualquier comando cancela ("y no toco
    nada"). Antes era mentira: los CommandHandler no pasan por _turno, asi
    que el estado seguia puesto y se comia el mensaje siguiente."""
    telegram_bot._esperando_texto[111] = "recuerdo"

    asyncio.run(telegram_bot.puerta_soltar_espera(_update(texto="/ayuda"), _context()))

    assert 111 not in telegram_bot._esperando_texto


def test_un_mensaje_normal_no_cancela_la_peticion_pendiente():
    """La otra mitad: solo los COMANDOS cancelan. Un mensaje normal es la
    respuesta que estabamos esperando, no una cancelacion."""
    telegram_bot._esperando_texto[111] = "recuerdo"

    asyncio.run(telegram_bot.puerta_soltar_espera(_update(texto="el chiste"), _context()))

    assert telegram_bot._esperando_texto.get(111) == "recuerdo"


def test_la_puerta_de_soltar_espera_esta_registrada_tras_la_allowlist():
    """Va en el grupo -1 y DESPUES de la allowlist: un desconocido no debe
    poder tocar ni este diccionario."""
    aplicacion = telegram_bot.construir_aplicacion()
    callbacks = [h.callback for h in aplicacion.handlers[-1]]

    assert telegram_bot.puerta_soltar_espera in callbacks
    assert callbacks.index(telegram_bot.puerta_allowlist) < callbacks.index(
        telegram_bot.puerta_soltar_espera
    )


def test_en_telegram_el_comando_se_llama_cerrar_no_salir():
    """La divergencia anotada el 28/07, cerrada el 01/08.

    "/salir" significaba dos cosas segun donde lo escribieras: en la CLI
    termina el PROGRAMA, en Telegram solo cierra la conversacion y el bot
    sigue vivo. Jordi lo probo, hizo /salir y se quedo esperando que el
    proceso se parara.

    NO se arregla haciendo que /salir apague el bot: entonces no habria
    forma de volver a encenderlo desde Telegram (habria que ir al PC). Un
    servicio no se apaga desde su propio chat. Lo que estaba mal era el
    nombre.
    """
    anunciados = {c.command for c in telegram_bot.comandos_para_telegram()}

    assert "cerrar" in anunciados
    assert "salir" not in anunciados, "en Telegram nada 'sale': el bot sigue vivo"


def test_salir_sigue_funcionando_como_alias_oculto():
    """No se borra: Jordi lleva dias escribiendolo y el bot no debe
    contestarle "no conozco ese comando" por un cambio de nombre nuestro."""
    aplicacion = telegram_bot.construir_aplicacion()
    registrados = set()
    for handlers in aplicacion.handlers.values():
        for handler in handlers:
            registrados |= {c.lower() for c in getattr(handler, "commands", None) or []}

    assert "salir" in registrados and "cerrar" in registrados


def test_en_la_CLI_salir_sigue_significando_terminar():
    """La otra mitad de la divergencia: en la terminal SI se sale del
    programa, y ahi el nombre es correcto. No se toca."""
    from src.main import COMANDOS

    assert "/salir" in COMANDOS
    assert "Terminar" in COMANDOS["/salir"]
