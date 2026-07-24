# Router de proveedores con reintentos y fallback automatico (F5.0/T4).
#
# El PORQUE (ADR-004): hasta ahora la cadena de proveedores de ADR-001
# (Groq -> Ollama -> Gemini) solo existia como texto en la documentacion.
# El codigo hablaba con UN proveedor y, si daba 429/timeout/cae la red, el
# turno se perdia. Para un bot que quiere estar vivo 24/7 eso no vale: si
# el proveedor principal falla de forma transitoria, el agente debe (1)
# reintentar con backoff y, si aun asi no responde, (2) degradar solo al
# siguiente proveedor de la cadena. Esto es lo que da sentido REAL a
# ADR-001; antes era una promesa sin cumplir (hallazgo de la revision).
import logging
import time
from dataclasses import dataclass

# Cada eslabon de la cadena necesita SU proveedor + clave + modelo. El
# router los prueba en orden.
from src.config import ClaveApiNoConfigurada, obtener_api_key, obtener_modelo_por_defecto
from src.llm_client import responder_proveedor
from src.llm_errors import ErrorLLM

# ADR-001: orden oficial de la cadena de proveedores. Anthropic queda fuera
# porque todavia no esta implementado como proveedor.
_ORDEN_ADR001 = ["groq", "ollama", "gemini"]


@dataclass
class Eslabon:
    """Un proveedor de la cadena, con todo lo que hace falta para llamarlo."""
    proveedor: str
    api_key: str
    modelo: str


def _llamar_real(eslabon: Eslabon, historial: list, tools: list | None) -> str:
    """Como se llama de verdad a un eslabon (se inyecta otra en los tests
    para no tocar la red)."""
    return responder_proveedor(
        eslabon.proveedor, eslabon.api_key, eslabon.modelo, historial, tools,
    )


class LLMRouter:
    """Prueba una cadena de proveedores en orden. Por cada uno: reintenta
    con backoff exponencial si el fallo es transitorio (rate limit, timeout,
    red); si el fallo es fatal (clave mala, peticion invalida) o se agotan
    los reintentos, degrada al siguiente. Si TODOS fallan, relanza el ultimo
    error (nada se traga en silencio).
    """

    def __init__(self, eslabones: list[Eslabon], max_reintentos: int = 2,
                 backoff_base: float = 1.0, _dormir=time.sleep, _llamar=_llamar_real):
        if not eslabones:
            raise ValueError("La cadena del router no puede estar vacia.")
        self.eslabones = eslabones
        self.max_reintentos = max_reintentos
        self.backoff_base = backoff_base
        # _dormir y _llamar son "costuras" para los tests: se pueden inyectar
        # versiones falsas que ni duermen ni tocan la red.
        self._dormir = _dormir
        self._llamar = _llamar
        # Que proveedor respondio de verdad la ultima vez (util para logs y
        # para que el CLI/bot pueda avisar si respondio un fallback).
        self.ultimo_proveedor: str | None = None

    def responder(self, historial: list, tools: list | None) -> str:
        ultimo_error = None

        for indice, eslabon in enumerate(self.eslabones):
            es_primario = (indice == 0)

            # Bucle de reintentos DENTRO del mismo proveedor.
            for intento in range(self.max_reintentos + 1):
                try:
                    texto = self._llamar(eslabon, historial, tools)
                except ErrorLLM as error:
                    ultimo_error = error
                    quedan_reintentos = intento < self.max_reintentos

                    if error.reintentable and quedan_reintentos:
                        # Fallo transitorio y aun quedan intentos: espera
                        # creciente (1s, 2s, 4s...) y reintenta el MISMO.
                        espera = self.backoff_base * (2 ** intento)
                        logging.warning(
                            f"Router: {eslabon.proveedor} fallo reintentable "
                            f"({type(error).__name__}); reintento "
                            f"{intento + 1}/{self.max_reintentos} en {espera:.1f}s"
                        )
                        self._dormir(espera)
                        continue

                    # Fallo fatal, o agotados los reintentos: se abandona
                    # este proveedor y se prueba el siguiente de la cadena.
                    logging.warning(
                        f"Router: {eslabon.proveedor} agotado "
                        f"({type(error).__name__}); "
                        + ("degradando al siguiente proveedor"
                           if indice + 1 < len(self.eslabones)
                           else "no quedan mas proveedores")
                    )
                    break
                else:
                    # Exito. Si respondio un fallback (no el primario), se
                    # deja constancia clara en el log.
                    self.ultimo_proveedor = eslabon.proveedor
                    if not es_primario:
                        logging.info(
                            f"Router: respondio el fallback {eslabon.proveedor} "
                            f"(el primario {self.eslabones[0].proveedor} fallo)"
                        )
                    return texto

        # Si llegamos aqui, TODOS los proveedores fallaron. Relanzamos el
        # ultimo error para que el Agente lo convierta en mensaje_usuario.
        raise ultimo_error


def construir_cadena(proveedor_primario: str, api_key: str, modelo: str,
                     **kwargs_router) -> LLMRouter:
    """Arma un LLMRouter con el proveedor elegido como PRIMARIO y, de
    fallback, los demas proveedores de la cadena ADR-001 que tengan su clave
    configurada en el .env. Los que no tengan clave se saltan (no rompen):
    si solo hay una clave, la cadena es de un solo eslabon y se comporta
    como antes (sin fallback), pero sin codigo especial para ese caso.

    El modelo de cada fallback sale de obtener_modelo_por_defecto() (F5.0/T5:
    fuente unica de verdad = variable *_MODEL del .env, con el catalogo como
    respaldo) - la misma que usa el menu para el primario.
    """
    eslabones = [Eslabon(proveedor_primario, api_key, modelo)]

    for proveedor in _ORDEN_ADR001:
        if proveedor == proveedor_primario:
            continue  # el primario ya esta el primero
        try:
            clave = obtener_api_key(proveedor)
        except ClaveApiNoConfigurada:
            continue  # sin clave configurada: no puede ser fallback
        eslabones.append(Eslabon(proveedor, clave, obtener_modelo_por_defecto(proveedor)))

    return LLMRouter(eslabones, **kwargs_router)
