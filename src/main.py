# questionary: libreria para menus interactivos en terminal (flechas + Enter).
import questionary
# Traemos de config.py: la funcion para leer la clave del proveedor
# elegido, el diccionario PROVEEDORES (nombres de proveedor) y MODELOS
# (lista de modelos disponibles por proveedor).
from src.config import obtener_api_key, PROVEEDORES, MODELOS
# Traemos de llm_client.py la funcion que hace la pregunta de verdad.
from src.llm_client import preguntar


def elegir_proveedor() -> str:
    """Muestra un menu de flechas con los proveedores disponibles."""
    return questionary.select(
        "¿Qué proveedor quieres usar?",
        choices=list(PROVEEDORES.keys()),
    ).ask()


def elegir_modelo(proveedor: str) -> str:
    """Muestra un menu de flechas con los modelos del proveedor ya elegido."""
    return questionary.select(
        "¿Qué modelo quieres usar?",
        choices=MODELOS[proveedor],
    ).ask()


def main():
    # Primero se elige el proveedor...
    proveedor = elegir_proveedor()
    # ...y con ese proveedor ya sabido, se elige uno de sus 3 modelos.
    modelo = elegir_modelo(proveedor)
    api_key = obtener_api_key(proveedor)

    print(f"Agente listo con {proveedor} ({modelo}).")
    print("Escribe 'salir' para terminar, '/modelo' o '/proveedor' para cambiar.")
    
    while True:
        pregunta = input("Tú: ")
        comando = pregunta.strip().lower()

        if comando == "salir":
            print("Agente: ¡Hasta luego!")
            break

        # Comando para cambiar solo el modelo, sin tocar el proveedor.
        if comando == "/modelo":
            modelo = elegir_modelo(proveedor)
            print(f"Modelo cambiado a: {modelo}")
            continue  # vuelve al principio del bucle, no manda nada al LLM

        # Comando para cambiar de proveedor - hay que volver a pedir modelo
        # (la lista de modelos depende del proveedor) y la clave tambien cambia.
        if comando == "/proveedor":
            proveedor = elegir_proveedor()
            modelo = elegir_modelo(proveedor)
            api_key = obtener_api_key(proveedor)
            print(f"Proveedor cambiado a: {proveedor} ({modelo})")
            continue

        respuesta = preguntar(pregunta, proveedor, api_key, modelo)
        print(f"Agente: {respuesta}")


if __name__ == "__main__":
    main()