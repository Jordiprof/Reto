# Traemos del config.py: la funcion para leer las credenciales del
# proveedor elegido, y el diccionario PROVEEDORES (para saber que
# opciones existen y mostrarlas al usuario).
from src.config import obtener_credenciales, PROVEEDORES

# Traemos de llm_client.py la funcion que hace la pregunta de verdad.
from src.llm_client import preguntar


def elegir_proveedor() -> str:
    """Pregunta al usuario que proveedor quiere usar, hasta que escriba uno valido."""
    # .keys() saca los nombres del diccionario PROVEEDORES ("groq", "ollama", "gemini").
    # list(...) los convierte en una lista para poder usarlos varias veces.
    opciones = list(PROVEEDORES.keys())

    while True:
        # "/".join(opciones) junta la lista en un texto tipo "groq/ollama/gemini"
        # para mostrarlo en el mensaje.
        elegido = input(f"¿Qué proveedor quieres usar? ({'/'.join(opciones)}): ").strip().lower()

        # "in" comprueba si lo escrito esta dentro de la lista de opciones validas.
        if elegido in opciones:
            return elegido

        print(f"Proveedor no válido. Opciones: {', '.join(opciones)}")


def main():
    proveedor = elegir_proveedor()

    # Pide a config.py las credenciales (clave y modelo) SOLO de este
    # proveedor concreto - no de los otros tres.
    api_key, modelo = obtener_credenciales(proveedor)

    print(f"Agente listo con {proveedor} ({modelo}). Escribe 'salir' para terminar.")

    while True:
        pregunta = input("Tú: ")
        if pregunta.strip().lower() == "salir":
            print("Agente: ¡Hasta luego!")
            break

        # Le pasamos a preguntar() todo lo que necesita: el texto, que
        # proveedor usar, y las credenciales de ese proveedor.
        respuesta = preguntar(pregunta, proveedor, api_key, modelo)
        print(f"Agente: {respuesta}")


# Solo se ejecuta si lanzas este fichero directamente con "python -m src.main".
if __name__ == "__main__":
    main()