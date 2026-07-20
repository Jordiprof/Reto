# json: para serializar el historial (lista de diccionarios) a disco.
import json
# sqlite3: viene con Python, no hace falta instalar nada. Nos da un motor
# de base de datos relacional que vive en un solo fichero (.db).
import sqlite3
# datetime: para generar la fecha/hora que va en el nombre del fichero.
from datetime import datetime
# Path: manejo de rutas multiplataforma, igual que en config.py.
from pathlib import Path

# Carpeta donde se guardan las conversaciones. Mismo patron que LOGS_DIR en
# config.py: ruta absoluta relativa a ESTE fichero (no al directorio desde
# donde se ejecute el script), para que funcione igual sin importar desde
# donde se lance `python -m src.main`.
CONVERSATIONS_DIR = Path(__file__).resolve().parent.parent / "conversations"
CONVERSATIONS_DIR.mkdir(exist_ok=True)

# F3.5 (ADR-002): "intro SQLite". El JSON (arriba) sigue siendo la fuente
# COMPLETA de cada conversacion - esta base de datos es solo un INDICE
# consultable con SQL (fecha, proveedor, modelo, cuantos mensajes, y la
# ruta al JSON con el contenido real). Duplicar el contenido entero en
# SQL es trabajo de Fase Avanzada (ADR-002), no de esta introduccion.
DB_PATH = Path(__file__).resolve().parent.parent / "conversations.db"


def _inicializar_db() -> None:
    """Crea la tabla 'conversaciones' si todavia no existe.

    CREATE TABLE IF NOT EXISTS: no falla si ya esta creada de una
    ejecucion anterior - se puede llamar en cada arranque sin problema.
    """
    with sqlite3.connect(DB_PATH) as conexion:
        conexion.execute(
            """
            CREATE TABLE IF NOT EXISTS conversaciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT,
                proveedor TEXT,
                modelo TEXT,
                ruta_json TEXT,
                num_mensajes INTEGER
            )
            """
        )
    # El "with" hace conexion.commit() automaticamente al salir sin
    # errores (y rollback si hay excepcion) - OJO, NO cierra la conexion
    # por si sola, pero como no la reutilizamos, Python la libera sola
    # al salir de la funcion.


def _indexar_en_sqlite(ruta_json: Path, proveedor: str, modelo: str, num_mensajes: int) -> None:
    """Inserta una fila en conversaciones.db apuntando al JSON real.

    Con "?" como placeholder (nunca con f-strings) se evita SQL injection:
    sqlite3 se encarga de escapar el valor, aunque aqui el dato venga de
    variables internas del programa, no de un usuario externo - es la
    forma correcta de hacerlo siempre, por costumbre segura.
    """
    _inicializar_db()
    with sqlite3.connect(DB_PATH) as conexion:
        conexion.execute(
            "INSERT INTO conversaciones (fecha, proveedor, modelo, ruta_json, num_mensajes) "
            "VALUES (?, ?, ?, ?, ?)",
            (datetime.now().isoformat(), proveedor, modelo, str(ruta_json), num_mensajes),
        )


def guardar_conversacion(historial: list, proveedor: str, modelo: str) -> Path | None:
    """Guarda la conversacion en un .json con fecha/hora en el nombre.

    Devuelve la ruta del fichero creado, o None si no habia nada real que
    guardar (el usuario escribio "salir" sin llegar a preguntar nada: el
    historial solo tiene el system prompt, ni un turno de conversacion).
    Evita llenar conversations/ de ficheros basura de sesiones vacias.
    """
    # historial[0] es siempre el system prompt (ver main.py); si no hay
    # nada mas, no hubo conversacion que merezca guardarse.
    if len(historial) <= 1:
        return None

    # strftime con "-" en vez de ":" (Windows no permite ":" en nombres de
    # fichero) y en orden año-mes-dia_hora-min-seg: ordena alfabeticamente
    # igual que cronologicamente.
    marca_tiempo = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    ruta = CONVERSATIONS_DIR / f"{marca_tiempo}.json"

    # Envolvemos el historial con metadatos. OJO: proveedor/modelo son los
    # ULTIMOS usados en la conversacion - si se cambio con /proveedor a
    # mitad de charla, aqui solo queda el final, no el historial de
    # cambios. Simplificacion consciente de F3.3, documentada en el diario.
    datos = {
        "fecha": datetime.now().isoformat(),
        "proveedor": proveedor,
        "modelo": modelo,
        "historial": historial,
    }

    # ensure_ascii=False: sin esto, cada tilde/eñe saldria escapada como
    # "ó" en vez de legible al abrir el fichero a mano. indent=2:
    # formato legible, no una sola linea larga.
    with open(ruta, "w", encoding="utf-8") as fichero:
        json.dump(datos, fichero, ensure_ascii=False, indent=2)

    # F3.5: ademas del JSON (fuente completa), dejamos una fila-indice en
    # SQLite. Si esto fallara por lo que sea, no queremos perder el JSON
    # ya guardado - por eso va DESPUES y en su propia funcion, no antes.
    _indexar_en_sqlite(ruta, proveedor, modelo, len(historial))

    return ruta
