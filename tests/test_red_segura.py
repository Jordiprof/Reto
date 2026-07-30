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
