"""AUD-03: el historial deja de crecer sin freno.

EL PROBLEMA, medido sobre las conversaciones REALES de Jordi el 02/08.
Cada turno reenvia TODO lo anterior, asi que el coste no crece: se ACUMULA.
Es la suma de las sumas. Su conversacion mas larga (23 mensajes, 19.211
caracteres) ya eran ~5.200 tokens, el 43% de los 12.000 tokens/minuto que
da Groq en el plan gratuito. Proyectado desde sus propios datos:

    turno 10 ->  4.515 tokens/peticion |  24.832 gastados
    turno 20 ->  9.030 tokens/peticion |  94.813 gastados  <- la cuota DIARIA
    turno 30 -> 13.545 tokens/peticion | NO CABE en un minuto

O sea: 20 turnos se comian el dia entero de Groq y 30 dejaban de funcionar.

POR QUE VENTANA Y NO RESUMEN (decision de Jordi): resumir cuesta una
llamada al LLM cada vez, y aqui no hace falta porque el proyecto YA tiene
memoria permanente. Lo que sale del historial no se pierde -esta en
conversations/ y en el RAG- solo deja de REENVIARSE.
"""
import pytest

from src.agent import _MAX_CARACTERES_HISTORIAL, _MENSAJES_QUE_SE_CONSERVAN, Agente


def _agente():
    """Un Agente sin red: construir_cadena no llega a usarse porque estos
    tests no llaman a preguntar()."""
    return Agente("system prompt", "groq", "clave", "llama-3.3-70b-versatile")


def _llenar(agente, mensajes, caracteres_por_mensaje=1000):
    for i in range(mensajes):
        rol = "user" if i % 2 == 0 else "assistant"
        agente.historial.append({"role": rol, "content": f"m{i} " + "x" * caracteres_por_mensaje})


def test_una_conversacion_normal_NO_se_toca():
    """El tope sale de los datos reales de Jordi: su charla mas larga son
    19.211 caracteres, asi que en una conversacion normal esto no debe
    entrar nunca. Un control que salta cuando no toca es peor que ninguno."""
    agente = _agente()
    _llenar(agente, mensajes=15, caracteres_por_mensaje=1000)  # ~15.000

    assert agente.compactar_si_hace_falta() == 0
    assert len(agente.historial) == 16


def test_cuando_se_pasa_se_tiran_los_MAS_VIEJOS():
    agente = _agente()
    _llenar(agente, mensajes=40, caracteres_por_mensaje=1000)  # ~40.000

    tirados = agente.compactar_si_hace_falta()

    assert tirados > 0
    assert len(agente.historial) == 1 + _MENSAJES_QUE_SE_CONSERVAN
    # Lo que queda son los ULTIMOS, no unos cualesquiera.
    assert agente.historial[-1]["content"].startswith("m39")


@pytest.mark.requisito("RF-05", "RF-26")
def test_el_SYSTEM_PROMPT_nunca_se_tira():
    """Es quien ES el agente, no memoria de nada. Mismo criterio que
    /limpiar, que tambien lo conserva."""
    agente = _agente()
    _llenar(agente, mensajes=40)

    agente.compactar_si_hace_falta()

    assert agente.historial[0]["role"] == "system"
    assert agente.historial[0]["content"] == "system prompt"


@pytest.mark.requisito("RF-26")
def test_el_historial_compactado_baja_del_tope():
    """Lo que de verdad importa: que la peticion siguiente quepa en la
    cuota. Si tras compactar sigue pasandose, no hemos arreglado nada."""
    agente = _agente()
    _llenar(agente, mensajes=40, caracteres_por_mensaje=1000)

    agente.compactar_si_hace_falta()

    assert agente._tamaño_historial() <= _MAX_CARACTERES_HISTORIAL


@pytest.mark.requisito("RF-26", "RF-06")
def test_ANTES_de_tirar_nada_se_guarda():
    """LO QUE HACE SEGURA LA VENTANA. En Telegram el turno ya se persiste
    solo, pero la CLI guarda AL SALIR: sin esto, lo compactado a mitad de
    sesion se perderia de verdad en vez de quedarse en el RAG."""
    agente = _agente()
    _llenar(agente, mensajes=40)
    orden = []

    def persistir():
        # Al guardar, el historial tiene que estar TODAVIA entero.
        orden.append(len(agente.historial))

    agente.compactar_si_hace_falta(persistir)

    assert orden == [41], "se guardo despues de tirar, o no se guardo"


def test_si_falla_el_guardado_NO_se_compacta():
    """Mejor un turno caro que perder lo hablado. Misma prioridad que
    _persistir en el bot: guardar importa, pero nunca a costa del
    contenido."""
    agente = _agente()
    _llenar(agente, mensajes=40)
    antes = len(agente.historial)

    def persistir_roto():
        raise OSError("disco lleno")

    assert agente.compactar_si_hace_falta(persistir_roto) == 0
    assert len(agente.historial) == antes


def test_sin_funcion_de_guardado_se_compacta_igual():
    """Telegram no la pasa porque ya persiste cada turno por su cuenta."""
    agente = _agente()
    _llenar(agente, mensajes=40)

    assert agente.compactar_si_hace_falta(None) > 0


def test_un_UNICO_mensaje_gigante_no_deja_la_conversacion_vacia():
    """Un documento pegado o una respuesta larguisima pueden pasarse del
    tope ellos solos. Tirar mas seria quedarse sin conversacion, y no
    arreglaria nada porque el que abulta es el que queda."""
    agente = _agente()
    agente.historial.append({"role": "user", "content": "x" * 50_000})

    assert agente.compactar_si_hace_falta() == 0
    assert len(agente.historial) == 2


@pytest.mark.requisito("RF-26")
@pytest.mark.parametrize("mensajes", [12, 20, 40, 100])
def test_da_igual_lo_larga_que_sea_la_charla_el_contexto_queda_acotado(mensajes):
    """La propiedad de fondo: el coste por turno deja de depender de cuanto
    lleves hablando. Antes crecia sin techo."""
    agente = _agente()
    _llenar(agente, mensajes=mensajes, caracteres_por_mensaje=1000)

    agente.compactar_si_hace_falta()

    assert agente._tamaño_historial() <= _MAX_CARACTERES_HISTORIAL
