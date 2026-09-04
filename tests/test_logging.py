# Tests de la fuga de PII en logs encontrada el 27/07/2026 (F5.2).
#
# _ejecutar_tool logueaba args=%s y ->%s en claro: para buscar_en_recuerdos
# eso es texto DESCIFRADO de conversaciones pasadas (ver src/rag.py). El
# mismo razonamiento que test_chromadb_no_guarda_el_texto_en_claro
# (tests/test_rag.py), aplicado a un canal que nadie habia mirado: el
# cifrado Fernet de storage.py no sirve de nada si el dato sale en claro
# por logging.
#
# Se afirma sobre caplog.records con .getMessage(), no sobre caplog.text:
# asi se caza tambien el formato perezoso (logging.info("...%s", pii)),
# que es justo como estaba escrita la linea original.
import logging

import pytest
from pydantic import BaseModel, ConfigDict

from src import tools
from src.llm_client import _campos_seguros, _ejecutar_tool, _nombre_seguro


class _ArgsFalsos(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consulta: str


def _texto_de(caplog) -> str:
    """Todo lo que ha llegado al logger, con los %s ya rellenados."""
    return "\n".join(registro.getMessage() for registro in caplog.records)


FRASE_PERSONAL = "la cita del medico del jueves con el doctor Ramirez"


@pytest.mark.requisito("RNF-07")
@pytest.mark.control("E2-TRAZAS")
def test_el_log_no_guarda_el_contenido_que_devuelve_una_tool(caplog, monkeypatch):
    """EL TEST DE PRIVACIDAD DE LOGS (F5.2), hermano de
    test_chromadb_no_guarda_el_texto_en_claro. Se registra una tool falsa
    que devuelve texto personal, para no depender del RAG real."""
    monkeypatch.setitem(
        tools.HERRAMIENTAS,
        "recordar_falso",
        tools.Herramienta(
            funcion=lambda consulta: f"[2026-07-01] JIM dijo: {FRASE_PERSONAL}",
            args=_ArgsFalsos,
            descripcion="tool de prueba",
        ),
    )

    with caplog.at_level(logging.INFO):
        resultado = _ejecutar_tool("recordar_falso", {"consulta": "lo del medico"})

    # La tool SI devuelve el texto personal (va al modelo, es su trabajo)...
    assert FRASE_PERSONAL in resultado
    # ...pero NI UNA palabra de el llega al log.
    registros = _texto_de(caplog)
    assert FRASE_PERSONAL not in registros
    assert "Ramirez" not in registros
    assert "lo del medico" not in registros  # ni el VALOR del argumento


@pytest.mark.requisito("RNF-07")
def test_el_log_si_registra_que_tool_se_llamo_y_con_que_campos(caplog):
    """Contrapeso del test anterior: 'no loguear nada' seria trivialmente
    seguro e inutil. El objetivo de T8 se conserva entero. Numeros
    distinguibles (111/222) a proposito: un '1' o un '2' sueltos
    apareceria por casualidad en chars=/ms= y el assert negativo pasaria
    sin significar nada."""
    with caplog.at_level(logging.INFO):
        _ejecutar_tool("calcular", {"expresion": "111 + 222"})

    registros = _texto_de(caplog)
    assert "calcular" in registros  # QUE tool
    assert "ok" in registros  # y que funciono
    assert "expresion" in registros  # QUE campos (el NOMBRE, del schema)
    assert "111" not in registros  # pero NO el valor que mando el modelo
    assert "222" not in registros
    assert "333" not in registros  # ni el resultado


MARCADOR = "zanahoria_confidencial_42"


@pytest.mark.parametrize(
    "nombre, argumentos, estado_esperado",
    [
        ("tool_que_no_existe", {"consulta": MARCADOR}, "inexistente"),
        ("calcular", {"expresion": "1+1", "campo_de_mas": MARCADOR}, "args_invalidos"),
        ("calcular", {"expresion": MARCADOR}, "fallo"),  # string valido -> revienta en calcular()
    ],
)
def test_ninguna_rama_de_ejecutar_tool_loguea_valores(
    caplog, nombre, argumentos, estado_esperado
):
    """La linea vieja estaba FUERA de todos los if/try, asi que filtraba
    por las cuatro salidas posibles. Este test las recorre una a una: si
    alguien vuelve a meter un valor en cualquiera de ellas, salta aqui."""
    with caplog.at_level(logging.INFO):
        _ejecutar_tool(nombre, argumentos)

    registros = _texto_de(caplog)
    assert MARCADOR not in registros
    assert estado_esperado in registros


# --- Log injection: el nombre de la tool y las claves los elige el LLM ---
#
# Estos tests faltaban en la primera version del arreglo (27/07): el saneado
# se habia verificado A MANO en la terminal, pero sin test que lo fijara.
# Justo el fallo que causo toda esta incidencia - una garantia escrita que
# nadie comprueba sola. Si alguien quita _nombre_seguro/_campos_seguros,
# estos tests se ponen rojos.

# Salto de linea + texto que imita una entrada de log legitima: el objetivo
# de un atacante no es romper el programa, es FALSIFICAR el rastro de
# auditoria (que agente.log muestre un evento que nunca ocurrio).
_NOMBRE_MALICIOSO = (
    "calcular\n2026-07-27 23:59:59 [INFO] Tool robar_datos | ok | campos=todo"
)


@pytest.mark.requisito("RNF-07")
@pytest.mark.control("E2-TRAZAS")
def test_un_nombre_de_tool_con_salto_de_linea_no_parte_el_log(caplog):
    """El log es una linea por evento: si el nombre colara un '\\n', una
    sola llamada escribiria DOS lineas y la segunda podria hacerse pasar
    por un evento real."""
    with caplog.at_level(logging.INFO):
        _ejecutar_tool(_NOMBRE_MALICIOSO, {"consulta": "x"})

    # Un unico registro, y su texto no contiene ningun salto de linea.
    assert len(caplog.records) == 1
    assert "\n" not in caplog.records[0].getMessage()


@pytest.mark.control("E2-TRAZAS")
def test_las_claves_de_argumentos_tambien_se_sanean(caplog):
    """Mismo agujero por la otra puerta: las CLAVES del dict de argumentos
    las elige el LLM igual que el nombre."""
    with caplog.at_level(logging.INFO):
        _ejecutar_tool("calcular", {"expresion\n[INFO] falso": "1+1"})

    assert len(caplog.records) == 1
    assert "\n" not in caplog.records[0].getMessage()


@pytest.mark.parametrize(
    "entrada",
    ["hola\nmundo", "a\rb", "punto y coma; barra |", "日本語", "", "x" * 500],
)
def test_nombre_seguro_nunca_deja_pasar_caracteres_de_formato(entrada):
    """Unitario del saneador, sobre casos limite reales: saltos de linea,
    retorno de carro, el separador '|' que usa nuestro propio formato,
    unicode que se sanea entero, cadena vacia y una entrada larguisima."""
    limpio = _nombre_seguro(entrada)

    assert "\n" not in limpio
    assert "\r" not in limpio
    assert "|" not in limpio
    assert len(limpio) <= 40  # acotado: un nombre gigante no inunda el log
    assert limpio  # nunca cadena vacia (rompería el formato de la linea)


def test_campos_seguros_acota_y_sanea_aunque_haya_muchos_campos():
    """Un modelo desbocado podria mandar decenas de campos inventados: la
    linea de log no debe crecer sin limite ni llevar caracteres de formato."""
    muchos = {f"campo\n{i}": i for i in range(50)}

    salida = _campos_seguros(muchos)

    assert "\n" not in salida
    assert len(salida) <= 200
