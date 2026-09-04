# Tests de src/voz.py (F5.5 #8).
#
# NINGUNO toca la red, ni carga los 63 MB de Piper, ni ejecuta ffmpeg: la
# costura es siempre la misma que en el resto del proyecto - se sustituye
# la funcion del borde (el cliente de Groq, subprocess.run, shutil.which)
# y se comprueba lo que HACE nuestro codigo alrededor.
#
# Lo que estos tests protegen de verdad:
#   1. que un audio demasiado largo o demasiado grande se rechace SIN
#      salir a Groq (o sea: sin que el audio salga de la maquina);
#   2. que el texto que se le da a Piper este limpio y acotado;
#   3. que ffmpeg se invoque sin shell y por tuberias.
from types import SimpleNamespace

import pytest

from src import voz

# --- _texto_hablable: funcion pura -----------------------------------------


def test_quita_markdown_y_emojis_porque_piper_los_pronuncia():
    limpio = voz._texto_hablable("**Listo** ✅ ya _está_ `hecho`")

    for basura in ("*", "_", "`", "✅"):
        assert basura not in limpio
    assert "Listo" in limpio and "hecho" in limpio


def test_una_url_se_sustituye_en_vez_de_deletrearse():
    limpio = voz._texto_hablable("Mira https://ejemplo.com/a/b?c=1 y me dices")

    assert "https" not in limpio
    assert "un enlace" in limpio


def test_el_texto_largo_se_corta_y_lo_dice():
    """Cortar en silencio es lo que hace creer que se tiene todo (misma
    leccion que el truncado de leer_documento)."""
    largo = ("Una frase de relleno bastante larga. " * 60)

    limpio = voz._texto_hablable(largo)

    assert len(limpio) <= voz._MAX_CARACTERES_HABLAR + 40
    assert "por escrito" in limpio


def test_el_corte_respeta_el_final_de_una_frase():
    largo = "Frase. " * 300

    limpio = voz._texto_hablable(largo)

    # Lo que se lee acaba en punto (antes del aviso), no a media palabra.
    assert "Frase. Te lo dejo entero por escrito." in limpio


def test_un_texto_corto_no_se_toca():
    assert voz._texto_hablable("Hola JIM").startswith("Hola JIM")


# --- Limites de ENTRADA: rechazar sin gastar cuota --------------------------


@pytest.mark.requisito("RF-21")
def test_una_nota_demasiado_larga_se_rechaza_por_el_metadato():
    """validar_duracion trabaja con el dato que ya viene en el update: aqui
    todavia no se ha descargado ni un byte."""
    with pytest.raises(voz.VozNoDisponible, match="corta"):
        voz.validar_duracion(voz._MAX_SEGUNDOS + 1)


def test_una_nota_normal_pasa():
    voz.validar_duracion(30)
    voz.validar_duracion(None)  # el campo es opcional en la API de Telegram


@pytest.mark.requisito("RF-21")
def test_un_audio_gigante_no_llega_a_groq(monkeypatch):
    """EL test importante de esta seccion: no basta con que devuelva error,
    hay que demostrar que el audio NO SALIO. Se espia el cliente de Groq y
    se afirma que no se le llamo."""
    llamadas = []
    import groq

    monkeypatch.setattr(groq, "Groq", lambda **kw: llamadas.append(kw))

    with pytest.raises(voz.VozNoDisponible):
        voz.transcribir(b"x" * (voz._MAX_BYTES + 1))

    assert llamadas == []


def test_un_audio_vacio_tampoco_llega_a_groq(monkeypatch):
    llamadas = []
    import groq

    monkeypatch.setattr(groq, "Groq", lambda **kw: llamadas.append(kw))

    with pytest.raises(voz.VozNoDisponible):
        voz.transcribir(b"")

    assert llamadas == []


# --- transcribir: el camino bueno y los fallos ------------------------------


class _GroqFalso:
    """Sustituye al cliente de Groq. Guarda con que se le llamo."""

    ultima_llamada = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.audio = SimpleNamespace(
            transcriptions=SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        type(self).ultima_llamada = kwargs
        return SimpleNamespace(text="  hola qué tal  ")


@pytest.mark.requisito("RF-21")
def test_transcribir_devuelve_el_texto_limpio(monkeypatch):
    import groq

    monkeypatch.setattr(groq, "Groq", _GroqFalso)
    monkeypatch.setattr(voz, "obtener_api_key", lambda p: "clave-de-mentira")

    assert voz.transcribir(b"audio") == "hola qué tal"


def test_transcribir_fija_el_idioma_y_el_modelo(monkeypatch):
    """El idioma no es opcional por gusto: sin el, una nota corta o con
    ruido se detecta a veces como otro idioma y sale traducida."""
    import groq

    monkeypatch.setattr(groq, "Groq", _GroqFalso)
    monkeypatch.setattr(voz, "obtener_api_key", lambda p: "clave-de-mentira")

    voz.transcribir(b"audio")

    assert _GroqFalso.ultima_llamada["language"] == "es"
    assert _GroqFalso.ultima_llamada["model"] == voz._MODELO_WHISPER


def test_si_groq_falla_el_error_no_lleva_detalles(monkeypatch, caplog):
    """Politica de logging del proyecto: al log el TIPO, nunca el str del
    error (que en los SDK puede llevar la peticion entera) y nunca el
    audio ni lo que se dijo."""
    import groq

    def _explota(**kwargs):
        raise RuntimeError("token=secreto-en-el-mensaje")

    monkeypatch.setattr(groq, "Groq", _explota)
    monkeypatch.setattr(voz, "obtener_api_key", lambda p: "clave-de-mentira")

    with caplog.at_level("ERROR"):
        with pytest.raises(voz.VozNoDisponible) as fallo:
            voz.transcribir(b"audio")

    assert "secreto" not in str(fallo.value)
    assert "secreto" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_una_transcripcion_vacia_se_trata_como_fallo(monkeypatch):
    """Whisper devuelve cadena vacia con un audio mudo. Sin esto, el turno
    seguiria con un mensaje vacio hasta el LLM."""
    import groq

    class _Mudo(_GroqFalso):
        def _create(self, **kwargs):
            return SimpleNamespace(text="   ")

    monkeypatch.setattr(groq, "Groq", _Mudo)
    monkeypatch.setattr(voz, "obtener_api_key", lambda p: "clave-de-mentira")

    with pytest.raises(voz.VozNoDisponible, match="No he entendido"):
        voz.transcribir(b"audio")


def test_sin_clave_de_groq_lo_dice_sin_enseñarla(monkeypatch):
    from src.config import ClaveApiNoConfigurada

    def _sin_clave(proveedor):
        raise ClaveApiNoConfigurada("falta")

    monkeypatch.setattr(voz, "obtener_api_key", _sin_clave)

    with pytest.raises(voz.VozNoDisponible, match="GROQ_API_KEY"):
        voz.transcribir(b"audio")


# --- Hablar: ffmpeg y disponibilidad ---------------------------------------


def test_ffmpeg_se_invoca_sin_shell_y_por_tuberias(monkeypatch):
    """No hay dato de fuera en esta linea de comandos hoy, y el test existe
    para que siga siendo asi: argumentos en LISTA, sin shell=True, y el
    audio entrando por stdin en vez de por un fichero temporal cuyo nombre
    habria que construir."""
    capturado = {}

    def _run_falso(argv, **kwargs):
        capturado["argv"] = argv
        capturado["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout=b"OggS...", stderr=b"")

    monkeypatch.setattr(voz.shutil, "which", lambda nombre: "C:/ffmpeg/ffmpeg.exe")
    monkeypatch.setattr(voz.subprocess, "run", _run_falso)

    assert voz._a_opus(b"RIFF....") == b"OggS..."
    assert isinstance(capturado["argv"], list) and capturado["argv"][0] == "ffmpeg"
    assert "shell" not in capturado["kwargs"]
    assert capturado["kwargs"]["input"] == b"RIFF...."
    assert "libopus" in capturado["argv"]


def test_sin_ffmpeg_se_avisa_en_vez_de_petar(monkeypatch):
    monkeypatch.setattr(voz.shutil, "which", lambda nombre: None)

    with pytest.raises(voz.VozNoDisponible, match="ffmpeg"):
        voz._a_opus(b"RIFF")


def test_si_ffmpeg_falla_su_stderr_no_va_al_log(monkeypatch, caplog):
    """El stderr de ffmpeg puede incluir rutas locales."""
    def _run_falso(argv, **kwargs):
        return SimpleNamespace(
            returncode=1, stdout=b"", stderr=b"C:/Users/jordi/ruta/privada.wav no existe"
        )

    monkeypatch.setattr(voz.shutil, "which", lambda nombre: "ffmpeg")
    monkeypatch.setattr(voz.subprocess, "run", _run_falso)

    with caplog.at_level("ERROR"):
        with pytest.raises(voz.VozNoDisponible):
            voz._a_opus(b"RIFF")

    assert "jordi" not in caplog.text.lower()


def test_motivo_no_disponible_avisa_de_la_voz_que_falta(monkeypatch, tmp_path):
    """El menu de /voz tiene que poder decir la verdad ANTES de que se
    encienda el interruptor."""
    monkeypatch.setattr(voz, "obtener_ruta_voz", lambda: tmp_path / "no-existe.onnx")

    motivo = voz.motivo_no_disponible()

    assert motivo and "download_voices" in motivo


def test_motivo_no_disponible_avisa_de_ffmpeg(monkeypatch, tmp_path):
    falsa = tmp_path / "voz.onnx"
    falsa.write_bytes(b"x")
    monkeypatch.setattr(voz, "obtener_ruta_voz", lambda: falsa)
    monkeypatch.setattr(voz.shutil, "which", lambda nombre: None)

    assert "ffmpeg" in voz.motivo_no_disponible()


def test_sintetizar_no_carga_el_modelo_si_no_hay_nada_que_decir(monkeypatch):
    """Un texto que se queda vacio al limpiarlo (solo emojis, por ejemplo)
    no debe cargar 63 MB de Piper para no decir nada."""
    llamadas = []
    monkeypatch.setattr(voz, "_cargar_voz", lambda: llamadas.append(1))

    with pytest.raises(voz.VozNoDisponible):
        voz.sintetizar("✅✅")

    assert llamadas == []


def test_sintetizar_pasa_por_texto_hablable_y_por_opus(monkeypatch):
    """Camino completo sin Piper real: se comprueba que lo que se sintetiza
    es el texto LIMPIO (no el original con markdown) y que la salida pasa
    por la conversion a Opus."""
    dicho = {}

    class _VozFalsa:
        def synthesize_wav(self, texto, fichero, *a, **kw):
            dicho["texto"] = texto
            fichero.setnchannels(1)
            fichero.setsampwidth(2)
            fichero.setframerate(22050)
            fichero.writeframes(b"\x00\x00" * 10)

    monkeypatch.setattr(voz, "_cargar_voz", lambda: _VozFalsa())
    monkeypatch.setattr(voz, "_a_opus", lambda wav: b"OGG:" + wav[:4])

    assert voz.sintetizar("**Hola** ✅") == b"OGG:RIFF"
    assert dicho["texto"] == "Hola"
