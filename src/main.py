# sys: para forzar la codificacion de la salida estandar a UTF-8 (ver
# comentario justo debajo).
import sys
# questionary: libreria para menus interactivos en terminal (flechas + Enter).
import questionary

# Forzamos UTF-8 en stdout SIEMPRE, sin depender de que la terminal
# donde se ejecute este programa lo tenga configurado asi. Hallazgo
# real de F4.3: un modelo devolvio un caracter Unicode poco comun
# (un "espacio estrecho" para agrupar digitos), y con la codificacion
# por defecto de algunas consolas (cp1252 en parte de Windows) un
# print() normal con ese caracter revienta el programa entero con
# UnicodeEncodeError. errors="replace": si algun caracter fuera IMPOSIBLE
# de mostrar ni asi, se sustituye por un simbolo en vez de crashear -
# coherente con RNF-02 (el programa avisa y sigue vivo, nunca se cae).
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# Traemos de config.py: la funcion para leer la clave del proveedor
# elegido, el diccionario PROVEEDORES (nombres de proveedor) y MODELOS
# (lista de modelos disponibles por proveedor).
from src.config import obtener_api_key, PROVEEDORES, MODELOS
# Traemos de llm_client.py: preguntar() para /resumen (no necesita
# tools), preguntar_con_tools() para el turno normal (F4.3 - el modelo
# puede pedir usar la calculadora si hace falta).
from src.llm_client import preguntar, preguntar_con_tools
# Traemos de storage.py la funcion que guarda la conversacion en disco.
from src.storage import guardar_conversacion

# SYSTEM PROMPT: instrucciones ESTABLES del asistente (quien es, como
# habla, que limites tiene). Va una sola vez al principio del historial
# y no cambia en toda la conversacion. Lo que cambia en cada turno (la
# pregunta concreta) va en mensajes con rol "user", nunca aqui.
#
# String triple-comilla (""") en vez de varios strings pegados: la
# version anterior tenia un bug real - "cuando encaja." pegado sin coma
# a "**Como respondes**" se concatenaba solo, sin separador, y el modelo
# recibia todo el prompt como un unico parrafo aplastado (mismo bug que
# ya se documento en el diario el 17/07, F2.6b - coleado aqui tambien).
# Con """ los saltos de linea son literales y no hay forma de que pase.
SYSTEM_PROMPT = """Eres el asistente personal de Jordi. Hablas siempre en español, de tú, con tono cercano y con chispa - como un amigo que sabe de lo que habla, no como un bot corporativo. Se te permite tener opinión y personalidad propia; no tienes que sonar neutro todo el rato.

Cómo respondes:
- Ve al grano, pero sin cortar de más: si la pregunta pide una respuesta corta, que sea corta; si pide explicación, tómate el espacio que haga falta. No fuerces la brevedad cuando resta claridad.
- Si no sabes algo o no estás seguro, dilo explícitamente en vez de inventar una respuesta que suene convincente.
- En temas normales puedes opinar con soltura; en política o religión evita mojarte, esquívalo con humor y redirige, sin sermonear.

Para qué sirves:
- Recordar tareas, pendientes y cosas que Jordi te cuente sobre su vida, y usarlas cuando vengan a cuento más adelante.
- Responder con precisión, ayudar a planificar el día, tomar notas, resumir.
- Charlar sin más, cuando lo que se busca es compañía, no una tarea.

Cómo actúas:
- Si el encargo es ambiguo, haz UNA pregunta concreta antes de lanzarte.
- Si está claro lo que se pide, hazlo directo, sin pedir permiso de más.

Siempre en español, aunque te escriban en otro idioma."""


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
    print("Escribe 'salir' para terminar, '/modelo' o '/proveedor' para cambiar, '/resumen' para resumir.")

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

            # F3.6 (extra): pide al propio modelo que resuma la conversacion
            # hasta ahora. OJO: construimos una lista NUEVA (historial + la
            # peticion de resumen), no modificamos "historial" - el resumen
            # es una consulta de lectura, no un turno mas de la conversacion.
            # Si lo guardaramos en el historial real, cada vez que pidas otro
            # resumen estarias resumiendo (entre otras cosas) resumenes
            # anteriores, en vez de la conversacion original.
            if comando == "/resumen":
                peticion = historial + [{
                    "role": "user",
                    "content": "Resume la conversacion anterior en pocas frases, "
                                "destacando solo lo mas importante.",
                }]
                resumen = preguntar(peticion, proveedor, api_key, modelo)
                print(f"Resumen: {resumen}")
                continue

            # 1) La pregunta entra al historial ANTES de llamar: la API tiene
            #    que recibir la lista con este ultimo mensaje ya incluido.
            historial.append({"role": "user", "content": pregunta})

            # 2) Ya no mandamos la pregunta suelta: mandamos la lista completa.
            #    preguntar_con_tools() puede usar la calculadora por dentro
            #    (F4.3) si el modelo decide que la necesita - main.py no
            #    tiene que enterarse de ese ir-y-venir, solo recibe el
            #    texto final, igual que antes de tener tools.
            respuesta = preguntar_con_tools(historial, proveedor, api_key, modelo)

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