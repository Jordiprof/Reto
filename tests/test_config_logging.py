# Tests de la Fase 2 del arreglo de logs (F5.2, 27/07/2026): rotacion y
# modo depuracion opt-in (DEBUG_LOG_CONTENIDO). Hermano de
# tests/test_logging.py (Fase 1, la fuga en si).
import logging
from logging.handlers import RotatingFileHandler

import pytest

from src import config


@pytest.fixture
def depuracion_aislada(tmp_path, monkeypatch):
    """Redirige logs/debug_contenido.log a un directorio temporal.

    Sin esto, cualquier test que llame a logger_depuracion() CREA el
    fichero real del proyecto y le escribe dentro (detectado el 27/07 al
    revisar: los tests habian dejado 1.5 KB de basura ahi). Dos motivos
    para arreglarlo, y el segundo es el importante:
      1. Un test no debe escribir en los directorios reales del proyecto.
      2. Rompia la garantia que documentamos en .env.example y el README:
         "si nunca enciendes el modo, el fichero no llega a existir". Si
         los propios tests lo crean, esa frase deja de ser cierta.
    """
    log = logging.getLogger(config._LOGGER_DEPURACION)
    handlers_originales = log.handlers[:]
    for handler in handlers_originales:
        handler.close()
    log.handlers.clear()
    monkeypatch.setattr(config, "_RUTA_DEPURACION", tmp_path / "debug_contenido.log")
    yield log
    for handler in log.handlers[:]:
        handler.close()
    log.handlers.clear()
    log.handlers.extend(handlers_originales)


@pytest.mark.parametrize("valor", [None, "", "  ", "0", "false", "no", "banana"])
def test_la_depuracion_esta_apagada_salvo_que_se_encienda_a_proposito(monkeypatch, valor):
    """Allowlist de valores afirmativos, no blacklist: ausente, vacia o
    cualquier texto raro -> apagado. No hay erratas que la enciendan."""
    if valor is None:
        monkeypatch.delenv(config.DEPURACION_ENV, raising=False)
    else:
        monkeypatch.setenv(config.DEPURACION_ENV, valor)
    assert config.depuracion_contenido_activa() is False


@pytest.mark.parametrize("valor", ["1", "true", "TRUE", "si", "on"])
def test_la_depuracion_se_enciende_con_valores_afirmativos(monkeypatch, valor):
    monkeypatch.setenv(config.DEPURACION_ENV, valor)
    assert config.depuracion_contenido_activa() is True


def test_con_la_depuracion_encendida_el_contenido_si_se_registra(depuracion_aislada):
    """Si esto fallara, el modo depuracion seria inutil: comprueba que el
    logger dedicado SI recibe el contenido cuando se le escribe."""
    capturado = []
    log = config.logger_depuracion()
    handler = logging.Handler()
    handler.emit = lambda registro: capturado.append(registro.getMessage())
    log.addHandler(handler)
    try:
        log.debug("Tool calcular args=%r -> %r", {"expresion": "111 + 222"}, "333")
    finally:
        log.removeHandler(handler)

    assert "111 + 222" in "\n".join(capturado)


def test_el_fichero_de_depuracion_no_existe_hasta_que_se_usa(depuracion_aislada):
    """La garantia que documentamos en .env.example y el README: el handler
    se monta perezosamente, asi que quien nunca encienda el modo no tiene
    un fichero de contenido olvidado en el disco."""
    ruta = config._RUTA_DEPURACION
    assert not ruta.exists()  # aun no se ha llamado a logger_depuracion()

    config.logger_depuracion().debug("algo")

    assert ruta.exists()  # solo aparece al usarlo de verdad


def test_la_depuracion_no_contamina_el_log_normal(depuracion_aislada):
    """LA PIEZA CLAVE del diseño de dos ficheros: con propagate=False, lo
    que escribe el logger de depuracion NO sube al logger RAIZ (el que
    alimenta agente.log de verdad) -> no llega a agente.log aunque el modo
    este activo. Si alguien quitara propagate=False (o usara
    logging.debug() a secas en vez del logger dedicado), este test se
    pone rojo.

    OJO, no se puede usar la fixture "caplog" aqui: pytest engancha su
    propio handler de captura tambien a CUALQUIER logger con
    propagate=False (documentado en el propio codigo fuente de pytest,
    _pytest.logging.catching_logs - lo hace para que sus logs sigan
    siendo depurables en un test que falla), lo que enmascararia
    justo lo que este test quiere demostrar. En su lugar, se engancha un
    handler propio directamente al logger RAIZ - el mismo sitio donde
    vive el RotatingFileHandler real de agente.log."""
    capturado = []
    handler = logging.Handler()
    handler.emit = lambda registro: capturado.append(registro.getMessage())
    raiz = logging.getLogger()
    raiz.addHandler(handler)
    try:
        config.logger_depuracion().debug("Tool calcular args=%r -> %r", "111 + 222", "333")
    finally:
        raiz.removeHandler(handler)

    assert capturado == []


def test_agente_log_rota_y_no_crece_sin_limite(handlers_de_fichero_apartados):
    """Antes era append infinito (117 KB y subiendo). Con el bot 24/7 de
    F5.2 eso se dispara, y un tope duro hace ademas que cualquier linea
    que se cuele mal caduque sola en vez de quedarse para siempre.

    Los handlers se piden a la fixture de conftest.py (que los aparta
    durante los tests para no ensuciar el fichero real), no al logger
    raiz: durante el test ya no estan enganchados ahi."""
    rotativos = [
        h for h in handlers_de_fichero_apartados if isinstance(h, RotatingFileHandler)
    ]
    assert rotativos, "agente.log debe escribirse con un handler que rote"
    assert rotativos[0].maxBytes > 0
    assert rotativos[0].backupCount > 0
    assert rotativos[0].baseFilename.endswith("agente.log")
