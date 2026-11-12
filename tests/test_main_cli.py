# NC-06 (auditoria ISO del 04/09): src/main.py estaba al 17 % de cobertura,
# 273 sentencias de 339 sin ejecutar NUNCA. No es la superficie expuesta -esa
# es el bot- pero era el mayor agujero de la bateria y hasta la auditoria no
# estaba declarado en ninguna parte.
#
# test_main_menus.py ya cubria los menus encadenados proveedor->modelo. Lo que
# no tocaba nadie era: la lista blanca tal y como se enseña en la CLI, el
# descifrado al abrir una conversacion guardada, el menu de /tools, y -lo mas
# importante de todo- que main() COJA EL CERROJO antes de nada (RF-24).
#
# Mismo principio que test_main_menus.py y que ProveedorFalso en conftest.py:
# se sustituye la costura (questionary, el cerrojo, el almacen), no se simula
# una terminal de verdad. Ni un test toca la red, el disco real ni la cuota.
import pytest

import src.main as m
from src.storage import ConversacionNoDescifrable


class _SelectFalso:
    """questionary.select() de mentira: devuelve, en orden, los valores que se
    le programan. Igual que ProveedorFalso con las respuestas del LLM.

    Se le pasa una LISTA porque menu_tools es un bucle: hace falta poder
    contestar "enciende esto" y despues "vuelve", o el test no terminaria.
    """

    def __init__(self, valores):
        self._valores = list(valores)
        self.veces = 0
        self.ultimas_opciones = None

    def __call__(self, mensaje, **kwargs):
        self.veces += 1
        self.ultimas_opciones = kwargs.get("choices")
        return self

    def ask(self):
        return self._valores.pop(0)


class _AgenteFalso:
    """Lo unico que menu_tools necesita de un Agente: el conjunto mutable de
    categorias encendidas."""

    def __init__(self, activas=()):
        self.categorias_activas = set(activas)


# ---------------------------------------------------------------------------
# _imprimir_sitios: la lista blanca, tal y como la ve Jordi en la CLI
# ---------------------------------------------------------------------------


@pytest.mark.requisito("RNF-06")
def test_sin_dominios_avisa_de_que_no_podra_leer_ninguna_web(capsys):
    m._imprimir_sitios({})
    salida = capsys.readouterr().out
    assert "No hay ningún sitio autorizado" in salida
    # Y dice DONDE se arregla, que es la mitad util del aviso.
    assert "DOMINIOS_PERMITIDOS_WEB" in salida


@pytest.mark.requisito("RNF-06")
def test_cada_dominio_sale_como_URL_COMPLETA_y_pegable(capsys):
    """Peticion del 31/07 tras probar en real: la lista blanca guarda
    DOMINIOS, pero lo que hay que pegarle al agente es una direccion exacta,
    porque `resumir_url` no busca. Sin el https:// y la barra, la lista se
    miraba pero no se usaba."""
    m._imprimir_sitios({"Documentación": ["docs.python.org", "peps.python.org"]})
    salida = capsys.readouterr().out
    assert "https://docs.python.org/" in salida
    assert "https://peps.python.org/" in salida


def test_los_sitios_salen_agrupados_por_su_cabecera(capsys):
    m._imprimir_sitios({"Prensa": ["elpais.com"], "Documentación": ["docs.python.org"]})
    salida = capsys.readouterr().out
    assert "Prensa" in salida
    assert "Documentación" in salida


def test_avisa_de_que_NO_sigue_redirecciones(capsys):
    """Caso real: https://dgt.es/ redirige, y como NO seguimos redirecciones
    (es seguridad, no comodidad), sin este aviso un 301 parece un fallo
    nuestro."""
    m._imprimir_sitios({"Tráfico": ["dgt.es"]})
    assert "no sigo redirecciones" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# mostrar_conversacion: descifra sola, y si no puede AVISA en vez de reventar
# ---------------------------------------------------------------------------


@pytest.mark.requisito("RF-19")
def test_mostrar_conversacion_NO_imprime_el_system_prompt(monkeypatch, capsys):
    """historial[0] es el system prompt: es configuracion, no es "lo que se
    dijo". Enseñarlo confundiria, y ademas puede ser largo."""
    monkeypatch.setattr(
        m,
        "cargar_conversacion",
        lambda ruta: {
            "historial": [
                {"role": "system", "content": "ERES-UN-ASISTENTE-SECRETO"},
                {"role": "user", "content": "hola"},
                {"role": "assistant", "content": "buenas"},
            ]
        },
    )
    m.mostrar_conversacion("da_igual.json")
    salida = capsys.readouterr().out
    assert "ERES-UN-ASISTENTE-SECRETO" not in salida
    assert "hola" in salida
    assert "buenas" in salida


@pytest.mark.requisito("RNF-02", "RF-17")
def test_una_conversacion_que_no_se_puede_descifrar_avisa_y_NO_revienta(monkeypatch, capsys):
    """RNF-02: ante un fichero que no se puede leer, el programa avisa y sigue
    vivo. Si esto lanzara, se llevaria por delante la sesion entera por no
    poder abrir UNA conversacion vieja."""

    def _explota(ruta):
        raise ConversacionNoDescifrable("la clave no vale para este fichero")

    monkeypatch.setattr(m, "cargar_conversacion", _explota)
    m.mostrar_conversacion("cifrada.json")  # no debe lanzar
    assert "la clave no vale para este fichero" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# menu_tools: cancelar NUNCA debe cambiar nada por sorpresa
# ---------------------------------------------------------------------------


@pytest.mark.requisito("RF-13")
def test_volver_sale_del_menu_SIN_tocar_las_categorias(monkeypatch, capsys):
    agente = _AgenteFalso({"tiempo"})
    monkeypatch.setattr(m.questionary, "select", _SelectFalso([m.VOLVER]))
    m.menu_tools(agente)
    assert agente.categorias_activas == {"tiempo"}
    assert "Herramientas activas: tiempo" in capsys.readouterr().out


@pytest.mark.requisito("RF-13")
def test_ctrl_c_tampoco_le_apaga_las_herramientas_al_agente(monkeypatch):
    """questionary.ask() atrapa el Ctrl+C y devuelve None. Si ese None se
    tratara como "no eligio nada, apaga todo", cancelar seria destructivo."""
    agente = _AgenteFalso({"tiempo", "memoria"})
    monkeypatch.setattr(m.questionary, "select", _SelectFalso([None]))
    m.menu_tools(agente)
    assert agente.categorias_activas == {"tiempo", "memoria"}


@pytest.mark.requisito("RF-13")
def test_elegir_una_categoria_apagada_la_enciende(monkeypatch):
    agente = _AgenteFalso()
    monkeypatch.setattr(m.questionary, "select", _SelectFalso(["tiempo", m.VOLVER]))
    m.menu_tools(agente)
    assert "tiempo" in agente.categorias_activas


@pytest.mark.requisito("RF-13")
def test_elegir_una_categoria_encendida_la_apaga(monkeypatch):
    agente = _AgenteFalso({"tiempo"})
    monkeypatch.setattr(m.questionary, "select", _SelectFalso(["tiempo", m.VOLVER]))
    m.menu_tools(agente)
    assert "tiempo" not in agente.categorias_activas


@pytest.mark.requisito("RF-13")
def test_ver_los_sitios_NO_conmuta_ninguna_categoria(monkeypatch, capsys):
    """Peticion del 31/07: antes la lista solo se imprimia al ENCENDER web, asi
    que con web ya encendida habia que apagarla y encenderla para volver a
    verla. Esta opcion existe para no tener que hacer eso."""
    agente = _AgenteFalso({"web"})
    monkeypatch.setattr(m.questionary, "select", _SelectFalso([m._VER_SITIOS, m.VOLVER]))
    monkeypatch.setattr("src.config.obtener_dominios_agrupados", lambda: {"Docs": ["a.com"]})
    m.menu_tools(agente)
    assert agente.categorias_activas == {"web"}
    assert "https://a.com/" in capsys.readouterr().out


@pytest.mark.requisito("RF-13", "RNF-06")
def test_al_encender_web_se_listan_los_sitios_autorizados(monkeypatch, capsys):
    """web es la unica categoria donde "que puede hacer" depende de una
    configuracion externa: encenderla sin ver la lista no dice nada."""
    agente = _AgenteFalso()
    monkeypatch.setattr(m.questionary, "select", _SelectFalso(["web", m.VOLVER]))
    monkeypatch.setattr("src.config.obtener_dominios_agrupados", lambda: {"Docs": ["b.com"]})
    m.menu_tools(agente)
    assert "https://b.com/" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# main(): el cerrojo va PRIMERO, antes incluso de preguntar proveedor (RF-24)
# ---------------------------------------------------------------------------


class _CerrojoFalso:
    def __init__(self, **kwargs):
        self.tomado = False
        self.soltado = False
        _CerrojoFalso.ultimo = self

    def tomar(self):
        self.tomado = True
        return self

    def soltar(self):
        self.soltado = True


@pytest.mark.requisito("RF-24")
def test_si_la_memoria_esta_ocupada_la_CLI_NO_arranca_la_sesion(monkeypatch, capsys):
    """El 31/07 Jordi ejecuto la CLI CON EL BOT ARRANCADO, que es justo lo que
    el aviso de pantalla pedia no hacer - por eso ahora se IMPIDE en vez de
    avisarse. Si esto se rompiera, dos procesos escribirian sobre el mismo
    indice."""

    def _ocupada(**kwargs):
        raise m.MemoriaOcupada("ya lo tiene el bot de Telegram")

    monkeypatch.setattr(m, "CerrojoMemoria", _ocupada)
    llamadas = []
    monkeypatch.setattr(m, "_sesion", lambda: llamadas.append(1))

    m.main()

    assert llamadas == [], "la sesion no debe arrancar con la memoria ocupada"
    assert "ya lo tiene el bot de Telegram" in capsys.readouterr().out


@pytest.mark.requisito("RF-24")
def test_el_cerrojo_se_suelta_al_terminar_la_sesion(monkeypatch):
    monkeypatch.setattr(m, "CerrojoMemoria", _CerrojoFalso)
    monkeypatch.setattr(m, "_sesion", lambda: None)

    m.main()

    assert _CerrojoFalso.ultimo.tomado
    assert _CerrojoFalso.ultimo.soltado


@pytest.mark.requisito("RF-24")
def test_el_cerrojo_se_suelta_AUNQUE_la_sesion_reviente(monkeypatch):
    """Sin el finally, un fallo cualquiera dejaria el cerrojo cogido y la
    siguiente CLI -o el bot- no podria arrancar hasta reiniciar la maquina."""

    def _revienta():
        raise RuntimeError("algo peto a mitad")

    monkeypatch.setattr(m, "CerrojoMemoria", _CerrojoFalso)
    monkeypatch.setattr(m, "_sesion", _revienta)

    with pytest.raises(RuntimeError):
        m.main()

    assert _CerrojoFalso.ultimo.soltado, "el cerrojo quedaria colgado"


# ---------------------------------------------------------------------------
# R-09 (auditoria de seguridad de noviembre): la compactacion NO escribe nada
# ---------------------------------------------------------------------------


@pytest.fixture
def sesion_cli_con_charla_larga(tmp_path, monkeypatch):
    """Monta _sesion() de punta a punta sin terminal, sin red y sin tocar las
    conversaciones reales: un Agente de verdad con un router falso, una
    charla lo bastante larga para que se compacte, y luego /salir.

    Devuelve una funcion que ejecuta la sesion contestando `respuesta` a la
    pregunta "¿Guardar esta conversación?", y la carpeta donde se guarda.
    """
    from types import SimpleNamespace

    from src import rag, storage

    monkeypatch.setattr(storage, "CONVERSATIONS_DIR", tmp_path / "conversations")
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "conversations.db")
    storage.CONVERSATIONS_DIR.mkdir()
    monkeypatch.delenv("CONVERSATIONS_KEY", raising=False)
    monkeypatch.setattr(rag, "indexar_conversaciones", lambda: 0)
    monkeypatch.setattr(m, "elegir_proveedor_y_modelo", lambda: ("groq", "fake", "x"))
    monkeypatch.setattr(m, "pedir_nombre_conversacion", lambda: None)

    class _AgenteSinRed(m.Agente):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.router = SimpleNamespace(
                responder=lambda mensajes, tools: "respuesta " + "z" * 1500,
                aviso_fallback=None,
            )

    monkeypatch.setattr(m, "Agente", _AgenteSinRed)

    def ejecutar(respuesta_guardar):
        entradas = iter([f"pregunta {i} " + "y" * 1500 for i in range(15)] + ["/salir"])
        monkeypatch.setattr("builtins.input", lambda *a: next(entradas))
        monkeypatch.setattr(
            m.questionary, "confirm",
            lambda *a, **kw: SimpleNamespace(ask=lambda: respuesta_guardar),
        )
        m._sesion()
        return sorted(storage.CONVERSATIONS_DIR.glob("*.json"))

    return ejecutar


@pytest.mark.requisito("RF-26", "RNF-06")
def test_R09_si_dices_NO_GUARDAR_no_queda_nada_en_disco_aunque_se_compactara(
    sesion_cli_con_charla_larga, capsys
):
    """Antes, la compactacion llamaba a agente.guardar() a mitad de sesion:
    la charla ya estaba en disco (y entraba al RAG en el siguiente arranque)
    cuando al salir se contestaba "no guardar". El "modo efimero" de RNF-06
    mentia."""
    ficheros = sesion_cli_con_charla_larga(False)

    assert "he sacado del" in capsys.readouterr().out  # precondicion: compacto
    assert ficheros == []


@pytest.mark.requisito("RF-26", "RF-06")
def test_R09_al_guardar_queda_UN_fichero_con_TODA_la_charla(sesion_cli_con_charla_larga):
    """La otra mitad: antes salian dos ficheros (el de la compactacion y el de
    la salida), y el RAG indexaba los mismos mensajes dos veces."""
    from src import storage

    ficheros = sesion_cli_con_charla_larga(True)

    assert len(ficheros) == 1
    datos = storage.cargar_conversacion(ficheros[0])
    assert len(datos["historial"]) == 1 + 2 * 15
    assert datos["historial"][1]["content"].startswith("pregunta 0 ")
