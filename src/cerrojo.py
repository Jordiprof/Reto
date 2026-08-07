# Cerrojo entre PROCESOS para la memoria compartida (01/08).
#
# POR QUE EXISTE: `conversations/` y sobre todo el indice de ChromaDB estan
# pensados para UN proceso. ChromaDB usa `PersistentClient`, que es una base
# de datos embebida: dos procesos escribiendo a la vez pueden corromper el
# indice. Hasta hoy esto era un LIMITE DOCUMENTADO con un aviso por pantalla,
# y dejo de serlo porque ya paso DOS veces de verdad:
#   - 31/07: Jordi ejecuto `main.py` con el bot arrancado.
#   - 01/08: apareciero DOS `python -m src.telegram_bot` a la vez.
# El segundo caso ademas rompe cosas que no son la base de datos: el estado
# del bot (que conversacion tienes abierta, si te ha pedido un nombre, los
# interruptores de voz) vive en RAM de CADA proceso, asi que pulsar un boton
# en una instancia y contestar en la otra pierde el estado sin dar ningun
# error - un fallo invisible y dificil de diagnosticar.
#
# EL RLock DE rag.py NO SIRVE PARA ESTO: protege HILOS dentro de un proceso.
# Dos procesos no comparten ese objeto.
#
# POR QUE UN CERROJO DEL SISTEMA OPERATIVO Y NO UN FICHERO CON EL PID:
# un fichero-PID hay que limpiarlo a mano, y si el proceso muere de golpe
# (Ctrl+C mal, corte de luz, kill -9) queda un cerrojo FANTASMA que bloquea
# los arranques siguientes hasta que alguien borra el fichero. Un cerrojo
# del SO lo suelta el propio SO al morir el proceso, pase lo que pase: no
# hay estado que limpiar y no existe el caso "bloqueado para siempre".
# Ademas evita la carrera del PID reutilizado.
import os
from pathlib import Path

_RUTA_POR_DEFECTO = Path(__file__).resolve().parent.parent / ".memoria.lock"


class MemoriaOcupada(Exception):
    """Ya hay otro proceso usando la memoria compartida."""


class CerrojoMemoria:
    """Cerrojo exclusivo, no bloqueante, sobre un fichero centinela.

    No bloqueante A PROPOSITO: si el recurso esta cogido queremos AVISAR y
    salir, no quedarnos esperando en silencio a que el otro termine - que
    desde fuera se ve igual que un bot colgado.

    Se usa como context manager:

        with CerrojoMemoria():
            ...

    o a mano con tomar()/soltar() cuando el ciclo de vida no encaja en un
    bloque (el bot corre hasta que lo paran).
    """

    def __init__(self, ruta: Path | None = None, quien: str = "otro proceso"):
        self.ruta = Path(ruta) if ruta else _RUTA_POR_DEFECTO
        self.quien = quien
        self._fichero = None

    def tomar(self) -> "CerrojoMemoria":
        # "a+" y no "w": abrir en modo escritura TRUNCA el fichero, y
        # truncarlo es escribir - o sea que borrariamos el contenido del
        # centinela ANTES de saber si teniamos derecho a cogerlo.
        fichero = open(self.ruta, "a+", encoding="utf-8")
        try:
            _bloquear(fichero)
        except OSError:
            fichero.close()
            raise MemoriaOcupada(
                "Ya hay otro proceso usando la memoria (el bot o la terminal).\n"
                "Solo puede haber UNO a la vez: dos procesos sobre el mismo índice "
                "de ChromaDB pueden corromperlo, y además cada uno tendría su propio "
                "estado en memoria.\n"
                "Cierra el que esté abierto y vuelve a intentarlo."
            ) from None

        # Quien lo tiene. Es solo INFORMATIVO; el cerrojo de verdad es el
        # del SO, no este texto.
        #
        # OJO con su utilidad real, comprobado al escribir los tests: en
        # Windows `msvcrt.locking` bloquea el rango de bytes de verdad, asi
        # que mientras el cerrojo esta cogido, leer el fichero desde fuera
        # da PermissionError. Sirve para saber DESPUES quien lo tuvo, no
        # para curiosear mientras corre.
        try:
            fichero.seek(0)
            fichero.truncate()
            fichero.write(f"{self.quien} pid={os.getpid()}\n")
            fichero.flush()
        except OSError:
            pass  # no poder anotar quien es no es motivo para no arrancar

        self._fichero = fichero
        return self

    def soltar(self) -> None:
        if self._fichero is None:
            return
        try:
            _desbloquear(self._fichero)
        except OSError:
            pass  # al cerrar el fichero el SO lo suelta igual
        finally:
            self._fichero.close()
            self._fichero = None

    def __enter__(self) -> "CerrojoMemoria":
        return self.tomar()

    def __exit__(self, *excepcion) -> None:
        self.soltar()


# --- La parte que depende del sistema operativo ----------------------------
# Se resuelve al importar y no en cada llamada. Los dos mecanismos tienen la
# misma propiedad, que es la que nos importa: el SO suelta el cerrojo cuando
# el proceso muere, sin que nadie tenga que limpiar nada.

if os.name == "nt":
    import msvcrt

    def _bloquear(fichero) -> None:
        # LK_NBLCK = "non-blocking lock": si no puede, lanza OSError en vez
        # de quedarse esperando. Se bloquea 1 byte, que basta: el fichero es
        # un centinela, no guarda datos.
        fichero.seek(0)
        msvcrt.locking(fichero.fileno(), msvcrt.LK_NBLCK, 1)

    def _desbloquear(fichero) -> None:
        fichero.seek(0)
        msvcrt.locking(fichero.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _bloquear(fichero) -> None:
        # LOCK_NB = no bloqueante, mismo criterio que arriba. Hace falta
        # aunque el proyecto corra en Windows: el CI de GitHub Actions es
        # Linux y estos tests se ejecutan alli.
        fcntl.flock(fichero.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _desbloquear(fichero) -> None:
        fcntl.flock(fichero.fileno(), fcntl.LOCK_UN)
