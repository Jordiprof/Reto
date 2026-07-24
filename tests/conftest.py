# Infraestructura de tests COMPARTIDA (F5.0/T6). Proveedores/objetos falsos
# reutilizables por varios ficheros de test, sin gastar llamadas reales ni
# depender de ningun SDK. pytest carga este fichero automaticamente (no hace
# falta importarlo con "import conftest"), pero las CLASES de aqui si se
# importan a mano donde hagan falta (no son fixtures, son helpers normales).
from src.llm_client import _ProveedorLLM


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
