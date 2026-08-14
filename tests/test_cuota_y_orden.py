"""Los arreglos del 03/08 que salieron de leer el log de una sesion real de
pruebas de Jordi, no de ejecutar la suite (doctrina del proyecto: probar en
real siempre; aqui hasta el diagnostico salio del log).

Cubren tres cosas distintas que compartian una misma raiz -clasificar mal un
error hace que el router actue mal-:

  - la cuota DIARIA deja de ser reintentable (el codigo contradecia a su
    propio mensaje);
  - un fallo de RED de Ollama deja de matar el proveedor sin reintentar;
  - el orden de proveedores tiene UNA fuente de verdad, no tres copias.
"""

import httpx
import pytest

from src.config import PROVEEDORES
from src.llm_errors import ErrorConexion, ErrorLimitePeticiones
from src.llm_router import _ORDEN_ADR001, Eslabon, LLMRouter

# --- La cuota DIARIA no se reintenta -------------------------------------

# Textos reales tal y como los manda cada proveedor, no inventados por mi:
# es la leccion del 02/08 (marque como reintentables dos excepciones de
# Gemini que NO EXISTEN, y el test no lo cazo porque fabricaba clases falsas
# con esos nombres).
_POR_DIA = [
    "Rate limit reached for model `llama-3.3-70b-versatile` in organization "
    "`org_x` service tier `on_demand` on tokens per day (TPD): Limit 100000, "
    "Used 99876, Requested 500.",
    "Limit exceeded on requests per day (RPD)",
]
_POR_MINUTO = [
    "Rate limit reached ... on tokens per minute (TPM): Limit 12000",
    "Limit exceeded on requests per minute (RPM)",
]


@pytest.mark.parametrize("detalle", _POR_DIA)
def test_la_cuota_diaria_NO_es_reintentable(detalle):
    """Esperar no la arregla, asi que reintentar solo tira llamadas.

    Es el bug del 03/08: el mensaje decia "esto no se arregla esperando un
    rato" y el router, acto seguido, esperaba y reintentaba tres veces."""
    error = ErrorLimitePeticiones("groq", detalle)
    assert error.es_diario
    assert error.reintentable is False


@pytest.mark.parametrize("detalle", _POR_MINUTO)
def test_la_cuota_por_minuto_SI_es_reintentable(detalle):
    """Se recupera sola en menos de un minuto: reintentar es justo lo que
    hay que hacer."""
    error = ErrorLimitePeticiones("groq", detalle)
    assert error.es_diario is False
    assert error.reintentable is True


def test_sin_detalle_se_reintenta_como_siempre():
    """Si no sabemos que limite es, se reintenta. Fallar hacia el
    comportamiento de antes, nunca hacia el nuevo."""
    assert ErrorLimitePeticiones("groq").reintentable is True


def test_el_mensaje_y_la_decision_NO_pueden_discrepar():
    """El invariante que faltaba y que causo el bug: si el aviso dice
    "DIARIA", el router NO puede reintentar; y al reves.

    Los dos beben de `es_diario` a proposito - antes eran dos lecturas
    separadas del mismo texto y se separaron."""
    for detalle in _POR_DIA + _POR_MINUTO + ["algo que no reconocemos"]:
        error = ErrorLimitePeticiones("groq", detalle)
        dice_diaria = "DIARIA" in error.mensaje_usuario
        assert dice_diaria is (not error.reintentable), detalle


def test_el_router_NO_gasta_reintentos_con_la_cuota_diaria():
    """La prueba de que el arreglo llega hasta donde duele.

    Medido en el log del 03/08: quince mensajes seguidos, tres llamadas
    tiradas en cada uno a un proveedor ya muerto. Aqui se comprueba que hoy
    es UNA llamada y se pasa al siguiente."""
    intentos = []

    def _falla_groq_responde_ollama(eslabon, historial, tools, turno):
        intentos.append(eslabon.proveedor)
        if eslabon.proveedor == "groq":
            raise ErrorLimitePeticiones("groq", _POR_DIA[0])
        return "respuesta de ollama"

    dormidas = []
    router = LLMRouter(
        [Eslabon("groq", "k", "m"), Eslabon("ollama", "k", "m")],
        _dormir=dormidas.append, _llamar=_falla_groq_responde_ollama,
    )

    assert router.responder([{"rol": "usuario", "texto": "hola"}], None) == "respuesta de ollama"
    assert intentos == ["groq", "ollama"], "groq se probo mas de una vez"
    assert dormidas == [], "no se espera por una cuota que no se recupera hoy"


def test_con_cuota_POR_MINUTO_el_router_SI_reintenta():
    """El contraste que hace util al test de arriba: mismo camino, mismo
    proveedor, y la unica diferencia es el texto del limite."""
    intentos = []

    def _siempre_por_minuto(eslabon, historial, tools, turno):
        intentos.append(eslabon.proveedor)
        if eslabon.proveedor == "groq":
            raise ErrorLimitePeticiones("groq", _POR_MINUTO[0])
        return "ok"

    dormidas = []
    router = LLMRouter(
        [Eslabon("groq", "k", "m"), Eslabon("ollama", "k", "m")],
        _dormir=dormidas.append, _llamar=_siempre_por_minuto,
    )

    router.responder([{"rol": "usuario", "texto": "hola"}], None)
    assert intentos.count("groq") == 3, "deberia reintentar 2 veces + la primera"
    assert dormidas == [1.0, 2.0]


# --- Un fallo de red de Ollama es reintentable ---------------------------


@pytest.mark.parametrize("error_red", [
    httpx.ConnectError("connection refused"),
    ConnectionError("connection aborted"),
])
def test_ollama_sin_red_degrada_pero_REINTENTANDO(error_red, monkeypatch):
    """Salio del log del 03/08: "Ollama: error (ConnectionError)" se
    tipaba como ErrorPeticionInvalida -no reintentable- y el proveedor
    moria a la primera. Un cable que se cae no es una peticion invalida:
    no hay codigo HTTP porque la peticion no llego a viajar."""
    from src.llm_client import _ProveedorOllama

    proveedor = _ProveedorOllama("clave", "gpt-oss:120b")

    class _ClienteQueNoConecta:
        def chat(self, **kwargs):
            raise error_red

    estado = {"client": _ClienteQueNoConecta(), "mensajes": [], "tools": None}
    with pytest.raises(ErrorConexion) as capturado:
        proveedor._llamar(estado)
    assert capturado.value.reintentable is True


def test_ollama_429_se_tipa_como_LIMITE_y_no_como_red():
    """Un 429 es una cuota, y hay que tiparlo como tal para que la
    distincion por-minuto/por-dia valga tambien aqui y no solo en Groq."""
    from src.llm_client import _ProveedorOllama

    class _Error429(Exception):
        status_code = 429

    class _ClienteSinCuota:
        def chat(self, **kwargs):
            raise _Error429("on requests per day (RPD)")

    proveedor = _ProveedorOllama("clave", "gpt-oss:120b")
    estado = {"client": _ClienteSinCuota(), "mensajes": [], "tools": None}
    with pytest.raises(ErrorLimitePeticiones) as capturado:
        proveedor._llamar(estado)
    assert capturado.value.reintentable is False, "es la cuota del dia"


# --- Una sola fuente de verdad para el orden -----------------------------


def test_el_orden_del_router_SALE_de_config_PROVEEDORES():
    """Invariante, no gusto. Antes "groq primero" estaba escrito a mano en
    tres sitios -el menu de la CLI, el arranque del bot y la cadena del
    router- y cambiar la preferencia obligaba a acordarse de los tres.

    Este test es lo que impide que vuelvan a separarse."""
    assert _ORDEN_ADR001 == list(PROVEEDORES)


def test_el_bot_arranca_con_el_MISMO_proveedor_que_la_CLI(monkeypatch):
    """La divergencia silenciosa que este arreglo cierra: si el bot se
    quedara con el proveedor viejo, los dos canales usarian modelos
    distintos sin que nada lo dijera. Misma familia que la de /salir.

    BUG DEL TEST, no del codigo (14/08, encontrado por el CI): faltaba este
    monkeypatch, asi que el test solo pasaba si el .env REAL de quien lo
    ejecuta tenia OLLAMA_API_KEY puesta - en la maquina de Jordi, siempre;
    en el runner de GitHub, que no tiene .env, nunca. El CI llevaba dias sin
    poder instalar (ver requirements-lock.txt) y este fallo estaba
    escondido detras de aquel: en cuanto se arreglo la instalacion, salio
    este. Reproducido en local moviendo el .env aparte antes del arreglo."""
    from src.telegram_bot import _configuracion_por_defecto

    primero_de_la_cadena = _ORDEN_ADR001[0]
    monkeypatch.setenv(PROVEEDORES[primero_de_la_cadena], "clave-de-prueba")

    assert _configuracion_por_defecto()[0] == primero_de_la_cadena


def test_ollama_es_hoy_el_primero():
    """La decision del 03/08 en si, escrita para que cambiarla sea un acto
    consciente y no un descuido. El porque (cuota diaria de Groq agotada en
    ~20 mensajes con un documento cargado, y llama-3.3 reescribiendo
    fechas) esta en el comentario de _ORDEN_ADR001."""
    assert _ORDEN_ADR001[0] == "ollama"


# --- Modelo de RESERVA dentro del mismo proveedor (03/08, idea de Jordi) --


def test_groq_degrada_a_OTRO_MODELO_SUYO_antes_de_cambiar_de_proveedor():
    """En Groq el cupo es POR MODELO. Verificado contra la API real con las
    cabeceras x-ratelimit-*: cuatro llamadas solo a llama-3.3 dejaron su
    contador en 993/10.969 y el de gpt-oss-120b INTACTO en 997/7.920.

    O sea que quedarse sin llama-3.3 no deja sin gpt-oss-120b, y saltar de
    proveedor sin probarlo antes es tirar cuota que si tenemos. Ademas
    gpt-oss-120b tiene el DOBLE de cuota diaria (200.000 contra 100.000)."""
    from src.llm_router import construir_cadena

    router = construir_cadena("groq", "clave", "llama-3.3-70b-versatile")
    primeros = [(e.proveedor, e.modelo) for e in router.eslabones[:2]]

    assert primeros[0] == ("groq", "llama-3.3-70b-versatile")
    assert primeros[1] == ("groq", "openai/gpt-oss-120b"), (
        "antes de cambiar de proveedor hay que agotar los modelos de Groq"
    )


def test_la_reserva_NO_se_duplica_si_ya_es_el_modelo_en_uso():
    """Si JIM ya eligio gpt-oss-120b a mano, no puede aparecer dos veces en
    la cadena: seria un reintento disfrazado de fallback."""
    from src.llm_router import construir_cadena

    router = construir_cadena("groq", "clave", "openai/gpt-oss-120b")
    de_groq = [e.modelo for e in router.eslabones if e.proveedor == "groq"]

    assert de_groq.count("openai/gpt-oss-120b") == 1, "aparece dos veces"
    assert de_groq[0] == "openai/gpt-oss-120b", "el elegido a mano va primero"
    # Las OTRAS reservas siguen detrás: quitarse a sí mismo de la lista no
    # puede llevarse por delante a las demás.
    assert "qwen/qwen3.6-27b" in de_groq


def test_la_reserva_SE_SALTA_si_el_fallo_no_es_de_cuota():
    """Cambiar de modelo solo salva de una cuota agotada. Con una clave
    mala el modelo siguiente del mismo proveedor fallaria igual, y probarlo
    es una llamada tirada - justo lo que SEG-03 vino a evitar."""
    from src.llm_errors import ErrorAutenticacion

    intentos = []

    def _clave_mala_en_groq(eslabon, historial, tools, turno):
        intentos.append((eslabon.proveedor, eslabon.modelo))
        if eslabon.proveedor == "groq":
            raise ErrorAutenticacion("groq", "clave invalida")
        return "responde ollama"

    router = LLMRouter(
        [
            Eslabon("groq", "k", "llama-3.3-70b-versatile"),
            Eslabon("groq", "k", "openai/gpt-oss-120b"),
            Eslabon("ollama", "k", "gpt-oss:120b"),
        ],
        _dormir=lambda s: None, _llamar=_clave_mala_en_groq,
    )

    router.responder([{"rol": "usuario", "texto": "hola"}], None)
    assert intentos == [
        ("groq", "llama-3.3-70b-versatile"),
        ("ollama", "gpt-oss:120b"),
    ], "la reserva de groq no debia probarse"


def test_la_reserva_SI_se_prueba_si_el_fallo_ES_de_cuota():
    """El contraste: mismo camino, y lo unico que cambia es el tipo de
    error. Aqui la reserva es exactamente lo que hay que probar."""
    intentos = []

    def _sin_cuota_en_llama(eslabon, historial, tools, turno):
        intentos.append((eslabon.proveedor, eslabon.modelo))
        if eslabon.modelo == "llama-3.3-70b-versatile":
            raise ErrorLimitePeticiones("groq", _POR_DIA[0])
        return "responde gpt-oss"

    router = LLMRouter(
        [
            Eslabon("groq", "k", "llama-3.3-70b-versatile"),
            Eslabon("groq", "k", "openai/gpt-oss-120b"),
            Eslabon("ollama", "k", "gpt-oss:120b"),
        ],
        _dormir=lambda s: None, _llamar=_sin_cuota_en_llama,
    )

    assert router.responder([{"rol": "usuario", "texto": "hola"}], None) == "responde gpt-oss"
    assert intentos == [
        ("groq", "llama-3.3-70b-versatile"),
        ("groq", "openai/gpt-oss-120b"),
    ], "no debia hacer falta salir de groq"


# --- El tope de documento depende del proveedor --------------------------


def test_groq_recibe_LA_MITAD_de_documento_que_los_demas():
    """El texto de un documento se queda en el historial y se REENVIA en
    cada turno (AUD-03), asi que es lo que mas gasta la cuota diaria. Groq
    da 100.000 tokens/dia: con 20.000 caracteres (~5.400 tokens) por turno
    la cuota se va en ~18 turnos, y con 10.000 dura el doble."""
    from src.tools import (
        _MAX_CARACTERES_DOCUMENTO,
        _tope_documento,
        fijar_proveedor_actual,
        restaurar_proveedor_actual,
    )

    token = fijar_proveedor_actual("groq")
    try:
        assert _tope_documento() == 10000
    finally:
        restaurar_proveedor_actual(token)

    for proveedor in ["ollama", "gemini"]:
        token = fijar_proveedor_actual(proveedor)
        try:
            assert _tope_documento() == _MAX_CARACTERES_DOCUMENTO, proveedor
        finally:
            restaurar_proveedor_actual(token)


def test_sin_proveedor_fijado_se_usa_el_tope_GENERAL():
    """Fallar hacia el comportamiento de siempre: si nadie lo fijo (un test
    suelto, una tool llamada a mano), el tope es el mas generoso."""
    from src.tools import _MAX_CARACTERES_DOCUMENTO, _tope_documento

    assert _tope_documento() == _MAX_CARACTERES_DOCUMENTO
