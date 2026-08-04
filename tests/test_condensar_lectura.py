"""Los dos ahorros de /condensar del 03/08, los dos encontrados por Jordi
probando en real (no por la suite):

  1. "se lo lee dos veces": con UN bloque, la pasada 1 resumia el bloque y
     la pasada 2 resumia ESE resumen. El modelo escribia el documento final
     sin haber visto nunca el texto original.
  2. "ya lo tenia leido y cargado, deberia haberse puesto a crear
     directamente el .md": pedir el rapido y luego el completo del mismo
     PDF releia el documento entero por segunda vez.
"""

from types import SimpleNamespace

import pytest

from src.agent import Agente
from src.resumen_largo import condensar


def _contador():
    """Un `llamar` que apunta cada prompt que recibe. Sin red y a coste 0,
    igual que el ProveedorFalso de F5.0/T6."""
    prompts = []

    def llamar(prompt):
        prompts.append(prompt)
        return "resumen del modelo"

    return llamar, prompts


# --- 1. Un bloque, una llamada -------------------------------------------


def test_un_bloque_es_UNA_llamada_y_no_dos():
    """El bug de "se lo lee dos veces". Con un solo bloque la pasada 2 no
    reduce nada: solo reescribe lo que ya estaba escrito."""
    llamar, prompts = _contador()
    _, datos = condensar("un texto corto", "Apuntes.pdf", llamar, tamaño_bloque=10_000)

    assert len(prompts) == 1
    assert datos["llamadas"] == 1


def test_con_un_bloque_el_modelo_ve_el_TEXTO_ORIGINAL():
    """Lo importante no es el ahorro, es la CALIDAD: antes el resumen final
    se escribia a partir de un resumen de segunda mano, y cada pasada
    pierde detalle. Ahora el texto de verdad llega a la unica llamada."""
    llamar, prompts = _contador()
    condensar("la frase que tiene que llegar", "Apuntes.pdf", llamar, tamaño_bloque=10_000)

    assert "la frase que tiene que llegar" in prompts[0]


def test_con_VARIOS_bloques_siguen_siendo_dos_pasadas():
    """El contraste que hace util al test de arriba: con varios bloques la
    pasada 2 SI hace falta -es la que junta y ordena- y no se toca."""
    texto = "\n\n".join(f"parrafo numero {i} con su contenido" for i in range(12))
    llamar, prompts = _contador()
    _, datos = condensar(texto, "Apuntes.pdf", llamar, tamaño_bloque=60)

    assert datos["bloques_procesados"] > 1
    assert len(prompts) == datos["bloques_procesados"] + 1
    assert datos["llamadas"] == len(prompts)


def test_el_aviso_NO_dice_bloque_1_de_1():
    """Detalle de interfaz que Jordi vio antes que nadie: contar "bloque 1
    de 1" y luego "ordenando todo" hacia creer que iban dos fases."""
    avisos = []
    llamar, _ = _contador()
    condensar("corto", "Apuntes.pdf", llamar, tamaño_bloque=10_000, avisar=avisos.append)

    assert not any("1 de 1" in a for a in avisos), avisos
    assert not any("Ordenando" in a for a in avisos), avisos


# --- 2. La lectura se reutiliza entre formatos ---------------------------


def test_la_lectura_se_reutiliza_y_ahorra_la_pasada_1():
    """El caso real de Jordi: primero el rapido para ver de que va, luego
    el completo para estudiarlo. La lectura de cada bloque es IDENTICA
    para los dos formatos (_PROMPT_BLOQUE no recibe `formato`)."""
    texto = "\n\n".join(f"parrafo numero {i} con su contenido" for i in range(12))

    llamar, prompts_1 = _contador()
    _, datos_1 = condensar(texto, "Apuntes.pdf", llamar, tamaño_bloque=60, formato="rapido")
    assert datos_1["lectura"], "el rapido tiene que dejar la lectura guardada"

    llamar_2, prompts_2 = _contador()
    _, datos_2 = condensar(
        texto, "Apuntes.pdf", llamar_2, tamaño_bloque=60, formato="completo",
        lectura_previa=datos_1["lectura"],
    )

    assert len(prompts_2) == 1, "solo deberia quedar la pasada 2"
    assert datos_2["llamadas"] == 1
    assert len(prompts_2) < len(prompts_1)


def test_reutilizar_la_lectura_NO_cambia_el_formato_pedido():
    """El ahorro no puede colarse en el resultado: se salta la LECTURA, no
    la redaccion. El .md completo tiene que seguir siendo el completo."""
    texto = "\n\n".join(f"parrafo numero {i} con su contenido" for i in range(12))

    llamar, _ = _contador()
    _, datos = condensar(texto, "Apuntes.pdf", llamar, tamaño_bloque=60, formato="rapido")

    llamar_2, prompts_2 = _contador()
    condensar(
        texto, "Apuntes.pdf", llamar_2, tamaño_bloque=60, formato="completo",
        lectura_previa=datos["lectura"],
    )

    llamar_3, prompts_3 = _contador()
    condensar(texto, "Apuntes.pdf", llamar_3, tamaño_bloque=60, formato="completo")

    assert prompts_2[0] == prompts_3[-1], "el prompt final debe ser el mismo"


def test_una_lectura_COJA_no_se_ofrece_para_reutilizar():
    """Si un bloque fallo por cuota, guardar esa lectura convertiria un
    fallo pasajero en un resumen incompleto para siempre."""
    texto = "\n\n".join(f"parrafo numero {i} con su contenido" for i in range(12))
    # Se cuenta la llamada en vez de mirar el texto del prompt: el prompt
    # FINAL tambien contiene "Bloque 2" (dentro de los puntos que junta), y
    # la primera version de este test hacia fallar tambien esa.
    vistas = {"n": 0}

    def llamar(prompt):
        vistas["n"] += 1
        if vistas["n"] == 2:
            raise RuntimeError("sin cuota")
        return "resumen del modelo"

    _, datos = condensar(texto, "Apuntes.pdf", llamar, tamaño_bloque=60)

    assert datos["bloques_fallidos"], "el test necesita que falle un bloque"
    assert datos["lectura"] == []


# --- 3. La lectura se suelta con el documento ----------------------------


def _agente():
    return Agente(proveedor="ollama", api_key="k", modelo="m", system_prompt="s")


def test_cambiar_de_documento_SUELTA_la_lectura():
    """El agujero que cierra el setter de la propiedad: cargar otro PDF sin
    pasar por /limpiar dejaria viva la lectura del anterior, y /condensar
    devolveria el resumen del documento equivocado."""
    agente = _agente()
    agente.documento_pendiente = SimpleNamespace(nombre="Primero.pdf")
    agente.lectura_condensada = ["lo leido del primero"]

    agente.documento_pendiente = SimpleNamespace(nombre="Segundo.pdf")

    assert agente.lectura_condensada == []


def test_limpiar_historial_SUELTA_la_lectura():
    """"Empezamos de cero" incluye la lectura, no solo el documento."""
    agente = _agente()
    agente.documento_pendiente = SimpleNamespace(nombre="Apuntes.pdf")
    agente.lectura_condensada = ["lo leido"]

    agente.limpiar_historial()

    assert agente.documento_pendiente is None
    assert agente.lectura_condensada == []


def test_volver_a_poner_EL_MISMO_objeto_conserva_la_lectura():
    """Sin esto el cacheo no serviria de nada: el segundo /condensar del
    mismo documento tiene que encontrarla puesta."""
    agente = _agente()
    documento = SimpleNamespace(nombre="Apuntes.pdf")
    agente.documento_pendiente = documento
    agente.lectura_condensada = ["lo leido"]

    agente.documento_pendiente = documento

    assert agente.lectura_condensada == ["lo leido"]


@pytest.mark.parametrize("formato", ["rapido", "completo"])
def test_el_formato_sigue_validandose(formato):
    """Regresion barata: la reestructuracion no puede haberse llevado por
    delante la validacion de la entrada."""
    llamar, _ = _contador()
    condensar("corto", "Apuntes.pdf", llamar, tamaño_bloque=10_000, formato=formato)

    with pytest.raises(ValueError):
        condensar("corto", "Apuntes.pdf", llamar, formato="inventado")


# --- 4. El dia de la semana en la prevision (arreglo F del 03/08) --------


def test_la_prevision_lleva_el_DIA_DE_LA_SEMANA():
    """MITIGACION, no garantia. llama-3.3-70b reescribio 2026-08-03 como
    2024-03-07 copiando en cambio las 21 cifras sin un error, y a eso no
    llega ningun control de esta capa: la API respondio bien y lo que se
    estropeo fue el texto que el modelo escribio DESPUES.

    Lo que si hace el dia de la semana es volver la mentira inconsistente
    consigo misma - "lunes 2024-03-07" es un jueves-, o sea VISIBLE."""
    from src.tools import _formatear_prevision

    salida = _formatear_prevision(
        {
            "time": ["2026-08-03", "2026-08-04"],
            "weather_code": [3, 0],
            "temperature_2m_min": [22.7, 20.8],
            "temperature_2m_max": [31.9, 31.9],
            "precipitation_probability_max": [15, 0],
            "wind_speed_10m_max": [19.0, 14.0],
        },
        "Fuenlabrada (España)",
    )

    assert "lunes 2026-08-03" in salida
    assert "martes 2026-08-04" in salida
    # La fecha ISO sigue estando entera: el dia se AÑADE, no sustituye.
    assert "2026-08-03" in salida


def test_una_fecha_rara_no_tumba_la_prevision_entera():
    """Open-Meteo siempre manda ISO, pero si algun dia cambiara el formato
    es mejor enseñar la fecha tal cual que perder los datos por un adorno."""
    from src.tools import _formatear_prevision

    salida = _formatear_prevision(
        {
            "time": ["mañana"],
            "weather_code": [0],
            "temperature_2m_min": [20.0],
            "temperature_2m_max": [30.0],
            "precipitation_probability_max": [0],
            "wind_speed_10m_max": [10.0],
        },
        "Fuenlabrada",
    )

    assert "mañana" in salida
    assert "20.0-30.0" in salida


def test_con_UN_bloque_no_se_le_dice_que_son_puntos_ya_resumidos():
    """Con una sola pasada lo que se le manda es el DOCUMENTO ENTERO, no
    puntos destilados. Decirle lo contrario le hace resumir un resumen que
    no existe, y se pierde el detalle que la pasada unica venia a salvar."""
    llamar, prompts = _contador()
    condensar("el texto crudo del documento", "Apuntes.pdf", llamar,
              tamaño_bloque=10_000)

    assert "TEXTO DEL DOCUMENTO:" in prompts[0]
    assert "PUNTOS DESTACADOS POR BLOQUE:" not in prompts[0]
    assert "puntos destacados de las" not in prompts[0]


def test_con_VARIOS_bloques_el_prompt_final_SIGUE_hablando_de_puntos():
    """El contraste: ahi si son puntos de verdad, salidos de la pasada 1."""
    texto = "\n\n".join(f"parrafo numero {i} con su contenido" for i in range(12))
    llamar, prompts = _contador()
    condensar(texto, "Apuntes.pdf", llamar, tamaño_bloque=60)

    assert "PUNTOS DESTACADOS POR BLOQUE:" in prompts[-1]
    assert "puntos destacados de las" in prompts[-1]


def test_el_titulo_llega_al_markdown_en_LOS_DOS_caminos():
    """Regresion de la parametrizacion: al sacar {titulo} de la frase de
    entrada, la estructura del .md lo sigue necesitando como titulo `#`."""
    texto_largo = "\n\n".join(f"parrafo numero {i} con su contenido" for i in range(12))
    for texto, tamaño in [("corto", 10_000), (texto_largo, 60)]:
        llamar, prompts = _contador()
        condensar(texto, "Apuntes.pdf", llamar, tamaño_bloque=tamaño)
        assert "# Apuntes.pdf" in prompts[-1], f"tamaño={tamaño}"
