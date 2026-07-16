from src.llm_client import preguntar


def main():
    print("Agente listo. Escribe 'salir' para terminar.")
    while True:
        pregunta = input("Tú: ")
        if pregunta.strip().lower() == "salir":
            print("Agente: ¡Hasta luego!")
            break
        respuesta = preguntar(pregunta)
        print(f"Agente: {respuesta}")


if __name__ == "__main__":
    main()