# Cerrojo entre PROCESOS (01/08).
#
# Deja de ser un limite documentado y pasa a impedirse, porque el aviso por
# pantalla no funciono DOS veces:
#   - 31/07: Jordi ejecuto main.py con el bot arrancado (lo que el aviso
#     pedia expresamente no hacer).
#   - 01/08: aparecieron DOS `python -m src.telegram_bot` a la vez, y ademas
#     del riesgo sobre chroma_db explica sintomas raros de la sesion de
#     prueba: el estado del bot (conversacion abierta, "te he pedido un
#     nombre", interruptores de voz) vive en RAM de CADA proceso, asi que
#     pulsar un boton en una instancia y contestar en la otra pierde el
#     estado sin dar ningun error.
#
# Lo importante de estos tests: el caso que de verdad importa es el de DOS
# PROCESOS, y eso no se puede simular con mocks. test_dos_procesos_de_verdad
# lanza un subproceso real.
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from src.cerrojo import CerrojoMemoria, MemoriaOcupada

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture
def ruta_lock(tmp_path):
    return tmp_path / "prueba.lock"


def test_tomarlo_dos_veces_en_el_mismo_proceso_falla(ruta_lock):
    primero = CerrojoMemoria(ruta_lock, quien="A").tomar()
    try:
        with pytest.raises(MemoriaOcupada):
            CerrojoMemoria(ruta_lock, quien="B").tomar()
    finally:
        primero.soltar()


def test_al_soltarlo_otro_puede_cogerlo(ruta_lock):
    CerrojoMemoria(ruta_lock, quien="A").tomar().soltar()

    segundo = CerrojoMemoria(ruta_lock, quien="B").tomar()
    segundo.soltar()  # si no se hubiera soltado, esto habria lanzado


def test_funciona_como_context_manager(ruta_lock):
    with CerrojoMemoria(ruta_lock, quien="A"):
        with pytest.raises(MemoriaOcupada):
            CerrojoMemoria(ruta_lock, quien="B").tomar()

    # Al salir del `with` queda libre.
    CerrojoMemoria(ruta_lock, quien="C").tomar().soltar()


def test_se_suelta_aunque_el_bloque_reviente(ruta_lock):
    """Si una excepcion dentro del `with` dejara el cerrojo cogido, un fallo
    cualquiera del bot obligaria a reiniciar la maquina para volver a
    arrancarlo."""
    with pytest.raises(ValueError):
        with CerrojoMemoria(ruta_lock, quien="A"):
            raise ValueError("algo revento")

    CerrojoMemoria(ruta_lock, quien="B").tomar().soltar()


def test_soltar_dos_veces_no_revienta(ruta_lock):
    """main_bot() lo suelta en un finally; si ademas se hubiera soltado
    antes, no debe explotar al salir."""
    cerrojo = CerrojoMemoria(ruta_lock, quien="A").tomar()
    cerrojo.soltar()
    cerrojo.soltar()


def test_apunta_quien_lo_tiene(ruta_lock):
    """Informativo: sirve para saber DESPUES quien lo tuvo.

    Se comprueba tras soltarlo, y no mientras esta cogido, por algo que
    salio al escribir este test: en Windows `msvcrt.locking` bloquea el
    rango de bytes de verdad, asi que leer el fichero desde otro handle
    lanza PermissionError. O sea que "mira el fichero para ver quien lo
    tiene" NO funciona en Windows mientras esta cogido - solo despues.
    """
    CerrojoMemoria(ruta_lock, quien="bot de Telegram").tomar().soltar()

    assert "bot de Telegram" in ruta_lock.read_text(encoding="utf-8")


def test_no_borra_el_contenido_antes_de_saber_si_puede(ruta_lock):
    """Se abre en modo "a+" y no "w" a proposito: "w" TRUNCA al abrir, o sea
    que el segundo proceso borraria la anotacion del primero ANTES de
    descubrir que no tenia derecho a cogerlo."""
    primero = CerrojoMemoria(ruta_lock, quien="el primero").tomar()
    try:
        with pytest.raises(MemoriaOcupada):
            CerrojoMemoria(ruta_lock, quien="el segundo").tomar()
    finally:
        primero.soltar()

    # Si el rechazado hubiera abierto en "w", esto estaria vacio.
    assert "el primero" in ruta_lock.read_text(encoding="utf-8")


# --- El caso de verdad: DOS PROCESOS ---------------------------------------


def _script(ruta_lock, accion):
    return textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(RAIZ)!r})
        from src.cerrojo import CerrojoMemoria, MemoriaOcupada
        try:
            c = CerrojoMemoria({str(ruta_lock)!r}, quien="subproceso").tomar()
            print("COGIDO")
            sys.stdout.flush()  # os._exit no vacia los buffers: sin esto no llega nada
            {accion}
        except MemoriaOcupada:
            print("RECHAZADO")
    """)


def test_dos_procesos_de_verdad_no_pueden_a_la_vez(ruta_lock):
    """EL test de esta funcionalidad. Los de arriba comprueban la API; este
    comprueba lo unico que de verdad se prometio: que un SEGUNDO PROCESO no
    puede arrancar. Un cerrojo que solo funcione dentro de un proceso no
    habria evitado nada de lo que paso."""
    padre = CerrojoMemoria(ruta_lock, quien="el proceso padre").tomar()
    try:
        salida = subprocess.run(
            [sys.executable, "-c", _script(ruta_lock, "pass")],
            capture_output=True, text=True, timeout=60,
        )
        assert "RECHAZADO" in salida.stdout, salida.stdout + salida.stderr
    finally:
        padre.soltar()


def test_un_proceso_muerto_NO_deja_el_cerrojo_colgado(ruta_lock):
    """La razon de usar un cerrojo del SO y no un fichero con el PID.

    El subproceso coge el cerrojo y muere SIN soltarlo (sys.exit brusco,
    dejando el fichero en disco). Con un fichero-PID haria falta limpiarlo a
    mano y el arranque siguiente quedaria bloqueado; con el cerrojo del SO,
    lo suelta el propio sistema al morir el proceso.
    """
    salida = subprocess.run(
        [sys.executable, "-c", _script(ruta_lock, "import os; os._exit(1)")],
        capture_output=True, text=True, timeout=60,
    )
    assert "COGIDO" in salida.stdout
    assert ruta_lock.exists(), "el fichero centinela sigue en disco, como debe"

    # Y aun asi, el siguiente puede cogerlo.
    CerrojoMemoria(ruta_lock, quien="el siguiente").tomar().soltar()


# --- Que el bot y la CLI lo usen de verdad ---------------------------------


def test_el_bot_no_arranca_si_la_memoria_esta_ocupada(monkeypatch, capsys):
    """Que exista el cerrojo no sirve de nada si main_bot() no lo coge.

    Y ademas se comprueba QUE NO TOCA NADA: ni construye la Application ni
    indexa. Indexar ya escribe en el indice de ChromaDB, que es justo el
    fichero que estamos protegiendo - hacerlo antes de saber si podemos
    seria haber corrompido lo que veniamos a salvar.
    """
    from src import telegram_bot

    def prohibido(*a, **kw):
        raise AssertionError("no debe tocar nada si la memoria esta ocupada")

    monkeypatch.setattr(telegram_bot, "construir_aplicacion", prohibido)
    monkeypatch.setattr(telegram_bot, "indexar_conversaciones", prohibido)

    class _Ocupada:
        def __init__(self, *a, **kw):
            pass

        def tomar(self):
            raise MemoriaOcupada("ya hay otro proceso")

    monkeypatch.setattr(telegram_bot, "CerrojoMemoria", _Ocupada)

    telegram_bot.main_bot()

    assert "⛔" in capsys.readouterr().out


def test_la_cli_no_arranca_si_la_memoria_esta_ocupada(monkeypatch, capsys):
    """La otra mitad: el 31/07 Jordi ejecuto la CLI con el bot arrancado."""
    from src import main as cli

    def prohibido(*a, **kw):
        raise AssertionError("no debe llegar a pedir proveedor")

    monkeypatch.setattr(cli, "_sesion", prohibido)

    class _Ocupada:
        def __init__(self, *a, **kw):
            pass

        def tomar(self):
            raise MemoriaOcupada("ya hay otro proceso")

    monkeypatch.setattr(cli, "CerrojoMemoria", _Ocupada)

    cli.main()

    assert "⛔" in capsys.readouterr().out
