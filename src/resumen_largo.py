"""Condensar un documento (o una web) ENTERO en un .md, por bloques.

QUE PROBLEMA CIERRA. `leer_documento` resuelve "que dice sobre X": trocea,
busca por significado y manda los fragmentos que hablan de eso. Lo que NO
resuelve es "resumemelo entero": para eso se mandan los primeros 20.000
caracteres y el resumen sale cojo. El problema no es como lo redacta, es
QUE VE.

POR QUE NO ES UNA TOOL, y es la decision de diseño importante. Esto son N
llamadas al LLM. Si viviera dentro de una tool tendriamos al modelo
llamando a una tool que llama al modelo, y eso rompe tres cosas que ya
funcionan: el presupuesto por turno (SEG-03) cuenta las llamadas para que
un mensaje no dispare 45; el bucle de tools espera que una tool tarde
milisegundos, no medio minuto; y la memoria de LOG-07 guardaria un
resultado enorme para reutilizarlo. Es un COMANDO, que orquesta las
llamadas FUERA del bucle de tools - igual que `Agente.resumir()` desde
F3.6.

LAS DOS PASADAS.
  1. MAPA: cada bloque se lee entero y salen SUS puntos destacados. El
     modelo decide que es importante en ese trozo, sin cuota de longitud.
  2. REDUCCION: todos los puntos juntos se ordenan en el documento final
     con la plantilla de abajo.
La pasada 2 existe PORQUE hay troceo: si cupiera todo de una, el modelo ya
lo habria visto todo y escribiria el resultado directamente.

POR QUE HAY QUE TROCEAR AUNQUE QUEPA (medido el 02/08 en documentacion
oficial). No es por el tamaño del modelo -llama-3.3 admite 131.072 tokens
de entrada, unas 485 hojas- sino por la CUOTA POR MINUTO del plan gratuito:

    llama-3.3-70b (Groq)  12.000 tokens/minuto  ->  ~44 hojas por minuto
    gpt-oss-120b  (Groq)   8.000 tokens/minuto
    gemini-2.5-flash     250.000 tokens/minuto  ->  ~925 hojas por minuto

Un documento de 300 hojas son ~81.000 tokens: SIETE VECES lo que Groq deja
gastar en un minuto entero, asi que la peticion se rechaza antes de salir.
En gemini-2.5-flash cabe de una pieza y sobra sitio. De ahi que el comando
prefiera Gemini y trocee fino con los demas.
"""
import logging
import unicodedata
from datetime import datetime
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent

# Donde se dejan los .md generados (gitignored: son datos de JIM).
RESUMENES_DIR = _RAIZ / "resumenes"

# Cuanto texto va en cada bloque, segun lo que aguante el proveedor por
# minuto. No son numeros a ojo: salen de la tabla de arriba, dejando margen
# para la respuesta (que tambien cuenta en la cuota) y contando ~3,7
# caracteres por token en español.
#
#   AMPLIO    60.000 car ~ 16.000 tokens -> cabe en los 250.000/min de Gemini
#   ESTRECHO  20.000 car ~  5.400 tokens -> cabe en los  8.000/min del mas justo
#
# EL AMPLIO ERA DE 200.000 Y SE BAJO A 60.000 (02/08, tras la primera
# prueba real). Cabia en cuota, si, pero la CUOTA NO ES EL UNICO LIMITE: un
# bloque de 200.000 caracteres son ~54.000 tokens que el modelo tiene que
# leerse ENTEROS antes de escribir una palabra, y eso son minutos por
# llamada. Con el PDF de Jordi (284 fragmentos) salio UN bloque gigante y
# los tres proveedores se quedaron sin tiempo. Con 60.000 son tres bloques
# que Gemini despacha igual de rapido -le caben los tres en el mismo
# minuto- y ninguno se eterniza.
#
# La leccion, que es la misma del tamaño de trozo del 01/08: el numero se
# MIDE probando, no se elige por ser redondo.
CARACTERES_BLOQUE_AMPLIO = 60_000
CARACTERES_BLOQUE_ESTRECHO = 20_000

# Tope de bloques (decision de Jordi, 02/08). Con el bloque estrecho son
# ~200 hojas, y unos 54.000 tokens: la MITAD de la cuota diaria de Groq
# (100.000/dia) en un solo documento. Por eso hay tope y por eso se avisa
# antes: el precio real es alto y conviene saberlo antes de pagarlo.
TOPE_BLOQUES = 10


class ResumenImposible(Exception):
    """No hay nada que condensar, o fallaron todas las llamadas."""


def _sin_acentos(texto: str) -> str:
    """Quita tildes y eñes descomponiendo cada letra en 'letra + acento' y
    tirando el acento. Para el NOMBRE del fichero, no para su contenido."""
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def nombre_de_fichero(titulo: str) -> str:
    """Nombre seguro para el .md a partir del titulo del documento.

    ES UN CONTROL, no cosmetica: el titulo viene del nombre del fichero que
    manda JIM por Telegram, o sea de FUERA. Sin esto, un adjunto llamado
    "../../.env.pdf" escribiria donde no debe. Se construye por LISTA
    BLANCA -solo letras, digitos, guion y guion bajo- en vez de quitando lo
    malo: mismo criterio que la allowlist de /borrar del 28/07, porque una
    lista de lo prohibido siempre se deja algo fuera.
    """
    base = _sin_acentos(titulo).lower()
    limpio = "".join(c if c.isalnum() or c in "-_" else "-" for c in base)
    # Guiones repetidos a uno solo, y sin guiones sueltos en los extremos.
    while "--" in limpio:
        limpio = limpio.replace("--", "-")
    limpio = limpio.strip("-")[:60]
    marca = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return f"{marca}_{limpio or 'documento'}.md"


def partir_en_bloques(texto: str, tamaño: int) -> list[str]:
    """Corta el texto en bloques de como mucho `tamaño` caracteres, SIN
    partir parrafos por la mitad.

    Se corta por el ultimo salto de parrafo que quepa, no a pelo por el
    caracter N: partir una explicacion en dos deja las dos mitades sin
    sentido, y el modelo resume mal las dos. Si un parrafo es mas largo que
    el bloque entero (una tabla, un chorizo sin saltos) se corta a pelo,
    porque la alternativa seria mandar un bloque que no cabe en la cuota.
    """
    texto = texto.strip()
    if not texto:
        return []
    if tamaño <= 0:
        raise ValueError("el tamaño de bloque debe ser positivo")

    bloques = []
    resto = texto
    while len(resto) > tamaño:
        trozo = resto[:tamaño]
        corte = trozo.rfind("\n\n")
        if corte <= 0:
            corte = trozo.rfind("\n")
        if corte <= 0:
            corte = tamaño  # sin sitio donde cortar limpio: a pelo
        bloques.append(resto[:corte].strip())
        resto = resto[corte:].lstrip()
    if resto:
        bloques.append(resto)
    return [b for b in bloques if b]


# --- Los dos prompts -------------------------------------------------------
#
# La plantilla sale de la skill /planificador de Jordi (decision suya del
# 02/08: "probemos con planificador y si vemos que no va bien la
# modificamos"). La idea que se reutiliza es la que alli funciona: no pedir
# "un resumen" -que da parrafos blandos- sino EXIGIR SECCIONES CONCRETAS,
# porque una estructura obliga al modelo a buscar cada cosa por separado.

_PROMPT_BLOQUE = """\
Estás leyendo el bloque {n} de {total} de un documento titulado «{titulo}».

Saca los PUNTOS DESTACADOS de este bloque, y solo de este bloque. Reglas:

- No resumas en prosa: escribe puntos sueltos, uno por idea.
- Recoge lo que habría que RETENER: definiciones, datos, cifras, nombres,
  procedimientos, conclusiones y cualquier cosa que parezca importante.
- Si hay algo numerado, fechado o con nombre propio, consérvalo TAL CUAL.
- No te inventes nada ni completes lo que no esté: si el bloque empieza o
  acaba a mitad de una idea, recoge lo que haya y ya está.
- No escribas introducción ni cierre. Solo los puntos.

TEXTO DEL BLOQUE:
{bloque}"""

_PROMPT_FINAL = """\
Tienes los puntos destacados de las {total} partes de un documento titulado
«{titulo}», en orden. Escribe con ellos un documento en Markdown.

Estructura EXACTA que debe tener:

# {titulo}

## Resumen ejecutivo
Entre 5 y 10 líneas: de qué va el documento y qué se saca en claro.

## Puntos clave por tema
Agrupa los puntos POR TEMA, no por el orden en que venían. Un `###` por
tema, y debajo sus puntos. Es la parte más larga y la más importante.

## Conceptos a retener
Los términos, definiciones y datos concretos que hay que memorizar, en
formato `**término** — explicación corta`.

## Huecos y dudas
Lo que el documento menciona pero no explica, o lo que quedó a medias. Si
no hay nada, escribe "Nada reseñable".

Reglas:
- NO te inventes nada que no esté en los puntos. Si algo no aparece, no está.
- Junta lo que se repita en varios bloques en un solo punto.
- No expliques lo que estás haciendo: escribe directamente el documento.

PUNTOS DESTACADOS POR BLOQUE:
{puntos}"""


_PROMPT_FINAL_RAPIDO = """\
Tienes los puntos destacados de las {total} partes de un documento titulado
«{titulo}», en orden. Escribe un resumen BREVE, de unas {lineas} líneas.

Reglas:
- Prosa corrida y párrafos cortos. NADA de listas, títulos ni secciones.
- Cuenta de qué va el documento y lo esencial que hay que saber; deja fuera
  el detalle fino, los ejemplos y las enumeraciones largas.
- Si hay dos o tres datos que serían un error no mencionar, mencionálos.
- NO te inventes nada que no esté en los puntos. Si algo no aparece, no está.
- No expliques lo que estás haciendo: escribe directamente el resumen.

PUNTOS DESTACADOS POR BLOQUE:
{puntos}"""

# Formatos de salida (02/08, peticion de Jordi tras ver el completo
# funcionando). Son dos NECESIDADES distintas, no dos gustos:
#
#   "completo" -> "me voy a estudiar esto": el .md con sus cuatro
#                 secciones, para tenerlo abierto al lado.
#   "rapido"   -> "¿de que va este PDF?": 10-20 lineas ahi mismo, sin
#                 fichero que abrir.
#
# LO QUE CAMBIA ES SOLO EL PROMPT DE LA SEGUNDA PASADA. La primera -sacar
# los puntos de cada bloque- es identica, y por eso esto costo casi nada.
#
# OJO A LO QUE **NO** CAMBIA: el rapido NO es mas barato. Para resumir en
# diez lineas hay que haberse leido el documento entero igual, asi que son
# las mismas N+1 llamadas. Lo que se ahorra es lo que lees TU.
FORMATOS = ("completo", "rapido")


def _lineas_del_rapido(bloques: int) -> int:
    """Cuantas lineas pedirle al resumen corto, segun lo gordo que sea el
    documento (peticion de Jordi: "10 o 20 dependiendo de lo largo que
    sea"). Un documento de un bloque en 20 lineas no es un resumen; uno de
    diez bloques en 10 lineas se queda en nada. Acotado por arriba porque
    pasado ese punto ya no cabe en un mensaje de Telegram."""
    return min(20, max(10, bloques * 4))


def condensar(
    texto: str,
    titulo: str,
    llamar,
    tamaño_bloque: int = CARACTERES_BLOQUE_ESTRECHO,
    tope_bloques: int = TOPE_BLOQUES,
    avisar=None,
    formato: str = "completo",
) -> tuple[str, dict]:
    """Condensa el texto entero y devuelve (markdown, datos).

    `llamar(prompt) -> str` es quien habla con el modelo. Se INYECTA en vez
    de importarse para poder probar toda esta logica sin red y a coste 0,
    igual que el ProveedorFalso de F5.0/T6 y el `_llamar` del router.

    `avisar(texto)` es opcional y sirve para ir contando por donde va. El
    trabajo caro se hace donde se puede AVISAR (leccion del 01/08 con la
    preparacion del documento): aqui son minutos, no segundos.

    Si un bloque falla, se sigue con los demas y se anota - un bloque
    perdido es un resumen incompleto, pero perder los otros nueve por uno
    seria mucho peor (mismo espiritu que RNF-02).
    """
    if formato not in FORMATOS:
        raise ValueError(f"formato debe ser uno de {FORMATOS}, no {formato!r}")

    bloques = partir_en_bloques(texto, tamaño_bloque)
    if not bloques:
        raise ResumenImposible("El documento está vacío; no hay nada que resumir.")

    total_real = len(bloques)
    recortado = total_real > tope_bloques
    bloques = bloques[:tope_bloques]
    total = len(bloques)

    if avisar:
        avisar(f"Voy a leerlo en {total} bloque(s). Esto tarda un rato.")

    # PASADA 1 (mapa): los puntos destacados de cada bloque, por separado.
    puntos, fallidos = [], []
    for i, bloque in enumerate(bloques, start=1):
        if avisar:
            avisar(f"Bloque {i} de {total}…")
        try:
            respuesta = llamar(
                _PROMPT_BLOQUE.format(n=i, total=total, titulo=titulo, bloque=bloque)
            )
        except Exception as error:
            logging.error("Resumen: fallo el bloque %d (%s)", i, type(error).__name__)
            fallidos.append(i)
            continue
        puntos.append(f"### Bloque {i} de {total}\n{respuesta.strip()}")

    if not puntos:
        raise ResumenImposible(
            "No he podido leer ningún bloque del documento. Puede ser falta de cuota; "
            "inténtalo dentro de un rato."
        )

    # PASADA 2 (reduccion): de los puntos sueltos al documento estructurado.
    if avisar:
        avisar("Ordenando todo y escribiendo el resumen…")
    todos_los_puntos = "\n\n".join(puntos)
    if formato == "rapido":
        prompt_final = _PROMPT_FINAL_RAPIDO.format(
            total=total, titulo=titulo, puntos=todos_los_puntos,
            lineas=_lineas_del_rapido(total),
        )
    else:
        prompt_final = _PROMPT_FINAL.format(
            total=total, titulo=titulo, puntos=todos_los_puntos,
        )
    markdown = llamar(prompt_final).strip()

    # Los avisos van DENTRO del documento, que es donde no se pueden pasar
    # por alto - mismo patron que el "⚠️ ATENCIÓN" de NASA APOD y el
    # truncado de documentos: recortado y a la vista, nunca en silencio.
    notas = []
    if recortado:
        notas.append(
            f"El documento tenía **{total_real} bloques** y se han procesado los "
            f"**{tope_bloques} primeros**. Falta el final."
        )
    if fallidos:
        notas.append(
            f"Fallaron los bloques **{', '.join(map(str, fallidos))}** y no están "
            "recogidos aquí."
        )
    if notas:
        markdown += "\n\n---\n\n> ⚠️ **Aviso:** " + " ".join(notas)

    return markdown, {
        "bloques_totales": total_real,
        "bloques_procesados": total,
        "bloques_fallidos": fallidos,
        "recortado": recortado,
        "llamadas": total + 1,
        "formato": formato,
    }


# Quien resume, y por que se elige a dedo. Es el UNICO sitio del proyecto
# donde no se respeta el proveedor que JIM tiene puesto, asi que conviene
# que el motivo este escrito:
#
#   - gemini-2.5-flash admite 250.000 tokens/minuto, VEINTE VECES lo de
#     Groq (12.000). Es la diferencia entre resumir un documento de 300
#     hojas en dos bloques o en quince - o entre poder y no poder.
#   - El bug de Gemini del 24/07 (emite las tool-calls como TEXTO) AQUI NO
#     PUEDE APARECER, porque el resumen no usa ni una sola herramienta.
#     Gemini se usa justo donde brilla y donde su defecto no existe.
#   - Se elige 2.5 y no 3.5 porque es el unico cuyos limites del free tier
#     publica Google. Del resto no se puede planificar (ver config.py).
#
# Si no hay clave de Gemini, se sigue con el proveedor que haya y bloques
# estrechos: mas lento y mas llamadas, pero funciona. La preferencia es una
# OPTIMIZACION, no un requisito - si fuera un requisito, quien no tenga
# cuenta de Google se quedaria sin comando.
_PROVEEDOR_PREFERIDO = "gemini"
_MODELO_PREFERIDO = "models/gemini-2.5-flash"


def preparar_resumidor(proveedor_actual: str, api_key_actual: str, modelo_actual: str):
    """Devuelve (llamar, tamaño_bloque, quien) para condensar.

    `llamar(prompt) -> str` habla con el modelo SIN herramientas: esto no
    es un turno del agente, es una consulta de una vez - igual que
    Agente.resumir() desde F3.6.
    """
    from src.config import ClaveApiNoConfigurada, obtener_api_key
    from src.llm_client import _TIMEOUT_TRABAJO_LARGO, fijar_timeout, restaurar_timeout
    from src.llm_router import construir_cadena

    try:
        clave = obtener_api_key(_PROVEEDOR_PREFERIDO)
        proveedor, modelo, tamaño = (
            _PROVEEDOR_PREFERIDO, _MODELO_PREFERIDO, CARACTERES_BLOQUE_AMPLIO,
        )
    except ClaveApiNoConfigurada:
        logging.info("Resumen: sin clave de Gemini; se usa %s con bloques estrechos",
                     proveedor_actual)
        clave = api_key_actual
        proveedor, modelo, tamaño = (
            proveedor_actual, modelo_actual, CARACTERES_BLOQUE_ESTRECHO,
        )

    router = construir_cadena(proveedor, clave, modelo)

    def llamar(prompt: str) -> str:
        # El timeout se amplia AQUI y se restaura SIEMPRE (02/08, bug real):
        # con los 30s de un chat normal, Ollama fallo tres veces seguidas
        # leyendo el PDF de Jordi - no es que no pudiera, es que no le
        # dejabamos acabar. Se fija dentro de `llamar` y no fuera para que
        # dé igual en qué hilo acabe ejecutandose (Telegram lo lanza con
        # asyncio.to_thread), y en finally porque un timeout largo que se
        # quedara puesto haria que un chat normal esperase tres minutos a
        # un proveedor caido.
        token = fijar_timeout(_TIMEOUT_TRABAJO_LARGO)
        try:
            # tools=None a proposito: sin herramientas no hay bucle de tools,
            # ni presupuesto de turno, ni riesgo de que el modelo se ponga a
            # buscar cosas en vez de resumir lo que tiene delante.
            return router.responder([{"role": "user", "content": prompt}], tools=None)
        finally:
            restaurar_timeout(token)

    return llamar, tamaño, f"{proveedor} ({modelo})"


def guardar(markdown: str, titulo: str) -> Path:
    """Escribe el .md y devuelve su ruta.

    Va a un fichero y no al chat porque un condensado son decenas de miles
    de caracteres: en Telegram serian trece mensajes seguidos, que es
    inusable. Ademas asi te queda algo que abrir y guardar, no un churro
    que hay que ir rebuscando en la conversacion.
    """
    RESUMENES_DIR.mkdir(exist_ok=True)
    ruta = RESUMENES_DIR / nombre_de_fichero(titulo)
    ruta.write_text(markdown, encoding="utf-8")
    logging.info("Resumen escrito (%d caracteres)", len(markdown))
    return ruta
