# Infraestructura de tests COMPARTIDA (F5.0/T6). Proveedores/objetos falsos
# reutilizables por varios ficheros de test, sin gastar llamadas reales ni
# depender de ningun SDK. pytest carga este fichero automaticamente (no hace
# falta importarlo con "import conftest"), pero las CLASES de aqui si se
# importan a mano donde hagan falta (no son fixtures, son helpers normales).
import logging
from logging.handlers import RotatingFileHandler

import pytest

from src.llm_client import _ProveedorLLM


@pytest.fixture(autouse=True)
def handlers_de_fichero_apartados():
    """Impide que la bateria de tests escriba en logs/agente.log.

    src/config.py monta un RotatingFileHandler sobre el fichero real en
    cuanto se importa, asi que cualquier test que ejecute codigo con
    logging (casi todos) acababa dejando lineas de prueba ahi dentro
    - detectado el 27/07 al revisar las fases 1-3.

    autouse=True: se aplica a TODOS los tests sin que haya que acordarse
    de pedirla, que es justo la leccion de esta incidencia (un control
    que hay que recordar aplicar no es un control). El handler se aparta
    durante el test y se devuelve despues, para no alterar la
    configuracion real del programa.

    Devuelve la lista de handlers apartados para el unico test que SI
    necesita inspeccionarlos (el de rotacion, en test_config_logging.py).
    """
    raiz = logging.getLogger()
    a_fichero = [h for h in raiz.handlers if isinstance(h, RotatingFileHandler)]
    for handler in a_fichero:
        raiz.removeHandler(handler)
    yield a_fichero
    for handler in a_fichero:
        raiz.addHandler(handler)


@pytest.fixture(autouse=True)
def cerrojo_aislado(tmp_path_factory, monkeypatch):
    """Ningun test toca el cerrojo REAL de la maquina (`.memoria.lock`).

    Nace de un fallo inmediato (01/08): al hacer que main_bot() coja el
    cerrojo, dos tests que lo llaman se pusieron ROJOS *solo porque habia
    un bot corriendo en el portatil*. Un test que pasa o falla segun lo que
    este abierto en la maquina no vale para nada, y en CI habria sido peor:
    un fallo intermitente e imposible de reproducir en local.

    Se redirige la ruta por defecto a un fichero temporal por sesion, asi
    que los tests siguen ejerciendo el cerrojo DE VERDAD (no es un mock:
    test_cerrojo.py comprueba que bloquea de verdad, incluso entre
    procesos) pero sobre un fichero que no es el del programa.

    autouse=True por la misma leccion que la fixture de arriba: un control
    que hay que acordarse de pedir no es un control.
    """
    import src.cerrojo

    monkeypatch.setattr(
        src.cerrojo, "_RUTA_POR_DEFECTO",
        tmp_path_factory.mktemp("cerrojo") / "test.lock",
    )


class ProveedorFalso(_ProveedorLLM):
    """Proveedor de mentira: se le programa de antemano la lista de
    respuestas que ira devolviendo, en orden, en cada vuelta del bucle
    LLM->tool->resultado->LLM. Usado por test_llm_loop.py."""

    def __init__(self, respuestas):
        super().__init__(api_key="x", modelo="fake")
        self._respuestas = list(respuestas)
        self.resultados_registrados = []

    def _estado_inicial(self, historial, tools):
        return {"historial": list(historial)}

    def _llamar(self, estado):
        return self._respuestas.pop(0)

    def _registrar_peticion(self, estado, respuesta):
        pass  # al falso no le hace falta reconstruir el estado del SDK

    def _registrar_resultado(self, estado, llamada, resultado):
        self.resultados_registrados.append((llamada.nombre, resultado))
