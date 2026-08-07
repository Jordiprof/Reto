"""AUD-04: una clave de cifrado ROTA se caza al leerla, no al guardar.

EL FALLO QUE CIERRA. Hasta el 02/08, obtener_clave_conversaciones() hacia
`.encode()` y ya. Una clave mal escrita -un caracter de menos al copiarla,
un espacio, una clave de otro sitio- pasaba por buena: el programa
anunciaba "cifrado activo" y solo reventaba al INTENTAR GUARDAR, o sea al
final de una conversacion entera. Contradice la politica del proyecto de
avisar en vez de fallar en silencio.

POR QUE NO SE DEGRADA A "guardar sin cifrar", que era la otra opcion:
creerias que tus conversaciones estan cifradas y estarian en claro en
disco. Una clave rota es un error de configuracion que se arregla en
treinta segundos; tragarselo es mucho peor que parar.
"""
import pytest
from cryptography.fernet import Fernet

from src.config import ClaveCifradoInvalida, obtener_clave_conversaciones


def test_sin_clave_devuelve_None_y_NO_falla(monkeypatch):
    """El cifrado es OPCIONAL: no tener clave es un caso legitimo, y quien
    llama ya avisa por pantalla (main.py y telegram_bot.py)."""
    monkeypatch.delenv("CONVERSATIONS_KEY", raising=False)

    assert obtener_clave_conversaciones() is None


def test_una_clave_vacia_cuenta_como_no_tener_clave(monkeypatch):
    """Variable puesta en el .env pero sin valor detras."""
    monkeypatch.setenv("CONVERSATIONS_KEY", "")

    assert obtener_clave_conversaciones() is None


def test_una_clave_VALIDA_pasa(monkeypatch):
    clave = Fernet.generate_key().decode()
    monkeypatch.setenv("CONVERSATIONS_KEY", clave)

    assert obtener_clave_conversaciones() == clave.encode()


@pytest.mark.parametrize("rota,motivo", [
    ("esto-no-es-una-clave", "texto cualquiera"),
    ("YWJjZGVm", "base64 valido pero de longitud incorrecta"),
    ("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!=", "44 caracteres pero no base64"),
])
def test_una_clave_ROTA_se_caza_al_LEERLA(monkeypatch, rota, motivo):
    """Al leerla, que es cuando aun se puede hacer algo - no al guardar,
    que es donde reventaba antes."""
    monkeypatch.setenv("CONVERSATIONS_KEY", rota)

    with pytest.raises(ClaveCifradoInvalida):
        obtener_clave_conversaciones()


def test_una_clave_a_la_que_le_falta_un_caracter_tambien(monkeypatch):
    """El caso REAL que motiva esto: copiar la clave y dejarse el ultimo
    caracter. Es indistinguible a ojo de una buena."""
    clave = Fernet.generate_key().decode()
    monkeypatch.setenv("CONVERSATIONS_KEY", clave[:-1])

    with pytest.raises(ClaveCifradoInvalida):
        obtener_clave_conversaciones()


def test_el_aviso_explica_COMO_arreglarlo(monkeypatch):
    """Un error que dice "clave invalida" y nada mas obliga a buscar en
    Google. El mensaje trae el comando para generar una."""
    monkeypatch.setenv("CONVERSATIONS_KEY", "rota")

    with pytest.raises(ClaveCifradoInvalida) as error:
        obtener_clave_conversaciones()

    assert "Fernet.generate_key()" in str(error.value)
    # Y avisa de lo que NO es obvio: cambiar la clave deja lo viejo ilegible.
    assert "NO se podrán abrir" in str(error.value)


def test_el_aviso_NO_filtra_la_clave(monkeypatch):
    """Ese texto acaba en pantalla y puede acabar en una captura o en un
    log. La clave rota sigue siendo un secreto: no se hace eco de ella."""
    monkeypatch.setenv("CONVERSATIONS_KEY", "clave-secreta-rota-12345")

    with pytest.raises(ClaveCifradoInvalida) as error:
        obtener_clave_conversaciones()

    assert "clave-secreta-rota-12345" not in str(error.value)
