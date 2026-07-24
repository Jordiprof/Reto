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
# F4.5: toda la logica de la conversacion (historial, tools, resumen,
# guardado) vive ahora en agent.py - main.py solo habla con un Agente
# a traves de sus metodos, no conoce ni un detalle de como funciona
# por dentro. Esto es lo que permitira reutilizar Agente con Telegram
# en Fase 5, sin tocar nada de su logica interna.
# noqa: E402 en las dos siguientes - van DESPUES de sys.stdout.reconfigure()
# a proposito (ver comentario de arriba): si un import disparara un print()
# con un caracter raro antes de reconfigurar stdout, el programa reventaria.
from src.agent import Agente  # noqa: E402
from src.config import (  # noqa: E402
    MODELOS,
    PROVEEDORES,
    ClaveApiNoConfigurada,
    obtener_api_key,
    obtener_modelo_por_defecto,
)

# cifrado_activo: para avisar al arrancar si las conversaciones se van a
# guardar sin cifrar (F5.3). main.py es la capa que habla con el usuario;
# storage.py solo expone el dato, no imprime nada.
from src.storage import cifrado_activo  # noqa: E402

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
SYSTEM_PROMPT = """Eres el asistente personal de Jordi. Hablas siempre en español, de tú, \
con tono cercano y con chispa - como un amigo que sabe de lo que habla, no como un bot \
corporativo. Se te permite tener opinión y personalidad propia; no tienes que sonar \
neutro todo el rato.

Cómo respondes:
- Ve al grano, pero sin cortar de más: si la pregunta pide una respuesta corta, que sea \
corta; si pide explicación, tómate el espacio que haga falta. No fuerces la brevedad \
cuando resta claridad.
- Si no sabes algo o no estás seguro, dilo explícitamente en vez de inventar una \
respuesta que suene convincente.
- En temas normales puedes opinar con soltura; en política o religión evita mojarte, \
esquívalo con humor y redirige, sin sermonear.

Para qué sirves:
- Recordar tareas, pendientes y cosas que Jordi te cuente sobre su vida, y usarlas \
cuando vengan a cuento más adelante.
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
    """Muestra un menu de flechas con los modelos del proveedor ya elegido.

    F5.0/T5: el modelo por defecto del .env aparece YA preseleccionado (basta
    pulsar Enter para usarlo). questionary exige que 'default' sea uno de los
    choices, asi que si el modelo del .env no esta en el catalogo, no se pasa
    (queda seleccionado el primero de la lista)."""
    catalogo = MODELOS[proveedor]
    por_defecto = obtener_modelo_por_defecto(proveedor)
    return questionary.select(
        "¿Qué modelo quieres usar?",
        choices=catalogo,
        default=por_defecto if por_defecto in catalogo else None,
    ).ask()


def main():
    # Primero se elige el proveedor...
    proveedor = elegir_proveedor()
    # ...y con ese proveedor ya sabido, se elige uno de sus 3 modelos.
    modelo = elegir_modelo(proveedor)
    # F5.0/T2 (AUD-06): si falta la API key en .env, avisar con claridad y
    # salir - NO reventar con un traceback (RNF-02).
    try:
        api_key = obtener_api_key(proveedor)
    except ClaveApiNoConfigurada as error:
        print(f"⚠️ {error}")
        return

    # El Agente es quien lleva de verdad la conversacion (historial,
    # tools, resumen, guardado) - main.py solo lo crea y le pregunta.
    agente = Agente(SYSTEM_PROMPT, proveedor, api_key, modelo)

    print(f"Agente listo con {proveedor} ({modelo}).")
    # F5.3: el cifrado de las conversaciones es opcional, pero si esta
    # apagado hay que DECIRLO. Un aviso solo en logs/agente.log no sirve:
    # nadie lee el log mientras usa el programa, y una degradacion de
    # seguridad que nadie ve es como si no existiera.
    if not cifrado_activo():
        print(
            "⚠️ Las conversaciones se guardaran SIN CIFRAR "
            "(configura CONVERSATIONS_KEY en el .env; ver .env.example)."
        )
    print(
        "Escribe 'salir' para terminar, '/modelo' o '/proveedor' para cambiar, "
        "'/resumen' para resumir."
    )

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
                agente.cambiar_modelo(modelo)
                print(f"Modelo cambiado a: {modelo}")
                continue  # vuelve al principio del bucle, no manda nada al LLM

            # Comando para cambiar de proveedor - hay que volver a pedir modelo
            # (la lista de modelos depende del proveedor) y la clave tambien cambia.
            # OJO: el historial NO se borra al cambiar - el Agente lo hereda
            # tal cual (formato canonico, ver F3.1). Puedes empezar a hablar
            # con Groq y seguir la MISMA charla con Gemini.
            if comando == "/proveedor":
                nuevo_proveedor = elegir_proveedor()
                nuevo_modelo = elegir_modelo(nuevo_proveedor)
                # Si falta la API key de este proveedor, avisamos y
                # seguimos con el proveedor/modelo que ya teniamos (RNF-02:
                # avisa y sigue vivo, en vez de perder la sesion en curso).
                try:
                    api_key = obtener_api_key(nuevo_proveedor)
                except ClaveApiNoConfigurada as error:
                    print(f"⚠️ {error}")
                    continue
                proveedor, modelo = nuevo_proveedor, nuevo_modelo
                agente.cambiar_proveedor(proveedor, modelo, api_key)
                print(f"Proveedor cambiado a: {proveedor} ({modelo})")
                continue

            # F3.6 (extra): pide al propio modelo que resuma la conversacion.
            if comando == "/resumen":
                print(f"Resumen: {agente.resumir()}")
                continue

            # Un turno completo (historial, tools, guardado del turno) lo
            # resuelve el Agente por dentro - main.py solo imprime.
            respuesta = agente.preguntar(pregunta)
            print(f"Agente: {respuesta}")
    except KeyboardInterrupt:
        # Ctrl+C dispara esta excepcion en vez de reventar con un
        # traceback feo. La atrapamos solo para avisar con un mensaje
        # limpio - el guardado real pasa en el finally de abajo.
        print("\nAgente: interrumpido, guardando la conversación...")
    finally:
        # Se ejecuta SIEMPRE: tanto tras el break de "salir" como tras el
        # except de arriba. agente.guardar() ya decide por dentro si hay
        # algo real que guardar (ver storage.py).
        ruta = agente.guardar()
        if ruta:
            print(f"Conversación guardada en conversations/{ruta.name}")


if __name__ == "__main__":
    main()
