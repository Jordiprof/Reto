"""El README no puede mentir sobre lo que hace el programa.

POR QUE EXISTE ESTE TEST. El 02/08, al ir a cerrar la Fase 5, el README no
mencionaba `/condensar`, `/voz`, `/documento` ni `/cerrar`, y afirmaba que
`/tools` arranca con "todas las categorias apagadas" - falso desde el
31/07. Cuatro comandos y un default, y ninguno se habia olvidado por
descuido: se olvidaron porque **nadie comprueba el README**.

Es el mismo razonamiento que el test de invariante de los menus (28/07):
una regla que depende de que alguien se acuerde, no es una regla. El README
es lo PRIMERO que ve quien evalue el repo, asi que su desfase no es un
detalle cosmetico - es la primera impresion mintiendo.

Lo que NO hace este test, a proposito: comprobar que la descripcion sea
BUENA. Eso no lo puede medir una maquina. Solo comprueba que no falte
ninguno, que es justo lo que fallo.
"""
from pathlib import Path

import pytest

from src.main import COMANDOS
from src.telegram_bot import _CATALOGO

README = Path(__file__).resolve().parent.parent / "README.md"


@pytest.fixture(scope="module")
def readme():
    return README.read_text(encoding="utf-8")


@pytest.mark.parametrize("comando", sorted(COMANDOS))
def test_cada_comando_de_la_CLI_esta_en_el_README(comando, readme):
    assert comando in readme, (
        f"{comando} existe en la CLI y el README no lo menciona. "
        "Si es nuevo, añádelo a la tabla de comandos."
    )


@pytest.mark.parametrize("nombre", sorted(n for n, _, _ in _CATALOGO))
def test_cada_comando_de_TELEGRAM_esta_en_el_README(nombre, readme):
    assert f"/{nombre}" in readme, (
        f"/{nombre} existe en el bot y el README no lo menciona."
    )


def test_el_README_no_dice_que_TODAS_las_tools_arranquen_apagadas():
    """Lo decia, y era falso desde el 31/07: solo `memoria` y `web` arrancan
    apagadas, y el resto encendidas. Un README que describe una postura de
    seguridad MAS restrictiva de la real es peor que uno incompleto."""
    from src.tools import CATEGORIAS_APAGADAS_AL_ARRANCAR

    texto = README.read_text(encoding="utf-8").lower()

    assert "todas empiezan apagadas" not in texto
    # Y las que SI arrancan apagadas tienen que estar nombradas.
    for categoria in CATEGORIAS_APAGADAS_AL_ARRANCAR:
        assert categoria in texto, f"el README no dice que '{categoria}' arranca apagada"
