"""F5.5 #4 - Guardian de URLs: la puerta por la que pasa TODA peticion cuyo
destino elija el modelo o el usuario (ADR-006).

QUE PROBLEMA CIERRA (SSRF, Server-Side Request Forgery). Cuando el destino
de una peticion sale de un argumento -y no de una constante del codigo- el
modelo puede apuntar a donde quiera. Y el proceso que hace esa peticion esta
DENTRO de la red de Jordi, asi que puede llegar a sitios que desde internet
no se alcanzan:
  - http://127.0.0.1:... -> cualquier servicio local del propio PC.
  - http://192.168.1.1/  -> el router de casa, su panel de administracion.
  - http://169.254.169.254/latest/meta-data/ -> el endpoint de metadatos de
    los proveedores cloud, que sirve CREDENCIALES de la maquina. Es el
    vector clasico si algun dia el bot vive en un VPS (ver E1 §7, hosting
    sin decidir).

POR QUE DOS CONTROLES Y NO UNO. La lista blanca de dominios y el bloqueo de
IPs internas parecen redundantes, pero cubren cosas distintas:
  - La LISTA BLANCA responde a "¿confio en el contenido de ese sitio?" - es
    una decision editorial de Jordi, que un programa no puede tomar.
  - El BLOQUEO DE IPs responde a "¿esa direccion esta dentro de mi red?" -
    es una comprobacion tecnica, verificable, sin opinion.
Un dominio de la lista blanca podria apuntar (por error, o porque alguien
tomo su DNS) a 127.0.0.1: sin la segunda comprobacion, la lista blanca lo
dejaria pasar.

LIMITACION CONOCIDA, dicha aqui y no escondida: entre que se resuelve el
nombre y que se abre la conexion, el DNS podria cambiar de respuesta (DNS
rebinding). Cerrarlo del todo obliga a conectarse a mano por IP con la
cabecera Host, que es mucha maquinaria para un bot personal. Se asume, se
documenta, y se compensa con la lista blanca: el atacante tendria que
controlar ademas un dominio que Jordi haya autorizado a mano.
"""
import ipaddress
import socket
from urllib.parse import urlparse

from src.config import obtener_dominios_permitidos

# Solo http/https. Sin esto pasarian file:// (leer ficheros locales),
# ftp://, gopher:// (usable para hablar con otros protocolos) o data:.
_ESQUEMAS_PERMITIDOS = ("http", "https")


class UrlNoPermitida(Exception):
    """La URL no supera el guardian. El mensaje esta escrito para que lo
    lea el MODELO como resultado de la tool: dice que pasa y que hacer, sin
    detalles internos."""


def _resolver(host: str) -> list:
    """Todas las IPs a las que resuelve un nombre.

    TODAS y no solo la primera: un nombre puede resolver a varias, y basta
    con que UNA sea interna para que la peticion pueda acabar dentro de la
    red. Se comprueban todas y se rechaza si alguna falla.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise UrlNoPermitida(
            f"No he podido resolver el dominio '{host}'. Comprueba que este bien escrito."
        ) from None
    # sockaddr[0] es la IP tanto en IPv4 como en IPv6.
    return [info[4][0] for info in infos]


def _es_interna(ip_texto: str) -> bool:
    """True si la IP pertenece a la maquina o a la red local.

    Se listan las categorias una a una en vez de fiarlo todo a is_private:
    asi queda escrito QUE se bloquea y por que, y no depende de que la
    definicion de "privada" de Python coincida con la nuestra.
    """
    try:
        ip = ipaddress.ip_address(ip_texto)
    except ValueError:
        return True  # si no se puede interpretar, se trata como peligrosa

    return (
        ip.is_private        # 10/8, 172.16/12, 192.168/16
        or ip.is_loopback    # 127/8 y ::1 - el propio PC
        or ip.is_link_local  # 169.254/16 - INCLUYE el metadata de cloud
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified  # 0.0.0.0
    )


def _dominio_autorizado(host: str, permitidos: frozenset) -> bool:
    """El host esta en la lista, o es un subdominio suyo.

    La comprobacion es `host == dominio or host.endswith("." + dominio)`, y
    ese punto NO es cosmetico: sin el, autorizar "ejemplo.com" tambien
    dejaria pasar "ejemplo.com.sitio-malicioso.net" y "malejemplo.com", que
    son dominios de otro dueño.
    """
    return any(host == d or host.endswith("." + d) for d in permitidos)


def validar_url(url: str) -> str:
    """Deja pasar la URL o lanza UrlNoPermitida explicando por que no.

    Devuelve la URL tal cual si es valida, para poder escribir
    `httpx.get(validar_url(u))` y que sea imposible saltarse el guardian
    por olvido.
    """
    try:
        partes = urlparse(url.strip())
    except ValueError:
        raise UrlNoPermitida("Esa dirección no tiene forma de URL válida.") from None

    if partes.scheme.lower() not in _ESQUEMAS_PERMITIDOS:
        raise UrlNoPermitida(
            "Solo puedo visitar direcciones http:// o https://."
        )

    # .hostname (no .netloc): urlparse ya descarta el usuario y el puerto,
    # asi que un "http://sitio-de-confianza.com@127.0.0.1/" da hostname
    # 127.0.0.1, que es a donde de verdad iria la peticion. Usar netloc
    # aqui seria el fallo clasico.
    host = (partes.hostname or "").lower()
    if not host:
        raise UrlNoPermitida("Esa dirección no tiene dominio.")

    permitidos = obtener_dominios_permitidos()
    if not permitidos:
        raise UrlNoPermitida(
            "No tengo ningún dominio autorizado todavía. Añádelos a "
            "DOMINIOS_PERMITIDOS_WEB en el .env."
        )
    if not _dominio_autorizado(host, permitidos):
        raise UrlNoPermitida(
            f"'{host}' no está en mi lista de sitios autorizados. Si te fías "
            "de él, añádelo a DOMINIOS_PERMITIDOS_WEB en el .env."
        )

    for ip in _resolver(host):
        if _es_interna(ip):
            # NO se dice a que IP resolvio: seria confirmarle a quien
            # sondea que existe algo ahi dentro.
            raise UrlNoPermitida(
                f"'{host}' apunta a una dirección de la red interna y no la visito."
            )

    return url.strip()
