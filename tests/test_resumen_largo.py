"""Condensar un documento entero por bloques (02/08).

Todo con un `llamar` FALSO inyectado: sin red, sin cuota y determinista,
igual que el ProveedorFalso de F5.0/T6 y el `_llamar` del router. Lo que se
prueba aqui es la ORQUESTACION -cuantas llamadas, en que orden, que pasa si
una falla- que es donde estan los errores caros; la calidad del texto que
escriba el modelo no la puede medir ningun test.
"""
import pytest

from src import resumen_largo
from src.resumen_largo import (
    CARACTERES_BLOQUE_AMPLIO,
    CARACTERES_BLOQUE_ESTRECHO,
    ResumenImposible,
    condensar,
    guardar,
    nombre_de_fichero,
    partir_en_bloques,
)


def _llamar_falso(registro=None, fallar_en=()):
    """Un `llamar` que apunta lo que le piden y devuelve texto previsible."""
    def llamar(prompt):
        if registro is not None:
            registro.append(prompt)
        n = len(registro or [])
        if n in fallar_en:
            raise RuntimeError("el proveedor se cayo")
        return f"respuesta {n}"
    return llamar


# --- Partir en bloques ----------------------------------------------------


def test_un_texto_corto_es_un_solo_bloque():
    assert partir_en_bloques("hola", 100) == ["hola"]


def test_un_texto_vacio_no_da_bloques():
    assert partir_en_bloques("", 100) == []
    assert partir_en_bloques("   \n  ", 100) == []


def test_se_corta_por_parrafo_y_no_a_mitad_de_frase():
    """Partir una explicacion por la mitad deja las dos mitades sin sentido
    y el modelo resume mal las dos."""
    texto = "primer parrafo entero.\n\nsegundo parrafo entero."

    bloques = partir_en_bloques(texto, 30)

    assert bloques == ["primer parrafo entero.", "segundo parrafo entero."]


def test_un_parrafo_mas_largo_que_el_bloque_se_corta_a_pelo():
    """Una tabla o un chorizo sin saltos no se puede cortar limpio, y
    mandarlo entero seria mandar un bloque que no cabe en la cuota."""
    texto = "x" * 250

    bloques = partir_en_bloques(texto, 100)

    assert len(bloques) == 3
    assert "".join(bloques) == texto


def test_ningun_bloque_pasa_del_tamaño_pedido():
    """El tamaño no es estetico: si un bloque se pasa, la peticion se sale
    de la cuota por minuto y el proveedor la rechaza entera."""
    texto = "\n\n".join(f"parrafo numero {i} con algo de relleno" for i in range(200))

    for bloque in partir_en_bloques(texto, 500):
        assert len(bloque) <= 500


def test_no_se_pierde_texto_al_trocear():
    """Lo que importa es que no falte NADA: los saltos y espacios de los
    bordes se normalizan al cortar (por eso se comparan sin blancos), pero
    ni una palabra puede quedarse por el camino."""
    def sin_blancos(t):
        return "".join(t.split())

    texto = "\n\n".join(f"parrafo {i}" for i in range(50))

    junto = "".join(sin_blancos(b) for b in partir_en_bloques(texto, 100))

    assert junto == sin_blancos(texto)


def test_un_tamaño_invalido_se_rechaza():
    with pytest.raises(ValueError):
        partir_en_bloques("hola", 0)


def test_cada_bloque_cabe_en_la_cuota_de_su_proveedor():
    """Este test estaba MAL planteado y lo destapo bajar el bloque amplio de
    200.000 a 60.000: exigia que uno fuera diez veces el otro, que es una
    relacion inventada. Lo que de verdad importa es que cada tamaño quepa en
    los tokens por minuto de quien lo va a usar, medidos en documentacion
    oficial el 02/08:

        gpt-oss-120b (el mas justo)   8.000 tokens/minuto
        gemini-2.5-flash            250.000 tokens/minuto

    Si un bloque se pasa, el proveedor rechaza la peticion ENTERA y no es
    que salga peor: es que no sale.
    """
    caracteres_por_token = 3.7

    assert CARACTERES_BLOQUE_ESTRECHO / caracteres_por_token < 8_000
    assert CARACTERES_BLOQUE_AMPLIO / caracteres_por_token < 250_000
    # Y el amplio tiene que aprovechar de verdad la holgura de Gemini.
    assert CARACTERES_BLOQUE_AMPLIO > CARACTERES_BLOQUE_ESTRECHO


# --- Nombre del fichero (es un control, no cosmetica) ---------------------


@pytest.mark.parametrize("titulo", [
    "../../.env",
    "..\\..\\secreto",
    "/etc/passwd",
    "C:\\Windows\\System32\\config",
])
def test_un_titulo_hostil_no_puede_escapar_de_la_carpeta(titulo):
    """El titulo viene del nombre del adjunto que manda JIM, o sea de
    FUERA. Se construye por LISTA BLANCA (solo alfanumericos, guion y guion
    bajo) y no quitando lo malo: una lista de lo prohibido siempre se deja
    algo. Mismo criterio que la allowlist de /borrar del 28/07."""
    nombre = nombre_de_fichero(titulo)

    assert "/" not in nombre
    assert "\\" not in nombre
    assert ".." not in nombre
    assert nombre.endswith(".md")


def test_las_tildes_y_eñes_no_acaban_en_el_nombre():
    nombre = nombre_de_fichero("Programación Española ñ")

    assert "ó" not in nombre and "ñ" not in nombre
    assert "programacion" in nombre


def test_un_titulo_que_se_queda_sin_nada_usable_no_da_un_nombre_vacio():
    nombre = nombre_de_fichero("///???")

    assert nombre.endswith("_documento.md")


def test_dos_ficheros_seguidos_no_se_pisan():
    """Lleva marca de tiempo hasta los segundos, igual que storage.py."""
    assert nombre_de_fichero("apuntes").endswith("_apuntes.md")


# --- La orquestacion de las dos pasadas ----------------------------------


def test_son_una_llamada_por_bloque_MAS_la_final():
    """Las dos pasadas: N de mapa + 1 de reduccion. Si esto cambia sin
    querer, cambia lo que cuesta cada resumen en cuota."""
    registro = []
    texto = "\n\n".join(f"parrafo {i}" for i in range(100))

    _, datos = condensar(texto, "Apuntes", _llamar_falso(registro), tamaño_bloque=200)

    assert datos["llamadas"] == datos["bloques_procesados"] + 1
    assert len(registro) == datos["llamadas"]


def test_la_ultima_llamada_recibe_los_puntos_de_todas_las_demas():
    """La pasada 2 no vuelve a ver el documento: ve los PUNTOS. Es lo que
    hace que quepa en la cuota aunque el documento no cupiera."""
    registro = []
    texto = "\n\n".join(f"parrafo {i}" for i in range(100))

    condensar(texto, "Apuntes", _llamar_falso(registro), tamaño_bloque=200)

    final = registro[-1]
    assert "Resumen ejecutivo" in final
    assert "respuesta 1" in final          # los puntos del bloque 1
    assert "parrafo 0" not in final        # pero NO el texto original


def test_un_documento_vacio_no_gasta_ni_una_llamada():
    registro = []

    with pytest.raises(ResumenImposible):
        condensar("   ", "Vacio", _llamar_falso(registro))

    assert registro == []


def test_si_falla_UN_bloque_se_sigue_con_los_demas():
    """Un bloque perdido es un resumen incompleto; perder los otros nueve
    por uno seria mucho peor (mismo espiritu que RNF-02)."""
    texto = "\n\n".join(f"parrafo {i}" for i in range(100))

    markdown, datos = condensar(
        texto, "Apuntes", _llamar_falso([], fallar_en=(2,)), tamaño_bloque=200
    )

    assert datos["bloques_fallidos"] == [2]
    assert "Fallaron los bloques **2**" in markdown


def test_si_fallan_TODOS_se_avisa_en_vez_de_devolver_un_resumen_falso():
    texto = "\n\n".join(f"parrafo {i}" for i in range(20))

    def siempre_falla(prompt):
        raise RuntimeError("sin cuota")

    with pytest.raises(ResumenImposible):
        condensar(texto, "Apuntes", siempre_falla, tamaño_bloque=200)


def test_el_tope_de_bloques_recorta_Y_LO_DICE():
    """Recortado y a la vista es mejor que ausente y en silencio - mismo
    criterio que el truncado de documentos y el aviso de NASA APOD."""
    texto = "\n\n".join(f"parrafo {i}" for i in range(500))

    markdown, datos = condensar(
        texto, "Apuntes", _llamar_falso([]), tamaño_bloque=200, tope_bloques=3
    )

    assert datos["bloques_procesados"] == 3
    assert datos["recortado"] is True
    assert datos["bloques_totales"] > 3
    assert "se han procesado los **3 primeros**" in markdown


def test_sin_recorte_no_se_ensucia_el_documento_con_avisos():
    """Contrapeso: el aviso solo aparece cuando hay algo que avisar."""
    markdown, datos = condensar("un parrafo corto", "Apuntes", _llamar_falso([]))

    assert datos["recortado"] is False
    assert "⚠️" not in markdown


def test_se_va_avisando_por_donde_va():
    """El trabajo caro se hace donde se puede AVISAR (leccion del 01/08):
    esto son minutos, y sin avisos parece que se ha colgado."""
    avisos = []
    texto = "\n\n".join(f"parrafo {i}" for i in range(100))

    condensar(
        texto, "Apuntes", _llamar_falso([]), tamaño_bloque=200, avisar=avisos.append
    )

    assert any("bloque" in a.lower() for a in avisos)
    assert len(avisos) >= 2


# --- Guardado -------------------------------------------------------------


def test_se_escribe_el_md_y_se_devuelve_su_ruta(tmp_path, monkeypatch):
    monkeypatch.setattr(resumen_largo, "RESUMENES_DIR", tmp_path / "resumenes")

    ruta = guardar("# Hola\n\ncontenido", "Mis Apuntes")

    assert ruta.exists()
    assert ruta.suffix == ".md"
    assert ruta.read_text(encoding="utf-8") == "# Hola\n\ncontenido"


def test_el_md_se_guarda_dentro_de_la_carpeta_aunque_el_titulo_sea_hostil(
    tmp_path, monkeypatch
):
    """De punta a punta: la lista blanca del nombre tiene que aguantar
    tambien cuando se escribe de verdad, no solo en la funcion suelta."""
    destino = tmp_path / "resumenes"
    monkeypatch.setattr(resumen_largo, "RESUMENES_DIR", destino)

    ruta = guardar("x", "../../.env")

    assert ruta.parent == destino
    assert not (tmp_path.parent / ".env").exists()


# --- Quien resume: Gemini a dedo ------------------------------------------


def test_se_prefiere_gemini_2_5_aunque_JIM_tenga_puesto_otro(monkeypatch):
    """LA DECISION DEL 02/08. Es el unico sitio del proyecto donde no se
    respeta el proveedor elegido, y el motivo es la cuota: gemini-2.5-flash
    admite 250.000 tokens/minuto frente a los 12.000 de Groq. Con Groq un
    documento de 300 hojas NO CABE en una peticion."""
    monkeypatch.setattr("src.config.obtener_api_key", lambda p: f"clave-{p}")
    monkeypatch.setattr("src.llm_router.construir_cadena", lambda *a, **k: object())

    _, tamaño, quien = resumen_largo.preparar_resumidor("groq", "clave-groq", "llama-3.3")

    assert "gemini" in quien and "2.5" in quien
    assert tamaño == CARACTERES_BLOQUE_AMPLIO


def test_sin_clave_de_gemini_se_sigue_con_el_proveedor_de_JIM(monkeypatch):
    """La preferencia es una OPTIMIZACION, no un requisito: quien no tenga
    cuenta de Google no puede quedarse sin el comando. Se paga con bloques
    estrechos, o sea mas llamadas."""
    from src.config import ClaveApiNoConfigurada

    def sin_gemini(proveedor):
        raise ClaveApiNoConfigurada(proveedor)

    monkeypatch.setattr("src.config.obtener_api_key", sin_gemini)
    monkeypatch.setattr("src.llm_router.construir_cadena", lambda *a, **k: object())

    _, tamaño, quien = resumen_largo.preparar_resumidor("groq", "clave-groq", "llama-3.3")

    assert "groq" in quien
    assert tamaño == CARACTERES_BLOQUE_ESTRECHO


def test_el_resumen_NUNCA_lleva_herramientas(monkeypatch):
    """Sin tools no hay bucle de tools, ni presupuesto de turno, ni riesgo
    de que el modelo se ponga a buscar en vez de resumir. Y ademas es lo
    que hace que el bug de Gemini del 24/07 (tool-calls como texto) no
    pueda aparecer aqui."""
    recibido = {}

    class RouterFalso:
        def responder(self, mensajes, tools):
            recibido["tools"] = tools
            recibido["mensajes"] = mensajes
            return "resumen"

    monkeypatch.setattr("src.config.obtener_api_key", lambda p: "clave")
    monkeypatch.setattr("src.llm_router.construir_cadena", lambda *a, **k: RouterFalso())

    llamar, _, _ = resumen_largo.preparar_resumidor("groq", "clave", "llama-3.3")
    assert llamar("resume esto") == "resumen"

    assert recibido["tools"] is None
    assert recibido["mensajes"] == [{"role": "user", "content": "resume esto"}]


# --- El timeout: el bug que tumbo la primera prueba real (02/08) ---------


def test_el_resumen_usa_el_timeout_LARGO_y_no_el_de_chat(monkeypatch):
    """EL BUG. Jordi le dio un PDF de 284 fragmentos y Ollama fallo con
    "timeout tras 30.0s" TRES VECES: no es que no pudiera, es que no le
    dejabamos acabar. Los 30s valen para un chat -si tarda mas, algo se ha
    colgado- pero leerse 142.000 caracteres son minutos."""
    from src.llm_client import _TIMEOUT_SEGUNDOS, _TIMEOUT_TRABAJO_LARGO, timeout_actual

    visto = {}

    class RouterFalso:
        def responder(self, mensajes, tools):
            visto["timeout"] = timeout_actual()
            return "ok"

    monkeypatch.setattr("src.config.obtener_api_key", lambda p: "clave")
    monkeypatch.setattr("src.llm_router.construir_cadena", lambda *a, **k: RouterFalso())

    llamar, _, _ = resumen_largo.preparar_resumidor("groq", "clave", "llama-3.3")
    llamar("resume esto")

    assert visto["timeout"] == _TIMEOUT_TRABAJO_LARGO
    assert visto["timeout"] > _TIMEOUT_SEGUNDOS


def test_el_timeout_largo_se_restaura_AUNQUE_falle_la_llamada(monkeypatch):
    """Si se quedara puesto, un chat normal esperaria TRES MINUTOS a un
    proveedor caido. Es el mismo fallo que el ContextVar del documento que
    no se soltaba (01/08): el estado se suelta en un finally, no cuando te
    acuerdas."""
    from src.llm_client import _TIMEOUT_SEGUNDOS, timeout_actual

    class RouterQueRevienta:
        def responder(self, mensajes, tools):
            raise RuntimeError("proveedor caido")

    monkeypatch.setattr("src.config.obtener_api_key", lambda p: "clave")
    monkeypatch.setattr(
        "src.llm_router.construir_cadena", lambda *a, **k: RouterQueRevienta()
    )

    llamar, _, _ = resumen_largo.preparar_resumidor("groq", "clave", "llama-3.3")
    with pytest.raises(RuntimeError):
        llamar("resume esto")

    assert timeout_actual() == _TIMEOUT_SEGUNDOS


def test_fuera_del_resumen_el_timeout_sigue_siendo_el_de_siempre():
    """Quien no sepa que esto existe no puede notar nada."""
    from src.llm_client import _TIMEOUT_SEGUNDOS, timeout_actual

    assert timeout_actual() == _TIMEOUT_SEGUNDOS


# --- Formato rapido (02/08) ----------------------------------------------


def test_el_rapido_usa_OTRO_prompt_final(monkeypatch):
    """Lo unico que cambia entre los dos formatos es la SEGUNDA pasada: la
    primera -sacar los puntos de cada bloque- es identica, y por eso esto
    costo casi nada."""
    registro = []
    texto = "\n\n".join(f"parrafo {i}" for i in range(100))

    condensar(texto, "Apuntes", _llamar_falso(registro), tamaño_bloque=200,
              formato="rapido")

    final = registro[-1]
    assert "líneas" in final              # le pide una longitud concreta
    assert "Resumen ejecutivo" not in final  # y NO las secciones del completo


def test_los_dos_formatos_cuestan_LO_MISMO():
    """Importa que quede fijado: el rapido NO ahorra cuota. Para resumir en
    diez lineas hay que haberse leido el documento entero igual. Lo que se
    ahorra es lo que lee el usuario."""
    texto = "\n\n".join(f"parrafo {i}" for i in range(100))

    _, completo = condensar(texto, "A", _llamar_falso([]), tamaño_bloque=200,
                            formato="completo")
    _, rapido = condensar(texto, "A", _llamar_falso([]), tamaño_bloque=200,
                          formato="rapido")

    assert completo["llamadas"] == rapido["llamadas"]


def test_un_documento_mas_gordo_pide_mas_lineas():
    """Peticion de Jordi: "10 o 20 dependiendo de lo largo que sea". Un
    documento de un bloque en 20 lineas no es un resumen; uno de diez
    bloques en 10 lineas se queda en nada."""
    assert resumen_largo._lineas_del_rapido(1) < resumen_largo._lineas_del_rapido(5)


def test_las_lineas_del_rapido_estan_acotadas_por_arriba():
    """Pasado cierto punto ya no cabe en un mensaje de Telegram, y deja de
    ser un resumen rapido."""
    assert resumen_largo._lineas_del_rapido(1000) <= 20


def test_un_formato_inventado_se_rechaza_ANTES_de_gastar():
    registro = []

    with pytest.raises(ValueError):
        condensar("hola", "A", _llamar_falso(registro), formato="poema")

    assert registro == []
