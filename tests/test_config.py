# Test de config.py (F5.0/T2, hallazgo AUD-06 de la auditoria del 23/07):
# antes, una API key ausente en .env lanzaba un KeyError sin capturar y el
# programa moria con un traceback crudo, incumpliendo RNF-02 ("ante un
# fallo de API, el programa avisa al usuario y sigue vivo").
import pytest

from src import config
from src.config import (
    MODELOS,
    MODELOS_ENV,
    PROVEEDORES,
    ClaveApiNoConfigurada,
    obtener_api_key,
    obtener_modelo_por_defecto,
)


def test_clave_ausente_lanza_error_controlado(monkeypatch):
    """Si la variable de entorno de la API key no esta puesta, debe
    lanzarse ClaveApiNoConfigurada (con un mensaje claro) - NUNCA un
    KeyError crudo."""
    # Borramos la variable de Groq del entorno, este puesta o no de antes
    # (raising=False: no falla si ya no estaba).
    monkeypatch.delenv(PROVEEDORES["groq"], raising=False)

    with pytest.raises(ClaveApiNoConfigurada) as excinfo:
        obtener_api_key("groq")

    assert PROVEEDORES["groq"] in str(excinfo.value)


def test_clave_presente_se_devuelve_tal_cual(monkeypatch):
    """Caso de control: si la variable SI esta, se devuelve su valor."""
    monkeypatch.setenv(PROVEEDORES["groq"], "clave-de-prueba")

    assert obtener_api_key("groq") == "clave-de-prueba"


def test_modelo_por_defecto_lee_del_env(monkeypatch):
    """F5.0/T5: el modelo por defecto sale de la variable *_MODEL del .env."""
    monkeypatch.setenv(MODELOS_ENV["gemini"], "models/gemini-2.5-flash")

    assert obtener_modelo_por_defecto("gemini") == "models/gemini-2.5-flash"


def test_modelo_por_defecto_cae_al_catalogo_si_no_hay_env(monkeypatch):
    """Si la variable no esta puesta, cae al primero del catalogo MODELOS
    (un valor verificado) para que el programa arranque igual."""
    monkeypatch.delenv(MODELOS_ENV["gemini"], raising=False)

    assert obtener_modelo_por_defecto("gemini") == MODELOS["gemini"][0]


def test_modelo_por_defecto_env_vacio_cae_al_catalogo(monkeypatch):
    """Una variable puesta pero VACIA tambien cae al catalogo (el 'or'
    cubre el string vacio, no solo la ausencia)."""
    monkeypatch.setenv(MODELOS_ENV["groq"], "")

    assert obtener_modelo_por_defecto("groq") == MODELOS["groq"][0]


# --- F5.5 #4: lista blanca de dominios (formato multilínea) -------------
# Bug REAL del 30/07: se escribió la lista en varias líneas SIN COMILLAS y
# python-dotenv se quedó con el valor vacío, dejando el guardián con CERO
# dominios. Falla cerrado (no deja pasar nada), pero en SILENCIO: parecía
# que había 38 sitios autorizados y no había ninguno.

def test_lista_de_una_sola_linea(monkeypatch):
    monkeypatch.setenv(config.DOMINIOS_WEB_ENV, "a.com, b.com ,C.COM")

    assert config.obtener_dominios_permitidos() == {"a.com", "b.com", "c.com"}


def test_lista_multilinea_con_comentarios(monkeypatch):
    """Con comillas en el .env, dotenv entrega el valor con saltos de línea
    y los '#' DENTRO del valor (no los quita él). Por eso config.py tiene
    que ignorarlos: si no, '# Nivel 1' entraría como si fuera un dominio."""
    monkeypatch.setenv(config.DOMINIOS_WEB_ENV, """
  # Organismos oficiales
  cdc.gov, nasa.gov,
  # Laboratorios de IA
  openai.com, anthropic.com
""")

    dominios = config.obtener_dominios_permitidos()

    assert dominios == {"cdc.gov", "nasa.gov", "openai.com", "anthropic.com"}
    # Ni un solo resto de los comentarios se cuela como dominio.
    assert not any("#" in d or "Nivel" in d or "oficiales" in d for d in dominios)


def test_una_linea_entera_de_comentario_no_aporta_dominios(monkeypatch):
    monkeypatch.setenv(config.DOMINIOS_WEB_ENV, "\n  # solo un comentario\n")

    assert config.obtener_dominios_permitidos() == frozenset()


def test_el_www_se_normaliza(monkeypatch):
    """Comodidad al rellenar a mano: 'www.x.com' y 'x.com' son el mismo
    permiso (el guardián ya autoriza subdominios)."""
    monkeypatch.setenv(config.DOMINIOS_WEB_ENV, "www.ejemplo.com")

    assert config.obtener_dominios_permitidos() == {"ejemplo.com"}


def test_sin_variable_la_lista_esta_vacia(monkeypatch):
    """FALLA CERRADO: sin lista, red_segura no visita ningún sitio."""
    monkeypatch.delenv(config.DOMINIOS_WEB_ENV, raising=False)

    assert config.obtener_dominios_permitidos() == frozenset()


def test_el_env_REAL_del_proyecto_carga_dominios():
    """RED DE SEGURIDAD contra el bug del 30/07.

    No comprueba CUÁLES son (eso es decisión de Jordi y cambia), sino que
    el .env real se parsea y produce dominios. Si alguien vuelve a escribir
    el bloque multilínea sin comillas, la lista queda vacía y este test lo
    caza en vez de descubrirse porque el bot no lee ninguna web."""
    from dotenv import dotenv_values

    valor = dotenv_values(".env").get(config.DOMINIOS_WEB_ENV)
    if valor is None:
        pytest.skip("no hay .env local (p. ej. en el CI)")

    import os
    os.environ[config.DOMINIOS_WEB_ENV] = valor
    assert len(config.obtener_dominios_permitidos()) > 0, (
        "La lista blanca del .env está VACÍA. Si la escribiste en varias "
        'líneas, tienen que ir entre comillas: DOMINIOS_PERMITIDOS_WEB="...'
    )


# --- F5.5: lista blanca agrupada por niveles (30/07) --------------------
# obtener_dominios_agrupados() es la que de verdad parsea el .env;
# obtener_dominios_permitidos() reutiliza su resultado. Un solo parseo, no
# dos que puedan desincronizarse (era justo el riesgo antes del refactor:
# las dos funciones leian la variable por su cuenta con logica separada).

def test_agrupa_por_las_cabeceras_de_comentario(monkeypatch):
    monkeypatch.setenv(config.DOMINIOS_WEB_ENV, """
  # Nivel 1: Oficial
  nasa.gov, esa.int,
  # Nivel 2: IA
  openai.com, anthropic.com
""")

    agrupados = config.obtener_dominios_agrupados()

    assert agrupados == {
        "Nivel 1: Oficial": ["nasa.gov", "esa.int"],
        "Nivel 2: IA": ["openai.com", "anthropic.com"],
    }


def test_sin_ningun_comentario_cae_en_UN_solo_grupo(monkeypatch):
    """El formato de toda la vida (una linea, sin cabeceras) sigue
    funcionando sin tener que agruparla a mano."""
    monkeypatch.setenv(config.DOMINIOS_WEB_ENV, "a.com,b.com,c.com")

    agrupados = config.obtener_dominios_agrupados()

    assert agrupados == {"Otros dominios": ["a.com", "b.com", "c.com"]}


def test_un_dominio_suelto_ANTES_del_primer_comentario_tambien_cuenta(monkeypatch):
    monkeypatch.setenv(config.DOMINIOS_WEB_ENV, "suelto.com,\n# Nivel 1\na.com")

    agrupados = config.obtener_dominios_agrupados()

    assert agrupados["Otros dominios"] == ["suelto.com"]
    assert agrupados["Nivel 1"] == ["a.com"]


def test_el_plano_y_el_agrupado_SIEMPRE_coinciden(monkeypatch):
    """LA GARANTIA que exige tener una sola fuente de parseo: el conjunto
    total de dominios tiene que ser IDENTICO se mire como se mire. Antes
    del refactor eran dos parseos independientes; este test falla si
    alguna vez vuelven a divergir."""
    monkeypatch.setenv(config.DOMINIOS_WEB_ENV, """
  # Nivel 1
  A.COM, www.B.com,
  # Nivel 2
  c.org
""")

    plano = config.obtener_dominios_permitidos()
    del_agrupado = {d for doms in config.obtener_dominios_agrupados().values() for d in doms}

    assert plano == del_agrupado == {"a.com", "b.com", "c.org"}


def test_no_duplica_un_dominio_repetido_en_el_mismo_grupo(monkeypatch):
    monkeypatch.setenv(config.DOMINIOS_WEB_ENV, "a.com, a.com, www.a.com")

    assert config.obtener_dominios_agrupados() == {"Otros dominios": ["a.com"]}


def test_agrupado_vacio_si_no_hay_variable(monkeypatch):
    monkeypatch.delenv(config.DOMINIOS_WEB_ENV, raising=False)

    assert config.obtener_dominios_agrupados() == {}


# --- El catalogo de modelos caduca solo (01/08) ----------------------------
# minimax-m2.5 se retiro el 31/07 y el catalogo siguio ofreciendolo: Jordi lo
# eligio en el menu y TODOS sus mensajes cayeron al fallback. Ademas
# .env.example recomendaba "gpt-oss:120b-cloud", que NO esta en el catalogo
# del menu (aunque el modelo si funciona: se comprobo).
#
# Estos tests NO tocan la red (no pueden saber si un modelo sigue vivo). Lo
# que vigilan es la COHERENCIA interna, que es lo que se rompio las dos
# veces: que lo que se recomienda exista en el catalogo, y que lo retirado
# no vuelva a colarse.


def _valor_env_example(clave):
    from pathlib import Path

    ruta = Path(__file__).resolve().parent.parent / ".env.example"
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        limpia = linea.strip()
        if limpia.startswith(f"{clave}="):
            return limpia.split("=", 1)[1].strip()
    return None


def test_los_modelos_de_env_example_estan_en_el_catalogo():
    """Si .env.example recomienda un modelo que el menu no conoce, es que
    uno de los dos esta desactualizado - y quien clona el repo se lleva el
    error."""
    from src.config import MODELOS

    for proveedor, clave in [("groq", "GROQ_MODEL"), ("ollama", "OLLAMA_MODEL"),
                             ("gemini", "GEMINI_MODEL")]:
        valor = _valor_env_example(clave)
        assert valor, f"{clave} no esta en .env.example"
        assert valor in MODELOS[proveedor], (
            f"{clave}={valor} no esta en el catalogo de {proveedor}: "
            "uno de los dos se ha quedado viejo"
        )


def test_los_modelos_retirados_no_vuelven_al_catalogo():
    """Lista de lapidas. Cada nombre esta aqui porque se comprobo con una
    llamada REAL que ya no sirve, con su motivo y su fecha."""
    from src.config import MODELOS

    # OJO con lo que entra en esta lista. El 01/08 metí aqui
    # "gpt-oss:120b-cloud" dandolo por retirado porque lo decia un
    # comentario del 23/07... y al comprobarlo con una llamada real
    # RESPONDE PERFECTAMENTE. Es exactamente el fallo que este proyecto
    # lleva persiguiendo desde el 15/07 (no fiarse de lo que dice una nota,
    # verificar), cometido sobre una nota propia. Regla: aqui solo entra lo
    # que se haya probado con una llamada de verdad, y el motivo se escribe
    # con el codigo HTTP que devolvio.
    retirados = {
        "minimax-m2.5": "HTTP 410 'was retired at 2026-07-31' (probado 01/08)",
        "gemini-3-flash-preview": "HTTP 410, retirado el 15/07/2026 (probado 01/08)",
        "qwen/qwen3-32b": "HTTP 404, ya no existe en Groq (probado 01/08)",
        # Existen, pero piden suscripcion Pro: ofrecerlos en el menu seria
        # ofrecer un 403. Probados los nueve el 01/08.
        "minimax-m2.7": "HTTP 403 'requires a subscription'",
        "glm-5.2": "HTTP 403 'requires a subscription'",
        "glm-5.1": "HTTP 403 'requires a subscription'",
        "kimi-k3": "HTTP 403 'requires a subscription'",
        "kimi-k2.6": "HTTP 403 'requires a subscription'",
        "kimi-k2.7-code": "HTTP 403 'requires a subscription'",
        "qwen3.5": "HTTP 403 'requires a subscription'",
        "deepseek-v4-pro": "HTTP 403 'requires a subscription'",
        "deepseek-v4-flash": "HTTP 403 'requires a subscription'",
    }
    todos = {m for lista in MODELOS.values() for m in lista}

    for modelo, motivo in retirados.items():
        assert modelo not in todos, f"{modelo}: {motivo}"
