# F5.5: tests del "volver atras" en los menus encadenados proveedor->modelo
# (hallazgo real del 25/07: Esc no hacia nada, y Ctrl+C dentro de un menu de
# questionary devolvia None en silencio en vez de propagarse como
# KeyboardInterrupt - eso ya causo el bug "Agente listo con groq (None)").
#
# Nada de esto toca la terminal real: se parchea questionary.select (o las
# propias funciones de main.py) con monkeypatch, mismo principio que
# ProveedorFalso en conftest.py para el router - sustituir la costura, no
# simular una terminal de verdad.
import questionary

import src.main as m
from src.config import MODELOS_ENV, ClaveApiNoConfigurada


class _SelectFalso:
    """Sustituye a questionary.select(): guarda los kwargs recibidos (para
    poder inspeccionarlos) y su .ask() devuelve un valor fijo."""

    def __init__(self, valor):
        self._valor = valor
        self.kwargs = None

    def __call__(self, mensaje, **kwargs):
        self.kwargs = kwargs
        return self

    def ask(self):
        return self._valor


def test_elegir_modelo_sin_volver_no_incluye_la_opcion(monkeypatch):
    """Desde /modelo (permitir_volver=False) no hay "a donde volver" - la
    opcion no debe aparecer, ni siquiera como ruido."""
    falso = _SelectFalso(valor="llama-3.3-70b-versatile")
    monkeypatch.setattr(questionary, "select", falso)

    m.elegir_modelo("groq")

    assert all(isinstance(c, str) for c in falso.kwargs["choices"])


def test_elegir_modelo_con_volver_anade_la_opcion_al_final(monkeypatch):
    falso = _SelectFalso(valor=m.VOLVER)
    monkeypatch.setattr(questionary, "select", falso)

    m.elegir_modelo("groq", permitir_volver=True)

    ultima = falso.kwargs["choices"][-1]
    assert isinstance(ultima, questionary.Choice)
    assert ultima.value is m.VOLVER
    # Las anteriores siguen siendo los modelos reales del catalogo, sin tocar.
    assert falso.kwargs["choices"][:-1] == list(m.MODELOS["groq"])


def test_default_del_env_se_preselecciona_con_volver_activo(monkeypatch):
    """Blinda el hallazgo clave: una lista MIXTA (strings + Choice de
    Volver) no rompe la preseleccion del modelo del .env (F5.0/T5)."""
    modelo_env = m.MODELOS["groq"][1]
    monkeypatch.setenv(MODELOS_ENV["groq"], modelo_env)
    falso = _SelectFalso(valor=modelo_env)
    monkeypatch.setattr(questionary, "select", falso)

    m.elegir_modelo("groq", permitir_volver=True)

    assert falso.kwargs["default"] == modelo_env


def test_modelo_fuera_del_catalogo_no_se_pasa_como_default(monkeypatch):
    """Comportamiento ya existente (F5.0/T5), que no debe romperse: si el
    .env trae un modelo que no esta en MODELOS, default queda en None."""
    monkeypatch.setenv(MODELOS_ENV["groq"], "modelo-que-no-existe")
    falso = _SelectFalso(valor=m.MODELOS["groq"][0])
    monkeypatch.setattr(questionary, "select", falso)

    m.elegir_modelo("groq")

    assert falso.kwargs["default"] is None


def test_volver_reabre_el_menu_de_proveedor(monkeypatch):
    """El caso central: VOLVER hace que se vuelva a preguntar el proveedor,
    no que se cancele todo."""
    respuestas_proveedor = iter(["gemini", "groq"])
    respuestas_modelo = iter([m.VOLVER, "llama-3.3-70b-versatile"])
    llamadas_proveedor = []

    def proveedor_falso():
        llamadas_proveedor.append(1)
        return next(respuestas_proveedor)

    monkeypatch.setattr(m, "elegir_proveedor", proveedor_falso)
    monkeypatch.setattr(
        m, "elegir_modelo", lambda p, permitir_volver=False: next(respuestas_modelo)
    )
    monkeypatch.setattr(m, "obtener_api_key", lambda p: "clave-x")

    resultado = m.elegir_proveedor_y_modelo()

    assert resultado == ("groq", "llama-3.3-70b-versatile", "clave-x")
    assert len(llamadas_proveedor) == 2  # se reabrio el menu de proveedor


def test_ctrl_c_en_proveedor_cancela_todo(monkeypatch):
    """Ctrl+C en el PRIMER menu (proveedor) no es "volver" - cancela entero."""
    monkeypatch.setattr(m, "elegir_proveedor", lambda: None)

    assert m.elegir_proveedor_y_modelo() is None


def test_ctrl_c_en_modelo_cancela_todo(monkeypatch):
    """Ctrl+C en el menu de MODELO tambien cancela - distinto de VOLVER,
    que reabre el menu anterior en vez de abortar."""
    monkeypatch.setattr(m, "elegir_proveedor", lambda: "groq")
    monkeypatch.setattr(m, "elegir_modelo", lambda p, permitir_volver=False: None)

    assert m.elegir_proveedor_y_modelo() is None


def test_clave_ausente_vuelve_al_menu_en_vez_de_abortar(monkeypatch, capsys):
    """RNF-02: si el proveedor elegido no tiene clave en el .env, se avisa
    y se vuelve a preguntar - no se mata el programa entero (comportamiento
    de antes del 25/07, ya corregido)."""
    respuestas_proveedor = iter(["gemini", "groq"])
    monkeypatch.setattr(m, "elegir_proveedor", lambda: next(respuestas_proveedor))
    monkeypatch.setattr(m, "elegir_modelo", lambda p, permitir_volver=False: "un-modelo")

    def api_key_falsa(proveedor):
        if proveedor == "gemini":
            raise ClaveApiNoConfigurada("Falta GEMINI_API_KEY")
        return "clave-buena"

    monkeypatch.setattr(m, "obtener_api_key", api_key_falsa)

    resultado = m.elegir_proveedor_y_modelo()

    assert resultado == ("groq", "un-modelo", "clave-buena")
    assert "Falta GEMINI_API_KEY" in capsys.readouterr().out
