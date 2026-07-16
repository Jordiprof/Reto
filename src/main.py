from src.llm_client import preguntar

# Este if evita que el codigo se ejecute si algun dia importas este
# fichero desde otro sitio; solo corre cuando lo lanzas directamente.
if __name__ == "__main__":
    pregunta = "¿Qué es un LLM, en una frase?"
    print(f"Tú: {pregunta}")
    print(f"Agente: {preguntar(pregunta)}")