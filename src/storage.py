# json: para serializar el historial (lista de diccionarios) a disco.
import json
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

    return ruta
