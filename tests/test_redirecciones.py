"""Seguir redirecciones SIN dejar fuera al guardian (02/08).

EL PROBLEMA MEDIDO. Jordi pidio leer `https://anthropic.com/` -que ESTA en
la lista blanca- y el bot contesto que no sigue redirecciones. Al medirlo:
**11 de los 28 dominios autorizados redirigen**, o sea que el 39% de la
lista era decorativa. Ocho van al `www.` de su propio dominio y tres a una
ruta interna. Ninguna salta a otro dominio.

LO QUE NO PUEDE ROMPERSE. El motivo por el que se puso follow_redirects=False
sigue vivo: un dominio autorizado que redirija a 127.0.0.1 esquivaria el
guardian. Por eso el salto se sigue A MANO y el destino pasa por
validar_url() ENTERO - lista blanca Y bloqueo de IPs internas.
"""


from src import tools


class _RespuestaFalsa:
    """Imita lo justo de httpx.Response que usa _pedir_texto."""

    def __init__(self, location=None, cuerpo=b"", tipo="text/html"):
        self.is_redirect = location is not None
        self.headers = {"content-type": tipo}
        if location is not None:
            self.headers["location"] = location
        self._cuerpo = cuerpo

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    def iter_bytes(self):
        yield self._cuerpo


def _httpx_falso(monkeypatch, respuestas: dict):
    """Devuelve una respuesta distinta segun la URL pedida, y apunta el
    orden en que se piden."""
    pedidas = []

    def stream(metodo, url, **kw):
        pedidas.append(url)
        return respuestas[url]

    monkeypatch.setattr(
        "httpx.stream", stream, raising=False
    )
    return pedidas


def test_una_redireccion_a_www_del_MISMO_dominio_se_sigue(monkeypatch):
    """El caso real de Jordi: anthropic.com -> www.anthropic.com. La lista
    blanca ya acepta subdominios, asi que el destino es igual de legitimo."""
    pedidas = _httpx_falso(monkeypatch, {
        "https://anthropic.com/": _RespuestaFalsa(location="https://www.anthropic.com/"),
        "https://www.anthropic.com/": _RespuestaFalsa(cuerpo=b"<p>hola desde www</p>"),
    })

    resultado = tools._pedir_texto("https://anthropic.com/")

    assert "hola desde www" in resultado
    assert pedidas == ["https://anthropic.com/", "https://www.anthropic.com/"]


def test_una_redireccion_RELATIVA_se_resuelve(monkeypatch):
    """learn.microsoft.com devuelve `/en-us/` a secas, sin dominio. Sin
    resolverlo contra el origen, tres de los once casos reales seguirian
    sin funcionar."""
    pedidas = _httpx_falso(monkeypatch, {
        "https://learn.microsoft.com/": _RespuestaFalsa(location="/en-us/"),
        "https://learn.microsoft.com/en-us/": _RespuestaFalsa(cuerpo=b"<p>docs</p>"),
    })

    resultado = tools._pedir_texto("https://learn.microsoft.com/")

    assert "docs" in resultado
    assert pedidas[-1] == "https://learn.microsoft.com/en-us/"


def test_una_redireccion_a_UNA_IP_INTERNA_SIGUE_BLOQUEADA(monkeypatch):
    """EL TEST QUE IMPORTA. Es el ataque exacto por el que existia
    follow_redirects=False: un dominio autorizado que manda la peticion a
    127.0.0.1. El destino pasa por el guardian entero, asi que se para
    igual que si lo hubiera pedido el modelo directamente."""
    pedidas = _httpx_falso(monkeypatch, {
        "https://anthropic.com/": _RespuestaFalsa(location="http://127.0.0.1:8080/admin"),
    })

    resultado = tools._pedir_texto("https://anthropic.com/")

    assert "no está entre los autorizados" in resultado
    assert len(pedidas) == 1, "la IP interna NO puede llegar a pedirse"


def test_una_redireccion_a_OTRO_dominio_no_autorizado_se_para(monkeypatch):
    """Un sitio de la lista blanca no puede usarse de trampolin hacia
    cualquier otro."""
    pedidas = _httpx_falso(monkeypatch, {
        "https://anthropic.com/": _RespuestaFalsa(location="https://sitio-cualquiera.com/"),
    })

    resultado = tools._pedir_texto("https://anthropic.com/")

    assert "no está entre los autorizados" in resultado
    assert len(pedidas) == 1


def test_un_bucle_de_redirecciones_se_corta(monkeypatch):
    """Sin tope, dos paginas apuntandose la una a la otra tienen a la tool
    dando vueltas hasta el timeout."""
    pedidas = _httpx_falso(monkeypatch, {
        "https://anthropic.com/": _RespuestaFalsa(location="https://www.anthropic.com/"),
        "https://www.anthropic.com/": _RespuestaFalsa(location="https://anthropic.com/"),
    })

    resultado = tools._pedir_texto("https://anthropic.com/")

    assert "demasiadas redirecciones" in resultado.lower()
    assert len(pedidas) <= tools._MAX_REDIRECCIONES + 1


def test_una_redireccion_sin_destino_no_revienta(monkeypatch):
    _httpx_falso(monkeypatch, {
        "https://anthropic.com/": _RespuestaFalsa(location=""),
    })
    # location="" hace is_redirect True pero sin destino que seguir.
    resultado = tools._pedir_texto("https://anthropic.com/")

    assert "no ha querido decirme" in resultado.lower()


def test_sin_redireccion_todo_sigue_igual(monkeypatch):
    """Contrapeso: los 16 dominios que responden directo no pueden haberse
    roto por esto."""
    _httpx_falso(monkeypatch, {
        "https://cohere.com/": _RespuestaFalsa(cuerpo=b"<p>directo</p>"),
    })

    assert "directo" in tools._pedir_texto("https://cohere.com/")
