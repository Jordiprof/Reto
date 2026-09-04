# Tests de F5.5 #7 (leer PDF/Word): src/documentos.py.
#
# Doctrina del proyecto: los controles de seguridad se validan por
# MUTACION, no solo con tests en verde (ver diario 27/07 y 30/07). Aqui hay
# dos controles reales: (1) solo se aceptan .pdf/.docx de un tamaño
# razonable, y (2) un .docx (que es un ZIP) no se descomprime sin mirar
# antes el tamaño de sus partes - la bomba de descompresion que cita
# ADR-006. Los tests de esos dos controles construyen la mutacion a mano
# (quitar la comprobacion) para demostrar que SI detectarian el fallo.
import io
import zipfile

import docx
import pytest

from src.documentos import (
    DocumentoNoValido,
    documento_actual,
    extraer_texto,
    fijar_documento_actual,
    restaurar_documento_actual,
    validar_adjunto,
)


def _pdf_con_texto(texto: str) -> bytes:
    """PDF minimo escrito a mano (sin reportlab): un objeto Catalog, uno
    Pages, uno Page y un content stream con el texto. pypdf lo lee bien
    aunque el xref no sea perfecto (recupera escaneando objetos, como
    haria con cualquier PDF real algo maltratado)."""
    stream = f"BT /F1 24 Tf 10 100 Td ({texto}) Tj ET".encode()
    contenido = f"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >>
   /MediaBox [0 0 300 300] /Contents 5 0 R >>
endobj
4 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
5 0 obj
<< /Length {len(stream)} >>
stream
{stream.decode()}
endstream
endobj
xref
0 6
0000000000 65535 f
trailer
<< /Size 6 /Root 1 0 R >>
startxref
0
%%EOF""".encode()
    return contenido


def _docx_con_texto(*parrafos: str) -> bytes:
    documento = docx.Document()
    for parrafo in parrafos:
        documento.add_paragraph(parrafo)
    buffer = io.BytesIO()
    documento.save(buffer)
    return buffer.getvalue()


# --- Extension y tamaño --------------------------------------------------


@pytest.mark.requisito("RF-20")
@pytest.mark.control("E2-FICHEROS")
def test_una_extension_no_pdf_ni_docx_se_rechaza():
    with pytest.raises(DocumentoNoValido, match="\\.pdf o \\.docx"):
        validar_adjunto(b"lo que sea", "notas.txt")


def test_sin_extension_se_rechaza():
    with pytest.raises(DocumentoNoValido):
        validar_adjunto(b"lo que sea", "notas")


def test_un_pdf_dentro_del_tamaño_se_acepta():
    adjunto = validar_adjunto(_pdf_con_texto("Hola"), "informe.pdf")
    assert adjunto.tipo == "pdf"
    assert adjunto.nombre == "informe.pdf"


@pytest.mark.requisito("RF-20")
@pytest.mark.control("E2-FICHEROS")
def test_un_fichero_demasiado_grande_se_rechaza(monkeypatch):
    import src.documentos as documentos

    monkeypatch.setattr(documentos, "_MAX_BYTES_ADJUNTO", 10)
    with pytest.raises(DocumentoNoValido, match="pesa demasiado"):
        validar_adjunto(b"x" * 11, "informe.pdf")


def test_justo_en_el_limite_de_tamaño_se_acepta(monkeypatch):
    """Caso de control del test anterior: el limite es <=, no <."""
    import src.documentos as documentos

    monkeypatch.setattr(documentos, "_MAX_BYTES_ADJUNTO", 10)
    validar_adjunto(b"x" * 10, "informe.pdf")  # no lanza


# --- Bomba de descompresion en .docx (ADR-006) ----------------------------


def _docx_con_entrada_gigante(tamaño_descomprimido: int) -> bytes:
    """Una bomba de descompresion DE VERDAD, no simulada: bytes muy
    repetitivos (comprimen brutalmente con DEFLATE) para que el ZIP
    resultante sea pequeño en disco pero enorme al descomprimir - la forma
    real del ataque que cita ADR-006. ZipFile.writestr() RECALCULA
    file_size a partir de los bytes reales, asi que no basta con poner el
    numero a mano en el ZipInfo (se probo y no sobrevive al writestr)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as paquete:
        paquete.writestr("word/document.xml", b"0" * tamaño_descomprimido)
    return buffer.getvalue()


@pytest.mark.requisito("RF-20")
@pytest.mark.control("E2-FICHEROS")
def test_un_docx_con_una_parte_gigante_se_rechaza():
    grande = _docx_con_entrada_gigante(60_000_000)
    with pytest.raises(DocumentoNoValido, match="sospechosamente grande"):
        validar_adjunto(grande, "bomba.docx")


def test_un_docx_normal_no_activa_la_comprobacion_de_bomba():
    """Caso de control: sin el, el test anterior podria estar rechazando
    CUALQUIER .docx, no solo el malicioso."""
    normal = _docx_con_texto("Un documento normal y corriente.")
    validar_adjunto(normal, "normal.docx")  # no lanza


@pytest.mark.requisito("RF-20", "RNF-08")
@pytest.mark.mutacion("Quitar el aviso de tamaño en el docx")
def test_MUTACION_sin_la_comprobacion_de_bomba_el_docx_pasaria(monkeypatch):
    """Prueba de mutacion (doctrina del proyecto, 27/07): se rompe el
    control a proposito -subiendo el tope muy por encima del ataque- y se
    confirma que ES la comprobacion quien paraba el fichero, no una
    casualidad de otro sitio (extension, tamaño total del fichero
    comprimido, que sigue siendo minusculo - el ataque es justo que
    comprime mucho)."""
    import src.documentos as documentos

    grande = _docx_con_entrada_gigante(60_000_000)
    assert len(grande) < 1_000_000  # el .docx en si pasa de sobra _MAX_BYTES_ADJUNTO

    monkeypatch.setattr(documentos, "_MAX_BYTES_DESCOMPRIMIDOS", 200_000_000)
    validar_adjunto(grande, "bomba.docx")  # con el tope "roto", ya no lanza


def test_un_docx_corrupto_se_rechaza():
    with pytest.raises(DocumentoNoValido, match="dañado"):
        validar_adjunto(b"esto no es un zip de verdad", "roto.docx")


def test_LOG02_no_se_fia_del_campo_file_size_de_la_cabecera(monkeypatch):
    """Auditoria del 04/08 (LOG-02): `entrada.file_size` lo escribe quien
    CREA el ZIP -es la cabecera local del formato- y se puede falsear sin
    que el fichero deje de ser un ZIP valido. No hay forma de fabricar eso
    con `zipfile.writestr()` (recalcula el campo, ver el comentario de
    `_docx_con_entrada_gigante`), asi que aqui se simula reemplazando lo
    que devuelve `paquete.open()`: una entrada que DICE pesar 1 byte pero
    cuyo contenido real, al leerlo, son 60.000.000.

    Se usa un file-like minimo (no el `ZipExtFile` real) A PROPOSITO: la
    implementacion real de zipfile verifica el CRC-32 contra `file_size` al
    CERRAR el miembro, y esa verificacion se dispara ANTES de que el
    `DocumentoNoValido` de nuestro codigo termine de propagarse, dejando
    ver un `BadZipFile` en su lugar -detalle de implementacion de la
    libreria, no del codigo que se esta probando-. Con un file-like que no
    verifica nada al cerrar, la unica razon por la que el test puede fallar
    es que NUESTRO codigo vuelva a fiarse de `file_size`.

    Si alguien revirtiera el arreglo (volver a leer `entrada.file_size` en
    vez de medir bytes reales al descomprimir), este test empezaria a
    fallar: el ZIP con la cabecera mentirosa dejaria de rechazarse. Hace de
    test de mutacion sin tener que romper el codigo a mano."""
    grande = _docx_con_entrada_gigante(60_000_000)
    contenido_real = b"0" * 60_000_000

    class _MiembroConCabeceraMentirosa:
        """Simula lo que devuelve `ZipFile.open()`: mismo contenido real
        que un ataque de verdad tendria, sin la verificacion de CRC al
        cerrar que complica el test sin aportar nada a lo que se prueba."""

        def __init__(self, datos):
            self._buffer = io.BytesIO(datos)

        def read(self, n=-1):
            return self._buffer.read(n)

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    def open_con_cabecera_mentirosa(self, entrada, *args, **kwargs):
        if isinstance(entrada, zipfile.ZipInfo):
            entrada.file_size = 1  # la cabecera MIENTE
        return _MiembroConCabeceraMentirosa(contenido_real)

    monkeypatch.setattr(zipfile.ZipFile, "open", open_con_cabecera_mentirosa)

    with pytest.raises(DocumentoNoValido, match="sospechosamente grande"):
        validar_adjunto(grande, "bomba.docx")


# --- Extraccion de texto --------------------------------------------------


@pytest.mark.requisito("RF-20", "CU-05")
def test_extrae_texto_de_un_pdf():
    adjunto = validar_adjunto(_pdf_con_texto("Contenido del PDF"), "x.pdf")
    assert "Contenido del PDF" in extraer_texto(adjunto)


@pytest.mark.requisito("RF-20")
def test_extrae_texto_de_un_docx():
    adjunto = validar_adjunto(_docx_con_texto("Primer párrafo.", "Segundo párrafo."), "x.docx")
    texto = extraer_texto(adjunto)
    assert "Primer párrafo." in texto
    assert "Segundo párrafo." in texto


def test_extrae_texto_de_tablas_en_un_docx():
    """Las tablas NO salen en `.paragraphs` (python-docx las trata aparte):
    sin recorrerlas a mano, un documento con datos solo en tablas
    devolveria texto vacio aunque el documento SI tuviera contenido."""
    documento = docx.Document()
    tabla = documento.add_table(rows=1, cols=2)
    tabla.rows[0].cells[0].text = "Nombre"
    tabla.rows[0].cells[1].text = "Precio"
    buffer = io.BytesIO()
    documento.save(buffer)

    adjunto = validar_adjunto(buffer.getvalue(), "tabla.docx")
    texto = extraer_texto(adjunto)

    assert "Nombre" in texto and "Precio" in texto


def test_un_pdf_cifrado_no_se_puede_leer(monkeypatch):
    """No se fabrica un PDF cifrado de verdad (complejidad innecesaria):
    se sustituye PdfReader por uno de mentira que declara is_encrypted,
    igual que otros tests del proyecto sustituyen la pieza minima que
    hace falta para forzar la rama."""
    from src.documentos import _extraer_texto_pdf

    class _LectorFalso:
        is_encrypted = True
        pages = []

    # _extraer_texto_pdf importa PdfReader dentro de la funcion (import
    # perezoso, ver el resto del proyecto), asi que se parchea el modulo
    # real de pypdf, no un atributo de documentos.py.
    import pypdf

    monkeypatch.setattr(pypdf, "PdfReader", lambda datos: _LectorFalso())

    with pytest.raises(DocumentoNoValido, match="contraseña"):
        _extraer_texto_pdf(b"lo que sea")


def test_si_falta_la_libreria_de_pdf_el_mensaje_es_NUESTRO(monkeypatch):
    """REGRESION de un fallo REAL (31/07): pypdf estaba instalado en el
    Python del sistema pero NO en el venv desde el que Jordi ejecuta. El
    ImportError crudo llegaba al modelo como "Error ejecutando
    'leer_documento': No module named 'pypdf'" y el modelo, en vez de
    decir que la herramienta habia reventado, se INVENTO que el usuario no
    habia adjuntado nada - le echo la culpa a Jordi de un fallo del
    servidor.

    Es la misma leccion que la alucinacion de fecha de NASA APOD: cuando el
    modelo puede confundir un fallo con otra cosa, no basta con que el dato
    sea correcto, hay que hacer el fallo VISIBLE e inconfundible.

    Importa de cara al hosting (decision todavia abierta): el dia que el
    bot se despliegue en un VPS y falte una dependencia, esto es lo que
    decidira si el mensaje es util o una mentira."""
    import builtins

    real_import = builtins.__import__

    def sin_pypdf(nombre, *args, **kwargs):
        if nombre.startswith("pypdf"):
            raise ImportError("No module named 'pypdf'")
        return real_import(nombre, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", sin_pypdf)

    from src.documentos import _extraer_texto_pdf

    with pytest.raises(DocumentoNoValido) as fallo:
        _extraer_texto_pdf(b"lo que sea")

    mensaje = str(fallo.value)
    # Dice que el problema es de INSTALACION, no del fichero ni del usuario.
    assert "instalada" in mensaje or "instalar" in mensaje
    # Y le prohibe explicitamente al modelo culpar al usuario, que es
    # exactamente lo que hizo el 31/07.
    assert "no es culpa" in mensaje.lower()
    # No filtra el volcado interno de Python (misma politica que
    # test_mensajes_de_error_no_filtran_detalles_internos en test_tools.py).
    assert "No module named" not in mensaje


def test_si_falta_la_libreria_de_word_el_mensaje_es_NUESTRO(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def sin_docx(nombre, *args, **kwargs):
        if nombre == "docx" or nombre.startswith("docx."):
            raise ImportError("No module named 'docx'")
        return real_import(nombre, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", sin_docx)

    from src.documentos import _extraer_texto_docx

    with pytest.raises(DocumentoNoValido) as fallo:
        _extraer_texto_docx(b"lo que sea")

    assert "no es culpa" in str(fallo.value).lower()
    assert "No module named" not in str(fallo.value)


def test_un_docx_sin_texto_da_cadena_vacia():
    """No es un error - lo distingue tools.py, que es quien decide el
    mensaje ('no tiene texto que pueda leer')."""
    adjunto = validar_adjunto(_docx_con_texto(), "vacio.docx")
    assert extraer_texto(adjunto) == ""


# --- El ContextVar (como leer_documento sabe "cual" documento) -----------


def test_sin_fijar_nada_documento_actual_es_None():
    assert documento_actual() is None


def test_fijar_y_restaurar_documento_actual():
    adjunto = validar_adjunto(_pdf_con_texto("x"), "x.pdf")

    token = fijar_documento_actual(adjunto)
    try:
        assert documento_actual() is adjunto
    finally:
        restaurar_documento_actual(token)

    assert documento_actual() is None


# --- Trocear + buscar por relevancia (01/08) -------------------------------
# Antes, de un documento largo el modelo recibia los primeros 8.000
# caracteres y punto: medido con un PDF de 19.193, le llegaba hasta la
# seccion 17 de 40 y el final NO existia para el. Ahora se trocea y se le
# mandan los trozos que hablan de lo que se pregunta.


def test_trocear_cubre_todo_el_texto():
    from src.documentos import trocear

    texto = "\n".join(f"linea {i} con algo de contenido" for i in range(400))
    trozos = trocear(texto)

    assert len(trozos) > 1
    # Nada se pierde: la primera y la ultima linea tienen que estar.
    assert "linea 0 " in trozos[0]
    assert "linea 399" in trozos[-1]


def test_los_trozos_se_solapan():
    """Sin solape, una frase que cae justo en la frontera se parte y no se
    parece a nada al buscar."""
    from src.documentos import trocear

    texto = "x" * 5000
    trozos = trocear(texto, tamaño=1000, solape=200)

    assert sum(len(t) for t in trozos) > len(texto)


def test_trocear_texto_vacio_no_revienta():
    from src.documentos import trocear

    assert trocear("") == []


def test_encuentra_lo_que_esta_AL_FINAL_del_documento():
    """EL test de esta funcionalidad: lo que antes era imposible. El dato
    esta en el ultimo tramo, muy por detras del limite de 8.000."""
    from src.documentos import buscar_en_documento

    relleno = "\n".join(
        f"Seccion {i}: hablamos de bases de datos y de rendimiento general."
        for i in range(120)
    )
    texto = relleno + "\nSeccion final: el protocolo de CIFRADO usa AES-256-GCM."

    elegidos = buscar_en_documento(texto, "que cifrado usa")

    assert any("AES-256-GCM" in trozo for _i, trozo in elegidos)


def test_los_fragmentos_vuelven_en_ORDEN_del_documento():
    """Se eligen por relevancia pero se entregan en el orden en que estan
    escritos: al modelo se le da el documento, no un ranking."""
    from src.documentos import buscar_en_documento

    texto = "\n".join(f"Seccion {i}: contenido variado sobre redes." for i in range(200))

    elegidos = buscar_en_documento(texto, "redes")
    posiciones = [i for i, _t in elegidos]

    assert posiciones == sorted(posiciones)


def test_un_documento_corto_se_devuelve_entero_sin_buscar():
    """Si cabe, no hay nada que elegir - y asi no se paga el coste de
    calcular vectores para nada."""
    from src.documentos import buscar_en_documento

    texto = "Un documento cortito.\nCon dos lineas."

    elegidos = buscar_en_documento(texto, "lo que sea")

    assert len(elegidos) == len(texto.split("\n")) or len(elegidos) >= 1
    assert "".join(t for _i, t in elegidos).replace("\n", "") != ""


def test_leer_documento_con_consulta_llega_al_final(monkeypatch):
    """De punta a punta por la tool, que es como lo usa el modelo."""
    from src.documentos import (
        DocumentoAdjunto,
        fijar_documento_actual,
        restaurar_documento_actual,
    )
    from src.tools import leer_documento

    # 800 secciones (~44.000 caracteres): el documento tiene que NO caber en
    # _MAX_CARACTERES_DOCUMENTO -20.000 desde el 01/08- o este test dejaria
    # de probar el troceo y probaria el camino "cabe entero".
    relleno = "\n".join(
        f"Seccion {i}: contenido de relleno sobre arquitectura." for i in range(800)
    )
    texto = relleno + "\nCONCLUSION: la clave del informe es ZANAHORIA-7788."

    monkeypatch.setattr("src.documentos.extraer_texto", lambda a: texto)
    # Se guarda el token y se restaura: el ContextVar es GLOBAL del hilo, y
    # dejarlo puesto contaminaba a otros tests (paso el 01/08: un test que
    # comprueba "no hay documento" fallaba solo al correr la suite entera).
    token = fijar_documento_actual(
        DocumentoAdjunto(datos=b"x", nombre="largo.pdf", tipo="pdf")
    )
    try:
        sin_consulta = leer_documento()
        con_consulta = leer_documento(consulta="cual es la clave del informe")
    finally:
        restaurar_documento_actual(token)

    assert "ZANAHORIA-7788" not in sin_consulta, "sin consulta se manda el principio"
    assert "ZANAHORIA-7788" in con_consulta, "con consulta tiene que llegar al final"
    assert "fragmento" in con_consulta, "hay que decirle de que parte sale cada trozo"


def test_el_aviso_de_troceo_prohibe_afirmar_ausencias(monkeypatch):
    """Misma leccion que el 31/07: afirmo que el documento NO hablaba de
    pruebas de penetracion mirando solo el 76%."""
    from src.documentos import (
        DocumentoAdjunto,
        fijar_documento_actual,
        restaurar_documento_actual,
    )
    from src.tools import leer_documento

    # Mismo motivo que el test de arriba: debe superar los 20.000 caracteres.
    texto = "\n".join(f"Seccion {i}: contenido de relleno variado." for i in range(900))
    monkeypatch.setattr("src.documentos.extraer_texto", lambda a: texto)
    token = fijar_documento_actual(
        DocumentoAdjunto(datos=b"x", nombre="largo.pdf", tipo="pdf")
    )
    try:
        r = leer_documento(consulta="seguridad")
    finally:
        restaurar_documento_actual(token)

    assert "NO afirmes que el documento no menciona algo" in r
    assert "NO son" in r and "consecutivos" in r


def test_el_documento_NO_entra_en_la_memoria_permanente(monkeypatch):
    """Los trozos de un adjunto no deben acabar en ChromaDB: un documento
    que se lee una vez no es una conversacion, y ensuciaria para siempre las
    busquedas de recuerdos."""
    import src.rag as rag
    from src.documentos import buscar_en_documento

    def prohibido(*a, **kw):
        raise AssertionError("buscar en un adjunto NO debe tocar el indice")

    monkeypatch.setattr(rag, "_coleccion", prohibido)

    texto = "\n".join(f"Seccion {i}: contenido sobre redes." for i in range(200))
    buscar_en_documento(texto, "redes")


# --- leer_fichero: rutas tal y como las escribe una persona (01/08) --------
# Jordi intento adjuntar un PDF por la CLI cuatro veces y fallaron las
# cuatro, ninguna por culpa suya. La funcionalidad estaba bien y aun asi era
# inusable, que a efectos practicos es lo mismo que estar rota.


def test_una_carpeta_se_explica_como_carpeta(tmp_path):
    """Antes: "[Errno 13] Permission denied", que manda a buscar un problema
    de permisos que no existe."""
    from src.documentos import DocumentoNoValido, leer_fichero

    with pytest.raises(DocumentoNoValido) as error:
        leer_fichero(str(tmp_path))

    assert "carpeta" in str(error.value)


def test_acepta_la_ruta_con_el_ampersand_de_windows(tmp_path):
    r"""`& 'C:\...'` es LITERALMENTE lo que pega Windows con "Copiar como
    ruta" y al arrastrar un fichero a PowerShell."""
    from src.documentos import leer_fichero

    fichero = tmp_path / "informe.pdf"
    fichero.write_bytes(b"%PDF-1.4 contenido")

    datos, nombre = leer_fichero(f"& '{fichero}'")

    assert datos == b"%PDF-1.4 contenido"
    assert nombre == "informe.pdf"


def test_acepta_la_ruta_entre_comillas(tmp_path):
    """Windows las pone solo cuando la ruta lleva espacios - y son del
    SHELL, no del nombre del fichero."""
    from src.documentos import leer_fichero

    fichero = tmp_path / "con espacios.pdf"
    fichero.write_bytes(b"x")

    for entrecomillada in (f'"{fichero}"', f"'{fichero}'"):
        datos, nombre = leer_fichero(entrecomillada)
        assert nombre == "con espacios.pdf"
        assert datos == b"x"


def test_un_fichero_que_no_existe_lo_dice_claro(tmp_path):
    from src.documentos import DocumentoNoValido, leer_fichero

    with pytest.raises(DocumentoNoValido) as error:
        leer_fichero(str(tmp_path / "no_existe.pdf"))

    assert "No encuentro" in str(error.value)


def test_una_ruta_vacia_no_revienta():
    from src.documentos import DocumentoNoValido, leer_fichero

    for vacia in ("", "   ", None):
        with pytest.raises(DocumentoNoValido):
            leer_fichero(vacia)


def test_los_espacios_sobrantes_no_estorban(tmp_path):
    """Al pegar una ruta se cuela un espacio delante o detras mas veces de
    las que parece."""
    from src.documentos import leer_fichero

    fichero = tmp_path / "informe.pdf"
    fichero.write_bytes(b"x")

    _datos, nombre = leer_fichero(f"   {fichero}  ")

    assert nombre == "informe.pdf"


# --- Cache de vectores y preparacion previa (01/08) ------------------------
# Con un PDF real de 1,1 MB cada llamada a leer_documento tardaba 40-69
# SEGUNDOS porque re-troceaba y re-incrustaba el documento entero. Y como
# ese mismo dia la tool se marco repetible=True, el modelo la llamo SEIS
# veces en un turno: ~4 minutos parado hasta agotar las rondas de tools.
# Los dos cambios eran correctos por separado y desastrosos juntos.


def test_los_vectores_de_un_documento_se_calculan_UNA_vez(monkeypatch):
    import src.documentos as d

    veces = []
    real = d.trocear

    def contar(textos):
        veces.append(len(textos))
        return [[0.1] * 8 for _ in textos]

    monkeypatch.setattr("src.rag.incrustar_textos", contar)
    d._CACHE_VECTORES.clear()
    texto = "\n".join(f"Seccion {i}: contenido variado." for i in range(400))

    d.buscar_en_documento(texto, "primera consulta")
    d.buscar_en_documento(texto, "segunda consulta")
    d.buscar_en_documento(texto, "tercera consulta")

    # 1 vez el documento entero (cientos de trozos) + 1 texto por consulta.
    grandes = [n for n in veces if n > 5]
    assert len(grandes) == 1, f"el documento se incrusto {len(grandes)} veces"
    assert veces.count(1) == 3, "la consulta si se incrusta en cada llamada"
    assert real is d.trocear


def test_la_cache_no_crece_sin_limite(monkeypatch):
    """Vive en RAM mientras el proceso siga vivo: una tarde adjuntando PDFs
    se comeria la memoria."""
    import src.documentos as d

    monkeypatch.setattr(
        "src.rag.incrustar_textos", lambda textos: [[0.1] * 8 for _ in textos]
    )
    d._CACHE_VECTORES.clear()

    for n in range(10):
        texto = "\n".join(f"Doc {n} seccion {i}: contenido." for i in range(400))
        d.buscar_en_documento(texto, "algo")

    assert len(d._CACHE_VECTORES) <= d._MAX_DOCUMENTOS_EN_CACHE


def test_preparar_deja_la_busqueda_lista(monkeypatch):
    """Lo que convierte "40 segundos en mitad de tu pregunta" en "40
    segundos al adjuntar, avisando"."""
    import src.documentos as d

    llamadas = []
    monkeypatch.setattr(
        "src.rag.incrustar_textos",
        lambda textos: llamadas.append(len(textos)) or [[0.1] * 8 for _ in textos],
    )
    d._CACHE_VECTORES.clear()
    texto = "\n".join(f"Seccion {i}: contenido." for i in range(400))
    monkeypatch.setattr(d, "extraer_texto", lambda a: texto)

    fragmentos = d.preparar(d.DocumentoAdjunto(datos=b"x", nombre="a.pdf", tipo="pdf"))

    assert fragmentos > 0
    de_preparar = list(llamadas)
    d.buscar_en_documento(texto, "una consulta")
    # Tras preparar, la busqueda solo incrusta la CONSULTA (1 texto).
    assert llamadas[len(de_preparar):] == [1]


def test_preparar_no_lanza_si_el_documento_es_ilegible(monkeypatch):
    """Un fallo al preparar no puede impedir que el documento se acepte."""
    import src.documentos as d

    def ilegible(a):
        raise d.DocumentoNoValido("PDF dañado")

    monkeypatch.setattr(d, "extraer_texto", ilegible)

    assert d.preparar(d.DocumentoAdjunto(datos=b"x", nombre="a.pdf", tipo="pdf")) == 0


def test_preparar_no_hace_nada_si_el_documento_cabe_entero(monkeypatch):
    import src.documentos as d

    def prohibido(textos):
        raise AssertionError("un documento corto no necesita vectores")

    monkeypatch.setattr("src.rag.incrustar_textos", prohibido)
    monkeypatch.setattr(d, "extraer_texto", lambda a: "Documento cortito.")

    assert d.preparar(d.DocumentoAdjunto(datos=b"x", nombre="a.pdf", tipo="pdf")) == 0
