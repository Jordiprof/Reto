# questionary: libreria para menus interactivos en terminal (flechas + Enter).
import questionary
# Traemos de config.py: la funcion para leer la clave del proveedor
# elegido, el diccionario PROVEEDORES (nombres de proveedor) y MODELOS
# (lista de modelos disponibles por proveedor).
from src.config import obtener_api_key, PROVEEDORES, MODELOS
# Traemos de llm_client.py la funcion que hace la pregunta de verdad.
from src.llm_client import preguntar
# Traemos de storage.py la funcion que guarda la conversacion en disco.
from src.storage import guardar_conversacion

# SYSTEM PROMPT: instrucciones ESTABLES del asistente (quien es, como
# habla, que limites tiene). Va una sola vez al principio del historial
# y no cambia en toda la conversacion. Lo que cambia en cada turno (la
# pregunta concreta) va en mensajes con rol "user", nunca aqui.
SYSTEM_PROMPT = (
    "Eres mi asistente personal. Hablas siempre en español, de tú, con tono cercano y "
    "natural — como un amigo listo, no como un robot corporativo. Usas humor ligero "
    "cuando encaja."
    "**Cómo respondes**"
    "- Siempre corto y directo. Si cabe en dos frases, dos frases."
    "- Nunca des más contexto del que se pidió."
    "- No te salgas del tema por voluntad propia."
    "- No opines sobre política ni religión — si te preguntan, esquívalo con gracia "
    "  y redirige."
    "**Para qué sirves**"
    "- Anotar y recordar tareas, pendientes y plazos."
    "- Responder preguntas con precisión (si no sabes algo, dilo)."
    "- Ayudar a planificar el día, tomar notas y resumir cosas."
    "- Conversar de forma natural cuando el usuario quiere charlar."
    "**Cómo actúas**"
    "- Si algo no está claro, haz UNA pregunta concreta antes de actuar."
    "- Si es obvio lo que se pide, hazlo directamente sin pedir confirmación."
    "- Aprende de la conversación: si el usuario comparte algo de su vida, recuérdalo "
    "  y úsalo cuando sea relevante."
    "**Idioma:** Siempre en español, aunque el usuario escriba en otro idioma."
)


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

    # El historial ES la memoria de la conversacion. El modelo no recuerda
    # nada entre llamadas: en cada turno le reenviamos esta lista entera y
    # el genera "la siguiente linea de la transcripcion". Arranca con el
    # system prompt y solo crece (cada turno añade 2 mensajes: user + assistant).
    historial = [{"role": "system", "content": SYSTEM_PROMPT}]

    # try/finally alrededor de TODO el bucle: asi la conversacion se
    # guarda tanto si sales escribiendo "salir" (break normal) como si
    # cierras de golpe con Ctrl+C (KeyboardInterrupt) - el finally se
    # ejecuta siempre, pase lo que pase dentro del bucle.
    try:
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
            # OJO: el historial NO se borra al cambiar - como esta en formato
            # canonico, el proveedor nuevo hereda la conversacion entera. Puedes
            # empezar a hablar con Groq y seguir la MISMA charla con Gemini.
            if comando == "/proveedor":
                proveedor = elegir_proveedor()
                modelo = elegir_modelo(proveedor)
                api_key = obtener_api_key(proveedor)
                print(f"Proveedor cambiado a: {proveedor} ({modelo})")
                continue

            # 1) La pregunta entra al historial ANTES de llamar: la API tiene
            #    que recibir la lista con este ultimo mensaje ya incluido.
            historial.append({"role": "user", "content": pregunta})

            # 2) Ya no mandamos la pregunta suelta: mandamos la lista completa.
            respuesta = preguntar(historial, proveedor, api_key, modelo)

            # 3) La respuesta tambien se guarda - el modelo NO recuerda ni sus
            #    propias respuestas; si no la añadimos, en el siguiente turno
            #    "olvidaria" lo que acaba de decir. EXCEPCION: si la llamada
            #    fallo, las funciones de llm_client.py devuelven un aviso que
            #    empieza por "⚠️" (nunca texto real del modelo) - eso NO es un
            #    turno de conversacion valido. Si lo guardaramos, se reenviaria
            #    como si el asistente lo hubiera dicho de verdad, y el modelo
            #    empezaria a "razonar" sobre su propio mensaje de error en
            #    turnos futuros. La pregunta del usuario SI queda guardada
            #    (es real); solo se descarta la respuesta rota.
            if not respuesta.startswith("⚠️"):
                historial.append({"role": "assistant", "content": respuesta})

            print(f"Agente: {respuesta}")
    except KeyboardInterrupt:
        # Ctrl+C dispara esta excepcion en vez de reventar con un
        # traceback feo. La atrapamos solo para avisar con un mensaje
        # limpio - el guardado real pasa en el finally de abajo.
        print("\nAgente: interrumpido, guardando la conversación...")
    finally:
        # Se ejecuta SIEMPRE: tanto tras el break de "salir" como tras el
        # except de arriba. guardar_conversacion() ya decide por dentro
        # si hay algo real que guardar (ver storage.py).
        ruta = guardar_conversacion(historial, proveedor, modelo)
        if ruta:
            print(f"Conversación guardada en conversations/{ruta.name}")


if __name__ == "__main__":
    main()