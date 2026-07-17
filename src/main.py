# Traemos de config.py: la funcion para leer la clave del proveedor
# elegido, el diccionario PROVEEDORES (nombres de proveedor) y MODELOS
# (lista de modelos disponibles por proveedor).
from src.config import obtener_api_key, PROVEEDORES, MODELOS
# Traemos de llm_client.py la funcion que hace la pregunta de verdad.
from src.llm_client import preguntar


def elegir_de_lista(pregunta: str, opciones: list) -> str:
    """Funcion generica: sirve tanto para elegir proveedor como modelo."""
    while True:
        # "/".join(opciones) junta la lista en texto tipo "a/b/c" para mostrarlo.
        elegido = input(f"{pregunta} ({'/'.join(opciones)}): ").strip().lower()
        # "in" comprueba si lo escrito esta dentro de la lista valida.
        if elegido in opciones:
            return elegido
        print(f"Opción no válida. Opciones: {', '.join(opciones)}")


def main():
    # Primero se elige el proveedor...
    proveedor = elegir_de_lista("¿Qué proveedor quieres usar?", list(PROVEEDORES.keys()))
    # ...y con ese proveedor ya sabido, se elige uno de sus 3 modelos.
    modelo = elegir_de_lista("¿Qué modelo quieres usar?", MODELOS[proveedor])
    api_key = obtener_api_key(proveedor)

    print(f"Agente listo con {proveedor} ({modelo}). Escribe 'salir' para terminar.")

    while True:
        pregunta = input("Tú: ")
        if pregunta.strip().lower() == "salir":
            print("Agente: ¡Hasta luego!")
            break
        respuesta = preguntar(pregunta, proveedor, api_key, modelo)
        print(f"Agente: {respuesta}")


# Solo se ejecuta si lanzas este fichero directamente con "python -m src.main".
if __name__ == "__main__":
    main()