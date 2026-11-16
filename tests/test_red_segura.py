"""F5.5 #4 - Tests del guardian de URLs (SSRF).

Ninguno toca la red: se sustituye la resolucion DNS (`socket.getaddrinfo`)
por una tabla, asi que se puede probar "este dominio resuelve a 127.0.0.1"
sin montar un servidor ni depender de que exista ningun dominio real.

Es el control mas delicado de F5.5: es el unico que decide si una peticion
sale de la maquina hacia donde diga el modelo.
"""
import pytest

from src import config, red_segura
from src.red_segura import UrlNoPermitida, validar_url


@pytest.fixture(autouse=True)
def dns_falso(monkeypatch):
    """Resolucion DNS de mentira: todo lo que no este en la tabla resuelve
    a una IP publica cualquiera."""
    tabla = {
        "interno.ejemplo.com": "127.0.0.1",
        "router.ejemplo.com": "192.168.1.1",
        "cloud.ejemplo.com": "169.254.169.254",
        "varias.ejemplo.com": ["93.184.216.34", "10.0.0.5"],  # una publica, una interna
    }

    def getaddrinfo_falso(host, _puerto, *a, **kw):
        ips = tabla.get(host, "93.184.216.34")
        if isinstance(ips, str):
            ips = [ips]
        # Se imita la forma real: lo que importa es info[4][0].
        return [(2, 1, 6, "", (ip, 0)) for ip in ips]

    monkeypatch.setattr(red_segura.socket, "getaddrinfo", getaddrinfo_falso)


@pytest.fixture(autouse=True)
def lista_blanca(monkeypatch):
    """Lista blanca conocida para todos los tests."""
    monkeypatch.setenv(config.DOMINIOS_WEB_ENV, "ejemplo.com, otro.org")


# --- Lo que DEBE pasar -------------------------------------------------


def test_un_dominio_de_la_lista_pasa():
    assert validar_url("https://ejemplo.com/articulo") == "https://ejemplo.com/articulo"


def test_un_subdominio_de_la_lista_pasa():
    """Autorizar un dominio autoriza sus subdominios: es lo que espera
    cualquiera al escribir 'ejemplo.com' en la lista."""
    assert validar_url("https://www.ejemplo.com/x")
    assert validar_url("https://blog.ejemplo.com/x")


def test_http_y_https_valen_los_dos():
    assert validar_url("http://ejemplo.com")
    assert validar_url("https://ejemplo.com")


# --- SSRF: el ataque que este guardian existe para parar ----------------


@pytest.mark.requisito("RNF-06")
@pytest.mark.control("E2-RED")
@pytest.mark.parametrize("url, motivo", [
    ("http://127.0.0.1:8080/admin", "el propio PC"),
    ("http://localhost/panel", "el propio PC por nombre"),
    ("http://192.168.1.1/", "el router de casa"),
    ("http://10.0.0.5/interno", "red privada"),
    ("http://169.254.169.254/latest/meta-data/", "metadatos de cloud: CREDENCIALES"),
    ("http://[::1]/", "loopback IPv6"),
    ("http://0.0.0.0/", "sin especificar"),
])
def test_las_direcciones_internas_se_rechazan(url, motivo):
    """EL TEST QUE JUSTIFICA TODO EL MODULO. Ninguna de estas debe salir
    NUNCA, aunque el modelo la pida con toda la seguridad del mundo."""
    with pytest.raises(UrlNoPermitida):
        validar_url(url)


@pytest.mark.requisito("RNF-06")
@pytest.mark.control("E2-RED")
def test_un_dominio_permitido_que_apunta_dentro_tambien_se_rechaza(monkeypatch):
    """LA RAZON DE TENER DOS CONTROLES Y NO UNO. 'interno.ejemplo.com' SI
    esta en la lista blanca (es subdominio de ejemplo.com), pero resuelve a
    127.0.0.1. Con solo lista blanca, pasaria."""
    with pytest.raises(UrlNoPermitida, match="red interna"):
        validar_url("https://interno.ejemplo.com/")


def test_si_UNA_de_varias_ips_es_interna_se_rechaza():
    """Un nombre puede resolver a varias IPs. Basta con que una sea interna
    para que la peticion pueda acabar dentro: se comprueban TODAS."""
    with pytest.raises(UrlNoPermitida, match="red interna"):
        validar_url("https://varias.ejemplo.com/")


@pytest.mark.control("E2-RED")
def test_el_truco_del_arroba_no_cuela():
    """El clasico: 'http://sitio-bueno.com@127.0.0.1/' parece apuntar al
    sitio bueno, pero httpx va a 127.0.0.1 - lo de antes del @ es el
    usuario, no el destino.

    HONESTIDAD SOBRE ESTE TEST (descubierto por mutacion el 30/07): con
    .netloc en vez de .hostname, este caso TAMBIEN se rechazaria - pero por
    la lista blanca ("ejemplo.com@127.0.0.1" no casa con ningun dominio
    autorizado), no por leer bien el host. Es defensa en profundidad
    funcionando, y esta bien; pero significa que este test NO demuestra por
    si solo que se use .hostname. Quien lo demuestra es
    test_un_puerto_explicito_no_rompe_la_lista_blanca."""
    with pytest.raises(UrlNoPermitida):
        validar_url("http://ejemplo.com@127.0.0.1/")


def test_un_puerto_explicito_no_rompe_la_lista_blanca():
    """ESTE es el test que fija .hostname (y no .netloc).

    .netloc devuelve 'ejemplo.com:8443' con el puerto pegado, que no casa
    con la lista blanca y rechazaria una URL legitima. .hostname devuelve
    'ejemplo.com' limpio. Sin este test, cambiar hostname por netloc pasaba
    la bateria entera sin que nadie se enterara (mutacion del 30/07)."""
    assert validar_url("https://ejemplo.com:8443/x")


# --- Lista blanca -------------------------------------------------------


@pytest.mark.requisito("RNF-06")
@pytest.mark.control("E2-RED")
def test_un_dominio_que_no_esta_en_la_lista_se_rechaza():
    with pytest.raises(UrlNoPermitida, match="autorizados"):
        validar_url("https://sitio-cualquiera.com/")


def test_un_dominio_parecido_NO_cuela():
    """Sin el punto en la comprobacion, autorizar 'ejemplo.com' dejaria
    pasar tambien estos, que son de otro dueño."""
    for tramposo in (
        "https://ejemplo.com.malicioso.net/",
        "https://malejemplo.com/",
        "https://noesejemplo.com/",
    ):
        with pytest.raises(UrlNoPermitida, match="autorizados"):
            validar_url(tramposo)


@pytest.mark.requisito("RNF-06")
@pytest.mark.control("E2-RED")
def test_sin_lista_blanca_no_se_visita_NADA(monkeypatch):
    """FALLA CERRADO, igual que la lista blanca del bot: una lista de
    permitidos que al estar vacia permitiera todo seria un control al
    reves.

    OJO (mutacion del 30/07): esto se cumple SOLO por _dominio_autorizado,
    que sobre un conjunto vacio devuelve False para todo. La guarda
    explicita `if not permitidos` NO añade seguridad - lo comprobamos
    quitandola y la bateria seguia verde. Lo que si añade es un MENSAJE
    util, y eso es lo que fija el test de abajo."""
    monkeypatch.setenv(config.DOMINIOS_WEB_ENV, "")

    with pytest.raises(UrlNoPermitida):
        validar_url("https://ejemplo.com/")


def test_con_la_lista_vacia_el_mensaje_dice_COMO_arreglarlo(monkeypatch):
    """Este es el test que fija la guarda `if not permitidos`.

    Sin ella, con la lista vacia el mensaje seria "no está en mi lista de
    sitios autorizados" - tecnicamente cierto y completamente inutil, porque
    la lista no existe. El mensaje correcto dice que no hay NINGUNO
    configurado y donde ponerlos."""
    monkeypatch.setenv(config.DOMINIOS_WEB_ENV, "")

    with pytest.raises(UrlNoPermitida, match="ningún dominio autorizado"):
        validar_url("https://ejemplo.com/")


def test_la_lista_ignora_mayusculas_y_www(monkeypatch):
    """Comodidad al rellenar el .env a mano, sin abrir agujeros."""
    monkeypatch.setenv(config.DOMINIOS_WEB_ENV, "WWW.Ejemplo.COM")

    assert validar_url("https://ejemplo.com/")


# --- Esquemas -----------------------------------------------------------


@pytest.mark.parametrize("url", [
    "file:///C:/Users/jordi/.env",       # leer ficheros locales
    "ftp://ejemplo.com/x",
    "gopher://ejemplo.com:70/x",         # usable para hablar otros protocolos
    "data:text/html,<script>",
    "javascript:alert(1)",
])
def test_solo_se_permiten_http_y_https(url):
    """Sin esta comprobacion, file:// convertiria la tool de 'resumir una
    URL' en un lector de ficheros del disco."""
    with pytest.raises(UrlNoPermitida):
        validar_url(url)


def test_una_url_sin_dominio_se_rechaza():
    with pytest.raises(UrlNoPermitida):
        validar_url("https:///solo-ruta")


def test_un_dominio_que_no_existe_lo_dice_claro(monkeypatch):
    """Un fallo de DNS no debe confundirse con un rechazo de seguridad: el
    mensaje tiene que ayudar a corregir la URL."""
    import socket as socket_real

    def falla(*a, **kw):
        raise socket_real.gaierror("no existe")

    monkeypatch.setattr(red_segura.socket, "getaddrinfo", falla)

    with pytest.raises(UrlNoPermitida, match="resolver"):
        validar_url("https://ejemplo.com/")


def test_el_mensaje_de_error_no_revela_a_que_ip_resolvio():
    """No se le dice a quien sondea que hay algo en esa IP: seria
    confirmarle la existencia de un servicio interno."""
    with pytest.raises(UrlNoPermitida) as error:
        validar_url("https://interno.ejemplo.com/")

    assert "127.0.0.1" not in str(error.value)


# --- IP interna: bloquear NO basta, el mensaje importa (02/08) ------------


@pytest.mark.requisito("RNF-06")
@pytest.mark.parametrize("url,host", [
    ("https://192.168.1.1/", "192.168.1.1"),      # el router de Jordi
    ("http://127.0.0.1:8080/admin", "127.0.0.1"),
    ("http://169.254.169.254/latest/meta-data/", "169.254.169.254"),
    ("http://10.0.0.1/", "10.0.0.1"),
    # AÑADIDOS el 07/08 probando en real: los NOMBRES reservados caían por
    # la otra vía (la lista blanca), cuyo texto termina en "pídele a JIM que
    # lo añada a DOMINIOS_PERMITIDOS_WEB" — o sea, explicándole cómo
    # autorizar su propio localhost. Mismo fallo que el 02/08 con
    # 192.168.1.1, por una puerta distinta. El bloqueo ya era correcto; lo
    # que estaba mal era el CONSEJO.
    ("https://localhost:8080", "localhost"),
    ("http://localhost/panel", "localhost"),
    ("https://metadata.google.internal/", "metadata.google.internal"),
    ("http://mi-nas.local/", "mi-nas.local"),
    ("http://algo.localhost/", "algo.localhost"),
])
def test_una_IP_interna_NO_invita_a_añadirla_a_la_lista(url, host):
    """BUG REAL encontrado por Jordi probando el 02/08. Pidió resumir
    `https://192.168.1.1/` -su propio router- y el bot contestó: "JIM tiene
    que añadir el dominio 192.168.1.1 a DOMINIOS_PERMITIDOS_WEB".

    Bloqueaba bien, pero el mensaje ENSEÑABA A SALTARSE LA PROTECCIÓN: si
    alguien sigue esa instrucción, abre un SSRF contra su propia red.

    Pasaba porque una IP privada no está en la lista blanca, así que se
    paraba en la primera comprobación y usaba su texto genérico, sin llegar
    nunca a la segunda -la que sabe que eso es interno-.
    """
    with pytest.raises(UrlNoPermitida) as error:
        validar_url(url)

    mensaje = str(error.value)
    assert "interna" in mensaje.lower()
    assert "DOMINIOS_PERMITIDOS_WEB" not in mensaje, "le está diciendo cómo saltárselo"
    assert "NO le sugieras" in mensaje
    assert "listas" not in mensaje.lower() or "ninguna" in mensaje.lower()


def test_un_dominio_normal_SIGUE_diciendo_como_autorizarlo():
    """Contrapeso: para un sitio público normal, explicar cómo añadirlo es
    lo correcto y no se puede haber perdido."""
    with pytest.raises(UrlNoPermitida) as error:
        validar_url("https://sitio-cualquiera.com/")

    assert "DOMINIOS_PERMITIDOS_WEB" in str(error.value)


def test_el_mensaje_habla_a_JIM_en_SEGUNDA_persona():
    """FALLO REAL del 07/08. El texto decía "la única manera es que JIM
    añada ese dominio", y el modelo -que está hablando CON JIM- leyó "JIM"
    como un tercero. Contestó "¿te parece bien que le pida a JIM que lo
    añada?" y luego "JIM, ¿puedes añadir wikipedia.org...? 🙏", dirigiéndose
    a un administrador que no existe.

    Es primo hermano de la alucinación del 01/08 ("he pedido que se añada,
    avisaré cuando esté"): la prohibición de inventarse una cola de
    aprobación ya estaba puesta, pero nombrar a JIM en tercera persona le
    volvía a ofrecer un intermediario al que dirigirse."""
    with pytest.raises(UrlNoPermitida) as error:
        validar_url("https://sitio-cualquiera.com/")

    mensaje = str(error.value)
    assert "TÚ MISMO" in mensaje
    assert "nadie puede hacerlo por ti" in mensaje
    assert "que JIM añada" not in mensaje, "vuelve a hablar de JIM en tercera persona"


@pytest.mark.requisito("RNF-06")
@pytest.mark.control("E2-RED")
@pytest.mark.mutacion("_es_interna devuelve False ante una IP ilegible: sobrevivio")
def test_una_IP_que_no_se_puede_interpretar_se_trata_como_INTERNA():
    """HALLAZGO DE LA PRIMERA EJECUCION REAL DE `mutmut` (06/09).

    `_es_interna` termina en un `except ValueError: return True` con el
    comentario "si no se puede interpretar, se trata como peligrosa". Es la
    doctrina de fallar cerrado, escrita a mano en el sitio correcto... y
    NINGUN test la sujetaba: al cambiarlo a `return False` -o sea, al hacer
    que el guardian abriera ante una direccion ilegible- los 38 tests de este
    fichero seguian en verde.

    No es explotable hoy: el camino de `es_url_interna` solo llama aqui
    despues de que `ipaddress.ip_address` ya haya funcionado. Pero el OTRO
    llamador (`validar_url`, con cada IP que devuelve `_resolver`) recibe lo
    que diga el DNS, que es un sistema de fuera. Es codigo defensivo real y
    ahora tiene quien lo defienda.

    Se prueba la funcion privada a proposito: por el camino publico esta rama
    es inalcanzable, y un test que no puede llegar al codigo que dice
    verificar es justo la promesa que E2 §1 no admite."""
    assert red_segura._es_interna("no-soy-una-ip") is True
    assert red_segura._es_interna("") is True
    assert red_segura._es_interna("999.999.999.999") is True


# --- R-03: una lista propia para quien la necesite, sin abrir la general ---


@pytest.mark.requisito("RNF-06")
@pytest.mark.control("E2-RED")
def test_R03_una_lista_EXPLICITA_sustituye_a_la_general_no_la_amplia():
    """/noticias valida los enlaces de sus feeds con SU lista (los medios
    configurados), no con DOMINIOS_PERMITIDOS_WEB. Pasarla no puede abrir
    la general: un dominio que solo esta en la general se rechaza."""
    propia = frozenset({"medio.example"})

    assert red_segura.validar_url("https://www.medio.example/x", propia)
    with pytest.raises(red_segura.UrlNoPermitida):
        red_segura.validar_url("https://ejemplo.com/", propia)


@pytest.mark.control("E2-RED")
def test_R03_con_lista_explicita_el_bloqueo_de_IP_interna_sigue_igual():
    """La lista cambia QUE medios se aceptan; la comprobacion de red no se
    toca: un dominio de la lista que resuelve dentro se para igual."""
    with pytest.raises(red_segura.UrlNoPermitida):
        red_segura.validar_url("http://interno.ejemplo.com/", frozenset({"ejemplo.com"}))
